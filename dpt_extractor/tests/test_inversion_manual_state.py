from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.models.bridge_profile import make_profile
from dpt_extractor.models.waveform import TekMetadata, WaveformBundle


class _StatusBar:
    def __init__(self) -> None:
        self.message = ""

    def showMessage(self, message: str) -> None:  # noqa: N802
        self.message = str(message)


class _ManualStateHarness:
    _logical_roles_affected_by_channel_transform = (
        MainWindow._logical_roles_affected_by_channel_transform
    )
    _manual_parameter_waveform_roles = MainWindow._manual_parameter_waveform_roles
    _invalidate_manual_adjustments_for_channel_transform = (
        MainWindow._invalidate_manual_adjustments_for_channel_transform
    )
    _cursor_endpoint_channels_for_param = (
        MainWindow._cursor_endpoint_channels_for_param
    )
    _channel_for_param = MainWindow._channel_for_param
    _on_waveform_channel_inversion_changed = (
        MainWindow._on_waveform_channel_inversion_changed
    )

    def __init__(self, *, profile=None, formulas=None) -> None:
        self.profile = profile or make_profile("U", "upper")
        self.bundle = WaveformBundle(
            t=np.array([0.0, 1e-9], dtype=np.float64),
            channels={},
            meta=TekMetadata(
                source_path="same-file.tss",
                channel_math_formulas=dict(formulas or {}),
            ),
        )
        marker = (1.0, 2.0, 3.0, 4.0)
        self._manual_intervals = {
            ("反向恢复", "Err"): (1.0, 2.0),
            ("反向恢复", "Pdmax"): (1.0, 2.0),
            ("反向恢复", "Vrr"): (1.0, 2.0),
            ("开通", "Eon"): (1.0, 2.0),
            ("开通", "串扰电压"): (1.0, 2.0),
        }
        self._manual_extreme_values = {
            ("反向恢复", "Vrr"): (3.0, 3.0),
            ("开通", "Vce_on_max"): (3.0, 3.0),
            ("开通", "Ic_on_max"): (3.0, 3.0),
        }
        self._manual_energy = {
            ("反向恢复", "Err"): marker,
            ("开通", "Eon"): marker,
        }
        self._manual_delta_vce = {
            ("开通", "ΔVce"): marker,
            ("关断过程", "ΔVce"): marker,
        }
        self._manual_dvdt = {
            ("反向恢复", "dv/dt"): marker,
            ("开通", "dv/dt"): marker,
        }
        self._manual_didt = {
            ("反向恢复", "di/dt"): (*marker, "idm"),
            ("开通", "di/dt"): (*marker, "generic"),
        }
        self._manual_turn_on_current = marker
        self._manual_trr_measure = (1.0, 2.0, 3.0, 4.0, 5)
        self.cfg = SimpleNamespace(test_mode=SimpleNamespace(mode="dpt"))
        self._status = _StatusBar()
        self.recalculate_calls: list[bool] = []

    def _recalculate(self, *, reset_manual: bool = False) -> None:
        self.recalculate_calls.append(bool(reset_manual))

    def _refresh_offset_measurement_table(self, *, update_auxiliary: bool = False) -> None:
        raise AssertionError("DPT inversion must not enter offset refresh")

    def statusBar(self) -> _StatusBar:  # noqa: N802
        return self._status


def test_upper_ch3_inversion_drops_current_related_manual_state_only() -> None:
    owner = _ManualStateHarness()

    affected = owner._invalidate_manual_adjustments_for_channel_transform("CH3")

    assert affected == {"irr", "ic"}
    assert ("反向恢复", "di/dt") not in owner._manual_didt
    assert ("开通", "di/dt") not in owner._manual_didt
    assert ("反向恢复", "Err") not in owner._manual_energy
    assert ("开通", "Eon") not in owner._manual_energy
    assert ("反向恢复", "Err") not in owner._manual_intervals
    assert ("反向恢复", "Pdmax") not in owner._manual_intervals
    assert ("开通", "Eon") not in owner._manual_intervals
    assert owner._manual_turn_on_current is None
    assert owner._manual_trr_measure is None

    # Vd/Vce/Vge-other do not change when the upper-bridge Irr source changes.
    assert ("反向恢复", "dv/dt") in owner._manual_dvdt
    assert ("反向恢复", "Vrr") in owner._manual_intervals
    assert ("反向恢复", "Vrr") in owner._manual_extreme_values
    assert ("开通", "Vce_on_max") in owner._manual_extreme_values
    assert ("开通", "ΔVce") in owner._manual_delta_vce
    assert ("开通", "串扰电压") in owner._manual_intervals


def test_vdiode_inversion_drops_err_vrr_but_preserves_rr_current_state() -> None:
    owner = _ManualStateHarness()

    affected = owner._invalidate_manual_adjustments_for_channel_transform("CH5")

    assert affected == {"v_diode"}
    assert ("反向恢复", "Err") not in owner._manual_energy
    assert ("反向恢复", "Err") not in owner._manual_intervals
    assert ("反向恢复", "Pdmax") not in owner._manual_intervals
    assert ("反向恢复", "Vrr") not in owner._manual_intervals
    assert ("反向恢复", "Vrr") not in owner._manual_extreme_values
    assert ("反向恢复", "dv/dt") not in owner._manual_dvdt

    assert ("反向恢复", "di/dt") in owner._manual_didt
    assert owner._manual_trr_measure is not None
    assert ("开通", "Eon") in owner._manual_energy
    assert owner._manual_turn_on_current is not None


def test_math_dependency_and_handler_invalidate_before_fresh_recalculation() -> None:
    upper = make_profile("U", "upper")
    profile = replace(upper, irr="MATH2")
    owner = _ManualStateHarness(profile=profile, formulas={"MATH2": "CH3"})

    owner._on_waveform_channel_inversion_changed("CH3", True)

    assert owner.bundle.meta.channel_display_inversions == {"CH3"}
    assert ("反向恢复", "di/dt") not in owner._manual_didt
    assert ("反向恢复", "Err") not in owner._manual_energy
    assert owner.recalculate_calls == [False]
    assert owner.statusBar().message == "CH3 已切换为反相"


def test_unmapped_channel_inversion_preserves_every_manual_cache() -> None:
    owner = _ManualStateHarness()
    snapshots = {
        name: dict(getattr(owner, name))
        for name in (
            "_manual_intervals",
            "_manual_extreme_values",
            "_manual_energy",
            "_manual_delta_vce",
            "_manual_dvdt",
            "_manual_didt",
        )
    }
    turn_on = owner._manual_turn_on_current
    trr = owner._manual_trr_measure

    affected = owner._invalidate_manual_adjustments_for_channel_transform("CH8")

    assert affected == set()
    for name, snapshot in snapshots.items():
        assert getattr(owner, name) == snapshot
    assert owner._manual_turn_on_current == turn_on
    assert owner._manual_trr_measure == trr
