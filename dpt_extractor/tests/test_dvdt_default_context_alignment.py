"""Default turn-on/RR dv/dt cards must share one numeric and GUI context."""

from __future__ import annotations

import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
TARGET = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "HT"
    / "UH_750V_1048A_000.tss"
)
NDE36_RT_UH2 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "NDE36_MCU24A1"
    / "SMC"
    / "RT"
    / "UH2_915V_400A_000.tss"
)
RR_LOCAL_VIEW_TARGET = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "RT"
    / "UH_600V_403A_000.tss"
)
WANGLIHUI_HT_TARGETS = (
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "20260729"
        / "UH_HT_Rgon3.33R_Rgoff8.92R"
        / "UH_486V_950A_Rgon3.33R_Rgoff8.92R_000.tss",
        0.7293554360160139,
        27.275863829518315,
        27.7900164380851,
    ),
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "20260729"
        / "UL_HT_Rgon2.267R_Rgoff7.5R"
        / "UL_486V_950A_Rgon2.267R_Rgoff7.5R_000.tss",
        0.894175273833987,
        26.286128080946867,
        26.709087662884734,
    ),
)


class TestDvdtStablePlatformFailClosed(unittest.TestCase):
    def test_missing_platform_edge_never_falls_back_to_zero_origin_or_max_slope(
        self,
    ) -> None:
        from unittest.mock import patch

        from dpt_extractor.config.loader import load_config
        from dpt_extractor.metrics.slopes import (
            rr_dvdt_measurement_context,
            turn_off_dvdt_measurement_context,
            turn_on_dvdt_measurement_context,
        )

        t = np.arange(1_200, dtype=np.float64) * 1e-9
        flat = np.full(len(t), 12.0, dtype=np.float64)
        cfg = load_config()
        with patch(
            "dpt_extractor.metrics.slopes.dvdt_max",
            return_value=123.456,
        ):
            turn_on = turn_on_dvdt_measurement_context(
                t,
                flat,
                750.0,
                100,
                800,
                1e-9,
                cfg,
                0.90,
                0.10,
                event_end_idx=1_000,
            )
            turn_off = turn_off_dvdt_measurement_context(
                t,
                flat,
                100,
                800,
                1e-9,
                cfg,
                0.10,
                0.90,
            )
            recovery = rr_dvdt_measurement_context(
                t,
                -flat,
                100,
                800,
                1e-9,
                cfg,
                0.10,
                0.90,
                event_end_idx=1_000,
                pulse_end_idx=1_100,
            )

        for context in (turn_on, turn_off, recovery):
            with self.subTest(context=context):
                self.assertTrue(context.used_fallback)
                self.assertAlmostEqual(context.base_v, 12.0, places=9)
                self.assertAlmostEqual(context.top_v, 12.0, places=9)
                self.assertEqual(context.crossing.dvdt, 0.0)
                self.assertIsNone(context.crossing.t_pct_a_s)
                self.assertIsNone(context.crossing.t_pct_b_s)


@unittest.skipUnless(TARGET.exists(), "songzhenxi 20260717 HT target sample missing")
class TestDvdtDefaultContextAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    @classmethod
    def _events(cls) -> None:
        for _ in range(3):
            cls.app.processEvents()

    def _assert_plot_matches_context(self, win, section: str, context) -> None:
        plot = win.wave_plot
        channel = "v_diode" if section == "反向恢复" else "vce"
        self.assertIsNotNone(plot._h_cursor_a)
        self.assertIsNotNone(plot._h_cursor_b)
        self.assertIsNotNone(plot._cursor_a)
        self.assertIsNotNone(plot._cursor_b)
        assert plot._h_cursor_a is not None and plot._h_cursor_b is not None
        assert plot._cursor_a is not None and plot._cursor_b is not None

        ha = plot._from_disp(channel, float(plot._h_cursor_a.value()))
        hb = plot._from_disp(channel, float(plot._h_cursor_b.value()))
        self.assertAlmostEqual(ha, float(context.top_v), places=9)
        self.assertAlmostEqual(hb, float(context.base_v), places=9)

        self.assertIsNotNone(context.crossing.t_pct_a_s)
        self.assertIsNotNone(context.crossing.t_pct_b_s)
        assert context.crossing.t_pct_a_s is not None
        assert context.crossing.t_pct_b_s is not None
        self.assertAlmostEqual(
            float(plot._cursor_a.value()),
            float(context.crossing.t_pct_a_s) * 1e6,
            places=8,
        )
        self.assertAlmostEqual(
            float(plot._cursor_b.value()),
            float(context.crossing.t_pct_b_s) * 1e6,
            places=8,
        )

        raw = np.asarray(win.bundle.get(getattr(win.profile, channel)), dtype=np.float64)
        if section == "反向恢复":
            raw = np.abs(raw)
        self.assertAlmostEqual(
            float(np.interp(context.crossing.t_pct_a_s, win.bundle.t, raw)),
            float(context.crossing.th_a),
            places=7,
        )
        self.assertAlmostEqual(
            float(np.interp(context.crossing.t_pct_b_s, win.bundle.t, raw)),
            float(context.crossing.th_b),
            places=7,
        )

    def test_target_default_dvdt_cards_match_pipeline_values_and_raw_crossings(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win.resize(1600, 1000)
            win.show()
            self._events()
            win._load_file(str(TARGET))
            self._events()
            self.assertIsNotNone(win.result)
            assert win.result is not None
            result_before = deepcopy(win.result)

            on_interval = win._parameter_interval_us("开通", "dv/dt")
            self.assertIsNotNone(on_interval)
            assert on_interval is not None
            on_context = win._turn_on_dvdt_context(*on_interval)
            self.assertIsNotNone(on_context)
            assert on_context is not None
            self.assertAlmostEqual(on_context.base_v, 11.609375, places=9)
            self.assertAlmostEqual(on_context.top_v, 748.0, places=9)
            self.assertAlmostEqual(
                on_context.crossing.dvdt,
                2.1041710329819425,
                places=12,
            )
            self.assertAlmostEqual(
                on_context.crossing.dvdt,
                win.result.turn_on.dvdt,
                places=12,
            )
            self.assertAlmostEqual(
                float(on_context.crossing.t_pct_a_s) * 1e6,
                20.576103514045492,
                places=8,
            )
            self.assertAlmostEqual(
                float(on_context.crossing.t_pct_b_s) * 1e6,
                20.85607719050331,
                places=8,
            )
            win._on_value_clicked("开通", "dv/dt")
            self._events()
            self._assert_plot_matches_context(win, "开通", on_context)

            rr_context = win._rr_dvdt_context()
            self.assertIsNotNone(rr_context)
            assert rr_context is not None
            self.assertAlmostEqual(rr_context.base_v, 8.859375, places=9)
            self.assertAlmostEqual(rr_context.top_v, 720.015625, places=9)
            self.assertAlmostEqual(
                win.result.reverse_recovery.vrr,
                1025.0,
                places=9,
            )
            self.assertGreater(
                win.result.reverse_recovery.vrr,
                rr_context.top_v,
            )
            self.assertAlmostEqual(
                rr_context.crossing.dvdt,
                18.05629729392376,
                places=12,
            )
            self.assertAlmostEqual(
                rr_context.crossing.dvdt,
                win.result.reverse_recovery.dvdt_max,
                places=12,
            )
            self.assertAlmostEqual(
                float(rr_context.crossing.t_pct_a_s) * 1e6,
                20.75995017145558,
                places=8,
            )
            self.assertAlmostEqual(
                float(rr_context.crossing.t_pct_b_s) * 1e6,
                20.79145856937011,
                places=8,
            )
            win._on_value_clicked("反向恢复", "dv/dt")
            self._events()
            self._assert_plot_matches_context(win, "反向恢复", rr_context)

            # Selecting a default card is display-only and cannot silently
            # rewrite the pipeline values it is supposed to explain.
            self.assertEqual(win.result, result_before)
        finally:
            win.close()
            self._events()


@unittest.skipUnless(
    NDE36_RT_UH2.exists(),
    "songzhenxi NDE36_MCU24A1 RT UH2 target sample missing",
)
class TestNde36DvdtRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    @classmethod
    def _events(cls) -> None:
        for _ in range(3):
            cls.app.processEvents()

    @unittest.skipUnless(
        RR_LOCAL_VIEW_TARGET.exists(),
        "songzhenxi 20260717 RT 403A RR local-view sample missing",
    )
    def test_rr_dvdt_reclick_keeps_user_panned_local_view(self) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QAbstractItemView

        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win.resize(1600, 1000)
            win.show()
            self._events()
            win._load_file(str(RR_LOCAL_VIEW_TARGET))
            self._events()

            table = win.result_table.table
            row = next(
                index
                for index, meta in enumerate(win.result_table._row_meta)
                if meta == ("反向恢复", "dv/dt")
            )
            cell = table.model().index(row, 4)

            def click_metric() -> None:
                table.scrollTo(
                    cell,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
                self._events()
                QTest.mouseClick(
                    table.viewport(),
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                    table.visualRect(cell).center(),
                )
                self._events()

            click_metric()
            initial = win.wave_plot.current_x_range_us()
            self.assertIsNotNone(initial)
            assert initial is not None
            span = initial[1] - initial[0]
            panned = (initial[0] + 0.12 * span, initial[1] + 0.12 * span)
            self.assertTrue(win.wave_plot.restore_local_x_window_us(panned))
            self._events()
            expected = win.wave_plot.current_x_range_us()
            self.assertIsNotNone(expected)
            assert expected is not None
            self.assertNotAlmostEqual(expected[0], initial[0], places=6)

            click_metric()
            actual = win.wave_plot.current_x_range_us()
            self.assertIsNotNone(actual)
            assert actual is not None
            self.assertAlmostEqual(actual[0], expected[0], places=9)
            self.assertAlmostEqual(actual[1], expected[1], places=9)
        finally:
            win.close()
            self._events()

    @unittest.skipUnless(
        RR_LOCAL_VIEW_TARGET.exists(),
        "songzhenxi 20260717 RT 403A parameter local-view sample missing",
    )
    def test_all_parameter_local_views_survive_switch_and_return(self) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QAbstractItemView

        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win.resize(1600, 1000)
            win.show()
            self._events()
            win._load_file(str(RR_LOCAL_VIEW_TARGET))
            self._events()

            table = win.result_table.table

            def click_metric(key: tuple[str, str]) -> None:
                row = next(
                    index
                    for index, meta in enumerate(win.result_table._row_meta)
                    if meta == key
                )
                cell = table.model().index(row, 4)
                table.scrollTo(
                    cell,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
                self._events()
                QTest.mouseClick(
                    table.viewport(),
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                    table.visualRect(cell).center(),
                )
                self._events()

            available = tuple(
                key
                for key in win.result_table._row_meta
                if not win.result.is_metric_unavailable(*key)
            )
            switch_candidates = (
                ("关断过程", "ΔVce"),
                ("开通", "ΔVce"),
            )
            self.assertTrue(all(key in available for key in switch_candidates))

            for key in available:
                with self.subTest(parameter=key):
                    click_metric(key)
                    initial = win.wave_plot.current_local_x_window_us()
                    self.assertIsNotNone(initial)
                    assert initial is not None
                    span = initial[1] - initial[0]
                    requested = (
                        initial[0] + 0.04 * span,
                        initial[1] + 0.04 * span,
                    )
                    self.assertTrue(
                        win.wave_plot.restore_local_x_window_us(requested)
                    )
                    self._events()
                    expected = win.wave_plot.current_x_range_us()
                    self.assertIsNotNone(expected)
                    assert expected is not None

                    switch_key = next(
                        candidate
                        for candidate in switch_candidates
                        if candidate != key
                    )
                    click_metric(switch_key)
                    click_metric(key)
                    actual = win.wave_plot.current_x_range_us()
                    self.assertIsNotNone(actual)
                    assert actual is not None
                    self.assertAlmostEqual(actual[0], expected[0], places=9)
                    self.assertAlmostEqual(actual[1], expected[1], places=9)

            self.assertTrue(set(available).issubset(win._parameter_local_views))
            last_saved = win.wave_plot.current_x_range_us()
            self.assertIsNotNone(last_saved)
            win._recalculate(reset_manual=True)
            self._events()
            self.assertEqual(win._parameter_local_views, {})
            recalculated = win.wave_plot.current_x_range_us()
            self.assertIsNotNone(recalculated)
            assert last_saved is not None and recalculated is not None
            self.assertNotAlmostEqual(recalculated[0], last_saved[0], places=6)
        finally:
            win.close()
            self._events()

    @unittest.skipUnless(
        RR_LOCAL_VIEW_TARGET.exists(),
        "songzhenxi 20260717 RT 403A compact parameter-view sample missing",
    )
    def test_default_platform_cursor_views_stay_at_200ns_when_content_fits(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        keys = (
            ("关断过程", "串扰电压"),
            ("开通", "串扰电压"),
            ("反向恢复", "Irr"),
            ("反向恢复", "Trr"),
            ("反向恢复", "Vrr"),
            ("反向恢复", "Pdmax"),
            ("反向恢复", "Err"),
        )
        win = MainWindow()
        try:
            win.resize(1600, 1000)
            win.show()
            self._events()
            win._load_file(str(RR_LOCAL_VIEW_TARGET))
            self._events()
            self.assertIsNotNone(win.result)
            assert win.result is not None

            for key in keys:
                with self.subTest(parameter=key):
                    self.assertFalse(win.result.is_metric_unavailable(*key))
                    win._on_value_clicked(*key)
                    self._events()
                    current = win.wave_plot.current_x_range_us()
                    self.assertIsNotNone(current)
                    assert current is not None
                    self.assertAlmostEqual(current[1] - current[0], 2.0, delta=0.02)
                    self.assertEqual(win.wave_plot._x_scale_edit.text(), "200 ns/div")
                    if (
                        win.wave_plot._cursor_a is not None
                        and win.wave_plot._cursor_b is not None
                    ):
                        a_us = float(win.wave_plot._cursor_a.value())
                        b_us = float(win.wave_plot._cursor_b.value())
                        self.assertGreaterEqual(min(a_us, b_us), current[0] - 1e-6)
                        self.assertLessEqual(max(a_us, b_us), current[1] + 1e-6)
        finally:
            win.close()
            self._events()

    @unittest.skipUnless(
        RR_LOCAL_VIEW_TARGET.exists(),
        "songzhenxi 20260717 RT 403A manual cursor sample missing",
    )
    def test_all_movable_parameter_cursors_survive_switch_and_return(self) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QAbstractItemView

        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win.resize(1600, 1000)
            win.show()
            self._events()
            win._load_file(str(RR_LOCAL_VIEW_TARGET))
            self._events()

            table = win.result_table.table
            plot = win.wave_plot
            cursor_attrs = (
                "_cursor_a",
                "_cursor_b",
                "_h_cursor_a",
                "_h_cursor_b",
            )

            def click_metric(key: tuple[str, str]) -> None:
                row = next(
                    index
                    for index, meta in enumerate(win.result_table._row_meta)
                    if meta == key
                )
                cell = table.model().index(row, 4)
                table.scrollTo(
                    cell,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
                self._events()
                QTest.mouseClick(
                    table.viewport(),
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                    table.visualRect(cell).center(),
                )
                self._events()

            def visible_cursor_state() -> dict[str, float]:
                return {
                    attr: float(line.value())
                    for attr in cursor_attrs
                    if (line := getattr(plot, attr)) is not None and line.isVisible()
                }

            def metric_value_text(key: tuple[str, str]) -> str:
                row = next(
                    index
                    for index, meta in enumerate(win.result_table._row_meta)
                    if meta == key
                )
                item = table.item(row, 4)
                return "" if item is None else item.text()

            available = tuple(
                key
                for key in win.result_table._row_meta
                if not win.result.is_metric_unavailable(*key)
            )
            switch_candidates = (
                ("关断过程", "ΔVce"),
                ("开通", "ΔVce"),
            )

            audited: set[tuple[str, str]] = set()
            for key in available:
                with self.subTest(parameter=key):
                    click_metric(key)
                    x_range, y_range = plot.plot.getPlotItem().getViewBox().viewRange()
                    x_delta = 0.012 * (float(x_range[1]) - float(x_range[0]))
                    y_delta = 0.012 * (float(y_range[1]) - float(y_range[0]))
                    moved = False
                    for attr in cursor_attrs:
                        line = getattr(plot, attr)
                        if (
                            line is None
                            or not line.isVisible()
                            or not bool(getattr(line, "movable", False))
                        ):
                            continue
                        delta = y_delta if line.angle % 180 == 0 else x_delta
                        before = float(line.value())
                        line.setValue(before + delta)
                        self._events()
                        moved = moved or not np.isclose(
                            float(line.value()), before, rtol=0.0, atol=1e-9
                        )
                    if not moved:
                        continue
                    audited.add(key)
                    expected = visible_cursor_state()
                    expected_value = metric_value_text(key)

                    switch_key = next(
                        candidate
                        for candidate in switch_candidates
                        if candidate != key
                    )
                    click_metric(switch_key)
                    click_metric(key)
                    actual = visible_cursor_state()
                    self.assertEqual(actual.keys(), expected.keys())
                    for attr, value in expected.items():
                        self.assertAlmostEqual(actual[attr], value, places=6)
                    self.assertEqual(metric_value_text(key), expected_value)

            self.assertGreaterEqual(len(audited), 24)
        finally:
            win.close()
            self._events()

    @unittest.skipUnless(
        RR_LOCAL_VIEW_TARGET.exists(),
        "songzhenxi 20260717 RT 403A real RR drag sample missing",
    )
    def test_rr_dvdt_real_horizontal_drag_survives_parameter_switch(self) -> None:
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QAbstractItemView

        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win.resize(1600, 1000)
            win.show()
            self._events()
            win._load_file(str(RR_LOCAL_VIEW_TARGET))
            self._events()
            table = win.result_table.table

            def click_metric(key: tuple[str, str]) -> None:
                row = next(
                    index
                    for index, meta in enumerate(win.result_table._row_meta)
                    if meta == key
                )
                cell = table.model().index(row, 4)
                table.scrollTo(
                    cell,
                    QAbstractItemView.ScrollHint.PositionAtCenter,
                )
                self._events()
                QTest.mouseClick(
                    table.viewport(),
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                    table.visualRect(cell).center(),
                )
                self._events()

            rr_key = ("反向恢复", "dv/dt")
            click_metric(rr_key)
            plot = win.wave_plot
            line = plot._h_cursor_a
            self.assertIsNotNone(line)
            assert line is not None
            self.assertTrue(line.isVisible())
            self.assertTrue(bool(getattr(line, "movable", False)))

            view_box = plot.plot.getPlotItem().getViewBox()
            x_range, _y_range = view_box.viewRange()
            scene = view_box.mapViewToScene(
                QPointF(
                    float(x_range[0])
                    + 0.73 * (float(x_range[1]) - float(x_range[0])),
                    float(line.value()),
                )
            )
            plot_point = plot.plot.mapFromScene(scene)
            press = plot.plot.viewport().mapFrom(plot.plot, plot_point)
            release = press + QPoint(0, -32)
            before = float(line.value())

            QTest.mouseMove(plot.plot.viewport(), QPoint(1, 1))
            QTest.qWait(20)
            QTest.mouseMove(plot.plot.viewport(), press)
            QTest.qWait(40)
            QTest.mousePress(
                plot.plot.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                press,
            )
            QTest.mouseMove(plot.plot.viewport(), release, delay=40)
            QTest.mouseRelease(
                plot.plot.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                release,
            )
            QTest.qWait(40)
            self._events()
            dragged = float(line.value())
            self.assertNotAlmostEqual(dragged, before, places=6)
            saved_value = float(win.result.reverse_recovery.dvdt_max)
            saved_view = plot.current_x_range_us()

            click_metric(("开通", "Eon"))
            click_metric(rr_key)
            assert plot._h_cursor_a is not None
            self.assertAlmostEqual(float(plot._h_cursor_a.value()), dragged, places=6)
            self.assertAlmostEqual(
                float(win.result.reverse_recovery.dvdt_max),
                saved_value,
                places=9,
            )
            self.assertEqual(plot.current_x_range_us(), saved_view)
        finally:
            win.close()
            self._events()

    def test_three_dvdt_defaults_use_stable_platforms_not_peak_values(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win._load_file(str(NDE36_RT_UH2))
            self.assertIsNotNone(win.result)
            assert win.result is not None

            off_interval = win._parameter_interval_us("关断过程", "dv/dt")
            on_interval = win._parameter_interval_us("开通", "dv/dt")
            self.assertIsNotNone(off_interval)
            self.assertIsNotNone(on_interval)
            assert off_interval is not None and on_interval is not None
            contexts = {
                "关断过程": win._turn_off_dvdt_context(*off_interval),
                "开通": win._turn_on_dvdt_context(*on_interval),
                "反向恢复": win._rr_dvdt_context(),
            }
            for context in contexts.values():
                self.assertIsNotNone(context)
            off = contexts["关断过程"]
            on = contexts["开通"]
            rr = contexts["反向恢复"]
            assert off is not None and on is not None and rr is not None

            expected = {
                "关断过程": (19.71875, 932.03125, 7.047363085544232),
                "开通": (19.75, 927.984375, 5.883471874936103),
                "反向恢复": (5.03125, 900.359375, 8.486742593527238),
            }
            for section, context in contexts.items():
                assert context is not None
                base_v, top_v, dvdt = expected[section]
                self.assertAlmostEqual(context.base_v, base_v, places=9)
                self.assertAlmostEqual(context.top_v, top_v, places=9)
                self.assertAlmostEqual(context.crossing.dvdt, dvdt, places=12)
                self.assertFalse(context.used_fallback)

            # Peak/overshoot metrics remain independent and must not become
            # the horizontal Top cursor for any of the three dv/dt cards.
            self.assertGreater(win.result.turn_off.vce_off_max, off.top_v)
            self.assertGreater(win.result.turn_on.vce_on_max, on.top_v)
            self.assertGreater(win.result.reverse_recovery.vrr, rr.top_v)
            self.assertAlmostEqual(
                win.result.turn_off.dvdt,
                off.crossing.dvdt,
                places=12,
            )
            self.assertAlmostEqual(win.result.turn_on.dvdt, on.crossing.dvdt, places=12)
            self.assertAlmostEqual(
                win.result.reverse_recovery.dvdt_max,
                rr.crossing.dvdt,
                places=12,
            )
        finally:
            win.close()
            self._events()

    def test_manual_dvdt_reclick_refocuses_when_another_card_moved_the_view(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win.resize(1600, 1000)
            win.show()
            self._events()
            win._load_file(str(NDE36_RT_UH2))
            self._events()

            win._on_result_value_clicked("开通", "dv/dt")
            self._events()
            plot = win.wave_plot
            assert plot._h_cursor_a is not None and plot._h_cursor_b is not None
            initial_ha = plot._from_disp("vce", float(plot._h_cursor_a.value()))
            initial_hb = plot._from_disp("vce", float(plot._h_cursor_b.value()))
            manual_ha = initial_hb + 0.95 * (initial_ha - initial_hb)
            plot._h_cursor_a.setValue(plot._to_disp("vce", manual_ha))
            self._events()
            self.assertIn(("开通", "dv/dt"), win._manual_dvdt)

            win._on_result_value_clicked("关断过程", "Eoff")
            self._events()
            assert plot._cursor_a is not None and plot._cursor_b is not None
            eoff_window = plot.current_x_range_us()
            self.assertIsNotNone(eoff_window)

            win._on_result_value_clicked("开通", "dv/dt")
            self._events()
            ta_us = float(plot._cursor_a.value())
            tb_us = float(plot._cursor_b.value())
            self.assertTrue(plot.current_local_x_window_contains_us(ta_us, tb_us))
            self.assertTrue(plot._cursor_a.isVisible())
            self.assertTrue(plot._cursor_b.isVisible())
            self.assertTrue(plot._h_cursor_a.isVisible())
            self.assertTrue(plot._h_cursor_b.isVisible())
            self.assertTrue(plot._cursor_a_t_label.isVisible())
            self.assertTrue(plot._cursor_b_t_label.isVisible())
            self.assertTrue(plot._cursor_ha_v_label.isVisible())
            self.assertTrue(plot._cursor_hb_v_label.isVisible())
            self.assertIn("A", plot._readout_label.text())
            self.assertIn("Ha", plot._readout_label.text())
            restored_ha = plot._from_disp("vce", float(plot._h_cursor_a.value()))
            self.assertAlmostEqual(restored_ha, manual_ha, places=9)
        finally:
            win.close()
            self._events()

    def test_eoff_uses_local_vce_platform_and_restores_reference_cursors(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win.resize(1600, 1000)
            win.show()
            self._events()
            win._load_file(str(NDE36_RT_UH2))
            self._events()

            win._on_result_value_clicked("关断过程", "Eoff")
            self._events()
            plot = win.wave_plot
            assert plot._cursor_a is not None and plot._cursor_b is not None
            assert plot._h_cursor_a is not None and plot._h_cursor_b is not None
            default_a_us = float(plot._cursor_a.value())
            default_ha_v = plot._from_disp("vce", float(plot._h_cursor_a.value()))
            self.assertAlmostEqual(default_a_us, 4.545344155194873, places=8)
            self.assertAlmostEqual(default_ha_v, 19.74805400683488, places=8)
            self.assertLess(default_ha_v, 30.0)
            interpolated_vce = float(
                np.interp(
                    default_a_us * 1e-6,
                    win.bundle.t,
                    win.bundle.get(win.profile.vce),
                )
            )
            self.assertAlmostEqual(interpolated_vce, default_ha_v, places=6)
            assert win.result is not None
            self.assertAlmostEqual(win.result.turn_off.eoff, 40.02418711899071, places=8)

            # Operator-confirmed NDE36 reference from the real waveform view.
            # Manual cursors are intentionally independent after dragging.
            plot._h_cursor_a.setValue(plot._to_disp("vce", 18.187))
            plot._h_cursor_b.setValue(plot._to_disp("ic", 14.151))
            plot._cursor_a.setValue(4.509)
            plot._cursor_b.setValue(4.913)
            self._events()
            self.assertAlmostEqual(
                win.result.turn_off.eoff,
                40.391310782760655,
                places=8,
            )
            self.assertAlmostEqual(
                win.result.turn_off.pmax,
                346.404740234375,
                places=8,
            )
            self.assertIn(("关断过程", "Eoff"), win._manual_energy)

            # Move the local X window to another switching event, then re-enter
            # Eoff.  The saved A/B/Ha/Hb must all become visible again.
            win._on_result_value_clicked("开通", "Eon")
            self._events()
            win._on_result_value_clicked("关断过程", "Eoff")
            self._events()
            assert plot._cursor_a is not None and plot._cursor_b is not None
            assert plot._h_cursor_a is not None and plot._h_cursor_b is not None
            self.assertAlmostEqual(float(plot._cursor_a.value()), 4.509, places=9)
            self.assertAlmostEqual(float(plot._cursor_b.value()), 4.913, places=9)
            self.assertAlmostEqual(
                plot._from_disp("vce", float(plot._h_cursor_a.value())),
                18.187,
                places=9,
            )
            self.assertAlmostEqual(
                plot._from_disp("ic", float(plot._h_cursor_b.value())),
                14.151,
                places=9,
            )
            self.assertTrue(plot.current_local_x_window_contains_us(4.509, 4.913))
            self.assertTrue(plot._cursor_a.isVisible())
            self.assertTrue(plot._cursor_b.isVisible())
            self.assertTrue(plot._h_cursor_a.isVisible())
            self.assertTrue(plot._h_cursor_b.isVisible())
            self.assertTrue(plot._cursor_a_t_label.isVisible())
            self.assertTrue(plot._cursor_b_t_label.isVisible())
            self.assertTrue(plot._cursor_ha_v_label.isVisible())
            self.assertTrue(plot._cursor_hb_v_label.isVisible())
        finally:
            win.close()
            self._events()


@unittest.skipUnless(
    all(path.exists() for path, *_values in WANGLIHUI_HT_TARGETS),
    "wanglihui 20260729 HT target samples missing",
)
class TestSlowTurnOnDvdtCompletion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_ht_slow_vce_fall_uses_real_90_to_10_crossings_before_turn_off(
        self,
    ) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        for path, expected_dvdt, expected_a_us, expected_b_us in (
            WANGLIHUI_HT_TARGETS
        ):
            with self.subTest(path=str(path)):
                win = MainWindow()
                try:
                    win._load_file(str(path))
                    interval = win._parameter_interval_us("开通", "dv/dt")
                    self.assertIsNotNone(interval)
                    assert interval is not None
                    context = win._turn_on_dvdt_context(*interval)
                    self.assertIsNotNone(context)
                    assert context is not None
                    self.assertFalse(context.used_fallback)
                    self.assertAlmostEqual(
                        context.crossing.dvdt, expected_dvdt, places=12
                    )
                    self.assertAlmostEqual(
                        float(context.crossing.t_pct_a_s) * 1e6,
                        expected_a_us,
                        places=8,
                    )
                    self.assertAlmostEqual(
                        float(context.crossing.t_pct_b_s) * 1e6,
                        expected_b_us,
                        places=8,
                    )
                    self.assertAlmostEqual(
                        win.result.turn_on.dvdt,
                        context.crossing.dvdt,
                        places=12,
                    )

                    win._on_value_clicked("开通", "dv/dt")
                    self.assertIsNotNone(win.wave_plot._cursor_a)
                    self.assertIsNotNone(win.wave_plot._cursor_b)
                    self.assertAlmostEqual(
                        float(win.wave_plot._cursor_a.value()),
                        expected_a_us,
                        places=8,
                    )
                    self.assertAlmostEqual(
                        float(win.wave_plot._cursor_b.value()),
                        expected_b_us,
                        places=8,
                    )
                finally:
                    win.close()


if __name__ == "__main__":
    unittest.main()
