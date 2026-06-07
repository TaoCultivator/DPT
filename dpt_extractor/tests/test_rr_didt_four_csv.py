from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.tek_parser import TekParser
from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
from dpt_extractor.metrics.slopes import analyze_rr_recovery_current, didt_rr_recovery
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.waveform import bundle_reverse_recovery_current
from dpt_extractor.pipeline.extract import extract_all

ROOT = Path(__file__).resolve().parents[2]

CSV_CASES = [
    ("UH_750V_1050A_000_ALL.csv", 13.0, 14.5),
    ("WH_480V_800A_000_ALL.csv", 1.8, 2.5),
    ("UL_750V_1050A_000_ALL.csv", 10.0, 11.5),
    ("WL_480V_800A_000_ALL.csv", 1.5, 2.2),
]


class TestRrDidtFourCsv(unittest.TestCase):
    def test_idm_90_10_spec_on_all_samples(self) -> None:
        for name, lo, hi in CSV_CASES:
            with self.subTest(name=name):
                path = ROOT / name
                if not path.exists():
                    self.skipTest(f"{name} missing")
                bundle = TekParser().parse(path)
                profile = guess_profile_from_path(name)
                result = extract_all(bundle, profile, load_config())
                irr = bundle_reverse_recovery_current(bundle, profile)
                on0, _ = result.segments.turn_on
                _, rr1 = result.segments.reverse_recovery
                i0, i1 = rr_slope_window_indices(
                    on0, rr1, len(bundle.t), bundle.dt
                )
                seg = irr[i0 : i1 + 1]
                idm, irm, _ = analyze_rr_recovery_current(seg)
                self.assertGreater(idm, 1.0, msg=f"{name}: IDM should be forward peak")
                res = didt_rr_recovery(
                    bundle.t,
                    irr,
                    i0,
                    i1,
                    0.9,
                    0.1,
                    measure="idm",
                    idm_override=0.0,
                    base_override=float(idm),
                )
                self.assertGreater(res.didt, lo, msg=f"{name}: didt={res.didt}")
                self.assertLess(res.didt, hi, msg=f"{name}: didt={res.didt}")
                self.assertIsNotNone(res.t_pct_a_s)
                self.assertIsNotNone(res.t_pct_b_s)
                self.assertLess(res.t_pct_a_s, res.t_pct_b_s)
                self.assertAlmostEqual(res.th_a, 0.9 * idm, delta=1.0)
                self.assertAlmostEqual(res.th_b, 0.1 * idm, delta=1.0)
                i_pk = int(np.argmax(seg))
                peak_t = float(bundle.t[i0 + i_pk])
                self.assertLessEqual(res.t_pct_a_s, peak_t + 1e-6)
                self.assertIsNotNone(irm)


if __name__ == "__main__":
    unittest.main()
