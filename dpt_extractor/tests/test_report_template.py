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

    def test_dpt_template_writes_matching_condition_row_and_image(self):
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
                images={
                    DPT_OVERVIEW_IMAGE_PARAM: image,
                    ("关断过程", "ΔVce"): image,
                },
            )

            saved = load_workbook(report)
            saved_wave = saved["U相_双脉冲波形"]
            self.assertEqual(summary.data_sheet, "U相_双脉冲数据")
            self.assertEqual(summary.data_row, 6)
            self.assertEqual(summary.waveform_anchor_row, 54)
            self.assertEqual(saved["U相_双脉冲数据"].cell(6, COL_OFF["delta_vce"]).value, 123.456)
            self.assertIsNone(saved_wave.cell(88, 1).value)
            self.assertLess(saved_wave.column_dimensions["J"].width, 13)
            self.assertEqual(len(saved_wave._images), 2)

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
            pic.merge_cells("F1:H1")
            pic["F1"] = "短路电流Imax 短路时间Tsc 短路能量Esc_本管"
            pic.merge_cells("F2:H10")
            wb.save(report)

            result = ExtractResult(
                source_path=str(Path("samples") / "RT" / "VH_750V_000.tss"),
                profile_code="VH",
                vdc_set=750.0,
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
            self.assertEqual(saved["短路测试"].cell(7, 5).value, 3210.5)
            self.assertEqual(len(saved["短路测试图片"]._images), 1)


if __name__ == "__main__":
    unittest.main()
