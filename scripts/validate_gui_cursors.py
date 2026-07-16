"""无界面光标-波形绑定校验：对代表性工况逐参数触发 GUI 交互，
回读 MainWindow 传给 wave_plot 的光标放置参数（绑定通道 / A/B 时刻 / Ha/Hb 电平），
断言每个数据光标落在正确波形的正确特征上，输出 OK/FAIL 矩阵。

以 UH 上桥为基准，重点暴露下桥（Irr=Ic−IL 为负、Vd 负偏）的极性类不兼容。
默认使用代表性样本以保证 GUI 子进程审计在单测超时内完成；设置
DPT_VALIDATE_ALL_CURSORS=1 可扫描所有示例 .tss。
"""
from __future__ import annotations

import os
import re
import sys
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
    PARAM_FOCUS_ANCHOR_FRACTION,
    _solve_parameter_x_window,
)
from dpt_extractor.models.waveform import (  # noqa: E402
    bundle_reverse_recovery_current,
    bundle_total_current,
)
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

SECTION_SEGMENT = {
    "关断过程": "turn_off",
    "开通": "turn_on",
    "反向恢复": "reverse_recovery",
}

DEFAULT_SAMPLE_FRAGMENTS = (
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
            "enable_trr_measure_interaction",
            "enable_turn_on_current_interaction",
            "enable_delta_vce_interaction",
            "enable_crosstalk_interaction",
            "enable_interval_interaction",
            "set_interval_peak_horizontal",
            "set_interval_base_horizontal",
        ):
            orig = getattr(wave_plot, meth)
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


def _captured_parameter_focus(
    calls: dict[str, dict],
) -> tuple[float, tuple[float, ...], float] | None:
    """Read the actual focus call used by the UI, without re-deriving its anchor."""
    call = calls.get("focus_parameter_window_us")
    if call is None:
        return None
    bound = call.get("bound", {})
    if "anchor_us" not in bound:
        return None
    required = tuple(float(value) for value in bound.get("required_times_us", ()))
    return (
        float(bound["anchor_us"]),
        required,
        float(bound.get("anchor_fraction", PARAM_FOCUS_ANCHOR_FRACTION)),
    )


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
    captured_focus: tuple[float, tuple[float, ...], float] | None,
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
    anchor_us, _implementation_required, anchor_fraction = captured_focus
    expected_x0, expected_x1 = _solve_parameter_x_window(
        full_range_us,
        anchor_us,
        (float(cursor_a_us), float(cursor_b_us)),
        anchor_fraction=anchor_fraction,
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
    return any(
        parts[index] == "wanglihui" and parts[index + 1] == "u"
        for index in range(len(parts) - 1)
    )


def _ensure_wanglihui_u_ch3_ui_inversion(mw, QApplication, path: Path) -> str:
    """Apply the wanglihui/U CH3 inversion through the same state path as the UI.

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


def audit_file(MainWindow, QApplication, app, path: Path) -> list[tuple]:
    sample_id = _sample_trace_id(path)
    mw = MainWindow()
    mw._load_file(str(path))
    if mw.bundle is None or mw.result is None or mw.result.segments is None:
        detail = mw.statusBar().currentMessage() if mw.statusBar() is not None else "参数未计算"
        mw.close()
        return [(sample_id, "加载", "自动提取", "INFO", detail)]
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
    t = bundle.t
    segs = result.segments
    chan = {
        "vce": bundle.get(profile.vce),
        "ic": bundle_total_current(bundle, profile),
        "irr": bundle_reverse_recovery_current(bundle, profile),
        "v_diode": bundle.get(profile.v_diode),
    }
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

    for section, name in INTERACTIVE_PARAMS:
        if result.single_pulse_mode and section in {"开通", "反向恢复"}:
            record(section, name, "INFO", "单脉冲模式不适用")
            continue
        seg_name = SECTION_SEGMENT[section]
        s0, s1 = seg_idx[seg_name]
        cap.reset()
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
        turn_off_slope_crossing_full: bool | None = None

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
            if win_us is not None:
                w0 = max(0, min(_idx(t, win_us[0]), len(t) - 1))
                w1 = max(w0 + 1, min(_idx(t, win_us[1]), len(t) - 1))
            else:
                w0, w1 = s0, s1
            if not _level_on_channel(level, chan[ch], w0, w1):
                lo, hi = _signed_range(chan[ch], w0, w1)
                problems.append(
                    f"{label}={level:.2f} 不在{ch}有符号范围[{lo:.1f},{hi:.1f}]"
                )

        if name in ("dv/dt", "di/dt"):
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
            check_level(top_v, channel, "Ha", win)
            check_level(base_v, channel, "Hb", win)
            ab = calls.get("apply_dvdt_ab_times")
            ab_txt = ""
            gui_ab_us: tuple[float, float] | None = None
            if ab is not None:
                ta, tb = ab["bound"]["t_a_us"], ab["bound"]["t_b_us"]
                gui_ab_us = (float(ta), float(tb))
                check_time(ta, "A")
                check_time(tb, "B")
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
                        use_abs = True
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
            check_time(ta, "A")
            check_time(tb, "B")
            check_level(ha_v, ha_ch, "Ha", win)
            check_level(hb_a, hb_ch, "Hb", win)
            detail = f"Ha({ha_ch})={ha_v:.1f} Hb({hb_ch})={hb_a:.1f} A={ta:.2f} B={tb:.2f}"

        elif name == "Err":
            c = calls.get("enable_energy_loss_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_energy_loss_interaction")
                continue
            b = c["bound"]
            ta, tb, ha_a, hb_v = b["t_a_us"], b["t_b_us"], b["ha_v"], b["hb_a"]
            ha_ch, hb_ch = b.get("ha_channel"), b.get("hb_channel")
            check_channel(ha_ch, "irr", "Ha")
            check_channel(hb_ch, "v_diode", "Hb")
            if not (ta > tb):
                problems.append(f"A({ta:.3f})应晚于B({tb:.3f})")
            on1 = seg_idx["turn_on"][1]
            from dpt_extractor.metrics.iec_windows import err_recovery_peak_index

            ipk = s0 + err_recovery_peak_index(
                np.asarray(chan["irr"][s0 : s1 + 1], dtype=np.float64),
                bundle.dt,
            )
            tpk_us = float(t[ipk]) * 1e6
            ha_win = (tpk_us + 0.4, tpk_us + 0.8)
            hb_win = (tpk_us - 0.6, tpk_us - 0.2)
            check_time(ta, "A", (s0, on1))
            check_time(tb, "B", (s0, on1))
            check_level(ha_a, "irr", "Ha", ha_win)
            check_level(hb_v, "v_diode", "Hb", hb_win)
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
            detail = f"Ha(irr)={ha_a:.2f} Hb(vd)={hb_v:.2f} A={ta:.3f} B={tb:.3f}"

        elif name == "Irr":
            c = calls.get("enable_irr_peak_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_irr_peak_interaction")
                continue
            hb_call = calls.get("set_interval_peak_on_hb")
            hb_val = hb_call["bound"].get("y") if hb_call else float("nan")
            ch = hb_call["bound"].get("channel") if hb_call else None
            check_channel(ch, "irr", "Hb")
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
            if not np.isfinite(float(hb_val)) or not np.isclose(
                float(hb_val), expected_signed, rtol=0.15, atol=8.0
            ):
                problems.append(
                    f"Irr峰 Hb={float(hb_val):.1f} 与有符号尖峰"
                    f"={expected_signed:.1f}不符"
                )
            if irr_ref > 1.0 and not (0.5 * irr_ref <= abs(hb_val) <= 1.3 * irr_ref):
                problems.append(f"Irr峰|Hb|={abs(hb_val):.1f} 与提取Irr={irr_ref:.1f}不符")
            detail = f"ch={ch} Hb={float(hb_val):.1f} irr_ref={irr_ref:.1f}"

        elif name == "Trr":
            c = calls.get("enable_trr_measure_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_trr_measure_interaction（回退 generic）")
                continue
            b = c["bound"]
            ha_a, hb_a, ta, tb = b["ha_a"], b["hb_a"], b["ta_us"], b["tb_us"]
            peak_idx = b.get("peak_idx")
            check_time(ta, "A")
            check_time(tb, "B")
            if not (ta < tb):
                problems.append(f"A({ta:.3f})应早于B({tb:.3f})")
            if irr_ref > 1.0 and not (0.4 * irr_ref <= abs(hb_a) <= 1.4 * irr_ref):
                problems.append(f"Trr尖峰|Hb|={abs(hb_a):.1f} 与提取Irr={irr_ref:.1f}不符")
            if peak_idx is not None and not (s0 <= int(peak_idx) <= s1):
                problems.append(f"peak_idx={peak_idx}不在反向恢复段")
            check_level(ha_a, "irr", "Ha")
            check_level(hb_a, "irr", "Hb")
            if peak_idx is not None and 0 <= int(peak_idx) < len(chan["irr"]):
                expected_signed = float(chan["irr"][int(peak_idx)])
                if not np.isclose(hb_a, expected_signed, rtol=0.15, atol=8.0):
                    problems.append(
                        f"Trr Hb={hb_a:.1f} 与 peak_idx 有符号值"
                        f"={expected_signed:.1f}不符"
                    )
            detail = f"Ha={ha_a:.2f} Hb={hb_a:.1f} A={ta:.3f} B={tb:.3f} pk={peak_idx}"

        elif name == "开通电流":
            c = calls.get("enable_turn_on_current_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_turn_on_current_interaction")
                continue
            b = c["bound"]
            t_a, t_b, hb0, ha0 = b["t_a_us"], b["t_b_us"], b["hb"], b["ha"]
            check_time(t_a, "A")
            check_time(t_b, "B")
            check_level(ha0, "ic", "Ha")
            if not (abs(ha0) > abs(hb0)):
                problems.append(f"Ha({ha0:.1f})应>Hb({hb0:.1f})")
            detail = f"Hb={hb0:.2f} Ha={ha0:.1f} A={t_a:.3f} B={t_b:.3f}"

        elif name in {"ΔVce", "Ls_on", "Ls_off"}:
            c = calls.get("enable_delta_vce_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发 enable_delta_vce_interaction")
                continue
            b = c["bound"]
            fixed_t, fixed_v, move_t = b["fixed_t_us"], b["fixed_v"], b["move_t_us"]
            check_time(fixed_t, "A")
            check_time(move_t, "B")
            check_level(fixed_v, "vce", "Ha")
            detail = f"ch=vce A={fixed_t:.3f} B={move_t:.3f} Va={fixed_v:.1f}"

        elif name in {"Pmax", "Pdmax"}:
            c = calls.get("enable_interval_interaction")
            if c is None:
                record(section, name, "FAIL", "未触发功率区间交互")
                continue
            b = c["bound"]
            ta, tb = b["start_t_us"], b["end_t_us"]
            power_segment = (
                (s0, seg_idx["turn_on"][1])
                if section == "反向恢复"
                else (s0, s1)
            )
            check_time(ta, "A", power_segment)
            check_time(tb, "B", power_segment)
            peak = calls.get("set_interval_peak_horizontal")
            peak_text = ""
            if peak is not None:
                peak_y = peak["bound"].get("y")
                if peak_y is None or not np.isfinite(float(peak_y)):
                    problems.append(f"功率峰值无效: {peak_y}")
                else:
                    peak_text = f" peak={float(peak_y):.1f}"
            detail = f"A={ta:.3f} B={tb:.3f}{peak_text}"

        elif name == "串扰电压":
            c = calls.get("enable_crosstalk_interaction")
            if c is None:
                if not profile.vge_other or result.is_metric_unavailable(section, name):
                    record(section, name, "INFO", "无对管门极通道，串扰电压不可用")
                    continue
                record(section, name, "FAIL", "未触发 enable_crosstalk_interaction")
                continue
            b = c["bound"]
            check_time(b["start_t_us"], "A")
            check_time(b["end_t_us"], "B")
            detail = f"ch=vge_other A={b['start_t_us']:.3f} B={b['end_t_us']:.3f}"

        else:  # generic max: Ic_off_max / Vce_off_max / Ic_on_max / Vce_on_max / Vrr
            c = calls.get("set_interval_peak_horizontal")
            if c is None:
                interval_call = calls.get("enable_interval_interaction")
                if interval_call is None:
                    record(section, name, "FAIL", "未触发通用参数区间交互")
                    continue
                ib = interval_call["bound"]
                ta, tb = ib["start_t_us"], ib["end_t_us"]
                check_time(ta, "A")
                check_time(tb, "B")
                detail = f"纯区间 A={ta:.3f} B={tb:.3f}"
            else:
                b = c["bound"]
                peak_y = b.get("y")
                ch = b.get("channel")
                win = None
                if b.get("t0_us") is not None and b.get("t1_us") is not None:
                    win = (b["t0_us"], b["t1_us"])
                expected = {
                    "Ic_off_max": "ic",
                    "Vce_off_max": "vce",
                    "Ic_on_max": "ic",
                    "Vce_on_max": "vce",
                    "Vrr": "v_diode",
                }.get(name)
                check_channel(ch, expected, "峰")
                check_level(peak_y, ch, "峰值", win)
                base = calls.get("set_interval_base_horizontal")
                min_y = None
                if base is None:
                    problems.append("未设置Hb最小值参考线")
                else:
                    bb = base["bound"]
                    min_y = bb.get("y")
                    min_ch = bb.get("channel")
                    check_channel(min_ch, expected, "Hb最小值")
                    check_level(min_y, min_ch, "Hb最小值", win)
                min_txt = "" if min_y is None else f" HbMin={min_y:.1f}"
                detail = f"ch={ch} 峰={peak_y:.1f}{min_txt} win={win}"

        xr = mw.wave_plot.current_x_range_us()
        full_x = mw.wave_plot._full_x_range
        captured_focus = _captured_parameter_focus(calls)
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
                anchor_us, required_times_us, expected_fraction = captured_focus
                for required_us in required_times_us:
                    if required_us < x0 - 1e-6 or required_us > x1 + 1e-6:
                        problems.append(
                            f"focus 必需时刻={required_us:.3f} 不在视窗"
                            f"[{x0:.3f},{x1:.3f}]"
                        )
                if x0 > full_x0 + 0.02 and x1 < full_x1 - 0.02:
                    fraction = (anchor_us - x0) / max(span, 1e-12)
                    if abs(fraction - expected_fraction) > 0.025:
                        problems.append(
                            f"真实 focus 锚点比例={fraction:.3f}，"
                            f"调用期望约{expected_fraction:.3f}"
                        )
                detail += (
                    f" focus_anchor={anchor_us:.3f}"
                    f" required={required_times_us}"
                )
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
    paths = [
        path
        for path in discover_sample_waveforms(root)
        if not _is_short_circuit_sample(path)
    ]
    if os.environ.get("DPT_VALIDATE_ALL_CURSORS", "").lower() in {"1", "true", "yes"}:
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
    selected: list[Path] = []
    for fragments in DEFAULT_SAMPLE_FRAGMENTS:
        for path in paths:
            text = str(path)
            if all(fragment in text for fragment in fragments):
                selected.append(path)
                break
    if selected:
        return selected
    return paths[: min(8, len(paths))]


def run_all() -> list[tuple]:
    """对选定示例文件跑光标审计，返回 (file, section, name, status, detail) 行。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from dpt_extractor.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    all_rows: list[tuple] = []
    for path in _selected_sample_waveforms(ROOT):
        all_rows.extend(audit_file(MainWindow, QApplication, app, path))
    return all_rows


def main() -> None:
    all_rows = run_all()
    fails = [r for r in all_rows if r[3] == "FAIL"]
    by_file = _group_rows_by_sample(all_rows)

    for fn, rows in by_file.items():
        n_ok = sum(1 for r in rows if r[3] == "OK")
        n_fail = sum(1 for r in rows if r[3] == "FAIL")
        print(f"\n=== {fn}  OK={n_ok} FAIL={n_fail} ===")
        for _f, section, name, status, detail in rows:
            mark = {"OK": "OK ", "FAIL": "FAIL", "INFO": "INFO"}.get(status, status)
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
