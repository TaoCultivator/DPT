"""示例 TSS 波形批量验证。"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_windows import err_energy_markers, integrate_err_recovery
from dpt_extractor.metrics.plateau_level import (
    turn_on_current_hb_ha_t,
    turn_on_didt_ha_at_turn_on,
)
from dpt_extractor.models.bridge_profile import guess_profile_from_path
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
        help="发现失败样本时返回非零；默认只输出报告，便于训练集扫描",
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


def _validate_dpt_sample(path: Path) -> SampleValidation:
    cfg = load_config()
    prof = guess_profile_from_path(path)
    b = load_waveform(path)
    r = extract_all(b, prof, cfg)
    segs = r.segments
    assert segs is not None
    on0, on1 = segs.turn_on
    rr0, rr1 = segs.reverse_recovery
    ic = bundle_total_current(b, prof)
    irr = bundle_reverse_recovery_current(b, prof)
    vd = b.get(prof.v_diode)
    _, ha = turn_on_current_hb_ha_t(b.t, ic, on0, on1, b.dt)
    ha_d = turn_on_didt_ha_at_turn_on(b.t, ic, on0, on1, b.dt)
    mk = err_energy_markers(b.t, irr, vd, rr0, rr1, b.dt, i_search_end=on1)
    e_chk = integrate_err_recovery(b.t, vd, irr, mk.as_integration_window())
    problems: list[str] = []
    if abs(ha - ha_d) >= 1.0:
        problems.append(f"on_ha偏差={abs(ha - ha_d):.2f}A")
    if not (
        r.reverse_recovery.err > 0.2
        and abs(r.reverse_recovery.err - e_chk) < 0.01
    ):
        problems.append(f"Err校验={r.reverse_recovery.err:.3f}/{e_chk:.3f}mJ")
    if abs(mk.hb_a) >= 50.0:
        problems.append(f"Err Hb={mk.hb_a:.2f}A")
    status = "WARN" if problems else "OK"
    detail = (
        f"profile={prof.code} "
        f"err={r.reverse_recovery.err:.3f} "
        f"hb={mk.hb_a:.2f} "
        f"on_ha={ha:.1f} "
        f"didt_ha={ha_d:.1f}"
    )
    if problems:
        detail += " | " + "; ".join(problems)
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
        "sc_ok": 0,
        "sc_warn": 0,
        "failed": 0,
    }
    print(f"发现 TSS 样本 {len(samples)} 个，开始兼容性扫描...")
    for path in samples:
        result = _validate_sample(path)
        if result.failed:
            stats["failed"] += 1
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
    warnings = stats["dpt_warn"] + stats["sc_warn"]
    print(
        "扫描完成："
        f"total={len(samples)} "
        f"dpt_ok={stats['dpt_ok']} "
        f"dpt_warn={stats['dpt_warn']} "
        f"sc_ok={stats['sc_ok']} "
        f"sc_warn={stats['sc_warn']} "
        f"failed={stats['failed']} "
        f"warnings={warnings}"
    )
    if args.strict and stats["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
