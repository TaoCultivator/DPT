"""PoC-3：批处理多进程并行 —— 实测加速比（只用标准库 ProcessPoolExecutor）。

背景
----
`check_cpu_bound.py` 实测提取阶段 **CPU/墙钟 = 0.977**，属纯 CPU 受限，
本机 16 逻辑核 → 多进程并行理论上可接近线性扩展。

本脚本在同一批文件上对比「串行」与「多进程并行」的墙钟耗时，
给出**实测**加速比，作为 P2 阶段（批处理并行）的可行性证据。

限定与诚实说明
--------------
* 本脚本**不修改** GUI 路径，也不接入生产流程；只是独立基准。
* 并行度受限因素：进程启动开销、numba 缓存目录竞争、内存带宽。
  因此实测值必然**低于**核数，报告里给出实测值而不是理论值。
* Windows 使用 spawn 语义，每个子进程都要重新导入 numpy/包，
  启动开销会明显压低小批次的加速比——这正是本脚本要暴露的事实。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/poc_parallel_speedup.py
"""
from __future__ import annotations

import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
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


def _extract_one(path_str: str) -> tuple[str, float, str]:
    """子进程工作单元：装载 + 提取一个文件，返回 (路径, 秒, 错误)。

    必须放在模块顶层，Windows spawn 才能 pickle。
    """
    t0 = time.perf_counter()
    try:
        from dpt_extractor.utils.app_paths import configure_numba_cache_dir

        configure_numba_cache_dir()

        from dpt_extractor.config.loader import load_config
        from dpt_extractor.io.waveform_loader import load_waveform
        from dpt_extractor.models.bridge_profile import (
            as_short_circuit_profile,
            guess_profile_from_path,
        )
        from dpt_extractor.models.channel_mapping import (
            apply_mapping,
            infer_best_mapping_from_bundle,
        )
        from dpt_extractor.pipeline.extract import extract_all
        from dpt_extractor.pipeline.short_circuit_extract import extract_short_circuit

        path = Path(path_str)
        cfg = load_config()
        bundle = load_waveform(path)
        base = guess_profile_from_path(path)
        mapping, _src = infer_best_mapping_from_bundle(bundle, base.bridge)
        prof = apply_mapping(base, mapping) if mapping is not None else base
        if _is_short(path):
            prof = as_short_circuit_profile(prof)
            extract_short_circuit(bundle, prof, cfg)
        else:
            extract_all(bundle, prof, cfg)
        return path_str, time.perf_counter() - t0, ""
    except Exception as exc:  # noqa: BLE001
        return path_str, time.perf_counter() - t0, f"{type(exc).__name__}:{exc}"


def _is_short(path: Path) -> bool:
    from _harness import is_short_circuit_sample

    return is_short_circuit_sample(path)


def _pick(files: list[Path], want: int) -> list[Path]:
    """优先挑双脉冲样例（占耗时 89%，是 P2 的真实目标场景）。"""
    dual = [p for p in files if not is_short_circuit_sample(p)]
    dual.sort(key=lambda p: p.stat().st_size)
    if len(dual) <= want:
        return dual
    step = max(1, len(dual) // want)
    return [dual[i * step] for i in range(want)]


def main() -> int:
    # 必须：Windows spawn 下让子进程能 import 到本脚本所在目录
    os.environ.setdefault("PYTHONPATH", str(_HERE.parents[2]))

    files = _pick(corpus_files(DEFAULT_CORPUS), 24)
    paths = [str(p) for p in files]
    cores = os.cpu_count() or 1

    print(f"文件数: {len(paths)}   逻辑核数: {cores}")
    print("（全部为双脉冲样例，对应耗时占比 89% 的真实场景）\n")

    # --- 预热：先把 numba 缓存与 import 成本付掉，避免污染串行基准 ---
    _extract_one(paths[0])

    # --- 串行 ---
    t0 = time.perf_counter()
    serial_errs = 0
    for p in paths:
        _, _, err = _extract_one(p)
        serial_errs += 1 if err else 0
    serial = time.perf_counter() - t0
    print(f"串行      : {serial:7.2f}s   失败 {serial_errs}")

    results: dict[str, dict] = {
        "files": len(paths),
        "cpu_count": cores,
        "serial_s": round(serial, 3),
        "serial_failed": serial_errs,
        "parallel": {},
    }

    for workers in (2, 4, 8, 12):
        t0 = time.perf_counter()
        errs = 0
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for _p, _s, err in ex.map(_extract_one, paths):
                errs += 1 if err else 0
        elapsed = time.perf_counter() - t0
        speedup = serial / elapsed if elapsed else 0.0
        results["parallel"][str(workers)] = {
            "wall_s": round(elapsed, 3),
            "speedup": round(speedup, 3),
            "efficiency": round(speedup / workers, 4),
            "failed": errs,
        }
        print(
            f"并行 {workers:>2d} 进程: {elapsed:7.2f}s   加速 {speedup:5.2f}x   "
            f"效率 {speedup/workers*100:5.1f}%   失败 {errs}"
        )
        sys.stdout.flush()

    best = max(
        results["parallel"].items(), key=lambda kv: kv[1]["speedup"], default=None
    )
    if best:
        results["best"] = {"workers": int(best[0]), **best[1]}

    print("\n== 结论 ==")
    if best:
        print(f"  最佳并行度 {best[0]} 进程，实测加速 {best[1]['speedup']}x，"
              f"并行效率 {best[1]['efficiency']*100:.1f}%")
        print(f"  理论核数上限 {cores}x，实测/理论 = {best[1]['speedup']/cores*100:.1f}%")
        print("  差距来自进程启动（Windows spawn）、numba 缓存竞争与内存带宽。")

    out = write_json("poc_parallel_speedup.json", results)
    print(f"\nraw -> {out}")
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
