"""Event-local current platforms and the independent Pdmax measurement."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dpt_extractor.metrics.energy import peak_power_kw
from dpt_extractor.metrics.iec_windows import IntegrationWindow
from dpt_extractor.metrics.irr_measure import (
    default_irr_trr_measure,
    irr_parameter_peak_index,
)
from dpt_extractor.metrics.plateau_level import (
    _plateau_mid_without_isolated_spikes,
    recovery_stable_cursor_range_indices,
)
from dpt_extractor.models.results import SegmentIndices


@dataclass(frozen=True)
class RecoveryCurrentInterval:
    a_idx: int
    b_idx: int
    pre_level: float
    post_level: float
    current_peak_idx: int


def _quiet_post_reference(
    irr: np.ndarray, peak: int, end: int, dt: float, pre: float, post: float,
) -> float | None:
    """Recover a ringing-biased reference without accepting an unproven band.

    Use multiple complete, event-local bands near the original post rail.
    The following switching edge/rail must not become a reference.  A new
    reference still has to pass recovery_stable_cursor_range_indices; this
    estimator never publishes an endpoint or relaxes its quiet/rebound gates.
    """
    if not np.all(np.isfinite([dt, pre, post, irr[peak]])) or dt <= 0.0:
        return None
    width = max(8, int(round(200e-9 / dt)))
    first = peak + max(2, int(round(30e-9 / dt)))
    excursion = max(abs(float(irr[peak]) - pre), abs(post - pre))
    if excursion <= 1e-12:
        return None
    candidates: list[tuple[float, float]] = []
    for start in range(first, end - width + 2, width):
        band = irr[start:start + width]
        if len(band) != width or not np.all(np.isfinite(band)):
            continue
        p05, p95 = np.percentile(band, [5.0, 95.0])
        center = float(np.median(band))
        if abs(center - post) > 0.15 * excursion:
            continue
        if abs(center - pre) <= abs(center - post):
            # A large recovery peak must not make a later return to the
            # forward-conduction rail look like a quiet recovered platform.
            continue
        candidates.append((float(p95 - p05), center))
    if len(candidates) < 2:
        return None
    candidates.sort()
    quiet_count = max(2, int(np.ceil(0.25 * len(candidates))))
    return float(np.median([center for _, center in candidates[:quiet_count]]))


def recovery_current_stable_interval(
    t: np.ndarray,
    irr: np.ndarray,
    segs: SegmentIndices,
    dt: float,
    *,
    forward_hint: float | None = None,
    refine_post_reference: bool = False,
) -> RecoveryCurrentInterval | None:
    """The adjacent complete quiet bands already used by the Irr cursor card.

    Search through this recovery event, not through the displayed viewport.
    No qualifying band means no automatic interval, never a guessed endpoint.
    Neither the Irr peak nor any slope/energy measurement is changed here.
    Only Pdmax opts into reference refinement when an old Trr-derived rail
    cannot qualify; the existing Irr card keeps its exact selection policy.
    """
    irr = np.asarray(irr, dtype=np.float64)
    n = min(len(t), len(irr))
    if n < 2:
        return None
    rr0, rr1 = segs.reverse_recovery
    on0, on1 = segs.turn_on
    marker = default_irr_trr_measure(
        t, irr, rr0, rr1, segs.pulse2_on, on0, on1,
        pulse2_off=segs.pulse2_off,
    )
    peak_idx = int(marker.peak_idx) if marker is not None else int(
        irr_parameter_peak_index(irr, rr0, rr1, segs.pulse2_on, on0, on1)
    )
    peak_idx = max(0, min(peak_idx, n - 1))
    dt = max(float(dt), 1e-15)
    if marker is not None and marker.stable_level is not None:
        post_level = float(marker.stable_level)
    else:
        base0 = min(n - 1, peak_idx + max(2, int(100e-9 / dt)))
        base1 = min(
            n,
            max(base0 + 3, min(int(segs.pulse2_off), peak_idx + int(700e-9 / dt))),
        )
        post_level = float(_plateau_mid_without_isolated_spikes(irr[base0:base1]))
    pre_lo = max(
        0,
        int(segs.pulse1_off) + 1,
        min(int(on0), int(segs.pulse2_on) - int(round(700e-9 / dt))),
    )
    reference = irr[
        pre_lo:min(peak_idx, pre_lo + max(8, int(round(200e-9 / dt))))
    ]
    finite_pre = reference[np.isfinite(reference)]
    if len(finite_pre) < 8:
        return None
    pre_level = float(np.median(finite_pre))
    pre_spread = float(np.ptp(np.percentile(finite_pre, [5.0, 95.0])))
    if forward_hint is not None:
        hint = float(forward_hint)
        excursion = max(
            abs(float(irr[peak_idx]) - pre_level), abs(post_level - pre_level)
        )
        if np.isfinite(hint) and abs(hint - pre_level) <= max(
            0.10 * excursion, 2.0 * pre_spread
        ):
            pre_level = hint
    post_hi = min(n - 1, int(segs.pulse2_off) - max(1, int(round(50e-9 / dt))))
    pair = recovery_stable_cursor_range_indices(
        irr, pre_lo, peak_idx, post_hi, dt, pre_level, post_level
    )
    if pair is None and refine_post_reference:
        refined = _quiet_post_reference(irr, peak_idx, post_hi, dt, pre_level, post_level)
        if refined is not None:
            pair = recovery_stable_cursor_range_indices(
                irr, pre_lo, peak_idx, post_hi, dt, pre_level, refined
            )
            if pair is not None:
                post_level = refined
    if pair is None:
        return None
    return RecoveryCurrentInterval(*pair, pre_level, post_level, peak_idx)


@dataclass(frozen=True)
class RecoveryPowerContext:
    current_interval: RecoveryCurrentInterval
    t_start: float
    t_end: float
    peak_idx: int
    value_kw: float

    def as_integration_window(self) -> IntegrationWindow:
        return IntegrationWindow(
            self.current_interval.a_idx, self.current_interval.b_idx,
            self.t_start, self.t_end,
        )


def recovery_power_context(
    t: np.ndarray,
    v_diode: np.ndarray,
    irr: np.ndarray,
    segs: SegmentIndices,
    dt: float,
    *,
    forward_hint: float | None = None,
) -> RecoveryPowerContext | None:
    """Raw |Vd|*|Irr| maximum in [pre-stable A, post-stable B), not Err's window."""
    interval = recovery_current_stable_interval(
        t, irr, segs, dt, forward_hint=forward_hint, refine_post_reference=True
    )
    if interval is None:
        return None
    a, b = interval.a_idx, interval.b_idx
    if b >= min(len(t), len(v_diode), len(irr)) or a >= b:
        return None
    raw = np.abs(np.asarray(v_diode[a:b], dtype=np.float64)) * np.abs(irr[a:b])
    finite_indices = np.flatnonzero(np.isfinite(raw))
    if not len(finite_indices):
        return None
    peak_idx = a + int(finite_indices[np.argmax(raw[finite_indices])])
    window = IntegrationWindow(a, b, float(t[a]), float(t[b]))
    return RecoveryPowerContext(
        interval, window.t_start, window.t_end, peak_idx,
        peak_power_kw(v_diode, irr, window, absolute=True),
    )
