from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_timings import (
    TurnOffTimingInstants,
    turn_off_timing_instants,
)
from dpt_extractor.metrics.iec_timings import turn_off_timings
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.tests.sample_paths import sample_tss


class TestTurnOffTimingAtomicPair(unittest.TestCase):
    def setUp(self) -> None:
        self.dt = 1e-9
        self.t = np.arange(1000, dtype=np.float64) * self.dt
        self.vge = np.zeros(1000, dtype=np.float64)
        self.ic = np.zeros(1000, dtype=np.float64)
        self.cfg = load_config()

    def _measure_with_crossings(
        self, crossings: list[float | None]
    ) -> TurnOffTimingInstants:
        with (
            patch(
                "dpt_extractor.metrics.iec_timings._plateau_ic",
                return_value=100.0,
            ),
            patch(
                "dpt_extractor.metrics.iec_timings.crossing_time",
                side_effect=crossings,
            ),
        ):
            return turn_off_timing_instants(
                self.t,
                self.vge,
                self.ic,
                0,
                900,
                200,
                self.dt,
                self.cfg,
            )

    def test_missing_ic10_does_not_fabricate_toff(self) -> None:
        inst = self._measure_with_crossings([100e-9, 200e-9, None])
        self.assertEqual(inst.t_v90_s, 100e-9)
        self.assertEqual(inst.t_i90_s, 200e-9)
        self.assertIsNone(inst.t_i10_s)
        self.assertEqual(inst.td_off_ns, 0.0)
        self.assertEqual(inst.tf_ns, 0.0)
        self.assertEqual(inst.toff_ns, 0.0)
        self.assertEqual(
            turn_off_timings(
                self.t,
                self.vge,
                self.ic,
                0,
                900,
                200,
                self.dt,
                self.cfg,
            ),
            (0.0, 0.0, 0.0),
        )

    def test_complete_ordered_instants_preserve_sum_identity(self) -> None:
        inst = self._measure_with_crossings([100e-9, 200e-9, 350e-9])
        self.assertAlmostEqual(inst.td_off_ns, 100.0)
        self.assertAlmostEqual(inst.tf_ns, 150.0)
        self.assertAlmostEqual(inst.toff_ns, 250.0)
        self.assertAlmostEqual(inst.toff_ns, inst.td_off_ns + inst.tf_ns)


UH = sample_tss("UH_750V_1050A_000.tss")


@unittest.skipUnless(UH.exists(), "UH sample missing")
class TestTurnOffTimingAvailabilityPropagation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_waveform(UH)
        cls.profile = guess_profile_from_path(str(Path(UH)))
        cls.cfg = load_config()

    def test_missing_ic10_marks_all_turn_off_timing_cards_unavailable(self) -> None:
        incomplete = TurnOffTimingInstants(
            1e-6,
            1.1e-6,
            None,
            0.0,
            0.0,
            0.0,
        )
        with patch(
            "dpt_extractor.pipeline.extract.turn_off_timing_instants",
            return_value=incomplete,
        ):
            result = extract_all(self.bundle, self.profile, self.cfg)
        for name in ("Toff", "Td_off", "Tf"):
            self.assertTrue(result.is_metric_unavailable("关断过程", name), name)
        self.assertEqual(result.turn_off.toff, 0.0)
        self.assertEqual(result.turn_off.td_off, 0.0)
        self.assertEqual(result.turn_off.tf, 0.0)


if __name__ == "__main__":
    unittest.main()
