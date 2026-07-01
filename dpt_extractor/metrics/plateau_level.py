"""无震荡平台段中值：(max + min) / 2。"""
from __future__ import annotations

import numpy as np

# 默认 Ha/Hb 只在跃变附近短窗内搜平台，避免对整段波形 O(n²) 滑动窗
_PLATEAU_PROBE = 96


def _quiet_plateau_mid(band: np.ndarray, *, prefer: str) -> float:
    """在短窗 band 内找最平稳子段，返回 (max+min)/2。"""
    band = np.asarray(band, dtype=np.float64)
    n = len(band)
    if n < 3:
        return plateau_mid(band)
    v_lo = float(np.min(band))
    v_hi = float(np.max(band))
    span = max(v_hi - v_lo, 1e-9)
    dy_lim = max(0.75, 0.012 * span)
    diffs = np.abs(np.diff(band))
    wlen_hi = min(22, n)
    wlen_lo = min(10, n)
    if wlen_hi < wlen_lo:
        return plateau_mid(band)
    best_span = float("inf")
    best_sub = band
    for wlen in range(wlen_lo, wlen_hi + 1):
        nwin = n - wlen + 1
        if nwin < 1:
            break
        for w0 in range(nwin):
            if w0 + wlen - 2 < len(diffs):
                if float(np.max(diffs[w0 : w0 + wlen - 1])) > dy_lim:
                    continue
            sub = band[w0 : w0 + wlen]
            mu = float(np.mean(sub))
            if prefer == "low" and mu > v_lo + 0.42 * span:
                continue
            if prefer == "high" and mu < v_lo + 0.58 * span:
                continue
            s = float(np.max(sub) - np.min(sub))
            if s < best_span:
                best_span = s
                best_sub = sub
    return plateau_mid(best_sub)


def plateau_mid(seg: np.ndarray) -> float:
    block = np.asarray(seg, dtype=np.float64)
    if len(block) == 0:
        return 0.0
    if len(block) < 3:
        return float(np.mean(block))
    return 0.5 * (float(np.max(block)) + float(np.min(block)))


def _transition_index_rise(seg: np.ndarray) -> int:
    dy = np.diff(seg.astype(np.float64))
    ipk = int(np.argmax(dy))
    return max(5, min(ipk, len(seg) - 6))


def _transition_index_fall(seg: np.ndarray) -> int:
    dy = np.diff(seg.astype(np.float64))
    ipk = int(np.argmin(dy))
    return max(5, min(ipk, len(seg) - 6))


def dvdt_rise_base_top_mid(seg: np.ndarray) -> tuple[float, float]:
    """
    上升沿 dv/dt：Hb=段窗前端低平台，Ha=段窗后端高平台（各取短窗）。
    dv/dt 搜索窗已包住关断沿，用首尾短窗即可，避免全段滑动扫描。
    """
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 12:
        v_lo = float(np.min(seg)) if len(seg) else 0.0
        v_hi = float(np.max(seg)) if len(seg) else 0.0
        mid = 0.5 * (v_lo + v_hi)
        return mid, mid
    n = len(seg)
    n_pre = min(_PLATEAU_PROBE, max(12, n // 5))
    n_post = min(_PLATEAU_PROBE, max(12, n // 5))
    pre_w = seg[:n_pre]
    post_w = seg[-n_post:]
    base = _quiet_plateau_mid(pre_w, prefer="low")
    top = _quiet_plateau_mid(post_w, prefer="high")
    return base, top


def dvdt_on_vce_fall_base_top(
    seg: np.ndarray, dt: float = 0.0
) -> tuple[float, float]:
    """
    开通 Vce：Ha=跌落前高平台；Hb=回落后平稳段平均值（非全段 min）。
    返回 (Hb, Ha) 即 (base, top)。
    """
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 12:
        m = float(np.mean(seg)) if len(seg) else 0.0
        return m, m
    dt_s = float(dt) if dt > 0 else 1e-9
    itrans = _transition_index_fall(seg)
    tail = seg[itrans:]
    n_pre = min(
        _PLATEAU_PROBE,
        max(12, itrans // 2, int(100e-9 / dt_s)),
    )
    pre_w = seg[: min(max(12, itrans), n_pre)]
    if len(pre_w) < 3:
        top = float(np.percentile(seg[: max(1, itrans)], 95))
    else:
        top = _quiet_plateau_mid(pre_w, prefer="high")
    skip = max(8, int(40e-9 / dt_s))
    post = tail[skip:] if len(tail) > skip + 5 else tail
    n_avg = min(len(post), max(12, int(120e-9 / dt_s)))
    post_w = post[-n_avg:] if len(post) >= n_avg else post
    if len(post_w) < 3:
        hb = float(np.mean(tail)) if len(tail) else float(np.min(seg))
    else:
        hb = float(np.mean(post_w))
    return hb, top


def turn_on_vce_on_max_window_indices(
    t: np.ndarray,
    vge: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    pulse2_on: int,
    pulse2_off: int,
    dt: float,
    vce_top: float | None = None,
) -> tuple[int, int]:
    """
    开通 Vce_on_max 窗口：A=Vge 低电平开始抬升点，B=本管 Vce 跌到低平台后。

    这个窗口用于数值和 GUI 光标，避免旧逻辑只截取跌落前高平台而把 A/B 卡到
    开通事件左侧。
    """
    t_arr = np.asarray(t, dtype=np.float64)
    vge_arr = np.asarray(vge, dtype=np.float64)
    vce_arr = np.asarray(vce, dtype=np.float64)
    n = min(len(t_arr), len(vge_arr), len(vce_arr))
    if n == 0:
        return 0, 0
    if n < 4:
        return 0, n - 1
    dt_s = max(float(dt), 1e-15)
    s0 = max(0, min(int(i0), n - 2))
    s1 = max(s0 + 2, min(int(i1), n - 1))
    on_idx = max(s0, min(int(pulse2_on), n - 2))
    off_idx = max(on_idx + 1, min(int(pulse2_off), n - 1))

    def _block_percentile(
        arr: np.ndarray, lo: int, hi: int, pct: float, fallback: float
    ) -> float:
        lo = max(0, min(int(lo), n - 1))
        hi = max(lo + 1, min(int(hi), n))
        block = arr[lo:hi]
        if len(block) == 0 or not np.isfinite(block).any():
            return float(fallback)
        return float(np.nanpercentile(block, float(pct)))

    pre0 = max(0, min(s0, on_idx - int(800e-9 / dt_s)))
    pre0 = max(pre0, on_idx - int(800e-9 / dt_s))
    pre1 = min(on_idx, on_idx - int(50e-9 / dt_s))
    if pre1 <= pre0 + 3:
        pre0 = max(s0, on_idx - int(500e-9 / dt_s))
        pre1 = max(pre0 + 3, on_idx)
    post0 = min(n - 1, max(on_idx + int(100e-9 / dt_s), on_idx))
    post1 = min(n, max(post0 + 4, min(off_idx, on_idx + int(900e-9 / dt_s))))
    vge_lo = _block_percentile(vge_arr, pre0, pre1, 5.0, float(vge_arr[on_idx]))
    vge_hi = _block_percentile(vge_arr, post0, post1, 95.0, float(vge_arr[on_idx]))
    span = vge_hi - vge_lo

    a_idx = on_idx
    search_a0 = max(s0, pre0)
    search_a1 = min(n - 1, on_idx + int(250e-9 / dt_s))
    if abs(span) >= 0.5 and search_a1 > search_a0:
        threshold = vge_lo + 0.02 * span
        if span >= 0.0:
            hits = np.where(vge_arr[search_a0 : search_a1 + 1] >= threshold)[0]
        else:
            hits = np.where(vge_arr[search_a0 : search_a1 + 1] <= threshold)[0]
        if len(hits):
            a_idx = search_a0 + int(hits[0])

    if vce_top is None or not np.isfinite(float(vce_top)):
        vce_top = float(np.nanmax(vce_arr[s0 : s1 + 1]))
    top = float(vce_top)
    base0 = min(n - 1, max(a_idx + int(100e-9 / dt_s), on_idx + int(300e-9 / dt_s)))
    base1 = min(n, max(base0 + 6, min(off_idx, on_idx + int(1400e-9 / dt_s))))
    if base1 <= base0 + 3:
        base0 = min(n - 1, max(a_idx + int(120e-9 / dt_s), s0))
        base1 = min(n, max(base0 + 6, s1 + 1))
    base_block = vce_arr[base0:base1]
    if len(base_block) >= 3 and np.isfinite(base_block).any():
        vce_base = float(np.nanpercentile(base_block, 20))
    else:
        vce_base = float(np.nanmin(vce_arr[s0 : s1 + 1]))
    swing = max(top - vce_base, 1.0)
    low_threshold = vce_base + max(0.05 * swing, 5.0)
    hold_threshold = low_threshold + max(0.02 * swing, 5.0)
    hold = max(3, int(40e-9 / dt_s))
    search_b1 = min(n - 1, max(s1, min(off_idx - 1, a_idx + int(2000e-9 / dt_s))))

    b_idx = s1
    for k in range(max(a_idx + 1, s0), search_b1 + 1):
        if float(vce_arr[k]) > low_threshold:
            continue
        if k + hold <= n:
            sub = vce_arr[k : k + hold]
            if len(sub) and float(np.nanpercentile(sub, 80)) <= hold_threshold:
                b_idx = k + hold - 1
                break
        else:
            b_idx = k
            break
    if b_idx <= a_idx + 2:
        b_idx = max(a_idx + 2, s1)
    return int(max(0, min(a_idx, n - 1))), int(max(a_idx + 1, min(b_idx, n - 1)))


def turn_on_vce_on_max_value(
    t: np.ndarray,
    vge: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    pulse2_on: int,
    pulse2_off: int,
    dt: float,
    vce_top: float | None = None,
) -> float:
    """开通 Vce_on_max 数值：Vge 抬升到 Vce 低平台窗口内最大值。"""
    if len(vce) == 0:
        return 0.0
    w0, w1 = turn_on_vce_on_max_window_indices(
        t,
        vge,
        vce,
        i0,
        i1,
        pulse2_on,
        pulse2_off,
        dt,
        vce_top,
    )
    block = vce[w0 : w1 + 1]
    return float(np.max(block)) if len(block) else 0.0


def dvdt_rr_vd_plateau_top(
    t: np.ndarray,
    v_d: np.ndarray,
    vrr_peak_idx: int,
    dt: float,
    search_end: int,
) -> float:
    """反向恢复二极管 dv/dt 的 Ha：Vrr 尖峰后震荡结束尾段 |Vd| 的 (max+min)/2。"""
    t_arr = np.asarray(t, dtype=np.float64)
    vd_abs = np.abs(np.asarray(v_d, dtype=np.float64))
    n = len(t_arr)
    if n < 4:
        return 0.0
    ipk = max(0, min(int(vrr_peak_idx), n - 1))
    search_end = max(ipk + 2, min(int(search_end), n - 1))
    peak_t = float(t_arr[ipk])
    dt_s = max(float(dt), 1e-15)
    wlen = max(5, int(300e-9 / dt_s))
    settle = max(3, int(970e-9 / dt_s))
    t_lo = peak_t + float(settle) * dt_s
    t_hi = min(float(t_arr[search_end]), t_lo + 300e-9)
    lo = int(np.searchsorted(t_arr, t_lo))
    hi = int(np.searchsorted(t_arr, t_hi, side="right"))
    block = vd_abs[lo:hi]
    ha = plateau_mid(block) if len(block) >= 3 else 0.0
    if ha <= 1e-6:
        lo2 = min(ipk + settle, n - wlen - 1)
        lo2 = max(0, lo2)
        ha = plateau_mid(vd_abs[lo2 : lo2 + wlen])
    return float(ha)


def dvdt_rr_vd_base_top(
    t: np.ndarray,
    v_d: np.ndarray,
    vrr_peak_idx: int,
    dt: float,
    search_end: int,
) -> tuple[float, float]:
    """Hb=0（|VDM| 幅值基准），Ha=震荡结束后的 Vd 平台。"""
    return 0.0, dvdt_rr_vd_plateau_top(t, v_d, vrr_peak_idx, dt, search_end)


def dvdt_fall_base_top_mid(seg: np.ndarray) -> tuple[float, float]:
    """下降沿 dv/dt：Ha=高平台，Hb=低平台。"""
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 12:
        v_lo = float(np.min(seg)) if len(seg) else 0.0
        v_hi = float(np.max(seg)) if len(seg) else 0.0
        mid = 0.5 * (v_lo + v_hi)
        return mid, mid
    itrans = _transition_index_fall(seg)
    head = seg[: itrans + 1]
    tail = seg[itrans:]
    pre_w = head[-min(_PLATEAU_PROBE, len(head)) :]
    post_w = tail[-min(_PLATEAU_PROBE, len(tail)) :]
    top = _quiet_plateau_mid(pre_w, prefer="high")
    base = _quiet_plateau_mid(post_w, prefer="low")
    return top, base


def _turn_on_rise_index(seg: np.ndarray, dt_s: float) -> int:
    # 用带符号电流：下桥导通前基线可能为负(~-32A)，abs 会把负基线翻正、
    # 使横向光标浮在波形上方。导通沿单调上升，带符号判定对上桥完全等价。
    seg = np.asarray(seg, dtype=np.float64)
    n_flat = max(12, min(len(seg) // 6, int(70e-9 / dt_s)))
    hb_block = seg[:n_flat]
    cut = float(np.percentile(hb_block, 55))
    stable = hb_block[
        hb_block <= cut + max(15.0, 0.05 * float(np.max(hb_block)))
    ]
    hb = plateau_mid(stable) if len(stable) >= 3 else plateau_mid(hb_block)
    ic_max = float(np.max(seg))
    thr = hb + max(20.0, 0.10 * (ic_max - hb))
    rise = len(seg) - 1
    step = max(3, int(8e-9 / dt_s))
    for k in range(n_flat, len(seg) - step):
        if float(np.mean(seg[k : k + step])) > thr:
            rise = k
            break
    return rise


def _turn_on_current_hb_ha_at_rise(
    t: np.ndarray,
    ic_abs: np.ndarray,
    rise_idx: int,
    i_end: int,
    dt: float,
) -> tuple[float, float]:
    """Hb=抬升前 ~600ns 窗 (max+min)/2；Ha=抬升后 ~514–714ns 尾段 (max+min)/2。

    带符号取值：下桥导通前基线为负，须让 Hb 落在真实波形(带符号)上而非 |Ic|。
    """
    t_arr = np.asarray(t, dtype=np.float64)
    ic_abs = np.asarray(ic_abs, dtype=np.float64)
    n = len(t_arr)
    if n < 4:
        return 0.0, 0.0
    rise_idx = max(0, min(int(rise_idx), n - 1))
    i_end = max(rise_idx + 2, min(int(i_end), n - 1))
    dt_s = max(float(dt), 1e-15)
    t_rise = float(t_arr[rise_idx])
    t_hb_lo = t_rise - 600e-9
    t_hb_hi = t_rise - 50e-9
    lo = int(np.searchsorted(t_arr, t_hb_lo))
    hi = int(np.searchsorted(t_arr, t_hb_hi, side="right"))
    hb = plateau_mid(ic_abs[lo:hi]) if hi > lo else plateau_mid(ic_abs[: max(rise_idx, 3)])

    t_ha_lo = t_rise + 514e-9
    t_ha_hi = min(float(t_arr[i_end]), t_rise + 714e-9)
    lo2 = int(np.searchsorted(t_arr, t_ha_lo))
    hi2 = int(np.searchsorted(t_arr, t_ha_hi, side="right"))
    if hi2 <= lo2:
        hi2 = min(n, lo2 + max(5, int(200e-9 / dt_s)))
    ha = plateau_mid(ic_abs[lo2:hi2]) if hi2 > lo2 else float(np.max(ic_abs[rise_idx:]))
    return float(hb), float(ha)


def turn_on_current_hb_ha_t(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
) -> tuple[float, float]:
    """开通电流 Ha/Hb：全时间轴上按 Ic 抬升沿定位前后平台窗（带符号，贴真实波形）。"""
    ic_abs = np.asarray(ic, dtype=np.float64)
    t_arr = np.asarray(t, dtype=np.float64)
    i0 = max(0, min(int(i0), len(t_arr) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t_arr) - 1))
    seg = ic_abs[i0 : i1 + 1]
    if len(seg) < 8:
        m = plateau_mid(seg)
        return m, m
    dt_s = max(float(dt), 1e-15)
    rise_local = _turn_on_rise_index(seg, dt_s)
    rise_g = i0 + rise_local
    t_rise = float(t_arr[rise_g])
    i_end = max(
        i1,
        min(len(t_arr) - 1, int(np.searchsorted(t_arr, t_rise + 720e-9))),
    )
    return _turn_on_current_hb_ha_at_rise(t_arr, ic_abs, rise_g, i_end, dt_s)


def turn_on_current_baseline_and_plateau(
    seg: np.ndarray, dt: float = 0.0
) -> tuple[float, float]:
    """Hb=抬升前低平台；Ha=抬升后震荡结束平台（段内相对时间窗，带符号贴波形）。"""
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 8:
        mid = plateau_mid(seg)
        return mid, mid
    dt_s = max(float(dt), 1e-15)
    rise = _turn_on_rise_index(seg, dt_s)
    n = len(seg)
    pre = max(5, int(600e-9 / dt_s))
    margin = max(3, int(50e-9 / dt_s))
    lo = max(0, rise - pre)
    hi = max(lo + 3, min(n, rise - margin))
    hb = plateau_mid(seg[lo:hi])
    ha_lo = rise + max(3, int(514e-9 / dt_s))
    ha_hi = min(n, rise + max(5, int(714e-9 / dt_s)))
    if ha_hi <= ha_lo:
        ha_hi = min(n, ha_lo + max(5, int(200e-9 / dt_s)))
    ha = plateau_mid(seg[ha_lo:ha_hi]) if ha_hi > ha_lo else float(np.max(seg[rise:]))
    return float(hb), float(ha)


def ic_plateau_confirm_index(
    seg: np.ndarray, level: float, *, rise: int = 0
) -> int:
    """在搜索段内找与 level 最接近的导通平稳区时刻（相对下标，带符号贴波形）。"""
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) == 0:
        return 0
    tol = max(25.0, 0.035 * float(level))
    mask = np.abs(seg - float(level)) <= tol
    if np.any(mask):
        idx = np.where(mask)[0]
        late = idx[idx >= max(int(rise), int(0.45 * len(seg)))]
        if len(late) == 0:
            late = idx
        return int(np.median(late))
    cross = np.where(seg >= float(level) * 0.92)[0]
    if len(cross):
        return int(cross[-1])
    return len(seg) - 1


def ic_plateau_mean_near_time_us(
    t: np.ndarray,
    ic: np.ndarray,
    t_center_us: float,
    dt: float,
    *,
    half_window_s: float = 100e-9,
) -> float:
    """B 附近短窗 Ic 平均，用于震荡基本结束后的平台 Ha（带符号贴波形）。"""
    ic = np.asarray(ic, dtype=np.float64)
    if len(t) == 0:
        return 0.0
    ts = float(t_center_us) * 1e-6
    hw = float(half_window_s)
    i0 = int(np.searchsorted(t, ts - hw, side="left"))
    i1 = int(np.searchsorted(t, ts + hw, side="right"))
    i0 = max(0, min(i0, len(ic) - 1))
    i1 = max(i0, min(i1, len(ic) - 1))
    if i1 <= i0:
        return float(ic[i0])
    return float(np.mean(ic[i0 : i1 + 1]))


def _interp_cross_t(
    t0: float, t1: float, y0: float, y1: float, level: float
) -> float:
    if abs(y1 - y0) < 1e-30:
        return t0
    f = float(np.clip((level - y0) / (y1 - y0), 0.0, 1.0))
    return t0 + f * (t1 - t0)


def _turn_on_a_cross_window(
    seg: np.ndarray, seg_t: np.ndarray, dt_s: float
) -> tuple[float, float]:
    rise = _turn_on_rise_index(seg, dt_s)
    t_rise = float(seg_t[min(rise, len(seg_t) - 1)])
    win_lo = max(float(seg_t[0]), t_rise - 80e-9)
    win_hi = min(float(seg_t[-1]), t_rise + 30e-9)
    return win_lo, win_hi


def _turn_on_collect_hb_rise_crosses(
    seg: np.ndarray,
    seg_t: np.ndarray,
    hb: float,
    win_lo: float,
    win_hi: float,
    *,
    strict: bool,
) -> list[float]:
    dy = np.diff(seg)
    dy_min = 4.0
    seg_cap = min(45.0, float(hb) + 15.0)
    out: list[float] = []
    for k in range(len(seg) - 1):
        tk = float(seg_t[k])
        if tk < win_lo or tk > win_hi:
            continue
        if not (seg[k] < float(hb) <= seg[k + 1]):
            continue
        if strict:
            if float(seg[k]) >= seg_cap:
                continue
            if k < len(dy) and float(dy[k]) < dy_min:
                continue
        out.append(
            _interp_cross_t(
                float(seg_t[k]),
                float(seg_t[k + 1]),
                float(seg[k]),
                float(seg[k + 1]),
                float(hb),
            )
        )
    return out


def turn_on_ic_a_cross_hb_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    hb: float,
    dt: float,
) -> float:
    """A：Hb 平台窗末端附近，|Ic| 主上升沿与 Hb 的第一次有效上升交汇（µs）。"""
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    seg = ic[i0 : i1 + 1].astype(np.float64)
    seg_t = t[i0 : i1 + 1]
    if len(seg) < 4:
        return float(seg_t[0]) * 1e6
    dt_s = max(float(dt), 1e-15)
    win_lo, win_hi = _turn_on_a_cross_window(seg, seg_t, dt_s)
    crosses = _turn_on_collect_hb_rise_crosses(
        seg, seg_t, hb, win_lo, win_hi, strict=True
    )
    if not crosses:
        crosses = _turn_on_collect_hb_rise_crosses(
            seg, seg_t, hb, win_lo, win_hi, strict=False
        )
    if crosses:
        return float(crosses[0]) * 1e6
    rise = _turn_on_rise_index(seg, dt_s)
    return float(seg_t[min(rise, len(seg_t) - 1)]) * 1e6


def turn_on_ic_a_cross_hb_near_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    hb: float,
    ref_t_us: float,
    dt: float,
) -> float:
    """A：在 ref 附近找 Ic 与 Hb 的主上升沿交汇（拖 A 时用，带符号贴波形）。"""
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    seg = ic[i0 : i1 + 1].astype(np.float64)
    seg_t = t[i0 : i1 + 1]
    if len(seg) < 4:
        return float(seg_t[0]) * 1e6
    dt_s = max(float(dt), 1e-15)
    ref_s = float(ref_t_us) * 1e-6
    win_lo, win_hi = _turn_on_a_cross_window(seg, seg_t, dt_s)
    pad = 120e-9
    near_lo = max(win_lo, ref_s - pad)
    near_hi = min(win_hi, ref_s + pad)
    crosses = _turn_on_collect_hb_rise_crosses(
        seg, seg_t, hb, near_lo, near_hi, strict=True
    )
    if not crosses:
        crosses = _turn_on_collect_hb_rise_crosses(
            seg, seg_t, hb, win_lo, win_hi, strict=True
        )
    if not crosses:
        return turn_on_ic_a_cross_hb_us(t, ic, i0, i1, hb, dt)
    t_first_s = turn_on_ic_a_cross_hb_us(t, ic, i0, i1, hb, dt) * 1e-6
    # 主上升沿首交点优先：ref 在其后 100ns 内仍吸附首交点
    if ref_s <= t_first_s + 100e-9:
        return float(t_first_s) * 1e6
    best = min(crosses, key=lambda tc: abs(tc - ref_s))
    return float(best) * 1e6


def turn_on_ic_b_cross_ha_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    ha: float,
    dt: float,
) -> float:
    """B：Ic 震荡尾段与 Ha 的第一个平稳交汇时刻（µs，带符号贴波形）。"""
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    ic_abs = np.asarray(ic, dtype=np.float64)
    seg = ic_abs[i0 : i1 + 1]
    if len(seg) < 8:
        return float(t[i0]) * 1e6
    dt_s = max(float(dt), 1e-15)
    rise = _turn_on_rise_index(seg, dt_s)
    rise_g = i0 + rise
    t_rise = float(t[rise_g])
    i_end = max(
        i1,
        min(len(t) - 1, int(np.searchsorted(t, t_rise + 1.35e-6))),
    )
    i_lo = int(np.searchsorted(t, t_rise + 514e-9))
    hold = max(5, int(80e-9 / dt_s))
    tol = max(25.0, 0.035 * float(ha))
    span_thr = max(30.0, 0.06 * float(ha))
    for j in range(i_lo, max(i_lo + 1, i_end - hold)):
        sub = ic_abs[j : j + hold]
        if abs(float(np.mean(sub)) - float(ha)) > tol:
            continue
        if float(np.max(sub) - np.min(sub)) > span_thr:
            continue
        k0 = max(i_lo, j - max(3, int(40e-9 / dt_s)))
        for k in range(k0, min(j + 1, len(ic_abs) - 1)):
            y0, y1 = float(ic_abs[k]), float(ic_abs[k + 1])
            if (y0 >= float(ha) > y1) or (y0 < float(ha) <= y1):
                return (
                    _interp_cross_t(
                        float(t[k]), float(t[k + 1]), y0, y1, float(ha)
                    )
                    * 1e6
                )
        return float(t[j]) * 1e6
    return ic_plateau_confirm_time_us(t, ic, i0, i1, ha, dt)


def turn_on_ic_b_cross_ha_near_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    ha: float,
    ref_t_us: float,
    dt: float,
) -> float:
    """B：在 ref 附近找 Ic 与 Ha 的平稳段交汇（拖 B 时用，带符号贴波形）。"""
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    ic_abs = np.asarray(ic, dtype=np.float64)
    seg = ic_abs[i0 : i1 + 1]
    seg_t = t[i0 : i1 + 1]
    if len(seg) < 8:
        return float(seg_t[0]) * 1e6
    dt_s = max(float(dt), 1e-15)
    ref_s = float(ref_t_us) * 1e-6
    rise = _turn_on_rise_index(seg, dt_s)
    t_rise = float(seg_t[min(rise, len(seg_t) - 1)])
    plat_lo = t_rise + 514e-9
    plat_hi = min(float(seg_t[-1]), t_rise + 714e-9)
    pad = 150e-9
    near_lo = max(plat_lo, ref_s - pad)
    near_hi = min(max(plat_hi, ref_s + pad), float(seg_t[-1]))
    tol = max(25.0, 0.035 * float(ha))
    span_thr = max(30.0, 0.06 * float(ha))
    hold = max(5, int(80e-9 / dt_s))
    candidates: list[float] = []

    def _add_cross(k: int) -> None:
        y0, y1 = float(ic_abs[i0 + k]), float(ic_abs[i0 + k + 1])
        if (y0 >= float(ha) > y1) or (y0 < float(ha) <= y1):
            candidates.append(
                _interp_cross_t(
                    float(seg_t[k]),
                    float(seg_t[k + 1]),
                    y0,
                    y1,
                    float(ha),
                )
            )

    i_lo = int(np.searchsorted(seg_t, near_lo))
    i_hi = int(np.searchsorted(seg_t, near_hi, side="right"))
    i_lo = max(0, min(i_lo, len(seg) - 2))
    i_hi = max(i_lo + 1, min(i_hi, len(seg) - 1))
    for j in range(i_lo, max(i_lo + 1, i_hi - hold)):
        sub = seg[j : j + hold]
        if abs(float(np.mean(sub)) - float(ha)) > tol:
            continue
        if float(np.max(sub) - np.min(sub)) > span_thr:
            continue
        k0 = max(i_lo, j - max(3, int(40e-9 / dt_s)))
        for k in range(k0, min(j + 1, len(seg) - 1)):
            tk = float(seg_t[k])
            if near_lo <= tk <= near_hi:
                _add_cross(k)
    if not candidates:
        for k in range(i_lo, min(len(seg) - 1, i_hi)):
            if near_lo <= float(seg_t[k]) <= near_hi:
                _add_cross(k)
    t_first_s = turn_on_ic_b_cross_ha_us(t, ic, i0, i1, ha, dt) * 1e-6
    if ref_s <= t_first_s + 150e-9:
        return float(t_first_s) * 1e6
    if candidates:
        return float(min(candidates, key=lambda tc: abs(tc - ref_s))) * 1e6
    return float(t_first_s) * 1e6


def turn_on_ic_link_default_times(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
) -> tuple[float, float, float, float]:
    """默认 Hb/Ha 平台 + A/B 在 |Ic| 上的首次有效交汇时刻。"""
    hb, ha = turn_on_current_hb_ha_t(t, ic, i0, i1, dt)
    t_a_us = turn_on_ic_a_cross_hb_us(t, ic, i0, i1, hb, dt)
    t_b_us = turn_on_ic_b_cross_ha_us(t, ic, i0, i1, ha, dt)
    return t_a_us, t_b_us, float(hb), float(ha)


def ic_plateau_confirm_time_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    level: float,
    dt: float,
) -> float:
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    seg = ic[i0 : i1 + 1].astype(np.float64)
    dt_s = float(dt) if dt > 0 else 1e-9
    rise = _turn_on_rise_index(seg, dt_s)
    j = ic_plateau_confirm_index(seg, level, rise=rise)
    return float(t[i0 + j] * 1e6)


def turn_on_current_hb_ha_levels(
    seg: np.ndarray, dt: float = 0.0
) -> tuple[float, float, float]:
    """兼容旧接口：Hb, Ha(=导通平台), 开通电流值。"""
    hb, val = turn_on_current_baseline_and_plateau(seg, dt)
    return hb, val, val


def turn_on_didt_ha_at_turn_on(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
) -> float:
    """
    开通 di/dt Ha：相对 |Ic| 抬升沿后 ~514–714ns 尾段 (max+min)/2。
    UH 样例约等价于开通段末 19.0–19.2µs 平台，换工况时随段窗/抬升沿自适应。
    """
    _hb, ha = turn_on_current_hb_ha_t(t, ic, i0, i1, dt)
    return float(ha)


def didt_fall_top_base_mid(seg: np.ndarray) -> tuple[float, float]:
    """下降沿 di/dt（关断电流）：Ha=关断前高平台，Hb=关断后低平台中值。"""
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 12:
        v_lo = float(np.min(seg)) if len(seg) else 0.0
        v_hi = float(np.max(seg)) if len(seg) else 0.0
        mid = 0.5 * (v_lo + v_hi)
        return mid, mid
    itrans = _transition_index_fall(seg)
    head = seg[: itrans + 1]
    tail = seg[itrans:]
    pre_w = head[-min(_PLATEAU_PROBE, len(head)) :]
    post_w = tail[-min(_PLATEAU_PROBE, len(tail)) :]
    top = _quiet_plateau_mid(pre_w, prefer="high")
    base = _quiet_plateau_mid(post_w, prefer="low")
    return top, base
