from __future__ import annotations

from collections.abc import Callable
from html import escape
from pathlib import Path
import re

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
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
RESULT_SCROLLBAR_RESERVE = 10
ENERGY_NAMES = {"Eoff", "Eon", "Err"}
ENERGY_TEXT_COLOR = "#ffd34d"
SECTION_ACTIVE_BG = "#22b8cc"
SECTION_ACTIVE_TEXT = "#061112"


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


def format_metric_display(section: str, name: str, value: float) -> str:
    """与 set_result 填表规则一致，避免交互写回时位数跳动。"""
    _ = section
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
    return SECTION_OFF


def _section_stack_label(section: str) -> str:
    return "\n".join(section) if len(section) > 1 else section


class _SectionTableItem(QTableWidgetItem):
    def __init__(self, section: str, display_text: str | None = None) -> None:
        super().__init__(display_text if display_text is not None else section)
        self._section_text = section

    def text(self) -> str:  # noqa: D102
        return self._section_text


def _summary_metric_html(label: str, value: str, unit: str, accent: str) -> str:
    unit_html = f" <span style='color:#9aa9a8'>{escape(unit)}</span>" if unit else ""
    value_color = ENERGY_TEXT_COLOR if label in ENERGY_NAMES else "#edf4ef"
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
        self._set_column_widths(RESULT_COLUMN_DEFAULTS)
        layout.addWidget(self.table, stretch=1)

        self._slope_ranges = default_slope_ranges()
        self._on_range_changed: Callable[[str, SlopeRange], None] | None = None
        self._on_eoff_pre_changed: Callable[[float], None] | None = None
        self._on_value_clicked: Callable[[str, str], None] | None = None
        self._row_keys: list[str | None] = []
        self._row_meta: list[tuple[str, str]] = []
        self._section_ranges: dict[str, tuple[int, int]] = {}
        self._active_metric: tuple[str, str] | None = None
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.cellClicked.connect(self._on_cell_clicked)

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
        return max(RESULT_PANEL_TARGET_WIDTH, content_w)

    def _target_columns_width(self) -> int:
        return max(
            sum(RESULT_COLUMN_DEFAULTS),
            RESULT_PANEL_TARGET_WIDTH
            - RESULT_PANEL_MARGIN * 2
            - 2 * self.table.frameWidth()
            - RESULT_SCROLLBAR_RESERVE,
        )

    def _set_column_widths(self, widths: tuple[int, ...]) -> None:
        hdr = self.table.horizontalHeader()
        for col, w in enumerate(widths):
            self.table.setColumnWidth(col, w)
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

    def _apply_compact_column_widths(self) -> None:
        from PyQt6.QtGui import QFontMetrics

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
            html = (
                "<div style='margin:0'>"
                f"<div style='color:#d7e2dc;font-size:14px;font-weight:700'>{_summary_title(result, self._temp_labels)}</div>"
                "<table style='margin-top:3px' cellspacing='0' cellpadding='0'><tr>"
                + _summary_metric_html("Udc", f"{vdc_disp:.1f}", "V", "#4fdbe8")
                + _summary_metric_html("Imax", f"{sc.ic_max:.1f}", "A", "#f2d06b")
                + _summary_metric_html("Tsc", f"{sc.tsc:.3f}", "us", "#f4a261")
                + "</tr><tr>"
                + _summary_metric_html("Esc 本管", _fmt(sc.esc_dut), "J", "#8fd17f")
                + _summary_metric_html("Esc 对管", _fmt(sc.esc_other), "J", "#7cc7e8")
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
        eon_disp = "—" if result.single_pulse_mode else _fmt_energy(on.eon)
        err_disp = "—" if result.single_pulse_mode else _fmt_energy(rr.err)
        note = mode_note + warn
        html = (
            "<div style='margin:0'>"
            f"<div style='color:#d7e2dc;font-size:14px;font-weight:700'>{_summary_title(result, self._temp_labels)}</div>"
            "<table style='margin-top:3px' cellspacing='0' cellpadding='0'>"
            "<tr>"
            + _summary_metric_html("Vdc", f"{vdc_disp:.1f}", "V", "#4fdbe8")
            + _summary_metric_html("Idc", f"{idc_disp:.1f}", "A", "#7cc7e8")
            + "</tr><tr>"
            + _summary_metric_html("Eoff", _fmt_energy(off.eoff), "mJ", ENERGY_TEXT_COLOR)
            + _summary_metric_html("Eon", eon_disp, "mJ", ENERGY_TEXT_COLOR)
            + _summary_metric_html("Err", err_disp, "mJ", ENERGY_TEXT_COLOR)
            + "</tr></table>"
            f"<div style='margin-top:3px;color:#aeb8b8;font-size:11px'>{note}</div>"
            "</div>"
        )
        self.summary.setText(html)

    def set_mode_placeholder(self, title: str, detail: str) -> None:
        """非双脉冲模式或功能未就绪时清空参数表并显示说明。"""
        self.table.clearSpans()
        html = f"""
        <p style='margin:0;color:#89b4fa;font-size:13px'><b>{title}</b></p>
        <p style='margin:8px 0 0 0;color:#a6adc8;font-size:12px'>{detail}</p>
        """
        self.summary.setText(html)
        self.table.setRowCount(0)

    def set_result(self, result: ExtractResult) -> None:
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
                if section == "关断过程" and name == "串扰电压":
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
        self.table.clearSpans()
        self.table.setRowCount(len(rows))
        self._row_keys = []
        self._row_meta = []
        self._section_ranges = {}
        param_font = _result_font("Microsoft YaHei UI", bold=True)
        section_font = _result_font("Microsoft YaHei UI", bold=True)
        value_font = _result_font("Cascadia Mono", bold=True)
        utility_font = _result_font("Microsoft YaHei UI")
        for r, (section, name, unit, rng_disp, val, bg) in enumerate(rows):
            self._row_meta.append((section, name))
            color = QColor(bg)
            text_color = QColor(
                ENERGY_TEXT_COLOR if name in ENERGY_NAMES else TEXT_ON_SECTION
            )
            row_key = SLOPE_ROW_KEYS.get((section, name))
            self._row_keys.append(row_key)
            if section not in self._section_ranges:
                self._section_ranges[section] = (r, 1)
            else:
                start, count = self._section_ranges[section]
                self._section_ranges[section] = (start, count + 1)

            section_shadow_item = _SectionTableItem(section)
            section_shadow_item.setBackground(QColor(_section_base_color(section)))
            section_shadow_item.setForeground(QColor(TEXT_ON_SECTION))
            section_shadow_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            section_shadow_item.setFont(section_font)
            self.table.setItem(r, 0, section_shadow_item)

            for c, text in ((1, name), (2, unit)):
                item = QTableWidgetItem(text)
                item.setBackground(color)
                item.setForeground(text_color)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 1:
                    item.setFont(param_font)
                else:
                    item.setFont(utility_font)
                self.table.setItem(r, c, item)

            range_item = QTableWidgetItem(rng_disp)
            range_item.setBackground(color)
            range_item.setForeground(text_color)
            range_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            range_item.setFont(utility_font)
            if row_key or (section == "关断过程" and name == "Eoff"):
                range_item.setToolTip("双击修改范围取值")
            self.table.setItem(r, 3, range_item)
            val_item = QTableWidgetItem(val)

            val_item.setBackground(color)
            val_item.setForeground(text_color)
            val_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            val_item.setFont(value_font)
            self.table.setItem(r, 4, val_item)

        for section, (start, count) in self._section_ranges.items():
            section_item = _SectionTableItem(section, _section_stack_label(section))
            section_item.setBackground(QColor(_section_base_color(section)))
            section_item.setForeground(QColor(TEXT_ON_SECTION))
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
        active_section = self._active_metric[0] if self._active_metric else None
        for section, (start, count) in self._section_ranges.items():
            active = section == active_section
            bg = QColor(SECTION_ACTIVE_BG if active else _section_base_color(section))
            fg = QColor(SECTION_ACTIVE_TEXT if active else TEXT_ON_SECTION)
            for r in range(start, start + count):
                item = self.table.item(r, 0)
                if item is None:
                    continue
                item.setBackground(bg)
                item.setForeground(fg)

    def set_active_metric(self, section: str, name: str) -> None:
        self._active_metric = (section, name)
        for r, (sec, nm) in enumerate(self._row_meta):
            if sec == section and nm == name:
                self.table.setCurrentCell(r, 1)
                self.table.selectRow(r)
                break
        self._refresh_section_highlight()

    def _on_cell_clicked(self, row: int, col: int) -> None:
        # 点击任意列都联动波形定位，避免仍停留在旧交互模式
        if row < 0 or row >= len(self._row_meta):
            return
        section, name = self._row_meta[row]
        self.set_active_metric(section, name)
        if self._on_value_clicked is None:
            return
        self._on_value_clicked(section, name)

    def set_metric_value(self, section: str, name: str, value: float) -> None:
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
