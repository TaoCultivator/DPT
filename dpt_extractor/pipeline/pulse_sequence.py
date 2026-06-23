from __future__ import annotations

from copy import deepcopy

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.models.bridge_profile import BridgeProfile
from dpt_extractor.models.results import ExtractResult
from dpt_extractor.models.test_mode import TestMode, parse_test_mode
from dpt_extractor.models.waveform import WaveformBundle
from dpt_extractor.pipeline.run_extract import run_extraction


def dpt_export_pulse_pairs(detected_pulse_count: int) -> list[tuple[int, int]]:
    """
    Return (turn-off pulse, turn-on pulse) rows for DPT export/report.

    Double-pulse keeps the legacy single row: off #1 + on #2.
    For >2 pulses, rows slide forward: off #1/on #2, off #2/on #3, ...
    The first pulse's turn-on is intentionally not exported.
    """
    count = max(1, int(detected_pulse_count))
    if count == 1:
        return [(1, 1)]
    return [(pulse, pulse + 1) for pulse in range(1, count)]


def dpt_export_results(
    bundle: WaveformBundle,
    profile: BridgeProfile,
    cfg: AppConfig,
    current_result: ExtractResult,
) -> list[ExtractResult]:
    """Build the result rows that should be written for the current DPT waveform."""
    mode = parse_test_mode(cfg.test_mode.mode)
    if mode != TestMode.DPT or current_result.single_pulse_mode:
        return [current_result]
    count = int(current_result.detected_pulse_count or 0)
    if count <= 2:
        return [current_result]

    rows: list[ExtractResult] = []
    for off_pulse, on_pulse in dpt_export_pulse_pairs(count):
        row_cfg = deepcopy(cfg)
        row_cfg.pulse_selection.off_pulse = off_pulse
        row_cfg.pulse_selection.on_pulse = on_pulse
        rows.append(run_extraction(bundle, profile, row_cfg))
    return rows
