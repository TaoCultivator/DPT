from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook, load_workbook

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _write_dpt_template(report: Path) -> None:
    """Minimal double-pulse template: UH/UL groups at 25℃ plus their blocks."""

    from dpt_extractor.export.mcu2506_layout import COL_CURRENT, COL_VOLTAGE

    wb = Workbook()
    ws = wb.active
    ws.title = "U相_双脉冲数据"
    for start, phase in ((5, "UH"), (9, "UL")):
        ws.merge_cells(
            start_row=start,
            start_column=1,
            end_row=start + 3,
            end_column=1,
        )
        ws.merge_cells(
            start_row=start,
            start_column=2,
            end_row=start + 3,
            end_column=2,
        )
        ws.cell(start, 1, phase)
        ws.cell(start, 2, "25℃")
        ws.cell(start, COL_VOLTAGE, 750)
        ws.cell(start, COL_CURRENT, 1048)
    # Second payload row of the UH group: same voltage, other current.
    ws.cell(6, COL_VOLTAGE, 750)
    ws.cell(6, COL_CURRENT, 806)

    wave = wb.create_sheet("U相_双脉冲波形")
    for base, label in ((1, "UH_RT"), (54, "UH_RT"), (107, "UL_RT")):
        wave.merge_cells(
            start_row=base,
            start_column=1,
            end_row=base + 16,
            end_column=8,
        )
        wave.cell(base, 1, label)
        wave.merge_cells(
            start_row=base + 17,
            start_column=1,
            end_row=base + 33,
            end_column=8,
        )
        wave.merge_cells(
            start_row=base + 34,
            start_column=1,
            end_row=base + 50,
            end_column=8,
        )
    wb.save(report)


def _write_short_template(report: Path) -> None:
    """Minimal short-circuit template with one data group and one picture block."""

    wb = Workbook()
    ws = wb.active
    ws.title = "短路测试"
    ws["A5"] = "RT"
    ws["B5"] = "UH"
    pic = wb.create_sheet("短路测试图片")
    pic.merge_cells("A1:E4")
    pic["A1"] = "UH_RT"
    pic["A5"] = "Vce"
    pic["B5"] = "Imax"
    pic.merge_cells("F1:H1")
    pic["F1"] = "短路电流Imax 短路时间Tsc 短路能量Esc_本管"
    pic.merge_cells("F2:H10")
    wb.save(report)


def _dpt_result(
    *,
    current: float,
    eoff: float,
    vdc: float = 750.0,
    filename: str | None = None,
):
    from dpt_extractor.models.results import ExtractResult, TurnOffResult

    name = filename or f"UH_{int(vdc)}V_{int(current)}A_000.tss"
    return ExtractResult(
        source_path=str(Path("samples") / "RT" / name),
        profile_code="UH",
        turn_off=TurnOffResult(eoff=eoff),
    )


def _short_result(*, ic_max: float):
    from dpt_extractor.models.results import ExtractResult, ShortCircuitResult

    return ExtractResult(
        source_path=str(Path("samples") / "RT" / "UH_750V_short.tss"),
        profile_code="UH",
        vdc_set=750.0,
        short_circuit_mode=True,
        short_circuit=ShortCircuitResult(ic_max=ic_max),
    )


class TestReportSheetPrefixDerivation(unittest.TestCase):
    def test_prefix_uses_first_data_folder_below_report_directory(self):
        from dpt_extractor.export.report_template import report_sheet_prefix_for_paths

        self.assertEqual(
            report_sheet_prefix_for_paths(
                r"E:\root\10A2\SMC\RT\UH_459V_425A_000.tss",
                report_path=r"E:\root\report.xlsx",
            ),
            "10A2",
        )

    def test_structure_folders_never_become_a_prefix(self):
        from dpt_extractor.export.report_template import report_sheet_prefix_for_paths

        for structure in ("SMC", "RT", "HT", "tss", "xlsx", "short", "UH"):
            self.assertEqual(
                report_sheet_prefix_for_paths(
                    rf"E:\root\{structure}\UH_459V_425A_000.tss",
                    report_path=r"E:\root\report.xlsx",
                ),
                "",
                structure,
            )

    def test_template_anchor_is_used_when_sample_is_outside_report_tree(self):
        from dpt_extractor.export.report_template import report_sheet_prefix_for_paths

        self.assertEqual(
            report_sheet_prefix_for_paths(
                r"E:\root\10B2\SMC\RT\UH_459V_425A_000.tss",
                report_path=r"E:\reports\project\report.xlsx",
                template_path=r"E:\root\template.xlsx",
            ),
            "10B2",
        )

    def test_illegal_folder_characters_are_sanitized(self):
        from dpt_extractor.export.report_template import report_sheet_prefix_for_paths

        self.assertEqual(
            report_sheet_prefix_for_paths(
                r"E:\root\10A:2\SMC\RT\UH_459V_425A_000.tss",
                report_path=r"E:\root\report.xlsx",
            ),
            "10A_2",
        )

    def test_hidden_folder_and_scope_source_keep_original_titles(self):
        from dpt_extractor.export.report_template import report_sheet_prefix_for_paths

        self.assertEqual(
            report_sheet_prefix_for_paths(
                r"E:\root\.hidden\10A2\SMC\RT\UH_459V_425A_000.tss",
                report_path=r"E:\root\report.xlsx",
            ),
            "",
        )
        self.assertEqual(
            report_sheet_prefix_for_paths(
                "scope://C078514",
                report_path=r"E:\root\report.xlsx",
            ),
            "",
        )

    def test_over_long_prefix_is_truncated_to_a_legal_sheet_title(self):
        from dpt_extractor.export.report_template import _prefixed_sheet_title

        base = "U相_双脉冲数据"
        title = _prefixed_sheet_title("A" * 60, base)
        self.assertLessEqual(len(title), 31)
        self.assertTrue(title.endswith("_" + base))
        self.assertTrue(title.startswith("A"))

        # No room left for any prefix character: keep the base title.
        crowded = _prefixed_sheet_title("B" * 40, "X" * 31)
        self.assertEqual(crowded, "X" * 31)

    def test_reserved_and_empty_prefixes_are_ignored(self):
        from dpt_extractor.export.report_template import (
            _clean_report_sheet_prefix,
            _prefixed_sheet_title,
        )

        self.assertEqual(_clean_report_sheet_prefix("history"), "")
        self.assertEqual(_clean_report_sheet_prefix("  _'10A2' _"), "10A2")
        self.assertEqual(_prefixed_sheet_title("", "短路测试"), "短路测试")

    def test_over_long_prefixes_that_share_their_head_stay_distinct(self):
        from dpt_extractor.export.report_template import _prefixed_sheet_title

        base = "U相_双脉冲数据"
        first = "LCG660FF120I3A2-G1LEP202510090002"
        second = "LCG660FF120I3A2-G1LEP202510090003"
        first_title = _prefixed_sheet_title(first, base)
        second_title = _prefixed_sheet_title(second, base)

        self.assertNotEqual(first_title, second_title)
        for title in (first_title, second_title):
            self.assertLessEqual(len(title), 31)
            self.assertTrue(title.endswith("_" + base))
            self.assertTrue(title.startswith("LCG660FF120I3A"))

    def test_short_prefix_is_used_verbatim_without_a_digest(self):
        from dpt_extractor.export.report_template import _prefixed_sheet_title

        self.assertEqual(
            _prefixed_sheet_title("10A2", "U相_双脉冲数据"),
            "10A2_U相_双脉冲数据",
        )
        self.assertEqual(
            _prefixed_sheet_title("10A2", "短路测试图片"),
            "10A2_短路测试图片",
        )


class TestPrefixedReportSheets(unittest.TestCase):
    def test_long_prefixes_sharing_their_head_write_independent_pages(self):
        from dpt_extractor.export.mcu2506_layout import COL_OFF
        from dpt_extractor.export.report_template import write_report_template

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            _write_dpt_template(report)

            first = write_report_template(
                _dpt_result(current=1048.0, eoff=111.111),
                report,
                phase_code="UH",
                temperature_code="RT",
                sheet_prefix="LCG660FF120I3A2-G1LEP202510090002",
            )
            second = write_report_template(
                _dpt_result(current=1048.0, eoff=222.222),
                report,
                phase_code="UH",
                temperature_code="RT",
                sheet_prefix="LCG660FF120I3A2-G1LEP202510090003",
            )

            self.assertNotEqual(first.data_sheet, second.data_sheet)
            self.assertNotEqual(first.waveform_sheet, second.waveform_sheet)
            for title in (first.data_sheet, second.data_sheet):
                self.assertLessEqual(len(title), 31)
                self.assertTrue(title.endswith("_U相_双脉冲数据"))

            saved = load_workbook(report)
            self.assertIn(first.data_sheet, saved.sheetnames)
            self.assertIn(second.data_sheet, saved.sheetnames)
            # Neither page may be overwritten by the other data folder.
            self.assertEqual(
                saved[first.data_sheet].cell(5, COL_OFF["eoff"]).value,
                111.111,
            )
            self.assertEqual(
                saved[second.data_sheet].cell(5, COL_OFF["eoff"]).value,
                222.222,
            )
            self.assertIsNone(saved["U相_双脉冲数据"].cell(5, COL_OFF["eoff"]).value)

    def test_two_data_folders_write_their_own_dpt_and_waveform_sheets(self):
        from dpt_extractor.export.mcu2506_layout import COL_OFF
        from dpt_extractor.export.report_template import write_report_template

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            _write_dpt_template(report)

            first = write_report_template(
                _dpt_result(current=1048.0, eoff=100.125),
                report,
                phase_code="UH",
                temperature_code="RT",
                sheet_prefix="10A2",
            )
            second = write_report_template(
                _dpt_result(current=1048.0, eoff=200.375),
                report,
                phase_code="UH",
                temperature_code="RT",
                sheet_prefix="10B2",
            )

            saved = load_workbook(report)
            names = saved.sheetnames
            self.assertIn("10A2_U相_双脉冲数据", names)
            self.assertIn("10B2_U相_双脉冲数据", names)
            self.assertIn("10A2_U相_双脉冲波形", names)
            self.assertIn("10B2_U相_双脉冲波形", names)

            self.assertEqual(first.data_sheet, "10A2_U相_双脉冲数据")
            self.assertEqual(second.data_sheet, "10B2_U相_双脉冲数据")
            self.assertEqual(first.waveform_sheet, "10A2_U相_双脉冲波形")
            self.assertEqual(second.waveform_sheet, "10B2_U相_双脉冲波形")

            # Values land in their own prefixed page...
            self.assertEqual(
                saved["10A2_U相_双脉冲数据"].cell(5, COL_OFF["eoff"]).value,
                100.125,
            )
            self.assertEqual(
                saved["10B2_U相_双脉冲数据"].cell(5, COL_OFF["eoff"]).value,
                200.375,
            )
            # ...and the unprefixed base page stays empty.
            self.assertIsNone(saved["U相_双脉冲数据"].cell(5, COL_OFF["eoff"]).value)
            self.assertIsNone(saved["U相_双脉冲数据"].cell(6, COL_OFF["eoff"]).value)

            # The base waveform page is never written either: only a written
            # page carries the condition label of the block.
            self.assertIsNone(saved["U相_双脉冲波形"].cell(18, 1).value)
            self.assertEqual(
                saved["10A2_U相_双脉冲波形"].cell(18, 1).value,
                "750V_1048A",
            )
            self.assertEqual(
                saved["10B2_U相_双脉冲波形"].cell(18, 1).value,
                "750V_1048A",
            )

    def test_same_prefix_reuses_its_sheets_instead_of_duplicating(self):
        from dpt_extractor.export.mcu2506_layout import COL_OFF
        from dpt_extractor.export.report_template import write_report_template

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            _write_dpt_template(report)

            write_report_template(
                _dpt_result(current=1048.0, eoff=100.125),
                report,
                phase_code="UH",
                temperature_code="RT",
                sheet_prefix="10A2",
            )
            write_report_template(
                _dpt_result(current=806.0, eoff=101.5),
                report,
                phase_code="UH",
                temperature_code="RT",
                sheet_prefix="10A2",
            )

            saved = load_workbook(report)
            names = saved.sheetnames
            self.assertEqual(names.count("10A2_U相_双脉冲数据"), 1)
            self.assertEqual(names.count("10A2_U相_双脉冲波形"), 1)
            self.assertEqual(
                len([name for name in names if name.startswith("10A2_")]),
                2,
            )

            sheet = saved["10A2_U相_双脉冲数据"]
            self.assertEqual(sheet.cell(5, COL_OFF["eoff"]).value, 100.125)
            self.assertEqual(sheet.cell(6, COL_OFF["eoff"]).value, 101.5)
            self.assertIsNone(saved["U相_双脉冲数据"].cell(6, COL_OFF["eoff"]).value)

    def test_short_circuit_sheets_are_prefixed_and_base_sheet_stays_empty(self):
        from dpt_extractor.export.report_template import write_report_template

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "short_report.xlsx"
            _write_short_template(report)

            summary = write_report_template(
                _short_result(ic_max=593.0),
                report,
                phase_code="UH",
                temperature_code="RT",
                sheet_prefix="10A2",
            )

            saved = load_workbook(report)
            names = saved.sheetnames
            self.assertEqual(summary.data_sheet, "10A2_短路测试")
            self.assertEqual(summary.waveform_sheet, "10A2_短路测试图片")
            self.assertIn("10A2_短路测试", names)
            self.assertIn("10A2_短路测试图片", names)

            written = saved["10A2_短路测试"]
            self.assertEqual(written.cell(5, 4).value, 750)
            self.assertEqual(written.cell(5, 5).value, 593)
            self.assertEqual(written["A5"].value, "25℃")

            # The base page keeps no measurement: only the workbook-wide
            # temperature-label normalisation may touch its placeholder text.
            base = saved["短路测试"]
            self.assertIsNone(base.cell(5, 4).value)
            self.assertIsNone(base.cell(5, 5).value)
            for column in range(4, 12):
                self.assertIsNone(base.cell(5, column).value, column)

            # Prefixed short picture page is normalised, not left as a placeholder.
            self.assertEqual(saved["10A2_短路测试图片"]["A1"].value, "UH_25℃")

    def test_writer_without_prefix_still_fills_the_base_sheets(self):
        from dpt_extractor.export.mcu2506_layout import COL_OFF
        from dpt_extractor.export.report_template import write_report_template

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            _write_dpt_template(report)

            summary = write_report_template(
                _dpt_result(current=1048.0, eoff=300.5),
                report,
                phase_code="UH",
                temperature_code="RT",
                sheet_prefix=None,
            )

            saved = load_workbook(report)
            self.assertEqual(summary.data_sheet, "U相_双脉冲数据")
            self.assertEqual(summary.waveform_sheet, "U相_双脉冲波形")
            self.assertEqual(
                saved["U相_双脉冲数据"].cell(5, COL_OFF["eoff"]).value,
                300.5,
            )
            self.assertEqual(
                [name for name in saved.sheetnames if "10A2" in name],
                [],
            )

    def test_missing_base_data_sheet_reports_the_base_title(self):
        from dpt_extractor.export.report_template import write_report_template

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "no_data_sheet.xlsx"
            wb = Workbook()
            wb.active.title = "说明"
            wb.save(report)

            with self.assertRaisesRegex(
                ValueError,
                "报告模板缺少工作表：U相_双脉冲数据",
            ):
                write_report_template(
                    _dpt_result(current=1048.0, eoff=100.125),
                    report,
                    phase_code="UH",
                    temperature_code="RT",
                    sheet_prefix="10A2",
                )


class _NoopTempdir:
    def cleanup(self) -> None:
        return None


class _DummySignal:
    def __init__(self) -> None:
        self.slots: list[object] = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def emit(self, *args) -> None:
        for slot in self.slots:
            slot(*args)


class _DummySignals:
    def __init__(self) -> None:
        self.progress = _DummySignal()
        self.finished = _DummySignal()
        self.failed = _DummySignal()


def _recording_write_task(records: list[tuple[tuple, dict]]):
    from PyQt6.QtCore import QRunnable

    class _RecordingWriteTask(QRunnable):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__()
            records.append((args, kwargs))
            self.signals = _DummySignals()

        def run(self) -> None:  # pragma: no cover - never executed in these tests
            return None

    return _RecordingWriteTask


class TestReportWriteTaskPrefixWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _start_task(self, window, sample: Path) -> list[tuple[tuple, dict]]:
        from unittest.mock import patch

        from dpt_extractor.gui import main_window as main_window_module
        from dpt_extractor.models.results import ExtractResult

        records: list[tuple[tuple, dict]] = []
        with patch.object(
            main_window_module,
            "_ReportWriteTask",
            _recording_write_task(records),
        ):
            window._start_report_write_task(
                _NoopTempdir(),  # type: ignore[arg-type]
                {},
                [ExtractResult(source_path=str(sample), profile_code="UH")],
            )
        return records

    def test_write_task_receives_prefix_from_the_data_folder(self):
        from dpt_extractor.gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "report.xlsx"
            sample = root / "10A2" / "SMC" / "RT" / "UH_750V_1048A_000.tss"
            sample.parent.mkdir(parents=True)
            sample.write_bytes(b"")

            window = MainWindow()
            try:
                window._report_output_path = report
                window._report_template_source_path = None
                records = self._start_task(window, sample)
            finally:
                window._finish_report_progress("写入失败", ok=False)
                window._release_report_operation()
                window.close()

        self.assertEqual(len(records), 1)
        _args, kwargs = records[0]
        self.assertEqual(kwargs["sheet_prefix"], "10A2")

    def test_loaded_template_source_is_the_second_anchor(self):
        from dpt_extractor.gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "output" / "report.xlsx"
            template = root / "template.xlsx"
            sample = root / "10B2" / "SMC" / "RT" / "UH_750V_1048A_000.tss"
            sample.parent.mkdir(parents=True)
            sample.write_bytes(b"")

            window = MainWindow()
            try:
                window._report_output_path = report
                window._report_template_source_path = template
                records = self._start_task(window, sample)
            finally:
                window._finish_report_progress("写入失败", ok=False)
                window._release_report_operation()
                window.close()

        self.assertEqual(len(records), 1)
        _args, kwargs = records[0]
        self.assertEqual(kwargs["sheet_prefix"], "10B2")

    def test_no_data_folder_keeps_the_original_sheet_titles(self):
        from dpt_extractor.gui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "report.xlsx"
            sample = root / "RT" / "UH_750V_1048A_000.tss"
            sample.parent.mkdir(parents=True)
            sample.write_bytes(b"")

            window = MainWindow()
            try:
                window._report_output_path = report
                window._report_template_source_path = None
                records = self._start_task(window, sample)
            finally:
                window._finish_report_progress("写入失败", ok=False)
                window._release_report_operation()
                window.close()

        self.assertEqual(len(records), 1)
        _args, kwargs = records[0]
        self.assertEqual(kwargs["sheet_prefix"], "")

    def test_write_task_forwards_the_prefix_to_the_writer(self):
        from unittest.mock import patch

        from dpt_extractor.gui.main_window import _ReportWriteTask
        from dpt_extractor.models.results import ExtractResult

        captured: dict[str, object] = {}

        def fake_write(*_args, **kwargs):
            captured.update(kwargs)
            return object()

        task = _ReportWriteTask(
            7,
            ExtractResult(),
            Path("report.xlsx"),
            {},
            _NoopTempdir(),  # type: ignore[arg-type]
            None,
            {},
            sheet_prefix="10A2",
        )
        with patch(
            "dpt_extractor.gui.main_window.write_report_template",
            side_effect=fake_write,
        ):
            task.run()

        self.assertEqual(captured["sheet_prefix"], "10A2")


if __name__ == "__main__":
    unittest.main()
