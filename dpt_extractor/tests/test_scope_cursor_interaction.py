"""Real mouse-event checks for thin scope cursor interaction."""

from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyqtgraph as pg
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from dpt_extractor.gui.waveform_plot import ScopeCursorLine


class TestScopeCursorInteraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        self.plot = pg.PlotWidget()
        self.plot.resize(1000, 700)
        self.plot.setRange(xRange=(-1.0, 1.0), yRange=(-1.0, 1.0), padding=0.0)
        view_box = self.plot.getPlotItem().getViewBox()
        view_box.setBorder(None)
        view_box.borderRect.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        view_box.borderRect.hide()
        self.lines = {
            "A": ScopeCursorLine(
                "A", pos=-0.35, angle=90, movable=True,
                pen=pg.mkPen("#FFFFFF", width=1),
                hoverPen=pg.mkPen("#FFFFFF", width=2),
            ),
            "B": ScopeCursorLine(
                "B", pos=0.35, angle=90, movable=True,
                pen=pg.mkPen("#FFFFFF", width=1),
                hoverPen=pg.mkPen("#FFFFFF", width=2),
            ),
            "Ha": ScopeCursorLine(
                "Ha", pos=0.35, angle=0, movable=True,
                pen=pg.mkPen("#FFFFFF", width=1),
                hoverPen=pg.mkPen("#FFFFFF", width=2),
            ),
            "Hb": ScopeCursorLine(
                "Hb", pos=-0.35, angle=0, movable=True,
                pen=pg.mkPen("#FFFFFF", width=1),
                hoverPen=pg.mkPen("#FFFFFF", width=2),
            ),
        }
        for line in self.lines.values():
            line.setZValue(50)
            self.plot.addItem(line)
        self.plot.show()
        self.plot.raise_()
        self.plot.activateWindow()
        self.plot.viewport().setFocus()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.plot.close()
        self.app.processEvents()

    def _line_point(self, line: ScopeCursorLine, offset_px: int = 0) -> QPoint:
        view_box = self.plot.getPlotItem().getViewBox()
        x_range, y_range = view_box.viewRange()
        if line.angle % 180 == 0:
            scene = view_box.mapViewToScene(
                QPointF(x_range[0] + 0.73 * (x_range[1] - x_range[0]), line.value())
            )
            offset = QPoint(0, offset_px)
        else:
            scene = view_box.mapViewToScene(
                QPointF(line.value(), y_range[0] + 0.82 * (y_range[1] - y_range[0]))
            )
            offset = QPoint(offset_px, 0)
        plot_point = self.plot.mapFromScene(scene)
        viewport_point = self.plot.viewport().mapFrom(self.plot, plot_point)
        return viewport_point + offset

    def _drag(self, line: ScopeCursorLine, offset_px: int, delta_px: int) -> None:
        viewport = self.plot.viewport()
        press = self._line_point(line, offset_px)
        if line.angle % 180 == 0:
            release = press + QPoint(0, delta_px)
            expected_cursor = Qt.CursorShape.SizeVerCursor
        else:
            release = press + QPoint(delta_px, 0)
            expected_cursor = Qt.CursorShape.SizeHorCursor
        before = float(line.value())

        QTest.mouseMove(viewport, QPoint(1, 1))
        QTest.qWait(20)
        self.app.processEvents()
        QTest.mouseMove(viewport, press)
        QTest.qWait(40)
        self.app.processEvents()
        plot_point = viewport.mapTo(self.plot, press)
        scene_point = self.plot.mapToScene(plot_point)
        local_point = line.mapFromScene(scene_point)
        scene_items = [
            (
                getattr(item, "_cursor_id", type(item).__name__),
                item.zValue(),
                type(item.parentItem()).__name__ if item.parentItem() is not None else None,
                item.acceptHoverEvents(),
                int(item.acceptedMouseButtons().value),
            )
            for item in self.plot.scene().items(scene_point)
        ]
        hover_items = [
            getattr(item, "_cursor_id", type(item).__name__)
            for item in self.plot.scene().hoverItems
        ]
        last_hover = self.plot.scene().lastHoverEvent
        self.assertTrue(
            line.mouseHovering,
            msg=(
                f"offset={offset_px}px press={press} plot={plot_point} "
                f"scene={scene_point} local={local_point} "
                f"bounds={line.boundingRect()} shape={line.shape().contains(local_point)} "
                f"items={scene_items} hover={hover_items} "
                f"last={last_hover.scenePos() if last_hover is not None else None} "
                f"buttons={QApplication.mouseButtons()} cursor={QCursor.pos()} "
                f"target={viewport.mapToGlobal(press)}"
            ),
        )
        self.assertTrue(line.hasCursor(), msg=f"offset={offset_px}px")
        self.assertEqual(line.cursor().shape(), expected_cursor)
        QTest.mousePress(
            viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, press
        )
        QTest.qWait(40)
        QTest.mouseMove(viewport, release, delay=40)
        QTest.qWait(40)
        QTest.mouseRelease(
            viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, release
        )
        QTest.qWait(40)
        self.app.processEvents()
        self.assertNotAlmostEqual(float(line.value()), before, places=6)

    def test_real_drag_uses_16px_hit_band_without_thickening_lines(self) -> None:
        for line in self.lines.values():
            self.assertEqual(line.pen.width(), 1)
            self.assertEqual(line.hoverPen.width(), 2)

        self._drag(self.lines["Ha"], 0, 35)
        self._drag(self.lines["Hb"], 4, -35)
        self._drag(self.lines["A"], 7, 35)
        self._drag(self.lines["B"], -7, -35)

    def test_locked_slope_ab_ignore_real_drag_and_clear_resize_cursor(self) -> None:
        viewport = self.plot.viewport()
        for name in ("A", "B"):
            line = self.lines[name]
            line.setMovable(False)
            before = float(line.value())
            press = self._line_point(line)
            release = press + QPoint(35, 0)

            QTest.mouseMove(viewport, press)
            QTest.qWait(40)
            self.app.processEvents()
            self.assertFalse(line.mouseHovering)
            self.assertFalse(line.hasCursor())
            QTest.mousePress(
                viewport,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                press,
            )
            QTest.qWait(40)
            QTest.mouseMove(viewport, release, delay=40)
            QTest.qWait(40)
            QTest.mouseRelease(
                viewport,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                release,
            )
            QTest.qWait(40)
            self.app.processEvents()
            self.assertAlmostEqual(float(line.value()), before, places=12)


if __name__ == "__main__":
    unittest.main()
