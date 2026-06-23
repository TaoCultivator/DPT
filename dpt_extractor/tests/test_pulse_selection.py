import unittest

import numpy as np

from dpt_extractor.config.loader import AppConfig, PulseSelectionConfig
from dpt_extractor.detect.pulse_detector import PulseDetector
from dpt_extractor.pipeline.pulse_sequence import dpt_export_pulse_pairs


class TestPulseSelection(unittest.TestCase):
    def test_build_edges_second_pulse(self):
        cfg = AppConfig(pulse_selection=PulseSelectionConfig(off_pulse=1, on_pulse=2))
        pulses = [(100, 200), (300, 400), (500, 600)]
        vge = np.zeros(700)
        vge[100:201] = 10.0
        vge[300:401] = 10.0
        vge[500:601] = 10.0
        edges = PulseDetector(cfg).build_edges(pulses, 1, 2, vge, 1e-8)
        self.assertEqual(edges.pulse1_on, 100)
        self.assertEqual(edges.pulse2_on, 300)
        self.assertEqual(edges.off_pulse_number, 1)
        self.assertEqual(edges.on_pulse_number, 2)

    def test_build_edges_third_on(self):
        cfg = AppConfig(pulse_selection=PulseSelectionConfig(off_pulse=2, on_pulse=3))
        pulses = [(100, 200), (300, 400), (500, 600)]
        vge = np.zeros(700)
        for a, b in pulses:
            vge[a : b + 1] = 10.0
        edges = PulseDetector(cfg).build_edges(pulses, 2, 3, vge, 1e-8)
        self.assertEqual(edges.pulse1_on, 300)
        self.assertEqual(edges.pulse2_on, 500)

    def test_on_before_off_rejected(self):
        cfg = AppConfig()
        pulses = [(0, 10), (20, 30)]
        vge = np.zeros(40)
        with self.assertRaises(ValueError):
            PulseDetector(cfg).build_edges(pulses, 2, 1, vge, 1e-8)

    def test_same_pulse_off_and_on(self):
        pulses = [(100, 200), (300, 400)]
        vge = np.zeros(500)
        vge[100:201] = 10.0
        vge[300:401] = 10.0
        edges = PulseDetector(AppConfig()).build_edges(pulses, 2, 2, vge, 1e-8)
        self.assertEqual(edges.pulse1_on, 300)
        self.assertEqual(edges.pulse2_on, 300)
        self.assertEqual(edges.pulse2_off, 400)
        self.assertGreater(edges.pulse1_off, edges.pulse1_on)
        self.assertEqual(edges.off_pulse_number, 2)
        self.assertEqual(edges.on_pulse_number, 2)

    def test_export_pairs_skip_first_turn_on_and_slide_forward(self):
        self.assertEqual(dpt_export_pulse_pairs(2), [(1, 2)])
        self.assertEqual(dpt_export_pulse_pairs(4), [(1, 2), (2, 3), (3, 4)])


if __name__ == "__main__":
    unittest.main()
