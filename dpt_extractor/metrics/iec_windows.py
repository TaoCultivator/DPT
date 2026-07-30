from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from dpt_extractor.metrics.offset_measurement import scope_top_base
from dpt_extractor.utils.signal import crossing_index, crossing_time, smooth, threshold_value
from dpt_extractor.utils.timing_adapt import scope_turn_off_bases, scope_turn_on_bases


@dataclass
class IntegrationWindow:
    i_start: int
    i_end: int
    t_start: float
    t_end: float


@dataclass(frozen=True)
class EnergyLossMarkers:
    """Eoff/Eon 卡尺：Ha/Hb 为平台电平，A/B 为与对应波形交点时刻。

    Eoff: ha_v=Vce 导通平台(V)，hb_a=Ic 回落平台(A)。
    Eon:  ha_v=Ic 抬升前平台(A)；hb_a=Vce 回落后导通平台(V)；v_b 同 hb_a。
    Err:  ha_v=Irr 平台/幅值光标(A)；hb_a=V_二极管 基线(V)；v_b 同 hb_a。
    """

    ha_v: float
    hb_a: float
    t_start: float
    t_end: float
    i_start: int
    i_end: int
    v_b: float | None = None  # Eon：B 光标用 Vce 导通平台穿越电平

    def as_integration_window(self) -> IntegrationWindow:
        return IntegrationWindow(
            self.i_start, self.i_end, self.t_start, self.t_end
        )


_PARAM_LOCAL_US_PER_DIV = 0.2
_PARAM_LOCAL_DIV_COUNT = 10.0
_PARAM_LOCAL_LEFT_DIVS = 2.0
_PARAM_LOCAL_VGE_SMOOTH_NS = 15.0


def _plateau_mean_vce_before_off(
    vce: np.ndarray, ic: np.ndarray, off_idx: int, w0: int, dt: float
) -> float:
    """关断：电压抬升前导通段 Vce 平稳均值。"""
    pre_end = max(w0 + 5, off_idx)
    pre_v = vce[w0:pre_end].astype(np.float64)
    pre_i = np.abs(ic[w0:pre_end])
    if len(pre_v) < 8:
        return float(np.mean(pre_v)) if len(pre_v) else 0.0
    i_top = float(np.percentile(pre_i, 95))
    on_thr = max(0.55 * i_top, 20.0)
    on_mask = pre_i >= on_thr
    if int(np.count_nonzero(on_mask)) >= 8:
        return float(np.median(pre_v[on_mask]))
    return float(np.median(pre_v))


def _local_band_center(values: np.ndarray) -> float:
    """Signed center of a local waveform band, robust to isolated spikes."""
    vals = np.asarray(values, dtype=np.float64)
    vals = vals[np.isfinite(vals)]
    if len(vals) < 8:
        return float(np.mean(vals)) if len(vals) else 0.0
    p05, p95 = (float(np.nanpercentile(vals, p)) for p in (5, 95))
    return 0.5 * (p05 + p95)


def _scope_band_center(values: np.ndarray) -> float:
    """Center of a local visible waveform band using the offset Top/Base logic."""
    vals = np.asarray(values, dtype=np.float64)
    vals = vals[np.isfinite(vals)]
    if len(vals) < 8:
        return float(np.mean(vals)) if len(vals) else 0.0
    top, base = scope_top_base(vals)
    if np.isfinite(top) and np.isfinite(base):
        center = 0.5 * (float(top) + float(base))
        p01, p99 = (float(np.nanpercentile(vals, p)) for p in (1, 99))
        margin = max(1e-9, 0.05 * (p99 - p01))
        if p01 - margin <= center <= p99 + margin:
            return float(center)
    return _local_band_center(vals)


def _quiet_local_platform_level(values: np.ndarray, dt: float, *, min_ns: float = 200.0) -> float:
    """Signed center of the quietest local platform band, using about 200 ns."""
    vals = np.asarray(values, dtype=np.float64)
    vals = vals[np.isfinite(vals)]
    if len(vals) < 8:
        return float(np.mean(vals)) if len(vals) else 0.0
    win_n = _samples_for_seconds(dt, min_ns * 1e-9, minimum=16)
    if len(vals) <= win_n:
        return _local_band_center(vals)

    step = max(1, win_n // 8)
    starts = list(range(0, len(vals) - win_n + 1, step))
    if starts[-1] != len(vals) - win_n:
        starts.append(len(vals) - win_n)
    tail_ref = _local_band_center(vals[-win_n:])
    best_start = starts[0]
    best_score = float("inf")
    for start in starts:
        block = vals[start : start + win_n]
        if len(block) < win_n:
            continue
        p05, p50, p95 = (float(np.nanpercentile(block, p)) for p in (5, 50, 95))
        pp = p95 - p05
        slope = abs(float(block[-1]) - float(block[0]))
        center = 0.5 * (p05 + p95)
        score = pp + 0.15 * abs(center - tail_ref) + 0.05 * slope + 0.02 * abs(p50 - center)
        if score < best_score:
            best_score = score
            best_start = start
    return _local_band_center(vals[best_start : best_start + win_n])


def _platform_center_rejecting_rise_tail(
    values: np.ndarray,
    dt: float,
    *,
    min_ns: float = 120.0,
) -> float:
    """Local platform center with protection against a nearby rising-edge tail."""
    vals = np.asarray(values, dtype=np.float64)
    vals = vals[np.isfinite(vals)]
    if len(vals) < 8:
        return float(np.mean(vals)) if len(vals) else 0.0

    level = _quiet_local_platform_level(vals, dt, min_ns=min_ns)
    p05, p10, p50, p70, p80, p90, p95 = (
        float(np.nanpercentile(vals, p)) for p in (5, 10, 50, 70, 80, 90, 95)
    )
    low_band = max(p50 - p10, p70 - p50, p50 - p05, 0.25)
    high_tail = p90 - p50
    if high_tail <= max(4.0, 4.0 * low_band):
        return float(level)

    cutoff = min(p80, p50 + max(2.5, 3.0 * low_band))
    core = vals[vals <= cutoff]
    if len(core) >= max(8, len(vals) // 3):
        top, base = scope_top_base(core)
        if np.isfinite(top) and np.isfinite(base):
            spread = abs(float(top) - float(base))
            if spread <= max(5.0, 5.0 * low_band):
                return 0.5 * (float(top) + float(base))
        return _quiet_local_platform_level(core, dt, min_ns=min_ns)

    top, base = scope_top_base(vals)
    if np.isfinite(top) and np.isfinite(base):
        spread = abs(float(top) - float(base))
        if spread <= max(5.0, 5.0 * low_band):
            return 0.5 * (float(top) + float(base))
    return float(level)


def _refine_eoff_vce_base_before_rise(
    vce: np.ndarray,
    rise_idx: int,
    sw0: int,
    dt: float,
    current_level: float,
    span: float,
) -> float:
    """Refine Eoff Ha in the local stable Vce band just before the main rise."""
    guard = _samples_for_seconds(dt, 20e-9, minimum=2)
    win = _samples_for_seconds(dt, 220e-9, minimum=16)
    hi = max(int(sw0) + 8, int(rise_idx) - guard)
    lo = max(int(sw0), hi - win)
    hi = max(lo + 1, min(hi, len(vce)))
    seg = np.asarray(vce[lo:hi], dtype=np.float64)
    if len(seg) < 8:
        return float(current_level)
    candidate = _scope_band_center(seg)
    if abs(candidate - float(current_level)) <= max(5.0, 0.030 * max(float(span), 1.0)):
        return float(candidate)
    return float(current_level)


def _refine_eoff_ic_base_after_fall(
    ic: np.ndarray,
    fall_idx: int,
    w1: int,
    dt: float,
    current_level: float,
    span: float,
) -> float:
    """Refine Eoff Hb in the local stable Ic band just after the main fall."""
    guard = _samples_for_seconds(dt, 20e-9, minimum=2)
    win = _samples_for_seconds(dt, 220e-9, minimum=16)
    lo = min(max(0, int(w1) - 8), int(fall_idx) + guard)
    hi = min(len(ic), int(w1) + 1, lo + win)
    if hi <= lo + 7:
        return float(current_level)
    seg = np.asarray(ic[lo:hi], dtype=np.float64)
    candidate = _scope_band_center(seg)
    if abs(candidate - float(current_level)) <= max(8.0, 0.035 * max(float(span), 1.0)):
        return float(candidate)
    return float(current_level)


def _plateau_mean_ic_after_off(
    ic: np.ndarray, off_idx: int, w1: int, dt: float
) -> float:
    """关断：Ic 回落平台均值（关断后早期稳态，带符号贴波形；下桥回落为负）。

    早期稳态默认取 off_idx 后约 120ns 均值。但小电流/慢关断工况下，栅极电气关断
    (off_idx) 可能早于电流实际下降——此时早窗仍处导通态，会把导通电流误当作回落平台，
    导致 Eoff 积分终点（Ic 与该平台下降穿越）紧贴起点、窗口塌缩、Eoff≈0。
    用关断前导通电流做参照：早窗均值接近导通电流且窗尾已明显更低时，改用窗尾稳态。
    """
    post = ic[off_idx : w1 + 1].astype(np.float64)
    if len(post) < 8:
        return float(np.mean(post)) if len(post) else 0.0
    early_len = max(12, int(120e-9 / dt))
    settle_len = max(12, int(80e-9 / dt))
    early = (
        float(np.mean(post[:early_len]))
        if len(post) >= early_len
        else float(np.mean(post))
    )
    local_platform = _quiet_local_platform_level(post, dt)
    tail = (
        float(np.mean(post[-settle_len:]))
        if len(post) > settle_len
        else early
    )
    pre0 = max(0, off_idx - int(200e-9 / dt))
    i_on = (
        float(np.percentile(np.abs(ic[pre0:off_idx]), 90))
        if off_idx > pre0
        else 0.0
    )
    triggered = (
        i_on > 1.0
        and abs(early) > 0.7 * i_on
        and abs(early) - abs(tail) > 0.3 * i_on
    )
    if triggered:
        return local_platform
    # 示波器式平台线必须来自本次关断后的局部窗口。早窗若仍被主下降后的
    # 阻尼振荡顶高，则用同一局部窗口的平台中值，避免 Hb 卡在非 base 位置。
    local_delta = abs(early - local_platform)
    local_gate = max(5.0, 0.02 * i_on)
    post_span = float(np.percentile(post, 95) - np.percentile(post, 5))
    if (
        len(post) >= max(24, settle_len)
        and post_span > max(8.0, 0.04 * i_on)
        and local_delta > local_gate
    ):
        return local_platform
    return early


def _plateau_mean_vce_after_on(
    vce: np.ndarray, ic: np.ndarray, on_idx: int, w1: int, dt: float
) -> float:
    """开通：Vce 回落至导通态后的平稳均值（Eon 积分终点 Vce 穿越电平）。"""
    post_v = vce[on_idx : w1 + 1].astype(np.float64)
    post_i = np.abs(ic[on_idx : w1 + 1])
    if len(post_v) < 8:
        return float(np.mean(post_v)) if len(post_v) else 0.0
    local_platform = _quiet_local_platform_level(post_v, dt)
    if not _use_legacy_loss_platform_mode():
        return local_platform
    i_top = float(np.percentile(post_i, 95))
    cond_thr = max(0.5 * i_top, 20.0)
    cond = post_i >= cond_thr
    if int(np.count_nonzero(cond)) >= 8:
        cond_level = float(np.percentile(post_v[cond], 20))
        spread = float(np.nanpercentile(post_v, 95) - np.nanpercentile(post_v, 5))
        if abs(cond_level - local_platform) > max(3.0, 0.025 * max(spread, 1.0)):
            return local_platform
        return cond_level
    settle_len = max(12, int(80e-9 / dt))
    if len(post_v) > settle_len:
        return local_platform
    return float(np.mean(post_v))


def _plateau_mean_vce_before_on(
    vce: np.ndarray, ic: np.ndarray, on_idx: int, w0: int
) -> float:
    """开通：电压下降前关断态 Vce 高平台均值。"""
    pre_end = max(w0 + 5, on_idx)
    pre_v = vce[w0:pre_end].astype(np.float64)
    pre_i = np.abs(ic[w0:pre_end])
    if len(pre_v) < 8:
        return float(np.mean(pre_v)) if len(pre_v) else 0.0
    off_thr = max(0.35 * float(np.percentile(pre_i, 95)), 15.0)
    off_mask = pre_i <= off_thr
    if int(np.count_nonzero(off_mask)) >= 8:
        return float(np.mean(pre_v[off_mask]))
    return float(np.percentile(pre_v, 80))


def _eon_ic_rise_start_index(
    i_seg: np.ndarray,
    ha_ic: float,
    anchor: int,
    dt: float,
    i_top: float,
) -> int:
    """开通 A：Ic 主上升沿第一次穿 Ha。"""
    t_seg = np.arange(len(i_seg), dtype=np.float64) * float(dt)
    ix, _ = _main_edge_level_crossing(
        t_seg,
        i_seg,
        ha_ic,
        i_top,
        "rising",
        anchor,
        dt,
        min_trigger=15.0,
    )
    return int(ix)


def _crossing_pair_index(
    y: np.ndarray,
    level: float,
    direction: str,
    start: int = 0,
    end: int | None = None,
) -> int | None:
    """Return the sample-pair index containing a threshold crossing."""
    if end is None:
        end = len(y) - 1
    start = max(0, int(start))
    end = min(len(y) - 1, int(end))
    if end <= start:
        return None
    yy = np.asarray(y, dtype=np.float64)
    lvl = float(level)
    for k in range(start, end):
        y0, y1 = float(yy[k]), float(yy[k + 1])
        if direction == "falling":
            if y0 >= lvl and y1 <= lvl and y0 > y1:
                return k
        elif direction == "rising":
            if y0 <= lvl and y1 >= lvl and y1 > y0:
                return k
        else:
            raise ValueError(direction)
    return None


def _crossing_pair_indices(
    y: np.ndarray,
    level: float,
    start: int = 0,
    end: int | None = None,
    direction: str | None = None,
) -> list[int]:
    """Return all sample-pair indices containing a level crossing."""
    if end is None:
        end = len(y) - 1
    start = max(0, int(start))
    end = min(len(y) - 1, int(end))
    if end <= start:
        return []
    yy = np.asarray(y, dtype=np.float64)
    lvl = float(level)
    out: list[int] = []
    for k in range(start, end):
        y0, y1 = float(yy[k]), float(yy[k + 1])
        if direction == "falling":
            ok = y0 >= lvl and y1 <= lvl and y0 > y1
        elif direction == "rising":
            ok = y0 <= lvl and y1 >= lvl and y1 > y0
        elif direction is None or direction == "any":
            d0, d1 = y0 - lvl, y1 - lvl
            ok = (d0 == 0.0 and d1 != 0.0) or (d0 * d1 <= 0.0 and d0 != d1)
        else:
            raise ValueError(direction)
        if ok:
            out.append(k)
    return out


def _ns_to_t_units(t_seg: np.ndarray, dt: float, ns: float) -> float:
    diffs = np.diff(np.asarray(t_seg, dtype=np.float64))
    positive = diffs[diffs > 0.0]
    sample_dt = float(np.median(positive)) if len(positive) else float(dt)
    return float(ns) * 1e-3 if sample_dt > 1e-7 else float(ns) * 1e-9


def _level_crossing_time(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    ix: int,
    level: float,
) -> float:
    """Linear interpolation time for a true waveform/level intersection."""
    if len(t_seg) == 0:
        return 0.0
    ix = max(0, min(int(ix), len(t_seg) - 2))
    y0, y1 = float(y_seg[ix]), float(y_seg[ix + 1])
    if y1 == y0:
        return float(t_seg[ix])
    frac = float(np.clip((float(level) - y0) / (y1 - y0), 0.0, 1.0))
    return float(t_seg[ix] + frac * (t_seg[ix + 1] - t_seg[ix]))


@dataclass(frozen=True)
class _ThreeCycleSettleRegion:
    level: float
    start_idx: int
    end_idx: int
    pp_amp: float
    rate_cv: float
    period_cv: float
    strict: bool = False


def _edge_smoothed(y: np.ndarray, points: int) -> np.ndarray:
    arr = np.asarray(y, dtype=np.float64)
    if points <= 1 or len(arr) < 3:
        return arr.copy()
    k = min(int(points), len(arr) if len(arr) % 2 == 1 else len(arr) - 1)
    if k < 3:
        return arr.copy()
    if k % 2 == 0:
        k -= 1
    pad = k // 2
    kernel = np.ones(k, dtype=np.float64) / float(k)
    return np.convolve(np.pad(arr, (pad, pad), mode="edge"), kernel, mode="valid")


def _local_extrema_indices(
    y: np.ndarray,
    start_idx: int,
    end_idx: int,
    dt: float,
    *,
    min_gap_ns: float = 6.0,
) -> list[int]:
    yy = np.asarray(y, dtype=np.float64)
    if len(yy) < 5:
        return []
    lo = max(0, min(int(start_idx), len(yy) - 2))
    hi = max(lo + 2, min(int(end_idx), len(yy) - 1))
    seg = yy[lo : hi + 1]
    if len(seg) < 5:
        return []
    dy = np.diff(seg)
    signs = np.sign(dy)
    last = 0.0
    for idx, sign in enumerate(signs):
        if sign == 0.0:
            signs[idx] = last
        else:
            last = float(sign)
    last = 0.0
    for idx in range(len(signs) - 1, -1, -1):
        if signs[idx] == 0.0:
            signs[idx] = last
        else:
            last = float(signs[idx])
    raw = [lo + idx + 1 for idx in range(len(signs) - 1) if signs[idx] * signs[idx + 1] < 0.0]
    if not raw:
        return []
    min_gap = max(1, int(round(min_gap_ns * 1e-9 / max(float(dt), 1e-15))))
    out: list[int] = []
    for idx in raw:
        if not out or idx - out[-1] >= min_gap:
            out.append(int(idx))
            continue
        prev = out[-1]
        win_lo = max(0, min(prev, idx) - min_gap)
        win_hi = min(len(yy), max(prev, idx) + min_gap + 1)
        med = float(np.nanmedian(yy[win_lo:win_hi]))
        if abs(float(yy[idx]) - med) > abs(float(yy[prev]) - med):
            out[-1] = int(idx)
    return out


def _three_cycle_thresholds(
    settle_profile: str,
    span: float,
    tail_floor: float = 0.0,
) -> list[tuple[bool, float, float, float]]:
    s = max(float(span), 1.0)
    if settle_profile == "err_current":
        if s < 120.0:
            return [
                (True, max(16.0, 0.149 * s), 0.22, 0.22),
                (False, max(18.0, 0.220 * s), 0.28, 0.28),
            ]
        return [
            (True, max(12.0, 0.100 * s), 0.18, 0.20),
            (False, max(14.0, 0.130 * s), 0.22, 0.24),
        ]
    if settle_profile == "current_fall":
        strict = max(10.0, min(18.0, 0.080 * s))
        loose = max(12.0, min(28.0, 0.120 * s))
        return [(True, strict, 0.24, 0.24), (False, loose, 0.30, 0.30)]
    if settle_profile == "voltage_fall":
        if s >= 700.0:
            strict = max(7.0, min(22.0, 0.024 * s))
            loose = max(10.0, min(35.0, 0.040 * s))
        else:
            strict = max(7.0, min(14.0, max(0.030 * s, 2.2 * tail_floor)))
            loose = max(9.0, min(22.0, max(0.050 * s, 3.0 * tail_floor)))
        return [(True, strict, 0.24, 0.24), (False, loose, 0.32, 0.32)]
    cap = max(5.0, min(22.0, 0.035 * s))
    return [(True, cap, 0.25, 0.25), (False, 1.5 * cap, 0.32, 0.32)]


def _first_crossing_in_region(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    level: float,
    start_idx: int,
    end_idx: int,
    dt: float,
) -> tuple[int, float] | None:
    lo = max(0, min(int(start_idx), len(y_seg) - 2))
    hi_extra = max(2, int(round(30e-9 / max(float(dt), 1e-15))))
    hi = max(lo + 1, min(int(end_idx) + hi_extra, len(y_seg) - 2))
    crosses = _crossing_pair_indices(y_seg, float(level), lo, hi, direction=None)
    if not crosses:
        return None
    ix = int(crosses[0])
    return ix, _level_crossing_time(t_seg, y_seg, ix, float(level))


@dataclass(frozen=True)
class _EnvelopeGate:
    start_idx: int
    threshold: float
    last_extremum_idx: int
    significant_count: int


@dataclass(frozen=True)
class _LossCursorEventGate:
    start_idx: int
    end_idx: int
    cap_idx: int
    threshold: float
    last_extremum_idx: int
    significant_count: int
    classification: str


def _use_legacy_loss_cursor_mode() -> bool:
    mode = os.environ.get("DPT_LOSS_CURSOR_MODE", "").strip().lower()
    return mode in {"legacy", "old", "current", "off", "0"}


def _use_legacy_loss_platform_mode() -> bool:
    mode = os.environ.get("DPT_LOSS_PLATFORM_MODE", "").strip().lower()
    if mode in {"legacy", "old", "current", "off", "0"}:
        return True
    return _use_legacy_loss_cursor_mode()


def _samples_for_seconds(dt: float, seconds: float, *, minimum: int = 1) -> int:
    return max(int(minimum), int(round(float(seconds) / max(float(dt), 1e-15))))


def _robust_tail_floor(dev: np.ndarray) -> float:
    vals = np.asarray(dev, dtype=np.float64)
    if len(vals) == 0:
        return 0.0
    tail_len = max(8, len(vals) // 5)
    tail = vals[-tail_len:]
    med = float(np.nanmedian(tail)) if len(tail) else 0.0
    mad = float(np.nanmedian(np.abs(tail - med))) if len(tail) else 0.0
    return med + 3.0 * 1.4826 * mad


def _loss_envelope_threshold(
    settle_profile: str,
    span: float,
    tail_floor: float,
) -> float:
    """Visible-envelope cutoff; smoothing is for judgment only, not cursor placement."""
    s = max(float(span), 1.0)
    noise_hint = min(8.0, 2.0 * max(float(tail_floor), 0.0))
    if settle_profile == "current_fall":
        return max(5.0, min(12.0, 0.016 * s), noise_hint)
    if settle_profile == "voltage_fall":
        return max(7.0, min(10.0, 0.012 * s), noise_hint)
    return max(5.0, min(18.0, 0.020 * s), noise_hint)


def _loss_cursor_event_gate_after_main_edge(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    level: float,
    first_ix: int,
    end_ix: int,
    legacy_t: float,
    dt: float,
    span: float,
    tail_floor: float,
    settle_profile: str,
) -> _LossCursorEventGate:
    """Gate Eoff/Eon right-cursor judgment to a visible local event window.

    The gate starts at the main-edge platform crossing, is never intentionally
    shorter than about 200 ns when enough samples exist, expands to include the
    local ringing packet, and then stops at a bounded event cap so long LC tails
    cannot keep dragging the B cursor.
    """
    yy = np.asarray(y_seg, dtype=np.float64)
    tt = np.asarray(t_seg, dtype=np.float64)
    n = min(len(yy), len(tt))
    if n < 2:
        return _LossCursorEventGate(0, 0, 0, 0.0, 0, 0, "unknown")

    lo = max(0, min(int(first_ix), n - 2))
    hi_limit = max(lo + 1, min(int(end_ix), n - 2))
    base_n = _samples_for_seconds(dt, 200e-9, minimum=16)
    guard_n = _samples_for_seconds(
        dt,
        (45e-9 if settle_profile == "current_fall" else 35e-9),
        minimum=2,
    )
    # Eoff current ringing can legitimately be wider than Eon Vce fall, but both
    # need an upper bound so a later low-energy tail is not treated as the same
    # switching event.
    cap_ns = 850.0 if settle_profile == "current_fall" else 680.0
    cap_n = _samples_for_seconds(dt, cap_ns * 1e-9, minimum=base_n)
    cap_idx = min(hi_limit, lo + cap_n)
    min_end = min(cap_idx, lo + base_n)

    legacy_idx = int(np.searchsorted(tt[:n], float(legacy_t), side="left"))
    legacy_idx = max(lo, min(legacy_idx, cap_idx))
    event_end = max(min_end, min(cap_idx, legacy_idx + guard_n))

    threshold = _loss_envelope_threshold(settle_profile, span, tail_floor)
    last_extremum = lo
    significant_count = 0
    classification = "smooth"

    if cap_idx > lo + _samples_for_seconds(dt, 40e-9, minimum=8):
        smooth_n = _samples_for_seconds(dt, 4e-9, minimum=3)
        smooth_y = _edge_smoothed(yy[:n], smooth_n)
        extrema_lo = min(cap_idx - 1, lo + _samples_for_seconds(dt, 4e-9, minimum=1))
        extrema = _local_extrema_indices(
            smooth_y, extrema_lo, cap_idx + 1, dt, min_gap_ns=5.0
        )
        significant = [
            int(idx)
            for idx in extrema
            if abs(float(smooth_y[int(idx)]) - float(level)) >= threshold
        ]
        significant_count = len(significant)
        if significant:
            last_extremum = int(significant[-1])
            event_end = max(event_end, min(cap_idx, last_extremum + guard_n))
        view = smooth_y[lo : event_end + 1]
        local_pp = (
            float(np.nanmax(view) - np.nanmin(view))
            if len(view) >= 4
            else 0.0
        )
        if significant_count >= (4 if settle_profile == "current_fall" else 5):
            classification = "ringing"
        elif significant_count >= 2 or local_pp > max(2.2 * threshold, 0.040 * max(float(span), 1.0)):
            classification = "damped"

    return _LossCursorEventGate(
        int(lo),
        int(max(lo + 1, min(event_end, cap_idx))),
        int(cap_idx),
        float(threshold),
        int(last_extremum),
        int(significant_count),
        classification,
    )


def _loss_envelope_gate_after_main_edge(
    y_seg: np.ndarray,
    level: float,
    first_ix: int,
    end_ix: int,
    dt: float,
    span: float,
    tail_floor: float,
    settle_profile: str,
) -> _EnvelopeGate | None:
    yy = np.asarray(y_seg, dtype=np.float64)
    if len(yy) < 12:
        return None
    if settle_profile == "current_fall" and not (330.0 <= float(span) <= 520.0):
        return None
    lo = max(0, min(int(first_ix), len(yy) - 2))
    hi = max(lo + 2, min(int(end_ix), len(yy) - 2))
    if hi <= lo + _samples_for_seconds(dt, 30e-9, minimum=6):
        return None

    smooth_n = _samples_for_seconds(dt, 4e-9, minimum=3)
    smooth_y = _edge_smoothed(yy, smooth_n)
    extrema_lo = min(hi - 1, lo + _samples_for_seconds(dt, 4e-9, minimum=1))
    extrema = _local_extrema_indices(
        smooth_y, extrema_lo, hi + 1, dt, min_gap_ns=5.0
    )
    if not extrema:
        return None

    threshold = _loss_envelope_threshold(settle_profile, span, tail_floor)
    significant = [
        int(idx)
        for idx in extrema
        if abs(float(smooth_y[int(idx)]) - float(level)) >= threshold
    ]
    min_count = 4 if settle_profile == "current_fall" else 5
    if len(significant) < min_count:
        return None

    first_sig = significant[0]
    last_sig = significant[-1]
    packet_span = (last_sig - first_sig) * max(float(dt), 1e-15)
    if packet_span < 35e-9:
        return None

    guard = 10e-9 if settle_profile == "current_fall" else 8e-9
    gate_idx = min(hi, last_sig + _samples_for_seconds(dt, guard, minimum=1))
    if gate_idx <= lo:
        return None
    return _EnvelopeGate(
        int(gate_idx),
        float(threshold),
        int(last_sig),
        int(len(significant)),
    )


def _first_crossing_after_gate(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    level: float,
    crosses: list[int],
    gate_idx: int,
) -> tuple[int, float] | None:
    if len(t_seg) < 2:
        return None
    gate_idx = max(0, min(int(gate_idx), len(t_seg) - 2))
    gate_t = float(t_seg[gate_idx])
    for ix in crosses:
        k = max(0, min(int(ix), len(t_seg) - 2))
        t_cross = _level_crossing_time(t_seg, y_seg, k, float(level))
        if t_cross >= gate_t:
            return k, float(t_cross)
    return None


def _first_crossing_after_time_from_pairs(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    level: float,
    crosses: list[int],
    t_after: float,
) -> tuple[int, float] | None:
    if len(t_seg) < 2:
        return None
    for ix in crosses:
        k = max(0, min(int(ix), len(t_seg) - 2))
        t_cross = _level_crossing_time(t_seg, y_seg, k, float(level))
        if t_cross >= float(t_after):
            return k, float(t_cross)
    return None


def _voltage_fall_ringing_candidate_is_stable(
    y_seg: np.ndarray,
    level: float,
    candidate_ix: int,
    dt: float,
    span: float,
) -> bool:
    """Audit an Eon Vce candidate before allowing it to exceed legacy timing."""
    yy = np.asarray(y_seg, dtype=np.float64)
    if len(yy) < 12:
        return False
    ix = max(0, min(int(candidate_ix), len(yy) - 2))
    local_n = _samples_for_seconds(dt, 200e-9, minimum=16)
    future_n = _samples_for_seconds(dt, 320e-9, minimum=local_n)
    local = yy[ix : min(len(yy), ix + local_n)]
    future = yy[ix : min(len(yy), ix + future_n)]
    if len(local) < 12 or len(future) < len(local):
        return False
    local_dev = np.abs(local - float(level))
    future_dev = np.abs(future - float(level))
    local_pp = float(np.nanmax(local) - np.nanmin(local))
    p85 = float(np.nanpercentile(local_dev, 85))
    p95 = float(np.nanpercentile(local_dev, 95))
    future_max = float(np.nanmax(future_dev))
    s = max(float(span), 1.0)
    pp_limit = max(18.0, min(34.0, 0.045 * s))
    p85_limit = max(5.0, min(8.0, 0.012 * s))
    p95_limit = max(6.0, min(10.0, 0.014 * s))
    rebound_limit = max(14.0, min(24.0, 0.032 * s), 2.8 * max(p95, 1.0))
    return (
        local_pp <= pp_limit
        and p85 <= p85_limit
        and p95 <= p95_limit
        and future_max <= rebound_limit
    )


def _first_sustained_rise_crossing(
    y_seg: np.ndarray,
    level: float,
    raw_lo: int,
    raw_hi: int,
    k_trigger: int,
    dt: float,
    span: float,
) -> int | None:
    """First raw level crossing that belongs to the main rising edge."""
    yy = np.asarray(y_seg, dtype=np.float64)
    if len(yy) < 2:
        return None
    lo = max(0, min(int(raw_lo), len(yy) - 2))
    hi = max(lo, min(int(raw_hi), int(k_trigger), len(yy) - 2))
    candidates: list[int] = []
    lvl = float(level)
    for kk in range(lo, hi + 1):
        y0, y1 = float(yy[kk]), float(yy[kk + 1])
        if y0 <= lvl < y1 and y1 > y0:
            candidates.append(int(kk))
    if not candidates:
        return None

    edge_gate: int | None = None
    edge_hi = max(lo + 2, min(len(yy) - 1, int(k_trigger) + _samples_for_seconds(dt, 90e-9, minimum=8)))
    edge_seg = yy[lo : edge_hi + 1]
    if len(edge_seg) >= 12:
        smooth_n = _samples_for_seconds(dt, 8e-9, minimum=5)
        smooth = _edge_smoothed(edge_seg, smooth_n)
        deriv = np.gradient(smooth, max(float(dt), 1e-15)) / 1e9
        pos = deriv[np.isfinite(deriv) & (deriv > 0.0)]
        if len(pos):
            peak_der = float(np.nanmax(pos))
            der_gate = max(
                0.14 * peak_der,
                min(2.0, max(0.12, 0.0015 * max(float(span), 1.0))),
            )
            peak_rel = int(np.nanargmax(deriv))
            scan_hi = max(0, min(peak_rel, int(k_trigger) - lo))
            hold_n = _samples_for_seconds(dt, 10e-9, minimum=3)
            rise_n = _samples_for_seconds(dt, 70e-9, minimum=8)
            min_future_rise = max(4.0, min(35.0, 0.035 * max(float(span), 1.0)))
            for rel in range(0, scan_hi + 1):
                hold = deriv[rel : min(len(deriv), rel + hold_n)]
                future = smooth[rel : min(len(smooth), rel + rise_n)]
                if len(hold) < 3 or len(future) < 3:
                    continue
                if float(np.nanpercentile(hold, 60)) < der_gate:
                    continue
                if float(np.nanmax(future)) - float(smooth[rel]) < min_future_rise:
                    continue
                edge_gate = lo + rel
                break
    if edge_gate is not None:
        margin = _samples_for_seconds(dt, 8e-9, minimum=1)
        gated = [kk for kk in candidates if kk >= max(lo, edge_gate - margin)]
        if gated:
            candidates = gated
        elif 500.0 <= float(span) < 1100.0:
            pre_margin_ns = 35.0 if float(span) < 700.0 else 25.0
            pre_margin = _samples_for_seconds(dt, pre_margin_ns * 1e-9, minimum=1)
            post_margin = _samples_for_seconds(dt, 8e-9, minimum=1)
            gate_lo = max(lo, edge_gate - pre_margin)
            gate_hi = min(hi, edge_gate + post_margin)
            near_edge = [kk for kk in candidates if gate_lo <= kk <= gate_hi]
            if near_edge:
                candidates = near_edge

    hold_n = _samples_for_seconds(dt, 18e-9, minimum=4)
    rise_n = _samples_for_seconds(dt, 70e-9, minimum=8)
    min_sustained = lvl - max(1.0, 0.006 * max(float(span), 1.0))
    min_rise = max(4.0, min(35.0, 0.045 * max(float(span), 1.0)))
    for kk in candidates:
        hold = yy[kk + 1 : min(len(yy), kk + 1 + hold_n)]
        rise = yy[kk + 1 : min(len(yy), kk + 1 + rise_n)]
        if len(hold) < 3 or len(rise) < 3:
            continue
        sustained = float(np.nanpercentile(hold, 60)) >= min_sustained
        local_rise = float(np.nanmax(rise)) - max(float(yy[kk]), lvl)
        if sustained and local_rise >= min_rise:
            return int(kk)
    return int(candidates[-1])


def _low_current_main_foot_rising_crossing(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    base_level: float,
    edge_top: float,
    current_t: float,
    dt: float,
    *,
    foot_frac: float,
    max_delay_ns: float,
) -> tuple[int, float] | None:
    """Use a low-current foot only to gate the main edge, then return Ic=Base.

    The small percentage foot is useful for rejecting pre-edge ripple, but it is
    not the declared Ha level.  Once that foot is found, project the cursor back
    to the nearest preceding raw rising crossing of ``base_level`` so the final
    A cursor remains a real waveform/Ha intersection.
    """
    if len(t_seg) < 2:
        return None
    tt = np.asarray(t_seg, dtype=np.float64)
    yy = np.asarray(y_seg, dtype=np.float64)
    span = abs(float(edge_top) - float(base_level))
    if span < 20.0:
        return None

    foot_level = float(base_level) + float(foot_frac) * span
    sample_dt = max(float(dt), 1e-15)
    start_t = float(current_t) - sample_dt
    end_t = float(current_t) + float(max_delay_ns) * 1e-9
    lo = max(
        0,
        min(int(np.searchsorted(tt, start_t, side="left")), len(yy) - 2),
    )
    hi = max(
        lo,
        min(int(np.searchsorted(tt, end_t, side="right")), len(yy) - 2),
    )

    foot_ix: int | None = None
    foot_t: float | None = None
    for k in range(lo, hi + 1):
        y0, y1 = float(yy[k]), float(yy[k + 1])
        if y0 <= foot_level < y1 and y1 > y0:
            candidate_t = _level_crossing_time(tt, yy, int(k), foot_level)
            foot_ix = int(k)
            foot_t = float(candidate_t)
            break
    if foot_ix is None or foot_t is None:
        return None

    for k in range(foot_ix, lo - 1, -1):
        y0, y1 = float(yy[k]), float(yy[k + 1])
        if y0 <= float(base_level) < y1 and y1 > y0:
            base_t = _level_crossing_time(tt, yy, int(k), float(base_level))
            if base_t <= foot_t + sample_dt:
                return int(k), float(base_t)
    return None


def _smooth_early_crossing_after_main_edge(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    level: float,
    crosses: list[int],
    first_t: float,
    legacy_t: float,
    dt: float,
    span: float,
    settle_profile: str,
    event_gate: _LossCursorEventGate | None = None,
) -> tuple[int, float] | None:
    """Early exit for large, already-flat Eoff current falls."""
    if settle_profile != "current_fall" or len(crosses) == 0:
        return None
    if float(span) < 650.0:
        return None
    if float(legacy_t) - float(first_t) < 90e-9:
        return None

    yy = np.asarray(y_seg, dtype=np.float64)
    tt = np.asarray(t_seg, dtype=np.float64)
    if len(yy) < 12 or len(tt) != len(yy):
        return None
    ix = max(0, min(int(crosses[0]), len(yy) - 2))
    candidate_t = _level_crossing_time(tt, yy, ix, float(level))
    if candidate_t > float(first_t) + 25e-9:
        return None

    fwd_n = _samples_for_seconds(dt, 200e-9, minimum=16)
    future_n = _samples_for_seconds(dt, 360e-9, minimum=fwd_n)
    event_end = len(yy)
    if event_gate is not None:
        event_end = max(ix + fwd_n, min(len(yy), int(event_gate.end_idx) + 1))
    local = yy[ix : min(event_end, ix + fwd_n)]
    future = yy[ix : min(event_end, ix + future_n)]
    if len(local) < 12 or len(future) < len(local):
        return None
    local_dev = np.abs(local - float(level))
    future_dev = np.abs(future - float(level))
    local_pp = float(np.nanmax(local) - np.nanmin(local))
    p95 = float(np.nanpercentile(local_dev, 95))
    med = float(np.nanmedian(local_dev))
    future_p95 = float(np.nanpercentile(future_dev, 95))
    future_max = float(np.nanmax(future_dev))

    p95_limit = max(12.0, min(16.0, 0.017 * float(span)))
    med_limit = max(4.0, min(8.0, 0.010 * float(span)))
    pp_limit = max(36.0, min(52.0, 0.060 * float(span)))
    if local_pp > pp_limit or p95 > p95_limit or med > med_limit:
        return None
    if future_p95 > max(p95_limit, 1.20 * p95):
        return None
    if future_max > max(2.2 * p95_limit, p95 + 18.0):
        return None
    return int(ix), float(candidate_t)


def _three_full_cycle_settle_region(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    *,
    level_hint: float | None,
    start_idx: int,
    end_idx: int,
    dt: float,
    span: float,
    settle_profile: str,
    tail_floor: float = 0.0,
    seed_start_extremum: bool = False,
) -> _ThreeCycleSettleRegion | None:
    """First low-amplitude region where three complete adjacent cycles agree.

    The selected group is based on 7 consecutive extrema:
    high-low-high-low-high-low-high or the inverse. Smoothing is used only for
    extrema/rate detection; the returned level and all cursor crossings stay on
    the raw waveform.
    """
    yy = np.asarray(y_seg, dtype=np.float64)
    tt = np.asarray(t_seg, dtype=np.float64)
    if len(yy) < 12 or len(tt) != len(yy):
        return None
    k0 = max(0, min(int(start_idx), len(yy) - 2))
    k_end = max(k0 + 2, min(int(end_idx), len(yy) - 1))
    if k_end <= k0 + 8:
        return None
    smooth_n = max(3, int(round(4e-9 / max(float(dt), 1e-15))))
    smooth_y = _edge_smoothed(yy, smooth_n)
    search_lo = min(k_end - 2, k0 + max(1, int(round(5e-9 / max(float(dt), 1e-15)))))
    extrema = _local_extrema_indices(smooth_y, search_lo, k_end, dt)
    if seed_start_extremum and (not extrema or extrema[0] - k0 > 2):
        extrema = [k0] + [idx for idx in extrema if idx > k0]
    if len(extrema) < 7:
        return None

    min_period = 10e-9
    max_period = 320e-9
    for strict, amp_ceiling, rate_cv_limit, period_cv_limit in _three_cycle_thresholds(
        settle_profile, span, tail_floor
    ):
        for pos in range(0, len(extrema) - 6):
            pts = extrema[pos : pos + 7]
            cycle_amps: list[float] = []
            cycle_periods: list[float] = []
            for offset in (0, 2, 4):
                a = int(pts[offset])
                b = int(pts[offset + 2])
                if b <= a:
                    break
                block = smooth_y[a : b + 1]
                cycle_amps.append(float(np.nanmax(block) - np.nanmin(block)))
                cycle_periods.append(float(tt[b] - tt[a]))
            if len(cycle_amps) != 3 or len(cycle_periods) != 3:
                continue
            periods = np.asarray(cycle_periods, dtype=np.float64)
            if np.any(periods < min_period) or np.any(periods > max_period):
                continue
            amps = np.asarray(cycle_amps, dtype=np.float64)
            rates = amps / np.maximum(periods, 1e-30)
            mean_rate = float(np.nanmean(rates))
            mean_period = float(np.nanmean(periods))
            if mean_rate <= 0.0 or mean_period <= 0.0:
                continue
            rate_cv = float(np.nanstd(rates) / mean_rate)
            period_cv = float(np.nanstd(periods) / mean_period)
            pp_amp = float(np.nanmax(amps))
            if pp_amp > amp_ceiling or rate_cv > rate_cv_limit or period_cv > period_cv_limit:
                continue
            g0 = int(pts[0])
            g1 = int(pts[-1])
            raw = yy[g0 : g1 + 1]
            if len(raw) < 4:
                continue
            region_level = (
                float(level_hint)
                if level_hint is not None
                else 0.5 * (float(np.nanmax(raw)) + float(np.nanmin(raw)))
            )
            if level_hint is not None:
                center = 0.5 * (float(np.nanmax(raw)) + float(np.nanmin(raw)))
                near_limit = max(1.7 * amp_ceiling, 0.060 * max(float(span), 1.0), 10.0)
                if abs(center - float(level_hint)) > near_limit:
                    continue
            return _ThreeCycleSettleRegion(
                float(region_level),
                g0,
                g1,
                pp_amp,
                rate_cv,
                period_cv,
                strict=strict,
            )
    return None


def _legacy_settled_level_crossing_after_main_edge(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    level: float,
    first_ix: int,
    first_t: float,
    dt: float,
    edge_top: float,
    *,
    direction: str,
    end: int | None = None,
    settle_profile: str = "generic",
) -> tuple[int, float]:
    """Eoff/Eon right cursor after the selected main falling edge settles.

    This is not the Err/IRM-peak rule. Eoff calls it with Ic after the turn-off
    current falling edge; Eon calls it with Vce after the turn-on voltage falling
    edge. The first main-edge crossing only proves the selected waveform touched
    the local platform; the cursor then includes meaningful local damping and
    lands on the real waveform/platform intersection. Long low-level tail noise
    stays out.
    """
    if len(t_seg) < 2:
        return 0, float(t_seg[0]) if len(t_seg) else 0.0
    yy = np.asarray(y_seg, dtype=np.float64)
    tt = np.asarray(t_seg, dtype=np.float64)
    lvl = float(level)
    first_ix = max(0, min(int(first_ix), len(yy) - 2))
    end_ix = (
        len(yy) - 2
        if end is None
        else max(first_ix + 1, min(int(end), len(yy) - 2))
    )
    if end_ix <= first_ix + 2:
        return first_ix, float(first_t)

    span = max(
        abs(float(edge_top) - lvl),
        float(np.nanpercentile(np.abs(yy[first_ix : end_ix + 2] - lvl), 95)),
        1.0,
    )
    dev = np.abs(yy[first_ix : end_ix + 2] - lvl)
    if len(dev) < 8:
        return first_ix, float(first_t)

    tail_len = max(8, len(dev) // 5)
    tail = dev[-tail_len:]
    tail_med = float(np.nanmedian(tail)) if len(tail) else 0.0
    tail_mad = (
        float(np.nanmedian(np.abs(tail - tail_med)))
        if len(tail)
        else 0.0
    )
    tail_floor = tail_med + 3.0 * 1.4826 * tail_mad
    crosses = _crossing_pair_indices(
        yy,
        lvl,
        first_ix,
        end_ix,
        direction=None,
    )
    if not crosses:
        return first_ix, float(first_t)

    # Choose the first real platform crossing after the locally visible ringing
    # has become small enough. This is intentionally a "first pass" rule; do not
    # chase a later, smaller tail window after the process has already settled.
    pre_n = max(2, int(round(40e-9 / max(float(dt), 1e-15))))
    post_n = max(4, int(round(160e-9 / max(float(dt), 1e-15))))
    smooth_n = max(3, int(round(8e-9 / max(float(dt), 1e-15))))
    smooth_y = yy
    if smooth_n > 1 and len(yy) >= smooth_n:
        kernel = np.ones(smooth_n, dtype=np.float64) / float(smooth_n)
        smooth_y = np.convolve(yy, kernel, mode="same")
    current_pp_tol: float | None = None
    if settle_profile == "voltage_fall":
        if span >= 700.0:
            visible_cap = max(7.0, min(22.0, 0.024 * span))
        else:
            visible_cap = max(7.0, min(12.0, 2.2 * tail_floor))
        p75_tol = max(1.0, 0.0132 * span, min(0.024 * span, 0.90 * visible_cap))
        p85_tol = max(1.0, 0.0140 * span, min(0.030 * span, visible_cap))
        p95_tol = max(2.0, min(0.060 * span, 1.35 * visible_cap))
    elif settle_profile == "current_fall":
        visible_cap = max(10.0, min(18.0, 0.080 * span))
        p75_tol = max(1.0, min(0.080 * span, 0.55 * visible_cap))
        p85_tol = max(1.0, min(0.100 * span, 0.60 * visible_cap))
        p95_tol = max(2.0, min(0.130 * span, 0.80 * visible_cap))
        if 180.0 <= span <= 500.0:
            current_pp_tol = max(12.0, min(15.0, 0.055 * span))
    else:
        visible_cap = max(5.0, min(20.0, max(2.2 * tail_floor, 0.025 * span)))
        p75_tol = max(1.0, min(0.026 * span, 0.95 * visible_cap))
        p85_tol = max(1.0, min(0.032 * span, visible_cap))
        p95_tol = max(2.0, min(0.065 * span, 1.45 * visible_cap))
    p50_tol = max(1.0, 0.020 * span, 0.45 * visible_cap)
    min_delay_s = 0.0
    if settle_profile == "current_fall":
        min_delay_s = 190e-9 if tail_floor < 1.0 else 140e-9
    elif settle_profile == "voltage_fall":
        min_delay_s = 0.0 if span >= 700.0 else 45e-9

    chosen: int | None = None
    for ix in crosses:
        candidate_t = _level_crossing_time(tt, yy, int(ix), lvl)
        if candidate_t < float(first_t) + min_delay_s:
            continue
        lo = max(0, int(ix) - pre_n)
        hi = min(end_ix + 2, int(ix) + post_n)
        local_dev = np.abs(yy[lo:hi] - lvl)
        if len(local_dev) < 8:
            continue
        p50, p75, p85, p95 = (
            float(np.nanpercentile(local_dev, pct))
            for pct in (50, 75, 85, 95)
        )
        if current_pp_tol is not None:
            pp_hi = min(end_ix + 2, int(ix) + post_n)
            pp_seg = smooth_y[int(ix) : pp_hi]
            local_pp = (
                float(np.nanmax(pp_seg) - np.nanmin(pp_seg))
                if len(pp_seg) >= 4
                else float("inf")
            )
            if local_pp > current_pp_tol:
                continue
        if (
            p50 <= p50_tol
            and p75 <= p75_tol
            and p85 <= p85_tol
            and p95 <= p95_tol
        ):
            chosen = int(ix)
            break
    if chosen is None:
        chosen = int(crosses[-1])
    chosen_t = _level_crossing_time(tt, yy, chosen, lvl)
    if chosen_t < float(first_t):
        return first_ix, float(first_t)

    cycle_region = _three_full_cycle_settle_region(
        tt,
        yy,
        level_hint=lvl,
        start_idx=first_ix,
        end_idx=end_ix + 1,
        dt=dt,
        span=span,
        settle_profile=settle_profile,
        tail_floor=tail_floor,
    )
    if cycle_region is not None:
        cycle_cross = _first_crossing_in_region(
            tt,
            yy,
            lvl,
            cycle_region.start_idx,
            cycle_region.end_idx,
            dt,
        )
        if cycle_cross is not None and cycle_cross[1] >= float(first_t):
            cycle_ix, cycle_t = cycle_cross
            if settle_profile == "voltage_fall":
                max_extra_delay = 35e-9
            elif settle_profile == "current_fall" and span < 180.0:
                max_extra_delay = 320e-9
            else:
                max_extra_delay = 45e-9
            if cycle_t <= chosen_t + max_extra_delay:
                return int(cycle_ix), float(cycle_t)
    return chosen, float(chosen_t)


def _settled_level_crossing_after_main_edge(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    level: float,
    first_ix: int,
    first_t: float,
    dt: float,
    edge_top: float,
    *,
    direction: str,
    end: int | None = None,
    settle_profile: str = "generic",
) -> tuple[int, float]:
    """Eoff/Eon B: wait for the visible main ringing envelope, then use raw Hb crossing."""
    legacy_ix, legacy_t = _legacy_settled_level_crossing_after_main_edge(
        t_seg,
        y_seg,
        level,
        first_ix,
        first_t,
        dt,
        edge_top,
        direction=direction,
        end=end,
        settle_profile=settle_profile,
    )
    if _use_legacy_loss_cursor_mode():
        return legacy_ix, legacy_t

    if settle_profile not in {"current_fall", "voltage_fall"} or len(t_seg) < 2:
        return legacy_ix, legacy_t

    yy = np.asarray(y_seg, dtype=np.float64)
    tt = np.asarray(t_seg, dtype=np.float64)
    lvl = float(level)
    first_ix = max(0, min(int(first_ix), len(yy) - 2))
    end_ix = len(yy) - 2 if end is None else max(first_ix + 1, min(int(end), len(yy) - 2))
    if end_ix <= first_ix + 2:
        return legacy_ix, legacy_t

    span = max(
        abs(float(edge_top) - lvl),
        float(np.nanpercentile(np.abs(yy[first_ix : end_ix + 2] - lvl), 95)),
        1.0,
    )
    dev = np.abs(yy[first_ix : end_ix + 2] - lvl)
    if len(dev) < 8:
        return legacy_ix, legacy_t
    tail_floor = _robust_tail_floor(dev)
    event_gate = _loss_cursor_event_gate_after_main_edge(
        tt,
        yy,
        lvl,
        first_ix,
        end_ix,
        legacy_t,
        dt,
        span,
        tail_floor,
        settle_profile,
    )
    event_end_ix = max(first_ix + 1, min(int(event_gate.end_idx), end_ix))
    crosses = _crossing_pair_indices(yy, lvl, first_ix, event_end_ix, direction=None)
    if not crosses:
        return legacy_ix, legacy_t

    early = _smooth_early_crossing_after_main_edge(
        tt,
        yy,
        lvl,
        crosses,
        first_t,
        legacy_t,
        dt,
        span,
        settle_profile,
        event_gate,
    )
    if early is not None:
        return early

    if (
        settle_profile == "current_fall"
        and event_gate.classification == "smooth"
        and event_gate.significant_count <= 1
        and span < 120.0
    ):
        late_smooth = _first_crossing_after_time_from_pairs(
            tt,
            yy,
            lvl,
            crosses,
            float(first_t) + 120e-9,
        )
        if late_smooth is not None:
            late_ix, late_t = late_smooth
            if late_t <= float(tt[event_end_ix]) + max(float(dt), 1e-15):
                return int(late_ix), float(late_t)

    if (
        settle_profile == "current_fall"
        and event_gate.classification == "ringing"
        and event_gate.significant_count >= 10
        and 180.0 <= span <= 360.0
        and float(legacy_t) - float(first_t) >= 180e-9
    ):
        mid_packet = _first_crossing_after_time_from_pairs(
            tt,
            yy,
            lvl,
            crosses,
            float(legacy_t) - 100e-9,
        )
        if mid_packet is not None:
            mid_ix, mid_t = mid_packet
            if float(first_t) <= mid_t <= float(legacy_t) - 20e-9:
                return int(mid_ix), float(mid_t)

    gate = _loss_envelope_gate_after_main_edge(
        yy,
        lvl,
        first_ix,
        event_end_ix,
        dt,
        span,
        tail_floor,
        settle_profile,
    )
    if gate is None:
        return legacy_ix, legacy_t

    candidate = _first_crossing_after_gate(tt, yy, lvl, crosses, gate.start_idx)
    if candidate is None:
        return legacy_ix, legacy_t
    candidate_ix, candidate_t = candidate

    if candidate_t < float(first_t):
        return legacy_ix, legacy_t
    event_end_t = float(tt[event_end_ix])
    if candidate_t > event_end_t + max(float(dt), 1e-15):
        return legacy_ix, legacy_t
    max_extra_delay = 260e-9 if settle_profile == "current_fall" else 90e-9
    if (
        settle_profile == "voltage_fall"
        and event_gate.classification == "ringing"
        and event_gate.significant_count >= 5
        and _voltage_fall_ringing_candidate_is_stable(
            yy,
            lvl,
            candidate_ix,
            dt,
            span,
        )
    ):
        max_extra_delay = 260e-9
    if candidate_t > float(legacy_t) + max_extra_delay:
        if (
            settle_profile == "voltage_fall"
            and event_gate.classification == "ringing"
            and event_gate.significant_count >= 6
            and span >= 500.0
        ):
            delayed = _first_crossing_after_time_from_pairs(
                tt,
                yy,
                lvl,
                crosses,
                float(legacy_t) + 150e-9,
            )
            if delayed is not None:
                delayed_ix, delayed_t = delayed
                if delayed_t <= event_end_t + max(float(dt), 1e-15):
                    return int(delayed_ix), float(delayed_t)
        return legacy_ix, legacy_t
    return int(candidate_ix), float(candidate_t)


def _main_edge_level_crossing(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    level: float,
    edge_top: float,
    direction: str,
    anchor: int,
    dt: float,
    *,
    fit_pre_ns: float = 180.0,
    fit_post_ns: float = 80.0,
    trigger_frac: float = 0.50,
    fit_low_frac: float = 0.10,
    fit_high_frac: float = 0.35,
    min_trigger: float = 30.0,
    prefer_raw_crossing: bool = True,
    raw_window_ns: float = 80.0,
    first_sustained_rise: bool = False,
) -> tuple[int, float]:
    """主上升/下降沿进入平台电平的交点。

    先用远离平台噪声的主沿有效电平定位主沿，再在主沿 10%~35% 区间拟合，
    回推到平台电平。这样平台附近的小振铃/噪声穿越不会抢走 A/B 光标。
    """
    if len(t_seg) < 2:
        return 0, float(t_seg[0]) if len(t_seg) else 0.0
    yy = np.asarray(y_seg, dtype=np.float64)
    tt = np.asarray(t_seg, dtype=np.float64)
    lvl = float(level)
    span = max(abs(float(edge_top) - lvl), 1.0)
    anchor = max(0, min(int(anchor), len(yy) - 2))
    trigger_step = max(float(min_trigger), float(trigger_frac) * span)
    trigger_step = min(trigger_step, 0.85 * span)
    trigger = lvl + trigger_step
    low = lvl + float(fit_low_frac) * span
    high = lvl + float(fit_high_frac) * span
    if low > high:
        low, high = high, low

    k_trigger: int | None = None
    if direction == "rising":
        for k in range(anchor, len(yy)):
            if float(yy[k]) >= trigger:
                k_trigger = k
                break
    elif direction == "falling":
        for k in range(anchor, len(yy)):
            if float(yy[k]) <= trigger:
                k_trigger = k
                break
    else:
        raise ValueError(direction)

    if k_trigger is None:
        ix = _crossing_pair_index(yy, lvl, direction, anchor)
        if ix is not None:
            return int(ix), _eoff_crossing_time_us(tt, yy, int(ix), lvl, direction)
        return anchor, float(tt[anchor])

    fit_pre = _ns_to_t_units(tt, dt, fit_pre_ns)
    fit_post = _ns_to_t_units(tt, dt, fit_post_ns)
    fit_lo_t = float(tt[k_trigger]) - fit_pre
    fit_hi_t = float(tt[k_trigger]) + fit_post
    fit_lo = max(anchor, int(np.searchsorted(tt, fit_lo_t, side="left")))
    fit_hi = min(len(yy) - 1, int(np.searchsorted(tt, fit_hi_t, side="right")))
    if fit_hi <= fit_lo + 2:
        fit_lo = max(anchor, k_trigger - 8)
        fit_hi = min(len(yy) - 1, k_trigger + 8)

    if prefer_raw_crossing:
        raw_window = _ns_to_t_units(tt, dt, raw_window_ns)
        if direction == "rising":
            raw_lo = max(anchor, int(np.searchsorted(tt, float(tt[k_trigger]) - raw_window, side="left")))
            raw_hi = min(k_trigger, len(yy) - 2)
            if first_sustained_rise and not _use_legacy_loss_cursor_mode():
                raw_ix = _first_sustained_rise_crossing(
                    yy,
                    lvl,
                    raw_lo,
                    raw_hi,
                    k_trigger,
                    dt,
                    span,
                )
            else:
                raw_ix = None
                for kk in range(raw_lo, raw_hi + 1):
                    y0, y1 = float(yy[kk]), float(yy[kk + 1])
                    if y0 <= lvl < y1 and y1 > y0:
                        raw_ix = kk
            if raw_ix is not None:
                return int(raw_ix), _eoff_crossing_time_us(
                    tt, yy, int(raw_ix), lvl, direction
                )
            # Slow/low-current edges can place the real Base crossing outside
            # the narrow pre-trigger window.  Expand only the raw crossing
            # search, retaining the sustained-edge gate so platform noise
            # cannot win.  A fitted foot is not a valid oscilloscope cursor.
            full_hi = min(k_trigger, len(yy) - 2)
            if first_sustained_rise and not _use_legacy_loss_cursor_mode():
                raw_ix = _first_sustained_rise_crossing(
                    yy,
                    lvl,
                    anchor,
                    full_hi,
                    k_trigger,
                    dt,
                    span,
                )
            else:
                raw_ix = _crossing_pair_index(
                    yy, lvl, direction, anchor, full_hi
                )
            if raw_ix is not None:
                return int(raw_ix), _eoff_crossing_time_us(
                    tt, yy, int(raw_ix), lvl, direction
                )
        else:
            raw_lo = max(anchor, k_trigger)
            raw_hi = min(
                len(yy) - 2,
                int(np.searchsorted(tt, float(tt[k_trigger]) + raw_window, side="right")),
            )
            for kk in range(raw_lo, raw_hi + 1):
                y0, y1 = float(yy[kk]), float(yy[kk + 1])
                if y0 > lvl >= y1 and y0 > y1:
                    return int(kk), _eoff_crossing_time_us(
                        tt, yy, int(kk), lvl, direction
                    )
            raw_ix = _crossing_pair_index(
                yy, lvl, direction, max(anchor, k_trigger), len(yy) - 2
            )
            if raw_ix is not None:
                return int(raw_ix), _eoff_crossing_time_us(
                    tt, yy, int(raw_ix), lvl, direction
                )

    band = np.flatnonzero((yy[fit_lo : fit_hi + 1] >= low) & (yy[fit_lo : fit_hi + 1] <= high))
    if len(band) < 4:
        broad_low = lvl + 0.05 * span
        broad_high = lvl + 0.50 * span
        if broad_low > broad_high:
            broad_low, broad_high = broad_high, broad_low
        band = np.flatnonzero(
            (yy[fit_lo : fit_hi + 1] >= broad_low)
            & (yy[fit_lo : fit_hi + 1] <= broad_high)
        )

    if len(band) >= 4:
        abs_band = fit_lo + band
        gaps = np.flatnonzero(np.diff(abs_band) > 3)
        starts = np.concatenate(([0], gaps + 1))
        ends = np.concatenate((gaps + 1, [len(abs_band)]))
        runs = [abs_band[s:e] for s, e in zip(starts, ends) if e - s >= 4]
        if runs:
            if direction == "rising":
                before = [run for run in runs if int(run[-1]) <= k_trigger]
                idx = before[-1] if before else min(
                    runs, key=lambda run: abs(int(run[-1]) - k_trigger)
                )
            else:
                after = [run for run in runs if int(run[0]) >= k_trigger]
                idx = after[0] if after else min(
                    runs, key=lambda run: abs(int(run[0]) - k_trigger)
                )
        else:
            idx = abs_band
        slope, intercept = np.polyfit(tt[idx], yy[idx], 1)
        if (direction == "rising" and slope > 0.0) or (
            direction == "falling" and slope < 0.0
        ):
            t_fit = (lvl - float(intercept)) / float(slope)
            if direction == "rising":
                t_fit = max(float(tt[fit_lo]), min(float(t_fit), float(tt[k_trigger])))
            else:
                t_fit = max(float(tt[k_trigger]), min(float(t_fit), float(tt[fit_hi])))
            ix = int(np.searchsorted(tt, t_fit, side="right")) - 1
            ix = max(0, min(ix, len(tt) - 2))
            return ix, float(t_fit)

    if direction == "rising":
        search_lo, search_hi = fit_lo, min(k_trigger, len(yy) - 2)
    else:
        search_lo, search_hi = max(anchor, k_trigger), min(fit_hi, len(yy) - 2)
    ix = _crossing_pair_index(yy, lvl, direction, search_lo, search_hi)
    if ix is not None:
        return int(ix), _eoff_crossing_time_us(tt, yy, int(ix), lvl, direction)
    return k_trigger, float(tt[k_trigger])


def _eoff_vce_ha_crossing_at_main_rise(
    t_seg: np.ndarray,
    v_seg: np.ndarray,
    ha_v: float,
    dt: float,
    v_top: float,
    search_span_ns: float = 350.0,
    pre_rise_span_ns: float = 160.0,
) -> tuple[int, float]:
    """关断 A：Vce 主上升沿第一次穿 Ha 的时刻。"""
    _ = search_span_ns
    provisional_idx, provisional_t = _main_edge_level_crossing(
        t_seg,
        v_seg,
        ha_v,
        v_top,
        "rising",
        0,
        dt,
        fit_pre_ns=pre_rise_span_ns,
        min_trigger=30.0,
        raw_window_ns=pre_rise_span_ns,
        first_sustained_rise=True,
    )
    # The edge fit is only an anchor for rejecting pre-edge noise.  Published
    # A must still be a real interpolation of the raw Vce samples with Ha;
    # returning the fitted timestamp itself can visibly miss the waveform on
    # slow/noisy turn-off captures.
    radius = max(
        8,
        int(round(max(float(pre_rise_span_ns), 40.0) * 1e-9 / max(float(dt), 1e-15))),
    )
    lo = max(0, int(provisional_idx) - radius)
    hi = min(len(v_seg) - 1, int(provisional_idx) + radius)
    candidates = _crossing_pair_indices(
        v_seg,
        float(ha_v),
        lo,
        hi,
        direction="rising",
    )
    if candidates:
        raw = [
            (
                idx,
                _eoff_crossing_time_us(
                    t_seg,
                    v_seg,
                    idx,
                    float(ha_v),
                    "rising",
                ),
            )
            for idx in candidates
        ]
        return min(raw, key=lambda item: abs(float(item[1]) - float(provisional_t)))
    return int(provisional_idx), float(provisional_t)


def _eoff_vce_rise_start_index(
    v_seg: np.ndarray,
    ha_v: float,
    anchor: int,
    dt: float,
    v_top: float,
    t_seg: np.ndarray | None = None,
    pre_rise_span_ns: float = 160.0,
) -> int:
    """关断 A 样本索引（与 _eoff_vce_ha_crossing_at_main_rise 一致）。"""
    _ = anchor
    if t_seg is None or len(t_seg) != len(v_seg):
        t_seg = np.arange(len(v_seg), dtype=np.float64) * float(dt)
    ix, _ = _eoff_vce_ha_crossing_at_main_rise(
        t_seg,
        v_seg,
        ha_v,
        dt,
        v_top,
        pre_rise_span_ns=pre_rise_span_ns,
    )
    return int(ix)


def _eoff_crossing_time_us(
    t_seg: np.ndarray,
    y_seg: np.ndarray,
    ix: int,
    level: float,
    edge: str,
) -> float:
    """由样本索引得到与 level 的线性插值交点时刻（秒）。"""
    ix = max(0, min(int(ix), len(t_seg) - 2))
    y0, y1 = float(y_seg[ix]), float(y_seg[ix + 1])
    if edge == "rising" and y1 > y0:
        frac = float(np.clip((level - y0) / (y1 - y0), 0.0, 1.0))
    elif edge == "falling" and y0 > y1:
        frac = float(np.clip((level - y0) / (y1 - y0), 0.0, 1.0))
    else:
        return float(t_seg[ix])
    return float(t_seg[ix] + frac * (t_seg[ix + 1] - t_seg[ix]))


def _eon_ic_rise_crossing_at_main_rise(
    t_seg: np.ndarray,
    i_seg: np.ndarray,
    ha_ic: float,
    anchor: int,
    dt: float,
    i_top: float,
) -> tuple[int, float]:
    """开通 A：Ic 主上升沿第一次穿 Ha。"""
    return _main_edge_level_crossing(
        t_seg,
        i_seg,
        ha_ic,
        i_top,
        "rising",
        anchor,
        dt,
        min_trigger=15.0,
        raw_window_ns=200.0,
        first_sustained_rise=True,
    )


def _eoff_ic_fall_crossing_at_main_fall(
    t_seg: np.ndarray,
    i_seg: np.ndarray,
    hb: float,
    anchor: int,
    dt: float,
    i_top: float,
) -> tuple[int, float]:
    """关断 B：Ic 主振荡包络结束后，与 Hb 的第一个真实交点。"""
    first_ix, first_t = _main_edge_level_crossing(
        t_seg,
        i_seg,
        hb,
        i_top,
        "falling",
        anchor,
        dt,
        min_trigger=15.0,
        fit_post_ns=300.0,
        raw_window_ns=400.0,
    )
    return _settled_level_crossing_after_main_edge(
        t_seg,
        i_seg,
        hb,
        first_ix,
        first_t,
        dt,
        i_top,
        direction="falling",
        settle_profile="current_fall",
    )


def _eon_vce_hb_fall_crossing_at_main_fall(
    t_seg: np.ndarray,
    v_seg: np.ndarray,
    hb: float,
    anchor: int,
    dt: float,
    v_top: float,
) -> tuple[int, float]:
    """开通 B：Vce 主振荡包络结束后，与 Hb 的第一个真实交点。"""
    first_ix, first_t = _main_edge_level_crossing(
        t_seg,
        v_seg,
        hb,
        v_top,
        "falling",
        anchor,
        dt,
        min_trigger=5.0,
        fit_post_ns=300.0,
        raw_window_ns=400.0,
    )
    return _settled_level_crossing_after_main_edge(
        t_seg,
        v_seg,
        hb,
        first_ix,
        first_t,
        dt,
        v_top,
        direction="falling",
        settle_profile="voltage_fall",
    )


def _eoff_ic_fall_start_index(
    i_seg: np.ndarray,
    hb: float,
    anchor: int,
    dt: float,
    i_top: float,
) -> int:
    """关断 B 样本索引（与主下降沿首交点口径一致）。"""
    t_seg = np.arange(len(i_seg), dtype=np.float64) * float(dt)
    ix, _ = _eoff_ic_fall_crossing_at_main_fall(
        t_seg, i_seg, hb, anchor, dt, i_top
    )
    return int(ix)


def _eon_vce_hb_fall_start_index(
    v_seg: np.ndarray,
    hb: float,
    anchor: int,
    dt: float,
    v_top: float,
) -> int:
    """开通 B 样本索引（与主下降沿首交点口径一致）。"""
    t_seg = np.arange(len(v_seg), dtype=np.float64) * float(dt)
    ix, _ = _eon_vce_hb_fall_crossing_at_main_fall(
        t_seg, v_seg, hb, anchor, dt, v_top
    )
    return int(ix)


def _plateau_mean_ic_before_on(
    ic: np.ndarray, on_idx: int, w0: int, dt: float
) -> float:
    """开通：电流抬升前 Ic 低平台平稳均值（Eon Ha，带符号贴波形；下桥基线为负）。"""
    pre_end = max(w0 + 5, on_idx)
    pre = ic[w0:pre_end].astype(np.float64)
    if len(pre) < 8:
        return float(np.mean(pre)) if len(pre) else 0.0
    if not _use_legacy_loss_platform_mode():
        pre_margin = _samples_for_seconds(dt, 40e-9, minimum=1)
        pre_span = _samples_for_seconds(dt, 600e-9, minimum=16)
        local_hi = max(w0 + 1, int(on_idx) - pre_margin)
        local_lo = max(int(w0), local_hi - pre_span)
        local = ic[local_lo:local_hi].astype(np.float64)
        if len(local) >= 8:
            return _quiet_local_platform_level(local, dt)
    from dpt_extractor.metrics.plateau_level import turn_on_current_baseline_and_plateau

    hb, _ = turn_on_current_baseline_and_plateau(pre, dt)
    return float(hb)


def _plateau_mean_ic_after_on(
    ic: np.ndarray, on_idx: int, w1: int, dt: float
) -> float:
    """开通：电流抬升后导通段 |Ic| 平稳均值。"""
    post = np.abs(ic[on_idx : w1 + 1].astype(np.float64))
    if len(post) < 8:
        return float(np.mean(post)) if len(post) else 0.0
    i_top = float(np.percentile(post, 95))
    cond_thr = max(0.5 * i_top, 20.0)
    cond = post >= cond_thr
    if int(np.count_nonzero(cond)) >= 8:
        return float(np.mean(post[cond]))
    settle_len = max(12, int(80e-9 / dt))
    if len(post) > settle_len:
        return float(np.mean(post[-settle_len:]))
    return float(np.mean(post))


def eoff_energy_markers(
    t: np.ndarray,
    ic: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    off_idx: int,
    dt: float,
    pre_ns: float = 450.0,
    pulse1_on: int | None = None,
) -> EnergyLossMarkers:
    """
    关断损耗卡尺：Ha=Vce 抬升前平台均值；Hb=Ic 回落后平台均值；
    A=Vce 与 Ha 上升穿越；B=Ic 主振荡包络结束后与 Hb 的第一个真实交点。
    """
    _v_base, i_top, i_base, v_top, w0, w1 = scope_turn_off_bases(
        vce, ic, off_idx, i0, i1, dt, pre_ns, pulse1_on=pulse1_on
    )
    if w1 <= w0 + 10:
        return EnergyLossMarkers(
            float(_v_base),
            float(i_base),
            float(t[w0]),
            float(t[w1]),
            w0,
            w1,
        )

    ha_v = float(_v_base)
    hb_a = _plateau_mean_ic_after_off(ic, off_idx, w1, dt)

    low_current_eoff = float(i_top) < 180.0
    pre_rise_span_ns = 320.0 if low_current_eoff else 160.0
    sw0 = max(w0, i0)
    # A compact segment may begin one or a few samples after Vce has already
    # crossed its refined conducting-platform Ha.  In that specific case,
    # extend only the A-search source slightly to the left so the published
    # cursor can remain a real raw Vce/Ha interpolation.
    if sw0 > 0 and float(vce[sw0]) >= float(_v_base):
        left_limit = (
            max(0, int(pulse1_on))
            if pulse1_on is not None
            else 0
        )
        sw0 = max(
            left_limit,
            sw0
            - max(
                2,
                int(
                    round(
                        pre_rise_span_ns
                        * 1e-9
                        / max(float(dt), 1e-15)
                    )
                ),
            ),
        )
    v_seg = vce[sw0 : w1 + 1].astype(np.float64)
    # 带符号：下桥关断回落平台为负，B=Ic 回落与 Hb 交点须在真实波形上
    i_seg = ic[sw0 : w1 + 1].astype(np.float64)
    t_sw = t[sw0 : w1 + 1]
    local_off = off_idx - sw0

    i_start_local, t_start = _eoff_vce_ha_crossing_at_main_rise(
        t_sw,
        v_seg,
        ha_v,
        dt,
        float(v_top),
        pre_rise_span_ns=pre_rise_span_ns,
    )
    raw_ha_v = float(ha_v)
    raw_i_start_local = int(i_start_local)
    raw_t_start = float(t_start)
    if not _use_legacy_loss_platform_mode():
        refined_ha = _refine_eoff_vce_base_before_rise(
            vce,
            sw0 + i_start_local,
            sw0,
            dt,
            ha_v,
            abs(float(v_top) - float(ha_v)),
        )
        if abs(refined_ha - ha_v) > 1e-12:
            ha_v = refined_ha
            i_start_local, t_start = _eoff_vce_ha_crossing_at_main_rise(
                t_sw,
                v_seg,
                ha_v,
                dt,
                float(v_top),
                pre_rise_span_ns=pre_rise_span_ns,
            )

    fall_anchor = max(i_start_local + 1, int(np.searchsorted(t_sw, t_start, side="left")))
    i_end_local, t_end = _eoff_ic_fall_crossing_at_main_fall(
        t_sw, i_seg, hb_a, fall_anchor, dt, float(i_top)
    )
    if not _use_legacy_loss_platform_mode():
        refined_hb = _refine_eoff_ic_base_after_fall(
            ic,
            sw0 + i_end_local,
            w1,
            dt,
            hb_a,
            float(i_top),
        )
        if abs(refined_hb - hb_a) > 1e-12:
            hb_a = refined_hb
            i_end_local, t_end = _eoff_ic_fall_crossing_at_main_fall(
                t_sw, i_seg, hb_a, fall_anchor, dt, float(i_top)
            )

    if (
        float(i_top) >= 500.0
        and float(raw_ha_v) - float(ha_v) > 3.0
        and (
            float(raw_t_start) < float(t_start)
            or float(t_start)
            < float(raw_t_start) - max(8e-9, 8.0 * max(float(dt), 1e-15))
        )
    ):
        ha_v = float(raw_ha_v)
        i_start_local = int(raw_i_start_local)
        t_start = float(raw_t_start)

    i_start = int(np.searchsorted(t, t_start, side="left"))
    i_end = int(np.searchsorted(t, t_end, side="left"))
    i_start = max(sw0, min(i_start, len(t) - 2))
    i_end = max(i_start + 1, min(i_end, len(t) - 1))
    return EnergyLossMarkers(
        float(ha_v),
        float(hb_a),
        float(t_start),
        float(t_end),
        i_start,
        i_end,
    )


def eoff_window_scope_example(
    t: np.ndarray,
    ic: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    off_idx: int,
    dt: float,
    pre_ns: float = 450.0,
    pulse1_on: int | None = None,
) -> IntegrationWindow:
    """示波器 Eoff 积分窗口：与 Ha/Hb 卡尺交点一致。"""
    return eoff_energy_markers(
        t, ic, vce, i0, i1, off_idx, dt, pre_ns, pulse1_on=pulse1_on
    ).as_integration_window()


def eon_energy_markers(
    t: np.ndarray,
    ic: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    on_idx: int,
    dt: float,
    pulse1_off: int | None = None,
) -> EnergyLossMarkers:
    """
    开通损耗卡尺：Ha=Ic 抬升前低平台；Hb=Vce 回落后平稳均值；
    A=Ic 上升沿与 Ha 的交点；B=Vce 主振荡包络结束后与 Hb 的第一个真实交点。
    """
    on_ref = int(on_idx)
    if on_ref < int(i0) or on_ref > int(i1):
        on_ref = int(i0)
    i_base, v_top, i_top, v_base, w0, w1 = scope_turn_on_bases(
        vce, ic, on_ref, i0, i1, dt, pulse1_off=pulse1_off
    )
    if w1 <= w0 + 10:
        return EnergyLossMarkers(
            float(i_base), float(i_top), float(t[w0]), float(t[w1]), w0, w1
        )

    ha_ic = _plateau_mean_ic_before_on(ic, on_ref, w0, dt)
    base_win1 = min(
        int(w1),
        int(i1),
        on_ref + _samples_for_seconds(dt, 1200e-9, minimum=16),
    )
    hb_clip = _plateau_mean_vce_after_on(vce, ic, on_ref, base_win1, dt)
    post_tail_end = min(
        len(t) - 1,
        max(
            int(w1),
            int(i1),
            on_ref + _samples_for_seconds(dt, 1200e-9, minimum=16),
        ),
    )
    hb_v = float(hb_clip)
    win1 = base_win1
    if post_tail_end > base_win1 and not _use_legacy_loss_platform_mode():
        hb_tail = _plateau_mean_vce_after_on(vce, ic, on_ref, post_tail_end, dt)
        tail_gate = max(20.0, 0.04 * max(abs(float(v_top)), 1.0))
        if abs(float(hb_tail)) < abs(float(hb_clip)) - tail_gate:
            hb_v = float(hb_tail)
            win1 = post_tail_end

    # ``turn_on[0]`` can start a little after a slow/low-current Ic foot has
    # already crossed the signed Ha platform.  Cutting the search at i0 then
    # leaves no raw Ha intersection and the main-edge helper can only return a
    # fitted pseudo-foot.  Keep the event-local scope bound, but admit the
    # final 200 ns of the stable pre-on context so A can remain a real raw
    # waveform/platform crossing.  The sustained-edge gate below still rejects
    # earlier platform noise whenever a crossing exists on the main edge.
    sw0 = max(w0, on_ref - int(200e-9 / dt))
    if win1 <= sw0 + 2:
        win1 = min(len(t) - 1, max(i1, sw0 + int(350e-9 / dt)))
    # 带符号：下桥导通前基线为负，A=Ic 上升沿与 Ha 交点须在真实波形上
    i_seg = ic[sw0 : win1 + 1].astype(np.float64)
    v_seg = vce[sw0 : win1 + 1].astype(np.float64)
    t_sw = t[sw0 : win1 + 1]
    local_on = on_ref - sw0

    # The segment already starts no more than 200 ns before the detected
    # switching event.  Low-current/slow edges can cross the pre-on Ha platform
    # tens of nanoseconds before ``on_ref``; anchoring at on_ref-15 ns skips the
    # only real intersection and forces a fitted pseudo-foot.  Search the whole
    # bounded local segment and let the sustained-edge gate reject noise.
    anchor = 0
    i_start_local, t_start = _eon_ic_rise_crossing_at_main_rise(
        t_sw, i_seg, ha_ic, anchor, dt, float(i_top)
    )
    if i_start_local >= len(i_seg) - 2:
        i_start_local = max(0, min(len(i_seg) - 2, local_on))
        t_start = float(t_sw[i_start_local])

    if abs(float(i_top)) < 180.0 and not _use_legacy_loss_cursor_mode():
        main_edge_crossing = _low_current_main_foot_rising_crossing(
            t_sw,
            i_seg,
            ha_ic,
            float(i_top),
            float(t_start),
            dt,
            foot_frac=0.030,
            max_delay_ns=90.0,
        )
        if main_edge_crossing is not None:
            i_start_local, t_start = main_edge_crossing

    i_end_local, t_end = _eon_vce_hb_fall_crossing_at_main_fall(
        t_sw, v_seg, hb_v, i_start_local, dt, float(v_top)
    )

    i_start = int(np.searchsorted(t, float(t_start), side="left"))
    i_end = int(np.searchsorted(t, t_end, side="left"))
    i_start = max(sw0, min(i_start, len(t) - 2))
    i_end = max(i_start + 1, min(i_end, len(t) - 1))
    return EnergyLossMarkers(
        float(ha_ic),
        float(hb_v),
        float(t_start),
        float(t_end),
        i_start,
        i_end,
        v_b=float(hb_v),
    )


def eon_window_scope_example(
    t: np.ndarray,
    ic: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    on_idx: int,
    dt: float,
    pulse1_off: int | None = None,
) -> IntegrationWindow:
    """示波器 Eon 积分窗口：与 Ha/Hb 卡尺交点一致。"""
    return eon_energy_markers(
        t, ic, vce, i0, i1, on_idx, dt, pulse1_off=pulse1_off
    ).as_integration_window()


def _err_recovery_orientation(seg_i: np.ndarray) -> float:
    """恢复过冲方向：正向导通电流为负则取 +1，为正则取 -1。

    将电流定向到“恢复过冲为正”的统一坐标，使上/下桥（Irr=Ic−IL 为负）
    都能用同一套 UH 已调好的逻辑；避免按 |Irr| 处理时被恢复后的负向振铃
    误当作主峰。
    """
    seg = np.asarray(seg_i, dtype=np.float64)
    if len(seg) == 0:
        return 1.0
    head = seg[: max(8, len(seg) // 5)]
    base = float(np.median(head)) if len(head) else 0.0
    return -1.0 if base > 0 else 1.0


def err_recovery_peak_index(seg_i: np.ndarray, dt: float) -> int:
    """定向后恢复主峰(IRM)位置：恢复过冲为正，取 argmax，振铃不会误选。"""
    seg = np.asarray(seg_i, dtype=np.float64)
    if len(seg) < 3:
        return int(np.argmax(np.abs(seg))) if len(seg) else 0
    q = _err_recovery_orientation(seg) * seg
    return int(np.argmax(q))


@dataclass(frozen=True)
class _ErrRecoveryBase:
    level: float
    start_idx: int
    end_idx: int
    amp: float
    strict: bool = False


def _scope_top_in_time_window(
    t: np.ndarray,
    y: np.ndarray,
    t_lo_s: float,
    t_hi_s: float,
) -> float | None:
    """Top value using the same range-local algorithm as offset measurement."""
    top_base = _scope_top_base_in_time_window(t, y, t_lo_s, t_hi_s)
    if top_base is None:
        return None
    top, _base = top_base
    return float(top)


def _scope_top_base_in_time_window(
    t: np.ndarray,
    y: np.ndarray,
    t_lo_s: float,
    t_hi_s: float,
) -> tuple[float, float] | None:
    """Top/Base values using the same range-local algorithm as offset measurement."""
    if len(t) == 0 or len(y) == 0:
        return None
    lo = min(float(t_lo_s), float(t_hi_s))
    hi = max(float(t_lo_s), float(t_hi_s))
    i0 = int(np.searchsorted(t, lo, side="left"))
    i1 = int(np.searchsorted(t, hi, side="right"))
    i0 = max(0, min(i0, len(y) - 1))
    i1 = max(i0 + 1, min(i1, len(y)))
    block = np.asarray(y[i0:i1], dtype=np.float64)
    if len(block) < 8:
        return None
    top, _base = scope_top_base(block)
    if not np.isfinite(top) or not np.isfinite(_base):
        return None
    return float(top), float(_base)


def _parameter_focus_window_s(
    t: np.ndarray,
    anchor_us: float,
    *,
    left_divs: float = _PARAM_LOCAL_LEFT_DIVS,
) -> tuple[float, float] | None:
    """Screen time window used by parameter-local focus views."""
    if len(t) < 2 or not np.isfinite(anchor_us):
        return None
    span_us = _PARAM_LOCAL_US_PER_DIV * _PARAM_LOCAL_DIV_COUNT
    left_us = float(anchor_us) - float(left_divs) * _PARAM_LOCAL_US_PER_DIV
    right_us = left_us + span_us
    full_left_us = float(t[0]) * 1e6
    full_right_us = float(t[-1]) * 1e6
    if right_us - left_us <= 0.0 or full_right_us <= full_left_us:
        return None
    if left_us < full_left_us:
        right_us += full_left_us - left_us
        left_us = full_left_us
    if right_us > full_right_us:
        left_us -= right_us - full_right_us
        right_us = full_right_us
    left_us = max(full_left_us, left_us)
    right_us = min(full_right_us, right_us)
    if right_us <= left_us:
        return None
    return left_us * 1e-6, right_us * 1e-6


def _vge_turn_on_focus_edge_start_us(
    t: np.ndarray,
    vge: np.ndarray | None,
    pulse1_off: int | None,
    pulse2_on: int | None,
    pulse2_off: int | None,
    dt: float,
) -> float | None:
    """Vge rising-edge anchor used by the local Err/turn-on parameter view."""
    if vge is None or pulse2_on is None or pulse2_off is None:
        return None
    n = len(t)
    vge_arr = np.asarray(vge, dtype=np.float64)
    if n < 20 or len(vge_arr) != n:
        return None
    on_idx = max(0, min(int(pulse2_on), n - 1))
    p2_off = max(on_idx + 1, min(int(pulse2_off), n - 1))
    p1_off = int(pulse1_off) if pulse1_off is not None else 0
    same_pulse = on_idx <= p1_off
    gap12 = max(10, on_idx - p1_off) if not same_pulse else max(10, on_idx)
    p2w = max(10, p2_off - on_idx)
    pre_lo = max(int(50e-9 / max(dt, 1e-15)), int(0.05 * gap12))
    post_hi = max(int(80e-9 / max(dt, 1e-15)), int(0.06 * p2w))

    if same_pulse:
        lo0 = max(0, on_idx - int(500e-9 / max(dt, 1e-15)))
        lo1 = max(lo0 + 20, min(on_idx - pre_lo, n - 1))
    else:
        lo0 = min(n - 1, max(p1_off + int(150e-9 / max(dt, 1e-15)), 0))
        lo1 = max(lo0 + 20, min(on_idx - pre_lo, n - 1))
    if lo1 <= lo0 + 5:
        lo1 = max(lo0 + 20, min(on_idx - int(15e-9 / max(dt, 1e-15)), n - 1))
    hi0 = min(n - 1, max(on_idx + int(150e-9 / max(dt, 1e-15)), lo1 + 10))
    hi1 = max(hi0 + 20, min(p2_off - post_hi, n - 1))
    if lo1 <= lo0 + 5 or hi1 <= hi0 + 5:
        return None

    rise_span = max(
        int(1.2e-6 / max(dt, 1e-15)),
        int(0.25 * gap12),
        int(0.5 * p2w),
    )
    if same_pulse:
        w0 = max(0, on_idx - rise_span)
    else:
        w0 = max(0, p1_off, on_idx - rise_span)
    w1 = min(n - 1, on_idx)
    if w1 <= w0 + 10:
        return None
    v_lo = float(np.percentile(vge_arr[lo0:lo1], 5))
    v_hi = float(np.percentile(vge_arr[hi0:hi1], 95))
    if abs(v_hi - v_lo) < 1.0:
        return None
    ts = t[w0 : w1 + 1]
    vge_s = smooth(vge_arr[w0 : w1 + 1], dt, _PARAM_LOCAL_VGE_SMOOTH_NS)
    starts: list[float] = []
    for pct in (0.02, 0.05, 0.10):
        tv = crossing_time(
            ts,
            vge_s,
            threshold_value(v_lo, v_hi, pct),
            "rising",
            start=0,
        )
        if tv is not None and np.isfinite(tv):
            starts.append(float(tv))
    if not starts:
        return None
    return min(starts) * 1e6


def _err_ha_top_from_offset_window(
    t: np.ndarray,
    irr: np.ndarray,
    t_b_v: float,
    err_base: _ErrRecoveryBase,
    dt: float,
    *,
    vge: np.ndarray | None = None,
    pulse1_off: int | None = None,
    pulse2_on: int | None = None,
    pulse2_off: int | None = None,
) -> float | None:
    """Err Ha uses the same Top definition as offset measurement.

    The default GUI loads a parameter-local Err view at roughly 200 ns/div.
    Recreate that deterministic 2 us screen-like window around the Err cursors
    so automatic extraction, cursor display, and offset-measurement Top agree.
    """
    if len(t) == 0 or len(irr) == 0:
        return None
    anchor_us = _vge_turn_on_focus_edge_start_us(
        t, vge, pulse1_off, pulse2_on, pulse2_off, dt
    )
    if pulse2_on is not None:
        p2_idx = max(0, min(int(pulse2_on), len(t) - 1))
        p2_anchor_us = float(t[p2_idx]) * 1e6
        # Multi-pulse sessions can contain a noisy post-pulse transition before
        # the selected turn-on edge. If the Vge-derived anchor falls on that
        # previous platform, the 200 ns/div local Top window reads the wrong
        # high-current plateau. In that case anchor the local view to the
        # selected pulse2_on edge instead.
        if (
            anchor_us is None
            or anchor_us < p2_anchor_us - 0.25
            or anchor_us > p2_anchor_us + 0.10
        ):
            anchor_us = p2_anchor_us
    if anchor_us is not None:
        local_window = _parameter_focus_window_s(t, anchor_us)
        if local_window is not None:
            top = _scope_top_in_time_window(t, irr, local_window[0], local_window[1])
            if top is not None:
                return top

    i_a_hint = max(0, min(int(err_base.start_idx), len(t) - 1))
    t_a_hint = float(t[i_a_hint])
    raw_lo = min(float(t_b_v), t_a_hint) - 150e-9
    raw_hi = max(float(t_b_v), t_a_hint) + 150e-9
    center = 0.5 * (raw_lo + raw_hi)
    half_width = max(1.0e-6, 0.5 * (raw_hi - raw_lo))
    full_lo = float(t[0])
    full_hi = float(t[-1])
    if center - half_width < full_lo:
        center = full_lo + half_width
    if center + half_width > full_hi:
        center = full_hi - half_width
    top = _scope_top_in_time_window(t, irr, center - half_width, center + half_width)
    if top is not None:
        return top

    # Fallback to the settled window only when the deterministic local view
    # cannot provide enough samples.
    lo = max(0, min(int(err_base.start_idx), len(t) - 1))
    hi = max(lo + 1, min(int(err_base.end_idx) + 1, len(t)))
    min_len = _samples_for_seconds(dt, 40e-9, minimum=8)
    if hi - lo < min_len:
        return None
    return _scope_top_in_time_window(t, irr, float(t[lo]), float(t[hi - 1]))


def _err_low_current_stable_top_from_offset_window(
    t: np.ndarray,
    irr: np.ndarray,
    err_base: _ErrRecoveryBase,
    dt: float,
    *,
    vge: np.ndarray | None = None,
    pulse1_off: int | None = None,
    pulse2_on: int | None = None,
    pulse2_off: int | None = None,
) -> float | None:
    """Low-current Err Ha fallback: Top from the right-side stable local view."""
    anchor_us = _vge_turn_on_focus_edge_start_us(
        t, vge, pulse1_off, pulse2_on, pulse2_off, dt
    )
    if anchor_us is None:
        return None
    local_window = _parameter_focus_window_s(t, anchor_us)
    if local_window is None:
        return None
    lo_idx = max(0, min(int(err_base.end_idx), len(t) - 1))
    top_base = _scope_top_base_in_time_window(
        t,
        irr,
        float(t[lo_idx]),
        local_window[1],
    )
    if top_base is None:
        return None
    top, _base = top_base
    return float(top)


def _err_vd_base_from_offset_window(
    t: np.ndarray,
    vd: np.ndarray,
    t_b_v: float,
    err_base: _ErrRecoveryBase,
) -> float | None:
    """Err Hb(Vd) Base using the same local screen range as offset measurement."""
    if len(t) == 0 or len(vd) == 0:
        return None
    i_a_hint = max(0, min(int(err_base.start_idx), len(t) - 1))
    t_a_hint = float(t[i_a_hint])
    raw_lo = min(float(t_b_v), t_a_hint) - 150e-9
    raw_hi = max(float(t_b_v), t_a_hint) + 150e-9
    center = 0.5 * (raw_lo + raw_hi)
    half_width = max(1.0e-6, 0.5 * (raw_hi - raw_lo))
    full_lo = float(t[0])
    full_hi = float(t[-1])
    if center - half_width < full_lo:
        center = full_lo + half_width
    if center + half_width > full_hi:
        center = full_hi - half_width
    top_base = _scope_top_base_in_time_window(
        t, vd, center - half_width, center + half_width
    )
    if top_base is None:
        return None
    _top, base = top_base
    return float(base)


def _legacy_err_recovery_settled_base(
    irr: np.ndarray,
    ipk_global: int,
    dt: float,
    search_end: int,
) -> _ErrRecoveryBase:
    """Err Ha：主大振荡结束后，本次恢复过程内的 Irr base 有效值。

    仅用于反向恢复电流 Irr：从 IRM 尖峰后向右扫描滚动局部极差；第一个达到
    低幅稳定标准的位置就是 A/Ha 的结束评估区，后面的长尾噪声、LC 振铃和
    平台抖动不再参与。Eoff/Eon 不得引用这个尖峰规则，它们分别按 Ic/Vce
    主下降沿与各自 Hb 横线判定。这个 helper 取代旧的峰后固定 400~800ns 尾窗。
    """
    y = np.asarray(irr, dtype=np.float64)
    n = len(y)
    if n == 0:
        return _ErrRecoveryBase(0.0, 0, 0, 0.0)
    k0 = max(0, min(int(ipk_global), n - 1))
    k_end = max(k0 + 1, min(int(search_end), n - 1))
    available = k_end - k0
    if available < 12:
        level = float(y[k0])
        return _ErrRecoveryBase(level, k0, k_end, 0.0)

    base_len = max(16, int(60e-9 / max(dt, 1e-15)))
    if available <= base_len + 4:
        base_len = max(8, available - 2)
    step = max(1, int(5e-9 / max(dt, 1e-15)))
    scan_lo = k0 + max(4, int(80e-9 / max(dt, 1e-15)))
    scan_hi = k_end - base_len
    if scan_hi < scan_lo:
        scan_lo = max(k0 + 1, k_end - base_len)
        scan_hi = scan_lo

    def _stats(start: int) -> tuple[float, float]:
        block = y[start : start + base_len]
        if len(block) < 3:
            return 0.0, float(block[0]) if len(block) else float(y[k0])
        mn = float(np.min(block))
        mx = float(np.max(block))
        return 0.5 * (mx - mn), 0.5 * (mx + mn)

    peak_abs = max(abs(float(y[k0])), 1.0)
    cycle_region = _three_full_cycle_settle_region(
        np.arange(n, dtype=np.float64) * float(dt),
        y,
        level_hint=None,
        start_idx=k0,
        end_idx=k_end,
        dt=dt,
        span=peak_abs,
        settle_profile="err_current",
        seed_start_extremum=True,
    )
    if cycle_region is not None:
        return _ErrRecoveryBase(
            float(cycle_region.level),
            int(cycle_region.start_idx),
            int(cycle_region.end_idx),
            0.5 * float(cycle_region.pp_amp),
            strict=cycle_region.strict,
        )

    lookahead = max(6, int(120e-9 / max(step * dt, 1e-15)))
    best: tuple[int, float, float] | None = None

    def _scan_with_ceiling(ceiling: float, *, strict: bool) -> _ErrRecoveryBase | None:
        nonlocal best
        cur = scan_lo
        while cur <= scan_hi:
            amp, mid = _stats(cur)
            if best is None or amp < best[1]:
                best = (cur, amp, mid)
            if amp <= ceiling:
                future_amps = [amp]
                fut = cur + step
                for _ in range(lookahead - 1):
                    if fut > scan_hi:
                        break
                    fut_amp, _fut_mid = _stats(fut)
                    future_amps.append(fut_amp)
                    fut += step
                future_max = max(future_amps)
                no_main_rebound = future_max <= max(1.45 * amp, amp + 12.0)
                if no_main_rebound:
                    end_idx = min(n - 1, cur + base_len - 1)
                    return _ErrRecoveryBase(
                        float(mid), int(cur), end_idx, float(amp), strict=strict
                    )
            cur += step
        return None

    # 第一口径只吃主恢复大振荡已明显收敛的位置；找不到时再放宽一次，
    # 但仍拒绝还在肉眼可见大幅衰减的尾段。
    if peak_abs < 120.0:
        strict_ceiling = max(16.0, 0.149 * peak_abs)
        loose_ceiling = max(18.0, 0.220 * peak_abs)
    else:
        strict_ceiling = max(14.0, 0.120 * peak_abs)
        loose_ceiling = max(16.0, 0.180 * peak_abs)
    strict = _scan_with_ceiling(strict_ceiling, strict=True)
    if strict is not None:
        return strict
    loose = _scan_with_ceiling(loose_ceiling, strict=False)
    if loose is not None:
        return loose

    if best is None:
        block = y[k0 : k_end + 1]
        mn = float(np.min(block))
        mx = float(np.max(block))
        return _ErrRecoveryBase(0.5 * (mx + mn), k0, k_end, 0.5 * (mx - mn))
    start_idx = int(best[0])
    end_idx = min(n - 1, start_idx + base_len - 1)
    return _ErrRecoveryBase(float(best[2]), start_idx, end_idx, float(best[1]))


def _err_envelope_gate_after_peak(
    irr: np.ndarray,
    level_hint: float,
    ipk_global: int,
    search_end: int,
    dt: float,
    peak_abs: float,
) -> _EnvelopeGate | None:
    y = np.asarray(irr, dtype=np.float64)
    n = len(y)
    if n < 12:
        return None
    k0 = max(0, min(int(ipk_global), n - 2))
    k_end = max(k0 + 2, min(int(search_end), n - 1))
    if k_end <= k0 + _samples_for_seconds(dt, 80e-9, minimum=12):
        return None

    smooth_n = _samples_for_seconds(dt, 4e-9, minimum=3)
    smooth_y = _edge_smoothed(y, smooth_n)
    extrema_lo = min(k_end - 1, k0 + _samples_for_seconds(dt, 5e-9, minimum=1))
    extrema = _local_extrema_indices(
        smooth_y, extrema_lo, k_end, dt, min_gap_ns=5.0
    )
    if not extrema:
        return None

    p = max(float(peak_abs), 1.0)
    if p < 80.0:
        return None
    threshold = (
        max(16.0, min(28.0, 0.10 * p))
        if p >= 120.0
        else max(7.0, min(12.0, 0.065 * p))
    )
    significant = [
        int(idx)
        for idx in extrema
        if abs(float(smooth_y[int(idx)]) - float(level_hint)) >= threshold
    ]
    if len(significant) < 4:
        return None

    first_sig = significant[0]
    last_sig = significant[-1]
    if (last_sig - first_sig) * max(float(dt), 1e-15) < 60e-9:
        return None
    if (last_sig - k0) * max(float(dt), 1e-15) > 850e-9:
        return None

    gate_idx = min(
        k_end - 1,
        last_sig + _samples_for_seconds(dt, 10e-9, minimum=1),
    )
    if gate_idx <= k0:
        return None
    return _EnvelopeGate(
        int(gate_idx),
        float(threshold),
        int(last_sig),
        int(len(significant)),
    )


def _err_base_after_envelope_gate(
    irr: np.ndarray,
    gate_idx: int,
    ipk_global: int,
    dt: float,
    search_end: int,
    peak_abs: float,
) -> _ErrRecoveryBase | None:
    y = np.asarray(irr, dtype=np.float64)
    n = len(y)
    if n < 12:
        return None
    k0 = max(0, min(int(ipk_global), n - 1))
    k_end = max(k0 + 1, min(int(search_end), n - 1))
    base_len = max(16, _samples_for_seconds(dt, 60e-9, minimum=16))
    if k_end - k0 <= base_len + 4:
        return None
    step = max(1, _samples_for_seconds(dt, 5e-9, minimum=1))
    scan_lo = max(
        int(gate_idx),
        k0 + _samples_for_seconds(dt, 80e-9, minimum=4),
    )
    scan_hi = k_end - base_len
    if scan_hi < scan_lo:
        return None

    def _stats(start: int) -> tuple[float, float]:
        block = y[start : start + base_len]
        if len(block) < 3:
            return 0.0, float(block[0]) if len(block) else float(y[k0])
        mn = float(np.min(block))
        mx = float(np.max(block))
        return 0.5 * (mx - mn), 0.5 * (mx + mn)

    p = max(float(peak_abs), 1.0)
    if p < 120.0:
        strict_ceiling = max(12.0, min(18.0, 0.120 * p))
        loose_ceiling = max(16.0, min(24.0, 0.160 * p))
    else:
        strict_ceiling = max(9.0, min(20.0, 0.080 * p))
        loose_ceiling = max(strict_ceiling + 4.0, min(28.0, 0.125 * p))
    lookahead = max(4, int(round(120e-9 / max(step * float(dt), 1e-15))))

    best: tuple[int, float, float] | None = None

    def _scan(ceiling: float, *, strict: bool) -> _ErrRecoveryBase | None:
        nonlocal best
        cur = scan_lo
        while cur <= scan_hi:
            amp, mid = _stats(cur)
            if best is None or amp < best[1]:
                best = (cur, amp, mid)
            if amp <= ceiling:
                future_amps = [amp]
                fut = cur + step
                for _ in range(lookahead - 1):
                    if fut > scan_hi:
                        break
                    fut_amp, _fut_mid = _stats(fut)
                    future_amps.append(fut_amp)
                    fut += step
                future_max = max(future_amps)
                no_rebound = future_max <= max(
                    1.50 * amp,
                    amp + max(8.0, 0.045 * p),
                )
                if no_rebound:
                    return _ErrRecoveryBase(
                        float(mid),
                        int(cur),
                        min(n - 1, int(cur) + base_len - 1),
                        float(amp),
                        strict=strict,
                    )
            cur += step
        return None

    found = _scan(strict_ceiling, strict=True)
    if found is not None:
        return found
    found = _scan(loose_ceiling, strict=False)
    if found is not None:
        return found
    return None


def _err_first_stable_entry_after_main_recovery(
    irr: np.ndarray,
    ipk_global: int,
    dt: float,
    search_end: int,
    rebound_check_end: int,
    peak_abs: float,
) -> _ErrRecoveryBase | None:
    """First low-amplitude entry after the main reverse-recovery ringing packet.

    This is intentionally different from "the quietest/latest tail": it waits
    until the main visible ringing extrema have passed, then scans left-to-right
    for the first local window with low peak-to-peak, center near the local
    platform, and no obvious rebound shortly after it.
    """
    y = np.asarray(irr, dtype=np.float64)
    n = len(y)
    if n < 24:
        return None
    k0 = max(0, min(int(ipk_global), n - 2))
    k_end = max(k0 + 2, min(int(search_end), n - 1))
    rebound_end = max(k_end, min(int(rebound_check_end), n - 1))
    base_len = _samples_for_seconds(dt, 60e-9, minimum=16)
    if k_end <= k0 + base_len + 4:
        return None

    p = max(float(peak_abs), 1.0)
    if p < 80.0:
        return None

    platform_block = y[k0 : k_end + 1]
    if len(platform_block) < base_len:
        return None
    platform = _quiet_local_platform_level(platform_block, dt, min_ns=200.0)

    smooth_n = _samples_for_seconds(dt, 4e-9, minimum=3)
    smooth_y = _edge_smoothed(y, smooth_n)
    extrema_lo = min(k_end - 1, k0 + _samples_for_seconds(dt, 5e-9, minimum=1))
    extrema = _local_extrema_indices(
        smooth_y, extrema_lo, k_end, dt, min_gap_ns=5.0
    )
    if not extrema:
        return None

    if p < 120.0:
        major_threshold = max(16.0, min(24.0, 0.170 * p))
        pp_limit = max(16.0, min(28.0, 0.190 * p))
        min_sig_count = 4
    else:
        major_threshold = max(18.0, min(42.0, 0.170 * p))
        pp_limit = max(28.0, min(64.0, 0.380 * p))
        min_sig_count = 5

    significant = [
        int(idx)
        for idx in extrema
        if abs(float(smooth_y[int(idx)]) - float(platform)) >= major_threshold
    ]
    if len(significant) < min_sig_count:
        return None
    first_sig = significant[0]
    last_sig = significant[-1]
    if (last_sig - first_sig) * max(float(dt), 1e-15) < 60e-9:
        return None

    step = _samples_for_seconds(dt, 5e-9, minimum=1)
    scan_lo = max(
        last_sig + _samples_for_seconds(dt, 8e-9, minimum=1),
        k0 + _samples_for_seconds(dt, 80e-9, minimum=4),
    )
    scan_hi = k_end - base_len
    if scan_hi < scan_lo:
        return None

    center_limit = max(8.0, min(30.0, 0.100 * p), 0.65 * pp_limit)
    lookahead = max(4, int(round(160e-9 / max(step * float(dt), 1e-15))))

    def _stats(start: int) -> tuple[float, float, float]:
        block = y[start : start + base_len]
        if len(block) < 3:
            v = float(block[0]) if len(block) else float(y[k0])
            return 0.0, v, v
        mn = float(np.min(block))
        mx = float(np.max(block))
        return mx - mn, 0.5 * (mx + mn), float(np.median(block))

    cur = scan_lo
    while cur <= scan_hi:
        pp, mid, med = _stats(cur)
        center_dev = abs(float(mid) - float(platform))
        median_dev = abs(float(med) - float(platform))
        if (
            pp <= pp_limit
            and center_dev <= center_limit
            and median_dev <= 1.25 * center_limit
        ):
            future_pp = [pp]
            future_dev = [center_dev]
            fut = cur + step
            for _ in range(lookahead - 1):
                if fut > min(rebound_end - base_len, scan_hi + lookahead * step):
                    break
                fpp, fmid, _fmed = _stats(fut)
                future_pp.append(fpp)
                future_dev.append(abs(float(fmid) - float(platform)))
                fut += step
            max_future_pp = max(future_pp)
            max_future_dev = max(future_dev)
            no_rebound = (
                max_future_pp
                <= max(1.55 * pp, pp + max(8.0, 0.055 * p), 1.20 * pp_limit)
                and max_future_dev
                <= max(
                    major_threshold,
                    center_dev + max(8.0, 0.060 * p),
                    1.15 * center_limit,
                )
            )
            if no_rebound:
                strict = pp <= 0.85 * pp_limit and center_dev <= 0.70 * center_limit
                return _ErrRecoveryBase(
                    float(mid),
                    int(cur),
                    min(n - 1, int(cur) + base_len - 1),
                    0.5 * float(pp),
                    strict=bool(strict),
                )
        cur += step
    return None


def _prefer_first_err_stable_entry(
    first_stable: _ErrRecoveryBase | None,
    current: _ErrRecoveryBase,
    legacy: _ErrRecoveryBase,
    dt: float,
) -> _ErrRecoveryBase:
    if first_stable is None:
        return current
    margin = _samples_for_seconds(dt, 18e-9, minimum=1)
    if int(first_stable.start_idx) < int(current.start_idx) - margin:
        if bool(first_stable.strict) or float(first_stable.amp) <= max(
            1.20 * float(current.amp),
            float(current.amp) + 8.0,
        ):
            return first_stable
    legacy_shift = _samples_for_seconds(dt, 25e-9, minimum=1)
    if (
        int(current.start_idx) <= int(legacy.start_idx) + margin
        and int(first_stable.start_idx) > int(legacy.start_idx) + legacy_shift
        and float(first_stable.amp) <= 1.10 * max(float(legacy.amp), 1e-9)
    ):
        return first_stable
    return current


def _err_positive_soft_recovery_early_cross_t(
    t: np.ndarray,
    irr: np.ndarray,
    ha: float,
    ipk_global: int,
    i_end: int,
    dt: float,
) -> float | None:
    """Moderate positive soft-recovery Err A: avoid waiting for the quiet tail."""
    if len(t) < 2 or len(irr) != len(t):
        return None
    k0 = max(0, min(int(ipk_global), len(irr) - 2))
    peak = float(irr[k0])
    peak_abs = abs(peak)
    if peak <= 0.0 or ha <= 0.0 or peak_abs < 120.0:
        return None
    k_end = max(k0 + 2, min(int(i_end), len(irr) - 1))
    if k_end <= k0 + _samples_for_seconds(dt, 220e-9, minimum=8):
        return None

    smooth_n = _samples_for_seconds(dt, 4e-9, minimum=3)
    smooth_y = _edge_smoothed(np.asarray(irr, dtype=np.float64), smooth_n)
    extrema = _local_extrema_indices(
        smooth_y,
        k0 + _samples_for_seconds(dt, 140e-9, minimum=1),
        k_end,
        dt,
        min_gap_ns=5.0,
    )
    if not extrema:
        return None

    min_start = k0 + _samples_for_seconds(dt, 180e-9, minimum=1)
    low_rebound_limit = max(18.0, min(34.0, 0.18 * peak_abs))
    seed_idx: int | None = None
    for idx in extrema:
        idx = int(idx)
        if idx < min_start:
            continue
        if float(smooth_y[idx]) > 0.0 and abs(float(smooth_y[idx])) <= low_rebound_limit:
            seed_idx = idx
            break
    if seed_idx is None:
        return None

    return _first_level_cross_after_time(
        t,
        np.asarray(irr, dtype=np.float64),
        float(ha),
        float(t[seed_idx]) + 14e-9,
        dt,
        window_ns=120.0,
    )


def _err_positive_soft_recovery_ha_signal_floor(
    peak: float,
) -> float:
    """Minimum resolvable Ha before the positive soft-recovery shortcut is safe.

    A near-zero local Top can be smaller than the ringing/noise band. In that
    case every zero crossing looks like a valid Irr/Ha intersection and the
    shortcut can cut the main recovery packet hundreds of nanoseconds early.
    Keep the accepted soft-recovery class, but require Ha to reach one percent
    of the recovery peak first. Across the original songzhenxi corpus the bad
    near-zero case is 0.0134%, while every verified early-entry case is at least
    2.51%, so this guard does not reclassify the accepted waveform family.
    """
    return 0.01 * abs(float(peak))


def _err_recovery_settled_base(
    irr: np.ndarray,
    ipk_global: int,
    dt: float,
    search_end: int,
) -> _ErrRecoveryBase:
    """Err Ha base: optionally wait for the main recovery ringing envelope tail."""
    legacy = _legacy_err_recovery_settled_base(irr, ipk_global, dt, search_end)
    if _use_legacy_loss_cursor_mode():
        return legacy

    y = np.asarray(irr, dtype=np.float64)
    if len(y) < 12:
        return legacy
    k0 = max(0, min(int(ipk_global), len(y) - 1))
    peak_abs = max(abs(float(y[k0])), 1.0)
    if peak_abs < 80.0:
        return legacy
    envelope_search_end = min(
        len(y) - 1,
        int(search_end) + _samples_for_seconds(dt, 180e-9, minimum=1),
    )
    first_stable = _err_first_stable_entry_after_main_recovery(
        y,
        k0,
        dt,
        int(envelope_search_end),
        envelope_search_end,
        peak_abs,
    )
    gate = _err_envelope_gate_after_peak(
        y,
        float(legacy.level),
        k0,
        envelope_search_end,
        dt,
        peak_abs,
    )
    if gate is None:
        return _prefer_first_err_stable_entry(first_stable, legacy, legacy, dt)

    min_shift = _samples_for_seconds(
        dt,
        20e-9 if peak_abs >= 120.0 else 30e-9,
        minimum=1,
    )
    if abs(int(gate.start_idx) - int(legacy.start_idx)) <= min_shift:
        return _prefer_first_err_stable_entry(first_stable, legacy, legacy, dt)
    max_shift_ns = 320e-9 if peak_abs < 120.0 else 230e-9
    max_shift = _samples_for_seconds(dt, max_shift_ns, minimum=1)
    if gate.start_idx > int(legacy.start_idx) + max_shift:
        return _prefer_first_err_stable_entry(first_stable, legacy, legacy, dt)

    candidate = _err_base_after_envelope_gate(
        y,
        gate.start_idx,
        k0,
        dt,
        envelope_search_end,
        peak_abs,
    )
    if candidate is None:
        return _prefer_first_err_stable_entry(first_stable, legacy, legacy, dt)
    legacy_amp = max(float(legacy.amp), 1e-9)
    candidate_amp = float(candidate.amp)
    if peak_abs < 120.0 and candidate_amp > 1.10 * legacy_amp:
        return _prefer_first_err_stable_entry(first_stable, legacy, legacy, dt)
    if (
        candidate.start_idx
        < int(legacy.start_idx) - _samples_for_seconds(dt, 80e-9, minimum=1)
        and candidate_amp <= max(0.14 * peak_abs, legacy_amp + 14.0)
    ):
        return _prefer_first_err_stable_entry(first_stable, candidate, legacy, dt)
    if peak_abs >= 120.0 and candidate_amp > 0.85 * legacy_amp:
        return _prefer_first_err_stable_entry(first_stable, legacy, legacy, dt)
    if peak_abs >= 120.0 and candidate_amp > 0.80 * legacy_amp:
        max_shift_ns = 170e-9
    max_shift = _samples_for_seconds(dt, max_shift_ns, minimum=1)
    if candidate.start_idx <= int(legacy.start_idx) + min_shift:
        return _prefer_first_err_stable_entry(first_stable, legacy, legacy, dt)
    if candidate.start_idx > int(legacy.start_idx) + max_shift:
        return _prefer_first_err_stable_entry(first_stable, legacy, legacy, dt)
    return _prefer_first_err_stable_entry(first_stable, candidate, legacy, dt)


def _err_hb_v_before_rise(
    seg_v: np.ndarray, seg_abs: np.ndarray, ipk: int, dt: float
) -> float:
    """电压主抬升前 Vd 平稳基线（Hb）。"""
    wlen = max(5, int(30e-9 / max(dt, 1e-15)))
    lo = max(0, ipk - int(150e-9 / max(dt, 1e-15)))
    hi = max(lo + wlen, ipk - int(5e-9 / max(dt, 1e-15)))
    v_hi = max(
        40.0,
        0.2
        * float(
            np.max(
                seg_v[
                    ipk : min(len(seg_v), ipk + int(40e-9 / max(dt, 1e-15)) + 1)
                ]
            )
        ),
    )
    best_std = float("inf")
    hb = float(np.median(seg_v[lo:hi])) if hi > lo else float(seg_v[lo])
    for w0 in range(lo, hi - wlen + 1):
        sub = seg_v[w0 : w0 + wlen]
        if float(np.max(sub)) > v_hi:
            continue
        st = float(np.std(sub))
        if st < best_std:
            best_std = st
            hb = float(np.median(sub))
    return hb


def _err_interp_cross_time(
    t_seg: np.ndarray, y_seg: np.ndarray, k: int, level: float
) -> float:
    y0, y1 = float(y_seg[k]), float(y_seg[k + 1])
    t0, t1 = float(t_seg[k]), float(t_seg[k + 1])
    if abs(y1 - y0) < 1e-30:
        return t0
    frac = float(np.clip((level - y0) / (y1 - y0), 0.0, 1.0))
    return t0 + frac * (t1 - t0)


def _err_negative_ringing_tail_cross_t(
    t: np.ndarray,
    irr: np.ndarray,
    ha: float,
    ipk_global: int,
    i_end: int,
    dt: float,
) -> float | None:
    """WH 类负向强振荡 Err A：等主包络收敛后再取 Ha 真实交点。"""
    y = np.asarray(irr, dtype=np.float64)
    if len(y) < 12 or len(t) != len(y):
        return None
    k0 = max(0, min(int(ipk_global), len(y) - 2))
    peak = float(y[k0])
    peak_abs = abs(peak)
    if peak >= 0.0 or peak_abs < 120.0:
        return None
    k_end = max(k0 + 2, min(int(i_end), len(y) - 1))
    legacy = _legacy_err_recovery_settled_base(y, k0, dt, k_end)
    search_end = min(
        len(y) - 1,
        k_end + _samples_for_seconds(dt, 500e-9, minimum=1),
    )
    smooth_n = _samples_for_seconds(dt, 4e-9, minimum=3)
    smooth_y = _edge_smoothed(y, smooth_n)
    extrema = _local_extrema_indices(
        smooth_y,
        k0,
        search_end,
        dt,
        min_gap_ns=5.0,
    )
    if not extrema:
        return None
    threshold = max(8.0, 0.08 * peak_abs)
    significant = [
        int(idx)
        for idx in extrema
        if abs(float(smooth_y[int(idx)]) - float(legacy.level)) >= threshold
    ]
    if len(significant) < 4:
        return None
    gate_t = float(t[significant[-1]]) + 10e-9
    start = int(np.searchsorted(t, gate_t, side="left"))
    stop = min(len(y) - 2, start + _samples_for_seconds(dt, 160e-9, minimum=2))
    lvl = float(ha)
    for k in range(max(k0, start), stop + 1):
        y0, y1 = float(y[k]), float(y[k + 1])
        if min(y0, y1) <= lvl <= max(y0, y1) and abs(y1 - y0) > 1e-30:
            return float(_err_interp_cross_time(t, y, k, lvl))
    return None


def _first_level_cross_after_time(
    t: np.ndarray,
    y: np.ndarray,
    level: float,
    t_after: float,
    dt: float,
    *,
    window_ns: float = 420.0,
) -> float | None:
    """First raw crossing of level after a time guard."""
    if len(t) < 2 or len(y) != len(t):
        return None
    start = int(np.searchsorted(t, float(t_after), side="left"))
    stop = min(
        len(t) - 2,
        start + _samples_for_seconds(dt, window_ns * 1e-9, minimum=2),
    )
    lvl = float(level)
    for k in range(max(0, start), stop + 1):
        y0, y1 = float(y[k]), float(y[k + 1])
        if min(y0, y1) <= lvl <= max(y0, y1) and abs(y1 - y0) > 1e-30:
            return float(_err_interp_cross_time(t, y, k, lvl))
    return None


def _level_cross_after_index(
    t: np.ndarray,
    y: np.ndarray,
    level: float,
    start_idx: int,
    stop_idx: int,
    *,
    prefer_after_idx: int | None = None,
) -> float | None:
    """Raw level crossing in an index window, optionally preferring the later half."""
    if len(t) < 2 or len(y) != len(t):
        return None
    start = max(0, min(int(start_idx), len(t) - 2))
    stop = max(start, min(int(stop_idx), len(t) - 2))
    lvl = float(level)
    crossings: list[float] = []
    for k in range(start, stop + 1):
        y0, y1 = float(y[k]), float(y[k + 1])
        if min(y0, y1) <= lvl <= max(y0, y1) and abs(y1 - y0) > 1e-30:
            crossings.append(float(_err_interp_cross_time(t, y, k, lvl)))
    if not crossings:
        return None
    if prefer_after_idx is not None:
        prefer_idx = max(start, min(int(prefer_after_idx), stop))
        prefer_t = float(t[prefer_idx])
        for candidate in crossings:
            if candidate >= prefer_t:
                return float(candidate)
    return float(crossings[0])


def _err_irr_ha_level_series(
    irr: np.ndarray,
    ha: float,
    ipk_global: int,
    *,
    force_signed: bool = False,
) -> tuple[np.ndarray, float]:
    # Err 光标 A 表示逻辑 Irr 与 Ha 的真实交点。即使恢复电流正峰值、
    # Ha 也为正，也不能在 |Irr| 上求交，否则 A 可能卡在 -Ha 处。
    # 保留 force_signed 参数以兼容现有调用方；当前语义始终使用有符号波形。
    del ipk_global, force_signed
    return np.asarray(irr, dtype=np.float64), float(ha)


def _err_true_irr_ha_cross_t(
    t: np.ndarray,
    irr: np.ndarray,
    ha: float,
    ipk_global: int,
    i_end: int,
    *,
    after_idx: int,
    force_signed: bool = False,
) -> float | None:
    """First real Irr/Ha crossing after the settled-gate index."""
    if len(t) < 2 or len(irr) != len(t):
        return None
    y, level = _err_irr_ha_level_series(
        irr,
        ha,
        ipk_global,
        force_signed=force_signed,
    )
    start = max(0, min(max(int(ipk_global), int(after_idx) - 1), len(t) - 2))
    stop = max(start, min(int(i_end), len(t) - 2))
    t_after = float(t[max(0, min(int(after_idx), len(t) - 1))])
    seg = np.asarray(y[start : stop + 2], dtype=np.float64)
    if len(seg) < 2:
        return None
    d0 = seg[:-1] - level
    d1 = seg[1:] - level
    changes = (np.abs(seg[1:] - seg[:-1]) > 1e-30) & (d0 * d1 <= 0.0) & (d0 != d1)
    for offset in np.flatnonzero(changes):
        k = start + int(offset)
        t_cross = float(_err_interp_cross_time(t, y, k, level))
        if t_cross + 1e-15 >= t_after:
            return t_cross
    return None


def _err_irr_ha_cross_matches(
    t: np.ndarray,
    irr: np.ndarray,
    ha: float,
    t_cross: float | None,
    ipk_global: int,
    *,
    force_signed: bool = False,
) -> bool:
    if t_cross is None or len(t) < 2 or len(irr) != len(t):
        return False
    y, level = _err_irr_ha_level_series(
        irr,
        ha,
        ipk_global,
        force_signed=force_signed,
    )
    tc = float(t_cross)
    if tc < float(t[0]) or tc > float(t[-1]):
        return False
    y_at = float(np.interp(tc, t, y))
    if abs(y_at - level) > max(0.75, 0.005 * max(abs(level), 1.0)):
        return False
    k = int(np.searchsorted(t, tc, side="right")) - 1
    k = max(0, min(k, len(t) - 2))
    for kk in ((k - 1, k) if k > 0 else (k,)):
        y0, y1 = float(y[kk]), float(y[kk + 1])
        d0, d1 = y0 - level, y1 - level
        if abs(y1 - y0) > 1e-30 and (
            (d0 == 0.0 and d1 != 0.0) or (d0 * d1 <= 0.0 and d0 != d1)
        ):
            return True
    return False


def _err_ic_fall_cross_after_peak(
    t_seg: np.ndarray,
    seg_abs: np.ndarray,
    ipk: int,
    ha: float,
    dt: float,
) -> tuple[int, float]:
    """A：尖峰后下降沿与 Ha 的第一次下降穿越。"""
    hold = max(2, int(15e-9 / max(dt, 1e-15)))
    for k in range(ipk, len(seg_abs) - hold - 1):
        if seg_abs[k] > ha and seg_abs[k + 1] <= ha:
            if float(np.mean(seg_abs[k + 1 : k + 1 + hold])) <= ha + max(
                5.0, 0.15 * ha
            ):
                return k, _err_interp_cross_time(t_seg, seg_abs, k, ha)
    ix = _crossing_pair_index(seg_abs, ha, "falling", ipk)
    if ix is not None:
        return int(ix), _err_interp_cross_time(t_seg, seg_abs, int(ix), ha)
    return ipk, float(t_seg[ipk])


def _err_window_mid(arr: np.ndarray, t: np.ndarray, t_lo_s: float, t_hi_s: float) -> float:
    """[t_lo,t_hi] 秒窗内波形 (max+min)/2（带符号，平台有效值）。"""
    i0 = int(np.searchsorted(t, float(t_lo_s), side="left"))
    i1 = int(np.searchsorted(t, float(t_hi_s), side="right"))
    i0 = max(0, min(i0, len(arr) - 1))
    i1 = max(i0 + 1, min(i1, len(arr)))
    seg = np.asarray(arr[i0:i1], dtype=np.float64)
    if len(seg) < 2:
        return float(seg[0]) if len(seg) else 0.0
    return 0.5 * (float(np.max(seg)) + float(np.min(seg)))


def _err_vd_main_rise_search(
    t: np.ndarray,
    vd: np.ndarray,
    hb_hint: float,
    ipk_global: int,
    dt: float,
    *,
    pre_peak_ns: float = 800.0,
    post_peak_ns: float = 50.0,
) -> tuple[int, int, int | None, float]:
    """Err Vd 主上升沿搜索：限定在第二脉冲开通过程/反向恢复 IRM 附近。"""
    ipk_global = int(ipk_global)
    lo = max(0, ipk_global - int(float(pre_peak_ns) * 1e-9 / max(dt, 1e-15)))
    hi = min(len(vd) - 2, ipk_global + int(float(post_peak_ns) * 1e-9 / max(dt, 1e-15)))
    if hi <= lo + 1:
        return lo, hi, None, float(vd[min(ipk_global, len(vd) - 1)])
    peak_hi = hi if float(post_peak_ns) > 50.0 else min(ipk_global, hi)
    v_peak = float(np.max(vd[lo : peak_hi + 1]))
    span = max(abs(v_peak - float(hb_hint)), 1.0)
    trigger_step = min(max(30.0, 0.50 * span), 0.85 * span)
    trigger = float(hb_hint) + trigger_step
    k_trigger: int | None = None
    for k in range(lo, hi + 1):
        if float(vd[k]) >= trigger:
            k_trigger = k
            break
    return lo, hi, k_trigger, v_peak


def _err_vd_base_before_main_rise(
    t: np.ndarray,
    vd: np.ndarray,
    hb_hint: float,
    ipk_global: int,
    dt: float,
    *,
    prefer_post_peak_main_rise: bool = False,
) -> float:
    """Err Hb：第二脉冲开通过程中，Vd 主上升沿前的本地 base。"""
    pre_peak_ns = 250.0 if prefer_post_peak_main_rise else 800.0
    post_peak_ns = 650.0 if prefer_post_peak_main_rise else 50.0
    _lo, _hi, k_trigger, _v_peak = _err_vd_main_rise_search(
        t,
        vd,
        hb_hint,
        ipk_global,
        dt,
        pre_peak_ns=pre_peak_ns,
        post_peak_ns=post_peak_ns,
    )
    if k_trigger is None:
        return float(hb_hint)
    pre_hi = int(np.searchsorted(t, float(t[k_trigger]) - 35e-9, side="left"))
    pre_lo = int(np.searchsorted(t, float(t[k_trigger]) - 155e-9, side="left"))
    pre_lo = max(0, min(pre_lo, len(vd) - 1))
    pre_hi = max(pre_lo + 1, min(pre_hi, len(vd)))
    seg = np.asarray(vd[pre_lo:pre_hi], dtype=np.float64)
    if len(seg) < 8:
        return float(hb_hint)
    return float(_platform_center_rejecting_rise_tail(seg, dt, min_ns=120.0))


def _err_vd_rise_cross_hb_t(
    t: np.ndarray,
    vd: np.ndarray,
    hb: float,
    ipk_global: int,
    i0: int,
    dt: float,
    *,
    prefer_low_current_main_rise: bool = False,
    prefer_main_rise: bool = False,
    prefer_post_peak_main_rise: bool = False,
) -> float:
    """Vd 主上升沿第一次穿 Hb（带符号）的交点。

    搜索窗以 IRM 为锚向左延伸，不得仅用 reverse_recovery 段起点截断（WH 等工况
    段起点常晚于真实抬升脚，否则会误落在段界上）。
    """
    _ = i0  # 保留参数以兼容调用方
    pre_peak_ns = 250.0 if prefer_post_peak_main_rise else 800.0
    post_peak_ns = 650.0 if prefer_post_peak_main_rise else 50.0
    lo, hi, k_trigger, v_peak = _err_vd_main_rise_search(
        t,
        vd,
        hb,
        ipk_global,
        dt,
        pre_peak_ns=pre_peak_ns,
        post_peak_ns=post_peak_ns,
    )
    if hi <= lo + 1:
        return float(t[min(ipk_global, len(t) - 1)])
    span = abs(float(v_peak) - float(hb))
    if (prefer_main_rise or prefer_post_peak_main_rise) and k_trigger is not None and (
        prefer_post_peak_main_rise
        or span >= 500.0
        or span < 260.0
        or abs(float(hb)) >= 1.0
    ):
        if prefer_post_peak_main_rise:
            raw_window_ns = 60.0
        else:
            raw_window_ns = 100.0 if span >= 500.0 else (40.0 if span < 260.0 else 60.0)
        raw_lo = max(
            lo,
            int(np.searchsorted(t, float(t[k_trigger]) - raw_window_ns * 1e-9, side="left")),
        )
        raw_hi = min(int(k_trigger), hi)
        raw_ix = _first_sustained_rise_crossing(
            vd,
            float(hb),
            raw_lo,
            raw_hi,
            int(k_trigger),
            dt,
            span,
        )
        if raw_ix is not None:
            return float(_err_interp_cross_time(t, vd, int(raw_ix), float(hb)))
    if prefer_low_current_main_rise and k_trigger is not None and span <= 250.0:
        raw_lo = max(
            lo,
            int(np.searchsorted(t, float(t[k_trigger]) - 40e-9, side="left")),
        )
        raw_hi = min(int(k_trigger), hi)
        for k in range(raw_lo, raw_hi + 1):
            y0 = float(vd[k])
            y1 = float(vd[k + 1])
            if y0 <= float(hb) <= y1 and y1 > y0 and abs(y1 - y0) > 1e-30:
                return float(_err_interp_cross_time(t, vd, k, float(hb)))
    lookahead = _samples_for_seconds(dt, 120e-9, minimum=2)
    min_rise = 30.0
    scan_lo = lo
    if prefer_post_peak_main_rise and k_trigger is not None:
        scan_lo = max(
            lo,
            int(np.searchsorted(t, float(t[k_trigger]) - 90e-9, side="left")),
        )
    for k in range(scan_lo, hi):
        y0 = float(vd[k])
        y1 = float(vd[k + 1])
        if not (y0 <= float(hb) <= y1 and y1 > y0 and abs(y1 - y0) > 1e-30):
            continue
        k_hi = min(hi + 1, k + lookahead + 1)
        if float(np.max(vd[k : k_hi + 1])) - float(hb) < min_rise:
            continue
        return float(_err_interp_cross_time(t, vd, k, float(hb)))
    _, t_cross = _main_edge_level_crossing(
        t[lo : hi + 1],
        vd[lo : hi + 1],
        float(hb),
        v_peak,
        "rising",
        0,
        dt,
        min_trigger=30.0,
        prefer_raw_crossing=True,
        raw_window_ns=80.0 if prefer_post_peak_main_rise else 160.0,
        first_sustained_rise=prefer_post_peak_main_rise,
    )
    return float(t_cross)


def _err_has_dominant_opposite_rebound(
    irr: np.ndarray,
    ipk_global: int,
    i_end: int,
    peak: float,
    dt: float,
) -> bool:
    """True when a post-IRM opposite rebound would make the first |Irr| cross early."""
    if abs(float(peak)) < 1.0:
        return False
    k0 = max(0, int(ipk_global) + int(80e-9 / max(dt, 1e-15)))
    k1 = min(
        len(irr) - 1,
        int(i_end),
        int(ipk_global) + int(350e-9 / max(dt, 1e-15)),
    )
    if k1 <= k0 + 2:
        return False
    seg = np.asarray(irr[k0 : k1 + 1], dtype=np.float64)
    if float(peak) > 0.0:
        rebound = max(0.0, -float(np.min(seg)))
    else:
        rebound = max(0.0, float(np.max(seg)))
    return rebound >= 0.95 * abs(float(peak))


def _err_irr_fall_cross_ha_t(
    t: np.ndarray,
    irr: np.ndarray,
    ha: float,
    ipk_global: int,
    i_end: int,
    dt: float,
    *,
    force_signed: bool = False,
    settle_idx: int | None = None,
    settle_end_idx: int | None = None,
    settle_strict: bool = False,
) -> float | None:
    """IRM 主峰后恢复沿与 Ha 的第一个真实交点（秒）。

    光标 A 始终按逻辑 Irr 与带符号 Ha 求交，避免正 Ha 被卡到 -Ha。
    """
    k0 = max(0, int(ipk_global))
    k1 = max(k0 + 1, min(int(i_end), len(irr) - 1))
    y, lvl = _err_irr_ha_level_series(
        irr,
        ha,
        ipk_global,
        force_signed=force_signed,
    )

    crossings: list[tuple[int, float, str]] = []
    for k in range(k0, k1):
        y0, y1 = float(y[k]), float(y[k + 1])
        if min(y0, y1) <= lvl <= max(y0, y1) and abs(y1 - y0) > 1e-30:
            direction = "falling" if y1 < y0 else "rising"
            crossings.append((k, _err_interp_cross_time(t, y, k, lvl), direction))

    if crossings:
        if settle_idx is not None:
            settle_lo = max(k0, int(settle_idx) - 1)
            settle_hi = (
                min(k1, int(settle_end_idx) + max(2, int(30e-9 / max(dt, 1e-15))))
                if settle_end_idx is not None
                else k1
            )
            for k, t_cross, _direction in crossings:
                if settle_lo <= int(k) <= settle_hi:
                    return float(t_cross)
            for k, t_cross, _direction in crossings:
                if int(k) >= settle_lo:
                    return float(t_cross)
        for _k, t_cross, direction in crossings:
            if direction == "falling":
                return float(t_cross)
        return float(crossings[0][1])

    t_seg = t[k0 : k1 + 1]
    seg_abs = np.abs(np.asarray(irr[k0 : k1 + 1], dtype=np.float64))
    if len(seg_abs) >= 4:
        _, t_cross = _err_ic_fall_cross_after_peak(
            t_seg, seg_abs, 0, abs(lvl), dt
        )
        if t_cross > float(t[k0]):
            return float(t_cross)
    return float(t[min(k0 + 1, len(t) - 1)])


def err_energy_markers(
    t: np.ndarray,
    irr: np.ndarray,
    v_diode: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    i_search_end: int | None = None,
    *,
    vge: np.ndarray | None = None,
    pulse1_off: int | None = None,
    pulse2_on: int | None = None,
    pulse2_off: int | None = None,
    dc_current: float | None = None,
    lower_bridge_irr_from_ic_minus_il: bool = False,
) -> EnergyLossMarkers:
    """
    反向恢复损耗 Err（示波器卡尺）：
    Ha=尖峰下降沿震荡结束后的 Irr 平台/幅值光标；Hb=电压抬升前 Vd 平台；
    A=下降沿与 Ha 的第一个交点；B=电压上升沿与 Hb 的第一个交点。
    调用方应传入 reverse_recovery 段索引 [i0,i1]。
    """
    i0 = max(0, min(i0, len(t) - 2))
    i1 = max(i0 + 2, min(i1, len(t) - 1))
    seg_i = np.asarray(irr[i0 : i1 + 1], dtype=np.float64)
    seg_v = np.abs(np.asarray(v_diode[i0 : i1 + 1], dtype=np.float64))
    t_seg = t[i0 : i1 + 1]
    if len(seg_i) < 12:
        return EnergyLossMarkers(
            0.0,
            0.0,
            float(t[i0]),
            float(t[i1]),
            int(i0),
            int(i1),
        )

    ipk = err_recovery_peak_index(seg_i, dt)
    ipk_global = i0 + ipk
    if i_search_end is None:
        i_search_end = min(
            i1 + max(5, int(800e-9 / max(dt, 1e-15))), len(t) - 1
        )
    else:
        i_search_end = max(i0, min(int(i_search_end), len(t) - 1))

    irr_full = np.asarray(irr, dtype=np.float64)
    vd_full = np.asarray(v_diode, dtype=np.float64)
    tpk = float(t[ipk_global])
    # Low-IRM captures can still carry a recovery ringing packet when the
    # segmenter's compact ``turn_on`` window ends.  Treating that boundary as
    # the Err search ceiling makes A land on an early ringing crossing even
    # though the same pulse contains a settled-tail crossing a few hundred
    # nanoseconds later.  Extend only when the post-boundary packet remains
    # large relative to the actual recovery peak; established HT/RT cases
    # whose tail is already small keep their historical window bit-for-bit.
    initial_search_end = int(i_search_end)
    hard_search_end = (
        min(len(t) - 1, max(initial_search_end, int(pulse2_off)))
        if pulse2_off is not None
        else len(t) - 1
    )
    peak_abs = abs(float(irr_full[ipk_global]))
    unsettled_tail_extended = False
    if 80.0 <= peak_abs <= 130.0 and hard_search_end > initial_search_end:
        lookahead_end = min(
            hard_search_end,
            initial_search_end
            + _samples_for_seconds(dt, 120e-9, minimum=8),
        )
        if lookahead_end >= initial_search_end + 8:
            post_tail = irr_full[initial_search_end : lookahead_end + 1]
            post_tail_pp = float(np.max(post_tail) - np.min(post_tail))
            unsettled_limit = max(35.0, 0.35 * peak_abs)
            if post_tail_pp >= unsettled_limit:
                i_search_end = min(
                    hard_search_end,
                    initial_search_end
                    + _samples_for_seconds(dt, 300e-9, minimum=8),
                )
                unsettled_tail_extended = int(i_search_end) > initial_search_end
    # legacy 先找主 IRM 后的恢复稳定入口；新口径只把它作为 Err 本地
    # Top/Base 窗口的事件锚点，不能继续把 (max+min)/2 当成 Ha Top。
    err_base = _err_recovery_settled_base(irr_full, ipk_global, dt, i_search_end)
    ha_tail = float(err_base.level)
    peak = float(irr_full[ipk_global])
    lower_bridge_post_peak_vd_b = (
        bool(lower_bridge_irr_from_ic_minus_il)
        and peak < 0.0
        and abs(float(peak)) >= 120.0
    )
    # Hb=第二脉冲开通过程中，对管电压 Vd 主上升沿前的本地 base。
    # B 必须贴同一段 Vd 与该横线的真实交点，不能取全局或关断过程 base。
    hb_hint = _err_window_mid(vd_full, t, tpk - 600e-9, tpk - 200e-9)
    hb_v = _err_vd_base_before_main_rise(
        t,
        vd_full,
        hb_hint,
        ipk_global,
        dt,
        prefer_post_peak_main_rise=lower_bridge_post_peak_vd_b,
    )
    prefer_low_current_b = abs(float(peak)) < 125.0
    prefer_main_rise_b = (
        peak > 0.0 and abs(float(peak)) >= 120.0
    ) or lower_bridge_post_peak_vd_b
    # B=Vd 主抬升沿与 Hb 的首个上升穿越（带符号 Vd）。Err 的
    # Ha(Irr) 需要按点击参数后的局部放大窗口 Top 定义取值，所以先确定 B，
    # 再用 B 与 Irr 稳定入口组成局部窗口；不得用全波形 Top/Base。
    t_b_v = _err_vd_rise_cross_hb_t(
        t,
        vd_full,
        hb_v,
        ipk_global,
        i0,
        dt,
        prefer_low_current_main_rise=prefer_low_current_b,
        prefer_main_rise=prefer_main_rise_b,
        prefer_post_peak_main_rise=lower_bridge_post_peak_vd_b,
    )
    if not _use_legacy_loss_platform_mode():
        hb_from_offset = _err_vd_base_from_offset_window(t, vd_full, t_b_v, err_base)
        if hb_from_offset is not None:
            hb_v = float(hb_from_offset)
            t_b_v = _err_vd_rise_cross_hb_t(
                t,
                vd_full,
                hb_v,
                ipk_global,
                i0,
                dt,
                prefer_low_current_main_rise=prefer_low_current_b,
                prefer_main_rise=prefer_main_rise_b,
                prefer_post_peak_main_rise=lower_bridge_post_peak_vd_b,
            )
    if not _use_legacy_loss_cursor_mode():
        ha_top = _err_ha_top_from_offset_window(
            t,
            irr_full,
            t_b_v,
            err_base,
            dt,
            vge=vge,
            pulse1_off=pulse1_off,
            pulse2_on=pulse2_on,
            pulse2_off=pulse2_off,
        )
        if ha_top is not None:
            ha_tail = float(ha_top)
        if dc_current is not None and abs(float(dc_current)) <= 150.0:
            stable_top = _err_low_current_stable_top_from_offset_window(
                t,
                irr_full,
                err_base,
                dt,
                vge=vge,
                pulse1_off=pulse1_off,
                pulse2_on=pulse2_on,
                pulse2_off=pulse2_off,
            )
            if stable_top is not None:
                top_drift = abs(float(ha_tail) - float(err_base.level))
                drift_limit = max(3.0, 0.35 * max(float(err_base.amp), 0.0))
                if top_drift > drift_limit:
                    ha_tail = float(stable_top)
    signed_tail_after_rebound = peak > 0.0 and float(ha_tail) < 0.0 and (
        abs(float(ha_tail)) >= max(3.0, 0.03 * abs(float(peak)))
        or _err_has_dominant_opposite_rebound(irr_full, ipk_global, i_search_end, peak, dt)
    )
    ha = float(ha_tail)
    i_fall_end = max(
        ipk_global + 2,
        min(
            max(int(i_search_end), int(err_base.end_idx) + 2),
            max(err_base.end_idx + 2, ipk_global + int(120e-9 / max(dt, 1e-15))),
        ),
    )
    force_signed_a = ha < 0.0
    a_search_end = max(
        ipk_global + 2,
        min(
            len(t) - 1,
            max(
                int(i_search_end),
                int(err_base.end_idx)
                + _samples_for_seconds(dt, 900e-9, minimum=4),
            ),
        ),
    )
    t_a_irr = _err_irr_fall_cross_ha_t(
        t,
        irr_full,
        ha,
        ipk_global,
        i_fall_end,
        dt,
        force_signed=force_signed_a,
        settle_idx=err_base.start_idx,
        settle_end_idx=err_base.end_idx,
        settle_strict=err_base.strict,
    )
    if t_a_irr is None:
        t_a_irr = _err_true_irr_ha_cross_t(
            t,
            irr_full,
            ha,
            ipk_global,
            a_search_end,
            after_idx=err_base.end_idx,
            force_signed=force_signed_a,
        )
    if t_a_irr is None:
        t_a_irr = _err_true_irr_ha_cross_t(
            t,
            irr_full,
            ha,
            ipk_global,
            a_search_end,
            after_idx=err_base.start_idx,
            force_signed=force_signed_a,
        )
    if t_a_irr is None:
        t_a_irr = float(t[min(max(ipk_global + 1, int(err_base.end_idx)), len(t) - 1)])
    if (
        peak > 0.0
        and signed_tail_after_rebound
        and ha < 0.0
        and abs(float(peak)) >= 120.0
    ):
        legacy_base = _legacy_err_recovery_settled_base(
            irr_full,
            ipk_global,
            dt,
            i_search_end,
        )
        far_shift = (int(err_base.start_idx) - int(legacy_base.start_idx)) * max(
            float(dt), 1e-15
        )
        if far_shift > 300e-9:
            guard_ns = 35.0 if abs(float(peak)) >= 300.0 else 45.0
            guarded_t = _first_level_cross_after_time(
                t,
                irr_full,
                ha,
                float(t[legacy_base.end_idx]) + guard_ns * 1e-9,
                dt,
            )
            if guarded_t is not None and guarded_t < t_a_irr - 20e-9:
                t_a_irr = float(guarded_t)
    soft_recovery_ha_floor = _err_positive_soft_recovery_ha_signal_floor(
        peak,
    )
    if (
        not unsettled_tail_extended
        and peak > 0.0
        and ha >= soft_recovery_ha_floor
        and abs(float(peak)) >= 120.0
    ):
        early_soft_t = _err_positive_soft_recovery_early_cross_t(
            t,
            irr_full,
            ha,
            ipk_global,
            i_search_end,
            dt,
        )
        if early_soft_t is not None and t_a_irr > early_soft_t + 180e-9:
            t_a_irr = float(early_soft_t)
    if peak > 0.0 and ha < 0.0 and abs(float(peak)) >= 300.0:
        stable_legacy_base = _legacy_err_recovery_settled_base(
            irr_full,
            ipk_global,
            dt,
            i_search_end,
        )
        base_shift_s = (
            int(err_base.start_idx) - int(stable_legacy_base.start_idx)
        ) * max(
            float(dt), 1e-15
        )
        if (
            0.0 <= base_shift_s <= 300e-9
            and float(err_base.amp) <= max(34.0, 0.10 * abs(float(peak)))
        ):
            settled_t = _first_level_cross_after_time(
                t,
                irr_full,
                ha,
                float(t[max(0, min(int(err_base.end_idx), len(t) - 1))]),
                dt,
                window_ns=180.0,
            )
            if settled_t is not None and settled_t > t_a_irr + 20e-9:
                t_a_irr = float(settled_t)
    lower_bridge_positive_ha = (
        bool(lower_bridge_irr_from_ic_minus_il)
        and peak < 0.0
        and ha > 0.0
        and abs(float(peak)) >= 120.0
    )
    if lower_bridge_positive_ha:
        stable_cross_t = _err_true_irr_ha_cross_t(
            t,
            irr_full,
            ha,
            ipk_global,
            a_search_end,
            after_idx=err_base.end_idx,
            force_signed=True,
        )
        if stable_cross_t is not None and (
            t_a_irr < stable_cross_t - 20e-9 or t_a_irr > stable_cross_t + 200e-9
        ):
            t_a_irr = float(stable_cross_t)
    negative_tail_t = None
    if not lower_bridge_positive_ha:
        negative_tail_t = _err_negative_ringing_tail_cross_t(
            t,
            irr_full,
            ha,
            ipk_global,
            i_search_end,
            dt,
        )
    if negative_tail_t is not None and negative_tail_t > t_a_irr + 20e-9:
        t_a_irr = float(negative_tail_t)
    if dc_current is not None and abs(float(dc_current)) <= 150.0:
        stable_cross_t = _first_level_cross_after_time(
            t,
            irr_full,
            ha,
            float(t[max(0, min(int(err_base.end_idx), len(t) - 1))]) + 80e-9,
            dt,
            window_ns=900.0,
        )
        if stable_cross_t is not None:
            t_a_irr = float(stable_cross_t)
    if abs(float(peak)) >= 120.0 and not _err_irr_ha_cross_matches(
        t,
        irr_full,
        ha,
        t_a_irr,
        ipk_global,
        force_signed=force_signed_a,
    ):
        corrected_t = _err_true_irr_ha_cross_t(
            t,
            irr_full,
            ha,
            ipk_global,
            a_search_end,
            after_idx=err_base.end_idx,
            force_signed=force_signed_a,
        )
        if corrected_t is None:
            corrected_t = _err_true_irr_ha_cross_t(
                t,
                irr_full,
                ha,
                ipk_global,
                a_search_end,
                after_idx=err_base.start_idx,
                force_signed=force_signed_a,
            )
        if corrected_t is None:
            corrected_t = _err_true_irr_ha_cross_t(
                t,
                irr_full,
                ha,
                ipk_global,
                a_search_end,
                after_idx=ipk_global,
                force_signed=force_signed_a,
            )
        if corrected_t is not None:
            t_a_irr = float(corrected_t)
    if abs(t_a_irr - t_b_v) < 1e-15:
        t_a_irr, t_b_v = float(t[i0]), float(t[i1])

    # A=Irr 与 Ha 交点；B=Vd 与 Hb 交点（B 往往早于 A）
    t_start = float(t_a_irr)
    t_end = float(t_b_v)
    t_lo = min(t_start, t_end)
    t_hi = max(t_start, t_end)

    i_start = int(np.searchsorted(t, t_lo, side="left"))
    i_end = int(np.searchsorted(t, t_hi, side="left"))
    i_start = max(0, min(i_start, len(t) - 2))
    i_end = max(i_start + 1, min(i_end, len(t) - 1))

    return EnergyLossMarkers(
        float(ha),
        float(hb_v),
        float(t_start),
        float(t_end),
        i_start,
        i_end,
        v_b=float(hb_v),
    )


def energy_window_power(
    t: np.ndarray,
    v: np.ndarray,
    i: np.ndarray,
    center_idx: int,
    dt: float,
    pre_ns: float = 80.0,
    post_ns: float = 500.0,
    p_start_frac: float = 0.03,
    p_end_frac: float = 0.02,
) -> IntegrationWindow:
    """Power-threshold window (3% Pmax → 2% Pmax), robust when IEC crossings collapse."""
    w0 = max(0, center_idx - int(pre_ns * 1e-9 / dt))
    w1 = min(len(t) - 1, center_idx + int(post_ns * 1e-9 / dt))
    p = np.abs(v[w0:w1] * i[w0:w1])
    if len(p) < 10:
        return IntegrationWindow(w0, w1, float(t[w0]), float(t[w1]))
    pmax = float(np.max(p))
    if pmax < 1.0:
        return IntegrationWindow(w0, w1, float(t[w0]), float(t[w1]))
    th_hi = p_start_frac * pmax
    th_lo = p_end_frac * pmax
    above_hi = np.where(p >= th_hi)[0]
    above_lo = np.where(p >= th_lo)[0]
    if len(above_hi) == 0 or len(above_lo) == 0:
        return IntegrationWindow(w0, w1, float(t[w0]), float(t[w1]))
    i_start = w0 + int(above_hi[0])
    i_end = w0 + int(above_lo[-1])
    if i_end <= i_start + 5:
        i_end = min(w1, i_start + int(400e-9 / dt))
    return IntegrationWindow(i_start, i_end, float(t[i_start]), float(t[i_end]))


def integrate_vi_window(
    t: np.ndarray,
    v: np.ndarray,
    i: np.ndarray,
    win: IntegrationWindow,
) -> float:
    """∫ v·i dt in mJ."""
    i0, i1 = win.i_start, win.i_end
    if i1 <= i0 + 1:
        return 0.0
    seg_t = t[i0:i1]
    p = v[i0:i1] * i[i0:i1]
    dt_arr = np.diff(seg_t)
    p_mid = 0.5 * (p[:-1] + p[1:])
    return float(np.sum(p_mid * dt_arr)) * 1e3


def integrate_err_recovery(
    t: np.ndarray,
    v_diode: np.ndarray,
    irr: np.ndarray,
    win: IntegrationWindow,
) -> float:
    """反向恢复 Err：|Vd|×|Irr|，兼容下桥 Ic−IL 为负及 Vd 小幅负偏。"""
    return integrate_vi_window(
        t,
        np.abs(np.asarray(v_diode, dtype=np.float64)),
        np.abs(np.asarray(irr, dtype=np.float64)),
        win,
    )


def integrate_vi_window_base_compensated(
    t: np.ndarray,
    v: np.ndarray,
    i: np.ndarray,
    win: IntegrationWindow,
    v_base: float,
    i_base: float,
    use_abs_i: bool = True,
) -> float:
    """
    Base-compensated ∫ v·i dt in mJ.
    功率采用 max(v-v_base,0) * max(i-i_base,0)，更贴近“任一量回到 base 则损耗≈0”。
    """
    i0, i1 = win.i_start, win.i_end
    if i1 <= i0 + 1:
        return 0.0
    seg_t = t[i0 : i1 + 1]
    seg_v = v[i0 : i1 + 1]
    seg_i = np.abs(i[i0 : i1 + 1]) if use_abs_i else i[i0 : i1 + 1]
    v_eff = np.maximum(seg_v - float(v_base), 0.0)
    i_eff = np.maximum(seg_i - float(i_base), 0.0)
    p = v_eff * i_eff
    dt_arr = np.diff(seg_t)
    if len(dt_arr) == 0:
        return 0.0
    p_mid = 0.5 * (p[:-1] + p[1:])
    return float(np.sum(p_mid * dt_arr)) * 1e3


RR_SLOPE_TAIL_NS = 250.0
RR_SLOPE_COMPLETION_FRACTION = 0.90


def rr_slope_window_indices(
    on0: int,
    rr1: int,
    n_samples: int,
    dt: float,
    *,
    tail_ns: float = RR_SLOPE_TAIL_NS,
) -> tuple[int, int]:
    """
    反向恢复 di/dt、dv/dt 搜索窗：turn-on 起点 → reverse_recovery 段末 + tail。
    与 pipeline/extract 及 GUI 斜率交互共用。
    """
    i0 = max(0, min(int(on0), n_samples - 2))
    tail = max(0, int(round(float(tail_ns) * 1e-9 / dt)))
    i1 = max(i0 + 2, min(n_samples - 1, int(rr1) + tail))
    return i0, i1


def rr_completed_measurement_window_indices(
    on0: int,
    rr1: int,
    event_end_idx: int,
    v_diode: np.ndarray,
    n_samples: int,
    dt: float,
) -> tuple[int, int, bool]:
    """Return the legacy RR slope window, extending only when its edge is incomplete.

    The default RR dv/dt measurement needs the physical 90% crossing of the
    event-local ``max(abs(Vd))``.  Some slow commutations finish after the
    segmenter's ``rr1 + 250 ns`` tail.  In that case the legacy window can
    contain neither that crossing nor the matching current commutation edge,
    yet still publish plausible slopes from pre-edge drift.

    Keep the legacy window bit-stable whenever it already reaches 90% of the
    complete turn-on event's ``|Vd|`` peak.  Otherwise, extend only to the
    caller-supplied end of that same turn-on event.  The boolean tells callers
    whether RR peak/platform-dependent contexts must use the completed end too.
    """
    i0, legacy_i1 = rr_slope_window_indices(on0, rr1, n_samples, dt)
    if n_samples < 2:
        return i0, legacy_i1, False

    event_i1 = max(i0 + 2, min(int(event_end_idx), int(n_samples)))
    if event_i1 <= legacy_i1:
        return i0, legacy_i1, False

    vd = np.abs(np.asarray(v_diode, dtype=np.float64))
    available = min(len(vd), int(n_samples))
    legacy_end = min(int(legacy_i1), available)
    event_end = min(int(event_i1), available)
    if legacy_end <= i0 or event_end <= legacy_end:
        return i0, legacy_i1, False

    legacy_finite = vd[i0:legacy_end]
    legacy_finite = legacy_finite[np.isfinite(legacy_finite)]
    event_finite = vd[i0:event_end]
    event_finite = event_finite[np.isfinite(event_finite)]
    if legacy_finite.size == 0 or event_finite.size == 0:
        return i0, legacy_i1, False

    legacy_peak = float(np.max(legacy_finite))
    event_peak = float(np.max(event_finite))
    incomplete = (
        event_peak > 1e-12
        and legacy_peak
        < RR_SLOPE_COMPLETION_FRACTION * event_peak
    )
    return i0, event_i1 if incomplete else legacy_i1, bool(incomplete)
