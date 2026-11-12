"""性能基线 1/3：解析与参数提取吞吐（全语料）。

用法（从仓库根运行）::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/bench_full_corpus.py

测量口径：

* ``read_zip``   —— 打开 ``.tss``（zip 容器）并读取 ``manifest.json`` 成员列表
* ``load``       —— ``load_waveform()``：包含内层 ``.wfm`` 解析（第三方 ``tm_data_types``）
* ``map``        —— 通道映射推断 ``infer_best_mapping_from_bundle``
* ``extract``    —— ``extract_all`` / ``extract_short_circuit``，即参数提取
* ``total``      —— 单文件端到端（load + map + extract）

输出：``raw/bench_full_corpus.json``（逐文件原始数据）与终端汇总。
"""
from __future__ import annotations

import json
import statistics
import sys
import time
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from _harness import (  # noqa: E402
    DEFAULT_CORPUS,
    corpus_files,
    ensure_repo_on_path,
    human_mb,
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


def _zip_member_count(path: Path) -> int:
    try:
        with zipfile.ZipFile(path) as zf:
            return len(zf.namelist())
    except Exception:  # noqa: BLE001
        return -1


def _rows_of(result) -> int:
    if result is None:
        return 0
    total = 0
    for attr in ("turn_off", "turn_on", "reverse_recovery", "short_circuit"):
        obj = getattr(result, attr, None)
        if obj is None:
            continue
        if hasattr(obj, "__dataclass_fields__"):
            total += len(obj.__dataclass_fields__)
    return total


def main() -> int:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    files = corpus_files(DEFAULT_CORPUS)
    if limit is not None:
        files = files[:limit]

    cfg = load_config()
    print(f"corpus: {DEFAULT_CORPUS}")
    print(f"files: {len(files)}")
    print(f"config mode: {cfg.test_mode.mode}")
    sys.stdout.flush()

    records: list[dict] = []
    cold_start = None

    for index, path in enumerate(files):
        size_bytes = path.stat().st_size
        rec: dict = {
            "index": index,
            "path": str(path),
            "rel": str(path.relative_to(DEFAULT_CORPUS)) if DEFAULT_CORPUS in path.parents else path.name,
            "size_bytes": size_bytes,
            "size_mb": human_mb(size_bytes),
            "zip_members": _zip_member_count(path),
            "short_circuit": is_short_circuit_sample(path),
            "error": "",
        }

        t0 = time.perf_counter()
        try:
            bundle = load_waveform(path)
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"load:{type(exc).__name__}:{exc}"
            rec["t_load"] = time.perf_counter() - t0
            records.append(rec)
            print(f"[{index:3d}/{len(files)}] LOAD-FAIL {path.name}: {rec['error'][:70]}")
            sys.stdout.flush()
            continue
        t1 = time.perf_counter()

        base = guess_profile_from_path(path)
        mapping, mapping_src = infer_best_mapping_from_bundle(bundle, base.bridge)
        t2 = time.perf_counter()

        prof = apply_mapping(base, mapping) if mapping is not None else base
        if is_short_circuit_sample(path):
            prof = as_short_circuit_profile(prof)
        t3 = time.perf_counter()

        try:
            if is_short_circuit_sample(path):
                result = extract_short_circuit(bundle, prof, cfg)
            else:
                result = extract_all(bundle, prof, cfg)
            rec["param_fields"] = _rows_of(result)
        except Exception as exc:  # noqa: BLE001
            result = None
            rec["error"] = f"extract:{type(exc).__name__}:{exc}"
        t4 = time.perf_counter()

        rec.update(
            {
                "t_load": t1 - t0,
                "t_map": t2 - t1,
                "t_apply": t3 - t2,
                "t_extract": t4 - t3,
                "t_total": t4 - t0,
                "mapping_source": mapping_src,
                "bridge": prof.bridge,
                "phase": prof.phase,
                "n_samples": int(bundle.n),
                "n_channels": len(bundle.channels),
                "dt": bundle.dt,
            }
        )
        if index == 0:
            cold_start = t1 - t0
        records.append(rec)
        print(
            f"[{index:3d}/{len(files)}] {path.name[:40]:40s} "
            f"load={rec['t_load']:7.4f} map={rec['t_map']:6.4f} "
            f"extract={rec['t_extract']:7.4f} total={rec['t_total']:7.4f} "
            f"{rec['error'][:45]}"
        )
        sys.stdout.flush()

    ok = [r for r in records if not r["error"]]
    failed = [r for r in records if r["error"]]
    total_mb = sum(r["size_bytes"] for r in ok) / 1024 / 1024

    def _stats(key: str, rows: list[dict]) -> dict:
        vals = sorted(r[key] for r in rows if key in r)
        if not vals:
            return {}
        return {
            "sum_s": round(sum(vals), 4),
            "mean_s": round(statistics.fmean(vals), 5),
            "median_s": round(statistics.median(vals), 5),
            "p95_s": round(vals[int(len(vals) * 0.95) - 1] if len(vals) > 1 else vals[0], 5),
            "max_s": round(vals[-1], 5),
        }

    summary = {
        "corpus": str(DEFAULT_CORPUS),
        "files_total": len(records),
        "files_ok": len(ok),
        "files_failed": len(failed),
        "total_mb_ok": round(total_mb, 2),
        "cold_start_load_s": round(cold_start, 4) if cold_start else None,
        "sum_t_load_s": round(sum(r["t_load"] for r in ok), 3),
        "sum_t_map_s": round(sum(r["t_map"] for r in ok), 3),
        "sum_t_extract_s": round(sum(r["t_extract"] for r in ok), 3),
        "sum_t_total_s": round(sum(r["t_total"] for r in ok), 3),
        "throughput_files_per_s": round(len(ok) / sum(r["t_total"] for r in ok), 3),
        "throughput_mb_per_s": round(total_mb / sum(r["t_total"] for r in ok), 3),
        "extract_share_of_total": round(
            sum(r["t_extract"] for r in ok) / sum(r["t_total"] for r in ok), 4
        ),
        "load_share_of_total": round(
            sum(r["t_load"] for r in ok) / sum(r["t_total"] for r in ok), 4
        ),
        "stats": {
            "load": _stats("t_load", ok),
            "map": _stats("t_map", ok),
            "extract": _stats("t_extract", ok),
            "total": _stats("t_total", ok),
        },
        "error_kinds": {},
    }
    kinds: dict[str, int] = {}
    for r in failed:
        head = ":".join(r["error"].split(":")[:2])
        kinds[head] = kinds.get(head, 0) + 1
    summary["error_kinds"] = kinds

    payload = {"summary": summary, "records": records}
    out = write_json("bench_full_corpus.json", payload)

    print("\n================ SUMMARY ================")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nraw -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
