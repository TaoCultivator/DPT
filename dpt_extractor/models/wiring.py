"""接线拓扑识别：用示波器数学通道恒等式判定 CH3/CH4 的物理含义。

文件名与目录名是人为标注，会随测试集迁徙而漂移；示波器里 MATH 通道的算式
才是硬件事实。本模块只认恒等式，不认标签，也绝不按目录名猜：

- ``MATH1 == CH3 + CH4``：CH3 是反向恢复支路电流 Irr，CH4 是电感电流 IL，
  MATH1 即总电流 Ic。对应上桥接法（``ic_from_sum_irr_il=True``）。
- ``MATH1 == CH3 - CH4``：CH3 是实测总电流 Ic，CH4 是 IL，MATH1 是 Irr。
  对应下桥接法（``irr_from_ic_minus_il=True``）。
- 没有 CH4 且 CH3 标签为 Ic：CH3 直读总电流，对应短路接法。

恒等式不成立也算一种结论（``unknown``），不能当成通过——未知不等于正确。

最危险的一类错配是**静默数值错误**：短路接法把 CH3(Irr) 当成 Ic 直读，
程序能跑通、不抛异常，只是每个数值都错。因此本模块把"声明与接线不符"
判为硬错误，由调用方决定是抛异常还是降级为警告。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型提示
    from dpt_extractor.models.bridge_profile import BridgeProfile
    from dpt_extractor.models.waveform import WaveformBundle

TOPOLOGY_DPT_UPPER_SUM = "dpt_upper_sum"
TOPOLOGY_DPT_LOWER_SUB = "dpt_lower_sub"
TOPOLOGY_DIRECT_IC = "direct_ic"
TOPOLOGY_AMBIGUOUS = "ambiguous"
TOPOLOGY_UNKNOWN = "unknown"

TOPOLOGY_LABELS: dict[str, str] = {
    TOPOLOGY_DPT_UPPER_SUM: "上桥接法（CH3=Irr，CH4=IL，Ic=Irr+IL）",
    TOPOLOGY_DPT_LOWER_SUB: "下桥接法（CH3=Ic，CH4=IL，Irr=Ic-IL）",
    TOPOLOGY_DIRECT_IC: "直读接法（CH3 即总电流）",
    TOPOLOGY_AMBIGUOUS: "恒等式歧义（+CH4 与 -CH4 同时成立）",
    TOPOLOGY_UNKNOWN: "无法判定",
}

#: 恒等式相对容差（相对 p95 幅度）。
_IDENTITY_REL_TOL = 1e-9
#: 恒等式绝对容差下限，避免小信号下浮点噪声被当成不成立。
_IDENTITY_ABS_TOL = 1e-6


@dataclass(frozen=True)
class WiringReport:
    """一次接线识别的结果。字段保留原始证据，便于日志与回显。"""

    topology: str
    has_il: bool
    ch3_label: str = ""
    ch4_label: str = ""
    math1_label: str = ""
    residual: float | None = None
    scale: float = 0.0
    note: str = ""

    @property
    def label(self) -> str:
        return TOPOLOGY_LABELS.get(self.topology, self.topology)

    def to_dict(self) -> dict[str, object]:
        return {
            "topology": self.topology,
            "label": self.label,
            "has_il": self.has_il,
            "ch3_label": self.ch3_label,
            "ch4_label": self.ch4_label,
            "math1_label": self.math1_label,
            "residual": self.residual,
            "scale": self.scale,
            "note": self.note,
        }


def _p95_abs(values: np.ndarray | None) -> float:
    if values is None:
        return 0.0
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.0
    return float(np.percentile(np.abs(arr), 95.0))


def _max_abs_diff(left: np.ndarray, right: np.ndarray) -> float:
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.shape != b.shape:
        return float("inf")
    diff = np.abs(a - b)
    diff = diff[np.isfinite(diff)]
    return float(diff.max()) if diff.size else 0.0


def detect_wiring(bundle: "WaveformBundle") -> WiringReport:
    """按原始通道数据判定接线拓扑。

    刻意绕开 ``bundle.maybe_get()``：那个接口会按显示/源极性做一次翻转，
    是给测量口径用的；恒等式校验必须用示波器存下来的原始数值。
    """
    meta = getattr(bundle, "meta", None)
    labels: dict[str, str] = dict(getattr(meta, "channel_labels", None) or {})
    channels: dict[str, np.ndarray] = dict(getattr(bundle, "channels", None) or {})

    ch3 = channels.get("CH3")
    ch4 = channels.get("CH4")
    math1 = channels.get("MATH1")

    ch3_label = str(labels.get("CH3", "") or "").strip()
    ch4_label = str(labels.get("CH4", "") or "").strip()
    m1_label = str(labels.get("MATH1", "") or "").strip()
    has_il = ch4 is not None

    if ch3 is None or math1 is None:
        missing = "CH3" if ch3 is None else "MATH1"
        return WiringReport(
            TOPOLOGY_UNKNOWN,
            has_il,
            ch3_label,
            ch4_label,
            m1_label,
            note=f"缺少 {missing}，无法校验恒等式",
        )

    if not has_il:
        # 没有 IL 就无法合成 Irr+IL，也不存在 Ic-IL，只剩直读一种可能。
        lower = ch3_label.lower()
        if lower and lower != "ic":
            return WiringReport(
                TOPOLOGY_DIRECT_IC,
                False,
                ch3_label,
                ch4_label,
                m1_label,
                note=f"无 CH4(IL)，但 CH3 标签为 {ch3_label}；直读接法下该通道将被当作总电流",
            )
        return WiringReport(TOPOLOGY_DIRECT_IC, False, ch3_label, ch4_label, m1_label)

    scale = max(_p95_abs(ch3), _p95_abs(ch4), _p95_abs(math1))
    tol = max(_IDENTITY_ABS_TOL, _IDENTITY_REL_TOL * scale)

    r_sum = _max_abs_diff(np.asarray(ch3) + np.asarray(ch4), math1)
    r_sub = _max_abs_diff(np.asarray(ch3) - np.asarray(ch4), math1)
    sum_ok = r_sum <= tol
    sub_ok = r_sub <= tol

    if sum_ok and sub_ok:
        # CH4 恒为零（或数据退化）时两种接法无法区分，交给标签消歧。
        lower = ch3_label.lower()
        if lower == "irr":
            return WiringReport(
                TOPOLOGY_DPT_UPPER_SUM, True, ch3_label, ch4_label, m1_label,
                residual=r_sum, scale=scale,
                note="CH4 近似为零，按标签 CH3=Irr 判为上桥接法",
            )
        if lower == "ic":
            return WiringReport(
                TOPOLOGY_DPT_LOWER_SUB, True, ch3_label, ch4_label, m1_label,
                residual=r_sub, scale=scale,
                note="CH4 近似为零，按标签 CH3=Ic 判为下桥接法",
            )
        return WiringReport(
            TOPOLOGY_AMBIGUOUS, True, ch3_label, ch4_label, m1_label,
            residual=max(r_sum, r_sub), scale=scale,
            note="恒等式两种接法同时成立且标签无法消歧",
        )

    if sum_ok:
        return WiringReport(
            TOPOLOGY_DPT_UPPER_SUM, True, ch3_label, ch4_label, m1_label,
            residual=r_sum, scale=scale,
        )
    if sub_ok:
        return WiringReport(
            TOPOLOGY_DPT_LOWER_SUB, True, ch3_label, ch4_label, m1_label,
            residual=r_sub, scale=scale,
        )

    return WiringReport(
        TOPOLOGY_UNKNOWN, True, ch3_label, ch4_label, m1_label,
        residual=min(r_sum, r_sub), scale=scale,
        note="恒等式均不成立，无法判定接线；请核对 CH3/CH4/MATH1 是否同一批次采集",
    )


def _ref_targets_ch3(ref: str) -> bool:
    return str(ref or "").strip().lstrip("+-").upper().startswith("CH3")


def validate_profile_against_wiring(
    profile: "BridgeProfile",
    report: WiringReport,
) -> tuple[bool, str, str]:
    """核对 profile 声明与接线事实是否自洽。

    返回 ``(ok, severity, reason)``，``severity`` 取 ``ok`` / ``fatal`` / ``mismatch``：

    - ``fatal``：数据里根本没有 profile 需要的通道，提取必然失败。
    - ``mismatch``：通道存在但语义对不上，**能跑通而数值错**，最需要拦。
    """
    ic_sum = bool(getattr(profile, "ic_from_sum_irr_il", False))
    irr_sub = bool(getattr(profile, "irr_from_ic_minus_il", False))
    ic_ref = str(getattr(profile, "ic", "") or "")
    irr_ref = str(getattr(profile, "irr", "") or "")

    # 前置：声明走 Irr+IL 合成，但数据里没有 IL，无论恒等式如何都跑不动。
    if ic_sum and not report.has_il:
        return (
            False,
            "fatal",
            "当前 profile 用 Irr+IL 合成总电流（ic_from_sum_irr_il=True），"
            "但波形中没有 CH4(IL) 通道；请改用直读或短路 profile",
        )

    if report.topology == TOPOLOGY_DPT_UPPER_SUM:
        if ic_sum:
            return True, "ok", ""
        return (
            False,
            "mismatch",
            f"实测接线为{report.label}，CH3 是反向恢复电流 Irr；"
            f"当前 profile 却把 ic={ic_ref or '空'} 当总电流直读，会得到错误数值",
        )

    if report.topology == TOPOLOGY_DPT_LOWER_SUB:
        if ic_sum:
            return (
                False,
                "mismatch",
                f"实测接线为{report.label}，CH3 是总电流 Ic；"
                "当前 profile 却按 Irr+IL 合成总电流，方向相反",
            )
        if irr_sub or not irr_ref:
            return True, "ok", ""
        if _ref_targets_ch3(irr_ref):
            return (
                False,
                "mismatch",
                f"实测接线为{report.label}，CH3 是总电流 Ic；"
                "当前 profile 却把 CH3 映射为反向恢复电流 Irr",
            )
        return True, "ok", ""

    if report.topology == TOPOLOGY_DIRECT_IC:
        if ic_sum:
            return (
                False,
                "fatal",
                "波形无 CH4(IL)，但 profile 仍要求 Irr+IL 合成总电流",
            )
        if report.ch3_label and report.ch3_label.lower() != "ic" and _ref_targets_ch3(ic_ref):
            return (
                False,
                "mismatch",
                f"波形为直读接法，但 CH3 标签是 {report.ch3_label} 而非 Ic；"
                "当前 profile 把 CH3 当总电流读取，数值不可信",
            )
        if ic_ref and not _ref_targets_ch3(ic_ref):
            return (
                True,
                "ok",
                f"直读接法下 profile 的 Ic 映射为 {ic_ref}，未指向 CH3；请确认是否接错探头",
            )
        return True, "ok", ""

    # AMBIGUOUS / UNKNOWN：判据不足，不阻断，但把结论带出去让调用方决定。
    return True, "ok", report.note or "接线无法从数据判定，已跳过校验"