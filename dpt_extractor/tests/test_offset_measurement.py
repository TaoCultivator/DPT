from __future__ import annotations

import unittest

import numpy as np

from dpt_extractor.metrics.offset_measurement import (
    auto_offset_measurement_unit,
    calculate_offset_measurement,
    convert_offset_measurement_value,
    normalize_offset_metric_key,
    normalize_offset_range_key,
    offset_measurement_marker,
    offset_measurement_unit_candidates,
    offset_measurement_unit,
    scope_top_base,
)


class TestOffsetMeasurement(unittest.TestCase):
    def test_basic_waveform_measurements(self) -> None:
        t = np.array([0.0, 1.0, 2.0, 3.0])
        y = np.array([0.0, 2.0, 4.0, 6.0])

        self.assertAlmostEqual(calculate_offset_measurement(t, y, "maximum"), 6.0)
        self.assertAlmostEqual(calculate_offset_measurement(t, y, "minimum"), 0.0)
        self.assertAlmostEqual(calculate_offset_measurement(t, y, "peak_to_peak"), 6.0)
        self.assertAlmostEqual(calculate_offset_measurement(t, y, "mean"), 3.0)
        self.assertAlmostEqual(
            calculate_offset_measurement(t, y, "rms"),
            float(np.sqrt(np.mean(y * y))),
        )
        self.assertAlmostEqual(
            calculate_offset_measurement(t, y, "ac_rms"),
            float(np.sqrt(np.mean((y - np.mean(y)) ** 2))),
        )
        self.assertAlmostEqual(calculate_offset_measurement(t, y, "area"), 9.0)

    def test_units_follow_metric_kind(self) -> None:
        self.assertEqual(offset_measurement_unit("maximum", "V"), "V")
        self.assertEqual(offset_measurement_unit("positive_overshoot", "V"), "%")
        self.assertEqual(offset_measurement_unit("area", "A"), "A*s")
        self.assertIn("KW", offset_measurement_unit_candidates("maximum", "W"))
        self.assertIn("mJ", offset_measurement_unit_candidates("maximum", "J"))
        self.assertAlmostEqual(
            convert_offset_measurement_value(0.125, "J", "mJ"),
            125.0,
        )
        self.assertAlmostEqual(
            convert_offset_measurement_value(0.002, "A*s", "mA*s"),
            2.0,
        )
        self.assertAlmostEqual(
            convert_offset_measurement_value(500_000.0, "W", "KW"),
            500.0,
        )

    def test_auto_units_drop_below_one(self) -> None:
        self.assertEqual(auto_offset_measurement_unit(0.5, "V"), "mV")
        self.assertEqual(auto_offset_measurement_unit(-0.25, "A"), "mA")
        self.assertEqual(auto_offset_measurement_unit(0.125, "J"), "mJ")
        self.assertEqual(auto_offset_measurement_unit(0.0002, "J"), "uJ")
        self.assertEqual(auto_offset_measurement_unit(0.002, "A*s"), "mA*s")
        self.assertEqual(auto_offset_measurement_unit(2.0, "V"), "V")
        self.assertEqual(auto_offset_measurement_unit(0.0, "J"), "J")
        self.assertEqual(auto_offset_measurement_unit(0.5, "%"), "%")

    def test_power_units_default_to_kw(self) -> None:
        self.assertEqual(auto_offset_measurement_unit(0.0, "W"), "KW")
        self.assertEqual(auto_offset_measurement_unit(999.0, "W"), "W")
        self.assertEqual(auto_offset_measurement_unit(1000.0, "W"), "KW")
        self.assertEqual(auto_offset_measurement_unit(999_999.0, "W"), "KW")
        self.assertEqual(auto_offset_measurement_unit(1_000_000.0, "W"), "MW")
        self.assertEqual(auto_offset_measurement_unit(0.5, "KW"), "W")
        self.assertEqual(auto_offset_measurement_unit(2000.0, "KW"), "MW")

    def test_top_base_and_overshoot_follow_scope_definitions(self) -> None:
        t = np.arange(10, dtype=np.float64)
        y = np.array([0.0, 0.0, 0.0, 0.0, 10.0, 10.0, 10.0, 10.0, 12.0, -2.0])

        self.assertAlmostEqual(calculate_offset_measurement(t, y, "top"), 10.0)
        self.assertAlmostEqual(calculate_offset_measurement(t, y, "base"), 0.0)
        self.assertAlmostEqual(calculate_offset_measurement(t, y, "amplitude"), 10.0)
        self.assertAlmostEqual(
            calculate_offset_measurement(t, y, "positive_overshoot"),
            20.0,
        )
        self.assertAlmostEqual(
            calculate_offset_measurement(t, y, "negative_overshoot"),
            20.0,
        )

    def test_top_base_use_local_range_modal_levels_not_global_extrema(self) -> None:
        y = np.array(
            [-120.0, -110.0, 0.0, 0.0, 0.1, 9.9, 10.0, 10.0, 40.0, 45.0],
            dtype=np.float64,
        )

        top, base = scope_top_base(y[2:8])

        self.assertAlmostEqual(top, 10.0)
        self.assertAlmostEqual(base, 0.0)

    def test_area_rms_and_ac_rms_stay_inside_selected_range(self) -> None:
        t = np.array([10.0, 11.0, 12.0, 13.0], dtype=np.float64)
        y = np.array([-2.0, 0.0, 2.0, 4.0], dtype=np.float64)

        self.assertAlmostEqual(calculate_offset_measurement(t, y, "area"), 3.0)
        self.assertAlmostEqual(
            calculate_offset_measurement(t, y, "rms"),
            float(np.sqrt(np.mean(y * y))),
        )
        self.assertAlmostEqual(
            calculate_offset_measurement(t, y, "ac_rms"),
            float(np.sqrt(np.mean((y - np.mean(y)) ** 2))),
        )

    def test_metric_aliases_and_marker_points(self) -> None:
        t = np.arange(5, dtype=np.float64)
        y = np.array([1.0, 2.0, 9.0, 4.0, 3.0])

        self.assertEqual(normalize_offset_metric_key("PK2Pk"), "peak_to_peak")
        self.assertEqual(normalize_offset_metric_key("AC RMS"), "ac_rms")
        self.assertEqual(normalize_offset_range_key("visible"), "screen")
        self.assertEqual(normalize_offset_range_key("between cursors"), "cursor")
        self.assertEqual(normalize_offset_range_key(None), "screen")
        self.assertEqual(normalize_offset_range_key("全波形"), "full")
        self.assertEqual(normalize_offset_range_key("屏幕"), "screen")
        self.assertEqual(normalize_offset_range_key("光标"), "cursor")
        self.assertEqual(offset_measurement_marker(t, y, "maximum"), (2.0, 9.0))


if __name__ == "__main__":
    unittest.main()
