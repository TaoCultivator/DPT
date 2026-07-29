"""Logical measurement values must project onto the waveform users can see."""

from __future__ import annotations

import os
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
WANGLIHUI_UH = (
    ROOT
    / "示例文件"
    / "wanglihui"
    / "U"
    / "UH_486V_985A_Rgon2.88R_Rgoff6.21R_000.tss"
)
WANGLIHUI_UL = (
    ROOT
    / "示例文件"
    / "wanglihui"
    / "U"
    / "UL_486V_985A_Rgon1.1R_Rgof5R_000.tss"
)
SONGZHENXI_UH = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "HT"
    / "UH_750V_1048A_000.tss"
)


class TestLogicalDisplaySign(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_all_logical_roles_keep_unsigned_visible_keys_and_symmetric_conversion(self) -> None:
        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import BridgeProfile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        t = np.linspace(0.0, 2e-6, 2001)
        phase = np.linspace(0.0, 4.0 * np.pi, len(t))
        channels = {
            "CH1": 5.0 + np.sin(phase),
            "CH2": 600.0 + 20.0 * np.sin(phase + 0.1),
            # A negative source plus an explicit -CH3 reference is auto-oriented
            # to positive logical Ic and therefore remains opposite to CH3.
            "CH3": -200.0 - 30.0 * np.sin(phase + 0.2),
            "CH4": 100.0 + 10.0 * np.sin(phase + 0.3),
            "CH5": 150.0 + 30.0 * np.sin(phase + 0.4),
            "CH6": 450.0 + 15.0 * np.sin(phase + 0.5),
            "CH7": 8.0 + 2.0 * np.sin(phase + 0.6),
            "CH8": 12.0 + 1.0 * np.sin(phase + 0.7),
        }
        bundle = WaveformBundle(
            t=t,
            channels=channels,
            meta=TekMetadata(
                source_path="synthetic-logical-sign.tss",
                source_channel_inversions={"CH4"},
                channel_display_inversions={"CH5"},
            ),
        )
        profile = BridgeProfile(
            name="signed_roles",
            display_name="signed roles",
            phase="U",
            bridge="upper",
            code="UH",
            vge="-CH1",
            vce="CH2",
            ic="-CH3",
            il="CH4",
            irr="-CH5",
            v_diode="CH6",
            vge_other="-CH7",
            vdesat="CH8",
        )
        plot = WaveformPlot()
        try:
            plot.plot_waveforms(bundle, profile, None)
            expected_signs = {
                "vge": -1,
                "vce": 1,
                "ic": -1,
                "il": 1,
                # -CH5 and the visible CH5 are both inverted exactly once.
                "irr": 1,
                "v_diode": 1,
                "vge_other": -1,
                "vdesat": 1,
            }
            self.assertEqual(plot._logical_display_signs, expected_signs)
            self.assertNotIn("-CH1", plot._logical_display_keys.values())
            self.assertNotIn("-CH3", plot._logical_display_keys.values())
            self.assertNotIn("-CH5", plot._logical_display_keys.values())
            np.testing.assert_allclose(
                plot._effective_raw_for_channel("-CH5"),
                channels["CH5"],
            )

            index = 713
            for logical, expected_sign in expected_signs.items():
                display_key = plot._display_key_for_channel(logical)
                logical_value = float(plot._logical_role_raw[logical][index])
                visible_raw = plot._effective_raw_for_channel(display_key)
                self.assertIsNotNone(visible_raw, logical)
                assert visible_raw is not None
                visible_value = float(visible_raw[index])
                self.assertAlmostEqual(
                    visible_value,
                    expected_sign * logical_value,
                    places=9,
                    msg=logical,
                )
                logical_y = plot._to_disp(logical, logical_value)
                visible_y = plot._to_disp(display_key, visible_value)
                self.assertAlmostEqual(logical_y, visible_y, places=12, msg=logical)
                self.assertAlmostEqual(
                    plot._from_disp(logical, logical_y),
                    logical_value,
                    places=9,
                    msg=logical,
                )
                # Passing a physical source key must continue to mean the
                # value users see, without the logical role's sign applied.
                self.assertAlmostEqual(
                    plot._from_disp(display_key, visible_y),
                    visible_value,
                    places=9,
                    msg=display_key,
                )
        finally:
            plot.close()

    def test_stale_derived_math_formula_fails_closed_to_logical_irr(self) -> None:
        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import BridgeProfile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        t = np.linspace(0.0, 4e-6, 4001)
        phase = np.linspace(0.0, 3.0 * np.pi, len(t))
        ic = 420.0 + 35.0 * np.sin(phase)
        il = 390.0 + 20.0 * np.sin(phase + 0.15)
        authoritative_irr = ic - il
        # The expression text is semantically plausible, but these saved Math
        # samples belong to a stale/scaled acquisition and must not become the
        # cursor source merely because the formula still says CH3-CH4.
        stale_math = -2.5 * authoritative_irr + 75.0
        bundle = WaveformBundle(
            t=t,
            channels={
                "CH1": 5.0 + np.sin(phase),
                "CH2": 600.0 + 10.0 * np.sin(phase),
                "CH3": ic,
                "CH4": il,
                "CH5": 400.0 + np.sin(phase),
                "CH6": 4.0 + np.sin(phase),
                "MATH1": stale_math,
            },
            meta=TekMetadata(
                source_path="synthetic-stale-derived-math.tss",
                channel_math_formulas={"MATH1": "CH3-CH4"},
            ),
        )
        profile = BridgeProfile(
            name="lower-derived-irr",
            display_name="lower derived Irr",
            phase="U",
            bridge="lower",
            code="UL",
            vge="CH6",
            vce="CH5",
            ic="CH3",
            il="CH4",
            irr="",
            v_diode="CH2",
            vge_other="CH1",
            irr_from_ic_minus_il=True,
        )

        plot = WaveformPlot()
        try:
            plot.plot_waveforms(bundle, profile, None)
            self.assertEqual(plot._display_key_for_channel("irr"), "LOGIC_IRR")
            self.assertIn("MATH1", plot._trace_items)
            self.assertIn("LOGIC_IRR", plot._trace_raw)
            self.assertNotIn("LOGIC_IRR", plot._trace_items)
            np.testing.assert_allclose(
                plot._trace_raw["LOGIC_IRR"],
                authoritative_irr,
            )
            np.testing.assert_allclose(
                plot._cursor_value_raw("irr"),
                authoritative_irr,
            )
        finally:
            plot.close()

    def test_stale_sum_math_formula_fails_closed_to_logical_ic(self) -> None:
        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.models.bridge_profile import BridgeProfile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        t = np.linspace(0.0, 4e-6, 4001)
        phase = np.linspace(0.0, 3.0 * np.pi, len(t))
        irr = -150.0 + 12.0 * np.sin(phase)
        il = 430.0 + 18.0 * np.sin(phase + 0.1)
        authoritative_ic = irr + il
        bundle = WaveformBundle(
            t=t,
            channels={
                "CH1": 5.0 + np.sin(phase),
                "CH2": 600.0 + np.sin(phase),
                "CH3": irr,
                "CH4": il,
                "CH5": 400.0 + np.sin(phase),
                "CH6": 4.0 + np.sin(phase),
                "MATH1": 0.1 * authoritative_ic - 90.0,
            },
            meta=TekMetadata(
                source_path="synthetic-stale-sum-math.tss",
                channel_math_formulas={"MATH1": "CH3+CH4"},
            ),
        )
        profile = BridgeProfile(
            name="upper-derived-ic",
            display_name="upper derived Ic",
            phase="U",
            bridge="upper",
            code="UH",
            vge="CH1",
            vce="CH2",
            ic="",
            il="CH4",
            irr="CH3",
            v_diode="CH5",
            vge_other="CH6",
            ic_from_sum_irr_il=True,
        )

        plot = WaveformPlot()
        try:
            plot.plot_waveforms(bundle, profile, None)
            self.assertEqual(plot._display_key_for_channel("ic"), "LOGIC_IC")
            self.assertIn("MATH1", plot._trace_items)
            self.assertIn("LOGIC_IC", plot._trace_raw)
            self.assertNotIn("LOGIC_IC", plot._trace_items)
            np.testing.assert_allclose(plot._trace_raw["LOGIC_IC"], authoritative_ic)
            np.testing.assert_allclose(plot._cursor_value_raw("ic"), authoritative_ic)
        finally:
            plot.close()

    @unittest.skipUnless(WANGLIHUI_UH.exists(), "wanglihui UH sample missing")
    def test_wanglihui_explicit_negative_irr_hb_tracks_visible_platform_and_report_replot(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win._load_file(str(WANGLIHUI_UH))
            win.profile = replace(win.profile, irr="-CH3")
            win._recalculate(reset_manual=True)
            self.assertIsNotNone(win.result)
            plot = win.wave_plot
            self.assertEqual(plot._display_key_for_channel("irr"), "CH3")
            self.assertEqual(plot._logical_display_signs["irr"], -1)

            interval = win._parameter_interval_us("反向恢复", "di/dt")
            self.assertIsNotNone(interval)
            assert interval is not None
            context = win._rr_didt_context(*interval)
            self.assertIsNotNone(context)
            assert context is not None
            win._on_value_clicked("反向恢复", "di/dt")
            self.assertIsNotNone(plot._h_cursor_b)
            assert plot._h_cursor_b is not None

            self.assertEqual(plot._horizontal_cursor_binding("ha"), ("irr", True))
            self.assertEqual(plot._horizontal_cursor_binding("hb"), ("irr", True))
            live = plot.read_didt_slope_state("irr")
            self.assertIsNotNone(live)
            assert live is not None
            self.assertAlmostEqual(live[0], context.base_a, places=9)
            self.assertAlmostEqual(live[1], context.forward_a, places=9)

            emitted: list[tuple[float, ...]] = []
            plot._interactive_on_change = lambda *values: emitted.append(values)
            plot._emit_dvdt_changed()
            self.assertEqual(len(emitted), 1)
            self.assertAlmostEqual(emitted[0][0], context.base_a, places=9)
            self.assertAlmostEqual(emitted[0][1], context.forward_a, places=9)

            logical_hb = plot._from_disp("irr", float(plot._h_cursor_b.value()))
            visible_hb = plot._from_disp("CH3", float(plot._h_cursor_b.value()))
            self.assertAlmostEqual(logical_hb, context.forward_a, places=9)
            self.assertAlmostEqual(visible_hb, -context.forward_a, places=9)
            self.assertLess(logical_hb, 0.0)
            self.assertGreater(visible_hb, 0.0)
            self.assertAlmostEqual(
                float(plot._h_cursor_b.value()),
                plot._to_disp("irr", context.forward_a),
                places=12,
            )
            for value in (context.forward_a, context.base_a, context.reverse_a):
                self.assertAlmostEqual(
                    plot._from_disp("irr", plot._to_disp("irr", value)),
                    value,
                    places=9,
                )

            # V/div and position changes use the interval agent's snapshot /
            # restore path; the signed logical value must not double-invert.
            original_scale = float(plot._disp_scale["CH3"])
            plot._set_channel_scale("CH3", original_scale * 1.25)
            plot._set_channel_offset(
                "CH3",
                float(plot._disp_offset["CH3"]) + 0.4,
            )
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_b.value())),
                context.forward_a,
                places=9,
            )
            self.assertAlmostEqual(
                float(plot._h_cursor_b.value()),
                plot._to_disp("irr", context.forward_a),
                places=12,
            )

            # Report capture freezes and reapplies the page before screenshot.
            # That replot must rebuild the same signed logical/display mapping.
            report_page = win._current_report_page_state()
            win._apply_report_page_state(report_page)
            self.app.processEvents()
            plot = win.wave_plot
            self.assertEqual(plot._logical_display_signs["irr"], -1)
            self.assertEqual(plot._display_key_for_channel("irr"), "CH3")
            self.assertIsNotNone(plot._h_cursor_b)
            assert plot._h_cursor_b is not None
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_b.value())),
                context.forward_a,
                places=9,
            )
            self.assertAlmostEqual(
                plot._from_disp("CH3", float(plot._h_cursor_b.value())),
                -context.forward_a,
                places=9,
            )
        finally:
            win.close()

    @unittest.skipUnless(SONGZHENXI_UH.exists(), "songzhenxi target sample missing")
    def test_songzhenxi_default_and_wanglihui_ui_inversion_remain_sign_plus_one(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        song = MainWindow()
        try:
            song._load_file(str(SONGZHENXI_UH))
            song._on_value_clicked("反向恢复", "di/dt")
            plot = song.wave_plot
            self.assertEqual(plot._logical_display_signs["irr"], 1)
            self.assertIsNotNone(plot._h_cursor_b)
            assert plot._h_cursor_b is not None
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_b.value())),
                -1044.40625,
                places=6,
            )
            self.assertAlmostEqual(
                plot._from_disp("CH3", float(plot._h_cursor_b.value())),
                -1044.40625,
                places=6,
            )
        finally:
            song.close()

        if not WANGLIHUI_UH.exists():
            self.skipTest("wanglihui UH sample missing")
        wang = MainWindow()
        try:
            wang._load_file(str(WANGLIHUI_UH))
            didt_before = wang.result.reverse_recovery.didt_irr
            wang.wave_plot.set_channel_inversion_enabled("CH3", True)
            self.app.processEvents()
            self.assertIsNotNone(wang.result)
            self.assertAlmostEqual(
                wang.result.reverse_recovery.didt_irr,
                didt_before,
                places=9,
            )
            wang._on_value_clicked("反向恢复", "di/dt")
            plot = wang.wave_plot
            self.assertEqual(plot._logical_display_signs["irr"], 1)
            self.assertIsNotNone(plot._h_cursor_b)
            assert plot._h_cursor_b is not None
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_b.value())),
                plot._from_disp("CH3", float(plot._h_cursor_b.value())),
                places=9,
            )
        finally:
            wang.close()

    @unittest.skipUnless(WANGLIHUI_UH.exists(), "wanglihui UH sample missing")
    def test_explicit_negative_irr_then_manual_inversion_flips_source_once_before_auto_orientation(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        win = MainWindow()
        try:
            win._load_file(str(WANGLIHUI_UH))
            win.profile = replace(win.profile, irr="-CH3")
            win._recalculate(reset_manual=True)
            self.assertIsNotNone(win.bundle)
            self.assertIsNotNone(win.result)
            assert win.bundle is not None and win.result is not None

            mapped_before = win.bundle.get("-CH3").copy()
            normalized_before = bundle_reverse_recovery_current(
                win.bundle,
                win.profile,
            ).copy()
            interval = win._parameter_interval_us("反向恢复", "di/dt")
            self.assertIsNotNone(interval)
            assert interval is not None
            context_before = win._rr_didt_context(*interval)
            self.assertIsNotNone(context_before)
            assert context_before is not None
            metrics_before = (
                win.result.reverse_recovery.irr,
                win.result.reverse_recovery.trr,
                win.result.reverse_recovery.err,
                win.result.reverse_recovery.didt_irr,
            )

            win.wave_plot.set_channel_inversion_enabled("CH3", True)
            self.app.processEvents()
            self.assertIn("CH3", win.bundle.meta.channel_display_inversions)
            mapped_after = win.bundle.get("-CH3")
            # Explicit '-' and the UI inversion are independent factors.  The
            # latter must flip the mapped logical source once, so two negatives
            # cancel instead of the signed reference bypassing the setting.
            np.testing.assert_allclose(mapped_after, -mapped_before)

            normalized_after = bundle_reverse_recovery_current(
                win.bundle,
                win.profile,
            )
            # RR then performs its one polarity normalization.  The same
            # physical event therefore keeps its chronological A/B and slope.
            np.testing.assert_allclose(normalized_after, normalized_before)
            np.testing.assert_allclose(
                np.asarray(win.wave_plot._interactive_irr, dtype=np.float64),
                normalized_after,
            )
            interval = win._parameter_interval_us("反向恢复", "di/dt")
            self.assertIsNotNone(interval)
            assert interval is not None
            context_after = win._rr_didt_context(*interval)
            self.assertIsNotNone(context_after)
            assert context_after is not None
            self.assertAlmostEqual(
                context_after.crossing.t_pct_a_s,
                context_before.crossing.t_pct_a_s,
                places=15,
            )
            self.assertAlmostEqual(
                context_after.crossing.t_pct_b_s,
                context_before.crossing.t_pct_b_s,
                places=15,
            )
            self.assertAlmostEqual(
                context_after.crossing.didt,
                context_before.crossing.didt,
                places=12,
            )
            metrics_after = (
                win.result.reverse_recovery.irr,
                win.result.reverse_recovery.trr,
                win.result.reverse_recovery.err,
                win.result.reverse_recovery.didt_irr,
            )
            np.testing.assert_allclose(metrics_after, metrics_before, rtol=0.0, atol=1e-12)
            np.testing.assert_allclose(
                metrics_after,
                (352.96875, 346.77059498497783, 11.163217897453809, 10.938162389246163),
                rtol=0.0,
                atol=1e-12,
            )

            win._on_value_clicked("反向恢复", "di/dt")
            plot = win.wave_plot
            self.assertEqual(plot._logical_display_signs["irr"], 1)
            self.assertEqual(plot._display_key_for_channel("irr"), "CH3")
            self.assertIsNotNone(plot._h_cursor_b)
            assert plot._h_cursor_b is not None
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_b.value())),
                context_after.forward_a,
                places=9,
            )
            self.assertAlmostEqual(
                plot._from_disp("CH3", float(plot._h_cursor_b.value())),
                context_after.forward_a,
                places=9,
            )
            self.assertAlmostEqual(
                float(plot._h_cursor_b.value()),
                plot._to_disp("irr", context_after.forward_a),
                places=12,
            )
        finally:
            win.close()

    @unittest.skipUnless(WANGLIHUI_UL.exists(), "wanglihui UL sample missing")
    def test_wanglihui_ul_matching_source_and_display_inversions_do_not_double_flip(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win._load_file(str(WANGLIHUI_UL))
            self.assertIsNotNone(win.bundle)
            self.assertIsNotNone(win.result)
            assert win.bundle is not None and win.result is not None
            self.assertEqual(win.bundle.meta.source_channel_inversions, {"CH3"})
            self.assertEqual(win.bundle.meta.channel_display_inversions, {"CH3"})
            np.testing.assert_allclose(
                win.bundle.get("CH3"),
                win.bundle.channels["CH3"],
            )
            self.assertAlmostEqual(
                win.result.reverse_recovery.irr,
                312.1875,
                places=9,
            )
            self.assertAlmostEqual(
                win.result.reverse_recovery.trr,
                287.32292063373046,
                places=9,
            )
            self.assertAlmostEqual(
                win.result.reverse_recovery.err,
                10.503158151987204,
                places=9,
            )
            self.assertAlmostEqual(
                win.result.reverse_recovery.didt_irr,
                10.796129092771245,
                places=9,
            )
            win._on_value_clicked("反向恢复", "di/dt")
            plot = win.wave_plot
            self.assertEqual(plot._logical_display_signs["irr"], 1)
            context = win._rr_didt_context(
                *win._parameter_interval_us("反向恢复", "di/dt")
            )
            self.assertIsNotNone(context)
            assert context is not None
            self.assertAlmostEqual(context.forward_a, -948.703125, places=9)
            self.assertAlmostEqual(context.base_a, 22.0546875, places=9)
            self.assertAlmostEqual(
                plot._from_disp("irr", float(plot._h_cursor_b.value())),
                context.forward_a,
                places=9,
            )
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
