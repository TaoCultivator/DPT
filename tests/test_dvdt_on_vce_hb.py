"""开通 Vce dv/dt：Hb 为回落后平均值。"""
import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.tek_parser import TekParser
from dpt_extractor.metrics.plateau_level import dvdt_on_vce_fall_base_top
from dpt_extractor.models.bridge_profile import UPPER_BRIDGE
from dpt_extractor.pipeline.extract import extract_all


def test_dvdt_on_hb_above_segment_min():
    b = TekParser().parse("UH_750V_1050A_000_ALL.csv")
    r = extract_all(b, UPPER_BRIDGE, load_config())
    vce = b.get(UPPER_BRIDGE.vce)
    on0, on1 = r.segments.turn_on
    seg = vce[on0 : on1 + 1]
    hb, ha = dvdt_on_vce_fall_base_top(seg, b.dt)
    assert hb > float(np.min(seg)) + 5.0
    assert ha > hb + 100.0
