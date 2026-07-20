from __future__ import annotations

import unittest

from dpt_extractor.utils.filename import parse_setpoints_from_filename


class TestFilenameParsing(unittest.TestCase):
    def test_parse_setpoints_with_extra_condition_tokens_anywhere(self):
        cases = {
            "UH_Rg_on3.3_Rg_off3.6_Cg10_750V_805A_000.tss": (750.0, 805.0),
            "UH_750V_805A_Rg_on3.3_Rg_off3.6_Cg10_000.tss": (750.0, 805.0),
            "UH_750V_Rg_on3.3_Rg_off3.6_Cg10_805A_000.tss": (750.0, 805.0),
            "UH_805A_Rg_on3.3_750V_Rg_off3.6_Cg10_000.tss": (750.0, 805.0),
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(parse_setpoints_from_filename(filename), expected)

    def test_parse_decimal_setpoints_from_report_condition_labels(self):
        cases = {
            "900V_494.9A": (900.0, 494.9),
            "900V_693.37A": (900.0, 693.37),
            "850V_777.7A": (850.0, 777.7),
            "850V_1061.01A": (850.0, 1061.01),
        }
        for label, expected in cases.items():
            with self.subTest(label=label):
                self.assertEqual(parse_setpoints_from_filename(label), expected)


if __name__ == "__main__":
    unittest.main()
