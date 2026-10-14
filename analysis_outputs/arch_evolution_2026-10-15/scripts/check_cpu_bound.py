"""判定参数提取是 **CPU 受限** 还是 **I/O / 等待受限**。

为什么重要
----------
P2 阶段（批处理多进程并行）的收益完全取决于这一点：
  * 若 ``CPU时间 / 墙钟时间 ≈ 1`` → 单线程跑满一核，纯 CPU 受限，
    多进程并行可接近线性扩展（本机 16 逻辑核）。
  * 若该比值远小于 1 → 有大量 I/O 或等待，加进程收益有限。

测量方式：对同一批文件分别在单文件循环里跑，记录
``time.process_time()``（CPU 时间）与 ``time.perf_counter()``（墙钟时间）。
``process_time`` 只统计 CPU 时间，不含 I/O 等待与 sleep。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/check_cpu_bound.py
"""
from __future__ import annotations

import os
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


def _pick(files: list[Path], want: int) -> list[Path]:
    """优先挑双脉冲样例 —— 它们才是耗时的 89%（对应 P2 的目标场景）。"""
    dual = [p for p in files if not is_short_circuit_sample(p)]
    dual.sort(key=lambda p: p.stat().st_size)
    if len(dual) <= want:
        return dual
    step = len(dual) // want
    return [dual[i * step] for i in range(want)]


def main() -> int:
    files = _pick(corpus_files(DEFAULT_CORPUS), 24)
    cfg = load_config()

    # 预热：排除 numba 编译与惰性导入
    load_waveform(files[0])

    cpu_load = 0.0
    wall_load = 0.0
    cpu_extract = 0.0
    wall_extract = 0.0
    ok = 0
    failed = 0

    for path in files:
        c0, w0 = time.process_time(), time.perf_counter()
        try:
            bundle = load_waveform(path)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        c1, w1 = time.process_time(), time.perf_counter()

        try:
            base = guess_profile_from_path(path)
            mapping, _src = infer_best_mapping_from_bundle(bundle, base.bridge)
            prof = apply_mapping(base, mapping) if mapping is not None else base
            if is_short_circuit_sample(path):
                prof = as_short_circuit_profile(prof)
                extract_short_circuit(bundle, prof, cfg)
            else:
                extract_all(bundle, prof, cfg)
            ok += 1
        except Exception:  # noqa: BLE001
            failed += 1
        c2, w2 = time.process_time(), time.perf_counter()

        cpu_load += c1 - c0
        wall_load += w1 - w0
        cpu_extract += c2 - c1
        wall_extract += w2 - w1

    total_cpu = cpu_load + cpu_extract
    total_wall = wall_load + wall_extract
    cores = os.cpu_count() or 1

    result = {
        "files_ok": ok,
        "files_failed": failed,
        "cpu_count": cores,
        "load": {
            "cpu_s": round(cpu_load, 3),
            "wall_s": round(wall_load, 3),
            "ratio": round(cpu_load / wall_load, 4) if wall_load else None,
        },
        "extract": {
            "cpu_s": round(cpu_extract, 3),
            "wall_s": round(wall_extract, 3),
            "ratio": round(cpu_extract / wall_extract, 4) if wall_extract else None,
        },
        "total": {
            "cpu_s": round(total_cpu, 3),
            "wall_s": round(total_wall, 3),
            "ratio": round(total_cpu / total_wall, 4) if total_wall else None,
        },
    }

    # 16 核理想上限（Amdahl 简化：假设并行开销可忽略）
    ratio = total_cpu / total_wall if total_wall else 0
    result["ideal_speedup_ceiling"] = round(min(cores, ratio * cores), 2)
    result["note"] = (
        "cpu/wall ≈ 1 表示单线程跑满一核，属纯 CPU 受限；"
        "上限按 min(核数, ratio×核数) 估算，未计进程启动与内存带宽折损"
    )

    print("== 参数提取 CPU/墙钟 比值 ==")
    print(f"  文件数      : {ok} ok / {failed} failed")
    print(f"  逻辑核数    : {cores}")
    print(f"  装载   CPU={result['load']['cpu_s']:8.3f}s  wall={result['load']['wall_s']:8.3f}s  "
          f"比值={result['load']['ratio']}")
    print(f"  提取   CPU={result['extract']['cpu_s']:8.3f}s  wall={result['extract']['wall_s']:8.3f}s  "
          f"比值={result['extract']['ratio']}")
    print(f"  合计   CPU={result['total']['cpu_s']:8.3f}s  wall={result['total']['wall_s']:8.3f}s  "
          f"比值={result['total']['ratio']}")
    print(f"\n  并行理论加速上限 ≈ {result['ideal_speedup_ceiling']}x")

    if ratio >= 0.9:
        print("  判读：比值 >= 0.9 → **纯 CPU 受限**，多进程并行收益接近线性，P2 值得做。")
    elif ratio >= 0.6:
        print("  判读：比值 0.6~0.9 → 部分等待，并行仍有明显收益但需实测标定。")
    else:
        print("  判读：比值 < 0.6 → 存在大量 I/O 或等待，**优先查 I/O 而不是加进程**。")

    out = write_json("cpu_bound_check.json", result)
    print(f"\nraw -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
