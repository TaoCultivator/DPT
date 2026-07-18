"""GUI 启动+光标交互的轻量自检（无界面，使用 offscreen Qt）。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
from dpt_extractor.tests.sample_paths import sample_tss

WH = sample_tss("WH_480V_800A_000.tss")
UH = sample_tss("UH_750V_1050A_000.tss")
SMC_RT_UH = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "UH_750V_1048A_000.tss"
)
SMC_RT_UL = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "UL_750V_1048A_000.tss"
)
SMC_RT_UL_806 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "UL_750V_806A_000.tss"
)
SMC_RT_UL_403 = (
    ROOT
    / "示例文件"
    / "tss格式"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "UL_600V_403A_000.tss"
)
SONG_SMC_HT_WL_1048 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "HT"
    / "tss"
    / "WL_750V_1048A_000.tss"
)
SONG_SMC_RT_UH_1048 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "RT"
    / "tss"
    / "UH_750V_1048A_000.tss"
)
SONG_SMC_HT_20260717_UH_1048 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "HT"
    / "UH_750V_1048A_000.tss"
)
OTHER_360A = ROOT / "示例文件" / "其他数据" / "360A.tss"
SONG_DCU_RT_WL_480_1000 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2506"
    / "DCU"
    / "SMC"
    / "RT"
    / "tss"
    / "WL_480V_1000A_000.tss"
)
SONG_DCU_LT_WH_450_800 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2506"
    / "DCU"
    / "SMC"
    / "LT"
    / "tss"
    / "WH_450V_800A_000.tss"
)
SONG_DCU_LT_WH_530_800 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2506"
    / "DCU"
    / "SMC"
    / "LT"
    / "tss"
    / "WH_530V_800A_000.tss"
)
WANGLIHUI_UH_400_1070 = (
    ROOT
    / "示例文件"
    / "wanglihui"
    / "U"
    / "UH_400V_1070A_Rgon1.515R_Rgoff6.346R_000.tss"
)
WANGLIHUI_UL_400_1070 = (
    ROOT
    / "示例文件"
    / "wanglihui"
    / "U"
    / "UL_400V_1070A_Rgon1.1R_Rgof5R_000.tss"
)
WANGLIHUI_UL_486_985 = (
    ROOT
    / "示例文件"
    / "wanglihui"
    / "U"
    / "UL_486V_985A_Rgon1.1R_Rgof5R_000.tss"
)
WANGLIHUI_UH_486_985 = (
    ROOT
    / "示例文件"
    / "wanglihui"
    / "U"
    / "UH_486V_985A_Rgon2.88R_Rgoff6.21R_000.tss"
)
WANGLIHUI_UH_486_985_FAST = (
    ROOT
    / "示例文件"
    / "wanglihui"
    / "U"
    / "UH_486V_985A_Rgon1.515R_Rgoff6.346R_000.tss"
)
SHORT_VH_750 = (
    ROOT
    / "示例文件"
    / "likangkang"
    / "NED34jixian"
    / "short"
    / "750v-vh-short-25c_000.tss"
)
LIKANG_UH_930_REVERSED_TD_ON = (
    ROOT
    / "示例文件"
    / "likangkang"
    / "NED34jixian"
    / "uh"
    / "915v-uh-930a-10.8us-25c_000.tss"
)
WANGLIHUI_SLOW_TURN_ON_CASES = (
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "U"
        / "UH_400V_1070A_Rgon2.88R_Rgoff6.21R_000.tss",
        498.734,
        85.105,
    ),
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "U"
        / "UH_486V_1035A_Rgon2.88R_Rgoff6.21R_000.tss",
        489.155,
        83.571,
    ),
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "U"
        / "UH_486V_985A_Rgon2.88R_Rgoff6.21R_000.tss",
        488.207,
        80.422,
    ),
)


class TestWaveformImportAutoCenter(unittest.TestCase):
    """导入时 (min+max)/2 对齐 0 格；不依赖 WH/UH 样例文件。"""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_tss_scope_ypos_sets_initial_zero_offsets(self):
        """TSS 中的示波器 yPosition 是该通道 0 刻度的初始位置。"""
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 100
        t = np.linspace(0, 1e-6, n)
        profile = make_profile("W", "lower")
        bundle = WaveformBundle(
            t=t,
            channels={
                profile.vge: np.linspace(2.0, 12.0, n),
                profile.vce: np.linspace(100.0, 500.0, n),
                profile.ic: np.linspace(-50.0, 450.0, n),
                profile.il: np.linspace(0.0, 100.0, n),
                profile.v_diode: np.linspace(50.0, 150.0, n),
                profile.vge_other: np.linspace(0.0, 8.0, n),
            },
            meta=TekMetadata(
                source_path="/fake/session.tss",
                channel_vdiv={
                    profile.vge: 5.0,
                    profile.vce: 200.0,
                    profile.ic: 200.0,
                },
                channel_y_position={
                    profile.vge: -0.6,
                    profile.vce: -3.54,
                    profile.ic: 2.5,
                },
            ),
        )
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)
        expected_offsets = {
            "vge": -0.6,
            "vce": -3.54,
            "ic": 2.5,
        }
        for key, expected in expected_offsets.items():
            display_key = plot._display_key_for_channel(key)
            self.assertAlmostEqual(plot._disp_offset[display_key], expected, places=6)
            self.assertAlmostEqual(
                plot._zero_handle_display_y(display_key),
                expected,
                places=6,
                msg=key,
            )

    def _make_synthetic_bundle(self):
        import numpy as np

        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 200
        t = np.linspace(0, 1e-6, n)
        profile = make_profile("W", "lower")
        bundle = WaveformBundle(
            t=t,
            channels={
                profile.vge: np.linspace(-5.0, 15.0, n),
                profile.vce: np.linspace(0.0, 1200.0, n),
                profile.ic: np.linspace(-100.0, 900.0, n),
                profile.il: np.linspace(-50.0, 450.0, n),
                profile.v_diode: np.linspace(0.0, 800.0, n),
                profile.vge_other: np.linspace(-10.0, 10.0, n),
                "MATH1": np.linspace(0.0, 1.0, n),
            },
            meta=TekMetadata(
                source_path="/fake/synthetic.tss",
                channel_labels={
                    "CH3": "Irr",
                    "MATH1": "Ic",
                },
            ),
        )
        return bundle, profile

    def _make_synthetic_plot(self):
        from dpt_extractor.gui.waveform_plot import WaveformPlot

        bundle, profile = self._make_synthetic_bundle()
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)
        return plot

    def test_interval_cursor_endpoints_can_bind_different_waveforms(self):
        plot = self._make_synthetic_plot()
        try:
            plot.enable_interval_interaction(
                0.2,
                0.8,
                lambda *_args: None,
                channel="ic",
                a_channel="vge",
                b_channel="vce",
            )
            plot.set_cursor_type("waveform")
            plot._update_readout()
            self.assertEqual(plot._interval_a_channel, "vge")
            self.assertEqual(plot._interval_b_channel, "vce")
            assert plot._cursor_a is not None and plot._cursor_b is not None
            assert plot._cursor_a_wave_marker is not None
            assert plot._cursor_b_wave_marker is not None
            a_sample = plot._sample_cursor_channel(
                "vge", float(plot._cursor_a.value())
            )
            b_sample = plot._sample_cursor_channel(
                "vce", float(plot._cursor_b.value())
            )
            self.assertIsNotNone(a_sample)
            self.assertIsNotNone(b_sample)
            assert a_sample is not None and b_sample is not None
            _ax, ay = plot._cursor_a_wave_marker.getData()
            _bx, by = plot._cursor_b_wave_marker.getData()
            self.assertAlmostEqual(float(ay[0]), a_sample[1], places=9)
            self.assertAlmostEqual(float(by[0]), b_sample[1], places=9)
            active_before = plot._active_channel
            unrelated = plot._display_key_for_channel("il")
            plot._raise_trace(unrelated)
            plot._highlight_trace(unrelated)
            self.assertEqual(plot._active_channel, active_before)
            self.assertEqual(plot._cursor_endpoint_channel("a"), "vge")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "vce")
            plot._hidden_channels.add(plot._display_key_for_channel("vce"))
            self.assertEqual(plot._cursor_endpoint_channel("a"), "vge")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "vce")
        finally:
            plot.close()

    def test_shared_interval_source_survives_unrelated_trace_highlight(self):
        plot = self._make_synthetic_plot()
        try:
            plot.enable_interval_interaction(
                0.2,
                0.8,
                lambda *_args: None,
                channel="ic",
            )
            self.assertEqual(plot._cursor_endpoint_channel("a"), "ic")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "ic")
            unrelated = plot._display_key_for_channel("vce")
            plot._raise_trace(unrelated)
            plot._highlight_trace(unrelated)
            self.assertEqual(plot._active_channel, "ic")
            self.assertEqual(plot._interval_ab_channel, "ic")
            self.assertEqual(plot._cursor_endpoint_channel("a"), "ic")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "ic")
        finally:
            plot.close()

    def test_semantic_interval_keeps_reversed_ab_roles_and_channels(self):
        plot = self._make_synthetic_plot()
        emitted = []
        try:
            plot.enable_interval_interaction(
                0.8,
                0.2,
                lambda *values: emitted.append(values),
                mode="semantic_interval",
                channel="ic",
                a_channel="vge",
                b_channel="ic",
            )
            assert plot._cursor_a is not None and plot._cursor_b is not None
            self.assertAlmostEqual(float(plot._cursor_a.value()), 0.8, places=9)
            self.assertAlmostEqual(float(plot._cursor_b.value()), 0.2, places=9)
            self.assertEqual(plot._cursor_endpoint_channel("a"), "vge")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "ic")
            plot._on_any_cursor_moved()
            self.assertEqual(emitted[-1], (0.8, 0.2))
        finally:
            plot.close()

    def test_energy_cursor_endpoints_keep_their_semantic_waveforms(self):
        plot = self._make_synthetic_plot()
        try:
            cases = (
                ("vce", "ic", "vce", "ic"),
                ("ic", "vce", "ic", "vce"),
                ("irr", "v_diode", "irr", "v_diode"),
            )
            for a_channel, b_channel, ha_channel, hb_channel in cases:
                with self.subTest(
                    a=a_channel,
                    b=b_channel,
                    ha=ha_channel,
                    hb=hb_channel,
                ):
                    plot.enable_energy_loss_interaction(
                        0.1,
                        0.9,
                        0.2,
                        0.8,
                        500.0,
                        100.0,
                        lambda *_args: None,
                        a_channel=a_channel,
                        b_channel=b_channel,
                        ha_channel=ha_channel,
                        hb_channel=hb_channel,
                        sync_cursors_from_levels=False,
                    )
                    self.assertEqual(
                        plot._cursor_endpoint_channel("a"), a_channel
                    )
                    self.assertEqual(
                        plot._cursor_endpoint_channel("b"), b_channel
                    )
                    self.assertEqual(
                        plot._horizontal_cursor_binding("ha"),
                        (ha_channel, True),
                    )
                    self.assertEqual(
                        plot._horizontal_cursor_binding("hb"),
                        (hb_channel, True),
                    )
                    unrelated = plot._display_key_for_channel("il")
                    plot._raise_trace(unrelated)
                    plot._highlight_trace(unrelated)
                    self.assertEqual(
                        plot._cursor_endpoint_channel("a"), a_channel
                    )
                    self.assertEqual(
                        plot._cursor_endpoint_channel("b"), b_channel
                    )
        finally:
            plot.close()

    def test_err_energy_signed_levels_match_labels_readout_and_callback(self):
        emitted = []
        plot = self._make_synthetic_plot()
        try:
            plot.enable_energy_loss_interaction(
                0.0,
                1.0,
                0.2,
                0.8,
                -25.0,
                -12.0,
                lambda *values: emitted.append(values),
                a_channel="irr",
                b_channel="v_diode",
                ha_channel="irr",
                hb_channel="v_diode",
                fall_a_mode="err_irr",
                rise_b_mode="err_vd",
                peak_channels=("irr", "v_diode"),
                sync_cursors_from_levels=False,
            )
            plot.set_cursor_type("both")
            plot._update_readout()
            assert plot._cursor_ha_v_label is not None
            ha_label = plot._cursor_ha_v_label.textItem.toPlainText()
            top_readout = plot._readout_label.text()
            self.assertIn("-25", ha_label)
            self.assertIn("-25.00A", top_readout)
            self.assertIn("-12.00V", top_readout)

            plot._emit_energy_loss_changed()
            self.assertEqual(len(emitted), 1)
            self.assertAlmostEqual(emitted[-1][2], -25.0, places=9)
            self.assertAlmostEqual(emitted[-1][3], -12.0, places=9)

            # Other Irr amplitude modes keep their historical magnitude semantics.
            plot.enable_energy_loss_interaction(
                0.0,
                1.0,
                0.2,
                0.8,
                -25.0,
                12.0,
                lambda *values: emitted.append(values),
                a_channel="irr",
                ha_channel="irr",
                sync_cursors_from_levels=False,
            )
            plot.set_cursor_type("both")
            plot._update_readout()
            self.assertIn("+25.00A", plot._readout_label.text())
            plot._emit_energy_loss_changed()
            self.assertAlmostEqual(emitted[-1][2], 25.0, places=9)
        finally:
            plot.close()

    def test_energy_manual_endpoint_markers_sample_semantic_waveforms(self):
        cases = (
            ("Eoff", "vce", "ic", None),
            ("Eon", "ic", "vce", None),
            ("Err", "irr", "v_diode", "err_irr"),
        )
        for name, a_channel, b_channel, fall_a_mode in cases:
            plot = self._make_synthetic_plot()
            try:
                with self.subTest(parameter=name):
                    plot.enable_energy_loss_interaction(
                        0.0,
                        1.0,
                        0.2,
                        0.8,
                        7777.0,
                        -3333.0,
                        lambda *_args: None,
                        a_channel=a_channel,
                        b_channel=b_channel,
                        ha_channel=a_channel,
                        hb_channel=b_channel,
                        fall_a_mode=fall_a_mode,
                        sync_cursors_from_levels=False,
                    )
                    plot.set_cursor_type("both")
                    assert plot._cursor_a is not None and plot._cursor_b is not None
                    plot._cursor_a.setValue(0.37)
                    plot._cursor_b.setValue(0.63)
                    plot._update_readout()

                    if name == "Err":
                        logical_irr = plot._display_key_for_channel("irr")
                        self.assertEqual(logical_irr, "LOGIC_IRR")
                        self.assertIn(logical_irr, plot._trace_raw)
                        self.assertNotIn(logical_irr, plot._trace_items)

                    for end, channel, cursor, marker in (
                        ("a", a_channel, plot._cursor_a, plot._cursor_a_wave_marker),
                        ("b", b_channel, plot._cursor_b, plot._cursor_b_wave_marker),
                    ):
                        self.assertIsNotNone(marker, end)
                        expected = plot._sample_cursor_channel(
                            channel, float(cursor.value())
                        )
                        self.assertIsNotNone(expected, end)
                        assert marker is not None and expected is not None
                        marker_x, marker_y = marker.getData()
                        self.assertEqual(len(marker_x), 1, end)
                        self.assertEqual(len(marker_y), 1, end)
                        self.assertAlmostEqual(
                            float(marker_x[0]), float(cursor.value()), places=9
                        )
                        self.assertAlmostEqual(
                            float(marker_y[0]), float(expected[1]), places=9
                        )
            finally:
                plot.close()

    def test_apply_power_peak_binding_transitions_are_atomic(self):
        plot = self._make_synthetic_plot()
        try:
            vce_key = plot._display_key_for_channel("vce")
            ic_key = plot._display_key_for_channel("ic")
            plot._set_math_formula("MATH2", f"{vce_key} * {ic_key}")
            plot._set_math_formula("MATH9", f"0.9 * {vce_key} * {ic_key}")
            plot.enable_interval_interaction(
                0.2,
                0.8,
                lambda *_args: None,
                show_horizontal_peak=True,
                mode="power_peak",
                channel="MATH2",
                a_channel="MATH2",
                b_channel="MATH2",
            )
            plot.set_cursor_type("both")

            def assert_matched(channel, peak_value, peak_t_us):
                self.assertEqual(plot._cursor_endpoint_channel("a"), channel)
                self.assertEqual(plot._cursor_endpoint_channel("b"), channel)
                self.assertEqual(plot._interval_ab_channel, channel)
                self.assertEqual(plot._active_channel, channel)
                self.assertEqual(
                    plot._horizontal_cursor_binding("ha"), (channel, True)
                )
                self.assertFalse(plot._horizontal_cursor_binding("hb")[1])
                self.assertTrue(plot._interval_max_hline_enabled)
                self.assertEqual(plot._cursor_aux_channel, channel)
                self.assertAlmostEqual(plot._cursor_aux_t_us, peak_t_us, places=9)
                self.assertAlmostEqual(plot._cursor_aux_value, peak_value, places=9)

            plot.apply_power_peak_binding(
                boundary_a_channel="vce",
                boundary_b_channel="ic",
                peak_channel="MATH2",
                peak_value=123.0,
                peak_t_us=0.41,
            )
            assert_matched("MATH2", 123.0, 0.41)

            # MATH2 -> no eligible power trace.
            plot.apply_power_peak_binding(
                boundary_a_channel="vce", boundary_b_channel="ic"
            )
            self.assertEqual(plot._cursor_endpoint_channel("a"), "vce")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "ic")
            self.assertEqual(plot._interval_ab_channel, "vce")
            self.assertEqual(plot._active_channel, "vce")
            self.assertFalse(plot._horizontal_cursor_binding("ha")[1])
            self.assertFalse(plot._horizontal_cursor_binding("hb")[1])
            self.assertFalse(plot._interval_max_hline_enabled)
            self.assertIsNone(plot._cursor_aux_channel)
            self.assertIsNone(plot._cursor_aux_t_us)
            self.assertIsNone(plot._cursor_aux_value)

            # No trace -> MATH9, then a direct MATH2 -> MATH9 switch.
            plot.apply_power_peak_binding(
                boundary_a_channel="vce",
                boundary_b_channel="ic",
                peak_channel="MATH9",
                peak_value=456.0,
                peak_t_us=0.52,
            )
            assert_matched("MATH9", 456.0, 0.52)
            plot.apply_power_peak_binding(
                boundary_a_channel="vce",
                boundary_b_channel="ic",
                peak_channel="MATH2",
                peak_value=321.0,
                peak_t_us=0.43,
            )
            plot.apply_power_peak_binding(
                boundary_a_channel="vce",
                boundary_b_channel="ic",
                peak_channel="MATH9",
                peak_value=654.0,
                peak_t_us=0.57,
            )
            assert_matched("MATH9", 654.0, 0.57)
        finally:
            plot.close()

    def test_slope_cursor_endpoints_keep_the_logical_waveform_role(self):
        plot = self._make_synthetic_plot()
        try:
            plot.enable_dvdt_interaction(
                0.1,
                0.9,
                100.0,
                0.0,
                "irr",
                lambda *_args: None,
                mode="didt",
            )
            plot.apply_dvdt_ab_times(0.3, 0.7)
            self.assertEqual(plot._cursor_endpoint_channel("a"), "irr")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "irr")
            unrelated = plot._display_key_for_channel("vce")
            plot._raise_trace(unrelated)
            plot._highlight_trace(unrelated)
            self.assertEqual(plot._cursor_endpoint_channel("a"), "irr")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "irr")
        finally:
            plot.close()

    def test_short_current_keeps_logical_ic_after_visible_channel_selection(self):
        plot = self._make_synthetic_plot()
        emitted = []
        try:
            plot.enable_short_current_interaction(
                0.1,
                0.9,
                0.2,
                0.8,
                100.0,
                500.0,
                lambda *values: emitted.append(values),
                channel="CH1",
            )
            self.assertEqual(plot._active_channel, "ic")
            self.assertEqual(plot._slope_channel, "ic")
            self.assertEqual(plot._horizontal_cursor_binding("ha"), ("ic", True))
            self.assertEqual(plot._horizontal_cursor_binding("hb"), ("ic", True))

            vge_key = plot._display_key_for_channel("vge")
            self.assertNotEqual(vge_key, plot._display_key_for_channel("ic"))
            plot._on_legend_clicked(vge_key)
            self.assertEqual(plot._active_channel, "ic")
            plot._on_legend_double_clicked(vge_key)
            self.assertEqual(plot._active_channel, "ic")

            plot._emit_short_current_changed()
            self.assertEqual(len(emitted), 1)
            self.assertAlmostEqual(emitted[0][2], 100.0, places=9)
            self.assertAlmostEqual(emitted[0][3], 500.0, places=9)
        finally:
            plot.close()

    def test_mixed_boundary_parameter_cursor_channel_matrix(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            expected = {
                ("开通", "Ton"): ("vge", "ic"),
                ("开通", "Td_on"): ("vge", "ic"),
                ("开通", "Tr"): ("ic", "ic"),
                ("关断过程", "Toff"): ("vge", "ic"),
                ("关断过程", "Td_off"): ("vge", "ic"),
                ("关断过程", "Tf"): ("ic", "ic"),
                ("关断过程", "Ic_off_max"): ("vge", "vge"),
                ("关断过程", "Vce_off_max"): ("vce", "vce"),
                ("开通", "Vce_on_max"): ("vge", "vce"),
                ("反向恢复", "Vrr"): ("v_diode", "v_diode"),
                ("开通", "Ic_on_max"): ("ic", "vce"),
                ("短路过程", "应力Vpeak_本管"): ("vge", "vge"),
                ("短路过程", "应力Vpeak_对管"): ("vge", "vge"),
            }
            for key, channels in expected.items():
                with self.subTest(parameter=key):
                    self.assertEqual(
                        win._cursor_endpoint_channels_for_param(*key), channels
                    )
        finally:
            win.close()

    def test_channel_box_mouse_gestures(self):
        try:
            from PyQt6.QtTest import QTest
        except ImportError:
            self.skipTest("QtTest is not available")
        from PyQt6.QtCore import Qt

        from dpt_extractor.gui.waveform_plot import ChannelBox

        box = ChannelBox("CH2", "CH2", "#28bce8")
        events = []
        box.raiseClicked.connect(lambda key: events.append(("raise", key)))
        box.highlightDoubleClicked.connect(
            lambda key: events.append(("highlight", key))
        )
        box.verticalSettingsRequested.connect(
            lambda key: events.append(("settings", key))
        )
        box.show()

        QTest.mouseClick(box, Qt.MouseButton.LeftButton)
        self.assertIn(("raise", "CH2"), events)
        QTest.mouseDClick(box, Qt.MouseButton.LeftButton)
        self.assertIn(("highlight", "CH2"), events)
        QTest.mouseClick(box, Qt.MouseButton.RightButton)
        self.assertIn(("settings", "CH2"), events)
        box.close()

    def test_channel_bar_uses_arrow_buttons_instead_of_scrollbar(self):
        from PyQt6.QtCore import Qt

        plot = self._make_synthetic_plot()
        plot.resize(520, 520)
        plot.show()
        self.app.processEvents()
        plot._sync_channel_bar_width()
        self.app.processEvents()

        bar = plot._channel_scroll.horizontalScrollBar()
        self.assertEqual(
            plot._channel_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertTrue(plot._channel_nav_left_btn.isVisible())
        self.assertTrue(plot._channel_nav_right_btn.isVisible())
        self.assertFalse(plot._channel_nav_left_btn.isEnabled())
        self.assertTrue(plot._channel_nav_right_btn.isEnabled())

        start = bar.value()
        plot._channel_nav_right_btn.click()
        self.app.processEvents()
        self.assertGreater(bar.value(), start)
        self.assertTrue(plot._channel_nav_left_btn.isEnabled())

        plot.resize(1600, 520)
        self.app.processEvents()
        plot._sync_channel_bar_width()
        self.app.processEvents()
        self.assertFalse(plot._channel_nav_left_btn.isVisible())
        self.assertFalse(plot._channel_nav_right_btn.isVisible())
        self.assertEqual(bar.value(), bar.minimum())
        plot.close()

    def test_zero_handle_shows_math_label_and_uses_press_feedback(self):
        from PyQt6.QtCore import Qt

        from dpt_extractor.gui.waveform_plot import ChannelZeroHandle

        plot = self._make_synthetic_plot()
        handle = plot._zero_handles["MATH1"]

        self.assertEqual(plot._zero_handle_display_label("CH1"), "C1")
        self.assertEqual(handle._label, "M1")
        self.assertEqual(handle._px_len, ChannelZeroHandle._PX_LEN)
        self.assertEqual(handle._px_h, ChannelZeroHandle._PX_H)
        self.assertEqual(handle.cursor().shape(), Qt.CursorShape.ArrowCursor)

        base = handle._current_fill_color()
        handle._set_pressed(True)
        pressed = handle._current_fill_color()
        self.assertLess(pressed.lightness(), base.lightness())
        handle._set_pressed(False)
        restored = handle._current_fill_color()
        self.assertEqual(restored.name(), base.name())
        self.assertEqual(restored.alpha(), base.alpha())

    def test_zero_handles_resync_after_viewbox_resize_without_drag(self):
        plot = self._make_synthetic_plot()
        plot.resize(900, 500)
        plot.show()
        for _ in range(3):
            self.app.processEvents()
        plot._update_zero_handle_positions()

        plot.resize(1180, 660)
        for _ in range(6):
            self.app.processEvents()

        vb = plot.plot.getPlotItem().getViewBox()
        for key in ("CH1", "MATH1"):
            expected = plot._zero_handle_scene_pos(
                vb, plot._zero_handle_display_y(key)
            )
            actual = plot._zero_handles[key].pos()
            self.assertAlmostEqual(actual.x(), expected.x(), places=3, msg=key)
            self.assertAlmostEqual(actual.y(), expected.y(), places=3, msg=key)
        plot.close()

    def test_pyqtgraph_auto_buttons_are_hidden(self):
        plot = self._make_synthetic_plot()
        self.assertTrue(plot.plot.getPlotItem().buttonsHidden)
        self.assertTrue(plot._overview_plot.getPlotItem().buttonsHidden)

    def test_auxiliary_dash_pen_uses_spaced_pattern(self):
        from PyQt6.QtCore import Qt

        from dpt_extractor.gui.waveform_plot import AUX_DASH_PATTERN, _spaced_dash_pen

        pen = _spaced_dash_pen("#ffffff", 1.0)

        self.assertTrue(pen.isCosmetic())
        self.assertEqual(pen.style(), Qt.PenStyle.CustomDashLine)
        self.assertEqual(list(pen.dashPattern()), list(AUX_DASH_PATTERN))

    def test_cursor_auxiliary_guides_stay_between_cursor_pairs_when_bound(self):
        from dpt_extractor.gui.waveform_plot import (
            CURSOR_AUXILIARY_HORIZONTAL_COLOR,
            CURSOR_AUXILIARY_VERTICAL_COLOR,
        )

        plot = self._make_synthetic_plot()
        plot.enable_interval_interaction(
            0.2,
            0.8,
            lambda *_args: None,
            show_horizontal_peak=True,
        )
        plot.set_interval_peak_horizontal(
            0.0,
            channel="vce",
            t0_us=0.2,
            t1_us=0.8,
        )
        # The auxiliary Ha-Hb connector is meaningful only after both
        # horizontal lines are explicitly bound to comparable quantities.
        plot.set_interval_base_horizontal(-0.25, channel="vce")

        point = plot._peak_plot_point_in_window("vce", 0.2, 0.8)
        self.assertIsNotNone(point)
        assert point is not None
        peak_t_us, peak_value, peak_y = point
        plot.set_cursor_auxiliary_point(
            "vce",
            peak_t_us,
            peak_value,
            show_vertical_guide=True,
        )

        self.assertIsNotNone(plot._cursor_aux_hline)
        self.assertIsNotNone(plot._cursor_aux_vline)
        assert plot._cursor_aux_hline is not None
        assert plot._cursor_aux_vline is not None
        self.assertGreater(plot._cursor_aux_hline.zValue(), plot._cursor_a.zValue())
        self.assertGreater(plot._cursor_aux_vline.zValue(), plot._cursor_a.zValue())
        self.assertEqual(
            plot._cursor_aux_hline.opts["pen"].color().name(),
            CURSOR_AUXILIARY_VERTICAL_COLOR.lower(),
        )
        self.assertEqual(
            plot._cursor_aux_vline.opts["pen"].color().name(),
            CURSOR_AUXILIARY_HORIZONTAL_COLOR.lower(),
        )

        hx, hy = plot._cursor_aux_hline.getData()
        vx, vy = plot._cursor_aux_vline.getData()
        assert plot._cursor_a is not None and plot._cursor_b is not None
        assert plot._h_cursor_a is not None and plot._h_cursor_b is not None
        a, b = sorted((float(plot._cursor_a.value()), float(plot._cursor_b.value())))
        ha, hb = sorted(
            (float(plot._h_cursor_a.value()), float(plot._h_cursor_b.value()))
        )
        aux_x = plot._horizontal_cursor_auxiliary_x()

        self.assertAlmostEqual(float(hx[0]), a, places=9)
        self.assertAlmostEqual(float(hx[1]), b, places=9)
        self.assertAlmostEqual(float(hy[0]), peak_y, places=9)
        self.assertAlmostEqual(float(hy[1]), peak_y, places=9)
        self.assertAlmostEqual(float(vx[0]), aux_x, places=9)
        self.assertAlmostEqual(float(vx[1]), aux_x, places=9)
        self.assertAlmostEqual(float(vy[0]), ha, places=9)
        self.assertAlmostEqual(float(vy[1]), hb, places=9)

        plot._set_cursor_type("vertical")
        self.assertTrue(plot._cursor_aux_hline.isVisible())
        self.assertFalse(plot._cursor_aux_vline.isVisible())
        plot._set_cursor_type("horizontal")
        self.assertFalse(plot._cursor_aux_hline.isVisible())
        self.assertTrue(plot._cursor_aux_vline.isVisible())
        plot.close()

    def test_interval_vertical_cursor_auxiliary_guide_is_hidden_by_default(self):
        plot = self._make_synthetic_plot()
        plot.enable_interval_interaction(
            0.2,
            0.8,
            lambda *_args: None,
            show_horizontal_peak=True,
        )
        plot.set_interval_peak_horizontal(
            0.0,
            channel="vce",
            t0_us=0.2,
            t1_us=0.8,
        )

        self.assertIsNotNone(plot._cursor_aux_hline)
        assert plot._cursor_aux_hline is not None
        self.assertFalse(plot._cursor_aux_hline.isVisible())
        plot._set_cursor_type("vertical")
        self.assertFalse(plot._cursor_aux_hline.isVisible())
        plot.close()

    def test_cursor_auxiliary_guides_have_default_waveform_point_without_vertical_guide(self):
        plot = self._make_synthetic_plot()
        self.assertIsNotNone(plot._cursor_aux_hline)
        self.assertIsNotNone(plot._cursor_aux_vline)
        assert plot._cursor_aux_hline is not None
        assert plot._cursor_aux_vline is not None
        self.assertFalse(plot._cursor_aux_hline.isVisible())
        self.assertTrue(plot._cursor_aux_vline.isVisible())

        point = plot._cursor_auxiliary_point()
        self.assertIsNotNone(point)
        assert point is not None
        channel, t_us, value = point
        self.assertEqual(channel, plot._cursor_source_channel())
        assert plot._cursor_a is not None and plot._cursor_b is not None
        expected_t = 0.5 * (float(plot._cursor_a.value()) + float(plot._cursor_b.value()))
        expected = plot._sample_cursor_channel(channel, expected_t)
        self.assertIsNotNone(expected)
        assert expected is not None
        self.assertAlmostEqual(t_us, expected_t, places=9)
        self.assertAlmostEqual(value, expected[0], places=9)
        plot.close()

    def test_waveform_cursor_mode_keeps_default_vertical_auxiliary_hidden(self):
        plot = self._make_synthetic_plot()
        plot._set_cursor_type("waveform")
        assert plot._cursor_a is not None and plot._cursor_b is not None
        plot._cursor_a.setPos(0.8)
        plot._cursor_b.setPos(0.2)
        plot._update_readout()

        self.assertIsNotNone(plot._cursor_aux_hline)
        self.assertIsNotNone(plot._cursor_aux_vline)
        assert plot._cursor_aux_hline is not None
        assert plot._cursor_aux_vline is not None
        self.assertFalse(plot._cursor_aux_hline.isVisible())
        self.assertFalse(plot._cursor_aux_vline.isVisible())

        point = plot._cursor_auxiliary_point()
        self.assertIsNotNone(point)
        assert point is not None
        channel, t_us, value = point
        self.assertEqual(channel, plot._cursor_source_channel())
        candidates = []
        for cursor in (plot._cursor_a, plot._cursor_b):
            cursor_t = float(cursor.value())
            sample = plot._sample_cursor_channel(channel, cursor_t)
            self.assertIsNotNone(sample)
            assert sample is not None
            sample_value, sample_y = sample
            candidates.append((sample_value, sample_y, cursor_t))
        expected_value, expected_y, expected_t = max(
            candidates, key=lambda item: item[1]
        )
        self.assertAlmostEqual(t_us, expected_t, places=9)
        self.assertAlmostEqual(value, expected_value, places=9)

        plot.close()

    def test_offset_measurement_mode_adds_custom_waveform_metric(self):
        from PyQt6.QtCore import QSettings
        from PyQt6.QtWidgets import QComboBox

        from dpt_extractor.gui.main_window import MainWindow, _WaveformLoadOutcome
        from dpt_extractor.gui.main_window import NONCOMMERCIAL_NOTICE_SETTINGS_KEY
        from dpt_extractor.models.test_mode import TestMode

        bundle, profile = self._make_synthetic_bundle()
        bundle.meta.channel_math_formulas["MATH1"] = "INTG(CH1)"
        settings = QSettings("DPT", "DPTExtractor")
        old_value = settings.value(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, None)
        settings.setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, True)
        try:
            win = MainWindow()
            self.app.processEvents()
            win.cfg.test_mode.mode = TestMode.OFFSET_MEASUREMENT.value
            win._apply_test_mode_ui()
            win._apply_loaded_waveform(
                _WaveformLoadOutcome(
                    path="/fake/offset_mode.tss",
                    bundle=bundle,
                    guessed=profile,
                    profile=profile,
                    inferred=None,
                    inferred_source="",
                    mapping_custom=False,
                    result=None,
                    short_circuit_not_ready=False,
                    extraction_error="",
                    load_ms=1.0,
                    extract_ms=0.0,
                )
            )

            self.assertIsNone(win.result)
            self.assertFalse(win.result_table.offset_panel.isHidden())
            self.assertFalse(win.btn_export.isEnabled())
            self.assertIsNotNone(win.result_table.offset_measure_button)
            self.assertGreater(len(win._offset_source_options()), 0)

            source = win._offset_source_options()[0][0]
            win._on_offset_measurement_add_requested(source, "maximum", "cursor")
            self.assertEqual(win.result_table.table.rowCount(), 1)
            self.assertEqual(
                win.result_table._row_meta[0][0],
                win._offset_source_display_name(source),
            )
            self.assertIn("Maximum", win.result_table._row_meta[0][1])
            self.assertNotIn("H-Vge", win.result_table._row_meta[0][1])
            self.assertEqual(win.result_table.table.item(0, 3).text(), "光标")
            self.assertNotEqual(win.result_table.table.item(0, 4).text(), "—")
            self.assertIn((source.upper(), "maximum", "cursor"), win._offset_measurements)
            aux_point = win.wave_plot._cursor_auxiliary_point()
            self.assertIsNotNone(aux_point)
            assert aux_point is not None
            self.assertEqual(aux_point[0], source.upper())
            _t_range, raw = win._offset_series_for_range(source.upper(), "cursor")
            self.assertAlmostEqual(aux_point[2], float(raw.max()), places=9)
            self.assertIsNotNone(win.wave_plot._cursor_aux_hline)
            assert win.wave_plot._cursor_aux_hline is not None
            self.assertTrue(win.wave_plot._cursor_aux_hline.isVisible())

            source_combo = win.result_table.table.cellWidget(0, 0)
            self.assertIsInstance(source_combo, QComboBox)
            assert isinstance(source_combo, QComboBox)
            math_idx = source_combo.findData("MATH1")
            self.assertGreaterEqual(math_idx, 0)
            source_combo.setCurrentIndex(math_idx)
            self.app.processEvents()
            self.assertEqual(win._offset_measurements[0], ("MATH1", "maximum", "cursor"))
            self.assertEqual(win.result_table.table.item(0, 0).text(), "Math 1")
            self.assertEqual(
                win.result_table.table.item(0, 0).background().color().name(),
                win.wave_plot.trace_color("MATH1").lower(),
            )
            aux_point = win.wave_plot._cursor_auxiliary_point()
            self.assertIsNotNone(aux_point)
            assert aux_point is not None
            self.assertEqual(aux_point[0], "MATH1")
            _t_range, raw = win._offset_series_for_range("MATH1", "cursor")
            self.assertAlmostEqual(aux_point[2], float(raw.max()), places=9)
            assert win.wave_plot._cursor_aux_hline is not None
            self.assertTrue(win.wave_plot._cursor_aux_hline.isVisible())

            win._on_offset_measurement_update_requested(0, "metric", "minimum")
            self.app.processEvents()
            self.assertEqual(win._offset_measurements[0], ("MATH1", "minimum", "cursor"))
            aux_point = win.wave_plot._cursor_auxiliary_point()
            self.assertIsNotNone(aux_point)
            assert aux_point is not None
            _t_range, raw = win._offset_series_for_range("MATH1", "cursor")
            self.assertAlmostEqual(aux_point[2], float(raw.min()), places=9)
            assert win.wave_plot._cursor_aux_hline is not None
            self.assertTrue(win.wave_plot._cursor_aux_hline.isVisible())
            win._on_offset_measurement_update_requested(0, "metric", "maximum")
            self.app.processEvents()

            self.assertIsNone(win.result_table.table.cellWidget(0, 2))
            self.assertEqual(win.result_table.table.item(0, 2).text(), "mJ")
            _t_range, raw = win._offset_series_for_range("MATH1", "cursor")
            expected_mj = win._offset_value_text(float(raw.max()) * 1000.0)
            self.assertEqual(win.result_table.table.item(0, 4).text(), expected_mj)

            win._on_offset_measurement_delete_requested("MATH1", "maximum", "cursor")
            self.assertNotIn(
                ("MATH1", "maximum", "cursor"),
                win._offset_measurements,
            )
            self.assertEqual(win.result_table.table.rowCount(), 0)
            self.assertIsNone(win.result_table.current_offset_measurement_spec())

            win._on_offset_measurement_add_requested(source, "maximum")
            self.assertEqual(win.result_table.table.rowCount(), 1)
            self.assertIn((source.upper(), "maximum", "screen"), win._offset_measurements)
            self.assertEqual(win.result_table.table.item(0, 3).text(), "屏幕")
            win._on_offset_measurement_delete_all_requested()
            self.assertEqual(win._offset_measurements, [])
            self.assertEqual(win.result_table.table.rowCount(), 0)
            win.close()
            self.app.processEvents()
        finally:
            if old_value is None:
                settings.remove(NONCOMMERCIAL_NOTICE_SETTINGS_KEY)
            else:
                settings.setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, old_value)

    def test_offset_measurement_uses_live_math_and_inverted_waveform(self):
        from PyQt6.QtCore import QSettings

        from dpt_extractor.gui.main_window import MainWindow, _WaveformLoadOutcome
        from dpt_extractor.gui.main_window import NONCOMMERCIAL_NOTICE_SETTINGS_KEY
        from dpt_extractor.metrics.offset_measurement import (
            auto_offset_measurement_unit,
            convert_offset_measurement_value,
        )
        from dpt_extractor.models.test_mode import TestMode

        bundle, profile = self._make_synthetic_bundle()
        settings = QSettings("DPT", "DPTExtractor")
        old_value = settings.value(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, None)
        settings.setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, True)
        try:
            win = MainWindow()
            self.app.processEvents()
            win.cfg.test_mode.mode = TestMode.OFFSET_MEASUREMENT.value
            win._apply_test_mode_ui()
            win._apply_loaded_waveform(
                _WaveformLoadOutcome(
                    path="/fake/offset_live_math.tss",
                    bundle=bundle,
                    guessed=profile,
                    profile=profile,
                    inferred=None,
                    inferred_source="",
                    mapping_custom=False,
                    result=None,
                    short_circuit_not_ready=False,
                    extraction_error="",
                    load_ms=1.0,
                    extract_ms=0.0,
                )
            )

            win.wave_plot._set_math_formula("MATH2", "CH2 * CH3")
            self.assertIn("MATH2", dict(win._offset_source_options()))
            win._on_offset_measurement_add_requested("MATH2", "maximum", "full")
            self.app.processEvents()

            def _assert_math2_max_matches_current_display() -> None:
                raw = win.wave_plot.current_display_raw("MATH2")
                self.assertIsNotNone(raw)
                assert raw is not None
                expected = float(raw.max())
                self.assertGreater(abs(expected), 1000.0)
                unit = auto_offset_measurement_unit(expected, "W")
                expected_display = convert_offset_measurement_value(
                    expected,
                    "W",
                    unit,
                )
                self.assertEqual(win.result_table.table.item(0, 0).text(), "Math 2")
                self.assertEqual(win.result_table.table.item(0, 1).text(), "Maximum")
                self.assertEqual(win.result_table.table.item(0, 2).text(), unit)
                self.assertEqual(
                    win.result_table.table.item(0, 4).text(),
                    win._offset_value_text(expected_display),
                )
                aux_point = win.wave_plot._cursor_auxiliary_point()
                self.assertIsNotNone(aux_point)
                assert aux_point is not None
                self.assertEqual(aux_point[0], "MATH2")
                self.assertAlmostEqual(aux_point[2], expected, places=6)

            _assert_math2_max_matches_current_display()
            self.assertIn(win.result_table.table.item(0, 2).text(), {"KW", "MW"})
            self.assertNotEqual(win.result_table.table.item(0, 4).text(), "0.1872")

            win.wave_plot.set_channel_inversion_enabled("MATH2", True)
            win._refresh_offset_measurement_table(update_auxiliary=True)
            self.app.processEvents()
            _assert_math2_max_matches_current_display()
            win.close()
            self.app.processEvents()
        finally:
            if old_value is None:
                settings.remove(NONCOMMERCIAL_NOTICE_SETTINGS_KEY)
            else:
                settings.setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, old_value)

    def test_offset_measurement_auxiliary_guide_uses_selected_range(self):
        from PyQt6.QtCore import QSettings

        from dpt_extractor.gui.main_window import MainWindow, _WaveformLoadOutcome
        from dpt_extractor.gui.main_window import NONCOMMERCIAL_NOTICE_SETTINGS_KEY
        from dpt_extractor.models.test_mode import TestMode

        bundle, profile = self._make_synthetic_bundle()
        settings = QSettings("DPT", "DPTExtractor")
        old_value = settings.value(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, None)
        settings.setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, True)
        try:
            win = MainWindow()
            self.app.processEvents()
            win.cfg.test_mode.mode = TestMode.OFFSET_MEASUREMENT.value
            win._apply_test_mode_ui()
            win._apply_loaded_waveform(
                _WaveformLoadOutcome(
                    path="/fake/offset_range_guides.tss",
                    bundle=bundle,
                    guessed=profile,
                    profile=profile,
                    inferred=None,
                    inferred_source="",
                    mapping_custom=False,
                    result=None,
                    short_circuit_not_ready=False,
                    extraction_error="",
                    load_ms=1.0,
                    extract_ms=0.0,
                )
            )

            assert win.wave_plot._cursor_a is not None
            assert win.wave_plot._cursor_b is not None
            win.wave_plot._cursor_a.setPos(0.25)
            win.wave_plot._cursor_b.setPos(0.75)
            source = win._offset_source_options()[0][0]
            win._on_offset_measurement_add_requested(source, "maximum", "cursor")
            self.app.processEvents()

            def _guide_x() -> tuple[float, float]:
                line = win.wave_plot._cursor_aux_hline
                self.assertIsNotNone(line)
                assert line is not None
                x, _y = line.getData()
                return float(x[0]), float(x[-1])

            def _assert_marker_matches_range(range_key: str) -> None:
                aux_point = win.wave_plot._cursor_auxiliary_point()
                self.assertIsNotNone(aux_point)
                assert aux_point is not None
                t_range, raw = win._offset_series_for_range(source.upper(), range_key)
                self.assertGreater(raw.size, 0)
                self.assertAlmostEqual(aux_point[1], float(t_range[-1] * 1e6), places=9)
                self.assertAlmostEqual(aux_point[2], float(raw.max()), places=9)

            self.assertEqual(_guide_x(), (0.25, 0.75))
            _assert_marker_matches_range("cursor")

            vb = win.wave_plot.plot.getPlotItem().getViewBox()
            vb.setXRange(0.10, 0.60, padding=0.0)
            self.app.processEvents()
            win._on_offset_measurement_update_requested(0, "range", "screen")
            self.app.processEvents()
            screen = win.wave_plot.current_x_range_us()
            self.assertIsNotNone(screen)
            assert screen is not None
            sx0, sx1 = _guide_x()
            self.assertAlmostEqual(sx0, screen[0], places=9)
            self.assertAlmostEqual(sx1, screen[1], places=9)
            _assert_marker_matches_range("screen")

            vb.setXRange(0.20, 0.50, padding=0.0)
            self.app.processEvents()
            screen = win.wave_plot.current_x_range_us()
            self.assertIsNotNone(screen)
            assert screen is not None
            sx0, sx1 = _guide_x()
            self.assertAlmostEqual(sx0, screen[0], places=9)
            self.assertAlmostEqual(sx1, screen[1], places=9)
            _assert_marker_matches_range("screen")

            win._on_offset_measurement_update_requested(0, "range", "full")
            self.app.processEvents()
            fx0, fx1 = _guide_x()
            self.assertAlmostEqual(fx0, float(bundle.t[0] * 1e6), places=9)
            self.assertAlmostEqual(fx1, float(bundle.t[-1] * 1e6), places=9)
            _assert_marker_matches_range("full")
            win.close()
            self.app.processEvents()
        finally:
            if old_value is None:
                settings.remove(NONCOMMERCIAL_NOTICE_SETTINGS_KEY)
            else:
                settings.setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, old_value)

    def test_offset_cursor_window_is_independent_from_parameter_modes(self):
        from PyQt6.QtCore import QSettings

        from dpt_extractor.gui.main_window import MainWindow, _WaveformLoadOutcome
        from dpt_extractor.gui.main_window import NONCOMMERCIAL_NOTICE_SETTINGS_KEY
        from dpt_extractor.models.results import (
            ExtractResult,
            SegmentIndices,
            ShortCircuitResult,
        )
        from dpt_extractor.models.test_mode import TestMode

        bundle, profile = self._make_synthetic_bundle()
        settings = QSettings("DPT", "DPTExtractor")
        old_value = settings.value(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, None)
        settings.setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, True)
        try:
            win = MainWindow()
            self.app.processEvents()
            path = "/fake/offset_cursor_independent.tss"

            def _load(result: ExtractResult | None, mode: TestMode) -> None:
                win.cfg.test_mode.mode = mode.value
                win._apply_test_mode_ui()
                win._apply_loaded_waveform(
                    _WaveformLoadOutcome(
                        path=path,
                        bundle=bundle,
                        guessed=profile,
                        profile=profile,
                        inferred=None,
                        inferred_source="",
                        mapping_custom=False,
                        result=result,
                        short_circuit_not_ready=False,
                        extraction_error="",
                        load_ms=1.0,
                        extract_ms=0.0,
                    )
                )
                self.app.processEvents()

            _load(None, TestMode.OFFSET_MEASUREMENT)
            self.assertEqual(win.wave_plot.cursor_type(), "waveform")
            assert win.wave_plot._cursor_a is not None
            assert win.wave_plot._cursor_b is not None
            assert win.wave_plot._h_cursor_a is not None
            assert win.wave_plot._h_cursor_b is not None
            self.assertTrue(win.wave_plot._cursor_a.isVisible())
            self.assertTrue(win.wave_plot._cursor_b.isVisible())
            self.assertFalse(win.wave_plot._h_cursor_a.isVisible())
            self.assertFalse(win.wave_plot._h_cursor_b.isVisible())

            win.wave_plot._cursor_a.setValue(0.82)
            win.wave_plot._cursor_b.setValue(0.91)
            self.app.processEvents()
            offset_window = win._offset_cursor_window_for_current_waveform()
            self.assertEqual(offset_window, (0.82, 0.91))

            segments = SegmentIndices(
                turn_off=(20, 70),
                turn_on=(110, 160),
                reverse_recovery=(110, 160),
                pulse1_on=10,
                pulse1_off=45,
                pulse2_on=130,
                pulse2_off=180,
            )
            dpt_result = ExtractResult(
                segments=segments,
                detected_pulse_count=2,
                off_pulse_index=1,
                on_pulse_index=2,
            )
            _load(dpt_result, TestMode.DPT)
            self.assertEqual(win.wave_plot.cursor_type(), "both")
            dpt_interval = win._parameter_interval_us("关断过程", "Ic_off_max")
            self.assertIsNotNone(dpt_interval)
            assert dpt_interval is not None
            win._enable_generic_parameter_interaction("关断过程", "Ic_off_max")
            self.app.processEvents()
            self.assertAlmostEqual(float(win.wave_plot._cursor_a.value()), dpt_interval[0])
            self.assertAlmostEqual(float(win.wave_plot._cursor_b.value()), dpt_interval[1])
            self.assertNotAlmostEqual(float(win.wave_plot._cursor_a.value()), 0.82)
            self.assertNotAlmostEqual(float(win.wave_plot._cursor_b.value()), 0.91)
            self.assertEqual(win._offset_cursor_window_for_current_waveform(), offset_window)

            short_result = ExtractResult(
                segments=segments,
                short_circuit_mode=True,
                short_circuit=ShortCircuitResult(ic_max=100.0, tsc=0.1),
            )
            _load(short_result, TestMode.SHORT_CIRCUIT)
            short_interval = win._parameter_interval_us("短路过程", "短路电流Imax")
            self.assertIsNotNone(short_interval)
            assert short_interval is not None
            win._enable_generic_parameter_interaction("短路过程", "短路电流Imax")
            self.app.processEvents()
            self.assertAlmostEqual(float(win.wave_plot._cursor_a.value()), short_interval[0])
            self.assertAlmostEqual(float(win.wave_plot._cursor_b.value()), short_interval[1])
            self.assertNotAlmostEqual(float(win.wave_plot._cursor_a.value()), 0.82)
            self.assertNotAlmostEqual(float(win.wave_plot._cursor_b.value()), 0.91)
            self.assertEqual(win._offset_cursor_window_for_current_waveform(), offset_window)

            _load(None, TestMode.OFFSET_MEASUREMENT)
            self.assertEqual(win.wave_plot.cursor_type(), "waveform")
            self.assertAlmostEqual(float(win.wave_plot._cursor_a.value()), 0.82)
            self.assertAlmostEqual(float(win.wave_plot._cursor_b.value()), 0.91)
            win.close()
            self.app.processEvents()
        finally:
            if old_value is None:
                settings.remove(NONCOMMERCIAL_NOTICE_SETTINGS_KEY)
            else:
                settings.setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, old_value)

    def test_normal_edge_reference_lines_are_not_drawn(self):
        import numpy as np
        from PyQt6.QtCore import Qt

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import ExtractResult, SegmentIndices
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 128
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("W", "upper")
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(
                t=t,
                channels={
                    "CH1": np.zeros(n),
                    "CH2": np.ones(n),
                    "CH3": np.ones(n),
                    "CH4": np.zeros(n),
                    "CH5": np.zeros(n),
                    "CH6": np.zeros(n),
                },
                meta=TekMetadata(source_path="/fake/no_edge_reference_lines.tss"),
            ),
            profile,
            ExtractResult(
                segments=SegmentIndices(
                    turn_off=(10, 30),
                    turn_on=(70, 90),
                    reverse_recovery=(70, 90),
                    pulse1_off=20,
                    pulse2_on=80,
                )
            ),
        )

        lines = [
            item
            for item in plot.plot.getPlotItem().items
            if getattr(item, "angle", None) == 90
            and hasattr(item, "pen")
            and item.pen.style() == Qt.PenStyle.CustomDashLine
        ]
        self.assertEqual(lines, [])
        self.assertEqual(plot._auxiliary_dash_lines, [])

    def test_short_circuit_edge_reference_lines_are_not_drawn(self):
        import numpy as np
        from PyQt6.QtCore import Qt

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import (
            ExtractResult,
            SegmentIndices,
            ShortCircuitResult,
        )
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 128
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("W", "upper")
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(
                t=t,
                channels={
                    "CH1": np.zeros(n),
                    "CH2": np.ones(n),
                    "CH3": np.ones(n),
                    "CH4": np.zeros(n),
                    "CH5": np.zeros(n),
                    "CH6": np.zeros(n),
                },
                meta=TekMetadata(source_path="/fake/short_circuit_reference_lines.tss"),
            ),
            profile,
            ExtractResult(
                segments=SegmentIndices(
                    turn_off=(10, 30),
                    turn_on=(70, 90),
                    reverse_recovery=(70, 90),
                    pulse1_off=20,
                    pulse2_on=80,
                ),
                short_circuit_mode=True,
                short_circuit=ShortCircuitResult(tsc_start_us=0.2, tsc_end_us=0.7),
            ),
        )
        labels = {
            getattr(getattr(item, "label", None), "format", None)
            for item in plot.plot.getPlotItem().items
        }
        self.assertNotIn("短路开始", labels)
        self.assertNotIn("短路结束", labels)
        lines = [
            item
            for item in plot.plot.getPlotItem().items
            if getattr(item, "angle", None) == 90
            and hasattr(item, "pen")
            and item.pen.style() == Qt.PenStyle.CustomDashLine
        ]
        self.assertEqual(lines, [])
        self.assertEqual(plot._auxiliary_dash_lines, [])

    def test_time_axis_ticks_inline_unit_without_axis_title(self):
        plot = self._make_synthetic_plot()
        vb = plot.plot.getPlotItem().getViewBox()
        vb.setXRange(0.0, 1.0, padding=0.0)
        plot._update_x_ticks()

        bottom_axis = plot.plot.getPlotItem().getAxis("bottom")
        tick_text = [
            text
            for level in bottom_axis._tickLevels
            for _, text in level
        ]
        self.assertFalse(bottom_axis.label.isVisible())
        self.assertIn("0.1us", tick_text)
        self.assertNotIn("0.1", tick_text)
        self.assertLessEqual(bottom_axis.maximumHeight(), 1.0)
        self.assertGreater(len(plot._x_tick_label_items), 0)
        _xr, yr = vb.viewRange()
        for item in plot._x_tick_label_items:
            self.assertAlmostEqual(item.pos().y(), yr[0], places=9)

        right_axis = plot.plot.getPlotItem().getAxis("right")
        plot._update_y_ticks()
        self.assertLessEqual(right_axis.maximumWidth(), 1.0)
        self.assertGreater(len(plot._y_tick_label_items), 0)
        xr, _yr = vb.viewRange()
        for item in plot._y_tick_label_items:
            self.assertAlmostEqual(item.pos().x(), xr[1], places=9)

    def test_scope_graticule_uses_fixed_neutral_dots(self):
        from dpt_extractor.gui.waveform_plot import (
            GRATICULE_DOT_ALPHA,
            GRATICULE_DOT_COLOR,
            GRATICULE_DOT_SIZE_PX,
            GRATICULE_SUBDIVISIONS_PER_DIV,
            _graticule_dot_line_points,
            _graticule_dot_values,
        )

        plot = self._make_synthetic_plot()
        self.assertFalse(plot.plot.getPlotItem().getAxis("bottom").grid)
        self.assertFalse(plot.plot.getPlotItem().getAxis("right").grid)
        self.assertLessEqual(GRATICULE_DOT_SIZE_PX, 1.0)
        self.assertLessEqual(GRATICULE_DOT_ALPHA, 150)
        self.assertGreater(len(plot._graticule_dots.data), 0)
        self.assertEqual(
            plot._graticule_dots.opts["brush"].color().name(),
            GRATICULE_DOT_COLOR,
        )
        self.assertEqual(
            plot._graticule_dots.opts["brush"].color().alpha(),
            GRATICULE_DOT_ALPHA,
        )
        self.assertEqual(plot._graticule_dots.opts["size"], GRATICULE_DOT_SIZE_PX)
        self.assertEqual(GRATICULE_SUBDIVISIONS_PER_DIV, 5)
        x_values = [
            round(float(v), 10)
            for v in _graticule_dot_values([6.0, 9.0], 6.0, 9.0)
        ]
        y_values = [
            round(float(v), 10)
            for v in _graticule_dot_values([-1.0, 1.0], -1.0, 1.0)
        ]
        self.assertEqual(x_values, [6.0, 6.6, 7.2, 7.8, 8.4, 9.0])
        self.assertEqual(y_values, [-1.0, -0.6, -0.2, 0.2, 0.6, 1.0])
        edge_values = [
            round(float(v), 10)
            for v in _graticule_dot_values([6.0, 9.0], 5.3, 9.7)
        ]
        self.assertEqual(edge_values, [5.4, 6.0, 6.6, 7.2, 7.8, 8.4, 9.0, 9.6])
        line_x, line_y = _graticule_dot_line_points(
            [6.0, 9.0],
            [-1.0, 1.0],
            6.0,
            9.0,
            -1.0,
            1.0,
        )
        line_points = {
            (round(float(x), 10), round(float(y), 10))
            for x, y in zip(line_x, line_y)
        }
        self.assertIn((6.6, -1.0), line_points)
        self.assertIn((6.0, -0.6), line_points)
        self.assertNotIn((6.6, -0.6), line_points)
        self.assertEqual(len(line_points), 20)

        plot._on_legend_clicked("CH5")

        self.assertGreater(len(plot._graticule_dots.data), 0)
        self.assertEqual(
            plot._graticule_dots.opts["brush"].color().name(),
            GRATICULE_DOT_COLOR,
        )
        self.assertEqual(
            plot._graticule_dots.opts["brush"].color().alpha(),
            GRATICULE_DOT_ALPHA,
        )
        self.assertEqual(plot._graticule_dots.opts["size"], GRATICULE_DOT_SIZE_PX)

    def test_overview_time_axis_uses_tss_scale_and_inline_units(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 200
        t = np.linspace(0.0, 30e-6, n)
        profile = make_profile("U", "upper")
        bundle = WaveformBundle(
            t=t,
            channels={
                profile.vge: np.linspace(-5.0, 15.0, n),
                profile.vce: np.linspace(50.0, 900.0, n),
                profile.ic: np.linspace(-100.0, 900.0, n),
                profile.il: np.linspace(-50.0, 450.0, n),
                profile.v_diode: np.linspace(0.0, 800.0, n),
                profile.vge_other: np.linspace(-10.0, 10.0, n),
            },
            meta=TekMetadata(
                source_path="/fake/scope-scale.tss",
                horizontal_scale_per_div=3e-6,
            ),
        )
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)
        plot._apply_x_us_per_div(0.5, center_us=12.0)

        bottom_axis = plot._overview_plot.getPlotItem().getAxis("bottom")
        tick_text = [
            text
            for level in bottom_axis._tickLevels
            for _, text in level
        ]
        self.assertIn("3us", tick_text)
        self.assertIn("6us", tick_text)
        self.assertNotIn("3", tick_text)
        self.assertNotIn("5us", tick_text)

    def test_horizontal_scale_controls_align_to_gray_bar_left_center(self):
        plot = self._make_synthetic_plot()
        plot.resize(900, 500)
        plot._scope_scale_bar.show()
        plot.show()
        self.app.processEvents()

        scale_box = plot._x_scale_caption.parentWidget()
        self.assertIsNotNone(scale_box)
        pos = scale_box.mapTo(plot._scope_scale_bar, scale_box.rect().topLeft())
        self.assertLessEqual(pos.x(), 1)
        scale_center_y = pos.y() + scale_box.height() / 2
        bar_center_y = plot._scope_scale_bar.height() / 2
        self.assertLessEqual(abs(scale_center_y - bar_center_y), 1.0)
        plot.close()

    def test_math_channels_display_and_formula_eval(self):
        import numpy as np

        plot = self._make_synthetic_plot()
        self.assertEqual(
            list(plot._channel_boxes),
            ["CH1", "CH2", "CH3", "CH4", "CH5", "CH6", "MATH1"],
        )
        self.assertEqual(plot._display_channel_roles["CH3"], ["Ic", "Irr=Ic-IL"])
        self.assertIn("MATH1", plot._channel_boxes)
        self.assertIn("MATH1", plot._trace_items)
        self.assertIn("CH3 Irr", plot._channel_boxes["CH3"].name_lbl.text())
        self.assertIn("MATH1 Ic", plot._channel_boxes["MATH1"].name_lbl.text())
        self.assertNotIn(">C3 ", plot._channel_boxes["CH3"].name_lbl.text())

        plot._set_math_formula("MATH2", "CH3 + CH4")
        self.assertIn("MATH2", plot._channel_boxes)
        self.assertEqual(plot._unit_for_channel("MATH2"), "A")
        np.testing.assert_allclose(
            plot._trace_raw["MATH2"],
            plot._formula_sources["CH3"] + plot._formula_sources["CH4"],
        )

        plot._set_math_formula("MATH3", "INTG(CH2 * MATH2)")
        self.assertIn("MATH3", plot._channel_boxes)
        self.assertEqual(plot._unit_for_channel("MATH3"), "J")
        plot._set_channel_scale("MATH3", 0.05)
        self.assertAlmostEqual(plot._disp_scale["MATH3"], 0.05)
        self.assertEqual(plot._vdiv_text("MATH3"), "50 mJ/div")

        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QApplication, QLabel
        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        panel = ChannelSettingsPanel(plot, "MATH3", QPoint(0, 0), parent=plot)
        self.assertAlmostEqual(panel._vdiv_spin.value(), 50.0)
        self.assertEqual(panel._vdiv_spin.suffix(), "")
        self.assertEqual(panel._vdiv_unit_combo.currentText(), "mJ")
        panel._step_vdiv(-1)
        self.assertAlmostEqual(plot._disp_scale["MATH3"], 0.02)
        self.assertEqual(plot._vdiv_text("MATH3"), "20 mJ/div")
        self.assertAlmostEqual(panel._vdiv_spin.value(), 20.0)
        panel.close()

        plot._set_channel_scale("MATH2", 0.5)
        self.assertAlmostEqual(plot._disp_scale["MATH2"], 0.5)
        self.assertEqual(plot._vdiv_text("MATH2"), "500 mA/div")
        panel = ChannelSettingsPanel(plot, "MATH2", QPoint(0, 0), parent=plot)
        self.assertAlmostEqual(panel._vdiv_spin.value(), 500.0)
        self.assertEqual(panel._vdiv_unit_combo.currentText(), "mA")
        panel.close()
        plot._set_math_formula("MATH4", "CH2")
        self.assertEqual(plot._unit_for_channel("MATH4"), "V")
        plot._set_channel_scale("MATH4", 0.5)
        self.assertAlmostEqual(plot._disp_scale["MATH4"], 0.5)
        self.assertEqual(plot._vdiv_text("MATH4"), "500 mV/div")

        panel = ChannelSettingsPanel(plot, "MATH4", QPoint(0, 0), parent=plot)
        self.assertAlmostEqual(panel._vdiv_spin.value(), 500.0)
        self.assertEqual(panel._vdiv_unit_combo.currentText(), "mV")
        panel.show()
        QApplication.processEvents()
        div_label = panel.findChild(QLabel, "vdivDivLabel")
        self.assertIsNotNone(div_label)
        spin_right = panel._vdiv_spin.mapTo(panel, panel._vdiv_spin.rect().topRight()).x()
        unit_left = panel._vdiv_unit_combo.mapTo(panel, panel._vdiv_unit_combo.rect().topLeft()).x()
        unit_right = panel._vdiv_unit_combo.mapTo(panel, panel._vdiv_unit_combo.rect().topRight()).x()
        div_left = div_label.mapTo(panel, div_label.rect().topLeft()).x()
        self.assertLess(spin_right, unit_left)
        self.assertLessEqual(unit_right, div_left + 1)
        self.assertIn(
            "V",
            [panel._vdiv_unit_combo.itemText(i) for i in range(panel._vdiv_unit_combo.count())],
        )
        plot._set_channel_scale("MATH4", 1000.0)
        panel.sync_from_plot()
        self.assertAlmostEqual(panel._vdiv_spin.value(), 1.0)
        self.assertEqual(panel._vdiv_unit_combo.currentText(), "kV")
        self.assertEqual(plot._vdiv_text("MATH4"), "1 kV/div")
        panel.close()
        plot.close()

    def test_unmapped_channels_keep_last_known_units(self):
        import numpy as np
        from dataclasses import replace

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 32
        t = np.linspace(0.0, 1e-6, n)
        bundle = WaveformBundle(
            t=t,
            channels={
                **{
                    f"CH{i}": np.linspace(float(i), float(i + 1), n)
                    for i in range(1, 9)
                },
                "MATH1": np.linspace(0.0, 10.0, n),
                "MATH2": np.linspace(10.0, 20.0, n),
            },
            meta=TekMetadata(source_path="/fake/unit-retain.tss"),
        )
        mapped = replace(
            make_profile("U", "upper"),
            vge="CH8",
            vce="CH7",
            v_diode="CH6",
            irr="MATH1",
            il="CH5",
            ic="MATH2",
            vge_other="CH1",
            ic_from_sum_irr_il=False,
            irr_from_ic_minus_il=False,
        )
        unmapped = replace(
            mapped,
            v_diode="",
            irr="",
        )

        plot = WaveformPlot()
        plot.plot_waveforms(bundle, mapped, None)
        self.assertEqual(plot._unit_for_channel("CH6"), "V")
        self.assertEqual(plot._unit_for_channel("MATH1"), "A")

        plot.plot_waveforms(bundle, unmapped, None)
        self.assertEqual(plot._unit_for_channel("CH6"), "V")
        self.assertEqual(plot._unit_for_channel("MATH1"), "A")
        plot.close()

    def test_unmapped_channels_use_tss_units_on_first_plot(self):
        import numpy as np
        from dataclasses import replace

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 16
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, n),
            channels={
                "CH1": np.zeros(n),
                "CH2": np.ones(n),
                "CH6": np.linspace(0.0, 10.0, n),
                "MATH1": np.linspace(10.0, 20.0, n),
            },
            meta=TekMetadata(
                source_path="/fake/source-units.tss",
                channel_units={"CH6": "A", "MATH1": "V"},
            ),
        )
        profile = replace(
            make_profile("U", "upper"),
            vge="CH1",
            vce="CH2",
            ic="",
            il="",
            irr="",
            v_diode="",
            vge_other="",
            ic_from_sum_irr_il=False,
            irr_from_ic_minus_il=False,
        )

        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)

        self.assertEqual(plot._unit_for_channel("CH6"), "A")
        self.assertEqual(plot._unit_for_channel("MATH1"), "V")
        plot.close()

    def test_manual_mapping_keeps_tss_unit_until_user_override(self):
        import numpy as np
        from dataclasses import replace

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 16
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, n),
            channels={
                "CH1": np.zeros(n),
                "CH2": np.ones(n),
                "CH6": np.linspace(0.0, 10.0, n),
            },
            meta=TekMetadata(
                source_path="/fake/source-units-remap.tss",
                channel_units={"CH6": "A"},
            ),
        )
        base_profile = replace(
            make_profile("U", "upper"),
            vge="CH1",
            vce="CH2",
            ic="",
            il="",
            irr="",
            v_diode="",
            vge_other="",
            ic_from_sum_irr_il=False,
            irr_from_ic_minus_il=False,
        )

        plot = WaveformPlot()
        plot.plot_waveforms(bundle, base_profile, None)
        self.assertEqual(plot._unit_for_channel("CH6"), "A")

        plot.plot_waveforms(bundle, replace(base_profile, v_diode="CH6"), None)
        self.assertEqual(plot._unit_for_channel("CH6"), "A")

        plot.set_channel_unit_override("CH6", "V")
        bundle.meta.channel_unit_overrides["CH6"] = "V"
        self.assertEqual(plot._unit_for_channel("CH6"), "V")

        plot.plot_waveforms(bundle, base_profile, None)
        self.assertEqual(plot._unit_for_channel("CH6"), "V")
        plot.set_channel_unit_override("CH6", "")
        bundle.meta.channel_unit_overrides.pop("CH6", None)
        self.assertEqual(plot._unit_for_channel("CH6"), "A")
        plot.close()

    def test_user_math_channels_sync_to_bundle_for_direct_mapping(self):
        import numpy as np
        from dataclasses import replace

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import (
            TekMetadata,
            WaveformBundle,
            bundle_reverse_recovery_current,
            bundle_total_current,
        )

        n = 32
        t = np.linspace(0.0, 1e-6, n)
        ch4 = np.linspace(1.0, 32.0, n)
        ch5 = np.linspace(100.0, 200.0, n)
        channels = {
            f"CH{i}": np.linspace(float(i), float(i + 1), n)
            for i in range(1, 9)
        }
        channels["CH4"] = ch4
        channels["CH5"] = ch5
        bundle = WaveformBundle(
            t=t,
            channels=channels,
            meta=TekMetadata(source_path="/fake/math-sync.tss"),
        )
        profile = replace(
            make_profile("U", "upper"),
            vge="CH1",
            vce="CH2",
            v_diode="CH3",
            irr="-CH4",
            il="CH5",
            ic="",
            vge_other="CH8",
            ic_from_sum_irr_il=True,
            irr_from_ic_minus_il=False,
        )

        win = MainWindow()
        try:
            win.bundle = bundle
            win.profile = profile
            win.wave_plot.plot_waveforms(bundle, profile, None)
            win.wave_plot._set_math_formula("MATH1", "-CH4")
            win.wave_plot._set_math_formula("MATH2", "CH5 + MATH1")
            win._sync_plot_math_to_bundle()

            self.assertEqual(bundle.meta.channel_math_formulas["MATH1"], "-CH4")
            self.assertEqual(
                bundle.meta.channel_math_formulas["MATH2"],
                "CH5 + MATH1",
            )
            self.assertIn("MATH2", bundle.meta.computed_math_channels)
            self.assertEqual(bundle.meta.channel_units["MATH1"], "A")
            self.assertEqual(bundle.meta.channel_units["MATH2"], "A")
            np.testing.assert_allclose(bundle.channels["MATH1"], -ch4)
            np.testing.assert_allclose(bundle.channels["MATH2"], ch5 - ch4)

            direct_profile = replace(
                profile,
                irr="MATH1",
                ic="MATH2",
                ic_from_sum_irr_il=False,
            )
            np.testing.assert_allclose(
                bundle_reverse_recovery_current(bundle, direct_profile),
                -ch4,
            )
            np.testing.assert_allclose(
                bundle_total_current(bundle, direct_profile),
                ch5 - ch4,
            )
        finally:
            win.close()

    def test_source_channel_colors_follow_scope_palette(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 16
        t = np.linspace(0.0, 1e-6, n)
        channels = {
            f"CH{i}": np.linspace(float(i), float(i + 1), n)
            for i in range(1, 9)
        }
        channels.update(
            {
                f"MATH{i}": np.linspace(float(i * 10), float(i * 10 + 1), n)
                for i in range(1, 9)
            }
        )
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(
                t=t,
                channels=channels,
                meta=TekMetadata(source_path="/fake/colors.tss"),
            ),
            make_profile("U", "upper"),
            None,
        )

        expected = {
            "CH1": "#FFF53B",
            "CH2": "#20CFD3",
            "CH3": "#EA4460",
            "CH4": "#91CE32",
            "CH5": "#FF9832",
            "CH6": "#2626BF",
            "CH7": "#E254A6",
            "CH8": "#00E09B",
            "MATH1": "#008000",
            "MATH2": "#A62323",
            "MATH3": "#FF0000",
            "MATH4": "#789ED3",
            "MATH5": "#936756",
            "MATH6": "#6E2B85",
            "MATH7": "#A62323",
            "MATH8": "#96B03C",
        }
        self.assertEqual(list(plot._channel_boxes), list(expected))
        for key, color in expected.items():
            self.assertEqual(plot._trace_style[key][0].upper(), color)

    def test_channel_label_edit_updates_source_label(self):
        plot = self._make_synthetic_plot()
        seen: list[tuple[str, str]] = []
        plot.channelLabelChanged.connect(lambda key, label: seen.append((key, label)))

        plot.set_channel_label("CH3", "Ic")

        self.assertEqual(plot._channel_labels["CH3"], "Ic")
        self.assertIn("CH3 Ic", plot._trace_legend["CH3"])
        self.assertIn("CH3 Ic", plot._channel_boxes["CH3"].name_lbl.text())
        self.assertEqual(seen[-1], ("CH3", "Ic"))

        plot.set_channel_label("CH3", "")
        self.assertNotIn("CH3", plot._channel_labels)
        self.assertEqual(plot._trace_legend["CH3"], "CH3")
        self.assertEqual(seen[-1], ("CH3", ""))

    def test_main_window_channel_label_edit_updates_bundle_metadata(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        win = MainWindow()
        win.bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 8),
            channels={"CH1": np.zeros(8)},
            meta=TekMetadata(channel_labels={"CH1": "Old"}),
        )

        win._on_waveform_channel_label_changed("CH1", "Vge")
        self.assertEqual(win.bundle.meta.channel_labels["CH1"], "Vge")

        win._on_waveform_channel_label_changed("CH1", "")
        self.assertNotIn("CH1", win.bundle.meta.channel_labels)
        win.close()

    def test_label_mapping_button_applies_label_override(self):
        import tempfile
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.channel_mapping import ChannelMappingStore
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        win = MainWindow()
        with tempfile.TemporaryDirectory() as tmp:
            win._channel_store = ChannelMappingStore(Path(tmp) / "maps.yaml")
            win.bundle = WaveformBundle(
                t=np.linspace(0.0, 1e-6, 16),
                channels={f"CH{i}": np.zeros(16) for i in range(1, 7)},
                meta=TekMetadata(
                    channel_labels={
                        "CH1": "L-Vge",
                        "CH2": "L-Vce",
                        "CH3": "IL",
                        "CH4": "Ic",
                        "CH5": "H-Vce",
                        "CH6": "H-Vge",
                    }
                ),
            )
            win.profile = make_profile("U", "upper")

            self.assertEqual(
                [btn.text() for btn in win._context_menu_buttons],
                ["光标", "缩放"],
            )
            win._on_apply_label_mapping_requested()

            stored = win._channel_store.get("U", "upper")
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored.vge, "CH6")
            self.assertEqual(stored.vce, "CH5")
            self.assertEqual(stored.irr, "CH4")
            self.assertEqual(stored.il, "CH3")
            self.assertEqual(win.profile.vge, "CH6")

        win.close()

    def test_waveform_mapping_direct_ic_disables_sum_fallback(self):
        import tempfile
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.channel_mapping import ChannelMappingStore
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        win = MainWindow()
        try:
            phase_idx = win.combo_phase.findData("U")
            bridge_idx = win.combo_bridge.findData("upper")
            if phase_idx >= 0:
                win.combo_phase.setCurrentIndex(phase_idx)
            if bridge_idx >= 0:
                win.combo_bridge.setCurrentIndex(bridge_idx)
            with tempfile.TemporaryDirectory() as tmp:
                win._channel_store = ChannelMappingStore(Path(tmp) / "maps.yaml")
                win.bundle = WaveformBundle(
                    t=np.linspace(0.0, 1e-6, 8),
                    channels={f"CH{i}": np.zeros(8) for i in range(1, 7)}
                    | {"MATH2": np.zeros(8)},
                    meta=TekMetadata(),
                )
                win.profile = make_profile("U", "upper")
                win._recalculate = (  # type: ignore[method-assign]
                    lambda reset_manual=False: None
                )

                win._on_waveform_channel_mapping_requested("MATH2", "ic")

                stored = win._channel_store.get("U", "upper")
                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(stored.ic, "MATH2")
                self.assertFalse(stored.ic_from_sum_irr_il)
        finally:
            win.close()

    def test_main_window_toolbar_compacts_on_small_width(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()

        def assert_test_mode_children_contained():
            group = win.test_mode_group
            for child in (win.lbl_test_mode, win.combo_test_mode):
                top_left = child.mapTo(group, child.rect().topLeft())
                bottom_right = child.mapTo(group, child.rect().bottomRight())
                self.assertGreaterEqual(top_left.x(), 0, child.objectName())
                self.assertGreaterEqual(top_left.y(), 0, child.objectName())
                self.assertLess(bottom_right.x(), group.width(), child.objectName())
                self.assertLess(bottom_right.y(), group.height(), child.objectName())

        win._apply_toolbar_density(860)
        self.app.processEvents()

        self.assertEqual(win.btn_open.text(), "打开")
        self.assertEqual(win.btn_recalc.text(), "重算")
        self.assertEqual(win.btn_export.text(), "导出")
        self.assertTrue(win._context_menu_label.isHidden())
        self.assertTrue(win.lbl_map_status.isHidden())
        self.assertEqual(win._toolbar_rows[0].spacing(), 3)
        self.assertLessEqual(win.toolbar.minimumSizeHint().width(), 860)
        self.assertFalse(hasattr(win, "combo_std"))
        self.assertFalse(hasattr(win, "spin_vdc"))
        self.assertIn("#081719", win.combo_phase.view().styleSheet())
        self.assertFalse(win.report_progress.isHidden())
        self.assertEqual(win.report_progress.percent_text(), "0.0%")
        assert_test_mode_children_contained()

        win._apply_toolbar_density(1600)
        self.assertEqual(win.btn_open.text(), "打开文件")
        self.assertEqual(win.btn_recalc.text(), "重新计算")
        self.assertEqual(win.btn_export.text(), "导出 Excel")
        self.assertTrue(win._context_menu_label.isHidden())
        self.assertFalse(win.lbl_map_status.isHidden())
        self.assertEqual(win.combo_phase.minimumWidth(), 78)
        self.assertEqual(win.combo_bridge.minimumWidth(), 84)
        self.assertEqual(win.combo_temp.minimumWidth(), 68)
        self.assertEqual(win.spin_temp_value.minimumWidth(), 72)
        assert_test_mode_children_contained()
        win.close()

    def test_result_table_uses_compact_content_widths(self):
        from PyQt6.QtGui import QFontMetrics

        from dpt_extractor.gui.result_table import ResultTable
        from dpt_extractor.models.results import (
            ExtractResult,
            ReverseRecoveryResult,
            SegmentIndices,
            TurnOffResult,
            TurnOnResult,
        )

        result = ExtractResult(
            phase="U",
            profile_code="UH",
            source_path="UH_RT.tss",
            vdc=764.1,
            segments=SegmentIndices(
                turn_off=(0, 1),
                turn_on=(2, 3),
                reverse_recovery=(4, 5),
            ),
            turn_off=TurnOffResult(
                ic_off_max=1051.25,
                vce_off_max=1093.25,
                dvdt=7.594,
                didt=10.623,
                dvdt_range="10%→90%",
                didt_range="90%→10%",
                crosstalk_vmax=-2.78,
                crosstalk_vmin=-8.05,
                eoff=88.884,
                eoff_range="V↑~Ic平稳",
            ),
            turn_on=TurnOnResult(
                ic_on_max=1154.22,
                turn_on_current=1036.12,
                dvdt_range="90%→10%",
                didt_range="10%→90%",
                crosstalk_vmax=-0.24,
                crosstalk_vmin=-8.85,
                eon=68.662,
            ),
            reverse_recovery=ReverseRecoveryResult(
                vrr=985.03,
                dvdt_max=12.971,
                didt_irr=13.738,
                err=1.116,
            ),
        )
        table = ResultTable()
        table.set_result(result)

        widths = [table.table.columnWidth(c) for c in range(table.table.columnCount())]
        self.assertEqual(table.table.font().pixelSize(), 12)
        self.assertLessEqual(table.preferred_panel_width(), 465)
        self.assertLessEqual(widths[1], 135)
        self.assertLessEqual(widths[2], 50)
        self.assertLessEqual(widths[3], 90)
        self.assertLessEqual(widths[4], 135)

        max_font_height = 0
        for row in range(table.table.rowCount()):
            for col in range(1, table.table.columnCount()):
                item = table.table.item(row, col)
                if item is None:
                    continue
                metrics = QFontMetrics(item.font())
                max_font_height = max(max_font_height, metrics.height())
                needed = metrics.horizontalAdvance(item.text()) + 2
                self.assertLessEqual(needed, table.table.columnWidth(col), item.text())
        self.assertLessEqual(
            max_font_height + 4,
            table.table.verticalHeader().defaultSectionSize(),
        )
        table.close()

    def test_report_progress_bar_updates(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win._begin_report_progress(5, "准备报告截图...")
        self.assertFalse(win.report_progress.isHidden())
        self.assertEqual(win.report_progress.stage_text(), "报告写入")
        self.assertEqual(win.report_progress.maximum(), 5)
        self.assertEqual(win.report_progress.value(), 0)
        self.assertEqual(win.report_progress.percent_text(), "1.0%")
        self.assertEqual(win.report_progress.detail_text(), "准备截图")
        self.assertEqual(
            win.report_progress.eta_caption_text(),
            "剩余",
        )

        win._set_report_progress(3, 5, "截图 3/5")
        self.assertEqual(win.report_progress.value(), 3)
        self.assertEqual(win.report_progress.format(), "截图 3/5")
        self.assertEqual(win.report_progress.percent_text(), "60.0%")
        self.assertEqual(win.report_progress.detail_text(), "截图 3/5")

        win._set_report_progress_busy("正在写入 Excel...")
        self.assertTrue(win.report_progress.is_busy())
        self.assertEqual(win.report_progress.detail_text(), "写入 Excel")
        self.assertEqual(win.report_progress.eta_text(), "估算中")

        win._finish_report_progress("写入完成 100%", ok=True)
        self.assertEqual(win.report_progress.maximum(), 100)
        self.assertEqual(win.report_progress.value(), 100)
        self.assertEqual(win.report_progress.percent_text(), "100.0%")
        self.assertEqual(win.report_progress.detail_text(), "完成")
        win.close()

    def test_report_progress_panel_compacts_without_widget_overlap(self):
        from dpt_extractor.gui.main_window import ReportProgressPanel

        panel = ReportProgressPanel()
        try:
            cases = (
                (320, "tiny", True, True),
                (420, "compact", True, False),
                (560, "medium", False, False),
                (760, "full", False, False),
            )
            for width, mode, detail_hidden, caption_hidden in cases:
                panel._apply_density_for_width(width)
                panel.resize(width, 30)
                layout = panel.layout()
                assert layout is not None
                layout.setGeometry(panel.rect())

                self.assertEqual(panel._density_mode, mode)
                self.assertEqual(panel._detail_label.isHidden(), detail_hidden)
                self.assertEqual(panel._eta_caption.isHidden(), caption_hidden)
                self.assertEqual(
                    panel.eta_caption_text(),
                    "当前阶段预计剩余" if mode == "full" else "剩余",
                )

                ordered = (
                    panel._stage_label,
                    panel._sep_a,
                    panel._detail_label,
                    panel._sep_b,
                    panel._bar,
                    panel._percent_label,
                    panel._sep_c,
                    panel._eta_caption,
                    panel._eta_label,
                )
                visible = [widget for widget in ordered if not widget.isHidden()]
                for left, right in zip(visible, visible[1:]):
                    self.assertLess(
                        left.geometry().right(),
                        right.geometry().left(),
                        f"{mode}: {left.objectName()} overlaps {right.objectName()}",
                    )
                self.assertLess(
                    visible[-1].geometry().right(),
                    panel.contentsRect().right(),
                    f"{mode}: last progress widget exceeds the panel boundary",
                )

            panel._apply_density_for_width(420)
            panel.resize(420, 30)
            panel.begin(100, "准备报告截图...", stage="报告写入")

            class _FixedEta:
                @staticmethod
                def observe(*_args):
                    return None

                @staticmethod
                def eta_ms():
                    return 754_000.0

            panel._eta_estimator = _FixedEta()
            panel.update_progress(
                100,
                100,
                "插入报告图片 19/19",
                eta_phase="embed_images",
                eta_completed=19,
                eta_total=19,
            )
            layout = panel.layout()
            assert layout is not None
            layout.invalidate()
            layout.setGeometry(panel.rect())

            self.assertEqual(panel.percent_text(), "99.9%")
            self.assertEqual(panel.eta_text(), "12m 34s")
            self.assertIn("报告写入：插入报告图片 19/19", panel.toolTip())
            self.assertIn("当前阶段预计剩余", panel.toolTip())
            self.assertIn("12m 34s", panel.toolTip())
            self.assertEqual(panel.accessibleDescription(), panel.toolTip())
            visible = [widget for widget in ordered if not widget.isHidden()]
            for left, right in zip(visible, visible[1:]):
                self.assertLess(left.geometry().right(), right.geometry().left())
            self.assertLess(
                visible[-1].geometry().right(),
                panel.contentsRect().right(),
            )
        finally:
            panel.close()

    def test_main_window_restored_progress_panel_has_no_overlap(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win.resize(1280, 830)
        win.show()
        try:
            self.app.processEvents()
            panel = win.report_progress
            self.assertLess(panel.width(), 470)
            self.assertEqual(panel._density_mode, "compact")

            ordered = (
                panel._stage_label,
                panel._sep_a,
                panel._detail_label,
                panel._sep_b,
                panel._bar,
                panel._percent_label,
                panel._sep_c,
                panel._eta_caption,
                panel._eta_label,
            )
            visible = [widget for widget in ordered if widget.isVisible()]
            for left, right in zip(visible, visible[1:]):
                self.assertLess(
                    left.geometry().right(),
                    right.geometry().left(),
                    f"{left.objectName()} overlaps {right.objectName()}",
                )
        finally:
            win.close()
            win.deleteLater()
            self.app.processEvents()

    def test_progress_eta_uses_completed_units_and_failure_keeps_last_value(self):
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.task_progress import UnitRateEstimator

        now = [0.0]
        win = MainWindow()
        win._begin_report_progress(100, "准备报告截图...")
        win.report_progress._eta_estimator = UnitRateEstimator(lambda: now[0])
        win._set_report_progress(
            10,
            100,
            "准备报告截图...",
            eta_phase="capture",
            eta_completed=0,
            eta_total=5,
        )
        now[0] = 1.0
        win._set_report_progress(
            20,
            100,
            "截图 1/5",
            eta_phase="capture",
            eta_completed=1,
            eta_total=5,
        )
        self.assertEqual(win.report_progress.eta_text(), "估算中")
        now[0] = 2.0
        win._set_report_progress(
            30,
            100,
            "截图 2/5",
            eta_phase="capture",
            eta_completed=2,
            eta_total=5,
        )
        self.assertEqual(win.report_progress.eta_text(), "3.0 s")

        win._finish_report_progress("写入失败", ok=False)
        self.assertEqual(win.report_progress.value(), 30)
        self.assertEqual(win.report_progress.percent_text(), "30.0%")
        self.assertEqual(win.report_progress.eta_text(), "—")
        win.close()

    def test_completed_eta_phase_does_not_claim_whole_task_is_finished(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win._begin_report_progress(100, "准备报告截图...")
        win._set_report_progress(
            15,
            100,
            "准备报告截图...",
            eta_phase="capture",
            eta_completed=0,
            eta_total=1,
        )
        win._set_report_progress(
            55,
            100,
            "截图 1/1",
            eta_phase="capture",
            eta_completed=1,
            eta_total=1,
        )

        self.assertEqual(win.report_progress.percent_text(), "55.0%")
        self.assertEqual(win.report_progress.eta_text(), "估算中")
        self.assertIn("当前同质阶段", win.report_progress.toolTip())
        win.close()

    def test_positive_sub_second_eta_uses_honest_coarse_display(self):
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.task_progress import UnitRateEstimator

        now = [0.0]
        win = MainWindow()
        win._begin_report_progress(100, "准备报告截图...")
        win.report_progress._eta_estimator = UnitRateEstimator(lambda: now[0])
        win._set_report_progress(
            55,
            100,
            "插入报告图片",
            eta_phase="report-write-images",
            eta_completed=0,
            eta_total=3,
        )
        now[0] = 0.0001
        win._set_report_progress(
            65,
            100,
            "插入报告图片",
            eta_phase="report-write-images",
            eta_completed=1,
            eta_total=3,
        )
        now[0] = 0.0002
        win._set_report_progress(
            78,
            100,
            "插入报告图片",
            eta_phase="report-write-images",
            eta_completed=2,
            eta_total=3,
        )

        self.assertEqual(win.report_progress.percent_text(), "78.0%")
        self.assertEqual(win.report_progress.eta_text(), "<1 s")
        win.close()

    def test_load_progress_bar_updates(self):
        from dpt_extractor.gui.main_window import MainWindow, TASK_PROGRESS_TOTAL
        from dpt_extractor.gui.task_progress import UnitRateEstimator

        now = [0.0]
        win = MainWindow()
        win._load_request_id = 7
        win._begin_task_progress("数据导入", TASK_PROGRESS_TOTAL, "准备读取原始数据...")
        win.report_progress._eta_estimator = UnitRateEstimator(lambda: now[0])
        self.assertEqual(win.report_progress.stage_text(), "数据导入")
        self.assertEqual(win.report_progress.detail_text(), "准备读取")

        win._on_background_load_progress(
            7,
            0,
            TASK_PROGRESS_TOTAL,
            "读取波形通道",
            "load-waveform-channels",
            0,
            4,
        )
        self.assertEqual(win.report_progress.percent_text(), "1.0%")
        self.assertEqual(win.report_progress.eta_text(), "估算中")

        now[0] = 1.0
        win._on_background_load_progress(
            7,
            8750,
            TASK_PROGRESS_TOTAL,
            "读取波形通道 1/4",
            "load-waveform-channels",
            1,
            4,
        )
        self.assertEqual(win.report_progress.percent_text(), "8.8%")
        self.assertEqual(win.report_progress.eta_text(), "估算中")

        now[0] = 2.0
        win._on_background_load_progress(
            7,
            17500,
            TASK_PROGRESS_TOTAL,
            "读取波形通道 2/4",
            "load-waveform-channels",
            2,
            4,
        )
        self.assertEqual(win.report_progress.percent_text(), "17.5%")
        self.assertEqual(win.report_progress.eta_text(), "2.0 s")

        win._on_background_load_progress(
            7,
            35000,
            TASK_PROGRESS_TOTAL,
            "读取完成，正在识别通道...",
        )
        self.assertEqual(win.report_progress.value(), 35000)
        self.assertEqual(win.report_progress.percent_text(), "35.0%")
        self.assertEqual(win.report_progress.detail_text(), "识别通道")
        self.assertEqual(win.report_progress.eta_text(), "估算中")

        win._finish_task_progress("导入完成 100%", ok=True, stage="数据导入")
        self.assertEqual(win.report_progress.value(), 100)
        self.assertEqual(win.report_progress.percent_text(), "100.0%")
        self.assertEqual(win.report_progress.detail_text(), "导入完成")
        self.assertEqual(win.report_progress.eta_text(), "0 ms")
        win.close()

    def test_waveform_load_task_forwards_homogeneous_eta_signal_fields(self):
        from unittest.mock import patch

        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.main_window import _WaveformLoadTask

        events: list[tuple[int, int, int, str, str, int, int]] = []
        finished: list[tuple[int, object]] = []
        task = _WaveformLoadTask(7, "sample.tss", load_config())
        task.signals.progress.connect(
            lambda request_id, value, total, label, phase, completed, unit_total: events.append(
                (
                    int(request_id),
                    int(value),
                    int(total),
                    str(label),
                    str(phase),
                    int(completed),
                    int(unit_total),
                )
            )
        )
        task.signals.finished.connect(
            lambda request_id, outcome: finished.append((int(request_id), outcome))
        )
        expected_outcome = object()

        def fake_compute(path, cfg, progress_callback):
            self.assertEqual(path, "sample.tss")
            progress_callback(
                8750,
                100000,
                "读取波形通道 1/4",
                "load-waveform-channels",
                1,
                4,
            )
            return expected_outcome

        with patch(
            "dpt_extractor.gui.main_window._compute_waveform_load_outcome",
            side_effect=fake_compute,
        ):
            task.run()

        self.assertEqual(
            events,
            [
                (
                    7,
                    8750,
                    100000,
                    "读取波形通道 1/4",
                    "load-waveform-channels",
                    1,
                    4,
                )
            ],
        )
        self.assertEqual(finished, [(7, expected_outcome)])

    def test_report_write_progress_caps_until_finished(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.gui.main_window import (
            MainWindow,
            REPORT_PROGRESS_TOTAL,
            REPORT_PROGRESS_WRITE_DONE_CAP,
            REPORT_PROGRESS_WRITE_START,
        )

        win = MainWindow()
        win._report_request_id = 9
        win._begin_report_progress(REPORT_PROGRESS_TOTAL, "准备报告截图...")
        win._set_report_progress(
            REPORT_PROGRESS_WRITE_START,
            REPORT_PROGRESS_TOTAL,
            "正在写入 Excel...",
        )

        win._on_report_write_progress(9, 10, 10, "保存报告文件")
        self.assertEqual(win.report_progress.value(), REPORT_PROGRESS_WRITE_DONE_CAP)
        self.assertEqual(win.report_progress.percent_text(), "85.0%")
        self.assertEqual(win.report_progress.detail_text(), "保存报告文件")
        self.assertTrue(win.report_progress.is_busy())

        QTimer.singleShot(
            0,
            lambda: win._finish_report_progress("写入完成 100%", ok=True),
        )
        QApplication.processEvents()
        self.assertEqual(win.report_progress.value(), 100)
        self.assertEqual(win.report_progress.percent_text(), "100.0%")
        self.assertEqual(win.report_progress.detail_text(), "完成")
        self.assertFalse(win.report_progress.is_busy())
        win.close()

    def test_report_image_progress_uses_actual_inserted_image_count(self):
        from unittest.mock import Mock

        from dpt_extractor.gui.main_window import (
            MainWindow,
            REPORT_PROGRESS_TOTAL,
        )

        win = MainWindow()
        win._report_request_id = 10
        win._begin_report_progress(REPORT_PROGRESS_TOTAL, "正在写入 Excel...")
        observe = Mock()
        win.report_progress._eta_estimator.observe = observe

        win._on_report_write_progress(10, 1, 2, "插入报告图片")

        observe.assert_called_once_with("report-write-images", 1, 2)
        self.assertEqual(win.report_progress.value(), 70000)
        win.close()

    def test_report_write_progress_is_monotonic_across_real_callback_sequence(self):
        from dpt_extractor.gui.main_window import (
            MainWindow,
            REPORT_PROGRESS_TOTAL,
            REPORT_PROGRESS_WRITE_DATA_DONE,
            REPORT_PROGRESS_WRITE_IMAGES_DONE,
            REPORT_PROGRESS_WRITE_START,
            REPORT_PROGRESS_WRITE_TEMPLATE_DONE,
        )

        win = MainWindow()
        win._report_request_id = 11
        win._begin_report_progress(REPORT_PROGRESS_TOTAL, "正在写入 Excel...")

        observed: list[int] = []
        callbacks = (
            (0, 25, "打开报告文件"),
            (1, 25, "读取报告模板"),
            (2, 25, "写入报告数据"),
            (1, 19, "插入报告图片"),
            (2, 19, "插入报告图片"),
            (19, 19, "插入报告图片"),
        )
        for value, total, label in callbacks:
            win._on_report_write_progress(11, value, total, label)
            observed.append(win.report_progress.value())

        self.assertEqual(observed, sorted(observed))
        self.assertEqual(observed[0], REPORT_PROGRESS_WRITE_START)
        self.assertEqual(observed[1], REPORT_PROGRESS_WRITE_TEMPLATE_DONE)
        self.assertEqual(observed[2], REPORT_PROGRESS_WRITE_DATA_DONE)
        self.assertGreater(observed[3], REPORT_PROGRESS_WRITE_DATA_DONE)
        self.assertEqual(observed[-1], REPORT_PROGRESS_WRITE_IMAGES_DONE)

        win._on_report_write_progress(11, 24, 25, "保存报告文件")
        self.assertEqual(win.report_progress.percent_text(), "85.0%")
        win._finish_report_progress("写入完成 100%", ok=True)
        self.assertEqual(win.report_progress.percent_text(), "100.0%")
        self.assertEqual(win.report_progress.eta_text(), "0 ms")
        win.close()

    def test_running_progress_cannot_publish_100_or_regress(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win._begin_report_progress(100, "开始")
        win._set_report_progress(70, 100, "阶段一")
        win._set_report_progress(60, 100, "乱序旧检查点")
        self.assertEqual(win.report_progress.value(), 70)

        win._set_report_progress(100, 100, "仍在运行")
        self.assertLess(win.report_progress.value(), win.report_progress.maximum())
        self.assertNotEqual(win.report_progress.percent_text(), "100.0%")

        win._finish_report_progress("写入失败", ok=False)
        self.assertNotEqual(win.report_progress.percent_text(), "100.0%")
        self.assertEqual(win.report_progress.eta_text(), "—")
        win.close()

    def test_progress_display_remains_monotonic_when_total_changes(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win._begin_report_progress(100, "开始")
        win._set_report_progress(70, 100, "大分母")
        self.assertEqual(win.report_progress.percent_text(), "70.0%")

        win._set_report_progress(2, 3, "小分母")
        self.assertEqual(win.report_progress.percent_text(), "70.0%")
        win.close()

    def test_first_terminal_state_is_immutable(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win._begin_report_progress(100, "开始")
        win._finish_report_progress("成功", ok=True)
        win._finish_report_progress("迟到失败", ok=False)
        self.assertEqual(win.report_progress.percent_text(), "100.0%")
        self.assertEqual(win.report_progress.detail_text(), "成功")
        self.assertEqual(win.report_progress.eta_text(), "0 ms")

        win._begin_report_progress(100, "重试")
        win._set_report_progress(40, 100, "处理中")
        win._finish_report_progress("失败", ok=False)
        win._finish_report_progress("迟到成功", ok=True)
        self.assertEqual(win.report_progress.percent_text(), "40.0%")
        self.assertEqual(win.report_progress.detail_text(), "失败")
        self.assertEqual(win.report_progress.eta_text(), "—")
        win.close()

    def test_sub_second_eta_display_boundary(self):
        from dpt_extractor.gui.main_window import MainWindow

        class _FixedEstimator:
            def __init__(self, value: float) -> None:
                self.value = value

            def observe(self, *_args) -> None:
                return None

            def eta_ms(self) -> float:
                return self.value

        win = MainWindow()
        win._begin_report_progress(100, "开始")
        estimator = _FixedEstimator(999.0)
        win.report_progress._eta_estimator = estimator  # type: ignore[assignment]
        win._set_report_progress(
            50,
            100,
            "阶段",
            eta_phase="phase",
            eta_completed=1,
            eta_total=2,
        )
        self.assertEqual(win.report_progress.eta_text(), "<1 s")

        estimator.value = 1000.0
        win.report_progress._refresh_readout()
        self.assertEqual(win.report_progress.eta_text(), "1.0 s")
        win.close()

    def test_late_same_request_progress_cannot_rewrite_success_terminal(self):
        from dpt_extractor.gui.main_window import MainWindow, REPORT_PROGRESS_TOTAL

        win = MainWindow()
        win._report_request_id = 12
        win._begin_report_progress(REPORT_PROGRESS_TOTAL, "正在写入 Excel...")
        win._finish_report_progress("写入完成 100%", ok=True)

        win._on_report_write_progress(12, 1, 19, "插入报告图片")
        self.assertEqual(win.report_progress.percent_text(), "100.0%")
        self.assertEqual(win.report_progress.eta_text(), "0 ms")
        win.close()

    def test_production_report_capture_yields_between_view_change_and_grab(self):
        import tempfile

        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.export.report_template import DPT_OVERVIEW_IMAGE_PARAM
        from dpt_extractor.gui.main_window import (
            MainWindow,
            REPORT_PROGRESS_CAPTURE_DONE,
            REPORT_PROGRESS_TOTAL,
        )
        from dpt_extractor.models.results import ExtractResult

        win = MainWindow()
        win.result = ExtractResult()
        params = (
            DPT_OVERVIEW_IMAGE_PARAM,
            ("关断过程", "dv/dt"),
            ("关断过程", "di/dt"),
        )
        selected: list[tuple[str, str]] = []
        saved: list[tuple[str, int]] = []
        writer_calls: list[tuple[int, int, str, str, int]] = []
        win._report_image_params = lambda: params  # type: ignore[method-assign]
        win._on_value_clicked = (  # type: ignore[method-assign]
            lambda section, name: selected.append((section, name))
        )

        def fake_save(path, _size):
            path.write_bytes(b"captured")
            saved.append((path.name, len(selected)))

        def fake_start_writer(
            tempdir,
            images,
            _results,
            *,
            request_id=None,
            temperature_code=None,
            temperature_labels=None,
            phase_code=None,
            image_result_index=None,
        ):
            self.assertEqual(len(images), len(params))
            self.assertTrue(all(path.read_bytes() == b"captured" for path in images.values()))
            self.assertEqual(temperature_labels["LT"], "-40℃")
            writer_calls.append(
                (
                    int(request_id or 0),
                    len(images),
                    str(temperature_code),
                    str(phase_code),
                    int(image_result_index),
                )
            )
            tempdir.cleanup()

        win._save_report_plot_capture = fake_save  # type: ignore[method-assign]
        win._start_report_write_task = fake_start_writer  # type: ignore[method-assign]
        before_window = win.geometry()
        before_plot = win.wave_plot.geometry()
        tempdir = tempfile.TemporaryDirectory()
        win._report_request_id = 41
        win._set_temperature_code("LT")
        win._begin_report_progress(REPORT_PROGRESS_TOTAL, "准备报告截图...")
        win._start_report_capture_sequence(
            tempdir,
            [win.result],
            request_id=41,
        )
        for _ in range(30):
            QApplication.processEvents()
            if writer_calls:
                break

        self.assertEqual(len(saved), len(params))
        self.assertEqual(selected, list(params[1:]))
        self.assertEqual([count for _name, count in saved], [0, 1, 2])
        self.assertEqual(writer_calls, [(41, len(params), "LT", "UH", 0)])
        self.assertIsNone(win._report_capture_state)
        self.assertEqual(win.report_progress.value(), REPORT_PROGRESS_CAPTURE_DONE)
        self.assertEqual(win.geometry(), before_window)
        self.assertEqual(win.wave_plot.geometry(), before_plot)
        win.close()

    def test_toolbar_temperature_values_are_editable_and_persisted(self):
        from PyQt6.QtCore import QSettings

        from dpt_extractor.gui.main_window import (
            MainWindow,
            TEMP_CONDITION_SETTINGS_PREFIX,
        )

        settings = QSettings("DPT", "DPTExtractor")
        keys = [f"{TEMP_CONDITION_SETTINGS_PREFIX}{code}" for code in ("RT", "HT", "LT")]
        old_values = {key: settings.value(key, None) for key in keys}
        for key in keys:
            settings.remove(key)
        try:
            win = MainWindow()
            self.assertEqual(win.combo_temp.currentData(), "RT")
            self.assertAlmostEqual(win.spin_temp_value.value(), 25.0)

            win.spin_temp_value.setValue(32.0)
            self.assertAlmostEqual(
                float(settings.value(f"{TEMP_CONDITION_SETTINGS_PREFIX}RT")),
                32.0,
            )
            win._set_temperature_code("HT")
            self.assertAlmostEqual(win.spin_temp_value.value(), 150.0)
            win.spin_temp_value.setValue(155.0)
            win.close()

            win2 = MainWindow()
            win2._set_temperature_code("RT")
            self.assertAlmostEqual(win2.spin_temp_value.value(), 32.0)
            win2._set_temperature_code("HT")
            self.assertAlmostEqual(win2.spin_temp_value.value(), 155.0)
            win2.close()
        finally:
            for key, value in old_values.items():
                if value is None:
                    settings.remove(key)
                else:
                    settings.setValue(key, value)

    def test_main_window_shows_noncommercial_notice(self):
        from PyQt6.QtCore import QSettings

        from dpt_extractor.gui.main_window import (
            COMMERCIAL_AUTH_QQ,
            MainWindow,
            NONCOMMERCIAL_NOTICE_SETTINGS_KEY,
            commercial_authorization_message,
        )

        message = commercial_authorization_message()
        self.assertIn("禁止任何商业使用", message)
        self.assertIn(COMMERCIAL_AUTH_QQ, message)

        settings = QSettings("DPT", "DPTExtractor")
        old_value = settings.value(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, None)
        settings.remove(NONCOMMERCIAL_NOTICE_SETTINGS_KEY)
        try:
            win = MainWindow()
            self.app.processEvents()

            self.assertFalse(hasattr(win, "license_notice"))
            self.assertTrue(win._should_show_license_notice())
            win._mark_license_notice_shown()
            self.assertFalse(win._should_show_license_notice())
            win.close()
        finally:
            if old_value is None:
                settings.remove(NONCOMMERCIAL_NOTICE_SETTINGS_KEY)
            else:
                settings.setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, old_value)

    def test_irr_interactive_peak_uses_actual_spike(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        irr = np.zeros(120, dtype=np.float64)
        irr[20] = -320.0
        irr[40:80] = np.linspace(0.0, 40.0, 40)
        irr[80] = 250.0
        irr[81:] = 38.0

        self.assertAlmostEqual(win._irr_peak_interactive(irr, 0, len(irr) - 1), 250.0)
        win.close()

    def test_report_plot_capture_size_uses_fixed_plot_baseline(self):
        from dpt_extractor.gui.main_window import (
            MainWindow,
            REPORT_PLOT_CAPTURE_SIZE,
        )

        win = MainWindow()
        win.wave_plot.plot.setFixedSize(320, 240)
        small = win._report_plot_capture_size()
        self.assertEqual(small.width(), REPORT_PLOT_CAPTURE_SIZE.width())
        self.assertEqual(small.height(), REPORT_PLOT_CAPTURE_SIZE.height())

        win.wave_plot.plot.setFixedSize(1800, 960)
        large = win._report_plot_capture_size()
        self.assertEqual(large.width(), REPORT_PLOT_CAPTURE_SIZE.width())
        self.assertEqual(large.height(), REPORT_PLOT_CAPTURE_SIZE.height())
        self.assertAlmostEqual(large.width() / large.height(), 4 / 3, places=3)
        win.close()

    def test_report_plot_capture_keeps_window_geometry_and_writes_complete_png(self):
        import tempfile

        from PyQt6.QtGui import QPixmap

        from dpt_extractor.gui.main_window import (
            MainWindow,
            REPORT_PLOT_CAPTURE_SIZE,
        )

        win = MainWindow()
        win.resize(1000, 720)
        win.show()
        self.app.processEvents()
        target = win.wave_plot
        before_window_geometry = win.geometry()
        before_target_geometry = target.geometry()
        before_minimum = target.minimumSize()
        before_maximum = target.maximumSize()
        before_policy = target.sizePolicy()

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report_capture.png"
            win._save_report_plot_capture(path, REPORT_PLOT_CAPTURE_SIZE)

            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 0)
            image = QPixmap(str(path))
            self.assertFalse(image.isNull())
            self.assertEqual(image.size(), REPORT_PLOT_CAPTURE_SIZE)

        self.assertEqual(win.geometry(), before_window_geometry)
        self.assertEqual(target.geometry(), before_target_geometry)
        self.assertEqual(target.minimumSize(), before_minimum)
        self.assertEqual(target.maximumSize(), before_maximum)
        self.assertEqual(
            target.sizePolicy().horizontalPolicy(), before_policy.horizontalPolicy()
        )
        self.assertEqual(
            target.sizePolicy().verticalPolicy(), before_policy.verticalPolicy()
        )
        win.close()

    def test_report_plot_capture_normalizes_high_dpi_before_centering(self):
        import tempfile

        from PyQt6.QtGui import QColor, QImage, QPixmap

        from dpt_extractor.gui.main_window import (
            MainWindow,
            REPORT_PLOT_CAPTURE_SIZE,
        )

        source = QPixmap(600, 300)
        source.fill(QColor("#ff0000"))
        source.setDevicePixelRatio(1.5)

        class _CaptureTarget:
            def grab(self) -> QPixmap:
                return QPixmap(source)

        win = MainWindow()
        win.wave_plot = _CaptureTarget()  # type: ignore[assignment]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "high_dpi_capture.png"
            win._save_report_plot_capture(path, REPORT_PLOT_CAPTURE_SIZE)
            image = QImage(str(path))

        self.assertFalse(image.isNull())
        self.assertEqual(image.width(), 1280)
        self.assertEqual(image.height(), 960)
        self.assertEqual(image.pixelColor(640, 159), QColor("#11121f"))
        self.assertEqual(image.pixelColor(640, 160), QColor("#ff0000"))
        self.assertEqual(image.pixelColor(640, 799), QColor("#ff0000"))
        self.assertEqual(image.pixelColor(640, 800), QColor("#11121f"))
        win.close()

    def test_report_plot_capture_reports_png_save_failure(self):
        import tempfile

        from dpt_extractor.gui.main_window import (
            MainWindow,
            REPORT_PLOT_CAPTURE_SIZE,
        )

        win = MainWindow()
        with tempfile.TemporaryDirectory() as tmp:
            missing_parent = Path(tmp) / "missing" / "capture.png"
            with self.assertRaisesRegex(RuntimeError, "截图保存失败"):
                win._save_report_plot_capture(
                    missing_parent,
                    REPORT_PLOT_CAPTURE_SIZE,
                )
        win.close()

    def test_parameter_window_solver_is_bounded_and_reserves_post_event_room(self):
        from dpt_extractor.gui.waveform_plot import (
            PARAM_FOCUS_ANCHOR_FRACTION,
            _solve_parameter_x_window,
        )

        x0, x1 = _solve_parameter_x_window(
            (0.0, 10.0),
            5.0,
            (4.9, 5.6),
            base_span_us=2.0,
            guard_us=0.0,
        )
        self.assertAlmostEqual(x1 - x0, 2.0, places=9)
        self.assertAlmostEqual(
            (5.0 - x0) / (x1 - x0), PARAM_FOCUS_ANCHOR_FRACTION, places=9
        )

        expanded0, expanded1 = _solve_parameter_x_window(
            (0.0, 10.0),
            5.0,
            (4.0, 7.0),
            base_span_us=2.0,
            guard_us=0.0,
        )
        self.assertLessEqual(expanded0, 4.0)
        self.assertGreaterEqual(expanded1, 7.0)
        # This synthetic required range cannot coexist with a 12% anchor and
        # the finite right boundary.  Required content and data bounds take
        # precedence, so the anchor may move right but no required point clips.
        self.assertGreaterEqual(
            (5.0 - expanded0) / (expanded1 - expanded0),
            PARAM_FOCUS_ANCHOR_FRACTION,
        )

        # A required point before the preferred 12% anchor must shift the
        # composition right instead of inflating a valid 200 ns/div window.
        conflict0, conflict1 = _solve_parameter_x_window(
            (0.0, 30.0),
            14.451282777854443,
            (14.012719999925231, 15.776319999917897),
            base_span_us=2.0,
            guard_us=0.02,
        )
        self.assertAlmostEqual(conflict1 - conflict0, 2.0, places=9)
        self.assertLessEqual(conflict0, 14.012719999925231 - 0.02)
        self.assertGreaterEqual(conflict1, 15.776319999917897 + 0.02)
        self.assertGreater(
            (14.451282777854443 - conflict0) / (conflict1 - conflict0),
            PARAM_FOCUS_ANCHOR_FRACTION,
        )

        far_left0, far_left1 = _solve_parameter_x_window(
            (0.0, 10.0),
            5.0,
            (3.4, 5.5),
            base_span_us=2.0,
            guard_us=0.0,
        )
        self.assertLessEqual((5.0 - far_left0) / (far_left1 - far_left0), 0.65)
        self.assertGreaterEqual(far_left1 - 5.0, 0.35 * (far_left1 - far_left0))

        left0, left1 = _solve_parameter_x_window(
            (0.0, 10.0),
            0.1,
            (0.0, 1.0),
            base_span_us=2.0,
            guard_us=0.0,
        )
        self.assertAlmostEqual(left0, 0.0, places=9)
        self.assertGreaterEqual(left1, 1.0)

        right0, right1 = _solve_parameter_x_window(
            (0.0, 10.0),
            9.5,
            (9.4, 10.0),
            base_span_us=2.0,
            guard_us=0.0,
        )
        self.assertLessEqual(right0, 9.4)
        self.assertAlmostEqual(right1, 10.0, places=9)

        short0, short1 = _solve_parameter_x_window(
            (2.0, 3.5),
            2.5,
            (2.1, 3.4),
            base_span_us=2.0,
            guard_us=0.0,
        )
        self.assertAlmostEqual(short0, 2.0, places=9)
        self.assertAlmostEqual(short1, 3.5, places=9)

    def test_short_report_skips_desat_screenshot_without_value_or_channel(self):
        from dpt_extractor.export.report_template import SHORT_REPORT_IMAGE_PARAMS
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.results import ExtractResult, ShortCircuitResult

        desat_param = ("短路过程", "Desat动作时间")
        win = MainWindow()
        win.result = ExtractResult(
            short_circuit_mode=True,
            short_circuit=ShortCircuitResult(desat_time=None),
        )

        self.assertIn(desat_param, SHORT_REPORT_IMAGE_PARAMS)
        self.assertNotIn(desat_param, win._report_image_params())

        win.result.short_circuit.desat_time = 1.23
        self.assertNotIn(desat_param, win._report_image_params())

        win._short_circuit_desat_channel = lambda: "CH7"  # type: ignore[method-assign]
        self.assertIn(desat_param, win._report_image_params())
        win.close()

    def test_single_pulse_report_skips_turn_on_and_reverse_recovery_screenshots(self):
        from dpt_extractor.export.report_template import (
            DPT_OVERVIEW_IMAGE_PARAM,
            DPT_REPORT_IMAGE_PARAMS,
        )
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.results import ExtractResult

        win = MainWindow()
        win.result = ExtractResult(single_pulse_mode=True)

        params = win._report_image_params()
        self.assertLess(len(params), len(DPT_REPORT_IMAGE_PARAMS))
        self.assertIn(DPT_OVERVIEW_IMAGE_PARAM, params)
        self.assertIn(("关断过程", "Eoff"), params)
        self.assertFalse(
            any(section in {"开通", "反向恢复"} for section, _name in params)
        )
        win.close()

    def test_mapping_dialog_starts_from_defaults_not_bad_labels(self):
        import tempfile
        import numpy as np

        from dpt_extractor.gui.channel_mapping_dialog import ChannelMappingDialog
        from dpt_extractor.models.channel_mapping import ChannelMappingStore
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 8
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, n),
            channels={f"CH{i}": np.zeros(n) for i in range(1, 7)},
            meta=TekMetadata(
                channel_labels={
                    "CH1": "L-Vge",
                    "CH2": "L-Vce",
                    "CH5": "H-Vce",
                    "CH6": "H-Vge",
                }
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = ChannelMappingStore(Path(tmp) / "maps.yaml")
            dlg = ChannelMappingDialog(
                phase="U",
                bridge="lower",
                bundle=bundle,
                store=store,
            )
            self.assertEqual(dlg._combos["vge"].currentData(), "CH6")
            self.assertEqual(dlg._combos["vce"].currentData(), "CH5")
            self.assertEqual(dlg._combos["ic"].currentData(), "CH3")
            self.assertEqual(dlg._combos["il"].currentData(), "CH4")
            self.assertEqual(dlg._combos["v_diode"].currentData(), "CH2")
            self.assertEqual(dlg._combos["vge_other"].currentData(), "CH1")
            dlg.close()

    def test_upper_mapping_dialog_starts_from_defaults_not_bad_labels(self):
        import tempfile
        import numpy as np

        from dpt_extractor.gui.channel_mapping_dialog import ChannelMappingDialog
        from dpt_extractor.models.channel_mapping import ChannelMappingStore
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 8
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, n),
            channels={f"CH{i}": np.zeros(n) for i in range(1, 7)}
            | {"MATH1": np.zeros(n)},
            meta=TekMetadata(
                channel_labels={
                    "CH1": "L-Vge",
                    "CH2": "L-Vce",
                    "CH3": "Ic",
                    "CH4": "IL",
                    "CH5": "H-Vce",
                    "CH6": "H-Vge",
                    "MATH1": "Vge",
                }
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = ChannelMappingStore(Path(tmp) / "maps.yaml")
            dlg = ChannelMappingDialog(
                phase="U",
                bridge="upper",
                bundle=bundle,
                store=store,
            )
            self.assertEqual(dlg._combos["vge"].currentData(), "CH1")
            self.assertEqual(dlg._combos["vce"].currentData(), "CH2")
            self.assertEqual(dlg._combos["irr"].currentData(), "CH3")
            self.assertEqual(dlg._combos["il"].currentData(), "CH4")
            self.assertEqual(dlg._combos["v_diode"].currentData(), "CH5")
            self.assertEqual(dlg._combos["vge_other"].currentData(), "CH6")
            self.assertTrue(dlg._ic_sum_cb.isChecked())
            idx = dlg._combos["ic"].findData("MATH1")
            self.assertGreaterEqual(idx, 0)
            dlg._combos["ic"].setCurrentIndex(idx)
            mapping = dlg._collect_mapping()
            self.assertEqual(mapping.ic, "MATH1")
            self.assertFalse(mapping.ic_from_sum_irr_il)
            dlg.close()

    def test_mapping_dialog_swaps_conflicting_channel_selection(self):
        import tempfile
        import numpy as np

        from dpt_extractor.gui.channel_mapping_dialog import ChannelMappingDialog
        from dpt_extractor.models.channel_mapping import (
            ChannelMappingStore,
            validate_mapping,
        )
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 8
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, n),
            channels={f"CH{i}": np.zeros(n) for i in range(1, 7)},
            meta=TekMetadata(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = ChannelMappingStore(Path(tmp) / "maps.yaml")
            dlg = ChannelMappingDialog(
                phase="U",
                bridge="upper",
                bundle=bundle,
                store=store,
            )
            idx = dlg._combos["il"].findData("CH3")
            self.assertGreaterEqual(idx, 0)
            dlg._combos["il"].setCurrentIndex(idx)

            self.assertEqual(dlg._combos["il"].currentData(), "CH3")
            self.assertEqual(dlg._combos["irr"].currentData(), "CH4")
            self.assertFalse(validate_mapping(dlg._collect_mapping(), bundle))
            dlg.close()

    def test_mapping_dialog_allows_missing_optional_current_file_channel(self):
        import tempfile
        import numpy as np

        from dpt_extractor.gui.channel_mapping_dialog import ChannelMappingDialog
        from dpt_extractor.models.channel_mapping import ChannelMappingStore
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 8
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, n),
            channels={f"CH{i}": np.zeros(n) for i in range(1, 6)},
            meta=TekMetadata(),
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = ChannelMappingStore(Path(tmp) / "maps.yaml")
            dlg = ChannelMappingDialog(
                phase="U",
                bridge="upper",
                bundle=bundle,
                store=store,
            )

            self.assertEqual(dlg._combos["vge_other"].currentData(), "CH6")
            idx = dlg._combos["vce"].findData("CH5")
            self.assertGreaterEqual(idx, 0)
            dlg._combos["vce"].setCurrentIndex(idx)
            dlg._on_apply()

            self.assertTrue(dlg.was_applied())
            saved = store.get("U", "upper")
            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertEqual(saved.vce, "CH5")
            self.assertEqual(saved.vge_other, "CH6")
            dlg.close()

    def test_added_math_channel_can_be_deleted(self):
        plot = self._make_synthetic_plot()
        self.assertFalse(plot._can_delete_channel("CH1"))
        self.assertTrue(plot._can_delete_channel("MATH1"))

        plot._set_math_formula("MATH2", "CH3 + CH4")
        self.assertTrue(plot._can_delete_channel("MATH2"))
        self.assertIn("MATH2", plot._channel_boxes)
        self.assertIn("MATH2", plot._zero_handles)

        plot._toggle_channel_visibility("MATH2")
        self.assertIn("MATH2", plot._hidden_channels)
        plot._delete_math_channel("MATH2")

        self.assertNotIn("MATH2", plot._trace_items)
        self.assertNotIn("MATH2", plot._channel_boxes)
        self.assertNotIn("MATH2", plot._zero_handles)
        self.assertNotIn("MATH2", plot._math_formulas)
        self.assertNotIn("MATH2", plot._math_source_keys)
        self.assertNotIn("MATH2", plot._formula_sources)
        self.assertNotIn("MATH2", plot._hidden_channels)
        self.assertEqual(plot._next_math_key(), "MATH2")

    def test_math_channel_settings_panel_has_delete_action(self):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QLineEdit, QPushButton

        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        plot = self._make_synthetic_plot()
        plot._set_math_formula("MATH2", "CH3 + CH4")

        panel = ChannelSettingsPanel(plot, "MATH2", QPoint(0, 0), parent=plot)
        formula_value = panel.findChild(QLineEdit, "chFormulaValue")
        formula_btn = panel.findChild(QPushButton, "chFormulaBtn")
        delete_btn = panel.findChild(QPushButton, "chDeleteBtn")
        self.assertIsNotNone(formula_value)
        self.assertEqual(formula_value.text(), "CH3 + CH4")
        self.assertTrue(formula_value.isReadOnly())
        self.assertIsNotNone(formula_btn)
        self.assertEqual(formula_btn.text(), "编辑")
        self.assertIsNotNone(delete_btn)
        self.assertEqual(delete_btn.text(), "删除 Math 通道")
        delete_btn.click()
        self.assertNotIn("MATH2", plot._trace_items)

        ch_panel = ChannelSettingsPanel(plot, "CH1", QPoint(0, 0), parent=plot)
        self.assertIsNone(ch_panel.findChild(QPushButton, "chDeleteBtn"))
        ch_panel.close()

    def test_channel_boxes_do_not_expose_context_menu(self):
        plot = self._make_synthetic_plot()
        plot._set_math_formula("MATH2", "CH3 + CH4")

        self.assertFalse(hasattr(plot, "_build_channel_box_menu"))
        self.assertFalse(hasattr(plot, "_show_channel_box_menu"))
        self.assertFalse(hasattr(plot._channel_boxes["MATH2"], "contextMenuRequested"))
        self.assertFalse(hasattr(plot._channel_boxes["CH6"], "contextMenuRequested"))

    def test_zoom_overview_region_tracks_and_pans_view(self):
        from PyQt6.QtWidgets import QSizePolicy

        plot = self._make_synthetic_plot()
        self.assertTrue(plot._overview_plot.isHidden())

        plot._apply_x_us_per_div(0.02, center_us=0.5)
        self.assertFalse(plot._overview_plot.isHidden())
        self.assertFalse(plot._scope_scale_bar.isHidden())
        self.assertFalse(plot._zoom_toggle_btn.isHidden())
        self.assertEqual(
            plot._scope_scale_bar.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Expanding,
        )
        self.assertEqual(plot._scope_scale_bar.maximumHeight(), 20)
        scale_margins = plot._scope_scale_bar.layout().contentsMargins()
        self.assertEqual(scale_margins.left(), 0)
        self.assertEqual(scale_margins.top(), 0)
        self.assertEqual(scale_margins.bottom(), 0)
        self.assertEqual(plot._x_scale_caption.height(), 16)
        self.assertEqual(plot._local_zoom_close_btn.height(), 16)
        self.assertIs(plot._zoom_toggle_btn.parentWidget(), plot._overview_plot)
        r0, r1 = plot._overview_region.getRegion()
        self.assertAlmostEqual(r0, 0.25, places=3)
        self.assertAlmostEqual(r1, 0.75, places=3)

        plot._overview_region.setRegion((0.2, 0.4))
        x0, x1 = plot.plot.getPlotItem().getViewBox().viewRange()[0]
        self.assertAlmostEqual(x0, 0.2, places=3)
        self.assertAlmostEqual(x1, 0.4, places=3)

        plot._fit_full_range()
        self.assertTrue(plot._overview_plot.isHidden())
        self.assertTrue(plot._scope_scale_bar.isHidden())
        self.assertFalse(plot._zoom_toggle_btn.isHidden())
        self.assertIs(plot._zoom_toggle_btn.parentWidget(), plot.plot)

        plot._toggle_zoom_preview()
        self.assertFalse(plot._overview_plot.isHidden())
        self.assertFalse(plot._scope_scale_bar.isHidden())
        self.assertIs(plot._zoom_toggle_btn.parentWidget(), plot._overview_plot)

        plot._exit_local_zoom()
        self.assertTrue(plot._overview_plot.isHidden())
        self.assertTrue(plot._scope_scale_bar.isHidden())

    def test_tss_derived_ic_max_cursor_uses_imported_math_trace(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 300
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("U", "upper")
        # Upper-bridge raw Irr has a negative dominant commutation platform;
        # IL is positive and larger, so the imported CH3+CH4 Math is also the
        # numerically authoritative logical Ic (not merely a formula-name hit).
        irr = -np.linspace(100.0, 700.0, n)
        il = np.linspace(200.0, 1200.0, n)
        math_ic = irr + il
        bundle = WaveformBundle(
            t=t,
            channels={
                "CH1": np.linspace(-5.0, 15.0, n),
                "CH2": np.linspace(50.0, 900.0, n),
                "CH3": irr,
                "CH4": il,
                "CH5": np.linspace(0.0, 600.0, n),
                "CH6": np.zeros(n),
                "MATH1": math_ic,
            },
            meta=TekMetadata(
                source_path="/fake/imported.tss",
                channel_vdiv={"MATH1": 200.0},
                channel_math_formulas={"MATH1": "CH3+CH4"},
            ),
        )
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)

        self.assertEqual(plot._display_key_for_channel("ic"), "MATH1")
        self.assertIn("Ic", plot._display_channel_roles["MATH1"])

        plot.enable_interval_interaction(
            0.2,
            0.8,
            lambda *_args: None,
            show_horizontal_peak=True,
        )
        peak = float(np.max(math_ic))
        plot.set_interval_peak_horizontal(peak, channel="ic", t0_us=0.2, t1_us=0.8)

        self.assertEqual(plot._readout_channel(), "MATH1")
        self.assertIsNotNone(plot._h_cursor_a)
        assert plot._h_cursor_a is not None
        win = (t >= 0.2e-6) & (t <= 0.8e-6)
        expected_peak = float(np.max(math_ic[win]))
        self.assertAlmostEqual(
            plot._from_disp("ic", float(plot._h_cursor_a.value())),
            expected_peak,
            delta=1.0,
        )

    def test_derived_ic_without_matching_math_uses_internal_logic_trace(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import (
            TekMetadata,
            WaveformBundle,
            bundle_total_current,
        )

        n = 300
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("U", "upper")
        irr = np.linspace(100.0, 700.0, n)
        il = np.linspace(20.0, 320.0, n)
        unrelated_math = np.linspace(-5.0, 5.0, n)
        bundle = WaveformBundle(
            t=t,
            channels={
                "CH1": np.linspace(-5.0, 15.0, n),
                "CH2": np.linspace(50.0, 900.0, n),
                "CH3": irr,
                "CH4": il,
                "CH5": np.linspace(0.0, 600.0, n),
                "CH6": np.zeros(n),
                "MATH1": unrelated_math,
            },
            meta=TekMetadata(
                source_path="/fake/no_matching_math.tss",
                channel_math_formulas={"MATH1": "CH1"},
            ),
        )
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)

        self.assertEqual(plot._display_key_for_channel("ic"), "LOGIC_IC")
        expected = bundle_total_current(bundle, profile)
        np.testing.assert_allclose(plot._interactive_ic, expected)
        np.testing.assert_allclose(plot._trace_raw["LOGIC_IC"], expected)
        self.assertEqual(plot._unit_for_channel("ic"), "A")

    def test_peak_cursor_uses_full_resolution_signed_current(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import MAX_PLOT_POINTS, WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = MAX_PLOT_POINTS * 3
        t = np.arange(n, dtype=np.float64) * 1e-9
        profile = make_profile("W", "lower")
        ic = np.full(n, -20.0, dtype=np.float64)
        peak_idx = MAX_PLOT_POINTS + 123
        ic[peak_idx] = -900.0
        bundle = WaveformBundle(
            t=t,
            channels={
                profile.vge: np.zeros(n),
                profile.vce: np.linspace(0.0, 900.0, n),
                profile.ic: ic,
                profile.il: np.zeros(n),
                profile.v_diode: np.linspace(0.0, 700.0, n),
                profile.vge_other: np.zeros(n),
            },
            meta=TekMetadata(source_path="/fake/full-resolution.tss"),
        )
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)

        t_peak_us = float(t[peak_idx] * 1e6)
        plot.enable_interval_interaction(
            t_peak_us - 0.02,
            t_peak_us + 0.02,
            lambda *_args: None,
            show_horizontal_peak=True,
        )
        plot.set_interval_peak_horizontal(
            900.0,
            channel="ic",
            t0_us=t_peak_us - 0.02,
            t1_us=t_peak_us + 0.02,
            use_abs_peak=True,
        )

        self.assertEqual(len(plot._trace_raw[profile.ic]), n)
        self.assertIsNotNone(plot._h_cursor_a)
        assert plot._h_cursor_a is not None
        self.assertAlmostEqual(
            plot._from_disp("ic", float(plot._h_cursor_a.value())),
            -900.0,
            places=6,
        )

    def test_math_channel_can_open_settings_for_mapping(self):
        from PyQt6.QtCore import QPoint

        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        plot = self._make_synthetic_plot()
        panel = ChannelSettingsPanel(plot, "MATH1", QPoint(0, 0), parent=plot)
        self.assertGreaterEqual(panel._mapping_combo.findData("ic"), 0)
        self.assertEqual(panel._mapping_combo.findData(""), 0)
        self.assertEqual(panel._label_edit.text(), "Ic")
        panel.close()

    def test_channel_settings_label_edits_raw_label_only(self):
        from PyQt6.QtCore import QPoint

        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        plot = self._make_synthetic_plot()
        panel = ChannelSettingsPanel(plot, "CH3", QPoint(0, 0), parent=plot)
        self.assertEqual(panel._label_edit.text(), "Irr")
        self.assertNotIn("CH3", panel._label_edit.text())

        panel._label_edit.setText("Ic")
        panel._on_label_changed()

        self.assertEqual(plot._channel_labels["CH3"], "Ic")
        self.assertIn("CH3 Ic", plot._trace_legend["CH3"])
        self.assertIn("CH3 Ic", plot._channel_boxes["CH3"].name_lbl.text())
        panel.close()

    def test_channel_settings_custom_unit_and_invert_controls(self):
        import numpy as np
        from PyQt6.QtCore import QPoint

        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        plot = self._make_synthetic_plot()
        panel = ChannelSettingsPanel(plot, "CH3", QPoint(0, 0), parent=plot)

        self.assertFalse(panel._unit_edit.isEnabled())
        self.assertEqual(panel._unit_toggle.text(), "关")
        panel._unit_toggle.click()
        self.assertTrue(panel._unit_toggle.isChecked())
        self.assertEqual(panel._unit_toggle.text(), "开")
        panel._unit_edit.setText("V")
        panel._on_unit_changed()
        self.assertEqual(plot._unit_for_channel("CH3"), "V")
        panel._unit_toggle.click()
        self.assertFalse(panel._unit_toggle.isChecked())
        self.assertEqual(panel._unit_toggle.text(), "关")
        self.assertEqual(plot._unit_for_channel("CH3"), "A")

        panel._invert_toggle.click()
        self.assertEqual(panel._invert_toggle.text(), "开")
        self.assertTrue(plot.channel_inversion_enabled("CH3"))
        self.assertNotIn("-CH3", plot._trace_items)
        np.testing.assert_allclose(
            plot.current_display_raw("CH3"),
            -plot._trace_raw["CH3"],
        )
        sample = plot._sample_cursor_channel("CH3", float(plot._trace_t_us[0]))
        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertAlmostEqual(sample[0], -float(plot._trace_raw["CH3"][0]))

        seen: list[tuple[str, str]] = []
        plot.channelMappingRequested.connect(
            lambda source, role: seen.append((source, role))
        )
        idx = panel._mapping_combo.findData("irr")
        self.assertGreaterEqual(idx, 0)
        panel._mapping_combo.setCurrentIndex(idx)
        panel._on_mapping_apply()
        self.assertEqual(seen[-1], ("CH3", "irr"))
        panel.close()

    def test_channel_inversion_survives_replot_as_display_state(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot

        bundle, profile = self._make_synthetic_bundle()
        raw = np.asarray(bundle.channels["CH3"], dtype=np.float64).copy()
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)

        returned = plot.set_channel_inversion_enabled("-CH3", True)
        bundle.meta.channel_display_inversions.add("CH3")
        plot.plot_waveforms(bundle, profile, None)

        self.assertEqual(returned, "CH3")
        self.assertNotIn("-CH3", plot._trace_items)
        self.assertTrue(plot.channel_inversion_enabled("CH3"))
        np.testing.assert_allclose(plot.current_display_raw("CH3"), -raw)
        sample = plot._sample_cursor_channel("CH3", float(plot._trace_t_us[0]))
        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertAlmostEqual(sample[0], -float(raw[0]))
        plot.close()

    def test_tss_default_inversion_sets_channel_panel_switch(self):
        import numpy as np

        from PyQt6.QtCore import QPoint

        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel
        from dpt_extractor.gui.waveform_plot import WaveformPlot

        bundle, profile = self._make_synthetic_bundle()
        raw = np.asarray(bundle.channels["CH3"], dtype=np.float64).copy()
        bundle.meta.source_channel_inversions.add("CH3")
        bundle.meta.channel_display_inversions.add("CH3")
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)
        panel = ChannelSettingsPanel(plot, "CH3", QPoint(0, 0), parent=plot)

        self.assertTrue(plot.channel_inversion_enabled("CH3"))
        self.assertTrue(panel._invert_toggle.isChecked())
        self.assertEqual(panel._invert_toggle.text(), "开")
        np.testing.assert_allclose(plot.current_display_raw("CH3"), raw)

        panel._invert_toggle.click()
        bundle.meta.channel_display_inversions.discard("CH3")
        plot.plot_waveforms(bundle, profile, None)
        self.assertFalse(plot.channel_inversion_enabled("CH3"))
        np.testing.assert_allclose(plot.current_display_raw("CH3"), -raw)
        panel.close()
        plot.close()

    def test_user_math_formula_uses_current_display_inversion(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot

        bundle, profile = self._make_synthetic_bundle()
        raw = np.asarray(bundle.channels["CH3"], dtype=np.float64).copy()
        bundle.meta.channel_display_inversions.add("CH3")
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)

        plot._set_math_formula("MATH2", "CH3")
        np.testing.assert_allclose(plot._trace_raw["MATH2"], -raw)
        plot.close()

    def test_user_math_formula_refreshes_before_inversion_export(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot

        bundle, profile = self._make_synthetic_bundle()
        raw = np.asarray(bundle.channels["CH3"], dtype=np.float64).copy()
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)
        plot._set_math_formula("MATH2", "CH3")
        np.testing.assert_allclose(plot._trace_raw["MATH2"], raw)

        plot.set_channel_inversion_enabled("CH3", True)

        np.testing.assert_allclose(plot._trace_raw["MATH2"], -raw)
        exported, _expr, _scale, _offset = plot.export_user_math_channels()[
            "MATH2"
        ]
        np.testing.assert_allclose(exported, -raw)
        plot.close()

    def test_static_waveform_curve_cache_survives_trace_data_refresh(self):
        import numpy as np
        from PyQt6.QtWidgets import QGraphicsItem

        plot = self._make_synthetic_plot()
        try:
            for item in plot._trace_items.values():
                self.assertEqual(
                    item.curve.cacheMode(),
                    QGraphicsItem.CacheMode.DeviceCoordinateCache,
                )

            item = plot._trace_items["CH3"]
            before = np.asarray(item.curve.getData()[1], dtype=np.float64).copy()
            plot._set_channel_offset(
                "CH3",
                float(plot._disp_offset["CH3"]) + 0.5,
            )
            after = np.asarray(item.curve.getData()[1], dtype=np.float64)
            self.assertFalse(np.array_equal(after, before))
            self.assertEqual(
                item.curve.cacheMode(),
                QGraphicsItem.CacheMode.DeviceCoordinateCache,
            )
        finally:
            plot.close()

    def test_channel_settings_panel_control_bounds_are_compact(self):
        from PyQt6.QtCore import QPoint, QRect
        from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        plot = self._make_synthetic_plot()
        panel = ChannelSettingsPanel(plot, "CH3", QPoint(0, 0), parent=plot)
        panel.show()
        QApplication.processEvents()

        def panel_rect(widget):
            return QRect(widget.mapTo(panel, widget.rect().topLeft()), widget.size())

        def assert_inside_panel(name, widget):
            rect = panel_rect(widget)
            self.assertGreaterEqual(rect.left(), panel.rect().left(), name)
            self.assertGreaterEqual(rect.top(), panel.rect().top(), name)
            self.assertLessEqual(rect.right(), panel.rect().right(), name)
            self.assertLessEqual(rect.bottom(), panel.rect().bottom(), name)
            return rect

        def assert_no_overlaps(group_name, widgets):
            rects = [
                (name, assert_inside_panel(f"{group_name}:{name}", widget))
                for name, widget in widgets
                if widget.isVisible()
            ]
            for i, (name_a, rect_a) in enumerate(rects):
                for name_b, rect_b in rects[i + 1 :]:
                    self.assertFalse(
                        rect_a.intersects(rect_b),
                        f"{group_name}: {name_a} overlaps {name_b}: "
                        f"{rect_a.getRect()} vs {rect_b.getRect()}",
                    )
            return rects

        div_label = panel.findChild(QLabel, "vdivDivLabel")
        self.assertIsNotNone(div_label)
        scale_buttons = panel.findChildren(QPushButton, "chScaleStepBtn")
        pos_buttons = panel.findChildren(QPushButton, "chStepBtn")
        zero_btn = panel.findChild(QPushButton, "chZeroBtn")
        self.assertEqual(len(scale_buttons), 2)
        self.assertEqual(len(pos_buttons), 2)
        self.assertIsNotNone(zero_btn)
        setting_frames = [
            ("display_setting", panel._display_setting),
            ("invert_setting", panel._invert_setting),
            ("unit_setting", panel._unit_setting),
            ("vdiv_setting", panel._vdiv_setting),
            ("position_setting", panel._position_setting),
            ("label_setting", panel._label_setting),
            ("mapping_setting", panel._mapping_setting),
        ]
        setting_rects = {
            name: assert_inside_panel(name, frame)
            for name, frame in setting_frames
        }
        self.assertFalse(
            setting_rects["display_setting"].intersects(setting_rects["invert_setting"])
        )
        self.assertFalse(
            setting_rects["display_setting"].intersects(setting_rects["unit_setting"])
        )
        self.assertFalse(
            setting_rects["invert_setting"].intersects(setting_rects["unit_setting"])
        )

        row_groups = [
            (
                "top_switches",
                [
                    ("display_toggle", panel._display_toggle),
                    ("invert_toggle", panel._invert_toggle),
                    ("unit_toggle", panel._unit_toggle),
                    ("unit_edit", panel._unit_edit),
                ],
            ),
            (
                "vertical_scale",
                [
                    ("scale_value", panel._vdiv_spin),
                    ("scale_unit", panel._vdiv_unit_combo),
                    ("scale_div", div_label),
                    ("scale_up", scale_buttons[0]),
                    ("scale_down", scale_buttons[1]),
                ],
            ),
            (
                "position",
                [
                    ("position_value", panel._pos_spin),
                    ("position_up", pos_buttons[0]),
                    ("position_down", pos_buttons[1]),
                    ("zero", zero_btn),
                ],
            ),
            ("label", [("label_edit", panel._label_edit)]),
            (
                "mapping",
                [
                    ("mapping_combo", panel._mapping_combo),
                    ("mapping_apply", panel._mapping_apply),
                ],
            ),
        ]

        row_bounds = []
        for group_name, widgets in row_groups:
            rects = assert_no_overlaps(group_name, widgets)
            left = min(rect.left() for _, rect in rects)
            top = min(rect.top() for _, rect in rects)
            right = max(rect.right() for _, rect in rects)
            bottom = max(rect.bottom() for _, rect in rects)
            row_bounds.append((group_name, QRect(left, top, right - left + 1, bottom - top + 1)))

        for (name_a, rect_a), (name_b, rect_b) in zip(row_bounds, row_bounds[1:]):
            self.assertLess(
                rect_a.bottom(),
                rect_b.top(),
                f"{name_a} row overlaps {name_b} row: "
                f"{rect_a.getRect()} vs {rect_b.getRect()}",
            )

        def assert_control_in_setting(setting_name, control_name, widget, max_left_gap):
            setting_rect = setting_rects[setting_name]
            control_rect = assert_inside_panel(control_name, widget)
            self.assertLessEqual(setting_rect.left(), control_rect.left(), control_name)
            self.assertGreaterEqual(setting_rect.right(), control_rect.right(), control_name)
            self.assertLessEqual(
                control_rect.left() - setting_rect.left(),
                max_left_gap,
                f"{control_name} is too far from {setting_name}: "
                f"{control_rect.getRect()} vs {setting_rect.getRect()}",
            )

        assert_control_in_setting(
            "display_setting", "display_toggle", panel._display_toggle, 82
        )
        assert_control_in_setting(
            "invert_setting", "invert_toggle", panel._invert_toggle, 82
        )
        assert_control_in_setting("unit_setting", "unit_toggle", panel._unit_toggle, 110)
        assert_control_in_setting(
            "vdiv_setting", "scale_value", panel._vdiv_spin, 110
        )
        assert_control_in_setting(
            "position_setting", "position_value", panel._pos_spin, 110
        )
        assert_control_in_setting(
            "mapping_setting", "mapping_combo", panel._mapping_combo, 110
        )

        self.assertLessEqual(panel.width(), 430)
        self.assertLessEqual(panel._display_setting.width(), 96)
        self.assertLessEqual(panel._invert_setting.width(), 96)
        self.assertLessEqual(panel._unit_setting.width(), 160)
        self.assertLessEqual(panel._display_toggle.width(), 80)
        self.assertLessEqual(panel._invert_toggle.width(), 80)
        self.assertLessEqual(panel._unit_toggle.width(), 80)
        self.assertLessEqual(panel._unit_edit.width(), 60)
        self.assertLessEqual(panel._vdiv_spin.width(), 80)
        self.assertLessEqual(panel._vdiv_unit_combo.width(), 82)
        self.assertLessEqual(panel._pos_spin.width(), 96)
        self.assertLessEqual(panel._label_edit.width(), 190)
        self.assertLessEqual(panel._mapping_combo.width(), 180)
        consistent_height_widgets = [
            panel._display_toggle,
            panel._invert_toggle,
            panel._unit_toggle,
            panel._unit_edit,
            panel._vdiv_spin,
            panel._vdiv_unit_combo,
            panel._pos_spin,
            *scale_buttons,
            *pos_buttons,
            zero_btn,
            panel._label_edit,
            panel._mapping_combo,
            panel._mapping_apply,
        ]
        for widget in consistent_height_widgets:
            self.assertGreaterEqual(widget.height(), 40)
            self.assertLessEqual(widget.height(), 44)

        panel.close()
        plot.close()

    def test_main_window_channel_unit_override_updates_bundle_metadata(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        win = MainWindow()
        win.bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 8),
            channels={"CH1": np.zeros(8)},
            meta=TekMetadata(channel_units={"CH1": "V"}),
        )

        win.wave_plot.set_channel_unit_override("CH1", "A")
        self.assertEqual(win.bundle.meta.channel_unit_overrides["CH1"], "A")
        win.wave_plot.set_channel_unit_override("CH1", "")
        self.assertNotIn("CH1", win.bundle.meta.channel_unit_overrides)
        win.close()

    def test_parameter_max_default_intervals_use_algorithm_windows(self):
        import numpy as np

        os.environ["LOCALAPPDATA"] = str(ROOT / ".tmp" / "localappdata")

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import (
            ExtractResult,
            SegmentIndices,
            TurnOffResult,
        )
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        off = "\u5173\u65ad\u8fc7\u7a0b"
        on = "\u5f00\u901a"
        rr = "\u53cd\u5411\u6062\u590d"

        n = 1000
        dt = 10e-9
        t = np.arange(n) * dt
        profile = make_profile("U", "lower")
        vge = np.zeros(n)
        vge[100:420] = 15.0
        vge[620:900] = 15.0
        vce = np.ones(n) * 800.0
        vce[100:420] = 50.0
        vce[420:450] = np.linspace(50.0, 1100.0, 30)
        vce[450:480] = np.linspace(1100.0, 800.0, 30)
        vce[760:900] = 50.0
        ic = np.zeros(n)
        ic[120:390] = 100.0
        ic[390:450] = np.linspace(100.0, 0.0, 60)
        ic[650:780] = np.linspace(0.0, 120.0, 130)
        il = np.ones(n) * 10.0
        irr = np.zeros(n)
        irr[610:760] = np.linspace(0.0, 80.0, 150)
        irr[760:850] = np.linspace(80.0, 0.0, 90)
        vd = np.zeros(n)
        vd[600:900] = np.linspace(0.0, 500.0, 300)
        vgo = np.zeros(n)
        bundle = WaveformBundle(
            t=t,
            channels={
                profile.vge: vge,
                profile.vce: vce,
                profile.ic: ic,
                profile.il: il,
                profile.irr: irr,
                profile.v_diode: vd,
                profile.vge_other: vgo,
            },
            meta=TekMetadata(sample_interval=dt),
        )
        segs = SegmentIndices(
            turn_off=(350, 520),
            turn_on=(580, 900),
            reverse_recovery=(720, 820),
            pulse1_on=100,
            pulse1_off=400,
            pulse2_on=620,
            pulse2_off=900,
        )
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = ExtractResult(
            segments=segs,
            turn_off=TurnOffResult(delta_vce=300.0, vce_off_max=1100.0),
        )

        off_ic = win._parameter_max_interval_indices(off, "Ic_off_max")
        off_vce = win._parameter_max_interval_indices(off, "Vce_off_max")
        on_ic = win._parameter_max_interval_indices(on, "Ic_on_max")
        on_vce = win._parameter_max_interval_indices(on, "Vce_on_max")
        rr_irr = win._parameter_max_interval_indices(rr, "Irr")

        self.assertIsNotNone(off_ic)
        self.assertIsNotNone(off_vce)
        self.assertIsNotNone(on_ic)
        self.assertIsNotNone(on_vce)
        self.assertIsNotNone(rr_irr)
        assert off_ic is not None and off_vce is not None and on_ic is not None and on_vce is not None and rr_irr is not None

        self.assertLess(off_ic[1], segs.turn_off[1])
        self.assertGreater(off_vce[0], segs.turn_off[0])
        self.assertLess(off_vce[1], segs.turn_off[1])
        self.assertLess(
            off_vce[1] - off_vce[0],
            segs.turn_off[1] - segs.turn_off[0],
        )
        self.assertLessEqual(off_vce[0], int(np.argmax(vce)))
        self.assertGreaterEqual(off_vce[1], int(np.argmax(vce)))
        self.assertGreater(on_ic[0], segs.turn_on[0])
        self.assertLess(on_vce[1], segs.turn_on[1])
        self.assertEqual(
            rr_irr,
            (max(segs.reverse_recovery[0], segs.pulse2_on), segs.turn_on[1] - 1),
        )

        for section, name, idx in (
            (off, "Ic_off_max", off_ic),
            (off, "Vce_off_max", off_vce),
            (on, "Ic_on_max", on_ic),
            (on, "Vce_on_max", on_vce),
            (rr, "Irr", rr_irr),
        ):
            iv = win._parameter_interval_us(section, name)
            self.assertIsNotNone(iv)
            assert iv is not None
            self.assertAlmostEqual(iv[0], t[idx[0]] * 1e6)
            self.assertAlmostEqual(iv[1], t[idx[1]] * 1e6)
        win.close()

    def test_math_integral_uses_full_resolution_sources(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import MAX_PLOT_POINTS, WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = MAX_PLOT_POINTS * 2 + 123
        t = np.arange(n, dtype=np.float64) * 1e-9
        profile = make_profile("W", "lower")
        channels = {
            profile.vge: np.ones(n),
            profile.vce: np.ones(n),
            profile.ic: np.ones(n),
            profile.il: np.zeros(n),
            profile.v_diode: np.ones(n),
            profile.vge_other: np.zeros(n),
        }
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(t=t, channels=channels, meta=TekMetadata(source_path="/fake/full.tss")),
            profile,
            None,
        )

        plot._set_math_formula("MATH1", "INTG(CH2 * CH3)")
        self.assertEqual(len(plot._formula_sources["MATH1"]), n)
        self.assertEqual(len(plot._trace_raw["MATH1"]), n)
        display_x, _display_y = plot._trace_items["MATH1"].getData()
        self.assertLess(len(display_x), n)
        self.assertAlmostEqual(plot._formula_sources["MATH1"][-1], t[-1] - t[0], places=12)

    def test_formula_functions_match_numpy_reference(self):
        import numpy as np

        plot = self._make_synthetic_plot()
        plot._formula_sources["CH1"] = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
        plot._formula_sources["CH2"] = np.array([1.0, 2.0, 4.0, 8.0, 16.0])
        plot._formula_sources["CH3"] = np.array([0.0, 1.0, 0.0, 1.0, 1.0])
        plot._formula_sources["CH4"] = np.array([1.0, 1.0, 0.0, 0.0, 1.0])
        plot._formula_t_s = np.arange(5, dtype=np.float64)

        checks = {
            "ABS(CH1)": np.abs(plot._formula_sources["CH1"]),
            "SQRT(CH2)": np.sqrt(plot._formula_sources["CH2"]),
            "LOG(CH2)": np.log10(plot._formula_sources["CH2"]),
            "LN(CH2)": np.log(plot._formula_sources["CH2"]),
            "EXP(CH1)": np.exp(plot._formula_sources["CH1"]),
            "SIN(CH1)": np.sin(plot._formula_sources["CH1"]),
            "COS(CH1)": np.cos(plot._formula_sources["CH1"]),
            "TAN(CH1)": np.tan(plot._formula_sources["CH1"]),
            "CEIL(CH1/2)": np.ceil(plot._formula_sources["CH1"] / 2.0),
            "FLOOR(CH1/2)": np.floor(plot._formula_sources["CH1"] / 2.0),
            "INV(CH2)": 1.0 / plot._formula_sources["CH2"],
            "MIN(CH1,CH2)": np.minimum(plot._formula_sources["CH1"], plot._formula_sources["CH2"]),
            "MAX(CH1,CH2)": np.maximum(plot._formula_sources["CH1"], plot._formula_sources["CH2"]),
            "AND(CH3,CH4)": np.logical_and(plot._formula_sources["CH3"] != 0, plot._formula_sources["CH4"] != 0).astype(float),
            "OR(CH3,CH4)": np.logical_or(plot._formula_sources["CH3"] != 0, plot._formula_sources["CH4"] != 0).astype(float),
            "XOR(CH3,CH4)": np.logical_xor(plot._formula_sources["CH3"] != 0, plot._formula_sources["CH4"] != 0).astype(float),
            "NAND(CH3,CH4)": (~np.logical_and(plot._formula_sources["CH3"] != 0, plot._formula_sources["CH4"] != 0)).astype(float),
            "NOR(CH3,CH4)": (~np.logical_or(plot._formula_sources["CH3"] != 0, plot._formula_sources["CH4"] != 0)).astype(float),
            "EQV(CH3,CH4)": (~np.logical_xor(plot._formula_sources["CH3"] != 0, plot._formula_sources["CH4"] != 0)).astype(float),
            "CH1 > 0": (plot._formula_sources["CH1"] > 0).astype(float),
        }
        for expr, expected in checks.items():
            np.testing.assert_allclose(plot._evaluate_math_formula("MATH9", expr), expected, err_msg=expr)
        np.testing.assert_allclose(
            plot._evaluate_math_formula("MATH9", "DERIV(CH2)"),
            np.gradient(plot._formula_sources["CH2"], plot._formula_t_s),
        )
        np.testing.assert_allclose(
            plot._evaluate_math_formula("MATH9", "PI + E"),
            np.full(5, np.pi + np.e),
        )

    def test_formula_energy_matches_result_table_integrators(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.metrics.iec_windows import (
            IntegrationWindow,
            integrate_err_recovery,
            integrate_vi_window,
        )
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 2000
        t = np.arange(n, dtype=np.float64) * 1e-9
        v = 700.0 + 80.0 * np.sin(np.linspace(0.0, 6.0 * np.pi, n))
        i = 950.0 + 120.0 * np.cos(np.linspace(0.0, 4.0 * np.pi, n))
        vd = -400.0 + 50.0 * np.sin(np.linspace(0.0, 2.0 * np.pi, n))
        irr = -150.0 + 25.0 * np.cos(np.linspace(0.0, 5.0 * np.pi, n))
        profile = make_profile("W", "upper")
        channels = {
            "CH1": np.zeros(n),
            "CH2": v,
            "CH3": i,
            "CH4": irr,
            "CH5": vd,
            "CH6": np.zeros(n),
        }
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(t=t, channels=channels, meta=TekMetadata(source_path="/fake/energy.tss")),
            profile,
            None,
        )
        win = IntegrationWindow(300, 1500, float(t[300]), float(t[1500]))

        plot._set_math_formula("MATH1", "INTG(CH2*CH3)")
        integ = plot._formula_sources["MATH1"]
        actual_mj = float(integ[win.i_end - 1] - integ[win.i_start]) * 1e3
        self.assertAlmostEqual(actual_mj, integrate_vi_window(t, v, i, win), places=9)

        plot._set_math_formula("MATH2", "INTG(ABS(CH5)*ABS(CH4))")
        integ = plot._formula_sources["MATH2"]
        actual_mj = float(integ[win.i_end - 1] - integ[win.i_start]) * 1e3
        self.assertAlmostEqual(actual_mj, integrate_err_recovery(t, vd, irr, win), places=9)

    def test_original_math_channels_load_by_default_on_new_file(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 128
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("W", "upper")
        base_channels = {
            "CH1": np.zeros(n),
            "CH2": np.ones(n),
            "CH3": np.ones(n),
            "CH4": np.zeros(n),
            "CH5": np.zeros(n),
            "CH6": np.zeros(n),
        }
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(t=t, channels=base_channels, meta=TekMetadata(source_path="/fake/no_math.tss")),
            profile,
            None,
        )
        plot._set_math_formula("MATH1", "CH2+CH3")
        self.assertIn("MATH1", plot._math_source_keys)

        original_math = np.linspace(10.0, 20.0, n)
        channels_with_math = dict(base_channels)
        channels_with_math["MATH1"] = original_math
        plot.plot_waveforms(
            WaveformBundle(
                t=t,
                channels=channels_with_math,
                meta=TekMetadata(
                    source_path="/fake/with_math.tss",
                    channel_vdiv={"MATH1": 0.05},
                    channel_math_formulas={"MATH1": "CH3+CH4"},
                ),
            ),
            profile,
            None,
        )
        self.assertIn("MATH1", plot._channel_boxes)
        self.assertEqual(plot._math_formulas, {"MATH1": "CH3+CH4"})
        self.assertNotIn("MATH1", plot._math_source_keys)
        self.assertAlmostEqual(plot._manual_vdiv["MATH1"], 0.05)
        self.assertAlmostEqual(plot._disp_scale["MATH1"], 0.05)
        self.assertEqual(plot._unit_for_channel("MATH1"), "A")
        np.testing.assert_allclose(plot._trace_raw["MATH1"], original_math)

        from PyQt6.QtCore import QPoint
        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        panel = ChannelSettingsPanel(plot, "MATH1", QPoint(0, 0), parent=plot)
        self.assertAlmostEqual(panel._vdiv_spin.value(), 50.0)
        self.assertEqual(panel._vdiv_unit_combo.currentText(), "mA")
        panel.close()

    def test_channel_settings_position_steps_by_tenth_div(self):
        from PyQt6.QtCore import QPoint

        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        plot = self._make_synthetic_plot()
        panel = ChannelSettingsPanel(plot, "CH5", QPoint(0, 0), parent=plot)
        start = float(panel._pos_spin.value())
        panel._step_position(+1)
        self.assertAlmostEqual(panel._pos_spin.value(), start + 0.1)
        self.assertAlmostEqual(plot._disp_offset["CH5"], start + 0.1)
        panel._step_position(-1)
        self.assertAlmostEqual(panel._pos_spin.value(), start)
        panel.close()

    def test_computed_non_loss_math_respects_tss_setup_vdiv_when_present(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 128
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("W", "upper")
        channels = {
            "CH1": np.zeros(n),
            "CH2": np.ones(n),
            "CH3": np.ones(n),
            "CH4": np.zeros(n),
            "CH5": np.zeros(n),
            "CH6": np.zeros(n),
            "MATH2": np.linspace(0.0, 240.0, n),
        }
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(
                t=t,
                channels=channels,
                meta=TekMetadata(
                    source_path="/fake/computed_math.tss",
                    channel_vdiv={"MATH2": 0.05},
                    channel_math_formulas={"MATH2": "CH2+CH3"},
                    computed_math_channels={"MATH2"},
                ),
            ),
            profile,
            None,
        )

        self.assertAlmostEqual(plot._manual_vdiv["MATH2"], 0.05)
        self.assertAlmostEqual(plot._disp_scale["MATH2"], 0.05)

    def test_computed_loss_math_uses_tss_vdiv_and_ypos_on_load(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import ExtractResult, SegmentIndices
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 128
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("W", "upper")
        loss = np.full(n, 5.0)
        loss[10:30] = np.linspace(0.0, 0.4, 20)
        loss[70:90] = np.linspace(0.1, 0.3, 20)
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(
                t=t,
                channels={
                    "CH1": np.zeros(n),
                    "CH2": np.ones(n),
                    "CH3": np.ones(n),
                    "CH4": np.zeros(n),
                    "CH5": np.zeros(n),
                    "CH6": np.zeros(n),
                    "MATH2": loss,
                },
                meta=TekMetadata(
                    source_path="/fake/computed_loss_scope_setup.tss",
                    channel_vdiv={"MATH2": 0.05},
                    channel_y_position={"MATH2": -2.75},
                    channel_math_formulas={"MATH2": "INTG(CH2*MATH1)"},
                    computed_math_channels={"MATH2"},
                ),
            ),
            profile,
            ExtractResult(
                segments=SegmentIndices(
                    turn_off=(10, 30),
                    turn_on=(70, 90),
                    reverse_recovery=(70, 90),
                    pulse1_off=20,
                    pulse2_on=80,
                )
            ),
        )

        self.assertAlmostEqual(plot._manual_vdiv["MATH2"], 0.05)
        self.assertAlmostEqual(plot._disp_scale["MATH2"], 0.05)
        self.assertAlmostEqual(plot._disp_offset["MATH2"], -2.75)
        self.assertAlmostEqual(plot._zero_handle_display_y("MATH2"), -2.75)

    def test_math_without_tss_vdiv_auto_uses_math_fit_ladder(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 128
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("W", "upper")
        channels = {
            "CH1": np.zeros(n),
            "CH2": np.ones(n),
            "CH3": np.ones(n),
            "CH4": np.zeros(n),
            "CH5": np.zeros(n),
            "CH6": np.zeros(n),
            "MATH2": np.linspace(0.0, 240.0, n),
        }
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(
                t=t,
                channels=channels,
                meta=TekMetadata(
                    source_path="/fake/auto_math.tss",
                    channel_math_formulas={"MATH2": "INTG(CH2*MATH1)"},
                    computed_math_channels={"MATH2"},
                ),
            ),
            profile,
            None,
        )

        self.assertNotIn("MATH2", plot._manual_vdiv)
        self.assertEqual(plot._disp_scale["MATH2"], 50.0)
        _x, y = plot._trace_items["MATH2"].getData()
        self.assertAlmostEqual(float(np.nanmin(y)), -2.4, places=6)
        self.assertAlmostEqual(float(np.nanmax(y)), 2.4, places=6)

    def test_loss_math_without_tss_vdiv_uses_switching_windows(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import ExtractResult, SegmentIndices
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 128
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("W", "upper")
        loss = np.full(n, 5.0)
        loss[10:30] = np.linspace(0.0, 0.4, 20)
        loss[70:90] = np.linspace(0.1, 0.3, 20)
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(
                t=t,
                channels={
                    "CH1": np.zeros(n),
                    "CH2": np.ones(n),
                    "CH3": np.ones(n),
                    "CH4": np.zeros(n),
                    "CH5": np.zeros(n),
                    "CH6": np.zeros(n),
                    "MATH2": loss,
                },
                meta=TekMetadata(
                    source_path="/fake/windowed_loss_math.tss",
                    channel_math_formulas={"MATH2": "INTG(CH2*MATH1)"},
                ),
            ),
            profile,
            ExtractResult(
                segments=SegmentIndices(
                    turn_off=(10, 30),
                    turn_on=(70, 90),
                    reverse_recovery=(70, 90),
                    pulse1_off=20,
                    pulse2_on=80,
                )
            ),
        )

        self.assertNotIn("MATH2", plot._manual_vdiv)
        self.assertAlmostEqual(plot._disp_scale["MATH2"], 0.05)
        self.assertEqual(plot._vdiv_text("MATH2"), "50 mJ/div")
        fit = np.concatenate([loss[10:30], loss[70:90]])
        fit_y = fit / plot._disp_scale["MATH2"] + plot._disp_offset["MATH2"]
        self.assertGreaterEqual(float(np.nanmin(fit_y)), -4.05)
        self.assertLessEqual(float(np.nanmax(fit_y)), 4.05)

    def test_loss_math_with_tss_50mj_vdiv_uses_switching_windows_for_initial_offset(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import DISP_HALF_DIV, WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import ExtractResult, SegmentIndices
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 128
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("W", "upper")
        loss = np.linspace(0.0, 0.6, n)
        loss[10:30] = np.linspace(0.065, 0.334, 20)
        loss[70:90] = np.linspace(0.080, 0.300, 20)
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(
                t=t,
                channels={
                    "CH1": np.zeros(n),
                    "CH2": np.ones(n),
                    "CH3": np.ones(n),
                    "CH4": np.zeros(n),
                    "CH5": np.zeros(n),
                    "CH6": np.zeros(n),
                    "MATH2": loss,
                },
                meta=TekMetadata(
                    source_path="/fake/scope_50mj_loss_math.tss",
                    channel_vdiv={"MATH2": 0.05},
                    channel_math_formulas={"MATH2": "INTG(CH2*MATH1)"},
                ),
            ),
            profile,
            ExtractResult(
                segments=SegmentIndices(
                    turn_off=(10, 30),
                    turn_on=(70, 90),
                    reverse_recovery=(70, 90),
                    pulse1_off=20,
                    pulse2_on=80,
                )
            ),
        )

        self.assertAlmostEqual(plot._manual_vdiv["MATH2"], 0.05)
        self.assertEqual(plot._vdiv_text("MATH2"), "50 mJ/div")
        self.assertTrue(plot._trace_items["MATH2"].opts["clipToView"])

        fit = np.concatenate([loss[10:30], loss[70:90]])
        fit_y = fit / plot._disp_scale["MATH2"] + plot._disp_offset["MATH2"]
        self.assertGreaterEqual(float(np.nanmin(fit_y)), -4.05)
        self.assertLessEqual(float(np.nanmax(fit_y)), 4.05)

        full_y = loss / plot._disp_scale["MATH2"] + plot._disp_offset["MATH2"]
        self.assertGreater(float(np.nanmax(full_y)), DISP_HALF_DIV)
        visible_low_mj = (-DISP_HALF_DIV - plot._disp_offset["MATH2"]) * 50.0
        visible_high_mj = (DISP_HALF_DIV - plot._disp_offset["MATH2"]) * 50.0
        self.assertGreaterEqual(visible_low_mj, -60.0)
        self.assertLessEqual(visible_low_mj, -40.0)
        self.assertGreaterEqual(visible_high_mj, 440.0)
        self.assertLessEqual(visible_high_mj, 460.0)

    def test_loss_math_zero_handles_keep_zero_reference(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import ExtractResult, SegmentIndices
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 128
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("W", "upper")
        loss2 = np.linspace(0.018, 0.082, n)
        loss3 = np.linspace(0.004, 0.018, n)
        plot = WaveformPlot()
        plot.plot_waveforms(
            WaveformBundle(
                t=t,
                channels={
                    "CH1": np.zeros(n),
                    "CH2": np.ones(n),
                    "CH3": np.ones(n),
                    "CH4": np.zeros(n),
                    "CH5": np.zeros(n),
                    "CH6": np.zeros(n),
                    "MATH2": loss2,
                    "MATH3": loss3,
                },
                meta=TekMetadata(
                    source_path="/fake/dual_loss_math.tss",
                    channel_vdiv={"MATH2": 0.01, "MATH3": 0.001},
                    channel_math_formulas={
                        "MATH2": "INTG(CH2*MATH1)",
                        "MATH3": "INTG(CH5*MATH1)",
                    },
                ),
            ),
            profile,
            ExtractResult(
                segments=SegmentIndices(
                    turn_off=(10, 30),
                    turn_on=(70, 90),
                    reverse_recovery=(70, 90),
                    pulse1_off=20,
                    pulse2_on=80,
                )
            ),
        )

        plot._update_zero_handle_positions()
        vb = plot.plot.getPlotItem().getViewBox()

        for key in ("MATH2", "MATH3"):
            expected_y = plot._to_disp(key, 0.0)
            self.assertAlmostEqual(plot._zero_handle_display_y(key), expected_y, places=6)
            handle_y = float(vb.mapSceneToView(plot._zero_handles[key].scenePos()).y())
            self.assertAlmostEqual(handle_y, expected_y, places=6)

            before = plot._disp_offset[key]
            plot._on_zero_handle_dragged(key, expected_y)
            self.assertAlmostEqual(plot._disp_offset[key], before, places=6)

    def test_zero_handle_drag_uses_lightweight_channel_refresh(self):
        plot = self._make_synthetic_plot()
        plot._set_math_formula("MATH2", "CH3 + CH4")

        calls: list[object] = []
        original_full = plot._refresh_visible_traces
        original_overview = plot._refresh_overview_traces
        original_single = plot._refresh_visible_trace

        def full_refresh(*args, **kwargs):
            calls.append("full")
            return original_full(*args, **kwargs)

        def overview_refresh(*args, **kwargs):
            calls.append("overview")
            return original_overview(*args, **kwargs)

        def single_refresh(key):
            calls.append(("single", key))
            return original_single(key)

        plot._refresh_visible_traces = full_refresh
        plot._refresh_overview_traces = overview_refresh
        plot._refresh_visible_trace = single_refresh
        try:
            plot._on_zero_handle_dragged("MATH2", -2.0)
        finally:
            plot._refresh_visible_traces = original_full
            plot._refresh_overview_traces = original_overview
            plot._refresh_visible_trace = original_single

        self.assertAlmostEqual(plot._disp_offset["MATH2"], -2.0)
        self.assertIn(("single", "MATH2"), calls)
        self.assertNotIn("full", calls)
        self.assertNotIn("overview", calls)

    def test_selected_channel_updates_physical_y_axis(self):
        plot = self._make_synthetic_plot()
        self.assertEqual(plot._axis_channel(), "CH3")
        plot._on_legend_clicked("CH5")
        self.assertEqual(plot._raised_key, "CH5")
        self.assertIsNone(plot._highlighted_key)
        self.assertEqual(plot._axis_channel(), "CH5")
        self.assertEqual(plot._axis_last_signature[0], "CH5")
        self.assertEqual(plot._format_axis_value(1200.0, "V"), "1.2 kV")
        self.assertEqual(plot._format_axis_value(1000.0, "W"), "1 KW")
        self.assertEqual(plot._format_axis_value(1_000_000.0, "W"), "1 MW")
        self.assertEqual(plot._format_axis_value(0.5, "W"), "500 mW")
        self.assertEqual(plot._format_axis_value(0.0005, "W"), "500 µW")
        self.assertEqual(plot._format_axis_value(1500.0, "KW"), "1.5 MW")
        self.assertIn("background:#151722", plot._channel_boxes["CH5"].styleSheet())
        self.assertNotIn("background:#181b26", plot._channel_boxes["CH5"].styleSheet())

    def test_power_peak_focus_does_not_highlight_or_select_channel(self):
        plot = self._make_synthetic_plot()
        plot._set_math_formula("MATH2", "CH2 * CH3")
        self.assertEqual(plot._unit_for_channel("MATH2"), "W")
        plot._on_legend_clicked("CH5")
        active_before = plot._active_channel
        raised_before = plot._raised_key
        highlighted_before = plot._highlighted_key

        matched = plot.focus_power_peak_in_window(0.2, 0.8)

        self.assertIsNotNone(matched)
        self.assertEqual(matched[0], "MATH2")
        self.assertEqual(plot._active_channel, active_before)
        self.assertEqual(plot._raised_key, raised_before)
        self.assertEqual(plot._highlighted_key, highlighted_before)
        aux_point = plot._cursor_auxiliary_point()
        self.assertIsNotNone(aux_point)
        self.assertEqual(aux_point[0], "MATH2")

    def test_vdiv_unit_combo_fits_prefixed_units(self):
        from PyQt6.QtCore import QPoint

        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        plot = self._make_synthetic_plot()
        plot._set_channel_scale("CH2", 200_000.0)
        plot._set_math_formula("MATH2", "CH2 * CH3")
        plot._set_channel_scale("MATH2", 200_000.0)

        for key, expected_unit in (("CH2", "kV"), ("MATH2", "kW")):
            panel = ChannelSettingsPanel(plot, key, QPoint(0, 0), parent=plot)
            self.app.processEvents()
            combo = panel._vdiv_unit_combo
            self.assertEqual(combo.currentData(), expected_unit)
            text_width = combo.fontMetrics().horizontalAdvance(expected_unit)
            self.assertGreater(combo.width(), 58)
            self.assertGreaterEqual(combo.width() - 48, text_width)
            self.assertGreaterEqual(
                panel._vdiv_input.width(),
                76 + combo.width() + 46,
            )
            panel.close()

    def test_reverse_recovery_power_uses_200kw_default_vdiv(self):
        plot = self._make_synthetic_plot()
        vce_key = plot._display_key_for_channel("vce")
        ic_key = plot._display_key_for_channel("ic")
        vd_key = plot._display_key_for_channel("v_diode")
        irr_key = plot._display_key_for_channel("irr")

        plot._set_math_formula("MATH2", f"{vce_key} * {ic_key}")
        plot._set_math_formula("MATH3", f"{vd_key} * {irr_key}")

        self.assertEqual(plot._unit_for_channel("MATH2"), "W")
        self.assertEqual(plot._unit_for_channel("MATH3"), "W")
        self.assertEqual(plot._disp_scale["MATH2"], 500_000.0)
        self.assertEqual(plot._disp_scale["MATH3"], 200_000.0)
        self.assertEqual(plot._vdiv_text("MATH3"), "200 kW/div")

    def test_y_axis_ticks_anchor_to_channel_zero_and_vdiv(self):
        plot = self._make_synthetic_plot()
        plot._on_legend_clicked("CH6")
        self.assertFalse(plot.plot.getPlotItem().getAxis("left").isVisible())
        self.assertTrue(plot.plot.getPlotItem().getAxis("right").isVisible())
        tick_text = [
            text
            for level in plot.plot.getPlotItem().getAxis("right")._tickLevels
            for _, text in level
        ]
        for expected in ("0 V", "3 V", "6 V", "9 V", "12 V"):
            self.assertIn(expected, tick_text)

    def test_dragging_math_zero_handle_selects_math_axis(self):
        plot = self._make_synthetic_plot()
        plot._set_math_formula("MATH2", "INTG(ABS(CH5)*ABS(CH4))")
        plot._set_channel_scale("MATH2", 0.05)

        plot._on_zero_handle_dragged("MATH2", -3.5)
        plot._on_zero_handle_drag_finished("MATH2")

        self.assertEqual(plot._highlighted_key, "MATH2")
        self.assertEqual(plot._axis_channel(), "MATH2")
        tick_text = [
            text
            for level in plot.plot.getPlotItem().getAxis("right")._tickLevels
            for _, text in level
        ]
        self.assertIn("50 mJ", tick_text)
        self.assertIn("0 J", tick_text)

    def test_selection_zoom_applies_local_x_and_y_range(self):
        from PyQt6.QtCore import QPointF

        plot = self._make_synthetic_plot()
        vb = plot.plot.getPlotItem().getViewBox()
        p0 = vb.mapViewToScene(QPointF(0.20, -2.0))
        p1 = vb.mapViewToScene(QPointF(0.70, 2.0))
        self.assertTrue(plot._apply_selection_zoom(p0, p1))
        xr, yr = vb.viewRange()
        self.assertAlmostEqual(xr[0], 0.20, places=2)
        self.assertAlmostEqual(xr[1], 0.70, places=2)
        self.assertAlmostEqual(yr[0], -2.0, places=2)
        self.assertAlmostEqual(yr[1], 2.0, places=2)

    def test_selection_zoom_switch_toggles_until_closed(self):
        plot = self._make_synthetic_plot()
        self.assertFalse(plot._selection_zoom_enabled)
        self.assertFalse(plot._zoom_select_btn.isChecked())

        captured: list[bool] = []
        plot.selectionZoomChanged.connect(captured.append)

        plot.set_selection_zoom_switch_enabled(True)
        self.assertTrue(plot._selection_zoom_enabled)
        self.assertTrue(plot._zoom_select_btn.isChecked())
        self.assertEqual(captured, [True])

        plot._finish_selection_zoom_mode()
        self.assertFalse(plot._selection_zoom_enabled)
        self.assertFalse(plot._zoom_select_btn.isChecked())
        self.assertEqual(captured, [True, False])

        plot._arm_selection_zoom()
        self.assertTrue(plot._selection_zoom_enabled)
        self.assertTrue(plot._zoom_select_btn.isChecked())
        plot.set_selection_zoom_switch_enabled(False)
        self.assertFalse(plot._selection_zoom_enabled)
        self.assertFalse(plot._zoom_select_btn.isChecked())

    def test_selection_zoom_disarms_after_drag(self):
        from PyQt6.QtCore import QPointF, Qt

        class _DragEvent:
            def __init__(
                self,
                scene_pos: QPointF,
                *,
                start: bool = False,
                finish: bool = False,
            ) -> None:
                self._scene_pos = scene_pos
                self._start = start
                self._finish = finish
                self.accepted = False

            def button(self):
                return Qt.MouseButton.LeftButton

            def scenePos(self):
                return self._scene_pos

            def isStart(self):
                return self._start

            def isFinish(self):
                return self._finish

            def accept(self):
                self.accepted = True

        plot = self._make_synthetic_plot()
        vb = plot.plot.getPlotItem().getViewBox()
        p0 = vb.mapViewToScene(QPointF(0.20, -2.0))
        p1 = vb.mapViewToScene(QPointF(0.70, 2.0))
        captured: list[bool] = []
        plot.selectionZoomChanged.connect(captured.append)

        plot.set_selection_zoom_switch_enabled(True)
        self.assertTrue(plot._on_selection_drag(_DragEvent(p0, start=True)))
        self.assertTrue(plot._on_selection_drag(_DragEvent(p1, finish=True)))
        self.assertFalse(plot._selection_zoom_enabled)
        self.assertFalse(plot._zoom_select_btn.isChecked())
        self.assertEqual(captured, [True, False])

    def test_drag_wrapper_keeps_original_viewbox_handler(self):
        plot = self._make_synthetic_plot()
        vb = plot.plot.getPlotItem().getViewBox()
        closure_types = [
            type(cell.cell_contents).__name__
            for cell in (vb.mouseDragEvent.__closure__ or [])
        ]
        self.assertIn("method", closure_types)
        self.assertNotIn("function", closure_types)

    def test_cursor_and_zoom_switch_api(self):
        plot = self._make_synthetic_plot()
        cursor_changes: list[bool] = []
        zoom_changes: list[bool] = []
        plot.cursorVisibilityChanged.connect(cursor_changes.append)
        plot.selectionZoomChanged.connect(zoom_changes.append)

        self.assertTrue(plot.cursor_switch_enabled())
        plot.set_cursor_switch_enabled(False)
        self.assertFalse(plot.cursor_switch_enabled())
        self.assertEqual(cursor_changes, [False])
        plot._set_cursor_type("horizontal")
        self.assertTrue(plot.cursor_switch_enabled())
        plot.set_cursor_switch_enabled(False)
        plot.set_cursor_switch_enabled(True)
        self.assertEqual(plot._cursor_type, "horizontal")

        self.assertFalse(plot.selection_zoom_switch_enabled())
        plot.set_selection_zoom_switch_enabled(True)
        self.assertTrue(plot.selection_zoom_switch_enabled())
        plot.set_selection_zoom_switch_enabled(False)
        self.assertFalse(plot.selection_zoom_switch_enabled())
        self.assertEqual(zoom_changes, [True, False])

    def test_scope_context_menu_is_cursor_menu_only(self):
        plot = self._make_synthetic_plot()
        self.assertTrue(plot._readout_scroll.isHidden())
        menu = plot._build_scope_context_menu(0.5, 0.0)
        texts = [
            "|" if action.isSeparator() else action.text()
            for action in menu.actions()
        ]
        self.assertIn("关闭光标", texts)
        self.assertIn("光标类型", texts)
        self.assertIn("光标模式", texts)
        self.assertNotIn("光标", texts)
        self.assertNotIn("缩放", texts)
        self.assertNotIn("清除光标测量", texts)
        self.assertNotIn("复制截图到剪贴板", texts)
        self.assertNotIn("纵轴", texts)
        self.assertNotIn("配置视图...", texts)
        self.assertNotIn("显示模式", texts)
        self.assertNotIn("默认设置", texts)

        type_menu = next(
            action.menu() for action in menu.actions() if action.text() == "光标类型"
        )
        self.assertEqual(
            [action.text() for action in type_menu.actions()],
            ["波形", "竖条", "横条", "竖条与横条"],
        )
        menu.actions()[0].trigger()
        self.assertEqual(plot._cursor_type, "none")
        self.assertFalse(plot._cursor_a.isVisible())
        menu_after_close = plot._build_scope_context_menu(0.5, 0.0)
        self.assertEqual(menu_after_close.actions()[0].text(), "打开光标")
        menu_after_close.actions()[0].trigger()
        self.assertEqual(plot._cursor_type, "both")
        self.assertTrue(plot._cursor_a.isVisible())
        plot.close()

    def test_scope_context_menu_move_actions_follow_cursor_type(self):
        plot = self._make_synthetic_plot()

        def move_actions(cursor_type: str) -> list[str]:
            plot._set_cursor_type(cursor_type)
            menu = plot._build_scope_context_menu(0.5, 0.0)
            return [
                action.text()
                for action in menu.actions()
                if not action.isSeparator()
                and ("移到此处" in action.text() or action.text() == "尚未安装光标")
            ]

        vertical_actions = ["将光标 A 移到此处", "将光标 B 移到此处"]
        horizontal_actions = [
            "将光标 Ha 移到此处",
            "将光标 Hb 移到此处",
        ]

        for cursor_type in ("waveform", "vertical"):
            with self.subTest(cursor_type=cursor_type):
                actions = move_actions(cursor_type)
                self.assertEqual(actions, vertical_actions)

        self.assertEqual(move_actions("horizontal"), horizontal_actions)
        self.assertEqual(move_actions("both"), vertical_actions + horizontal_actions)
        self.assertEqual(move_actions("none"), [])
        plot.close()

    def test_cursor_type_visibility_modes(self):
        import numpy as np

        plot = self._make_synthetic_plot()
        plot._set_cursor_type("waveform")
        self.assertTrue(plot._cursor_a.isVisible())
        self.assertTrue(plot._cursor_b.isVisible())
        self.assertFalse(plot._h_cursor_a.isVisible())
        self.assertFalse(plot._h_cursor_b.isVisible())
        self.assertIsNotNone(plot._cursor_a_wave_marker)
        self.assertTrue(plot._cursor_a_wave_marker.isVisible())

        plot._on_legend_clicked("CH2")
        marker_x, marker_y = plot._cursor_a_wave_marker.getData()
        self.assertGreater(len(marker_x), 0)
        self.assertGreater(len(marker_y), 0)
        expected = float(
            np.interp(
                float(marker_x[0]),
                plot._trace_t_us,
                plot._trace_raw["CH2"],
            )
        )
        self.assertAlmostEqual(
            plot._from_disp("CH2", float(marker_y[0])),
            expected,
            places=6,
        )

        plot._set_cursor_type("vertical")
        self.assertTrue(plot._cursor_a.isVisible())
        self.assertTrue(plot._cursor_b.isVisible())
        self.assertFalse(plot._h_cursor_a.isVisible())
        self.assertFalse(plot._h_cursor_b.isVisible())
        self.assertFalse(plot._cursor_a_wave_marker.isVisible())

        plot._set_cursor_type("horizontal")
        self.assertFalse(plot._cursor_a.isVisible())
        self.assertFalse(plot._cursor_b.isVisible())
        self.assertTrue(plot._h_cursor_a.isVisible())
        self.assertTrue(plot._h_cursor_b.isVisible())
        self.assertFalse(plot._cursor_a_wave_marker.isVisible())

        plot._set_cursor_type("both")
        self.assertTrue(plot._cursor_a.isVisible())
        self.assertTrue(plot._h_cursor_a.isVisible())
        self.assertFalse(plot._cursor_a_wave_marker.isVisible())

        plot._set_cursor_type("none")
        self.assertFalse(plot._cursor_a.isVisible())
        self.assertFalse(plot._h_cursor_a.isVisible())
        self.assertFalse(plot._cursor_a_wave_marker.isVisible())

    def test_cursor_readouts_match_scope_cursor_types(self):
        plot = self._make_synthetic_plot()

        plot._set_cursor_type("both")
        both_a = plot._cursor_a_t_label.textItem.toPlainText()
        both_delta = plot._cursor_ab_delta_label.textItem.toPlainText()
        both_h_delta = plot._cursor_hb_ha_delta_label.textItem.toPlainText()
        both_ha = plot._cursor_ha_v_label.textItem.toPlainText()
        both_hb = plot._cursor_hb_v_label.textItem.toPlainText()
        self.assertIn("t:", both_a)
        self.assertNotIn("\n", both_a)
        self.assertIn("Ha:", both_ha)
        self.assertIn("Hb:", both_hb)
        self.assertIn("Δ t:", both_delta)
        self.assertIn("1 / Δ t:", both_delta)
        self.assertNotIn("Δ a:", both_delta)
        self.assertIn("Δ a:", both_h_delta)
        self.assertIn("Δ a/ Δ t:", both_h_delta)

        plot._set_cursor_type("horizontal")
        horizontal_delta = plot._cursor_hb_ha_delta_label.textItem.toPlainText()
        self.assertIn("Δ a:", horizontal_delta)
        self.assertNotIn("/ Δ t", horizontal_delta)

        plot._set_cursor_type("waveform")
        wave_a = plot._cursor_a_t_label.textItem.toPlainText()
        wave_delta = plot._cursor_ab_delta_label.textItem.toPlainText()
        self.assertIn("t:", wave_a)
        self.assertIn("\n", wave_a)
        self.assertIn("a:", wave_a)
        self.assertIn("Δ t:", wave_delta)
        self.assertIn("Δ a:", wave_delta)
        self.assertIn("Δ a/ Δ t:", wave_delta)
        self.assertFalse(plot._h_cursor_a.isVisible())

    def test_interval_horizontal_lines_keep_independent_channels_and_units(self):
        """Esc may use MATH/Ic, while Desat keeps a same-channel Δ readout."""

        plot = self._make_synthetic_plot()
        try:
            plot._set_math_formula("MATH2", "CH2 * CH3")
            self.assertEqual(plot._unit_for_channel("MATH2"), "W")
            captured: list[tuple[float, float]] = []
            plot.set_horizontal_cursor_handler(
                lambda ha, hb: captured.append((float(ha), float(hb)))
            )

            plot.enable_interval_interaction(
                0.2,
                0.8,
                lambda *_args: None,
                show_horizontal_peak=True,
                channel="MATH2",
            )
            plot.set_interval_peak_horizontal(0.0, channel="MATH2")
            plot.set_interval_base_horizontal(12.5, channel="ic")

            self.assertEqual(plot._horizontal_cursor_binding("ha"), ("MATH2", True))
            self.assertEqual(plot._horizontal_cursor_binding("hb"), ("ic", True))
            self.assertFalse(plot._horizontal_quantities_comparable())
            self.assertTrue(plot._h_cursor_a.isVisible())
            self.assertTrue(plot._h_cursor_b.isVisible())
            self.assertFalse(plot._cursor_hb_ha_delta_label.isVisible())
            self.assertIn(
                "MATH2", plot._cursor_ha_v_label.textItem.toPlainText()
            )
            self.assertNotIn("Δy", plot._readout_label.text())
            plot._h_cursor_a.setPos(float(plot._h_cursor_a.value()) + 0.1)
            self.app.processEvents()
            self.assertEqual(captured, [])

            plot.enable_interval_interaction(
                0.2,
                0.8,
                lambda *_args: None,
                show_horizontal_peak=True,
                channel="vce",
            )
            plot.set_interval_peak_horizontal(400.0, channel="vce")
            plot.set_interval_base_horizontal(40.0, channel="vce")

            self.assertTrue(plot._horizontal_quantities_comparable())
            self.assertTrue(plot._cursor_hb_ha_delta_label.isVisible())
            self.assertIn("Δy", plot._readout_label.text())
        finally:
            plot.close()

    def test_power_peak_uses_only_a_valid_ha_and_clears_when_trace_is_missing(self):
        plot = self._make_synthetic_plot()
        try:
            plot._set_math_formula("MATH2", "CH2 * CH3")
            plot.enable_interval_interaction(
                0.2,
                0.8,
                lambda *_args: None,
                show_horizontal_peak=True,
                mode="power_peak",
                channel="MATH2",
            )
            self.assertFalse(plot._h_cursor_a.isVisible())
            self.assertFalse(plot._h_cursor_b.isVisible())

            plot.set_interval_peak_horizontal(0.0, channel="MATH2")
            self.assertEqual(plot._horizontal_cursor_binding("ha"), ("MATH2", True))
            self.assertTrue(plot._h_cursor_a.isVisible())
            self.assertFalse(plot._h_cursor_b.isVisible())
            self.assertFalse(plot._cursor_hb_ha_delta_label.isVisible())

            plot.enable_interval_interaction(
                0.2,
                0.8,
                lambda *_args: None,
                show_horizontal_peak=False,
                mode="power_peak",
                channel="vce",
            )
            self.assertEqual(plot._horizontal_cursor_binding("ha")[1], False)
            self.assertEqual(plot._horizontal_cursor_binding("hb")[1], False)
            self.assertFalse(plot._h_cursor_a.isVisible())
            self.assertFalse(plot._h_cursor_b.isVisible())

            plot.disable_interactive_cursors()
            self.assertTrue(plot._h_cursor_a.isVisible())
            self.assertTrue(plot._h_cursor_b.isVisible())
        finally:
            plot.close()

    def test_hiding_an_active_parameter_source_exits_card_mode(self):
        plot = self._make_synthetic_plot()
        try:
            plot._set_math_formula("MATH2", "CH2 * CH3")
            plot.enable_interval_interaction(
                0.2,
                0.8,
                lambda *_args: None,
                show_horizontal_peak=True,
                mode="power_peak",
                channel="MATH2",
                a_channel="MATH2",
                b_channel="MATH2",
            )
            plot.set_interval_peak_horizontal(0.0, channel="MATH2")
            self.assertEqual(plot._interactive_mode, "power_peak")

            plot._toggle_channel_visibility("MATH2")

            self.assertEqual(plot._interactive_mode, "global")
            self.assertIn("MATH2", plot._hidden_channels)
        finally:
            plot.close()

    def test_active_slope_horizontal_levels_flip_once_with_display_inversion(self):
        plot = self._make_synthetic_plot()
        try:
            plot.enable_dvdt_interaction(
                0.1,
                0.9,
                600.0,
                -80.0,
                "ic",
                lambda *_args: None,
                mode="didt",
            )
            before_ha = plot._from_disp("ic", float(plot._h_cursor_a.value()))
            before_hb = plot._from_disp("ic", float(plot._h_cursor_b.value()))
            source = plot._display_key_for_channel("ic")

            plot.set_channel_inversion_enabled(source, True)
            self.assertAlmostEqual(
                plot._from_disp("ic", float(plot._h_cursor_a.value())),
                -before_ha,
                places=9,
            )
            self.assertAlmostEqual(
                plot._from_disp("ic", float(plot._h_cursor_b.value())),
                -before_hb,
                places=9,
            )

            plot.set_channel_inversion_enabled(source, False)
            self.assertAlmostEqual(
                plot._from_disp("ic", float(plot._h_cursor_a.value())),
                before_ha,
                places=9,
            )
            self.assertAlmostEqual(
                plot._from_disp("ic", float(plot._h_cursor_b.value())),
                before_hb,
                places=9,
            )
        finally:
            plot.close()

    def test_cursor_readout_overlays_stay_on_plot_edges(self):
        from PyQt6.QtCore import QPointF

        from dpt_extractor.gui.waveform_plot import (
            CURSOR_READOUT_BOTTOM_TICK_GUARD_PX,
            CURSOR_READOUT_CURSOR_GAP_PX,
            CURSOR_READOUT_EDGE_INSET_PX,
        )

        plot = self._make_synthetic_plot()
        plot.resize(900, 520)
        plot.show()
        self.app.processEvents()

        assert plot._h_cursor_a is not None
        assert plot._h_cursor_b is not None
        assert plot._cursor_a is not None
        assert plot._cursor_b is not None
        plot._cursor_a.setPos(0.50)
        plot._cursor_b.setPos(0.51)
        plot._h_cursor_a.setPos(0.0)
        plot._h_cursor_b.setPos(-1.5)
        plot._set_cursor_type("both")
        self.app.processEvents()

        vb = plot.plot.getPlotItem().getViewBox()
        rect = vb.sceneBoundingRect()
        top_y = float(rect.top()) + CURSOR_READOUT_EDGE_INSET_PX
        bottom_y = float(rect.bottom()) - CURSOR_READOUT_BOTTOM_TICK_GUARD_PX

        self.assertAlmostEqual(
            float(plot._cursor_ab_delta_label.scenePos().y()), top_y, delta=1.0
        )
        self.assertAlmostEqual(
            float(plot._cursor_a_t_label.scenePos().y()), bottom_y, delta=1.0
        )
        self.assertAlmostEqual(
            float(plot._cursor_b_t_label.scenePos().y()), bottom_y, delta=1.0
        )
        a_line_x = plot._cursor_readout_scene_x(float(plot._cursor_a.value()))
        b_line_x = plot._cursor_readout_scene_x(float(plot._cursor_b.value()))
        self.assertLess(a_line_x, b_line_x)
        self.assertAlmostEqual(float(plot._cursor_a_t_label.anchor.x()), 1.0)
        self.assertAlmostEqual(float(plot._cursor_b_t_label.anchor.x()), 0.0)
        self.assertAlmostEqual(
            float(plot._cursor_a_t_label.scenePos().x()),
            a_line_x - CURSOR_READOUT_CURSOR_GAP_PX,
            delta=1.0,
        )
        self.assertAlmostEqual(
            float(plot._cursor_b_t_label.scenePos().x()),
            b_line_x + CURSOR_READOUT_CURSOR_GAP_PX,
            delta=1.0,
        )
        self.assertAlmostEqual(
            float(plot._cursor_ha_v_label.scenePos().y()), top_y, delta=1.0
        )
        ha_line_y = float(vb.mapViewToScene(QPointF(0.0, 0.0)).y())
        self.assertGreater(
            abs(float(plot._cursor_ha_v_label.scenePos().y()) - ha_line_y),
            20.0,
        )

        plot._cursor_a.setPos(0.80)
        plot._cursor_b.setPos(0.20)
        plot._update_readout()
        self.app.processEvents()
        a_line_x = plot._cursor_readout_scene_x(float(plot._cursor_a.value()))
        b_line_x = plot._cursor_readout_scene_x(float(plot._cursor_b.value()))
        self.assertGreater(a_line_x, b_line_x)
        self.assertAlmostEqual(float(plot._cursor_a_t_label.anchor.x()), 0.0)
        self.assertAlmostEqual(float(plot._cursor_b_t_label.anchor.x()), 1.0)
        self.assertAlmostEqual(
            float(plot._cursor_a_t_label.scenePos().x()),
            a_line_x + CURSOR_READOUT_CURSOR_GAP_PX,
            delta=1.0,
        )
        self.assertAlmostEqual(
            float(plot._cursor_b_t_label.scenePos().x()),
            b_line_x - CURSOR_READOUT_CURSOR_GAP_PX,
            delta=1.0,
        )

        plot._set_cursor_type("horizontal")
        self.app.processEvents()
        self.assertAlmostEqual(
            float(plot._cursor_hb_ha_delta_label.scenePos().y()),
            bottom_y,
            delta=1.0,
        )
        plot.close()

    def test_waveform_cursor_readout_avoids_intersection_marker(self):
        from PyQt6.QtCore import QPointF, QRectF

        from dpt_extractor.gui.waveform_plot import CURSOR_READOUT_MARKER_GUARD_PX

        plot = self._make_synthetic_plot()
        plot.resize(900, 520)
        plot.show()
        self.app.processEvents()

        assert plot._cursor_a is not None
        assert plot._cursor_b is not None
        plot._set_cursor_type("waveform")
        plot._cursor_a.setPos(0.50)
        plot._cursor_b.setPos(0.51)
        plot._update_readout()
        self.app.processEvents()

        assert plot._cursor_a_wave_marker is not None
        assert plot._cursor_a_t_label is not None
        a_us = float(plot._cursor_a.value())
        b_us = float(plot._cursor_b.value())
        a_line_x = plot._cursor_readout_scene_x(a_us)
        label_rect = plot._cursor_text_scene_rect(plot._cursor_a_t_label)
        marker_scene = QPointF(a_line_x, float(label_rect.center().y()))
        marker_view = plot.plot.getPlotItem().getViewBox().mapSceneToView(marker_scene)

        plot._cursor_a_wave_marker.setData([a_us], [float(marker_view.y())])
        plot._cursor_a_wave_marker.show()
        plot._position_v_cursor_plot_labels(a_us, b_us)

        guard = QRectF(
            float(marker_scene.x()) - CURSOR_READOUT_MARKER_GUARD_PX,
            float(marker_scene.y()) - CURSOR_READOUT_MARKER_GUARD_PX,
            CURSOR_READOUT_MARKER_GUARD_PX * 2.0,
            CURSOR_READOUT_MARKER_GUARD_PX * 2.0,
        )
        moved_rect = plot._cursor_text_scene_rect(plot._cursor_a_t_label)
        self.assertFalse(moved_rect.intersects(guard))
        self.assertGreaterEqual(
            float(plot._cursor_a_t_label.scenePos().y()),
            float(guard.bottom()),
        )
        plot.close()

    def test_cursor_readout_labels_avoid_each_other(self):
        from dpt_extractor.gui.waveform_plot import CURSOR_READOUT_LABEL_GUARD_PX

        plot = self._make_synthetic_plot()
        plot.resize(900, 520)
        plot.show()
        self.app.processEvents()

        plot._set_cursor_type("vertical")
        assert plot._cursor_a_t_label is not None
        assert plot._cursor_b_t_label is not None
        plot._cursor_b_t_label.setPos(plot._cursor_a_t_label.scenePos())
        before_a = plot._padded_scene_rect(
            plot._cursor_text_scene_rect(plot._cursor_a_t_label),
            CURSOR_READOUT_LABEL_GUARD_PX,
        )
        before_b = plot._padded_scene_rect(
            plot._cursor_text_scene_rect(plot._cursor_b_t_label),
            CURSOR_READOUT_LABEL_GUARD_PX,
        )
        self.assertTrue(before_a.intersects(before_b))

        plot._avoid_cursor_label_overlaps()

        after_a = plot._padded_scene_rect(
            plot._cursor_text_scene_rect(plot._cursor_a_t_label),
            CURSOR_READOUT_LABEL_GUARD_PX,
        )
        after_b = plot._padded_scene_rect(
            plot._cursor_text_scene_rect(plot._cursor_b_t_label),
            CURSOR_READOUT_LABEL_GUARD_PX,
        )
        self.assertFalse(after_a.intersects(after_b))
        plot.close()

    def test_close_cursor_line_labels_split_around_lines(self):
        from dpt_extractor.gui.waveform_plot import CURSOR_LINE_LABEL_GUARD_PX

        plot = self._make_synthetic_plot()
        plot.resize(900, 520)
        plot.show()
        self.app.processEvents()

        assert plot._cursor_a is not None
        assert plot._cursor_b is not None
        assert plot._h_cursor_a is not None
        assert plot._h_cursor_b is not None
        plot._cursor_a.setPos(0.50)
        plot._cursor_b.setPos(0.51)
        plot._h_cursor_a.setPos(0.0)
        plot._h_cursor_b.setPos(-0.2)
        plot._set_cursor_type("both")
        plot._update_readout()
        self.app.processEvents()

        a_label = getattr(plot._cursor_a, "label", None)
        b_label = getattr(plot._cursor_b, "label", None)
        ha_label = getattr(plot._h_cursor_a, "label", None)
        hb_label = getattr(plot._h_cursor_b, "label", None)
        self.assertIsNotNone(a_label)
        self.assertIsNotNone(b_label)
        self.assertIsNotNone(ha_label)
        self.assertIsNotNone(hb_label)

        a_rect = plot._padded_scene_rect(
            plot._cursor_line_label_scene_rect(plot._cursor_a),
            CURSOR_LINE_LABEL_GUARD_PX,
        )
        b_rect = plot._padded_scene_rect(
            plot._cursor_line_label_scene_rect(plot._cursor_b),
            CURSOR_LINE_LABEL_GUARD_PX,
        )
        ha_rect = plot._padded_scene_rect(
            plot._cursor_line_label_scene_rect(plot._h_cursor_a),
            CURSOR_LINE_LABEL_GUARD_PX,
        )
        hb_rect = plot._padded_scene_rect(
            plot._cursor_line_label_scene_rect(plot._h_cursor_b),
            CURSOR_LINE_LABEL_GUARD_PX,
        )
        self.assertFalse(a_rect.intersects(b_rect))
        self.assertFalse(ha_rect.intersects(hb_rect))
        self.assertAlmostEqual(float(a_label.anchor.x()), 1.0)
        self.assertAlmostEqual(float(b_label.anchor.x()), 0.0)
        self.assertAlmostEqual(float(ha_label.anchor.y()), 1.0)
        self.assertAlmostEqual(float(hb_label.anchor.y()), 0.0)
        plot.close()

    def test_waveform_cursor_markers_survive_replot(self):
        from dpt_extractor.gui.waveform_plot import WaveformPlot

        bundle, profile = self._make_synthetic_bundle()
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)
        plot._set_cursor_type("waveform")
        marker = plot._cursor_a_wave_marker
        self.assertIsNotNone(marker)
        self.assertIn(marker, plot.plot.getPlotItem().items)
        self.assertTrue(marker.isVisible())

        plot.plot_waveforms(bundle, profile, None)

        self.assertIs(plot._cursor_a_wave_marker, marker)
        self.assertIn(marker, plot.plot.getPlotItem().items)
        self.assertTrue(marker.isVisible())


@unittest.skipUnless(WH.exists() and UH.exists(), "WH/UH sample missing")
class TestWaveformPlotSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _load_and_plot(self, sample_path: Path):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.io.waveform_loader import load_waveform
        from dpt_extractor.models.bridge_profile import guess_profile_from_path, make_profile
        from dpt_extractor.models.channel_mapping import apply_mapping, infer_mapping_from_bundle
        from dpt_extractor.pipeline.extract import extract_all

        cfg = load_config()
        bundle = load_waveform(sample_path)
        guessed = guess_profile_from_path(sample_path.name)
        inferred = infer_mapping_from_bundle(bundle, guessed.bridge)
        profile = make_profile(guessed.phase, guessed.bridge)
        if inferred is not None:
            profile = apply_mapping(profile, inferred)
        result = extract_all(bundle, profile, cfg)
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, result)
        return plot, bundle, profile, result

    def test_persistent_cursors_installed(self):
        plot, bundle, _, result = self._load_and_plot(WH)
        self.assertIsNotNone(plot._cursor_a)
        self.assertIsNotNone(plot._cursor_b)
        self.assertIsNotNone(plot._h_cursor_a)
        self.assertIsNotNone(plot._h_cursor_b)
        # 顶部 readout 已隐藏，读数保留为内部状态/状态栏信息。
        self.assertTrue(plot._readout_scroll.isHidden())
        self.assertNotEqual(plot._readout_label.text(), "")
        # TSS 显示保留示波器原始通道名，并可附加 Math 通道。
        self.assertGreaterEqual(len(plot._channel_boxes), 6)
        self.assertIn("CH1", plot._channel_boxes)
        self.assertIn("CH6", plot._channel_boxes)

    def test_per_channel_scale_setting(self):
        plot, bundle, profile, _ = self._load_and_plot(WH)
        key = "CH1"
        # 手动设置 CH1 为 2 V/格
        plot._set_channel_scale(key, 2.0)
        self.assertEqual(plot._disp_scale[key], 2.0)
        self.assertEqual(plot._manual_vdiv[key], 2.0)
        # 显示数据应按新刻度缩放（含该通道默认垂直位置偏移）
        import numpy as np

        raw = plot._trace_raw[key]
        offset = plot._disp_offset[key]
        self.assertIsNotNone(raw)
        self.assertIsNotNone(offset)
        # 恢复自动
        plot._set_channel_scale(key, None)
        self.assertNotIn(key, plot._manual_vdiv)

    def test_per_channel_vertical_position(self):
        import numpy as np

        plot, bundle, profile, _ = self._load_and_plot(WH)
        if not hasattr(plot, "_on_channel_position_step"):
            self.skipTest("channel position step UI is not present in this plot implementation")
        key = "CH2"
        raw = plot._trace_raw[key]
        scale = plot._disp_scale[key]
        base = plot._disp_offset[key]  # 默认位置偏移
        # 滚轮上移 2 步 = +1.0 格（相对默认偏移）
        plot._on_channel_position_step(key, 2)
        self.assertAlmostEqual(plot._disp_offset[key], base + 1.0, places=6)
        self.assertTrue(
            np.allclose(plot._trace_items[key].getData()[1], raw / scale + base + 1.0)
        )
        # 高亮出现接地标记
        plot._on_legend_clicked(key)
        self.assertIsNotNone(plot._ground_marker)
        self.assertTrue(plot._ground_marker.isVisible())
        self.assertEqual(plot._ground_marker_key, key)
        # 拖动接地标记改位置
        plot._ground_marker.setValue(-1.5)
        self.assertAlmostEqual(plot._disp_offset[key], -1.5, places=6)
        self.assertTrue(
            np.allclose(plot._trace_items[key].getData()[1], raw / scale - 1.5)
        )
        # 取消高亮隐藏标记
        plot._on_legend_clicked(key)
        self.assertFalse(plot._ground_marker.isVisible())

    def test_legend_click_raises_and_double_click_toggles_highlight(self):
        plot, bundle, profile, _ = self._load_and_plot(WH)
        vb = plot.plot.getPlotItem().getViewBox()
        y_before = vb.viewRange()[1]
        # 单击 CH1：仅置顶，不高亮、不压暗其它波形，纵轴量程不变
        plot._on_legend_clicked("CH1")
        self.assertEqual(plot._raised_key, "CH1")
        self.assertIsNone(plot._highlighted_key)
        self.assertEqual(plot._trace_items["CH1"].zValue(), 20)
        self.assertEqual(plot._trace_items["CH2"].zValue(), 0)
        self.assertEqual(plot._zero_handles["CH1"].zValue(), 120)
        self.assertEqual(plot._zero_handles["CH2"].zValue(), 100)
        y_after = vb.viewRange()[1]
        self.assertAlmostEqual(y_before[0], y_after[0], places=3)
        self.assertAlmostEqual(y_before[1], y_after[1], places=3)

        # 双击 CH1：高亮；再次双击取消高亮，但保留该通道置顶
        plot._on_legend_double_clicked("CH1")
        self.assertEqual(plot._raised_key, "CH1")
        self.assertEqual(plot._highlighted_key, "CH1")
        self.assertEqual(plot._trace_items["CH1"].zValue(), 20)
        selected_pen = plot._trace_items["CH1"].opts["pen"]
        dimmed_pen = plot._trace_items["CH2"].opts["pen"]
        self.assertEqual(selected_pen.color().alpha(), 255)
        self.assertLess(dimmed_pen.color().alpha(), selected_pen.color().alpha())
        self.assertTrue(plot._zero_handles["CH1"]._highlighted)
        self.assertFalse(plot._zero_handles["CH1"]._dimmed)
        self.assertTrue(plot._zero_handles["CH2"]._dimmed)
        plot._on_legend_double_clicked("CH1")
        self.assertIsNone(plot._highlighted_key)
        self.assertEqual(plot._trace_items["CH1"].zValue(), 20)
        self.assertEqual(plot._zero_handles["CH1"].zValue(), 120)
        self.assertFalse(any(h._highlighted for h in plot._zero_handles.values()))
        self.assertFalse(any(h._dimmed for h in plot._zero_handles.values()))

    def test_real_channel_box_double_click_can_clear_existing_highlight(self):
        try:
            from PyQt6.QtTest import QTest
        except ImportError:
            self.skipTest("QtTest is not available")
        from PyQt6.QtCore import Qt

        plot, _, _, _ = self._load_and_plot(WH)
        try:
            plot.show()
            self.app.processEvents()
            box = plot._channel_boxes["CH1"]

            # Exercise Qt's real event sequence.  It includes ordinary press
            # handling before the double-click event, which previously erased
            # the state needed for the second gesture to toggle highlight off.
            QTest.mouseDClick(box, Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertEqual(plot._highlighted_key, "CH1")

            QTest.mouseDClick(box, Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertIsNone(plot._highlighted_key)
            self.assertEqual(plot._raised_key, "CH1")
        finally:
            plot.close()

    def test_channel_visibility_toggle(self):
        plot, _, _, _ = self._load_and_plot(WH)
        key = "CH2"
        self.assertTrue(plot._trace_items[key].isVisible())
        plot._on_legend_clicked(key)
        self.assertEqual(plot._trace_items[key].zValue(), 20)
        plot._toggle_channel_visibility(key)
        self.assertIn(key, plot._hidden_channels)
        self.assertFalse(plot._trace_items[key].isVisible())
        self.assertIsNone(plot._raised_key)
        plot._toggle_channel_visibility(key)
        self.assertNotIn(key, plot._hidden_channels)
        self.assertTrue(plot._trace_items[key].isVisible())
        self.assertEqual(plot._trace_items[key].zValue(), 0)

    def test_scope_ypos_or_auto_center_on_import(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import DISP_HALF_DIV

        plot, bundle, _, _ = self._load_and_plot(WH)
        for key in plot._trace_items:
            if key in bundle.meta.channel_y_position:
                expected = max(
                    -DISP_HALF_DIV,
                    min(DISP_HALF_DIV, float(bundle.meta.channel_y_position[key])),
                )
                self.assertAlmostEqual(plot._disp_offset[key], expected, places=6)
                self.assertAlmostEqual(plot._zero_handle_display_y(key), expected, places=6)
                continue
            raw = plot._trace_raw[key]
            scale = plot._disp_scale[key]
            if key.startswith("MATH") and plot._unit_for_channel(key) == "J":
                raw = plot._fit_raw_for_channel(key, raw)
            mid_raw = 0.5 * (float(np.nanmin(raw)) + float(np.nanmax(raw)))
            mid_disp = mid_raw / scale + plot._disp_offset[key]
            self.assertLess(abs(mid_disp), 0.35, msg=key)

    def test_auto_vdiv_ladder_and_margin(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import (  # noqa: PLC0415
            CURRENT_VDIV_MAX,
            DISP_HALF_DIV,
            VERT_VIEW_MARGIN,
            _auto_vdiv_for_channel,
            _pick_vdiv_ladder,
            _wheel_delta_y,
        )

        class _SceneWheel:
            def delta(self):
                return 120

        self.assertEqual(_wheel_delta_y(_SceneWheel()), 120)
        raw = np.array([0.0, 800.0])
        self.assertEqual(_auto_vdiv_for_channel("vce", raw), 100.0)
        self.assertEqual(_auto_vdiv_for_channel("vge", np.array([0.0, 15.0])), 2.0)
        self.assertEqual(_pick_vdiv_ladder(37.0, "vge"), 50.0)
        self.assertEqual(_pick_vdiv_ladder(250.0, "ic"), 250.0)
        self.assertEqual(_pick_vdiv_ladder(280.0, "ic"), 300.0)
        small_ic = np.array([0.0, 400.0])
        self.assertEqual(_auto_vdiv_for_channel("ic", small_ic), 50.0)
        self.assertEqual(_pick_vdiv_ladder(0.05, "MATH2"), 0.05)
        self.assertEqual(_auto_vdiv_for_channel("MATH2", np.array([0.0, 240.0])), 50.0)
        self.assertEqual(_auto_vdiv_for_channel("MATH3", np.array([-1.7, 2.3])), 0.5)
        self.assertEqual(
            _auto_vdiv_for_channel("MATH1", np.array([0.0, 1.2e6]), "W"),
            500_000.0,
        )
        self.assertEqual(
            _auto_vdiv_for_channel(
                "MATH1",
                np.array([0.0, 1.2e6]),
                "W",
                reverse_recovery_power=True,
            ),
            200_000.0,
        )
        self.assertEqual(
            _auto_vdiv_for_channel("MATH1", np.array([0.0, 1200.0]), "KW"),
            500.0,
        )
        self.assertEqual(
            _auto_vdiv_for_channel(
                "MATH1",
                np.array([0.0, 1200.0]),
                "KW",
                reverse_recovery_power=True,
            ),
            200.0,
        )
        self.assertEqual(
            _auto_vdiv_for_channel("MATH1", np.array([0.0, 1.2]), "MW"),
            0.5,
        )
        self.assertEqual(
            _auto_vdiv_for_channel(
                "MATH1",
                np.array([0.0, 1.2]),
                "MW",
                reverse_recovery_power=True,
            ),
            0.2,
        )

        plot, _, _, _ = self._load_and_plot(WH)
        max_half = DISP_HALF_DIV * (1.0 - VERT_VIEW_MARGIN) + 0.05
        for key, scale in plot._disp_scale.items():
            if key.startswith("MATH") and plot._unit_for_channel(key) == "J":
                raw = plot._fit_raw_for_channel(key, plot._trace_raw[key])
                ymin, ymax = float(np.nanmin(raw)), float(np.nanmax(raw))
            else:
                ymin, ymax = plot._trace_yrange[key]
            half_pp_div = (ymax - ymin) / (2.0 * scale)
            if key in plot._manual_vdiv:
                self.assertEqual(scale, plot._manual_vdiv[key])
                continue
            if key.startswith("MATH"):
                self.assertGreaterEqual(scale, 1e-9)
            else:
                self.assertEqual(scale, float(int(scale)), msg=key)
            if key in ("ic", "irr"):
                self.assertLessEqual(scale, CURRENT_VDIV_MAX)
                self.assertGreaterEqual(scale, 1.0)
            self.assertLessEqual(half_pp_div, max_half, key)
        plot._apply_x_us_per_div(0.2, center_us=18.0)
        before = plot._x_us_per_div
        plot._on_x_wheel(_SceneWheel())
        self.assertNotAlmostEqual(plot._x_us_per_div, before, places=9)

    def test_per_channel_vertical_scale(self):
        """每通道独立 V/div：小信号(Vge)与大信号(Vce)显示幅度应相近，不再被压扁。"""
        import numpy as np

        plot, bundle, profile, _ = self._load_and_plot(WH)
        # 纵轴固定为 ±DISP_HALF_DIV 格
        vb = plot.plot.getPlotItem().getViewBox()
        yr = vb.viewRange()[1]
        from dpt_extractor.gui.waveform_plot import DISP_HALF_DIV

        self.assertAlmostEqual(yr[0], -DISP_HALF_DIV, places=3)
        self.assertAlmostEqual(yr[1], DISP_HALF_DIV, places=3)
        # 每通道有独立刻度
        self.assertIn("CH1", plot._disp_scale)
        self.assertIn("CH2", plot._disp_scale)
        # CH1 门极刻度应远小于 CH2 主电压刻度（5V/格 量级 vs 数百V/格）
        self.assertLess(plot._disp_scale["CH1"], plot._disp_scale["CH2"])
        from dpt_extractor.gui.waveform_plot import VERT_VIEW_MARGIN

        max_half = DISP_HALF_DIV * (1.0 - VERT_VIEW_MARGIN) + 0.05
        for key, (ymin, ymax) in plot._trace_yrange.items():
            if key.startswith("MATH"):
                continue
            half_pp_div = (ymax - ymin) / (2.0 * plot._disp_scale[key])
            self.assertGreater(half_pp_div, 0.1, f"{key} 显示太小被压扁: {half_pp_div:.2f} 格")
            self.assertLessEqual(half_pp_div, max_half, f"{key} 超出屏幕: {half_pp_div:.2f} 格")
        # 4 根光标默认可拖
        self.assertTrue(plot._cursor_a.movable)
        self.assertTrue(plot._cursor_b.movable)
        self.assertTrue(plot._h_cursor_a.movable)
        self.assertTrue(plot._h_cursor_b.movable)
        # 默认 X 范围 ≈ 全 record
        full = plot._full_x_range
        self.assertIsNotNone(full)
        t = bundle.t
        self.assertAlmostEqual(full[0], float(t[0]) * 1e6, places=3)
        self.assertAlmostEqual(full[1], float(t[-1]) * 1e6, places=3)

    def test_off_dvdt_default_hb_is_on_state_vce(self):
        from dpt_extractor.gui.main_window import MainWindow

        if not UH.exists():
            self.skipTest("UH sample missing")
        plot, bundle, profile, result = self._load_and_plot(UH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__(
            "dpt_extractor.config.loader", fromlist=["load_config"]
        ).load_config()
        interval = win._parameter_interval_us("关断过程", "dv/dt")
        self.assertIsNotNone(interval)
        t0, t1 = interval
        base_v = win._default_dvdt_base_v("关断过程", t0, t1)
        top_v = win._default_dvdt_top_v("关断过程", t0, t1)
        self.assertLess(base_v, 100.0, "Hb 应为开通态低 Vce，不是母线 Vdc")
        self.assertGreater(top_v, base_v + 100.0)
        self.assertGreater(top_v, result.vdc * 0.5)

    def test_on_timing_intervals_follow_iec_spec(self):
        from dpt_extractor.gui.main_window import MainWindow

        if not UH.exists():
            self.skipTest("UH sample missing")
        _, bundle, profile, result = self._load_and_plot(UH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__(
            "dpt_extractor.config.loader", fromlist=["load_config"]
        ).load_config()
        inst = win._turn_on_timing_instants()
        ton_iv = win._parameter_interval_us("开通", "Ton")
        td_iv = win._parameter_interval_us("开通", "Td_on")
        tr_iv = win._parameter_interval_us("开通", "Tr")
        self.assertIsNotNone(ton_iv)
        self.assertIsNotNone(td_iv)
        self.assertIsNotNone(tr_iv)
        t0, t1 = ton_iv
        self.assertAlmostEqual((t1 - t0) * 1000.0, inst.ton_ns, places=1)
        t0, t1 = td_iv
        self.assertAlmostEqual((t1 - t0) * 1000.0, inst.td_on_ns, places=1)
        t0, t1 = tr_iv
        self.assertAlmostEqual((t1 - t0) * 1000.0, inst.tr_ns, places=1)
        self.assertAlmostEqual(inst.ton_ns, inst.td_on_ns + inst.tr_ns, places=1)
        # Tr 起点 = Td_on 终点；Ton 终点 = Tr 终点
        self.assertAlmostEqual(td_iv[1], tr_iv[0], places=3)
        self.assertAlmostEqual(ton_iv[1], tr_iv[1], places=3)

    @unittest.skipUnless(
        LIKANG_UH_930_REVERSED_TD_ON.exists(),
        "likangkang reversed Td_on sample missing",
    )
    def test_reversed_tdon_keeps_vge_a_and_ic_b_semantics(self):
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win._load_file(str(LIKANG_UH_930_REVERSED_TD_ON))
            QApplication.processEvents()
            inst = win._turn_on_timing_instants()
            self.assertIsNotNone(inst.t_v10_s)
            self.assertIsNotNone(inst.t_i10_s)
            assert inst.t_v10_s is not None and inst.t_i10_s is not None
            self.assertGreater(inst.t_v10_s, inst.t_i10_s)

            win._on_value_clicked("开通", "Td_on")
            QApplication.processEvents()
            assert win.wave_plot._cursor_a is not None
            assert win.wave_plot._cursor_b is not None
            self.assertEqual(win.wave_plot._interactive_mode, "semantic_interval")
            self.assertAlmostEqual(
                float(win.wave_plot._cursor_a.value()), inst.t_v10_s * 1e6, places=6
            )
            self.assertAlmostEqual(
                float(win.wave_plot._cursor_b.value()), inst.t_i10_s * 1e6, places=6
            )
            self.assertEqual(win.wave_plot._cursor_endpoint_channel("a"), "vge")
            self.assertEqual(win.wave_plot._cursor_endpoint_channel("b"), "ic")
        finally:
            win.close()

    @unittest.skipUnless(
        all(case[0].exists() for case in WANGLIHUI_SLOW_TURN_ON_CASES),
        "wanglihui slow turn-on samples missing",
    )
    def test_wanglihui_slow_turn_on_uses_stable_pulse_platform_after_ch3_inversion(self):
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.gui.main_window import MainWindow

        for sample_path, expected_td, expected_tr in WANGLIHUI_SLOW_TURN_ON_CASES:
            with self.subTest(sample=sample_path.name):
                win = MainWindow()
                try:
                    win._load_file(str(sample_path))
                    self.assertIsNotNone(win.result)
                    assert win.result is not None
                    # 该批 UH 文件的 CH3 探头方向保存反了；必须走与通道设置
                    # 面板相同的反相信号路径，随后同步重算。
                    self.assertFalse(win.wave_plot.channel_inversion_enabled("CH3"))
                    win.wave_plot.set_channel_inversion_enabled("CH3", True)
                    QApplication.processEvents()

                    self.assertIn("CH3", win.bundle.meta.channel_display_inversions)
                    on = win.result.turn_on
                    self.assertAlmostEqual(on.td_on, expected_td, delta=0.25)
                    self.assertAlmostEqual(on.tr, expected_tr, delta=0.25)
                    self.assertAlmostEqual(on.ton, on.td_on + on.tr, places=6)

                    for name, expected_ns in (
                        ("Td_on", expected_td),
                        ("Tr", expected_tr),
                    ):
                        win._on_value_clicked("开通", name)
                        QApplication.processEvents()
                        self.assertIsNotNone(win.wave_plot._cursor_a)
                        self.assertIsNotNone(win.wave_plot._cursor_b)
                        cursor_ns = abs(
                            float(win.wave_plot._cursor_b.value())
                            - float(win.wave_plot._cursor_a.value())
                        ) * 1000.0
                        self.assertAlmostEqual(cursor_ns, expected_ns, delta=0.25)
                finally:
                    win.close()

    def test_dvdt_interaction_mode(self):
        from dpt_extractor.gui.main_window import MainWindow

        plot, bundle, profile, result = self._load_and_plot(WH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__("dpt_extractor.config.loader", fromlist=["load_config"]).load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)
        win._enable_dvdt_interaction("关断过程")
        self.assertEqual(plot._interactive_mode, "dvdt")
        self.assertEqual(plot._active_channel, "vce")
        self.assertFalse(plot._cursor_a.movable)
        self.assertFalse(plot._cursor_b.movable)
        self.assertTrue(plot._h_cursor_a.movable)
        self.assertTrue(plot._h_cursor_b.movable)
        win._show_stored_metric_status("关断过程", "dv/dt")
        self.assertIn(
            "拖动 Ha/Hb 后 A/B 自动跟随重算",
            win.statusBar().currentMessage(),
        )
        interval = win._parameter_interval_us("关断过程", "dv/dt")
        self.assertIsNotNone(interval)
        search_t0, search_t1 = interval
        ha_v = plot._from_disp("vce", float(plot._h_cursor_a.value()))
        hb_v = plot._from_disp("vce", float(plot._h_cursor_b.value()))
        res1 = win._compute_dvdt_base_top("关断过程", search_t0, search_t1, ha_v, hb_v)
        self.assertGreater(res1.dvdt, 0.0)
        self.assertIsNotNone(res1.t_pct_a_s)
        ta_us = float(plot._cursor_a.value())
        tb_us = float(plot._cursor_b.value())
        self.assertLess(ta_us, tb_us)
        win._manual_dvdt[("关断过程", "dv/dt")] = (
            search_t0,
            search_t1,
            ha_v + 50.0,
            hb_v,
        )
        win._enable_dvdt_interaction("关断过程")
        self.assertAlmostEqual(
            plot._from_disp("vce", float(plot._h_cursor_a.value())), ha_v + 50.0, places=1
        )
        tb_us2 = float(plot._cursor_b.value())
        self.assertNotAlmostEqual(tb_us, tb_us2, places=3)

    def test_crosstalk_on_locks_hlines_to_plot_minmax(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.metrics.derived import crosstalk_extrema

        if not UH.exists():
            self.skipTest("UH sample missing")
        plot, bundle, profile, result = self._load_and_plot(UH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__(
            "dpt_extractor.config.loader", fromlist=["load_config"]
        ).load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)
        win._on_value_clicked("开通", "串扰电压")
        self.assertEqual(plot._interactive_mode, "crosstalk")
        self.assertFalse(plot._h_cursor_a.movable)
        self.assertFalse(plot._h_cursor_b.movable)
        t0 = float(plot._cursor_a.value())
        t1 = float(plot._cursor_b.value())
        vgo = bundle.get(profile.vge_other)
        i0 = int(np.searchsorted(bundle.t, min(t0, t1) * 1e-6))
        i1 = int(np.searchsorted(bundle.t, max(t0, t1) * 1e-6))
        plot_hi = plot._peak_plot_y_in_window("vge_other", t0, t1)
        plot_lo = plot._min_plot_y_in_window("vge_other", t0, t1)
        self.assertIsNotNone(plot_hi)
        self.assertIsNotNone(plot_lo)
        self.assertAlmostEqual(float(plot._h_cursor_a.value()), plot_hi, places=2)
        self.assertAlmostEqual(float(plot._h_cursor_b.value()), plot_lo, places=2)
    def test_ls_on_uses_delta_vce_interaction(self):
        from dpt_extractor.gui.main_window import MainWindow

        if not UH.exists():
            self.skipTest("UH sample missing")
        plot, bundle, profile, result = self._load_and_plot(UH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__(
            "dpt_extractor.config.loader", fromlist=["load_config"]
        ).load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)
        ls_before = float(result.turn_on.ls_on)
        win._on_value_clicked("开通", "Ls_on")
        self.assertEqual(plot._interactive_mode, "delta_vce")
        self.assertEqual(plot._cursor_endpoint_channel("a"), "vce")
        self.assertEqual(plot._cursor_endpoint_channel("b"), "vce")
        self.assertEqual(plot._horizontal_cursor_binding("ha"), ("vce", True))
        self.assertEqual(plot._horizontal_cursor_binding("hb"), ("vce", True))
        self.assertFalse(plot._active_channel_can_follow_selection())
        self.assertTrue(plot._cursor_a.movable)
        self.assertTrue(plot._h_cursor_a.movable)
        ha_disp = float(plot._h_cursor_a.value())
        plot._h_cursor_a.setPos(ha_disp + 5.0)
        plot._on_horizontal_cursor_moved()
        self.assertNotEqual(float(result.turn_on.ls_on), ls_before)

    @unittest.skipUnless(
        SONG_DCU_LT_WH_450_800.exists(),
        "songzhenxi LT WH 450V/800A sample missing",
    )
    def test_turn_off_delta_vce_b_uses_blocking_platform_raw_crossing(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow

        plot, bundle, profile, result = self._load_and_plot(SONG_DCU_LT_WH_450_800)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__(
            "dpt_extractor.config.loader", fromlist=["load_config"]
        ).load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)
        win._on_value_clicked("关断过程", "ΔVce")
        self.assertEqual(plot._interactive_mode, "delta_vce")
        b_us = float(plot._cursor_b.value())
        hb_v = plot._from_disp("vce", float(plot._h_cursor_b.value()))
        self.assertAlmostEqual(
            float(np.interp(b_us * 1e-6, bundle.t, bundle.get(profile.vce))),
            hb_v,
            places=6,
        )
        self.assertGreater(b_us, float(bundle.t[result.segments.turn_off[1]] * 1e6))

    @unittest.skipUnless(
        SONG_DCU_LT_WH_530_800.exists(),
        "songzhenxi single-pulse LT WH 530V/800A sample missing",
    )
    def test_single_pulse_delta_vce_uses_dut_stable_band_midpoint(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.metrics.plateau_level import (
            turn_off_delta_vce_blocking_top,
        )

        plot, bundle, profile, result = self._load_and_plot(SONG_DCU_LT_WH_530_800)
        self.assertTrue(result.single_pulse_mode)
        assert result.segments is not None
        off0, off1 = result.segments.turn_off
        vce = bundle.get(profile.vce)
        expected_hb = turn_off_delta_vce_blocking_top(
            vce, off0, off1, bundle.dt
        )
        self.assertAlmostEqual(expected_hb, 536.125, places=6)
        self.assertAlmostEqual(
            result.turn_off.delta_vce,
            result.turn_off.vce_off_max - expected_hb,
            places=9,
        )

        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__(
            "dpt_extractor.config.loader", fromlist=["load_config"]
        ).load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)
        win._on_value_clicked("关断过程", "ΔVce")
        b_us = float(plot._cursor_b.value())
        hb_v = plot._from_disp("vce", float(plot._h_cursor_b.value()))
        self.assertAlmostEqual(hb_v, expected_hb, places=6)
        self.assertAlmostEqual(
            float(np.interp(b_us * 1e-6, bundle.t, vce)),
            hb_v,
            places=6,
        )

    def test_didt_interaction_mode(self):
        from dpt_extractor.gui.main_window import MainWindow

        plot, bundle, profile, result = self._load_and_plot(WH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__("dpt_extractor.config.loader", fromlist=["load_config"]).load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)
        win._enable_didt_interaction("关断过程")
        self.assertEqual(plot._interactive_mode, "didt")
        self.assertEqual(plot._active_channel, "ic")
        self.assertFalse(plot._cursor_a.movable)
        self.assertTrue(plot._h_cursor_a.movable)
        interval = win._parameter_interval_us("关断过程", "di/dt")
        search_t0, search_t1 = interval
        ha_a = plot._from_disp("ic", float(plot._h_cursor_a.value()))
        hb_a = plot._from_disp("ic", float(plot._h_cursor_b.value()))
        res = win._compute_didt_base_top("关断过程", search_t0, search_t1, ha_a, hb_a)
        self.assertGreater(res.didt, 0.0)
        self.assertIsNotNone(res.t_pct_a_s)

    def test_turn_off_didt_levels_cannot_leak_into_turn_on(self):
        from dpt_extractor.gui.main_window import MainWindow

        plot, bundle, profile, result = self._load_and_plot(WH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__(
            "dpt_extractor.config.loader", fromlist=["load_config"]
        ).load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)

        win._enable_didt_interaction("关断过程")
        assert plot._h_cursor_a is not None and plot._h_cursor_b is not None
        plot._h_cursor_a.setPos(plot._to_disp("ic", 123.456))
        plot._h_cursor_b.setPos(plot._to_disp("ic", -78.9))

        on_interval = win._parameter_interval_us("开通", "di/dt")
        assert on_interval is not None
        expected = win._turn_on_didt_context(*on_interval)
        assert expected is not None
        win._enable_didt_interaction("开通")

        actual_top = plot._from_disp("ic", float(plot._h_cursor_a.value()))
        actual_base = plot._from_disp("ic", float(plot._h_cursor_b.value()))
        self.assertAlmostEqual(actual_top, expected.top_a, places=9)
        self.assertAlmostEqual(actual_base, expected.base_a, places=9)
        self.assertNotAlmostEqual(actual_top, 123.456, places=3)
        self.assertEqual(win._active_slope_param, ("开通", "di/dt"))
        win.close()

    def test_invalid_manual_didt_clears_stale_ab_and_recovers_once_valid(self):
        from dpt_extractor.gui.main_window import MainWindow

        plot, bundle, profile, result = self._load_and_plot(WH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__(
            "dpt_extractor.config.loader", fromlist=["load_config"]
        ).load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)
        win._enable_didt_interaction("开通")
        self.assertTrue(plot._slope_ab_valid)
        self.assertTrue(plot._cursor_a.isVisible())
        callback = plot._interactive_on_change
        self.assertIsNotNone(callback)
        on_interval = win._parameter_interval_us("开通", "di/dt")
        assert on_interval is not None
        context = win._turn_on_didt_context(*on_interval)
        assert context is not None

        callback(0.0, 0.0)
        self.assertFalse(plot._slope_ab_valid)
        self.assertFalse(plot._cursor_a.isVisible())
        self.assertFalse(plot._cursor_b.isVisible())
        self.assertTrue(result.is_metric_unavailable("开通", "di/dt"))
        self.assertTrue(result.is_metric_unavailable("开通", "Ls_on"))

        callback(context.top_a, context.base_a)
        self.assertTrue(plot._slope_ab_valid)
        self.assertTrue(plot._cursor_a.isVisible())
        self.assertTrue(plot._cursor_b.isVisible())
        self.assertFalse(result.is_metric_unavailable("开通", "di/dt"))
        self.assertFalse(result.is_metric_unavailable("开通", "Ls_on"))
        win.close()

    def test_valid_cursor_readout_does_not_reapply_visibility_on_every_update(self):
        from unittest.mock import Mock

        plot, _bundle, _profile, _result = self._load_and_plot(WH)
        plot._interactive_mode = "didt"
        plot._slope_ab_valid = True
        plot._parameter_cursor_context_suppressed = False
        original = plot._apply_cursor_visibility
        original()
        plot._apply_cursor_visibility = Mock(wraps=original)
        for _ in range(8):
            plot._update_readout(update_axis=False)
        self.assertEqual(plot._apply_cursor_visibility.call_count, 0)

    def test_rr_didt_interaction_no_crash(self):
        from dpt_extractor.gui.main_window import MainWindow

        if not UH.exists():
            self.skipTest("UH sample missing")
        plot, bundle, profile, result = self._load_and_plot(UH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = __import__(
            "dpt_extractor.config.loader", fromlist=["load_config"]
        ).load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)
        win._enable_didt_interaction("反向恢复")
        self.assertEqual(plot._interactive_mode, "didt")
        self.assertEqual(plot._slope_channel, "irr")
        ha_before = float(plot._h_cursor_a.value())
        plot._highlight_trace("vce")
        self.assertEqual(plot._slope_channel, "irr")
        ha_irr = plot._from_disp("irr", float(plot._h_cursor_a.value()))
        self.assertAlmostEqual(ha_irr, plot._from_disp("irr", ha_before), places=3)
        interval = win._parameter_interval_us("反向恢复", "di/dt")
        self.assertIsNotNone(interval)
        search_t0, search_t1 = interval
        base_a = win._default_didt_base_a("反向恢复", search_t0, search_t1)
        top_a = win._default_didt_top_a("反向恢复", search_t0, search_t1)
        # IDM 水平卡尺语义：Ha=恢复尾部基线，Hb=带符号正向平台。
        self.assertGreater(top_a, -100.0)
        self.assertLess(top_a, 150.0)
        self.assertLess(base_a, -900.0)
        res = win._compute_didt_base_top(
            "反向恢复", search_t0, search_t1, top_a, base_a
        )
        self.assertGreater(res.didt, 1.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)
        assert res.t_pct_a_s is not None and res.t_pct_b_s is not None
        self.assertLess(res.t_pct_a_s, res.t_pct_b_s)
        self.assertAlmostEqual(
            res.didt, result.reverse_recovery.didt_irr, places=9
        )

    def test_slope_horizontal_drag_does_not_refocus_view(self):
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.gui.main_window import MainWindow

        for section, name, enable in (
            ("关断过程", "dv/dt", "_enable_dvdt_interaction"),
            ("反向恢复", "di/dt", "_enable_didt_interaction"),
        ):
            with self.subTest(section=section, name=name):
                plot, bundle, profile, result = self._load_and_plot(UH)
                win = MainWindow()
                win.bundle = bundle
                win.profile = profile
                win.result = result
                win.cfg = __import__(
                    "dpt_extractor.config.loader", fromlist=["load_config"]
                ).load_config()
                win.wave_plot = plot
                win.result_table.set_result(result)
                getattr(win, enable)(section)

                plot.focus_interval_us(12.0, 14.0)
                before = plot.current_x_range_us()
                self.assertIsNotNone(before)
                assert before is not None
                assert plot._h_cursor_b is not None
                plot._h_cursor_b.setPos(float(plot._h_cursor_b.value()) + 0.1)
                QApplication.processEvents()
                after = plot.current_x_range_us()
                self.assertIsNotNone(after)
                assert after is not None
                self.assertAlmostEqual(after[0], before[0], places=6)
                self.assertAlmostEqual(after[1], before[1], places=6)
                win.close()

    @unittest.skipUnless(
        SONG_SMC_HT_WL_1048.exists(), "songzhenxi SMC HT WL 1048A sample missing"
    )
    def test_switching_parameter_focus_is_bounded_and_reserves_post_event_room(self):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.waveform_plot import (
            PARAM_FOCUS_ANCHOR_FRACTION,
            PARAM_FOCUS_DEFAULT_US_PER_DIV,
        )

        plot, bundle, profile, result = self._load_and_plot(SONG_SMC_HT_WL_1048)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)

        def assert_focus(section: str, name: str) -> None:
            interval = win._parameter_interval_us(section, name)
            self.assertIsNotNone(interval)
            win._on_value_clicked(section, name)
            xr = plot.current_x_range_us()
            self.assertIsNotNone(xr)
            x0, x1 = xr
            edge_us = win._switching_focus_anchor_us(section)
            self.assertIsNotNone(edge_us)
            assert edge_us is not None
            if section == "关断过程":
                ref = win._turn_off_timing_instants().t_v90_s
            elif section in {"开通", "反向恢复"}:
                ref = win._turn_on_timing_instants().t_v10_s
            else:
                ref = None
            if ref is not None:
                ref_us = float(ref * 1e6)
                self.assertGreaterEqual(ref_us - edge_us, -1e-9)
                self.assertLessEqual(ref_us - edge_us, 0.250001)
            self.assertIsNotNone(plot._full_x_range)
            assert plot._full_x_range is not None
            full_x0, full_x1 = plot._full_x_range
            self.assertGreaterEqual(x0, full_x0 - 1e-6)
            self.assertLessEqual(x1, full_x1 + 1e-6)
            self.assertAlmostEqual(
                x1 - x0, PARAM_FOCUS_DEFAULT_US_PER_DIV * 10.0, delta=0.02
            )
            self.assertAlmostEqual(
                (edge_us - x0) / (x1 - x0),
                PARAM_FOCUS_ANCHOR_FRACTION,
                delta=0.02,
            )
            if plot._cursor_a is not None and plot._cursor_b is not None:
                a = float(plot._cursor_a.value())
                b = float(plot._cursor_b.value())
                self.assertGreaterEqual(min(a, b), x0 - 1e-6)
                self.assertLessEqual(max(a, b), x1 + 1e-6)

        assert_focus("关断过程", "Eoff")
        assert_focus("开通", "Eon")
        assert_focus("反向恢复", "di/dt")
        win.close()

    @unittest.skipUnless(
        SONG_SMC_RT_UH_1048.exists(), "songzhenxi SMC RT UH 1048A sample missing"
    )
    def test_crosstalk_first_and_second_click_both_use_200ns_per_div(self):
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.main_window import MainWindow

        plot, bundle, profile, result = self._load_and_plot(SONG_SMC_RT_UH_1048)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)
        key = ("关断过程", "串扰电压")
        try:
            win._on_value_clicked(*key)
            QApplication.processEvents()
            first = plot.current_x_range_us()
            self.assertIsNotNone(first)
            assert first is not None
            self.assertAlmostEqual(first[1] - first[0], 2.0, places=6)
            self.assertEqual(plot._x_scale_edit.text(), "200 ns/div")
            self.assertNotIn(key, win._manual_intervals)

            win._on_value_clicked(*key)
            QApplication.processEvents()
            second = plot.current_x_range_us()
            self.assertIsNotNone(second)
            assert second is not None
            self.assertAlmostEqual(second[1] - second[0], 2.0, places=6)
            self.assertAlmostEqual(second[0], first[0], places=6)
            self.assertAlmostEqual(second[1], first[1], places=6)
            self.assertEqual(plot._x_scale_edit.text(), "200 ns/div")
            self.assertNotIn(key, win._manual_intervals)
        finally:
            win.close()
            plot.close()

    @unittest.skipUnless(
        SONG_DCU_RT_WL_480_1000.exists() and SONG_SMC_HT_WL_1048.exists(),
        "songzhenxi focus regression samples missing",
    )
    def test_default_slope_and_energy_focus_uses_real_ab_not_search_bounds(self):
        from copy import deepcopy

        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.waveform_plot import PARAM_FOCUS_ANCHOR_FRACTION

        cases = (
            (
                SONG_DCU_RT_WL_480_1000,
                (
                    ("关断过程", "dv/dt"),
                    ("关断过程", "di/dt"),
                    ("关断过程", "Eoff"),
                ),
            ),
            (
                SONG_SMC_HT_WL_1048,
                (
                    ("开通", "dv/dt"),
                    ("开通", "di/dt"),
                    ("开通", "Eon"),
                ),
            ),
        )

        for sample_path, params in cases:
            plot, bundle, profile, result = self._load_and_plot(sample_path)
            result_before_focus = deepcopy(result)
            win = MainWindow()
            win.bundle = bundle
            win.profile = profile
            win.result = result
            win.cfg = load_config()
            win.wave_plot = plot
            win.result_table.set_result(result)
            focus_calls: list[tuple[float, tuple[float, ...], float]] = []
            original_focus = plot.focus_parameter_window_us

            def _record_focus(
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

            plot.focus_parameter_window_us = _record_focus
            try:
                for section, name in params:
                    with self.subTest(
                        sample=sample_path.name,
                        section=section,
                        name=name,
                    ):
                        focus_calls.clear()
                        win._on_value_clicked(section, name)
                        QApplication.processEvents()
                        self.assertTrue(focus_calls)
                        self.assertIsNotNone(plot._cursor_a)
                        self.assertIsNotNone(plot._cursor_b)
                        assert (
                            plot._cursor_a is not None
                            and plot._cursor_b is not None
                        )

                        anchor_us, required_times, anchor_fraction = focus_calls[-1]
                        self.assertEqual(len(required_times), 2)
                        actual_ab = sorted(
                            (
                                float(plot._cursor_a.value()),
                                float(plot._cursor_b.value()),
                            )
                        )
                        required_ab = sorted(required_times)
                        self.assertAlmostEqual(
                            required_ab[0], actual_ab[0], places=6
                        )
                        self.assertAlmostEqual(
                            required_ab[1], actual_ab[1], places=6
                        )

                        xr = plot.current_x_range_us()
                        self.assertIsNotNone(xr)
                        assert xr is not None
                        x0, x1 = xr
                        span = x1 - x0
                        self.assertAlmostEqual(span, 2.0, delta=0.02)
                        self.assertAlmostEqual(
                            (anchor_us - x0) / span,
                            anchor_fraction,
                            delta=0.025,
                        )
                        self.assertGreaterEqual(actual_ab[0], x0 - 1e-6)
                        self.assertLessEqual(actual_ab[1], x1 + 1e-6)

                self.assertEqual(result, result_before_focus)
            finally:
                win.close()

    def test_restored_trr_refocuses_and_restored_err_keeps_current_view(self):
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.waveform_plot import PARAM_FOCUS_ANCHOR_FRACTION

        plot, bundle, profile, result = self._load_and_plot(UH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = load_config()
        win.wave_plot = plot
        win.result_table.set_result(result)
        calls: list[tuple[float, tuple[float, ...]]] = []
        original_focus = plot.focus_parameter_window_us

        def _record_focus(
            anchor_us: float,
            *required_times_us: float,
            anchor_fraction: float = PARAM_FOCUS_ANCHOR_FRACTION,
        ) -> None:
            calls.append((float(anchor_us), tuple(map(float, required_times_us))))
            original_focus(
                anchor_us,
                *required_times_us,
                anchor_fraction=anchor_fraction,
            )

        plot.focus_parameter_window_us = _record_focus
        try:
            win._on_value_clicked("反向恢复", "Trr")
            plot._emit_trr_measure_changed()
            self.assertIsNotNone(win._manual_trr_measure)
            assert win._manual_trr_measure is not None
            saved_trr_a = float(win._manual_trr_measure[2])
            plot.focus_interval_us(float(bundle.t[0] * 1e6), float(bundle.t[1] * 1e6))
            calls.clear()
            win._on_value_clicked("反向恢复", "Trr")
            QApplication.processEvents()
            self.assertTrue(calls)
            expected_anchor = win._switching_focus_anchor_us("反向恢复")
            self.assertIsNotNone(expected_anchor)
            assert expected_anchor is not None
            self.assertAlmostEqual(calls[-1][0], expected_anchor, places=6)
            self.assertTrue(
                any(abs(value - saved_trr_a) <= 1e-6 for value in calls[-1][1])
            )

            win._on_value_clicked("反向恢复", "Err")
            plot._emit_energy_loss_changed()
            saved_err = win._manual_energy.get(("反向恢复", "Err"))
            self.assertIsNotNone(saved_err)
            assert saved_err is not None
            plot.focus_interval_us(float(bundle.t[0] * 1e6), float(bundle.t[1] * 1e6))
            before_err_view = plot.current_x_range_us()
            calls.clear()
            win._on_value_clicked("反向恢复", "Err")
            QApplication.processEvents()
            self.assertFalse(calls)
            after_err_view = plot.current_x_range_us()
            self.assertIsNotNone(before_err_view)
            self.assertIsNotNone(after_err_view)
            assert before_err_view is not None and after_err_view is not None
            self.assertAlmostEqual(after_err_view[0], before_err_view[0], places=6)
            self.assertAlmostEqual(after_err_view[1], before_err_view[1], places=6)
        finally:
            win.close()

    @unittest.skipUnless(
        UH.exists() and WANGLIHUI_UL_400_1070.exists(),
        "upper/lower DPT samples missing",
    )
    def test_all_dpt_parameter_views_stay_bounded_with_right_side_room(self):
        from copy import deepcopy

        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.waveform_plot import PARAM_FOCUS_ANCHOR_FRACTION

        params = (
            *(
                ("关断过程", name)
                for name in (
                    "ΔVce",
                    "Ic_off_max",
                    "Vce_off_max",
                    "dv/dt",
                    "di/dt",
                    "Ls_off",
                    "Toff",
                    "Td_off",
                    "Tf",
                    "串扰电压",
                    "Pmax",
                    "Eoff",
                )
            ),
            *(
                ("开通", name)
                for name in (
                    "ΔVce",
                    "Ic_on_max",
                    "Vce_on_max",
                    "开通电流",
                    "dv/dt",
                    "di/dt",
                    "Ls_on",
                    "Ton",
                    "Td_on",
                    "Tr",
                    "串扰电压",
                    "Pmax",
                    "Eon",
                )
            ),
            *(
                ("反向恢复", name)
                for name in ("Irr", "Trr", "Vrr", "dv/dt", "di/dt", "Pdmax", "Err")
            ),
        )

        for sample_path in (UH, WANGLIHUI_UL_400_1070):
            plot, bundle, profile, result = self._load_and_plot(sample_path)
            result_before_focus = deepcopy(result)
            win = MainWindow()
            win.bundle = bundle
            win.profile = profile
            win.result = result
            win.cfg = load_config()
            win.wave_plot = plot
            win.result_table.set_result(result)
            focus_calls: list[tuple[float, tuple[float, ...], float]] = []
            original_focus = plot.focus_parameter_window_us

            def _record_focus(
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

            plot.focus_parameter_window_us = _record_focus
            self.assertIsNotNone(plot._full_x_range)
            assert plot._full_x_range is not None
            full_x0, full_x1 = plot._full_x_range
            full_span = full_x1 - full_x0

            for section, name in params:
                with self.subTest(sample=sample_path.name, section=section, name=name):
                    self.assertFalse(result.is_metric_unavailable(section, name))
                    focus_calls.clear()
                    win._on_value_clicked(section, name)
                    QApplication.processEvents()
                    self.assertTrue(focus_calls, "参数点击未调用局部视图构图")
                    xr = plot.current_x_range_us()
                    self.assertIsNotNone(xr)
                    assert xr is not None
                    x0, x1 = xr
                    span = x1 - x0
                    self.assertGreater(span, 0.0)
                    self.assertGreaterEqual(x0, full_x0 - 1e-6)
                    self.assertLessEqual(x1, full_x1 + 1e-6)
                    self.assertGreaterEqual(span, min(2.0, full_span) - 0.02)

                    anchor_us, required_times, anchor_fraction = focus_calls[-1]
                    if section == "反向恢复":
                        expected_anchor = win._switching_focus_anchor_us(section)
                        self.assertIsNotNone(expected_anchor)
                        assert expected_anchor is not None
                        self.assertAlmostEqual(anchor_us, expected_anchor, places=6)
                    if x0 > full_x0 + 0.02 and x1 < full_x1 - 0.02:
                        self.assertGreaterEqual(
                            (anchor_us - x0) / span,
                            anchor_fraction - 0.025,
                        )
                    for required_time in required_times:
                        self.assertGreaterEqual(required_time, x0 - 1e-6)
                        self.assertLessEqual(required_time, x1 + 1e-6)
                    if plot._cursor_a is not None and plot._cursor_b is not None:
                        a = float(plot._cursor_a.value())
                        b = float(plot._cursor_b.value())
                        self.assertGreaterEqual(min(a, b), x0 - 1e-6)
                        self.assertLessEqual(max(a, b), x1 + 1e-6)
            self.assertEqual(result, result_before_focus)
            win.close()

    def test_report_capture_rejects_tiny_or_solid_waveform_grab(self):
        import tempfile
        from unittest.mock import patch

        from PyQt6.QtCore import QSize
        from PyQt6.QtGui import QColor, QPixmap

        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            tiny = QPixmap(1, 1)
            tiny.fill(QColor("#11121f"))
            solid = QPixmap(640, 480)
            solid.fill(QColor("#11121f"))
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "capture.png"
                with patch.object(win.wave_plot, "grab", return_value=tiny):
                    with self.assertRaisesRegex(RuntimeError, "区域过小"):
                        win._save_report_plot_capture(out, QSize(1280, 960))
                with patch.object(win.wave_plot, "grab", return_value=solid):
                    with self.assertRaisesRegex(RuntimeError, "空白或纯色背景"):
                        win._save_report_plot_capture(out, QSize(1280, 960))
        finally:
            win.close()

    def test_full_report_capture_sequence_writes_every_png_without_window_resize(self):
        import tempfile

        from PyQt6.QtCore import QEvent, QObject
        from PyQt6.QtGui import QImage
        from PyQt6.QtWidgets import QApplication

        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.main_window import MainWindow, REPORT_PLOT_CAPTURE_SIZE

        _unused_plot, bundle, profile, result = self._load_and_plot(UH)
        _unused_plot.close()
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = load_config()
        win.result_table.set_result(result)
        win.wave_plot.plot_waveforms(bundle, profile, result)
        win.resize(1100, 760)
        win.show()
        QApplication.processEvents()

        class _ResizeCounter(QObject):
            def __init__(self) -> None:
                super().__init__()
                self.resize_count = 0
                self.move_count = 0

            def eventFilter(self, watched, event) -> bool:  # noqa: N802
                if event.type() == QEvent.Type.Resize:
                    self.resize_count += 1
                elif event.type() == QEvent.Type.Move:
                    self.move_count += 1
                return False

        window_events = _ResizeCounter()
        waveform_events = _ResizeCounter()
        win.installEventFilter(window_events)
        win.wave_plot.installEventFilter(waveform_events)
        before_window_geometry = win.geometry()
        before_waveform_geometry = win.wave_plot.geometry()
        before_minimum = win.wave_plot.minimumSize()
        before_maximum = win.wave_plot.maximumSize()
        before_x, before_y = win.wave_plot.plot.getPlotItem().getViewBox().viewRange()

        with tempfile.TemporaryDirectory() as tmp:
            images = win._capture_report_images(Path(tmp))
            self.assertEqual(len(images), len(win._report_image_params()))
            for path in images.values():
                image = QImage(str(path))
                self.assertFalse(image.isNull(), path.name)
                self.assertEqual(image.size(), REPORT_PLOT_CAPTURE_SIZE, path.name)
                self.assertGreater(path.stat().st_size, 0, path.name)

        after_x, after_y = win.wave_plot.plot.getPlotItem().getViewBox().viewRange()
        self.assertEqual(win.geometry(), before_window_geometry)
        self.assertEqual(win.wave_plot.geometry(), before_waveform_geometry)
        self.assertEqual(win.wave_plot.minimumSize(), before_minimum)
        self.assertEqual(win.wave_plot.maximumSize(), before_maximum)
        self.assertEqual(window_events.resize_count, 0)
        self.assertEqual(window_events.move_count, 0)
        self.assertEqual(waveform_events.resize_count, 0)
        self.assertEqual(waveform_events.move_count, 0)
        self.assertAlmostEqual(after_x[0], before_x[0], places=6)
        self.assertAlmostEqual(after_x[1], before_x[1], places=6)
        self.assertAlmostEqual(after_y[0], before_y[0], places=6)
        self.assertAlmostEqual(after_y[1], before_y[1], places=6)
        win.close()

    def test_param_focus_x_scale_memory(self):
        from dpt_extractor.gui.waveform_plot import PARAM_FOCUS_DEFAULT_US_PER_DIV

        plot, _, _, _ = self._load_and_plot(WH)
        mid = 18.0
        plot.focus_interval_us(mid - 0.1, mid + 0.1)
        self.assertAlmostEqual(plot._x_us_per_div, PARAM_FOCUS_DEFAULT_US_PER_DIV, places=9)
        self.assertEqual(plot._x_scale_edit.text(), "200 ns/div")
        plot._x_scale_edit.setText("100")
        plot._on_x_scale_committed()
        plot.focus_interval_us(mid - 0.5, mid + 0.5)
        self.assertAlmostEqual(plot._x_us_per_div, 0.1, places=9)
        self.assertEqual(plot._x_scale_edit.text(), "100 ns/div")

    def test_horizontal_scale_readout(self):
        from dpt_extractor.gui.waveform_plot import (
            X_NS_PER_DIV,
            _parse_time_per_div_input,
            _quantize_x_us_per_div,
            _x_wheel_step_us,
        )

        class _SceneWheel:
            def delta(self):
                return 120

        self.assertEqual(_quantize_x_us_per_div(0.121), 0.1)
        self.assertAlmostEqual(_x_wheel_step_us(0.2), X_NS_PER_DIV / 1000.0, places=9)

        plot, _, _, _ = self._load_and_plot(WH)
        self.assertIn("div", plot._x_scale_edit.text())
        self.assertGreater(plot._x_us_per_div, 0.0)
        self.assertAlmostEqual(_parse_time_per_div_input("200"), 0.2)
        self.assertAlmostEqual(_parse_time_per_div_input("0.2"), 0.2)
        self.assertAlmostEqual(_parse_time_per_div_input("200ns"), 0.2)
        mid = 18.0
        plot._apply_x_us_per_div(0.2, center_us=mid)
        self.assertEqual(plot._x_scale_edit.text(), "200 ns/div")
        self.assertAlmostEqual(plot._x_us_per_div, 0.2, places=9)
        vb = plot.plot.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        self.assertAlmostEqual(x1 - x0, 2.0, places=6)
        self.assertAlmostEqual((x0 + x1) * 0.5, mid, places=6)
        plot._on_x_wheel(_SceneWheel())
        self.assertEqual(plot._x_scale_edit.text(), "150 ns/div")
        plot._apply_x_us_per_div(0.15, center_us=mid)
        self.assertEqual(plot._x_scale_edit.text(), "150 ns/div")
        plot._x_scale_edit.setText("250")
        plot._on_x_scale_committed()
        self.assertEqual(plot._x_scale_edit.text(), "250 ns/div")
        self.assertAlmostEqual(_quantize_x_us_per_div(plot._x_us_per_div), 0.25, places=9)

    def test_viewbox_wheel_fallback_does_not_capture_itself(self):
        plot, _, _, _ = self._load_and_plot(WH)
        vb = plot.plot.getPlotItem().getViewBox()
        handler = vb.wheelEvent
        closure_cells = getattr(handler, "__closure__", ()) or ()
        captured = [cell.cell_contents for cell in closure_cells]

        self.assertNotIn(handler, captured)

    def test_xrange_limits(self):
        plot, _, _, _ = self._load_and_plot(WH)
        vb = plot.plot.getPlotItem().getViewBox()
        # setLimits 内部存到 vb.state['limits']
        limits = vb.state["limits"]
        full = plot._full_x_range
        self.assertIsNotNone(full)
        self.assertAlmostEqual(limits["xLimits"][0], full[0], places=3)
        self.assertAlmostEqual(limits["xLimits"][1], full[1], places=3)
        # maxXRange ≈ full span（不允许缩小到超出全景）
        self.assertAlmostEqual(limits["xRange"][1], full[1] - full[0], places=3)

    def test_global_cursor_callback(self):
        plot, _, _, _ = self._load_and_plot(WH)
        captured = []
        plot.set_global_cursor_handler(lambda a, b: captured.append((a, b)))
        plot._interactive_enabled = True
        plot._interactive_mode = "global"
        # 拖动 B
        plot._cursor_b.setValue(plot._cursor_b.value() + 0.5)
        plot._on_any_cursor_moved()
        self.assertGreater(len(captured), 0)
        a, b = captured[-1]
        self.assertLess(a, b)

    def test_horizontal_cursor_callback(self):
        plot, _, _, _ = self._load_and_plot(WH)
        captured = []
        plot.set_horizontal_cursor_handler(lambda ha, hb: captured.append((ha, hb)))
        plot._h_cursor_b.setValue(plot._h_cursor_b.value() + 1.0)
        self.assertGreater(len(captured), 0)

    def test_reopen_keeps_limits(self):
        plot, _, _, _ = self._load_and_plot(WH)
        full_first = plot._full_x_range
        # 再画 UH 切换工况
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.io.waveform_loader import load_waveform
        from dpt_extractor.models.bridge_profile import guess_profile_from_path, make_profile
        from dpt_extractor.models.channel_mapping import apply_mapping, infer_mapping_from_bundle
        from dpt_extractor.pipeline.extract import extract_all

        bundle2 = load_waveform(UH)
        guessed2 = guess_profile_from_path(UH.name)
        inferred2 = infer_mapping_from_bundle(bundle2, guessed2.bridge)
        prof2 = make_profile(guessed2.phase, guessed2.bridge)
        if inferred2 is not None:
            prof2 = apply_mapping(prof2, inferred2)
        result2 = extract_all(bundle2, prof2, load_config())
        plot.plot_waveforms(bundle2, prof2, result2)
        full_second = plot._full_x_range
        self.assertIsNotNone(full_second)
        self.assertNotEqual(full_first, full_second)
        # 持久光标位置应仍在新范围内
        a = plot._cursor_a.value()
        b = plot._cursor_b.value()
        self.assertGreaterEqual(a, full_second[0])
        self.assertLessEqual(b, full_second[1])


@unittest.skipUnless(WH.exists(), "WH sample missing")
class TestMainWindowSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    @unittest.skipUnless(SHORT_VH_750.exists(), "short-circuit sample missing")
    def test_invalid_manual_short_energy_window_does_not_store_nan(self) -> None:
        from unittest.mock import patch

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.test_mode import TestMode

        win = MainWindow()
        try:
            mode_index = win.combo_test_mode.findData(TestMode.SHORT_CIRCUIT.value)
            self.assertGreaterEqual(mode_index, 0)
            win.combo_test_mode.setCurrentIndex(mode_index)
            win._apply_test_mode_ui()
            win._load_file(str(SHORT_VH_750), background=False)
            self.assertIsNotNone(win.result)
            assert win.result is not None and win.result.segments is not None
            i0, i1 = win.result.segments.turn_off
            sc = win.result.short_circuit

            for name, value_attr, source_attr in (
                ("短路能量Esc_本管", "esc_dut", "energy_dut_channel"),
                ("短路能量Esc_对管", "esc_other", "energy_other_channel"),
            ):
                with self.subTest(name=name):
                    win.result.unavailable_metrics.discard(("短路过程", name))
                    setattr(sc, value_attr, 1.25)
                    setattr(sc, source_attr, "ORIGINAL")
                    with patch(
                        "dpt_extractor.gui.main_window.short_circuit_energy_value",
                        return_value=(float("nan"), "INVALID"),
                    ):
                        value = win._recompute_param_from_interval(
                            "短路过程", name, i0, i1
                        )

                    self.assertIsNone(value)
                    self.assertEqual(getattr(sc, value_attr), 1.25)
                    self.assertEqual(getattr(sc, source_attr), "ORIGINAL")
        finally:
            win.close()

    @unittest.skipUnless(
        SONG_SMC_HT_20260717_UH_1048.exists() and SONG_SMC_RT_UH_1048.exists(),
        "songzhenxi 20260717 HT / 20260506 RT UH samples missing",
    )
    def test_songzhenxi_rr_didt_pipeline_context_gui_and_overlay_are_identical(
        self,
    ) -> None:
        """重点 UH 样例必须由一份 RR context 同时驱动表值、卡尺和读数框。"""
        import numpy as np
        from PyQt6.QtCore import QPointF

        from dpt_extractor.gui.main_window import MainWindow, REPORT_PROGRESS_TOTAL
        from dpt_extractor.metrics.iec_windows import err_recovery_peak_index
        from dpt_extractor.metrics.slopes import (
            _rr_quiet_local_platform_window,
            _rr_spike_guarded_extreme_index,
        )
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        cases = (
            (SONG_SMC_HT_20260717_UH_1048, 5.485001520939264),
            (SONG_SMC_RT_UH_1048, 6.3621142660389545),
        )
        for sample_path, expected_didt in cases:
            with self.subTest(sample=str(sample_path)):
                win = MainWindow()
                try:
                    win._load_file(str(sample_path))
                    self.assertIsNotNone(win.bundle)
                    self.assertIsNotNone(win.result)
                    assert win.bundle is not None and win.result is not None

                    interval = win._parameter_interval_us("反向恢复", "di/dt")
                    self.assertIsNotNone(interval)
                    assert interval is not None
                    context = win._rr_didt_context(*interval)
                    self.assertIsNotNone(context)
                    assert context is not None
                    crossing = context.crossing
                    self.assertFalse(context.used_fallback)
                    self.assertEqual(context.polarity, -1)
                    self.assertAlmostEqual(
                        win.result.reverse_recovery.didt_irr,
                        expected_didt,
                        places=9,
                    )
                    self.assertAlmostEqual(crossing.didt, expected_didt, places=9)
                    self.assertIsNotNone(crossing.t_pct_a_s)
                    self.assertIsNotNone(crossing.t_pct_b_s)
                    assert crossing.t_pct_a_s is not None
                    assert crossing.t_pct_b_s is not None
                    self.assertLess(crossing.t_pct_a_s, crossing.t_pct_b_s)

                    # GUI 的 IDM 水平语义为 Ha=尾部基线、Hb=带符号正向平台。
                    gui_ha = win._default_didt_top_a("反向恢复", *interval)
                    gui_hb = win._default_didt_base_a("反向恢复", *interval)
                    self.assertEqual(gui_ha, context.base_a)
                    self.assertEqual(gui_hb, context.forward_a)
                    manual = win._compute_didt_base_top(
                        "反向恢复", *interval, gui_ha, gui_hb
                    )
                    self.assertEqual(manual.didt, crossing.didt)
                    self.assertEqual(manual.t_pct_a_s, crossing.t_pct_a_s)
                    self.assertEqual(manual.t_pct_b_s, crossing.t_pct_b_s)

                    win._on_value_clicked("反向恢复", "di/dt")
                    self.app.processEvents()
                    plot = win.wave_plot
                    self.assertAlmostEqual(
                        float(plot._cursor_a.value()),
                        crossing.t_pct_a_s * 1e6,
                        places=9,
                    )
                    self.assertAlmostEqual(
                        float(plot._cursor_b.value()),
                        crossing.t_pct_b_s * 1e6,
                        places=9,
                    )
                    self.assertAlmostEqual(
                        plot._from_disp("irr", float(plot._h_cursor_a.value())),
                        context.base_a,
                        places=12,
                    )
                    self.assertAlmostEqual(
                        plot._from_disp("irr", float(plot._h_cursor_b.value())),
                        context.forward_a,
                        places=12,
                    )

                    if sample_path == SONG_SMC_HT_20260717_UH_1048:
                        rr0, rr1 = win.result.segments.reverse_recovery
                        irr = bundle_reverse_recovery_current(
                            win.bundle, win.profile
                        )
                        peak_idx = rr0 + int(
                            err_recovery_peak_index(
                                irr[rr0 : rr1 + 1], win.bundle.dt
                            )
                        )
                        peak_t = float(win.bundle.t[peak_idx])
                        platform_i0 = int(
                            np.searchsorted(
                                win.bundle.t,
                                peak_t - 0.6e-6,
                                side="left",
                            )
                        )
                        platform_i1 = int(
                            np.searchsorted(
                                win.bundle.t,
                                peak_t - 0.2e-6,
                                side="right",
                            )
                        )
                        source_region = irr[platform_i0:platform_i1]
                        stable_platform = _rr_quiet_local_platform_window(
                            source_region,
                            win.bundle.dt,
                            min_ns=200.0,
                        )
                        guarded_min = _rr_spike_guarded_extreme_index(
                            stable_platform, maximum=False
                        )
                        guarded_max = _rr_spike_guarded_extreme_index(
                            stable_platform, maximum=True
                        )
                        expected_forward = 0.5 * (
                            float(stable_platform[guarded_min])
                            + float(stable_platform[guarded_max])
                        )
                        self.assertEqual(
                            expected_forward,
                            -968.0624999999999,
                        )
                        self.assertEqual(context.forward_a, expected_forward)
                        # Selecting the result-table row must place the visible
                        # lower horizontal cursor at that exact physical level.
                        table_cursor_forward = plot._from_disp(
                            "irr", float(plot._h_cursor_b.value())
                        )
                        self.assertAlmostEqual(
                            table_cursor_forward,
                            expected_forward,
                            places=12,
                        )

                        def _assert_forward_line_matches_platform_pixel() -> None:
                            physical = plot._from_disp(
                                "irr", float(plot._h_cursor_b.value())
                            )
                            self.assertAlmostEqual(
                                physical,
                                expected_forward,
                                places=12,
                            )
                            vb = plot.plot.getPlotItem().getViewBox()
                            line_y = float(
                                vb.mapViewToScene(
                                    QPointF(0.0, float(plot._h_cursor_b.value()))
                                ).y()
                            )
                            platform_y = float(
                                vb.mapViewToScene(
                                    QPointF(
                                        0.0,
                                        plot._to_disp("irr", expected_forward),
                                    )
                                ).y()
                            )
                            self.assertAlmostEqual(line_y, platform_y, delta=0.25)

                        # Changing the real CH3 position or A/div must reproject
                        # the already selected signed platform level instead of
                        # changing its physical value or leaving the line behind.
                        irr_key = plot._display_key_for_channel("irr")
                        self.assertIn(irr_key, plot._trace_items)
                        _assert_forward_line_matches_platform_pixel()
                        plot._set_channel_offset(
                            irr_key,
                            float(plot._disp_offset[irr_key]) + 0.75,
                        )
                        _assert_forward_line_matches_platform_pixel()
                        plot._set_channel_scale(
                            irr_key,
                            float(plot._disp_scale[irr_key]) * 1.25,
                        )
                        _assert_forward_line_matches_platform_pixel()

                        # Exercise the production report-capture state rather
                        # than merely reusing the live table selection.  The
                        # level sampled at the instant the RR di/dt PNG would be
                        # written must remain the same frozen-page value.
                        import tempfile

                        captured_report_levels: list[float] = []
                        writer_finished: list[bool] = []
                        win._report_image_params = lambda: (  # type: ignore[method-assign]
                            ("反向恢复", "di/dt"),
                        )

                        def fake_capture(path, _size):
                            captured_report_levels.append(
                                plot._from_disp(
                                    "irr", float(plot._h_cursor_b.value())
                                )
                            )
                            path.write_bytes(b"rr-didt-capture")

                        def fake_writer(tempdir, images, _results, **_kwargs):
                            self.assertEqual(
                                tuple(images), (("反向恢复", "di/dt"),)
                            )
                            writer_finished.append(True)
                            tempdir.cleanup()

                        win._save_report_plot_capture = fake_capture  # type: ignore[method-assign]
                        win._start_report_write_task = fake_writer  # type: ignore[method-assign]
                        tempdir = tempfile.TemporaryDirectory()
                        win._report_request_id = 77
                        win._begin_report_progress(
                            REPORT_PROGRESS_TOTAL,
                            "准备报告截图...",
                        )
                        win._start_report_capture_sequence(
                            tempdir,
                            [win.result],
                            request_id=77,
                        )
                        for _ in range(30):
                            self.app.processEvents()
                            if writer_finished:
                                break
                        if not writer_finished:
                            tempdir.cleanup()
                        self.assertEqual(writer_finished, [True])
                        self.assertEqual(len(captured_report_levels), 1)
                        self.assertAlmostEqual(
                            captured_report_levels[0],
                            expected_forward,
                            places=12,
                        )

                    irr = bundle_reverse_recovery_current(win.bundle, win.profile)
                    raw_a = float(
                        np.interp(crossing.t_pct_a_s, win.bundle.t, irr)
                    )
                    raw_b = float(
                        np.interp(crossing.t_pct_b_s, win.bundle.t, irr)
                    )
                    self.assertAlmostEqual(raw_a, crossing.th_a, places=9)
                    self.assertAlmostEqual(raw_b, crossing.th_b, places=9)

                    # 斜率框用 A/B 的百分比交点差，不得误用完整 Ha↔Hb 跨度。
                    expected_delta = abs(raw_b - raw_a)
                    expected_rate = expected_delta / (
                        (crossing.t_pct_b_s - crossing.t_pct_a_s) * 1e6
                    )
                    readout = (
                        plot._cursor_hb_ha_delta_label.textItem.toPlainText()
                    )
                    self.assertIn(f"{expected_delta:.3f} A", readout)
                    self.assertIn(f"{expected_rate:.2f} MA/s", readout)
                    self.assertNotIn(
                        f"{abs(context.forward_a - context.base_a):.3f} A",
                        readout,
                    )
                finally:
                    win.close()

    @unittest.skipUnless(
        WANGLIHUI_UH_486_985.exists() and WANGLIHUI_UH_486_985_FAST.exists(),
        "wanglihui UH 486V 985A samples missing",
    )
    def test_wanglihui_rr_didt_survives_manual_ch3_inversion(self) -> None:
        """通道设置反相后应重算同一物理斜率，不能坍缩到近零噪声。"""
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        cases = (
            (
                WANGLIHUI_UH_486_985,
                10.938162389246163,
                -956.671875,
                12.515625,
            ),
            (
                WANGLIHUI_UH_486_985_FAST,
                13.397852675728164,
                -954.65625,
                15.4453125,
            ),
        )
        for sample_path, expected_didt, expected_forward, expected_base in cases:
            with self.subTest(sample=sample_path.name):
                win = MainWindow()
                try:
                    win._load_file(str(sample_path))
                    self.assertIsNotNone(win.bundle)
                    self.assertIsNotNone(win.result)
                    assert win.bundle is not None and win.result is not None
                    irr_before = bundle_reverse_recovery_current(
                        win.bundle, win.profile
                    ).copy()
                    source_inversions = set(
                        win.bundle.meta.source_channel_inversions
                    )
                    self.assertFalse(
                        win.wave_plot.channel_inversion_enabled("CH3")
                    )
                    win._on_value_clicked("反向恢复", "di/dt")
                    self.app.processEvents()
                    self.assertEqual(win.wave_plot._interactive_mode, "didt")

                    # Reproduce the real interaction order that previously kept
                    # stale signed levels alive: adjust/save this card first,
                    # then invert its physical source without loading a new file.
                    interval_before = win._parameter_interval_us(
                        "反向恢复", "di/dt"
                    )
                    self.assertIsNotNone(interval_before)
                    assert interval_before is not None
                    context_before = win._rr_didt_context(*interval_before)
                    self.assertIsNotNone(context_before)
                    assert context_before is not None
                    stale_top = float(context_before.base_a + 7.0)
                    stale_base = float(context_before.forward_a + 7.0)
                    win._save_manual_didt(
                        ("反向恢复", "di/dt"),
                        "idm",
                        float(interval_before[0]),
                        float(interval_before[1]),
                        stale_top,
                        stale_base,
                    )
                    self.assertIn(
                        ("反向恢复", "di/dt"), win._manual_didt
                    )

                    win.wave_plot.set_channel_inversion_enabled("CH3", True)
                    self.app.processEvents()
                    self.assertTrue(
                        win.wave_plot.channel_inversion_enabled("CH3")
                    )
                    self.assertIn(
                        "CH3", win.bundle.meta.channel_display_inversions
                    )
                    self.assertEqual(
                        set(win.bundle.meta.source_channel_inversions),
                        source_inversions,
                    )
                    irr_after = bundle_reverse_recovery_current(
                        win.bundle, win.profile
                    )
                    # 上桥逻辑 Irr 会补偿显示反相以避免二次翻转；真实通道
                    # 设置已写入元数据，但参与计算的物理方向应保持不变。
                    np.testing.assert_allclose(irr_after, irr_before)

                    interval = win._parameter_interval_us("反向恢复", "di/dt")
                    self.assertIsNotNone(interval)
                    assert interval is not None
                    context = win._rr_didt_context(*interval)
                    self.assertIsNotNone(context)
                    assert context is not None
                    self.assertFalse(context.used_fallback)
                    self.assertEqual(context.polarity, -1)
                    self.assertAlmostEqual(
                        context.crossing.didt, expected_didt, places=9
                    )
                    self.assertAlmostEqual(
                        context.forward_a, expected_forward, places=9
                    )
                    self.assertAlmostEqual(
                        context.base_a, expected_base, places=9
                    )
                    self.assertGreater(
                        abs(context.forward_a - context.base_a), 500.0
                    )
                    self.assertEqual(
                        win.result.reverse_recovery.didt_irr,
                        context.crossing.didt,
                    )
                    # The saved pre-transform state is invalid.  Because it had
                    # made this card eligible for automatic re-entry, the card
                    # must now be active with freshly calculated levels rather
                    # than the stale values above.
                    self.assertNotIn(
                        ("反向恢复", "di/dt"), win._manual_didt
                    )
                    self.assertEqual(win.wave_plot._interactive_mode, "didt")
                    self.assertAlmostEqual(
                        win.wave_plot._from_disp(
                            "irr", float(win.wave_plot._h_cursor_a.value())
                        ),
                        context.base_a,
                        places=9,
                    )
                    self.assertAlmostEqual(
                        win.wave_plot._from_disp(
                            "irr", float(win.wave_plot._h_cursor_b.value())
                        ),
                        context.forward_a,
                        places=9,
                    )
                    self.assertNotAlmostEqual(context.base_a, stale_top, places=6)
                    self.assertNotAlmostEqual(
                        context.forward_a, stale_base, places=6
                    )
                    self.assertIsNotNone(context.crossing.t_pct_a_s)
                    self.assertIsNotNone(context.crossing.t_pct_b_s)
                    assert context.crossing.t_pct_a_s is not None
                    assert context.crossing.t_pct_b_s is not None
                    self.assertLess(
                        context.crossing.t_pct_a_s,
                        context.crossing.t_pct_b_s,
                    )
                    rr0, rr1 = win.result.segments.reverse_recovery
                    recovery_peak = rr0 + int(
                        np.argmax(irr_after[rr0 : rr1 + 1])
                    )
                    self.assertGreater(
                        float(win.bundle.t[recovery_peak]),
                        context.crossing.t_pct_b_s,
                    )
                finally:
                    win.close()

    @unittest.skipUnless(
        WANGLIHUI_UH_486_985.exists(),
        "wanglihui UH 486V 985A sample missing",
    )
    def test_active_rr_didt_drops_manual_levels_before_ch3_inversion_reentry(self) -> None:
        """An active card must re-enter from the post-inversion auto context."""

        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win._load_file(str(WANGLIHUI_UH_486_985))
            win._on_value_clicked("反向恢复", "di/dt")
            self.app.processEvents()
            interval = win._parameter_interval_us("反向恢复", "di/dt")
            self.assertIsNotNone(interval)
            assert interval is not None
            key = ("反向恢复", "di/dt")
            bad_top, bad_base = 321.0, -123.0
            win._save_manual_didt(
                key,
                "idm",
                interval[0],
                interval[1],
                bad_top,
                bad_base,
            )
            plot = win.wave_plot
            plot._interactive_syncing = True
            try:
                plot._h_cursor_a.setPos(plot._to_disp("irr", bad_top))
                plot._h_cursor_b.setPos(plot._to_disp("irr", bad_base))
            finally:
                plot._interactive_syncing = False

            plot.set_channel_inversion_enabled("CH3", True)
            self.app.processEvents()

            self.assertNotIn(key, win._manual_didt)
            self.assertEqual(win._active_slope_param, key)
            self.assertEqual(plot._interactive_mode, "didt")
            context = win._rr_didt_context(*interval)
            self.assertIsNotNone(context)
            assert context is not None
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_a.value())),
                context.base_a,
                places=9,
            )
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_b.value())),
                context.forward_a,
                places=9,
            )
            self.assertNotAlmostEqual(context.base_a, bad_top, places=3)
            self.assertNotAlmostEqual(context.forward_a, bad_base, places=3)
            self.assertAlmostEqual(
                win.result.reverse_recovery.didt_irr,
                context.crossing.didt,
                places=9,
            )
        finally:
            win.close()

    @unittest.skipUnless(SHORT_VH_750.exists(), "750V VH short sample missing")
    def test_short_vpeak_and_esc_keep_independent_horizontal_channels(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.test_mode import TestMode

        win = MainWindow()
        try:
            mode_index = win.combo_test_mode.findData(TestMode.SHORT_CIRCUIT.value)
            self.assertGreaterEqual(mode_index, 0)
            win.combo_test_mode.setCurrentIndex(mode_index)
            win._apply_test_mode_ui()
            win._load_file(str(SHORT_VH_750), background=False)
            self.assertIsNotNone(win.result)
            assert win.result is not None
            self.assertTrue(win.result.short_circuit_mode)

            name = "应力Vpeak_本管"
            win._on_value_clicked("短路过程", name)
            plot = win.wave_plot
            self.assertEqual(plot._horizontal_cursor_binding("ha"), ("vce", True))
            self.assertEqual(plot._horizontal_cursor_binding("hb"), ("vge", True))
            self.assertEqual(plot._interval_a_channel, "vge")
            self.assertEqual(plot._interval_b_channel, "vge")
            self.assertFalse(plot._horizontal_quantities_comparable())
            self.assertFalse(plot._cursor_hb_ha_delta_label.isVisible())

            ha_before = plot._from_disp("vce", float(plot._h_cursor_a.value()))
            hb_before = plot._from_disp("vge", float(plot._h_cursor_b.value()))
            vce_key = plot._display_key_for_channel("vce")
            vge_key = plot._display_key_for_channel("vge")
            self.assertNotEqual(vce_key, vge_key)
            plot._set_channel_scale(vce_key, 125.0)
            plot._set_channel_offset(vce_key, 1.25)
            plot._set_channel_scale(vge_key, 2.5)
            plot._set_channel_offset(vge_key, -1.0)
            self.assertAlmostEqual(
                plot._from_disp("vce", float(plot._h_cursor_a.value())),
                ha_before,
                places=9,
            )
            self.assertAlmostEqual(
                plot._from_disp("vge", float(plot._h_cursor_b.value())),
                hb_before,
                places=9,
            )
            self.assertNotIn(("短路过程", name), win._manual_extreme_values)

            manual_vpeak = 777.25
            plot._h_cursor_a.setPos(plot._to_disp("vce", manual_vpeak))
            self.app.processEvents()
            self.assertEqual(
                win._manual_extreme_values[("短路过程", name)],
                (manual_vpeak, manual_vpeak),
            )
            self.assertAlmostEqual(
                win.result.short_circuit.vpeak_dut,
                manual_vpeak,
                places=9,
            )

            # A second click must restore the manual Vce line; it must not be
            # replaced by the automatic window peak or converted through Vge.
            win._on_value_clicked("短路过程", name)
            self.assertAlmostEqual(
                plot._from_disp("vce", float(plot._h_cursor_a.value())),
                manual_vpeak,
                places=9,
            )
            self.assertEqual(plot._horizontal_cursor_binding("ha"), ("vce", True))
            self.assertEqual(plot._horizontal_cursor_binding("hb"), ("vge", True))

            win._on_value_clicked("短路过程", "短路能量Esc_本管")
            ha_channel, ha_valid = plot._horizontal_cursor_binding("ha")
            hb_channel, hb_valid = plot._horizontal_cursor_binding("hb")
            self.assertTrue(ha_valid)
            self.assertTrue(hb_valid)
            marker = win._short_circuit_energy_peak_marker(
                "短路能量Esc_本管",
                *win._short_circuit_ic_window_indices(),
            )
            self.assertIsNotNone(marker)
            assert marker is not None
            _peak, expected_energy_channel = marker
            self.assertEqual(ha_channel, expected_energy_channel)
            self.assertIn(ha_channel, plot._trace_items)
            self.assertEqual(hb_channel, "ic")
            self.assertEqual(plot._unit_for_channel(ha_channel), "J")
            self.assertEqual(plot._unit_for_channel(hb_channel), "A")
            self.assertFalse(plot._cursor_hb_ha_delta_label.isVisible())
        finally:
            win.close()

    def test_open_and_drag_cursor_recomputes_param(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win._load_file(str(WH))
        self.assertIsNotNone(win.result)
        # 模拟点击参数 Eoff（进入 energy_loss 四光标模式）
        win._on_value_clicked("关断过程", "Eoff")
        plot = win.wave_plot
        self.assertEqual(plot._interactive_mode, "energy_loss")
        self.assertIsNotNone(plot._cursor_b)
        original_eoff = win.result.turn_off.eoff
        new_b = plot._cursor_b.value() - 0.05
        plot._cursor_b.setValue(new_b)
        # 拖动应该触发 _enable_energy_interaction 的 on_change，更新 result.turn_off.eoff
        # 至少 result 仍是有限数值
        self.assertIsNotNone(win.result.turn_off.eoff)
        self.assertFalse(win.result.turn_off.eoff != win.result.turn_off.eoff)  # 不是 NaN
        win.close()

    def test_pmax_click_uses_power_peak_interval_not_energy_loss(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win._load_file(str(WH))
        self.assertIsNotNone(win.result)
        self.assertIsNotNone(win.result.segments)
        vce_key = win.wave_plot._display_key_for_channel("vce")
        ic_key = win.wave_plot._display_key_for_channel("ic")
        vd_key = win.wave_plot._display_key_for_channel("v_diode")
        win.wave_plot._set_math_formula("MATH8", f"{vce_key} * {vd_key}")
        win.wave_plot._set_math_formula("MATH9", f"{vce_key} * {ic_key}")
        interval = win._parameter_interval_us("关断过程", "Pmax")
        self.assertIsNotNone(interval)
        assert interval is not None

        win._on_value_clicked("关断过程", "Pmax")
        plot = win.wave_plot

        self.assertEqual(plot._interactive_mode, "power_peak")
        self.assertTrue(plot._interval_max_hline_enabled)
        self.assertNotEqual(plot._interactive_mode, "energy_loss")
        self.assertEqual(plot._horizontal_cursor_binding("ha"), ("MATH9", True))
        self.assertFalse(plot._horizontal_cursor_binding("hb")[1])
        self.assertTrue(plot._h_cursor_a.isVisible())
        self.assertFalse(plot._h_cursor_b.isVisible())
        self.assertAlmostEqual(float(plot._cursor_a.value()), interval[0], places=6)
        self.assertAlmostEqual(float(plot._cursor_b.value()), interval[1], places=6)
        aux_point = plot._cursor_auxiliary_point()
        self.assertIsNotNone(aux_point)
        assert aux_point is not None
        channel, peak_t_us, peak_value = aux_point
        self.assertEqual(channel, "MATH9")
        self.assertGreaterEqual(peak_t_us, min(interval))
        self.assertLessEqual(peak_t_us, max(interval))
        self.assertAlmostEqual(
            plot._from_disp(channel, float(plot._h_cursor_a.value())),
            peak_value,
            delta=max(abs(peak_value) * 1e-9, 1e-6),
        )
        win.close()

    def test_visible_power_trace_never_overrides_raw_pmax_value(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.result_table import format_metric_display
        from dpt_extractor.gui.waveform_plot import _is_power_unit
        from dpt_extractor.metrics.energy import peak_power_kw
        from dpt_extractor.metrics.iec_windows import IntegrationWindow
        from dpt_extractor.models.waveform import bundle_total_current

        win = MainWindow()
        try:
            win._load_file(str(WH))
            plot = win.wave_plot
            for key, item in plot._trace_items.items():
                if _is_power_unit(plot._unit_for_channel(key)):
                    plot._hidden_channels.add(key)
                    item.hide()
            vce_key = plot._display_key_for_channel("vce")
            ic_key = plot._display_key_for_channel("ic")
            plot._set_math_formula("MATH9", f"0.8 * {vce_key} * {ic_key}")

            win._on_value_clicked("关断过程", "Pmax")
            self.assertEqual(plot._cursor_endpoint_channel("a"), "MATH9")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "MATH9")
            self.assertEqual(plot._horizontal_cursor_binding("ha"), ("MATH9", True))
            self.assertIn("A/B/Ha 显示", win.statusBar().currentMessage())
            self.assertIn("卡值按原始 V×I", win.statusBar().currentMessage())
            assert plot._cursor_a is not None and plot._cursor_b is not None
            ta = float(plot._cursor_a.value())
            tb = float(plot._cursor_b.value()) - 0.02
            plot._interactive_on_change(ta, tb)
            self.assertEqual(plot._cursor_endpoint_channel("a"), "MATH9")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "MATH9")
            self.assertEqual(plot._horizontal_cursor_binding("ha"), ("MATH9", True))
            self.assertIn("卡值按原始 V×I", win.statusBar().currentMessage())

            t = win.bundle.t
            i0 = int(np.searchsorted(t, min(ta, tb) * 1e-6, side="left"))
            i1 = int(np.searchsorted(t, max(ta, tb) * 1e-6, side="left"))
            expected = peak_power_kw(
                win.bundle.get(win.profile.vce),
                bundle_total_current(win.bundle, win.profile),
                IntegrationWindow(i0, i1, float(t[i0]), float(t[i1])),
            )
            self.assertAlmostEqual(win.result.turn_off.pmax, expected, places=9)
            row = win.result_table._row_meta.index(("关断过程", "Pmax"))
            self.assertEqual(
                win.result_table.table.item(row, 4).text(),
                format_metric_display("关断过程", "Pmax", expected),
            )
        finally:
            win.close()

    def test_scaled_power_math_never_rewrites_restored_power_card_values(self):
        """Drag -> switch/re-enter must retain raw V×I for all power cards."""
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.waveform_plot import _is_power_unit

        win = MainWindow()
        try:
            win._load_file(str(WH))
            plot = win.wave_plot
            vce_key = plot._display_key_for_channel("vce")
            ic_key = plot._display_key_for_channel("ic")
            vd_key = plot._display_key_for_channel("v_diode")
            irr_key = plot._display_key_for_channel("irr")
            cases = (
                (
                    "关断过程",
                    "Pmax",
                    f"0.8 * {vce_key} * {ic_key}",
                    lambda: float(win.result.turn_off.pmax),
                    ("关断过程", "Eoff"),
                ),
                (
                    "开通",
                    "Pmax",
                    f"0.8 * {vce_key} * {ic_key}",
                    lambda: float(win.result.turn_on.pmax),
                    ("开通", "Eon"),
                ),
                (
                    "反向恢复",
                    "Pdmax",
                    f"0.8 * ABS({vd_key}) * ABS({irr_key})",
                    lambda: float(win.result.reverse_recovery.pdmax),
                    ("反向恢复", "Err"),
                ),
            )

            for section, metric, formula, stored_value, switch_to in cases:
                with self.subTest(section=section, metric=metric):
                    plot._set_math_formula("MATH9", formula)
                    for key, item in plot._trace_items.items():
                        if key != "MATH9" and _is_power_unit(
                            plot._unit_for_channel(key)
                        ):
                            plot._hidden_channels.add(key)
                            item.hide()
                    plot._hidden_channels.discard("MATH9")

                    win._on_value_clicked(section, metric)
                    self.assertEqual(plot._horizontal_cursor_binding("ha"), ("MATH9", True))
                    assert plot._cursor_a is not None and plot._cursor_b is not None
                    ta = float(plot._cursor_a.value())
                    tb = float(plot._cursor_b.value()) - 0.02
                    plot._interactive_on_change(ta, tb)
                    raw_after_drag = stored_value()
                    self.assertGreater(raw_after_drag, 0.0)
                    aux = plot._cursor_auxiliary_point()
                    self.assertIsNotNone(aux)
                    assert aux is not None
                    self.assertEqual(aux[0], "MATH9")
                    math_peak_kw = abs(float(aux[2])) / 1000.0
                    self.assertAlmostEqual(
                        math_peak_kw / raw_after_drag,
                        0.8,
                        delta=0.02,
                    )

                    win._on_value_clicked(*switch_to)
                    win._on_value_clicked(section, metric)
                    self.assertAlmostEqual(stored_value(), raw_after_drag, places=9)
                    self.assertEqual(plot._horizontal_cursor_binding("ha"), ("MATH9", True))
                    self.assertIn("卡值按原始 V×I", win.statusBar().currentMessage())
        finally:
            win.close()

    @unittest.skipUnless(
        SONG_SMC_HT_20260717_UH_1048.exists(), "20260717 UH 1048A sample missing"
    )
    def test_non_slope_cards_clear_stale_slope_reactivation_before_recalculate(self):
        """Pmax/Irr/Trr must not jump back to an earlier RR di/dt card."""
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win._load_file(str(SONG_SMC_HT_20260717_UH_1048))
            for section, metric, expected_mode in (
                ("关断过程", "Pmax", "power_peak"),
                ("反向恢复", "Irr", "irr_peak"),
                ("反向恢复", "Trr", "trr_measure"),
            ):
                with self.subTest(section=section, metric=metric):
                    win._on_value_clicked("反向恢复", "di/dt")
                    self.assertEqual(
                        win._active_slope_param,
                        ("反向恢复", "di/dt"),
                    )
                    win._on_value_clicked(section, metric)
                    self.assertIsNone(win._active_slope_param)
                    self.assertEqual(win.wave_plot._interactive_mode, expected_mode)

                    win._recalculate()
                    self.assertNotEqual(win.wave_plot._interactive_mode, "didt")
                    self.assertIsNone(win._active_slope_param)

            win._on_value_clicked("反向恢复", "di/dt")
            win.result.unavailable_metrics.add(("开通", "串扰电压"))
            win._on_value_clicked("开通", "串扰电压")
            self.assertIsNone(win._active_slope_param)
            self.assertNotEqual(win.wave_plot._interactive_mode, "didt")
            win._recalculate()
            self.assertIsNone(win._active_slope_param)
            self.assertNotEqual(win.wave_plot._interactive_mode, "didt")
        finally:
            win.close()

    @unittest.skipUnless(OTHER_360A.exists(), "360A unavailable-card sample missing")
    def test_recalculate_restores_unavailable_active_card_empty_cursor_context(self):
        """An unavailable selected row must not regain global MATH cursors."""
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win._load_file(str(OTHER_360A))
            plot = win.wave_plot
            key = ("关断过程", "串扰电压")
            self.assertTrue(win.result.is_metric_unavailable(*key))

            # Enter a real slope first to prove its state and bindings cannot
            # leak through the unavailable card or the subsequent replot.
            win._on_value_clicked("关断过程", "di/dt")
            self.assertEqual(plot._interactive_mode, "didt")
            win._on_value_clicked(*key)
            self.assertEqual(plot._interactive_mode, "unavailable")
            self.assertIsNone(win._active_slope_param)

            win._recalculate()

            self.assertTrue(win.result.is_metric_unavailable(*key))
            self.assertEqual(win.result_table._active_metric, key)
            self.assertEqual(plot._interactive_mode, "unavailable")
            self.assertIsNone(plot._cursor_endpoint_channel("a"))
            self.assertIsNone(plot._cursor_endpoint_channel("b"))
            self.assertEqual(plot._horizontal_cursor_binding("ha"), ("", False))
            self.assertEqual(plot._horizontal_cursor_binding("hb"), ("", False))
            self.assertFalse(plot._cursor_a.isVisible())
            self.assertFalse(plot._cursor_b.isVisible())
            self.assertFalse(plot._h_cursor_a.isVisible())
            self.assertFalse(plot._h_cursor_b.isVisible())
            self.assertEqual(plot._readout_label.text(), "")
        finally:
            win.close()

    @unittest.skipUnless(
        SONG_SMC_HT_20260717_UH_1048.exists(), "20260717 UH 1048A sample missing"
    )
    def test_recalculate_restores_valid_non_slope_card_cursor_semantics(self):
        """The selected card must still own A/B/Ha/Hb after a replot."""
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.waveform_plot import _is_power_unit

        win = MainWindow()
        try:
            win._load_file(str(SONG_SMC_HT_20260717_UH_1048))
            plot = win.wave_plot

            def snapshot() -> dict[str, object]:
                horizontal: dict[str, tuple[tuple[str, bool], bool, float | None]] = {}
                for which, cursor in (
                    ("ha", plot._h_cursor_a),
                    ("hb", plot._h_cursor_b),
                ):
                    binding = plot._horizontal_cursor_binding(which)
                    raw_value = (
                        float(plot._from_disp(binding[0], float(cursor.value())))
                        if binding[1]
                        else None
                    )
                    horizontal[which] = (
                        binding,
                        bool(cursor.isVisible()),
                        raw_value,
                    )
                return {
                    "mode": plot._interactive_mode,
                    "a": (
                        plot._cursor_endpoint_channel("a"),
                        bool(plot._cursor_a.isVisible()),
                        float(plot._cursor_a.value()),
                    ),
                    "b": (
                        plot._cursor_endpoint_channel("b"),
                        bool(plot._cursor_b.isVisible()),
                        float(plot._cursor_b.value()),
                    ),
                    "horizontal": horizontal,
                    "readout": plot._readout_label.text(),
                }

            def assert_snapshot_equal(
                before: dict[str, object], after: dict[str, object]
            ) -> None:
                self.assertEqual(after["mode"], before["mode"])
                self.assertEqual(after["readout"], before["readout"])
                for key in ("a", "b"):
                    expected = before[key]
                    actual = after[key]
                    self.assertEqual(actual[:2], expected[:2])
                    self.assertAlmostEqual(actual[2], expected[2], places=9)
                expected_h = before["horizontal"]
                actual_h = after["horizontal"]
                for which in ("ha", "hb"):
                    self.assertEqual(actual_h[which][:2], expected_h[which][:2])
                    expected_value = expected_h[which][2]
                    actual_value = actual_h[which][2]
                    if expected_value is None:
                        self.assertIsNone(actual_value)
                    else:
                        self.assertAlmostEqual(actual_value, expected_value, places=9)

            cases = (
                (
                    ("反向恢复", "Irr"),
                    "irr_peak",
                    ("irr", "irr"),
                    (("CH3", False), ("irr", True)),
                ),
                (
                    ("反向恢复", "Trr"),
                    "trr_measure",
                    ("irr", "irr"),
                    (("irr", True), ("irr", True)),
                ),
                (
                    ("开通", "Eon"),
                    "energy_loss",
                    ("ic", "vce"),
                    (("ic", True), ("vce", True)),
                ),
                (
                    ("开通", "Vce_on_max"),
                    "interval",
                    ("vge", "vce"),
                    (("vce", True), ("vce", True)),
                ),
            )
            for key, mode, endpoints, horizontal_bindings in cases:
                with self.subTest(section=key[0], metric=key[1]):
                    win._on_value_clicked(*key)
                    before = snapshot()
                    self.assertEqual(before["mode"], mode)
                    self.assertEqual(
                        (before["a"][0], before["b"][0]), endpoints
                    )
                    self.assertEqual(
                        (
                            before["horizontal"]["ha"][0],
                            before["horizontal"]["hb"][0],
                        ),
                        horizontal_bindings,
                    )
                    self.assertTrue(before["readout"])

                    win._recalculate()

                    self.assertEqual(win.result_table._active_metric, key)
                    self.assertIsNone(win._active_slope_param)
                    assert_snapshot_equal(before, snapshot())

            # This target has no verified visible W/kW trace for turn-off
            # power.  Pmax therefore binds A/B to its raw Vce/Ic loss
            # boundaries and must not show unrelated horizontal lines.
            key = ("关断过程", "Pmax")
            win._on_value_clicked(*key)
            before = snapshot()
            self.assertEqual(before["mode"], "power_peak")
            a_channel, b_channel = before["a"][0], before["b"][0]
            ha_binding = before["horizontal"]["ha"][0]
            hb_binding = before["horizontal"]["hb"][0]
            self.assertEqual((a_channel, b_channel), ("vce", "ic"))
            self.assertFalse(ha_binding[1])
            self.assertFalse(hb_binding[1])
            self.assertFalse(plot._h_cursor_a.isVisible())
            self.assertFalse(plot._h_cursor_b.isVisible())
            self.assertFalse(_is_power_unit(plot._unit_for_channel(a_channel)))
            self.assertTrue(before["readout"])

            win._recalculate()

            self.assertEqual(win.result_table._active_metric, key)
            self.assertIsNone(win._active_slope_param)
            assert_snapshot_equal(before, snapshot())
        finally:
            win.close()

    def test_pmax_without_a_visible_power_trace_has_no_horizontal_lines(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.waveform_plot import _is_power_unit
        from dpt_extractor.metrics.energy import peak_power_kw
        from dpt_extractor.metrics.iec_windows import IntegrationWindow
        from dpt_extractor.models.waveform import bundle_total_current

        win = MainWindow()
        try:
            win._load_file(str(WH))
            plot = win.wave_plot
            for key, item in plot._trace_items.items():
                if _is_power_unit(plot._unit_for_channel(key)):
                    plot._hidden_channels.add(key)
                    item.hide()

            win._on_value_clicked("关断过程", "Pmax")
            self.assertEqual(plot._interactive_mode, "power_peak")
            self.assertFalse(plot._horizontal_cursor_binding("ha")[1])
            self.assertFalse(plot._horizontal_cursor_binding("hb")[1])
            self.assertFalse(plot._h_cursor_a.isVisible())
            self.assertFalse(plot._h_cursor_b.isVisible())
            self.assertEqual(plot._cursor_endpoint_channel("a"), "vce")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "ic")

            assert plot._cursor_a is not None and plot._cursor_b is not None
            ta = float(plot._cursor_a.value())
            tb = float(plot._cursor_b.value()) - 0.02
            plot._interactive_on_change(ta, tb)
            t = win.bundle.t
            i0 = int(np.searchsorted(t, min(ta, tb) * 1e-6, side="left"))
            i1 = int(np.searchsorted(t, max(ta, tb) * 1e-6, side="left"))
            expected = peak_power_kw(
                win.bundle.get(win.profile.vce),
                bundle_total_current(win.bundle, win.profile),
                IntegrationWindow(i0, i1, float(t[i0]), float(t[i1])),
            )
            self.assertAlmostEqual(win.result.turn_off.pmax, expected, places=9)
        finally:
            win.close()

    @unittest.skipUnless(
        SONG_SMC_HT_20260717_UH_1048.exists(), "20260717 UH 1048A sample missing"
    )
    def test_reverse_recovery_pdmax_displays_absolute_power_peak(self):
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.waveform_plot import _is_power_unit

        win = MainWindow()
        win._load_file(str(SONG_SMC_HT_20260717_UH_1048))
        self.assertIsNotNone(win.result)
        self.assertIsNotNone(win.result.segments)
        plot = win.wave_plot
        vd_key = plot._display_key_for_channel("v_diode")
        irr_key = plot._display_key_for_channel("irr")
        plot._set_math_formula("MATH9", f"-ABS({vd_key}) * ABS({irr_key})")
        self.assertEqual(plot._unit_for_channel("MATH9"), "W")
        for key in list(plot._trace_items):
            if key != "MATH9" and _is_power_unit(plot._unit_for_channel(key)):
                plot._hidden_channels.add(key)
        plot._hidden_channels.discard("MATH9")

        interval = win._parameter_interval_us("反向恢复", "Pdmax")
        self.assertIsNotNone(interval)
        assert interval is not None
        win._on_value_clicked("反向恢复", "Pdmax")

        self.assertEqual(plot._interactive_mode, "power_peak")
        self.assertTrue(plot._horizontal_cursor_binding("ha")[1])
        self.assertFalse(plot._horizontal_cursor_binding("hb")[1])
        self.assertTrue(plot._h_cursor_a.isVisible())
        self.assertFalse(plot._h_cursor_b.isVisible())
        aux_point = plot._cursor_auxiliary_point()
        self.assertIsNotNone(aux_point)
        assert aux_point is not None
        channel, peak_t_us, peak_value = aux_point
        self.assertEqual(channel, "MATH9")
        self.assertGreaterEqual(peak_t_us, min(interval))
        self.assertLessEqual(peak_t_us, max(interval))
        self.assertGreater(peak_value, 0.0)
        self.assertIsNotNone(plot._h_cursor_a)
        assert plot._h_cursor_a is not None
        ha_value = plot._from_disp(channel, float(plot._h_cursor_a.value()))
        self.assertGreater(ha_value, 0.0)
        self.assertAlmostEqual(
            ha_value,
            peak_value,
            delta=max(abs(peak_value) * 1e-9, 1e-6),
        )
        self.assertGreater(win.result.reverse_recovery.pdmax, 0.0)
        self.assertAlmostEqual(
            win.result.reverse_recovery.pdmax,
            peak_value / 1000.0,
            delta=max(abs(peak_value) / 1000.0 * 1e-9, 1e-6),
        )
        win.close()

    @unittest.skipUnless(
        SONG_SMC_HT_20260717_UH_1048.exists(), "20260717 UH 1048A sample missing"
    )
    def test_reverse_recovery_pdmax_without_power_trace_uses_raw_vd_irr(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.waveform_plot import _is_power_unit
        from dpt_extractor.metrics.energy import peak_power_kw
        from dpt_extractor.metrics.iec_windows import IntegrationWindow
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        win = MainWindow()
        try:
            win._load_file(str(SONG_SMC_HT_20260717_UH_1048))
            plot = win.wave_plot
            for key, item in plot._trace_items.items():
                if _is_power_unit(plot._unit_for_channel(key)):
                    plot._hidden_channels.add(key)
                    item.hide()

            win._on_value_clicked("反向恢复", "Pdmax")
            self.assertEqual(plot._cursor_endpoint_channel("a"), "v_diode")
            self.assertEqual(plot._cursor_endpoint_channel("b"), "irr")
            self.assertFalse(plot._horizontal_cursor_binding("ha")[1])
            self.assertFalse(plot._horizontal_cursor_binding("hb")[1])
            assert plot._cursor_a is not None and plot._cursor_b is not None
            ta = float(plot._cursor_a.value())
            tb = float(plot._cursor_b.value()) - 0.02
            plot._interactive_on_change(ta, tb)

            t = win.bundle.t
            i0 = int(np.searchsorted(t, min(ta, tb) * 1e-6, side="left"))
            i1 = int(np.searchsorted(t, max(ta, tb) * 1e-6, side="left"))
            expected = peak_power_kw(
                win.bundle.get(win.profile.v_diode),
                bundle_reverse_recovery_current(win.bundle, win.profile),
                IntegrationWindow(i0, i1, float(t[i0]), float(t[i1])),
                absolute=True,
            )
            self.assertAlmostEqual(
                win.result.reverse_recovery.pdmax, expected, places=9
            )
        finally:
            win.close()

    def test_uh_eoff_cursor_uses_main_rise_not_pulse_off(self):
        """Eoff 进入时 A 应在主 Vce 抬升沿，而非关断沿或导通态噪声。"""
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win._load_file(str(UH))
        self.assertIsNotNone(win.result)
        win._manual_energy[("关断过程", "Eoff")] = (
            14.375,
            14.801,
            11.0,
            42.0,
        )
        win._on_value_clicked("关断过程", "Eoff")
        plot = win.wave_plot
        ta = float(plot._cursor_a.value())
        tb = float(plot._cursor_b.value())
        self.assertGreater(ta, 14.525, f"A too early/noise: {ta}")
        self.assertLess(ta, 14.56, f"A too late/pulse_off: {ta}")
        self.assertGreater(tb, 14.77)
        self.assertLess(tb, 15.00)
        a_samples = plot._energy_cursor_samples(ta)
        b_samples = plot._energy_cursor_samples(tb)
        self.assertEqual([s[0] for s in a_samples], ["vce", "ic"])
        self.assertEqual([s[0] for s in b_samples], ["vce", "ic"])
        ha_v = plot._from_disp("vce", float(plot._h_cursor_a.value()))
        vce = win.bundle.get(win.profile.vce)
        vce_at_a = float(np.interp(ta * 1e-6, win.bundle.t, vce))
        self.assertAlmostEqual(vce_at_a, ha_v, delta=0.5)
        marker_x, marker_y = plot._cursor_a_wave_marker.getData()
        self.assertEqual(len(marker_x), 1)
        self.assertEqual(len(marker_y), 1)
        self.assertAlmostEqual(float(marker_x[0]), ta, places=6)
        self.assertAlmostEqual(
            plot._from_disp("vce", float(marker_y[0])),
            ha_v,
            delta=0.5,
        )
        marker_x, marker_y = plot._cursor_b_wave_marker.getData()
        self.assertEqual(len(marker_x), 1)
        self.assertEqual(len(marker_y), 1)
        self.assertAlmostEqual(float(marker_x[0]), tb, places=6)
        hb_a = plot._from_disp("ic", float(plot._h_cursor_b.value()))
        self.assertAlmostEqual(
            plot._from_disp("ic", float(marker_y[0])),
            hb_a,
            delta=0.5,
        )
        readout = plot._readout_label.text()
        self.assertIn("A[", readout)
        self.assertIn("B[", readout)
        self.assertIn("Vce", readout)
        self.assertIn("Ic", readout)
        win.close()

    def test_trr_cursor_shows_irr_ha_intersection_markers(self):
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win._load_file(str(UH))
        self.assertIsNotNone(win.result)
        win._on_value_clicked("反向恢复", "Trr")
        plot = win.wave_plot
        self.assertEqual(plot._interactive_mode, "trr_measure")
        self.assertIsNotNone(plot._cursor_a_wave_marker)
        self.assertIsNotNone(plot._cursor_b_wave_marker)
        self.assertTrue(plot._cursor_a_wave_marker.isVisible())
        self.assertTrue(plot._cursor_b_wave_marker.isVisible())

        ha = plot._from_disp("irr", float(plot._h_cursor_a.value()))
        ta = float(plot._cursor_a.value())
        tb = float(plot._cursor_b.value())
        self.assertAlmostEqual(
            win.result.reverse_recovery.trr,
            abs(tb - ta) * 1e3,
            delta=0.001,
        )
        for marker, cursor in (
            (plot._cursor_a_wave_marker, plot._cursor_a),
            (plot._cursor_b_wave_marker, plot._cursor_b),
        ):
            marker_x, marker_y = marker.getData()
            self.assertEqual(len(marker_x), 1)
            self.assertEqual(len(marker_y), 1)
            self.assertAlmostEqual(float(marker_x[0]), float(cursor.value()), places=6)
            self.assertAlmostEqual(
                plot._from_disp("irr", float(marker_y[0])),
                ha,
                delta=0.5,
            )
        win.close()

    @unittest.skipUnless(WANGLIHUI_UL_486_985.exists(), "wanglihui UL sample missing")
    def test_derived_irr_trr_cursor_card_uses_internal_current_trace(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        win = MainWindow()
        win._load_file(str(WANGLIHUI_UL_486_985))
        self.assertTrue(win.profile.irr_from_ic_minus_il)

        plot = win.wave_plot
        plot._on_legend_double_clicked("CH1")
        self.assertEqual(plot._highlighted_key, "CH1")

        win._on_value_clicked("反向恢复", "Trr")
        logical_irr = plot._display_key_for_channel("irr")
        self.assertEqual(logical_irr, "LOGIC_IRR")
        self.assertIn(logical_irr, plot._trace_raw)
        self.assertNotIn(logical_irr, plot._trace_items)
        self.assertAlmostEqual(win.result.reverse_recovery.trr, 287.322921, delta=0.01)

        def assert_bound_to_logical_irr() -> None:
            self.assertEqual(plot._active_channel, "irr")
            self.assertEqual(plot._cursor_source_channel(), logical_irr)
            self.assertEqual(plot._axis_channel(), logical_irr)
            readout = plot._cursor_a_t_label.textItem.toPlainText()
            self.assertIn("Irr", readout)
            self.assertIn("A", readout)
            self.assertNotIn("VGE", readout.upper())
            top_readout = plot._readout_label.text()
            self.assertIn("Irr", top_readout)
            self.assertIn("A", top_readout)
            self.assertNotIn("VGE", top_readout.upper())

        # A pre-existing visible-channel highlight must not steal the Trr axis.
        self.assertEqual(plot._highlighted_key, "CH1")
        assert_bound_to_logical_irr()

        # In-mode single/double clicks may still raise/highlight CH1 visually,
        # but LOGIC_IRR has no selectable channel box and must remain bound.
        plot._on_legend_clicked("CH1")
        self.assertEqual(plot._raised_key, "CH1")
        assert_bound_to_logical_irr()
        plot._on_legend_double_clicked("CH1")
        self.assertEqual(plot._highlighted_key, "CH1")
        assert_bound_to_logical_irr()

        irr = bundle_reverse_recovery_current(win.bundle, win.profile)
        for marker, cursor in (
            (plot._cursor_a_wave_marker, plot._cursor_a),
            (plot._cursor_b_wave_marker, plot._cursor_b),
        ):
            marker_x, marker_y = marker.getData()
            self.assertEqual(len(marker_x), 1)
            self.assertEqual(len(marker_y), 1)
            t_us = float(cursor.value())
            self.assertAlmostEqual(float(marker_x[0]), t_us, places=6)
            expected = float(np.interp(t_us * 1e-6, win.bundle.t, irr))
            actual = plot._from_disp("irr", float(marker_y[0]))
            self.assertAlmostEqual(actual, expected, delta=0.75)

        # Leaving Trr must bind Toff's two physical endpoints explicitly:
        # A=Vge and B=Ic.  Channel clicks remain visual inspection gestures and
        # cannot turn either endpoint into an unrelated CH trace.
        win._on_value_clicked("关断过程", "Toff")
        self.assertEqual(plot._interactive_mode, "semantic_interval")
        self.assertEqual(plot._active_channel, "ic")
        self.assertIsNone(plot._raw_only_logical_readout_channel())
        self.assertEqual(plot._cursor_endpoint_channel("a"), "vge")
        self.assertEqual(plot._cursor_endpoint_channel("b"), "ic")
        plot._on_legend_clicked("CH2")
        self.assertEqual(plot._raised_key, "CH2")
        self.assertEqual(plot._active_channel, "ic")
        self.assertEqual(plot._cursor_endpoint_channel("a"), "vge")
        self.assertEqual(plot._cursor_endpoint_channel("b"), "ic")
        win.close()

    def test_smc_rt_eoff_ha_intersects_vce_a_cursor(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow

        if not SMC_RT_UH.exists():
            self.skipTest("SMC RT UH sample missing")
        win = MainWindow()
        win._load_file(str(SMC_RT_UH))
        self.assertIsNotNone(win.result)
        win._on_value_clicked("关断过程", "Eoff")
        plot = win.wave_plot
        ta = float(plot._cursor_a.value())
        tb = float(plot._cursor_b.value())
        ha_v = plot._from_disp("vce", float(plot._h_cursor_a.value()))
        hb_a = plot._from_disp("ic", float(plot._h_cursor_b.value()))
        vce = win.bundle.get(win.profile.vce)
        from dpt_extractor.models.waveform import bundle_total_current

        ic = bundle_total_current(win.bundle, win.profile)
        self.assertAlmostEqual(
            float(np.interp(ta * 1e-6, win.bundle.t, vce)), ha_v, delta=0.5
        )
        self.assertAlmostEqual(
            float(np.interp(tb * 1e-6, win.bundle.t, ic)), hb_a, delta=0.5
        )
        self.assertGreater(ta, 14.68)
        self.assertLess(ta, 14.74)
        self.assertAlmostEqual(ha_v, 12.34375, delta=0.5)
        win.close()

    @unittest.skipUnless(WANGLIHUI_UH_400_1070.exists(), "wanglihui UH sample missing")
    def test_wanglihui_upper_inverted_irr_eoff_cursor_uses_logical_ic(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.waveform import (
            bundle_reverse_recovery_current,
            bundle_total_current,
        )

        win = MainWindow()
        win._load_file(str(WANGLIHUI_UH_400_1070))
        self.assertIsNotNone(win.result)

        win.wave_plot.set_channel_inversion_enabled("CH3", True)
        plot = win.wave_plot
        self.assertEqual(plot._display_key_for_channel("ic"), "MATH1")
        np.testing.assert_allclose(
            np.asarray(plot._interactive_ic, dtype=float),
            bundle_total_current(win.bundle, win.profile),
        )
        np.testing.assert_allclose(
            np.asarray(plot._interactive_irr, dtype=float),
            bundle_reverse_recovery_current(win.bundle, win.profile),
        )

        win._on_value_clicked("关断过程", "Eoff")
        plot = win.wave_plot
        tb = float(plot._cursor_b.value())
        hb = plot._from_disp("ic", float(plot._h_cursor_b.value()))
        logic_ic = bundle_total_current(win.bundle, win.profile)
        logic_at_b = float(np.interp(tb * 1e-6, win.bundle.t, logic_ic))
        math_sample = plot._sample_cursor_channel("MATH1", tb)
        self.assertIsNotNone(math_sample)
        assert math_sample is not None
        self.assertAlmostEqual(hb, logic_at_b, delta=0.5)
        self.assertAlmostEqual(math_sample[0], hb, delta=0.5)
        marker_x, marker_y = plot._cursor_b_wave_marker.getData()
        self.assertEqual(len(marker_x), 1)
        self.assertAlmostEqual(float(marker_x[0]), tb, places=6)
        self.assertAlmostEqual(
            plot._from_disp("ic", float(marker_y[0])),
            hb,
            delta=0.5,
        )
        win.close()

    @unittest.skipUnless(WANGLIHUI_UH_400_1070.exists(), "wanglihui UH sample missing")
    def test_wanglihui_upper_inverted_irr_err_cursor_uses_true_intersections(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        win = MainWindow()
        win._load_file(str(WANGLIHUI_UH_400_1070))
        self.assertIsNotNone(win.result)

        win.wave_plot.set_channel_inversion_enabled("CH3", True)
        win._on_value_clicked("反向恢复", "Err")
        plot = win.wave_plot
        ta_us = float(plot._cursor_a.value())
        tb_us = float(plot._cursor_b.value())
        ha = plot._from_disp("irr", float(plot._h_cursor_a.value()))
        hb = plot._from_disp("v_diode", float(plot._h_cursor_b.value()))
        irr = bundle_reverse_recovery_current(win.bundle, win.profile)
        vd = win.bundle.get(win.profile.v_diode)

        self.assertAlmostEqual(
            float(np.interp(ta_us * 1e-6, win.bundle.t, irr)),
            ha,
            delta=0.75,
        )
        self.assertAlmostEqual(
            float(np.interp(tb_us * 1e-6, win.bundle.t, vd)),
            hb,
            delta=0.02,
        )
        self.assertAlmostEqual(ta_us, 36.449, delta=0.025)
        self.assertAlmostEqual(tb_us, 35.935, delta=0.025)
        marker_x, marker_y = plot._cursor_a_wave_marker.getData()
        self.assertEqual(len(marker_x), 1)
        self.assertAlmostEqual(float(marker_x[0]), ta_us, places=6)
        self.assertAlmostEqual(
            plot._from_disp("irr", float(marker_y[0])),
            ha,
            delta=0.75,
        )
        win.close()

    @unittest.skipUnless(WANGLIHUI_UL_400_1070.exists(), "wanglihui UL sample missing")
    def test_wanglihui_lower_err_cursor_uses_stable_gate_not_tail(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        win = MainWindow()
        win._load_file(str(WANGLIHUI_UL_400_1070))
        self.assertIsNotNone(win.result)
        self.assertTrue(win.profile.irr_from_ic_minus_il)

        win._on_value_clicked("反向恢复", "Err")
        plot = win.wave_plot
        ta_us = float(plot._cursor_a.value())
        tb_us = float(plot._cursor_b.value())
        ha = plot._from_disp("irr", float(plot._h_cursor_a.value()))
        hb = plot._from_disp("v_diode", float(plot._h_cursor_b.value()))
        irr = bundle_reverse_recovery_current(win.bundle, win.profile)
        vd = win.bundle.get(win.profile.v_diode)

        self.assertAlmostEqual(
            float(np.interp(ta_us * 1e-6, win.bundle.t, irr)),
            ha,
            delta=0.75,
        )
        self.assertAlmostEqual(
            float(np.interp(tb_us * 1e-6, win.bundle.t, vd)),
            hb,
            delta=0.03,
        )
        self.assertAlmostEqual(ta_us, 36.977, delta=0.025)
        self.assertAlmostEqual(tb_us, 36.640, delta=0.025)
        self.assertGreater(tb_us, 36.60)
        self.assertLess(ta_us, 37.2)
        plot._sync_energy_b_from_hb(ta_us)
        self.assertAlmostEqual(float(plot._cursor_b.value()), 36.640, delta=0.025)

        marker_x, marker_y = plot._cursor_a_wave_marker.getData()
        self.assertEqual(len(marker_x), 1)
        self.assertAlmostEqual(float(marker_x[0]), ta_us, places=6)
        self.assertAlmostEqual(
            plot._from_disp("irr", float(marker_y[0])),
            ha,
            delta=0.75,
        )
        win.close()

    def test_smc_rt_ul_806_eoff_a_uses_main_rise_ha_crossing(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow

        if not SMC_RT_UL_806.exists():
            self.skipTest("SMC RT UL 806A sample missing")
        win = MainWindow()
        win._load_file(str(SMC_RT_UL_806))
        self.assertIsNotNone(win.result)
        win._on_value_clicked("关断过程", "Eoff")
        plot = win.wave_plot
        ta = float(plot._cursor_a.value())
        tb = float(plot._cursor_b.value())
        ha_v = plot._from_disp("vce", float(plot._h_cursor_a.value()))
        vce = win.bundle.get(win.profile.vce)
        self.assertAlmostEqual(
            float(np.interp(ta * 1e-6, win.bundle.t, vce)), ha_v, delta=0.5
        )
        self.assertGreater(ta, 11.55)
        self.assertLess(ta, 11.59)
        self.assertGreater(tb, ta + 0.20)
        win.close()

    def test_smc_rt_irr_hb_tracks_parameter_spike_not_abs_prespike(self):
        from dpt_extractor.gui.main_window import MainWindow

        for path, expected in ((SMC_RT_UH, 170.4375), (SMC_RT_UL, 127.03125)):
            if not path.exists():
                self.skipTest(f"{path.name} sample missing")
            win = MainWindow()
            win._load_file(str(path))
            self.assertIsNotNone(win.result)
            win._on_value_clicked("反向恢复", "Irr")
            plot = win.wave_plot
            hb_irr = plot._from_disp("irr", float(plot._h_cursor_b.value()))
            self.assertAlmostEqual(hb_irr, expected, delta=0.5)
            self.assertAlmostEqual(win.result.reverse_recovery.irr, expected, delta=0.5)
            win.close()


if __name__ == "__main__":
    unittest.main()
