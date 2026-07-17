"""songzhenxi 报告参数局部视图的真实 TSS 回归。"""

from __future__ import annotations

import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from dpt_extractor.config.loader import load_config
from dpt_extractor.export.report_template import (
    DPT_OVERVIEW_IMAGE_PARAM,
    DPT_REPORT_IMAGE_PARAMS,
)
from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.gui.waveform_plot import PARAM_FOCUS_ANCHOR_FRACTION, WaveformPlot
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import guess_profile_from_path, make_profile
from dpt_extractor.models.channel_mapping import apply_mapping, infer_mapping_from_bundle
from dpt_extractor.pipeline.extract import extract_all


ROOT = Path(__file__).resolve().parents[2]
SONGZHENXI_SMC_HT = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "HT"
    / "tss"
)
FOCUS_SAMPLES = (
    SONGZHENXI_SMC_HT / "VH_600V_403A_000.tss",
    SONGZHENXI_SMC_HT / "VH_750V_806A_000.tss",
)
LOCAL_REPORT_PARAMS = tuple(
    param for param in DPT_REPORT_IMAGE_PARAMS if param != DPT_OVERVIEW_IMAGE_PARAM
)


class TestSongzhenxiParameterFocus(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _load_case(self, sample_path: Path):
        cfg = load_config()
        bundle = load_waveform(sample_path)
        guessed = guess_profile_from_path(sample_path.name)
        profile = make_profile(guessed.phase, guessed.bridge)
        inferred = infer_mapping_from_bundle(bundle, guessed.bridge)
        if inferred is not None:
            profile = apply_mapping(profile, inferred)
        result = extract_all(bundle, profile, cfg)
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, result)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = cfg
        win.wave_plot = plot
        win.result_table.set_result(result)
        return win, plot, result

    def test_all_report_parameter_views_keep_verified_geometry_and_result(self):
        self.assertEqual(len(LOCAL_REPORT_PARAMS), 18)
        self.assertGreaterEqual(PARAM_FOCUS_ANCHOR_FRACTION, 0.10)
        self.assertLessEqual(PARAM_FOCUS_ANCHOR_FRACTION, 0.15)

        for sample_path in FOCUS_SAMPLES:
            if not sample_path.is_file():
                self.skipTest(f"songzhenxi 样例缺失: {sample_path}")

            win, plot, result = self._load_case(sample_path)
            result_before_focus = deepcopy(result)
            focus_calls: list[tuple[float, tuple[float, ...], float]] = []
            original_focus = plot.focus_parameter_window_us

            def record_focus(
                anchor_us: float,
                *required_times_us: float,
                anchor_fraction: float = PARAM_FOCUS_ANCHOR_FRACTION,
            ) -> None:
                focus_calls.append(
                    (
                        float(anchor_us),
                        tuple(float(value) for value in required_times_us),
                        float(anchor_fraction),
                    )
                )
                original_focus(
                    anchor_us,
                    *required_times_us,
                    anchor_fraction=anchor_fraction,
                )

            plot.focus_parameter_window_us = record_focus  # type: ignore[method-assign]
            try:
                for section, name in LOCAL_REPORT_PARAMS:
                    with self.subTest(
                        sample=sample_path.name,
                        section=section,
                        parameter=name,
                    ):
                        self.assertFalse(result.is_metric_unavailable(section, name))
                        focus_calls.clear()
                        win._on_value_clicked(section, name)
                        QApplication.processEvents()

                        self.assertTrue(focus_calls, "参数点击未执行局部视图构图")
                        self.assertIsNotNone(plot._cursor_a)
                        self.assertIsNotNone(plot._cursor_b)
                        self.assertIsNotNone(plot.current_x_range_us())
                        assert plot._cursor_a is not None
                        assert plot._cursor_b is not None
                        x_range = plot.current_x_range_us()
                        assert x_range is not None

                        x0, x1 = map(float, x_range)
                        span_us = x1 - x0
                        self.assertAlmostEqual(span_us, 2.0, places=6)

                        anchor_us, required_times_us, _requested_fraction = focus_calls[-1]
                        if section == "反向恢复":
                            expected_anchor = win._switching_focus_anchor_us(section)
                            self.assertIsNotNone(expected_anchor)
                            assert expected_anchor is not None
                            self.assertAlmostEqual(anchor_us, expected_anchor, places=6)
                        anchor_position = (anchor_us - x0) / span_us
                        self.assertGreaterEqual(anchor_position, 0.10)
                        self.assertLessEqual(anchor_position, 0.15)

                        cursor_a_us = float(plot._cursor_a.value())
                        cursor_b_us = float(plot._cursor_b.value())
                        for label, cursor_us in (("A", cursor_a_us), ("B", cursor_b_us)):
                            cursor_position = (cursor_us - x0) / span_us
                            self.assertGreaterEqual(
                                cursor_position,
                                0.04 if section == "反向恢复" else 0.095,
                                f"{label} 光标过于靠左: {cursor_position:.3%}",
                            )
                            self.assertLessEqual(
                                cursor_position,
                                0.80 if section == "反向恢复" else 0.65,
                                f"{label} 光标过于靠右: {cursor_position:.3%}",
                            )

                        self.assertGreaterEqual(
                            x1 - max(cursor_a_us, cursor_b_us),
                            0.70,
                            "较晚 A/B 后的右侧振铃观察区不足 0.70us",
                        )

                        self.assertTrue(required_times_us, "局部视图缺少必要守卫时刻")
                        for required_us in required_times_us:
                            required_position = (required_us - x0) / span_us
                            self.assertGreaterEqual(
                                required_position,
                                0.04,
                                f"必要守卫点过于靠左: {required_position:.3%}",
                            )
                            self.assertLessEqual(
                                required_position,
                                0.90 if section == "反向恢复" else 0.65,
                                f"必要守卫点过于靠右: {required_position:.3%}",
                            )

                        self.assertEqual(result, result_before_focus)

                self.assertEqual(result, result_before_focus)
            finally:
                win.close()
                plot.close()


if __name__ == "__main__":
    unittest.main()
