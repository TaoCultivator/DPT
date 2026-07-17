from __future__ import annotations

from dataclasses import dataclass

# 行键：与结果表 (分区, 参数) 对应
SLOPE_ROW_KEYS: dict[tuple[str, str], str] = {
    ("关断过程", "dv/dt"): "off_dvdt",
    ("关断过程", "di/dt"): "off_didt",
    ("开通", "dv/dt"): "on_dvdt",
    ("开通", "di/dt"): "on_didt",
    ("反向恢复", "dv/dt"): "rr_dvdt",
    ("反向恢复", "di/dt"): "rr_didt",
}

# (标签, 起点%, 终点%[, 电流参考 peak|plateau][, 沿 rise|fall])
SlopePreset = tuple[str, float, float] | tuple[str, float, float, str] | tuple[str, float, float, str, str]

SLOPE_RANGE_PRESETS: dict[str, list[SlopePreset]] = {
    # 关断 di/dt：阈值相对当前关断窗最大电流（与 Ic_off_max 同口径）
    "off_didt": [
        ("90%→10%", 90.0, 10.0, "top", "fall"),
        ("90%→50%", 90.0, 50.0, "top", "fall"),
        ("80%→20%", 80.0, 20.0, "top", "fall"),
    ],
    # 关断 dv/dt：(1) 0.1→0.9·Vce；(2) 0.2→0.8·Vce
    "off_dvdt": [
        ("10%→90%", 10.0, 90.0),
        ("20%→80%", 20.0, 80.0),
    ],
    # 开通 di/dt：阈值相对开通 Top（100% Ic 平台）
    "on_didt": [
        ("10%→90%", 10.0, 90.0, "top", "rise"),
        ("50%→90%", 50.0, 90.0, "top", "rise"),
        ("80%→20%", 80.0, 20.0, "top", "rise"),
    ],
    # 开通 dv/dt：(1) 0.9→0.1·Vce；(2) 0.8→0.2·Vce
    "on_dvdt": [
        ("90%→10%", 90.0, 10.0),
        ("80%→20%", 80.0, 20.0),
    ],
    # 反向恢复二极管 di/dt：Ha=0div、Hb=IDM（规格书 0.9·IDM→0.1·IDM / 0.8→0.2）
    # (3) 50%IF→50%IRM — IF 同 IDM 下降沿；IRM 为零交叉↔尖峰
    "rr_didt": [
        ("90%→10%", 90.0, 10.0, "idm"),
        ("80%→20%", 80.0, 20.0, "idm"),
        ("50%IF→50%IRM", 50.0, 50.0, "if_irm"),
    ],
    # 反向恢复二极管 dv/dt：|VDM| 幅值
    # (1) 0.1*|VDM|→0.9*|VDM| => 10%→90%
    # (2) 0.2*|VDM|→0.8*|VDM| => 20%→80%
    "rr_dvdt": [
        ("10%→90%", 10.0, 90.0),
        ("20%→80%", 20.0, 80.0),
    ],
}

CUSTOM_RANGE_LABEL = "自定义…"
RR_DIDT_CUSTOM_IDM = "IDM 百分比（Ha=0, Hb=IDM）"
RR_DIDT_CUSTOM_IF_IRM = "零基准百分比（H0=0, Ha=IF, Hb=IRM）"


@dataclass(frozen=True)
class SlopeRange:
    start_pct: float
    end_pct: float
    #: top=关断前电流平台；peak=窗内峰值；plateau=开通 Ic 平台
    #: 反向恢复 rr_didt：idm=0~IDM 百分比；if_irm=50%IF→50%IRM
    ic_reference: str = "plateau"
    #: rise=电流上升穿越，fall=电流下降穿越
    ic_direction: str = "rise"
    #: 非空时覆盖 label()（如 50%IF→50%IRM）
    preset_label: str = ""

    def label(self) -> str:
        if self.preset_label:
            return self.preset_label
        return f"{self.start_pct:g}%→{self.end_pct:g}%"

    def as_fractions(self) -> tuple[float, float]:
        return self.start_pct / 100.0, self.end_pct / 100.0


def preset_to_range(preset: SlopePreset) -> SlopeRange:
    plabel, a, b = preset[0], preset[1], preset[2]
    ic_ref = "plateau"
    direction = "fall" if a > b else "rise"
    if len(preset) >= 4:
        ic_ref = str(preset[3])
    if len(preset) >= 5:
        direction = str(preset[4])
    use_preset_label = plabel if ic_ref == "if_irm" else ""
    return SlopeRange(
        a,
        b,
        ic_reference=ic_ref,
        ic_direction=direction,
        preset_label=use_preset_label,
    )


def default_slope_ranges() -> dict[str, SlopeRange]:
    return {
        "off_didt": SlopeRange(90.0, 10.0, ic_reference="top", ic_direction="fall"),
        "off_dvdt": SlopeRange(10.0, 90.0),
        "on_didt": SlopeRange(10.0, 90.0, ic_reference="top", ic_direction="rise"),
        "on_dvdt": SlopeRange(90.0, 10.0),
        "rr_didt": SlopeRange(90.0, 10.0, ic_reference="idm", ic_direction="fall"),
        "rr_dvdt": SlopeRange(10.0, 90.0),
    }


def slope_range_matches_preset(key: str, sr: SlopeRange, pr: SlopeRange) -> bool:
    """dv/dt 仅比较百分比；di/dt 还需比较电流参考与沿方向。"""
    if abs(pr.start_pct - sr.start_pct) >= 0.05 or abs(pr.end_pct - sr.end_pct) >= 0.05:
        return False
    # 反向恢复 dv/dt：只按百分比匹配
    if key == "rr_dvdt":
        return True
    if key == "rr_didt":
        return pr.ic_reference == sr.ic_reference
    if key.endswith("dvdt"):
        return True
    return pr.ic_reference == sr.ic_reference and pr.ic_direction == sr.ic_direction


def normalize_slope_range(key: str, sr: SlopeRange) -> SlopeRange:
    """若与某条预设百分比一致，则对齐为预设完整字段（避免误判为自定义）。"""
    idx = preset_index_for_range(key, sr)
    if idx < 0:
        return sr
    return preset_to_range(SLOPE_RANGE_PRESETS[key][idx])


def preset_index_for_range(key: str, sr: SlopeRange) -> int:
    presets = SLOPE_RANGE_PRESETS.get(key, [])
    for i, p in enumerate(presets):
        pr = preset_to_range(p)
        if slope_range_matches_preset(key, sr, pr):
            return i
    return -1
