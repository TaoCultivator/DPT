from __future__ import annotations

from dataclasses import dataclass

import numpy as np


OFF_OVERSHOOT_SUPPORT_FRACTION = 0.05
MIN_OVERSHOOT_V = 0.5
MIN_DELTA_CURRENT_A = 0.5
MIN_DELTA_CURRENT_FRACTION = 0.02


@dataclass(frozen=True)
class CommutationInductanceContext:
    """One voltage/current-coincident commutation-inductance measurement."""

    value_nh: float
    t_start_s: float
    t_end_s: float
    voltage_area_vs: float
    delta_current_a: float
    voltage_reference_v: float
    support_threshold_v: float = 0.0


def _finite_series(
    t_s: np.ndarray,
    voltage_v: np.ndarray,
    current_a: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    t = np.asarray(t_s, dtype=np.float64)
    voltage = np.asarray(voltage_v, dtype=np.float64)
    current = np.asarray(current_a, dtype=np.float64)
    n = min(len(t), len(voltage), len(current))
    if n < 3:
        return None
    t = t[:n]
    voltage = voltage[:n]
    current = current[:n]
    finite = np.isfinite(t) & np.isfinite(voltage) & np.isfinite(current)
    if np.count_nonzero(finite) < 3:
        return None
    if not np.all(finite):
        t = t[finite]
        voltage = voltage[finite]
        current = current[finite]
    order = np.argsort(t, kind="stable")
    t = t[order]
    voltage = voltage[order]
    current = current[order]
    keep = np.concatenate(([True], np.diff(t) > 0.0))
    t = t[keep]
    voltage = voltage[keep]
    current = current[keep]
    if len(t) < 3:
        return None
    return t, voltage, current


def _window_series(
    t_s: np.ndarray,
    voltage_v: np.ndarray,
    current_a: np.ndarray,
    t_start_s: float | None,
    t_end_s: float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    prepared = _finite_series(t_s, voltage_v, current_a)
    if prepared is None or t_start_s is None or t_end_s is None:
        return None
    t, voltage, current = prepared
    start = max(float(t[0]), min(float(t_start_s), float(t_end_s)))
    end = min(float(t[-1]), max(float(t_start_s), float(t_end_s)))
    if not np.isfinite(start) or not np.isfinite(end) or end <= start:
        return None
    inside = (t > start) & (t < end)
    window_t = np.concatenate(([start], t[inside], [end]))
    window_v = np.interp(window_t, t, voltage)
    window_i = np.interp(window_t, t, current)
    if len(window_t) < 3:
        return None
    return window_t, window_v, window_i


def _valid_delta_current(
    current_a: np.ndarray,
    start_a: float,
    end_a: float,
) -> float | None:
    delta = abs(float(end_a) - float(start_a))
    span = float(np.max(current_a) - np.min(current_a))
    minimum = max(MIN_DELTA_CURRENT_A, MIN_DELTA_CURRENT_FRACTION * span)
    if not np.isfinite(delta) or delta < minimum:
        return None
    return delta


def turn_on_commutation_inductance(
    t_s: np.ndarray,
    vce_v: np.ndarray,
    current_a: np.ndarray,
    vce_top_v: float,
    t_start_s: float | None,
    t_end_s: float | None,
) -> CommutationInductanceContext | None:
    """Integrate the turn-on inductive voltage over the same Ic A/B window.

    ``Vce_top - Vce(t)`` is the commutation-loop voltage while current rises.
    Integrating it and dividing by the current change is the waveform form of
    ``integral(u_L dt) = L * delta(I)``.  Negative samples are clipped because
    they are pre-edge overshoot/noise, not positive commutation-loop voltage.
    """

    window = _window_series(t_s, vce_v, current_a, t_start_s, t_end_s)
    if window is None or not np.isfinite(float(vce_top_v)):
        return None
    t, vce, current = window
    delta_current = _valid_delta_current(current, current[0], current[-1])
    if delta_current is None:
        return None
    inductive_voltage = np.maximum(float(vce_top_v) - vce, 0.0)
    area = float(np.trapezoid(inductive_voltage, t))
    if not np.isfinite(area) or area <= 0.0:
        return None
    value_nh = area / delta_current * 1e9
    if not np.isfinite(value_nh) or value_nh <= 0.0:
        return None
    return CommutationInductanceContext(
        float(value_nh),
        float(t[0]),
        float(t[-1]),
        area,
        float(delta_current),
        float(vce_top_v),
    )


def _threshold_crossing(
    t0: float,
    y0: float,
    i0: float,
    t1: float,
    y1: float,
    i1: float,
    threshold: float,
) -> tuple[float, float]:
    dy = float(y1 - y0)
    if abs(dy) <= 1e-15:
        return float(t1), float(i1)
    fraction = min(1.0, max(0.0, float((threshold - y0) / dy)))
    return (
        float(t0 + fraction * (t1 - t0)),
        float(i0 + fraction * (i1 - i0)),
    )


def turn_off_commutation_inductance(
    t_s: np.ndarray,
    vce_v: np.ndarray,
    current_a: np.ndarray,
    blocking_top_v: float,
    t_start_s: float | None,
    t_end_s: float | None,
    *,
    support_fraction: float = OFF_OVERSHOOT_SUPPORT_FRACTION,
    select_main_support: bool = True,
) -> CommutationInductanceContext | None:
    """Integrate the main positive Vce overshoot with its coincident delta-I.

    The di/dt A/B interval is only the search boundary.  Inside it, the
    contiguous overshoot lobe containing the maximum ``Vce - blocking_top``
    is selected.  A 5%-of-peak floor rejects baseline noise/ringing tails;
    both voltage area and current change then use exactly that sub-window.
    """

    window = _window_series(t_s, vce_v, current_a, t_start_s, t_end_s)
    if window is None or not np.isfinite(float(blocking_top_v)):
        return None
    t, vce, current = window
    excess = np.maximum(vce - float(blocking_top_v), 0.0)
    if not select_main_support:
        delta_current = _valid_delta_current(current, current[0], current[-1])
        if delta_current is None:
            return None
        area = float(np.trapezoid(excess, t))
        if not np.isfinite(area) or area <= 0.0:
            return None
        value_nh = area / delta_current * 1e9
        if not np.isfinite(value_nh) or value_nh <= 0.0:
            return None
        return CommutationInductanceContext(
            float(value_nh),
            float(t[0]),
            float(t[-1]),
            area,
            float(delta_current),
            float(blocking_top_v),
        )
    peak_index = int(np.argmax(excess))
    peak = float(excess[peak_index])
    if not np.isfinite(peak) or peak <= MIN_OVERSHOOT_V:
        return None
    fraction = min(0.95, max(0.0, float(support_fraction)))
    threshold = max(MIN_OVERSHOOT_V, fraction * peak)

    left = peak_index
    right = peak_index
    while left > 0 and excess[left - 1] >= threshold:
        left -= 1
    while right + 1 < len(excess) and excess[right + 1] >= threshold:
        right += 1
    if right - left < 2:
        return None

    selected_t = t[left : right + 1]
    selected_v = excess[left : right + 1]
    selected_i = current[left : right + 1]

    if left > 0:
        cross_t, cross_i = _threshold_crossing(
            t[left - 1],
            excess[left - 1],
            current[left - 1],
            t[left],
            excess[left],
            current[left],
            threshold,
        )
        selected_t = np.concatenate(([cross_t], selected_t))
        selected_v = np.concatenate(([threshold], selected_v))
        selected_i = np.concatenate(([cross_i], selected_i))
    if right + 1 < len(excess):
        cross_t, cross_i = _threshold_crossing(
            t[right],
            excess[right],
            current[right],
            t[right + 1],
            excess[right + 1],
            current[right + 1],
            threshold,
        )
        selected_t = np.concatenate((selected_t, [cross_t]))
        selected_v = np.concatenate((selected_v, [threshold]))
        selected_i = np.concatenate((selected_i, [cross_i]))

    delta_current = _valid_delta_current(
        current,
        selected_i[0],
        selected_i[-1],
    )
    if delta_current is None:
        return None
    area = float(np.trapezoid(selected_v, selected_t))
    if not np.isfinite(area) or area <= 0.0:
        return None
    value_nh = area / delta_current * 1e9
    if not np.isfinite(value_nh) or value_nh <= 0.0:
        return None
    return CommutationInductanceContext(
        float(value_nh),
        float(selected_t[0]),
        float(selected_t[-1]),
        area,
        float(delta_current),
        float(blocking_top_v),
        float(threshold),
    )
