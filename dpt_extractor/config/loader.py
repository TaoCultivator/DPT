from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from dpt_extractor.models.slope_range import SlopeRange


@dataclass
class ThresholdConfig:
    low_pct: float = 0.10
    mid_pct: float = 0.50
    high_pct: float = 0.90


@dataclass
class PulseDetectionConfig:
    smooth_ns: float = 40.0
    min_pulse_width_us: float = 0.3
    hysteresis_ratio: float = 0.25


@dataclass
class PulseSelectionConfig:
    """1-based indices into detected gate pulses (max 10)."""

    off_pulse: int = 1
    on_pulse: int = 2


@dataclass
class TestModeConfig:
    """测试模式：dpt=双脉冲计算，short_circuit=短路计算。"""

    mode: str = "dpt"


@dataclass
class SegmentConfig:
    turn_off_pre_ns: float = 200.0
    turn_off_post_ns: float = 500.0
    turn_on_pre_ns: float = 100.0
    turn_on_post_ns: float = 800.0


@dataclass
class SmoothingConfig:
    slope_window_ns: float = 20.0
    detect_window_ns: float = 15.0


@dataclass
class SlopesConfig:
    percentile: int = 95
    ma_points: int = 21


@dataclass
class EnergyConfig:
    warn_relative_diff: float = 0.15
    # 示波器风格关断损耗窗口：从关断参考点向左搜索 t1 的预扩展窗口
    eoff_pre_ns: float = 450.0


@dataclass
class StandardConfig:
    name: str = "IEC60747-9"


@dataclass
class VdcConfig:
    use_plateau_before_off: bool = True
    plateau_ic_fraction: float = 0.85


@dataclass
class AppConfig:
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    pulse_detection: PulseDetectionConfig = field(default_factory=PulseDetectionConfig)
    pulse_selection: PulseSelectionConfig = field(default_factory=PulseSelectionConfig)
    test_mode: TestModeConfig = field(default_factory=TestModeConfig)
    segments: SegmentConfig = field(default_factory=SegmentConfig)
    smoothing: SmoothingConfig = field(default_factory=SmoothingConfig)
    slopes: SlopesConfig = field(default_factory=SlopesConfig)
    energy: EnergyConfig = field(default_factory=EnergyConfig)
    vdc: VdcConfig = field(default_factory=VdcConfig)
    standard: StandardConfig = field(default_factory=StandardConfig)

    # runtime overrides
    vdc_override: float | None = None
    slope_ranges: dict[str, "SlopeRange"] = field(default_factory=dict)


def _merge_dataclass(cls, data: dict):
    if not data:
        return cls()
    fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
    return cls(**{k: v for k, v in data.items() if k in fields})


def load_config(path: str | Path | None = None) -> AppConfig:
    if path is None:
        from dpt_extractor.utils.app_paths import default_config_path

        path = default_config_path()
    path = Path(path)
    if not path.exists():
        return AppConfig()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig(
        thresholds=_merge_dataclass(ThresholdConfig, raw.get("thresholds", {})),
        pulse_detection=_merge_dataclass(PulseDetectionConfig, raw.get("pulse_detection", {})),
        pulse_selection=_merge_dataclass(PulseSelectionConfig, raw.get("pulse_selection", {})),
        test_mode=_merge_dataclass(TestModeConfig, raw.get("test_mode", {})),
        segments=_merge_dataclass(SegmentConfig, raw.get("segments", {})),
        smoothing=_merge_dataclass(SmoothingConfig, raw.get("smoothing", {})),
        slopes=_merge_dataclass(SlopesConfig, raw.get("slopes", {})),
        energy=_merge_dataclass(EnergyConfig, raw.get("energy", {})),
        vdc=_merge_dataclass(VdcConfig, raw.get("vdc", {})),
        standard=_merge_dataclass(StandardConfig, raw.get("standard", {})),
    )
