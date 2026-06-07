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

    @property
    def dt(self) -> float:
        return self.sample_interval


@dataclass
class WaveformBundle:
    """All channels keyed by CSV column name (CH1..CH6, MATH1.., etc.)."""

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
    if profile.ic_from_sum_irr_il:
        return bundle.get(profile.irr) + bundle.get(profile.il)
    return bundle.get(profile.ic)


def bundle_reverse_recovery_current(
    bundle: WaveformBundle, profile: BridgeProfile
) -> np.ndarray:
    """Reverse recovery current: mapped Irr column, or Ic − IL when irr_from_ic_minus_il."""
    if profile.irr_from_ic_minus_il:
        return bundle_total_current(bundle, profile) - bundle.get(profile.il)
    return bundle.get(profile.irr)
