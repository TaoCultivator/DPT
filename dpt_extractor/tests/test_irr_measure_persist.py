"""Irr/Trr 手动光标在再次点击参数时应保持。"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dpt_extractor.config.loader import load_config
from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.gui.waveform_plot import WaveformPlot
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.tests.sample_paths import sample_tss

UH = sample_tss("UH_750V_1050A_000.tss")
TRR_SAMPLE = sample_tss("UL_486V_985A_Rgon1.1R_Rgof5R_000.tss")


class TestIrrMeasurePersist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_reclick_trr_keeps_four_independent_manual_cursors(self):
        if not TRR_SAMPLE.is_file():
            self.skipTest("Trr TSS 样本缺失")
        win = MainWindow()
        try:
            win._load_file(str(TRR_SAMPLE))
            self.assertIsNotNone(win.result)
            result = win.result
            plot = win.wave_plot
            win._enable_trr_interaction()
            self.assertEqual(plot._interactive_mode, "trr_measure")
            self.assertTrue(plot._cursor_a.movable)
            self.assertTrue(plot._cursor_b.movable)
            self.assertTrue(plot._h_cursor_a.movable)
            self.assertTrue(plot._h_cursor_b.movable)

            ta0 = float(plot._cursor_a.value())
            tb0 = float(plot._cursor_b.value())
            ha0 = plot._from_disp("irr", float(plot._h_cursor_a.value()))
            hb0 = plot._from_disp("irr", float(plot._h_cursor_b.value()))

            user_ha = ha0 + 7.0
            plot._h_cursor_a.setValue(plot._to_disp("irr", user_ha))
            self.app.processEvents()
            self.assertAlmostEqual(float(plot._cursor_a.value()), ta0, places=9)
            self.assertAlmostEqual(float(plot._cursor_b.value()), tb0, places=9)
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_b.value())),
                hb0,
                places=9,
            )

            user_hb = hb0 - 5.0
            plot._h_cursor_b.setValue(plot._to_disp("irr", user_hb))
            self.app.processEvents()
            self.assertAlmostEqual(float(plot._cursor_a.value()), ta0, places=9)
            self.assertAlmostEqual(float(plot._cursor_b.value()), tb0, places=9)
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_a.value())),
                user_ha,
                places=9,
            )

            user_ta = ta0 + 0.003
            plot._cursor_a.setValue(user_ta)
            self.app.processEvents()
            self.assertAlmostEqual(float(plot._cursor_b.value()), tb0, places=9)
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_a.value())),
                user_ha,
                places=9,
            )
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_b.value())),
                user_hb,
                places=9,
            )

            user_tb = tb0 - 0.004
            plot._cursor_b.setValue(user_tb)
            self.app.processEvents()
            self.assertAlmostEqual(float(plot._cursor_a.value()), user_ta, places=9)

            win._enable_trr_interaction()
            self.assertAlmostEqual(float(plot._cursor_a.value()), user_ta, places=9)
            self.assertAlmostEqual(float(plot._cursor_b.value()), user_tb, places=9)
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_a.value())),
                user_ha,
                places=9,
            )
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_b.value())),
                user_hb,
                places=9,
            )
            self.assertAlmostEqual(
                result.reverse_recovery.trr,
                abs(user_tb - user_ta) * 1e3,
                places=9,
            )
        finally:
            win.close()

    def test_irr_mode_updates_hb_from_ab(self):
        if not UH.is_file():
            self.skipTest("UH TSS 样本缺失")
        bundle = load_waveform(UH)
        profile = guess_profile_from_path(str(UH))
        result = extract_all(bundle, profile, load_config())
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, result)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = load_config()
        win.wave_plot = plot

        win._enable_irr_interaction()
        self.assertEqual(plot._interactive_mode, "irr_peak")
        hb = plot._from_disp("irr", float(plot._h_cursor_b.value()))
        self.assertGreater(hb, 100.0)
        self.assertAlmostEqual(result.reverse_recovery.irr, hb, delta=1.0)


if __name__ == "__main__":
    unittest.main()
