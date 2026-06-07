from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
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
from dpt_extractor.gui.theme import SECTION_ENERGY, SECTION_OFF, SECTION_ON, SECTION_RR, TEXT_ON_SECTION
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


def format_metric_display(section: str, name: str, value: float) -> str:
    """与 set_result 填表规则一致，避免交互写回时位数跳动。"""
    _ = section
    if name in {"Eoff", "Eon", "Err"}:
        return _fmt_energy(value)
    return _fmt(value)


def _range_label_for_row(section: str, name: str, result: ExtractResult) -> str:
    off, on, rr = result.turn_off, result.turn_on, result.reverse_recovery
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


class ResultTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.summary = QLabel()
        self.summary.setFixedHeight(58)
        self.summary.setWordWrap(False)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["分区", "参数", "单位", "范围取值", "数值"]
        )
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, stretch=1)

        self._slope_ranges = default_slope_ranges()
        self._on_range_changed: Callable[[str, SlopeRange], None] | None = None
        self._on_eoff_pre_changed: Callable[[float], None] | None = None
        self._on_value_clicked: Callable[[str, str], None] | None = None
        self._row_keys: list[str | None] = []
        self._row_meta: list[tuple[str, str]] = []
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.cellClicked.connect(self._on_cell_clicked)

        pane_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        pane_policy.setHeightForWidth(False)
        self.setSizePolicy(pane_policy)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.preferred_panel_width(), 680)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(340, 400)

    def preferred_panel_width(self) -> int:
        """参数表侧栏紧凑宽度：列宽之和 + 边距，保证文字完整显示。"""
        n = self.table.columnCount()
        if n <= 0:
            table_w = 396
        else:
            table_w = sum(self.table.columnWidth(c) for c in range(n))
        # layout margins(8*2) + 竖滚动条预留
        return int(table_w + 2 * self.table.frameWidth() + 16 + 14)

    def _apply_compact_column_widths(self) -> None:
        from PyQt6.QtGui import QFontMetrics

        fm = QFontMetrics(self.table.font())
        rng_w = 124
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 3)
            if item is not None:
                rng_w = max(rng_w, fm.horizontalAdvance(item.text()) + 20)
        char2 = fm.horizontalAdvance("00")
        val_pad = 16 + char2
        val_w = 72 + char2
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 4)
            if item is not None:
                val_w = max(val_w, fm.horizontalAdvance(item.text()) + val_pad)
        widths = (76, 84, 40, min(rng_w, 148), min(val_w, 88 + char2))
        hdr = self.table.horizontalHeader()
        for col, w in enumerate(widths):
            self.table.setColumnWidth(col, w)
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

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
        html = f"""
        <p style='margin:0;color:#cdd6f4;font-size:13px'>
        <b style='color:#89b4fa'>工况</b>
        {f" &nbsp; <span style='color:#cba6f7'>{result.profile_code}</span>" if result.profile_code else ""}
        &nbsp; Vdc = <b>{vdc_disp:.1f} V</b> &nbsp;|&nbsp;
        Idc = <b>{idc_disp:.1f} A</b>
        {mode_note}
        </p>
        <p style='margin:6px 0 0 0;color:#a6adc8;font-size:12px'>
        <b style='color:#fab387'>Eoff</b> {_fmt_energy(off.eoff)} mJ &nbsp;
        <b style='color:#a6e3a1'>Eon</b> {eon_disp} mJ &nbsp;
        <b style='color:#89dceb'>Err</b> {err_disp} mJ
        {warn}
        </p>
        """
        self.summary.setText(html)

    def set_mode_placeholder(self, title: str, detail: str) -> None:
        """非双脉冲模式或功能未就绪时清空参数表并显示说明。"""
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

        def add(
            section: str,
            bg: str,
            items: list[tuple[str, str, float]],
            energy: set[str],
        ) -> None:
            for name, unit, val in items:
                bg_use = SECTION_ENERGY if name in energy else bg
                if section == "关断过程" and name == "串扰电压":
                    disp = f"{off.crosstalk_vmax:.2f}/{off.crosstalk_vmin:.2f}"
                elif section == "开通" and name == "串扰电压":
                    disp = f"{on.crosstalk_vmax:.2f}/{on.crosstalk_vmin:.2f}"
                else:
                    disp = _fmt_energy(val) if name in energy else _fmt(val)
                rng = _range_label_for_row(section, name, result) or "—"
                rows.append((section, name, unit, rng, disp, bg_use))

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

        self.table.setRowCount(len(rows))
        self._row_keys = []
        self._row_meta = []
        bold = QFont()
        bold.setBold(True)
        for r, (section, name, unit, rng_disp, val, bg) in enumerate(rows):
            self._row_meta.append((section, name))
            color = QColor(bg)
            row_key = SLOPE_ROW_KEYS.get((section, name))
            self._row_keys.append(row_key)

            for c, text in enumerate([section, name, unit]):
                item = QTableWidgetItem(text)
                item.setBackground(color)
                item.setForeground(QColor(TEXT_ON_SECTION))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 1:
                    item.setFont(bold)
                self.table.setItem(r, c, item)

            range_item = QTableWidgetItem(rng_disp)
            range_item.setBackground(color)
            range_item.setForeground(QColor(TEXT_ON_SECTION))
            range_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 3, range_item)
            val_item = QTableWidgetItem(val)

            val_item.setBackground(color)
            val_item.setForeground(QColor(TEXT_ON_SECTION))
            val_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 4, val_item)

        self._apply_compact_column_widths()
        self.setMaximumWidth(self.preferred_panel_width())
        vh = self.table.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vh.setDefaultSectionSize(26)

    def _on_cell_clicked(self, row: int, col: int) -> None:
        # 点击任意列都联动波形定位，避免仍停留在旧交互模式
        if row < 0 or row >= len(self._row_meta):
            return
        if self._on_value_clicked is None:
            return
        section, name = self._row_meta[row]
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
