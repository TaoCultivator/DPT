from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.plateau_level import (
    _plateau_mid_without_isolated_spikes,
    turn_on_current_baseline_and_plateau,
    turn_on_current_hb_ha_window_indices,
    turn_on_didt_ha_at_turn_on,
)
from dpt_extractor.metrics.slopes import (
    didt_between_base_top,
    turn_on_didt_measurement_context,
)
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.slope_range import (
    SlopeRange,
    preset_to_range,
    SLOPE_RANGE_PRESETS,
)
from dpt_extractor.models.waveform import bundle_total_current
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.tests.sample_paths import sample_tss

UH = sample_tss("UH_750V_1050A_000.tss")
WH = sample_tss("WH_480V_800A_000.tss")
ROOT = Path(__file__).resolve().parents[2]
SONG_SMC_HT_UH = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "HT"
    / "UH_750V_1048A_000.tss"
)


@unittest.skipUnless(UH.exists(), "UH sample missing")
class TestOnDidt8020(unittest.TestCase):
    def test_8020_rise_crossings_with_plateau_hb(self) -> None:
        bundle = load_waveform(UH)
        profile = guess_profile_from_path(UH.name)
        result = extract_all(bundle, profile, load_config())
        on0, on1 = result.segments.turn_on
        ic = bundle_total_current(bundle, profile)
        seg = np.abs(ic[on0 : on1 + 1])
        hb, _ha_seg = turn_on_current_baseline_and_plateau(seg, bundle.dt)
        ha = turn_on_didt_ha_at_turn_on(bundle.t, ic, on0, on1, bundle.dt)
        self.assertGreater(ha, 1000.0)
        self.assertLess(ha, 1060.0)
        self.assertAlmostEqual(ha, 1032.4, delta=5.0)
        sr = preset_to_range(SLOPE_RANGE_PRESETS["on_didt"][2])
        pa, pb = sr.as_fractions()
        self.assertEqual(sr.ic_direction, "rise")
        res = didt_between_base_top(
            bundle.t, ic, on0, on1, hb, ha, pa, pb, sr.ic_direction
        )
        self.assertGreater(res.didt, 1.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)
        self.assertGreater(res.t_pct_a_s, res.t_pct_b_s)
        self.assertGreater(res.t_pct_b_s * 1e6, 18.46)
        self.assertLess(res.t_pct_a_s * 1e6, 18.65)


@unittest.skipUnless(WH.exists(), "WH sample missing")
class TestOnDidtHaRelative(unittest.TestCase):
    def test_ha_follows_turn_on_plateau_not_fixed_19us(self) -> None:
        bundle = load_waveform(WH)
        profile = guess_profile_from_path(WH.name)
        result = extract_all(bundle, profile, load_config())
        on0, on1 = result.segments.turn_on
        ic = bundle_total_current(bundle, profile)
        ha = turn_on_didt_ha_at_turn_on(bundle.t, ic, on0, on1, bundle.dt)
        self.assertGreater(ha, 600.0)
        self.assertLess(ha, 950.0)


class TestTurnOnDidtSharedContext(unittest.TestCase):
    def setUp(self) -> None:
        self.dt = 1e-9
        self.t = np.arange(1400, dtype=np.float64) * self.dt
        self.ic = np.full(1400, -20.0, dtype=np.float64)
        # A one-sample pre-edge spike reaches the high threshold but does not
        # persist.  It must be excluded both from the stable-band midpoint and
        # from A/B edge selection.
        self.ic[350] = 75.0
        self.ic[500:601] = np.linspace(-20.0, 80.0, 101)
        self.ic[601:] = 80.0

    def _context(self, sr: SlopeRange):
        pa, pb = sr.as_fractions()
        return turn_on_didt_measurement_context(
            self.t,
            self.ic,
            200,
            1300,
            self.dt,
            pa,
            pb,
            edge=sr.ic_direction,
        )

    def test_stable_midpoints_and_raw_main_edge_crossings_are_shared(self) -> None:
        context = self._context(SlopeRange(10.0, 90.0, ic_direction="rise"))
        self.assertFalse(context.used_fallback)
        self.assertIsNotNone(context.base_window)
        self.assertIsNotNone(context.top_window)
        assert context.base_window is not None and context.top_window is not None
        b0, b1 = context.base_window
        h0, h1 = context.top_window
        self.assertEqual(
            context.base_a,
            _plateau_mid_without_isolated_spikes(self.ic[b0 : b1 + 1]),
        )
        self.assertEqual(
            context.top_a,
            _plateau_mid_without_isolated_spikes(self.ic[h0 : h1 + 1]),
        )
        self.assertEqual(context.base_a, -20.0)
        self.assertEqual(context.top_a, 80.0)
        self.assertEqual(context.crossing.th_a, -10.0)
        self.assertEqual(context.crossing.th_b, 70.0)
        self.assertIsNotNone(context.crossing.t_pct_a_s)
        self.assertIsNotNone(context.crossing.t_pct_b_s)
        assert context.crossing.t_pct_a_s is not None
        assert context.crossing.t_pct_b_s is not None
        self.assertGreater(context.crossing.t_pct_a_s, 500e-9)
        self.assertGreater(context.crossing.t_pct_b_s, context.crossing.t_pct_a_s)
        self.assertAlmostEqual(
            float(np.interp(context.crossing.t_pct_a_s, self.t, self.ic)),
            context.crossing.th_a,
            places=10,
        )
        self.assertAlmostEqual(
            float(np.interp(context.crossing.t_pct_b_s, self.t, self.ic)),
            context.crossing.th_b,
            places=10,
        )

    def test_all_supported_percentage_roles_keep_raw_physical_order(self) -> None:
        for sr in (
            SlopeRange(10.0, 90.0, ic_direction="rise"),
            SlopeRange(50.0, 90.0, ic_direction="rise"),
            SlopeRange(80.0, 20.0, ic_direction="rise"),
        ):
            with self.subTest(range=sr.label()):
                context = self._context(sr)
                crossing = context.crossing
                self.assertFalse(context.used_fallback)
                self.assertIsNotNone(crossing.t_pct_a_s)
                self.assertIsNotNone(crossing.t_pct_b_s)
                assert crossing.t_pct_a_s is not None
                assert crossing.t_pct_b_s is not None
                # Visible scope cursors are always chronological A(left) and
                # B(right); a reversed percentage label must swap the paired
                # thresholds as well, not swap the physical cursor names.
                self.assertLess(crossing.t_pct_a_s, crossing.t_pct_b_s)
                self.assertLess(crossing.th_a, crossing.th_b)
                self.assertAlmostEqual(
                    float(np.interp(crossing.t_pct_a_s, self.t, self.ic)),
                    crossing.th_a,
                    places=10,
                )
                self.assertAlmostEqual(
                    float(np.interp(crossing.t_pct_b_s, self.t, self.ic)),
                    crossing.th_b,
                    places=10,
                )

    def test_reversed_custom_direction_still_measures_physical_rise(self) -> None:
        context = self._context(
            SlopeRange(70.0, 30.0, ic_direction="fall")
        )
        self.assertFalse(context.used_fallback)
        self.assertLess(
            float(context.crossing.t_pct_a_s),
            float(context.crossing.t_pct_b_s),
        )
        self.assertEqual(context.crossing.th_a, 10.0)
        self.assertEqual(context.crossing.th_b, 50.0)

    def test_narrow_false_pulse_cannot_steal_main_turn_on_episode(self) -> None:
        t = np.arange(1600, dtype=np.float64) * self.dt
        ic = np.full(1600, -20.0, dtype=np.float64)
        ic[100:106] = np.linspace(-20.0, 80.0, 6)
        ic[106:112] = np.linspace(80.0, -20.0, 6)
        ic[500:601] = np.linspace(-20.0, 80.0, 101)
        ic[601:] = 80.0
        context = turn_on_didt_measurement_context(
            t,
            ic,
            0,
            1400,
            self.dt,
            0.1,
            0.9,
            edge="rise",
            event_end_idx=1500,
        )
        self.assertFalse(context.used_fallback)
        self.assertGreater(float(context.crossing.t_pct_a_s), 500e-9)
        self.assertGreater(
            float(context.crossing.t_pct_b_s),
            float(context.crossing.t_pct_a_s),
        )

    def test_short_pulse_ha_window_stays_before_physical_turn_off(self) -> None:
        t = np.arange(1000, dtype=np.float64) * self.dt
        ic = np.full(1000, -20.0, dtype=np.float64)
        ic[200:251] = np.linspace(-20.0, 80.0, 51)
        ic[251:460] = 80.0
        ic[460:] = -20.0
        event_end = 460
        context = turn_on_didt_measurement_context(
            t,
            ic,
            100,
            700,
            self.dt,
            0.1,
            0.9,
            edge="rise",
            event_end_idx=event_end,
        )
        self.assertFalse(context.used_fallback)
        self.assertIsNotNone(context.top_window)
        assert context.top_window is not None
        self.assertLess(context.top_window[1], event_end)
        self.assertTrue(np.all(ic[context.top_window[0] : context.top_window[1] + 1] == 80.0))

    def test_missing_physical_edge_fails_closed_without_fake_cursors(self) -> None:
        flat = np.full_like(self.ic, 12.0)
        context = turn_on_didt_measurement_context(
            self.t,
            flat,
            200,
            1300,
            self.dt,
            0.1,
            0.9,
            edge="rise",
        )
        self.assertTrue(context.used_fallback)
        self.assertIsNone(context.crossing.t_pct_a_s)
        self.assertIsNone(context.crossing.t_pct_b_s)
        self.assertEqual(context.crossing.didt, 0.0)


@unittest.skipUnless(SONG_SMC_HT_UH.exists(), "songzhenxi SMC HT UH sample missing")
class TestTurnOnDidtRealSharedContext(unittest.TestCase):
    def test_pipeline_value_levels_and_raw_cursors_use_one_context(self) -> None:
        bundle = load_waveform(SONG_SMC_HT_UH)
        profile = guess_profile_from_path(str(SONG_SMC_HT_UH))
        cfg = load_config()
        result = extract_all(bundle, profile, cfg)
        on0, on1 = result.segments.turn_on
        ic = bundle_total_current(bundle, profile)
        sr = SlopeRange(10.0, 90.0, ic_reference="top", ic_direction="rise")
        pa, pb = sr.as_fractions()
        context = turn_on_didt_measurement_context(
            bundle.t,
            ic,
            on0,
            on1,
            bundle.dt,
            pa,
            pb,
            edge=sr.ic_direction,
            event_end_idx=result.segments.pulse2_off,
        )
        self.assertFalse(result.is_metric_unavailable("开通", "di/dt"))
        self.assertEqual(result.turn_on.didt, context.crossing.didt)
        self.assertEqual(result.turn_on.turn_on_current, context.top_a)
        self.assertEqual(
            result.turn_on.ls_on,
            result.turn_on.delta_vce / context.crossing.didt,
        )
        self.assertIsNotNone(context.base_window)
        self.assertIsNotNone(context.top_window)
        hb_win, ha_win = turn_on_current_hb_ha_window_indices(
            bundle.t,
            ic,
            on0,
            on1,
            bundle.dt,
            event_end_idx=result.segments.pulse2_off,
        )
        self.assertEqual(context.base_window, hb_win)
        self.assertEqual(context.top_window, ha_win)
        for time_s, threshold in (
            (context.crossing.t_pct_a_s, context.crossing.th_a),
            (context.crossing.t_pct_b_s, context.crossing.th_b),
        ):
            self.assertIsNotNone(time_s)
            assert time_s is not None
            self.assertAlmostEqual(
                float(np.interp(time_s, bundle.t, ic)),
                threshold,
                places=8,
            )


if __name__ == "__main__":
    unittest.main()
