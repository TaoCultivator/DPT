from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from dpt_extractor.gui.theme import DARK_STYLESHEET
from dpt_extractor.models.slope_range import (
    AUTO_MAX_SLOPE_LABEL,
    AUTO_MAX_SLOPE_SPAN_PERCENT,
    CUSTOM_RANGE_LABEL,
    RR_DIDT_CUSTOM_IDM,
    RR_DIDT_CUSTOM_IF_IRM,
    SLOPE_RANGE_PRESETS,
    SlopeRange,
    auto_max_slope_range,
    preset_index_for_range,
    preset_to_range,
)


class SlopeRangeDialog(QDialog):
    """在一个窗口中选择预设或输入自定义斜率百分比范围。"""

    def __init__(
        self,
        parent=None,
        title: str = "取值范围",
        initial: SlopeRange | None = None,
        *,
        row_key: str | None = None,
        ic_reference: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.setStyleSheet(DARK_STYLESHEET)

        self._result: SlopeRange | None = None
        self._row_key = row_key
        self._initial = initial or SlopeRange(90.0, 10.0)
        self._ic_reference = ic_reference or self._initial.ic_reference

        layout = QVBoxLayout(self)
        self.range_selector = QComboBox()
        self.range_selector.setAccessibleName("选择范围")
        if row_key is not None:
            presets = SLOPE_RANGE_PRESETS.get(row_key, [])
            self.range_selector.addItems(
                [str(preset[0]) for preset in presets]
                + [AUTO_MAX_SLOPE_LABEL, CUSTOM_RANGE_LABEL]
            )
            preset_index = preset_index_for_range(row_key, self._initial)
            if self._initial.is_auto_max:
                self.range_selector.setCurrentText(AUTO_MAX_SLOPE_LABEL)
            else:
                self.range_selector.setCurrentIndex(
                    preset_index
                    if preset_index >= 0
                    else self.range_selector.count() - 1
                )
            selector_form = QFormLayout()
            selector_form.addRow("选择范围", self.range_selector)
            layout.addLayout(selector_form)
        else:
            self.range_selector.addItem(CUSTOM_RANGE_LABEL)
            self.range_selector.hide()

        self.algorithm_editor = QWidget()
        algorithm_form = QFormLayout(self.algorithm_editor)
        algorithm_form.setContentsMargins(0, 0, 0, 0)
        self.algorithm_selector = QComboBox()
        self.algorithm_selector.setAccessibleName("反向恢复算法")
        self.algorithm_selector.addItems(
            [RR_DIDT_CUSTOM_IDM, RR_DIDT_CUSTOM_IF_IRM]
        )
        if self._initial.ic_reference == "if_irm":
            self.algorithm_selector.setCurrentIndex(1)
        algorithm_form.addRow("算法", self.algorithm_selector)
        if self._row_key == "rr_didt":
            algorithm_policy = self.algorithm_editor.sizePolicy()
            algorithm_policy.setRetainSizeWhenHidden(True)
            self.algorithm_editor.setSizePolicy(algorithm_policy)
        layout.addWidget(self.algorithm_editor)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#a6adc8;font-size:12px;")
        layout.addWidget(self.hint)

        self.custom_editor = QWidget()
        custom_form = QFormLayout(self.custom_editor)
        custom_form.setContentsMargins(0, 0, 0, 0)
        self.spin_start = QDoubleSpinBox()
        self.spin_end = QDoubleSpinBox()
        for spin, accessible_name in (
            (self.spin_start, "起点百分比"),
            (self.spin_end, "终点百分比"),
        ):
            spin.setAccessibleName(accessible_name)
            spin.setRange(0.0, 100.0)
            spin.setDecimals(1)
            spin.setSuffix(" %")
            spin.setSingleStep(5.0)
        self.spin_start.setValue(self._initial.start_pct)
        self.spin_end.setValue(self._initial.end_pct)
        custom_form.addRow("起点百分比", self.spin_start)
        custom_form.addRow("终点百分比", self.spin_end)
        if self._row_key is not None:
            custom_policy = self.custom_editor.sizePolicy()
            custom_policy.setRetainSizeWhenHidden(True)
            self.custom_editor.setSizePolicy(custom_policy)
        layout.addWidget(self.custom_editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.range_selector.currentIndexChanged.connect(
            self._on_selection_changed
        )
        self.algorithm_selector.currentIndexChanged.connect(
            self._on_algorithm_changed
        )
        # Measure the largest state before the native window is shown.  If the
        # dialog is first centered in its compact preset state and expands
        # afterward, Windows can keep the old top-left position while the
        # frame crosses the work-area edge, producing QWindows setGeometry
        # warnings and a visibly jumping dialog.  Preallocating the maximum
        # content height keeps preset/custom switching geometry-stable.
        self.custom_editor.setVisible(True)
        self.algorithm_editor.setVisible(self._row_key == "rr_didt")
        self._update_hint()
        layout.activate()
        expanded_hint = self.sizeHint()
        self.setMinimumHeight(expanded_hint.height())
        self.resize(
            max(self.minimumWidth(), expanded_hint.width()),
            expanded_hint.height(),
        )
        self._on_selection_changed()

    def range_value(self) -> SlopeRange | None:
        return self._result

    def _is_custom(self) -> bool:
        return self.range_selector.currentText() == CUSTOM_RANGE_LABEL

    def _is_auto_max(self) -> bool:
        return self.range_selector.currentText() == AUTO_MAX_SLOPE_LABEL

    def _current_ic_reference(self) -> str:
        if self._row_key == "rr_didt" and self._is_custom():
            if self.algorithm_selector.currentText() == RR_DIDT_CUSTOM_IF_IRM:
                return "if_irm"
            return "idm"
        return self._ic_reference

    def _update_hint(self) -> None:
        if self._is_auto_max():
            self.hint.setText(
                f"在该参数既有主沿内滑动 {AUTO_MAX_SLOPE_SPAN_PERCENT:g}% 幅度窗口，"
                "自动选择平均斜率最大且连续、单调、近似直线的区间；"
                "最终数值和 A/B 光标仍由原始波形交点计算。"
            )
            return
        ic_reference = self._current_ic_reference()
        if ic_reference == "if_irm":
            text = (
                "零基准算法：thA = H0 + 起点%·(Ha−H0)，"
                "thB = H0 + 终点%·(Hb−H0)。"
            )
        elif ic_reference == "idm":
            text = (
                "IDM 算法：Ha=恢复尾稳定基准、Hb=带符号 IDM，"
                "按归一化主换流沿查找百分比穿越。"
            )
        else:
            text = "输入电流或电压幅值的起止百分比（沿开关方向穿越）。"
        self.hint.setText(text)

    def _on_selection_changed(self) -> None:
        custom = self._is_custom()
        self.custom_editor.setVisible(custom)
        self.algorithm_editor.setVisible(custom and self._row_key == "rr_didt")
        self._update_hint()
        if custom and self.isVisible():
            self.spin_start.setFocus()
            self.spin_start.selectAll()

    def _on_algorithm_changed(self) -> None:
        self._update_hint()

    def _accept(self) -> None:
        if self._is_auto_max() and self._row_key is not None:
            self._result = auto_max_slope_range(self._row_key)
            self.accept()
            return
        if not self._is_custom() and self._row_key is not None:
            selected = self.range_selector.currentText()
            for preset in SLOPE_RANGE_PRESETS.get(self._row_key, []):
                if str(preset[0]) == selected:
                    self._result = preset_to_range(preset)
                    self.accept()
                    return
            return

        start = float(self.spin_start.value())
        end = float(self.spin_end.value())
        ic_reference = self._current_ic_reference()
        if abs(start - end) < 0.1 and ic_reference != "if_irm":
            return
        direction = "fall" if start > end else "rise"
        preset_label = (
            f"{start:g}%IF→{end:g}%IRM" if ic_reference == "if_irm" else ""
        )
        self._result = SlopeRange(
            start,
            end,
            ic_reference=ic_reference,
            ic_direction=direction,
            preset_label=preset_label,
        )
        self.accept()
