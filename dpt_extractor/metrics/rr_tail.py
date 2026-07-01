from __future__ import annotations

import numpy as np


def reverse_recovery_tail_end_index(
    t: np.ndarray,
    rr1: int,
    on1: int | None = None,
    *,
    peak_idx: int | None = None,
    pulse2_off: int | None = None,
    dt: float | None = None,
    tail_ns: float = 900.0,
) -> int:
    """Search tail for Irr/Trr/Err after the recovery peak.

    Some fast Rg waveforms settle just after the detected turn-on segment.  The
    electrical event is still the same reverse-recovery lobe, so the marker
    search must include a short post-peak tail instead of stopping exactly at
    the segment boundary.
    """
    n = len(t)
    if n <= 0:
        return 0
    rr1_i = max(0, min(int(rr1), n - 1))
    end = rr1_i
    if on1 is not None:
        end = max(end, max(0, min(int(on1), n - 1)))

    dt_s = float(dt) if dt is not None and float(dt) > 0.0 else 0.0
    if dt_s <= 0.0 and n >= 2:
        diffs = np.diff(np.asarray(t, dtype=np.float64))
        diffs = diffs[np.isfinite(diffs) & (diffs > 0.0)]
        dt_s = float(np.median(diffs)) if diffs.size else 1e-9
    if dt_s <= 0.0:
        dt_s = 1e-9

    tail_samples = max(8, int(float(tail_ns) * 1e-9 / max(dt_s, 1e-15)))
    anchor = rr1_i
    if peak_idx is not None:
        anchor = max(0, min(int(peak_idx), n - 1))
    end = max(end, min(n - 1, anchor + tail_samples))

    if pulse2_off is not None:
        cap = max(0, min(int(pulse2_off), n - 1))
        if cap > anchor:
            end = min(end, cap)
    return max(rr1_i, min(int(end), n - 1))
