"""反向恢复 Irr / Trr 示波器卡尺口径（Ha 参考线 + 尖峰 Hb）。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class IrrTrrMeasure:
    """Irr=Hb 处尖峰电流；Trr=(B−A) 在 Ha 上的两交点间隔。"""

    ha: float
    hb: float
    ta_s: float
    tb_s: float
    irr: float
    trr_ns: float
    peak_idx: int


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
    """IRM 主峰：正向主瓣占优时用 argmax(Irr)，否则用 Err 定向主峰。"""
    from dpt_extractor.metrics.iec_windows import err_recovery_peak_index

    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 3:
        return int(np.argmax(np.abs(seg))) if len(seg) else 0
    pos_max = float(np.max(seg))
    neg_min = float(np.min(seg))
    if pos_max >= abs(neg_min):
        return int(np.argmax(seg))
    return err_recovery_peak_index(seg, dt)


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
    j_lo = _lobe_valley_before_peak(seg, ipk)
    j_on = _plateau_end_before_spike(seg, ipk)
    jf = min(len(seg) - 2, j_fall_end if j_fall_end is not None else len(seg) - 2)

    # A：主瓣上升沿与 Ha 的第一个上升穿越（从谷底起搜，勿用 j_on 以免跳过抬升脚前的首交点）
    ja: int | None = None
    search_lo = max(0, j_lo)
    for j in range(search_lo, ipk):
        y1, y2 = float(seg[j]), float(seg[j + 1])
        if y1 <= level_f < y2 or (
            (y1 - level_f) * (y2 - level_f) <= 0.0 and y2 > y1 and abs(y2 - y1) > 1e-12
        ):
            ja = j
            break
    if ja is None:
        for j in range(search_lo, ipk):
            y1, y2 = float(seg[j]), float(seg[j + 1])
            if (y1 - level_f) * (y2 - level_f) <= 0.0 and y2 > y1:
                ja = j
                break

    # B：尖峰下降沿与 Ha 的第一个下降穿越
    jb: int | None = None
    for j in range(ipk, jf):
        y1, y2 = float(seg[j]), float(seg[j + 1])
        if y1 >= y2 and y1 > level_f >= y2:
            jb = j
            break
    if jb is None and peak > max(5.0, 3.0 * abs(level_f)):
        lvl = abs(level_f)
        for j in range(ipk, jf):
            y1, y2 = abs(float(seg[j])), abs(float(seg[j + 1]))
            if float(seg[j]) >= float(seg[j + 1]) and y1 > lvl >= y2:
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
    if float(seg[ipk]) > 0.0 and level <= 0.0 and jb is not None:
        tb = _interp_cross_time(ts, np.abs(seg), jb, abs(level))
    else:
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
) -> IrrTrrMeasure | None:
    """
    在 [i0,i1] 内识别反向恢复主瓣：
    - Ha：脉冲前稳态电流（参考线，可外部指定）
    - Hb：主瓣尖峰电流（Irr 读数）
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

    level = float(ha) if ha is not None else _default_ha(seg, ipk)
    hb = float(seg[ipk])
    irr_val = abs(hb)

    if i_fall_end is None:
        i_fall_end = min(len(t) - 1, i0 + ipk + int(600e-9 / max(dt, 1e-15)))
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
    )
