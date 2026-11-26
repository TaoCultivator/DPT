"""Crosstalk display endpoints must not redefine the measured extrema."""

from __future__ import annotations

import copy
import os
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.models.bridge_profile import make_profile
from dpt_extractor.models.results import ExtractResult, SegmentIndices
from dpt_extractor.models.waveform import TekMetadata, WaveformBundle


@pytest.mark.parametrize(
    "values,expected",
    [
        ([99, -8, -4, -8, -12, -8, -99], (2, 4)),
        ([99, -8, -12, -8, -4, -8, -99], (2, 4)),
        ([99, -4, -8, -8, -4, -12, -8, -4, -99], (4, 5)),
        ([99, -12, -8, -8, -12, -4, -8, -12, -99], (4, 5)),
    ],
)
def test_extrema_use_half_open_event_and_closest_equal_pair(values, expected):
    """2026-11-18: 默认窗口从「最近极值对」放宽到 ≥50ns，但仍须覆盖极值。"""
    t = 10e-6 + np.arange(len(values)) * 2e-9
    owner = SimpleNamespace(bundle=SimpleNamespace(t=t))
    actual = MainWindow._crosstalk_extrema_cursor_window(
        owner, (1, len(values) - 1), np.asarray(values)
    )
    assert actual is not None
    a_us, b_us = actual
    lo_idx = int(np.searchsorted(t, min(a_us, b_us) * 1e-6, side="left"))
    hi_idx = int(np.searchsorted(t, max(a_us, b_us) * 1e-6, side="left"))
    section = np.asarray(values)[1 : len(values) - 1]
    window = np.asarray(values)[lo_idx : hi_idx + 1]
    # 事件段内极值必须仍被默认窗口覆盖（数值不变）。
    assert float(np.max(window)) == float(np.max(section))
    assert float(np.min(window)) == float(np.min(section))
    # 最小显示跨度：≥50ns，但不超过事件段本身长度。
    section_span_ns = abs(float(t[len(values) - 2] - t[1])) * 1e9
    assert abs(b_us - a_us) * 1e3 >= min(50.0, section_span_ns) - 1e-6
    # 仍须包住原「最近极值对」两个采样点。
    pair_lo, pair_hi = sorted(expected)
    assert lo_idx <= pair_lo and pair_hi <= hi_idx


@pytest.mark.parametrize("values", [[], [-8], [-8, -8], [-8, np.nan], [-8, np.inf]])
def test_degenerate_event_does_not_fabricate_extrema(values):
    owner = SimpleNamespace(bundle=SimpleNamespace(t=np.arange(len(values)) * 1e-9))
    assert MainWindow._crosstalk_extrema_cursor_window(
        owner, (0, len(values)), np.asarray(values)
    ) is None


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.profile = make_profile("W", "upper")
    t = 10e-6 + np.arange(101) * 2e-9
    values = np.full(t.size, -8.0)
    values[[35, 50, 65]] = [-4.0, -10.0, -12.0]
    values[[19, 80]] = [99.0, -99.0]  # Outside [20, 80): never measured.
    channels = {
        ch: np.zeros(t.size)
        for ch in win.profile.all_channels()
        if ch
    }
    channels[win.profile.vge_other] = values
    win.bundle = WaveformBundle(t=t, channels=channels, meta=TekMetadata(sample_interval=2e-9))
    win.result = ExtractResult(
        segments=SegmentIndices(turn_off=(20, 80), turn_on=(20, 80), reverse_recovery=(20, 80))
    )
    for state in (win.result.turn_off, win.result.turn_on):
        state.crosstalk_v = state.crosstalk_vmax = -4.0
        state.crosstalk_vmin = -12.0
    win.result_table.set_result(win.result)
    win.wave_plot.plot_waveforms(win.bundle, win.profile, win.result)
    yield win
    win.close()
    app.processEvents()


@pytest.mark.parametrize("section", ["关断过程", "开通"])
def test_default_display_does_not_recalculate_and_focus_uses_real_extrema(window, section):
    before = copy.deepcopy(window.result)
    t = window.bundle.t
    index_interval = (20, 80)
    vge_other = np.asarray(window.bundle.get(window.profile.vge_other), dtype=float)
    with (
        patch("dpt_extractor.gui.main_window.crosstalk_extrema") as calculate,
        patch.object(window, "_focus_switching_local_view") as focus,
    ):
        window._enable_crosstalk_interaction(section)
        calculate.assert_not_called()
        focus.assert_called_once()
    args = focus.call_args.args
    assert args[0] == section
    a_us, b_us = float(args[1]), float(args[2])
    # 2026-11-19（R-XT）：独立核对几何约束——A 在段内最早极值之前、B 在最晚极值
    # 之后、两端都是事件段内的原始采样、跨度 >=100ns，且取景用的就是这对时刻。
    t_us = np.asarray(t, dtype=float) * 1e6
    segment = np.asarray(vge_other[20:80], dtype=float)
    arg_max = int(np.argmax(segment))
    arg_min = int(np.argmin(segment))
    earliest_us = float(t_us[20 + min(arg_max, arg_min)])
    latest_us = float(t_us[20 + max(arg_max, arg_min)])
    eps_us = 1e-9
    assert a_us < earliest_us - eps_us
    assert b_us > latest_us + eps_us
    # 20ns 最小外侧偏移，100ns 最小跨度（单位：us）
    assert a_us <= earliest_us - 0.020 + eps_us
    assert b_us >= latest_us + 0.020 - eps_us
    assert float(t_us[20]) <= a_us < b_us <= float(t_us[79])
    assert b_us - a_us >= 0.100 - eps_us
    assert a_us == float(window.wave_plot._cursor_a.value())
    assert b_us == float(window.wave_plot._cursor_b.value())
    assert window.result == before
    assert window._manual_intervals == {}
    plot = window.wave_plot
    assert plot._from_disp("vge_other", plot._h_cursor_a.value()) == pytest.approx(-4.0)
    assert plot._from_disp("vge_other", plot._h_cursor_b.value()) == pytest.approx(-12.0)


@pytest.mark.parametrize("section", ["关断过程", "开通"])
@pytest.mark.parametrize("commit_at_report", [False, True])
def test_manual_drag_commits_once_then_restores_without_recalculation(window, section, commit_at_report):
    from dpt_extractor.metrics.derived import crosstalk_extrema

    window._enable_crosstalk_interaction(section)
    plot = window.wave_plot
    state = window.result.turn_off if section == "关断过程" else window.result.turn_on
    # 默认 A 由事件起点给出（R-XT）；B 拖到 -10V 采样点。
    default_a_us = float(plot._cursor_a.value())
    # Exclude the -12V trough, keeping the -10V trough at an exact sample time.
    ta, tb = default_a_us, float(window.bundle.t[50] * 1e6)
    with patch("dpt_extractor.gui.main_window.crosstalk_extrema", wraps=crosstalk_extrema) as calculate:
        with patch.object(plot, "_cursor_sender_is_dragging", return_value=True):
            for idx in (60, 55, 50):
                plot._cursor_b.setPos(float(window.bundle.t[idx] * 1e6))
        calculate.assert_not_called()
        assert state.crosstalk_vmin == -12.0
        if commit_at_report:
            window._commit_report_submission_state()
            window._commit_report_submission_state()
        else:
            plot._on_any_cursor_drag_finished()
        calculate.assert_called_once()
        assert (state.crosstalk_vmax, state.crosstalk_vmin, state.crosstalk_v) == (-4.0, -10.0, -4.0)
        assert window._manual_intervals[(section, "串扰电压")] == (ta, tb)

        other = "开通" if section == "关断过程" else "关断过程"
        window._enable_crosstalk_interaction(other)
        window._enable_crosstalk_interaction(section)
        calculate.assert_called_once()
    assert (plot._cursor_a.value(), plot._cursor_b.value()) == (ta, tb)
    assert plot._from_disp("vge_other", plot._h_cursor_b.value()) == pytest.approx(-10.0)
    assert state.crosstalk_vmin == -10.0
    page = window._current_report_page_state()
    report_state = page.result.turn_off if section == "关断过程" else page.result.turn_on
    assert report_state.crosstalk_vmin == -10.0
    assert page.manual_state["_manual_intervals"][(section, "串扰电压")] == (ta, tb)
