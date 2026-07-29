"""Slow gate-fall captures must keep the real turn-off edge and crossings."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

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
                    plot = win.wave_plot
                    self.assertIsNotNone(plot._cursor_a)
                    self.assertIsNotNone(plot._h_cursor_a)
                    ta_us = float(plot._cursor_a.value())
                    ha_v = plot._from_disp(
                        "vce", float(plot._h_cursor_a.value())
                    )
                    raw_vce_at_a = float(
                        np.interp(
                            ta_us * 1e-6,
                            win.bundle.t,
                            win.bundle.get(win.profile.vce),
                        )
                    )
                    self.assertAlmostEqual(raw_vce_at_a, ha_v, places=7)
                finally:
                    win.close()

    @unittest.skipUnless(
        TRUNCATED_EOFF_EDGE_SAMPLE.exists(),
        "wanglihui truncated Eoff edge sample missing",
    )
    def test_eoff_can_interpolate_crossing_just_before_compact_segment(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win._load_file(str(TRUNCATED_EOFF_EDGE_SAMPLE))
            self.assertIsNotNone(win.bundle)
            assert win.bundle is not None
            win._on_value_clicked("关断过程", "Eoff")
            plot = win.wave_plot
            ta_us = float(plot._cursor_a.value())
            ha_v = plot._from_disp("vce", float(plot._h_cursor_a.value()))
            raw_vce_at_a = float(
                np.interp(
                    ta_us * 1e-6,
                    win.bundle.t,
                    win.bundle.get(win.profile.vce),
                )
            )
            self.assertAlmostEqual(raw_vce_at_a, ha_v, places=7)
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
