from __future__ import annotations

import os
import unittest
from pathlib import Path

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_windows import (
    _loss_cursor_event_gate_after_main_edge,
    _err_ha_top_from_offset_window,
    _err_recovery_settled_base,
    _first_sustained_rise_crossing,
    _quiet_local_platform_level,
    eoff_energy_markers,
    eoff_window_scope_example,
    eon_energy_markers,
    err_energy_markers,
    err_recovery_peak_index,
    integrate_err_recovery,
    integrate_vi_window,
)
from dpt_extractor.models.waveform import bundle_reverse_recovery_current
from dpt_extractor.models.bridge_profile import UPPER_BRIDGE, guess_profile_from_path
from dpt_extractor.models.waveform import bundle_total_current
from dpt_extractor.metrics.plateau_level import (
    dvdt_rr_vd_base_top,
    turn_on_ic_a_cross_hb_us,
    turn_on_ic_b_cross_ha_us,
    turn_on_ic_link_default_times,
)
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.tests.sample_paths import sample_tss

import numpy as np

WH = sample_tss("WH_480V_800A_000.tss")
ROOT = Path(__file__).resolve().parents[2]
UH = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "SSM1R7PB12B3DTFMMSPP25M4CF0016"
    / "SSS"
    / "RT"
    / "tss"
    / "UH_750V_1050A_000.tss"
)
SMC_RT_UH = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "UH_750V_1048A_000.tss"
)
SMC_RT_UH_403 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "UH_600V_403A_000.tss"
)
SMC_RT_UL_806 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "UL_750V_806A_000.tss"
)
SMC_RT_VH_806 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "VH_750V_806A_000.tss"
)
SMC_RT_VL_806 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "VL_750V_806A_000.tss"
)
SMC_RT_VL_1048 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "VL_750V_1048A_000.tss"
)
SMC_RT_VH_403 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "VH_600V_403A_000.tss"
)
SONG_SMC_RT = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
)
SONG_SMC_RT_UH_1048 = SONG_SMC_RT / "UH_750V_1048A_000.tss"
SONG_SMC_RT_VL_806 = SONG_SMC_RT / "VL_750V_806A_000.tss"
SONG_SMC_RT_VL_1048 = SONG_SMC_RT / "VL_750V_1048A_000.tss"
GCU_LT_UH_500 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2506"
    / "GCU"
    / "SMC"
    / "LT"
    / "tss"
    / "UH_480V_500A_000.tss"
)
LOW_CURRENT_WH = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2506"
    / "DCU"
    / "SMC"
    / "LT"
    / "tss"
    / "WH_480V_100A_000.tss"
)
SOFT_ERR_WH = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2506"
    / "DCU"
    / "SMC"
    / "RT"
    / "tss"
    / "WH_480V_800A_000.tss"
)
SSS_RT_UL_1050 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "SSM1R7PB12B3DTFMMSPP25M4CF0016"
    / "SSS"
    / "RT"
    / "tss"
    / "UL_750V_1050A_000.tss"
)
SSS_RT_UL_805 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "SSM1R7PB12B3DTFMMSPP25M4CF0016"
    / "SSS"
    / "RT"
    / "tss"
    / "UL_750V_805A_000.tss"
)
SSS_LT_UH_1050 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "SSM1R7PB12B3DTFMMSPP25M4CF0016"
    / "SSS"
    / "LT"
    / "tss"
    / "UH-750V-1050A_000.tss"
)


def _assert_crossing(
    case: unittest.TestCase,
    t: np.ndarray,
    y: np.ndarray,
    t_cross: float,
    level: float,
    direction: str,
    *,
    delta: float = 0.75,
) -> None:
    y_at = float(np.interp(t_cross, t, y))
    case.assertAlmostEqual(y_at, level, delta=delta)
    k = int(np.searchsorted(t, t_cross, side="right")) - 1
    k = max(0, min(k, len(t) - 2))
    candidates = [k - 1, k] if k > 0 else [k]
    ok = False
    for kk in candidates:
        y0, y1 = float(y[kk]), float(y[kk + 1])
        if direction == "falling":
            ok = y0 >= level and y1 <= level and y0 > y1
        elif direction == "rising":
            ok = y0 <= level and y1 >= level and y1 > y0
        elif direction == "any":
            d0, d1 = y0 - level, y1 - level
            ok = (d0 == 0.0 and d1 != 0.0) or (d0 * d1 <= 0.0 and d0 != d1)
        else:
            raise ValueError(direction)
        if ok:
            break
    case.assertTrue(ok, f"{direction} crossing not found at {t_cross * 1e6:.3f} us")


def _assert_vd_main_rise_after(
    case: unittest.TestCase,
    t: np.ndarray,
    vd: np.ndarray,
    t_cross: float,
    hb: float,
    *,
    within_s: float = 120e-9,
    min_rise_v: float = 30.0,
) -> None:
    vd_at_cross = float(np.interp(float(t_cross), t, vd))
    case.assertAlmostEqual(
        vd_at_cross,
        float(hb),
        delta=1e-3,
        msg="B 必须是 Vd 曲线与 Hb 横线的真实交点",
    )
    i0 = int(np.searchsorted(t, t_cross, side="left"))
    i1 = int(np.searchsorted(t, t_cross + within_s, side="right"))
    i0 = max(0, min(i0, len(vd) - 1))
    i1 = max(i0 + 1, min(i1, len(vd)))
    case.assertGreaterEqual(
        float(np.max(vd[i0:i1])) - float(hb),
        min_rise_v,
        "B 应贴 Vd 主上升沿与 Hb 的交点",
    )


class TestEoffWindow(unittest.TestCase):
    def test_loss_cursor_event_gate_uses_200ns_base_and_upper_cap(self):
        dt = 1e-9
        t = np.arange(1600, dtype=np.float64) * dt
        y = np.zeros_like(t)
        first_ix = 100
        # Main local ringing packet stays inside the event cap.
        k = np.arange(first_ix, 950)
        y[k] = 45.0 * np.exp(-(k - first_ix) / 260.0) * np.sin(
            2.0 * np.pi * (k - first_ix) / 44.0
        )
        # A later unrelated tail must not expand the same cursor event forever.
        late = np.arange(1250, 1360)
        y[late] = 80.0 * np.sin(2.0 * np.pi * (late - 1250) / 26.0)

        gate = _loss_cursor_event_gate_after_main_edge(
            t,
            y,
            0.0,
            first_ix,
            len(y) - 2,
            float(t[first_ix + 8]),
            dt,
            400.0,
            1.0,
            "current_fall",
        )

        self.assertGreaterEqual((gate.end_idx - gate.start_idx) * dt, 195e-9)
        self.assertLessEqual((gate.cap_idx - gate.start_idx) * dt, 851e-9)
        self.assertLessEqual(gate.end_idx, gate.cap_idx)
        self.assertIn(gate.classification, {"smooth", "damped", "ringing"})

    def test_left_cursor_uses_first_sustained_rising_crossing(self):
        dt = 1e-9
        level = 0.0
        y = np.full(260, -4.0, dtype=np.float64)
        y[40:48] = [-2.0, 1.0, -1.0, 0.6, -0.8, 0.4, -1.0, -2.0]
        y[120:170] = np.linspace(-3.0, 120.0, 50)
        y[170:] = 120.0

        ix = _first_sustained_rise_crossing(
            y,
            level,
            30,
            160,
            150,
            dt,
            120.0,
        )

        self.assertIsNotNone(ix)
        assert ix is not None
        self.assertGreaterEqual(ix, 120)
        self.assertLess(ix, 123)

    def test_eon_markers_fall_back_when_pulse2_on_outside_turn_on_segment(self):
        dt = 1e-9
        t = np.arange(2000, dtype=np.float64) * dt
        ic = np.zeros_like(t)
        vce = np.full_like(t, 500.0)
        i0, i1 = 1000, 1500
        ic[i0 : i1 + 1] = np.linspace(0.0, 100.0, i1 - i0 + 1)
        ic[i1 + 1 :] = 100.0
        vce[i0 : i1 + 1] = np.linspace(500.0, 5.0, i1 - i0 + 1)
        vce[i1 + 1 :] = 5.0

        mk = eon_energy_markers(
            t,
            ic,
            vce,
            i0,
            i1,
            on_idx=100,
            dt=dt,
            pulse1_off=900,
        )

        self.assertGreaterEqual(mk.i_start, i0)
        self.assertLessEqual(mk.i_end, i1)
        self.assertGreater(mk.t_end, mk.t_start)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_scope_window_near_manual_reference(self):
        bundle = load_waveform(UH)
        cfg = load_config()
        result = extract_all(bundle, UPPER_BRIDGE, cfg)
        segs = result.segments
        assert segs is not None
        t = bundle.t
        ic = bundle_total_current(bundle, UPPER_BRIDGE)
        vce = bundle.get(UPPER_BRIDGE.vce)
        w = eoff_window_scope_example(
            t,
            ic,
            vce,
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_off,
            bundle.dt,
            pre_ns=cfg.energy.eoff_pre_ns,
            pulse1_on=segs.pulse1_on,
        )
        t0_us = w.t_start * 1e6
        t1_us = w.t_end * 1e6
        self.assertGreater(t0_us, 14.50)
        self.assertLess(t0_us, 14.54)
        self.assertGreater(t1_us, 14.77)
        self.assertLess(t1_us, 14.98)
        e = integrate_vi_window(t, vce, ic, w)
        self.assertGreater(e, 82.0)
        self.assertLess(e, 96.0)
        mk = eoff_energy_markers(
            t,
            ic,
            vce,
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_off,
            bundle.dt,
            pre_ns=cfg.energy.eoff_pre_ns,
            pulse1_on=segs.pulse1_on,
        )
        self.assertLess(mk.ha_v, 25.0, "关断 Ha 应为导通低 Vce 平台")
        self.assertGreater(mk.hb_a, 5.0, "关断 Hb 应为回落后残余电流平台")
        self.assertAlmostEqual(mk.t_start, w.t_start, delta=50e-9)
        self.assertAlmostEqual(mk.t_end, w.t_end, delta=50e-9)
        _assert_crossing(self, t, ic, mk.t_end, mk.hb_a, "any")

    @unittest.skipUnless(SMC_RT_UH.exists(), "SMC RT UH sample missing")
    def test_smc_rt_eoff_ha_uses_vce_base_not_rise_foot(self):
        bundle = load_waveform(SMC_RT_UH)
        profile = guess_profile_from_path(str(SMC_RT_UH))
        cfg = load_config()
        result = extract_all(bundle, profile, cfg)
        segs = result.segments
        assert segs is not None
        t = bundle.t
        ic = bundle_total_current(bundle, profile)
        vce = bundle.get(profile.vce)
        mk = eoff_energy_markers(
            t,
            ic,
            vce,
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_off,
            bundle.dt,
            pre_ns=cfg.energy.eoff_pre_ns,
            pulse1_on=segs.pulse1_on,
        )
        v_at_a = float(np.interp(mk.t_start, t, vce))
        self.assertAlmostEqual(mk.ha_v, 12.34375, delta=0.5)
        self.assertAlmostEqual(v_at_a, mk.ha_v, delta=0.5)
        _assert_crossing(self, t, ic, mk.t_end, mk.hb_a, "any")
        self.assertLess(mk.ha_v, 15.0)
        self.assertGreater(mk.t_start * 1e6, 14.68)
        self.assertLess(mk.t_start * 1e6, 14.74)

    @unittest.skipUnless(SMC_RT_UL_806.exists(), "SMC RT UL 806A sample missing")
    def test_smc_rt_ul_806_eoff_a_uses_main_rise_ha_crossing(self):
        bundle = load_waveform(SMC_RT_UL_806)
        profile = guess_profile_from_path(str(SMC_RT_UL_806))
        cfg = load_config()
        result = extract_all(bundle, profile, cfg)
        segs = result.segments
        assert segs is not None
        t = bundle.t
        ic = bundle_total_current(bundle, profile)
        vce = bundle.get(profile.vce)
        mk = eoff_energy_markers(
            t,
            ic,
            vce,
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_off,
            bundle.dt,
            pre_ns=cfg.energy.eoff_pre_ns,
            pulse1_on=segs.pulse1_on,
        )
        t_a_us = mk.t_start * 1e6
        v_at_a = float(np.interp(mk.t_start, t, vce))
        i_aft = int(np.searchsorted(t, mk.t_start + 120e-9))
        i_aft = min(i_aft, segs.turn_off[1])
        v_after = float(np.max(vce[mk.i_start : i_aft + 1]))
        swing = max(float(result.turn_off.vce_off_max) - mk.ha_v, 1.0)
        self.assertGreater(t_a_us, 11.55)
        self.assertLess(t_a_us, 11.59)
        self.assertAlmostEqual(v_at_a, mk.ha_v, delta=0.5)
        _assert_crossing(self, t, ic, mk.t_end, mk.hb_a, "any")
        self.assertGreater(v_after, mk.ha_v + 0.3 * swing)

    @unittest.skipUnless(SMC_RT_VH_806.exists(), "SMC RT VH 806A sample missing")
    def test_smc_rt_vh_806_smooth_eoff_b_uses_early_settled_crossing(self):
        bundle = load_waveform(SMC_RT_VH_806)
        profile = guess_profile_from_path(str(SMC_RT_VH_806))
        cfg = load_config()
        result = extract_all(bundle, profile, cfg)
        segs = result.segments
        assert segs is not None
        t = bundle.t
        ic = bundle_total_current(bundle, profile)
        vce = bundle.get(profile.vce)
        mk = eoff_energy_markers(
            t,
            ic,
            vce,
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_off,
            bundle.dt,
            pre_ns=cfg.energy.eoff_pre_ns,
            pulse1_on=segs.pulse1_on,
        )
        self.assertAlmostEqual(mk.t_end * 1e6, 11.410, delta=0.020)
        self.assertLess(mk.t_end * 1e6, 11.46)
        _assert_crossing(self, t, ic, mk.t_end, mk.hb_a, "any")

    @unittest.skipUnless(SMC_RT_VL_806.exists(), "SMC RT VL 806A sample missing")
    def test_smc_rt_vl_806_noisy_eoff_b_rejects_smooth_early_crossing(self):
        bundle = load_waveform(SMC_RT_VL_806)
        profile = guess_profile_from_path(str(SMC_RT_VL_806))
        cfg = load_config()
        result = extract_all(bundle, profile, cfg)
        segs = result.segments
        assert segs is not None
        t = bundle.t
        ic = bundle_total_current(bundle, profile)
        vce = bundle.get(profile.vce)
        mk = eoff_energy_markers(
            t,
            ic,
            vce,
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_off,
            bundle.dt,
            pre_ns=cfg.energy.eoff_pre_ns,
            pulse1_on=segs.pulse1_on,
        )
        self.assertAlmostEqual(mk.t_end * 1e6, 11.993, delta=0.020)
        self.assertGreater(mk.t_end * 1e6, 11.90)
        _assert_crossing(self, t, ic, mk.t_end, mk.hb_a, "any")

    @unittest.skipUnless(GCU_LT_UH_500.exists(), "GCU LT UH 500A sample missing")
    def test_gcu_lt_uh_500_eoff_hb_uses_local_post_off_base(self):
        bundle = load_waveform(GCU_LT_UH_500)
        profile = guess_profile_from_path(str(GCU_LT_UH_500))
        cfg = load_config()
        result = extract_all(bundle, profile, cfg)
        segs = result.segments
        assert segs is not None
        t = bundle.t
        dt = bundle.dt
        ic = bundle_total_current(bundle, profile)
        vce = bundle.get(profile.vce)
        mk = eoff_energy_markers(
            t,
            ic,
            vce,
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_off,
            dt,
            pre_ns=cfg.energy.eoff_pre_ns,
            pulse1_on=segs.pulse1_on,
        )

        off_idx = int(segs.pulse1_off)
        post_end = min(len(ic) - 1, segs.turn_off[1], off_idx + int(900e-9 / dt))
        post = ic[off_idx : post_end + 1].astype(np.float64)
        early_len = max(12, int(120e-9 / dt))
        early = float(np.mean(post[:early_len]))
        local_platform = _quiet_local_platform_level(post, dt)

        self.assertGreater(abs(early - local_platform), 10.0)
        self.assertAlmostEqual(mk.hb_a, local_platform, delta=0.5)
        self.assertLess(abs(mk.hb_a), abs(early))
        _assert_crossing(self, t, ic, mk.t_end, mk.hb_a, "any")

    @unittest.skipUnless(LOW_CURRENT_WH.exists(), "low-current WH sample missing")
    def test_low_current_eoff_ha_uses_vce_base_not_foot(self):
        bundle = load_waveform(LOW_CURRENT_WH)
        profile = guess_profile_from_path(str(LOW_CURRENT_WH))
        cfg = load_config()
        result = extract_all(bundle, profile, cfg)
        segs = result.segments
        assert segs is not None
        t = bundle.t
        ic = bundle_total_current(bundle, profile)
        vce = bundle.get(profile.vce)
        mk = eoff_energy_markers(
            t,
            ic,
            vce,
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_off,
            bundle.dt,
            pre_ns=cfg.energy.eoff_pre_ns,
            pulse1_on=segs.pulse1_on,
        )
        v_at_a = float(np.interp(mk.t_start, t, vce))
        self.assertAlmostEqual(v_at_a, mk.ha_v, delta=0.5)
        self.assertLess(mk.ha_v, 5.0)
        self.assertLess(v_at_a, 5.0)

    @unittest.skipUnless(WH.exists(), "WH sample missing")
    def test_wh_eon_b_at_vce_hb_fall_cross(self):
        """WH 慢拖尾：B 须为 Vce 与 Hb 下降穿越，而非 A+450ns 回退。"""
        bundle = load_waveform(WH)
        profile = guess_profile_from_path(str(WH))
        cfg = load_config()
        result = extract_all(bundle, profile, cfg)
        segs = result.segments
        assert segs is not None
        t = bundle.t
        ic = bundle_total_current(bundle, profile)
        vce = bundle.get(profile.vce)
        mk = eon_energy_markers(
            t,
            ic,
            vce,
            segs.turn_on[0],
            segs.turn_on[1],
            segs.pulse2_on,
            bundle.dt,
            pulse1_off=segs.pulse1_off,
        )
        t_a_us = mk.t_start * 1e6
        t_b_us = mk.t_end * 1e6
        self.assertGreater(t_b_us, t_a_us + 0.15)
        self.assertGreater(t_b_us, 22.92)
        self.assertLess(t_b_us, 23.08)
        self.assertNotAlmostEqual(t_b_us, t_a_us + 0.218, delta=0.02)
        _assert_crossing(self, t, vce, mk.t_end, mk.hb_a, "any")

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_eon_markers_plateau_and_window(self):
        bundle = load_waveform(UH)
        cfg = load_config()
        result = extract_all(bundle, UPPER_BRIDGE, cfg)
        segs = result.segments
        assert segs is not None
        t = bundle.t
        ic = bundle_total_current(bundle, UPPER_BRIDGE)
        vce = bundle.get(UPPER_BRIDGE.vce)
        mk = eon_energy_markers(
            t,
            ic,
            vce,
            segs.turn_on[0],
            segs.turn_on[1],
            segs.pulse2_on,
            bundle.dt,
            pulse1_off=segs.pulse1_off,
        )
        self.assertLess(mk.ha_v, 80.0, "开通 Ha 应为抬升前低 Ic 平台")
        self.assertLess(mk.hb_a, 80.0, "开通 Hb 应为 Vce 回落后导通平台")
        t0_us = mk.t_start * 1e6
        t1_us = mk.t_end * 1e6
        self.assertGreater(t0_us, 18.38)
        self.assertLess(t0_us, 18.44)
        self.assertGreater(t1_us, 18.65)
        self.assertLess(t1_us, 18.88)
        _assert_crossing(self, t, vce, mk.t_end, mk.hb_a, "any")
        w = mk.as_integration_window()
        e = integrate_vi_window(t, vce, ic, w)
        self.assertGreater(e, 60.0)
        self.assertLess(e, 76.0)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_err_markers_window(self):
        bundle = load_waveform(UH)
        result = extract_all(bundle, UPPER_BRIDGE, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        irr = bundle_reverse_recovery_current(bundle, UPPER_BRIDGE)
        vd = bundle.get(UPPER_BRIDGE.v_diode)
        rr0, rr1 = segs.reverse_recovery
        on1 = segs.turn_on[1]
        mk = err_energy_markers(
            t, irr, vd, rr0, rr1, bundle.dt, i_search_end=on1
        )
        ta_us = mk.t_start * 1e6
        tb_us = mk.t_end * 1e6
        self.assertGreater(ta_us, tb_us, "A(Irr) 应晚于 B(Vd)")
        # A=IRM 主峰后恢复沿与 Ha 的第一个真实交点。
        ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
        self.assertGreater(ta_us, float(t[ipk]) * 1e6)
        self.assertLess(ta_us, float(t[on1]) * 1e6)
        # B=Vd 主抬升脚×Hb(恢复前正向导通电平)
        self.assertGreater(tb_us, 18.51)
        self.assertLess(tb_us, 18.62)
        self.assertGreater(mk.ha_v, 20.0)
        self.assertLess(mk.ha_v, 60.0)
        # Hb 为带符号正向导通 Vd 平台（≈0）
        self.assertLess(abs(mk.hb_a), 10.0)
        _assert_crossing(self, t, np.abs(irr), mk.t_start, abs(mk.ha_v), "any")
        _assert_vd_main_rise_after(self, t, vd, mk.t_end, mk.hb_a)
        e = integrate_err_recovery(t, vd, irr, mk.as_integration_window())
        self.assertGreater(e, 0.2)

    def _assert_err_ha_uses_local_offset_top(self, path: Path) -> None:
        bundle = load_waveform(path)
        profile = guess_profile_from_path(str(path))
        result = extract_all(bundle, profile, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        irr = bundle_reverse_recovery_current(bundle, profile)
        vd = bundle.get(profile.v_diode)
        rr0, rr1 = segs.reverse_recovery
        mk = err_energy_markers(
            t, irr, vd, rr0, rr1, bundle.dt, i_search_end=segs.turn_on[1]
        )
        ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
        base = _err_recovery_settled_base(irr, ipk, bundle.dt, segs.turn_on[1])
        local_top = _err_ha_top_from_offset_window(
            t, irr, mk.t_end, base, bundle.dt
        )
        self.assertIsNotNone(local_top)
        assert local_top is not None
        self.assertAlmostEqual(mk.ha_v, local_top, delta=1e-6)
        self.assertAlmostEqual(float(np.interp(mk.t_start, t, irr)), mk.ha_v, delta=0.02)

    def _assert_err_first_stable_entry_not_tail(
        self,
        path: Path,
        *,
        expected_a_us: float,
        tail_guard_us: float,
        expected_err_mj: float,
        min_a_us: float | None = None,
    ) -> None:
        bundle = load_waveform(path)
        profile = guess_profile_from_path(str(path))
        result = extract_all(bundle, profile, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        irr = bundle_reverse_recovery_current(bundle, profile)
        vd = bundle.get(profile.v_diode)
        rr0, rr1 = segs.reverse_recovery
        mk = err_energy_markers(
            t, irr, vd, rr0, rr1, bundle.dt, i_search_end=segs.turn_on[1]
        )
        ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
        base = _err_recovery_settled_base(irr, ipk, bundle.dt, segs.turn_on[1])
        ta_us = mk.t_start * 1e6
        tb_us = mk.t_end * 1e6
        peak_us = float(t[ipk]) * 1e6
        base_start_us = float(t[base.start_idx]) * 1e6
        self.assertGreater(ta_us, tb_us)
        self.assertGreater(ta_us, peak_us)
        if min_a_us is not None:
            self.assertGreater(ta_us, min_a_us)
        self.assertLess(ta_us, tail_guard_us)
        self.assertLess(base_start_us, tail_guard_us)
        self.assertAlmostEqual(ta_us, expected_a_us, delta=0.025)
        self.assertAlmostEqual(
            float(np.interp(mk.t_start, t, irr)), mk.ha_v, delta=0.05
        )
        _assert_vd_main_rise_after(self, t, vd, mk.t_end, mk.hb_a)
        e = integrate_err_recovery(t, vd, irr, mk.as_integration_window())
        self.assertAlmostEqual(e, expected_err_mj, delta=0.25)
        self.assertAlmostEqual(result.reverse_recovery.err, e, places=9)

    @unittest.skipUnless(
        SONG_SMC_RT_VL_806.exists(), "songzhenxi SMC RT VL 806A sample missing"
    )
    def test_smc_rt_vl_806_err_uses_first_stable_entry_not_tail(self):
        self._assert_err_first_stable_entry_not_tail(
            SONG_SMC_RT_VL_806,
            expected_a_us=16.254416,
            tail_guard_us=16.33,
            expected_err_mj=13.543679,
        )

    @unittest.skipUnless(
        SONG_SMC_RT_VL_1048.exists(), "songzhenxi SMC RT VL 1048A sample missing"
    )
    def test_smc_rt_vl_1048_err_uses_first_stable_entry_not_tail(self):
        self._assert_err_first_stable_entry_not_tail(
            SONG_SMC_RT_VL_1048,
            expected_a_us=20.172930,
            tail_guard_us=20.24,
            expected_err_mj=16.262180,
        )

    @unittest.skipUnless(
        SONG_SMC_RT_UH_1048.exists(), "songzhenxi SMC RT UH 1048A sample missing"
    )
    def test_smc_rt_uh_1048_err_keeps_lower_pp_candidate_near_user_mark(self):
        self._assert_err_first_stable_entry_not_tail(
            SONG_SMC_RT_UH_1048,
            expected_a_us=19.408277,
            min_a_us=19.36,
            tail_guard_us=19.45,
            expected_err_mj=13.980974,
        )

    @unittest.skipUnless(GCU_LT_UH_500.exists(), "GCU LT UH 500A sample missing")
    def test_gcu_lt_uh_500_err_ha_uses_local_offset_top_not_mid(self):
        self._assert_err_ha_uses_local_offset_top(GCU_LT_UH_500)

    @unittest.skipUnless(SOFT_ERR_WH.exists(), "soft Err WH sample missing")
    def test_wh_err_current_fall_uses_display_ha_magnitude(self):
        bundle = load_waveform(SOFT_ERR_WH)
        profile = guess_profile_from_path(str(SOFT_ERR_WH))
        result = extract_all(bundle, profile, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        irr = bundle_reverse_recovery_current(bundle, profile)
        vd = bundle.get(profile.v_diode)
        rr0, rr1 = segs.reverse_recovery
        mk = err_energy_markers(
            t, irr, vd, rr0, rr1, bundle.dt, i_search_end=segs.turn_on[1]
        )
        from dpt_extractor.metrics.iec_windows import err_recovery_peak_index

        ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
        self.assertGreater(float(irr[ipk]), 0.0)
        self.assertGreaterEqual(mk.ha_v, 0.0)
        _assert_crossing(self, t, np.abs(irr), mk.t_start, abs(mk.ha_v), "falling")
        _assert_vd_main_rise_after(self, t, vd, mk.t_end, mk.hb_a)

    @unittest.skipUnless(SSS_RT_UL_1050.exists(), "SSS RT UL 1050A sample missing")
    def test_ul_rt_err_a_uses_negative_base_three_cycle_cross_after_peak(self):
        bundle = load_waveform(SSS_RT_UL_1050)
        profile = guess_profile_from_path(str(SSS_RT_UL_1050))
        result = extract_all(bundle, profile, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        irr = bundle_reverse_recovery_current(bundle, profile)
        vd = bundle.get(profile.v_diode)
        rr0, rr1 = segs.reverse_recovery
        mk = err_energy_markers(
            t, irr, vd, rr0, rr1, bundle.dt, i_search_end=segs.turn_on[1]
        )
        from dpt_extractor.metrics.iec_windows import err_recovery_peak_index

        ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
        t_pk_us = float(t[ipk]) * 1e6
        ta_us = mk.t_start * 1e6
        tb_us = mk.t_end * 1e6
        self.assertLess(mk.ha_v, 0.0)
        local_top = _err_ha_top_from_offset_window(
            t,
            irr,
            mk.t_end,
            _err_recovery_settled_base(irr, ipk, bundle.dt, segs.turn_on[1]),
            bundle.dt,
        )
        self.assertIsNotNone(local_top)
        assert local_top is not None
        self.assertAlmostEqual(mk.ha_v, local_top, delta=1e-6)
        self.assertAlmostEqual(ta_us, 19.937605, places=5)
        self.assertGreater(ta_us, t_pk_us)
        self.assertLess(ta_us, float(t[segs.turn_on[1]]) * 1e6)
        self.assertGreater(tb_us, t_pk_us - 0.05)
        self.assertLess(tb_us, t_pk_us)
        _assert_crossing(self, t, irr, mk.t_start, mk.ha_v, "any")
        _assert_vd_main_rise_after(self, t, vd, mk.t_end, mk.hb_a)
        e = integrate_err_recovery(t, vd, irr, mk.as_integration_window())
        self.assertAlmostEqual(result.reverse_recovery.err, e, places=9)
        self.assertAlmostEqual(e, 11.692869, places=5)

    @unittest.skipUnless(SSS_RT_UL_805.exists(), "SSS RT UL 805A sample missing")
    def test_ul_rt_805_err_ha_keeps_meaningful_negative_tail_signed(self):
        bundle = load_waveform(SSS_RT_UL_805)
        profile = guess_profile_from_path(str(SSS_RT_UL_805))
        result = extract_all(bundle, profile, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        irr = bundle_reverse_recovery_current(bundle, profile)
        vd = bundle.get(profile.v_diode)
        rr0, rr1 = segs.reverse_recovery
        mk = err_energy_markers(
            t, irr, vd, rr0, rr1, bundle.dt, i_search_end=segs.turn_on[1]
        )
        from dpt_extractor.metrics.iec_windows import err_recovery_peak_index

        ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
        base = _err_recovery_settled_base(irr, ipk, bundle.dt, segs.turn_on[1])
        self.assertLess(base.level, -20.0)
        self.assertLess(mk.ha_v, 0.0)
        self.assertAlmostEqual(float(np.interp(mk.t_start, t, irr)), mk.ha_v, delta=0.01)
        self.assertAlmostEqual(mk.t_start * 1e6, 16.043064, places=5)
        self.assertAlmostEqual(mk.t_end * 1e6, 15.651653, places=5)
        _assert_crossing(self, t, irr, mk.t_start, mk.ha_v, "any")
        _assert_vd_main_rise_after(self, t, vd, mk.t_end, mk.hb_a)
        e = integrate_err_recovery(t, vd, irr, mk.as_integration_window())
        self.assertAlmostEqual(result.reverse_recovery.err, 10.731051, places=5)
        self.assertAlmostEqual(result.reverse_recovery.err, e, places=9)

    def test_rt_right_cursor_manual_screenshot_regressions(self):
        base = (
            ROOT
            / "示例文件"
            / "tss格式"
            / "KSU2577"
            / "SSM1R7PB12B3DTFMMSPP25M4CF0016"
            / "SSS"
            / "RT"
            / "tss"
        )
        cases = [
            ("UL_600V_285A_000.tss", "eoff", 4.903, 5.301, 8.249, 0.020),
            ("UL_600V_285A_000.tss", "eon", 8.753, 8.982, 9.102, 0.020),
            ("UL_600V_285A_000.tss", "err", 9.488, 8.901, 5.672, 0.015),
            ("UH_750V_1050A_000.tss", "eon", 18.384, 18.770, 69.588, 0.020),
            ("UL_750V_805A_000.tss", "eoff", 11.551, 11.959, 45.785, 0.020),
            ("UL_750V_805A_000.tss", "err", 16.043, 15.652, 10.731, 0.015),
            ("UL_750V_50A_000.tss", "err", 10.584, 10.552, 0.293, 0.020),
            ("WH_750V_50A_000.tss", "eoff", 6.292, 6.522, 1.744, 0.020),
            ("WH_750V_50A_000.tss", "err", 10.209, 10.069, 0.776, 0.015),
            ("WL_750V_50A_000.tss", "eoff", 6.666, 7.303, 1.028, 0.020),
            ("WL_750V_50A_000.tss", "err", 10.586, 10.551, 0.361, 0.015),
            ("WL_750V_805A_000.tss", "eoff", 11.853, 12.396, 43.190, 0.020),
            ("WL_750V_805A_000.tss", "err", 16.368, 15.957, 13.298, 0.015),
            ("VH_600V_285A_000.tss", "eoff", 4.598, 4.953, 12.716, 0.020),
            ("VH_600V_285A_000.tss", "eon", 8.339, 8.679, 13.240, 0.020),
            ("VH_600V_285A_000.tss", "err", 8.940, 8.515, 3.620, 0.015),
        ]
        cfg = load_config()
        cache = {}
        for name, kind, ta_us, tb_us, energy_mj, time_tol_us in cases:
            path = base / name
            if not path.exists():
                continue
            with self.subTest(sample=name, kind=kind):
                if name not in cache:
                    profile = guess_profile_from_path(str(path))
                    bundle = load_waveform(path)
                    result = extract_all(bundle, profile, cfg)
                    cache[name] = (profile, bundle, result, result.segments)
                profile, bundle, result, segs = cache[name]
                assert segs is not None
                t = bundle.t
                ic = bundle_total_current(bundle, profile)
                vce = bundle.get(profile.vce)
                irr = bundle_reverse_recovery_current(bundle, profile)
                vd = bundle.get(profile.v_diode)
                if kind == "eoff":
                    mk = eoff_energy_markers(
                        t,
                        ic,
                        vce,
                        segs.turn_off[0],
                        segs.turn_off[1],
                        segs.pulse1_off,
                        bundle.dt,
                        pre_ns=cfg.energy.eoff_pre_ns,
                        pulse1_on=segs.pulse1_on,
                    )
                    energy = integrate_vi_window(t, vce, ic, mk.as_integration_window())
                elif kind == "eon":
                    mk = eon_energy_markers(
                        t,
                        ic,
                        vce,
                        segs.turn_on[0],
                        segs.turn_on[1],
                        segs.pulse2_on,
                        bundle.dt,
                        pulse1_off=segs.pulse1_off,
                    )
                    energy = integrate_vi_window(t, vce, ic, mk.as_integration_window())
                else:
                    mk = err_energy_markers(
                        t,
                        irr,
                        vd,
                        segs.reverse_recovery[0],
                        segs.reverse_recovery[1],
                        bundle.dt,
                        i_search_end=segs.turn_on[1],
                    )
                    energy = integrate_err_recovery(t, vd, irr, mk.as_integration_window())
                self.assertAlmostEqual(mk.t_start * 1e6, ta_us, delta=time_tol_us)
                self.assertAlmostEqual(mk.t_end * 1e6, tb_us, delta=time_tol_us)
                self.assertAlmostEqual(energy, energy_mj, delta=max(0.02, energy_mj * 0.02))

    @unittest.skipUnless(SMC_RT_UH.exists(), "SMC RT UH sample missing")
    def test_smc_rt_uh_1048_err_waits_for_late_settlement(self):
        bundle = load_waveform(SMC_RT_UH)
        profile = guess_profile_from_path(str(SMC_RT_UH))
        result = extract_all(bundle, profile, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        irr = bundle_reverse_recovery_current(bundle, profile)
        vd = bundle.get(profile.v_diode)
        rr0, rr1 = segs.reverse_recovery
        mk = err_energy_markers(
            t, irr, vd, rr0, rr1, bundle.dt, i_search_end=segs.turn_on[1]
        )
        ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
        base = _err_recovery_settled_base(irr, ipk, bundle.dt, segs.turn_on[1])
        self.assertAlmostEqual(mk.t_start * 1e6, 19.412, delta=0.020)
        self.assertGreater(mk.t_start * 1e6, 19.35)
        self.assertAlmostEqual(mk.t_end * 1e6, 18.809, delta=0.020)
        self.assertGreater(2.0 * base.amp, 40.0)
        _assert_crossing(self, t, np.abs(irr), mk.t_start, abs(mk.ha_v), "any")

    @unittest.skipUnless(SMC_RT_UH.exists(), "SMC RT UH sample missing")
    def test_loss_cursor_legacy_mode_restores_previous_err_a(self):
        bundle = load_waveform(SMC_RT_UH)
        profile = guess_profile_from_path(str(SMC_RT_UH))
        result = extract_all(bundle, profile, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        irr = bundle_reverse_recovery_current(bundle, profile)
        vd = bundle.get(profile.v_diode)
        rr0, rr1 = segs.reverse_recovery
        old_mode = os.environ.get("DPT_LOSS_CURSOR_MODE")
        os.environ["DPT_LOSS_CURSOR_MODE"] = "legacy"
        try:
            mk = err_energy_markers(
                t, irr, vd, rr0, rr1, bundle.dt, i_search_end=segs.turn_on[1]
            )
        finally:
            if old_mode is None:
                os.environ.pop("DPT_LOSS_CURSOR_MODE", None)
            else:
                os.environ["DPT_LOSS_CURSOR_MODE"] = old_mode
        self.assertAlmostEqual(mk.t_start * 1e6, 19.293, delta=0.020)
        self.assertAlmostEqual(mk.t_end * 1e6, 18.809, delta=0.020)

    def _assert_err_a_uses_expected_raw_crossing(
        self,
        path: Path,
        *,
        expected_a_us: float,
    ) -> None:
        bundle = load_waveform(path)
        profile = guess_profile_from_path(str(path))
        result = extract_all(bundle, profile, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        irr = bundle_reverse_recovery_current(bundle, profile)
        vd = bundle.get(profile.v_diode)
        rr0, rr1 = segs.reverse_recovery
        mk = err_energy_markers(
            t, irr, vd, rr0, rr1, bundle.dt, i_search_end=segs.turn_on[1]
        )
        self.assertAlmostEqual(mk.t_start * 1e6, expected_a_us, delta=0.030)
        _assert_crossing(self, t, np.abs(irr), mk.t_start, abs(mk.ha_v), "any")

    @unittest.skipUnless(SMC_RT_UH_403.exists(), "SMC RT UH 403A sample missing")
    def test_smc_rt_uh_403_err_waits_for_low_amplitude_tail(self):
        self._assert_err_a_uses_expected_raw_crossing(
            SMC_RT_UH_403,
            expected_a_us=11.519,
        )

    @unittest.skipUnless(SMC_RT_VH_403.exists(), "SMC RT VH 403A sample missing")
    def test_smc_rt_vh_403_err_waits_for_low_amplitude_tail(self):
        self._assert_err_a_uses_expected_raw_crossing(
            SMC_RT_VH_403,
            expected_a_us=11.419,
        )

    @unittest.skipUnless(SMC_RT_VH_806.exists(), "SMC RT VH 806A sample missing")
    def test_smc_rt_vh_806_err_uses_quieter_late_envelope(self):
        self._assert_err_a_uses_expected_raw_crossing(
            SMC_RT_VH_806,
            expected_a_us=15.779,
        )

    @unittest.skipUnless(SMC_RT_VL_806.exists(), "SMC RT VL 806A sample missing")
    def test_smc_rt_vl_806_err_signed_tail_uses_quieter_late_envelope(self):
        self._assert_err_a_uses_expected_raw_crossing(
            SMC_RT_VL_806,
            expected_a_us=16.347,
        )

    @unittest.skipUnless(SMC_RT_VL_1048.exists(), "SMC RT VL 1048A sample missing")
    def test_smc_rt_vl_1048_err_signed_tail_uses_quieter_late_envelope(self):
        self._assert_err_a_uses_expected_raw_crossing(
            SMC_RT_VL_1048,
            expected_a_us=20.269,
        )

    @unittest.skipUnless(SSS_LT_UH_1050.exists(), "SSS LT UH 1050A sample missing")
    def test_lt_uh_1050_smooth_eon_b_does_not_chase_tail(self):
        bundle = load_waveform(SSS_LT_UH_1050)
        profile = guess_profile_from_path(str(SSS_LT_UH_1050))
        result = extract_all(bundle, profile, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        ic = bundle_total_current(bundle, profile)
        vce = bundle.get(profile.vce)
        mk = eon_energy_markers(
            t,
            ic,
            vce,
            segs.turn_on[0],
            segs.turn_on[1],
            segs.pulse2_on,
            bundle.dt,
            pulse1_off=segs.pulse1_off,
        )
        energy = integrate_vi_window(t, vce, ic, mk.as_integration_window())
        self.assertAlmostEqual(mk.t_start * 1e6, 15.908, delta=0.020)
        self.assertAlmostEqual(mk.t_end * 1e6, 16.359, delta=0.020)
        self.assertLess(mk.t_end * 1e6, 16.45)
        self.assertAlmostEqual(energy, 91.225, delta=0.05)
        _assert_crossing(self, t, vce, mk.t_end, mk.hb_a, "any")

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_rr_dvdt_ha_post_ring_plateau(self):
        """反向恢复 dv/dt Ha 应对齐 Vrr 后 ~19.7µs 震荡尾段 (max+min)/2。"""
        bundle = load_waveform(UH)
        result = extract_all(bundle, UPPER_BRIDGE, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        vd = bundle.get(UPPER_BRIDGE.v_diode)
        on0, on1 = segs.turn_on
        ipk = on0 + int(np.argmax(np.abs(vd[on0 : on1 + 1])))
        search_end = min(
            len(t) - 1, int(np.searchsorted(t, float(t[ipk]) + 1.35e-6))
        )
        hb, ha = dvdt_rr_vd_base_top(t, vd, ipk, bundle.dt, search_end)
        mask = (t >= 19.7e-6) & (t <= 20.0e-6)
        ref = 0.5 * (float(np.max(np.abs(vd[mask]))) + float(np.min(np.abs(vd[mask]))))
        self.assertAlmostEqual(hb, 0.0, places=3)
        self.assertAlmostEqual(ha, ref, delta=5.0)
        self.assertGreater(ha, 700.0)
        self.assertLess(ha, 750.0)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_turn_on_current_hb_ha_windows(self):
        """开通电流 Hb/Ha 应对齐抬升前/19.0–19.2µs 平台 (max+min)/2。"""
        bundle = load_waveform(UH)
        result = extract_all(bundle, UPPER_BRIDGE, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        from dpt_extractor.models.waveform import bundle_total_current
        from dpt_extractor.metrics.plateau_level import turn_on_current_hb_ha_t

        ic = np.abs(bundle_total_current(bundle, UPPER_BRIDGE))
        on0, on1 = segs.turn_on
        hb, ha = turn_on_current_hb_ha_t(t, ic, on0, on1, bundle.dt)
        m_hb = (t >= 17.8e-6) & (t <= 18.4e-6)
        m_ha = (t >= 19.0e-6) & (t <= 19.2e-6)
        ref_hb = 0.5 * (float(np.max(ic[m_hb])) + float(np.min(ic[m_hb])))
        ref_ha = 0.5 * (float(np.max(ic[m_ha])) + float(np.min(ic[m_ha])))
        self.assertAlmostEqual(hb, ref_hb, delta=2.0)
        self.assertAlmostEqual(ha, ref_ha, delta=12.0)
        self.assertGreater(hb, 20.0)
        self.assertLess(hb, 50.0)
        self.assertGreater(ha, 1000.0)
        self.assertLess(ha, 1060.0)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_turn_on_ab_cross_times(self):
        bundle = load_waveform(UH)
        result = extract_all(bundle, UPPER_BRIDGE, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        from dpt_extractor.models.waveform import bundle_total_current

        ic = np.abs(bundle_total_current(bundle, UPPER_BRIDGE))
        on0, on1 = segs.turn_on
        ta, tb, hb, ha = turn_on_ic_link_default_times(t, ic, on0, on1, bundle.dt)
        self.assertGreater(ta, 18.36)
        self.assertLess(ta, 18.418)
        self.assertGreater(tb, 18.96)
        self.assertLess(tb, 19.05)

    @unittest.skipUnless(WH.exists(), "WH sample missing")
    def test_wh_eoff_stays_in_expected_band(self):
        bundle = load_waveform(WH)
        cfg = load_config()
        result = extract_all(bundle, UPPER_BRIDGE, cfg)
        self.assertGreater(result.turn_off.eoff, 30.0)
        self.assertLess(result.turn_off.eoff, 60.0)
