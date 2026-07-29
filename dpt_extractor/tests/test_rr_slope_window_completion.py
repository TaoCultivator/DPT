from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_windows import (
    rr_completed_measurement_window_indices,
)
from dpt_extractor.models.bridge_profile import PROFILES
from dpt_extractor.pipeline.extract import extract_all


ROOT = Path(__file__).resolve().parents[2]
SLOW_VL_LT = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "LT"
    / "VL_750V_1048A_000.tss"
)


@unittest.skipUnless(SLOW_VL_LT.exists(), "slow VL LT target sample missing")
class TestRrSlopeWindowCompletion(unittest.TestCase):
    def test_slow_vl_rr_metrics_reach_the_physical_commutation_event(self) -> None:
        bundle = load_waveform(SLOW_VL_LT)
        result = extract_all(bundle, PROFILES["VL"], load_config())

        # Irr/Trr were already correct through their own completed main-lobe
        # path.  Completing the shared RR measurement context must not move
        # those two control metrics.
        self.assertAlmostEqual(result.reverse_recovery.irr, 94.4375, places=9)
        self.assertAlmostEqual(
            result.reverse_recovery.trr,
            29.608641740979344,
            places=9,
        )
        self.assertAlmostEqual(
            result.reverse_recovery.dvdt_max,
            4.406522505465541,
            places=9,
        )
        self.assertAlmostEqual(
            result.reverse_recovery.didt_irr,
            4.222953299110066,
            places=9,
        )
        self.assertAlmostEqual(
            result.reverse_recovery.pdmax,
            43.906484375,
            places=9,
        )
        self.assertAlmostEqual(
            result.reverse_recovery.err,
            5.085597732896291,
            places=9,
        )

        # The old fixed rr1+250 ns window stopped at 19.84056 us, before
        # either physical edge completed, yet produced plausible noise slopes.
        # The authoritative crossings must instead land on the late main
        # commutation edges of this same turn-on event.
        self.assertGreater(result.reverse_recovery.dvdt_max, 1.0)
        self.assertGreater(result.reverse_recovery.didt_irr, 3.5)


class TestRrMeasurementWindowCompletionGate(unittest.TestCase):
    def test_extends_when_legacy_window_cannot_reach_90_percent_vd(self) -> None:
        vd = np.zeros(1000, dtype=np.float64)
        vd[400:500] = np.linspace(0.0, 100.0, 100)

        i0, i1, completed = rr_completed_measurement_window_indices(
            10,
            100,
            500,
            vd,
            len(vd),
            1e-9,
        )

        self.assertEqual(i0, 10)
        self.assertEqual(i1, 500)
        self.assertTrue(completed)

    def test_preserves_legacy_window_when_main_vd_edge_is_already_complete(
        self,
    ) -> None:
        vd = np.zeros(1000, dtype=np.float64)
        vd[200:300] = np.linspace(0.0, 100.0, 100)
        vd[300:] = 100.0

        i0, i1, completed = rr_completed_measurement_window_indices(
            10,
            100,
            500,
            vd,
            len(vd),
            1e-9,
        )

        self.assertEqual(i0, 10)
        self.assertEqual(i1, 350)
        self.assertFalse(completed)


if __name__ == "__main__":
    unittest.main()
