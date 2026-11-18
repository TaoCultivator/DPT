"""Default display span for extreme/peak parameter cards.

Every DPT parameter card whose numeric value is an extreme (max/peak) inside a
time window must place its default A/B *display* interval around the
authoritative peak, not against one edge of the event window.  The user
requirement (2026-11-18) is:

- ``A = peak - round(300ns / dt)``, ``B = peak + round(300ns / dt)``;
- both clipped to the parameter event window ``[lo, hi]``;
- when the peak sits closer than 300 ns to one edge, the half span narrows to
  the smaller available side so the interval stays centred on the peak;
- ``A < B`` always holds, and the peak index is always inside the interval;
- degenerate windows return ``None`` so each card can fall back to its legacy
  stable-platform placement instead of raising.

Because the numeric definition of these cards is "maximum of |value| inside
the default A/B interval", and the authoritative peak index belongs to that
interval, the published number cannot change when only the display span
changes.
"""

from __future__ import annotations

import numpy as np


DEFAULT_EXTREME_HALF_SPAN_S = 300e-9


def extreme_display_span_indices(
    peak_idx: int,
    lo: int,
    hi: int,
    dt: float,
    *,
    half_span_s: float = DEFAULT_EXTREME_HALF_SPAN_S,
) -> tuple[int, int] | None:
    """Return ``(a_idx, b_idx)`` centred on ``peak_idx`` (peak +/- half span).

    ``None`` means the window/peak combination is degenerate and the caller
    must keep its legacy placement.
    """

    lo = int(lo)
    hi = int(hi)
    if hi <= lo:
        return None
    peak_idx = int(peak_idx)
    if peak_idx < lo or peak_idx > hi:
        return None
    dt_s = max(float(dt), 1e-15)
    radius = max(1, int(round(float(half_span_s) / dt_s)))
    left_room = peak_idx - lo
    right_room = hi - peak_idx
    if left_room < 1 and right_room < 1:
        return None
    half = min(radius, left_room, right_room)
    if half >= 1:
        a_idx = peak_idx - half
        b_idx = peak_idx + half
    else:
        # The peak is pinned to one window edge: clamp each side separately.
        a_idx = max(lo, peak_idx - radius)
        b_idx = min(hi, peak_idx + radius)
    if b_idx <= a_idx:
        return None
    return int(a_idx), int(b_idx)


def stage_union_span_indices(
    peak_idx: int,
    stage_lo: int | None,
    stage_hi: int | None,
    data_lo: int,
    data_hi: int,
    dt: float,
    *,
    half_span_s: float = DEFAULT_EXTREME_HALF_SPAN_S,
    min_span_s: float = 0.0,
) -> tuple[int, int] | None:
    """Peak +/- half span UNION the physical stage bracket, clipped to data.

    Cards that must keep expressing a physical stage (Base->Top etc.) cannot
    clip the peak window to a bare event segment: when the peak sits on the
    segment start the interval collapses to a few tens of nanoseconds.  The
    rule used here is

        A = min(peak - half, stage_lo)
        B = max(peak + half, stage_hi)

    then both are clipped to ``[data_lo, data_hi]``, ``min_span_s`` is
    enforced around the interval centre, and ``A < B`` plus ``peak`` inside
    the interval are re-verified.  ``None`` means the caller must keep its
    legacy placement.
    """

    data_lo = int(data_lo)
    data_hi = int(data_hi)
    if data_hi <= data_lo:
        return None
    peak_idx = int(peak_idx)
    if peak_idx < data_lo or peak_idx > data_hi:
        return None
    dt_s = max(float(dt), 1e-15)
    radius = max(1, int(round(float(half_span_s) / dt_s)))
    a_idx = peak_idx - radius
    b_idx = peak_idx + radius
    if stage_lo is not None:
        a_idx = min(a_idx, int(stage_lo))
    if stage_hi is not None:
        b_idx = max(b_idx, int(stage_hi))
    min_span = max(0, int(round(float(min_span_s) / dt_s)))
    if min_span > 0 and (b_idx - a_idx) < min_span:
        centre = 0.5 * (a_idx + b_idx)
        a_idx = int(np.floor(centre - 0.5 * min_span))
        b_idx = a_idx + min_span
    a_idx = max(data_lo, a_idx)
    b_idx = min(data_hi, b_idx)
    if b_idx <= a_idx:
        return None
    if not a_idx <= peak_idx <= b_idx:
        return None
    return int(a_idx), int(b_idx)

def window_extreme_value(values: np.ndarray, i0: int, i1: int) -> float:
    """``max(|values[i0:i1+1]|)`` -- the number a display interval must keep."""

    block = np.asarray(values, dtype=np.float64)[int(i0) : int(i1) + 1]
    if block.size == 0:
        return 0.0
    block = block[np.isfinite(block)]
    if block.size == 0:
        return 0.0
    return float(np.max(np.abs(block)))