"""性能基线 2b/3：py-spy 采样剖析的目标工作负载。

本身不产出报告，只做「被采样进程」。由 ``run_pyspy.ps1`` 用 py-spy 包住运行。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/pyspy_workload.py --rounds 3
"""
from __future__ import annotations

import argparse
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--take", type=int, default=40, help="每轮取前 N 个语料文件")
    args = ap.parse_args()

    files = corpus_files(DEFAULT_CORPUS)[: args.take]
    cfg = load_config()

    # 预热，避免把 numba 冷启动采进样本
    load_waveform(files[0])

    started = time.perf_counter()
    n = 0
    for _ in range(args.rounds):
        for path in files:
            bundle = load_waveform(path)
            base = guess_profile_from_path(path)
            mapping, _src = infer_best_mapping_from_bundle(bundle, base.bridge)
            prof = apply_mapping(base, mapping) if mapping is not None else base
            if is_short_circuit_sample(path):
                extract_short_circuit(bundle, as_short_circuit_profile(prof), cfg)
            else:
                extract_all(bundle, prof, cfg)
            n += 1
    elapsed = time.perf_counter() - started
    print(f"workload done: {n} extractions in {elapsed:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
