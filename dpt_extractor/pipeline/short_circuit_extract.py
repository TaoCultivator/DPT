"""短路测试参数提取（与双脉冲 ``extract_all`` 隔离）。"""

from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.models.bridge_profile import BridgeProfile, as_short_circuit_profile
from dpt_extractor.models.results import ExtractResult, SegmentIndices, ShortCircuitResult
from dpt_extractor.models.waveform import WaveformBundle, bundle_total_current


class ShortCircuitExtractNotReady(RuntimeError):
    """兼容旧调用方；短路提取已实现后不再主动抛出。"""


@dataclass(frozen=True)
class ShortCircuitCurrentCursors:
    t_a_s: float
    t_b_s: float
    hb_a: float
    ha_a: float
    i0: int
    i1: int


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
    return np.convolve(np.pad(y.astype(np.float64), (pad, pad), mode="edge"), ker, mode="valid")


def _clip_indices(i0: int, i1: int, n: int) -> tuple[int, int]:
    if n <= 0:
        return 0, 0
    a = max(0, min(int(i0), n - 1))
    b = max(a, min(int(i1), n - 1))
    return a, b


def _dominant_gate_window(vge: np.ndarray, dt: float) -> tuple[int, int]:
    """Use the DUT gate high interval as the short-circuit stress window."""
    n = len(vge)
    if n < 4:
        return 0, max(0, n - 1)
    smooth_pts = max(5, int(round(40e-9 / max(dt, 1e-15))) | 1)
    y = _smooth_edge_padded(np.asarray(vge, dtype=np.float64), smooth_pts)
    lo = float(np.percentile(y, 5))
    hi = float(np.percentile(y, 95))
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


def short_circuit_current_cursors(
    t: np.ndarray,
    ic: np.ndarray,
    gate_i0: int,
    gate_i1: int,
    dt: float,
    *,
    smooth_ns: float = 40.0,
    peak_mode: str = "abs",
) -> ShortCircuitCurrentCursors | None:
    """Hb crossing cursors for a short-circuit waveform."""
    n = len(t)
    if n == 0 or len(ic) != n:
        return None
    dt = max(float(dt), 1e-15)
    g0, g1 = _clip_indices(gate_i0, gate_i1, n)
    if g1 <= g0 + 2:
        return None
    smooth_pts = max(5, int(round(float(smooth_ns) * 1e-9 / dt)) | 1)
    ic_s = _smooth_edge_padded(np.asarray(ic, dtype=np.float64), smooth_pts)

    def _finite(vals: np.ndarray) -> np.ndarray:
        return vals[np.isfinite(vals)]

    pre_len = max(10, int(round(0.8e-6 / dt)))
    pre0 = max(0, g0 - pre_len)
    pre1 = max(pre0 + 1, g0)
    base_vals = _finite(ic_s[pre0:pre1])
    if len(base_vals) < 8:
        head_len = max(8, min(g1 - g0 + 1, int(round(0.08e-6 / dt))))
        base_vals = _finite(ic_s[g0 : g0 + head_len])
    if len(base_vals):
        hb = 0.5 * (float(np.nanmax(base_vals)) + float(np.nanmin(base_vals)))
        mad = float(np.nanmedian(np.abs(base_vals - hb)))
        p05 = float(np.nanpercentile(base_vals, 5))
        p95 = float(np.nanpercentile(base_vals, 95))
        noise = max(1.4826 * mad, (p95 - p05) / 3.29, 0.0)
    else:
        hb = 0.0
        noise = 0.0

    delta_s = np.abs(ic_s - hb)
    gate_delta = _finite(delta_s[g0 : g1 + 1])
    if len(gate_delta) == 0:
        return None
    peak_idx = g0 + int(np.nanargmax(delta_s[g0 : g1 + 1]))
    peak_delta = float(delta_s[peak_idx])
    if not np.isfinite(peak_delta) or peak_delta <= max(1e-9, 4.0 * noise):
        return None

    threshold = max(
        6.0 * noise,
        0.004 * peak_delta,
        min(20.0, 0.02 * peak_delta),
    )
    pre_pad = max(5, int(round(0.3e-6 / dt)))
    post_pad = max(
        int(round(1.5e-6 / dt)),
        int(round(0.5 * max(g1 - g0, 1))),
    )
    search0 = max(0, g0 - pre_pad)
    search1 = min(n - 1, g1 + post_pad)
    if search1 <= search0 + 2:
        return None

    pulse_sign = 1.0 if float(ic_s[peak_idx]) >= float(hb) else -1.0
    state = pulse_sign * (ic_s - float(hb))
    seg = state[search0 : search1 + 1]
    peak_local = peak_idx - search0
    active = seg >= threshold
    run = max(3, int(round(20e-9 / dt)))

    def _first_run(mask: np.ndarray, start: int, stop: int) -> int | None:
        count = 0
        stop = max(start, min(int(stop), len(mask)))
        for idx in range(max(0, start), stop):
            count = count + 1 if bool(mask[idx]) else 0
            if count >= run:
                return idx - count + 1
        return None

    def _last_run(mask: np.ndarray, start: int, stop: int) -> int | None:
        count = 0
        start = max(0, int(start))
        stop = max(start, min(int(stop), len(mask)))
        for idx in range(stop - 1, start - 1, -1):
            count = count + 1 if bool(mask[idx]) else 0
            if count >= run:
                return idx + count - 1
        return None

    start_local = _first_run(active, 0, peak_local + 1)
    end_local = _last_run(active, peak_local, len(active))
    if start_local is None or end_local is None or end_local <= start_local:
        return None

    def _cross_time(left: int, right: int) -> float:
        y0 = float(state[left])
        y1 = float(state[right])
        if abs(y1 - y0) < 1e-30:
            return float(t[left])
        frac = max(0.0, min(1.0, -y0 / (y1 - y0)))
        return float(t[left] + frac * (t[right] - t[left]))

    rise_abs = search0 + start_local
    fall_abs = search0 + end_local
    t_a_s = float(t[rise_abs])
    for idx in range(rise_abs, search0, -1):
        if float(state[idx - 1]) <= 0.0 <= float(state[idx]):
            t_a_s = _cross_time(idx - 1, idx)
            break

    t_b_s = float(t[fall_abs])
    for idx in range(max(peak_idx, rise_abs), search1):
        if float(state[idx]) >= 0.0 >= float(state[idx + 1]):
            t_b_s = _cross_time(idx, idx + 1)
            break

    if t_b_s <= t_a_s:
        t_a_s = float(t[rise_abs])
        t_b_s = float(t[fall_abs])
    if t_b_s <= t_a_s:
        return None

    ia = max(0, min(int(np.searchsorted(t, t_a_s, side="left")), n - 1))
    ib = max(ia, min(int(np.searchsorted(t, t_b_s, side="left")), n - 1))
    seg_raw = np.asarray(ic[ia : ib + 1], dtype=np.float64)
    if len(seg_raw):
        if peak_mode == "abs":
            ha = float(seg_raw[int(np.nanargmax(np.abs(seg_raw)))])
        else:
            ha = float(np.nanmax(seg_raw))
    else:
        ha = float(ic[peak_idx])
    return ShortCircuitCurrentCursors(t_a_s, t_b_s, float(hb), ha, ia, ib)


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
    """Vpeak cursors: A/B and Hb from DUT Vge base crossings, Ha from voltage max."""
    n = len(t)
    if n == 0 or len(vge) != n or len(voltage) != n:
        return None
    dt = max(float(dt), 1e-15)
    g0, g1 = _clip_indices(gate_i0, gate_i1, n)
    if g1 <= g0 + 2:
        return None

    smooth_pts = max(5, int(round(float(smooth_ns) * 1e-9 / dt)) | 1)
    gate = _smooth_edge_padded(np.asarray(vge, dtype=np.float64), smooth_pts)
    pre_len = max(10, int(round(0.8e-6 / dt)))
    pre0 = max(0, g0 - pre_len)
    pre = gate[pre0:g0]
    pre = pre[np.isfinite(pre)]
    if len(pre) >= 8:
        stable_pre = pre[: max(8, int(round(0.70 * len(pre))))]
        hb = float(np.nanmedian(stable_pre))
    else:
        vals = gate[np.isfinite(gate)]
        if len(vals) == 0:
            return None
        hb = float(np.nanpercentile(vals, 5))

    gate_seg = gate[g0 : g1 + 1]
    if len(gate_seg) == 0 or not np.any(np.isfinite(gate_seg)):
        return None
    peak_idx = g0 + int(np.nanargmax(np.abs(gate_seg - hb)))
    pulse_sign = 1.0 if float(gate[peak_idx]) >= hb else -1.0
    state = pulse_sign * (gate - hb)

    def _interp_cross(left: int, right: int) -> float:
        y0 = float(state[left])
        y1 = float(state[right])
        if abs(y1 - y0) < 1e-30:
            return float(t[left])
        frac = max(0.0, min(1.0, -y0 / (y1 - y0)))
        return float(t[left] + frac * (t[right] - t[left]))

    pre_pad = max(pre_len, int(round(1.0e-6 / dt)))
    post_pad = max(pre_len, int(round(1.5e-6 / dt)))
    search0 = max(0, g0 - pre_pad)
    search1 = min(n - 1, g1 + post_pad)

    t_a_s: float | None = None
    for idx in range(g0, search0, -1):
        if float(state[idx - 1]) <= 0.0 <= float(state[idx]):
            t_a_s = _interp_cross(idx - 1, idx)
            break
    if t_a_s is None:
        for idx in range(search0, min(g1, n - 1)):
            if float(state[idx]) <= 0.0 <= float(state[idx + 1]):
                t_a_s = _interp_cross(idx, idx + 1)
                break
    if t_a_s is None:
        t_a_s = float(t[g0])

    t_b_s: float | None = None
    for idx in range(max(g1, peak_idx), search1):
        if float(state[idx]) >= 0.0 >= float(state[idx + 1]):
            t_b_s = _interp_cross(idx, idx + 1)
            break
    if t_b_s is None:
        for idx in range(g1, search1):
            if float(state[idx]) >= 0.0 >= float(state[idx + 1]):
                t_b_s = _interp_cross(idx, idx + 1)
                break
    if t_b_s is None:
        t_b_s = float(t[g1])
    if t_b_s <= t_a_s:
        return None

    i0 = max(0, min(int(np.searchsorted(t, t_a_s, side="left")), n - 1))
    i1 = max(i0, min(int(np.searchsorted(t, t_b_s, side="left")), n - 1))
    seg = np.asarray(voltage[i0 : i1 + 1], dtype=np.float64)
    ha = float(np.nanmax(seg)) if len(seg) else 0.0
    return ShortCircuitCurrentCursors(
        float(t_a_s),
        float(t_b_s),
        hb,
        ha,
        i0,
        i1,
    )


def _source_tokens(expr: str) -> set[str]:
    return {m.upper() for m in re.findall(r"\b(?:CH[1-6]|MATH\d+)\b", expr.upper())}


def find_energy_math_channel(
    bundle: WaveformBundle,
    voltage_channel: str,
    current_channel: str,
) -> str | None:
    """Find a Tek MATH INTG(current * voltage) channel for the requested voltage."""
    voltage_channel = voltage_channel.upper()
    current_channel = current_channel.upper()
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


def find_desat_voltage_channel(bundle: WaveformBundle) -> str | None:
    """Find a future Desat voltage channel by Tek label text."""
    patterns = (r"^DESAT$", r"VDESAT", r"DESATV", r"DSAT")
    labels = {
        ch.upper(): str(label)
        for ch, label in bundle.meta.channel_labels.items()
        if ch.upper() in bundle.channels
    }
    for ch in sorted(bundle.channels):
        norm = re.sub(r"[^A-Z0-9]", "", labels.get(ch.upper(), "").upper())
        if not norm:
            continue
        if any(re.search(pat, norm) for pat in patterns):
            return ch.upper()
    return None


def short_circuit_energy_value(
    bundle: WaveformBundle,
    profile: BridgeProfile,
    i0: int,
    i1: int,
    *,
    other: bool = False,
    math_channel: str | None = None,
) -> tuple[float, str]:
    """Return short-circuit energy in J and the source channel/formula name."""
    n = bundle.n
    i0, i1 = _clip_indices(i0, i1, n)
    voltage_channel = profile.v_diode if other else profile.vce
    current_channel = profile.ic or "CH3"
    if math_channel is None:
        math_channel = find_energy_math_channel(bundle, voltage_channel, current_channel)
    if math_channel and math_channel in bundle.channels:
        seg = np.asarray(bundle.channels[math_channel][i0 : i1 + 1], dtype=np.float64)
        if len(seg):
            return max(0.0, float(seg[-1] - seg[0])), math_channel

    t = np.asarray(bundle.t, dtype=np.float64)
    ic = np.asarray(bundle_total_current(bundle, profile), dtype=np.float64)
    v = np.asarray(bundle.get(voltage_channel), dtype=np.float64)
    if i1 <= i0:
        return 0.0, f"{current_channel}*{voltage_channel}"
    energy = float(np.trapezoid(ic[i0 : i1 + 1] * v[i0 : i1 + 1], t[i0 : i1 + 1]))
    return max(0.0, energy), f"{current_channel}*{voltage_channel}"


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
        if ch in bundle.channels:
            seg = np.asarray(bundle.channels[ch][a:b], dtype=np.float64)
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
    """提取短路窗口内最大值与短路时间。"""
    profile = as_short_circuit_profile(profile)
    t = bundle.t
    n = bundle.n
    if n == 0:
        return ExtractResult(short_circuit_mode=True)

    vge = np.asarray(bundle.get(profile.vge), dtype=np.float64)
    vce = np.asarray(bundle.get(profile.vce), dtype=np.float64)
    vce_other_raw = bundle.channels.get(profile.v_diode) if profile.v_diode else None
    vce_other = (
        np.asarray(vce_other_raw, dtype=np.float64)
        if vce_other_raw is not None
        else None
    )
    ic = np.asarray(bundle_total_current(bundle, profile), dtype=np.float64)
    unavailable: set[tuple[str, str]] = set()
    if vce_other is None:
        unavailable.update(
            {
                ("短路过程", "短路能量Esc_对管"),
                ("短路过程", "应力Vpeak_对管"),
            }
        )

    i0, i1 = _dominant_gate_window(vge, bundle.dt)
    i0, i1 = _clip_indices(i0, i1, n)
    if i1 <= i0:
        i1 = min(n - 1, i0 + 1)

    current_cursors = short_circuit_current_cursors(
        t,
        ic,
        i0,
        i1,
        bundle.dt,
        smooth_ns=cfg.smoothing.detect_window_ns,
    )
    if current_cursors is not None:
        ic0, ic1 = current_cursors.i0, current_cursors.i1
        ic_max = float(np.nanmax(np.abs(ic[ic0 : ic1 + 1])))
        tsc = float(max(0.0, (current_cursors.t_b_s - current_cursors.t_a_s) * 1e6))
        tsc_start_us = float(current_cursors.t_a_s * 1e6)
        tsc_end_us = float(current_cursors.t_b_s * 1e6)
        tsc_range = "Ic-Hb交点"
    else:
        ic_max = float(np.nanmax(np.abs(ic[i0 : i1 + 1])))
        tsc = float(max(0.0, (t[i1] - t[i0]) * 1e6))
        tsc_start_us = float(t[i0] * 1e6)
        tsc_end_us = float(t[i1] * 1e6)
        tsc_range = "Vge高电平"

    energy_i0, energy_i1 = (ic0, ic1) if current_cursors is not None else (i0, i1)
    vpeak_dut_cursors = short_circuit_vpeak_cursors(
        t,
        vge,
        vce,
        i0,
        i1,
        bundle.dt,
        smooth_ns=cfg.smoothing.detect_window_ns,
    )
    vpeak_other_cursors = (
        short_circuit_current_cursors(
            t,
            vce_other,
            i0,
            i1,
            bundle.dt,
            smooth_ns=cfg.smoothing.detect_window_ns,
            peak_mode="max",
        )
        if vce_other is not None
        else None
    )
    vpeak_dut = (
        vpeak_dut_cursors.ha_a
        if vpeak_dut_cursors is not None
        else float(np.nanmax(vce[i0 : i1 + 1]))
    )
    vpeak_other = (
        vpeak_other_cursors.ha_a
        if vpeak_other_cursors is not None
        else float(np.nanmax(vce_other[i0 : i1 + 1]))
        if vce_other is not None
        else 0.0
    )
    desat_time: float | None = None
    desat_range = "预留"
    desat_channel = find_desat_voltage_channel(bundle)
    if desat_channel is not None:
        desat_cursors = short_circuit_current_cursors(
            t,
            np.asarray(bundle.get(desat_channel), dtype=np.float64),
            i0,
            i1,
            bundle.dt,
            smooth_ns=cfg.smoothing.detect_window_ns,
            peak_mode="max",
        )
        if desat_cursors is not None:
            desat_time = float(
                max(0.0, (desat_cursors.t_b_s - desat_cursors.t_a_s) * 1e6)
            )
            desat_range = "Desat-Hb交点"

    esc_dut, e_dut_ch = short_circuit_energy_value(
        bundle, profile, energy_i0, energy_i1, other=False
    )
    if vce_other is not None:
        esc_other, e_other_ch = short_circuit_energy_value(
            bundle, profile, energy_i0, energy_i1, other=True
        )
    else:
        esc_other, e_other_ch = 0.0, ""
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
        tsc_range=tsc_range,
        desat_range=desat_range,
        energy_dut_channel=e_dut_ch,
        energy_other_channel=e_other_ch,
    )
    segs = SegmentIndices(
        turn_off=(i0, i1),
        turn_on=(i0, i1),
        reverse_recovery=(i0, i1),
        pulse1_on=i0,
        pulse1_off=i1,
        pulse2_on=i1,
        pulse2_off=i1,
    )
    vdc = _vdc_from_pre_window(bundle, profile, i0)
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
