from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.utils.signal import crossing_index, smooth, threshold_value
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
    Err:  ha_v=Irr 平台(A)；hb_a=V_二极管 基线(V)；v_b 同 hb_a。
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


def _icm(ic: np.ndarray, i0: int, i1: int) -> float:
    return float(np.percentile(np.abs(ic[i0:i1]), 95))


def _vge_levels(vge: np.ndarray, i0: int, i1: int) -> tuple[float, float]:
    seg = vge[i0:i1]
    return float(np.percentile(seg, 5)), float(np.percentile(seg, 95))


def eoff_window_iec(
    t: np.ndarray,
    vge: np.ndarray,
    ic: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    off_idx: int,
    dt: float,
    cfg: AppConfig,
    vdc: float | None = None,
) -> IntegrationWindow:
    """IEC60747-9 Eoff: t1=90% Vge↓, t2=2% Icm↓."""
    th = cfg.thresholds
    w0 = max(i0, off_idx - int(80e-9 / dt))
    w1 = min(i1, off_idx + int(500e-9 / dt))

    v_lo, v_hi = _vge_levels(vge, w0, w1)
    vge_s = smooth(vge[w0:w1], dt, cfg.smoothing.detect_window_ns)
    ic_s = smooth(np.abs(ic[w0:w1]), dt, cfg.smoothing.detect_window_ns)

    v_90 = threshold_value(v_lo, v_hi, th.high_pct)
    i_2 = 0.02 * _icm(ic, w0, w1)

    i_start_local = crossing_index(vge_s, v_90, "falling", 0)
    if i_start_local is None:
        i_start_local = max(0, off_idx - w0)

    i_end_local = crossing_index(ic_s, i_2, "falling", i_start_local)
    if i_end_local is None:
        i_end_local = crossing_index(ic_s, i_2, "falling", i_start_local, last=True)
    if i_end_local is None:
        i_end_local = min(len(vge_s) - 1, i_start_local + int(350e-9 / dt))
    if i_end_local <= i_start_local + 5:
        i_end_local = min(len(vge_s) - 1, off_idx - w0 + int(300e-9 / dt))

    i_start = w0 + i_start_local
    i_end = w0 + i_end_local
    return IntegrationWindow(i_start, i_end, float(t[i_start]), float(t[i_end]))


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
    """开通 A：|Ic| 上升沿与 Ha 的第一个有效交点（跳过开通前小幅抖动穿越）。"""
    hold = max(3, int(25e-9 / dt))
    margin = 10.0
    for k in range(max(0, anchor), len(i_seg) - hold - 1):
        if i_seg[k] < ha_ic and i_seg[k + 1] >= ha_ic:
            if float(np.mean(i_seg[k + 1 : k + 1 + hold])) >= ha_ic + margin:
                return k
    i_start = crossing_index(i_seg, ha_ic, "rising", anchor)
    if i_start is None:
        di = max(float(i_top) - ha_ic, 1.0)
        i_start = crossing_index(
            i_seg, ha_ic + max(0.03 * di, 15.0), "rising", anchor
        )
    return int(i_start) if i_start is not None else max(0, anchor)


def _eoff_last_on_state_index(v_seg: np.ndarray, ha_v: float, v_top: float, end: int) -> int:
    """关断前最后一个低 Vce 平台样本（主抬升前），用于跳过早期噪声穿越。"""
    on_ceiling = ha_v + max(22.0, 0.04 * max(float(v_top) - ha_v, 1.0))
    last_on = 0
    for k in range(0, max(1, end + 1)):
        if v_seg[k] <= on_ceiling:
            last_on = k
    return int(last_on)


def _eoff_vce_ha_crossing_time(
    t_seg: np.ndarray,
    v_seg: np.ndarray,
    ha_v: float,
    i_lo: int,
    i_hi: int,
) -> float:
    """沿 [i_lo, i_hi] 线性插值 Vce 与 Ha 的交点时刻。"""
    i_lo = max(0, int(i_lo))
    i_hi = min(len(v_seg) - 1, int(i_hi))
    if i_hi <= i_lo:
        return float(t_seg[i_lo])
    v0 = float(v_seg[i_lo])
    v1 = float(v_seg[i_hi])
    if abs(v1 - v0) < 1e-30:
        return float(t_seg[i_lo])
    frac = float(np.clip((ha_v - v0) / (v1 - v0), 0.0, 1.0))
    return float(t_seg[i_lo] + frac * (t_seg[i_hi] - t_seg[i_lo]))


def _eoff_vce_ha_crossing_at_main_rise(
    t_seg: np.ndarray,
    v_seg: np.ndarray,
    ha_v: float,
    dt: float,
    v_top: float,
    search_span_ns: float = 350.0,
) -> tuple[int, float]:
    """关断 A：窗内主 Vce 抬升（最大 dV/dt）与 Ha 的上升穿越时刻。"""
    if len(t_seg) < 2:
        return 0, float(t_seg[0]) if len(t_seg) else 0.0

    t_lo = float(t_seg[0])
    # 搜索整个关断窗内 Vce<=on_hi 的最大 dV/dt 点（主抬升脚）。
    # 不能用 t_lo+固定 350ns 截断：下桥窗起点距实际抬升 >350ns 时，
    # 主抬升会被排除、best_k 落到导通态噪声上（A 偏早上百 ns）。
    # 抬升后 Vce 高位 (>on_hi) 已被下面的 continue 跳过，故全窗搜索安全。
    _ = search_span_ns
    t_hi = float(t_seg[-1])
    on_hi = ha_v + max(30.0, 0.04 * max(float(v_top) - ha_v, 1.0))

    # 主抬升定位：先找首个越过 50% (ha_v→v_top) 的样本（仅真实关断抬升能到达，
    # 导通态噪声尖峰幅度远不及），再在它前方局部窗口内取 Ha 的第一个上升穿越。
    # 这与示波器卡尺一致：A 卡在 Ha 水平线和 Vce 主上升沿的第一个交点。
    # 旧法「全窗 Vce<=on_hi 的最大 dV/dt」会被导通态噪声尖峰带偏到抬升前数百 ns
    # （尤其关断窗起点 off0 前移、纳入更多导通态噪声时）。
    mid = ha_v + 0.5 * max(float(v_top) - ha_v, 1.0)
    k_high: int | None = None
    for k in range(len(v_seg)):
        if float(t_seg[k]) > t_hi:
            break
        if float(v_seg[k]) >= mid:
            k_high = k
            break
    if k_high is not None:
        diffs = np.diff(t_seg)
        positive_diffs = diffs[diffs > 0.0]
        sample_dt = float(np.median(positive_diffs)) if len(positive_diffs) else float(dt)
        # t_seg 在 pipeline 中是秒，在 GUI 交互中是微秒；按采样间隔推断单位。
        pre_rise_span = 0.145 if sample_dt > 1e-7 else 145e-9
        t_near = float(t_seg[k_high]) - pre_rise_span
        for kk in range(0, max(0, k_high)):
            if float(t_seg[kk]) < t_near:
                continue
            y0, y1 = float(v_seg[kk]), float(v_seg[kk + 1])
            if y0 < ha_v <= y1 and y1 > y0:
                frac = float(np.clip((ha_v - y0) / (y1 - y0), 0.0, 1.0))
                t_cross = float(t_seg[kk] + frac * (t_seg[kk + 1] - t_seg[kk]))
                return int(kk), t_cross

        # 若局部窗口未找到 Ha 交点，回退到脚点附近插值。
        foot = k_high
        while foot > 0 and float(v_seg[foot - 1]) > on_hi:
            foot -= 1
        best_k = max(0, foot - 1)
    else:
        # 回退：窗内 Vce<=on_hi 的最大 dV/dt（保留旧行为）
        best_k = 0
        best_slope = -1.0
        for k in range(1, len(t_seg) - 1):
            if float(t_seg[k]) > t_hi:
                break
            if float(v_seg[k]) > on_hi:
                continue
            dt_k = float(t_seg[k + 1] - t_seg[k])
            if dt_k <= 0.0:
                continue
            slope = (float(v_seg[k + 1]) - float(v_seg[k])) / dt_k
            if slope > best_slope:
                best_slope = slope
                best_k = k

    # 仅在最大斜率点附近找 Ha 穿越（避免 lookback 随 dt 放大到数百点误取早期噪声）
    look = max(4, min(24, int(3e-9 / max(float(dt), 1e-12))))
    best_kk: int | None = None
    best_dist = len(v_seg)
    for kk in range(max(0, best_k - look), min(len(v_seg) - 1, best_k + look)):
        y0, y1 = float(v_seg[kk]), float(v_seg[kk + 1])
        if y0 < ha_v <= y1 and y1 > y0:
            dist = abs(kk - best_k)
            if dist < best_dist:
                best_dist = dist
                best_kk = kk
    if best_kk is not None:
        y0, y1 = float(v_seg[best_kk]), float(v_seg[best_kk + 1])
        frac = float(np.clip((ha_v - y0) / (y1 - y0), 0.0, 1.0))
        t_cross = float(t_seg[best_kk] + frac * (t_seg[best_kk + 1] - t_seg[best_kk]))
        return int(best_kk), t_cross

    j_hi = min(len(t_seg) - 1, best_k + look)
    j_lo = max(0, best_k - look)
    t_cross = _eoff_vce_ha_crossing_time(t_seg, v_seg, ha_v, j_lo, j_hi)
    return int(j_lo), t_cross


def _eoff_vce_rise_start_index(
    v_seg: np.ndarray,
    ha_v: float,
    anchor: int,
    dt: float,
    v_top: float,
    t_seg: np.ndarray | None = None,
) -> int:
    """关断 A 样本索引（与 _eoff_vce_ha_crossing_at_main_rise 一致）。"""
    _ = anchor
    if t_seg is None or len(t_seg) != len(v_seg):
        t_seg = np.arange(len(v_seg), dtype=np.float64) * float(dt)
    ix, _ = _eoff_vce_ha_crossing_at_main_rise(t_seg, v_seg, ha_v, dt, v_top)
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


def _eoff_ic_fall_start_index(
    i_seg: np.ndarray,
    hb: float,
    anchor: int,
    dt: float,
    i_top: float,
) -> int:
    """关断 B：|Ic| 主下降沿与 Hb 的第一个有效交点（仅抑制紧邻回穿）。"""
    hold = max(3, int(25e-9 / dt))
    bounce_tol = max(5.0, 0.08 * max(float(i_top) - hb, 1.0))
    for k in range(max(0, anchor), len(i_seg) - hold - 1):
        if i_seg[k] > hb and i_seg[k + 1] <= hb:
            if float(np.mean(i_seg[k + 1 : k + 1 + hold])) <= hb + bounce_tol:
                return k
    i_end = crossing_index(i_seg, hb, "falling", anchor)
    if i_end is None:
        di = max(float(i_top) - hb, 1.0)
        i_end = crossing_index(
            i_seg, hb + max(0.03 * di, 30.0), "falling", anchor
        )
    return int(i_end) if i_end is not None else max(anchor, 0)


def _eon_vce_hb_fall_start_index(
    v_seg: np.ndarray,
    hb: float,
    anchor: int,
    dt: float,
    v_top: float,
) -> int:
    """开通 B：Vce 主下降沿与 Hb 的第一个有效下降穿越（抑制拖尾振铃假交点）。"""
    hold = max(3, int(25e-9 / dt))
    bounce_tol = max(3.0, 0.015 * max(float(v_top) - float(hb), 1.0))
    sw_hi = max(float(hb) + 12.0, 0.06 * max(float(v_top), 1.0))
    for k in range(max(0, anchor), len(v_seg) - hold - 1):
        if float(np.max(v_seg[max(anchor, k - 8) : k + 1])) < sw_hi:
            continue
        y0, y1 = float(v_seg[k]), float(v_seg[k + 1])
        if y0 > float(hb) and y1 <= float(hb):
            if float(np.mean(v_seg[k + 1 : k + 1 + hold])) <= float(hb) + bounce_tol:
                return k
    i_end = crossing_index(v_seg, float(hb), "falling", anchor)
    if i_end is None:
        dv = max(float(v_top) - float(hb), 1.0)
        i_end = crossing_index(
            v_seg,
            float(hb) + max(0.02 * dv, 5.0),
            "falling",
            anchor,
        )
    return int(i_end) if i_end is not None else max(anchor, 0)


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
    A=Vce 与 Ha 上升穿越；B=|Ic| 与 Hb 下降穿越。
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

    i_start_local, t_start = _eoff_vce_ha_crossing_at_main_rise(
        t_sw, v_seg, ha_v, dt, float(v_top)
    )

    fall_anchor = max(i_start_local + 1, int(np.searchsorted(t_sw, t_start, side="left")))
    i_end_local = _eoff_ic_fall_start_index(
        i_seg, hb_a, fall_anchor, dt, float(i_top)
    )
    if i_end_local is None:
        i_end_local = min(len(i_seg) - 1, i_start_local + int(450e-9 / dt))
    if i_end_local <= i_start_local + 5:
        i_end_local = min(len(i_seg) - 1, i_start_local + int(350e-9 / dt))

    t_end = _eoff_crossing_time_us(t_sw, i_seg, i_end_local, hb_a, "falling")
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


def eon_window_iec(
    t: np.ndarray,
    vge: np.ndarray,
    ic: np.ndarray,
    vce: np.ndarray,
    vdc: float,
    i0: int,
    i1: int,
    on_idx: int,
    dt: float,
    cfg: AppConfig,
) -> IntegrationWindow:
    """IEC60747-9 Eon: t1=10% Vge↑, t2=2% Vce↓ (last Vce fall to on-state)."""
    th = cfg.thresholds
    w0 = max(i0, on_idx - int(80e-9 / dt))
    w1 = min(i1, on_idx + int(700e-9 / dt))

    v_lo, v_hi = _vge_levels(vge, w0, w1)
    vge_s = smooth(vge[w0:w1], dt, cfg.smoothing.detect_window_ns)
    vce_s = smooth(vce[w0:w1], dt, cfg.smoothing.detect_window_ns)

    v_10 = threshold_value(v_lo, v_hi, th.low_pct)
    vce_hi = float(np.max(vce[w0:w1]))
    vce_2 = vdc + 0.02 * max(vce_hi - vdc, 1.0)

    anchor = max(0, on_idx - w0)
    i_start_local = crossing_index(vge_s, v_10, "rising", anchor)
    if i_start_local is None:
        i_start_local = anchor

    i_end_local = crossing_index(vce_s, vce_2, "falling", i_start_local, last=True)
    if i_end_local is None:
        i_end_local = min(len(vge_s) - 1, i_start_local + int(500e-9 / dt))
    if i_end_local <= i_start_local + 5:
        i_end_local = min(len(vge_s) - 1, on_idx - w0 + int(450e-9 / dt))

    i_start = w0 + i_start_local
    i_end = w0 + i_end_local
    return IntegrationWindow(i_start, i_end, float(t[i_start]), float(t[i_end]))


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
    A=|Ic| 上升沿与 Ha 的第一个交点；B=Vce 下降沿与 Hb 的第一个交点。
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
    i_start_local = _eon_ic_rise_start_index(i_seg, ha_ic, anchor, dt, float(i_top))
    if i_start_local >= len(i_seg) - 2:
        i_start_local = max(0, min(len(i_seg) - 2, local_on))

    i_end_local = _eon_vce_hb_fall_start_index(
        v_seg, hb_v, i_start_local, dt, float(v_top)
    )
    if i_end_local <= i_start_local + 5:
        i_end_local = min(len(v_seg) - 1, i_start_local + int(350e-9 / dt))

    t_end = _eoff_crossing_time_us(t_sw, v_seg, i_end_local, hb_v, "falling")
    i_start = int(np.searchsorted(t, float(t_sw[i_start_local]), side="left"))
    i_end = int(np.searchsorted(t, t_end, side="left"))
    i_start = max(sw0, min(i_start, len(t) - 2))
    i_end = max(i_start + 1, min(i_end, len(t) - 1))
    return EnergyLossMarkers(
        float(ha_ic),
        float(hb_v),
        float(t_sw[i_start_local]),
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


def err_window_iec(
    t: np.ndarray,
    irr: np.ndarray,
    v_diode: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    cfg: AppConfig,
) -> IntegrationWindow:
    """IEC60747-9 Err: t1=10% Vd↑, t2=2% Irr↓ after peak."""
    th = cfg.thresholds
    irr_s = smooth(irr[i0:i1], dt, cfg.smoothing.detect_window_ns)
    vd_s = smooth(v_diode[i0:i1], dt, cfg.smoothing.detect_window_ns)

    irr_abs = np.abs(irr_s)
    irm = float(np.max(irr_abs)) if len(irr_abs) else 0.0
    if irm < 1.0:
        return IntegrationWindow(i0, i1, float(t[i0]), float(t[i1]))

    vdm = float(np.percentile(vd_s, 10))
    vmax = float(np.max(vd_s))
    v_10 = vdm + th.low_pct * max(vmax - vdm, 1.0)
    i_2 = 0.02 * irm

    peak_local = int(np.argmax(irr_abs))
    i_start_local = crossing_index(vd_s, v_10, "rising", 0, end=max(peak_local + 1, 10))
    if i_start_local is None:
        i_start_local = max(0, peak_local - int(80e-9 / dt))

    i_end_local = crossing_index(irr_abs, i_2, "falling", peak_local, last=True)
    if i_end_local is None:
        i_end_local = min(len(irr_s) - 1, peak_local + int(250e-9 / dt))
    if i_end_local <= i_start_local + 5:
        i_end_local = min(len(irr_s) - 1, i_start_local + int(200e-9 / dt))

    return IntegrationWindow(
        i0 + i_start_local,
        i0 + i_end_local,
        float(t[i0 + i_start_local]),
        float(t[i0 + i_end_local]),
    )


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


def _err_recovery_peak_index(seg_abs: np.ndarray, dt: float) -> int:
    """反向恢复主尖峰：跳过窗头已处于高电流的样点。"""
    n = len(seg_abs)
    if n < 8:
        return int(np.argmax(seg_abs))
    w = min(max(8, n // 4), int(100e-9 / max(dt, 1e-15)))
    j0 = int(np.argmin(seg_abs[:w])) if w >= 3 else 0
    return j0 + int(np.argmax(seg_abs[j0:]))


def _err_ha_post_peak_plateau(
    t: np.ndarray,
    irr_abs: np.ndarray,
    ipk: int,
    dt: float,
    search_end: int,
) -> float:
    """尖峰后震荡结束尾段 |Irr| 平台：峰后约 370ns 起取 600ns 窗 (max+min)/2。

    须在 reverse_recovery 段之外继续搜索（典型工况峰后 ~19µs 才进入平稳尾段）。
    """
    peak = float(irr_abs[ipk])
    wlen = max(5, int(600e-9 / max(dt, 1e-15)))
    settle = max(3, int(370e-9 / max(dt, 1e-15)))
    lo = ipk + settle
    hi = min(len(irr_abs) - wlen, int(search_end) - wlen + 1)
    if lo > hi:
        lo = max(ipk + 3, min(lo, len(irr_abs) - wlen - 1))
        hi = lo

    def _mid_range(block: np.ndarray) -> float:
        return 0.5 * (float(np.max(block)) + float(np.min(block)))

    sub = irr_abs[lo : lo + wlen]
    if len(sub) >= 3:
        return _mid_range(sub)

    tail = irr_abs[max(ipk, len(irr_abs) - wlen) :]
    return _mid_range(tail) if len(tail) else peak * 0.25


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
    ix = crossing_index(seg_abs, ha, "falling", ipk)
    if ix is not None:
        return int(ix), _err_interp_cross_time(t_seg, seg_abs, int(ix), ha)
    return ipk, float(t_seg[ipk])


def _err_v_rise_cross_hb(
    t_seg: np.ndarray,
    seg_v: np.ndarray,
    hb: float,
    ipk: int,
    dt: float,
) -> tuple[int, float]:
    """B：|Vd| 主抬升沿与 Hb 的上升穿越。

    尖峰前 Vd 仍处低平台（典型上桥）：取尖峰前最后一段有效穿越。
    尖峰前 |Vd| 已偏高（典型下桥）：取段内首次有效穿越，避免 B 贴在尖峰上。
    """
    seg_v = np.asarray(seg_v, dtype=np.float64)
    hold = max(3, int(20e-9 / max(dt, 1e-15)))
    v_hi = hb + max(30.0, 0.2 * max(float(np.max(seg_v[: ipk + 1])) - hb, 1.0))

    def _rising_cross_at(kk: int) -> bool:
        if kk + 1 >= len(seg_v):
            return False
        if not (seg_v[kk] < hb <= seg_v[kk + 1]):
            return False
        return float(np.max(seg_v[kk + 1 : min(len(seg_v), kk + 1 + hold)])) >= v_hi

    w_pre = max(5, int(32e-9 / max(dt, 1e-15)))
    pre_med = (
        float(np.median(seg_v[max(0, ipk - w_pre) : ipk])) if ipk > 0 else 0.0
    )
    v_pk = float(seg_v[ipk]) if ipk < len(seg_v) else pre_med
    if pre_med > hb + max(50.0, 0.25 * max(v_pk - hb, 1.0)):
        for kk in range(0, max(1, ipk)):
            if _rising_cross_at(kk):
                return kk, _err_interp_cross_time(t_seg, seg_v, kk, hb)

    lo = max(0, ipk - w_pre)
    hi = max(lo + 2, ipk - int(5e-9 / max(dt, 1e-15)))
    best_kk: int | None = None
    for kk in range(lo, hi):
        if _rising_cross_at(kk):
            best_kk = kk
    if best_kk is not None:
        return best_kk, _err_interp_cross_time(t_seg, seg_v, best_kk, hb)
    ix = crossing_index(seg_v, hb, "rising", lo)
    if ix is not None and int(ix) < ipk:
        return int(ix), _err_interp_cross_time(t_seg, seg_v, int(ix), hb)
    return max(0, ipk - 1), float(t_seg[max(0, ipk - 1)])


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


def _err_vd_rise_cross_hb_t(
    t: np.ndarray, vd: np.ndarray, hb: float, ipk_global: int, i0: int, dt: float
) -> float:
    """Vd 主抬升沿与 Hb（带符号）的上升穿越：主峰前最后一次有效穿 Hb 的脚。

    搜索窗以 IRM 为锚向左延伸，不得仅用 reverse_recovery 段起点截断（WH 等工况
    段起点常晚于真实抬升脚，否则会误落在段界上）。
    """
    _ = i0  # 保留参数以兼容调用方
    ipk_global = int(ipk_global)
    lo = max(0, ipk_global - int(800e-9 / max(dt, 1e-15)))
    hi = min(len(vd) - 2, ipk_global + int(50e-9 / max(dt, 1e-15)))
    if hi <= lo + 1:
        return float(t[min(ipk_global, len(t) - 1)])
    hold = max(3, int(20e-9 / max(dt, 1e-15)))
    v_hi = float(hb) + max(
        30.0, 0.15 * max(float(np.max(vd[lo : ipk_global + 1])) - float(hb), 1.0)
    )
    best_t: float | None = None
    for k in range(lo, min(ipk_global, hi)):
        y0, y1 = float(vd[k]), float(vd[k + 1])
        if y0 <= hb < y1:
            if float(np.max(vd[k + 1 : min(len(vd), k + 1 + hold)])) >= v_hi:
                best_t = _err_interp_cross_time(t, vd, k, hb)
    if best_t is not None:
        return best_t
    d = np.diff(vd[lo : hi + 1]) / np.maximum(np.diff(t[lo : hi + 1]), 1e-15)
    ks = lo + int(np.argmax(d))
    for k in range(min(ks, ipk_global), lo - 1, -1):
        y0, y1 = float(vd[k]), float(vd[k + 1])
        if y0 <= hb < y1:
            return _err_interp_cross_time(t, vd, k, hb)
    for k in range(lo, min(ipk_global, hi)):
        y0, y1 = float(vd[k]), float(vd[k + 1])
        if y0 <= hb < y1:
            return _err_interp_cross_time(t, vd, k, hb)
    return float(t[lo])


def _err_irr_fall_cross_ha_t(
    t: np.ndarray,
    irr: np.ndarray,
    ha: float,
    ipk_global: int,
    i_end: int,
    dt: float,
) -> float:
    """IRM 主峰后下降沿与 Ha 的首个下降穿越（秒）。

    上桥软恢复：Irr 为正、Ha 为尾段带符号平台时，示波器读数为 |Irr| 与 |Ha|，
    按幅值下降穿越；硬恢复/下桥负向过冲仍用带符号下降穿越。
    """
    k0 = max(0, int(ipk_global))
    k1 = max(k0 + 1, min(int(i_end), len(irr) - 1))
    peak = float(irr[k0]) if k0 < len(irr) else 0.0
    use_mag = peak > 0.0 and (
        float(ha) > 0.0 or (float(ha) < 0.0 and abs(peak) > 3.0 * abs(float(ha)))
    )
    if use_mag:
        lvl = abs(float(ha))
        for k in range(k0, k1):
            y0, y1 = abs(float(irr[k])), abs(float(irr[k + 1]))
            if y0 > lvl >= y1:
                return _err_interp_cross_time(
                    t, np.abs(np.asarray(irr, dtype=np.float64)), k, lvl
                )
    else:
        for k in range(k0, k1):
            y0, y1 = float(irr[k]), float(irr[k + 1])
            if y0 > float(ha) >= y1:
                return _err_interp_cross_time(t, irr, k, float(ha))
    t_seg = t[k0 : k1 + 1]
    seg_abs = np.abs(np.asarray(irr[k0 : k1 + 1], dtype=np.float64))
    lvl = abs(float(ha))
    if len(seg_abs) >= 4:
        _, t_cross = _err_ic_fall_cross_after_peak(
            t_seg, seg_abs, 0, lvl, dt
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
    Ha=尖峰下降沿震荡结束后的 |Irr| 平台；Hb=电压抬升前 Vd 平台；
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
    # Ha=恢复后稳定 Irr 平台 (max+min)/2（主峰后 400–800ns，带符号贴波形）
    ha = _err_window_mid(irr_full, t, tpk + 400e-9, tpk + 800e-9)
    # Hb=恢复前正向导通 Vd 平台 (max+min)/2（主峰前 200–600ns，带符号）
    hb_v = _err_window_mid(vd_full, t, tpk - 600e-9, tpk - 200e-9)
    i_fall_end = max(
        ipk_global + 2,
        min(
            int(i_search_end),
            ipk_global + int(800e-9 / max(dt, 1e-15)),
        ),
    )
    t_a_irr = _err_irr_fall_cross_ha_t(
        t, irr_full, ha, ipk_global, i_fall_end, dt
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
