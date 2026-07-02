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

from dpt_extractor.models.waveform import (  # noqa: E402
    bundle_reverse_recovery_current,
    bundle_total_current,
)
from dpt_extractor.utils.sample_corpus import discover_sample_waveforms  # noqa: E402

# 每个交互参数：(section, name)。Vce_off_max 等走 generic interval（带横向峰）。
INTERACTIVE_PARAMS = [
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
    ("反向恢复", "Irr"),
    ("反向恢复", "Trr"),
    ("反向恢复", "Vrr"),
    ("反向恢复", "dv/dt"),
    ("反向恢复", "di/dt"),
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


def _abs_range(arr: np.ndarray, i0: int, i1: int) -> tuple[float, float]:
    seg = np.abs(np.asarray(arr[i0 : i1 + 1], dtype=np.float64))
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
    lo, hi = _abs_range(arr, i0, i1)
    tol = max(8.0, 0.08 * hi)
    return (lo - tol) <= abs(float(level)) <= (hi + tol)


def audit_file(MainWindow, QApplication, app, path: Path) -> list[tuple]:
    mw = MainWindow()
    mw._load_file(str(path))
    bundle = mw.bundle
    profile = mw.profile
    result = mw.result
    if bundle is None or result is None or result.segments is None:
        detail = mw.statusBar().currentMessage() if mw.statusBar() is not None else "参数未计算"
        mw.close()
        return [(path.name, "加载", "自动提取", "INFO", detail)]
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

    cap = Capture()
    cap.install(mw.wave_plot)

    rows: list[tuple] = []

    def record(section, name, status, detail):
        rows.append((path.name, section, name, status, detail))

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
        problems: list[str] = []

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
                lo, hi = _abs_range(chan[ch], w0, w1)
                problems.append(
                    f"{label}={level:.2f} 不在{ch}|值|[{lo:.1f},{hi:.1f}]"
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
            if ab is not None:
                ta, tb = ab["bound"]["t_a_us"], ab["bound"]["t_b_us"]
                check_time(ta, "A")
                check_time(tb, "B")
                ab_txt = f" A={ta:.3f} B={tb:.3f}"
            detail = f"ch={channel} Ha={top_v:.2f} Hb={base_v:.2f}{ab_txt}"

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
            if irr_ref > 1.0 and not (0.5 * irr_ref <= abs(hb_val) <= 1.3 * irr_ref):
                problems.append(f"Irr峰|Hb|={abs(hb_val):.1f} 与提取Irr={irr_ref:.1f}不符")
            detail = f"ch={ch} |Hb|={abs(hb_val):.1f} irr_ref={irr_ref:.1f}"

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
            detail = f"Ha={ha_a:.2f} |Hb|={abs(hb_a):.1f} A={ta:.3f} B={tb:.3f} pk={peak_idx}"

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

        elif name == "ΔVce":
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
                record(section, name, "INFO", "无横向峰（纯区间/时间参数）")
                continue
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
    by_file: dict[str, list[tuple]] = {}
    for r in all_rows:
        by_file.setdefault(r[0], []).append(r)

    for fn, rows in by_file.items():
        n_ok = sum(1 for r in rows if r[3] == "OK")
        n_fail = sum(1 for r in rows if r[3] == "FAIL")
        print(f"\n=== {fn}  OK={n_ok} FAIL={n_fail} ===")
        for _f, section, name, status, detail in rows:
            mark = {"OK": "OK ", "FAIL": "FAIL", "INFO": "INFO"}.get(status, status)
            print(f"  [{mark}] {section}/{name}: {detail}")

    print(f"\n总计 FAIL={len(fails)}")
    if fails:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
