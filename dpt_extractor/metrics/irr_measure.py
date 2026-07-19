"""反向恢复 Irr / Trr 示波器卡尺口径（主峰到恢复稳定平台）。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dpt_extractor.metrics.plateau_level import (
    _plateau_mid_without_isolated_spikes,
)
from dpt_extractor.metrics.rr_tail import reverse_recovery_tail_end_index

@dataclass(frozen=True)
class IrrTrrMeasure:
    """Trr 主峰到稳定平台卡尺上下文。

    ``Hb`` 是有符号 I_RM 主峰，``Ha`` 是峰后恢复稳定平台本身的
    可见最大/最小值中点。
    ``A/B`` 分别是同一条原始带符号 Irr 主瓣上升沿、峰后下降沿与
    ``Ha`` 的第一个真实插值交点。
    """

    ha: float
    hb: float
    ta_s: float
    tb_s: float
    irr: float
    trr_ns: float
    peak_idx: int
    stable_level: float | None = None


def _interp_cross_time(
    ts: np.ndarray, ys: np.ndarray, j: int, level: float
) -> float:
    y1, y2 = float(ys[j]), float(ys[j + 1])
    t1, t2 = float(ts[j]), float(ts[j + 1])
    dy = y2 - y1
    if abs(dy) < 1e-12:
        return t1
    f = (level - y1) / dy
    f = max(0.0, min(1.0, f))
    return t1 + f * (t2 - t1)


def _find_recovery_peak_index(seg: np.ndarray, dt: float) -> int:
    """Irr/Trr 主峰：取反向恢复电流主瓣的绝对峰值。"""
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 3:
        return int(np.argmax(np.abs(seg))) if len(seg) else 0
    pos_max = float(np.max(seg))
    neg_min = float(np.min(seg))
    if pos_max >= abs(neg_min):
        return int(np.argmax(seg))
    return int(np.argmin(seg))


def irr_parameter_peak_index(
    irr: np.ndarray,
    rr0: int,
    rr1: int,
    on_edge: int,
    on0: int,
    on1: int,
) -> int:
    """Index for the Irr parameter peak, matching extraction's main-lobe rule."""
    arr = np.asarray(irr, dtype=np.float64)
    n = len(arr)
    if n == 0:
        return 0
    s0 = max(0, min(max(int(rr0), int(on_edge)), int(on1) - 1, n - 1))
    s1 = max(s0 + 1, min(int(on1), n))
    if s1 <= s0:
        s0 = max(0, min(int(on0), n - 1))
        s1 = max(s0 + 1, min(int(on1), n))
    seg = arr[s0:s1]
    if len(seg) == 0:
        return s0

    pos_i = int(np.argmax(seg))
    neg_i = int(np.argmin(seg))
    peak_pos = float(seg[pos_i])
    peak_neg = abs(float(seg[neg_i]))
    amp = max(peak_pos, peak_neg, 1.0)
    if peak_pos >= 0.1 * amp:
        return s0 + pos_i

    k = max(8, len(seg) // 5)
    head = seg[:k]
    ref = float(np.median(head)) if len(head) else float(np.median(seg))
    th = 0.02 * amp
    head_diffs = np.diff(np.asarray(head, dtype=np.float64))
    local_noise = (
        float(np.median(np.abs(head_diffs - np.median(head_diffs))))
        if len(head_diffs)
        else 0.0
    )
    negative_platform_fraction = (
        float(np.mean(head <= -0.5 * peak_neg))
        if len(head) and peak_neg > 0.0
        else 0.0
    )
    clear_negative_platform = (
        ref <= -0.5 * peak_neg and negative_platform_fraction >= 0.75
    )
    recovery_floor = max(3.0, th, 6.0 * local_noise)

    # At high load, a real 60--80 A positive I_RM can be less than 10% of the
    # preceding -800--1100 A commutation platform.  Select it only when that
    # large negative platform is clearly present, the positive lobe follows
    # the platform trough, and it clears the local raw-sample noise floor.
    # Near-zero and generic bipolar inputs therefore retain the existing
    # signed-main-lobe rule below.
    if (
        clear_negative_platform
        and pos_i > neg_i
        and peak_pos >= recovery_floor
    ):
        return s0 + pos_i

    if peak_neg >= 0.1 * amp:
        return s0 + neg_i

    if ref < 0:
        cross = np.where(seg > th)[0]
        if len(cross):
            start = int(cross[0])
            return s0 + start + int(np.argmax(seg[start:]))
    elif ref > 0:
        cross = np.where(seg < -th)[0]
        if len(cross):
            start = int(cross[0])
            return s0 + start + int(np.argmin(seg[start:]))
    return s0 + pos_i


def irr_parameter_peak_value(
    irr: np.ndarray,
    rr0: int,
    rr1: int,
    on_edge: int,
    on0: int,
    on1: int,
) -> float:
    """Magnitude of the Irr parameter peak, matching ``irr_parameter_peak_index``."""
    arr = np.asarray(irr, dtype=np.float64)
    if len(arr) == 0:
        return 0.0
    idx = max(
        0,
        min(
            irr_parameter_peak_index(arr, rr0, rr1, on_edge, on0, on1),
            len(arr) - 1,
        ),
    )
    return abs(float(arr[idx]))


def _trr_recovery_stable_level(
    t: np.ndarray,
    irr: np.ndarray,
    peak_idx: int,
    tail_end_idx: int,
) -> float | None:
    """Return the post-peak stable-platform centre used by Trr.

    Keep the project's historical Trr recovery-platform window (300--600 ns
    after I_RM) so this change only replaces the Trr reference level.  When a
    record is shorter, use the last available up-to-200 ns post-peak window.
    The final level is the visible-band midpoint ``(max + min) / 2`` after
    applying the project's existing isolated-spike guard.
    """

    t_arr = np.asarray(t, dtype=np.float64)
    irr_arr = np.asarray(irr, dtype=np.float64)
    n = min(len(t_arr), len(irr_arr))
    if n < 3:
        return None
    peak_idx = max(0, min(int(peak_idx), n - 2))
    tail_end_idx = min(int(tail_end_idx), n - 1)
    if tail_end_idx <= peak_idx:
        return None
    peak_t = float(t_arr[peak_idx])
    tail_t = float(t_arr[tail_end_idx])

    def _mid_if_enough(lo_s: float, hi_s: float) -> float | None:
        lo, hi = float(lo_s), float(hi_s)
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            return None
        i0 = int(np.searchsorted(t_arr[:n], lo, side="left"))
        i1 = int(np.searchsorted(t_arr[:n], hi, side="right"))
        i0 = max(0, min(i0, n - 1))
        i1 = max(0, min(i1, n))
        if i1 <= i0:
            return None
        values = irr_arr[i0:i1]
        values = values[np.isfinite(values)]
        if values.size < 3:
            return None
        return float(_plateau_mid_without_isolated_spikes(values))

    preferred_lo = peak_t + 0.3e-6
    preferred_hi = min(peak_t + 0.6e-6, tail_t)
    stable = (
        _mid_if_enough(preferred_lo, preferred_hi)
        if preferred_hi > preferred_lo
        else None
    )
    if stable is not None:
        return float(stable)

    fallback_hi = tail_t
    # A short-tail fallback still needs a real post-peak platform.  Excluding
    # the peak sample makes fewer than three recovered samples fail closed
    # instead of averaging I_RM into a fabricated stable level.
    fallback_lo = max(float(t_arr[peak_idx + 1]), fallback_hi - 0.2e-6)
    return _mid_if_enough(fallback_lo, fallback_hi)


def _lobe_valley_before_peak(seg: np.ndarray, ipk: int) -> int:
    """尖峰前主瓣谷底，用于限定 A/B 交点搜索范围。"""
    lookback = min(300, max(20, ipk))
    w0 = max(0, ipk - lookback)
    return w0 + int(np.argmin(seg[w0:ipk]))


def _plateau_end_before_spike(seg: np.ndarray, ipk: int) -> int:
    """主尖峰陡升起点：其前为无震荡电流平台。"""
    j_lo = _lobe_valley_before_peak(seg, ipk)
    peak = float(seg[ipk])
    level_thr = max(0.18 * peak, float(np.percentile(seg[j_lo:ipk], 25)))
    for j in range(ipk - 1, max(j_lo, ipk - 350), -1):
        if float(seg[j]) < level_thr:
            return min(ipk - 1, j + 1)
    return max(j_lo + 1, ipk // 2)


def _quiet_plateau_block(seg: np.ndarray, ipk: int, j_lo: int) -> np.ndarray:
    """尖峰前无震荡平台：在峰前搜索斜率/幅值最小的短窗。"""
    peak = float(seg[ipk])
    search_lo = max(j_lo, ipk - 220)
    search_hi = max(search_lo + 12, ipk - 12)
    best_sub: np.ndarray | None = None
    best_span = float("inf")
    for wlen in range(10, 22):
        for w0 in range(search_lo, search_hi - wlen + 1):
            sub = np.asarray(seg[w0 : w0 + wlen], dtype=np.float64)
            if float(np.mean(sub)) > 0.35 * peak:
                continue
            if float(np.max(np.abs(np.diff(sub)))) > 0.75:
                continue
            span = float(np.max(sub) - np.min(sub))
            if span < best_span:
                best_span = span
                best_sub = sub
    if best_sub is not None and len(best_sub) >= 3:
        return best_sub
    onset = _plateau_end_before_spike(seg, ipk)
    return np.asarray(seg[max(j_lo, onset - 18) : onset], dtype=np.float64)


def _default_ha(seg: np.ndarray, ipk: int) -> float:
    """尖峰前无震荡电流平台：(该平台 max + min) / 2。"""
    j_lo = _lobe_valley_before_peak(seg, ipk)
    block = _quiet_plateau_block(seg, ipk, j_lo)
    if len(block) < 3:
        block = np.asarray(seg[: max(8, min(ipk, len(seg) // 4))], dtype=np.float64)
    return 0.5 * (float(np.max(block)) + float(np.min(block)))


def _first_crossing_index(
    seg: np.ndarray, j0: int, j1: int, level: float
) -> int | None:
    j0 = max(0, j0)
    j1 = min(len(seg) - 2, j1)
    if j1 < j0:
        return None
    for j in range(j0, j1 + 1):
        y1, y2 = float(seg[j]), float(seg[j + 1])
        if (y1 - level) * (y2 - level) <= 0.0 and abs(y2 - y1) > 1e-12:
            return j
    return None


def _trr_cross_indices_at_ha(
    seg: np.ndarray,
    ipk: int,
    level: float,
    *,
    j_fall_end: int | None = None,
) -> tuple[int | None, int | None]:
    """主瓣上升沿 / 下降沿与 Ha 的首个交点索引（段内相对下标）。"""
    ipk = max(1, min(int(ipk), len(seg) - 2))
    peak = float(seg[ipk])
    level_f = float(level)
    polarity = 1.0 if peak >= level_f else -1.0
    work = np.asarray(seg, dtype=np.float64) * polarity
    level_w = level_f * polarity
    peak_w = float(work[ipk])
    jf = min(len(seg) - 2, j_fall_end if j_fall_end is not None else len(seg) - 2)

    # A：从反向恢复事件窗起点开始，取主瓣上升沿与恢复平台中线的
    # 第一个上升穿越。稳定平台线通常明显早于半高点，不能沿用只回看
    # 峰前 300 点的局部谷底，否则慢沿/高采样率记录会把真实 A 排除。
    ja: int | None = None
    search_lo = 0
    for j in range(search_lo, ipk):
        y1, y2 = float(work[j]), float(work[j + 1])
        if y1 <= level_w < y2 or (
            (y1 - level_w) * (y2 - level_w) <= 0.0 and y2 > y1 and abs(y2 - y1) > 1e-12
        ):
            ja = j
            break
    if ja is None:
        for j in range(search_lo, ipk):
            y1, y2 = float(work[j]), float(work[j + 1])
            if (y1 - level_w) * (y2 - level_w) <= 0.0 and y2 > y1:
                ja = j
                break

    # B：尖峰下降沿与 Ha 的第一个下降穿越
    jb: int | None = None
    for j in range(ipk, jf):
        y1, y2 = float(work[j]), float(work[j + 1])
        if y1 >= y2 and y1 > level_w >= y2:
            jb = j
            break
    return ja, jb


def trr_rise_cross_at_ha(
    t: np.ndarray,
    irr: np.ndarray,
    i0: int,
    i1: int,
    ha: float,
    *,
    peak_idx: int | None = None,
) -> tuple[float, int] | None:
    """固定主峰，仅重算上升沿与 Ha 的交点 A（秒）。"""
    i0 = max(0, min(i0, len(t) - 2))
    i1 = max(i0 + 2, min(i1, len(t) - 1))
    seg = np.asarray(irr[i0 : i1 + 1], dtype=np.float64)
    ts = np.asarray(t[i0 : i1 + 1], dtype=np.float64)
    if len(seg) < 12:
        return None
    dt = float(np.median(np.diff(ts))) if len(ts) > 1 else 1e-9
    if peak_idx is not None:
        ipk = peak_idx - i0
    else:
        ipk = _find_recovery_peak_index(seg, dt)
    ipk = max(1, min(ipk, len(seg) - 2))
    jf = min(len(seg) - 2, ipk + int(600e-9 / max(dt, 1e-15)))
    ja, _ = _trr_cross_indices_at_ha(seg, ipk, float(ha), j_fall_end=jf)
    if ja is None:
        return None
    return _interp_cross_time(ts, seg, ja, float(ha)), i0 + ipk


def trr_crossings_at_ha(
    t: np.ndarray,
    irr: np.ndarray,
    i0: int,
    i1: int,
    ha: float,
    *,
    peak_idx: int | None = None,
    i_fall_end: int | None = None,
) -> tuple[float, float, int] | None:
    """
    固定尖峰位置，按 Ha 重算 A/B 交点时刻（秒）。
    返回 (ta_s, tb_s, peak_idx)。
    """
    i0 = max(0, min(i0, len(t) - 2))
    i1 = max(i0 + 2, min(i1, len(t) - 1))
    if i_fall_end is not None:
        i1 = max(i1, min(int(i_fall_end), len(t) - 1))
    seg = np.asarray(irr[i0 : i1 + 1], dtype=np.float64)
    ts = np.asarray(t[i0 : i1 + 1], dtype=np.float64)
    if len(seg) < 12:
        return None

    dt = float(np.median(np.diff(ts))) if len(ts) > 1 else 1e-9
    if peak_idx is not None:
        ipk = peak_idx - i0
    else:
        ipk = _find_recovery_peak_index(seg, dt)
    ipk = max(1, min(ipk, len(seg) - 2))

    level = float(ha)
    jf_rel = len(seg) - 2
    ja, jb = _trr_cross_indices_at_ha(seg, ipk, level, j_fall_end=jf_rel)
    if ja is None or jb is None:
        return None

    ta = _interp_cross_time(ts, seg, ja, level)
    # A/B/Ha share the same signed logical Irr source.  Interpolating B on
    # abs(Irr) when a positive lobe returns to a slightly negative Ha creates
    # a plausible time that is not an intersection of the displayed waveform
    # and horizontal cursor.
    tb = _interp_cross_time(ts, seg, jb, level)
    if tb <= ta:
        return None
    return ta, tb, i0 + ipk


def measure_irr_trr(
    t: np.ndarray,
    irr: np.ndarray,
    i0: int,
    i1: int,
    *,
    ha: float | None = None,
    peak_idx: int | None = None,
    i_fall_end: int | None = None,
    stable_level: float | None = None,
) -> IrrTrrMeasure | None:
    """
    在 [i0,i1] 内识别反向恢复主瓣：
    - Hb：有符号反向恢复尖峰 I_RM
    - Ha：默认取峰后恢复稳定平台本身的可见最大/最小值中点；可由手动交互指定
    - A/B：主瓣上升沿、下降沿与 Ha 的交点时刻（Trr）
    """
    i0 = max(0, min(i0, len(t) - 2))
    i1 = max(i0 + 2, min(i1, len(t) - 1))
    seg = np.asarray(irr[i0 : i1 + 1], dtype=np.float64)
    ts = np.asarray(t[i0 : i1 + 1], dtype=np.float64)
    if len(seg) < 12:
        return None

    dt = float(np.median(np.diff(ts))) if len(ts) > 1 else 1e-9
    if peak_idx is not None:
        ipk = peak_idx - i0
    else:
        ipk = _find_recovery_peak_index(seg, dt)
    ipk = max(1, min(ipk, len(seg) - 2))

    hb = float(seg[ipk])
    irr_val = abs(hb)

    if i_fall_end is None:
        i_fall_end = min(len(t) - 1, i0 + ipk + int(600e-9 / max(dt, 1e-15)))
    if stable_level is None:
        stable_level = _trr_recovery_stable_level(
            t,
            irr,
            i0 + ipk,
            int(i_fall_end),
        )
    if ha is None:
        if stable_level is None or not np.isfinite(float(stable_level)):
            return None
        level = float(stable_level)
    else:
        level = float(ha)
    cross = trr_crossings_at_ha(
        t, irr, i0, i1, level, peak_idx=i0 + ipk, i_fall_end=i_fall_end
    )
    if cross is None:
        return None
    ta, tb, pk = cross

    return IrrTrrMeasure(
        ha=level,
        hb=hb,
        ta_s=ta,
        tb_s=tb,
        irr=irr_val,
        trr_ns=max(0.0, (tb - ta) * 1e9),
        peak_idx=pk,
        stable_level=(
            float(stable_level)
            if stable_level is not None and np.isfinite(float(stable_level))
            else None
        ),
    )


def default_irr_trr_measure(
    t: np.ndarray,
    irr: np.ndarray,
    rr0: int,
    rr1: int,
    on_edge: int,
    on0: int,
    on1: int,
    *,
    pulse2_off: int | None = None,
) -> IrrTrrMeasure | None:
    """
    Trr 唯一默认口径：主恢复峰到峰后恢复稳定平台中线的时间宽度。

    Hb 为有符号 I_RM 主峰，Ha 为恢复稳定平台本身的可见最大/最小值
    中点；A/B 是
    原始带符号 Irr 在主峰上升沿、峰后下降沿与 Ha 的第一个交点。
    Irr 峰值选择、Err 积分以及反向恢复 di/dt 均不由本函数修改。
    """
    t_arr = np.asarray(t, dtype=np.float64)
    irr_arr = np.asarray(irr, dtype=np.float64)
    n = min(len(t_arr), len(irr_arr))
    if n < 12:
        return None

    rr0 = max(0, min(int(rr0), n - 2))
    rr1 = max(rr0 + 2, min(int(rr1), n - 1))
    on0 = max(0, min(int(on0), n - 2))
    on1 = max(on0 + 2, min(int(on1), n - 1))
    on_edge = max(0, min(int(on_edge), n - 1))

    pulse2_off_i: int | None = None
    peak_search_end = on1
    rr1_event = rr1
    tail_on1 = on1
    if pulse2_off is not None:
        pulse2_off_i = max(0, min(int(pulse2_off), n - 1))
        # pulse2_off is the first sample of the following turn-off event, so
        # neither the I_RM search nor the recovered platform may include it.
        event_last = pulse2_off_i - 1
        if event_last <= max(rr0, on_edge):
            return None
        peak_search_end = min(on1, pulse2_off_i)
        rr1_event = min(rr1, event_last)
        tail_on1 = min(on1, event_last)

    peak_idx = irr_parameter_peak_index(
        irr_arr,
        rr0,
        rr1_event,
        on_edge,
        on0,
        peak_search_end,
    )
    peak_idx = max(rr0, min(int(peak_idx), min(peak_search_end - 1, n - 1)))
    if pulse2_off_i is not None and pulse2_off_i <= peak_idx:
        return None
    fall_end = reverse_recovery_tail_end_index(
        t_arr,
        rr1_event,
        tail_on1,
        peak_idx=peak_idx,
        pulse2_off=pulse2_off_i,
    )
    if pulse2_off_i is not None:
        fall_end = min(fall_end, pulse2_off_i - 1)
    if fall_end <= peak_idx:
        return None
    measure_i1 = max(rr1_event, peak_idx)

    return measure_irr_trr(
        t_arr,
        irr_arr,
        rr0,
        measure_i1,
        peak_idx=peak_idx,
        i_fall_end=fall_end,
    )
