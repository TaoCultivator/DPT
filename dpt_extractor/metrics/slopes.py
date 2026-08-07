from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy.ndimage import median_filter

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.metrics.plateau_level import (
    _plateau_mid_without_isolated_spikes,
    dvdt_rr_vd_plateau_top,
)
from dpt_extractor.models.slope_range import AUTO_MAX_SLOPE_SPAN_PERCENT
from dpt_extractor.utils.signal import (
    crossing_time,
    max_slope_filtered,
    slope_between_crossings,
    threshold_value,
)


def rr_dvdt_prefers_settled_platform(
    irr: np.ndarray,
    irr_peak_a: float,
    compact_event_end_idx: int,
    pulse_end_idx: int,
    dt: float,
) -> bool:
    """Whether low-IRM ringing makes the Vd overshoot an invalid dv/dt Top.

    The 0729 LT reference captures have a real low-current recovery edge
    followed by a large ringing packet.  In that morphology the absolute Vd
    maximum is a later overshoot, not the stable blocking-voltage endpoint.
    Keep the historical peak-amplitude definition for all other records.
    """
    y = np.asarray(irr, dtype=np.float64)
    n = len(y)
    if n < 12:
        return False
    event_end = max(0, min(int(compact_event_end_idx), n - 1))
    pulse_end = max(event_end, min(int(pulse_end_idx), n - 1))
    if pulse_end <= event_end:
        return False
    peak_abs = abs(float(irr_peak_a))
    if not 80.0 <= peak_abs <= 130.0:
        return False
    lookahead = max(8, int(round(120e-9 / max(float(dt), 1e-15))))
    tail_end = min(pulse_end, event_end + lookahead)
    if tail_end < event_end + 8:
        return False
    post_tail = y[event_end : tail_end + 1]
    post_tail_pp = float(np.max(post_tail) - np.min(post_tail))
    return post_tail_pp >= max(35.0, 0.35 * peak_abs)


def _rr_dvdt_settled_base_top(
    t: np.ndarray,
    vd_abs: np.ndarray,
    i0: int,
    i1: int,
    event_end_idx: int | None,
    dt: float,
) -> tuple[float, float, float, float] | None:
    """Return event-local stable Vd Base/Top for a ringing-polluted RR edge."""
    t_arr = np.asarray(t, dtype=np.float64)
    y = np.asarray(vd_abs, dtype=np.float64)
    n = min(len(t_arr), len(y))
    if n < 12:
        return None
    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 2, min(int(i1), n))
    event_end = (
        i1 - 1
        if event_end_idx is None
        else max(i0 + 1, min(int(event_end_idx), n - 1))
    )
    peak_idx = i0 + int(np.argmax(y[i0 : event_end + 1]))
    search_end = min(
        n - 1,
        max(
            peak_idx + 2,
            int(np.searchsorted(t_arr, float(t_arr[peak_idx]) + 1.35e-6)),
        ),
    )
    top = float(
        dvdt_rr_vd_plateau_top(
            t_arr,
            y,
            peak_idx,
            dt,
            search_end,
        )
    )
    if not np.isfinite(top) or top <= 1e-9:
        return None

    seg_t = t_arr[i0:i1]
    seg_y = y[i0:i1]
    first_rise = crossing_time(seg_t, seg_y, 0.10 * top, "rising", start=0)
    base = 0.0
    if first_rise is not None:
        base_i0 = int(np.searchsorted(t_arr, float(first_rise) - 400e-9))
        base_i1 = int(np.searchsorted(t_arr, float(first_rise) - 100e-9))
        base_i0 = max(0, min(base_i0, n - 2))
        base_i1 = max(base_i0 + 2, min(base_i1, n))
        base_band = y[base_i0:base_i1]
        base_band = base_band[np.isfinite(base_band)]
        if len(base_band) >= 2:
            # This range is already a declared, edge-adjacent stable band.
            # Tek-style modal Top/Base would split its ripple and bias Base
            # toward one side of the visible trace.  The slope reference must
            # instead sit at the spike-guarded raw (max + min) / 2 centre.
            base = float(_plateau_mid_without_isolated_spikes(base_band))
    if abs(base) <= 0.01 * abs(top):
        base = 0.0
    if base >= top:
        return None
    return float(base), float(top)


def dvdt_off(
    t: np.ndarray,
    vce: np.ndarray,
    vdc: float,
    i0: int,
    i1: int,
    cfg: AppConfig,
    pct_lo: float | None = None,
    pct_hi: float | None = None,
    vce_top: float | None = None,
) -> float:
    """关断 Vce 上升 dv/dt：阈值相对电压 Top（100% Vce），在 Vge 下降同窗内搜穿越。"""
    lo = cfg.thresholds.low_pct if pct_lo is None else pct_lo
    hi = cfg.thresholds.high_pct if pct_hi is None else pct_hi
    top = vce_top if vce_top is not None and vce_top > 0 else vdc
    return dvdt_vce_rise(
        t, vce, top, i0, i1, lo, hi, vce_top=top, search_from_vce_min=True
    )


def didt_off(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    cfg: AppConfig,
    pct_start: float | None = None,
    pct_end: float | None = None,
    ic_reference: str = "peak",
    ic_direction: str = "fall",
    icm_override: float | None = None,
    search_from_peak: bool = False,
) -> float:
    """
    关断 di/dt (A/ns)。
    阈值相对关断前电流 Top（icm_override）；在 Vge 下降窗内搜 90%→10% 等下降穿越。
    """
    p0 = cfg.thresholds.high_pct if pct_start is None else pct_start
    p1 = cfg.thresholds.low_pct if pct_end is None else pct_end
    if ic_direction == "rise":
        return didt_ic_rise(
            t,
            ic,
            i0,
            i1,
            p0,
            p1,
            ic_reference=ic_reference,
            icm_override=icm_override,
            search_from_peak=search_from_peak,
        )
    return didt_ic_fall(
        t,
        ic,
        i0,
        i1,
        p0,
        p1,
        ic_reference=ic_reference,
        icm_override=icm_override,
        search_from_peak=search_from_peak,
    )


def dvdt_on(
    t: np.ndarray,
    vce: np.ndarray,
    vdc: float,
    i0: int,
    i1: int,
    cfg: AppConfig,
    pct_hi: float | None = None,
    pct_lo: float | None = None,
    vce_top: float | None = None,
) -> float:
    """开通 Vce 下降段 dv/dt (V/ns)，阈值相对开通 Top（100% Vce）。"""
    hi = cfg.thresholds.high_pct if pct_hi is None else pct_hi
    lo = cfg.thresholds.low_pct if pct_lo is None else pct_lo
    top = vce_top if vce_top is not None and vce_top > 0 else vdc
    return dvdt_vce_fall(
        t, vce, top, i0, i1, hi, lo, vce_top=top, search_from_vce_max=False
    )


def didt_on(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    cfg: AppConfig,
    pct_start: float | None = None,
    pct_end: float | None = None,
    ic_reference: str = "peak",
    ic_direction: str = "rise",
    icm_override: float | None = None,
    search_from_peak: bool = False,
) -> float:
    """
    开通 di/dt (A/ns)。
    阈值相对开通电流 Top（100% Ic），在开通段内顺序搜上升/下降穿越。
    (1) 10%→90%·Ic 上升；(2) 50%→90%·Ic 上升；(3) 80%→20%·Ic 上升（高→低阈值）。
    """
    p0 = cfg.thresholds.low_pct if pct_start is None else pct_start
    p1 = cfg.thresholds.high_pct if pct_end is None else pct_end
    if ic_direction == "fall":
        return didt_ic_fall(
            t,
            ic,
            i0,
            i1,
            p0,
            p1,
            ic_reference=ic_reference,
            icm_override=icm_override,
            search_from_peak=search_from_peak,
        )
    return didt_ic_rise(
        t,
        ic,
        i0,
        i1,
        p0,
        p1,
        ic_reference=ic_reference,
        icm_override=icm_override,
        search_from_peak=search_from_peak,
    )


@dataclass(frozen=True)
class DvdtCrossingResult:
    """Ha/Hb 为 Top/Base 时，按百分比在两者之间找穿越点。"""

    dvdt: float
    t_pct_a_s: float | None
    t_pct_b_s: float | None
    th_a: float
    th_b: float
    resolved_pct_a: float | None = None
    resolved_pct_b: float | None = None


def dvdt_between_base_top(
    t: np.ndarray,
    y: np.ndarray,
    i0: int,
    i1: int,
    base_v: float,
    top_v: float,
    pct_a: float,
    pct_b: float,
    edge: str,
    *,
    use_abs: bool = False,
) -> DvdtCrossingResult:
    """
    在 [i0,i1] 内按 Base–Top 电压跨度计算阈值穿越。
    pct_a/pct_b 为 0~1 分数（如 10%→0.1, 90%→0.9）。
    edge: 'rise' 为电压上升沿；'fall' 为下降沿。
    """
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    v_lo = float(min(base_v, top_v))
    v_hi = float(max(base_v, top_v))
    span = v_hi - v_lo
    if span <= 1e-9:
        return DvdtCrossingResult(0.0, None, None, v_lo, v_hi)
    th_a = v_lo + float(pct_a) * span
    th_b = v_lo + float(pct_b) * span
    seg_t = t[i0 : i1 + 1]
    seg_y = y[i0 : i1 + 1].astype(np.float64)
    if use_abs:
        seg_y = np.abs(seg_y)
    if len(seg_t) < 2:
        return DvdtCrossingResult(0.0, None, None, th_a, th_b)

    if edge == "rise":
        start = max(0, int(np.argmin(seg_y)) - 1)
        if float(pct_a) > float(pct_b):
            # 开通 80%→20% 等：沿上升沿先低后高，A=高%、B=低%（t_a > t_b）
            t_b = crossing_time(seg_t, seg_y, th_b, "rising", start=start)
            if t_b is None:
                t_b = crossing_time(seg_t, seg_y, th_b, "rising", start=0)
            if t_b is None:
                return DvdtCrossingResult(0.0, None, None, th_a, th_b)
            local = int(np.searchsorted(seg_t, t_b, side="left"))
            local = max(0, min(local, len(seg_t) - 2))
            t_a = crossing_time(seg_t, seg_y, th_a, "rising", start=local)
            if t_a is None:
                t_a = crossing_time(seg_t, seg_y, th_a, "rising", start=0)
            if t_a is None or t_a <= t_b:
                return DvdtCrossingResult(0.0, t_a, t_b, th_a, th_b)
        else:
            t_a = crossing_time(seg_t, seg_y, th_a, "rising", start=start)
            if t_a is None:
                t_a = crossing_time(seg_t, seg_y, th_a, "rising", start=0)
            if t_a is None:
                return DvdtCrossingResult(0.0, None, None, th_a, th_b)
            local = int(np.searchsorted(seg_t, t_a, side="left"))
            local = max(0, min(local, len(seg_t) - 2))
            t_b = crossing_time(seg_t, seg_y, th_b, "rising", start=local)
            if t_b is None or t_b <= t_a:
                return DvdtCrossingResult(0.0, t_a, None, th_a, th_b)
    else:
        start = max(0, int(np.argmax(seg_y)) - 1)
        t_a = crossing_time(seg_t, seg_y, th_a, "falling", start=start)
        if t_a is None:
            t_a = crossing_time(seg_t, seg_y, th_a, "falling", start=0)
        if t_a is None:
            return DvdtCrossingResult(0.0, None, None, th_a, th_b)
        local = int(np.searchsorted(seg_t, t_a, side="left"))
        local = max(0, min(local, len(seg_t) - 2))
        t_b = crossing_time(seg_t, seg_y, th_b, "falling", start=local)
        if t_b is None or t_b <= t_a:
            return DvdtCrossingResult(0.0, t_a, None, th_a, th_b)
    dt_s = t_b - t_a
    if abs(dt_s) < 1e-15:
        return DvdtCrossingResult(0.0, t_a, t_b, th_a, th_b)
    dvdt = abs(th_b - th_a) / abs(dt_s) / 1e9
    return DvdtCrossingResult(float(dvdt), float(t_a), float(t_b), th_a, th_b)


@dataclass(frozen=True)
class DidtCrossingResult:
    """Ha/Hb 为电流 Top/Base 时，按百分比在两者之间找穿越点。"""

    didt: float
    t_pct_a_s: float | None
    t_pct_b_s: float | None
    th_a: float
    th_b: float
    idm: float | None = None
    irm: float | None = None
    resolved_pct_a: float | None = None
    resolved_pct_b: float | None = None


def _linear_window_quality(
    t_s: np.ndarray,
    progress: np.ndarray,
    start: int,
    end: int,
    reversal_tolerance: float,
) -> tuple[float, float, float, float]:
    """Return fitted slope, R², monotonic share and fitted amplitude."""

    x = np.asarray(t_s[start : end + 1], dtype=np.float64)
    y = np.asarray(progress[start : end + 1], dtype=np.float64)
    if len(x) < 3 or not np.isfinite(x).all() or not np.isfinite(y).all():
        return 0.0, 0.0, 0.0, 0.0
    x = x - float(x[0])
    duration = float(x[-1])
    if duration <= 0.0:
        return 0.0, 0.0, 0.0, 0.0
    design = np.column_stack((x, np.ones_like(x)))
    slope, intercept = np.linalg.lstsq(design, y, rcond=None)[0]
    fitted = slope * x + intercept
    residual = float(np.sum((y - fitted) ** 2))
    total = float(np.sum((y - float(np.mean(y))) ** 2))
    r2 = 1.0 - residual / total if total > 1e-18 else 0.0
    monotonic = float(np.mean(np.diff(y) >= -float(reversal_tolerance)))
    amplitude = float(slope * duration)
    return float(slope), float(r2), monotonic, amplitude


def _auto_max_slope_percentages(
    t: np.ndarray,
    y: np.ndarray,
    base_v: float,
    top_v: float,
    edge: str,
    anchor: DvdtCrossingResult,
    *,
    use_abs: bool = False,
) -> tuple[float, float, float, float] | None:
    """Select the fastest valid fixed-percentage band on the main edge.

    The broad ``anchor`` is supplied by each parameter's existing episode
    detector, so this locator cannot jump to a different pulse or later
    ringing packet.  A fixed 20 percentage-point window is slid through that
    anchor and ranked by its average slope.  Filtering and quality gates are
    used only to choose the band.  Callers then run their established raw
    crossing routine again at the resolved levels.
    """

    if anchor.t_pct_a_s is None or anchor.t_pct_b_s is None:
        return None
    tt = np.asarray(t, dtype=np.float64)
    yy = np.asarray(y, dtype=np.float64)
    n = min(len(tt), len(yy))
    if n < 7:
        return None
    tt = tt[:n]
    yy = yy[:n]
    if use_abs:
        yy = np.abs(yy)
    lo_t = min(float(anchor.t_pct_a_s), float(anchor.t_pct_b_s))
    hi_t = max(float(anchor.t_pct_a_s), float(anchor.t_pct_b_s))
    i0 = max(0, int(np.searchsorted(tt, lo_t, side="left")) - 1)
    i1 = min(n - 1, int(np.searchsorted(tt, hi_t, side="right")))
    if i1 - i0 + 1 < 7:
        return None
    seg_t = tt[i0 : i1 + 1]
    seg_y = yy[i0 : i1 + 1]
    if not np.isfinite(seg_t).all() or not np.isfinite(seg_y).all():
        return None
    if np.any(np.diff(seg_t) <= 0.0):
        return None

    low = float(min(base_v, top_v))
    high = float(max(base_v, top_v))
    span = high - low
    if not np.isfinite(span) or span <= 1e-12:
        return None
    level = (seg_y - low) / span
    progress = level if edge == "rise" else 1.0 - level

    # A small sample-count-derived median kernel rejects isolated spikes while
    # preserving the duration of a genuinely short switching edge.  It never
    # sets the reported A/B levels or the final slope.
    kernel = max(3, 2 * max(1, len(progress) // 50) + 1)
    kernel = min(9, kernel)
    if kernel >= len(progress):
        kernel = len(progress) if len(progress) % 2 == 1 else len(progress) - 1
    located = median_filter(progress, size=max(1, kernel), mode="nearest")
    if len(located) >= 3:
        padded = np.pad(located, (1, 1), mode="edge")
        located = (
            0.25 * padded[:-2] + 0.50 * padded[1:-1] + 0.25 * padded[2:]
        )

    increments = np.diff(located)
    curvature = np.diff(located, n=2)
    median_curvature = float(np.median(curvature)) if len(curvature) else 0.0
    noise = (
        0.5
        * 1.4826
        * float(np.median(np.abs(curvature - median_curvature)))
        if len(curvature)
        else 0.0
    )
    reversal_tolerance = max(0.003, 3.0 * noise)
    fixed_span = float(AUTO_MAX_SLOPE_SPAN_PERCENT) / 100.0
    if fixed_span + 1e-12 < max(0.015, 4.0 * noise):
        return None

    # Derive the usable progress bounds from the anchored times rather than
    # ``anchor.th_*``.  RR di/dt keeps those thresholds in the original
    # signed probe coordinate while ``located`` is polarity-normalized.
    anchor_progress = (
        float(np.interp(lo_t, seg_t, located)),
        float(np.interp(hi_t, seg_t, located)),
    )
    progress_lo = max(0.01, min(anchor_progress))
    progress_hi = min(0.99, max(anchor_progress))
    latest_start = progress_hi - fixed_span
    if latest_start < progress_lo - 1e-12:
        return None

    # Half-percent placement resolution keeps the automatic result stable and
    # still lets the fixed 20% band follow the fastest part of a curved edge.
    grid_step = 0.005
    first_grid = np.ceil((progress_lo - 1e-12) / grid_step) * grid_step
    last_grid = np.floor((latest_start + 1e-12) / grid_step) * grid_step
    candidate_starts = list(
        np.arange(first_grid, last_grid + 0.5 * grid_step, grid_step)
    )
    for boundary in (progress_lo, latest_start):
        if not any(
            abs(float(value) - boundary) < 1e-9
            for value in candidate_starts
        ):
            candidate_starts.append(boundary)
    candidate_starts.sort()

    best: tuple[float, float, float, float] | None = None
    for start_progress in candidate_starts:
        start_progress = float(start_progress)
        end_progress = start_progress + fixed_span
        start_t = crossing_time(
            seg_t, located, start_progress, "rising", start=0
        )
        if start_t is None:
            continue
        start_search = max(
            0,
            min(
                len(seg_t) - 2,
                int(np.searchsorted(seg_t, start_t, side="left")) - 1,
            ),
        )
        end_t = crossing_time(
            seg_t,
            located,
            end_progress,
            "rising",
            start=start_search,
        )
        if end_t is None or end_t <= start_t:
            continue
        quality_start = max(
            0, int(np.searchsorted(seg_t, start_t, side="left")) - 1
        )
        quality_end = min(
            len(seg_t) - 1,
            int(np.searchsorted(seg_t, end_t, side="right")),
        )
        slope, r2, monotonic, amplitude = _linear_window_quality(
            seg_t,
            located,
            quality_start,
            quality_end,
            reversal_tolerance,
        )
        if (
            slope <= 0.0
            or r2 < 0.80
            or monotonic < 0.70
            or amplitude < 0.70 * fixed_span
        ):
            continue
        average_slope = fixed_span / (float(end_t) - float(start_t))
        candidate = (average_slope, r2, start_progress, float(start_t))
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return None

    _average_slope, _r2, start_progress, start_t = best
    end_progress = start_progress + fixed_span
    start_search = max(
        0,
        min(
            len(seg_t) - 2,
            int(np.searchsorted(seg_t, start_t, side="left")) - 1,
        ),
    )
    end_t = crossing_time(
        seg_t, located, end_progress, "rising", start=start_search
    )
    if end_t is None or end_t <= start_t:
        return None
    if edge == "rise":
        return start_progress, end_progress, float(start_t), float(end_t)
    return (
        1.0 - start_progress,
        1.0 - end_progress,
        float(start_t),
        float(end_t),
    )


def auto_dvdt_between_base_top(
    t: np.ndarray,
    y: np.ndarray,
    i0: int,
    i1: int,
    base_v: float,
    top_v: float,
    edge: str,
    *,
    use_abs: bool = False,
) -> DvdtCrossingResult:
    """Automatic valid-band variant of :func:`dvdt_between_base_top`."""

    anchor: DvdtCrossingResult | None = None
    for low_pct, high_pct in (
        (0.02, 0.98),
        (0.05, 0.95),
        (0.10, 0.90),
        (0.20, 0.80),
    ):
        broad_a, broad_b = (
            (low_pct, high_pct)
            if edge == "rise"
            else (high_pct, low_pct)
        )
        candidate = dvdt_between_base_top(
            t,
            y,
            i0,
            i1,
            base_v,
            top_v,
            broad_a,
            broad_b,
            edge,
            use_abs=use_abs,
        )
        if candidate.t_pct_a_s is not None and candidate.t_pct_b_s is not None:
            anchor = candidate
            break
    if anchor is None:
        return DvdtCrossingResult(0.0, None, None, float(base_v), float(top_v))
    percentages = _auto_max_slope_percentages(
        t, y, base_v, top_v, edge, anchor, use_abs=use_abs
    )
    if percentages is None:
        return DvdtCrossingResult(0.0, None, None, anchor.th_a, anchor.th_b)
    pct_a, pct_b, selected_t0, selected_t1 = percentages
    local_i0 = max(
        int(i0), int(np.searchsorted(np.asarray(t), selected_t0, side="left")) - 2
    )
    local_i1 = min(
        int(i1), int(np.searchsorted(np.asarray(t), selected_t1, side="right")) + 1
    )
    result = dvdt_between_base_top(
        t,
        y,
        local_i0,
        local_i1,
        base_v,
        top_v,
        pct_a,
        pct_b,
        edge,
        use_abs=use_abs,
    )
    if result.t_pct_a_s is None or result.t_pct_b_s is None:
        return result
    return replace(result, resolved_pct_a=pct_a, resolved_pct_b=pct_b)


def auto_didt_between_base_top(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    base_a: float,
    top_a: float,
    edge: str,
    *,
    use_abs: bool = True,
) -> DidtCrossingResult:
    """Automatic valid-band variant of :func:`didt_between_base_top`."""

    raw = auto_dvdt_between_base_top(
        t, ic, i0, i1, base_a, top_a, edge, use_abs=use_abs
    )
    return DidtCrossingResult(
        raw.dvdt,
        raw.t_pct_a_s,
        raw.t_pct_b_s,
        raw.th_a,
        raw.th_b,
        resolved_pct_a=raw.resolved_pct_a,
        resolved_pct_b=raw.resolved_pct_b,
    )


def _didt_fall_robust(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    base_a: float,
    top_a: float,
    pct_a: float,
    pct_b: float,
    *,
    use_abs: bool = True,
) -> DidtCrossingResult | None:
    """关断电流下降 di/dt（抗导通纹波）。

    通用穿越从峰值起找首个高百分位（如 90%）下降穿越，导通纹波若跌破该阈值会被
    误锚定。低百分位（如 10%）仅在真实关断下降时才到达，因此先锚定低百分位穿越，
    再向时间更早处回溯最近一次高百分位穿越，得到真实开关沿。
    """
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    v_lo = float(min(base_a, top_a))
    v_hi = float(max(base_a, top_a))
    span = v_hi - v_lo
    if span <= 1e-9:
        return None
    f_hi = max(float(pct_a), float(pct_b))
    f_lo = min(float(pct_a), float(pct_b))
    th_hi = v_lo + f_hi * span
    th_lo = v_lo + f_lo * span
    seg_t = t[i0 : i1 + 1]
    seg_y = ic[i0 : i1 + 1].astype(np.float64)
    if use_abs:
        seg_y = np.abs(seg_y)
    if len(seg_t) < 2:
        return None
    start = max(0, int(np.argmax(seg_y)) - 1)
    dt_s = float(np.median(np.diff(seg_t))) if len(seg_t) > 1 else 0.0
    hold = max(3, int(round(5e-9 / max(dt_s, 1e-15))))
    hold = min(64, hold)
    tolerance = 0.01 * max(span, 1.0)
    low_idx: int | None = None
    low_crossings = np.flatnonzero(
        (seg_y[:-1] >= th_lo) & (seg_y[1:] < th_lo)
    )
    for k_raw in low_crossings:
        k = int(k_raw)
        if k < start:
            continue
        tail = seg_y[k + 1 : min(len(seg_y), k + 1 + hold)]
        if len(tail) >= 3 and float(np.mean(tail <= th_lo + tolerance)) >= 0.70:
            low_idx = k
            break
    if low_idx is None:
        return None
    y0 = float(seg_y[low_idx])
    y1 = float(seg_y[low_idx + 1])
    frac = (th_lo - y0) / (y1 - y0) if abs(y1 - y0) > 1e-30 else 0.0
    t_lo = float(
        seg_t[low_idx] + frac * (seg_t[low_idx + 1] - seg_t[low_idx])
    )
    local = low_idx + 1
    t_hi: float | None = None
    for k in range(local - 1, start - 1, -1):
        if seg_y[k] >= th_hi > seg_y[k + 1]:
            y0, y1 = seg_y[k], seg_y[k + 1]
            frac = (th_hi - y0) / (y1 - y0) if abs(y1 - y0) > 1e-30 else 0.0
            t_hi = float(seg_t[k] + frac * (seg_t[k + 1] - seg_t[k]))
            break
    if t_hi is None or t_lo <= t_hi:
        return None
    didt = abs(th_hi - th_lo) / abs(t_lo - t_hi) / 1e9
    if float(pct_a) >= float(pct_b):
        return DidtCrossingResult(float(didt), t_hi, t_lo, th_hi, th_lo)
    return DidtCrossingResult(float(didt), t_lo, t_hi, th_lo, th_hi)


def didt_between_base_top(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    base_a: float,
    top_a: float,
    pct_a: float,
    pct_b: float,
    edge: str,
    *,
    use_abs: bool = True,
) -> DidtCrossingResult:
    """在 [i0,i1] 内按 Base–Top 电流跨度计算 di/dt 真实穿越。

    ``use_abs`` 保留开通等历史幅值域口径。关断逻辑 Ic 已由通道映射
    自动定向，且其 Base 必须保持带符号，因此关断调用方使用原始带符号
    坐标，避免“负参考电平却在 |Ic| 上找交点”的不可达混用。
    """
    if edge == "fall":
        robust = _didt_fall_robust(
            t,
            ic,
            i0,
            i1,
            base_a,
            top_a,
            pct_a,
            pct_b,
            use_abs=use_abs,
        )
        if robust is not None:
            return robust
    r = dvdt_between_base_top(
        t,
        ic,
        i0,
        i1,
        float(base_a),
        float(top_a),
        pct_a,
        pct_b,
        edge,
        use_abs=use_abs,
    )
    return DidtCrossingResult(
        float(r.dvdt), r.t_pct_a_s, r.t_pct_b_s, r.th_a, r.th_b
    )


def _sustained_rise_between_base_top(
    t: np.ndarray,
    y: np.ndarray,
    i0: int,
    i1: int,
    base_v: float,
    top_v: float,
    pct_a: float,
    pct_b: float,
    dt: float,
) -> DvdtCrossingResult | None:
    """Find raw A/B intersections around a rise that reaches a lasting high level.

    The persistence check is used only to choose the physical switching edge;
    the returned times are still linearly interpolated intersections of the raw
    waveform.  This prevents an isolated pre-edge spike from becoming cursor A.
    """
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    v_lo = float(min(base_v, top_v))
    v_hi = float(max(base_v, top_v))
    span = v_hi - v_lo
    if span <= 1e-9:
        return None
    th_a = v_lo + float(pct_a) * span
    th_b = v_lo + float(pct_b) * span
    th_lo = min(th_a, th_b)
    th_hi = max(th_a, th_b)
    seg_t = np.asarray(t[i0 : i1 + 1], dtype=np.float64)
    seg_y = np.asarray(y[i0 : i1 + 1], dtype=np.float64)
    if len(seg_t) < 3:
        return None

    hold = max(3, int(round(5e-9 / max(float(dt), 1e-15))))
    hold = min(64, hold)
    tolerance = 0.01 * max(span, 1.0)
    high_crossings = np.flatnonzero(
        (seg_y[:-1] < th_hi) & (seg_y[1:] >= th_hi)
    )
    high_idx: int | None = None
    for k_raw in high_crossings:
        k = int(k_raw)
        tail = seg_y[k + 1 : min(len(seg_y), k + 1 + hold)]
        if len(tail) >= 3 and float(np.mean(tail >= th_hi - tolerance)) >= 0.70:
            high_idx = k
            break
    if high_idx is None:
        return None

    low_crossings = np.flatnonzero(
        (seg_y[: high_idx + 1] < th_lo)
        & (seg_y[1 : high_idx + 2] >= th_lo)
    )
    if len(low_crossings) == 0:
        return None
    low_idx = int(low_crossings[-1])

    def _interp(k: int, threshold: float) -> float:
        y0 = float(seg_y[k])
        y1 = float(seg_y[k + 1])
        frac = (threshold - y0) / (y1 - y0) if abs(y1 - y0) > 1e-30 else 0.0
        return float(seg_t[k] + frac * (seg_t[k + 1] - seg_t[k]))

    t_lo = _interp(low_idx, th_lo)
    t_hi = _interp(high_idx, th_hi)
    if t_hi <= t_lo:
        return None
    value = abs(th_hi - th_lo) / (t_hi - t_lo) / 1e9
    if th_a <= th_b:
        return DvdtCrossingResult(float(value), t_lo, t_hi, th_a, th_b)
    return DvdtCrossingResult(float(value), t_hi, t_lo, th_a, th_b)


def _turn_on_main_rise_between_base_top(
    t: np.ndarray,
    y: np.ndarray,
    i0: int,
    plateau_window: tuple[int, int],
    base_v: float,
    top_v: float,
    pct_a: float,
    pct_b: float,
    dt: float,
) -> tuple[DvdtCrossingResult | None, tuple[int, int]]:
    """Lock turn-on A/B to the rise episode that feeds the declared Ha band.

    A short pre-edge pulse can contain perfectly valid raw percentage
    crossings, so a crossing-equality check alone is not enough.  Starting at
    the confirmed Ha plateau, walk back to the last sustained low-state block
    and only search the following episode.  Returned A/B and thresholds are
    always chronological/low-to-high, matching the oscilloscope's visible
    left/right cursor names even when a custom percentage label is reversed.
    """

    tt = np.asarray(t, dtype=np.float64)
    yy = np.asarray(y, dtype=np.float64)
    n = min(len(tt), len(yy))
    if n < 4:
        return None, (0, 0)
    h0, h1 = (int(plateau_window[0]), int(plateau_window[1]))
    i0 = max(0, min(int(i0), n - 2))
    h0 = max(i0 + 2, min(h0, n - 1))
    h1 = max(h0, min(h1, n - 1))
    span = float(top_v - base_v)
    if not np.isfinite(span) or span <= 1e-9:
        return None, (i0, h0)

    f_lo = min(float(pct_a), float(pct_b))
    f_hi = max(float(pct_a), float(pct_b))
    th_lo = float(base_v + f_lo * span)
    th_hi = float(base_v + f_hi * span)
    if not (np.isfinite(th_lo) and np.isfinite(th_hi)) or th_hi <= th_lo:
        return None, (i0, h0)

    # The episode gate stays below the lower published threshold.  A genuine
    # rise therefore crosses both thresholds after the chosen low-state block.
    positive_lo = max(0.0, f_lo)
    gate_fraction = max(
        0.005,
        min(0.08, 0.5 * positive_lo if positive_lo > 0.0 else 0.005),
    )
    gate = float(base_v + gate_fraction * span)
    seg = yy[i0 : h0 + 1]
    if len(seg) < 4 or not np.isfinite(seg).all():
        return None, (i0, h0)
    low = seg <= gate + 0.005 * max(abs(span), 1.0)
    dt_s = max(float(dt), 1e-15)
    max_hole = max(1, int(round(10e-9 / dt_s)))
    min_low = max(3, int(round(20e-9 / dt_s)))

    # Close only brief high holes surrounded by low state.  A 12 ns false
    # pulse remains a separator; a few-sample noise excursion does not.
    closed = low.copy()
    k = 0
    while k < len(closed):
        if closed[k]:
            k += 1
            continue
        j = k + 1
        while j < len(closed) and not closed[j]:
            j += 1
        if k > 0 and j < len(closed) and j - k <= max_hole:
            closed[k:j] = True
        k = j

    runs: list[tuple[int, int]] = []
    k = 0
    while k < len(closed):
        if not closed[k]:
            k += 1
            continue
        j = k + 1
        while j < len(closed) and closed[j]:
            j += 1
        if j - k >= min_low and j < len(closed):
            runs.append((k, j))
        k = j
    if not runs:
        return None, (i0, h0)
    _low_start, low_end = runs[-1]
    episode_start = max(i0, i0 + low_end - 1)

    search_y = yy[episode_start : h0 + 1]
    low_crosses = np.flatnonzero(
        (search_y[:-1] < th_lo) & (search_y[1:] >= th_lo)
    )
    if len(low_crosses) == 0:
        return None, (episode_start, h0)
    low_idx = episode_start + int(low_crosses[0])
    high_y = yy[low_idx : h0 + 1]
    high_crosses = np.flatnonzero(
        (high_y[:-1] < th_hi) & (high_y[1:] >= th_hi)
    )
    if len(high_crosses) == 0:
        return None, (episode_start, h0)
    high_idx = low_idx + int(high_crosses[0])
    if high_idx < low_idx or h0 <= high_idx or h1 < h0:
        return None, (episode_start, h0)

    def _interp(k0: int, threshold: float) -> float:
        y0 = float(yy[k0])
        y1 = float(yy[k0 + 1])
        frac = (threshold - y0) / (y1 - y0) if abs(y1 - y0) > 1e-30 else 0.0
        return float(tt[k0] + frac * (tt[k0 + 1] - tt[k0]))

    t_lo = _interp(low_idx, th_lo)
    t_hi = _interp(high_idx, th_hi)
    if not (np.isfinite(t_lo) and np.isfinite(t_hi)) or t_hi <= t_lo:
        return None, (episode_start, h0)
    value = abs(th_hi - th_lo) / (t_hi - t_lo) / 1e9
    return (
        DvdtCrossingResult(float(value), t_lo, t_hi, th_lo, th_hi),
        (episode_start, h0),
    )


@dataclass(frozen=True)
class DvdtMeasurementContext:
    """一次 dv/dt 测量的参考电平、真实交点与最终值。"""

    base_v: float
    top_v: float
    crossing: DvdtCrossingResult
    used_fallback: bool = False


def turn_on_dvdt_measurement_context(
    t: np.ndarray,
    vce: np.ndarray,
    top_v: float,
    i0: int,
    i1: int,
    dt: float,
    cfg: AppConfig,
    pct_hi: float,
    pct_lo: float,
    *,
    event_end_idx: int | None = None,
    auto_max: bool = False,
) -> DvdtMeasurementContext:
    """Build the canonical turn-on Vce dv/dt context.

    The accepted DPT definition is ``pct * VceTop`` rather than a percentage
    of the post-fall local platform span.  ``i1`` is inclusive, matching the
    turn-on segment stored in :class:`SegmentIndices`.  Keeping the zero
    reference, A/B crossings and fallback together prevents the result card
    and its default GUI cursors from silently measuring different slopes.
    """

    t_arr = np.asarray(t, dtype=np.float64)
    vce_arr = np.asarray(vce, dtype=np.float64)
    n = min(len(t_arr), len(vce_arr))
    if n < 2:
        crossing = DvdtCrossingResult(0.0, None, None, 0.0, 0.0)
        return DvdtMeasurementContext(0.0, float(top_v), crossing, True)
    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 1, min(int(i1), n - 1))
    top = float(top_v)
    if auto_max:
        crossing = auto_dvdt_between_base_top(
            t_arr,
            vce_arr,
            i0,
            i1,
            0.0,
            top,
            "fall",
        )
        if (
            (crossing.t_pct_a_s is None or crossing.t_pct_b_s is None)
            and event_end_idx is not None
        ):
            extended_i1 = max(i1, min(int(event_end_idx), n - 1))
            if extended_i1 > i1:
                extended = auto_dvdt_between_base_top(
                    t_arr,
                    vce_arr,
                    i0,
                    extended_i1,
                    0.0,
                    top,
                    "fall",
                )
                if (
                    extended.t_pct_a_s is not None
                    and extended.t_pct_b_s is not None
                ):
                    crossing = extended
        return DvdtMeasurementContext(
            0.0,
            top,
            crossing,
            crossing.t_pct_a_s is None or crossing.t_pct_b_s is None,
        )
    high_pct = max(float(pct_hi), float(pct_lo))
    low_pct = min(float(pct_hi), float(pct_lo))
    th_hi = high_pct * top
    th_lo = low_pct * top
    seg_t = t_arr[i0 : i1 + 1]
    seg_y = vce_arr[i0 : i1 + 1]
    t_a = crossing_time(seg_t, seg_y, th_hi, "falling", start=0)
    t_b = None
    if t_a is not None:
        local = int(np.searchsorted(seg_t, t_a, side="left"))
        local = max(0, min(local, len(seg_t) - 2))
        t_b = crossing_time(seg_t, seg_y, th_lo, "falling", start=local)
    complete = t_a is not None and t_b is not None and t_b > t_a
    # Some slow turn-on records finish the physical Vce fall after the
    # segmenter's compact turn-on display window.  Preserve the historical
    # window whenever it already contains both crossings; only a missing pair
    # may extend to the real second-pulse turn-off boundary.
    if not complete and event_end_idx is not None:
        extended_i1 = max(i1, min(int(event_end_idx), n - 1))
        if extended_i1 > i1:
            extended_t = t_arr[i0 : extended_i1 + 1]
            extended_y = vce_arr[i0 : extended_i1 + 1]
            extended_a = crossing_time(
                extended_t, extended_y, th_hi, "falling", start=0
            )
            extended_b = None
            if extended_a is not None:
                local = int(
                    np.searchsorted(extended_t, extended_a, side="left")
                )
                local = max(0, min(local, len(extended_t) - 2))
                extended_b = crossing_time(
                    extended_t,
                    extended_y,
                    th_lo,
                    "falling",
                    start=local,
                )
            if (
                extended_a is not None
                and extended_b is not None
                and extended_b > extended_a
            ):
                t_a = extended_a
                t_b = extended_b
                complete = True
    value = (
        abs(th_hi - th_lo) / abs(float(t_b) - float(t_a)) / 1e9
        if complete
        else 0.0
    )
    used_fallback = value < 1e-6
    if used_fallback:
        value = dvdt_max(t_arr, vce_arr, i0, i1 + 1, dt, cfg)
    crossing = DvdtCrossingResult(
        float(value),
        float(t_a) if t_a is not None else None,
        float(t_b) if t_b is not None and complete else None,
        th_hi,
        th_lo,
    )
    return DvdtMeasurementContext(0.0, top, crossing, used_fallback)


def rr_dvdt_measurement_context(
    t: np.ndarray,
    v_d: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    cfg: AppConfig,
    pct_lo: float,
    pct_hi: float,
    *,
    fallback_i0: int | None = None,
    fallback_i1: int | None = None,
    use_settled_platform: bool = False,
    event_end_idx: int | None = None,
    auto_max: bool = False,
) -> DvdtMeasurementContext:
    """Build the canonical reverse-recovery ``|Vd|`` dv/dt context.

    ``i1`` is exclusive to preserve the long-standing
    :func:`dvdt_diode_recovery` search window.  The default Ha is the same
    ``|VDM|`` peak used by the numeric result and Hb is its zero-amplitude
    reference.  A narrowly detected low-IRM ringing morphology may instead
    use the event-local stable blocking-voltage Base/Top so a later overshoot
    cannot steal the 90% crossing.
    """

    t_arr = np.asarray(t, dtype=np.float64)
    vd_arr = np.asarray(v_d, dtype=np.float64)
    n = min(len(t_arr), len(vd_arr))
    if n < 2:
        crossing = DvdtCrossingResult(0.0, None, None, 0.0, 0.0)
        return DvdtMeasurementContext(0.0, 0.0, crossing, True)
    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 2, min(int(i1), n))
    seg_t = t_arr[i0:i1]
    seg_y = np.abs(vd_arr[i0:i1])
    base = 0.0
    top = float(np.max(seg_y)) if len(seg_y) else 0.0
    if use_settled_platform:
        settled_levels = _rr_dvdt_settled_base_top(
            t_arr,
            np.abs(vd_arr),
            i0,
            i1,
            event_end_idx,
            dt,
        )
        if settled_levels is not None:
            base, top = settled_levels
    if auto_max:
        crossing = auto_dvdt_between_base_top(
            t_arr,
            vd_arr,
            i0,
            i1 - 1,
            base,
            top,
            "rise",
            use_abs=True,
        )
        return DvdtMeasurementContext(
            base,
            top,
            crossing,
            crossing.t_pct_a_s is None or crossing.t_pct_b_s is None,
        )
    span = float(top) - float(base)
    th_lo = float(base) + float(pct_lo) * span
    th_hi = float(base) + float(pct_hi) * span
    t_a = crossing_time(seg_t, seg_y, th_lo, "rising", start=0)
    t_b = None
    if t_a is not None:
        local = int(np.searchsorted(seg_t, t_a, side="left"))
        local = max(0, min(local, len(seg_t) - 2))
        t_b = crossing_time(seg_t, seg_y, th_hi, "rising", start=local)
    complete = t_a is not None and t_b is not None and t_b > t_a
    value = (
        abs(th_hi - th_lo) / abs(float(t_b) - float(t_a)) / 1e9
        if complete
        else 0.0
    )
    used_fallback = value < 1e-6
    if used_fallback and not auto_max:
        fb0 = i0 if fallback_i0 is None else int(fallback_i0)
        fb1 = i1 if fallback_i1 is None else int(fallback_i1)
        value = dvdt_max(t_arr, vd_arr, fb0, fb1, dt, cfg)
    crossing = DvdtCrossingResult(
        float(value),
        float(t_a) if t_a is not None else None,
        float(t_b) if t_b is not None and complete else None,
        th_lo,
        th_hi,
    )
    return DvdtMeasurementContext(base, top, crossing, used_fallback)


@dataclass(frozen=True)
class DidtMeasurementContext:
    """一次 di/dt 测量的稳定电平、真实交点与最终值。"""

    base_a: float
    top_a: float
    crossing: DidtCrossingResult
    used_fallback: bool = False
    base_window: tuple[int, int] | None = None
    top_window: tuple[int, int] | None = None
    search_window: tuple[int, int] | None = None


@dataclass(frozen=True)
class RrDidtMeasurementContext:
    """一次反向恢复 di/dt 的带符号电平、真实交点与最终值。

    ``forward_a`` 是换流前二极管正向电流在原始 Irr 坐标中的稳定平台，
    ``base_a`` 是恢复后的本地稳定基线。``reverse_a`` 是反向恢复峰值；
    只有 ``50%IF→50%IRM`` 模式会把它作为 Hb。管线、GUI 和报告必须复用
    这一上下文，避免把负向主平台之后的正恢复峰误认成 IDM。
    """

    forward_a: float
    base_a: float
    reverse_a: float
    zero_a: float | None
    crossing: DidtCrossingResult
    polarity: int
    used_fallback: bool = False


@dataclass(frozen=True)
class RrDidtPreparedSeries:
    """RR slope data prepared once for the GUI horizontal-cursor hot path.

    Time repair, finite-sample repair, spike-guarded extrema and both physical
    polarities are independent of the user-selected Ha/Hb levels.  Keeping
    them here avoids repeating those full-record operations for every
    ``sigPositionChanged`` event while preserving raw-sample interpolation.
    """

    t_s: np.ndarray
    positive_a: np.ndarray
    negative_a: np.ndarray
    start_positive: int
    start_negative: int
    min_positive_a: float
    min_negative_a: float

    @property
    def valid(self) -> bool:
        return len(self.t_s) >= 4 and len(self.positive_a) == len(self.t_s)


def turn_off_dvdt_measurement_context(
    t: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    cfg: AppConfig,
    pct_a: float,
    pct_b: float,
    *,
    rise_start: int | None = None,
    rise_end: int | None = None,
    auto_max: bool = False,
) -> DvdtMeasurementContext:
    """用同一参数本地窗口生成关断 dv/dt 的完整默认测量上下文。"""
    from dpt_extractor.metrics.plateau_level import turn_off_dvdt_base_top_levels

    n = min(len(t), len(vce))
    if n < 2:
        crossing = DvdtCrossingResult(0.0, None, None, 0.0, 0.0)
        return DvdtMeasurementContext(0.0, 0.0, crossing, True)
    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 1, min(int(i1), n - 1))
    search0 = i0 if rise_start is None else max(i0, min(int(rise_start), i1 - 1))
    search1 = i1 if rise_end is None else max(search0 + 1, min(int(rise_end), i1))
    base_v, top_v = turn_off_dvdt_base_top_levels(t, vce, i0, i1)
    if auto_max:
        anchor: DvdtCrossingResult | None = None
        for low_pct, high_pct in (
            (0.02, 0.98),
            (0.05, 0.95),
            (0.10, 0.90),
            (0.20, 0.80),
        ):
            anchor = _sustained_rise_between_base_top(
                t,
                vce,
                search0,
                i1,
                base_v,
                top_v,
                low_pct,
                high_pct,
                dt,
            )
            if anchor is None:
                candidate = dvdt_between_base_top(
                    t,
                    vce,
                    search0,
                    i1,
                    base_v,
                    top_v,
                    low_pct,
                    high_pct,
                    "rise",
                )
                if (
                    candidate.t_pct_a_s is not None
                    and candidate.t_pct_b_s is not None
                ):
                    anchor = candidate
            if anchor is not None:
                break
        if anchor is None:
            crossing = DvdtCrossingResult(0.0, None, None, base_v, top_v)
            return DvdtMeasurementContext(
                float(base_v), float(top_v), crossing, True
            )
        percentages = _auto_max_slope_percentages(
            t, vce, base_v, top_v, "rise", anchor
        )
        if percentages is None:
            crossing = DvdtCrossingResult(
                0.0, None, None, anchor.th_a, anchor.th_b
            )
        else:
            auto_a, auto_b, _selected_t0, _selected_t1 = percentages
            crossing = _sustained_rise_between_base_top(
                t, vce, search0, i1, base_v, top_v, auto_a, auto_b, dt
            )
            if crossing is None:
                crossing = dvdt_between_base_top(
                    t,
                    vce,
                    search0,
                    i1,
                    base_v,
                    top_v,
                    auto_a,
                    auto_b,
                    "rise",
                )
            if crossing.t_pct_a_s is not None and crossing.t_pct_b_s is not None:
                crossing = replace(
                    crossing,
                    resolved_pct_a=auto_a,
                    resolved_pct_b=auto_b,
                )
        return DvdtMeasurementContext(
            float(base_v),
            float(top_v),
            crossing,
            crossing.t_pct_a_s is None or crossing.t_pct_b_s is None,
        )
    crossing = _sustained_rise_between_base_top(
        t, vce, search0, search1, base_v, top_v, pct_a, pct_b, dt
    )
    if crossing is None:
        crossing = dvdt_between_base_top(
            t,
            vce,
            search0,
            search1,
            base_v,
            top_v,
            pct_a,
            pct_b,
            "rise",
        )
    # Low-current/slow turn-off can reach the 90% Vce threshold after the
    # Vge-derived primary rise window.  Preserve that primary window when it
    # already yields a complete pair, but otherwise extend only to this
    # parameter's declared local end and adopt the result only when both raw
    # ordered intersections exist.  A max-slope fallback must not masquerade
    # as a complete A/B cursor pair.
    if (
        (crossing.t_pct_a_s is None or crossing.t_pct_b_s is None)
        and search1 < i1
    ):
        extended = _sustained_rise_between_base_top(
            t, vce, search0, i1, base_v, top_v, pct_a, pct_b, dt
        )
        if extended is None:
            extended = dvdt_between_base_top(
                t,
                vce,
                search0,
                i1,
                base_v,
                top_v,
                pct_a,
                pct_b,
                "rise",
            )
        if (
            extended.t_pct_a_s is not None
            and extended.t_pct_b_s is not None
        ):
            crossing = extended
    used_fallback = crossing.dvdt < 1e-6
    if used_fallback:
        fallback = dvdt_max(t, vce, search0, search1 + 1, dt, cfg)
        crossing = DvdtCrossingResult(
            float(fallback),
            crossing.t_pct_a_s,
            crossing.t_pct_b_s,
            crossing.th_a,
            crossing.th_b,
        )
    return DvdtMeasurementContext(
        float(base_v), float(top_v), crossing, used_fallback
    )


def turn_off_didt_measurement_context(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    pulse1_on: int,
    off_idx: int,
    fall_start: int,
    fall_end: int,
    dt: float,
    cfg: AppConfig,
    pct_a: float,
    pct_b: float,
    edge: str = "fall",
    *,
    next_pulse_on: int | None = None,
    auto_max: bool = False,
) -> DidtMeasurementContext:
    """用同一参数本地窗口生成关断 di/dt 的完整默认测量上下文。"""
    from dpt_extractor.metrics.plateau_level import (
        turn_off_didt_base_top_levels,
        turn_off_didt_stable_base_window_indices,
    )

    n = min(len(t), len(ic))
    if n < 2:
        crossing = DidtCrossingResult(0.0, None, None, 0.0, 0.0)
        return DidtMeasurementContext(0.0, 0.0, crossing, True)
    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 1, min(int(i1), n - 1))
    search0 = max(i0, min(int(fall_start), i1 - 1))
    search1 = max(search0 + 1, min(int(fall_end), i1))
    base_window = turn_off_didt_stable_base_window_indices(
        ic,
        i1,
        off_idx,
        fall_end,
        dt,
        next_pulse_on=next_pulse_on,
    )
    base_a, top_a = turn_off_didt_base_top_levels(
        ic,
        i0,
        i1,
        pulse1_on,
        off_idx,
        fall_start,
        fall_end,
        dt,
        next_pulse_on=next_pulse_on,
        base_window=base_window,
    )
    if auto_max:
        crossing = auto_didt_between_base_top(
            t,
            ic,
            search0,
            i1,
            base_a,
            top_a,
            "fall",
            use_abs=False,
        )
        return DidtMeasurementContext(
            float(base_a),
            float(top_a),
            crossing,
            crossing.t_pct_a_s is None or crossing.t_pct_b_s is None,
            base_window,
        )
    # Turn-off is always the physical falling Ic edge. ``edge`` is retained
    # for saved configuration compatibility; custom percentage order must not
    # redirect the measurement to a rising edge.
    _ = edge
    fall_pct_a = max(float(pct_a), float(pct_b))
    fall_pct_b = min(float(pct_a), float(pct_b))
    crossing = didt_between_base_top(
        t,
        ic,
        search0,
        search1,
        base_a,
        top_a,
        fall_pct_a,
        fall_pct_b,
        "fall",
        use_abs=False,
    )
    # Slow/low-current turn-off can finish after the Vge-derived fall window.
    # Keep that window as the primary search so established complete cases do
    # not drift, but extend to the declared parameter-local end when either
    # percentage intersection is missing.  A numerical fallback without a
    # real A/B pair is not suitable for GUI cursor verification.
    if (
        (crossing.t_pct_a_s is None or crossing.t_pct_b_s is None)
        and search1 < i1
    ):
        extended = didt_between_base_top(
            t,
            ic,
            search0,
            i1,
            base_a,
            top_a,
            fall_pct_a,
            fall_pct_b,
            "fall",
            use_abs=False,
        )
        if extended.t_pct_a_s is not None and extended.t_pct_b_s is not None:
            crossing = extended
    used_fallback = crossing.didt < 1e-6
    if used_fallback and not auto_max:
        fallback = didt_max(t, ic, search0, search1 + 1, dt, cfg)
        crossing = DidtCrossingResult(
            float(fallback),
            crossing.t_pct_a_s,
            crossing.t_pct_b_s,
            crossing.th_a,
            crossing.th_b,
            crossing.idm,
            crossing.irm,
        )
    return DidtMeasurementContext(
        float(base_a), float(top_a), crossing, used_fallback, base_window
    )


def turn_on_didt_measurement_context(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    pct_a: float,
    pct_b: float,
    edge: str = "rise",
    *,
    base_override: float | None = None,
    top_override: float | None = None,
    event_end_idx: int | None = None,
    auto_max: bool = False,
) -> DidtMeasurementContext:
    """Build one canonical turn-on di/dt context on the logical signed Ic.

    Base/Hb and Top/Ha are the same event-local stable-band midpoints used by
    the opening-current card.  Percentage levels are therefore always
    ``Base + pct * (Top - Base)``.  Raw A/B intersections are limited to the
    physical rise between those two declared platform windows; an unrelated
    pre-edge ripple or a highlighted display trace cannot become the source.
    """

    from dpt_extractor.metrics.plateau_level import (
        turn_on_current_hb_ha_t,
        turn_on_current_hb_ha_window_indices,
    )

    t_arr = np.asarray(t, dtype=np.float64)
    ic_arr = np.asarray(ic, dtype=np.float64)
    n = min(len(t_arr), len(ic_arr))
    if n < 3:
        crossing = DidtCrossingResult(0.0, None, None, 0.0, 0.0)
        return DidtMeasurementContext(0.0, 0.0, crossing, True)

    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 1, min(int(i1), n - 1))
    base_window, top_window = turn_on_current_hb_ha_window_indices(
        t_arr,
        ic_arr,
        i0,
        i1,
        dt,
        event_end_idx=event_end_idx,
    )
    default_base, default_top = turn_on_current_hb_ha_t(
        t_arr,
        ic_arr,
        i0,
        i1,
        dt,
        event_end_idx=event_end_idx,
    )
    base_a = (
        float(base_override)
        if base_override is not None and np.isfinite(float(base_override))
        else float(default_base)
    )
    top_a = (
        float(top_override)
        if top_override is not None and np.isfinite(float(top_override))
        else float(default_top)
    )

    b0, _b1 = base_window
    h0, h1 = top_window
    search0 = max(0, min(int(b0), n - 2))
    span = float(top_a - base_a)
    f_lo = min(float(pct_a), float(pct_b))
    f_hi = max(float(pct_a), float(pct_b))
    th_a = float(base_a + f_lo * span) if np.isfinite(span) else 0.0
    th_b = float(base_a + f_hi * span) if np.isfinite(span) else 0.0

    # Turn-on is always the physical rising Ic edge.  ``edge`` remains in the
    # public signature for saved configuration compatibility; reversing a
    # custom percentage label must not redirect the measurement to turn-off.
    _ = edge
    raw: DvdtCrossingResult | None = None
    search_window = (search0, max(search0 + 1, min(int(h0), n - 1)))
    if (
        h0 >= 0
        and h1 >= h0
        and np.isfinite(base_a)
        and np.isfinite(top_a)
        and span > 1e-9
    ):
        raw, search_window = _turn_on_main_rise_between_base_top(
            t_arr,
            ic_arr,
            search0,
            top_window,
            base_a,
            top_a,
            pct_a,
            pct_b,
            dt,
        )

    if auto_max:
        broad: DvdtCrossingResult | None = None
        for low_pct, high_pct in (
            (0.02, 0.98),
            (0.05, 0.95),
            (0.10, 0.90),
            (0.20, 0.80),
        ):
            broad, search_window = _turn_on_main_rise_between_base_top(
                t_arr,
                ic_arr,
                search0,
                top_window,
                base_a,
                top_a,
                low_pct,
                high_pct,
                dt,
            )
            if broad is not None:
                break
        percentages = (
            _auto_max_slope_percentages(
                t_arr, ic_arr, base_a, top_a, "rise", broad
            )
            if broad is not None
            else None
        )
        if percentages is None:
            crossing = DidtCrossingResult(0.0, None, None, th_a, th_b)
            return DidtMeasurementContext(
                base_a,
                top_a,
                crossing,
                True,
                base_window,
                top_window,
                search_window,
            )
        auto_a, auto_b, _selected_t0, _selected_t1 = percentages
        selected, search_window = _turn_on_main_rise_between_base_top(
            t_arr,
            ic_arr,
            search0,
            top_window,
            base_a,
            top_a,
            auto_a,
            auto_b,
            dt,
        )
        if selected is None:
            crossing = DidtCrossingResult(0.0, None, None, th_a, th_b)
        else:
            crossing = DidtCrossingResult(
                float(selected.dvdt),
                selected.t_pct_a_s,
                selected.t_pct_b_s,
                selected.th_a,
                selected.th_b,
                resolved_pct_a=auto_a,
                resolved_pct_b=auto_b,
            )
        return DidtMeasurementContext(
            base_a,
            top_a,
            crossing,
            crossing.t_pct_a_s is None or crossing.t_pct_b_s is None,
            base_window,
            top_window,
            search_window,
        )

    if raw is None:
        crossing = DidtCrossingResult(0.0, None, None, th_a, th_b)
        return DidtMeasurementContext(
            base_a,
            top_a,
            crossing,
            True,
            base_window,
            top_window,
            search_window,
        )
    crossing = DidtCrossingResult(
        float(raw.dvdt),
        raw.t_pct_a_s,
        raw.t_pct_b_s,
        float(raw.th_a),
        float(raw.th_b),
    )
    return DidtMeasurementContext(
        base_a,
        top_a,
        crossing,
        False,
        base_window,
        top_window,
        search_window,
    )


def dvdt_vce_rise(
    t: np.ndarray,
    vce: np.ndarray,
    vdc: float,
    i0: int,
    i1: int,
    pct_lo: float,
    pct_hi: float,
    vce_top: float | None = None,
    search_from_vce_min: bool = True,
) -> float:
    """Vce 上升 dv/dt；vce_top 为 100% Vce 时阈值 = pct × Top（规格书），否则回退分位插值。"""
    if vce_top is not None and vce_top > 1.0:
        th_lo = pct_lo * vce_top
        th_hi = pct_hi * vce_top
    else:
        v_hi = float(np.max(vce[i0:i1]))
        v_lo = vdc
        th_lo = threshold_value(v_lo, v_hi, pct_lo)
        th_hi = threshold_value(v_lo, v_hi, pct_hi)
    seg_t = t[i0:i1]
    seg_y = vce[i0:i1].astype(np.float64)
    if len(seg_t) < 2:
        return 0.0
    start = max(0, int(np.argmin(seg_y)) - 1) if search_from_vce_min else 0
    t_a = crossing_time(seg_t, seg_y, th_lo, "rising", start=start)
    if t_a is None:
        t_a = crossing_time(seg_t, seg_y, th_lo, "rising", start=0)
    if t_a is None:
        return 0.0
    local = int(np.searchsorted(seg_t, t_a, side="left"))
    local = max(0, min(local, len(seg_t) - 2))
    t_b = crossing_time(seg_t, seg_y, th_hi, "rising", start=local)
    if t_b is None or t_b <= t_a:
        return 0.0
    dt_s = t_b - t_a
    if abs(dt_s) < 1e-15:
        return 0.0
    return abs(th_hi - th_lo) / abs(dt_s) / 1e9


def dvdt_vce_fall(
    t: np.ndarray,
    vce: np.ndarray,
    vdc: float,
    i0: int,
    i1: int,
    pct_hi: float,
    pct_lo: float,
    vce_top: float | None = None,
    search_from_vce_max: bool = True,
) -> float:
    if vce_top is not None and vce_top > 1.0:
        th_hi = pct_hi * vce_top
        th_lo = pct_lo * vce_top
    else:
        v_hi = float(np.max(vce[i0:i1]))
        v_lo = vdc
        th_hi = threshold_value(v_lo, v_hi, pct_hi)
        th_lo = threshold_value(v_lo, v_hi, pct_lo)
    seg_t = t[i0:i1]
    seg_y = vce[i0:i1].astype(np.float64)
    if len(seg_t) < 2:
        return 0.0
    start = max(0, int(np.argmax(seg_y)) - 1) if search_from_vce_max else 0
    t_a = crossing_time(seg_t, seg_y, th_hi, "falling", start=start)
    if t_a is None:
        t_a = crossing_time(seg_t, seg_y, th_hi, "falling", start=0)
    if t_a is None:
        return 0.0
    local = int(np.searchsorted(seg_t, t_a, side="left"))
    local = max(0, min(local, len(seg_t) - 2))
    t_b = crossing_time(seg_t, seg_y, th_lo, "falling", start=local)
    if t_b is None or t_b <= t_a:
        return 0.0
    dt_s = t_b - t_a
    if abs(dt_s) < 1e-15:
        return 0.0
    return abs(th_hi - th_lo) / abs(dt_s) / 1e9


def didt_ic_fall(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    pct_hi: float,
    pct_lo: float,
    ic_reference: str = "plateau",
    icm_override: float | None = None,
    search_from_peak: bool = True,
) -> float:
    """电流下降段 di/dt (A/ns)；关断时 icm_override 为 Vge 下降窗内 Ic 峰值。"""
    if icm_override is not None and icm_override > 0:
        icm = float(icm_override)
    else:
        icm = _ic_amplitude(ic, i0, i1, ic_reference)
    th_hi = pct_hi * icm
    th_lo = pct_lo * icm
    seg_t = t[i0:i1]
    seg_y = np.abs(ic[i0:i1]).astype(np.float64)
    if len(seg_t) < 2:
        return 0.0
    start = 0
    if search_from_peak:
        start = max(0, int(np.argmax(seg_y)) - 1)
    t_a = crossing_time(seg_t, seg_y, th_hi, "falling", start=start)
    if t_a is None:
        t_a = crossing_time(seg_t, seg_y, th_hi, "falling", start=0)
    if t_a is None:
        return 0.0
    local = int(np.searchsorted(seg_t, t_a, side="left"))
    local = max(0, min(local, len(seg_t) - 2))
    t_b = crossing_time(seg_t, seg_y, th_lo, "falling", start=local)
    if t_b is None or t_b <= t_a:
        return 0.0
    dt_s = t_b - t_a
    if abs(dt_s) < 1e-15:
        return 0.0
    return abs(th_hi - th_lo) / abs(dt_s) / 1e9


def _ic_amplitude(ic: np.ndarray, i0: int, i1: int, ic_reference: str) -> float:
    seg = np.abs(ic[i0:i1])
    if len(seg) == 0:
        return 1.0
    if ic_reference == "peak":
        return float(np.max(seg))
    return float(np.percentile(seg, 95))


def didt_ic_rise(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    pct_lo: float,
    pct_hi: float,
    ic_reference: str = "plateau",
    icm_override: float | None = None,
    search_from_peak: bool = True,
) -> float:
    """电流上升段 di/dt (A/ns)；开通时 icm_override 为 Vge 上升窗内 Icm。"""
    if icm_override is not None and icm_override > 0:
        icm = float(icm_override)
    else:
        icm = _ic_amplitude(ic, i0, i1, ic_reference)
    seg_t = t[i0:i1]
    seg_y = np.abs(ic[i0:i1]).astype(np.float64)
    if len(seg_t) < 2:
        return 0.0
    start = 0
    if search_from_peak:
        start = max(0, int(np.argmin(seg_y)) - 1)
    if float(pct_lo) > float(pct_hi):
        th_lo = float(pct_hi) * icm
        th_hi = float(pct_lo) * icm
        t_lo = crossing_time(seg_t, seg_y, th_lo, "rising", start=start)
        if t_lo is None:
            t_lo = crossing_time(seg_t, seg_y, th_lo, "rising", start=0)
        if t_lo is None:
            return 0.0
        local = int(np.searchsorted(seg_t, t_lo, side="left"))
        local = max(0, min(local, len(seg_t) - 2))
        t_hi = crossing_time(seg_t, seg_y, th_hi, "rising", start=local)
        if t_hi is None or t_hi <= t_lo:
            return 0.0
        dt_s = t_hi - t_lo
    else:
        th_lo = pct_lo * icm
        th_hi = pct_hi * icm
        t_a = crossing_time(seg_t, seg_y, th_lo, "rising", start=start)
        if t_a is None:
            t_a = crossing_time(seg_t, seg_y, th_lo, "rising", start=0)
        if t_a is None:
            return 0.0
        local = int(np.searchsorted(seg_t, t_a, side="left"))
        local = max(0, min(local, len(seg_t) - 2))
        t_b = crossing_time(seg_t, seg_y, th_hi, "rising", start=local)
        if t_b is None or t_b <= t_a:
            return 0.0
        dt_s = t_b - t_a
    if abs(dt_s) < 1e-15:
        return 0.0
    return abs(th_hi - th_lo) / abs(dt_s) / 1e9


def dvdt_max(
    t: np.ndarray,
    y: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    cfg: AppConfig,
) -> float:
    s = max_slope_filtered(y[i0:i1], dt, cfg.smoothing.slope_window_ns, cfg.slopes.ma_points)
    return s / 1e9


def didt_max(
    t: np.ndarray,
    y: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    cfg: AppConfig,
) -> float:
    s = max_slope_filtered(y[i0:i1], dt, cfg.smoothing.slope_window_ns, cfg.slopes.ma_points)
    return s / 1e9


def analyze_rr_recovery_current(seg_i: np.ndarray) -> tuple[float, float, int]:
    """
    从 Irr 段解析 IDM（换流前正向峰值）、IRM（反向峰值，≤0）与零交叉局部下标。
    IDM 取首个正向区间内的峰值；零交叉取该峰值之后首次由正到非正的过渡。
    """
    seg_i = seg_i.astype(np.float64)
    if len(seg_i) < 4:
        return 0.0, 0.0, 0
    pos = np.where(seg_i > 0.0)[0]
    if len(pos) == 0:
        i_idm = int(np.argmax(seg_i))
        idm = float(seg_i[i_idm])
        zc = i_idm
    else:
        i_fwd0 = int(pos[0])
        fwd = seg_i[i_fwd0:]
        i_idm = i_fwd0 + int(np.argmax(fwd))
        idm = float(seg_i[i_idm])
        zc = i_idm
        for k in range(i_idm + 1, len(seg_i)):
            if seg_i[k - 1] > 0.0 and seg_i[k] <= 0.0:
                zc = k
                break
    tail = seg_i[zc:]
    if len(tail) == 0:
        irm = 0.0
    else:
        irm = float(np.min(tail))
        if irm > 0:
            irm = -irm
    return idm, irm, zc


_RR_MAX_REPAIR_RUN_SAMPLES = 3


def _rr_longest_invalid_run(values: np.ndarray) -> int:
    """Return the longest consecutive NaN/Inf run in a one-dimensional trace."""
    invalid = ~np.isfinite(np.asarray(values, dtype=np.float64))
    indices = np.flatnonzero(invalid)
    if len(indices) == 0:
        return 0
    boundaries = np.flatnonzero(np.diff(indices) > 1)
    starts = np.r_[0, boundaries + 1]
    stops = np.r_[boundaries + 1, len(indices)]
    return int(np.max(stops - starts))


def _rr_invalid_run_exceeds_repair_limit(values: np.ndarray) -> bool:
    """Only isolated/small invalid clusters may be linearly repaired."""
    return _rr_longest_invalid_run(values) > _RR_MAX_REPAIR_RUN_SAMPLES


def _rr_repair_finite_signal(values: np.ndarray) -> np.ndarray:
    """Interpolate isolated invalid current samples without changing valid data."""
    arr = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(arr)
    if np.all(finite):
        return arr
    if not np.any(finite):
        return np.zeros_like(arr, dtype=np.float64)
    sample_index = np.arange(len(arr), dtype=np.float64)
    return np.interp(sample_index, sample_index[finite], arr[finite])


def _rr_repair_time_axis(values: np.ndarray) -> np.ndarray | None:
    """Repair isolated NaN/Inf timestamps and reject a non-monotonic axis."""
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 2:
        return None
    if _rr_invalid_run_exceeds_repair_limit(arr):
        return None
    finite = np.isfinite(arr)
    if np.all(finite):
        return arr if np.all(np.diff(arr) > 0.0) else None
    finite_index = np.flatnonzero(finite)
    if len(finite_index) < 2:
        return None
    finite_values = arr[finite]
    per_sample_steps = np.diff(finite_values) / np.diff(finite_index)
    positive_steps = per_sample_steps[
        np.isfinite(per_sample_steps) & (per_sample_steps > 0.0)
    ]
    if len(positive_steps) == 0:
        return None
    step = float(np.median(positive_steps))
    sample_index = np.arange(len(arr), dtype=np.float64)
    repaired = np.interp(sample_index, finite_index, finite_values)
    first = int(finite_index[0])
    last = int(finite_index[-1])
    if first > 0:
        repaired[:first] = finite_values[0] - step * np.arange(
            first, 0, -1, dtype=np.float64
        )
    if last + 1 < len(repaired):
        repaired[last + 1 :] = finite_values[-1] + step * np.arange(
            1, len(repaired) - last, dtype=np.float64
        )
    return repaired if np.all(np.diff(repaired) > 0.0) else None


def _rr_spike_guarded_extreme_index(
    values: np.ndarray,
    *,
    maximum: bool,
) -> int:
    """Return a raw extreme unless it is only a one-point/small-cluster spike.

    A short median reference is used only as an outlier audit.  Genuine raw
    extrema are retained verbatim, preserving the established stable-band
    ``(max + min) / 2`` values and the physical IRM peak.  When an extreme is
    unsupported by its neighbours, the corresponding median-filtered extreme
    supplies the replacement index.
    """
    arr = _rr_repair_finite_signal(values)
    if len(arr) == 0:
        return 0
    kernel = min(11, len(arr) if len(arr) % 2 else len(arr) - 1)
    if kernel < 3:
        return int(np.argmax(arr) if maximum else np.argmin(arr))
    filtered = median_filter(arr, size=kernel, mode="nearest")
    raw_idx = int(np.argmax(arr) if maximum else np.argmin(arr))
    p01, p99 = (float(np.percentile(arr, p)) for p in (1.0, 99.0))
    raw_span = float(np.max(arr) - np.min(arr))
    # A genuine ringing band normally has supported excursions on both sides,
    # so a raw extreme can sit roughly half a full band away from its local
    # median.  A one-sided acquisition spike is nearly the entire raw span away
    # and still fails this guard.  The robust-span term protects broad/noisy
    # physical lobes whose 1%/99% band already carries the excursion.
    tolerance = max(
        1e-9,
        0.15 * max(0.0, p99 - p01),
        0.55 * max(0.0, raw_span),
    )
    if abs(float(arr[raw_idx]) - float(filtered[raw_idx])) <= tolerance:
        return raw_idx
    return int(np.argmax(filtered) if maximum else np.argmin(filtered))


def _rr_spike_guarded_band_center(values: np.ndarray) -> float:
    """Stable-band max/min midpoint with isolated-extreme rejection."""
    arr = _rr_repair_finite_signal(values)
    if len(arr) == 0:
        return 0.0
    i_min = _rr_spike_guarded_extreme_index(arr, maximum=False)
    i_max = _rr_spike_guarded_extreme_index(arr, maximum=True)
    return 0.5 * (float(arr[i_min]) + float(arr[i_max]))


def _rr_quiet_local_platform_window(
    values: np.ndarray,
    dt: float,
    *,
    min_ns: float = 200.0,
) -> np.ndarray:
    """Return the same quiet RR platform window used for its cursor level.

    Window selection remains robust (P5/P95 spread, tail proximity and local
    slope), but the returned raw band lets the final level use the user's
    oscilloscope rule: spike-guarded ``(max + min) / 2``.
    """

    vals = _rr_repair_finite_signal(values)
    if len(vals) < 8:
        return vals
    win_n = max(
        16,
        int(round(float(min_ns) * 1e-9 / max(float(dt), 1e-15))),
    )
    if len(vals) <= win_n:
        return vals

    def _robust_center(block: np.ndarray) -> float:
        p05, p95 = (float(np.percentile(block, p)) for p in (5.0, 95.0))
        return 0.5 * (p05 + p95)

    step = max(1, win_n // 8)
    starts = list(range(0, len(vals) - win_n + 1, step))
    if starts[-1] != len(vals) - win_n:
        starts.append(len(vals) - win_n)
    tail_ref = _robust_center(vals[-win_n:])
    best_start = starts[0]
    best_score = float("inf")
    for start in starts:
        block = vals[start : start + win_n]
        p05, p50, p95 = (
            float(np.percentile(block, p)) for p in (5.0, 50.0, 95.0)
        )
        center = 0.5 * (p05 + p95)
        score = (
            (p95 - p05)
            + 0.15 * abs(center - tail_ref)
            + 0.05 * abs(float(block[-1]) - float(block[0]))
            + 0.02 * abs(p50 - center)
        )
        if score < best_score:
            best_score = score
            best_start = start
    return vals[best_start : best_start + win_n]


def _rr_quiet_local_platform_band_center(
    values: np.ndarray,
    dt: float,
    *,
    min_ns: float = 200.0,
) -> float:
    """Spike-guarded raw max/min midpoint of the selected quiet RR band."""

    return _rr_spike_guarded_band_center(
        _rr_quiet_local_platform_window(values, dt, min_ns=min_ns)
    )


def _rr_prepeak_forward_platform_band_center(
    values: np.ndarray,
    dt: float,
    *,
    min_ns: float = 200.0,
) -> float:
    """Return the forward-platform centre without shrinking a clean source band.

    The pre-peak source region is intentionally wider than the nominal quiet
    platform so it remains compatible with different sample rates and edge
    positions.  A clean broad region keeps its spike-guarded raw max/min
    midpoint.  Only when the broad region has both a much larger robust spread
    and a materially displaced midpoint do we treat it as edge-contaminated
    and use the quiet sub-band.  Requiring both signals avoids moving an
    already-correct stable cursor merely because a shorter window has slightly
    different noise extrema.
    """

    source = _rr_repair_finite_signal(values)
    if len(source) == 0:
        return 0.0
    broad_center = _rr_spike_guarded_band_center(source)
    quiet = _rr_quiet_local_platform_window(source, dt, min_ns=min_ns)
    if len(quiet) < 2 or len(quiet) >= len(source):
        return float(broad_center)

    quiet_center = _rr_spike_guarded_band_center(quiet)
    broad_p05, broad_p95 = (
        float(np.percentile(source, p)) for p in (5.0, 95.0)
    )
    quiet_p05, quiet_p95 = (
        float(np.percentile(quiet, p)) for p in (5.0, 95.0)
    )
    broad_spread = max(0.0, broad_p95 - broad_p05)
    quiet_spread = max(0.0, quiet_p95 - quiet_p05)
    # A tiny scale-relative floor prevents a numerically flat clean band from
    # turning harmless quantisation into a contamination decision.
    quiet_reference = max(
        1e-9,
        quiet_spread,
        0.002 * max(abs(float(quiet_center)), 1.0),
    )
    contaminated = (
        broad_spread > 2.0 * quiet_reference
        and abs(float(broad_center) - float(quiet_center))
        > 1.5 * quiet_reference
    )
    return float(quiet_center if contaminated else broad_center)


def prepare_rr_didt_series(
    t: np.ndarray,
    i_d: np.ndarray,
    i0: int,
    i1: int,
) -> RrDidtPreparedSeries:
    """Prepare an exact RR cursor-search segment once.

    Invalid time axes and current gaps longer than the established repair
    limit fail closed exactly like :func:`rr_didt_between_levels`.  The two
    cached orientations are mathematical mirrors of the same repaired raw
    samples; no smoothing or decimation is introduced.
    """

    t_arr = np.asarray(t, dtype=np.float64)
    i_arr = np.asarray(i_d, dtype=np.float64)
    n = min(len(t_arr), len(i_arr))
    empty = np.asarray([], dtype=np.float64)
    empty.setflags(write=False)
    if n < 2:
        return RrDidtPreparedSeries(empty, empty, empty, 0, 0, 0.0, 0.0)

    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 1, min(int(i1), n - 1))
    raw_i = i_arr[i0 : i1 + 1]
    repaired_t = _rr_repair_time_axis(t_arr[i0 : i1 + 1])
    if repaired_t is None or _rr_invalid_run_exceeds_repair_limit(raw_i):
        return RrDidtPreparedSeries(empty, empty, empty, 0, 0, 0.0, 0.0)

    # ``frozen=True`` protects only the dataclass fields, not NumPy storage.
    # Own the prepared samples so an input-array edit cannot change crossings
    # halfway through one cursor session, then expose all three arrays read-only.
    prepared_t = np.array(repaired_t, dtype=np.float64, copy=True)
    positive = np.array(
        _rr_repair_finite_signal(raw_i),
        dtype=np.float64,
        copy=True,
    )
    negative = -positive
    start_positive = max(
        0,
        _rr_spike_guarded_extreme_index(positive, maximum=True) - 1,
    )
    # Applying the same maximum audit to -I is exactly equivalent to the
    # negative-polarity normalization used by the uncached implementation.
    start_negative = max(
        0,
        _rr_spike_guarded_extreme_index(negative, maximum=True) - 1,
    )
    for prepared_values in (prepared_t, positive, negative):
        prepared_values.setflags(write=False)
    return RrDidtPreparedSeries(
        prepared_t,
        positive,
        negative,
        int(start_positive),
        int(start_negative),
        float(np.min(positive)) if len(positive) else 0.0,
        float(np.min(negative)) if len(negative) else 0.0,
    )


def _rr_default_signed_levels(
    seg_i: np.ndarray,
    dt: float,
) -> tuple[float, float, float, float, int]:
    """Return forward/base/reverse/zero levels and the physical polarity.

    The current stored in a TSS remains signed.  Some upper-bridge recordings
    therefore contain the large forward-diode platform on the negative side,
    followed by a smaller positive recovery peak.  Extrema order identifies
    that physical orientation without globally inverting Irr or affecting
    Irr/Trr/Err and total-current synthesis.
    """
    seg = _rr_repair_finite_signal(seg_i)
    if len(seg) < 4:
        return 0.0, 0.0, 0.0, 0.0, 1

    i_pos = _rr_spike_guarded_extreme_index(seg, maximum=True)
    i_neg = _rr_spike_guarded_extreme_index(seg, maximum=False)
    polarity = 1 if i_pos < i_neg else -1
    i_forward = i_pos if polarity > 0 else i_neg
    i_reverse = i_neg if polarity > 0 else i_pos

    # Keep an extrema-local fallback, then refine it from the approximately
    # 200 ns quiet band before the preliminary 90% commutation crossing.  The
    # refinement uses the visible stable-band centre, not a single peak.
    span = max(8, abs(i_reverse - i_forward))
    plateau_w = max(12, int(0.35 * span))
    p0 = max(0, i_forward - plateau_w // 6)
    p1 = min(len(seg), i_forward + plateau_w)
    plateau = seg[p0:p1]
    if len(plateau) < 3:
        forward = float(seg[i_forward])
    else:
        logical = float(polarity) * plateau
        high_cut = float(np.percentile(logical, 90.0))
        stable_high = plateau[logical >= high_cut]
        forward = (
            float(np.median(stable_high))
            if len(stable_high) >= 3
            else float(seg[i_forward])
        )
    forward_initial = float(forward)

    # The IDM base is the signed centre of the quiet recovery tail.  The
    # 50%IF→50%IRM H0 keeps the established late-tail median semantics.
    tail0 = i_reverse + max(8, int(0.30 * (len(seg) - i_reverse)))
    tail = seg[tail0:]
    if len(tail) < 8:
        tail = seg[i_reverse:]
    base = (
        float(_rr_quiet_local_platform_band_center(tail, float(dt), min_ns=200.0))
        if len(tail)
        else 0.0
    )

    normalized = float(polarity) * (seg - base)
    preliminary_peak = float(np.max(normalized[: i_reverse + 1]))
    preliminary_90 = 0.90 * preliminary_peak
    preliminary_crossings = np.flatnonzero(
        (normalized[:-1] >= preliminary_90)
        & (normalized[1:] < preliminary_90)
    )
    pre_end: int | None = None
    for candidate in preliminary_crossings:
        if int(candidate) >= i_forward:
            pre_end = int(candidate) + 1
            break
    if pre_end is not None and pre_end >= 8:
        candidate = float(
            _rr_quiet_local_platform_band_center(
                seg[:pre_end], float(dt), min_ns=200.0
            )
        )
        initial_mag = float(polarity) * (forward_initial - base)
        candidate_mag = float(polarity) * (candidate - base)
        # A quiet-window estimator may lock onto the recovery-tail noise on a
        # short/positive-polarity record.  Only accept it when it preserves the
        # extrema-local forward-platform magnitude.  This also protects the
        # real wanglihui CH3 display-inversion workflow.
        if (
            initial_mag > 1e-6
            and candidate_mag > 1e-6
            and candidate_mag >= 0.50 * initial_mag
            and candidate_mag <= 1.50 * initial_mag
        ):
            forward = candidate

    zero_tail = seg[i_reverse + 1 :]
    if len(zero_tail) < 8:
        zero_tail = tail
    skip = max(8, int(0.10 * len(zero_tail)))
    rest = zero_tail[skip:] if len(zero_tail) > skip + 8 else zero_tail
    zero_n = max(8, int(0.22 * len(rest)))
    settled = rest[-zero_n:] if len(rest) >= zero_n else rest
    zero = float(np.median(settled)) if len(settled) else float(base)
    reverse = float(seg[i_reverse])
    return forward, float(base), reverse, zero, polarity


def _rr_idm_crossings_from_prepared(
    prepared: RrDidtPreparedSeries,
    forward_a: float,
    base_a: float,
    pct_a: float,
    pct_b: float,
) -> DidtCrossingResult:
    """Measure the main forward-current commutation from prepared raw data."""

    polarity = 1 if float(forward_a) >= float(base_a) else -1
    oriented = prepared.positive_a if polarity > 0 else prepared.negative_a
    oriented_base = float(polarity) * float(base_a)
    forward_mag = float(polarity) * (float(forward_a) - float(base_a))
    th_a_l = float(pct_a) * forward_mag
    th_b_l = float(pct_b) * forward_mag
    th_a = float(base_a) + float(polarity) * th_a_l
    th_b = float(base_a) + float(polarity) * th_b_l
    oriented_min = (
        prepared.min_positive_a if polarity > 0 else prepared.min_negative_a
    )
    # An invalid prepared series has no observed reverse-current sample.  Its
    # placeholder minimum is zero, so subtracting a non-zero Base here would
    # fabricate an IRM diagnostic (for example ``-Base``) even though the
    # measurement correctly fails closed.  Preserve the established invalid
    # result semantics: no crossings, zero slope and zero observed IRM.
    irm = 0.0 if not prepared.valid else float(oriented_min - oriented_base)
    if (
        not prepared.valid
        or forward_mag <= 1e-9
        or abs(th_a_l - th_b_l) <= 1e-12
    ):
        return DidtCrossingResult(
            0.0, None, None, th_a, th_b, idm=forward_mag, irm=irm
        )

    th_high = max(th_a_l, th_b_l)
    th_low = min(th_a_l, th_b_l)
    th_high_oriented = oriented_base + th_high
    th_low_oriented = oriented_base + th_low
    start = (
        prepared.start_positive if polarity > 0 else prepared.start_negative
    )
    seg_t = prepared.t_s
    dt_s = float(np.median(np.diff(seg_t))) if len(seg_t) > 1 else 0.0
    hold = max(3, int(round(5e-9 / max(dt_s, 1e-15))))
    hold = min(64, hold)
    rebound_hold = max(3, int(round(2e-9 / max(dt_s, 1e-15))))
    rebound_hold = min(64, rebound_hold)
    tolerance = 0.01 * max(forward_mag, 1.0)

    high_idx: int | None = None
    low_idx: int | None = None
    high_candidates = np.flatnonzero(
        (oriented[:-1] >= th_high_oriented)
        & (oriented[1:] < th_high_oriented)
    )
    low_candidates = np.flatnonzero(
        (oriented[:-1] >= th_low_oriented)
        & (oriented[1:] < th_low_oriented)
    )
    for high_candidate in high_candidates:
        h = int(high_candidate)
        if h < start:
            continue
        for low_candidate in low_candidates:
            k = int(low_candidate)
            if k <= h:
                continue
            tail = oriented[k + 1 : min(len(oriented), k + 1 + hold)]
            if (
                len(tail) < 3
                or float(np.mean(tail <= th_low_oriented + tolerance)) < 0.70
            ):
                continue

            # A short downward platform glitch may cross 90% without reaching
            # 10%, recover to the forward platform, and otherwise steal cursor
            # A from the later physical commutation edge.  Reject that high
            # candidate only when the signal has a sustained rebound clearly
            # above the high threshold before the paired low crossing.  Brief
            # near-threshold ringing remains attached to the first physical
            # crossing, preserving the established cursor interpolation.
            rebound_run = 0
            sustained_rebound = False
            for value in oriented[h + 1 : k + 1]:
                if float(value) > th_high_oriented + tolerance:
                    rebound_run += 1
                    if rebound_run >= rebound_hold:
                        sustained_rebound = True
                        break
                else:
                    rebound_run = 0
            if sustained_rebound:
                continue
            high_idx = h
            low_idx = k
            break
        if high_idx is not None:
            break
    if high_idx is None or low_idx is None:
        return DidtCrossingResult(
            0.0, None, None, th_a, th_b, idm=forward_mag, irm=irm
        )

    def _interp(k: int, threshold: float) -> float:
        y0 = float(oriented[k] - oriented_base)
        y1 = float(oriented[k + 1] - oriented_base)
        frac = (threshold - y0) / (y1 - y0) if abs(y1 - y0) > 1e-30 else 0.0
        return float(seg_t[k] + frac * (seg_t[k + 1] - seg_t[k]))

    t_high = _interp(high_idx, th_high)
    t_low = _interp(low_idx, th_low)
    if t_low <= t_high:
        return DidtCrossingResult(
            0.0, None, None, th_a, th_b, idm=forward_mag, irm=irm
        )
    t_a = t_high if th_a_l == th_high else t_low
    t_b = t_high if th_b_l == th_high else t_low
    didt = abs(th_a_l - th_b_l) / (t_low - t_high) / 1e9
    return DidtCrossingResult(
        float(didt), float(t_a), float(t_b), th_a, th_b, idm=forward_mag, irm=irm
    )


def _rr_idm_crossings_from_levels(
    seg_t: np.ndarray,
    seg_i: np.ndarray,
    forward_a: float,
    base_a: float,
    pct_a: float,
    pct_b: float,
) -> DidtCrossingResult:
    prepared = prepare_rr_didt_series(seg_t, seg_i, 0, max(1, len(seg_t) - 1))
    return _rr_idm_crossings_from_prepared(
        prepared,
        forward_a,
        base_a,
        pct_a,
        pct_b,
    )


def _rr_if_irm_crossings_from_prepared(
    prepared: RrDidtPreparedSeries,
    forward_a: float,
    reverse_a: float,
    zero_a: float,
    pct_a: float,
    pct_b: float,
) -> DidtCrossingResult:
    """Measure IF to IRM on the same normalized physical commutation edge."""
    polarity = 1 if float(forward_a) >= float(zero_a) else -1
    oriented = prepared.positive_a if polarity > 0 else prepared.negative_a
    oriented_zero = float(polarity) * float(zero_a)
    if_level = float(polarity) * (float(forward_a) - float(zero_a))
    irm_level = float(polarity) * (float(reverse_a) - float(zero_a))
    th_if_l = float(pct_a) * if_level
    th_irm_l = float(pct_b) * irm_level
    th_if = float(zero_a) + float(polarity) * th_if_l
    th_irm = float(zero_a) + float(polarity) * th_irm_l
    if (
        not prepared.valid
        or if_level <= 1e-9
        or irm_level >= -1e-9
        or abs(th_if_l - th_irm_l) <= 1e-12
    ):
        return DidtCrossingResult(
            0.0, None, None, th_if, th_irm, idm=if_level, irm=irm_level
        )

    start = (
        prepared.start_positive if polarity > 0 else prepared.start_negative
    )
    seg_t = prepared.t_s
    t_if = crossing_time(
        seg_t,
        oriented,
        oriented_zero + th_if_l,
        "falling",
        start=start,
    )
    if t_if is None:
        return DidtCrossingResult(
            0.0, None, None, th_if, th_irm, idm=if_level, irm=irm_level
        )
    local = int(np.searchsorted(seg_t, t_if, side="left"))
    local = max(start, min(local, len(seg_t) - 2))
    t_irm = crossing_time(
        seg_t,
        oriented,
        oriented_zero + th_irm_l,
        "falling",
        start=local,
    )
    if t_irm is None or t_irm <= t_if:
        return DidtCrossingResult(
            0.0, t_if, None, th_if, th_irm, idm=if_level, irm=irm_level
        )
    didt = abs(th_if_l - th_irm_l) / (t_irm - t_if) / 1e9
    return DidtCrossingResult(
        float(didt), float(t_if), float(t_irm), th_if, th_irm,
        idm=if_level, irm=irm_level,
    )


def _rr_if_irm_crossings_from_levels(
    seg_t: np.ndarray,
    seg_i: np.ndarray,
    forward_a: float,
    reverse_a: float,
    zero_a: float,
    pct_a: float,
    pct_b: float,
) -> DidtCrossingResult:
    prepared = prepare_rr_didt_series(seg_t, seg_i, 0, max(1, len(seg_t) - 1))
    return _rr_if_irm_crossings_from_prepared(
        prepared,
        forward_a,
        reverse_a,
        zero_a,
        pct_a,
        pct_b,
    )


def rr_didt_between_prepared_levels(
    prepared: RrDidtPreparedSeries,
    pct_a: float,
    pct_b: float,
    *,
    measure: str,
    forward_a: float,
    base_or_reverse_a: float,
    zero_a: float | None = None,
) -> DidtCrossingResult:
    """Recalculate exact RR crossings from a prepared cursor-search segment."""

    forward = float(forward_a) if np.isfinite(forward_a) else 0.0
    other = (
        float(base_or_reverse_a) if np.isfinite(base_or_reverse_a) else 0.0
    )
    zero_value = (
        float(zero_a) if zero_a is not None and np.isfinite(zero_a) else 0.0
    )
    if measure == "if_irm":
        return _rr_if_irm_crossings_from_prepared(
            prepared,
            forward,
            other,
            zero_value,
            pct_a,
            pct_b,
        )
    return _rr_idm_crossings_from_prepared(
        prepared,
        forward,
        other,
        pct_a,
        pct_b,
    )


def auto_rr_didt_between_prepared_levels(
    prepared: RrDidtPreparedSeries,
    *,
    forward_a: float,
    base_a: float,
) -> DidtCrossingResult:
    """Select the maximum valid interval on the signed IDM commutation edge."""

    forward = float(forward_a) if np.isfinite(forward_a) else 0.0
    base = float(base_a) if np.isfinite(base_a) else 0.0
    polarity = 1 if forward >= base else -1
    oriented = prepared.positive_a if polarity > 0 else prepared.negative_a
    oriented_base = float(polarity) * base
    oriented_top = float(polarity) * forward
    anchor: DidtCrossingResult | None = None
    for high_pct, low_pct in (
        (0.98, 0.02),
        (0.95, 0.05),
        (0.90, 0.10),
        (0.80, 0.20),
    ):
        candidate = _rr_idm_crossings_from_prepared(
            prepared,
            forward,
            base,
            high_pct,
            low_pct,
        )
        if candidate.t_pct_a_s is not None and candidate.t_pct_b_s is not None:
            anchor = candidate
            break
    if anchor is None:
        return DidtCrossingResult(0.0, None, None, forward, base)
    percentages = _auto_max_slope_percentages(
        prepared.t_s,
        oriented,
        oriented_base,
        oriented_top,
        "fall",
        anchor,
    )
    if percentages is None:
        return DidtCrossingResult(
            0.0,
            None,
            None,
            anchor.th_a,
            anchor.th_b,
            anchor.idm,
            anchor.irm,
        )
    pct_a, pct_b, _selected_t0, _selected_t1 = percentages
    result = _rr_idm_crossings_from_prepared(
        prepared,
        forward,
        base,
        pct_a,
        pct_b,
    )
    if result.t_pct_a_s is None or result.t_pct_b_s is None:
        return result
    return replace(
        result,
        resolved_pct_a=pct_a,
        resolved_pct_b=pct_b,
    )


def auto_rr_didt_between_levels(
    t: np.ndarray,
    i_d: np.ndarray,
    i0: int,
    i1: int,
    *,
    forward_a: float,
    base_a: float,
) -> DidtCrossingResult:
    prepared = prepare_rr_didt_series(t, i_d, i0, i1)
    return auto_rr_didt_between_prepared_levels(
        prepared,
        forward_a=forward_a,
        base_a=base_a,
    )


def rr_didt_between_levels(
    t: np.ndarray,
    i_d: np.ndarray,
    i0: int,
    i1: int,
    pct_a: float,
    pct_b: float,
    *,
    measure: str,
    forward_a: float,
    base_or_reverse_a: float,
    zero_a: float | None = None,
) -> DidtCrossingResult:
    """Recalculate RR di/dt from the currently displayed signed levels."""

    prepared = prepare_rr_didt_series(t, i_d, i0, i1)
    return rr_didt_between_prepared_levels(
        prepared,
        pct_a,
        pct_b,
        measure=measure,
        forward_a=forward_a,
        base_or_reverse_a=base_or_reverse_a,
        zero_a=zero_a,
    )


def rr_didt_measurement_context(
    t: np.ndarray,
    i_d: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    cfg: AppConfig,
    pct_a: float,
    pct_b: float,
    *,
    measure: str = "idm",
    rr_i0: int | None = None,
    rr_i1: int | None = None,
    fallback_i0: int | None = None,
    fallback_i1: int | None = None,
    auto_max: bool = False,
) -> RrDidtMeasurementContext:
    """Build the one authoritative RR di/dt context for pipeline and GUI."""
    t_arr = np.asarray(t, dtype=np.float64)
    i_arr = np.asarray(i_d, dtype=np.float64)
    n = min(len(t_arr), len(i_arr))
    if n < 2:
        empty_crossing = DidtCrossingResult(0.0, None, None, 0.0, 0.0)
        return RrDidtMeasurementContext(
            0.0, 0.0, 0.0, None, empty_crossing, 1, True
        )
    t_arr = t_arr[:n]
    i_arr = i_arr[:n]
    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 1, min(int(i1), n - 1))
    valid_dt = float(dt) if np.isfinite(dt) and float(dt) > 0.0 else 0.0
    if valid_dt <= 0.0:
        finite_index = np.flatnonzero(np.isfinite(t_arr))
        if len(finite_index) >= 2:
            per_sample_steps = np.diff(t_arr[finite_index]) / np.diff(finite_index)
            positive_steps = per_sample_steps[
                np.isfinite(per_sample_steps) & (per_sample_steps > 0.0)
            ]
            if len(positive_steps):
                valid_dt = float(np.median(positive_steps))
    audit_i0 = i0
    audit_i1 = i1
    for audit_start, audit_end in (
        (rr_i0, rr_i1),
        (fallback_i0, fallback_i1),
    ):
        if audit_start is None or audit_end is None:
            continue
        lo = max(0, min(int(audit_start), n - 1))
        hi = max(lo, min(int(audit_end), n - 1))
        audit_i0 = min(audit_i0, lo)
        audit_i1 = max(audit_i1, hi)
    # The authoritative forward-platform centre is measured as far as 0.6 us
    # before the recovery peak and may begin before the crossing-search i0.
    # Audit that whole source region before any interpolation; otherwise a
    # long missing platform block could still synthesize a plausible IDM and
    # move both the lower horizontal cursor and the final slope.
    platform_margin = (
        int(np.ceil(0.6e-6 / valid_dt)) if valid_dt > 0.0 else n
    )
    audit_i0 = max(0, audit_i0 - platform_margin)
    if _rr_invalid_run_exceeds_repair_limit(i_arr[audit_i0 : audit_i1 + 1]):
        empty_crossing = DidtCrossingResult(0.0, None, None, 0.0, 0.0)
        return RrDidtMeasurementContext(
            0.0, 0.0, 0.0, None, empty_crossing, 1, True
        )
    i_arr = _rr_repair_finite_signal(i_arr)
    repaired_t = _rr_repair_time_axis(t_arr)
    if valid_dt <= 0.0 and repaired_t is not None:
        valid_dt = float(np.median(np.diff(repaired_t)))
    level_dt = valid_dt if valid_dt > 0.0 else 1e-9
    seg_i = i_arr[i0 : i1 + 1]
    forward, base, reverse, zero, polarity = _rr_default_signed_levels(
        seg_i, level_dt
    )
    if repaired_t is not None and rr_i0 is not None and rr_i1 is not None:
        from dpt_extractor.metrics.iec_windows import err_recovery_peak_index

        r0 = max(0, min(int(rr_i0), n - 2))
        r1 = max(r0 + 1, min(int(rr_i1), n - 1))
        rr_seg = i_arr[r0 : r1 + 1]
        if len(rr_seg) >= 4:
            peak_idx = r0 + int(err_recovery_peak_index(rr_seg, level_dt))
            peak_t = float(repaired_t[peak_idx])
            p0 = int(
                np.searchsorted(repaired_t, peak_t - 0.6e-6, side="left")
            )
            p1 = int(
                np.searchsorted(repaired_t, peak_t - 0.2e-6, side="right")
            )
            # The declared platform window is adjacent to the crossing search
            # and may begin before ``rr_slope_window_indices().i0``.  Apply the
            # same signed centre rule for either probe polarity; the magnitude
            # guard below rejects a window that has landed on tail noise.
            p0 = max(0, min(p0, n - 1))
            p1 = max(p0 + 1, min(p1, n))
            platform = i_arr[p0:p1]
            if len(platform) >= 2:
                # ``peak-0.6us .. peak-0.2us`` is only a broad source region.
                # On slow/high-current commutations its right edge can already
                # contain the beginning of the physical current transition.
                # Taking max/min over that whole region can pull the forward
                # platform cursor away from the visible quiet-band centre.
                # Keep the broad raw midpoint when it is demonstrably stable;
                # only a robust-spread and midpoint-displacement pollution gate
                # may switch to the quiet ~200 ns sub-band.
                candidate = _rr_prepeak_forward_platform_band_center(
                    platform,
                    level_dt,
                    min_ns=200.0,
                )
                candidate_mag = float(polarity) * (candidate - base)
                detected_mag = float(polarity) * (forward - base)
                if (
                    candidate_mag > 1e-6
                    and detected_mag > 1e-6
                    and candidate_mag >= 0.50 * detected_mag
                    and candidate_mag <= 1.50 * detected_mag
                ):
                    forward = float(candidate)
    if auto_max:
        crossing = auto_rr_didt_between_levels(
            repaired_t if repaired_t is not None else t_arr,
            i_arr,
            i0,
            i1,
            forward_a=forward,
            base_a=base,
        )
        zero_out = None
    elif measure == "if_irm":
        crossing = rr_didt_between_levels(
            repaired_t if repaired_t is not None else t_arr,
            i_arr,
            i0,
            i1,
            pct_a,
            pct_b,
            measure="if_irm",
            forward_a=forward,
            base_or_reverse_a=reverse,
            zero_a=zero,
        )
        zero_out: float | None = float(zero)
    else:
        crossing = rr_didt_between_levels(
            repaired_t if repaired_t is not None else t_arr,
            i_arr,
            i0,
            i1,
            pct_a,
            pct_b,
            measure="idm",
            forward_a=forward,
            base_or_reverse_a=base,
        )
        zero_out = None

    used_fallback = crossing.didt < 1e-6
    if used_fallback and not auto_max:
        fb0 = i0 if fallback_i0 is None else int(fallback_i0)
        fb1 = i1 if fallback_i1 is None else int(fallback_i1)
        fb0 = max(0, min(fb0, n - 1))
        fb1 = max(fb0 + 1, min(fb1, n - 1))
        fallback = 0.0
        if valid_dt > 0.0 and fb1 - fb0 >= 3:
            fallback = didt_max(
                repaired_t if repaired_t is not None else t_arr,
                i_arr,
                fb0,
                fb1,
                valid_dt,
                cfg,
            )
            if not np.isfinite(fallback):
                fallback = 0.0
        crossing = DidtCrossingResult(
            float(fallback),
            crossing.t_pct_a_s,
            crossing.t_pct_b_s,
            crossing.th_a,
            crossing.th_b,
            crossing.idm,
            crossing.irm,
        )
    return RrDidtMeasurementContext(
        float(forward),
        float(base),
        float(reverse),
        zero_out,
        crossing,
        int(polarity),
        used_fallback,
    )


def _rr_peak_index_near_hb(seg_i: np.ndarray, hb: float, ha: float) -> int:
    """在 Irr 上找最贴近 Hb（base/IRM 尖峰）的局部极值下标。"""
    hb_f, ha_f = float(hb), float(ha)
    i_near = int(np.argmin(np.abs(seg_i - hb_f)))
    win = max(20, len(seg_i) // 20)
    lo = max(0, i_near - win)
    hi = min(len(seg_i), i_near + win + 1)
    chunk = seg_i[lo:hi]
    if len(chunk) == 0:
        return i_near
    if hb_f < ha_f:
        local = int(np.argmin(chunk))
    else:
        local = int(np.argmax(chunk))
    return lo + local


def _rr_idm_peak_index(seg_i: np.ndarray, idm_hint: float) -> int:
    """在 Irr 上找最贴近 IDM 电平的换流前峰值下标。"""
    hint = float(idm_hint)
    i_near = int(np.argmin(np.abs(seg_i - hint)))
    win = max(20, len(seg_i) // 20)
    lo = max(0, i_near - win)
    hi = min(len(seg_i), i_near + win + 1)
    chunk = seg_i[lo:hi]
    if len(chunk) == 0:
        return i_near
    if hint >= 0.0:
        return lo + int(np.argmax(chunk))
    return lo + int(np.argmin(chunk))


def _rr_ha_hb_edge_direction(ha: float, hb: float) -> str:
    """
    判定在 Irr 上搜上升/下降穿越。
    - Hb<Ha：0→IRM 等，走下降沿；
    - Ha≥0 且 Hb>Ha：规格书 0→IDM，IDM 峰值后下降沿；
    - Ha 为大负、Hb 较浅（通道反相时示波器上常见“上升”换流沿）：走上升沿。
    """
    ha_f, hb_f = float(ha), float(hb)
    if hb_f < ha_f:
        return "falling"
    if ha_f < 0.0 and hb_f > ha_f:
        return "rising"
    return "falling"


def _rr_ha_hb_crossings(
    seg_t: np.ndarray,
    seg_i: np.ndarray,
    ha: float,
    hb: float,
    pct_a: float,
    pct_b: float,
) -> tuple[float | None, float | None, float, float]:
    """
    按 Ha/Hb 手调跨度 th=Ha+pct·(Hb−Ha) 在 Irr 上找 A/B 穿越。
    沿方向由 _rr_ha_hb_edge_direction 判定，支持规格书 IDM 下降沿与反相通道上的换流上升沿。
    """
    ha_f, hb_f = float(ha), float(hb)
    th_a = _rr_threshold(ha_f, hb_f, pct_a)
    th_b = _rr_threshold(ha_f, hb_f, pct_b)
    if abs(hb_f - ha_f) <= 1e-9:
        return None, None, th_a, th_b

    th_shallow = max(th_a, th_b)
    th_deep = min(th_a, th_b)
    edge = _rr_ha_hb_edge_direction(ha_f, hb_f)

    if edge == "rising":
        i_v = int(np.argmin(seg_i))
        start = max(0, i_v - 1)
        t_deep = crossing_time(seg_t, seg_i, th_deep, "rising", start=start)
        if t_deep is None:
            return None, None, th_a, th_b
        local = int(np.searchsorted(seg_t, t_deep, side="left"))
        local = max(start, min(local, len(seg_t) - 2))
        t_shallow = crossing_time(seg_t, seg_i, th_shallow, "rising", start=local)
        if t_shallow is None or t_shallow <= t_deep:
            return None, None, th_a, th_b
        t_at_a = t_shallow if th_a == th_shallow else t_deep
        t_at_b = t_deep if th_b == th_deep else t_shallow
        return float(t_at_a), float(t_at_b), th_a, th_b

    if hb_f >= ha_f:
        i_pk = _rr_idm_peak_index(seg_i, hb_f)
        post_t = seg_t[i_pk:]
        post_i = seg_i[i_pk:]
        if len(post_t) < 2:
            return None, None, th_a, th_b
        below = np.where(post_i < ha_f)[0]
        end = int(below[0]) if len(below) else len(post_i)
        sub_t = post_t[:end]
        sub_i = post_i[:end]
        if len(sub_t) < 2:
            sub_t, sub_i = post_t, post_i
        if len(sub_t) < 2:
            return None, None, th_a, th_b
        start = 0
        t_shallow = crossing_time(sub_t, sub_i, th_shallow, "falling", start=start)
        if t_shallow is None:
            t_shallow = crossing_time(post_t, post_i, th_shallow, "falling", start=0)
        if t_shallow is None:
            return None, None, th_a, th_b
        local = int(np.searchsorted(sub_t, t_shallow, side="left"))
        local = max(0, min(local, len(sub_t) - 2))
        t_deep = crossing_time(sub_t, sub_i, th_deep, "falling", start=local)
        if t_deep is None or t_deep <= t_shallow:
            t_deep = crossing_time(post_t, post_i, th_deep, "falling", start=local)
        if t_deep is None or t_deep <= t_shallow:
            return None, None, th_a, th_b
    else:
        i_end = _rr_peak_index_near_hb(seg_i, hb_f, ha_f)
        win_t = seg_t[: i_end + 1]
        win_i = seg_i[: i_end + 1]
        if len(win_t) < 2:
            return None, None, th_a, th_b
        start = max(0, int(np.argmax(win_i)) - 1)
        t_shallow = crossing_time(win_t, win_i, th_shallow, "falling", start=start)
        if t_shallow is None:
            return None, None, th_a, th_b
        local = int(np.searchsorted(win_t, t_shallow, side="left"))
        local = max(start, min(local, len(win_t) - 2))
        t_deep = crossing_time(win_t, win_i, th_deep, "falling", start=local)
        if t_deep is None or t_deep <= t_shallow:
            return None, None, th_a, th_b

    t_at_a = t_shallow if th_a == th_shallow else t_deep
    t_at_b = t_deep if th_b == th_deep else t_shallow
    return float(t_at_a), float(t_at_b), th_a, th_b


def _rr_zero_crossing_index(seg_i: np.ndarray, zero_ref: float) -> int:
    """在 Irr 段内找最贴近 zero_ref 的换流过零点下标。"""
    seg_i = seg_i.astype(np.float64)
    if len(seg_i) < 2:
        return 0
    diff = seg_i - float(zero_ref)
    for k in range(1, len(diff)):
        if diff[k - 1] == 0.0:
            return k - 1
        if diff[k - 1] * diff[k] < 0.0:
            return k
    return int(np.argmin(np.abs(diff)))


def _rr_if_irm_crossings(
    seg_t: np.ndarray,
    seg_i: np.ndarray,
    zero_ref: float,
    if_level: float,
    irm_level: float,
    pct_a: float,
    pct_b: float,
) -> tuple[float | None, float | None, float, float]:
    """
    50%IF→50%IRM：thA = zero + pct_a·(IF−zero)，thB = zero + pct_b·(IRM−zero)。
    在 IF/IRM 峰值之间的换流沿上搜穿越；兼容通道反相（段内先 IRM 后 IF）。
    """
    th_if = _rr_threshold(zero_ref, if_level, pct_a)
    th_irm = _rr_threshold(zero_ref, irm_level, pct_b)
    if len(seg_t) < 4:
        return None, None, th_if, th_irm

    ipk_if = int(np.argmax(seg_i))
    ipk_irm = int(np.argmin(seg_i))
    i_lo = min(ipk_if, ipk_irm)
    i_hi = max(ipk_if, ipk_irm)
    if i_hi - i_lo < 2:
        return None, None, th_if, th_irm

    mid_t = seg_t[i_lo : i_hi + 1]
    mid_i = seg_i[i_lo : i_hi + 1]
    t_if: float | None = None
    t_irm: float | None = None

    # 通道反相常见：段内先 IRM 谷底再沿换流上升沿到 IF —— 50% 两点都在该上升沿上
    if (
        ipk_irm < ipk_if
        and abs(irm_level - zero_ref) > 1e-6
        and abs(if_level - zero_ref) > 1e-6
    ):
        comm_t = seg_t[ipk_irm : ipk_if + 1]
        comm_i = seg_i[ipk_irm : ipk_if + 1]
        if len(comm_t) >= 2:
            t_irm = crossing_time(comm_t, comm_i, th_irm, "rising", start=0)
            start_if = 0
            if t_irm is not None:
                start_if = int(np.searchsorted(comm_t, t_irm, side="left"))
                start_if = max(0, min(start_if, len(comm_t) - 2))
            t_if = crossing_time(comm_t, comm_i, th_if, "rising", start=start_if)
        return t_if, t_irm, th_if, th_irm

    if abs(irm_level - zero_ref) > 1e-6:
        if ipk_irm <= ipk_if:
            t_irm = crossing_time(mid_t, mid_i, th_irm, "rising", start=0)
            if t_irm is None:
                t_irm = crossing_time(mid_t, mid_i, th_irm, "falling", start=0)
        else:
            zc_rel = _rr_zero_crossing_index(mid_i, zero_ref)
            zc = int(zc_rel)
            search_t = mid_t[zc:]
            search_i = mid_i[zc:]
            if len(search_t) >= 2:
                t_irm = crossing_time(search_t, search_i, th_irm, "falling", start=0)
            if t_irm is None:
                t_irm = crossing_time(mid_t, mid_i, th_irm, "falling", start=0)

    if abs(if_level - zero_ref) > 1e-6:
        if ipk_if >= ipk_irm:
            comm_t = seg_t[ipk_irm : ipk_if + 1]
            comm_i = seg_i[ipk_irm : ipk_if + 1]
            if len(comm_t) >= 2:
                start_if = 0
                if t_irm is not None:
                    start_if = int(np.searchsorted(comm_t, t_irm, side="left"))
                    start_if = max(0, min(start_if, len(comm_t) - 2))
                t_if = crossing_time(comm_t, comm_i, th_if, "rising", start=start_if)
            if t_if is None:
                post_t = seg_t[ipk_if:]
                post_i = seg_i[ipk_if:]
                t_if = crossing_time(post_t, post_i, th_if, "falling", start=0)
        else:
            search_t = mid_t
            search_i = mid_i
            t_if = crossing_time(search_t, search_i, th_if, "falling", start=0)
            if t_if is None:
                t_if = crossing_time(search_t, search_i, th_if, "rising", start=0)

    return t_if, t_irm, th_if, th_irm


def _rr_threshold(zero_ref: float, peak_ref: float, pct: float) -> float:
    return float(zero_ref) + float(pct) * (float(peak_ref) - float(zero_ref))


def didt_rr_recovery(
    t: np.ndarray,
    i_d: np.ndarray,
    i0: int,
    i1: int,
    pct_a: float,
    pct_b: float,
    measure: str = "idm",
    ha_override: float | None = None,
    hb_override: float | None = None,
    irm_override: float | None = None,
    *,
    idm_override: float | None = None,
    base_override: float | None = None,
    zero_override: float | None = None,
) -> DidtCrossingResult:
    """
    反向恢复 di/dt（有符号 Irr）：
      - measure=idm：规格书 di/dt(1)/(2)；Ha=0div、Hb=IDM；th=Ha+pct·(Hb−Ha)；
        A/B 为换流前 IDM 下降沿上与 0.9·IDM / 0.1·IDM（或 0.8/0.2）的穿越时刻。
      - measure=if_irm：50%IF→50%IRM；H0=零基准，Ha=IF，Hb=IRM；
        thA=H0+pct_a·(Ha−H0)，thB=H0+pct_b·(Hb−H0)，分别在过零前/后搜穿越。
    ha_override/hb_override = GUI 横向光标 Ha/Hb（可手调）。zero_override = H0 零基准。
    idm_override/base_override 为兼容别名。
    """
    if ha_override is None:
        ha_override = idm_override
    if hb_override is None:
        hb_override = base_override
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    seg_t = t[i0 : i1 + 1]
    seg_i = i_d[i0 : i1 + 1].astype(np.float64)
    if len(seg_t) < 4:
        return DidtCrossingResult(0.0, None, None, 0.0, 0.0)

    idm_auto, irm_auto, _ = analyze_rr_recovery_current(seg_i)
    ha = 0.0 if ha_override is None else float(ha_override)
    if hb_override is not None:
        hb = float(hb_override)
    elif irm_override is not None and measure == "if_irm":
        hb = float(irm_override)
    elif idm_auto != 0.0:
        hb = float(idm_auto)
    else:
        hb = float(np.max(seg_i)) if len(seg_i) else 0.0
    idm_v = float(idm_auto)
    irm_v = float(irm_auto)

    if measure == "if_irm":
        zero_ref = 0.0 if zero_override is None else float(zero_override)
        if ha_override is not None:
            if_level = float(ha_override)
        else:
            if_level = float(np.max(seg_i)) if len(seg_i) else float(idm_auto)
        if hb_override is not None:
            irm_level = float(hb_override)
        elif irm_override is not None:
            irm_level = float(irm_override)
        else:
            irm_level = float(np.min(seg_i)) if len(seg_i) else float(irm_auto)

        t_a, t_b, th_if, th_irm = _rr_if_irm_crossings(
            seg_t, seg_i, zero_ref, if_level, irm_level, pct_a, pct_b
        )
        if t_a is None or t_b is None:
            return DidtCrossingResult(
                0.0, t_a, t_b, th_if, th_irm, idm=if_level, irm=irm_level
            )
        dt_s = abs(t_b - t_a)
        if dt_s < 1e-15:
            return DidtCrossingResult(
                0.0, t_a, t_b, th_if, th_irm, idm=if_level, irm=irm_level
            )
        didt = abs(th_if - th_irm) / dt_s / 1e9
        return DidtCrossingResult(
            float(didt), float(t_a), float(t_b), th_if, th_irm, idm=if_level, irm=irm_level
        )

    t_a, t_b, th_a, th_b = _rr_ha_hb_crossings(seg_t, seg_i, ha, hb, pct_a, pct_b)
    if t_a is None or t_b is None:
        return DidtCrossingResult(0.0, t_a, t_b, th_a, th_b, idm=idm_v, irm=irm_v)
    dt_s = t_b - t_a
    if abs(dt_s) < 1e-15:
        return DidtCrossingResult(0.0, t_a, t_b, th_a, th_b, idm=idm_v, irm=irm_v)
    didt = abs(th_a - th_b) / abs(dt_s) / 1e9
    return DidtCrossingResult(
        float(didt), t_a, t_b, th_a, th_b, idm=idm_v, irm=irm_v
    )


def didt_diode_recovery(
    t: np.ndarray,
    i_d: np.ndarray,
    i0: int,
    i1: int,
    pct_hi: float = 0.9,
    pct_lo: float = 0.1,
    measure: str = "idm",
) -> float:
    """二极管反向恢复 di/dt；默认 0.9·IDM→0.1·IDM（有符号 Irr）。"""
    res = didt_rr_recovery(t, i_d, i0, i1, pct_hi, pct_lo, measure=measure)
    return float(res.didt)


def dvdt_diode_recovery(
    t: np.ndarray,
    v_d: np.ndarray,
    i0: int,
    i1: int,
    pct_lo: float = 0.1,
    pct_hi: float = 0.9,
    vdm_top: float | None = None,
) -> float:
    """
    二极管反向恢复 dv/dt：按指导书 dv/dt(1) 用 0.1*(-VDM) -> 0.9*(-VDM)。
    对 |v_d| 做上升穿越，等价于指导书中的 -VDM 幅值定义，兼容通道极性差异。
    """
    seg_t = t[i0:i1]
    seg_v = np.abs(v_d[i0:i1]).astype(np.float64)
    if len(seg_t) < 4:
        return 0.0
    vdm = float(abs(vdm_top)) if vdm_top is not None and abs(vdm_top) > 1e-9 else float(np.max(seg_v))
    if vdm <= 1e-9:
        return 0.0

    th_lo = pct_lo * vdm
    th_hi = pct_hi * vdm
    t_a = crossing_time(seg_t, seg_v, th_lo, "rising", start=0)
    if t_a is None:
        return 0.0
    local = int(np.searchsorted(seg_t, t_a, side="left"))
    local = max(0, min(local, len(seg_t) - 2))
    t_b = crossing_time(seg_t, seg_v, th_hi, "rising", start=local)
    if t_b is None or t_b <= t_a:
        return 0.0
    return abs(th_hi - th_lo) / abs(t_b - t_a) / 1e9


# backward-compatible aliases
def peak_dvdt(t, vce, i0, i1, dt, cfg):
    return dvdt_max(t, vce, i0, i1, dt, cfg)


def peak_didt(t, ic, i0, i1, dt, cfg):
    return didt_max(t, ic, i0, i1, dt, cfg)
