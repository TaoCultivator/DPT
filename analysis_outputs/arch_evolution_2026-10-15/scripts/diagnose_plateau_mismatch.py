"""定位 PoC-2 在退化输入上的 3 例不一致（n=26 单调 low）。

用途：把模糊测试发现的差异缩小到具体的守卫条件，确认是**我的向量化错了**
还是**原实现的行为本身有分支**。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/diagnose_plateau_mismatch.py
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
from poc_plateau_vectorize import _quiet_plateau_mid_vectorized as vec  # noqa: E402


def trace(band: np.ndarray, prefer: str) -> None:
    """逐窗口打印原实现的决策过程，复现守卫分支。"""
    b = np.asarray(band, dtype=np.float64)
    n = len(b)
    v_lo = float(np.min(b))
    v_hi = float(np.max(b))
    span = max(v_hi - v_lo, 1e-9)
    dy_lim = max(0.75, 0.012 * span)
    diffs = np.abs(np.diff(b))
    wlen_hi = min(22, n)
    wlen_lo = min(10, n)

    print(f"  n={n} span={span:.4f} dy_lim={dy_lim:.4f} len(diffs)={len(diffs)}")
    print(f"  v_lo={v_lo:.4f} v_hi={v_hi:.4f}")
    lo_bound = v_lo + 0.42 * span if prefer == "low" else None
    print(f"  prefer={prefer} lo_bound={lo_bound}")

    best_span = float("inf")
    best_sub = b
    for wlen in range(wlen_lo, wlen_hi + 1):
        nwin = n - wlen + 1
        if nwin < 1:
            break
        checked = 0
        passed_guard = 0
        for w0 in range(nwin):
            guard_active = w0 + wlen - 2 < len(diffs)
            if guard_active:
                checked += 1
                if float(np.max(diffs[w0 : w0 + wlen - 1])) > dy_lim:
                    continue
            else:
                passed_guard += 1
            sub = b[w0 : w0 + wlen]
            mu = float(np.mean(sub))
            if prefer == "low" and mu > lo_bound:
                continue
            s = float(np.max(sub) - np.min(sub))
            if s < best_span:
                best_span = s
                best_sub = sub
        print(
            f"    wlen={wlen:>2d} nwin={nwin:>2d} 守卫生效={checked:>2d} "
            f"守卫失效(视为通过)={passed_guard:>2d} 当前best_span={best_span}"
        )
    print(f"  -> best_span={best_span} best_sub[0:3]={best_sub[:3]} "
          f"max={np.max(best_sub):.4f} min={np.min(best_sub):.4f} "
          f"result={pl.plateau_mid(best_sub)}")
    print(f"  原实现返回   = {pl._quiet_plateau_mid(b, prefer=prefer)}")
    print(f"  向量化返回   = {vec(b, prefer=prefer)}")


def main() -> int:
    # 复现模糊测试里 kind==2（linspace(0,5,n)）且 n=26、prefer=low 的用例
    rng = np.random.default_rng(20261015)
    # 重放 fuzz 序列以精确命中 round 156
    found = 0
    for i in range(4000):
        n = int(rng.integers(1, 130))
        kind = i % 7
        if kind == 0:
            band = rng.normal(0, 1, n)
        elif kind == 1:
            band = np.full(n, float(rng.integers(-3, 4)))
        elif kind == 2:
            band = np.linspace(0, 5, n)
        elif kind == 3:
            band = np.zeros(n)
            if n > 2:
                band[rng.integers(0, n)] = 50.0
        elif kind == 4:
            band = rng.normal(0, 0.001, n)
        elif kind == 5:
            band = rng.integers(0, 2, n).astype(np.float64)
        else:
            band = rng.normal(0, 1, n)
            if n > 3 and rng.random() < 0.5:
                band[rng.integers(0, n)] = np.nan
        prefer = ["low", "high", "none"][i % 3]
        if i in (156, 2697, 3936):
            a = pl._quiet_plateau_mid(band, prefer=prefer)
            bb = vec(band, prefer=prefer)
            print(f"\n=== round {i}: n={n} kind={kind} prefer={prefer} "
                  f"original={a} vectorized={bb} ===")
            trace(band, prefer)
            found += 1
    if not found:
        print("未复现到目标轮次")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
