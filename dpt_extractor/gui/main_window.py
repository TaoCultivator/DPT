from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import time
import numpy as np

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QApplication,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from dpt_extractor.config.loader import AppConfig, load_config
from dpt_extractor.export.excel_export import default_export_path, export_to_excel
from dpt_extractor.gui.channel_mapping_dialog import resolve_profile
from dpt_extractor.gui.recent_paths import (
    open_dialog_start_dir,
    save_dialog_initial_path,
    set_last_export_path,
    set_last_open_path,
)
from dpt_extractor.gui.result_table import ResultTable
from dpt_extractor.gui.theme import DARK_STYLESHEET, SUMMARY_STYLE
from dpt_extractor.gui.waveform_plot import WaveformPlot
from dpt_extractor.models.channel_mapping import (
    LOGICAL_SIGNAL_KEYS,
    ChannelMapping,
    ChannelMappingStore,
    apply_mapping,
    validate_mapping,
)
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import (
    PHASES,
    UPPER_BRIDGE,
    BridgeProfile,
    guess_profile_from_path,
    make_profile,
)
from dpt_extractor.models.results import ExtractResult
from dpt_extractor.models.slope_range import (
    SLOPE_ROW_KEYS,
    SlopeRange,
    default_slope_ranges,
    normalize_slope_range,
)
from dpt_extractor.models.waveform import WaveformBundle
from dpt_extractor.metrics.iec_windows import (
    IntegrationWindow,
    eoff_energy_markers,
    eoff_window_scope_example,
    eon_energy_markers,
    eon_window_scope_example,
    err_energy_markers,
    err_window_scope_example,
    integrate_err_recovery,
    integrate_vi_window,
)
from dpt_extractor.metrics.slopes import (
    DidtCrossingResult,
    DvdtCrossingResult,
    analyze_rr_recovery_current,
    didt_between_base_top,
    didt_max,
    didt_rr_recovery,
    dvdt_between_base_top,
    dvdt_max,
)
from dpt_extractor.metrics.derived import crosstalk_extrema
from dpt_extractor.metrics.iec_timings import (
    turn_off_ic_fall_window,
    turn_on_ic_top,
    turn_off_timing_instants,
    turn_on_vce_top_from_ic_rise,
    turn_on_timing_instants,
)
from dpt_extractor.metrics.plateau_level import _turn_on_vce_pre_fall_slice
from dpt_extractor.models.test_mode import MODE_UI_LABELS, TestMode, parse_test_mode
from dpt_extractor.pipeline.extract import _turn_on_delta_vce_knee_point
from dpt_extractor.pipeline.run_extract import run_extraction
from dpt_extractor.pipeline.short_circuit_extract import ShortCircuitExtractNotReady


@dataclass
class _WaveformLoadOutcome:
    path: str
    bundle: WaveformBundle
    guessed: BridgeProfile
    profile: BridgeProfile
    inferred: ChannelMapping | None
    mapping_custom: bool
    result: ExtractResult | None
    short_circuit_not_ready: bool
    load_ms: float
    extract_ms: float


def _compute_waveform_load_outcome(
    path: str,
    cfg: AppConfig,
) -> _WaveformLoadOutcome:
    load_t0 = time.perf_counter()
    bundle = load_waveform(path)
    load_t1 = time.perf_counter()

    guessed = guess_profile_from_path(path)
    base_profile = make_profile(guessed.phase, guessed.bridge)
    custom_mapping = ChannelMappingStore().get(guessed.phase, guessed.bridge)
    mapping_custom = custom_mapping is not None
    profile = (
        apply_mapping(base_profile, custom_mapping)
        if custom_mapping is not None
        else base_profile
    )

    extract_t0 = time.perf_counter()
    try:
        result = run_extraction(bundle, profile, cfg)
        short_circuit_not_ready = False
    except ShortCircuitExtractNotReady:
        result = None
        short_circuit_not_ready = True
    extract_t1 = time.perf_counter()

    return _WaveformLoadOutcome(
        path=path,
        bundle=bundle,
        guessed=guessed,
        profile=profile,
        inferred=None,
        mapping_custom=mapping_custom,
        result=result,
        short_circuit_not_ready=short_circuit_not_ready,
        load_ms=(load_t1 - load_t0) * 1000.0,
        extract_ms=(extract_t1 - extract_t0) * 1000.0,
    )


class _WaveformLoadSignals(QObject):
    finished = pyqtSignal(int, object)
    failed = pyqtSignal(int, str, str)


class _WaveformLoadTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        path: str,
        cfg: AppConfig,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.path = path
        self.cfg = cfg
        self.signals = _WaveformLoadSignals()

    def run(self) -> None:
        try:
            outcome = _compute_waveform_load_outcome(
                self.path,
                self.cfg,
            )
        except Exception as exc:
            self.signals.failed.emit(self.request_id, self.path, str(exc))
            return
        self.signals.finished.emit(self.request_id, outcome)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DPT 双脉冲参数提取工具")
        self.resize(1280, 800)
        self.setMinimumSize(960, 620)
        stylesheet = DARK_STYLESHEET + SUMMARY_STYLE
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet)
        self.setStyleSheet(stylesheet)

        self.cfg: AppConfig = load_config()
        self.bundle: WaveformBundle | None = None
        self.profile: BridgeProfile = UPPER_BRIDGE
        self.result: ExtractResult | None = None
        self._current_path: str = ""
        self._channel_store = ChannelMappingStore()
        self._mapping_custom = False
        self._slope_ranges = default_slope_ranges()
        # 记忆每个参数手动调整的光标区间（µs），再次点击时恢复而非回退默认窗口
        self._manual_intervals: dict[tuple[str, str], tuple[float, float]] = {}
        # 开通电流：保存 A/B 时刻 + Hb/Ha 电平 (µs, µs, A, A)
        self._manual_turn_on_current: tuple[float, float, float, float] | None = None
        # Eoff/Eon 四光标 (A_t, B_t, Ha_v, Hb_a)
        self._manual_energy: dict[tuple[str, str], tuple[float, float, float, float]] = {}
        # ΔVce 四光标状态 (A_t, B_t, Ha_v, Hb_v)，再次点击时恢复
        self._manual_delta_vce: dict[tuple[str, str], tuple[float, float, float, float]] = {}
        # 手动光标绑定的波形源路径；换文件后不再恢复旧光标位置
        self._manual_waveform_source: str = ""
        # dv/dt、di/dt：段窗 (µs,µs) + Ha Top + Hb Base
        self._manual_dvdt: dict[tuple[str, str], tuple[float, float, float, float]] = {}
        self._manual_didt: dict[tuple[str, str], tuple[float, float, float, float]] = {}
        # Trr：Ha、Hb、A/B (µs)、尖峰索引（与 Irr 区间模式分离）
        self._manual_trr_measure: tuple[float, float, float, float, int | None] | None = None
        self._active_slope_param: tuple[str, str] | None = None
        self._load_request_id = 0
        self._load_tasks: dict[int, _WaveformLoadTask] = {}
        self._load_pool = QThreadPool.globalInstance()

        self._build_ui()
        self.result_table.set_range_handler(self._on_slope_range_changed)
        self.result_table.set_eoff_pre_handler(self._on_eoff_pre_changed)
        self.result_table.set_value_click_handler(self._on_value_clicked)
        self.result_table.set_slope_ranges(self._slope_ranges)
        # 持久 A/B 光标：global 模式拖动时显示测量读数；横向 Ha/Hb 同步
        self.wave_plot.set_global_cursor_handler(self._on_global_cursors_moved)
        self.wave_plot.set_horizontal_cursor_handler(self._on_horizontal_cursors_moved)
        self.wave_plot.channelMappingRequested.connect(
            self._on_waveform_channel_mapping_requested
        )
        self.wave_plot.channelLabelChanged.connect(
            self._on_waveform_channel_label_changed
        )

    def _build_ui(self) -> None:
        self.wave_plot = WaveformPlot()

        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        tb_root = QVBoxLayout(toolbar)
        tb_root.setContentsMargins(8, 6, 8, 6)
        tb_root.setSpacing(4)

        self.btn_open = QPushButton("📂  打开文件")
        self.btn_open.setToolTip("支持 Tektronix TSS 会话文件")
        self.btn_open.clicked.connect(self._open_waveform)

        self.combo_phase = QComboBox()
        self.combo_phase.setMinimumContentsLength(4)
        for p in PHASES:
            self.combo_phase.addItem(f"{p}相", p)
        self.combo_phase.currentIndexChanged.connect(self._on_phase_bridge_changed)

        self.combo_bridge = QComboBox()
        self.combo_bridge.setMinimumContentsLength(4)
        self.combo_bridge.addItem("上桥", "upper")
        self.combo_bridge.addItem("下桥", "lower")
        self.combo_bridge.currentIndexChanged.connect(self._on_phase_bridge_changed)

        self.combo_std = QComboBox()
        self.combo_std.addItems(["IEC60747-9", "Infineon (Eon Ic起点)", "Mitsubishi"])
        self.combo_std.setToolTip("能量积分窗口判据（当前主实现为 IEC60747-9）")
        self.combo_std.setMaximumWidth(168)
        self.combo_std.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

        self.spin_vdc = QDoubleSpinBox()
        self.spin_vdc.setRange(0, 5000)
        self.spin_vdc.setDecimals(1)
        self.spin_vdc.setSuffix(" V")
        self.spin_vdc.setSpecialValueText("自动测量")
        self.spin_vdc.setValue(0)
        self.spin_vdc.setMaximumWidth(118)
        self.spin_vdc.valueChanged.connect(self._on_vdc_changed)

        self.btn_recalc = QPushButton("↻  重新计算")
        self.btn_recalc.clicked.connect(lambda: self._recalculate(reset_manual=True))
        self.btn_export = QPushButton("💾  导出 Excel")
        self.btn_export.clicked.connect(self._export_excel)

        self.lbl_map_status = QLabel("")
        self.lbl_map_status.setStyleSheet("color:#f9e2af;font-size:11px;")
        self.lbl_map_status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(self.btn_open)
        row1.addWidget(QLabel("相别"))
        row1.addWidget(self.combo_phase)
        row1.addWidget(QLabel("桥臂"))
        row1.addWidget(self.combo_bridge)
        row1.addWidget(QLabel("判据"))
        row1.addWidget(self.combo_std)
        row1.addWidget(QLabel("Vdc"))
        row1.addWidget(self.spin_vdc)
        row1.addWidget(self.btn_recalc)
        row1.addWidget(self.btn_export)
        row1.addWidget(self._build_context_menu_selector())
        row1.addWidget(self.lbl_map_status, stretch=1)
        row1.addWidget(QLabel("测试"))
        self.combo_test_mode = QComboBox()
        for mode in (TestMode.DPT, TestMode.SHORT_CIRCUIT):
            self.combo_test_mode.addItem(MODE_UI_LABELS[mode], mode.value)
        idx = self.combo_test_mode.findData(
            parse_test_mode(self.cfg.test_mode.mode).value
        )
        if idx >= 0:
            self.combo_test_mode.setCurrentIndex(idx)
        self.combo_test_mode.setMinimumContentsLength(8)
        self.combo_test_mode.setMaximumWidth(112)
        self.combo_test_mode.setToolTip(
            "双脉冲与短路测试使用独立计算流程；短路功能后续开放"
        )
        self.combo_test_mode.currentIndexChanged.connect(self._on_test_mode_changed)
        row1.addWidget(self.combo_test_mode)

        pulse_sep = QFrame()
        pulse_sep.setFrameShape(QFrame.Shape.VLine)
        pulse_sep.setStyleSheet("color:#45475a;")

        self.lbl_pulse_count = QLabel("— 波")
        self.lbl_pulse_count.setStyleSheet("color:#a6adc8;font-size:11px;")

        self.lbl_off_pulse = QLabel("关断")
        self.spin_off_pulse = QSpinBox()
        self.spin_off_pulse.setRange(1, 10)
        self.spin_off_pulse.setValue(self.cfg.pulse_selection.off_pulse)
        self.spin_off_pulse.setFixedWidth(40)
        self.spin_off_pulse.setToolTip("取第 N 个门极脉冲的关断沿")

        self.lbl_on_pulse = QLabel("开通")
        self.spin_on_pulse = QSpinBox()
        self.spin_on_pulse.setRange(1, 10)
        self.spin_on_pulse.setValue(self.cfg.pulse_selection.on_pulse)
        self.spin_on_pulse.setFixedWidth(40)
        self.spin_on_pulse.setToolTip(
            "取第 N 个门极脉冲的开通沿；可与关断同波（分析该脉冲的开通与关断）"
        )

        self.spin_off_pulse.valueChanged.connect(self._on_pulse_spin_changed)
        self.spin_on_pulse.valueChanged.connect(self._on_pulse_spin_changed)

        self._pulse_toolbar_widgets = (
            pulse_sep,
            self.lbl_pulse_count,
            self.lbl_off_pulse,
            self.spin_off_pulse,
            self.lbl_on_pulse,
            self.spin_on_pulse,
        )

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(pulse_sep)
        row2.addWidget(self.lbl_pulse_count)
        row2.addWidget(self.lbl_off_pulse)
        row2.addWidget(self.spin_off_pulse)
        row2.addWidget(self.lbl_on_pulse)
        row2.addWidget(self.spin_on_pulse)
        row2.addStretch(1)

        tb_root.addLayout(row1)
        tb_root.addLayout(row2)

        self.result_table = ResultTable()

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.wave_plot)
        self.splitter.addWidget(self.result_table)
        self.splitter.setStretchFactor(0, 5)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setHandleWidth(5)
        self._split_ratio = 0.74
        self._splitter_user_moved = False
        self.splitter.setSizes([1036, 364])
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        splitter = self.splitter

        pane_policy = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        pane_policy.setHeightForWidth(False)
        self.wave_plot.setSizePolicy(pane_policy)
        self.result_table.setSizePolicy(pane_policy)
        self.wave_plot.setMinimumWidth(360)
        self.result_table.setMinimumWidth(280)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("请打开 Tektronix TSS 会话文件")
        self._apply_test_mode_ui()

    def _build_context_menu_selector(self) -> QWidget:
        box = QFrame()
        box.setObjectName("contextMenuSelector")
        box.setStyleSheet(
            "QFrame#contextMenuSelector{background:#2a2a2a;"
            "border:1px solid #585858;border-radius:5px;}"
            "QLabel#contextMenuSelectorLabel{color:#aeb6d8;font-size:12px;"
            "padding-left:8px;padding-right:2px;}"
            "QPushButton#contextMenuSelectorButton{background:#3d3d3d;"
            "color:#f0f0f0;border:1px solid #6a6a6a;border-radius:5px;"
            "padding:4px 10px;min-height:26px;min-width:52px;}"
            "QPushButton#contextMenuSelectorButton:hover{background:#505050;}"
            "QPushButton#contextMenuSelectorButton:checked{background:#28bce8;"
            "color:#061014;border-color:#8fd3ff;}"
        )
        lay = QHBoxLayout(box)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(4)

        label = QLabel("功能菜单")
        label.setObjectName("contextMenuSelectorLabel")
        lay.addWidget(label)

        group = QButtonGroup(box)
        group.setExclusive(True)
        self._context_menu_button_group = group
        for text, key, tip in (
            ("光标", "cursor", "右键菜单显示光标类型、模式与配置"),
            ("缩放", "zoom", "右键菜单显示框选局部放大、水平缩放与重置"),
            ("视图", "view", "右键菜单显示视图配置与显示模式"),
            ("纵轴", "y", "右键菜单显示纵轴功能"),
            ("截图", "capture", "复制当前窗口截图到剪贴板"),
            ("更多", "all", "右键菜单显示完整示波器功能"),
        ):
            btn = QPushButton(text)
            btn.setObjectName("contextMenuSelectorButton")
            btn.setToolTip(tip)
            if key == "capture":
                btn.setCheckable(False)
                btn.clicked.connect(lambda checked=False: self.wave_plot._copy_screenshot_to_clipboard())
            else:
                btn.setCheckable(True)
                btn.clicked.connect(
                    lambda checked=False, menu_key=key: self.wave_plot.set_context_menu_group(
                        menu_key
                    )
                )
                group.addButton(btn)
            lay.addWidget(btn)
            if key == self.wave_plot.context_menu_group():
                btn.setChecked(True)
        return box

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_splitter_sizes()

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        sizes = self.splitter.sizes()
        total = sum(sizes)
        if total > 0:
            self._split_ratio = sizes[0] / total
            self._splitter_user_moved = True

    def _sync_splitter_sizes(self) -> None:
        """波形区尽量大；参数表按内容紧凑宽度，避免拖动光标触发布局抖动。"""
        w = self.splitter.width()
        if w < 200:
            return
        handle = self.splitter.handleWidth()
        inner = max(1, w - handle)
        compact_right = self.result_table.preferred_panel_width()
        if self._splitter_user_moved:
            left = max(
                self.wave_plot.minimumWidth(),
                int(round(inner * self._split_ratio)),
            )
            right = max(self.result_table.minimumWidth(), inner - left)
        else:
            right = max(
                self.result_table.minimumWidth(),
                min(compact_right, int(inner * 0.34)),
            )
            left = max(self.wave_plot.minimumWidth(), inner - right)
        if left + right > inner:
            left = max(self.wave_plot.minimumWidth(), inner - right)
        self.result_table.setMaximumWidth(compact_right)
        self.splitter.setSizes([left, right])

    def _on_vdc_changed(self, val: float) -> None:
        self.cfg.vdc_override = None if val <= 0 else val

    def _set_pulse_spin_values(self, off_pulse: int, on_pulse: int) -> None:
        self.spin_off_pulse.blockSignals(True)
        self.spin_on_pulse.blockSignals(True)
        try:
            self.spin_off_pulse.setValue(max(1, min(10, off_pulse)))
            self.spin_on_pulse.setValue(max(1, min(10, on_pulse)))
        finally:
            self.spin_off_pulse.blockSignals(False)
            self.spin_on_pulse.blockSignals(False)

    def _update_pulse_toolbar(self, detected_count: int, off_pulse: int, on_pulse: int) -> None:
        mx = max(1, min(10, detected_count)) if detected_count > 0 else 10
        self.spin_off_pulse.blockSignals(True)
        self.spin_on_pulse.blockSignals(True)
        try:
            self.spin_off_pulse.setMaximum(mx)
            self.spin_on_pulse.setMaximum(mx)
            self.spin_off_pulse.setValue(max(1, min(mx, off_pulse)))
            self.spin_on_pulse.setValue(max(1, min(mx, on_pulse)))
            single = detected_count == 1
            self.spin_on_pulse.setEnabled(not single)
            self.lbl_on_pulse.setEnabled(not single)
            if detected_count > 0:
                suffix = "（单脉冲·仅关断）" if single else ""
                self.lbl_pulse_count.setText(f"{detected_count} 波{suffix}")
            else:
                self.lbl_pulse_count.setText("— 波")
        finally:
            self.spin_off_pulse.blockSignals(False)
            self.spin_on_pulse.blockSignals(False)

    def _on_test_mode_changed(self, _index: int = 0) -> None:
        data = self.combo_test_mode.currentData()
        if data is not None:
            self.cfg.test_mode.mode = str(data)
        self._apply_test_mode_ui()
        if self.bundle is not None:
            self._recalculate(reset_manual=True)

    def _apply_test_mode_ui(self) -> None:
        is_dpt = parse_test_mode(self.cfg.test_mode.mode) == TestMode.DPT
        for w in self._pulse_toolbar_widgets:
            w.setEnabled(is_dpt)
            w.setVisible(is_dpt)
        self.btn_export.setEnabled(is_dpt)
        if not is_dpt:
            self.btn_export.setToolTip("短路计算模式下暂不支持导出（功能开发中）")
        else:
            self.btn_export.setToolTip("")

    def _on_pulse_spin_changed(self, _value: int) -> None:
        if parse_test_mode(self.cfg.test_mode.mode) != TestMode.DPT:
            return
        self._on_pulse_selection_changed()

    def _on_global_cursors_moved(self, t_a_us: float, t_b_us: float) -> None:
        """Global 模式 A/B 拖动：按物理光标位置更新 statusBar（A/B 与波形上一致）。"""
        dt_us = t_b_us - t_a_us
        freq_khz = 1.0e3 / abs(dt_us) if abs(dt_us) > 1e-12 else 0.0
        freq_disp = (
            f"{freq_khz / 1000:.2f} MHz"
            if freq_khz >= 1000
            else f"{freq_khz:.2f} kHz"
        )
        self.statusBar().showMessage(
            f"光标测量: A={t_a_us:.3f} µs  B={t_b_us:.3f} µs  "
            f"Δt={dt_us:+.3f} µs  |Δt|={abs(dt_us):.3f} µs  1/|Δt|={freq_disp}"
        )

    def _on_horizontal_cursors_moved(self, ha: float, hb: float) -> None:
        if self._active_slope_param is not None:
            return
        dy = hb - ha
        self.statusBar().showMessage(
            f"横光标: Ha={ha:+.3f}  Hb={hb:+.3f}  Δy={dy:+.3f}"
        )

    def _current_profile(self) -> BridgeProfile:
        phase = self.combo_phase.currentData()
        bridge = self.combo_bridge.currentData()
        profile, custom = resolve_profile(phase, bridge, self._channel_store)
        self._mapping_custom = custom
        self._update_map_status_label()
        return profile

    def _update_map_status_label(self) -> None:
        if self._mapping_custom:
            self.lbl_map_status.setText("已自定义通道")
        else:
            self.lbl_map_status.setText("")

    def _on_pulse_selection_changed(self) -> None:
        if parse_test_mode(self.cfg.test_mode.mode) != TestMode.DPT:
            return
        off = int(self.spin_off_pulse.value())
        on = int(self.spin_on_pulse.value())
        if on < off:
            QMessageBox.warning(
                self,
                "脉冲选择无效",
                f"开通波次 ({on}) 不能早于关断波次 ({off})。",
            )
            self._set_pulse_spin_values(
                self.cfg.pulse_selection.off_pulse,
                self.cfg.pulse_selection.on_pulse,
            )
            return
        self.cfg.pulse_selection.off_pulse = off
        self.cfg.pulse_selection.on_pulse = on
        self._recalculate()

    def _on_phase_bridge_changed(self) -> None:
        self.profile = self._current_profile()
        if self.bundle:
            self._recalculate(reset_manual=True)

    def _on_waveform_channel_mapping_requested(self, source_key: str, logical_role: str) -> None:
        if self.bundle is None:
            return
        source_key = source_key.upper()
        phase = self.combo_phase.currentData()
        bridge = self.combo_bridge.currentData()
        current = ChannelMapping.from_profile(self.profile)
        parts = {key: getattr(current, key) for key in LOGICAL_SIGNAL_KEYS}
        ic_sum = bool(current.ic_from_sum_irr_il)
        irr_diff = bool(current.irr_from_ic_minus_il)

        if logical_role:
            if logical_role not in LOGICAL_SIGNAL_KEYS:
                return
            parts[logical_role] = source_key
            if logical_role == "ic":
                ic_sum = False
            if logical_role == "irr":
                irr_diff = False
        else:
            for key in LOGICAL_SIGNAL_KEYS:
                if parts.get(key) == source_key:
                    parts[key] = ""
            if parts.get("irr") == "" and ic_sum:
                ic_sum = False
            if parts.get("ic") == "" and irr_diff:
                irr_diff = False

        mapping = ChannelMapping(
            **parts,
            ic_from_sum_irr_il=ic_sum,
            irr_from_ic_minus_il=irr_diff,
        )
        errors = validate_mapping(mapping, self.bundle)
        if errors:
            QMessageBox.warning(
                self,
                "映射无效",
                "该设置会导致参数计算通道不完整或重复：\n\n"
                + "\n".join(f"- {err}" for err in errors),
            )
            return

        self._channel_store.set(phase, bridge, mapping)
        self.profile = self._current_profile()
        self._mapping_custom = True
        self._update_map_status_label()
        self._recalculate(reset_manual=True)
        role_label = logical_role or "未映射"
        self.statusBar().showMessage(f"{source_key} 已映射为 {role_label}")

    def _on_waveform_channel_label_changed(self, source_key: str, label: str) -> None:
        if self.bundle is None:
            return
        source_key = source_key.upper()
        if source_key not in self.bundle.channels:
            return
        label = label.strip()
        if label:
            self.bundle.meta.channel_labels[source_key] = label
            self.statusBar().showMessage(f"{source_key} 标签已改为 {label}")
        else:
            self.bundle.meta.channel_labels.pop(source_key, None)
            self.statusBar().showMessage(f"{source_key} 标签已清空")

    def _set_profile_combos(self, profile: BridgeProfile) -> None:
        pi = self.combo_phase.findData(profile.phase)
        if pi >= 0:
            self.combo_phase.blockSignals(True)
            self.combo_phase.setCurrentIndex(pi)
            self.combo_phase.blockSignals(False)
        bi = self.combo_bridge.findData(profile.bridge)
        if bi >= 0:
            self.combo_bridge.blockSignals(True)
            self.combo_bridge.setCurrentIndex(bi)
            self.combo_bridge.blockSignals(False)
        self.profile, self._mapping_custom = resolve_profile(
            profile.phase, profile.bridge, self._channel_store
        )
        self._update_map_status_label()

    def _open_waveform(self) -> None:
        fallback = (
            Path(self._current_path).parent if self._current_path else Path.home()
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开波形文件",
            open_dialog_start_dir(fallback),
            "TSS 会话 (*.tss);;All (*)",
        )
        if path:
            self._load_file(path, background=True)

    def _load_cfg_for_new_file(self) -> AppConfig:
        cfg = deepcopy(self.cfg)
        cfg.vdc_override = None
        cfg.slope_ranges = default_slope_ranges()
        return cfg

    def _set_load_busy(self, busy: bool, path: str = "") -> None:
        self.btn_open.setEnabled(not busy)
        self.btn_recalc.setEnabled(not busy)
        self.btn_export.setEnabled(
            (not busy) and parse_test_mode(self.cfg.test_mode.mode) == TestMode.DPT
        )
        if busy:
            self.statusBar().showMessage(f"正在后台加载: {Path(path).name}")

    def _start_background_load(self, path: str) -> None:
        self._load_request_id += 1
        request_id = self._load_request_id
        cfg = self._load_cfg_for_new_file()
        task = _WaveformLoadTask(
            request_id,
            path,
            cfg,
        )
        task.signals.finished.connect(self._on_background_load_finished)
        task.signals.failed.connect(self._on_background_load_failed)
        self._load_tasks[request_id] = task
        self._set_load_busy(True, path)
        self._load_pool.start(task)

    def _on_background_load_finished(
        self,
        request_id: int,
        outcome: _WaveformLoadOutcome,
    ) -> None:
        self._load_tasks.pop(request_id, None)
        if request_id != self._load_request_id:
            return
        try:
            self._apply_loaded_waveform(outcome)
        except Exception as exc:
            QMessageBox.critical(self, "加载失败", str(exc))
        finally:
            self._set_load_busy(False)

    def _on_background_load_failed(
        self,
        request_id: int,
        _path: str,
        message: str,
    ) -> None:
        self._load_tasks.pop(request_id, None)
        if request_id != self._load_request_id:
            return
        self._set_load_busy(False)
        QMessageBox.critical(self, "加载失败", message)

    def _clear_manual_adjustments(self, *, reset_plot: bool = True) -> None:
        self._manual_intervals.clear()
        self._manual_turn_on_current = None
        self._manual_delta_vce.clear()
        self._manual_dvdt.clear()
        self._manual_didt.clear()
        self._manual_trr_measure = None
        self._manual_waveform_source = ""
        self._active_slope_param = None
        if reset_plot:
            self.wave_plot.reset_interaction_state()

    def _loaded_status_message(
        self,
        outcome: _WaveformLoadOutcome,
        inferred: ChannelMapping | None,
    ) -> str:
        msg = (
            f"已加载: {Path(outcome.path).name}  |  "
            f"读取 {outcome.load_ms:.0f} ms  提取 {outcome.extract_ms:.0f} ms"
        )
        if outcome.mapping_custom:
            msg += "（已应用自定义通道映射）"
        if outcome.bundle.meta.channel_vdiv:
            msg += f"（已应用 TSS 垂直刻度 {len(outcome.bundle.meta.channel_vdiv)} 通道）"
        return msg

    def _apply_loaded_waveform(self, outcome: _WaveformLoadOutcome) -> None:
        path = outcome.path
        inferred = outcome.inferred
        self.bundle = outcome.bundle
        self._current_path = path

        self._set_profile_combos(outcome.guessed)
        self.profile = outcome.profile
        self._mapping_custom = outcome.mapping_custom
        self._update_map_status_label()

        self.spin_vdc.blockSignals(True)
        self.spin_vdc.setValue(0)
        self.spin_vdc.blockSignals(False)
        self.cfg.vdc_override = None
        self._slope_ranges = default_slope_ranges()
        self.result_table.set_slope_ranges(self._slope_ranges)
        self._clear_manual_adjustments()
        set_last_open_path(path)

        if outcome.short_circuit_not_ready:
            self.result = None
            self.wave_plot.plot_waveforms(self.bundle, self.profile, None)
            self.result_table.set_mode_placeholder(
                "短路计算",
                "功能开发中。当前仅显示波形，参数提取与 Excel 导出将在后续版本提供。",
            )
            self.statusBar().showMessage("短路计算：功能开发中，当前仅显示波形")
            return

        if outcome.result is None:
            raise ValueError("提取失败：后台任务未返回参数结果")
        self.result = outcome.result
        self.result_table.set_result(self.result)
        if self.result.detected_pulse_count > 0:
            self._update_pulse_toolbar(
                self.result.detected_pulse_count,
                self.result.off_pulse_index,
                self.result.on_pulse_index,
            )
        self.result_table.setMaximumWidth(self.result_table.preferred_panel_width())
        if not self._splitter_user_moved:
            self._sync_splitter_sizes()
        self.wave_plot.plot_waveforms(self.bundle, self.profile, self.result)
        self.statusBar().showMessage(self._loaded_status_message(outcome, inferred))

    def _load_file(self, path: str, *, background: bool = False) -> None:
        if background:
            self._start_background_load(path)
            return
        try:
            outcome = _compute_waveform_load_outcome(
                path,
                self._load_cfg_for_new_file(),
            )
            self._apply_loaded_waveform(outcome)
        except Exception as e:
            QMessageBox.critical(self, "加载失败", str(e))

    def _on_slope_range_changed(self, key: str, sr: SlopeRange) -> None:
        old = self._slope_ranges.get(key)
        self._slope_ranges[key] = normalize_slope_range(key, sr)
        if key == "rr_didt":
            new = self._slope_ranges[key]
            if old is None or old.ic_reference != new.ic_reference:
                self._manual_didt.pop(("反向恢复", "di/dt"), None)
            elif old.label() != new.label():
                self._manual_didt.pop(("反向恢复", "di/dt"), None)
        self.cfg.slope_ranges = dict(self._slope_ranges)
        self._recalculate()

    def _on_eoff_pre_changed(self, pre_ns: float) -> None:
        self.cfg.energy.eoff_pre_ns = float(pre_ns)
        self._recalculate()

    def _touch_manual_waveform_source(self) -> None:
        if self.bundle is not None:
            self._manual_waveform_source = self.bundle.meta.source_path

    def _manual_cursors_apply_to_current_waveform(self) -> bool:
        if self.bundle is None:
            return False
        return self.bundle.meta.source_path == self._manual_waveform_source

    def _save_manual_delta_vce(
        self,
        section: str,
        a_t: float,
        b_t: float,
        ha_v: float,
        hb_v: float,
    ) -> None:
        self._touch_manual_waveform_source()
        self._manual_delta_vce[(section, "ΔVce")] = (
            float(a_t),
            float(b_t),
            float(ha_v),
            float(hb_v),
        )

    def _on_value_clicked(self, section: str, name: str) -> None:
        if (
            self.result is not None
            and self.result.single_pulse_mode
            and section in {"开通", "反向恢复"}
        ):
            self.wave_plot.disable_interactive_cursors()
            self.statusBar().showMessage(
                f"{section}-{name}: 单脉冲模式下该参数不适用"
            )
            return
        if section == "开通" and name in {"ΔVce", "Ls_on"}:
            self._enable_turn_on_delta_vce_interaction(focus_name=name)
            return
        if section == "关断过程" and name in {"ΔVce", "Ls_off"}:
            self._enable_turn_off_delta_vce_interaction(focus_name=name)
            return
        if name == "dv/dt":
            self._enable_dvdt_interaction(section)
            return
        if name == "di/dt":
            self._enable_didt_interaction(section)
            return
        if name in {"Eoff", "Eon", "Err"}:
            self._enable_energy_interaction(section, name)
            return
        if section == "反向恢复" and name == "Irr":
            self._enable_irr_interaction()
            return
        if section == "反向恢复" and name == "Trr":
            self._enable_trr_interaction()
            return
        if section == "开通" and name == "开通电流":
            self._enable_turn_on_current_interaction()
            return
        if name == "串扰电压" and section in {"关断过程", "开通"}:
            self._enable_crosstalk_interaction(section)
            return
        self._enable_generic_parameter_interaction(section, name)

    def _dvdt_channel(self, section: str) -> str:
        return "v_diode" if section == "反向恢复" else "vce"

    # ---- 平稳区 (max+min)/2 工具：横向光标取"震荡结束后平台有效值" ----
    def _window_mid(self, arr: np.ndarray, t_lo_us: float, t_hi_us: float) -> float | None:
        """[t_lo,t_hi]µs 窗内波形 (max+min)/2（带符号，贴真实波形）。"""
        if self.bundle is None:
            return None
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(t_lo_us, t_hi_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t_lo_us, t_hi_us) * 1e-6, side="right"))
        i0 = max(0, min(i0, len(arr) - 1))
        i1 = max(i0 + 1, min(i1, len(arr)))
        seg = np.asarray(arr[i0:i1], dtype=np.float64)
        if len(seg) < 2:
            return None
        return 0.5 * (float(np.max(seg)) + float(np.min(seg)))

    def _turn_off_rise_us(self) -> float | None:
        """关断 Vce 主抬升脚时刻（µs）：段内 Vce<=on_hi 的最大 dV/dt 点。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        t = self.bundle.t
        vce = self.bundle.get(self.profile.vce)
        off0, off1 = self.result.segments.turn_off
        seg = vce[off0 : off1 + 1].astype(np.float64)
        if len(seg) < 4:
            return None
        v_base = float(np.percentile(seg[: max(4, len(seg) // 5)], 50))
        v_top = float(np.max(seg))
        on_hi = v_base + max(30.0, 0.04 * max(v_top - v_base, 1.0))
        d = np.diff(seg) / np.maximum(np.diff(t[off0 : off1 + 1]), 1e-15)
        best_k, best = 0, -1.0
        for k in range(len(d)):
            if seg[k] > on_hi:
                continue
            if d[k] > best:
                best, best_k = d[k], k
        return float(t[off0 + best_k]) * 1e6

    def _recovery_peak_us(self) -> float | None:
        """反向恢复主峰 (IRM) 时刻（µs，定向后取 argmax）。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.metrics.iec_windows import err_recovery_peak_index
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        irr = bundle_reverse_recovery_current(self.bundle, self.profile)
        rr0, rr1 = self.result.segments.reverse_recovery
        ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], self.bundle.dt)
        return float(self.bundle.t[ipk]) * 1e6

    def _default_dvdt_on_vce_base_top(
        self, t0_us: float, t1_us: float
    ) -> tuple[float, float] | None:
        """开通 Vce dv/dt：Hb=回落后平均值，Ha=跌前高平台。"""
        if self.bundle is None or self.result is None:
            return None
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        from dpt_extractor.metrics.plateau_level import dvdt_on_vce_fall_base_top

        vce = self.bundle.get(self.profile.vce)
        seg = vce[i0 : i1 + 1]
        if len(seg) < 8:
            return None
        return dvdt_on_vce_fall_base_top(seg, self.bundle.dt)

    def _default_rr_dvdt_base_top_v(self) -> tuple[float, float] | None:
        """反向恢复 dv/dt：Hb=0，Ha=Vrr 后二极管电压震荡结束平台。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.metrics.plateau_level import dvdt_rr_vd_base_top

        t = self.bundle.t
        vd = self.bundle.get(self.profile.v_diode)
        on0, on1 = self.result.segments.turn_on
        on0 = max(0, min(on0, len(t) - 2))
        on1 = max(on0 + 1, min(on1, len(t) - 1))
        vd_abs = np.abs(vd[on0 : on1 + 1])
        if len(vd_abs) < 4:
            return None
        ipk = on0 + int(np.argmax(vd_abs))
        search_end = min(len(t) - 1, int(np.searchsorted(t, float(t[ipk]) + 1.35e-6)))
        search_end = max(ipk + 2, search_end)
        return dvdt_rr_vd_base_top(t, vd, ipk, self.bundle.dt, search_end)

    def _default_dvdt_base_top_v(
        self, section: str, t0_us: float, t1_us: float
    ) -> tuple[float, float] | None:
        """关断上升沿 dv/dt 一次算 Ha/Hb，避免重复扫描波形。"""
        if section == "开通":
            return self._default_dvdt_on_vce_base_top(t0_us, t1_us)
        if section == "反向恢复":
            return self._default_rr_dvdt_base_top_v()
        if self.bundle is None or self.result is None or section != "关断过程":
            return None
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        from dpt_extractor.metrics.plateau_level import dvdt_rise_base_top_mid

        vce = self.bundle.get(self.profile.vce)
        seg = vce[i0 : i1 + 1]
        if len(seg) < 8:
            off = self.result.turn_off
            top = float(max(0.0, off.vce_off_max - off.delta_vce))
            base = float(np.min(seg)) if len(seg) else top * 0.05
            return base, top
        base, top = dvdt_rise_base_top_mid(seg)
        # Hb(Base)=导通态 Vce 平台 (max+min)/2（抬升脚前窗，贴真实波形）
        rise_us = self._turn_off_rise_us()
        if rise_us is not None:
            hb = self._window_mid(vce, rise_us - 0.5, rise_us - 0.1)
            if hb is not None:
                base = float(hb)
        return base, top

    def _default_dvdt_top_v(self, section: str, t0_us: float, t1_us: float) -> float:
        if self.bundle is None or self.result is None:
            return 0.0
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        if section == "关断过程":
            pair = self._default_dvdt_base_top_v(section, t0_us, t1_us)
            if pair is not None:
                return pair[1]
            return 0.0
        if section == "开通":
            pair = self._default_dvdt_on_vce_base_top(t0_us, t1_us)
            if pair is not None:
                return pair[1]
            vce = self.bundle.get(self.profile.vce)
            vdc = self.result.vdc_set if self.result.vdc_set is not None else self.result.vdc
            seg = vce[i0 : i1 + 1]
            return float(np.percentile(seg, 95)) if len(seg) else float(vdc)
        if section == "反向恢复":
            pair = self._default_rr_dvdt_base_top_v()
            if pair is not None:
                return pair[1]
        v_diode = self.bundle.get(self.profile.v_diode)
        seg = np.abs(v_diode[i0 : i1 + 1])
        return float(np.max(seg)) if len(seg) else 0.0

    def _default_dvdt_base_v(self, section: str, t0_us: float, t1_us: float) -> float:
        if self.bundle is None or self.result is None:
            return 0.0
        vdc = float(
            self.result.vdc_set if self.result.vdc_set is not None else self.result.vdc
        )
        if section == "反向恢复":
            return 0.0
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        vce = self.bundle.get(self.profile.vce)
        seg = vce[i0 : i1 + 1]
        if len(seg) == 0:
            return vdc if section == "关断过程" else vdc
        if section == "关断过程":
            # Hb=导通态 Vce 平台 (max+min)/2（抬升脚前 ~100–500ns 窗，贴真实波形）
            rise_us = self._turn_off_rise_us()
            if rise_us is not None:
                hb = self._window_mid(vce, rise_us - 0.5, rise_us - 0.1)
                if hb is not None:
                    return float(hb)
            pair = self._default_dvdt_base_top_v(section, t0_us, t1_us)
            if pair is not None:
                return pair[0]
            return float(np.min(seg)) if len(seg) else vdc
        if section == "开通":
            pair = self._default_dvdt_on_vce_base_top(t0_us, t1_us)
            if pair is not None:
                return pair[0]
        return float(np.min(seg)) if len(seg) else vdc

    def _dvdt_edge(self, section: str) -> str:
        return "rise" if section in ("关断过程", "反向恢复") else "fall"

    def _compute_dvdt_base_top(
        self,
        section: str,
        search_t0_us: float,
        search_t1_us: float,
        top_v: float,
        base_v: float,
    ) -> DvdtCrossingResult:
        if self.bundle is None or self.result is None:
            return DvdtCrossingResult(0.0, None, None, 0.0, 0.0)
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(search_t0_us, search_t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(search_t0_us, search_t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 2))
        i1 = max(i0 + 2, min(i1, len(t) - 1))
        row_key = SLOPE_ROW_KEYS.get((section, "dv/dt"))
        sr = self._slope_ranges.get(row_key) if row_key else None
        pct_a, pct_b = sr.as_fractions() if sr else (0.1, 0.9)
        edge = self._dvdt_edge(section)
        use_abs = section == "反向恢复"
        if section == "反向恢复":
            y = self.bundle.get(self.profile.v_diode)
        else:
            y = self.bundle.get(self.profile.vce)
        return dvdt_between_base_top(
            t,
            y,
            i0,
            i1,
            float(base_v),
            float(top_v),
            pct_a,
            pct_b,
            edge,
            use_abs=use_abs,
        )

    def _apply_dvdt_result(
        self,
        section: str,
        res: DvdtCrossingResult,
        top_v: float,
        base_v: float,
        search_t0_us: float,
        search_t1_us: float,
    ) -> None:
        if self.result is None:
            return
        val = float(res.dvdt)
        row_key = SLOPE_ROW_KEYS.get((section, "dv/dt"))
        sr = self._slope_ranges.get(row_key) if row_key else None
        range_disp = (
            f"{sr.label()}·Top={top_v:.2f}V·Base={base_v:.2f}V"
            if sr
            else f"Top={top_v:.2f}V·Base={base_v:.2f}V"
        )
        if section == "关断过程":
            self.result.turn_off.dvdt = val
            self.result.turn_off.dvdt_range = range_disp
            self.result_table.set_metric_value("关断过程", "dv/dt", val)
        elif section == "开通":
            self.result.turn_on.dvdt = val
            self.result.turn_on.dvdt_range = range_disp
            self.result_table.set_metric_value("开通", "dv/dt", val)
        else:
            self.result.reverse_recovery.dvdt_max = val
            self.result.reverse_recovery.dvdt_range = range_disp
            self.result_table.set_metric_value("反向恢复", "dv/dt", val)
        ta_us = res.t_pct_a_s * 1e6 if res.t_pct_a_s is not None else None
        tb_us = res.t_pct_b_s * 1e6 if res.t_pct_b_s is not None else None
        ab_msg = (
            f"A={ta_us:.3f}µs B={tb_us:.3f}µs"
            if ta_us is not None and tb_us is not None
            else "A/B 未找到穿越"
        )
        self.statusBar().showMessage(
            f"{section}-dv/dt: Ha(Top)={top_v:.2f}V Hb(Base)={base_v:.2f}V, "
            f"段窗[{min(search_t0_us, search_t1_us):.3f},"
            f"{max(search_t0_us, search_t1_us):.3f}]µs, "
            f"{sr.label() if sr else ''}, {ab_msg}, 值={val:.3f} V/ns"
        )

    def _enable_dvdt_interaction(self, section: str) -> None:
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        interval = self._parameter_interval_us(section, "dv/dt")
        if interval is None:
            return
        key = (section, "dv/dt")
        self._active_slope_param = key
        search_t0, search_t1 = interval
        restored = self._manual_dvdt.get(key)
        if restored is not None:
            search_t0, search_t1, top_v, base_v = restored
        elif section in ("关断过程", "反向恢复"):
            pair = self._default_dvdt_base_top_v(section, search_t0, search_t1)
            if pair is not None:
                base_v, top_v = pair
            else:
                top_v = self._default_dvdt_top_v(section, search_t0, search_t1)
                base_v = self._default_dvdt_base_v(section, search_t0, search_t1)
        else:
            top_v = self._default_dvdt_top_v(section, search_t0, search_t1)
            base_v = self._default_dvdt_base_v(section, search_t0, search_t1)
        channel = self._dvdt_channel(section)

        def _on_dvdt_voltages_changed(top_v_live: float, base_v_live: float) -> None:
            t0 = min(search_t0, search_t1)
            t1 = max(search_t0, search_t1)
            self._touch_manual_waveform_source()
            self._manual_dvdt[key] = (t0, t1, float(top_v_live), float(base_v_live))
            res = self._compute_dvdt_base_top(
                section, t0, t1, top_v_live, base_v_live
            )
            if res.t_pct_a_s is not None and res.t_pct_b_s is not None:
                ta_us = res.t_pct_a_s * 1e6
                tb_us = res.t_pct_b_s * 1e6
                self.wave_plot.apply_dvdt_ab_times(ta_us, tb_us)
                pad = max(0.08, abs(ta_us - tb_us) * 4.0)
                self.wave_plot.focus_interval_us(
                    min(ta_us, tb_us) - pad, max(ta_us, tb_us) + pad
                )
            self._apply_dvdt_result(section, res, top_v_live, base_v_live, t0, t1)

        self.wave_plot.enable_dvdt_interaction(
            search_t0,
            search_t1,
            top_v,
            base_v,
            channel,
            _on_dvdt_voltages_changed,
            mode="dvdt",
        )
        res0 = self._compute_dvdt_base_top(section, search_t0, search_t1, top_v, base_v)
        if res0.t_pct_a_s is not None and res0.t_pct_b_s is not None:
            ta_us = res0.t_pct_a_s * 1e6
            tb_us = res0.t_pct_b_s * 1e6
            self.wave_plot.apply_dvdt_ab_times(ta_us, tb_us)
            pad = max(0.08, abs(ta_us - tb_us) * 4.0)
            self.wave_plot.focus_interval_us(
                min(ta_us, tb_us) - pad, max(ta_us, tb_us) + pad
            )
        else:
            self.wave_plot.focus_interval_us(min(search_t0, search_t1), max(search_t0, search_t1))
        if restored is not None:
            self._apply_dvdt_result(section, res0, top_v, base_v, search_t0, search_t1)
        else:
            self._show_stored_metric_status(section, "dv/dt")

    def _didt_channel(self, section: str) -> str:
        return "irr" if section == "反向恢复" else "ic"

    def _rr_didt_mode_tag(self, section: str) -> str:
        if section != "反向恢复":
            return "generic"
        row_key = SLOPE_ROW_KEYS.get((section, "di/dt"))
        sr = self._slope_ranges.get(row_key) if row_key else None
        if sr and sr.ic_reference == "if_irm":
            return "if_irm"
        if section == "反向恢复":
            return "idm"
        return "generic"

    def _restore_manual_didt(
        self, key: tuple[str, str], mode_tag: str
    ) -> tuple[float, float, float, float, float | None] | None:
        """恢复手调 di/dt 光标；算法模式不一致则丢弃（避免 if_irm 污染 idm）。"""
        restored = self._manual_didt.get(key)
        if restored is None:
            return None
        saved_tag = (
            str(restored[-1])
            if len(restored) >= 5
            and str(restored[-1]) in {"generic", "idm", "if_irm"}
            else ""
        )
        if saved_tag and saved_tag != mode_tag:
            return None
        if len(restored) >= 6:
            t0, t1, top_a, base_a = restored[:4]
            zero_a = restored[4] if mode_tag == "if_irm" else None
            return t0, t1, top_a, base_a, zero_a
        if len(restored) >= 5 and mode_tag == "if_irm":
            return None
        if len(restored) >= 4:
            if mode_tag == "if_irm":
                return None
            t0, t1, top_a, base_a = restored[:4]
            return t0, t1, top_a, base_a, None
        return None

    def _saved_didt_slope_state(
        self, section: str
    ) -> tuple[float, float, float | None] | None:
        """再次点击 di/dt 时优先用波形上当前 Ha/Hb。"""
        channel = self._didt_channel(section)
        live = self.wave_plot.read_didt_slope_state(channel)
        if live is not None:
            return live
        key = (section, "di/dt")
        mode_tag = self._rr_didt_mode_tag(section)
        manual = self._restore_manual_didt(key, mode_tag)
        if manual is None:
            return None
        _t0, _t1, top_a, base_a, zero_a = manual
        return top_a, base_a, zero_a

    def _save_manual_didt(
        self,
        key: tuple[str, str],
        mode_tag: str,
        t0: float,
        t1: float,
        top_a: float,
        base_a: float,
        zero_a: float | None = None,
    ) -> None:
        self._touch_manual_waveform_source()
        if mode_tag == "if_irm":
            self._manual_didt[key] = (
                float(t0),
                float(t1),
                float(top_a),
                float(base_a),
                float(zero_a if zero_a is not None else 0.0),
                mode_tag,
            )
        else:
            self._manual_didt[key] = (
                float(t0),
                float(t1),
                float(top_a),
                float(base_a),
                mode_tag,
            )

    def _rr_didt_use_zero_ref(self, section: str) -> bool:
        return self._rr_didt_mode_tag(section) == "if_irm"

    @staticmethod
    def _rr_irm_plateau_level(
        seg: np.ndarray, ipk_irm: int, ipk_if: int,
    ) -> float:
        """IRM 负向平台中线（略高于单点谷底，贴合示波器底部绿线）。"""
        seg = np.asarray(seg, dtype=np.float64)
        if ipk_irm >= ipk_if:
            return float(np.min(seg))
        span = max(8, ipk_if - ipk_irm)
        pl_w = max(12, int(0.35 * span))
        lo = max(0, ipk_irm - pl_w // 6)
        hi = min(len(seg), ipk_irm + pl_w)
        plateau = seg[lo:hi]
        if len(plateau) < 3:
            return float(seg[ipk_irm])
        thr = float(np.percentile(plateau, 10))
        low = plateau[plateau <= thr]
        if len(low) >= 3:
            return float(np.median(low))
        return float(np.percentile(plateau, 10))

    def _default_rr_didt_ha_hb(self, seg: np.ndarray, mode_tag: str) -> tuple[float, float]:
        """
        反向恢复 di/dt 默认 Ha/Hb 电平（物理电流 A）。
        idm：顺相 Ha=0·Hb=IDM；反相通道 Ha=IRM 底部平台、Hb=换流后正平台。
        if_irm：Ha=IF 尖峰、Hb=IRM 底部平台中线。
        """
        seg = np.asarray(seg, dtype=np.float64)
        if len(seg) < 8:
            return 0.0, 0.0
        ipk_if = int(np.argmax(seg))
        ipk_irm = int(np.argmin(seg))
        if mode_tag == "if_irm":
            w = max(4, int(0.015 * len(seg)))
            lo = max(0, ipk_if - w)
            hi = min(len(seg), ipk_if + w + 1)
            ha = float(np.max(seg[lo:hi]))
            hb = self._rr_irm_plateau_level(seg, ipk_irm, ipk_if)
            return ha, hb
        if ipk_irm < ipk_if:
            ha = self._rr_irm_plateau_level(seg, ipk_irm, ipk_if)
            tail0 = ipk_if + max(8, int(0.30 * (len(seg) - ipk_if)))
            tail = seg[tail0:]
            if len(tail) < 8:
                tail = seg[ipk_if :]
            hb = float(np.percentile(tail, 50))
            return ha, hb
        idm, _, _ = analyze_rr_recovery_current(seg)
        return 0.0, float(idm)

    def _default_didt_zero_a(self, section: str, t0_us: float, t1_us: float) -> float:
        if self.bundle is None or section != "反向恢复":
            return 0.0
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        irr = bundle_reverse_recovery_current(self.bundle, self.profile)
        seg = irr[i0 : i1 + 1]
        if len(seg) == 0:
            return 0.0
        ipk_if = int(np.argmax(seg))
        # IF 峰后振铃平息段中位数：作 50%IF→50%IRM 的 H0 零基准（贴近示波器 0 值中线）
        tail = seg[ipk_if + 1 :]
        if len(tail) < 8:
            tail = seg[max(0, ipk_if - 4) :]
        skip = max(8, int(0.10 * len(tail)))
        rest = tail[skip:] if len(tail) > skip + 8 else tail
        n = max(8, int(0.22 * len(rest)))
        settled = rest[-n:] if len(rest) >= n else rest
        if len(settled) == 0:
            return 0.0
        return float(np.median(settled))

    def _default_didt_top_a(self, section: str, t0_us: float, t1_us: float) -> float:
        if self.bundle is None or self.result is None:
            return 0.0
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        if section == "关断过程":
            return float(self.result.turn_off.ic_off_max)
        if section == "开通":
            from dpt_extractor.metrics.plateau_level import turn_on_didt_ha_at_turn_on
            from dpt_extractor.models.waveform import bundle_total_current

            ic = bundle_total_current(self.bundle, self.profile)
            segs = self.result.segments
            if segs is not None:
                on0, on1 = segs.turn_on
                return float(turn_on_didt_ha_at_turn_on(t, ic, on0, on1, self.bundle.dt))
            return float(np.max(np.abs(ic[i0 : i1 + 1]))) if i1 > i0 else 0.0
        if section == "反向恢复":
            from dpt_extractor.models.waveform import bundle_reverse_recovery_current

            irr = bundle_reverse_recovery_current(self.bundle, self.profile)
            # Ha=恢复前正向导通电流平台 (max+min)/2（主峰前 ~200–600ns 窗，贴真实波形）
            pk_us = self._recovery_peak_us()
            if pk_us is not None:
                ha_w = self._window_mid(irr, pk_us - 0.6, pk_us - 0.2)
                if ha_w is not None:
                    return float(ha_w)
            seg = irr[i0 : i1 + 1]
            if len(seg) == 0:
                return 0.0
            mode = self._rr_didt_mode_tag(section)
            ha, _hb = self._default_rr_didt_ha_hb(seg, mode)
            return ha
        return 0.0

    def _default_didt_base_a(self, section: str, t0_us: float, t1_us: float) -> float:
        if self.bundle is None or self.result is None:
            return 0.0
        if section == "反向恢复":
            t = self.bundle.t
            i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
            i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
            i0 = max(0, min(i0, len(t) - 1))
            i1 = max(i0 + 1, min(i1, len(t) - 1))
            from dpt_extractor.models.waveform import bundle_reverse_recovery_current

            irr = bundle_reverse_recovery_current(self.bundle, self.profile)
            seg = irr[i0 : i1 + 1]
            if len(seg) == 0:
                return 0.0
            mode = self._rr_didt_mode_tag(section)
            _ha, hb = self._default_rr_didt_ha_hb(seg, mode)
            return hb
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        from dpt_extractor.models.waveform import bundle_total_current
        from dpt_extractor.metrics.plateau_level import didt_fall_top_base_mid

        ic = bundle_total_current(self.bundle, self.profile)
        if section == "开通" and (i1 - i0) >= 8:
            from dpt_extractor.metrics.plateau_level import (
                turn_on_current_baseline_and_plateau,
            )

            # 带符号：下桥导通前基线为负，di/dt 基线光标须贴真实波形
            seg_signed = ic[i0 : i1 + 1].astype(np.float64)
            hb, _ha = turn_on_current_baseline_and_plateau(seg_signed, self.bundle.dt)
            return float(hb)
        # 带符号：下桥关断后回落平台为负，Hb 须取回落后平稳区 (max+min)/2 贴真实波形
        seg = ic[i0 : i1 + 1].astype(np.float64)
        if section == "关断过程" and len(seg) >= 8:
            _top, base = didt_fall_top_base_mid(seg)
            return base
        return float(np.min(np.abs(seg))) if len(seg) else 0.0

    def _compute_didt_base_top(
        self,
        section: str,
        search_t0_us: float,
        search_t1_us: float,
        top_a: float,
        base_a: float,
        zero_a: float | None = None,
    ) -> DidtCrossingResult:
        if self.bundle is None or self.result is None:
            return DidtCrossingResult(0.0, None, None, 0.0, 0.0)
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(search_t0_us, search_t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(search_t0_us, search_t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 2))
        i1 = max(i0 + 2, min(i1, len(t) - 1))
        row_key = SLOPE_ROW_KEYS.get((section, "di/dt"))
        sr = self._slope_ranges.get(row_key) if row_key else None
        pct_a, pct_b = sr.as_fractions() if sr else (0.9, 0.1)
        edge = sr.ic_direction if sr else ("fall" if pct_a > pct_b else "rise")
        if section == "反向恢复":
            from dpt_extractor.models.waveform import bundle_reverse_recovery_current

            y = bundle_reverse_recovery_current(self.bundle, self.profile)
            measure = "idm"
            if sr and sr.ic_reference == "if_irm":
                measure = "if_irm"
            elif sr and sr.ic_reference == "idm":
                measure = "idm"
            return didt_rr_recovery(
                t,
                y,
                i0,
                i1,
                pct_a,
                pct_b,
                measure=measure,
                ha_override=float(top_a),
                hb_override=float(base_a),
                zero_override=None if zero_a is None else float(zero_a),
            )
        from dpt_extractor.models.waveform import bundle_total_current

        y = bundle_total_current(self.bundle, self.profile)
        return didt_between_base_top(
            t, y, i0, i1, float(base_a), float(top_a), pct_a, pct_b, edge
        )

    def _apply_didt_result(
        self,
        section: str,
        res: DidtCrossingResult,
        top_a: float,
        base_a: float,
        search_t0_us: float,
        search_t1_us: float,
        zero_a: float | None = None,
    ) -> None:
        if self.result is None:
            return
        val = float(res.didt)
        row_key = SLOPE_ROW_KEYS.get((section, "di/dt"))
        sr = self._slope_ranges.get(row_key) if row_key else None
        unit = "A"
        if section == "反向恢复" and res.idm is not None:
            irm = res.irm if res.irm is not None else 0.0
            is_if_irm = sr and sr.ic_reference == "if_irm"
            if is_if_irm and zero_a is not None:
                range_disp = (
                    f"{sr.label() if sr else ''}·H0={zero_a:.2f}{unit}"
                    f"·Ha={top_a:.2f}{unit}·Hb={base_a:.2f}{unit}"
                    if sr
                    else f"H0={zero_a:.2f}{unit}·Ha={top_a:.2f}{unit}·Hb={base_a:.2f}{unit}"
                )
            else:
                range_disp = (
                    f"{sr.label() if sr else ''}·Ha={top_a:.2f}{unit}·Hb={base_a:.2f}{unit}"
                    if sr
                    else f"Ha={top_a:.2f}{unit}·Hb={base_a:.2f}{unit}"
                )
        else:
            range_disp = (
                f"{sr.label()}·Top={top_a:.2f}{unit}·Base={base_a:.2f}{unit}"
                if sr
                else f"Top={top_a:.2f}{unit}·Base={base_a:.2f}{unit}"
            )
        if section == "关断过程":
            self.result.turn_off.didt = val
            self.result.turn_off.didt_range = range_disp
            self.result_table.set_metric_value("关断过程", "di/dt", val)
            self._sync_ls_off()
        elif section == "开通":
            self.result.turn_on.didt = val
            self.result.turn_on.didt_range = range_disp
            self.result_table.set_metric_value("开通", "di/dt", val)
            self._sync_ls_on()
        else:
            self.result.reverse_recovery.didt_irr = val
            self.result.reverse_recovery.didt_range = range_disp
            self.result_table.set_metric_value("反向恢复", "di/dt", val)
        ta_us = res.t_pct_a_s * 1e6 if res.t_pct_a_s is not None else None
        tb_us = res.t_pct_b_s * 1e6 if res.t_pct_b_s is not None else None
        if section == "反向恢复" and ta_us is not None and tb_us is not None:
            t_left = min(ta_us, tb_us)
            t_right = max(ta_us, tb_us)
            is_if_irm = sr and sr.ic_reference == "if_irm"
            if is_if_irm:
                ab_msg = (
                    f"50%IF={ta_us:.3f}µs 50%IRM={tb_us:.3f}µs "
                    f"thIF={res.th_a:.2f}A thIRM={res.th_b:.2f}A"
                )
            else:
                ab_msg = (
                    f"A={t_left:.3f}µs B={t_right:.3f}µs "
                    f"thA={res.th_a:.2f}A thB={res.th_b:.2f}A"
                )
        else:
            ab_msg = (
                f"A={ta_us:.3f}µs B={tb_us:.3f}µs"
                if ta_us is not None and tb_us is not None
                else "A/B 未找到穿越"
            )
        if section == "反向恢复":
            irm = res.irm if res.irm is not None else 0.0
            idm = res.idm if res.idm is not None else 0.0
            mode = sr.label() if sr else ""
            zero_msg = f" H0={zero_a:.2f}A" if zero_a is not None else ""
            id_vals = (
                f"IF={idm:.2f}A IRM={irm:.2f}A"
                if is_if_irm
                else f"IDM={idm:.2f}A IRM={irm:.2f}A"
            )
            self.statusBar().showMessage(
                f"{section}-di/dt: Ha={top_a:.2f}A Hb={base_a:.2f}A{zero_msg} "
                f"(识别 {id_vals}), "
                f"段窗[{min(search_t0_us, search_t1_us):.3f},"
                f"{max(search_t0_us, search_t1_us):.3f}]µs, "
                f"{mode}, {ab_msg}, 值={val:.3f} A/ns"
            )
        else:
            self.statusBar().showMessage(
                f"{section}-di/dt: Ha(Top)={top_a:.2f}A Hb(Base)={base_a:.2f}A, "
                f"段窗[{min(search_t0_us, search_t1_us):.3f},"
                f"{max(search_t0_us, search_t1_us):.3f}]µs, "
                f"{sr.label() if sr else ''}, {ab_msg}, 值={val:.3f} A/ns"
            )

    def _enable_didt_interaction(self, section: str) -> None:
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        interval = self._parameter_interval_us(section, "di/dt")
        if interval is None:
            return
        key = (section, "di/dt")
        self._active_slope_param = key
        search_t0, search_t1 = interval
        mode_tag = self._rr_didt_mode_tag(section)
        use_zero = mode_tag == "if_irm"
        auto_top = self._default_didt_top_a(section, search_t0, search_t1)
        auto_base = self._default_didt_base_a(section, search_t0, search_t1)
        auto_zero = self._default_didt_zero_a(section, search_t0, search_t1) if use_zero else None
        manual = self._restore_manual_didt(key, mode_tag)
        saved_levels = self._saved_didt_slope_state(section)
        if manual is not None:
            search_t0, search_t1, top_a, base_a, zero_a = manual
        else:
            top_a, base_a = auto_top, auto_base
            zero_a = auto_zero
        if saved_levels is not None:
            top_a, base_a, z = saved_levels
            if use_zero and z is not None:
                zero_a = z
            elif not use_zero:
                zero_a = None
        channel = self._didt_channel(section)

        def _on_didt_currents_changed(
            top_a_live: float, base_a_live: float, zero_a_live: float | None = None
        ) -> None:
            t0 = min(search_t0, search_t1)
            t1 = max(search_t0, search_t1)
            zero_live = zero_a_live if use_zero else None
            self._save_manual_didt(
                key,
                mode_tag,
                t0,
                t1,
                top_a_live,
                base_a_live,
                zero_live,
            )
            res = self._compute_didt_base_top(
                section, t0, t1, top_a_live, base_a_live, zero_live
            )
            if res.t_pct_a_s is not None and res.t_pct_b_s is not None:
                ta_us = res.t_pct_a_s * 1e6
                tb_us = res.t_pct_b_s * 1e6
                self.wave_plot.apply_dvdt_ab_times(ta_us, tb_us)
                pad = max(0.08, abs(ta_us - tb_us) * 4.0)
                t_lo = min(ta_us, tb_us) - pad
                t_hi = max(ta_us, tb_us) + pad
                self.wave_plot.focus_interval_us(t_lo, t_hi)
            self._apply_didt_result(
                section, res, top_a_live, base_a_live, t0, t1, zero_live
            )

        self.wave_plot.focus_interval_us(min(search_t0, search_t1), max(search_t0, search_t1))
        self.wave_plot.enable_dvdt_interaction(
            search_t0,
            search_t1,
            top_a,
            base_a,
            channel,
            _on_didt_currents_changed,
            mode="didt",
            zero_v=zero_a if use_zero else None,
        )
        res0 = self._compute_didt_base_top(
            section,
            search_t0,
            search_t1,
            top_a,
            base_a,
            zero_a if use_zero else None,
        )
        if res0.t_pct_a_s is not None and res0.t_pct_b_s is not None:
            ta_us = res0.t_pct_a_s * 1e6
            tb_us = res0.t_pct_b_s * 1e6
            self.wave_plot.apply_dvdt_ab_times(ta_us, tb_us)
            pad = max(0.08, abs(ta_us - tb_us) * 4.0)
            self.wave_plot.focus_interval_us(
                min(ta_us, tb_us) - pad, max(ta_us, tb_us) + pad
            )
        else:
            self.wave_plot.focus_interval_us(min(search_t0, search_t1), max(search_t0, search_t1))
        if manual is not None:
            self._apply_didt_result(
                section,
                res0,
                top_a,
                base_a,
                search_t0,
                search_t1,
                zero_a if use_zero else None,
            )
        else:
            self._show_stored_metric_status(section, "di/dt")

    def _enable_turn_on_delta_vce_interaction(self, *, focus_name: str = "ΔVce") -> None:
        self._active_slope_param = None
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        t = self.bundle.t
        dt = self.bundle.dt
        segs = self.result.segments
        i0, i1 = segs.turn_on
        i0 = max(0, min(i0, len(t) - 2))
        i1 = max(i0 + 2, min(i1, len(t) - 1))

        from dpt_extractor.models.waveform import bundle_total_current

        ic = bundle_total_current(self.bundle, self.profile)
        vce = self.bundle.get(self.profile.vce)
        abs_ic = np.abs(ic)

        # 与 Top 口径一致：以“电流近零开始抬升”时刻左侧 200ns 定义 Vce Top
        pre0 = max(0, i0 - int(300e-9 / dt))
        pre1 = max(pre0 + 5, i0)
        ic_base = float(np.percentile(abs_ic[pre0:pre1], 50)) if pre1 > pre0 else 0.0
        look1 = min(len(ic) - 1, i0 + int(600e-9 / dt))
        ic_ref = float(np.percentile(abs_ic[i0:look1], 95)) if look1 > i0 + 5 else float(np.max(abs_ic))
        rise_th = ic_base + max(0.02 * max(ic_ref, 1.0), 3.0)
        rise_idx = i0
        for k in range(i0, i1):
            if abs_ic[k] >= rise_th:
                rise_idx = k
                break
        w1 = max(1, rise_idx)
        w0 = max(0, w1 - int(200e-9 / dt))
        if w1 <= w0 + 5:
            w0 = max(0, i0 - int(200e-9 / dt))
            w1 = max(w0 + 6, i0)
        v_top = float(np.percentile(vce[w0:w1], 95)) if w1 > w0 else float(np.percentile(vce[max(0, i0 - 20):max(i0, 1)], 95))
        top_seg = vce[w0:w1] if w1 > w0 else vce[i0:i1]
        if len(top_seg) == 0:
            return
        top_local = int(np.argmin(np.abs(top_seg - v_top)))
        top_idx = (w0 + top_local) if w1 > w0 else (i0 + top_local)
        top_t_us = float(t[top_idx] * 1e6)

        # Hb 初始位置：与提取层一致；三斜率取中间段中点，两斜率取主下降起点拐点。
        knee = _turn_on_delta_vce_knee_point(vce, i0, i1, dt, v_top)
        if knee is not None:
            move_idx, move_v = knee
        else:
            target_v = float(max(0.0, v_top - self.result.turn_on.delta_vce))
            cand = np.arange(i0, i1 + 1)
            if len(cand) == 0:
                return
            cand_right = cand[cand >= top_idx]
            if len(cand_right) == 0:
                cand_right = cand
            move_idx = int(cand_right[np.argmin(np.abs(vce[cand_right] - target_v))])
            move_v = float(vce[move_idx])
        move_t_us = float(t[move_idx] * 1e6)

        self.wave_plot.focus_interval_us(float(t[i0] * 1e6), float(t[i1] * 1e6))

        def _on_cursor_change(_fx_t: float, _fx_v: float, _mv_t: float, _mv_v: float, delta: float) -> None:
            # delta 已是两光标电压差绝对值（A、B 对称）
            self._save_manual_delta_vce("开通", _fx_t, _mv_t, _fx_v, _mv_v)
            if self.result is not None:
                self.result.turn_on.delta_vce = float(delta)
            self.result_table.set_metric_value("开通", "ΔVce", delta)
            # 开通 ΔVce 变化 → Ls_on = 开通 ΔVce / (开通 di/dt) 实时重算
            self._sync_ls_on()
            if self.result is not None and focus_name == "Ls_on":
                on = self.result.turn_on
                self.statusBar().showMessage(
                    f"开通Ls_on: Ha={_fx_v:.2f} V, Hb={_mv_v:.2f} V, "
                    f"ΔVce={delta:.3f} V, di/dt={on.didt:.3f} A/ns, Ls_on={on.ls_on:.3f} nH"
                )
            else:
                self.statusBar().showMessage(
                    f"开通ΔVce交互: A={_fx_v:.2f} V, B={_mv_v:.2f} V, ΔVce={delta:.3f} V"
                )

        key = ("开通", "ΔVce")
        restored = (
            self._manual_delta_vce.get(key)
            if self._manual_cursors_apply_to_current_waveform()
            else None
        )
        if restored is not None:
            a_t, b_t, ha_v, hb_v = restored
            self.wave_plot.focus_interval_us(float(t[i0] * 1e6), float(t[i1] * 1e6))
            self.wave_plot.enable_delta_vce_interaction(
                fixed_t_us=a_t,
                fixed_v=ha_v,
                move_t_us=b_t,
                move_v=hb_v,
                on_change=_on_cursor_change,
                search_t0_us=float(t[i0] * 1e6),
                search_t1_us=float(t[i1] * 1e6),
            )
            return

        self.wave_plot.enable_delta_vce_interaction(
            fixed_t_us=top_t_us,
            fixed_v=v_top,
            move_t_us=move_t_us,
            move_v=move_v,
            on_change=_on_cursor_change,
            search_t0_us=float(t[i0] * 1e6),
            search_t1_us=float(t[i1] * 1e6),
        )
        self._show_stored_metric_status("开通", focus_name if focus_name == "Ls_on" else "ΔVce")

    def _enable_turn_off_delta_vce_interaction(self, *, focus_name: str = "ΔVce") -> None:
        self._active_slope_param = None
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        t = self.bundle.t
        vce = self.bundle.get(self.profile.vce)
        segs = self.result.segments
        off0, off1 = segs.turn_off
        off0 = max(0, min(off0, len(t) - 2))
        off1 = max(off0 + 2, min(off1, len(t) - 1))

        # Hb(Top)=母线电压（关断后阻断平台），与管线 ΔVce 参考一致（vce_off_max - ΔVce = Vdc）。
        # 不再用 rise_us±窗的 (max+min)/2：rise_us 偶发偏早会令窗横跨抬升沿而取到半幅值。
        v_top = float(max(0.0, self.result.turn_off.vce_off_max - self.result.turn_off.delta_vce))
        search = np.arange(off0, off1 + 1)
        if len(search) == 0:
            return

        peak_idx = int(search[np.argmax(vce[search])])
        peak_t_us = float(t[peak_idx] * 1e6)
        peak_v = float(vce[peak_idx])

        # B/Hb 卡尖峰之后的稳定阻断平台（Vce≈母线），避免落在上升沿同电平点上。
        tail = np.arange(peak_idx, off1 + 1)
        if len(tail) >= 2:
            top_idx = int(tail[np.argmin(np.abs(vce[tail] - v_top))])
        else:
            top_idx = int(search[np.argmin(np.abs(vce[search] - v_top))])
        top_t_us = float(t[top_idx] * 1e6)
        self.wave_plot.focus_interval_us(float(t[off0] * 1e6), float(t[off1] * 1e6))

        def _on_cursor_change(_fx_t: float, _fx_v: float, _mv_t: float, _mv_v: float, delta: float) -> None:
            # delta 已是两光标电压差绝对值（A、B 对称）
            self._save_manual_delta_vce("关断过程", _fx_t, _mv_t, _fx_v, _mv_v)
            if self.result is not None:
                self.result.turn_off.delta_vce = float(delta)
            self.result_table.set_metric_value("关断过程", "ΔVce", delta)
            # ΔVce 变化只影响 Ls_off（与 di/dt 无直接关联）
            self._sync_ls_off()
            if self.result is not None and focus_name == "Ls_off":
                off = self.result.turn_off
                self.statusBar().showMessage(
                    f"关断Ls_off: Ha(尖峰)={_fx_v:.2f} V, Hb(Top)={_mv_v:.2f} V, "
                    f"ΔVce={delta:.3f} V, di/dt={off.didt:.3f} A/ns, Ls_off={off.ls_off:.3f} nH"
                )
            else:
                self.statusBar().showMessage(
                    f"关断ΔVce交互: A(尖峰)={_fx_v:.2f} V, B(Top)={_mv_v:.2f} V, ΔVce={delta:.3f} V"
                )

        key = ("关断过程", "ΔVce")
        restored = (
            self._manual_delta_vce.get(key)
            if self._manual_cursors_apply_to_current_waveform()
            else None
        )
        if restored is not None:
            a_t, b_t, ha_v, hb_v = restored
            self.wave_plot.focus_interval_us(float(t[off0] * 1e6), float(t[off1] * 1e6))
            self.wave_plot.enable_delta_vce_interaction(
                fixed_t_us=a_t,
                fixed_v=ha_v,
                move_t_us=b_t,
                move_v=hb_v,
                on_change=_on_cursor_change,
                search_t0_us=float(t[off0] * 1e6),
                search_t1_us=float(t[off1] * 1e6),
            )
            return

        # A/Ha 卡尖峰（最大值，在上），B/Hb 卡 Top 阻断平台有效值（在下）
        self.wave_plot.enable_delta_vce_interaction(
            fixed_t_us=peak_t_us,
            fixed_v=peak_v,
            move_t_us=top_t_us,
            move_v=v_top,
            on_change=_on_cursor_change,
            search_t0_us=float(t[off0] * 1e6),
            search_t1_us=float(t[off1] * 1e6),
        )
        self._show_stored_metric_status(
            "关断过程", focus_name if focus_name == "Ls_off" else "ΔVce"
        )

    def _enable_energy_interaction(self, section: str, name: str) -> None:
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        if name == "Err":
            self._enable_err_energy_interaction()
            return
        if name not in {"Eoff", "Eon"}:
            return
        self._enable_eoff_eon_energy_interaction(section, name)

    def _enable_err_energy_interaction(self) -> None:
        """Err：Ha=Irr 平台、Hb=V_二极管 基线，A/B 交点 + 四光标围成积分区（同 Eon）。"""
        self._active_slope_param = None
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        t = self.bundle.t
        dt = self.bundle.dt
        segs = self.result.segments
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        irr = bundle_reverse_recovery_current(self.bundle, self.profile)
        v_diode = self.bundle.get(self.profile.v_diode)
        rr0, rr1 = segs.reverse_recovery
        on1 = segs.turn_on[1]
        markers = err_energy_markers(
            t, irr, v_diode, rr0, rr1, dt, i_search_end=on1
        )
        search_t0 = float(t[rr0] * 1e6)
        search_t1 = float(t[rr1] * 1e6)
        edge_a, edge_b = "falling", "rising"
        ha_channel, hb_channel, a_channel, b_channel = "irr", "v_diode", "irr", "v_diode"
        from dpt_extractor.metrics.iec_windows import err_recovery_peak_index

        ipk = err_recovery_peak_index(irr[rr0 : rr1 + 1], dt)
        a_anchor_us = float(t[rr0 + ipk] * 1e6)

        def _idx_from_t_us(t_us: float) -> int:
            ts = t_us * 1e-6
            idx = int(np.searchsorted(t, ts, side="left"))
            return max(0, min(idx, len(t) - 1))

        def _on_energy_change(
            ta_us: float, tb_us: float, ha_a: float, hb_v: float
        ) -> None:
            i0w = _idx_from_t_us(min(ta_us, tb_us))
            i1w = _idx_from_t_us(max(ta_us, tb_us))
            if i1w <= i0w + 1:
                return
            self._touch_manual_waveform_source()
            self._manual_energy[("反向恢复", "Err")] = (
                float(ta_us),
                float(tb_us),
                float(ha_a),
                float(hb_v),
            )
            win = IntegrationWindow(i0w, i1w, float(t[i0w]), float(t[i1w]))
            val = float(integrate_err_recovery(t, v_diode, irr, win))
            self.result.reverse_recovery.err = val
            self.result_table.set_metric_value("反向恢复", "Err", val)
            self.statusBar().showMessage(
                f"反向恢复-Err: Ha(Irr)={ha_a:.2f}A Hb(Vd)={hb_v:.2f}V "
                f"A={ta_us:.3f}µs B={tb_us:.3f}µs, Err={val:.3f} mJ"
            )

        legacy = self._manual_intervals.get(("反向恢复", "Err"))
        restored = self._manual_energy.get(("反向恢复", "Err"))
        if restored is not None:
            ta_r, tb_r, _, _ = restored
            ta_m = float(markers.t_start * 1e6)
            tb_m = float(markers.t_end * 1e6)
            if abs(ta_r - ta_m) > 0.08 or abs(tb_r - tb_m) > 0.08:
                restored = None
        if restored is not None:
            ta_us, tb_us, ha_a, hb_v = restored
        elif legacy is not None:
            ta_us, tb_us = legacy
            ha_a, hb_v = markers.ha_v, markers.hb_a
        else:
            ta_us = markers.t_start * 1e6
            tb_us = markers.t_end * 1e6
            ha_a, hb_v = markers.ha_v, markers.hb_a

        self.wave_plot.focus_interval_us(
            min(ta_us, tb_us) - 0.15, max(ta_us, tb_us) + 0.15
        )
        self.wave_plot.enable_energy_loss_interaction(
            search_t0,
            search_t1,
            ta_us,
            tb_us,
            ha_a,
            hb_v,
            _on_energy_change,
            edge_a=edge_a,
            edge_b=edge_b,
            b_channel=b_channel,
            ha_channel=ha_channel,
            hb_channel=hb_channel,
            a_channel=a_channel,
            a_anchor_us=a_anchor_us,
            rise_a_mode=None,
            fall_a_mode="err_irr",
            rise_b_mode="err_vd",
            peak_channels=("irr", "v_diode"),
            sync_cursors_from_levels=False,
        )
        if restored is None and legacy is None:
            self._show_stored_metric_status("反向恢复", "Err")

    def _enable_eoff_eon_energy_interaction(self, section: str, name: str) -> None:
        """Eoff/Eon：Ha=Vce 平台、Hb=Ic 平台，A/B 为与电平交点，拖动实时重算损耗。"""
        self._active_slope_param = None
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        t = self.bundle.t
        dt = self.bundle.dt
        segs = self.result.segments
        from dpt_extractor.models.waveform import bundle_total_current

        ic = bundle_total_current(self.bundle, self.profile)
        vce = self.bundle.get(self.profile.vce)

        if section == "关断过程" and name == "Eoff":
            markers = eoff_energy_markers(
                t,
                ic,
                vce,
                segs.turn_off[0],
                segs.turn_off[1],
                segs.pulse1_off,
                dt,
                pre_ns=self.cfg.energy.eoff_pre_ns,
                pulse1_on=segs.pulse1_on,
            )
            edge_a, edge_b = "rising", "falling"
            b_channel, b_level_vce = "ic", None
            ha_channel, hb_channel, a_channel = "vce", "ic", "vce"
            search_t0 = float(t[segs.turn_off[0]] * 1e6)
            search_t1 = float(t[segs.turn_off[1]] * 1e6)
            # 须在主 Vce 抬升前搜索；勿用 pulse1_off 作 anchor（会在关断沿之后误找）
            a_anchor_us = max(
                search_t0,
                float(markers.t_start * 1e6) - 150.0,
            )
            rise_a_mode = "eoff_vce"
            fall_b_mode = "eoff_ic_fall"
        else:
            markers = eon_energy_markers(
                t,
                ic,
                vce,
                segs.turn_on[0],
                segs.turn_on[1],
                segs.pulse2_on,
                dt,
                pulse1_off=segs.pulse1_off,
            )
            edge_a, edge_b = "rising", "falling"
            ha_channel, a_channel, hb_channel = "ic", "ic", "vce"
            b_channel = "vce"
            b_level_vce = None
            on_ref = (
                segs.pulse2_on
                if segs.turn_on[0] <= segs.pulse2_on <= segs.turn_on[1]
                else segs.turn_on[0]
            )
            a_anchor_us = float(t[on_ref] * 1e6) - 50.0
            rise_a_mode = "eon_ic"
            fall_b_mode = "eon_vce_fall"
            search_t0 = float(t[segs.turn_on[0]] * 1e6)
            search_t1 = float(t[segs.turn_on[1]] * 1e6)

        def _idx_from_t_us(t_us: float) -> int:
            ts = t_us * 1e-6
            idx = int(np.searchsorted(t, ts, side="left"))
            return max(0, min(idx, len(t) - 1))

        def _on_energy_change(
            ta_us: float, tb_us: float, ha_v: float, hb_a: float
        ) -> None:
            i0 = _idx_from_t_us(min(ta_us, tb_us))
            i1 = _idx_from_t_us(max(ta_us, tb_us))
            if i1 <= i0 + 1:
                return
            self._touch_manual_waveform_source()
            self._manual_energy[(section, name)] = (
                float(ta_us),
                float(tb_us),
                float(ha_v),
                float(hb_a),
            )
            win = IntegrationWindow(i0, i1, float(t[i0]), float(t[i1]))
            val = float(integrate_vi_window(t, vce, ic, win))
            if section == "关断过程":
                self.result.turn_off.eoff = val
                self.result_table.set_metric_value("关断过程", "Eoff", val)
            else:
                self.result.turn_on.eon = val
                self.result_table.set_metric_value("开通", "Eon", val)
            if section == "开通":
                ha_txt = f"Ha(Ic)={ha_v:.2f}A"
                hb_txt = f"Hb(Vce)={hb_a:.2f}V"
            else:
                ha_txt = f"Ha(Vce)={ha_v:.2f}V"
                hb_txt = f"Hb(Ic)={hb_a:.2f}A"
            self.statusBar().showMessage(
                f"{section}-{name}: {ha_txt} {hb_txt} "
                f"A={ta_us:.3f}µs B={tb_us:.3f}µs, {name}={val:.3f} mJ"
            )

        key = (section, name)
        restored = self._manual_energy.get(key)
        # 关断 Eoff：每次进入均用算法光标，避免会话内旧手动位置（如 14.37µs）被恢复
        if section == "关断过程" and name == "Eoff":
            restored = None
        elif restored is not None:
            ta_r, tb_r, _, _ = restored
            ta_m = float(markers.t_start * 1e6)
            tb_m = float(markers.t_end * 1e6)
            if abs(ta_r - ta_m) > 0.15 or abs(tb_r - tb_m) > 0.15:
                restored = None
        if restored is not None:
            ta_us, tb_us, ha_v, hb_v = restored
            self.wave_plot.focus_interval_us(min(ta_us, tb_us), max(ta_us, tb_us))
            self.wave_plot.enable_energy_loss_interaction(
                search_t0,
                search_t1,
                ta_us,
                tb_us,
                ha_v,
                hb_v,
                _on_energy_change,
                edge_a=edge_a,
                edge_b=edge_b,
                b_channel=b_channel,
                b_level_vce=b_level_vce,
                ha_channel=ha_channel,
                hb_channel=hb_channel,
                a_channel=a_channel,
                a_anchor_us=a_anchor_us,
                rise_a_mode=rise_a_mode,
                fall_b_mode=fall_b_mode,
                sync_cursors_from_levels=False,
            )
            return

        ta_us = markers.t_start * 1e6
        tb_us = markers.t_end * 1e6
        self.wave_plot.focus_interval_us(search_t0, search_t1)
        self.wave_plot.enable_energy_loss_interaction(
            search_t0,
            search_t1,
            ta_us,
            tb_us,
            markers.ha_v,
            markers.hb_a,
            _on_energy_change,
            edge_a=edge_a,
            edge_b=edge_b,
            b_channel=b_channel,
            b_level_vce=b_level_vce,
            ha_channel=ha_channel,
            hb_channel=hb_channel,
            a_channel=a_channel,
            a_anchor_us=a_anchor_us,
            rise_a_mode=rise_a_mode,
            fall_b_mode=fall_b_mode,
            sync_cursors_from_levels=False,
        )
        self._show_stored_metric_status(section, name)

    def _auto_align_irr_channel_baseline(self, irr: np.ndarray, i0: int, i1: int) -> None:
        """整段 Irr 波形 (max+min)/2 对齐 0 格（与导入时示波器规则一致）。"""
        _ = irr, i0, i1
        self.wave_plot._auto_center_channel("irr")

    def _saved_trr_measure_state(
        self,
    ) -> tuple[float, float, float, float, int | None] | None:
        """再次点击 Trr 时恢复用户上次拖动的 Ha/A/B。"""
        live = self.wave_plot.read_trr_measure_state()
        if live is not None:
            return live
        return self._manual_trr_measure

    def _enable_irr_interaction(self) -> None:
        """Irr：A/B 定区间，Hb 自动跟区间内 Irr 最大值（与 Trr 无关）。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        t = self.bundle.t
        segs = self.result.segments
        rr0, rr1 = segs.reverse_recovery
        irr = bundle_reverse_recovery_current(self.bundle, self.profile)

        interval = self._parameter_interval_us("反向恢复", "Irr")
        restored = self._manual_intervals.get(("反向恢复", "Irr"))
        if restored is not None:
            t0_us, t1_us = restored
        elif interval is not None:
            t0_us, t1_us = interval
        else:
            t0_us = float(t[rr0] * 1e6)
            t1_us = float(t[rr1] * 1e6)

        if restored is None:
            self._auto_align_irr_channel_baseline(irr, rr0, rr1)

        def _on_irr_interval(t0_us: float, t1_us: float) -> None:
            i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
            i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
            i0 = max(0, min(i0, len(t) - 1))
            i1 = max(i0 + 1, min(i1, len(t) - 1))
            val = float(self._irr_peak_interactive(irr, i0, i1))
            self._touch_manual_waveform_source()
            self._manual_intervals[("反向恢复", "Irr")] = (min(t0_us, t1_us), max(t0_us, t1_us))
            self.wave_plot.set_interval_peak_on_hb(
                val,
                channel="irr",
                t0_us=min(t0_us, t1_us),
                t1_us=max(t0_us, t1_us),
                use_abs_peak=True,
            )
            if self.result is None:
                return
            self.result.reverse_recovery.irr = val
            self.result_table.set_metric_value("反向恢复", "Irr", val)
            self.statusBar().showMessage(
                f"反向恢复 Irr: {val:.3f}A（A/B 区间内最大值，Hb 自动跟随）  "
                f"[{min(t0_us, t1_us):.3f}~{max(t0_us, t1_us):.3f}µs]"
            )

        self.wave_plot.focus_interval_us(t0_us, t1_us)
        self.wave_plot.enable_irr_peak_interaction(t0_us, t1_us, _on_irr_interval)
        if restored is not None:
            _on_irr_interval(t0_us, t1_us)
        elif self.result is not None:
            self.wave_plot.set_interval_peak_on_hb(
                float(self.result.reverse_recovery.irr),
                channel="irr",
                t0_us=min(t0_us, t1_us),
                t1_us=max(t0_us, t1_us),
                use_abs_peak=True,
            )
            self.statusBar().showMessage(
                f"反向恢复 Irr: {self.result.reverse_recovery.irr:.3f}A（拖动 A/B 后重算）  "
                f"[{min(t0_us, t1_us):.3f}~{max(t0_us, t1_us):.3f}µs]"
            )

    def _enable_trr_interaction(self) -> None:
        """Trr：Ha 参考线 + A/B 与 Ha 交点；拖 Ha 联动 A(上升沿)、B(下降沿) 首个交点。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        from dpt_extractor.metrics.irr_measure import (
            irr_parameter_peak_index,
            measure_irr_trr,
        )
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        t = self.bundle.t
        segs = self.result.segments
        i0, i1 = segs.reverse_recovery
        on0, on1 = segs.turn_on
        t0_us = float(t[i0] * 1e6)
        t1_us = float(t[i1] * 1e6)
        irr = bundle_reverse_recovery_current(self.bundle, self.profile)

        saved = self._saved_trr_measure_state()
        if saved is None:
            self._auto_align_irr_channel_baseline(irr, i0, i1)
            peak_idx = irr_parameter_peak_index(
                irr,
                i0,
                i1,
                segs.pulse2_on,
                on0,
                on1,
            )
            peak_idx = max(i0, min(int(peak_idx), min(on1, len(t) - 1)))
            measure_i1 = max(i1, peak_idx)
            # Ha=软恢复尾段参考（主峰后 300–600ns）；硬恢复回退算法默认尖峰前平台
            ha_override = None
            pk_us = float(t[peak_idx]) * 1e6
            ha_override = self._window_mid(irr, pk_us + 0.3, pk_us + 0.6)
            m = measure_irr_trr(
                t,
                irr,
                i0,
                measure_i1,
                ha=ha_override,
                peak_idx=peak_idx,
                i_fall_end=on1,
            )
            if m is None and ha_override is not None:
                # 软恢复(Ha≈0)时该参考线交点可能取不到，回退默认 Ha
                m = measure_irr_trr(
                    t,
                    irr,
                    i0,
                    measure_i1,
                    peak_idx=peak_idx,
                    i_fall_end=on1,
                )
            if m is None:
                self._enable_generic_parameter_interaction("反向恢复", "Trr")
                return
            ha_a, hb_a = m.ha, m.hb
            ta_us, tb_us = m.ta_s * 1e6, m.tb_s * 1e6
            peak_idx = m.peak_idx
            trr_init = m.trr_ns
        else:
            ha_a, hb_a, ta_us, tb_us, peak_idx = saved
            trr_init = abs(tb_us - ta_us) * 1e3

        def _on_trr_measure(
            ha: float,
            hb: float,
            ta_us: float,
            tb_us: float,
            trr_ns: float,
        ) -> None:
            if self.result is None:
                return
            pk = self.wave_plot._interactive_irr_peak_idx
            self._touch_manual_waveform_source()
            self._manual_trr_measure = (ha, hb, ta_us, tb_us, pk)
            self.result.reverse_recovery.trr = float(trr_ns)
            self.result_table.set_metric_value("反向恢复", "Trr", trr_ns)
            self.statusBar().showMessage(
                f"反向恢复 Trr={trr_ns:.3f}ns (A={ta_us:.3f}µs B={tb_us:.3f}µs Ha={ha:.2f}A)"
            )

        self.wave_plot.focus_interval_us(t0_us, t1_us)
        self.wave_plot.enable_trr_measure_interaction(
            t0_us,
            t1_us,
            ha_a,
            hb_a,
            ta_us,
            tb_us,
            _on_trr_measure,
            peak_idx=peak_idx,
            i_fall_end_idx=on1,
        )
        if saved is not None:
            _on_trr_measure(ha_a, hb_a, ta_us, tb_us, trr_init)
        else:
            self._show_stored_metric_status("反向恢复", "Trr")

    def _channel_for_param(self, section: str, name: str) -> str:
        """参数 → 波形通道（用于横向光标按该通道 V/div 换算定位）。"""
        if name in {"Ic_off_max", "Ic_on_max", "开通电流"}:
            return "ic"
        if name in {"Vce_off_max", "Vce_on_max", "ΔVce"}:
            return "vce"
        if name == "Irr":
            return "irr"
        if name == "Vrr":
            return "v_diode"
        if name == "串扰电压":
            return "vge_other"
        return "ic"

    def _enable_turn_on_current_interaction(self) -> None:
        """开通电流：A↔Hb、B↔Ha，与 ΔVce 相同实时贴波形交点；数值=Ha(|Ic@B|)。"""
        self._active_slope_param = None
        if self.bundle is None or self.result is None:
            return
        interval = self._parameter_interval_us("开通", "开通电流")
        if interval is None:
            return
        t = self.bundle.t
        dt = self.bundle.dt
        t_search_lo, t_search_hi = min(interval), max(interval)
        restored = self._manual_turn_on_current

        def _idx_from_t_us(t_us: float) -> int:
            idx = int(np.searchsorted(t, t_us * 1e-6, side="left"))
            return max(0, min(idx, len(t) - 1))

        def _on_turn_on_current_change(
            t_a_us: float, t_b_us: float, hb: float, ha: float
        ) -> None:
            i_val = float(ha)
            self.result.turn_on.turn_on_current = i_val
            self.result_table.set_metric_value("开通", "开通电流", i_val)
            self._touch_manual_waveform_source()
            self._manual_turn_on_current = (
                float(t_a_us),
                float(t_b_us),
                float(hb),
                float(ha),
            )
            self.statusBar().showMessage(
                f"开通-开通电流: A={t_a_us:.3f}us Hb={hb:.2f}A | "
                f"B={t_b_us:.3f}us Ha={ha:.2f}A → 值={i_val:.2f}A"
            )

        i0 = _idx_from_t_us(t_search_lo)
        i1 = _idx_from_t_us(t_search_hi)
        from dpt_extractor.metrics.plateau_level import turn_on_ic_link_default_times
        from dpt_extractor.models.waveform import bundle_total_current

        # 带符号：下桥导通前基线为负，光标须贴真实波形（上桥电流为正，等价不变）
        ic = bundle_total_current(self.bundle, self.profile)
        if restored is not None:
            t_a_us, t_b_us, hb0, ha0 = restored
        else:
            t_a_us, t_b_us, hb0, ha0 = turn_on_ic_link_default_times(
                t, ic, i0, i1, dt
            )
            if self.result is not None:
                ha0 = float(self.result.turn_on.turn_on_current)

        self.wave_plot.focus_interval_us(t_a_us, t_b_us)
        self.wave_plot.enable_turn_on_current_interaction(
            t_a_us,
            t_search_hi,
            t_b_us,
            hb0,
            ha0,
            _on_turn_on_current_change,
        )
        if restored is None:
            self._show_stored_metric_status("开通", "开通电流")

    def _enable_crosstalk_interaction(self, section: str) -> None:
        """串扰电压：A/B 定窗，Ha/Hb 锁定在窗内对管 Vge 最大/最小（与关断/开通同一逻辑）。"""
        self._active_slope_param = None
        if self.bundle is None or self.result is None:
            return
        name = "串扰电压"
        interval = self._parameter_interval_us(section, name)
        if interval is None:
            return
        t = self.bundle.t
        dt = self.bundle.dt
        vge_other = self.bundle.get(self.profile.vge_other)

        def _idx_from_t_us(t_us: float) -> int:
            ts = t_us * 1e-6
            idx = int(np.searchsorted(t, ts, side="left"))
            return max(0, min(idx, len(t) - 1))

        def _on_interval_change(t0_us: float, t1_us: float) -> None:
            i0 = _idx_from_t_us(min(t0_us, t1_us))
            i1 = _idx_from_t_us(max(t0_us, t1_us))
            if i1 <= i0 + 1:
                return
            vmax, vmin = crosstalk_extrema(vge_other, i0, i1 + 1, dt)
            cs = self.result.turn_off if section == "关断过程" else self.result.turn_on
            cs.crosstalk_vmax = float(vmax)
            cs.crosstalk_vmin = float(vmin)
            cs.crosstalk_v = float(vmax)
            ta, tb = min(t0_us, t1_us), max(t0_us, t1_us)
            self._touch_manual_waveform_source()
            self._manual_intervals[(section, name)] = (ta, tb)
            self.wave_plot.set_interval_minmax_horizontal(
                float(vmin),
                float(vmax),
                channel="vge_other",
                lock_horizontal=True,
                t0_us=ta,
                t1_us=tb,
            )
            disp = f"{cs.crosstalk_vmax:.2f}/{cs.crosstalk_vmin:.2f}"
            self.result_table.set_value_text(section, name, disp)
            self.statusBar().showMessage(
                f"{section}-串扰电压 交互窗口: {ta:.3f}us ~ {tb:.3f}us | "
                f"max={cs.crosstalk_vmax:.2f} V, min={cs.crosstalk_vmin:.2f} V"
            )

        restored = self._manual_intervals.get((section, name))
        t0_us, t1_us = restored if restored is not None else interval
        self.wave_plot.focus_interval_us(t0_us, t1_us)
        self.wave_plot.enable_crosstalk_interaction(
            start_t_us=t0_us,
            end_t_us=t1_us,
            on_change=_on_interval_change,
        )
        _on_interval_change(t0_us, t1_us)

    def _enable_generic_parameter_interaction(self, section: str, name: str) -> None:
        self._active_slope_param = None
        if self.bundle is None or self.result is None:
            return
        interval = self._parameter_interval_us(section, name)
        if interval is None:
            return
        t = self.bundle.t

        def _idx_from_t_us(t_us: float) -> int:
            ts = t_us * 1e-6
            idx = int(np.searchsorted(t, ts, side="left"))
            return max(0, min(idx, len(t) - 1))

        def _on_interval_change(t0_us: float, t1_us: float) -> None:
            i0 = _idx_from_t_us(min(t0_us, t1_us))
            i1 = _idx_from_t_us(max(t0_us, t1_us))
            if i1 <= i0 + 1:
                return
            val = self._recompute_param_from_interval(section, name, i0, i1)
            if val is None:
                return
            # 记住用户手动调整的区间，下次点击该参数时恢复
            self._touch_manual_waveform_source()
            self._manual_intervals[(section, name)] = (min(t0_us, t1_us), max(t0_us, t1_us))
            peak_y = self._peak_y_for_param(section, name, i0, i1)
            if peak_y is not None:
                ta, tb = min(t0_us, t1_us), max(t0_us, t1_us)
                self.wave_plot.set_interval_peak_horizontal(
                    float(peak_y),
                    channel=self._channel_for_param(section, name),
                    t0_us=ta,
                    t1_us=tb,
                    use_abs_peak=name in {"Ic_off_max", "Ic_on_max"},
                )
            if section == "关断过程" and name in {"Ic_off_max", "Vce_off_max"} and self.result is not None:
                cur = (
                    self.result.turn_off.ic_off_max
                    if name == "Ic_off_max"
                    else self.result.turn_off.vce_off_max
                )
                self.statusBar().showMessage(
                    f"{section}-{name} 区间最大值: [{t0_us:.3f},{t1_us:.3f}]us | {name}={cur:.3f}"
                )
                return
            if section == "开通" and name in {"Ic_on_max", "Vce_on_max"} and self.result is not None:
                cur = (
                    self.result.turn_on.ic_on_max
                    if name == "Ic_on_max"
                    else self.result.turn_on.vce_on_max
                )
                self.statusBar().showMessage(
                    f"{section}-{name} 区间最大值: [{t0_us:.3f},{t1_us:.3f}]us | {name}={cur:.3f}"
                )
                return
            if isinstance(val, str):
                self.result_table.set_value_text(section, name, val)
                self.statusBar().showMessage(
                    f"{section}-{name} 交互窗口: {t0_us:.3f}us ~ {t1_us:.3f}us, 实时值={val}"
                )
            else:
                self.result_table.set_metric_value(section, name, float(val))
                hint = self._iec_timing_status_hint(section, name)
                spec = f", {hint}" if hint else ""
                self.statusBar().showMessage(
                    f"{section}-{name} 交互窗口: {t0_us:.3f}us ~ {t1_us:.3f}us{spec}, "
                    f"实时值={val:.3f}"
                )

        # 若该参数此前手动调整过，恢复手动区间而非默认窗口
        restored = self._manual_intervals.get((section, name))
        t0_us, t1_us = restored if restored is not None else interval
        self.wave_plot.focus_interval_us(t0_us, t1_us)
        self.wave_plot.enable_interval_interaction(
            start_t_us=t0_us,
            end_t_us=t1_us,
            on_change=_on_interval_change,
            show_horizontal_peak=name
            in {"Ic_off_max", "Vce_off_max", "Ic_on_max", "Vce_on_max", "Vrr"},
        )
        # IEC 时间参数：点击仅对齐 A/B 光标；拖动 A/B 时由 on_change 重算并联动
        _MAX_INTERVAL_NAMES = {
            "Ic_off_max",
            "Vce_off_max",
            "Ic_on_max",
            "Vce_on_max",
            "Vrr",
        }
        if (section, name) in self._IEC_TIMING_PARAMS:
            self._refresh_iec_timing_status(section, name, t0_us, t1_us)
        elif restored is not None:
            _on_interval_change(t0_us, t1_us)
        elif name in _MAX_INTERVAL_NAMES:
            stored = self._stored_param_value(section, name)
            if stored is not None:
                self.statusBar().showMessage(
                    f"{section}-{name} 区间最大值: [{t0_us:.3f},{t1_us:.3f}]us | "
                    f"{name}={stored:.3f}（拖动 A/B 后重算）"
                )
        # 进入模式布置峰值横线（首次点击用 extract 结果，不重算）
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        peak_y = self._peak_y_for_param(section, name, i0, i1)
        if peak_y is not None:
            ta, tb = min(t0_us, t1_us), max(t0_us, t1_us)
            self.wave_plot.set_interval_peak_horizontal(
                float(peak_y),
                channel=self._channel_for_param(section, name),
                t0_us=ta,
                t1_us=tb,
                use_abs_peak=name in {"Ic_off_max", "Ic_on_max"},
            )
        if name in {"Ic_off_max", "Vce_off_max", "Ic_on_max", "Vce_on_max", "Vrr"}:
            self.statusBar().showMessage(
                f"{section}-{name} 区间最大值模式：拖动两根纵向光标，实时取窗口内最大值"
            )

    def _recompute_param_from_interval(
        self, section: str, name: str, i0: int, i1: int
    ) -> float | str | None:
        if self.bundle is None or self.result is None:
            return None
        t = self.bundle.t
        dt = self.bundle.dt
        from dpt_extractor.models.waveform import (
            bundle_reverse_recovery_current,
            bundle_total_current,
        )

        vce = self.bundle.get(self.profile.vce)
        ic = bundle_total_current(self.bundle, self.profile)
        irr = bundle_reverse_recovery_current(self.bundle, self.profile)
        v_diode = self.bundle.get(self.profile.v_diode)
        vge_other = self.bundle.get(self.profile.vge_other)
        dur_ns = max(0.0, (t[i1] - t[i0]) * 1e9)

        if section == "关断过程":
            if name == "Ic_off_max":
                ic_max = float(np.max(np.abs(ic[i0 : i1 + 1])))
                self.result.turn_off.ic_off_max = ic_max
                self.result_table.set_metric_value("关断过程", "Ic_off_max", ic_max)
                return ic_max
            if name == "Vce_off_max":
                vce_max = float(np.max(vce[i0 : i1 + 1]))
                self.result.turn_off.vce_off_max = vce_max
                self.result_table.set_metric_value("关断过程", "Vce_off_max", vce_max)
                return vce_max
            if name == "dv/dt":
                v = float(dvdt_max(t, vce, i0, i1 + 1, dt, self.cfg))
                self.result.turn_off.dvdt = v
                return v
            if name == "di/dt":
                v = float(didt_max(t, ic, i0, i1 + 1, dt, self.cfg))
                self.result.turn_off.didt = v
                # 仅 di/dt 变化 → 重算 Ls_off（不影响 ΔVce / 开通侧）
                self._sync_ls_off()
                return v
            if name == "Ls_off":
                # 在所选窗口重算 di/dt，并按 Ls_off = ΔVce / (di/dt) 同步
                didt = float(didt_max(t, ic, i0, i1 + 1, dt, self.cfg))
                self.result.turn_off.didt = didt
                self.result_table.set_metric_value("关断过程", "di/dt", didt)
                self._sync_ls_off()
                return self.result.turn_off.ls_off
            if name == "Toff":
                self.result.turn_off.toff = dur_ns
                self._sync_off_time_relations(changed="toff")
                return dur_ns
            if name == "Td_off":
                self.result.turn_off.td_off = dur_ns
                self._sync_off_time_relations(changed="td_off")
                return dur_ns
            if name == "Tf":
                self.result.turn_off.tf = dur_ns
                self._sync_off_time_relations(changed="tf")
                return dur_ns
            if name == "串扰电压":
                vmax, vmin = crosstalk_extrema(vge_other, i0, i1 + 1, dt)
                self.result.turn_off.crosstalk_vmax = float(vmax)
                self.result.turn_off.crosstalk_vmin = float(vmin)
                return f"{vmax:.2f}/{vmin:.2f}"

        if section == "开通":
            if name == "Ic_on_max":
                ic_max = float(np.max(np.abs(ic[i0 : i1 + 1])))
                self.result.turn_on.ic_on_max = ic_max
                self.result_table.set_metric_value("开通", "Ic_on_max", ic_max)
                return ic_max
            if name == "Vce_on_max":
                vce_max = float(np.max(vce[i0 : i1 + 1]))
                self.result.turn_on.vce_on_max = vce_max
                self.result_table.set_metric_value("开通", "Vce_on_max", vce_max)
                return vce_max
            if name == "开通电流":
                from dpt_extractor.metrics.plateau_level import (
                    turn_on_current_baseline_and_plateau,
                )

                _hb, v = turn_on_current_baseline_and_plateau(
                    np.abs(ic[i0 : i1 + 1]), dt
                )
                self.result.turn_on.turn_on_current = float(v)
                self.result_table.set_metric_value("开通", "开通电流", v)
                return v
            if name == "dv/dt":
                v = float(dvdt_max(t, vce, i0, i1 + 1, dt, self.cfg))
                self.result.turn_on.dvdt = v
                return v
            if name == "di/dt":
                v = float(didt_max(t, ic, i0, i1 + 1, dt, self.cfg))
                self.result.turn_on.didt = v
                # 仅 di/dt 变化 → 重算 Ls_on（不影响 ΔVce / 关断侧）
                self._sync_ls_on()
                return v
            if name == "Ls_on":
                # 在所选窗口重算 di/dt，并按 Ls_on = ΔV / (di/dt) 同步
                didt = float(didt_max(t, ic, i0, i1 + 1, dt, self.cfg))
                self.result.turn_on.didt = didt
                self.result_table.set_metric_value("开通", "di/dt", didt)
                self._sync_ls_on()
                return self.result.turn_on.ls_on
            if name == "Ton":
                self.result.turn_on.ton = dur_ns
                self._sync_on_time_relations(changed="ton")
                return dur_ns
            if name == "Td_on":
                self.result.turn_on.td_on = dur_ns
                self._sync_on_time_relations(changed="td_on")
                return dur_ns
            if name == "Tr":
                self.result.turn_on.tr = dur_ns
                self._sync_on_time_relations(changed="tr")
                return dur_ns
            if name == "串扰电压":
                vmax, vmin = crosstalk_extrema(vge_other, i0, i1 + 1, dt)
                self.result.turn_on.crosstalk_vmax = float(vmax)
                self.result.turn_on.crosstalk_vmin = float(vmin)
                return f"{vmax:.2f}/{vmin:.2f}"

        if section == "反向恢复":
            if name == "Irr":
                v = self._irr_peak_interactive(irr, i0, i1)
                self.result.reverse_recovery.irr = v
                return v
            if name == "Trr":
                self.result.reverse_recovery.trr = dur_ns
                return dur_ns
            if name == "Vrr":
                v = float(np.max(v_diode[i0 : i1 + 1]))
                self.result.reverse_recovery.vrr = v
                return v
            if name == "dv/dt":
                v = float(dvdt_max(t, v_diode, i0, i1 + 1, dt, self.cfg))
                self.result.reverse_recovery.dvdt_max = v
                return v
            if name == "di/dt":
                v = float(didt_max(t, irr, i0, i1 + 1, dt, self.cfg))
                self.result.reverse_recovery.didt_irr = v
                return v

        return None

    def _stored_param_value(self, section: str, name: str) -> float | str | None:
        """首次进入交互时沿用 extract 结果，避免点击参数即重算。"""
        if self.result is None:
            return None
        off = self.result.turn_off
        on = self.result.turn_on
        rr = self.result.reverse_recovery
        if section == "关断过程":
            m = {
                "ΔVce": off.delta_vce,
                "Ic_off_max": off.ic_off_max,
                "Vce_off_max": off.vce_off_max,
                "dv/dt": off.dvdt,
                "di/dt": off.didt,
                "Ls_off": off.ls_off,
                "Toff": off.toff,
                "Td_off": off.td_off,
                "Tf": off.tf,
                "Eoff": off.eoff,
            }
            if name == "串扰电压":
                return f"{off.crosstalk_vmax:.6f}/{off.crosstalk_vmin:.6f}"
            return m.get(name)
        if section == "开通":
            m = {
                "ΔVce": on.delta_vce,
                "Ic_on_max": on.ic_on_max,
                "Vce_on_max": on.vce_on_max,
                "开通电流": on.turn_on_current,
                "dv/dt": on.dvdt,
                "di/dt": on.didt,
                "Ls_on": on.ls_on,
                "Ton": on.ton,
                "Td_on": on.td_on,
                "Tr": on.tr,
                "Eon": on.eon,
            }
            if name == "串扰电压":
                return f"{on.crosstalk_vmax:.6f}/{on.crosstalk_vmin:.6f}"
            return m.get(name)
        if section == "反向恢复":
            m = {
                "Irr": rr.irr,
                "Trr": rr.trr,
                "Vrr": rr.vrr,
                "dv/dt": rr.dvdt_max,
                "di/dt": rr.didt_irr,
                "Err": rr.err,
            }
            return m.get(name)
        return None

    def _show_stored_metric_status(self, section: str, name: str) -> None:
        """点击参数仅放大波形，状态栏提示当前 extract 值。"""
        stored = self._stored_param_value(section, name)
        if stored is None:
            return
        if isinstance(stored, str):
            disp = stored
        else:
            from dpt_extractor.gui.result_table import format_metric_display

            disp = format_metric_display(section, name, float(stored))
        self.statusBar().showMessage(
            f"{section}-{name}: 当前值={disp}（拖动光标后重算）"
        )

    def _peak_y_for_param(
        self, section: str, name: str, i0: int, i1: int
    ) -> float | None:
        if self.bundle is None:
            return None
        from dpt_extractor.models.waveform import (
            bundle_reverse_recovery_current,
            bundle_total_current,
        )

        vce = self.bundle.get(self.profile.vce)
        ic = bundle_total_current(self.bundle, self.profile)
        irr = bundle_reverse_recovery_current(self.bundle, self.profile)
        v_diode = self.bundle.get(self.profile.v_diode)

        if section == "关断过程":
            if name == "Ic_off_max":
                seg = np.asarray(ic[i0 : i1 + 1], dtype=np.float64)
                if len(seg) == 0:
                    return 0.0
                return float(seg[int(np.argmax(np.abs(seg)))])
            if name == "Vce_off_max":
                return float(np.max(vce[i0 : i1 + 1]))
        if section == "开通":
            if name == "Ic_on_max":
                seg = np.asarray(ic[i0 : i1 + 1], dtype=np.float64)
                if len(seg) == 0:
                    return 0.0
                return float(seg[int(np.argmax(np.abs(seg)))])
            if name == "Vce_on_max":
                return float(np.max(vce[i0 : i1 + 1]))
        if section == "反向恢复":
            if name == "Irr":
                return self._irr_peak_interactive(irr, i0, i1)
            if name == "Vrr":
                return float(np.max(v_diode[i0 : i1 + 1]))
        return None

    def _irr_peak_interactive(self, irr: np.ndarray, i0: int, i1: int) -> float:
        seg = irr[i0 : i1 + 1]
        if len(seg) == 0:
            return 0.0
        def _robust_pos_peak(x: np.ndarray) -> float:
            if len(x) == 0:
                return 0.0
            if len(x) < 8:
                return float(np.max(x))
            # 交互默认线避免被单点尖峰抬高：取高分位替代绝对最大值
            return float(np.percentile(x, 98))

        def _robust_neg_peak_abs(x: np.ndarray) -> float:
            if len(x) == 0:
                return 0.0
            if len(x) < 8:
                return float(abs(np.min(x)))
            # 对负峰同理，取低分位替代绝对最小值
            return float(abs(np.percentile(x, 2)))

        k = max(8, len(seg) // 5)
        head = seg[:k]
        ref = float(np.median(head)) if len(head) else float(np.median(seg))
        amp = max(abs(float(np.max(seg))), abs(float(np.min(seg))), 1.0)
        th = 0.02 * amp
        if ref < 0:
            cross = np.where(seg > th)[0]
            if len(cross):
                return _robust_pos_peak(seg[cross[0] :])
            return _robust_pos_peak(seg)
        cross = np.where(seg < -th)[0]
        if len(cross):
            return _robust_neg_peak_abs(seg[cross[0] :])
        return _robust_neg_peak_abs(seg)

    def _irr_settled_midline(self, irr: np.ndarray, i0: int, i1: int) -> float:
        """Irr 尖峰前无震荡平台（Ha 默认，与 Trr 卡尺一致）。"""
        from dpt_extractor.metrics.irr_measure import (
            _default_ha,
            _find_recovery_peak_index,
        )

        seg = np.asarray(irr[i0 : i1 + 1], dtype=np.float64)
        if len(seg) == 0:
            return 0.0
        ipk = _find_recovery_peak_index(seg, self.bundle.dt)
        return float(_default_ha(seg, ipk))

    def _irr_default_crossings(
        self, irr: np.ndarray, t: np.ndarray, i0: int, i1: int
    ) -> tuple[float, float, float] | None:
        """返回 (Ha中线A值, A交点µs, B交点µs)。"""
        seg = np.asarray(irr[i0 : i1 + 1], dtype=np.float64)
        tt = np.asarray(t[i0 : i1 + 1], dtype=np.float64)
        if len(seg) < 8 or len(tt) != len(seg):
            return None
        mid = self._irr_settled_midline(irr, i0, i1)
        ipk = int(np.argmax(seg))
        if ipk <= 1 or ipk >= len(seg) - 2:
            return None

        ja = None
        for j in range(0, ipk):
            if seg[j] <= mid and seg[j + 1] >= mid:
                ja = j
        if ja is None:
            return None
        jb = None
        for j in range(ipk, len(seg) - 1):
            if seg[j] >= mid and seg[j + 1] <= mid:
                jb = j
                break
        if jb is None:
            return None

        def _interp_t(j: int) -> float:
            y1, y2 = seg[j], seg[j + 1]
            t1, t2 = tt[j], tt[j + 1]
            dy = y2 - y1
            if abs(dy) < 1e-12:
                return float(t1)
            f = (mid - y1) / dy
            f = max(0.0, min(1.0, f))
            return float(t1 + f * (t2 - t1))

        ta_us = _interp_t(ja) * 1e6
        tb_us = _interp_t(jb) * 1e6
        if tb_us <= ta_us:
            return None
        return float(mid), float(ta_us), float(tb_us)

    def _sync_ls_off(self) -> None:
        """Ls_off = 关断 ΔVce / (关断 di/dt)，单位 nH（ΔVce[V] / di/dt[A/ns]）。"""
        if self.result is None:
            return
        off = self.result.turn_off
        off.ls_off = float(off.delta_vce / off.didt) if off.didt > 1e-9 else 0.0
        self.result_table.set_metric_value("关断过程", "Ls_off", off.ls_off)

    def _sync_ls_on(self) -> None:
        """Ls_on = 开通 ΔVce / (开通 di/dt)，单位 nH，与 Ls_off 对称（ΔVce 可光标卡值）。"""
        if self.result is None:
            return
        on = self.result.turn_on
        on.ls_on = float(on.delta_vce / on.didt) if on.didt > 1e-9 else 0.0
        self.result_table.set_metric_value("开通", "Ls_on", on.ls_on)

    def _sync_off_time_relations(self, changed: str) -> None:
        """Keep Toff = Td_off + Tf during interactive edits."""
        if self.result is None:
            return
        off = self.result.turn_off
        if changed == "toff":
            # 保持当前 Td_off，占比缩放 Tf；若二者都近零则平分
            s = off.td_off + off.tf
            if s > 1e-9:
                ratio = max(0.0, min(1.0, off.td_off / s))
                off.td_off = off.toff * ratio
                off.tf = max(0.0, off.toff - off.td_off)
            else:
                off.td_off = off.toff * 0.5
                off.tf = off.toff * 0.5
        elif changed == "td_off":
            off.toff = max(0.0, off.td_off + off.tf)
        elif changed == "tf":
            off.toff = max(0.0, off.td_off + off.tf)
        self.result_table.set_metric_value("关断过程", "Toff", off.toff)
        self.result_table.set_metric_value("关断过程", "Td_off", off.td_off)
        self.result_table.set_metric_value("关断过程", "Tf", off.tf)

    def _sync_on_time_relations(self, changed: str) -> None:
        """Keep Ton = Td_on + Tr during interactive edits."""
        if self.result is None:
            return
        on = self.result.turn_on
        if changed == "ton":
            # 保持当前 Td_on，占比缩放 Tr；若二者都近零则平分
            s = on.td_on + on.tr
            if s > 1e-9:
                ratio = max(0.0, min(1.0, on.td_on / s))
                on.td_on = on.ton * ratio
                on.tr = max(0.0, on.ton - on.td_on)
            else:
                on.td_on = on.ton * 0.5
                on.tr = on.ton * 0.5
        elif changed == "td_on":
            on.ton = max(0.0, on.td_on + on.tr)
        elif changed == "tr":
            on.ton = max(0.0, on.td_on + on.tr)
        self.result_table.set_metric_value("开通", "Ton", on.ton)
        self.result_table.set_metric_value("开通", "Td_on", on.td_on)
        self.result_table.set_metric_value("开通", "Tr", on.tr)

    _IEC_TIMING_PARAMS = frozenset(
        {
            ("关断过程", "Toff"),
            ("关断过程", "Td_off"),
            ("关断过程", "Tf"),
            ("开通", "Ton"),
            ("开通", "Td_on"),
            ("开通", "Tr"),
        }
    )

    def _turn_on_timing_instants(self):
        from dpt_extractor.models.waveform import bundle_total_current

        assert self.bundle is not None and self.result is not None
        segs = self.result.segments
        assert segs is not None
        vge = self.bundle.get(self.profile.vge)
        ic = bundle_total_current(self.bundle, self.profile)
        on0, on1 = segs.turn_on
        return turn_on_timing_instants(
            self.bundle.t,
            vge,
            ic,
            on0,
            on1,
            segs.pulse2_on,
            self.bundle.dt,
            self.cfg,
        )

    def _turn_off_timing_instants(self):
        from dpt_extractor.models.waveform import bundle_total_current

        assert self.bundle is not None and self.result is not None
        segs = self.result.segments
        assert segs is not None
        vge = self.bundle.get(self.profile.vge)
        ic = bundle_total_current(self.bundle, self.profile)
        off0, off1 = segs.turn_off
        return turn_off_timing_instants(
            self.bundle.t,
            vge,
            ic,
            off0,
            off1,
            segs.pulse1_off,
            self.bundle.dt,
            self.cfg,
            pulse1_on=segs.pulse1_on,
            pulse2_on=segs.pulse2_on,
        )

    def _iec_timing_interval_us(self, section: str, name: str) -> tuple[float, float] | None:
        """按 IEC60747-9 / ZF 阈值穿越定位 A/B 光标。"""
        if section == "开通":
            inst = self._turn_on_timing_instants()
            if name == "Ton":
                if inst.t_v10_s is None or inst.t_i90_s is None:
                    return None
                return inst.t_v10_s * 1e6, inst.t_i90_s * 1e6
            if name == "Td_on":
                if inst.t_v10_s is None or inst.t_i10_s is None:
                    return None
                return inst.t_v10_s * 1e6, inst.t_i10_s * 1e6
            if name == "Tr":
                if inst.t_i10_s is None or inst.t_i90_s is None:
                    return None
                return inst.t_i10_s * 1e6, inst.t_i90_s * 1e6
        if section == "关断过程":
            inst = self._turn_off_timing_instants()
            if name == "Toff":
                if inst.t_v90_s is None or inst.t_i10_s is None:
                    return None
                return inst.t_v90_s * 1e6, inst.t_i10_s * 1e6
            if name == "Td_off":
                if inst.t_v90_s is None or inst.t_i90_s is None:
                    return None
                return inst.t_v90_s * 1e6, inst.t_i90_s * 1e6
            if name == "Tf":
                if inst.t_i90_s is None or inst.t_i10_s is None:
                    return None
                return inst.t_i90_s * 1e6, inst.t_i10_s * 1e6
        return None

    def _refresh_iec_timing_status(
        self, section: str, name: str, t0_us: float, t1_us: float
    ) -> None:
        """进入 IEC 时间参数交互：仅摆放 A/B 与状态栏，不重算、不联动其它项。"""
        if self.result is None:
            return
        hint = self._iec_timing_status_hint(section, name)
        spec = f", {hint}" if hint else ""
        if section == "关断过程":
            off = self.result.turn_off
            val = {"Toff": off.toff, "Td_off": off.td_off, "Tf": off.tf}.get(name)
        elif section == "开通":
            on = self.result.turn_on
            val = {"Ton": on.ton, "Td_on": on.td_on, "Tr": on.tr}.get(name)
        else:
            val = None
        if val is None:
            return
        self.statusBar().showMessage(
            f"{section}-{name} 交互窗口: {t0_us:.3f}us ~ {t1_us:.3f}us{spec}, "
            f"实时值={val:.3f}"
        )

    def _iec_timing_status_hint(self, section: str, name: str) -> str:
        hints = {
            ("开通", "Ton"): "10%Vge→90%Icm",
            ("开通", "Td_on"): "10%Vge→10%Icm",
            ("开通", "Tr"): "10%Icm→90%Icm",
            ("关断过程", "Toff"): "90%Vge↓→10%Ic↓",
            ("关断过程", "Td_off"): "90%Vge↓→90%Ic↓",
            ("关断过程", "Tf"): "90%Ic↓→10%Ic↓",
        }
        return hints.get((section, name), "")

    def _default_trr_interval_us(self) -> tuple[float, float] | None:
        """
        Trr 默认 A/B：
        A=反向主谷后首次上穿中线；B=正向峰值后首次下穿中线。
        """
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        t = self.bundle.t
        dt = self.bundle.dt
        segs = self.result.segments
        on0, on1 = segs.turn_on
        if on1 <= on0 + 6:
            return None

        ts = t[on0:on1]
        irr = bundle_reverse_recovery_current(self.bundle, self.profile)[on0:on1]
        if len(ts) < 8 or len(irr) < 8:
            return None

        # 轻平滑，降低单点尖噪影响
        win = max(5, int(round(40e-9 / max(dt, 1e-15))))
        if win % 2 == 0:
            win += 1
        win = min(win, max(5, len(irr) // 3 * 2 + 1))
        if win >= 5:
            ker = np.ones(win, dtype=np.float64) / float(win)
            ys = np.convolve(irr.astype(np.float64), ker, mode="same")
        else:
            ys = irr.astype(np.float64)

        # 以窗口前段中位数作中线，适配轻微零漂
        k = max(8, len(ys) // 6)
        mid = float(np.median(ys[:k]))

        i_neg = int(np.argmin(ys))
        i_pos = int(np.argmax(ys))
        if i_pos <= i_neg + 2:
            return None

        def _cross_up(arr: np.ndarray, start: int, level: float) -> int | None:
            for j in range(start, len(arr) - 1):
                if arr[j] <= level and arr[j + 1] >= level:
                    return j
            return None

        def _cross_down(arr: np.ndarray, start: int, level: float) -> int | None:
            for j in range(start, len(arr) - 1):
                if arr[j] >= level and arr[j + 1] <= level:
                    return j
            return None

        j_a = _cross_up(ys, i_neg, mid)
        if j_a is None:
            return None
        j_b = _cross_down(ys, max(i_pos, j_a + 1), mid)
        if j_b is None:
            return None

        ta = float(ts[j_a] * 1e6)
        tb = float(ts[j_b] * 1e6)
        if tb <= ta:
            return None
        return ta, tb

    def _turn_on_ic_max_window_indices(self) -> tuple[int, int] | None:
        """Window used by extract._turn_on_ic_max_in_base_window."""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.models.waveform import bundle_total_current

        dt = max(float(self.bundle.dt), 1e-15)
        segs = self.result.segments
        ic = bundle_total_current(self.bundle, self.profile)
        vce = self.bundle.get(self.profile.vce)
        n = len(ic)
        if n == 0:
            return None
        on0, on1 = segs.turn_on
        s0 = max(0, min(on0, n - 2))
        s1 = max(s0 + 2, min(on1, n - 1))
        ic_top = turn_on_ic_top(ic, segs.pulse2_on, segs.pulse2_off, dt)
        vce_top = turn_on_vce_top_from_ic_rise(
            ic, vce, segs.pulse2_on, segs.pulse2_off, dt
        )
        abs_ic = np.abs(ic)
        pre0 = max(0, s0 - int(300e-9 / dt))
        pre1 = max(pre0 + 5, s0)
        ic_base = float(np.percentile(abs_ic[pre0:pre1], 50)) if pre1 > pre0 else 0.0
        ic_rise_th = ic_base + max(0.02 * max(ic_top, 1.0), 3.0)

        i_start = s0
        for k in range(s0, s1):
            if abs_ic[k] >= ic_rise_th:
                i_start = k
                break

        post0 = min(n - 1, max(i_start + int(120e-9 / dt), s0))
        post1 = max(post0 + 10, min(s1, post0 + int(700e-9 / dt)))
        if post1 <= post0 + 5:
            post0 = max(s0, s1 - int(500e-9 / dt))
            post1 = s1
        vce_base = (
            float(np.percentile(vce[post0:post1], 20))
            if post1 > post0
            else float(np.min(vce[s0:s1]))
        )
        vce_base_th = vce_base + max(0.02 * max(vce_top, 1.0), 2.0)

        i_end = s1
        for k in range(i_start, s1):
            if vce[k] <= vce_base_th:
                i_end = k
                break
        if i_end <= i_start + 2:
            i_end = s1
        return int(i_start), int(i_end)

    def _turn_off_vce_max_window_indices(self) -> tuple[int, int] | None:
        """Narrow the default Vce_off_max cursor window to the turn-off spike."""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        vce = np.asarray(self.bundle.get(self.profile.vce), dtype=np.float64)
        n = len(vce)
        if n == 0:
            return None
        dt = max(float(self.bundle.dt), 1e-15)
        off0, off1 = self.result.segments.turn_off
        s0 = max(0, min(int(off0), n - 2))
        s1 = max(s0 + 2, min(int(off1), n - 1))
        seg = vce[s0 : s1 + 1]
        if len(seg) == 0:
            return None

        peak_idx = s0 + int(np.nanargmax(seg))
        peak_v = float(vce[peak_idx])
        off = self.result.turn_off
        top_v = float(off.vce_off_max - off.delta_vce)
        if not np.isfinite(top_v) or top_v <= 0.0 or top_v >= peak_v:
            post0 = min(s1, peak_idx + max(3, int(40e-9 / dt)))
            post1 = min(s1 + 1, peak_idx + max(10, int(500e-9 / dt)))
            if post1 > post0 + 3:
                top_v = float(np.percentile(vce[post0:post1], 50))
            else:
                top_v = float(np.percentile(seg, 75))

        overshoot = peak_v - top_v
        min_margin = max(5.0, 0.01 * max(abs(peak_v), 1.0))
        if overshoot > min_margin:
            threshold = top_v + max(0.12 * overshoot, min_margin)
            left = peak_idx
            while left > s0 and float(vce[left]) >= threshold:
                left -= 1
            right = peak_idx
            while right < s1 and float(vce[right]) >= threshold:
                right += 1
        else:
            left = peak_idx
            right = peak_idx

        pad = max(3, int(60e-9 / dt))
        i0 = max(s0, left - pad)
        i1 = min(s1, right + pad)
        min_half = max(3, int(80e-9 / dt))
        i0 = min(i0, max(s0, peak_idx - min_half))
        i1 = max(i1, min(s1, peak_idx + min_half))

        max_half = max(min_half, int(350e-9 / dt))
        if peak_idx - i0 > max_half:
            i0 = peak_idx - max_half
        if i1 - peak_idx > max_half:
            i1 = peak_idx + max_half
        return int(max(s0, i0)), int(min(s1, i1))

    def _parameter_max_interval_indices(
        self, section: str, name: str
    ) -> tuple[int, int] | None:
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        segs = self.result.segments
        t = self.bundle.t
        dt = max(float(self.bundle.dt), 1e-15)
        n = len(t)
        if n == 0:
            return None

        def _clip_pair(a: int, b: int) -> tuple[int, int]:
            i0 = max(0, min(int(a), n - 1))
            i1 = max(i0, min(int(b), n - 1))
            return i0, i1

        if section == "关断过程" and name == "Ic_off_max":
            vge = self.bundle.get(self.profile.vge)
            win = turn_off_ic_fall_window(
                t,
                vge,
                segs.turn_off[0],
                segs.turn_off[1],
                segs.pulse1_on,
                segs.pulse1_off,
                segs.pulse2_on,
                dt,
                self.cfg,
            )
            return _clip_pair(*(win if win is not None else segs.turn_off))

        if section == "关断过程" and name == "Vce_off_max":
            return self._turn_off_vce_max_window_indices()

        if section == "开通" and name == "Ic_on_max":
            return self._turn_on_ic_max_window_indices()

        if section == "开通" and name == "Vce_on_max":
            from dpt_extractor.models.waveform import bundle_total_current

            ic = bundle_total_current(self.bundle, self.profile)
            vce = self.bundle.get(self.profile.vce)
            vce_top = turn_on_vce_top_from_ic_rise(
                ic, vce, segs.pulse2_on, segs.pulse2_off, dt
            )
            return _clip_pair(
                *_turn_on_vce_pre_fall_slice(
                    vce, segs.turn_on[0], segs.turn_on[1], dt, vce_top
                )
            )

        if section == "反向恢复" and name == "Irr":
            from dpt_extractor.models.waveform import bundle_reverse_recovery_current

            irr = bundle_reverse_recovery_current(self.bundle, self.profile)
            on0, on1 = segs.turn_on
            rr0, _rr1 = segs.reverse_recovery
            s0 = max(0, min(max(rr0, segs.pulse2_on), on1 - 1))
            s1 = max(s0 + 1, min(on1, len(irr)))
            if s1 <= s0:
                s0 = max(0, min(on0, len(irr) - 1))
                s1 = max(s0 + 1, min(on1, len(irr)))
            return _clip_pair(s0, s1 - 1)

        return None

    def _parameter_interval_us(self, section: str, name: str) -> tuple[float, float] | None:
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        t = self.bundle.t
        segs = self.result.segments

        iec_interval = self._iec_timing_interval_us(section, name)
        if iec_interval is not None:
            return iec_interval

        # 直接窗口型参数
        if section == "关断过程" and name == "Eoff":
            from dpt_extractor.models.waveform import bundle_total_current

            vce = self.bundle.get(self.profile.vce)
            i = bundle_total_current(self.bundle, self.profile)
            w = eoff_window_scope_example(
                t,
                i,
                vce,
                segs.turn_off[0],
                segs.turn_off[1],
                segs.pulse1_off,
                self.bundle.dt,
                pre_ns=self.cfg.energy.eoff_pre_ns,
                pulse1_on=segs.pulse1_on,
            )
            return w.t_start * 1e6, w.t_end * 1e6
        if section == "开通" and name == "Eon":
            from dpt_extractor.models.waveform import bundle_total_current

            vce = self.bundle.get(self.profile.vce)
            i = bundle_total_current(self.bundle, self.profile)
            w = eon_window_scope_example(
                t, i, vce, segs.turn_on[0], segs.turn_on[1], segs.pulse2_on, self.bundle.dt
            )
            return w.t_start * 1e6, w.t_end * 1e6
        if section == "反向恢复" and name == "Err":
            from dpt_extractor.models.waveform import bundle_reverse_recovery_current

            irr_sig = bundle_reverse_recovery_current(self.bundle, self.profile)
            w = err_window_scope_example(
                t,
                irr_sig,
                self.bundle.get(self.profile.v_diode),
                segs.turn_on[0],
                segs.turn_on[1],
                self.bundle.dt,
            )
            return w.t_start * 1e6, w.t_end * 1e6

        max_interval = self._parameter_max_interval_indices(section, name)
        if max_interval is not None:
            i0, i1 = max_interval
            return t[i0] * 1e6, t[i1] * 1e6

        # 时间参数：用当前结果值近似定位
        if section == "关断过程":
            if name in {"Ic_off_max", "Vce_off_max", "Ls_off", "串扰电压"}:
                return t[segs.turn_off[0]] * 1e6, t[segs.turn_off[1]] * 1e6
            if name in {"dv/dt", "di/dt"}:
                return t[segs.turn_off[0]] * 1e6, t[segs.turn_off[1]] * 1e6
        if section == "开通":
            if name in {"Ic_on_max", "Vce_on_max", "开通电流", "Ls_on", "串扰电压"}:
                return t[segs.turn_on[0]] * 1e6, t[segs.turn_on[1]] * 1e6
            if name in {"dv/dt", "di/dt"}:
                return t[segs.turn_on[0]] * 1e6, t[segs.turn_on[1]] * 1e6
        if section == "反向恢复":
            if name in {"Irr", "Vrr"}:
                if name == "Vrr":
                    return t[segs.turn_on[0]] * 1e6, t[segs.turn_on[1]] * 1e6
                return t[segs.reverse_recovery[0]] * 1e6, t[segs.reverse_recovery[1]] * 1e6
            if name == "Trr":
                trr_iv = self._default_trr_interval_us()
                if trr_iv is not None:
                    return trr_iv
                return t[segs.reverse_recovery[0]] * 1e6, t[segs.reverse_recovery[1]] * 1e6
            if name in {"dv/dt", "di/dt"}:
                from dpt_extractor.metrics.iec_windows import rr_slope_window_indices

                on0, _ = segs.turn_on
                _, rr1 = segs.reverse_recovery
                i0, i1 = rr_slope_window_indices(
                    on0, rr1, len(t), self.bundle.dt
                )
                return t[i0] * 1e6, t[i1] * 1e6

        return None

    def _recalculate(self, *, reset_manual: bool = False) -> None:
        if self.bundle is None:
            QMessageBox.warning(self, "提示", "请先打开波形文件")
            return
        try:
            self.cfg.slope_ranges = dict(self._slope_ranges)
            active_param = self._active_slope_param
            if reset_manual:
                self._clear_manual_adjustments()
                active_param = None
            try:
                self.result = run_extraction(self.bundle, self.profile, self.cfg)
            except ShortCircuitExtractNotReady:
                self.result = None
                self._clear_manual_adjustments(reset_plot=False)
                self.wave_plot.plot_waveforms(self.bundle, self.profile, None)
                self.result_table.set_mode_placeholder(
                    "短路计算",
                    "功能开发中。当前仅显示波形，参数提取与 Excel 导出将在后续版本提供。",
                )
                self.statusBar().showMessage(
                    "短路计算：功能开发中，当前仅显示波形"
                )
                return

            self.result_table.set_result(self.result)
            if self.result.detected_pulse_count > 0:
                self._update_pulse_toolbar(
                    self.result.detected_pulse_count,
                    self.result.off_pulse_index,
                    self.result.on_pulse_index,
                )
            self.result_table.setMaximumWidth(
                self.result_table.preferred_panel_width()
            )
            if not self._splitter_user_moved:
                self._sync_splitter_sizes()
            self.wave_plot.plot_waveforms(self.bundle, self.profile, self.result)
            if active_param is not None and self._manual_cursors_apply_to_current_waveform():
                section, name = active_param
                self._on_value_clicked(section, name)

            off, on, rr = self.result.turn_off, self.result.turn_on, self.result.reverse_recovery
            vdc_disp = self.result.vdc_set if self.result.vdc_set is not None else self.result.vdc
            idc_disp = off.ic_off_max
            if self.result.single_pulse_mode:
                msg = (
                    f"单脉冲工况  Vdc={vdc_disp:.1f} V  Idc={idc_disp:.0f} A  |  "
                    f"Eoff={off.eoff:.3f} mJ  |  Ic_off={off.ic_off_max:.0f} A"
                )
            else:
                msg = (
                    f"Vdc={vdc_disp:.1f} V  Idc={idc_disp:.0f} A  |  "
                    f"Eoff={off.eoff:.3f} mJ  Eon={on.eon:.3f} mJ  Err={rr.err:.3f} mJ  |  "
                    f"Ic_off={off.ic_off_max:.0f} A  Irr={rr.irr:.1f} A"
                )
            self.statusBar().showMessage(msg)
        except Exception as e:
            QMessageBox.critical(self, "提取失败", str(e))

    def _export_excel(self) -> None:
        if self.result is None:
            QMessageBox.warning(self, "提示", "无提取结果可导出")
            return
        if self._current_path:
            suggested = Path(self._current_path).with_suffix(".xlsx")
        else:
            suggested = default_export_path(self.result)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 Excel",
            save_dialog_initial_path(suggested),
            "Excel (*.xlsx)",
        )
        if not path:
            return
        if not str(path).lower().endswith(".xlsx"):
            path = str(Path(path).with_suffix(".xlsx"))
        try:
            export_to_excel(self.result, path)
            set_last_export_path(path)
            QMessageBox.information(self, "导出成功", f"已保存:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
