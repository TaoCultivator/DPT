"""开通电流 Ha/Hb：抬升前低平台 + 抬升后震荡中线。"""
import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.tek_parser import TekParser
from dpt_extractor.metrics.plateau_level import turn_on_current_hb_ha_levels
from dpt_extractor.models.bridge_profile import UPPER_BRIDGE
from dpt_extractor.models.waveform import bundle_total_current
from dpt_extractor.pipeline.extract import extract_all


def test_turn_on_current_hb_ha_uh_sample():
    b = TekParser().parse("UH_750V_1050A_000_ALL.csv")
    r = extract_all(b, UPPER_BRIDGE, load_config())
    ic = np.abs(bundle_total_current(b, UPPER_BRIDGE))
    t = b.t
    on0, on1 = r.segments.turn_on
    from dpt_extractor.metrics.plateau_level import (
        ic_plateau_confirm_time_us,
        turn_on_current_baseline_and_plateau,
    )

    hb, val = turn_on_current_baseline_and_plateau(ic[on0 : on1 + 1], b.dt)
    t_b = ic_plateau_confirm_time_us(b.t, ic, on0, on1, val, b.dt)
    assert 20 < hb < 50
    assert 1000 < val < 1060
    assert abs(val - r.turn_on.turn_on_current) < 80
    assert t[on0] * 1e6 < t_b <= t[on1] * 1e6
