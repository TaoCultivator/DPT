from __future__ import annotations

import unittest
from pathlib import Path

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.tek_parser import TekParser
from dpt_extractor.metrics.iec_windows import (
    eoff_energy_markers,
    eoff_window_scope_example,
    eon_energy_markers,
    err_energy_markers,
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

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
UH = ROOT / "UH_750V_1050A_000_ALL.csv"
WH = ROOT / "WH_480V_800A_000_ALL.csv"


class TestEoffWindow(unittest.TestCase):
    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_scope_window_near_manual_reference(self):
        bundle = TekParser().parse(UH)
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
        self.assertGreater(t0_us, 14.495)
        self.assertLess(t0_us, 14.505)
        self.assertGreater(t1_us, 14.77)
        self.assertLess(t1_us, 14.84)
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

    @unittest.skipUnless(WH.exists(), "WH sample missing")
    def test_wh_eon_b_at_vce_hb_fall_cross(self):
        """WH 慢拖尾：B 须为 Vce 与 Hb 下降穿越，而非 A+450ns 回退。"""
        bundle = TekParser().parse(WH)
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
        self.assertGreater(t_b_us, 22.95)
        self.assertLess(t_b_us, 23.05)
        self.assertNotAlmostEqual(t_b_us, t_a_us + 0.218, delta=0.02)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_eon_markers_plateau_and_window(self):
        bundle = TekParser().parse(UH)
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
        self.assertGreater(t0_us, 18.40)
        self.assertLess(t0_us, 18.44)
        self.assertGreater(t1_us, 18.74)
        self.assertLess(t1_us, 18.80)
        w = mk.as_integration_window()
        e = integrate_vi_window(t, vce, ic, w)
        self.assertGreater(e, 65.0)
        self.assertLess(e, 76.0)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_err_markers_window(self):
        bundle = TekParser().parse(UH)
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
        # A=恢复主峰下降沿×Ha(恢复后稳定 Irr 平台)
        self.assertGreater(ta_us, 18.63)
        self.assertLess(ta_us, 18.66)
        # B=Vd 主抬升脚×Hb(恢复前正向导通电平)
        self.assertGreater(tb_us, 18.55)
        self.assertLess(tb_us, 18.62)
        self.assertGreater(mk.ha_v, 20.0)
        self.assertLess(mk.ha_v, 32.0)
        # Hb 为带符号正向导通 Vd 平台（≈0）
        self.assertLess(abs(mk.hb_a), 10.0)
        e = integrate_err_recovery(t, vd, irr, mk.as_integration_window())
        self.assertGreater(e, 0.5)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_rr_dvdt_ha_post_ring_plateau(self):
        """反向恢复 dv/dt Ha 应对齐 Vrr 后 ~19.7µs 震荡尾段 (max+min)/2。"""
        bundle = TekParser().parse(UH)
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
        self.assertAlmostEqual(ha, ref, places=0)
        self.assertGreater(ha, 700.0)
        self.assertLess(ha, 750.0)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_turn_on_current_hb_ha_windows(self):
        """开通电流 Hb/Ha 应对齐抬升前/19.0–19.2µs 平台 (max+min)/2。"""
        bundle = TekParser().parse(UH)
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
        self.assertAlmostEqual(hb, ref_hb, places=0)
        self.assertAlmostEqual(ha, ref_ha, places=0)
        self.assertGreater(hb, 20.0)
        self.assertLess(hb, 50.0)
        self.assertGreater(ha, 1000.0)
        self.assertLess(ha, 1060.0)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_turn_on_ab_cross_times(self):
        bundle = TekParser().parse(UH)
        result = extract_all(bundle, UPPER_BRIDGE, load_config())
        segs = result.segments
        assert segs is not None
        t = bundle.t
        from dpt_extractor.models.waveform import bundle_total_current

        ic = np.abs(bundle_total_current(bundle, UPPER_BRIDGE))
        on0, on1 = segs.turn_on
        ta, tb, hb, ha = turn_on_ic_link_default_times(t, ic, on0, on1, bundle.dt)
        self.assertGreater(ta, 18.412)
        self.assertLess(ta, 18.418)
        self.assertGreater(tb, 18.98)
        self.assertLess(tb, 19.05)

    @unittest.skipUnless(WH.exists(), "WH sample missing")
    def test_wh_eoff_stays_in_expected_band(self):
        bundle = TekParser().parse(WH)
        cfg = load_config()
        result = extract_all(bundle, UPPER_BRIDGE, cfg)
        self.assertGreater(result.turn_off.eoff, 30.0)
        self.assertLess(result.turn_off.eoff, 60.0)
