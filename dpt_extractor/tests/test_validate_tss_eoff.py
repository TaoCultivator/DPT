"""Strict corpus Eoff validation for stable-platform and legacy endpoints."""

from __future__ import annotations

import unittest
from dataclasses import replace

import numpy as np

from dpt_extractor.metrics.iec_windows import EnergyLossMarkers
from dpt_extractor.metrics.plateau_level import EoffStablePlatformCursorContext
from scripts.validate_tss_samples import (
    _audit_eoff_marker,
    _independent_eoff_half_open_mj,
)


class TestStrictEoffMarkerAudit(unittest.TestCase):
    @staticmethod
    def _fixture() -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        EoffStablePlatformCursorContext,
    ]:
        t = np.arange(1_000, dtype=np.float64) * 1e-9
        vce = np.full(1_000, 5.2, dtype=np.float64)
        vce[300:401] = np.linspace(5.2, 400.0, 101)
        vce[401:] = 400.0
        ic = np.full(1_000, 50.0, dtype=np.float64)
        ic[400:501] = np.linspace(50.0, 2.2, 101)
        ic[501:] = 2.2
        context = EoffStablePlatformCursorContext(
            a_idx=200,
            b_idx=650,
            a_band_start_idx=160,
            a_band_end_idx=239,
            b_band_start_idx=610,
            b_band_end_idx=689,
            v10_idx=310,
            v90_idx=390,
            i90_idx=410,
            i10_idx=490,
            search_end_idx=660,
        )
        return t, vce, ic, context

    @staticmethod
    def _marker(
        t: np.ndarray,
        context: EoffStablePlatformCursorContext | None,
        *,
        endpoint_mode: str = "stable_platforms",
        i_start: int = 200,
        i_end: int = 650,
        hb_a: float = -0.1,
    ) -> EnergyLossMarkers:
        return EnergyLossMarkers(
            ha_v=5.0,
            hb_a=hb_a,
            t_start=float(t[i_start]),
            t_end=float(t[i_end]),
            i_start=i_start,
            i_end=i_end,
            endpoint_mode=endpoint_mode,
            stable_platform_context=context,
        )

    def _energy(
        self,
        t: np.ndarray,
        vce: np.ndarray,
        ic: np.ndarray,
        marker: EnergyLossMarkers,
    ) -> float:
        value = _independent_eoff_half_open_mj(
            t,
            vce,
            ic,
            marker.i_start,
            marker.i_end,
        )
        self.assertIsNotNone(value)
        assert value is not None
        return float(value)

    def test_stable_platforms_accept_context_without_ha_hb_intersections(self) -> None:
        t, vce, ic, context = self._fixture()
        marker = self._marker(t, context)
        # A differs from Ha by 0.2 V and B differs from Hb by 2.3 A.  These
        # are stable-band representative points, not forced raw intersections.
        self.assertGreater(abs(float(ic[marker.i_end]) - marker.hb_a), 2.0)

        problems = _audit_eoff_marker(
            t,
            vce,
            ic,
            marker,
            self._energy(t, vce, ic, marker),
        )

        self.assertEqual(problems, [])

    def test_stable_platforms_fails_closed_without_global_context(self) -> None:
        t, vce, ic, _context = self._fixture()
        marker = self._marker(t, None)

        problems = _audit_eoff_marker(
            t,
            vce,
            ic,
            marker,
            self._energy(t, vce, ic, marker),
        )

        self.assertEqual(
            problems,
            ["Eoff stable_platforms 缺少全局稳定带证据上下文"],
        )

    def test_stable_platforms_rejects_marker_ab_that_differ_from_context(self) -> None:
        t, vce, ic, context = self._fixture()
        marker = self._marker(t, context, i_start=201, i_end=649)

        problems = _audit_eoff_marker(
            t,
            vce,
            ic,
            marker,
            self._energy(t, vce, ic, marker),
        )

        self.assertTrue(any("Eoff A索引=" in problem for problem in problems))
        self.assertTrue(any("Eoff B索引=" in problem for problem in problems))
        self.assertTrue(any("Eoff A时刻未与" in problem for problem in problems))
        self.assertTrue(any("Eoff B时刻未与" in problem for problem in problems))

    def test_stable_platforms_rejects_unstable_band_and_energy_drift(self) -> None:
        t, vce, ic, context = self._fixture()
        marker = self._marker(t, context)
        ic[context.b_band_start_idx : context.b_band_end_idx + 1] = np.linspace(
            -10.0,
            20.0,
            context.b_band_end_idx - context.b_band_start_idx + 1,
        )
        actual = self._energy(t, vce, ic, marker)

        problems = _audit_eoff_marker(
            t,
            vce,
            ic,
            marker,
            actual + 0.5,
        )

        self.assertTrue(
            any("Eoff B/Ic Base稳定带" in problem for problem in problems)
        )
        self.assertTrue(
            any(problem.startswith("Eoff校验=") for problem in problems)
        )

    def test_stable_platforms_rejects_wrong_adaptive_width_or_event_bound(
        self,
    ) -> None:
        t, vce, ic, context = self._fixture()
        bad_context = replace(
            context,
            b_band_end_idx=context.b_band_end_idx - 1,
            search_end_idx=context.b_idx - 1,
        )
        marker = self._marker(t, bad_context)

        problems = _audit_eoff_marker(
            t,
            vce,
            ic,
            marker,
            self._energy(t, vce, ic, marker),
        )

        self.assertTrue(any("B稳定带宽度未与Ic主沿" in p for p in problems))
        self.assertIn(
            "Eoff B代表点/稳定带越过事件门允许的半带确认范围",
            problems,
        )

    def test_stable_platforms_rejects_main_signed_power_peak_outside_ab(self) -> None:
        t, vce, ic, context = self._fixture()
        marker = self._marker(t, context)
        # Put a larger positive signed-power sample after B but still inside
        # the production-declared event evidence band.
        vce[680] = 2_000.0
        ic[680] = 100.0

        problems = _audit_eoff_marker(
            t,
            vce,
            ic,
            marker,
            self._energy(t, vce, ic, marker),
        )

        self.assertIn(
            "Eoff stable_platforms A/B未包含主有符号Vce*Ic峰",
            problems,
        )

    def test_level_crossings_keeps_old_b_hb_binding(self) -> None:
        t, vce, ic, _context = self._fixture()
        bad = self._marker(
            t,
            None,
            endpoint_mode="level_crossings",
            hb_a=-0.1,
        )
        good = self._marker(
            t,
            None,
            endpoint_mode="level_crossings",
            hb_a=2.2,
        )

        bad_problems = _audit_eoff_marker(
            t,
            vce,
            ic,
            bad,
            self._energy(t, vce, ic, bad),
        )
        good_problems = _audit_eoff_marker(
            t,
            vce,
            ic,
            good,
            self._energy(t, vce, ic, good),
        )

        self.assertTrue(
            any("Eoff B未贴Ic平台=" in problem for problem in bad_problems)
        )
        self.assertEqual(good_problems, [])


if __name__ == "__main__":
    unittest.main()
