from __future__ import annotations

import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import LOWER_BRIDGE, UPPER_BRIDGE, guess_profile_from_path
from dpt_extractor.models.waveform import bundle_total_current
from dpt_extractor.metrics.iec_timings import turn_on_vce_top_from_ic_rise
from dpt_extractor.pipeline.extract import (
    _turn_on_delta_vce,
    _turn_on_delta_vce_knee_point,
    extract_all,
)
from dpt_extractor.tests.sample_paths import SAMPLE_ROOT, sample_tss

WH = sample_tss("WH_480V_800A_000.tss")
WL = sample_tss("WL_480V_800A_000.tss")
UH = sample_tss("UH_750V_1050A_000.tss")
UL = sample_tss("UL_750V_1050A_000.tss")
VH = sample_tss("VH_750V_1050A_000.tss")
WL_450_SMC_LT = (
    SAMPLE_ROOT
    / "tss格式"
    / "KSU2506"
    / "DCU"
    / "SMC"
    / "LT"
    / "tss"
    / "WL_450V_800A_000.tss"
)


class TestTurnOnDeltaVceKnee(unittest.TestCase):
    def test_hb_defaults_to_two_stage_fall_knee(self):
        n = 4000
        v_top = 760.0
        vce = np.full(n, v_top)
        # 第一状态：平缓下降；第二状态：主下降。理想 Hb 应落在二者交接处。
        knee = 1800
        vce[:1200] = v_top
        vce[1200:knee] = np.linspace(v_top, 470.0, knee - 1200, endpoint=False)
        vce[knee:2300] = np.linspace(470.0, 20.0, 500, endpoint=False)
        vce[2300:] = 12.0

        idx, v_knee = _turn_on_delta_vce_knee_point(vce, 0, n, 1e-10, v_top)
        self.assertLess(abs(idx - knee), 80)
        self.assertAlmostEqual(v_knee, 470.0, delta=45.0)
        self.assertAlmostEqual(
            _turn_on_delta_vce(vce, 0, n, 1e-10, v_top),
            v_top - v_knee,
            places=6,
        )

    def test_hb_defaults_to_middle_of_three_slope_fall(self):
        n = 5000
        v_top = 450.0
        vce = np.full(n, v_top)
        mid_start = 1900
        mid_end = 2800
        mid_expected = (mid_start + mid_end) // 2
        # 三斜率：高速下降 -> 中间缓斜率 -> 再次高速下降。
        vce[:1600] = v_top
        vce[1600:mid_start] = np.linspace(v_top, 330.0, mid_start - 1600, endpoint=False)
        vce[mid_start:mid_end] = np.linspace(330.0, 220.0, mid_end - mid_start, endpoint=False)
        vce[mid_end:3300] = np.linspace(220.0, 40.0, 3300 - mid_end, endpoint=False)
        vce[3300:] = 35.0

        idx, v_mid = _turn_on_delta_vce_knee_point(vce, 0, n, 1e-10, v_top)
        self.assertLess(abs(idx - mid_expected), 250)
        self.assertAlmostEqual(v_mid, 275.0, delta=35.0)

    def test_hb_uses_stable_platform_max_min_average(self):
        n = 5000
        v_top = 444.6
        vce = np.full(n, v_top)
        plateau_start = 680
        plateau_end = 1550
        vce[:600] = v_top
        vce[600:plateau_start] = np.linspace(
            v_top, 340.0, plateau_start - 600, endpoint=False
        )
        plateau = 335.0 + 1.2 * np.sin(np.linspace(0, 4 * np.pi, plateau_end - plateau_start))
        vce[plateau_start:plateau_end] = plateau
        vce[plateau_end:2000] = np.linspace(335.0, 60.0, 2000 - plateau_end, endpoint=False)
        vce[2000:] = 40.0

        idx, v_platform = _turn_on_delta_vce_knee_point(vce, 0, n, 8e-11, v_top)
        self.assertGreater(idx, plateau_start)
        self.assertLess(idx, plateau_end + 50)
        self.assertAlmostEqual(v_platform, 335.0, delta=4.0)

    @unittest.skipUnless(WL_450_SMC_LT.exists(), "WL 450V SMC LT sample missing")
    def test_real_wl_450_open_delta_vce_uses_pre_fall_platform(self):
        bundle = load_waveform(WL_450_SMC_LT)
        profile = guess_profile_from_path(WL_450_SMC_LT)
        result = extract_all(bundle, profile, load_config())
        assert result.segments is not None

        vce = bundle.get(profile.vce)
        ic = bundle_total_current(bundle, profile)
        on0, on1 = result.segments.turn_on
        v_top = turn_on_vce_top_from_ic_rise(
            ic,
            vce,
            result.segments.pulse2_on,
            result.segments.pulse2_off,
            bundle.dt,
        )
        knee = _turn_on_delta_vce_knee_point(vce, on0, on1, bundle.dt, v_top)

        self.assertIsNotNone(knee)
        assert knee is not None
        self.assertAlmostEqual(float(bundle.t[knee[0]] * 1e6), 24.43424, delta=0.03)
        self.assertAlmostEqual(float(knee[1]), 348.0, delta=2.0)
        self.assertAlmostEqual(result.turn_on.delta_vce, 96.05, delta=2.0)


class TestTssSamples(unittest.TestCase):
    @unittest.skipUnless(WH.exists(), "WH sample missing")
    def test_load_wh(self):
        bundle = load_waveform(WH)
        self.assertGreater(bundle.n, 1_000)
        self.assertGreater(bundle.dt, 0)
        self.assertIn("CH1", bundle.channels)
        self.assertIn("MATH1", bundle.channels)

    @unittest.skipUnless(VH.exists(), "VH sample missing")
    def test_load_vh_includes_math_channels(self):
        bundle = load_waveform(VH)
        self.assertTrue(any(name.startswith("MATH") for name in bundle.channels))
        self.assertGreaterEqual(len(bundle.channels), 6)


class TestExtractWH(unittest.TestCase):
    @unittest.skipUnless(WH.exists(), "WH sample missing")
    def test_upper_bridge_metrics(self):
        bundle = load_waveform(WH)
        cfg = load_config()
        result = extract_all(bundle, UPPER_BRIDGE, cfg)

        self.assertGreater(result.vdc, 400)
        self.assertLess(result.vdc, 520)
        self.assertGreater(result.turn_off.ic_off_max, 700)
        self.assertLess(result.turn_off.ic_off_max, 900)
        self.assertGreater(result.turn_off.vce_off_max, 600)
        self.assertGreater(result.turn_off.delta_vce, 100)
        off = result.turn_off
        self.assertAlmostEqual(off.toff, off.td_off + off.tf, places=2)
        self.assertGreater(off.td_off, 50)
        self.assertGreater(off.tf, 50)
        self.assertGreater(off.toff, 100)
        self.assertGreater(result.reverse_recovery.irr, 100)
        self.assertIsNotNone(result.segments)
        on = result.turn_on
        self.assertAlmostEqual(on.ton, on.td_on + on.tr, places=3)
        self.assertGreater(on.td_on, 200)
        self.assertGreater(on.tr, 30)
        self.assertGreater(on.ton, 300)

    @unittest.skipUnless(WH.exists(), "WH sample missing")
    def test_missing_vge_fall_window_reuses_didt_top_as_ic_off_max(self):
        bundle = load_waveform(WH)
        cfg = load_config()
        with patch(
            "dpt_extractor.pipeline.extract.turn_off_ic_fall_window",
            return_value=None,
        ):
            result = extract_all(bundle, UPPER_BRIDGE, cfg)

        assert result.segments is not None
        ic = bundle_total_current(bundle, UPPER_BRIDGE)
        start = max(
            int(result.segments.pulse1_on) + 1,
            int(result.segments.turn_off[0]),
        )
        end = min(int(result.segments.turn_off[1]), len(ic) - 1)
        expected = float(np.max(np.abs(ic[start : end + 1])))
        self.assertAlmostEqual(result.turn_off.ic_off_max, expected, places=12)


class TestExtractWL(unittest.TestCase):
    @unittest.skipUnless(WL.exists(), "WL sample missing")
    def test_lower_bridge_metrics(self):
        bundle = load_waveform(WL)
        cfg = load_config()
        result = extract_all(bundle, LOWER_BRIDGE, cfg)

        self.assertGreater(result.vdc, 400)
        self.assertLess(result.vdc, 520)
        self.assertGreater(result.turn_off.ic_off_max, 700)
        self.assertLess(result.turn_off.ic_off_max, 900)
        self.assertGreater(result.turn_off.vce_off_max, 600)
        self.assertGreater(result.turn_off.delta_vce, 50)
        self.assertGreater(result.turn_off.eoff, 30)
        self.assertLess(result.turn_off.eoff, 60)
        off = result.turn_off
        self.assertAlmostEqual(off.toff, off.td_off + off.tf, places=2)
        self.assertGreater(off.td_off, 50)
        self.assertGreater(off.tf, 50)
        on = result.turn_on
        self.assertAlmostEqual(on.ton, on.td_on + on.tr, places=3)
        self.assertGreater(on.td_on, 200)
        self.assertGreater(result.reverse_recovery.irr, 100)
        self.assertGreater(result.reverse_recovery.trr, 100)
        self.assertGreater(result.reverse_recovery.err, 1.0)
        self.assertLess(result.reverse_recovery.err, 8.0)


class TestExtractUH(unittest.TestCase):
    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_u_phase_upper_long_pulse(self):
        bundle = load_waveform(UH)
        cfg = load_config()
        profile = guess_profile_from_path(UH.name)
        result = extract_all(bundle, profile, cfg)

        self.assertGreater(result.vdc, 700)
        self.assertLess(result.vdc, 820)
        self.assertGreater(result.turn_off.ic_off_max, 900)
        self.assertGreater(result.turn_off.eoff, 25)
        self.assertLess(result.turn_off.eoff, 120)
        self.assertGreater(result.reverse_recovery.irr, 80)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_missing_opposite_channels_only_hide_dependent_metrics(self):
        from dpt_extractor.models.waveform import WaveformBundle

        bundle = load_waveform(UH)
        cfg = load_config()
        profile = guess_profile_from_path(UH.name)
        channels = {
            name: data
            for name, data in bundle.channels.items()
            if name not in {profile.v_diode, profile.vge_other}
        }
        missing_bundle = WaveformBundle(
            t=bundle.t,
            channels=channels,
            meta=bundle.meta,
        )

        result = extract_all(missing_bundle, profile, cfg)

        self.assertGreater(result.turn_off.eoff, 25)
        self.assertGreater(result.turn_on.eon, 25)
        self.assertGreater(result.reverse_recovery.irr, 80)
        self.assertFalse(result.is_metric_unavailable("关断过程", "Eoff"))
        self.assertFalse(result.is_metric_unavailable("开通", "Eon"))
        self.assertFalse(result.is_metric_unavailable("反向恢复", "Irr"))
        self.assertTrue(result.is_metric_unavailable("关断过程", "串扰电压"))
        self.assertTrue(result.is_metric_unavailable("开通", "串扰电压"))
        self.assertTrue(result.is_metric_unavailable("反向恢复", "Vrr"))
        self.assertTrue(result.is_metric_unavailable("反向恢复", "dv/dt"))
        self.assertTrue(result.is_metric_unavailable("反向恢复", "Err"))


class TestExtractUL(unittest.TestCase):
    @unittest.skipUnless(UL.exists(), "UL sample missing")
    def test_u_phase_lower(self):
        bundle = load_waveform(UL)
        cfg = load_config()
        profile = guess_profile_from_path(UL.name)
        result = extract_all(bundle, profile, cfg)

        self.assertGreater(result.turn_off.ic_off_max, 900)
        self.assertGreater(result.turn_off.eoff, 25)
        self.assertLess(result.turn_off.eoff, 120)


if __name__ == "__main__":
    unittest.main()
