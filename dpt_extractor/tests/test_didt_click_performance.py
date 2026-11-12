"""Regression coverage for the di/dt parameter-click UI hot path."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QAbstractItemView

from dpt_extractor.gui.main_window import MainWindow


ROOT = Path(__file__).resolve().parents[2]
TARGET = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "RT"
    / "UH_750V_806A_000.tss"
)


@unittest.skipUnless(TARGET.exists(), "songzhenxi 806A di/dt click sample missing")
class TestDidtClickPerformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        self.win = MainWindow()
        self.win.resize(1600, 1000)
        self.win.show()
        self.app.processEvents()
        self.win._load_file(str(TARGET))
        self.app.processEvents()

    def tearDown(self) -> None:
        self.win.close()
        self.app.processEvents()

    def _click_metric(self, section: str, name: str) -> None:
        table = self.win.result_table.table
        row = next(
            row
            for row, meta in enumerate(self.win.result_table._row_meta)
            if meta == (section, name)
        )
        index = table.model().index(row, 4)
        table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.app.processEvents()
        QTest.mouseClick(
            table.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            table.visualRect(index).center(),
        )

    def test_real_turn_off_didt_click_reuses_extracted_context(self) -> None:
        result = self.win.result
        self.assertIsNotNone(result)
        assert result is not None
        key = ("关断过程", "di/dt")
        context = result.didt_contexts.get(key)
        self.assertIsNotNone(context)
        assert context is not None
        value_before = float(result.turn_off.didt)

        with patch.object(
            self.win,
            "_turn_off_didt_context",
            side_effect=AssertionError(
                "a parameter click repeated the extracted turn-off di/dt analysis"
            ),
        ):
            started = time.perf_counter()
            self._click_metric(*key)
            self.app.processEvents()
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 1.0)
        self.assertEqual(float(result.turn_off.didt), value_before)
        self.assertIs(self.win._extracted_didt_context("关断过程"), context)
        self.assertIsNotNone(self.win.wave_plot._cursor_a)
        self.assertIsNotNone(self.win.wave_plot._cursor_b)
        assert self.win.wave_plot._cursor_a is not None
        assert self.win.wave_plot._cursor_b is not None
        self.assertAlmostEqual(
            float(self.win.wave_plot._cursor_a.value()),
            float(context.crossing.t_pct_a_s) * 1e6,
            places=9,
        )
        self.assertAlmostEqual(
            float(self.win.wave_plot._cursor_b.value()),
            float(context.crossing.t_pct_b_s) * 1e6,
            places=9,
        )

    def test_mismatched_context_metadata_falls_back_to_rebuild(self) -> None:
        result = self.win.result
        self.assertIsNotNone(result)
        assert result is not None
        context = result.didt_contexts[("关断过程", "di/dt")]
        result.turn_off.didt_range += " stale"

        with patch.object(
            self.win,
            "_turn_off_didt_context",
            return_value=context,
        ) as rebuild:
            self.win._on_value_clicked("关断过程", "di/dt")

        rebuild.assert_called_once()

    def test_all_visible_parameter_clicks_remain_responsive(self) -> None:
        """Every displayed result-card click must stay off slow rebuild paths."""

        result = self.win.result
        self.assertIsNotNone(result)
        assert result is not None
        result_before = deepcopy(result)
        timings: dict[tuple[str, str], float] = {}

        with (
            patch.object(
                self.win,
                "_turn_off_didt_context",
                side_effect=AssertionError(
                    "a parameter click repeated turn-off di/dt extraction"
                ),
            ),
            patch.object(
                self.win,
                "_turn_on_didt_context",
                side_effect=AssertionError(
                    "a parameter click repeated turn-on di/dt extraction"
                ),
            ),
            patch.object(
                self.win,
                "_turn_off_dvdt_context",
                side_effect=AssertionError(
                    "a parameter click repeated turn-off dv/dt extraction"
                ),
            ),
            patch.object(
                self.win,
                "_turn_on_dvdt_context",
                side_effect=AssertionError(
                    "a parameter click repeated turn-on dv/dt extraction"
                ),
            ),
            patch.object(
                self.win,
                "_rr_dvdt_context",
                side_effect=AssertionError(
                    "a parameter click repeated reverse-recovery dv/dt extraction"
                ),
            ),
            patch(
                "dpt_extractor.gui.main_window.eoff_energy_markers",
                side_effect=AssertionError(
                    "a parameter click repeated Eoff marker extraction"
                ),
            ),
            patch(
                "dpt_extractor.gui.main_window.eon_energy_markers",
                side_effect=AssertionError(
                    "a parameter click repeated Eon marker extraction"
                ),
            ),
            patch(
                "dpt_extractor.gui.main_window.err_energy_markers",
                side_effect=AssertionError(
                    "a parameter click repeated Err marker extraction"
                ),
            ),
            patch(
                "dpt_extractor.gui.main_window.eoff_window_scope_example",
                side_effect=AssertionError(
                    "a parameter click repeated Eoff window extraction"
                ),
            ),
            patch(
                "dpt_extractor.gui.main_window.eon_window_scope_example",
                side_effect=AssertionError(
                    "a parameter click repeated Eon window extraction"
                ),
            ),
        ):
            for section, name in tuple(self.win.result_table._row_meta):
                if result.is_metric_unavailable(section, name):
                    continue
                started = time.perf_counter()
                self._click_metric(section, name)
                self.app.processEvents()
                timings[(section, name)] = time.perf_counter() - started

        slow = {
            key: elapsed
            for key, elapsed in timings.items()
            if elapsed >= 1.0
        }
        self.assertFalse(slow, f"slow parameter clicks: {slow}")
        self.assertIn(("关断过程", "Ls_off"), timings)
        self.assertIn(("开通", "Ls_on"), timings)
        self.assertEqual(result, result_before)


if __name__ == "__main__":
    unittest.main()
