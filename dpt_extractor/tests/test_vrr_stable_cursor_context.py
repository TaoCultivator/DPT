"""Vrr display endpoints require genuine pre-rise/post-ringing platforms."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.metrics.slopes import DvdtMeasurementContext
from dpt_extractor.models.bridge_profile import make_profile
from dpt_extractor.models.results import ExtractResult, SegmentIndices
from dpt_extractor.models.waveform import TekMetadata, WaveformBundle


def _host(ring_end=1300, *, temporary_gap=False, incomplete=False):
    dt = 1e-9
    voltage = np.full(4200, 5.0)
    voltage[600:701] = np.linspace(5.0, 550.0, 101)
    voltage[701:801] = np.linspace(550.0, 400.0, 100)
    voltage[801:ring_end] = 400.0 + 60.0 * np.sin(np.arange(ring_end - 801) * 0.2)
    voltage[ring_end:] = 400.0
    if temporary_gap:
        voltage[801:1030] = 400.0
    if incomplete:
        voltage[801:3900] = 400.0 + 80.0 * np.sin(np.arange(3099) * 0.2)
    voltage[3900:] = 900.0  # Unrelated next event must not supply a platform.
    profile = make_profile("W", "upper")
    bundle = WaveformBundle(
        t=np.arange(len(voltage)) * dt,
        channels={profile.v_diode: voltage},
        meta=TekMetadata(sample_interval=dt),
    )
    result = ExtractResult(segments=SegmentIndices(
        turn_off=(0, 100), turn_on=(650, 1900), reverse_recovery=(680, 850),
        pulse1_on=0, pulse1_off=100, pulse2_on=500, pulse2_off=3900,
    ))
    result.reverse_recovery.vrr = 550.0
    result.dvdt_contexts[("反向恢复", "dv/dt")] = DvdtMeasurementContext(
        base_v=5.0, top_v=400.0, crossing=None,
    )
    return SimpleNamespace(bundle=bundle, profile=profile, result=result,
                           _default_cursor_context_cache={})


@pytest.mark.parametrize("ring_end", [1050, 2400])
def test_vrr_uses_nearest_complete_base_and_first_settled_top(ring_end):
    host = _host(ring_end)
    before = copy.deepcopy(host.result)
    context = MainWindow._rr_vrr_cursor_context(host)
    assert context is not None
    a, b, top = context
    assert 480 <= a < 600  # Not clipped to turn_on[0] inside the rise.
    assert ring_end + 85 <= b <= ring_end + 120
    assert a < 700 < b < host.result.segments.pulse2_off
    voltage = host.bundle.get(host.profile.v_diode)
    assert np.ptp(voltage[a-90:a+90]) == 0.0
    assert np.ptp(voltage[b-90:b+90]) == 0.0
    assert (voltage[a], voltage[b], top) == (5.0, 400.0, 400.0)
    assert host.result == before
    assert MainWindow._rr_vrr_cursor_context(host) is context


def test_vrr_temporary_quiet_gap_cannot_hide_later_rebound():
    host = _host(1500, temporary_gap=True)
    context = MainWindow._rr_vrr_cursor_context(host)
    assert context is not None
    assert 1585 <= context[1] <= 1620


def test_vrr_missing_stable_top_does_not_select_least_bad_ringing():
    host = _host(incomplete=True)
    assert MainWindow._rr_vrr_cursor_context(host) is None


@pytest.mark.parametrize("ring_end", [2400, 3900])
def test_vrr_sustained_moderate_ringing_cannot_set_its_own_noise_floor(ring_end):
    host = _host()
    voltage = host.bundle.get(host.profile.v_diode)
    voltage[801:ring_end] = 400.0 + 20.0 * np.sin(np.arange(ring_end - 801) * 0.2)
    voltage[ring_end:3900] = 400.0
    context = MainWindow._rr_vrr_cursor_context(host)
    if ring_end == 3900:
        assert context is None
    else:
        assert context is not None
        assert ring_end + 85 <= context[1] <= ring_end + 120


@pytest.mark.parametrize("missing_band", ["base", "top", "peak", "short_base"])
def test_vrr_missing_or_nonfinite_evidence_is_not_a_stable_platform(missing_band):
    host = _host()
    voltage = host.bundle.get(host.profile.v_diode)
    if missing_band == "base":
        voltage[:600] = np.nan
    elif missing_band == "top":
        voltage[801:] = np.nan
    elif missing_band == "peak":
        voltage[650:1900] = np.nan
    else:
        host.result.segments.pulse1_off = 540
    assert MainWindow._rr_vrr_cursor_context(host) is None


DATA = Path(os.environ.get("DPT_TEST_ZHONGBAN2", r"F:\JinMai\双脉冲数据处理\songzhenxi\MCU25T8\SMC\zhongban2"))
CASES = [
    ("HT", "VH_400V_1070A_Rgon1.8_Rgoff6.8_000.tss"),
    ("LT", "VL_486V_950A_Rgon0.8_Rgoff5.1_000.tss"),
    ("RT", "VL_486V_950A_Rgon0.8_Rgoff5.1_000.tss"),
    ("LT", "VH_486V_30A_Rgon1.8_Rgoff6.8_000.tss"),
]


@pytest.mark.parametrize("temperature,filename", CASES)
def test_real_vrr_bands_preserve_peak_horizontal_levels_and_result(temperature, filename):
    from dpt_extractor.tests.test_turn_on_cursor_windows import _load_mapped
    path = DATA / temperature / filename
    if not path.exists():
        pytest.skip(f"missing {path}")
    bundle, profile, result = _load_mapped(path)
    host = SimpleNamespace(bundle=bundle, profile=profile, result=result,
                           _default_cursor_context_cache={})
    before = copy.deepcopy(result)
    context = MainWindow._rr_vrr_cursor_context(host)
    assert context is not None
    a, b, top = context
    voltage = bundle.get(profile.v_diode)
    slope = result.dvdt_contexts[("反向恢复", "dv/dt")]
    span = slope.top_v - slope.base_v
    i0, i1 = result.segments.turn_on
    peak = i0 + int(np.argmax(voltage[i0:i1]))
    assert a < peak < b < result.segments.pulse2_off
    radius = round(95e-9 / bundle.dt)
    for index, level in ((a, slope.base_v), (b, slope.top_v)):
        band = np.abs(voltage[index-radius:index+radius])
        assert abs(np.median(band) - level) < 0.04 * span
        assert np.ptp(np.percentile(band, [5, 95])) < 0.035 * span
    assert top == slope.top_v
    assert result == before


def test_real_vrr_default_reentry_manual_release_and_report_keep_user_values(monkeypatch):
    path = DATA / CASES[2][0] / CASES[2][1]
    if not path.exists():
        pytest.skip(f"missing {path}")
    from dpt_extractor.gui import main_window
    from scripts.validate_gui_cursors import _audit_state_snapshot

    monkeypatch.setattr(main_window, "set_last_open_path", lambda *_: None)
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    key = ("反向恢复", "Vrr")
    try:
        win._load_file(str(path))
        win.showMaximized()
        app.processEvents()
        before = _audit_state_snapshot(win.result)
        win._on_value_clicked(*key)
        plot = win.wave_plot
        a, b = plot._cursor_a.value(), plot._cursor_b.value()
        plot._on_legend_double_clicked(win.profile.vge)
        assert _audit_state_snapshot(win.result) == before
        assert (plot._cursor_a.value(), plot._cursor_b.value()) == (a, b)
        win._on_value_clicked("反向恢复", "Trr")
        win._on_value_clicked(*key)
        assert (plot._cursor_a.value(), plot._cursor_b.value()) == (a, b)
        assert _audit_state_snapshot(win.result) == before
        assert key not in win._manual_intervals

        manual_a = a - 0.025
        with patch.object(win, "_recompute_param_from_interval", wraps=win._recompute_param_from_interval) as recalculate:
            with patch.object(plot, "_cursor_sender_is_dragging", return_value=True):
                plot._cursor_a.setPos(a - 0.010)
                plot._cursor_a.setPos(manual_a)
            recalculate.assert_not_called()
            assert key not in win._manual_intervals
            plot._on_any_cursor_drag_finished()
            recalculate.assert_called_once()
        assert win._manual_intervals[key] == pytest.approx((manual_a, b))
        channel = win.profile.v_diode
        manual_ha = plot._from_disp(channel, plot._h_cursor_a.value()) + 3.0
        manual_hb = plot._from_disp(channel, plot._h_cursor_b.value()) - 2.0
        plot._h_cursor_a.setValue(plot._to_disp(channel, manual_ha))
        plot._h_cursor_b.setValue(plot._to_disp(channel, manual_hb))
        app.processEvents()
        win._on_value_clicked("反向恢复", "Trr")
        win._on_value_clicked(*key)
        assert (plot._cursor_a.value(), plot._cursor_b.value()) == pytest.approx((manual_a, b))
        assert plot._from_disp(channel, plot._h_cursor_a.value()) == pytest.approx(manual_ha)
        assert plot._from_disp(channel, plot._h_cursor_b.value()) == pytest.approx(manual_hb)
        assert win.result.reverse_recovery.vrr == pytest.approx(manual_ha)
        page = win._current_report_page_state()
        assert page.result.reverse_recovery.vrr == pytest.approx(manual_ha)
        assert page.manual_state["_manual_intervals"][key] == pytest.approx((manual_a, b))
        assert page.manual_state["_manual_extreme_values"][key] == pytest.approx((manual_ha, manual_ha))
        assert page.manual_state["_manual_extreme_references"][key] == pytest.approx((manual_ha, manual_hb))
    finally:
        win.close()
        app.processEvents()


def test_real_vrr_audit_rejects_peak_as_top_even_when_context_agrees(monkeypatch):
    path = DATA / CASES[2][0] / CASES[2][1]
    if not path.exists():
        pytest.skip(f"missing {path}")
    from dpt_extractor.gui import main_window
    from scripts.validate_gui_cursors import audit_file

    original = MainWindow._rr_vrr_cursor_context

    def peak_instead_of_top(win):
        context = original(win)
        if context is None:
            return None
        i0, i1 = win.result.segments.turn_on
        voltage = win.bundle.get(win.profile.v_diode)
        peak = i0 + int(np.argmax(voltage[i0:i1]))
        return context[0], peak, context[2]

    monkeypatch.setenv("DPT_VALIDATE_CURSOR_METRIC", "反向恢复/Vrr")
    monkeypatch.setenv("DPT_VALIDATE_FOCUS_ONLY", "0")
    monkeypatch.setattr(main_window, "set_last_open_path", lambda *_: None)
    monkeypatch.setattr(MainWindow, "_rr_vrr_cursor_context", peak_instead_of_top)
    app = QApplication.instance() or QApplication([])
    rows = audit_file(MainWindow, QApplication, app, path)
    vrr_rows = [row for row in rows if row[1:3] == ("反向恢复", "Vrr")]
    assert len(vrr_rows) == 1
    assert vrr_rows[0][3] == "FAIL"
    assert "Vrr B周围电压带仍有振荡或偏离稳定平台" in vrr_rows[0][4]
