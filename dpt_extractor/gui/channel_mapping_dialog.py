from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dpt_extractor.gui.theme import DARK_STYLESHEET
from dpt_extractor.models.bridge_profile import BridgeProfile, make_profile
from dpt_extractor.models.channel_mapping import (
    LOGICAL_SIGNALS,
    ChannelMapping,
    channels_for_mapping,
    default_mapping_for,
    infer_mapping_from_bundle,
    validate_mapping,
)
from dpt_extractor.models.channel_mapping import ChannelMappingStore, apply_mapping
from dpt_extractor.models.waveform import WaveformBundle


class ChannelMappingDialog(QDialog):
    """Map logical signals (Vge, Vce, …) to waveform channels."""

    def __init__(
        self,
        parent=None,
        phase: str = "W",
        bridge: str = "upper",
        bundle: WaveformBundle | None = None,
        store: ChannelMappingStore | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("通道映射")
        self.setMinimumWidth(480)
        self.setStyleSheet(DARK_STYLESHEET)
        self._phase = phase
        self._bridge = bridge
        self._bundle = bundle
        self._store = store or ChannelMappingStore()
        self._combos: dict[str, QComboBox] = {}
        self._ic_sum_cb: QCheckBox | None = None
        self._irr_diff_cb: QCheckBox | None = None
        self._mapping_result: ChannelMapping | None = None
        self._applied = False

        self._build_ui()
        self._load_initial_mapping()

    def mapping(self) -> ChannelMapping | None:
        return self._mapping_result

    def was_applied(self) -> bool:
        return self._applied

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        prof = make_profile(self._phase, self._bridge)
        title = QLabel(f"当前配置：{prof.display_name}")
        title.setStyleSheet("font-size:15px;font-weight:bold;color:#89b4fa;")
        layout.addWidget(title)

        ch_list = channels_for_mapping(self._bundle)
        if ch_list:
            ch_hint = "、".join(ch_list)
            hint_text = (
                f"为每个逻辑信号指定当前 TSS 波形中的通道：{ch_hint}。"
                "适用于探头接线与默认 U/V/W 模板不一致的情况。"
            )
        else:
            hint_text = "请先加载 TSS 波形；下拉列表将显示该文件中的 CH/MATH 通道。"
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#a6adc8;font-size:12px;")
        layout.addWidget(hint)

        form_frame = QFrame()
        form_frame.setStyleSheet(
            "QFrame { background-color: #242436; border: 1px solid #45475a; border-radius: 8px; }"
        )
        form = QFormLayout(form_frame)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        available = channels_for_mapping(self._bundle)

        for key, label, tip in LOGICAL_SIGNALS:
            combo = QComboBox()
            combo.setMinimumWidth(120)
            for ch in available:
                combo.addItem(ch, ch)
            combo.setToolTip(tip)
            self._combos[key] = combo
            name_lbl = QLabel(label)
            name_lbl.setStyleSheet("color:#cdd6f4;font-weight:bold;")
            if key == "ic":
                row_w = QWidget()
                h = QHBoxLayout(row_w)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(10)
                self._ic_sum_cb = QCheckBox(
                    "上桥总电流 = 下桥支路电流 + 电感电流（软件相加）"
                )
                self._ic_sum_cb.setStyleSheet("color:#a6adc8;font-size:12px;")
                self._ic_sum_cb.toggled.connect(self._on_ic_sum_toggled)
                h.addWidget(self._ic_sum_cb, stretch=0)
                h.addWidget(combo, stretch=1)
                form.addRow(name_lbl, row_w)
            elif key == "irr":
                row_w = QWidget()
                h = QHBoxLayout(row_w)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(10)
                self._irr_diff_cb = QCheckBox(
                    "下桥反向恢复 = 总电流 − 电感电流（软件相减）"
                )
                self._irr_diff_cb.setStyleSheet("color:#a6adc8;font-size:12px;")
                self._irr_diff_cb.toggled.connect(self._on_irr_diff_toggled)
                h.addWidget(self._irr_diff_cb, stretch=0)
                h.addWidget(combo, stretch=1)
                form.addRow(name_lbl, row_w)
            else:
                form.addRow(name_lbl, combo)

        layout.addWidget(form_frame)

        btn_row = QHBoxLayout()
        self.btn_infer = QPushButton("按标签识别")
        self.btn_infer.setToolTip("根据 TSS 中各通道的 Label 名称自动填充映射")
        self.btn_infer.clicked.connect(self._on_infer_labels)
        self.btn_reset = QPushButton("恢复默认")
        self.btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(self.btn_infer)
        btn_row.addWidget(self.btn_reset)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用并关闭")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_ic_sum_toggled(self, checked: bool) -> None:
        self._combos["ic"].setEnabled(not checked)
        if checked and self._irr_diff_cb is not None and self._irr_diff_cb.isChecked():
            self._irr_diff_cb.setChecked(False)

    def _on_irr_diff_toggled(self, checked: bool) -> None:
        self._combos["irr"].setEnabled(not checked)
        if checked and self._ic_sum_cb is not None and self._ic_sum_cb.isChecked():
            self._ic_sum_cb.setChecked(False)

    def _set_combo(self, key: str, value: str) -> None:
        combo = self._combos[key]
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.addItem(value, value)
            combo.setCurrentIndex(combo.count() - 1)

    def _apply_mapping_to_ui(self, mapping: ChannelMapping) -> None:
        d = mapping.to_dict()
        if self._ic_sum_cb is not None:
            self._ic_sum_cb.setChecked(bool(d.get("ic_from_sum_irr_il")))
            self._combos["ic"].setEnabled(not d.get("ic_from_sum_irr_il"))
        if self._irr_diff_cb is not None:
            self._irr_diff_cb.setChecked(bool(d.get("irr_from_ic_minus_il")))
            self._combos["irr"].setEnabled(not d.get("irr_from_ic_minus_il"))
        for key in self._combos:
            col = d.get(key)
            if col is None:
                continue
            if key == "ic" and d.get("ic_from_sum_irr_il"):
                continue
            if key == "irr" and d.get("irr_from_ic_minus_il"):
                continue
            if isinstance(col, str) and col:
                self._set_combo(key, col)

    def _load_initial_mapping(self) -> None:
        custom = self._store.get(self._phase, self._bridge)
        if custom:
            self._apply_mapping_to_ui(custom)
            return
        self._apply_mapping_to_ui(default_mapping_for(self._phase, self._bridge))

    def _on_infer_labels(self) -> None:
        inferred = infer_mapping_from_bundle(self._bundle, self._bridge)
        if inferred is None:
            QMessageBox.information(
                self,
                "无法识别",
                "当前 TSS 无通道标签信息，或标签与上/下桥无法匹配。",
            )
            return
        self._apply_mapping_to_ui(inferred)

    def _collect_mapping(self) -> ChannelMapping:
        parts = {k: self._combos[k].currentData() for k in self._combos}
        use_sum = self._ic_sum_cb.isChecked() if self._ic_sum_cb else False
        use_diff = self._irr_diff_cb.isChecked() if self._irr_diff_cb else False
        if use_sum:
            parts["ic"] = ""
        if use_diff:
            parts["irr"] = ""
        return ChannelMapping(
            **parts,
            ic_from_sum_irr_il=use_sum,
            irr_from_ic_minus_il=use_diff,
        )

    def _on_reset(self) -> None:
        self._apply_mapping_to_ui(default_mapping_for(self._phase, self._bridge))
        self._store.clear(self._phase, self._bridge)

    def _on_apply(self) -> None:
        if not channels_for_mapping(self._bundle):
            QMessageBox.warning(
                self,
                "未加载 TSS",
                "请先加载 TSS 波形文件，再配置通道映射。",
            )
            return
        mapping = self._collect_mapping()
        errors = validate_mapping(mapping, self._bundle)
        if errors:
            QMessageBox.warning(
                self,
                "映射无效",
                "请修正以下问题：\n\n" + "\n".join(f"• {e}" for e in errors),
            )
            return
        self._store.set(self._phase, self._bridge, mapping)
        self._mapping_result = mapping
        self._applied = True
        self.accept()


def resolve_profile(
    phase: str,
    bridge: str,
    store: ChannelMappingStore | None = None,
) -> tuple[BridgeProfile, bool]:
    """Return profile with optional user channel override; bool = is custom."""
    store = store or ChannelMappingStore()
    base = make_profile(phase, bridge)
    custom = store.get(phase, bridge)
    if custom is None:
        return base, False
    return apply_mapping(base, custom), True
