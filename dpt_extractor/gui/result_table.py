from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path
import re

from PyQt6.QtCore import Qt, QSize, QRect
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QStylePainter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dpt_extractor.metrics.offset_measurement import (
    OFFSET_MEASUREMENT_SPECS,
    OFFSET_RANGE_OPTIONS,
)
from dpt_extractor.gui.slope_range_dialog import SlopeRangeDialog
from dpt_extractor.gui.theme import (
    SECTION_OFF,
    SECTION_ON,
    SECTION_RR,
    SECTION_SHORT,
    SECTION_SHORT_DUT,
    SECTION_SHORT_OTHER,
    TEXT_ON_SECTION,
    apply_combo_popup_style,
)
from dpt_extractor.models.results import ExtractResult
from dpt_extractor.models.slope_range import (
    CUSTOM_RANGE_LABEL,
    RR_DIDT_CUSTOM_IDM,
    RR_DIDT_CUSTOM_IF_IRM,
    SLOPE_RANGE_PRESETS,
    SLOPE_ROW_KEYS,
    SlopeRange,
    default_slope_ranges,
    normalize_slope_range,
    preset_index_for_range,
    preset_to_range,
)


_TEMP_LABELS = {
    "RT": "25℃",
    "HT": "150℃",
    "LT": "-40℃",
}

RESULT_PANEL_MARGIN = 4
RESULT_PANEL_SPACING = 4
RESULT_SUMMARY_HEIGHT = 76
RESULT_HEADER_HEIGHT = 24
RESULT_ROW_HEIGHT = 26
RESULT_TABLE_FONT_PX = 12
RESULT_PANEL_TARGET_WIDTH = 420
RESULT_COLUMN_DEFAULTS = (38, 112, 50, 80, 112)
RESULT_COLUMN_FILL_WEIGHTS = (0, 3, 0, 2, 2)
RESULT_OFFSET_PANEL_TARGET_WIDTH = 446
RESULT_OFFSET_COLUMN_DEFAULTS = (84, 106, 56, 86, 92)
RESULT_OFFSET_COLUMN_CAPS = (112, 120, 64, 100, 108)
RESULT_OFFSET_VALUE_BG = "#808080"
RESULT_OFFSET_TEXT = "#000000"
RESULT_OFFSET_GRID = "#2f555b"
RESULT_OFFSET_POPUP_SELECTED = "#d9e5e6"
RESULT_SCROLLBAR_RESERVE = 10
ENERGY_NAMES = {"Eoff", "Eon", "Err"}
ENERGY_TEXT_COLOR = "#ffd34d"
MISSING_VALUE_TEXT = "-"
MISSING_TEXT_COLOR = "#ff4d4d"
SECTION_ACTIVE_BG = "#22b8cc"
SECTION_ACTIVE_TEXT = "#061112"
SECTION_OFFSET = "#24545c"
PROCESS_SECTIONS = {"关断过程", "开通", "反向恢复", "短路过程", "偏移测量"}


def _result_font(family: str, *, bold: bool = False) -> QFont:
    font = QFont(family)
    font.setPixelSize(RESULT_TABLE_FONT_PX)
    font.setBold(bold)
    return font


def _fmt(v: float) -> str:
    if "E" in f"{v:.4e}" and abs(v) < 0.01:
        return f"{v:.4e}"
    if abs(v) >= 100:
        return f"{v:.2f}"
    if abs(v) >= 1:
        return f"{v:.3f}"
    return f"{v:.4f}"


def _fmt_energy(v: float) -> str:
    if v <= 0 or not (v == v):
        return "—"
    if v >= 100:
        return f"{v:.2f}"
    if v >= 1:
        return f"{v:.3f}"
    return f"{v:.4f}"


def _fmt_optional(v: float | None) -> str:
    if v is None:
        return "—"
    return _fmt(float(v))


def format_metric_display(section: str, name: str, value: float | None) -> str:
    """与 set_result 填表规则一致，避免交互写回时位数跳动。"""
    _ = section
    if value is None:
        return MISSING_VALUE_TEXT
    if name in {"Eoff", "Eon", "Err"}:
        return _fmt_energy(value)
    return _fmt(value)


def _range_label_for_row(section: str, name: str, result: ExtractResult) -> str:
    off, on, rr = result.turn_off, result.turn_on, result.reverse_recovery
    if result.short_circuit_mode:
        sc = result.short_circuit
        if section == "短路过程" and name == "短路时间Tsc":
            return sc.tsc_range or "A-B"
        if section == "短路过程" and name == "Desat动作时间":
            return sc.desat_range or "预留"
        if section == "短路过程" and name in {
            "短路电流Imax",
            "短路能量Esc_本管",
            "应力Vpeak_本管",
            "短路能量Esc_对管",
            "应力Vpeak_对管",
        }:
            return "Max"
    if section == "关断过程" and name == "dv/dt":
        return off.dvdt_range
    if section == "关断过程" and name == "di/dt":
        return off.didt_range
    if section == "开通" and name == "dv/dt":
        return on.dvdt_range
    if section == "开通" and name == "di/dt":
        return on.didt_range
    if section == "反向恢复" and name == "dv/dt":
        return rr.dvdt_range
    if section == "反向恢复" and name == "di/dt":
        return rr.didt_range
    if section == "关断过程" and name == "Eoff":
        return off.eoff_range
    return ""


def _path_parts(path: str) -> list[str]:
    return [p for p in re.split(r"[\\/]+", str(path)) if p]


def _infer_temp_code(path: str) -> str:
    for part in reversed(_path_parts(path)):
        stem = Path(part).stem.upper()
        for code in _TEMP_LABELS:
            if re.search(rf"(?<![A-Z0-9]){code}(?![A-Z0-9])", stem):
                return code
        if re.search(r"(?<!\d)25(?:℃|C|DEG)?(?!\d)", stem):
            return "RT"
        if re.search(r"(?<!\d)150(?:℃|C|DEG)?(?!\d)", stem):
            return "HT"
        if re.search(r"(?<!\d)-?40(?:℃|C|DEG)?(?!\d)", stem):
            return "LT"
    return ""


def _section_base_color(section: str) -> str:
    if section == "关断过程":
        return SECTION_OFF
    if section == "开通":
        return SECTION_ON
    if section == "反向恢复":
        return SECTION_RR
    if section == "短路过程":
        return SECTION_SHORT
    if section == "偏移测量":
        return SECTION_OFFSET
    return SECTION_OFF


def _section_stack_label(section: str) -> str:
    if section in PROCESS_SECTIONS:
        return "\n".join(section) if len(section) > 1 else section
    return section


def _offset_source_short_label(key: str) -> str:
    raw = str(key or "").upper()
    if m := re.fullmatch(r"CH(\d+)", raw):
        return f"Ch {m.group(1)}"
    if m := re.fullmatch(r"MATH(\d+)", raw):
        return f"Math {m.group(1)}"
    return raw


class _SectionTableItem(QTableWidgetItem):
    def __init__(self, section: str, display_text: str | None = None) -> None:
        super().__init__(display_text if display_text is not None else section)
        self._section_text = section

    def text(self) -> str:  # noqa: D102
        return self._section_text

    def setText(self, text: str) -> None:  # noqa: N802, D102
        self._section_text = text
        super().setText(text)


class _ResultCellDelegate(QStyledItemDelegate):
    def __init__(self, offset_mode: Callable[[], bool], parent: QWidget | None = None):
        super().__init__(parent)
        self._offset_mode = offset_mode

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        opt = QStyleOptionViewItem(option)
        if self._offset_mode():
            opt.state &= ~QStyle.StateFlag.State_Selected
            opt.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, opt, index)
        if not self._offset_mode():
            return
        painter.save()
        grid = QColor(RESULT_OFFSET_GRID)
        rect = option.rect
        painter.fillRect(QRect(rect.right(), rect.top(), 1, rect.height()), grid)
        painter.fillRect(QRect(rect.left(), rect.bottom(), rect.width(), 1), grid)
        painter.restore()


def _offset_combo_popup_style() -> str:
    return f"""
    QAbstractItemView {{
        background-color:#f2f4f4;
        color:#101014;
        border:1px solid #6d7478;
        selection-background-color:{RESULT_OFFSET_POPUP_SELECTED};
        selection-color:#101014;
        outline:0;
    }}
    QAbstractItemView::item {{
        min-height:26px;
        padding:5px 9px;
        color:#101014;
        background-color:#f2f4f4;
    }}
    QAbstractItemView::item:hover {{
        background-color:#e7eeee;
        color:#050607;
    }}
    QAbstractItemView::item:selected {{
        background-color:{RESULT_OFFSET_POPUP_SELECTED};
        color:#101014;
    }}
    QAbstractItemView::item:disabled {{
        color:#747a7d;
    }}
    """


class _CenteredCellComboBox(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cell_bg = QColor(RESULT_OFFSET_VALUE_BG)
        self._grid_color = QColor(RESULT_OFFSET_GRID)

    def set_cell_colors(self, bg: QColor, grid: QColor) -> None:
        self._cell_bg = QColor(bg)
        self._grid_color = QColor(grid)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.state &= ~QStyle.StateFlag.State_Selected
        option.state &= ~QStyle.StateFlag.State_HasFocus
        for group in (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Inactive,
            QPalette.ColorGroup.Disabled,
        ):
            option.palette.setColor(group, QPalette.ColorRole.Button, self._cell_bg)
            option.palette.setColor(group, QPalette.ColorRole.Base, self._cell_bg)
            option.palette.setColor(group, QPalette.ColorRole.Window, self._cell_bg)
            option.palette.setColor(group, QPalette.ColorRole.Highlight, self._cell_bg)
            option.palette.setColor(
                group, QPalette.ColorRole.HighlightedText, QColor(RESULT_OFFSET_TEXT)
            )
            option.palette.setColor(
                group, QPalette.ColorRole.ButtonText, QColor(RESULT_OFFSET_TEXT)
            )
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawItemText(
            self.rect().adjusted(1, 0, -1, 0),
            Qt.AlignmentFlag.AlignCenter,
            option.palette,
            self.isEnabled(),
            self.currentText(),
            QPalette.ColorRole.ButtonText,
        )
        painter.fillRect(QRect(self.width() - 1, 0, 1, self.height()), self._grid_color)
        painter.fillRect(QRect(0, self.height() - 1, self.width(), 1), self._grid_color)


class OffsetMeasurementDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        add_handler: Callable[[str, str, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._add_handler = add_handler
        self.setObjectName("offsetMeasurementDialog")
        self.setWindowTitle("添加测量值")
        self.setMinimumSize(600, 390)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setStyleSheet(
            """
            QDialog#offsetMeasurementDialog {
                background:#061112;
                color:#d7e2dc;
                font-family:"Microsoft YaHei UI","Segoe UI",sans-serif;
                font-size:13px;
            }
            QWidget#offsetDialogBody {
                background:#081719;
                border:1px solid #22464c;
                border-radius:6px;
            }
            QLabel { color:#d7e2dc; background:transparent; }
            QLabel#offsetDialogSourceLabel {
                color:#a6adc8;
                font-size:12px;
                font-weight:700;
                padding:0 2px;
            }
            QComboBox {
                background:#edf3f2;
                color:#061014;
                border:1px solid #5d7d83;
                border-radius:5px;
                padding:6px 10px;
                min-height:30px;
            }
            QComboBox:hover {
                background:#f8fbfb;
                border-color:#28bce8;
            }
            QComboBox:focus {
                border:2px solid #28bce8;
                padding:5px 9px;
            }
            QComboBox::drop-down {
                border:0;
                width:18px;
            }
            QComboBox QAbstractItemView {
                background:#f2f4f4;
                color:#101014;
                border:1px solid #6d7478;
                selection-background-color:#28bce8;
                selection-color:#061014;
                outline:0;
            }
            QComboBox QAbstractItemView::item {
                min-height:26px;
                padding:5px 9px;
                color:#101014;
                background:#f2f4f4;
            }
            QComboBox QAbstractItemView::item:hover {
                background:#dce6e8;
                color:#050607;
            }
            QComboBox QAbstractItemView::item:selected {
                background:#28bce8;
                color:#061014;
            }
            QPushButton#offsetDialogAdd {
                background:#28bce8;
                color:#061014;
                border:1px solid #73d9e7;
                border-radius:6px;
                padding:7px 24px;
                min-width:76px;
                min-height:30px;
                font-weight:700;
            }
            QPushButton#offsetDialogAdd:hover {
                background:#4fd4ee;
                border-color:#a4eff7;
            }
            QPushButton#offsetDialogAdd:pressed {
                background:#1596b6;
                border-color:#28bce8;
            }
            QPushButton#offsetDialogAdd:disabled {
                background:#2b3f43;
                color:#7d8b90;
                border-color:#405a60;
            }
            QLabel#offsetDialogSection {
                background:#102529;
                color:#edf6ee;
                padding:8px 10px;
                font-weight:700;
                border:1px solid #284950;
                border-top:2px solid #28bce8;
                border-radius:5px;
            }
            QPushButton#offsetMetricButton {
                background:#e6ecec;
                color:#061014;
                border:1px solid #6f8b91;
                border-radius:6px;
                padding:10px 12px;
                min-height:44px;
                text-align:left;
            }
            QPushButton#offsetMetricButton:hover {
                background:#f5f8f8;
                border-color:#28bce8;
            }
            QPushButton#offsetMetricButton:checked {
                background:#28bce8;
                color:#061014;
                border:2px solid #a4eff7;
                font-weight:700;
                padding:9px 11px;
            }
            QPushButton#offsetMetricButton:pressed {
                background:#cbd8d9;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        body = QWidget()
        body.setObjectName("offsetDialogBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(10)
        root.addWidget(body, stretch=1)

        source_label = QLabel("源")
        source_label.setObjectName("offsetDialogSourceLabel")
        body_layout.addWidget(source_label)
        source_row = QHBoxLayout()
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(10)
        self.source_combo = QComboBox()
        self.source_combo.setObjectName("offsetSourceCombo")
        apply_combo_popup_style(self.source_combo, light=True)
        source_row.addWidget(self.source_combo, stretch=2)
        self.range_combo = QComboBox()
        self.range_combo.setObjectName("offsetRangeCombo")
        apply_combo_popup_style(self.range_combo, light=True)
        for key, label in OFFSET_RANGE_OPTIONS:
            self.range_combo.addItem(label, key)
        screen_index = self.range_combo.findData("screen")
        if screen_index >= 0:
            self.range_combo.setCurrentIndex(screen_index)
        source_row.addWidget(self.range_combo, stretch=1)
        self.add_button = QPushButton("添加")
        self.add_button.setObjectName("offsetDialogAdd")
        source_row.addWidget(self.add_button)
        body_layout.addLayout(source_row)

        section = QLabel("偏移测量")
        section.setObjectName("offsetDialogSection")
        body_layout.addWidget(section)

        self.metric_group = QButtonGroup(self)
        self.metric_group.setExclusive(True)
        metric_grid = QGridLayout()
        metric_grid.setContentsMargins(0, 0, 0, 0)
        metric_grid.setHorizontalSpacing(8)
        metric_grid.setVerticalSpacing(8)
        for index, spec in enumerate(OFFSET_MEASUREMENT_SPECS):
            btn = QPushButton(spec.label)
            btn.setObjectName("offsetMetricButton")
            btn.setCheckable(True)
            btn.setProperty("metricKey", spec.key)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.metric_group.addButton(btn)
            metric_grid.addWidget(btn, index // 3, index % 3)
            if index == 0:
                btn.setChecked(True)
        for col in range(3):
            metric_grid.setColumnStretch(col, 1)
        body_layout.addLayout(metric_grid)
        body_layout.addStretch(1)

        self.add_button.clicked.connect(self._on_add_clicked)

    def set_add_handler(
        self, handler: Callable[[str, str, str], None] | None
    ) -> None:
        self._add_handler = handler

    def set_sources(
        self,
        sources: list[tuple[str, str]],
        selected: str | None = None,
    ) -> None:
        current = selected or self.source_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        for key, label in sources:
            self.source_combo.addItem(label, key)
        index = self.source_combo.findData(current)
        if index < 0 and self.source_combo.count() > 0:
            index = 0
        if index >= 0:
            self.source_combo.setCurrentIndex(index)
        self.source_combo.blockSignals(False)
        enabled = self.source_combo.count() > 0
        self.source_combo.setEnabled(enabled)
        self.range_combo.setEnabled(enabled)
        self.add_button.setEnabled(enabled)

    def _on_add_clicked(self) -> None:
        if self._add_handler is None:
            return
        source = self.source_combo.currentData()
        button = self.metric_group.checkedButton()
        metric = button.property("metricKey") if button is not None else None
        range_key = self.range_combo.currentData()
        if source is None or metric is None or range_key is None:
            return
        self._add_handler(str(source), str(metric), str(range_key))


def _summary_metric_html(label: str, value: str, unit: str, accent: str) -> str:
    unit_html = f" <span style='color:#9aa9a8'>{escape(unit)}</span>" if unit else ""
    value_color = (
        MISSING_TEXT_COLOR
        if value == MISSING_VALUE_TEXT
        else ENERGY_TEXT_COLOR
        if label in ENERGY_NAMES
        else "#edf4ef"
    )
    return (
        "<td style='padding:1px 2px'>"
        "<div style='background-color:#0d1d1f;border:1px solid #1f4c52;"
        "border-radius:4px;padding:2px 5px;white-space:nowrap'>"
        f"<span style='color:{accent};font-weight:700'>{escape(label)}</span>"
        "&nbsp;"
        f"<span style='color:{value_color};font-family:\"Cascadia Mono\",Consolas,monospace;"
        f"font-weight:700'>{escape(value)}</span>{unit_html}"
        "</div></td>"
    )


def _summary_title(
    result: ExtractResult,
    temp_labels: dict[str, str] | None = None,
) -> str:
    labels = temp_labels or _TEMP_LABELS
    parts = [result.profile_code or result.phase or "DPT"]
    temp = _infer_temp_code(result.source_path)
    if temp:
        parts.extend((temp, labels.get(temp, _TEMP_LABELS[temp])))
    if result.short_circuit_mode:
        parts.append("短路")
    elif result.single_pulse_mode:
        parts.append("单脉冲")
    else:
        parts.append("双脉冲")
    return " · ".join(escape(p) for p in parts if p)


class ResultTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._temp_labels = dict(_TEMP_LABELS)
        self.setObjectName("resultPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            RESULT_PANEL_MARGIN,
            RESULT_PANEL_MARGIN,
            RESULT_PANEL_MARGIN,
            RESULT_PANEL_MARGIN,
        )
        layout.setSpacing(RESULT_PANEL_SPACING)

        self.summary = QLabel()
        self.summary.setObjectName("resultSummary")
        self.summary.setFixedHeight(RESULT_SUMMARY_HEIGHT)
        self.summary.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.summary.setWordWrap(False)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.summary)

        self.offset_panel: QFrame | None = None
        self.offset_measure_button: QPushButton | None = None
        self.offset_dialog: OffsetMeasurementDialog | None = None
        self._offset_sources: list[tuple[str, str]] = []

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("resultDataTable")
        table_font = _result_font("Microsoft YaHei UI")
        self.table.setFont(table_font)
        self.table.setHorizontalHeaderLabels(
            ["分区", "参数", "单位", "范围取值", "数值"]
        )
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        hdr.setHighlightSections(False)
        hdr.setFixedHeight(RESULT_HEADER_HEIGHT)
        hdr.setMinimumSectionSize(24)
        header_font = _result_font("Microsoft YaHei UI", bold=True)
        hdr.setFont(header_font)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setWordWrap(False)
        self.table.setCornerButtonEnabled(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._cell_delegate = _ResultCellDelegate(
            self._is_offset_measurement_table, self.table
        )
        self.table.setItemDelegate(self._cell_delegate)
        self._set_column_widths(RESULT_COLUMN_DEFAULTS)
        layout.addWidget(self.table, stretch=1)

        self._slope_ranges = default_slope_ranges()
        self._on_range_changed: Callable[[str, SlopeRange], None] | None = None
        self._on_eoff_pre_changed: Callable[[float], None] | None = None
        self._on_value_clicked: Callable[[str, str], None] | None = None
        self._on_offset_measurement_add: Callable[[str, str, str], None] | None = None
        self._on_offset_measurement_delete: Callable[[str, str, str], None] | None = None
        self._on_offset_measurement_delete_all: Callable[[], None] | None = None
        self._on_offset_measurement_update: (
            Callable[[int, str, str], None] | None
        ) = None
        self._row_keys: list[str | None] = []
        self._row_meta: list[tuple[str, str]] = []
        self._row_colors: list[str] = []
        self._offset_row_specs: list[tuple[str, str, str] | None] = []
        self._offset_editor_refreshing = False
        self._section_ranges: dict[str, tuple[int, int]] = {}
        self._section_colors: dict[str, str] = {}
        self._section_text_colors: dict[str, str] = {}
        self._active_metric: tuple[str, str] | None = None
        self._unavailable_metrics: set[tuple[str, str]] = set()
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.currentCellChanged.connect(self._on_current_cell_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_offset_context_menu)

        pane_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        pane_policy.setHeightForWidth(False)
        self.setSizePolicy(pane_policy)

    def set_temperature_labels(self, labels: dict[str, str]) -> None:
        self._temp_labels = dict(_TEMP_LABELS)
        for code, text in labels.items():
            if code in self._temp_labels and text:
                self._temp_labels[code] = str(text)

    def set_offset_measurement_add_handler(
        self, handler: Callable[[str, str, str], None] | None
    ) -> None:
        self._on_offset_measurement_add = handler
        if self.offset_dialog is not None:
            self.offset_dialog.set_add_handler(handler)

    def set_offset_measurement_delete_handler(
        self,
        row_handler: Callable[[str, str, str], None] | None,
        all_handler: Callable[[], None] | None,
    ) -> None:
        self._on_offset_measurement_delete = row_handler
        self._on_offset_measurement_delete_all = all_handler

    def set_offset_measurement_update_handler(
        self, handler: Callable[[int, str, str], None] | None
    ) -> None:
        self._on_offset_measurement_update = handler

    def _ensure_offset_panel(self) -> None:
        if self.offset_panel is not None:
            return
        panel = QFrame()
        panel.setObjectName("offsetMeasurementPanel")
        offset_layout = QHBoxLayout(panel)
        offset_layout.setContentsMargins(6, 6, 6, 6)
        offset_layout.setSpacing(6)
        label = QLabel("偏移测量")
        label.setObjectName("offsetActionLabel")
        offset_layout.addWidget(label, stretch=1)
        measure_button = QPushButton("测量")
        measure_button.setObjectName("offsetMeasureButton")
        offset_layout.addWidget(measure_button)
        panel.hide()

        layout = self.layout()
        assert layout is not None
        layout.insertWidget(1, panel)
        measure_button.clicked.connect(self._show_offset_measurement_dialog)
        self.offset_panel = panel
        self.offset_measure_button = measure_button

    def _ensure_offset_dialog(self) -> OffsetMeasurementDialog:
        if self.offset_dialog is None:
            self.offset_dialog = OffsetMeasurementDialog(
                self,
                add_handler=self._on_offset_measurement_add,
            )
        self.offset_dialog.set_sources(self._offset_sources)
        return self.offset_dialog

    def _show_offset_measurement_dialog(self) -> None:
        dialog = self._ensure_offset_dialog()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def set_offset_sources(
        self, sources: list[tuple[str, str]], selected: str | None = None
    ) -> None:
        self._ensure_offset_panel()
        self._offset_sources = list(sources)
        if self.offset_dialog is not None:
            self.offset_dialog.set_sources(self._offset_sources, selected=selected)
        if self.offset_measure_button is not None:
            self.offset_measure_button.setEnabled(bool(self._offset_sources))

    def show_offset_measurements(
        self,
        rows: list[tuple[str, str, str, str, str, str]],
        *,
        source_count: int,
        row_specs: list[tuple[str, str, str]] | None = None,
    ) -> None:
        self._ensure_offset_panel()
        assert self.offset_panel is not None
        self.offset_panel.show()
        self.summary.setText(
            "<div style='margin:0'>"
            "<div style='color:#d7e2dc;font-size:14px;font-weight:700'>偏移测量</div>"
            f"<div style='margin-top:6px;color:#a6adc8;font-size:12px'>"
            f"可用源 {source_count} 个 · 已添加 {len(rows)} 项"
            "</div></div>"
        )
        self._offset_row_specs = [
            tuple(spec) for spec in (row_specs or [])
        ][: len(rows)]
        while len(self._offset_row_specs) < len(rows):
            self._offset_row_specs.append(None)
        self._populate_rows(rows)
        if rows:
            current = self.table.currentRow()
            if current < 0 or current >= len(rows):
                self.table.setCurrentCell(0, 1)
            self._refresh_offset_row_styles()

    def hide_offset_measurements(self) -> None:
        if self.offset_panel is not None:
            self.offset_panel.hide()
        self._offset_row_specs = []
        self._set_offset_table_visual_mode(False)

    def current_offset_measurement_spec(self) -> tuple[str, str, str] | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._offset_row_specs):
            return None
        return self._offset_row_specs[row]

    def _request_delete_offset_measurement_row(self, row: int) -> bool:
        if row < 0 or row >= len(self._offset_row_specs):
            return False
        spec = self._offset_row_specs[row]
        if spec is None or self._on_offset_measurement_delete is None:
            return False
        source_key, metric_key, range_key = spec
        self._on_offset_measurement_delete(source_key, metric_key, range_key)
        return True

    def _request_delete_all_offset_measurements(self) -> bool:
        if not self._is_offset_measurement_table() or self.table.rowCount() <= 0:
            return False
        if self._on_offset_measurement_delete_all is None:
            return False
        self._on_offset_measurement_delete_all()
        return True

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.preferred_panel_width(), 680)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(300, 360)

    def preferred_panel_width(self) -> int:
        """参数表侧栏紧凑宽度：列宽之和 + 边距，保证文字完整显示。"""
        n = self.table.columnCount()
        if n <= 0:
            table_w = 530
        else:
            table_w = sum(self.table.columnWidth(c) for c in range(n))
        # layout margins + 竖滚动条预留
        content_w = int(
            table_w
            + 2 * self.table.frameWidth()
            + RESULT_PANEL_MARGIN * 2
            + RESULT_SCROLLBAR_RESERVE
        )
        target = (
            RESULT_OFFSET_PANEL_TARGET_WIDTH
            if self._is_offset_measurement_table()
            else RESULT_PANEL_TARGET_WIDTH
        )
        return max(target, content_w)

    def _target_columns_width(self) -> int:
        target = (
            RESULT_OFFSET_PANEL_TARGET_WIDTH
            if self._is_offset_measurement_table()
            else RESULT_PANEL_TARGET_WIDTH
        )
        defaults = (
            RESULT_OFFSET_COLUMN_DEFAULTS
            if self._is_offset_measurement_table()
            else RESULT_COLUMN_DEFAULTS
        )
        return max(
            sum(defaults),
            target
            - RESULT_PANEL_MARGIN * 2
            - 2 * self.table.frameWidth()
            - RESULT_SCROLLBAR_RESERVE,
        )

    def _set_column_widths(self, widths: tuple[int, ...]) -> None:
        hdr = self.table.horizontalHeader()
        for col, w in enumerate(widths):
            self.table.setColumnWidth(col, w)
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

    def _clear_offset_editors(self) -> None:
        for row in range(self.table.rowCount()):
            for col in range(min(4, self.table.columnCount())):
                if self.table.cellWidget(row, col) is not None:
                    self.table.removeCellWidget(row, col)

    def _style_offset_combo(self, combo: QComboBox, bg: QColor) -> None:
        grid = QColor(RESULT_OFFSET_GRID)
        if isinstance(combo, _CenteredCellComboBox):
            combo.set_cell_colors(bg, grid)
        palette = combo.palette()
        for group in (
            QPalette.ColorGroup.Active,
            QPalette.ColorGroup.Inactive,
            QPalette.ColorGroup.Disabled,
        ):
            palette.setColor(group, QPalette.ColorRole.Button, bg)
            palette.setColor(group, QPalette.ColorRole.Base, bg)
            palette.setColor(group, QPalette.ColorRole.Window, bg)
            palette.setColor(group, QPalette.ColorRole.Highlight, bg)
            palette.setColor(group, QPalette.ColorRole.Text, QColor(RESULT_OFFSET_TEXT))
            palette.setColor(
                group, QPalette.ColorRole.ButtonText, QColor(RESULT_OFFSET_TEXT)
            )
            palette.setColor(
                group, QPalette.ColorRole.HighlightedText, QColor(RESULT_OFFSET_TEXT)
            )
        combo.setPalette(palette)
        view_palette = combo.view().palette()
        view_palette.setColor(
            QPalette.ColorRole.Highlight, QColor(RESULT_OFFSET_POPUP_SELECTED)
        )
        view_palette.setColor(
            QPalette.ColorRole.HighlightedText, QColor(RESULT_OFFSET_TEXT)
        )
        combo.view().setPalette(view_palette)
        combo.setStyleSheet(
            "QComboBox {"
            f"background:{bg.name()};"
            f"color:{RESULT_OFFSET_TEXT};"
            "border:0;"
            "border-radius:0;"
            "padding:0 6px;"
            "font-weight:400;"
            f"selection-background-color:{bg.name()};"
            f"selection-color:{RESULT_OFFSET_TEXT};"
            "}"
            "QComboBox:on {"
            f"background:{bg.name()};"
            f"color:{RESULT_OFFSET_TEXT};"
            "}"
            "QComboBox:focus {"
            f"background:{bg.name()};"
            f"color:{RESULT_OFFSET_TEXT};"
            "}"
            "QComboBox::drop-down { border:0; width:14px; }"
        )

    def _offset_combo(
        self,
        row: int,
        col: int,
        field: str,
        entries: list[tuple[str, str]],
        current_value: str,
    ) -> QComboBox:
        combo = _CenteredCellComboBox(self.table)
        combo.setObjectName(f"offset{field.title()}Combo")
        combo.setFont(_result_font("Microsoft YaHei UI"))
        combo.setFixedHeight(RESULT_ROW_HEIGHT)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        apply_combo_popup_style(combo, light=True)
        combo.view().setStyleSheet(_offset_combo_popup_style())

        self._offset_editor_refreshing = True
        combo.clear()
        for value, label in entries:
            combo.addItem(label, value)
            combo.setItemData(
                combo.count() - 1,
                Qt.AlignmentFlag.AlignCenter,
                Qt.ItemDataRole.TextAlignmentRole,
            )
        idx = combo.findData(current_value)
        if idx < 0 and combo.count() > 0:
            idx = 0
        if idx >= 0:
            combo.setCurrentIndex(idx)
        self._offset_editor_refreshing = False

        def _emit_update(_index: int) -> None:
            if self._offset_editor_refreshing:
                return
            value = combo.currentData()
            if value is None:
                return
            self.table.setCurrentCell(row, col)
            item = self.table.item(row, col)
            if item is not None:
                item.setText(combo.currentText())
            if self._on_offset_measurement_update is not None:
                self._on_offset_measurement_update(row, field, str(value))

        combo.currentIndexChanged.connect(_emit_update)
        return combo

    def _install_offset_row_editors(self) -> None:
        if not self._is_offset_measurement_table():
            return
        self._clear_offset_editors()
        metric_entries = [
            (spec.key, spec.label.replace("\n", " "))
            for spec in OFFSET_MEASUREMENT_SPECS
        ]
        range_entries = [(key, label) for key, label in OFFSET_RANGE_OPTIONS]
        for row, spec in enumerate(self._offset_row_specs):
            if spec is None:
                continue
            source_key, metric_key, range_key = spec
            editors = (
                (
                    0,
                    "source",
                    [
                        (key, _offset_source_short_label(key))
                        for key, _label in self._offset_sources
                    ],
                    source_key,
                ),
                (1, "metric", metric_entries, metric_key),
                (3, "range", range_entries, range_key),
            )
            for col, field, entries, current in editors:
                combo = self._offset_combo(row, col, field, entries, current)
                self.table.setCellWidget(row, col, combo)

    def _is_offset_measurement_table(self) -> bool:
        return bool(self._offset_row_specs)

    def _set_offset_table_visual_mode(self, enabled: bool) -> None:
        self.table.setShowGrid(not enabled)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
            if enabled
            else QAbstractItemView.SelectionMode.SingleSelection
        )

    def _column_text_width(self, column: int, default: int) -> int:
        from PyQt6.QtGui import QFontMetrics

        width = default
        pad = (
            32
            if self._is_offset_measurement_table() and column in {0, 1, 3}
            else 12
        )
        header = self.table.horizontalHeaderItem(column)
        if header is not None:
            width = max(
                width,
                QFontMetrics(header.font()).horizontalAdvance(header.text()) + pad,
            )
        for row in range(self.table.rowCount()):
            item = self.table.item(row, column)
            if item is None:
                continue
            text = item.text()
            if column == 0:
                text = _section_stack_label(text)
            width = max(
                width,
                QFontMetrics(item.font()).horizontalAdvance(text) + pad,
            )
        return width

    def _apply_compact_column_widths(self) -> None:
        from PyQt6.QtGui import QFontMetrics

        if self._is_offset_measurement_table():
            widths = [
                min(
                    self._column_text_width(0, RESULT_OFFSET_COLUMN_DEFAULTS[0]),
                    RESULT_OFFSET_COLUMN_CAPS[0],
                ),
                min(
                    self._column_text_width(1, RESULT_OFFSET_COLUMN_DEFAULTS[1]),
                    RESULT_OFFSET_COLUMN_CAPS[1],
                ),
                min(
                    self._column_text_width(2, RESULT_OFFSET_COLUMN_DEFAULTS[2]),
                    RESULT_OFFSET_COLUMN_CAPS[2],
                ),
                min(
                    self._column_text_width(3, RESULT_OFFSET_COLUMN_DEFAULTS[3]),
                    RESULT_OFFSET_COLUMN_CAPS[3],
                ),
                min(
                    self._column_text_width(4, RESULT_OFFSET_COLUMN_DEFAULTS[4]),
                    RESULT_OFFSET_COLUMN_CAPS[4],
                ),
            ]
            extra = self._target_columns_width() - sum(widths)
            if extra > 0:
                widths[0] += extra
            self._set_column_widths(tuple(widths))
            return

        rng_w = RESULT_COLUMN_DEFAULTS[3]
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 3)
            if item is not None:
                rng_w = max(
                    rng_w,
                    QFontMetrics(item.font()).horizontalAdvance(item.text()) + 2,
                )
        param_w = RESULT_COLUMN_DEFAULTS[1]
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 1)
            if item is not None:
                param_w = max(
                    param_w,
                    QFontMetrics(item.font()).horizontalAdvance(item.text()) + 2,
                )
        val_pad = 2
        val_w = RESULT_COLUMN_DEFAULTS[4]
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 4)
            if item is not None:
                val_w = max(
                    val_w,
                    QFontMetrics(item.font()).horizontalAdvance(item.text()) + val_pad,
                )
        widths = [
            RESULT_COLUMN_DEFAULTS[0],
            min(param_w, 156),
            RESULT_COLUMN_DEFAULTS[2],
            min(rng_w, 138),
            min(val_w, 150),
        ]
        extra = self._target_columns_width() - sum(widths)
        if extra > 0:
            total_weight = sum(RESULT_COLUMN_FILL_WEIGHTS)
            used = 0
            for idx, weight in enumerate(RESULT_COLUMN_FILL_WEIGHTS):
                if weight <= 0:
                    continue
                add = extra * weight // total_weight
                widths[idx] += add
                used += add
            widths[4] += extra - used
        self._set_column_widths(tuple(widths))

    def set_range_handler(
        self, handler: Callable[[str, SlopeRange], None] | None,
    ) -> None:
        self._on_range_changed = handler

    def set_eoff_pre_handler(self, handler: Callable[[float], None] | None) -> None:
        self._on_eoff_pre_changed = handler

    def set_value_click_handler(
        self, handler: Callable[[str, str], None] | None
    ) -> None:
        self._on_value_clicked = handler

    def slope_ranges(self) -> dict[str, SlopeRange]:
        return dict(self._slope_ranges)

    def set_slope_ranges(self, ranges: dict[str, SlopeRange]) -> None:
        self._slope_ranges = dict(default_slope_ranges())
        for key, sr in ranges.items():
            self._slope_ranges[key] = normalize_slope_range(key, sr)

    def _set_summary(self, result: ExtractResult) -> None:
        if result.short_circuit_mode:
            sc = result.short_circuit
            vdc_disp = result.vdc_set if result.vdc_set is not None else result.vdc
            esc_other_disp = (
                MISSING_VALUE_TEXT
                if result.is_metric_unavailable("短路过程", "短路能量Esc_对管")
                else _fmt(sc.esc_other)
            )
            html = (
                "<div style='margin:0'>"
                f"<div style='color:#d7e2dc;font-size:14px;font-weight:700'>{_summary_title(result, self._temp_labels)}</div>"
                "<table style='margin-top:3px' cellspacing='0' cellpadding='0'><tr>"
                + _summary_metric_html("Udc", f"{vdc_disp:.1f}", "V", "#4fdbe8")
                + _summary_metric_html("Imax", f"{sc.ic_max:.1f}", "A", "#f2d06b")
                + _summary_metric_html("Tsc", f"{sc.tsc:.3f}", "us", "#f4a261")
                + "</tr><tr>"
                + _summary_metric_html("Esc 本管", _fmt(sc.esc_dut), "J", "#8fd17f")
                + _summary_metric_html("Esc 对管", esc_other_disp, "J", "#7cc7e8")
                + "</tr></table></div>"
            )
            self.summary.setText(html)
            return
        off, on, rr = result.turn_off, result.turn_on, result.reverse_recovery
        vdc_disp = result.vdc_set if result.vdc_set is not None else result.vdc
        idc_disp = off.ic_off_max
        warn = ""
        if off.energy_warn or on.energy_warn or rr.energy_warn:
            warn = (
                '<br><span style="color:#f9e2af">⚠ MATH 通道与 V×I 积分偏差较大，'
                "已采用 IEC60747-9 窗口 V×I 结果</span>"
            )

        mode_note = ""
        if result.single_pulse_mode:
            mode_note = (
                '<br><span style="color:#89b4fa">单脉冲工况：仅关断参数</span>'
            )
        eoff_disp = (
            MISSING_VALUE_TEXT
            if result.is_metric_unavailable("关断过程", "Eoff")
            else _fmt_energy(off.eoff)
        )
        eon_disp = (
            "—"
            if result.single_pulse_mode
            else MISSING_VALUE_TEXT
            if result.is_metric_unavailable("开通", "Eon")
            else _fmt_energy(on.eon)
        )
        err_disp = (
            "—"
            if result.single_pulse_mode
            else MISSING_VALUE_TEXT
            if result.is_metric_unavailable("反向恢复", "Err")
            else _fmt_energy(rr.err)
        )
        note = mode_note + warn
        html = (
            "<div style='margin:0'>"
            f"<div style='color:#d7e2dc;font-size:14px;font-weight:700'>{_summary_title(result, self._temp_labels)}</div>"
            "<table style='margin-top:3px' cellspacing='0' cellpadding='0'>"
            "<tr>"
            + _summary_metric_html("Vdc", f"{vdc_disp:.1f}", "V", "#4fdbe8")
            + _summary_metric_html("Idc", f"{idc_disp:.1f}", "A", "#7cc7e8")
            + "</tr><tr>"
            + _summary_metric_html("Eoff", eoff_disp, "mJ", ENERGY_TEXT_COLOR)
            + _summary_metric_html("Eon", eon_disp, "mJ", ENERGY_TEXT_COLOR)
            + _summary_metric_html("Err", err_disp, "mJ", ENERGY_TEXT_COLOR)
            + "</tr></table>"
            f"<div style='margin-top:3px;color:#aeb8b8;font-size:11px'>{note}</div>"
            "</div>"
        )
        self.summary.setText(html)

    def set_mode_placeholder(self, title: str, detail: str) -> None:
        """非双脉冲模式或功能未就绪时清空参数表并显示说明。"""
        self.hide_offset_measurements()
        self.table.clearSpans()
        self._unavailable_metrics = set()
        html = f"""
        <p style='margin:0;color:#89b4fa;font-size:13px'><b>{title}</b></p>
        <p style='margin:8px 0 0 0;color:#a6adc8;font-size:12px'>{detail}</p>
        """
        self.summary.setText(html)
        self.table.setRowCount(0)

    def set_result(self, result: ExtractResult) -> None:
        self.hide_offset_measurements()
        self._unavailable_metrics = set(result.unavailable_metrics)
        self._set_summary(result)
        rows: list[tuple[str, str, str, str, str, str]] = []
        off, on, rr = result.turn_off, result.turn_on, result.reverse_recovery

        if result.short_circuit_mode:
            sc = result.short_circuit
            for name, unit, val in (
                ("短路电流Imax", "A", _fmt(sc.ic_max)),
                ("短路时间Tsc", "us", _fmt(sc.tsc)),
                ("短路能量Esc_本管", "J", _fmt(sc.esc_dut)),
                ("应力Vpeak_本管", "V", _fmt(sc.vpeak_dut)),
                ("短路能量Esc_对管", "J", _fmt(sc.esc_other)),
                ("应力Vpeak_对管", "V", _fmt(sc.vpeak_other)),
                ("Desat动作时间", "us", _fmt_optional(sc.desat_time)),
            ):
                if result.is_metric_unavailable("短路过程", name):
                    val = MISSING_VALUE_TEXT
                if "本管" in name:
                    bg = SECTION_SHORT_DUT
                elif "对管" in name:
                    bg = SECTION_SHORT_OTHER
                else:
                    bg = SECTION_SHORT
                rng = _range_label_for_row("短路过程", name, result) or "—"
                rows.append(("短路过程", name, unit, rng, val, bg))
            self._populate_rows(rows)
            return

        def add(
            section: str,
            bg: str,
            items: list[tuple[str, str, float]],
            energy: set[str],
        ) -> None:
            for name, unit, val in items:
                if result.is_metric_unavailable(section, name):
                    disp = MISSING_VALUE_TEXT
                elif section == "关断过程" and name == "串扰电压":
                    disp = f"{off.crosstalk_vmax:.2f}/{off.crosstalk_vmin:.2f}"
                elif section == "开通" and name == "串扰电压":
                    disp = f"{on.crosstalk_vmax:.2f}/{on.crosstalk_vmin:.2f}"
                else:
                    disp = _fmt_energy(val) if name in energy else _fmt(val)
                rng = _range_label_for_row(section, name, result) or "—"
                rows.append((section, name, unit, rng, disp, bg))

        add(
            "关断过程",
            SECTION_OFF,
            [
                ("ΔVce", "V", off.delta_vce),
                ("Ic_off_max", "A", off.ic_off_max),
                ("Vce_off_max", "V", off.vce_off_max),
                ("dv/dt", "V/ns", off.dvdt),
                ("di/dt", "A/ns", off.didt),
                ("Ls_off", "nH", off.ls_off),
                ("Toff", "ns", off.toff),
                ("Td_off", "ns", off.td_off),
                ("Tf", "ns", off.tf),
                ("串扰电压", "V", off.crosstalk_v),
                ("Eoff", "mJ", off.eoff),
            ],
            {"Eoff"},
        )
        if not result.single_pulse_mode:
            add(
                "开通",
                SECTION_ON,
                [
                    ("ΔVce", "V", on.delta_vce),
                    ("Ic_on_max", "A", on.ic_on_max),
                    ("Vce_on_max", "V", on.vce_on_max),
                    ("开通电流", "A", on.turn_on_current),
                    ("dv/dt", "V/ns", on.dvdt),
                    ("di/dt", "A/ns", on.didt),
                    ("Ls_on", "nH", on.ls_on),
                    ("Ton", "ns", on.ton),
                    ("Td_on", "ns", on.td_on),
                    ("Tr", "ns", on.tr),
                    ("串扰电压", "V", on.crosstalk_v),
                    ("Eon", "mJ", on.eon),
                ],
                {"Eon"},
            )
            add(
                "反向恢复",
                SECTION_RR,
                [
                    ("Irr", "A", rr.irr),
                    ("Trr", "ns", rr.trr),
                    ("Vrr", "V", rr.vrr),
                    ("dv/dt", "V/ns", rr.dvdt_max),
                    ("di/dt", "A/ns", rr.didt_irr),
                    ("Err", "mJ", rr.err),
                ],
                {"Err"},
            )

        self._populate_rows(rows)

    def _populate_rows(self, rows: list[tuple[str, str, str, str, str, str]]) -> None:
        self.table.setUpdatesEnabled(False)
        self._clear_offset_editors()
        self.table.clearSpans()
        self.table.setRowCount(len(rows))
        self._row_keys = []
        self._row_meta = []
        self._row_colors = []
        self._section_ranges = {}
        self._section_colors = {}
        self._section_text_colors = {}
        param_font = _result_font("Microsoft YaHei UI", bold=True)
        section_font = _result_font("Microsoft YaHei UI", bold=True)
        value_font = _result_font("Cascadia Mono", bold=True)
        utility_font = _result_font("Microsoft YaHei UI")
        is_offset_table = self._is_offset_measurement_table()
        self._set_offset_table_visual_mode(is_offset_table)
        if is_offset_table:
            param_font = _result_font("Microsoft YaHei UI")
            section_font = _result_font("Microsoft YaHei UI")
            value_font = _result_font("Cascadia Mono")
        for r, (section, name, unit, rng_disp, val, bg) in enumerate(rows):
            self._row_meta.append((section, name))
            self._row_colors.append(bg)
            color = QColor(bg)
            if is_offset_table:
                text_hex = RESULT_OFFSET_TEXT
            elif section not in PROCESS_SECTIONS:
                text_hex = "#101014" if color.lightness() > 145 else TEXT_ON_SECTION
            else:
                text_hex = ENERGY_TEXT_COLOR if name in ENERGY_NAMES else TEXT_ON_SECTION
            text_color = QColor(text_hex)
            missing_value = (section, name) in self._unavailable_metrics or val == MISSING_VALUE_TEXT
            value_text_color = QColor(MISSING_TEXT_COLOR if missing_value else text_hex)
            row_key = SLOPE_ROW_KEYS.get((section, name))
            self._row_keys.append(row_key)
            if not is_offset_table and section not in self._section_ranges:
                self._section_ranges[section] = (r, 1)
                self._section_colors[section] = bg
                self._section_text_colors[section] = text_hex
            elif not is_offset_table:
                start, count = self._section_ranges[section]
                self._section_ranges[section] = (start, count + 1)

            section_shadow_item = _SectionTableItem(section)
            if is_offset_table:
                section_shadow_item.setBackground(color)
                section_shadow_item.setForeground(QColor(RESULT_OFFSET_TEXT))
            else:
                section_shadow_item.setBackground(
                    QColor(self._section_colors.get(section, _section_base_color(section)))
                )
                section_shadow_item.setForeground(
                    QColor(self._section_text_colors.get(section, TEXT_ON_SECTION))
                )
            section_shadow_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            section_shadow_item.setFont(section_font)
            self.table.setItem(r, 0, section_shadow_item)

            for c, text in ((1, name), (2, unit)):
                item = QTableWidgetItem(text)
                item.setBackground(QColor(RESULT_OFFSET_VALUE_BG) if is_offset_table else color)
                item.setForeground(text_color)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 1:
                    item.setFont(param_font)
                else:
                    item.setFont(utility_font)
                self.table.setItem(r, c, item)

            range_item = QTableWidgetItem(rng_disp)
            range_item.setBackground(QColor(RESULT_OFFSET_VALUE_BG) if is_offset_table else color)
            range_item.setForeground(text_color)
            range_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            range_item.setFont(utility_font)
            if row_key or (section == "关断过程" and name == "Eoff"):
                range_item.setToolTip("双击修改范围取值")
            self.table.setItem(r, 3, range_item)
            val_item = QTableWidgetItem(val)

            val_item.setBackground(QColor(RESULT_OFFSET_VALUE_BG) if is_offset_table else color)
            val_item.setForeground(value_text_color)
            val_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            val_item.setFont(value_font)
            self.table.setItem(r, 4, val_item)

        if is_offset_table:
            self._install_offset_row_editors()
            self._refresh_offset_row_styles()
        else:
            for section, (start, count) in self._section_ranges.items():
                section_item = _SectionTableItem(section, _section_stack_label(section))
                section_item.setBackground(
                    QColor(self._section_colors.get(section, _section_base_color(section)))
                )
                section_item.setForeground(
                    QColor(self._section_text_colors.get(section, TEXT_ON_SECTION))
                )
                section_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                section_item.setFont(section_font)
                self.table.setItem(start, 0, section_item)
                if count > 1:
                    self.table.setSpan(start, 0, count, 1)

            self._refresh_section_highlight()
        self._apply_compact_column_widths()
        self.setMaximumWidth(self.preferred_panel_width())
        vh = self.table.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(RESULT_ROW_HEIGHT)
        self.table.setUpdatesEnabled(True)

    def _refresh_section_highlight(self) -> None:
        if self._is_offset_measurement_table():
            self._refresh_offset_row_styles()
            return
        active_section = self._active_metric[0] if self._active_metric else None
        for section, (start, count) in self._section_ranges.items():
            active = section == active_section
            bg = QColor(
                SECTION_ACTIVE_BG
                if active
                else self._section_colors.get(section, _section_base_color(section))
            )
            fg = QColor(SECTION_ACTIVE_TEXT if active else TEXT_ON_SECTION)
            if not active:
                fg = QColor(self._section_text_colors.get(section, TEXT_ON_SECTION))
            for r in range(start, start + count):
                item = self.table.item(r, 0)
                if item is None:
                    continue
                item.setBackground(bg)
                item.setForeground(fg)

    def _refresh_offset_row_styles(self) -> None:
        active_row = self.table.currentRow()
        for row in range(self.table.rowCount()):
            row_color = QColor(
                self._row_colors[row]
                if row < len(self._row_colors)
                else RESULT_OFFSET_VALUE_BG
            )
            section_item = self.table.item(row, 0)
            if section_item is not None:
                section_item.setBackground(row_color)
                section_item.setForeground(QColor(RESULT_OFFSET_TEXT))
            section_widget = self.table.cellWidget(row, 0)
            if isinstance(section_widget, QComboBox):
                self._style_offset_combo(section_widget, row_color)
            fill = row_color if row == active_row else QColor(RESULT_OFFSET_VALUE_BG)
            for col in range(1, self.table.columnCount()):
                item = self.table.item(row, col)
                if item is None:
                    continue
                item.setBackground(fill)
                item.setForeground(QColor(RESULT_OFFSET_TEXT))
                widget = self.table.cellWidget(row, col)
                if isinstance(widget, QComboBox):
                    self._style_offset_combo(widget, fill)
        self.table.clearSelection()

    def _on_current_cell_changed(
        self,
        current_row: int,
        _current_col: int,
        _previous_row: int,
        _previous_col: int,
    ) -> None:
        if current_row >= 0 and self._is_offset_measurement_table():
            self._refresh_offset_row_styles()

    def _show_offset_context_menu(self, pos) -> None:
        if not self._is_offset_measurement_table() or self.table.rowCount() <= 0:
            return
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self._offset_row_specs):
            return
        col = self.table.columnAt(pos.x())
        self.table.setCurrentCell(row, max(0, col))
        self._refresh_offset_row_styles()

        menu = QMenu(self.table)
        delete_row_action = menu.addAction("删除本行")
        delete_all_action = menu.addAction("删除全部")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == delete_row_action:
            self._request_delete_offset_measurement_row(row)
        elif chosen == delete_all_action:
            self._request_delete_all_offset_measurements()

    def set_active_metric(self, section: str, name: str) -> None:
        self._active_metric = (section, name)
        for r, (sec, nm) in enumerate(self._row_meta):
            if sec == section and nm == name:
                self.table.setCurrentCell(r, 1)
                if not self._is_offset_measurement_table():
                    self.table.selectRow(r)
                break
        self._refresh_section_highlight()

    def _on_cell_clicked(self, row: int, col: int) -> None:
        # 点击任意列都联动波形定位，避免仍停留在旧交互模式
        if row < 0 or row >= len(self._row_meta):
            return
        section, name = self._row_meta[row]
        self._active_metric = (section, name)
        self.table.setCurrentCell(row, max(0, min(col, self.table.columnCount() - 1)))
        if not self._is_offset_measurement_table():
            self.table.selectRow(row)
        self._refresh_section_highlight()
        if self._on_value_clicked is None:
            return
        self._on_value_clicked(section, name)

    def set_metric_value(self, section: str, name: str, value: float | None) -> None:
        """按 extract 相同格式写回数值单元格。"""
        self.set_value_text(
            section, name, format_metric_display(section, name, value)
        )

    def set_value_text(self, section: str, name: str, text: str) -> None:
        """Update one result-cell text without rebuilding the whole table."""
        for r, (sec, nm) in enumerate(self._row_meta):
            if sec == section and nm == name:
                item = self.table.item(r, 4)
                if item is not None:
                    item.setText(text)
                    missing_value = (
                        (section, name) in self._unavailable_metrics
                        or text.strip() == MISSING_VALUE_TEXT
                    )
                    if self._is_offset_measurement_table():
                        color = RESULT_OFFSET_TEXT
                    elif missing_value:
                        color = MISSING_TEXT_COLOR
                    elif name in ENERGY_NAMES:
                        color = ENERGY_TEXT_COLOR
                    else:
                        color = TEXT_ON_SECTION
                    item.setForeground(QColor(color))
                return

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        # 仅允许在“范围取值”单元格修改
        if col != 3 or row < 0 or row >= len(self._row_meta):
            return
        section, name = self._row_meta[row]
        if section == "关断过程" and name == "Eoff":
            item = self.table.item(row, col)
            text = item.text() if item else ""
            current = 450.0
            if text.startswith("pre=") and text.endswith("ns"):
                try:
                    current = float(text[4:-2])
                except ValueError:
                    current = 450.0
            value, ok = QInputDialog.getDouble(
                self,
                "关断 Eoff 窗口预扩展",
                "pre (ns):",
                current,
                50.0,
                2000.0,
                1,
            )
            if not ok:
                return
            if item:
                item.setText(f"pre={value:g}ns")
            if self._on_eoff_pre_changed:
                self._on_eoff_pre_changed(float(value))
            return

        row_key = self._row_keys[row]
        if not row_key:
            return
        current = self._slope_ranges.get(row_key, default_slope_ranges()[row_key])
        presets = SLOPE_RANGE_PRESETS.get(row_key, [])
        options = [p[0] for p in presets] + [CUSTOM_RANGE_LABEL]
        idx = preset_index_for_range(row_key, current)
        current_idx = idx if idx >= 0 else len(options) - 1
        title_map = {
            "off_dvdt": "关断 dv/dt 取值范围",
            "off_didt": "关断 di/dt 取值范围",
            "on_dvdt": "开通 dv/dt 取值范围",
            "on_didt": "开通 di/dt 取值范围",
            "rr_dvdt": "反向恢复 dv/dt 取值范围",
            "rr_didt": "反向恢复 di/dt 取值范围",
        }
        selected, ok = QInputDialog.getItem(
            self,
            title_map.get(row_key, "取值范围"),
            "选择范围：",
            options,
            current_idx,
            False,
        )
        if not ok:
            return

        if selected == CUSTOM_RANGE_LABEL:
            ic_reference = "plateau"
            if row_key == "rr_didt":
                algo_options = [RR_DIDT_CUSTOM_IDM, RR_DIDT_CUSTOM_IF_IRM]
                algo_idx = 0
                if current.ic_reference == "if_irm":
                    algo_idx = 1
                algo, ok_algo = QInputDialog.getItem(
                    self,
                    title_map.get(row_key, "自定义取值范围"),
                    "先选择算法：",
                    algo_options,
                    algo_idx,
                    False,
                )
                if not ok_algo:
                    return
                ic_reference = "if_irm" if algo == RR_DIDT_CUSTOM_IF_IRM else "idm"
            dlg = SlopeRangeDialog(
                self,
                title=title_map.get(row_key, "自定义取值范围"),
                initial=current,
                ic_reference=ic_reference,
            )
            if dlg.exec() != dlg.DialogCode.Accepted or dlg.range_value() is None:
                return
            new_range = dlg.range_value()
            assert new_range is not None
        else:
            new_range = None
            for p in presets:
                if p[0] == selected:
                    new_range = preset_to_range(p)
                    break
            if new_range is None:
                return

        self._slope_ranges[row_key] = normalize_slope_range(row_key, new_range)
        if self._on_range_changed:
            self._on_range_changed(row_key, self._slope_ranges[row_key])
