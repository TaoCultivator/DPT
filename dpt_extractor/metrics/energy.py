from __future__ import annotations

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.metrics.iec_windows import (
    IntegrationWindow,
    energy_window_power,
    integrate_vi_window,
)


def integrate_energy(
    t: np.ndarray,
    power: np.ndarray,
    i0: int,
    i1: int,
    cfg: AppConfig,
) -> float:
    """Legacy MATH channel integral (often not power); kept for reference."""
    if i1 <= i0 + 1:
        return 0.0
    seg_t = t[i0:i1]
    seg_p = power[i0:i1]
    dt_arr = np.diff(seg_t)
    p_mid = 0.5 * (seg_p[:-1] + seg_p[1:])
    return float(np.sum(p_mid * dt_arr)) * 1e3


def integrate_vi(
    t: np.ndarray,
    v: np.ndarray,
    i: np.ndarray,
    i0: int,
    i1: int,
) -> float:
    if i1 <= i0 + 1:
        return 0.0
    seg_t = t[i0:i1]
    p = v[i0:i1] * i[i0:i1]
    dt_arr = np.diff(seg_t)
    p_mid = 0.5 * (p[:-1] + p[1:])
    return float(np.sum(p_mid * dt_arr)) * 1e3


def peak_power_kw(
    v: np.ndarray,
    i: np.ndarray,
    win: IntegrationWindow,
    *,
    absolute: bool = False,
) -> float:
    """Peak V*I in the same half-open integration window, returned in kW."""
    v_arr = np.asarray(v, dtype=np.float64)
    i_arr = np.asarray(i, dtype=np.float64)
    n = min(v_arr.size, i_arr.size)
    if n == 0:
        return 0.0
    i0 = max(0, min(int(win.i_start), n - 1))
    i1 = max(i0 + 1, min(int(win.i_end), n))
    if i1 <= i0:
        return 0.0
    if absolute:
        power = np.abs(v_arr[i0:i1]) * np.abs(i_arr[i0:i1])
    else:
        power = v_arr[i0:i1] * i_arr[i0:i1]
    finite = power[np.isfinite(power)]
    if finite.size == 0:
        return 0.0
    return float(np.max(finite)) / 1000.0


def switch_energy(
    t: np.ndarray,
    v: np.ndarray,
    i: np.ndarray,
    win: IntegrationWindow,
    cfg: AppConfig,
    center_idx: int | None = None,
    dt: float = 8e-11,
) -> tuple[float, bool]:
    """
    Primary: IEC ∫v·i over window; fallback to power-threshold window if IEC window too narrow.
    """
    e_vi = integrate_vi_window(t, v, i, win)
    dur = (win.t_end - win.t_start) * 1e9
    if dur < 50 and center_idx is not None:
        win = energy_window_power(t, v, i, center_idx, dt)
        e_vi = integrate_vi_window(t, v, i, win)
    return e_vi, False


def energy_warn(e_primary: float, e_check: float, cfg: AppConfig) -> bool:
    if e_primary <= 0 and e_check <= 0:
        return False
    denom = max(abs(e_primary), abs(e_check), 1e-12)
    return abs(e_primary - e_check) / denom > cfg.energy.warn_relative_diff
