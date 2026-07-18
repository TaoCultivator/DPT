"""Regression coverage for the RR slope-cursor mouse-move hot path."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
TARGET = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "HT"
    / "UH_750V_1048A_000.tss"
)


@unittest.skipUnless(TARGET.exists(), "songzhenxi RR cursor sample missing")
class TestRrCursorMovePerformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        self.win = MainWindow()
        self.win.resize(1600, 1000)
        self.win.show()
        self.app.processEvents()
        self.win._load_file(str(TARGET))
        self.win._on_value_clicked("反向恢复", "di/dt")
        for _ in range(3):
            self.app.processEvents()

    def tearDown(self) -> None:
        self.win.close()
        self.app.processEvents()

    def test_cached_logical_irr_is_read_only_and_fails_closed_when_stale(self) -> None:
        from dpt_extractor.models.waveform import channel_reference_base_name

        plot = self.win.wave_plot
        bundle = self.win.bundle
        profile = self.win.profile
        self.assertIsNotNone(bundle)
        assert bundle is not None

        cached = plot.logical_reverse_recovery_current(bundle, profile)
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertFalse(cached.flags.writeable)
        self.assertTrue(np.shares_memory(cached, plot._interactive_irr))
        with self.assertRaises(ValueError):
            cached[0] = cached[0]

        remapped = replace(profile, irr=f"-{profile.irr.lstrip('-')}")
        self.assertIsNone(plot.logical_reverse_recovery_current(bundle, remapped))

        base = channel_reference_base_name(profile.irr)
        original_display = set(bundle.meta.channel_display_inversions)
        try:
            if base in bundle.meta.channel_display_inversions:
                bundle.meta.channel_display_inversions.remove(base)
            else:
                bundle.meta.channel_display_inversions.add(base)
            self.assertIsNone(plot.logical_reverse_recovery_current(bundle, profile))
        finally:
            bundle.meta.channel_display_inversions = original_display

    def test_plain_hover_does_not_recalculate_or_refresh_cursor_readout(self) -> None:
        from PyQt6.QtCore import QPoint
        from PyQt6.QtTest import QTest

        plot = self.win.wave_plot
        viewport = plot.plot.viewport()
        with (
            patch.object(plot, "_update_readout", wraps=plot._update_readout) as readout,
            patch.object(
                self.win,
                "_compute_didt_base_top",
                wraps=self.win._compute_didt_base_top,
            ) as compute,
        ):
            for x, y in ((90, 90), (220, 140), (360, 210), (500, 280)):
                QTest.mouseMove(viewport, QPoint(x, y), 0)
                self.app.processEvents()
            self.assertEqual(compute.call_count, 0)
            self.assertEqual(readout.call_count, 0)

    def test_rr_slope_burst_computes_and_reads_exactly_once_per_event(self) -> None:
        from PyQt6.QtCore import QPointF

        plot = self.win.wave_plot
        result = self.win.result
        bundle = self.win.bundle
        self.assertIsNotNone(result)
        self.assertIsNotNone(bundle)
        self.assertIsNotNone(plot._h_cursor_b)
        self.assertIsNotNone(plot._cursor_a)
        self.assertIsNotNone(plot._cursor_b)
        assert result is not None and bundle is not None
        assert plot._h_cursor_b is not None
        assert plot._cursor_a is not None and plot._cursor_b is not None

        original_hb_div = float(plot._h_cursor_b.value())
        original_hb_a = plot._from_disp("irr", original_hb_div)
        original_didt = float(result.reverse_recovery.didt_irr)
        original_a_us = float(plot._cursor_a.value())
        original_b_us = float(plot._cursor_b.value())

        cached = plot.logical_reverse_recovery_current(bundle, self.win.profile)
        self.assertIsNotNone(cached)
        burst = 24
        with (
            patch.object(plot, "_update_readout", wraps=plot._update_readout) as readout,
            patch.object(
                self.win,
                "_compute_didt_base_top",
                wraps=self.win._compute_didt_base_top,
            ) as compute,
            patch(
                "dpt_extractor.models.waveform.bundle_reverse_recovery_current",
                side_effect=AssertionError("valid plot Irr cache unexpectedly missed"),
            ) as fallback,
            patch(
                "dpt_extractor.gui.main_window.prepare_rr_didt_series",
                side_effect=AssertionError("RR cursor event rebuilt its prepared series"),
            ) as prepare_again,
            patch(
                "dpt_extractor.metrics.slopes._rr_repair_time_axis",
                side_effect=AssertionError("RR cursor event rescanned the time axis"),
            ) as repair_time,
            patch(
                "dpt_extractor.metrics.slopes._rr_repair_finite_signal",
                side_effect=AssertionError("RR cursor event repaired full current data"),
            ) as repair_current,
            patch(
                "dpt_extractor.metrics.slopes._rr_spike_guarded_extreme_index",
                side_effect=AssertionError("RR cursor event repeated extrema filtering"),
            ) as filter_extrema,
        ):
            for i in range(burst - 1):
                delta = 0.001 if i % 2 else -0.001
                plot._h_cursor_b.setPos(original_hb_div + delta)
            plot._h_cursor_b.setPos(original_hb_div)

            self.assertEqual(compute.call_count, burst)
            self.assertEqual(fallback.call_count, 0)
            self.assertEqual(prepare_again.call_count, 0)
            self.assertEqual(repair_time.call_count, 0)
            self.assertEqual(repair_current.call_count, 0)
            self.assertEqual(filter_extrema.call_count, 0)
            self.assertEqual(readout.call_count, burst)
            for call in compute.call_args_list:
                prepared = call.kwargs.get("rr_prepared")
                self.assertIsNotNone(prepared)
                self.assertTrue(prepared.valid)

        self.assertAlmostEqual(
            float(result.reverse_recovery.didt_irr), original_didt, places=12
        )
        self.assertAlmostEqual(float(plot._cursor_a.value()), original_a_us, places=12)
        self.assertAlmostEqual(float(plot._cursor_b.value()), original_b_us, places=12)
        self.assertEqual(plot._from_disp("irr", float(plot._h_cursor_b.value())), original_hb_a)

        expected_text = plot._scope_quantity_text(original_hb_a, "A")
        self.assertIsNotNone(plot._cursor_hb_v_label)
        assert plot._cursor_hb_v_label is not None
        self.assertIn(expected_text, plot._cursor_hb_v_label.toPlainText())

        vb = plot.plot.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        cursor_scene_y = vb.mapViewToScene(
            QPointF(0.5 * (float(x0) + float(x1)), float(plot._h_cursor_b.value()))
        ).y()
        expected_scene_y = vb.mapViewToScene(
            QPointF(0.5 * (float(x0) + float(x1)), plot._to_disp("irr", original_hb_a))
        ).y()
        self.assertLessEqual(abs(float(cursor_scene_y) - float(expected_scene_y)), 0.01)

    def test_non_slope_horizontal_move_remains_immediate(self) -> None:
        plot = self.win.wave_plot
        plot.disable_interactive_cursors()
        self.assertEqual(plot._interactive_mode, "global")
        assert plot._h_cursor_b is not None
        with patch.object(plot, "_update_readout", wraps=plot._update_readout) as readout:
            plot._h_cursor_b.setPos(float(plot._h_cursor_b.value()) + 0.001)
            self.assertEqual(readout.call_count, 1)


if __name__ == "__main__":
    unittest.main()
