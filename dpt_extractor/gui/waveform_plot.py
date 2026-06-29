from __future__ import annotations

import ast
from dataclasses import replace
import os
import re

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QFont,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGraphicsRectItem,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QGraphicsItem,
    QVBoxLayout,
    QWidget,
)


def _pyqtgraph_config_options() -> dict[str, object]:
    opts: dict[str, object] = {
        "antialias": False,
        "background": WAVEFORM_PLOT_BG,
        "foreground": WAVEFORM_PLOT_FG,
    }
    accel = os.environ.get("DPT_PLOT_ACCEL", "").strip().lower()
    if accel in {"1", "true", "yes", "gpu", "opengl"}:
        opts["useOpenGL"] = True
    return opts

class _ClickableLabel(QLabel):
    """可点击的标签，点击发射 clicked(key)。"""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self._key = key
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(ev)


class ChannelZeroHandle(pg.GraphicsObject):
    """波形左缘 0 值标记：固定像素绘制，箭头尖端指向该通道 0 值。"""

    clicked = pyqtSignal(str)
    dragged = pyqtSignal(str, float)
    dragFinished = pyqtSignal(str)

    _PX_LEN = 34
    _PX_H = 15
    _TEXT_RATIO = 0.68
    _FONT_PT = 7

    def __init__(self, key: str, label: str, color: str, view_box: pg.ViewBox):
        super().__init__()
        self._key = key
        self._label = label
        self._color = QColor(color)
        self._vb = view_box
        self._px_len = self._PX_LEN
        self._px_h = self._PX_H
        self._highlighted = False
        self._dimmed = False
        self._hovered = False
        self._pressed = False
        self._press_scene: QPointF | None = None
        self._dragging = False
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setZValue(100)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_highlighted(self, on: bool) -> None:
        if self._highlighted != on:
            self._highlighted = on
            self.update()

    def set_dimmed(self, on: bool) -> None:
        if self._dimmed != on:
            self._dimmed = on
            self.update()

    def _set_pressed(self, on: bool) -> None:
        if self._pressed != on:
            self._pressed = on
            self.update()

    @staticmethod
    def _right_arrow_polygon_px(px_len: float, px_h: float) -> QPolygonF:
        """像素坐标：左侧为通道标签，右侧尖端精确指向该通道 0 值。"""
        body_w = px_len * ChannelZeroHandle._TEXT_RATIO
        hh = px_h * 0.5
        tip = px_len
        return QPolygonF(
            [
                QPointF(tip, 0.0),
                QPointF(body_w, -hh),
                QPointF(0.0, -hh),
                QPointF(0.0, hh),
                QPointF(body_w, hh),
            ]
        )

    @staticmethod
    def _label_font(base: QFont | None = None) -> QFont:
        font = QFont(base) if base is not None else QFont()
        font.setBold(True)
        font.setPointSize(ChannelZeroHandle._FONT_PT)
        return font

    def _label_text_rect(self) -> QRectF:
        return QRectF(
            2.0,
            -self._px_h / 2.0,
            self._px_len * self._TEXT_RATIO - 3.0,
            self._px_h,
        )

    def _current_fill_color(self) -> QColor:
        fill = QColor(self._color)
        if self._highlighted:
            fill = fill.lighter(124)
        elif self._dimmed:
            fill = fill.darker(185)
            fill.setAlpha(135)
        elif self._hovered:
            fill = fill.lighter(105)
        if self._pressed:
            fill = fill.darker(190)
        return fill

    def boundingRect(self):  # noqa: N802
        return QRectF(
            -2,
            -self._px_h / 2 - 2,
            self._px_len + 4,
            self._px_h + 4,
        )

    def paint(self, painter, opt, widget=None) -> None:  # noqa: N802
        fill = self._current_fill_color()
        outline = QColor("#101010")
        outline.setAlpha(130 if self._dimmed and not self._highlighted else 210)
        painter.setPen(QPen(outline, 1.0))
        painter.setBrush(fill)
        painter.drawPolygon(self._right_arrow_polygon_px(self._px_len, self._px_h))
        painter.setFont(self._label_font(painter.font()))
        text_color = QColor("#111111") if fill.lightness() > 145 else QColor("#ffffff")
        if self._dimmed and not self._highlighted:
            text_color.setAlpha(180)
        painter.setPen(text_color)
        painter.drawText(
            self._label_text_rect(),
            Qt.AlignmentFlag.AlignCenter,
            self._label,
        )

    def hoverEnterEvent(self, ev) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().hoverEnterEvent(ev)

    def hoverLeaveEvent(self, ev) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(ev)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._press_scene = ev.scenePos()
            self._dragging = False
            self._set_pressed(True)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._press_scene is None or ev.buttons() != Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(ev)
            return
        if not self._dragging:
            delta = ev.scenePos() - self._press_scene
            if abs(delta.y()) < 3 and abs(delta.x()) < 3:
                return
            self._dragging = True
        view_y = float(self._vb.mapSceneToView(ev.scenePos()).y())
        self.dragged.emit(self._key, view_y)
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._dragging
            if not was_dragging:
                self.clicked.emit(self._key)
            self._press_scene = None
            self._dragging = False
            self._set_pressed(False)
            if was_dragging:
                self.dragFinished.emit(self._key)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)


class ScopeCursorLine(pg.InfiniteLine):
    """InfiniteLine with a scope-style right-click menu hook."""

    contextRequested = pyqtSignal(str, QPointF)

    def __init__(self, cursor_id: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cursor_id = cursor_id

    def mouseClickEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.RightButton:
            self.contextRequested.emit(self._cursor_id, QPointF(ev.scenePos()))
            ev.accept()
            return
        super().mouseClickEvent(ev)


class CursorSettingsDialog(QDialog):
    """Scope-style cursor settings panel."""

    def __init__(self, plot: "WaveformPlot", parent=None):
        super().__init__(parent)
        self._plot = plot
        self.setWindowTitle("光标")
        self.setModal(False)
        self.setMinimumWidth(430)
        self.setStyleSheet(
            "QDialog{background:rgba(120,120,120,235);color:#101010;"
            "font-family:'Microsoft YaHei UI','Segoe UI',sans-serif;font-size:14px;}"
            "QLabel{color:#101010;font-size:14px;}"
            "QLabel#cursorPanelTitle{font-size:16px;color:#f0f0f0;background:#5f5f5f;"
            "padding:8px 12px;}"
            "QComboBox,QLineEdit{background:#d9dcdf;color:#101010;border:1px solid #8a8d92;"
            "border-radius:4px;padding:6px 8px;min-height:24px;}"
            "QComboBox QAbstractItemView{background:#f2f4f4;color:#101014;"
            "border:1px solid #6d7478;selection-background-color:#28bce8;"
            "selection-color:#061014;outline:0;}"
            "QComboBox QAbstractItemView::item{min-height:26px;padding:5px 9px;"
            "color:#101014;background:#f2f4f4;}"
            "QComboBox QAbstractItemView::item:hover{background:#dce6e8;color:#050607;}"
            "QComboBox QAbstractItemView::item:selected{background:#28bce8;color:#061014;}"
            "QCheckBox{color:#101010;spacing:8px;}"
            "QPushButton{background:#c7c9cc;color:#111;border:1px solid #8e9297;"
            "border-radius:6px;padding:8px 18px;}"
            "QPushButton:checked{background:#28bce8;color:#061014;}"
            "QPushButton:hover{background:#d8dade;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        title = QLabel("光标")
        title.setObjectName("cursorPanelTitle")
        root.addWidget(title)

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        self._show_cb = QCheckBox("显示")
        self._show_cb.setChecked(plot._cursor_type != "none")
        grid.addWidget(self._show_cb, 0, 0)

        grid.addWidget(QLabel("光标类型"), 1, 0)
        self._type_combo = QComboBox()
        apply_combo_popup_style(self._type_combo, light=True)
        for text, key in (
            ("波形", "waveform"),
            ("竖条", "vertical"),
            ("横条", "horizontal"),
            ("竖条与横条", "both"),
        ):
            self._type_combo.addItem(text, key)
        idx = self._type_combo.findData(plot._cursor_type if plot._cursor_type != "none" else "both")
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        grid.addWidget(self._type_combo, 1, 1)

        grid.addWidget(QLabel("源"), 2, 0)
        source_combo = QComboBox()
        apply_combo_popup_style(source_combo, light=True)
        source_combo.addItem("选定波形")
        grid.addWidget(source_combo, 2, 1)

        grid.addWidget(QLabel("读数位置"), 0, 2)
        readout_box = QWidget()
        readout_lay = QHBoxLayout(readout_box)
        readout_lay.setContentsMargins(0, 0, 0, 0)
        readout_lay.setSpacing(0)
        self._readout_ticks = QPushButton("刻度")
        self._readout_marks = QPushButton("标记")
        for btn in (self._readout_ticks, self._readout_marks):
            btn.setCheckable(True)
            readout_lay.addWidget(btn)
        self._readout_ticks.setChecked(not plot._cursor_readout_overlay)
        self._readout_marks.setChecked(plot._cursor_readout_overlay)
        grid.addWidget(readout_box, 0, 3)

        grid.addWidget(QLabel("光标模式"), 3, 0)
        mode_box = QWidget()
        mode_lay = QHBoxLayout(mode_box)
        mode_lay.setContentsMargins(0, 0, 0, 0)
        mode_lay.setSpacing(0)
        self._mode_independent = QPushButton("独立")
        self._mode_linked = QPushButton("联动")
        for btn in (self._mode_independent, self._mode_linked):
            btn.setCheckable(True)
            mode_lay.addWidget(btn)
        self._mode_independent.setChecked(not plot._cursor_linked)
        self._mode_linked.setChecked(plot._cursor_linked)
        grid.addWidget(mode_box, 3, 1, 1, 2)

        if plot._cursor_a is not None and plot._cursor_b is not None:
            a = float(plot._cursor_a.value())
            b = float(plot._cursor_b.value())
        else:
            a = b = 0.0
        grid.addWidget(QLabel("光标 A 的 X 位置"), 4, 0)
        self._a_edit = QLineEdit(f"{a:.3f} µs")
        grid.addWidget(self._a_edit, 4, 1)
        grid.addWidget(QLabel("光标 B 的 X 位置"), 4, 2)
        self._b_edit = QLineEdit(f"{b:.3f} µs")
        grid.addWidget(self._b_edit, 4, 3)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        grid.addWidget(buttons, 5, 0, 1, 4)
        root.addWidget(body)

        self._show_cb.toggled.connect(self._apply_visibility_preview)
        self._type_combo.currentIndexChanged.connect(self._apply_visibility_preview)
        self._mode_independent.clicked.connect(lambda: self._set_mode_buttons(False))
        self._mode_linked.clicked.connect(lambda: self._set_mode_buttons(True))
        self._readout_ticks.clicked.connect(lambda: self._set_readout_buttons(False))
        self._readout_marks.clicked.connect(lambda: self._set_readout_buttons(True))

    def _set_mode_buttons(self, linked: bool) -> None:
        self._mode_linked.setChecked(linked)
        self._mode_independent.setChecked(not linked)

    def _set_readout_buttons(self, overlay: bool) -> None:
        self._readout_marks.setChecked(overlay)
        self._readout_ticks.setChecked(not overlay)

    def _apply_visibility_preview(self) -> None:
        if not self._show_cb.isChecked():
            self._plot._set_cursor_type("none")
            return
        self._plot._set_cursor_type(str(self._type_combo.currentData() or "both"))

    @staticmethod
    def _parse_us(text: str) -> float | None:
        cleaned = text.strip().lower().replace("µs", "").replace("us", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _apply(self) -> None:
        self._apply_visibility_preview()
        self._plot._set_cursor_link_mode(linked=self._mode_linked.isChecked())
        self._plot._set_cursor_readout_overlay(self._readout_marks.isChecked())
        a = self._parse_us(self._a_edit.text())
        b = self._parse_us(self._b_edit.text())
        if a is not None:
            self._plot._jump_vertical_cursor("a", a)
        if b is not None:
            self._plot._jump_vertical_cursor("b", b)
        self.accept()


class ChannelBox(QFrame):
    """示波器风格底部通道盒：单击置顶、双击高亮、右键改垂直。"""

    raiseClicked = pyqtSignal(str)
    highlightDoubleClicked = pyqtSignal(str)
    verticalSettingsRequested = pyqtSignal(str)

    def __init__(self, key: str, name: str, color: str, parent=None):
        super().__init__(parent)
        self._key = key
        self._color = color
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(108, 52)
        self.setMaximumSize(132, 52)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.name_lbl = QLabel(name)
        self.name_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.name_lbl.setObjectName("channelTitle")
        self.name_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.name_lbl.setFixedHeight(24)
        self.vdiv_lbl = QLabel("")
        self.vdiv_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.vdiv_lbl.setObjectName("channelScale")
        self.vdiv_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.vdiv_lbl.setFixedHeight(26)
        lay.addWidget(self.name_lbl)
        lay.addWidget(self.vdiv_lbl)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.raiseClicked.emit(self._key)
            ev.accept()
            return
        if ev.button() == Qt.MouseButton.RightButton:
            self.verticalSettingsRequested.emit(self._key)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.highlightDoubleClicked.emit(self._key)
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def set_texts(self, name_html: str, vdiv_html: str) -> None:
        self.name_lbl.setText(name_html)
        self.vdiv_lbl.setText(vdiv_html)

    def set_box_style(self, style: str) -> None:
        self.setStyleSheet(style)


_CHANNEL_CONTEXT_MENU_STYLE = """
QMenu {
    background-color: #d2d2d2;
    color: #111111;
    border: 1px solid #777777;
    padding: 6px 0;
    font-size: 15px;
}
QMenu::item {
    min-width: 188px;
    padding: 11px 42px 11px 22px;
    background-color: transparent;
}
QMenu::item:selected {
    background-color: #28bce8;
    color: #061014;
}
QMenu::item:disabled {
    color: #555966;
}
QMenu::separator {
    height: 1px;
    background-color: #b8bbc4;
    margin: 6px 0;
}
"""

class MathFormulaDialog(QDialog):
    """Small oscilloscope-style editor for a display math trace."""

    def __init__(self, plot: "WaveformPlot", key: str, parent=None):
        super().__init__(parent)
        self._plot = plot
        self._key = key
        self.setWindowTitle(f"{key} Formula")
        self.setMinimumWidth(560)
        self.setStyleSheet(
            "QDialog{background:#d6d8df;color:#111;}"
            "QLabel{color:#111;}"
            "QPushButton{background:#eeeeee;color:#111;border:1px solid #999;"
            "border-radius:4px;padding:7px 10px;min-width:58px;}"
            "QPushButton:hover{background:#f8f8f8;}"
            "QLineEdit{background:#f8fbff;color:#111;border:2px solid #4bc0d9;"
            "border-radius:5px;padding:7px;font-family:Consolas,'Courier New',monospace;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        root.addWidget(QLabel(f"{key} ="))
        self._edit = QLineEdit(plot._math_formulas.get(key, ""))
        self._edit.setPlaceholderText("Example: INTG(CH2 * (CH3 + CH4))")
        root.addWidget(self._edit)

        src_grid = QGridLayout()
        src_grid.setSpacing(6)
        names = plot._formula_source_names()
        for i, name in enumerate(names):
            btn = QPushButton(name.title().replace("Math", "Math "))
            btn.clicked.connect(lambda _checked=False, text=name: self._insert(text))
            src_grid.addWidget(btn, i // 6, i % 6)
        root.addWidget(QLabel("Sources"))
        root.addLayout(src_grid)

        fn_grid = QGridLayout()
        fn_grid.setSpacing(6)
        funcs = [
            "INTG()",
            "DERIV()",
            "MAX()",
            "MIN()",
            "ABS()",
            "SQRT()",
            "LOG()",
            "LN()",
            "EXP()",
            "SIN()",
            "COS()",
            "TAN()",
            "+",
            "-",
            "*",
            "/",
            "(",
            ")",
            ",",
            "AND",
            "OR",
            "XOR",
            "NAND()",
            "NOR()",
            "EQV()",
            "PI",
            "E",
        ]
        for i, text in enumerate(funcs):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _checked=False, value=text: self._insert_func(value))
            fn_grid.addWidget(btn, i // 6, i % 6)
        root.addWidget(QLabel("Functions"))
        root.addLayout(fn_grid)

        self._error = QLabel("")
        self._error.setStyleSheet("color:#b00020;")
        root.addWidget(self._error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _insert(self, text: str) -> None:
        self._edit.insert(text)
        self._edit.setFocus()

    def _insert_func(self, text: str) -> None:
        if text.endswith("()"):
            self._edit.insert(text[:-1])
        elif text in {"AND", "OR", "XOR"}:
            op = "^" if text == "XOR" else text.lower()
            self._edit.insert(f" {op} ")
        else:
            self._edit.insert(text.lower() if text in {"PI", "E"} else text)
        self._edit.setFocus()

    def _apply(self) -> bool:
        try:
            self._plot._set_math_formula(self._key, self._edit.text())
        except Exception as exc:  # noqa: BLE001 - show formula errors in the editor
            self._error.setText(str(exc))
            return False
        self._error.setText("")
        return True

    def _accept(self) -> None:
        if self._apply():
            self.accept()

from dpt_extractor.gui.theme import (
    WAVEFORM_PLOT_BG,
    WAVEFORM_PLOT_FG,
    WAVEFORM_TRACE_STYLES,
    apply_combo_popup_style,
)
from dpt_extractor.models.bridge_profile import BridgeProfile
from dpt_extractor.models.results import ExtractResult, SegmentIndices
from dpt_extractor.models.waveform import (
    WaveformBundle,
    channel_reference_base_name,
    channel_reference_sign,
    normalize_channel_reference,
    split_channel_reference,
)

MAX_PLOT_POINTS = 8000
MIN_X_SPAN_US = 0.2  # 200 ns 最小放大窗口
V_CURSOR_WIDTH = 1
H_CURSOR_WIDTH = 1

CURSOR_PEN_A = "#FFFFFF"
CURSOR_PEN_B = "#FFFFFF"
CURSOR_PEN_ZERO = "#FFFFFF"
REFERENCE_LINE_COLOR = "#FFFFFF"
AUX_DASH_PATTERN = (6.0, 8.0)
CURSOR_AUXILIARY_LINE_Z = 55
CURSOR_AUXILIARY_LINE_WIDTH = 1.2
CURSOR_AUXILIARY_VERTICAL_COLOR = "#F0A020"
CURSOR_AUXILIARY_HORIZONTAL_COLOR = "#8B1A1A"
REFERENCE_LINE_Z = 65
CURSOR_READOUT_OVERLAY_Z = 10000
CURSOR_NAME_OVERLAY_Z = CURSOR_READOUT_OVERLAY_Z + 10
CURSOR_READOUT_BG_ALPHA = 175
CURSOR_NAME_BG_ALPHA = 185
CURSOR_NAME_FONT_SIZE_PX = 12
CURSOR_LINE_LABEL_FONT_PT = 10
CURSOR_READOUT_EDGE_INSET_PX = 8.0
CURSOR_READOUT_BOTTOM_TICK_GUARD_PX = 28.0
CURSOR_READOUT_STACK_GAP_PX = 5.0
CURSOR_READOUT_MIN_ROW_PX = 22.0
CURSOR_READOUT_CURSOR_GAP_PX = 4.0
CURSOR_READOUT_MARKER_GUARD_PX = 14.0
CURSOR_READOUT_LABEL_GUARD_PX = 4.0
CURSOR_LINE_LABEL_GUARD_PX = 2.0

# 每通道独立垂直刻度（示波器 V/div 风格）：显示坐标 = 原始值 / (单位每格)
DISP_HALF_DIV = 5.0  # 纵向显示半高（格），总高 10 格（同示波器）
HORIZONTAL_DIV_COUNT = 10.0  # 横向整格数（与 _update_x_ticks 一致）
X_NS_PER_DIV = 50  # 水平标度 ns/格 步进（滚轮与显示量化）
PARAM_FOCUS_DEFAULT_US_PER_DIV = 0.2  # 点击参数局部放大默认 200 ns/div
VERT_VIEW_MARGIN = 0.10  # 纵向上下各留 10% 空白
PLOT_AXIS_LABEL_EDGE_INSET = 0.0
PLOT_AXIS_LABEL_END_GUARD = 0.008
GRATICULE_DOT_COLOR = "#b7b7b7"
GRATICULE_DOT_ALPHA = 145
GRATICULE_DOT_SIZE_PX = 1.0
GRATICULE_SUBDIVISIONS_PER_DIV = 5
VDIV_LADDER = (1, 2, 5, 10, 20, 50, 100, 150, 200, 250, 300)
CURRENT_VDIV_DEFAULT = 200.0  # 电流通道默认刻度（A/格）
CURRENT_VDIV_MAX = 300.0  # 电流通道可选上限（含 250、300）
POWER_VDIV_DEFAULT = 500_000.0  # 功率通道默认刻度：500 kW/格
RR_POWER_VDIV_DEFAULT = 200_000.0  # 反向恢复功率默认刻度：200 kW/格
_NICE_STEPS = (1.0, 2.0, 2.5, 5.0)

# 参考示波器默认垂直刻度（Ch1 5V/格, Ch2 200V/格, Ch3/4 200A/格, Ch5 200V/格, Ch6 5V/格）
SCOPE_VDIV_DEFAULT: dict[str, float] = {
    "vge": 5.0,        # CH1 H-Vge
    "vce": 200.0,      # CH2 H-Vce
    "ic": 200.0,       # CH3+CH4 总电流
    "irr": 200.0,      # CH3/CH4 电流
    "v_diode": 200.0,  # CH5 L-Vce
    "vge_other": 5.0,  # CH6 L-Vge
    "vdesat": 5.0,
}

# 默认垂直位置偏移（格），对齐用户示波器布局
SCOPE_OFFSET_DEFAULT: dict[str, float] = {
    "vge": -1.0,
    "vce": -3.0,
    "ic": 2.5,
    "irr": 2.5,
    "v_diode": -2.0,
    "vge_other": -0.5,
    "vdesat": 0.0,
}


def _spaced_dash_pen(color: str, width: float = 1.0) -> QPen:
    pen = QPen(QColor(color), float(width))
    pen.setCosmetic(True)
    pen.setStyle(Qt.PenStyle.CustomDashLine)
    pen.setDashPattern(list(AUX_DASH_PATTERN))
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    return pen


# 通道单位（用于读数显示）
CHANNEL_UNITS = {
    "vge": "V",
    "vce": "V",
    "ic": "A",
    "irr": "A",
    "v_diode": "V",
    "vge_other": "V",
    "vdesat": "V",
}

SOURCE_CHANNEL_PATTERN = r"(?:CH[1-8]|MATH\d+)"
SOURCE_CHANNEL_RE = re.compile(rf"^{SOURCE_CHANNEL_PATTERN}$", re.I)

MATH_TRACE_COLORS = (
    "#008000",
    "#A62323",
    "#FF0000",
    "#789ED3",
    "#936756",
    "#6E2B85",
    "#A62323",
    "#96B03C",
)
MATH_VDIV_LADDER = (
    1e-9,
    2e-9,
    5e-9,
    1e-8,
    2e-8,
    5e-8,
    1e-7,
    2e-7,
    5e-7,
    1e-6,
    2e-6,
    5e-6,
    1e-5,
    2e-5,
    5e-5,
    1e-4,
    2e-4,
    5e-4,
    1e-3,
    2e-3,
    5e-3,
    1e-2,
    2e-2,
    5e-2,
    1e-1,
    2e-1,
    5e-1,
    *VDIV_LADDER,
)


def _source_channel_sort_key(name: str) -> tuple[int, int, int, str]:
    key = normalize_channel_reference(name)
    signed = 1 if key.startswith("-") else 0
    base = channel_reference_base_name(key)
    m = re.fullmatch(r"(CH|MATH)(\d+)", base)
    if not m:
        return (2, signed, 0, key)
    return (0 if m.group(1) == "CH" else 1, int(m.group(2)), signed, key)


def _is_math_trace_key(key: str) -> bool:
    return bool(re.fullmatch(r"MATH\d+", channel_reference_base_name(key)))


def _is_source_channel_key(key: str) -> bool:
    return bool(SOURCE_CHANNEL_RE.fullmatch(channel_reference_base_name(key)))


_POWER_UNIT_TO_W = {
    "pW": 1e-12,
    "nW": 1e-9,
    "uW": 1e-6,
    "µW": 1e-6,
    "mW": 1e-3,
    "W": 1.0,
    "KW": 1e3,
    "kW": 1e3,
    "MW": 1e6,
    "GW": 1e9,
}


def _is_power_unit(unit: str) -> bool:
    return str(unit or "").strip() in _POWER_UNIT_TO_W


def _power_vdiv_default_for_unit(
    unit: str,
    *,
    reverse_recovery: bool = False,
) -> float:
    text = str(unit or "").strip()
    default_w = RR_POWER_VDIV_DEFAULT if reverse_recovery else POWER_VDIV_DEFAULT
    return default_w / _POWER_UNIT_TO_W.get(text, 1.0)


def _power_unit_to_w_factor(unit: str) -> float:
    return float(_POWER_UNIT_TO_W.get(str(unit or "").strip(), 1.0))


def _format_power_axis_value(value: float, unit: str) -> str:
    watts = float(value) * _power_unit_to_w_factor(unit)
    abs_w = abs(watts)
    if abs_w < 1e-15:
        return "0 W"
    for suffix, factor in (
        ("GW", 1e9),
        ("MW", 1e6),
        ("KW", 1e3),
        ("W", 1.0),
        ("mW", 1e-3),
        ("µW", 1e-6),
        ("nW", 1e-9),
        ("pW", 1e-12),
    ):
        if abs_w >= factor:
            disp = watts / factor
            break
    else:
        suffix, factor = "pW", 1e-12
        disp = watts / factor
    if abs(disp - round(disp)) < 1e-6:
        text = f"{int(round(disp))}"
    elif abs(disp) >= 10.0:
        text = f"{disp:.1f}".rstrip("0").rstrip(".")
    else:
        text = f"{disp:.2f}".rstrip("0").rstrip(".")
    return f"{text} {suffix}"


def _math_color(key: str) -> str:
    style = WAVEFORM_TRACE_STYLES.get(key.upper())
    if style is not None:
        return style[0]
    m = re.fullmatch(r"MATH(\d+)", key.upper())
    idx = int(m.group(1)) - 1 if m else 0
    return MATH_TRACE_COLORS[idx % len(MATH_TRACE_COLORS)]


def _source_trace_style(key: str) -> tuple[str, float]:
    key = normalize_channel_reference(key)
    style = WAVEFORM_TRACE_STYLES.get(key)
    if style is not None:
        return style
    base = channel_reference_base_name(key)
    style = WAVEFORM_TRACE_STYLES.get(base)
    if style is not None:
        return style
    if _is_math_trace_key(key):
        return _math_color(base), 1.5
    return "#d0d0d0", 1.5


def _source_channel_legend(key: str, labels: dict[str, str]) -> str:
    key = normalize_channel_reference(key)
    base = channel_reference_base_name(key)
    label = (labels.get(key) or labels.get(base) or "").strip()
    if label and label.upper() != key:
        return f"{key} {label}"
    return key


def _vdiv_ladder_for_channel(key: str) -> tuple[float, ...]:
    return MATH_VDIV_LADDER if _is_math_trace_key(key) else VDIV_LADDER


def _nice_per_div(peak: float, target_div: float = 4.0) -> float:
    """按 1-2-2.5-5 选取使 peak ≈ target_div 格的「单位/格」。"""
    import math

    peak = abs(float(peak))
    if peak <= 1e-9:
        return 1.0
    target = peak / target_div
    dec = 10.0 ** math.floor(math.log10(target))
    for s in _NICE_STEPS:
        if s * dec >= target:
            return s * dec
    return 10.0 * dec


def _exact_x_us_per_div(span_us: float) -> float:
    """当前视窗水平每格时间（µs），与滚轮缩放后的可见跨度严格一致。"""
    span_us = abs(float(span_us))
    if span_us <= 0:
        return 0.0
    return span_us / HORIZONTAL_DIV_COUNT


def _quantize_x_us_per_div(scale_us: float) -> float:
    """量化水平标度：<1µs 按 50ns 整档；≥1µs 用整数 µs。"""
    scale_us = abs(float(scale_us))
    if scale_us <= 0:
        return MIN_X_SPAN_US / HORIZONTAL_DIV_COUNT
    if scale_us < 1.0:
        ns = scale_us * 1000.0
        ns_q = max(X_NS_PER_DIV, int(round(ns / X_NS_PER_DIV)) * X_NS_PER_DIV)
        return ns_q / 1000.0
    if scale_us < 1000.0:
        return float(max(1, int(round(scale_us))))
    return round(scale_us / 1000.0, 2) * 1000.0


def _x_wheel_step_us(scale_us: float) -> float:
    """滚轮一档步进：<1µs/格 固定 ±50ns；≥1µs/格 为 ±1µs。"""
    scale_us = _quantize_x_us_per_div(scale_us)
    if scale_us < 1.0:
        return X_NS_PER_DIV / 1000.0
    return 1.0


def _format_time_per_div(step_us: float) -> str:
    """示波器风格水平时间标度（整数 ns / 简洁 µs）。"""
    step_us = _quantize_x_us_per_div(step_us)
    if step_us <= 0:
        return "—"
    if step_us >= 1000.0:
        ms = step_us / 1000.0
        if abs(ms - round(ms)) < 1e-9:
            return f"{int(round(ms))} ms/div"
        return f"{ms:g} ms/div"
    if step_us >= 1.0:
        if abs(step_us - round(step_us)) < 1e-9:
            return f"{int(round(step_us))} µs/div"
        return f"{step_us:g} µs/div"
    ns = int(round(step_us * 1000.0))
    return f"{ns} ns/div"


def _format_x_tick_us(value_us: float) -> str:
    value_us = float(value_us)
    if abs(value_us) < 1e-12:
        value_us = 0.0
    return f"{value_us:g}us"


def _x_axis_ticks(x0: float, x1: float, step_us: float) -> list[tuple[float, str]]:
    import math

    span = float(x1) - float(x0)
    step_us = abs(float(step_us))
    if span <= 0 or step_us <= 0:
        return []
    start = math.ceil(float(x0) / step_us - 1e-9) * step_us
    ticks = []
    v = start
    cnt = 0
    while v <= float(x1) + 1e-9 and cnt < 80:
        ticks.append((v, _format_x_tick_us(v)))
        v += step_us
        cnt += 1
    return ticks


def _graticule_dot_values(
    ticks: list[float], lower: float, upper: float
) -> np.ndarray:
    majors = sorted({float(v) for v in ticks})
    if not majors:
        return np.asarray([], dtype=np.float64)
    if len(majors) == 1:
        values = majors
    else:
        diffs = [
            b - a
            for a, b in zip(majors, majors[1:])
            if b > a
        ]
        if diffs:
            step = float(np.median(np.asarray(diffs, dtype=np.float64)))
            while step > 0 and majors[0] > float(lower):
                majors.insert(0, majors[0] - step)
            while step > 0 and majors[-1] < float(upper):
                majors.append(majors[-1] + step)
        values = []
        for a, b in zip(majors, majors[1:]):
            if b <= a:
                continue
            step = (b - a) / GRATICULE_SUBDIVISIONS_PER_DIV
            values.extend(a + step * i for i in range(GRATICULE_SUBDIVISIONS_PER_DIV))
        values.append(majors[-1])
    span = max(float(upper) - float(lower), 1e-12)
    pad = span * 1e-6
    return np.asarray(
        [v for v in values if float(lower) - pad <= v <= float(upper) + pad],
        dtype=np.float64,
    )


def _graticule_major_values(
    ticks: list[float], lower: float, upper: float
) -> np.ndarray:
    span = max(float(upper) - float(lower), 1e-12)
    pad = span * 1e-6
    return np.asarray(
        [
            float(v)
            for v in sorted({float(v) for v in ticks})
            if float(lower) - pad <= float(v) <= float(upper) + pad
        ],
        dtype=np.float64,
    )


def _graticule_dot_line_points(
    x_ticks: list[float],
    y_ticks: list[float],
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> tuple[np.ndarray, np.ndarray]:
    x_minor = _graticule_dot_values(x_ticks, x0, x1)
    y_minor = _graticule_dot_values(y_ticks, y0, y1)
    x_major = _graticule_major_values(x_ticks, x0, x1)
    y_major = _graticule_major_values(y_ticks, y0, y1)
    if (
        len(x_minor) == 0
        or len(y_minor) == 0
        or len(x_major) == 0
        or len(y_major) == 0
    ):
        return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)

    # Scope graticules are dotted major lines, not a filled minor-dot lattice.
    x = np.concatenate(
        [
            np.tile(x_minor, len(y_major)),
            np.tile(x_major, len(y_minor)),
        ]
    )
    y = np.concatenate(
        [
            np.repeat(y_major, len(x_minor)),
            np.repeat(y_minor, len(x_major)),
        ]
    )
    points = np.unique(np.column_stack([x, y]), axis=0)
    return points[:, 0], points[:, 1]


def _usable_y_divs() -> float:
    """纵向可用于波形的总格数（上下各留 VERT_VIEW_MARGIN）。"""
    return HORIZONTAL_DIV_COUNT * (1.0 - 2.0 * VERT_VIEW_MARGIN)


def _vdiv_max_for_channel(key: str) -> float:
    normalized = normalize_channel_reference(key)
    if CHANNEL_UNITS.get(normalized) == "A":
        return CURRENT_VDIV_MAX
    return float(_vdiv_ladder_for_channel(key)[-1])


def _pick_vdiv_ladder(required: float, key: str) -> float:
    """Pick the smallest vertical scale that can contain required units/div."""
    required = max(float(required), 1e-12)
    cap = _vdiv_max_for_channel(key)
    ladder = _vdiv_ladder_for_channel(key)
    for v in ladder:
        if float(v) > cap:
            break
        if float(v) >= required:
            return float(v)
    for v in reversed(ladder):
        if float(v) <= cap:
            return float(v)
    return float(ladder[0])


def _raw_value_span(raw: np.ndarray) -> tuple[float, float, float, float]:
    """返回 (vmin, vmax, mid, half_span_max)；忽略非有限值。"""
    valid = raw[np.isfinite(raw)] if len(raw) else raw
    if len(valid) == 0:
        return 0.0, 0.0, 0.0, 1.0
    vmin = float(np.min(valid))
    vmax = float(np.max(valid))
    mid = 0.5 * (vmin + vmax)
    half_span = max(vmax - mid, mid - vmin, 1e-12)
    return vmin, vmax, mid, half_span


def _y_fit_limit_div() -> float:
    """中点在 0 格时，向上/向下各自允许的最大半幅（格）。"""
    return DISP_HALF_DIV * (1.0 - VERT_VIEW_MARGIN)


def _auto_vdiv_for_channel(
    key: str,
    raw: np.ndarray,
    unit: str = "",
    *,
    reverse_recovery_power: bool = False,
) -> float:
    """TSS 没有垂直刻度时，按 10%~90% 波形区自动选取单位/格。"""
    if _is_power_unit(unit):
        return _power_vdiv_default_for_unit(
            unit,
            reverse_recovery=reverse_recovery_power,
        )
    if len(raw) == 0:
        return float(_vdiv_ladder_for_channel(key)[0])
    _, _, _, half_span = _raw_value_span(raw)
    required = (2.0 * half_span) / _usable_y_divs()
    if _is_math_trace_key(key):
        return _pick_vdiv_ladder(required, key)
    import math

    scale = float(max(1, int(math.ceil(max(required, 1e-12)))))
    return min(scale, _vdiv_max_for_channel(key))


def _loss_window_raw(
    raw: np.ndarray,
    segments: SegmentIndices | None,
    *,
    include_turn_on: bool = True,
) -> np.ndarray:
    if segments is None or len(raw) == 0:
        return raw
    windows = [segments.turn_off]
    if include_turn_on:
        windows.append(segments.turn_on)
    chunks: list[np.ndarray] = []
    n = len(raw)
    for i0, i1 in windows:
        lo = max(0, min(n, int(i0)))
        hi = max(0, min(n, int(i1)))
        if hi > lo:
            chunks.append(np.asarray(raw[lo:hi], dtype=np.float64))
    if not chunks:
        return raw
    return np.concatenate(chunks)


def _wheel_delta_y(ev) -> int:
    """兼容 QWidget 与 QGraphicsScene 的滚轮事件。"""
    ad = getattr(ev, "angleDelta", None)
    if callable(ad):
        pt = ad()
        if pt is not None and hasattr(pt, "y"):
            y = int(pt.y())
            if y:
                return y
    d = getattr(ev, "delta", None)
    if callable(d):
        d = d()
    if isinstance(d, int):
        return d
    if d is not None and hasattr(d, "y"):
        return int(d.y())
    return 0


def _waveform_fits_at_center(raw: np.ndarray, scale: float) -> bool:
    """当前 V/div 下，(min+max)/2 对齐 0 格时波形是否仍在可视范围内。"""
    if len(raw) == 0 or scale <= 0:
        return True
    vmin, vmax, mid, _ = _raw_value_span(raw)
    limit = _y_fit_limit_div()
    half_up = (vmax - mid) / scale
    half_dn = (mid - vmin) / scale
    return half_up <= limit + 1e-9 and half_dn <= limit + 1e-9


def _safe_initial_vdiv_for_channel(
    key: str,
    raw: np.ndarray,
    scope_scale: float | None,
    unit: str = "",
    *,
    reverse_recovery_power: bool = False,
) -> float:
    if (
        scope_scale is not None
        and np.isfinite(float(scope_scale))
        and float(scope_scale) > 0
    ):
        return float(scope_scale)
    return _auto_vdiv_for_channel(
        key,
        raw,
        unit,
        reverse_recovery_power=reverse_recovery_power,
    )


def _clamp_offset_div(offset: float) -> float:
    return float(max(-DISP_HALF_DIV, min(DISP_HALF_DIV, float(offset))))


_SI_DISPLAY_FACTORS: tuple[tuple[str, float], ...] = (
    ("p", 1e12),
    ("n", 1e9),
    ("µ", 1e6),
    ("m", 1e3),
    ("", 1.0),
    ("k", 1e-3),
    ("M", 1e-6),
    ("G", 1e-9),
)
_SI_PREFIX_TO_FACTOR = {prefix: factor for prefix, factor in _SI_DISPLAY_FACTORS}


def _normalize_si_prefix(prefix: str) -> str:
    prefix = str(prefix or "").strip()
    if prefix in {"u", "U", "μ"}:
        return "µ"
    if prefix == "K":
        return "k"
    return prefix


def _split_si_unit(display_unit: str, base_unit: str) -> tuple[str, str]:
    base_unit = str(base_unit or "")
    display_unit = str(display_unit or "").strip()
    if not base_unit or not display_unit.endswith(base_unit):
        return "", base_unit
    prefix = display_unit[: -len(base_unit)]
    return _normalize_si_prefix(prefix), base_unit


def _unit_factor_for_display_unit(display_unit: str, base_unit: str) -> float:
    prefix, _base = _split_si_unit(display_unit, base_unit)
    return float(_SI_PREFIX_TO_FACTOR.get(prefix, 1.0))


def _vdiv_unit_options(display_unit: str, base_unit: str, radius: int = 2) -> list[str]:
    """Return nearby SI display units around the current unit."""
    base_unit = str(base_unit or "")
    if not base_unit:
        return [""]
    prefix, _base = _split_si_unit(display_unit, base_unit)
    prefixes = [p for p, _factor in _SI_DISPLAY_FACTORS]
    try:
        center = prefixes.index(prefix)
    except ValueError:
        center = prefixes.index("")
    lo = max(0, center - int(radius))
    hi = min(len(prefixes), center + int(radius) + 1)
    return [f"{prefixes[i]}{base_unit}" for i in range(lo, hi)]


def _scaled_div_value(scale: float, unit: str) -> tuple[float, str, float]:
    """Display vertical scale with SI sub-units."""
    unit = unit or ""
    scale = float(scale)
    if not unit or scale == 0.0 or not np.isfinite(scale):
        return scale, unit, 1.0
    abs_scale = abs(scale)
    smallest_prefix, smallest_factor = _SI_DISPLAY_FACTORS[0]
    if abs_scale * smallest_factor < 1.0:
        return scale * smallest_factor, f"{smallest_prefix}{unit}", smallest_factor
    best_prefix, best_factor = _SI_DISPLAY_FACTORS[-1]
    for prefix, factor in _SI_DISPLAY_FACTORS:
        value = abs_scale * factor
        if 1.0 <= value < 1000.0:
            best_prefix, best_factor = prefix, factor
            break
    return scale * best_factor, f"{best_prefix}{unit}", best_factor


def _format_vdiv_text(scale: float, unit: str) -> str:
    disp_scale, disp_unit, _factor = _scaled_div_value(scale, unit)
    if abs(disp_scale - round(disp_scale)) < 1e-9:
        value = str(int(round(disp_scale)))
    else:
        value = f"{disp_scale:g}"
    suffix = f" {disp_unit}" if disp_unit else ""
    return f"{value}{suffix}/div"


def _auto_center_offset_div(raw: np.ndarray, scale: float) -> float:
    """使波形中点 (min+max)/2 落在 0 格：显示 = raw/scale + offset。"""
    if len(raw) == 0 or scale <= 0:
        return 0.0
    vmin, vmax, mid, _ = _raw_value_span(raw)
    offset = -mid / float(scale)
    if _waveform_fits_at_center(raw, scale):
        return float(offset)
    return float(max(-DISP_HALF_DIV, min(DISP_HALF_DIV, offset)))


def _parse_time_per_div_input(text: str) -> float | None:
    """解析输入为 µs/格；无单位时：≥100 视为 ns，否则视为 µs。"""
    t = text.strip().lower().replace("μ", "µ").replace("/div", "").strip()
    if not t:
        return None
    m = re.match(
        r"^([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*(ns|ps|µs|us|ms|s)?$",
        t,
    )
    if not m:
        return None
    val = float(m.group(1))
    unit = (m.group(2) or "").replace("us", "µs")
    if unit == "ns":
        return _quantize_x_us_per_div(val / 1000.0)
    if unit == "ps":
        return _quantize_x_us_per_div(val / 1e6)
    if unit in ("µs",):
        return _quantize_x_us_per_div(val)
    if unit == "ms":
        return _quantize_x_us_per_div(val * 1000.0)
    if unit == "s":
        return _quantize_x_us_per_div(val * 1e6)
    if val >= 100.0:
        scale_us = val / 1000.0
    else:
        scale_us = val
    return _quantize_x_us_per_div(scale_us)


def _downsample(t: np.ndarray, *arrays: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
    n = len(t)
    if n <= MAX_PLOT_POINTS:
        return t, list(arrays)
    step = max(1, n // MAX_PLOT_POINTS)
    idx = np.arange(0, n, step)
    return t[idx], [a[idx] for a in arrays]


def _display_curve_data(
    t_us: np.ndarray, y: np.ndarray, x0_us: float, x1_us: float
) -> tuple[np.ndarray, np.ndarray]:
    if len(t_us) != len(y) or len(t_us) <= MAX_PLOT_POINTS:
        return t_us, y
    lo, hi = (float(x0_us), float(x1_us)) if x0_us <= x1_us else (float(x1_us), float(x0_us))
    i0 = int(np.searchsorted(t_us, lo, side="left"))
    i1 = int(np.searchsorted(t_us, hi, side="right"))
    i0 = max(0, min(i0, len(t_us) - 1))
    i1 = max(i0 + 1, min(i1, len(t_us)))
    n = i1 - i0
    if n <= MAX_PLOT_POINTS:
        return t_us[i0:i1], y[i0:i1]
    step = max(1, int(np.ceil(n / MAX_PLOT_POINTS)))
    idx = np.arange(i0, i1, step)
    if len(idx) == 0 or idx[-1] != i1 - 1:
        idx = np.append(idx, i1 - 1)
    return t_us[idx], y[idx]


class WaveformPlot(QWidget):
    """双脉冲波形 + 持久 A/B 时间光标 + Ha/Hb 通道光标。

    交互模式（_interactive_mode）：
      - "global"   : 默认。A/B 拖动只更新读数 + 通知 MainWindow（用于无激活参数的测量）
      - "interval" : 某参数被点击后绑定到 A/B；拖动 A/B 实时重算该参数
      - "delta_vce": ΔVce 专用——A/B + Ha/Hb 联动
      - "dvdt"/"didt": Ha=Top、Hb=Base；A/B 卡在两者之间百分比穿越时刻（随 Ha/Hb 联动）
    """

    channelMappingRequested = pyqtSignal(str, str)
    channelLabelChanged = pyqtSignal(str, str)
    channelUnitChanged = pyqtSignal(str, str)
    channelInversionChanged = pyqtSignal(str, bool)
    cursorVisibilityChanged = pyqtSignal(bool)
    selectionZoomChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WaveformPlotRoot")
        self.setStyleSheet(
            "QWidget#WaveformPlotRoot{background:#11121f;"
            "border:0;}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        pg.setConfigOptions(**_pyqtgraph_config_options())

        # 光标读数保留为内部状态，不再占用波形顶部空间。
        self._readout_scroll = QScrollArea(self)
        self._readout_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._readout_scroll.setWidgetResizable(False)
        self._readout_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._readout_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._readout_scroll.setFixedHeight(36)
        self._readout_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        readout_host = QWidget()
        readout_lay = QHBoxLayout(readout_host)
        readout_lay.setContentsMargins(2, 0, 2, 0)
        readout_lay.setSpacing(0)
        self._readout_label = QLabel("")
        self._readout_label.setStyleSheet(
            f"color:{WAVEFORM_PLOT_FG};font-size:12px;font-family:Consolas,'Courier New',monospace;"
        )
        self._readout_label.setTextFormat(Qt.TextFormat.RichText)
        self._readout_label.setWordWrap(False)
        self._readout_label.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )
        readout_lay.addWidget(self._readout_label)
        self._readout_scroll.setWidget(readout_host)
        self._readout_scroll.hide()

        scale_box = QWidget()
        scale_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        scale_box.setFixedHeight(16)
        scale_lay = QHBoxLayout(scale_box)
        scale_lay.setContentsMargins(0, 0, 0, 0)
        scale_lay.setSpacing(5)
        self._x_scale_caption = QLabel("水平标度")
        self._x_scale_caption.setObjectName("scopeScaleCaption")
        self._x_scale_caption.setFixedHeight(16)
        self._x_scale_caption.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._x_scale_caption.setStyleSheet(
            "QLabel#scopeScaleCaption{color:#f2f2f2;font-size:10px;"
            "font-weight:700;padding:0 4px;margin:0;}"
        )
        self._x_scale_edit = QLineEdit()
        self._x_scale_edit.setObjectName("scopeScaleEdit")
        self._x_scale_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._x_scale_edit.setFixedWidth(104)
        self._x_scale_edit.setFixedHeight(16)
        self._x_scale_edit.setPlaceholderText("200ns")
        self._x_scale_edit.setStyleSheet(
            "QLineEdit#scopeScaleEdit{background-color:#e6e6e6;color:#1a1a1a;"
            "font-size:10px;font-family:Consolas,'Courier New',monospace;"
            "padding:0 6px;border-radius:2px;border:1px solid #b0b0b0;"
            "min-height:16px;max-height:16px;}"
        )
        self._x_scale_edit.returnPressed.connect(self._on_x_scale_committed)
        self._x_scale_edit.editingFinished.connect(self._on_x_scale_committed)
        self._zoom_select_btn = QPushButton("⌕")
        self._zoom_select_btn.setCheckable(True)
        self._zoom_select_btn.setFixedSize(42, 32)
        self._zoom_select_btn.setToolTip("框选局部放大：点击后在波形区左键拖出范围框")
        self._zoom_select_btn.setStyleSheet(
            "QPushButton{background-color:#2f3038;color:#d9e3f0;"
            "border:1px solid #60636f;border-radius:4px;"
            "font-size:20px;font-weight:700;padding:0;}"
            "QPushButton:hover{background-color:#3a3c46;}"
            "QPushButton:checked{background-color:#1f6feb;color:#ffffff;"
            "border-color:#8fd3ff;}"
        )
        self._zoom_select_btn.toggled.connect(self._set_selection_zoom_enabled)
        self._zoom_select_btn.hide()
        self._x_zoom_in_btn = QPushButton("+")
        self._x_zoom_in_btn.setObjectName("scopeScaleTinyButton")
        self._x_zoom_in_btn.setFixedSize(28, 16)
        self._x_zoom_in_btn.setToolTip("水平放大")
        self._x_zoom_in_btn.clicked.connect(lambda: self._step_x_scale(zoom_in=True))
        self._x_zoom_out_btn = QPushButton("−")
        self._x_zoom_out_btn.setObjectName("scopeScaleTinyButton")
        self._x_zoom_out_btn.setFixedSize(28, 16)
        self._x_zoom_out_btn.setToolTip("水平缩小")
        self._x_zoom_out_btn.clicked.connect(lambda: self._step_x_scale(zoom_in=False))
        self._x_zoom_factor_label = QLabel("(1.00x 缩放)")
        self._x_zoom_factor_label.setObjectName("scopeScaleFactor")
        self._x_zoom_factor_label.setFixedHeight(16)
        self._x_zoom_factor_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._x_zoom_factor_label.setStyleSheet(
            "QLabel#scopeScaleFactor{color:#f2f2f2;font-size:10px;"
            "font-family:Consolas,'Courier New',monospace;"
            "padding:0 0 0 4px;margin:0;}"
        )
        for btn in (self._x_zoom_in_btn, self._x_zoom_out_btn):
            btn.setStyleSheet(
                "QPushButton#scopeScaleTinyButton{background:#4a4a4a;color:#f2f2f2;"
                "border:1px solid #5f5f5f;"
                "border-radius:2px;font-size:10px;font-weight:700;padding:0;margin:0;"
                "min-width:28px;max-width:28px;min-height:16px;max-height:16px;}"
                "QPushButton#scopeScaleTinyButton:hover{background:#5c5c5c;}"
                "QPushButton#scopeScaleTinyButton:pressed{background:#303030;}"
            )
        scale_lay.addWidget(
            self._x_scale_caption, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        scale_lay.addWidget(
            self._x_scale_edit, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        scale_lay.addWidget(
            self._x_zoom_in_btn, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        scale_lay.addWidget(
            self._x_zoom_out_btn, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        scale_lay.addWidget(
            self._x_zoom_factor_label, alignment=Qt.AlignmentFlag.AlignVCenter
        )

        self.plot = pg.PlotWidget()
        self.plot.setTitle(None)
        self.plot.setBackground(WAVEFORM_PLOT_BG)
        plot_item = self.plot.getPlotItem()
        plot_item.hideButtons()
        plot_item.setContentsMargins(0, 0, 0, 0)
        plot_item.showAxis("right")
        plot_item.hideAxis("left")
        plot_item.getViewBox().setBackgroundColor(WAVEFORM_PLOT_BG)
        self.plot.showGrid(x=False, y=False)
        axis_pen = pg.mkPen(WAVEFORM_PLOT_FG)
        for axis_name in ("right", "bottom"):
            ax = plot_item.getAxis(axis_name)
            ax.setPen(axis_pen)
            ax.setTextPen(axis_pen)
            ax.showLabel(False)
            ax.setStyle(
                showValues=False,
                tickLength=0,
                tickTextOffset=0,
                autoExpandTextSpace=False,
                autoReduceTextSpace=False,
            )
        plot_item.getAxis("bottom").showLabel(False)
        plot_item.getAxis("bottom").setHeight(1)
        # 纵轴固定整格刻度线显示在波形区右侧（示波器式整格水平线）。
        ax_right = plot_item.getAxis("right")
        ax_right.setTicks(
            [[(i, str(i)) for i in range(-int(DISP_HALF_DIV), int(DISP_HALF_DIV) + 1)]]
        )
        ax_right.setWidth(1)
        plot_item.getAxis("left").setGrid(False)
        ax_right.setGrid(False)
        self._x_tick_label_items: list[pg.TextItem] = []
        self._y_tick_label_items: list[pg.TextItem] = []
        self._graticule_x_ticks: list[float] = []
        self._graticule_y_ticks: list[float] = []
        graticule_dot_color = QColor(GRATICULE_DOT_COLOR)
        graticule_dot_color.setAlpha(GRATICULE_DOT_ALPHA)
        self._graticule_dots = pg.ScatterPlotItem(
            size=GRATICULE_DOT_SIZE_PX,
            pxMode=True,
            pen=pg.mkPen(None),
            brush=pg.mkBrush(graticule_dot_color),
        )
        self._graticule_dots.setZValue(-50)
        self.plot.addItem(self._graticule_dots)
        # 图例不再画在波形内（改用顶部 _legend_label）
        self.plot.setMenuEnabled(False)
        self.plot.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plot.customContextMenuRequested.connect(self._show_context_menu)

        vb = self.plot.getPlotItem().getViewBox()
        vb.setMouseEnabled(x=True, y=False)
        vb.setDefaultPadding(0.0)
        # 时间轴按 ~10 等分给整刻度线（随缩放自适应，去掉细密小网格）
        vb.sigXRangeChanged.connect(lambda *_: self._update_x_ticks())
        vb.sigRangeChanged.connect(self._on_view_range_changed)
        if hasattr(vb, "sigResized"):
            vb.sigResized.connect(self._on_view_geometry_changed)
        _orig_vb_wheel = vb.wheelEvent

        def _vb_wheel(ev, axis=None):
            if self._on_x_wheel(ev):
                return
            _orig_vb_wheel(ev, axis)

        vb.wheelEvent = _vb_wheel
        _orig_vb_drag = vb.mouseDragEvent

        def _vb_drag(ev, axis=None):
            if self._on_selection_drag(ev):
                return
            _orig_vb_drag(ev, axis)

        vb.mouseDragEvent = _vb_drag

        self._overview_plot = pg.PlotWidget()
        self._overview_plot.setFixedHeight(86)
        self._overview_plot.setBackground("#151515")
        self._overview_plot.setMenuEnabled(False)
        self._overview_plot.showGrid(x=True, y=False, alpha=0.22)
        overview_item = self._overview_plot.getPlotItem()
        overview_item.hideButtons()
        overview_item.hideAxis("left")
        overview_item.getAxis("bottom").setPen(axis_pen)
        overview_item.getAxis("bottom").setTextPen(axis_pen)
        overview_item.setContentsMargins(0, 0, 0, 0)
        overview_vb = overview_item.getViewBox()
        overview_vb.setMouseEnabled(x=False, y=False)
        overview_vb.setDefaultPadding(0.0)
        overview_vb.setBackgroundColor("#151515")
        self._overview_region = pg.LinearRegionItem(
            values=(0.0, 1.0),
            orientation="vertical",
            brush=QBrush(QColor(143, 211, 255, 42)),
            pen=pg.mkPen("#d7ecff", width=1.6),
            hoverBrush=QBrush(QColor(143, 211, 255, 72)),
            hoverPen=pg.mkPen("#ffffff", width=2.0),
            movable=True,
            bounds=(0.0, 1.0),
        )
        self._overview_region.setZValue(50)
        self._overview_region.setToolTip(
            "拖动总览框：平移局部放大位置；拖动边缘：调整放大范围"
        )
        self._overview_region.sigRegionChanged.connect(
            self._on_overview_region_changed
        )
        overview_item.addItem(self._overview_region)
        self._overview_plot.hide()
        self._scope_scale_bar = QFrame()
        self._scope_scale_bar.setObjectName("scopeScaleBar")
        self._scope_scale_bar.setFixedHeight(20)
        self._scope_scale_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._scope_scale_bar.setStyleSheet(
            "QFrame#scopeScaleBar{background:#777777;border:1px solid #5f5f5f;}"
        )
        scope_scale_lay = QHBoxLayout(self._scope_scale_bar)
        scope_scale_lay.setContentsMargins(0, 0, 4, 0)
        scope_scale_lay.setSpacing(6)
        scope_scale_lay.addWidget(scale_box, alignment=Qt.AlignmentFlag.AlignVCenter)
        scope_scale_lay.addStretch(1)
        self._local_zoom_close_btn = QPushButton("X")
        self._local_zoom_close_btn.setObjectName("scopeScaleCloseButton")
        self._local_zoom_close_btn.setFixedSize(30, 16)
        self._local_zoom_close_btn.setStyleSheet(
            "QPushButton#scopeScaleCloseButton{background:transparent;color:#e8e8e8;border:0;"
            "font-size:10px;font-weight:800;padding:0;margin:0;"
            "min-width:30px;max-width:30px;min-height:16px;max-height:16px;}"
            "QPushButton#scopeScaleCloseButton:hover{background:#5e5e5e;color:#ffffff;}"
        )
        self._local_zoom_close_btn.clicked.connect(self._exit_local_zoom)
        scope_scale_lay.addWidget(
            self._local_zoom_close_btn, alignment=Qt.AlignmentFlag.AlignVCenter
        )
        self._scope_scale_bar.hide()
        self._waveform_panel = QFrame()
        self._waveform_panel.setObjectName("waveformPanel")
        waveform_panel_layout = QVBoxLayout(self._waveform_panel)
        waveform_panel_layout.setContentsMargins(4, 4, 4, 4)
        waveform_panel_layout.setSpacing(4)
        waveform_panel_layout.addWidget(self._overview_plot)
        waveform_panel_layout.addWidget(self._scope_scale_bar)
        waveform_panel_layout.addWidget(self.plot, stretch=1)
        layout.addWidget(self._waveform_panel, stretch=1)
        self._zoom_toggle_btn = QPushButton("⌕", self._overview_plot)
        self._zoom_toggle_btn.setFixedSize(34, 34)
        self._zoom_toggle_btn.setToolTip("切换最近局部放大 / 全图预览")
        self._zoom_toggle_btn.setStyleSheet(
            "QPushButton{background:rgba(20,25,35,170);color:#79d7ff;"
            "border:2px solid #28bce8;border-radius:4px;"
            "font-size:20px;font-weight:700;padding:0;}"
            "QPushButton:hover{background:rgba(40,188,232,210);color:#101014;}"
        )
        self._zoom_toggle_btn.clicked.connect(self._toggle_zoom_preview)
        self._zoom_toggle_btn.hide()

        # ---- 底部通道盒（隐藏滚动条，左右箭头平移）----
        self._channel_strip = QFrame()
        self._channel_strip.setObjectName("channelStrip")
        self._channel_strip.setFixedHeight(68)
        self._channel_strip.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        channel_strip_layout = QHBoxLayout(self._channel_strip)
        channel_strip_layout.setContentsMargins(2, 2, 2, 2)
        channel_strip_layout.setSpacing(0)

        self._channel_nav_left_btn = QPushButton("‹")
        self._channel_nav_right_btn = QPushButton("›")
        for btn in (self._channel_nav_left_btn, self._channel_nav_right_btn):
            btn.setFixedSize(28, 60)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setVisible(False)
            btn.setStyleSheet(
                "QPushButton{background:#171924;color:#cdd6f4;"
                "border:1px solid #46525a;border-radius:3px;"
                "font-size:30px;font-weight:700;padding:0;}"
                "QPushButton:hover{background:#273044;color:#ffffff;}"
                "QPushButton:disabled{color:#5e6678;background:#11131c;}"
            )
        self._channel_nav_left_btn.clicked.connect(
            lambda: self._scroll_channel_bar(-1)
        )
        self._channel_nav_right_btn.clicked.connect(
            lambda: self._scroll_channel_bar(1)
        )

        self._channel_bar = QWidget()
        self._channel_layout = QHBoxLayout(self._channel_bar)
        self._channel_layout.setContentsMargins(6, 5, 6, 5)
        self._channel_layout.setSpacing(5)
        self._channel_scroll = QScrollArea()
        self._channel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._channel_scroll.setWidgetResizable(False)
        self._channel_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._channel_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._channel_scroll.setFixedHeight(64)
        self._channel_settings_panel = None
        self._channel_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._channel_scroll.setStyleSheet(
            "QScrollArea { background-color: #10111a; border: none; }"
        )
        self._channel_strip.setStyleSheet(
            "QFrame#channelStrip { background-color: #10111a;"
            "border: 2px solid #46525a; border-radius: 4px; }"
        )
        self._channel_bar.setStyleSheet("background-color: #10111a;")
        self._channel_scroll.setWidget(self._channel_bar)
        channel_strip_layout.addWidget(self._channel_nav_left_btn)
        channel_strip_layout.addWidget(self._channel_scroll, stretch=1)
        channel_strip_layout.addWidget(self._channel_nav_right_btn)
        self._channel_scroll.horizontalScrollBar().rangeChanged.connect(
            lambda _min, _max: self._sync_channel_nav_buttons()
        )
        self._channel_scroll.horizontalScrollBar().valueChanged.connect(
            lambda _value: self._sync_channel_nav_buttons()
        )
        layout.addWidget(self._channel_strip)
        self._channel_boxes: dict[str, ChannelBox] = {}
        self._channel_content_width = 0

        # 持久光标
        self._cursor_a: pg.InfiniteLine | None = None
        self._cursor_b: pg.InfiniteLine | None = None
        self._h_cursor_a: pg.InfiniteLine | None = None
        self._h_cursor_b: pg.InfiniteLine | None = None
        self._h_cursor_zero: pg.InfiniteLine | None = None
        self._cursor_a_t_label: pg.TextItem | None = None
        self._cursor_b_t_label: pg.TextItem | None = None
        self._cursor_ab_delta_label: pg.TextItem | None = None
        self._cursor_ha_v_label: pg.TextItem | None = None
        self._cursor_hb_v_label: pg.TextItem | None = None
        self._cursor_hb_ha_delta_label: pg.TextItem | None = None
        self._cursor_ha_name_label: pg.TextItem | None = None
        self._cursor_hb_name_label: pg.TextItem | None = None
        self._cursor_a_wave_marker: pg.ScatterPlotItem | None = None
        self._cursor_b_wave_marker: pg.ScatterPlotItem | None = None
        self._cursor_aux_hline: pg.PlotDataItem | None = None
        self._cursor_aux_vline: pg.PlotDataItem | None = None
        self._cursor_aux_channel: str | None = None
        self._cursor_aux_t_us: float | None = None
        self._cursor_aux_value: float | None = None
        self._cursor_aux_x_range_us: tuple[float, float] | None = None
        self._cursor_aux_vertical_guide_enabled = False
        self._x_us_per_div: float = 0.0
        self._x_target_us_per_div: float = 0.0
        self._scope_x_us_per_div: float | None = None
        self._x_scale_updating: bool = False
        # 用户手动调整过的水平标度（点击参数局部放大后记忆，µs/格）
        self._user_x_us_per_div: float | None = None

        pane_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        pane_policy.setHeightForWidth(False)
        self.setSizePolicy(pane_policy)

        # 波形高亮/置顶
        self._trace_items: dict[str, pg.PlotDataItem] = {}
        self._trace_style: dict[str, tuple[str, float]] = {}
        self._trace_yrange: dict[str, tuple[float, float]] = {}
        self._trace_legend: dict[str, str] = {}
        self._channel_labels: dict[str, str] = {}
        self._trace_units: dict[str, str] = {}
        self._source_file_units: dict[str, str] = {}
        self._unit_overrides: dict[str, str] = {}
        self._role_units: dict[str, str] = {}
        self._raised_key: str | None = None
        self._highlighted_key: str | None = None
        self._hidden_channels: set[str] = set()

        # 每通道垂直刻度（单位/格），显示坐标 = 原始值 / 刻度 + 位置偏移
        self._disp_scale: dict[str, float] = {}
        # 每通道垂直位置偏移（格），示波器 position 旋钮；默认对齐示波器布局
        self._disp_offset: dict[str, float] = dict(SCOPE_OFFSET_DEFAULT)
        # 用户手动设置的 V/div（覆盖默认/自动）
        self._manual_vdiv: dict[str, float] = {}
        self._loaded_source_path: str | None = None
        self._manual_inverted_channels: set[str] = set()
        self._source_inverted_channels: set[str] = set()
        # 全采样波形缓存（光标吸附/峰值定位必须与参数计算使用同一数据源）
        self._trace_t_us: np.ndarray | None = None
        self._trace_raw: dict[str, np.ndarray] = {}
        self._trace_view_signature: tuple[float, float] | None = None
        self._trace_display_updating = False
        self._plot_geometry_sync_pending = False
        self._plot_geometry_force_trace_sync = False
        self._auxiliary_dash_lines: list[pg.InfiniteLine] = []
        self._overview_items: dict[str, pg.PlotDataItem] = {}
        self._overview_syncing = False
        self._formula_t_s: np.ndarray | None = None
        self._formula_sources: dict[str, np.ndarray] = {}
        self._math_formulas: dict[str, str] = {}
        self._math_source_keys: set[str] = set()
        self._computed_math_channels: set[str] = set()
        self._loss_fit_segments: SegmentIndices | None = None
        self._loss_fit_include_turn_on: bool = True
        self._base_logical_display_keys: dict[str, str] = {}
        self._logical_display_keys: dict[str, str] = {}
        self._display_channel_roles: dict[str, list[str]] = {}
        # 每通道 0 值箭头手柄（波形右缘，拖动调垂直位置）
        self._zero_handles: dict[str, ChannelZeroHandle] = {}
        # 横向光标当前对应的通道（决定 Ha/Hb/Δy 的真实单位换算）
        self._active_channel: str = "ic"
        # dv/dt、di/dt 模式锁定的测量通道（图例高亮不改变）
        self._slope_channel: str | None = None
        self._slope_zero_ref_enabled = False

        # 波形数据缓存（用于 ΔVce 模式电压匹配）
        self._interactive_vce_t_us: np.ndarray | None = None
        self._interactive_vce: np.ndarray | None = None
        self._interactive_irr_t_us: np.ndarray | None = None
        self._interactive_irr: np.ndarray | None = None
        self._interactive_irr_peak_idx: int | None = None
        self._interactive_trr_i_fall_end: int | None = None
        self._interactive_ic_t_us: np.ndarray | None = None
        self._interactive_ic: np.ndarray | None = None
        self._interactive_dt: float = 1e-9

        # 交互状态
        self._interactive_on_change = None
        self._interactive_enabled = True
        self._interactive_mode: str = "global"
        self._interactive_search_t0_us: float | None = None
        self._interactive_search_t1_us: float | None = None
        self._interactive_syncing = False
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._h_cursor_a_locked = False
        # 光标联动模式：True=联动（原逻辑），False=独立（禁止自动吸附/联动）
        self._cursor_linked = True
        self._cursor_type = "both"
        self._last_visible_cursor_type = "both"
        self._cursor_readout_overlay = True
        self._energy_edge_a = "rising"
        self._energy_edge_b = "falling"
        self._energy_b_channel = "ic"
        self._energy_b_level_vce: float | None = None
        self._energy_ha_channel = "vce"
        self._energy_a_channel = "vce"
        self._energy_a_anchor_us: float | None = None
        self._energy_rise_a_mode: str | None = None
        self._energy_fall_a_mode: str | None = None
        self._energy_fall_b_mode: str | None = None
        self._energy_peak_channels: tuple[str, ...] = ("vce", "ic")
        self._energy_hb_channel = "ic"

        # 视图限制
        self._full_x_range: tuple[float, float] | None = None
        self._last_x_window: tuple[float, float] | None = None
        self._selection_start_scene: QPointF | None = None
        self._selection_rect_item: QGraphicsRectItem | None = None
        self._selection_zoom_enabled = False
        self._axis_last_signature: tuple | None = None
        self._display_mode = "overlay"
        self._recent_local_x_window: tuple[float, float] | None = None

        # 持久光标回调（global 模式拖动时触发）
        self._global_callback = None
        self._horizontal_callback = None
        self._view_range_callback = None

    # ------------------------------------------------------------------ 公共 API ----
    def set_global_cursor_handler(self, cb) -> None:
        """A/B 拖动时 MainWindow 监听：cb(t0_us, t1_us)。"""
        self._global_callback = cb

    def set_horizontal_cursor_handler(self, cb) -> None:
        """Ha/Hb 拖动时 MainWindow 监听：cb(ha, hb)。"""
        self._horizontal_callback = cb

    def set_view_range_handler(self, cb) -> None:
        """MainWindow 监听当前屏幕范围变化，用于屏幕范围测量。"""
        self._view_range_callback = cb

    def current_x_range_us(self) -> tuple[float, float] | None:
        try:
            x0, x1 = self.plot.getPlotItem().getViewBox().viewRange()[0]
        except Exception:
            return None
        if not (np.isfinite(float(x0)) and np.isfinite(float(x1))):
            return None
        return min(float(x0), float(x1)), max(float(x0), float(x1))

    def trace_color(self, channel: str) -> str:
        key = self._display_key_for_channel(str(channel))
        return self._trace_style.get(key, (WAVEFORM_PLOT_FG, 1.0))[0]

    def reset_interaction_state(self) -> None:
        """换文件或「重新计算」清空手动状态时，退出参数绑定模式，避免沿用旧光标。"""
        self._interactive_enabled = False
        self._interactive_mode = "global"
        self._interactive_on_change = None
        self._interactive_search_t0_us = None
        self._interactive_search_t1_us = None
        self._h_cursor_a_locked = False
        self.clear_cursor_auxiliary_guides()

    def cursors_t_us(self) -> tuple[float, float] | None:
        if self._cursor_a is None or self._cursor_b is None:
            return None
        a = float(self._cursor_a.value())
        b = float(self._cursor_b.value())
        return min(a, b), max(a, b)

    def cursor_type(self) -> str:
        return self._cursor_type

    def set_cursor_type(self, cursor_type: str) -> None:
        self._set_cursor_type(cursor_type)

    def cursor_linked(self) -> bool:
        return bool(self._cursor_linked)

    def set_cursor_linked(self, linked: bool) -> None:
        self._set_cursor_link_mode(linked=bool(linked))

    def set_global_cursor_window(self, a_us: float, b_us: float) -> None:
        if self._cursor_a is None or self._cursor_b is None:
            self._install_persistent_cursors(float(a_us), float(b_us), 1.0)
        if self._cursor_a is None or self._cursor_b is None:
            return
        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(self._clip_t_us(float(a_us)))
            self._cursor_b.setPos(self._clip_t_us(float(b_us)))
            self._cursor_a.setMovable(True)
            self._cursor_b.setMovable(True)
            if self._h_cursor_a is not None:
                self._h_cursor_a.setMovable(True)
                self._h_cursor_a_locked = False
            if self._h_cursor_b is not None:
                self._h_cursor_b.setMovable(True)
        finally:
            self._interactive_syncing = False
        self._update_readout()

    def enable_global_cursor_interaction(
        self,
        cursor_window_us: tuple[float, float] | None = None,
    ) -> None:
        self.clear_cursor_auxiliary_guides()
        self._interactive_enabled = True
        self._interactive_on_change = None
        self._interactive_mode = "global"
        self._interactive_search_t0_us = None
        self._interactive_search_t1_us = None
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._slope_channel = None
        self._slope_zero_ref_enabled = False
        self._hide_h_cursor_zero()
        self._h_cursor_a_locked = False
        if cursor_window_us is not None:
            self.set_global_cursor_window(cursor_window_us[0], cursor_window_us[1])
        else:
            for line in (
                self._cursor_a,
                self._cursor_b,
                self._h_cursor_a,
                self._h_cursor_b,
            ):
                if line is not None:
                    line.setMovable(True)
            self._update_readout()

    # ------------------------------------------------------------------ 视图 ----
    def _items_to_keep(self) -> list:
        keep = []
        for it in (
            self._cursor_a,
            self._cursor_b,
            self._h_cursor_a,
            self._h_cursor_b,
            self._cursor_a_t_label,
            self._cursor_b_t_label,
            self._cursor_ab_delta_label,
            self._cursor_ha_v_label,
            self._cursor_hb_v_label,
            self._cursor_hb_ha_delta_label,
            self._cursor_a_wave_marker,
            self._cursor_b_wave_marker,
        ):
            if it is not None:
                keep.append(it)
        return keep

    def _soft_clear(self) -> None:
        """清除波形/分区，但保留持久光标。"""
        self._clear_selection_rect()
        self._remove_zero_handles()
        self._clear_overview_traces()
        self.clear_cursor_auxiliary_guides()
        keep = self._items_to_keep()
        plot_item = self.plot.getPlotItem()
        for it in list(plot_item.items):
            if it not in keep:
                plot_item.removeItem(it)
        self._auxiliary_dash_lines.clear()
        if hasattr(self, "_x_tick_label_items"):
            self._x_tick_label_items.clear()
            self._y_tick_label_items.clear()
            self._graticule_x_ticks.clear()
            self._graticule_y_ticks.clear()
            self._graticule_dots.setData([], [])
            self._axis_last_signature = None

    def clear(self) -> None:
        """完全清除：包括光标（仅在新文件加载等场景使用）。"""
        self.clear_cursor_auxiliary_guides()
        for it in self._items_to_keep():
            self.plot.removeItem(it)
        self._cursor_a = None
        self._cursor_b = None
        self._h_cursor_a = None
        self._h_cursor_b = None
        self._clear_selection_rect()
        self._clear_overview_traces()
        self._remove_cursor_plot_labels()
        self._remove_zero_handles()
        self._clear_axis_tick_labels()
        self._auxiliary_dash_lines.clear()
        self._interactive_vce_t_us = None
        self._interactive_vce = None
        self._interactive_irr_t_us = None
        self._interactive_irr = None
        self._interactive_irr_peak_idx = None
        self._interactive_trr_i_fall_end = None
        self._interactive_ic_t_us = None
        self._interactive_ic = None
        self._scope_x_us_per_div = None
        self._slope_channel = None
        self._interactive_on_change = None
        self._interactive_mode = "global"
        self._interactive_search_t0_us = None
        self._interactive_search_t1_us = None
        self._interactive_syncing = False
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._h_cursor_a_locked = False
        self._raised_key = None
        self._highlighted_key = None

    def _view_coords_at_context_pos(self, pos) -> tuple[float, float]:
        """右键位置 → 视图坐标 (时间 µs, 纵向显示格)。"""
        vb = self.plot.getPlotItem().getViewBox()
        scene = self.plot.mapToScene(pos)
        view = vb.mapSceneToView(scene)
        return float(view.x()), float(view.y())

    def _clip_t_us(self, t_us: float) -> float:
        if self._full_x_range is None:
            return t_us
        return float(
            np.clip(t_us, self._full_x_range[0], self._full_x_range[1])
        )

    @staticmethod
    def _line_movable(line: pg.InfiniteLine | None) -> bool:
        if line is None:
            return False
        return bool(getattr(line, "movable", True))

    def _jump_vertical_cursor(self, which: str, t_us: float) -> None:
        line = self._cursor_a if which == "a" else self._cursor_b
        if line is None:
            return
        line.setPos(self._clip_t_us(t_us))

    def _jump_horizontal_cursor(self, which: str, y_div: float) -> None:
        line = self._h_cursor_a if which == "a" else self._h_cursor_b
        if line is None:
            return
        if which == "a" and self._h_cursor_a_locked:
            return
        if self._cursor_linked:
            y_div = float(max(-DISP_HALF_DIV, min(DISP_HALF_DIV, y_div)))
        line.setPos(float(y_div))

    def _set_cursor_link_mode(self, *, linked: bool) -> None:
        self._cursor_linked = bool(linked)
        if linked:
            self._apply_cursor_visibility()
            return
        # 独立模式：允许所有可见光标单独拖动，不再被“锁定”挡住。
        for line in (
            self._cursor_a,
            self._cursor_b,
            self._h_cursor_a,
            self._h_cursor_b,
            self._h_cursor_zero,
        ):
            if line is not None:
                line.setMovable(True)
        self._h_cursor_a_locked = False
        self._apply_cursor_visibility()

    def _cursor_vertical_visible(self) -> bool:
        return self._cursor_type in {"vertical", "both", "waveform"}

    def _cursor_horizontal_visible(self) -> bool:
        return self._cursor_type in {"horizontal", "both"}

    def _cursor_waveform_visible(self) -> bool:
        return self._cursor_type == "waveform" or (
            self._cursor_type == "both"
            and self._interactive_mode in {"energy_loss", "trr_measure"}
        )

    def cursor_switch_enabled(self) -> bool:
        return self._cursor_type != "none"

    def set_cursor_switch_enabled(self, enabled: bool) -> None:
        if enabled:
            self._set_cursor_type(self._last_visible_cursor_type or "both")
        else:
            self._set_cursor_type("none")

    def _set_cursor_type(self, cursor_type: str) -> None:
        if cursor_type not in {"none", "waveform", "vertical", "horizontal", "both"}:
            cursor_type = "both"
        was_enabled = self.cursor_switch_enabled()
        self._cursor_type = cursor_type
        if cursor_type != "none":
            self._last_visible_cursor_type = cursor_type
        if cursor_type == "waveform":
            self._set_cursor_link_mode(linked=True)
            self._update_readout()
            if self.cursor_switch_enabled() != was_enabled:
                self.cursorVisibilityChanged.emit(self.cursor_switch_enabled())
            return
        self._update_readout()
        self._apply_cursor_visibility()
        if self.cursor_switch_enabled() != was_enabled:
            self.cursorVisibilityChanged.emit(self.cursor_switch_enabled())

    def _apply_cursor_visibility(self) -> None:
        show_v = self._cursor_vertical_visible()
        show_h = self._cursor_horizontal_visible()
        for item in (self._cursor_a, self._cursor_b):
            if item is not None:
                item.setVisible(show_v)
        for item in (self._h_cursor_a, self._h_cursor_b, self._h_cursor_zero):
            if item is not None:
                item.setVisible(show_h and (item is not self._h_cursor_zero or self._slope_zero_ref_enabled))
        for attr in ("_cursor_a_t_label", "_cursor_b_t_label", "_cursor_ab_delta_label"):
            item = getattr(self, attr)
            if item is not None:
                item.setVisible(show_v and self._cursor_readout_overlay)
        for attr in ("_cursor_ha_v_label", "_cursor_hb_v_label", "_cursor_hb_ha_delta_label"):
            item = getattr(self, attr)
            if item is not None:
                item.setVisible(show_h and self._cursor_readout_overlay)
        for attr in ("_cursor_ha_name_label", "_cursor_hb_name_label"):
            item = getattr(self, attr)
            if item is not None:
                item.setVisible(show_h)
        self._update_waveform_cursor_markers()
        self._sync_cursor_line_label_positions()
        self._refresh_cursor_auxiliary_guides()

    def _set_cursor_readout_overlay(self, enabled: bool) -> None:
        self._cursor_readout_overlay = bool(enabled)
        self._update_readout()
        self._apply_cursor_visibility()

    def _show_cursor_settings_dialog(self) -> None:
        dlg = CursorSettingsDialog(self, parent=self)
        dlg.show()

    def _add_cursor_type_menu(self, menu: QMenu) -> QMenu:
        type_menu = menu.addMenu("光标类型")
        group = QActionGroup(type_menu)
        group.setExclusive(True)
        for key, text in (
            ("waveform", "波形"),
            ("vertical", "竖条"),
            ("horizontal", "横条"),
            ("both", "竖条与横条"),
        ):
            act = QAction(text, type_menu)
            act.setCheckable(True)
            act.setChecked(self._cursor_type == key)
            act.triggered.connect(
                lambda _checked=False, mode=key: self._set_cursor_type(mode)
            )
            group.addAction(act)
            type_menu.addAction(act)
        return type_menu

    def _add_cursor_mode_menu(self, menu: QMenu) -> QMenu:
        mode_menu = menu.addMenu("光标模式")
        group = QActionGroup(mode_menu)
        group.setExclusive(True)
        for linked, text in ((True, "联动"), (False, "独立")):
            act = QAction(text, mode_menu)
            act.setCheckable(True)
            act.setChecked(self._cursor_linked == linked)
            act.triggered.connect(
                lambda _checked=False, is_linked=linked: self._set_cursor_link_mode(
                    linked=is_linked
                )
            )
            group.addAction(act)
            mode_menu.addAction(act)
        return mode_menu

    def _add_cursor_move_actions(self, menu: QMenu, t_us: float, y_div: float) -> None:
        show_vertical = self._cursor_vertical_visible()
        show_horizontal = self._cursor_horizontal_visible()
        if not show_vertical and not show_horizontal:
            return

        has_vertical_cursors = self._cursor_a is not None and self._cursor_b is not None
        has_horizontal_cursors = (
            self._h_cursor_a is not None and self._h_cursor_b is not None
        )
        separator_added = False

        def _add_move_action(action: QAction) -> None:
            nonlocal separator_added
            if not separator_added:
                menu.addSeparator()
                separator_added = True
            menu.addAction(action)

        if show_vertical and has_vertical_cursors:
            act_a = QAction("将光标 A 移到此处", self)
            act_b = QAction("将光标 B 移到此处", self)
            act_a.setEnabled(self._line_movable(self._cursor_a))
            act_b.setEnabled(self._line_movable(self._cursor_b))
            act_a.triggered.connect(lambda: self._jump_vertical_cursor("a", t_us))
            act_b.triggered.connect(lambda: self._jump_vertical_cursor("b", t_us))
            _add_move_action(act_a)
            _add_move_action(act_b)
        if show_horizontal and has_horizontal_cursors:
            act_ha = QAction("将光标 Ha 移到此处", self)
            act_ha.setEnabled(not self._h_cursor_a_locked)
            act_ha.triggered.connect(
                lambda: self._jump_horizontal_cursor("a", y_div)
            )
            _add_move_action(act_ha)
            act_hb = QAction("将光标 Hb 移到此处", self)
            act_hb.setEnabled(self._line_movable(self._h_cursor_b))
            act_hb.triggered.connect(
                lambda: self._jump_horizontal_cursor("b", y_div)
            )
            _add_move_action(act_hb)
        if not separator_added:
            act_no_cursor = QAction("尚未安装光标", self)
            act_no_cursor.setEnabled(False)
            _add_move_action(act_no_cursor)

    def _populate_cursor_menu(self, menu: QMenu, t_us: float, y_div: float) -> None:
        has_cursors = self._cursor_a is not None and self._cursor_b is not None
        if self._cursor_type == "none":
            toggle_action = QAction("打开光标", menu)
            toggle_action.setEnabled(has_cursors)
            toggle_action.triggered.connect(lambda: self._set_cursor_type("both"))
        else:
            toggle_action = QAction("关闭光标", menu)
            toggle_action.triggered.connect(lambda: self._set_cursor_type("none"))
        menu.addAction(toggle_action)
        config_action = QAction("配置光标...", menu)
        config_action.triggered.connect(self._show_cursor_settings_dialog)
        menu.addAction(config_action)
        self._add_cursor_type_menu(menu)
        self._add_cursor_mode_menu(menu)
        self._add_cursor_move_actions(menu, t_us, y_div)

    def _populate_zoom_menu(self, menu: QMenu) -> None:
        act_zoom_select = QAction("框选局部放大", self)
        act_zoom_select.setCheckable(True)
        act_zoom_select.setChecked(self._selection_zoom_enabled)
        act_zoom_select.triggered.connect(lambda checked=False: self._arm_selection_zoom())
        menu.addAction(act_zoom_select)
        menu.addSeparator()
        act_zoom_in = QAction("水平放大", self)
        act_zoom_in.triggered.connect(lambda: self._step_x_scale(zoom_in=True))
        act_zoom_out = QAction("水平缩小", self)
        act_zoom_out.triggered.connect(lambda: self._step_x_scale(zoom_in=False))
        menu.addAction(act_zoom_in)
        menu.addAction(act_zoom_out)
        menu.addSeparator()
        act_full = QAction("铺满全部波形", self)
        act_full.triggered.connect(self._fit_full_range)
        act_reset = QAction("重置缩放", self)
        act_reset.triggered.connect(self._reset_view)
        menu.addAction(act_full)
        menu.addAction(act_reset)

    def _build_scope_context_menu(self, t_us: float, y_div: float) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet(_CHANNEL_CONTEXT_MENU_STYLE)
        self._populate_cursor_menu(menu, t_us, y_div)
        return menu

    def _show_context_menu(self, pos) -> None:
        t_us, y_div = self._view_coords_at_context_pos(pos)
        menu = self._build_scope_context_menu(t_us, y_div)
        menu.exec(self.plot.mapToGlobal(pos))

    def _show_cursor_context_menu(self, _cursor_id: str, scene_pos: QPointF) -> None:
        view = self.plot.getPlotItem().getViewBox().mapSceneToView(scene_pos)
        menu = QMenu(self)
        menu.setStyleSheet(_CHANNEL_CONTEXT_MENU_STYLE)
        self._populate_cursor_menu(menu, float(view.x()), float(view.y()))
        menu.exec(self.plot.mapToGlobal(self.plot.mapFromScene(scene_pos)))

    def _apply_disp_yrange(self) -> None:
        """固定纵向显示为 ±DISP_HALF_DIV 格（每通道按自身 V/div 缩放）。"""
        vb = self.plot.getPlotItem().getViewBox()
        vb.setYRange(-DISP_HALF_DIV, DISP_HALF_DIV, padding=0.0)
        vb.setMouseEnabled(x=True, y=False)
        self._update_y_ticks()

    @staticmethod
    def _axis_tick_html(text: str, color: str) -> str:
        return (
            "<span style='"
            f"color:{color};"
            "font-size:12px;"
            "font-family:Consolas,\"Courier New\",monospace;"
            "font-weight:700;"
            "'>"
            f"{text}"
            "</span>"
        )

    def _clear_axis_tick_labels(self) -> None:
        if not hasattr(self, "_x_tick_label_items"):
            return
        for item in [*self._x_tick_label_items, *self._y_tick_label_items]:
            try:
                self.plot.removeItem(item)
            except Exception:
                pass
        self._x_tick_label_items.clear()
        self._y_tick_label_items.clear()
        if hasattr(self, "_graticule_dots"):
            self._graticule_x_ticks.clear()
            self._graticule_y_ticks.clear()
            self._graticule_dots.setData([], [])

    def _ensure_graticule_dots(self) -> None:
        if not hasattr(self, "_graticule_dots"):
            return
        plot_items = self.plot.getPlotItem().items
        if self._graticule_dots not in plot_items:
            self.plot.addItem(self._graticule_dots)

    def _sync_graticule_dots(self) -> None:
        if not hasattr(self, "_graticule_dots"):
            return
        self._ensure_graticule_dots()
        if not self._graticule_x_ticks or not self._graticule_y_ticks:
            self._graticule_dots.setData([], [])
            return
        try:
            (x0, x1), (y0, y1) = self.plot.getPlotItem().getViewBox().viewRange()
        except Exception:
            return
        x_arr, y_arr = _graticule_dot_line_points(
            self._graticule_x_ticks,
            self._graticule_y_ticks,
            float(x0),
            float(x1),
            float(y0),
            float(y1),
        )
        if len(x_arr) == 0 or len(y_arr) == 0:
            self._graticule_dots.setData([], [])
            return
        self._graticule_dots.setData(x=x_arr, y=y_arr)

    def _sync_axis_tick_items(
        self,
        items: list[pg.TextItem],
        count: int,
        *,
        anchor: tuple[float, float],
    ) -> None:
        while len(items) < count:
            item = pg.TextItem(anchor=anchor)
            item.setZValue(35)
            self.plot.addItem(item)
            items.append(item)
        while len(items) > count:
            item = items.pop()
            try:
                self.plot.removeItem(item)
            except Exception:
                pass

    def _sync_x_tick_labels(self, ticks: list[tuple[float, str]]) -> None:
        if not hasattr(self, "_x_tick_label_items"):
            return
        try:
            (x0, x1), (y0, y1) = self.plot.getPlotItem().getViewBox().viewRange()
        except Exception:
            return
        x_span = max(float(x1) - float(x0), 1e-12)
        y_span = max(float(y1) - float(y0), 1e-12)
        x_guard = PLOT_AXIS_LABEL_END_GUARD * x_span
        y = float(y0) + PLOT_AXIS_LABEL_EDGE_INSET * y_span
        visible = [
            (max(float(x0) + x_guard, min(float(x1) - x_guard, float(x))), str(text))
            for x, text in ticks
            if float(x0) - x_guard <= float(x) <= float(x1) + x_guard
        ]
        self._sync_axis_tick_items(
            self._x_tick_label_items,
            len(visible),
            anchor=(0.5, 1.0),
        )
        color = self._axis_tick_color()
        for item, (x, text) in zip(self._x_tick_label_items, visible):
            item.setHtml(self._axis_tick_html(text, color))
            item.setPos(x, y)
            item.show()

    def _sync_y_tick_labels(self, ticks: list[tuple[float, str]], color: str) -> None:
        if not hasattr(self, "_y_tick_label_items"):
            return
        try:
            (x0, x1), (y0, y1) = self.plot.getPlotItem().getViewBox().viewRange()
        except Exception:
            return
        x_span = max(float(x1) - float(x0), 1e-12)
        y_span = max(float(y1) - float(y0), 1e-12)
        x = float(x1) - PLOT_AXIS_LABEL_EDGE_INSET * x_span
        y_guard = PLOT_AXIS_LABEL_END_GUARD * y_span
        visible = [
            (
                max(float(y0) + y_guard, min(float(y1) - y_guard, float(y))),
                str(text),
            )
            for y, text in ticks
            if float(y0) - y_guard <= float(y) <= float(y1) + y_guard
        ]
        self._sync_axis_tick_items(
            self._y_tick_label_items,
            len(visible),
            anchor=(1.0, 0.5),
        )
        for item, (y, text) in zip(self._y_tick_label_items, visible):
            item.setHtml(self._axis_tick_html(text, color))
            item.setPos(x, y)
            item.show()

    def _sync_x_tick_labels_from_axis(self) -> None:
        axis = self.plot.getPlotItem().getAxis("bottom")
        levels = getattr(axis, "_tickLevels", [])
        ticks = list(levels[0]) if levels else []
        self._sync_x_tick_labels(ticks)

    def _update_x_ticks(self) -> None:
        """时间轴只画 ~10 等分整刻度线（无细密小网格），随缩放自适应。"""
        vb = self.plot.getPlotItem().getViewBox()
        try:
            x0, x1 = vb.viewRange()[0]
        except Exception:
            return
        span = x1 - x0
        if span <= 0:
            return
        if not self._x_scale_updating:
            self._x_target_us_per_div = _quantize_x_us_per_div(_exact_x_us_per_div(span))
        self._x_us_per_div = self._x_target_us_per_div
        self._sync_x_scale_readout()
        step = self._x_tick_step_for_range(float(x0), float(x1))
        ticks = _x_axis_ticks(float(x0), float(x1), step)
        self._graticule_x_ticks = [float(x) for x, _text in ticks]
        self._sync_graticule_dots()
        self.plot.getPlotItem().getAxis("bottom").setTicks([ticks])
        self._sync_x_tick_labels(ticks)

    def _is_full_x_view(self, x0: float, x1: float) -> bool:
        if self._full_x_range is None:
            return False
        f0, f1 = self._full_x_range
        full_span = max(float(f1) - float(f0), 1e-12)
        tol = max(1e-6, full_span * 1e-5)
        return abs(float(x0) - float(f0)) <= tol and abs(float(x1) - float(f1)) <= tol

    def _x_tick_step_for_range(
        self, x0: float, x1: float, *, prefer_scope: bool = False
    ) -> float:
        span = float(x1) - float(x0)
        if span <= 0:
            return 0.0
        if (prefer_scope or self._is_full_x_view(x0, x1)) and self._scope_x_us_per_div:
            return float(self._scope_x_us_per_div)
        return _nice_per_div(span, target_div=HORIZONTAL_DIV_COUNT)

    def _update_overview_x_ticks(self) -> None:
        if self._full_x_range is None:
            return
        f0, f1 = self._full_x_range
        step = self._x_tick_step_for_range(float(f0), float(f1), prefer_scope=True)
        ticks = _x_axis_ticks(float(f0), float(f1), step)
        self._overview_plot.getPlotItem().getAxis("bottom").setTicks([ticks])

    def _sync_x_scale_readout(self, scale_us: float | None = None) -> None:
        if scale_us is None:
            scale_us = self._x_target_us_per_div
        self._x_scale_edit.blockSignals(True)
        self._x_scale_edit.setText(_format_time_per_div(scale_us))
        self._x_scale_edit.blockSignals(False)
        if hasattr(self, "_x_zoom_factor_label"):
            if self._full_x_range is not None and scale_us > 0:
                f0, f1 = self._full_x_range
                full_span = max(float(f1) - float(f0), 1e-12)
                factor = full_span / max(scale_us * HORIZONTAL_DIV_COUNT, 1e-12)
            else:
                factor = 1.0
            self._x_zoom_factor_label.setText(f"({factor:.2f}x 缩放)")

    def _x_scale_limits_us(self) -> tuple[float, float]:
        min_scale = MIN_X_SPAN_US / HORIZONTAL_DIV_COUNT
        if self._full_x_range is not None:
            max_scale = (self._full_x_range[1] - self._full_x_range[0]) / HORIZONTAL_DIV_COUNT
        else:
            max_scale = min_scale * 1e6
        return min_scale, max(max_scale, min_scale)

    def _apply_x_us_per_div(self, scale_us: float, center_us: float | None = None) -> None:
        """按指定 µs/格 设置横向视窗（10 格），保持视窗中心不变。"""
        min_scale, max_scale = self._x_scale_limits_us()
        scale_us = _quantize_x_us_per_div(scale_us)
        scale_us = max(min_scale, min(max_scale, scale_us))
        self._x_target_us_per_div = scale_us
        self._x_us_per_div = scale_us

        vb = self.plot.getPlotItem().getViewBox()
        if center_us is None:
            x0, x1 = vb.viewRange()[0]
            center_us = (float(x0) + float(x1)) * 0.5
        span = scale_us * HORIZONTAL_DIV_COUNT
        x0 = center_us - span * 0.5
        x1 = center_us + span * 0.5
        if self._full_x_range is not None:
            f0, f1 = self._full_x_range
            if x0 < f0:
                shift = f0 - x0
                x0 += shift
                x1 += shift
            if x1 > f1:
                shift = x1 - f1
                x0 -= shift
                x1 -= shift
            if x1 - x0 < MIN_X_SPAN_US:
                x0, x1 = center_us - MIN_X_SPAN_US * 0.5, center_us + MIN_X_SPAN_US * 0.5
            x0 = max(f0, x0)
            x1 = min(f1, x1)

        self._x_scale_updating = True
        try:
            vb.setXRange(x0, x1, padding=0.0)
            self._sync_x_scale_readout(scale_us)
        finally:
            self._x_scale_updating = False

    def _remember_user_x_scale(self, scale_us: float) -> None:
        self._user_x_us_per_div = _quantize_x_us_per_div(scale_us)

    def _param_focus_x_scale_us(self) -> float:
        if self._user_x_us_per_div is not None:
            return self._user_x_us_per_div
        return PARAM_FOCUS_DEFAULT_US_PER_DIV

    def _on_x_wheel(self, ev) -> bool:
        """滚轮离散调节水平标度（ns 档：50/100/150…，每档 ±50ns）。"""
        delta = _wheel_delta_y(ev)
        if delta == 0:
            return False
        vb = self.plot.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        cur = _quantize_x_us_per_div(
            self._x_target_us_per_div or _exact_x_us_per_div(x1 - x0)
        )
        min_scale, max_scale = self._x_scale_limits_us()
        min_scale = _quantize_x_us_per_div(min_scale)
        max_scale = _quantize_x_us_per_div(max_scale)
        if cur < 1.0:
            cur_ns = int(round(cur * 1000.0))
            if delta > 0:
                new_ns = max(X_NS_PER_DIV, cur_ns - X_NS_PER_DIV)
            else:
                new_ns = cur_ns + X_NS_PER_DIV
            new_scale = _quantize_x_us_per_div(new_ns / 1000.0)
        else:
            step = _x_wheel_step_us(cur)
            if delta > 0:
                new_scale = max(1.0, cur - step)
            else:
                new_scale = cur + step
            new_scale = _quantize_x_us_per_div(new_scale)
        new_scale = max(min_scale, min(max_scale, new_scale))
        if abs(new_scale - cur) < 1e-15:
            return True
        self._apply_x_us_per_div(new_scale)
        self._remember_user_x_scale(new_scale)
        return True

    def _step_x_scale(self, *, zoom_in: bool) -> None:
        vb = self.plot.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        cur = _quantize_x_us_per_div(
            self._x_target_us_per_div or _exact_x_us_per_div(x1 - x0)
        )
        min_scale, max_scale = self._x_scale_limits_us()
        step = X_NS_PER_DIV / 1000.0 if cur < 1.0 else _x_wheel_step_us(cur)
        new_scale = cur - step if zoom_in else cur + step
        new_scale = _quantize_x_us_per_div(max(min_scale, min(max_scale, new_scale)))
        if abs(new_scale - cur) < 1e-15:
            return
        self._apply_x_us_per_div(new_scale)
        self._remember_user_x_scale(new_scale)

    def _on_x_scale_committed(self) -> None:
        if self._x_scale_updating:
            return
        parsed = _parse_time_per_div_input(self._x_scale_edit.text())
        if parsed is None:
            self._sync_x_scale_readout()
            return
        self._apply_x_us_per_div(parsed)
        self._remember_user_x_scale(parsed)

    def selection_zoom_switch_enabled(self) -> bool:
        return self._selection_zoom_enabled

    def set_selection_zoom_switch_enabled(self, enabled: bool) -> None:
        self._set_selection_zoom_enabled(bool(enabled))

    def _set_selection_zoom_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        changed = self._selection_zoom_enabled != enabled
        self._selection_zoom_enabled = enabled
        if self._zoom_select_btn.isChecked() != enabled:
            self._zoom_select_btn.blockSignals(True)
            try:
                self._zoom_select_btn.setChecked(enabled)
            finally:
                self._zoom_select_btn.blockSignals(False)
        if self._selection_zoom_enabled:
            self.plot.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.plot.unsetCursor()
            self._clear_selection_rect()
        if changed:
            self.selectionZoomChanged.emit(self._selection_zoom_enabled)

    def _finish_selection_zoom_mode(self) -> None:
        self._set_selection_zoom_enabled(False)

    def _arm_selection_zoom(self) -> None:
        self._set_selection_zoom_enabled(True)

    # ---- 每通道垂直刻度换算（显示坐标 = 原始值 / 刻度 + 位置偏移）----
    def _selection_button_is_left(self, ev) -> bool:
        btn_fn = getattr(ev, "button", None)
        btn = btn_fn() if callable(btn_fn) else None
        return btn in (None, Qt.MouseButton.LeftButton)

    def _ensure_selection_rect(self, start: QPointF) -> None:
        if self._selection_rect_item is None:
            item = QGraphicsRectItem(QRectF(start, start))
            fill = QColor("#1e90ff")
            fill.setAlpha(45)
            item.setPen(_spaced_dash_pen("#8fd3ff", 1.4))
            item.setBrush(QBrush(fill))
            item.setZValue(200)
            self.plot.scene().addItem(item)
            self._selection_rect_item = item
        else:
            self._selection_rect_item.setRect(QRectF(start, start))
            self._selection_rect_item.show()

    def _clear_selection_rect(self) -> None:
        if self._selection_rect_item is not None:
            self.plot.scene().removeItem(self._selection_rect_item)
            self._selection_rect_item = None
        self._selection_start_scene = None

    def _apply_selection_zoom(self, p0: QPointF, p1: QPointF) -> bool:
        vb = self.plot.getPlotItem().getViewBox()
        v0 = vb.mapSceneToView(p0)
        v1 = vb.mapSceneToView(p1)
        x0, x1 = sorted((float(v0.x()), float(v1.x())))
        y0, y1 = sorted((float(v0.y()), float(v1.y())))
        if self._full_x_range is not None:
            f0, f1 = self._full_x_range
            x0 = max(f0, min(f1, x0))
            x1 = max(f0, min(f1, x1))
        if x1 - x0 < MIN_X_SPAN_US or y1 - y0 < 0.05:
            return False
        vb.setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0.0)
        self._last_x_window = (x0, x1)
        self._x_target_us_per_div = _quantize_x_us_per_div(
            _exact_x_us_per_div(x1 - x0)
        )
        self._x_us_per_div = self._x_target_us_per_div
        self._remember_user_x_scale(self._x_target_us_per_div)
        self._sync_x_scale_readout()
        self._update_y_ticks()
        return True

    def _on_selection_drag(self, ev) -> bool:
        if (
            not self._selection_zoom_enabled
            or self._full_x_range is None
            or not self._selection_button_is_left(ev)
        ):
            return False
        is_start = getattr(ev, "isStart", lambda: False)
        is_finish = getattr(ev, "isFinish", lambda: False)
        if is_start():
            self._selection_start_scene = QPointF(ev.scenePos())
            self._ensure_selection_rect(self._selection_start_scene)
            ev.accept()
            return True
        if self._selection_start_scene is None:
            return False

        cur = QPointF(ev.scenePos())
        rect = QRectF(self._selection_start_scene, cur).normalized()
        if self._selection_rect_item is not None:
            self._selection_rect_item.setRect(rect)

        if is_finish():
            start = QPointF(self._selection_start_scene)
            self._clear_selection_rect()
            applied = False
            if rect.width() >= 8 and rect.height() >= 8:
                applied = self._apply_selection_zoom(start, cur)
            if applied:
                self._finish_selection_zoom_mode()
            ev.accept()
            return True

        ev.accept()
        return True

    def _axis_channel(self) -> str | None:
        if (
            self._highlighted_key is not None
            and self._highlighted_key in self._trace_items
            and self._highlighted_key not in self._hidden_channels
        ):
            return self._highlighted_key
        ch = self._readout_channel()
        if ch in self._trace_items and ch not in self._hidden_channels:
            return ch
        for key in self._trace_items:
            if key not in self._hidden_channels:
                return key
        return None

    def _axis_tick_color(self) -> str:
        ch = self._axis_channel()
        if ch is None:
            return WAVEFORM_PLOT_FG
        return self._trace_style.get(ch, (WAVEFORM_PLOT_FG, 1.0))[0]

    @staticmethod
    def _format_axis_value(value: float, unit: str) -> str:
        if _is_power_unit(unit):
            return _format_power_axis_value(value, unit)
        abs_v = abs(float(value))
        prefix = ""
        scale = 1.0
        if abs_v >= 1000.0 and unit in {"V", "A"}:
            prefix = "k"
            scale = 1000.0
        elif unit == "J":
            if 0.0 < abs_v < 1.0:
                prefix = "m"
                scale = 1e-3
            elif abs_v >= 1000.0:
                prefix = "k"
                scale = 1000.0
        disp = float(value) / scale
        if abs(disp) < 1e-9:
            disp = 0.0
        if abs(disp - round(disp)) < 1e-6:
            text = f"{int(round(disp))}"
        elif abs(disp) >= 10.0:
            text = f"{disp:.1f}".rstrip("0").rstrip(".")
        else:
            text = f"{disp:.2f}".rstrip("0").rstrip(".")
        suffix = f" {prefix}{unit}" if unit else ""
        return f"{text}{suffix}"

    def _update_y_ticks(self) -> None:
        vb = self.plot.getPlotItem().getViewBox()
        try:
            x0, x1 = vb.viewRange()[0]
            y0, y1 = vb.viewRange()[1]
        except Exception:
            return
        ch = self._axis_channel()
        if ch is None:
            ticks = [
                (i, str(i))
                for i in range(-int(DISP_HALF_DIV), int(DISP_HALF_DIV) + 1)
            ]
            signature = (
                None,
                round(float(x0), 9),
                round(float(x1), 9),
                round(float(y0), 9),
                round(float(y1), 9),
            )
            color = self._axis_tick_color()
        else:
            import math

            unit = self._unit_for_channel(ch)
            scale = self._disp_scale.get(ch, 1.0)
            offset = self._disp_offset.get(ch, 0.0)
            span = max(abs(float(y1) - float(y0)), 1e-9)
            div_step = max(1, int(math.ceil(span / 12.0)))
            for candidate in (1, 2, 5, 10, 20, 50):
                if candidate >= div_step:
                    div_step = candidate
                    break
            start_n = math.ceil((float(y0) - offset) / div_step - 1e-9)
            end_n = math.floor((float(y1) - offset) / div_step + 1e-9)
            ticks = []
            n = int(start_n)
            count = 0
            while n <= int(end_n) and count < 80:
                y = offset + n * div_step
                raw_value = n * div_step * scale
                ticks.append((y, self._format_axis_value(raw_value, unit)))
                n += 1
                count += 1
            color = self._axis_tick_color()
            signature = (
                ch,
                round(float(x0), 9),
                round(float(x1), 9),
                round(float(y0), 9),
                round(float(y1), 9),
                round(float(scale), 9),
                round(float(offset), 9),
                self._highlighted_key,
            )
        if signature == self._axis_last_signature:
            self._graticule_y_ticks = [float(y) for y, _text in ticks]
            self._sync_graticule_dots()
            self._sync_y_tick_labels(ticks, color)
            return
        self._axis_last_signature = signature
        self._graticule_y_ticks = [float(y) for y, _text in ticks]
        self._sync_graticule_dots()
        ax = self.plot.getPlotItem().getAxis("right")
        ax.setTicks([ticks])
        ax.setPen(pg.mkPen(color))
        ax.setTextPen(pg.mkPen(color))
        ax.showLabel(False)
        self._sync_y_tick_labels(ticks, color)
        bottom_ax = self.plot.getPlotItem().getAxis("bottom")
        bottom_ax.setPen(pg.mkPen(color))
        bottom_ax.setTextPen(pg.mkPen(color))
        overview_bottom_ax = self._overview_plot.getPlotItem().getAxis("bottom")
        overview_bottom_ax.setPen(pg.mkPen(color))
        overview_bottom_ax.setTextPen(pg.mkPen(color))
        self._sync_x_tick_labels_from_axis()

    def _to_disp(self, channel: str, value: float) -> float:
        channel = self._display_key_for_channel(channel)
        scale = self._disp_scale.get(channel, 1.0)
        offset = self._disp_offset.get(channel, 0.0)
        return (float(value) / scale if scale else float(value)) + offset

    def _from_disp(self, channel: str, y_div: float) -> float:
        channel = self._display_key_for_channel(channel)
        scale = self._disp_scale.get(channel, 1.0)
        offset = self._disp_offset.get(channel, 0.0)
        return (float(y_div) - offset) * scale

    def _display_inversion_enabled(self, key: str) -> bool:
        base = channel_reference_base_name(key)
        return bool(base and f"-{base}" in self._manual_inverted_channels)

    def _source_inversion_enabled(self, key: str) -> bool:
        base = channel_reference_base_name(key)
        return bool(base and f"-{base}" in self._source_inverted_channels)

    def _display_transform_inverted(self, key: str) -> bool:
        base = channel_reference_base_name(key)
        return bool(
            base
            and self._display_inversion_enabled(base)
            != self._source_inversion_enabled(base)
        )

    def _effective_raw_for_channel(
        self,
        channel: str | None,
        *,
        include_display_inversion: bool = True,
    ) -> np.ndarray | None:
        ref = normalize_channel_reference(channel)
        if not ref:
            return None
        sign, base = split_channel_reference(ref)
        raw = self._trace_raw.get(ref)
        if raw is None and base:
            raw = self._trace_raw.get(base)
        if raw is None:
            return None
        arr = np.asarray(raw, dtype=np.float64)
        if sign < 0:
            return -arr
        if include_display_inversion and self._display_transform_inverted(base or ref):
            return -arr
        return arr

    def current_display_raw(self, channel: str | None) -> np.ndarray | None:
        """Return the full-resolution waveform currently shown for a channel."""
        return self._effective_raw_for_channel(channel, include_display_inversion=True)

    def _effective_reference_for_channel(self, channel: str | None) -> str:
        ref = normalize_channel_reference(channel)
        sign, base = split_channel_reference(ref)
        if not base or sign < 0:
            return ref
        if self._display_transform_inverted(base):
            return f"-{base}"
        return base

    def effective_profile_for_channel_inversions(
        self, profile: BridgeProfile
    ) -> BridgeProfile:
        """Profile used for calculations when source channels are display-inverted."""

        return replace(
            profile,
            vge=self._effective_reference_for_channel(profile.vge),
            vce=self._effective_reference_for_channel(profile.vce),
            ic=self._effective_reference_for_channel(profile.ic),
            il=self._effective_reference_for_channel(profile.il),
            irr=self._effective_reference_for_channel(profile.irr),
            v_diode=self._effective_reference_for_channel(profile.v_diode),
            vge_other=self._effective_reference_for_channel(profile.vge_other),
            vdesat=self._effective_reference_for_channel(profile.vdesat),
        )

    def _current_x_window_for_display(self) -> tuple[float, float] | None:
        if self._trace_t_us is None or len(self._trace_t_us) == 0:
            return None
        try:
            x0, x1 = self.plot.getPlotItem().getViewBox().viewRange()[0]
            return float(x0), float(x1)
        except Exception:
            if self._full_x_range is not None:
                return self._full_x_range
            return float(self._trace_t_us[0]), float(self._trace_t_us[-1])

    def _refresh_visible_traces(self, *, force: bool = False) -> None:
        if self._trace_display_updating or self._trace_t_us is None:
            return
        win = self._current_x_window_for_display()
        if win is None:
            return
        x0, x1 = win
        signature = (round(float(x0), 6), round(float(x1), 6))
        if not force and signature == self._trace_view_signature:
            return
        self._trace_display_updating = True
        try:
            for key, item in self._trace_items.items():
                raw = self._effective_raw_for_channel(key)
                if raw is None:
                    continue
                scale = self._disp_scale.get(key, 1.0) or 1.0
                offset = self._disp_offset.get(key, 0.0)
                tx, raw_disp = _display_curve_data(
                    self._trace_t_us, np.asarray(raw, dtype=np.float64), x0, x1
                )
                yy = raw_disp / float(scale) + float(offset)
                item.setData(tx, yy)
            self._trace_view_signature = signature
        finally:
            self._trace_display_updating = False

    def _refresh_visible_trace(self, key: str) -> None:
        if self._trace_display_updating or self._trace_t_us is None:
            return
        item = self._trace_items.get(key)
        raw = self._effective_raw_for_channel(key)
        if item is None or raw is None:
            return
        win = self._current_x_window_for_display()
        if win is None:
            return
        x0, x1 = win
        scale = self._disp_scale.get(key, 1.0) or 1.0
        offset = self._disp_offset.get(key, 0.0)
        tx, raw_disp = _display_curve_data(
            self._trace_t_us, np.asarray(raw, dtype=np.float64), x0, x1
        )
        item.setData(tx, raw_disp / float(scale) + float(offset))

    def _overview_trace_data(self, key: str) -> tuple[np.ndarray, np.ndarray] | None:
        if self._trace_t_us is None or self._full_x_range is None:
            return None
        raw = self._effective_raw_for_channel(key)
        if raw is None:
            return None
        f0, f1 = self._full_x_range
        tx, raw_disp = _display_curve_data(
            self._trace_t_us, np.asarray(raw, dtype=np.float64), f0, f1
        )
        scale = self._disp_scale.get(key, 1.0) or 1.0
        offset = self._disp_offset.get(key, 0.0)
        return tx, raw_disp / float(scale) + float(offset)

    def _clear_overview_traces(self) -> None:
        for item in list(self._overview_items.values()):
            self._overview_plot.removeItem(item)
        self._overview_items.clear()
        self._overview_plot.hide()
        self._scope_scale_bar.hide()
        self._zoom_toggle_btn.hide()

    def _refresh_overview_traces(self) -> None:
        if self._trace_t_us is None or self._full_x_range is None:
            self._clear_overview_traces()
            return
        for key, item in list(self._overview_items.items()):
            if key not in self._trace_items:
                self._overview_plot.removeItem(item)
                self._overview_items.pop(key, None)
        for key in self._trace_items:
            data = self._overview_trace_data(key)
            if data is None:
                continue
            tx, yy = data
            color, width = self._trace_style.get(key, ("#d0d0d0", 1.0))
            item = self._overview_items.get(key)
            if item is None:
                item = self._overview_plot.plot(
                    tx,
                    yy,
                    pen=pg.mkPen(color, width=max(1.0, float(width) * 0.72)),
                )
                item.setClipToView(True)
                item.setZValue(0)
                self._overview_items[key] = item
            else:
                item.setData(tx, yy)
                item.setPen(pg.mkPen(color, width=max(1.0, float(width) * 0.72)))
            item.setVisible(key not in self._hidden_channels)
        f0, f1 = self._full_x_range
        self._overview_region.setBounds((f0, f1))
        self._overview_plot.getPlotItem().getViewBox().setLimits(
            xMin=f0,
            xMax=f1,
            minXRange=f1 - f0,
            maxXRange=f1 - f0,
        )
        self._overview_plot.setXRange(f0, f1, padding=0.0)
        self._overview_plot.setYRange(-DISP_HALF_DIV, DISP_HALF_DIV, padding=0.0)
        self._update_overview_x_ticks()
        self._sync_overview_region_to_main()

    def _refresh_overview_trace(self, key: str) -> None:
        item = self._overview_items.get(key)
        if item is None or key not in self._trace_items:
            return
        data = self._overview_trace_data(key)
        if data is None:
            return
        tx, yy = data
        color, width = self._trace_style.get(key, ("#d0d0d0", 1.0))
        item.setData(tx, yy)
        item.setPen(pg.mkPen(color, width=max(1.0, float(width) * 0.72)))
        item.setVisible(key not in self._hidden_channels)

    def _is_local_x_window(self, x0: float, x1: float) -> bool:
        if self._full_x_range is None:
            return False
        f0, f1 = self._full_x_range
        full_span = max(float(f1) - float(f0), 1e-12)
        span = max(0.0, float(x1) - float(x0))
        return span < full_span - max(1e-6, full_span * 1e-5)

    def _clamp_x_window(self, x0: float, x1: float) -> tuple[float, float]:
        if self._full_x_range is None:
            return float(x0), float(x1)
        f0, f1 = self._full_x_range
        lo, hi = sorted((float(x0), float(x1)))
        span = max(MIN_X_SPAN_US, hi - lo)
        span = min(span, max(MIN_X_SPAN_US, float(f1) - float(f0)))
        center = 0.5 * (lo + hi)
        lo = center - 0.5 * span
        hi = center + 0.5 * span
        if lo < f0:
            hi += f0 - lo
            lo = f0
        if hi > f1:
            lo -= hi - f1
            hi = f1
        lo = max(f0, lo)
        hi = min(f1, hi)
        return float(lo), float(hi)

    def _sync_overview_region_to_main(self) -> None:
        if self._overview_syncing:
            return
        if self._full_x_range is None or self._trace_t_us is None:
            self._overview_plot.hide()
            self._scope_scale_bar.hide()
            self._zoom_toggle_btn.hide()
            return
        try:
            x0, x1 = self.plot.getPlotItem().getViewBox().viewRange()[0]
        except Exception:
            self._overview_plot.hide()
            self._scope_scale_bar.hide()
            self._zoom_toggle_btn.hide()
            return
        x0, x1 = self._clamp_x_window(float(x0), float(x1))
        if not self._is_local_x_window(x0, x1):
            self._overview_plot.hide()
            self._scope_scale_bar.hide()
            if self._recent_local_x_window is not None:
                self._zoom_toggle_btn.show()
                self._position_zoom_toggle_button()
            else:
                self._zoom_toggle_btn.hide()
            return
        self._recent_local_x_window = (x0, x1)
        self._overview_plot.show()
        self._scope_scale_bar.show()
        self._zoom_toggle_btn.show()
        self._position_zoom_toggle_button()
        self._overview_syncing = True
        try:
            self._overview_region.setRegion((x0, x1))
        finally:
            self._overview_syncing = False

    def _on_overview_region_changed(self) -> None:
        if self._overview_syncing or self._full_x_range is None:
            return
        x0, x1 = self._overview_region.getRegion()
        x0, x1 = self._clamp_x_window(float(x0), float(x1))
        self._overview_syncing = True
        try:
            current = tuple(float(v) for v in self._overview_region.getRegion())
            if abs(current[0] - x0) > 1e-9 or abs(current[1] - x1) > 1e-9:
                self._overview_region.setRegion((x0, x1))
            self.plot.getPlotItem().getViewBox().setXRange(x0, x1, padding=0.0)
            self._last_x_window = (x0, x1)
            self._x_target_us_per_div = _quantize_x_us_per_div(
                _exact_x_us_per_div(x1 - x0)
            )
            self._x_us_per_div = self._x_target_us_per_div
            self._remember_user_x_scale(self._x_target_us_per_div)
            self._sync_x_scale_readout()
            self._recent_local_x_window = (x0, x1)
        finally:
            self._overview_syncing = False

    def _exit_local_zoom(self) -> None:
        if self._full_x_range is None:
            return
        self._fit_full_range()

    def _toggle_zoom_preview(self) -> None:
        if self._full_x_range is None:
            return
        try:
            x0, x1 = self.plot.getPlotItem().getViewBox().viewRange()[0]
        except Exception:
            x0, x1 = self._full_x_range
        if self._is_local_x_window(float(x0), float(x1)):
            self._recent_local_x_window = self._clamp_x_window(float(x0), float(x1))
            self._fit_full_range()
            return
        if self._recent_local_x_window is None:
            return
        lx0, lx1 = self._clamp_x_window(*self._recent_local_x_window)
        self.plot.getPlotItem().getViewBox().setXRange(lx0, lx1, padding=0.0)

    def _position_zoom_toggle_button(self) -> None:
        if not hasattr(self, "_zoom_toggle_btn"):
            return
        target = self._overview_plot if not self._overview_plot.isHidden() else self.plot
        should_show = not self._zoom_toggle_btn.isHidden()
        if self._zoom_toggle_btn.parentWidget() is not target:
            self._zoom_toggle_btn.setParent(target)
        margin = 8
        x = max(margin, target.width() - self._zoom_toggle_btn.width() - margin)
        y = margin
        self._zoom_toggle_btn.move(x, y)
        if should_show:
            self._zoom_toggle_btn.show()
        self._zoom_toggle_btn.raise_()

    def _reset_view(self) -> None:
        self._fit_full_range()

    def _fit_last_window(self) -> None:
        if self._last_x_window is None:
            return
        x0, x1 = self._last_x_window
        vb = self.plot.getPlotItem().getViewBox()
        vb.setXRange(x0, x1, padding=0.0)
        self._apply_disp_yrange()

    def _fit_full_range(self) -> None:
        if self._full_x_range is None:
            return
        x0, x1 = self._full_x_range
        vb = self.plot.getPlotItem().getViewBox()
        vb.setXRange(x0, x1, padding=0.0)
        self._apply_disp_yrange()

    def _unit_for_channel(self, key: str) -> str:
        key = self._display_key_for_channel(key)
        return self._lookup_channel_unit(
            self._trace_units,
            key,
        ) or self._lookup_channel_unit(CHANNEL_UNITS, key)

    @staticmethod
    def _lookup_channel_unit(units: dict[str, str], key: str | None) -> str:
        raw = str(key or "").strip()
        ref = normalize_channel_reference(key)
        base = channel_reference_base_name(ref)
        candidates = (
            raw,
            raw.upper(),
            raw.lower(),
            ref,
            base,
            ref.lower(),
            base.lower(),
        )
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate:
                unit = str(units.get(candidate) or "").strip()
                if unit:
                    return unit
        return ""

    def _formula_source_names(self) -> list[str]:
        def _sort_key(name: str) -> tuple[int, int, str]:
            m = re.search(r"\d+", name)
            return (
                0 if name.upper().startswith("CH") else 1,
                int(m.group(0)) if m else 0,
                name,
            )

        return sorted(self._formula_sources, key=_sort_key)

    def _normalize_formula(self, expr: str) -> str:
        expr = expr.strip()
        expr = re.sub(r"\bMath\s*(\d+)\b", r"MATH\1", expr, flags=re.I)
        expr = re.sub(r"\bCh\s*(\d+)\b", r"CH\1", expr, flags=re.I)
        expr = re.sub(r"\bAND\b(?!\s*\()", "and", expr, flags=re.I)
        expr = re.sub(r"\bOR\b(?!\s*\()", "or", expr, flags=re.I)
        expr = re.sub(r"\bXOR\b(?!\s*\()", "^", expr, flags=re.I)
        return expr

    @staticmethod
    def _logic_array(value) -> np.ndarray:
        return np.asarray(value) != 0

    @staticmethod
    def _logic_float(value) -> np.ndarray:
        return np.asarray(value, dtype=bool).astype(np.float64)

    def _formula_unit(
        self,
        expr: str,
        unit_overrides: dict[str, str] | None = None,
    ) -> str:
        text = expr.upper()
        if "INTG" in text or "INTEG" in text:
            return "J"
        source_refs = re.findall(rf"\b{SOURCE_CHANNEL_PATTERN}\b", text)
        if "*" in text and len(set(ref.upper() for ref in source_refs)) >= 2:
            return "W"
        for name in source_refs:
            unit = (
                self._lookup_channel_unit(unit_overrides or {}, name)
                or self._lookup_channel_unit(self._trace_units, name)
                or self._lookup_channel_unit(CHANNEL_UNITS, name)
            )
            if unit:
                return unit
        return ""

    def _source_trace_unit(
        self,
        key: str,
        expr: str | None,
        file_units: dict[str, str],
        override_units: dict[str, str],
        role_units: dict[str, str],
        saved_units: dict[str, str],
    ) -> str:
        unit_context = dict(saved_units)
        unit_context.update(role_units)
        unit_context.update(file_units)
        unit_context.update(override_units)
        override_unit = self._lookup_channel_unit(override_units, key)
        if override_unit:
            return override_unit
        file_unit = self._lookup_channel_unit(file_units, key)
        if file_unit:
            return file_unit
        if expr:
            formula_unit = self._formula_unit(expr, unit_context)
            if formula_unit:
                return formula_unit
        return (
            self._lookup_channel_unit(saved_units, key)
            or self._lookup_channel_unit(role_units, key)
            or self._lookup_channel_unit(CHANNEL_UNITS, key)
        )

    @staticmethod
    def _metadata_channel_units(meta_units: dict[str, str]) -> dict[str, str]:
        units: dict[str, str] = {}
        for channel, unit in meta_units.items():
            ref = normalize_channel_reference(channel)
            base = channel_reference_base_name(ref)
            text = str(unit or "").strip()
            if not text:
                continue
            if base:
                units[base] = text
            if ref:
                units[ref] = text
        return units

    def channel_unit_override(self, key: str) -> str:
        key = normalize_channel_reference(key)
        base = channel_reference_base_name(key)
        return self._lookup_channel_unit(self._unit_overrides, base or key)

    def source_file_unit(self, key: str) -> str:
        key = normalize_channel_reference(key)
        base = channel_reference_base_name(key)
        return self._lookup_channel_unit(self._source_file_units, base or key)

    @staticmethod
    def _physical_channel_units(profile: BridgeProfile) -> dict[str, str]:
        units: dict[str, str] = {}

        def add_unit(channel: str, unit: str) -> None:
            ref = normalize_channel_reference(channel)
            base = channel_reference_base_name(ref)
            if base:
                units[base] = unit
            if ref:
                units[ref] = unit

        for channel, unit in (
            (profile.vge, "V"),
            (profile.vce, "V"),
            (profile.ic, "A"),
            (profile.irr, "A"),
            (profile.il, "A"),
            (profile.v_diode, "V"),
            (profile.vge_other, "V"),
            (profile.vdesat, "V"),
        ):
            if channel:
                add_unit(channel, unit)
        return units

    @staticmethod
    def _logical_display_key_map(profile: BridgeProfile) -> dict[str, str]:
        mapping: dict[str, str] = {}

        def display_ref(channel: str) -> str:
            ref = normalize_channel_reference(channel)
            return channel_reference_base_name(ref) or ref

        for logical, channel in (
            ("vge", profile.vge),
            ("vce", profile.vce),
            ("ic", profile.ic),
            ("il", profile.il),
            ("irr", profile.irr),
            ("v_diode", profile.v_diode),
            ("vge_other", profile.vge_other),
            ("vdesat", profile.vdesat),
        ):
            if channel:
                mapping[logical] = display_ref(channel)
        if profile.ic_from_sum_irr_il and not profile.ic:
            mapping["ic"] = display_ref(
                profile.irr or profile.il or profile.ic
            )
        if profile.irr_from_ic_minus_il and not profile.irr:
            mapping["irr"] = display_ref(
                profile.irr or profile.ic or profile.il
            )
        return mapping

    @staticmethod
    def _build_display_channel_roles(
        profile: BridgeProfile, logical_map: dict[str, str] | None = None
    ) -> dict[str, list[str]]:
        labels = {
            "vge": "Vge",
            "vce": "Vce",
            "ic": "Ic",
            "il": "IL",
            "irr": "Irr",
            "v_diode": "V_二极管",
            "vge_other": "对管Vge",
            "vdesat": "Vdesat",
        }
        roles: dict[str, list[str]] = {}
        display_map = logical_map or WaveformPlot._logical_display_key_map(profile)
        for logical, channel in display_map.items():
            if channel:
                roles.setdefault(channel, []).append(labels.get(logical, logical))
        if profile.ic_from_sum_irr_il and not profile.ic:
            for channel in (profile.irr, profile.il):
                if channel:
                    role_list = roles.setdefault(
                        channel_reference_base_name(channel) or normalize_channel_reference(channel),
                        [],
                    )
                    if "Ic" in role_list:
                        role_list.remove("Ic")
                    if "Ic=Irr+IL" not in role_list:
                        role_list.append("Ic=Irr+IL")
        if profile.irr_from_ic_minus_il and not profile.irr:
            for channel in (profile.ic, profile.il):
                if channel:
                    role_list = roles.setdefault(
                        channel_reference_base_name(channel) or normalize_channel_reference(channel),
                        [],
                    )
                    if "Irr" in role_list:
                        role_list.remove("Irr")
                    if "Irr=Ic-IL" not in role_list:
                        role_list.append("Irr=Ic-IL")
        return roles

    @staticmethod
    def _formula_tokens(expr: str) -> tuple[list[str], list[str]]:
        text = re.sub(r"\s+", "", expr.upper())
        tokens = re.findall(SOURCE_CHANNEL_PATTERN, text)
        ops = re.findall(r"[+\-*/]", text)
        return tokens, ops

    @staticmethod
    def _is_sum_formula(expr: str, a: str, b: str) -> bool:
        tokens, ops = WaveformPlot._formula_tokens(expr)
        return (
            len(tokens) == 2
            and set(tokens)
            == {channel_reference_base_name(a), channel_reference_base_name(b)}
            and ops == ["+"]
            and channel_reference_sign(a) > 0
            and channel_reference_sign(b) > 0
        )

    @staticmethod
    def _is_difference_formula(expr: str, a: str, b: str) -> bool:
        tokens, ops = WaveformPlot._formula_tokens(expr)
        return (
            tokens == [channel_reference_base_name(a), channel_reference_base_name(b)]
            and ops == ["-"]
            and channel_reference_sign(a) > 0
            and channel_reference_sign(b) > 0
        )

    def _prefer_math_display_keys_for_derived_currents(
        self,
        profile: BridgeProfile,
        formulas: dict[str, str],
    ) -> None:
        """Bind derived logical currents to visible TSS Math traces when available."""
        if (
            profile.ic_from_sum_irr_il
            and not profile.ic
            and profile.irr
            and profile.il
        ):
            for key, expr in formulas.items():
                if self._is_sum_formula(expr, profile.irr, profile.il):
                    self._logical_display_keys["ic"] = key.upper()
                    break
        if (
            profile.irr_from_ic_minus_il
            and not profile.irr
            and profile.ic
            and profile.il
        ):
            for key, expr in formulas.items():
                if self._is_difference_formula(expr, profile.ic, profile.il):
                    self._logical_display_keys["irr"] = key.upper()
                    break

    def _display_key_for_channel(self, channel: str) -> str:
        logical = channel.strip().lower()
        if logical in self._logical_display_keys:
            return self._logical_display_keys[logical]
        return normalize_channel_reference(channel)

    def _logical_role_for_source(self, source_key: str) -> str:
        source_key = normalize_channel_reference(source_key)
        for logical, display_key in self._logical_display_keys.items():
            if display_key == source_key:
                return logical
        return source_key.lower()

    def mapping_role_for_source(self, source_key: str) -> str:
        source_key = normalize_channel_reference(source_key)
        for logical, display_key in self._logical_display_keys.items():
            if display_key == source_key:
                return logical
        return ""

    def _logical_roles_for_source(self, source_key: str) -> set[str]:
        source_key = normalize_channel_reference(source_key)
        roles: set[str] = set()
        for logical, display_key in self._logical_display_keys.items():
            if display_key == source_key:
                roles.add(logical)
        return roles

    def _is_reverse_recovery_power_formula(self, expr: str | None) -> bool:
        if not expr:
            return False
        text = str(expr).upper()
        if "*" not in text:
            return False
        roles: set[str] = set()
        for ref in re.findall(rf"\b{SOURCE_CHANNEL_PATTERN}\b", text):
            roles.update(self._logical_roles_for_source(ref))
        return "v_diode" in roles and "irr" in roles

    def _auto_vdiv_for_trace(
        self,
        key: str,
        raw: np.ndarray,
        *,
        expr: str | None = None,
    ) -> float:
        return _auto_vdiv_for_channel(
            key,
            raw,
            self._unit_for_channel(key),
            reverse_recovery_power=self._is_reverse_recovery_power_formula(expr),
        )

    def request_channel_mapping(self, source_key: str, logical_role: str) -> None:
        self.channelMappingRequested.emit(
            normalize_channel_reference(source_key),
            logical_role,
        )

    def _formula_eval_context(self, target_key: str) -> dict[str, np.ndarray | float]:
        ctx: dict[str, np.ndarray | float] = {}
        for name, arr in self._formula_sources.items():
            if name.upper() != target_key.upper():
                effective = self._effective_raw_for_channel(name)
                if effective is not None and np.shape(effective) == np.shape(arr):
                    ctx[name.upper()] = effective
                else:
                    ctx[name.upper()] = arr
        ctx["PI"] = float(np.pi)
        ctx["E"] = float(np.e)
        return ctx

    def _eval_formula_ast(self, node: ast.AST, ctx: dict[str, np.ndarray | float]):
        if isinstance(node, ast.Expression):
            return self._eval_formula_ast(node.body, ctx)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Only numeric constants are allowed.")
        if isinstance(node, ast.Name):
            name = node.id.upper()
            if name not in ctx:
                raise ValueError(f"Unknown source: {node.id}")
            return ctx[name]
        if isinstance(node, ast.UnaryOp):
            val = self._eval_formula_ast(node.operand, ctx)
            if isinstance(node.op, ast.USub):
                return -val
            if isinstance(node.op, ast.UAdd):
                return val
            raise ValueError("Unsupported unary operator.")
        if isinstance(node, ast.BinOp):
            left = self._eval_formula_ast(node.left, ctx)
            right = self._eval_formula_ast(node.right, ctx)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return np.power(left, right)
            if isinstance(node.op, ast.BitAnd):
                return self._logic_float(np.logical_and(self._logic_array(left), self._logic_array(right)))
            if isinstance(node.op, ast.BitOr):
                return self._logic_float(np.logical_or(self._logic_array(left), self._logic_array(right)))
            if isinstance(node.op, ast.BitXor):
                return self._logic_float(np.logical_xor(self._logic_array(left), self._logic_array(right)))
            raise ValueError("Unsupported operator.")
        if isinstance(node, ast.BoolOp):
            vals = [self._eval_formula_ast(v, ctx) for v in node.values]
            out = vals[0] != 0
            for val in vals[1:]:
                if isinstance(node.op, ast.And):
                    out = np.logical_and(out, val != 0)
                elif isinstance(node.op, ast.Or):
                    out = np.logical_or(out, val != 0)
                else:
                    raise ValueError("Unsupported boolean operator.")
            return self._logic_float(out)
        if isinstance(node, ast.Compare):
            left = self._eval_formula_ast(node.left, ctx)
            out = None
            for op, comp in zip(node.ops, node.comparators):
                right = self._eval_formula_ast(comp, ctx)
                if isinstance(op, ast.Eq):
                    cur = left == right
                elif isinstance(op, ast.NotEq):
                    cur = left != right
                elif isinstance(op, ast.Lt):
                    cur = left < right
                elif isinstance(op, ast.LtE):
                    cur = left <= right
                elif isinstance(op, ast.Gt):
                    cur = left > right
                elif isinstance(op, ast.GtE):
                    cur = left >= right
                else:
                    raise ValueError("Unsupported comparison.")
                out = cur if out is None else np.logical_and(out, cur)
                left = right
            return self._logic_float(out)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Unsupported function.")
            name = node.func.id.upper()
            args = [self._eval_formula_ast(arg, ctx) for arg in node.args]
            if name in {"INTG", "INTEG"}:
                if len(args) != 1:
                    raise ValueError("INTG() takes one argument.")
                y = np.asarray(args[0], dtype=np.float64)
                out = np.zeros_like(y, dtype=np.float64)
                if self._formula_t_s is None or len(self._formula_t_s) != len(y) or len(y) <= 1:
                    return out
                dt = np.diff(self._formula_t_s)
                out[1:] = np.cumsum(0.5 * (y[1:] + y[:-1]) * dt)
                return out
            if name in {"DERIV", "DDX"}:
                if len(args) != 1:
                    raise ValueError("DERIV() takes one argument.")
                y = np.asarray(args[0], dtype=np.float64)
                if self._formula_t_s is None or len(self._formula_t_s) != len(y) or len(y) <= 1:
                    return np.zeros_like(y, dtype=np.float64)
                return np.gradient(y, self._formula_t_s)
            funcs = {
                "ABS": np.abs,
                "SQRT": np.sqrt,
                "LOG": np.log10,
                "LN": np.log,
                "EXP": np.exp,
                "SIN": np.sin,
                "COS": np.cos,
                "TAN": np.tan,
                "CEIL": np.ceil,
                "FLOOR": np.floor,
                "INV": lambda x: 1.0 / x,
                "MIN": np.minimum if len(args) == 2 else np.nanmin,
                "MAX": np.maximum if len(args) == 2 else np.nanmax,
                "AND": lambda a, b: self._logic_float(np.logical_and(self._logic_array(a), self._logic_array(b))),
                "OR": lambda a, b: self._logic_float(np.logical_or(self._logic_array(a), self._logic_array(b))),
                "XOR": lambda a, b: self._logic_float(np.logical_xor(self._logic_array(a), self._logic_array(b))),
                "NAND": lambda a, b: self._logic_float(~np.logical_and(self._logic_array(a), self._logic_array(b))),
                "NOR": lambda a, b: self._logic_float(~np.logical_or(self._logic_array(a), self._logic_array(b))),
                "EQV": lambda a, b: self._logic_float(~np.logical_xor(self._logic_array(a), self._logic_array(b))),
            }
            if name not in funcs:
                raise ValueError(f"Unsupported function: {name}")
            return funcs[name](*args)
        raise ValueError("Unsupported formula syntax.")

    def _evaluate_math_formula(self, key: str, expr: str) -> np.ndarray:
        expr = self._normalize_formula(expr)
        if not expr:
            raise ValueError("Formula is empty.")
        parsed = ast.parse(expr, mode="eval")
        value = self._eval_formula_ast(parsed, self._formula_eval_context(key))
        arr = np.asarray(value, dtype=np.float64)
        if arr.ndim == 0:
            if self._formula_t_s is None:
                raise ValueError("No waveform time base is loaded.")
            arr = np.full(len(self._formula_t_s), float(arr), dtype=np.float64)
        if self._formula_t_s is None or len(arr) != len(self._formula_t_s):
            raise ValueError("Formula result length does not match the waveform.")
        return arr

    def _loss_fit_raw_for_channel(self, key: str, raw: np.ndarray) -> np.ndarray:
        if self._unit_for_channel(key) != "J":
            return raw
        return _loss_window_raw(
            raw,
            self._loss_fit_segments,
            include_turn_on=self._loss_fit_include_turn_on,
        )

    def _is_computed_loss_math_channel(self, key: str) -> bool:
        key = key.upper()
        return (
            _is_math_trace_key(key)
            and key in self._computed_math_channels
            and self._unit_for_channel(key) == "J"
        )

    def _auto_scale_raw_for_channel(self, key: str, raw: np.ndarray) -> np.ndarray:
        if _is_math_trace_key(key) and self._unit_for_channel(key) == "J":
            if self._is_computed_loss_math_channel(key):
                return raw
            return self._loss_fit_raw_for_channel(key, raw)
        return raw

    def _fit_raw_for_channel(self, key: str, raw: np.ndarray) -> np.ndarray:
        return self._auto_scale_raw_for_channel(key, raw)

    def _add_trace_item(
        self, key: str, raw: np.ndarray, legend: str, color: str, width: float
    ) -> None:
        if self._trace_t_us is None:
            return
        raw = np.asarray(raw, dtype=np.float64)
        self._trace_raw[key] = raw
        effective_raw = self._effective_raw_for_channel(key)
        if effective_raw is None:
            effective_raw = raw
        fit_raw = self._fit_raw_for_channel(key, effective_raw)
        if key in self._manual_vdiv:
            scale = float(self._manual_vdiv[key])
        else:
            scale = self._auto_vdiv_for_trace(
                key,
                fit_raw,
                expr=self._math_formulas.get(key),
            )
        self._disp_scale[key] = scale
        self._disp_offset[key] = _auto_center_offset_div(fit_raw, scale)
        win = self._current_x_window_for_display()
        if win is None:
            win = (float(self._trace_t_us[0]), float(self._trace_t_us[-1]))
        tx, raw_disp = _display_curve_data(self._trace_t_us, effective_raw, win[0], win[1])
        item = self.plot.plot(
            tx,
            raw_disp / scale + self._disp_offset[key],
            pen=pg.mkPen(color, width=width),
        )
        item.setClipToView(True)
        item.setZValue(0)
        self._trace_items[key] = item
        self._trace_style[key] = (color, width)
        self._trace_legend[key] = legend
        if len(raw):
            self._trace_yrange[key] = (float(np.nanmin(raw)), float(np.nanmax(raw)))
        else:
            self._trace_yrange[key] = (0.0, 0.0)
        self._refresh_overview_traces()

    def _set_math_formula(self, key: str, expr: str) -> None:
        key = key.upper()
        expr = self._normalize_formula(expr)
        if self._formula_t_s is None:
            raise ValueError("No waveform time base is loaded.")
        previous_unit = self._lookup_channel_unit(self._trace_units, key)
        raw = np.asarray(self._evaluate_math_formula(key, expr), dtype=np.float64)
        self._math_formulas[key] = expr
        self._math_source_keys.add(key)
        self._formula_sources[key] = raw
        self._trace_units[key] = self._formula_unit(expr) or previous_unit
        if key not in self._trace_items:
            color, width = _source_trace_style(key)
            self._add_trace_item(key, raw, key, color, width)
            self._build_channel_bar()
            return
        self._trace_raw[key] = raw
        self._trace_yrange[key] = (float(np.nanmin(raw)), float(np.nanmax(raw))) if len(raw) else (0.0, 0.0)
        fit_raw = self._fit_raw_for_channel(key, raw)
        if key in self._manual_vdiv:
            scale = float(self._manual_vdiv[key])
        else:
            scale = self._auto_vdiv_for_trace(key, fit_raw, expr=expr)
        self._disp_scale[key] = scale
        self._disp_offset[key] = _auto_center_offset_div(fit_raw, scale)
        self._refresh_visible_traces(force=True)
        self._refresh_overview_traces()
        self._refresh_legend_styles()
        self._update_zero_handle_positions()
        self._update_y_ticks()

    def export_user_math_channels(
        self,
    ) -> dict[str, tuple[np.ndarray, str, float | None, float | None]]:
        """Return GUI-edited Math traces so extraction can use the same sources."""
        exported: dict[str, tuple[np.ndarray, str, float | None, float | None]] = {}
        for key in sorted(self._math_source_keys, key=_source_channel_sort_key):
            expr = self._math_formulas.get(key)
            raw = self._trace_raw.get(key)
            if not expr or raw is None:
                continue
            scale = self._disp_scale.get(key)
            offset = self._disp_offset.get(key)
            exported[key] = (
                np.asarray(raw, dtype=np.float64).copy(),
                expr,
                float(scale) if scale is not None and np.isfinite(scale) else None,
                float(offset) if offset is not None and np.isfinite(offset) else None,
            )
        return exported

    def _next_math_key(self) -> str:
        used = {
            int(m.group(1))
            for name in list(self._trace_items) + list(self._math_formulas)
            if (m := re.fullmatch(r"MATH(\d+)", name.upper()))
        }
        n = 1
        while n in used:
            n += 1
        return f"MATH{n}"

    def _add_math_channel(self) -> None:
        if self._trace_t_us is None:
            return
        key = self._next_math_key()
        self._set_math_formula(key, "CH1")
        self._show_math_formula_editor(key)

    def _show_math_formula_editor(self, key: str) -> None:
        dlg = MathFormulaDialog(self, key, parent=self)
        dlg.exec()

    # ------------------------------------------------------------------ 主入口 ----
    def plot_waveforms(
        self,
        bundle: WaveformBundle,
        profile: BridgeProfile,
        result: ExtractResult | None = None,
    ) -> None:
        source = bundle.meta.source_path
        is_new_source = source != self._loaded_source_path
        computed_math_channels = {
            str(ch or "").upper() for ch in bundle.meta.computed_math_channels
        }
        imported_math_formulas = {
            ch.upper(): self._normalize_formula(expr)
            for ch, expr in bundle.meta.channel_math_formulas.items()
        }
        if is_new_source:
            self._loaded_source_path = source
            self.reset_interaction_state()
            saved_offset: dict[str, float] = {}
            saved_units: dict[str, str] = {}
            self._math_formulas.clear()
            self._math_source_keys.clear()
            self._manual_vdiv.clear()
            for ch, scale in bundle.meta.channel_vdiv.items():
                ch_key = ch.upper()
                try:
                    scope_scale = float(scale)
                except (TypeError, ValueError):
                    continue
                if (
                    _is_source_channel_key(ch_key)
                    and np.isfinite(scope_scale)
                    and scope_scale > 0
                ):
                    self._manual_vdiv[ch_key] = scope_scale
        else:
            saved_offset = dict(self._disp_offset) if self._trace_items else {}
            saved_units = dict(self._trace_units) if self._trace_items else {}
        source_inversions: set[str] = set()
        for ch in bundle.meta.source_channel_inversions:
            base = channel_reference_base_name(ch) or normalize_channel_reference(ch)
            if base:
                source_inversions.add(f"-{base}")
        self._source_inverted_channels = source_inversions
        active_inversions: set[str] = set()
        for ch in bundle.meta.channel_display_inversions:
            base = channel_reference_base_name(ch) or normalize_channel_reference(ch)
            if base:
                active_inversions.add(f"-{base}")
        self._manual_inverted_channels = active_inversions
        scope_y_position: dict[str, float] = {}
        for ch, pos in bundle.meta.channel_y_position.items():
            ch_key = str(ch or "").upper()
            try:
                scope_pos = float(pos)
            except (TypeError, ValueError):
                continue
            if _is_source_channel_key(ch_key) and np.isfinite(scope_pos):
                scope_y_position[ch_key] = scope_pos
        self._soft_clear()
        self._disp_offset.clear()
        self._user_x_us_per_div = None
        t = bundle.t
        zero_trace = np.zeros_like(np.asarray(t, dtype=np.float64), dtype=np.float64)

        def effective_bundle_channel(col: str) -> np.ndarray | None:
            ref = normalize_channel_reference(col)
            sign, base = split_channel_reference(ref)
            if not base:
                return None
            channel = bundle.channels.get(base)
            if channel is None:
                return None
            arr = np.asarray(channel, dtype=np.float64)
            if sign < 0:
                return -arr
            if self._display_transform_inverted(base or ref):
                return -arr
            return arr

        def safe_channel(col: str) -> np.ndarray:
            channel = effective_bundle_channel(col)
            if channel is not None:
                return channel
            return zero_trace

        def safe_total_current() -> np.ndarray:
            direct = effective_bundle_channel(profile.ic)
            if direct is not None:
                return direct
            if profile.ic_from_sum_irr_il:
                irr_source = effective_bundle_channel(profile.irr)
                il_source = effective_bundle_channel(profile.il)
                if irr_source is not None and il_source is not None:
                    return irr_source + il_source
            return zero_trace

        def safe_reverse_recovery_current() -> np.ndarray:
            direct = effective_bundle_channel(profile.irr)
            if direct is not None:
                return direct
            if profile.irr_from_ic_minus_il:
                il_source = effective_bundle_channel(profile.il)
                if il_source is not None:
                    ic_source = safe_total_current()
                    return ic_source - il_source
            return zero_trace

        vge = safe_channel(profile.vge)
        vce = safe_channel(profile.vce)
        ic = safe_total_current()
        irr = safe_reverse_recovery_current()
        v_diode = safe_channel(profile.v_diode)
        vge_other = safe_channel(profile.vge_other)
        self._interactive_vce_t_us = t * 1e6
        self._interactive_vce = vce
        self._interactive_irr_t_us = t * 1e6
        self._interactive_irr = irr
        self._interactive_ic_t_us = t * 1e6
        self._interactive_ic = ic
        self._interactive_dt = float(bundle.dt)

        source_item_map: dict[str, np.ndarray] = {
            normalize_channel_reference(ch): np.asarray(raw, dtype=np.float64)
            for ch, raw in bundle.channels.items()
            if _is_source_channel_key(ch)
        }
        source_items = list(source_item_map.items())
        source_items.sort(key=lambda item: _source_channel_sort_key(item[0]))
        t_us = np.asarray(t, dtype=np.float64) * 1e6
        self._trace_items.clear()
        self._trace_style.clear()
        self._trace_yrange.clear()
        self._trace_legend.clear()
        self._trace_units.clear()
        self._disp_scale.clear()
        self._trace_raw.clear()
        self._channel_labels = {
            ch.upper(): str(label).strip()
            for ch, label in bundle.meta.channel_labels.items()
            if _is_source_channel_key(ch) and str(label).strip()
        }
        self._formula_sources.clear()
        self._formula_t_s = np.asarray(t, dtype=np.float64)
        self._trace_t_us = t_us
        self._trace_view_signature = None
        self._computed_math_channels = set(computed_math_channels)
        self._loss_fit_segments = result.segments if result is not None else None
        self._loss_fit_include_turn_on = not (
            bool(result.single_pulse_mode) if result is not None else False
        )
        scope_scale = bundle.meta.horizontal_scale_per_div
        self._scope_x_us_per_div = (
            float(scope_scale) * 1e6
            if scope_scale is not None
            and np.isfinite(float(scope_scale))
            and float(scope_scale) > 0
            else None
        )
        self._logical_display_keys = self._logical_display_key_map(profile)
        self._base_logical_display_keys = dict(self._logical_display_keys)
        self._prefer_math_display_keys_for_derived_currents(
            profile, imported_math_formulas
        )
        self._display_channel_roles = self._build_display_channel_roles(
            profile, self._logical_display_keys
        )
        file_units = self._metadata_channel_units(bundle.meta.channel_units)
        override_units = self._metadata_channel_units(bundle.meta.channel_unit_overrides)
        self._source_file_units = dict(file_units)
        self._unit_overrides = dict(override_units)
        role_units = self._physical_channel_units(profile)
        self._role_units = dict(role_units)
        for key, data in source_items:
            color, width = _source_trace_style(key)
            legend = _source_channel_legend(key, self._channel_labels)
            raw = np.asarray(data, dtype=np.float64)
            self._trace_raw[key] = raw
            expr = imported_math_formulas.get(key)
            self._trace_units[key] = self._source_trace_unit(
                key,
                expr,
                file_units,
                override_units,
                role_units,
                saved_units,
            )
            fit_raw = self._fit_raw_for_channel(key, raw)
            if key in self._manual_vdiv:
                scale = float(self._manual_vdiv[key])
            else:
                scope_scale = bundle.meta.channel_vdiv.get(
                    key,
                    bundle.meta.channel_vdiv.get(channel_reference_base_name(key)),
                )
                scale = _safe_initial_vdiv_for_channel(
                    key,
                    fit_raw,
                    scope_scale,
                    self._unit_for_channel(key),
                    reverse_recovery_power=self._is_reverse_recovery_power_formula(expr),
                )
            self._disp_scale[key] = scale
            if key in saved_offset:
                offset = float(saved_offset[key])
            elif key in scope_y_position:
                offset = float(scope_y_position[key])
            elif channel_reference_base_name(key) in scope_y_position:
                offset = float(scope_y_position[channel_reference_base_name(key)])
            else:
                offset = _auto_center_offset_div(fit_raw, scale)
            self._disp_offset[key] = _clamp_offset_div(offset)
            effective_raw = self._effective_raw_for_channel(key)
            if effective_raw is None:
                effective_raw = raw
            tx, raw_disp = _display_curve_data(
                t_us, effective_raw, float(t_us[0]), float(t_us[-1])
            )
            item = self.plot.plot(
                tx,
                raw_disp / scale + self._disp_offset[key],
                pen=pg.mkPen(color, width=width),
            )
            item.setClipToView(True)
            item.setZValue(0)
            self._trace_items[key] = item
            self._trace_style[key] = (color, width)
            self._trace_legend[key] = legend
            if expr:
                self._math_formulas[key] = expr
            if len(data):
                self._trace_yrange[key] = (
                    float(np.nanmin(data)),
                    float(np.nanmax(data)),
                )
        # 重建底部通道盒（含每通道 V/div）
        self._raised_key = None
        self._highlighted_key = None
        for key in list(self._trace_items):
            self._trace_units.setdefault(
                key,
                self._source_trace_unit(
                    key,
                    None,
                    file_units,
                    override_units,
                    role_units,
                    saved_units,
                ),
            )

        for ch, raw_full in bundle.channels.items():
            ch_key = ch.upper()
            if not _is_source_channel_key(ch_key):
                continue
            self._formula_sources[ch_key] = np.asarray(raw_full, dtype=np.float64)

        for ch_key, expr in list(self._math_formulas.items()):
            if ch_key in bundle.channels and ch_key not in self._math_source_keys:
                continue
            try:
                self._set_math_formula(ch_key, expr)
            except Exception:
                self._math_formulas.pop(ch_key, None)

        self._hidden_channels.clear()
        self._active_channel = self._display_key_for_channel("ic")
        self._build_channel_bar()

        # ---- 默认 X：铺满双脉冲全景（用原始 t 而非降采样后的 t_us，避免精度损失）----
        full_min = float(t[0] * 1e6)
        full_max = float(t[-1] * 1e6)
        full_span = full_max - full_min
        self._full_x_range = (full_min, full_max)

        vb = self.plot.getPlotItem().getViewBox()
        # 缩小不能超出全部双脉冲波形窗口；放大允许至 MIN_X_SPAN_US
        vb.setLimits(
            xMin=full_min,
            xMax=full_max,
            minXRange=MIN_X_SPAN_US,
            maxXRange=full_span,
        )
        self._last_x_window = (full_min, full_max)
        self._refresh_overview_traces()
        vb.setXRange(full_min, full_max, padding=0.0)
        self._refresh_visible_traces(force=True)
        # 纵向固定为 ±DISP_HALF_DIV 格（每通道按自身 V/div 缩放）
        self._apply_disp_yrange()
        self._update_x_ticks()

        # ---- 持久 4 根光标 ----
        if result and result.segments:
            if result.short_circuit_mode:
                sc = result.short_circuit
                a_us = (
                    float(sc.tsc_start_us)
                    if sc.tsc_start_us is not None
                    else float(t[result.segments.turn_off[0]] * 1e6)
                )
                b_us = (
                    float(sc.tsc_end_us)
                    if sc.tsc_end_us is not None
                    else float(t[result.segments.turn_off[1]] * 1e6)
                )
            else:
                a_us = float(t[result.segments.pulse1_off] * 1e6)
                b_us = float(t[result.segments.pulse2_on] * 1e6)
        else:
            a_us = full_min + 0.30 * full_span
            b_us = full_min + 0.70 * full_span
        peak_ic = float(np.max(np.abs(ic))) if len(ic) else 1.0
        self._install_persistent_cursors(a_us, b_us, peak_ic)
        self._update_zero_handle_positions()
        self._schedule_post_layout_sync()

    # ------------------------------------------------------------------ 底部通道盒/高亮 ----
    def _build_channel_bar(self) -> None:
        while self._channel_layout.count():
            it = self._channel_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        self._channel_boxes.clear()
        for key in self._trace_items:
            color, _ = self._trace_style[key]
            legend = self._trace_legend[key]
            box = ChannelBox(key, legend, color)
            box.raiseClicked.connect(self._on_legend_clicked)
            box.highlightDoubleClicked.connect(self._on_legend_double_clicked)
            box.verticalSettingsRequested.connect(self._show_channel_settings_panel)
            self._channel_boxes[key] = box
            self._channel_layout.addWidget(box)
        add_math = QPushButton("+ Math")
        add_math.setToolTip("Add a custom math waveform")
        add_math.setFixedSize(82, 42)
        add_math.setStyleSheet(
            "QPushButton{background:#2b2d3f;color:#cdd6f4;"
            "border:1px dashed #6c7086;border-radius:4px;padding:0;}"
            "QPushButton:hover{background:#373a52;border-color:#89b4fa;}"
        )
        add_math.clicked.connect(self._add_math_channel)
        self._channel_layout.addWidget(add_math)
        self._channel_layout.addStretch(1)
        self._refresh_legend_styles()
        self._rebuild_zero_handles()
        self._sync_channel_bar_width()
        # 首次显示前 viewport 宽度常为 0，延迟再同步一次以免通道条高度为 0
        QTimer.singleShot(0, self._sync_channel_bar_width)
        self._schedule_post_layout_sync()

    def _zero_handle_label(self, key: str, legend: str) -> str:
        text = legend.strip().lstrip("-━— ").strip()
        return text[:10] if text else key

    @staticmethod
    def _zero_handle_display_label(key: str) -> str:
        key = normalize_channel_reference(key)
        sign = "-" if key.startswith("-") else ""
        base = channel_reference_base_name(key)
        if m := re.fullmatch(r"CH(\d+)", base):
            return f"{sign}C{m.group(1)}"
        if m := re.fullmatch(r"MATH(\d+)", base):
            return f"{sign}M{m.group(1)}"
        return key[:4] if sign else key[:3]

    def _zero_handle_tooltip(self, key: str, legend: str) -> str:
        text = self._zero_handle_label(key, legend)
        unit = self._unit_for_channel(key)
        off = self._disp_offset.get(key, 0.0)
        return (
            '<div style="white-space:nowrap;">'
            f"<b>{key.upper()} · {text}</b><br>"
            f"0{unit} 基准线：{off:+.2f} div<br>"
            "拖动箭头：调整垂直位置"
            "</div>"
        )

    def _vdiv_text(self, key: str) -> str:
        scale = self._disp_scale.get(key, 1.0)
        unit = self._unit_for_channel(key)
        return _format_vdiv_text(scale, unit)

    def _refresh_legend_styles(self) -> None:
        keys = list(self._channel_boxes.keys())
        for key in keys:
            box = self._channel_boxes[key]
            color, _ = self._trace_style[key]
            legend = self._trace_legend[key]
            vdiv = self._vdiv_text(key)
            hidden = key in self._hidden_channels
            highlighted = (not hidden) and key == self._highlighted_key
            dim = (
                hidden
                or (self._highlighted_key is not None and not highlighted)
            )
            qcolor = QColor(color)
            title_fg = "#111111" if qcolor.lightness() > 145 else "#f7f7f7"
            if hidden:
                title_bg = "#3a3d4d"
                title_fg = "#b8bece"
                scale_fg = "#a9afbf"
                border = "#2d3040"
                body_bg = "#10111a"
                mark = " 关闭"
            else:
                title_bg = color if not dim else "#3b3f4f"
                scale_fg = "#f0f0f0" if highlighted else ("#b7bdcc" if dim else "#d9deea")
                border = "#f5f5f5" if highlighted else color
                body_bg = "#202230" if highlighted else "#151722"
                mark = " ◀" if highlighted else ""
            box.set_texts(
                f"<span style='font-weight:700;font-size:12px'>"
                f"{legend}{mark}</span>",
                f"<span style='font-size:12px'>{vdiv}</span>",
            )
            box.set_box_style(
                "QFrame{"
                f"border:1px solid {border};"
                "border-radius:4px;"
                f"background:{body_bg};"
                "}"
                "QLabel#channelTitle{"
                f"background:{title_bg};"
                f"color:{title_fg};"
                "border:0;"
                "border-top-left-radius:3px;"
                "border-top-right-radius:3px;"
                "padding:0 6px;"
                "}"
                "QLabel#channelScale{"
                "background:transparent;"
                f"color:{scale_fg};"
                "border:0;"
                "padding:0 6px;"
                "font-family:Consolas,'Courier New',monospace;"
                "}"
            )

    def _can_delete_channel(self, key: str) -> bool:
        key = normalize_channel_reference(key)
        return (
            not key.startswith("-")
            and _is_math_trace_key(key)
            and key in self._trace_items
        )

    def set_channel_label(self, key: str, label: str) -> None:
        key = key.upper()
        if key not in self._trace_items:
            return
        label = label.strip()
        if not label:
            self._channel_labels.pop(key, None)
        else:
            self._channel_labels[key] = label
        self._trace_legend[key] = _source_channel_legend(key, self._channel_labels)
        self._refresh_legend_styles()
        self._update_zero_handle_positions()
        self._sync_channel_bar_width()
        self.channelLabelChanged.emit(key, label)

    def set_channel_unit_override(self, key: str, unit: str) -> None:
        ref = normalize_channel_reference(key)
        base = channel_reference_base_name(ref)
        if not base:
            return
        text = str(unit or "").strip()
        if text:
            self._unit_overrides[base] = text
            self._unit_overrides[ref] = text
        else:
            for candidate in (base, ref, f"-{base}"):
                self._unit_overrides.pop(candidate, None)
        resolved = (
            text
            or self._lookup_channel_unit(self._source_file_units, base)
            or self._lookup_channel_unit(self._role_units, base)
            or self._lookup_channel_unit(CHANNEL_UNITS, base)
        )
        for candidate in (base, ref, f"-{base}"):
            if candidate in self._trace_items or candidate in self._trace_units:
                if resolved:
                    self._trace_units[candidate] = resolved
                else:
                    self._trace_units.pop(candidate, None)
        self._refresh_legend_styles()
        self._update_y_ticks()
        self._update_readout()
        self._update_zero_handle_positions()
        self.channelUnitChanged.emit(base, text)

    def inverted_reference_for(self, key: str) -> str:
        ref = normalize_channel_reference(key)
        base = channel_reference_base_name(ref)
        return f"-{base}" if base else ""

    def channel_inversion_enabled(self, key: str) -> bool:
        ref = normalize_channel_reference(key)
        if ref.startswith("-"):
            return True
        return self._display_inversion_enabled(ref)

    def _remove_trace_item_only(self, key: str) -> None:
        item = self._trace_items.pop(key, None)
        if item is not None:
            self.plot.removeItem(item)
        self._trace_style.pop(key, None)
        self._trace_yrange.pop(key, None)
        self._trace_legend.pop(key, None)
        self._trace_units.pop(key, None)
        self._trace_raw.pop(key, None)
        self._formula_sources.pop(key, None)
        self._disp_scale.pop(key, None)
        self._disp_offset.pop(key, None)
        self._manual_vdiv.pop(key, None)
        self._hidden_channels.discard(key)

    def set_channel_inversion_enabled(self, key: str, enabled: bool) -> str:
        ref = normalize_channel_reference(key)
        base = channel_reference_base_name(ref)
        inverted = f"-{base}" if base else ""
        if not inverted:
            return ref
        changed = self._display_inversion_enabled(base) != bool(enabled)
        if enabled:
            self._manual_inverted_channels.add(inverted)
        else:
            self._manual_inverted_channels.discard(inverted)
        self._trace_view_signature = None
        self._refresh_visible_trace(base)
        self._refresh_visible_traces(force=True)
        self._refresh_overview_traces()
        self._update_readout()
        self._update_waveform_cursor_markers()
        self._update_y_ticks()
        self._update_zero_handle_positions()
        if changed:
            self.channelInversionChanged.emit(base, bool(enabled))
        return base

    def _delete_math_channel(self, key: str) -> None:
        key = key.upper()
        if key not in self._trace_items or not self._can_delete_channel(key):
            return
        if self._raised_key == key:
            self._raised_key = None
        if self._highlighted_key == key:
            self._clear_highlight()

        panel = self._channel_settings_panel
        if panel is not None and getattr(panel, "_key", None) == key:
            panel.close()
            self._channel_settings_panel = None

        item = self._trace_items.pop(key)
        self.plot.removeItem(item)
        self._trace_style.pop(key, None)
        self._trace_yrange.pop(key, None)
        self._trace_legend.pop(key, None)
        self._trace_units.pop(key, None)
        self._trace_raw.pop(key, None)
        self._formula_sources.pop(key, None)
        self._math_formulas.pop(key, None)
        self._math_source_keys.discard(key)
        self._computed_math_channels.discard(key)
        self._disp_scale.pop(key, None)
        self._disp_offset.pop(key, None)
        self._manual_vdiv.pop(key, None)
        self._hidden_channels.discard(key)

        for logical, display_key in list(self._logical_display_keys.items()):
            if display_key.upper() == key:
                fallback = self._base_logical_display_keys.get(logical, "")
                if fallback and fallback.upper() != key and fallback in self._trace_items:
                    self._logical_display_keys[logical] = fallback
                else:
                    self._logical_display_keys.pop(logical, None)
        self._display_channel_roles = {
            channel: [role for role in roles if channel.upper() != key]
            for channel, roles in self._display_channel_roles.items()
            if channel.upper() != key
        }
        if self._active_channel.upper() == key:
            self._active_channel = self._axis_channel() or "ic"

        self._refresh_overview_traces()
        self._build_channel_bar()
        self._update_y_ticks()
        self._update_readout()

    def _toggle_channel_visibility(self, key: str) -> None:
        if key not in self._trace_items:
            return
        if key in self._hidden_channels:
            self._hidden_channels.discard(key)
            self._trace_items[key].setVisible(True)
        else:
            self._hidden_channels.add(key)
            self._trace_items[key].setVisible(False)
            if self._raised_key == key:
                self._raised_key = None
            if self._highlighted_key == key:
                self._clear_highlight()
        self._apply_trace_selection_style()
        self._refresh_legend_styles()
        self._refresh_zero_handle_styles()
        self._refresh_overview_traces()
        self._update_y_ticks()

    # ------------------------------------------------------------------ 每通道垂直位置 ----
    def _auto_center_channel(self, key: str) -> None:
        """按当前刻度将通道波形中点对齐 0 格。"""
        raw = self._effective_raw_for_channel(key)
        scale = self._disp_scale.get(key, 1.0)
        if raw is None:
            return
        self._set_channel_offset(
            key,
            _auto_center_offset_div(self._fit_raw_for_channel(key, raw), scale),
        )

    def _set_channel_offset(
        self, key: str, offset: float, *, lightweight: bool = False, **_kwargs
    ) -> None:
        if key not in self._trace_items or self._trace_t_us is None:
            return
        offset = _clamp_offset_div(offset)
        self._disp_offset[key] = offset
        if lightweight:
            self._refresh_visible_trace(key)
            self._update_zero_handle_position(key)
            return
        self._refresh_visible_traces(force=True)
        self._refresh_overview_traces()
        self._refresh_legend_styles()
        self._update_y_ticks()
        self._update_zero_handle_positions()
        self._update_readout()

    def _on_zero_handle_dragged(self, key: str, view_y: float) -> None:
        if self._highlighted_key != key:
            self._highlight_trace(key)
        self._set_channel_offset(key, float(view_y), lightweight=True)

    def _on_zero_handle_drag_finished(self, key: str) -> None:
        if key not in self._trace_items:
            return
        self._refresh_overview_trace(key)
        self._update_y_ticks()
        self._update_zero_handle_positions()
        self._update_readout()

    def _plot_scene(self):
        return self.plot.scene()

    def _remove_zero_handles(self) -> None:
        scene = self._plot_scene()
        for handle in self._zero_handles.values():
            scene.removeItem(handle)
        self._zero_handles.clear()

    def _rebuild_zero_handles(self) -> None:
        self._remove_zero_handles()
        vb = self.plot.getPlotItem().getViewBox()
        scene = self._plot_scene()
        for key in self._trace_items:
            color, _ = self._trace_style[key]
            legend = self._trace_legend[key]
            label = self._zero_handle_display_label(key)
            handle = ChannelZeroHandle(key, label, color, vb)
            handle.setToolTip(self._zero_handle_tooltip(key, legend))
            handle.clicked.connect(self._on_legend_clicked)
            handle.dragged.connect(self._on_zero_handle_dragged)
            handle.dragFinished.connect(self._on_zero_handle_drag_finished)
            scene.addItem(handle)
            self._zero_handles[key] = handle
        self._refresh_zero_handle_styles()
        self._update_zero_handle_positions()

    def _zero_handle_scene_pos(self, vb: pg.ViewBox, y_div: float) -> QPointF:
        """图元原点在箭尾平边，与 Y 轴（波形区左界）对齐，箭身向右展开。"""
        xr, _yr = vb.viewRange()
        axis_scene = vb.mapViewToScene(QPointF(float(xr[0]), y_div))
        return QPointF(axis_scene.x(), axis_scene.y())

    def _zero_handle_display_y(self, key: str) -> float:
        return float(self._to_disp(key, 0.0))

    def _update_zero_handle_position(self, key: str) -> None:
        handle = self._zero_handles.get(key)
        if handle is None:
            return
        hidden = key in self._hidden_channels
        handle.setVisible(not hidden)
        if hidden:
            return
        vb = self.plot.getPlotItem().getViewBox()
        y = float(self._zero_handle_display_y(key))
        pos = self._zero_handle_scene_pos(vb, y)
        handle.setPos(pos.x(), pos.y())
        legend = self._trace_legend.get(key, key)
        handle.setToolTip(self._zero_handle_tooltip(key, legend))

    def _update_zero_handle_positions(self) -> None:
        if not self._zero_handles:
            return
        for key in self._zero_handles:
            self._update_zero_handle_position(key)

    def _refresh_zero_handle_styles(self) -> None:
        for key, handle in self._zero_handles.items():
            highlighted = (
                key not in self._hidden_channels and key == self._highlighted_key
            )
            raised = key not in self._hidden_channels and key == self._raised_key
            dimmed = (
                key not in self._hidden_channels
                and self._highlighted_key is not None
                and not highlighted
            )
            handle.set_highlighted(highlighted)
            handle.set_dimmed(dimmed)
            handle.setZValue(120 if (highlighted or raised) else 100)

    def _on_legend_clicked(self, key: str) -> None:
        if key not in self._trace_items or key in self._hidden_channels:
            return
        self._raise_trace(key)

    def _on_legend_double_clicked(self, key: str) -> None:
        if key not in self._trace_items or key in self._hidden_channels:
            return
        if self._highlighted_key == key:
            self._clear_highlight()
        else:
            self._highlight_trace(key)

    # ------------------------------------------------------------------ 每通道 V/div ----
    def _vdiv_options(self, key: str) -> list[float]:
        cap = _vdiv_max_for_channel(key)
        return [float(v) for v in _vdiv_ladder_for_channel(key) if float(v) <= cap]

    def _position_menu_line(self, key: str) -> str:
        offset = self._disp_offset.get(key, 0.0)
        if abs(offset) > 1e-6:
            return f"垂直位置：{offset:+.2f} 格"
        return "垂直位置：0 格"

    def _show_channel_settings_panel(self, key: str) -> None:
        from dpt_extractor.gui.channel_settings_panel import ChannelSettingsPanel

        if key not in self._trace_items:
            return
        panel = self._channel_settings_panel
        if panel is not None and panel.isVisible():
            panel.close()
        box = self._channel_boxes.get(key)
        if box is not None:
            anchor = box.mapToGlobal(QPoint(0, 0))
        else:
            anchor = self.mapToGlobal(self.rect().center())
        panel = ChannelSettingsPanel(self, key, anchor, parent=self)
        self._channel_settings_panel = panel
        panel.show()

    def _set_channel_scale(self, key: str, value: float | None) -> None:
        """设置某通道 V/div；value=None 表示恢复自动。"""
        if key not in self._trace_items or self._trace_t_us is None:
            return
        raw = self._effective_raw_for_channel(key)
        if raw is None:
            return
        fit_raw = self._fit_raw_for_channel(key, raw)
        if value is None:
            self._manual_vdiv.pop(key, None)
            scale = self._auto_vdiv_for_trace(
                key,
                fit_raw,
                expr=self._math_formulas.get(key),
            )
        else:
            scale = max(float(value), 1e-15)
            self._manual_vdiv[key] = scale
        self._disp_scale[key] = scale
        self._auto_center_channel(key)

    def _dim_color(self, color: str, alpha: int = 70) -> QColor:
        c = QColor(color)
        c.setAlpha(alpha)
        return c

    def _active_channel_can_follow_selection(self) -> bool:
        if self._interactive_mode in self._BASE_TOP_SLOPE_MODES:
            return False
        return self._interactive_mode != "turn_on_current"

    def _apply_trace_selection_style(self) -> None:
        for k, item in self._trace_items.items():
            color, width = self._trace_style[k]
            if self._highlighted_key == k:
                item.setPen(pg.mkPen(color, width=width + 1.8))
            elif self._highlighted_key is not None:
                item.setPen(pg.mkPen(self._dim_color(color, 60), width=width))
            else:
                item.setPen(pg.mkPen(color, width=width))
            item.setZValue(20 if self._raised_key == k else 0)

    def _raise_trace(self, key: str) -> None:
        """单击选中通道只置顶波形，不做加粗/变暗高亮。"""
        self._raised_key = key
        self._highlighted_key = None
        if self._active_channel_can_follow_selection():
            self._active_channel = key
        self._apply_trace_selection_style()
        self._refresh_legend_styles()
        self._refresh_zero_handle_styles()
        self._update_y_ticks()
        self._update_readout()

    def _highlight_trace(self, key: str) -> None:
        """仅高亮：选中波形置顶+加粗变亮，其余变暗。不改变纵轴量程。"""
        self._raised_key = key
        self._highlighted_key = key
        if self._active_channel_can_follow_selection():
            self._active_channel = key
        self._apply_trace_selection_style()
        self._refresh_legend_styles()
        self._refresh_zero_handle_styles()
        self._update_y_ticks()
        self._update_readout()

    def focus_power_peak_in_window(
        self,
        t0_us: float,
        t1_us: float,
        *,
        target_w: float | None = None,
        prefer_abs: bool = False,
    ) -> tuple[str, float] | None:
        """Focus a visible W trace and mark its peak within the requested window."""
        peak = self.power_peak_in_window(
            t0_us,
            t1_us,
            target_w=target_w,
            prefer_abs=prefer_abs,
        )
        if peak is None:
            return None
        key, peak_w, peak_value, peak_t_us = peak
        lo_us, hi_us = sorted((float(t0_us), float(t1_us)))
        pad = max(0.04, (hi_us - lo_us) * 0.2)
        self.focus_interval_us(lo_us - pad, hi_us + pad)
        self.set_cursor_auxiliary_point(
            key,
            peak_t_us,
            peak_value,
            show_vertical_guide=True,
            x_range_us=(lo_us, hi_us),
        )
        return key, peak_w

    def power_peak_in_window(
        self,
        t0_us: float,
        t1_us: float,
        *,
        target_w: float | None = None,
        prefer_abs: bool = False,
    ) -> tuple[str, float, float, float] | None:
        """Return (channel, peak W, display trace value, t_us) for a visible power trace."""
        if self._trace_t_us is None or len(self._trace_t_us) == 0:
            return None
        lo_us, hi_us = sorted((float(t0_us), float(t1_us)))
        if not np.isfinite(lo_us) or not np.isfinite(hi_us) or hi_us <= lo_us:
            return None
        mask = (self._trace_t_us >= lo_us) & (self._trace_t_us <= hi_us)
        if not np.any(mask):
            return None
        candidates: list[tuple[float, str, float, int]] = []
        for key in self._trace_items:
            unit = self._unit_for_channel(key)
            if key in self._hidden_channels or not _is_power_unit(unit):
                continue
            to_w = _power_unit_to_w_factor(unit)
            raw = self._effective_raw_for_channel(key)
            if raw is None:
                continue
            raw_arr = np.asarray(raw, dtype=np.float64)
            if raw_arr.size != self._trace_t_us.size:
                continue
            seg = raw_arr[mask]
            if seg.size == 0:
                continue
            finite = np.isfinite(seg)
            if not np.any(finite):
                continue
            local_indices = np.nonzero(mask)[0][finite]
            finite_seg = seg[finite]
            idx_max_local = int(np.nanargmax(finite_seg))
            peak_value = float(finite_seg[idx_max_local])
            peak_idx = int(local_indices[idx_max_local])
            if prefer_abs:
                idx_abs_local = int(np.nanargmax(np.abs(finite_seg)))
                abs_value = float(finite_seg[idx_abs_local])
                abs_idx = int(local_indices[idx_abs_local])
                abs_value_w = abs_value * to_w
                peak_value_w = peak_value * to_w
                if target_w is None or abs(abs(abs_value_w) - float(target_w)) <= abs(peak_value_w - float(target_w)):
                    peak_value = abs_value
                    peak_idx = abs_idx
            peak_value_w = peak_value * to_w
            if target_w is None or not np.isfinite(float(target_w)):
                score = -abs(peak_value_w)
            else:
                score = abs(abs(peak_value_w) - float(target_w)) if prefer_abs else abs(peak_value_w - float(target_w))
            candidates.append((float(score), key, peak_value, peak_idx))
        if not candidates:
            return None
        if target_w is None or not np.isfinite(float(target_w)):
            _score, key, peak_value, peak_idx = min(candidates, key=lambda item: item[0])
        else:
            _score, key, peak_value, peak_idx = min(candidates, key=lambda item: item[0])
        peak_w = peak_value * _power_unit_to_w_factor(self._unit_for_channel(key))
        display_value = abs(peak_value) if prefer_abs else peak_value
        return (
            key,
            abs(peak_w) if prefer_abs else peak_w,
            display_value,
            float(self._trace_t_us[peak_idx]),
        )

    def _clear_highlight(self) -> None:
        self._highlighted_key = None
        self._apply_trace_selection_style()
        self._refresh_legend_styles()
        self._refresh_zero_handle_styles()
        self._update_y_ticks()
        self._update_readout()

    # ------------------------------------------------------------------ 光标安装 ----
    def _install_persistent_cursors(self, a_us: float, b_us: float, peak_ic: float) -> None:
        # 加载新数据时回到 global 模式，解除任何残留锁定
        self.clear_cursor_auxiliary_guides()
        self._interactive_mode = "global"
        self._interactive_on_change = None
        self._interactive_search_t0_us = None
        self._interactive_search_t1_us = None
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._h_cursor_a_locked = False
        full = self._full_x_range
        if full is not None:
            a_us = float(np.clip(a_us, full[0], full[1]))
            b_us = float(np.clip(b_us, full[0], full[1]))

        def _mk_vline(pos: float, color: str, label: str) -> pg.InfiniteLine:
            line = ScopeCursorLine(
                label,
                pos=pos,
                angle=90,
                movable=True,
                pen=pg.mkPen(color, width=V_CURSOR_WIDTH),
                hoverPen=pg.mkPen("#FFFFFF", width=V_CURSOR_WIDTH + 1),
                label=label,
                labelOpts={
                    "color": color,
                    "position": 0.02,
                    "movable": False,
                    "fill": (0, 0, 0, 160),
                },
            )
            label_item = getattr(line, "label", None)
            if label_item is not None:
                label_item.setFont(
                    QFont("Segoe UI", CURSOR_LINE_LABEL_FONT_PT, QFont.Weight.Bold)
                )
            line.setZValue(50)
            line.contextRequested.connect(self._show_cursor_context_menu)
            return line

        def _mk_hline(pos: float, color: str, label: str) -> pg.InfiniteLine:
            line = ScopeCursorLine(
                label,
                pos=pos,
                angle=0,
                movable=True,
                pen=pg.mkPen(color, width=H_CURSOR_WIDTH),
                hoverPen=pg.mkPen("#FFFFFF", width=H_CURSOR_WIDTH + 1),
                label=label,
                labelOpts={
                    "color": color,
                    "position": 0.98,
                    "movable": False,
                    "fill": (0, 0, 0, 160),
                },
            )
            label_item = getattr(line, "label", None)
            if label_item is not None:
                label_item.setFont(
                    QFont("Segoe UI", CURSOR_LINE_LABEL_FONT_PT, QFont.Weight.Bold)
                )
            line.setZValue(50)
            line.contextRequested.connect(self._show_cursor_context_menu)
            return line

        # 纵向 A/B
        self._interactive_syncing = True
        if self._cursor_a is None:
            self._cursor_a = _mk_vline(a_us, CURSOR_PEN_A, "A")
            self.plot.addItem(self._cursor_a)
            self._cursor_a.sigPositionChanged.connect(self._on_any_cursor_moved)
        else:
            self._cursor_a.setPos(a_us)
            self._cursor_a.setMovable(True)
            self._cursor_a.setPen(pg.mkPen(CURSOR_PEN_A, width=V_CURSOR_WIDTH))
        if self._cursor_b is None:
            self._cursor_b = _mk_vline(b_us, CURSOR_PEN_B, "B")
            self.plot.addItem(self._cursor_b)
            self._cursor_b.sigPositionChanged.connect(self._on_any_cursor_moved)
        else:
            self._cursor_b.setPos(b_us)
            self._cursor_b.setMovable(True)
            self._cursor_b.setPen(pg.mkPen(CURSOR_PEN_B, width=V_CURSOR_WIDTH))

        # 横向 Ha/Hb 默认：Ha 在上(+2 格)、Hb 在下(-2 格)（显示坐标即「格」），可拖
        ha_y = 2.0
        hb_y = -2.0
        if self._h_cursor_a is None:
            self._h_cursor_a = _mk_hline(ha_y, CURSOR_PEN_A, "Ha")
            self.plot.addItem(self._h_cursor_a)
            self._h_cursor_a.sigPositionChanged.connect(self._on_horizontal_cursor_moved)
        else:
            self._h_cursor_a.setPos(ha_y)
            self._h_cursor_a.setPen(pg.mkPen(CURSOR_PEN_A, width=H_CURSOR_WIDTH))
            if not self._h_cursor_a_locked:
                self._h_cursor_a.setMovable(True)
        if self._h_cursor_b is None:
            self._h_cursor_b = _mk_hline(hb_y, CURSOR_PEN_B, "Hb")
            self.plot.addItem(self._h_cursor_b)
            self._h_cursor_b.sigPositionChanged.connect(self._on_horizontal_cursor_moved)
        else:
            self._h_cursor_b.setPos(hb_y)
            self._h_cursor_b.setMovable(True)
            self._h_cursor_b.setPen(pg.mkPen(CURSOR_PEN_B, width=H_CURSOR_WIDTH))

        self._interactive_syncing = False
        self._update_readout()
        self._apply_cursor_visibility()

    @staticmethod
    def _freq_text_from_dt_us(dt_us: float) -> str:
        if abs(dt_us) <= 1e-9:
            return "—"
        freq_khz = 1e3 / abs(dt_us)
        if freq_khz >= 1000:
            return f"{freq_khz / 1000:.2f} MHz"
        return f"{freq_khz:.2f} kHz"

    @staticmethod
    def _scope_quantity_text(value: float, unit: str) -> str:
        """示波器读数：按通道单位自动使用 m/k/M 前缀。"""
        unit = unit or ""
        value = float(value)
        abs_v = abs(value)
        if unit in {"V", "A"}:
            if 0.0 < abs_v < 1.0:
                return f"{value * 1000.0:.3f} m{unit}"
            if abs_v >= 1000.0:
                return f"{value / 1000.0:.3f} k{unit}"
        if unit == "J":
            if 0.0 < abs_v < 1.0:
                return f"{value * 1000.0:.3f} mJ"
            if abs_v >= 1000.0:
                return f"{value / 1000.0:.3f} kJ"
        if unit == "W":
            if abs_v >= 1e6:
                return f"{value / 1e6:.3f} MW"
            if abs_v >= 1000.0:
                return f"{value / 1000.0:.3f} kW"
        suffix = f" {unit}" if unit else ""
        return f"{value:.3f}{suffix}"

    @staticmethod
    def _scope_rate_text(delta: float, dt_us: float, *, is_current: bool = False) -> str:
        """示波器 Δ/Δt：自动 V/s、kV/s、MV/s 或 A/s、kA/s、MA/s。"""
        if abs(dt_us) <= 1e-9:
            return "—"
        rate = delta / (dt_us * 1e-6)
        abs_r = abs(rate)
        if is_current:
            if abs_r >= 1e6:
                return f"{rate / 1e6:.2f} MA/s"
            if abs_r >= 1e3:
                return f"{rate / 1e3:.2f} kA/s"
            return f"{rate:.2f} A/s"
        if abs_r >= 1e9:
            return f"{rate / 1e9:.2f} GV/s"
        if abs_r >= 1e6:
            return f"{rate / 1e6:.2f} MV/s"
        if abs_r >= 1e3:
            return f"{rate / 1e3:.2f} kV/s"
        return f"{rate:.2f} V/s"

    @staticmethod
    def _scope_wave_letter(unit: str) -> str:
        if unit == "A":
            return "a"
        if unit == "J":
            return "j"
        if unit == "W":
            return "p"
        return "v" if unit == "V" else "y"

    def _cursor_source_channel(self) -> str | None:
        ch = self._readout_channel()
        if ch in self._trace_items and ch not in self._hidden_channels:
            return ch
        if (
            self._highlighted_key is not None
            and self._highlighted_key in self._trace_items
            and self._highlighted_key not in self._hidden_channels
        ):
            return self._highlighted_key
        for key in self._trace_items:
            if key not in self._hidden_channels:
                return key
        return None

    def _cursor_source_color(self, channel: str | None) -> str:
        if channel is None:
            return WAVEFORM_PLOT_FG
        return self._trace_style.get(channel, (WAVEFORM_PLOT_FG, 1.0))[0]

    def _cursor_source_tag(self, channel: str | None) -> str:
        if channel is None:
            return ""
        legend = self._trace_legend.get(channel, channel)
        return legend if len(legend) <= 12 else legend[:11] + "…"

    def _sample_cursor_channel(
        self, channel: str | None, t_us: float
    ) -> tuple[float, float] | None:
        if channel is None or self._trace_t_us is None:
            return None
        raw = self._effective_raw_for_channel(channel)
        if raw is None or len(raw) == 0:
            return None
        tt = self._trace_t_us
        if len(tt) == 0:
            return None
        t_clamped = float(np.clip(float(t_us), float(tt[0]), float(tt[-1])))
        value = float(np.interp(t_clamped, tt, raw))
        return value, self._to_disp(channel, value)

    def _hide_cursor_auxiliary_items(self) -> None:
        for item in (self._cursor_aux_hline, self._cursor_aux_vline):
            if item is not None:
                item.hide()

    def clear_cursor_auxiliary_guides(self) -> None:
        self._cursor_aux_channel = None
        self._cursor_aux_t_us = None
        self._cursor_aux_value = None
        self._cursor_aux_x_range_us = None
        self._cursor_aux_vertical_guide_enabled = False
        for attr in ("_cursor_aux_hline", "_cursor_aux_vline"):
            item = getattr(self, attr, None)
            if item is not None:
                try:
                    self.plot.removeItem(item)
                except Exception:
                    pass
            setattr(self, attr, None)

    def _ensure_cursor_auxiliary_items(self) -> None:
        plot_items = self.plot.getPlotItem().items
        if self._cursor_aux_hline is None:
            self._cursor_aux_hline = pg.PlotDataItem()
            self._cursor_aux_hline.setZValue(CURSOR_AUXILIARY_LINE_Z)
        if self._cursor_aux_hline not in plot_items:
            self.plot.addItem(self._cursor_aux_hline)
        if self._cursor_aux_vline is None:
            self._cursor_aux_vline = pg.PlotDataItem()
            self._cursor_aux_vline.setZValue(CURSOR_AUXILIARY_LINE_Z)
        if self._cursor_aux_vline not in plot_items:
            self.plot.addItem(self._cursor_aux_vline)

    def set_cursor_auxiliary_point(
        self,
        channel: str,
        t_us: float,
        value: float,
        *,
        show_vertical_guide: bool = False,
        x_range_us: tuple[float, float] | None = None,
    ) -> None:
        self._cursor_aux_channel = self._display_key_for_channel(str(channel))
        self._cursor_aux_t_us = float(t_us)
        self._cursor_aux_value = float(value)
        if x_range_us is None:
            self._cursor_aux_x_range_us = None
        else:
            x0, x1 = sorted((float(x_range_us[0]), float(x_range_us[1])))
            if np.isfinite(x0) and np.isfinite(x1) and x1 > x0:
                self._cursor_aux_x_range_us = (x0, x1)
            else:
                self._cursor_aux_x_range_us = None
        self._cursor_aux_vertical_guide_enabled = bool(show_vertical_guide)
        self._refresh_cursor_auxiliary_guides()

    def _cursor_auxiliary_point(self) -> tuple[str, float, float] | None:
        channel = self._cursor_aux_channel
        t_us = self._cursor_aux_t_us
        value = self._cursor_aux_value
        if (
            channel is not None
            and t_us is not None
            and value is not None
            and np.isfinite(float(t_us))
            and np.isfinite(float(value))
        ):
            return channel, float(t_us), float(value)

        if self._cursor_a is None or self._cursor_b is None:
            return None
        channel = self._cursor_source_channel()
        if channel is None:
            return None
        if self._cursor_waveform_visible():
            candidates: list[tuple[float, float, float]] = []
            for cursor in (self._cursor_a, self._cursor_b):
                t_candidate = float(cursor.value())
                sample_candidate = self._sample_cursor_channel(channel, t_candidate)
                if sample_candidate is not None:
                    raw_value, y_disp = sample_candidate
                    candidates.append((float(y_disp), t_candidate, float(raw_value)))
            if not candidates:
                return None
            _y_disp, t_us, value = max(candidates, key=lambda item: item[0])
            return channel, float(t_us), float(value)
        else:
            t_us = 0.5 * (float(self._cursor_a.value()) + float(self._cursor_b.value()))
        sample = self._sample_cursor_channel(channel, t_us)
        if sample is None:
            return None
        value, _y_disp = sample
        return channel, float(t_us), float(value)

    def _refresh_cursor_auxiliary_guides(self) -> None:
        point = self._cursor_auxiliary_point()
        if point is None or self._cursor_a is None or self._cursor_b is None:
            self._hide_cursor_auxiliary_items()
            return
        channel, _t_us, value = point
        if channel in self._hidden_channels:
            self._hide_cursor_auxiliary_items()
            return
        if channel not in self._trace_items:
            self._hide_cursor_auxiliary_items()
            return

        self._ensure_cursor_auxiliary_items()
        assert self._cursor_aux_hline is not None
        assert self._cursor_aux_vline is not None
        vertical_pen = _spaced_dash_pen(
            CURSOR_AUXILIARY_VERTICAL_COLOR,
            CURSOR_AUXILIARY_LINE_WIDTH,
        )
        horizontal_pen = _spaced_dash_pen(
            CURSOR_AUXILIARY_HORIZONTAL_COLOR,
            CURSOR_AUXILIARY_LINE_WIDTH,
        )
        y = float(self._to_disp(channel, float(value)))

        show_v = (
            self._cursor_vertical_visible()
            and self._cursor_aux_vertical_guide_enabled
        )
        if self._cursor_aux_x_range_us is not None:
            x0, x1 = self._cursor_aux_x_range_us
        else:
            x0, x1 = sorted((float(self._cursor_a.value()), float(self._cursor_b.value())))
        if show_v and x1 > x0:
            self._cursor_aux_hline.setPen(vertical_pen)
            self._cursor_aux_hline.setData([x0, x1], [y, y])
            self._cursor_aux_hline.show()
        else:
            self._cursor_aux_hline.hide()

        show_h = self._cursor_horizontal_visible()
        if (
            show_h
            and self._h_cursor_a is not None
            and self._h_cursor_b is not None
        ):
            y0, y1 = sorted(
                (
                    float(self._h_cursor_a.value()),
                    float(self._h_cursor_b.value()),
                )
            )
            if y1 > y0:
                x_aux = self._horizontal_cursor_auxiliary_x()
                self._cursor_aux_vline.setPen(horizontal_pen)
                self._cursor_aux_vline.setData([x_aux, x_aux], [y0, y1])
                self._cursor_aux_vline.show()
            else:
                self._cursor_aux_vline.hide()
        else:
            self._cursor_aux_vline.hide()

    def _energy_cursor_channels(self) -> tuple[str, ...]:
        raw = tuple(getattr(self, "_energy_peak_channels", ()) or ())
        if not raw:
            raw = (
                getattr(self, "_energy_ha_channel", "vce"),
                getattr(self, "_energy_hb_channel", "ic"),
            )
        out: list[str] = []
        for ch in raw:
            logical = str(ch)
            if logical not in out:
                out.append(logical)
        return tuple(out)

    def _energy_cursor_samples(self, t_us: float) -> list[tuple[str, str, float, float, str, str, str]]:
        labels = {
            "vce": "Vce",
            "ic": "Ic",
            "irr": "Irr",
            "v_diode": "Vd",
        }
        samples: list[tuple[str, str, float, float, str, str, str]] = []
        for logical in self._energy_cursor_channels():
            display = self._display_key_for_channel(logical)
            if display in self._hidden_channels:
                continue
            sample = self._sample_cursor_channel(display, t_us)
            if sample is None:
                continue
            value, y_div = sample
            unit = self._unit_for_channel(display)
            tag = labels.get(logical, self._cursor_source_tag(display) or display)
            color = self._cursor_source_color(display)
            samples.append((logical, display, value, y_div, unit, tag, color))
        return samples

    def _energy_cursor_values_html(
        self, samples: list[tuple[str, str, float, float, str, str, str]]
    ) -> str:
        lines = []
        for _logical, _display, value, _y_div, unit, tag, color in samples:
            sym = self._scope_wave_letter(unit)
            lines.append(
                f"<span style='color:{color};font-weight:700'>{tag}</span> "
                f"{sym}: {self._scope_quantity_text(value, unit)}"
            )
        return "<br/>".join(lines)

    def _energy_cursor_values_inline(
        self, samples: list[tuple[str, str, float, float, str, str, str]]
    ) -> str:
        parts = []
        for _logical, _display, value, _y_div, unit, tag, color in samples:
            parts.append(
                f"<span style='color:{color};font-weight:700'>{tag}</span> "
                f"{self._scope_quantity_text(value, unit)}"
            )
        return ", ".join(parts)

    def _energy_rule_marker_point(self, end: str) -> tuple[float, float, str] | None:
        if self._cursor_a is None or self._cursor_b is None:
            return None
        if end == "a":
            cursor = self._cursor_a
            h_line = self._h_cursor_a
            marker_channel = getattr(self, "_energy_a_channel", "vce")
            level_channel = getattr(self, "_energy_ha_channel", marker_channel)
            level_value = (
                self._from_disp(level_channel, float(h_line.value()))
                if h_line is not None
                else self._interp_channel(marker_channel, float(cursor.value()))
            )
        elif end == "b":
            cursor = self._cursor_b
            h_line = self._h_cursor_b
            marker_channel = getattr(self, "_energy_b_channel", "ic")
            level_channel = getattr(self, "_energy_hb_channel", marker_channel)
            if self._energy_b_level_vce is not None:
                marker_channel = "vce"
                level_channel = "vce"
                level_value = float(self._energy_b_level_vce)
            elif h_line is not None:
                level_value = self._from_disp(level_channel, float(h_line.value()))
            else:
                level_value = self._interp_channel(marker_channel, float(cursor.value()))
        else:
            return None

        marker_display = self._display_key_for_channel(marker_channel)
        level_display = self._display_key_for_channel(level_channel)
        if marker_display != level_display:
            return None
        if marker_display in self._hidden_channels:
            return None
        if marker_display not in self._trace_raw:
            return None
        return (
            float(cursor.value()),
            self._to_disp(marker_display, float(level_value)),
            self._cursor_source_color(marker_display),
        )

    def _energy_delta_values_html(
        self,
        a_samples: list[tuple[str, str, float, float, str, str, str]],
        b_samples: list[tuple[str, str, float, float, str, str, str]],
    ) -> str:
        by_key = {logical: (value, unit, tag, color) for logical, _display, value, _y, unit, tag, color in a_samples}
        lines = []
        for logical, _display, b_value, _y, unit, tag, color in b_samples:
            a = by_key.get(logical)
            if a is None:
                continue
            a_value, _unit, _tag, _color = a
            delta = float(b_value) - float(a_value)
            sym = self._scope_wave_letter(unit)
            lines.append(
                f"<span style='color:{color};font-weight:700'>Δ{tag}</span> "
                f"{sym}: {self._scope_quantity_text(delta, unit)}"
            )
        return "<br/>".join(lines)

    def _ensure_waveform_cursor_markers(self) -> None:
        plot_items = self.plot.getPlotItem().items
        for attr in ("_cursor_a_wave_marker", "_cursor_b_wave_marker"):
            item = getattr(self, attr)
            if item is None:
                item = pg.ScatterPlotItem(size=9, pxMode=True)
                item.setZValue(70)
                setattr(self, attr, item)
            if item not in plot_items:
                self.plot.addItem(item)

    def _hide_waveform_cursor_markers(self) -> None:
        for item in (self._cursor_a_wave_marker, self._cursor_b_wave_marker):
            if item is not None:
                item.hide()

    def _update_waveform_cursor_markers(self) -> None:
        if (
            not self._cursor_waveform_visible()
            or self._cursor_a is None
            or self._cursor_b is None
        ):
            self._hide_waveform_cursor_markers()
            return
        if self._interactive_mode == "energy_loss":
            a_point = self._energy_rule_marker_point("a")
            b_point = self._energy_rule_marker_point("b")
            if a_point is None and b_point is None:
                self._hide_waveform_cursor_markers()
                return
            self._ensure_waveform_cursor_markers()
            pen = pg.mkPen("#f2f2f2", width=1.2)

            assert self._cursor_a_wave_marker is not None
            assert self._cursor_b_wave_marker is not None
            if a_point is None:
                self._cursor_a_wave_marker.hide()
            else:
                x, y, color = a_point
                self._cursor_a_wave_marker.setData(
                    [x],
                    [y],
                    pen=pen,
                    brush=pg.mkBrush(QColor(color)),
                )
                self._cursor_a_wave_marker.show()
            if b_point is None:
                self._cursor_b_wave_marker.hide()
            else:
                x, y, color = b_point
                self._cursor_b_wave_marker.setData(
                    [x],
                    [y],
                    pen=pen,
                    brush=pg.mkBrush(QColor(color)),
                )
                self._cursor_b_wave_marker.show()
            return
        ch = self._cursor_source_channel()
        a_sample = self._sample_cursor_channel(ch, float(self._cursor_a.value()))
        b_sample = self._sample_cursor_channel(ch, float(self._cursor_b.value()))
        if ch is None or a_sample is None or b_sample is None:
            self._hide_waveform_cursor_markers()
            return
        self._ensure_waveform_cursor_markers()
        color = self._cursor_source_color(ch)
        pen = pg.mkPen("#f2f2f2", width=1.2)
        brush = pg.mkBrush(QColor(color))
        assert self._cursor_a_wave_marker is not None
        assert self._cursor_b_wave_marker is not None
        self._cursor_a_wave_marker.setData(
            [float(self._cursor_a.value())],
            [a_sample[1]],
            pen=pen,
            brush=brush,
        )
        self._cursor_b_wave_marker.setData(
            [float(self._cursor_b.value())],
            [b_sample[1]],
            pen=pen,
            brush=brush,
        )
        self._cursor_a_wave_marker.show()
        self._cursor_b_wave_marker.show()

    @staticmethod
    def _cursor_plot_label_html(text: str, color: str) -> str:
        return (
            "<div style='"
            f"background-color:rgba(30,30,46,{CURSOR_READOUT_BG_ALPHA});"
            "padding:4px 8px;"
            "border-radius:6px;"
            f"color:{color};font-size:11px;line-height:1.35;"
            "font-family:Segoe UI,sans-serif'>"
            f"{text}</div>"
        )

    @staticmethod
    def _cursor_name_label_html(text: str, color: str) -> str:
        return (
            "<div style='"
            f"background-color:rgba(10,10,14,{CURSOR_NAME_BG_ALPHA});"
            "padding:2px 5px;border-radius:4px;"
            f"color:{color};font-size:{CURSOR_NAME_FONT_SIZE_PX}px;"
            "font-weight:700;line-height:1.2;"
            "font-family:Segoe UI,sans-serif'>"
            f"{text}</div>"
        )

    def _cursor_readout_scene_rect(self) -> QRectF:
        return self.plot.getPlotItem().getViewBox().sceneBoundingRect()

    def _cursor_readout_top_scene_y(self) -> float:
        rect = self._cursor_readout_scene_rect()
        return float(rect.top()) + CURSOR_READOUT_EDGE_INSET_PX

    def _cursor_readout_bottom_scene_y(self) -> float:
        rect = self._cursor_readout_scene_rect()
        bottom = float(rect.bottom()) - CURSOR_READOUT_BOTTOM_TICK_GUARD_PX
        return max(float(rect.top()) + CURSOR_READOUT_EDGE_INSET_PX, bottom)

    def _cursor_readout_scene_x(self, x: float) -> float:
        vb = self.plot.getPlotItem().getViewBox()
        return float(vb.mapViewToScene(QPointF(float(x), 0.0)).x())

    def _cursor_readout_stack_height(self, item: pg.TextItem | None) -> float:
        if item is None:
            return CURSOR_READOUT_MIN_ROW_PX
        try:
            h = float(item.boundingRect().height())
        except Exception:
            h = 0.0
        return max(CURSOR_READOUT_MIN_ROW_PX, h)

    def _cursor_marker_scene_point(self, end: str) -> QPointF | None:
        marker = (
            self._cursor_a_wave_marker
            if end == "a"
            else self._cursor_b_wave_marker
            if end == "b"
            else None
        )
        if marker is None or not marker.isVisible():
            return None
        try:
            xs, ys = marker.getData()
            x_arr = np.asarray(xs, dtype=float).ravel()
            y_arr = np.asarray(ys, dtype=float).ravel()
            if x_arr.size == 0 or y_arr.size == 0:
                return None
            x = float(x_arr[0])
            y = float(y_arr[0])
        except Exception:
            return None
        if not (np.isfinite(x) and np.isfinite(y)):
            return None
        vb = self.plot.getPlotItem().getViewBox()
        return vb.mapViewToScene(QPointF(x, y))

    @staticmethod
    def _cursor_text_scene_rect(item: pg.TextItem) -> QRectF:
        return item.mapRectToScene(item.boundingRect())

    @staticmethod
    def _padded_scene_rect(rect: QRectF, padding: float) -> QRectF:
        return QRectF(
            float(rect.left()) - padding,
            float(rect.top()) - padding,
            float(rect.width()) + padding * 2.0,
            float(rect.height()) + padding * 2.0,
        )

    @staticmethod
    def _cursor_line_label(line: pg.InfiniteLine | None):
        if line is None:
            return None
        return getattr(line, "label", None)

    @staticmethod
    def _set_cursor_line_label_anchors(
        line: pg.InfiniteLine | None,
        anchors: tuple[tuple[float, float], tuple[float, float]],
    ) -> None:
        label = WaveformPlot._cursor_line_label(line)
        if label is None:
            return
        label.anchors = [tuple(anchors[0]), tuple(anchors[1])]
        try:
            label.updatePosition()
        except Exception:
            pass

    def _cursor_line_label_scene_rect(
        self, line: pg.InfiniteLine | None
    ) -> QRectF | None:
        label = self._cursor_line_label(line)
        if label is None or not label.isVisible():
            return None
        try:
            rect = label.mapRectToScene(label.boundingRect())
        except Exception:
            return None
        if float(rect.width()) <= 0.0 or float(rect.height()) <= 0.0:
            return None
        return rect

    def _cursor_line_labels_intersect(
        self, first: QRectF | None, second: QRectF | None
    ) -> bool:
        if first is None or second is None:
            return False
        return self._padded_scene_rect(
            first,
            CURSOR_LINE_LABEL_GUARD_PX,
        ).intersects(
            self._padded_scene_rect(
                second,
                CURSOR_LINE_LABEL_GUARD_PX,
            )
        )

    def _sync_cursor_line_label_positions(self) -> None:
        vertical_default = ((0.0, 0.5), (1.0, 0.5))
        horizontal_default = ((0.5, 0.0), (0.5, 1.0))
        for line in (self._cursor_a, self._cursor_b):
            self._set_cursor_line_label_anchors(line, vertical_default)
        for line in (self._h_cursor_a, self._h_cursor_b):
            self._set_cursor_line_label_anchors(line, horizontal_default)

        a_rect = self._cursor_line_label_scene_rect(self._cursor_a)
        b_rect = self._cursor_line_label_scene_rect(self._cursor_b)
        if self._cursor_line_labels_intersect(a_rect, b_rect):
            a_x = self._cursor_readout_scene_x(float(self._cursor_a.value()))
            b_x = self._cursor_readout_scene_x(float(self._cursor_b.value()))
            if a_x <= b_x:
                a_anchor, b_anchor = (1.0, 0.5), (0.0, 0.5)
            else:
                a_anchor, b_anchor = (0.0, 0.5), (1.0, 0.5)
            self._set_cursor_line_label_anchors(self._cursor_a, (a_anchor, a_anchor))
            self._set_cursor_line_label_anchors(self._cursor_b, (b_anchor, b_anchor))

        ha_rect = self._cursor_line_label_scene_rect(self._h_cursor_a)
        hb_rect = self._cursor_line_label_scene_rect(self._h_cursor_b)
        if self._cursor_line_labels_intersect(ha_rect, hb_rect):
            vb = self.plot.getPlotItem().getViewBox()
            ha_y = float(
                vb.mapViewToScene(
                    QPointF(0.0, float(self._h_cursor_a.value()))
                ).y()
            )
            hb_y = float(
                vb.mapViewToScene(
                    QPointF(0.0, float(self._h_cursor_b.value()))
                ).y()
            )
            if ha_y <= hb_y:
                ha_anchor, hb_anchor = (0.5, 1.0), (0.5, 0.0)
            else:
                ha_anchor, hb_anchor = (0.5, 0.0), (0.5, 1.0)
            self._set_cursor_line_label_anchors(self._h_cursor_a, (ha_anchor, ha_anchor))
            self._set_cursor_line_label_anchors(self._h_cursor_b, (hb_anchor, hb_anchor))

    def _visible_cursor_readout_items(self) -> list[pg.TextItem]:
        items: list[pg.TextItem] = []
        for attr in (
            "_cursor_ha_v_label",
            "_cursor_hb_v_label",
            "_cursor_hb_ha_delta_label",
            "_cursor_ab_delta_label",
            "_cursor_a_t_label",
            "_cursor_b_t_label",
        ):
            item = getattr(self, attr, None)
            if item is not None and item.isVisible():
                items.append(item)
        return items

    def _move_cursor_label_to_scene_top(
        self, item: pg.TextItem, top_y: float
    ) -> None:
        current = self._cursor_text_scene_rect(item)
        item.setPos(
            QPointF(
                float(item.scenePos().x()),
                float(item.scenePos().y()) + top_y - float(current.top()),
            )
        )

    def _avoid_cursor_label_overlaps(self) -> None:
        scene_rect = self._cursor_readout_scene_rect()
        top_limit = float(scene_rect.top()) + CURSOR_READOUT_EDGE_INSET_PX
        bottom_limit = float(scene_rect.bottom()) - CURSOR_READOUT_EDGE_INSET_PX
        placed: list[QRectF] = []
        for end in ("a", "b"):
            point = self._cursor_marker_scene_point(end)
            if point is not None:
                placed.append(
                    QRectF(
                        float(point.x()) - CURSOR_READOUT_MARKER_GUARD_PX,
                        float(point.y()) - CURSOR_READOUT_MARKER_GUARD_PX,
                        CURSOR_READOUT_MARKER_GUARD_PX * 2.0,
                        CURSOR_READOUT_MARKER_GUARD_PX * 2.0,
                    )
                )
        for item in self._visible_cursor_readout_items():
            for _ in range(6):
                current = self._padded_scene_rect(
                    self._cursor_text_scene_rect(item),
                    CURSOR_READOUT_LABEL_GUARD_PX,
                )
                blocker = next(
                    (rect for rect in placed if current.intersects(rect)),
                    None,
                )
                if blocker is None:
                    break
                raw_current = self._cursor_text_scene_rect(item)
                target_top = float(blocker.bottom()) + CURSOR_READOUT_STACK_GAP_PX
                if target_top + float(raw_current.height()) > bottom_limit:
                    target_top = (
                        float(blocker.top())
                        - CURSOR_READOUT_STACK_GAP_PX
                        - float(raw_current.height())
                    )
                max_top = bottom_limit - float(raw_current.height())
                target_top = max(top_limit, min(max_top, target_top))
                self._move_cursor_label_to_scene_top(item, target_top)
            placed.append(
                self._padded_scene_rect(
                    self._cursor_text_scene_rect(item),
                    CURSOR_READOUT_LABEL_GUARD_PX,
                )
            )

    def _plot_label_x_left_edge(self) -> float:
        """横向光标读数框：贴在当前视图最左侧，避免压在波形中间。"""
        vb = self.plot.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        span = max(x1 - x0, 1e-9)
        return x0 + 0.01 * span

    def _horizontal_cursor_auxiliary_x(self) -> float:
        """横向光标辅助竖线对齐左侧读数浮窗的左边距。"""
        return self._plot_label_x_left_edge()

    def _plot_label_x_right_edge(self) -> float:
        """横向光标名称框：贴右侧，避开左侧 Ha/Hb 数值读数。"""
        vb = self.plot.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        span = max(x1 - x0, 1e-9)
        return x1 - 0.01 * span

    def _horizontal_cursor_plot_values(
        self, ha_div: float, hb_div: float, dt_us: float, *, include_rate: bool
    ) -> tuple[str, str, str | None]:
        """返回 Ha/Hb 单点 HTML 与 Δ/Δt 浮动框 HTML（示波器风格）。"""

        def _level_html(name: str, val: float, unit: str, color: str) -> str:
            return self._cursor_plot_label_html(
                f"{name}: {self._scope_quantity_text(val, unit)}", color
            )

        def _delta_html(dv: float, unit: str) -> str:
            sym = self._scope_wave_letter(unit)
            text = f"Δ {sym}: {self._scope_quantity_text(dv, unit)}"
            if include_rate:
                is_i = unit == "A"
                text += (
                    "<br/>"
                    f"Δ {sym}/ Δ t: {self._scope_rate_text(dv, dt_us, is_current=is_i)}"
                )
            return self._cursor_plot_label_html(text, "#CDD6F4")

        if self._interactive_mode == "energy_loss":
            ha_ch = getattr(self, "_energy_ha_channel", "vce")
            hb_ch = getattr(self, "_energy_hb_channel", "ic")
            ha_val = self._from_disp(ha_ch, ha_div)
            hb_val = self._from_disp(hb_ch, hb_div)
            if ha_ch == "irr":
                ha_val = abs(ha_val)
            if hb_ch == "irr":
                hb_val = abs(hb_val)
            u_ha = self._unit_for_channel(ha_ch)
            u_hb = self._unit_for_channel(hb_ch)
            ha_html = _level_html("Ha", ha_val, u_ha, CURSOR_PEN_A)
            hb_html = _level_html("Hb", hb_val, u_hb, CURSOR_PEN_B)
            if ha_ch != hb_ch or u_ha != u_hb:
                return ha_html, hb_html, None
            return ha_html, hb_html, _delta_html(hb_val - ha_val, u_ha)

        ch = self._readout_channel()
        unit = self._unit_for_channel(ch)
        ha_val = self._from_disp(ch, ha_div)
        hb_val = self._from_disp(ch, hb_div)
        if ch == "irr":
            ha_val = abs(ha_val)
            hb_val = abs(hb_val)
        ha_html = _level_html("Ha", ha_val, unit, CURSOR_PEN_A)
        hb_html = _level_html("Hb", hb_val, unit, CURSOR_PEN_B)
        return ha_html, hb_html, _delta_html(hb_val - ha_val, unit)

    def _remove_cursor_plot_labels(self) -> None:
        for attr in (
            "_cursor_a_t_label",
            "_cursor_b_t_label",
            "_cursor_ab_delta_label",
            "_cursor_ha_v_label",
            "_cursor_hb_v_label",
            "_cursor_hb_ha_delta_label",
            "_cursor_ha_name_label",
            "_cursor_hb_name_label",
        ):
            item = getattr(self, attr)
            if item is not None:
                self.plot.scene().removeItem(item)
            setattr(self, attr, None)
        for attr in (
            "_cursor_a_wave_marker",
            "_cursor_b_wave_marker",
        ):
            item = getattr(self, attr)
            if item is not None:
                self.plot.removeItem(item)
            setattr(self, attr, None)

    def _ensure_v_cursor_plot_labels(self) -> None:
        if self._cursor_a_t_label is None:
            self._cursor_a_t_label = pg.TextItem(anchor=(0.5, 1.0))
            self._cursor_a_t_label.setZValue(CURSOR_READOUT_OVERLAY_Z)
            self.plot.scene().addItem(self._cursor_a_t_label)
        if self._cursor_b_t_label is None:
            self._cursor_b_t_label = pg.TextItem(anchor=(0.5, 1.0))
            self._cursor_b_t_label.setZValue(CURSOR_READOUT_OVERLAY_Z)
            self.plot.scene().addItem(self._cursor_b_t_label)
        if self._cursor_ab_delta_label is None:
            self._cursor_ab_delta_label = pg.TextItem(anchor=(0.5, 1.0))
            self._cursor_ab_delta_label.setZValue(CURSOR_READOUT_OVERLAY_Z)
            self.plot.scene().addItem(self._cursor_ab_delta_label)

    def _separate_h_cursor_name_positions(
        self, ha_pos: QPointF, hb_pos: QPointF
    ) -> tuple[QPointF, QPointF]:
        min_gap_px = 18.0
        dy = float(hb_pos.y() - ha_pos.y())
        if abs(dy) < min_gap_px:
            center = 0.5 * (float(ha_pos.y()) + float(hb_pos.y()))
            if dy >= 0:
                ha_pos.setY(center - min_gap_px * 0.5)
                hb_pos.setY(center + min_gap_px * 0.5)
            else:
                ha_pos.setY(center + min_gap_px * 0.5)
                hb_pos.setY(center - min_gap_px * 0.5)
        try:
            rect = self.plot.getPlotItem().getViewBox().sceneBoundingRect()
            top = float(rect.top()) + 8.0
            bottom = float(rect.bottom()) - 8.0
            ha_pos.setY(max(top, min(bottom, float(ha_pos.y()))))
            hb_pos.setY(max(top, min(bottom, float(hb_pos.y()))))
        except Exception:
            pass
        return ha_pos, hb_pos

    def _position_v_cursor_plot_labels(self, a_us: float, b_us: float) -> None:
        if (
            self._cursor_a_t_label is None
            or self._cursor_b_t_label is None
            or self._cursor_ab_delta_label is None
        ):
            return
        y_bottom = self._cursor_readout_bottom_scene_y()
        y_top = self._cursor_readout_top_scene_y()
        a_x = self._cursor_readout_scene_x(a_us)
        b_x = self._cursor_readout_scene_x(b_us)
        if a_x <= b_x:
            self._cursor_a_t_label.setAnchor((1.0, 1.0))
            self._cursor_b_t_label.setAnchor((0.0, 1.0))
            a_label_x = a_x - CURSOR_READOUT_CURSOR_GAP_PX
            b_label_x = b_x + CURSOR_READOUT_CURSOR_GAP_PX
        else:
            self._cursor_a_t_label.setAnchor((0.0, 1.0))
            self._cursor_b_t_label.setAnchor((1.0, 1.0))
            a_label_x = a_x + CURSOR_READOUT_CURSOR_GAP_PX
            b_label_x = b_x - CURSOR_READOUT_CURSOR_GAP_PX
        self._cursor_ab_delta_label.setAnchor((0.5, 0.0))
        self._cursor_a_t_label.setPos(QPointF(a_label_x, y_bottom))
        self._cursor_b_t_label.setPos(QPointF(b_label_x, y_bottom))
        self._cursor_ab_delta_label.setPos(
            QPointF(self._cursor_readout_scene_x(0.5 * (a_us + b_us)), y_top)
        )
        self._avoid_v_cursor_marker_overlap(
            self._cursor_a_t_label,
            "a",
            a_label_x,
            anchor_x=float(self._cursor_a_t_label.anchor.x()),
        )
        self._avoid_v_cursor_marker_overlap(
            self._cursor_b_t_label,
            "b",
            b_label_x,
            anchor_x=float(self._cursor_b_t_label.anchor.x()),
        )

    def _avoid_v_cursor_marker_overlap(
        self, item: pg.TextItem, end: str, label_x: float, *, anchor_x: float
    ) -> None:
        point = self._cursor_marker_scene_point(end)
        if point is None:
            return
        guard = QRectF(
            float(point.x()) - CURSOR_READOUT_MARKER_GUARD_PX,
            float(point.y()) - CURSOR_READOUT_MARKER_GUARD_PX,
            CURSOR_READOUT_MARKER_GUARD_PX * 2.0,
            CURSOR_READOUT_MARKER_GUARD_PX * 2.0,
        )
        if not self._cursor_text_scene_rect(item).intersects(guard):
            return
        item.setAnchor((anchor_x, 0.0))
        item.setPos(
            QPointF(label_x, float(guard.bottom()) + CURSOR_READOUT_STACK_GAP_PX)
        )
        if not self._cursor_text_scene_rect(item).intersects(guard):
            return
        item.setAnchor((anchor_x, 1.0))
        item.setPos(
            QPointF(label_x, float(guard.top()) - CURSOR_READOUT_STACK_GAP_PX)
        )

    def _update_v_cursor_plot_labels(self, a_us: float, b_us: float) -> None:
        """A/B 竖向或波形光标读数（示波器风格）。"""
        show_v = self._cursor_vertical_visible()
        if not show_v or not self._cursor_readout_overlay:
            for attr in ("_cursor_a_t_label", "_cursor_b_t_label", "_cursor_ab_delta_label"):
                item = getattr(self, attr)
                if item is not None:
                    item.hide()
            self._update_waveform_cursor_markers()
            return
        if self._cursor_a is None or self._cursor_b is None:
            self._remove_cursor_plot_labels()
            return
        self._ensure_v_cursor_plot_labels()
        dt_us = b_us - a_us
        freq_txt = self._freq_text_from_dt_us(dt_us)
        if self._interactive_mode == "energy_loss":
            a_samples = self._energy_cursor_samples(a_us)
            b_samples = self._energy_cursor_samples(b_us)
            if self._cursor_waveform_visible() and a_samples and b_samples:
                a_text = (
                    f"t: {a_us:.3f} µs<br/>"
                    f"{self._energy_cursor_values_html(a_samples)}"
                )
                b_text = (
                    f"t: {b_us:.3f} µs<br/>"
                    f"{self._energy_cursor_values_html(b_samples)}"
                )
                delta_lines = self._energy_delta_values_html(a_samples, b_samples)
                delta_text = f"Δ t: {dt_us:.3f} µs&nbsp;&nbsp;&nbsp;1 / Δ t: {freq_txt}"
                if delta_lines:
                    delta_text = f"{delta_text}<br/>{delta_lines}"
                self._cursor_a_t_label.setHtml(
                    self._cursor_plot_label_html(a_text, CURSOR_PEN_A)
                )
                self._cursor_b_t_label.setHtml(
                    self._cursor_plot_label_html(b_text, CURSOR_PEN_B)
                )
                self._cursor_ab_delta_label.setHtml(
                    self._cursor_plot_label_html(delta_text, "#CDD6F4")
                )
                self._update_waveform_cursor_markers()
                self._position_v_cursor_plot_labels(a_us, b_us)
                self._cursor_a_t_label.show()
                self._cursor_b_t_label.show()
                self._cursor_ab_delta_label.show()
                return
        ch = self._cursor_source_channel()
        unit = self._unit_for_channel(ch) if ch is not None else ""
        sym = self._scope_wave_letter(unit)
        a_sample = self._sample_cursor_channel(ch, a_us)
        b_sample = self._sample_cursor_channel(ch, b_us)
        show_wave_values = self._cursor_waveform_visible() and a_sample is not None and b_sample is not None
        source_color = self._cursor_source_color(ch)
        if show_wave_values:
            assert a_sample is not None and b_sample is not None
            tag = self._cursor_source_tag(ch)
            prefix = f"<span style='color:{source_color};font-weight:700'>{tag}</span> " if tag else ""
            a_text = (
                f"{prefix}t: {a_us:.3f} µs<br/>"
                f"{sym}: {self._scope_quantity_text(a_sample[0], unit)}"
            )
            b_text = (
                f"{prefix}t: {b_us:.3f} µs<br/>"
                f"{sym}: {self._scope_quantity_text(b_sample[0], unit)}"
            )
            dv = b_sample[0] - a_sample[0]
            delta_text = (
                f"Δ t: {dt_us:.3f} µs&nbsp;&nbsp;&nbsp;1 / Δ t: {freq_txt}<br/>"
                f"Δ {sym}: {self._scope_quantity_text(dv, unit)}&nbsp;&nbsp;&nbsp;"
                f"Δ {sym}/ Δ t: {self._scope_rate_text(dv, dt_us, is_current=unit == 'A')}"
            )
        else:
            a_text = f"t: {a_us:.3f} µs"
            b_text = f"t: {b_us:.3f} µs"
            delta_text = f"Δ t: {dt_us:.3f} µs<br/>1 / Δ t: {freq_txt}"
        self._cursor_a_t_label.setHtml(
            self._cursor_plot_label_html(a_text, CURSOR_PEN_A)
        )
        self._cursor_b_t_label.setHtml(
            self._cursor_plot_label_html(b_text, CURSOR_PEN_B)
        )
        delta_html = self._cursor_plot_label_html(delta_text, "#CDD6F4")
        self._cursor_ab_delta_label.setHtml(delta_html)
        self._update_waveform_cursor_markers()
        self._position_v_cursor_plot_labels(a_us, b_us)
        self._cursor_a_t_label.show()
        self._cursor_b_t_label.show()
        self._cursor_ab_delta_label.show()

    def _ensure_h_cursor_plot_labels(self) -> None:
        if self._cursor_ha_v_label is None:
            self._cursor_ha_v_label = pg.TextItem(anchor=(0.0, 0.5))
            self._cursor_ha_v_label.setZValue(CURSOR_READOUT_OVERLAY_Z)
            self.plot.scene().addItem(self._cursor_ha_v_label)
        if self._cursor_hb_v_label is None:
            self._cursor_hb_v_label = pg.TextItem(anchor=(0.0, 0.5))
            self._cursor_hb_v_label.setZValue(CURSOR_READOUT_OVERLAY_Z)
            self.plot.scene().addItem(self._cursor_hb_v_label)
        if self._cursor_hb_ha_delta_label is None:
            self._cursor_hb_ha_delta_label = pg.TextItem(anchor=(0.0, 0.5))
            self._cursor_hb_ha_delta_label.setZValue(CURSOR_READOUT_OVERLAY_Z)
            self.plot.scene().addItem(self._cursor_hb_ha_delta_label)

    def _position_h_cursor_plot_labels(
        self, a_us: float, b_us: float, ha_div: float, hb_div: float
    ) -> None:
        if (
            self._cursor_ha_v_label is None
            or self._cursor_hb_v_label is None
            or self._cursor_hb_ha_delta_label is None
        ):
            return
        rect = self._cursor_readout_scene_rect()
        x_left = float(rect.left()) + CURSOR_READOUT_EDGE_INSET_PX
        y_top = self._cursor_readout_top_scene_y()
        self._cursor_ha_v_label.setAnchor((0.0, 0.0))
        self._cursor_hb_v_label.setAnchor((0.0, 0.0))
        self._cursor_ha_v_label.setPos(QPointF(x_left, y_top))
        hb_y = (
            y_top
            + self._cursor_readout_stack_height(self._cursor_ha_v_label)
            + CURSOR_READOUT_STACK_GAP_PX
        )
        self._cursor_hb_v_label.setPos(QPointF(x_left, hb_y))
        if self._cursor_vertical_visible():
            delta_y = (
                hb_y
                + self._cursor_readout_stack_height(self._cursor_hb_v_label)
                + CURSOR_READOUT_STACK_GAP_PX
            )
            self._cursor_hb_ha_delta_label.setAnchor((0.0, 0.0))
        else:
            delta_y = self._cursor_readout_bottom_scene_y()
            self._cursor_hb_ha_delta_label.setAnchor((0.0, 1.0))
        self._cursor_hb_ha_delta_label.setPos(QPointF(x_left, delta_y))

    def _update_h_cursor_plot_labels(
        self, a_us: float, b_us: float, ha_div: float, hb_div: float, dt_us: float
    ) -> None:
        """Ha/Hb 旁显示物理量、Δv 与 Δv/Δt（Δt 取自纵向 A/B）。"""
        show_h = self._cursor_horizontal_visible()
        if not show_h:
            for attr in (
                "_cursor_ha_v_label",
                "_cursor_hb_v_label",
                "_cursor_hb_ha_delta_label",
                "_cursor_ha_name_label",
                "_cursor_hb_name_label",
            ):
                item = getattr(self, attr)
                if item is not None:
                    item.hide()
            return
        if self._h_cursor_a is None or self._h_cursor_b is None:
            for attr in (
                "_cursor_ha_v_label",
                "_cursor_hb_v_label",
                "_cursor_hb_ha_delta_label",
                "_cursor_ha_name_label",
                "_cursor_hb_name_label",
            ):
                item = getattr(self, attr)
                if item is not None:
                    item.hide()
            return
        self._ensure_h_cursor_plot_labels()
        if not self._cursor_readout_overlay:
            for attr in (
                "_cursor_ha_v_label",
                "_cursor_hb_v_label",
                "_cursor_hb_ha_delta_label",
            ):
                item = getattr(self, attr)
                if item is not None:
                    item.hide()
            self._position_h_cursor_plot_labels(a_us, b_us, ha_div, hb_div)
            return
        ha_html, hb_html, delta_html = self._horizontal_cursor_plot_values(
            ha_div,
            hb_div,
            dt_us,
            include_rate=self._cursor_vertical_visible(),
        )
        self._cursor_ha_v_label.setHtml(ha_html)
        self._cursor_hb_v_label.setHtml(hb_html)
        self._position_h_cursor_plot_labels(a_us, b_us, ha_div, hb_div)
        self._cursor_ha_v_label.show()
        self._cursor_hb_v_label.show()
        if delta_html is not None:
            self._cursor_hb_ha_delta_label.setHtml(delta_html)
            self._cursor_hb_ha_delta_label.show()
        else:
            self._cursor_hb_ha_delta_label.hide()

    def _on_view_geometry_changed(self, *_) -> None:
        self._queue_plot_geometry_sync(force_traces=True)

    def _queue_plot_geometry_sync(self, *, force_traces: bool = False) -> None:
        if force_traces:
            self._plot_geometry_force_trace_sync = True
        if getattr(self, "_plot_geometry_sync_pending", False):
            return
        self._plot_geometry_sync_pending = True
        QTimer.singleShot(0, self._run_plot_geometry_sync)

    def _schedule_post_layout_sync(self) -> None:
        self._queue_plot_geometry_sync(force_traces=True)
        QTimer.singleShot(
            16, lambda: self._queue_plot_geometry_sync(force_traces=True)
        )
        QTimer.singleShot(
            80, lambda: self._queue_plot_geometry_sync(force_traces=True)
        )

    def _run_plot_geometry_sync(self) -> None:
        self._plot_geometry_sync_pending = False
        force_traces = bool(getattr(self, "_plot_geometry_force_trace_sync", False))
        self._plot_geometry_force_trace_sync = False
        if getattr(self, "_trace_t_us", None) is None:
            return
        if force_traces:
            self._refresh_visible_traces(force=True)
        self._update_y_ticks()
        self._sync_x_tick_labels_from_axis()
        self._update_zero_handle_positions()
        self._refresh_auxiliary_dash_lines()
        self._sync_cursor_line_label_positions()
        self._refresh_cursor_auxiliary_guides()

    def _on_view_range_changed(self) -> None:
        self._refresh_visible_traces()
        try:
            xr = self.plot.getPlotItem().getViewBox().viewRange()[0]
            self._last_x_window = (float(xr[0]), float(xr[1]))
        except Exception:
            pass
        self._sync_overview_region_to_main()
        self._update_zero_handle_positions()
        self._update_y_ticks()
        self._sync_x_tick_labels_from_axis()
        self._refresh_auxiliary_dash_lines()
        self._sync_cursor_line_label_positions()
        self._refresh_cursor_auxiliary_guides()
        if self._view_range_callback is not None:
            try:
                self._view_range_callback()
            except Exception:
                pass
        if self._cursor_a is None or self._cursor_b is None:
            return
        a = float(self._cursor_a.value())
        b = float(self._cursor_b.value())
        self._position_v_cursor_plot_labels(a, b)
        if self._h_cursor_a is not None and self._h_cursor_b is not None:
            self._position_h_cursor_plot_labels(
                a,
                b,
                float(self._h_cursor_a.value()),
                float(self._h_cursor_b.value()),
            )
        self._sync_cursor_line_label_positions()
        self._avoid_cursor_label_overlaps()
        self._apply_cursor_visibility()

    # ------------------------------------------------------------------ 读数刷新 ----
    def _sync_readout_scroll_width(self) -> None:
        host = self._readout_scroll.widget()
        if host is None:
            return
        self._readout_label.adjustSize()
        content_w = self._readout_label.sizeHint().width() + 16
        view_w = max(120, self._readout_scroll.viewport().width())
        host.setFixedWidth(max(content_w, view_w))

    def _sync_channel_bar_width(self) -> None:
        n = len(self._channel_boxes)
        if n == 0:
            return
        self._channel_bar.adjustSize()
        # sizeHint 在首次布局前可能偏小，按通道盒最小宽度兜底
        box_min_w = 108
        margins = 22
        content_w = max(
            n * (box_min_w + 5) + margins,
            self._channel_bar.sizeHint().width() + 12,
        )
        view_w = max(120, self._channel_scroll.viewport().width())
        bar_h = max(62, self._channel_bar.sizeHint().height())
        self._channel_content_width = content_w
        self._channel_bar.setFixedSize(max(content_w, view_w), bar_h)
        self._sync_channel_nav_buttons()

    def _channel_nav_overflow(self) -> bool:
        if not hasattr(self, "_channel_strip"):
            return False
        content_w = int(getattr(self, "_channel_content_width", 0))
        if content_w <= 0:
            content_w = int(self._channel_bar.sizeHint().width() + 12)
        available_w = max(120, int(self._channel_strip.width()) - 4)
        return content_w > available_w

    def _sync_channel_nav_buttons(self) -> None:
        if not hasattr(self, "_channel_nav_left_btn"):
            return
        overflow = self._channel_nav_overflow()
        was_left_visible = self._channel_nav_left_btn.isVisible()
        was_right_visible = self._channel_nav_right_btn.isVisible()
        self._channel_nav_left_btn.setVisible(overflow)
        self._channel_nav_right_btn.setVisible(overflow)
        bar = self._channel_scroll.horizontalScrollBar()
        if not overflow:
            if bar.value() != bar.minimum():
                bar.setValue(bar.minimum())
            self._channel_nav_left_btn.setEnabled(False)
            self._channel_nav_right_btn.setEnabled(False)
        else:
            self._channel_nav_left_btn.setEnabled(bar.value() > bar.minimum())
            self._channel_nav_right_btn.setEnabled(bar.value() < bar.maximum())
        if (
            was_left_visible != self._channel_nav_left_btn.isVisible()
            or was_right_visible != self._channel_nav_right_btn.isVisible()
        ):
            QTimer.singleShot(0, self._sync_channel_bar_width)

    def _scroll_channel_bar(self, direction: int) -> None:
        bar = self._channel_scroll.horizontalScrollBar()
        step = max(120, int(self._channel_scroll.viewport().width() * 0.6))
        bar.setValue(bar.value() + int(direction) * step)
        self._sync_channel_nav_buttons()

    def _set_readout_text(self, txt: str) -> None:
        self._readout_label.setText(txt)
        self._sync_readout_scroll_width()
        if hasattr(self, "_cursor_type"):
            self._apply_cursor_visibility()

    def _register_auxiliary_dash_line(
        self,
        line: pg.InfiniteLine,
        *,
        color: str = REFERENCE_LINE_COLOR,
        width: float = 1.0,
        hover_color: str | None = None,
        hover_width: float | None = None,
    ) -> pg.InfiniteLine:
        line._dpt_dash_color = color
        line._dpt_dash_width = float(width)
        line._dpt_dash_hover_color = hover_color
        line._dpt_dash_hover_width = (
            float(hover_width) if hover_width is not None else None
        )
        self._apply_auxiliary_dash_line_style(line)
        if line not in self._auxiliary_dash_lines:
            self._auxiliary_dash_lines.append(line)
        return line

    def _apply_auxiliary_dash_line_style(self, line: pg.InfiniteLine) -> None:
        color = getattr(line, "_dpt_dash_color", REFERENCE_LINE_COLOR)
        width = float(getattr(line, "_dpt_dash_width", 1.0))
        line.setPen(_spaced_dash_pen(color, width))
        hover_color = getattr(line, "_dpt_dash_hover_color", None)
        hover_width = getattr(line, "_dpt_dash_hover_width", None)
        if hover_color is not None and hover_width is not None:
            line.setHoverPen(_spaced_dash_pen(hover_color, float(hover_width)))
        line.update()
        label = getattr(line, "label", None)
        if label is not None:
            label.update()

    def _refresh_auxiliary_dash_lines(self) -> None:
        if not self._auxiliary_dash_lines:
            return
        plot_items = set(self.plot.getPlotItem().items)
        self._auxiliary_dash_lines = [
            line for line in self._auxiliary_dash_lines if line in plot_items
        ]
        for line in self._auxiliary_dash_lines:
            self._apply_auxiliary_dash_line_style(line)
        self.plot.scene().update()
        self.plot.viewport().update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_readout_scroll_width()
        self._sync_channel_bar_width()
        self._sync_x_tick_labels_from_axis()
        if self._cursor_a is not None and self._cursor_b is not None:
            a = float(self._cursor_a.value())
            b = float(self._cursor_b.value())
            self._position_v_cursor_plot_labels(a, b)
            if self._h_cursor_a is not None and self._h_cursor_b is not None:
                self._position_h_cursor_plot_labels(
                    a,
                    b,
                    float(self._h_cursor_a.value()),
                    float(self._h_cursor_b.value()),
                )
            self._avoid_cursor_label_overlaps()
        self._position_zoom_toggle_button()
        self._queue_plot_geometry_sync(force_traces=True)
        self._refresh_cursor_auxiliary_guides()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._schedule_post_layout_sync()

    def _update_readout(self) -> None:
        """更新顶部信息栏的光标读数（横向排版，不在波形上）。"""
        if self._cursor_a is None or self._cursor_b is None:
            return
        a = float(self._cursor_a.value())
        b = float(self._cursor_b.value())
        ha_div = float(self._h_cursor_a.value()) if self._h_cursor_a is not None else 0.0
        hb_div = float(self._h_cursor_b.value()) if self._h_cursor_b is not None else 0.0
        dt_us = b - a
        self._update_y_ticks()
        self._update_v_cursor_plot_labels(a, b)
        self._update_h_cursor_plot_labels(a, b, ha_div, hb_div, dt_us)
        self._sync_cursor_line_label_positions()
        self._avoid_cursor_label_overlaps()
        self._refresh_cursor_auxiliary_guides()
        if abs(dt_us) > 1e-9:
            freq_khz = 1e3 / abs(dt_us)
            freq_txt = (
                f"{freq_khz/1000:.2f} MHz" if freq_khz >= 1000 else f"{freq_khz:.2f} kHz"
            )
        else:
            freq_txt = "—"
        ca, cb = CURSOR_PEN_A, CURSOR_PEN_B
        if self._interactive_mode == "turn_on_current":
            ha_val = self._from_disp("ic", ha_div)
            hb_val = self._from_disp("ic", hb_div)
            txt = (
                f"<span style='color:{ca}'>A {a:9.3f}µs</span>&nbsp;"
                f"<span style='color:{cb}'>B {b:9.3f}µs</span>&nbsp;"
                f"Δt {dt_us:+9.3f}µs&nbsp;|&nbsp;"
                f"<span style='color:{ca}'>[Ic] Ha {ha_val:+10.2f}A</span>&nbsp;"
                f"<span style='color:{cb}'>[Ic] Hb {hb_val:+10.2f}A</span>"
            )
            self._set_readout_text(txt)
            return
        if self._interactive_mode == "energy_loss":
            ha_ch = getattr(self, "_energy_ha_channel", "vce")
            ha_u = self._unit_for_channel(ha_ch)
            ha_val = self._from_disp(ha_ch, ha_div)
            if ha_ch == "irr":
                ha_val = abs(ha_val)
            hb_ch = getattr(self, "_energy_hb_channel", "ic")
            hb_u = self._unit_for_channel(hb_ch)
            hb_val = self._from_disp(hb_ch, hb_div)
            if hb_ch == "irr":
                hb_val = abs(hb_val)
            _ch_tag = {
                "ic": "Ic",
                "vce": "Vce",
                "irr": "Irr",
                "v_diode": "Vd",
            }
            ha_tag = _ch_tag.get(ha_ch, ha_ch)
            hb_tag = _ch_tag.get(hb_ch, hb_ch)
            a_samples = self._energy_cursor_samples(a)
            b_samples = self._energy_cursor_samples(b)
            a_txt = self._energy_cursor_values_inline(a_samples) or "—"
            b_txt = self._energy_cursor_values_inline(b_samples) or "—"
            txt = (
                f"<span style='color:{ca}'>A {a:9.3f}µs</span>&nbsp;"
                f"<span style='color:{cb}'>B {b:9.3f}µs</span>&nbsp;"
                f"Δt {dt_us:+9.3f}µs&nbsp;|&nbsp;"
                f"<span style='color:{ca}'>A[{a_txt}]</span>&nbsp;"
                f"<span style='color:{cb}'>B[{b_txt}]</span>&nbsp;|&nbsp;"
                f"<span style='color:{ca}'>[{ha_tag}] Ha {ha_val:+10.2f}{ha_u}</span>&nbsp;"
                f"<span style='color:{cb}'>[{hb_tag}] Hb {hb_val:+10.2f}{hb_u}</span>"
            )
            self._set_readout_text(txt)
            return
        # Ha/Hb/Δy 按当前活动通道的真实单位显示
        ch = self._readout_channel()
        if ch not in self._trace_items:
            ch = self._axis_channel() or ch
        unit = self._unit_for_channel(ch)
        ha = self._from_disp(ch, ha_div)
        hb = self._from_disp(ch, hb_div)
        dy = hb - ha
        ch_label = self._trace_legend.get(ch, ch)
        if (
            self._slope_zero_ref_enabled
            and self._h_cursor_zero is not None
            and self._h_cursor_zero.isVisible()
        ):
            h0 = self._from_disp(ch, float(self._h_cursor_zero.value()))
            h0_txt = (
                f"<span style='color:{CURSOR_PEN_ZERO}'>"
                f"H0 {h0:+10.2f}{unit}</span>"
            )
        else:
            h0_txt = (
                "<span style='color:transparent'>"
                f"H0 {0:+10.2f}{unit}</span>"
            )
        ch_tag = ch_label if len(ch_label) <= 12 else ch_label[:11] + "…"
        txt = (
            f"<span style='color:{ca}'>A {a:9.3f}µs</span>&nbsp;"
            f"<span style='color:{cb}'>B {b:9.3f}µs</span>&nbsp;"
            f"Δt {dt_us:+9.3f}µs&nbsp;|Δt| {abs(dt_us):9.3f}µs&nbsp;"
            f"1/|Δt| {freq_txt:>10}&nbsp;|&nbsp;"
            f"<span style='color:#999999'>[{ch_tag}]</span>&nbsp;"
            f"<span style='color:{ca}'>Ha {ha:+10.2f}{unit}</span>&nbsp;"
            f"<span style='color:{cb}'>Hb {hb:+10.2f}{unit}</span>&nbsp;"
            f"{h0_txt}&nbsp;"
            f"Δy {dy:+10.2f}{unit}"
        )
        self._set_readout_text(txt)

    # ------------------------------------------------------------------ 工具 ----
    def _interp_vce(self, t_us: float) -> float:
        if self._interactive_vce_t_us is None or self._interactive_vce is None:
            return 0.0
        tt = self._interactive_vce_t_us
        vv = self._interactive_vce
        t_clamped = float(np.clip(t_us, float(tt[0]), float(tt[-1])))
        return float(np.interp(t_clamped, tt, vv))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(920, 680)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, 400)

    def disable_interactive_cursors(self) -> None:
        """退回 global 模式（光标依旧存在、可拖、显示读数）。"""
        self.clear_cursor_auxiliary_guides()
        self._interactive_on_change = None
        self._interactive_mode = "global"
        self._interactive_search_t0_us = None
        self._interactive_search_t1_us = None
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._slope_channel = None
        self._slope_zero_ref_enabled = False
        self._hide_h_cursor_zero()
        if self._h_cursor_a is not None:
            self._h_cursor_a.setMovable(True)
            self._h_cursor_a_locked = False
        if self._h_cursor_b is not None:
            self._h_cursor_b.setMovable(True)
        self._update_readout()

    # ------------------------------------------------------------------ ΔVce 模式 ----
    def enable_delta_vce_interaction(
        self,
        fixed_t_us: float,
        fixed_v: float,
        move_t_us: float,
        on_change,
        search_t0_us: float | None = None,
        search_t1_us: float | None = None,
        move_v: float | None = None,
        *,
        emit_result_on_enter: bool = False,
    ) -> None:
        self._interactive_enabled = True
        self.clear_cursor_auxiliary_guides()
        self._interactive_on_change = on_change
        self._interactive_mode = "delta_vce"
        self._active_channel = "vce"
        if search_t0_us is not None and search_t1_us is not None:
            self._interactive_search_t0_us = min(search_t0_us, search_t1_us)
            self._interactive_search_t1_us = max(search_t0_us, search_t1_us)
        else:
            self._interactive_search_t0_us = None
            self._interactive_search_t1_us = None

        if self._cursor_a is None or self._cursor_b is None or self._h_cursor_a is None or self._h_cursor_b is None:
            # 还没有持久光标——立即装一套
            self._install_persistent_cursors(fixed_t_us, move_t_us, 1.0)

        self._interactive_syncing = True
        try:
            # A、B 两根纵向光标都可拖动；各自与 Ha/Hb 横向光标联动
            self._cursor_a.setPos(fixed_t_us)
            self._cursor_a.setMovable(True)
            self._cursor_b.setPos(move_t_us)
            self._cursor_b.setMovable(True)
            # 横向光标按 Vce 通道刻度换算到显示「格」，均可拖
            self._h_cursor_a.setPos(self._to_disp("vce", fixed_v))
            self._h_cursor_a.setMovable(True)
            self._h_cursor_a_locked = False
            if move_v is None:
                move_v = self._interp_vce(move_t_us)
            self._h_cursor_b.setPos(self._to_disp("vce", move_v))
            self._h_cursor_b.setMovable(True)
        finally:
            self._interactive_syncing = False
        if emit_result_on_enter and self._interactive_on_change is not None:
            va = self._interp_vce(fixed_t_us)
            vb = self._interp_vce(move_t_us)
            delta = abs(va - vb)
            self._interactive_on_change(
                float(fixed_t_us), float(va), float(move_t_us), float(vb), float(delta)
            )
        self._update_readout()

    def _series_for_channel(self, channel: str) -> tuple[np.ndarray | None, np.ndarray | None]:
        if channel == "vce":
            return self._interactive_vce_t_us, self._interactive_vce
        if channel == "irr":
            return self._interactive_irr_t_us, self._interactive_irr
        if channel == "ic":
            return self._interactive_ic_t_us, self._interactive_ic
        if channel == "v_diode" and self._trace_t_us is not None:
            raw = self._effective_raw_for_channel(self._display_key_for_channel("v_diode"))
            if raw is not None:
                return self._trace_t_us, raw
        return None, None

    def _interp_channel(self, channel: str, t_us: float) -> float:
        if channel == "vce":
            return self._interp_vce(t_us)
        tt, vv = self._series_for_channel(channel)
        if tt is None or vv is None or len(tt) == 0:
            return 0.0
        return float(np.interp(t_us, tt, vv))

    def _nearest_time_on_waveform(
        self, channel: str, target_v: float, ref_t_us: float
    ) -> tuple[float, float]:
        tt, vv = self._series_for_channel(channel)
        if tt is None or vv is None:
            return ref_t_us, self._interp_channel(channel, ref_t_us)
        if len(tt) == 0:
            return ref_t_us, self._interp_channel(channel, ref_t_us)
        if self._interactive_search_t0_us is not None and self._interactive_search_t1_us is not None:
            mask = (tt >= self._interactive_search_t0_us) & (tt <= self._interactive_search_t1_us)
            idxs = np.where(mask)[0]
        else:
            idxs = np.arange(len(tt))
        if len(idxs) == 0:
            idxs = np.arange(len(tt))
        score = np.abs(vv[idxs] - target_v) + 0.02 * np.abs(tt[idxs] - ref_t_us)
        pick = int(idxs[int(np.argmin(score))])
        return float(tt[pick]), float(vv[pick])

    def _nearest_time_for_vce(self, target_v: float, ref_t_us: float) -> tuple[float, float]:
        return self._nearest_time_on_waveform("vce", target_v, ref_t_us)

    def _emit_delta_vce_changed(self) -> None:
        if self._cursor_a is None or self._cursor_b is None:
            return
        fixed_t_us = float(self._cursor_a.value())
        move_t_us = float(self._cursor_b.value())
        # 横向光标在显示「格」，换算回 Vce 真实电压
        if self._h_cursor_a is not None:
            fixed_v = self._from_disp("vce", float(self._h_cursor_a.value()))
        else:
            fixed_v = self._interp_vce(fixed_t_us)
        if self._h_cursor_b is not None:
            move_v = self._from_disp("vce", float(self._h_cursor_b.value()))
        else:
            move_v = self._interp_vce(move_t_us)
        # ΔVce = 两光标电压差的绝对值（A、B 对称）
        delta = abs(float(fixed_v - move_v))
        if self._interactive_on_change is not None:
            self._interactive_on_change(fixed_t_us, fixed_v, move_t_us, move_v, delta)

    # ------------------------------------------------------------------ dv/dt 模式 ----
    _BASE_TOP_SLOPE_MODES = frozenset({"dvdt", "didt"})

    def _readout_channel(self) -> str:
        if self._interactive_mode in {"turn_on_current", "short_current"}:
            return self._display_key_for_channel("ic")
        if (
            self._interactive_mode in self._BASE_TOP_SLOPE_MODES
            and self._slope_channel is not None
        ):
            return self._display_key_for_channel(self._slope_channel)
        return self._display_key_for_channel(self._active_channel)

    def _ensure_h_cursor_zero(self, channel: str, zero_v: float) -> None:
        pos = self._to_disp(channel, float(zero_v))
        if self._h_cursor_zero is None:
            line = ScopeCursorLine(
                "H0",
                pos=pos,
                angle=0,
                movable=True,
                pen=_spaced_dash_pen(REFERENCE_LINE_COLOR, 1),
                hoverPen=_spaced_dash_pen("#FFFFFF", 2),
                label="H0",
                labelOpts={
                    "color": REFERENCE_LINE_COLOR,
                    "position": 0.98,
                    "movable": False,
                    "fill": (0, 0, 0, 160),
                },
            )
            line.setZValue(51)
            self._register_auxiliary_dash_line(
                line,
                hover_color="#FFFFFF",
                hover_width=2,
            )
            self.plot.addItem(line)
            line.sigPositionChanged.connect(self._on_horizontal_cursor_moved)
            line.contextRequested.connect(self._show_cursor_context_menu)
            self._h_cursor_zero = line
        else:
            self._h_cursor_zero.setPos(pos)
            self._h_cursor_zero.setMovable(True)
            self._h_cursor_zero.show()
        self._apply_cursor_visibility()

    def _hide_h_cursor_zero(self) -> None:
        if self._h_cursor_zero is not None:
            self._h_cursor_zero.hide()

    def enable_dvdt_interaction(
        self,
        search_t0_us: float,
        search_t1_us: float,
        top_v: float,
        base_v: float,
        channel: str,
        on_change,
        *,
        mode: str = "dvdt",
        zero_v: float | None = None,
        emit_result_on_enter: bool = False,
    ) -> None:
        """dv/dt 或 di/dt：Ha=Top、Hb=Base（可拖）；RR 50%IF→50%IRM 时另加 H0 零基准。"""
        if mode not in self._BASE_TOP_SLOPE_MODES:
            mode = "dvdt"
        if search_t1_us < search_t0_us:
            search_t0_us, search_t1_us = search_t1_us, search_t0_us
        self._interactive_enabled = True
        self.clear_cursor_auxiliary_guides()
        self._interactive_on_change = on_change
        self._interactive_mode = mode
        self._slope_channel = channel
        self._active_channel = channel
        self._slope_zero_ref_enabled = zero_v is not None
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._interactive_search_t0_us = float(search_t0_us)
        self._interactive_search_t1_us = float(search_t1_us)

        mid_us = 0.5 * (search_t0_us + search_t1_us)
        if self._cursor_a is None or self._cursor_b is None:
            self._install_persistent_cursors(search_t0_us, search_t1_us, 1.0)

        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(mid_us)
            self._cursor_a.setMovable(False)
            self._cursor_b.setPos(mid_us)
            self._cursor_b.setMovable(False)
            if self._h_cursor_a is not None:
                self._h_cursor_a.setPos(self._to_disp(channel, float(top_v)))
                self._h_cursor_a.setMovable(True)
                self._h_cursor_a_locked = False
            if self._h_cursor_b is not None:
                self._h_cursor_b.setPos(self._to_disp(channel, float(base_v)))
                self._h_cursor_b.setMovable(True)
            if zero_v is not None:
                self._ensure_h_cursor_zero(channel, float(zero_v))
            else:
                self._hide_h_cursor_zero()
        finally:
            self._interactive_syncing = False
        if emit_result_on_enter:
            self._emit_dvdt_changed()

    def apply_dvdt_ab_times(self, t_a_us: float, t_b_us: float) -> None:
        """将 A/B 纵向光标设到百分比穿越时刻（左→右）。"""
        if self._cursor_a is None or self._cursor_b is None:
            return
        ta = float(t_a_us)
        tb = float(t_b_us)
        if ta > tb:
            ta, tb = tb, ta
        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(ta)
            self._cursor_b.setPos(tb)
            self._cursor_a.setMovable(False)
            self._cursor_b.setMovable(False)
        finally:
            self._interactive_syncing = False
        self._update_readout()

    def read_didt_slope_state(
        self, channel: str
    ) -> tuple[float, float, float | None] | None:
        """当前 di/dt 模式 Ha/Hb（物理量），用于再次点击时恢复手调位置。"""
        if self._interactive_mode != "didt" or self._slope_channel != channel:
            return None
        if self._h_cursor_a is None or self._h_cursor_b is None:
            return None
        ch = self._readout_channel()
        top_v = self._from_disp(ch, float(self._h_cursor_a.value()))
        base_v = self._from_disp(ch, float(self._h_cursor_b.value()))
        zero_v = None
        if self._slope_zero_ref_enabled and self._h_cursor_zero is not None:
            zero_v = self._from_disp(ch, float(self._h_cursor_zero.value()))
        return float(top_v), float(base_v), zero_v

    def _emit_dvdt_changed(self) -> None:
        if (
            self._interactive_mode not in self._BASE_TOP_SLOPE_MODES
            or self._h_cursor_a is None
            or self._h_cursor_b is None
            or self._interactive_on_change is None
        ):
            return
        ch = self._readout_channel()
        top_v = self._from_disp(ch, float(self._h_cursor_a.value()))
        base_v = self._from_disp(ch, float(self._h_cursor_b.value()))
        if self._slope_zero_ref_enabled and self._h_cursor_zero is not None:
            zero_v = self._from_disp(ch, float(self._h_cursor_zero.value()))
            self._interactive_on_change(float(top_v), float(base_v), float(zero_v))
        else:
            self._interactive_on_change(float(top_v), float(base_v))

    # ------------------------------------------------------------------ 区间模式 ----
    def enable_interval_interaction(
        self,
        start_t_us: float,
        end_t_us: float,
        on_change,
        show_horizontal_peak: bool = False,
        *,
        mode: str = "interval",
    ) -> None:
        if end_t_us < start_t_us:
            start_t_us, end_t_us = end_t_us, start_t_us
        self._interactive_enabled = True
        self.clear_cursor_auxiliary_guides()
        self._interactive_on_change = on_change
        self._interactive_mode = (
            mode
            if mode
            in {
                "interval",
                "irr_cross",
                "trr_measure",
                "irr_peak",
                "turn_on_current",
                "crosstalk",
                "power_peak",
            }
            else "interval"
        )
        self._interval_max_hline_enabled = bool(show_horizontal_peak)
        self._interval_peak_on_hb = False

        if self._cursor_a is None or self._cursor_b is None:
            self._install_persistent_cursors(start_t_us, end_t_us, 1.0)

        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(start_t_us)
            self._cursor_a.setMovable(True)
            self._cursor_b.setPos(end_t_us)
            self._cursor_b.setMovable(True)
            # Ha/Hb 仍作为通用横向测量光标可拖
            if self._h_cursor_a is not None:
                self._h_cursor_a.setMovable(True)
                self._h_cursor_a_locked = False
            if self._h_cursor_b is not None:
                self._h_cursor_b.setMovable(True)
        finally:
            self._interactive_syncing = False

        self._update_readout()

    def enable_crosstalk_interaction(
        self,
        start_t_us: float,
        end_t_us: float,
        on_change,
    ) -> None:
        """串扰电压：仅 A/B 定窗，Ha/Hb 锁定在窗内对管 Vge 最大/最小显示行。"""
        if end_t_us < start_t_us:
            start_t_us, end_t_us = end_t_us, start_t_us
        self._interactive_enabled = True
        self.clear_cursor_auxiliary_guides()
        self._interactive_on_change = on_change
        self._interactive_mode = "crosstalk"
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._active_channel = "vge_other"

        if self._cursor_a is None or self._cursor_b is None:
            self._install_persistent_cursors(start_t_us, end_t_us, 1.0)

        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(start_t_us)
            self._cursor_a.setMovable(True)
            self._cursor_b.setPos(end_t_us)
            self._cursor_b.setMovable(True)
        finally:
            self._interactive_syncing = False

        self._update_readout()

    def enable_energy_loss_interaction(
        self,
        search_t0_us: float,
        search_t1_us: float,
        t_a_us: float,
        t_b_us: float,
        ha_v: float,
        hb_a: float,
        on_change,
        *,
        edge_a: str = "rising",
        edge_b: str = "falling",
        b_channel: str = "ic",
        b_level_vce: float | None = None,
        ha_channel: str = "vce",
        hb_channel: str = "ic",
        a_channel: str | None = None,
        a_anchor_us: float | None = None,
        eon_ic_rise_a: bool = False,
        rise_a_mode: str | None = None,
        fall_a_mode: str | None = None,
        fall_b_mode: str | None = None,
        rise_b_mode: str | None = None,
        peak_channels: tuple[str, ...] | None = None,
        sync_cursors_from_levels: bool = True,
        update_result_on_enter: bool = False,
    ) -> None:
        """
        Eoff：Ha/Vce，A=Vce 与 Ha 穿越。
        Eon：Ha/Ic 抬升前平台 + A 交点；Hb/Vce 回落后平台 + B 交点。
        Err：Ha/Irr，Hb/V_二极管，A/B 为对应交点。
        """
        if search_t1_us < search_t0_us:
            search_t0_us, search_t1_us = search_t1_us, search_t0_us
        self._interactive_enabled = True
        self.clear_cursor_auxiliary_guides()
        self._interactive_on_change = on_change
        self._interactive_mode = "energy_loss"
        self._slope_channel = None
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._interactive_search_t0_us = float(search_t0_us)
        self._interactive_search_t1_us = float(search_t1_us)
        self._energy_edge_a = str(edge_a)
        self._energy_edge_b = str(edge_b)
        self._energy_b_channel = str(b_channel)
        self._energy_b_level_vce = (
            float(b_level_vce) if b_level_vce is not None else None
        )
        self._energy_ha_channel = str(ha_channel)
        self._energy_hb_channel = str(hb_channel)
        self._energy_a_channel = str(a_channel or ha_channel)
        self._energy_a_anchor_us = (
            float(a_anchor_us) if a_anchor_us is not None else None
        )
        if rise_a_mode is not None:
            self._energy_rise_a_mode = str(rise_a_mode)
        elif eon_ic_rise_a:
            self._energy_rise_a_mode = "eon_ic"
        else:
            self._energy_rise_a_mode = None
        self._energy_fall_a_mode = str(fall_a_mode) if fall_a_mode else None
        self._energy_fall_b_mode = str(fall_b_mode) if fall_b_mode else None
        self._energy_rise_b_mode = str(rise_b_mode) if rise_b_mode else None
        self._energy_peak_channels = (
            tuple(peak_channels) if peak_channels is not None else ("vce", "ic")
        )
        self._active_channel = self._energy_ha_channel

        if self._cursor_a is None or self._cursor_b is None:
            self._install_persistent_cursors(t_a_us, t_b_us, 1.0)

        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(float(t_a_us))
            self._cursor_b.setPos(float(t_b_us))
            self._cursor_a.setMovable(True)
            self._cursor_b.setMovable(True)
            if self._h_cursor_a is not None:
                self._h_cursor_a.setPos(
                    self._to_disp(self._energy_ha_channel, float(ha_v))
                )
                self._h_cursor_a.setMovable(True)
                self._h_cursor_a_locked = False
            if self._h_cursor_b is not None:
                self._h_cursor_b.setPos(
                    self._to_disp(self._energy_hb_channel, float(hb_a))
                )
                self._h_cursor_b.setMovable(True)
        finally:
            self._interactive_syncing = False
        if sync_cursors_from_levels:
            self._sync_energy_loss_cursors()
        self._update_readout()
        if update_result_on_enter:
            self._emit_energy_loss_changed()

    def _energy_crossing_us(
        self,
        channel: str,
        level: float,
        edge: str,
        t_lo_us: float,
        t_hi_us: float,
        *,
        after_us: float | None = None,
    ) -> float | None:
        tt, vv = self._series_for_channel(channel)
        if tt is None or vv is None or len(tt) < 2:
            return None
        lo, hi = (min(t_lo_us, t_hi_us), max(t_lo_us, t_hi_us))
        mask = (tt >= lo) & (tt <= hi)
        if after_us is not None:
            mask &= tt >= float(after_us)
        if not np.any(mask):
            return None
        t_seg = tt[mask].astype(np.float64)
        y_seg = np.asarray(vv[mask], dtype=np.float64)
        if channel in ("ic", "irr"):
            y_seg = np.abs(y_seg)
        from dpt_extractor.utils.signal import crossing_time

        t_cross = crossing_time(t_seg, y_seg, float(level), edge, start=0)
        return float(t_cross) if t_cross is not None else None

    def _rise_crossing_us_on_channel(
        self,
        channel: str,
        level: float,
        t_lo_us: float,
        t_hi_us: float,
        anchor_us: float | None,
        *,
        use_rise_index: bool,
    ) -> float | None:
        """在 channel 上用平台上升沿防抖找 A（与 Eon/Eoff/Err 算法一致）。"""
        tt, vv = self._series_for_channel(channel)
        if tt is None or vv is None or len(tt) < 2:
            return None
        lo, hi = (min(t_lo_us, t_hi_us), max(t_lo_us, t_hi_us))
        mask = (tt >= lo) & (tt <= hi)
        if anchor_us is not None:
            mask &= tt >= float(anchor_us)
        if not np.any(mask):
            return None
        t_seg = tt[mask].astype(np.float64)
        y_seg = np.asarray(vv[mask], dtype=np.float64)
        if channel == "irr":
            y_seg = np.abs(y_seg)
        anchor = 0
        if anchor_us is not None:
            anchor = int(np.searchsorted(t_seg, float(anchor_us), side="left"))
            anchor = max(0, min(anchor, len(y_seg) - 2))
        if use_rise_index:
            from dpt_extractor.metrics.iec_windows import (
                _eon_ic_rise_crossing_at_main_rise,
                _eoff_vce_ha_crossing_at_main_rise,
            )

            y_top = float(np.max(y_seg)) if len(y_seg) else float(level)
            if self._energy_rise_a_mode == "eoff_vce":
                _, t_cross = _eoff_vce_ha_crossing_at_main_rise(
                    t_seg, y_seg, float(level), self._interactive_dt, y_top
                )
                return float(t_cross)
            else:
                _, t_cross = _eon_ic_rise_crossing_at_main_rise(
                    t_seg,
                    y_seg,
                    float(level),
                    anchor,
                    self._interactive_dt,
                    y_top,
                )
                return float(t_cross)
        from dpt_extractor.utils.signal import crossing_time

        t_cross = crossing_time(t_seg, y_seg, float(level), "rising", start=anchor)
        return float(t_cross) if t_cross is not None else None

    def _eon_ic_rise_crossing_us(
        self,
        ha_ic: float,
        t_lo_us: float,
        t_hi_us: float,
        anchor_us: float | None,
    ) -> float | None:
        """Eon：|Ic| 主上升沿与 Ha 的第一个有效交点（与算法默认一致）。"""
        return self._rise_crossing_us_on_channel(
            "ic", ha_ic, t_lo_us, t_hi_us, anchor_us, use_rise_index=True
        )

    def _eoff_vce_rise_crossing_us(
        self,
        ha_v: float,
        t_lo_us: float,
        t_hi_us: float,
        anchor_us: float | None,
    ) -> float | None:
        return self._rise_crossing_us_on_channel(
            "vce", ha_v, t_lo_us, t_hi_us, anchor_us, use_rise_index=True
        )

    def _err_irr_rise_crossing_us(
        self,
        ha_a: float,
        t_lo_us: float,
        t_hi_us: float,
        anchor_us: float | None,
    ) -> float | None:
        return self._rise_crossing_us_on_channel(
            "irr", ha_a, t_lo_us, t_hi_us, anchor_us, use_rise_index=True
        )

    def _err_irr_fall_crossing_us(
        self,
        ha_a: float,
        t_lo_us: float,
        t_hi_us: float,
        peak_us: float | None,
    ) -> float | None:
        """Err：Irm 主峰后稳定 base 附近与 Ha 的真实交点（与算法一致）。"""
        from dpt_extractor.metrics.iec_windows import (
            _err_irr_fall_cross_ha_t,
            _err_recovery_settled_base,
            err_recovery_peak_index,
        )

        tt, vv = self._series_for_channel("irr")
        if tt is None or vv is None or len(tt) < 2:
            return None
        lo, hi = (min(t_lo_us, t_hi_us), max(t_lo_us, t_hi_us))
        mask = (tt >= lo) & (tt <= hi)
        if not np.any(mask):
            return None
        t_seg = (tt[mask] * 1e-6).astype(np.float64)
        y_seg = np.asarray(vv[mask], dtype=np.float64)
        if peak_us is not None:
            ipk_g = int(np.searchsorted(t_seg, float(peak_us) * 1e-6, side="left"))
            ipk_g = max(0, min(ipk_g, len(y_seg) - 2))
        else:
            ipk_g = err_recovery_peak_index(np.abs(y_seg), self._interactive_dt)
        i1 = int(np.searchsorted(t_seg, hi * 1e-6, side="right"))
        i1 = max(ipk_g + 2, min(i1, len(y_seg) - 1))
        peak = float(y_seg[ipk_g]) if ipk_g < len(y_seg) else 0.0
        force_signed = peak > 0.0 and float(ha_a) < 0.0
        base = _err_recovery_settled_base(y_seg, ipk_g, self._interactive_dt, i1)
        t_cross = _err_irr_fall_cross_ha_t(
            t_seg,
            y_seg,
            float(ha_a),
            ipk_g,
            i1,
            self._interactive_dt,
            force_signed=force_signed,
            settle_idx=base.start_idx,
            settle_end_idx=base.end_idx,
        )
        return float(t_cross) * 1e6

    def _err_vd_rise_crossing_us(
        self,
        hb_v: float,
        t_lo_us: float,
        t_hi_us: float,
        peak_us: float | None,
    ) -> float | None:
        """Err：Vd 主上升沿第一次穿 Hb 的交点。"""
        from dpt_extractor.metrics.iec_windows import (
            _err_vd_rise_cross_hb_t,
            err_recovery_peak_index,
        )

        tt, vv = self._series_for_channel("v_diode")
        if tt is None or vv is None or len(tt) < 2:
            return None
        lo, hi = (min(t_lo_us, t_hi_us), max(t_lo_us, t_hi_us))
        mask = (tt >= lo) & (tt <= hi)
        if not np.any(mask):
            return None
        t_s = (tt[mask] * 1e-6).astype(np.float64)
        y_seg = np.asarray(vv[mask], dtype=np.float64)
        i0_seg = int(np.searchsorted(t_s, lo * 1e-6, side="left"))
        if peak_us is not None:
            ipk_g = int(np.searchsorted(t_s, float(peak_us) * 1e-6, side="left"))
            ipk_g = max(0, min(ipk_g, len(t_s) - 2))
        else:
            ipk_g = err_recovery_peak_index(np.abs(y_seg), self._interactive_dt)
        t_cross = _err_vd_rise_cross_hb_t(
            t_s, y_seg, float(hb_v), ipk_g, i0_seg, self._interactive_dt
        )
        return float(t_cross) * 1e6

    def _fall_crossing_us_on_channel(
        self,
        channel: str,
        level: float,
        t_lo_us: float,
        t_hi_us: float,
        after_us: float,
        *,
        use_fall_index: bool,
    ) -> float | None:
        tt, vv = self._series_for_channel(channel)
        if tt is None or vv is None or len(tt) < 2:
            return None
        lo, hi = (min(t_lo_us, t_hi_us), max(t_lo_us, t_hi_us))
        mask = (tt >= lo) & (tt <= hi) & (tt >= float(after_us))
        if not np.any(mask):
            return None
        t_seg = tt[mask].astype(np.float64)
        y_seg = np.asarray(vv[mask], dtype=np.float64)
        if channel == "irr":
            y_seg = np.abs(y_seg)
        anchor = 0
        if use_fall_index and self._energy_fall_b_mode == "eoff_ic_fall":
            from dpt_extractor.metrics.iec_windows import (
                _eoff_ic_fall_crossing_at_main_fall,
            )

            y_top = float(np.max(y_seg)) if len(y_seg) else float(level)
            _, t_cross = _eoff_ic_fall_crossing_at_main_fall(
                t_seg,
                y_seg,
                float(level),
                anchor,
                self._interactive_dt,
                y_top,
            )
            return float(t_cross)
        elif use_fall_index and self._energy_fall_b_mode == "eon_vce_fall":
            from dpt_extractor.metrics.iec_windows import (
                _eon_vce_hb_fall_crossing_at_main_fall,
            )

            y_top = float(np.max(y_seg)) if len(y_seg) else float(level)
            _, t_cross = _eon_vce_hb_fall_crossing_at_main_fall(
                t_seg,
                y_seg,
                float(level),
                anchor,
                self._interactive_dt,
                y_top,
            )
            return float(t_cross)
        from dpt_extractor.utils.signal import crossing_time

        t_cross = crossing_time(t_seg, y_seg, float(level), "falling", start=0)
        return float(t_cross) if t_cross is not None else None

    def _eoff_ic_fall_crossing_us(
        self,
        hb_a: float,
        t_lo_us: float,
        t_hi_us: float,
        after_us: float,
    ) -> float | None:
        return self._fall_crossing_us_on_channel(
            "ic", hb_a, t_lo_us, t_hi_us, after_us, use_fall_index=True
        )

    def _eon_vce_fall_crossing_us(
        self,
        hb_v: float,
        t_lo_us: float,
        t_hi_us: float,
        after_us: float,
    ) -> float | None:
        """Eon：Vce 主下降沿与 Hb 的第一个有效交点（与 eon_energy_markers 一致）。"""
        return self._fall_crossing_us_on_channel(
            "vce", hb_v, t_lo_us, t_hi_us, after_us, use_fall_index=True
        )

    def _energy_irr_a_uses_magnitude(self, ha_a: float) -> bool:
        """Err 正向软恢复时，A 用 |Irr| 与 |Ha| 的交点。"""
        if self._energy_fall_a_mode != "err_irr" or self._energy_a_channel != "irr":
            return False
        tt, vv = self._series_for_channel("irr")
        if tt is None or vv is None or len(tt) == 0:
            return False
        if self._energy_a_anchor_us is not None:
            idx = int(np.searchsorted(tt, float(self._energy_a_anchor_us), side="left"))
            idx = max(0, min(idx, len(vv) - 1))
        else:
            idx = int(np.argmax(np.abs(vv)))
        peak = float(vv[idx])
        return peak > 0.0 and float(ha_a) > 0.0

    def _handle_energy_loss_vertical_moved(self) -> None:
        self._emit_energy_loss_changed()
        self._update_readout()

    def _sync_energy_a_from_ha(self) -> float | None:
        """拖动 Ha：A 跟随与 Ha 的穿越点（横向→纵向）。返回 A 时刻 µs。"""
        if self._cursor_a is None or self._h_cursor_a is None:
            return None
        t_lo = float(self._interactive_search_t0_us or 0.0)
        t_hi = float(self._interactive_search_t1_us or t_lo + 1.0)
        ha_ch = self._energy_ha_channel
        ha_lvl = float(self._from_disp(ha_ch, float(self._h_cursor_a.value())))
        a_anchor = self._energy_a_anchor_us
        if self._energy_fall_a_mode == "err_irr" and self._energy_a_channel == "irr":
            ta = self._err_irr_fall_crossing_us(ha_lvl, t_lo, t_hi, a_anchor)
        elif self._energy_rise_a_mode == "eon_ic" and self._energy_a_channel == "ic":
            ta = self._eon_ic_rise_crossing_us(ha_lvl, t_lo, t_hi, a_anchor)
        elif self._energy_rise_a_mode == "eoff_vce" and self._energy_a_channel == "vce":
            ta = self._eoff_vce_rise_crossing_us(ha_lvl, t_lo, t_hi, a_anchor)
        elif self._energy_rise_a_mode == "err_irr" and self._energy_a_channel == "irr":
            ta = self._err_irr_rise_crossing_us(ha_lvl, t_lo, t_hi, a_anchor)
        else:
            if ha_ch == "irr":
                ha_lvl = abs(ha_lvl)
            ta = self._energy_crossing_us(
                self._energy_a_channel,
                ha_lvl,
                self._energy_edge_a,
                t_lo,
                t_hi,
                after_us=a_anchor,
            )
        if ta is None:
            ta = float(self._cursor_a.value())
        self._cursor_a.setPos(float(ta))
        return float(ta)

    def _sync_energy_b_from_hb(self, ta_us: float | None = None) -> None:
        """拖动 Hb：B 跟随与 Hb 的穿越点（横向→纵向）。"""
        if self._cursor_b is None or self._h_cursor_b is None:
            return
        t_lo = float(self._interactive_search_t0_us or 0.0)
        t_hi = float(self._interactive_search_t1_us or t_lo + 1.0)
        hb_ch = self._energy_hb_channel
        hb_lvl = float(self._from_disp(hb_ch, float(self._h_cursor_b.value())))
        if hb_ch == "irr":
            hb_lvl = abs(hb_lvl)
        if ta_us is None:
            ta_us = float(self._cursor_a.value()) if self._cursor_a is not None else t_lo
        b_ch = self._energy_b_channel
        if b_ch in ("vce", "v_diode"):
            b_lvl = hb_lvl
        elif self._energy_b_level_vce is not None:
            b_lvl = float(self._energy_b_level_vce)
            b_ch = "vce"
        else:
            b_lvl = hb_lvl
            b_ch = "ic"
        if self._energy_rise_b_mode == "err_vd" and b_ch in ("vce", "v_diode"):
            peak_us = self._energy_a_anchor_us
            tb = self._err_vd_rise_crossing_us(hb_lvl, t_lo, t_hi, peak_us)
        elif self._energy_fall_b_mode == "eoff_ic_fall" and b_ch == "ic":
            tb = self._eoff_ic_fall_crossing_us(hb_lvl, t_lo, t_hi, float(ta_us))
        elif self._energy_fall_b_mode == "eon_vce_fall" and b_ch in ("vce", "v_diode"):
            tb = self._eon_vce_fall_crossing_us(hb_lvl, t_lo, t_hi, float(ta_us))
        else:
            tb = self._energy_crossing_us(
                b_ch, b_lvl, self._energy_edge_b, t_lo, t_hi, after_us=ta_us
            )
        if tb is None:
            tb = float(self._cursor_b.value())
        if self._energy_rise_b_mode != "err_vd" and tb <= ta_us:
            tb = float(ta_us) + 0.01
        self._cursor_b.setPos(float(tb))

    def _sync_energy_loss_cursors(self) -> None:
        if (
            self._cursor_a is None
            or self._cursor_b is None
            or self._h_cursor_a is None
            or self._h_cursor_b is None
        ):
            return
        self._interactive_syncing = True
        try:
            ta = self._sync_energy_a_from_ha()
            self._sync_energy_b_from_hb(ta)
        finally:
            self._interactive_syncing = False

    def _emit_energy_loss_changed(self) -> None:
        if self._interactive_on_change is None:
            return
        if (
            self._cursor_a is None
            or self._cursor_b is None
            or self._h_cursor_a is None
            or self._h_cursor_b is None
        ):
            return
        ha_ch = self._energy_ha_channel
        ha_v = float(self._from_disp(ha_ch, float(self._h_cursor_a.value())))
        if ha_ch == "irr" and self._energy_fall_a_mode != "err_irr":
            ha_v = abs(ha_v)
        hb_ch = self._energy_hb_channel
        hb_v = float(self._from_disp(hb_ch, float(self._h_cursor_b.value())))
        if hb_ch == "irr":
            hb_v = abs(hb_v)
        ta = float(self._cursor_a.value())
        tb = float(self._cursor_b.value())
        self._interactive_on_change(ta, tb, ha_v, hb_v)

    def _peak_plot_y_in_window(
        self,
        channel: str,
        t0_us: float,
        t1_us: float,
        *,
        use_abs: bool = False,
    ) -> float | None:
        """A-B 窗口内全采样曲线峰值的显示坐标，与参数计算数据源一致。"""
        point = self._peak_plot_point_in_window(
            channel, t0_us, t1_us, use_abs=use_abs
        )
        if point is None:
            return None
        _t_us, _value, y_disp = point
        return y_disp

    def _peak_plot_point_in_window(
        self,
        channel: str,
        t0_us: float,
        t1_us: float,
        *,
        use_abs: bool = False,
        display_abs: bool = False,
    ) -> tuple[float, float, float] | None:
        """A-B 窗口内峰值点: (时间 µs, 显示/读数值, 显示 Y)。"""
        channel = self._display_key_for_channel(channel)
        tt = self._trace_t_us
        raw = self._effective_raw_for_channel(channel)
        if tt is None or raw is None or len(tt) == 0:
            return None
        t_lo, t_hi = (min(t0_us, t1_us), max(t0_us, t1_us))
        mask = (tt >= t_lo) & (tt <= t_hi)
        if not np.any(mask):
            return None
        idxs = np.where(mask)[0]
        seg = np.asarray(raw[mask], dtype=np.float64)
        try:
            if use_abs:
                local_idx = int(np.nanargmax(np.abs(seg)))
            else:
                local_idx = int(np.nanargmax(seg))
        except ValueError:
            return None
        idx = int(idxs[local_idx])
        value = float(np.asarray(raw, dtype=np.float64)[idx])
        if display_abs:
            value = abs(value)
        return float(tt[idx]), value, float(self._to_disp(channel, value))

    def _min_plot_y_in_window(
        self, channel: str, t0_us: float, t1_us: float
    ) -> float | None:
        """A-B 窗口内全采样曲线谷值的显示坐标，与参数计算数据源一致。"""
        point = self._min_plot_point_in_window(channel, t0_us, t1_us)
        if point is None:
            return None
        _t_us, _value, y_disp = point
        return y_disp

    def _min_plot_point_in_window(
        self, channel: str, t0_us: float, t1_us: float
    ) -> tuple[float, float, float] | None:
        """A-B 窗口内谷值点: (时间 µs, 原始值, 显示 Y)。"""
        channel = self._display_key_for_channel(channel)
        tt = self._trace_t_us
        raw = self._effective_raw_for_channel(channel)
        if tt is None or raw is None or len(tt) == 0:
            return None
        t_lo, t_hi = (min(t0_us, t1_us), max(t0_us, t1_us))
        mask = (tt >= t_lo) & (tt <= t_hi)
        if not np.any(mask):
            return None
        idxs = np.where(mask)[0]
        seg = np.asarray(raw[mask], dtype=np.float64)
        try:
            local_idx = int(np.nanargmin(seg))
        except ValueError:
            return None
        idx = int(idxs[local_idx])
        value = float(np.asarray(raw, dtype=np.float64)[idx])
        return float(tt[idx]), value, float(self._to_disp(channel, value))

    def set_interval_peak_horizontal(
        self,
        y: float,
        channel: str = "ic",
        *,
        t0_us: float | None = None,
        t1_us: float | None = None,
        use_abs_peak: bool = False,
        display_abs_peak: bool = False,
    ) -> None:
        """interval-peak 模式下把 Ha 设到 A-B 窗内峰值（与全采样波形对齐）。"""
        if not self._interval_max_hline_enabled or self._interval_peak_on_hb:
            return
        if self._h_cursor_a is None:
            return
        self._active_channel = channel
        y_disp = self._to_disp(channel, float(y))
        if t0_us is not None and t1_us is not None:
            plot_peak = self._peak_plot_point_in_window(
                channel,
                t0_us,
                t1_us,
                use_abs=use_abs_peak,
                display_abs=display_abs_peak,
            )
            if plot_peak is not None:
                peak_t_us, peak_value, y_disp = plot_peak
                self.set_cursor_auxiliary_point(channel, peak_t_us, peak_value)
            else:
                self.clear_cursor_auxiliary_guides()
        self._interactive_syncing = True
        try:
            self._h_cursor_a.setPos(y_disp)
            self._h_cursor_a.setMovable(True)
            self._h_cursor_a_locked = False
        finally:
            self._interactive_syncing = False
        self._update_readout()

    def set_interval_base_horizontal(self, y: float, channel: str = "ic") -> None:
        """interval-peak 模式下把 Hb 设到基准电平。"""
        if not self._interval_max_hline_enabled or self._h_cursor_b is None:
            return
        self._active_channel = channel
        self._interactive_syncing = True
        try:
            self._h_cursor_b.setPos(self._to_disp(channel, float(y)))
            self._h_cursor_b.setMovable(True)
        finally:
            self._interactive_syncing = False
        self._update_readout()

    def set_interval_peak_on_hb(
        self,
        y: float,
        channel: str = "irr",
        *,
        t0_us: float | None = None,
        t1_us: float | None = None,
        use_abs_peak: bool = False,
    ) -> None:
        """Irr 模式：Hb 自动跟 A/B 区间内最大值（不可手拖）。"""
        if self._h_cursor_b is None:
            return
        self._active_channel = channel
        y_disp = self._to_disp(channel, float(y))
        if t0_us is not None and t1_us is not None:
            plot_peak = self._peak_plot_point_in_window(
                channel, t0_us, t1_us, use_abs=use_abs_peak
            )
            if plot_peak is not None:
                peak_t_us, peak_value, y_disp = plot_peak
                self.set_cursor_auxiliary_point(channel, peak_t_us, peak_value)
            else:
                self.clear_cursor_auxiliary_guides()
        self._interactive_syncing = True
        try:
            self._h_cursor_b.setPos(y_disp)
            self._h_cursor_b.setMovable(False)
        finally:
            self._interactive_syncing = False
        self._update_readout()

    def enable_turn_on_current_interaction(
        self,
        t_a_us: float,
        t_search_end_us: float,
        t_b_us: float,
        hb: float,
        ha: float,
        on_change,
        *,
        emit_result_on_enter: bool = False,
    ) -> None:
        """开通电流：Hb↔A、Ha↔B 双向吸附交汇；Hb/Ha 为 |Ic| 平台电平。"""
        t_lo = min(t_a_us, t_search_end_us)
        t_hi = max(t_a_us, t_search_end_us)
        self._interactive_enabled = True
        self.clear_cursor_auxiliary_guides()
        self._interactive_on_change = on_change
        self._interactive_mode = "turn_on_current"
        self._active_channel = "ic"
        self._slope_channel = "ic"
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._interactive_search_t0_us = t_lo
        self._interactive_search_t1_us = t_hi

        if self._cursor_a is None or self._cursor_b is None:
            self._install_persistent_cursors(t_a_us, t_b_us, 1.0)

        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(float(t_a_us))
            self._cursor_a.setMovable(True)
            self._cursor_b.setPos(float(t_b_us))
            self._cursor_b.setMovable(True)
            if self._h_cursor_a is not None:
                self._h_cursor_a.setPos(self._to_disp("ic", float(ha)))
                self._h_cursor_a.setMovable(True)
            if self._h_cursor_b is not None:
                self._h_cursor_b.setPos(self._to_disp("ic", float(hb)))
                self._h_cursor_b.setMovable(True)
            if self._h_cursor_a is not None:
                self._h_cursor_a_locked = False
        finally:
            self._interactive_syncing = False
        self._interactive_syncing = True
        try:
            self._link_turn_on_current_from_horizontal("both")
        finally:
            self._interactive_syncing = False
        self._update_readout()
        if emit_result_on_enter:
            self._emit_turn_on_current_changed()

    def sync_turn_on_current_cursors(
        self,
        t_a_us: float,
        t_b_us: float,
        hb: float,
        ha: float,
    ) -> None:
        if self._interactive_mode != "turn_on_current":
            return
        self._interactive_syncing = True
        try:
            if self._cursor_a is not None:
                self._cursor_a.setPos(float(t_a_us))
            if self._cursor_b is not None:
                self._cursor_b.setPos(float(t_b_us))
            if self._h_cursor_a is not None:
                self._h_cursor_a.setPos(self._to_disp("ic", float(ha)))
            if self._h_cursor_b is not None:
                self._h_cursor_b.setPos(self._to_disp("ic", float(hb)))
        finally:
            self._interactive_syncing = False
        self._update_readout()

    def _ic_at_t_us(self, t_us: float) -> float:
        # 带符号：下桥导通前基线为负，光标须贴真实波形而非 |Ic|
        return float(self._interp_channel("ic", float(t_us)))

    def _turn_on_ic_dt_s(self) -> float:
        tt = self._interactive_ic_t_us
        if tt is not None and len(tt) > 1:
            return float(np.median(np.diff(tt))) * 1e-6
        return 8e-8

    def _turn_on_ic_search_slice(self) -> tuple[np.ndarray, np.ndarray, int, int]:
        tt = self._interactive_ic_t_us
        ic = self._interactive_ic
        if tt is None or ic is None or len(tt) < 2:
            return np.array([0.0]), np.array([0.0]), 0, 0
        t_s = np.asarray(tt, dtype=np.float64) * 1e-6
        ic_abs = np.asarray(ic, dtype=np.float64)
        t0 = float(self._interactive_search_t0_us)
        t1 = float(self._interactive_search_t1_us)
        i0 = int(np.searchsorted(tt, min(t0, t1)))
        i1 = int(np.searchsorted(tt, max(t0, t1)))
        i0 = max(0, min(i0, len(tt) - 2))
        i1 = max(i0 + 1, min(i1, len(tt) - 1))
        return t_s, ic_abs, i0, i1

    def _turn_on_ab_cross_us(self, hb: float, ha: float) -> tuple[float, float]:
        from dpt_extractor.metrics.plateau_level import (
            turn_on_ic_a_cross_hb_us,
            turn_on_ic_b_cross_ha_us,
        )

        t_s, ic_abs, i0, i1 = self._turn_on_ic_search_slice()
        dt = self._turn_on_ic_dt_s()
        t_a = turn_on_ic_a_cross_hb_us(t_s, ic_abs, i0, i1, hb, dt)
        t_b = turn_on_ic_b_cross_ha_us(t_s, ic_abs, i0, i1, ha, dt)
        return float(t_a), float(t_b)

    def _link_turn_on_current_from_vertical(self, which: str) -> None:
        """拖 A/B：Hb/Ha 随 Ic@该时刻移动（同 ΔVce），不吸回纵线位置以便手调。"""
        if self._h_cursor_a is None or self._h_cursor_b is None:
            return
        t_a = t_b = None
        if which in ("a", "both") and self._cursor_a is not None:
            t_a = float(self._cursor_a.value())
            self._h_cursor_b.setPos(self._to_disp("ic", self._ic_at_t_us(t_a)))
        if which in ("b", "both") and self._cursor_b is not None:
            t_b = float(self._cursor_b.value())
            self._h_cursor_a.setPos(self._to_disp("ic", self._ic_at_t_us(t_b)))

    def _link_turn_on_current_from_horizontal(self, which: str) -> None:
        """横光标 Hb→A 上升沿首交点，Ha→B 平稳段首交点（保持 Hb/Ha 电平）。"""
        if self._h_cursor_a is None or self._h_cursor_b is None:
            return
        hb = float(self._from_disp("ic", float(self._h_cursor_b.value())))
        ha = float(self._from_disp("ic", float(self._h_cursor_a.value())))
        t_a, t_b = self._turn_on_ab_cross_us(hb, ha)
        if which in ("hb", "both") and self._cursor_a is not None:
            self._cursor_a.setPos(t_a)
            self._h_cursor_b.setPos(self._to_disp("ic", self._ic_at_t_us(t_a)))
        if which in ("ha", "both") and self._cursor_b is not None:
            self._cursor_b.setPos(t_b)
            self._h_cursor_a.setPos(self._to_disp("ic", self._ic_at_t_us(t_b)))

    def _emit_turn_on_current_changed(self) -> None:
        if self._interactive_on_change is None:
            return
        if (
            self._cursor_a is None
            or self._cursor_b is None
            or self._h_cursor_a is None
            or self._h_cursor_b is None
        ):
            return
        ha = float(self._from_disp("ic", float(self._h_cursor_a.value())))
        hb = float(self._from_disp("ic", float(self._h_cursor_b.value())))
        ta = float(self._cursor_a.value())
        tb = float(self._cursor_b.value())
        self._interactive_on_change(ta, tb, hb, ha)

    def enable_short_current_interaction(
        self,
        search_t0_us: float,
        search_t1_us: float,
        t_a_us: float,
        t_b_us: float,
        hb: float,
        ha: float,
        on_change,
        *,
        channel: str = "ic",
        emit_result_on_enter: bool = False,
    ) -> None:
        """短路电流/Tsc：Hb 与电流交点联动 A/B，Ha 保持窗口内电流最大值。"""
        lo = min(float(search_t0_us), float(search_t1_us), float(t_a_us), float(t_b_us))
        hi = max(float(search_t0_us), float(search_t1_us), float(t_a_us), float(t_b_us))
        self._interactive_enabled = True
        self.clear_cursor_auxiliary_guides()
        self._interactive_on_change = on_change
        self._interactive_mode = "short_current"
        self._active_channel = channel
        self._slope_channel = channel
        self._interval_max_hline_enabled = True
        self._interval_peak_on_hb = False
        self._interactive_search_t0_us = lo
        self._interactive_search_t1_us = hi

        if self._cursor_a is None or self._cursor_b is None:
            self._install_persistent_cursors(t_a_us, t_b_us, 1.0)

        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(float(t_a_us))
            self._cursor_a.setMovable(True)
            self._cursor_b.setPos(float(t_b_us))
            self._cursor_b.setMovable(True)
            if self._h_cursor_a is not None:
                self._h_cursor_a.setPos(self._to_disp(channel, float(ha)))
                self._h_cursor_a.setMovable(False)
                self._h_cursor_a_locked = True
            if self._h_cursor_b is not None:
                self._h_cursor_b.setPos(self._to_disp(channel, float(hb)))
                self._h_cursor_b.setMovable(True)
        finally:
            self._interactive_syncing = False
        self.set_cursor_auxiliary_point(channel, float(t_b_us), float(ha))
        self._update_readout()
        if emit_result_on_enter:
            self._emit_short_current_changed()

    def _short_current_search_slice(
        self, channel: str
    ) -> tuple[np.ndarray, np.ndarray] | None:
        tt, yy = self._series_for_channel(channel)
        if tt is None or yy is None or len(tt) < 4:
            return None
        lo = (
            float(self._interactive_search_t0_us)
            if self._interactive_search_t0_us is not None
            else float(np.nanmin(tt))
        )
        hi = (
            float(self._interactive_search_t1_us)
            if self._interactive_search_t1_us is not None
            else float(np.nanmax(tt))
        )
        if hi < lo:
            lo, hi = hi, lo
        mask = (tt >= lo) & (tt <= hi)
        idx = np.where(mask)[0]
        if len(idx) < 4:
            idx = np.arange(len(tt))
        return np.asarray(tt[idx], dtype=np.float64), np.asarray(yy[idx], dtype=np.float64)

    @staticmethod
    def _interp_crossing_time_us(
        t0: float,
        y0: float,
        t1: float,
        y1: float,
        level: float,
    ) -> float:
        dy = float(y1) - float(y0)
        if abs(dy) < 1e-30:
            return float(t0)
        frac = (float(level) - float(y0)) / dy
        frac = max(0.0, min(1.0, frac))
        return float(t0) + frac * (float(t1) - float(t0))

    def _short_current_crossings_for_hb(
        self, channel: str, hb: float
    ) -> tuple[float, float, float, float] | None:
        sliced = self._short_current_search_slice(channel)
        if sliced is None:
            return None
        tt, yy = sliced
        finite = np.isfinite(tt) & np.isfinite(yy)
        tt = tt[finite]
        yy = yy[finite]
        if len(tt) < 4:
            return None
        peak_idx = int(np.nanargmax(yy))
        if peak_idx <= 0 or peak_idx >= len(yy) - 1:
            return None
        ha = float(np.nanmax(yy))
        rise_idx: int | None = None
        for idx in range(0, peak_idx):
            if float(yy[idx]) <= hb <= float(yy[idx + 1]):
                rise_idx = idx
                break
        fall_idx: int | None = None
        for idx in range(peak_idx, len(yy) - 1):
            if float(yy[idx]) >= hb >= float(yy[idx + 1]):
                fall_idx = idx
                break
        if rise_idx is None or fall_idx is None:
            return None
        ta = self._interp_crossing_time_us(
            tt[rise_idx], yy[rise_idx], tt[rise_idx + 1], yy[rise_idx + 1], hb
        )
        tb = self._interp_crossing_time_us(
            tt[fall_idx], yy[fall_idx], tt[fall_idx + 1], yy[fall_idx + 1], hb
        )
        if tb <= ta:
            return None
        return ta, tb, float(hb), ha

    def _sync_short_current_from_hb(self) -> None:
        if (
            self._h_cursor_b is None
            or self._cursor_a is None
            or self._cursor_b is None
        ):
            return
        channel = self._active_channel or "ic"
        hb = float(self._from_disp(channel, float(self._h_cursor_b.value())))
        crosses = self._short_current_crossings_for_hb(channel, hb)
        if crosses is None:
            return
        ta, tb, hb, ha = crosses
        self._cursor_a.setPos(float(ta))
        self._cursor_b.setPos(float(tb))
        if self._h_cursor_a is not None:
            self._h_cursor_a.setPos(self._to_disp(channel, float(ha)))
            self._h_cursor_a.setMovable(False)
            self._h_cursor_a_locked = True
        self.set_cursor_auxiliary_point(channel, float(tb), float(ha))

    def _sync_short_current_peak_from_window(self) -> None:
        if (
            self._cursor_a is None
            or self._cursor_b is None
            or self._h_cursor_a is None
        ):
            return
        channel = self._active_channel or "ic"
        tt, yy = self._series_for_channel(channel)
        if tt is None or yy is None or len(tt) == 0:
            return
        lo = min(float(self._cursor_a.value()), float(self._cursor_b.value()))
        hi = max(float(self._cursor_a.value()), float(self._cursor_b.value()))
        mask = (tt >= lo) & (tt <= hi)
        if not np.any(mask):
            return
        idxs = np.where(mask)[0]
        seg = np.asarray(yy[idxs], dtype=np.float64)
        if len(seg) == 0 or not np.isfinite(seg).any():
            return
        local = int(np.nanargmax(seg))
        peak_idx = int(idxs[local])
        ha = float(yy[peak_idx])
        self._h_cursor_a.setPos(self._to_disp(channel, ha))
        self._h_cursor_a.setMovable(False)
        self._h_cursor_a_locked = True
        self.set_cursor_auxiliary_point(channel, float(tt[peak_idx]), ha)

    def _emit_short_current_changed(self) -> None:
        if self._interactive_on_change is None:
            return
        if (
            self._cursor_a is None
            or self._cursor_b is None
            or self._h_cursor_a is None
            or self._h_cursor_b is None
        ):
            return
        channel = self._active_channel or "ic"
        ta = float(self._cursor_a.value())
        tb = float(self._cursor_b.value())
        hb = float(self._from_disp(channel, float(self._h_cursor_b.value())))
        ha = float(self._from_disp(channel, float(self._h_cursor_a.value())))
        self._interactive_on_change(ta, tb, hb, ha)

    def enable_irr_peak_interaction(
        self,
        start_t_us: float,
        end_t_us: float,
        on_change,
    ) -> None:
        """Irr：拖动 A/B，Hb 随区间内最大值变化。"""
        if end_t_us < start_t_us:
            start_t_us, end_t_us = end_t_us, start_t_us
        self._interactive_enabled = True
        self.clear_cursor_auxiliary_guides()
        self._interactive_on_change = on_change
        self._interactive_mode = "irr_peak"
        self._active_channel = "irr"
        self._slope_channel = None
        self._interval_max_hline_enabled = True
        self._interval_peak_on_hb = True

        if self._cursor_a is None or self._cursor_b is None:
            self._install_persistent_cursors(start_t_us, end_t_us, 1.0)

        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(start_t_us)
            self._cursor_a.setMovable(True)
            self._cursor_b.setPos(end_t_us)
            self._cursor_b.setMovable(True)
            if self._h_cursor_a is not None:
                self._h_cursor_a.setMovable(True)
            if self._h_cursor_b is not None:
                self._h_cursor_b.setMovable(False)
        finally:
            self._interactive_syncing = False
        self._update_readout()

    def _crossings_with_level(
        self,
        channel: str,
        level: float,
        t0_us: float,
        t1_us: float,
    ) -> tuple[float, float] | None:
        tt, vv = self._series_for_channel(channel)
        if tt is None or vv is None or len(tt) < 4:
            return None
        lo, hi = (float(t0_us), float(t1_us)) if t0_us <= t1_us else (float(t1_us), float(t0_us))
        mask = (tt >= lo) & (tt <= hi)
        idx = np.where(mask)[0]
        if len(idx) < 4:
            return None
        ts = tt[idx]
        ys = vv[idx]
        ipk = int(np.argmax(ys))
        if ipk <= 0 or ipk >= len(ys) - 1:
            return None

        ja = None
        for j in range(0, ipk):
            if ys[j] <= level <= ys[j + 1]:
                ja = j
        if ja is None:
            return None
        jb = None
        for j in range(ipk, len(ys) - 1):
            if ys[j] >= level >= ys[j + 1]:
                jb = j
                break
        if jb is None:
            return None

        def _interp_t(j: int) -> float:
            y1, y2 = float(ys[j]), float(ys[j + 1])
            t1, t2 = float(ts[j]), float(ts[j + 1])
            dy = y2 - y1
            if abs(dy) < 1e-12:
                return t1
            f = (level - y1) / dy
            f = max(0.0, min(1.0, f))
            return t1 + f * (t2 - t1)

        ta = _interp_t(ja)
        tb = _interp_t(jb)
        if tb <= ta:
            return None
        return ta, tb

    def read_trr_measure_state(
        self,
    ) -> tuple[float, float, float, float, int | None] | None:
        """当前 Trr 卡尺位置（物理 A），用于再次点击参数时恢复。"""
        if self._interactive_mode != "trr_measure":
            return None
        if (
            self._h_cursor_a is None
            or self._h_cursor_b is None
            or self._cursor_a is None
            or self._cursor_b is None
        ):
            return None
        return (
            self._from_disp("irr", float(self._h_cursor_a.value())),
            self._from_disp("irr", float(self._h_cursor_b.value())),
            float(self._cursor_a.value()),
            float(self._cursor_b.value()),
            self._interactive_irr_peak_idx,
        )

    def enable_trr_measure_interaction(
        self,
        search_t0_us: float,
        search_t1_us: float,
        ha_a: float,
        hb_a: float,
        ta_us: float,
        tb_us: float,
        on_change,
        *,
        peak_idx: int | None = None,
        i_fall_end_idx: int | None = None,
        emit_result_on_enter: bool = False,
    ) -> None:
        """Trr：Ha=参考线；拖 Ha 联动 A(上升沿首个交点)、B(下降沿首个交点)。"""
        if search_t1_us < search_t0_us:
            search_t0_us, search_t1_us = search_t1_us, search_t0_us
        self._interactive_enabled = True
        self.clear_cursor_auxiliary_guides()
        self._interactive_on_change = on_change
        self._interactive_mode = "trr_measure"
        self._active_channel = "irr"
        self._slope_channel = None
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._interactive_search_t0_us = float(search_t0_us)
        self._interactive_search_t1_us = float(search_t1_us)
        self._interactive_irr_peak_idx = peak_idx
        self._interactive_trr_i_fall_end = i_fall_end_idx

        if self._cursor_a is None or self._cursor_b is None:
            self._install_persistent_cursors(search_t0_us, search_t1_us, 1.0)

        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(float(ta_us))
            self._cursor_b.setPos(float(tb_us))
            self._cursor_a.setMovable(True)
            self._cursor_b.setMovable(True)
            if self._h_cursor_a is not None:
                self._h_cursor_a.setPos(self._to_disp("irr", float(ha_a)))
                self._h_cursor_a.setMovable(True)
                self._h_cursor_a_locked = False
            if self._h_cursor_b is not None:
                self._h_cursor_b.setPos(self._to_disp("irr", float(hb_a)))
                self._h_cursor_b.setMovable(True)
        finally:
            self._interactive_syncing = False
        self._update_readout()
        if emit_result_on_enter:
            self._emit_trr_measure_changed()

    def _emit_trr_measure_changed(self) -> None:
        if (
            self._interactive_mode != "trr_measure"
            or self._interactive_on_change is None
            or self._h_cursor_a is None
            or self._h_cursor_b is None
            or self._cursor_a is None
            or self._cursor_b is None
        ):
            return
        ha = self._from_disp("irr", float(self._h_cursor_a.value()))
        hb = self._from_disp("irr", float(self._h_cursor_b.value()))
        ta = float(self._cursor_a.value())
        tb = float(self._cursor_b.value())
        trr_ns = abs(tb - ta) * 1e3  # µs -> ns
        self._interactive_on_change(ha, hb, ta, tb, trr_ns)

    def set_interval_level_crossings(
        self, t_a_us: float, t_b_us: float, y_level: float, channel: str = "irr"
    ) -> None:
        """区间模式下设置 A/B 与 Ha：A/B 为交点，Ha 为参考中线。"""
        if self._cursor_a is None or self._cursor_b is None or self._h_cursor_a is None:
            return
        ta = float(t_a_us)
        tb = float(t_b_us)
        if tb < ta:
            ta, tb = tb, ta
        self._active_channel = channel
        self._interactive_syncing = True
        try:
            self._cursor_a.setPos(ta)
            self._cursor_b.setPos(tb)
            self._cursor_a.setMovable(True)
            self._cursor_b.setMovable(True)
            self._h_cursor_a.setPos(self._to_disp(channel, float(y_level)))
            self._h_cursor_a.setMovable(True)
            self._h_cursor_a_locked = False
        finally:
            self._interactive_syncing = False
        self._update_readout()

    def set_interval_minmax_horizontal(
        self,
        y_min: float,
        y_max: float,
        channel: str = "vge_other",
        *,
        lock_horizontal: bool = False,
        t0_us: float | None = None,
        t1_us: float | None = None,
    ) -> None:
        """串扰电压等 min/max 型参数：Ha=最大值(在上)、Hb=最小值(在下)。"""
        if self._h_cursor_a is None or self._h_cursor_b is None:
            return
        self._active_channel = channel
        hi, lo = (max(y_min, y_max), min(y_min, y_max))
        ha_disp = self._to_disp(channel, float(hi))
        hb_disp = self._to_disp(channel, float(lo))
        if t0_us is not None and t1_us is not None:
            plot_hi = self._peak_plot_point_in_window(channel, t0_us, t1_us)
            plot_lo = self._min_plot_point_in_window(channel, t0_us, t1_us)
            if plot_hi is not None:
                peak_t_us, peak_value, ha_disp = plot_hi
                self.set_cursor_auxiliary_point(channel, peak_t_us, peak_value)
            else:
                self.clear_cursor_auxiliary_guides()
            if plot_lo is not None:
                _min_t_us, _min_value, hb_disp = plot_lo
        self._interactive_syncing = True
        try:
            self._h_cursor_a.setPos(ha_disp)
            self._h_cursor_a.setMovable(not lock_horizontal)
            self._h_cursor_a_locked = lock_horizontal
            self._h_cursor_b.setPos(hb_disp)
            self._h_cursor_b.setMovable(not lock_horizontal)
        finally:
            self._interactive_syncing = False
        self._update_readout()

    # ------------------------------------------------------------------ 信号回调 ----
    def _on_any_cursor_moved(self) -> None:
        if self._interactive_syncing:
            return
        self._update_readout()
        if not self._interactive_enabled or self._cursor_a is None or self._cursor_b is None:
            return
        if not self._cursor_linked:
            if self._interactive_mode == "delta_vce":
                self._emit_delta_vce_changed()
                return
            if self._interactive_mode == "irr_peak":
                t0 = float(self._cursor_a.value())
                t1 = float(self._cursor_b.value())
                if self._interactive_on_change is not None:
                    self._interactive_on_change(min(t0, t1), max(t0, t1))
                return
            if self._interactive_mode == "turn_on_current":
                self._emit_turn_on_current_changed()
                return
            if self._interactive_mode == "short_current":
                self._emit_short_current_changed()
                return
            if self._interactive_mode == "trr_measure":
                self._emit_trr_measure_changed()
                return
            if self._interactive_mode == "energy_loss":
                self._handle_energy_loss_vertical_moved()
                return
            if self._interactive_mode in {
                "interval",
                "irr_cross",
                "crosstalk",
                "power_peak",
            }:
                t0 = float(self._cursor_a.value())
                t1 = float(self._cursor_b.value())
                if self._interactive_on_change is not None:
                    self._interactive_on_change(min(t0, t1), max(t0, t1))
                return
            if self._interactive_mode == "global" and self._global_callback is not None:
                self._global_callback(
                    float(self._cursor_a.value()),
                    float(self._cursor_b.value()),
                )
            return
        if self._interactive_mode == "delta_vce":
            # 拖动的那根纵向光标 → 对应横向光标贴到该点 Vce 值（A↔Ha, B↔Hb）
            sender = self.sender()
            self._interactive_syncing = True
            try:
                if sender is self._cursor_a and self._h_cursor_a is not None:
                    self._h_cursor_a.setPos(
                        self._to_disp("vce", self._interp_vce(float(self._cursor_a.value())))
                    )
                elif sender is self._cursor_b and self._h_cursor_b is not None:
                    self._h_cursor_b.setPos(
                        self._to_disp("vce", self._interp_vce(float(self._cursor_b.value())))
                    )
                else:
                    if self._h_cursor_a is not None:
                        self._h_cursor_a.setPos(
                            self._to_disp("vce", self._interp_vce(float(self._cursor_a.value())))
                        )
                    if self._h_cursor_b is not None:
                        self._h_cursor_b.setPos(
                            self._to_disp("vce", self._interp_vce(float(self._cursor_b.value())))
                        )
            finally:
                self._interactive_syncing = False
            self._emit_delta_vce_changed()
            self._update_readout()
            return
        if self._interactive_mode in self._BASE_TOP_SLOPE_MODES:
            return
        if self._interactive_mode == "irr_peak":
            t0 = float(self._cursor_a.value())
            t1 = float(self._cursor_b.value())
            if self._interactive_on_change is not None:
                self._interactive_on_change(min(t0, t1), max(t0, t1))
            self._update_readout()
            return
        if self._interactive_mode == "turn_on_current":
            sender = self.sender()
            self._interactive_syncing = True
            try:
                if sender is self._cursor_a:
                    self._link_turn_on_current_from_vertical("a")
                elif sender is self._cursor_b:
                    self._link_turn_on_current_from_vertical("b")
            finally:
                self._interactive_syncing = False
            self._emit_turn_on_current_changed()
            self._update_readout()
            return
        if self._interactive_mode == "short_current":
            self._interactive_syncing = True
            try:
                self._sync_short_current_peak_from_window()
            finally:
                self._interactive_syncing = False
            self._emit_short_current_changed()
            self._update_readout()
            return
        if self._interactive_mode == "trr_measure":
            self._emit_trr_measure_changed()
            return
        if self._interactive_mode == "energy_loss":
            self._handle_energy_loss_vertical_moved()
            return
        if self._interactive_mode in {"interval", "irr_cross", "crosstalk"}:
            t0 = float(self._cursor_a.value())
            t1 = float(self._cursor_b.value())
            if self._interactive_on_change is not None:
                self._interactive_on_change(min(t0, t1), max(t0, t1))
            return
        # global 模式：仅通知 MainWindow 用于 statusBar 测量读数
        if self._interactive_mode == "global" and self._global_callback is not None:
            self._global_callback(
                float(self._cursor_a.value()),
                float(self._cursor_b.value()),
            )

    def _on_horizontal_cursor_moved(self) -> None:
        if self._interactive_syncing:
            return
        self._update_readout()
        if not self._cursor_linked:
            if self._interactive_mode == "delta_vce":
                self._emit_delta_vce_changed()
                return
            if self._interactive_mode in self._BASE_TOP_SLOPE_MODES:
                self._emit_dvdt_changed()
                return
            if self._interactive_mode == "crosstalk":
                if self._cursor_a is not None and self._cursor_b is not None:
                    t0 = float(self._cursor_a.value())
                    t1 = float(self._cursor_b.value())
                    if self._interactive_on_change is not None:
                        self._interactive_on_change(min(t0, t1), max(t0, t1))
                return
            if self._interactive_mode == "energy_loss":
                self._emit_energy_loss_changed()
                return
            if self._interactive_mode == "turn_on_current":
                self._emit_turn_on_current_changed()
                return
            if self._interactive_mode == "short_current":
                self._emit_short_current_changed()
                return
            if self._interactive_mode == "trr_measure":
                self._emit_trr_measure_changed()
                return
            if self._horizontal_callback is not None:
                ch = self._active_channel
                ha = self._from_disp(ch, float(self._h_cursor_a.value())) if self._h_cursor_a is not None else 0.0
                hb = self._from_disp(ch, float(self._h_cursor_b.value())) if self._h_cursor_b is not None else 0.0
                self._horizontal_callback(ha, hb)
            return
        if self._interactive_mode == "delta_vce":
            # 拖动的那根横向光标 → 沿波形吸附其对应纵向光标（Ha↔A, Hb↔B）
            sender = self.sender()
            if sender is self._h_cursor_a and self._cursor_a is not None:
                hcur, vcur = self._h_cursor_a, self._cursor_a
            elif sender is self._h_cursor_b and self._cursor_b is not None:
                hcur, vcur = self._h_cursor_b, self._cursor_b
            elif self._h_cursor_b is not None and self._cursor_b is not None:
                hcur, vcur = self._h_cursor_b, self._cursor_b
            else:
                return
            target_v = self._from_disp("vce", float(hcur.value()))
            ref_t_us = float(vcur.value())
            t_match, v_match = self._nearest_time_for_vce(target_v, ref_t_us)
            self._interactive_syncing = True
            try:
                vcur.setPos(t_match)
                hcur.setPos(self._to_disp("vce", v_match))
            finally:
                self._interactive_syncing = False
            self._emit_delta_vce_changed()
            self._update_readout()
            return
        if self._interactive_mode in self._BASE_TOP_SLOPE_MODES:
            self._emit_dvdt_changed()
            self._update_readout()
            return
        if self._interactive_mode == "irr_peak":
            return
        if self._interactive_mode == "crosstalk":
            if self._cursor_a is not None and self._cursor_b is not None:
                t0 = float(self._cursor_a.value())
                t1 = float(self._cursor_b.value())
                if self._interactive_on_change is not None:
                    self._interactive_on_change(min(t0, t1), max(t0, t1))
            self._update_readout()
            return
        if self._interactive_mode == "energy_loss":
            self._emit_energy_loss_changed()
            self._update_readout()
            return
        if self._interactive_mode == "turn_on_current":
            sender = self.sender()
            self._interactive_syncing = True
            try:
                if sender is self._h_cursor_a:
                    self._link_turn_on_current_from_horizontal("ha")
                elif sender is self._h_cursor_b:
                    self._link_turn_on_current_from_horizontal("hb")
                else:
                    self._link_turn_on_current_from_horizontal("both")
            finally:
                self._interactive_syncing = False
            self._emit_turn_on_current_changed()
            self._update_readout()
            return
        if self._interactive_mode == "short_current":
            sender = self.sender()
            self._interactive_syncing = True
            try:
                if sender is self._h_cursor_b:
                    self._sync_short_current_from_hb()
                else:
                    self._sync_short_current_peak_from_window()
            finally:
                self._interactive_syncing = False
            self._emit_short_current_changed()
            self._update_readout()
            return
        if self._interactive_mode == "trr_measure":
            if (
                self._h_cursor_a is None
                or self._h_cursor_b is None
                or self._cursor_a is None
                or self._cursor_b is None
            ):
                return
            from dpt_extractor.metrics.irr_measure import trr_crossings_at_ha

            t0 = float(self._interactive_search_t0_us or self._cursor_a.value())
            t1 = float(self._interactive_search_t1_us or self._cursor_b.value())
            tt, vv = self._series_for_channel("irr")
            if tt is None or vv is None:
                return
            i0 = int(np.searchsorted(tt, min(t0, t1), side="left"))
            i1 = int(np.searchsorted(tt, max(t0, t1), side="right")) - 1
            i0 = max(0, min(i0, len(tt) - 2))
            i1 = max(i0 + 2, min(i1, len(tt) - 1))
            pk = self._interactive_irr_peak_idx
            fall_ns = int(600e-9 / max(self._interactive_dt, 1e-15))
            i_fall_local = min(len(tt) - 2, max(i1, (pk if pk is not None else i0) + fall_ns))
            i_fall_end = (
                self._interactive_trr_i_fall_end
                if self._interactive_trr_i_fall_end is not None
                else i_fall_local
            )
            i_fall_end = min(len(tt) - 2, max(i_fall_end, i_fall_local))

            sender = self.sender()
            ha = self._from_disp("irr", float(self._h_cursor_a.value()))

            if sender is self._h_cursor_b:
                self._emit_trr_measure_changed()
                return

            t_s = tt * 1e-6
            cross = trr_crossings_at_ha(
                t_s,
                vv,
                i0,
                i1,
                ha,
                peak_idx=pk,
                i_fall_end=i_fall_end,
            )
            if cross is None:
                self._emit_trr_measure_changed()
                return
            ta_s, tb_s, pk_out = cross
            self._interactive_irr_peak_idx = pk_out
            self._interactive_syncing = True
            try:
                self._cursor_a.setPos(ta_s * 1e6)
                self._cursor_b.setPos(tb_s * 1e6)
            finally:
                self._interactive_syncing = False
            self._update_readout()
            if self._interactive_on_change is not None:
                hb = self._from_disp("irr", float(self._h_cursor_b.value()))
                self._interactive_on_change(
                    ha,
                    hb,
                    ta_s * 1e6,
                    tb_s * 1e6,
                    max(0.0, (tb_s - ta_s) * 1e9),
                )
            return
        if self._interactive_mode == "irr_cross":
            if self._h_cursor_a is None or self._cursor_a is None or self._cursor_b is None:
                return
            t0 = (
                self._interactive_search_t0_us
                if self._interactive_search_t0_us is not None
                else float(self._cursor_a.value())
            )
            t1 = (
                self._interactive_search_t1_us
                if self._interactive_search_t1_us is not None
                else float(self._cursor_b.value())
            )
            level = self._from_disp("irr", float(self._h_cursor_a.value()))
            crosses = self._crossings_with_level("irr", float(level), float(t0), float(t1))
            if crosses is not None:
                ta, tb = crosses
                self._interactive_syncing = True
                try:
                    self._cursor_a.setPos(float(ta))
                    self._cursor_b.setPos(float(tb))
                finally:
                    self._interactive_syncing = False
                self._update_readout()
                if self._interactive_on_change is not None:
                    self._interactive_on_change(float(ta), float(tb))
            return
        if self._horizontal_callback is not None:
            # 回调以活动通道真实单位上报
            ch = self._active_channel
            ha = self._from_disp(ch, float(self._h_cursor_a.value())) if self._h_cursor_a is not None else 0.0
            hb = self._from_disp(ch, float(self._h_cursor_b.value())) if self._h_cursor_b is not None else 0.0
            self._horizontal_callback(ha, hb)

    # ------------------------------------------------------------------ 焦点 ----
    def focus_interval_us(self, t_start_us: float, t_end_us: float) -> None:
        """以区间中心为基准局部放大；默认 200ns/div，用户调过标度则沿用记忆值。"""
        if t_end_us < t_start_us:
            t_start_us, t_end_us = t_end_us, t_start_us
        center_us = 0.5 * (float(t_start_us) + float(t_end_us))
        scale_us = self._param_focus_x_scale_us()
        self._apply_x_us_per_div(scale_us, center_us=center_us)
        self._apply_disp_yrange()
        vb = self.plot.getPlotItem().getViewBox()
        try:
            xr = vb.viewRange()[0]
            self._last_x_window = (float(xr[0]), float(xr[1]))
        except Exception:
            self._last_x_window = (
                center_us - scale_us * HORIZONTAL_DIV_COUNT * 0.5,
                center_us + scale_us * HORIZONTAL_DIV_COUNT * 0.5,
            )

    def focus_anchor_left_divs_us(
        self, anchor_us: float, *, left_divs: float = 2.0
    ) -> None:
        """局部放大时把事件锚点放在左侧若干格，给右侧振荡留观察空间。"""
        scale_us = self._param_focus_x_scale_us()
        left_divs = float(np.clip(float(left_divs), 0.0, HORIZONTAL_DIV_COUNT))
        center_us = float(anchor_us) + (HORIZONTAL_DIV_COUNT * 0.5 - left_divs) * scale_us
        self._apply_x_us_per_div(scale_us, center_us=center_us)
        self._apply_disp_yrange()
        vb = self.plot.getPlotItem().getViewBox()
        try:
            xr = vb.viewRange()[0]
            self._last_x_window = (float(xr[0]), float(xr[1]))
        except Exception:
            span = scale_us * HORIZONTAL_DIV_COUNT
            self._last_x_window = (
                center_us - span * 0.5,
                center_us + span * 0.5,
            )
