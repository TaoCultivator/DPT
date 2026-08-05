from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

import numpy as np

from dpt_extractor.models.bridge_profile import BridgeProfile


_UNICODE_MINUS = ("\N{MINUS SIGN}", "\N{EN DASH}", "\N{EM DASH}")


def normalize_channel_reference(ref: str | None) -> str:
    """Normalize a CH/MATH reference, preserving an optional leading minus sign."""
    text = str(ref or "").strip()
    for minus in _UNICODE_MINUS:
        text = text.replace(minus, "-")
    text = re.sub(r"\s+", "", text).upper()
    if not text:
        return ""
    sign = ""
    if text[0] in "+-":
        sign = "-" if text[0] == "-" else ""
        text = text[1:]
    if not text:
        return sign
    return f"{sign}{text}"


def split_channel_reference(ref: str | None) -> tuple[int, str]:
    """Return (sign, base channel) for refs like CH3, +CH3 or -MATH1."""
    normalized = normalize_channel_reference(ref)
    if not normalized:
        return 1, ""
    if normalized.startswith("-"):
        return -1, normalized[1:]
    if normalized.startswith("+"):
        return 1, normalized[1:]
    return 1, normalized


def channel_reference_base_name(ref: str | None) -> str:
    return split_channel_reference(ref)[1]


def channel_reference_sign(ref: str | None) -> int:
    return split_channel_reference(ref)[0]


@dataclass
class TekMetadata:
    model: str = ""
    sample_interval: float = 8e-11
    record_length: int = 0
    zero_index: float = 0.0
    source_path: str = ""
    #: Data origin. ``file`` keeps the historical TSS path behaviour; ``scope``
    #: marks a live USB/VISA record and enables one-shot scope synchronization.
    source_kind: str = "file"
    #: VISA resource used to read the live record, for example
    #: USB0::0x0699::0x0527::C078514::INSTR.
    instrument_resource: str = ""
    #: Full *IDN? response captured together with the live record.
    instrument_idn: str = ""
    #: CH/MATH column name -> oscilloscope Label row text
    channel_labels: dict[str, str] = field(default_factory=dict)
    #: CH/MATH -> vertical scale from session (.wfm user view), units per division (V/格, A/格)
    channel_vdiv: dict[str, float] = field(default_factory=dict)
    #: CH/MATH -> vertical unit recorded by the source WFM/TSS file, such as V or A.
    channel_units: dict[str, str] = field(default_factory=dict)
    #: CH/MATH -> user unit override for cases where the oscilloscope unit was wrong.
    channel_unit_overrides: dict[str, str] = field(default_factory=dict)
    #: CH/MATH -> vertical position from session (divisions, Tek yPosition)
    channel_y_position: dict[str, float] = field(default_factory=dict)
    #: MATH channel -> formula restored from a Tektronix session setup file.
    channel_math_formulas: dict[str, str] = field(default_factory=dict)
    #: MATH channels synthesized from setup formulas rather than loaded as .wfm members.
    computed_math_channels: set[str] = field(default_factory=set)
    #: Scope horizontal scale from the Tektronix session setup, seconds per division.
    horizontal_scale_per_div: float | None = None
    #: Scope horizontal position from the Tektronix session setup, percent.
    horizontal_position_percent: float | None = None
    #: Scope horizontal delay from the Tektronix session setup, seconds.
    horizontal_delay: float | None = None
    #: Scope measurement definitions restored from the session setup:
    #: (source channel, metric key, range key).
    offset_measurements: list[tuple[str, str, str]] = field(default_factory=list)
    #: CH/MATH channels whose oscilloscope session source had invert enabled.
    #: WFM values are treated as already matching this source display state.
    source_channel_inversions: set[str] = field(default_factory=set)
    #: Active display inversions. Initialized from source_channel_inversions,
    #: then updated by the channel settings panel for live display/calculation.
    channel_display_inversions: set[str] = field(default_factory=set)

    @property
    def dt(self) -> float:
        return self.sample_interval


@dataclass
class WaveformBundle:
    """All channels keyed by waveform channel name (CH1..CH8, MATH1.., etc.)."""

    t: np.ndarray
    channels: dict[str, np.ndarray]
    meta: TekMetadata = field(default_factory=TekMetadata)

    @property
    def dt(self) -> float:
        return self.meta.dt

    @property
    def n(self) -> int:
        return len(self.t)

    def get(self, col: str) -> np.ndarray:
        channel = self.maybe_get(col)
        if channel is None:
            raise KeyError(f"Channel {col} not in bundle")
        return channel

    def maybe_get(self, col: str | None) -> np.ndarray | None:
        sign, base = split_channel_reference(col)
        if not base:
            return None
        channel = self.channels.get(base)
        if channel is None:
            return None
        display_transform_inverted = (
            base in self.meta.channel_display_inversions
        ) != (
            base in self.meta.source_channel_inversions
        )
        # A signed mapping and the user/source display transform are two
        # independent factors.  Compose them exactly once instead of letting a
        # leading '-' bypass the inversion selected in channel settings.
        if (sign < 0) != display_transform_inverted:
            return -np.asarray(channel, dtype=np.float64)
        return channel

    def has_channel_reference(self, col: str | None) -> bool:
        _sign, base = split_channel_reference(col)
        return bool(base and base in self.channels)

    def slice(self, i0: int, i1: int) -> WaveformBundle:
        return WaveformBundle(
            t=self.t[i0:i1],
            channels={k: v[i0:i1].copy() for k, v in self.channels.items()},
            meta=self.meta,
        )


def bundle_total_current(bundle: WaveformBundle, profile: BridgeProfile) -> np.ndarray:
    """Total device current: direct Ic mapping first, then Irr + IL fallback."""
    current = try_bundle_total_current(bundle, profile)
    if current is None:
        raise KeyError("Total current channel is not available in bundle")
    return current


def try_bundle_total_current(
    bundle: WaveformBundle,
    profile: BridgeProfile,
) -> np.ndarray | None:
    """Return total device current when the mapped source channels are available."""
    direct = bundle.maybe_get(profile.ic)
    if direct is not None:
        return _auto_orient_total_current(direct)
    if profile.ic_from_sum_irr_il:
        il = bundle.maybe_get(profile.il)
        irr = _auto_orient_reverse_recovery_current(
            bundle.maybe_get(profile.irr),
            il,
        )
        if irr is not None and il is not None:
            return irr + il
    return None


def _finite_percentiles(values: np.ndarray) -> tuple[float, float]:
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.0, 0.0
    p05, p95 = np.percentile(arr, [5.0, 95.0])
    return float(p05), float(p95)


def _current_scale_hint(companion: np.ndarray | None) -> float:
    if companion is None:
        return 0.0
    arr = np.asarray(companion, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.0
    return float(np.percentile(np.abs(arr), 95.0))


def _dominant_current_polarity(
    values: np.ndarray,
    companion: np.ndarray | None = None,
) -> int:
    """Return +1/-1 when one high-current plateau polarity clearly dominates."""
    p05, p95 = _finite_percentiles(values)
    positive = max(float(p95), 0.0)
    negative = max(-float(p05), 0.0)
    scale = _current_scale_hint(companion)
    floor = max(20.0, 0.15 * scale)
    if positive >= max(3.0 * negative, floor):
        return 1
    if negative >= max(3.0 * positive, floor):
        return -1
    return 0


def _auto_orient_total_current(current: np.ndarray | None) -> np.ndarray | None:
    """Total device current should have a positive high-current plateau."""
    if current is None:
        return None
    arr = np.asarray(current, dtype=np.float64)
    return -arr if _dominant_current_polarity(arr) < 0 else arr


def _auto_orient_reverse_recovery_current(
    current: np.ndarray | None,
    companion_il: np.ndarray | None = None,
) -> np.ndarray | None:
    """
    Reverse-recovery branch current uses the DPT physical polarity.

    In the project samples, the large commutation/current-platform component of
    Irr is negative and the recovery spike is measured from that physical
    signal. Some scopes are saved with the current probe inverted; when the
    dominant high-current plateau is positive and comparable to IL, flip only
    the logical Irr used for extraction/display.
    """
    if current is None:
        return None
    arr = np.asarray(current, dtype=np.float64)
    if companion_il is None or _current_scale_hint(companion_il) < 20.0:
        return arr
    return -arr if _dominant_current_polarity(arr, companion_il) > 0 else arr


def bundle_reverse_recovery_current(
    bundle: WaveformBundle, profile: BridgeProfile
) -> np.ndarray:
    """Reverse recovery current: direct Irr mapping first, then Ic − IL fallback."""
    current = try_bundle_reverse_recovery_current(bundle, profile)
    if current is None:
        return np.zeros_like(bundle.t, dtype=np.float64)
    return current


def try_bundle_reverse_recovery_current(
    bundle: WaveformBundle,
    profile: BridgeProfile,
    total_current: np.ndarray | None = None,
) -> np.ndarray | None:
    """Return reverse-recovery current when its mapped source channels are available."""
    direct = bundle.maybe_get(profile.irr)
    if direct is not None:
        return _auto_orient_reverse_recovery_current(
            direct,
            bundle.maybe_get(profile.il),
        )
    if profile.irr_from_ic_minus_il:
        il = bundle.maybe_get(profile.il)
        if il is not None:
            ic = total_current
            if ic is None:
                ic = try_bundle_total_current(bundle, profile)
            if ic is not None:
                return ic - il
    return None
