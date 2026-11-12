"""性能基线 2/3：热点函数定位（cProfile）。

用法（从仓库根运行）::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/hotspots.py --n 6 --repeat 4

设计说明
--------
* 本机 **未安装 py-spy**（无法采样 ``pip`` 安装），因此采用标准库 ``cProfile``。
  ``cProfile`` 是确定性插桩剖析，对 ``tottime``（自身耗时）口径可信；
  ``cumtime`` 会受插桩开销放大，报告中两个口径都给出并注明差异。
* 采样策略：全语料按 ``size_mb`` 排序后做**分层抽样**，避免热点被单一体量文件主导。
  抽样数、重复次数与随机种子均写入 JSON，便于复现。
* 剖析范围：``load_waveform`` + 通道映射 + 参数提取（不含 GUI）。

输出：``raw/hotspots.json``。
"""
from __future__ import annotations

import argparse
import cProfile
import pstats
import random
import sys
from io import StringIO
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from _harness import (  # noqa: E402
    DEFAULT_CORPUS,
    corpus_files,
    ensure_repo_on_path,
    write_json,
)

ensure_repo_on_path()

from dpt_extractor.utils.app_paths import configure_numba_cache_dir  # noqa: E402

configure_numba_cache_dir()

from dpt_extractor.config.loader import load_config  # noqa: E402
from dpt_extractor.io.waveform_loader import load_waveform  # noqa: E402
from dpt_extractor.models.bridge_profile import (  # noqa: E402
    as_short_circuit_profile,
    guess_profile_from_path,
)
from dpt_extractor.models.channel_mapping import (  # noqa: E402
    apply_mapping,
    infer_best_mapping_from_bundle,
)
from dpt_extractor.pipeline.extract import extract_all  # noqa: E402
from dpt_extractor.pipeline.short_circuit_extract import extract_short_circuit  # noqa: E402


def _run_one(path: Path, cfg) -> str:
    """跑一个文件的完整链路，返回错误串（空串表示成功）。

    热点剖析只关心「正常路径的耗时分布」，因此失败的样例跳过而不中断整轮。
    """
    short = _is_short(path)
    try:
        bundle = load_waveform(path)
    except Exception as exc:  # noqa: BLE001
        return f"load:{type(exc).__name__}"
    try:
        base = guess_profile_from_path(path)
        mapping, _src = infer_best_mapping_from_bundle(bundle, base.bridge)
        prof = apply_mapping(base, mapping) if mapping is not None else base
        if short:
            prof = as_short_circuit_profile(prof)
            extract_short_circuit(bundle, prof, cfg)
        else:
            extract_all(bundle, prof, cfg)
    except Exception as exc:  # noqa: BLE001
        return f"extract:{type(exc).__name__}"
    return ""


def _is_short(path: Path) -> bool:
    from _harness import is_short_circuit_sample

    return is_short_circuit_sample(path)


def _stratified(paths: list[Path], n: int, seed: int) -> list[Path]:
    """按体积分层抽样：小/中/大各取 1/3，层内随机。"""
    ordered = sorted(paths, key=lambda p: p.stat().st_size)
    third = max(1, len(ordered) // 3)
    strata = [ordered[:third], ordered[third : 2 * third], ordered[2 * third :]]
    rng = random.Random(seed)
    per = max(1, n // 3)
    picked: list[Path] = []
    for stratum in strata:
        pool = list(stratum)
        rng.shuffle(pool)
        picked.extend(pool[:per])
    return picked[:n]


def _flatten(stats: pstats.Stats, repo_root: Path) -> list[dict]:
    """把 pstats 原始元组摊平成可读记录。"""
    rows = []
    for (filename, lineno, funcname), (cc, nc, tt, ct, _callers) in stats.stats.items():
        try:
            rel = str(Path(filename).resolve().relative_to(repo_root))
        except (ValueError, OSError):
            rel = filename
        rows.append(
            {
                "file": rel.replace("\\", "/"),
                "line": lineno,
                "func": funcname,
                "tottime": tt,
                "cumtime": ct,
                "ncalls": nc,
                "primitive_calls": cc,
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6, help="分层抽样的文件数")
    ap.add_argument("--repeat", type=int, default=4, help="同一批文件重复轮数")
    ap.add_argument("--seed", type=int, default=20261015)
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    files = corpus_files(DEFAULT_CORPUS)
    picked = _stratified(files, args.n, args.seed)
    cfg = load_config()

    print(f"corpus files: {len(files)}  sampled: {len(picked)}  repeat: {args.repeat}")
    for p in picked:
        print(f"  sample {p.stat().st_size/1024:9.1f} KB  {p.name}")
    sys.stdout.flush()

    # 预热：触发 numba 缓存与 numpy 导入，避免把冷启动算进热点
    _run_one(picked[0], cfg)

    pr = cProfile.Profile()
    pr.enable()
    for _ in range(args.repeat):
        for path in picked:
            _run_one(path, cfg)
    pr.disable()

    buf = StringIO()
    stats = pstats.Stats(pr, stream=buf)
    stats.sort_stats("tottime")

    rows = _flatten(stats, repo_root)
    total_tt = sum(r["tottime"] for r in rows) or 1.0

    # 只保留本项目代码 + 少量第三方热点，便于阅读
    def _is_project(rel: str) -> bool:
        return "dpt_extractor" in rel

    project = [r for r in rows if _is_project(r["file"])]
    project.sort(key=lambda r: r["tottime"], reverse=True)
    overall = sorted(rows, key=lambda r: r["tottime"], reverse=True)

    top_all = []
    for r in overall[:40]:
        r = dict(r)
        r["share_of_total_tt"] = round(r["tottime"] / total_tt, 5)
        top_all.append(r)

    top_project = []
    project_tt = sum(r["tottime"] for r in project) or 1.0
    for r in project[:40]:
        r = dict(r)
        r["share_of_project_tt"] = round(r["tottime"] / project_tt, 5)
        r["share_of_total_tt"] = round(r["tottime"] / total_tt, 5)
        top_project.append(r)

    payload = {
        "meta": {
            "method": "cProfile deterministic profiling",
            "pyspy_available": False,
            "pyspy_note": "本机未安装 py-spy（无 cargo/rustc，pip 安装未授权），改用 cProfile",
            "corpus_files": len(files),
            "sampled_files": [str(p) for p in picked],
            "repeat": args.repeat,
            "seed": args.seed,
            "profiled_rounds": args.repeat * len(picked),
            "total_tottime_s": round(total_tt, 4),
            "project_tottime_s": round(project_tt, 4),
        },
        "top_project_by_tottime": top_project,
        "top_all_by_tottime": top_all,
    }
    out = write_json("hotspots.json", payload)

    print("\n=== TOP 20 本项目热点（按自身耗时 tottime）===")
    print(f"{'file:line':52s} {'func':38s} {'tottime':>9s} {'ncalls':>8s} {'占项目':>7s}")
    for r in top_project[:20]:
        where = f"{r['file'].split('dpt_extractor/')[-1]}:{r['line']}"
        print(
            f"{where[:52]:52s} {r['func'][:38]:38s} "
            f"{r['tottime']:9.3f} {r['ncalls']:8d} {r['share_of_project_tt']*100:6.2f}%"
        )
    print(f"\nraw -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
