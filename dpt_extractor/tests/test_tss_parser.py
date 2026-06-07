from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dpt_extractor.io.tss_parser import TssParser, _channel_from_member
from tm_data_types import AnalogWaveform, AnalogWaveformMetaInfo


class TestTssHelpers(unittest.TestCase):
    def test_channel_from_member(self):
        self.assertEqual(_channel_from_member("CH1.wfm"), "CH1")
        self.assertEqual(_channel_from_member("waveforms/math2.wfm"), "MATH2")
        self.assertIsNone(_channel_from_member("screenshot.png"))


class TestTssParser(unittest.TestCase):
    def _make_wfm(self, n: int = 8, label: str = "H-Vge") -> AnalogWaveform:
        wfm = AnalogWaveform()
        wfm.meta_info = AnalogWaveformMetaInfo(waveform_label=label)
        wfm.source_name = "CH1"
        wfm.x_axis_spacing = 8e-11
        wfm.trigger_index = 2.0
        wfm.y_axis_values = np.linspace(-1.0, 1.0, n)
        return wfm

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

    def test_invalid_tss_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.tss"
            bad.write_text("not a zip", encoding="utf-8")
            with self.assertRaises(ValueError):
                TssParser().parse(bad)
