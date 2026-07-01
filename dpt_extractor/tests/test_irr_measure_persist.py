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


class TestIrrMeasurePersist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_reclick_trr_keeps_manual_ha(self):
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

        win._enable_trr_interaction()
        # UH 为负向主瓣：Ha 过深（如 -120A）无有效交点；用 0A 验证重进 Trr 后保留手动 Ha
        user_ha = 0.0
        plot._interactive_syncing = True
        try:
            plot._h_cursor_a.setPos(plot._to_disp("irr", user_ha))
        finally:
            plot._interactive_syncing = False
        ta_before = float(plot._cursor_a.value())
        tb_before = float(plot._cursor_b.value())
        plot._on_horizontal_cursor_moved()
        ta_after = float(plot._cursor_a.value())
        tb_after = float(plot._cursor_b.value())

        win._enable_trr_interaction()
        ha_after = plot._from_disp("irr", float(plot._h_cursor_a.value()))
        self.assertAlmostEqual(ha_after, user_ha, delta=0.5)
        self.assertTrue(abs(ta_after) > 0.0)
        self.assertTrue(abs(tb_after) > 0.0)

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
