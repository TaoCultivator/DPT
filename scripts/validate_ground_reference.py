"""校验 6 通道「地参考线 / 0 值参考线」是否与显示坐标一致。

地参考线（选中通道时的 ⏚ 水平线）位于显示坐标 y = _disp_offset[ch]，
按定义应对应该通道物理量 0（raw=0 → y = 0/scale + offset = offset）。

屏幕中央 0 格横线（y=0）在导入后对齐的是波形振幅中点 (min+max)/2，不一定是物理零点。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

FILES = (
    "UH_750V_1050A_000_ALL.csv",
    "UL_750V_1050A_000_ALL.csv",
    "WH_480V_800A_000_ALL.csv",
    "WL_480V_800A_000_ALL.csv",
)

CHANNELS = ("vge", "vce", "ic", "irr", "v_diode", "vge_other")


def _load_plot(csv_name: str):
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    from dpt_extractor.config.loader import load_config
    from dpt_extractor.gui.waveform_plot import (
        WaveformPlot,
        _auto_center_offset_div,
        _auto_vdiv_for_channel,
        _downsample,
        _raw_value_span,
    )
    from dpt_extractor.io.tek_parser import TekParser
    from dpt_extractor.models.bridge_profile import guess_profile_from_path
    from dpt_extractor.models.waveform import (
        bundle_reverse_recovery_current,
        bundle_total_current,
    )
    from dpt_extractor.pipeline.extract import extract_all

    path = ROOT / csv_name
    cfg = load_config()
    bundle = TekParser().parse(path)
    profile = guess_profile_from_path(path.name)
    result = extract_all(bundle, profile, cfg)
    plot = WaveformPlot()
    plot.plot_waveforms(bundle, profile, result)

    t = bundle.t
    arrays = {
        "vge": bundle.get(profile.vge),
        "vce": bundle.get(profile.vce),
        "ic": bundle_total_current(bundle, profile),
        "irr": bundle_reverse_recovery_current(bundle, profile),
        "v_diode": bundle.get(profile.v_diode),
        "vge_other": bundle.get(profile.vge_other),
    }
    _, ds = _downsample(
        t,
        arrays["vge"],
        arrays["vce"],
        arrays["ic"],
        arrays["irr"],
        arrays["v_diode"],
        arrays["vge_other"],
    )
    down = dict(zip(CHANNELS, ds, strict=True))
    return plot, arrays, down, app


def _check_channel(plot, key: str, full_raw: np.ndarray, ds_raw: np.ndarray) -> dict:
    from dpt_extractor.gui.waveform_plot import _auto_center_offset_div, _raw_value_span

    scale = plot._disp_scale[key]
    offset = plot._disp_offset[key]
    zero_at_disp = plot._to_disp(key, 0.0)
    phys_at_center = plot._from_disp(key, 0.0)
    vmin, vmax, mid, _ = _raw_value_span(np.asarray(ds_raw, dtype=np.float64))

    full_off = _auto_center_offset_div(
        np.asarray(full_raw, dtype=np.float64), scale
    )
    ds_off = _auto_center_offset_div(np.asarray(ds_raw, dtype=np.float64), scale)

    y_plot = np.asarray(plot._trace_items[key].getData()[1], dtype=np.float64)
    raw_plot = np.asarray(plot._trace_raw[key], dtype=np.float64)
    recon = raw_plot / scale + offset
    max_recon_err = float(np.max(np.abs(y_plot - recon))) if len(y_plot) else 0.0

    tol = max(abs(scale) * 0.02, 1e-6)
    near_zero = np.abs(raw_plot) <= tol
    if np.any(near_zero):
        err_near0 = float(np.max(np.abs(y_plot[near_zero] - offset)))
    else:
        err_near0 = float("nan")

    plot._on_legend_clicked(key)
    gm_y = float(plot._ground_marker.value()) if plot._ground_marker else float("nan")
    plot._on_legend_clicked(key)

    ok_math = abs(zero_at_disp - offset) < 1e-9 and abs(phys_at_center + offset * scale) < 1e-6
    ok_recon = max_recon_err < 1e-9
    ok_marker = abs(gm_y - offset) < 1e-9
    ok_mid_grid = abs(mid / scale + offset) < 0.02
    off_drift = abs(offset - full_off)

    return {
        "ok_math": ok_math,
        "ok_recon": ok_recon,
        "ok_marker": ok_marker,
        "ok_mid_grid": ok_mid_grid,
        "offset": offset,
        "zero_at_disp": zero_at_disp,
        "phys_at_center_grid": phys_at_center,
        "mid_raw": mid,
        "vmin": vmin,
        "vmax": vmax,
        "off_drift_div": off_drift,
        "ds_vs_full_off": abs(offset - ds_off),
        "err_near0_div": err_near0,
        "max_recon_err": max_recon_err,
    }


def main() -> int:
    fails = 0
    print("=== 6 通道地参考线（物理 0 <-> 显示 offset）校验 ===\n")
    for csv in FILES:
        if not (ROOT / csv).exists():
            print(f"[SKIP] {csv} 不存在")
            continue
        plot, full, down, _ = _load_plot(csv)
        print(f"--- {csv} ---")
        row_fail = False
        for key in CHANNELS:
            r = _check_channel(plot, key, full[key], down[key])
            hard_ok = r["ok_math"] and r["ok_recon"] and r["ok_marker"]
            tag = "OK" if hard_ok else "FAIL"
            if not hard_ok:
                row_fail = True
                fails += 1
            near = (
                f"近零点贴合={r['err_near0_div']:.4f}格"
                if np.isfinite(r["err_near0_div"])
                else "波形内无|raw|≈0采样点"
            )
            print(
                f"  {tag} {key:10s} offset={r['offset']:+.3f}格 "
                f"0格处物理量={r['phys_at_center_grid']:+.2f} "
                f"振幅中点={r['mid_raw']:+.2f} "
                f"({near}; 降采样偏移差={r['off_drift_div']:.4f}格)"
            )
            if not hard_ok:
                print(
                    f"       math={r['ok_math']} recon={r['ok_recon']} "
                    f"marker={r['ok_marker']} mid@0格={r['ok_mid_grid']}"
                )
        if row_fail:
            print("  >> 本文件存在 FAIL\n")
        else:
            print("  >> 六通道换算与接地标记位置全部 OK\n")
    print("说明：")
    print("  - 地参考线(接地标记) = 物理 0，位于 y=offset 格（选中通道可见）")
    print("  - 屏幕中央 0 格 = 振幅中点，物理量一般为 phys_at_center_grid != 0")
    print("  - 近零点贴合：|raw|~0 的采样点是否落在 offset 线上（有零点才统计）")
    if fails:
        print(f"\n合计 FAIL 项: {fails}")
        return 1
    print("\n全部通道地参考线数学关系正确。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
