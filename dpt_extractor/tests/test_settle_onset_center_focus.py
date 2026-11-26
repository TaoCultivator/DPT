from __future__ import annotations

import math
import os
import sys
from copy import deepcopy
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from dpt_extractor.config.loader import load_config
from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.gui.waveform_plot import (
    PARAM_FOCUS_EVENT_CENTER_FRACTION,
    WaveformPlot,
)
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import guess_profile_from_path, make_profile
from dpt_extractor.models.channel_mapping import apply_mapping, infer_mapping_from_bundle
from dpt_extractor.pipeline.extract import extract_all


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "MCU24N9"
    / "10B2"
    / "SMC"
    / "RT"
    / "UH_RT_459V_750A_000.tss"
)
TARGET_CARDS = (
    ("开通", "Vce_on_max"),
    ("开通", "Ic_on_max"),
    ("关断过程", "Vce_off_max"),
    ("关断过程", "Ic_off_max"),
)

pytestmark = pytest.mark.usefixtures("isolate_qsettings_root", "reset_production_qsettings")


def test_default_focus_centers_settle_onset_and_keeps_extract_result() -> None:
    if not SAMPLE.is_file():
        pytest.skip(f"songzhenxi 样例缺失: {SAMPLE}")

    app = QApplication.instance() or QApplication(sys.argv)
    cfg = load_config()
    bundle = load_waveform(SAMPLE)
    guessed = guess_profile_from_path(SAMPLE.name)
    profile = make_profile(guessed.phase, guessed.bridge)
    inferred = infer_mapping_from_bundle(bundle, guessed.bridge)
    if inferred is not None:
        profile = apply_mapping(profile, inferred)
    result = extract_all(bundle, profile, cfg)
    result_before_focus = deepcopy(result)

    plot = WaveformPlot()
    plot.plot_waveforms(bundle, profile, result)
    win = MainWindow()
    try:
        win.bundle = bundle
        win.profile = profile
        win.result = result
        win.cfg = cfg
        win.wave_plot = plot
        win.result_table.set_result(result)

        for section, name in TARGET_CARDS:
            settle_onset_us = win._settle_onset_us(section, name)
            assert settle_onset_us is not None, f"{section}-{name} 缺少回落起点"
            assert math.isfinite(settle_onset_us), f"{section}-{name} 回落起点非有限值"

            win._on_value_clicked(section, name)
            QApplication.processEvents()

            x_range = plot.current_x_range_us()
            assert x_range is not None, f"{section}-{name} 未生成默认局部视窗"
            x0, x1 = map(float, x_range)
            span_us = x1 - x0
            assert span_us > 0.0, f"{section}-{name} 视窗跨度无效"
            onset_fraction = (settle_onset_us - x0) / span_us
            assert onset_fraction == pytest.approx(
                PARAM_FOCUS_EVENT_CENTER_FRACTION,
                abs=0.01,
            ), f"{section}-{name} 回落起点不在 50%±1%: {onset_fraction:.3%}"

            interval = win._parameter_interval_us(section, name)
            assert interval is not None, f"{section}-{name} 缺少 A/B 区间"
            a_us, b_us = sorted(map(float, interval))
            assert x0 <= a_us <= x1, f"{section}-{name} A 不在默认视窗内"
            assert x0 <= b_us <= x1, f"{section}-{name} B 不在默认视窗内"
            assert result == result_before_focus, f"{section}-{name} 取景改变了 ExtractResult"
    finally:
        win.close()
        plot.close()
        app.processEvents()
