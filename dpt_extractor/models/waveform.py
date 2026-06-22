from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from dpt_extractor.models.bridge_profile import BridgeProfile


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
        if col not in self.channels:
            raise KeyError(f"Channel {col} not in bundle")
        return self.channels[col]

    def slice(self, i0: int, i1: int) -> WaveformBundle:
        return WaveformBundle(
            t=self.t[i0:i1],
            channels={k: v[i0:i1].copy() for k, v in self.channels.items()},
            meta=self.meta,
        )


def bundle_total_current(bundle: WaveformBundle, profile: BridgeProfile) -> np.ndarray:
    """Total device current: mapped Ic column, or Irr + IL when ic_from_sum_irr_il."""
    current = try_bundle_total_current(bundle, profile)
    if current is None:
        raise KeyError("Total current channel is not available in bundle")
    return current


def try_bundle_total_current(
    bundle: WaveformBundle,
    profile: BridgeProfile,
) -> np.ndarray | None:
    """Return total device current when the mapped source channels are available."""
    if profile.ic_from_sum_irr_il:
        irr = bundle.channels.get(profile.irr) if profile.irr else None
        il = bundle.channels.get(profile.il) if profile.il else None
        if irr is not None and il is not None:
            return irr + il
        if profile.ic:
            return bundle.channels.get(profile.ic)
        return None
    if not profile.ic:
        return None
    return bundle.channels.get(profile.ic)


def bundle_reverse_recovery_current(
    bundle: WaveformBundle, profile: BridgeProfile
) -> np.ndarray:
    """Reverse recovery current: mapped Irr column, or Ic − IL when irr_from_ic_minus_il."""
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
    if profile.irr_from_ic_minus_il:
        il = bundle.channels.get(profile.il) if profile.il else None
        if il is not None:
            ic = total_current
            if ic is None:
                ic = try_bundle_total_current(bundle, profile)
            if ic is not None:
                return ic - il
        if profile.irr:
            return bundle.channels.get(profile.irr)
        return None
    if not profile.irr:
        return None
    return bundle.channels.get(profile.irr)
