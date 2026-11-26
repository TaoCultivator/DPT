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
from dpt_extractor.gui.waveform_plot import (
    PARAM_FOCUS_ANCHOR_FRACTION,
    PARAM_FOCUS_EVENT_CENTER_FRACTION,
    PARAM_FOCUS_REQUIRED_GUARD_US,
    TURN_ON_CURRENT_FOCUS_MIDPOINT_FRACTION,
    TURN_ON_LS_FOCUS_MIDPOINT_FRACTION,
    TURN_ON_SLOPE_FOCUS_MIDPOINT_FRACTION,
    RR_POWER_FOCUS_MIDPOINT_FRACTION,
    RR_ERR_FOCUS_MIDPOINT_FRACTION,
    RR_TRR_ANCHOR_FRACTION,
    TF_FOCUS_MIDPOINT_FRACTION,
    WaveformPlot,
)
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
            focus_calls: list[
                tuple[float, tuple[float, ...], float, bool, float | None]
            ] = []
            original_focus = plot.focus_parameter_window_us

            def record_focus(
                anchor_us: float,
                *required_times_us: float,
                anchor_fraction: float = PARAM_FOCUS_ANCHOR_FRACTION,
                prefer_right_room: bool = False,
                minimum_span_us: float | None = None,
                composition_anchor_us: float | None = None,
                composition_balance_fraction: float | None = None,
                min_margin_fraction: float = 0.0,
                center_required: bool = False,
                center_event_us: float | None = None,
                ) -> None:
                focus_calls.append(
                    (
                        float(anchor_us),
                        tuple(float(value) for value in required_times_us),
                        float(anchor_fraction),
                        bool(prefer_right_room),
                        (
                            None
                            if center_event_us is None
                            else float(center_event_us)
                        ),
                    )
                )
                original_focus(
                    anchor_us,
                    *required_times_us,
                    anchor_fraction=anchor_fraction,
                    prefer_right_room=prefer_right_room,
                    minimum_span_us=minimum_span_us,
                    composition_anchor_us=composition_anchor_us,
                    composition_balance_fraction=composition_balance_fraction,
                    min_margin_fraction=min_margin_fraction,
                    center_required=center_required,
                    center_event_us=center_event_us,
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
                        self.assertGreaterEqual(span_us, 2.0 - 1e-6)

                        (
                            anchor_us,
                            required_times_us,
                            requested_fraction,
                            prefer_right_room,
                            center_event_us,
                        ) = focus_calls[-1]
                        gate_anchored = "vge" in win._cursor_endpoint_channels_for_param(
                            section, name
                        )
                        settle_centered = center_event_us is not None
                        vge_auxiliary = (
                            section in {"开通", "反向恢复"} and not gate_anchored
                        )
                        turn_on_current_balanced = (
                            section,
                            name,
                        ) == ("开通", "开通电流")
                        turn_on_slope_balanced = (
                            section == "开通" and name in {"dv/dt", "di/dt"}
                        )
                        turn_on_ls_balanced = (section, name) == ("开通", "Ls_on")
                        tf_balanced = (section, name) == ("关断过程", "Tf")
                        rr_power_balanced = (section, name) == ("反向恢复", "Pdmax")
                        rr_err_balanced = (section, name) == ("反向恢复", "Err")
                        rr_trr_shifted = (section, name) == ("反向恢复", "Trr")
                        if gate_anchored:
                            self.assertFalse(prefer_right_room)
                            expected_anchor = win._switching_focus_anchor_us(section)
                            self.assertIsNotNone(expected_anchor)
                            assert expected_anchor is not None
                            self.assertAlmostEqual(anchor_us, expected_anchor, places=6)
                            self.assertAlmostEqual(
                                requested_fraction,
                                PARAM_FOCUS_ANCHOR_FRACTION,
                                places=9,
                            )
                        elif settle_centered:
                            # New first-view contract: the post-spike settling onset
                            # is the 50% composition anchor, not the Vge edge.
                            self.assertFalse(prefer_right_room)
                            self.assertTrue(required_times_us)
                            self.assertAlmostEqual(anchor_us, center_event_us, places=6)
                            self.assertAlmostEqual(
                                requested_fraction,
                                PARAM_FOCUS_EVENT_CENTER_FRACTION,
                                places=9,
                            )
                        elif vge_auxiliary:
                            # Turn-on/recovery non-gate rows use the Vge rising
                            # edge as a proportional composition reference;
                            # their real A/B envelope remains the required
                            # visibility constraint.
                            self.assertTrue(prefer_right_room)
                            self.assertTrue(required_times_us)
                            expected_anchor = win._switching_focus_anchor_us(section)
                            self.assertIsNotNone(expected_anchor)
                            assert expected_anchor is not None
                            self.assertAlmostEqual(anchor_us, expected_anchor, places=6)
                            self.assertAlmostEqual(
                                requested_fraction,
                                PARAM_FOCUS_ANCHOR_FRACTION,
                                places=9,
                            )
                        elif turn_on_current_balanced:
                            self.assertFalse(prefer_right_room)
                            self.assertTrue(required_times_us)
                            self.assertAlmostEqual(
                                anchor_us,
                                0.5
                                * (min(required_times_us) + max(required_times_us)),
                                places=9,
                            )
                            self.assertAlmostEqual(
                                requested_fraction,
                                TURN_ON_CURRENT_FOCUS_MIDPOINT_FRACTION,
                                places=9,
                            )
                        elif turn_on_slope_balanced:
                            self.assertFalse(prefer_right_room)
                            self.assertTrue(required_times_us)
                            self.assertAlmostEqual(
                                anchor_us,
                                0.5
                                * (min(required_times_us) + max(required_times_us)),
                                places=9,
                            )
                            self.assertAlmostEqual(
                                requested_fraction,
                                TURN_ON_SLOPE_FOCUS_MIDPOINT_FRACTION,
                                places=9,
                            )
                        elif turn_on_ls_balanced:
                            self.assertFalse(prefer_right_room)
                            self.assertTrue(required_times_us)
                            self.assertEqual(len(required_times_us), 2)
                            self.assertAlmostEqual(
                                anchor_us,
                                0.5
                                * (min(required_times_us) + max(required_times_us)),
                                places=9,
                            )
                            self.assertAlmostEqual(
                                requested_fraction,
                                TURN_ON_LS_FOCUS_MIDPOINT_FRACTION,
                                places=9,
                            )
                        elif rr_power_balanced:
                            self.assertFalse(prefer_right_room)
                            self.assertEqual(len(required_times_us), 2)
                            self.assertAlmostEqual(anchor_us, 0.5 * sum(required_times_us), places=9)
                            self.assertAlmostEqual(requested_fraction, RR_POWER_FOCUS_MIDPOINT_FRACTION, places=9)
                        elif rr_err_balanced:
                            self.assertFalse(prefer_right_room)
                            self.assertEqual(len(required_times_us), 2)
                            self.assertAlmostEqual(anchor_us, 0.5 * sum(required_times_us), places=9)
                            self.assertAlmostEqual(requested_fraction, RR_ERR_FOCUS_MIDPOINT_FRACTION, places=9)
                        elif rr_trr_shifted:
                            self.assertFalse(prefer_right_room)
                            self.assertEqual(len(required_times_us), 2)
                            self.assertAlmostEqual(anchor_us, 0.5 * sum(required_times_us), places=9)
                            self.assertAlmostEqual(requested_fraction, RR_TRR_ANCHOR_FRACTION, places=9)
                        elif tf_balanced:
                            self.assertFalse(prefer_right_room)
                            self.assertTrue(required_times_us)
                            self.assertAlmostEqual(
                                anchor_us,
                                0.5
                                * (min(required_times_us) + max(required_times_us)),
                                places=9,
                            )
                            self.assertAlmostEqual(
                                requested_fraction,
                                TF_FOCUS_MIDPOINT_FRACTION,
                                places=9,
                            )
                        else:
                            self.assertTrue(prefer_right_room)
                            self.assertTrue(required_times_us)
                            self.assertAlmostEqual(
                                anchor_us,
                                0.5
                                * (min(required_times_us) + max(required_times_us)),
                                places=9,
                            )
                        anchor_position = (anchor_us - x0) / span_us
                        if gate_anchored:
                            self.assertGreaterEqual(anchor_position, 0.10)
                            self.assertLessEqual(anchor_position, 0.65)
                        elif settle_centered:
                            full_range = plot._full_x_range
                            assert full_range is not None
                            interior = (
                                x0 > float(full_range[0]) + 0.025
                                and x1 < float(full_range[1]) - 0.025
                            )
                            if interior:
                                self.assertAlmostEqual(
                                    anchor_position,
                                    PARAM_FOCUS_EVENT_CENTER_FRACTION,
                                    delta=0.025,
                                )
                        elif vge_auxiliary:
                            # The Vge reference is kept just inside the left
                            # edge; the physical A/B envelope owns the rest
                            # of the right-priority composition.
                            self.assertGreaterEqual(anchor_position, -0.02)
                            self.assertLessEqual(anchor_position, 0.35)
                            full_range = plot._full_x_range
                            assert full_range is not None
                            interior = (
                                x0 > float(full_range[0]) + 0.025
                                and x1 < float(full_range[1]) - 0.025
                            )
                            required_lo = min(required_times_us)
                            required_hi = max(required_times_us)
                            self.assertGreaterEqual(
                                x1 - required_hi + 0.025,
                                required_lo - x0,
                                "开通/反向恢复 Vge 辅助构图右侧观察余量不足",
                            )
                        elif turn_on_current_balanced:
                            required_lo = min(required_times_us)
                            required_hi = max(required_times_us)
                            left_room = required_lo - x0
                            right_room = x1 - required_hi
                            self.assertGreaterEqual(
                                right_room + 0.025,
                                left_room,
                                "开通电流右侧观察余量不足",
                            )
                            full_range = plot._full_x_range
                            assert full_range is not None
                            interior = (
                                x0 > float(full_range[0]) + 0.025
                                and x1 < float(full_range[1]) - 0.025
                            )
                            if interior:
                                self.assertAlmostEqual(
                                    anchor_position,
                                    TURN_ON_CURRENT_FOCUS_MIDPOINT_FRACTION,
                                    delta=0.025,
                                )
                        elif turn_on_slope_balanced:
                            required_lo = min(required_times_us)
                            required_hi = max(required_times_us)
                            left_room = required_lo - x0
                            right_room = x1 - required_hi
                            self.assertGreaterEqual(
                                right_room + 0.025,
                                left_room,
                                "开通斜率右侧观察余量不足",
                            )
                            full_range = plot._full_x_range
                            assert full_range is not None
                            interior = (
                                x0 > float(full_range[0]) + 0.025
                                and x1 < float(full_range[1]) - 0.025
                            )
                            if interior:
                                self.assertAlmostEqual(
                                    anchor_position,
                                    TURN_ON_SLOPE_FOCUS_MIDPOINT_FRACTION,
                                    delta=0.025,
                                )
                        elif turn_on_ls_balanced:
                            required_lo = min(required_times_us)
                            required_hi = max(required_times_us)
                            left_room = required_lo - x0
                            right_room = x1 - required_hi
                            self.assertGreaterEqual(
                                right_room + 0.025,
                                left_room,
                                "Ls_on 右侧稳定平台观察余量不足",
                            )
                            full_range = plot._full_x_range
                            assert full_range is not None
                            interior = (
                                x0 > float(full_range[0]) + 0.025
                                and x1 < float(full_range[1]) - 0.025
                            )
                            if interior:
                                self.assertAlmostEqual(
                                    anchor_position,
                                    TURN_ON_LS_FOCUS_MIDPOINT_FRACTION,
                                    delta=0.025,
                                )
                        elif rr_power_balanced:
                            self.assertGreaterEqual(
                                x1 - max(required_times_us) + 0.025,
                                min(required_times_us) - x0,
                            )
                            self.assertAlmostEqual(
                                anchor_position, RR_POWER_FOCUS_MIDPOINT_FRACTION, delta=0.025
                            )
                        elif rr_err_balanced:
                            self.assertGreaterEqual(
                                x1 - max(required_times_us) + 0.025,
                                min(required_times_us) - x0,
                            )
                            self.assertAlmostEqual(
                                anchor_position, RR_ERR_FOCUS_MIDPOINT_FRACTION, delta=0.025
                            )
                        elif rr_trr_shifted:
                            self.assertGreaterEqual(
                                x1 - max(required_times_us) + 0.025,
                                min(required_times_us) - x0,
                            )
                            full_range = plot._full_x_range
                            assert full_range is not None
                            interior = (
                                x0 > float(full_range[0]) + 0.025
                                and x1 < float(full_range[1]) - 0.025
                            )
                            if interior:
                                self.assertGreaterEqual(
                                    anchor_position,
                                    RR_TRR_ANCHOR_FRACTION - 0.025,
                                )
                        elif tf_balanced:
                            required_lo = min(required_times_us)
                            required_hi = max(required_times_us)
                            left_room = required_lo - x0
                            right_room = x1 - required_hi
                            self.assertGreaterEqual(
                                right_room + 0.025,
                                left_room,
                                "Tf 右侧观察余量不足",
                            )
                            full_range = plot._full_x_range
                            assert full_range is not None
                            interior = (
                                x0 > float(full_range[0]) + 0.025
                                and x1 < float(full_range[1]) - 0.025
                            )
                            if interior:
                                self.assertAlmostEqual(
                                    anchor_position,
                                    TF_FOCUS_MIDPOINT_FRACTION,
                                    delta=0.025,
                                )
                                self.assertLessEqual(
                                    (required_hi - x0) / span_us,
                                    0.50 + 0.025,
                                    "Tf 的 B 不应越过示例构图中线",
                                )
                        else:
                            required_lo = min(required_times_us)
                            required_hi = max(required_times_us)
                            left_room = required_lo - x0
                            right_room = x1 - required_hi
                            self.assertGreaterEqual(
                                right_room + 0.025,
                                left_room,
                                "非门极参数没有把更多动态余量留给右侧震荡",
                            )
                            hard_width = (
                                required_hi
                                - required_lo
                                + 2.0 * PARAM_FOCUS_REQUIRED_GUARD_US
                            )
                            full_range = plot._full_x_range
                            assert full_range is not None
                            interior = (
                                x0 > float(full_range[0]) + 0.025
                                and x1 < float(full_range[1]) - 0.025
                            )
                            if interior and hard_width <= 0.5 * span_us + 1e-9:
                                self.assertLessEqual(
                                    (required_hi - x0) / span_us,
                                    0.50 + 0.025,
                                    "可左置的主物理阶段后端仍越过窗口中线",
                                )

                        cursor_a_us = float(plot._cursor_a.value())
                        cursor_b_us = float(plot._cursor_b.value())
                        if (section, name) == ("反向恢复", "Err"):
                            self.assertEqual(len(required_times_us), 2)
                            self.assertAlmostEqual(
                                min(required_times_us),
                                min(cursor_a_us, cursor_b_us),
                                places=6,
                                msg="Err 局部取景不得在真实 A/B 左侧追加固定时长",
                            )
                            self.assertAlmostEqual(
                                max(required_times_us),
                                max(cursor_a_us, cursor_b_us),
                                places=6,
                                msg="Err 局部取景不得在真实 A/B 右侧追加固定时长",
                            )
                        for label, cursor_us in (("A", cursor_a_us), ("B", cursor_b_us)):
                            cursor_position = (cursor_us - x0) / span_us
                            self.assertGreaterEqual(
                                cursor_position,
                                -1e-6,
                                f"{label} 光标落在局部视窗左侧: {cursor_position:.3%}",
                            )
                            self.assertLessEqual(
                                cursor_position,
                                1.0 + 1e-6,
                                f"{label} 光标落在局部视窗右侧: {cursor_position:.3%}",
                            )

                        self.assertTrue(required_times_us, "局部视图缺少必要守卫时刻")
                        for required_us in required_times_us:
                            required_position = (required_us - x0) / span_us
                            self.assertGreaterEqual(
                                required_position,
                                -1e-6,
                                f"稳定平台/必要守卫点落在视窗左侧: {required_position:.3%}",
                            )
                            self.assertLessEqual(
                                required_position,
                                1.0 + 1e-6,
                                f"稳定平台/必要守卫点落在视窗右侧: {required_position:.3%}",
                            )

                        # 真实 A/B、稳定平台守卫点和事件锚点能一起装入
                        # 2 us 时，不得仅为 65%/3.5 格留白比例扩档。
                        hard_times = (
                            anchor_us,
                            cursor_a_us,
                            cursor_b_us,
                            *required_times_us,
                        )
                        hard_span_us = max(hard_times) - min(hard_times)
                        if (
                            hard_span_us + 2.0 * PARAM_FOCUS_REQUIRED_GUARD_US
                            <= 2.0 + 1e-9
                        ):
                            expected_span_us = (
                                2.5
                                if (section, name)
                                == ("关断过程", "Ic_off_max")
                                else 2.0
                            )
                            self.assertAlmostEqual(
                                span_us,
                                expected_span_us,
                                delta=0.02,
                                msg="参数局部视图未遵守本卡的基准时间轴",
                            )

                        self.assertEqual(result, result_before_focus)

                self.assertEqual(result, result_before_focus)
            finally:
                win.close()
                plot.close()


if __name__ == "__main__":
    unittest.main()
