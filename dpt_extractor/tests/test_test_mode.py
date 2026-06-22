import unittest

from dpt_extractor.config.loader import TestModeConfig, _merge_dataclass
from dpt_extractor.models.test_mode import MODE_UI_LABELS, TestMode, parse_test_mode


class TestTestMode(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_test_mode(None), TestMode.DPT)
        self.assertEqual(parse_test_mode("dpt"), TestMode.DPT)
        self.assertEqual(parse_test_mode("short_circuit"), TestMode.SHORT_CIRCUIT)
        self.assertEqual(
            parse_test_mode("offset_measurement"),
            TestMode.OFFSET_MEASUREMENT,
        )
        self.assertEqual(parse_test_mode("unknown"), TestMode.DPT)

    def test_ui_labels(self):
        self.assertEqual(MODE_UI_LABELS[TestMode.DPT], "双脉冲计算")
        self.assertEqual(MODE_UI_LABELS[TestMode.SHORT_CIRCUIT], "短路计算")
        self.assertEqual(MODE_UI_LABELS[TestMode.OFFSET_MEASUREMENT], "偏移测量")

    def test_config_merge(self):
        cfg = _merge_dataclass(TestModeConfig, {"mode": "short_circuit"})
        self.assertEqual(cfg.mode, "short_circuit")


if __name__ == "__main__":
    unittest.main()
