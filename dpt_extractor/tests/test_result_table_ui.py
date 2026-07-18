from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QPushButton,
)

from dpt_extractor.gui.result_table import (
    ENERGY_TEXT_COLOR,
    MISSING_TEXT_COLOR,
    MISSING_VALUE_TEXT,
    RESULT_OFFSET_TEXT,
    RESULT_OFFSET_POPUP_SELECTED,
    RESULT_OFFSET_VALUE_BG,
    SECTION_ACTIVE_BG,
    SECTION_ACTIVE_TEXT,
    ResultTable,
)
from dpt_extractor.gui.theme import SECTION_OFF, SECTION_ON, SECTION_RR
from dpt_extractor.models.results import (
    ExtractResult,
    ReverseRecoveryResult,
    SegmentIndices,
    ShortCircuitResult,
    TurnOffResult,
    TurnOnResult,
)


def _sample_result() -> ExtractResult:
    return ExtractResult(
        phase="U",
        profile_code="UH",
        source_path="UH_RT.tss",
        vdc=764.1,
        segments=SegmentIndices(
            turn_off=(0, 1),
            turn_on=(2, 3),
            reverse_recovery=(4, 5),
        ),
        turn_off=TurnOffResult(
            delta_vce=337.22,
            ic_off_max=1051.25,
            vce_off_max=1093.25,
            dvdt=7.594,
            didt=10.623,
            pmax=910.5,
            eoff=88.884,
            eoff_range="V↑~Ic平稳",
        ),
        turn_on=TurnOnResult(
            delta_vce=309.70,
            ic_on_max=1154.22,
            vce_on_max=763.59,
            turn_on_current=1036.12,
            dvdt=2.597,
            didt=6.565,
            pmax=640.2,
            eon=68.662,
        ),
        reverse_recovery=ReverseRecoveryResult(
            irr=173.91,
            trr=35.496,
            vrr=985.03,
            dvdt_max=12.971,
            didt_irr=13.738,
            pdmax=158.9,
            err=1.116,
        ),
    )


def _row_for(table: ResultTable, section: str, name: str) -> int:
    for row, meta in enumerate(table._row_meta):
        if meta == (section, name):
            return row
    raise AssertionError(f"missing row: {section}/{name}")


def _alignment_value(value) -> int:
    return value.value if hasattr(value, "value") else int(value)


class TestResultTableUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_section_labels_stack_energy_rows_and_active_section(self) -> None:
        table = ResultTable()
        table.set_result(_sample_result())
        self.assertGreaterEqual(table.summary.text().count(ENERGY_TEXT_COLOR), 6)

        on_start, _ = table._section_ranges["开通"]
        rr_start, _ = table._section_ranges["反向恢复"]
        self.assertEqual(
            table.table.item(on_start, 0).data(Qt.ItemDataRole.DisplayRole),
            "开\n通",
        )
        self.assertEqual(
            table.table.item(rr_start, 0).data(Qt.ItemDataRole.DisplayRole),
            "反\n向\n恢\n复",
        )

        for section, name, expected_bg in (
            ("关断过程", "Eoff", SECTION_OFF),
            ("开通", "Eon", SECTION_ON),
            ("反向恢复", "Err", SECTION_RR),
        ):
            row = _row_for(table, section, name)
            self.assertEqual(table.table.item(row, 1).background().color().name(), expected_bg)
            self.assertEqual(
                table.table.item(row, 4).foreground().color().name(),
                ENERGY_TEXT_COLOR,
            )

        for section, name in (
            ("关断过程", "Pmax"),
            ("开通", "Pmax"),
            ("反向恢复", "Pdmax"),
        ):
            row = _row_for(table, section, name)
            self.assertEqual(table.table.item(row, 2).text(), "KW")

        table.set_active_metric("开通", "di/dt")
        self.assertEqual(table.table.currentRow(), _row_for(table, "开通", "di/dt"))
        self.assertEqual(
            table.table.item(on_start, 0).background().color().name(),
            SECTION_ACTIVE_BG,
        )
        self.assertEqual(
            table.table.item(on_start, 0).foreground().color().name(),
            SECTION_ACTIVE_TEXT,
        )
        table.close()

    def test_unavailable_metrics_show_red_dash_value(self) -> None:
        table = ResultTable()
        result = _sample_result()
        result.unavailable_metrics.update(
            {
                ("关断过程", "串扰电压"),
                ("反向恢复", "Err"),
            }
        )
        table.set_result(result)

        for section, name in (
            ("关断过程", "串扰电压"),
            ("反向恢复", "Err"),
        ):
            row = _row_for(table, section, name)
            self.assertEqual(table.table.item(row, 4).text(), MISSING_VALUE_TEXT)
            self.assertEqual(
                table.table.item(row, 4).foreground().color().name(),
                MISSING_TEXT_COLOR,
            )

        row = _row_for(table, "反向恢复", "Irr")
        self.assertNotEqual(
            table.table.item(row, 4).foreground().color().name(),
            MISSING_TEXT_COLOR,
        )
        table.close()

    def test_short_summary_matches_unavailable_detail_rows(self) -> None:
        table = ResultTable()
        result = _sample_result()
        result.short_circuit_mode = True
        result.short_circuit = ShortCircuitResult(
            ic_max=float("nan"),
            tsc=float("nan"),
            esc_dut=float("nan"),
            esc_other=float("nan"),
        )
        unavailable = {
            ("短路过程", "短路电流Imax"),
            ("短路过程", "短路时间Tsc"),
            ("短路过程", "短路能量Esc_本管"),
            ("短路过程", "短路能量Esc_对管"),
        }
        result.unavailable_metrics.update(unavailable)
        table.set_result(result)

        summary_html = table.summary.text()
        self.assertNotIn("nan", summary_html.lower())
        self.assertEqual(summary_html.count(f"color:{MISSING_TEXT_COLOR}"), 4)
        for _, name in unavailable:
            row = _row_for(table, "短路过程", name)
            self.assertEqual(table.table.item(row, 4).text(), MISSING_VALUE_TEXT)
            self.assertEqual(
                table.table.item(row, 4).foreground().color().name(),
                MISSING_TEXT_COLOR,
            )
        table.close()

    def test_main_window_skips_unavailable_metric_click_without_channel(self) -> None:
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 100
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("W", "upper")
        bundle = WaveformBundle(
            t=t,
            channels={
                profile.vge: np.linspace(-5.0, 15.0, n),
                profile.vce: np.linspace(0.0, 700.0, n),
                profile.irr: np.linspace(0.0, 80.0, n),
                profile.il: np.linspace(10.0, 120.0, n),
            },
            meta=TekMetadata(source_path="/fake/missing_other.tss"),
        )
        result = _sample_result()
        result.unavailable_metrics.add(("关断过程", "串扰电压"))

        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.result_table.set_result(result)
        win._on_value_clicked("关断过程", "串扰电压")

        self.assertIn("参数不可用", win.statusBar().currentMessage())
        win.close()

    def test_offset_measurement_dialog_adds_selected_metric(self) -> None:
        table = ResultTable()
        events: list[tuple[str, str, str]] = []
        table.set_offset_measurement_add_handler(
            lambda source, metric, range_key: events.append((source, metric, range_key))
        )
        table.set_offset_sources([("CH1", "H-Vge (CH1)"), ("MATH1", "Ic (MATH1)")])
        table.show_offset_measurements(
            [("Ch 1", "Maximum", "V", "全波形", "12.34", "#fff53b")],
            source_count=2,
            row_specs=[("CH1", "maximum", "full")],
        )

        self.assertFalse(table.offset_panel.isHidden())
        self.assertIsNotNone(table.offset_measure_button)
        assert table.offset_measure_button is not None
        table.offset_measure_button.click()
        self.assertIsNotNone(table.offset_dialog)
        assert table.offset_dialog is not None
        self.assertIsNone(table.offset_dialog.findChild(QFrame, "offsetDialogPreview"))
        self.assertFalse(table.offset_dialog.findChildren(QPushButton, "offsetDialogTab"))
        for combo in (table.offset_dialog.source_combo, table.offset_dialog.range_combo):
            palette = combo.view().palette()
            self.assertEqual(palette.color(QPalette.ColorRole.Base).name(), "#f2f4f4")
            self.assertEqual(palette.color(QPalette.ColorRole.Text).name(), "#101014")
        self.assertEqual(table.offset_dialog.source_combo.currentData(), "CH1")
        self.assertEqual(table.offset_dialog.source_combo.itemText(0), "Ch 1")
        self.assertEqual(table.offset_dialog.source_combo.itemText(1), "Math 1")
        self.assertEqual(table.offset_dialog.range_combo.currentData(), "screen")
        max_button = next(
            button
            for button in table.offset_dialog.metric_group.buttons()
            if button.property("metricKey") == "maximum"
        )
        max_button.setChecked(True)
        idx = table.offset_dialog.range_combo.findData("cursor")
        table.offset_dialog.range_combo.setCurrentIndex(idx)
        table.offset_dialog.add_button.click()
        self.assertEqual(events, [("CH1", "maximum", "cursor")])
        self.assertEqual(_row_for(table, "Ch 1", "Maximum"), 0)
        table.table.setCurrentCell(0, 1)
        self.assertEqual(table.current_offset_measurement_spec(), ("CH1", "maximum", "full"))

        table.set_result(_sample_result())
        self.assertTrue(table.offset_panel.isHidden())
        self.assertTrue(table.table.showGrid())
        self.assertEqual(
            table.table.selectionMode(),
            QAbstractItemView.SelectionMode.SingleSelection,
        )
        table.close()

    def test_offset_measurement_delete_actions_use_row_specs(self) -> None:
        table = ResultTable()
        deleted_rows: list[tuple[str, str, str]] = []
        deleted_all: list[bool] = []
        table.set_offset_measurement_delete_handler(
            lambda source, metric, range_key: deleted_rows.append(
                (source, metric, range_key)
            ),
            lambda: deleted_all.append(True),
        )
        table.show_offset_measurements(
            [
                ("Ch 1", "Maximum", "V", "全波形", "14.848", "#fff53b"),
                ("Ch 2", "Maximum", "V", "屏幕", "1109.97", "#20cfd3"),
            ],
            source_count=2,
            row_specs=[
                ("CH1", "maximum", "full"),
                ("CH2", "maximum", "screen"),
            ],
        )

        self.assertTrue(table._request_delete_offset_measurement_row(1))
        self.assertEqual(deleted_rows, [("CH2", "maximum", "screen")])
        self.assertTrue(table._request_delete_all_offset_measurements())
        self.assertEqual(deleted_all, [True])
        table.close()

    def test_offset_measurement_editable_columns_use_combo_boxes(self) -> None:
        table = ResultTable()
        events: list[tuple[int, str, str]] = []
        table.set_offset_sources([("CH1", "H-Vge (CH1)"), ("CH2", "H-Vce (CH2)")])
        table.set_offset_measurement_update_handler(
            lambda row, field, value: events.append((row, field, value))
        )
        table.show_offset_measurements(
            [("Ch 1", "Maximum", "V", "全波形", "14.848", "#fff53b")],
            source_count=2,
            row_specs=[("CH1", "maximum", "full")],
        )

        self.assertFalse(table.table.showGrid())
        self.assertEqual(
            table.table.selectionMode(),
            QAbstractItemView.SelectionMode.NoSelection,
        )
        for col in (0, 1, 3):
            widget = table.table.cellWidget(0, col)
            self.assertIsInstance(widget, QComboBox)
            assert isinstance(widget, QComboBox)
            self.assertFalse(widget.font().bold())
            self.assertIn("border:0", widget.styleSheet())
            self.assertNotIn("#28bce8", widget.styleSheet().lower())
            item = table.table.item(0, col)
            self.assertIsNotNone(item)
            assert item is not None
            self.assertEqual(
                _alignment_value(item.textAlignment()),
                Qt.AlignmentFlag.AlignCenter.value,
            )
            for index in range(widget.count()):
                self.assertEqual(
                    _alignment_value(
                        widget.itemData(
                            index, Qt.ItemDataRole.TextAlignmentRole
                        )
                    ),
                    Qt.AlignmentFlag.AlignCenter.value,
                )
            self.assertEqual(
                widget.view().palette().color(QPalette.ColorRole.Highlight).name(),
                RESULT_OFFSET_POPUP_SELECTED,
            )
        self.assertIsNone(table.table.cellWidget(0, 2))
        unit_item = table.table.item(0, 2)
        self.assertIsNotNone(unit_item)
        assert unit_item is not None
        self.assertEqual(unit_item.text(), "V")
        self.assertEqual(
            _alignment_value(unit_item.textAlignment()),
            Qt.AlignmentFlag.AlignCenter.value,
        )
        self.assertEqual(
            _alignment_value(table.table.item(0, 4).textAlignment()),
            Qt.AlignmentFlag.AlignCenter.value,
        )

        source_combo = table.table.cellWidget(0, 0)
        assert isinstance(source_combo, QComboBox)
        self.assertEqual(source_combo.currentText(), "Ch 1")
        self.assertEqual(
            source_combo.palette().color(QPalette.ColorRole.Highlight).name(),
            "#fff53b",
        )
        source_combo.setCurrentIndex(source_combo.findData("CH2"))
        self.assertEqual(events[-1], (0, "source", "CH2"))
        self.assertEqual(table.table.item(0, 0).text(), "Ch 2")

        metric_combo = table.table.cellWidget(0, 1)
        assert isinstance(metric_combo, QComboBox)
        metric_combo.setCurrentIndex(metric_combo.findData("rms"))
        self.assertEqual(events[-1], (0, "metric", "rms"))
        self.assertEqual(table.table.item(0, 1).text(), "RMS")

        range_combo = table.table.cellWidget(0, 3)
        assert isinstance(range_combo, QComboBox)
        range_combo.setCurrentIndex(range_combo.findData("cursor"))
        self.assertEqual(events[-1], (0, "range", "cursor"))
        self.assertEqual(table.table.item(0, 3).text(), "光标")
        table.close()

    def test_offset_measurement_columns_keep_source_labels_readable(self) -> None:
        table = ResultTable()
        table.show_offset_measurements(
            [
                ("Ch 1", "Maximum", "V", "全波形", "14.848", "#fff53b"),
                ("Ch 2", "Maximum", "V", "全波形", "1109.97", "#20cfd3"),
                ("Math 1", "Maximum", "A", "全波形", "1211.72", "#008000"),
            ],
            source_count=2,
            row_specs=[
                ("CH1", "maximum", "full"),
                ("CH2", "maximum", "full"),
                ("MATH1", "maximum", "full"),
            ],
        )

        self.assertEqual(table.table.item(0, 0).text(), "Ch 1")
        self.assertEqual(table.table.item(1, 0).text(), "Ch 2")
        self.assertEqual(table.table.item(2, 0).text(), "Math 1")
        self.assertEqual(table.table.rowSpan(0, 0), 1)
        self.assertEqual(table.table.rowSpan(1, 0), 1)
        for row in range(table.table.rowCount()):
            item = table.table.item(row, 0)
            self.assertFalse(item.font().bold())
            needed = QFontMetrics(item.font()).horizontalAdvance(item.text()) + 32
            self.assertLessEqual(needed, table.table.columnWidth(0), item.text())
            self.assertEqual(item.foreground().color().name(), RESULT_OFFSET_TEXT)

        widths = [table.table.columnWidth(c) for c in range(table.table.columnCount())]
        self.assertGreaterEqual(widths[0], 84)
        self.assertLessEqual(widths[0], 112)
        self.assertLessEqual(widths[1], 120)
        self.assertLessEqual(widths[2], 64)
        self.assertLessEqual(widths[3], 100)
        self.assertLessEqual(widths[4], 108)

        self.assertEqual(table.table.item(0, 0).background().color().name(), "#fff53b")
        self.assertEqual(table.table.item(1, 0).background().color().name(), "#20cfd3")
        self.assertEqual(table.table.item(1, 1).background().color().name(), RESULT_OFFSET_VALUE_BG)
        table.table.setCurrentCell(1, 1)
        self.assertEqual(table.table.item(0, 1).background().color().name(), RESULT_OFFSET_VALUE_BG)
        self.assertEqual(table.table.item(1, 1).background().color().name(), "#20cfd3")
        for col in range(1, table.table.columnCount()):
            self.assertEqual(table.table.item(1, col).foreground().color().name(), RESULT_OFFSET_TEXT)
        table.close()


if __name__ == "__main__":
    unittest.main()
