from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.tek_parser import TekParser
from dpt_extractor.metrics.plateau_level import (
    turn_on_current_baseline_and_plateau,
    turn_on_didt_ha_at_turn_on,
)
from dpt_extractor.metrics.slopes import didt_between_base_top
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.slope_range import preset_to_range, SLOPE_RANGE_PRESETS
from dpt_extractor.models.waveform import bundle_total_current
from dpt_extractor.pipeline.extract import extract_all

UH = Path(__file__).resolve().parents[2] / "UH_750V_1050A_000_ALL.csv"
WH = Path(__file__).resolve().parents[2] / "WH_480V_800A_000_ALL.csv"


@unittest.skipUnless(UH.exists(), "UH sample missing")
class TestOnDidt8020(unittest.TestCase):
    def test_8020_rise_crossings_with_plateau_hb(self) -> None:
        bundle = TekParser().parse(UH)
        profile = guess_profile_from_path(UH.name)
        result = extract_all(bundle, profile, load_config())
        on0, on1 = result.segments.turn_on
        ic = bundle_total_current(bundle, profile)
        seg = np.abs(ic[on0 : on1 + 1])
        hb, _ha_seg = turn_on_current_baseline_and_plateau(seg, bundle.dt)
        ha = turn_on_didt_ha_at_turn_on(bundle.t, ic, on0, on1, bundle.dt)
        self.assertGreater(ha, 1000.0)
        self.assertLess(ha, 1060.0)
        self.assertAlmostEqual(ha, 1036.125, delta=2.0)
        sr = preset_to_range(SLOPE_RANGE_PRESETS["on_didt"][2])
        pa, pb = sr.as_fractions()
        self.assertEqual(sr.ic_direction, "rise")
        res = didt_between_base_top(
            bundle.t, ic, on0, on1, hb, ha, pa, pb, sr.ic_direction
        )
        self.assertGreater(res.didt, 1.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)
        self.assertGreater(res.t_pct_a_s, res.t_pct_b_s)
        self.assertGreater(res.t_pct_b_s * 1e6, 18.47)
        self.assertLess(res.t_pct_a_s * 1e6, 18.65)


@unittest.skipUnless(WH.exists(), "WH sample missing")
class TestOnDidtHaRelative(unittest.TestCase):
    def test_ha_follows_turn_on_plateau_not_fixed_19us(self) -> None:
        bundle = TekParser().parse(WH)
        profile = guess_profile_from_path(WH.name)
        result = extract_all(bundle, profile, load_config())
        on0, on1 = result.segments.turn_on
        ic = bundle_total_current(bundle, profile)
        ha = turn_on_didt_ha_at_turn_on(bundle.t, ic, on0, on1, bundle.dt)
        self.assertGreater(ha, 600.0)
        self.assertLess(ha, 950.0)


if __name__ == "__main__":
    unittest.main()
