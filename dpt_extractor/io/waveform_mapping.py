from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np

from dpt_extractor.models.channel_mapping import (
    ChannelMapping,
    sort_channel_names,
    validate_mapping,
)
from dpt_extractor.models.waveform import WaveformBundle, channel_reference_base_name


@dataclass(frozen=True)
class _TrendFeatures:
    channel: str
    low: float
    robust_range: float
    median: float
    high: float
    roughness: float


def _unit_kind(unit: str) -> str:
    text = str(unit or "").replace(" ", "").replace("µ", "U").replace("μ", "U").upper()
    if not text:
        return ""
    if text.endswith("V"):
        return "voltage"
    if text.endswith("A") and not text.endswith("VA"):
        return "current"
    if text.endswith("J"):
        return "energy"
    if text.endswith("W"):
        return "power"
    return ""


_FORMULA_CHANNEL_RE = re.compile(r"\b(?:CH|MATH)\d+\b", re.IGNORECASE)


def _formula_unit_kind(
    bundle: WaveformBundle,
    channel: str,
    seen: set[str],
) -> str:
    base = channel_reference_base_name(channel)
    expr = (bundle.meta.channel_math_formulas or {}).get(base, "")
    if not expr or "*" in expr or "/" in expr:
        return ""
    tokens = [
        channel_reference_base_name(token)
        for token in _FORMULA_CHANNEL_RE.findall(expr)
    ]
    tokens = [token for token in tokens if token and token != base]
    if not tokens:
        return ""
    kinds = [_channel_unit_kind(bundle, token, seen) for token in tokens]
    if not all(kinds):
        return ""
    first = kinds[0]
    return first if all(kind == first for kind in kinds) else ""


def _channel_unit_kind(
    bundle: WaveformBundle,
    channel: str,
    seen: set[str] | None = None,
) -> str:
    base = channel_reference_base_name(channel)
    unit = (
        bundle.meta.channel_unit_overrides.get(base)
        or bundle.meta.channel_units.get(base)
        or ""
    )
    kind = _unit_kind(unit)
    if kind:
        return kind
    if not base.startswith("MATH"):
        return ""
    seen = set(seen or set())
    if base in seen:
        return ""
    seen.add(base)
    return _formula_unit_kind(bundle, base, seen)


def _unit_allows(bundle: WaveformBundle, channel: str, expected: str) -> bool:
    kind = _channel_unit_kind(bundle, channel)
    return not kind or kind == expected


def _raw_scope_channels(bundle: WaveformBundle) -> list[str]:
    return [
        ch
        for ch in sort_channel_names(bundle.channels)
        if ch.upper().startswith("CH") and ch.upper()[2:].isdigit()
    ]


def _mapping_candidate_channels(
    bundle: WaveformBundle,
    *,
    include_math: bool,
) -> list[str]:
    channels = _raw_scope_channels(bundle)
    if include_math:
        channels.extend(
            ch
            for ch in sort_channel_names(bundle.channels)
            if ch.upper().startswith("MATH") and ch.upper()[4:].isdigit()
        )
    return sort_channel_names(channels)


def _channel_values(bundle: WaveformBundle, channel: str) -> np.ndarray:
    values = bundle.maybe_get(channel)
    if values is None:
        return np.asarray([], dtype=np.float64)
    return np.asarray(values, dtype=np.float64)


def _sample(y: np.ndarray, limit: int = 5000) -> np.ndarray:
    arr = np.asarray(y, dtype=np.float64)
    if arr.size > limit:
        idx = np.linspace(0, arr.size - 1, limit).astype(int)
        arr = arr[idx]
    return arr


def _features(channel: str, y: np.ndarray) -> _TrendFeatures:
    arr = _sample(y)
    if arr.size == 0:
        return _TrendFeatures(channel, 0.0, 0.0, 0.0, 0.0, 0.0)
    q05, q50, q95 = np.nanpercentile(arr, [5, 50, 95])
    robust_range = float(q95 - q05)
    if arr.size > 1:
        roughness = float(
            np.nanpercentile(np.abs(np.diff(arr)), 95)
            / max(abs(robust_range), 1e-9)
        )
    else:
        roughness = 0.0
    return _TrendFeatures(
        channel=channel,
        low=float(q05),
        robust_range=robust_range,
        median=float(q50),
        high=float(q95),
        roughness=roughness,
    )


def _vge_level_score(f: _TrendFeatures) -> float:
    """Vge is a low-voltage gate swing; exact drive rails vary by device."""
    if not (4.0 <= f.robust_range <= 45.0):
        return 0.0
    if not (-25.0 <= f.low <= 10.0 and 5.0 <= f.high <= 35.0):
        return 0.0
    score = 1.0
    if -12.0 <= f.low <= 2.0:
        score += 0.25
    if 10.0 <= f.high <= 25.0:
        score += 0.25
    if 10.0 <= f.robust_range <= 35.0:
        score += 0.15
    if f.roughness <= 0.08:
        score += 0.15
    return score


def _gate_candidates(
    bundle: WaveformBundle,
    features: dict[str, _TrendFeatures],
) -> list[str]:
    candidates = [
        ch
        for ch, f in features.items()
        if _unit_allows(bundle, ch, "voltage")
        if _vge_level_score(f) > 0.0 and f.roughness <= 0.12
    ]
    return sorted(
        sort_channel_names(candidates),
        key=lambda ch: _vge_level_score(features[ch]),
        reverse=True,
    )


def _small_signal_candidates(
    bundle: WaveformBundle,
    features: dict[str, _TrendFeatures],
    *,
    expected_unit: str = "",
) -> list[str]:
    candidates = [
        ch
        for ch, f in features.items()
        if not expected_unit or _unit_allows(bundle, ch, expected_unit)
        if f.robust_range <= 90.0 and abs(f.median) <= 40.0
    ]
    return sort_channel_names(candidates)


def _large_signal_candidates(
    bundle: WaveformBundle,
    features: dict[str, _TrendFeatures],
    *,
    expected_unit: str = "",
) -> list[str]:
    candidates = [
        ch
        for ch, f in features.items()
        if not expected_unit or _unit_allows(bundle, ch, expected_unit)
        if f.robust_range >= 80.0
    ]
    return sort_channel_names(candidates)


def _binary_gate(y: np.ndarray) -> np.ndarray:
    arr = _sample(y)
    lo, hi = np.nanpercentile(arr, [5, 95])
    if hi - lo <= 1e-9:
        return np.zeros_like(arr)
    return (arr > (lo + hi) * 0.5).astype(np.float64)


def _edge_indices(gate_bin: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if gate_bin.size < 3:
        empty = np.asarray([], dtype=np.int64)
        return empty, empty
    diff = np.diff(gate_bin)
    return np.flatnonzero(diff > 0.5) + 1, np.flatnonzero(diff < -0.5) + 1


def _edge_delta_median(y: np.ndarray, gate_bin: np.ndarray) -> tuple[float, float]:
    arr = _sample(y)
    n = min(arr.size, gate_bin.size)
    if n < 20:
        return 0.0, 0.0
    arr = arr[:n]
    gate = gate_bin[:n]
    rises, falls = _edge_indices(gate)
    win = max(3, min(40, n // 120))

    def one_delta(i: int) -> float | None:
        before0 = max(0, i - 2 * win)
        before1 = max(0, i - win)
        after0 = min(n, i + win)
        after1 = min(n, i + 2 * win)
        if before1 <= before0 or after1 <= after0:
            return None
        return float(np.nanmedian(arr[after0:after1]) - np.nanmedian(arr[before0:before1]))

    rise_deltas = [d for i in rises if (d := one_delta(int(i))) is not None]
    fall_deltas = [d for i in falls if (d := one_delta(int(i))) is not None]
    rise = float(np.nanmedian(rise_deltas)) if rise_deltas else 0.0
    fall = float(np.nanmedian(fall_deltas)) if fall_deltas else 0.0
    return rise, fall


def _norm_delta(delta: float, f: _TrendFeatures) -> float:
    return float(delta / max(abs(f.robust_range), 1e-9))


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    aa = _sample(a)
    bb = _sample(b)
    n = min(aa.size, bb.size)
    if n < 8:
        return 0.0
    aa = aa[:n]
    bb = bb[:n]
    if float(np.nanstd(aa)) <= 1e-12 or float(np.nanstd(bb)) <= 1e-12:
        return 0.0
    return float(np.corrcoef(aa, bb)[0, 1])


def _pick_gate_and_voltage(
    bundle: WaveformBundle,
    bridge: str,
    features: dict[str, _TrendFeatures],
) -> tuple[str, str, float] | None:
    expected_gate = "CH1" if bridge.lower() == "upper" else "CH6"
    expected_vce = "CH2" if bridge.lower() == "upper" else "CH5"
    gates = _gate_candidates(bundle, features)
    large = _large_signal_candidates(bundle, features, expected_unit="voltage")
    best: tuple[float, str, str, float] | None = None
    for gate in gates:
        gate_bin = _binary_gate(_channel_values(bundle, gate))
        for ch in large:
            if ch == gate:
                continue
            f = features[ch]
            values = _channel_values(bundle, ch)
            c = _corr(gate_bin, values)
            if c > -0.45:
                continue
            rise_delta, fall_delta = _edge_delta_median(values, gate_bin)
            vce_edge_score = max(-_norm_delta(rise_delta, f), 0.0) + max(
                _norm_delta(fall_delta, f),
                0.0,
            )
            if vce_edge_score < 0.12:
                continue
            score = -c + vce_edge_score + _vge_level_score(features[gate]) * 0.25
            if gate == expected_gate:
                score += 0.12
            if ch == expected_vce:
                score += 0.08
            if best is None or score > best[0]:
                best = (score, gate, ch, c)
    if best is None:
        return None
    _score, gate, vce, corr = best
    return gate, vce, corr


def _pick_positive_voltage(
    bundle: WaveformBundle,
    bridge: str,
    features: dict[str, _TrendFeatures],
    gate: str,
    used: set[str],
) -> str | None:
    expected = "CH5" if bridge.lower() == "upper" else "CH2"
    gate_bin = _binary_gate(_channel_values(bundle, gate))
    if (
        expected in features
        and expected not in used
        and _unit_allows(bundle, expected, "voltage")
    ):
        expected_values = _channel_values(bundle, expected)
        expected_corr = _corr(gate_bin, expected_values)
        rise_delta, fall_delta = _edge_delta_median(
            expected_values,
            gate_bin,
        )
        expected_edge_score = max(
            _norm_delta(rise_delta, features[expected]),
            0.0,
        ) + max(-_norm_delta(fall_delta, features[expected]), 0.0)
        if (
            expected_corr >= 0.30
            and features[expected].robust_range >= 40.0
            and expected_edge_score >= 0.10
        ):
            return expected
    best: tuple[float, str] | None = None
    for ch in _large_signal_candidates(bundle, features, expected_unit="voltage"):
        if ch in used:
            continue
        f = features[ch]
        values = _channel_values(bundle, ch)
        c = _corr(gate_bin, values)
        if c < 0.25:
            continue
        rise_delta, fall_delta = _edge_delta_median(values, gate_bin)
        diode_edge_score = max(_norm_delta(rise_delta, f), 0.0) + max(
            -_norm_delta(fall_delta, f),
            0.0,
        )
        if diode_edge_score < 0.08:
            continue
        score = c + diode_edge_score + (0.15 if ch == expected else 0.0)
        if best is None or score > best[0]:
            best = (score, ch)
    if best is not None:
        return best[1]
    return (
        expected
        if expected in features
        and expected not in used
        and _unit_allows(bundle, expected, "voltage")
        else None
    )


def _pick_other_gate(
    bundle: WaveformBundle,
    bridge: str,
    features: dict[str, _TrendFeatures],
    used: set[str],
) -> str | None:
    expected = "CH6" if bridge.lower() == "upper" else "CH1"
    if (
        expected in features
        and expected not in used
        and _unit_allows(bundle, expected, "voltage")
    ):
        return expected
    candidates = [
        ch
        for ch in _small_signal_candidates(
            bundle,
            features,
            expected_unit="voltage",
        )
        if ch not in used and features[ch].robust_range <= 35.0
    ]
    return candidates[0] if candidates else None


def _switched_current_score(
    bundle: WaveformBundle,
    gate_bin: np.ndarray,
    features: dict[str, _TrendFeatures],
    channel: str,
) -> float:
    f = features[channel]
    values = _channel_values(bundle, channel)
    corr = max(_corr(gate_bin, values), 0.0)
    rise_delta, fall_delta = _edge_delta_median(values, gate_bin)
    turn_on_rise = max(_norm_delta(rise_delta, f), 0.0)
    turn_off_fall = max(-_norm_delta(fall_delta, f), 0.0)
    return corr + turn_on_rise * 0.6 + turn_off_fall * 0.6


def _pick_current_pair(
    bundle: WaveformBundle,
    gate: str,
    bridge: str,
    features: dict[str, _TrendFeatures],
    used: set[str],
) -> tuple[str, str] | None:
    remaining = [
        ch
        for ch in sort_channel_names(features)
        if ch not in used and _unit_allows(bundle, ch, "current")
    ]
    if len(remaining) < 2:
        return None
    gate_bin = _binary_gate(_channel_values(bundle, gate))
    current_scores = {
        ch: _switched_current_score(bundle, gate_bin, features, ch)
        for ch in remaining
    }
    current = max(remaining, key=lambda ch: current_scores[ch])
    if current_scores[current] < 0.18:
        return None
    il_candidates = [ch for ch in remaining if ch != current]
    if not il_candidates:
        return None
    il = min(
        il_candidates,
        key=lambda ch: (
            current_scores[ch],
            features[ch].roughness,
            -features[ch].median,
        ),
    )
    return (current, il) if bridge.lower() == "upper" else (current, il)


def infer_channel_mapping_from_waveform_trends(
    bundle: WaveformBundle | None,
    bridge: str,
) -> ChannelMapping | None:
    """
    Infer DPT channel mapping from waveform shapes, without trusting TSS labels.

    The trend model does not trust labels. It looks for Vge's low-voltage gate
    swing, the DUT Vce falling from the off-state voltage platform to a low
    conduction drop on turn-on, the complementary diode voltage moving the
    opposite way, the switched current's fast turn-on/turn-off edges, and the IL
    staircase/slow-ramp channel. For upper bridge Ic is branch current + IL; for
    lower bridge Irr is Ic - IL. If the waveform evidence is weak, returns None
    so label inference or manual mapping can take over.
    """
    if bundle is None:
        return None
    raw_channels = _raw_scope_channels(bundle)
    if len(raw_channels) < 4:
        return None
    channels = _mapping_candidate_channels(
        bundle,
        include_math=len(raw_channels) < 6,
    )

    features = {
        ch: _features(ch, _channel_values(bundle, ch))
        for ch in channels
        if ch in bundle.channels
    }
    gate_and_vce = _pick_gate_and_voltage(bundle, bridge, features)
    if gate_and_vce is None:
        return None
    vge, vce, corr = gate_and_vce
    if corr > -0.55:
        return None

    used = {vge, vce}
    v_diode = _pick_positive_voltage(bundle, bridge, features, vge, used)
    if not v_diode:
        return None
    used.add(v_diode)
    vge_other = _pick_other_gate(bundle, bridge, features, used)
    if vge_other:
        used.add(vge_other)

    current_pair = _pick_current_pair(bundle, vge, bridge, features, used)
    if current_pair is None:
        return None
    current, il = current_pair

    if bridge.lower() == "upper":
        mapping = ChannelMapping(
            vge=vge,
            vce=vce,
            ic="",
            il=il,
            irr=current,
            v_diode=v_diode,
            vge_other=vge_other or "",
            ic_from_sum_irr_il=True,
            irr_from_ic_minus_il=False,
        )
    else:
        mapping = ChannelMapping(
            vge=vge,
            vce=vce,
            ic=current,
            il=il,
            irr="",
            v_diode=v_diode,
            vge_other=vge_other or "",
            ic_from_sum_irr_il=False,
            irr_from_ic_minus_il=True,
        )

    return None if validate_mapping(mapping, bundle) else mapping
