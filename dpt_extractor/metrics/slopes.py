from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.utils.signal import (
    crossing_time,
    max_slope_filtered,
    slope_between_crossings,
    threshold_value,
)


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


def _didt_fall_robust(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    base_a: float,
    top_a: float,
    pct_a: float,
    pct_b: float,
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
    seg_y = np.abs(ic[i0 : i1 + 1].astype(np.float64))
    if len(seg_t) < 2:
        return None
    start = max(0, int(np.argmax(seg_y)) - 1)
    t_lo = crossing_time(seg_t, seg_y, th_lo, "falling", start=start)
    if t_lo is None:
        return None
    local = int(np.searchsorted(seg_t, t_lo, side="left"))
    local = max(1, min(local, len(seg_y) - 1))
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
) -> DidtCrossingResult:
    """在 [i0,i1] 内按 Base–Top 电流跨度（|Ic|）计算 di/dt 穿越。"""
    if edge == "fall":
        robust = _didt_fall_robust(t, ic, i0, i1, base_a, top_a, pct_a, pct_b)
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
        use_abs=True,
    )
    return DidtCrossingResult(
        float(r.dvdt), r.t_pct_a_s, r.t_pct_b_s, r.th_a, r.th_b
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
