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
    turn_off_ic_top,
    turn_on_ic_top,
    turn_on_vce_top_from_ic_rise,
    turn_off_timings,
    turn_on_ic_rise_window,
    turn_on_timings,
)
from dpt_extractor.metrics.iec_windows import (
    eoff_window_scope_example,
    eon_window_scope_example,
    err_window_scope_example,
    err_energy_markers,
    energy_window_power,
    integrate_err_recovery,
    integrate_vi_window,
    rr_slope_window_indices,
)
from dpt_extractor.metrics.irr_measure import irr_parameter_peak_value
from dpt_extractor.metrics.slopes import (
    didt_diode_recovery,
    didt_max,
    didt_off,
    didt_on,
    dvdt_diode_recovery,
    dvdt_max,
    dvdt_off,
    dvdt_on,
)
from dpt_extractor.models.slope_range import SlopeRange, default_slope_ranges
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
    ("反向恢复", "Err"),
}


def _optional_channel(bundle: WaveformBundle, col: str) -> np.ndarray | None:
    if not col:
        return None
    return bundle.channels.get(col)


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

    # 三斜率形态：下降速度曲线上有两个持续高速段，中间夹着较缓的中间斜率段。
    # 此时人工卡尺更稳定的位置是两个高速段之间的时间中点。
    dv_state = _smooth_edge_padded(dv_fall, min(101, max(9, (len(dv_fall) // 80) | 1)))
    state_win = dv_state[j0 : j1 + 1]
    state_peak = float(max(np.max(state_win), 1e-12))
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
    vce: np.ndarray,
    on0: int,
    on1: int,
    dt: float,
    vce_top: float,
) -> float:
    """开通 Vce_on_max：跌落前 200ns 平台窗内最大值。"""
    from dpt_extractor.metrics.plateau_level import turn_on_vce_on_max_value

    return turn_on_vce_on_max_value(vce, on0, on1, dt, vce_top)


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
        ic_off_max = float(np.max(np.abs(ic[ic_f0 : ic_f1 + 1])))
        ic_top = turn_off_ic_top(
            ic, edges.pulse1_on, edges.pulse1_off, ic_f0, dt
        )
    else:
        ic_f0, ic_f1 = off0, off1
        ic_off_max = float(np.max(np.abs(ic[off0:off1])))
        ic_top = float(np.percentile(np.abs(ic[off0:off1]), 95))

    slope_active = default_slope_ranges()
    slope_active.update(cfg.slope_ranges)
    off_dv = slope_active["off_dvdt"]
    off_di = slope_active["off_didt"]
    dv_lo, dv_hi = off_dv.as_fractions()
    off_di_p0, off_di_p1 = off_di.as_fractions()
    dvdt_o = dvdt_off(
        t,
        vce,
        vdc_top,
        ic_f0,
        ic_f1 + 1,
        cfg,
        pct_lo=dv_lo,
        pct_hi=dv_hi,
        vce_top=vdc_top,
    )
    if dvdt_o < 1e-6:
        dvdt_o = dvdt_max(t, vce, ic_f0, ic_f1 + 1, dt, cfg)
    # 关断 di/dt：Vge 下降窗内搜穿越；阈值 = Top% × 关断前电流 Top（100% Ic）
    didt_o = didt_off(
        t,
        ic,
        ic_f0,
        ic_f1 + 1,
        cfg,
        pct_start=off_di_p0,
        pct_end=off_di_p1,
        ic_reference=off_di.ic_reference,
        ic_direction=off_di.ic_direction,
        icm_override=ic_top,
        search_from_peak=False,
    )
    if didt_o < 1e-6:
        didt_o = didt_max(t, ic, ic_f0, ic_f1 + 1, dt, cfg)

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
        dvdt_range=off_dv.label(),
        didt_range=off_di.label(),
        ls_off=ls_off,
        toff=toff,
        td_off=td_off,
        tf=tf,
        crosstalk_v=off_vmax,
        crosstalk_vmax=off_vmax,
        crosstalk_vmin=off_vmin,
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
    vce_on_max = _turn_on_vce_on_max(vce, on0, on1, dt, vce_top_on)
    ic_on_max = _turn_on_ic_max_in_base_window(
        ic, vce, on0, on1, dt, ic_top_on, vce_top_on
    )
    turn_on_current = _turn_on_current_top_after_rr_end(
        t, ic, irr, v_diode, on0, on1, dt
    )
    # 开通斜率：在完整开通段内按 Top 百分比找穿越（Vge 上升窗不含 Vce 跌落/电流上升）
    dvdt_on_v = dvdt_on(
        t,
        vce,
        vce_top_on,
        on0,
        on1 + 1,
        cfg,
        pct_hi=on_dv_hi,
        pct_lo=on_dv_lo,
        vce_top=vce_top_on,
    )
    if dvdt_on_v < 1e-6:
        dvdt_on_v = dvdt_max(t, vce, on0, on1 + 1, dt, cfg)
    didt_on_v = didt_on(
        t,
        ic,
        on0,
        on1 + 1,
        cfg,
        pct_start=on_di_p0,
        pct_end=on_di_p1,
        ic_reference=on_di.ic_reference,
        ic_direction=on_di.ic_direction,
        icm_override=ic_top_on,
        search_from_peak=False,
    )
    if didt_on_v < 1e-6:
        didt_on_v = didt_max(t, ic, on0, on1 + 1, dt, cfg)

    # 开通杂散电感：Ls_on = 开通 ΔVce / (开通 di/dt)，与 Ls_off 口径对称（ΔVce 可光标卡值）
    delta_vce_on = _turn_on_delta_vce(vce, on0, on1, dt, vce_top_on)
    ls_on = delta_vce_on / didt_on_v if didt_on_v > 1e-9 else 0.0

    td_on, tr, ton = turn_on_timings(t, vge, ic, on0, on1, edges.pulse2_on, dt, cfg)
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
        dvdt_range=on_dv.label(),
        didt_range=on_di.label(),
        ls_on=ls_on,
        ton=ton,
        td_on=td_on,
        tr=tr,
        crosstalk_v=on_vmax,
        crosstalk_vmax=on_vmax,
        crosstalk_vmin=on_vmin,
        eon=eon,
        eon_check=eon_math,
        energy_warn=eon_warn,
    )

    # --- Reverse recovery ---
    irr_peak = _irr_peak(irr, rr0, rr1, edges.pulse2_on, on0, on1)
    # Vrr 口径：开通过程中换流二极管电压最大值
    vrr = float(np.max(v_diode[on0:on1])) if v_diode is not None else 0.0
    # 指导书：di/dt(1)=0.9*IDM->0.1*IDM，dv/dt(1)=0.1*(-VDM)->0.9*(-VDM)
    rr_s0, rr_s1 = rr_slope_window_indices(on0, rr1, len(t), dt)
    # 反向恢复 di/dt、dv/dt：由 GUI “范围取值”选择百分比计算
    rr_dv = slope_active["rr_dvdt"]
    rr_di = slope_active["rr_didt"]
    dv_a, dv_b = rr_dv.as_fractions()
    di_a, di_b = rr_di.as_fractions()
    pct_lo = min(dv_a, dv_b)
    pct_hi = max(dv_a, dv_b)
    pct_hi_di = max(di_a, di_b)
    pct_lo_di = min(di_a, di_b)
    dvdt_rr = (
        dvdt_diode_recovery(t, v_diode, rr_s0, rr_s1, pct_lo=pct_lo, pct_hi=pct_hi)
        if v_diode is not None
        else 0.0
    )
    rr_measure = rr_di.ic_reference if rr_di.ic_reference in ("idm", "if_irm") else "idm"
    didt_rr = didt_diode_recovery(
        t,
        irr,
        rr_s0,
        rr_s1,
        pct_hi=pct_hi_di,
        pct_lo=pct_lo_di,
        measure=rr_measure,
    )
    if v_diode is not None and dvdt_rr < 1e-6:
        dvdt_rr = dvdt_max(t, v_diode, rr0, rr1, dt, cfg)
    if didt_rr < 1e-6:
        didt_rr = didt_max(t, irr, rr0, rr1, dt, cfg)
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
    )
    # Err 按示波器口径：从反向谷值到电流/电压同时回到 base 的区间积分
    if v_diode is not None:
        win_rr_scope = err_energy_markers(
            t, irr, v_diode, rr0, rr1, dt, i_search_end=on1
        ).as_integration_window()
        err = integrate_err_recovery(t, v_diode, irr, win_rr_scope)
    else:
        err = 0.0
    err_math = 0.0
    err_warn = False

    reverse_recovery = ReverseRecoveryResult(
        irr=irr_peak,
        trr=trr,
        vrr=vrr,
        dvdt_max=dvdt_rr,
        didt_irr=didt_rr,
        dvdt_range=rr_dv.label(),
        didt_range=rr_di.label(),
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
