"""开通 Vce dv/dt：Hb 为回落后平均值。"""
from pathlib import Path

import numpy as np
import pytest

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.plateau_level import dvdt_on_vce_fall_base_top
from dpt_extractor.models.bridge_profile import UPPER_BRIDGE
from dpt_extractor.pipeline.extract import extract_all

ROOT = Path(__file__).resolve().parents[1]


def _uh_sample() -> Path | None:
    sample_root = ROOT / "示例文件"
    matches = sorted(sample_root.rglob("UH_750V_1050A_000.tss")) if sample_root.exists() else []
    return matches[0] if matches else None


def test_dvdt_on_hb_above_segment_min():
    sample = _uh_sample()
    if sample is None:
        pytest.skip("UH TSS sample missing")
    b = load_waveform(sample)
    r = extract_all(b, UPPER_BRIDGE, load_config())
    vce = b.get(UPPER_BRIDGE.vce)
    on0, on1 = r.segments.turn_on
    seg = vce[on0 : on1 + 1]
    hb, ha = dvdt_on_vce_fall_base_top(seg, b.dt)
    assert hb > float(np.min(seg)) + 5.0
    assert ha > hb + 100.0
