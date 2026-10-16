"""无界面光标-波形绑定校验：对代表性工况逐参数触发 GUI 交互，
回读 MainWindow 传给 wave_plot 的光标放置参数（绑定通道 / A/B 时刻 / Ha/Hb 电平），
断言每个数据光标落在正确波形的正确特征上，输出 OK/FAIL 矩阵。

以 UH 上桥为基准，重点暴露下桥（Irr=Ic−IL 为负、Vd 负偏）的极性类不兼容。
默认使用代表性样本以保证 GUI 子进程审计在单测超时内完成；设置
DPT_VALIDATE_ALL_CURSORS=1 可扫描所有示例 .tss。
DPT_VALIDATE_DPT_ONLY=1 可在全量模式下仅扫描非短路样例，并在分页前过滤。
DPT_VALIDATE_CURSOR_MATCH 可按路径片段过滤，再由 OFFSET/LIMIT 分批；
DPT_VALIDATE_SAMPLE_ROOT 可指定仓库外的原始 TSS 语料根目录；
DPT_VALIDATE_FOCUS_ONLY=1 可只审计参数局部取景、真实 A/B 可见性及
通道高亮后的绑定稳定性，用于把显示层回归与既有测量语义告警分开；
OFFSET/LIMIT 同时适用于默认代表样本和全量样本，避免 GUI 长进程累积资源。
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
import os
import re
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

from dpt_extractor.gui.waveform_plot import (  # noqa: E402
    PARAMETER_POWER_REFERENCE_CHANNEL,
    PARAM_FOCUS_ANCHOR_FRACTION,
    PARAM_FOCUS_REQUIRED_GUARD_US,
    PARAM_FOCUS_RIGHT_PRIORITY_LATEST_FRACTION,
    TURN_ON_CURRENT_FOCUS_MIDPOINT_FRACTION,
    TURN_ON_LS_FOCUS_MIDPOINT_FRACTION,
    TURN_ON_SLOPE_FOCUS_MIDPOINT_FRACTION,
    RR_POWER_FOCUS_MIDPOINT_FRACTION,
    TF_FOCUS_MIDPOINT_FRACTION,
    _is_power_unit,
    _solve_parameter_x_window,
)
from dpt_extractor.metrics.commutation_inductance import (  # noqa: E402
    turn_on_commutation_inductance,
)
from dpt_extractor.metrics.iec_timings import (  # noqa: E402
    turn_off_ic_fall_window,
    turn_on_vce_top_from_ic_rise,
)
from dpt_extractor.metrics.plateau_level import (  # noqa: E402
    _plateau_mid_without_isolated_spikes,
    turn_off_delta_vce_cursor_range_indices,
    turn_off_dvdt_base_top_levels,
    turn_on_dvdt_base_top_levels,
    turn_on_current_hb_ha_window_indices,
    turn_on_current_cursor_hb_a_us,
    turn_on_ic_b_cross_ha_us,
)
from dpt_extractor.metrics.slopes import (  # noqa: E402
    _rr_dvdt_stable_base_top,
)
from dpt_extractor.models.waveform import (  # noqa: E402
    bundle_reverse_recovery_current,
    bundle_total_current,
)
from dpt_extractor.models.results import (  # noqa: E402
    SHORT_CIRCUIT_TSC_RANGE_DEFAULT,
)
from dpt_extractor.models.slope_range import (  # noqa: E402
    AUTO_MAX_SLOPE_SPAN_PERCENT,
    SLOPE_ROW_KEYS,
    auto_max_slope_range,
)
from dpt_extractor.models.test_mode import TestMode  # noqa: E402
from dpt_extractor.utils.sample_corpus import discover_sample_waveforms  # noqa: E402

# 每个交互参数：(section, name)。Vce_off_max 等走 generic interval（带横向峰）。
INTERACTIVE_PARAMS = [
    ("关断过程", "Ls_off"),
    ("关断过程", "Toff"),
    ("关断过程", "Td_off"),
    ("关断过程", "Tf"),
    ("关断过程", "Pmax"),
    ("关断过程", "dv/dt"),
    ("关断过程", "di/dt"),
    ("关断过程", "Eoff"),
    ("关断过程", "ΔVce"),
    ("关断过程", "Ic_off_max"),
    ("关断过程", "Vce_off_max"),
    ("关断过程", "串扰电压"),
    ("开通", "dv/dt"),
    ("开通", "di/dt"),
    ("开通", "Eon"),
    ("开通", "ΔVce"),
    ("开通", "开通电流"),
    ("开通", "Ic_on_max"),
    ("开通", "Vce_on_max"),
    ("开通", "串扰电压"),
    ("开通", "Ls_on"),
    ("开通", "Ton"),
    ("开通", "Td_on"),
    ("开通", "Tr"),
    ("开通", "Pmax"),
    ("反向恢复", "Irr"),
    ("反向恢复", "Trr"),
    ("反向恢复", "Vrr"),
    ("反向恢复", "dv/dt"),
    ("反向恢复", "di/dt"),
    ("反向恢复", "Pdmax"),
    ("反向恢复", "Err"),
]

# 人工验收矩阵：每个参数卡必须说明 A/B 与 Ha/Hb 的物理角色。
# “不适用”表示该卡按规范只显示纵向区间或单条峰值参考线，并非漏检。
DPT_PARAMETER_CURSOR_ROLES = {
    ("关断过程", "Ls_off"): "A/B=主Vce正过冲与Ic同步积分窗；Ha/Hb=不适用；逻辑=∫max(Vce−Top,0)dt÷|ΔIc|，受手动ΔVce幅值校准",
    ("关断过程", "Toff"): "A=Vge下降90%；B=Ic下降10%；Ha/Hb=不适用",
    ("关断过程", "Td_off"): "A=Vge下降90%；B=Ic下降90%；Ha/Hb=不适用",
    ("关断过程", "Tf"): "A=Ic下降90%；B=Ic下降10%；Ha/Hb=不适用",
    ("关断过程", "Pmax"): "A/B=Eoff功率窗口；Ha=Vce×Ic峰（无匹配功率Math时使用只读功率参考）；Hb=不适用",
    ("关断过程", "dv/dt"): "A/B=Vce阈值交点；Ha/Hb=Vce Top/Base",
    ("关断过程", "di/dt"): "A/B=Ic阈值交点；Ha/Hb=Ic Top/Base",
    ("关断过程", "Eoff"): (
        "A=Vce Base稳定带代表点(smooth)/Vce与Ha交点(fallback)；"
        "B=Ic Base稳定带代表点(smooth)/Ic与Hb交点(fallback)；"
        "Ha=Vce；Hb=Ic"
    ),
    ("关断过程", "ΔVce"): "A=抬升前Vce Base稳定段；B=尖峰后Vce Top稳定段；Ha=Vce尖峰最大值；Hb=Vce Top稳定值",
    ("关断过程", "Ic_off_max"): "A=Vce抬升前Base稳定段；B=Ic抬升前Base稳定段；Ha=Ic最大值；Hb=Ic Base稳定值",
    ("关断过程", "Vce_off_max"): "A=Vce抬升前Base稳定段；B=尖峰后Top稳定段；Ha=Vce最大值；Hb=Vce Top稳定值",
    ("关断过程", "串扰电压"): "A/B=对管Vge最大/最小时刻；Ha=Vge最大值；Hb=Vge最小值",
    ("开通", "dv/dt"): "A/B=Vce阈值交点；Ha/Hb=跌落前后稳定高/低电压平台",
    ("开通", "di/dt"): "A/B=Ic阈值交点；Ha/Hb=Ic Top/Base",
    ("开通", "Eon"): "A=Ic与Ha交点；B=Vce与Hb交点；Ha=Ic；Hb=Vce",
    ("开通", "ΔVce"): "A=Vce下降前Top稳定段；B=下降后Base稳定段；Ha=Vce Top；Hb=Vce下降拐点",
    ("开通", "开通电流"): "A/Hb=Ic基线；B/Ha=Ic导通平台",
    ("开通", "Ic_on_max"): "A=Ic抬升前Base稳定段；B=Ic震荡结束后Top稳定段；Ha=Ic最大值；Hb=Ic Base稳定值",
    ("开通", "Vce_on_max"): "A=Vce最大值左侧相邻Top段；B=Vce下降及震荡结束后首个Base稳定段；Ha=Vce最大值；Hb=Vce Base稳定值",
    ("开通", "串扰电压"): "A/B=对管Vge最大/最小时刻；Ha=Vge最大值；Hb=Vge最小值",
    ("开通", "Ls_on"): "A/B=Ic斜率交点同步积分窗；Ha/Hb=不适用；逻辑=∫max(Top−Vce,0)dt÷|ΔIc|，受手动ΔVce幅值校准",
    ("开通", "Ton"): "A=Vge上升10%；B=Ic上升90%；Ha/Hb=不适用",
    ("开通", "Td_on"): "A=Vge上升10%；B=Ic上升10%；Ha/Hb=不适用",
    ("开通", "Tr"): "A=Ic上升10%；B=Ic上升90%；Ha/Hb=不适用",
    ("开通", "Pmax"): "A/B=Eon功率窗口；Ha=Vce×Ic峰（无匹配功率Math时使用只读功率参考）；Hb=不适用",
    ("反向恢复", "Irr"): "A=Irr正向稳定段；B=恢复Base稳定段；Ha=Irr恢复Base；Hb=Irr有符号尖峰",
    ("反向恢复", "Trr"): (
        "A/B=逻辑Irr主瓣上升/下降沿与Ha首交点；"
        "Ha=峰后恢复稳定平台max/min平均中线；Hb=有符号I_RM尖峰"
    ),
    ("反向恢复", "Vrr"): "A=Vd抬升前Base稳定段；B=尖峰后Top稳定段；Ha=Vd最大值；Hb=Vd Top稳定值",
    ("反向恢复", "dv/dt"): "A/B=|Vd|阈值交点；Ha/Hb=主上升后/前稳定高/低电压平台",
    ("反向恢复", "di/dt"): "A/B=Irr阈值交点；Ha/Hb=Irr恢复平台/正向平台",
    ("反向恢复", "Pdmax"): "A=Irr抬升前稳定平台；B=震荡后首个稳定平台；取A/B间原始|Vd|×|Irr|峰；无可信功率轨迹时Ha/Hb=不适用",
    ("反向恢复", "Err"): "A=Irr与Ha交点；B=Vd与Hb交点；Ha=Irr首个无显著后续漂移稳定带中点；Hb=Vd主上升前本地Base",
}

IEC_TIMING_CURSOR_ROLES = {
    key: value
    for key, value in DPT_PARAMETER_CURSOR_ROLES.items()
    if key[1] in {"Toff", "Td_off", "Tf", "Ton", "Td_on", "Tr"}
}

IEC_TIMING_ENDPOINT_CHANNELS = {
    ("开通", "Ton"): ("vge", "ic"),
    ("开通", "Td_on"): ("vge", "ic"),
    ("开通", "Tr"): ("ic", "ic"),
    ("关断过程", "Toff"): ("vge", "ic"),
    ("关断过程", "Td_off"): ("vge", "ic"),
    ("关断过程", "Tf"): ("ic", "ic"),
}

GENERIC_MAX_CURSOR_CHANNELS = {
    "Ic_off_max": "ic",
    "Vce_off_max": "vce",
    "Ic_on_max": "ic",
    "Vce_on_max": "vce",
    "Vrr": "v_diode",
}

GENERIC_MAX_ENDPOINT_CHANNELS = {
    ("关断过程", "Ic_off_max"): ("vce", "ic"),
    ("关断过程", "Vce_off_max"): ("vce", "vce"),
    ("开通", "Ic_on_max"): ("ic", "ic"),
    ("开通", "Vce_on_max"): ("vce", "vce"),
    ("反向恢复", "Vrr"): ("v_diode", "v_diode"),
}

# Every DPT card must bind each vertical cursor to the waveform that defines
# that endpoint.  Power cards are intentionally dynamic: when a real W/kW
# trace is visible both endpoints belong to that trace; otherwise they bind to
# the two raw V/I boundary waves and are filled in by the power branch below.
DPT_ENDPOINT_CHANNELS = {
    ("关断过程", "Ls_off"): ("ic", "ic"),
    **IEC_TIMING_ENDPOINT_CHANNELS,
    ("关断过程", "dv/dt"): ("vce", "vce"),
    ("关断过程", "di/dt"): ("ic", "ic"),
    ("关断过程", "Eoff"): ("vce", "ic"),
    ("关断过程", "ΔVce"): ("vce", "vce"),
    **GENERIC_MAX_ENDPOINT_CHANNELS,
    ("关断过程", "串扰电压"): ("vge_other", "vge_other"),
    ("开通", "dv/dt"): ("vce", "vce"),
    ("开通", "di/dt"): ("ic", "ic"),
    ("开通", "Eon"): ("ic", "vce"),
    ("开通", "ΔVce"): ("vce", "vce"),
    ("开通", "开通电流"): ("ic", "ic"),
    ("开通", "串扰电压"): ("vge_other", "vge_other"),
    ("开通", "Ls_on"): ("ic", "ic"),
    ("反向恢复", "Irr"): ("irr", "irr"),
    ("反向恢复", "Trr"): ("irr", "irr"),
    ("反向恢复", "dv/dt"): ("v_diode", "v_diode"),
    ("反向恢复", "di/dt"): ("irr", "irr"),
    ("反向恢复", "Err"): ("irr", "v_diode"),
}

_AUTO_SLOPE_LABEL_RE = re.compile(
    r"^自动\s+(-?\d+(?:\.\d+)?)%→(-?\d+(?:\.\d+)?)%"
    r"（(\d+(?:\.\d+)?)\s+ns）$"
)


def _auto_slope_label_has_fixed_span(label: object) -> bool:
    match = _AUTO_SLOPE_LABEL_RE.fullmatch(str(label))
    if match is None:
        return False
    pct_a = float(match.group(1))
    pct_b = float(match.group(2))
    duration_ns = float(match.group(3))
    return (
        abs(abs(pct_a - pct_b) - AUTO_MAX_SLOPE_SPAN_PERCENT) <= 0.11
        and duration_ns > 0.0
    )


def _effective_slope_percentages(
    slope_range,
    crossing,
    fallback: tuple[float, float],
) -> tuple[float, float]:
    if slope_range is not None and slope_range.is_auto_max:
        pct_a = getattr(crossing, "resolved_pct_a", None)
        pct_b = getattr(crossing, "resolved_pct_b", None)
        if pct_a is not None and pct_b is not None:
            return float(pct_a), float(pct_b)
    if slope_range is not None:
        return slope_range.as_fractions()
    return fallback

# (channel, valid) for Ha/Hb.  An invalid cursor must remain hidden and must
# not inherit a stale line from the previously selected parameter card.
DPT_HORIZONTAL_BINDINGS = {
    ("关断过程", "Ls_off"): ((None, False), (None, False)),
    ("关断过程", "Toff"): ((None, False), (None, False)),
    ("关断过程", "Td_off"): ((None, False), (None, False)),
    ("关断过程", "Tf"): ((None, False), (None, False)),
    ("关断过程", "dv/dt"): (("vce", True), ("vce", True)),
    ("关断过程", "di/dt"): (("ic", True), ("ic", True)),
    ("关断过程", "Eoff"): (("vce", True), ("ic", True)),
    ("关断过程", "ΔVce"): (("vce", True), ("vce", True)),
    ("关断过程", "Ic_off_max"): (("ic", True), ("ic", True)),
    ("关断过程", "Vce_off_max"): (("vce", True), ("vce", True)),
    ("关断过程", "串扰电压"): (
        ("vge_other", True),
        ("vge_other", True),
    ),
    ("开通", "dv/dt"): (("vce", True), ("vce", True)),
    ("开通", "di/dt"): (("ic", True), ("ic", True)),
    ("开通", "Eon"): (("ic", True), ("vce", True)),
    ("开通", "ΔVce"): (("vce", True), ("vce", True)),
    ("开通", "开通电流"): (("ic", True), ("ic", True)),
    ("开通", "Ic_on_max"): (("ic", True), ("ic", True)),
    ("开通", "Vce_on_max"): (("vce", True), ("vce", True)),
    ("开通", "串扰电压"): (("vge_other", True), ("vge_other", True)),
    ("开通", "Ls_on"): ((None, False), (None, False)),
    ("开通", "Ton"): ((None, False), (None, False)),
    ("开通", "Td_on"): ((None, False), (None, False)),
    ("开通", "Tr"): ((None, False), (None, False)),
    ("反向恢复", "Irr"): (("irr", True), ("irr", True)),
    ("反向恢复", "Trr"): (("irr", True), ("irr", True)),
    ("反向恢复", "Vrr"): (("v_diode", True), ("v_diode", True)),
    ("反向恢复", "dv/dt"): (("v_diode", True), ("v_diode", True)),
    ("反向恢复", "di/dt"): (("irr", True), ("irr", True)),
    ("反向恢复", "Err"): (("irr", True), ("v_diode", True)),
}

SHORT_CIRCUIT_PARAMS = (
    "短路电流Imax",
    "短路时间Tsc",
    "短路能量Esc_本管",
    "应力Vpeak_本管",
    "短路能量Esc_对管",
    "应力Vpeak_对管",
    "Desat动作时间",
)

SHORT_CIRCUIT_REQUIRED_PARAMS = frozenset(
    {
        "短路电流Imax",
        "短路时间Tsc",
        "短路能量Esc_本管",
    }
)

# These double-pulse cards are defined by raw intersections on mandatory Vge/
# logical-Ic sources.  A corpus sample that cannot produce them is a regression
# to investigate, not an optional-channel INFO row.
DPT_REQUIRED_INTERSECTION_PARAMS = frozenset(
    {
        ("开通", "di/dt"),
        ("开通", "Ls_on"),
        ("开通", "Ton"),
        ("开通", "Td_on"),
        ("开通", "Tr"),
        ("反向恢复", "Trr"),
    }
)


def _short_unavailable_audit_status(name: str) -> str:
    return "FAIL" if name in SHORT_CIRCUIT_REQUIRED_PARAMS else "INFO"

SECTION_SEGMENT = {
    "关断过程": "turn_off",
    "开通": "turn_on",
    "反向恢复": "reverse_recovery",
}

DEFAULT_SAMPLE_FRAGMENTS = (
    ("KSU2577", "07CF2C1000 20260717", "SMC", "HT", "UH_750V_1048A_000.tss"),
    ("KSU2577", "07CF2C1000 20260506", "SMC", "RT", "UH_750V_1048A_000.tss"),
    ("KSU2577", "07CF2C1000 20260506", "SMC", "RT", "UL_750V_1048A_000.tss"),
    ("KSU2577", "07CF2C1000 20260506", "SMC", "RT", "WH_750V_1048A_000.tss"),
    ("KSU2577", "07CF2C1000 20260506", "SMC", "RT", "WL_750V_1048A_000.tss"),
    ("KSU2506", "GCU", "SMC", "LT", "UH_480V_500A_000.tss"),
    ("KSU2506", "GCU", "SMC", "LT", "UL_480V_500A_000.tss"),
    ("KSU2506", "DCU", "SMC", "LT", "WH_480V_800A_000.tss"),
    ("KSU2506", "DCU", "SMC", "LT", "WL_480V_800A_000.tss"),
    ("SSM1R7PB12B3DTFMMSPP25M4CF0016", "SSS", "HT", "UH_750V_1050A_000.tss"),
    ("SSM1R7PB12B3DTFMMSPP25M4CF0016", "SSS", "HT", "UL_750V_1050A_000.tss"),
    ("SSM1R7PB12B3DTFMMSPP25M4CF0016", "SSS", "LT", "WH-750V-1050A_000.tss"),
    ("SSM1R7PB12B3DTFMMSPP25M4CF0016", "SSS", "LT", "WL-750V-1050A_000.tss"),
    ("wanglihui", "U", "UH_486V_985A_Rgon2.88R_Rgoff6.21R_000.tss"),
    ("wanglihui", "U", "UH_486V_985A_Rgon1.515R_Rgoff6.346R_000.tss"),
)

_SHORT_CIRCUIT_DIR_TOKENS = {"DL", "DDD", "SHORT"}
_SHORT_CIRCUIT_FILENAME_RE = re.compile(
    r"(?:^|[_-])short(?:[_-]|$)|^[UVW][HL][_-]\d+(?:\.\d+)?V[_-]0{3}$",
    re.IGNORECASE,
)


def _is_short_circuit_sample(path: Path) -> bool:
    parts = {part.upper() for part in path.parts}
    if parts & _SHORT_CIRCUIT_DIR_TOKENS:
        return True
    return bool(_SHORT_CIRCUIT_FILENAME_RE.search(path.stem))


def _sample_trace_id(path: Path, root: Path = ROOT) -> str:
    """Return an unambiguous, human-readable sample path for audit output."""
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
        return str(resolved_path.relative_to(resolved_root))
    except (OSError, ValueError):
        try:
            return str(path.resolve())
        except OSError:
            return str(path)


def _group_rows_by_sample(rows: list[tuple]) -> dict[str, list[tuple]]:
    """Group rows by their traceable sample id, never by basename alone."""
    grouped: dict[str, list[tuple]] = {}
    for row in rows:
        grouped.setdefault(row[0], []).append(row)
    return grouped


class Capture:
    """捕获 MainWindow 调用 wave_plot.enable_* 时传入的光标放置参数。"""

    def __init__(self) -> None:
        self.calls: dict[str, dict] = {}

    def reset(self) -> None:
        self.calls = {}

    def install(self, wave_plot) -> None:
        import inspect

        cap = self

        def wrap(name, orig):
            try:
                sig = inspect.signature(orig)
            except (TypeError, ValueError):
                sig = None

            def inner(*args, **kwargs):
                bound: dict = {}
                if sig is not None:
                    try:
                        ba = sig.bind_partial(*args, **kwargs)
                        ba.apply_defaults()
                        bound = dict(ba.arguments)
                    except TypeError:
                        bound = {}
                cap.calls[name] = {"args": args, "kwargs": kwargs, "bound": bound}
                try:
                    return orig(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    cap.calls[name]["error"] = repr(exc)
                    return None

            return inner

        for meth in (
            "focus_parameter_window_us",
            "enable_dvdt_interaction",
            "apply_dvdt_ab_times",
            "enable_energy_loss_interaction",
            "enable_irr_peak_interaction",
            "set_interval_peak_on_hb",
            "set_irr_base_on_ha",
            "enable_trr_measure_interaction",
            "enable_turn_on_current_interaction",
            "enable_delta_vce_interaction",
            "enable_crosstalk_interaction",
            "enable_interval_interaction",
            "enable_short_current_interaction",
            "set_interval_peak_horizontal",
            "set_interval_base_horizontal",
            "set_interval_minmax_horizontal",
            "disable_interactive_cursors",
            "clear_parameter_cursor_context",
            "invalidate_dvdt_ab_times",
        ):
            orig = getattr(wave_plot, meth, None)
            if orig is None:
                continue
            setattr(wave_plot, meth, wrap(meth, orig))


def _capture_error_details(calls: dict[str, dict]) -> list[str]:
    """Return every exception swallowed by a capture wrapper.

    The wrapper intentionally keeps the audit process alive so one bad cursor
    does not hide the rest of the matrix.  Consequently, callers must promote
    every recorded exception to FAIL instead of trusting the method's fallback
    return value.
    """
    return [
        f"{name}: {call['error']}"
        for name, call in calls.items()
        if call.get("error")
    ]


def _captured_cursor_bindings(calls: dict[str, dict]) -> dict[str, object]:
    """Normalize captured API inputs into the real A/B/Ha/Hb card roles."""

    binding: dict[str, object] = {}
    if "apply_dvdt_ab_times" in calls:
        b = calls["apply_dvdt_ab_times"]["bound"]
        binding.update(a_us=b.get("t_a_us"), b_us=b.get("t_b_us"))
        slope = calls.get("enable_dvdt_interaction", {}).get("bound", {})
        channel = slope.get("channel")
        binding.update(a_channel=channel, b_channel=channel)
    elif "enable_short_current_interaction" in calls:
        b = calls["enable_short_current_interaction"]["bound"]
        channel = b.get("channel")
        binding.update(a_us=b.get("t_a_us"), b_us=b.get("t_b_us"))
        binding["ha"] = (b.get("ha"), channel)
        binding["hb"] = (b.get("hb"), channel)
    elif "enable_energy_loss_interaction" in calls:
        b = calls["enable_energy_loss_interaction"]["bound"]
        binding.update(
            a_us=b.get("t_a_us"),
            b_us=b.get("t_b_us"),
            a_channel=b.get("a_channel") or b.get("ha_channel"),
            b_channel=b.get("b_channel"),
        )
        binding["ha"] = (b.get("ha_v"), b.get("ha_channel"))
        binding["hb"] = (b.get("hb_a"), b.get("hb_channel"))
    elif "enable_irr_peak_interaction" in calls:
        b = calls["enable_irr_peak_interaction"]["bound"]
        binding.update(
            a_us=b.get("start_t_us"),
            b_us=b.get("end_t_us"),
            a_channel="irr",
            b_channel="irr",
        )
    elif "enable_trr_measure_interaction" in calls:
        b = calls["enable_trr_measure_interaction"]["bound"]
        binding.update(
            a_us=b.get("ta_us"),
            b_us=b.get("tb_us"),
            a_channel="irr",
            b_channel="irr",
        )
        binding["ha"] = (b.get("ha_a"), "irr")
        binding["hb"] = (b.get("hb_a"), "irr")
    elif "enable_turn_on_current_interaction" in calls:
        b = calls["enable_turn_on_current_interaction"]["bound"]
        binding.update(
            a_us=b.get("t_a_us"),
            b_us=b.get("t_b_us"),
            a_channel="ic",
            b_channel="ic",
        )
        binding["ha"] = (b.get("ha"), "ic")
        binding["hb"] = (b.get("hb"), "ic")
    elif "enable_delta_vce_interaction" in calls:
        b = calls["enable_delta_vce_interaction"]["bound"]
        binding.update(
            a_us=b.get("fixed_t_us"),
            b_us=b.get("move_t_us"),
            a_channel="vce",
            b_channel="vce",
        )
        binding["ha"] = (b.get("fixed_v"), "vce")
        binding["hb"] = (b.get("move_v"), "vce")
    elif "enable_crosstalk_interaction" in calls:
        b = calls["enable_crosstalk_interaction"]["bound"]
        binding.update(
            a_us=b.get("start_t_us"),
            b_us=b.get("end_t_us"),
            a_channel="vge_other",
            b_channel="vge_other",
        )
    elif "enable_interval_interaction" in calls:
        b = calls["enable_interval_interaction"]["bound"]
        shared_channel = b.get("channel")
        binding.update(
            a_us=b.get("start_t_us"),
            b_us=b.get("end_t_us"),
            a_channel=b.get("a_channel") or shared_channel,
            b_channel=b.get("b_channel") or shared_channel,
        )

    if "enable_dvdt_interaction" in calls:
        b = calls["enable_dvdt_interaction"]["bound"]
        channel = b.get("channel")
        binding["ha"] = (b.get("top_v"), channel)
        binding["hb"] = (b.get("base_v"), channel)
    if "set_interval_peak_horizontal" in calls:
        b = calls["set_interval_peak_horizontal"]["bound"]
        binding["ha"] = (b.get("y"), b.get("channel"))
    if "set_interval_base_horizontal" in calls:
        b = calls["set_interval_base_horizontal"]["bound"]
        binding["hb"] = (b.get("y"), b.get("channel"))
    if "set_interval_peak_on_hb" in calls:
        b = calls["set_interval_peak_on_hb"]["bound"]
        binding["hb"] = (b.get("y"), b.get("channel"))
    if "set_irr_base_on_ha" in calls:
        b = calls["set_irr_base_on_ha"]["bound"]
        binding["ha"] = (b.get("y"), b.get("channel"))
    if "set_interval_minmax_horizontal" in calls:
        b = calls["set_interval_minmax_horizontal"]["bound"]
        channel = b.get("channel")
        binding["ha"] = (b.get("y_max"), channel)
        binding["hb"] = (b.get("y_min"), channel)
    return binding


def _captured_parameter_focus(
    calls: dict[str, dict],
) -> tuple[float, tuple[float, ...], float, bool] | tuple[
    float, tuple[float, ...], float, bool, float | None
] | tuple[float, tuple[float, ...], float, bool, float | None, float | None] | None:
    """Read the actual focus call used by the UI, without re-deriving its anchor."""
    call = calls.get("focus_parameter_window_us")
    if call is None:
        return None
    bound = call.get("bound", {})
    if "anchor_us" not in bound:
        return None
    required = tuple(float(value) for value in bound.get("required_times_us", ()))
    captured = (
        float(bound["anchor_us"]),
        required,
        float(bound.get("anchor_fraction", PARAM_FOCUS_ANCHOR_FRACTION)),
        bool(bound.get("prefer_right_room", False)),
    )
    composition_anchor = bound.get("composition_anchor_us")
    composition_balance = bound.get("composition_balance_fraction")
    if composition_anchor is None and composition_balance is None:
        return captured
    return (
        *captured,
        None if composition_anchor is None else float(composition_anchor),
        None if composition_balance is None else float(composition_balance),
    )


def _normalize_captured_parameter_focus(
    captured_focus,
) -> tuple[float, tuple[float, ...], float, bool, float | None, float | None]:
    """Keep validator helpers compatible with pre-composition captures."""
    if len(captured_focus) == 4:
        return (*captured_focus, None, None)
    if len(captured_focus) == 5:
        return (*captured_focus, None)
    return captured_focus


def _captured_parameter_minimum_span_us(calls: dict[str, dict]) -> float | None:
    call = calls.get("focus_parameter_window_us")
    if call is None:
        return None
    value = call.get("bound", {}).get("minimum_span_us")
    if value is None or not np.isfinite(float(value)):
        return None
    return max(0.0, float(value))


def _crosstalk_cursor_display_problems(t, vge, indices, ta, tb) -> list[str]:
    """Independently check event membership, raw levels and minimum pair span."""
    i0, i1 = indices
    values = np.asarray(vge[i0:i1])
    if values.size < 2 or not np.all(np.isfinite(values)) or np.max(values) == np.min(values):
        return []  # No distinct finite extrema: the event-window fallback is valid.
    high = i0 + np.flatnonzero(values == np.max(values))
    low = i0 + np.flatnonzero(values == np.min(values))
    tol_us = 1e-8
    problems = []
    levels = []
    for label, time_us in (("A", ta), ("B", tb)):
        pos = int(np.searchsorted(t, time_us * 1e-6))
        candidates = range(max(0, pos - 1), min(len(t), pos + 1))
        idx = min(candidates, key=lambda k: abs(float(t[k] * 1e6) - time_us))
        if not i0 <= idx < i1 or abs(float(t[idx] * 1e6) - time_us) > tol_us:
            problems.append(f"串扰{label}未落在本事件原始采样时刻")
        levels.append(float(vge[idx]))
    if sorted(levels) != [float(np.min(values)), float(np.max(values))]:
        problems.append("串扰A/B未分别覆盖对管Vge的raw最大值/最小值")
    # Nearest-neighbor lookup in the other extrema set, intentionally not
    # the production helper's merged-adjacency selection algorithm.
    nearest = np.searchsorted(low, high)
    gap = min(
        float(np.min(np.abs(t[high] - t[low[np.clip(nearest, 0, len(low) - 1)]]))),
        float(np.min(np.abs(t[high] - t[low[np.clip(nearest - 1, 0, len(low) - 1)]]))),
    ) * 1e6
    if abs((tb - ta) - gap) > tol_us:
        problems.append("串扰A/B未选取包含同一raw最大/最小值的最近时刻对")
    return problems


def _audit_state_snapshot(value):
    """Freeze every dataclass field for NaN-safe mutation detection.

    ``ExtractResult`` intentionally excludes several measurement-context maps
    from dataclass equality.  Parameter navigation is display-only, so this
    audit must include those fields as well and must not treat unchanged NaN
    values as mutations.
    """

    if value is None or isinstance(value, (str, bytes, bool, int)):
        return value
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if np.isnan(number):
            return ("float", "nan")
        if np.isposinf(number):
            return ("float", "+inf")
        if np.isneginf(number):
            return ("float", "-inf")
        return ("float", number.hex())
    if isinstance(value, np.ndarray):
        contiguous = np.ascontiguousarray(value)
        return (
            "ndarray",
            contiguous.dtype.str,
            tuple(int(size) for size in contiguous.shape),
            contiguous.tobytes(),
        )
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value).__qualname__,
            tuple(
                (field.name, _audit_state_snapshot(getattr(value, field.name)))
                for field in fields(value)
            ),
        )
    if isinstance(value, dict):
        items = [
            (_audit_state_snapshot(key), _audit_state_snapshot(item))
            for key, item in value.items()
        ]
        return ("dict", tuple(sorted(items, key=repr)))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(_audit_state_snapshot(v) for v in value))
    if isinstance(value, (set, frozenset)):
        return (
            type(value).__name__,
            tuple(sorted((_audit_state_snapshot(v) for v in value), key=repr)),
        )
    return (type(value).__qualname__, repr(value))


def _independent_ic_off_max_stable_center_index(
    t: np.ndarray,
    ic: np.ndarray,
    dt: float,
    didt_context,
    signed_base: float,
    peak_idx: int,
) -> int | None:
    """Independently locate the first adjacent Ic Base representative point."""

    crossing_s = getattr(getattr(didt_context, "crossing", None), "t_pct_b_s", None)
    base_window = getattr(didt_context, "base_window", None)
    if crossing_s is None or base_window is None or not np.isfinite(crossing_s):
        return None
    n = min(len(t), len(ic))
    if n < 2:
        return None
    b0 = max(0, min(int(base_window[0]), n - 1))
    b1 = max(b0, min(int(base_window[1]), n - 1))
    search_window = getattr(didt_context, "search_window", None)
    search_end = b1
    if search_window is not None:
        search_end = max(search_end, min(int(search_window[1]), n - 1))
    reference = np.asarray(ic[b0 : b1 + 1], dtype=np.float64)
    if len(reference) < 8 or not np.isfinite(reference).any():
        return None
    p05, p95 = (
        float(np.nanpercentile(reference, percentile))
        for percentile in (5.0, 95.0)
    )
    reference_spread = max(0.0, p95 - p05)
    top_a = float(getattr(didt_context, "top_a", signed_base))
    peak = max(0, min(int(peak_idx), n - 1))
    event_span = max(
        abs(top_a - float(signed_base)),
        abs(float(ic[peak]) - float(signed_base)),
        1.0,
    )
    width_limit = max(1e-12, 1.35 * reference_spread, 0.075 * event_span)
    level_limit = max(1e-12, 0.50 * reference_spread, 0.040 * event_span)
    drift_limit = max(1e-12, reference_spread, 0.050 * event_span)

    dt_s = max(float(dt), 1e-15)
    stable_n = max(16, int(round(200e-9 / dt_s)))
    guard_n = max(8, int(round(100e-9 / dt_s)))
    edge_idx = int(np.searchsorted(t[:n], float(crossing_s), side="left"))
    lo = min(n - 1, max(0, edge_idx) + guard_n)
    if search_end - lo + 1 < stable_n:
        return None
    final_start = search_end - stable_n + 1
    step = max(1, stable_n // 16)
    starts = list(range(lo, final_start + 1, step))
    if not starts or starts[-1] != final_start:
        starts.append(final_start)
    for start in starts:
        block = np.asarray(ic[start : start + stable_n], dtype=np.float64)
        finite = block[np.isfinite(block)]
        if len(finite) < max(8, stable_n // 2):
            continue
        q05, q95 = (
            float(np.nanpercentile(finite, percentile))
            for percentile in (5.0, 95.0)
        )
        half = max(1, len(finite) // 2)
        half_drift = abs(
            float(np.nanmedian(finite[:half]))
            - float(np.nanmedian(finite[half:]))
        )
        if (
            q95 - q05 <= width_limit
            and float(np.nanstd(finite)) <= 0.50 * width_limit
            and abs(0.5 * (q05 + q95) - float(signed_base)) <= level_limit
            and half_drift <= drift_limit
        ):
            return int(start + stable_n // 2)
    return None


def _parameter_focus_geometry_problem(
    view_range_us: tuple[float, float],
    full_range_us: tuple[float, float],
    captured_focus: tuple[
        float, tuple[float, ...], float, bool, float | None, float | None
    ] | None,
    *,
    tolerance_us: float = 0.025,
    minimum_span_us: float | None = None,
    parameter_key: tuple[str, str] | None = None,
) -> str | None:
    """Verify the real view against the same bounded focus policy used by UI.

    The requested anchor fraction and spare post-event area are preferred
    composition only. Stable-platform/real-cursor visibility may move the
    anchor within the same 200 ns/div window; expansion is valid only when the
    real required-time envelope itself no longer fits. Re-solving the policy is
    therefore stricter and more accurate than requiring a fixed blank ratio.
    """
    if captured_focus is None:
        return None
    (
        anchor_us,
        required_times_us,
        anchor_fraction,
        prefer_right_room,
        composition_anchor_us,
        composition_balance_fraction,
    ) = _normalize_captured_parameter_focus(captured_focus)
    numeric_values = (
        *view_range_us,
        *full_range_us,
        anchor_us,
        anchor_fraction,
        *required_times_us,
    )
    if not all(np.isfinite(float(value)) for value in numeric_values):
        return "参数 focus 包含 NaN/Inf 几何值"
    if not float(view_range_us[1]) > float(view_range_us[0]):
        return "参数 focus 视窗跨度无效"
    if not float(full_range_us[1]) > float(full_range_us[0]):
        return "参数 focus 完整范围无效"
    expected_x0, expected_x1 = _solve_parameter_x_window(
        full_range_us,
        anchor_us,
        required_times_us,
        base_span_us=max(2.0, float(minimum_span_us or 0.0)),
        anchor_fraction=anchor_fraction,
        prefer_right_room=prefer_right_room,
        composition_anchor_us=composition_anchor_us,
        composition_balance_fraction=composition_balance_fraction,
    )
    actual_x0, actual_x1 = map(float, view_range_us)
    tol = max(0.0, float(tolerance_us))
    if (
        abs(actual_x0 - expected_x0) > tol
        or abs(actual_x1 - expected_x1) > tol
    ):
        return (
            f"参数 focus 构图偏离策略: 实际[{actual_x0:.3f},{actual_x1:.3f}]us，"
            f"期望[{expected_x0:.3f},{expected_x1:.3f}]us"
        )

    # Independently audit the right-priority geometry instead of accepting a
    # self-consistent but wrong solver.  No fixed pre-event duration is used:
    # only the real required envelope and the selected span define the check.
    if prefer_right_room and required_times_us:
        required_lo = min(required_times_us)
        required_hi = max(required_times_us)
        span = actual_x1 - actual_x0
        full_x0, full_x1 = map(float, full_range_us)
        guard = PARAM_FOCUS_REQUIRED_GUARD_US
        numeric_tol = 1e-6
        if (
            required_lo - guard >= full_x0 - numeric_tol
            and actual_x0 > required_lo - guard + numeric_tol
        ):
            return (
                "参数 focus 裁掉左侧 required 保护距: "
                f"left={required_lo - actual_x0:.6f}us"
            )
        if (
            required_hi + guard <= full_x1 + numeric_tol
            and actual_x1 < required_hi + guard - numeric_tol
        ):
            return (
                "参数 focus 裁掉右侧 required 保护距: "
                f"right={actual_x1 - required_hi:.6f}us"
            )
        interior = actual_x0 > full_x0 + tol and actual_x1 < full_x1 - tol
        if interior:
            left_room = required_lo - actual_x0
            right_room = actual_x1 - required_hi
            if right_room + tol < left_room:
                return (
                    "参数 focus 右侧观察区未优先: "
                    f"左余量={left_room:.3f}us 右余量={right_room:.3f}us"
                )
            guarded_width = (
                required_hi
                - required_lo
                + 2.0 * PARAM_FOCUS_REQUIRED_GUARD_US
            )
            if (
                span > 0.0
                and guarded_width <= 0.5 * span + 1e-9
                and composition_anchor_us is None
                and (required_hi - actual_x0) / span
                > PARAM_FOCUS_RIGHT_PRIORITY_LATEST_FRACTION + tol / span
            ):
                return (
                    "参数 focus 可左置的物理阶段后端越过中线: "
                    f"position={(required_hi - actual_x0) / span:.3%}"
                )

    # Turn-on and reverse-recovery views use the measured Vge rising edge as
    # the proportional composition reference.  The solver still receives the
    # real A/B/stable-platform envelope as required content; this audit only
    # checks that the old midpoint/right-priority policies are not used again.
    if (
        composition_anchor_us is not None
        and parameter_key is not None
        and parameter_key[0] in {"开通", "反向恢复"}
    ):
        if not np.isclose(
            float(anchor_fraction),
            PARAM_FOCUS_ANCHOR_FRACTION,
            rtol=0.0,
            atol=1e-9,
        ):
            return (
                f"开通/反向恢复 Vge 辅助锚点比例={float(anchor_fraction):.3f}≠"
                f"{PARAM_FOCUS_ANCHOR_FRACTION:.3f}"
            )
        if not required_times_us:
            return "开通/反向恢复 focus 缺少真实必要时刻"
        if composition_anchor_us is not None:
            if not np.isfinite(float(composition_anchor_us)):
                return "开通/反向恢复 Vge 辅助锚点非有限"
            if not (
                actual_x0 - PARAM_FOCUS_REQUIRED_GUARD_US
                <= float(composition_anchor_us)
                <= actual_x1 + PARAM_FOCUS_REQUIRED_GUARD_US
            ):
                return "开通/反向恢复 Vge 辅助锚点未落在局部视窗内"
            return None
        span = actual_x1 - actual_x0
        full_x0, full_x1 = map(float, full_range_us)
        interior = actual_x0 > full_x0 + tol and actual_x1 < full_x1 - tol
        if interior and span > 0.0:
            required_lo = min(required_times_us)
            required_hi = max(required_times_us)
            guarded_lo = max(full_x0, required_lo - PARAM_FOCUS_REQUIRED_GUARD_US)
            guarded_hi = min(full_x1, required_hi + PARAM_FOCUS_REQUIRED_GUARD_US)
            ideal_x0 = float(anchor_us) - PARAM_FOCUS_ANCHOR_FRACTION * span
            preferred_fits = (
                ideal_x0 <= guarded_lo + 1e-9
                and ideal_x0 + span >= guarded_hi - 1e-9
            )
            anchor_position = (float(anchor_us) - actual_x0) / span
            if (
                preferred_fits
                and abs(anchor_position - PARAM_FOCUS_ANCHOR_FRACTION)
                > tol / span
            ):
                return (
                    "开通/反向恢复 Vge 辅助锚点未按比例落位: "
                    f"position={anchor_position:.3%}"
                )
        return None

    if parameter_key == ("开通", "开通电流"):
        if prefer_right_room:
            return "开通电流不应继续套用通用右优先构图"
        if not np.isclose(
            float(anchor_fraction),
            TURN_ON_CURRENT_FOCUS_MIDPOINT_FRACTION,
            rtol=0.0,
            atol=1e-9,
        ):
            return (
                f"开通电流中点目标={float(anchor_fraction):.3f}≠"
                f"{TURN_ON_CURRENT_FOCUS_MIDPOINT_FRACTION:.3f}"
            )
        if not required_times_us:
            return "开通电流 focus 缺少真实 A/B 时刻"
        span = actual_x1 - actual_x0
        full_x0, full_x1 = map(float, full_range_us)
        required_lo = min(required_times_us)
        required_hi = max(required_times_us)
        interior = actual_x0 > full_x0 + tol and actual_x1 < full_x1 - tol
        if interior and span > 0.0:
            midpoint_position = (float(anchor_us) - actual_x0) / span
            if (
                abs(midpoint_position - TURN_ON_CURRENT_FOCUS_MIDPOINT_FRACTION)
                > tol / span
            ):
                return (
                    f"开通电流中点位置={midpoint_position:.3%}偏离"
                    f"{TURN_ON_CURRENT_FOCUS_MIDPOINT_FRACTION:.1%}"
                )
            left_room = required_lo - actual_x0
            right_room = actual_x1 - required_hi
            if right_room + tol < left_room:
                return (
                    "开通电流右侧观察区不足: "
                    f"左余量={left_room:.3f}us 右余量={right_room:.3f}us"
                )

    if parameter_key in {("开通", "dv/dt"), ("开通", "di/dt")}:
        if prefer_right_room:
            return "开通斜率不应继续套用通用右优先构图"
        if not np.isclose(
            float(anchor_fraction),
            TURN_ON_SLOPE_FOCUS_MIDPOINT_FRACTION,
            rtol=0.0,
            atol=1e-9,
        ):
            return (
                f"开通斜率中点目标={float(anchor_fraction):.3f}≠"
                f"{TURN_ON_SLOPE_FOCUS_MIDPOINT_FRACTION:.3f}"
            )
        if not required_times_us:
            return "开通斜率 focus 缺少真实 A/B 时刻"
        if len(required_times_us) != 2:
            return "开通斜率 focus 必须只传入真实 A/B，不能混入搜索窗"
        span = actual_x1 - actual_x0
        full_x0, full_x1 = map(float, full_range_us)
        required_lo = min(required_times_us)
        required_hi = max(required_times_us)
        if not np.isclose(
            float(anchor_us),
            0.5 * (required_lo + required_hi),
            rtol=0.0,
            atol=1e-9,
        ):
            return "开通斜率 focus 锚点不是实际 A/B 中点"
        interior = actual_x0 > full_x0 + tol and actual_x1 < full_x1 - tol
        if interior and span > 0.0:
            ideal_x0 = float(anchor_us) - TURN_ON_SLOPE_FOCUS_MIDPOINT_FRACTION * span
            guarded_lo = max(full_x0, required_lo - PARAM_FOCUS_REQUIRED_GUARD_US)
            guarded_hi = min(full_x1, required_hi + PARAM_FOCUS_REQUIRED_GUARD_US)
            preferred_fits = (
                ideal_x0 <= guarded_lo + 1e-9
                and ideal_x0 + span >= guarded_hi - 1e-9
            )
            midpoint_position = (float(anchor_us) - actual_x0) / span
            if (
                preferred_fits
                and abs(midpoint_position - TURN_ON_SLOPE_FOCUS_MIDPOINT_FRACTION)
                > tol / span
            ):
                return (
                    f"开通斜率中点位置={midpoint_position:.3%}偏离"
                    f"{TURN_ON_SLOPE_FOCUS_MIDPOINT_FRACTION:.1%}"
                )
            left_room = required_lo - actual_x0
            right_room = actual_x1 - required_hi
            if right_room + tol < left_room:
                return (
                    "开通斜率右侧观察区不足: "
                    f"左余量={left_room:.3f}us 右余量={right_room:.3f}us"
                )

    if parameter_key == ("开通", "Ls_on"):
        if prefer_right_room:
            return "Ls_on 不应继续套用通用右优先构图"
        if not np.isclose(
            float(anchor_fraction),
            TURN_ON_LS_FOCUS_MIDPOINT_FRACTION,
            rtol=0.0,
            atol=1e-9,
        ):
            return (
                f"Ls_on 中点目标={float(anchor_fraction):.3f}≠"
                f"{TURN_ON_LS_FOCUS_MIDPOINT_FRACTION:.3f}"
            )
        if not required_times_us:
            return "Ls_on focus 缺少真实 A/B 积分时刻"
        if len(required_times_us) != 2:
            return "Ls_on focus 必须只传入真实 A/B，不能混入搜索窗"
        span = actual_x1 - actual_x0
        full_x0, full_x1 = map(float, full_range_us)
        required_lo = min(required_times_us)
        required_hi = max(required_times_us)
        if not np.isclose(
            float(anchor_us),
            0.5 * (required_lo + required_hi),
            rtol=0.0,
            atol=1e-9,
        ):
            return "Ls_on focus 锚点不是实际 A/B 积分窗中点"
        interior = actual_x0 > full_x0 + tol and actual_x1 < full_x1 - tol
        if interior and span > 0.0:
            ideal_x0 = float(anchor_us) - TURN_ON_LS_FOCUS_MIDPOINT_FRACTION * span
            guarded_lo = max(full_x0, required_lo - PARAM_FOCUS_REQUIRED_GUARD_US)
            guarded_hi = min(full_x1, required_hi + PARAM_FOCUS_REQUIRED_GUARD_US)
            preferred_fits = (
                ideal_x0 <= guarded_lo + 1e-9
                and ideal_x0 + span >= guarded_hi - 1e-9
            )
            midpoint_position = (float(anchor_us) - actual_x0) / span
            if (
                preferred_fits
                and abs(midpoint_position - TURN_ON_LS_FOCUS_MIDPOINT_FRACTION)
                > tol / span
            ):
                return (
                    f"Ls_on 中点位置={midpoint_position:.3%}偏离"
                    f"{TURN_ON_LS_FOCUS_MIDPOINT_FRACTION:.1%}"
                )
            left_room = required_lo - actual_x0
            right_room = actual_x1 - required_hi
            if right_room + tol < left_room:
                return (
                    "Ls_on 右侧稳定平台观察区不足: "
                    f"左余量={left_room:.3f}us 右余量={right_room:.3f}us"
                )

    if parameter_key == ("关断过程", "Tf"):
        if prefer_right_room:
            return "Tf 不应继续套用通用30/70余量构图"
        if not np.isclose(
            float(anchor_fraction),
            TF_FOCUS_MIDPOINT_FRACTION,
            rtol=0.0,
            atol=1e-9,
        ):
            return (
                f"Tf 中点目标={float(anchor_fraction):.3f}≠"
                f"{TF_FOCUS_MIDPOINT_FRACTION:.3f}"
            )
        if not required_times_us:
            return "Tf focus 缺少真实 A/B 时刻"
        span = actual_x1 - actual_x0
        full_x0, full_x1 = map(float, full_range_us)
        required_lo = min(required_times_us)
        required_hi = max(required_times_us)
        interior = actual_x0 > full_x0 + tol and actual_x1 < full_x1 - tol
        if interior and span > 0.0:
            midpoint_position = (float(anchor_us) - actual_x0) / span
            if abs(midpoint_position - TF_FOCUS_MIDPOINT_FRACTION) > tol / span:
                return (
                    f"Tf 中点位置={midpoint_position:.3%}偏离"
                    f"{TF_FOCUS_MIDPOINT_FRACTION:.1%}"
                )
            if (required_hi - actual_x0) / span > 0.50 + tol / span:
                return (
                    "Tf B 光标越过构图中线: "
                    f"position={(required_hi - actual_x0) / span:.3%}"
                )
            left_room = required_lo - actual_x0
            right_room = actual_x1 - required_hi
            if right_room + tol < left_room:
                return (
                    "Tf 右侧观察区不足: "
                    f"左余量={left_room:.3f}us 右余量={right_room:.3f}us"
                )
    if parameter_key == ("反向恢复", "Pdmax"):
        if prefer_right_room or not np.isclose(
            anchor_fraction, RR_POWER_FOCUS_MIDPOINT_FRACTION, rtol=0.0, atol=1e-9
        ):
            return "Pdmax 应使用稳定电流 A/B 中点的平衡构图"
        if len(required_times_us) != 2:
            return "Pdmax focus 缺少独立稳定电流 A/B"
        midpoint = 0.5 * (min(required_times_us) + max(required_times_us))
        if abs(anchor_us - midpoint) > tol:
            return "Pdmax focus 锚点偏离稳定平台区间中点"
        if actual_x1 - max(required_times_us) + tol < min(required_times_us) - actual_x0:
            return "Pdmax 右侧稳定平台观察余量不足"
    return None


def _parameter_primary_event_geometry_problem(
    view_range_us: tuple[float, float],
    full_range_us: tuple[float, float],
    captured_focus: tuple[
        float, tuple[float, ...], float, bool, float | None, float | None
    ] | None,
    primary_event_us: float | None,
    *,
    tolerance_us: float = 0.025,
) -> str | None:
    """Independently keep a declared peak/event in the left half when feasible.

    Peak markers are not inputs to the current focus solver.  Auditing them
    separately prevents a self-consistent A/B envelope from hiding a main
    overshoot that was accidentally left too far right.  Full-data bounds and
    every hard required point remain stronger constraints than composition.
    """

    if captured_focus is None:
        return None
    (
        anchor_us,
        required_times_us,
        _anchor_fraction,
        prefer_right_room,
        _composition_anchor_us,
        _composition_balance_fraction,
    ) = _normalize_captured_parameter_focus(captured_focus)
    if not prefer_right_room:
        return None

    numeric_ranges = (*view_range_us, *full_range_us)
    if not all(np.isfinite(float(value)) for value in numeric_ranges):
        return "参数主事件取景包含 NaN/Inf 范围"
    if primary_event_us is None or not np.isfinite(float(primary_event_us)):
        return "参数主事件时刻缺失或非有限"

    actual_x0, actual_x1 = map(float, view_range_us)
    full_x0, full_x1 = map(float, full_range_us)
    event_us = float(primary_event_us)
    span = actual_x1 - actual_x0
    tol = max(0.0, float(tolerance_us))
    if span <= 0.0:
        return "参数主事件取景跨度无效"
    if not full_x1 > full_x0:
        return "参数主事件完整范围无效"
    if event_us < actual_x0 - tol or event_us > actual_x1 + tol:
        return (
            f"参数主事件={event_us:.3f}us 不在视窗"
            f"[{actual_x0:.3f},{actual_x1:.3f}]us"
        )

    hard_times = [
        float(value)
        for value in (*required_times_us, anchor_us)
        if np.isfinite(float(value))
    ]
    if not hard_times:
        hard_times = [event_us]
    hard_times = [float(np.clip(value, full_x0, full_x1)) for value in hard_times]
    guarded_lo = max(full_x0, min(hard_times) - PARAM_FOCUS_REQUIRED_GUARD_US)
    guarded_hi = min(full_x1, max(hard_times) + PARAM_FOCUS_REQUIRED_GUARD_US)
    feasible_lo = max(full_x0, guarded_hi - span)
    feasible_hi = min(full_x1 - span, guarded_lo)
    event_left_half_lo = event_us - (
        PARAM_FOCUS_RIGHT_PRIORITY_LATEST_FRACTION * span
    )
    can_place_event_left = (
        max(feasible_lo, event_left_half_lo) <= feasible_hi + tol
    )
    event_position = (event_us - actual_x0) / span
    if (
        can_place_event_left
        and event_position
        > PARAM_FOCUS_RIGHT_PRIORITY_LATEST_FRACTION + tol / span
    ):
        return (
            "参数主事件在可左置时仍越过中线: "
            f"event={event_us:.3f}us position={event_position:.3%}"
        )
    return None


def _authoritative_primary_event_us(
    mw,
    section: str,
    name: str,
    t: np.ndarray,
    chan: dict[str, np.ndarray],
    result,
    cursor_a_us: float | None,
    cursor_b_us: float | None,
) -> float | None:
    """Derive the visible card's main event independently from its focus call."""

    if cursor_a_us is None or cursor_b_us is None or len(t) == 0:
        return None
    try:
        point = mw._default_extreme_peak_point(section, name)
    except Exception:
        point = None
    if point is not None:
        idx = max(0, min(int(point[0]), len(t) - 1))
        return float(t[idx] * 1e6)

    lo_us, hi_us = sorted((float(cursor_a_us), float(cursor_b_us)))
    i0 = max(0, min(int(np.searchsorted(t, lo_us * 1e-6, side="left")), len(t) - 1))
    i1 = max(i0, min(int(np.searchsorted(t, hi_us * 1e-6, side="right")) - 1, len(t) - 1))

    def _peak_time(values: np.ndarray, *, use_abs: bool = True) -> float | None:
        block = np.asarray(values[i0 : i1 + 1], dtype=np.float64)
        if len(block) == 0 or not np.isfinite(block).any():
            return None
        ranked = np.abs(block) if use_abs else block
        ranked = np.where(np.isfinite(ranked), ranked, -np.inf)
        idx = i0 + int(np.argmax(ranked))
        return float(t[idx] * 1e6)

    if name in {"Pmax", "Eoff", "Eon"}:
        return _peak_time(np.asarray(chan["vce"]) * np.asarray(chan["ic"]))
    if name in {"Pdmax", "Err"}:
        return _peak_time(
            np.asarray(chan["v_diode"]) * np.asarray(chan["irr"])
        )
    if name in {"Irr", "Trr"}:
        from dpt_extractor.metrics.irr_measure import irr_parameter_peak_index

        segs = result.segments
        rr0, rr1 = segs.reverse_recovery
        peak_idx = int(
            irr_parameter_peak_index(
                np.asarray(chan["irr"], dtype=np.float64),
                rr0,
                rr1,
                segs.pulse2_on,
                segs.turn_on[0],
                segs.turn_on[1],
            )
        )
        peak_idx = max(0, min(peak_idx, len(t) - 1))
        return float(t[peak_idx] * 1e6)
    if name == "串扰电压" and "vge_other" in chan:
        return _peak_time(np.asarray(chan["vge_other"]))
    if name == "ΔVce" and section == "关断过程":
        return _peak_time(np.asarray(chan["vce"]), use_abs=False)
    if name == "ΔVce" and section == "开通":
        block = np.asarray(chan["vce"][i0 : i1 + 1], dtype=np.float64)
        if len(block) >= 2 and np.isfinite(block).any():
            edge = np.abs(np.diff(block, prepend=block[0]))
            edge = np.where(np.isfinite(edge), edge, -np.inf)
            return float(t[i0 + int(np.argmax(edge))] * 1e6)

    # Slopes, Ls and non-gate time ranges use the real physical A/B stage;
    # its temporal midpoint is independent of the focus solver and is the
    # appropriate event representative when no unique peak is declared.
    return 0.5 * (lo_us + hi_us)


_COMPACT_AB_FOCUS_PARAMS = {
    ("关断过程", "dv/dt"),
    ("关断过程", "di/dt"),
    ("关断过程", "Eoff"),
    ("开通", "dv/dt"),
    ("开通", "di/dt"),
    ("开通", "Eon"),
}


def _unnecessary_ab_focus_expansion(
    section: str,
    name: str,
    view_range_us: tuple[float, float],
    full_range_us: tuple[float, float],
    captured_focus: tuple[
        float, tuple[float, ...], float, bool, float | None, float | None
    ] | None,
    cursor_a_us: float | None,
    cursor_b_us: float | None,
    *,
    tolerance_us: float = 0.02,
) -> str | None:
    """Flag default views widened by search bounds when actual A/B already fit.

    The UI is allowed to expand the 2 us baseline for physical A/B visibility or
    full-waveform boundaries.  Search windows are calculation inputs, however,
    and must not make the report view wider after real cursor times are known.
    """
    if (section, name) not in _COMPACT_AB_FOCUS_PARAMS:
        return None
    if captured_focus is None or cursor_a_us is None or cursor_b_us is None:
        return None
    (
        anchor_us,
        _implementation_required,
        anchor_fraction,
        prefer_right_room,
        composition_anchor_us,
        composition_balance_fraction,
    ) = _normalize_captured_parameter_focus(captured_focus)
    expected_x0, expected_x1 = _solve_parameter_x_window(
        full_range_us,
        anchor_us,
        (float(cursor_a_us), float(cursor_b_us)),
        anchor_fraction=anchor_fraction,
        prefer_right_room=prefer_right_room,
        composition_anchor_us=composition_anchor_us,
        composition_balance_fraction=composition_balance_fraction,
    )
    actual_span = float(view_range_us[1]) - float(view_range_us[0])
    expected_span = expected_x1 - expected_x0
    if actual_span <= expected_span + max(0.0, float(tolerance_us)):
        return None
    return (
        f"局部视窗不必要放大: 实际{actual_span:.3f}us，"
        f"真实A/B仅需{expected_span:.3f}us"
    )


def _is_wanglihui_u_sample(path: Path) -> bool:
    parts = [part.casefold() for part in path.parts]
    if "wanglihui" not in parts:
        return False
    # The older batch is stored below wanglihui/U, while uploaded batches such
    # as wanglihui/20260729 group files by UH_*/UL_* acquisition folders.
    # File bridge codes are the stable U-phase discriminator across both
    # layouts; do not bind the audit setup to one historical directory name.
    stem = path.stem.casefold()
    legacy_u_dir = any(
        parts[index] == "wanglihui" and parts[index + 1] == "u"
        for index in range(len(parts) - 1)
    )
    return legacy_u_dir or stem.startswith(("uh_", "uh-", "ul_", "ul-"))


def _ensure_wanglihui_u_ch3_ui_inversion(mw, QApplication, path: Path) -> str:
    """Apply the wanglihui U-phase CH3 inversion through the UI state path.

    UH sources start with the display toggle off, so enabling it emits
    ``channelInversionChanged`` and MainWindow recalculates synchronously.  UL
    sources already carry CH3 source/display inversion metadata; toggling those
    again would double-flip the probe.  In that case keep the enabled UI state
    and explicitly recalculate once.
    """
    if not _is_wanglihui_u_sample(path) or mw.bundle is None:
        return ""

    source_before = set(mw.bundle.meta.source_channel_inversions)
    result_before = mw.result
    was_enabled = bool(mw.wave_plot.channel_inversion_enabled("CH3"))
    if was_enabled:
        # The source-inverted UL path is already checked in the UI.  Recompute
        # from that state without toggling it off/on (which would double-flip).
        mw._recalculate(reset_manual=False)
    else:
        # This is the real Channel Settings action.  Its signal updates bundle
        # display metadata and invokes MainWindow._recalculate.
        mw.wave_plot.set_channel_inversion_enabled("CH3", True)
    QApplication.processEvents()

    if set(mw.bundle.meta.source_channel_inversions) != source_before:
        raise AssertionError("CH3 UI 反相不应改写 source_channel_inversions")
    if not mw.wave_plot.channel_inversion_enabled("CH3"):
        raise AssertionError("CH3 UI 反相未保持启用")
    if "CH3" not in mw.bundle.meta.channel_display_inversions:
        raise AssertionError("CH3 display inversion 未写入波形状态")
    if mw.result is None or mw.result is result_before:
        raise AssertionError("CH3 display inversion 后 MainWindow 未完成重算")

    source_mode = "source已反相，未二次翻转" if "CH3" in source_before else "UI手动反相"
    return f"CH3反相=开启（{source_mode}，已重算）"


def _abs_range(arr: np.ndarray, i0: int, i1: int) -> tuple[float, float]:
    seg = np.abs(np.asarray(arr[i0 : i1 + 1], dtype=np.float64))
    if len(seg) == 0:
        return 0.0, 0.0
    return float(np.min(seg)), float(np.max(seg))


def _signed_range(arr: np.ndarray, i0: int, i1: int) -> tuple[float, float]:
    seg = np.asarray(arr[i0 : i1 + 1], dtype=np.float64)
    seg = seg[np.isfinite(seg)]
    if len(seg) == 0:
        return 0.0, 0.0
    return float(np.min(seg)), float(np.max(seg))


def _idx(t: np.ndarray, t_us: float) -> int:
    return int(np.searchsorted(t, t_us * 1e-6, side="left"))


def _in_window(t_us: float, t: np.ndarray, i0: int, i1: int, pad_us: float = 0.5) -> bool:
    lo = float(t[i0]) * 1e6 - pad_us
    hi = float(t[i1]) * 1e6 + pad_us
    return lo <= t_us <= hi


def _level_on_channel(level: float, arr: np.ndarray, i0: int, i1: int) -> bool:
    lo, hi = _signed_range(arr, i0, i1)
    tol = max(8.0, 0.08 * max(abs(lo), abs(hi)))
    return (lo - tol) <= float(level) <= (hi + tol)


def _cursor_level_binding_problem(
    label: str,
    t_us: float,
    level: float,
    t: np.ndarray,
    values: np.ndarray,
    *,
    floor: float,
    span_fraction: float = 0.0001,
) -> str | None:
    """Verify one horizontal level is attached to its waveform at A or B."""

    times = np.asarray(t, dtype=np.float64)
    signal = np.asarray(values, dtype=np.float64)
    cursor_s = float(t_us) * 1e-6
    if (
        len(times) < 2
        or len(signal) != len(times)
        or not np.isfinite(cursor_s)
        or not np.isfinite(level)
        or cursor_s < float(times[0])
        or cursor_s > float(times[-1])
    ):
        return f"{label}绑定输入非法"
    observed = float(np.interp(cursor_s, times, signal))
    finite = signal[np.isfinite(signal)]
    span = float(np.max(finite) - np.min(finite)) if len(finite) else 0.0
    tolerance = max(float(floor), float(span_fraction) * abs(span))
    if np.isfinite(observed) and abs(observed - float(level)) <= tolerance:
        return None
    return (
        f"{label}={float(level):.6g} 未贴波形@{float(t_us):.6f}us"
        f"（插值={observed:.6g},tol={tolerance:.6g}）"
    )


def _nearest_time_index(t: np.ndarray, t_us: float) -> int | None:
    """Return the raw sample nearest one visible microsecond cursor time."""

    times = np.asarray(t, dtype=np.float64)
    if len(times) == 0 or not np.isfinite(float(t_us)):
        return None
    target_s = float(t_us) * 1e-6
    pos = int(np.searchsorted(times, target_s, side="left"))
    if pos <= 0:
        return 0
    if pos >= len(times):
        return len(times) - 1
    before = pos - 1
    return int(
        before
        if abs(float(times[before]) - target_s)
        <= abs(float(times[pos]) - target_s)
        else pos
    )


def _visible_eoff_energy_mj(
    t: np.ndarray,
    vce: np.ndarray,
    ic: np.ndarray,
    a_us: float,
    b_us: float,
) -> float | None:
    """Independently integrate raw Vce*Ic from the visible GUI A/B window."""

    times = np.asarray(t, dtype=np.float64)
    voltage = np.asarray(vce, dtype=np.float64)
    current = np.asarray(ic, dtype=np.float64)
    n = min(len(times), len(voltage), len(current))
    if n < 3 or not (
        np.isfinite(float(a_us)) and np.isfinite(float(b_us))
    ):
        return None
    lo_s, hi_s = sorted((float(a_us) * 1e-6, float(b_us) * 1e-6))
    i0 = max(0, min(int(np.searchsorted(times[:n], lo_s, side="left")), n - 2))
    i1 = max(i0 + 1, min(int(np.searchsorted(times[:n], hi_s, side="left")), n - 1))
    if i1 <= i0 + 1:
        return 0.0
    seg_t = times[i0:i1]
    power = voltage[i0:i1] * current[i0:i1]
    finite = np.isfinite(seg_t) & np.isfinite(power)
    if int(np.count_nonzero(finite)) < 2:
        return None
    # Energy windows are contiguous raw samples.  Refuse interior non-finite
    # values rather than silently stitching separate pieces of a waveform.
    if not np.all(finite):
        return None
    dt_arr = np.diff(seg_t)
    p_mid = 0.5 * (power[:-1] + power[1:])
    return float(np.sum(p_mid * dt_arr)) * 1e3


def _energy_endpoint_mode(context) -> str:  # noqa: ANN001
    """Read the compatible endpoint mode; old snapshots remain crossings."""

    return str(getattr(context, "endpoint_mode", "level_crossings"))


def _eoff_stable_band_problem(
    label: str,
    values: np.ndarray,
    band_start: int,
    band_end: int,
    cursor_idx: int,
    target_level: float,
    event_span: float,
    *,
    width_fraction: float,
    level_fraction: float,
    drift_fraction: float,
) -> str | None:
    """Audit raw evidence inside a production-declared stable endpoint band."""

    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    lo = int(band_start)
    hi = int(band_end)
    idx = int(cursor_idx)
    if (
        n == 0
        or lo < 0
        or hi < lo
        or hi >= n
        or not lo <= idx <= hi
        or not np.isfinite(float(target_level))
    ):
        return f"{label}稳定带索引/代表点非法"
    band = arr[lo : hi + 1]
    finite = band[np.isfinite(band)]
    if len(finite) < 8:
        return f"{label}稳定带有效原始样本不足"
    p05, p95 = (
        float(np.nanpercentile(finite, percentile))
        for percentile in (5.0, 95.0)
    )
    center = 0.5 * (p05 + p95)
    half = max(1, len(finite) // 2)
    drift = (
        abs(
            float(np.nanmedian(finite[:half]))
            - float(np.nanmedian(finite[half:]))
        )
        if len(finite[half:])
        else 0.0
    )
    span = max(abs(float(event_span)), 1.0)
    width_limit = max(1.0, float(width_fraction) * span)
    level_limit = max(2.0, float(level_fraction) * span)
    drift_limit = max(0.75, float(drift_fraction) * span)
    if p95 - p05 > width_limit:
        return (
            f"{label}稳定带峰峰值过大: "
            f"p95-p05={p95 - p05:.6g}>{width_limit:.6g}"
        )
    if abs(center - float(target_level)) > level_limit:
        return (
            f"{label}稳定带中心偏离局部平台: "
            f"center={center:.6g}, level={float(target_level):.6g}"
        )
    if drift > drift_limit:
        return f"{label}稳定带前后漂移过大: {drift:.6g}>{drift_limit:.6g}"
    return None


def _eoff_stable_platform_audit_problems(
    t: np.ndarray,
    vce: np.ndarray,
    ic: np.ndarray,
    *,
    a_us: float,
    b_us: float,
    ha_v: float,
    hb_a: float,
    stored_eoff_mj: float,
    context,
) -> tuple[list[str], str]:  # noqa: ANN001
    """Audit smooth Eoff stable endpoints without imposing Ha/Hb crossings."""

    problems: list[str] = []
    times = np.asarray(t, dtype=np.float64)
    voltage = np.asarray(vce, dtype=np.float64)
    current = np.asarray(ic, dtype=np.float64)
    n = min(len(times), len(voltage), len(current))
    required_fields = (
        "a_idx",
        "b_idx",
        "a_band_start_idx",
        "a_band_end_idx",
        "b_band_start_idx",
        "b_band_end_idx",
        "v10_idx",
        "v90_idx",
        "i90_idx",
        "i10_idx",
        "search_end_idx",
    )
    if context is None or any(not hasattr(context, name) for name in required_fields):
        return ["Eoff stable_platforms 缺少稳定带证据上下文"], ""
    indices = {name: int(getattr(context, name)) for name in required_fields}
    if n < 3 or any(value < 0 or value >= n for value in indices.values()):
        return ["Eoff stable_platforms 稳定带证据索引越界"], ""

    a_idx = _nearest_time_index(times[:n], float(a_us))
    b_idx = _nearest_time_index(times[:n], float(b_us))
    if a_idx is None or b_idx is None:
        return ["Eoff stable_platforms 可见 A/B 时刻非法"], ""
    expected_a = indices["a_idx"]
    expected_b = indices["b_idx"]
    if abs(int(a_idx) - expected_a) > 1:
        problems.append(
            f"Eoff A={float(a_us):.9f}us≠Vce Base稳定带代表点"
            f"{float(times[expected_a]) * 1e6:.9f}us"
        )
    if abs(int(b_idx) - expected_b) > 1:
        problems.append(
            f"Eoff B={float(b_us):.9f}us≠Ic Base首个稳定带代表点"
            f"{float(times[expected_b]) * 1e6:.9f}us"
        )

    a0, a1 = indices["a_band_start_idx"], indices["a_band_end_idx"]
    b0, b1 = indices["b_band_start_idx"], indices["b_band_end_idx"]
    v10, v90 = indices["v10_idx"], indices["v90_idx"]
    i90, i10 = indices["i90_idx"], indices["i10_idx"]
    search_end = indices["search_end_idx"]
    if not (a0 <= expected_a <= a1 < v10 < v90):
        problems.append("Eoff A稳定带/主Vce上升沿时序非法")
    if not (v10 <= i90 < i10 <= b0 <= expected_b <= b1):
        problems.append("Eoff 主Ic下降沿/B首个稳定带时序非法")

    raw_dt = np.diff(times[:n])
    finite_dt = raw_dt[np.isfinite(raw_dt) & (raw_dt > 0.0)]
    if len(finite_dt) == 0:
        problems.append("Eoff stable_platforms 原始时间步长不可用")
    else:
        dt_s = float(np.nanmedian(finite_dt))
        expected_a_width = max(
            8,
            int(
                round(
                    float(
                        np.clip(
                            0.5 * float(times[v90] - times[v10]),
                            80e-9,
                            200e-9,
                        )
                    )
                    / dt_s
                )
            ),
        )
        expected_b_width = max(
            8,
            int(
                round(
                    float(
                        np.clip(
                            0.5 * float(times[i10] - times[i90]),
                            80e-9,
                            200e-9,
                        )
                    )
                    / dt_s
                )
            ),
        )
        if a1 - a0 + 1 != expected_a_width:
            problems.append(
                "Eoff A稳定带宽度未与Vce主沿自适应闭环: "
                f"actual={a1 - a0 + 1}, expected={expected_a_width}"
            )
        if b1 - b0 + 1 != expected_b_width:
            problems.append(
                "Eoff B稳定带宽度未与Ic主沿自适应闭环: "
                f"actual={b1 - b0 + 1}, expected={expected_b_width}"
            )
        trailing_confirmation = max(
            0,
            expected_b_width - 1 - expected_b_width // 2,
        )
        if not (
            expected_b <= search_end
            and b1 <= min(n - 1, search_end + trailing_confirmation)
        ):
            problems.append(
                "Eoff B代表点/稳定带越过事件门允许的半带确认范围"
            )

    v_event = voltage[a0 : b1 + 1]
    i_event = current[a0 : b1 + 1]
    v_finite = v_event[np.isfinite(v_event)]
    i_finite = i_event[np.isfinite(i_event)]
    v_span = (
        float(np.nanpercentile(v_finite, 95) - np.nanpercentile(v_finite, 5))
        if len(v_finite)
        else 1.0
    )
    i_span = (
        float(np.nanpercentile(i_finite, 95) - np.nanpercentile(i_finite, 5))
        if len(i_finite)
        else 1.0
    )
    for problem in (
        _eoff_stable_band_problem(
            "Eoff A/Vce Base",
            voltage,
            a0,
            a1,
            expected_a,
            float(ha_v),
            v_span,
            width_fraction=0.06,
            level_fraction=0.08,
            drift_fraction=0.08,
        ),
        _eoff_stable_band_problem(
            "Eoff B/Ic Base",
            current,
            b0,
            b1,
            expected_b,
            float(hb_a),
            i_span,
            width_fraction=0.16,
            level_fraction=0.16,
            drift_fraction=0.14,
        ),
    ):
        if problem is not None:
            problems.append(problem)

    peak_lo = max(0, min(v10, n - 1))
    peak_hi = max(peak_lo, min(b1, n - 1))
    event_power = voltage[peak_lo : peak_hi + 1] * current[peak_lo : peak_hi + 1]
    finite_power = np.isfinite(event_power)
    peak_idx: int | None = None
    if np.any(finite_power):
        ranked = np.where(finite_power, event_power, -np.inf)
        peak_idx = peak_lo + int(np.argmax(ranked))
        if not int(a_idx) <= peak_idx < int(b_idx):
            problems.append(
                "Eoff stable_platforms 可见 A/B 未包含原始 Vce*Ic 主功率峰"
            )
    else:
        problems.append("Eoff stable_platforms 主功率峰审计无有效样本")

    visible_energy = _visible_eoff_energy_mj(
        times[:n], voltage[:n], current[:n], float(a_us), float(b_us)
    )
    if visible_energy is None:
        problems.append("Eoff 可见 A/B 原始 Vce*Ic 独立积分不可用")
    elif not _short_values_close(
        float(stored_eoff_mj), float(visible_energy), floor=1e-9, rtol=2e-8
    ):
        problems.append(
            "Eoff 表值未与可见 A/B 原始 Vce*Ic 积分闭环: "
            f"stored={float(stored_eoff_mj):.12g}mJ, "
            f"visible={float(visible_energy):.12g}mJ"
        )
    peak_text = "missing" if peak_idx is None else f"{float(times[peak_idx]) * 1e6:.6f}us"
    energy_text = "missing" if visible_energy is None else f"{float(visible_energy):.9g}mJ"
    return problems, f"mode=stable_platforms peak={peak_text} visible_Eoff={energy_text}"


def _first_trr_stable_platform_crossings(
    t: np.ndarray,
    irr: np.ndarray,
    rr_start: int,
    peak_idx: int,
    fall_end_idx: int,
    stable_level: float,
) -> tuple[float, float] | None:
    """Independently find Trr's first raw crossings from the RR window start."""

    times = np.asarray(t, dtype=np.float64)
    values = np.asarray(irr, dtype=np.float64)
    n = min(len(times), len(values))
    if n < 3:
        return None
    start = max(0, min(int(rr_start), n - 2))
    peak = max(start + 1, min(int(peak_idx), n - 2))
    end = max(peak + 1, min(int(fall_end_idx), n - 1))
    level = float(stable_level)
    polarity = 1.0 if float(values[peak]) >= level else -1.0
    work = polarity * values[:n]
    work_level = polarity * level

    def _interp(j: int) -> float:
        y0, y1 = float(work[j]), float(work[j + 1])
        t0, t1 = float(times[j]), float(times[j + 1])
        if abs(y1 - y0) < 1e-15:
            return t0
        ratio = (work_level - y0) / (y1 - y0)
        return t0 + max(0.0, min(1.0, ratio)) * (t1 - t0)

    rise_idx = next(
        (
            j
            for j in range(start, peak)
            if (
                float(work[j]) <= work_level < float(work[j + 1])
                or (
                    (float(work[j]) - work_level)
                    * (float(work[j + 1]) - work_level)
                    <= 0.0
                    and float(work[j + 1]) > float(work[j])
                    and abs(float(work[j + 1]) - float(work[j])) > 1e-12
                )
            )
        ),
        None,
    )
    fall_idx = next(
        (
            j
            for j in range(peak, end)
            if (
                float(work[j]) >= float(work[j + 1])
                and float(work[j]) > work_level >= float(work[j + 1])
            )
        ),
        None,
    )
    if rise_idx is None or fall_idx is None:
        return None
    return _interp(rise_idx), _interp(fall_idx)


def _waveform_marker_binding_problems(
    wave_plot,
    role: str,
    channel: str,
    cursor,
    marker,
) -> list[str]:
    """Check one rendered marker against its semantic raw/derived waveform."""

    display_key = str(wave_plot._display_key_for_channel(str(channel)))
    source = f"{role}({display_key})"
    if cursor is None:
        return [f"{source}缺少真实光标"]
    if marker is None:
        return [f"{source}缺少 waveform marker"]

    trace_t_us = wave_plot._trace_t_us
    raw = wave_plot._cursor_value_raw(str(channel))
    if trace_t_us is None or raw is None:
        return [f"{source}缺少 raw/derived 取样源"]
    times = np.asarray(trace_t_us, dtype=np.float64)
    values = np.asarray(raw, dtype=np.float64)
    cursor_us = float(cursor.value())
    if (
        len(times) < 2
        or len(values) != len(times)
        or not np.isfinite(cursor_us)
        or cursor_us < float(times[0])
        or cursor_us > float(times[-1])
    ):
        return [f"{source}标记取样输入非法"]

    try:
        marker_x, marker_y = marker.getData()
        marker_x = np.asarray(marker_x, dtype=np.float64).reshape(-1)
        marker_y = np.asarray(marker_y, dtype=np.float64).reshape(-1)
    except Exception as exc:  # noqa: BLE001
        return [f"{source}标记数据不可读: {exc!r}"]
    if len(marker_x) != 1 or len(marker_y) != 1:
        return [f"{source}标记点数={len(marker_x)}/{len(marker_y)}≠1/1"]

    problems: list[str] = []
    if hasattr(marker, "isVisible") and not bool(marker.isVisible()):
        problems.append(f"{source}在 waveform 模式不可见")
    actual_x = float(marker_x[0])
    actual_y = float(marker_y[0])
    expected_raw = float(np.interp(cursor_us, times, values))
    expected_y = float(wave_plot._to_disp(str(channel), expected_raw))
    x_tol = max(1e-7, abs(cursor_us) * 1e-10)
    y_tol = max(1e-7, abs(expected_y) * 1e-8)
    if not np.isfinite(actual_x) or abs(actual_x - cursor_us) > x_tol:
        problems.append(
            f"{source}标记X={actual_x:.9g}≠光标{cursor_us:.9g}us"
        )
    if not np.isfinite(actual_y) or abs(actual_y - expected_y) > y_tol:
        problems.append(
            f"{source}标记Y={actual_y:.9g}≠语义波形取样"
            f"{expected_y:.9g}（raw={expected_raw:.9g}）"
        )
    return problems


def _audit_waveform_marker_bindings(
    wave_plot,
    endpoint_channels: tuple[str, str],
) -> list[str]:
    """Refresh real marker items in waveform mode, audit them, then restore."""

    previous_type = str(getattr(wave_plot, "_cursor_type", wave_plot.cursor_type()))
    problems: list[str] = []
    try:
        # Assign directly so the audit does not alter cursor-link state.  The
        # production marker refresh is still used, including LOGIC_IRR/IC.
        wave_plot._cursor_type = "waveform"
        wave_plot._update_waveform_cursor_markers()
        for role, channel, cursor_attr, marker_attr in (
            ("A", endpoint_channels[0], "_cursor_a", "_cursor_a_wave_marker"),
            ("B", endpoint_channels[1], "_cursor_b", "_cursor_b_wave_marker"),
        ):
            problems.extend(
                _waveform_marker_binding_problems(
                    wave_plot,
                    role,
                    str(channel),
                    getattr(wave_plot, cursor_attr, None),
                    getattr(wave_plot, marker_attr, None),
                )
            )
    except Exception as exc:  # noqa: BLE001
        problems.append(f"waveform marker 审计异常: {exc!r}")
    finally:
        wave_plot._cursor_type = previous_type
        try:
            wave_plot._update_waveform_cursor_markers()
            wave_plot._apply_cursor_visibility()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"waveform marker 恢复异常: {exc!r}")
    return problems


def _signed_cursor_text_problem(
    text: str,
    role: str,
    expected_value: float,
    *,
    source: str,
) -> str | None:
    """Require one rendered Ha/Hb number to retain the binding's sign."""

    plain = re.sub(r"<[^>]*>", " ", str(text))
    plain = plain.replace("&nbsp;", " ").replace("\xa0", " ")
    number = re.search(
        rf"(?<![A-Za-z]){re.escape(role)}\s*:?\s*"
        r"([+-]?\s*(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
        plain,
        flags=re.IGNORECASE,
    )
    if number is None:
        return f"{source}缺少{role}有符号数值"
    observed = float(number.group(1).replace(" ", ""))
    expected = float(expected_value)
    if not np.isfinite(expected) or not np.isfinite(observed):
        return f"{source}{role}符号检查输入非有限"
    if expected != 0.0 and bool(np.signbit(observed)) != bool(np.signbit(expected)):
        return (
            f"{source}{role}文本符号={observed:+.9g}"
            f"≠绑定值{expected:+.9g}"
        )
    return None


def _err_signed_cursor_text_problems(
    wave_plot,
    ha_irr: float,
    hb_vd: float,
) -> list[str]:
    """Audit Err signed Ha(Irr)/Hb(Vd) in top and beside-line readouts."""

    problems: list[str] = []
    try:
        wave_plot._update_readout()
    except Exception as exc:  # noqa: BLE001
        return [f"Err读数刷新异常: {exc!r}"]

    top_label = getattr(wave_plot, "_readout_label", None)
    top_text = top_label.text() if top_label is not None else ""
    top_plain = re.sub(r"<[^>]*>", " ", str(top_text)).replace("&nbsp;", " ")
    if re.search(r"\[Irr\]\s*Ha", top_plain, re.IGNORECASE) is None:
        problems.append("Err顶部读数缺少[Irr] Ha")
    if re.search(r"\[Vd\]\s*Hb", top_plain, re.IGNORECASE) is None:
        problems.append("Err顶部读数缺少[Vd] Hb")

    labels = (
        (
            "Ha",
            float(ha_irr),
            "Err顶部读数",
            top_text,
            getattr(wave_plot, "_cursor_ha_v_label", None),
        ),
        (
            "Hb",
            float(hb_vd),
            "Err顶部读数",
            top_text,
            getattr(wave_plot, "_cursor_hb_v_label", None),
        ),
    )
    for role, expected, top_source, rendered_top, side_label in labels:
        problem = _signed_cursor_text_problem(
            rendered_top,
            role,
            expected,
            source=top_source,
        )
        if problem is not None:
            problems.append(problem)
        if side_label is None or getattr(side_label, "textItem", None) is None:
            problems.append(f"Err横线旁读数缺少{role}")
            continue
        side_text = side_label.textItem.toPlainText()
        problem = _signed_cursor_text_problem(
            side_text,
            role,
            expected,
            source="Err横线旁读数",
        )
        if problem is not None:
            problems.append(problem)
    return problems


def _ab_role_binding_problems(
    actual_a_us: float,
    actual_b_us: float,
    expected: tuple[float, float] | None,
    *,
    role_text: str,
    tolerance_us: float = 1e-6,
) -> list[str]:
    """Compare a card's vertical cursors with its authoritative logical roles."""

    if expected is None:
        return [f"{role_text}: 权威A/B不可用"]
    exp_a, exp_b = map(float, expected)
    problems: list[str] = []
    if not np.isclose(float(actual_a_us), exp_a, rtol=0.0, atol=tolerance_us):
        problems.append(
            f"A={float(actual_a_us):.6f}us≠角色时刻{exp_a:.6f}us"
        )
    if not np.isclose(float(actual_b_us), exp_b, rtol=0.0, atol=tolerance_us):
        problems.append(
            f"B={float(actual_b_us):.6f}us≠角色时刻{exp_b:.6f}us"
        )
    return problems


def _slope_intersection_atol(
    t: np.ndarray,
    values: np.ndarray,
    t_cross_s: float,
    threshold: float,
) -> float:
    """Return a numerical-only tolerance for a raw slope intersection."""
    times = np.asarray(t, dtype=np.float64)
    signal = np.asarray(values, dtype=np.float64)
    if len(times) < 2 or len(signal) != len(times):
        return 1e-6

    k = int(np.searchsorted(times, float(t_cross_s), side="right")) - 1
    k = max(0, min(k, len(times) - 2))
    t0, t1 = float(times[k]), float(times[k + 1])
    y0, y1 = float(signal[k]), float(signal[k + 1])
    dt = abs(t1 - t0)
    slope_per_s = abs(y1 - y0) / dt if dt > 0.0 else 0.0
    time_ulp_s = max(
        abs(float(np.spacing(t0))),
        abs(float(np.spacing(t1))),
        abs(float(np.spacing(float(t_cross_s)))),
    )
    value_ulp = max(
        abs(float(np.spacing(y0))),
        abs(float(np.spacing(y1))),
        abs(float(np.spacing(float(threshold)))),
    )
    return max(1e-6, 64.0 * (value_ulp + slope_per_s * time_ulp_s))


def _audit_turn_off_slope_context_consistency(
    *,
    metric_name: str,
    gui_top: float,
    gui_base: float,
    gui_ab_us: tuple[float, float] | None,
    context_top: float,
    context_base: float,
    context_value: float,
    context_t_a_s: float | None,
    context_t_b_s: float | None,
    threshold_a: float,
    threshold_b: float,
    used_fallback: bool,
    result_value: float,
    t: np.ndarray,
    raw_values: np.ndarray,
    use_abs: bool,
) -> tuple[list[str], str]:
    """Audit one turn-off slope GUI call against its shared pure context.

    Top/Base, A/B and the published result are expected to be the exact values
    passed through from the common context.  The only tolerance in this audit
    is for evaluating the captured microsecond A/B back on the raw waveform,
    where a seconds -> microseconds -> seconds float round trip is unavoidable.
    """
    problems: list[str] = []

    def check_exact(label: str, actual: float, expected: float) -> None:
        actual_f = float(actual)
        expected_f = float(expected)
        if (
            not np.isfinite(actual_f)
            or not np.isfinite(expected_f)
            or actual_f != expected_f
        ):
            problems.append(
                f"{metric_name} {label}={actual_f!r} 与context={expected_f!r}不精确一致"
            )

    check_exact("Top", gui_top, context_top)
    check_exact("Base", gui_base, context_base)
    check_exact("result", result_value, context_value)

    has_a = context_t_a_s is not None
    has_b = context_t_b_s is not None
    if has_a and has_b:
        crossing_state = "full"
    elif has_a:
        crossing_state = "partial-A"
    elif has_b:
        crossing_state = "partial-B"
    else:
        crossing_state = "none"

    if not used_fallback and crossing_state != "full":
        problems.append(
            f"{metric_name} 未fallback但context交点状态={crossing_state}"
        )

    raw = np.asarray(raw_values, dtype=np.float64)
    if use_abs:
        raw = np.abs(raw)
    times = np.asarray(t, dtype=np.float64)
    raw_a: float | None = None
    raw_b: float | None = None

    if crossing_state == "full":
        assert context_t_a_s is not None
        assert context_t_b_s is not None
        if gui_ab_us is None:
            problems.append(f"{metric_name} context有完整A/B但GUI未调用apply_dvdt_ab_times")
        else:
            gui_a_us, gui_b_us = (float(gui_ab_us[0]), float(gui_ab_us[1]))
            expected_a_us = float(context_t_a_s) * 1e6
            expected_b_us = float(context_t_b_s) * 1e6
            check_exact("A", gui_a_us, expected_a_us)
            check_exact("B", gui_b_us, expected_b_us)

            if len(times) < 2 or len(raw) != len(times):
                problems.append(
                    f"{metric_name} 原始波形长度无效: len(t)={len(times)} len(y)={len(raw)}"
                )
            else:
                gui_a_s = gui_a_us * 1e-6
                gui_b_s = gui_b_us * 1e-6
                raw_a = float(np.interp(gui_a_s, times, raw))
                raw_b = float(np.interp(gui_b_s, times, raw))
                atol_a = _slope_intersection_atol(
                    times, raw, gui_a_s, float(threshold_a)
                )
                atol_b = _slope_intersection_atol(
                    times, raw, gui_b_s, float(threshold_b)
                )
                if abs(raw_a - float(threshold_a)) > atol_a:
                    problems.append(
                        f"{metric_name} 原始A插值={raw_a:.9g} 不等于阈值"
                        f"{float(threshold_a):.9g} (tol={atol_a:.3g})"
                    )
                if abs(raw_b - float(threshold_b)) > atol_b:
                    problems.append(
                        f"{metric_name} 原始B插值={raw_b:.9g} 不等于阈值"
                        f"{float(threshold_b):.9g} (tol={atol_b:.3g})"
                    )
    elif gui_ab_us is not None:
        problems.append(
            f"{metric_name} context交点状态={crossing_state}但GUI仍设置了完整A/B"
        )

    if gui_ab_us is None:
        ab_detail = "guiAB=none"
    else:
        ab_detail = f"guiAB={float(gui_ab_us[0]):.9f}/{float(gui_ab_us[1]):.9f}us"
    raw_detail = (
        "rawAB=none"
        if raw_a is None or raw_b is None
        else f"rawAB={raw_a:.9g}/{raw_b:.9g}"
    )
    detail = (
        f"contextTop={float(context_top):.9g} contextBase={float(context_base):.9g} "
        f"contextValue={float(context_value):.12g} result={float(result_value):.12g} "
        f"used_fallback={bool(used_fallback)} cross={crossing_state} {ab_detail} "
        f"thAB={float(threshold_a):.9g}/{float(threshold_b):.9g} {raw_detail}"
    )
    return problems, detail


ERR_A_INTERP_MIN_ATOL_A = 1e-6
ERR_A_INTERP_ULP_FACTOR = 32.0
ERR_A_NEAR_ZERO_PEAK_RATIO = 0.01
ERR_A_SETTLED_GATE_MARGIN_S = 2e-9


def _err_a_interpolation_atol(
    t: np.ndarray,
    irr: np.ndarray,
    t_a_s: float,
    ha_a: float,
) -> float:
    """Return a float/interpolation-only tolerance for signed Err A auditing."""
    times = np.asarray(t, dtype=np.float64)
    values = np.asarray(irr, dtype=np.float64)
    if len(times) < 2 or len(values) != len(times):
        return ERR_A_INTERP_MIN_ATOL_A

    k = int(np.searchsorted(times, float(t_a_s), side="right")) - 1
    k = max(0, min(k, len(times) - 2))
    t0, t1 = float(times[k]), float(times[k + 1])
    y0, y1 = float(values[k]), float(values[k + 1])
    dt = abs(t1 - t0)
    slope_a_per_s = abs(y1 - y0) / dt if dt > 0.0 else 0.0

    # A time is passed through seconds -> microseconds -> seconds before this
    # audit. Bound that round-trip and np.interp arithmetic by local ULPs, then
    # map the time error through the local segment slope. The 1 µA floor is only
    # a defensive allowance for float serialization; it is still far below any
    # waveform/amplitude tolerance and cannot hide a meaningful sign reversal.
    time_ulp_s = max(
        abs(float(np.spacing(t0))),
        abs(float(np.spacing(t1))),
        abs(float(np.spacing(float(t_a_s)))),
    )
    value_ulp_a = max(
        abs(float(np.spacing(y0))),
        abs(float(np.spacing(y1))),
        abs(float(np.spacing(float(ha_a)))),
    )
    numeric_atol_a = ERR_A_INTERP_ULP_FACTOR * (
        value_ulp_a + slope_a_per_s * time_ulp_s
    )
    return max(ERR_A_INTERP_MIN_ATOL_A, float(numeric_atol_a))


def _err_a_signed_intersection_check(
    ha_a: float,
    t_a_s: float,
    t: np.ndarray,
    irr: np.ndarray,
) -> tuple[bool, float, float]:
    """Check that Err A is the real signed Irr/Ha interpolation crossing."""
    irr_at_a = float(np.interp(float(t_a_s), t, irr))
    atol_a = _err_a_interpolation_atol(t, irr, t_a_s, ha_a)
    opposite_sign = (
        abs(float(ha_a)) > atol_a
        and abs(irr_at_a) > atol_a
        and np.signbit(float(ha_a)) != np.signbit(irr_at_a)
    )
    matches = not opposite_sign and abs(float(ha_a) - irr_at_a) <= atol_a
    return matches, irr_at_a, atol_a


def _err_a_requires_settled_gate(peak_a: float, ha_a: float) -> bool:
    """Mirror the production guard for a near-zero positive Err Ha."""
    peak = float(peak_a)
    ha = float(ha_a)
    return (
        peak > 0.0
        and ha > 0.0
        and ha < ERR_A_NEAR_ZERO_PEAK_RATIO * abs(peak)
    )


def _err_a_settled_gate_check(
    peak_a: float,
    ha_a: float,
    t_a_s: float,
    settled_start_s: float,
) -> bool:
    """Require near-zero positive-Ha A at/after the settled envelope gate."""
    if not _err_a_requires_settled_gate(peak_a, ha_a):
        return True
    return float(t_a_s) + ERR_A_SETTLED_GATE_MARGIN_S >= float(settled_start_s)


def _plot_x_range_us(wave_plot) -> tuple[float, float]:
    values = wave_plot.plot.getPlotItem().getViewBox().viewRange()[0]
    return float(values[0]), float(values[1])


def _short_window_indices(
    t: np.ndarray,
    t_a_us: float,
    t_b_us: float,
) -> tuple[int, int]:
    lo_s, hi_s = sorted((float(t_a_us) * 1e-6, float(t_b_us) * 1e-6))
    i0 = int(np.searchsorted(t, lo_s, side="left"))
    i1 = int(np.searchsorted(t, hi_s, side="left"))
    i0 = max(0, min(i0, len(t) - 1))
    i1 = max(i0, min(i1, len(t) - 1))
    return i0, i1


def _short_exact_vi_energy(
    t: np.ndarray,
    current: np.ndarray,
    voltage: np.ndarray,
    t_a_us: float,
    t_b_us: float,
) -> float:
    """Independently integrate V*I on the GUI's interpolated A/B endpoints."""

    time = np.asarray(t, dtype=np.float64)
    ic = np.asarray(current, dtype=np.float64)
    v = np.asarray(voltage, dtype=np.float64)
    lo_s, hi_s = sorted((float(t_a_us) * 1e-6, float(t_b_us) * 1e-6))
    if (
        len(time) < 2
        or len(ic) != len(time)
        or len(v) != len(time)
        or not np.isfinite(time).all()
        or np.any(np.diff(time) <= 0.0)
        or not np.isfinite(lo_s)
        or not np.isfinite(hi_s)
        or hi_s <= lo_s
        or lo_s < float(time[0])
        or hi_s > float(time[-1])
    ):
        return float("nan")
    inner = (time > lo_s) & (time < hi_s)
    exact_t = np.concatenate(([lo_s], time[inner], [hi_s]))
    exact_i = np.interp(exact_t, time, ic)
    exact_v = np.interp(exact_t, time, v)
    power = exact_i * exact_v
    if not np.isfinite(power).all():
        return float("nan")
    energy = float(np.trapezoid(power, exact_t))
    return max(0.0, energy) if np.isfinite(energy) else float("nan")


def _short_raw_level_tolerance(
    values: np.ndarray,
    gate_i0: int,
    dt: float,
    signal_span: float,
    *,
    floor: float,
) -> float:
    """Tolerance for raw-vs-smoothed crossing checks, derived from pre-event noise."""
    pre_len = max(10, int(round(0.8e-6 / max(float(dt), 1e-15))))
    p0 = max(0, int(gate_i0) - pre_len)
    p1 = max(p0 + 1, min(int(gate_i0), len(values)))
    pre = np.asarray(values[p0:p1], dtype=np.float64)
    pre = pre[np.isfinite(pre)]
    if len(pre):
        median = float(np.median(pre))
        mad = float(np.median(np.abs(pre - median)))
    else:
        mad = 0.0
    return max(float(floor), 0.01 * abs(float(signal_span)), 8.0 * 1.4826 * mad)


def _short_values_close(
    actual: float,
    expected: float,
    *,
    floor: float = 1e-9,
    rtol: float = 1e-8,
) -> bool:
    return bool(
        np.isfinite(actual)
        and np.isfinite(expected)
        and abs(float(actual) - float(expected))
        <= max(float(floor), float(rtol) * max(abs(float(expected)), 1.0))
    )


def audit_short_circuit_file(MainWindow, QApplication, app, path: Path) -> list[tuple]:
    """Exercise every real short-circuit result-row click and audit raw bindings."""
    _ = app
    sample_id = _sample_trace_id(path)
    mw = MainWindow()
    mode_index = mw.combo_test_mode.findData(TestMode.SHORT_CIRCUIT.value)
    if mode_index < 0:
        mw.close()
        return [
            (sample_id, "短路过程", "模式", "FAIL", "GUI缺少短路测试模式")
        ]
    # Use the same selector path as a person switching modes before opening a file.
    mw.combo_test_mode.setCurrentIndex(mode_index)
    mw._apply_test_mode_ui()
    mw._load_file(str(path), background=False)
    QApplication.processEvents()
    # QSettings may retain a user's custom Tsc range.  The corpus audit pins the
    # documented 0%-0% baseline without writing back to that user setting.
    mw.cfg.short_circuit_tsc_range = SHORT_CIRCUIT_TSC_RANGE_DEFAULT
    mw._recalculate(reset_manual=True)
    QApplication.processEvents()
    if (
        mw.bundle is None
        or mw.result is None
        or mw.result.segments is None
        or not mw.result.short_circuit_mode
    ):
        detail = (
            mw.statusBar().currentMessage()
            if mw.statusBar() is not None
            else "短路参数未计算"
        )
        mw.close()
        return [(sample_id, "短路过程", "加载", "FAIL", detail)]

    bundle = mw.bundle
    profile = mw.profile
    result = mw.result
    sc = result.short_circuit
    t = np.asarray(bundle.t, dtype=np.float64)
    ic = np.asarray(bundle_total_current(bundle, profile), dtype=np.float64)
    vce = np.asarray(bundle.get(profile.vce), dtype=np.float64)
    vge = np.asarray(bundle.get(profile.vge), dtype=np.float64)
    v_diode_raw = bundle.maybe_get(profile.v_diode)
    v_diode = (
        np.asarray(v_diode_raw, dtype=np.float64)
        if v_diode_raw is not None
        else None
    )
    gate_i0, gate_i1 = result.segments.turn_off
    gate_i0 = max(0, min(int(gate_i0), len(t) - 1))
    gate_i1 = max(gate_i0, min(int(gate_i1), len(t) - 1))
    cap = Capture()
    cap.install(mw.wave_plot)
    rows: list[tuple] = []
    short_vpeak_reference: tuple[float, float, float, str] | None = None

    def record(name: str, status: str, detail: str) -> None:
        rows.append((sample_id, "短路过程", name, status, detail))

    for name in SHORT_CIRCUIT_PARAMS:
        cap.reset()
        QApplication.processEvents()
        before_view = _plot_x_range_us(mw.wave_plot)
        unavailable = result.is_metric_unavailable("短路过程", name)
        try:
            mw._on_value_clicked("短路过程", name)
            QApplication.processEvents()
        except Exception as exc:  # noqa: BLE001
            record(name, "FAIL", f"真实参数点击异常: {exc!r}")
            continue
        after_view = _plot_x_range_us(mw.wave_plot)
        capture_errors = _capture_error_details(cap.calls)
        if capture_errors:
            record(name, "FAIL", "捕获到 GUI 调用异常: " + "; ".join(capture_errors))
            continue
        if unavailable:
            unexpected = [
                method
                for method in cap.calls
                if method.startswith("enable_")
                or method.startswith("set_interval_")
            ]
            if unexpected:
                record(name, "FAIL", "不可用参数仍启用交互=" + ",".join(unexpected))
            elif "clear_parameter_cursor_context" not in cap.calls:
                record(name, "FAIL", "不可用参数未清除旧 A/B/Ha/Hb")
            else:
                cursor_items = (
                    mw.wave_plot._cursor_a,
                    mw.wave_plot._cursor_b,
                    mw.wave_plot._h_cursor_a,
                    mw.wave_plot._h_cursor_b,
                    mw.wave_plot._cursor_a_wave_marker,
                    mw.wave_plot._cursor_b_wave_marker,
                )
                if any(item is not None and item.isVisible() for item in cursor_items):
                    record(name, "FAIL", "不可用参数仍显示上一参数光标/波形交点")
                    continue
                if mw.wave_plot._interactive_mode != "unavailable":
                    record(name, "FAIL", "不可用参数未进入无绑定光标状态")
                    continue
                status = _short_unavailable_audit_status(name)
                detail = (
                    "必需短路参数不可用，GUI已阻止交互"
                    if status == "FAIL"
                    else "缺少关联通道/数值，GUI已阻止交互"
                )
                record(name, status, detail)
            continue

        problems: list[str] = []
        expected_endpoint_channels: tuple[str | None, str | None] | None = None
        view_tol = max(1e-6, 1e-8 * max(abs(before_view[1] - before_view[0]), 1.0))
        if not np.allclose(before_view, after_view, rtol=0.0, atol=view_tol):
            problems.append(
                "短路参数点击不应改变时间视窗="
                f"[{before_view[0]:.6f},{before_view[1]:.6f}]→"
                f"[{after_view[0]:.6f},{after_view[1]:.6f}]us"
            )
        if "focus_parameter_window_us" in cap.calls:
            problems.append("短路参数错误触发局部放大")

        if name in {"短路电流Imax", "短路时间Tsc"}:
            call = cap.calls.get("enable_short_current_interaction")
            if call is None:
                record(name, "FAIL", "未触发 enable_short_current_interaction")
                continue
            bound = call["bound"]
            t_a_us = float(bound["t_a_us"])
            t_b_us = float(bound["t_b_us"])
            hb = float(bound["hb"])
            ha = float(bound["ha"])
            channel = str(bound["channel"])
            if channel != "ic":
                problems.append(f"交互通道={channel}≠ic")
            expected_current_cursors = (
                mw._short_circuit_tsc_cursors()
                if name == "短路时间Tsc"
                else mw._short_circuit_ic_default_cursors()
            )
            if expected_current_cursors is None:
                problems.append("短路 Ic 权威卡尺不可用")
            else:
                exp_a, exp_b, exp_hb, exp_ha = map(
                    float, expected_current_cursors
                )
                problems.extend(
                    _ab_role_binding_problems(
                        t_a_us,
                        t_b_us,
                        (exp_a, exp_b),
                        role_text=f"{name}: A/B=Ic电平交点",
                        tolerance_us=1e-7,
                    )
                )
                if not _short_values_close(hb, exp_hb, floor=1e-6):
                    problems.append(f"Hb={hb:.9g}≠Ic权威Base={exp_hb:.9g}A")
                if not _short_values_close(ha, exp_ha, floor=1e-6):
                    problems.append(f"Ha={ha:.9g}≠Ic权威峰值={exp_ha:.9g}A")
            signal_span = float(np.nanmax(ic) - np.nanmin(ic))
            raw_tol = _short_raw_level_tolerance(
                ic, gate_i0, bundle.dt, signal_span, floor=2.0
            )
            raw_a = float(np.interp(t_a_us * 1e-6, t, ic))
            raw_b = float(np.interp(t_b_us * 1e-6, t, ic))
            if abs(raw_a - hb) > raw_tol or abs(raw_b - hb) > raw_tol:
                problems.append(
                    f"A/B未贴Ic对应电平: raw={raw_a:.3f}/{raw_b:.3f},"
                    f"Hb={hb:.3f},tol={raw_tol:.3f}A"
                )
        else:
            call = cap.calls.get("enable_interval_interaction")
            if call is None:
                record(name, "FAIL", "未触发 enable_interval_interaction")
                continue
            bound = call["bound"]
            t_a_us = float(bound["start_t_us"])
            t_b_us = float(bound["end_t_us"])
            channel = str(bound["channel"])
            hb = float("nan")
            ha = float("nan")

        if (
            not np.isfinite(t_a_us)
            or not np.isfinite(t_b_us)
            or t_b_us <= t_a_us
        ):
            problems.append(f"A/B非法={t_a_us!r}/{t_b_us!r}us")
            i0, i1 = gate_i0, gate_i1
        else:
            if t_a_us < float(t[0] * 1e6) - 1e-6 or t_b_us > float(t[-1] * 1e6) + 1e-6:
                problems.append(
                    f"A/B越出原始时间轴={t_a_us:.6f}/{t_b_us:.6f}us"
                )
            i0, i1 = _short_window_indices(t, t_a_us, t_b_us)
        cursor_a = getattr(mw.wave_plot, "_cursor_a", None)
        cursor_b = getattr(mw.wave_plot, "_cursor_b", None)
        if cursor_a is None or cursor_b is None:
            problems.append("真实 GUI 未生成 A/B 光标")
        else:
            actual_a = float(cursor_a.value())
            actual_b = float(cursor_b.value())
            if not _short_values_close(actual_a, t_a_us, floor=1e-7):
                problems.append(f"GUI A/调用A={actual_a:.9f}/{t_a_us:.9f}us")
            if not _short_values_close(actual_b, t_b_us, floor=1e-7):
                problems.append(f"GUI B/调用B={actual_b:.9f}/{t_b_us:.9f}us")
        active_channel = str(getattr(mw.wave_plot, "_active_channel", ""))
        if active_channel != channel:
            problems.append(f"真实活动通道={active_channel}≠调用通道{channel}")

        stored_value: float | None
        if name == "短路电流Imax":
            stored_value = float(sc.ic_max)
            raw_max = float(np.nanmax(ic[i0 : i1 + 1]))
            signal_span = float(np.nanmax(ic[i0 : i1 + 1]) - np.nanmin(ic[i0 : i1 + 1]))
            raw_tol = _short_raw_level_tolerance(
                ic, gate_i0, bundle.dt, signal_span, floor=2.0
            )
            raw_a = float(np.interp(t_a_us * 1e-6, t, ic))
            raw_b = float(np.interp(t_b_us * 1e-6, t, ic))
            if abs(raw_a - hb) > raw_tol or abs(raw_b - hb) > raw_tol:
                problems.append(
                    f"A/B未贴近Ic稳定基线: raw={raw_a:.3f}/{raw_b:.3f},"
                    f"Hb={hb:.3f},tol={raw_tol:.3f}A"
                )
            if not _short_values_close(ha, raw_max, floor=1e-6):
                problems.append(f"Ha/原始Ic最大值={ha:.9g}/{raw_max:.9g}A")
            if not _short_values_close(stored_value, raw_max, floor=1e-6):
                problems.append(f"Imax/原始最大值={stored_value:.9g}/{raw_max:.9g}A")
            detail = (
                f"ch={channel} A={t_a_us:.6f} B={t_b_us:.6f}us "
                f"Hb={hb:.3f}A Ha/Imax={ha:.3f}/{stored_value:.3f}A"
            )
        elif name == "短路时间Tsc":
            stored_value = float(sc.tsc)
            duration_us = float(t_b_us - t_a_us)
            if not _short_values_close(stored_value, duration_us, floor=1e-7):
                problems.append(f"Tsc/B-A={stored_value:.9g}/{duration_us:.9g}us")
            if sc.tsc_start_us is None or sc.tsc_end_us is None:
                problems.append("结果缺少 Tsc 起止时刻")
            else:
                if not _short_values_close(float(sc.tsc_start_us), t_a_us, floor=1e-7):
                    problems.append("Tsc起点与GUI A不一致")
                if not _short_values_close(float(sc.tsc_end_us), t_b_us, floor=1e-7):
                    problems.append("Tsc终点与GUI B不一致")
            if sc.tsc_range != SHORT_CIRCUIT_TSC_RANGE_DEFAULT:
                problems.append(f"Tsc范围={sc.tsc_range}≠{SHORT_CIRCUIT_TSC_RANGE_DEFAULT}")
            detail = (
                f"ch={channel} A={t_a_us:.6f} B={t_b_us:.6f}us "
                f"Hb={hb:.3f}A Tsc={stored_value:.6f}us range={sc.tsc_range}"
            )
        elif name in {"短路能量Esc_本管", "短路能量Esc_对管"}:
            other = name.endswith("对管")
            expected_channel = "ic"
            if channel != expected_channel:
                problems.append(f"积分交互通道={channel}≠{expected_channel}")
            ic_reference = mw._short_circuit_ic_default_cursors()
            if ic_reference is None:
                problems.append("Esc 缺少 Ic-Base 权威积分窗口")
            else:
                ref_a, ref_b, ref_hb, _ref_ha = map(float, ic_reference)
                problems.extend(
                    _ab_role_binding_problems(
                        t_a_us,
                        t_b_us,
                        (ref_a, ref_b),
                        role_text="Esc A/B=Imax同一Ic-Base交点",
                        tolerance_us=1e-7,
                    )
                )
            voltage = v_diode if other else vce
            if voltage is None:
                problems.append("参数可用但缺少对应电压原始通道")
                raw_energy = float("nan")
            else:
                raw_energy = _short_exact_vi_energy(
                    t,
                    ic,
                    voltage,
                    t_a_us,
                    t_b_us,
                )
            stored_value = float(sc.esc_other if other else sc.esc_dut)
            if not _short_values_close(stored_value, raw_energy, floor=1e-9):
                problems.append(
                    f"Esc/原始V×I积分={stored_value:.12g}/{raw_energy:.12g}J"
                )
            base_call = cap.calls.get("set_interval_base_horizontal")
            if base_call is None or base_call["bound"].get("channel") != "ic":
                problems.append("Esc Hb未绑定Ic")
            elif ic_reference is not None:
                base_y = base_call["bound"].get("y")
                if base_y is None or not _short_values_close(
                    float(base_y), float(ic_reference[2]), floor=1e-6
                ):
                    problems.append(
                        f"Esc Hb={base_y!r}≠Ic Base={float(ic_reference[2]):.9g}A"
                    )
            source = sc.energy_other_channel if other else sc.energy_dut_channel
            peak_call = cap.calls.get("set_interval_peak_horizontal")
            if source and bundle.has_channel_reference(source):
                if peak_call is None:
                    problems.append(f"可见能量通道{source}缺少Ha")
                else:
                    peak_bound = peak_call["bound"]
                    if peak_bound.get("channel") != source:
                        problems.append(
                            f"Esc Ha通道={peak_bound.get('channel')}≠{source}"
                        )
                    raw_peak = float(np.nanmax(bundle.get(source)[i0 : i1 + 1]))
                    if not _short_values_close(
                        float(peak_bound["y"]), raw_peak, floor=1e-8
                    ):
                        problems.append("Esc Ha未贴能量通道原始峰值")
            detail = (
                f"ch={channel} A={t_a_us:.6f} B={t_b_us:.6f}us "
                f"source={source or 'V×I'} Esc={stored_value:.9g}J"
            )
        elif name in {"应力Vpeak_本管", "应力Vpeak_对管"}:
            other = name.endswith("对管")
            voltage = v_diode if other else vce
            expected_channel = "v_diode" if other else "vce"
            voltage_reference = profile.v_diode if other else profile.vce
            vpeak_context = mw._short_circuit_vpeak_default_context(
                voltage_reference,
                gate_channel=profile.vge,
            )
            if vpeak_context is None:
                problems.append("Vpeak 标为可用但 Vge/电流 A/B 卡尺均不可用")
                boundary_source = "vge"
                vpeak_cursors = None
            else:
                boundary_source = str(vpeak_context.boundary_source)
                expected_endpoint_channels = (boundary_source, boundary_source)
                vpeak_cursors = (
                    vpeak_context.t_a_s * 1e6,
                    vpeak_context.t_b_s * 1e6,
                    vpeak_context.hb_a,
                    vpeak_context.ha_a,
                )
                ref_a, ref_b, ref_hb, _ref_ha = map(float, vpeak_cursors)
                problems.extend(
                    _ab_role_binding_problems(
                        t_a_us,
                        t_b_us,
                        (ref_a, ref_b),
                        role_text=f"Vpeak A/B={boundary_source} Base交点",
                        tolerance_us=1e-7,
                    )
                )
                current_reference = (ref_a, ref_b, ref_hb, boundary_source)
                if short_vpeak_reference is None:
                    short_vpeak_reference = current_reference
                elif (
                    boundary_source != short_vpeak_reference[3]
                    or not all(
                        _short_values_close(actual, expected, floor=1e-7)
                        for actual, expected in zip(
                            current_reference[:3],
                            short_vpeak_reference[:3],
                            strict=True,
                        )
                    )
                ):
                    problems.append("本管/对管 Vpeak 未共用同一来源的 A/B/Hb")
            if channel != expected_channel:
                problems.append(f"Vpeak交互通道={channel}≠{expected_channel}")
            stored_value = float(sc.vpeak_other if other else sc.vpeak_dut)
            raw_peak = (
                float(np.nanmax(voltage[i0 : i1 + 1]))
                if voltage is not None
                else float("nan")
            )
            if not _short_values_close(stored_value, raw_peak, floor=1e-6):
                problems.append(f"Vpeak/原始最大值={stored_value:.9g}/{raw_peak:.9g}V")
            peak_call = cap.calls.get("set_interval_peak_horizontal")
            if peak_call is None:
                problems.append("Vpeak缺少Ha横光标")
            else:
                peak_bound = peak_call["bound"]
                if peak_bound.get("channel") != expected_channel:
                    problems.append(
                        f"Vpeak Ha通道={peak_bound.get('channel')}≠{expected_channel}"
                    )
                if not _short_values_close(
                    float(peak_bound["y"]), raw_peak, floor=1e-6
                ):
                    problems.append("Vpeak Ha未贴原始峰值")
            base_call = cap.calls.get("set_interval_base_horizontal")
            if (
                base_call is None
                or base_call["bound"].get("channel") != boundary_source
            ):
                problems.append(f"Vpeak Hb未绑定{boundary_source}")
            else:
                boundary_hb = float(base_call["bound"]["y"])
                if vpeak_cursors is not None and not _short_values_close(
                    boundary_hb, float(vpeak_cursors[2]), floor=1e-6
                ):
                    problems.append(f"Vpeak Hb未绑定权威 {boundary_source} Base")
                boundary_waveform = ic if boundary_source == "ic" else vge
                boundary_span = float(
                    np.nanmax(boundary_waveform[gate_i0 : gate_i1 + 1])
                    - np.nanmin(boundary_waveform[gate_i0 : gate_i1 + 1])
                )
                boundary_tol = _short_raw_level_tolerance(
                    boundary_waveform,
                    gate_i0,
                    bundle.dt,
                    boundary_span,
                    floor=0.15,
                )
                boundary_a = float(
                    np.interp(t_a_us * 1e-6, t, boundary_waveform)
                )
                boundary_b = float(
                    np.interp(t_b_us * 1e-6, t, boundary_waveform)
                )
                if (
                    abs(boundary_a - boundary_hb) > boundary_tol
                    or abs(boundary_b - boundary_hb) > boundary_tol
                ):
                    problems.append(
                        f"Vpeak A/B未贴近{boundary_source}稳定基线: "
                        f"raw={boundary_a:.3f}/{boundary_b:.3f},"
                        f"Hb={boundary_hb:.3f},tol={boundary_tol:.3f}"
                    )
            detail = (
                f"ch={channel} A={t_a_us:.6f} B={t_b_us:.6f}us "
                f"Vpeak={stored_value:.6g}V Hb_ch={boundary_source}"
            )
        else:  # Desat动作时间（仅有真实 Vdesat 通道/阈值时可达）
            desat_channel = mw._short_circuit_desat_channel()
            expected_endpoint_channels = ("vge", desat_channel)
            desat_cursors = mw._short_circuit_desat_default_cursors()
            stored_value = sc.desat_time
            if desat_channel is None or stored_value is None or desat_cursors is None:
                problems.append("Desat标为可用但缺少真实通道/数值")
                stored_float = float("nan")
            else:
                stored_float = float(stored_value)
                ref_a, ref_b, ref_hb, ref_ha = map(float, desat_cursors)
                problems.extend(
                    _ab_role_binding_problems(
                        t_a_us,
                        t_b_us,
                        (ref_a, ref_b),
                        role_text="Desat A=Vge Base交点；B=Vdesat阈值交点",
                        tolerance_us=1e-7,
                    )
                )
                if channel != desat_channel:
                    problems.append(f"Desat通道={channel}≠{desat_channel}")
                if not _short_values_close(
                    stored_float, t_b_us - t_a_us, floor=1e-7
                ):
                    problems.append("Desat数值不等于B-A")
                for method in (
                    "set_interval_peak_horizontal",
                    "set_interval_base_horizontal",
                ):
                    horizontal = cap.calls.get(method)
                    if horizontal is None or horizontal["bound"].get("channel") != desat_channel:
                        problems.append(f"{method}未绑定{desat_channel}")
                peak_call = cap.calls.get("set_interval_peak_horizontal")
                base_call = cap.calls.get("set_interval_base_horizontal")
                peak_y = peak_call["bound"].get("y") if peak_call else None
                base_y = base_call["bound"].get("y") if base_call else None
                if peak_y is None or not _short_values_close(
                    float(peak_y), ref_ha, floor=1e-9
                ):
                    problems.append("Desat Ha未绑定配置阈值")
                if base_y is None or not _short_values_close(
                    float(base_y), ref_hb, floor=1e-9
                ):
                    problems.append("Desat Hb未绑定配置阈值")
                desat_values = np.asarray(
                    bundle.get(desat_channel), dtype=np.float64
                )
                problem = _cursor_level_binding_problem(
                    "Desat B/Ha",
                    t_b_us,
                    ref_ha,
                    t,
                    desat_values,
                    floor=0.05,
                )
                if problem is not None:
                    problems.append(problem)
            detail = (
                f"ch={channel} A={t_a_us:.6f} B={t_b_us:.6f}us "
                f"Desat={stored_float:.6f}us"
            )

        live_binding = _captured_cursor_bindings(cap.calls)
        if expected_endpoint_channels is not None:
            expected_a_channel, expected_b_channel = expected_endpoint_channels
            captured_a_channel = live_binding.get("a_channel")
            captured_b_channel = live_binding.get("b_channel")
            if captured_a_channel != expected_a_channel:
                problems.append(
                    f"短路卡调用A端点={captured_a_channel}≠期望{expected_a_channel}"
                )
            if captured_b_channel != expected_b_channel:
                problems.append(
                    f"短路卡调用B端点={captured_b_channel}≠期望{expected_b_channel}"
                )
            actual_a_channel = mw.wave_plot._cursor_endpoint_channel("a")
            actual_b_channel = mw.wave_plot._cursor_endpoint_channel("b")
            if actual_a_channel != expected_a_channel:
                problems.append(
                    f"短路卡真实A端点={actual_a_channel}≠期望{expected_a_channel}"
                )
            if actual_b_channel != expected_b_channel:
                problems.append(
                    f"短路卡真实B端点={actual_b_channel}≠期望{expected_b_channel}"
                )
        for role, cursor_attr in (("ha", "_h_cursor_a"), ("hb", "_h_cursor_b")):
            expected_horizontal = live_binding.get(role)
            if expected_horizontal is None:
                continue
            expected_level, expected_channel = expected_horizontal
            horizontal = getattr(mw.wave_plot, cursor_attr, None)
            if expected_level is None or not expected_channel or horizontal is None:
                problems.append(f"短路卡真实 {role.upper()} 绑定缺失")
                continue
            actual_level = float(
                mw.wave_plot._from_disp(
                    str(expected_channel), float(horizontal.value())
                )
            )
            if not _short_values_close(
                # Imported Math traces may accumulate a few 1e-5 units in the
                # display-coordinate round trip.  This is still far below a
                # meaningful waveform/cursor mismatch.
                actual_level,
                float(expected_level),
                floor=1e-4,
            ):
                problems.append(
                    f"短路卡真实{role.upper()}({expected_channel})={actual_level:.9g}"
                    f"≠绑定{float(expected_level):.9g}"
                )

        if stored_value is None or not np.isfinite(float(stored_value)):
            problems.append(f"参数值非有限={stored_value!r}")
        elif name.startswith("短路能量"):
            if float(stored_value) < 0.0:
                problems.append(f"参数值为负={stored_value!r}")
        elif float(stored_value) <= 0.0:
            problems.append(f"参数值非正={stored_value!r}")
        record(name, "OK" if not problems else "FAIL", detail + (" | " + "; ".join(problems) if problems else ""))

    mw.close()
    return rows


def audit_file(MainWindow, QApplication, app, path: Path) -> list[tuple]:
    sample_id = _sample_trace_id(path)
    mw = MainWindow()
    focus_only = os.environ.get("DPT_VALIDATE_FOCUS_ONLY", "").lower() in {
        "1",
        "true",
        "yes",
    }
    validate_auto_slopes = os.environ.get(
        "DPT_VALIDATE_AUTO_SLOPES", ""
    ).lower() in {
        "1",
        "true",
        "yes",
    }
    mw._load_file(str(path))
    if validate_auto_slopes:
        # Loading a new waveform intentionally restores the application's
        # historical default ranges.  Inject the audit mode afterward and use
        # the production recalculation path so the GUI, result and report
        # labels all exercise the requested automatic range.
        mw._slope_ranges = {
            row_key: auto_max_slope_range(row_key)
            for row_key in SLOPE_ROW_KEYS.values()
        }
        mw.cfg.slope_ranges = dict(mw._slope_ranges)
        mw.result_table.set_slope_ranges(mw._slope_ranges)
        mw._recalculate(reset_manual=True)
    if mw.bundle is None or mw.result is None or mw.result.segments is None:
        detail = mw.statusBar().currentMessage() if mw.statusBar() is not None else "参数未计算"
        mw.close()
        return [(sample_id, "加载", "自动提取", "FAIL", detail)]
    try:
        inversion_note = _ensure_wanglihui_u_ch3_ui_inversion(
            mw, QApplication, path
        )
    except Exception as exc:  # noqa: BLE001
        mw.close()
        return [
            (
                sample_id,
                "通道设置",
                "CH3反相",
                "FAIL",
                f"真实 UI 反相/重算失败: {exc!r}",
            )
        ]
    bundle = mw.bundle
    profile = mw.profile
    result = mw.result
    if bundle is None or result is None or result.segments is None:
        detail = "通道状态更新后参数未计算"
        mw.close()
        return [(sample_id, "通道设置", "CH3反相", "FAIL", detail)]
    result_before_focus = _audit_state_snapshot(result) if focus_only else None
    t = bundle.t
    segs = result.segments
    chan = {
        "vge": bundle.get(profile.vge),
        "vce": bundle.get(profile.vce),
        "ic": bundle_total_current(bundle, profile),
        "irr": bundle_reverse_recovery_current(bundle, profile),
        "v_diode": bundle.get(profile.v_diode),
    }
    direct_cursor_ic = bundle.maybe_get(profile.ic)
    cursor_ic = np.asarray(
        direct_cursor_ic if direct_cursor_ic is not None else chan["ic"],
        dtype=np.float64,
    )
    if profile.vge_other:
        try:
            chan["vge_other"] = bundle.get(profile.vge_other)
        except KeyError:
            pass
    seg_idx = {
        "turn_off": segs.turn_off,
        "turn_on": segs.turn_on,
        "reverse_recovery": segs.reverse_recovery,
    }
    irr_ref = float(result.reverse_recovery.irr)

    if _is_wanglihui_u_sample(path):
        on0, on1 = segs.turn_on
        ic_on = np.asarray(chan["ic"][on0 : on1 + 1], dtype=np.float64)
        ic_p10, ic_p90 = np.percentile(ic_on, [10.0, 90.0])
        from dpt_extractor.metrics.irr_measure import irr_parameter_peak_index

        irr_peak_idx = int(
            irr_parameter_peak_index(
                np.asarray(chan["irr"], dtype=np.float64),
                segs.reverse_recovery[0],
                segs.reverse_recovery[1],
                segs.pulse2_on,
                segs.turn_on[0],
                segs.turn_on[1],
            )
        )
        signed_irr_peak = float(chan["irr"][irr_peak_idx])
        setup_problems: list[str] = []
        if not (ic_p90 > max(20.0, abs(float(ic_p10)))):
            setup_problems.append(
                f"Ic 导通趋势极性异常: P10={ic_p10:.1f}, P90={ic_p90:.1f}"
            )
        if not (signed_irr_peak > 0.0):
            setup_problems.append(
                f"Irr 尖峰应为正向: idx={irr_peak_idx}, y={signed_irr_peak:.1f}"
            )
        if irr_ref > 1.0 and not np.isclose(
            signed_irr_peak,
            irr_ref,
            rtol=0.15,
            atol=8.0,
        ):
            setup_problems.append(
                f"Irr 有符号尖峰={signed_irr_peak:.1f} 与结果={irr_ref:.1f}不符"
            )
        if setup_problems:
            mw.close()
            return [
                (
                    sample_id,
                    "通道设置",
                    "CH3反相",
                    "FAIL",
                    f"{inversion_note} | " + "; ".join(setup_problems),
                )
            ]

    cap = Capture()
    cap.install(mw.wave_plot)

    rows: list[tuple] = []

    def record(section, name, status, detail):
        rows.append((sample_id, section, name, status, detail))

    metric_filter_text = os.environ.get(
        "DPT_VALIDATE_CURSOR_METRIC", ""
    ).strip()
    metric_filters = {
        item.strip()
        for item in metric_filter_text.split("|")
        if item.strip()
    }
    for section, name in INTERACTIVE_PARAMS:
        if metric_filters and f"{section}/{name}" not in metric_filters:
            continue
        if result.single_pulse_mode and section in {"开通", "反向恢复"}:
            cap.reset()
            try:
                mw._on_value_clicked(section, name)
            except Exception as exc:  # noqa: BLE001
                record(section, name, "FAIL", f"单脉冲禁用路径异常: {exc!r}")
                continue
            forbidden = [
                method
                for method in cap.calls
                if method.startswith("enable_")
                or method.startswith("set_interval_")
                or method == "apply_dvdt_ab_times"
            ]
            single_problems: list[str] = []
            if "disable_interactive_cursors" not in cap.calls:
                single_problems.append("单脉冲不适用参数未清除旧 A/B/Ha/Hb")
            if forbidden:
                single_problems.append("单脉冲不适用参数仍启用交互=" + ",".join(forbidden))
            visible_mode_rows = [
                key
                for key in getattr(mw.result_table, "_row_meta", [])
                if key[0] in {"开通", "反向恢复"}
            ]
            if visible_mode_rows:
                single_problems.append(
                    "单脉冲结果表仍显示开通/反向恢复行="
                    + ",".join(f"{sec}/{metric}" for sec, metric in visible_mode_rows)
                )
            record(
                section,
                name,
                "FAIL" if single_problems else "INFO",
                "单脉冲模式不适用"
                + (" | " + "; ".join(single_problems) if single_problems else ""),
            )
            continue
        if result.is_metric_unavailable(section, name):
            cap.reset()
            try:
                mw._on_value_clicked(section, name)
                QApplication.processEvents()
            except Exception as exc:  # noqa: BLE001
                record(section, name, "FAIL", f"不可用参数禁用路径异常: {exc!r}")
                continue
            forbidden = [
                method
                for method in cap.calls
                if method.startswith("enable_")
                or method.startswith("set_interval_")
                or method == "apply_dvdt_ab_times"
            ]
            unavailable_problems: list[str] = []
            if forbidden:
                unavailable_problems.append(
                    "仍启用交互=" + ",".join(forbidden)
                )
            if "clear_parameter_cursor_context" not in cap.calls:
                unavailable_problems.append("未清除上一参数光标上下文")
            cursor_items = (
                mw.wave_plot._cursor_a,
                mw.wave_plot._cursor_b,
                mw.wave_plot._h_cursor_a,
                mw.wave_plot._h_cursor_b,
                mw.wave_plot._cursor_a_wave_marker,
                mw.wave_plot._cursor_b_wave_marker,
            )
            if any(item is not None and item.isVisible() for item in cursor_items):
                unavailable_problems.append("仍显示上一参数A/B/Ha/Hb或波形交点")
            if mw.wave_plot._interactive_mode != "unavailable":
                unavailable_problems.append(
                    f"mode={mw.wave_plot._interactive_mode!r}而非unavailable"
                )
            if mw.wave_plot._cursor_endpoint_channel("a") is not None:
                unavailable_problems.append("A仍绑定旧波形")
            if mw.wave_plot._cursor_endpoint_channel("b") is not None:
                unavailable_problems.append("B仍绑定旧波形")
            if mw.wave_plot._readout_label.text():
                unavailable_problems.append("顶部仍显示上一参数光标读数")
            required_failure = (section, name) in DPT_REQUIRED_INTERSECTION_PARAMS
            record(
                section,
                name,
                "FAIL" if unavailable_problems or required_failure else "INFO",
                "参数按原始交点完整性规则不可用"
                + (
                    " | " + "; ".join(unavailable_problems)
                    if unavailable_problems
                    else (
                        "，核心参数缺失真实交点（旧光标/绑定/读数已清空）"
                        if required_failure
                        else "，旧光标/绑定/读数已清空"
                    )
                ),
            )
            continue
        seg_name = SECTION_SEGMENT[section]
        s0, s1 = seg_idx[seg_name]
        cap.reset()
        recovery_peak_result_before_click = (
            _audit_state_snapshot(mw.result)
            if section == "反向恢复" and name in {"Irr", "Vrr"}
            else None
        )
        try:
            mw._on_value_clicked(section, name)
        except Exception as exc:  # noqa: BLE001
            record(section, name, "FAIL", f"异常: {exc!r}")
            continue
        calls = cap.calls
        capture_errors = _capture_error_details(calls)
        if capture_errors:
            record(
                section,
                name,
                "FAIL",
                "捕获到 GUI 调用异常: " + "; ".join(capture_errors),
            )
            continue
        problems: list[str] = []
        if recovery_peak_result_before_click is not None and (
            _audit_state_snapshot(mw.result) != recovery_peak_result_before_click
        ):
            problems.append(f"{name} 默认平台光标改变了提取结果或关联参数数值")
        turn_off_slope_crossing_full: bool | None = None
        parameter_key = (section, name)
        expected_endpoint_channels = DPT_ENDPOINT_CHANNELS.get(parameter_key)
        expected_horizontal_bindings = DPT_HORIZONTAL_BINDINGS.get(parameter_key)

        def check_channel(actual, expected, label):
            if actual != expected:
                problems.append(f"{label}通道={actual}≠期望{expected}")

        def check_time(t_us, label, seg=(s0, s1)):
            if not _in_window(t_us, t, seg[0], seg[1]):
                problems.append(
                    f"{label}={t_us:.3f}µs 不在段[{t[seg[0]]*1e6:.2f},{t[seg[1]]*1e6:.2f}]"
                )

        def check_level(level, ch, label, win_us=None):
            if ch not in chan:
                problems.append(f"{label}未知通道{ch}")
                return
            values = (
                cursor_ic
                if parameter_key
                in {
                    ("关断过程", "Ic_off_max"),
                    ("开通", "Ic_on_max"),
                }
                and ch == "ic"
                else chan[ch]
            )
            if win_us is not None:
                w0 = max(0, min(_idx(t, win_us[0]), len(t) - 1))
                w1 = max(w0 + 1, min(_idx(t, win_us[1]), len(t) - 1))
            else:
                w0, w1 = s0, s1
            if not _level_on_channel(level, values, w0, w1):
                lo, hi = _signed_range(values, w0, w1)
                problems.append(
                    f"{label}={level:.2f} 不在{ch}有符号范围[{lo:.1f},{hi:.1f}]"
                )

        def check_endpoint_waveform(role: str, channel: str, t_us: float) -> None:
            """Verify the bound identity also resolves to the authoritative samples."""

            raw = mw.wave_plot._cursor_value_raw(channel)
            trace_t_us = mw.wave_plot._trace_t_us
            if raw is None or trace_t_us is None or len(raw) != len(trace_t_us):
                problems.append(f"{role}通道{channel}缺少可取样的真实波形")
                return
            if channel not in chan:
                return
            actual_y = float(np.interp(float(t_us), trace_t_us, raw))
            authoritative = (
                cursor_ic
                if parameter_key
                in {
                    ("关断过程", "Ic_off_max"),
                    ("开通", "Ic_on_max"),
                }
                and channel == "ic"
                else np.asarray(chan[channel])
            )
            expected_y = float(
                np.interp(float(t_us) * 1e-6, t, authoritative)
            )
            tolerance = max(1e-7, abs(expected_y) * 1e-8)
            if abs(actual_y - expected_y) > tolerance:
                problems.append(
                    f"{role}通道名={channel}但底层取样={actual_y:.9g}"
                    f"≠权威波形{expected_y:.9g}"
                )

        if name in ("dv/dt", "di/dt"):
            if validate_auto_slopes:
                row_key = SLOPE_ROW_KEYS[(section, name)]
                selected_range = mw._slope_ranges.get(row_key)
                if selected_range is None or not selected_range.is_auto_max:
                    problems.append("GUI 自动斜率范围未保持 auto_max 模式")
                result_section = {
                    "关断过程": result.turn_off,
                    "开通": result.turn_on,
                    "反向恢复": result.reverse_recovery,
                }[section]
                range_label = (
                    result_section.dvdt_range
                    if name == "dv/dt"
                    else result_section.didt_range
                )
                if not _auto_slope_label_has_fixed_span(range_label):
                    problems.append(
                        "GUI 自动"
                        f"{AUTO_MAX_SLOPE_SPAN_PERCENT:g}%"
                        f"范围标签无效={range_label!r}"
                    )
            c = calls.get("enable_dvdt_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_dvdt_interaction")
                continue
            b = c["bound"]
            top_v, base_v, channel = b["top_v"], b["base_v"], b["channel"]
            win = (b["search_t0_us"], b["search_t1_us"])
            expected_ch = (
                ("v_diode" if section == "反向恢复" else "vce")
                if name == "dv/dt"
                else ("irr" if section == "反向恢复" else "ic")
            )
            check_channel(channel, expected_ch, "dvdt/didt")
            # ``win`` is the compact A/B crossing-search interval.  Stable
            # Top/Base bands are deliberately sampled before/after that edge
            # and may lie outside its raw value range on slow records.  The
            # metric-specific audits below compare Ha/Hb exactly with their
            # independently recomputed stable bands, while this common block
            # only rejects invalid numeric cursor levels.
            if not np.isfinite(float(top_v)):
                problems.append(f"Ha不是有限值: {top_v!r}")
            if not np.isfinite(float(base_v)):
                problems.append(f"Hb不是有限值: {base_v!r}")
            ab = calls.get("apply_dvdt_ab_times")
            ab_txt = ""
            gui_ab_us: tuple[float, float] | None = None
            if ab is None:
                problems.append("斜率参数未布置真实 A/B 交点")
            else:
                ta, tb = ab["bound"]["t_a_us"], ab["bound"]["t_b_us"]
                gui_ab_us = (float(ta), float(tb))
                slope_segment = (s0, s1)
                if section == "反向恢复":
                    completed = mw._rr_measurement_window_indices()
                    if completed is not None:
                        slope_segment = (completed[0], completed[1])
                check_time(ta, "A", slope_segment)
                check_time(tb, "B", slope_segment)
                ab_txt = f" A={ta:.3f} B={tb:.3f}"
            detail = f"ch={channel} Ha={top_v:.2f} Hb={base_v:.2f}{ab_txt}"
            if section == "关断过程":
                context = (
                    mw._turn_off_dvdt_context(*win)
                    if name == "dv/dt"
                    else mw._turn_off_didt_context(*win)
                )
                if context is None:
                    problems.append(f"{name} MainWindow共用context不可用")
                    detail += " | context=none used_fallback=unknown cross=unknown"
                else:
                    turn_off_slope_crossing_full = (
                        context.crossing.t_pct_a_s is not None
                        and context.crossing.t_pct_b_s is not None
                    )
                    if name == "dv/dt":
                        context_top = float(context.top_v)
                        context_base = float(context.base_v)
                        context_value = float(context.crossing.dvdt)
                        result_value = float(result.turn_off.dvdt)
                        use_abs = False
                    else:
                        context_top = float(context.top_a)
                        context_base = float(context.base_a)
                        context_value = float(context.crossing.didt)
                        result_value = float(result.turn_off.didt)
                        # 关断逻辑 Ic 已自动定向；Base/Hb 保持带符号，
                        # 因而 A/B 必须回插到同一条带符号原始 Ic。
                        use_abs = False
                    context_problems, context_detail = (
                        _audit_turn_off_slope_context_consistency(
                            metric_name=name,
                            gui_top=float(top_v),
                            gui_base=float(base_v),
                            gui_ab_us=gui_ab_us,
                            context_top=context_top,
                            context_base=context_base,
                            context_value=context_value,
                            context_t_a_s=context.crossing.t_pct_a_s,
                            context_t_b_s=context.crossing.t_pct_b_s,
                            threshold_a=float(context.crossing.th_a),
                            threshold_b=float(context.crossing.th_b),
                            used_fallback=bool(context.used_fallback),
                            result_value=result_value,
                            t=t,
                            raw_values=chan[channel],
                            use_abs=use_abs,
                        )
                    )
                    problems.extend(context_problems)
                    detail += " | " + context_detail
                    if name == "di/dt":
                        base_window = context.base_window
                        if base_window is None:
                            problems.append("关断 di/dt 未声明 Base 稳定平台来源窗")
                        else:
                            b0, b1 = (int(base_window[0]), int(base_window[1]))
                            if not (0 <= b0 <= b1 < len(t)):
                                problems.append(
                                    f"关断 di/dt Base窗越界: {base_window!r}"
                                )
                            else:
                                base_band = np.asarray(
                                    chan["ic"][b0 : b1 + 1], dtype=np.float64
                                )
                                independent_base = float(
                                    _plateau_mid_without_isolated_spikes(base_band)
                                )
                                if independent_base != float(context.base_a):
                                    problems.append(
                                        "关断 di/dt Hb未使用声明稳定带原始"
                                        "max/min中点: "
                                        f"{float(context.base_a):.12g}≠"
                                        f"{independent_base:.12g}"
                                    )
                                expected_n = max(
                                    16,
                                    int(round(200e-9 / max(float(bundle.dt), 1e-15))),
                                )
                                guard_n = max(
                                    8,
                                    int(round(100e-9 / max(float(bundle.dt), 1e-15))),
                                )
                                candidate_start = min(
                                    len(t) - 1, max(0, int(segs.pulse1_off) + 1)
                                )
                                candidate_end = min(
                                    len(t) - 1,
                                    int(segs.turn_off[1]) + 5 * expected_n,
                                )
                                next_on = segs.next_pulse_on
                                if next_on is not None and int(next_on) > candidate_start:
                                    candidate_end = min(
                                        candidate_end, int(next_on) - guard_n
                                    )
                                    if b1 >= int(next_on):
                                        problems.append(
                                            "关断 di/dt Base窗越过下一实际Vge上升沿"
                                        )
                                available = max(
                                    0, candidate_end - candidate_start + 1
                                )
                                if available >= expected_n and (b1 - b0 + 1) != expected_n:
                                    problems.append(
                                        "关断 di/dt Base稳定窗非约200ns完整带: "
                                        f"n={b1 - b0 + 1} expected={expected_n}"
                                    )
                                detail += (
                                    f" baseWin={float(t[b0]) * 1e6:.6f}/"
                                    f"{float(t[b1]) * 1e6:.6f}us"
                                    f" baseMid={independent_base:.9g}A"
                                )
            elif section == "反向恢复" and name == "di/dt":
                context = mw._rr_didt_context(*win)
                if context is None:
                    problems.append("di/dt MainWindow共用RR context不可用")
                    detail += " | context=none used_fallback=unknown cross=unknown"
                else:
                    mode_tag = mw._rr_didt_mode_tag(section)
                    stable_base_detail = ""
                    if mode_tag == "if_irm":
                        context_top = float(context.forward_a)
                        context_base = float(context.reverse_a)
                        zero_expected = context.zero_a
                        zero_bound = b.get("zero_v")
                        if zero_expected is None or zero_bound is None:
                            problems.append("RR di/dt IF-IRM 模式缺少 H0 零基准绑定")
                        elif not _short_values_close(
                            float(zero_bound), float(zero_expected), floor=1e-9
                        ):
                            problems.append("RR di/dt H0 未绑定权威零基准")
                        zero_line = getattr(mw.wave_plot, "_h_cursor_zero", None)
                        if zero_line is None or not zero_line.isVisible():
                            problems.append("RR di/dt IF-IRM 模式真实 H0 光标缺失")
                        elif zero_expected is not None:
                            zero_actual = float(
                                mw.wave_plot._from_disp(
                                    "irr", float(zero_line.value())
                                )
                            )
                            if not _short_values_close(
                                zero_actual, float(zero_expected), floor=1e-6
                            ):
                                problems.append("RR di/dt 真实 H0 未落在零基准")
                    else:
                        # IDM 水平卡尺语义：Ha=恢复尾部基线，Hb=正向平台。
                        context_top = float(context.base_a)
                        context_base = float(context.forward_a)
                        from dpt_extractor.metrics.slopes import (
                            _rr_quiet_local_platform_window,
                            _rr_spike_guarded_band_center,
                            _rr_spike_guarded_extreme_index,
                        )

                        rr_i0 = max(
                            0,
                            min(
                                int(
                                    np.searchsorted(
                                        t,
                                        min(float(win[0]), float(win[1]))
                                        * 1e-6,
                                        side="left",
                                    )
                                ),
                                len(t) - 2,
                            ),
                        )
                        rr_i1 = max(
                            rr_i0 + 1,
                            min(
                                int(
                                    np.searchsorted(
                                        t,
                                        max(float(win[0]), float(win[1]))
                                        * 1e-6,
                                        side="left",
                                    )
                                ),
                                len(t) - 1,
                            ),
                        )
                        rr_seg = np.asarray(
                            chan["irr"][rr_i0 : rr_i1 + 1], dtype=np.float64
                        )
                        if len(rr_seg) >= 8:
                            reverse_idx = _rr_spike_guarded_extreme_index(
                                rr_seg,
                                maximum=bool(context.polarity < 0),
                            )
                            tail0 = reverse_idx + max(
                                8,
                                int(0.30 * (len(rr_seg) - reverse_idx)),
                            )
                            tail = rr_seg[tail0:]
                            if len(tail) < 8:
                                tail = rr_seg[reverse_idx:]
                            quiet_tail = _rr_quiet_local_platform_window(
                                tail, bundle.dt, min_ns=200.0
                            )
                            expected_stable_base = _rr_spike_guarded_band_center(
                                quiet_tail
                            )
                            if not _short_values_close(
                                float(context.base_a),
                                float(expected_stable_base),
                                floor=1e-9,
                            ):
                                problems.append(
                                    "RR di/dt Ha未使用稳定尾段原始max/min中点: "
                                    f"{float(context.base_a):.9g}≠"
                                    f"{float(expected_stable_base):.9g}A"
                                )
                            stable_base_detail = (
                                f" stableBaseMid={float(expected_stable_base):.9g}A"
                            )
                            from dpt_extractor.metrics.iec_windows import (
                                err_recovery_peak_index,
                            )
                            from dpt_extractor.metrics.slopes import (
                                rr_didt_between_levels,
                            )

                            completed = mw._rr_measurement_window_indices()
                            recovery_end = (
                                completed[2] if completed is not None else s1
                            )
                            recovery = np.asarray(
                                chan["irr"][s0 : recovery_end + 1],
                                dtype=np.float64,
                            )
                            recovery_peak = s0 + int(
                                err_recovery_peak_index(recovery, bundle.dt)
                            )
                            recovery_peak_t = float(t[recovery_peak])
                            platform_i0 = int(
                                np.searchsorted(
                                    t,
                                    recovery_peak_t - 0.6e-6,
                                    side="left",
                                )
                            )
                            platform_i1 = int(
                                np.searchsorted(
                                    t,
                                    recovery_peak_t - 0.2e-6,
                                    side="right",
                                )
                            )
                            stable_forward = np.asarray(
                                chan["irr"][platform_i0:platform_i1],
                                dtype=np.float64,
                            )
                            if len(stable_forward) >= 2:
                                broad_center = _rr_spike_guarded_band_center(
                                    stable_forward
                                )
                                quiet_forward = _rr_quiet_local_platform_window(
                                    stable_forward,
                                    bundle.dt,
                                    min_ns=200.0,
                                )
                                quiet_center = _rr_spike_guarded_band_center(
                                    quiet_forward
                                )
                                broad_p05, broad_p95 = (
                                    float(np.percentile(stable_forward, p))
                                    for p in (5.0, 95.0)
                                )
                                quiet_p05, quiet_p95 = (
                                    float(np.percentile(quiet_forward, p))
                                    for p in (5.0, 95.0)
                                )
                                broad_spread = max(
                                    0.0, broad_p95 - broad_p05
                                )
                                quiet_spread = max(
                                    0.0, quiet_p95 - quiet_p05
                                )
                                quiet_reference = max(
                                    1e-9,
                                    quiet_spread,
                                    0.002
                                    * max(abs(float(quiet_center)), 1.0),
                                )
                                edge_contaminated = (
                                    broad_spread > 2.0 * quiet_reference
                                    and abs(
                                        float(broad_center)
                                        - float(quiet_center)
                                    )
                                    > 1.5 * quiet_reference
                                )
                                expected_stable_forward = (
                                    quiet_center
                                    if edge_contaminated
                                    else broad_center
                                )
                                if not _short_values_close(
                                    float(context.forward_a),
                                    float(expected_stable_forward),
                                    floor=1e-9,
                                ):
                                    problems.append(
                                        "RR di/dt Hb未按宽窗污染门选择换流前"
                                        "稳定带原始max/min中点: "
                                        f"{float(context.forward_a):.9g}≠"
                                        f"{float(expected_stable_forward):.9g}A"
                                    )
                                row_key = SLOPE_ROW_KEYS[("反向恢复", "di/dt")]
                                slope_ranges = getattr(
                                    mw,
                                    "_slope_ranges",
                                    mw.cfg.slope_ranges,
                                )
                                slope_range = slope_ranges.get(row_key)
                                pct_a, pct_b = _effective_slope_percentages(
                                    slope_range,
                                    context.crossing,
                                    (0.9, 0.1),
                                )
                                independent_crossing = rr_didt_between_levels(
                                    t,
                                    chan["irr"],
                                    rr_i0,
                                    rr_i1,
                                    pct_a,
                                    pct_b,
                                    measure="idm",
                                    forward_a=float(expected_stable_forward),
                                    base_or_reverse_a=float(expected_stable_base),
                                )
                                if (
                                    independent_crossing.t_pct_a_s is None
                                    or independent_crossing.t_pct_b_s is None
                                ):
                                    problems.append(
                                        "RR di/dt 独立稳定中点无法得到真实 A/B"
                                    )
                                else:
                                    independent_ab = (
                                        float(independent_crossing.t_pct_a_s) * 1e6,
                                        float(independent_crossing.t_pct_b_s) * 1e6,
                                    )
                                    if gui_ab_us is None or not all(
                                        _short_values_close(
                                            float(actual),
                                            float(expected),
                                            floor=1e-7,
                                        )
                                        for actual, expected in zip(
                                            gui_ab_us,
                                            independent_ab,
                                            strict=True,
                                        )
                                    ):
                                        problems.append(
                                            "RR di/dt A/B未绑定独立稳定中点交点: "
                                            f"gui={gui_ab_us} expected={independent_ab}"
                                        )
                                    if not _short_values_close(
                                        float(result.reverse_recovery.didt_irr),
                                        float(independent_crossing.didt),
                                        floor=1e-9,
                                    ):
                                        problems.append(
                                            "RR di/dt结果未绑定独立稳定中点斜率: "
                                            f"{float(result.reverse_recovery.didt_irr):.12g}≠"
                                            f"{float(independent_crossing.didt):.12g}"
                                        )
                                stable_base_detail += (
                                    f" stableForwardMid="
                                    f"{float(expected_stable_forward):.9g}A"
                                )
                    context_problems, context_detail = (
                        _audit_turn_off_slope_context_consistency(
                            metric_name="反向恢复 di/dt",
                            gui_top=float(top_v),
                            gui_base=float(base_v),
                            gui_ab_us=gui_ab_us,
                            context_top=context_top,
                            context_base=context_base,
                            context_value=float(context.crossing.didt),
                            context_t_a_s=context.crossing.t_pct_a_s,
                            context_t_b_s=context.crossing.t_pct_b_s,
                            threshold_a=float(context.crossing.th_a),
                            threshold_b=float(context.crossing.th_b),
                            used_fallback=bool(context.used_fallback),
                            result_value=float(result.reverse_recovery.didt_irr),
                            t=t,
                            raw_values=chan[channel],
                            use_abs=False,
                        )
                    )
                    problems.extend(context_problems)
                    detail += " | " + context_detail + stable_base_detail
            elif section == "开通" and name == "di/dt":
                context = mw._turn_on_didt_context(*win)
                if context is None:
                    problems.append("开通 di/dt MainWindow共用context不可用")
                    detail += " | context=none used_fallback=unknown cross=unknown"
                else:
                    context_problems, context_detail = (
                        _audit_turn_off_slope_context_consistency(
                            metric_name="开通 di/dt",
                            gui_top=float(top_v),
                            gui_base=float(base_v),
                            gui_ab_us=gui_ab_us,
                            context_top=float(context.top_a),
                            context_base=float(context.base_a),
                            context_value=float(context.crossing.didt),
                            context_t_a_s=context.crossing.t_pct_a_s,
                            context_t_b_s=context.crossing.t_pct_b_s,
                            threshold_a=float(context.crossing.th_a),
                            threshold_b=float(context.crossing.th_b),
                            used_fallback=bool(context.used_fallback),
                            result_value=float(result.turn_on.didt),
                            t=t,
                            raw_values=chan["ic"],
                            use_abs=False,
                        )
                    )
                    problems.extend(context_problems)

                    row_key = SLOPE_ROW_KEYS[("开通", "di/dt")]
                    slope_ranges = getattr(mw, "_slope_ranges", mw.cfg.slope_ranges)
                    slope_range = slope_ranges.get(row_key)
                    pct_a, pct_b = _effective_slope_percentages(
                        slope_range,
                        context.crossing,
                        (0.1, 0.9),
                    )
                    span = float(context.top_a - context.base_a)
                    expected_th_a = float(
                        context.base_a + min(pct_a, pct_b) * span
                    )
                    expected_th_b = float(
                        context.base_a + max(pct_a, pct_b) * span
                    )
                    if float(context.crossing.th_a) != expected_th_a:
                        problems.append(
                            "开通 di/dt A阈值未使用Base+pct*(Top-Base): "
                            f"{float(context.crossing.th_a):.12g}≠{expected_th_a:.12g}"
                        )
                    if float(context.crossing.th_b) != expected_th_b:
                        problems.append(
                            "开通 di/dt B阈值未使用Base+pct*(Top-Base): "
                            f"{float(context.crossing.th_b):.12g}≠{expected_th_b:.12g}"
                        )
                    if (
                        context.crossing.t_pct_a_s is not None
                        and context.crossing.t_pct_b_s is not None
                        and not (
                            float(context.crossing.t_pct_a_s)
                            < float(context.crossing.t_pct_b_s)
                        )
                    ):
                        problems.append("开通 di/dt 屏幕A/B未保持左→右物理顺序")

                    stable_detail: list[str] = []
                    for label, declared, expected_level in (
                        ("Hb", context.base_window, float(context.base_a)),
                        ("Ha", context.top_window, float(context.top_a)),
                    ):
                        if declared is None:
                            problems.append(f"开通 di/dt 未声明{label}稳定平台来源窗")
                            continue
                        w0, w1 = int(declared[0]), int(declared[1])
                        if not (0 <= w0 <= w1 < len(t)):
                            problems.append(
                                f"开通 di/dt {label}稳定窗越界: {declared!r}"
                            )
                            continue
                        if label == "Ha":
                            pulse2_off = int(result.segments.pulse2_off)
                            if w1 >= pulse2_off:
                                problems.append(
                                    "开通 di/dt Ha稳定窗越过本次pulse2_off"
                                )
                            if (
                                context.crossing.t_pct_b_s is not None
                                and float(t[w0])
                                <= float(context.crossing.t_pct_b_s)
                            ):
                                problems.append(
                                    "开通 di/dt B后未进入声明的Ic Ha平台"
                                )
                        independent_mid = float(
                            _plateau_mid_without_isolated_spikes(
                                np.asarray(chan["ic"][w0 : w1 + 1], dtype=np.float64)
                            )
                        )
                        if independent_mid != expected_level:
                            problems.append(
                                f"开通 di/dt {label}未绑定声明稳定带原始max/min中点: "
                                f"{expected_level:.12g}≠{independent_mid:.12g}"
                            )
                        stable_detail.append(
                            f"{label}Win={float(t[w0])*1e6:.6f}/"
                            f"{float(t[w1])*1e6:.6f}us mid={independent_mid:.9g}A"
                        )
                    if float(result.turn_on.turn_on_current) != float(context.top_a):
                        problems.append(
                            "开通 di/dt Ha与开通电流卡值未共用同一平台: "
                            f"{float(context.top_a):.12g}≠"
                            f"{float(result.turn_on.turn_on_current):.12g}"
                        )
                    if (
                        context.crossing.t_pct_a_s is not None
                        and context.crossing.t_pct_b_s is not None
                    ):
                        segs = result.segments
                        assert segs is not None
                        vce_top = turn_on_vce_top_from_ic_rise(
                            chan["ic"],
                            chan["vce"],
                            segs.pulse2_on,
                            segs.pulse2_off,
                            bundle.dt,
                        )
                        ls_context = turn_on_commutation_inductance(
                            t,
                            chan["vce"],
                            chan["ic"],
                            vce_top,
                            context.crossing.t_pct_a_s,
                            context.crossing.t_pct_b_s,
                        )
                        if ls_context is None:
                            problems.append("Ls_on同步积分context不可用")
                        elif float(result.turn_on.ls_on) != float(ls_context.value_nh):
                            problems.append(
                                "Ls_on未绑定开通di/dt共用时间窗积分: "
                                f"{float(result.turn_on.ls_on):.12g}≠"
                                f"{float(ls_context.value_nh):.12g}"
                            )
                    detail += " | " + context_detail
                    if stable_detail:
                        detail += " | " + " ".join(stable_detail)
            elif section == "开通" and name == "dv/dt":
                context = mw._turn_on_dvdt_context(*win)
                if context is None:
                    problems.append("开通 dv/dt MainWindow共用context不可用")
                    detail += " | context=none used_fallback=unknown cross=unknown"
                else:
                    segs = result.segments
                    assert segs is not None
                    on0, on1 = segs.turn_on
                    independent_base, independent_top = (
                        turn_on_dvdt_base_top_levels(
                            np.asarray(chan["vce"]),
                            on0,
                            on1,
                            segs.pulse2_off,
                            bundle.dt,
                        )
                    )
                    independent_base = float(independent_base)
                    independent_top = float(independent_top)
                    if not _short_values_close(
                        float(base_v), independent_base, floor=1e-9
                    ):
                        problems.append(
                            "开通 dv/dt Hb未绑定跌落后稳定低电压平台: "
                            f"{float(base_v):.12g}≠{independent_base:.12g}V"
                        )
                    if not _short_values_close(
                        float(top_v), independent_top, floor=1e-9
                    ):
                        problems.append(
                            "开通 dv/dt Ha未绑定跌落前稳定电压平台: "
                            f"{float(top_v):.12g}≠{independent_top:.12g}V"
                        )
                    context_problems, context_detail = (
                        _audit_turn_off_slope_context_consistency(
                            metric_name="开通 dv/dt",
                            gui_top=float(top_v),
                            gui_base=float(base_v),
                            gui_ab_us=gui_ab_us,
                            context_top=float(context.top_v),
                            context_base=float(context.base_v),
                            context_value=float(context.crossing.dvdt),
                            context_t_a_s=context.crossing.t_pct_a_s,
                            context_t_b_s=context.crossing.t_pct_b_s,
                            threshold_a=float(context.crossing.th_a),
                            threshold_b=float(context.crossing.th_b),
                            used_fallback=bool(context.used_fallback),
                            result_value=float(result.turn_on.dvdt),
                            t=t,
                            raw_values=chan["vce"],
                            use_abs=False,
                        )
                    )
                    problems.extend(context_problems)
                    detail += " | " + context_detail
            elif section == "反向恢复" and name == "dv/dt":
                context = mw._rr_dvdt_context()
                if context is None:
                    problems.append("反向恢复 dv/dt MainWindow共用context不可用")
                    detail += " | context=none used_fallback=unknown cross=unknown"
                else:
                    completed = mw._rr_measurement_window_indices()
                    assert completed is not None
                    rr_i0, rr_i1, _rr_context_i1, _extended = completed
                    # The stable blocking platform is intentionally allowed to
                    # settle after the compact RR crossing window.  Its
                    # physical upper bound must therefore use the same
                    # event-local look-ahead as the production context, never
                    # the compact ``rr_i0:rr_i1`` slice alone.  Some slow
                    # records finish a few volts above that compact slice while
                    # remaining well below the actual event peak.
                    rr_peak_end = max(
                        rr_i1,
                        min(int(segs.pulse2_off) + 1, len(t)),
                    )
                    independent_peak = float(
                        np.max(np.abs(chan["v_diode"][rr_i0:rr_peak_end]))
                    )
                    independent_levels = _rr_dvdt_stable_base_top(
                        t,
                        np.abs(chan["v_diode"]),
                        rr_i0,
                        rr_i1,
                        segs.turn_on[1],
                        segs.pulse2_off,
                        bundle.dt,
                    )
                    if independent_levels is None:
                        problems.append(
                            "反向恢复 dv/dt 稳定高低平台独立计算不可用"
                        )
                    else:
                        independent_base, independent_top = independent_levels
                        if not _short_values_close(
                            float(base_v), float(independent_base), floor=1e-9
                        ):
                            problems.append(
                                "反向恢复 dv/dt Hb未绑定主上升前稳定低电压平台: "
                                f"{float(base_v):.12g}≠{float(independent_base):.12g}V"
                            )
                        if not _short_values_close(
                            float(top_v), float(independent_top), floor=1e-9
                        ):
                            problems.append(
                                "反向恢复 dv/dt Ha未绑定恢复后稳定阻断平台: "
                                f"{float(top_v):.12g}≠{float(independent_top):.12g}V"
                            )
                    if (
                        not np.isfinite(float(context.top_v))
                        or float(context.top_v) <= 0.0
                        or float(context.top_v) > independent_peak * 1.001
                    ):
                        problems.append(
                            "反向恢复 dv/dt Ha不是有效稳定阻断平台: "
                            f"Ha={float(context.top_v):.12g}V, "
                            f"|VDM|max={independent_peak:.12g}V"
                        )
                    context_problems, context_detail = (
                        _audit_turn_off_slope_context_consistency(
                            metric_name="反向恢复 dv/dt",
                            gui_top=float(top_v),
                            gui_base=float(base_v),
                            gui_ab_us=gui_ab_us,
                            context_top=float(context.top_v),
                            context_base=float(context.base_v),
                            context_value=float(context.crossing.dvdt),
                            context_t_a_s=context.crossing.t_pct_a_s,
                            context_t_b_s=context.crossing.t_pct_b_s,
                            threshold_a=float(context.crossing.th_a),
                            threshold_b=float(context.crossing.th_b),
                            used_fallback=bool(context.used_fallback),
                            result_value=float(result.reverse_recovery.dvdt_max),
                            t=t,
                            raw_values=chan["v_diode"],
                            use_abs=True,
                        )
                    )
                    problems.extend(context_problems)
                    detail += " | " + context_detail

        elif name in ("Eoff", "Eon"):
            c = calls.get("enable_energy_loss_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_energy_loss_interaction")
                continue
            b = c["bound"]
            ta, tb, ha_v, hb_a = b["t_a_us"], b["t_b_us"], b["ha_v"], b["hb_a"]
            ha_ch, hb_ch = b.get("ha_channel"), b.get("hb_channel")
            win = (b["search_t0_us"], b["search_t1_us"])
            exp = ("vce", "ic") if name == "Eoff" else ("ic", "vce")
            check_channel(ha_ch, exp[0], "Ha")
            check_channel(hb_ch, exp[1], "Hb")
            loss_search_segment = (
                _idx(t, min(float(win[0]), float(win[1]))),
                _idx(t, max(float(win[0]), float(win[1]))),
            )
            check_time(ta, "A", loss_search_segment)
            check_time(tb, "B", loss_search_segment)
            if not float(ta) < float(tb):
                problems.append(f"A({float(ta):.6f})应早于B({float(tb):.6f})")
            problems.extend(
                _ab_role_binding_problems(
                    float(ta),
                    float(tb),
                    mw._parameter_interval_us(section, name),
                    role_text=DPT_PARAMETER_CURSOR_ROLES[(section, name)],
                )
            )
            check_level(ha_v, ha_ch, "Ha", win)
            check_level(hb_a, hb_ch, "Hb", win)
            energy_contexts = getattr(result, "energy_contexts", {})
            marker_context = (
                energy_contexts.get((section, name))
                if isinstance(energy_contexts, dict)
                else None
            )
            endpoint_mode = _energy_endpoint_mode(marker_context)
            if name == "Eoff" and endpoint_mode == "stable_platforms":
                stable_context = getattr(
                    marker_context,
                    "stable_platform_context",
                    None,
                )
                stable_problems, stable_detail = (
                    _eoff_stable_platform_audit_problems(
                        t,
                        chan["vce"],
                        chan["ic"],
                        a_us=float(ta),
                        b_us=float(tb),
                        ha_v=float(ha_v),
                        hb_a=float(hb_a),
                        stored_eoff_mj=float(result.turn_off.eoff),
                        context=stable_context,
                    )
                )
                problems.extend(stable_problems)
            else:
                stable_detail = f"mode={endpoint_mode}"
                if endpoint_mode != "level_crossings":
                    problems.append(
                        f"{name} 未知损耗端点模式: {endpoint_mode!r}"
                    )
            if (
                not (name == "Eoff" and endpoint_mode == "stable_platforms")
                and ha_ch in chan
                and hb_ch in chan
            ):
                for problem in (
                    _cursor_level_binding_problem(
                        "A/Ha",
                        float(ta),
                        float(ha_v),
                        t,
                        chan[ha_ch],
                        floor=0.05,
                    ),
                    _cursor_level_binding_problem(
                        "B/Hb",
                        float(tb),
                        float(hb_a),
                        t,
                        chan[hb_ch],
                        floor=0.05,
                    ),
                ):
                    if problem is not None:
                        problems.append(problem)
            if name == "Eoff" and endpoint_mode != "stable_platforms":
                visible_energy = _visible_eoff_energy_mj(
                    t,
                    chan["vce"],
                    chan["ic"],
                    float(ta),
                    float(tb),
                )
                if visible_energy is None:
                    problems.append("Eoff 可见 A/B 原始 Vce*Ic 独立积分不可用")
                elif not _short_values_close(
                    float(result.turn_off.eoff),
                    float(visible_energy),
                    floor=1e-9,
                    rtol=2e-8,
                ):
                    problems.append(
                        "Eoff 表值未与可见 A/B 原始 Vce*Ic 积分闭环: "
                        f"stored={float(result.turn_off.eoff):.12g}mJ, "
                        f"visible={float(visible_energy):.12g}mJ"
                    )
                else:
                    stable_detail += f" visible_Eoff={float(visible_energy):.9g}mJ"
            detail = (
                f"Ha({ha_ch})={ha_v:.1f} Hb({hb_ch})={hb_a:.1f} "
                f"A={ta:.2f} B={tb:.2f} {stable_detail}"
            )

        elif name == "Err":
            c = calls.get("enable_energy_loss_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_energy_loss_interaction")
                continue
            b = c["bound"]
            ta, tb, ha_a, hb_v = b["t_a_us"], b["t_b_us"], b["ha_v"], b["hb_a"]
            ha_ch, hb_ch = b.get("ha_channel"), b.get("hb_channel")
            win = (b["search_t0_us"], b["search_t1_us"])
            check_channel(ha_ch, "irr", "Ha")
            check_channel(hb_ch, "v_diode", "Hb")
            if not (ta > tb):
                problems.append(f"A({ta:.3f})应晚于B({tb:.3f})")
            on1 = seg_idx["turn_on"][1]
            from dpt_extractor.metrics.iec_windows import err_recovery_peak_index

            completed = mw._rr_measurement_window_indices()
            rr_context_i1 = completed[2] if completed is not None else s1
            ipk = s0 + err_recovery_peak_index(
                np.asarray(
                    chan["irr"][s0 : rr_context_i1 + 1],
                    dtype=np.float64,
                ),
                bundle.dt,
            )
            tpk_us = float(t[ipk]) * 1e6
            err_search_segment = (
                _idx(t, min(float(win[0]), float(win[1]))),
                _idx(t, max(float(win[0]), float(win[1]))),
            )
            check_time(ta, "A", err_search_segment)
            check_time(tb, "B", err_search_segment)
            # Err levels are defined by its actual parameter-local window and
            # raw A/B intersections.  A fixed peak+0.4~0.8us audit band is not
            # authoritative for low-current soft recovery and can exclude the
            # valid early local Top even when Irr(A)==Ha exactly.
            err_level_window = (
                min(float(win[0]), float(ta), float(tb)),
                max(float(win[1]), float(ta), float(tb)),
            )
            check_level(ha_a, "irr", "Ha", err_level_window)
            check_level(hb_v, "v_diode", "Hb", err_level_window)
            err_a_matches, irr_at_a, err_a_atol = _err_a_signed_intersection_check(
                ha_a,
                ta * 1e-6,
                t,
                chan["irr"],
            )
            peak_a = float(chan["irr"][ipk])
            if _err_a_requires_settled_gate(peak_a, ha_a):
                from dpt_extractor.metrics.iec_windows import (
                    _err_recovery_settled_base,
                )

                settled = _err_recovery_settled_base(
                    np.asarray(chan["irr"], dtype=np.float64),
                    ipk,
                    bundle.dt,
                    on1,
                )
                settled_start_s = float(t[settled.start_idx])
                if not _err_a_settled_gate_check(
                    peak_a,
                    ha_a,
                    ta * 1e-6,
                    settled_start_s,
                ):
                    problems.append(
                        f"近零正Ha的A={ta:.6f}us 早于恢复稳定门"
                        f"={settled_start_s * 1e6:.6f}us"
                        f"（允许提前{ERR_A_SETTLED_GATE_MARGIN_S * 1e9:.1f}ns）"
                    )
            vd_at_b = float(np.interp(tb * 1e-6, t, chan["v_diode"]))
            if not err_a_matches:
                problems.append(
                    f"Ha 符号/落点={ha_a:.6f} 与 irr(A)={irr_at_a:.6f}不符"
                    f" (差值={abs(float(ha_a) - irr_at_a):.6g}A,"
                    f" 插值容差={err_a_atol:.6g}A)"
                )
            if not np.isclose(hb_v, vd_at_b, rtol=0.08, atol=8.0):
                problems.append(
                    f"Hb 符号/落点={hb_v:.2f} 与 Vd(B)={vd_at_b:.2f}不符"
                )
            problems.extend(
                _err_signed_cursor_text_problems(
                    mw.wave_plot,
                    float(ha_a),
                    float(hb_v),
                )
            )
            detail = f"Ha(irr)={ha_a:.2f} Hb(vd)={hb_v:.2f} A={ta:.3f} B={tb:.3f}"

        elif name == "Irr":
            c = calls.get("enable_irr_peak_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_irr_peak_interaction")
                continue
            interval_bound = c["bound"]
            irr_a = float(interval_bound["start_t_us"])
            irr_b = float(interval_bound["end_t_us"])
            if not irr_a < irr_b:
                problems.append(f"Irr A({irr_a:.6f})应早于B({irr_b:.6f})")
            problems.extend(
                _ab_role_binding_problems(
                    irr_a,
                    irr_b,
                    mw._parameter_interval_us(section, name),
                    role_text=DPT_PARAMETER_CURSOR_ROLES[(section, name)],
                )
            )
            if str(getattr(mw.wave_plot, "_active_channel", "")) != "irr":
                problems.append("Irr A/B 未绑定 irr 活动通道")
            hb_call = calls.get("set_interval_peak_on_hb")
            hb_val = hb_call["bound"].get("y") if hb_call else float("nan")
            ch = hb_call["bound"].get("channel") if hb_call else None
            check_channel(ch, "irr", "Hb")
            ha_call = calls.get("set_irr_base_on_ha")
            ha_val = ha_call["bound"].get("y") if ha_call else float("nan")
            ha_ch = ha_call["bound"].get("channel") if ha_call else None
            check_channel(ha_ch, "irr", "Ha")
            stable_context = mw._rr_irr_cursor_context()
            if stable_context is None:
                problems.append("Irr 稳定平台光标上下文不可用")
            else:
                expected_a_us = float(t[int(stable_context[0])] * 1e6)
                expected_b_us = float(t[int(stable_context[1])] * 1e6)
                expected_base = float(stable_context[2])
                if not _short_values_close(irr_a, expected_a_us, floor=1e-9):
                    problems.append(
                        f"Irr A={irr_a:.9f}us≠正向稳定段{expected_a_us:.9f}us"
                    )
                if not _short_values_close(irr_b, expected_b_us, floor=1e-9):
                    problems.append(
                        f"Irr B={irr_b:.9f}us≠恢复Base稳定段{expected_b_us:.9f}us"
                    )
                if not np.isfinite(float(ha_val)) or not _short_values_close(
                    float(ha_val), expected_base, floor=1e-8
                ):
                    problems.append(
                        f"Irr Ha={float(ha_val):.9g}≠恢复Base{expected_base:.9g}"
                    )
            from dpt_extractor.metrics.irr_measure import irr_parameter_peak_index

            expected_idx = int(
                irr_parameter_peak_index(
                    np.asarray(chan["irr"], dtype=np.float64),
                    segs.reverse_recovery[0],
                    segs.reverse_recovery[1],
                    segs.pulse2_on,
                    segs.turn_on[0],
                    segs.turn_on[1],
                )
            )
            expected_signed = float(chan["irr"][expected_idx])
            expected_peak_us = float(t[expected_idx] * 1e6)
            if not irr_a <= expected_peak_us <= irr_b:
                problems.append("Irr 权威尖峰不在 A/B 取值窗内")
            if not np.isfinite(float(hb_val)) or not np.isclose(
                float(hb_val), expected_signed, rtol=0.15, atol=8.0
            ):
                problems.append(
                    f"Irr峰 Hb={float(hb_val):.1f} 与有符号尖峰"
                    f"={expected_signed:.1f}不符"
                )
            if irr_ref > 1.0 and not (0.5 * irr_ref <= abs(hb_val) <= 1.3 * irr_ref):
                problems.append(f"Irr峰|Hb|={abs(hb_val):.1f} 与提取Irr={irr_ref:.1f}不符")
            detail = (
                f"ch={ch} A={irr_a:.3f} B={irr_b:.3f} "
                f"Ha={float(ha_val):.1f} Hb={float(hb_val):.1f} irr_ref={irr_ref:.1f}"
            )

        elif name == "Trr":
            c = calls.get("enable_trr_measure_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_trr_measure_interaction（回退 generic）")
                continue
            if "enable_interval_interaction" in calls:
                problems.append("Trr 禁止回退 generic interval 交互")
            b = c["bound"]
            ha_a, hb_a, ta, tb = b["ha_a"], b["hb_a"], b["ta_us"], b["tb_us"]
            peak_idx = b.get("peak_idx")
            from dpt_extractor.metrics.irr_measure import default_irr_trr_measure

            expected = default_irr_trr_measure(
                t,
                np.asarray(chan["irr"], dtype=np.float64),
                segs.reverse_recovery[0],
                segs.reverse_recovery[1],
                segs.pulse2_on,
                segs.turn_on[0],
                segs.turn_on[1],
                pulse2_off=segs.pulse2_off,
            )
            fall_end_idx = b.get("i_fall_end_idx")
            authoritative_peak_idx = (
                int(expected.peak_idx)
                if expected is not None
                else int(peak_idx) if peak_idx is not None else int(s1)
            )
            authoritative_end_idx = max(
                int(s1),
                authoritative_peak_idx,
                int(fall_end_idx) if fall_end_idx is not None else int(s1),
            )
            authoritative_end_idx = max(
                int(s0), min(authoritative_end_idx, len(t) - 1)
            )
            trr_segment = (int(s0), authoritative_end_idx)
            trr_window_us = (
                float(t[trr_segment[0]]) * 1e6,
                float(t[trr_segment[1]]) * 1e6,
            )

            check_time(ta, "A", seg=trr_segment)
            check_time(tb, "B", seg=trr_segment)
            if not (ta < tb):
                problems.append(f"A({ta:.3f})应早于B({tb:.3f})")
            if peak_idx is not None and not (
                trr_segment[0] <= int(peak_idx) <= trr_segment[1]
            ):
                problems.append(
                    f"peak_idx={peak_idx}不在权威Trr扩展窗"
                    f"[{trr_segment[0]},{trr_segment[1]}]"
                )
            if peak_idx is None:
                problems.append("Trr 缺少 Irr 尖峰索引")
            elif 0 <= int(peak_idx) < len(t):
                peak_t_us = float(t[int(peak_idx)] * 1e6)
                if not float(ta) < peak_t_us < float(tb):
                    problems.append(
                        f"Trr 尖峰={peak_t_us:.6f}us 未位于 A/B 之间"
                    )
            trr_from_ab_ns = abs(float(tb) - float(ta)) * 1e3
            if not _short_values_close(
                float(result.reverse_recovery.trr), trr_from_ab_ns, floor=1e-6
            ):
                problems.append(
                    f"Trr结果/B-A={result.reverse_recovery.trr:.9g}/"
                    f"{trr_from_ab_ns:.9g}ns"
                )
            check_level(ha_a, "irr", "Ha", win_us=trr_window_us)
            check_level(hb_a, "irr", "Hb", win_us=trr_window_us)
            if str(getattr(mw.wave_plot, "_active_channel", "")) != "irr":
                problems.append("Trr A/B/Ha/Hb 未绑定 irr 活动通道")
            stable_a = None if expected is None else expected.stable_level
            if expected is None or stable_a is None:
                problems.append("Trr 权威恢复平台卡尺上下文不可用，禁止 generic 回退")
            else:
                first_crossings = _first_trr_stable_platform_crossings(
                    t,
                    np.asarray(chan["irr"], dtype=np.float64),
                    segs.reverse_recovery[0],
                    expected.peak_idx,
                    (
                        int(fall_end_idx)
                        if fall_end_idx is not None
                        else authoritative_end_idx
                    ),
                    float(stable_a),
                )
                if first_crossings is None:
                    problems.append("Trr 从RR事件窗起点无法取得稳定平台首个双交点")
                    expected_a_us = float(expected.ta_s) * 1e6
                    expected_b_us = float(expected.tb_s) * 1e6
                else:
                    expected_a_us = float(first_crossings[0]) * 1e6
                    expected_b_us = float(first_crossings[1]) * 1e6
                expected_values = (
                    ("Ha", float(ha_a), float(stable_a), 1e-8),
                    ("Hb", float(hb_a), float(expected.hb), 1e-8),
                    ("A", float(ta), expected_a_us, 1e-7),
                    ("B", float(tb), expected_b_us, 1e-7),
                )
                for label, actual, expected_value, floor in expected_values:
                    if not _short_values_close(
                        actual,
                        expected_value,
                        floor=floor,
                        rtol=1e-8,
                    ):
                        problems.append(
                            f"Trr {label}={actual:.9g} 与权威恢复平台卡尺"
                            f"={expected_value:.9g}不符"
                        )
                if not _short_values_close(
                    float(expected.ha),
                    float(stable_a),
                    floor=1e-8,
                    rtol=1e-8,
                ):
                    problems.append(
                        f"Trr上下文Ha={expected.ha:.9g} 未等于恢复平台"
                        f"max/min平均中线={float(stable_a):.9g}"
                    )
                if not _short_values_close(
                    float(expected.ta_s) * 1e6,
                    expected_a_us,
                    floor=1e-7,
                ) or not _short_values_close(
                    float(expected.tb_s) * 1e6,
                    expected_b_us,
                    floor=1e-7,
                ):
                    problems.append(
                        "Trr上下文A/B未使用从RR事件窗起点取得的首个上升/下降交点"
                    )
                if peak_idx is None or int(peak_idx) != int(expected.peak_idx):
                    problems.append(
                        f"Trr peak_idx={peak_idx} 与权威主峰"
                        f"={expected.peak_idx}不符"
                    )
                if not _short_values_close(
                    float(result.reverse_recovery.trr),
                    float(expected.trr_ns),
                    floor=1e-6,
                ):
                    problems.append(
                        f"Trr结果/权威恢复平台={result.reverse_recovery.trr:.9g}/"
                        f"{expected.trr_ns:.9g}ns"
                    )
                if irr_ref > 1.0 and not np.isclose(
                    abs(float(hb_a)),
                    irr_ref,
                    rtol=0.15,
                    atol=8.0,
                ):
                    problems.append(
                        f"Trr尖峰|Hb|={abs(float(hb_a)):.1f} "
                        f"与提取Irr={irr_ref:.1f}不符"
                    )

            for label, cursor_us in (("A/Ha", ta), ("B/Ha", tb)):
                problem = _cursor_level_binding_problem(
                    label,
                    float(cursor_us),
                    float(ha_a),
                    t,
                    chan["irr"],
                    floor=0.05,
                )
                if problem is not None:
                    problems.append(problem)

            for label, cursor in (
                ("A", getattr(mw.wave_plot, "_cursor_a", None)),
                ("B", getattr(mw.wave_plot, "_cursor_b", None)),
                ("Ha", getattr(mw.wave_plot, "_h_cursor_a", None)),
                ("Hb", getattr(mw.wave_plot, "_h_cursor_b", None)),
            ):
                if cursor is None or not bool(getattr(cursor, "movable", False)):
                    problems.append(f"Trr {label} 光标应保持可移动")

            stable_text = (
                f"{float(stable_a):.2f}" if stable_a is not None else "不可用"
            )
            detail = (
                f"stable=Ha={stable_text} HbPeak={hb_a:.1f} "
                f"A={ta:.3f} B={tb:.3f} pk={peak_idx}"
            )

        elif name == "开通电流":
            c = calls.get("enable_turn_on_current_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_turn_on_current_interaction")
                continue
            b = c["bound"]
            t_a, t_b, hb0, ha0 = b["t_a_us"], b["t_b_us"], b["hb"], b["ha"]
            timing = mw._turn_on_timing_instants()
            expected_a_us, expected_hb, hb_win = turn_on_current_cursor_hb_a_us(
                t,
                chan["ic"],
                s0,
                s1,
                mw.bundle.dt,
                vge10_s=timing.t_v10_s,
                detect_window_ns=mw.cfg.smoothing.detect_window_ns,
            )
            _pipeline_hb_win, ha_win = turn_on_current_hb_ha_window_indices(
                t,
                chan["ic"],
                s0,
                s1,
                mw.bundle.dt,
                event_end_idx=result.segments.pulse2_off,
            )
            if ha_win[0] < 0 or ha_win[1] < ha_win[0]:
                problems.append("开通电流 Ha稳定平台在本次开通事件内不可用")
                record(section, name, "FAIL", "; ".join(problems))
                continue
            hb_win_us = (float(t[hb_win[0]] * 1e6), float(t[hb_win[1]] * 1e6))
            ha_win_us = (float(t[ha_win[0]] * 1e6), float(t[ha_win[1]] * 1e6))
            a_gate_end = int(
                np.searchsorted(
                    t,
                    float(t[hb_win[1]]) + 80e-9,
                    side="right",
                )
            )
            a_gate_end = max(
                max(s0, hb_win[0]) + 1,
                min(a_gate_end, len(t) - 1),
            )
            check_time(t_a, "A", seg=(max(s0, hb_win[0]), a_gate_end))
            check_time(t_b, "B")
            if not float(t_a) < float(t_b):
                problems.append(f"开通电流A({t_a:.6f})应早于B({t_b:.6f})")
            check_level(ha0, "ic", "Ha", win_us=ha_win_us)
            check_level(hb0, "ic", "Hb", win_us=hb_win_us)
            hb_block = np.asarray(chan["ic"])[hb_win[0] : hb_win[1] + 1]
            ha_block = np.asarray(chan["ic"])[ha_win[0] : ha_win[1] + 1]
            hb_mid = _plateau_mid_without_isolated_spikes(hb_block)
            ha_mid = _plateau_mid_without_isolated_spikes(ha_block)
            if not np.isclose(float(hb0), hb_mid, rtol=0.0, atol=1e-9):
                problems.append(
                    f"Hb={hb0:.9g}≠稳定窗原始(max+min)/2={hb_mid:.9g}"
                )
            if not np.isclose(float(hb0), expected_hb, rtol=0.0, atol=1e-9):
                problems.append(
                    f"Hb={hb0:.9g}≠Vge10守卫后的权威Hb={expected_hb:.9g}"
                )
            if not np.isclose(float(ha0), ha_mid, rtol=0.0, atol=1e-9):
                problems.append(
                    f"Ha={ha0:.9g}≠稳定窗原始(max+min)/2={ha_mid:.9g}"
                )
            if not np.isfinite(expected_a_us):
                problems.append("事件局部 Ic/Hb 主上升交点不可用")
            elif not _short_values_close(
                float(t_a), float(expected_a_us), floor=1e-7
            ):
                problems.append(
                    f"A={float(t_a):.9f}us≠事件局部Ic/Hb交点"
                    f"{float(expected_a_us):.9f}us"
                )
            expected_b_us = turn_on_ic_b_cross_ha_us(
                t,
                chan["ic"],
                s0,
                s1,
                float(ha0),
                mw.bundle.dt,
                event_end_idx=result.segments.pulse2_off,
            )
            if not np.isfinite(expected_b_us):
                problems.append("本次事件内 Ic/Ha 稳定平台交点不可用")
            elif not _short_values_close(
                float(t_b), float(expected_b_us), floor=1e-7
            ):
                problems.append(
                    f"B={float(t_b):.9f}us≠本次事件Ic/Ha交点"
                    f"{float(expected_b_us):.9f}us"
                )
            if str(getattr(mw.wave_plot, "_active_channel", "")) != "ic":
                problems.append("开通电流 A/B/Ha/Hb 未绑定 ic 活动通道")
            for label, cursor_us, level in (
                ("A/Hb", t_a, hb0),
                ("B/Ha", t_b, ha0),
            ):
                problem = _cursor_level_binding_problem(
                    label,
                    float(cursor_us),
                    float(level),
                    t,
                    chan["ic"],
                    floor=0.05,
                )
                if problem is not None:
                    problems.append(problem)
            if not (abs(ha0) > abs(hb0)):
                problems.append(f"Ha({ha0:.1f})应>Hb({hb0:.1f})")
            if not _short_values_close(
                float(result.turn_on.turn_on_current), float(ha0), floor=1e-6
            ):
                problems.append("开通电流结果未绑定 Ha")
            detail = (
                f"Hb={hb0:.2f} Ha={ha0:.1f} A={t_a:.3f} B={t_b:.3f} "
                f"hbWin={hb_win_us[0]:.6f}/{hb_win_us[1]:.6f}us "
                f"haWin={ha_win_us[0]:.6f}/{ha_win_us[1]:.6f}us"
            )

        elif name == "ΔVce":
            c = calls.get("enable_delta_vce_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_delta_vce_interaction")
                continue
            b = c["bound"]
            fixed_t = b["fixed_t_us"]
            fixed_v = b["fixed_v"]
            move_t = b["move_t_us"]
            move_v = b.get("move_v")
            search_t0_us = b.get("search_t0_us")
            search_t1_us = b.get("search_t1_us")
            search_window_us = None
            if (
                search_t0_us is not None
                and search_t1_us is not None
                and np.isfinite(float(search_t0_us))
                and np.isfinite(float(search_t1_us))
            ):
                search_window_us = (
                    min(float(search_t0_us), float(search_t1_us)),
                    max(float(search_t0_us), float(search_t1_us)),
                )
            if search_window_us is None:
                check_time(fixed_t, "A")
                check_time(move_t, "B")
            else:
                for label, cursor_us in (("A", fixed_t), ("B", move_t)):
                    if not (
                        search_window_us[0] - 1e-9
                        <= float(cursor_us)
                        <= search_window_us[1] + 1e-9
                    ):
                        problems.append(
                            f"{label}={float(cursor_us):.3f}µs 不在ΔVce参数窗"
                            f"[{search_window_us[0]:.3f},{search_window_us[1]:.3f}]"
                        )
            if not float(fixed_t) < float(move_t):
                problems.append(f"ΔVce A({fixed_t:.6f})应早于B({move_t:.6f})")
            check_level(fixed_v, "vce", "Ha", win_us=search_window_us)
            if move_v is None:
                problems.append("ΔVce 缺少 Hb 电平")
            else:
                check_level(move_v, "vce", "Hb", win_us=search_window_us)
            if str(getattr(mw.wave_plot, "_active_channel", "")) != "vce":
                problems.append("ΔVce A/B/Ha/Hb 未绑定 vce 活动通道")
            if section == "关断过程" and move_v is not None:
                off0, off1 = result.segments.turn_off
                blocking_end = off1
                if not result.single_pulse_mode and result.segments.pulse2_on > off0:
                    blocking_end = max(
                        off1,
                        min(
                            len(t) - 1,
                            int(result.segments.pulse2_on)
                            - max(1, int(200e-9 / mw.bundle.dt)),
                        ),
                    )
                expected_a, expected_b = turn_off_delta_vce_cursor_range_indices(
                    t,
                    chan["vce"],
                    off0,
                    off1,
                    mw.bundle.dt,
                    float(move_v),
                    search_end=blocking_end,
                )
                expected_a_us = float(t[expected_a] * 1e6)
                expected_b_us = float(t[expected_b] * 1e6)
                if not _short_values_close(
                    float(fixed_t), expected_a_us, floor=1e-9
                ):
                    problems.append(
                        f"ΔVce A={float(fixed_t):.9f}us≠Base稳定段"
                        f"{expected_a_us:.9f}us"
                    )
                if not _short_values_close(
                    float(move_t), expected_b_us, floor=1e-9
                ):
                    problems.append(
                        f"ΔVce B={float(move_t):.9f}us≠Top稳定段"
                        f"{expected_b_us:.9f}us"
                    )
                peak_idx = off0 + int(np.argmax(chan["vce"][off0 : off1 + 1]))
                peak_us = float(t[peak_idx] * 1e6)
                if not float(fixed_t) < peak_us < float(move_t):
                    problems.append(
                        f"ΔVce范围未包住抬升尖峰: "
                        f"A/peak/B={float(fixed_t):.6f}/{peak_us:.6f}/"
                        f"{float(move_t):.6f}us"
                    )
                base_v, _stable_top_v = turn_off_dvdt_base_top_levels(
                    t, chan["vce"], off0, off1
                )
                event_span = max(abs(float(move_v) - float(base_v)), 1.0)
                if abs(float(chan["vce"][expected_a]) - float(base_v)) > max(
                    1.0, 0.04 * event_span
                ):
                    problems.append("ΔVce A未落在Vce Base稳定带")
                if abs(float(chan["vce"][expected_b]) - float(move_v)) > max(
                    1.0, 0.04 * event_span
                ):
                    problems.append("ΔVce B未落在Vce Top稳定带")
                if not _short_values_close(
                    float(fixed_v),
                    float(result.turn_off.vce_off_max),
                    floor=1e-6,
                ):
                    problems.append("ΔVce Ha未绑定Vce尖峰最大值")
            else:
                stable_context = mw._turn_on_vce_stable_cursor_context()
                if stable_context is None:
                    problems.append("开通ΔVce稳定 Top/Base 光标上下文不可用")
                else:
                    expected_a, expected_b, base_v, top_v = stable_context
                    expected_a_us = float(t[int(expected_a)] * 1e6)
                    expected_b_us = float(t[int(expected_b)] * 1e6)
                    if not _short_values_close(
                        float(fixed_t), expected_a_us, floor=1e-9
                    ):
                        problems.append("开通ΔVce A未绑定Vce Top稳定段")
                    if not _short_values_close(
                        float(move_t), expected_b_us, floor=1e-9
                    ):
                        problems.append("开通ΔVce B未绑定Vce Base稳定段")
                    span_v = max(abs(float(top_v) - float(base_v)), 1.0)
                    if abs(float(chan["vce"][int(expected_a)]) - float(top_v)) > max(
                        1.0, 0.04 * span_v
                    ):
                        problems.append("开通ΔVce A未落在Vce Top稳定带")
                    if abs(float(chan["vce"][int(expected_b)]) - float(base_v)) > max(
                        1.0, 0.04 * span_v
                    ):
                        problems.append("开通ΔVce B未落在Vce Base稳定带")
            move_text = "missing" if move_v is None else f"{float(move_v):.1f}"
            if move_v is not None:
                delta = abs(float(fixed_v) - float(move_v))
                process_result = (
                    result.turn_off if section == "关断过程" else result.turn_on
                )
                if not _short_values_close(
                    float(process_result.delta_vce), delta, floor=1e-6
                ):
                    problems.append("ΔVce结果未绑定 abs(Ha-Hb)")
            if section == "关断过程":
                detail = (
                    f"ch=vce A(Base)={fixed_t:.3f}us "
                    f"B(Top)={move_t:.3f}us Ha(peak)={fixed_v:.1f}V "
                    f"Hb(Top)={move_text}V"
                )
            else:
                detail = (
                    f"ch=vce A(Top)={fixed_t:.3f}us B(Base)={move_t:.3f}us "
                    f"Ha(Top)={fixed_v:.1f}V Hb(knee)={move_text}V"
                )

        elif name in {"Ls_on", "Ls_off"}:
            c = calls.get("enable_interval_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 Ls 同步积分窗交互")
                continue
            b = c["bound"]
            ta = float(b["start_t_us"])
            tb = float(b["end_t_us"])
            if b.get("mode") != "interval":
                problems.append(f"Ls交互模式={b.get('mode')!r}≠interval")
            if not ta < tb:
                problems.append(f"Ls A({ta:.6f})应早于B({tb:.6f})")
            if (b.get("a_channel") or b.get("channel")) != "ic":
                problems.append("Ls A 未绑定 ic")
            if (b.get("b_channel") or b.get("channel")) != "ic":
                problems.append("Ls B 未绑定 ic")
            if str(getattr(mw.wave_plot, "_active_channel", "")) != "ic":
                problems.append("Ls A/B 未绑定 ic 活动通道")
            context = mw._commutation_inductance_context(section)
            if context is None:
                problems.append("Ls同步电压/电流积分context不可用")
                detail = f"ch=ic A={ta:.6f}us B={tb:.6f}us context=none"
            else:
                expected_a = float(context.t_start_s * 1e6)
                expected_b = float(context.t_end_s * 1e6)
                if not _short_values_close(ta, expected_a, floor=1e-9):
                    problems.append(f"Ls A={ta:.9f}us≠积分窗起点{expected_a:.9f}us")
                if not _short_values_close(tb, expected_b, floor=1e-9):
                    problems.append(f"Ls B={tb:.9f}us≠积分窗终点{expected_b:.9f}us")
                process_result = (
                    result.turn_off if section == "关断过程" else result.turn_on
                )
                actual_ls = (
                    process_result.ls_off if name == "Ls_off" else process_result.ls_on
                )
                if not _short_values_close(
                    float(actual_ls), float(context.value_nh), floor=1e-9
                ):
                    problems.append(
                        f"Ls结果未绑定同步积分context: {float(actual_ls):.12g}≠"
                        f"{float(context.value_nh):.12g}"
                    )
                detail = (
                    f"ch=ic A={ta:.6f}us B={tb:.6f}us "
                    f"area={context.voltage_area_vs * 1e9:.6f}Vns "
                    f"dI={context.delta_current_a:.6f}A L={context.value_nh:.6f}nH"
                )

        elif name in {"Pmax", "Pdmax"}:
            c = calls.get("enable_interval_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发功率区间交互")
                continue
            b = c["bound"]
            ta, tb = b["start_t_us"], b["end_t_us"]
            interval_channel = b.get("channel")
            if b.get("mode") != "power_peak":
                problems.append(f"功率交互模式={b.get('mode')!r}≠power_peak")
            if not float(ta) < float(tb):
                problems.append(f"功率A({float(ta):.6f})应早于B({float(tb):.6f})")
            expected_power_interval = mw._parameter_interval_us(section, name)
            if expected_power_interval is not None:
                # Switching Pmax uses loss bounds; Pdmax independently uses
                # the current's pre/post stable bands, in chronological order.
                expected_power_interval = tuple(sorted(expected_power_interval))
                power_segment = (
                    _idx(t, float(expected_power_interval[0])),
                    _idx(t, float(expected_power_interval[1])),
                )
            else:
                power_segment = (s0, s1)
            check_time(ta, "A", power_segment)
            check_time(tb, "B", power_segment)
            problems.extend(
                _ab_role_binding_problems(
                    float(ta),
                    float(tb),
                    expected_power_interval,
                    role_text=DPT_PARAMETER_CURSOR_ROLES[(section, name)],
                )
            )
            if section == "反向恢复":
                expected_power_series_w = np.abs(chan["v_diode"]) * np.abs(
                    chan["irr"]
                )
                expected_power_roles = ("v_diode", "irr")
            else:
                expected_power_series_w = chan["vce"] * chan["ic"]
                expected_power_roles = ("vce", "ic")
            from dpt_extractor.metrics.energy import peak_power_kw
            from dpt_extractor.metrics.iec_windows import IntegrationWindow

            i0 = int(
                np.searchsorted(t, min(float(ta), float(tb)) * 1e-6, side="left")
            )
            i1 = int(
                np.searchsorted(t, max(float(ta), float(tb)) * 1e-6, side="left")
            )
            i0 = max(0, min(i0, len(t) - 2))
            i1 = max(i0 + 1, min(i1, len(t) - 1))
            raw_win = IntegrationWindow(i0, i1, float(t[i0]), float(t[i1]))
            if section == "反向恢复":
                raw_peak_kw = peak_power_kw(
                    chan["v_diode"], chan["irr"], raw_win, absolute=True
                )
                stored_peak_kw = result.reverse_recovery.pdmax
            else:
                raw_peak_kw = peak_power_kw(chan["vce"], chan["ic"], raw_win)
                stored_peak_kw = (
                    result.turn_off.pmax
                    if section == "关断过程"
                    else result.turn_on.pmax
                )
            if not _short_values_close(
                float(stored_peak_kw), float(raw_peak_kw), floor=1e-9
            ):
                problems.append(
                    f"功率卡值/原始V×I峰="
                    f"{float(stored_peak_kw):.12g}/{float(raw_peak_kw):.12g}kW"
                )
            peak = calls.get("set_interval_peak_horizontal")
            peak_text = ""
            if peak is None:
                # A horizontal power cursor can only be drawn when the TSS
                # actually contains a visible W/kW Math trace.  With raw V/I
                # only, production binds A/B to the two loss-boundary waves
                # and the card must still equal the raw V*I peak.
                expected_endpoint_channels = {
                    "关断过程": ("vce", "ic"),
                    "开通": ("ic", "vce"),
                    "反向恢复": ("irr", "irr"),
                }[section]
                expected_horizontal_bindings = (
                    (None, False),
                    (None, False),
                )
                if mw.wave_plot.power_peak_in_window(
                    float(ta),
                    float(tb),
                    prefer_abs=section == "反向恢复",
                    required_roles=expected_power_roles,
                    expected_power_w=expected_power_series_w,
                ) is not None:
                    problems.append("存在可见功率波形但缺少 Ha 功率峰值参考线")
            else:
                peak_channel = peak["bound"].get("channel")
                peak_y = peak["bound"].get("y")
                raw_reference = (
                    peak_channel == PARAMETER_POWER_REFERENCE_CHANNEL
                )
                expected_endpoint_channels = (
                    {
                        "关断过程": ("vce", "ic"),
                        "开通": ("ic", "vce"),
                        "反向恢复": ("irr", "irr"),
                    }[section]
                    if raw_reference
                    else (peak_channel, peak_channel)
                )
                expected_horizontal_bindings = (
                    (peak_channel, True),
                    (None, False),
                )
                if peak_y is None or not np.isfinite(float(peak_y)):
                    problems.append(f"功率峰值无效: {peak_y}")
                else:
                    peak_text = f" Ha({peak_channel})={float(peak_y):.1f}"
                if raw_reference:
                    if interval_channel != expected_endpoint_channels[0]:
                        problems.append(
                            f"Pmax 原始功率Ha不得改写A/B通道: "
                            f"{interval_channel}≠{expected_endpoint_channels[0]}"
                        )
                elif interval_channel != peak_channel:
                    problems.append(
                        f"功率A/B通道={interval_channel}≠Ha通道{peak_channel}"
                    )
                unit = (
                    mw.wave_plot._unit_for_channel(str(peak_channel))
                    if peak_channel is not None
                    else ""
                )
                if not _is_power_unit(unit):
                    problems.append(
                        f"功率Ha通道={peak_channel}单位={unit!r}，不是功率波形"
                    )
                if raw_reference:
                    if section not in {"关断过程", "开通"}:
                        problems.append("Pdmax 不应使用 Pmax 原始功率参考通道")
                    elif peak_y is None or not np.isclose(
                        float(peak_y),
                        float(raw_peak_kw) * 1000.0,
                        rtol=1e-10,
                        atol=1e-8,
                    ):
                        problems.append("Pmax Ha未绑定原始Vce×Ic峰值")
                else:
                    target_kw = (
                        result.turn_off.pmax
                        if section == "关断过程"
                        else result.turn_on.pmax
                        if section == "开通"
                        else result.reverse_recovery.pdmax
                    )
                    expected_power = mw.wave_plot.power_peak_in_window(
                        float(ta),
                        float(tb),
                        target_w=float(target_kw) * 1000.0,
                        prefer_abs=section == "反向恢复",
                        required_roles=expected_power_roles,
                        expected_power_w=expected_power_series_w,
                    )
                    if expected_power is None:
                        problems.append("A/B 内权威功率峰不可用")
                    else:
                        expected_power_channel, _peak_w, expected_y, _peak_t = expected_power
                        if peak_channel != expected_power_channel:
                            problems.append(
                                f"功率Ha通道={peak_channel}≠权威{expected_power_channel}"
                            )
                        if peak_y is None or not np.isclose(
                            float(peak_y), float(expected_y), rtol=1e-10, atol=1e-8
                        ):
                            problems.append("功率Ha未绑定A/B内权威峰值")
            detail = (
                f"A/B({interval_channel})={ta:.3f}/{tb:.3f}us"
                f"{peak_text}"
            )

        elif name == "串扰电压":
            c = calls.get("enable_crosstalk_interaction")
            if c is None:
                if not profile.vge_other or result.is_metric_unavailable(section, name):
                    record(section, name, "INFO", "无对管门极通道，串扰电压不可用")
                    continue
                record(section, name, "FAIL", "未触发 enable_crosstalk_interaction")
                continue
            b = c["bound"]
            ta = float(b["start_t_us"])
            tb = float(b["end_t_us"])
            check_time(ta, "A")
            check_time(tb, "B")
            if not ta < tb:
                problems.append(f"串扰A({ta:.6f})应早于B({tb:.6f})")
            crosstalk_display_problems = []
            if "vge_other" in chan:
                indices = result.segments.turn_off if section == "关断过程" else result.segments.turn_on
                crosstalk_display_problems = _crosstalk_cursor_display_problems(
                    t, chan["vge_other"], indices, ta, tb
                )
                problems.extend(crosstalk_display_problems)
            horizontal = calls.get("set_interval_minmax_horizontal")
            if horizontal is None:
                problems.append("串扰电压缺少 Ha/Hb 最大最小参考线")
                minmax_text = "missing"
            else:
                hb = horizontal["bound"]
                h_channel = hb.get("channel")
                y_min = hb.get("y_min")
                y_max = hb.get("y_max")
                check_channel(h_channel, "vge_other", "串扰Ha/Hb")
                if y_min is None or y_max is None:
                    problems.append("串扰 Ha/Hb 数值缺失")
                else:
                    check_level(float(y_min), "vge_other", "Hb", (ta, tb))
                    check_level(float(y_max), "vge_other", "Ha", (ta, tb))
                    cs = result.turn_off if section == "关断过程" else result.turn_on
                    if not np.isclose(
                        float(y_min), float(cs.crosstalk_vmin), rtol=1e-10, atol=1e-9
                    ):
                        problems.append("串扰 Hb 未绑定结果最小值")
                    if not np.isclose(
                        float(y_max), float(cs.crosstalk_vmax), rtol=1e-10, atol=1e-9
                    ):
                        problems.append("串扰 Ha 未绑定结果最大值")
                minmax_text = f"Ha/Hb={y_max}/{y_min}"
            if str(getattr(mw.wave_plot, "_active_channel", "")) != "vge_other":
                problems.append("串扰 A/B/Ha/Hb 未绑定 vge_other 活动通道")
            detail = (
                f"ch=vge_other A={ta:.3f} B={tb:.3f} {minmax_text}"
            )

        elif (section, name) in IEC_TIMING_CURSOR_ROLES:
            expected_endpoint_channels = IEC_TIMING_ENDPOINT_CHANNELS[(section, name)]
            interval_call = calls.get("enable_interval_interaction")
            if interval_call is None:
                record(section, name, "FAIL", "IEC 时间参数未触发 A/B 区间交互")
                continue
            ib = interval_call["bound"]
            ta = float(ib["start_t_us"])
            tb = float(ib["end_t_us"])
            timing_interval = mw._iec_timing_interval_us(section, name)
            if timing_interval is not None:
                timing_segment = (
                    _idx(t, min(float(timing_interval[0]), float(timing_interval[1]))),
                    _idx(t, max(float(timing_interval[0]), float(timing_interval[1]))),
                )
            else:
                timing_segment = (s0, s1)
            check_time(ta, "A", timing_segment)
            check_time(tb, "B", timing_segment)
            endpoint_channels = IEC_TIMING_ENDPOINT_CHANNELS[(section, name)]
            if endpoint_channels[0] == endpoint_channels[1] and not ta < tb:
                problems.append(f"IEC时间A({ta:.6f})应早于B({tb:.6f})")
            problems.extend(
                _ab_role_binding_problems(
                    ta,
                    tb,
                    timing_interval,
                    role_text=IEC_TIMING_CURSOR_ROLES[(section, name)],
                )
            )
            timing_value = (
                {
                    "Toff": result.turn_off.toff,
                    "Td_off": result.turn_off.td_off,
                    "Tf": result.turn_off.tf,
                }.get(name)
                if section == "关断过程"
                else {
                    "Ton": result.turn_on.ton,
                    "Td_on": result.turn_on.td_on,
                    "Tr": result.turn_on.tr,
                }.get(name)
            )
            duration_ns = abs(tb - ta) * 1e3
            if timing_value is None or not _short_values_close(
                float(timing_value), duration_ns, floor=1e-6
            ):
                problems.append(
                    f"IEC时间结果/B-A={timing_value!r}/{duration_ns:.9g}ns"
                )
            detail = (
                f"A={ta:.6f} B={tb:.6f}us "
                f"roles={IEC_TIMING_CURSOR_ROLES[(section, name)]}"
            )

        else:  # Ic/Vce/Vrr 最大值卡；端点按各参数的物理范围绑定。
            expected = GENERIC_MAX_CURSOR_CHANNELS.get(name)
            if expected is None:
                record(section, name, "FAIL", "审计矩阵存在未覆盖参数卡")
                continue
            expected_endpoint_channels = GENERIC_MAX_ENDPOINT_CHANNELS.get(
                (section, name)
            )
            if expected_endpoint_channels is None:
                record(section, name, "FAIL", "最大值端点通道矩阵存在未覆盖参数卡")
                continue
            interval_call = calls.get("enable_interval_interaction")
            if interval_call is None:
                record(section, name, "FAIL", "最大值参数未触发 A/B 区间交互")
                continue
            ib = interval_call["bound"]
            ta = float(ib["start_t_us"])
            tb = float(ib["end_t_us"])
            if not ta < tb:
                problems.append(f"最大值A({ta:.6f})应早于B({tb:.6f})")
            problems.extend(
                _ab_role_binding_problems(
                    ta,
                    tb,
                    mw._parameter_interval_us(section, name),
                    role_text=DPT_PARAMETER_CURSOR_ROLES[(section, name)],
                )
            )
            check_channel(ib.get("channel"), expected, "A/B")

            peak = calls.get("set_interval_peak_horizontal")
            if peak is None:
                problems.append("最大值参数缺少 Ha 峰值参考线")
                peak_y = None
                peak_ch = None
                win = (ta, tb)
            else:
                b = peak["bound"]
                peak_y = b.get("y")
                peak_ch = b.get("channel")
                win = (
                    (float(b["t0_us"]), float(b["t1_us"]))
                    if b.get("t0_us") is not None and b.get("t1_us") is not None
                    else (ta, tb)
                )
                check_channel(peak_ch, expected, "Ha峰")
                if peak_y is None:
                    problems.append("最大值参数 Ha 数值缺失")
                else:
                    check_level(float(peak_y), expected, "Ha峰值", win)

            base = calls.get("set_interval_base_horizontal")
            min_y = None
            if base is None:
                problems.append("最大值参数缺少 Hb 稳定平台参考线")
            else:
                bb = base["bound"]
                min_y = bb.get("y")
                min_ch = bb.get("channel")
                check_channel(min_ch, expected, "Hb稳定平台")
                if min_y is None:
                    problems.append("最大值参数 Hb 数值缺失")
                else:
                    check_level(float(min_y), expected, "Hb稳定平台", (ta, tb))
            i0 = max(0, min(_idx(t, min(ta, tb)), len(t) - 1))
            i1 = max(i0, min(_idx(t, max(ta, tb)), len(t) - 1))
            default_peak_point = mw._default_extreme_peak_point(section, name)
            expected_peak = (
                None if default_peak_point is None else float(default_peak_point[1])
            )
            expected_base = mw._secondary_y_for_param(section, name, i0, i1)
            if (
                peak_y is not None
                and expected_peak is not None
                and not np.isclose(
                    float(peak_y), float(expected_peak), rtol=1e-10, atol=1e-8
                )
            ):
                problems.append(
                    f"Ha={float(peak_y):.9g}≠{expected}提取极值{float(expected_peak):.9g}"
                )
            if (
                min_y is not None
                and expected_base is not None
                and not np.isclose(
                    float(min_y), float(expected_base), rtol=1e-10, atol=1e-8
                )
            ):
                problems.append(
                    f"Hb={float(min_y):.9g}≠{expected}稳定平台{float(expected_base):.9g}"
                )

            stable_context = None
            if (section, name) == ("关断过程", "Vce_off_max"):
                stable_context = mw._turn_off_vce_stable_cursor_context()
            elif (section, name) == ("开通", "Ic_on_max"):
                stable_context = mw._turn_on_ic_on_max_cursor_context()
            elif (section, name) == ("开通", "Vce_on_max"):
                stable_context = mw._turn_on_vce_on_max_cursor_context()
            elif (section, name) == ("反向恢复", "Vrr"):
                stable_context = mw._rr_vrr_cursor_context()
                if stable_context is None:
                    problems.append("Vrr 缺少完整 Base/Top 稳定带证据")
                else:
                    a_idx, b_idx, _top = stable_context
                    slope = result.dvdt_contexts[("反向恢复", "dv/dt")]
                    span = max(abs(slope.top_v - slope.base_v), 1.0)
                    width = max(8, int(round(200e-9 / max(bundle.dt, 1e-15))))
                    for label, index, level in (
                        ("A", a_idx, slope.base_v), ("B", b_idx, slope.top_v)
                    ):
                        start = max(0, index - width // 2)
                        band = np.abs(chan["v_diode"][start : start + width])
                        if len(band) != width or not np.all(np.isfinite(band)):
                            problems.append(f"Vrr {label}缺少完整有限值稳定带")
                            continue
                        p05, p95 = np.percentile(band, [5, 95])
                        if (
                            p95 - p05 > 0.10 * span
                            or abs(0.5 * (p05 + p95) - level) > 0.05 * span
                            or abs(np.median(band[:width//2]) - np.median(band[width//2:])) > 0.03 * span
                        ):
                            problems.append(f"Vrr {label}周围电压带仍有振荡或偏离稳定平台")
                    if b_idx >= result.segments.pulse2_off:
                        problems.append("Vrr B越过下一次关断")
            if stable_context is not None:
                expected_a_us = float(t[int(stable_context[0])] * 1e6)
                expected_b_us = float(t[int(stable_context[1])] * 1e6)
                if not _short_values_close(ta, expected_a_us, floor=1e-9):
                    problems.append(
                        f"{name} A={ta:.9f}us≠稳定平台点{expected_a_us:.9f}us"
                    )
                if not _short_values_close(tb, expected_b_us, floor=1e-9):
                    problems.append(
                        f"{name} B={tb:.9f}us≠稳定平台点{expected_b_us:.9f}us"
                    )
            if default_peak_point is not None:
                expected_peak_us = float(t[int(default_peak_point[0])] * 1e6)
                if not ta <= expected_peak_us <= tb:
                    problems.append(f"{name} 权威最大值不在稳定平台 A/B 范围内")
            if section == "开通" and name == "Vce_on_max" and stable_context is not None:
                a_idx, b_idx, base_v, top_v = stable_context
                span = max(abs(float(top_v) - float(base_v)), 1.0)
                if default_peak_point is not None:
                    peak_idx = int(default_peak_point[0])
                    if not a_idx < peak_idx < b_idx:
                        problems.append("Vce_on_max A必须在权威最大值左侧，B必须在其右侧")
                    if float(t[peak_idx] - t[a_idx]) > 200e-9 + 2.0 * bundle.dt:
                        problems.append("Vce_on_max A仍远离峰值左侧相邻平台")
                if b_idx >= result.segments.pulse2_off:
                    problems.append("Vce_on_max B越过下一次关断")
                # Inspect raw samples as well as matching the context's
                # timestamps: an isolated Base crossing must not pass as B.
                width = max(16, int(round(200e-9 / max(bundle.dt, 1e-15))))
                band = chan["vce"][max(0, b_idx - width // 2) : b_idx + width // 2]
                if len(band) >= width - 1:
                    p05, p95 = np.percentile(band, [5, 95])
                    if (
                        float(p95 - p05) > 0.10 * span
                        or abs(float((p05 + p95) * 0.5) - base_v) > 0.04 * span
                    ):
                        problems.append("Vce_on_max B周围完整电压带仍有振荡或偏离Base")
            if section == "关断过程" and name == "Ic_off_max":
                context = mw._turn_off_ic_off_max_cursor_context()
                if context is None:
                    problems.append("Ic_off_max 稳定 Base 光标上下文不可用")
                else:
                    expected_a_idx, expected_b_idx, expected_ic_base = context
                    expected_a_us = float(t[expected_a_idx] * 1e6)
                    expected_b_us = float(t[expected_b_idx] * 1e6)
                    if not _short_values_close(ta, expected_a_us, floor=1e-9):
                        problems.append(
                            f"Ic_off_max A={ta:.9f}us≠Vce Base稳定段"
                            f"{expected_a_us:.9f}us"
                        )
                    if not _short_values_close(tb, expected_b_us, floor=1e-9):
                        problems.append(
                            f"Ic_off_max B={tb:.9f}us≠Ic Base稳定段"
                            f"{expected_b_us:.9f}us"
                        )
                    vce_base, vce_top = turn_off_dvdt_base_top_levels(
                        t,
                        chan["vce"],
                        result.segments.turn_off[0],
                        result.segments.turn_off[1],
                    )
                    vce_span = max(abs(float(vce_top) - float(vce_base)), 1.0)
                    if abs(float(chan["vce"][expected_a_idx]) - float(vce_base)) > max(
                        1.0, 0.04 * vce_span
                    ):
                        problems.append("Ic_off_max A未落在Vce抬升前Base稳定带")
                    ic_span = max(
                        abs(float(result.turn_off.ic_off_max) - float(expected_ic_base)),
                        1.0,
                    )
                    if abs(float(cursor_ic[expected_b_idx]) - float(expected_ic_base)) > max(
                        1.0, 0.04 * ic_span
                    ):
                        problems.append("Ic_off_max B未落在抬升前Base稳定带")
                    if min_y is None or not _short_values_close(
                        float(min_y), float(expected_ic_base), floor=1e-8
                    ):
                        problems.append("Ic_off_max Hb未绑定Ic Base稳定值")
                    if peak_y is None or not _short_values_close(
                        abs(float(peak_y)),
                        float(result.turn_off.ic_off_max),
                        floor=1e-8,
                    ):
                        problems.append("Ic_off_max Ha未绑定提取结果最大值")
                    fall_window = turn_off_ic_fall_window(
                        t,
                        chan["vge"],
                        result.segments.turn_off[0],
                        result.segments.turn_off[1],
                        result.segments.pulse1_on,
                        result.segments.pulse1_off,
                        result.segments.pulse2_on,
                        bundle.dt,
                        mw.cfg,
                    )
                    fall0, fall1 = (
                        fall_window
                        if fall_window is not None
                        else result.segments.turn_off
                    )
                    authoritative_peak_idx = int(fall0) + int(
                        np.argmax(np.abs(chan["ic"][int(fall0) : int(fall1) + 1]))
                    )
                    authoritative_signed_peak = float(
                        np.copysign(
                            float(result.turn_off.ic_off_max),
                            float(cursor_ic[authoritative_peak_idx]) or 1.0,
                        )
                    )
                    actual_ha = (
                        None
                        if mw.wave_plot._h_cursor_a is None
                        else float(
                            mw.wave_plot._from_disp(
                                "ic", float(mw.wave_plot._h_cursor_a.value())
                            )
                        )
                    )
                    actual_hb = (
                        None
                        if mw.wave_plot._h_cursor_b is None
                        else float(
                            mw.wave_plot._from_disp(
                                "ic", float(mw.wave_plot._h_cursor_b.value())
                            )
                        )
                    )
                    if actual_ha is None or not _short_values_close(
                        actual_ha, authoritative_signed_peak, floor=1e-8
                    ):
                        problems.append("Ic_off_max 真实Ha未落在提取峰值电平")
                    if actual_hb is None or not _short_values_close(
                        actual_hb, float(expected_ic_base), floor=1e-8
                    ):
                        problems.append("Ic_off_max 真实Hb未落在Ic Base电平")
                    expected_peak_t_us = float(t[authoritative_peak_idx] * 1e6)
                    if (
                        mw.wave_plot._cursor_aux_t_us is None
                        or not _short_values_close(
                            float(mw.wave_plot._cursor_aux_t_us),
                            expected_peak_t_us,
                            floor=1e-9,
                        )
                    ):
                        problems.append("Ic_off_max 峰值标记未落在原提取峰值时刻")
            if section == "开通" and name == "Ic_on_max":
                context = mw._turn_on_ic_on_max_cursor_context()
                if context is None:
                    problems.append("Ic_on_max Base/Top 稳定光标上下文不可用")
                else:
                    expected_a_idx, expected_b_idx, expected_ic_base = context
                    hb_window, ha_window = turn_on_current_hb_ha_window_indices(
                        t,
                        cursor_ic,
                        result.segments.turn_on[0],
                        result.segments.turn_on[1],
                        bundle.dt,
                        event_end_idx=result.segments.pulse2_off,
                    )
                    hb0, hb1 = hb_window
                    ha0, ha1 = ha_window
                    if ha0 < 0 or ha1 < ha0:
                        problems.append("Ic_on_max 电流Top稳定带不可用")
                    else:
                        if default_peak_point is not None and int(default_peak_point[0]) <= hb0:
                            dt_s = max(float(bundle.dt), 1e-15)
                            hb1 = max(0, int(default_peak_point[0]) - max(1, int(round(30e-9 / dt_s))))
                            hb0 = max(0, hb1 - max(8, int(round(200e-9 / dt_s))))
                        if not hb0 <= expected_a_idx <= hb1:
                            problems.append("Ic_on_max A未落在Ic抬升前Base稳定带")
                        if expected_b_idx >= result.segments.pulse2_off:
                            problems.append("Ic_on_max B越过本次开通的下一关断事件")
                        hb_mid = _plateau_mid_without_isolated_spikes(
                            cursor_ic[hb0 : hb1 + 1]
                        )
                        ha_mid = _plateau_mid_without_isolated_spikes(
                            cursor_ic[ha0 : ha1 + 1]
                        )
                        ic_span = max(
                            abs(float(result.turn_on.ic_on_max) - float(expected_ic_base)),
                            1.0,
                        )
                        if abs(float(cursor_ic[expected_a_idx]) - float(hb_mid)) > max(
                            1.0, 0.04 * ic_span
                        ):
                            problems.append("Ic_on_max A未落在Ic抬升前Base稳定带")
                        if abs(float(cursor_ic[expected_b_idx]) - float(ha_mid)) > max(
                            1.0, 0.04 * ic_span
                        ):
                            problems.append("Ic_on_max B未落在电流震荡后Top稳定带")
                        # B may precede or follow the amplitude-reference
                        # window; independently inspect the complete band
                        # around the chosen time, not just a level crossing.
                        width = max(16, int(round(200e-9 / max(float(bundle.dt), 1e-15))))
                        band_lo = expected_b_idx - width // 2
                        band = cursor_ic[band_lo : band_lo + width]
                        top_band = cursor_ic[ha0 : ha1 + 1]
                        event_span = max(abs(float(ha_mid) - float(hb_mid)), 1.0)
                        noise = min(
                            float(np.percentile(top_band, 95) - np.percentile(top_band, 5)),
                            0.10 * event_span,
                        )
                        width_limit = max(1.35 * noise, 0.075 * event_span)
                        if len(band) == width and not ha0 <= expected_b_idx <= ha1:
                            p05, p95 = np.percentile(band, [5, 95])
                            if (
                                float(p95 - p05) > width_limit + 1e-9
                                or float(np.std(band)) > 0.5 * width_limit + 1e-9
                                or abs(float((p05 + p95) * 0.5) - float(ha_mid))
                                > max(0.5 * noise, 0.04 * event_span) + 1e-9
                            ):
                                problems.append("Ic_on_max B周围完整电流带仍有明显振荡或偏离Top")
                        if min_y is None or not _short_values_close(
                            float(min_y), float(expected_ic_base), floor=1e-8
                        ):
                            problems.append("Ic_on_max Hb未绑定Ic Base稳定值")
                        if peak_y is None or not _short_values_close(
                            abs(float(peak_y)),
                            float(result.turn_on.ic_on_max),
                            floor=1e-8,
                        ):
                            problems.append("Ic_on_max Ha未绑定提取结果最大值")
            peak_txt = "missing" if peak_y is None else f"{float(peak_y):.1f}"
            min_txt = "missing" if min_y is None else f"{float(min_y):.1f}"
            detail = (
                f"ch={expected} A={ta:.3f} B={tb:.3f} "
                f"Ha={peak_txt} Hb={min_txt}"
            )

        expected_binding = _captured_cursor_bindings(calls)
        if expected_endpoint_channels is not None:
            expected_a_channel, expected_b_channel = expected_endpoint_channels
            captured_a_channel = expected_binding.get("a_channel")
            captured_b_channel = expected_binding.get("b_channel")
            if captured_a_channel != expected_a_channel:
                problems.append(
                    f"参数卡调用A端点={captured_a_channel}≠期望{expected_a_channel}"
                )
            if captured_b_channel != expected_b_channel:
                problems.append(
                    f"参数卡调用B端点={captured_b_channel}≠期望{expected_b_channel}"
                )
            actual_a_channel = mw.wave_plot._cursor_endpoint_channel("a")
            actual_b_channel = mw.wave_plot._cursor_endpoint_channel("b")
            if actual_a_channel != expected_a_channel:
                problems.append(
                    f"参数卡真实A端点={actual_a_channel}≠期望{expected_a_channel}"
                )
            if actual_b_channel != expected_b_channel:
                problems.append(
                    f"参数卡真实B端点={actual_b_channel}≠期望{expected_b_channel}"
                )
            if mw.wave_plot._cursor_a is not None:
                check_endpoint_waveform(
                    "A",
                    str(expected_a_channel),
                    float(mw.wave_plot._cursor_a.value()),
                )
            if mw.wave_plot._cursor_b is not None:
                check_endpoint_waveform(
                    "B",
                    str(expected_b_channel),
                    float(mw.wave_plot._cursor_b.value()),
                )
            problems.extend(
                _audit_waveform_marker_bindings(
                    mw.wave_plot,
                    (str(expected_a_channel), str(expected_b_channel)),
                )
            )
        expected_a = expected_binding.get("a_us")
        expected_b = expected_binding.get("b_us")
        if expected_a is None or expected_b is None:
            problems.append("参数卡捕获路径未声明真实 A/B 绑定")
        elif mw.wave_plot._cursor_a is None or mw.wave_plot._cursor_b is None:
            problems.append("参数卡真实 A/B 光标缺失")
        else:
            actual_a = float(mw.wave_plot._cursor_a.value())
            actual_b = float(mw.wave_plot._cursor_b.value())
            if mw.wave_plot.cursor_type() in {"vertical", "both", "waveform"}:
                if not mw.wave_plot._cursor_a.isVisible():
                    problems.append("参数卡真实A光标被上一不可用卡状态隐藏")
                if not mw.wave_plot._cursor_b.isVisible():
                    problems.append("参数卡真实B光标被上一不可用卡状态隐藏")
            if not _short_values_close(actual_a, float(expected_a), floor=1e-7):
                problems.append(
                    f"真实A={actual_a:.9f}us≠卡片A={float(expected_a):.9f}us"
                )
            if not _short_values_close(actual_b, float(expected_b), floor=1e-7):
                problems.append(
                    f"真实B={actual_b:.9f}us≠卡片B={float(expected_b):.9f}us"
                )
        for role, cursor_attr in (("ha", "_h_cursor_a"), ("hb", "_h_cursor_b")):
            expected_horizontal = expected_binding.get(role)
            if expected_horizontal is None:
                continue
            expected_level, expected_channel = expected_horizontal
            horizontal = getattr(mw.wave_plot, cursor_attr, None)
            if expected_level is None or not expected_channel:
                problems.append(f"参数卡 {role.upper()} 绑定声明不完整")
            elif horizontal is None:
                problems.append(f"参数卡真实 {role.upper()} 光标缺失")
            else:
                actual_level = float(
                    mw.wave_plot._from_disp(
                        str(expected_channel), float(horizontal.value())
                    )
                )
                if not _short_values_close(
                    actual_level,
                    float(expected_level),
                    floor=1e-4,
                ):
                    problems.append(
                        f"真实{role.upper()}({expected_channel})={actual_level:.9g}"
                        f"≠卡片绑定{float(expected_level):.9g}"
                    )

        if expected_horizontal_bindings is None:
            problems.append("参数卡缺少 Ha/Hb 通道审计矩阵")
        else:
            for role, expected_horizontal in zip(
                ("ha", "hb"), expected_horizontal_bindings, strict=True
            ):
                expected_channel, expected_valid = expected_horizontal
                actual_channel, actual_valid = mw.wave_plot._horizontal_cursor_binding(
                    role
                )
                if bool(actual_valid) != bool(expected_valid):
                    problems.append(
                        f"参数卡真实{role.upper()}有效性={actual_valid}"
                        f"≠期望{expected_valid}"
                    )
                elif expected_valid and actual_channel != expected_channel:
                    problems.append(
                        f"参数卡真实{role.upper()}通道={actual_channel}"
                        f"≠期望{expected_channel}"
                    )
                horizontal = getattr(
                    mw.wave_plot,
                    "_h_cursor_a" if role == "ha" else "_h_cursor_b",
                    None,
                )
                if (
                    mw.wave_plot.cursor_type() in {"horizontal", "both"}
                    and horizontal is not None
                    and bool(horizontal.isVisible()) != bool(expected_valid)
                ):
                    problems.append(
                        f"参数卡真实{role.upper()}可见性={horizontal.isVisible()}"
                        f"≠期望{expected_valid}"
                    )
                captured_horizontal = expected_binding.get(role)
                if expected_valid:
                    if captured_horizontal is None:
                        problems.append(
                            f"参数卡调用未声明{role.upper()}真实波形来源"
                        )
                    elif captured_horizontal[1] != expected_channel:
                        problems.append(
                            f"参数卡调用{role.upper()}通道={captured_horizontal[1]}"
                            f"≠期望{expected_channel}"
                        )

        captured_focus = _captured_parameter_focus(calls)
        if focus_only:
            # Everything above this point audits the parameter's extraction and
            # measurement semantics.  Keep those diagnostics in the normal
            # corpus run, but isolate this display-only mode to the requested
            # X-window composition and visual bindings.  Recheck every display
            # invariant explicitly after clearing semantic-only diagnostics so
            # a missing focus/A/B/binding cannot become a false OK.
            problems.clear()
            if name == "串扰电压":
                # This is a display-endpoint contract, not a calculation
                # diagnostic; focus-only audits must not discard it.
                problems.extend(crosstalk_display_problems)
            if mw.result is not result:
                problems.append("参数点击替换了 result 对象")
            if (
                result_before_focus is not None
                and _audit_state_snapshot(mw.result) != result_before_focus
            ):
                problems.append("参数点击改变了 result 内容")
            if captured_focus is None:
                problems.append("参数卡未调用 focus_parameter_window_us")

            cursor_a_item = mw.wave_plot._cursor_a
            cursor_b_item = mw.wave_plot._cursor_b
            if cursor_a_item is None or cursor_b_item is None:
                problems.append("参数取景缺少真实 A/B 光标")
            else:
                if not cursor_a_item.isVisible():
                    problems.append("参数取景真实 A 光标不可见")
                if not cursor_b_item.isVisible():
                    problems.append("参数取景真实 B 光标不可见")
                expected_a = expected_binding.get("a_us")
                expected_b = expected_binding.get("b_us")
                if expected_a is None or expected_b is None:
                    problems.append("参数取景调用未声明真实 A/B")
                else:
                    if not _short_values_close(
                        float(cursor_a_item.value()), float(expected_a), floor=1e-7
                    ):
                        problems.append("参数取景真实 A 与交互调用不一致")
                    if not _short_values_close(
                        float(cursor_b_item.value()), float(expected_b), floor=1e-7
                    ):
                        problems.append("参数取景真实 B 与交互调用不一致")

            if expected_endpoint_channels is None:
                problems.append("参数取景缺少 A/B 通道审计矩阵")
            else:
                for role, expected_channel in zip(
                    ("a", "b"), expected_endpoint_channels, strict=True
                ):
                    actual_channel = mw.wave_plot._cursor_endpoint_channel(role)
                    if actual_channel is None:
                        problems.append(f"参数取景 {role.upper()} 未绑定波形")
                    elif actual_channel != expected_channel:
                        problems.append(
                            f"参数取景 {role.upper()} 通道={actual_channel}"
                            f"≠期望{expected_channel}"
                        )
                problems.extend(
                    _audit_waveform_marker_bindings(
                        mw.wave_plot,
                        (
                            str(expected_endpoint_channels[0]),
                            str(expected_endpoint_channels[1]),
                        ),
                    )
                )

            if expected_horizontal_bindings is None:
                problems.append("参数取景缺少 Ha/Hb 通道审计矩阵")
            else:
                for role, expected_horizontal in zip(
                    ("ha", "hb"), expected_horizontal_bindings, strict=True
                ):
                    expected_channel, expected_valid = expected_horizontal
                    actual_channel, actual_valid = (
                        mw.wave_plot._horizontal_cursor_binding(role)
                    )
                    if bool(actual_valid) != bool(expected_valid):
                        problems.append(
                            f"参数取景 {role.upper()} 有效性={actual_valid}"
                            f"≠期望{expected_valid}"
                        )
                    elif expected_valid and actual_channel != expected_channel:
                        problems.append(
                            f"参数取景 {role.upper()} 通道={actual_channel}"
                            f"≠期望{expected_channel}"
                        )

        if (section, name) == ("关断过程", "Ic_off_max"):
            didt_context = result.didt_contexts.get(("关断过程", "di/dt"))
            base_window = getattr(didt_context, "base_window", None)
            actual_b_item = mw.wave_plot._cursor_b
            if base_window is not None and actual_b_item is not None:
                b0, b1 = (int(base_window[0]), int(base_window[1]))
                b0 = max(0, min(b0, len(cursor_ic) - 1))
                b1 = max(b0, min(b1, len(cursor_ic) - 1))
                signed_base = float(
                    _plateau_mid_without_isolated_spikes(cursor_ic[b0 : b1 + 1])
                )
                actual_b_us = float(actual_b_item.value())
                actual_b_idx = int(
                    np.searchsorted(t, actual_b_us * 1e-6, side="left")
                )
                actual_b_idx = max(0, min(actual_b_idx, len(t) - 1))
                # 用户 2026-10-16 拍板「② 关断 B 落点 = 甲 · 稳定抬升前 Base」：
                # 独立判据改为「B 必须落在 Vce/Ic 主抬升前的稳定 Base 窗内，
                # 且该处 Ic 电平等于本卡发布的 Base 稳定值」，不再要求 B 位于
                # Ic 主下降后的首个稳定带。旧的「下降后首个完整 Base 稳定窗」
                # 不可满足情形（历史 15 条 FAIL）随之不再计为 FAIL。
                span = max(
                    abs(float(result.turn_off.ic_off_max) - signed_base), 1.0
                )
                if not b0 <= actual_b_idx <= b1:
                    problems.append(
                        "Ic_off_max B未落在抬升前Base稳定窗: "
                        f"实际={actual_b_us:.6f}us "
                        f"窗=[{float(t[b0]) * 1e6:.6f},{float(t[b1]) * 1e6:.6f}]us"
                    )
                elif abs(float(cursor_ic[actual_b_idx]) - signed_base) > max(
                    1.0, 0.04 * span
                ):
                    problems.append(
                        "Ic_off_max B处Ic偏离抬升前Base稳定值: "
                        f"{float(cursor_ic[actual_b_idx]):.3f}A "
                        f"vs {signed_base:.3f}A"
                    )

        # Real-operation guard: users single/double-click other channels to
        # raise or highlight traces while inspecting a parameter.  That visual
        # gesture must not steal A/B/Ha/Hb from the parameter's logical source.
        before_a_channel = mw.wave_plot._cursor_endpoint_channel("a")
        before_b_channel = mw.wave_plot._cursor_endpoint_channel("b")
        before_ha_binding = mw.wave_plot._horizontal_cursor_binding("ha")
        before_hb_binding = mw.wave_plot._horizontal_cursor_binding("hb")
        before_active_channel = str(getattr(mw.wave_plot, "_active_channel", ""))
        bound_display_keys = {
            mw.wave_plot._display_key_for_channel(channel)
            for channel in (
                before_a_channel,
                before_b_channel,
                before_ha_binding[0] if before_ha_binding[1] else None,
                before_hb_binding[0] if before_hb_binding[1] else None,
                before_active_channel or None,
            )
            if channel
        }
        unrelated_trace = next(
            (
                key
                for key in mw.wave_plot._trace_items
                if key not in mw.wave_plot._hidden_channels
                and key not in bound_display_keys
            ),
            None,
        )
        if unrelated_trace is not None:
            try:
                mw.wave_plot._raise_trace(unrelated_trace)
                mw.wave_plot._highlight_trace(unrelated_trace)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"异通道高亮异常: {exc!r}")
            after_a_channel = mw.wave_plot._cursor_endpoint_channel("a")
            after_b_channel = mw.wave_plot._cursor_endpoint_channel("b")
            after_ha_binding = mw.wave_plot._horizontal_cursor_binding("ha")
            after_hb_binding = mw.wave_plot._horizontal_cursor_binding("hb")
            after_active_channel = str(
                getattr(mw.wave_plot, "_active_channel", "")
            )
            if after_a_channel != before_a_channel:
                problems.append(
                    f"异通道高亮后A源={after_a_channel}≠原{before_a_channel}"
                )
            if after_b_channel != before_b_channel:
                problems.append(
                    f"异通道高亮后B源={after_b_channel}≠原{before_b_channel}"
                )
            if after_ha_binding != before_ha_binding:
                problems.append(
                    f"异通道高亮后Ha绑定={after_ha_binding}≠原{before_ha_binding}"
                )
            if after_hb_binding != before_hb_binding:
                problems.append(
                    f"异通道高亮后Hb绑定={after_hb_binding}≠原{before_hb_binding}"
                )
            if after_active_channel != before_active_channel:
                problems.append(
                    f"异通道高亮后活动源={after_active_channel}≠原{before_active_channel}"
                )
        if (
            focus_only
            and result_before_focus is not None
            and _audit_state_snapshot(mw.result) != result_before_focus
        ):
            problems.append("异通道高亮后改变了 result 内容")
        if focus_only and mw.result is not result:
            problems.append("异通道高亮后替换了 result 对象")

        xr = mw.wave_plot.current_x_range_us()
        full_x = mw.wave_plot._full_x_range
        if xr is None or full_x is None:
            problems.append("参数局部视窗不可用")
        else:
            x0, x1 = (float(xr[0]), float(xr[1]))
            full_x0, full_x1 = (float(full_x[0]), float(full_x[1]))
            span = x1 - x0
            full_span = full_x1 - full_x0
            if x0 < full_x0 - 1e-6 or x1 > full_x1 + 1e-6:
                problems.append(
                    f"视窗[{x0:.3f},{x1:.3f}]越出完整范围"
                    f"[{full_x0:.3f},{full_x1:.3f}]"
                )
            if span < min(2.0, full_span) - 0.02:
                problems.append(f"局部视窗过窄: {span:.3f}us")
            if captured_focus is not None:
                (
                    anchor_us,
                    required_times_us,
                    expected_fraction,
                    prefer_right_room,
                    _composition_anchor_us,
                    _composition_balance_fraction,
                ) = _normalize_captured_parameter_focus(captured_focus)
                for required_us in required_times_us:
                    if required_us < x0 - 1e-6 or required_us > x1 + 1e-6:
                        problems.append(
                            f"focus 必需时刻={required_us:.3f} 不在视窗"
                            f"[{x0:.3f},{x1:.3f}]"
                        )
                geometry_problem = _parameter_focus_geometry_problem(
                    (x0, x1),
                    (full_x0, full_x1),
                    captured_focus,
                    minimum_span_us=_captured_parameter_minimum_span_us(calls),
                    parameter_key=(section, name),
                )
                if geometry_problem is not None:
                    problems.append(geometry_problem)
                focus_cursor_a = (
                    None
                    if mw.wave_plot._cursor_a is None
                    else float(mw.wave_plot._cursor_a.value())
                )
                focus_cursor_b = (
                    None
                    if mw.wave_plot._cursor_b is None
                    else float(mw.wave_plot._cursor_b.value())
                )
                primary_event_us = _authoritative_primary_event_us(
                    mw,
                    section,
                    name,
                    t,
                    chan,
                    result,
                    focus_cursor_a,
                    focus_cursor_b,
                )
                primary_problem = _parameter_primary_event_geometry_problem(
                    (x0, x1),
                    (full_x0, full_x1),
                    captured_focus,
                    primary_event_us,
                )
                if primary_problem is not None:
                    problems.append(primary_problem)
                detail += (
                    f" focus_anchor={anchor_us:.3f}"
                    f" required={required_times_us}"
                    f" right_priority={prefer_right_room}"
                )
                if primary_event_us is not None and np.isfinite(
                    float(primary_event_us)
                ):
                    detail += f" primary_raw={float(primary_event_us):.3f}"
                auxiliary_event_us = getattr(
                    mw.wave_plot, "_cursor_aux_t_us", None
                )
                if auxiliary_event_us is not None and np.isfinite(
                    float(auxiliary_event_us)
                ):
                    detail += f" primary_marker={float(auxiliary_event_us):.3f}"
            cursor_a = None
            cursor_b = None
            has_real_slope_ab = turn_off_slope_crossing_full is not False
            if (
                has_real_slope_ab
                and mw.wave_plot._cursor_a is not None
                and mw.wave_plot._cursor_b is not None
            ):
                cursor_a = float(mw.wave_plot._cursor_a.value())
                cursor_b = float(mw.wave_plot._cursor_b.value())
                if min(cursor_a, cursor_b) < x0 - 1e-6 or max(cursor_a, cursor_b) > x1 + 1e-6:
                    problems.append(
                        f"A/B={cursor_a:.3f}/{cursor_b:.3f} 不在视窗"
                        f"[{x0:.3f},{x1:.3f}]"
                    )
            expansion_problem = _unnecessary_ab_focus_expansion(
                section,
                name,
                (x0, x1),
                (full_x0, full_x1),
                captured_focus,
                cursor_a,
                cursor_b,
            )
            if expansion_problem is not None:
                problems.append(expansion_problem)
            detail += f" view=[{x0:.3f},{x1:.3f}]"

        status = "OK" if not problems else "FAIL"
        if problems:
            detail = detail + " | " + "; ".join(problems)
        record(section, name, status, detail)

    mw.close()
    return rows


def _selected_sample_waveforms(root: Path) -> list[Path]:
    discovered = discover_sample_waveforms(root)
    path_match = os.environ.get("DPT_VALIDATE_CURSOR_MATCH", "").strip().lower()
    if path_match:
        discovered = [
            path for path in discovered if path_match in str(path).lower()
        ]
    if os.environ.get("DPT_VALIDATE_SHORT_ONLY", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        discovered = [path for path in discovered if _is_short_circuit_sample(path)]
    if os.environ.get("DPT_VALIDATE_DPT_ONLY", "").lower() in {
        "1",
        "true",
        "yes",
    }:
        discovered = [path for path in discovered if not _is_short_circuit_sample(path)]
    if os.environ.get("DPT_VALIDATE_ALL_CURSORS", "").lower() in {"1", "true", "yes"}:
        # Full mode is a corpus audit: include both DPT and every short-circuit
        # sample.  Offset/limit continue to provide deterministic pagination.
        paths = discovered
    else:
        paths = [path for path in discovered if not _is_short_circuit_sample(path)]
        selected: list[Path] = []
        for fragments in DEFAULT_SAMPLE_FRAGMENTS:
            for path in paths:
                text = str(path)
                if all(fragment in text for fragment in fragments):
                    selected.append(path)
                    break
        paths = selected or paths[: min(8, len(paths))]

    try:
        offset = max(0, int(os.environ.get("DPT_VALIDATE_CURSOR_OFFSET", "0")))
    except ValueError:
        offset = 0
    try:
        limit = int(os.environ.get("DPT_VALIDATE_CURSOR_LIMIT", "0"))
    except ValueError:
        limit = 0
    if limit > 0:
        return paths[offset : offset + limit]
    return paths[offset:]


def run_all() -> list[tuple]:
    """对选定示例文件跑光标审计，返回 (file, section, name, status, detail) 行。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    from dpt_extractor.gui import main_window as main_window_module

    # Corpus audits load many real files through the production path, but must
    # not replace the user's persisted "last opened TSS" with the final audit
    # sample.  Patch only this validator process; production behavior remains
    # unchanged.
    original_set_last_open_path = main_window_module.set_last_open_path
    original_app_settings = main_window_module._app_settings
    MainWindow = main_window_module.MainWindow

    app = QApplication.instance() or QApplication([])
    all_rows: list[tuple] = []
    with tempfile.TemporaryDirectory() as tmp:
        settings_path = Path(tmp) / "DPTExtractor.ini"
        main_window_module.set_last_open_path = lambda _path: None
        main_window_module._app_settings = lambda: QSettings(
            str(settings_path),
            QSettings.Format.IniFormat,
        )
        try:
            sample_root_text = os.environ.get("DPT_VALIDATE_SAMPLE_ROOT", "").strip()
            sample_root = Path(sample_root_text) if sample_root_text else ROOT
            if not sample_root.is_dir():
                raise FileNotFoundError(f"TSS 语料根目录不存在: {sample_root}")
            for path in _selected_sample_waveforms(sample_root):
                if _is_short_circuit_sample(path):
                    if os.environ.get("DPT_VALIDATE_CURSOR_METRIC", "").strip():
                        continue
                    all_rows.extend(
                        audit_short_circuit_file(MainWindow, QApplication, app, path)
                    )
                else:
                    all_rows.extend(audit_file(MainWindow, QApplication, app, path))
        finally:
            main_window_module.set_last_open_path = original_set_last_open_path
            main_window_module._app_settings = original_app_settings
    return all_rows


def main() -> None:
    all_rows = run_all()
    fails = [r for r in all_rows if r[3] == "FAIL"]
    by_file = _group_rows_by_sample(all_rows)

    summary_only = os.environ.get(
        "DPT_VALIDATE_CURSOR_SUMMARY_ONLY", ""
    ).lower() in {"1", "true", "yes"}
    if not summary_only or fails:
        for fn, rows in by_file.items():
            n_ok = sum(1 for r in rows if r[3] == "OK")
            n_fail = sum(1 for r in rows if r[3] == "FAIL")
            print(f"\n=== {fn}  OK={n_ok} FAIL={n_fail} ===")
            for _f, section, name, status, detail in rows:
                mark = {"OK": "OK ", "FAIL": "FAIL", "INFO": "INFO"}.get(
                    status, status
                )
                print(f"  [{mark}] {section}/{name}: {detail}")

    ok_count = sum(1 for row in all_rows if row[3] == "OK")
    info_count = sum(1 for row in all_rows if row[3] == "INFO")
    print(
        "\nSUMMARY "
        f"files={len(by_file)} items={len(all_rows)} "
        f"OK={ok_count} INFO={info_count} FAIL={len(fails)}"
    )
    if fails:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
