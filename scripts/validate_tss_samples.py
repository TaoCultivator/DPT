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
)
from dpt_extractor.metrics.plateau_level import (
    turn_on_current_hb_ha_t,
    turn_on_didt_ha_at_turn_on,
)
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.channel_mapping import (
    apply_mapping,
    infer_best_mapping_from_bundle,
)
from dpt_extractor.models.test_mode import TestMode
from dpt_extractor.models.waveform import (
    bundle_reverse_recovery_current,
    bundle_total_current,
)
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.pipeline.run_extract import run_extraction
from dpt_extractor.utils.sample_corpus import discover_sample_waveforms

_SHORT_CIRCUIT_DIR_TOKENS = {"DL", "DDD"}
_SHORT_CIRCUIT_FILENAME_RE = re.compile(
    r"^[UVW][HL][_-]\d+(?:\.\d+)?V[_-]0{3}$",
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
    within_s: float = 120e-9,
    min_rise_v: float = 30.0,
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


def _mapping_fallback_result(
    path: Path,
    bundle,
    base_profile,
    *,
    allow_mapping_fallback: bool,
) -> SampleValidation | None:
    if not allow_mapping_fallback:
        return None
    inferred_mapping, mapping_method = infer_best_mapping_from_bundle(
        bundle,
        base_profile.bridge,
    )
    if inferred_mapping is None:
        return None
    mapped_profile = apply_mapping(base_profile, inferred_mapping)
    result = _validate_dpt_sample(
        path,
        profile_override=mapped_profile,
        mapping_method=mapping_method or "inferred",
        allow_mapping_fallback=False,
    )
    return result if not result.warned and not result.failed else None


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
    r = extract_all(b, prof, cfg)
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
            )
            if fallback is not None:
                return fallback
        return SampleValidation(path=path, kind="DPT-1P", status=status, detail=detail)

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
    _, ha = turn_on_current_hb_ha_t(b.t, ic, on0, on1, b.dt)
    ha_d = turn_on_didt_ha_at_turn_on(b.t, ic, on0, on1, b.dt)
    mk = err_energy_markers(b.t, irr, vd, rr0, rr1, b.dt, i_search_end=on1)
    eoff_chk = integrate_vi_window(b.t, vce, ic, eoff_m.as_integration_window())
    eon_chk = integrate_vi_window(b.t, vce, ic, eon_m.as_integration_window())
    e_chk = integrate_err_recovery(b.t, vd, irr, mk.as_integration_window())
    ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], b.dt)
    err_base = _err_recovery_settled_base(irr, ipk, b.dt, on1)
    ha_settle = float(err_base.level)
    settle_pp = 2.0 * float(err_base.amp)
    problems: list[str] = []
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
        f"didt_ha={ha_d:.1f}"
    )
    if problems:
        detail += " | " + "; ".join(problems)
        fallback = _mapping_fallback_result(
            path,
            b,
            base_prof,
            allow_mapping_fallback=allow_mapping_fallback,
        )
        if fallback is not None:
            return fallback
    return SampleValidation(path=path, kind="DPT", status=status, detail=detail)


def _validate_short_circuit_sample(path: Path) -> SampleValidation:
    cfg = load_config()
    cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
    prof = guess_profile_from_path(path)
    b = load_waveform(path)
    r = run_extraction(b, prof, cfg)
    sc = r.short_circuit
    problems: list[str] = []
    if not r.short_circuit_mode:
        problems.append("未进入短路模式")
    if sc.ic_max <= 0.0:
        problems.append(f"Imax={sc.ic_max:.3f}A")
    if sc.tsc <= 0.0:
        problems.append(f"Tsc={sc.tsc:.4f}us")
    status = "WARN" if problems else "OK"
    detail = (
        f"profile={prof.code} "
        f"Imax={sc.ic_max:.1f}A "
        f"Tsc={sc.tsc:.3f}us "
        f"EscDUT={sc.esc_dut:.4f}J "
        f"EscOther={sc.esc_other:.4f}J "
        f"VpeakDUT={sc.vpeak_dut:.1f}V "
        f"VpeakOther={sc.vpeak_other:.1f}V"
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
        f"failed={stats['failed']} "
        f"warnings={warnings}"
    )
    if args.strict and (stats["failed"] or warnings):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
