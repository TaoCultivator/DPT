"""Turn-off slope contexts must bind one stable-band definition end to end."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.metrics.iec_timings import turn_off_ic_fall_window
from dpt_extractor.metrics.slopes import (
    turn_off_didt_measurement_context,
    turn_off_dvdt_measurement_context,
)
from dpt_extractor.models.slope_range import default_slope_ranges
from dpt_extractor.models.waveform import bundle_total_current


ROOT = Path(__file__).resolve().parents[2]
SONG_DCU_RT_WL_480_1000 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2506"
    / "DCU"
    / "SMC"
    / "RT"
    / "tss"
    / "WL_480V_1000A_000.tss"
)


class TestTurnOffSlopeSyntheticContext(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = AppConfig()
        self.dt = 1e-9
        self.t = np.arange(2_200, dtype=np.float64) * self.dt

    def test_dvdt_uses_stable_band_centers_and_raw_intersections(self) -> None:
        indices = np.arange(len(self.t))
        vce = np.where(indices % 2 == 0, 4.8, 5.2).astype(np.float64)
        vce[900:1001] = np.linspace(vce[899], 472.0, 102)[1:]
        vce[1001:] = np.where(indices[1001:] % 2 == 0, 471.8, 472.2)

        # These isolated excursions are inside the parameter-local record but
        # outside the selected quiet low/high platform bands.
        vce[650] = 200.0
        vce[850] = -20.0
        vce[1200] = 650.0

        i0, i1 = 300, 1800
        context = turn_off_dvdt_measurement_context(
            self.t,
            vce,
            i0,
            i1,
            self.dt,
            self.cfg,
            0.10,
            0.90,
            rise_start=800,
            rise_end=1100,
        )

        self.assertAlmostEqual(context.base_v, (4.8 + 5.2) / 2.0, places=12)
        self.assertAlmostEqual(context.top_v, (471.8 + 472.2) / 2.0, places=12)
        local = vce[i0 : i1 + 1]
        self.assertNotAlmostEqual(context.top_v, float(np.max(local)), places=6)
        self.assertNotAlmostEqual(
            context.top_v, float(np.percentile(local, 95.0)), places=6
        )
        self.assertNotAlmostEqual(context.base_v, float(np.min(local)), places=6)
        self.assertFalse(context.used_fallback)

        crossing = context.crossing
        self.assertIsNotNone(crossing.t_pct_a_s)
        self.assertIsNotNone(crossing.t_pct_b_s)
        assert crossing.t_pct_a_s is not None
        assert crossing.t_pct_b_s is not None
        self.assertLess(crossing.t_pct_a_s, crossing.t_pct_b_s)
        self.assertGreater(crossing.t_pct_a_s, float(self.t[890]))
        self.assertAlmostEqual(
            float(np.interp(crossing.t_pct_a_s, self.t, vce)),
            crossing.th_a,
            places=9,
        )
        self.assertAlmostEqual(
            float(np.interp(crossing.t_pct_b_s, self.t, vce)),
            crossing.th_b,
            places=9,
        )
        self.assertGreater(crossing.dvdt, 0.0)

    def test_didt_uses_stable_band_centers_not_peak_or_p95(self) -> None:
        indices = np.arange(len(self.t))
        ic = np.where(indices % 2 == 0, 979.5, 980.5).astype(np.float64)
        ic[900:911] = np.linspace(ic[899], 8.0, 12)[1:]
        ic[911:] = np.where(indices[911:] % 2 == 0, 7.5, 8.5)

        # A peak and an undershoot remain in the broader local record. Neither
        # is allowed to redefine the actual pre/post-fall stable bands.
        ic[400] = 1000.0
        ic[650] = 1200.0
        ic[850] = 0.0
        ic[1400] = -5.0

        i0, i1 = 300, 1800
        context = turn_off_didt_measurement_context(
            self.t,
            ic,
            i0,
            i1,
            pulse1_on=200,
            off_idx=1000,
            fall_start=800,
            fall_end=1000,
            dt=self.dt,
            cfg=self.cfg,
            pct_a=0.90,
            pct_b=0.10,
            edge="fall",
        )

        self.assertAlmostEqual(context.top_a, (979.5 + 980.5) / 2.0, places=12)
        self.assertAlmostEqual(context.base_a, (7.5 + 8.5) / 2.0, places=12)
        local = ic[i0 : i1 + 1]
        self.assertNotAlmostEqual(context.top_a, float(np.max(local)), places=6)
        self.assertNotAlmostEqual(
            context.top_a, float(np.percentile(local, 95.0)), places=6
        )
        self.assertNotAlmostEqual(context.base_a, float(np.min(local)), places=6)
        self.assertFalse(context.used_fallback)

        crossing = context.crossing
        self.assertIsNotNone(crossing.t_pct_a_s)
        self.assertIsNotNone(crossing.t_pct_b_s)
        assert crossing.t_pct_a_s is not None
        assert crossing.t_pct_b_s is not None
        self.assertLess(crossing.t_pct_a_s, crossing.t_pct_b_s)
        self.assertGreater(crossing.t_pct_a_s, float(self.t[890]))
        self.assertAlmostEqual(
            float(np.interp(crossing.t_pct_a_s, self.t, np.abs(ic))),
            crossing.th_a,
            places=9,
        )
        self.assertAlmostEqual(
            float(np.interp(crossing.t_pct_b_s, self.t, np.abs(ic))),
            crossing.th_b,
            places=9,
        )
        self.assertGreater(crossing.didt, 0.0)

    def test_degenerate_records_return_unknown_context_without_gradient_error(self) -> None:
        t = np.asarray([0.0], dtype=np.float64)
        y = np.asarray([1.0], dtype=np.float64)
        dv = turn_off_dvdt_measurement_context(
            t, y, 0, 0, self.dt, self.cfg, 0.10, 0.90
        )
        di = turn_off_didt_measurement_context(
            t,
            y,
            0,
            0,
            pulse1_on=0,
            off_idx=0,
            fall_start=0,
            fall_end=0,
            dt=self.dt,
            cfg=self.cfg,
            pct_a=0.90,
            pct_b=0.10,
        )
        self.assertTrue(dv.used_fallback)
        self.assertTrue(di.used_fallback)
        self.assertEqual(dv.crossing.dvdt, 0.0)
        self.assertEqual(di.crossing.didt, 0.0)


@unittest.skipUnless(
    SONG_DCU_RT_WL_480_1000.exists(),
    "songzhenxi WL_480V_1000A sample is not available",
)
class TestTurnOffSlopeSongzhenxiContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_pipeline_and_gui_share_the_same_measurement_context(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        window = MainWindow()
        self.addCleanup(window.close)
        window._load_file(str(SONG_DCU_RT_WL_480_1000))

        self.assertIsNotNone(window.bundle)
        self.assertIsNotNone(window.result)
        assert window.bundle is not None
        assert window.result is not None
        self.assertIsNotNone(window.result.segments)
        assert window.result.segments is not None

        bundle = window.bundle
        result = window.result
        segments = result.segments
        t = bundle.t
        vce = bundle.get(window.profile.vce)
        ic = bundle_total_current(bundle, window.profile)
        slope_ranges = default_slope_ranges()
        slope_ranges.update(window.cfg.slope_ranges)
        dv_range = slope_ranges["off_dvdt"]
        di_range = slope_ranges["off_didt"]
        dv_a, dv_b = dv_range.as_fractions()
        di_a, di_b = di_range.as_fractions()

        fall_window = turn_off_ic_fall_window(
            t,
            bundle.get(window.profile.vge),
            segments.turn_off[0],
            segments.turn_off[1],
            segments.pulse1_on,
            segments.pulse1_off,
            segments.pulse2_on,
            bundle.dt,
            window.cfg,
        )
        self.assertIsNotNone(fall_window)
        assert fall_window is not None

        dv_context = turn_off_dvdt_measurement_context(
            t,
            vce,
            segments.turn_off[0],
            segments.turn_off[1],
            bundle.dt,
            window.cfg,
            dv_a,
            dv_b,
            rise_start=fall_window[0],
            rise_end=fall_window[1],
        )
        di_context = turn_off_didt_measurement_context(
            t,
            ic,
            segments.turn_off[0],
            segments.turn_off[1],
            segments.pulse1_on,
            segments.pulse1_off,
            fall_window[0],
            fall_window[1],
            bundle.dt,
            window.cfg,
            di_a,
            di_b,
            edge=di_range.ic_direction,
        )

        self.assertAlmostEqual(result.turn_off.dvdt, dv_context.crossing.dvdt, places=12)
        self.assertAlmostEqual(result.turn_off.didt, di_context.crossing.didt, places=12)
        self.assertEqual(
            result.turn_off.dvdt_range,
            f"{dv_range.label()}·Top={dv_context.top_v:.2f}V"
            f"·Base={dv_context.base_v:.2f}V",
        )
        self.assertEqual(
            result.turn_off.didt_range,
            f"{di_range.label()}·Top={di_context.top_a:.2f}A"
            f"·Base={di_context.base_a:.2f}A",
        )

        self.assertAlmostEqual(dv_context.top_v, 472.0234375, places=6)
        self.assertAlmostEqual(dv_context.base_v, 5.984375, places=6)
        self.assertAlmostEqual(di_context.top_a, 980.59375, places=6)
        self.assertAlmostEqual(di_context.base_a, 8.03125, places=6)
        self.assertFalse(dv_context.used_fallback)
        self.assertFalse(di_context.used_fallback)

        # The GUI rebuilds the very same default contexts for its horizontal
        # lines and raw A/B intersections; it must not invent another result.
        dv_interval = window._parameter_interval_us("关断过程", "dv/dt")
        di_interval = window._parameter_interval_us("关断过程", "di/dt")
        self.assertIsNotNone(dv_interval)
        self.assertIsNotNone(di_interval)
        assert dv_interval is not None
        assert di_interval is not None
        gui_dv = window._turn_off_dvdt_context(*dv_interval)
        gui_di = window._turn_off_didt_context(*di_interval)
        self.assertEqual(gui_dv, dv_context)
        self.assertEqual(gui_di, di_context)

        # Peak current and loss/overshoot metrics remain independent outputs.
        self.assertAlmostEqual(result.turn_off.ic_off_max, 1002.15625, places=6)
        self.assertNotAlmostEqual(
            result.turn_off.ic_off_max, di_context.top_a, places=6
        )
        self.assertGreater(result.turn_off.ic_off_max, di_context.top_a)
        self.assertAlmostEqual(result.turn_off.eoff, 56.49762867, places=6)
        self.assertAlmostEqual(result.turn_off.delta_vce, 194.609375, places=6)


if __name__ == "__main__":
    unittest.main()
