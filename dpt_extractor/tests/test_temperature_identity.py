from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from openpyxl import Workbook, load_workbook


class TestTemperatureParsingAndIdentity(unittest.TestCase):
    def test_numeric_temperature_parser_rejects_voltage_and_current_tokens(self):
        from dpt_extractor.utils.temperature import infer_temperature_token_code

        self.assertIsNone(infer_temperature_token_code("VH_150V_400A"))
        self.assertIsNone(infer_temperature_token_code("VH_25V_400A"))
        self.assertIsNone(infer_temperature_token_code("VH_40A_400V"))

    def test_report_and_gui_path_inference_do_not_promote_150v_to_ht(self):
        from dpt_extractor.export.report_template import _infer_temp_code as report_infer
        from dpt_extractor.gui.main_window import _infer_temp_code_from_path
        from dpt_extractor.gui.result_table import _infer_temp_code as table_infer

        path = "VH_150V_400A.tss"
        self.assertNotEqual(_infer_temp_code_from_path(path), "HT")
        self.assertNotEqual(table_infer(path), "HT")
        self.assertNotEqual(report_infer(path), "HT")

    def test_numeric_temperature_parser_accepts_current_ht_condition(self):
        from dpt_extractor.utils.temperature import infer_temperature_token_code

        self.assertEqual(infer_temperature_token_code("VH_175C_400A"), "HT")
        self.assertEqual(infer_temperature_token_code("VH_175℃_400A"), "HT")
        self.assertEqual(infer_temperature_token_code("VH_-40C_400A"), "LT")

    def test_previous_temperature_labels_fill_omitted_current_labels(self):
        from dpt_extractor.export.report_template import _TemperatureIdentityLabels

        labels = _TemperatureIdentityLabels(None, previous={"HT": "175℃"})
        self.assertEqual(labels["HT"], "175℃")

        explicit = _TemperatureIdentityLabels(
            {"HT": "150℃"}, previous={"HT": "175℃"}
        )
        self.assertEqual(explicit["HT"], "150℃")

    def test_report_write_reuses_persisted_175c_when_labels_are_omitted(self):
        from dpt_extractor.export.report_template import write_report_template
        from dpt_extractor.models.results import ExtractResult, TurnOffResult

        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / "report.xlsx"
            wb = Workbook()
            data = wb.active
            data.title = "U相_双脉冲数据"
            for start_row, temperature in ((5, "25℃"), (9, "150℃")):
                data.merge_cells(
                    start_row=start_row,
                    start_column=1,
                    end_row=start_row + 3,
                    end_column=1,
                )
                data.merge_cells(
                    start_row=start_row,
                    start_column=2,
                    end_row=start_row + 3,
                    end_column=2,
                )
                data.cell(start_row, 1, "UH")
                data.cell(start_row, 2, temperature)
            wave = wb.create_sheet("U相_双脉冲波形")
            wave.merge_cells("A1:H17")
            wave["A1"] = "UH_150℃"
            wave.merge_cells("A18:H34")
            wave["A18"] = "750V_1050A"
            wave.merge_cells("A35:H51")
            wave["A35"] = "总概览图"
            wb.save(report)

            result = ExtractResult(
                source_path="samples/HT/UH_750V_1050A_000.tss",
                profile_code="UH",
                turn_off=TurnOffResult(eoff=1.25),
            )
            first = write_report_template(
                result,
                report,
                temperature_labels={
                    "RT": "25℃",
                    "HT": "175℃",
                    "LT": "-40℃",
                },
                temperature_code="HT",
                phase_code="UH",
            )
            result.turn_off.eoff = 2.5
            second = write_report_template(
                result,
                report,
                temperature_code="HT",
                phase_code="UH",
            )

            saved = load_workbook(report)
            self.assertEqual(first.data_row, 9)
            self.assertEqual(second.data_row, 9)
            self.assertEqual(saved["U相_双脉冲数据"]["B9"].value, "175℃")
            self.assertEqual(saved["U相_双脉冲波形"]["A1"].value, "UH_175℃")
            self.assertNotIn("150℃", [
                saved["U相_双脉冲数据"].cell(row, 2).value
                for row in range(5, saved["U相_双脉冲数据"].max_row + 1)
            ])


if __name__ == "__main__":
    unittest.main()
