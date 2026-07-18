from __future__ import annotations

import unittest

import numpy as np

from dpt_extractor.metrics.iec_timings import TurnOnTimingInstants
from dpt_extractor.models.results import ExtractResult, TurnOnResult
from scripts.validate_tss_samples import _audit_turn_on_timing_core


class TestValidateTssTurnOnTimingCore(unittest.TestCase):
    def setUp(self) -> None:
        self.t = np.arange(2001, dtype=np.float64) * 1e-9

    @staticmethod
    def _result(
        instants: TurnOnTimingInstants,
        *,
        unavailable: set[tuple[str, str]] | None = None,
    ) -> ExtractResult:
        return ExtractResult(
            turn_on=TurnOnResult(
                ton=instants.ton_ns,
                td_on=instants.td_on_ns,
                tr=instants.tr_ns,
            ),
            unavailable_metrics=set(unavailable or ()),
        )

    def _audit(
        self,
        result: ExtractResult,
        instants: TurnOnTimingInstants,
    ) -> tuple[list[str], str]:
        return _audit_turn_on_timing_core(
            self.t,
            result,
            instants,
            event_start_idx=400,
            event_end_idx=1800,
        )

    def test_complete_ordered_instants_and_matching_cards_pass(self) -> None:
        instants = TurnOnTimingInstants(
            t_v10_s=700e-9,
            t_i10_s=850e-9,
            t_i90_s=1050e-9,
            td_on_ns=150.0,
            tr_ns=200.0,
            ton_ns=350.0,
        )

        problems, detail = self._audit(self._result(instants), instants)

        self.assertEqual(problems, [])
        self.assertIn("on_instants=", detail)

    def test_reversed_td_order_uses_each_endpoint_pair_not_sum_identity(self) -> None:
        # Vge10 can trail Ic10 on a marginal trace.  Absolute duration semantics
        # then give Ton != Td_on + Tr even though all three endpoint pairs exist.
        instants = TurnOnTimingInstants(
            t_v10_s=1200e-9,
            t_i10_s=1100e-9,
            t_i90_s=1400e-9,
            td_on_ns=100.0,
            tr_ns=300.0,
            ton_ns=200.0,
        )
        self.assertNotAlmostEqual(
            instants.ton_ns,
            instants.td_on_ns + instants.tr_ns,
        )

        problems, _ = self._audit(self._result(instants), instants)

        self.assertEqual(problems, [])

    def test_unavailable_nonfinite_and_missing_instants_fail_closed(self) -> None:
        instants = TurnOnTimingInstants(
            t_v10_s=700e-9,
            t_i10_s=None,
            t_i90_s=None,
            td_on_ns=0.0,
            tr_ns=0.0,
            ton_ns=0.0,
        )
        result = ExtractResult(
            turn_on=TurnOnResult(ton=float("nan"), td_on=0.0, tr=0.0),
            unavailable_metrics={
                ("开通", "Ton"),
                ("开通", "Td_on"),
                ("开通", "Tr"),
            },
        )

        problems, _ = self._audit(result, instants)

        self.assertIn("Ton=unavailable", problems)
        self.assertIn("Td_on=unavailable", problems)
        self.assertIn("Tr=unavailable", problems)
        self.assertTrue(any("缺少Ic10真实交点" in item for item in problems))
        self.assertTrue(any("缺少Ic90真实交点" in item for item in problems))
        self.assertTrue(any("Ton结果无效" in item for item in problems))

    def test_card_value_must_match_its_own_real_endpoint_pair(self) -> None:
        instants = TurnOnTimingInstants(
            t_v10_s=700e-9,
            t_i10_s=850e-9,
            t_i90_s=1050e-9,
            td_on_ns=150.0,
            tr_ns=200.0,
            ton_ns=350.0,
        )
        result = self._result(instants)
        result.turn_on.tr = 201.0

        problems, _ = self._audit(result, instants)

        self.assertTrue(any(item.startswith("Tr结果/交点=") for item in problems))

    def test_instants_outside_declared_turn_on_event_fail(self) -> None:
        instants = TurnOnTimingInstants(
            t_v10_s=300e-9,
            t_i10_s=850e-9,
            t_i90_s=1050e-9,
            td_on_ns=550.0,
            tr_ns=200.0,
            ton_ns=750.0,
        )

        problems, _ = self._audit(self._result(instants), instants)

        self.assertTrue(any("Vge10交点越界" in item for item in problems))


if __name__ == "__main__":
    unittest.main()
