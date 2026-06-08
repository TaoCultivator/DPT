"""Dark theme stylesheet for DPT extractor GUI."""

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
    background-color: #f2f3f5;
    color: #101014;
    selection-background-color: #28bce8;
    selection-color: #061014;
    border: 1px solid #6f7280;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    min-height: 24px;
    padding: 4px 8px;
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

# Section colors (dark-theme friendly, muted)
SECTION_OFF = "#6b4a2a"
SECTION_ON = "#3d5c34"
SECTION_RR = "#2a4a6b"
SECTION_ENERGY = "#5c5a2a"
TEXT_ON_SECTION = "#f5f5f5"

SUMMARY_STYLE = """
QLabel#summaryTitle { font-size: 15px; font-weight: bold; color: #89b4fa; }
QLabel#summaryValue { font-size: 20px; font-weight: bold; color: #a6e3a1; }
QLabel#summaryLabel { font-size: 12px; color: #a6adc8; }
"""

# Tek 示波器风格波形配色（高饱和、黑底对比）
WAVEFORM_PLOT_BG = "#000000"
WAVEFORM_PLOT_FG = "#e8e8e8"
WAVEFORM_GRID_ALPHA = 0.38

# (颜色, 线宽) — 对齐 CH1~CH6 典型色：黄/青/红/绿/橙/紫
WAVEFORM_TRACE_STYLES: dict[str, tuple[str, float]] = {
    "vge": ("#FFE600", 1.8),       # CH1 黄（被测管栅极）
    "vce": ("#00F5FF", 1.8),       # CH2 青
    "ic": ("#FF1010", 2.0),        # CH3 红（总电流）
    "irr": ("#00FF3C", 1.6),       # CH4 绿（Irr/IL）
    "v_diode": ("#FF8C00", 1.6),   # CH5 橙
    "vge_other": ("#C77DFF", 1.5), # CH6 紫（对管栅极，串扰电压）
}

WAVEFORM_EDGE_COLORS = {
    "off": "#FFB020",
    "on": "#00FF66",
}
