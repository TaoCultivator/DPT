"""Pure progress-rate estimation helpers for long-running GUI tasks.

The estimator deliberately knows nothing about Qt or percentage phase weights.
It learns only from homogeneous units that have actually completed in the
current phase.  When the observations are insufficient or unstable it returns
``None`` instead of presenting a precise-looking but unreliable ETA.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Hashable
from dataclasses import asdict, dataclass
import json
import math
from statistics import median
import time
from typing import Mapping, Sequence

__all__ = [
    "ReportStageBudgetEstimator",
    "ReportTimingContext",
    "ReportTimingHistory",
    "UnitRateEstimator",
    "format_duration_ms",
]


Clock = Callable[[], float]
_NO_PHASE = object()


@dataclass(frozen=True)
class ReportTimingContext:
    """Complexity signals used to select comparable report timing samples."""

    existing_report: bool
    report_size_bytes: int
    image_count: int
    result_count: int
    first_in_session: bool


def _default_report_stage_budgets_ms(
    context: ReportTimingContext,
) -> dict[str, float]:
    """Return a conservative first-run model until local history is available."""

    size_ratio = max(0.35, min(4.0, context.report_size_bytes / 5_000_000.0))
    size_scale = math.sqrt(size_ratio)
    image_scale = max(0.25, context.image_count / 19.0)
    result_scale = max(1.0, float(context.result_count))
    cold_scale = 1.15 if context.first_in_session else 1.0
    return {
        "copy-template": 450.0 if not context.existing_report else 1.0,
        "prepare": 900.0 * result_scale,
        "capture": 4_800.0 * image_scale,
        "open-workbook": 5_000.0 * size_scale * cold_scale,
        "write-data": 500.0 * result_scale,
        "write-images": 8_000.0 * size_scale * image_scale,
        "finalize-workbook": 10_500.0 * size_scale * cold_scale,
        "save-workbook": 1_000.0 * size_scale,
    }


class ReportTimingHistory:
    """Persist and robustly reuse successful whole-report stage timings."""

    _VERSION = 1
    _MAX_SAMPLES = 30
    _MAX_NEIGHBORS = 5

    def __init__(self, samples: Sequence[Mapping[str, object]] | None = None) -> None:
        self._samples: list[dict[str, object]] = []
        for sample in samples or ():
            normalized = self._normalize_sample(sample)
            if normalized is not None:
                self._samples.append(normalized)
        self._samples = self._samples[-self._MAX_SAMPLES :]

    @classmethod
    def from_json(cls, raw: object) -> "ReportTimingHistory":
        try:
            payload = json.loads(str(raw or ""))
        except (TypeError, ValueError, json.JSONDecodeError):
            return cls()
        if not isinstance(payload, dict) or payload.get("version") != cls._VERSION:
            return cls()
        samples = payload.get("samples")
        return cls(samples if isinstance(samples, list) else ())

    def to_json(self) -> str:
        return json.dumps(
            {"version": self._VERSION, "samples": self._samples},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def estimate(self, context: ReportTimingContext) -> dict[str, float]:
        defaults = _default_report_stage_budgets_ms(context)
        if not self._samples:
            return defaults

        ranked = sorted(
            self._samples,
            key=lambda sample: self._distance(context, sample),
        )[: self._MAX_NEIGHBORS]
        estimates = dict(defaults)
        for stage, fallback in defaults.items():
            candidates: list[float] = []
            for sample in ranked:
                duration = sample["durations_ms"].get(stage)  # type: ignore[union-attr]
                if not isinstance(duration, (int, float)) or duration <= 0:
                    continue
                candidates.append(
                    float(duration) * self._stage_scale(stage, context, sample)
                )
            if candidates:
                # Retain a small conservative prior so one unusually fast run
                # cannot make the next atomic stage race to its cap.
                observed = float(median(candidates))
                estimates[stage] = max(1.0, 0.8 * observed + 0.2 * fallback)
        if context.existing_report:
            estimates["copy-template"] = 1.0
        return estimates

    def record(
        self,
        context: ReportTimingContext,
        durations_ms: Mapping[str, float],
    ) -> None:
        normalized_durations = {
            str(stage): float(value)
            for stage, value in durations_ms.items()
            if isinstance(value, (int, float))
            and math.isfinite(float(value))
            and float(value) > 0.0
        }
        if not normalized_durations:
            return
        self._samples.append(
            {
                "context": asdict(context),
                "durations_ms": normalized_durations,
            }
        )
        self._samples = self._samples[-self._MAX_SAMPLES :]

    @staticmethod
    def _normalize_sample(sample: Mapping[str, object]) -> dict[str, object] | None:
        context = sample.get("context")
        durations = sample.get("durations_ms")
        if not isinstance(context, dict) or not isinstance(durations, dict):
            return None
        try:
            normalized_context = {
                "existing_report": bool(context["existing_report"]),
                "report_size_bytes": max(0, int(context["report_size_bytes"])),
                "image_count": max(0, int(context["image_count"])),
                "result_count": max(1, int(context["result_count"])),
                "first_in_session": bool(context["first_in_session"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
        normalized_durations = {
            str(stage): float(value)
            for stage, value in durations.items()
            if isinstance(value, (int, float))
            and math.isfinite(float(value))
            and float(value) > 0.0
        }
        if not normalized_durations:
            return None
        return {
            "context": normalized_context,
            "durations_ms": normalized_durations,
        }

    @staticmethod
    def _distance(context: ReportTimingContext, sample: Mapping[str, object]) -> float:
        other = sample["context"]
        assert isinstance(other, dict)
        size_a = max(1, context.report_size_bytes)
        size_b = max(1, int(other["report_size_bytes"]))
        distance = abs(math.log(size_a / size_b))
        distance += abs(context.image_count - int(other["image_count"])) / 19.0
        distance += abs(context.result_count - int(other["result_count"])) * 0.75
        if context.existing_report != bool(other["existing_report"]):
            distance += 3.0
        if context.first_in_session != bool(other["first_in_session"]):
            distance += 1.5
        return distance

    @staticmethod
    def _stage_scale(
        stage: str,
        context: ReportTimingContext,
        sample: Mapping[str, object],
    ) -> float:
        other = sample["context"]
        assert isinstance(other, dict)
        size_ratio = max(
            0.25,
            min(
                4.0,
                max(1, context.report_size_bytes)
                / max(1, int(other["report_size_bytes"])),
            ),
        )
        image_ratio = max(
            0.25,
            min(4.0, max(1, context.image_count) / max(1, int(other["image_count"]))),
        )
        result_ratio = max(
            0.5,
            min(4.0, context.result_count / max(1, int(other["result_count"]))),
        )
        cold_ratio = 1.0
        other_first = bool(other["first_in_session"])
        if context.first_in_session and not other_first:
            cold_ratio = 1.15
        elif not context.first_in_session and other_first:
            cold_ratio = 1.0 / 1.15
        if stage in {"capture"}:
            return image_ratio
        if stage in {"write-images"}:
            return math.sqrt(size_ratio) * image_ratio
        if stage in {"prepare", "write-data"}:
            return result_ratio
        if stage in {"open-workbook", "finalize-workbook", "save-workbook"}:
            return math.sqrt(size_ratio) * cold_ratio
        return 1.0


class ReportStageBudgetEstimator:
    """Whole-report ETA and capped interpolation across real stage checkpoints."""

    def __init__(
        self,
        budgets_ms: Mapping[str, float],
        stage_windows: Mapping[str, tuple[float, float]],
        clock: Clock | None = None,
    ) -> None:
        self._clock: Clock = clock or time.perf_counter
        self._budgets_ms = {
            str(stage): max(1.0, float(value))
            for stage, value in budgets_ms.items()
            if math.isfinite(float(value)) and float(value) > 0.0
        }
        self._windows = {
            str(stage): (float(window[0]), float(window[1]))
            for stage, window in stage_windows.items()
        }
        self._order = [stage for stage in self._windows if stage in self._budgets_ms]
        self._current: str | None = None
        self._stage_started_at = 0.0
        self._observed_fraction = 0.0
        self._durations_ms: dict[str, float] = {}

    def observe(self, stage: str, completed: int = 0, total: int = 0) -> None:
        stage = str(stage)
        if stage not in self._windows or stage not in self._budgets_ms:
            return
        now = float(self._clock())
        if stage != self._current:
            self._close_current(now)
            self._current = stage
            self._stage_started_at = now
            self._observed_fraction = 0.0
        if total > 0:
            fraction = max(0.0, min(1.0, float(completed) / float(total)))
            self._observed_fraction = max(self._observed_fraction, fraction)

    def eta_ms(self) -> float | None:
        if self._current is None or self._current not in self._order:
            return None
        now = float(self._clock())
        elapsed_ms = self._current_elapsed_ms(now)
        predicted_ms = self._current_predicted_total_ms(elapsed_ms)
        if self._observed_fraction >= 1.0:
            current_remaining = 0.0
        else:
            current_remaining = max(
                250.0,
                predicted_ms - elapsed_ms,
                predicted_ms * 0.05,
            )
        current_index = self._order.index(self._current)
        future = sum(
            self._budgets_ms[stage]
            for stage in self._order[current_index + 1 :]
        )
        return max(1.0, current_remaining + future)

    def projected_fraction(self) -> float | None:
        if self._current is None:
            return None
        window = self._windows.get(self._current)
        if window is None:
            return None
        elapsed_ms = self._current_elapsed_ms(float(self._clock()))
        predicted_ms = self._current_predicted_total_ms(elapsed_ms)
        timed_fraction = elapsed_ms / max(1.0, predicted_ms)
        fraction = max(self._observed_fraction, timed_fraction)
        if self._observed_fraction < 1.0:
            fraction = min(fraction, 0.95)
        else:
            fraction = 1.0
        start, end = window
        return max(0.0, min(0.999, start + (end - start) * fraction))

    def finish(self) -> dict[str, float]:
        self._close_current(float(self._clock()))
        self._current = None
        return dict(self._durations_ms)

    def _current_elapsed_ms(self, now: float) -> float:
        if self._current is None:
            return 0.0
        elapsed = (now - self._stage_started_at) * 1000.0
        return max(0.0, elapsed) if math.isfinite(elapsed) else 0.0

    def _current_predicted_total_ms(self, elapsed_ms: float) -> float:
        if self._current is None:
            return 1.0
        baseline = self._budgets_ms[self._current]
        if self._observed_fraction <= 0.05 or elapsed_ms <= 0.0:
            return baseline
        current_run = elapsed_ms / self._observed_fraction
        current_run = max(baseline * 0.5, min(baseline * 3.0, current_run))
        return 0.35 * baseline + 0.65 * current_run

    def _close_current(self, now: float) -> None:
        if self._current is None:
            return
        elapsed_ms = self._current_elapsed_ms(now)
        if elapsed_ms > 0.0:
            self._durations_ms[self._current] = elapsed_ms


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
