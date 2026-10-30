"""Slow gate-fall captures must keep the real turn-off edge and crossings."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = (
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "20260729"
        / "UH_HT_Rgon3.33R_Rgoff8.92R"
        / "UH_486V_200A_Rgon3.33R_Rgoff8.92R_000.tss",
        False,
    ),
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "20260729"
        / "UL_RT_Rgon2.267R_Rgoff7.5R"
        / "UL_486V_200A_Rgon2.267R_Rgoff7.5R_000.tss",
        True,
    ),
)
TRUNCATED_EOFF_EDGE_SAMPLE = (
    ROOT
    / "示例文件"
    / "wanglihui"
    / "20260729"
    / "UL_RT_Rgon2.267R_Rgoff7.5R"
    / "UL_486V_400A_Rgon2.267R_Rgoff7.5R_000.tss"
)


@unittest.skipUnless(
    all(path.exists() for path, _source_inverted in SAMPLES),
    "wanglihui 20260729 slow turn-off samples missing",
)
class TestSlowGateTurnOffWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _assert_eoff_cursor_semantics(self, win) -> None:
        """Audit v71 Eoff endpoints without weakening fallback crossings."""

        from dpt_extractor.models.waveform import bundle_total_current

        self.assertIsNotNone(win.bundle)
        self.assertIsNotNone(win.result)
        assert win.bundle is not None and win.result is not None
        markers = win.result.energy_contexts.get(("关断过程", "Eoff"))
        self.assertIsNotNone(markers)
        assert markers is not None

        plot = win.wave_plot
        self.assertIsNotNone(plot._cursor_a)
        self.assertIsNotNone(plot._cursor_b)
        self.assertIsNotNone(plot._h_cursor_a)
        self.assertIsNotNone(plot._h_cursor_b)
        ta_us = float(plot._cursor_a.value())
        tb_us = float(plot._cursor_b.value())
        ha_v = plot._from_disp("vce", float(plot._h_cursor_a.value()))
        hb_a = plot._from_disp("ic", float(plot._h_cursor_b.value()))
        self.assertAlmostEqual(ta_us, float(markers.t_start) * 1e6, places=9)
        self.assertAlmostEqual(tb_us, float(markers.t_end) * 1e6, places=9)
        self.assertAlmostEqual(ha_v, float(markers.ha_v), places=9)
        self.assertAlmostEqual(hb_a, float(markers.hb_a), places=9)

        if markers.endpoint_mode == "stable_platforms":
            context = markers.stable_platform_context
            self.assertIsNotNone(context)
            assert context is not None
            self.assertEqual(markers.i_start, context.a_idx)
            self.assertEqual(markers.i_end, context.b_idx)
            self.assertLessEqual(context.a_band_start_idx, context.a_idx)
            self.assertLessEqual(context.a_idx, context.a_band_end_idx)
            self.assertLessEqual(context.b_band_start_idx, context.b_idx)
            self.assertLessEqual(context.b_idx, context.b_band_end_idx)
            self.assertLess(context.a_idx, context.v10_idx)
            self.assertLess(context.i10_idx, context.b_idx)
            self.assertAlmostEqual(
                ta_us,
                float(win.bundle.t[context.a_idx]) * 1e6,
                places=9,
            )
            self.assertAlmostEqual(
                tb_us,
                float(win.bundle.t[context.b_idx]) * 1e6,
                places=9,
            )
            return

        self.assertEqual(markers.endpoint_mode, "level_crossings")
        self.assertIsNone(markers.stable_platform_context)
        raw_vce_at_a = float(
            np.interp(
                ta_us * 1e-6,
                win.bundle.t,
                win.bundle.get(win.profile.vce),
            )
        )
        raw_ic_at_b = float(
            np.interp(
                tb_us * 1e-6,
                win.bundle.t,
                bundle_total_current(win.bundle, win.profile),
            )
        )
        self.assertAlmostEqual(raw_vce_at_a, ha_v, places=7)
        self.assertAlmostEqual(raw_ic_at_b, hb_a, places=7)

    def test_real_gate_fall_and_current_crossings_remain_available(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.metrics.iec_timings import vge_fall_window_indices

        for path, source_inverted in SAMPLES:
            with self.subTest(path=str(path)):
                win = MainWindow()
                try:
                    win._load_file(str(path))
                    if not source_inverted:
                        win.wave_plot.set_channel_inversion_enabled("CH3", True)
                        self.app.processEvents()
                    self.assertIsNotNone(win.bundle)
                    self.assertIsNotNone(win.result)
                    assert win.bundle is not None and win.result is not None
                    segs = win.result.segments
                    fall = vge_fall_window_indices(
                        win.bundle.t,
                        win.bundle.get(win.profile.vge),
                        segs.turn_off[0],
                        segs.turn_off[1],
                        segs.pulse1_on,
                        segs.pulse1_off,
                        segs.pulse2_on,
                        win.bundle.dt,
                        win.cfg,
                    )
                    self.assertIsNotNone(fall)
                    assert fall is not None
                    # The real Vge 90% crossing precedes the late Schmitt
                    # low-threshold pulse end by multiple microseconds.
                    self.assertGreater(
                        (
                            float(win.bundle.t[segs.pulse1_off])
                            - float(win.bundle.t[fall[0]])
                        )
                        * 1e6,
                        2.0,
                    )
                    self.assertGreater(win.result.turn_off.td_off, 0.0)
                    self.assertGreater(win.result.turn_off.tf, 0.0)
                    self.assertGreater(win.result.turn_off.toff, 0.0)

                    for metric in ("dv/dt", "di/dt"):
                        win._on_value_clicked("关断过程", metric)
                        self.assertIsNotNone(win.wave_plot._cursor_a)
                        self.assertIsNotNone(win.wave_plot._cursor_b)
                        self.assertTrue(win.wave_plot._slope_ab_valid)

                    win._on_value_clicked("关断过程", "Eoff")
                    self._assert_eoff_cursor_semantics(win)
                finally:
                    win.close()

    @unittest.skipUnless(
        TRUNCATED_EOFF_EDGE_SAMPLE.exists(),
        "wanglihui truncated Eoff edge sample missing",
    )
    def test_eoff_can_interpolate_crossing_just_before_compact_segment(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        for cursor_mode, expected_mode in (
            ("", "stable_platforms"),
            ("legacy", "level_crossings"),
        ):
            with self.subTest(endpoint_mode=expected_mode):
                with mock.patch.dict(
                    os.environ,
                    {"DPT_LOSS_CURSOR_MODE": cursor_mode},
                ):
                    win = MainWindow()
                    try:
                        win._load_file(str(TRUNCATED_EOFF_EDGE_SAMPLE))
                        self.assertIsNotNone(win.bundle)
                        self.assertIsNotNone(win.result)
                        assert win.bundle is not None and win.result is not None
                        win._on_value_clicked("关断过程", "Eoff")
                        markers = win.result.energy_contexts.get(
                            ("关断过程", "Eoff")
                        )
                        self.assertIsNotNone(markers)
                        assert markers is not None
                        self.assertEqual(markers.endpoint_mode, expected_mode)
                        self._assert_eoff_cursor_semantics(win)
                    finally:
                        win.close()


if __name__ == "__main__":
    unittest.main()
