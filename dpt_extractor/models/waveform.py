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
        if sign < 0:
            return -np.asarray(channel, dtype=np.float64)
        if (base in self.meta.channel_display_inversions) != (
            base in self.meta.source_channel_inversions
        ):
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
        return direct
    if profile.ic_from_sum_irr_il:
        irr = bundle.maybe_get(profile.irr)
        il = bundle.maybe_get(profile.il)
        if irr is not None and il is not None:
            return irr + il
    return None


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
        return direct
    if profile.irr_from_ic_minus_il:
        il = bundle.maybe_get(profile.il)
        if il is not None:
            ic = total_current
            if ic is None:
                ic = try_bundle_total_current(bundle, profile)
            if ic is not None:
                return ic - il
    return None
