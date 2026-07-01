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


if __name__ == "__main__":
    unittest.main()
