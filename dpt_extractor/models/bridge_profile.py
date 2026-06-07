from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

PHASES = ("U", "V", "W")


@dataclass(frozen=True)
class BridgeProfile:
    """Logical signal name -> physical CSV column."""

    name: str
    display_name: str
    phase: str
    bridge: str  # "upper" | "lower"
    code: str  # e.g. UH, WL
    vge: str
    vce: str
    ic: str
    il: str
    irr: str
    v_diode: str
    vge_other: str
    #: 为 True 时总电流在软件内用 Irr+IL 波形相加，不使用示波器 MATH 列
    ic_from_sum_irr_il: bool = False
    #: 为 True 时反向恢复电流 = Ic 列 − IL 列（下桥典型接线），不使用 MATH 列
    irr_from_ic_minus_il: bool = False

    def all_channels(self) -> tuple[str, ...]:
        ch: list[str] = [self.vge, self.vce]
        if not self.ic_from_sum_irr_il and self.ic:
            ch.append(self.ic)
        ch.append(self.il)
        if not self.irr_from_ic_minus_il and self.irr:
            ch.append(self.irr)
        ch.extend((self.v_diode, self.vge_other))
        return tuple(ch)


# Channel wiring is the same for U / V / W; only DUT and filename prefix differ.
_UPPER_CHANNELS = dict(
    vge="CH1",
    vce="CH2",
    ic="",  # 上桥默认用 Irr+IL 相加，不读单独 Ic 列
    il="CH4",
    irr="CH3",
    v_diode="CH5",
    vge_other="CH6",
    ic_from_sum_irr_il=True,
)

# 下桥：DUT 为 CH6/CH5/CH2/CH1；电流与上桥同一套公式，仅示波器接线不同——
# 上桥 Ic=CH3+CH4、Irr=CH3；下桥 WL 样例 Ic=CH3、Irr=CH3−CH4（MATH1）。
_LOWER_CHANNELS = dict(
    vge="CH6",
    vce="CH5",
    ic="CH3",
    il="CH4",
    irr="",
    v_diode="CH2",
    vge_other="CH1",
    ic_from_sum_irr_il=False,
    irr_from_ic_minus_il=True,
)


def make_profile(phase: str, bridge: str) -> BridgeProfile:
    phase = phase.upper()
    if phase not in PHASES:
        raise ValueError(f"phase must be one of {PHASES}")
    bridge = bridge.lower()
    if bridge not in ("upper", "lower"):
        raise ValueError("bridge must be 'upper' or 'lower'")

    code = f"{phase}{'H' if bridge == 'upper' else 'L'}"
    bridge_cn = "上桥" if bridge == "upper" else "下桥"
    if bridge == "upper":
        channels = dict(_UPPER_CHANNELS)
    else:
        channels = dict(_LOWER_CHANNELS)

    return BridgeProfile(
        name=f"{phase.lower}_{bridge}",
        display_name=f"{phase}相-{bridge_cn} ({code})",
        phase=phase,
        bridge=bridge,
        code=code,
        **channels,
    )


def all_profiles() -> list[BridgeProfile]:
    return [make_profile(p, b) for p in PHASES for b in ("upper", "lower")]


# Legacy aliases (W phase)
UPPER_BRIDGE = make_profile("W", "upper")
LOWER_BRIDGE = make_profile("W", "lower")
WH_PROFILE = UPPER_BRIDGE
WL_PROFILE = LOWER_BRIDGE

# Build lookup tables
ALL_PROFILES: list[BridgeProfile] = all_profiles()
PROFILES: dict[str, BridgeProfile] = {}
for prof in ALL_PROFILES:
    PROFILES[prof.name] = prof
    PROFILES[prof.code] = prof
    PROFILES[prof.code.upper()] = prof
    PROFILES[prof.code.lower()] = prof
# backward compatibility
PROFILES["upper"] = UPPER_BRIDGE
PROFILES["lower"] = LOWER_BRIDGE
PROFILES["WH"] = UPPER_BRIDGE
PROFILES["WL"] = LOWER_BRIDGE

# Filename token -> profile (order: longer codes first)
_CODE_ORDER = ("UH", "UL", "VH", "VL", "WH", "WL")

_PHASE_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "U": ("U", "UA", "PHASEU", "PHU", "A", "PHA", "PHASEA"),
    "V": ("V", "VB", "PHASEV", "PHV", "B", "PHB", "PHASEB"),
    "W": ("W", "WC", "PHASEW", "PHW", "C", "PHC", "PHASEC"),
}
_UPPER_TOKENS = {"H", "HS", "HIGH", "HIGHSIDE", "UPPER", "TOP", "HI"}
_LOWER_TOKENS = {"L", "LS", "LOW", "LOWSIDE", "LOWER", "BOTTOM", "BOT"}


def _tokenize_path_for_guess(path: Path) -> tuple[str, ...]:
    """Split stem/parent into coarse tokens for robust profile guessing."""
    text = f"{path.parent.name}_{path.stem}".upper()
    parts = [p for p in re.split(r"[^A-Z0-9]+", text) if p]
    # Keep canonical code chunks for direct alias matching like "phase_u".
    parts.extend(
        p
        for p in (path.stem.upper(), path.parent.name.upper())
        if p and p not in parts
    )
    return tuple(parts)


def _guess_phase_from_tokens(tokens: tuple[str, ...]) -> str | None:
    for phase, aliases in _PHASE_TOKEN_ALIASES.items():
        if any(tok in aliases for tok in tokens):
            return phase
    return None


def _guess_bridge_from_tokens(tokens: tuple[str, ...]) -> str | None:
    if any(tok in _UPPER_TOKENS for tok in tokens):
        return "upper"
    if any(tok in _LOWER_TOKENS for tok in tokens):
        return "lower"
    return None


def guess_profile_from_path(path: str | Path) -> BridgeProfile:
    p = Path(path)
    stem = p.stem.upper()
    for code in _CODE_ORDER:
        if code in stem:
            return PROFILES[code]
    # fallback: H/L at end of name e.g. xxx_UH_xxx
    for code in _CODE_ORDER:
        if stem.endswith(code) or f"_{code}_" in stem:
            return PROFILES[code]
    tokens = _tokenize_path_for_guess(p)
    phase = _guess_phase_from_tokens(tokens)
    bridge = _guess_bridge_from_tokens(tokens)
    if phase and bridge:
        return make_profile(phase, bridge)
    if bridge:
        return make_profile("W", bridge)
    return UPPER_BRIDGE


def profile_from_combo_data(data) -> BridgeProfile:
    if isinstance(data, BridgeProfile):
        return data
    if isinstance(data, str) and data in PROFILES:
        return PROFILES[data]
    return UPPER_BRIDGE
