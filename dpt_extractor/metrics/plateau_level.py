"""无震荡平台段中值：(max + min) / 2。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dpt_extractor.metrics.default_spans import (
    DEFAULT_EXTREME_HALF_SPAN_S,
    extreme_display_span_indices,
)

# 默认 Ha/Hb 只在跃变附近短窗内搜平台，避免对整段波形 O(n²) 滑动窗
_PLATEAU_PROBE = 96


def _quiet_plateau_mid(band: np.ndarray, *, prefer: str) -> float:
    """在短窗 band 内找最平稳子段，返回 (max+min)/2。"""
    band = np.asarray(band, dtype=np.float64)
    n = len(band)
    if n < 3:
        return plateau_mid(band)
    v_lo = float(np.min(band))
    v_hi = float(np.max(band))
    span = max(v_hi - v_lo, 1e-9)
    dy_lim = max(0.75, 0.012 * span)
    diffs = np.abs(np.diff(band))
    wlen_hi = min(22, n)
    wlen_lo = min(10, n)
    if wlen_hi < wlen_lo:
        return plateau_mid(band)
    best_span = float("inf")
    best_sub = band
    for wlen in range(wlen_lo, wlen_hi + 1):
        nwin = n - wlen + 1
        if nwin < 1:
            break
        for w0 in range(nwin):
            if w0 + wlen - 2 < len(diffs):
                if float(np.max(diffs[w0 : w0 + wlen - 1])) > dy_lim:
                    continue
            sub = band[w0 : w0 + wlen]
            mu = float(np.mean(sub))
            if prefer == "low" and mu > v_lo + 0.42 * span:
                continue
            if prefer == "high" and mu < v_lo + 0.58 * span:
                continue
            s = float(np.max(sub) - np.min(sub))
            if s < best_span:
                best_span = s
                best_sub = sub
    return plateau_mid(best_sub)


def plateau_mid(seg: np.ndarray) -> float:
    block = np.asarray(seg, dtype=np.float64)
    if len(block) == 0:
        return 0.0
    if len(block) < 3:
        return float(np.mean(block))
    return 0.5 * (float(np.max(block)) + float(np.min(block)))


def _plateau_mid_without_isolated_spikes(seg: np.ndarray) -> float:
    """Return the visible stable-band midpoint while ignoring one-sample spikes.

    A stable oscilloscope plateau can legitimately have a fairly wide ripple, so
    percentile clipping would move the requested ``(max + min) / 2`` centre.
    Only samples whose two neighbours agree while the sample itself makes a
    much larger excursion than the normal adjacent ripple are excluded.
    """
    block = np.asarray(seg, dtype=np.float64)
    if len(block) < 4:
        return plateau_mid(block)
    diffs = np.abs(np.diff(block))
    normal_step = float(np.percentile(diffs, 90.0))
    jump_limit = max(1e-9, 8.0 * normal_step)
    prev = block[:-2]
    cur = block[1:-1]
    nxt = block[2:]
    neighbour_gap = np.abs(nxt - prev)
    excursion = np.abs(cur - 0.5 * (prev + nxt))
    isolated = (excursion > jump_limit) & (neighbour_gap <= 0.5 * jump_limit)

    # A capture/export boundary can place the only bad sample exactly at the
    # first or last point of the requested stable band.  Those endpoints do
    # not have neighbours on both sides, so compare them with the first/last
    # two in-band samples instead.  Requiring that pair to agree keeps a real
    # sloping/ringing endpoint while removing only a one-sample excursion.
    first_neighbour_gap = abs(float(block[2] - block[1]))
    first_excursion = abs(float(block[0] - 0.5 * (block[1] + block[2])))
    first_isolated = (
        first_excursion > jump_limit
        and first_neighbour_gap <= 0.5 * jump_limit
    )
    last_neighbour_gap = abs(float(block[-2] - block[-3]))
    last_excursion = abs(float(block[-1] - 0.5 * (block[-2] + block[-3])))
    last_isolated = (
        last_excursion > jump_limit
        and last_neighbour_gap <= 0.5 * jump_limit
    )

    # Preserve the historical whole-band P90 decisions above, then supplement
    # them with strict local shape evidence when sparse spikes hide each other.
    # A local interior candidate must be a one-step excursion with an agreeing
    # neighbour pair and quiet continuation on both available sides.  Endpoints
    # require three consecutive in-band neighbours to form the same platform.
    # Only a candidate that currently determines the remaining band's min/max
    # can be removed.  Repeating after each removal lets a smaller second spike
    # become visible without clipping normal quantisation or damped ringing.
    keep = np.ones(len(block), dtype=bool)
    keep[1:-1] = ~isolated
    keep[0] = not first_isolated
    keep[-1] = not last_isolated

    for _iteration in range(len(block)):
        remaining = np.flatnonzero(keep)
        if len(remaining) < 4:
            break
        values = block[remaining]
        remaining_min = float(np.min(values))
        remaining_max = float(np.max(values))
        remaining_span = remaining_max - remaining_min
        if remaining_span <= 0.0:
            break
        excursion_limit = max(1e-9, 0.45 * remaining_span)
        remove_positions: list[int] = []

        for pos in range(1, len(values) - 1):
            prev_value = float(values[pos - 1])
            cur_value = float(values[pos])
            next_value = float(values[pos + 1])
            if cur_value != remaining_min and cur_value != remaining_max:
                continue
            outer_steps: list[float] = []
            if pos >= 2:
                outer_steps.append(abs(prev_value - float(values[pos - 2])))
            if pos + 2 < len(values):
                outer_steps.append(abs(float(values[pos + 2]) - next_value))
            continuation_step = max(outer_steps) if outer_steps else 0.0
            local_step = max(abs(next_value - prev_value), continuation_step)
            local_excursion = abs(cur_value - 0.5 * (prev_value + next_value))
            if (
                local_excursion > max(1e-9, 8.0 * local_step)
                and local_excursion >= excursion_limit
            ):
                remove_positions.append(pos)

        first_gap = abs(float(values[2] - values[1]))
        first_continuation = abs(float(values[3] - values[2]))
        first_local_excursion = abs(
            float(values[0] - 0.5 * (values[1] + values[2]))
        )
        if (
            float(values[0]) in (remaining_min, remaining_max)
            and first_local_excursion
            > max(1e-9, 8.0 * max(first_gap, first_continuation))
            and first_local_excursion >= excursion_limit
        ):
            remove_positions.append(0)

        last_gap = abs(float(values[-2] - values[-3]))
        last_continuation = abs(float(values[-3] - values[-4]))
        last_local_excursion = abs(
            float(values[-1] - 0.5 * (values[-2] + values[-3]))
        )
        if (
            float(values[-1]) in (remaining_min, remaining_max)
            and last_local_excursion
            > max(1e-9, 8.0 * max(last_gap, last_continuation))
            and last_local_excursion >= excursion_limit
        ):
            remove_positions.append(len(values) - 1)

        if not remove_positions:
            break
        remove_positions = sorted(set(remove_positions))
        if len(remaining) - len(remove_positions) < 2:
            break
        keep[remaining[remove_positions]] = False

    cleaned = block[keep]
    return plateau_mid(cleaned if len(cleaned) >= 2 else block)


def _transition_index_rise(seg: np.ndarray) -> int:
    dy = np.diff(seg.astype(np.float64))
    ipk = int(np.argmax(dy))
    return max(5, min(ipk, len(seg) - 6))


def _transition_index_fall(seg: np.ndarray) -> int:
    dy = np.diff(seg.astype(np.float64))
    ipk = int(np.argmin(dy))
    return max(5, min(ipk, len(seg) - 6))


def dvdt_rise_base_top_mid(seg: np.ndarray) -> tuple[float, float]:
    """
    上升沿 dv/dt：Hb=段窗前端低平台，Ha=段窗后端高平台（各取短窗）。
    dv/dt 搜索窗已包住关断沿，用首尾短窗即可，避免全段滑动扫描。
    """
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 12:
        v_lo = float(np.min(seg)) if len(seg) else 0.0
        v_hi = float(np.max(seg)) if len(seg) else 0.0
        mid = 0.5 * (v_lo + v_hi)
        return mid, mid
    n = len(seg)
    n_pre = min(_PLATEAU_PROBE, max(12, n // 5))
    n_post = min(_PLATEAU_PROBE, max(12, n // 5))
    pre_w = seg[:n_pre]
    post_w = seg[-n_post:]
    base = _quiet_plateau_mid(pre_w, prefer="low")
    top = _quiet_plateau_mid(post_w, prefer="high")
    return base, top


def turn_off_dvdt_base_top_levels(
    t: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
) -> tuple[float, float]:
    """关断 dv/dt 的本地 Base/Top 稳定带中心。

    Top 取关断参数本地窗口后端的安静高平台；Base 取关断窗口起点前
    0.5~0.1us 的稳定低平台，并按该稳定段 ``(max + min) / 2``
    定位到可见波形带正中。Base 平台窗允许位于交点搜索窗之前，但仍属于
    同一关断参数本地测量上下文。
    """
    t = np.asarray(t, dtype=np.float64)
    vce = np.asarray(vce, dtype=np.float64)
    n = min(len(t), len(vce))
    if n < 2:
        return 0.0, 0.0
    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 1, min(int(i1), n - 1))
    seg = vce[i0 : i1 + 1]
    base, top = dvdt_rise_base_top_mid(seg)
    if len(seg) < 4:
        return float(base), float(top)

    # The last few nanoseconds of a blocking plateau can sit on one rail of a
    # small periodic ripple.  That rail is quiet, but it is not the visible
    # centre of the horizontal Top band used by an oscilloscope cursor.  Use a
    # complete event-local ~200 ns band so different ripple periods and sample
    # rates converge on the same raw-waveform midpoint.
    dt_s = float(np.nanmedian(np.diff(t[:n])))
    if np.isfinite(dt_s) and dt_s > 0.0:
        top_n = max(16, int(round(200e-9 / dt_s)))
        top_w = seg[-min(len(seg), top_n) :]
        if len(top_w) >= 4:
            stable_top = _plateau_mid_without_isolated_spikes(top_w)
            if abs(float(stable_top) - float(top)) > max(
                3.0,
                0.010 * max(abs(float(top)), 1.0),
            ):
                top = float(stable_top)

    base_anchor_time = float(t[i0])
    base_lo_t = max(float(t[0]), base_anchor_time - 0.5e-6)
    base_hi_t = min(float(t[n - 1]), base_anchor_time - 0.1e-6)
    if base_hi_t <= base_lo_t:
        return float(base), float(top)
    b0 = int(np.searchsorted(t, base_lo_t, side="left"))
    b1 = int(np.searchsorted(t, base_hi_t, side="right"))
    b0 = max(0, min(b0, n - 1))
    b1 = max(b0 + 1, min(b1, n))
    if b1 - b0 >= 2:
        base = _plateau_mid_without_isolated_spikes(vce[b0:b1])
    return float(base), float(top)


def turn_off_delta_vce_blocking_top(
    vce: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
) -> float:
    """Single-pulse ΔVce reference on the DUT post-off blocking plateau.

    A single-pulse capture has no inter-pulse DUT blocking plateau.  Using the
    opposite device's pre-off bus channel makes the ΔVce horizontal reference
    impossible to intersect on the DUT Vce trace when the two probes have a
    small offset.  Use the last about-200 ns of the DUT's own turn-off window
    and return the stable visible band centre, with isolated spikes excluded.
    """

    arr = np.asarray(vce, dtype=np.float64)
    if len(arr) == 0:
        return 0.0
    lo = max(0, min(int(i0), len(arr) - 1))
    hi = max(lo, min(int(i1), len(arr) - 1))
    window_n = max(16, int(round(200e-9 / max(float(dt), 1e-15))))
    stable_lo = max(lo, hi - window_n + 1)
    return float(_plateau_mid_without_isolated_spikes(arr[stable_lo : hi + 1]))


def _rolling_stable_level_centers(
    values: np.ndarray,
    lo: int,
    hi: int,
    *,
    target: float,
    event_span: float,
    window_n: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return candidate window centres and normalized stability scores."""

    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    if n == 0:
        return np.asarray([], dtype=np.int64), np.asarray([], dtype=np.float64)
    lo = max(0, min(int(lo), n - 1))
    hi = max(lo, min(int(hi), n - 1))
    width = max(1, min(int(window_n), hi - lo + 1))
    block = np.asarray(arr[lo : hi + 1], dtype=np.float64)
    finite = np.isfinite(block)
    if not np.all(finite):
        block = block.copy()
        block[~finite] = float(target)

    prefix = np.concatenate(([0.0], np.cumsum(block, dtype=np.float64)))
    prefix_sq = np.concatenate(
        ([0.0], np.cumsum(block * block, dtype=np.float64))
    )
    sums = prefix[width:] - prefix[:-width]
    sums_sq = prefix_sq[width:] - prefix_sq[:-width]
    means = sums / float(width)
    variances = np.maximum(sums_sq / float(width) - means * means, 0.0)
    stds = np.sqrt(variances)
    scale = max(abs(float(event_span)), 1.0)
    scores = np.abs(means - float(target)) / scale + stds / scale
    starts = np.arange(lo, lo + len(scores), dtype=np.int64)
    centers = starts + width // 2
    return centers, scores


def stable_platform_cursor_range_indices(
    values: np.ndarray,
    pre_lo: int,
    pre_hi: int,
    post_lo: int,
    post_hi: int,
    dt: float,
    pre_level: float,
    post_level: float,
) -> tuple[int, int]:
    """Place A/B on two declared stable bands without redefining amplitudes.

    The helper is intentionally display-only.  ``pre_level`` and
    ``post_level`` are canonical Top/Base values supplied by the extraction
    context; rolling windows only select quiet event-local *times*.  A is the
    latest acceptable point in the pre-transition band and B is the earliest
    acceptable point in the post-transition band.  The nearest raw sample in
    each selected band is returned so a highlighted trace visibly passes
    through the cursor.
    """

    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    if n < 2:
        return 0, 0
    pre_lo = max(0, min(int(pre_lo), n - 1))
    pre_hi = max(pre_lo, min(int(pre_hi), n - 1))
    post_lo = max(pre_hi + 1, min(int(post_lo), n - 1))
    post_hi = max(post_lo, min(int(post_hi), n - 1))
    if post_lo >= n:
        post_lo = post_hi = n - 1

    dt_s = max(float(dt), 1e-15)
    stable_n = max(8, int(round(120e-9 / dt_s)))
    event_span = max(
        abs(float(post_level) - float(pre_level)),
        float(np.nanpercentile(arr, 95) - np.nanpercentile(arr, 5)),
        1.0,
    )

    def _select(
        lo: int,
        hi: int,
        level: float,
        *,
        prefer_latest: bool,
    ) -> int:
        centers, scores = _rolling_stable_level_centers(
            arr,
            lo,
            hi,
            target=float(level),
            event_span=event_span,
            window_n=stable_n,
        )
        if len(centers):
            score_limit = 0.05 + max(0.5, 0.025 * event_span) / event_span
            valid = np.flatnonzero(scores <= score_limit)
            if len(valid):
                chosen = int(valid[-1] if prefer_latest else valid[0])
            else:
                chosen = int(np.argmin(scores))
            center = int(centers[chosen])
        else:
            center = int((lo + hi) // 2)

        radius = max(1, stable_n // 2)
        sample_lo = max(int(lo), center - radius)
        sample_hi = min(int(hi), center + radius)
        candidates = np.arange(sample_lo, sample_hi + 1, dtype=np.int64)
        if len(candidates) == 0:
            return center
        level_error = np.abs(arr[candidates] - float(level))
        time_penalty = (
            1e-6
            * event_span
            * np.abs(candidates.astype(np.float64) - float(center))
            / float(radius)
        )
        return int(candidates[int(np.argmin(level_error + time_penalty))])

    a_idx = _select(pre_lo, pre_hi, float(pre_level), prefer_latest=True)
    b_idx = _select(post_lo, post_hi, float(post_level), prefer_latest=False)
    return int(a_idx), int(max(a_idx + 1, b_idx))


def recovery_stable_cursor_range_indices(
    values: np.ndarray,
    search_start: int,
    peak_idx: int,
    search_end: int,
    dt: float,
    pre_level: float,
    post_level: float,
    *,
    bound_post_noise_to_pre: bool = False,
) -> tuple[int, int] | None:
    """Display recovery's adjacent pre-edge and first settled post-ringing bands.

    The caller owns the signed levels and authoritative recovery peak.  This
    function only selects default A/B times; it does not measure a new peak or
    change Irr/Vrr/Trr/Err.  In particular, the segment start may already be on the
    commutation edge and must not truncate the available pre-edge history.
    Both endpoints require a complete 200 ns band.  A later rebound rejects
    a temporary quiet gap, and missing evidence never selects a least-bad band.
    Vrr uses the pre-edge noise bound on the same voltage acquisition range;
    sustained voltage ringing must not define its own relaxed noise tolerance.
    The default preserves the existing Irr noise-floor policy.
    """
    arr = np.asarray(values, dtype=np.float64)
    if (
        len(arr) < 3
        or not np.isfinite(dt)
        or dt <= 0.0
        or not np.isfinite(pre_level)
        or not np.isfinite(post_level)
    ):
        return None
    lo = max(0, int(search_start))
    hi = min(len(arr) - 1, int(search_end))
    peak = int(peak_idx)
    if not lo < peak < hi:
        return None
    if not np.isfinite(arr[peak]):
        return None
    width = max(8, int(round(200e-9 / dt)))
    guard = max(2, int(round(30e-9 / dt)))
    step = max(1, width // 16)
    span = abs(float(post_level) - float(pre_level))
    if span <= 1e-12:
        return None
    peak_span = max(
        span,
        abs(float(arr[peak]) - pre_level),
        abs(float(arr[peak]) - post_level),
    )
    if not np.isfinite(peak_span):
        return None

    def reference_spread(start: int, level: float) -> float:
        block = arr[start : start + width]
        if len(block) != width or not np.all(np.isfinite(block)):
            return float("inf")
        p05, p95 = np.percentile(block, [5.0, 95.0])
        if abs(0.5 * (p05 + p95) - level) > 0.15 * peak_span:
            return float("inf")
        # Low-current records have a real ADC/noise floor.  Only a neighbouring
        # reference band may relax the gate, and ringing cannot relax it
        # beyond ten percent of the event excursion (not just the small
        # pre/post difference in a low-current, coarse-range acquisition).
        return min(float(p95 - p05), 0.10 * peak_span)

    def quiet_reference_noise(first: int, last: int, level: float) -> float:
        final = last - width + 1
        if final < first:
            return 0.0
        starts = list(range(first, final + 1, width))
        if starts[-1] != final:
            starts.append(final)
        spreads = np.asarray([reference_spread(start, level) for start in starts])
        finite = spreads[np.isfinite(spreads)]
        # One unusually quiet ADC block is not the acquisition's noise floor.
        # Use the lower quartile of local reference bands, still constrained
        # by the excursion cap, so an isolated narrow block cannot reject
        # every otherwise settled band in a low-current record.
        return float(np.percentile(finite, 25.0)) if len(finite) else 0.0

    pre_noise = quiet_reference_noise(lo, peak - guard, float(pre_level))
    post_noise = quiet_reference_noise(peak + guard, hi, float(post_level))
    if bound_post_noise_to_pre:
        post_noise = min(post_noise, pre_noise)

    def quiet(start: int, level: float, noise: float) -> bool:
        block = arr[start : start + width]
        if len(block) != width or not np.all(np.isfinite(block)):
            return False
        p05, p95 = np.percentile(block, [5.0, 95.0])
        half = width // 2
        width_limit = max(0.03 * span, 1.35 * noise)
        return bool(
            p95 - p05 <= width_limit
            and np.std(block) <= 0.5 * width_limit
            and abs(0.5 * (p05 + p95) - level) <= max(0.04 * span, 0.5 * noise)
            and abs(np.median(block[:half]) - np.median(block[half:]))
            <= max(0.015 * span, 0.5 * noise)
        )

    # Work back from the peak until an entire pre-edge band is proven quiet.
    # Use the latest qualified band's centre so A itself still has stable
    # neighbours on both sides, rather than sitting on a tolerated noisy foot.
    a_idx = None
    last_pre_start = peak - guard - width + 1
    if last_pre_start < lo:
        return None
    starts = list(range(last_pre_start, lo - 1, -step))
    if starts[-1] != lo:
        starts.append(lo)
    for start in starts:
        end = start + width - 1
        if quiet(start, float(pre_level), pre_noise) and abs(
            arr[end] - pre_level
        ) <= max(0.02 * span, 0.5 * pre_noise):
            a_idx = start + width // 2
            break
    if a_idx is None:
        return None

    # Search through this event, not just a fixed peak+700 ns tail.  The next
    # switching event is an exclusive boundary supplied by the caller.
    first = peak + guard
    last = hi - width + 1
    if last < first:
        return None
    starts = list(range(first, last + 1, step))
    if starts[-1] != last:
        starts.append(last)
    for start in starts:
        if not quiet(start, float(post_level), post_noise):
            continue
        future = arr[start + width : min(hi + 1, start + 2 * width)]
        if len(future) and (
            not np.all(np.isfinite(future))
            or np.percentile(np.abs(future - post_level), 95.0)
            > max(0.06 * span, 1.5 * post_noise)
        ):
            continue
        return int(a_idx), int(start + width // 2)
    return None


def first_post_edge_stable_band_center_index(
    values: np.ndarray,
    edge_idx: int,
    search_end: int,
    dt: float,
    target_level: float,
    event_span: float,
    reference_spread: float = 0.0,
) -> int | None:
    """Return a representative point in the first quiet band after an edge.

    This helper only chooses a display time; it never recalculates the supplied
    ``target_level``.  A 100 ns edge guard excludes the transition itself and
    each candidate must provide a complete 200 ns stable band.  The returned
    centre is a stable-platform representative point, consistent with the
    other Top/Base cursor cards.  Stronger ringing moves the selected band
    later instead of relying on a fixed time offset.
    """

    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    if n < 2 or not np.isfinite(float(target_level)):
        return None
    dt_s = max(float(dt), 1e-15)
    stable_n = max(16, int(round(200e-9 / dt_s)))
    guard_n = max(8, int(round(100e-9 / dt_s)))
    edge = max(0, min(int(edge_idx), n - 1))
    lo = min(n - 1, edge + guard_n)
    hi = max(lo, min(int(search_end), n - 1))
    if hi - lo + 1 < stable_n:
        return None

    span = max(abs(float(event_span)), 1.0)
    ref_spread = max(0.0, abs(float(reference_spread)))
    width_limit = max(1e-12, 1.35 * ref_spread, 0.075 * span)
    level_limit = max(1e-12, 0.50 * ref_spread, 0.040 * span)
    drift_limit = max(1e-12, ref_spread, 0.050 * span)

    # About 12.5 ns between candidates at normal sample rates gives a stable
    # visual representative without performing thousands of percentile scans
    # on every parameter click.  Always include the final complete band so the
    # trusted reference platform remains a valid last-resort candidate.
    step = max(1, stable_n // 16)
    final_start = hi - stable_n + 1
    starts = list(range(lo, final_start + 1, step))
    if not starts or starts[-1] != final_start:
        starts.append(final_start)
    for start in starts:
        block = np.asarray(arr[start : start + stable_n], dtype=np.float64)
        finite = block[np.isfinite(block)]
        if len(finite) < max(8, stable_n // 2):
            continue
        p05, p95 = (
            float(np.nanpercentile(finite, percentile))
            for percentile in (5.0, 95.0)
        )
        robust_center = 0.5 * (p05 + p95)
        half = max(1, len(finite) // 2)
        half_drift = abs(
            float(np.nanmedian(finite[:half]))
            - float(np.nanmedian(finite[half:]))
        )
        if (
            p95 - p05 <= width_limit
            and float(np.nanstd(finite)) <= 0.50 * width_limit
            and abs(robust_center - float(target_level)) <= level_limit
            and half_drift <= drift_limit
        ):
            return int(start + stable_n // 2)
    return None


def turn_on_vce_stable_cursor_range_indices(
    vce: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    base_v: float,
    top_v: float,
    *,
    search_end: int | None = None,
) -> tuple[int, int]:
    """Return turn-on Vce Top-to-Base stable-platform cursor times.

    A is placed on the high blocking plateau before the sustained Vce fall and
    B on the first quiet low-voltage plateau after it.  The supplied levels are
    not recalculated, so using this helper cannot change Delta Vce, dv/dt or a
    maximum-value result.
    """

    arr = np.asarray(vce, dtype=np.float64)
    n = len(arr)
    if n < 2:
        return 0, 0
    lo = max(0, min(int(i0), n - 2))
    hi = max(lo + 1, min(int(i1), n - 1))
    end = (
        hi
        if search_end is None
        else max(lo + 1, min(int(search_end), n - 1))
    )
    dt_s = max(float(dt), 1e-15)
    span = max(abs(float(top_v) - float(base_v)), 1.0)
    threshold = float(base_v) + 0.50 * span
    falling = np.asarray(arr[lo : hi + 1] <= threshold, dtype=np.int64)
    sustain_n = max(2, int(round(5e-9 / dt_s)))
    sustain_n = min(sustain_n, max(1, len(falling)))
    if len(falling) >= sustain_n:
        prefix = np.concatenate(([0], np.cumsum(falling, dtype=np.int64)))
        runs = prefix[sustain_n:] - prefix[:-sustain_n]
        hits = np.flatnonzero(runs >= sustain_n)
    else:
        hits = np.asarray([], dtype=np.int64)
    if len(hits):
        edge_idx = lo + int(hits[0])
    else:
        dy = np.diff(arr[lo : hi + 1])
        edge_idx = lo + (int(np.argmin(dy)) if len(dy) else 0)

    guard_n = max(2, int(round(30e-9 / dt_s)))
    probe_n = max(int(round(500e-9 / dt_s)), int(round(120e-9 / dt_s)))
    pre_hi = max(lo, edge_idx - guard_n)
    pre_lo = max(lo, pre_hi - probe_n)
    post_lo = min(end, edge_idx + guard_n)
    post_hi = min(end, post_lo + max(probe_n, int(round(1.35e-6 / dt_s))))
    if post_hi <= post_lo:
        post_hi = end
    return stable_platform_cursor_range_indices(
        arr,
        pre_lo,
        pre_hi,
        post_lo,
        post_hi,
        dt_s,
        float(top_v),
        float(base_v),
    )


def turn_off_delta_vce_cursor_range_indices(
    t: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    blocking_top_v: float,
    *,
    search_end: int | None = None,
) -> tuple[int, int]:
    """Return stable Base/Top time cursors for turn-off Delta Vce.

    This helper deliberately does not calculate the Delta Vce amplitude.  It
    only places the vertical measurement-range cursors: A in the last quiet
    Base band before the main Vce rise and B in the first quiet Top band after
    the overshoot peak.  Ha/Hb remain the independent peak and blocking-Top
    voltage references used by the extraction result.
    """

    tt = np.asarray(t, dtype=np.float64)
    vv = np.asarray(vce, dtype=np.float64)
    n = min(len(tt), len(vv))
    if n < 2:
        return 0, 0
    lo = max(0, min(int(i0), n - 2))
    hi = max(lo + 1, min(int(i1), n - 1))
    end = hi if search_end is None else max(hi, min(int(search_end), n - 1))
    dt_s = max(float(dt), 1e-15)

    base_v, local_top_v = turn_off_dvdt_base_top_levels(tt, vv, lo, hi)
    peak_rel = int(np.argmax(vv[lo : hi + 1]))
    peak_idx = lo + peak_rel
    event_span = max(
        abs(float(local_top_v) - float(base_v)),
        abs(float(blocking_top_v) - float(base_v)),
        1.0,
    )

    # Locate the first sustained 10% rise.  A short persistence guard keeps a
    # narrow pre-edge spike from moving the Base cursor into the transition.
    rise_threshold = float(base_v) + 0.10 * event_span
    rise_hi = max(lo, min(peak_idx, hi))
    rise_values = vv[lo : rise_hi + 1]
    above = np.asarray(rise_values >= rise_threshold, dtype=np.int64)
    sustain_n = max(2, int(round(5e-9 / dt_s)))
    sustain_n = min(sustain_n, max(1, len(above)))
    if len(above) >= sustain_n:
        prefix = np.concatenate(([0], np.cumsum(above, dtype=np.int64)))
        runs = prefix[sustain_n:] - prefix[:-sustain_n]
        sustained = np.flatnonzero(runs >= sustain_n)
    else:
        sustained = np.asarray([], dtype=np.int64)
    if len(sustained):
        rise_idx = lo + int(sustained[0])
    else:
        dy = np.diff(vv[lo : rise_hi + 1])
        rise_idx = lo + (int(np.argmax(dy)) if len(dy) else 0)

    stable_n = max(8, int(round(120e-9 / dt_s)))
    guard_n = max(2, int(round(30e-9 / dt_s)))
    base_probe_n = max(stable_n, int(round(500e-9 / dt_s)))
    base_hi = max(lo, rise_idx - guard_n)
    base_lo = max(lo, base_hi - base_probe_n)
    base_centers, base_scores = _rolling_stable_level_centers(
        vv,
        base_lo,
        base_hi,
        target=float(base_v),
        event_span=event_span,
        window_n=stable_n,
    )
    if len(base_centers):
        level_tol = max(1.0, 0.04 * event_span)
        score_limit = 0.04 + max(0.5, 0.025 * event_span) / event_span
        base_valid = np.flatnonzero(base_scores <= score_limit)
        if len(base_valid):
            a_idx = int(base_centers[int(base_valid[-1])])
        else:
            a_idx = int(base_centers[int(np.argmin(base_scores))])
        # A score can be low because of a quiet but offset rail.  Prefer the
        # middle of the declared Base probe when that candidate is clearly
        # outside the local Base level tolerance.
        if abs(float(vv[a_idx]) - float(base_v)) > level_tol:
            a_idx = int((base_lo + base_hi) // 2)
    else:
        a_idx = int((base_lo + base_hi) // 2)

    # B must be after the peak rather than the first ringing crossing of Hb.
    # Select the earliest 120 ns window whose mean and spread both describe a
    # stable blocking plateau.  If no window clears the strict gate, retain
    # the best quiet candidate in the complete event-local search range.
    top_lo = min(end, max(peak_idx + guard_n, rise_idx + guard_n))
    top_centers, top_scores = _rolling_stable_level_centers(
        vv,
        top_lo,
        end,
        target=float(blocking_top_v),
        event_span=event_span,
        window_n=stable_n,
    )
    if len(top_centers):
        top_score_limit = 0.05 + max(0.5, 0.025 * event_span) / event_span
        top_valid = np.flatnonzero(top_scores <= top_score_limit)
        if len(top_valid):
            b_idx = int(top_centers[int(top_valid[0])])
        else:
            b_idx = int(top_centers[int(np.argmin(top_scores))])
    else:
        b_idx = int((top_lo + end) // 2)

    def _nearest_platform_sample(
        center: int,
        target: float,
        range_lo: int,
        range_hi: int,
    ) -> int:
        radius = max(1, stable_n // 2)
        sample_lo = max(int(range_lo), int(center) - radius)
        sample_hi = min(int(range_hi), int(center) + radius)
        candidates = np.arange(sample_lo, sample_hi + 1, dtype=np.int64)
        if len(candidates) == 0:
            return int(center)
        level_error = np.abs(vv[candidates] - float(target))
        # Break near-equal level ties toward the confirmed stable window's
        # centre without letting the timing preference overpower voltage.
        time_penalty = (
            1e-6
            * event_span
            * np.abs(candidates.astype(np.float64) - float(center))
            / float(radius)
        )
        return int(candidates[int(np.argmin(level_error + time_penalty))])

    a_idx = _nearest_platform_sample(a_idx, float(base_v), base_lo, base_hi)
    b_idx = _nearest_platform_sample(
        b_idx,
        float(blocking_top_v),
        top_lo,
        end,
    )

    a_idx = max(lo, min(a_idx, max(lo, peak_idx - 1)))
    b_idx = max(min(end, peak_idx + 1), min(b_idx, end))
    return int(a_idx), int(b_idx)


@dataclass(frozen=True)
class EoffStablePlatformCursorContext:
    """Stable-platform Eoff endpoint candidates and their evidence bands."""

    a_idx: int
    b_idx: int
    a_band_start_idx: int
    a_band_end_idx: int
    b_band_start_idx: int
    b_band_end_idx: int
    v10_idx: int
    v90_idx: int
    i90_idx: int
    i10_idx: int
    search_end_idx: int

    def shifted(self, offset: int) -> "EoffStablePlatformCursorContext":
        """Return the same evidence in another array-index coordinate space."""

        delta = int(offset)
        return EoffStablePlatformCursorContext(
            self.a_idx + delta,
            self.b_idx + delta,
            self.a_band_start_idx + delta,
            self.a_band_end_idx + delta,
            self.b_band_start_idx + delta,
            self.b_band_end_idx + delta,
            self.v10_idx + delta,
            self.v90_idx + delta,
            self.i90_idx + delta,
            self.i10_idx + delta,
            self.search_end_idx + delta,
        )


def _first_sustained_threshold_index(
    values: np.ndarray,
    lo: int,
    hi: int,
    threshold: float,
    *,
    rising: bool,
    sustain_n: int,
) -> int | None:
    """Return the first sustained raw-threshold entry in one direction."""

    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 2:
        return None
    lo = max(0, min(int(lo), len(arr) - 1))
    hi = max(lo, min(int(hi), len(arr) - 1))
    count = hi - lo + 1
    width = max(1, min(int(sustain_n), count))
    block = arr[lo : hi + 1]
    condition = block >= float(threshold) if rising else block <= float(threshold)
    prefix = np.concatenate(([0], np.cumsum(condition, dtype=np.int64)))
    runs = prefix[width:] - prefix[:-width]
    hits = np.flatnonzero(runs >= width)
    if len(hits) == 0:
        return None
    return int(lo + int(hits[0]))


def _robust_band_stats(values: np.ndarray) -> tuple[float, float, float, float]:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if len(finite) == 0:
        return float("nan"), float("nan"), float("inf"), float("inf")
    p05, p95 = (
        float(np.nanpercentile(finite, percentile))
        for percentile in (5.0, 95.0)
    )
    center = 0.5 * (p05 + p95)
    half = max(1, len(finite) // 2)
    first = finite[:half]
    second = finite[half:]
    drift = (
        abs(float(np.nanmedian(first)) - float(np.nanmedian(second)))
        if len(second)
        else 0.0
    )
    return p05, p95, center, drift


def _first_level_crossing_index_after(
    values: np.ndarray,
    level: float,
    lo: int,
    hi: int,
) -> int | None:
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 2:
        return None
    lo = max(0, min(int(lo), len(arr) - 2))
    hi = max(lo, min(int(hi), len(arr) - 2))
    shifted = arr[lo : hi + 2] - float(level)
    pairs = shifted[:-1] * shifted[1:] <= 0.0
    changed = shifted[:-1] != shifted[1:]
    hits = np.flatnonzero(pairs & changed)
    if len(hits) == 0:
        return None
    return int(lo + int(hits[0]))


def turn_off_eoff_stable_platform_cursor_context(
    t: np.ndarray,
    vce: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    blocking_top_v: float,
    vce_base_v: float,
    ic_top_abs: float,
    ic_base_a: float,
    *,
    search_end: int | None = None,
) -> EoffStablePlatformCursorContext | None:
    """Return event-adaptive stable A/B candidates for a smooth Eoff edge.

    The helper selects times only; the caller-supplied Ha/Hb levels remain
    authoritative.  A reuses the Delta-Vce Base-band locator.  B starts after
    the fixed physical 90%->10% Ic fall (independent of configurable di/dt
    percentages) and uses the first complete quiet band near the signed Hb.
    A caller must still prove that the event is smooth and that the resulting
    window contains the authoritative loss-producing power peak.  ``search_end``
    bounds the published B representative point; at most the trailing half of
    its adaptive stability band may extend beyond that point for confirmation.
    """

    tt = np.asarray(t, dtype=np.float64)
    vv = np.asarray(vce, dtype=np.float64)
    ii = np.asarray(ic, dtype=np.float64)
    n = min(len(tt), len(vv), len(ii))
    if n < 16:
        return None
    lo = max(0, min(int(i0), n - 2))
    hi = max(lo + 1, min(int(i1), n - 1))
    cursor_end = (
        hi
        if search_end is None
        else max(lo + 1, min(int(search_end), hi))
    )
    dt_s = max(float(dt), 1e-15)

    local_base_v, local_top_v = turn_off_dvdt_base_top_levels(tt, vv, lo, hi)
    v_span = max(
        abs(float(local_top_v) - float(local_base_v)),
        abs(float(blocking_top_v) - float(vce_base_v)),
        1.0,
    )
    peak_idx = lo + int(np.nanargmax(vv[lo : hi + 1]))
    sustain_n = max(2, int(round(5e-9 / dt_s)))
    v10_level = float(local_base_v) + 0.10 * v_span
    v90_level = float(local_base_v) + 0.90 * v_span
    v10_idx = _first_sustained_threshold_index(
        vv, lo, peak_idx, v10_level, rising=True, sustain_n=sustain_n
    )
    if v10_idx is None:
        return None
    v90_idx = _first_sustained_threshold_index(
        vv, v10_idx, peak_idx, v90_level, rising=True, sustain_n=sustain_n
    )
    if v90_idx is None or v90_idx <= v10_idx:
        return None
    a_window_s = float(
        np.clip(0.5 * float(tt[v90_idx] - tt[v10_idx]), 80e-9, 200e-9)
    )
    a_idx, _unused_b = turn_off_delta_vce_cursor_range_indices(
        tt,
        vv,
        lo,
        hi,
        dt_s,
        float(blocking_top_v),
        search_end=hi,
    )
    a_window_n = max(8, int(round(a_window_s / dt_s)))
    a_band_start = max(lo, int(a_idx) - a_window_n // 2)
    a_band_end = min(max(lo, v10_idx - 1), a_band_start + a_window_n - 1)
    if a_band_end - a_band_start + 1 < a_window_n:
        return None
    a_band_start = max(lo, a_band_end - a_window_n + 1)
    a_p05, a_p95, a_center, a_drift = _robust_band_stats(
        vv[a_band_start : a_band_end + 1]
    )
    pre_ref_end = max(lo, a_band_start - 1)
    pre_ref_start = max(lo, pre_ref_end - a_window_n + 1)
    pre_p05, pre_p95, _pre_center, _pre_drift = _robust_band_stats(
        vv[pre_ref_start : pre_ref_end + 1]
    )
    pre_noise_pp = max(0.0, float(pre_p95) - float(pre_p05))
    if (
        not np.isfinite(a_center)
        or float(a_p95) - float(a_p05)
        > max(1.5 * pre_noise_pp, 0.015 * v_span, 1.0)
        or a_drift > max(pre_noise_pp, 0.010 * v_span, 0.5)
        or abs(float(a_center) - float(vce_base_v))
        > max(2.0 * pre_noise_pp, 0.040 * v_span, 2.0)
    ):
        return None

    # Recover the signed conducting-current side from the event-local pre-fall
    # samples; scope_turn_off_bases intentionally publishes only |Ic| Top.
    current_ref_lo = max(lo, v10_idx - max(a_window_n, int(round(300e-9 / dt_s))))
    current_ref = ii[current_ref_lo : v10_idx + 1]
    current_ref = current_ref[np.isfinite(current_ref)]
    if len(current_ref) < 4:
        return None
    signed_center = float(np.nanmedian(current_ref))
    if abs(signed_center) <= max(1.0, 0.05 * abs(float(ic_top_abs))):
        local = ii[lo : max(lo + 1, v10_idx + 1)]
        farthest = int(np.nanargmax(np.abs(local - float(ic_base_a))))
        signed_center = float(local[farthest])
    sign = 1.0 if signed_center >= float(ic_base_a) else -1.0
    signed_top = sign * abs(float(ic_top_abs))
    i_span = abs(float(signed_top) - float(ic_base_a))
    if i_span < 1.0:
        return None
    i90_level = float(ic_base_a) + 0.90 * (float(signed_top) - float(ic_base_a))
    i10_level = float(ic_base_a) + 0.10 * (float(signed_top) - float(ic_base_a))
    falling = float(signed_top) > float(ic_base_a)
    i90_idx = _first_sustained_threshold_index(
        ii,
        v10_idx,
        cursor_end,
        i90_level,
        rising=not falling,
        sustain_n=sustain_n,
    )
    if i90_idx is None:
        return None
    i10_idx = _first_sustained_threshold_index(
        ii,
        i90_idx,
        cursor_end,
        i10_level,
        rising=not falling,
        sustain_n=sustain_n,
    )
    if i10_idx is None or i10_idx <= i90_idx:
        return None
    b_window_s = float(
        np.clip(0.5 * float(tt[i10_idx] - tt[i90_idx]), 80e-9, 200e-9)
    )
    b_window_n = max(8, int(round(b_window_s / dt_s)))
    trailing_confirmation_n = max(0, b_window_n - 1 - b_window_n // 2)
    evidence_end = min(hi, cursor_end + trailing_confirmation_n)
    if evidence_end - i10_idx + 1 < b_window_n:
        return None

    first_hb_cross = _first_level_crossing_index_after(
        ii, float(ic_base_a), i10_idx, cursor_end - 1
    )
    search_start = max(i10_idx, first_hb_cross or i10_idx)
    final_start = min(
        evidence_end - b_window_n + 1,
        cursor_end - b_window_n // 2,
    )
    if final_start < search_start:
        return None
    tail_start = max(search_start, evidence_end - b_window_n + 1)
    tail_p05, tail_p95, _tail_center, _tail_drift = _robust_band_stats(
        ii[tail_start : evidence_end + 1]
    )
    tail_noise_pp = max(0.0, float(tail_p95) - float(tail_p05))
    width_limit = max(1.5 * tail_noise_pp, 0.12 * i_span, 1.0)
    drift_limit = max(tail_noise_pp, 0.02 * i_span, 0.50)
    median_level_limit = max(1.10, 0.020 * i_span)

    def _qualifies(start: int) -> bool:
        band = ii[int(start) : int(start) + b_window_n]
        p05, p95, center, drift = _robust_band_stats(band)
        median = float(np.nanmedian(band))
        half = max(1, len(band) // 2)
        first_median = float(np.nanmedian(band[:half]))
        second_median = float(np.nanmedian(band[half:]))
        return bool(
            np.isfinite(center)
            and np.isfinite(median)
            and np.isfinite(first_median)
            and np.isfinite(second_median)
            and float(p95) - float(p05) <= width_limit
            and drift <= drift_limit
            and abs(float(center) - float(ic_base_a)) <= median_level_limit
            and abs(median - float(ic_base_a)) <= median_level_limit
            and abs(first_median - float(ic_base_a)) <= median_level_limit
            and abs(second_median - float(ic_base_a)) <= median_level_limit
        )

    step = max(1, b_window_n // 32)
    starts = [search_start]
    starts.extend(range(search_start + step, final_start + 1, step))
    if starts[-1] != final_start:
        starts.append(final_start)
    chosen_start: int | None = None
    previous = search_start - 1
    for candidate_start in starts:
        if _qualifies(candidate_start):
            refine_start = max(search_start, previous + 1)
            chosen_start = int(candidate_start)
            for exact_start in range(refine_start, int(candidate_start) + 1):
                if _qualifies(exact_start):
                    chosen_start = int(exact_start)
                    break
            break
        previous = int(candidate_start)
    if chosen_start is None:
        return None
    b_band_start = int(chosen_start)
    b_band_end = int(chosen_start + b_window_n - 1)
    b_idx = int(b_band_start + b_window_n // 2)
    if not (
        lo
        <= a_idx
        < v10_idx
        <= i90_idx
        < i10_idx
        <= b_idx
        <= cursor_end
    ):
        return None
    return EoffStablePlatformCursorContext(
        int(a_idx),
        int(b_idx),
        int(a_band_start),
        int(a_band_end),
        int(b_band_start),
        int(b_band_end),
        int(v10_idx),
        int(v90_idx),
        int(i90_idx),
        int(i10_idx),
        int(cursor_end),
    )


IC_OFF_MAX_DISPLAY_HALF_SPAN_S = DEFAULT_EXTREME_HALF_SPAN_S


def turn_off_ic_off_max_display_span_indices(
    peak_idx: int,
    lo: int,
    hi: int,
    dt: float,
) -> tuple[int, int] | None:
    """Return the default Ic_off_max A/B display interval around the peak.

    Thin wrapper over the shared :func:`extreme_display_span_indices` helper
    (peak +/- 300 ns, clipped to the turn-off window, centred and ordered even
    at the window edges).  None means no non-degenerate interval exists and
    the caller keeps its legacy Base-to-Base placement.
    """

    return extreme_display_span_indices(
        peak_idx,
        lo,
        hi,
        dt,
        half_span_s=IC_OFF_MAX_DISPLAY_HALF_SPAN_S,
    )


def turn_off_ic_off_max_cursor_context(
    t: np.ndarray,
    vce: np.ndarray,
    ic: np.ndarray,
    local_start: int,
    local_end: int,
    pulse1_on: int,
    off_idx: int,
    fall_start: int,
    fall_end: int,
    dt: float,
    *,
    next_pulse_on: int | None = None,
) -> tuple[int, int, float]:
    """Return Ic_off_max A/B display times and its stable current Base level.

    The default A/B pair is a *display interval*, not the numeric peak window:
    it is centred on the authoritative argmax(|Ic|) of the same Vge
    current-fall window that produces ic_off_max, with a half span of 300ns
    quantized by dt and clipped to the turn-off window (see
    :func:`turn_off_ic_off_max_display_span_indices`).  Because the peak index
    is always inside that interval, the published number
    max(|ic[a_idx:b_idx + 1]|) still equals the unchanged extraction peak.

    The returned level is unchanged: it stays the signed, spike-guarded centre
    of the stable Ic Base band after the main current fall (Hb), and the
    independent Ha remains the extraction-owned signed peak.  The legacy
    Vce-Base -> Ic-Base placement is retained only as a fallback for all-zero
    traces or degenerate windows.
    """

    tt = np.asarray(t, dtype=np.float64)
    vv = np.asarray(vce, dtype=np.float64)
    ii = np.asarray(ic, dtype=np.float64)
    n = min(len(tt), len(vv), len(ii))
    if n < 2:
        return 0, 0, 0.0
    lo = max(0, min(int(local_start), n - 2))
    hi = max(lo + 1, min(int(local_end), n - 1))
    pulse1_on = max(0, min(int(pulse1_on), n - 2))
    off_idx = max(lo, min(int(off_idx), n - 1))
    fall_start = max(lo, min(int(fall_start), n - 2))
    fall_end = max(fall_start + 1, min(int(fall_end), n - 1))
    dt_s = max(float(dt), 1e-15)

    # Reuse the already-audited turn-off Vce Base locator used by Delta Vce.
    # Only its Base-side cursor is relevant here; the Ic Base owns the right
    # endpoint below.
    vce_base, vce_top = turn_off_dvdt_base_top_levels(tt, vv, lo, hi)
    a_idx, _unused_top_idx = turn_off_delta_vce_cursor_range_indices(
        tt,
        vv,
        lo,
        hi,
        dt_s,
        float(vce_top),
        search_end=hi,
    )

    # Ic_off_max is calculated in the existing Vge fall window.  On a few
    # high-current records its peak occurs slightly before the last valid Vce
    # Base centre selected above.  Keep A on the same stable Vce Base band but
    # move it to the last complete quiet window ending before that peak, so the
    # displayed A/B range actually contains the unchanged authoritative max.
    peak_slice = np.abs(ii[fall_start : fall_end + 1])
    ic_peak_idx = (
        fall_start + int(np.argmax(peak_slice))
        if len(peak_slice)
        else fall_start
    )
    if a_idx >= ic_peak_idx and ic_peak_idx > lo:
        stable_n = max(8, int(round(120e-9 / dt_s)))
        base_hi = max(lo, ic_peak_idx - 1)
        base_lo = max(lo, base_hi - max(stable_n, int(round(500e-9 / dt_s))))
        centers, scores = _rolling_stable_level_centers(
            vv,
            base_lo,
            base_hi,
            target=float(vce_base),
            event_span=max(abs(float(vce_top) - float(vce_base)), 1.0),
            window_n=stable_n,
        )
        if len(centers):
            span = max(abs(float(vce_top) - float(vce_base)), 1.0)
            score_limit = 0.04 + max(0.5, 0.025 * span) / span
            valid = np.flatnonzero(scores <= score_limit)
            center_idx = int(
                centers[int(valid[-1])]
                if len(valid)
                else centers[int(np.argmin(scores))]
            )
            radius = max(1, stable_n // 2)
            sample_lo = max(base_lo, center_idx - radius)
            sample_hi = min(base_hi, center_idx + radius)
        else:
            sample_lo, sample_hi = base_lo, base_hi
        candidates = np.arange(sample_lo, sample_hi + 1, dtype=np.int64)
        if len(candidates):
            a_idx = int(
                candidates[
                    int(np.argmin(np.abs(vv[candidates] - float(vce_base))))
                ]
            )

    base_window = turn_off_didt_stable_base_window_indices(
        ii,
        hi,
        off_idx,
        fall_end,
        dt_s,
        next_pulse_on=next_pulse_on,
    )
    base_a, _top_a = turn_off_didt_base_top_levels(
        ii,
        lo,
        hi,
        pulse1_on,
        off_idx,
        fall_start,
        fall_end,
        dt_s,
        next_pulse_on=next_pulse_on,
        base_window=base_window,
    )
    if base_window is None:
        b_idx = max(off_idx, fall_end)
    else:
        b0 = max(0, min(int(base_window[0]), n - 1))
        b1 = max(b0, min(int(base_window[1]), n - 1))
        candidates = np.arange(b0, b1 + 1, dtype=np.int64)
        center = 0.5 * (b0 + b1)
        radius = max(1.0, 0.5 * (b1 - b0 + 1))
        level_error = np.abs(ii[candidates] - float(base_a))
        time_penalty = (
            1e-6
            * max(abs(float(base_a)), 1.0)
            * np.abs(candidates.astype(np.float64) - center)
            / radius
        )
        b_idx = int(candidates[int(np.argmin(level_error + time_penalty))])

    legacy_a = max(lo, min(int(a_idx), n - 2))
    legacy_b = max(legacy_a + 1, min(int(b_idx), n - 1))

    # Default A/B is a peak-centred display interval (user decision
    # 2026-11-18).  It is not the numeric window: Ic_off_max stays max(|ic|)
    # over the interval, and the authoritative peak index is inside it, so the
    # published value cannot change.  Degenerate / all-zero traces keep the
    # legacy Base-to-Base placement above.
    peak_abs = float(np.max(np.abs(peak_slice))) if len(peak_slice) else 0.0
    if np.isfinite(peak_abs) and peak_abs > 0.0:
        display = turn_off_ic_off_max_display_span_indices(
            int(ic_peak_idx), lo, hi, dt_s
        )
        if display is not None:
            return int(display[0]), int(display[1]), float(base_a)
    return int(legacy_a), int(legacy_b), float(base_a)


def dvdt_on_vce_fall_base_top(
    seg: np.ndarray, dt: float = 0.0
) -> tuple[float, float]:
    """
    开通 Vce：Ha=跌落前稳定高平台；Hb=回落后稳定低平台。
    返回 (Hb, Ha) 即 (base, top)。
    """
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 12:
        m = float(np.mean(seg)) if len(seg) else 0.0
        return m, m
    dt_s = float(dt) if dt > 0 else 1e-9
    itrans = _transition_index_fall(seg)
    tail = seg[itrans:]
    n_pre = min(
        _PLATEAU_PROBE,
        max(12, itrans // 2, int(100e-9 / dt_s)),
    )
    pre_w = seg[: min(max(12, itrans), n_pre)]
    stable_top: float | None = None
    if len(pre_w) < 3:
        top = float(np.percentile(seg[: max(1, itrans)], 95))
    else:
        top = _quiet_plateau_mid(pre_w, prefer="high")
        # A quiet-window selector can lock to the upper rail of a visibly
        # thicker pre-fall band.  Confirm that rail against the centre of the
        # first ~40 ns stable block, and only move it when the disagreement is
        # large relative to the measured bus level.  This stays waveform- and
        # amplitude-adaptive instead of depending on a phase or file name.
        stable_n = min(
            max(12, itrans),
            max(12, int(round(40e-9 / dt_s))),
        )
        stable_top = float(
            _plateau_mid_without_isolated_spikes(seg[:stable_n])
        )
    skip = max(8, int(40e-9 / dt_s))
    post = tail[skip:] if len(tail) > skip + 5 else tail
    n_avg = min(len(post), max(12, int(120e-9 / dt_s)))
    post_w = post[-n_avg:] if len(post) >= n_avg else post
    if len(post_w) < 3:
        hb = (
            _plateau_mid_without_isolated_spikes(tail)
            if len(tail)
            else float(np.min(seg))
        )
    else:
        hb = _plateau_mid_without_isolated_spikes(post_w)
    if stable_top is not None:
        rail_gap = float(top) - float(stable_top)
        if (
            abs(float(hb)) >= 10.0
            and rail_gap > max(3.0, 0.006 * max(abs(float(top)), 1.0))
        ):
            top = float(stable_top)
    return hb, top


def _turn_on_dvdt_stable_low_platform(
    seg: np.ndarray,
    dt: float,
    top: float,
) -> float | None:
    """Find the quiet low-voltage platform after the physical Vce fall."""

    arr = np.asarray(seg, dtype=np.float64)
    if len(arr) < 12 or not np.isfinite(top):
        return None
    dt_s = max(float(dt), 1e-15)
    finite_values = arr[np.isfinite(arr)]
    if len(finite_values) < 8:
        return None
    low_seed = float(np.percentile(finite_values, 5.0))
    if low_seed >= float(top):
        return None
    high_threshold = low_seed + 0.90 * (float(top) - low_seed)
    low_threshold = low_seed + 0.10 * (float(top) - low_seed)
    below_high = np.flatnonzero(arr <= high_threshold)
    if len(below_high) == 0:
        return None
    main_fall_start = int(below_high[0])
    below_low = np.flatnonzero(arr[main_fall_start:] <= low_threshold)
    if len(below_low) == 0:
        return None
    low_cross = main_fall_start + int(below_low[0])
    settle_start = min(
        len(arr),
        low_cross + max(8, int(round(100e-9 / dt_s))),
    )
    settle_end = min(
        len(arr),
        low_cross + max(16, int(round(1.35e-6 / dt_s))),
    )
    if settle_end - settle_start < 8:
        return None
    candidate = arr[settle_start:settle_end]
    candidate = candidate[np.isfinite(candidate)]
    if len(candidate) < 8:
        return None

    window_n = max(16, int(round(200e-9 / dt_s)))
    if len(candidate) <= window_n:
        return float(_plateau_mid_without_isolated_spikes(candidate))
    step = max(1, window_n // 8)
    starts = list(range(0, len(candidate) - window_n + 1, step))
    if starts[-1] != len(candidate) - window_n:
        starts.append(len(candidate) - window_n)
    low_ref = float(np.percentile(candidate, 5.0))
    best_block = candidate[:window_n]
    best_score = float("inf")
    for start in starts:
        block = candidate[start : start + window_n]
        p05, p95 = (
            float(np.percentile(block, percentile))
            for percentile in (5.0, 95.0)
        )
        center = 0.5 * (p05 + p95)
        score = (
            (p95 - p05)
            + 0.10 * abs(float(block[-1]) - float(block[0]))
            + 0.10 * abs(center - low_ref)
        )
        if score < best_score:
            best_score = score
            best_block = block
    return float(_plateau_mid_without_isolated_spikes(best_block))


def turn_on_dvdt_base_top_levels(
    vce: np.ndarray,
    i0: int,
    i1: int,
    event_end_idx: int | None,
    dt: float,
) -> tuple[float, float]:
    """Return turn-on dv/dt stable low/high voltage platform centres.

    The compact turn-on segment is authoritative for the pre-fall high
    platform.  Slow records may not reach the low platform before that segment
    ends, so Base may search farther within the same event, never across the
    following pulse2-off boundary.
    """

    arr = np.asarray(vce, dtype=np.float64)
    n = len(arr)
    if n < 2:
        return 0.0, 0.0
    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 1, min(int(i1), n - 1))
    compact_base, top = dvdt_on_vce_fall_base_top(arr[i0 : i1 + 1], dt)
    platform_end = i1
    if event_end_idx is not None:
        platform_end = max(
            i1,
            min(max(i0 + 1, int(event_end_idx) - 1), n - 1),
        )
    base = _turn_on_dvdt_stable_low_platform(
        arr[i0 : platform_end + 1],
        dt,
        top,
    )
    if base is None or not np.isfinite(base) or float(base) >= float(top):
        base = compact_base
    return float(base), float(top)


def turn_on_vce_on_max_window_indices(
    t: np.ndarray,
    vge: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    pulse2_on: int,
    pulse2_off: int,
    dt: float,
    vce_top: float | None = None,
) -> tuple[int, int]:
    """
    开通 Vce_on_max 权威数值窗：从 Vge 低电平离开到本管 Vce 跌入低平台。

    该历史窗口只负责保持提取数值兼容，不再拥有默认 GUI A/B。默认竖向光标
    另由 ``turn_on_vce_stable_cursor_range_indices()`` 表达 Vce 稳定 Top→Base；
    两者解耦后，扩大显示阶段不能重新选取 Vce_on_max。
    """
    t_arr = np.asarray(t, dtype=np.float64)
    vge_arr = np.asarray(vge, dtype=np.float64)
    vce_arr = np.asarray(vce, dtype=np.float64)
    n = min(len(t_arr), len(vge_arr), len(vce_arr))
    if n == 0:
        return 0, 0
    if n < 4:
        return 0, n - 1
    dt_s = max(float(dt), 1e-15)
    s0 = max(0, min(int(i0), n - 2))
    s1 = max(s0 + 2, min(int(i1), n - 1))
    on_idx = max(s0, min(int(pulse2_on), n - 2))
    off_idx = max(on_idx + 1, min(int(pulse2_off), n - 1))

    def _block_percentile(
        arr: np.ndarray, lo: int, hi: int, pct: float, fallback: float
    ) -> float:
        lo = max(0, min(int(lo), n - 1))
        hi = max(lo + 1, min(int(hi), n))
        block = arr[lo:hi]
        if len(block) == 0 or not np.isfinite(block).any():
            return float(fallback)
        return float(np.nanpercentile(block, float(pct)))

    pre0 = max(0, min(s0, on_idx - int(800e-9 / dt_s)))
    pre0 = max(pre0, on_idx - int(800e-9 / dt_s))
    pre1 = min(on_idx, on_idx - int(50e-9 / dt_s))
    if pre1 <= pre0 + 3:
        pre0 = max(s0, on_idx - int(500e-9 / dt_s))
        pre1 = max(pre0 + 3, on_idx)
    post0 = min(n - 1, max(on_idx + int(100e-9 / dt_s), on_idx))
    post1 = min(n, max(post0 + 4, min(off_idx, on_idx + int(900e-9 / dt_s))))
    vge_lo = _block_percentile(vge_arr, pre0, pre1, 5.0, float(vge_arr[on_idx]))
    vge_hi = _block_percentile(vge_arr, post0, post1, 95.0, float(vge_arr[on_idx]))
    span = vge_hi - vge_lo

    a_idx = on_idx
    search_a0 = max(s0, pre0)
    search_a1 = min(n - 1, on_idx + int(250e-9 / dt_s))
    if abs(span) >= 0.5 and search_a1 > search_a0:
        threshold = vge_lo + 0.02 * span
        if span >= 0.0:
            hits = np.where(vge_arr[search_a0 : search_a1 + 1] >= threshold)[0]
        else:
            hits = np.where(vge_arr[search_a0 : search_a1 + 1] <= threshold)[0]
        if len(hits):
            a_idx = search_a0 + int(hits[0])

    if vce_top is None or not np.isfinite(float(vce_top)):
        vce_top = float(np.nanmax(vce_arr[s0 : s1 + 1]))
    top = float(vce_top)
    base0 = min(n - 1, max(a_idx + int(100e-9 / dt_s), on_idx + int(300e-9 / dt_s)))
    base1 = min(n, max(base0 + 6, min(off_idx, on_idx + int(1400e-9 / dt_s))))
    if base1 <= base0 + 3:
        base0 = min(n - 1, max(a_idx + int(120e-9 / dt_s), s0))
        base1 = min(n, max(base0 + 6, s1 + 1))
    base_block = vce_arr[base0:base1]
    if len(base_block) >= 3 and np.isfinite(base_block).any():
        vce_base = float(np.nanpercentile(base_block, 20))
    else:
        vce_base = float(np.nanmin(vce_arr[s0 : s1 + 1]))
    swing = max(top - vce_base, 1.0)
    low_threshold = vce_base + max(0.05 * swing, 5.0)
    hold_threshold = low_threshold + max(0.02 * swing, 5.0)
    hold = max(3, int(40e-9 / dt_s))
    search_b1 = min(n - 1, max(s1, min(off_idx - 1, a_idx + int(2000e-9 / dt_s))))

    b_idx = s1
    for k in range(max(a_idx + 1, s0), search_b1 + 1):
        if float(vce_arr[k]) > low_threshold:
            continue
        if k + hold <= n:
            sub = vce_arr[k : k + hold]
            if len(sub) and float(np.nanpercentile(sub, 80)) <= hold_threshold:
                b_idx = k + hold - 1
                break
        else:
            b_idx = k
            break
    if b_idx <= a_idx + 2:
        b_idx = max(a_idx + 2, s1)
    return int(max(0, min(a_idx, n - 1))), int(max(a_idx + 1, min(b_idx, n - 1)))


def turn_on_vce_on_max_value(
    t: np.ndarray,
    vge: np.ndarray,
    vce: np.ndarray,
    i0: int,
    i1: int,
    pulse2_on: int,
    pulse2_off: int,
    dt: float,
    vce_top: float | None = None,
) -> float:
    """开通 Vce_on_max 数值：Vge 抬升到 Vce 低平台窗口内最大值。"""
    if len(vce) == 0:
        return 0.0
    w0, w1 = turn_on_vce_on_max_window_indices(
        t,
        vge,
        vce,
        i0,
        i1,
        pulse2_on,
        pulse2_off,
        dt,
        vce_top,
    )
    block = vce[w0 : w1 + 1]
    return float(np.max(block)) if len(block) else 0.0


def dvdt_rr_vd_plateau_top(
    t: np.ndarray,
    v_d: np.ndarray,
    vrr_peak_idx: int,
    dt: float,
    search_end: int,
) -> float:
    """反向恢复二极管 dv/dt 的 Ha：Vrr 尖峰后震荡结束尾段 |Vd| 的 (max+min)/2。"""
    t_arr = np.asarray(t, dtype=np.float64)
    vd_abs = np.abs(np.asarray(v_d, dtype=np.float64))
    n = len(t_arr)
    if n < 4:
        return 0.0
    ipk = max(0, min(int(vrr_peak_idx), n - 1))
    search_end = max(ipk + 2, min(int(search_end), n - 1))
    peak_t = float(t_arr[ipk])
    dt_s = max(float(dt), 1e-15)
    wlen = max(5, int(300e-9 / dt_s))
    settle = max(3, int(970e-9 / dt_s))
    t_lo = peak_t + float(settle) * dt_s
    t_hi = min(float(t_arr[search_end]), t_lo + 300e-9)
    lo = int(np.searchsorted(t_arr, t_lo))
    hi = int(np.searchsorted(t_arr, t_hi, side="right"))
    block = vd_abs[lo:hi]
    ha = plateau_mid(block) if len(block) >= 3 else 0.0
    if ha <= 1e-6:
        lo2 = min(ipk + settle, n - wlen - 1)
        lo2 = max(0, lo2)
        ha = plateau_mid(vd_abs[lo2 : lo2 + wlen])
    return float(ha)


def dvdt_rr_vd_base_top(
    t: np.ndarray,
    v_d: np.ndarray,
    vrr_peak_idx: int,
    dt: float,
    search_end: int,
) -> tuple[float, float]:
    """Return stable low/high ``abs(Vd)`` platforms around recovery."""

    t_arr = np.asarray(t, dtype=np.float64)
    vd_abs = np.abs(np.asarray(v_d, dtype=np.float64))
    n = min(len(t_arr), len(vd_abs))
    if n < 4:
        return 0.0, 0.0
    peak = max(1, min(int(vrr_peak_idx), n - 1))
    top = dvdt_rr_vd_plateau_top(t_arr, vd_abs, peak, dt, search_end)
    pre = vd_abs[: peak + 1]
    seed = float(np.percentile(pre, 10.0))
    threshold = seed + 0.10 * (float(top) - seed)
    crossings = np.flatnonzero(
        (vd_abs[:peak] < threshold) & (vd_abs[1 : peak + 1] >= threshold)
    )
    edge = int(crossings[-1]) if len(crossings) else peak
    edge_t = float(t_arr[edge])
    b0 = int(np.searchsorted(t_arr, edge_t - 400e-9, side="left"))
    b1 = int(np.searchsorted(t_arr, edge_t - 100e-9, side="right"))
    b0 = max(0, min(b0, n - 2))
    b1 = max(b0 + 2, min(b1, n))
    base = _plateau_mid_without_isolated_spikes(vd_abs[b0:b1])
    return float(base), float(top)


def dvdt_fall_base_top_mid(seg: np.ndarray) -> tuple[float, float]:
    """下降沿 dv/dt：Ha=高平台，Hb=低平台。"""
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 12:
        v_lo = float(np.min(seg)) if len(seg) else 0.0
        v_hi = float(np.max(seg)) if len(seg) else 0.0
        mid = 0.5 * (v_lo + v_hi)
        return mid, mid
    itrans = _transition_index_fall(seg)
    head = seg[: itrans + 1]
    tail = seg[itrans:]
    pre_w = head[-min(_PLATEAU_PROBE, len(head)) :]
    post_w = tail[-min(_PLATEAU_PROBE, len(tail)) :]
    top = _quiet_plateau_mid(pre_w, prefer="high")
    base = _quiet_plateau_mid(post_w, prefer="low")
    return top, base


def _turn_on_rise_index(seg: np.ndarray, dt_s: float) -> int:
    # 用带符号电流：下桥导通前基线可能为负(~-32A)，abs 会把负基线翻正、
    # 使横向光标浮在波形上方。导通沿单调上升，带符号判定对上桥完全等价。
    seg = np.asarray(seg, dtype=np.float64)
    n_flat = max(12, min(len(seg) // 6, int(70e-9 / dt_s)))
    hb_block = seg[:n_flat]
    cut = float(np.percentile(hb_block, 55))
    stable = hb_block[
        hb_block <= cut + max(15.0, 0.05 * float(np.max(hb_block)))
    ]
    hb = plateau_mid(stable) if len(stable) >= 3 else plateau_mid(hb_block)
    ic_max = float(np.max(seg))
    thr = hb + max(20.0, 0.10 * (ic_max - hb))
    rise = len(seg) - 1
    step = max(3, int(8e-9 / dt_s))
    for k in range(n_flat, len(seg) - step):
        if float(np.mean(seg[k : k + step])) > thr:
            rise = k
            break
    return rise


def _last_rising_level_cross_index(
    values: np.ndarray,
    level: float,
    start: int,
    end: int,
) -> int | None:
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 2 or not np.isfinite(float(level)):
        return None
    lo = max(0, min(int(start), len(arr) - 2))
    hi = max(lo + 1, min(int(end), len(arr) - 1))
    matches = np.flatnonzero(
        (arr[lo:hi] < float(level)) & (arr[lo + 1 : hi + 1] >= float(level))
    )
    return None if len(matches) == 0 else lo + int(matches[-1])


def _turn_on_a_candidate_is_event_related(
    t: np.ndarray,
    ic: np.ndarray,
    candidate_idx: int | None,
    rise_idx: int,
    hb: float,
    dt: float,
) -> bool:
    """Reject an early baseline ripple that does not continue into the main rise."""

    if candidate_idx is None:
        return False
    t_arr = np.asarray(t, dtype=np.float64)
    arr = np.asarray(ic, dtype=np.float64)
    n = min(len(t_arr), len(arr))
    if n < 2:
        return False
    k = max(0, min(int(candidate_idx), n - 2))
    rise_idx = max(k + 1, min(int(rise_idx), n - 1))
    lead_s = float(t_arr[rise_idx] - t_arr[k])
    if lead_s <= 80e-9:
        return True

    # A genuine slow foot may start earlier than 80 ns, but it must keep
    # departing from Hb.  A ripple crossing followed by another flat baseline
    # does not.  Probe 30–60 ns after A and compare it with the actual main-rise
    # span; this is invariant to positive/negative signed baselines.
    dt_s = max(float(dt), 1e-15)
    probe0 = min(rise_idx - 1, k + max(2, int(round(30e-9 / dt_s))))
    probe1 = min(rise_idx, k + max(3, int(round(60e-9 / dt_s))))
    if probe1 <= probe0:
        return False
    main1 = min(n, rise_idx + max(4, int(round(80e-9 / dt_s))))
    main_span = float(np.max(arr[rise_idx:main1]) - float(hb))
    departure = float(np.median(arr[probe0:probe1]) - float(hb))
    return departure >= max(3.0, 0.05 * max(main_span, 0.0))


def _turn_on_current_window_slices_at_rise(
    t: np.ndarray,
    ic: np.ndarray,
    event_start_idx: int,
    rise_idx: int,
    i_end: int,
    dt: float,
) -> tuple[int, int, int, int]:
    """Return half-open Hb/Ha stable-window slices for one Ic rise.

    ``i_end`` is a hard physical-event boundary.  The Ha platform must never
    be sampled after the second-pulse turn-off merely to satisfy the historical
    ``rise + 714 ns`` preference.
    """

    t_arr = np.asarray(t, dtype=np.float64)
    ic_arr = np.asarray(ic, dtype=np.float64)
    n = len(t_arr)
    if n < 4 or len(ic_arr) != n:
        return 0, n, 0, n
    event_start_idx = max(0, min(int(event_start_idx), n - 2))
    rise_idx = max(0, min(int(rise_idx), n - 1))
    i_end = max(0, min(int(i_end), n - 1))
    dt_s = max(float(dt), 1e-15)
    t_rise = float(t_arr[rise_idx])

    # The visible Base/Hb must be the complete stable band immediately next to
    # this switching event.  A 550 ns history window can mix an older ripple or
    # slow drift into the midpoint and make the main rising edge unable to
    # intersect it.  Keep a full ~200 ns band, with 50 ns clearance from the
    # detector anchor so the edge itself is not folded into the platform.
    lo = int(np.searchsorted(t_arr, t_rise - 250e-9))
    hi = int(np.searchsorted(t_arr, t_rise - 50e-9, side="right"))

    hb = _plateau_mid_without_isolated_spikes(ic_arr[lo:hi])
    search_hi = int(np.searchsorted(t_arr, t_rise + 30e-9, side="right")) - 1
    primary_cross = _last_rising_level_cross_index(
        ic_arr, hb, max(event_start_idx, lo), search_hi
    )
    if not _turn_on_a_candidate_is_event_related(
        t_arr, ic_arr, primary_cross, rise_idx, hb, dt_s
    ):
        # Two known low-current captures begin their declared turn-on segment
        # inside the 200 ns band.  Only for a proven early-flat/noise crossing,
        # use the still-adjacent right-hand sub-band; never shorten every file.
        fallback_lo = max(event_start_idx, lo)
        min_fallback = max(16, int(round(60e-9 / dt_s)))
        if hi - fallback_lo >= min_fallback:
            fallback_hb = _plateau_mid_without_isolated_spikes(
                ic_arr[fallback_lo:hi]
            )
            fallback_cross = _last_rising_level_cross_index(
                ic_arr, fallback_hb, fallback_lo, search_hi
            )
            if _turn_on_a_candidate_is_event_related(
                t_arr,
                ic_arr,
                fallback_cross,
                rise_idx,
                fallback_hb,
                dt_s,
            ):
                lo = fallback_lo

    # Keep 50 ns clear of the physical turn-off edge.  If the preferred
    # 514--714 ns window does not fit, choose a quiet 60--200 ns high plateau
    # wholly inside the same on-state event.  Insufficient room fails closed.
    guard_n = max(3, int(round(50e-9 / dt_s)))
    min_win_n = max(8, int(round(60e-9 / dt_s)))
    preferred_win_n = max(min_win_n, int(round(200e-9 / dt_s)))
    safe_stop = min(n, i_end - guard_n + 1)
    preferred_lo = int(np.searchsorted(t_arr, t_rise + 514e-9, side="left"))
    preferred_hi = min(
        safe_stop,
        int(np.searchsorted(t_arr, t_rise + 714e-9, side="right")),
    )
    if preferred_hi - preferred_lo >= min_win_n:
        return lo, hi, preferred_lo, preferred_hi

    search_lo = max(
        rise_idx + 1,
        int(np.searchsorted(t_arr, t_rise + 120e-9, side="left")),
    )
    search_hi = safe_stop
    available = search_hi - search_lo
    if available < min_win_n:
        return lo, hi, 0, 0

    win_n = min(preferred_win_n, available)
    values = ic_arr[search_lo:search_hi]
    high_ref = float(np.nanpercentile(values, 85.0))
    global_span = max(
        float(np.nanpercentile(values, 95.0))
        - float(np.nanpercentile(values, 5.0)),
        1.0,
    )
    step = max(1, win_n // 8)
    starts = list(range(0, available - win_n + 1, step))
    final_start = available - win_n
    if not starts or starts[-1] != final_start:
        starts.append(final_start)
    best_start: int | None = None
    best_score = float("inf")
    for start in starts:
        block = values[start : start + win_n]
        finite = block[np.isfinite(block)]
        if len(finite) < min_win_n:
            continue
        p05, p50, p95 = (
            float(np.nanpercentile(finite, p)) for p in (5.0, 50.0, 95.0)
        )
        half = max(1, len(finite) // 2)
        drift = abs(
            float(np.nanmedian(finite[:half]))
            - float(np.nanmedian(finite[half:]))
        )
        low_state_penalty = max(0.0, high_ref - p50)
        score = (
            (p95 - p05)
            + 0.30 * drift
            + 0.80 * low_state_penalty
            + 0.02 * global_span * (1.0 - start / max(available, 1))
        )
        if score < best_score:
            best_score = score
            best_start = start
    if best_start is None:
        return lo, hi, 0, 0
    lo2 = search_lo + best_start
    hi2 = lo2 + win_n
    return lo, hi, lo2, hi2


def _turn_on_current_hb_ha_at_rise(
    t: np.ndarray,
    ic_abs: np.ndarray,
    event_start_idx: int,
    rise_idx: int,
    i_end: int,
    dt: float,
) -> tuple[float, float]:
    """Hb=抬升前邻接 ~200ns 稳定带；Ha=抬升后 ~514–714ns 稳定带。

    两者均取孤立毛刺保护后的原始 ``(max+min)/2``。带符号取值：
    下桥导通前基线为负，须让 Hb 落在真实波形(带符号)上而非 |Ic|。
    """
    t_arr = np.asarray(t, dtype=np.float64)
    ic_abs = np.asarray(ic_abs, dtype=np.float64)
    n = len(t_arr)
    if n < 4:
        return 0.0, 0.0
    rise_idx = max(0, min(int(rise_idx), n - 1))
    i_end = max(rise_idx + 2, min(int(i_end), n - 1))
    dt_s = max(float(dt), 1e-15)
    lo, hi, lo2, hi2 = _turn_on_current_window_slices_at_rise(
        t_arr, ic_abs, event_start_idx, rise_idx, i_end, dt_s
    )
    hb = (
        _plateau_mid_without_isolated_spikes(ic_abs[lo:hi])
        if hi > lo
        else plateau_mid(ic_abs[: max(rise_idx, 3)])
    )
    ha = (
        _plateau_mid_without_isolated_spikes(ic_abs[lo2:hi2])
        if hi2 > lo2
        else float("nan")
    )
    return float(hb), float(ha)


def turn_on_current_hb_ha_t(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    *,
    event_end_idx: int | None = None,
) -> tuple[float, float]:
    """开通电流 Ha/Hb：全时间轴上按 Ic 抬升沿定位前后平台窗（带符号，贴真实波形）。"""
    ic_abs = np.asarray(ic, dtype=np.float64)
    t_arr = np.asarray(t, dtype=np.float64)
    i0 = max(0, min(int(i0), len(t_arr) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t_arr) - 1))
    seg = ic_abs[i0 : i1 + 1]
    if len(seg) < 8:
        m = plateau_mid(seg)
        return m, m
    dt_s = max(float(dt), 1e-15)
    rise_local = _turn_on_rise_index(seg, dt_s)
    rise_g = i0 + rise_local
    t_rise = float(t_arr[rise_g])
    i_end = (
        max(
            i1,
            min(len(t_arr) - 1, int(np.searchsorted(t_arr, t_rise + 720e-9))),
        )
        if event_end_idx is None
        else max(0, min(int(event_end_idx), len(t_arr) - 1))
    )
    return _turn_on_current_hb_ha_at_rise(
        t_arr, ic_abs, i0, rise_g, i_end, dt_s
    )


def turn_on_current_hb_ha_window_indices(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    *,
    event_end_idx: int | None = None,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return inclusive raw Ic windows that define the Hb/Ha midpoints."""

    t_arr = np.asarray(t, dtype=np.float64)
    ic_arr = np.asarray(ic, dtype=np.float64)
    if len(t_arr) < 2 or len(ic_arr) != len(t_arr):
        return (0, 0), (0, 0)
    i0 = max(0, min(int(i0), len(t_arr) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t_arr) - 1))
    seg = ic_arr[i0 : i1 + 1]
    if len(seg) < 8:
        return (i0, i1), (i0, i1)
    dt_s = max(float(dt), 1e-15)
    rise_g = i0 + _turn_on_rise_index(seg, dt_s)
    t_rise = float(t_arr[rise_g])
    i_end = (
        max(
            i1,
            min(len(t_arr) - 1, int(np.searchsorted(t_arr, t_rise + 720e-9))),
        )
        if event_end_idx is None
        else max(0, min(int(event_end_idx), len(t_arr) - 1))
    )
    hb0, hb1, ha0, ha1 = _turn_on_current_window_slices_at_rise(
        t_arr, ic_arr, i0, rise_g, i_end, dt_s
    )
    return (
        (hb0, max(hb0, hb1 - 1)),
        ((ha0, ha1 - 1) if ha1 > ha0 else (-1, -1)),
    )


def turn_on_current_baseline_and_plateau(
    seg: np.ndarray, dt: float = 0.0
) -> tuple[float, float]:
    """Hb=抬升前低平台；Ha=抬升后震荡结束平台（段内相对时间窗，带符号贴波形）。"""
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 8:
        mid = plateau_mid(seg)
        return mid, mid
    dt_s = max(float(dt), 1e-15)
    rise = _turn_on_rise_index(seg, dt_s)
    n = len(seg)
    pre = max(5, int(600e-9 / dt_s))
    margin = max(3, int(50e-9 / dt_s))
    lo = max(0, rise - pre)
    hi = max(lo + 3, min(n, rise - margin))
    hb = plateau_mid(seg[lo:hi])
    ha_lo = rise + max(3, int(514e-9 / dt_s))
    ha_hi = min(n, rise + max(5, int(714e-9 / dt_s)))
    if ha_hi <= ha_lo:
        ha_hi = min(n, ha_lo + max(5, int(200e-9 / dt_s)))
    ha = plateau_mid(seg[ha_lo:ha_hi]) if ha_hi > ha_lo else float(np.max(seg[rise:]))
    return float(hb), float(ha)


def ic_plateau_confirm_index(
    seg: np.ndarray, level: float, *, rise: int = 0
) -> int:
    """在搜索段内找与 level 最接近的导通平稳区时刻（相对下标，带符号贴波形）。"""
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) == 0:
        return 0
    tol = max(25.0, 0.035 * float(level))
    mask = np.abs(seg - float(level)) <= tol
    if np.any(mask):
        idx = np.where(mask)[0]
        late = idx[idx >= max(int(rise), int(0.45 * len(seg)))]
        if len(late) == 0:
            late = idx
        return int(np.median(late))
    cross = np.where(seg >= float(level) * 0.92)[0]
    if len(cross):
        return int(cross[-1])
    return len(seg) - 1


def ic_plateau_mean_near_time_us(
    t: np.ndarray,
    ic: np.ndarray,
    t_center_us: float,
    dt: float,
    *,
    half_window_s: float = 100e-9,
) -> float:
    """B 附近短窗 Ic 平均，用于震荡基本结束后的平台 Ha（带符号贴波形）。"""
    ic = np.asarray(ic, dtype=np.float64)
    if len(t) == 0:
        return 0.0
    ts = float(t_center_us) * 1e-6
    hw = float(half_window_s)
    i0 = int(np.searchsorted(t, ts - hw, side="left"))
    i1 = int(np.searchsorted(t, ts + hw, side="right"))
    i0 = max(0, min(i0, len(ic) - 1))
    i1 = max(i0, min(i1, len(ic) - 1))
    if i1 <= i0:
        return float(ic[i0])
    return float(np.mean(ic[i0 : i1 + 1]))


def _interp_cross_t(
    t0: float, t1: float, y0: float, y1: float, level: float
) -> float:
    if abs(y1 - y0) < 1e-30:
        return t0
    f = float(np.clip((level - y0) / (y1 - y0), 0.0, 1.0))
    return t0 + f * (t1 - t0)


def _raw_level_crossing_times(
    t: np.ndarray,
    values: np.ndarray,
    level: float,
    i0: int,
    i1: int,
    *,
    rising_only: bool = False,
) -> list[float]:
    """Return exact raw-waveform intersections in ``[i0, i1]``.

    Detection/stability gates may use windows and tolerances, but a default
    cursor must never fall back to a merely nearby sample.  Exact samples at
    ``level`` are valid intersections; all other intersections are linearly
    interpolated between the two original samples that bracket the level.
    """

    tt = np.asarray(t, dtype=np.float64)
    yy = np.asarray(values, dtype=np.float64)
    if len(tt) < 2 or len(yy) != len(tt) or not np.isfinite(float(level)):
        return []
    lo = max(0, min(int(i0), len(tt) - 2))
    hi = max(lo, min(int(i1), len(tt) - 1))
    out: list[float] = []
    for k in range(lo, hi):
        y0, y1 = float(yy[k]), float(yy[k + 1])
        if not (np.isfinite(y0) and np.isfinite(y1)):
            continue
        if rising_only and not y1 > y0:
            continue
        if y0 == float(level):
            candidate = float(tt[k])
        elif y1 == float(level):
            candidate = float(tt[k + 1])
        elif (y0 - float(level)) * (y1 - float(level)) < 0.0:
            candidate = _interp_cross_t(
                float(tt[k]), float(tt[k + 1]), y0, y1, float(level)
            )
        else:
            continue
        if not out or abs(candidate - out[-1]) > 1e-15:
            out.append(float(candidate))
    return out


def turn_on_current_cursor_hb_a_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    *,
    vge10_s: float | None = None,
    detect_window_ns: float = 0.0,
) -> tuple[float, float, tuple[int, int]]:
    """Return the default turn-on-current ``A/Hb`` cursor context.

    Hb is the spike-guarded raw ``(max + min) / 2`` of the complete stable
    band from ``Ic rise - 250 ns`` through ``rise - 50 ns``.  A is the last
    *rising* raw Ic/Hb intersection between the start of that band and
    ``rise + 30 ns``.  Detection may judge a candidate, but the cursor itself
    is always a real interpolated crossing of the original signed logic Ic.

    A few captures declare ``turn_on[0]`` inside an older baseline ripple.  If
    the full-band A precedes Vge10 by more than one configured detection
    smoothing window, recompute Hb/A from the still-adjacent band clipped to
    ``turn_on[0]``.  Missing crossings fail closed as ``NaN``; a segment point,
    nearest sample, or unrelated ripple is never substituted.
    """

    t_arr = np.asarray(t, dtype=np.float64)
    ic_arr = np.asarray(ic, dtype=np.float64)
    n = min(len(t_arr), len(ic_arr))
    if n < 4:
        return float("nan"), float("nan"), (-1, -1)
    t_arr = t_arr[:n]
    ic_arr = ic_arr[:n]
    i0 = max(0, min(int(i0), n - 2))
    i1 = max(i0 + 1, min(int(i1), n - 1))
    dt_s = max(float(dt), 1e-15)
    rise_idx = i0 + _turn_on_rise_index(ic_arr[i0 : i1 + 1], dt_s)
    rise_idx = max(i0, min(rise_idx, i1))
    t_rise = float(t_arr[rise_idx])
    full_lo = max(0, int(np.searchsorted(t_arr, t_rise - 250e-9)))
    hb_hi = min(n, int(np.searchsorted(t_arr, t_rise - 50e-9, side="right")))
    search_hi = min(
        n - 1,
        int(np.searchsorted(t_arr, t_rise + 30e-9, side="right")) - 1,
    )

    def _from_window(lo: int) -> tuple[float, float, tuple[int, int]]:
        lo = max(0, min(int(lo), n - 1))
        if hb_hi - lo < 4 or search_hi <= lo:
            return float("nan"), float("nan"), (-1, -1)
        hb = _plateau_mid_without_isolated_spikes(ic_arr[lo:hb_hi])
        crosses = _raw_level_crossing_times(
            t_arr,
            ic_arr,
            float(hb),
            lo,
            search_hi,
            rising_only=True,
        )
        t_a_us = float(crosses[-1] * 1e6) if crosses else float("nan")
        return t_a_us, float(hb), (lo, hb_hi - 1)

    t_a_us, hb, hb_window = _from_window(full_lo)
    if (
        np.isfinite(t_a_us)
        and vge10_s is not None
        and np.isfinite(float(vge10_s))
    ):
        guard_s = max(0.0, float(detect_window_ns)) * 1e-9
        if t_a_us * 1e-6 < float(vge10_s) - guard_s:
            clipped_t_a_us, clipped_hb, clipped_window = _from_window(
                max(i0, full_lo)
            )
            if (
                np.isfinite(clipped_t_a_us)
                and clipped_t_a_us * 1e-6 < float(vge10_s) - guard_s
            ):
                # Clipping can still retain an older event-local ripple.  In
                # that case there is no defensible main-edge Ic/Hb cursor A;
                # keep the visible Hb source band for diagnostics but fail the
                # time cursor closed instead of attaching it to that ripple.
                return float("nan"), float(clipped_hb), clipped_window
            return clipped_t_a_us, clipped_hb, clipped_window
    return t_a_us, hb, hb_window


def _turn_on_a_cross_window(
    seg: np.ndarray, seg_t: np.ndarray, dt_s: float
) -> tuple[float, float]:
    rise = _turn_on_rise_index(seg, dt_s)
    t_rise = float(seg_t[min(rise, len(seg_t) - 1)])
    # Cover exactly the event-local Hb source context plus the main-edge foot;
    # choosing the last raw rising intersection keeps A off earlier ringing.
    win_lo = max(float(seg_t[0]), t_rise - 250e-9)
    win_hi = min(float(seg_t[-1]), t_rise + 30e-9)
    return win_lo, win_hi


def _turn_on_collect_hb_rise_crosses(
    seg: np.ndarray,
    seg_t: np.ndarray,
    hb: float,
    win_lo: float,
    win_hi: float,
) -> list[float]:
    """Collect every raw rising Ic/Hb intersection in the local event gate."""

    out: list[float] = []
    for k in range(len(seg) - 1):
        tk = float(seg_t[k])
        if tk < win_lo or tk > win_hi:
            continue
        if not (seg[k] < float(hb) <= seg[k + 1]):
            continue
        out.append(
            _interp_cross_t(
                float(seg_t[k]),
                float(seg_t[k + 1]),
                float(seg[k]),
                float(seg[k + 1]),
                float(hb),
            )
        )
    return out


def turn_on_ic_a_cross_hb_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    hb: float,
    dt: float,
) -> float:
    """A：事件局部窗内，逻辑 Ic 主上升沿与 Hb 的最后真实交点（µs）。"""
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    seg = ic[i0 : i1 + 1].astype(np.float64)
    seg_t = t[i0 : i1 + 1]
    if len(seg) < 4:
        return float("nan")
    dt_s = max(float(dt), 1e-15)
    rise = _turn_on_rise_index(seg, dt_s)
    rise_g = i0 + rise
    win_lo, win_hi = _turn_on_a_cross_window(seg, seg_t, dt_s)
    crosses = _turn_on_collect_hb_rise_crosses(
        seg, seg_t, hb, win_lo, win_hi
    )
    if crosses:
        candidate = float(crosses[-1])
        local_k = int(np.searchsorted(seg_t, candidate, side="right")) - 1
        if _turn_on_a_candidate_is_event_related(
            t, ic, i0 + max(0, local_k), rise_g, hb, dt_s
        ):
            return candidate * 1e6
    i_lo = max(0, min(int(np.searchsorted(seg_t, win_lo)), len(seg_t) - 2))
    i_hi = max(i_lo + 1, min(int(np.searchsorted(seg_t, win_hi, side="right")), len(seg_t) - 1))
    exact = _raw_level_crossing_times(
        seg_t, seg, float(hb), i_lo, i_hi, rising_only=False
    )
    if exact:
        candidate = float(exact[-1])
        local_k = int(np.searchsorted(seg_t, candidate, side="right")) - 1
        if _turn_on_a_candidate_is_event_related(
            t, ic, i0 + max(0, local_k), rise_g, hb, dt_s
        ):
            return candidate * 1e6
    return float("nan")


def turn_on_ic_a_cross_hb_near_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    hb: float,
    ref_t_us: float,
    dt: float,
) -> float:
    """A：在 ref 附近找 Ic 与 Hb 的主上升沿交汇（拖 A 时用，带符号贴波形）。"""
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    seg = ic[i0 : i1 + 1].astype(np.float64)
    seg_t = t[i0 : i1 + 1]
    if len(seg) < 4:
        return float("nan")
    dt_s = max(float(dt), 1e-15)
    ref_s = float(ref_t_us) * 1e-6
    win_lo, win_hi = _turn_on_a_cross_window(seg, seg_t, dt_s)
    pad = 120e-9
    near_lo = max(win_lo, ref_s - pad)
    near_hi = min(win_hi, ref_s + pad)
    crosses = _turn_on_collect_hb_rise_crosses(
        seg, seg_t, hb, near_lo, near_hi
    )
    if not crosses:
        crosses = _turn_on_collect_hb_rise_crosses(
            seg, seg_t, hb, win_lo, win_hi
        )
    if not crosses:
        return turn_on_ic_a_cross_hb_us(t, ic, i0, i1, hb, dt)
    t_first_s = turn_on_ic_a_cross_hb_us(t, ic, i0, i1, hb, dt) * 1e-6
    # 主上升沿首交点优先：ref 在其后 100ns 内仍吸附首交点
    if ref_s <= t_first_s + 100e-9:
        return float(t_first_s) * 1e6
    best = min(crosses, key=lambda tc: abs(tc - ref_s))
    return float(best) * 1e6


def turn_on_ic_b_cross_ha_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    ha: float,
    dt: float,
    *,
    event_end_idx: int | None = None,
) -> float:
    """B：Ic 震荡尾段与 Ha 的第一个平稳交汇时刻（µs，带符号贴波形）。"""
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    ic_abs = np.asarray(ic, dtype=np.float64)
    seg = ic_abs[i0 : i1 + 1]
    if len(seg) < 8:
        return float(t[i0]) * 1e6
    dt_s = max(float(dt), 1e-15)
    rise = _turn_on_rise_index(seg, dt_s)
    rise_g = i0 + rise
    t_rise = float(t[rise_g])
    _hb_window, ha_window = turn_on_current_hb_ha_window_indices(
        t,
        ic_abs,
        i0,
        i1,
        dt_s,
        event_end_idx=event_end_idx,
    )
    if ha_window[0] < 0 or ha_window[1] < ha_window[0]:
        return float("nan")
    hard_end = (
        max(
            i1,
            min(len(t) - 1, int(np.searchsorted(t, t_rise + 1.35e-6))),
        )
        if event_end_idx is None
        else max(0, min(int(event_end_idx), len(t) - 1))
    )
    i_lo = int(ha_window[0])
    i_end = min(hard_end, max(i_lo + 1, int(ha_window[1]) + 1))
    hold = max(5, int(80e-9 / dt_s))
    tol = max(25.0, 0.035 * float(ha))
    span_thr = max(30.0, 0.06 * float(ha))
    for j in range(i_lo, max(i_lo + 1, i_end - hold)):
        sub = ic_abs[j : j + hold]
        if abs(float(np.mean(sub)) - float(ha)) > tol:
            continue
        if float(np.max(sub) - np.min(sub)) > span_thr:
            continue
        k0 = max(i_lo, j - max(3, int(40e-9 / dt_s)))
        k1 = min(i_end, j + hold)
        exact = _raw_level_crossing_times(t, ic_abs, float(ha), k0, k1)
        if exact:
            return float(exact[0]) * 1e6

    # Fail over to the true crossing nearest the old platform-confirm anchor,
    # never to the anchor sample itself.  Ha is a (max+min)/2 platform level,
    # so a finite platform window normally guarantees at least one crossing.
    exact = _raw_level_crossing_times(t, ic_abs, float(ha), i_lo, i_end)
    if exact:
        confirm_us = ic_plateau_confirm_time_us(t, ic, i0, i1, ha, dt)
        confirm_s = float(confirm_us) * 1e-6
        return float(min(exact, key=lambda value: abs(value - confirm_s))) * 1e6
    return float("nan")


def turn_on_ic_b_cross_ha_near_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    ha: float,
    ref_t_us: float,
    dt: float,
    *,
    event_end_idx: int | None = None,
) -> float:
    """B：在 ref 附近找 Ic 与 Ha 的平稳段交汇（拖 B 时用，带符号贴波形）。"""
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    ic_abs = np.asarray(ic, dtype=np.float64)
    seg = ic_abs[i0 : i1 + 1]
    seg_t = t[i0 : i1 + 1]
    if len(seg) < 8:
        return float(seg_t[0]) * 1e6
    dt_s = max(float(dt), 1e-15)
    ref_s = float(ref_t_us) * 1e-6
    rise = _turn_on_rise_index(seg, dt_s)
    t_rise = float(seg_t[min(rise, len(seg_t) - 1)])
    _hb_window, ha_window = turn_on_current_hb_ha_window_indices(
        t,
        ic_abs,
        i0,
        i1,
        dt_s,
        event_end_idx=event_end_idx,
    )
    if ha_window[0] < 0 or ha_window[1] < ha_window[0]:
        return float("nan")
    plat_lo = float(t[ha_window[0]])
    plat_hi = float(t[ha_window[1]])
    pad = 150e-9
    near_lo = max(plat_lo, ref_s - pad)
    near_hi = min(max(plat_hi, ref_s + pad), float(seg_t[-1]))
    tol = max(25.0, 0.035 * float(ha))
    span_thr = max(30.0, 0.06 * float(ha))
    hold = max(5, int(80e-9 / dt_s))
    candidates: list[float] = []

    def _add_cross(k: int) -> None:
        y0, y1 = float(ic_abs[i0 + k]), float(ic_abs[i0 + k + 1])
        if (y0 >= float(ha) > y1) or (y0 < float(ha) <= y1):
            candidates.append(
                _interp_cross_t(
                    float(seg_t[k]),
                    float(seg_t[k + 1]),
                    y0,
                    y1,
                    float(ha),
                )
            )

    i_lo = int(np.searchsorted(seg_t, near_lo))
    i_hi = int(np.searchsorted(seg_t, near_hi, side="right"))
    i_lo = max(0, min(i_lo, len(seg) - 2))
    i_hi = max(i_lo + 1, min(i_hi, len(seg) - 1))
    for j in range(i_lo, max(i_lo + 1, i_hi - hold)):
        sub = seg[j : j + hold]
        if abs(float(np.mean(sub)) - float(ha)) > tol:
            continue
        if float(np.max(sub) - np.min(sub)) > span_thr:
            continue
        k0 = max(i_lo, j - max(3, int(40e-9 / dt_s)))
        for k in range(k0, min(j + 1, len(seg) - 1)):
            tk = float(seg_t[k])
            if near_lo <= tk <= near_hi:
                _add_cross(k)
    if not candidates:
        for k in range(i_lo, min(len(seg) - 1, i_hi)):
            if near_lo <= float(seg_t[k]) <= near_hi:
                _add_cross(k)
    t_first_s = turn_on_ic_b_cross_ha_us(
        t,
        ic,
        i0,
        i1,
        ha,
        dt,
        event_end_idx=event_end_idx,
    ) * 1e-6
    if ref_s <= t_first_s + 150e-9:
        return float(t_first_s) * 1e6
    if candidates:
        return float(min(candidates, key=lambda tc: abs(tc - ref_s))) * 1e6
    return float(t_first_s) * 1e6


def turn_on_ic_link_default_times(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    *,
    event_end_idx: int | None = None,
    vge10_s: float | None = None,
    detect_window_ns: float = 0.0,
) -> tuple[float, float, float, float]:
    """默认 Hb/Ha 平台 + A/B 在带符号逻辑 Ic 上的真实交点。"""
    _pipeline_hb, ha = turn_on_current_hb_ha_t(
        t, ic, i0, i1, dt, event_end_idx=event_end_idx
    )
    t_a_us, hb, _hb_window = turn_on_current_cursor_hb_a_us(
        t,
        ic,
        i0,
        i1,
        dt,
        vge10_s=vge10_s,
        detect_window_ns=detect_window_ns,
    )
    t_b_us = turn_on_ic_b_cross_ha_us(
        t, ic, i0, i1, ha, dt, event_end_idx=event_end_idx
    )
    return t_a_us, t_b_us, float(hb), float(ha)


def ic_plateau_confirm_time_us(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    level: float,
    dt: float,
) -> float:
    i0 = max(0, min(int(i0), len(t) - 2))
    i1 = max(i0 + 1, min(int(i1), len(t) - 1))
    seg = ic[i0 : i1 + 1].astype(np.float64)
    dt_s = float(dt) if dt > 0 else 1e-9
    rise = _turn_on_rise_index(seg, dt_s)
    j = ic_plateau_confirm_index(seg, level, rise=rise)
    return float(t[i0 + j] * 1e6)


def turn_on_current_hb_ha_levels(
    seg: np.ndarray, dt: float = 0.0
) -> tuple[float, float, float]:
    """兼容旧接口：Hb, Ha(=导通平台), 开通电流值。"""
    hb, val = turn_on_current_baseline_and_plateau(seg, dt)
    return hb, val, val


def turn_on_didt_ha_at_turn_on(
    t: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
    *,
    event_end_idx: int | None = None,
) -> float:
    """
    开通 di/dt Ha：相对 |Ic| 抬升沿后 ~514–714ns 尾段 (max+min)/2。
    UH 样例约等价于开通段末 19.0–19.2µs 平台，换工况时随段窗/抬升沿自适应。
    """
    _hb, ha = turn_on_current_hb_ha_t(
        t, ic, i0, i1, dt, event_end_idx=event_end_idx
    )
    return float(ha)


def didt_fall_top_base_mid(seg: np.ndarray) -> tuple[float, float]:
    """下降沿 di/dt（关断电流）：Ha=关断前高平台，Hb=关断后低平台中值。"""
    seg = np.asarray(seg, dtype=np.float64)
    if len(seg) < 12:
        v_lo = float(np.min(seg)) if len(seg) else 0.0
        v_hi = float(np.max(seg)) if len(seg) else 0.0
        mid = 0.5 * (v_lo + v_hi)
        return mid, mid
    itrans = _transition_index_fall(seg)
    head = seg[: itrans + 1]
    tail = seg[itrans:]
    pre_w = head[-min(_PLATEAU_PROBE, len(head)) :]
    post_w = tail[-min(_PLATEAU_PROBE, len(tail)) :]
    top = _quiet_plateau_mid(pre_w, prefer="high")
    base = _quiet_plateau_mid(post_w, prefer="low")
    return top, base


def turn_off_didt_stable_top_window_indices(
    ic: np.ndarray,
    local_start: int,
    local_end: int,
    fall_start: int,
    fall_end: int,
    dt: float,
) -> tuple[int, int] | None:
    """Choose the sustained high-current band immediately before the main fall.

    A Vge fall window can begin several microseconds before Ic actually falls.
    Searching that whole interval for a handful of unusually quiet samples can
    therefore select an arbitrary point on the preceding current ramp.  Locate
    the sustained Ic drop first, then compare complete ~200 ns bands in the
    parameter-local pre-edge region.  Robust spread/drift only select the band;
    the caller still publishes the raw spike-guarded ``(max + min) / 2`` level.
    """

    arr = np.asarray(ic, dtype=np.float64)
    n = len(arr)
    if n < 2:
        return None
    dt_s = max(float(dt), 1e-15)
    start = max(0, min(max(int(local_start), int(fall_start)), n - 1))
    end = max(start, min(int(local_end), int(fall_end), n - 1))
    if end <= start:
        return None

    values = np.abs(arr[start : end + 1])
    if len(values) < 4:
        return start, end

    # Reject isolated sample noise while retaining a real switching edge.  The
    # strongest sustained drop over ~12 ns is the main Ic fall; edge padding is
    # excluded because convolution cannot represent a complete local average.
    smooth_n = max(3, int(round(4e-9 / dt_s)))
    smooth_n = min(smooth_n, max(3, len(values) // 8))
    if smooth_n % 2 == 0:
        smooth_n += 1
    kernel = np.full(smooth_n, 1.0 / smooth_n, dtype=np.float64)
    smoothed = np.convolve(values, kernel, mode="same")
    drop_n = max(3, int(round(12e-9 / dt_s)))
    drop_n = min(drop_n, max(3, len(values) // 4))
    margin = max(smooth_n, 2)
    drop_stop = len(smoothed) - drop_n - margin
    if drop_stop <= margin:
        edge_rel = int(np.argmin(np.diff(smoothed))) + 1
    else:
        sustained_drop = (
            smoothed[margin:drop_stop]
            - smoothed[margin + drop_n : drop_stop + drop_n]
        )
        edge_rel = margin + int(np.argmax(sustained_drop)) + drop_n // 2

    guard_n = max(2, int(round(20e-9 / dt_s)))
    pre_end = max(0, min(edge_rel - guard_n, len(values) - 1))
    if pre_end < 3:
        return start, min(end, start + pre_end)

    win_n = max(16, int(round(200e-9 / dt_s)))
    available = pre_end + 1
    if available <= win_n:
        return start, start + pre_end

    # Stay event-local even when the enclosing parameter range is unusually
    # wide.  Centre agreement with the band nearest the edge prevents an older
    # quiet section of an inductor-current ramp from winning on spread alone.
    search_start = max(0, available - 5 * win_n)
    tail_ref_block = values[pre_end - win_n + 1 : pre_end + 1]
    tail_p05, tail_p95 = (
        float(np.nanpercentile(tail_ref_block, p)) for p in (5.0, 95.0)
    )
    tail_ref = 0.5 * (tail_p05 + tail_p95)
    step = max(1, win_n // 8)
    starts = list(range(search_start, pre_end - win_n + 2, step))
    final_start = pre_end - win_n + 1
    if not starts or starts[-1] != final_start:
        starts.append(final_start)

    best_start = starts[0]
    best_score = float("inf")
    for window_start in starts:
        block = values[window_start : window_start + win_n]
        if not np.isfinite(block).any():
            continue
        p05, p50, p95 = (
            float(np.nanpercentile(block, p)) for p in (5.0, 50.0, 95.0)
        )
        center = 0.5 * (p05 + p95)
        half = max(1, len(block) // 2)
        half_drift = abs(
            float(np.nanmedian(block[:half]))
            - float(np.nanmedian(block[half:]))
        )
        endpoint_drift = abs(float(block[-1]) - float(block[0]))
        score = (
            (p95 - p05)
            + 0.20 * half_drift
            + 0.10 * abs(center - tail_ref)
            + 0.05 * endpoint_drift
            + 0.02 * abs(p50 - center)
        )
        if score < best_score:
            best_score = score
            best_start = window_start
    return start + best_start, start + best_start + win_n - 1


def turn_off_didt_stable_base_window_indices(
    ic: np.ndarray,
    local_end: int,
    off_idx: int,
    fall_end: int,
    dt: float,
    *,
    next_pulse_on: int | None = None,
) -> tuple[int, int] | None:
    """Choose the adjacent quiet band used by turn-off di/dt ``Base/Hb``.

    The final level must represent a visible stable band, not a few samples
    from one ringing half-cycle.  Search complete ~200 ns windows after the
    main current fall, stay local (at most five such windows past the declared
    turn-off end), and never cross the next *physical* gate rise.  Selection
    uses robust spread/drift only; the caller still computes the published
    level from the selected raw band's spike-guarded ``(max + min) / 2``.
    Returned indices are inclusive so the exact source band can be audited.
    """

    arr = np.asarray(ic, dtype=np.float64)
    n = len(arr)
    if n < 2:
        return None
    dt_s = max(float(dt), 1e-15)
    win_n = max(16, int(round(200e-9 / dt_s)))
    guard_n = max(8, int(round(100e-9 / dt_s)))
    start = max(0, min(max(int(off_idx), int(fall_end)) + 1, n - 1))
    declared_end = max(start, min(int(local_end), n - 1))
    search_end = min(n - 1, declared_end + 5 * win_n)
    if next_pulse_on is not None and int(next_pulse_on) > start:
        search_end = min(search_end, int(next_pulse_on) - guard_n)
    if search_end < start:
        return None
    available = search_end - start + 1
    if available <= win_n:
        return start, search_end

    values = arr[start : search_end + 1]

    def robust_center(block: np.ndarray) -> float:
        p05, p95 = (float(np.nanpercentile(block, p)) for p in (5.0, 95.0))
        return 0.5 * (p05 + p95)

    step = max(1, win_n // 8)
    starts = list(range(0, len(values) - win_n + 1, step))
    final_start = len(values) - win_n
    if starts[-1] != final_start:
        starts.append(final_start)
    tail_ref = robust_center(values[-win_n:])
    best_start = starts[0]
    best_score = float("inf")
    for window_start in starts:
        block = values[window_start : window_start + win_n]
        if not np.isfinite(block).any():
            continue
        p05, p50, p95 = (
            float(np.nanpercentile(block, p)) for p in (5.0, 50.0, 95.0)
        )
        center = 0.5 * (p05 + p95)
        half = max(1, len(block) // 2)
        half_drift = abs(
            float(np.nanmedian(block[:half]))
            - float(np.nanmedian(block[half:]))
        )
        endpoint_drift = abs(float(block[-1]) - float(block[0]))
        score = (
            (p95 - p05)
            + 0.20 * half_drift
            + 0.10 * abs(center - tail_ref)
            + 0.05 * endpoint_drift
            + 0.02 * abs(p50 - center)
        )
        if score < best_score:
            best_score = score
            best_start = window_start
    return start + best_start, start + best_start + win_n - 1


def turn_off_didt_base_top_levels(
    ic: np.ndarray,
    local_start: int,
    local_end: int,
    pulse1_on: int,
    off_idx: int,
    fall_start: int,
    fall_end: int,
    dt: float,
    *,
    next_pulse_on: int | None = None,
    base_window: tuple[int, int] | None = None,
    top_window: tuple[int, int] | None = None,
) -> tuple[float, float]:
    """关断 di/dt 的本地稳定电流 Base/Top。

    Top 使用主下降沿前的本地稳定高电流平台；Base 使用主下降沿后的
    本地稳定低电流平台。独立的 ``Ic_off_max`` 峰值参数不得冒充 Top。
    返回顺序为 ``(Base, Top)``，便于直接生成百分比参考电平。
    """
    ic = np.asarray(ic, dtype=np.float64)
    n = len(ic)
    if n < 2:
        return 0.0, 0.0
    _ = off_idx, dt
    pulse1_on = max(0, min(int(pulse1_on), n - 2))
    local_start = max(0, min(int(local_start), n - 2))
    local_end = max(local_start + 1, min(int(local_end), n - 1))
    fall_start = max(pulse1_on + 1, min(int(fall_start), n - 2))
    fall_end = max(fall_start + 1, min(int(fall_end), n - 1))

    legacy_top_seg = ic[fall_start : fall_end + 1]
    legacy_top = (
        float(_quiet_plateau_mid(np.abs(legacy_top_seg), prefer="high"))
        if len(legacy_top_seg)
        else 0.0
    )
    if top_window is None:
        top_window = turn_off_didt_stable_top_window_indices(
            ic, local_start, local_end, fall_start, fall_end, dt
        )
    if top_window is not None:
        t0 = max(0, min(int(top_window[0]), n - 1))
        t1 = max(t0, min(int(top_window[1]), n - 1))
        top_band = np.abs(ic[t0 : t1 + 1])
        stable_top = _plateau_mid_without_isolated_spikes(top_band)
        p05, p95 = (
            float(np.nanpercentile(top_band, p)) for p in (5.0, 95.0)
        )
        tolerance = max(1e-9, 0.10 * max(p95 - p05, 0.0))
        # Preserve an established quiet-band centre when the independently
        # located sustained platform confirms that it really lies on that
        # band.  Reject it only with direct waveform evidence that it is off
        # platform (for example a quiet point on an earlier current ramp).
        if p05 - tolerance <= legacy_top <= p95 + tolerance:
            top = legacy_top
        else:
            top = stable_top
    else:
        top = legacy_top

    if base_window is None:
        base_window = turn_off_didt_stable_base_window_indices(
            ic,
            local_end,
            off_idx,
            fall_end,
            dt,
            next_pulse_on=next_pulse_on,
        )
    if base_window is not None:
        b0 = max(0, min(int(base_window[0]), n - 1))
        b1 = max(b0, min(int(base_window[1]), n - 1))
        base = _plateau_mid_without_isolated_spikes(ic[b0 : b1 + 1])
    else:
        local_seg = ic[local_start : local_end + 1]
        base = plateau_mid(local_seg)
    return float(base), float(top)
