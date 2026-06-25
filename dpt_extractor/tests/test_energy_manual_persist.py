"""Eoff/Eon/Err hand-adjusted cursors must survive parameter re-clicks."""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dpt_extractor.config.loader import load_config
from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.gui.waveform_plot import WaveformPlot
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.results import power_metric_name
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.tests.sample_paths import sample_tss


SAMPLE = sample_tss("UH_750V_1050A_000.tss")


class TestEnergyManualPersist(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _window(self) -> MainWindow:
        if not SAMPLE.is_file():
            self.skipTest("UH TSS sample missing")
        cfg = load_config()
        bundle = load_waveform(SAMPLE)
        profile = guess_profile_from_path(str(SAMPLE))
        result = extract_all(bundle, profile, cfg)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = cfg
        win.result_table.set_result(result)
        win.wave_plot.plot_waveforms(bundle, profile, result)
        return win

    def _assert_energy_reclick_restores_manual(
        self,
        section: str,
        name: str,
        manual: tuple[float, float, float, float],
    ) -> None:
        win = self._window()
        win._on_value_clicked(section, name)
        plot = win.wave_plot
        assert plot._interactive_on_change is not None
        plot._interactive_on_change(*manual)

        win._on_value_clicked(section, name)
        self.assertIsNotNone(plot._cursor_a)
        self.assertIsNotNone(plot._cursor_b)
        self.assertIsNotNone(plot._h_cursor_a)
        self.assertIsNotNone(plot._h_cursor_b)
        assert plot._cursor_a is not None and plot._cursor_b is not None
        assert plot._h_cursor_a is not None and plot._h_cursor_b is not None
        self.assertAlmostEqual(float(plot._cursor_a.value()), manual[0], places=6)
        self.assertAlmostEqual(float(plot._cursor_b.value()), manual[1], places=6)

        ha_channel = plot._energy_ha_channel
        hb_channel = plot._energy_hb_channel
        ha = plot._from_disp(ha_channel, float(plot._h_cursor_a.value()))
        hb = plot._from_disp(hb_channel, float(plot._h_cursor_b.value()))
        self.assertAlmostEqual(float(ha), manual[2], places=6)
        self.assertAlmostEqual(float(hb), manual[3], places=6)

    def test_reclick_eoff_keeps_manual_energy_cursors(self) -> None:
        self._assert_energy_reclick_restores_manual(
            "关断过程",
            "Eoff",
            (14.420, 15.260, 12.0, 45.0),
        )

    def test_reclick_eon_keeps_manual_energy_cursors(self) -> None:
        self._assert_energy_reclick_restores_manual(
            "开通",
            "Eon",
            (18.360, 18.920, 35.0, 8.0),
        )

    def test_reclick_err_keeps_manual_energy_cursors(self) -> None:
        self._assert_energy_reclick_restores_manual(
            "反向恢复",
            "Err",
            (19.060, 18.560, 24.0, 8.0),
        )

    def test_energy_adjustment_feeds_power_window(self) -> None:
        win = self._window()
        section, name = "开通", "Eon"
        manual = (18.360, 18.920, 35.0, 8.0)
        win._on_value_clicked(section, name)
        assert win.wave_plot._interactive_on_change is not None
        win.wave_plot._interactive_on_change(*manual)

        power_name = power_metric_name(section)
        self.assertEqual(
            win._manual_intervals[(section, power_name)],
            (min(manual[0], manual[1]), max(manual[0], manual[1])),
        )
        win._on_value_clicked(section, power_name)
        assert win.wave_plot._cursor_a is not None and win.wave_plot._cursor_b is not None
        self.assertAlmostEqual(float(win.wave_plot._cursor_a.value()), manual[0], places=6)
        self.assertAlmostEqual(float(win.wave_plot._cursor_b.value()), manual[1], places=6)

    def test_reset_manual_clears_energy_state(self) -> None:
        win = self._window()
        win._touch_manual_waveform_source()
        win._manual_energy[("开通", "Eon")] = (1.0, 2.0, 3.0, 4.0)
        win._clear_manual_adjustments(reset_plot=False)
        self.assertNotIn(("开通", "Eon"), win._manual_energy)

    def _assert_vertical_drag_keeps_levels_and_snaps(
        self,
        section: str,
        name: str,
    ) -> None:
        win = self._window()
        win._on_value_clicked(section, name)
        plot = win.wave_plot
        assert plot._cursor_a is not None
        assert plot._cursor_b is not None
        assert plot._h_cursor_a is not None
        assert plot._h_cursor_b is not None

        ha_y0 = float(plot._h_cursor_a.value())
        hb_y0 = float(plot._h_cursor_b.value())
        a0 = float(plot._cursor_a.value())
        b0 = float(plot._cursor_b.value())

        a_ref = a0 + 0.035
        expected_a = plot._first_energy_level_crossing_us(
            plot._energy_a_channel,
            plot._from_disp(plot._energy_ha_channel, ha_y0),
            a_ref,
            use_abs=plot._energy_a_channel == "irr"
            and (
                plot._energy_fall_a_mode != "err_irr"
                or plot._energy_irr_a_uses_magnitude(
                    plot._from_disp(plot._energy_ha_channel, ha_y0)
                )
            ),
            min_t_us=plot._energy_a_anchor_us
            if plot._energy_fall_a_mode == "err_irr"
            else None,
            edge=plot._energy_manual_snap_edge("a"),
        )
        self.assertIsNotNone(expected_a)
        plot._cursor_a.setPos(a_ref)

        self.assertAlmostEqual(float(plot._h_cursor_a.value()), ha_y0, places=9)
        self.assertAlmostEqual(float(plot._h_cursor_b.value()), hb_y0, places=9)
        self.assertAlmostEqual(float(plot._cursor_a.value()), float(expected_a), places=6)

        b_ref = b0 + 0.035
        if plot._energy_b_level_vce is not None:
            b_channel = "vce"
            b_level = plot._energy_b_level_vce
        else:
            b_channel = plot._energy_b_channel
            b_level = plot._from_disp(plot._energy_hb_channel, hb_y0)
        expected_b = plot._first_energy_level_crossing_us(
            b_channel,
            b_level,
            b_ref,
            use_abs=b_channel == "irr",
            min_t_us=None
            if plot._energy_rise_b_mode == "err_vd"
            else float(plot._cursor_a.value()),
            edge=plot._energy_manual_snap_edge("b"),
        )
        self.assertIsNotNone(expected_b)
        plot._cursor_b.setPos(b_ref)

        self.assertAlmostEqual(float(plot._h_cursor_a.value()), ha_y0, places=9)
        self.assertAlmostEqual(float(plot._h_cursor_b.value()), hb_y0, places=9)
        self.assertAlmostEqual(float(plot._cursor_b.value()), float(expected_b), places=6)

    def test_vertical_drag_keeps_energy_levels_and_snaps_to_crossing(self) -> None:
        for section, name in (
            ("关断过程", "Eoff"),
            ("开通", "Eon"),
            ("反向恢复", "Err"),
        ):
            with self.subTest(section=section, name=name):
                self._assert_vertical_drag_keeps_levels_and_snaps(section, name)

    def test_energy_snap_uses_first_edge_crossing_in_visible_window(self) -> None:
        plot = WaveformPlot()
        plot._interactive_search_t0_us = 0.0
        plot._interactive_search_t1_us = 1.0
        plot.current_x_range_us = lambda: (0.05, 0.75)  # type: ignore[method-assign]

        t = np.array([0.0, 0.1, 0.2, 0.4, 0.5, 0.6, 0.8], dtype=float)
        rising = np.array([-1.0, -1.0, 1.0, 1.0, -1.0, 1.0, 1.0], dtype=float)
        plot._series_for_channel = lambda channel: (t, rising)  # type: ignore[method-assign]

        first_rise = plot._first_energy_level_crossing_us(
            "ic", 0.0, 0.58, edge="rising"
        )
        self.assertAlmostEqual(float(first_rise), 0.15, places=9)

        falling = np.array([1.0, 1.0, -1.0, -1.0, 1.0, -1.0, -1.0], dtype=float)
        plot._series_for_channel = lambda channel: (t, falling)  # type: ignore[method-assign]

        first_fall = plot._first_energy_level_crossing_us(
            "ic", 0.0, 0.58, edge="falling"
        )
        self.assertAlmostEqual(float(first_fall), 0.15, places=9)

        gated_fall = plot._first_energy_level_crossing_us(
            "ic", 0.0, 0.58, edge="falling", min_t_us=0.3
        )
        self.assertAlmostEqual(float(gated_fall), 0.55, places=9)


if __name__ == "__main__":
    unittest.main()
