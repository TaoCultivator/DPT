from __future__ import annotations

import numpy as np

from dpt_extractor.metrics.commutation_inductance import (
    turn_off_commutation_inductance,
    turn_on_commutation_inductance,
)


def test_turn_on_constant_inductive_voltage_recovers_known_inductance() -> None:
    t = np.linspace(0.0, 10e-9, 11)
    current = np.linspace(0.0, 100.0, 11)
    vce_top = 800.0
    vce = np.full_like(t, vce_top - 100.0)

    context = turn_on_commutation_inductance(
        t,
        vce,
        current,
        vce_top,
        t[0],
        t[-1],
    )

    assert context is not None
    assert np.isclose(context.voltage_area_vs, 1e-6)
    assert np.isclose(context.delta_current_a, 100.0)
    assert np.isclose(context.value_nh, 10.0)


def test_turn_off_constant_positive_overshoot_recovers_known_inductance() -> None:
    t = np.linspace(0.0, 10e-9, 11)
    current = np.linspace(100.0, 0.0, 11)
    blocking_top = 750.0
    vce = np.full_like(t, blocking_top + 100.0)

    context = turn_off_commutation_inductance(
        t,
        vce,
        current,
        blocking_top,
        t[0],
        t[-1],
    )

    assert context is not None
    assert np.isclose(context.voltage_area_vs, 1e-6)
    assert np.isclose(context.delta_current_a, 100.0)
    assert np.isclose(context.value_nh, 10.0)


def test_commutation_inductance_rejects_negligible_current_change() -> None:
    t = np.linspace(0.0, 10e-9, 11)
    current = np.linspace(10.0, 10.1, 11)
    vce = np.full_like(t, 700.0)

    assert (
        turn_on_commutation_inductance(t, vce, current, 800.0, t[0], t[-1])
        is None
    )
    assert (
        turn_off_commutation_inductance(t, vce, current, 600.0, t[0], t[-1])
        is None
    )
