from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dpt_extractor.utils.signal import crossing_index
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
        return tail
    return early


def _plateau_mean_vce_after_on(
    vce: np.ndarray, ic: np.ndarray, on_idx: int, w1: int, dt: float
) -> float:
    """开通：Vce 回落至导通态后的平稳均值（Eon 积分终点 Vce 穿越电平）。"""
    post_v = vce[on_idx : w1 + 1].astype(np.float64)
    post_i = np.abs(ic[on_idx : w1 + 1])
    if len(post_v) < 8:
        return float(np.mean(post_v)) if len(post_v) else 0.0
    i_top = float(np.percentile(post_i, 95))
    cond_thr = max(0.5 * i_top, 20.0)
    cond = post_i >= cond_thr
    if int(np.count_nonzero(cond)) >= 8:
        return float(np.percentile(post_v[cond], 20))
    settle_len = max(12, int(80e-9 / dt))
    if len(post_v) > settle_len:
        return float(np.mean(post_v[-settle_len:]))
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
    end_ix = len(yy) - 2 if end is None else max(first_ix + 1, min(int(end), len(yy) - 2))
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
    return chosen, float(chosen_t)


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
            raw_ix = None
            for kk in range(raw_lo, raw_hi + 1):
                y0, y1 = float(yy[kk]), float(yy[kk + 1])
                if y0 <= lvl < y1 and y1 > y0:
                    raw_ix = kk
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
    return _main_edge_level_crossing(
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
    )


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
    )


def _eoff_ic_fall_crossing_at_main_fall(
    t_seg: np.ndarray,
    i_seg: np.ndarray,
    hb: float,
    anchor: int,
    dt: float,
    i_top: float,
) -> tuple[int, float]:
    """关断 B：Ic 主下降沿与 Hb 的第一个真实交点。"""
    return _main_edge_level_crossing(
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


def _eon_vce_hb_fall_crossing_at_main_fall(
    t_seg: np.ndarray,
    v_seg: np.ndarray,
    hb: float,
    anchor: int,
    dt: float,
    v_top: float,
) -> tuple[int, float]:
    """开通 B：Vce 主下降沿与 Hb 的第一个真实交点。"""
    return _main_edge_level_crossing(
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
    A=Vce 与 Ha 上升穿越；B=Ic 主下降沿与 Hb 的第一个真实交点。
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

    sw0 = max(w0, i0)
    v_seg = vce[sw0 : w1 + 1].astype(np.float64)
    # 带符号：下桥关断回落平台为负，B=Ic 回落与 Hb 交点须在真实波形上
    i_seg = ic[sw0 : w1 + 1].astype(np.float64)
    t_sw = t[sw0 : w1 + 1]
    local_off = off_idx - sw0

    low_current_eoff = float(i_top) < 180.0
    i_start_local, t_start = _eoff_vce_ha_crossing_at_main_rise(
        t_sw,
        v_seg,
        ha_v,
        dt,
        float(v_top),
        pre_rise_span_ns=320.0 if low_current_eoff else 160.0,
    )

    fall_anchor = max(i_start_local + 1, int(np.searchsorted(t_sw, t_start, side="left")))
    i_end_local, t_end = _eoff_ic_fall_crossing_at_main_fall(
        t_sw, i_seg, hb_a, fall_anchor, dt, float(i_top)
    )

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
    A=Ic 上升沿与 Ha 的交点；B=Vce 主下降沿与 Hb 的第一个真实交点。
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
    hb_v = _plateau_mean_vce_after_on(vce, ic, on_ref, w1, dt)

    sw0 = max(w0, i0, on_ref - int(200e-9 / dt))
    win1 = min(w1, i1, on_ref + int(1200e-9 / dt))
    if win1 <= sw0 + 2:
        win1 = min(len(t) - 1, max(i1, sw0 + int(350e-9 / dt)))
    # 带符号：下桥导通前基线为负，A=Ic 上升沿与 Ha 交点须在真实波形上
    i_seg = ic[sw0 : win1 + 1].astype(np.float64)
    v_seg = vce[sw0 : win1 + 1].astype(np.float64)
    t_sw = t[sw0 : win1 + 1]
    local_on = on_ref - sw0

    anchor = max(0, local_on - int(15e-9 / dt))
    i_start_local, t_start = _eon_ic_rise_crossing_at_main_rise(
        t_sw, i_seg, ha_ic, anchor, dt, float(i_top)
    )
    if i_start_local >= len(i_seg) - 2:
        i_start_local = max(0, min(len(i_seg) - 2, local_on))
        t_start = float(t_sw[i_start_local])

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


def err_window_scope_example(
    t: np.ndarray,
    irr: np.ndarray,
    v_diode: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
) -> IntegrationWindow:
    """
    示波器口径（用户定义）:
    - t1: 反向恢复电流离开 base
    - t2: 二极管电压回到 base
    """
    n = len(t)
    w0 = max(0, i0)
    w1 = min(n - 1, i1)
    if w1 <= w0 + 10:
        return IntegrationWindow(w0, w1, float(t[w0]), float(t[w1]))

    i_seg = irr[w0:w1].astype(np.float64)
    v_seg = v_diode[w0:w1].astype(np.float64)
    if len(i_seg) < 8:
        return IntegrationWindow(w0, w1, float(t[w0]), float(t[w1]))

    # 恢复主瓣峰值（通常为正峰），并在其前小窗口找反向谷值作为 t1
    i_peak = int(np.argmax(i_seg))
    lb = max(5, int(140e-9 / max(dt, 1e-15)))
    a = max(0, i_peak - lb)
    if i_peak > a:
        i_start_local = a + int(np.argmin(i_seg[a : i_peak + 1]))
    else:
        i_start_local = int(np.argmin(i_seg))

    # base 取窗口后段（示波器“归零点”）
    tail = max(10, int(180e-9 / max(dt, 1e-15)))
    i_base = float(np.percentile(i_seg[max(0, len(i_seg) - tail) :], 50))
    v_base = float(np.percentile(v_seg[max(0, len(v_seg) - tail) :], 50))

    i_span = max(float(np.max(np.abs(i_seg - i_base))), 1.0)
    v_span = max(float(np.max(np.abs(v_seg - v_base))), 1.0)
    i_tol = max(8.0, 0.02 * i_span)
    v_tol = max(4.0, 0.01 * v_span)
    hold = max(5, int(20e-9 / max(dt, 1e-15)))

    # t2：电流与电压同时回到各自 base（并保持短暂稳定）
    i_end_local = None
    for j in range(max(i_peak, i_start_local + 1), len(i_seg) - hold):
        i_ok = float(np.max(np.abs(i_seg[j : j + hold] - i_base))) <= i_tol
        v_ok = float(np.max(np.abs(v_seg[j : j + hold] - v_base))) <= v_tol
        if i_ok and v_ok:
            i_end_local = j
            break
    if i_end_local is None:
        i_end_local = len(i_seg) - 1
    if i_end_local <= i_start_local + 5:
        i_end_local = min(len(i_seg) - 1, i_start_local + int(300e-9 / max(dt, 1e-15)))

    i_start = w0 + int(i_start_local)
    i_end = w0 + int(i_end_local)
    return IntegrationWindow(i_start, i_end, float(t[i_start]), float(t[i_end]))


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


def _err_recovery_settled_base(
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

    # 第一口径只吃主恢复大振荡已明显收敛的位置；找不到时再回退旧的宽口径，
    # 避免无法自然收敛的样例被硬拖到后续长尾。
    strict = _scan_with_ceiling(max(16.0, 0.149 * peak_abs), strict=True)
    if strict is not None:
        return strict
    loose = _scan_with_ceiling(max(18.0, 0.22 * peak_abs), strict=False)
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


def _err_interp_value_at_time(t: np.ndarray, y: np.ndarray, t_value: float) -> float:
    if len(t) == 0 or len(y) == 0:
        return 0.0
    tv = float(t_value)
    if tv <= float(t[0]):
        return float(y[0])
    if tv >= float(t[-1]):
        return float(y[-1])
    k = int(np.searchsorted(t, tv, side="right") - 1)
    k = max(0, min(k, len(t) - 2))
    t0, t1 = float(t[k]), float(t[k + 1])
    y0, y1 = float(y[k]), float(y[k + 1])
    if abs(t1 - t0) < 1e-30:
        return y0
    frac = float(np.clip((tv - t0) / (t1 - t0), 0.0, 1.0))
    return y0 + frac * (y1 - y0)


def _err_low_current_recovery_endpoint_t(
    t: np.ndarray,
    irr: np.ndarray,
    ipk_global: int,
    i_end: int,
    dt: float,
) -> float | None:
    """低电流 Err A：峰后等待足够恢复时间，再取右侧稳定纵向落点。"""
    y = np.asarray(irr, dtype=np.float64)
    if len(y) < 12:
        return None
    k0 = max(0, min(int(ipk_global), len(y) - 2))
    peak_abs = abs(float(y[k0]))
    if peak_abs <= 1.0 or peak_abs >= 90.0:
        return None
    k_end = max(k0 + 2, min(int(i_end), len(y) - 1))
    base_len = max(16, int(60e-9 / max(dt, 1e-15)))
    scan_hi = k_end - base_len
    if scan_hi <= k0:
        return None
    min_after_ns = 280.0 + max(0.0, peak_abs - 60.0) * 3.0
    scan_lo = min(scan_hi, k0 + max(4, int(min_after_ns * 1e-9 / max(dt, 1e-15))))
    amp_ceiling = max(3.5, 0.10 * peak_abs)
    point_ceiling = max(3.2, 0.04 * peak_abs)
    for k in range(scan_lo, scan_hi + 1):
        block = y[k : k + base_len]
        if len(block) < base_len:
            break
        amp = 0.5 * (float(np.max(block)) - float(np.min(block)))
        if amp > amp_ceiling:
            continue
        if abs(float(y[k])) <= point_ceiling:
            return float(t[k])
    return None


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
    t: np.ndarray, vd: np.ndarray, hb_hint: float, ipk_global: int, dt: float
) -> tuple[int, int, int | None, float]:
    """Err Vd 主上升沿搜索：限定在第二脉冲开通过程/反向恢复 IRM 附近。"""
    ipk_global = int(ipk_global)
    lo = max(0, ipk_global - int(800e-9 / max(dt, 1e-15)))
    hi = min(len(vd) - 2, ipk_global + int(50e-9 / max(dt, 1e-15)))
    if hi <= lo + 1:
        return lo, hi, None, float(vd[min(ipk_global, len(vd) - 1)])
    v_peak = float(np.max(vd[lo : ipk_global + 1]))
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
    t: np.ndarray, vd: np.ndarray, hb_hint: float, ipk_global: int, dt: float
) -> float:
    """Err Hb：第二脉冲开通过程中，Vd 主上升沿前的本地 base。"""
    _lo, _hi, k_trigger, _v_peak = _err_vd_main_rise_search(
        t, vd, hb_hint, ipk_global, dt
    )
    if k_trigger is None:
        return float(hb_hint)
    pre_hi = int(np.searchsorted(t, float(t[k_trigger]) - 20e-9, side="left"))
    pre_lo = int(np.searchsorted(t, float(t[k_trigger]) - 120e-9, side="left"))
    pre_lo = max(0, min(pre_lo, len(vd) - 1))
    pre_hi = max(pre_lo + 1, min(pre_hi, len(vd)))
    seg = np.asarray(vd[pre_lo:pre_hi], dtype=np.float64)
    if len(seg) < 8:
        return float(hb_hint)
    return float(np.median(seg))


def _err_vd_rise_cross_hb_t(
    t: np.ndarray, vd: np.ndarray, hb: float, ipk_global: int, i0: int, dt: float
) -> float:
    """Vd 主上升沿第一次穿 Hb（带符号）的交点。

    搜索窗以 IRM 为锚向左延伸，不得仅用 reverse_recovery 段起点截断（WH 等工况
    段起点常晚于真实抬升脚，否则会误落在段界上）。
    """
    _ = i0  # 保留参数以兼容调用方
    lo, hi, _k_trigger, v_peak = _err_vd_main_rise_search(
        t, vd, hb, ipk_global, dt
    )
    if hi <= lo + 1:
        return float(t[min(ipk_global, len(t) - 1)])
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
        raw_window_ns=160.0,
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
    settle_strict: bool = False,
) -> float:
    """IRM 主峰后恢复沿与 Ha 的第一个真实交点（秒）。

    上桥软恢复：Irr 为正、Ha 为尾段带符号平台时，示波器读数为 |Irr| 与 |Ha|，
    按幅值穿越；硬恢复/下桥负向过冲仍用带符号 Irr 穿越。
    """
    k0 = max(0, int(ipk_global))
    k1 = max(k0 + 1, min(int(i_end), len(irr) - 1))
    peak = float(irr[k0]) if k0 < len(irr) else 0.0
    use_mag = not force_signed and peak > 0.0 and float(ha) > 0.0
    y = np.abs(np.asarray(irr, dtype=np.float64)) if use_mag else np.asarray(irr, dtype=np.float64)
    lvl = abs(float(ha)) if use_mag else float(ha)

    crossings: list[tuple[int, float, str]] = []
    for k in range(k0, k1):
        y0, y1 = float(y[k]), float(y[k + 1])
        if min(y0, y1) <= lvl <= max(y0, y1) and abs(y1 - y0) > 1e-30:
            direction = "falling" if y1 < y0 else "rising"
            crossings.append((k, _err_interp_cross_time(t, y, k, lvl), direction))

    if crossings:
        for _k, t_cross, direction in crossings:
            if direction == "falling":
                return float(t_cross)
        return float(crossings[0][1])

    if use_mag:
        lvl = abs(float(ha))
    else:
        lvl = float(ha)
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
        w = err_window_scope_example(t, irr, v_diode, i0, i1, dt)
        return EnergyLossMarkers(0.0, 0.0, w.t_start, w.t_end, w.i_start, w.i_end)

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
    # Ha=恢复后稳定 Irr 平台；稳定窗由本次反向恢复右侧的局部振荡收敛决定，
    # 不再使用峰后固定 400~800ns 尾窗。
    err_base = _err_recovery_settled_base(irr_full, ipk_global, dt, i_search_end)
    ha_tail = float(err_base.level)
    peak = float(irr_full[ipk_global])
    signed_tail_after_rebound = peak > 0.0 and float(ha_tail) < 0.0 and (
        abs(float(ha_tail)) >= max(3.0, 0.03 * abs(float(peak)))
        or _err_has_dominant_opposite_rebound(irr_full, ipk_global, i_search_end, peak, dt)
    )
    use_irr_mag = peak > 0.0 and (
        float(ha_tail) > 0.0
        or (
            float(ha_tail) < 0.0
            and not signed_tail_after_rebound
            and abs(peak) > 3.0 * abs(float(ha_tail))
        )
    )
    ha = (
        float(ha_tail)
        if signed_tail_after_rebound
        else (abs(float(ha_tail)) if use_irr_mag else float(ha_tail))
    )
    # Hb=第二脉冲开通过程中，对管电压 Vd 主上升沿前的本地 base。
    # B 必须贴同一段 Vd 与该横线的真实交点，不能取全局或关断过程 base。
    hb_hint = _err_window_mid(vd_full, t, tpk - 600e-9, tpk - 200e-9)
    hb_v = _err_vd_base_before_main_rise(t, vd_full, hb_hint, ipk_global, dt)
    i_fall_end = max(
        ipk_global + 2,
        min(
            int(i_search_end),
            max(err_base.end_idx + 2, ipk_global + int(120e-9 / max(dt, 1e-15))),
        ),
    )
    t_a_irr = _err_irr_fall_cross_ha_t(
        t,
        irr_full,
        ha,
        ipk_global,
        i_fall_end,
        dt,
        force_signed=signed_tail_after_rebound,
        settle_idx=err_base.start_idx,
        settle_strict=err_base.strict,
    )
    # B=Vd 主抬升沿与 Hb 的首个上升穿越（带符号 Vd）
    t_b_v = _err_vd_rise_cross_hb_t(t, vd_full, hb_v, ipk_global, i0, dt)

    if abs(t_a_irr - t_b_v) < 1e-15:
        w = err_window_scope_example(t, irr, v_diode, i0, i1, dt)
        t_a_irr, t_b_v = w.t_start, w.t_end

    # A=Irr 与 Ha 交点；B=Vd 与 Hb 交点（B 往往早于 A）
    t_start = float(t_a_irr)
    t_end = float(t_b_v)
    t_lo = min(t_start, t_end)
    t_hi = max(t_start, t_end)

    i_start = int(np.searchsorted(t, t_lo, side="left"))
    i_end = int(np.searchsorted(t, t_hi, side="left"))
    i_start = max(i0, min(i_start, len(t) - 2))
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
