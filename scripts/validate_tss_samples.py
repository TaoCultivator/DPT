"""示例 TSS 波形批量验证。"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_windows import (
    _err_recovery_settled_base,
    eoff_energy_markers,
    eon_energy_markers,
    err_energy_markers,
    err_recovery_peak_index,
    integrate_err_recovery,
    integrate_vi_window,
    rr_slope_window_indices,
)
from dpt_extractor.metrics.iec_timings import (
    TurnOnTimingInstants,
    turn_on_timing_instants,
)
from dpt_extractor.metrics.plateau_level import (
    turn_on_current_hb_ha_t,
    turn_on_didt_ha_at_turn_on,
)
from dpt_extractor.models.bridge_profile import (
    as_short_circuit_profile,
    guess_profile_from_path,
    has_bridge_hint_from_path,
    make_profile,
)
from dpt_extractor.models.channel_mapping import (
    apply_mapping,
    infer_best_mapping_from_bundle,
    infer_short_circuit_mapping_from_bundle,
)
from dpt_extractor.models.test_mode import TestMode
from dpt_extractor.models.slope_range import default_slope_ranges
from dpt_extractor.models.waveform import (
    bundle_reverse_recovery_current,
    bundle_total_current,
)
from dpt_extractor.metrics.slopes import rr_didt_measurement_context
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.pipeline.run_extract import run_extraction
from dpt_extractor.utils.sample_corpus import discover_sample_waveforms

_SHORT_CIRCUIT_DIR_TOKENS = {"DL", "DDD", "SHORT"}
_SHORT_CIRCUIT_FILENAME_RE = re.compile(
    r"(?:^|[_-])short(?:[_-]|$)|^[UVW][HL][_-]\d+(?:\.\d+)?V[_-]0{3}$",
    re.IGNORECASE,
)
_CONDITION_FILENAME_RE = re.compile(
    r"^[UVW][HL][_-](?P<voltage>\d+(?:\.\d+)?)V(?:[_-](?P<current>\d+(?:\.\d+)?)A)?[_-]\d+",
    re.IGNORECASE,
)
_VOLTAGE_TOL_ABS = 60.0
_VOLTAGE_TOL_REL = 0.18
_CURRENT_TOL_ABS = 30.0
_CURRENT_TOL_REL = 0.18


@dataclass(frozen=True)
class SampleValidation:
    path: Path
    kind: str
    status: str
    detail: str
    rr_polarity: int = 0
    problem_count: int = 0

    @property
    def failed(self) -> bool:
        return self.status == "ERROR"

    @property
    def warned(self) -> bool:
        return self.status == "WARN"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量验证示例 TSS 波形兼容性")
    parser.add_argument("--limit", type=int, default=None, help="仅验证前 N 个样本，便于快速冒烟")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="发现失败或警告样本时返回非零；默认只输出报告，便于训练集扫描",
    )
    return parser.parse_args()


def _sample_label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_short_circuit_sample(path: Path) -> bool:
    parts = {part.upper() for part in path.parts}
    if parts & _SHORT_CIRCUIT_DIR_TOKENS:
        return True
    return bool(_SHORT_CIRCUIT_FILENAME_RE.search(path.stem))


def _expected_condition_from_filename(path: Path) -> tuple[float | None, float | None]:
    match = _CONDITION_FILENAME_RE.search(path.stem)
    if not match:
        return None, None
    voltage = float(match.group("voltage"))
    current_text = match.group("current")
    current = float(current_text) if current_text is not None else None
    return voltage, current


def _out_of_tolerance(
    actual: float,
    expected: float,
    abs_tol: float,
    rel_tol: float,
) -> bool:
    return abs(float(actual) - float(expected)) > max(
        abs_tol,
        rel_tol * abs(float(expected)),
    )


def _append_condition_checks(
    problems: list[str],
    *,
    expected_voltage: float | None,
    expected_current: float | None,
    vdc: float,
    ioff: float,
    ion: float | None = None,
) -> None:
    """Use filename conditions as corpus-level calibration guards."""
    if expected_voltage is not None and _out_of_tolerance(
        vdc,
        expected_voltage,
        _VOLTAGE_TOL_ABS,
        _VOLTAGE_TOL_REL,
    ):
        problems.append(f"Vdc偏离文件名={vdc:.1f}/{expected_voltage:.0f}V")
    if expected_current is not None and _out_of_tolerance(
        ioff,
        expected_current,
        _CURRENT_TOL_ABS,
        _CURRENT_TOL_REL,
    ):
        problems.append(f"Ioff偏离文件名={ioff:.1f}/{expected_current:.0f}A")
    if ion is not None and expected_current is not None and _out_of_tolerance(
        ion,
        expected_current,
        _CURRENT_TOL_ABS,
        _CURRENT_TOL_REL,
    ):
        problems.append(f"Ion偏离文件名={ion:.1f}/{expected_current:.0f}A")


def _err_b_on_vd_main_rise(
    t,
    vd,
    t_b: float,
    hb: float,
    *,
    within_s: float = 220e-9,
    min_rise_v: float = 25.0,
) -> bool:
    vd_at_b = float(np.interp(float(t_b), t, vd))
    if abs(vd_at_b - float(hb)) > 1e-3:
        return False
    i0 = int(np.searchsorted(t, float(t_b), side="left"))
    i0 = max(0, min(i0, len(vd) - 1))
    i_probe = int(np.searchsorted(t, float(t_b) + 500e-9, side="right"))
    i_probe = max(i0 + 1, min(i_probe, len(vd)))
    span = max(0.0, float(np.max(vd[i0:i_probe])) - float(hb))
    if span >= min_rise_v:
        i1 = int(np.searchsorted(t, float(t_b) + within_s, side="right"))
        required = min_rise_v
    else:
        i1 = int(np.searchsorted(t, float(t_b) + 200e-9, side="right"))
        required = max(1.5, 0.5 * span)
    i1 = max(i0 + 1, min(i1, len(vd)))
    return float(np.max(vd[i0:i1])) - float(hb) >= required


def _cursor_on_level(
    t: np.ndarray,
    y: np.ndarray,
    t_cross: float,
    level: float,
    *,
    tol: float,
) -> bool:
    return abs(float(np.interp(float(t_cross), t, y)) - float(level)) <= float(tol)


def _audit_turn_on_timing_core(
    t: np.ndarray,
    result,
    instants: TurnOnTimingInstants,
    *,
    event_start_idx: int,
    event_end_idx: int,
) -> tuple[list[str], str]:
    """Fail closed unless all three turn-on timing cards have real endpoints.

    ``Ton``, ``Td_on`` and ``Tr`` are required for a double-pulse sample.  The
    audit intentionally checks each duration against its own authoritative
    endpoint pair instead of assuming ``Ton == Td_on + Tr``: with absolute
    duration semantics, a valid Vge 10% crossing can occur after Ic 10% on a
    marginal trace, so that identity is not generally safe as a validator.
    """

    problems: list[str] = []
    endpoint_values = {
        "Vge10": instants.t_v10_s,
        "Ic10": instants.t_i10_s,
        "Ic90": instants.t_i90_s,
    }
    valid_endpoints: dict[str, float] = {}
    for label, value in endpoint_values.items():
        if value is None:
            problems.append(f"开通时序缺少{label}真实交点")
            continue
        numeric = float(value)
        if not np.isfinite(numeric):
            problems.append(f"开通时序{label}交点非有限={value!r}")
            continue
        valid_endpoints[label] = numeric

    if len(t) < 2:
        problems.append("开通时序原始时间轴不足2点")
    else:
        start = max(0, min(int(event_start_idx), len(t) - 1))
        end = max(0, min(int(event_end_idx), len(t) - 1))
        event_lo = float(t[min(start, end)])
        event_hi = float(t[max(start, end)])
        if not np.isfinite(event_lo) or not np.isfinite(event_hi) or event_hi <= event_lo:
            problems.append(
                f"开通时序事件边界非法={event_lo!r}/{event_hi!r}"
            )
        else:
            for label, value in valid_endpoints.items():
                if not event_lo <= value <= event_hi:
                    problems.append(
                        f"开通时序{label}交点越界="
                        f"{value * 1e6:.6f}us not in "
                        f"[{event_lo * 1e6:.6f},{event_hi * 1e6:.6f}]us"
                    )

    if "Ic10" in valid_endpoints and "Ic90" in valid_endpoints:
        if valid_endpoints["Ic90"] <= valid_endpoints["Ic10"]:
            problems.append(
                "开通时序Ic交点未按主上升沿有序="
                f"{valid_endpoints['Ic10'] * 1e6:.6f}/"
                f"{valid_endpoints['Ic90'] * 1e6:.6f}us"
            )

    checks = (
        (
            "Ton",
            result.turn_on.ton,
            instants.ton_ns,
            "Vge10",
            "Ic90",
        ),
        (
            "Td_on",
            result.turn_on.td_on,
            instants.td_on_ns,
            "Vge10",
            "Ic10",
        ),
        (
            "Tr",
            result.turn_on.tr,
            instants.tr_ns,
            "Ic10",
            "Ic90",
        ),
    )
    for name, result_value, instant_value, left_label, right_label in checks:
        if result.is_metric_unavailable("开通", name):
            problems.append(f"{name}=unavailable")

        result_numeric = float(result_value)
        instant_numeric = float(instant_value)
        if not np.isfinite(result_numeric) or result_numeric <= 0.0:
            problems.append(f"{name}结果无效={result_value!r}")
        if not np.isfinite(instant_numeric) or instant_numeric <= 0.0:
            problems.append(f"{name}时序值无效={instant_value!r}")

        if left_label not in valid_endpoints or right_label not in valid_endpoints:
            continue
        expected_ns = (
            abs(valid_endpoints[right_label] - valid_endpoints[left_label]) * 1e9
        )
        if expected_ns <= 0.0:
            problems.append(f"{name}真实交点时间差为0")
            continue
        if np.isfinite(instant_numeric) and not np.isclose(
            instant_numeric,
            expected_ns,
            rtol=1e-10,
            atol=1e-6,
        ):
            problems.append(
                f"{name}时序/交点={instant_numeric:.9g}/{expected_ns:.9g}ns"
            )
        if np.isfinite(result_numeric) and not np.isclose(
            result_numeric,
            expected_ns,
            rtol=1e-10,
            atol=1e-6,
        ):
            problems.append(
                f"{name}结果/交点={result_numeric:.9g}/{expected_ns:.9g}ns"
            )

    def _endpoint_text(value: float | None) -> str:
        if value is None:
            return "missing"
        numeric = float(value)
        return f"{numeric * 1e6:.6f}us" if np.isfinite(numeric) else repr(value)

    detail = (
        f"Ton={float(result.turn_on.ton):.6f}ns "
        f"Td_on={float(result.turn_on.td_on):.6f}ns "
        f"Tr={float(result.turn_on.tr):.6f}ns "
        f"on_instants={_endpoint_text(instants.t_v10_s)}/"
        f"{_endpoint_text(instants.t_i10_s)}/"
        f"{_endpoint_text(instants.t_i90_s)}"
    )
    return problems, detail


def _audit_rr_didt_context(
    t: np.ndarray,
    irr: np.ndarray,
    context,
    result_value: float,
    *,
    pct_a: float,
    pct_b: float,
    measure: str,
) -> tuple[list[str], str]:
    """Strictly audit the authoritative RR di/dt context against raw data.

    This deliberately consumes the context already shared by pipeline/GUI, but
    verifies its intersections against the original signed Irr samples.  It
    therefore catches a self-consistent yet wrongly placed/fallback cursor pair
    without introducing a second parameter implementation into the validator.
    """
    problems: list[str] = []
    crossing = context.crossing
    polarity = int(context.polarity)
    signed_values = {
        "forward": float(context.forward_a),
        "base": float(context.base_a),
        "reverse": float(context.reverse_a),
        "threshold_a": float(crossing.th_a),
        "threshold_b": float(crossing.th_b),
        "didt": float(crossing.didt),
        "result": float(result_value),
    }
    if context.zero_a is not None:
        signed_values["zero"] = float(context.zero_a)
    nonfinite = [name for name, value in signed_values.items() if not np.isfinite(value)]
    if nonfinite:
        problems.append("RR di/dt非有限=" + ",".join(nonfinite))
    if polarity not in {-1, 1}:
        problems.append(f"RR极性非法={polarity}")
    elif np.isfinite(context.forward_a) and np.isfinite(context.base_a):
        forward_mag = polarity * (float(context.forward_a) - float(context.base_a))
        if forward_mag <= 0.0:
            problems.append(
                "RR有符号平台方向错误="
                f"forward={context.forward_a:.6g},base={context.base_a:.6g},"
                f"polarity={polarity:+d}"
            )
    if bool(context.used_fallback):
        problems.append("RR di/dt使用数值fallback")
    if not np.isfinite(result_value) or float(result_value) <= 0.0:
        problems.append(f"RR pipeline di/dt={result_value!r}")
    if not np.isfinite(crossing.didt) or float(crossing.didt) <= 0.0:
        problems.append(f"RR context di/dt={crossing.didt!r}")
    elif not np.isclose(
        float(result_value),
        float(crossing.didt),
        rtol=1e-11,
        atol=1e-12,
    ):
        problems.append(
            f"RR pipeline/context di/dt={result_value:.12g}/{crossing.didt:.12g}"
        )

    t_a = crossing.t_pct_a_s
    t_b = crossing.t_pct_b_s
    raw_a: float | None = None
    raw_b: float | None = None
    if t_a is None or t_b is None:
        missing = "A" if t_a is None else ""
        missing += "B" if t_b is None else ""
        problems.append(f"RR di/dt缺少真实{missing}交点")
    elif not np.isfinite(t_a) or not np.isfinite(t_b):
        problems.append(f"RR di/dt A/B非有限={t_a!r}/{t_b!r}")
    elif len(t) < 2 or len(irr) < 2:
        problems.append("RR di/dt原始波形不足2点")
    else:
        t_lo = float(t[0])
        t_hi = float(t[-1])
        if not (t_lo <= float(t_a) <= t_hi and t_lo <= float(t_b) <= t_hi):
            problems.append(
                f"RR di/dt A/B越界={t_a * 1e6:.6f}/{t_b * 1e6:.6f}us"
            )
        else:
            raw_a = float(np.interp(float(t_a), t, irr))
            raw_b = float(np.interp(float(t_b), t, irr))
            scale = max(
                1.0,
                abs(float(crossing.th_a)),
                abs(float(crossing.th_b)),
                abs(float(context.forward_a)),
                abs(float(context.base_a)),
            )
            level_tol = max(1e-6, 1e-8 * scale)
            if not np.isfinite(raw_a):
                problems.append(f"RR原始A插值非有限={raw_a!r}")
            elif abs(raw_a - float(crossing.th_a)) > level_tol:
                problems.append(
                    "RR原始A插值/阈值="
                    f"{raw_a:.9g}/{crossing.th_a:.9g}A"
                )
            if not np.isfinite(raw_b):
                problems.append(f"RR原始B插值非有限={raw_b!r}")
            elif abs(raw_b - float(crossing.th_b)) > level_tol:
                problems.append(
                    "RR原始B插值/阈值="
                    f"{raw_b:.9g}/{crossing.th_b:.9g}A"
                )
            if measure == "if_irm":
                chronological = float(t_a) < float(t_b)
            elif pct_a > pct_b:
                chronological = float(t_a) < float(t_b)
            elif pct_a < pct_b:
                chronological = float(t_a) > float(t_b)
            else:
                chronological = False
            if not chronological:
                problems.append(
                    f"RR di/dt A/B时序错误={t_a * 1e6:.6f}/{t_b * 1e6:.6f}us"
                )
            dt_s = abs(float(t_b) - float(t_a))
            if dt_s <= 0.0:
                problems.append("RR di/dt A/B时间差为0")
            else:
                raw_didt = (
                    abs(float(crossing.th_b) - float(crossing.th_a))
                    / dt_s
                    / 1e9
                )
                if not np.isclose(
                    raw_didt,
                    float(crossing.didt),
                    rtol=1e-10,
                    atol=1e-12,
                ):
                    problems.append(
                        f"RR阈值/A-B di/dt={raw_didt:.12g}/{crossing.didt:.12g}"
                    )

    polarity_text = "+1" if polarity == 1 else "-1" if polarity == -1 else str(polarity)
    ab_text = (
        f"{float(t_a) * 1e6:.6f}/{float(t_b) * 1e6:.6f}us"
        if t_a is not None and t_b is not None
        else "missing"
    )
    raw_text = (
        f"{raw_a:.6g}/{raw_b:.6g}A"
        if raw_a is not None and raw_b is not None
        else "missing"
    )
    detail = (
        f"rr_didt={float(crossing.didt):.6f} "
        f"rr_polarity={polarity_text} "
        f"rr_measure={measure} "
        f"rr_AB={ab_text} "
        f"rr_rawAB={raw_text} "
        f"rr_fallback={bool(context.used_fallback)}"
    )
    return problems, detail


def _mapping_fallback_result(
    path: Path,
    bundle,
    base_profile,
    *,
    allow_mapping_fallback: bool,
    current_problem_count: int | None = None,
) -> SampleValidation | None:
    if not allow_mapping_fallback:
        return None
    bridges = [base_profile.bridge]
    if not has_bridge_hint_from_path(path):
        bridges.append("lower" if base_profile.bridge == "upper" else "upper")
    best_warned: SampleValidation | None = None
    for bridge in dict.fromkeys(bridges):
        candidate_base = make_profile(base_profile.phase, bridge)
        inferred_mapping, mapping_method = infer_best_mapping_from_bundle(
            bundle,
            bridge,
        )
        if inferred_mapping is None:
            continue
        mapped_profile = apply_mapping(candidate_base, inferred_mapping)
        try:
            result = _validate_dpt_sample(
                path,
                profile_override=mapped_profile,
                mapping_method=mapping_method or "inferred",
                allow_mapping_fallback=False,
            )
        except Exception:  # noqa: BLE001
            continue
        if not result.warned and not result.failed:
            return result
        if (
            not result.failed
            and (
                best_warned is None
                or result.problem_count < best_warned.problem_count
            )
        ):
            best_warned = result
    if (
        best_warned is not None
        and (
            current_problem_count is None
            or best_warned.problem_count < int(current_problem_count)
        )
    ):
        # A newly required metric can make the physically correct inferred
        # mapping WARN without making the original default mapping better.
        # Keep the inferred candidate when it has fewer independent problems
        # so diagnostics report the right channel mapping and the real metric
        # gap instead of falling back to a much more broken default profile.
        return best_warned
    return None


def _validate_dpt_sample(
    path: Path,
    *,
    profile_override=None,
    mapping_method: str = "default",
    allow_mapping_fallback: bool = True,
) -> SampleValidation:
    cfg = load_config()
    base_prof = guess_profile_from_path(path)
    prof = profile_override or base_prof
    b = load_waveform(path)
    try:
        r = extract_all(b, prof, cfg)
    except Exception:
        fallback = _mapping_fallback_result(
            path,
            b,
            base_prof,
            allow_mapping_fallback=allow_mapping_fallback,
        )
        if fallback is not None:
            return fallback
        raise
    segs = r.segments
    assert segs is not None
    expected_voltage, expected_current = _expected_condition_from_filename(path)
    ic = bundle_total_current(b, prof)
    vce = b.get(prof.vce)
    if r.single_pulse_mode:
        problems: list[str] = []
        eoff_m = eoff_energy_markers(
            b.t,
            ic,
            vce,
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_off,
            b.dt,
            pre_ns=cfg.energy.eoff_pre_ns,
            pulse1_on=segs.pulse1_on,
        )
        eoff_chk = integrate_vi_window(b.t, vce, ic, eoff_m.as_integration_window())
        eoff_tol = max(0.02, 0.02 * max(abs(eoff_chk), 1e-9))
        if abs(r.turn_off.eoff - eoff_chk) > eoff_tol:
            problems.append(f"Eoff校验={r.turn_off.eoff:.3f}/{eoff_chk:.3f}mJ")
        if not _cursor_on_level(b.t, ic, eoff_m.t_end, eoff_m.hb_a, tol=2.0):
            problems.append(f"Eoff B未贴Ic平台={eoff_m.t_end * 1e6:.6f}us")
        if r.detected_pulse_count != 1:
            problems.append(f"单脉冲识别数={r.detected_pulse_count}")
        if r.turn_off.ic_off_max <= 0.0:
            problems.append(f"Ic_off_max={r.turn_off.ic_off_max:.3f}A")
        if r.turn_off.vce_off_max <= 0.0:
            problems.append(f"Vce_off_max={r.turn_off.vce_off_max:.3f}V")
        if r.turn_off.dvdt <= 0.0:
            problems.append(f"关断dv/dt={r.turn_off.dvdt:.3f}V/ns")
        if r.turn_off.didt <= 0.0:
            problems.append(f"关断di/dt={r.turn_off.didt:.3f}A/ns")
        if r.turn_off.eoff <= 0.0:
            problems.append(f"Eoff={r.turn_off.eoff:.3f}mJ")
        _append_condition_checks(
            problems,
            expected_voltage=expected_voltage,
            expected_current=expected_current,
            vdc=r.vdc,
            ioff=r.turn_off.ic_off_max,
        )
        status = "WARN" if problems else "OK"
        detail = (
            f"profile={prof.code} "
            f"map={mapping_method or 'default'} "
            f"pulses={r.detected_pulse_count} "
            f"target={expected_voltage or 0:.0f}V/"
            f"{expected_current or 0:.0f}A "
            f"Ic_off_max={r.turn_off.ic_off_max:.1f} "
            f"Vdc={r.vdc:.1f} "
            f"Vce_off_max={r.turn_off.vce_off_max:.1f} "
            f"dvdt_off={r.turn_off.dvdt:.3f} "
            f"didt_off={r.turn_off.didt:.3f} "
            f"Eoff={r.turn_off.eoff:.3f}"
        )
        if problems:
            detail += " | " + "; ".join(problems)
            fallback = _mapping_fallback_result(
                path,
                b,
                base_prof,
                allow_mapping_fallback=allow_mapping_fallback,
                current_problem_count=len(problems),
            )
            if fallback is not None:
                return fallback
        return SampleValidation(
            path=path,
            kind="DPT-1P",
            status=status,
            detail=detail,
            problem_count=len(problems),
        )

    on0, on1 = segs.turn_on
    rr0, rr1 = segs.reverse_recovery
    irr = bundle_reverse_recovery_current(b, prof)
    vd = b.get(prof.v_diode)
    eoff_m = eoff_energy_markers(
        b.t,
        ic,
        vce,
        segs.turn_off[0],
        segs.turn_off[1],
        segs.pulse1_off,
        b.dt,
        pre_ns=cfg.energy.eoff_pre_ns,
        pulse1_on=segs.pulse1_on,
    )
    eon_m = eon_energy_markers(
        b.t,
        ic,
        vce,
        on0,
        on1,
        segs.pulse2_on,
        b.dt,
        pulse1_off=segs.pulse1_off,
    )
    _, ha = turn_on_current_hb_ha_t(
        b.t,
        ic,
        on0,
        on1,
        b.dt,
        event_end_idx=segs.pulse2_off,
    )
    ha_d = turn_on_didt_ha_at_turn_on(
        b.t,
        ic,
        on0,
        on1,
        b.dt,
        event_end_idx=segs.pulse2_off,
    )
    mk = err_energy_markers(
        b.t,
        irr,
        vd,
        rr0,
        rr1,
        b.dt,
        i_search_end=on1,
        vge=b.get(prof.vge),
        pulse1_off=segs.pulse1_off,
        pulse2_on=segs.pulse2_on,
        pulse2_off=segs.pulse2_off,
        dc_current=r.idc,
        lower_bridge_irr_from_ic_minus_il=prof.irr_from_ic_minus_il,
    )
    eoff_chk = integrate_vi_window(b.t, vce, ic, eoff_m.as_integration_window())
    eon_chk = integrate_vi_window(b.t, vce, ic, eon_m.as_integration_window())
    e_chk = integrate_err_recovery(b.t, vd, irr, mk.as_integration_window())
    ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], b.dt)
    err_base = _err_recovery_settled_base(irr, ipk, b.dt, on1)
    ha_settle = float(err_base.level)
    settle_pp = 2.0 * float(err_base.amp)
    problems: list[str] = []
    if (
        r.is_metric_unavailable("反向恢复", "Trr")
        or not np.isfinite(float(r.reverse_recovery.trr))
        or float(r.reverse_recovery.trr) <= 0.0
    ):
        problems.append(
            f"Trr稳定平台首交点不可用={float(r.reverse_recovery.trr):.6g}ns"
        )
    on_timing = turn_on_timing_instants(
        b.t,
        b.get(prof.vge),
        ic,
        on0,
        on1,
        segs.pulse2_on,
        b.dt,
        cfg,
        pulse2_off=segs.pulse2_off,
    )
    timing_problems, timing_detail = _audit_turn_on_timing_core(
        b.t,
        r,
        on_timing,
        event_start_idx=on0,
        event_end_idx=segs.pulse2_off,
    )
    problems.extend(timing_problems)
    rr_s0, rr_s1 = rr_slope_window_indices(on0, rr1, len(b.t), b.dt)
    slope_active = default_slope_ranges()
    slope_active.update(cfg.slope_ranges)
    rr_di = slope_active["rr_didt"]
    di_a, di_b = rr_di.as_fractions()
    rr_measure = (
        rr_di.ic_reference
        if rr_di.ic_reference in {"idm", "if_irm"}
        else "idm"
    )
    rr_context = rr_didt_measurement_context(
        b.t,
        irr,
        rr_s0,
        rr_s1,
        b.dt,
        cfg,
        di_a,
        di_b,
        measure=rr_measure,
        rr_i0=rr0,
        rr_i1=rr1,
        fallback_i0=rr0,
        fallback_i1=rr1,
    )
    rr_problems, rr_detail = _audit_rr_didt_context(
        b.t,
        irr,
        rr_context,
        r.reverse_recovery.didt_irr,
        pct_a=di_a,
        pct_b=di_b,
        measure=rr_measure,
    )
    problems.extend(rr_problems)
    eoff_tol = max(0.02, 0.02 * max(abs(eoff_chk), 1e-9))
    if abs(r.turn_off.eoff - eoff_chk) > eoff_tol:
        problems.append(f"Eoff校验={r.turn_off.eoff:.3f}/{eoff_chk:.3f}mJ")
    eon_tol = max(0.02, 0.02 * max(abs(eon_chk), 1e-9))
    if abs(r.turn_on.eon - eon_chk) > eon_tol:
        problems.append(f"Eon校验={r.turn_on.eon:.3f}/{eon_chk:.3f}mJ")
    if not _cursor_on_level(b.t, ic, eoff_m.t_end, eoff_m.hb_a, tol=2.0):
        problems.append(f"Eoff B未贴Ic平台={eoff_m.t_end * 1e6:.6f}us")
    if not _cursor_on_level(b.t, vce, eon_m.t_end, eon_m.hb_a, tol=2.0):
        problems.append(f"Eon B未贴Vce平台={eon_m.t_end * 1e6:.6f}us")
    if abs(ha - ha_d) >= 1.0:
        problems.append(f"on_ha偏差={abs(ha - ha_d):.2f}A")
    err_tol = max(0.01, 0.02 * max(abs(e_chk), 1e-9))
    if not (
        r.reverse_recovery.err > 0.01
        and abs(r.reverse_recovery.err - e_chk) <= err_tol
    ):
        problems.append(f"Err校验={r.reverse_recovery.err:.3f}/{e_chk:.3f}mJ")
    if abs(mk.hb_a) >= 50.0:
        problems.append(f"Err Hb={mk.hb_a:.2f}V")
    if not _err_b_on_vd_main_rise(b.t, vd, mk.t_end, mk.hb_a):
        problems.append(f"Err B未贴Vd主上升沿={mk.t_end * 1e6:.6f}us")
    _append_condition_checks(
        problems,
        expected_voltage=expected_voltage,
        expected_current=expected_current,
        vdc=r.vdc,
        ioff=r.turn_off.ic_off_max,
        ion=ha,
    )
    status = "WARN" if problems else "OK"
    detail = (
        f"profile={prof.code} "
        f"map={mapping_method or 'default'} "
        f"target={expected_voltage or 0:.0f}V/"
        f"{expected_current or 0:.0f}A "
        f"Vdc={r.vdc:.1f} "
        f"Ioff={r.turn_off.ic_off_max:.1f} "
        f"err={r.reverse_recovery.err:.3f} "
        f"ha={mk.ha_v:.2f} "
        f"settle={ha_settle:.2f} "
        f"settle_pp={settle_pp:.2f} "
        f"hb={mk.hb_a:.2f} "
        f"b={mk.t_end * 1e6:.6f}us "
        f"on_ha={ha:.1f} "
        f"didt_ha={ha_d:.1f} "
        f"{timing_detail} "
        f"{rr_detail}"
    )
    if problems:
        detail += " | " + "; ".join(problems)
        fallback = _mapping_fallback_result(
            path,
            b,
            base_prof,
            allow_mapping_fallback=allow_mapping_fallback,
            current_problem_count=len(problems),
        )
        if fallback is not None:
            return fallback
    return SampleValidation(
        path=path,
        kind="DPT",
        status=status,
        detail=detail,
        rr_polarity=int(rr_context.polarity),
        problem_count=len(problems),
    )


def _short_metric_text(
    result,
    name: str,
    value: float,
    *,
    unit: str,
    precision: int,
) -> str:
    """Render unavailable/invalid short metrics without plausible fake numbers."""

    if result.is_metric_unavailable("短路过程", name):
        return "-"
    numeric = float(value)
    if not np.isfinite(numeric):
        return "invalid"
    return f"{numeric:.{precision}f}{unit}"


def _short_metric_state_problem(
    result,
    name: str,
    value: float | None,
    *,
    label: str,
    required: bool,
) -> str | None:
    """Reject required-unavailable and available-nonfinite short metrics."""

    unavailable = result.is_metric_unavailable("短路过程", name)
    if unavailable:
        return f"{label}=unavailable" if required else None
    if value is None or not np.isfinite(float(value)):
        return f"{label}={value!r}"
    return None


def _validate_short_circuit_sample(path: Path) -> SampleValidation:
    cfg = load_config()
    cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
    base_prof = guess_profile_from_path(path)
    b = load_waveform(path)
    inferred = infer_short_circuit_mapping_from_bundle(b, base_prof.bridge)
    if inferred is not None:
        prof = apply_mapping(as_short_circuit_profile(base_prof), inferred)
        mapping_method = "label"
    else:
        prof = as_short_circuit_profile(base_prof)
        mapping_method = "default"
    r = run_extraction(b, prof, cfg)
    sc = r.short_circuit
    problems: list[str] = []
    if not r.short_circuit_mode:
        problems.append("未进入短路模式")
    for name, value, label, required in (
        ("短路电流Imax", sc.ic_max, "Imax", True),
        ("短路时间Tsc", sc.tsc, "Tsc", True),
        ("短路能量Esc_本管", sc.esc_dut, "EscDUT", True),
        ("应力Vpeak_本管", sc.vpeak_dut, "VpeakDUT", False),
        ("短路能量Esc_对管", sc.esc_other, "EscOther", False),
        ("应力Vpeak_对管", sc.vpeak_other, "VpeakOther", False),
        ("Desat动作时间", sc.desat_time, "Desat", False),
    ):
        problem = _short_metric_state_problem(
            r,
            name,
            value,
            label=label,
            required=required,
        )
        if problem is not None:
            problems.append(problem)
    if (
        not r.is_metric_unavailable("短路过程", "短路电流Imax")
        and np.isfinite(sc.ic_max)
        and sc.ic_max <= 0.0
    ):
        problems.append(f"Imax={sc.ic_max:.3f}A")
    if (
        not r.is_metric_unavailable("短路过程", "短路时间Tsc")
        and np.isfinite(sc.tsc)
        and sc.tsc <= 0.0
    ):
        problems.append(f"Tsc={sc.tsc:.4f}us")
    status = "WARN" if problems else "OK"
    imax_text = _short_metric_text(r, "短路电流Imax", sc.ic_max, unit="A", precision=1)
    tsc_text = _short_metric_text(r, "短路时间Tsc", sc.tsc, unit="us", precision=3)
    esc_dut_text = _short_metric_text(
        r, "短路能量Esc_本管", sc.esc_dut, unit="J", precision=4
    )
    esc_other_text = _short_metric_text(
        r, "短路能量Esc_对管", sc.esc_other, unit="J", precision=4
    )
    vpeak_dut_text = _short_metric_text(
        r, "应力Vpeak_本管", sc.vpeak_dut, unit="V", precision=1
    )
    vpeak_other_text = _short_metric_text(
        r, "应力Vpeak_对管", sc.vpeak_other, unit="V", precision=1
    )
    detail = (
        f"profile={prof.code} "
        f"map={mapping_method} "
        f"Imax={imax_text} "
        f"Tsc={tsc_text} "
        f"EscDUT={esc_dut_text} "
        f"EscOther={esc_other_text} "
        f"VpeakDUT={vpeak_dut_text} "
        f"VpeakOther={vpeak_other_text}"
    )
    if problems:
        detail += " | " + "; ".join(problems)
    return SampleValidation(path=path, kind="SC", status=status, detail=detail)


def _validate_sample(path: Path) -> SampleValidation:
    try:
        if _is_short_circuit_sample(path):
            return _validate_short_circuit_sample(path)
        return _validate_dpt_sample(path)
    except Exception as exc:  # noqa: BLE001
        kind = "SC" if _is_short_circuit_sample(path) else "DPT"
        return SampleValidation(path=path, kind=kind, status="ERROR", detail=repr(exc))


def main() -> None:
    args = _parse_args()
    samples = discover_sample_waveforms(ROOT)
    if args.limit is not None:
        samples = samples[: max(0, args.limit)]
    if not samples:
        print("未发现可用于兼容性验证的 TSS 波形，请检查示例文件目录")
        raise SystemExit(1)
    stats = {
        "dpt_ok": 0,
        "dpt_warn": 0,
        "dpt_single_ok": 0,
        "dpt_single_warn": 0,
        "sc_ok": 0,
        "sc_warn": 0,
        "failed": 0,
        "rr_polarity_positive": 0,
        "rr_polarity_negative": 0,
    }
    print(f"发现 TSS 样本 {len(samples)} 个，开始兼容性扫描...")
    for path in samples:
        result = _validate_sample(path)
        if result.failed:
            stats["failed"] += 1
        elif result.kind == "DPT-1P" and result.warned:
            stats["dpt_single_warn"] += 1
        elif result.kind == "DPT-1P":
            stats["dpt_single_ok"] += 1
        elif result.kind == "SC" and result.warned:
            stats["sc_warn"] += 1
        elif result.kind == "SC":
            stats["sc_ok"] += 1
        elif result.warned:
            stats["dpt_warn"] += 1
        else:
            stats["dpt_ok"] += 1
        if result.kind == "DPT" and result.rr_polarity == 1:
            stats["rr_polarity_positive"] += 1
        elif result.kind == "DPT" and result.rr_polarity == -1:
            stats["rr_polarity_negative"] += 1
        print(
            _sample_label(result.path),
            result.kind,
            result.status,
            result.detail,
        )
    warnings = stats["dpt_warn"] + stats["dpt_single_warn"] + stats["sc_warn"]
    print(
        "扫描完成："
        f"total={len(samples)} "
        f"dpt_ok={stats['dpt_ok']} "
        f"dpt_warn={stats['dpt_warn']} "
        f"dpt_single_ok={stats['dpt_single_ok']} "
        f"dpt_single_warn={stats['dpt_single_warn']} "
        f"sc_ok={stats['sc_ok']} "
        f"sc_warn={stats['sc_warn']} "
        f"rr_polarity_positive={stats['rr_polarity_positive']} "
        f"rr_polarity_negative={stats['rr_polarity_negative']} "
        f"failed={stats['failed']} "
        f"warnings={warnings}"
    )
    if args.strict and (stats["failed"] or warnings):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
