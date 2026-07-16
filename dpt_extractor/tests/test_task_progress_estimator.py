from __future__ import annotations

import unittest

from dpt_extractor.gui.task_progress import UnitRateEstimator, format_duration_ms


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


if __name__ == "__main__":
    unittest.main()
