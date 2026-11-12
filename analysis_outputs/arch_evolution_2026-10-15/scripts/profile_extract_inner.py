"""性能基线 2c：单个参数提取内部的成本构成（按「成本种类」归类）。

目的：回答「热点到底是什么类型」，为「哪类改动真的有效」提供判据：
  * numpy ufunc / 数组运算（可 Rust+SIMD 或更优的向量化提速）
  * 数组拷贝 / 切片 / fancy-index（可由零拷贝或 Rust 侧所有权模型消除）
  * Python 字节码 / 纯标量循环（受 GIL 与解释器开销限制，Rust 收益最大）
  * 排序 / 搜索（np.searchsorted、argmax…）
  * 其他

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/profile_extract_inner.py
"""
from __future__ import annotations

import cProfile
import os
import pstats
import sys
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from _harness import (  # noqa: E402
    DEFAULT_CORPUS,
    corpus_files,
    ensure_repo_on_path,
    is_short_circuit_sample,
    write_json,
)

ensure_repo_on_path()

from dpt_extractor.utils.app_paths import configure_numba_cache_dir  # noqa: E402

configure_numba_cache_dir()

from dpt_extractor.config.loader import load_config  # noqa: E402
from dpt_extractor.io.waveform_loader import load_waveform  # noqa: E402
from dpt_extractor.models.bridge_profile import guess_profile_from_path  # noqa: E402
from dpt_extractor.models.channel_mapping import (  # noqa: E402
    apply_mapping,
    infer_best_mapping_from_bundle,
)
from dpt_extractor.pipeline.extract import extract_all  # noqa: E402

# ---------------------------------------------------------------- 成本归类

_NUMPY_MODULES = ("numpy",)


def _classify(file: str, func: str) -> str:
    p = file.replace("\\", "/")
    if "dpt_extractor" in p:
        return "本项目代码"
    if "/numpy/" in p or p.startswith("numpy"):
        if any(k in func for k in ("copy", "array", "asarray", "empty", "zeros", "full")):
            return "numpy: 分配/拷贝"
        if any(k in func for k in ("sort", "argsort", "searchsorted", "argmax", "argmin",
                                   "nonzero", "where", "partition")):
            return "numpy: 排序/搜索"
        if any(k in func for k in ("add", "subtract", "multiply", "divide", "true_divide",
                                   "maximum", "minimum", "clip", "abs", "negative", "sqrt",
                                   "power", "exp", "log", "convolve", "cumsum", "trapz")):
            return "numpy: 算术/ufunc"
        if any(k in func for k in ("take", "put", "compress", "getitem", "slice",
                                   "concatenate", "stack", "reshape", "transpose",
                                   "ravel", "flatten", "ascontiguousarray")):
            return "numpy: 索引/形状"
        return "numpy: 其他"
    if "/scipy/" in p or p.startswith("scipy"):
        return "scipy"
    if "/numba/" in p or p.startswith("numba"):
        return "numba(JIT)"
    if "built-in" in p or p.startswith("<"):
        return "Python 内建/字节码"
    return "第三方其他"


def main() -> int:
    files = [p for p in corpus_files(DEFAULT_CORPUS) if not is_short_circuit_sample(p)]
    files.sort(key=lambda p: p.stat().st_size)
    sample = files[len(files) // 2]
    print(f"sample: {sample.name}  ({sample.stat().st_size/1024:.1f} KB)")

    cfg = load_config()
    bundle = load_waveform(sample)
    base = guess_profile_from_path(sample)
    mapping, src = infer_best_mapping_from_bundle(bundle, base.bridge)
    prof = apply_mapping(base, mapping) if mapping is not None else base
    print(f"channels: {bundle.channels}  n={bundle.n}  mapping={src}")
    sys.stdout.flush()

    # 预热：先跑一次，排除 numba 编译与首次惰性导入
    for _ in range(2):
        extract_all(bundle, prof, cfg)

    pr = cProfile.Profile()
    pr.enable()
    for _ in range(10):
        extract_all(bundle, prof, cfg)
    pr.disable()

    stats = pstats.Stats(pr)
    rows = []
    for (fn, ln, func), (cc, nc, tt, ct, _c) in stats.stats.items():
        rows.append(
            {
                "file": fn.replace("\\", "/"),
                "line": ln,
                "func": func,
                "tottime_ms": tt * 1000 / 10,
                "ncalls_per_run": nc / 10,
                "kind": _classify(fn, func),
            }
        )

    by_kind: dict[str, float] = defaultdict(float)
    for r in rows:
        by_kind[r["kind"]] += r["tottime_ms"]
    total = sum(by_kind.values()) or 1.0
    kind_share = sorted(
        (
            {"kind": k, "tottime_ms": round(v, 3), "share": round(v / total, 4)}
            for k, v in by_kind.items()
        ),
        key=lambda r: r["tottime_ms"],
        reverse=True,
    )

    project = sorted(
        [r for r in rows if "dpt_extractor" in r["file"]],
        key=lambda r: r["tottime_ms"],
        reverse=True,
    )[:25]
    for r in project:
        r["file"] = r["file"].split("dpt_extractor/")[-1]
        r["tottime_ms"] = round(r["tottime_ms"], 3)
        r["ncalls_per_run"] = round(r["ncalls_per_run"], 1)

    # 纯 Python 解释器开销：所有 <built-in> 与项目自身字节码
    python_floor = sum(
        r["tottime_ms"]
        for r in rows
        if r["kind"] in ("本项目代码", "Python 内建/字节码")
    )

    payload = {
        "meta": {
            "sample": str(sample),
            "sample_kb": round(sample.stat().st_size / 1024, 1),
            "n_samples": int(bundle.n),
            "n_channels": len(bundle.channels),
            "mapping_source": src,
            "repeat": 10,
            "note": "已预热 2 次，排除 numba 编译；单次 extract_all 平均耗时",
        },
        "total_tottime_ms_per_run": round(total, 3),
        "by_kind": kind_share,
        "project_top25": project,
        "python_side_tottime_ms_per_run": round(python_floor, 3),
        "python_side_share": round(python_floor / total, 4),
    }
    out = write_json("profile_extract_inner.json", payload)

    print(f"\n单次 extract_all 插桩总耗时（各函数自身耗时之和）: {total:.1f} ms/run")
    print("\n按成本种类：")
    for r in kind_share:
        bar = "#" * max(1, int(r["share"] * 50))
        print(f"  {r['kind']:22s} {r['tottime_ms']:9.2f} ms  {r['share']*100:5.1f}%  {bar}")
    print(f"\n  Python 侧（项目字节码 + 解释器内建）合计占比: {python_floor/total*100:.1f}%")
    print("\n项目内热点 Top15：")
    for r in project[:15]:
        print(f"  {r['file']}:{r['line']} {r['func'][:34]:34s} {r['tottime_ms']:8.2f} ms  调用 {r['ncalls_per_run']:>7.0f}/次")
    print(f"\nraw -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
