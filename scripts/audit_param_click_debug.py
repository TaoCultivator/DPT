"""上下桥全参数点击审计：点击后表格数值须与 extract 一致。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication

from dpt_extractor.config.loader import load_config
from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.io.tek_parser import TekParser
from dpt_extractor.models.bridge_profile import LOWER_BRIDGE, UPPER_BRIDGE
from dpt_extractor.pipeline.extract import extract_all

CLICKABLE = [
    ("关断过程", "ΔVce"),
    ("关断过程", "Ic_off_max"),
    ("关断过程", "Vce_off_max"),
    ("关断过程", "dv/dt"),
    ("关断过程", "di/dt"),
    ("关断过程", "Ls_off"),
    ("关断过程", "Toff"),
    ("关断过程", "Td_off"),
    ("关断过程", "Tf"),
    ("关断过程", "串扰电压"),
    ("关断过程", "Eoff"),
    ("开通", "ΔVce"),
    ("开通", "Ic_on_max"),
    ("开通", "Vce_on_max"),
    ("开通", "开通电流"),
    ("开通", "dv/dt"),
    ("开通", "di/dt"),
    ("开通", "Ls_on"),
    ("开通", "Ton"),
    ("开通", "Td_on"),
    ("开通", "Tr"),
    ("开通", "串扰电压"),
    ("开通", "Eon"),
    ("反向恢复", "Irr"),
    ("反向恢复", "Trr"),
    ("反向恢复", "Vrr"),
    ("反向恢复", "dv/dt"),
    ("反向恢复", "di/dt"),
    ("反向恢复", "Err"),
]

CASES = (
    ("UH", ROOT / "UH_750V_1050A_000_ALL.csv", UPPER_BRIDGE),
    ("UL", ROOT / "UL_750V_1050A_000_ALL.csv", LOWER_BRIDGE),
    ("WH", ROOT / "WH_480V_800A_000_ALL.csv", UPPER_BRIDGE),
    ("WL", ROOT / "WL_480V_800A_000_ALL.csv", LOWER_BRIDGE),
)


def _table_text(win: MainWindow, section: str, name: str) -> str:
    for r in range(win.result_table.table.rowCount()):
        if (
            win.result_table.table.item(r, 0).text() == section
            and win.result_table.table.item(r, 1).text() == name
        ):
            return win.result_table.table.item(r, 4).text().strip()
    return ""


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    all_fails: list[str] = []
    for tag, path, profile in CASES:
        if not path.is_file():
            print(f"[{tag}] skip: no csv")
            continue
        bundle = TekParser().parse(path)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = extract_all(bundle, profile, load_config())
        win.cfg = load_config()
        win.result_table.set_result(win.result)
        win.wave_plot.plot_waveforms(bundle, profile, win.result)
        fails: list[str] = []
        for section, name in CLICKABLE:
            before = _table_text(win, section, name)
            win._on_value_clicked(section, name)
            after = _table_text(win, section, name)
            if before != after:
                fails.append(f"{section}/{name}: {before} -> {after}")
        if fails:
            print(f"[{tag}] FAIL:")
            for f in fails:
                print(f"  {f}")
            all_fails.extend(fails)
        else:
            print(f"[{tag}] OK ({len(CLICKABLE)} params)")
    return 1 if all_fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
