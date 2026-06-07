from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter1d


def window_samples(dt: float, window_ns: float) -> int:
    n = int(round(window_ns * 1e-9 / dt))
    return max(3, n | 1)


def smooth(y: np.ndarray, dt: float, window_ns: float) -> np.ndarray:
    w = window_samples(dt, window_ns)
    return uniform_filter1d(y.astype(np.float64), size=w, mode="nearest")


def derivative(y: np.ndarray, dt: float) -> np.ndarray:
    return np.gradient(y.astype(np.float64), dt)


def threshold_value(low: float, high: float, pct: float) -> float:
    return low + pct * (high - low)


def crossing_time(
    t: np.ndarray,
    y: np.ndarray,
    threshold: float,
    direction: str = "falling",
    start: int = 0,
) -> float | None:
    """Linear interpolation crossing time; search from `start` (local index)."""
    y = y.astype(np.float64)
    if start > 0:
        y = y[start:]
        t = t[start:]
    if len(y) < 2:
        return None
    if direction == "falling":
        idx = np.where((y[:-1] >= threshold) & (y[1:] < threshold))[0]
    elif direction == "rising":
        idx = np.where((y[:-1] <= threshold) & (y[1:] > threshold))[0]
    else:
        raise ValueError(direction)
    if len(idx) == 0:
        return None
    i = int(idx[0])
    y0, y1 = y[i], y[i + 1]
    if abs(y1 - y0) < 1e-30:
        return float(t[i])
    frac = (threshold - y0) / (y1 - y0)
    return float(t[i] + frac * (t[i + 1] - t[i]))


def crossing_index(
    y: np.ndarray,
    threshold: float,
    direction: str = "falling",
    start: int = 0,
    end: int | None = None,
    last: bool = False,
) -> int | None:
    """Sample index of first (or last) threshold crossing."""
    if end is None:
        end = len(y)
    seg = y[start:end]
    if len(seg) < 2:
        return None
    if direction == "falling":
        hits = np.where((seg[:-1] >= threshold) & (seg[1:] < threshold))[0]
    else:
        hits = np.where((seg[:-1] <= threshold) & (seg[1:] > threshold))[0]
    if len(hits) == 0:
        return None
    i = int(hits[-1] if last else hits[0])
    y0, y1 = seg[i], seg[i + 1]
    if abs(y1 - y0) < 1e-30:
        return start + i
    frac = (threshold - y0) / (y1 - y0)
    return start + i + int(round(frac))


def slope_between_crossings(
    t: np.ndarray,
    y: np.ndarray,
    th1: float,
    th2: float,
    dir1: str,
    dir2: str,
    i0: int,
    i1: int,
) -> float:
    """Average slope between two crossings (returns SI units per second)."""
    seg_t = t[i0:i1]
    seg_y = y[i0:i1]
    t_a = crossing_time(seg_t, seg_y, th1, dir1)
    t_b = crossing_time(seg_t, seg_y, th2, dir2, start=0)
    if t_a is None or t_b is None:
        return 0.0
    dt_s = t_b - t_a
    if abs(dt_s) < 1e-15:
        return 0.0
    return abs(th2 - th1) / abs(dt_s)


def max_slope_filtered(
    y: np.ndarray,
    dt: float,
    window_ns: float,
    ma_points: int = 21,
) -> float:
    """Max |dy/dt| after moving-average (IEC note: 21-point MA)."""
    ys = smooth(y, dt, window_ns)
    w = max(3, ma_points | 1)
    ys = uniform_filter1d(ys, size=w, mode="nearest")
    d = np.abs(derivative(ys, dt))
    return float(np.max(d)) if len(d) else 0.0
