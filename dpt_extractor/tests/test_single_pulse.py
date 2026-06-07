"""Single-pulse (one gate pulse) extraction — turn-off only."""

from __future__ import annotations

import unittest

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.detect.pulse_detector import PulseDetector
from dpt_extractor.detect.segmenter import Segmenter
from dpt_extractor.models.bridge_profile import make_profile
from dpt_extractor.models.waveform import TekMetadata, WaveformBundle
from dpt_extractor.pipeline.extract import extract_all


def _single_pulse_vge(n: int, dt: float, on_us: float, off_us: float) -> np.ndarray:
    vge = np.zeros(n)
    i_on = int(on_us * 1e-6 / dt)
    i_off = int(off_us * 1e-6 / dt)
    vge[i_on:i_off] = 15.0
    vge[i_off:] = 0.0
    return vge


class TestSinglePulse(unittest.TestCase):
    def test_detect_one_pulse_no_error(self):
        dt = 8e-11
        n = 250_000
        t = np.arange(n) * dt
        vge = _single_pulse_vge(n, dt, on_us=2.0, off_us=5.0)
        pulses = PulseDetector(AppConfig()).detect_all(t, vge, dt)
        self.assertEqual(len(pulses), 1)

    def test_build_edges_single_pulse(self):
        dt = 8e-11
        n = 50000
        vge = _single_pulse_vge(n, dt, on_us=2.0, off_us=5.0)
        pulses = [(int(2.0e-6 / dt), int(4.5e-6 / dt))]
        edges = PulseDetector(AppConfig()).build_edges(pulses, 1, 1, vge, dt)
        self.assertTrue(edges.single_pulse)
        self.assertEqual(edges.detected_pulse_count, 1)
        self.assertLess(edges.pulse1_on, edges.pulse1_off)

    def test_extract_single_pulse_mode(self):
        dt = 8e-11
        n = 250_000
        t = np.arange(n) * dt
        vge = _single_pulse_vge(n, dt, on_us=2.0, off_us=5.5)
        i0 = int(5.5e-6 / dt)
        i1 = min(n, i0 + 5000)
        vce = np.full(n, 600.0)
        seg = i1 - i0
        vce[i0:i1] = np.linspace(600, 50, seg)
        ic = np.zeros(n)
        ic[i0:i1] = np.linspace(200, 0, seg)
        bundle = WaveformBundle(
            t=t,
            channels={
                "CH1": vge,
                "CH2": vce,
                "CH3": ic,
                "CH4": np.zeros(n),
                "CH5": vce * 0.01,
                "CH6": np.zeros(n),
            },
            meta=TekMetadata(),
        )
        profile = make_profile("U", "upper")
        result = extract_all(bundle, profile, AppConfig())
        self.assertTrue(result.single_pulse_mode)
        self.assertGreater(result.turn_off.ic_off_max, 0.0)
        self.assertEqual(result.turn_on.eon, 0.0)
        self.assertEqual(result.reverse_recovery.err, 0.0)


if __name__ == "__main__":
    unittest.main()
