"""逐步对比原实现与向量化实现的每个窗口决策，定位分歧点。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/diagnose_plateau_step.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from _harness import ensure_repo_on_path  # noqa: E402

ensure_repo_on_path()

from dpt_extractor.metrics import plateau_level as pl  # noqa: E402


def original_windows(band, prefer):
    """复刻原实现，但返回每个 wlen 结束时的 (best_span, best_w0, best_wlen)。"""
    b = np.asarray(band, dtype=np.float64)
    n = len(b)
    v_lo = float(np.min(b))
    v_hi = float(np.max(b))
    span = max(v_hi - v_lo, 1e-9)
    dy_lim = max(0.75, 0.012 * span)
    diffs = np.abs(np.diff(b))
    wlen_hi = min(22, n)
    wlen_lo = min(10, n)
    best_span = float("inf")
    best = None
    per_wlen = {}
    for wlen in range(wlen_lo, wlen_hi + 1):
        nwin = n - wlen + 1
        if nwin < 1:
            break
        for w0 in range(nwin):
            if w0 + wlen - 2 < len(diffs):
                if float(np.max(diffs[w0 : w0 + wlen - 1])) > dy_lim:
                    continue
            sub = b[w0 : w0 + wlen]
            mu = float(np.mean(sub))
            if prefer == "low" and mu > v_lo + 0.42 * span:
                continue
            if prefer == "high" and mu < v_lo + 0.58 * span:
                continue
            s = float(np.max(sub) - np.min(sub))
            if s < best_span:
                best_span = s
                best = (w0, wlen)
        per_wlen[wlen] = (best_span, best)
    return per_wlen


def main() -> int:
    band = np.linspace(0, 5, 26)
    prefer = "low"
    print(f"band = linspace(0,5,26)  prefer={prefer}")
    print(f"原实现 = {pl._quiet_plateau_mid(band, prefer=prefer)}")

    from poc_plateau_vectorize import _quiet_plateau_mid_vectorized as vec

    print(f"向量化 = {vec(band, prefer=prefer)}\n")

    per = original_windows(band, prefer)
    print("原实现每个 wlen 的 (best_span, best(w0,wlen)):")
    for wlen, (bs, best) in per.items():
        print(f"  wlen={wlen:>2d}  best_span={bs:<20} best={best}")

    # 直接检查我的滑动均值与逐窗口均值是否一致
    b = np.asarray(band, dtype=np.float64)
    n = len(b)
    csum = np.concatenate(([0.0], np.cumsum(b)))
    print("\n滑动均值 vs np.mean 逐窗口比对（wlen=13）:")
    wlen = 13
    nwin = n - wlen + 1
    slide = (csum[wlen : wlen + nwin] - csum[:nwin]) / wlen
    worst = 0
    for w0 in range(nwin):
        direct = float(np.mean(b[w0 : w0 + wlen]))
        d = abs(slide[w0] - direct)
        worst = max(worst, d)
        if d != 0:
            print(f"  w0={w0} slide={slide[w0]!r} direct={direct!r} diff={abs(slide[w0]-direct):.3e}")
    print(f"  最大差异 = {worst:.3e}")

    print("\n守卫语义核对（wlen=13, nwin=%d）:" % nwin)
    m = wlen - 1
    k = len(b) - 1
    for w0 in range(nwin):
        active = w0 + wlen - 2 < k
        print(f"  w0={w0:>2d} w0+wlen-2={w0+wlen-2:>2d} < {k} = {active}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
