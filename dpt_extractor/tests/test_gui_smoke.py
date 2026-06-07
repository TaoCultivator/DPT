"""GUI 启动+光标交互的轻量自检（无界面，使用 offscreen Qt）。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
WH = ROOT / "WH_480V_800A_000_ALL.csv"
UH = ROOT / "UH_750V_1050A_000_ALL.csv"


class TestWaveformImportAutoCenter(unittest.TestCase):
    """导入时 (min+max)/2 对齐 0 格；不依赖 WH/UH 样例文件。"""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_tss_scope_ypos_does_not_override_auto_center(self):
        """TSS 中的示波器 yPosition 是零位偏移，不应替代 (min+max)/2 居中。"""
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
        for key in ("vge", "vce", "ic", "irr"):
            display_key = plot._display_key_for_channel(key)
            raw = plot._trace_raw[display_key]
            scale = plot._disp_scale[display_key]
            mid_raw = 0.5 * (float(np.min(raw)) + float(np.max(raw)))
            mid_disp = mid_raw / scale + plot._disp_offset[display_key]
            self.assertAlmostEqual(mid_disp, 0.0, places=2, msg=key)

    def _make_synthetic_plot(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
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
            meta=TekMetadata(source_path="/fake/synthetic.tss"),
        )
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, None)
        return plot

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

    def test_tss_derived_ic_max_cursor_uses_imported_math_trace(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 300
        t = np.linspace(0.0, 1e-6, n)
        profile = make_profile("U", "upper")
        irr = np.linspace(100.0, 700.0, n)
        il = np.linspace(20.0, 320.0, n)
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
        self.assertAlmostEqual(
            plot._from_disp("ic", float(plot._h_cursor_a.value())),
            peak,
            delta=1.0,
        )

    def test_math_channel_can_open_settings_for_mapping(self):
        from PyQt6.QtCore import QPoint

        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        plot = self._make_synthetic_plot()
        panel = ChannelSettingsPanel(plot, "MATH1", QPoint(0, 0), parent=plot)
        self.assertGreaterEqual(panel._mapping_combo.findData("ic"), 0)
        self.assertEqual(panel._mapping_combo.findData(""), 0)

    def test_parameter_max_default_intervals_use_algorithm_windows(self):
        import numpy as np

        os.environ["LOCALAPPDATA"] = str(ROOT / ".tmp" / "localappdata")

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import ExtractResult, SegmentIndices
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
            meta=TekMetadata(),
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
        win.result = ExtractResult(segments=segs)

        off_ic = win._parameter_max_interval_indices(off, "Ic_off_max")
        on_ic = win._parameter_max_interval_indices(on, "Ic_on_max")
        on_vce = win._parameter_max_interval_indices(on, "Vce_on_max")
        rr_irr = win._parameter_max_interval_indices(rr, "Irr")

        self.assertIsNotNone(off_ic)
        self.assertIsNotNone(on_ic)
        self.assertIsNotNone(on_vce)
        self.assertIsNotNone(rr_irr)
        assert off_ic is not None and on_ic is not None and on_vce is not None and rr_irr is not None

        self.assertLess(off_ic[1], segs.turn_off[1])
        self.assertGreater(on_ic[0], segs.turn_on[0])
        self.assertLess(on_vce[1], segs.turn_on[1])
        self.assertEqual(
            rr_irr,
            (max(segs.reverse_recovery[0], segs.pulse2_on), segs.turn_on[1] - 1),
        )

        for section, name, idx in (
            (off, "Ic_off_max", off_ic),
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
        self.assertLess(len(plot._trace_raw["MATH1"]), n)
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
        self.assertAlmostEqual(plot._disp_scale["MATH1"], 0.05)
        self.assertEqual(plot._unit_for_channel("MATH1"), "A")
        np.testing.assert_allclose(plot._trace_raw["MATH1"], original_math)

    def test_selected_channel_updates_physical_y_axis(self):
        plot = self._make_synthetic_plot()
        self.assertEqual(plot._axis_channel(), "CH3")
        plot._on_legend_clicked("CH5")
        self.assertEqual(plot._axis_channel(), "CH5")
        self.assertEqual(plot._axis_last_signature[0], "CH5")
        self.assertEqual(plot._format_axis_value(1200.0, "V"), "1.2 kV")

    def test_y_axis_ticks_anchor_to_channel_zero_and_vdiv(self):
        plot = self._make_synthetic_plot()
        plot._on_legend_clicked("CH6")
        tick_text = [
            text
            for level in plot.plot.getPlotItem().getAxis("left")._tickLevels
            for _, text in level
        ]
        for expected in ("0 V", "5 V", "10 V", "15 V", "20 V"):
            self.assertIn(expected, tick_text)

    def test_selection_zoom_applies_local_x_and_y_range(self):
        from PyQt6.QtCore import QPointF

        plot = self._make_synthetic_plot()
        vb = plot.plot.getPlotItem().getViewBox()
        p0 = vb.mapViewToScene(QPointF(0.20, -2.0))
        p1 = vb.mapViewToScene(QPointF(0.70, 2.0))
        plot._apply_selection_zoom(p0, p1)
        xr, yr = vb.viewRange()
        self.assertAlmostEqual(xr[0], 0.20, places=2)
        self.assertAlmostEqual(xr[1], 0.70, places=2)
        self.assertAlmostEqual(yr[0], -2.0, places=2)
        self.assertAlmostEqual(yr[1], 2.0, places=2)

    def test_selection_zoom_requires_one_shot_button(self):
        plot = self._make_synthetic_plot()
        self.assertFalse(plot._selection_zoom_enabled)
        self.assertFalse(plot._zoom_select_btn.isChecked())

        plot._zoom_select_btn.setChecked(True)
        self.assertTrue(plot._selection_zoom_enabled)
        plot._finish_selection_zoom_mode()
        self.assertFalse(plot._selection_zoom_enabled)
        self.assertFalse(plot._zoom_select_btn.isChecked())

        plot._arm_selection_zoom()
        self.assertTrue(plot._selection_zoom_enabled)
        self.assertTrue(plot._zoom_select_btn.isChecked())
        plot._finish_selection_zoom_mode()
        self.assertFalse(plot._selection_zoom_enabled)

    def test_drag_wrapper_keeps_original_viewbox_handler(self):
        plot = self._make_synthetic_plot()
        vb = plot.plot.getPlotItem().getViewBox()
        closure_types = [
            type(cell.cell_contents).__name__
            for cell in (vb.mouseDragEvent.__closure__ or [])
        ]
        self.assertIn("method", closure_types)
        self.assertNotIn("function", closure_types)

    def test_context_menu_group_selection(self):
        plot = self._make_synthetic_plot()
        self.assertEqual(plot.context_menu_group(), "cursor")
        plot.set_context_menu_group("zoom")
        self.assertEqual(plot.context_menu_group(), "zoom")
        plot.set_context_menu_group("view")
        self.assertEqual(plot.context_menu_group(), "view")
        plot.set_context_menu_group("bad-value")
        self.assertEqual(plot.context_menu_group(), "cursor")


@unittest.skipUnless(WH.exists() and UH.exists(), "WH/UH sample missing")
class TestWaveformPlotSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _load_and_plot(self, csv_path: Path):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.io.tek_parser import TekParser
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.pipeline.extract import extract_all

        cfg = load_config()
        bundle = TekParser().parse(csv_path)
        profile = guess_profile_from_path(csv_path.name)
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
        # 顶部信息栏文字（不在波形上）
        self.assertNotEqual(plot._readout_label.text(), "")
        # 底部通道盒含全部 6 条逻辑通道，并可附加原始 Math
        self.assertGreaterEqual(len(plot._channel_boxes), 6)
        self.assertIn("vge", plot._channel_boxes)
        self.assertIn("vge_other", plot._channel_boxes)

    def test_per_channel_scale_setting(self):
        plot, bundle, profile, _ = self._load_and_plot(WH)
        # 手动设置 Vge 为 2 V/格
        plot._set_channel_scale("vge", 2.0)
        self.assertEqual(plot._disp_scale["vge"], 2.0)
        self.assertEqual(plot._manual_vdiv["vge"], 2.0)
        # 显示数据应按新刻度缩放（含该通道默认垂直位置偏移）
        import numpy as np

        raw = plot._trace_raw["vge"]
        offset = plot._disp_offset["vge"]
        ydisp = plot._trace_items["vge"].getData()[1]
        self.assertTrue(np.allclose(ydisp, raw / 2.0 + offset))
        # 恢复自动
        plot._set_channel_scale("vge", None)
        self.assertNotIn("vge", plot._manual_vdiv)

    def test_per_channel_vertical_position(self):
        import numpy as np

        plot, bundle, profile, _ = self._load_and_plot(WH)
        raw = plot._trace_raw["vce"]
        scale = plot._disp_scale["vce"]
        base = plot._disp_offset["vce"]  # 默认位置偏移
        # 滚轮上移 2 步 = +1.0 格（相对默认偏移）
        plot._on_channel_position_step("vce", 2)
        self.assertAlmostEqual(plot._disp_offset["vce"], base + 1.0, places=6)
        self.assertTrue(
            np.allclose(plot._trace_items["vce"].getData()[1], raw / scale + base + 1.0)
        )
        # 高亮出现接地标记
        plot._on_legend_clicked("vce")
        self.assertIsNotNone(plot._ground_marker)
        self.assertTrue(plot._ground_marker.isVisible())
        self.assertEqual(plot._ground_marker_key, "vce")
        # 拖动接地标记改位置
        plot._ground_marker.setValue(-1.5)
        self.assertAlmostEqual(plot._disp_offset["vce"], -1.5, places=6)
        self.assertTrue(
            np.allclose(plot._trace_items["vce"].getData()[1], raw / scale - 1.5)
        )
        # 取消高亮隐藏标记
        plot._on_legend_clicked("vce")
        self.assertFalse(plot._ground_marker.isVisible())

    def test_legend_click_highlight(self):
        plot, bundle, profile, _ = self._load_and_plot(WH)
        vb = plot.plot.getPlotItem().getViewBox()
        y_before = vb.viewRange()[1]
        # 点击 Vge：仅置顶 + 高亮，纵轴量程不变
        plot._on_legend_clicked("vge")
        self.assertEqual(plot._highlighted_key, "vge")
        self.assertEqual(plot._trace_items["vge"].zValue(), 20)
        # 其它波形被压到底层
        self.assertEqual(plot._trace_items["vce"].zValue(), 0)
        y_after = vb.viewRange()[1]
        self.assertAlmostEqual(y_before[0], y_after[0], places=3)
        self.assertAlmostEqual(y_before[1], y_after[1], places=3)
        # 再次点击恢复
        plot._on_legend_clicked("vge")
        self.assertIsNone(plot._highlighted_key)
        self.assertEqual(plot._trace_items["vge"].zValue(), 0)

    def test_channel_visibility_toggle(self):
        plot, _, _, _ = self._load_and_plot(WH)
        self.assertTrue(plot._trace_items["vce"].isVisible())
        plot._toggle_channel_visibility("vce")
        self.assertIn("vce", plot._hidden_channels)
        self.assertFalse(plot._trace_items["vce"].isVisible())
        plot._toggle_channel_visibility("vce")
        self.assertNotIn("vce", plot._hidden_channels)
        self.assertTrue(plot._trace_items["vce"].isVisible())

    def test_auto_center_on_import(self):
        import numpy as np

        plot, _, _, _ = self._load_and_plot(WH)
        for key in plot._trace_items:
            raw = plot._trace_raw[key]
            scale = plot._disp_scale[key]
            mid_raw = 0.5 * (float(np.nanmin(raw)) + float(np.nanmax(raw)))
            mid_disp = mid_raw / scale + plot._disp_offset[key]
            self.assertAlmostEqual(mid_disp, 0.0, places=2, msg=key)

    def test_auto_vdiv_ladder_and_margin(self):
        import numpy as np

        from dpt_extractor.gui.waveform_plot import (  # noqa: PLC0415
            CURRENT_VDIV_DEFAULT,
            CURRENT_VDIV_MAX,
            DISP_HALF_DIV,
            VDIV_LADDER,
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
        self.assertEqual(_auto_vdiv_for_channel("vce", raw), 200.0)
        self.assertEqual(_auto_vdiv_for_channel("vge", np.array([0.0, 15.0])), 5.0)
        self.assertEqual(_pick_vdiv_ladder(37.0, "vge"), 50.0)
        self.assertEqual(_pick_vdiv_ladder(250.0, "ic"), 250.0)
        self.assertEqual(_pick_vdiv_ladder(280.0, "ic"), 300.0)
        small_ic = np.array([0.0, 400.0])
        self.assertEqual(_auto_vdiv_for_channel("ic", small_ic), CURRENT_VDIV_DEFAULT)

        plot, _, _, _ = self._load_and_plot(WH)
        max_half = DISP_HALF_DIV * (1.0 - VERT_VIEW_MARGIN) + 0.05
        for key, scale in plot._disp_scale.items():
            self.assertIn(scale, [float(v) for v in VDIV_LADDER])
            if key in ("ic", "irr"):
                self.assertLessEqual(scale, CURRENT_VDIV_MAX)
                self.assertGreaterEqual(scale, 1.0)
            ymin, ymax = plot._trace_yrange[key]
            half_pp_div = (ymax - ymin) / (2.0 * scale)
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
        self.assertIn("vge", plot._disp_scale)
        self.assertIn("vce", plot._disp_scale)
        # Vge 刻度应远小于 Vce 刻度（5V/格 量级 vs 数百V/格）
        self.assertLess(plot._disp_scale["vge"], plot._disp_scale["vce"])
        from dpt_extractor.gui.waveform_plot import VERT_VIEW_MARGIN

        max_half = DISP_HALF_DIV * (1.0 - VERT_VIEW_MARGIN) + 0.05
        for key, (ymin, ymax) in plot._trace_yrange.items():
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
        self.assertTrue(plot._cursor_a.movable)
        self.assertTrue(plot._h_cursor_a.movable)
        ha_disp = float(plot._h_cursor_a.value())
        plot._h_cursor_a.setPos(ha_disp + 5.0)
        plot._on_horizontal_cursor_moved()
        self.assertNotEqual(float(result.turn_on.ls_on), ls_before)

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
        self.assertLess(top_a, -900.0)
        self.assertGreater(base_a, -100.0)
        self.assertLess(base_a, 150.0)
        res = win._compute_didt_base_top(
            "反向恢复", search_t0, search_t1, top_a, base_a
        )
        self.assertGreater(res.didt, 1.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)

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
        # 拖动 B
        plot._cursor_b.setValue(plot._cursor_b.value() + 0.5)
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
        from dpt_extractor.io.tek_parser import TekParser
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.pipeline.extract import extract_all

        bundle2 = TekParser().parse(UH)
        prof2 = guess_profile_from_path(UH.name)
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

    def test_uh_eoff_cursor_uses_main_rise_not_pulse_off(self):
        """Eoff 进入时 A 应在主 Vce 抬升沿（~14.61µs），而非关断沿或 14.37µs 噪声。"""
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
        self.assertGreater(ta, 14.495, f"A too early/noise: {ta}")
        self.assertLess(ta, 14.505, f"A too late/pulse_off: {ta}")
        self.assertGreater(tb, 14.77)
        self.assertLess(tb, 14.84)
        win.close()


if __name__ == "__main__":
    unittest.main()
