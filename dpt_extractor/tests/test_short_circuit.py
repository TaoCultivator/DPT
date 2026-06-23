from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dpt_extractor.tests.sample_paths import SAMPLE_ROOT

DL_UH = SAMPLE_ROOT / "tss格式" / "KSU2506" / "DCU" / "DL" / "LT" / "UH_480V_000.tss"
DL_UL = SAMPLE_ROOT / "tss格式" / "KSU2506" / "DCU" / "DL" / "LT" / "UL_480V_000.tss"
DDD_UH = (
    SAMPLE_ROOT
    / "tss格式"
    / "KSU2577"
    / "SSM1R7PB12B3DTFMMSPP25M4CF0016"
    / "DDD"
    / "HT"
    / "UH_750V_000.tss"
)
DDD_RT_VH = (
    SAMPLE_ROOT
    / "tss格式"
    / "KSU2577"
    / "SSM1R7PB12B3DTFMMSPP25M4CF0016"
    / "DDD"
    / "RT"
    / "VH_750V_000.tss"
)


class TestShortCircuitLabelMapping(unittest.TestCase):
    def test_infers_non_default_short_circuit_labels(self):
        import numpy as np

        from dpt_extractor.models.channel_mapping import infer_short_circuit_mapping_from_bundle
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        meta = TekMetadata(
            channel_labels={
                "CH4": "H-Vge",
                "CH5": "H-Vce",
                "CH2": "Ic",
                "CH1": "L-Vce",
                "CH6": "L-Vge",
            }
        )
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 8),
            channels={f"CH{i}": np.zeros(8) for i in range(1, 7)},
            meta=meta,
        )

        mapping = infer_short_circuit_mapping_from_bundle(bundle, "upper")
        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.vge, "CH4")
        self.assertEqual(mapping.vce, "CH5")
        self.assertEqual(mapping.ic, "CH2")
        self.assertEqual(mapping.v_diode, "CH1")
        self.assertEqual(mapping.vge_other, "CH6")
        self.assertFalse(mapping.ic_from_sum_irr_il)

    def test_short_circuit_energy_math_channel_uses_display_inversion(self):
        import numpy as np

        from dpt_extractor.models.bridge_profile import as_short_circuit_profile, make_profile
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle
        from dpt_extractor.pipeline.short_circuit_extract import (
            short_circuit_energy_peak_value,
            short_circuit_energy_value,
        )

        raw_energy = np.array([-3.0, -2.0, -1.0], dtype=np.float64)
        profile = as_short_circuit_profile(make_profile("U", "upper"))
        bundle = WaveformBundle(
            t=np.arange(raw_energy.size, dtype=np.float64),
            channels={
                "CH2": np.array([10.0, 10.0, 10.0], dtype=np.float64),
                "CH3": np.array([1.0, 2.0, 3.0], dtype=np.float64),
                "MATH1": raw_energy,
            },
            meta=TekMetadata(channel_display_inversions={"MATH1"}),
        )

        value, source = short_circuit_energy_value(
            bundle,
            profile,
            0,
            2,
            math_channel="MATH1",
        )
        peak, peak_source = short_circuit_energy_peak_value(
            bundle,
            profile,
            0,
            2,
            math_channel="MATH1",
        )

        self.assertEqual(source, "MATH1")
        self.assertAlmostEqual(value, 40.0)
        self.assertEqual(peak_source, "MATH1")
        self.assertAlmostEqual(peak, 3.0)


@unittest.skipUnless(DL_UH.exists() and DL_UL.exists(), "short-circuit DL samples missing")
class TestShortCircuitExtract(unittest.TestCase):
    def _extract(self, path: Path):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.io.waveform_loader import load_waveform
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.test_mode import TestMode
        from dpt_extractor.pipeline.run_extract import run_extraction

        cfg = load_config()
        cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        bundle = load_waveform(path)
        profile = guess_profile_from_path(path)
        return bundle, run_extraction(bundle, profile, cfg)

    def test_extracts_upper_short_circuit_window_and_values(self):
        bundle, result = self._extract(DL_UH)
        sc = result.short_circuit
        i0, i1 = result.segments.turn_off
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.models.bridge_profile import as_short_circuit_profile, guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_total_current
        from dpt_extractor.pipeline.short_circuit_extract import (
            short_circuit_current_cursors,
            short_circuit_energy_value,
            short_circuit_vpeak_cursors,
        )

        cfg = load_config()
        profile = as_short_circuit_profile(guess_profile_from_path(DL_UH))
        cursors = short_circuit_current_cursors(
            bundle.t,
            bundle_total_current(bundle, profile),
            i0,
            i1,
            bundle.dt,
            smooth_ns=cfg.smoothing.detect_window_ns,
        )
        self.assertIsNotNone(cursors)
        assert cursors is not None
        dut_vce_cursors = short_circuit_vpeak_cursors(
            bundle.t,
            bundle.get(profile.vge),
            bundle.get(profile.vce),
            i0,
            i1,
            bundle.dt,
            smooth_ns=cfg.smoothing.detect_window_ns,
        )
        other_vce_cursors = short_circuit_vpeak_cursors(
            bundle.t,
            bundle.get(profile.vge),
            bundle.get(profile.v_diode),
            i0,
            i1,
            bundle.dt,
            smooth_ns=cfg.smoothing.detect_window_ns,
        )
        self.assertIsNotNone(dut_vce_cursors)
        self.assertIsNotNone(other_vce_cursors)
        assert dut_vce_cursors is not None
        assert other_vce_cursors is not None
        esc_dut_expected, _ = short_circuit_energy_value(
            bundle, profile, cursors.i0, cursors.i1, other=False
        )
        esc_other_expected, _ = short_circuit_energy_value(
            bundle, profile, cursors.i0, cursors.i1, other=True
        )

        self.assertTrue(result.short_circuit_mode)
        self.assertEqual(result.profile_code, "UH")
        self.assertGreater(sc.ic_max, 3000.0)
        self.assertGreater(sc.esc_dut, 1.0)
        self.assertGreater(sc.vpeak_dut, sc.vpeak_other)
        self.assertGreater(sc.tsc, 1.0)
        self.assertLess(sc.tsc, 5.0)
        self.assertAlmostEqual(
            sc.ic_max,
            float(bundle.channels["CH3"][cursors.i0 : cursors.i1 + 1].max()),
            delta=1e-6,
        )
        self.assertAlmostEqual(
            sc.tsc,
            float((cursors.t_b_s - cursors.t_a_s) * 1e6),
            delta=1e-6,
        )
        self.assertIsNotNone(sc.tsc_start_us)
        self.assertIsNotNone(sc.tsc_end_us)
        assert sc.tsc_start_us is not None and sc.tsc_end_us is not None
        self.assertAlmostEqual(sc.tsc_start_us, cursors.t_a_s * 1e6, delta=1e-6)
        self.assertAlmostEqual(sc.tsc_end_us, cursors.t_b_s * 1e6, delta=1e-6)
        self.assertAlmostEqual(sc.tsc, sc.tsc_end_us - sc.tsc_start_us, delta=1e-6)
        self.assertEqual(sc.tsc_range, "0%-0%")
        self.assertAlmostEqual(sc.esc_dut, esc_dut_expected, delta=1e-6)
        self.assertAlmostEqual(sc.esc_other, esc_other_expected, delta=1e-6)
        self.assertAlmostEqual(sc.vpeak_dut, dut_vce_cursors.ha_a, delta=1e-6)
        self.assertAlmostEqual(sc.vpeak_other, other_vce_cursors.ha_a, delta=1e-6)

    def test_short_circuit_tsc_can_use_10_percent_current_range(self):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.io.waveform_loader import load_waveform
        from dpt_extractor.models.bridge_profile import as_short_circuit_profile, guess_profile_from_path
        from dpt_extractor.models.results import SHORT_CIRCUIT_TSC_RANGE_10
        from dpt_extractor.models.test_mode import TestMode
        from dpt_extractor.models.waveform import bundle_total_current
        from dpt_extractor.pipeline.run_extract import run_extraction
        from dpt_extractor.pipeline.short_circuit_extract import (
            short_circuit_current_percent_cursors,
        )

        bundle = load_waveform(DL_UH)
        profile = guess_profile_from_path(DL_UH)
        cfg_default = load_config()
        cfg_default.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        default_result = run_extraction(bundle, profile, cfg_default)

        cfg = load_config()
        cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        cfg.short_circuit_tsc_range = SHORT_CIRCUIT_TSC_RANGE_10
        result = run_extraction(bundle, profile, cfg)
        sc = result.short_circuit
        assert result.segments is not None
        i0, i1 = result.segments.turn_off
        sc_profile = as_short_circuit_profile(profile)
        cursors = short_circuit_current_percent_cursors(
            bundle.t,
            bundle_total_current(bundle, sc_profile),
            i0,
            i1,
            bundle.dt,
            smooth_ns=cfg.smoothing.detect_window_ns,
            percent=10.0,
        )

        self.assertIsNotNone(cursors)
        assert cursors is not None
        self.assertEqual(sc.tsc_range, SHORT_CIRCUIT_TSC_RANGE_10)
        self.assertAlmostEqual(sc.tsc_start_us, cursors.t_a_s * 1e6, delta=1e-6)
        self.assertAlmostEqual(sc.tsc_end_us, cursors.t_b_s * 1e6, delta=1e-6)
        self.assertAlmostEqual(sc.tsc, (cursors.t_b_s - cursors.t_a_s) * 1e6, delta=1e-6)
        self.assertLess(sc.tsc, default_result.short_circuit.tsc)
        self.assertAlmostEqual(sc.esc_dut, default_result.short_circuit.esc_dut, delta=1e-6)
        self.assertAlmostEqual(sc.esc_other, default_result.short_circuit.esc_other, delta=1e-6)

    def test_lower_short_circuit_tsc_10_percent_keeps_energy_and_profile(self):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.io.waveform_loader import load_waveform
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.results import SHORT_CIRCUIT_TSC_RANGE_10
        from dpt_extractor.models.test_mode import TestMode
        from dpt_extractor.pipeline.run_extract import run_extraction

        bundle = load_waveform(DL_UL)
        profile = guess_profile_from_path(DL_UL)
        cfg_default = load_config()
        cfg_default.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        default_result = run_extraction(bundle, profile, cfg_default)

        cfg = load_config()
        cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        cfg.short_circuit_tsc_range = SHORT_CIRCUIT_TSC_RANGE_10
        result = run_extraction(bundle, profile, cfg)
        sc = result.short_circuit

        self.assertEqual(result.profile_code, "UL")
        self.assertEqual(sc.tsc_range, SHORT_CIRCUIT_TSC_RANGE_10)
        self.assertGreater(sc.tsc, 0.0)
        self.assertLess(sc.tsc, default_result.short_circuit.tsc)
        self.assertAlmostEqual(sc.ic_max, default_result.short_circuit.ic_max, delta=1e-6)
        self.assertAlmostEqual(sc.esc_dut, default_result.short_circuit.esc_dut, delta=1e-6)
        self.assertAlmostEqual(sc.esc_other, default_result.short_circuit.esc_other, delta=1e-6)

    def test_extracts_lower_short_circuit_uses_lower_vce_as_dut(self):
        _bundle, result = self._extract(DL_UL)
        sc = result.short_circuit

        self.assertTrue(result.short_circuit_mode)
        self.assertEqual(result.profile_code, "UL")
        self.assertGreater(sc.ic_max, 3000.0)
        self.assertGreater(sc.esc_dut, 1.0)
        self.assertGreater(sc.vpeak_dut, sc.vpeak_other)
        self.assertGreater(sc.tsc, 1.0)

    def test_vpeak_other_uses_dut_vge_window_for_upper_and_lower(self):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.io.waveform_loader import load_waveform
        from dpt_extractor.models.bridge_profile import (
            as_short_circuit_profile,
            guess_profile_from_path,
        )
        from dpt_extractor.models.test_mode import TestMode
        from dpt_extractor.pipeline.run_extract import run_extraction
        from dpt_extractor.pipeline.short_circuit_extract import short_circuit_vpeak_cursors

        cfg = load_config()
        cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        for path in (DL_UH, DL_UL):
            bundle = load_waveform(path)
            profile = as_short_circuit_profile(guess_profile_from_path(path))
            result = run_extraction(bundle, profile, cfg)
            assert result.segments is not None
            i0, i1 = result.segments.turn_off
            cursors = short_circuit_vpeak_cursors(
                bundle.t,
                bundle.get(profile.vge),
                bundle.get(profile.v_diode),
                i0,
                i1,
                bundle.dt,
                smooth_ns=cfg.smoothing.detect_window_ns,
            )

            self.assertIsNotNone(cursors, path.name)
            assert cursors is not None
            self.assertAlmostEqual(
                result.short_circuit.vpeak_other,
                cursors.ha_a,
                delta=1e-6,
                msg=path.name,
            )


@unittest.skipUnless(DDD_UH.exists(), "short-circuit DDD sample missing")
class TestShortCircuitMathChannels(unittest.TestCase):
    def test_uses_matching_math_channels_when_available(self):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.io.waveform_loader import load_waveform
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.test_mode import TestMode
        from dpt_extractor.pipeline.run_extract import run_extraction

        cfg = load_config()
        cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        bundle = load_waveform(DDD_UH)
        result = run_extraction(bundle, guess_profile_from_path(DDD_UH), cfg)

        self.assertEqual(result.short_circuit.energy_dut_channel, "MATH1")
        self.assertEqual(result.short_circuit.energy_other_channel, "MATH2")
        self.assertGreater(result.short_circuit.esc_dut, result.short_circuit.esc_other)


@unittest.skipUnless(DDD_UH.exists(), "short-circuit DDD sample missing")
class TestValidateTssSamplesScript(unittest.TestCase):
    def test_ddd_voltage_only_sample_uses_short_circuit_validation(self):
        from scripts.validate_tss_samples import (
            _is_short_circuit_sample,
            _validate_sample,
        )

        self.assertTrue(_is_short_circuit_sample(DDD_UH))
        result = _validate_sample(DDD_UH)

        self.assertEqual(result.kind, "SC")
        self.assertEqual(result.status, "OK")
        self.assertIn("Imax=", result.detail)
        self.assertIn("Tsc=", result.detail)


class TestShortCircuitTemplateLayout(unittest.TestCase):
    def test_header_merge_and_alignment(self):
        from openpyxl import load_workbook

        from dpt_extractor.export.short_circuit_layout import (
            COL_PHASE,
            COL_TEMP,
            COL_TYPE,
            COL_VDC,
            DATA_START_ROW,
            HEADER_NAME_ROW,
            HEADER_UNIT_ROW,
            LAST_COL,
            TEMPLATE_ROWS,
            build_short_circuit_workbook,
        )

        ws = build_short_circuit_workbook().active
        merged = {m.coord for m in ws.merged_cells.ranges}
        last_data_row = DATA_START_ROW + len(TEMPLATE_ROWS) - 1

        self.assertIn("A3:A4", merged)
        self.assertIn("B3:B4", merged)
        self.assertIn("C3:C4", merged)
        self.assertEqual(ws.max_row, last_data_row)

        for row in range(HEADER_NAME_ROW, DATA_START_ROW + len(TEMPLATE_ROWS)):
            for col in range(1, LAST_COL + 1):
                cell = ws.cell(row, col)
                self.assertEqual(cell.alignment.horizontal, "center")
                self.assertEqual(cell.alignment.vertical, "center")
                self.assertFalse(cell.alignment.wrap_text)

        self.assertEqual(ws.cell(HEADER_NAME_ROW, COL_TEMP).value, "Temp")
        self.assertEqual(ws.cell(HEADER_NAME_ROW, COL_PHASE).value, "测试相")
        self.assertEqual(ws.cell(HEADER_NAME_ROW, COL_TYPE).value, "短路类型")
        self.assertIsNone(ws.cell(HEADER_UNIT_ROW, COL_TEMP).value)
        self.assertIsNone(ws.cell(HEADER_UNIT_ROW, COL_PHASE).value)
        self.assertIsNone(ws.cell(HEADER_UNIT_ROW, COL_TYPE).value)
        expected_temp_labels = {
            5: "25℃",
            7: "150℃",
            9: "-40℃",
            11: "25℃",
            13: "150℃",
            15: "-40℃",
            17: "25℃",
            19: "150℃",
            21: "-40℃",
        }
        for row in range(DATA_START_ROW, DATA_START_ROW + len(TEMPLATE_ROWS)):
            if row in expected_temp_labels:
                self.assertEqual(ws.cell(row, COL_TEMP).value, expected_temp_labels[row])
            else:
                self.assertIsNone(ws.cell(row, COL_TEMP).value)
            self.assertIsNone(ws.cell(row, COL_PHASE).value)
            self.assertIsNone(ws.cell(row, COL_TYPE).value)
            self.assertIsNone(ws.cell(row, COL_VDC).value)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "short_layout.xlsx"
            ws.parent.save(out)
            saved_ws = load_workbook(out).active

        self.assertIn("A3:A4", {m.coord for m in saved_ws.merged_cells.ranges})
        self.assertEqual(saved_ws.max_row, last_data_row)
        for row in range(DATA_START_ROW, DATA_START_ROW + len(TEMPLATE_ROWS)):
            if row in expected_temp_labels:
                self.assertEqual(saved_ws.cell(row, COL_TEMP).value, expected_temp_labels[row])
            else:
                self.assertIsNone(saved_ws.cell(row, COL_TEMP).value)
            self.assertIsNone(saved_ws.cell(row, COL_PHASE).value)
            self.assertIsNone(saved_ws.cell(row, COL_TYPE).value)
            self.assertIsNone(saved_ws.cell(row, COL_VDC).value)
        for coord in ("A3", "B3", "C3", "D3", "D4", "A5", "E5"):
            alignment = saved_ws[coord].alignment
            self.assertEqual(alignment.horizontal, "center")
            self.assertEqual(alignment.vertical, "center")
            self.assertFalse(alignment.wrap_text)

    def test_export_infers_phase_from_source_path_without_writing_temp(self):
        from openpyxl import load_workbook

        from dpt_extractor.export.short_circuit_layout import (
            COL_ICMAX,
            COL_PHASE,
            COL_TEMP,
            COL_VDC,
            DATA_START_ROW,
            TEMPLATE_ROWS,
            export_short_circuit,
        )
        from dpt_extractor.models.results import ExtractResult, ShortCircuitResult

        result = ExtractResult(
            short_circuit=ShortCircuitResult(ic_max=12.3),
            short_circuit_mode=True,
            source_path=str(Path("sample") / "RT" / "VL_750V_000.tss"),
        )

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "short_path_infer.xlsx"
            export_short_circuit(result, out)
            ws = load_workbook(out, data_only=True).active

        rows = [
            row
            for row in range(DATA_START_ROW, DATA_START_ROW + len(TEMPLATE_ROWS))
            if ws.cell(row, COL_PHASE).value == "VL"
            and ws.cell(row, COL_ICMAX).value is not None
        ]
        self.assertEqual(rows, [12])
        self.assertEqual(ws.cell(11, COL_TEMP).value, "25℃")
        self.assertIsNone(ws.cell(rows[0], COL_TEMP).value)
        self.assertEqual(ws.cell(rows[0], COL_VDC).value, 750)


@unittest.skipUnless(DL_UH.exists(), "short-circuit DL sample missing")
class TestShortCircuitExcel(unittest.TestCase):
    def test_export_short_circuit_template(self):
        from openpyxl import load_workbook

        from dpt_extractor.config.loader import load_config
        from dpt_extractor.export.excel_export import export_to_excel
        from dpt_extractor.export.short_circuit_layout import (
            COL_ICMAX,
            COL_PHASE,
            COL_TEMP,
            DATA_START_ROW,
            COL_TSC,
            COL_TYPE,
            COL_VDC,
            TEMPLATE_ROWS,
        )
        from dpt_extractor.io.waveform_loader import load_waveform
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.test_mode import TestMode
        from dpt_extractor.pipeline.run_extract import run_extraction

        cfg = load_config()
        cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        bundle = load_waveform(DL_UH)
        result = run_extraction(bundle, guess_profile_from_path(DL_UH), cfg)

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "short.xlsx"
            export_to_excel(result, out)
            ws = load_workbook(out, data_only=True).active

        self.assertEqual(ws.title, "短路测试")
        self.assertEqual(ws.cell(1, 1).value, "短路测试")
        self.assertEqual(ws.cell(3, COL_ICMAX).value, "短路电流Imax")
        rows = [
            row
            for row in range(DATA_START_ROW, DATA_START_ROW + len(TEMPLATE_ROWS))
            if ws.cell(row, COL_PHASE).value == "UH"
            and ws.cell(row, COL_ICMAX).value is not None
        ]
        self.assertEqual(rows, [9])
        row = rows[0]
        self.assertGreater(float(ws.cell(row, COL_ICMAX).value), 3000.0)
        self.assertGreater(float(ws.cell(row, COL_TSC).value), 1.0)
        self.assertEqual(ws.cell(row, COL_TEMP).value, "-40℃")
        self.assertIsNone(ws.cell(row, COL_TYPE).value)
        self.assertEqual(ws.cell(row, COL_VDC).value, 480)


@unittest.skipUnless(DL_UH.exists(), "short-circuit DL sample missing")
class TestShortCircuitGuiInteraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from PyQt6.QtCore import QSettings

        from dpt_extractor.gui.main_window import SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY
        from dpt_extractor.models.results import SHORT_CIRCUIT_TSC_RANGE_DEFAULT

        self._tsc_settings = QSettings("DPT", "DPTExtractor")
        self._old_tsc_range = self._tsc_settings.value(
            SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY,
            None,
        )
        self._tsc_settings.setValue(
            SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY,
            SHORT_CIRCUIT_TSC_RANGE_DEFAULT,
        )

    def tearDown(self):
        from dpt_extractor.gui.main_window import SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY

        if self._old_tsc_range is None:
            self._tsc_settings.remove(SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY)
        else:
            self._tsc_settings.setValue(
                SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY,
                self._old_tsc_range,
            )

    def test_short_circuit_parameter_click_keeps_current_view(self):
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.test_mode import TestMode

        win = MainWindow()
        win.cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        win._apply_test_mode_ui()
        win._load_file(str(DL_UH), background=False)
        self.app.processEvents()

        calls: list[tuple[float, float]] = []

        def _spy_focus(t0_us: float, t1_us: float) -> None:
            calls.append((float(t0_us), float(t1_us)))

        win.wave_plot.focus_interval_us = _spy_focus  # type: ignore[method-assign]
        win._enable_generic_parameter_interaction("短路过程", "短路电流Imax")
        self.app.processEvents()

        self.assertEqual(calls, [])
        assert win.result is not None and win.result.segments is not None
        t = win.bundle.t
        gate0, gate1 = win.result.segments.turn_off
        cursors = win._short_circuit_ic_default_cursors()
        self.assertIsNotNone(cursors)
        assert cursors is not None
        t_a_us, t_b_us, hb, ha = cursors
        self.assertGreater(t_a_us, float(t[gate0] * 1e6))
        self.assertGreater(t_b_us, t_a_us)
        self.assertLess(t_b_us - t_a_us, float((t[gate1] - t[gate0]) * 1e6))
        self.assertAlmostEqual(
            float(win.wave_plot._cursor_a.value()), float(t_a_us), places=6
        )
        self.assertAlmostEqual(
            float(win.wave_plot._cursor_b.value()), float(t_b_us), places=6
        )
        assert win.wave_plot._h_cursor_a is not None
        assert win.wave_plot._h_cursor_b is not None
        ha_line = win.wave_plot._from_disp("ic", float(win.wave_plot._h_cursor_a.value()))
        hb_line = win.wave_plot._from_disp("ic", float(win.wave_plot._h_cursor_b.value()))
        self.assertAlmostEqual(float(ha_line), float(ha), places=3)
        self.assertAlmostEqual(float(hb_line), float(hb), places=3)
        self.assertTrue(win.wave_plot._interval_max_hline_enabled)
        self.assertAlmostEqual(win.result.short_circuit.tsc, t_b_us - t_a_us, places=6)

        win._enable_generic_parameter_interaction("短路过程", "短路时间Tsc")
        self.app.processEvents()
        self.assertEqual(calls, [])
        self.assertAlmostEqual(
            float(win.wave_plot._cursor_a.value()), float(t_a_us), places=6
        )
        self.assertAlmostEqual(
            float(win.wave_plot._cursor_b.value()), float(t_b_us), places=6
        )
        self.assertTrue(win.wave_plot._interval_max_hline_enabled)
        win.close()

    def test_short_circuit_tsc_range_persists_across_restart_and_file_load(self):
        from dpt_extractor.gui.main_window import (
            MainWindow,
            SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY,
        )
        from dpt_extractor.models.results import SHORT_CIRCUIT_TSC_RANGE_10
        from dpt_extractor.models.test_mode import TestMode

        win = MainWindow()
        win.cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        win._apply_test_mode_ui()
        win._load_file(str(DL_UH), background=False)
        self.app.processEvents()
        win._on_short_circuit_tsc_range_changed(SHORT_CIRCUIT_TSC_RANGE_10)
        self.app.processEvents()
        self.assertEqual(
            self._tsc_settings.value(SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY),
            SHORT_CIRCUIT_TSC_RANGE_10,
        )
        win.close()

        win2 = MainWindow()
        self.assertEqual(win2.cfg.short_circuit_tsc_range, SHORT_CIRCUIT_TSC_RANGE_10)
        win2.cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        win2._apply_test_mode_ui()
        win2._load_file(str(DL_UH), background=False)
        self.app.processEvents()
        self.assertEqual(win2.cfg.short_circuit_tsc_range, SHORT_CIRCUIT_TSC_RANGE_10)
        assert win2.result is not None
        self.assertEqual(win2.result.short_circuit.tsc_range, SHORT_CIRCUIT_TSC_RANGE_10)
        self.assertEqual(
            win2._load_cfg_for_new_file().short_circuit_tsc_range,
            SHORT_CIRCUIT_TSC_RANGE_10,
        )
        win2.close()

    def test_initial_short_circuit_cursors_use_tsc_window_without_edge_markers(self):
        if not DDD_RT_VH.exists():
            self.skipTest("screenshot-matching short-circuit sample missing")

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.test_mode import TestMode

        win = MainWindow()
        win.cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        win._apply_test_mode_ui()
        win._load_file(str(DDD_RT_VH), background=False)
        self.app.processEvents()

        assert win.result is not None and win.result.segments is not None
        sc = win.result.short_circuit
        self.assertIsNotNone(sc.tsc_start_us)
        self.assertIsNotNone(sc.tsc_end_us)
        assert sc.tsc_start_us is not None and sc.tsc_end_us is not None

        labels: set[str] = set()
        for item in win.wave_plot.plot.getPlotItem().items:
            label = getattr(getattr(item, "label", None), "format", None)
            if isinstance(label, str):
                labels.add(label)

        self.assertNotIn("短路开始", labels)
        self.assertNotIn("短路结束", labels)
        gate0, gate1 = win.result.segments.turn_off
        self.assertGreater(abs(sc.tsc_start_us - float(win.bundle.t[gate0] * 1e6)), 0.01)
        self.assertGreater(abs(sc.tsc_end_us - float(win.bundle.t[gate1] * 1e6)), 0.05)
        assert win.wave_plot._cursor_a is not None and win.wave_plot._cursor_b is not None
        self.assertAlmostEqual(float(win.wave_plot._cursor_a.value()), sc.tsc_start_us, places=6)
        self.assertAlmostEqual(float(win.wave_plot._cursor_b.value()), sc.tsc_end_us, places=6)
        win.close()

    def test_short_circuit_energy_and_vpeak_default_windows(self):
        import numpy as np

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.test_mode import TestMode

        win = MainWindow()
        win.cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        win._apply_test_mode_ui()
        win._load_file(str(DL_UH), background=False)
        self.app.processEvents()

        calls: list[tuple[float, float]] = []

        def _spy_focus(t0_us: float, t1_us: float) -> None:
            calls.append((float(t0_us), float(t1_us)))

        win.wave_plot.focus_interval_us = _spy_focus  # type: ignore[method-assign]
        ic_cursors = win._short_circuit_ic_default_cursors()
        dut_vce_cursors = win._short_circuit_vpeak_default_cursors(win.profile.vce)
        other_vce_cursors = win._short_circuit_vpeak_default_cursors(
            win.profile.v_diode,
            gate_channel=win.profile.vge,
        )
        self.assertIsNotNone(ic_cursors)
        self.assertIsNotNone(dut_vce_cursors)
        self.assertIsNotNone(other_vce_cursors)
        assert ic_cursors is not None
        assert dut_vce_cursors is not None
        assert other_vce_cursors is not None

        def _assert_ab(cursors: tuple[float, float, float, float]) -> None:
            t_a_us, t_b_us, _hb, _ha = cursors
            self.assertAlmostEqual(
                float(win.wave_plot._cursor_a.value()), float(t_a_us), places=6
            )
            self.assertAlmostEqual(
                float(win.wave_plot._cursor_b.value()), float(t_b_us), places=6
            )

        for name in ("短路能量Esc_本管", "短路能量Esc_对管"):
            win._enable_generic_parameter_interaction("短路过程", name)
            self.app.processEvents()
            _assert_ab(ic_cursors)
            _ta, _tb, hb, _ha = ic_cursors
            assert win.wave_plot._h_cursor_a is not None
            assert win.wave_plot._h_cursor_b is not None
            hb_line = win.wave_plot._from_disp(
                "ic", float(win.wave_plot._h_cursor_b.value())
            )
            self.assertAlmostEqual(float(hb_line), float(hb), places=3)
            i0 = int(np.searchsorted(win.bundle.t, min(_ta, _tb) * 1e-6, side="left"))
            i1 = int(np.searchsorted(win.bundle.t, max(_ta, _tb) * 1e-6, side="left"))
            marker = win._short_circuit_energy_peak_marker(name, i0, i1)
            if marker is not None:
                peak, peak_channel = marker
                ha_line = win.wave_plot._from_disp(
                    peak_channel, float(win.wave_plot._h_cursor_a.value())
                )
                self.assertAlmostEqual(float(ha_line), float(peak), places=3)

        for name, cursors, channel, base_channel in (
            ("应力Vpeak_本管", dut_vce_cursors, "vce", "vge"),
            ("应力Vpeak_对管", other_vce_cursors, "v_diode", "vge"),
        ):
            win._enable_generic_parameter_interaction("短路过程", name)
            self.app.processEvents()
            _assert_ab(cursors)
            _ta, _tb, hb, ha = cursors
            assert win.wave_plot._h_cursor_a is not None
            assert win.wave_plot._h_cursor_b is not None
            ha_line = win.wave_plot._from_disp(
                channel, float(win.wave_plot._h_cursor_a.value())
            )
            hb_line = win.wave_plot._from_disp(
                base_channel, float(win.wave_plot._h_cursor_b.value())
            )
            self.assertAlmostEqual(float(ha_line), float(ha), places=3)
            self.assertAlmostEqual(float(hb_line), float(hb), places=3)

        self.assertEqual(calls, [])
        win.close()

    def test_short_circuit_dut_and_other_rows_have_different_colors(self):
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.gui.theme import SECTION_SHORT_DUT, SECTION_SHORT_OTHER
        from dpt_extractor.models.test_mode import TestMode

        win = MainWindow()
        win.cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        win._apply_test_mode_ui()
        win._load_file(str(DL_UH), background=False)
        self.app.processEvents()

        row_for = {
            name: row
            for row, (_section, name) in enumerate(win.result_table._row_meta)
        }
        dut_row = row_for["短路能量Esc_本管"]
        other_row = row_for["短路能量Esc_对管"]
        dut_color = win.result_table.table.item(dut_row, 1).background().color().name()
        other_color = win.result_table.table.item(other_row, 1).background().color().name()

        self.assertEqual(dut_color, SECTION_SHORT_DUT.lower())
        self.assertEqual(other_color, SECTION_SHORT_OTHER.lower())
        self.assertNotEqual(dut_color, other_color)
        win.close()


@unittest.skipUnless(DDD_UH.exists(), "short-circuit DDD sample missing")
class TestCrossModeWaveformLoading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_dpt_mode_keeps_short_circuit_waveform_when_parameters_fail(self):
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.test_mode import TestMode

        win = MainWindow()
        win.cfg.test_mode.mode = TestMode.DPT.value
        win._apply_test_mode_ui()
        win._load_file(str(DDD_UH), background=False)
        self.app.processEvents()

        self.assertIsNotNone(win.bundle)
        self.assertIsNone(win.result)
        self.assertGreater(len(win.wave_plot._trace_items), 0)
        self.assertIsNotNone(win.wave_plot._cursor_a)
        self.assertIsNotNone(win.wave_plot._cursor_b)
        self.assertNotIn("[CH4]", win.wave_plot._readout_label.text())
        self.assertIn("参数未计算", win.result_table.summary.text())
        win.close()
