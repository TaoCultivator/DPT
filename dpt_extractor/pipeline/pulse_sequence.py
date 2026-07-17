from __future__ import annotations

from copy import deepcopy
from typing import Callable

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.models.bridge_profile import BridgeProfile
from dpt_extractor.models.results import ExtractResult
from dpt_extractor.models.test_mode import TestMode, parse_test_mode
from dpt_extractor.models.waveform import WaveformBundle
from dpt_extractor.pipeline.run_extract import run_extraction


def dpt_export_pulse_pairs(
    detected_pulse_count: int,
    *,
    include_pair: tuple[int, int] | None = None,
) -> list[tuple[int, int]]:
    """
    Return (turn-off pulse, turn-on pulse) rows for DPT export/report.

    Double-pulse keeps the legacy single row: off #1 + on #2.
    For >2 pulses, rows slide forward: off #1/on #2, off #2/on #3, ...
    The first pulse's turn-on is intentionally not exported.
    """
    count = max(1, int(detected_pulse_count))
    if count == 1:
        pairs = [(1, 1)]
    else:
        pairs = [(pulse, pulse + 1) for pulse in range(1, count)]
    if include_pair is not None:
        off_pulse, on_pulse = (int(include_pair[0]), int(include_pair[1]))
        valid = (
            1 <= off_pulse <= count
            and 1 <= on_pulse <= count
            and on_pulse >= off_pulse
        )
        pair = (off_pulse, on_pulse)
        if valid and pair not in pairs:
            pairs.append(pair)
            pairs.sort(key=lambda item: (item[1], item[0]))
    return pairs


def dpt_export_results(
    bundle: WaveformBundle,
    profile: BridgeProfile,
    cfg: AppConfig,
    current_result: ExtractResult,
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[ExtractResult]:
    """Build the result rows that should be written for the current DPT waveform."""
    mode = parse_test_mode(cfg.test_mode.mode)
    if mode != TestMode.DPT or current_result.single_pulse_mode:
        return [current_result]
    count = int(current_result.detected_pulse_count or 0)
    if count <= 2:
        return [current_result]

    rows: list[ExtractResult] = []
    current_pair = (
        int(current_result.off_pulse_index),
        int(current_result.on_pulse_index),
    )
    pairs = dpt_export_pulse_pairs(count, include_pair=current_pair)
    for index, (off_pulse, on_pulse) in enumerate(pairs, start=1):
        if (off_pulse, on_pulse) == current_pair:
            # The selected row is the exact page result.  This preserves any
            # user-adjusted cursors/parameters instead of silently replacing
            # them with a fresh background extraction during report creation.
            rows.append(deepcopy(current_result))
        else:
            row_cfg = deepcopy(cfg)
            row_cfg.pulse_selection.off_pulse = off_pulse
            row_cfg.pulse_selection.on_pulse = on_pulse
            rows.append(run_extraction(bundle, profile, row_cfg))
        if progress_callback is not None:
            progress_callback(index, len(pairs))
    return rows
