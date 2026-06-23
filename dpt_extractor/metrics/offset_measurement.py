from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np


@dataclass(frozen=True)
class OffsetMeasurementSpec:
    key: str
    label: str
    unit_kind: str = "source"


OFFSET_MEASUREMENT_SPECS: tuple[OffsetMeasurementSpec, ...] = (
    OffsetMeasurementSpec("amplitude", "Amplitude"),
    OffsetMeasurementSpec("maximum", "Maximum"),
    OffsetMeasurementSpec("minimum", "Minimum"),
    OffsetMeasurementSpec("peak_to_peak", "Peak-to-Peak"),
    OffsetMeasurementSpec("positive_overshoot", "Positive\nOvershoot", "percent"),
    OffsetMeasurementSpec("negative_overshoot", "Negative\nOvershoot", "percent"),
    OffsetMeasurementSpec("mean", "Mean"),
    OffsetMeasurementSpec("rms", "RMS"),
    OffsetMeasurementSpec("ac_rms", "AC RMS"),
    OffsetMeasurementSpec("top", "Top"),
    OffsetMeasurementSpec("base", "Base"),
    OffsetMeasurementSpec("area", "Area", "area"),
)

OFFSET_MEASUREMENT_BY_KEY = {spec.key: spec for spec in OFFSET_MEASUREMENT_SPECS}

OFFSET_RANGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("full", "全波形"),
    ("screen", "屏幕"),
    ("cursor", "光标"),
)
OFFSET_RANGE_LABELS = dict(OFFSET_RANGE_OPTIONS)

_UNIT_PREFIX_FACTORS = {
    "": 1.0,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
}

_UNIT_PREFIXES_BY_BASE = {
    "V": ("", "m", "k"),
    "A": ("", "m", "k"),
    "J": ("", "m", "u", "k"),
    "W": ("", "m", "K", "M"),
    "s": ("", "m", "u", "n"),
}

_BASE_UNITS = tuple(_UNIT_PREFIXES_BY_BASE)

_METRIC_ALIASES = {
    "AMPLITUDE": "amplitude",
    "AMPL": "amplitude",
    "MAXIMUM": "maximum",
    "MAX": "maximum",
    "MINIMUM": "minimum",
    "MIN": "minimum",
    "PEAKTOPEAK": "peak_to_peak",
    "PKTOPK": "peak_to_peak",
    "PK2PK": "peak_to_peak",
    "PKPK": "peak_to_peak",
    "P2P": "peak_to_peak",
    "POSITIVEOVERSHOOT": "positive_overshoot",
    "POSOVERSHOOT": "positive_overshoot",
    "POVERSHOOT": "positive_overshoot",
    "POV": "positive_overshoot",
    "NEGATIVEOVERSHOOT": "negative_overshoot",
    "NEGOVERSHOOT": "negative_overshoot",
    "NOVERSHOOT": "negative_overshoot",
    "NOV": "negative_overshoot",
    "MEAN": "mean",
    "RMS": "rms",
    "ACRMS": "ac_rms",
    "TOP": "top",
    "BASE": "base",
    "AREA": "area",
}


def _split_prefixed_unit(unit: str) -> tuple[str, str, str] | None:
    text = str(unit or "").strip()
    suffix = ""
    if text.endswith("*s") and text != "s":
        text = text[:-2]
        suffix = "*s"
    for base in _BASE_UNITS:
        if not text.endswith(base):
            continue
        prefix = text[: -len(base)]
        if prefix in _UNIT_PREFIX_FACTORS:
            return prefix, base, suffix
    return None


def _unit_dimension_and_factor(unit: str) -> tuple[str, float] | None:
    split = _split_prefixed_unit(unit)
    if split is None:
        return None
    prefix, base, suffix = split
    return f"{base}{suffix}", _UNIT_PREFIX_FACTORS[prefix]


def offset_measurement_unit_candidates(metric_key: str, source_unit: str) -> tuple[str, ...]:
    default_unit = offset_measurement_unit(metric_key, source_unit)
    if not default_unit:
        return ("",)
    if default_unit == "%":
        return ("%",)
    split = _split_prefixed_unit(default_unit)
    if split is None:
        return (default_unit,)
    _prefix, base, suffix = split
    units = tuple(f"{prefix}{base}{suffix}" for prefix in _UNIT_PREFIXES_BY_BASE[base])
    if default_unit not in units:
        return (default_unit, *units)
    return (default_unit, *(unit for unit in units if unit != default_unit))


def convert_offset_measurement_value(
    value: float,
    from_unit: str,
    to_unit: str,
) -> float:
    if from_unit == to_unit or not to_unit:
        return float(value)
    src = _unit_dimension_and_factor(from_unit)
    dst = _unit_dimension_and_factor(to_unit)
    if src is None or dst is None:
        return float(value)
    src_dim, src_factor = src
    dst_dim, dst_factor = dst
    if src_dim != dst_dim or dst_factor == 0:
        return float(value)
    return float(value) * src_factor / dst_factor


def auto_offset_measurement_unit(value: float, default_unit: str) -> str:
    unit = str(default_unit or "")
    if not unit or unit == "%":
        return unit
    try:
        magnitude = abs(float(value))
    except (TypeError, ValueError):
        return unit
    if not np.isfinite(magnitude):
        return unit

    split = _split_prefixed_unit(unit)
    if split is None:
        return unit
    prefix, base, suffix = split
    if base == "W" and suffix == "":
        magnitude_w = magnitude * _UNIT_PREFIX_FACTORS.get(prefix, 1.0)
        if magnitude_w == 0:
            return "KW"
        if magnitude_w < 1000.0:
            return "W"
        if magnitude_w >= 1_000_000.0:
            return "MW"
        return "KW"
    if magnitude == 0:
        return unit
    if magnitude >= 1:
        return unit
    current_factor = _UNIT_PREFIX_FACTORS[prefix]
    lower_prefixes = sorted(
        (
            candidate
            for candidate in _UNIT_PREFIXES_BY_BASE[base]
            if _UNIT_PREFIX_FACTORS[candidate] < current_factor
        ),
        key=lambda candidate: _UNIT_PREFIX_FACTORS[candidate],
        reverse=True,
    )
    chosen = unit
    for candidate_prefix in lower_prefixes:
        candidate_unit = f"{candidate_prefix}{base}{suffix}"
        chosen = candidate_unit
        display_value = abs(convert_offset_measurement_value(value, unit, candidate_unit))
        if display_value >= 1:
            return candidate_unit
    return chosen


def _finite_values(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    return arr[np.isfinite(arr)]


def _modal_level(values: np.ndarray) -> float:
    arr = _finite_values(values)
    if arr.size == 0:
        return float("nan")
    if arr.size == 1:
        return float(arr[0])
    span = float(np.max(arr) - np.min(arr))
    if span <= 1e-15:
        return float(np.mean(arr))
    bins = int(np.clip(np.sqrt(arr.size) * 2.0, 8, 256))
    counts, edges = np.histogram(arr, bins=bins)
    if counts.size == 0:
        return float(np.mean(arr))
    idx = int(np.argmax(counts))
    lo = float(edges[idx])
    hi = float(edges[idx + 1])
    if idx == counts.size - 1:
        mask = (arr >= lo) & (arr <= hi)
    else:
        mask = (arr >= lo) & (arr < hi)
    bucket = arr[mask]
    return float(np.mean(bucket if bucket.size else arr))


def _top_base(values: np.ndarray) -> tuple[float, float]:
    arr = _finite_values(values)
    if arr.size == 0:
        return float("nan"), float("nan")
    if arr.size == 1:
        value = float(arr[0])
        return value, value
    midpoint = float((np.max(arr) + np.min(arr)) / 2.0)
    top_arr = arr[arr >= midpoint]
    base_arr = arr[arr <= midpoint]
    return _modal_level(top_arr), _modal_level(base_arr)


def _finite_series(t_s: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t_arr = np.asarray(t_s, dtype=np.float64).reshape(-1)
    y_arr = np.asarray(values, dtype=np.float64).reshape(-1)
    if t_arr.size != y_arr.size:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
    mask = np.isfinite(t_arr) & np.isfinite(y_arr)
    return t_arr[mask], y_arr[mask]


def normalize_offset_metric_key(value: str) -> str | None:
    token = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if token in OFFSET_MEASUREMENT_BY_KEY:
        return token
    return _METRIC_ALIASES.get(token)


def normalize_offset_range_key(value: str | None) -> str:
    raw = str(value or "")
    if "光标" in raw:
        return "cursor"
    if "屏幕" in raw:
        return "screen"
    if "全" in raw:
        return "full"
    token = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if token in {"SCREEN", "VISIBLE", "DISPLAY", "VIEW"}:
        return "screen"
    if token in {"CURSOR", "CURSORS", "GATE", "GATED", "BETWEENCURSORS"}:
        return "cursor"
    if token in {"FULL", "ALL", "WHOLE", "WAVEFORM", "FULLWAVEFORM"}:
        return "full"
    return "screen"


def calculate_offset_measurement(
    t_s: np.ndarray,
    values: np.ndarray,
    metric_key: str,
) -> float:
    _t_arr, arr = _finite_series(t_s, values)
    if arr.size == 0:
        return float("nan")

    top, base = _top_base(arr)
    amplitude = top - base
    metric_key = str(metric_key)

    if metric_key == "amplitude":
        return float(amplitude)
    if metric_key == "maximum":
        return float(np.max(arr))
    if metric_key == "minimum":
        return float(np.min(arr))
    if metric_key == "peak_to_peak":
        return float(np.max(arr) - np.min(arr))
    if metric_key == "positive_overshoot":
        denom = abs(amplitude)
        return float("nan") if denom <= 1e-15 else float((np.max(arr) - top) / denom * 100.0)
    if metric_key == "negative_overshoot":
        denom = abs(amplitude)
        return float("nan") if denom <= 1e-15 else float((base - np.min(arr)) / denom * 100.0)
    if metric_key == "mean":
        return float(np.mean(arr))
    if metric_key == "rms":
        return float(np.sqrt(np.mean(arr * arr)))
    if metric_key == "ac_rms":
        centered = arr - float(np.mean(arr))
        return float(np.sqrt(np.mean(centered * centered)))
    if metric_key == "top":
        return float(top)
    if metric_key == "base":
        return float(base)
    if metric_key == "area":
        t_arr, y_arr = _finite_series(t_s, values)
        if t_arr.size < 2:
            return float("nan")
        integrator = getattr(np, "trapezoid", np.trapz)
        return float(integrator(y_arr, t_arr))
    raise KeyError(metric_key)


def offset_measurement_marker(
    t_s: np.ndarray,
    values: np.ndarray,
    metric_key: str,
) -> tuple[float, float] | None:
    """Return the waveform point used by the scope-style auxiliary guide."""
    t_arr, y_arr = _finite_series(t_s, values)
    if y_arr.size == 0:
        return None
    key = str(metric_key)
    top, base = _top_base(y_arr)
    if key in {"maximum", "positive_overshoot"}:
        idx = int(np.argmax(y_arr))
        return float(t_arr[idx]), float(y_arr[idx])
    if key in {"minimum", "negative_overshoot"}:
        idx = int(np.argmin(y_arr))
        return float(t_arr[idx]), float(y_arr[idx])
    if key in {"top", "amplitude", "peak_to_peak"} and np.isfinite(top):
        idx = int(np.argmin(np.abs(y_arr - top)))
        return float(t_arr[idx]), float(top)
    if key == "base" and np.isfinite(base):
        idx = int(np.argmin(np.abs(y_arr - base)))
        return float(t_arr[idx]), float(base)
    if key in {"mean", "rms", "ac_rms"}:
        value = calculate_offset_measurement(t_arr, y_arr, key)
        if np.isfinite(value):
            idx = int(np.argmin(np.abs(y_arr - value)))
            return float(t_arr[idx]), float(value)
    return None


def offset_measurement_unit(metric_key: str, source_unit: str) -> str:
    spec = OFFSET_MEASUREMENT_BY_KEY[str(metric_key)]
    source_unit = str(source_unit or "")
    if spec.unit_kind == "percent":
        return "%"
    if spec.unit_kind == "area":
        return f"{source_unit}*s" if source_unit else "s"
    return source_unit
