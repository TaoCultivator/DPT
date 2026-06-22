"""Dark theme stylesheet for DPT extractor GUI."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QComboBox


COMBO_POPUP_DARK_STYLESHEET = """
QAbstractItemView {
    background-color: #081719;
    color: #edf6ee;
    border: 1px solid #5a8b93;
    selection-background-color: #28bce8;
    selection-color: #061014;
    outline: 0;
}
QAbstractItemView::item {
    min-height: 26px;
    padding: 5px 9px;
    color: #edf6ee;
    background-color: #081719;
}
QAbstractItemView::item:hover {
    background-color: #123238;
    color: #ffffff;
}
QAbstractItemView::item:selected {
    background-color: #28bce8;
    color: #061014;
}
QAbstractItemView::item:disabled {
    color: #7a878c;
}
"""

COMBO_POPUP_LIGHT_STYLESHEET = """
QAbstractItemView {
    background-color: #f2f4f4;
    color: #101014;
    border: 1px solid #6d7478;
    selection-background-color: #28bce8;
    selection-color: #061014;
    outline: 0;
}
QAbstractItemView::item {
    min-height: 26px;
    padding: 5px 9px;
    color: #101014;
    background-color: #f2f4f4;
}
QAbstractItemView::item:hover {
    background-color: #dce6e8;
    color: #050607;
}
QAbstractItemView::item:selected {
    background-color: #28bce8;
    color: #061014;
}
QAbstractItemView::item:disabled {
    color: #747a7d;
}
"""


def apply_combo_popup_style(combo: QComboBox, *, light: bool = False) -> None:
    view = combo.view()
    view.setStyleSheet(
        COMBO_POPUP_LIGHT_STYLESHEET if light else COMBO_POPUP_DARK_STYLESHEET
    )
    palette = view.palette()
    if light:
        base = QColor("#f2f4f4")
        text = QColor("#101014")
    else:
        base = QColor("#081719")
        text = QColor("#edf6ee")
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.Window, base)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#28bce8"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#061014"))
    view.setPalette(palette)

DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
}
QPushButton {
    background-color: #45475a;
    color: #cdd6f4;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    min-height: 28px;
}
QPushButton:hover { background-color: #585b70; }
QPushButton:pressed { background-color: #313244; }
QComboBox, QDoubleSpinBox, QLineEdit {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 26px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #081719;
    color: #edf6ee;
    selection-background-color: #28bce8;
    selection-color: #061014;
    border: 1px solid #5a8b93;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 4px 8px;
    color: #edf6ee;
    background-color: #081719;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #123238;
    color: #ffffff;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #28bce8;
    color: #061014;
}
QComboBox QAbstractItemView::item:disabled {
    color: #7a878c;
}
QLabel { color: #bac2de; }
QToolTip {
    background-color: #fffdf5;
    color: #111827;
    border: 2px solid #28bce8;
    border-radius: 6px;
    padding: 8px 10px;
    opacity: 255;
    font-size: 13px;
}
QMenu {
    background-color: #f2f3f5;
    color: #101014;
    border: 1px solid #6f7280;
    padding: 6px 0;
}
QMenu::item {
    min-width: 160px;
    padding: 9px 32px 9px 18px;
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
QStatusBar {
    background-color: #181825;
    color: #a6adc8;
}
QSplitter::handle { background-color: #313244; width: 4px; }
QSplitter#mainSplitter::handle {
    background-color: #1a242c;
    width: 8px;
}
QTableWidget {
    background-color: #242436;
    color: #cdd6f4;
    gridline-color: #45475a;
    border: 1px solid #45475a;
    border-radius: 6px;
}
QTableWidget::item:selected {
    background-color: #28bce8;
    color: #061014;
}
QHeaderView::section {
    background-color: #313244;
    color: #cdd6f4;
    padding: 8px;
    border: none;
    font-weight: bold;
}
QWidget#resultPanel {
    background-color: #061112;
    border: 1px solid #31434b;
    border-radius: 6px;
}
QFrame#waveformPanel {
    background-color: #061112;
    border: 1px solid #31434b;
    border-radius: 6px;
}
QLabel#resultSummary {
    background-color: #081719;
    color: #d7e2dc;
    border: 1px solid #22464c;
    border-radius: 5px;
    padding: 4px 6px;
}
QFrame#offsetMeasurementPanel {
    background-color: #0b181a;
    border: 1px solid #284950;
    border-radius: 5px;
}
QFrame#offsetMeasurementPanel QLabel#offsetActionLabel {
    color: #d7e2dc;
    font-weight: 700;
}
QFrame#offsetMeasurementPanel QPushButton#offsetMeasureButton {
    background-color: #c9cece;
    color: #111827;
    border: 1px solid #7d8488;
    border-radius: 5px;
    padding: 5px 14px;
    min-height: 28px;
}
QTableWidget#resultDataTable {
    background-color: #081314;
    color: #eff6f0;
    gridline-color: #334244;
    border: 1px solid #284950;
    border-radius: 5px;
    selection-background-color: #25c3d6;
    selection-color: #061112;
    outline: 0;
}
QTableWidget#resultDataTable::item {
    padding: 0 2px;
}
QTableWidget#resultDataTable::item:selected {
    background-color: #22b8cc;
    color: #061112;
}
QTableWidget#resultDataTable QHeaderView::section {
    background-color: #1c3539;
    color: #edf6ee;
    border: none;
    border-right: 1px solid #2d474a;
    border-bottom: 1px solid #2d474a;
    padding: 2px 4px;
    font-weight: bold;
}
QTableWidget#resultDataTable QScrollBar:vertical {
    background: #071113;
    width: 9px;
    margin: 2px 1px 2px 1px;
    border: none;
}
QTableWidget#resultDataTable QScrollBar::handle:vertical {
    background: #2db6c2;
    min-height: 28px;
    border-radius: 4px;
}
QTableWidget#resultDataTable QScrollBar::handle:vertical:hover {
    background: #47d7df;
}
QTableWidget#resultDataTable QScrollBar::add-line:vertical,
QTableWidget#resultDataTable QScrollBar::sub-line:vertical {
    height: 0;
    border: none;
    background: transparent;
}
QTableWidget#resultDataTable QScrollBar::add-page:vertical,
QTableWidget#resultDataTable QScrollBar::sub-page:vertical {
    background: transparent;
}
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
"""

# Section colors (scope-inspired, muted but distinct)
SECTION_OFF = "#3c3119"
SECTION_ON = "#143d32"
SECTION_RR = "#173a55"
SECTION_ENERGY = "#4a421b"
SECTION_SHORT = "#244033"
SECTION_SHORT_DUT = "#1f4c34"
SECTION_SHORT_OTHER = "#1f4358"
TEXT_ON_SECTION = "#f2f7f1"

SUMMARY_STYLE = """
QLabel#summaryTitle { font-size: 15px; font-weight: bold; color: #89b4fa; }
QLabel#summaryValue { font-size: 20px; font-weight: bold; color: #a6e3a1; }
QLabel#summaryLabel { font-size: 12px; color: #a6adc8; }
"""

# Tek 示波器风格波形配色（高饱和、黑底对比）
WAVEFORM_PLOT_BG = "#000000"
WAVEFORM_PLOT_FG = "#e8e8e8"
WAVEFORM_GRID_ALPHA = 0.38

# (颜色, 线宽) — 按示波器源通道色表：CH1~CH8 / MATH1~MATH8
WAVEFORM_TRACE_STYLES: dict[str, tuple[str, float]] = {
    "CH1": ("#FFF53B", 1.8),
    "CH2": ("#20CFD3", 1.8),
    "CH3": ("#EA4460", 1.9),
    "CH4": ("#91CE32", 1.8),
    "CH5": ("#FF9832", 1.8),
    "CH6": ("#2626BF", 1.8),
    "CH7": ("#E254A6", 1.8),
    "CH8": ("#00E09B", 1.8),
    "MATH1": ("#008000", 1.5),
    "MATH2": ("#A62323", 1.5),
    "MATH3": ("#FF0000", 1.5),
    "MATH4": ("#789ED3", 1.5),
    "MATH5": ("#936756", 1.5),
    "MATH6": ("#6E2B85", 1.5),
    "MATH7": ("#A62323", 1.5),
    "MATH8": ("#96B03C", 1.5),
}

WAVEFORM_EDGE_COLORS = {
    "off": "#FFB020",
    "on": "#00FF66",
}
