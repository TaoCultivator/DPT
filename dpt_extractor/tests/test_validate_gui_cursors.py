from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from scripts.validate_gui_cursors import (
    Capture,
    _capture_error_details,
    _captured_parameter_focus,
    _ensure_wanglihui_u_ch3_ui_inversion,
    _err_a_settled_gate_check,
    _err_a_signed_intersection_check,
    _group_rows_by_sample,
    _level_on_channel,
    _sample_trace_id,
    _audit_turn_off_slope_context_consistency,
    _unnecessary_ab_focus_expansion,
)


_CAPTURE_METHODS = (
    "enable_dvdt_interaction",
    "apply_dvdt_ab_times",
    "enable_energy_loss_interaction",
    "enable_irr_peak_interaction",
    "set_interval_peak_on_hb",
    "enable_trr_measure_interaction",
    "enable_turn_on_current_interaction",
    "enable_delta_vce_interaction",
    "enable_crosstalk_interaction",
    "enable_interval_interaction",
    "set_interval_peak_horizontal",
    "set_interval_base_horizontal",
)


class _CapturePlot:
    def focus_parameter_window_us(
        self,
        anchor_us: float,
        *required_times_us: float,
        anchor_fraction: float = 0.12,
    ) -> tuple[float, tuple[float, ...], float]:
        return anchor_us, required_times_us, anchor_fraction


def _ok_method(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
    return args, kwargs


for _method_name in _CAPTURE_METHODS:
    setattr(_CapturePlot, _method_name, _ok_method)


class TestTurnOffSlopeContextAudit(unittest.TestCase):
    def test_exact_gui_context_and_raw_voltage_intersections_pass(self) -> None:
        t = np.asarray([0.0, 1.0e-6, 2.0e-6], dtype=np.float64)
        vce = np.asarray([0.0, 5.0, 10.0], dtype=np.float64)
        t_a_s, t_b_s = 0.2e-6, 1.8e-6

        problems, detail = _audit_turn_off_slope_context_consistency(
            metric_name="dv/dt",
            gui_top=10.0,
            gui_base=0.0,
            gui_ab_us=(t_a_s * 1e6, t_b_s * 1e6),
            context_top=10.0,
            context_base=0.0,
            context_value=0.005,
            context_t_a_s=t_a_s,
            context_t_b_s=t_b_s,
            threshold_a=1.0,
            threshold_b=9.0,
            used_fallback=False,
            result_value=0.005,
            t=t,
            raw_values=vce,
            use_abs=False,
        )

        self.assertEqual(problems, [])
        self.assertIn("used_fallback=False", detail)
        self.assertIn("cross=full", detail)
        self.assertIn("rawAB=1/9", detail)

    def test_exact_negative_current_intersections_use_raw_absolute_signal(self) -> None:
        t = np.asarray([0.0, 1.0e-6, 2.0e-6], dtype=np.float64)
        ic = np.asarray([-10.0, -5.0, 0.0], dtype=np.float64)
        t_a_s, t_b_s = 0.2e-6, 1.8e-6

        problems, detail = _audit_turn_off_slope_context_consistency(
            metric_name="di/dt",
            gui_top=-10.0,
            gui_base=0.0,
            gui_ab_us=(t_a_s * 1e6, t_b_s * 1e6),
            context_top=-10.0,
            context_base=0.0,
            context_value=0.005,
            context_t_a_s=t_a_s,
            context_t_b_s=t_b_s,
            threshold_a=9.0,
            threshold_b=1.0,
            used_fallback=False,
            result_value=0.005,
            t=t,
            raw_values=ic,
            use_abs=True,
        )

        self.assertEqual(problems, [])
        self.assertIn("cross=full", detail)
        self.assertIn("rawAB=9/1", detail)

    def test_mismatched_gui_values_and_raw_a_are_rejected(self) -> None:
        t = np.asarray([0.0, 1.0e-6, 2.0e-6], dtype=np.float64)
        vce = np.asarray([0.0, 5.0, 10.0], dtype=np.float64)

        problems, _detail = _audit_turn_off_slope_context_consistency(
            metric_name="dv/dt",
            gui_top=10.5,
            gui_base=0.0,
            gui_ab_us=(0.3, 1.8),
            context_top=10.0,
            context_base=0.0,
            context_value=0.005,
            context_t_a_s=0.2e-6,
            context_t_b_s=1.8e-6,
            threshold_a=1.0,
            threshold_b=9.0,
            used_fallback=False,
            result_value=0.006,
            t=t,
            raw_values=vce,
            use_abs=False,
        )

        joined = " | ".join(problems)
        self.assertIn("Top", joined)
        self.assertIn("result", joined)
        self.assertIn(" A=", joined)
        self.assertIn("原始A插值", joined)

    def test_fallback_without_intersections_is_recorded_not_failed(self) -> None:
        t = np.asarray([0.0, 1.0e-6], dtype=np.float64)
        values = np.asarray([3.0, 3.0], dtype=np.float64)

        problems, detail = _audit_turn_off_slope_context_consistency(
            metric_name="dv/dt",
            gui_top=3.0,
            gui_base=3.0,
            gui_ab_us=None,
            context_top=3.0,
            context_base=3.0,
            context_value=0.0,
            context_t_a_s=None,
            context_t_b_s=None,
            threshold_a=3.0,
            threshold_b=3.0,
            used_fallback=True,
            result_value=0.0,
            t=t,
            raw_values=values,
            use_abs=False,
        )

        self.assertEqual(problems, [])
        self.assertIn("used_fallback=True", detail)
        self.assertIn("cross=none", detail)
        self.assertIn("rawAB=none", detail)

    def test_fallback_with_partial_intersection_is_recorded_not_failed(self) -> None:
        t = np.asarray([0.0, 1.0e-6], dtype=np.float64)
        values = np.asarray([0.0, 1.0], dtype=np.float64)

        problems, detail = _audit_turn_off_slope_context_consistency(
            metric_name="di/dt",
            gui_top=1.0,
            gui_base=0.0,
            gui_ab_us=None,
            context_top=1.0,
            context_base=0.0,
            context_value=0.001,
            context_t_a_s=0.5e-6,
            context_t_b_s=None,
            threshold_a=0.5,
            threshold_b=0.1,
            used_fallback=True,
            result_value=0.001,
            t=t,
            raw_values=values,
            use_abs=True,
        )

        self.assertEqual(problems, [])
        self.assertIn("used_fallback=True", detail)
        self.assertIn("cross=partial-A", detail)
        self.assertIn("guiAB=none", detail)

    def test_missing_intersections_without_fallback_are_rejected(self) -> None:
        t = np.asarray([0.0, 1.0e-6], dtype=np.float64)
        values = np.asarray([3.0, 3.0], dtype=np.float64)

        problems, detail = _audit_turn_off_slope_context_consistency(
            metric_name="dv/dt",
            gui_top=3.0,
            gui_base=3.0,
            gui_ab_us=None,
            context_top=3.0,
            context_base=3.0,
            context_value=0.0,
            context_t_a_s=None,
            context_t_b_s=None,
            threshold_a=3.0,
            threshold_b=3.0,
            used_fallback=False,
            result_value=0.0,
            t=t,
            raw_values=values,
            use_abs=False,
        )

        self.assertTrue(any("未fallback" in problem for problem in problems))
        self.assertIn("cross=none", detail)


class TestCursorAuditCapture(unittest.TestCase):
    def test_same_basename_in_different_directories_keeps_distinct_trace_ids(
        self,
    ) -> None:
        root = Path.cwd()
        first = root / "示例文件" / "songzhenxi" / "U" / "wave.tss"
        second = root / "示例文件" / "wanglihui" / "U" / "wave.tss"

        first_id = _sample_trace_id(first, root)
        second_id = _sample_trace_id(second, root)

        self.assertNotEqual(first_id, second_id)
        self.assertTrue(first_id.endswith(str(Path("songzhenxi") / "U" / "wave.tss")))
        self.assertTrue(second_id.endswith(str(Path("wanglihui") / "U" / "wave.tss")))

        rows = [
            (first_id, "开通", "Tr", "OK", "first"),
            (second_id, "开通", "Tr", "FAIL", "second"),
        ]
        grouped = _group_rows_by_sample(rows)
        self.assertEqual(set(grouped), {first_id, second_id})
        self.assertEqual(len(grouped), 2)

    def test_capture_error_is_exposed_for_fail_promotion(self) -> None:
        plot = _CapturePlot()

        def broken_focus(
            anchor_us: float,
            *required_times_us: float,
            anchor_fraction: float = 0.12,
        ) -> None:
            _ = anchor_us, required_times_us, anchor_fraction
            raise RuntimeError("focus exploded")

        plot.focus_parameter_window_us = broken_focus  # type: ignore[method-assign]
        capture = Capture()
        capture.install(plot)

        plot.focus_parameter_window_us(10.0, 11.0)

        errors = _capture_error_details(capture.calls)
        self.assertEqual(len(errors), 1)
        self.assertIn("focus_parameter_window_us", errors[0])
        self.assertIn("focus exploded", errors[0])

    def test_focus_capture_uses_actual_anchor_required_times_and_fraction(self) -> None:
        plot = _CapturePlot()
        capture = Capture()
        capture.install(plot)

        plot.focus_parameter_window_us(
            10.25,
            10.5,
            12.75,
            anchor_fraction=0.31,
        )

        self.assertEqual(
            _captured_parameter_focus(capture.calls),
            (10.25, (10.5, 12.75), 0.31),
        )

    def test_cursor_a_b_audit_rejects_search_window_overexpansion(self) -> None:
        problem = _unnecessary_ab_focus_expansion(
            "关断过程",
            "Eoff",
            (22.871, 26.871),
            (0.0, 60.0),
            (23.991, (22.977, 25.015), 0.12),
            24.190,
            24.560,
        )

        self.assertIsNotNone(problem)
        assert problem is not None
        self.assertIn("实际4.000us", problem)
        self.assertIn("真实A/B仅需2.000us", problem)

    def test_cursor_a_b_audit_accepts_compact_default_view(self) -> None:
        problem = _unnecessary_ab_focus_expansion(
            "开通",
            "di/dt",
            (23.431, 25.431),
            (0.0, 60.0),
            (23.991, (24.190, 24.560), 0.12),
            24.190,
            24.560,
        )

        self.assertIsNone(problem)

    def test_cursor_a_b_audit_does_not_constrain_recovery_tail_views(self) -> None:
        problem = _unnecessary_ab_focus_expansion(
            "反向恢复",
            "Trr",
            (27.0, 31.0),
            (0.0, 60.0),
            (28.1, (28.1, 30.9), 0.12),
            28.1,
            28.45,
        )

        self.assertIsNone(problem)

    def test_level_check_preserves_signal_sign(self) -> None:
        values = np.asarray([-30.0, -25.0, -20.0], dtype=np.float64)
        self.assertTrue(_level_on_channel(-24.0, values, 0, 2))
        self.assertFalse(_level_on_channel(24.0, values, 0, 2))

    def test_err_a_signed_intersection_accepts_matching_positive_level(self) -> None:
        t = np.asarray([0.0, 1.0e-6], dtype=np.float64)
        irr = np.asarray([0.0, 0.032564], dtype=np.float64)

        matches, irr_at_a, atol_a = _err_a_signed_intersection_check(
            0.016282,
            0.5e-6,
            t,
            irr,
        )

        self.assertTrue(matches)
        self.assertAlmostEqual(irr_at_a, 0.016282, places=12)
        self.assertLessEqual(atol_a, 1e-5)

    def test_err_a_signed_intersection_rejects_opposite_sign_level(self) -> None:
        t = np.asarray([0.0, 1.0e-6], dtype=np.float64)
        irr = np.asarray([-0.032564, 0.0], dtype=np.float64)

        matches, irr_at_a, atol_a = _err_a_signed_intersection_check(
            0.016282,
            0.5e-6,
            t,
            irr,
        )

        self.assertFalse(matches)
        self.assertAlmostEqual(irr_at_a, -0.016282, places=12)
        self.assertLess(atol_a, abs(0.016282 - (-0.016282)))

    def test_err_a_near_zero_positive_old_early_entry_fails_settled_gate(self) -> None:
        self.assertFalse(
            _err_a_settled_gate_check(
                121.875,
                0.016281512605,
                15.778571318e-6,
                16.128640000e-6,
            )
        )

    def test_err_a_near_zero_positive_new_entry_passes_settled_gate(self) -> None:
        self.assertTrue(
            _err_a_settled_gate_check(
                121.875,
                0.016281512605,
                16.129918449e-6,
                16.128640000e-6,
            )
        )


class _FakeApplication:
    @staticmethod
    def processEvents() -> None:
        return None


class _InversionPlot:
    def __init__(self, owner, enabled: bool) -> None:  # noqa: ANN001
        self.owner = owner
        self.enabled = enabled
        self.setter_calls = 0

    def channel_inversion_enabled(self, key: str) -> bool:
        self.assert_key(key)
        return self.enabled

    def set_channel_inversion_enabled(self, key: str, enabled: bool) -> str:
        self.assert_key(key)
        self.setter_calls += 1
        self.enabled = bool(enabled)
        if enabled:
            self.owner.bundle.meta.channel_display_inversions.add("CH3")
        else:
            self.owner.bundle.meta.channel_display_inversions.discard("CH3")
        self.owner._recalculate(reset_manual=False)
        return "CH3"

    @staticmethod
    def assert_key(key: str) -> None:
        if key != "CH3":
            raise AssertionError(key)


class _InversionWindow:
    def __init__(self, *, source_inverted: bool) -> None:
        source = {"CH3"} if source_inverted else set()
        display = set(source)
        self.bundle = SimpleNamespace(
            meta=SimpleNamespace(
                source_channel_inversions=source,
                channel_display_inversions=display,
            )
        )
        self.result = object()
        self.recalculate_calls = 0
        self.wave_plot = _InversionPlot(self, enabled=source_inverted)

    def _recalculate(self, *, reset_manual: bool) -> None:
        self.assertFalse(reset_manual)
        self.recalculate_calls += 1
        self.result = object()

    @staticmethod
    def assertFalse(value: bool) -> None:
        if value:
            raise AssertionError(value)


class TestWanglihuiInversionAudit(unittest.TestCase):
    path = Path("samples") / "wanglihui" / "U" / "wave.tss"

    def test_uh_enables_display_inversion_through_ui_path(self) -> None:
        window = _InversionWindow(source_inverted=False)

        note = _ensure_wanglihui_u_ch3_ui_inversion(
            window, _FakeApplication, self.path
        )

        self.assertEqual(window.wave_plot.setter_calls, 1)
        self.assertEqual(window.recalculate_calls, 1)
        self.assertEqual(window.bundle.meta.source_channel_inversions, set())
        self.assertEqual(window.bundle.meta.channel_display_inversions, {"CH3"})
        self.assertIn("UI手动反相", note)

    def test_source_inverted_ul_recalculates_without_second_toggle(self) -> None:
        window = _InversionWindow(source_inverted=True)

        note = _ensure_wanglihui_u_ch3_ui_inversion(
            window, _FakeApplication, self.path
        )

        self.assertEqual(window.wave_plot.setter_calls, 0)
        self.assertEqual(window.recalculate_calls, 1)
        self.assertEqual(window.bundle.meta.source_channel_inversions, {"CH3"})
        self.assertEqual(window.bundle.meta.channel_display_inversions, {"CH3"})
        self.assertIn("未二次翻转", note)


if __name__ == "__main__":
    unittest.main()
