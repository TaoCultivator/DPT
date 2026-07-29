from __future__ import annotations

import os
import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_timings import turn_on_vce_top_from_ic_rise
from dpt_extractor.metrics.plateau_level import turn_on_vce_on_max_window_indices
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.channel_mapping import (
    apply_mapping,
    infer_best_mapping_from_bundle,
)
from dpt_extractor.models.waveform import bundle_total_current
from dpt_extractor.pipeline.extract import extract_all

ROOT = Path(__file__).resolve().parents[2]
WANGLIHUI_U = ROOT / "示例文件" / "wanglihui" / "U"
WANGLIHUI_UL = WANGLIHUI_U / "UL_400V_1070A_Rgon1.1R_Rgof5R_000.tss"
WANGLIHUI_UH = WANGLIHUI_U / "UH_400V_1070A_Rgon1.515R_Rgoff6.346R_000.tss"
LIKANGKANG_LT_V = (
    ROOT
    / "示例文件"
    / "likangkang"
    / "24B6-20260709"
    / "LT"
    / "v"
)


def _load_mapped(path: Path):
    bundle = load_waveform(path)
    guessed = guess_profile_from_path(str(path))
    mapping, _source = infer_best_mapping_from_bundle(bundle, guessed.bridge)
    profile = apply_mapping(guessed, mapping) if mapping is not None else guessed
    return bundle, profile, extract_all(bundle, profile, load_config())


class TestTurnOnCursorWindows(unittest.TestCase):
    def test_likangkang_vh_offset_baseline_keeps_real_turn_off_crossings(
        self,
    ) -> None:
        cases = {
            "vh-850v-1061.01a_000.tss": (
                510.530580835668,
                63.063803131152,
                573.594383966819,
            ),
            "vh-850v-777.7a_000.tss": (
                636.555185586138,
                55.068663139802,
                691.623848725940,
            ),
            "vh-900v-494.9a_000.tss": (
                597.786945709801,
                47.479217110926,
                645.266162820727,
            ),
            "vh-900v-693.37a_000.tss": (
                581.071327266743,
                52.800135979686,
                633.871463246428,
            ),
        }
        for name, (td_off_ns, tf_ns, toff_ns) in cases.items():
            path = LIKANGKANG_LT_V / name
            with self.subTest(sample=name):
                if not path.exists():
                    self.skipTest(f"missing {path}")
                _bundle, _profile, result = _load_mapped(path)
                self.assertAlmostEqual(result.turn_off.td_off, td_off_ns, places=6)
                self.assertAlmostEqual(result.turn_off.tf, tf_ns, places=6)
                self.assertAlmostEqual(result.turn_off.toff, toff_ns, places=6)

    def test_likangkang_vh_offset_baseline_keeps_real_turn_on_crossings(
        self,
    ) -> None:
        cases = {
            "vh-850v-1061.01a_000.tss": (
                195.378020876570,
                108.318917935122,
                303.696938811692,
            ),
            "vh-850v-777.7a_000.tss": (
                188.156957989656,
                95.738082067140,
                283.895040056796,
            ),
            "vh-900v-494.9a_000.tss": (
                176.798431009858,
                82.256592766703,
                259.055023776561,
            ),
            "vh-900v-693.37a_000.tss": (
                184.096872750447,
                91.736321134007,
                275.833193884454,
            ),
        }
        for name, (td_on_ns, tr_ns, ton_ns) in cases.items():
            path = LIKANGKANG_LT_V / name
            with self.subTest(sample=name):
                if not path.exists():
                    self.skipTest(f"missing {path}")
                _bundle, _profile, result = _load_mapped(path)
                self.assertAlmostEqual(result.turn_on.td_on, td_on_ns, places=6)
                self.assertAlmostEqual(result.turn_on.tr, tr_ns, places=6)
                self.assertAlmostEqual(result.turn_on.ton, ton_ns, places=6)
                self.assertNotIn(("开通", "Td_on"), result.unavailable_metrics)
                self.assertNotIn(("开通", "Tr"), result.unavailable_metrics)
                self.assertNotIn(("开通", "Ton"), result.unavailable_metrics)

    def test_wanglihui_vce_on_max_window_spans_turn_on_event(self) -> None:
        cases = [
            (WANGLIHUI_UL, (36.22, 36.32), (36.78, 36.95)),
            (WANGLIHUI_UH, (35.60, 35.72), (36.15, 36.32)),
        ]
        for path, a_band, b_band in cases:
            with self.subTest(sample=path.name):
                if not path.exists():
                    self.skipTest(f"missing {path}")
                bundle, profile, result = _load_mapped(path)
                segs = result.segments
                assert segs is not None
                t = bundle.t
                vge = bundle.get(profile.vge)
                vce = bundle.get(profile.vce)
                ic = bundle_total_current(bundle, profile)
                vce_top = turn_on_vce_top_from_ic_rise(
                    ic, vce, segs.pulse2_on, segs.pulse2_off, bundle.dt
                )
                ia, ib = turn_on_vce_on_max_window_indices(
                    t,
                    vge,
                    vce,
                    segs.turn_on[0],
                    segs.turn_on[1],
                    segs.pulse2_on,
                    segs.pulse2_off,
                    bundle.dt,
                    vce_top,
                )
                a_us = float(t[ia] * 1e6)
                b_us = float(t[ib] * 1e6)
                self.assertGreaterEqual(a_us, a_band[0])
                self.assertLessEqual(a_us, a_band[1])
                self.assertGreaterEqual(b_us, b_band[0])
                self.assertLessEqual(b_us, b_band[1])
                self.assertGreater(b_us, a_us + 0.45)
                self.assertLess(float(vce[ib]), 0.12 * max(float(vce[ia]), 1.0))
                self.assertAlmostEqual(
                    result.turn_on.vce_on_max,
                    float(np.max(vce[ia : ib + 1])),
                    delta=1e-9,
                )

    def test_non_slope_parameter_modes_enter_independent(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except Exception:
            self.skipTest("PyQt6 unavailable")
        from dpt_extractor.gui.waveform_plot import WaveformPlot

        app = QApplication.instance() or QApplication([])
        _ = app
        plot = WaveformPlot()
        plot.enable_turn_on_current_interaction(
            1.0, 2.0, 3.0, 10.0, 100.0, lambda *_args: None
        )
        self.assertFalse(plot.cursor_linked())
        assert plot._cursor_b is not None
        assert plot._h_cursor_a is not None
        b0 = float(plot._cursor_b.value())
        plot.set_cursor_linked(True)
        self.assertTrue(plot.cursor_linked())
        plot._h_cursor_a.setPos(float(plot._h_cursor_a.value()) + 0.5)
        self.assertAlmostEqual(float(plot._cursor_b.value()), b0)

        plot.enable_dvdt_interaction(
            1.0, 2.0, 100.0, 0.0, "vce", lambda *_args: None, mode="dvdt"
        )
        self.assertTrue(plot.cursor_linked())
        plot.close()

    def test_vce_on_max_horizontal_cursor_updates_value_only_from_ha(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except Exception:
            self.skipTest("PyQt6 unavailable")
        if not WANGLIHUI_UH.exists():
            self.skipTest(f"missing {WANGLIHUI_UH}")
        from dpt_extractor.gui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        bundle, profile, result = _load_mapped(WANGLIHUI_UH)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = load_config()
        win.result_table.set_result(result)
        win.wave_plot.plot_waveforms(bundle, profile, result)

        win._on_value_clicked("开通", "Vce_on_max")
        plot = win.wave_plot
        assert plot._cursor_a is not None
        assert plot._cursor_b is not None
        assert plot._h_cursor_a is not None
        assert plot._h_cursor_b is not None

        a0 = float(plot._cursor_a.value())
        b0 = float(plot._cursor_b.value())
        i0 = int(np.searchsorted(bundle.t, min(a0, b0) * 1e-6, side="left"))
        i1 = int(np.searchsorted(bundle.t, max(a0, b0) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(bundle.t) - 1))
        i1 = max(i0 + 1, min(i1, len(bundle.t) - 1))
        vce = bundle.get(profile.vce)

        ha = plot._from_disp("vce", float(plot._h_cursor_a.value()))
        hb = plot._from_disp("vce", float(plot._h_cursor_b.value()))
        self.assertAlmostEqual(float(ha), float(np.max(vce[i0 : i1 + 1])), places=6)
        self.assertAlmostEqual(float(hb), float(np.min(vce[i0 : i1 + 1])), places=6)

        manual_ha = float(ha) - 12.5
        plot._h_cursor_a.setPos(plot._to_disp("vce", manual_ha))
        QApplication.processEvents()
        self.assertAlmostEqual(float(plot._cursor_a.value()), a0, places=6)
        self.assertAlmostEqual(float(plot._cursor_b.value()), b0, places=6)
        self.assertAlmostEqual(win.result.turn_on.vce_on_max, manual_ha, places=6)

        plot._h_cursor_b.setPos(plot._to_disp("vce", float(hb) + 20.0))
        QApplication.processEvents()
        self.assertAlmostEqual(win.result.turn_on.vce_on_max, manual_ha, places=6)

        plot.focus_interval_us(30.0, 31.0)
        before = plot.current_x_range_us()
        self.assertIsNotNone(before)
        win._on_value_clicked("开通", "Vce_on_max")
        QApplication.processEvents()
        after = plot.current_x_range_us()
        self.assertIsNotNone(after)
        assert before is not None and after is not None
        self.assertAlmostEqual(after[0], before[0], places=6)
        self.assertAlmostEqual(after[1], before[1], places=6)
        restored_ha = plot._from_disp("vce", float(plot._h_cursor_a.value()))
        self.assertAlmostEqual(float(restored_ha), manual_ha, places=6)
        win.close()
        _ = app
