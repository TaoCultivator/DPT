"""示波器风格通道垂直设置浮窗（双击底部通道盒弹出）。

布局参考 Tektronix 垂直设置面板：标题色条 + 「显示 / 垂直刻度 / 位置」分块，
每个控件采用「标题在上、控件在下」的示波器排版。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dpt_extractor.gui.waveform_plot import (
    DISP_HALF_DIV,
    VDIV_LADDER,
    _pick_vdiv_ladder,
    _vdiv_max_for_channel,
)

if TYPE_CHECKING:
    from dpt_extractor.gui.waveform_plot import WaveformPlot

_PANEL_STYLE = """
QDialog#ChannelSettingsPanel {
    background-color: transparent;
    border: none;
}
QFrame#chPanelFrame {
    background-color: rgba(126, 126, 126, 218);
    border: 3px solid rgba(255, 73, 88, 235);
    border-radius: 2px;
}
QFrame#chPanelBody {
    background-color: rgba(142, 142, 138, 224);
}
QWidget#chPanelCell, QWidget#chPanelRow {
    background-color: transparent;
    color: #101010;
}
QDialog#ChannelSettingsPanel QLabel { color: #101010; }
QLabel#chPanelHeader {
    color: #f4f4f4;
    background-color: rgba(55, 55, 58, 225);
    font-size: 14px;
    font-weight: bold;
    padding: 9px 12px;
    letter-spacing: 1px;
}
QLabel#chPanelSection {
    color: #080808;
    background-color: rgba(225, 225, 225, 232);
    border-top: 1px solid rgba(255, 255, 255, 185);
    border-bottom: 1px solid rgba(82, 82, 82, 140);
    font-size: 14px;
    font-weight: bold;
    padding: 10px 12px;
}
QLabel#chCellCaption {
    color: #050505;
    background-color: transparent;
    font-size: 14px;
    font-weight: bold;
    padding: 0 0 2px 2px;
}
QPushButton#chToggleOn, QPushButton#chToggleOff {
    min-width: 58px;
    min-height: 34px;
    border: 1px solid rgba(95, 95, 95, 210);
    border-radius: 4px;
    background-color: rgba(232, 232, 232, 235);
    color: #1a1a1a;
    font-size: 14px;
}
QPushButton#chToggleOn:checked {
    background-color: #28bce8;
    color: #101010;
    border-color: #5de6ff;
}
QPushButton#chToggleOff:checked {
    background-color: #28bce8;
    color: #101010;
    border-color: #5de6ff;
}
QPushButton#chStepBtn {
    min-width: 42px;
    max-width: 42px;
    min-height: 34px;
    padding: 0;
    border: 1px solid rgba(95, 95, 95, 210);
    border-radius: 3px;
    background-color: rgba(238, 238, 238, 240);
    color: #1a1a1a;
    font-size: 14px;
}
QPushButton#chStepBtn:hover { background-color: #eaeaea; }
QPushButton#chStepBtn:pressed { background-color: #cccccc; }
QPushButton#chZeroBtn {
    min-height: 34px;
    padding: 4px 14px;
    border: 1px solid rgba(95, 95, 95, 210);
    border-radius: 3px;
    background-color: rgba(238, 238, 238, 240);
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
    min-height: 34px;
    background-color: rgba(246, 246, 246, 250);
    color: #050505;
    border: 1px solid rgba(95, 95, 95, 210);
    border-radius: 3px;
    padding: 2px 8px;
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
}
QLineEdit#chTagValue {
    min-height: 34px;
    background-color: rgba(246, 246, 246, 250);
    border: 1px solid rgba(95, 95, 95, 210);
    border-radius: 3px;
    padding: 2px 10px;
    font-size: 13px;
    color: #050505;
}
QPushButton#chApplyBtn {
    min-height: 34px;
    padding: 4px 12px;
    border: 1px solid #1599c7;
    border-radius: 3px;
    background-color: #28bce8;
    color: #101010;
    font-size: 13px;
    font-weight: bold;
}
QPushButton#chApplyBtn:hover { background-color: #44d4ff; }
QPushButton#chFormulaBtn {
    min-height: 34px;
    padding: 4px 12px;
    border: 1px solid #6f6f6f;
    border-radius: 3px;
    background-color: rgba(238, 238, 238, 245);
    color: #050505;
    font-size: 13px;
}
QPushButton#chFormulaBtn:hover { background-color: #ffffff; }
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


def _vdiv_options_for(key: str) -> list[float]:
    cap = _vdiv_max_for_channel(key)
    return [float(v) for v in VDIV_LADDER if float(v) <= cap]


def _vdiv_neighbor(cur: float, key: str, up: bool) -> float:
    opts = _vdiv_options_for(key)
    if not opts:
        return cur
    best_i = 0
    best_d = abs(opts[0] - cur)
    for i, v in enumerate(opts):
        d = abs(v - cur)
        if d < best_d:
            best_d = d
            best_i = i
    if up:
        return opts[min(best_i + 1, len(opts) - 1)]
    return opts[max(best_i - 1, 0)]


def _cell(caption: str, widget: QWidget) -> QWidget:
    """示波器风格单元：标题在上、控件在下。"""
    box = QWidget()
    box.setObjectName("chPanelCell")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    cap = QLabel(caption)
    cap.setObjectName("chCellCaption")
    lay.addWidget(cap)
    lay.addWidget(widget)
    return box


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
        self.setFixedWidth(430)

        ch_idx = list(plot._trace_items.keys()).index(key) + 1
        unit = plot._unit_for_channel(key)
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
        body_lay.setSpacing(6)

        sec = QLabel("垂直设置")
        sec.setObjectName("chPanelSection")
        sec.setContentsMargins(0, 0, 0, 0)
        body_lay.addWidget(sec)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        # --- 显示开关 ---
        disp_row = QHBoxLayout()
        disp_row.setContentsMargins(0, 0, 0, 0)
        disp_row.setSpacing(0)
        self._btn_on = QPushButton("开")
        self._btn_on.setObjectName("chToggleOn")
        self._btn_off = QPushButton("关")
        self._btn_off.setObjectName("chToggleOff")
        for btn in (self._btn_on, self._btn_off):
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
        self._btn_on.setChecked(not hidden)
        self._btn_off.setChecked(hidden)
        self._btn_on.clicked.connect(lambda: self._set_display(True))
        self._btn_off.clicked.connect(lambda: self._set_display(False))
        disp_row.addWidget(self._btn_on)
        disp_row.addWidget(self._btn_off)
        disp_w = QWidget()
        disp_w.setObjectName("chPanelRow")
        disp_w.setLayout(disp_row)
        grid.addWidget(_cell("显示", disp_w), 0, 0)

        # --- 垂直刻度 ---
        vdiv_row = QHBoxLayout()
        vdiv_row.setContentsMargins(0, 0, 0, 0)
        vdiv_row.setSpacing(4)
        self._vdiv_spin = QDoubleSpinBox()
        self._vdiv_spin.setDecimals(0)
        self._vdiv_spin.setRange(1.0, _vdiv_max_for_channel(key))
        self._vdiv_spin.setSuffix(f" {unit}/div")
        self._vdiv_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._vdiv_spin.setValue(plot._disp_scale.get(key, 1.0))
        self._vdiv_spin.valueChanged.connect(self._on_vdiv_changed)
        btn_up = QPushButton("▲")
        btn_dn = QPushButton("▼")
        for b in (btn_up, btn_dn):
            b.setObjectName("chStepBtn")
        btn_up.clicked.connect(lambda: self._step_vdiv(+1))
        btn_dn.clicked.connect(lambda: self._step_vdiv(-1))
        vdiv_row.addWidget(self._vdiv_spin, stretch=1)
        vdiv_row.addWidget(btn_up)
        vdiv_row.addWidget(btn_dn)
        vdiv_w = QWidget()
        vdiv_w.setObjectName("chPanelRow")
        vdiv_w.setLayout(vdiv_row)
        grid.addWidget(_cell("垂直刻度", vdiv_w), 0, 1)

        # --- 位置 ---
        pos_row = QHBoxLayout()
        pos_row.setContentsMargins(0, 0, 0, 0)
        pos_row.setSpacing(6)
        self._pos_spin = QDoubleSpinBox()
        self._pos_spin.setDecimals(2)
        self._pos_spin.setRange(-DISP_HALF_DIV, DISP_HALF_DIV)
        self._pos_spin.setSuffix(" divs")
        self._pos_spin.setSingleStep(0.5)
        self._pos_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._pos_spin.setValue(plot._disp_offset.get(key, 0.0))
        self._pos_spin.valueChanged.connect(self._on_pos_changed)
        btn_zero = QPushButton("设为 0")
        btn_zero.setObjectName("chZeroBtn")
        btn_zero.clicked.connect(self._on_pos_zero)
        pos_row.addWidget(self._pos_spin, stretch=1)
        pos_row.addWidget(btn_zero)
        pos_w = QWidget()
        pos_w.setObjectName("chPanelRow")
        pos_w.setLayout(pos_row)
        grid.addWidget(_cell("位置", pos_w), 1, 0, 1, 2)

        body_lay.addLayout(grid)

        # --- 标签（只编辑 TSS 标签；源通道名 CH/MATH 保持原始值）---
        self._label_edit = QLineEdit(plot._channel_labels.get(key.upper(), ""))
        self._label_edit.setObjectName("chTagValue")
        self._label_edit.setPlaceholderText(key.upper())
        self._label_edit.editingFinished.connect(self._on_label_changed)
        body_lay.addWidget(_cell("标签", self._label_edit))

        mapping_row = QHBoxLayout()
        mapping_row.setContentsMargins(0, 0, 0, 0)
        mapping_row.setSpacing(8)
        self._mapping_combo = QComboBox()
        for role, label in _MAPPING_OPTIONS:
            self._mapping_combo.addItem(label, role)
        current_role = plot.mapping_role_for_source(key)
        idx = self._mapping_combo.findData(current_role)
        if idx >= 0:
            self._mapping_combo.setCurrentIndex(idx)
        self._mapping_apply = QPushButton("应用映射")
        self._mapping_apply.setObjectName("chApplyBtn")
        self._mapping_apply.clicked.connect(self._on_mapping_apply)
        mapping_row.addWidget(self._mapping_combo, stretch=1)
        mapping_row.addWidget(self._mapping_apply)
        mapping_w = QWidget()
        mapping_w.setObjectName("chPanelRow")
        mapping_w.setLayout(mapping_row)
        body_lay.addWidget(_cell("DPT 映射", mapping_w))

        if key.upper().startswith("MATH"):
            formula_btn = QPushButton("编辑公式")
            formula_btn.setObjectName("chFormulaBtn")
            formula_btn.clicked.connect(self._on_formula_edit)
            body_lay.addWidget(_cell("数学通道", formula_btn))

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
        self._btn_on.setChecked(on)
        self._btn_off.setChecked(not on)

    def _on_vdiv_changed(self, value: float) -> None:
        scale = _pick_vdiv_ladder(float(value), self._key)
        if abs(scale - self._vdiv_spin.value()) > 1e-9:
            self._vdiv_spin.blockSignals(True)
            self._vdiv_spin.setValue(scale)
            self._vdiv_spin.blockSignals(False)
        self._plot._set_channel_scale(self._key, scale)

    def _step_vdiv(self, direction: int) -> None:
        cur = float(self._vdiv_spin.value())
        nxt = _vdiv_neighbor(cur, self._key, direction > 0)
        self._vdiv_spin.setValue(nxt)

    def _on_pos_changed(self, value: float) -> None:
        self._plot._set_channel_offset(self._key, float(value))

    def _on_pos_zero(self) -> None:
        self._pos_spin.setValue(0.0)

    def _on_auto_scale(self) -> None:
        self._plot._set_channel_scale(self._key, None)
        self._vdiv_spin.blockSignals(True)
        self._vdiv_spin.setValue(self._plot._disp_scale.get(self._key, 1.0))
        self._vdiv_spin.blockSignals(False)
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

    def sync_from_plot(self) -> None:
        """外部改刻度/位置后刷新控件。"""
        self._vdiv_spin.blockSignals(True)
        self._pos_spin.blockSignals(True)
        self._vdiv_spin.setValue(self._plot._disp_scale.get(self._key, 1.0))
        self._pos_spin.setValue(self._plot._disp_offset.get(self._key, 0.0))
        hidden = self._key in self._plot._hidden_channels
        self._btn_on.setChecked(not hidden)
        self._btn_off.setChecked(hidden)
        self._vdiv_spin.blockSignals(False)
        self._pos_spin.blockSignals(False)
