import unittest
from unittest.mock import patch

import numpy as np

from dpt_extractor.config.loader import AppConfig, PulseSelectionConfig
from dpt_extractor.detect.pulse_detector import PulseDetector
from dpt_extractor.pipeline.pulse_sequence import dpt_export_pulse_pairs
from dpt_extractor.pipeline.pulse_sequence import dpt_export_results


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
        self.assertEqual(
            dpt_export_pulse_pairs(4, include_pair=(1, 3)),
            [(1, 2), (1, 3), (2, 3), (3, 4)],
        )
        self.assertEqual(
            dpt_export_pulse_pairs(4, include_pair=(2, 2)),
            [(1, 2), (2, 2), (2, 3), (3, 4)],
        )

    def test_export_results_reports_only_completed_pulse_pairs(self):
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import ExtractResult
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        current = ExtractResult(
            detected_pulse_count=4,
            off_pulse_index=2,
            on_pulse_index=3,
            idc_set=987.0,
        )
        cfg = AppConfig()
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 8),
            channels={},
            meta=TekMetadata(),
        )
        completed: list[tuple[int, int]] = []

        def fake_extract(_bundle, _profile, row_cfg):
            return ExtractResult(
                off_pulse_index=row_cfg.pulse_selection.off_pulse,
                on_pulse_index=row_cfg.pulse_selection.on_pulse,
            )

        with patch(
            "dpt_extractor.pipeline.pulse_sequence.run_extraction",
            side_effect=fake_extract,
        ) as mocked:
            rows = dpt_export_results(
                bundle,
                make_profile("U", "upper"),
                cfg,
                current,
                progress_callback=lambda done, total: completed.append((done, total)),
            )

        self.assertEqual(completed, [(1, 3), (2, 3), (3, 3)])
        self.assertEqual(
            [(row.off_pulse_index, row.on_pulse_index) for row in rows],
            [(1, 2), (2, 3), (3, 4)],
        )
        self.assertEqual(rows[1].idc_set, 987.0)
        self.assertIsNot(rows[1], current)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(cfg.pulse_selection.off_pulse, 1)
        self.assertEqual(cfg.pulse_selection.on_pulse, 2)

    def test_export_results_preserves_non_adjacent_and_same_pulse_page_rows(self):
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import ExtractResult
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        cfg = AppConfig()
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 8),
            channels={},
            meta=TekMetadata(),
        )

        def fake_extract(_bundle, _profile, row_cfg):
            return ExtractResult(
                detected_pulse_count=4,
                off_pulse_index=row_cfg.pulse_selection.off_pulse,
                on_pulse_index=row_cfg.pulse_selection.on_pulse,
            )

        for current_pair in ((1, 3), (2, 2)):
            with self.subTest(current_pair=current_pair):
                current = ExtractResult(
                    detected_pulse_count=4,
                    off_pulse_index=current_pair[0],
                    on_pulse_index=current_pair[1],
                    idc_set=987.0,
                )
                progress: list[tuple[int, int]] = []
                with patch(
                    "dpt_extractor.pipeline.pulse_sequence.run_extraction",
                    side_effect=fake_extract,
                ):
                    rows = dpt_export_results(
                        bundle,
                        make_profile("U", "upper"),
                        cfg,
                        current,
                        progress_callback=lambda done, total: progress.append(
                            (done, total)
                        ),
                    )

                matching = [
                    row
                    for row in rows
                    if (row.off_pulse_index, row.on_pulse_index) == current_pair
                ]
                self.assertEqual(len(rows), 4)
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].idc_set, 987.0)
                self.assertIsNot(matching[0], current)
                self.assertEqual(progress[-1], (4, 4))


if __name__ == "__main__":
    unittest.main()
