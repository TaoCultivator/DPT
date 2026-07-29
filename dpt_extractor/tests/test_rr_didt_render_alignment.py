"""RR di/dt horizontal-cursor rendering regression for the 20260717 HT sample."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

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

EXPECTED_HB_A = -1044.40625


@unittest.skipUnless(TARGET.exists(), "songzhenxi 20260717 HT target sample missing")
class TestRrDidtRenderAlignment(unittest.TestCase):
    """The signed IDM platform midpoint must coincide with the rendered Hb line."""

    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    @classmethod
    def _process_layout_events(cls) -> None:
        # Repeated passes intentionally cover queued resize/ViewBox/trace refreshes.
        for _ in range(4):
            cls.app.processEvents()

    def _platform_bounds_us(self, win) -> tuple[float, float]:
        from dpt_extractor.metrics.iec_windows import err_recovery_peak_index
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        self.assertIsNotNone(win.bundle)
        self.assertIsNotNone(win.result)
        assert win.bundle is not None and win.result is not None
        rr0, rr1 = win.result.segments.reverse_recovery
        irr = np.asarray(
            bundle_reverse_recovery_current(win.bundle, win.profile),
            dtype=np.float64,
        )
        peak_idx = rr0 + int(
            err_recovery_peak_index(irr[rr0 : rr1 + 1], win.bundle.dt)
        )
        peak_t_us = float(win.bundle.t[peak_idx]) * 1e6
        return peak_t_us - 0.6, peak_t_us - 0.2

    def _raw_platform_midpoint(self, win) -> float:
        from dpt_extractor.metrics.slopes import (
            _rr_quiet_local_platform_window,
            _rr_spike_guarded_extreme_index,
        )
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        self.assertIsNotNone(win.bundle)
        assert win.bundle is not None
        t_us = np.asarray(win.bundle.t, dtype=np.float64) * 1e6
        irr = np.asarray(
            bundle_reverse_recovery_current(win.bundle, win.profile),
            dtype=np.float64,
        )
        platform_t0_us, platform_t1_us = self._platform_bounds_us(win)
        mask = (
            np.isfinite(t_us)
            & np.isfinite(irr)
            & (t_us >= platform_t0_us)
            & (t_us <= platform_t1_us)
        )
        source_region = irr[mask]
        self.assertGreater(source_region.size, 1000)
        platform = _rr_quiet_local_platform_window(
            source_region,
            win.bundle.dt,
            min_ns=200.0,
        )
        self.assertGreater(platform.size, 100)
        i_min = _rr_spike_guarded_extreme_index(platform, maximum=False)
        i_max = _rr_spike_guarded_extreme_index(platform, maximum=True)
        return 0.5 * (float(platform[i_min]) + float(platform[i_max]))

    def _assert_hb_rendered_on_platform_midpoint(
        self,
        win,
        expected_hb_a: float,
        *,
        checkpoint: str,
    ) -> None:
        from PyQt6.QtCore import QPointF

        from dpt_extractor.metrics.slopes import _rr_spike_guarded_extreme_index

        plot = win.wave_plot
        self.assertIsNotNone(plot._h_cursor_b, checkpoint)
        assert plot._h_cursor_b is not None

        physical_hb = plot._from_disp("irr", float(plot._h_cursor_b.value()))
        self.assertAlmostEqual(physical_hb, EXPECTED_HB_A, places=9, msg=checkpoint)
        self.assertAlmostEqual(physical_hb, expected_hb_a, places=9, msg=checkpoint)

        vb = plot.plot.getPlotItem().getViewBox()
        x_range = vb.viewRange()[0]
        scene_x_view = 0.5 * (float(x_range[0]) + float(x_range[1]))

        def scene_y(y_div: float) -> float:
            return float(
                vb.mapViewToScene(QPointF(scene_x_view, float(y_div))).y()
            )

        cursor_scene_y = scene_y(float(plot._h_cursor_b.value()))
        theory_scene_y = scene_y(plot._to_disp("irr", expected_hb_a))
        self.assertLessEqual(
            abs(cursor_scene_y - theory_scene_y),
            0.01,
            f"{checkpoint}: Hb and theoretical midpoint diverged in scene pixels",
        )

        # Inspect the data actually supplied to the visible PlotDataItem.  It is
        # intentionally decimated compared with the 5000-point broad source
        # region.  Select its own quiet sub-band before taking raw extrema so a
        # slow edge at the right boundary cannot circularly validate a cursor
        # that sits above the visible stable platform.
        display_key = plot._display_key_for_channel("irr")
        self.assertIn(display_key, plot._trace_items, checkpoint)
        item = plot._trace_items[display_key]
        self.assertTrue(item.isVisible(), checkpoint)
        trace_x, trace_y = item.getData()
        self.assertIsNotNone(trace_x, checkpoint)
        self.assertIsNotNone(trace_y, checkpoint)
        assert trace_x is not None and trace_y is not None
        trace_x = np.asarray(trace_x, dtype=np.float64)
        trace_y = np.asarray(trace_y, dtype=np.float64)
        platform_t0_us, platform_t1_us = self._platform_bounds_us(win)
        visible_mask = (
            np.isfinite(trace_x)
            & np.isfinite(trace_y)
            & (trace_x >= platform_t0_us)
            & (trace_x <= platform_t1_us)
        )
        visible_x = trace_x[visible_mask]
        visible_y = trace_y[visible_mask]
        self.assertGreater(visible_y.size, 100, checkpoint)
        visible_physical_source = np.asarray(
            [plot._from_disp("irr", float(y)) for y in visible_y],
            dtype=np.float64,
        )
        visible_dt = float(np.median(np.diff(visible_x))) * 1e-6
        from dpt_extractor.metrics.slopes import _rr_quiet_local_platform_window

        visible_physical = _rr_quiet_local_platform_window(
            visible_physical_source,
            visible_dt,
            min_ns=200.0,
        )
        i_min = _rr_spike_guarded_extreme_index(
            visible_physical,
            maximum=False,
        )
        i_max = _rr_spike_guarded_extreme_index(
            visible_physical,
            maximum=True,
        )
        visible_center_physical = 0.5 * (
            float(visible_physical[i_min]) + float(visible_physical[i_max])
        )
        visible_center_y = plot._to_disp("irr", visible_center_physical)
        visible_center_scene_y = scene_y(visible_center_y)
        self.assertLessEqual(
            abs(cursor_scene_y - visible_center_scene_y),
            0.5,
            f"{checkpoint}: Hb missed the center of the visible stable band",
        )

    def test_rr_didt_hb_stays_pixel_aligned_through_real_gui_redraws(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win.resize(1600, 1000)
            win.show()
            self._process_layout_events()
            win._load_file(str(TARGET))
            win._on_value_clicked("反向恢复", "di/dt")
            self._process_layout_events()

            expected_hb_a = self._raw_platform_midpoint(win)
            self.assertEqual(expected_hb_a, EXPECTED_HB_A)
            self._assert_hb_rendered_on_platform_midpoint(
                win,
                expected_hb_a,
                checkpoint="initial RR di/dt selection",
            )

            for size in ((1180, 760), (1760, 1040)):
                win.resize(*size)
                self._process_layout_events()
                self._assert_hb_rendered_on_platform_midpoint(
                    win,
                    expected_hb_a,
                    checkpoint=f"resize {size[0]}x{size[1]}",
                )

            plot = win.wave_plot
            rr_display_key = plot._display_key_for_channel("irr")
            other_key = next(
                key
                for key, item in plot._trace_items.items()
                if key != rr_display_key and item.isVisible()
            )
            plot._on_legend_clicked(other_key)
            self._process_layout_events()
            self._assert_hb_rendered_on_platform_midpoint(
                win,
                expected_hb_a,
                checkpoint=f"raise {other_key}",
            )
            plot._on_legend_double_clicked(other_key)
            self._process_layout_events()
            self._assert_hb_rendered_on_platform_midpoint(
                win,
                expected_hb_a,
                checkpoint=f"highlight {other_key}",
            )

            # Changing CH3's vertical transform must preserve the physical Hb
            # and reproject both the trace and line to the same scene pixel.
            original_scale = float(plot._disp_scale[rr_display_key])
            plot._set_channel_scale(rr_display_key, original_scale * 1.25)
            plot._set_channel_offset(
                rr_display_key,
                float(plot._disp_offset[rr_display_key]) + 0.35,
            )
            self._process_layout_events()
            self._assert_hb_rendered_on_platform_midpoint(
                win,
                expected_hb_a,
                checkpoint="CH3 V/div and offset change",
            )

            # Exercise the same page replot path used to freeze and restore a
            # report capture page.  The active RR metric and display transform
            # must be reapplied before the next frame is captured.
            report_page = win._current_report_page_state()
            win._apply_report_page_state(report_page)
            self._process_layout_events()
            self._assert_hb_rendered_on_platform_midpoint(
                win,
                expected_hb_a,
                checkpoint="report page replot",
            )
        finally:
            win.close()
            self._process_layout_events()


if __name__ == "__main__":
    unittest.main()
