"""核查 WaveformBundle 的 n / t / 通道长度语义（测量口径校正）。

背景：全语料基线里发现少数记录报 ``n_samples = 5000000``，但缓存的单文件
剖析中 ``bundle.n = 62500``、``bundle.t.shape = (375000,)``，且 ``len(bundle.t)``
与 ``bundle.n`` 不一致。若口径混用，任何「耗时 ∝ 采样点数」的结论都会失真。

本脚本对若干真实文件打印三者关系，给出准确口径。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/check_bundle_shape.py
"""
from __future__ import annotations

import sys
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

from dpt_extractor.io.waveform_loader import load_waveform  # noqa: E402


def main() -> int:
    files = corpus_files(DEFAULT_CORPUS)
    # 按体积分层各取若干，覆盖不同采样率
    files_sorted = sorted(files, key=lambda p: p.stat().st_size)
    picks: list[Path] = []
    n = len(files_sorted)
    for frac in (0.02, 0.2, 0.4, 0.6, 0.8, 0.95, 0.995):
        picks.append(files_sorted[int(n * frac)])

    print(f"{'文件':46s} {'bundle.n':>10} {'len(t)':>10} {'dt':>12} {'通道长度':>12}")
    rows = []
    for p in picks:
        try:
            b = load_waveform(p)
        except Exception as exc:  # noqa: BLE001
            print(f"{p.name[:46]:46s}  LOAD FAIL {type(exc).__name__}")
            continue
        chans = {}
        for key in b.channels:
            arr = b.get(key)
            chans[key] = 0 if arr is None else len(arr)
        uniq = sorted(set(chans.values()))
        rows.append(
            {
                "file": p.name,
                "size_kb": round(p.stat().st_size / 1024, 1),
                "bundle_n": int(b.n),
                "len_t": len(b.t),
                "dt": b.dt,
                "t_max_us": float(b.t[-1]) * 1e6 if len(b.t) else 0.0,
                "channel_lens": chans,
                "channel_len_unique": uniq,
            }
        )
        print(
            f"{p.name[:46]:46s} {int(b.n):>10d} {len(b.t):>10d} {b.dt:>12.4e} {str(uniq):>12}"
        )

    same = all(r["bundle_n"] == r["len_t"] for r in rows)
    print(f"\nbundle.n == len(t) 对所有抽检文件成立: {same}")

    payload = {
        "picks": rows,
        "bundle_n_equals_len_t": same,
        "note": "用于校正「耗时 vs 采样点数」标度分析的口径",
    }
    out = write_json("bundle_shape_check.json", payload)
    print(f"raw -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
