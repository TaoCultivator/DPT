"""Pdmax owns its stable-current interval, raw maximum and manual report state."""
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
from dpt_extractor.gui.waveform_plot import _is_power_unit
from dpt_extractor.metrics import recovery_power
from dpt_extractor.models.results import SegmentIndices
from dpt_extractor.models.waveform import bundle_reverse_recovery_current
from dpt_extractor.tests.test_irr_stable_cursor_context import DATA, CASES
from dpt_extractor.tests.test_turn_on_cursor_windows import _load_mapped


@pytest.mark.parametrize("polarity", [1.0, -1.0])
@pytest.mark.parametrize("ring_end", [900, 1700])
def test_current_platforms_bracket_raw_peak_and_exclude_outside_spikes(polarity, ring_end):
    t = np.arange(3000) * 1e-9
    irr = np.full(len(t), -100.0)
    irr[600:701] = np.linspace(-100.0, 40.0, 101)
    irr[701:801] = np.linspace(40.0, 2.0, 100)
    irr[801:ring_end] = 2.0 + 20.0 * np.sin(np.arange(ring_end-801) * 0.2)
    irr[ring_end:] = 2.0
    irr *= polarity
    vd = np.ones(len(t))
    vd[720] = 1000.0
    vd[10] = vd[2600] = 1e6  # Bigger, but outside this recovery's A/B.
    segs = SegmentIndices((0, 100), (100, 2500), (620, 2400),
                          pulse1_off=50, pulse2_on=500, pulse2_off=2700)
    with patch.object(recovery_power, "default_irr_trr_measure", return_value=
                      SimpleNamespace(peak_idx=700, stable_level=2.0*polarity)):
        context = recovery_power.recovery_power_context(
            t, vd, irr, segs, 1e-9, forward_hint=-100.0*polarity
        )
    assert context is not None
    a, b = context.current_interval.a_idx, context.current_interval.b_idx
    assert 480 <= a < 600
    assert ring_end + 85 <= b <= ring_end + 120
    assert context.peak_idx == 720
    assert context.value_kw == abs(vd[720] * irr[720]) / 1000.0
    assert context.t_start == t[a] and context.t_end == t[b]


def test_missing_stable_bands_never_fall_back_to_err_window():
    with patch.object(recovery_power, "recovery_current_stable_interval", return_value=None):
        assert recovery_power.recovery_power_context(
            np.arange(10), np.ones(10), np.ones(10),
            SegmentIndices((0, 2), (3, 9), (3, 9)), 1e-9
        ) is None


def test_invalid_post_reference_cannot_select_an_unrelated_rail():
    assert recovery_power._quiet_post_reference(
        np.ones(2000), 500, 1999, 1e-9, -100.0, float("nan")
    ) is None


def test_large_peak_cannot_admit_the_next_conduction_rail_as_reference():
    current = np.full(4000, -30.0)
    current[500] = 1000.0
    current[501:1300] = 0.0
    assert recovery_power._quiet_post_reference(
        current, 500, 3999, 1e-9, -30.0, 10.0
    ) == 0.0


@pytest.mark.parametrize("polarity", [1.0, -1.0])
@pytest.mark.parametrize("settles", [False, True])
def test_ringing_biased_reference_requires_complete_quiet_bands(polarity, settles):
    t = np.arange(3000) * 1e-9
    current = np.full(len(t), -100.0)
    current[600:701] = np.linspace(-100.0, 40.0, 101)
    current[701:] = 2.0 + 20.0 * np.sin(np.arange(2299)*0.2)
    if settles:
        current[1400:2400] = 2.0
    current[2400:] = -100.0  # Later switching must not supply the post rail.
    current *= polarity
    segs = SegmentIndices((0, 100), (100, 2500), (620, 2400),
                          pulse1_off=50, pulse2_on=500, pulse2_off=2900)
    with patch.object(recovery_power, "default_irr_trr_measure", return_value=
                      SimpleNamespace(peak_idx=700, stable_level=9.0*polarity)):
        # Existing Irr semantics remain unchanged, even if Pdmax can prove a
        # different post reference from this event's later quiet bands.
        assert recovery_power.recovery_current_stable_interval(t, current, segs, 1e-9) is None
        context = recovery_power.recovery_power_context(t, np.ones(len(t)), current, segs, 1e-9)
    if settles:
        assert context is not None
        assert 1485 <= context.current_interval.b_idx <= 1520
        assert context.current_interval.post_level == 2.0*polarity
    else:
        assert context is None


@pytest.mark.parametrize("relative_path,old_kw,b_range", [
    ("vh/915v-vh-50a-6us-175c_000.tss", 26.9744970703125, (8.5, 9.2)),
    ("wl/915v-wl-50a-6.2us-175c_000.tss", 30.61783593750001, (8.8, 9.3)),
])
def test_low_current_legacy_ringing_does_not_make_power_unavailable(relative_path, old_kw, b_range):
    path = Path(__file__).resolve().parents[2] / "示例文件/likangkang/NED34jixian" / relative_path
    if not path.exists():
        pytest.skip(f"missing {path}")
    bundle, profile, result = _load_mapped(path)
    context = result.power_contexts[("反向恢复", "Pdmax")]
    assert context is not None
    assert not result.is_metric_unavailable("反向恢复", "Pdmax")
    assert b_range[0] < context.t_end*1e6 < b_range[1]
    assert result.reverse_recovery.pdmax == pytest.approx(old_kw, abs=1e-10)
    irr = bundle_reverse_recovery_current(bundle, profile)
    radius = round(90e-9 / bundle.dt)
    interval = context.current_interval
    pre_band = irr[interval.a_idx-radius:interval.a_idx+radius]
    pre_noise = np.ptp(np.percentile(pre_band, [5, 95]))
    # The legacy 50 A captures have a several-amp acquisition floor.  Bound
    # the residual spread by that measured floor and the event excursion,
    # rather than imposing an unrelated fixed 4 A threshold.
    noise_limit = max(1.5*pre_noise,
                      0.03*abs(irr[interval.current_peak_idx]-interval.pre_level))
    # Both cursors retain full settled neighbours, not a ringing crossing or
    # the return to the next event's conducting-current rail.
    for idx in (interval.a_idx, interval.b_idx):
        block = irr[idx-radius:idx+radius]
        assert np.ptp(np.percentile(block, [5, 95])) <= noise_limit
    raw = np.abs(bundle.get(profile.v_diode)[interval.a_idx:interval.b_idx]) * np.abs(
        irr[interval.a_idx:interval.b_idx])
    assert context.value_kw == np.max(raw)/1000.0


@pytest.mark.parametrize("temperature,filename", CASES + [
    ("LT", "VH_486V_150A_Rgon1.8_Rgoff6.8_000.tss"),
    ("LT", "VL_400V_30A_Rgon0.8_Rgoff5.1_000.tss"),
])
def test_real_extraction_owns_default_interval_and_raw_value(temperature, filename):
    path = DATA / temperature / filename
    if not path.exists():
        pytest.skip(f"missing {path}")
    bundle, profile, result = _load_mapped(path)
    context = result.power_contexts[("反向恢复", "Pdmax")]
    assert context is not None
    host = SimpleNamespace(bundle=bundle, profile=profile, result=result,
                           _default_cursor_context_cache={},
                           _metric_unavailable=result.is_metric_unavailable,
                           _iec_timing_interval_us=lambda *_: None)
    before = copy.deepcopy(result)
    a, b, *_ = MainWindow._rr_irr_cursor_context(host)
    assert (a, b) == (context.current_interval.a_idx, context.current_interval.b_idx)
    raw = np.abs(bundle.get(profile.v_diode)[a:b]) * np.abs(
        bundle_reverse_recovery_current(bundle, profile)[a:b])
    assert result.reverse_recovery.pdmax == np.max(raw) / 1000.0
    assert context.peak_idx == a + np.argmax(raw)
    assert MainWindow._parameter_interval_us(host, "反向恢复", "Pdmax") == (
        bundle.t[a]*1e6, bundle.t[b]*1e6
    )
    assert result == before


@pytest.fixture
def power_window(monkeypatch):
    from dpt_extractor.gui import main_window
    path = DATA / CASES[2][0] / CASES[2][1]
    if not path.exists():
        pytest.skip(f"missing {path}")
    monkeypatch.setattr(main_window, "set_last_open_path", lambda *_: None)
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win._load_file(str(path))
    win.resize(1920, 1080)
    win.show()
    app.processEvents()
    yield win
    win.close()
    app.processEvents()


def test_default_click_balances_view_and_never_recalculates(power_window):
    win = power_window
    before = copy.deepcopy(win.result)
    context = win.result.power_contexts[("反向恢复", "Pdmax")]
    with patch.object(recovery_power, "recovery_power_context", side_effect=AssertionError):
        win._on_value_clicked("反向恢复", "Pdmax")
    plot = win.wave_plot
    a, b = plot._cursor_a.value(), plot._cursor_b.value()
    assert (a, b) == (context.t_start*1e6, context.t_end*1e6)
    x0, x1 = plot.current_x_range_us()
    assert (0.5*(a+b)-x0)/(x1-x0) == pytest.approx(0.43, abs=0.01)
    assert a-x0 > 0.15 and x1-b > a-x0
    assert win.result == before
    assert not win._manual_intervals


def test_no_math_endpoints_follow_irr_and_err_cannot_overwrite_manual_power(power_window):
    win = power_window
    plot = win.wave_plot
    for key, item in plot._trace_items.items():
        if _is_power_unit(plot._unit_for_channel(key)):
            plot._hidden_channels.add(key)
            item.hide()
    win._on_value_clicked("反向恢复", "Pdmax")
    assert plot._cursor_endpoint_channel("a") == "irr"
    assert plot._cursor_endpoint_channel("b") == "irr"
    assert not plot._horizontal_cursor_binding("ha")[1]
    old_err = win.result.reverse_recovery.err
    a, b = plot._cursor_a.value(), plot._cursor_b.value()-0.02
    plot._interactive_on_change(a, b)
    manual_kw = win.result.reverse_recovery.pdmax
    assert win.result.reverse_recovery.err == old_err
    assert win._manual_intervals[("反向恢复", "Pdmax")] == (a, b)
    win._on_value_clicked("反向恢复", "Err")
    markers = win.result.energy_contexts[("反向恢复", "Err")]
    plot._interactive_on_change(markers.t_start*1e6, markers.t_end*1e6+0.05,
                                markers.ha_v, markers.hb_a)
    assert win.result.reverse_recovery.pdmax == manual_kw
    assert win._manual_intervals[("反向恢复", "Pdmax")] == (a, b)
    state = win._snapshot_report_manual_state()
    assert state["_manual_intervals"][("反向恢复", "Pdmax")] == (a, b)
    win._on_value_clicked("反向恢复", "Pdmax")
    assert (plot._cursor_a.value(), plot._cursor_b.value()) == (a, b)
    assert win.result.reverse_recovery.pdmax == manual_kw


def test_power_drag_calculates_only_on_release_and_manual_ha_survives_err(power_window, tmp_path):
    win = power_window
    plot = win.wave_plot
    vd = plot._display_key_for_channel("v_diode")
    irr = plot._display_key_for_channel("irr")
    plot._set_math_formula("MATH9", f"ABS({vd}) * ABS({irr})")
    for key, item in plot._trace_items.items():
        if key != "MATH9" and _is_power_unit(plot._unit_for_channel(key)):
            plot._hidden_channels.add(key)
            item.hide()
    win._on_value_clicked("反向恢复", "Pdmax")
    assert plot._horizontal_cursor_binding("ha") == ("MATH9", True)
    original_kw = win.result.reverse_recovery.pdmax
    original_callback = plot._interactive_on_change
    with patch.object(plot, "_interactive_on_change", wraps=original_callback) as callback:
        plot._cursor_b.moving = True
        plot._cursor_b.setValue(plot._cursor_b.value()-0.015)
        assert callback.call_count == 0
        assert win.result.reverse_recovery.pdmax == original_kw
        plot._cursor_b.moving = False
        plot._cursor_b.sigPositionChangeFinished.emit(plot._cursor_b)
        assert callback.call_count == 1
    plot._h_cursor_a.moving = True
    plot._h_cursor_a.setValue(plot._h_cursor_a.value()+0.15)
    plot._h_cursor_a.moving = False
    plot.commit_pending_interaction_for_report()
    manual_kw = win.result.reverse_recovery.pdmax
    assert manual_kw != original_kw
    assert win._snapshot_report_manual_state()["_manual_extreme_values"][
        ("反向恢复", "Pdmax")][1] == manual_kw
    win._on_value_clicked("反向恢复", "Err")
    m = win.result.energy_contexts[("反向恢复", "Err")]
    plot._interactive_on_change(m.t_start*1e6, m.t_end*1e6+0.02, m.ha_v, m.hb_a)
    win._on_value_clicked("反向恢复", "Pdmax")
    assert win.result.reverse_recovery.pdmax == manual_kw
    # Keep Pdmax inactive during recalculation/report preparation: opening its
    # card must not be required to materialize manual report values.
    win._on_value_clicked("反向恢复", "Err")
    win._recalculate(reset_manual=False)
    assert win.result.reverse_recovery.pdmax == manual_kw
    from dpt_extractor.tests.test_report_e2e_regressions import _RecordingPool
    pool = _RecordingPool()
    original_pool = win._load_pool
    try:
        win._load_pool = pool
        win._start_report_prepare_task()
        assert len(pool.tasks) == 1
        frozen = pool.tasks[0].current_result
        assert frozen.reverse_recovery.pdmax == manual_kw
        # Exercise the real report writer, only on a disposable test workbook.
        from openpyxl import load_workbook
        from dpt_extractor.export.mcu2506_layout import (
            COL_RR, DATA_ROW, build_mcu2506_workbook, fill_data_row,
        )
        from dpt_extractor.export.report_template import write_report_template
        report = tmp_path / "manual_pdmax.xlsx"
        workbook = build_mcu2506_workbook(frozen)
        workbook.active.title = "V相_双脉冲数据"
        fill_data_row(workbook.active, DATA_ROW, frozen)
        for column in (1, 2, 3):
            workbook.active.merge_cells(
                start_row=DATA_ROW, end_row=DATA_ROW+3,
                start_column=column, end_column=column,
            )
        workbook.active.cell(DATA_ROW, 1, "VL")
        workbook.active.cell(DATA_ROW, 2, "25℃")
        workbook.save(report)
        workbook.close()
        win.result.reverse_recovery.pdmax = original_kw  # Later live state cannot win.
        summary = write_report_template(frozen, report)
        saved = load_workbook(report)
        try:
            value = saved[summary.data_sheet].cell(summary.data_row, COL_RR["pdmax"]).value
            assert value == pytest.approx(round(manual_kw, 3), abs=0.0005)
        finally:
            saved.close()
    finally:
        win._report_prepare_tasks.clear()
        win._release_report_operation()
        win._load_pool = original_pool
