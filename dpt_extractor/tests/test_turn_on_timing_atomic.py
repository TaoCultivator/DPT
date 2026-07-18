from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_timings import (
    TurnOnTimingInstants,
    turn_on_timing_instants,
)
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.tests.sample_paths import sample_tss


class TestTurnOnTimingAtomicPair(unittest.TestCase):
    def setUp(self) -> None:
        self.dt = 1e-9
        self.t = np.arange(1000, dtype=np.float64) * self.dt
        self.vge = np.zeros(1000, dtype=np.float64)
        self.ic = np.zeros(1000, dtype=np.float64)
        self.cfg = load_config()

    def _measure_with_crossings(
        self, crossings: list[float | None]
    ) -> TurnOnTimingInstants:
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
            return turn_on_timing_instants(
                self.t,
                self.vge,
                self.ic,
                0,
                900,
                200,
                self.dt,
                self.cfg,
            )

    def test_isolated_i90_is_discarded_with_missing_i10(self) -> None:
        inst = self._measure_with_crossings([150e-9, None, 420e-9])
        self.assertEqual(
            inst,
            TurnOnTimingInstants(150e-9, None, None, 0.0, 0.0, 0.0),
        )

    def test_isolated_i10_is_discarded_with_missing_i90(self) -> None:
        inst = self._measure_with_crossings([150e-9, 260e-9, None])
        self.assertEqual(
            inst,
            TurnOnTimingInstants(150e-9, None, None, 0.0, 0.0, 0.0),
        )

    def test_complete_pair_keeps_all_three_shared_endpoints(self) -> None:
        inst = self._measure_with_crossings([150e-9, 260e-9, 420e-9])
        self.assertEqual(inst.t_v10_s, 150e-9)
        self.assertEqual(inst.t_i10_s, 260e-9)
        self.assertEqual(inst.t_i90_s, 420e-9)
        self.assertAlmostEqual(inst.td_on_ns, 110.0)
        self.assertAlmostEqual(inst.tr_ns, 160.0)
        self.assertAlmostEqual(inst.ton_ns, 270.0)

    def test_missing_vge_keeps_tr_but_not_partial_td_or_ton(self) -> None:
        inst = self._measure_with_crossings([None, 260e-9, 420e-9])
        self.assertIsNone(inst.t_v10_s)
        self.assertEqual(inst.t_i10_s, 260e-9)
        self.assertEqual(inst.t_i90_s, 420e-9)
        self.assertEqual(inst.td_on_ns, 0.0)
        self.assertAlmostEqual(inst.tr_ns, 160.0)
        self.assertEqual(inst.ton_ns, 0.0)


UH = sample_tss("UH_750V_1050A_000.tss")


@unittest.skipUnless(UH.exists(), "UH sample missing")
class TestTurnOnTimingAvailabilityPropagation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_waveform(UH)
        cls.profile = guess_profile_from_path(str(Path(UH)))
        cls.cfg = load_config()

    def test_missing_ic_pair_marks_all_turn_on_timing_cards_unavailable(self) -> None:
        isolated = TurnOnTimingInstants(1e-6, None, None, 0.0, 0.0, 0.0)
        with patch(
            "dpt_extractor.pipeline.extract.turn_on_timing_instants",
            return_value=isolated,
        ):
            result = extract_all(self.bundle, self.profile, self.cfg)
        for name in ("Ton", "Td_on", "Tr"):
            self.assertTrue(result.is_metric_unavailable("开通", name), name)
        self.assertEqual(result.turn_on.ton, 0.0)
        self.assertEqual(result.turn_on.td_on, 0.0)
        self.assertEqual(result.turn_on.tr, 0.0)

    def test_missing_vge_marks_only_mixed_source_timings_unavailable(self) -> None:
        no_vge = TurnOnTimingInstants(None, 1e-6, 1.2e-6, 0.0, 200.0, 0.0)
        with patch(
            "dpt_extractor.pipeline.extract.turn_on_timing_instants",
            return_value=no_vge,
        ):
            result = extract_all(self.bundle, self.profile, self.cfg)
        self.assertTrue(result.is_metric_unavailable("开通", "Ton"))
        self.assertTrue(result.is_metric_unavailable("开通", "Td_on"))
        self.assertFalse(result.is_metric_unavailable("开通", "Tr"))
        self.assertEqual(result.turn_on.tr, 200.0)


if __name__ == "__main__":
    unittest.main()
