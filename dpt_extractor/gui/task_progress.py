"""Pure progress-rate estimation helpers for long-running GUI tasks.

The estimator deliberately knows nothing about Qt or percentage phase weights.
It learns only from homogeneous units that have actually completed in the
current phase.  When the observations are insufficient or unstable it returns
``None`` instead of presenting a precise-looking but unreliable ETA.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Hashable
import math
from statistics import median
import time

__all__ = ["UnitRateEstimator", "format_duration_ms"]


Clock = Callable[[], float]
_NO_PHASE = object()


class UnitRateEstimator:
    """Estimate remaining time from recently completed homogeneous units.

    ``start_phase`` establishes a baseline; units already complete at that
    point do not count as timing observations.  ``observe`` records elapsed
    time only when ``completed`` advances.  Changing the phase key, or moving
    the completed counter backwards, discards all previous rate samples.

    The estimate uses the median of at most five recent per-unit durations.
    It is withheld until at least two independent completion intervals have
    been observed, when recent unit times are too dispersed, or when the
    current/most recently completed unit is markedly slower than the
    established history.
    """

    _MAX_SAMPLES = 5
    _MIN_OBSERVED_INTERVALS = 2
    _MAX_SPREAD_RATIO = 3.0
    _MAX_RELATIVE_MAD = 0.60
    _SLOW_UNIT_FACTOR = 2.5

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or time.perf_counter
        self._phase_key: Hashable | object = _NO_PHASE
        self._completed = 0
        self._total = 0
        self._last_completed_at = 0.0
        self._observed_intervals = 0
        self._unit_seconds: deque[float] = deque(maxlen=self._MAX_SAMPLES)

    def start_phase(self, key: Hashable, completed: int, total: int) -> None:
        """Start or restart a homogeneous unit phase at the current clock."""

        self._phase_key = key
        self._completed = max(0, int(completed))
        self._total = max(0, int(total))
        self._last_completed_at = float(self._clock())
        self._observed_intervals = 0
        self._unit_seconds.clear()

    def observe(self, key: Hashable, completed: int, total: int) -> None:
        """Observe a completed-unit counter without inventing interim work."""

        completed_i = max(0, int(completed))
        total_i = max(0, int(total))
        now = float(self._clock())

        if self._phase_key != key:
            self.start_phase(key, completed_i, total_i)
            return

        if completed_i < self._completed:
            self.start_phase(key, completed_i, total_i)
            return

        self._total = total_i
        delta = completed_i - self._completed
        if delta <= 0:
            # Repeated UI refreshes must not move the timing baseline.  Keeping
            # it fixed lets eta_ms() count down instead of growing while the
            # completed counter is unchanged.
            return

        elapsed = now - self._last_completed_at
        self._completed = completed_i
        self._last_completed_at = now
        if not math.isfinite(elapsed) or elapsed <= 0.0:
            return

        per_unit = elapsed / float(delta)
        if not math.isfinite(per_unit) or per_unit <= 0.0:
            return

        # A batched callback supplies only one elapsed interval, even if it
        # reports several completed units.  Treating that single average as
        # several independent samples would manufacture confidence and could
        # expose a precise ETA before stability has actually been observed.
        self._observed_intervals += 1
        self._unit_seconds.append(per_unit)

    def eta_ms(self) -> float | None:
        """Return milliseconds remaining, or ``None`` when confidence is low."""

        if self._phase_key is _NO_PHASE:
            return None
        if self._completed >= self._total:
            return 0.0
        if self._observed_intervals < self._MIN_OBSERVED_INTERVALS:
            return None

        typical = self._stable_unit_seconds()
        if typical is None:
            return None

        now = float(self._clock())
        current_elapsed = max(0.0, now - self._last_completed_at)
        if not math.isfinite(current_elapsed):
            return None

        samples = list(self._unit_seconds)
        sample_mad = median(abs(value - typical) for value in samples)
        slow_limit = max(
            typical * self._SLOW_UNIT_FACTOR,
            typical + 4.0 * sample_mad,
        )
        if current_elapsed > slow_limit:
            return None

        remaining_units = max(0, self._total - self._completed)
        remaining_seconds = typical * float(remaining_units) - current_elapsed
        # Zero is authoritative only when all units have completed.  If an
        # in-progress unit has already consumed the whole prediction, the rate
        # model is stale and an unknown ETA is more honest than "0 ms".
        if remaining_units > 0 and remaining_seconds <= 0.0:
            return None
        return max(0.0, remaining_seconds * 1000.0)

    def _stable_unit_seconds(self) -> float | None:
        samples = [
            value
            for value in self._unit_seconds
            if math.isfinite(value) and value > 0.0
        ]
        if len(samples) < 2:
            return None

        typical = float(median(samples))
        if typical <= 0.0:
            return None

        smallest = min(samples)
        largest = max(samples)
        if smallest <= 0.0 or largest / smallest >= self._MAX_SPREAD_RATIO:
            return None

        sample_mad = float(median(abs(value - typical) for value in samples))
        if sample_mad / typical > self._MAX_RELATIVE_MAD:
            return None

        history = samples[:-1]
        if history:
            history_mid = float(median(history))
            history_mad = float(
                median(abs(value - history_mid) for value in history)
            )
            latest = samples[-1]
            latest_limit = max(
                history_mid * self._SLOW_UNIT_FACTOR,
                history_mid + 4.0 * history_mad,
            )
            if latest > latest_limit:
                return None
        return typical


def format_duration_ms(ms: float) -> str:
    """Format a duration and normalize rounding across minute boundaries."""

    value = float(ms)
    if not math.isfinite(value):
        return "--"
    value = max(0.0, value)
    if value < 1000.0:
        rounded_ms = int(round(value))
        # A positive running-phase estimate must never render as ``0 ms``.
        # Zero is reserved for the successful 100% terminal state; sub-ms
        # predictions are still in progress and therefore display at least 1 ms.
        if value > 0.0:
            rounded_ms = max(1, rounded_ms)
        return f"{rounded_ms} ms"
    if value < 60000.0:
        seconds = value / 1000.0
        rounded_tenths = round(seconds, 1)
        if rounded_tenths < 60.0:
            return f"{rounded_tenths:.1f} s"

    total_seconds = int(round(value / 1000.0))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds}s"
