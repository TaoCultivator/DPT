from __future__ import annotations

import os
import sys
import unittest

from dpt_extractor.models.slope_range import (
    AUTO_MAX_SLOPE_LABEL,
    CUSTOM_RANGE_LABEL,
    SlopeRange,
    auto_max_slope_range,
    default_slope_ranges,
    preset_index_for_range,
)


class TestSlopeRangePresetMatch(unittest.TestCase):
    def test_auto_mode_never_collapses_to_a_percentage_preset(self):
        sr = auto_max_slope_range("on_dvdt")
        self.assertTrue(sr.is_auto_max)
        self.assertEqual(sr.label(), AUTO_MAX_SLOPE_LABEL)
        self.assertEqual(preset_index_for_range("on_dvdt", sr), -1)

    def test_on_dvdt_default_matches_first_preset(self):
        sr = default_slope_ranges()["on_dvdt"]
        self.assertEqual(preset_index_for_range("on_dvdt", sr), 0)

    def test_on_dvdt_percent_only_match_ignores_ic_direction(self):
        sr = SlopeRange(90.0, 10.0, ic_direction="rise")
        self.assertEqual(preset_index_for_range("on_dvdt", sr), 0)

    def test_rr_didt_if_irm_preset(self):
        from dpt_extractor.models.slope_range import preset_to_range, SLOPE_RANGE_PRESETS

        sr = preset_to_range(SLOPE_RANGE_PRESETS["rr_didt"][2])
        self.assertEqual(sr.ic_reference, "if_irm")
        self.assertEqual(sr.label(), "50%IF→50%IRM")
        self.assertEqual(preset_index_for_range("rr_didt", sr), 2)

    def test_rr_custom_range_keeps_user_a_b_order(self):
        sr = SlopeRange(30.0, 70.0, ic_reference="idm", ic_direction="rise")
        self.assertEqual(sr.as_fractions(), (0.3, 0.7))
        self.assertEqual(sr.label(), "30%→70%")


class TestSlopeRangeDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_custom_selection_exposes_start_end_in_same_dialog(self) -> None:
        from dpt_extractor.gui.slope_range_dialog import SlopeRangeDialog

        dialog = SlopeRangeDialog(
            title="关断 dv/dt 取值范围",
            initial=default_slope_ranges()["off_dvdt"],
            row_key="off_dvdt",
        )
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()

        dialog.range_selector.setCurrentText(CUSTOM_RANGE_LABEL)
        self.app.processEvents()
        self.assertTrue(dialog.custom_editor.isVisible())
        self.assertTrue(dialog.spin_start.isEnabled())
        self.assertTrue(dialog.spin_end.isEnabled())

        dialog.spin_start.setValue(50.0)
        dialog.spin_end.setValue(70.0)
        dialog._accept()
        selected = dialog.range_value()
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.label(), "50%→70%")

    def test_auto_max_selection_is_available_for_every_slope_row(self) -> None:
        from dpt_extractor.gui.slope_range_dialog import SlopeRangeDialog
        from dpt_extractor.models.slope_range import SLOPE_ROW_KEYS

        for row_key in SLOPE_ROW_KEYS.values():
            with self.subTest(row_key=row_key):
                dialog = SlopeRangeDialog(
                    initial=default_slope_ranges()[row_key],
                    row_key=row_key,
                )
                self.addCleanup(dialog.close)
                dialog.range_selector.setCurrentText(AUTO_MAX_SLOPE_LABEL)
                dialog._accept()
                selected = dialog.range_value()
                self.assertIsNotNone(selected)
                assert selected is not None
                self.assertTrue(selected.is_auto_max)
                self.assertFalse(dialog.custom_editor.isVisible())
                if row_key == "rr_didt":
                    self.assertEqual(selected.ic_reference, "idm")

    def test_custom_didt_keeps_the_existing_current_reference(self) -> None:
        from dpt_extractor.gui.slope_range_dialog import SlopeRangeDialog

        dialog = SlopeRangeDialog(
            initial=default_slope_ranges()["off_didt"],
            row_key="off_didt",
        )
        self.addCleanup(dialog.close)
        dialog.range_selector.setCurrentText(CUSTOM_RANGE_LABEL)
        dialog.spin_start.setValue(50.0)
        dialog.spin_end.setValue(70.0)
        dialog._accept()

        selected = dialog.range_value()
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.ic_reference, "top")
        self.assertEqual(selected.label(), "50%→70%")

    def test_rr_didt_dynamic_sections_do_not_resize_the_native_dialog(self) -> None:
        from dpt_extractor.gui.slope_range_dialog import SlopeRangeDialog

        dialog = SlopeRangeDialog(
            title="反向恢复 di/dt 取值范围",
            initial=default_slope_ranges()["rr_didt"],
            row_key="rr_didt",
        )
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        preset_size = dialog.size()

        dialog.range_selector.setCurrentText(CUSTOM_RANGE_LABEL)
        self.app.processEvents()
        custom_idm_size = dialog.size()

        dialog.algorithm_selector.setCurrentIndex(1)
        self.app.processEvents()
        custom_if_irm_size = dialog.size()

        dialog.range_selector.setCurrentIndex(0)
        self.app.processEvents()
        restored_preset_size = dialog.size()

        self.assertEqual(custom_idm_size, preset_size)
        self.assertEqual(custom_if_irm_size, preset_size)
        self.assertEqual(restored_preset_size, preset_size)

    def test_preset_selection_returns_the_complete_preset(self) -> None:
        from dpt_extractor.gui.slope_range_dialog import SlopeRangeDialog

        dialog = SlopeRangeDialog(
            initial=SlopeRange(50.0, 70.0),
            row_key="on_dvdt",
        )
        self.addCleanup(dialog.close)
        dialog.range_selector.setCurrentText("90%→10%")
        dialog._accept()

        selected = dialog.range_value()
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.as_fractions(), (0.9, 0.1))
        self.assertEqual(preset_index_for_range("on_dvdt", selected), 0)

    def test_range_change_discards_only_the_affected_manual_slope(self) -> None:
        from unittest.mock import patch

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.slope_range import (
            SLOPE_RANGE_PRESETS,
            SLOPE_ROW_KEYS,
            preset_to_range,
        )

        for param_key, row_key in SLOPE_ROW_KEYS.items():
            with self.subTest(row_key=row_key):
                win = MainWindow()
                try:
                    section, metric = param_key
                    cache = (
                        win._manual_dvdt
                        if metric == "dv/dt"
                        else win._manual_didt
                    )
                    cache[param_key] = (1.0, 2.0, 3.0, 4.0)
                    win._manual_intervals[param_key] = (1.0, 2.0)
                    win._manual_energy[("开通", "Eon")] = (
                        1.0,
                        2.0,
                        3.0,
                        4.0,
                    )
                    ls_key = {
                        ("关断过程", "di/dt"): ("关断过程", "Ls_off"),
                        ("开通", "di/dt"): ("开通", "Ls_on"),
                    }.get(param_key)
                    if ls_key is not None:
                        win._manual_intervals[ls_key] = (1.0, 2.0)

                    changed = preset_to_range(SLOPE_RANGE_PRESETS[row_key][1])
                    with patch.object(win, "_recalculate") as recalculate:
                        win._on_slope_range_changed(row_key, changed)

                    recalculate.assert_called_once_with()
                    self.assertNotIn(param_key, cache)
                    self.assertNotIn(param_key, win._manual_intervals)
                    if ls_key is not None:
                        self.assertNotIn(ls_key, win._manual_intervals)
                    self.assertIn(("开通", "Eon"), win._manual_energy)
                finally:
                    win.close()


if __name__ == "__main__":
    unittest.main()
