"""短路测试参数提取（与双脉冲 ``extract_all`` 隔离）。"""

from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.models.bridge_profile import BridgeProfile, as_short_circuit_profile
from dpt_extractor.models.results import (
    ExtractResult,
    SegmentIndices,
    ShortCircuitResult,
    SHORT_CIRCUIT_TSC_RANGE_10,
    SHORT_CIRCUIT_TSC_RANGE_DEFAULT,
)
from dpt_extractor.models.waveform import (
    WaveformBundle,
    bundle_total_current,
    channel_reference_base_name,
    channel_reference_sign,
    normalize_channel_reference,
)


@dataclass(frozen=True)
class ShortCircuitCurrentCursors:
    """A/B/Ha/Hb for one short-circuit waveform rule."""

    t_a_s: float
    t_b_s: float
    hb_a: float
    ha_a: float
    i0: int
    i1: int


def short_circuit_tsc_range_percentages(label: str | None) -> tuple[float, float, str]:
    """Return (rise pct, fall pct, normalized label) for short-circuit Tsc."""
    if str(label or "").strip() == SHORT_CIRCUIT_TSC_RANGE_10:
        return 10.0, 10.0, SHORT_CIRCUIT_TSC_RANGE_10
    return 0.0, 0.0, SHORT_CIRCUIT_TSC_RANGE_DEFAULT


def _smooth_edge_padded(y: np.ndarray, window: int) -> np.ndarray:
    if len(y) == 0:
        return y.astype(np.float64)
    k = max(1, int(window))
    if k <= 1 or len(y) < 3:
        return y.astype(np.float64)
    k = min(k, len(y) if len(y) % 2 == 1 else len(y) - 1)
    if k < 3:
        return y.astype(np.float64)
    if k % 2 == 0:
        k -= 1
    pad = k // 2
    ker = np.ones(k, dtype=np.float64) / float(k)
    return np.convolve(
        np.pad(y.astype(np.float64), (pad, pad), mode="edge"),
        ker,
        mode="valid",
    )


def _clip_indices(i0: int, i1: int, n: int) -> tuple[int, int]:
    if n <= 0:
        return 0, 0
    a = max(0, min(int(i0), n - 1))
    b = max(a, min(int(i1), n - 1))
    return a, b


def _finite(vals: np.ndarray) -> np.ndarray:
    return vals[np.isfinite(vals)]


def _dominant_gate_window(vge: np.ndarray, dt: float) -> tuple[int, int]:
    """Use the DUT gate high interval as the broad short-circuit search window."""
    n = len(vge)
    if n < 4:
        return 0, max(0, n - 1)
    smooth_pts = max(5, int(round(40e-9 / max(dt, 1e-15))) | 1)
    y = _smooth_edge_padded(np.asarray(vge, dtype=np.float64), smooth_pts)
    vals = _finite(y)
    if len(vals) == 0:
        return 0, n - 1
    lo = float(np.nanpercentile(vals, 5))
    hi = float(np.nanpercentile(vals, 95))
    span = hi - lo
    if span <= max(1e-9, 0.02 * max(abs(hi), abs(lo), 1.0)):
        return 0, n - 1
    threshold = lo + 0.50 * span
    mask = y >= threshold
    min_width = max(5, int(round(0.08e-6 / max(dt, 1e-15))))
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for idx, active in enumerate(mask):
        if active and start is None:
            start = idx
        if (not active or idx == len(mask) - 1) and start is not None:
            end = idx - 1 if not active else idx
            if end - start + 1 >= min_width:
                runs.append((start, end))
            start = None
    if not runs:
        return 0, n - 1
    return max(runs, key=lambda pair: pair[1] - pair[0])


def _base_and_noise(y: np.ndarray, gate_i0: int, dt: float) -> tuple[float, float]:
    pre_len = max(10, int(round(0.8e-6 / max(dt, 1e-15))))
    pre0 = max(0, int(gate_i0) - pre_len)
    pre1 = max(pre0 + 1, int(gate_i0))
    vals = _finite(y[pre0:pre1])
    if len(vals) < 8:
        head_len = max(8, min(len(y), int(round(0.08e-6 / max(dt, 1e-15)))))
        vals = _finite(y[:head_len])
    if len(vals) == 0:
        return 0.0, 0.0
    base = float(np.nanmedian(vals))
    mad = float(np.nanmedian(np.abs(vals - base)))
    p05 = float(np.nanpercentile(vals, 5))
    p95 = float(np.nanpercentile(vals, 95))
    noise = max(1.4826 * mad, (p95 - p05) / 3.29, 0.0)
    return base, noise


def _interp_time(t: np.ndarray, y: np.ndarray, level: float, left: int, right: int) -> float:
    y0 = float(y[left])
    y1 = float(y[right])
    if abs(y1 - y0) < 1e-30:
        return float(t[left])
    frac = max(0.0, min(1.0, (float(level) - y0) / (y1 - y0)))
    return float(t[left] + frac * (t[right] - t[left]))


def _first_run(mask: np.ndarray, start: int, stop: int, run: int) -> int | None:
    count = 0
    stop = max(start, min(int(stop), len(mask)))
    for idx in range(max(0, int(start)), stop):
        count = count + 1 if bool(mask[idx]) else 0
        if count >= run:
            return idx - count + 1
    return None


def _last_run(mask: np.ndarray, start: int, stop: int, run: int) -> int | None:
    count = 0
    start = max(0, int(start))
    stop = max(start, min(int(stop), len(mask)))
    for idx in range(stop - 1, start - 1, -1):
        count = count + 1 if bool(mask[idx]) else 0
        if count >= run:
            return idx + count - 1
    return None


def _crossing_in_range(
    t: np.ndarray,
    y: np.ndarray,
    level: float,
    *,
    direction: str,
    start: int,
    end: int,
) -> tuple[float, int] | None:
    start = max(0, int(start))
    end = min(len(y) - 1, int(end))
    if end <= start:
        return None
    if direction == "rising":
        hits = np.where((y[start:end] <= level) & (y[start + 1 : end + 1] >= level))[0]
    elif direction == "falling":
        hits = np.where((y[start:end] >= level) & (y[start + 1 : end + 1] <= level))[0]
    else:
        raise ValueError(direction)
    if len(hits) == 0:
        return None
    left = start + int(hits[0])
    return _interp_time(t, y, level, left, left + 1), left


def short_circuit_current_cursors(
    t: np.ndarray,
    ic: np.ndarray,
    gate_i0: int,
    gate_i1: int,
    dt: float,
    *,
    smooth_ns: float = 40.0,
    peak_mode: str = "max",
) -> ShortCircuitCurrentCursors | None:
    """Imax/base-window cursors: Hb=current base, A/B=true base crossings."""
    n = len(t)
    if n == 0 or len(ic) != n:
        return None
    dt = max(float(dt), 1e-15)
    g0, g1 = _clip_indices(gate_i0, gate_i1, n)
    if g1 <= g0 + 2:
        return None
    smooth_pts = max(5, int(round(float(smooth_ns) * 1e-9 / dt)) | 1)
    y_s = _smooth_edge_padded(np.asarray(ic, dtype=np.float64), smooth_pts)
    hb, noise = _base_and_noise(y_s, g0, dt)

    seg = y_s[g0 : g1 + 1]
    if len(seg) == 0 or not np.isfinite(seg).any():
        return None
    if peak_mode == "abs":
        max_idx = g0 + int(np.nanargmax(np.abs(seg - hb)))
        pulse_sign = 1.0 if float(y_s[max_idx]) >= hb else -1.0
    elif peak_mode == "min":
        max_idx = g0 + int(np.nanargmin(seg))
        pulse_sign = -1.0
    else:
        max_idx = g0 + int(np.nanargmax(seg))
        pulse_sign = 1.0

    state = pulse_sign * (y_s - hb)
    peak_delta = float(state[max_idx])
    if not np.isfinite(peak_delta) or peak_delta <= max(1e-9, 4.0 * noise):
        return None

    active_threshold = max(
        6.0 * noise,
        0.004 * peak_delta,
        min(20.0, 0.02 * peak_delta),
    )
    pre_pad = max(5, int(round(0.3e-6 / dt)))
    post_pad = max(int(round(1.5e-6 / dt)), int(round(0.5 * max(g1 - g0, 1))))
    search0 = max(0, g0 - pre_pad)
    search1 = min(n - 1, g1 + post_pad)
    if search1 <= search0 + 2:
        return None
    seg_state = state[search0 : search1 + 1]
    peak_local = max_idx - search0
    run = max(3, int(round(20e-9 / dt)))
    active = seg_state >= active_threshold
    start_local = _first_run(active, 0, peak_local + 1, run)
    end_local = _last_run(active, peak_local, len(active), run)
    if start_local is None or end_local is None or end_local <= start_local:
        return None

    rise_abs = search0 + start_local
    fall_abs = search0 + end_local
    t_a_s = float(t[rise_abs])
    for idx in range(rise_abs, search0, -1):
        if float(state[idx - 1]) <= 0.0 <= float(state[idx]):
            t_a_s = _interp_time(t, state, 0.0, idx - 1, idx)
            break

    t_b_s = float(t[fall_abs])
    for idx in range(max(max_idx, rise_abs), search1):
        if float(state[idx]) >= 0.0 >= float(state[idx + 1]):
            t_b_s = _interp_time(t, state, 0.0, idx, idx + 1)
            break

    if t_b_s <= t_a_s:
        return None
    ia = max(0, min(int(np.searchsorted(t, t_a_s, side="left")), n - 1))
    ib = max(ia, min(int(np.searchsorted(t, t_b_s, side="left")), n - 1))
    raw_seg = np.asarray(ic[ia : ib + 1], dtype=np.float64)
    if len(raw_seg) == 0 or not np.isfinite(raw_seg).any():
        return None
    if peak_mode == "abs":
        ha = float(raw_seg[int(np.nanargmax(np.abs(raw_seg)))])
    elif peak_mode == "min":
        ha = float(np.nanmin(raw_seg))
    else:
        ha = float(np.nanmax(raw_seg))
    return ShortCircuitCurrentCursors(t_a_s, t_b_s, float(hb), ha, ia, ib)


def short_circuit_current_percent_cursors(
    t: np.ndarray,
    ic: np.ndarray,
    gate_i0: int,
    gate_i1: int,
    dt: float,
    *,
    percent: float,
    smooth_ns: float = 40.0,
    peak_mode: str = "max",
) -> ShortCircuitCurrentCursors | None:
    """Tsc-only current cursors at a percentage of the current base-to-peak span."""
    base = short_circuit_current_cursors(
        t,
        ic,
        gate_i0,
        gate_i1,
        dt,
        smooth_ns=smooth_ns,
        peak_mode=peak_mode,
    )
    if base is None:
        return None
    pct = max(0.0, min(100.0, float(percent)))
    if pct <= 1e-12:
        return base

    n = len(t)
    dt = max(float(dt), 1e-15)
    smooth_pts = max(5, int(round(float(smooth_ns) * 1e-9 / dt)) | 1)
    y_s = _smooth_edge_padded(np.asarray(ic, dtype=np.float64), smooth_pts)
    pulse_sign = 1.0 if float(base.ha_a) >= float(base.hb_a) else -1.0
    state = pulse_sign * (y_s - float(base.hb_a))
    ia0 = max(0, min(int(base.i0), n - 1))
    ib0 = max(ia0, min(int(base.i1), n - 1))
    seg = state[ia0 : ib0 + 1]
    if len(seg) == 0 or not np.isfinite(seg).any():
        return base
    peak_idx = ia0 + int(np.nanargmax(seg))
    peak_delta = float(max(np.nanmax(seg), pulse_sign * (base.ha_a - base.hb_a)))
    if not np.isfinite(peak_delta) or peak_delta <= 1e-12:
        return base
    target_state = peak_delta * pct / 100.0
    level = float(base.hb_a + pulse_sign * target_state)

    rise = _crossing_in_range(
        t,
        y_s,
        level,
        direction="rising" if pulse_sign > 0 else "falling",
        start=ia0,
        end=peak_idx,
    )
    fall = _crossing_in_range(
        t,
        y_s,
        level,
        direction="falling" if pulse_sign > 0 else "rising",
        start=peak_idx,
        end=ib0,
    )
    if rise is None or fall is None:
        return base
    t_a_s, _ = rise
    t_b_s, _ = fall
    if t_b_s <= t_a_s:
        return base
    ia = max(0, min(int(np.searchsorted(t, t_a_s, side="left")), n - 1))
    ib = max(ia, min(int(np.searchsorted(t, t_b_s, side="left")), n - 1))
    return ShortCircuitCurrentCursors(
        float(t_a_s),
        float(t_b_s),
        level,
        float(base.ha_a),
        ia,
        ib,
    )


def short_circuit_vpeak_cursors(
    t: np.ndarray,
    vge: np.ndarray,
    voltage: np.ndarray,
    gate_i0: int,
    gate_i1: int,
    dt: float,
    *,
    smooth_ns: float = 40.0,
) -> ShortCircuitCurrentCursors | None:
    """Vpeak cursors: A/B/Hb from the mapped Vge, Ha from voltage max in A-B."""
    gate = short_circuit_current_cursors(
        t,
        vge,
        gate_i0,
        gate_i1,
        dt,
        smooth_ns=smooth_ns,
        peak_mode="max",
    )
    if gate is None:
        return None
    if len(voltage) != len(t):
        return None
    seg = np.asarray(voltage[gate.i0 : gate.i1 + 1], dtype=np.float64)
    if len(seg) == 0 or not np.isfinite(seg).any():
        return None
    ha = float(np.nanmax(seg))
    return ShortCircuitCurrentCursors(
        gate.t_a_s,
        gate.t_b_s,
        gate.hb_a,
        ha,
        gate.i0,
        gate.i1,
    )


def _source_tokens(expr: str) -> set[str]:
    return {m.upper() for m in re.findall(r"\b(?:CH[1-8]|MATH\d+)\b", expr.upper())}


def find_energy_math_channel(
    bundle: WaveformBundle,
    voltage_channel: str,
    current_channel: str,
) -> str | None:
    """Find a visible Tek MATH INTG(current * voltage) channel for cursor display."""
    voltage_ref = normalize_channel_reference(voltage_channel)
    current_ref = normalize_channel_reference(current_channel)
    if channel_reference_sign(voltage_ref) < 0 or channel_reference_sign(current_ref) < 0:
        return None
    voltage_channel = channel_reference_base_name(voltage_ref)
    current_channel = channel_reference_base_name(current_ref)
    for math_key, expr in sorted(bundle.meta.channel_math_formulas.items()):
        key = math_key.upper()
        if key not in bundle.channels:
            continue
        expr_u = expr.upper()
        if "INTG" not in expr_u and "INTEG" not in expr_u:
            continue
        tokens = _source_tokens(expr_u)
        if voltage_channel in tokens and current_channel in tokens:
            return key
    return None


def find_desat_voltage_channel(
    bundle: WaveformBundle,
    preferred: str | None = None,
) -> str | None:
    """Return mapped/labelled Vdesat channel when it exists; never guess from other roles."""
    preferred_ref = normalize_channel_reference(preferred)
    if preferred_ref and bundle.has_channel_reference(preferred_ref):
        return preferred_ref
    patterns = (r"^DESAT$", r"VDESAT", r"DESATV", r"DSAT")
    labels = {
        ch.upper(): str(label)
        for ch, label in bundle.meta.channel_labels.items()
        if ch.upper() in bundle.channels
    }
    for ch in sorted(bundle.channels):
        norm = re.sub(r"[^A-Z0-9]", "", labels.get(ch.upper(), "").upper())
        if norm and any(re.search(pat, norm) for pat in patterns):
            return ch.upper()
    return None


def _energy_source_label(profile: BridgeProfile, other: bool) -> tuple[str, str, str]:
    voltage_channel = profile.v_diode if other else profile.vce
    current_channel = profile.ic or "CH3"
    return voltage_channel, current_channel, f"{current_channel}*{voltage_channel}"


def short_circuit_energy_value(
    bundle: WaveformBundle,
    profile: BridgeProfile,
    i0: int,
    i1: int,
    *,
    other: bool = False,
    math_channel: str | None = None,
) -> tuple[float, str]:
    """Return short-circuit energy in J using the specified V*I integration window."""
    n = bundle.n
    i0, i1 = _clip_indices(i0, i1, n)
    voltage_channel, current_channel, source = _energy_source_label(profile, other)
    if math_channel is None:
        math_channel = find_energy_math_channel(bundle, voltage_channel, current_channel)

    t = np.asarray(bundle.t, dtype=np.float64)
    ic = np.asarray(bundle_total_current(bundle, profile), dtype=np.float64)
    v = np.asarray(bundle.get(voltage_channel), dtype=np.float64)
    if i1 <= i0:
        return 0.0, math_channel or source
    energy = float(np.trapezoid(ic[i0 : i1 + 1] * v[i0 : i1 + 1], t[i0 : i1 + 1]))
    return max(0.0, energy), math_channel or source


def short_circuit_energy_peak_value(
    bundle: WaveformBundle,
    profile: BridgeProfile,
    i0: int,
    i1: int,
    *,
    other: bool = False,
    math_channel: str | None = None,
) -> tuple[float, str]:
    """Return Ha level for Esc: energy-curve max if visible, else cumulative integral max."""
    n = bundle.n
    i0, i1 = _clip_indices(i0, i1, n)
    voltage_channel, current_channel, source = _energy_source_label(profile, other)
    if math_channel is None:
        math_channel = find_energy_math_channel(bundle, voltage_channel, current_channel)
    if math_channel and bundle.has_channel_reference(math_channel):
        values = bundle.maybe_get(math_channel)
        if values is not None:
            seg = np.asarray(values[i0 : i1 + 1], dtype=np.float64)
            if len(seg) and np.isfinite(seg).any():
                return float(np.nanmax(seg)), math_channel

    t = np.asarray(bundle.t[i0 : i1 + 1], dtype=np.float64)
    ic = np.asarray(bundle_total_current(bundle, profile)[i0 : i1 + 1], dtype=np.float64)
    v = np.asarray(bundle.get(voltage_channel)[i0 : i1 + 1], dtype=np.float64)
    if len(t) < 2:
        return 0.0, source
    p = ic * v
    increments = 0.5 * (p[1:] + p[:-1]) * np.diff(t)
    cumulative = np.concatenate(([0.0], np.cumsum(increments)))
    return max(0.0, float(np.nanmax(cumulative))), source


def short_circuit_desat_cursors(
    t: np.ndarray,
    vge: np.ndarray,
    vdesat: np.ndarray,
    gate_i0: int,
    gate_i1: int,
    dt: float,
    *,
    threshold_v: float | None,
    smooth_ns: float = 40.0,
) -> ShortCircuitCurrentCursors | None:
    """Desat cursors. Returns None unless a real Vdesat channel and threshold exist."""
    if threshold_v is None or len(vdesat) != len(t):
        return None
    gate = short_circuit_current_cursors(
        t,
        vge,
        gate_i0,
        gate_i1,
        dt,
        smooth_ns=smooth_ns,
        peak_mode="max",
    )
    if gate is None:
        return None
    smooth_pts = max(5, int(round(float(smooth_ns) * 1e-9 / max(dt, 1e-15))) | 1)
    vd = _smooth_edge_padded(np.asarray(vdesat, dtype=np.float64), smooth_pts)
    start = max(0, min(gate.i0, len(t) - 1))
    end = min(len(t) - 1, max(gate.i1, int(gate_i1)))
    cross = _crossing_in_range(
        t,
        vd,
        float(threshold_v),
        direction="rising",
        start=start,
        end=end,
    )
    if cross is None:
        return None
    t_b_s, _idx = cross
    if t_b_s <= gate.t_a_s:
        return None
    ib = max(start, min(int(np.searchsorted(t, t_b_s, side="left")), len(t) - 1))
    return ShortCircuitCurrentCursors(
        gate.t_a_s,
        float(t_b_s),
        float(threshold_v),
        float(threshold_v),
        gate.i0,
        ib,
    )


def _vdc_from_pre_window(bundle: WaveformBundle, profile: BridgeProfile, i0: int) -> float:
    n = bundle.n
    if n == 0:
        return 0.0
    dt = max(float(bundle.dt), 1e-15)
    pre_len = max(10, int(round(0.5e-6 / dt)))
    a = max(0, i0 - pre_len)
    b = max(a + 1, min(i0, n))
    vals: list[float] = []
    for ch in (profile.vce, profile.v_diode):
        channel = bundle.maybe_get(ch)
        if channel is not None:
            seg = np.asarray(channel[a:b], dtype=np.float64)
            if len(seg):
                vals.append(float(np.nanpercentile(seg, 95)))
    if vals:
        return float(max(vals))
    return 0.0


def extract_short_circuit(
    bundle: WaveformBundle,
    profile: BridgeProfile,
    cfg: AppConfig,
) -> ExtractResult:
    """按短路规范提取 Imax/Tsc/Esc/Vpeak/Desat。"""
    profile = as_short_circuit_profile(profile)
    t = bundle.t
    n = bundle.n
    if n == 0:
        return ExtractResult(short_circuit_mode=True)

    vge = np.asarray(bundle.get(profile.vge), dtype=np.float64)
    vce = np.asarray(bundle.get(profile.vce), dtype=np.float64)
    ic = np.asarray(bundle_total_current(bundle, profile), dtype=np.float64)
    v_diode = bundle.maybe_get(profile.v_diode)
    v_diode_arr = np.asarray(v_diode, dtype=np.float64) if v_diode is not None else None

    unavailable: set[tuple[str, str]] = set()
    if v_diode_arr is None:
        unavailable.update(
            {
                ("短路过程", "短路能量Esc_对管"),
                ("短路过程", "应力Vpeak_对管"),
            }
        )

    gate0, gate1 = _dominant_gate_window(vge, bundle.dt)
    gate0, gate1 = _clip_indices(gate0, gate1, n)
    if gate1 <= gate0:
        gate1 = min(n - 1, gate0 + 1)

    current_cursors = short_circuit_current_cursors(
        t,
        ic,
        gate0,
        gate1,
        bundle.dt,
        smooth_ns=cfg.smoothing.detect_window_ns,
        peak_mode="max",
    )
    if current_cursors is None and n > 1:
        current_cursors = short_circuit_current_cursors(
            t,
            ic,
            0,
            n - 1,
            bundle.dt,
            smooth_ns=cfg.smoothing.detect_window_ns,
            peak_mode="max",
        )
    tsc_start_pct, tsc_end_pct, tsc_range_label = short_circuit_tsc_range_percentages(
        cfg.short_circuit_tsc_range
    )
    if current_cursors is None:
        unavailable.update(
            {
                ("短路过程", "短路电流Imax"),
                ("短路过程", "短路时间Tsc"),
                ("短路过程", "短路能量Esc_本管"),
                ("短路过程", "短路能量Esc_对管"),
            }
        )
        current_i0, current_i1 = gate0, gate1
        tsc_cursors = None
        ic_max = 0.0
        tsc = 0.0
        tsc_start_us = None
        tsc_end_us = None
    else:
        current_i0, current_i1 = current_cursors.i0, current_cursors.i1
        ic_max = float(np.nanmax(ic[current_i0 : current_i1 + 1]))
        if tsc_range_label == SHORT_CIRCUIT_TSC_RANGE_DEFAULT:
            tsc_cursors = current_cursors
        else:
            tsc_cursors = short_circuit_current_percent_cursors(
                t,
                ic,
                gate0,
                gate1,
                bundle.dt,
                smooth_ns=cfg.smoothing.detect_window_ns,
                percent=0.5 * (tsc_start_pct + tsc_end_pct),
                peak_mode="max",
            )
            if tsc_cursors is None and n > 1:
                tsc_cursors = short_circuit_current_percent_cursors(
                    t,
                    ic,
                    0,
                    n - 1,
                    bundle.dt,
                    smooth_ns=cfg.smoothing.detect_window_ns,
                    percent=0.5 * (tsc_start_pct + tsc_end_pct),
                    peak_mode="max",
                )
            if tsc_cursors is None:
                tsc_cursors = current_cursors
        tsc = float(max(0.0, (tsc_cursors.t_b_s - tsc_cursors.t_a_s) * 1e6))
        tsc_start_us = float(tsc_cursors.t_a_s * 1e6)
        tsc_end_us = float(tsc_cursors.t_b_s * 1e6)

    dut_vpeak_cursors = short_circuit_vpeak_cursors(
        t,
        vge,
        vce,
        gate0,
        gate1,
        bundle.dt,
        smooth_ns=cfg.smoothing.detect_window_ns,
    )
    other_vpeak_cursors = (
        short_circuit_vpeak_cursors(
            t,
            vge,
            v_diode_arr,
            gate0,
            gate1,
            bundle.dt,
            smooth_ns=cfg.smoothing.detect_window_ns,
        )
        if v_diode_arr is not None
        else None
    )

    vpeak_dut = (
        dut_vpeak_cursors.ha_a
        if dut_vpeak_cursors is not None
        else float(np.nanmax(vce[gate0 : gate1 + 1]))
    )
    vpeak_other = (
        other_vpeak_cursors.ha_a
        if other_vpeak_cursors is not None
        else 0.0
    )
    if other_vpeak_cursors is None:
        unavailable.add(("短路过程", "应力Vpeak_对管"))

    if current_cursors is not None:
        esc_dut, e_dut_ch = short_circuit_energy_value(
            bundle, profile, current_i0, current_i1, other=False
        )
        if v_diode_arr is not None:
            esc_other, e_other_ch = short_circuit_energy_value(
                bundle, profile, current_i0, current_i1, other=True
            )
        else:
            esc_other, e_other_ch = 0.0, ""
    else:
        esc_dut, e_dut_ch = 0.0, ""
        esc_other, e_other_ch = 0.0, ""

    desat_time: float | None = None
    desat_range = "预留"
    desat_channel = find_desat_voltage_channel(bundle, getattr(profile, "vdesat", ""))
    desat_threshold_v = getattr(cfg, "short_circuit_desat_threshold_v", None)
    if desat_channel is not None and desat_threshold_v is not None:
        desat_cursors = short_circuit_desat_cursors(
            t,
            vge,
            np.asarray(bundle.get(desat_channel), dtype=np.float64),
            gate0,
            gate1,
            bundle.dt,
            threshold_v=float(desat_threshold_v),
            smooth_ns=cfg.smoothing.detect_window_ns,
        )
        if desat_cursors is not None:
            desat_time = float(
                max(0.0, (desat_cursors.t_b_s - desat_cursors.t_a_s) * 1e6)
            )
            desat_range = "Vdesat阈值"
    if desat_time is None:
        unavailable.add(("短路过程", "Desat动作时间"))

    sc = ShortCircuitResult(
        ic_max=ic_max,
        tsc=tsc,
        tsc_start_us=tsc_start_us,
        tsc_end_us=tsc_end_us,
        esc_dut=esc_dut,
        vpeak_dut=vpeak_dut,
        esc_other=esc_other,
        vpeak_other=vpeak_other,
        desat_time=desat_time,
        tsc_range=tsc_range_label,
        desat_range=desat_range,
        energy_dut_channel=e_dut_ch,
        energy_other_channel=e_other_ch,
    )
    segs = SegmentIndices(
        turn_off=(gate0, gate1),
        turn_on=(gate0, gate1),
        reverse_recovery=(gate0, gate1),
        pulse1_on=gate0,
        pulse1_off=gate1,
        pulse2_on=gate1,
        pulse2_off=gate1,
    )
    vdc = _vdc_from_pre_window(bundle, profile, gate0)
    return ExtractResult(
        vdc=vdc,
        idc=sc.ic_max,
        vdc_set=vdc,
        idc_set=sc.ic_max,
        short_circuit=sc,
        segments=segs,
        profile_name=profile.name,
        profile_code=profile.code,
        phase=profile.phase,
        source_path=bundle.meta.source_path,
        detected_pulse_count=1,
        off_pulse_index=1,
        on_pulse_index=1,
        single_pulse_mode=False,
        short_circuit_mode=True,
        unavailable_metrics=unavailable,
    )
