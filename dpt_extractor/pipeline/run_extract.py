from __future__ import annotations

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.models.bridge_profile import BridgeProfile
from dpt_extractor.models.results import ExtractResult
from dpt_extractor.models.test_mode import TestMode, parse_test_mode
from dpt_extractor.models.waveform import WaveformBundle
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.pipeline.short_circuit_extract import extract_short_circuit


def run_extraction(
    bundle: WaveformBundle,
    profile: BridgeProfile,
    cfg: AppConfig,
) -> ExtractResult:
    """按当前测试模式调度提取逻辑（双脉冲 / 短路）。"""
    mode = parse_test_mode(cfg.test_mode.mode)
    if mode == TestMode.SHORT_CIRCUIT:
        return extract_short_circuit(bundle, profile, cfg)
    return extract_all(bundle, profile, cfg)
