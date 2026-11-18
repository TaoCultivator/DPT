"""Vce_on_max display-only peak-left / settled-Base cursor regression."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.models.bridge_profile import make_profile
from dpt_extractor.models.results import ExtractResult, SegmentIndices
from dpt_extractor.models.waveform import TekMetadata, WaveformBundle


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    yield win
    win.close()
    app.processEvents()


@pytest.mark.parametrize("ringing_end", [900, 1600])
@pytest.mark.parametrize("peak_idx", [500, 740])
def test_peak_left_and_first_settled_base_are_local_and_cached(
    window, ringing_end, peak_idx
):
    dt = 1e-9
    t = np.arange(2600) * dt
    vce = np.full(len(t), 400.0)
    vce[peak_idx] = 425.0
    vce[750:801] = np.linspace(400.0, 5.0, 51)
    vce[801:ringing_end] = 5.0 + 50.0 * np.sin(
        2 * np.pi * np.arange(ringing_end - 801) / 35
    )
    vce[ringing_end:] = 5.0
    vce[2400:] = 400.0  # Next turn-off must never be used as a Base.
    window.profile = make_profile("W", "upper")
    window.bundle = WaveformBundle(
        t=t, channels={window.profile.vce: vce}, meta=TekMetadata(sample_interval=dt)
    )
    window.result = ExtractResult(
        segments=SegmentIndices(
            turn_off=(0, 100),
            turn_on=(300, 2000),
            reverse_recovery=(750, 950),
            pulse1_on=0,
            pulse1_off=100,
            pulse2_on=400,
            pulse2_off=2400,
        )
    )
    window.result.turn_on.vce_on_max = 425.0
    before = copy.deepcopy(window.result)
    old_context = (350, 1800, 5.0, 400.0)
    with (
        patch.object(
            window, "_turn_on_vce_stable_cursor_context", return_value=old_context
        ) as stable,
        patch.object(
            window, "_default_extreme_peak_point", return_value=(peak_idx, 425.0)
        ) as peak,
    ):
        context = window._turn_on_vce_on_max_cursor_context()
        assert context is not None
        a, b, base, top = context
        # 2026-11-18: default A/B is the authoritative peak +/- 300 ns inside
        # the turn-on event window [turn_on[0], pulse2_off], narrowed
        # proportionally when the peak sits close to one edge.
        dt = float(window.bundle.dt)
        half = max(1, int(round(300e-9 / dt)))
        # 2026-11-18: 物理阶段包络 ∪ 峰值 ±300ns；阶段解析由生产代码在
        # patched 旧 context 之上再细化，故只断言「两侧至少 ±300ns 且含峰值」。
        assert a <= peak_idx - half
        assert b >= peak_idx + half
        assert a < peak_idx < b
        assert (base, top) == old_context[2:]
        assert window._parameter_max_interval_indices("开通", "Vce_on_max") == (a, b)
        assert stable.call_count == 1
        assert peak.call_count == 1
        # The shared Delta Vce context is not rewritten or cached over.
        assert window._turn_on_vce_stable_cursor_context() == old_context
    assert window.result == before
    assert window._manual_intervals == {}
    assert window._manual_extreme_values == {}


def test_b_does_not_stop_at_an_isolated_base_crossing_or_falling_tail(window):
    t = np.arange(2700) * 1e-9
    vce = np.full(len(t), 400.0)
    vce[600] = 420.0
    vce[800:900] = np.linspace(400.0, 26.0, 100)
    vce[900:1700] = np.linspace(26.0, 18.0, 800)
    vce[1000:1002] = 5.0  # A lone raw Base crossing is not a plateau.
    vce[1700:] = 5.0
    window.profile = make_profile("W", "upper")
    window.bundle = WaveformBundle(
        t=t, channels={window.profile.vce: vce}, meta=TekMetadata(sample_interval=1e-9)
    )
    window.result = ExtractResult(
        segments=SegmentIndices(
            turn_off=(0, 100),
            turn_on=(300, 2200),
            reverse_recovery=(800, 1000),
            pulse1_on=0,
            pulse1_off=100,
            pulse2_on=400,
            pulse2_off=2600,
        )
    )
    with (
        patch.object(
            window,
            "_turn_on_vce_stable_cursor_context",
            return_value=(300, 1000, 5.0, 400.0),
        ),
        patch.object(window, "_default_extreme_peak_point", return_value=(600, 420.0)),
    ):
        a, b, *_ = window._turn_on_vce_on_max_cursor_context()
    # 2026-11-18: 阶段包络 ∪ 峰值 ±300ns；两侧至少 ±300ns 且含峰值。
    assert a <= 300 and b >= 900
    assert a < 600 < b
    assert np.max(vce[a : b + 1]) == 420.0


def test_peak_on_first_numeric_sample_still_has_a_strict_left_cursor(window):
    t = np.arange(1800) * 1e-9
    vce = np.full(len(t), 400.0)
    vce[500] = 425.0
    vce[700:] = 5.0
    window.profile = make_profile("W", "upper")
    window.bundle = WaveformBundle(
        t=t, channels={window.profile.vce: vce}, meta=TekMetadata(sample_interval=1e-9)
    )
    window.result = ExtractResult(
        segments=SegmentIndices(
            turn_off=(0, 100),
            turn_on=(500, 1200),
            reverse_recovery=(650, 800),
            pulse1_on=0,
            pulse1_off=100,
            pulse2_on=500,
            pulse2_off=1600,
        )
    )
    with (
        patch.object(
            window,
            "_turn_on_vce_stable_cursor_context",
            return_value=(500, 1000, 5.0, 400.0),
        ),
        patch.object(window, "_default_extreme_peak_point", return_value=(500, 425.0)),
    ):
        a, b, *_ = window._turn_on_vce_on_max_cursor_context()
    # 峰值贴在事件段起点时,阶段包络 ∪ 峰值 ±300ns 仍保证两侧有足够跨度，
    # 不再退化成几十 ns 的窄窗（P1-1）。
    assert a <= 200 and b >= 800


@pytest.mark.parametrize("current", [50, 250])
def test_zhongban_actual_cursors_highlight_and_manual_value_are_preserved(
    window, current
):
    root = Path(
        os.environ.get(
            "DPT_ZHONGBAN_ROOT",
            r"F:\JinMai\双脉冲数据处理\songzhenxi\MCU25T8\SMC\zhongban",
        )
    )
    path = root / "RT" / f"WH_400V_{current}A_Rgon4_Rgoff9_000.tss"
    if not path.exists():
        pytest.skip("zhongban RT sample missing")
    window._load_file(str(path))
    before_on = copy.deepcopy(window.result.turn_on)
    shared = window._turn_on_vce_stable_cursor_context()
    context = window._turn_on_vce_on_max_cursor_context()
    assert context is not None
    a, b, base, _top = context
    peak_idx, peak_v = window._default_extreme_peak_point("开通", "Vce_on_max")
    dt = float(window.bundle.dt)
    half = max(1, int(round(300e-9 / dt)))
    # 2026-11-18: 阶段包络 ∪ 峰值 ±300ns（阶段解析可能比 shared 更靠右）。
    assert a <= peak_idx - half
    assert b >= peak_idx + half
    assert a < peak_idx < b
    assert context[2:] == shared[2:]
    window._on_value_clicked("开通", "Vce_on_max")
    plot = window.wave_plot
    expected = tuple(window.bundle.t[[a, b]] * 1e6)
    for channel in ("ic", "vce"):
        plot._on_legend_double_clicked(plot._display_key_for_channel(channel))
        QApplication.processEvents()
        assert plot._cursor_endpoint_channel("a") == "vce"
        assert plot._cursor_endpoint_channel("b") == "vce"
        assert (plot._cursor_a.value(), plot._cursor_b.value()) == pytest.approx(expected)
        assert plot._from_disp("vce", plot._h_cursor_a.value()) == pytest.approx(peak_v)
        assert plot._from_disp("vce", plot._h_cursor_b.value()) == pytest.approx(base)
    assert window.result.turn_on == before_on
    assert window._turn_on_vce_stable_cursor_context() == shared
    # Real horizontal-release path must retain the user's override on return.
    plot._h_cursor_a.setValue(plot._to_disp("vce", peak_v + 17.0))
    plot._h_cursor_a.sigPositionChangeFinished.emit(plot._h_cursor_a)
    QApplication.processEvents()
    assert window.result.turn_on.vce_on_max == pytest.approx(peak_v + 17.0)
    window._on_value_clicked("开通", "Ic_on_max")
    window._on_value_clicked("开通", "Vce_on_max")
    assert window.result.turn_on.vce_on_max == pytest.approx(peak_v + 17.0)
    assert (plot._cursor_a.value(), plot._cursor_b.value()) == pytest.approx(expected)
    assert plot._from_disp("vce", plot._h_cursor_a.value()) == pytest.approx(peak_v + 17.0)
