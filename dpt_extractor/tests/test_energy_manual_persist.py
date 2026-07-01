"""Eoff/Eon/Err hand-adjusted cursors must survive parameter re-clicks."""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dpt_extractor.config.loader import load_config
from dpt_extractor.gui.main_window import MainWindow
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

    def _assert_energy_reclick_keeps_current_view(
        self,
        section: str,
        name: str,
        manual: tuple[float, float, float, float],
    ) -> None:
        from PyQt6.QtWidgets import QApplication

        win = self._window()
        win._on_value_clicked(section, name)
        plot = win.wave_plot
        assert plot._interactive_on_change is not None
        plot._interactive_on_change(*manual)

        plot.focus_interval_us(12.0, 14.0)
        before = plot.current_x_range_us()
        self.assertIsNotNone(before)
        assert before is not None

        win._on_value_clicked(section, name)
        QApplication.processEvents()
        after = plot.current_x_range_us()
        self.assertIsNotNone(after)
        assert after is not None
        self.assertAlmostEqual(after[0], before[0], places=6)
        self.assertAlmostEqual(after[1], before[1], places=6)
        win.close()

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

    def test_reclick_energy_keeps_current_view(self) -> None:
        for section, name, manual in (
            ("关断过程", "Eoff", (14.420, 15.260, 12.0, 45.0)),
            ("开通", "Eon", (18.360, 18.920, 35.0, 8.0)),
            ("反向恢复", "Err", (19.060, 18.560, 24.0, 8.0)),
        ):
            with self.subTest(section=section, name=name):
                self._assert_energy_reclick_keeps_current_view(section, name, manual)

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

    def _assert_vertical_drag_keeps_levels_and_custom_time(
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

        a_ref = a0 + 0.037
        plot._cursor_a.setPos(a_ref)

        self.assertAlmostEqual(float(plot._h_cursor_a.value()), ha_y0, places=9)
        self.assertAlmostEqual(float(plot._h_cursor_b.value()), hb_y0, places=9)
        self.assertAlmostEqual(float(plot._cursor_a.value()), a_ref, places=6)

        b_ref = b0 + 0.063
        plot._cursor_b.setPos(b_ref)

        self.assertAlmostEqual(float(plot._h_cursor_a.value()), ha_y0, places=9)
        self.assertAlmostEqual(float(plot._h_cursor_b.value()), hb_y0, places=9)
        self.assertAlmostEqual(float(plot._cursor_b.value()), b_ref, places=6)

        stored = win._manual_energy.get((section, name))
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertAlmostEqual(stored[0], a_ref, places=6)
        self.assertAlmostEqual(stored[1], b_ref, places=6)

    def test_vertical_drag_keeps_energy_levels_and_custom_time(self) -> None:
        for section, name in (
            ("关断过程", "Eoff"),
            ("开通", "Eon"),
            ("反向恢复", "Err"),
        ):
            with self.subTest(section=section, name=name):
                self._assert_vertical_drag_keeps_levels_and_custom_time(section, name)

    def test_horizontal_drag_keeps_energy_vertical_cursors(self) -> None:
        win = self._window()
        section, name = "关断过程", "Eoff"
        win._on_value_clicked(section, name)
        plot = win.wave_plot
        assert plot._cursor_a is not None
        assert plot._cursor_b is not None
        assert plot._h_cursor_a is not None
        assert plot._h_cursor_b is not None

        plot._set_cursor_link_mode(linked=True)
        a0 = float(plot._cursor_a.value())
        b0 = float(plot._cursor_b.value())
        ha_y = float(plot._h_cursor_a.value()) + 0.125
        hb_y = float(plot._h_cursor_b.value()) - 0.125

        plot._h_cursor_a.setPos(ha_y)
        plot._h_cursor_b.setPos(hb_y)

        self.assertAlmostEqual(float(plot._cursor_a.value()), a0, places=6)
        self.assertAlmostEqual(float(plot._cursor_b.value()), b0, places=6)

        stored = win._manual_energy.get((section, name))
        self.assertIsNotNone(stored)
        assert stored is not None
        expected_ha = plot._from_disp(plot._energy_ha_channel, ha_y)
        expected_hb = plot._from_disp(plot._energy_hb_channel, hb_y)
        self.assertAlmostEqual(stored[2], expected_ha, places=6)
        self.assertAlmostEqual(stored[3], expected_hb, places=6)

    def test_energy_cursor_drag_does_not_refocus_view(self) -> None:
        from PyQt6.QtWidgets import QApplication

        win = self._window()
        win._on_value_clicked("开通", "Eon")
        plot = win.wave_plot
        assert plot._cursor_a is not None
        assert plot._h_cursor_b is not None

        plot.focus_interval_us(12.0, 14.0)
        before = plot.current_x_range_us()
        self.assertIsNotNone(before)
        assert before is not None

        plot._cursor_a.setPos(float(plot._cursor_a.value()) + 0.025)
        QApplication.processEvents()
        after_vertical = plot.current_x_range_us()
        self.assertIsNotNone(after_vertical)
        assert after_vertical is not None
        self.assertAlmostEqual(after_vertical[0], before[0], places=6)
        self.assertAlmostEqual(after_vertical[1], before[1], places=6)

        plot._h_cursor_b.setPos(float(plot._h_cursor_b.value()) + 0.1)
        QApplication.processEvents()
        after_horizontal = plot.current_x_range_us()
        self.assertIsNotNone(after_horizontal)
        assert after_horizontal is not None
        self.assertAlmostEqual(after_horizontal[0], before[0], places=6)
        self.assertAlmostEqual(after_horizontal[1], before[1], places=6)
        win.close()


if __name__ == "__main__":
    unittest.main()
