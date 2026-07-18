from __future__ import annotations

import unittest

from dpt_extractor.models.slope_range import (
    SlopeRange,
    default_slope_ranges,
    preset_index_for_range,
)


class TestSlopeRangePresetMatch(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
