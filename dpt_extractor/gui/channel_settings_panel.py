"""示波器风格通道垂直设置浮窗（双击底部通道盒弹出）。

布局参考示波器垂直设置面板：深色标题、浅色分节、半透明灰底，
字段名贴近控件，弱边界分组避免视觉归属断裂。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dpt_extractor.gui.theme import apply_combo_popup_style
from dpt_extractor.gui.waveform_plot import (
    DISP_HALF_DIV,
    _scaled_div_value,
    _unit_factor_for_display_unit,
    _vdiv_unit_options,
)

if TYPE_CHECKING:
    from dpt_extractor.gui.waveform_plot import WaveformPlot

_PANEL_STYLE = """
QDialog#ChannelSettingsPanel {
    background-color: transparent;
    border: none;
}
QFrame#chPanelFrame {
    background-color: rgba(92, 95, 92, 238);
    border: 1px solid rgba(20, 28, 30, 220);
    border-radius: 2px;
}
QFrame#chPanelBody {
    background-color: rgba(134, 138, 132, 232);
}
QWidget#chPanelRow {
    background-color: transparent;
    color: #101010;
}
QDialog#ChannelSettingsPanel QLabel { color: #101010; }
QLabel#chPanelHeader {
    color: #f4f4f4;
    background-color: rgba(58, 59, 61, 235);
    font-size: 14px;
    font-weight: bold;
    padding: 9px 12px;
    letter-spacing: 1px;
}
QLabel#chPanelSection {
    color: #080808;
    background-color: rgba(226, 226, 226, 235);
    border-top: 1px solid rgba(255, 255, 255, 185);
    border-bottom: 1px solid rgba(82, 82, 82, 140);
    font-size: 14px;
    font-weight: bold;
    padding: 10px 12px;
}
QFrame#chSettingRow {
    background-color: rgba(121, 126, 121, 34);
    border: 1px solid rgba(44, 52, 52, 45);
    border-radius: 4px;
}
QLabel#chSettingCaption {
    color: #050505;
    background-color: transparent;
    font-size: 14px;
    font-weight: bold;
    padding: 0 0 1px 0;
}
QPushButton#chSwitchButton {
    min-width: 72px;
    max-width: 72px;
    min-height: 40px;
    max-height: 40px;
    padding: 0;
    border: none;
    background: transparent;
    color: #1a1a1a;
    font-size: 14px;
}
QPushButton#chStepBtn {
    min-width: 42px;
    max-width: 42px;
    min-height: 40px;
    max-height: 40px;
    padding: 0;
    border: 1px solid rgba(95, 95, 95, 210);
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #f2f2f2, stop:1 #c9cece);
    color: #1a1a1a;
    font-size: 14px;
}
QPushButton#chStepBtn:hover { background-color: #eaeaea; }
QPushButton#chStepBtn:pressed { background-color: #cccccc; }
QPushButton#chScaleStepBtn {
    min-width: 42px;
    max-width: 42px;
    min-height: 40px;
    max-height: 40px;
    padding: 0;
    border: 1px solid rgba(82, 91, 94, 225);
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #f2f2f2, stop:1 #c9cece);
    color: #071014;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#chScaleStepBtn:hover { background-color: #ffffff; }
QPushButton#chScaleStepBtn:pressed { background-color: #d3dddd; }
QPushButton#chZeroBtn {
    min-height: 40px;
    max-height: 40px;
    padding: 0 14px;
    border: 1px solid rgba(95, 95, 95, 210);
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #f2f2f2, stop:1 #c9cece);
    color: #1a1a1a;
    font-size: 13px;
}
QPushButton#chZeroBtn:hover { background-color: #eaeaea; }
QPushButton#chZeroBtn:pressed { background-color: #cccccc; }
QPushButton#chLinkBtn {
    border: none;
    background: transparent;
    color: #002838;
    font-size: 12px;
    font-weight: bold;
    text-align: left;
    padding: 3px 2px;
    min-height: 22px;
}
QPushButton#chLinkBtn:hover { color: #001f2e; text-decoration: underline; }
QDoubleSpinBox, QComboBox {
    min-height: 40px;
    max-height: 40px;
    background-color: rgba(241, 241, 241, 250);
    color: #050505;
    border: 1px solid rgba(95, 95, 95, 210);
    border-radius: 3px;
    padding: 0 8px;
    font-size: 13px;
}
QComboBox::drop-down {
    border-left: 1px solid rgba(95, 95, 95, 210);
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #f2f2f2;
    color: #050505;
    selection-background-color: #28bce8;
    selection-color: #050505;
    border: 2px solid #ff4958;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 4px 8px;
    color: #050505;
    background-color: #f2f2f2;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #dce6e8;
    color: #050505;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #28bce8;
    color: #050505;
}
QComboBox QAbstractItemView::item:disabled {
    color: #747a7d;
}
QFrame#vdivInputGroup {
    min-width: 190px;
    max-width: 220px;
    min-height: 42px;
    max-height: 42px;
    background-color: #f1f3f2;
    border: 1px solid #566367;
    border-radius: 4px;
}
QDoubleSpinBox#vdivValueSpin {
    min-height: 40px;
    max-height: 40px;
    background-color: transparent;
    color: #050505;
    border: none;
    border-right: 1px solid #c5cdcd;
    border-radius: 0;
    padding: 0 7px;
    font-size: 13px;
}
QComboBox#vdivUnitCombo {
    min-height: 40px;
    max-height: 40px;
    background-color: #ffffff;
    color: #071014;
    border: none;
    border-right: 1px solid #c5cdcd;
    border-radius: 0;
    padding: 0 18px 0 7px;
    font-size: 13px;
    font-weight: bold;
}
QComboBox#vdivUnitCombo::drop-down {
    width: 16px;
    border-left: 1px solid #d1d8d8;
    background-color: #e8eeee;
}
QComboBox#vdivUnitCombo QAbstractItemView {
    background-color: #f8faf9;
    color: #071014;
    selection-background-color: #28bce8;
    selection-color: #061014;
    border: 1px solid #566367;
    outline: 0;
}
QComboBox#vdivUnitCombo QAbstractItemView::item {
    min-height: 24px;
    padding: 5px 9px;
    color: #071014;
    background-color: #f8faf9;
}
QComboBox#vdivUnitCombo QAbstractItemView::item:hover {
    background-color: #e0eceb;
    color: #050607;
}
QComboBox#vdivUnitCombo QAbstractItemView::item:selected {
    background-color: #28bce8;
    color: #061014;
}
QLabel#vdivDivLabel {
    min-height: 40px;
    max-height: 40px;
    background-color: #edf2f1;
    color: #263438;
    font-size: 12px;
    font-weight: bold;
    padding: 0 7px;
}
QLineEdit#chTagValue, QLineEdit#chUnitEdit, QLineEdit#chFormulaValue {
    min-height: 40px;
    max-height: 40px;
    background-color: rgba(241, 241, 241, 250);
    border: 1px solid rgba(95, 95, 95, 210);
    border-radius: 3px;
    padding: 0 10px;
    font-size: 13px;
    color: #050505;
}
QLineEdit#chUnitEdit:disabled {
    background-color: rgba(222, 224, 221, 210);
    color: #606663;
}
QLineEdit#chFormulaValue {
    color: #182226;
    background-color: rgba(245, 247, 246, 250);
    selection-background-color: #28bce8;
}
QPushButton#chApplyBtn {
    min-height: 40px;
    max-height: 40px;
    padding: 0 12px;
    border: 1px solid #1599c7;
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #35d3f4, stop:1 #20afd8);
    color: #101010;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#chApplyBtn:hover { background-color: #44d4ff; }
QPushButton#chFormulaBtn {
    min-height: 40px;
    max-height: 40px;
    padding: 0 10px;
    border: 1px solid #6f6f6f;
    border-radius: 3px;
    background-color: rgba(238, 238, 238, 245);
    color: #050505;
    font-size: 13px;
}
QPushButton#chFormulaBtn:hover { background-color: #ffffff; }
QPushButton#chDeleteBtn {
    min-height: 40px;
    max-height: 40px;
    padding: 0 12px;
    border: 1px solid #9f4b4b;
    border-radius: 3px;
    background-color: rgba(245, 225, 225, 245);
    color: #6d1010;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#chDeleteBtn:hover { background-color: #ffe6e6; }
"""

_MAPPING_OPTIONS = (
    ("", "未映射"),
    ("vge", "Vge"),
    ("vce", "Vce"),
    ("ic", "Ic"),
    ("il", "IL"),
    ("irr", "Irr"),
    ("v_diode", "V_二极管"),
    ("vge_other", "对管Vge"),
)

_VDIV_VALUE_WIDTH = 76
_VDIV_UNIT_MIN_WIDTH = 80
_VDIV_UNIT_MAX_WIDTH = 96
_VDIV_DIV_WIDTH = 46


def _vdiv_display_decimals(value: float) -> int:
    value = abs(float(value))
    if value <= 0.0:
        return 0
    for decimals in range(0, 4):
        if abs(round(value, decimals) - value) < 1e-9:
            return decimals
    if value >= 1.0:
        return 3
    if value >= 1e-3:
        return 3
    if value >= 1e-6:
        return 6
    return 9


def _vdiv_neighbor(cur: float, up: bool) -> float:
    cur = max(abs(float(cur)), 1e-15)
    exp = int(math.floor(math.log10(cur)))
    candidates = sorted(
        step * (10.0**power)
        for power in range(exp - 3, exp + 4)
        for step in (1.0, 2.0, 5.0)
        if step * (10.0**power) > 0.0
    )
    eps = max(cur * 1e-9, 1e-15)
    if up:
        for value in candidates:
            if value > cur + eps:
                return float(value)
        return cur * 10.0
    for value in reversed(candidates):
        if value < cur - eps:
            return float(value)
    return cur / 10.0


class _ScopeSwitchButton(QPushButton):
    """示波器菜单风格滑块开关：文字固定，滑块随状态左右移动。"""

    _WIDTH = 72
    _HEIGHT = 40
    _KNOB_WIDTH = 24
    _RADIUS = 5

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(self._WIDTH, self._HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(self._WIDTH, self._HEIGHT)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        checked = self.isChecked()
        knob_x = track.right() - self._KNOB_WIDTH if checked else track.left()
        knob = QRectF(
            knob_x,
            track.top(),
            float(self._KNOB_WIDTH),
            track.height(),
        )

        body_grad = QLinearGradient(0.0, track.top(), 0.0, track.bottom())
        body_grad.setColorAt(0.0, QColor("#f1f1f1"))
        body_grad.setColorAt(1.0, QColor("#c9cece"))
        painter.setPen(QPen(QColor(92, 99, 101, 210), 1.0))
        painter.setBrush(body_grad)
        painter.drawRoundedRect(track, self._RADIUS, self._RADIUS)

        if checked:
            state_rect = QRectF(
                track.left(),
                track.top(),
                track.width() - self._KNOB_WIDTH + 1.0,
                track.height(),
            )
            state_text = "开"
        else:
            state_rect = QRectF(
                track.left() + self._KNOB_WIDTH - 1.0,
                track.top(),
                track.width() - self._KNOB_WIDTH + 1.0,
                track.height(),
            )
            state_text = "关"
        if checked:
            active_grad = QLinearGradient(0.0, state_rect.top(), 0.0, state_rect.bottom())
            active_grad.setColorAt(0.0, QColor("#35d3f4"))
            active_grad.setColorAt(1.0, QColor("#20afd8"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(active_grad)
            painter.drawRoundedRect(state_rect, self._RADIUS, self._RADIUS)
            painter.fillRect(
                QRectF(
                    state_rect.right() - self._RADIUS,
                    state_rect.top(),
                    float(self._RADIUS),
                    state_rect.height(),
                ),
                QColor("#20afd8"),
            )

        painter.setPen(QColor("#101010"))
        font = painter.font()
        font.setPointSize(12)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(state_rect, Qt.AlignmentFlag.AlignCenter, state_text)

        seam_x = knob.left() if checked else knob.right()
        painter.setPen(QPen(QColor(82, 91, 94, 135), 1.0))
        painter.drawLine(
            int(seam_x),
            int(track.top() + 6),
            int(seam_x),
            int(track.bottom() - 6),
        )

        knob_grad = QLinearGradient(0.0, knob.top(), 0.0, knob.bottom())
        if self.isDown():
            knob_grad.setColorAt(0.0, QColor("#d7dddd"))
            knob_grad.setColorAt(1.0, QColor("#c5cccc"))
        else:
            knob_grad.setColorAt(0.0, QColor("#f7f7f7"))
            knob_grad.setColorAt(1.0, QColor("#d5dddd"))
        painter.setPen(QPen(QColor(122, 128, 128, 210), 1.0))
        painter.setBrush(knob_grad)
        painter.drawRoundedRect(
            knob.adjusted(0.0, 0.0, -0.5, -0.5), self._RADIUS, self._RADIUS
        )


def _setting_row(caption: str, widget: QWidget, *, label_width: int = 0) -> QFrame:
    row = QFrame()
    row.setObjectName("chSettingRow")
    row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    lay = QVBoxLayout(row)
    lay.setContentsMargins(8, 4, 8, 5)
    lay.setSpacing(3)
    label = QLabel(caption)
    label.setObjectName("chSettingCaption")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    if label_width > 0:
        label.setFixedWidth(label_width)
    lay.addWidget(label)
    lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft)
    lay.addStretch(1)
    return row


def _sync_switch_button(button: QPushButton, checked: bool) -> None:
    button.setChecked(bool(checked))
    button.setText("开" if checked else "关")


class ChannelSettingsPanel(QDialog):
    """Tek 风格垂直设置：显示、垂直刻度、位置。"""

    def __init__(
        self,
        plot: "WaveformPlot",
        key: str,
        anchor_global: QPoint,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._plot = plot
        self._key = key
        self.setObjectName("ChannelSettingsPanel")
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(_PANEL_STYLE)
        self.setFixedWidth(420)

        ch_idx = list(plot._trace_items.keys()).index(key) + 1
        hidden = key in plot._hidden_channels

        dialog_lay = QVBoxLayout(self)
        dialog_lay.setContentsMargins(0, 0, 0, 0)
        dialog_lay.setSpacing(0)

        frame = QFrame()
        frame.setObjectName("chPanelFrame")
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        dialog_lay.addWidget(frame)

        root = QVBoxLayout(frame)
        root.setContentsMargins(3, 3, 3, 3)
        root.setSpacing(0)

        header = QLabel(f"CHANNEL {ch_idx}    {key}")
        header.setObjectName("chPanelHeader")
        root.addWidget(header)

        body = QFrame()
        body.setObjectName("chPanelBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(12, 0, 12, 12)
        body_lay.setSpacing(5)

        sec = QLabel("垂直设置")
        sec.setObjectName("chPanelSection")
        sec.setContentsMargins(0, 0, 0, 0)
        body_lay.addWidget(sec)

        top_settings = QHBoxLayout()
        top_settings.setContentsMargins(0, 0, 0, 0)
        top_settings.setSpacing(8)

        # --- 显示开关 ---
        disp_row = QHBoxLayout()
        disp_row.setContentsMargins(0, 0, 0, 0)
        disp_row.setSpacing(0)
        self._display_toggle = _ScopeSwitchButton()
        self._display_toggle.setObjectName("chSwitchButton")
        _sync_switch_button(self._display_toggle, not hidden)
        self._display_toggle.toggled.connect(self._set_display)
        disp_row.addWidget(self._display_toggle)
        disp_w = QWidget()
        disp_w.setObjectName("chPanelRow")
        disp_w.setFixedWidth(72)
        disp_w.setLayout(disp_row)
        self._display_setting = _setting_row("显示", disp_w, label_width=42)
        self._display_setting.setFixedWidth(90)
        top_settings.addWidget(self._display_setting, stretch=0)

        # --- 反相开关 ---
        inv_row = QHBoxLayout()
        inv_row.setContentsMargins(0, 0, 0, 0)
        inv_row.setSpacing(0)
        self._invert_toggle = _ScopeSwitchButton()
        self._invert_toggle.setObjectName("chSwitchButton")
        inverted = plot.channel_inversion_enabled(key)
        _sync_switch_button(self._invert_toggle, inverted)
        self._invert_toggle.toggled.connect(self._set_inverted)
        inv_row.addWidget(self._invert_toggle)
        inv_w = QWidget()
        inv_w.setObjectName("chPanelRow")
        inv_w.setFixedWidth(72)
        inv_w.setLayout(inv_row)
        self._invert_setting = _setting_row("反相", inv_w, label_width=42)
        self._invert_setting.setFixedWidth(90)
        top_settings.addWidget(self._invert_setting, stretch=0)

        # --- 自定义单位 ---
        unit_row = QHBoxLayout()
        unit_row.setContentsMargins(0, 0, 0, 0)
        unit_row.setSpacing(6)
        self._unit_toggle = _ScopeSwitchButton()
        self._unit_toggle.setObjectName("chSwitchButton")
        unit_override = plot.channel_unit_override(key)
        _sync_switch_button(self._unit_toggle, bool(unit_override))
        self._unit_edit = QLineEdit(unit_override or plot._unit_for_channel(key))
        self._unit_edit.setObjectName("chUnitEdit")
        self._unit_edit.setFixedWidth(54)
        self._unit_edit.setEnabled(bool(unit_override))
        self._unit_toggle.toggled.connect(self._set_unit_override)
        self._unit_edit.editingFinished.connect(self._on_unit_changed)
        unit_row.addWidget(self._unit_toggle)
        unit_row.addWidget(self._unit_edit)
        unit_row.addStretch(1)
        unit_w = QWidget()
        unit_w.setObjectName("chPanelRow")
        unit_w.setFixedWidth(132)
        unit_w.setLayout(unit_row)
        self._unit_setting = _setting_row("自定义单位", unit_w)
        self._unit_setting.setFixedWidth(150)
        top_settings.addWidget(self._unit_setting, stretch=0)
        top_settings.addStretch(1)
        body_lay.addLayout(top_settings)

        # --- 垂直刻度 ---
        vdiv_row = QHBoxLayout()
        vdiv_row.setContentsMargins(0, 0, 0, 0)
        vdiv_row.setSpacing(4)
        current_scale = float(plot._disp_scale.get(key, 1.0))
        self._vdiv_display_factor = 1.0
        self._vdiv_base_unit = plot._unit_for_channel(key)
        self._syncing_vdiv = False
        self._vdiv_spin = QDoubleSpinBox()
        self._vdiv_spin.setObjectName("vdivValueSpin")
        self._vdiv_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._vdiv_spin.setFixedWidth(_VDIV_VALUE_WIDTH)
        self._vdiv_spin.setRange(1e-99, 1e99)
        self._vdiv_unit_combo = QComboBox()
        self._vdiv_unit_combo.setObjectName("vdivUnitCombo")
        self._vdiv_unit_combo.setFixedWidth(_VDIV_UNIT_MIN_WIDTH)
        self._vdiv_unit_combo.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        apply_combo_popup_style(self._vdiv_unit_combo, light=True)
        div_label = QLabel("/div")
        div_label.setObjectName("vdivDivLabel")
        div_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        div_label.setFixedWidth(_VDIV_DIV_WIDTH)
        self._vdiv_input = QFrame()
        self._vdiv_input.setObjectName("vdivInputGroup")
        self._vdiv_input.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._vdiv_input.setFixedWidth(
            _VDIV_VALUE_WIDTH + _VDIV_UNIT_MIN_WIDTH + _VDIV_DIV_WIDTH
        )
        vdiv_input_lay = QHBoxLayout(self._vdiv_input)
        vdiv_input_lay.setContentsMargins(0, 0, 0, 0)
        vdiv_input_lay.setSpacing(0)
        vdiv_input_lay.addWidget(self._vdiv_spin)
        vdiv_input_lay.addWidget(self._vdiv_unit_combo)
        vdiv_input_lay.addWidget(div_label)
        self._sync_vdiv_spin_from_scale(current_scale)
        self._vdiv_spin.valueChanged.connect(self._on_vdiv_changed)
        self._vdiv_unit_combo.currentIndexChanged.connect(self._on_vdiv_unit_changed)
        btn_up = QPushButton("▲")
        btn_dn = QPushButton("▼")
        for b in (btn_up, btn_dn):
            b.setObjectName("chScaleStepBtn")
            b.setFixedSize(42, 40)
        btn_up.clicked.connect(lambda: self._step_vdiv(+1))
        btn_dn.clicked.connect(lambda: self._step_vdiv(-1))
        vdiv_row.addWidget(self._vdiv_input, stretch=0)
        vdiv_row.addWidget(btn_up, stretch=0)
        vdiv_row.addWidget(btn_dn, stretch=0)
        vdiv_row.addStretch(1)
        vdiv_w = QWidget()
        vdiv_w.setObjectName("chPanelRow")
        vdiv_w.setLayout(vdiv_row)
        self._vdiv_setting = _setting_row("垂直刻度", vdiv_w)
        body_lay.addWidget(self._vdiv_setting)

        # --- 位置 ---
        pos_row = QHBoxLayout()
        pos_row.setContentsMargins(0, 0, 0, 0)
        pos_row.setSpacing(10)
        self._pos_spin = QDoubleSpinBox()
        self._pos_spin.setDecimals(2)
        self._pos_spin.setRange(-DISP_HALF_DIV, DISP_HALF_DIV)
        self._pos_spin.setSuffix(" divs")
        self._pos_spin.setSingleStep(0.1)
        self._pos_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._pos_spin.setFixedWidth(92)
        self._pos_spin.setValue(plot._disp_offset.get(key, 0.0))
        self._pos_spin.valueChanged.connect(self._on_pos_changed)
        pos_up = QPushButton("▲")
        pos_dn = QPushButton("▼")
        for b in (pos_up, pos_dn):
            b.setObjectName("chStepBtn")
            b.setFixedSize(42, 40)
        pos_up.clicked.connect(lambda: self._step_position(+1))
        pos_dn.clicked.connect(lambda: self._step_position(-1))
        btn_zero = QPushButton("设为 0")
        btn_zero.setObjectName("chZeroBtn")
        btn_zero.setFixedSize(86, 40)
        btn_zero.clicked.connect(self._on_pos_zero)
        pos_row.addWidget(self._pos_spin, stretch=0)
        pos_row.addWidget(pos_up)
        pos_row.addWidget(pos_dn)
        pos_row.addWidget(btn_zero)
        pos_row.addStretch(1)
        pos_w = QWidget()
        pos_w.setObjectName("chPanelRow")
        pos_w.setLayout(pos_row)
        self._position_setting = _setting_row("位置", pos_w)
        body_lay.addWidget(self._position_setting)

        # --- 标签（只编辑 TSS 标签；源通道名 CH/MATH 保持原始值）---
        self._label_edit = QLineEdit(plot._channel_labels.get(key.upper(), ""))
        self._label_edit.setObjectName("chTagValue")
        self._label_edit.setPlaceholderText(key.upper())
        self._label_edit.setFixedWidth(180)
        self._label_edit.editingFinished.connect(self._on_label_changed)
        self._label_setting = _setting_row("标签", self._label_edit)
        body_lay.addWidget(self._label_setting)

        mapping_row = QHBoxLayout()
        mapping_row.setContentsMargins(0, 0, 0, 0)
        mapping_row.setSpacing(8)
        self._mapping_combo = QComboBox()
        apply_combo_popup_style(self._mapping_combo, light=True)
        for role, label in _MAPPING_OPTIONS:
            self._mapping_combo.addItem(label, role)
        current_role = plot.mapping_role_for_source(key)
        idx = self._mapping_combo.findData(current_role)
        if idx >= 0:
            self._mapping_combo.setCurrentIndex(idx)
        self._mapping_apply = QPushButton("应用映射")
        self._mapping_apply.setObjectName("chApplyBtn")
        self._mapping_apply.setFixedSize(104, 40)
        self._mapping_apply.clicked.connect(self._on_mapping_apply)
        self._mapping_combo.setFixedWidth(170)
        mapping_row.addWidget(self._mapping_combo, stretch=0)
        mapping_row.addWidget(self._mapping_apply)
        mapping_row.addStretch(1)
        mapping_w = QWidget()
        mapping_w.setObjectName("chPanelRow")
        mapping_w.setLayout(mapping_row)
        self._mapping_setting = _setting_row("DPT 映射", mapping_w)
        body_lay.addWidget(self._mapping_setting)

        if key.upper().startswith("MATH"):
            math_row = QHBoxLayout()
            math_row.setContentsMargins(0, 0, 0, 0)
            math_row.setSpacing(8)
            formula_text = plot._math_formulas.get(key.upper(), "")
            self._formula_value = QLineEdit(formula_text)
            self._formula_value.setObjectName("chFormulaValue")
            self._formula_value.setReadOnly(True)
            self._formula_value.setCursorPosition(0)
            self._formula_value.setFixedWidth(160)
            formula_btn = QPushButton("编辑")
            formula_btn.setObjectName("chFormulaBtn")
            formula_btn.setFixedSize(58, 40)
            formula_btn.clicked.connect(self._on_formula_edit)
            math_row.addWidget(self._formula_value)
            math_row.addWidget(formula_btn)
            if plot._can_delete_channel(key):
                delete_btn = QPushButton("删除 Math 通道")
                delete_btn.setObjectName("chDeleteBtn")
                delete_btn.setFixedSize(128, 40)
                delete_btn.clicked.connect(self._on_delete_math)
                math_row.addWidget(delete_btn)
            math_row.addStretch(1)
            math_w = QWidget()
            math_w.setObjectName("chPanelRow")
            math_w.setLayout(math_row)
            self._math_setting = _setting_row("数学通道", math_w)
            body_lay.addWidget(self._math_setting)

        # --- 快捷动作 ---
        links = QHBoxLayout()
        links.setContentsMargins(0, 4, 0, 0)
        links.setSpacing(16)
        btn_auto = QPushButton("自动适配刻度")
        btn_auto.setObjectName("chLinkBtn")
        btn_auto.clicked.connect(self._on_auto_scale)
        btn_center = QPushButton("中点对齐 0 格")
        btn_center.setObjectName("chLinkBtn")
        btn_center.clicked.connect(self._on_center)
        links.addWidget(btn_auto)
        links.addWidget(btn_center)
        links.addStretch(1)
        body_lay.addLayout(links)

        root.addWidget(body)
        self.adjustSize()
        self._place_above(anchor_global)

    def _place_above(self, box_top_left: QPoint) -> None:
        """在通道盒上方弹出，并约束在屏幕可见范围内。"""
        size = self.sizeHint()
        x = box_top_left.x()
        y = box_top_left.y() - size.height() - 6  # 盒子上方，留 6px 间隙

        screen = self.screen() or QGuiApplication.primaryScreen()
        rect: QRect = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        x = max(rect.left() + 4, min(x, rect.right() - size.width() - 4))
        if y < rect.top() + 4:
            # 上方放不下时退回到盒子下方
            y = box_top_left.y() + 6
        y = max(rect.top() + 4, min(y, rect.bottom() - size.height() - 4))
        self.move(x, y)

    def _set_display(self, on: bool) -> None:
        hidden = self._key in self._plot._hidden_channels
        if on and hidden:
            self._plot._toggle_channel_visibility(self._key)
        elif not on and not hidden:
            self._plot._toggle_channel_visibility(self._key)
        _sync_switch_button(self._display_toggle, on)

    def _set_inverted(self, enabled: bool) -> None:
        self._key = self._plot.set_channel_inversion_enabled(self._key, enabled)
        _sync_switch_button(self._invert_toggle, enabled)
        self._vdiv_base_unit = self._plot._unit_for_channel(self._key)
        self._sync_vdiv_spin_from_scale(self._plot._disp_scale.get(self._key, 1.0))

    def _set_unit_override(self, enabled: bool) -> None:
        self._unit_edit.setEnabled(enabled)
        _sync_switch_button(self._unit_toggle, enabled)
        if enabled:
            if not self._unit_edit.text().strip():
                self._unit_edit.setText(self._plot._unit_for_channel(self._key))
            self._on_unit_changed()
        else:
            self._plot.set_channel_unit_override(self._key, "")
            restored = self._plot._unit_for_channel(self._key)
            self._unit_edit.setText(restored)
            self._vdiv_base_unit = restored
            self._sync_vdiv_spin_from_scale(self._plot._disp_scale.get(self._key, 1.0))

    def _on_unit_changed(self) -> None:
        if not self._unit_edit.isEnabled():
            return
        unit = self._unit_edit.text().strip()
        self._plot.set_channel_unit_override(self._key, unit)
        self._vdiv_base_unit = self._plot._unit_for_channel(self._key)
        self._sync_vdiv_spin_from_scale(self._plot._disp_scale.get(self._key, 1.0))

    def _on_vdiv_changed(self, value: float) -> None:
        if self._syncing_vdiv:
            return
        scale = max(float(value) / self._vdiv_display_factor, 1e-15)
        self._plot._set_channel_scale(self._key, scale)
        self._sync_vdiv_spin_from_scale(self._plot._disp_scale.get(self._key, scale))

    def _on_vdiv_unit_changed(self, _index: int = 0) -> None:
        if self._syncing_vdiv:
            return
        unit = str(self._vdiv_unit_combo.currentData() or "")
        scale = float(self._plot._disp_scale.get(self._key, 1.0))
        self._sync_vdiv_spin_from_scale(scale, display_unit=unit)

    def _step_vdiv(self, direction: int) -> None:
        cur = float(self._plot._disp_scale.get(self._key, 1.0))
        nxt = _vdiv_neighbor(cur, direction > 0)
        self._plot._set_channel_scale(self._key, nxt)
        self._sync_vdiv_spin_from_scale(self._plot._disp_scale.get(self._key, nxt))

    def _on_pos_changed(self, value: float) -> None:
        self._plot._set_channel_offset(self._key, float(value))

    def _step_position(self, direction: int) -> None:
        self._pos_spin.setValue(float(self._pos_spin.value()) + 0.1 * float(direction))

    def _on_pos_zero(self) -> None:
        self._pos_spin.setValue(0.0)

    def _on_auto_scale(self) -> None:
        self._plot._set_channel_scale(self._key, None)
        self._sync_vdiv_spin_from_scale(self._plot._disp_scale.get(self._key, 1.0))
        self._pos_spin.setValue(self._plot._disp_offset.get(self._key, 0.0))

    def _on_center(self) -> None:
        self._plot._auto_center_channel(self._key)
        self._pos_spin.setValue(self._plot._disp_offset.get(self._key, 0.0))

    def _on_mapping_apply(self) -> None:
        role = self._mapping_combo.currentData()
        self._plot.request_channel_mapping(self._key, str(role or ""))
        self.close()

    def _on_label_changed(self) -> None:
        self._plot.set_channel_label(self._key, self._label_edit.text().strip())

    def _on_formula_edit(self) -> None:
        self.close()
        self._plot._show_math_formula_editor(self._key)

    def _on_delete_math(self) -> None:
        self.close()
        self._plot._delete_math_channel(self._key)

    def _sync_vdiv_spin_from_scale(
        self,
        scale: float,
        *,
        display_unit: str | None = None,
    ) -> None:
        unit = self._vdiv_base_unit
        if display_unit is None:
            display_value, display_unit, factor = _scaled_div_value(float(scale), unit)
        else:
            factor = _unit_factor_for_display_unit(display_unit, unit)
            display_value = float(scale) * factor
        self._vdiv_display_factor = float(factor)
        self._syncing_vdiv = True
        try:
            self._vdiv_spin.setDecimals(_vdiv_display_decimals(display_value))
            self._vdiv_spin.setValue(display_value)
            units = _vdiv_unit_options(display_unit, unit)
            self._vdiv_unit_combo.clear()
            for option in units:
                self._vdiv_unit_combo.addItem(option, option)
            self._resize_vdiv_unit_combo(units)
            idx = self._vdiv_unit_combo.findData(display_unit)
            if idx >= 0:
                self._vdiv_unit_combo.setCurrentIndex(idx)
        finally:
            self._syncing_vdiv = False

    def _resize_vdiv_unit_combo(self, units: list[str]) -> None:
        text_width = max(
            (
                self._vdiv_unit_combo.fontMetrics().horizontalAdvance(str(unit))
                for unit in units
            ),
            default=0,
        )
        width = max(
            _VDIV_UNIT_MIN_WIDTH,
            min(_VDIV_UNIT_MAX_WIDTH, text_width + 48),
        )
        self._vdiv_unit_combo.setFixedWidth(width)
        self._vdiv_input.setFixedWidth(_VDIV_VALUE_WIDTH + width + _VDIV_DIV_WIDTH)

    def sync_from_plot(self) -> None:
        """外部改刻度/位置后刷新控件。"""
        self._pos_spin.blockSignals(True)
        self._sync_vdiv_spin_from_scale(self._plot._disp_scale.get(self._key, 1.0))
        self._pos_spin.setValue(self._plot._disp_offset.get(self._key, 0.0))
        hidden = self._key in self._plot._hidden_channels
        _sync_switch_button(self._display_toggle, not hidden)
        self._pos_spin.blockSignals(False)
