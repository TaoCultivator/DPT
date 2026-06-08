from __future__ import annotations

import ast
import re

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QBrush, QColor, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QFrame,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGraphicsRectItem,
    QHBoxLayout,
    QInputDialog,
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

    _PX_LEN = 34
    _PX_H = 15

    def __init__(self, key: str, label: str, color: str, view_box: pg.ViewBox):
        super().__init__()
        self._key = key
        self._label = label
        self._color = QColor(color)
        self._vb = view_box
        self._px_len = self._PX_LEN
        self._px_h = self._PX_H
        self._highlighted = False
        self._hovered = False
        self._press_scene: QPointF | None = None
        self._dragging = False
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setZValue(100)
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def set_highlighted(self, on: bool) -> None:
        if self._highlighted != on:
            self._highlighted = on
            self.update()

    @staticmethod
    def _right_arrow_polygon_px(px_len: float, px_h: float) -> QPolygonF:
        """像素坐标：左侧为通道标签，右侧尖端精确指向该通道 0 值。"""
        body_w = px_len * 0.68
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

    def boundingRect(self):  # noqa: N802
        return QRectF(
            -2,
            -self._px_h / 2 - 2,
            self._px_len + 4,
            self._px_h + 4,
        )

    def paint(self, painter, opt, widget=None) -> None:  # noqa: N802
        fill = self._color
        if self._highlighted:
            fill = fill.lighter(120)
        elif self._hovered:
            fill = fill.lighter(105)
        outline = QColor("#101010")
        outline.setAlpha(210)
        painter.setPen(QPen(outline, 1.0))
        painter.setBrush(fill)
        painter.drawPolygon(self._right_arrow_polygon_px(self._px_len, self._px_h))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(7)
        painter.setFont(font)
        text_color = QColor("#111111") if fill.lightness() > 145 else QColor("#ffffff")
        painter.setPen(text_color)
        painter.drawText(
            QRectF(1.0, -self._px_h / 2.0, self._px_len * 0.68 - 1.0, self._px_h),
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
            if not self._dragging:
                self.clicked.emit(self._key)
            self._press_scene = None
            self._dragging = False
            ev.accept()
            return
        super().mouseReleaseEvent(ev)


class ChannelBox(QFrame):
    """示波器风格底部通道盒：左键选中、双击改垂直、右键菜单。"""

    highlightClicked = pyqtSignal(str)
    verticalSettingsRequested = pyqtSignal(str)
    visibilityToggleRequested = pyqtSignal(str)
    contextMenuRequested = pyqtSignal(str, QPoint)

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
        if ev.button() == Qt.MouseButton.RightButton:
            if hasattr(ev, "globalPosition"):
                global_pos = ev.globalPosition().toPoint()
            else:
                global_pos = ev.globalPos()
            self.contextMenuRequested.emit(self._key, global_pos)
            ev.accept()
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            self.highlightClicked.emit(self._key)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.verticalSettingsRequested.emit(self._key)
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
    color: #f3fbff;
}
QMenu::item:disabled {
    color: #777777;
}
QMenu::separator {
    height: 2px;
    background-color: #f3f3f3;
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
    WAVEFORM_EDGE_COLORS,
    WAVEFORM_GRID_ALPHA,
    WAVEFORM_PLOT_BG,
    WAVEFORM_PLOT_FG,
    WAVEFORM_TRACE_STYLES,
)
from dpt_extractor.models.bridge_profile import BridgeProfile
from dpt_extractor.models.results import ExtractResult, SegmentIndices
from dpt_extractor.models.waveform import (
    WaveformBundle,
    bundle_reverse_recovery_current,
    bundle_total_current,
)

MAX_PLOT_POINTS = 8000
MIN_X_SPAN_US = 0.2  # 200 ns 最小放大窗口
V_CURSOR_WIDTH = 3
H_CURSOR_WIDTH = 2

# 示波器光标：橙 A + 黄 B（与示波器 Tek 风格一致）
CURSOR_PEN_A = "#FFAA00"
CURSOR_PEN_B = "#FFE600"
CURSOR_PEN_ZERO = "#A6E3A1"

# 每通道独立垂直刻度（示波器 V/div 风格）：显示坐标 = 原始值 / (单位每格)
DISP_HALF_DIV = 5.0  # 纵向显示半高（格），总高 10 格（同示波器）
HORIZONTAL_DIV_COUNT = 10.0  # 横向整格数（与 _update_x_ticks 一致）
X_NS_PER_DIV = 50  # 水平标度 ns/格 步进（滚轮与显示量化）
PARAM_FOCUS_DEFAULT_US_PER_DIV = 0.2  # 点击参数局部放大默认 200 ns/div
VERT_VIEW_MARGIN = 0.10  # 纵向上下各留 10% 空白
VDIV_LADDER = (1, 2, 5, 10, 20, 50, 100, 150, 200, 250, 300)
CURRENT_VDIV_DEFAULT = 200.0  # 电流通道默认刻度（A/格）
CURRENT_VDIV_MAX = 300.0  # 电流通道可选上限（含 250、300）
_NICE_STEPS = (1.0, 2.0, 2.5, 5.0)

# 参考示波器默认垂直刻度（Ch1 5V/格, Ch2 200V/格, Ch3/4 200A/格, Ch5 200V/格, Ch6 5V/格）
SCOPE_VDIV_DEFAULT: dict[str, float] = {
    "vge": 5.0,        # CH1 H-Vge
    "vce": 200.0,      # CH2 H-Vce
    "ic": 200.0,       # CH3+CH4 总电流
    "irr": 200.0,      # CH3/CH4 电流
    "v_diode": 200.0,  # CH5 L-Vce
    "vge_other": 5.0,  # CH6 L-Vge
}

# 默认垂直位置偏移（格），对齐用户示波器布局
SCOPE_OFFSET_DEFAULT: dict[str, float] = {
    "vge": -1.0,
    "vce": -3.0,
    "ic": 2.5,
    "irr": 2.5,
    "v_diode": -2.0,
    "vge_other": -0.5,
}

# 通道单位（用于读数显示）
CHANNEL_UNITS = {
    "vge": "V",
    "vce": "V",
    "ic": "A",
    "irr": "A",
    "v_diode": "V",
    "vge_other": "V",
}

MATH_TRACE_COLORS = (
    "#008000",
    "#B22222",
    "#FF1010",
    "#98B33A",
    "#F28A1D",
    "#742D8E",
    "#B22222",
    "#98B33A",
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


def _source_channel_sort_key(name: str) -> tuple[int, int, str]:
    m = re.fullmatch(r"(CH|MATH)(\d+)", name.upper())
    if not m:
        return (2, 0, name.upper())
    return (0 if m.group(1) == "CH" else 1, int(m.group(2)), name.upper())


def _is_math_trace_key(key: str) -> bool:
    return bool(re.fullmatch(r"MATH\d+", key.upper()))


def _math_color(key: str) -> str:
    m = re.fullmatch(r"MATH(\d+)", key.upper())
    idx = int(m.group(1)) - 1 if m else 0
    return MATH_TRACE_COLORS[idx % len(MATH_TRACE_COLORS)]


def _source_channel_legend(key: str, labels: dict[str, str]) -> str:
    key = key.upper()
    label = (labels.get(key) or "").strip()
    if label:
        return label
    m = re.fullmatch(r"MATH(\d+)", key)
    if m:
        return f"Math {int(m.group(1))}"
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


def _usable_y_divs() -> float:
    """纵向可用于波形的总格数（上下各留 VERT_VIEW_MARGIN）。"""
    return HORIZONTAL_DIV_COUNT * (1.0 - 2.0 * VERT_VIEW_MARGIN)


def _vdiv_max_for_channel(key: str) -> float:
    if CHANNEL_UNITS.get(key) == "A":
        return CURRENT_VDIV_MAX  # 250、300 可选
    return float(VDIV_LADDER[-1])


def _pick_vdiv_ladder(required: float, key: str) -> float:
    """取不小于 required 的最小整数档位；电流通道不超过 200A/格。"""
    required = max(float(required), 1e-12)
    cap = _vdiv_max_for_channel(key)
    for v in VDIV_LADDER:
        if float(v) > cap:
            break
        if float(v) >= required:
            return float(v)
    for v in reversed(VDIV_LADDER):
        if float(v) <= cap:
            return float(v)
    return float(VDIV_LADDER[0])


def _vdiv_max_for_channel(key: str) -> float:
    if CHANNEL_UNITS.get(key) == "A":
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


def _auto_vdiv_for_channel(key: str, raw: np.ndarray) -> float:
    """按波形半幅 + 上下 10% 边距自动选取整数 V/div（或 A/div）。

    默认刻度（SCOPE_VDIV_DEFAULT）能放下时保持默认：Vge 5V/格，电压/电流 200。
    仅当超出默认时才升档。
    """
    if len(raw) == 0:
        default = SCOPE_VDIV_DEFAULT.get(key, float(VDIV_LADDER[0]))
        return _pick_vdiv_ladder(default, key)
    _, _, _, half_span = _raw_value_span(raw)
    required = (2.0 * half_span) / _usable_y_divs()
    pref = SCOPE_VDIV_DEFAULT.get(key)
    if pref is not None and required <= float(pref):
        return float(pref)
    return _pick_vdiv_ladder(required, key)


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


class WaveformPlot(QWidget):
    """双脉冲波形 + 持久 A/B 时间光标 + Ha/Hb 通道光标。

    交互模式（_interactive_mode）：
      - "global"   : 默认。A/B 拖动只更新读数 + 通知 MainWindow（用于无激活参数的测量）
      - "interval" : 某参数被点击后绑定到 A/B；拖动 A/B 实时重算该参数
      - "delta_vce": ΔVce 专用——A/B + Ha/Hb 联动
      - "dvdt"/"didt": Ha=Top、Hb=Base；A/B 卡在两者之间百分比穿越时刻（随 Ha/Hb 联动）
    """

    channelMappingRequested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        pg.setConfigOptions(antialias=True, background=WAVEFORM_PLOT_BG, foreground=WAVEFORM_PLOT_FG)

        # ---- 顶部信息栏：读数可横向滚动，避免加载波形后挤出屏幕 ----
        self._header_bar = QWidget()
        header = QHBoxLayout(self._header_bar)
        header.setContentsMargins(4, 2, 4, 2)
        header.setSpacing(8)

        self._readout_scroll = QScrollArea()
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
        header.addWidget(self._readout_scroll, stretch=1)

        scale_box = QWidget()
        scale_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        scale_lay = QHBoxLayout(scale_box)
        scale_lay.setContentsMargins(0, 0, 0, 0)
        scale_lay.setSpacing(6)
        self._x_scale_caption = QLabel("水平标度")
        self._x_scale_caption.setStyleSheet(
            f"color:{WAVEFORM_PLOT_FG};font-size:12px;font-weight:600;"
        )
        self._x_scale_edit = QLineEdit()
        self._x_scale_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._x_scale_edit.setFixedWidth(108)
        self._x_scale_edit.setPlaceholderText("200ns")
        self._x_scale_edit.setStyleSheet(
            "background-color:#e6e6e6;color:#1a1a1a;"
            "font-size:12px;font-family:Consolas,'Courier New',monospace;"
            "padding:3px 8px;border-radius:4px;border:1px solid #b0b0b0;"
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
        scale_lay.addWidget(self._zoom_select_btn)
        scale_lay.addWidget(self._x_scale_caption)
        scale_lay.addWidget(self._x_scale_edit)
        header.addWidget(scale_box, stretch=0)

        layout.addWidget(self._header_bar)

        self.plot = pg.PlotWidget()
        self.plot.setTitle(None)
        self.plot.setBackground(WAVEFORM_PLOT_BG)
        self.plot.getPlotItem().getViewBox().setBackgroundColor(WAVEFORM_PLOT_BG)
        self.plot.setLabel("bottom", "时间", units="µs", color=WAVEFORM_PLOT_FG)
        self.plot.setLabel("left", "格 (div)", color=WAVEFORM_PLOT_FG)
        self.plot.showGrid(x=True, y=True, alpha=WAVEFORM_GRID_ALPHA)
        axis_pen = pg.mkPen(WAVEFORM_PLOT_FG)
        for axis_name in ("left", "bottom"):
            ax = self.plot.getPlotItem().getAxis(axis_name)
            ax.setPen(axis_pen)
            ax.setTextPen(axis_pen)
        # 纵轴固定整格刻度线（去掉细密小网格，只留示波器式整格水平线）
        ax_left = self.plot.getPlotItem().getAxis("left")
        ax_left.setTicks(
            [[(i, str(i)) for i in range(-int(DISP_HALF_DIV), int(DISP_HALF_DIV) + 1)]]
        )
        ax_left.setWidth(72)
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
        _vb_wheel = vb.wheelEvent

        def _vb_wheel(ev, axis=None):
            if self._on_x_wheel(ev):
                return
            _vb_wheel(ev, axis)

        vb.wheelEvent = _vb_wheel
        _orig_vb_drag = vb.mouseDragEvent

        def _vb_drag(ev, axis=None):
            if self._on_selection_drag(ev):
                return
            _orig_vb_drag(ev, axis)

        vb.mouseDragEvent = _vb_drag
        layout.addWidget(self.plot, stretch=1)

        # ---- 底部通道盒（横向滚动，窄屏不挤出）----
        self._channel_bar = QWidget()
        self._channel_layout = QHBoxLayout(self._channel_bar)
        self._channel_layout.setContentsMargins(6, 5, 6, 5)
        self._channel_layout.setSpacing(5)
        self._channel_scroll = QScrollArea()
        self._channel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._channel_scroll.setWidgetResizable(False)
        self._channel_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
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
            "QScrollArea { background-color: #10111a; border-top: 1px solid #303342; }"
        )
        self._channel_bar.setStyleSheet("background-color: #10111a;")
        self._channel_scroll.setWidget(self._channel_bar)
        layout.addWidget(self._channel_scroll)
        self._channel_boxes: dict[str, ChannelBox] = {}

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
        self._x_us_per_div: float = 0.0
        self._x_target_us_per_div: float = 0.0
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
        self._trace_units: dict[str, str] = {}
        self._highlighted_key: str | None = None
        self._hidden_channels: set[str] = set()

        # 每通道垂直刻度（单位/格），显示坐标 = 原始值 / 刻度 + 位置偏移
        self._disp_scale: dict[str, float] = {}
        # 每通道垂直位置偏移（格），示波器 position 旋钮；默认对齐示波器布局
        self._disp_offset: dict[str, float] = dict(SCOPE_OFFSET_DEFAULT)
        # 用户手动设置的 V/div（覆盖默认/自动）
        self._manual_vdiv: dict[str, float] = {}
        self._loaded_source_path: str | None = None
        # 原始波形缓存（改刻度/位置时重算显示坐标）
        self._trace_t_us: np.ndarray | None = None
        self._trace_raw: dict[str, np.ndarray] = {}
        self._formula_t_s: np.ndarray | None = None
        self._formula_sources: dict[str, np.ndarray] = {}
        self._math_formulas: dict[str, str] = {}
        self._math_source_keys: set[str] = set()
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
        self._context_menu_group = "cursor"

        # 持久光标回调（global 模式拖动时触发）
        self._global_callback = None
        self._horizontal_callback = None

    # ------------------------------------------------------------------ 公共 API ----
    def set_global_cursor_handler(self, cb) -> None:
        """A/B 拖动时 MainWindow 监听：cb(t0_us, t1_us)。"""
        self._global_callback = cb

    def set_horizontal_cursor_handler(self, cb) -> None:
        """Ha/Hb 拖动时 MainWindow 监听：cb(ha, hb)。"""
        self._horizontal_callback = cb

    def reset_interaction_state(self) -> None:
        """换文件或「重新计算」清空手动状态时，退出参数绑定模式，避免沿用旧光标。"""
        self._interactive_enabled = False
        self._interactive_mode = "global"
        self._interactive_on_change = None
        self._interactive_search_t0_us = None
        self._interactive_search_t1_us = None
        self._h_cursor_a_locked = False

    def cursors_t_us(self) -> tuple[float, float] | None:
        if self._cursor_a is None or self._cursor_b is None:
            return None
        a = float(self._cursor_a.value())
        b = float(self._cursor_b.value())
        return min(a, b), max(a, b)

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
        ):
            if it is not None:
                keep.append(it)
        return keep

    def _soft_clear(self) -> None:
        """清除波形/分区，但保留持久光标。"""
        self._clear_selection_rect()
        self._remove_zero_handles()
        keep = self._items_to_keep()
        plot_item = self.plot.getPlotItem()
        for it in list(plot_item.items):
            if it not in keep:
                plot_item.removeItem(it)

    def clear(self) -> None:
        """完全清除：包括光标（仅在新文件加载等场景使用）。"""
        for it in self._items_to_keep():
            self.plot.removeItem(it)
        self._cursor_a = None
        self._cursor_b = None
        self._h_cursor_a = None
        self._h_cursor_b = None
        self._clear_selection_rect()
        self._remove_cursor_plot_labels()
        self._remove_zero_handles()
        self._interactive_vce_t_us = None
        self._interactive_vce = None
        self._interactive_irr_t_us = None
        self._interactive_irr = None
        self._interactive_irr_peak_idx = None
        self._interactive_trr_i_fall_end = None
        self._interactive_ic_t_us = None
        self._interactive_ic = None
        self._slope_channel = None
        self._interactive_on_change = None
        self._interactive_mode = "global"
        self._interactive_search_t0_us = None
        self._interactive_search_t1_us = None
        self._interactive_syncing = False
        self._interval_max_hline_enabled = False
        self._interval_peak_on_hb = False
        self._h_cursor_a_locked = False

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

    def set_context_menu_group(self, group: str) -> None:
        if group not in {"cursor", "zoom", "view", "y", "all"}:
            group = "cursor"
        self._context_menu_group = group

    def context_menu_group(self) -> str:
        return self._context_menu_group

    def _populate_cursor_menu(self, menu: QMenu, t_us: float, y_div: float) -> None:
        has_cursors = self._cursor_a is not None and self._cursor_b is not None
        if has_cursors:
            act_a = QAction("将光标 A 移到此处", self)
            act_b = QAction("将光标 B 移到此处", self)
            act_a.setEnabled(self._line_movable(self._cursor_a))
            act_b.setEnabled(self._line_movable(self._cursor_b))
            act_a.triggered.connect(lambda: self._jump_vertical_cursor("a", t_us))
            act_b.triggered.connect(lambda: self._jump_vertical_cursor("b", t_us))
            menu.addAction(act_a)
            menu.addAction(act_b)
            if self._h_cursor_a is not None and self._h_cursor_b is not None:
                act_ha = QAction("将横向光标 Ha 移到此处", self)
                act_ha.setEnabled(not self._h_cursor_a_locked)
                act_ha.triggered.connect(
                    lambda: self._jump_horizontal_cursor("a", y_div)
                )
                menu.addAction(act_ha)
                act_hb = QAction("将横向光标 Hb 移到此处", self)
                act_hb.setEnabled(self._line_movable(self._h_cursor_b))
                act_hb.triggered.connect(
                    lambda: self._jump_horizontal_cursor("b", y_div)
                )
                menu.addAction(act_hb)
        else:
            act_no_cursor = QAction("尚未安装光标", self)
            act_no_cursor.setEnabled(False)
            menu.addAction(act_no_cursor)

        menu.addSeparator()
        mode_menu = menu.addMenu("光标模式")
        act_linked = QAction("联动", self)
        act_independent = QAction("独立", self)
        act_linked.setCheckable(True)
        act_independent.setCheckable(True)
        act_linked.setChecked(self._cursor_linked)
        act_independent.setChecked(not self._cursor_linked)
        mode_group = QActionGroup(mode_menu)
        mode_group.setExclusive(True)
        mode_group.addAction(act_linked)
        mode_group.addAction(act_independent)
        act_linked.triggered.connect(
            lambda checked=False: self._set_cursor_link_mode(linked=True)
        )
        act_independent.triggered.connect(
            lambda checked=False: self._set_cursor_link_mode(linked=False)
        )
        mode_menu.addAction(act_linked)
        mode_menu.addAction(act_independent)

    def _populate_zoom_menu(self, menu: QMenu) -> None:
        act_zoom_select = QAction("框选局部放大", self)
        act_zoom_select.setCheckable(True)
        act_zoom_select.setChecked(self._selection_zoom_enabled)
        act_zoom_select.triggered.connect(lambda checked=False: self._arm_selection_zoom())
        menu.addAction(act_zoom_select)

    def _populate_view_menu(self, menu: QMenu) -> None:
        act_fit = QAction("自适应铺满波形", self)
        act_full = QAction("铺满全部双脉冲波形", self)
        act_reset = QAction("重置视图", self)

        act_fit.triggered.connect(self._fit_last_window)
        act_full.triggered.connect(self._fit_full_range)
        act_reset.triggered.connect(self._reset_view)

        menu.addAction(act_fit)
        menu.addAction(act_full)
        menu.addAction(act_reset)

    def _populate_y_axis_menu(self, menu: QMenu) -> None:
        act_auto_y = QAction("自动纵轴", self)
        act_lock_y = QAction("锁定纵轴缩放(1.00x)", self)

        act_auto_y.triggered.connect(self._apply_disp_yrange)
        act_lock_y.triggered.connect(self._lock_y_mouse)

        menu.addAction(act_auto_y)
        menu.addAction(act_lock_y)

    def _show_context_menu(self, pos) -> None:
        t_us, y_div = self._view_coords_at_context_pos(pos)
        group = self._context_menu_group
        menu = QMenu(self)

        if group == "all":
            cursor_menu = menu.addMenu("光标")
            self._populate_cursor_menu(cursor_menu, t_us, y_div)
            zoom_menu = menu.addMenu("缩放")
            self._populate_zoom_menu(zoom_menu)
            view_menu = menu.addMenu("视图")
            self._populate_view_menu(view_menu)
            y_menu = menu.addMenu("纵轴")
            self._populate_y_axis_menu(y_menu)
        elif group == "zoom":
            self._populate_zoom_menu(menu)
        elif group == "view":
            self._populate_view_menu(menu)
        elif group == "y":
            self._populate_y_axis_menu(menu)
        else:
            self._populate_cursor_menu(menu, t_us, y_div)

        menu.exec(self.plot.mapToGlobal(pos))

    def _lock_y_mouse(self) -> None:
        vb = self.plot.getPlotItem().getViewBox()
        vb.setMouseEnabled(x=True, y=False)

    def _apply_disp_yrange(self) -> None:
        """固定纵向显示为 ±DISP_HALF_DIV 格（每通道按自身 V/div 缩放）。"""
        vb = self.plot.getPlotItem().getViewBox()
        vb.setYRange(-DISP_HALF_DIV, DISP_HALF_DIV, padding=0.0)
        vb.setMouseEnabled(x=True, y=False)
        self._update_y_ticks()

    def _update_x_ticks(self) -> None:
        """时间轴只画 ~10 等分整刻度线（无细密小网格），随缩放自适应。"""
        import math

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
        step = _nice_per_div(span, target_div=HORIZONTAL_DIV_COUNT)
        start = math.ceil(x0 / step - 1e-9) * step
        ticks = []
        v = start
        cnt = 0
        while v <= x1 + 1e-9 and cnt < 60:
            ticks.append((v, f"{v:g}"))
            v += step
            cnt += 1
        self.plot.getPlotItem().getAxis("bottom").setTicks([ticks])

    def _sync_x_scale_readout(self, scale_us: float | None = None) -> None:
        if scale_us is None:
            scale_us = self._x_target_us_per_div
        self._x_scale_edit.blockSignals(True)
        self._x_scale_edit.setText(_format_time_per_div(scale_us))
        self._x_scale_edit.blockSignals(False)

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

    def _on_x_scale_committed(self) -> None:
        if self._x_scale_updating:
            return
        parsed = _parse_time_per_div_input(self._x_scale_edit.text())
        if parsed is None:
            self._sync_x_scale_readout()
            return
        self._apply_x_us_per_div(parsed)
        self._remember_user_x_scale(parsed)

    def _set_selection_zoom_enabled(self, enabled: bool) -> None:
        self._selection_zoom_enabled = bool(enabled)
        if self._selection_zoom_enabled:
            self.plot.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.plot.unsetCursor()
            self._clear_selection_rect()

    def _finish_selection_zoom_mode(self) -> None:
        if self._zoom_select_btn.isChecked():
            self._zoom_select_btn.setChecked(False)
        else:
            self._set_selection_zoom_enabled(False)

    def _arm_selection_zoom(self) -> None:
        self._zoom_select_btn.setChecked(True)

    # ---- 每通道垂直刻度换算（显示坐标 = 原始值 / 刻度 + 位置偏移）----
    def _selection_button_is_left(self, ev) -> bool:
        btn_fn = getattr(ev, "button", None)
        btn = btn_fn() if callable(btn_fn) else None
        return btn in (None, Qt.MouseButton.LeftButton)

    def _ensure_selection_rect(self, start: QPointF) -> None:
        if self._selection_rect_item is None:
            item = QGraphicsRectItem(QRectF(start, start))
            pen = QPen(QColor("#8fd3ff"), 1.4, Qt.PenStyle.DashLine)
            fill = QColor("#1e90ff")
            fill.setAlpha(45)
            item.setPen(pen)
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

    def _apply_selection_zoom(self, p0: QPointF, p1: QPointF) -> None:
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
            return
        vb.setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0.0)
        self._last_x_window = (x0, x1)
        self._x_target_us_per_div = _quantize_x_us_per_div(
            _exact_x_us_per_div(x1 - x0)
        )
        self._x_us_per_div = self._x_target_us_per_div
        self._remember_user_x_scale(self._x_target_us_per_div)
        self._sync_x_scale_readout()
        self._update_y_ticks()

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
            if rect.width() >= 8 and rect.height() >= 8:
                self._apply_selection_zoom(start, cur)
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

    @staticmethod
    def _format_axis_value(value: float, unit: str) -> str:
        abs_v = abs(float(value))
        prefix = ""
        scale = 1.0
        if abs_v >= 1000.0 and unit in {"V", "A"}:
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
            y0, y1 = vb.viewRange()[1]
        except Exception:
            return
        ch = self._axis_channel()
        if ch is None:
            ticks = [
                (i, str(i))
                for i in range(-int(DISP_HALF_DIV), int(DISP_HALF_DIV) + 1)
            ]
            signature = (None, round(y0, 9), round(y1, 9))
            label = "div"
            color = WAVEFORM_PLOT_FG
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
            color = self._trace_style.get(ch, (WAVEFORM_PLOT_FG, 1.0))[0]
            try:
                idx = list(self._trace_items.keys()).index(ch) + 1
            except ValueError:
                idx = 0
            legend = self._trace_legend.get(ch, ch)
            vdiv = self._disp_scale.get(ch, 1.0)
            vdiv_txt = (
                f"{int(round(vdiv))}"
                if abs(vdiv - round(vdiv)) < 1e-9
                else f"{vdiv:g}"
            )
            label = (
                f"C{idx} {legend}  {vdiv_txt} {unit}/div"
                if idx
                else f"{legend} {unit}"
            )
            signature = (
                ch,
                round(float(y0), 9),
                round(float(y1), 9),
                round(float(scale), 9),
                round(float(offset), 9),
                self._highlighted_key,
            )
        if signature == self._axis_last_signature:
            return
        self._axis_last_signature = signature
        ax = self.plot.getPlotItem().getAxis("left")
        ax.setTicks([ticks])
        ax.setPen(pg.mkPen(color))
        ax.setTextPen(pg.mkPen(color))
        self.plot.setLabel("left", label, color=color)

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
        return self._trace_units.get(key, CHANNEL_UNITS.get(key, ""))

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

    def _formula_unit(self, expr: str) -> str:
        text = expr.upper()
        if "INTG" in text or "INTEG" in text:
            return "J"
        if re.search(r"\bCH[1-6]\b", text) and "*" in text:
            return "W"
        for name in re.findall(r"\b(?:CH[1-6]|MATH\d+)\b", text):
            unit = self._trace_units.get(name) or CHANNEL_UNITS.get(name, "")
            if unit:
                return unit
        return ""

    @staticmethod
    def _physical_channel_units(profile: BridgeProfile) -> dict[str, str]:
        units: dict[str, str] = {}
        for channel, unit in (
            (profile.vge, "V"),
            (profile.vce, "V"),
            (profile.ic, "A"),
            (profile.irr, "A"),
            (profile.il, "A"),
            (profile.v_diode, "V"),
            (profile.vge_other, "V"),
        ):
            if channel:
                units[channel.upper()] = unit
        return units

    @staticmethod
    def _logical_display_key_map(profile: BridgeProfile) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for logical, channel in (
            ("vge", profile.vge),
            ("vce", profile.vce),
            ("ic", profile.ic),
            ("il", profile.il),
            ("irr", profile.irr),
            ("v_diode", profile.v_diode),
            ("vge_other", profile.vge_other),
        ):
            if channel:
                mapping[logical] = channel.upper()
        if profile.ic_from_sum_irr_il:
            mapping["ic"] = (profile.irr or profile.il or profile.ic).upper()
        if profile.irr_from_ic_minus_il:
            mapping["irr"] = (profile.irr or profile.ic or profile.il).upper()
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
        }
        roles: dict[str, list[str]] = {}
        display_map = logical_map or WaveformPlot._logical_display_key_map(profile)
        for logical, channel in display_map.items():
            if channel:
                roles.setdefault(channel, []).append(labels.get(logical, logical))
        if profile.ic_from_sum_irr_il:
            for channel in (profile.irr, profile.il):
                if channel:
                    role_list = roles.setdefault(channel.upper(), [])
                    if "Ic" in role_list:
                        role_list.remove("Ic")
                    if "Ic=Irr+IL" not in role_list:
                        role_list.append("Ic=Irr+IL")
        if profile.irr_from_ic_minus_il:
            for channel in (profile.ic, profile.il):
                if channel:
                    role_list = roles.setdefault(channel.upper(), [])
                    if "Irr" in role_list:
                        role_list.remove("Irr")
                    if "Irr=Ic-IL" not in role_list:
                        role_list.append("Irr=Ic-IL")
        return roles

    @staticmethod
    def _formula_tokens(expr: str) -> tuple[list[str], list[str]]:
        text = re.sub(r"\s+", "", expr.upper())
        tokens = re.findall(r"(?:CH[1-6]|MATH\d+)", text)
        ops = re.findall(r"[+\-*/]", text)
        return tokens, ops

    @staticmethod
    def _is_sum_formula(expr: str, a: str, b: str) -> bool:
        tokens, ops = WaveformPlot._formula_tokens(expr)
        return len(tokens) == 2 and set(tokens) == {a.upper(), b.upper()} and ops == ["+"]

    @staticmethod
    def _is_difference_formula(expr: str, a: str, b: str) -> bool:
        tokens, ops = WaveformPlot._formula_tokens(expr)
        return tokens == [a.upper(), b.upper()] and ops == ["-"]

    def _prefer_math_display_keys_for_derived_currents(
        self,
        profile: BridgeProfile,
        formulas: dict[str, str],
    ) -> None:
        """Bind derived logical currents to visible TSS Math traces when available."""
        if profile.ic_from_sum_irr_il and profile.irr and profile.il:
            for key, expr in formulas.items():
                if self._is_sum_formula(expr, profile.irr, profile.il):
                    self._logical_display_keys["ic"] = key.upper()
                    break
        if profile.irr_from_ic_minus_il and profile.ic and profile.il:
            for key, expr in formulas.items():
                if self._is_difference_formula(expr, profile.ic, profile.il):
                    self._logical_display_keys["irr"] = key.upper()
                    break

    def _display_key_for_channel(self, channel: str) -> str:
        logical = channel.strip().lower()
        if logical in self._logical_display_keys:
            return self._logical_display_keys[logical]
        return channel.upper()

    def _logical_role_for_source(self, source_key: str) -> str:
        source_key = source_key.upper()
        for logical, display_key in self._logical_display_keys.items():
            if display_key == source_key:
                return logical
        return source_key.lower()

    def mapping_role_for_source(self, source_key: str) -> str:
        source_key = source_key.upper()
        for logical, display_key in self._logical_display_keys.items():
            if display_key == source_key:
                return logical
        return ""

    def request_channel_mapping(self, source_key: str, logical_role: str) -> None:
        self.channelMappingRequested.emit(source_key.upper(), logical_role)

    def _formula_eval_context(self, target_key: str) -> dict[str, np.ndarray | float]:
        ctx: dict[str, np.ndarray | float] = {}
        for name, arr in self._formula_sources.items():
            if name.upper() != target_key.upper():
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

    def _add_trace_item(
        self, key: str, raw: np.ndarray, legend: str, color: str, width: float
    ) -> None:
        if self._trace_t_us is None:
            return
        raw = np.asarray(raw, dtype=np.float64)
        self._trace_raw[key] = raw
        if key in self._manual_vdiv:
            scale = float(self._manual_vdiv[key])
            if not _is_math_trace_key(key) and not _waveform_fits_at_center(raw, scale):
                scale = _auto_vdiv_for_channel(key, raw)
        else:
            scale = _auto_vdiv_for_channel(key, raw)
        self._disp_scale[key] = scale
        self._disp_offset[key] = _auto_center_offset_div(raw, scale)
        item = self.plot.plot(
            self._trace_t_us,
            raw / scale + self._disp_offset[key],
            pen=pg.mkPen(color, width=width),
        )
        item.setZValue(0)
        self._trace_items[key] = item
        self._trace_style[key] = (color, width)
        self._trace_legend[key] = legend
        if len(raw):
            self._trace_yrange[key] = (float(np.nanmin(raw)), float(np.nanmax(raw)))
        else:
            self._trace_yrange[key] = (0.0, 0.0)

    def _set_math_formula(self, key: str, expr: str) -> None:
        key = key.upper()
        expr = self._normalize_formula(expr)
        if self._formula_t_s is None:
            raise ValueError("No waveform time base is loaded.")
        raw_full = self._evaluate_math_formula(key, expr)
        _t_disp, arrs = _downsample(self._formula_t_s, raw_full)
        raw = np.asarray(arrs[0], dtype=np.float64)
        self._math_formulas[key] = expr
        self._math_source_keys.add(key)
        self._formula_sources[key] = raw_full
        self._trace_units[key] = self._formula_unit(expr)
        if key not in self._trace_items:
            self._add_trace_item(key, raw, key.title().replace("Math", "Math "), _math_color(key), 1.5)
            self._build_channel_bar()
            return
        self._trace_raw[key] = raw
        self._trace_yrange[key] = (float(np.nanmin(raw)), float(np.nanmax(raw))) if len(raw) else (0.0, 0.0)
        self._disp_scale[key] = _auto_vdiv_for_channel(key, raw)
        self._disp_offset[key] = _auto_center_offset_div(raw, self._disp_scale[key])
        self._trace_items[key].setData(self._trace_t_us, raw / self._disp_scale[key] + self._disp_offset[key])
        self._refresh_legend_styles()
        self._update_zero_handle_positions()
        self._update_y_ticks()

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
        if is_new_source:
            self._loaded_source_path = source
            self.reset_interaction_state()
            saved_offset: dict[str, float] = {}
            self._math_formulas.clear()
            self._math_source_keys.clear()
            self._manual_vdiv.clear()
            for ch, scale in bundle.meta.channel_vdiv.items():
                ch_key = ch.upper()
                if re.fullmatch(r"(CH[1-6]|MATH\d+)", ch_key):
                    self._manual_vdiv[ch_key] = float(scale)
        else:
            saved_offset = dict(self._disp_offset) if self._trace_items else {}
        self._soft_clear()
        self._disp_offset.clear()
        self._user_x_us_per_div = None
        t = bundle.t
        vge = bundle.get(profile.vge)
        vce = bundle.get(profile.vce)
        ic = bundle_total_current(bundle, profile)
        irr = bundle_reverse_recovery_current(bundle, profile)
        v_diode = bundle.get(profile.v_diode)
        vge_other = bundle.get(profile.vge_other)
        self._interactive_vce_t_us = t * 1e6
        self._interactive_vce = vce
        self._interactive_irr_t_us = t * 1e6
        self._interactive_irr = irr
        self._interactive_ic_t_us = t * 1e6
        self._interactive_ic = ic
        self._interactive_dt = float(bundle.dt)

        source_items = [
            (ch.upper(), np.asarray(raw, dtype=np.float64))
            for ch, raw in bundle.channels.items()
            if re.fullmatch(r"(CH[1-6]|MATH\d+)", ch.upper())
        ]
        source_items.sort(key=lambda item: _source_channel_sort_key(item[0]))
        downsampled = _downsample(t, *(raw for _ch, raw in source_items))
        t_us = downsampled[0] * 1e6
        source_downsampled = [
            np.asarray(arr, dtype=np.float64) for arr in downsampled[1]
        ]
        self._trace_items.clear()
        self._trace_style.clear()
        self._trace_yrange.clear()
        self._trace_legend.clear()
        self._trace_units.clear()
        self._disp_scale.clear()
        self._trace_raw.clear()
        self._formula_sources.clear()
        self._formula_t_s = np.asarray(t, dtype=np.float64)
        self._trace_t_us = t_us
        imported_math_formulas = {
            ch.upper(): self._normalize_formula(expr)
            for ch, expr in bundle.meta.channel_math_formulas.items()
        }
        self._logical_display_keys = self._logical_display_key_map(profile)
        self._base_logical_display_keys = dict(self._logical_display_keys)
        self._prefer_math_display_keys_for_derived_currents(
            profile, imported_math_formulas
        )
        self._display_channel_roles = self._build_display_channel_roles(
            profile, self._logical_display_keys
        )
        source_units = self._physical_channel_units(profile)
        for (key, _raw_full), data in zip(source_items, source_downsampled):
            if _is_math_trace_key(key):
                color, width = _math_color(key), 1.5
            else:
                color, width = WAVEFORM_TRACE_STYLES.get(
                    self._logical_role_for_source(key),
                    (_math_color(key), 1.5),
                )
            legend = _source_channel_legend(key, bundle.meta.channel_labels)
            raw = np.asarray(data, dtype=np.float64)
            self._trace_raw[key] = raw
            expr = imported_math_formulas.get(key)
            self._trace_units[key] = (
                self._formula_unit(expr) if expr else source_units.get(key, "")
            )
            if key in self._manual_vdiv:
                scale = float(self._manual_vdiv[key])
                if not _is_math_trace_key(key) and not _waveform_fits_at_center(raw, scale):
                    scale = _auto_vdiv_for_channel(key, raw)
            else:
                scale = _auto_vdiv_for_channel(key, raw)
            self._disp_scale[key] = scale
            if key in saved_offset:
                offset = float(saved_offset[key])
            else:
                offset = _auto_center_offset_div(raw, scale)
            self._disp_offset[key] = offset
            item = self.plot.plot(t_us, raw / scale + offset, pen=pg.mkPen(color, width=width))
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
        self._highlighted_key = None
        for key in list(self._trace_items):
            self._trace_units.setdefault(key, CHANNEL_UNITS.get(key, ""))

        for ch, raw_full in bundle.channels.items():
            ch_key = ch.upper()
            if not re.fullmatch(r"(CH[1-6]|MATH\d+)", ch_key):
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

        if result and result.segments:
            segs: SegmentIndices = result.segments
            edge_marks = [(segs.pulse1_off, "关断沿", WAVEFORM_EDGE_COLORS["off"])]
            if not result.single_pulse_mode:
                edge_marks.append(
                    (segs.pulse2_on, "开通沿", WAVEFORM_EDGE_COLORS["on"])
                )
            for idx, label, color in edge_marks:
                line = pg.InfiniteLine(
                    pos=t[idx] * 1e6,
                    angle=90,
                    pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine),
                    label=label,
                    labelOpts={"color": color, "position": 0.95},
                )
                self.plot.addItem(line)

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
        vb.setXRange(full_min, full_max, padding=0.0)
        # 纵向固定为 ±DISP_HALF_DIV 格（每通道按自身 V/div 缩放）
        self._apply_disp_yrange()
        self._update_x_ticks()

        # ---- 持久 4 根光标 ----
        if result and result.segments:
            a_us = float(t[result.segments.pulse1_off] * 1e6)
            b_us = float(t[result.segments.pulse2_on] * 1e6)
        else:
            a_us = full_min + 0.30 * full_span
            b_us = full_min + 0.70 * full_span
        peak_ic = float(np.max(np.abs(ic))) if len(ic) else 1.0
        self._install_persistent_cursors(a_us, b_us, peak_ic)
        self._update_zero_handle_positions()

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
            box.setToolTip(
                "左键单击：选中并置顶高亮\n"
                "左键双击：打开垂直设置面板（显示/刻度/位置）\n"
                "右键：打开通道菜单（删除数学通道/关闭波形显示）\n"
                "波形区内 0 值箭头：箭尾贴 Y 轴，垂直对齐 0V/0A 基准线，按住拖动调节垂直位置"
            )
            box.highlightClicked.connect(self._on_legend_clicked)
            box.verticalSettingsRequested.connect(self._show_channel_settings_panel)
            box.visibilityToggleRequested.connect(self._toggle_channel_visibility)
            box.contextMenuRequested.connect(self._show_channel_box_menu)
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
        QTimer.singleShot(0, self._update_zero_handle_positions)

    def _zero_handle_label(self, key: str, legend: str) -> str:
        text = legend.strip().lstrip("-━— ").strip()
        return text[:10] if text else key

    def _zero_handle_tooltip(self, key: str, legend: str) -> str:
        text = self._zero_handle_label(key, legend)
        unit = self._unit_for_channel(key)
        off = self._disp_offset.get(key, 0.0)
        try:
            idx = list(self._trace_items.keys()).index(key) + 1
            ch = f"C{idx}"
        except ValueError:
            ch = key
        return (
            f"{ch} · {text}\n"
            f"箭头垂直中心 = 该通道 0{unit} 基准线（垂直位置 {off:+.2f} 格），箭尾贴 Y 轴\n"
            "左键拖动：上下移动基准线"
        )

    def _vdiv_text(self, key: str) -> str:
        scale = self._disp_scale.get(key, 1.0)
        unit = self._unit_for_channel(key)
        if abs(scale - round(scale)) < 1e-9:
            return f"{int(round(scale))} {unit}/格"
        return f"{scale:g} {unit}/格"

    def _vdiv_text(self, key: str) -> str:
        scale = self._disp_scale.get(key, 1.0)
        unit = self._unit_for_channel(key)
        disp_scale = scale
        disp_unit = unit
        if unit == "J" and 0 < abs(scale) < 1.0:
            disp_scale = scale * 1000.0
            disp_unit = "mJ"
        if abs(disp_scale - round(disp_scale)) < 1e-9:
            return f"{int(round(disp_scale))} {disp_unit}/div"
        return f"{disp_scale:g} {disp_unit}/div"

    def _refresh_legend_styles(self) -> None:
        keys = list(self._channel_boxes.keys())
        for i, key in enumerate(keys):
            box = self._channel_boxes[key]
            color, _ = self._trace_style[key]
            legend = self._trace_legend[key]
            vdiv = self._vdiv_text(key)
            ch_tag = f"C{i + 1}"
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
                title_fg = "#85889a"
                scale_fg = "#626678"
                border = "#2d3040"
                body_bg = "#10111a"
                mark = " 关闭"
            else:
                title_bg = color if not dim else "#3b3f4f"
                scale_fg = "#f0f0f0" if highlighted else ("#8b8f9f" if dim else "#cfd3dc")
                border = "#f5f5f5" if highlighted else color
                body_bg = "#202230" if highlighted else "#151722"
                mark = " ◀" if highlighted else ""
            box.set_texts(
                f"<span style='font-weight:700;font-size:12px'>"
                f"{ch_tag} {legend}{mark}</span>",
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

    def _channel_menu_display_name(self, key: str) -> str:
        key = key.upper()
        math_match = re.fullmatch(r"MATH(\d+)", key)
        if math_match:
            return f"数学 {int(math_match.group(1))}"
        ch_match = re.fullmatch(r"CH(\d+)", key)
        if ch_match:
            return f"Ch {int(ch_match.group(1))}"
        legend = self._trace_legend.get(key, key).strip()
        return legend or key

    def _channel_menu_action_text(self, verb: str, key: str) -> str:
        name = self._channel_menu_display_name(key)
        spacer = " " if re.fullmatch(r"Ch \d+", name) else ""
        return f"{verb}{spacer}{name}"

    def _build_channel_box_menu(self, key: str) -> QMenu:
        key = key.upper()
        menu = QMenu(self)
        menu.setStyleSheet(_CHANNEL_CONTEXT_MENU_STYLE)

        hidden = key in self._hidden_channels
        visibility_text = self._channel_menu_action_text(
            "启用" if hidden else "禁用", key
        )
        visibility_action = QAction(visibility_text, menu)
        visibility_action.triggered.connect(
            lambda _checked=False, ch=key: self._toggle_channel_visibility(ch)
        )
        menu.addAction(visibility_action)

        configure_action = QAction(
            f"{self._channel_menu_action_text('配置', key)}...", menu
        )
        if _is_math_trace_key(key):
            configure_action.triggered.connect(
                lambda _checked=False, ch=key: self._show_math_formula_editor(ch)
            )
        else:
            configure_action.triggered.connect(
                lambda _checked=False, ch=key: self._show_channel_settings_panel(ch)
            )
        menu.addAction(configure_action)

        menu.addSeparator()
        label_action = QAction("标签...", menu)
        label_action.triggered.connect(
            lambda _checked=False, ch=key: self._show_channel_label_editor(ch)
        )
        menu.addAction(label_action)

        if _is_math_trace_key(key):
            menu.addSeparator()
            delete_action = QAction(
                self._channel_menu_action_text("删除", key), menu
            )
            delete_action.setEnabled(self._can_delete_channel(key))
            delete_action.triggered.connect(
                lambda _checked=False, ch=key: self._delete_math_channel(ch)
            )
            menu.addAction(delete_action)
        return menu

    def _show_channel_box_menu(self, key: str, global_pos: QPoint) -> None:
        if key not in self._trace_items:
            return
        menu = self._build_channel_box_menu(key)
        menu.exec(global_pos)

    def _can_delete_channel(self, key: str) -> bool:
        key = key.upper()
        return _is_math_trace_key(key) and key in self._trace_items

    def _show_channel_label_editor(self, key: str) -> None:
        key = key.upper()
        if key not in self._trace_items:
            return
        current = self._trace_legend.get(key, self._channel_menu_display_name(key))
        text, ok = QInputDialog.getText(
            self,
            "标签",
            f"{self._channel_menu_display_name(key)} 标签：",
            text=current,
        )
        if not ok:
            return
        label = text.strip()
        if not label:
            label = self._channel_menu_display_name(key)
        self._trace_legend[key] = label
        self._refresh_legend_styles()
        self._update_zero_handle_positions()
        self._sync_channel_bar_width()

    def _delete_math_channel(self, key: str) -> None:
        key = key.upper()
        if key not in self._trace_items or not self._can_delete_channel(key):
            return
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
            if self._highlighted_key == key:
                self._clear_highlight()
        self._refresh_legend_styles()
        self._refresh_zero_handle_styles()
        self._update_y_ticks()

    # ------------------------------------------------------------------ 每通道垂直位置 ----
    def _auto_center_channel(self, key: str) -> None:
        """按当前刻度将通道波形中点对齐 0 格。"""
        raw = self._trace_raw.get(key)
        scale = self._disp_scale.get(key, 1.0)
        if raw is None:
            return
        self._set_channel_offset(key, _auto_center_offset_div(raw, scale))

    def _set_channel_offset(self, key: str, offset: float, **_kwargs) -> None:
        if key not in self._trace_items or self._trace_t_us is None:
            return
        offset = float(max(-DISP_HALF_DIV, min(DISP_HALF_DIV, offset)))
        self._disp_offset[key] = offset
        raw = self._trace_raw.get(key)
        scale = self._disp_scale.get(key, 1.0)
        if raw is not None:
            self._trace_items[key].setData(self._trace_t_us, raw / scale + offset)
        self._refresh_legend_styles()
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
        for idx, key in enumerate(self._trace_items, start=1):
            color, _ = self._trace_style[key]
            legend = self._trace_legend[key]
            label = f"C{idx}"
            handle = ChannelZeroHandle(key, label, color, vb)
            handle.setToolTip(self._zero_handle_tooltip(key, legend))
            handle.clicked.connect(self._on_legend_clicked)
            handle.dragged.connect(self._on_zero_handle_dragged)
            scene.addItem(handle)
            self._zero_handles[key] = handle
        self._refresh_zero_handle_styles()
        self._update_zero_handle_positions()

    def _on_zero_handle_dragged(self, key: str, view_y: float) -> None:
        self._set_channel_offset(key, view_y)

    def _zero_handle_scene_pos(self, vb: pg.ViewBox, y_div: float) -> QPointF:
        """图元原点在箭尾平边，与 Y 轴（波形区左界）对齐，箭身向右展开。"""
        xr, _yr = vb.viewRange()
        axis_scene = vb.mapViewToScene(QPointF(float(xr[0]), y_div))
        return QPointF(axis_scene.x(), axis_scene.y())

    def _update_zero_handle_positions(self) -> None:
        if not self._zero_handles:
            return
        vb = self.plot.getPlotItem().getViewBox()
        for key, handle in self._zero_handles.items():
            hidden = key in self._hidden_channels
            handle.setVisible(not hidden)
            if hidden:
                continue
            # 显式按该通道原始 0V/0A 换算，确保标记始终指向通道归零值。
            y = float(self._to_disp(key, 0.0))
            pos = self._zero_handle_scene_pos(vb, y)
            handle.setPos(pos.x(), pos.y())
            legend = self._trace_legend.get(key, key)
            handle.setToolTip(self._zero_handle_tooltip(key, legend))

    def _refresh_zero_handle_styles(self) -> None:
        for key, handle in self._zero_handles.items():
            highlighted = (
                key not in self._hidden_channels and key == self._highlighted_key
            )
            handle.set_highlighted(highlighted)
            handle.setZValue(120 if highlighted else 100)

    def _on_legend_clicked(self, key: str) -> None:
        if key not in self._trace_items or key in self._hidden_channels:
            return
        if self._highlighted_key == key:
            self._clear_highlight()
        else:
            self._highlight_trace(key)

    # ------------------------------------------------------------------ 每通道 V/div ----
    def _vdiv_options(self, key: str) -> list[float]:
        cap = _vdiv_max_for_channel(key)
        return [float(v) for v in VDIV_LADDER if float(v) <= cap]

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
        raw = self._trace_raw.get(key)
        if raw is None:
            return
        if value is None:
            self._manual_vdiv.pop(key, None)
            scale = _auto_vdiv_for_channel(key, raw)
        else:
            scale = _pick_vdiv_ladder(float(value), key)
            self._manual_vdiv[key] = scale
        self._disp_scale[key] = scale
        self._auto_center_channel(key)

    def _dim_color(self, color: str, alpha: int = 70) -> QColor:
        c = QColor(color)
        c.setAlpha(alpha)
        return c

    def _highlight_trace(self, key: str) -> None:
        """仅高亮：选中波形置顶+加粗变亮，其余变暗。不改变纵轴量程。"""
        self._highlighted_key = key
        if self._interactive_mode not in self._BASE_TOP_SLOPE_MODES:
            if self._interactive_mode != "turn_on_current":
                self._active_channel = key
        for k, item in self._trace_items.items():
            color, width = self._trace_style[k]
            if k == key:
                item.setPen(pg.mkPen(color, width=width + 1.8))
                item.setZValue(20)
            else:
                item.setPen(pg.mkPen(self._dim_color(color, 60), width=width))
                item.setZValue(0)
        self._refresh_legend_styles()
        self._refresh_zero_handle_styles()
        self._update_y_ticks()

    def _clear_highlight(self) -> None:
        self._highlighted_key = None
        for k, item in self._trace_items.items():
            color, width = self._trace_style[k]
            item.setPen(pg.mkPen(color, width=width))
            item.setZValue(0)
        self._refresh_legend_styles()
        self._refresh_zero_handle_styles()
        self._update_y_ticks()

    # ------------------------------------------------------------------ 光标安装 ----
    def _install_persistent_cursors(self, a_us: float, b_us: float, peak_ic: float) -> None:
        # 加载新数据时回到 global 模式，解除任何残留锁定
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
            line = pg.InfiniteLine(
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
            line.setZValue(50)
            return line

        def _mk_hline(pos: float, color: str, label: str) -> pg.InfiniteLine:
            line = pg.InfiniteLine(
                pos=pos,
                angle=0,
                movable=True,
                pen=pg.mkPen(color, width=H_CURSOR_WIDTH, style=Qt.PenStyle.DashLine),
                hoverPen=pg.mkPen("#FFFFFF", width=H_CURSOR_WIDTH + 1, style=Qt.PenStyle.DashLine),
                label=label,
                labelOpts={
                    "color": color,
                    "position": 0.02,
                    "movable": False,
                    "fill": (0, 0, 0, 160),
                },
            )
            line.setZValue(50)
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
            self._h_cursor_a.setPen(pg.mkPen(CURSOR_PEN_A, width=H_CURSOR_WIDTH, style=Qt.PenStyle.DashLine))
            if not self._h_cursor_a_locked:
                self._h_cursor_a.setMovable(True)
        if self._h_cursor_b is None:
            self._h_cursor_b = _mk_hline(hb_y, CURSOR_PEN_B, "Hb")
            self.plot.addItem(self._h_cursor_b)
            self._h_cursor_b.sigPositionChanged.connect(self._on_horizontal_cursor_moved)
        else:
            self._h_cursor_b.setPos(hb_y)
            self._h_cursor_b.setMovable(True)
            self._h_cursor_b.setPen(pg.mkPen(CURSOR_PEN_B, width=H_CURSOR_WIDTH, style=Qt.PenStyle.DashLine))

        self._interactive_syncing = False
        self._update_readout()

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
        """示波器读数：固定 3 位小数 + 单位。"""
        return f"{value:.3f} {unit}"

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
        return "i" if unit == "A" else "v"

    @staticmethod
    def _cursor_plot_label_html(text: str, color: str) -> str:
        return (
            "<div style='background-color:rgba(30,30,46,230);padding:4px 8px;"
            "border-radius:6px;"
            f"color:{color};font-size:11px;line-height:1.35;"
            "font-family:Segoe UI,sans-serif'>"
            f"{text}</div>"
        )

    def _plot_label_y_bottom(self) -> float:
        vb = self.plot.getPlotItem().getViewBox()
        y0, y1 = vb.viewRange()[1]
        return y0 + 0.06 * (y1 - y0)

    def _plot_label_y_delta(self) -> float:
        """Δt 浮动框：贴近视图上沿，避免挡住中部波形。"""
        vb = self.plot.getPlotItem().getViewBox()
        y0, y1 = vb.viewRange()[1]
        return y1 - 0.12 * (y1 - y0)

    def _plot_label_x_left_edge(self) -> float:
        """横向光标读数框：贴在当前视图最左侧，避免压在波形中间。"""
        vb = self.plot.getPlotItem().getViewBox()
        x0, x1 = vb.viewRange()[0]
        span = max(x1 - x0, 1e-9)
        return x0 + 0.01 * span

    def _horizontal_cursor_plot_values(
        self, ha_div: float, hb_div: float, dt_us: float
    ) -> tuple[str, str, str | None]:
        """返回 Ha/Hb 单点 HTML 与 Δ/Δt 浮动框 HTML（示波器风格）。"""

        def _level_html(val: float, unit: str, color: str) -> str:
            sym = self._scope_wave_letter(unit)
            return self._cursor_plot_label_html(
                f"{sym}: {self._scope_quantity_text(val, unit)}", color
            )

        def _delta_html(dv: float, unit: str) -> str:
            sym = self._scope_wave_letter(unit)
            is_i = unit == "A"
            return self._cursor_plot_label_html(
                f"Δ {sym}: {self._scope_quantity_text(dv, unit)}<br/>"
                f"Δ {sym}/ Δ t: {self._scope_rate_text(dv, dt_us, is_current=is_i)}",
                "#CDD6F4",
            )

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
            ha_html = _level_html(ha_val, u_ha, CURSOR_PEN_A)
            hb_html = _level_html(hb_val, u_hb, CURSOR_PEN_B)
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
        ha_html = _level_html(ha_val, unit, CURSOR_PEN_A)
        hb_html = _level_html(hb_val, unit, CURSOR_PEN_B)
        return ha_html, hb_html, _delta_html(hb_val - ha_val, unit)

    def _remove_cursor_plot_labels(self) -> None:
        for attr in (
            "_cursor_a_t_label",
            "_cursor_b_t_label",
            "_cursor_ab_delta_label",
            "_cursor_ha_v_label",
            "_cursor_hb_v_label",
            "_cursor_hb_ha_delta_label",
        ):
            item = getattr(self, attr)
            if item is not None:
                self.plot.removeItem(item)
            setattr(self, attr, None)

    def _ensure_v_cursor_plot_labels(self) -> None:
        if self._cursor_a_t_label is None:
            self._cursor_a_t_label = pg.TextItem(anchor=(0.5, 1.0))
            self._cursor_a_t_label.setZValue(55)
            self.plot.addItem(self._cursor_a_t_label)
        if self._cursor_b_t_label is None:
            self._cursor_b_t_label = pg.TextItem(anchor=(0.5, 1.0))
            self._cursor_b_t_label.setZValue(55)
            self.plot.addItem(self._cursor_b_t_label)
        if self._cursor_ab_delta_label is None:
            self._cursor_ab_delta_label = pg.TextItem(anchor=(0.5, 1.0))
            self._cursor_ab_delta_label.setZValue(55)
            self.plot.addItem(self._cursor_ab_delta_label)

    def _position_v_cursor_plot_labels(self, a_us: float, b_us: float) -> None:
        if (
            self._cursor_a_t_label is None
            or self._cursor_b_t_label is None
            or self._cursor_ab_delta_label is None
        ):
            return
        y_bot = self._plot_label_y_bottom()
        y_delta = self._plot_label_y_delta()
        self._cursor_a_t_label.setPos(a_us, y_bot)
        self._cursor_b_t_label.setPos(b_us, y_bot)
        self._cursor_ab_delta_label.setPos(0.5 * (a_us + b_us), y_delta)

    def _update_v_cursor_plot_labels(self, a_us: float, b_us: float) -> None:
        """波形上 A/B 光标旁显示绝对时间与 Δt、1/Δt（示波器风格）。"""
        if self._cursor_a is None or self._cursor_b is None:
            self._remove_cursor_plot_labels()
            return
        self._ensure_v_cursor_plot_labels()
        dt_us = b_us - a_us
        freq_txt = self._freq_text_from_dt_us(dt_us)
        self._cursor_a_t_label.setHtml(
            self._cursor_plot_label_html(f"t: {a_us:.3f} µs", CURSOR_PEN_A)
        )
        self._cursor_b_t_label.setHtml(
            self._cursor_plot_label_html(f"t: {b_us:.3f} µs", CURSOR_PEN_B)
        )
        delta_html = self._cursor_plot_label_html(
            f"Δ t: {dt_us:.3f} µs<br/>1 / Δ t: {freq_txt}",
            "#CDD6F4",
        )
        self._cursor_ab_delta_label.setHtml(delta_html)
        self._position_v_cursor_plot_labels(a_us, b_us)
        self._cursor_a_t_label.show()
        self._cursor_b_t_label.show()
        self._cursor_ab_delta_label.show()

    def _ensure_h_cursor_plot_labels(self) -> None:
        if self._cursor_ha_v_label is None:
            self._cursor_ha_v_label = pg.TextItem(anchor=(0.0, 0.5))
            self._cursor_ha_v_label.setZValue(55)
            self.plot.addItem(self._cursor_ha_v_label)
        if self._cursor_hb_v_label is None:
            self._cursor_hb_v_label = pg.TextItem(anchor=(0.0, 0.5))
            self._cursor_hb_v_label.setZValue(55)
            self.plot.addItem(self._cursor_hb_v_label)
        if self._cursor_hb_ha_delta_label is None:
            self._cursor_hb_ha_delta_label = pg.TextItem(anchor=(0.0, 0.5))
            self._cursor_hb_ha_delta_label.setZValue(55)
            self.plot.addItem(self._cursor_hb_ha_delta_label)

    def _position_h_cursor_plot_labels(
        self, a_us: float, b_us: float, ha_div: float, hb_div: float
    ) -> None:
        if (
            self._cursor_ha_v_label is None
            or self._cursor_hb_v_label is None
            or self._cursor_hb_ha_delta_label is None
        ):
            return
        x_left = self._plot_label_x_left_edge()
        y_mid = 0.5 * (ha_div + hb_div)
        self._cursor_ha_v_label.setPos(x_left, ha_div)
        self._cursor_hb_v_label.setPos(x_left, hb_div)
        self._cursor_hb_ha_delta_label.setPos(x_left, y_mid)

    def _update_h_cursor_plot_labels(
        self, a_us: float, b_us: float, ha_div: float, hb_div: float, dt_us: float
    ) -> None:
        """Ha/Hb 旁显示物理量、Δv 与 Δv/Δt（Δt 取自纵向 A/B）。"""
        if self._h_cursor_a is None or self._h_cursor_b is None:
            for attr in (
                "_cursor_ha_v_label",
                "_cursor_hb_v_label",
                "_cursor_hb_ha_delta_label",
            ):
                item = getattr(self, attr)
                if item is not None:
                    item.hide()
            return
        self._ensure_h_cursor_plot_labels()
        ha_html, hb_html, delta_html = self._horizontal_cursor_plot_values(
            ha_div, hb_div, dt_us
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

    def _on_view_range_changed(self) -> None:
        self._update_zero_handle_positions()
        self._update_y_ticks()
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
        self._channel_bar.setFixedSize(max(content_w, view_w), bar_h)

    def _set_readout_text(self, txt: str) -> None:
        self._readout_label.setText(txt)
        self._sync_readout_scroll_width()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_readout_scroll_width()
        self._sync_channel_bar_width()

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
            txt = (
                f"<span style='color:{ca}'>A {a:9.3f}µs</span>&nbsp;"
                f"<span style='color:{cb}'>B {b:9.3f}µs</span>&nbsp;"
                f"Δt {dt_us:+9.3f}µs&nbsp;|&nbsp;"
                f"<span style='color:{ca}'>[{ha_tag}] Ha {ha_val:+10.2f}{ha_u}</span>&nbsp;"
                f"<span style='color:{cb}'>[{hb_tag}] Hb {hb_val:+10.2f}{hb_u}</span>"
            )
            self._set_readout_text(txt)
            return
        # Ha/Hb/Δy 按当前活动通道的真实单位显示
        ch = self._readout_channel()
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
            raw = self._trace_raw.get(self._display_key_for_channel("v_diode"))
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
        if self._interactive_mode == "turn_on_current":
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
            line = pg.InfiniteLine(
                pos=pos,
                angle=0,
                movable=True,
                pen=pg.mkPen(
                    CURSOR_PEN_ZERO, width=H_CURSOR_WIDTH, style=Qt.PenStyle.DotLine
                ),
                hoverPen=pg.mkPen(
                    "#FFFFFF", width=H_CURSOR_WIDTH + 1, style=Qt.PenStyle.DotLine
                ),
                label="H0",
                labelOpts={
                    "color": CURSOR_PEN_ZERO,
                    "position": 0.98,
                    "movable": False,
                    "fill": (0, 0, 0, 160),
                },
            )
            line.setZValue(51)
            self.plot.addItem(line)
            line.sigPositionChanged.connect(self._on_horizontal_cursor_moved)
            self._h_cursor_zero = line
        else:
            self._h_cursor_zero.setPos(pos)
            self._h_cursor_zero.setMovable(True)
            self._h_cursor_zero.show()

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
        self._interactive_on_change = on_change
        self._interactive_mode = "energy_loss"
        self._active_channel = self._energy_ha_channel
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
                _eon_ic_rise_start_index,
                _eoff_vce_ha_crossing_at_main_rise,
            )

            y_top = float(np.max(y_seg)) if len(y_seg) else float(level)
            if self._energy_rise_a_mode == "eoff_vce":
                _, t_cross = _eoff_vce_ha_crossing_at_main_rise(
                    t_seg, y_seg, float(level), self._interactive_dt, y_top
                )
                return float(t_cross)
            else:
                ix = _eon_ic_rise_start_index(
                    y_seg, float(level), anchor, self._interactive_dt, y_top
                )
            if ix < len(t_seg) - 1:
                y0, y1 = float(y_seg[ix]), float(y_seg[ix + 1])
                if y1 > y0:
                    frac = (float(level) - y0) / (y1 - y0)
                    frac = float(np.clip(frac, 0.0, 1.0))
                    return float(t_seg[ix] + frac * (t_seg[ix + 1] - t_seg[ix]))
                return float(t_seg[ix])
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
        """Err：Irm 主峰后下降沿与 Ha 交点（与 err_energy_markers 一致）。"""
        from dpt_extractor.metrics.iec_windows import (
            _err_irr_fall_cross_ha_t,
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
        t_cross = _err_irr_fall_cross_ha_t(
            t_seg, y_seg, float(ha_a), ipk_g, i1, self._interactive_dt
        )
        return float(t_cross) * 1e6

    def _err_vd_rise_crossing_us(
        self,
        hb_v: float,
        t_lo_us: float,
        t_hi_us: float,
        peak_us: float | None,
    ) -> float | None:
        """Err：Vd 主抬升沿与 Hb 交点（主峰前最后一次有效上升穿越）。"""
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
            from dpt_extractor.metrics.iec_windows import _eoff_ic_fall_start_index

            y_top = float(np.max(y_seg)) if len(y_seg) else float(level)
            ix = _eoff_ic_fall_start_index(
                y_seg, float(level), anchor, self._interactive_dt, y_top
            )
        elif use_fall_index and self._energy_fall_b_mode == "eon_vce_fall":
            from dpt_extractor.metrics.iec_windows import _eon_vce_hb_fall_start_index

            y_top = float(np.max(y_seg)) if len(y_seg) else float(level)
            ix = _eon_vce_hb_fall_start_index(
                y_seg, float(level), anchor, self._interactive_dt, y_top
            )
            if ix < len(t_seg) - 1:
                y0, y1 = float(y_seg[ix]), float(y_seg[ix + 1])
                if y0 > y1:
                    frac = (float(level) - y0) / (y1 - y0)
                    frac = float(np.clip(frac, 0.0, 1.0))
                    return float(t_seg[ix] + frac * (t_seg[ix + 1] - t_seg[ix]))
                return float(t_seg[ix])
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

    def _link_energy_loss_h_from_v(self, end: str) -> None:
        """拖动 A/B：Ha/Hb 跟随该时刻波形幅值（纵向→横向）。"""
        if end == "a" and self._cursor_a is not None and self._h_cursor_a is not None:
            t_us = float(self._cursor_a.value())
            ch = self._energy_ha_channel
            v = self._interp_channel(ch, t_us)
            if ch == "irr":
                v = abs(v)
            self._h_cursor_a.setPos(self._to_disp(ch, float(v)))
        elif end == "b" and self._cursor_b is not None and self._h_cursor_b is not None:
            t_us = float(self._cursor_b.value())
            ch = self._energy_hb_channel
            v = self._interp_channel(ch, t_us)
            if ch == "irr":
                v = abs(v)
            self._h_cursor_b.setPos(self._to_disp(ch, float(v)))

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
        if ha_ch == "irr":
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
        """A–B 窗口内绘图曲线（降采样后）的显示坐标峰值，与屏幕上波形对齐。"""
        channel = self._display_key_for_channel(channel)
        tt = self._trace_t_us
        raw = self._trace_raw.get(channel)
        if tt is None or raw is None or len(tt) == 0:
            return None
        t_lo, t_hi = (min(t0_us, t1_us), max(t0_us, t1_us))
        mask = (tt >= t_lo) & (tt <= t_hi)
        if not np.any(mask):
            return None
        scale = self._disp_scale.get(channel, 1.0) or 1.0
        offset = self._disp_offset.get(channel, 0.0)
        seg = np.asarray(raw[mask], dtype=np.float64)
        if use_abs:
            seg = np.abs(seg)
        y_plot = seg / float(scale) + float(offset)
        return float(np.max(y_plot))

    def _min_plot_y_in_window(
        self, channel: str, t0_us: float, t1_us: float
    ) -> float | None:
        """A–B 窗口内绘图曲线（降采样后）的显示坐标谷值，与屏幕上波形对齐。"""
        channel = self._display_key_for_channel(channel)
        tt = self._trace_t_us
        raw = self._trace_raw.get(channel)
        if tt is None or raw is None or len(tt) == 0:
            return None
        t_lo, t_hi = (min(t0_us, t1_us), max(t0_us, t1_us))
        mask = (tt >= t_lo) & (tt <= t_hi)
        if not np.any(mask):
            return None
        scale = self._disp_scale.get(channel, 1.0) or 1.0
        offset = self._disp_offset.get(channel, 0.0)
        y_plot = np.asarray(raw[mask], dtype=np.float64) / float(scale) + float(offset)
        return float(np.min(y_plot))

    def set_interval_peak_horizontal(
        self,
        y: float,
        channel: str = "ic",
        *,
        t0_us: float | None = None,
        t1_us: float | None = None,
    ) -> None:
        """interval-peak 模式下把 Ha 设到 A–B 窗内峰值（与屏幕波形对齐；用户仍可拖）。"""
        if not self._interval_max_hline_enabled or self._interval_peak_on_hb:
            return
        if self._h_cursor_a is None:
            return
        self._active_channel = channel
        y_disp = self._to_disp(channel, float(y))
        if t0_us is not None and t1_us is not None:
            plot_peak = self._peak_plot_y_in_window(channel, t0_us, t1_us)
            if plot_peak is not None:
                # 降采样曲线峰值可能低于全采样 max；Ha 不得低于算法给出的最大值
                y_disp = max(y_disp, plot_peak)
        self._interactive_syncing = True
        try:
            self._h_cursor_a.setPos(y_disp)
            self._h_cursor_a.setMovable(True)
            self._h_cursor_a_locked = False
        finally:
            self._interactive_syncing = False
        self._update_readout()

    def set_interval_peak_on_hb(self, y: float, channel: str = "irr") -> None:
        """Irr 模式：Hb 自动跟 A/B 区间内最大值（不可手拖）。"""
        if self._h_cursor_b is None:
            return
        self._active_channel = channel
        self._interactive_syncing = True
        try:
            self._h_cursor_b.setPos(self._to_disp(channel, float(y)))
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
        # B 需在开通段后段（~19µs）搜平稳交汇，段窗止于 turn_on 末时需向后延伸
        if len(tt) > i0 + 8:
            seg = ic_abs[i0 : i1 + 1]
            dt_s = self._turn_on_ic_dt_s()
            from dpt_extractor.metrics.plateau_level import _turn_on_rise_index

            rise = _turn_on_rise_index(seg, dt_s)
            t_rise = float(t_s[i0 + rise])
            i_ext = int(np.searchsorted(t_s, t_rise + 1.35e-6))
            i1 = max(i1, min(len(tt) - 1, i_ext))
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
            plot_hi = self._peak_plot_y_in_window(channel, t0_us, t1_us)
            plot_lo = self._min_plot_y_in_window(channel, t0_us, t1_us)
            if plot_hi is not None:
                ha_disp = plot_hi
            if plot_lo is not None:
                hb_disp = plot_lo
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
            if self._interactive_mode == "trr_measure":
                self._emit_trr_measure_changed()
                return
            if self._interactive_mode == "energy_loss":
                self._emit_energy_loss_changed()
                return
            if self._interactive_mode in {"interval", "irr_cross", "crosstalk"}:
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
        if self._interactive_mode == "trr_measure":
            self._emit_trr_measure_changed()
            return
        if self._interactive_mode == "energy_loss":
            sender = self.sender()
            self._interactive_syncing = True
            try:
                if sender is self._cursor_a:
                    self._link_energy_loss_h_from_v("a")
                elif sender is self._cursor_b:
                    self._link_energy_loss_h_from_v("b")
            finally:
                self._interactive_syncing = False
            self._emit_energy_loss_changed()
            self._update_readout()
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
            sender = self.sender()
            self._interactive_syncing = True
            try:
                if sender is self._h_cursor_a:
                    ta = self._sync_energy_a_from_ha()
                    if self._energy_rise_b_mode != "err_vd":
                        self._sync_energy_b_from_hb(ta)
                elif sender is self._h_cursor_b:
                    ta = (
                        float(self._cursor_a.value())
                        if self._cursor_a is not None
                        else None
                    )
                    self._sync_energy_b_from_hb(ta)
            finally:
                self._interactive_syncing = False
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
