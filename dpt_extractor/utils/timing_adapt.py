"""自适应时间窗尺度：按脉冲宽度/沿间隔伸缩搜索范围，不改变指标计算公式。"""

from __future__ import annotations

import numpy as np


def samples_from_ns(ns: float, dt: float) -> int:
    return max(1, int(ns * 1e-9 / dt))


def adaptive_lookback_samples(
    anchor: int,
    pulse_start: int | None,
    dt: float,
    cfg_ns: float,
    *,
    max_us: float = 4.0,
    frac_of_interval: float = 0.12,
    min_ns: float = 200.0,
) -> int:
    """关断/开通沿前向左搜索长度：配置值、脉冲宽度比例、上限三者取合理值。"""
    base = samples_from_ns(cfg_ns, dt)
    floor = samples_from_ns(min_ns, dt)
    cap = int(max_us * 1e-6 / dt)
    n = base
    if pulse_start is not None and anchor > pulse_start + 10:
        n = max(n, int(frac_of_interval * (anchor - pulse_start)))
    return min(cap, max(floor, n))


def adaptive_forward_samples(
    anchor: int,
    pulse_end: int | None,
    dt: float,
    cfg_ns: float,
    *,
    max_us: float = 2.0,
    frac_of_interval: float = 0.08,
    min_ns: float = 200.0,
) -> int:
    base = samples_from_ns(cfg_ns, dt)
    floor = samples_from_ns(min_ns, dt)
    cap = int(max_us * 1e-6 / dt)
    n = base
    if pulse_end is not None and pulse_end > anchor + 10:
        n = max(n, int(frac_of_interval * (pulse_end - anchor)))
    return min(cap, max(floor, n))


def _dominant_low_plateau_mid(
    block: np.ndarray, rough_base: float, v_top: float
) -> float | None:
    """Most populated low-voltage shelf in a pre-rise block, as (max+min)/2."""
    arr = np.asarray(block, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if len(arr) < 12:
        return None
    span = max(float(v_top) - float(rough_base), 1.0)
    low_ceiling = float(rough_base) + 0.15 * span
    arr = arr[arr <= low_ceiling]
    if len(arr) < 12:
        return None
    bin_w = max(1.0, min(5.0, 0.003 * span))
    lo = float(np.floor(float(np.min(arr)) / bin_w) * bin_w)
    hi = float(np.ceil(float(np.max(arr)) / bin_w) * bin_w + bin_w)
    edges = np.arange(lo, hi + 0.5 * bin_w, bin_w, dtype=np.float64)
    if len(edges) < 2:
        return None
    hist, edges = np.histogram(arr, bins=edges)
    if len(hist) == 0 or int(np.max(hist)) < max(12, int(0.18 * len(arr))):
        return None
    k = int(np.argmax(hist))
    left = float(edges[k])
    right = float(edges[k + 1])
    if k == len(hist) - 1:
        cluster = arr[(arr >= left) & (arr <= right)]
    else:
        cluster = arr[(arr >= left) & (arr < right)]
    if len(cluster) < 3:
        return None
    return 0.5 * (float(np.max(cluster)) + float(np.min(cluster)))


def _refined_turn_off_vce_base(
    vce: np.ndarray,
    w0: int,
    w1: int,
    i0: int,
    dt: float,
    rough_base: float,
    v_top: float,
) -> float:
    """Prefer the stable on-state Vce shelf before the main rise over isolated lows."""
    sw0 = max(int(w0), int(i0))
    if w1 <= sw0 + 16:
        return float(rough_base)
    seg = vce[sw0 : w1 + 1].astype(np.float64)
    span = max(float(v_top) - float(rough_base), 1.0)
    mid = float(rough_base) + 0.5 * span
    k_high: int | None = None
    for k, value in enumerate(seg):
        if float(value) >= mid:
            k_high = int(k)
            break
    if k_high is None:
        return float(rough_base)

    rise_g = sw0 + k_high
    base_lo = max(sw0, rise_g - samples_from_ns(350.0, dt))
    base_hi = max(base_lo + 3, rise_g - samples_from_ns(80.0, dt))
    block = vce[base_lo:base_hi].astype(np.float64)
    candidate = _dominant_low_plateau_mid(block, rough_base, v_top)
    if candidate is None:
        return float(rough_base)
    if candidate > float(rough_base) + max(2.0, 0.003 * span):
        return float(candidate)
    return float(rough_base)


def scope_turn_off_bases(
    vce: np.ndarray,
    ic: np.ndarray,
    off_idx: int,
    i0: int,
    i1: int,
    dt: float,
    pre_ns: float,
    pulse1_on: int | None = None,
) -> tuple[float, float, float, float, int, int]:
    """
    示波器 Eoff 窗口：在关断沿前识别真实导通段 (Vce 低、|Ic| 高)，避免固定短 pre 窗落在切换中途。
    返回 v_base, i_top, i_base, v_top, w0, w1。
    """
    n = len(vce)
    abs_ic = np.abs(ic.astype(np.float64))
    lookback = adaptive_lookback_samples(
        off_idx, pulse1_on, dt, pre_ns, max_us=4.0, frac_of_interval=0.12
    )
    # 导通段搜索必须能早于分段器 turn_off 窄窗，否则长脉冲工况会落在切换中途
    # ``off_idx`` follows the gate event and can lag the actual Vce departure
    # by more than the adaptive look-back on slow/noisy captures.  In that
    # case starting at ``off_idx - lookback`` cuts away the real conducting
    # plateau and makes the 20th percentile land inside the rising edge.  The
    # detector's turn-off segment start is already the bounded local event
    # window, so include it whenever it is earlier.  Eoff Top/Base must come
    # from that stable local platform, never from an in-edge pseudo level.
    w0 = max(0, min(int(i0), off_idx - lookback))
    w1 = min(n - 1, i1, off_idx + int(900e-9 / dt))

    pre_end = max(w0 + 5, off_idx)
    pre_v = vce[w0:pre_end].astype(np.float64)
    pre_i = abs_ic[w0:pre_end]
    if len(pre_i) < 8:
        v_base = float(np.percentile(pre_v, 20)) if len(pre_v) else 0.0
        i_top = float(np.max(pre_i)) if len(pre_i) else 1.0
    else:
        i_top = float(np.percentile(pre_i, 95))
        on_thr = max(0.55 * i_top, 20.0)
        on_mask = pre_i >= on_thr
        if int(np.count_nonzero(on_mask)) >= 8:
            v_base = float(np.percentile(pre_v[on_mask], 20))
        else:
            v_base = float(np.percentile(pre_v, 10))

    post_i = abs_ic[off_idx : w1 + 1]
    post_v = vce[off_idx : w1 + 1].astype(np.float64)
    if len(post_i) < 5:
        i_base = 0.0
        v_top = v_base + max(50.0, 0.1 * abs(float(vce[off_idx])))
    else:
        i_base = float(np.percentile(post_i, 50))
        v_top = float(np.percentile(post_v, 80))

    v_base = _refined_turn_off_vce_base(vce, w0, w1, i0, dt, v_base, v_top)

    return v_base, i_top, i_base, v_top, w0, w1


def scope_turn_on_bases(
    vce: np.ndarray,
    ic: np.ndarray,
    on_idx: int,
    i0: int,
    i1: int,
    dt: float,
    pulse1_off: int | None = None,
) -> tuple[float, float, float, float, int, int]:
    """
    示波器 Eon：开通沿前识别关断态 (|Ic| 低、Vce 高)，开通后识别导通态。
    返回 i_base, v_top, i_top, v_base, w0, w1。
    """
    n = len(vce)
    abs_ic = np.abs(ic.astype(np.float64))
    lookback = adaptive_lookback_samples(
        on_idx, pulse1_off, dt, 250.0, max_us=3.0, frac_of_interval=0.15
    )
    w0 = max(0, on_idx - lookback)
    w1 = min(n - 1, i1, on_idx + int(900e-9 / dt))

    pre_end = max(w0 + 5, on_idx)
    pre_i = abs_ic[w0:pre_end]
    pre_v = vce[w0:pre_end].astype(np.float64)
    if len(pre_i) < 8:
        i_base = float(np.percentile(pre_i, 50)) if len(pre_i) else 0.0
        v_top = float(np.percentile(pre_v, 80)) if len(pre_v) else 0.0
    else:
        v_top = float(np.percentile(pre_v, 80))
        off_thr = max(0.35 * float(np.percentile(pre_i, 95)), 15.0)
        off_mask = pre_i <= off_thr
        if int(np.count_nonzero(off_mask)) >= 8:
            i_base = float(np.percentile(pre_i[off_mask], 50))
            v_hi = pre_v[off_mask]
            if len(v_hi):
                v_top = float(np.percentile(v_hi, 85))
        else:
            i_base = float(np.percentile(pre_i, 30))

    post_i = abs_ic[on_idx : w1 + 1]
    post_v = vce[on_idx : w1 + 1].astype(np.float64)
    if len(post_i) < 5:
        i_top = float(np.max(post_i)) if len(post_i) else 1.0
        v_base = float(np.percentile(post_v, 20)) if len(post_v) else 0.0
    else:
        i_top = float(np.percentile(post_i, 95))
        cond_thr = max(0.5 * i_top, 20.0)
        cond = post_i >= cond_thr
        if int(np.count_nonzero(cond)) >= 8:
            v_base = float(np.percentile(post_v[cond], 20))
        else:
            v_base = float(np.percentile(post_v, 20))

    return i_base, v_top, i_top, v_base, w0, w1
