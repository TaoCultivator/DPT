from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_windows import (
    rr_completed_measurement_window_indices,
)
from dpt_extractor.metrics.slopes import rr_dvdt_measurement_context
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

        # Irr/Trr/di-dt/Pdmax were already correct through their own completed
        # main-lobe path and remain unchanged.  The 0729 report-backed repair
        # intentionally moves only dv/dt away from the late Vd overshoot and
        # lets Err reach the visible settled-tail crossing.
        self.assertAlmostEqual(result.reverse_recovery.irr, 94.4375, places=9)
        self.assertAlmostEqual(
            result.reverse_recovery.trr,
            29.608641740979344,
            places=9,
        )
        self.assertAlmostEqual(
            result.reverse_recovery.dvdt_max,
            5.510706815483219,
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
            7.793262545633712,
            places=9,
        )

        # The old fixed rr1+250 ns window stopped at 19.84056 us, before
        # either physical edge completed, yet produced plausible noise slopes.
        # The authoritative crossings must instead land on the late main
        # commutation edges of this same turn-on event.  Its settled Base is
        # the visible 2.09375..21.6875 V band's exact 11.890625 V midpoint.
        self.assertGreater(result.reverse_recovery.dvdt_max, 1.0)
        self.assertGreater(result.reverse_recovery.didt_irr, 3.5)


class TestRrMeasurementWindowCompletionGate(unittest.TestCase):
    def test_default_rr_dvdt_uses_stable_high_and_low_voltage_platforms(self) -> None:
        dt = 2e-9
        t = np.arange(2500, dtype=np.float64) * dt
        vd = np.full_like(t, 30.0)

        # A noisy pre-edge trace and a 1000 V recovery overshoot must keep Hb
        # on the stable 30 V low platform and Ha on the stable 800 V platform.
        ripple = np.array(
            [20.0, 25.0, 30.0, 35.0, 40.0, 35.0, 30.0, 25.0]
        )
        vd[:800] = np.resize(ripple, 800)
        vd[800:850] = np.linspace(30.0, 800.0, 50)
        vd[850:] = 800.0
        vd[870] = 1000.0
        vd[1200:] = 800.0 + 10.0 * np.sin(
            np.linspace(0.0, 20.0 * np.pi, len(vd) - 1200)
        )

        context = rr_dvdt_measurement_context(
            t,
            vd,
            800,
            920,
            dt,
            load_config(),
            0.1,
            0.9,
            event_end_idx=900,
            pulse_end_idx=2000,
        )

        self.assertAlmostEqual(context.base_v, 30.0, delta=0.05)
        self.assertAlmostEqual(context.top_v, 800.0, delta=0.05)
        self.assertLess(context.top_v, float(np.max(vd[800:920])))
        self.assertFalse(context.used_fallback)

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
