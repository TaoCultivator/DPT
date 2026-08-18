from __future__ import annotations

import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from scripts.validate_gui_cursors import (
    Capture,
    DPT_ENDPOINT_CHANNELS,
    DPT_HORIZONTAL_BINDINGS,
    DPT_PARAMETER_CURSOR_ROLES,
    GENERIC_MAX_ENDPOINT_CHANNELS,
    IEC_TIMING_ENDPOINT_CHANNELS,
    INTERACTIVE_PARAMS,
    _capture_error_details,
    _audit_waveform_marker_bindings,
    _captured_parameter_focus,
    _captured_cursor_bindings,
    _ensure_wanglihui_u_ch3_ui_inversion,
    _err_a_settled_gate_check,
    _err_a_signed_intersection_check,
    _group_rows_by_sample,
    _level_on_channel,
    _parameter_focus_geometry_problem,
    _sample_trace_id,
    _selected_sample_waveforms,
    _short_exact_vi_energy,
    _short_unavailable_audit_status,
    _ab_role_binding_problems,
    _cursor_level_binding_problem,
    _err_signed_cursor_text_problems,
    _audit_turn_off_slope_context_consistency,
    _unnecessary_ab_focus_expansion,
    audit_file,
    audit_short_circuit_file,
    SHORT_CIRCUIT_PARAMS,
    SHORT_CIRCUIT_REQUIRED_PARAMS,
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
    "enable_short_current_interaction",
    "set_interval_peak_horizontal",
    "set_interval_base_horizontal",
    "set_interval_minmax_horizontal",
    "disable_interactive_cursors",
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


def _short_capture_method(
    self,  # noqa: ANN001
    search_t0_us: float,
    search_t1_us: float,
    t_a_us: float,
    t_b_us: float,
    hb: float,
    ha: float,
    on_change,  # noqa: ANN001
    *,
    channel: str = "ic",
    emit_result_on_enter: bool = False,
):
    return (
        search_t0_us,
        search_t1_us,
        t_a_us,
        t_b_us,
        hb,
        ha,
        on_change,
        channel,
        emit_result_on_enter,
    )


_CapturePlot.enable_short_current_interaction = _short_capture_method


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
    def test_waveform_marker_audit_captures_derived_sources_and_restores_mode(
        self,
    ) -> None:
        class _Cursor:
            def __init__(self, value: float) -> None:
                self._value = float(value)

            def value(self) -> float:
                return self._value

        class _Marker:
            def __init__(self) -> None:
                self.x = np.asarray([], dtype=np.float64)
                self.y = np.asarray([], dtype=np.float64)
                self.visible = False

            def getData(self):
                return self.x, self.y

            def isVisible(self) -> bool:
                return self.visible

        class _DerivedMarkerPlot:
            def __init__(
                self,
                *,
                bad_a_x: bool = False,
                bad_b_y: bool = False,
            ) -> None:
                self._cursor_type = "both"
                self._trace_t_us = np.asarray([0.0, 1.0, 2.0])
                self._raw = {
                    "irr": np.asarray([-10.0, -20.0, -30.0]),
                    "ic": np.asarray([2.0, 4.0, 6.0]),
                }
                self._cursor_a = _Cursor(0.5)
                self._cursor_b = _Cursor(1.5)
                self._cursor_a_wave_marker = _Marker()
                self._cursor_b_wave_marker = _Marker()
                self.bad_a_x = bool(bad_a_x)
                self.bad_b_y = bool(bad_b_y)
                self.refresh_modes = []
                self.visibility_refreshes = 0

            def cursor_type(self) -> str:
                return self._cursor_type

            @staticmethod
            def _display_key_for_channel(channel: str) -> str:
                return {"irr": "LOGIC_IRR", "ic": "LOGIC_IC"}[channel]

            def _cursor_value_raw(self, channel: str):
                return self._raw[channel]

            @staticmethod
            def _to_disp(channel: str, value: float) -> float:
                offset = 1.0 if channel == "irr" else -2.0
                return float(value) * 0.1 + offset

            def _update_waveform_cursor_markers(self) -> None:
                self.refresh_modes.append(self._cursor_type)
                markers = (
                    (
                        "irr",
                        self._cursor_a,
                        self._cursor_a_wave_marker,
                        self.bad_a_x,
                        False,
                    ),
                    (
                        "ic",
                        self._cursor_b,
                        self._cursor_b_wave_marker,
                        False,
                        self.bad_b_y,
                    ),
                )
                for channel, cursor, marker, bad_x, bad_y in markers:
                    if self._cursor_type != "waveform":
                        marker.visible = False
                        continue
                    t_us = float(cursor.value())
                    raw = float(np.interp(t_us, self._trace_t_us, self._raw[channel]))
                    y = self._to_disp(channel, raw) + (1.0 if bad_y else 0.0)
                    marker.x = np.asarray([t_us + (0.25 if bad_x else 0.0)])
                    marker.y = np.asarray([y])
                    marker.visible = True

            def _apply_cursor_visibility(self) -> None:
                self.visibility_refreshes += 1

        plot = _DerivedMarkerPlot()
        self.assertEqual(
            _audit_waveform_marker_bindings(plot, ("irr", "ic")),
            [],
        )
        self.assertEqual(plot._cursor_type, "both")
        self.assertEqual(plot.refresh_modes, ["waveform", "both"])
        self.assertEqual(plot.visibility_refreshes, 1)

        bad_plot = _DerivedMarkerPlot(bad_b_y=True)
        problems = _audit_waveform_marker_bindings(bad_plot, ("irr", "ic"))
        self.assertTrue(
            any("B(LOGIC_IC)标记Y" in problem for problem in problems),
            problems,
        )
        self.assertEqual(bad_plot._cursor_type, "both")

        bad_x_plot = _DerivedMarkerPlot(bad_a_x=True)
        problems = _audit_waveform_marker_bindings(bad_x_plot, ("irr", "ic"))
        self.assertTrue(
            any("A(LOGIC_IRR)标记X" in problem for problem in problems),
            problems,
        )

    def test_err_signed_text_audit_checks_top_and_beside_line_readouts(self) -> None:
        class _Plot:
            def __init__(self, top: str, ha: str, hb: str) -> None:
                self._readout_label = SimpleNamespace(text=lambda: top)
                self._cursor_ha_v_label = SimpleNamespace(
                    textItem=SimpleNamespace(toPlainText=lambda: ha)
                )
                self._cursor_hb_v_label = SimpleNamespace(
                    textItem=SimpleNamespace(toPlainText=lambda: hb)
                )

            @staticmethod
            def _update_readout() -> None:
                return None

        correct = _Plot(
            "<span>[Irr] Ha -12.50A</span> <span>[Vd] Hb +620.00V</span>",
            "[Irr] Ha: -12.500 A",
            "[Vd] Hb: 620.000 V",
        )
        self.assertEqual(
            _err_signed_cursor_text_problems(correct, -12.5, 620.0),
            [],
        )

        wrong = _Plot(
            "<span>[Irr] Ha +12.50A</span> <span>[Vd] Hb -620.00V</span>",
            "[Irr] Ha: 12.500 A",
            "[Vd] Hb: -620.000 V",
        )
        problems = _err_signed_cursor_text_problems(wrong, -12.5, 620.0)
        joined = " | ".join(problems)
        self.assertIn("Err顶部读数Ha文本符号", joined)
        self.assertIn("Err顶部读数Hb文本符号", joined)
        self.assertIn("Err横线旁读数Ha文本符号", joined)
        self.assertIn("Err横线旁读数Hb文本符号", joined)

    def test_capture_reads_interval_endpoint_channels(self) -> None:
        class _EndpointCapturePlot(_CapturePlot):
            def enable_interval_interaction(
                self,
                start_t_us,
                end_t_us,
                on_change,
                show_horizontal_peak=False,
                *,
                mode="interval",
                channel=None,
                a_channel=None,
                b_channel=None,
                on_horizontal_change=None,
            ):
                return None

        plot = _EndpointCapturePlot()
        capture = Capture()
        capture.install(plot)
        plot.enable_interval_interaction(
            1.0,
            2.0,
            None,
            channel="ic",
            a_channel="vge",
            b_channel="ic",
        )

        self.assertEqual(
            _captured_cursor_bindings(capture.calls),
            {
                "a_us": 1.0,
                "b_us": 2.0,
                "a_channel": "vge",
                "b_channel": "ic",
            },
        )

    def test_capture_binding_normalizes_real_ab_ha_hb_roles(self) -> None:
        calls = {
            "enable_turn_on_current_interaction": {
                "bound": {
                    "t_a_us": 1.0,
                    "t_b_us": 2.0,
                    "hb": 10.0,
                    "ha": 100.0,
                }
            }
        }
        self.assertEqual(
            _captured_cursor_bindings(calls),
            {
                "a_us": 1.0,
                "b_us": 2.0,
                "a_channel": "ic",
                "b_channel": "ic",
                "ha": (100.0, "ic"),
                "hb": (10.0, "ic"),
            },
        )

    def test_dpt_parameter_cursor_role_matrix_covers_every_card(self) -> None:
        self.assertEqual(
            set(DPT_PARAMETER_CURSOR_ROLES),
            set(INTERACTIVE_PARAMS),
        )
        for key, roles in DPT_PARAMETER_CURSOR_ROLES.items():
            with self.subTest(parameter=key):
                for token in ("A", "B", "Ha", "Hb"):
                    self.assertIn(token, roles)

        self.assertIn("Vge", DPT_PARAMETER_CURSOR_ROLES[("关断过程", "Ic_off_max")])
        self.assertIn("A=Ic", DPT_PARAMETER_CURSOR_ROLES[("开通", "Ic_on_max")])
        self.assertIn("B=Vce", DPT_PARAMETER_CURSOR_ROLES[("开通", "Ic_on_max")])
        self.assertIn("A=Vge", DPT_PARAMETER_CURSOR_ROLES[("开通", "Vce_on_max")])
        self.assertIn("B=Vce", DPT_PARAMETER_CURSOR_ROLES[("开通", "Vce_on_max")])

    def test_dpt_endpoint_and_horizontal_matrices_fail_closed(self) -> None:
        dynamic_power = {
            ("关断过程", "Pmax"),
            ("开通", "Pmax"),
            ("反向恢复", "Pdmax"),
        }
        expected = set(INTERACTIVE_PARAMS)
        self.assertEqual(set(DPT_ENDPOINT_CHANNELS) | dynamic_power, expected)
        self.assertEqual(set(DPT_HORIZONTAL_BINDINGS) | dynamic_power, expected)

    def test_endpoint_channel_matrices_match_production_contract(self) -> None:
        self.assertEqual(
            IEC_TIMING_ENDPOINT_CHANNELS,
            {
                ("开通", "Ton"): ("vge", "ic"),
                ("开通", "Td_on"): ("vge", "ic"),
                ("开通", "Tr"): ("ic", "ic"),
                ("关断过程", "Toff"): ("vge", "ic"),
                ("关断过程", "Td_off"): ("vge", "ic"),
                ("关断过程", "Tf"): ("ic", "ic"),
            },
        )
        self.assertEqual(
            GENERIC_MAX_ENDPOINT_CHANNELS,
            {
                ("关断过程", "Ic_off_max"): ("vge", "vge"),
                ("关断过程", "Vce_off_max"): ("vce", "vce"),
                ("开通", "Ic_on_max"): ("ic", "vce"),
                ("开通", "Vce_on_max"): ("vge", "vce"),
                ("反向恢复", "Vrr"): ("v_diode", "v_diode"),
            },
        )

    def test_ab_role_binding_fails_mismatched_card_times(self) -> None:
        self.assertEqual(
            _ab_role_binding_problems(
                1.0,
                2.0,
                (1.0, 2.0),
                role_text="A=Vge;B=Ic",
            ),
            [],
        )
        problems = _ab_role_binding_problems(
            1.1,
            2.0,
            (1.0, 2.0),
            role_text="A=Vge;B=Ic",
        )
        self.assertTrue(any(problem.startswith("A=") for problem in problems))

    def test_cursor_level_binding_checks_waveform_at_cursor_time(self) -> None:
        t = np.asarray([0.0, 1e-6, 2e-6], dtype=np.float64)
        values = np.asarray([0.0, 10.0, 20.0], dtype=np.float64)
        self.assertIsNone(
            _cursor_level_binding_problem(
                "A/Ha", 1.0, 10.0, t, values, floor=1e-6
            )
        )
        self.assertIsNotNone(
            _cursor_level_binding_problem(
                "A/Ha", 1.0, 15.0, t, values, floor=1e-6
            )
        )

    def test_short_required_unavailable_metrics_are_fail_closed(self) -> None:
        self.assertEqual(
            SHORT_CIRCUIT_REQUIRED_PARAMS,
            {
                "短路电流Imax",
                "短路时间Tsc",
                "短路能量Esc_本管",
            },
        )
        for name in SHORT_CIRCUIT_REQUIRED_PARAMS:
            self.assertEqual(_short_unavailable_audit_status(name), "FAIL")
        for name in {
            "应力Vpeak_本管",
            "短路能量Esc_对管",
            "应力Vpeak_对管",
            "Desat动作时间",
        }:
            self.assertEqual(_short_unavailable_audit_status(name), "INFO")

    def test_short_energy_audit_uses_interpolated_cursor_endpoints(self) -> None:
        t = np.asarray([0.0, 1e-6, 2e-6, 3e-6], dtype=np.float64)
        current = np.full(4, 2.0, dtype=np.float64)
        voltage = np.full(4, 3.0, dtype=np.float64)

        energy = _short_exact_vi_energy(
            t,
            current,
            voltage,
            0.25,
            2.75,
        )

        self.assertAlmostEqual(energy, 15e-6, places=15)

    def test_capture_records_real_short_current_signature(self) -> None:
        plot = _CapturePlot()
        capture = Capture()
        capture.install(plot)

        plot.enable_short_current_interaction(
            0.0,
            5.0,
            0.5,
            4.5,
            1.25,
            1200.0,
            lambda *_args: None,
            channel="ic",
            emit_result_on_enter=False,
        )

        bound = capture.calls["enable_short_current_interaction"]["bound"]
        self.assertEqual(bound["t_a_us"], 0.5)
        self.assertEqual(bound["t_b_us"], 4.5)
        self.assertEqual(bound["hb"], 1.25)
        self.assertEqual(bound["ha"], 1200.0)
        self.assertEqual(bound["channel"], "ic")

    def test_all_cursor_selection_includes_short_samples_and_paginates(self) -> None:
        root = Path.cwd()
        dpt_a = root / "示例文件" / "samples" / "UH_750V_1000A_000.tss"
        short = root / "示例文件" / "samples" / "short" / "UH_750V_000.tss"
        dpt_b = root / "示例文件" / "samples" / "UL_750V_1000A_000.tss"
        discovered = [dpt_a, short, dpt_b]

        with patch(
            "scripts.validate_gui_cursors.discover_sample_waveforms",
            return_value=discovered,
        ), patch.dict(
            os.environ,
            {
                "DPT_VALIDATE_ALL_CURSORS": "1",
                "DPT_VALIDATE_CURSOR_OFFSET": "1",
                "DPT_VALIDATE_CURSOR_LIMIT": "2",
            },
            clear=False,
        ):
            selected = _selected_sample_waveforms(root)

        self.assertEqual(selected, [short, dpt_b])

    def test_default_cursor_selection_excludes_short_samples(self) -> None:
        root = Path.cwd()
        dpt = root / "示例文件" / "samples" / "UH_750V_1000A_000.tss"
        short = root / "示例文件" / "samples" / "short" / "UH_750V_000.tss"
        with patch(
            "scripts.validate_gui_cursors.discover_sample_waveforms",
            return_value=[short, dpt],
        ), patch.dict(os.environ, {}, clear=False):
            old = os.environ.pop("DPT_VALIDATE_ALL_CURSORS", None)
            try:
                selected = _selected_sample_waveforms(root)
            finally:
                if old is not None:
                    os.environ["DPT_VALIDATE_ALL_CURSORS"] = old

        self.assertEqual(selected, [dpt])

    def test_default_cursor_selection_supports_bounded_pagination(self) -> None:
        root = Path.cwd()
        first = root / "示例文件" / "samples" / "UH_750V_1000A_000.tss"
        second = root / "示例文件" / "samples" / "UL_750V_1000A_000.tss"
        third = root / "示例文件" / "samples" / "WH_750V_1000A_000.tss"
        with patch(
            "scripts.validate_gui_cursors.discover_sample_waveforms",
            return_value=[first, second, third],
        ), patch(
            "scripts.validate_gui_cursors.DEFAULT_SAMPLE_FRAGMENTS",
            (),
        ), patch.dict(
            os.environ,
            {
                "DPT_VALIDATE_CURSOR_OFFSET": "1",
                "DPT_VALIDATE_CURSOR_LIMIT": "1",
            },
            clear=False,
        ):
            old = os.environ.pop("DPT_VALIDATE_ALL_CURSORS", None)
            try:
                selected = _selected_sample_waveforms(root)
            finally:
                if old is not None:
                    os.environ["DPT_VALIDATE_ALL_CURSORS"] = old

        self.assertEqual(selected, [second])

    def test_short_only_cursor_selection_filters_before_pagination(self) -> None:
        root = Path.cwd()
        dpt = root / "示例文件" / "samples" / "UH_750V_1000A_000.tss"
        short_a = root / "示例文件" / "samples" / "short" / "UH_750V_000.tss"
        short_b = root / "示例文件" / "samples" / "DDD" / "UL_750V_000.tss"
        with patch(
            "scripts.validate_gui_cursors.discover_sample_waveforms",
            return_value=[dpt, short_a, short_b],
        ), patch.dict(
            os.environ,
            {
                "DPT_VALIDATE_ALL_CURSORS": "1",
                "DPT_VALIDATE_SHORT_ONLY": "1",
                "DPT_VALIDATE_CURSOR_OFFSET": "1",
                "DPT_VALIDATE_CURSOR_LIMIT": "1",
            },
            clear=False,
        ):
            selected = _selected_sample_waveforms(root)

        self.assertEqual(selected, [short_b])

    def test_dpt_only_cursor_selection_filters_before_pagination(self) -> None:
        root = Path.cwd()
        dpt_a = root / "示例文件" / "samples" / "UH_750V_1000A_000.tss"
        short = root / "示例文件" / "samples" / "short" / "UH_750V_000.tss"
        dpt_b = root / "示例文件" / "samples" / "UL_750V_1000A_000.tss"
        with patch(
            "scripts.validate_gui_cursors.discover_sample_waveforms",
            return_value=[dpt_a, short, dpt_b],
        ), patch.dict(
            os.environ,
            {
                "DPT_VALIDATE_ALL_CURSORS": "1",
                "DPT_VALIDATE_DPT_ONLY": "1",
                "DPT_VALIDATE_CURSOR_OFFSET": "1",
                "DPT_VALIDATE_CURSOR_LIMIT": "1",
            },
            clear=False,
        ):
            selected = _selected_sample_waveforms(root)

        self.assertEqual(selected, [dpt_b])

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

    def test_focus_geometry_accepts_required_time_shift_from_preferred_anchor(self) -> None:
        problem = _parameter_focus_geometry_problem(
            (13.99272, 15.99272),
            (0.0, 30.0),
            (
                14.451282777854443,
                (14.012719999925231, 15.776319999917897),
                0.12,
            ),
        )

        self.assertIsNone(problem)

    def test_focus_geometry_rejects_view_that_ignores_required_time_shift(self) -> None:
        problem = _parameter_focus_geometry_problem(
            (14.21128, 16.21128),
            (0.0, 30.0),
            (
                14.451282777854443,
                (14.012719999925231, 15.776319999917897),
                0.12,
            ),
        )

        self.assertIsNotNone(problem)
        assert problem is not None
        self.assertIn("构图偏离策略", problem)

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
    uploaded_uh_path = (
        Path("samples")
        / "wanglihui"
        / "20260729"
        / "UH_RT_Rgon3.33R_Rgoff8.92R"
        / "UH_750V_950A_000.tss"
    )

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

    def test_uploaded_batch_uh_uses_the_same_ui_inversion_path(self) -> None:
        window = _InversionWindow(source_inverted=False)

        note = _ensure_wanglihui_u_ch3_ui_inversion(
            window, _FakeApplication, self.uploaded_uh_path
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


class TestShortCircuitGuiAudit(unittest.TestCase):
    sample = (
        Path(__file__).resolve().parents[2]
        / "示例文件"
        / "songzhenxi"
        / "KSU2506"
        / "DCU"
        / "DL"
        / "LT"
        / "UH_480V_000.tss"
    )

    @unittest.skipUnless(sample.exists(), "representative short-circuit sample missing")
    def test_real_short_branch_exercises_every_parameter_row(self) -> None:
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        rows = audit_short_circuit_file(
            MainWindow,
            QApplication,
            app,
            self.sample,
        )
        by_name = {row[2]: row for row in rows}

        self.assertEqual(set(by_name), set(SHORT_CIRCUIT_PARAMS))
        for name in (
            "短路电流Imax",
            "短路时间Tsc",
            "短路能量Esc_本管",
            "短路能量Esc_对管",
        ):
            self.assertEqual(by_name[name][3], "OK", by_name[name][4])
        for name in ("应力Vpeak_本管", "应力Vpeak_对管"):
            self.assertNotEqual(by_name[name][3], "INFO", by_name[name][4])
        self.assertIn(by_name["Desat动作时间"][3], {"OK", "INFO"})


class TestRrDvdtLateSettledPlatformGuiAudit(unittest.TestCase):
    sample = (
        Path(__file__).resolve().parents[2]
        / "示例文件"
        / "songzhenxi"
        / "KSU2506"
        / "DCU"
        / "SMC"
        / "LT"
        / "tss"
        / "WL_450V_800A_000.tss"
    )

    @unittest.skipUnless(sample.exists(), "late-settling RR sample missing")
    def test_rr_platform_after_compact_window_is_not_rejected(self) -> None:
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        with patch.dict(
            os.environ,
            {"DPT_VALIDATE_CURSOR_METRIC": "反向恢复/dv/dt"},
        ):
            rows = audit_file(MainWindow, QApplication, app, self.sample)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1:3], ("反向恢复", "dv/dt"))
        self.assertEqual(rows[0][3], "OK", rows[0][4])
        self.assertIn("Ha=438.03", rows[0][4])


class TestStablePlatformsOutsideCompactCrossingWindow(unittest.TestCase):
    sample = (
        Path(__file__).resolve().parents[2]
        / "示例文件"
        / "wanglihui"
        / "20260729"
        / "UH_HT_Rgon3.33R_Rgoff8.92R"
        / "UH_400V_1070A_Rgon3.33R_Rgoff8.92R_000.tss"
    )

    @unittest.skipUnless(sample.exists(), "slow stable-platform sample missing")
    def test_dvdt_platforms_need_not_be_inside_compact_ab_window(self) -> None:
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        with patch.dict(
            os.environ,
            {
                "DPT_VALIDATE_CURSOR_METRIC": (
                    "开通/dv/dt|反向恢复/dv/dt"
                )
            },
        ):
            rows = audit_file(MainWindow, QApplication, app, self.sample)

        self.assertEqual(len(rows), 2)
        self.assertEqual({row[1:3] for row in rows}, {
            ("开通", "dv/dt"),
            ("反向恢复", "dv/dt"),
        })
        for row in rows:
            self.assertEqual(row[3], "OK", row[4])


class TestTrrExtendedWindowGuiAudit(unittest.TestCase):
    sample = (
        Path(__file__).resolve().parents[2]
        / "示例文件"
        / "songzhenxi"
        / "KSU2577"
        / "SSM1R7PB12B3DTFMMSPP25M4CF0016"
        / "SSS"
        / "LT"
        / "tss"
        / "VL-750V-1050A_000.tss"
    )

    @unittest.skipUnless(sample.exists(), "extended-window Trr sample missing")
    def test_trr_audit_uses_authoritative_extended_marker_window(self) -> None:
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        rows = audit_file(MainWindow, QApplication, app, self.sample)
        trr_rows = [row for row in rows if row[1:3] == ("反向恢复", "Trr")]

        self.assertEqual(len(trr_rows), 1)
        self.assertEqual(trr_rows[0][3], "OK", trr_rows[0][4])
        self.assertIn("stable=Ha=-52.47", trr_rows[0][4])
        self.assertIn("HbPeak=72.5", trr_rows[0][4])
        self.assertIn("A=17.304 B=17.334", trr_rows[0][4])


class TestTurnOffDeltaVceExtendedPlatformGuiAudit(unittest.TestCase):
    sample = (
        Path(__file__).resolve().parents[2]
        / "示例文件"
        / "likangkang"
        / "24B6-20260709"
        / "RT"
        / "u"
        / "uh-900v-693.37a_000.tss"
    )

    @unittest.skipUnless(sample.exists(), "extended blocking-platform sample missing")
    def test_delta_vce_audit_uses_declared_parameter_search_window(self) -> None:
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        rows = audit_file(MainWindow, QApplication, app, self.sample)
        delta_rows = [
            row
            for row in rows
            if row[1:3] == ("关断过程", "ΔVce")
        ]
        ls_rows = [row for row in rows if row[1:3] == ("关断过程", "Ls_off")]

        self.assertEqual(len(delta_rows), 1)
        for row in delta_rows:
            self.assertEqual(row[3], "OK", row[4])
            self.assertIn("B/Hb=9.386us/895.3V", row[4])
        self.assertEqual(len(ls_rows), 1)
        self.assertEqual(ls_rows[0][3], "OK", ls_rows[0][4])
        self.assertIn("ch=ic", ls_rows[0][4])
        self.assertIn("area=", ls_rows[0][4])


class TestTurnOnDeltaVcePreRiseTopGuiAudit(unittest.TestCase):
    sample = (
        Path(__file__).resolve().parents[2]
        / "示例文件"
        / "likangkang"
        / "24B6-20260709"
        / "HT"
        / "w"
        / "wh-900v-494.9a_000.tss"
    )

    @unittest.skipUnless(sample.exists(), "pre-rise Top sample missing")
    def test_delta_vce_search_window_contains_its_default_top_cursor(self) -> None:
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        rows = audit_file(MainWindow, QApplication, app, self.sample)
        delta_rows = [
            row
            for row in rows
            if row[1:3] == ("开通", "ΔVce")
        ]
        ls_rows = [row for row in rows if row[1:3] == ("开通", "Ls_on")]

        self.assertEqual(len(delta_rows), 1)
        for row in delta_rows:
            self.assertEqual(row[3], "OK", row[4])
            self.assertIn("A/Ha=7.883us/906.6V", row[4])
        self.assertEqual(len(ls_rows), 1)
        self.assertEqual(ls_rows[0][3], "OK", ls_rows[0][4])
        self.assertIn("ch=ic", ls_rows[0][4])
        self.assertIn("area=", ls_rows[0][4])


if __name__ == "__main__":
    unittest.main()
