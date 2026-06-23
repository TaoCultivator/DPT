from __future__ import annotations

import base64
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from openpyxl import Workbook, load_workbook


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB"
    "/6X7W1sAAAAASUVORK5CYII="
)


def _write_tiny_png(path: Path) -> None:
    path.write_bytes(_PNG_1X1)


def _write_rgb_png(path: Path, size: tuple[int, int]) -> None:
    from PIL import Image

    Image.new("RGB", size, (16, 24, 32)).save(path)


def _drawing_anchor_counts(path: Path) -> dict[str, int]:
    tags = {
        "oneCellAnchor": "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}oneCellAnchor",
        "twoCellAnchor": "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}twoCellAnchor",
    }
    counts = {key: 0 for key in tags}
    with ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.startswith("xl/drawings/drawing") or not name.endswith(".xml"):
                continue
            root = ET.fromstring(zf.read(name))
            for key, tag in tags.items():
                counts[key] += len(root.findall(f".//{tag}"))
    return counts


class TestReportTemplateWriter(unittest.TestCase):
    def test_inserted_waveform_image_keeps_original_aspect_ratio(self):
        from openpyxl.worksheet.cell_range import CellRange

        from dpt_extractor.export.report_template import _insert_image

        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "scope_16x9.png"
            _write_rgb_png(image, (160, 90))

            wb = Workbook()
            ws = wb.active
            ws.merge_cells("J2:Q17")
            _insert_image(ws, image, CellRange("J2:Q17"))

            inserted = ws._images[0]
            self.assertAlmostEqual(inserted.width / inserted.height, 160 / 90, delta=0.02)

    def test_dpt_template_writes_next_empty_row_and_fills_waveform_labels(self):
        from dpt_extractor.export.mcu2506_layout import COL_OFF
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, TurnOffResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "report.xlsx"
            image = td_path / "scope.png"
            _write_tiny_png(image)

            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            for base, condition in ((1, "750V_1050A"), (54, "750V_805A")):
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.cell(base, 1, "UH_RT")
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.cell(base + 17, 1, condition)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.cell(base + 34, 1, "总概览图")
                wave.merge_cells(start_row=base, start_column=10, end_row=base, end_column=17)
                wave.cell(base, 10, "△Vce（V）")
                wave.merge_cells(start_row=base + 1, start_column=10, end_row=base + 16, end_column=17)
                wave.cell(base + 1, 10, 1)
            wb.save(report)

            result = ExtractResult(
                source_path=str(Path("samples") / "RT" / "UH_750V_805A_000.tss"),
                profile_code="UH",
                turn_off=TurnOffResult(delta_vce=123.456),
            )
            summary = write_report_template(
                result,
                report,
                images={("关断过程", "ΔVce"): image},
            )

            saved = load_workbook(report)
            saved_wave = saved["U相_双脉冲波形"]
            self.assertEqual(summary.data_sheet, "U相_双脉冲数据")
            self.assertEqual(summary.data_row, 5)
            self.assertEqual(summary.waveform_anchor_row, 1)
            self.assertEqual(saved["U相_双脉冲数据"].cell(5, COL_OFF["delta_vce"]).value, 123.456)
            self.assertEqual(saved_wave.cell(1, 1).value, "UH_25℃")
            self.assertEqual(saved_wave.cell(18, 1).value, "750V_805A")
            self.assertEqual(saved_wave.cell(35, 1).value, "总概览图")
            self.assertLess(saved_wave.column_dimensions["J"].width, 13)
            self.assertEqual(len(saved_wave._images), 1)

    def test_dpt_template_uses_current_temperature_label(self):
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "RT"
            wave = wb.create_sheet("U相_双脉冲波形")
            wave.merge_cells(start_row=1, start_column=1, end_row=17, end_column=8)
            wave.cell(1, 1, "UH_RT")
            wave.merge_cells(start_row=18, start_column=1, end_row=34, end_column=8)
            wave.cell(18, 1, "750V_1050A")
            wave.merge_cells(start_row=35, start_column=1, end_row=51, end_column=8)
            wave.cell(35, 1, "总概览图")
            wb.save(report)

            write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_1050A_000.tss"),
                    profile_code="UH",
                ),
                report,
                temperature_labels={"RT": "26.5℃", "HT": "175℃", "LT": "-55℃"},
            )

            saved = load_workbook(report)
            self.assertEqual(saved["U相_双脉冲数据"].cell(5, 2).value, "26.5℃")
            self.assertEqual(saved["U相_双脉冲波形"].cell(1, 1).value, "UH_26.5℃")

    def test_dpt_write_normalizes_short_picture_temperature_labels(self):
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            wave.merge_cells(start_row=1, start_column=1, end_row=17, end_column=8)
            wave.cell(1, 1, "UH_RT")
            wave.merge_cells(start_row=18, start_column=1, end_row=34, end_column=8)
            wave.cell(18, 1, "750V_1050A")
            wave.merge_cells(start_row=35, start_column=1, end_row=51, end_column=8)
            wave.cell(35, 1, "总概览图")
            short_pic = wb.create_sheet("短路测试图片")
            short_pic.merge_cells("A2:E5")
            short_pic["A2"] = "UH_RT"
            short_pic.merge_cells("A23:E26")
            short_pic["A23"] = "UH_HT"
            short_pic.merge_cells("A44:E47")
            short_pic["A44"] = "UH_LT"
            wb.save(report)

            write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_1050A_000.tss"),
                    profile_code="UH",
                ),
                report,
            )

            saved_short = load_workbook(report)["短路测试图片"]
            self.assertEqual(saved_short["A2"].value, "UH_25℃")
            self.assertEqual(saved_short["A23"].value, "UH_150℃")
            self.assertEqual(saved_short["A44"].value, "UH_-40℃")

    def test_dpt_template_leaves_unavailable_metric_cells_blank(self):
        from dpt_extractor.export.mcu2506_layout import (
            COL_CURRENT,
            COL_OFF,
            COL_ON,
            COL_RR,
            COL_TAIL,
            COL_VOLTAGE,
        )
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import (
            ExtractResult,
            ReverseRecoveryResult,
            TurnOffResult,
            TurnOnResult,
        )

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            ws.cell(5, COL_VOLTAGE, 750)
            ws.cell(5, COL_CURRENT, 1050)
            ws.cell(5, COL_OFF["crosstalk"], "stale")
            ws.cell(5, COL_RR["err"], 999)
            ws.cell(5, COL_TAIL["etotal"], 999)
            wb.save(report)

            write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_1050A_000.tss"),
                    profile_code="UH",
                    turn_off=TurnOffResult(
                        crosstalk_vmax=12.3,
                        crosstalk_vmin=-4.5,
                        eoff=10.0,
                    ),
                    turn_on=TurnOnResult(eon=20.0),
                    reverse_recovery=ReverseRecoveryResult(err=30.0),
                    unavailable_metrics={
                        ("关断过程", "串扰电压"),
                        ("反向恢复", "Err"),
                    },
                ),
                report,
            )

            saved = load_workbook(report)["U相_双脉冲数据"]
            self.assertIsNone(saved.cell(5, COL_OFF["crosstalk"]).value)
            self.assertIsNone(saved.cell(5, COL_RR["err"]).value)
            self.assertIsNone(saved.cell(5, COL_TAIL["etotal"]).value)
            self.assertEqual(saved.cell(5, COL_OFF["eoff"]).value, 10)
            self.assertEqual(saved.cell(5, COL_ON["eon"]).value, 20)

    def test_excel_layout_leaves_unavailable_metric_cells_blank(self):
        from dpt_extractor.export.mcu2506_layout import (
            COL_OFF,
            COL_ON,
            COL_RR,
            COL_TAIL,
            DATA_ROW,
            build_mcu2506_workbook,
            fill_data_row,
        )
        from dpt_extractor.models.results import (
            ExtractResult,
            ReverseRecoveryResult,
            TurnOffResult,
            TurnOnResult,
        )

        result = ExtractResult(
            source_path=str(Path("samples") / "RT" / "UH_750V_1050A_000.tss"),
            profile_code="UH",
            turn_off=TurnOffResult(eoff=10.0),
            turn_on=TurnOnResult(eon=20.0),
            reverse_recovery=ReverseRecoveryResult(vrr=900.0, err=30.0),
            unavailable_metrics={
                ("开通", "Eon"),
                ("反向恢复", "Vrr"),
            },
        )
        wb = build_mcu2506_workbook(result)
        ws = wb.active
        ws.cell(DATA_ROW, COL_ON["eon"], 999)
        ws.cell(DATA_ROW, COL_RR["vrr"], 999)
        ws.cell(DATA_ROW, COL_TAIL["etotal"], 999)

        fill_data_row(ws, DATA_ROW, result)

        self.assertEqual(ws.cell(DATA_ROW, COL_OFF["eoff"]).value, 10)
        self.assertIsNone(ws.cell(DATA_ROW, COL_ON["eon"]).value)
        self.assertIsNone(ws.cell(DATA_ROW, COL_RR["vrr"]).value)
        self.assertEqual(ws.cell(DATA_ROW, COL_RR["err"]).value, 30)
        self.assertIsNone(ws.cell(DATA_ROW, COL_TAIL["etotal"]).value)

    def test_short_template_leaves_unavailable_metric_cells_blank(self):
        from dpt_extractor.export.short_circuit_layout import COL_ESC_OTHER, COL_VPEAK_OTHER
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, ShortCircuitResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "short_report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "短路测试"
            ws.merge_cells("A5:A6")
            ws["A5"] = 25
            ws["B5"] = "UH"
            ws["B6"] = "UL"
            ws.cell(5, COL_ESC_OTHER, 999)
            ws.cell(5, COL_VPEAK_OTHER, 999)
            wb.save(report)

            write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_000.tss"),
                    profile_code="UH",
                    short_circuit_mode=True,
                    short_circuit=ShortCircuitResult(
                        esc_other=12.3456,
                        vpeak_other=789.123,
                    ),
                    unavailable_metrics={("短路过程", "短路能量Esc_对管")},
                ),
                report,
            )

            saved = load_workbook(report)["短路测试"]
            self.assertIsNone(saved.cell(5, COL_ESC_OTHER).value)
            self.assertEqual(saved.cell(5, COL_VPEAK_OTHER).value, 789.123)

    def test_short_layout_leaves_unavailable_metric_cells_blank(self):
        from dpt_extractor.export.short_circuit_layout import (
            COL_ESC_OTHER,
            COL_VPEAK_OTHER,
            DATA_START_ROW,
            build_short_circuit_workbook,
            fill_short_circuit_row,
        )
        from dpt_extractor.models.results import ExtractResult, ShortCircuitResult

        result = ExtractResult(
            source_path=str(Path("samples") / "RT" / "UH_750V_000.tss"),
            profile_code="UH",
            short_circuit_mode=True,
            short_circuit=ShortCircuitResult(
                esc_other=12.3456,
                vpeak_other=789.123,
            ),
            unavailable_metrics={("短路过程", "短路能量Esc_对管")},
        )
        wb = build_short_circuit_workbook(result)
        ws = wb.active
        ws.cell(DATA_START_ROW, COL_ESC_OTHER, 999)
        ws.cell(DATA_START_ROW, COL_VPEAK_OTHER, 999)

        fill_short_circuit_row(ws, DATA_START_ROW, result)

        self.assertIsNone(ws.cell(DATA_START_ROW, COL_ESC_OTHER).value)
        self.assertEqual(ws.cell(DATA_START_ROW, COL_VPEAK_OTHER).value, 789.123)

    def test_dpt_template_rewrites_same_condition_in_first_waveform_block(self):
        from dpt_extractor.export.mcu2506_layout import COL_CURRENT, COL_OFF, COL_VOLTAGE
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, TurnOffResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            ws.cell(5, COL_VOLTAGE, 750)
            ws.cell(5, COL_CURRENT, 1048)
            ws.cell(6, COL_VOLTAGE, 750)
            ws.cell(6, COL_CURRENT, 806)
            wave = wb.create_sheet("U相_双脉冲波形")
            for idx in range(2):
                base = 1 + idx * 53
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.merge_cells(start_row=base, start_column=10, end_row=base, end_column=17)
                wave.cell(base, 10, "△Vce（V）")
                wave.merge_cells(start_row=base + 1, start_column=10, end_row=base + 16, end_column=17)
            wb.save(report)

            summary = write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_1048A_000.tss"),
                    profile_code="UH",
                    turn_off=TurnOffResult(delta_vce=1048.0),
                ),
                report,
            )

            saved = load_workbook(report)
            self.assertEqual(summary.data_row, 5)
            self.assertEqual(summary.waveform_anchor_row, 1)
            self.assertEqual(saved["U相_双脉冲数据"].cell(5, COL_OFF["delta_vce"]).value, 1048)
            self.assertEqual(saved["U相_双脉冲波形"].cell(1, 1).value, "UH_25℃")
            self.assertEqual(saved["U相_双脉冲波形"].cell(18, 1).value, "750V_1048A")

    def test_dpt_template_clears_stale_duplicate_waveform_block(self):
        from openpyxl.drawing.image import Image as XLImage

        from dpt_extractor.export.mcu2506_layout import COL_CURRENT, COL_VOLTAGE
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "report.xlsx"
            image = td_path / "scope_4x3.png"
            _write_rgb_png(image, (1280, 960))

            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A7")
            ws.merge_cells("B5:B7")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            ws.cell(5, COL_VOLTAGE, 750)
            ws.cell(5, COL_CURRENT, 1048)
            ws.cell(6, COL_VOLTAGE, 750)
            ws.cell(6, COL_CURRENT, 806)
            wave = wb.create_sheet("U相_双脉冲波形")
            for base, condition in (
                (1, "750V_1048A"),
                (54, "750V_806A"),
                (107, "750V_806A"),
            ):
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.cell(base, 1, "UH_RT")
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.cell(base + 17, 1, condition)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.cell(base + 34, 1, "总概览图")
                wave.merge_cells(start_row=base, start_column=9, end_row=base + 16, end_column=9)
                wave.cell(base, 9, "关断")
                wave.merge_cells(start_row=base, start_column=10, end_row=base, end_column=17)
                wave.cell(base, 10, "△Vce（V）")
                wave.merge_cells(start_row=base + 1, start_column=10, end_row=base + 16, end_column=17)
            stale_image = XLImage(str(image))
            stale_image.anchor = "J108"
            wave.add_image(stale_image)
            wb.save(report)

            summary = write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_806A_000.tss"),
                    profile_code="UH",
                ),
                report,
                images={("关断过程", "ΔVce"): image},
            )

            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            self.assertEqual(summary.data_row, 6)
            self.assertEqual(summary.waveform_anchor_row, 54)
            self.assertEqual(saved_wave.cell(54, 1).value, "UH_25℃")
            self.assertEqual(saved_wave.cell(71, 1).value, "750V_806A")
            self.assertIsNone(saved_wave.cell(107, 1).value)
            self.assertIsNone(saved_wave.cell(124, 1).value)
            self.assertIsNone(saved_wave.cell(141, 1).value)
            self.assertEqual(saved_wave.cell(107, 9).value, "关断")
            self.assertEqual(saved_wave.cell(107, 10).value, "△Vce（V）")
            self.assertEqual(len(saved_wave._images), 1)
            image_rows = [
                img.anchor._from.row + 1
                for img in saved_wave._images
                if hasattr(img.anchor, "_from")
            ]
            self.assertEqual(image_rows, [55])

    def test_dpt_condition_rows_survive_narrow_left_blocks_and_overview_images(self):
        from dpt_extractor.export.mcu2506_layout import COL_OFF
        from dpt_extractor.export.report_template import (
            DPT_OVERVIEW_IMAGE_PARAM,
            write_report_template,
        )
        from dpt_extractor.models.results import ExtractResult, TurnOffResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "report.xlsx"
            image = td_path / "scope.png"
            _write_tiny_png(image)

            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            for base, condition in ((1, "750V_1050A"), (54, "750V_805A")):
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=7)
                wave.cell(base, 1, "UH_RT")
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=7)
                wave.cell(base + 17, 1, condition)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=7)
                wave.cell(base + 34, 1, "总概览图")
                wave.merge_cells(start_row=base, start_column=9, end_row=base, end_column=16)
                wave.cell(base, 9, "△Vce（V）")
                wave.merge_cells(start_row=base + 1, start_column=9, end_row=base + 16, end_column=16)
            wb.save(report)

            write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_1050A_000.tss"),
                    profile_code="UH",
                    turn_off=TurnOffResult(delta_vce=1050.0),
                ),
                report,
                images={
                    DPT_OVERVIEW_IMAGE_PARAM: image,
                    ("关断过程", "ΔVce"): image,
                },
            )
            write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_805A_000.tss"),
                    profile_code="UH",
                    turn_off=TurnOffResult(delta_vce=805.0),
                ),
                report,
                images={
                    DPT_OVERVIEW_IMAGE_PARAM: image,
                    ("关断过程", "ΔVce"): image,
                },
            )

            saved = load_workbook(report)
            saved_data = saved["U相_双脉冲数据"]
            saved_wave = saved["U相_双脉冲波形"]
            self.assertEqual(saved_data.cell(5, COL_OFF["delta_vce"]).value, 1050)
            self.assertEqual(saved_data.cell(6, COL_OFF["delta_vce"]).value, 805)
            self.assertEqual(saved_data.cell(5, 5).value, 1050)
            self.assertEqual(saved_data.cell(6, 5).value, 805)
            self.assertIsNone(saved_wave.cell(35, 1).value)
            self.assertIsNone(saved_wave.cell(88, 1).value)

    def test_dpt_unmatched_condition_uses_empty_data_row_without_overwriting_reserved_row(self):
        from dpt_extractor.export.mcu2506_layout import COL_CURRENT, COL_OFF, COL_VOLTAGE
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, TurnOffResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A7")
            ws.merge_cells("B5:B7")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            for base, condition in ((1, "750V_1050A"), (54, "750V_805A")):
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.cell(base, 1, "UH_RT")
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.cell(base + 17, 1, condition)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.cell(base + 34, 1, "总概览图")
            wb.save(report)

            rows = []
            for filename, marker in (
                ("UH_750V_1048A_000.tss", 1048.0),
                ("UH_750V_806A_000.tss", 806.0),
                ("UH_600V_403A_000.tss", 403.0),
            ):
                summary = write_report_template(
                    ExtractResult(
                        source_path=str(Path("samples") / "RT" / filename),
                        profile_code="UH",
                        turn_off=TurnOffResult(delta_vce=marker),
                    ),
                    report,
                )
                rows.append(summary.data_row)

            saved = load_workbook(report)["U相_双脉冲数据"]
            self.assertEqual(rows, [5, 6, 7])
            self.assertEqual(saved.cell(5, COL_VOLTAGE).value, 750)
            self.assertEqual(saved.cell(5, COL_CURRENT).value, 1048)
            self.assertEqual(saved.cell(5, COL_OFF["delta_vce"]).value, 1048)
            self.assertEqual(saved.cell(6, COL_CURRENT).value, 806)
            self.assertEqual(saved.cell(6, COL_OFF["delta_vce"]).value, 806)
            self.assertEqual(saved.cell(7, COL_VOLTAGE).value, 600)
            self.assertEqual(saved.cell(7, COL_CURRENT).value, 403)
            self.assertEqual(saved.cell(7, COL_OFF["delta_vce"]).value, 403)

    def test_dpt_waveform_blocks_do_not_keep_blank_reserved_rows_between_groups(self):
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, TurnOffResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            ws.merge_cells("A9:A12")
            ws.merge_cells("B9:B12")
            ws["A9"] = "UL"
            ws["B9"] = "25℃"

            wave = wb.create_sheet("U相_双脉冲波形")
            blocks = (
                ("UH_RT", "750V_1050A"),
                ("UH_RT", "750V_805A"),
                ("UH_RT", "750V_50A"),
                ("UH_RT", "600V_285A"),
                ("UL_RT", "750V_1050A"),
                ("UL_RT", "750V_805A"),
            )
            for idx, (phase_temp, condition) in enumerate(blocks):
                base = 1 + idx * 53
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.cell(base, 1, phase_temp)
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.cell(base + 17, 1, condition)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.cell(base + 34, 1, "总概览图")
            wb.save(report)

            anchors = []
            for phase, filename, marker in (
                ("UH", "UH_750V_1048A_000.tss", 1048.0),
                ("UH", "UH_750V_806A_000.tss", 806.0),
                ("UH", "UH_600V_403A_000.tss", 403.0),
                ("UL", "UL_750V_1048A_000.tss", 1048.0),
                ("UL", "UL_750V_806A_000.tss", 806.0),
            ):
                summary = write_report_template(
                    ExtractResult(
                        source_path=str(Path("samples") / "RT" / filename),
                        profile_code=phase,
                        turn_off=TurnOffResult(delta_vce=marker),
                    ),
                    report,
                )
                anchors.append(summary.waveform_anchor_row)

            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            self.assertEqual(anchors, [1, 54, 107, 160, 213])
            self.assertEqual(saved_wave.cell(107, 1).value, "UH_25℃")
            self.assertEqual(saved_wave.cell(124, 1).value, "600V_403A")
            self.assertEqual(saved_wave.cell(160, 1).value, "UL_25℃")
            self.assertEqual(saved_wave.cell(177, 1).value, "750V_1048A")
            self.assertEqual(saved_wave.cell(194, 1).value, "总概览图")
            self.assertEqual(saved_wave.cell(213, 1).value, "UL_25℃")
            self.assertEqual(saved_wave.cell(230, 1).value, "750V_806A")
            self.assertIsNone(saved_wave.cell(266, 1).value)
            self.assertIsNone(saved_wave.cell(283, 1).value)
            self.assertIsNone(saved_wave.cell(300, 1).value)

    def test_dpt_template_inserts_extra_condition_row_with_matching_style(self):
        from openpyxl.styles import Alignment, Border, PatternFill, Side

        from dpt_extractor.export.mcu2506_layout import COL_CURRENT, COL_OFF, COL_VOLTAGE
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, TurnOffResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws.merge_cells("C5:C8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            ws["C5"] = "Rg_on = 3.233 ohm"
            ws.merge_cells("A9:A12")
            ws.merge_cells("B9:B12")
            ws.merge_cells("C9:C12")
            ws["A9"] = "UL"
            ws["B9"] = "25℃"
            ws["C9"] = "Rg_on = 3.233 ohm"

            fill = PatternFill("solid", fgColor="D9EAD3")
            border = Border(
                left=Side(style="thin", color="808080"),
                right=Side(style="thin", color="808080"),
                top=Side(style="thin", color="808080"),
                bottom=Side(style="thin", color="808080"),
            )
            alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for row in range(5, 13):
                ws.row_dimensions[row].height = 22
                for col in range(1, 38):
                    cell = ws.cell(row, col)
                    cell.fill = fill
                    cell.border = border
                    cell.alignment = alignment
                    cell.number_format = "0.000"
            for row in range(5, 9):
                ws.cell(row, COL_VOLTAGE, 750)
                ws.cell(row, COL_CURRENT, 1000 - (row - 5) * 200)

            wave = wb.create_sheet("U相_双脉冲波形")
            conditions = ("750V_1000A", "750V_800A", "750V_600A", "750V_400A")
            for idx, condition in enumerate(conditions):
                base = 1 + idx * 53
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.cell(base, 1, "UH_RT")
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.cell(base + 17, 1, condition)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.cell(base + 34, 1, "总概览图")
            base = 1 + len(conditions) * 53
            wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
            wave.cell(base, 1, "UL_RT")
            wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
            wave.cell(base + 17, 1, "750V_1000A")
            wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
            wave.cell(base + 34, 1, "总概览图")
            wb.save(report)

            summary = write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_200A_000.tss"),
                    profile_code="UH",
                    turn_off=TurnOffResult(delta_vce=200.0),
                ),
                report,
            )

            saved = load_workbook(report)["U相_双脉冲数据"]
            merges = {str(rng) for rng in saved.merged_cells.ranges}
            self.assertEqual(summary.data_row, 9)
            self.assertEqual(summary.waveform_anchor_row, 213)
            self.assertIn("A5:A9", merges)
            self.assertIn("B5:B9", merges)
            self.assertIn("C5:C9", merges)
            self.assertIn("A10:A13", merges)
            self.assertEqual(saved.cell(10, 1).value, "UL")
            self.assertEqual(saved.cell(9, COL_VOLTAGE).value, 750)
            self.assertEqual(saved.cell(9, COL_CURRENT).value, 200)
            self.assertEqual(saved.cell(9, COL_OFF["delta_vce"]).value, 200)
            self.assertEqual(saved.row_dimensions[9].height, saved.row_dimensions[8].height)
            self.assertEqual(
                saved.cell(9, COL_OFF["delta_vce"]).fill.fgColor.rgb,
                saved.cell(8, COL_OFF["delta_vce"]).fill.fgColor.rgb,
            )
            self.assertEqual(
                saved.cell(9, COL_OFF["delta_vce"]).border.left.style,
                saved.cell(8, COL_OFF["delta_vce"]).border.left.style,
            )
            self.assertEqual(
                saved.cell(9, COL_OFF["delta_vce"]).alignment.horizontal,
                saved.cell(8, COL_OFF["delta_vce"]).alignment.horizontal,
            )
            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            self.assertEqual(saved_wave.cell(213, 1).value, "UH_25℃")
            self.assertEqual(saved_wave.cell(230, 1).value, "750V_200A")
            self.assertEqual(saved_wave.cell(266, 1).value, "UL_25℃")

    def test_dpt_template_appends_waveform_block_with_two_separator_rows(self):
        from dpt_extractor.export.mcu2506_layout import COL_CURRENT, COL_VOLTAGE
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            for row, current in zip(range(5, 9), (1000, 800, 600, 400)):
                ws.cell(row, COL_VOLTAGE, 750)
                ws.cell(row, COL_CURRENT, current)

            wave = wb.create_sheet("U相_双脉冲波形")
            for idx, current in enumerate((1000, 800, 600, 400)):
                base = 1 + idx * 53
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.cell(base, 1, "UH_RT")
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.cell(base + 17, 1, f"750V_{current}A")
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.cell(base + 34, 1, "总概览图")
            wave.row_dimensions[158].height = 6
            wave.row_dimensions[159].height = 6
            wb.save(report)

            summary = write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_200A_000.tss"),
                    profile_code="UH",
                ),
                report,
            )

            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            self.assertEqual(summary.waveform_anchor_row, 213)
            self.assertEqual(saved_wave.cell(213, 1).value, "UH_25℃")
            self.assertEqual(saved_wave.cell(230, 1).value, "750V_200A")
            self.assertEqual(saved_wave.cell(247, 1).value, "总概览图")
            self.assertIsNone(saved_wave.cell(211, 1).value)
            self.assertIsNone(saved_wave.cell(212, 1).value)

    def test_dpt_parameter_images_share_one_display_size_per_condition(self):
        from dpt_extractor.export.report_template import (
            REPORT_IMAGE_DISPLAY_SIZE_PX,
            write_report_template,
        )
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "report.xlsx"
            image = td_path / "scope_4x3.png"
            _write_rgb_png(image, (1280, 960))

            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            wave.merge_cells(start_row=1, start_column=1, end_row=17, end_column=8)
            wave.cell(1, 1, "UH_RT")
            wave.merge_cells(start_row=18, start_column=1, end_row=34, end_column=8)
            wave.cell(18, 1, "750V_1050A")
            wave.merge_cells(start_row=35, start_column=1, end_row=51, end_column=8)
            wave.cell(35, 1, "总概览图")
            wave.merge_cells(start_row=1, start_column=10, end_row=1, end_column=13)
            wave.cell(1, 10, "△Vce（V）")
            wave.merge_cells(start_row=2, start_column=10, end_row=17, end_column=13)
            wave.merge_cells(start_row=1, start_column=18, end_row=1, end_column=28)
            wave.cell(1, 18, "dv/dt(V/ns)")
            wave.merge_cells(start_row=2, start_column=18, end_row=17, end_column=28)
            wb.save(report)

            result = ExtractResult(
                source_path=str(Path("samples") / "RT" / "UH_750V_1050A_000.tss"),
                profile_code="UH",
            )
            write_report_template(
                result,
                report,
                images={
                    ("关断过程", "ΔVce"): image,
                    ("关断过程", "dv/dt"): image,
                },
            )

            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            self.assertEqual(len(saved_wave._images), 2)
            anchors = _drawing_anchor_counts(report)
            self.assertEqual(anchors["twoCellAnchor"], 2)
            self.assertEqual(anchors["oneCellAnchor"], 0)

    def test_dpt_parameter_images_share_one_display_size_across_conditions(self):
        from dpt_extractor.export.report_template import (
            REPORT_IMAGE_DISPLAY_SIZE_PX,
            write_report_template,
        )
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "report.xlsx"
            image = td_path / "scope_4x3.png"
            _write_rgb_png(image, (1280, 960))

            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            for base, condition, row_height in (
                (1, "750V_1050A", 20.0),
                (54, "750V_805A", 10.0),
            ):
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.cell(base, 1, "UH_RT")
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.cell(base + 17, 1, condition)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.cell(base + 34, 1, "总概览图")
                wave.merge_cells(start_row=base, start_column=10, end_row=base, end_column=17)
                wave.cell(base, 10, "△Vce（V）")
                wave.merge_cells(start_row=base + 1, start_column=10, end_row=base + 16, end_column=17)
                for row in range(base + 1, base + 17):
                    wave.row_dimensions[row].height = row_height
            wb.save(report)

            for current in ("UH_750V_1050A_000.tss", "UH_750V_805A_000.tss"):
                write_report_template(
                    ExtractResult(
                        source_path=str(Path("samples") / "RT" / current),
                        profile_code="UH",
                    ),
                    report,
                    images={("关断过程", "ΔVce"): image},
                )

            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            self.assertEqual(len(saved_wave._images), 2)
            anchors = _drawing_anchor_counts(report)
            self.assertEqual(anchors["twoCellAnchor"], 2)
            self.assertEqual(anchors["oneCellAnchor"], 0)

    def test_dpt_waveform_text_layout_and_open_zoom_are_normalized(self):
        from openpyxl.styles import Font

        from dpt_extractor.export.report_template import (
            _REPORT_VIEW_HORIZONTAL_MARGIN_PX,
            _REPORT_VIEW_MAX_ZOOM,
            _REPORT_VIEW_MIN_ZOOM,
            _WAVEFORM_HEADER_FONT_SIZE,
            _WAVEFORM_HEADER_ROW_HEIGHT_PX,
            _WAVEFORM_LEFT_LABEL_FONT_SIZE,
            _WAVEFORM_STATE_FONT_SIZE,
            _row_height_px,
            _used_columns_width_px,
            write_report_template,
        )
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "report.xlsx"

            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            ws.cell(5, 4, 750)
            ws.cell(5, 5, 1050)
            ws.cell(6, 4, 750)
            ws.cell(6, 5, 805)
            wave = wb.create_sheet("U相_双脉冲波形")
            headers = ("△Vce（V）", "dv/dt(V/ns)", "di/dt(A/ns)", "Tf(ns)", "Td_off(ns)", "Eoff(mJ)")
            for base, condition, header_height in (
                (1, "750V_1050A", 6.0),
                (54, "750V_805A", 42.0),
            ):
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.cell(base, 1, "UH_RT")
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.cell(base + 17, 1, condition)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.cell(base + 34, 1, "总概览图")
                for offset, label in ((0, "关断"), (17, "开通"), (34, "反向恢复")):
                    wave.merge_cells(
                        start_row=base + offset,
                        start_column=9,
                        end_row=base + offset + 16,
                        end_column=9,
                    )
                    wave.cell(base + offset, 9, label)
                for idx, header_text in enumerate(headers):
                    col = 10 + idx * 8
                    wave.merge_cells(
                        start_row=base,
                        start_column=col,
                        end_row=base,
                        end_column=col + 7,
                    )
                    cell = wave.cell(base, col, header_text)
                    cell.font = Font(size=22)
                    wave.row_dimensions[base].height = header_height
                    wave.merge_cells(
                        start_row=base + 1,
                        start_column=col,
                        end_row=base + 16,
                        end_column=col + 7,
                    )
            wb.save(report)

            write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_805A_000.tss"),
                    profile_code="UH",
                ),
                report,
                target_screen_width_px=1600,
            )

            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            for row in (1, 18, 35, 54, 71, 88):
                self.assertEqual(_row_height_px(saved_wave, row), _WAVEFORM_HEADER_ROW_HEIGHT_PX)
            self.assertEqual(saved_wave.cell(1, 10).font.sz, _WAVEFORM_HEADER_FONT_SIZE)
            self.assertTrue(saved_wave.cell(1, 10).alignment.shrink_to_fit)
            self.assertEqual(saved_wave.cell(71, 1).font.sz, _WAVEFORM_LEFT_LABEL_FONT_SIZE)
            self.assertTrue(saved_wave.cell(71, 1).alignment.shrink_to_fit)
            self.assertEqual(saved_wave.cell(88, 9).font.sz, _WAVEFORM_STATE_FONT_SIZE)

            usable_width = max(960, 1600 - _REPORT_VIEW_HORIZONTAL_MARGIN_PX)
            expected_zoom = int(usable_width * 100 / max(1, _used_columns_width_px(saved_wave)))
            expected_zoom = max(
                _REPORT_VIEW_MIN_ZOOM,
                min(_REPORT_VIEW_MAX_ZOOM, expected_zoom),
            )
            self.assertEqual(saved_wave.sheet_view.zoomScale, expected_zoom)

    def test_dpt_irr_header_does_not_match_didt_irr_slot(self):
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "report.xlsx"
            image = td_path / "scope_4x3.png"
            _write_rgb_png(image, (1280, 960))

            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            wave.merge_cells(start_row=1, start_column=1, end_row=17, end_column=8)
            wave.cell(1, 1, "UH_RT")
            wave.merge_cells(start_row=18, start_column=1, end_row=34, end_column=8)
            wave.cell(18, 1, "750V_805A")
            wave.merge_cells(start_row=35, start_column=1, end_row=51, end_column=8)
            wave.cell(35, 1, "总概览图")
            wave.merge_cells(start_row=35, start_column=10, end_row=35, end_column=17)
            wave.cell(35, 10, "Didt_Irr90-10")
            wave.merge_cells(start_row=36, start_column=10, end_row=51, end_column=17)
            wave.merge_cells(start_row=35, start_column=18, end_row=35, end_column=25)
            wave.cell(35, 18, "Irr")
            wave.merge_cells(start_row=36, start_column=18, end_row=51, end_column=25)
            wave.cell(36, 18, 12)
            wb.save(report)

            write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_805A_000.tss"),
                    profile_code="UH",
                ),
                report,
                images={
                    ("反向恢复", "Irr"): image,
                    ("反向恢复", "di/dt"): image,
                },
            )

            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            self.assertEqual(len(saved_wave._images), 2)
            self.assertIsNone(saved_wave.cell(36, 18).value)

    def test_dpt_full_image_set_writes_every_slot_for_multiple_conditions(self):
        from dpt_extractor.export.report_template import (
            DPT_REPORT_IMAGE_PARAMS,
            _DPT_IMAGE_HEADERS,
            write_report_template,
        )
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "report.xlsx"
            image = td_path / "scope_4x3.png"
            _write_rgb_png(image, (1280, 960))

            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            block_offsets = {"off": 0, "on": 17, "rr": 34}
            for base, condition in ((1, "750V_1050A"), (54, "750V_805A")):
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.cell(base, 1, "UH_RT")
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.cell(base + 17, 1, condition)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.cell(base + 34, 1, "总概览图")
                for block, row_offset in block_offsets.items():
                    headers = [
                        header_text
                        for _key, (item_block, header_text) in _DPT_IMAGE_HEADERS.items()
                        if item_block == block
                    ]
                    if block == "rr":
                        headers = ["Didt_Irr"] + [
                            header for header in headers if header != "Didt_Irr"
                        ]
                    for idx, header_text in enumerate(headers):
                        col = 10 + idx * 8
                        header_row = base + row_offset
                        wave.merge_cells(
                            start_row=header_row,
                            start_column=col,
                            end_row=header_row,
                            end_column=col + 7,
                        )
                        wave.cell(header_row, col, header_text)
                        wave.merge_cells(
                            start_row=header_row + 1,
                            start_column=col,
                            end_row=header_row + 16,
                            end_column=col + 7,
                        )
                        wave.cell(header_row + 1, col, "slot")
            wb.save(report)

            images = {param: image for param in DPT_REPORT_IMAGE_PARAMS}
            for current in ("UH_750V_1050A_000.tss", "UH_750V_805A_000.tss"):
                summary = write_report_template(
                    ExtractResult(
                        source_path=str(Path("samples") / "RT" / current),
                        profile_code="UH",
                    ),
                    report,
                    images=images,
                )
                self.assertEqual(summary.images_written, len(DPT_REPORT_IMAGE_PARAMS))

            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            self.assertEqual(len(saved_wave._images), len(DPT_REPORT_IMAGE_PARAMS) * 2)
            leftovers = [
                (cell.row, cell.column)
                for row in saved_wave.iter_rows(min_row=1, max_row=104)
                for cell in row
                if cell.value == "slot"
            ]
            self.assertEqual(leftovers, [])

    def test_single_pulse_template_skips_turn_on_and_reverse_recovery_images(self):
        from dpt_extractor.export.report_template import (
            DPT_REPORT_IMAGE_PARAMS,
            _DPT_IMAGE_HEADERS,
            dpt_report_image_params_for_result,
            write_report_template,
        )
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "report.xlsx"
            image = td_path / "scope_4x3.png"
            _write_rgb_png(image, (1280, 960))

            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            wave.merge_cells(start_row=1, start_column=1, end_row=17, end_column=8)
            wave.cell(1, 1, "UH_RT")
            wave.merge_cells(start_row=18, start_column=1, end_row=34, end_column=8)
            wave.cell(18, 1, "750V_1050A")
            wave.merge_cells(start_row=35, start_column=1, end_row=51, end_column=8)
            wave.cell(35, 1, "总概览图")
            block_offsets = {"off": 0, "on": 17, "rr": 34}
            block_counts = {"off": 0, "on": 0, "rr": 0}
            for _key, (block, header_text) in _DPT_IMAGE_HEADERS.items():
                col = 10 + block_counts[block] * 8
                block_counts[block] += 1
                header_row = 1 + block_offsets[block]
                wave.merge_cells(
                    start_row=header_row,
                    start_column=col,
                    end_row=header_row,
                    end_column=col + 7,
                )
                wave.cell(header_row, col, header_text)
                wave.merge_cells(
                    start_row=header_row + 1,
                    start_column=col,
                    end_row=header_row + 16,
                    end_column=col + 7,
                )
            wb.save(report)

            result = ExtractResult(
                source_path=str(Path("samples") / "RT" / "UH_750V_1050A_000.tss"),
                profile_code="UH",
                single_pulse_mode=True,
            )
            allowed_params = dpt_report_image_params_for_result(result)
            self.assertFalse(
                any(
                    section in {"开通", "反向恢复"}
                    for section, _name in allowed_params
                )
            )

            summary = write_report_template(
                result,
                report,
                images={param: image for param in DPT_REPORT_IMAGE_PARAMS},
            )

            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            self.assertEqual(summary.images_written, len(allowed_params))
            self.assertEqual(len(saved_wave._images), len(allowed_params))

    def test_dpt_image_slots_fit_fixed_4x3_display_size(self):
        from openpyxl.worksheet.cell_range import CellRange

        from dpt_extractor.export.report_template import (
            REPORT_IMAGE_DISPLAY_SIZE_PX,
            _column_width_px,
            _range_size_px,
            _row_height_px,
            write_report_template,
        )
        from dpt_extractor.models.results import ExtractResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "report.xlsx"
            image = td_path / "scope_4x3.png"
            _write_rgb_png(image, (1280, 960))

            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A8")
            ws.merge_cells("B5:B8")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            wave.merge_cells(start_row=1, start_column=1, end_row=17, end_column=8)
            wave.cell(1, 1, "UH_RT")
            wave.merge_cells(start_row=18, start_column=1, end_row=34, end_column=8)
            wave.cell(18, 1, "750V_1050A")
            wave.merge_cells(start_row=35, start_column=1, end_row=51, end_column=8)
            wave.cell(35, 1, "总概览图")
            wave.merge_cells(start_row=1, start_column=10, end_row=1, end_column=17)
            wave.cell(1, 10, "△Vce（V）")
            wave.merge_cells(start_row=2, start_column=10, end_row=17, end_column=17)
            wb.save(report)

            write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_1050A_000.tss"),
                    profile_code="UH",
                ),
                report,
                images={("关断过程", "ΔVce"): image},
            )

            saved_wave = load_workbook(report)["U相_双脉冲波形"]
            anchors = _drawing_anchor_counts(report)
            self.assertEqual(anchors["twoCellAnchor"], 1)
            self.assertEqual(anchors["oneCellAnchor"], 0)
            slot = CellRange("J2:Q17")
            slot_w, slot_h = _range_size_px(saved_wave, slot)
            self.assertGreaterEqual(slot_w, REPORT_IMAGE_DISPLAY_SIZE_PX[0] - 2)
            self.assertGreaterEqual(slot_h, REPORT_IMAGE_DISPLAY_SIZE_PX[1] - 2)
            self.assertGreaterEqual(
                sum(_column_width_px(saved_wave, col) for col in range(10, 18)),
                REPORT_IMAGE_DISPLAY_SIZE_PX[0],
            )
            self.assertGreaterEqual(
                sum(_row_height_px(saved_wave, row) for row in range(2, 18)),
                REPORT_IMAGE_DISPLAY_SIZE_PX[1],
            )

    def test_dpt_template_supports_more_than_four_condition_slots(self):
        from dpt_extractor.export.mcu2506_layout import COL_OFF
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, TurnOffResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "expanded_report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A10")
            ws.merge_cells("B5:B10")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            wave = wb.create_sheet("U相_双脉冲波形")
            conditions = (
                "750V_1050A",
                "750V_805A",
                "750V_50A",
                "600V_285A",
                "750V_1200A",
            )
            for idx, condition in enumerate(conditions):
                base = 1 + idx * 53
                wave.merge_cells(start_row=base, start_column=1, end_row=base + 16, end_column=8)
                wave.cell(base, 1, "UH_RT")
                wave.merge_cells(start_row=base + 17, start_column=1, end_row=base + 33, end_column=8)
                wave.cell(base + 17, 1, condition)
                wave.merge_cells(start_row=base + 34, start_column=1, end_row=base + 50, end_column=8)
                wave.cell(base + 34, 1, "总概览图")
            wb.save(report)

            for row, current in zip(range(5, 9), (1050, 805, 50, 285)):
                ws.cell(row, 4, 750 if current != 285 else 600)
                ws.cell(row, 5, current)
            wb.save(report)

            result = ExtractResult(
                source_path=str(Path("samples") / "RT" / "UH_750V_1200A_000.tss"),
                profile_code="UH",
                turn_off=TurnOffResult(delta_vce=555.0),
            )
            summary = write_report_template(result, report)
            saved = load_workbook(report)

            self.assertEqual(summary.data_row, 9)
            self.assertEqual(summary.waveform_anchor_row, 213)
            self.assertEqual(saved["U相_双脉冲数据"].cell(9, COL_OFF["delta_vce"]).value, 555.0)

    def test_dpt_template_multi_pulse_rows_do_not_overwrite_next_condition(self):
        from dpt_extractor.export.mcu2506_layout import COL_CURRENT, COL_OFF, COL_ON, COL_VOLTAGE
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, TurnOffResult, TurnOnResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "multi_report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "U相_双脉冲数据"
            ws.merge_cells("A5:A7")
            ws.merge_cells("B5:B7")
            ws["A5"] = "UH"
            ws["B5"] = "25℃"
            ws.cell(5, COL_VOLTAGE, 750)
            ws.cell(5, COL_CURRENT, 1048)
            ws.cell(6, COL_VOLTAGE, 750)
            ws.cell(6, COL_CURRENT, 806)
            wb.save(report)

            rows = [
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_1048A_000.tss"),
                    profile_code="UH",
                    detected_pulse_count=3,
                    off_pulse_index=1,
                    on_pulse_index=2,
                    turn_off=TurnOffResult(delta_vce=101.0),
                    turn_on=TurnOnResult(delta_vce=201.0),
                ),
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_1048A_000.tss"),
                    profile_code="UH",
                    detected_pulse_count=3,
                    off_pulse_index=2,
                    on_pulse_index=3,
                    turn_off=TurnOffResult(delta_vce=102.0),
                    turn_on=TurnOnResult(delta_vce=202.0),
                ),
            ]
            summary = write_report_template(rows, report)
            saved = load_workbook(report)["U相_双脉冲数据"]

            self.assertEqual(summary.data_row, 5)
            self.assertEqual(summary.data_row_end, 6)
            self.assertEqual(summary.data_rows_written, 2)
            self.assertEqual(saved.cell(5, COL_OFF["delta_vce"]).value, 101.0)
            self.assertEqual(saved.cell(5, COL_ON["delta_vce"]).value, 201.0)
            self.assertEqual(saved.cell(6, COL_OFF["delta_vce"]).value, 102.0)
            self.assertEqual(saved.cell(6, COL_ON["delta_vce"]).value, 202.0)
            self.assertEqual(saved.cell(7, COL_CURRENT).value, 806)

    def test_short_template_uses_labeled_picture_blocks_not_row_offsets(self):
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, ShortCircuitResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "short_report.xlsx"
            image = td_path / "short.png"
            _write_tiny_png(image)

            wb = Workbook()
            ws = wb.active
            ws.title = "短路测试"
            ws.merge_cells("A5:A6")
            ws["A5"] = 25
            ws["B5"] = "UH"
            ws["B6"] = "UL"
            pic = wb.create_sheet("短路测试图片")
            for base, phase_temp in ((1, "UH_RT"), (12, "UL_RT")):
                pic.merge_cells(
                    start_row=base,
                    start_column=1,
                    end_row=base + 3,
                    end_column=5,
                )
                pic.cell(base, 1, phase_temp)
                pic.cell(base + 4, 1, "Vce")
                pic.cell(base + 4, 2, "Imax")
                pic.merge_cells(
                    start_row=base,
                    start_column=6,
                    end_row=base,
                    end_column=8,
                )
                pic.cell(base, 6, "短路电流Imax 短路时间Tsc 短路能量Esc_本管")
                pic.merge_cells(
                    start_row=base + 1,
                    start_column=6,
                    end_row=base + 9,
                    end_column=8,
                )
            wb.save(report)

            rows_and_anchors = []
            for phase, filename, current in (
                ("UL", "UL_750V_000.tss", 2222.0),
                ("UH", "UH_750V_000.tss", 1111.0),
            ):
                summary = write_report_template(
                    ExtractResult(
                        source_path=str(Path("samples") / "RT" / filename),
                        profile_code=phase,
                        vdc_set=750.0,
                        short_circuit_mode=True,
                        short_circuit=ShortCircuitResult(ic_max=current),
                    ),
                    report,
                    images={("短路过程", "短路电流Imax"): image},
                )
                rows_and_anchors.append((summary.data_row, summary.waveform_anchor_row))

            saved = load_workbook(report)
            self.assertEqual(rows_and_anchors, [(6, 12), (5, 1)])
            self.assertEqual(saved["短路测试"].cell(5, 5).value, 1111)
            self.assertEqual(saved["短路测试"].cell(6, 5).value, 2222)
            self.assertEqual(saved["短路测试图片"].cell(1, 1).value, "UH_25℃")
            self.assertEqual(saved["短路测试图片"].cell(12, 1).value, "UL_25℃")
            self.assertEqual(saved["短路测试图片"].cell(6, 1).value, "750V")
            self.assertEqual(saved["短路测试图片"].cell(6, 2).value, "1111A")
            self.assertEqual(saved["短路测试图片"].cell(17, 1).value, "750V")
            self.assertEqual(saved["短路测试图片"].cell(17, 2).value, "2222A")
            self.assertEqual(len(saved["短路测试图片"]._images), 2)

    def test_short_template_uses_current_temperature_label(self):
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, ShortCircuitResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "short_report.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "短路测试"
            ws.merge_cells("A5:A6")
            ws["A5"] = "RT"
            ws["B5"] = "UH"
            ws["B6"] = "UL"
            pic = wb.create_sheet("短路测试图片")
            pic.merge_cells("A1:E4")
            pic["A1"] = "UH_RT"
            wb.save(report)

            write_report_template(
                ExtractResult(
                    source_path=str(Path("samples") / "RT" / "UH_750V_000.tss"),
                    profile_code="UH",
                    short_circuit_mode=True,
                    short_circuit=ShortCircuitResult(ic_max=1234.0),
                ),
                report,
                temperature_labels={"RT": "26.5℃", "HT": "175℃", "LT": "-55℃"},
            )

            saved = load_workbook(report)
            self.assertEqual(saved["短路测试"].cell(5, 1).value, "26.5℃")
            self.assertEqual(saved["短路测试图片"].cell(1, 1).value, "UH_26.5℃")

    def test_short_template_writes_row_and_global_image_slot(self):
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, ShortCircuitResult

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            report = td_path / "short_report.xlsx"
            image = td_path / "short.png"
            _write_tiny_png(image)

            wb = Workbook()
            ws = wb.active
            ws.title = "短路测试"
            ws.merge_cells("A5:A6")
            ws["A5"] = 25
            ws["B5"] = "UH"
            ws["B6"] = "UL"
            ws.merge_cells("A7:A8")
            ws["A7"] = 25
            ws["B7"] = "VH"
            ws["B8"] = "VL"
            pic = wb.create_sheet("短路测试图片")
            pic.merge_cells("A1:E4")
            pic["A1"] = "VH_RT"
            pic["A5"] = "Vce"
            pic["B5"] = "Imax"
            pic.merge_cells("F1:H1")
            pic["F1"] = "短路电流Imax 短路时间Tsc 短路能量Esc_本管"
            pic.merge_cells("F2:H10")
            wb.save(report)

            result = ExtractResult(
                source_path=str(Path("samples") / "RT" / "VH_750V_000.tss"),
                profile_code="VH",
                vdc_set=488.123,
                short_circuit_mode=True,
                short_circuit=ShortCircuitResult(ic_max=3210.5),
            )
            summary = write_report_template(
                result,
                report,
                images={("短路过程", "短路电流Imax"): image},
            )

            saved = load_workbook(report)
            self.assertEqual(summary.data_sheet, "短路测试")
            self.assertEqual(summary.data_row, 7)
            self.assertEqual(saved["短路测试"].cell(7, 4).value, 750)
            self.assertEqual(saved["短路测试"].cell(7, 5).value, 3210.5)
            self.assertEqual(saved["短路测试图片"].cell(6, 1).value, "750V")
            self.assertEqual(saved["短路测试图片"].cell(6, 2).value, "3210.5A")
            self.assertEqual(len(saved["短路测试图片"]._images), 1)


if __name__ == "__main__":
    unittest.main()
