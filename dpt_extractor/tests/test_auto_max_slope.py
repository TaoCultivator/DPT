from __future__ import annotations

import numpy as np

from dpt_extractor.metrics.slopes import (
    auto_dvdt_between_base_top,
    auto_rr_didt_between_levels,
)
from dpt_extractor.models.slope_range import (
    auto_max_slope_range,
    slope_range_result_label,
)


def _piecewise_progress(t_ns: np.ndarray) -> np.ndarray:
    progress = np.zeros_like(t_ns, dtype=np.float64)
    slow_1 = (t_ns >= 20.0) & (t_ns < 80.0)
    fast = (t_ns >= 80.0) & (t_ns < 105.0)
    slow_2 = (t_ns >= 105.0) & (t_ns < 170.0)
    progress[slow_1] = 0.25 * (t_ns[slow_1] - 20.0) / 60.0
    progress[fast] = 0.25 + 0.55 * (t_ns[fast] - 80.0) / 25.0
    progress[slow_2] = 0.80 + 0.20 * (t_ns[slow_2] - 105.0) / 65.0
    progress[t_ns >= 170.0] = 1.0
    return progress


def test_auto_rise_selects_the_fastest_fixed_twenty_percent_band() -> None:
    t_ns = np.linspace(0.0, 200.0, 401)
    t_s = t_ns * 1e-9
    progress = _piecewise_progress(t_ns)
    voltage = 100.0 * progress
    # A single raw spike outside the real fast edge must not become the range.
    voltage[int(np.argmin(np.abs(t_ns - 50.0)))] += 45.0

    result = auto_dvdt_between_base_top(
        t_s, voltage, 0, len(t_s) - 1, 0.0, 100.0, "rise"
    )

    assert result.t_pct_a_s is not None
    assert result.t_pct_b_s is not None
    assert result.resolved_pct_a is not None
    assert result.resolved_pct_b is not None
    assert 0.20 <= result.resolved_pct_a <= 0.75
    assert 0.30 <= result.resolved_pct_b <= 0.85
    assert np.isclose(
        result.resolved_pct_b - result.resolved_pct_a, 0.20, atol=1e-9
    )
    assert 1.8 <= result.dvdt <= 2.5


def test_auto_fall_preserves_chronological_high_to_low_percentages() -> None:
    t_ns = np.linspace(0.0, 200.0, 401)
    t_s = t_ns * 1e-9
    current = 100.0 * (1.0 - _piecewise_progress(t_ns))

    result = auto_dvdt_between_base_top(
        t_s, current, 0, len(t_s) - 1, 0.0, 100.0, "fall"
    )

    assert result.t_pct_a_s is not None
    assert result.t_pct_b_s is not None
    assert result.resolved_pct_a is not None
    assert result.resolved_pct_b is not None
    assert result.resolved_pct_a > result.resolved_pct_b
    assert np.isclose(
        result.resolved_pct_a - result.resolved_pct_b, 0.20, atol=1e-9
    )
    assert result.t_pct_a_s < result.t_pct_b_s
    assert 1.8 <= result.dvdt <= 2.5


def test_auto_rr_didt_keeps_negative_probe_polarity_and_real_ab() -> None:
    t_ns = np.linspace(0.0, 240.0, 481)
    t_s = t_ns * 1e-9
    progress = _piecewise_progress(np.minimum(t_ns, 200.0))
    # Negative-polarity forward platform commutates toward a zero tail.
    irr = -120.0 * (1.0 - progress)

    result = auto_rr_didt_between_levels(
        t_s,
        irr,
        0,
        len(t_s) - 1,
        forward_a=-120.0,
        base_a=0.0,
    )

    assert result.t_pct_a_s is not None
    assert result.t_pct_b_s is not None
    assert result.resolved_pct_a is not None
    assert result.resolved_pct_b is not None
    assert result.resolved_pct_a > result.resolved_pct_b
    assert np.isclose(
        result.resolved_pct_a - result.resolved_pct_b, 0.20, atol=1e-9
    )
    assert result.th_a < result.th_b
    assert result.didt > 2.0


def test_auto_result_label_preserves_internal_percentages_and_duration() -> None:
    t_ns = np.linspace(0.0, 200.0, 401)
    t_s = t_ns * 1e-9
    result = auto_dvdt_between_base_top(
        t_s,
        100.0 * _piecewise_progress(t_ns),
        0,
        len(t_s) - 1,
        0.0,
        100.0,
        "rise",
    )
    label = slope_range_result_label(auto_max_slope_range("off_dvdt"), result)

    assert label.startswith("自动 ")
    assert "%→" in label
    assert " ns）" in label


def test_full_corpus_validator_requires_exact_twenty_percent_compact_span() -> None:
    from scripts.validate_tss_samples import _auto_slope_label_has_fixed_span

    assert _auto_slope_label_has_fixed_span("自动 42.5%→62.5%（8.2 ns）")
    assert _auto_slope_label_has_fixed_span("自动 63%→43%（5 ns）")
    assert not _auto_slope_label_has_fixed_span("自动 42.5%→52.5%（8.2 ns）")
    assert not _auto_slope_label_has_fixed_span("42.5%→62.5%")
    assert not _auto_slope_label_has_fixed_span("自动最大斜率")
