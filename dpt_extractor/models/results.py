from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SegmentIndices:
    turn_off: tuple[int, int]
    turn_on: tuple[int, int]
    reverse_recovery: tuple[int, int]
    pulse1_on: int = 0
    pulse1_off: int = 0
    pulse2_on: int = 0
    pulse2_off: int = 0


@dataclass
class TurnOffResult:
    delta_vce: float = 0.0
    ic_off_max: float = 0.0
    vce_off_max: float = 0.0
    dvdt: float = 0.0
    didt: float = 0.0
    dvdt_range: str = ""
    didt_range: str = ""
    ls_off: float = 0.0
    toff: float = 0.0
    td_off: float = 0.0
    tf: float = 0.0
    crosstalk_v: float = 0.0
    crosstalk_vmax: float = 0.0
    crosstalk_vmin: float = 0.0
    eoff: float = 0.0
    eoff_range: str = ""
    eoff_check: float = 0.0
    energy_warn: bool = False


@dataclass
class TurnOnResult:
    delta_vce: float = 0.0
    ic_on_max: float = 0.0
    vce_on_max: float = 0.0
    turn_on_current: float = 0.0
    dvdt: float = 0.0
    didt: float = 0.0
    dvdt_range: str = ""
    didt_range: str = ""
    ls_on: float = 0.0
    ton: float = 0.0
    td_on: float = 0.0
    tr: float = 0.0
    crosstalk_v: float = 0.0
    crosstalk_vmax: float = 0.0
    crosstalk_vmin: float = 0.0
    eon: float = 0.0
    eon_check: float = 0.0
    energy_warn: bool = False


@dataclass
class ReverseRecoveryResult:
    irr: float = 0.0
    trr: float = 0.0
    vrr: float = 0.0
    dvdt_max: float = 0.0
    didt_irr: float = 0.0
    dvdt_range: str = ""
    didt_range: str = ""
    err: float = 0.0
    err_check: float = 0.0
    energy_warn: bool = False


@dataclass
class ShortCircuitResult:
    ic_max: float = 0.0
    tsc: float = 0.0
    tsc_start_us: float | None = None
    tsc_end_us: float | None = None
    esc_dut: float = 0.0
    vpeak_dut: float = 0.0
    esc_other: float = 0.0
    vpeak_other: float = 0.0
    desat_time: float | None = None
    tsc_range: str = ""
    desat_range: str = ""
    energy_dut_channel: str = ""
    energy_other_channel: str = ""


@dataclass
class ExtractResult:
    vdc: float = 0.0
    idc: float = 0.0
    vdc_set: float | None = None
    idc_set: float | None = None
    turn_off: TurnOffResult = field(default_factory=TurnOffResult)
    turn_on: TurnOnResult = field(default_factory=TurnOnResult)
    reverse_recovery: ReverseRecoveryResult = field(default_factory=ReverseRecoveryResult)
    short_circuit: ShortCircuitResult = field(default_factory=ShortCircuitResult)
    segments: SegmentIndices | None = None
    profile_name: str = ""
    profile_code: str = ""
    phase: str = ""
    source_path: str = ""
    detected_pulse_count: int = 0
    off_pulse_index: int = 1
    on_pulse_index: int = 2
    #: 单脉冲工况：仅关断参数有效，开通/反向恢复未计算
    single_pulse_mode: bool = False
    #: 短路工况：使用独立的短路参数表和导出模板
    short_circuit_mode: bool = False
