"""Irr display endpoints must bracket quiet stages, never redefine the peak."""
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
from dpt_extractor.metrics.plateau_level import recovery_stable_cursor_range_indices
from dpt_extractor.models.waveform import bundle_reverse_recovery_current
from dpt_extractor.tests.test_turn_on_cursor_windows import _load_mapped


@pytest.mark.parametrize("polarity", [1.0, -1.0])
@pytest.mark.parametrize("ring_end", [900, 1700])
def test_adjacent_platforms_follow_actual_ringing_not_fixed_tail(polarity, ring_end):
    current = np.full(3000, -100.0)
    current[600:701] = np.linspace(-100.0, 40.0, 101)
    current[701:801] = np.linspace(40.0, 2.0, 100)
    current[801:ring_end] = 2.0 + 20.0 * np.sin(np.arange(ring_end-801) * 0.2)
    current[ring_end:] = 2.0
    current[2700:] = -100.0  # Next event is excluded.
    current *= polarity
    before = current.copy()
    pair = recovery_stable_cursor_range_indices(
        current, 100, 700, 2650, 1e-9, -100.0*polarity, 2.0*polarity
    )
    assert pair is not None
    a, b = pair
    assert 480 <= a < 600
    assert ring_end + 85 <= b <= ring_end + 120
    assert a < 700 < b < 2700
    assert current[a] == -100.0*polarity
    assert current[b] == 2.0*polarity
    np.testing.assert_array_equal(current, before)


def test_temporary_quiet_gap_does_not_end_ringing():
    current = np.full(2800, -100.0)
    current[500:601] = np.linspace(-100.0, 40.0, 101)
    current[601:750] = np.linspace(40.0, 2.0, 149)
    current[750:] = 2.0
    current[960:1300] += 25.0*np.sin(np.arange(340)*0.2)
    pair = recovery_stable_cursor_range_indices(
        current, 100, 600, 2500, 1e-9, -100.0, 2.0
    )
    assert pair is not None
    assert 1380 <= pair[1] <= 1430


@pytest.mark.parametrize("missing_reference", [False, True])
def test_low_current_noise_floor_does_not_hide_real_settled_bands(missing_reference):
    rng = np.random.default_rng(20260919)
    current = np.full(2600, -40.0) + rng.normal(0.0, 7.0, 2600)
    current[600:701] = np.linspace(-40.0, 200.0, 101)
    current[701:801] = np.linspace(200.0, 0.0, 100)
    current[801:1300] = 80.0 * np.sin(np.arange(499) * 0.2)
    current[1300:] = rng.normal(0.0, 7.0, 1300)
    if missing_reference:
        current[100:110] = np.nan
    pair = recovery_stable_cursor_range_indices(
        current, 100, 700, 2450, 1e-9, -40.0, 0.0
    )
    assert pair is not None
    assert 300 <= pair[0] < 600
    assert 1380 <= pair[1] < 1600


@pytest.mark.parametrize("problem", ["short_pre", "short_post", "nan_tail", "nan_peak", "never_settles", "same_level"])
def test_incomplete_platform_evidence_never_chooses_least_bad_band(problem):
    current = np.full(1600, -100.0)
    current[600:701] = np.linspace(-100.0, 40.0, 101)
    current[701:] = 2.0
    start, end, post = 100, 1500, 2.0
    if problem == "short_pre":
        start = 550
    elif problem == "short_post":
        end = 820
    elif problem == "nan_tail":
        current[701:] = np.nan
    elif problem == "nan_peak":
        current[700] = np.nan
    elif problem == "never_settles":
        current[701:] += 30.0*np.sin(np.arange(899)*0.1)
    elif problem == "same_level":
        post = -100.0
    assert recovery_stable_cursor_range_indices(
        current, start, 700, end, 1e-9, -100.0, post
    ) is None


DATA = Path(os.environ.get("DPT_TEST_ZHONGBAN2", r"F:\JinMai\双脉冲数据处理\songzhenxi\MCU25T8\SMC\zhongban2"))
CASES = [
    ("HT", "VH_400V_1070A_Rgon1.8_Rgoff6.8_000.tss"),
    ("LT", "VL_486V_950A_Rgon0.8_Rgoff5.1_000.tss"),
    ("RT", "VL_486V_950A_Rgon0.8_Rgoff5.1_000.tss"),
]


@pytest.mark.parametrize("temperature,filename", CASES)
def test_real_cursor_precedes_rr_segment_without_changing_values(temperature, filename):
    path = DATA / temperature / filename
    if not path.exists():
        pytest.skip(f"missing {path}")
    bundle, profile, result = _load_mapped(path)
    host = SimpleNamespace(bundle=bundle, profile=profile, result=result,
                           _default_cursor_context_cache={})
    before = copy.deepcopy(result)
    context = MainWindow._rr_irr_cursor_context(host)
    assert context is not None
    a, b, post, peak, signed_peak = context
    irr = bundle_reverse_recovery_current(bundle, profile)
    pre = result.didt_contexts[("反向恢复", "di/dt")].forward_a
    span = abs(pre-post)
    assert a < result.segments.reverse_recovery[0] < peak < b < result.segments.pulse2_off
    assert abs(irr[a]-pre) < 0.02*span
    radius = round(95e-9 / bundle.dt)
    for index in (a, b):
        band = irr[index-radius:index+radius]
        assert np.ptp(np.percentile(band, [5,95])) < 0.031*span
    assert abs(signed_peak) == result.reverse_recovery.irr
    assert result == before
    assert MainWindow._rr_irr_cursor_context(host) is context


@pytest.mark.parametrize("temperature,filename,max_delay_ns", [
    ("RT", "VL_486V_50A_Rgon0.8_Rgoff5.1_000.tss", 400),
    ("LT", "VH_486V_30A_Rgon1.8_Rgoff6.8_000.tss", 1200),
])
def test_real_low_current_noise_keeps_stable_range_and_peak_separate(
    temperature, filename, max_delay_ns
):
    path = DATA / temperature / filename
    if not path.exists():
        pytest.skip(f"missing {path}")
    bundle, profile, result = _load_mapped(path)
    host = SimpleNamespace(bundle=bundle, profile=profile, result=result,
                           _default_cursor_context_cache={})
    before = copy.deepcopy(result)
    context = MainWindow._rr_irr_cursor_context(host)
    assert context is not None
    a, b, post, peak, signed_peak = context
    assert a < result.segments.reverse_recovery[0] < peak < b
    assert bundle.t[b] - bundle.t[peak] < max_delay_ns * 1e-9
    irr = bundle_reverse_recovery_current(bundle, profile)
    pre = result.didt_contexts[("反向恢复", "di/dt")].forward_a
    radius = round(95e-9 / bundle.dt)
    for index, level in ((a, pre), (b, post)):
        band = irr[index-radius:index+radius]
        reference = irr[index+radius:index+3*radius] if index == b else irr[index-3*radius:index-radius]
        noise = np.ptp(np.percentile(reference, [5, 95]))
        assert abs(np.median(band) - level) < 0.5 * noise
        assert np.ptp(np.percentile(band, [5, 95])) < 1.5 * noise
    assert abs(signed_peak) == result.reverse_recovery.irr
    assert result == before


@pytest.mark.parametrize("voltage", [400, 486])
def test_low_current_didt_hint_cannot_replace_irr_pre_edge_samples(voltage):
    path = DATA / "LT" / f"VL_{voltage}V_30A_Rgon0.8_Rgoff5.1_000.tss"
    if not path.exists():
        pytest.skip(f"missing {path}")
    bundle, profile, result = _load_mapped(path)
    host = SimpleNamespace(bundle=bundle, profile=profile, result=result,
                           _default_cursor_context_cache={})
    before = copy.deepcopy(result)
    context = MainWindow._rr_irr_cursor_context(host)
    assert context is not None
    a, b, _post, peak, signed_peak = context
    irr = bundle_reverse_recovery_current(bundle, profile)
    radius = round(95e-9 / bundle.dt)
    assert a < result.segments.reverse_recovery[0] < peak < b
    assert np.median(irr[a-radius:a+radius]) < -15.0
    assert abs(np.median(irr[b-radius:b+radius])) < 5.0
    assert 250e-9 < bundle.t[b] - bundle.t[peak] < 900e-9
    assert abs(signed_peak) == result.reverse_recovery.irr
    assert result == before


def test_real_card_highlight_reentry_and_manual_release_preserve_ownership(monkeypatch):
    path = DATA / CASES[2][0] / CASES[2][1]
    if not path.exists():
        pytest.skip(f"missing {path}")
    from dpt_extractor.gui import main_window
    from scripts.validate_gui_cursors import _audit_state_snapshot
    monkeypatch.setattr(main_window, "set_last_open_path", lambda *_: None)
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        win._load_file(str(path))
        win.show()
        app.processEvents()
        before = _audit_state_snapshot(win.result)
        win._on_value_clicked("反向恢复", "Irr")
        plot = win.wave_plot
        a, b = plot._cursor_a.value(), plot._cursor_b.value()
        plot._on_legend_double_clicked(win.profile.vge)
        assert _audit_state_snapshot(win.result) == before
        assert (plot._cursor_a.value(), plot._cursor_b.value()) == (a, b)
        win._on_value_clicked("开通", "Ton")
        win._on_value_clicked("反向恢复", "Irr")
        assert (plot._cursor_a.value(), plot._cursor_b.value()) == (a, b)
        assert _audit_state_snapshot(win.result) == before
        assert ("反向恢复", "Irr") not in win._manual_intervals
        manual_a = a - 0.025
        with patch.object(win, "_irr_peak_index_interactive", wraps=win._irr_peak_index_interactive) as recalculate:
            with patch.object(plot, "_cursor_sender_is_dragging", return_value=True):
                plot._cursor_a.setPos(a - 0.010)
                plot._cursor_a.setPos(manual_a)
            recalculate.assert_not_called()
            assert ("反向恢复", "Irr") not in win._manual_intervals
            plot._on_any_cursor_drag_finished()
            recalculate.assert_called_once()
        assert win._manual_intervals[("反向恢复", "Irr")] == pytest.approx((manual_a, b))
        manual_ha = plot._from_disp("irr", plot._h_cursor_a.value()) + 0.75
        plot._h_cursor_a.setValue(plot._to_disp("irr", manual_ha))
        app.processEvents()
        win._on_value_clicked("开通", "Ton")
        win._on_value_clicked("反向恢复", "Irr")
        assert (plot._cursor_a.value(), plot._cursor_b.value()) == pytest.approx((manual_a, b))
        assert plot._from_disp("irr", plot._h_cursor_a.value()) == pytest.approx(manual_ha)
        default_irr = win.result.reverse_recovery.irr
        context = win._rr_irr_cursor_context()
        assert context is not None
        manual_b = win.bundle.t[context[3]] * 1e6 - 0.010
        plot._cursor_b.setValue(manual_b)
        app.processEvents()
        manual_irr = win.result.reverse_recovery.irr
        assert manual_irr != pytest.approx(default_irr)
        win._on_value_clicked("开通", "Ton")
        win._on_value_clicked("反向恢复", "Irr")
        assert win.result.reverse_recovery.irr == pytest.approx(manual_irr)
        assert (plot._cursor_a.value(), plot._cursor_b.value()) == pytest.approx((manual_a, manual_b))
        page = win._current_report_page_state()
        assert page.result.reverse_recovery.irr == pytest.approx(manual_irr)
        assert page.manual_state["_manual_intervals"][("反向恢复", "Irr")] == pytest.approx((manual_a, manual_b))
        assert page.manual_state["_manual_extreme_references"][("反向恢复", "Irr")][0] == pytest.approx(manual_ha)
    finally:
        win.close()
        app.processEvents()
