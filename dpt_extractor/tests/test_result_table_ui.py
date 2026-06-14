from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from dpt_extractor.gui.result_table import (
    ENERGY_TEXT_COLOR,
    SECTION_ACTIVE_BG,
    SECTION_ACTIVE_TEXT,
    ResultTable,
)
from dpt_extractor.gui.theme import SECTION_OFF, SECTION_ON, SECTION_RR
from dpt_extractor.models.results import (
    ExtractResult,
    ReverseRecoveryResult,
    SegmentIndices,
    TurnOffResult,
    TurnOnResult,
)


def _sample_result() -> ExtractResult:
    return ExtractResult(
        phase="U",
        profile_code="UH",
        source_path="UH_RT.tss",
        vdc=764.1,
        segments=SegmentIndices(
            turn_off=(0, 1),
            turn_on=(2, 3),
            reverse_recovery=(4, 5),
        ),
        turn_off=TurnOffResult(
            delta_vce=337.22,
            ic_off_max=1051.25,
            vce_off_max=1093.25,
            dvdt=7.594,
            didt=10.623,
            eoff=88.884,
            eoff_range="V↑~Ic平稳",
        ),
        turn_on=TurnOnResult(
            delta_vce=309.70,
            ic_on_max=1154.22,
            vce_on_max=763.59,
            turn_on_current=1036.12,
            dvdt=2.597,
            didt=6.565,
            eon=68.662,
        ),
        reverse_recovery=ReverseRecoveryResult(
            irr=173.91,
            trr=35.496,
            vrr=985.03,
            dvdt_max=12.971,
            didt_irr=13.738,
            err=1.116,
        ),
    )


def _row_for(table: ResultTable, section: str, name: str) -> int:
    for row, meta in enumerate(table._row_meta):
        if meta == (section, name):
            return row
    raise AssertionError(f"missing row: {section}/{name}")


class TestResultTableUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_section_labels_stack_energy_rows_and_active_section(self) -> None:
        table = ResultTable()
        table.set_result(_sample_result())
        self.assertGreaterEqual(table.summary.text().count(ENERGY_TEXT_COLOR), 6)

        on_start, _ = table._section_ranges["开通"]
        rr_start, _ = table._section_ranges["反向恢复"]
        self.assertEqual(
            table.table.item(on_start, 0).data(Qt.ItemDataRole.DisplayRole),
            "开\n通",
        )
        self.assertEqual(
            table.table.item(rr_start, 0).data(Qt.ItemDataRole.DisplayRole),
            "反\n向\n恢\n复",
        )

        for section, name, expected_bg in (
            ("关断过程", "Eoff", SECTION_OFF),
            ("开通", "Eon", SECTION_ON),
            ("反向恢复", "Err", SECTION_RR),
        ):
            row = _row_for(table, section, name)
            self.assertEqual(table.table.item(row, 1).background().color().name(), expected_bg)
            self.assertEqual(
                table.table.item(row, 4).foreground().color().name(),
                ENERGY_TEXT_COLOR,
            )

        table.set_active_metric("开通", "di/dt")
        self.assertEqual(table.table.currentRow(), _row_for(table, "开通", "di/dt"))
        self.assertEqual(
            table.table.item(on_start, 0).background().color().name(),
            SECTION_ACTIVE_BG,
        )
        self.assertEqual(
            table.table.item(on_start, 0).foreground().color().name(),
            SECTION_ACTIVE_TEXT,
        )
        table.close()


if __name__ == "__main__":
    unittest.main()
