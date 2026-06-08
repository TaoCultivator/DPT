"""点击参数仅放大波形时，表格数值应与 extract 初值一致（上下桥四工况）。"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from dpt_extractor.config.loader import load_config
from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import (
    LOWER_BRIDGE,
    UPPER_BRIDGE,
)
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.tests.sample_paths import sample_tss

CASES = (
    ("UH", sample_tss("UH_750V_1050A_000.tss"), UPPER_BRIDGE),
    ("UL", sample_tss("UL_750V_1050A_000.tss"), LOWER_BRIDGE),
    ("WH", sample_tss("WH_480V_800A_000.tss"), UPPER_BRIDGE),
    ("WL", sample_tss("WL_480V_800A_000.tss"), LOWER_BRIDGE),
)

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


def _snapshot_metrics(win: MainWindow) -> dict[tuple[str, str], float | str]:
    out: dict[tuple[str, str], float | str] = {}
    for section, name in CLICKABLE:
        v = win._stored_param_value(section, name)
        if v is not None:
            out[(section, name)] = v
    return out


def _table_text(win: MainWindow, section: str, name: str) -> str:
    for r in range(win.result_table.table.rowCount()):
        if (
            win.result_table.table.item(r, 0).text() == section
            and win.result_table.table.item(r, 1).text() == name
        ):
            return win.result_table.table.item(r, 4).text().strip()
    raise KeyError((section, name))


class TestParamClickStable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _run_case(self, tag: str, path: Path, profile) -> None:
        if not path.is_file():
            self.skipTest(f"{tag} TSS 样本缺失")
        bundle = load_waveform(path)
        win = MainWindow()
        win.bundle = bundle
        win.profile = profile
        win.result = extract_all(bundle, profile, load_config())
        win.cfg = load_config()
        win.result_table.set_result(win.result)
        win.wave_plot.plot_waveforms(bundle, profile, win.result)
        before = _snapshot_metrics(win)
        fails: list[str] = []
        for section, name in CLICKABLE:
            try:
                table_before = _table_text(win, section, name)
            except KeyError:
                continue
            win._on_value_clicked(section, name)
            table_after = _table_text(win, section, name)
            if table_before != table_after:
                fails.append(
                    f"{section}/{name}: {table_before} -> {table_after}"
                )
            after = _snapshot_metrics(win)
            b = before.get((section, name))
            a = after.get((section, name))
            if b is None or a is None:
                continue
            if isinstance(b, str):
                if b != a:
                    fails.append(f"{section}/{name} metric {b} -> {a}")
            else:
                if abs(float(b) - float(a)) > 1e-3 * max(abs(float(b)), 1.0):
                    fails.append(
                        f"{section}/{name} metric {float(b):.6f} -> {float(a):.6f}"
                    )
        if fails:
            self.fail(f"[{tag}] 点击后数值变化:\n" + "\n".join(fails))

    def test_uh_all_params_click_stable(self):
        self._run_case(*CASES[0])

    def test_ul_all_params_click_stable(self):
        self._run_case(*CASES[1])

    def test_wh_all_params_click_stable(self):
        self._run_case(*CASES[2])

    def test_wl_all_params_click_stable(self):
        self._run_case(*CASES[3])


if __name__ == "__main__":
    unittest.main()
