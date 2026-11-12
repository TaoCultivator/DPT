"""复现性核查：对已入库的全语料基线做独立重跑抽样比对。

目的：证明 ``raw/bench_full_corpus.json`` 里的吞吐数字**不是一次性产物**，
而是能在同一台机器上重跑复现的。

做法：
1. 读取已入库的 ``raw/bench_full_corpus.json``（488 条逐文件记录）；
2. 按体积分层抽取 ``--n`` 个文件（固定 ``--seed``，可复现）；
3. 用与 ``bench_full_corpus.py`` **完全相同**的测量路径逐文件重跑一次；
4. 逐文件比对 ``t_load / t_extract / t_total``，给出比值分布与汇总。

输出：``raw/verify_baseline_replication.json``（附终端摘要）。

用法（从仓库根运行）::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/replicate_baseline.py --n 24
"""
from __future__ import annotations

import json
import random
import statistics
import sys
import time
from pathlib import Path

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

BASELINE = _HERE.resolve().parents[0] / "raw" / "bench_full_corpus.json"


def _pick(files: list[Path], baseline_index: dict[str, dict], n: int, seed: int) -> list[Path]:
    """按体积分层抽样：先按体积排序，再在每个等距层里随机取一个。"""
    known = [p for p in files if _rel(p) in baseline_index]
    known.sort(key=lambda p: baseline_index[_rel(p)]["size_bytes"])
    rng = random.Random(seed)
    out: list[Path] = []
    if n >= len(known):
        return known
    width = len(known) / n
    for i in range(n):
        lo = int(i * width)
        hi = max(lo + 1, int((i + 1) * width))
        out.append(rng.choice(known[lo:hi]))
    return out


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(DEFAULT_CORPUS))
    except ValueError:
        return path.name


def main() -> int:
    n = 24
    seed = 20261015
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    if "--seed" in sys.argv:
        seed = int(sys.argv[sys.argv.index("--seed") + 1])

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    index = {r["rel"]: r for r in baseline["records"]}
    cfg = load_config()
    files = corpus_files(DEFAULT_CORPUS)
    sample = _pick(files, index, n, seed)
    print(f"baseline: {BASELINE}")
    print(f"corpus files: {len(files)}　抽样: {len(sample)}　seed={seed}")
    sys.stdout.flush()

    rows: list[dict] = []
    for i, path in enumerate(sample):
        ref = index[_rel(path)]
        t0 = time.perf_counter()
        try:
            bundle = load_waveform(path)
        except Exception as exc:  # noqa: BLE001
            rows.append({"rel": _rel(path), "error": f"load:{type(exc).__name__}:{exc}"})
            print(f"[{i + 1:2d}/{len(sample)}] LOAD-FAIL {_rel(path)}")
            sys.stdout.flush()
            continue
        t1 = time.perf_counter()
        base = guess_profile_from_path(path)
        mapping, _src = infer_best_mapping_from_bundle(bundle, base.bridge)
        t2 = time.perf_counter()
        prof = apply_mapping(base, mapping) if mapping is not None else base
        if is_short_circuit_sample(path):
            prof = as_short_circuit_profile(prof)
        t3 = time.perf_counter()
        err = ""
        try:
            if is_short_circuit_sample(path):
                extract_short_circuit(bundle, prof, cfg)
            else:
                extract_all(bundle, prof, cfg)
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}:{exc}"
        t4 = time.perf_counter()

        row = {
            "rel": _rel(path),
            "size_mb": ref["size_mb"],
            "short_circuit": is_short_circuit_sample(path),
            "n_samples": int(bundle.n),
            "error": err,
            "ref_error": ref["error"],
            "t_load": round(t1 - t0, 4),
            "t_map": round(t2 - t1, 4),
            "t_apply": round(t3 - t2, 4),
            "t_extract": round(t4 - t3, 4),
            "t_total": round(t4 - t0, 4),
            "ref_t_load": ref["t_load"],
            "ref_t_extract": ref.get("t_extract", 0.0),
            "ref_t_total": ref["t_total"],
        }
        if ref.get("t_extract"):
            row["extract_ratio"] = round(row["t_extract"] / ref["t_extract"], 3)
        row["total_ratio"] = round(row["t_total"] / ref["t_total"], 3)
        rows.append(row)
        print(
            f"[{i + 1:2d}/{len(sample)}] {path.name[:34]:34s} "
            f"extract={row['t_extract']:7.4f} (ref {row['ref_t_extract']:7.4f}, "
            f"x{row.get('extract_ratio', float('nan')):.2f}) "
            f"total={row['t_total']:7.4f} (ref {row['ref_t_total']:7.4f}, x{row['total_ratio']:.2f}) {err[:40]}"
        )
        sys.stdout.flush()

    ok_rows = [r for r in rows if "t_total" in r and not r.get("error")]
    ratios = [r["total_ratio"] for r in ok_rows]
    ex_ratios = [r["extract_ratio"] for r in ok_rows if "extract_ratio" in r]
    payload = {
        "purpose": "复现性核查：抽样重跑并与已入库全语料基线逐文件比对",
        "baseline_file": str(BASELINE),
        "seed": seed,
        "requested": n,
        "completed": len(ok_rows),
        "failed": len(rows) - len(ok_rows),
        "rows": rows,
        "summary": {
            "median_total_ratio": round(statistics.median(ratios), 3) if ratios else None,
            "min_total_ratio": round(min(ratios), 3) if ratios else None,
            "max_total_ratio": round(max(ratios), 3) if ratios else None,
            "median_extract_ratio": round(statistics.median(ex_ratios), 3) if ex_ratios else None,
            "min_extract_ratio": round(min(ex_ratios), 3) if ex_ratios else None,
            "max_extract_ratio": round(max(ex_ratios), 3) if ex_ratios else None,
            "new_sum_t_total_s": round(sum(r["t_total"] for r in ok_rows), 3),
            "ref_sum_t_total_s": round(sum(r["ref_t_total"] for r in ok_rows), 3),
            "new_sum_t_extract_s": round(sum(r["t_extract"] for r in ok_rows), 3),
            "ref_sum_t_extract_s": round(sum(r["ref_t_extract"] for r in ok_rows), 3),
        },
        "note": (
            "比值 = 本次重跑 / 已入库基线。同一机器同一天内重跑，允许 ±30% 的运行时波动；"
            "只有系统性偏离（中位比值远离 1.0）才说明基线不可复现。"
        ),
    }
    out = write_json("verify_baseline_replication.json", payload)
    print("\nsummary:", json.dumps(payload["summary"], ensure_ascii=False, indent=1))
    print("raw ->", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
