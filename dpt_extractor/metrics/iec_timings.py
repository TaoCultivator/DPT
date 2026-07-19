from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.utils.signal import crossing_time, smooth, threshold_value


@dataclass(frozen=True)
class TurnOffTimingInstants:
    """IEC60747-9 / ZF 关断阈值穿越时刻（秒）。"""

    t_v90_s: float | None
    t_i90_s: float | None
    t_i10_s: float | None
    td_off_ns: float
    tf_ns: float
    toff_ns: float


@dataclass(frozen=True)
class TurnOnTimingInstants:
    """IEC60747-9 / ZF 开通阈值穿越时刻（秒）。"""

    t_v10_s: float | None
    t_i10_s: float | None
    t_i90_s: float | None
    td_on_ns: float
    tr_ns: float
    ton_ns: float


def _plateau_ic(ic: np.ndarray, i0: int, i1: int) -> float:
    return float(np.percentile(np.abs(ic[i0:i1]), 95))


def turn_off_timing_instants(
    t: np.ndarray,
    vge: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    off_idx: int,
    dt: float,
    cfg: AppConfig,
    pulse1_on: int | None = None,
    pulse2_on: int | None = None,
) -> TurnOffTimingInstants:
    """
    IEC60747-9 / ZF 关断时间：
    Td_off = 90%Vge↓ → 90%Ic↓，Tf = 90%Ic↓ → 10%Ic↓，Toff = 90%Vge↓ → 10%Ic↓。
    故 Toff = Td_off + Tf。在 Vge 下降窗内搜穿越，Ic 穿越在 Vge 90% 之后顺序查找。
    """
    th = cfg.thresholds
    if pulse1_on is not None and pulse2_on is not None:
        win = vge_fall_window_indices(
            t, vge, i0, i1, pulse1_on, off_idx, pulse2_on, dt, cfg
        )
        if win is not None:
            w0, w1 = win
        else:
            w0 = max(i0, off_idx - int(300e-9 / dt))
            w1 = min(i1, off_idx + int(450e-9 / dt))
    else:
        w0 = max(i0, off_idx - int(300e-9 / dt))
        w1 = min(i1, off_idx + int(450e-9 / dt))

    # Vge 下降窗止于 off_idx（栅极电气关断），适合估计电平与 Vge 90% 穿越；
    # 但 Ic 电流拖尾可能延续到 off_idx 之后（如 WH 工况）。若用同一窗找 Ic 90/10%，
    # t_i10 会落在窗外 → Tf=0、Toff 漏掉电流下降段。故 Ic 穿越窗延伸到 off_idx 之后。
    w1_vge = w1
    w1 = min(i1, max(w1, off_idx + int(450e-9 / dt)))

    if w1 <= w0 + 5:
        return TurnOffTimingInstants(None, None, None, 0.0, 0.0, 0.0)

    ts = t[w0 : w1 + 1]
    vge_s = smooth(vge[w0 : w1 + 1], dt, cfg.smoothing.detect_window_ns)
    ic_s = smooth(np.abs(ic[w0 : w1 + 1]), dt, cfg.smoothing.detect_window_ns)

    if pulse1_on is not None:
        icm = turn_off_ic_top(ic, pulse1_on, off_idx, w0, dt)
    else:
        icm = _plateau_ic(ic, w0, w1_vge)

    # 电平用原 Vge 下降窗 [w0, w1_vge] 估计，保持既有（UH）阈值与结果不变
    v_lo, v_hi = float(np.percentile(vge[w0 : w1_vge + 1], 5)), float(
        np.percentile(vge[w0 : w1_vge + 1], 95)
    )
    v_90 = threshold_value(v_lo, v_hi, th.high_pct)
    i_90 = th.high_pct * icm
    i_10 = th.low_pct * icm

    t_v90 = crossing_time(ts, vge_s, v_90, "falling", start=0)
    if t_v90 is None:
        return TurnOffTimingInstants(None, None, None, 0.0, 0.0, 0.0)

    lv = int(np.searchsorted(ts, t_v90, side="left"))
    lv = max(0, min(lv, len(ts) - 2))
    t_i90 = crossing_time(ts, ic_s, i_90, "falling", start=lv)
    if t_i90 is None:
        return TurnOffTimingInstants(t_v90, None, None, 0.0, 0.0, 0.0)

    li = int(np.searchsorted(ts, t_i90, side="left"))
    li = max(lv, min(li, len(ts) - 2))
    t_i10 = crossing_time(ts, ic_s, i_10, "falling", start=li)
    if t_i10 is None:
        td_off = max(0.0, (t_i90 - t_v90) * 1e9)
        return TurnOffTimingInstants(t_v90, t_i90, None, td_off, 0.0, td_off)

    td_off = max(0.0, (t_i90 - t_v90) * 1e9)
    tf = max(0.0, (t_i10 - t_i90) * 1e9)
    toff = max(0.0, (t_i10 - t_v90) * 1e9)
    return TurnOffTimingInstants(t_v90, t_i90, t_i10, td_off, tf, toff)


def turn_off_timings(
    t: np.ndarray,
    vge: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    off_idx: int,
    dt: float,
    cfg: AppConfig,
    pulse1_on: int | None = None,
    pulse2_on: int | None = None,
) -> tuple[float, float, float]:
    inst = turn_off_timing_instants(
        t, vge, ic, i0, i1, off_idx, dt, cfg, pulse1_on, pulse2_on
    )
    return inst.td_off_ns, inst.tf_ns, inst.toff_ns


def vge_fall_window_indices(
    t: np.ndarray,
    vge: np.ndarray,
    _i0: int,
    _i1: int,
    pulse1_on: int,
    off_idx: int,
    pulse2_on: int,
    dt: float,
    cfg: AppConfig,
) -> tuple[int, int] | None:
    """
    第一脉冲关断：栅极从高电平开始回落到「关断完成」时刻之间的区间。

    `off_idx` 须为 `PulseDetector` 给出的 **pulse1_off**（脉冲 1 末尾、Vge 90%→10%
    下降沿扫到的位置），近似示波器「栅极已关断」一侧光标，而不是沿的起点。

    起点：在 [pulse1_on, pulse1_off] 内用与工况一致的高/低参考电平，取 **首次**
    v_98 / v_95 / v_90 的下降穿越（栅极开始关断）。终点：**t[off_idx]**（含该点）。

    若仍用「首次 v_10 穿越」作终点，会远早于真实关断完成，漏掉米勒段附近的最大总电流
    （例如 WH 样例约 794A vs 示波器卡窗约 801A）。
    """
    th = cfg.thresholds
    n = len(t)
    p1w = max(10, off_idx - pulse1_on)
    gap12 = max(10, pulse2_on - off_idx)
    pre_hi = max(int(50e-9 / dt), int(0.03 * p1w))
    post_lo = max(int(80e-9 / dt), int(0.06 * gap12))
    # 导通段末端估计 Vge_on（高电平）
    hi0 = max(0, min(pulse1_on, n - 2))
    hi1 = max(hi0 + 20, min(off_idx - pre_hi, n - 1))
    if hi1 <= hi0 + 5:
        hi1 = max(hi0 + 20, min(off_idx - int(15e-9 / dt), n - 1))
    if hi1 <= hi0 + 5:
        return None
    v_hi = float(np.percentile(vge[hi0:hi1], 95))

    # 关断后截止段估计 Vge_off（低电平）
    if pulse2_on <= off_idx:
        lo0 = min(n - 1, max(off_idx + int(150e-9 / dt), hi1 + 10))
        lo1 = max(lo0 + 20, min(off_idx + int(2e-6 / dt), n - 1))
    else:
        lo0 = min(n - 1, max(off_idx + int(150e-9 / dt), hi1 + 10))
        lo1 = max(lo0 + 20, min(pulse2_on - post_lo, n - 1))
    if lo1 <= lo0 + 5:
        return None
    v_lo = float(np.percentile(vge[lo0:lo1], 5))

    span = v_hi - v_lo
    if span < 1.0:
        return None
    v_98 = threshold_value(v_lo, v_hi, 0.98)
    v_95 = threshold_value(v_lo, v_hi, 0.95)
    v_90 = threshold_value(v_lo, v_hi, th.high_pct)

    fall_span = max(int(1.2e-6 / dt), int(0.25 * p1w), int(0.5 * gap12))
    w0 = max(0, pulse1_on, off_idx - fall_span)
    w1 = min(n - 1, off_idx)
    if w1 <= w0 + 10:
        return None
    ts = t[w0 : w1 + 1]
    vge_s = smooth(vge[w0 : w1 + 1], dt, cfg.smoothing.detect_window_ns)

    t_98 = crossing_time(ts, vge_s, v_98, "falling", start=0)
    t_95 = crossing_time(ts, vge_s, v_95, "falling", start=0)
    t_90 = crossing_time(ts, vge_s, v_90, "falling", start=0)
    t_starts = [x for x in (t_98, t_95, t_90) if x is not None]
    if t_starts:
        t_start = float(min(t_starts))
    else:
        t_start = float(t[off_idx] - min(600e-9, (t[off_idx] - t[w0]) * 0.9))

    t_end = float(t[off_idx])
    if t_end <= t_start:
        return None

    i_start = int(np.searchsorted(t, t_start, side="left"))
    i_end = int(off_idx)
    i_start = max(0, min(i_start, n - 2))
    i_end = max(i_start + 1, min(i_end, n - 1))
    if i_end <= i_start:
        return None
    return i_start, i_end


def vge_rise_window_indices(
    t: np.ndarray,
    vge: np.ndarray,
    _i0: int,
    _i1: int,
    pulse1_off: int,
    on_idx: int,
    pulse2_off: int,
    dt: float,
    cfg: AppConfig,
) -> tuple[int, int] | None:
    """
    第二脉冲开通：栅极从低电平上升到「开通完成」时刻（与开通 di/dt、dv/dt 同窗）。

    对称于关断 Vge 下降窗：起点为首次 v_98/v_95/v_90 上升穿越，终点为 pulse2_on（开通沿结束）。
    """
    th = cfg.thresholds
    n = len(t)
    same_pulse = on_idx <= pulse1_off
    gap12 = max(10, on_idx - pulse1_off) if not same_pulse else max(10, on_idx)
    p2w = max(10, pulse2_off - on_idx)
    pre_lo = max(int(50e-9 / dt), int(0.05 * gap12))
    post_hi = max(int(80e-9 / dt), int(0.06 * p2w))
    if same_pulse:
        lo0 = max(0, on_idx - int(500e-9 / dt))
        lo1 = max(lo0 + 20, min(on_idx - pre_lo, n - 1))
    else:
        lo0 = min(n - 1, max(pulse1_off + int(150e-9 / dt), 0))
        lo1 = max(lo0 + 20, min(on_idx - pre_lo, n - 1))
    if lo1 <= lo0 + 5:
        lo1 = max(lo0 + 20, min(on_idx - int(15e-9 / dt), n - 1))
    if lo1 <= lo0 + 5:
        return None
    v_lo = float(np.percentile(vge[lo0:lo1], 5))

    hi0 = min(n - 1, max(on_idx + int(150e-9 / dt), lo1 + 10))
    hi1 = max(hi0 + 20, min(pulse2_off - post_hi, n - 1))
    if hi1 <= hi0 + 5:
        return None
    v_hi = float(np.percentile(vge[hi0:hi1], 95))

    span = v_hi - v_lo
    if span < 1.0:
        return None
    v_98 = threshold_value(v_lo, v_hi, 0.98)
    v_95 = threshold_value(v_lo, v_hi, 0.95)
    v_90 = threshold_value(v_lo, v_hi, th.high_pct)

    rise_span = max(int(1.2e-6 / dt), int(0.25 * gap12), int(0.5 * p2w))
    if same_pulse:
        w0 = max(0, on_idx - rise_span)
    else:
        w0 = max(0, pulse1_off, on_idx - rise_span)
    w1 = min(n - 1, on_idx)
    if w1 <= w0 + 10:
        return None
    ts = t[w0 : w1 + 1]
    vge_s = smooth(vge[w0 : w1 + 1], dt, cfg.smoothing.detect_window_ns)

    t_98 = crossing_time(ts, vge_s, v_98, "rising", start=0)
    t_95 = crossing_time(ts, vge_s, v_95, "rising", start=0)
    t_90 = crossing_time(ts, vge_s, v_90, "rising", start=0)
    t_starts = [x for x in (t_98, t_95, t_90) if x is not None]
    if t_starts:
        t_start = float(min(t_starts))
    else:
        t_start = float(t[on_idx] - min(600e-9, (t[on_idx] - t[w0]) * 0.9))

    t_end = float(t[on_idx])
    if t_end <= t_start:
        return None

    i_start = int(np.searchsorted(t, t_start, side="left"))
    i_end = int(on_idx)
    i_start = max(0, min(i_start, n - 2))
    i_end = max(i_start + 1, min(i_end, n - 1))
    if i_end <= i_start:
        return None
    return i_start, i_end


def turn_off_ic_top(
    ic: np.ndarray,
    pulse1_on: int,
    off_idx: int,
    fall_start: int,
    dt: float,
) -> float:
    """
    关断前电流 Top（100% Ic 平台），非切换过程中尖峰。

    在 Vge 开始下降、电流尚未明显跌落前的导通平台取 |Ic| 分位数作为 Icm 基准。
    """
    n = len(ic)
    plat1 = max(pulse1_on + 10, min(off_idx - int(40e-9 / dt), fall_start, n - 1))
    plat0 = max(pulse1_on, plat1 - int(250e-9 / dt))
    if plat1 <= plat0 + 5:
        plat0 = max(0, pulse1_on)
        plat1 = max(plat0 + 10, min(fall_start, off_idx))
    if plat1 <= plat0:
        return float(np.max(np.abs(ic[max(0, pulse1_on) : max(pulse1_on + 1, off_idx)])))
    return float(np.percentile(np.abs(ic[plat0:plat1]), 95))


def turn_on_ic_top(
    ic: np.ndarray,
    on_idx: int,
    pulse2_off: int,
    dt: float,
) -> float:
    """
    开通电流 Top（100% Ic 平台），非开通过冲峰值。

    取第二脉冲开通后、关断前的导通平台 |Ic| 分位数作为开通 di/dt 的 Icm 基准。
    """
    n = len(ic)
    plat0 = min(n - 1, max(on_idx + int(120e-9 / dt), 0))
    plat1 = max(plat0 + 20, min(pulse2_off - int(80e-9 / dt), n - 1))
    if plat1 <= plat0 + 5:
        plat0 = min(n - 2, max(on_idx + int(40e-9 / dt), 0))
        plat1 = max(plat0 + 10, min(pulse2_off, n - 1))
    if plat1 <= plat0:
        seg0 = max(0, on_idx)
        seg1 = max(seg0 + 1, min(pulse2_off, n - 1))
        return float(np.percentile(np.abs(ic[seg0:seg1]), 90))
    return float(np.percentile(np.abs(ic[plat0:plat1]), 95))


def turn_on_vce_top_from_ic_rise(
    ic: np.ndarray,
    vce: np.ndarray,
    on_idx: int,
    pulse2_off: int,
    dt: float,
) -> float:
    """
    开通电压 Top（100% Vce）取样：
    以“总电流从近零开始抬升”的时刻为右端，向左取 200ns 窗口估计 Vce Top。
    """
    n = len(ic)
    if n == 0:
        return 0.0
    i0 = max(0, min(on_idx, n - 2))
    i1 = max(i0 + 2, min(pulse2_off, n - 1))
    abs_ic = np.abs(ic)

    pre0 = max(0, i0 - int(300e-9 / dt))
    pre1 = max(pre0 + 5, i0)
    if pre1 <= pre0:
        pre0, pre1 = 0, min(max(5, i0), n - 1)
    ic_base = float(np.percentile(abs_ic[pre0:pre1], 50)) if pre1 > pre0 else 0.0

    look1 = min(n - 1, i0 + int(600e-9 / dt))
    ic_ref = (
        float(np.percentile(abs_ic[i0:look1], 95)) if look1 > i0 + 5 else float(np.max(abs_ic))
    )
    rise_th = ic_base + max(0.02 * max(ic_ref, 1.0), 3.0)

    rise_idx = i0
    for k in range(i0, i1):
        if abs_ic[k] >= rise_th:
            rise_idx = k
            break

    w1 = max(1, rise_idx)
    w0 = max(0, w1 - int(200e-9 / dt))
    if w1 <= w0 + 5:
        w0 = max(0, i0 - int(200e-9 / dt))
        w1 = max(w0 + 6, i0)
    if w1 <= w0:
        return float(np.percentile(vce[max(0, i0 - 20) : max(i0, 1)], 95))
    return float(np.percentile(vce[w0:w1], 95))


def turn_off_ic_fall_window(
    t: np.ndarray,
    vge: np.ndarray,
    i0: int,
    i1: int,
    pulse1_on: int,
    off_idx: int,
    pulse2_on: int,
    dt: float,
    cfg: AppConfig,
) -> tuple[int, int] | None:
    """第一脉冲关断：Vge 下降沿时间窗（与 Ic_off_max、关断 di/dt 共用）。"""
    return vge_fall_window_indices(
        t, vge, i0, i1, pulse1_on, off_idx, pulse2_on, dt, cfg
    )


def ic_off_max_in_vge_fall_window(
    t: np.ndarray,
    vge: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    pulse1_on: int,
    off_idx: int,
    pulse2_on: int,
    dt: float,
    cfg: AppConfig,
) -> float:
    """关断过程中，Vge 高→低下降沿区间内 |Ic| 最大值。"""
    win = turn_off_ic_fall_window(
        t, vge, i0, i1, pulse1_on, off_idx, pulse2_on, dt, cfg
    )
    if win is None:
        return float(np.max(np.abs(ic[i0:i1])))
    a, b = win
    if b <= a:
        return float(np.max(np.abs(ic[i0:i1])))
    return float(np.max(np.abs(ic[a : b + 1])))


def turn_on_ic_rise_window(
    t: np.ndarray,
    vge: np.ndarray,
    i0: int,
    i1: int,
    pulse1_off: int,
    on_idx: int,
    pulse2_off: int,
    dt: float,
    cfg: AppConfig,
) -> tuple[int, int] | None:
    """第二脉冲开通：Vge 上升沿时间窗（与开通 di/dt、dv/dt 共用）。"""
    return vge_rise_window_indices(
        t, vge, i0, i1, pulse1_off, on_idx, pulse2_off, dt, cfg
    )


def ic_stats_in_window(
    ic: np.ndarray, i0: int, i1: int
) -> tuple[float, float]:
    """返回 (窗内 |Ic| 峰值 Icm, 平台 Ic 95% 分位)。"""
    seg = np.abs(ic[i0 : i1 + 1])
    if len(seg) == 0:
        return 0.0, 0.0
    return float(np.max(seg)), float(np.percentile(seg, 95))


def turn_on_timing_instants(
    t: np.ndarray,
    vge: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    on_idx: int,
    dt: float,
    cfg: AppConfig,
    *,
    pulse2_off: int | None = None,
) -> TurnOnTimingInstants:
    """Td_on (10%Vge→10%Ic), Tr (10%Ic→90%Ic), Ton (10%Vge→90%Ic)."""
    th = cfg.thresholds
    w0 = max(i0, on_idx - int(80e-9 / dt))
    w1 = min(i1, on_idx + int(500e-9 / dt))
    if w1 <= w0 + 5:
        return TurnOnTimingInstants(None, None, None, 0.0, 0.0, 0.0)

    ts = t[w0:w1]
    vge_s = smooth(vge[w0:w1], dt, cfg.smoothing.detect_window_ns)
    ic_s = smooth(np.abs(ic[w0:w1]), dt, cfg.smoothing.detect_window_ns)

    icm = _plateau_ic(ic, w0, w1)
    v_lo, v_hi = float(np.percentile(vge[w0:w1], 5)), float(np.percentile(vge[w0:w1], 95))

    v_10 = threshold_value(v_lo, v_hi, th.low_pct)
    i_10 = th.low_pct * icm
    i_90 = th.high_pct * icm

    t_v10 = crossing_time(ts, vge_s, v_10, "rising")
    t_i10 = crossing_time(ts, ic_s, i_10, "rising")
    start_i90 = 0
    if t_i10 is not None:
        start_i90 = int(np.searchsorted(ts, t_i10, side="left"))
        start_i90 = max(0, min(start_i90, len(ts) - 2))
    t_i90 = crossing_time(ts, ic_s, i_90, "rising", start=start_i90)

    # 保留历史 500 ns 快速路径。慢开通样例可能尚未在该窗口内到达稳定
    # 导通平台，导致局部 95% 分位被误当作 Icm，甚至令 10% 阈值低于
    # 开通前电流。仅当旧路径缺少任一 Ic 交点时，才用第二脉冲稳定平台
    # 作为 Icm 并扩展搜索到 pulse2_off；这样不会漂移原本可正常测量的样例。
    if (
        (t_i10 is None or t_i90 is None)
        and pulse2_off is not None
        and int(pulse2_off) > on_idx + 5
    ):
        extended_end = min(len(t), max(w1, int(pulse2_off)))
        if extended_end > w0 + 5:
            stable_icm = turn_on_ic_top(ic, on_idx, int(pulse2_off), dt)
            if np.isfinite(stable_icm) and stable_icm > 0.0:
                extended_ts = t[w0:extended_end]
                extended_ic = smooth(
                    np.abs(ic[w0:extended_end]),
                    dt,
                    cfg.smoothing.detect_window_ns,
                )
                fallback_i10 = crossing_time(
                    extended_ts,
                    extended_ic,
                    th.low_pct * stable_icm,
                    "rising",
                )
                fallback_i90 = None
                if fallback_i10 is not None:
                    fallback_start_i90 = int(
                        np.searchsorted(extended_ts, fallback_i10, side="left")
                    )
                    fallback_start_i90 = max(
                        0, min(fallback_start_i90, len(extended_ts) - 2)
                    )
                    fallback_i90 = crossing_time(
                        extended_ts,
                        extended_ic,
                        th.high_pct * stable_icm,
                        "rising",
                        start=fallback_start_i90,
                    )
                if (
                    fallback_i10 is not None
                    and fallback_i90 is not None
                    and fallback_i90 > fallback_i10
                ):
                    t_i10 = fallback_i10
                    t_i90 = fallback_i90

    # Ic10/Ic90 describe one physical rising edge and therefore form an atomic
    # ordered pair.  Keeping only Ic90 (or only Ic10) lets Ton/Td_on/Tr borrow
    # endpoints from different events and leaves a plausible number with no
    # valid cursor pair.  Fail closed instead; the pipeline marks the affected
    # cards unavailable so GUI/report cannot present half a measurement.
    if t_i10 is None or t_i90 is None or t_i90 <= t_i10:
        t_i10 = None
        t_i90 = None

    # IEC60747-9 / ZF：Td_on=10%Vge→10%Icm，Tr=10%Icm→90%Icm，Ton=10%Vge→90%Icm ⇒ Ton=Td_on+Tr
    td_on = (
        abs(t_i10 - t_v10) * 1e9
        if t_v10 is not None and t_i10 is not None
        else 0.0
    )
    tr = (
        abs(t_i90 - t_i10) * 1e9
        if t_i10 is not None and t_i90 is not None
        else 0.0
    )
    ton = (
        abs(t_i90 - t_v10) * 1e9
        if t_v10 is not None and t_i90 is not None
        else 0.0
    )
    return TurnOnTimingInstants(t_v10, t_i10, t_i90, td_on, tr, ton)


def turn_on_timings(
    t: np.ndarray,
    vge: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    on_idx: int,
    dt: float,
    cfg: AppConfig,
    *,
    pulse2_off: int | None = None,
) -> tuple[float, float, float]:
    inst = turn_on_timing_instants(
        t,
        vge,
        ic,
        i0,
        i1,
        on_idx,
        dt,
        cfg,
        pulse2_off=pulse2_off,
    )
    return inst.td_on_ns, inst.tr_ns, inst.ton_ns


def reverse_recovery_trr(
    t: np.ndarray,
    irr: np.ndarray,
    v_diode: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    cfg: AppConfig,
    *,
    rr0: int | None = None,
    rr1: int | None = None,
    on_edge: int | None = None,
    pulse2_off: int | None = None,
) -> float:
    """
    Trr = B - A（反向恢复主峰到峰后恢复稳定平台中线的时间宽度）。

    自动结果与 GUI 默认卡尺共用同一 Ha/Hb/A/B 测量上下文；A/B
    均为原始带符号 Irr 与恢复稳定平台中线的真实首交点。
    """
    _ = v_diode, dt, cfg
    if i1 <= i0 + 5:
        return 0.0

    from dpt_extractor.metrics.irr_measure import (
        default_irr_trr_measure,
        measure_irr_trr,
    )

    if rr0 is not None and rr1 is not None and on_edge is not None:
        marker = default_irr_trr_measure(
            t,
            irr,
            rr0,
            rr1,
            on_edge,
            i0,
            i1,
            pulse2_off=pulse2_off,
        )
    else:
        marker = measure_irr_trr(t, irr, i0, i1, i_fall_end=i1)
    if marker is None:
        return 0.0
    return float(marker.trr_ns)
