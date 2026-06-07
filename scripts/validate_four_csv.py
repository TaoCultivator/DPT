"""示例波形批量验证（优先 TSS，其次 CSV）。"""
from __future__ import annotations

import argparse
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
from dpt_extractor.models.waveform import (
    bundle_reverse_recovery_current,
    bundle_total_current,
)
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.utils.sample_corpus import discover_sample_waveforms


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量验证示例波形兼容性（TSS 优先，CSV 兼容）")
    parser.add_argument("--limit", type=int, default=None, help="仅验证前 N 个样本，便于快速冒烟")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="发现失败样本时返回非零；默认只输出报告，便于训练集扫描",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    cfg = load_config()
    samples = discover_sample_waveforms(ROOT)
    if args.limit is not None:
        samples = samples[: max(0, args.limit)]
    if not samples:
        print("未发现可用于兼容性验证的 Tekscope 波形（CSV/TSS，请检查示例文件目录）")
        raise SystemExit(1)
    failed = 0
    print(f"发现样本 {len(samples)} 个，开始兼容性扫描...")
    for path in samples:
        fn = path.name
        try:
            prof = guess_profile_from_path(fn)
            b = load_waveform(path)
            r = extract_all(b, prof, cfg)
            segs = r.segments
            assert segs is not None
            on0, on1 = segs.turn_on
            rr0, rr1 = segs.reverse_recovery
            ic = bundle_total_current(b, prof)
            irr = bundle_reverse_recovery_current(b, prof)
            vd = b.get(prof.v_diode)
            hb, ha = turn_on_current_hb_ha_t(b.t, ic, on0, on1, b.dt)
            ha_d = turn_on_didt_ha_at_turn_on(b.t, ic, on0, on1, b.dt)
            mk = err_energy_markers(b.t, irr, vd, rr0, rr1, b.dt, i_search_end=on1)
            e_chk = integrate_err_recovery(b.t, vd, irr, mk.as_integration_window())
            ha_ok = abs(ha - ha_d) < 1.0
            err_ok = (
                r.reverse_recovery.err > 0.2
                and abs(r.reverse_recovery.err - e_chk) < 0.01
            )
            hb_ok = abs(mk.hb_a) < 50.0  # Hb=带符号正向导通 Vd 平台（≈0）
            line_ok = ha_ok and err_ok and hb_ok
            if not line_ok:
                failed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(fn, "ERROR", repr(exc))
            continue
        print(
            fn,
            "OK" if line_ok else "FAIL",
            f"profile={prof.code}",
            f"err={r.reverse_recovery.err:.3f}",
            f"hb={mk.hb_a:.2f}",
            f"on_ha={ha:.1f}",
            f"didt_ha={ha_d:.1f}",
        )
    print(f"扫描完成：total={len(samples)} failed={failed}")
    if args.strict and failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
