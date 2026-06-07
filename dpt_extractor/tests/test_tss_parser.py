from __future__ import annotations

import tempfile
import unittest
import zipfile
import io
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dpt_extractor.io.tss_parser import TssParser, _channel_from_member


class FakeAnalogWaveformMetaInfo:
    def __init__(self, waveform_label: str = "") -> None:
        self.waveform_label = waveform_label
        self.test_equipment = None
        self.y_position = None


class FakeAnalogWaveform:
    def __init__(self) -> None:
        self.meta_info = None
        self.source_name = ""
        self.x_axis_spacing = 0.0
        self.trigger_index = 0.0
        self.y_axis_values = np.array([], dtype=np.float64)
        self.x_axis_values = None

    @property
    def normalized_vertical_values(self):
        return self.y_axis_values

    @property
    def normalized_horizontal_values(self):
        spacing = float(self.x_axis_spacing or 0.0)
        trigger = float(self.trigger_index or 0.0)
        return (np.arange(len(self.y_axis_values), dtype=np.float64) - trigger) * spacing


class TestTssHelpers(unittest.TestCase):
    def test_channel_from_member(self):
        self.assertEqual(_channel_from_member("CH1.wfm"), "CH1")
        self.assertEqual(_channel_from_member("waveforms/math2.wfm"), "MATH2")
        self.assertEqual(_channel_from_member("waveforms/M3.wfm"), "MATH3")
        self.assertIsNone(_channel_from_member("screenshot.png"))


class TestTssParser(unittest.TestCase):
    def _make_wfm(self, n: int = 8, label: str = "H-Vge") -> FakeAnalogWaveform:
        wfm = FakeAnalogWaveform()
        wfm.meta_info = FakeAnalogWaveformMetaInfo(waveform_label=label)
        wfm.source_name = "CH1"
        wfm.x_axis_spacing = 8e-11
        wfm.trigger_index = 2.0
        wfm.y_axis_values = np.linspace(-1.0, 1.0, n)
        return wfm

    def _make_setup_zip(self, text: str) -> bytes:
        inner_bytes = io.BytesIO()
        with zipfile.ZipFile(inner_bytes, "w") as zf:
            zf.writestr("session_lrn.set", text)
        return inner_bytes.getvalue()

    def test_parse_session_zip(self):
        wfm = self._make_wfm()
        with tempfile.TemporaryDirectory() as tmp:
            tss_path = Path(tmp) / "WH_test.tss"
            with zipfile.ZipFile(tss_path, "w") as zf:
                zf.writestr("CH1.wfm", b"placeholder")
                zf.writestr("CH2.wfm", b"placeholder")

            t = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]) * 8e-11 - 2 * 8e-11
            y = np.linspace(-1.0, 1.0, 8)

            def fake_read(path: str):
                if Path(path).stem.upper() == "CH1":
                    return wfm
                other = self._make_wfm(label="H-Vce")
                other.source_name = "CH2"
                other.y_axis_values = y + 10.0
                return other

            with (
                patch("dpt_extractor.io.tss_parser.read_file", side_effect=fake_read),
                patch(
                    "dpt_extractor.io.tss_parser.read_wfm_vertical_scale_per_div",
                    side_effect=lambda p: 5.0 if Path(p).stem.upper() == "CH1" else 200.0,
                ),
            ):
                bundle = TssParser().parse(tss_path)

            self.assertEqual(set(bundle.channels.keys()), {"CH1", "CH2"})
            self.assertEqual(bundle.meta.channel_labels["CH1"], "H-Vge")
            self.assertEqual(bundle.meta.channel_vdiv["CH1"], 5.0)
            self.assertEqual(bundle.meta.channel_vdiv["CH2"], 200.0)
            self.assertEqual(bundle.n, 8)
            np.testing.assert_allclose(bundle.t, t)

    def test_parse_session_math_from_setup(self):
        n = 5
        values = {
            "CH1": np.zeros(n),
            "CH2": np.array([10.0, 10.0, 10.0, 10.0, 10.0]),
            "CH3": np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
            "CH4": np.array([5.0, 4.0, 3.0, 2.0, 1.0]),
            "CH5": np.array([2.0, 2.0, 2.0, 2.0, 2.0]),
            "CH6": np.zeros(n),
        }
        setup_text = (
            ':MAINWINDOW:SOURCEORDER "1%3Bch1%3Bch2%3Bch3%3Bch4%3Bch5%3Bch6%3Bmath1%3Bmath2%3Bmath3";'
            ":MATH:MATH1:FUNCTION ADD;"
            ':MATH:MATH1:DEFINE "";'
            ":MATH:MATH1:SOURCE1 CH3;"
            ":MATH:MATH1:SOURCE2 CH4;"
            ':MATH:MATH2:DEFINE "INTG%28Ch2%2AMath1%29";'
            ':MATH:MATH3:DEFINE "INTG%28Ch5%2ACh3%29";'
            ':CH1:LABEL:NAME "H-Vge";'
            ':MATH:MATH2:LABEL:NAME "Eon";'
            ":DISPLAY:GLOBAL:MATH1:STATE 1;"
            ":DISPLAY:GLOBAL:MATH2:STATE 1;"
            ":DISPLAY:GLOBAL:MATH3:STATE 1;"
            ":DISPLAY:WAVEVIEW1:MATH:MATH2:VERTICAL:SCALE 50.0000E-3;"
            ":DISPLAY:WAVEVIEW1:MATH:MATH2:VERTICAL:POSITION -3.8800;"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tss_path = Path(tmp) / "UH_test.tss"
            with zipfile.ZipFile(tss_path, "w") as zf:
                for ch in values:
                    zf.writestr(f"{ch.lower()}.wfm", b"placeholder")
                zf.writestr("UH_test.set", self._make_setup_zip(setup_text))

            def fake_read(path: str):
                ch = Path(path).stem.upper()
                wfm = self._make_wfm(n=n, label=ch)
                wfm.source_name = ch
                wfm.x_axis_spacing = 1.0
                wfm.trigger_index = 0.0
                wfm.y_axis_values = values[ch]
                return wfm

            with (
                patch("dpt_extractor.io.tss_parser.read_file", side_effect=fake_read),
                patch("dpt_extractor.io.tss_parser.read_wfm_vertical_scale_per_div", return_value=None),
            ):
                bundle = TssParser().parse(tss_path)

        expected_math1 = values["CH3"] + values["CH4"]
        expected_math2 = np.array([0.0, 60.0, 120.0, 180.0, 240.0])
        expected_math3 = np.array([0.0, 3.0, 8.0, 15.0, 24.0])
        self.assertEqual(
            [ch for ch in bundle.channels if ch.startswith("MATH")],
            ["MATH1", "MATH2", "MATH3"],
        )
        np.testing.assert_allclose(bundle.channels["MATH1"], expected_math1)
        np.testing.assert_allclose(bundle.channels["MATH2"], expected_math2)
        np.testing.assert_allclose(bundle.channels["MATH3"], expected_math3)
        self.assertEqual(bundle.meta.channel_math_formulas["MATH2"], "INTG(CH2*MATH1)")
        self.assertEqual(bundle.meta.channel_labels["CH1"], "H-Vge")
        self.assertEqual(bundle.meta.channel_labels["MATH2"], "Eon")
        self.assertAlmostEqual(bundle.meta.channel_vdiv["MATH2"], 0.05)
        self.assertAlmostEqual(bundle.meta.channel_y_position["MATH2"], -3.88)

    def test_invalid_tss_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.tss"
            bad.write_text("not a zip", encoding="utf-8")
            with self.assertRaises(ValueError):
                TssParser().parse(bad)
