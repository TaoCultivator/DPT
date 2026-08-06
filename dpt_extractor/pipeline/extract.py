from __future__ import annotations

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.detect.pulse_detector import PulseDetector
from dpt_extractor.detect.segmenter import Segmenter
from dpt_extractor.metrics.derived import (
    bus_voltage_before_off,
    bus_voltage_plateau,
    crosstalk_extrema,
    measure_idc,
    measure_vdc,
)
from dpt_extractor.metrics.iec_timings import (
    ic_stats_in_window,
    reverse_recovery_trr,
    turn_off_ic_fall_window,
    turn_on_ic_top,
    turn_on_vce_top_from_ic_rise,
    turn_off_timings,
    turn_on_ic_rise_window,
    turn_on_timing_instants,
)
from dpt_extractor.metrics.iec_windows import (
    eoff_window_scope_example,
    eon_window_scope_example,
    err_energy_markers,
    energy_window_power,
    integrate_err_recovery,
    integrate_vi_window,
    rr_completed_measurement_window_indices,
    rr_slope_window_indices,
)
from dpt_extractor.metrics.energy import peak_power_kw
from dpt_extractor.metrics.irr_measure import irr_parameter_peak_value
from dpt_extractor.metrics.plateau_level import turn_off_delta_vce_blocking_top
from dpt_extractor.metrics.slopes import (
    rr_dvdt_measurement_context,
    rr_dvdt_prefers_settled_platform,
    rr_didt_measurement_context,
    turn_on_dvdt_measurement_context,
    turn_on_didt_measurement_context,
    turn_off_didt_measurement_context,
    turn_off_dvdt_measurement_context,
)
from dpt_extractor.models.slope_range import (
    SlopeRange,
    default_slope_ranges,
    slope_range_result_label,
)
from dpt_extractor.models.bridge_profile import BridgeProfile
from dpt_extractor.models.results import (
    ExtractResult,
    ReverseRecoveryResult,
    TurnOffResult,
    TurnOnResult,
)
from dpt_extractor.models.waveform import (
    WaveformBundle,
    try_bundle_reverse_recovery_current,
    try_bundle_total_current,
)

MetricKey = tuple[str, str]
_REVERSE_RECOVERY_CURRENT_METRICS: set[MetricKey] = {
    ("反向恢复", "Irr"),
    ("反向恢复", "Trr"),
    ("反向恢复", "di/dt"),
    ("反向恢复", "Pdmax"),
    ("反向恢复", "Err"),
}
_TURN_ON_TIMING_METRICS: set[MetricKey] = {
    ("开通", "Ton"),
    ("开通", "Td_on"),
    ("开通", "Tr"),
}


def _optional_channel(bundle: WaveformBundle, col: str) -> np.ndarray | None:
    if not col:
        return None
    return bundle.maybe_get(col)


def _smooth_edge_padded(y: np.ndarray, window: int) -> np.ndarray:
    """Moving average without the zero-padding edge dip from np.convolve(..., same)."""
    if len(y) == 0:
        return y.astype(np.float64)
    k = int(window)
    if k <= 1 or len(y) < 3:
        return y.astype(np.float64)
    k = min(k, len(y) if len(y) % 2 == 1 else len(y) - 1)
    if k < 3:
        return y.astype(np.float64)
    if k % 2 == 0:
        k -= 1
    pad = k // 2
    ker = np.ones(k, dtype=np.float64) / float(k)
    return np.convolve(np.pad(y.astype(np.float64), (pad, pad), mode="edge"), ker, mode="valid")


def _turn_on_delta_vce_knee_point(
    vce: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    vce_top: float,
) -> tuple[int, float] | None:
    """
    开通 ΔVce 的 Hb 自动点。

    - 稳定平台：取平台段 (max + min) / 2；
    - 三斜率下降沿：取中间斜率段的时间中点；
    - 两斜率下降沿：取第一段平缓下降结束、第二段主下降开始的拐点；
    - 若特征不明显，则回退到主下降最陡点，保证仍能得到稳定默认值。
    """
    if i1 <= i0 + 8 or vce_top <= 1.0:
        return None
    seg = vce[i0:i1].astype(np.float64)
    n = len(seg)
    if n < 8:
        return None

    # 约 4 ns 上限的轻度平滑，使用边界填充避免开通窗左边缘被零填充拉低。
    win = min(51, max(7, (n // 80) | 1))
    seg_s = _smooth_edge_padded(seg, win)
    dv_fall = -np.diff(seg_s) / max(dt, 1e-15)
    if len(dv_fall) == 0:
        return None

    cand_main = np.where(
        (seg_s[:-1] <= 0.98 * vce_top) & (seg_s[:-1] >= 0.08 * vce_top)
    )[0]
    if len(cand_main) == 0:
        cand_main = np.arange(0, len(dv_fall))
    j0 = int(cand_main[0])
    j1 = int(cand_main[-1])
    if j1 <= j0 + 5:
        j0, j1 = 0, len(dv_fall) - 1

    win_dv = dv_fall[j0 : j1 + 1]
    j_peak = j0 + int(np.argmax(win_dv))
    dv_peak = float(max(dv_fall[j_peak], 1e-12))
    if dv_peak <= 1e-12:
        return None

    dv_state = _smooth_edge_padded(dv_fall, min(101, max(9, (len(dv_fall) // 80) | 1)))
    state_win = dv_state[j0 : j1 + 1]
    state_peak = float(max(np.max(state_win), 1e-12))

    def _stable_subwindow(a: int, b: int) -> tuple[int, float, float] | None:
        """Return the flattest local platform inside [a, b] as (idx, level, span)."""
        a = max(0, min(int(a), len(seg_s) - 1))
        b = max(a, min(int(b), len(seg_s) - 1))
        length = b - a + 1
        min_pts = max(20, int(8e-9 / max(dt, 1e-15)))
        if length < min_pts:
            return None
        win_pts = min(length, max(min_pts, int(12e-9 / max(dt, 1e-15))))
        best: tuple[float, int, float] | None = None
        for start in range(a, b - win_pts + 2):
            vals = seg_s[start : start + win_pts]
            if len(vals) == 0:
                continue
            span = float(np.max(vals) - np.min(vals))
            center = start + win_pts // 2
            level = 0.5 * (float(np.max(vals)) + float(np.min(vals)))
            if (
                best is None
                or span < best[0] - 1e-9
                or (abs(span - best[0]) <= 1e-9 and center > best[1])
            ):
                best = (span, center, level)
        if best is None:
            return None
        span, center, level = best
        if span > max(0.035 * vce_top, 18.0):
            return None
        return center, level, span

    # 有些开通波形先跌到一个短平台，再进入主跌落。该平台不在两个高速段之间，
    # 需要在主跌落峰值之前单独识别，否则 Hb 会落到主跌落开始后的偏低位置。
    plateau_slope_th = max(0.08 * state_peak, 0.10e9)
    min_pre_drop = max(0.12 * vce_top, 45.0)
    max_pre_drop = 0.80 * vce_top
    min_pre_run = max(20, int(18e-9 / max(dt, 1e-15)))
    candidates: list[tuple[float, int, float]] = []
    run_start: int | None = None
    for jj in range(j0, j_peak + 1):
        drop = float(vce_top - seg_s[jj])
        is_plateau_like = (
            abs(float(dv_state[jj])) <= plateau_slope_th
            and min_pre_drop <= drop <= max_pre_drop
        )
        if is_plateau_like and run_start is None:
            run_start = jj
        if (not is_plateau_like or jj == j_peak) and run_start is not None:
            run_end = jj - 1 if not is_plateau_like else jj
            if run_end - run_start + 1 >= min_pre_run:
                stable = _stable_subwindow(run_start, run_end)
                if stable is not None:
                    center, level, span = stable
                    drop_level = float(vce_top - level)
                    if min_pre_drop <= drop_level <= max_pre_drop:
                        candidates.append((span, center, level))
            run_start = None
    if candidates:
        _span, center, level = min(candidates, key=lambda item: (item[0], -item[1]))
        return i0 + center, float(level)

    # 三斜率形态：下降速度曲线上有两个持续高速段，中间夹着较缓的中间斜率段。
    # 此时人工卡尺更稳定的位置是两个高速段之间的时间中点。
    high_th = max(0.50 * state_peak, float(np.percentile(state_win, 80)))
    high_mask = state_win >= high_th
    min_run = max(20, int(1.2e-9 / max(dt, 1e-15)))
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for rel, is_high in enumerate(high_mask):
        if is_high and start is None:
            start = rel
        if (not is_high or rel == len(high_mask) - 1) and start is not None:
            end = rel - 1 if not is_high else rel
            if end - start + 1 >= min_run:
                runs.append((j0 + start, j0 + end))
            start = None

    min_gap = max(50, int(25e-9 / max(dt, 1e-15)))
    best_mid: int | None = None
    best_v: float | None = None
    best_gap = -1
    for left, right in zip(runs, runs[1:]):
        gap = right[0] - left[1]
        if gap < min_gap:
            continue
        mid = int((left[1] + right[0]) // 2)
        gap_state = dv_state[left[1] : right[0] + 1]
        if len(gap_state) == 0 or float(np.median(gap_state)) > 0.35 * state_peak:
            continue
        # 若中间段明显形成稳定电压平台，Hb 电平按平台 max/min 平均值，而不是取单点。
        low_mask = gap_state <= 0.05 * state_peak
        min_plateau = max(20, int(3e-9 / max(dt, 1e-15)))
        best_plateau: tuple[int, int] | None = None
        best_plateau_span = float("inf")
        plateau_start: int | None = None
        for rel, is_low in enumerate(low_mask):
            if is_low and plateau_start is None:
                plateau_start = rel
            if (not is_low or rel == len(low_mask) - 1) and plateau_start is not None:
                end = rel - 1 if not is_low else rel
                if end - plateau_start + 1 >= min_plateau:
                    pa = left[1] + plateau_start
                    pb = left[1] + end
                    platform = seg_s[pa : pb + 1]
                    span = float(np.max(platform) - np.min(platform)) if len(platform) > 0 else float("inf")
                    if (
                        best_plateau is None
                        or span < best_plateau_span
                        or (abs(span - best_plateau_span) < 1e-9 and (pb - pa) > (best_plateau[1] - best_plateau[0]))
                    ):
                        best_plateau = (pa, pb)
                        best_plateau_span = span
                plateau_start = None
        pick_mid = mid
        pick_v = float(seg_s[mid])
        platform_used = False
        if best_plateau is not None:
            pa, pb = best_plateau
            platform = seg_s[pa : pb + 1]
            if len(platform) > 0:
                p_min = float(np.min(platform))
                p_max = float(np.max(platform))
                if (p_max - p_min) <= max(0.035 * vce_top, 18.0):
                    pick_mid = int((pa + pb) // 2)
                    pick_v = 0.5 * (p_max + p_min)
                    platform_used = True
        pick_drop = float(vce_top - pick_v)
        min_drop = max(0.15 * vce_top, 60.0) if platform_used else max(0.25 * vce_top, 80.0)
        # 中间段应位于 Vce 主下降过程内部，避免把顶部小扰动或导通后振铃误判为三斜率。
        if not (min_drop <= pick_drop <= 0.80 * vce_top):
            continue
        if gap > best_gap:
            best_gap = gap
            best_mid = pick_mid
            best_v = pick_v
    if best_mid is not None and best_v is not None:
        return i0 + best_mid, best_v

    # 优先找“第二段主下降”的起点：速度进入主下降状态，且 Vce 已离开 Top 足够远。
    min_main_drop = max(0.25 * vce_top, 80.0)
    main_th = max(0.45 * dv_peak, float(np.percentile(win_dv, 85)))
    for jj in range(j0, j_peak + 1):
        if dv_fall[jj] >= main_th and (vce_top - seg_s[jj]) >= min_main_drop:
            return i0 + jj, float(seg_s[jj])

    # 拐点不明显时，放宽门槛找第二次明显下降的起点。
    loose_th = max(0.35 * dv_peak, float(np.percentile(win_dv, 75)))
    for jj in range(j0, j_peak + 1):
        if dv_fall[jj] >= loose_th and (vce_top - seg_s[jj]) >= 0.15 * vce_top:
            return i0 + jj, float(seg_s[jj])

    return i0 + j_peak, float(seg_s[j_peak])


def _turn_on_delta_vce(
    vce: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    vce_top: float,
) -> float:
    """
    开通 ΔVce：
    上点固定取 Vce Top；下点优先取稳定平台 max/min 平均值或三斜率下降沿的中间段中点，
    否则取两斜率下降沿第一段结束、第二段主下降开始的拐点。
    若特征不明显则回退到第二次明显下降的起点，再失败则取主下降最陡点。
    """
    point = _turn_on_delta_vce_knee_point(vce, i0, i1, dt, vce_top)
    if point is None:
        return 0.0
    _, v_knee = point
    return max(0.0, float(vce_top - v_knee))


def _turn_on_ic_max_in_base_window(
    ic: np.ndarray,
    vce: np.ndarray,
    on0: int,
    on1: int,
    dt: float,
    ic_top: float,
    vce_top: float,
) -> float:
    """
    开通 Ic_on_max：
    在“电流 base 抬升开始”到“电压下降到 base 附近”区间内取 |Ic| 最大值。
    """
    n = len(ic)
    if n == 0:
        return 0.0
    s0 = max(0, min(on0, n - 2))
    s1 = max(s0 + 2, min(on1, n - 1))

    abs_ic = np.abs(ic)
    # 电流 base：开通前小窗中值
    pre0 = max(0, s0 - int(300e-9 / dt))
    pre1 = max(pre0 + 5, s0)
    ic_base = float(np.percentile(abs_ic[pre0:pre1], 50)) if pre1 > pre0 else 0.0
    ic_rise_th = ic_base + max(0.02 * max(ic_top, 1.0), 3.0)

    i_start = s0
    for k in range(s0, s1):
        if abs_ic[k] >= ic_rise_th:
            i_start = k
            break

    # 电压 base：开通后导通段小窗低分位
    post0 = min(n - 1, max(i_start + int(120e-9 / dt), s0))
    post1 = max(post0 + 10, min(s1, post0 + int(700e-9 / dt)))
    if post1 <= post0 + 5:
        post0 = max(s0, s1 - int(500e-9 / dt))
        post1 = s1
    vce_base = float(np.percentile(vce[post0:post1], 20)) if post1 > post0 else float(np.min(vce[s0:s1]))
    vce_base_th = vce_base + max(0.02 * max(vce_top, 1.0), 2.0)

    i_end = s1
    for k in range(i_start, s1):
        if vce[k] <= vce_base_th:
            i_end = k
            break
    if i_end <= i_start + 2:
        i_end = s1
    return float(np.max(abs_ic[i_start : i_end + 1]))


def _turn_on_current_top_after_rr_end(
    t: np.ndarray,
    ic: np.ndarray,
    irr: np.ndarray,
    v_diode: np.ndarray | None,
    on0: int,
    on1: int,
    dt: float,
) -> float:
    """
    开通电流：Ic 抬升后震荡结束平台 Ha（与 GUI 开通电流光标一致）。
    """
    from dpt_extractor.metrics.plateau_level import turn_on_current_hb_ha_t

    n = len(ic)
    if n == 0:
        return 0.0
    _hb, ha = turn_on_current_hb_ha_t(t, ic, on0, on1, dt)
    if ha > 1e-6:
        return float(ha)
    if v_diode is not None:
        win = err_energy_markers(
            t, irr, v_diode, on0, on1, dt, i_search_end=on1
        ).as_integration_window()
        a = max(0, min(win.i_end, n - 1))
    else:
        a = max(0, min(on1 - max(5, int(200e-9 / dt)), n - 1))
    b = min(n, a + max(5, int(200e-9 / dt)))
    if b <= a + 1:
        b = min(n, a + 5)
    seg = np.abs(ic[a:b])
    if len(seg) == 0:
        return 0.0
    return float(np.percentile(seg, 50))


def _turn_on_vce_on_max(
    t: np.ndarray,
    vge: np.ndarray,
    vce: np.ndarray,
    on0: int,
    on1: int,
    pulse2_on: int,
    pulse2_off: int,
    dt: float,
    vce_top: float,
) -> float:
    """开通 Vce_on_max：Vge 抬升到 Vce 低平台窗口内最大值。"""
    from dpt_extractor.metrics.plateau_level import turn_on_vce_on_max_value

    return turn_on_vce_on_max_value(
        t, vge, vce, on0, on1, pulse2_on, pulse2_off, dt, vce_top
    )


def _irr_peak(
    irr: np.ndarray,
    rr0: int,
    rr1: int,
    on_edge: int,
    on0: int,
    on1: int,
) -> float:
    """
    Reverse-recovery peak current magnitude from Irr channel.
    口径：从第二脉冲开通沿之后，在反向恢复窗内取主瓣同极性峰值（对齐示波器 Max 读数）。
    """
    return irr_parameter_peak_value(irr, rr0, rr1, on_edge, on0, on1)


def extract_all(
    bundle: WaveformBundle,
    profile: BridgeProfile,
    cfg: AppConfig,
) -> ExtractResult:
    t = bundle.t
    dt = bundle.dt
    n = bundle.n

    vge = bundle.get(profile.vge)
    vce = bundle.get(profile.vce)
    vce_other = _optional_channel(bundle, profile.v_diode)
    ic = try_bundle_total_current(bundle, profile)
    if ic is None:
        raise KeyError("缺少总电流通道，无法执行参数提取")
    rr_current = try_bundle_reverse_recovery_current(bundle, profile, ic)
    rr_current_available = rr_current is not None
    irr = rr_current if rr_current_available else np.zeros_like(t, dtype=np.float64)
    v_diode = vce_other
    vge_other = _optional_channel(bundle, profile.vge_other)

    unavailable: set[MetricKey] = set()
    if not rr_current_available:
        unavailable.update(_REVERSE_RECOVERY_CURRENT_METRICS)
    if vge_other is None:
        unavailable.update(
            {
                ("关断过程", "串扰电压"),
                ("开通", "串扰电压"),
            }
        )
    if v_diode is None:
        unavailable.update(
            {
                ("反向恢复", "Vrr"),
                ("反向恢复", "dv/dt"),
                ("反向恢复", "Pdmax"),
                ("反向恢复", "Err"),
            }
        )

    detector = PulseDetector(cfg)
    edges = detector.detect(t, vge, dt)
    segs = Segmenter(cfg).build(edges, n, dt, irr=irr, ic=ic, vce=vce)

    off0, off1 = segs.turn_off
    on0, on1 = segs.turn_on
    rr0, rr1 = segs.reverse_recovery
    single_pulse = edges.single_pulse or edges.detected_pulse_count < 2

    vdc = measure_vdc(
        t,
        vce,
        vge,
        ic,
        off0,
        off1,
        cfg,
        pulse_off_idx=edges.pulse1_off,
        dt=dt,
        vce_other=vce_other,
    )
    idc = measure_idc(ic, off0, off1, pulse_off_idx=edges.pulse1_off, dt=dt)

    # Condition voltage: scope-like "Top" during off-state plateau before turn-off.
    if single_pulse or edges.pulse2_on < edges.pulse1_off:
        top_start = max(0, edges.pulse1_on + int(100e-9 / dt))
        top_end = max(top_start + 2, edges.pulse1_off - int(200e-9 / dt))
    else:
        top_start = min(n - 1, edges.pulse1_off + int(300e-9 / dt))
        top_end = max(top_start + 2, edges.pulse2_on - int(200e-9 / dt))
    if top_end > top_start + 5:
        plateau = bus_voltage_plateau(vce, vce_other, top_start, top_end, 95.0)
        vdc_top = plateau if plateau is not None else vdc
        # 脉冲间关断平台是最可靠的母线电压基准；关断前窗若横跨切换沿会失真，
        # 故 plateau 可用时同步修正 canonical vdc（中位电平，贴近平均母线）。
        plateau_med = bus_voltage_plateau(vce, vce_other, top_start, top_end, 50.0)
        if plateau_med is not None:
            vdc = plateau_med
        ref_off = bus_voltage_before_off(
            vce, vce_other, edges.pulse1_off, dt
        )
        # ΔVce 关断尖峰参考电平应为母线电压：脉冲间关断平台（vdc）最可靠，
        # 而关断前 400ns 窗在 off_idx 贴近切换沿时会横跨抬升而失真，故统一以 vdc 为基准。
        vce_off_top = vdc
    else:
        vdc_top = vdc
        vce_off_top = vdc
        ref_off = None

    # --- Turn-off ---
    vce_off_max = float(np.max(vce[off0:off1]))
    if single_pulse:
        # With no inter-pulse DUT blocking plateau, vdc may legitimately come
        # from the opposite device's bus-voltage channel.  ΔVce/Ls_off cursors
        # must nevertheless remain on one DUT Vce waveform, so use the DUT's
        # own post-off ~200 ns stable-band centre as the local reference.
        single_top = turn_off_delta_vce_blocking_top(vce, off0, off1, dt)
        if np.isfinite(single_top) and 0.0 < single_top < vce_off_max:
            vce_off_top = float(single_top)
    fall_win = turn_off_ic_fall_window(
        t,
        vge,
        off0,
        off1,
        edges.pulse1_on,
        edges.pulse1_off,
        edges.pulse2_on,
        dt,
        cfg,
    )
    if fall_win is not None:
        ic_f0, ic_f1 = fall_win
    else:
        ic_f0, ic_f1 = off0, off1

    slope_active = default_slope_ranges()
    slope_active.update(cfg.slope_ranges)
    off_dv = slope_active["off_dvdt"]
    off_di = slope_active["off_didt"]
    dv_lo, dv_hi = off_dv.as_fractions()
    off_di_p0, off_di_p1 = off_di.as_fractions()
    off_dvdt_context = turn_off_dvdt_measurement_context(
        t,
        vce,
        off0,
        off1,
        dt,
        cfg,
        dv_lo,
        dv_hi,
        rise_start=ic_f0,
        rise_end=ic_f1,
        auto_max=off_dv.is_auto_max,
    )
    dvdt_o = float(off_dvdt_context.crossing.dvdt)
    off_didt_context = turn_off_didt_measurement_context(
        t,
        ic,
        off0,
        off1,
        edges.pulse1_on,
        edges.pulse1_off,
        ic_f0,
        ic_f1,
        dt,
        cfg,
        off_di_p0,
        off_di_p1,
        edge=off_di.ic_direction,
        next_pulse_on=edges.next_pulse_on,
        auto_max=off_di.is_auto_max,
    )
    # One canonical source keeps Ic_off_max, the displayed Ha/Top, percentage
    # thresholds, GUI cursors and report values identical even on the fallback
    # interval path where no dedicated Vge fall window is available.
    ic_off_max = float(off_didt_context.top_a)
    didt_o = float(off_didt_context.crossing.didt)

    # 关断尖峰相关量基于 Vce Top（尖峰减 Top）
    ls_off = (vce_off_max - vce_off_top) / (didt_o * 1e9) * 1e9 if didt_o > 1e-9 else 0.0

    td_off, tf, toff = turn_off_timings(
        t,
        vge,
        ic,
        off0,
        off1,
        edges.pulse1_off,
        dt,
        cfg,
        pulse1_on=edges.pulse1_on,
        pulse2_on=edges.pulse2_on,
    )
    win_off_scope = eoff_window_scope_example(
        t,
        ic,
        vce,
        off0,
        off1,
        edges.pulse1_off,
        dt,
        pre_ns=cfg.energy.eoff_pre_ns,
        pulse1_on=edges.pulse1_on,
    )
    eoff_scope = integrate_vi_window(t, vce, ic, win_off_scope)
    pmax_off = peak_power_kw(vce, ic, win_off_scope)
    # 按用户提供的示波器示例定义：t1=Vce离开base，t2=Ic回落到base。
    eoff = eoff_scope
    eoff_math = 0.0
    eoff_warn = False

    off_vmax, off_vmin = (
        crosstalk_extrema(vge_other, off0, off1, dt)
        if vge_other is not None
        else (0.0, 0.0)
    )
    turn_off = TurnOffResult(
        delta_vce=vce_off_max - vce_off_top,
        ic_off_max=ic_off_max,
        vce_off_max=vce_off_max,
        dvdt=dvdt_o,
        didt=didt_o,
        dvdt_range=slope_range_result_label(
            off_dv, off_dvdt_context.crossing
        ),
        didt_range=slope_range_result_label(
            off_di, off_didt_context.crossing
        ),
        ls_off=ls_off,
        toff=toff,
        td_off=td_off,
        tf=tf,
        crosstalk_v=off_vmax,
        crosstalk_vmax=off_vmax,
        crosstalk_vmin=off_vmin,
        pmax=pmax_off,
        eoff=eoff,
        eoff_range="V↑~Ic平稳",
        eoff_check=eoff_math,
        energy_warn=eoff_warn,
    )
    # User definition: "工况电流" uses pulse1 turn-off max total current
    idc = ic_off_max

    if single_pulse:
        return ExtractResult(
            vdc=vdc,
            idc=idc,
            vdc_set=vdc_top,
            idc_set=ic_off_max,
            turn_off=turn_off,
            turn_on=TurnOnResult(),
            reverse_recovery=ReverseRecoveryResult(),
            segments=segs,
            profile_name=profile.name,
            profile_code=profile.code,
            phase=profile.phase,
            source_path=bundle.meta.source_path,
            detected_pulse_count=edges.detected_pulse_count,
            off_pulse_index=edges.off_pulse_number,
            on_pulse_index=edges.on_pulse_number,
            single_pulse_mode=True,
            unavailable_metrics=unavailable,
        )

    # --- Turn-on ---
    rise_win = turn_on_ic_rise_window(
        t,
        vge,
        on0,
        on1,
        edges.pulse1_off,
        edges.pulse2_on,
        edges.pulse2_off,
        dt,
        cfg,
    )
    if rise_win is not None:
        ic_r0, ic_r1 = rise_win
        ic_on_peak, ic_on_plateau = ic_stats_in_window(ic, ic_r0, ic_r1)
    else:
        ic_r0, ic_r1 = on0, on1
        ic_on_peak, ic_on_plateau = ic_stats_in_window(ic, ic_r0, ic_r1)

    vce_on_max = float(np.max(vce[ic_r0 : ic_r1 + 1]))
    vge_on = vge[ic_r0 : ic_r1 + 1]
    ic_on = ic[ic_r0 : ic_r1 + 1]
    vge_span = float(np.max(vge_on) - np.min(vge_on))
    rise_idx = np.where(np.diff(vge_on) > 0.05 * max(vge_span, 1.0))[0]
    on_dv = slope_active["on_dvdt"]
    on_di = slope_active["on_didt"]
    on_dv_hi, on_dv_lo = on_dv.as_fractions()
    on_di_p0, on_di_p1 = on_di.as_fractions()
    ic_top_on = turn_on_ic_top(ic, edges.pulse2_on, edges.pulse2_off, dt)
    vce_top_on = turn_on_vce_top_from_ic_rise(
        ic, vce, edges.pulse2_on, edges.pulse2_off, dt
    )
    vce_on_max = _turn_on_vce_on_max(
        t, vge, vce, on0, on1, edges.pulse2_on, edges.pulse2_off, dt, vce_top_on
    )
    ic_on_max = _turn_on_ic_max_in_base_window(
        ic, vce, on0, on1, dt, ic_top_on, vce_top_on
    )
    # 开通斜率：在完整开通段内按 Top 百分比找穿越（Vge 上升窗不含 Vce 跌落/电流上升）
    on_dvdt_context = turn_on_dvdt_measurement_context(
        t,
        vce,
        vce_top_on,
        on0,
        on1,
        dt,
        cfg,
        on_dv_hi,
        on_dv_lo,
        event_end_idx=edges.pulse2_off,
        auto_max=on_dv.is_auto_max,
    )
    dvdt_on_v = float(on_dvdt_context.crossing.dvdt)
    on_didt_context = turn_on_didt_measurement_context(
        t,
        ic,
        on0,
        on1,
        dt,
        on_di_p0,
        on_di_p1,
        edge=on_di.ic_direction,
        event_end_idx=edges.pulse2_off,
        auto_max=on_di.is_auto_max,
    )
    turn_on_current = float(on_didt_context.top_a)
    didt_on_v = float(on_didt_context.crossing.didt)
    on_didt_available = (
        not on_didt_context.used_fallback
        and on_didt_context.crossing.t_pct_a_s is not None
        and on_didt_context.crossing.t_pct_b_s is not None
        and didt_on_v > 1e-9
    )
    if not on_didt_available:
        unavailable.update({("开通", "di/dt"), ("开通", "Ls_on")})
    on_current_available = (
        np.isfinite(turn_on_current)
        and on_didt_context.top_window is not None
        and on_didt_context.top_window[0] >= 0
        and on_didt_context.top_window[1] >= on_didt_context.top_window[0]
    )
    if not on_current_available:
        unavailable.add(("开通", "开通电流"))
        turn_on_current = 0.0

    # 开通杂散电感：Ls_on = 开通 ΔVce / (开通 di/dt)，与 Ls_off 口径对称（ΔVce 可光标卡值）
    delta_vce_on = _turn_on_delta_vce(vce, on0, on1, dt, vce_top_on)
    ls_on = delta_vce_on / didt_on_v if on_didt_available else 0.0

    on_timing = turn_on_timing_instants(
        t,
        vge,
        ic,
        on0,
        on1,
        edges.pulse2_on,
        dt,
        cfg,
        pulse2_off=edges.pulse2_off,
    )
    td_on = float(on_timing.td_on_ns)
    tr = float(on_timing.tr_ns)
    ton = float(on_timing.ton_ns)
    if on_timing.t_i10_s is None or on_timing.t_i90_s is None:
        unavailable.update(_TURN_ON_TIMING_METRICS)
    elif on_timing.t_v10_s is None:
        unavailable.update({("开通", "Ton"), ("开通", "Td_on")})
    # 按用户示波器口径：t1=Ic离开base，t2=Vce回落到base（与关断窗口定义对称）
    win_on_scope = eon_window_scope_example(
        t,
        ic,
        vce,
        on0,
        on1,
        edges.pulse2_on,
        dt,
        pulse1_off=edges.pulse1_off,
    )
    # 开通损耗按用户口径：窗口精确到“电流base刚结束 -> 电压base刚回落”，积分用原始 V*I
    eon = integrate_vi_window(t, vce, ic, win_on_scope)
    pmax_on = peak_power_kw(vce, ic, win_on_scope)
    eon_math = 0.0
    eon_warn = False

    on_vmax, on_vmin = (
        crosstalk_extrema(vge_other, on0, on1, dt)
        if vge_other is not None
        else (0.0, 0.0)
    )
    turn_on = TurnOnResult(
        delta_vce=delta_vce_on,
        ic_on_max=ic_on_max,
        vce_on_max=vce_on_max,
        turn_on_current=turn_on_current,
        dvdt=dvdt_on_v,
        didt=didt_on_v,
        dvdt_range=slope_range_result_label(
            on_dv, on_dvdt_context.crossing
        ),
        didt_range=slope_range_result_label(
            on_di, on_didt_context.crossing
        ),
        ls_on=ls_on,
        ton=ton,
        td_on=td_on,
        tr=tr,
        crosstalk_v=on_vmax,
        crosstalk_vmax=on_vmax,
        crosstalk_vmin=on_vmin,
        pmax=pmax_on,
        eon=eon,
        eon_check=eon_math,
        energy_warn=eon_warn,
    )

    # --- Reverse recovery ---
    irr_peak = _irr_peak(irr, rr0, rr1, edges.pulse2_on, on0, on1)
    # Vrr 口径：开通过程中换流二极管电压最大值
    vrr = float(np.max(v_diode[on0:on1])) if v_diode is not None else 0.0
    # 指导书：di/dt(1)=0.9*IDM->0.1*IDM，dv/dt(1)=0.1*(-VDM)->0.9*(-VDM)
    if v_diode is not None:
        rr_s0, rr_s1, rr_window_completed = (
            rr_completed_measurement_window_indices(
                on0,
                rr1,
                on1,
                v_diode,
                len(t),
                dt,
            )
        )
    else:
        rr_s0, rr_s1 = rr_slope_window_indices(on0, rr1, len(t), dt)
        rr_window_completed = False
    rr_context_i1 = rr_s1 if rr_window_completed else rr1
    # 反向恢复 di/dt、dv/dt：由 GUI “范围取值”选择百分比计算
    rr_dv = slope_active["rr_dvdt"]
    rr_di = slope_active["rr_didt"]
    dv_a, dv_b = rr_dv.as_fractions()
    di_a, di_b = rr_di.as_fractions()
    pct_lo = min(dv_a, dv_b)
    pct_hi = max(dv_a, dv_b)
    rr_dvdt_settled_platform = rr_dvdt_prefers_settled_platform(
        irr,
        irr_peak,
        on1,
        edges.pulse2_off,
        dt,
    )
    rr_dvdt_context = (
        rr_dvdt_measurement_context(
            t,
            v_diode,
            rr_s0,
            rr_s1,
            dt,
            cfg,
            pct_lo,
            pct_hi,
            fallback_i0=rr0,
            fallback_i1=rr_context_i1,
            use_settled_platform=rr_dvdt_settled_platform,
            event_end_idx=on1,
            auto_max=rr_dv.is_auto_max,
        )
        if v_diode is not None
        else None
    )
    dvdt_rr = (
        float(rr_dvdt_context.crossing.dvdt)
        if rr_dvdt_context is not None
        else 0.0
    )
    rr_measure = rr_di.ic_reference if rr_di.ic_reference in ("idm", "if_irm") else "idm"
    rr_didt_context = rr_didt_measurement_context(
        t,
        irr,
        rr_s0,
        rr_s1,
        dt,
        cfg,
        di_a,
        di_b,
        measure=rr_measure,
        rr_i0=rr0,
        rr_i1=rr_context_i1,
        fallback_i0=rr0,
        fallback_i1=rr_context_i1,
        auto_max=rr_di.is_auto_max,
    )
    didt_rr = float(rr_didt_context.crossing.didt)
    # Trr 与 GUI 默认卡尺共用同一套 Ha/A/B 主恢复瓣交点逻辑
    trr = reverse_recovery_trr(
        t,
        irr,
        v_diode if v_diode is not None else np.zeros_like(irr),
        on0,
        on1,
        dt,
        cfg,
        rr0=rr0,
        rr1=rr1,
        on_edge=segs.pulse2_on,
        pulse2_off=segs.pulse2_off,
    )
    if not np.isfinite(trr) or trr <= 0.0:
        # A zero value here means the logical Irr main lobe did not provide
        # both real stable-platform intersections.  Do not publish a plausible
        # numeric zero or let the GUI fabricate a generic Ic cursor card.
        trr = 0.0
        unavailable.add(("反向恢复", "Trr"))
    # Err 按示波器口径：从反向谷值到电流/电压同时回到 base 的区间积分
    if v_diode is not None:
        win_rr_scope = err_energy_markers(
            t,
            irr,
            v_diode,
            rr0,
            rr_context_i1,
            dt,
            i_search_end=on1,
            vge=vge,
            pulse1_off=segs.pulse1_off,
            pulse2_on=segs.pulse2_on,
            pulse2_off=segs.pulse2_off,
            dc_current=idc,
            lower_bridge_irr_from_ic_minus_il=profile.irr_from_ic_minus_il,
        ).as_integration_window()
        err = integrate_err_recovery(t, v_diode, irr, win_rr_scope)
        pdmax_rr = peak_power_kw(v_diode, irr, win_rr_scope, absolute=True)
    else:
        err = 0.0
        pdmax_rr = 0.0
    err_math = 0.0
    err_warn = False

    reverse_recovery = ReverseRecoveryResult(
        irr=irr_peak,
        trr=trr,
        vrr=vrr,
        dvdt_max=dvdt_rr,
        didt_irr=didt_rr,
        dvdt_range=(
            slope_range_result_label(rr_dv, rr_dvdt_context.crossing)
            if rr_dvdt_context is not None
            else rr_dv.label()
        ),
        didt_range=slope_range_result_label(
            rr_di, rr_didt_context.crossing
        ),
        pdmax=pdmax_rr,
        err=err,
        err_check=err_math,
        energy_warn=err_warn,
    )

    return ExtractResult(
        vdc=vdc,
        idc=idc,
        vdc_set=vdc_top,
        idc_set=ic_off_max,
        turn_off=turn_off,
        turn_on=turn_on,
        reverse_recovery=reverse_recovery,
        segments=segs,
        profile_name=profile.name,
        profile_code=profile.code,
        phase=profile.phase,
        source_path=bundle.meta.source_path,
        detected_pulse_count=edges.detected_pulse_count,
        off_pulse_index=edges.off_pulse_number,
        on_pulse_index=edges.on_pulse_number,
        single_pulse_mode=False,
        unavailable_metrics=unavailable,
    )
