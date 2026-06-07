"""示波器风格通道垂直设置浮窗（双击底部通道盒弹出）。

布局参考 Tektronix 垂直设置面板：标题色条 + 「显示 / 垂直刻度 / 位置」分块，
每个控件采用「标题在上、控件在下」的示波器排版。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dpt_extractor.gui.waveform_plot import (
    CHANNEL_UNITS,
    DISP_HALF_DIV,
    VDIV_LADDER,
    _pick_vdiv_ladder,
    _vdiv_max_for_channel,
)

if TYPE_CHECKING:
    from dpt_extractor.gui.waveform_plot import WaveformPlot

_PANEL_STYLE = """
QDialog#ChannelSettingsPanel {
    background-color: #d9d9d9;
    border: 1px solid #6f6f6f;
}
QDialog#ChannelSettingsPanel QLabel { color: #1a1a1a; }
QLabel#chPanelHeader {
    color: #ffffff;
    font-size: 14px;
    font-weight: bold;
    padding: 8px 12px;
    letter-spacing: 1px;
}
QLabel#chPanelSection {
    color: #2a2a2a;
    font-size: 13px;
    font-weight: bold;
    padding: 10px 12px 2px 12px;
}
QLabel#chCellCaption {
    color: #444444;
    font-size: 12px;
    padding: 0 0 2px 2px;
}
QPushButton#chToggleOn, QPushButton#chToggleOff {
    min-width: 48px;
    min-height: 30px;
    border: 1px solid #9a9a9a;
    border-radius: 3px;
    background-color: #f4f4f4;
    color: #1a1a1a;
    font-size: 13px;
}
QPushButton#chToggleOn:checked {
    background-color: #29a36a;
    color: #ffffff;
    border-color: #1d7a4f;
}
QPushButton#chToggleOff:checked {
    background-color: #c44545;
    color: #ffffff;
    border-color: #963232;
}
QPushButton#chStepBtn {
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    padding: 0;
    border: 1px solid #9a9a9a;
    border-radius: 3px;
    background-color: #f4f4f4;
    color: #1a1a1a;
    font-size: 13px;
}
QPushButton#chStepBtn:hover { background-color: #eaeaea; }
QPushButton#chStepBtn:pressed { background-color: #cccccc; }
QPushButton#chZeroBtn {
    min-height: 30px;
    padding: 4px 14px;
    border: 1px solid #9a9a9a;
    border-radius: 3px;
    background-color: #f4f4f4;
    color: #1a1a1a;
    font-size: 13px;
}
QPushButton#chZeroBtn:hover { background-color: #eaeaea; }
QPushButton#chZeroBtn:pressed { background-color: #cccccc; }
QPushButton#chLinkBtn {
    border: none;
    background: transparent;
    color: #0a5fa6;
    font-size: 12px;
    text-align: left;
    padding: 3px 2px;
    min-height: 22px;
}
QPushButton#chLinkBtn:hover { text-decoration: underline; }
QDoubleSpinBox {
    min-height: 30px;
    background-color: #ffffff;
    color: #1a1a1a;
    border: 1px solid #9a9a9a;
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 13px;
}
QLabel#chTagValue {
    background-color: #ffffff;
    border: 1px solid #9a9a9a;
    border-radius: 3px;
    padding: 6px 10px;
    font-size: 13px;
    color: #1a1a1a;
}
"""


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
        self.setStyleSheet(_PANEL_STYLE)
        self.setFixedWidth(320)

        ch_idx = list(plot._trace_items.keys()).index(key) + 1
        legend = plot._trace_legend.get(key, key).strip().lstrip("-━— ")
        color = plot._trace_style.get(key, ("#cdd6f4", 1.0))[0]
        unit = CHANNEL_UNITS.get(key, "")
        hidden = key in plot._hidden_channels

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QLabel(f"CHANNEL {ch_idx}")
        header.setObjectName("chPanelHeader")
        header.setStyleSheet(
            f"QLabel#chPanelHeader {{ background-color: {color}; }}"
        )
        root.addWidget(header)

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(12, 4, 12, 12)
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
        pos_w.setLayout(pos_row)
        grid.addWidget(_cell("位置", pos_w), 1, 0, 1, 2)

        body_lay.addLayout(grid)

        # --- 标签（只读，显示通道逻辑名）---
        tag_val = QLabel(legend)
        tag_val.setObjectName("chTagValue")
        body_lay.addWidget(_cell("标签", tag_val))

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
