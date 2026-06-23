from __future__ import annotations

import re

from dpt_extractor.models.channel_mapping import ChannelMapping, sort_channel_names

# 电感电流（IGBT / MOSFET 通用）
_IL_PATTERNS = (r"^IL$",)

# --- 被测管门极（上桥 / 下桥）---
_UPPER_VGE_PATTERNS = (
    r"VGEVH$",
    r"VGESH$",
    r"^HVGE",
    r"VGEH",
    r"VGE.*H",
    r"VGSVH$",
    r"VGSSH$",
    r"^HVGS",
    r"VGSH",
    r"VGS.*H",
)
_LOWER_VGE_PATTERNS = (
    r"VGEVL$",
    r"VGESL$",
    r"^LVGE",
    r"VGEL",
    r"VGE.*L",
    r"VGSVL$",
    r"VGSSL$",
    r"^LVGS",
    r"VGSL",
    r"VGS.*L",
)

# --- 被测管主电压 Vce(IGBT) / Vds(MOSFET) ---
_UPPER_VCE_PATTERNS = (
    r"VCEVH$",
    r"VCEH$",
    r"^HVCE",
    r"VCE.*H",
    r"VDSVH$",
    r"VDSH$",
    r"^HVDS",
    r"VDS.*H",
)
_LOWER_VCE_PATTERNS = (
    r"VCEVL$",
    r"VCEL$",
    r"^LVCE",
    r"VCE.*L",
    r"VDSVL$",
    r"VDSL$",
    r"^LVDS",
    r"VDS.*L",
)

# --- 对管/换流二极管侧电压（上桥看低侧 Vce/Vds，下桥看高侧）---
_UPPER_VDIODE_PATTERNS = _LOWER_VCE_PATTERNS
_LOWER_VDIODE_PATTERNS = _UPPER_VCE_PATTERNS

# --- 对管门极 ---
_UPPER_VGE_OTHER_PATTERNS = _LOWER_VGE_PATTERNS
_LOWER_VGE_OTHER_PATTERNS = _UPPER_VGE_PATTERNS
_VDESAT_PATTERNS = (r"^DESAT$", r"VDESAT", r"DESATV", r"DSAT")

# 上桥：下桥支路电流（IGBT: IC_VL / Ic；MOSFET: IVL / Id 低侧支路）
_UPPER_LOWER_ARM_PATTERNS = (
    r"ICVL$",
    r"IC.*VL$",
    r"IVL$",
    r"IDVL$",
    r"ID.*VL$",
    r"^IRR$",
    r"ILOW",
    r"ICLOW",
    r"IDLOW",
    r"^IC$",  # WH 等：Ic 接下桥回路
)

# 下桥：被测管总电流（IGBT: Ic；MOSFET: Id / Ids / IVL）
_LOWER_TOTAL_IC_PATTERNS = (
    r"^ICTOTAL$",
    r"^IDTOTAL$",
    r"^IC$",
    r"^ID$",
    r"^IDS$",
    r"IVL$",  # 下桥被测时低侧漏极电流探头常标 IVL
    r"IDVL$",
    r"ICDUT",
    r"IDDUT",
    r"ICMAIN",
    r"IDMAIN",
)

# 下桥总电流列排除：高侧支路分量（非被测管总电流）
_LOWER_IC_EXCLUDE_NORM = (
    r"ICVH$",
    r"IDVH$",
    r"IC.*VH$",
    r"ID.*VH$",
    r"^IRR$",
    r"ILOW",
    r"ICLOW",
    r"IDLOW",
)


def _norm_label(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def _is_raw_scope_channel(ch: str) -> bool:
    return bool(re.fullmatch(r"CH[1-6]", ch.upper()))


def _default_mapping_for_bridge(bridge: str) -> ChannelMapping:
    if bridge.lower() == "upper":
        return ChannelMapping(
            vge="CH1",
            vce="CH2",
            ic="",
            il="CH4",
            irr="CH3",
            v_diode="CH5",
            vge_other="CH6",
            ic_from_sum_irr_il=True,
            irr_from_ic_minus_il=False,
        )
    return ChannelMapping(
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


def _fallback_raw_channel(
    available: set[str],
    channel: str,
    used: set[str],
) -> str | None:
    channel = channel.upper()
    if channel in available and channel not in used:
        return channel
    return None


def _pick_channel(
    labeled: list[tuple[str, str]],
    patterns: tuple[str, ...],
    used: set[str],
    *,
    exclude_norm: tuple[str, ...] = (),
) -> str | None:
    best_ch: str | None = None
    best_score = 0
    for ch, norm in labeled:
        if ch in used or not norm:
            continue
        if any(re.search(ex, norm) for ex in exclude_norm):
            continue
        for prio, pat in enumerate(patterns):
            if re.search(pat, norm):
                score = 1000 - prio
                if score > best_score:
                    best_score = score
                    best_ch = ch
                break
    return best_ch


def _labeled_scope_channels(
    labels: dict[str, str],
    available: set[str],
) -> list[tuple[str, str]]:
    by_channel: dict[str, str] = {}
    for ch, lab in labels.items():
        key = ch.upper()
        if key in available and _is_raw_scope_channel(key) and lab:
            by_channel[key] = _norm_label(lab)
    return [(ch, by_channel[ch]) for ch in sort_channel_names(by_channel)]


def _is_lower_arm_current_norm(norm: str) -> bool:
    """是否为「下桥支路电流」类标签（非 IL、非被测管总电流）。"""
    if norm == "IL":
        return False
    if any(re.search(ex, norm) for ex in _LOWER_IC_EXCLUDE_NORM):
        return True
    if re.search(r"ICVL|IDVL|IVL|ILOW|ICLOW|IDLOW", norm):
        return True
    if norm in ("IC", "ID"):
        return True
    if re.search(r"^IRR$", norm):
        return True
    return False


def _pick_upper_lower_arm_current(
    labeled: list[tuple[str, str]],
    used: set[str],
    il_ch: str | None,
) -> str | None:
    """上桥：下桥支路电流探头（IGBT/MOS 标签均可）。"""
    ch = _pick_channel(labeled, _UPPER_LOWER_ARM_PATTERNS, used)
    if ch:
        return ch
    for ch, norm in labeled:
        if ch in used or ch == il_ch:
            continue
        if _is_lower_arm_current_norm(norm):
            return ch
    return None


def _pick_lower_total_ic(
    labeled: list[tuple[str, str]],
    used: set[str],
) -> str | None:
    """下桥：被测管总电流列（IGBT Ic / MOSFET Id）。"""
    return _pick_channel(
        labeled,
        _LOWER_TOTAL_IC_PATTERNS,
        used,
        exclude_norm=_LOWER_IC_EXCLUDE_NORM,
    )


def _apply_upper_current_logic(
    m: ChannelMapping,
    labeled: list[tuple[str, str]],
    used: set[str],
    available: set[str],
) -> bool:
    """
    上桥被测：Ic = 下桥支路电流 + 电感电流（两探头逐点相加）。
    """
    il_ch = _pick_channel(labeled, _IL_PATTERNS, used)
    if not il_ch:
        il_ch = _fallback_raw_channel(available, "CH4", used)
    if not il_ch:
        return False
    m.il = il_ch
    used.add(il_ch)

    lower_arm = _pick_upper_lower_arm_current(labeled, used, il_ch)
    if not lower_arm:
        lower_arm = _fallback_raw_channel(available, "CH3", used)
    if not lower_arm or lower_arm == il_ch:
        return False

    m.irr = lower_arm
    m.ic = ""
    m.ic_from_sum_irr_il = True
    m.irr_from_ic_minus_il = False
    used.add(lower_arm)
    return True


def _apply_lower_current_logic(
    m: ChannelMapping,
    labeled: list[tuple[str, str]],
    used: set[str],
    available: set[str],
) -> bool:
    """
    下桥被测：总电流直接测量；Irr = 总电流 − 电感电流。
    """
    il_ch = _pick_channel(labeled, _IL_PATTERNS, used)
    if not il_ch:
        il_ch = _fallback_raw_channel(available, "CH4", used)
    if not il_ch:
        return False
    m.il = il_ch
    used.add(il_ch)

    ic_ch = _pick_lower_total_ic(labeled, used)
    if not ic_ch:
        ic_ch = _fallback_raw_channel(available, "CH3", used)
    if not ic_ch or ic_ch == il_ch:
        return False

    m.ic = ic_ch
    m.irr = ""
    m.ic_from_sum_irr_il = False
    m.irr_from_ic_minus_il = True
    used.add(ic_ch)
    return True


def infer_channel_mapping(
    labels: dict[str, str],
    bridge: str,
    available: set[str] | None = None,
) -> ChannelMapping | None:
    """
    根据示波器 Label 推断映射（兼容 IGBT：Vge/Vce/Ic 与 MOSFET：Vgs/Vds/Id/IVL）。

    电流逻辑：
    - 上桥：Ic = 下桥支路电流 + IL
    - 下桥：Irr = 总电流 − IL
    """
    if not labels:
        return None

    avail = {ch.upper() for ch in (available or set(labels.keys()))}
    labeled = _labeled_scope_channels(labels, avail)
    if not labeled:
        return None

    is_upper = bridge.lower() == "upper"
    used: set[str] = set()
    m = _default_mapping_for_bridge(bridge)

    if is_upper:
        vge_p = _UPPER_VGE_PATTERNS
        vce_p = _UPPER_VCE_PATTERNS
        vdiode_p = _UPPER_VDIODE_PATTERNS
        vge_other_p = _UPPER_VGE_OTHER_PATTERNS
    else:
        vge_p = _LOWER_VGE_PATTERNS
        vce_p = _LOWER_VCE_PATTERNS
        vdiode_p = _LOWER_VDIODE_PATTERNS
        vge_other_p = _LOWER_VGE_OTHER_PATTERNS

    for attr, patterns in (
        ("vge", vge_p),
        ("vce", vce_p),
        ("v_diode", vdiode_p),
        ("vge_other", vge_other_p),
    ):
        ch = _pick_channel(labeled, patterns, used)
        if ch:
            setattr(m, attr, ch)
            used.add(ch)
    vdesat = _pick_channel(labeled, _VDESAT_PATTERNS, used)
    if vdesat:
        m.vdesat = vdesat
        used.add(vdesat)

    if is_upper:
        if not _apply_upper_current_logic(m, labeled, used, avail):
            return None
    else:
        if not _apply_lower_current_logic(m, labeled, used, avail):
            return None

    if not m.vge or not m.vce or not m.il:
        return None
    return m


def infer_short_circuit_mapping(
    labels: dict[str, str],
    bridge: str,
    available: set[str] | None = None,
) -> ChannelMapping | None:
    """
    根据示波器 Label 推断短路测试映射。

    短路模式只需要 DUT Vge/Vce、短路电流 Ic、对管 Vce/Vge；不使用双脉冲
    IL/Irr 的组合电流逻辑。
    """
    if not labels:
        return None

    avail = {ch.upper() for ch in (available or set(labels.keys()))}
    labeled = _labeled_scope_channels(labels, avail)
    if not labeled:
        return None

    is_upper = bridge.lower() == "upper"
    used: set[str] = set()
    if is_upper:
        m = ChannelMapping(
            vge="CH1",
            vce="CH2",
            ic="CH3",
            il="",
            irr="",
            v_diode="CH5",
            vge_other="CH6",
            ic_from_sum_irr_il=False,
            irr_from_ic_minus_il=False,
        )
        vge_p = _UPPER_VGE_PATTERNS
        vce_p = _UPPER_VCE_PATTERNS
        vdiode_p = _UPPER_VDIODE_PATTERNS
        vge_other_p = _UPPER_VGE_OTHER_PATTERNS
    else:
        m = ChannelMapping(
            vge="CH6",
            vce="CH5",
            ic="CH3",
            il="",
            irr="",
            v_diode="CH2",
            vge_other="CH1",
            ic_from_sum_irr_il=False,
            irr_from_ic_minus_il=False,
        )
        vge_p = _LOWER_VGE_PATTERNS
        vce_p = _LOWER_VCE_PATTERNS
        vdiode_p = _LOWER_VDIODE_PATTERNS
        vge_other_p = _LOWER_VGE_OTHER_PATTERNS

    for attr, patterns in (
        ("vge", vge_p),
        ("vce", vce_p),
        ("v_diode", vdiode_p),
        ("vge_other", vge_other_p),
    ):
        ch = _pick_channel(labeled, patterns, used)
        if ch:
            setattr(m, attr, ch)
            used.add(ch)
    vdesat = _pick_channel(labeled, _VDESAT_PATTERNS, used)
    if vdesat:
        m.vdesat = vdesat
        used.add(vdesat)

    current = _pick_channel(
        labeled,
        _LOWER_TOTAL_IC_PATTERNS + _UPPER_LOWER_ARM_PATTERNS,
        used,
        exclude_norm=_IL_PATTERNS,
    )
    if not current:
        current = _fallback_raw_channel(avail, "CH3", used)
    if current:
        m.ic = current
        used.add(current)

    required = (m.vge, m.vce, m.ic, m.v_diode, m.vge_other)
    if not all(ch and ch.upper() in avail for ch in required):
        return None
    return m
