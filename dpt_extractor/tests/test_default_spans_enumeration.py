"""Enumeration gate for the shared default A/B span rule (2026-11-18).

Every extreme/peak card must place its default A/B interval with the shared
helper so that:

- the interval contains the authoritative peak and is centred on it (
  ``peak -+ 300ns``), widened by the card's physical stage envelope when the
  card also expresses a stage;
- the maximum inside the interval equals the published (authoritative) value,
  i.e. only the display interval changed;
- the cursors keep at least 10% margin from the local view edges.

A newly added extreme card that forgets to call the helper fails here.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt6.QtWidgets import QApplication

from types import SimpleNamespace

from dpt_extractor.metrics.default_spans import (
    DEFAULT_EXTREME_HALF_SPAN_S,
    extreme_display_span_indices,
    stage_union_span_indices,
)


ROOT = Path(__file__).resolve().parents[2]
SMC_RT_UH_1048 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "RT"
    / "UH_750V_1048A_000.tss"
)

# (section, name) -> signal kind used for the numeric invariance check
EXTREME_CARDS = {
    ("关断过程", "Ic_off_max"): "ic_abs",
    ("关断过程", "Vce_off_max"): "vce",
    ("开通", "Ic_on_max"): "ic_abs",
    ("开通", "Vce_on_max"): "vce",
    ("反向恢复", "Vrr"): "vd",
    ("反向恢复", "Irr"): "irr_abs",
}


class TestSharedSpanHelpers:
    def test_half_span_is_300ns_quantized_by_dt(self) -> None:
        offset = int(round(DEFAULT_EXTREME_HALF_SPAN_S / 8e-11))
        assert offset == 3750
        assert extreme_display_span_indices(10_000, 0, 20_000, 8e-11) == (
            10_000 - offset,
            10_000 + offset,
        )

    def test_narrows_proportionally_when_peak_touches_an_edge(self) -> None:
        assert extreme_display_span_indices(880, 0, 1000, 1e-9) == (760, 1000)
        assert extreme_display_span_indices(120, 0, 1000, 1e-9) == (0, 240)

    def test_stage_union_never_collapses_inside_a_narrow_window(self) -> None:
        # Peak pinned on the stage start: union still gives both sides room.
        assert stage_union_span_indices(500, 500, 1000, 0, 1600, 1e-9) == (
            200,
            1000,
        )
        # Stage wider than the peak window: the union keeps the whole stage.
        assert stage_union_span_indices(800, 300, 1500, 0, 2000, 1e-9) == (
            300,
            1500,
        )

    def test_stage_union_enforces_minimum_span(self) -> None:
        a_idx, b_idx = stage_union_span_indices(
            1000,
            1005,
            1010,
            0,
            2000,
            1e-9,
            half_span_s=10e-9,
            min_span_s=60e-9,
        )
        assert b_idx - a_idx == 60
        assert a_idx <= 1000 <= b_idx


@pytest.mark.skipif(not SMC_RT_UH_1048.exists(), reason="sample missing")
def test_every_extreme_card_keeps_peak_value_and_centred_interval() -> None:
    from dpt_extractor.gui.main_window import MainWindow
    from dpt_extractor.models.waveform import (
        bundle_reverse_recovery_current,
        bundle_total_current,
    )

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        win._load_file(str(SMC_RT_UH_1048))
        assert win.bundle is not None and win.result is not None
        t = win.bundle.t
        dt = float(win.bundle.dt)
        half = max(1, int(round(300e-9 / dt)))
        irr_raw = np.asarray(
            bundle_reverse_recovery_current(win.bundle, win.profile), dtype=np.float64
        )
        signals = {
            "ic_abs": np.abs(bundle_total_current(win.bundle, win.profile)),
            "vce": np.asarray(win.bundle.get(win.profile.vce), dtype=np.float64),
            "vd": np.asarray(win.bundle.get(win.profile.v_diode), dtype=np.float64),
            "irr_abs": np.abs(irr_raw),
        }
        stored = {
            ("关断过程", "Ic_off_max"): abs(float(win.result.turn_off.ic_off_max)),
            ("关断过程", "Vce_off_max"): float(win.result.turn_off.vce_off_max),
            ("开通", "Ic_on_max"): abs(float(win.result.turn_on.ic_on_max)),
            ("开通", "Vce_on_max"): float(win.result.turn_on.vce_on_max),
            ("反向恢复", "Vrr"): float(win.result.reverse_recovery.vrr),
            ("反向恢复", "Irr"): abs(float(win.result.reverse_recovery.irr)),
        }
        peaks = {}
        for key in EXTREME_CARDS:
            point = win._default_extreme_peak_point(*key)
            if point is None:
                context = win._rr_irr_cursor_context()
                assert context is not None
                point = (int(context[3]), float(context[4]))
            peaks[key] = point

        for key, kind in EXTREME_CARDS.items():
            interval = win._parameter_max_interval_indices(*key)
            assert interval is not None, key
            a_idx, b_idx = interval
            peak_idx = int(peaks[key][0])
            assert 0 <= a_idx < b_idx <= len(t) - 1, key
            assert a_idx <= peak_idx <= b_idx, key
            # 峰值两侧都应尽量拿到 300ns；阶段包络卡至少不退化到几十 ns。
            # 2026-11-19（用户 #4）：Vce_on_max 的 A 改为
            # clamp(峰值-300ns, Vge 开通起点, 峰值)，允许贴着峰值；
            # B 改为「回落首个 1.5µs 稳态带起点 + 20ns」，不再要求 ±300ns。
            if key == ("开通", "Vce_on_max"):
                # 2026-11-19（用户 #4）：A 在峰值左侧但不得早于 Vge 10% 起点
                # （含 5ns 余量）；B 在峰值右侧且不越过「事件段尾 + 200ns」。
                vge_10 = win._vge_turn_on_ten_percent_index()
                if vge_10 is not None and vge_10 <= peak_idx:
                    assert a_idx >= vge_10, key
                assert a_idx < peak_idx, key
                guard_n = max(1, int(round(200e-9 / dt)))
                assert peak_idx < b_idx <= int(win.result.segments.turn_on[1]) + guard_n, key
            else:
                assert peak_idx - a_idx >= min(half, peak_idx), key
                assert b_idx - peak_idx >= min(half, len(t) - 1 - peak_idx), key
            # 数值不变：区间极值 == 权威数值。Irr 的权威值是有符号 I_RM 峰值
            # （不是区间内 |Irr| 最大值），故按峰值点取值校验。
            if key == ("反向恢复", "Irr"):
                assert abs(float(irr_raw[peak_idx])) == pytest.approx(
                    stored[key], rel=1e-9, abs=1e-9
                ), key
            else:
                window_max = float(np.max(signals[kind][a_idx : b_idx + 1]))
                assert window_max == pytest.approx(
                    stored[key], rel=1e-9, abs=1e-9
                ), key
            # 局部取景：A/B 离视窗左右边至少 10%。
            win._on_value_clicked(*key)
            app.processEvents()
            x0, x1 = win.wave_plot.current_x_range_us()
            span = x1 - x0
            a_us = float(t[a_idx] * 1e6)
            b_us = float(t[b_idx] * 1e6)
            assert (a_us - x0) / span >= 0.10 - 1e-6, key
            assert (x1 - b_us) / span >= 0.10 - 1e-6, key
    finally:
        win.close()
        app.processEvents()

# 2026-11-18: 除六个极值卡外，其余交互卡的默认取景也必须保证 A/B 距视窗
# 左右边 ≥10%（受数据边界限制时由 `_last_focus_margin_limited` 标记）。
FOCUS_MARGIN_CARDS = [
    ("关断过程", "Ic_off_max"),
    ("关断过程", "Vce_off_max"),
    ("关断过程", "ΔVce"),
    ("关断过程", "Eoff"),
    ("关断过程", "Toff"),
    ("关断过程", "Td_off"),
    ("关断过程", "Tf"),
    ("关断过程", "dv/dt"),
    ("关断过程", "di/dt"),
    ("关断过程", "Ls_off"),
    ("关断过程", "串扰电压"),
    ("开通", "Ic_on_max"),
    ("开通", "Vce_on_max"),
    ("开通", "ΔVce"),
    ("开通", "Eon"),
    ("开通", "Ton"),
    ("开通", "Td_on"),
    ("开通", "Tr"),
    ("开通", "开通电流"),
    ("开通", "Ls_on"),
    ("开通", "串扰电压"),
    ("反向恢复", "Irr"),
    ("反向恢复", "Vrr"),
    ("反向恢复", "Trr"),
    ("反向恢复", "Err"),
    ("反向恢复", "Pdmax"),
]


@pytest.mark.skipif(not SMC_RT_UH_1048.exists(), reason="sample missing")
def test_every_interactive_card_keeps_10pct_view_margins() -> None:
    """A/B 距视窗左右边 ≥10%（数据边界受限时带显式标记）。"""

    from dpt_extractor.gui.main_window import MainWindow

    import copy

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    checked = 0
    try:
        win._load_file(str(SMC_RT_UH_1048))
        t = win.bundle.t
        # 取景只改显示层：逐卡点击后权威数值必须逐字段不变。
        baseline = copy.deepcopy(win.result)
        for key in FOCUS_MARGIN_CARDS:
            if win._parameter_interval_us(*key) is None:
                continue
            before = win.result
            win._on_value_clicked(*key)
            app.processEvents()
            x0, x1 = win.wave_plot.current_x_range_us()
            span = x1 - x0
            cursor_a = win.wave_plot._cursor_a
            cursor_b = win.wave_plot._cursor_b
            if cursor_a is None or cursor_b is None:
                continue
            a_us = float(cursor_a.value())
            b_us = float(cursor_b.value())
            left = (min(a_us, b_us) - x0) / span
            right = (x1 - max(a_us, b_us)) / span
            limited = bool(getattr(win.wave_plot, "_last_focus_margin_limited", False))
            assert left >= 0.10 - 1e-6 or limited, (key, left, limited)
            assert right >= 0.10 - 1e-6 or limited, (key, right, limited)
            assert win.result is before, key
            assert win.result == baseline, key
            checked += 1
    finally:
        win.close()
        app.processEvents()
    assert checked >= 15


def test_crosstalk_default_window_keeps_50ns_minimum_span() -> None:
    """P2-2: 串扰 A/B 至少 50ns 跨度、落在采样点上、仍覆盖段内极值。"""

    from dpt_extractor.gui.main_window import MainWindow
    from dpt_extractor.models.bridge_profile import make_profile
    from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

    dt = 1e-9
    t = np.arange(6000) * dt
    vge_other = np.full(len(t), -5.0)
    vge_other[2000:2600] = 3.0
    vge_other[3000] = -16.0
    vge_other[3030] = 4.0  # 右侧极值只比左侧晚 30ns
    profile = make_profile("W", "upper")
    bundle = WaveformBundle(
        t=t,
        channels={profile.vge_other: vge_other},
        meta=TekMetadata(sample_interval=dt),
    )
    host = SimpleNamespace(bundle=bundle, profile=profile)
    window = MainWindow._crosstalk_extrema_cursor_window(host, (0, len(t)), vge_other)
    assert window is not None
    a_us, b_us = window
    assert abs(b_us - a_us) * 1e3 >= 50.0 - 1e-6
    lo_idx = int(np.searchsorted(t, min(a_us, b_us) * 1e-6, side="left"))
    hi_idx = int(np.searchsorted(t, max(a_us, b_us) * 1e-6, side="left"))
    assert abs(float(t[lo_idx] * 1e6) - min(a_us, b_us)) <= 1e-9
    assert abs(float(t[hi_idx] * 1e6) - max(a_us, b_us)) <= 1e-9
    assert float(np.max(vge_other[lo_idx : hi_idx + 1])) == pytest.approx(4.0)
    assert float(np.min(vge_other[lo_idx : hi_idx + 1])) == pytest.approx(-16.0)
