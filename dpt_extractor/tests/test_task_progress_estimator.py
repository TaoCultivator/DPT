from __future__ import annotations

import unittest

from dpt_extractor.gui.task_progress import (
    ReportStageBudgetEstimator,
    ReportTimingContext,
    ReportTimingHistory,
    UnitRateEstimator,
    format_duration_ms,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class UnitRateEstimatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _FakeClock()
        self.estimator = UnitRateEstimator(self.clock)

    def _complete_unit(self, completed: int, seconds: float = 1.0) -> None:
        self.clock.advance(seconds)
        self.estimator.observe("capture", completed, 5)

    def test_requires_two_completed_units_before_estimating(self):
        self.estimator.start_phase("capture", 0, 5)
        self.assertIsNone(self.estimator.eta_ms())

        self._complete_unit(1)
        self.assertIsNone(self.estimator.eta_ms())

        self._complete_unit(2)
        self.assertAlmostEqual(self.estimator.eta_ms() or -1.0, 3000.0)

    def test_eta_counts_down_while_completed_counter_is_fixed(self):
        self.estimator.start_phase("capture", 0, 5)
        self._complete_unit(1)
        self._complete_unit(2)
        eta_at_checkpoint = self.estimator.eta_ms()

        self.clock.advance(0.4)
        self.estimator.observe("capture", 2, 5)
        eta_after_wait = self.estimator.eta_ms()

        self.assertIsNotNone(eta_at_checkpoint)
        self.assertIsNotNone(eta_after_wait)
        self.assertLess(eta_after_wait, eta_at_checkpoint)
        self.assertAlmostEqual(eta_after_wait or -1.0, 2600.0)

    def test_stalled_current_unit_becomes_unknown_instead_of_growing(self):
        self.estimator.start_phase("capture", 0, 5)
        self._complete_unit(1)
        self._complete_unit(2)

        self.clock.advance(2.6)
        self.assertIsNone(self.estimator.eta_ms())

    def test_phase_change_discards_previous_rate(self):
        self.estimator.start_phase("capture", 0, 5)
        self._complete_unit(1)
        self._complete_unit(2)
        self.assertIsNotNone(self.estimator.eta_ms())

        self.estimator.start_phase("save", 0, 1)
        self.assertIsNone(self.estimator.eta_ms())

        self.clock.advance(1.0)
        self.estimator.observe("save", 1, 1)
        self.assertEqual(self.estimator.eta_ms(), 0.0)

    def test_observe_with_new_phase_key_also_resets(self):
        self.estimator.start_phase("capture", 0, 5)
        self._complete_unit(1)
        self._complete_unit(2)

        self.estimator.observe("insert", 0, 3)
        self.assertIsNone(self.estimator.eta_ms())

    def test_completed_phase_returns_zero_without_rate_samples(self):
        self.estimator.start_phase("save", 1, 1)
        self.assertEqual(self.estimator.eta_ms(), 0.0)

    def test_slow_latest_unit_withholds_false_precision(self):
        self.estimator.start_phase("capture", 0, 5)
        self._complete_unit(1, 1.0)
        self._complete_unit(2, 1.0)
        self.assertIsNotNone(self.estimator.eta_ms())

        self._complete_unit(3, 3.0)
        self.assertIsNone(self.estimator.eta_ms())

    def test_highly_dispersed_unit_times_are_low_confidence(self):
        self.estimator.start_phase("capture", 0, 5)
        self._complete_unit(1, 0.5)
        self._complete_unit(2, 2.0)
        self.assertIsNone(self.estimator.eta_ms())

    def test_recent_window_recovers_after_old_outlier_expires(self):
        self.estimator.start_phase("capture", 0, 10)
        completed = 0
        for duration in (4.0, 1.0, 1.0, 1.0, 1.0, 1.0):
            completed += 1
            self.clock.advance(duration)
            self.estimator.observe("capture", completed, 10)

        self.assertAlmostEqual(self.estimator.eta_ms() or -1.0, 4000.0)

    def test_batched_completion_needs_two_independent_intervals(self):
        self.estimator.start_phase("insert", 0, 6)
        self.clock.advance(2.0)
        self.estimator.observe("insert", 2, 6)
        self.assertIsNone(self.estimator.eta_ms())

        self.clock.advance(2.0)
        self.estimator.observe("insert", 4, 6)
        self.assertAlmostEqual(self.estimator.eta_ms() or -1.0, 2000.0)


class FormatDurationTests(unittest.TestCase):
    def test_rounds_across_minute_boundary(self):
        self.assertEqual(format_duration_ms(119_600.0), "2m 0s")

    def test_preserves_short_duration_formats(self):
        self.assertEqual(format_duration_ms(0.0), "0 ms")
        self.assertEqual(format_duration_ms(0.1), "1 ms")
        self.assertEqual(format_duration_ms(0.5), "1 ms")
        self.assertEqual(format_duration_ms(125.4), "125 ms")
        self.assertEqual(format_duration_ms(1_250.0), "1.2 s")
        self.assertEqual(format_duration_ms(60_000.0), "1m 0s")

    def test_non_finite_duration_is_unknown(self):
        self.assertEqual(format_duration_ms(float("nan")), "--")


class ReportStageBudgetEstimatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _FakeClock()
        self.windows = {
            "capture": (0.15, 0.55),
            "open-workbook": (0.55, 0.60),
            "save-workbook": (0.60, 0.999),
        }
        self.estimator = ReportStageBudgetEstimator(
            {
                "capture": 4_000.0,
                "open-workbook": 5_000.0,
                "save-workbook": 1_000.0,
            },
            self.windows,
            self.clock,
        )

    def test_whole_task_eta_is_numeric_from_first_stage(self):
        self.estimator.observe("capture", 0, 4)
        self.assertAlmostEqual(self.estimator.eta_ms() or -1.0, 10_000.0)

        self.clock.advance(1.0)
        eta = self.estimator.eta_ms()
        self.assertIsNotNone(eta)
        self.assertLess(eta or 0.0, 10_000.0)

    def test_atomic_stage_interpolates_but_never_reaches_checkpoint(self):
        self.estimator.observe("open-workbook")
        self.clock.advance(20.0)
        projected = self.estimator.projected_fraction()
        self.assertIsNotNone(projected)
        self.assertLess(projected or 1.0, 0.60)
        self.assertGreater(projected or 0.0, 0.55)
        self.assertGreater(self.estimator.eta_ms() or 0.0, 0.0)

    def test_completed_units_correct_stage_and_future_eta(self):
        self.estimator.observe("capture", 0, 4)
        self.clock.advance(2.0)
        self.estimator.observe("capture", 2, 4)
        projected = self.estimator.projected_fraction()
        self.assertGreaterEqual(projected or 0.0, 0.35)
        self.assertLess(projected or 1.0, 0.55)

        self.clock.advance(2.0)
        self.estimator.observe("open-workbook")
        durations = self.estimator.finish()
        self.assertAlmostEqual(durations["capture"], 4_000.0)


class ReportTimingHistoryTests(unittest.TestCase):
    def _context(self, *, first: bool = False) -> ReportTimingContext:
        return ReportTimingContext(
            existing_report=True,
            report_size_bytes=5_000_000,
            image_count=19,
            result_count=1,
            first_in_session=first,
        )

    def test_empty_history_supplies_conservative_whole_report_model(self):
        estimate = ReportTimingHistory().estimate(self._context(first=True))
        self.assertGreater(sum(estimate.values()), 25_000.0)
        self.assertEqual(estimate["copy-template"], 1.0)

    def test_successful_history_round_trips_and_guides_next_run(self):
        history = ReportTimingHistory()
        history.record(
            self._context(),
            {
                "capture": 2_000.0,
                "open-workbook": 3_000.0,
                "save-workbook": 700.0,
            },
        )
        restored = ReportTimingHistory.from_json(history.to_json())
        estimate = restored.estimate(self._context())
        self.assertLess(estimate["capture"], 4_800.0)
        self.assertLess(estimate["open-workbook"], 5_000.0)

    def test_invalid_persisted_history_falls_back_without_crashing(self):
        history = ReportTimingHistory.from_json("{not json")
        self.assertGreater(sum(history.estimate(self._context()).values()), 0.0)


if __name__ == "__main__":
    unittest.main()
