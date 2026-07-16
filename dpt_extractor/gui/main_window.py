from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
import time
from typing import Callable
import numpy as np

from PyQt6.QtCore import QObject, QRunnable, QSize, QThreadPool, Qt, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCloseEvent, QPainter, QPalette, QPixmap, QResizeEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QApplication,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from dpt_extractor.config.loader import AppConfig, load_config
from dpt_extractor.export.excel_export import default_export_path, export_to_excel
from dpt_extractor.export.report_template import (
    DPT_OVERVIEW_IMAGE_PARAM,
    SHORT_REPORT_IMAGE_PARAMS,
    ReportWriteSummary,
    dpt_report_image_params_for_result,
    write_report_template,
)
from dpt_extractor.gui.channel_mapping_dialog import resolve_profile
from dpt_extractor.gui.recent_paths import (
    open_dialog_start_dir,
    report_output_path,
    report_template_source_path,
    save_dialog_initial_path,
    set_last_export_path,
    set_last_open_path,
    set_report_output_path,
    set_report_template_source_path,
)
from dpt_extractor.gui.result_table import ResultTable
from dpt_extractor.gui.theme import (
    DARK_STYLESHEET,
    SUMMARY_STYLE,
    apply_combo_popup_style,
)
from dpt_extractor.gui.waveform_plot import WaveformPlot
from dpt_extractor.utils.app_paths import (
    commercial_notice_poster_path,
    copy_report_template,
    default_report_template_path,
)
from dpt_extractor.models.channel_mapping import (
    LOGICAL_SIGNAL_KEYS,
    ChannelMapping,
    ChannelMappingStore,
    apply_mapping,
    infer_best_mapping_from_bundle,
    infer_mapping_from_bundle,
    infer_short_circuit_mapping_from_bundle,
    resolve_mapping_conflicts,
    validate_mapping,
)
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import (
    PHASES,
    UPPER_BRIDGE,
    BridgeProfile,
    as_short_circuit_profile,
    guess_profile_from_path,
    has_bridge_hint_from_path,
    make_profile,
)
from dpt_extractor.models.results import (
    ExtractResult,
    SHORT_CIRCUIT_TSC_RANGE_DEFAULT,
    power_metric_name,
)
from dpt_extractor.models.slope_range import (
    SLOPE_ROW_KEYS,
    SlopeRange,
    default_slope_ranges,
    normalize_slope_range,
)
from dpt_extractor.models.waveform import WaveformBundle, normalize_channel_reference
from dpt_extractor.metrics.iec_windows import (
    IntegrationWindow,
    _quiet_local_platform_level,
    eoff_energy_markers,
    eoff_window_scope_example,
    eon_energy_markers,
    eon_window_scope_example,
    err_energy_markers,
    integrate_err_recovery,
    integrate_vi_window,
)
from dpt_extractor.metrics.energy import peak_power_kw
from dpt_extractor.metrics.rr_tail import reverse_recovery_tail_end_index
from dpt_extractor.metrics.offset_measurement import (
    OFFSET_MEASUREMENT_BY_KEY,
    OFFSET_RANGE_LABELS,
    auto_offset_measurement_unit,
    calculate_offset_measurement,
    convert_offset_measurement_value,
    normalize_offset_range_key,
    offset_measurement_marker,
    offset_measurement_unit,
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
from dpt_extractor.utils.signal import crossing_time, smooth, threshold_value
from dpt_extractor.metrics.plateau_level import turn_on_vce_on_max_window_indices
from dpt_extractor.models.test_mode import MODE_UI_LABELS, TestMode, parse_test_mode
from dpt_extractor.pipeline.extract import _turn_on_delta_vce_knee_point
from dpt_extractor.pipeline.pulse_sequence import dpt_export_results
from dpt_extractor.pipeline.run_extract import run_extraction
from dpt_extractor.pipeline.short_circuit_extract import (
    find_desat_voltage_channel,
    short_circuit_current_cursors,
    short_circuit_current_percent_cursors,
    short_circuit_desat_cursors,
    short_circuit_energy_peak_value,
    short_circuit_tsc_range_percentages,
    short_circuit_energy_value,
    short_circuit_vpeak_cursors,
)


REPORT_PLOT_CAPTURE_SIZE = QSize(1280, 960)
COMMERCIAL_AUTH_QQ = "3796823"
NONCOMMERCIAL_NOTICE_TITLE = "非商业用途授权提示"
NONCOMMERCIAL_NOTICE_SETTINGS_KEY = "license/noncommercial_notice_shown"
TASK_PROGRESS_TOTAL = 100000
REPORT_PROGRESS_TOTAL = TASK_PROGRESS_TOTAL
REPORT_PROGRESS_TEMPLATE_DONE = 5000
REPORT_PROGRESS_CAPTURE_DONE = 62000
REPORT_PROGRESS_WRITE_START = REPORT_PROGRESS_CAPTURE_DONE
REPORT_PROGRESS_WRITE_DONE_CAP = 99000
LOAD_PROGRESS_PARSE_DONE = 35000
LOAD_PROGRESS_EXTRACT_DONE = 80000
LOAD_PROGRESS_APPLY_START = 84000
LOAD_PROGRESS_PLOT_DONE = 98000
TEMP_CONDITION_DEFAULTS = {
    "RT": 25.0,
    "HT": 150.0,
    "LT": -40.0,
}
TEMP_CONDITION_SETTINGS_PREFIX = "conditions/temperature/"
SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY = "short_circuit/tsc_range"


def _format_temperature_number(value: float) -> str:
    fv = float(value)
    if abs(fv - round(fv)) < 0.05:
        return str(int(round(fv)))
    return f"{fv:.1f}".rstrip("0").rstrip(".")


def _format_temperature_label(value: float) -> str:
    return f"{_format_temperature_number(value)}℃"


class TemperatureSpinBox(QDoubleSpinBox):
    def textFromValue(self, value: float) -> str:  # noqa: N802
        return _format_temperature_number(value)


class CenteredComboBox(QComboBox):
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QStylePainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        text = opt.currentText
        opt.currentText = ""
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        text_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            opt,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextSingleLine,
            text,
        )


class PulseComboBox(CenteredComboBox):
    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(1, 10)
        self.currentIndexChanged.connect(self._emit_value_changed)

    def _emit_value_changed(self, _index: int = 0) -> None:
        self.valueChanged.emit(self.value())

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        current = self.value() if self.count() else int(minimum)
        was_blocked = self.blockSignals(True)
        try:
            self.clear()
            for value in range(int(minimum), int(maximum) + 1):
                self.addItem(f"第 {value} 波", value)
            self.setValue(max(int(minimum), min(int(maximum), current)))
        finally:
            self.blockSignals(was_blocked)

    def setMaximum(self, maximum: int) -> None:  # noqa: N802
        self.setRange(1, int(maximum))

    def setValue(self, value: int) -> None:  # noqa: N802
        idx = self.findData(int(value))
        if idx >= 0:
            self.setCurrentIndex(idx)

    def value(self) -> int:
        data = self.currentData()
        return int(data) if data is not None else 1


class ReportProgressPanel(QFrame):
    """Compact task progress readout with percent and ETA."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("reportProgressPanel")
        self._minimum = 0
        self._maximum = 100
        self._value = 0
        self._format = "待命"
        self._started_at = time.perf_counter()
        self._busy = False

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh_readout)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(8)

        self._stage_label = QLabel("任务进度")
        self._stage_label.setObjectName("reportProgressStage")
        self._detail_label = QLabel("待命")
        self._detail_label.setObjectName("reportProgressDetail")
        self._detail_label.setMinimumWidth(62)
        self._detail_label.setMaximumWidth(180)

        sep_a = QLabel("|")
        sep_a.setObjectName("reportProgressSeparator")
        sep_b = QLabel("|")
        sep_b.setObjectName("reportProgressSeparator")
        sep_c = QLabel("|")
        sep_c.setObjectName("reportProgressSeparator")

        self._bar = QProgressBar()
        self._bar.setObjectName("reportProgressTrack")
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 100000)
        self._bar.setValue(0)
        self._bar.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        self._percent_label = QLabel("0.000%")
        self._percent_label.setObjectName("reportProgressPercent")
        self._percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._percent_label.setMinimumWidth(74)
        self._eta_label = QLabel("0 ms")
        self._eta_label.setObjectName("reportProgressEta")
        self._eta_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._eta_label.setMinimumWidth(50)

        lay.addWidget(self._stage_label)
        lay.addWidget(sep_a)
        lay.addWidget(self._detail_label)
        lay.addWidget(sep_b)
        lay.addWidget(self._bar, stretch=1)
        lay.addWidget(self._percent_label)
        lay.addWidget(sep_c)
        lay.addWidget(self._eta_label)
        self.setToolTip("当前后台任务的阶段、百分比和预计剩余时间")
        self.reset_idle()

    def set_stage(self, stage: str) -> None:
        self._stage_label.setText(str(stage or "任务进度"))

    def begin(self, total: int, label: str, *, stage: str = "任务进度") -> None:
        self._started_at = time.perf_counter()
        self._busy = False
        self.set_stage(stage)
        self.setRange(0, max(1, int(total)))
        self.setValue(0)
        self.setFormat(label)
        self._timer.start()
        self.show()
        self._refresh_readout()

    def update_progress(
        self,
        value: int,
        total: int,
        label: str,
        *,
        stage: str | None = None,
    ) -> None:
        self._busy = False
        if stage is not None:
            self.set_stage(stage)
        self.setRange(0, max(1, int(total)))
        self.setValue(value)
        self.setFormat(label)
        self._timer.start()
        self.show()
        self._refresh_readout()

    def set_busy(self, label: str, *, stage: str | None = None) -> None:
        self._busy = True
        if stage is not None:
            self.set_stage(stage)
        self.setFormat(label)
        self._timer.start()
        self.show()
        self._refresh_readout()

    def finish(self, label: str, *, ok: bool, stage: str | None = None) -> None:
        self._busy = False
        if stage is not None:
            self.set_stage(stage)
        self.setRange(0, 100)
        self.setValue(100 if ok else 0)
        self.setFormat(label)
        self._refresh_readout()
        self._timer.stop()
        self.show()

    def reset_idle(self) -> None:
        self._busy = False
        self.set_stage("任务进度")
        self.setRange(0, 100)
        self.setValue(0)
        self.setFormat("待命")
        self._timer.stop()
        self._eta_label.setText("0 ms")
        self.show()

    def setRange(self, minimum: int, maximum: int) -> None:  # noqa: N802
        self._minimum = int(minimum)
        self._maximum = max(int(maximum), self._minimum)
        self._refresh_readout()

    def setValue(self, value: int) -> None:  # noqa: N802
        lo = self._minimum
        hi = self._maximum
        self._value = max(lo, min(int(value), hi))
        self._refresh_readout()

    def setFormat(self, label: str) -> None:  # noqa: N802
        self._format = str(label or "")
        self._detail_label.setText(self._detail_text(self._format))
        self._detail_label.setToolTip(self._format)
        self._refresh_readout()

    def minimum(self) -> int:
        return self._minimum

    def maximum(self) -> int:
        return self._maximum

    def value(self) -> int:
        return self._value

    def format(self) -> str:
        return self._format

    def percent_text(self) -> str:
        return self._percent_label.text()

    def eta_text(self) -> str:
        return self._eta_label.text()

    def detail_text(self) -> str:
        return self._detail_label.text()

    def stage_text(self) -> str:
        return self._stage_label.text()

    def is_busy(self) -> bool:
        return self._busy

    def _percent(self) -> float:
        span = self._maximum - self._minimum
        if span <= 0:
            return 0.0
        return 100.0 * (self._value - self._minimum) / span

    def _refresh_readout(self) -> None:
        percent = max(0.0, min(100.0, self._percent()))
        self._bar.setRange(0, 100000)
        self._bar.setValue(int(round(percent * 1000.0)))
        self._percent_label.setText(f"{percent:0.3f}%")
        if self._busy:
            self._eta_label.setText("--")
            return
        self._eta_label.setText(self._format_duration_ms(self._eta_ms(percent)))

    def _eta_ms(self, percent: float) -> float:
        if percent <= 0.0 or percent >= 100.0:
            return 0.0
        elapsed_ms = max(0.0, (time.perf_counter() - self._started_at) * 1000.0)
        return elapsed_ms * (100.0 - percent) / percent

    @staticmethod
    def _format_duration_ms(ms: float) -> str:
        if ms < 1000.0:
            return f"{int(round(ms))} ms"
        if ms < 60000.0:
            return f"{ms / 1000.0:.1f} s"
        minutes = int(ms // 60000.0)
        seconds = int(round((ms - minutes * 60000.0) / 1000.0))
        return f"{minutes}m {seconds}s"

    @staticmethod
    def _detail_text(label: str) -> str:
        text = str(label or "").strip()
        text = re.sub(r"[.。…]+$", "", text)
        replacements = (
            ("准备读取原始数据", "准备读取"),
            ("读取原始数据", "读取"),
            ("解析波形数据", "解析波形"),
            ("识别通道", "识别通道"),
            ("执行参数计算", "参数计算"),
            ("刷新界面", "刷新界面"),
            ("绘制波形", "绘制波形"),
            ("导入完成", "导入完成"),
            ("导入失败", "导入失败"),
            ("准备报告截图", "准备截图"),
            ("截图完成，准备写入 Excel", "准备写入 Excel"),
            ("正在写入 Excel", "写入 Excel"),
            ("写入完成 100%", "完成"),
            ("写入失败", "失败"),
        )
        for source, target in replacements:
            if text.startswith(source):
                return target
        return text or "待命"


def _configure_combo_popup(combo: QComboBox) -> None:
    apply_combo_popup_style(combo)


def _infer_temp_code_from_path(path: str) -> str:
    for part in reversed([p for p in re.split(r"[\\/]+", str(path)) if p]):
        stem = Path(part).stem.upper()
        for code in TEMP_CONDITION_DEFAULTS:
            if re.search(rf"(?<![A-Z0-9]){code}(?![A-Z0-9])", stem):
                return code
        if re.search(r"(?<!\d)25(?:℃|C|DEG)?(?!\d)", stem):
            return "RT"
        if re.search(r"(?<!\d)150(?:℃|C|DEG)?(?!\d)", stem):
            return "HT"
        if re.search(r"(?<!\d)-?40(?:℃|C|DEG)?(?!\d)", stem):
            return "LT"
    return "RT"


def commercial_authorization_message() -> str:
    return (
        "DPT 仅允许个人学习、研究、测试以及非商业组织使用。\n\n"
        "未经版权方书面授权，禁止任何商业使用，包括但不限于：\n"
        "1. 销售本软件、打包版或修改版；\n"
        "2. 集成到商业产品、商业服务或内部收费平台；\n"
        "3. 作为商业项目交付内容、外包成果或验收工具；\n"
        "4. 提供营利性托管、代运行、培训交付或商业目的再分发。\n\n"
        f"如需商业使用、商业集成或商务授权，请通过 QQ {COMMERCIAL_AUTH_QQ} 联系项目维护者。"
    )


@dataclass
class _WaveformLoadOutcome:
    path: str
    bundle: WaveformBundle
    guessed: BridgeProfile
    profile: BridgeProfile
    inferred: ChannelMapping | None
    inferred_source: str
    mapping_custom: bool
    result: ExtractResult | None
    short_circuit_not_ready: bool
    extraction_error: str
    load_ms: float
    extract_ms: float


def _profile_for_test_mode(profile: BridgeProfile, cfg: AppConfig) -> BridgeProfile:
    if parse_test_mode(cfg.test_mode.mode) == TestMode.SHORT_CIRCUIT:
        return as_short_circuit_profile(profile)
    return profile


@dataclass
class _AutoProfileCandidate:
    profile: BridgeProfile
    inferred: ChannelMapping | None
    inferred_source: str
    result: ExtractResult
    score: float


def _score_auto_dpt_profile(result: ExtractResult) -> float:
    score = 0.0
    if result.detected_pulse_count > 0:
        score += min(float(result.detected_pulse_count), 2.0)
    if abs(float(result.vdc)) > 20.0:
        score += 2.0
    ioff = abs(float(result.turn_off.ic_off_max))
    ion = abs(float(result.turn_on.turn_on_current))
    if ioff > 20.0:
        score += 2.0
        if ion > 20.0:
            rel = abs(ioff - ion) / max(ioff, ion, 1.0)
            score += max(0.0, 10.0 - 20.0 * rel)
            if (
                float(result.turn_off.ic_off_max) * float(result.turn_on.turn_on_current)
                >= 0.0
            ):
                score += 1.0
            else:
                score -= 4.0
        else:
            score -= 10.0
    else:
        score -= 4.0
    if result.turn_off.eoff > 0.01:
        score += 1.0
    if result.turn_on.eon > 0.01:
        score += 1.0
    if result.reverse_recovery.err > 0.01:
        score += 0.5
    if result.single_pulse_mode:
        score -= 2.0
    return score


def _auto_dpt_profile_candidate(
    bundle: WaveformBundle,
    cfg: AppConfig,
    phase: str,
    bridge: str,
) -> _AutoProfileCandidate | None:
    base_profile = make_profile(phase, bridge)
    inferred, inferred_source = infer_best_mapping_from_bundle(bundle, bridge)
    profile = apply_mapping(base_profile, inferred) if inferred is not None else base_profile
    try:
        result = run_extraction(bundle, profile, cfg)
    except Exception:  # noqa: BLE001
        return None
    return _AutoProfileCandidate(
        profile=profile,
        inferred=inferred,
        inferred_source=inferred_source,
        result=result,
        score=_score_auto_dpt_profile(result),
    )


def _select_ambiguous_bridge_dpt_profile(
    path: str,
    bundle: WaveformBundle,
    cfg: AppConfig,
    guessed: BridgeProfile,
) -> _AutoProfileCandidate | None:
    if has_bridge_hint_from_path(path):
        return None
    candidates: list[_AutoProfileCandidate] = []
    bridges = [guessed.bridge, "lower" if guessed.bridge == "upper" else "upper"]
    for bridge in dict.fromkeys(bridges):
        candidate = _auto_dpt_profile_candidate(bundle, cfg, guessed.phase, bridge)
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.score)


def _compute_waveform_load_outcome(
    path: str,
    cfg: AppConfig,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> _WaveformLoadOutcome:
    def emit_progress(value: int, label: str) -> None:
        if progress_callback is not None:
            progress_callback(value, TASK_PROGRESS_TOTAL, label)

    emit_progress(0, "读取原始数据...")
    load_t0 = time.perf_counter()
    bundle = load_waveform(path)
    load_t1 = time.perf_counter()
    emit_progress(LOAD_PROGRESS_PARSE_DONE, "解析波形数据...")

    guessed = guess_profile_from_path(path)
    base_profile = make_profile(guessed.phase, guessed.bridge)
    custom_mapping = ChannelMappingStore().get(
        guessed.phase,
        guessed.bridge,
        source_path=bundle.meta.source_path or path,
    )
    mapping_custom = custom_mapping is not None
    profile = (
        apply_mapping(base_profile, custom_mapping)
        if custom_mapping is not None
        else base_profile
    )
    inferred = None
    inferred_source = ""
    mode = parse_test_mode(cfg.test_mode.mode)
    if custom_mapping is None:
        if mode == TestMode.SHORT_CIRCUIT:
            inferred = infer_short_circuit_mapping_from_bundle(bundle, guessed.bridge)
            inferred_source = "label" if inferred is not None else ""
            if inferred is not None:
                profile = apply_mapping(as_short_circuit_profile(base_profile), inferred)
            else:
                profile = as_short_circuit_profile(profile)
        else:
            inferred, inferred_source = infer_best_mapping_from_bundle(
                bundle,
                guessed.bridge,
            )
            if inferred is not None:
                profile = apply_mapping(base_profile, inferred)
    else:
        profile = _profile_for_test_mode(profile, cfg)
    emit_progress(55000, "识别通道...")

    extract_t0 = time.perf_counter()
    extraction_error = ""
    try:
        if mode == TestMode.OFFSET_MEASUREMENT:
            result = None
            short_circuit_not_ready = False
        elif mode == TestMode.DPT and custom_mapping is None:
            selected = _select_ambiguous_bridge_dpt_profile(path, bundle, cfg, guessed)
            if selected is not None:
                profile = selected.profile
                inferred = selected.inferred
                inferred_source = selected.inferred_source
                result = selected.result
            else:
                result = run_extraction(bundle, profile, cfg)
            short_circuit_not_ready = False
        else:
            result = run_extraction(bundle, profile, cfg)
            short_circuit_not_ready = False
    except Exception as exc:
        result = None
        short_circuit_not_ready = False
        extraction_error = str(exc) or exc.__class__.__name__
    extract_t1 = time.perf_counter()
    emit_progress(LOAD_PROGRESS_EXTRACT_DONE, "执行参数计算...")

    return _WaveformLoadOutcome(
        path=path,
        bundle=bundle,
        guessed=guessed,
        profile=profile,
        inferred=inferred,
        inferred_source=inferred_source,
        mapping_custom=mapping_custom,
        result=result,
        short_circuit_not_ready=short_circuit_not_ready,
        extraction_error=extraction_error,
        load_ms=(load_t1 - load_t0) * 1000.0,
        extract_ms=(extract_t1 - extract_t0) * 1000.0,
    )


class _WaveformLoadSignals(QObject):
    progress = pyqtSignal(int, int, int, str)
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
                progress_callback=lambda value, total, label: self.signals.progress.emit(
                    self.request_id,
                    value,
                    total,
                    label,
                ),
            )
        except Exception as exc:
            self.signals.failed.emit(self.request_id, self.path, str(exc))
            return
        self.signals.finished.emit(self.request_id, outcome)


class _ReportWriteSignals(QObject):
    progress = pyqtSignal(int, int, int, str)
    finished = pyqtSignal(int, object, float)
    failed = pyqtSignal(int, str)


@dataclass
class _ReportCaptureState:
    request_id: int
    tempdir: tempfile.TemporaryDirectory
    directory: Path
    params: tuple[tuple[str, str], ...]
    results: list[ExtractResult]
    old_x: list[float]
    old_y: list[float]
    capture_start: int
    capture_span: int
    capture_size: QSize
    index: int = 0
    images: dict[tuple[str, str], Path] | None = None


class _ReportWriteTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        result: ExtractResult | list[ExtractResult],
        report_path: Path,
        images: dict[tuple[str, str], Path],
        tempdir: tempfile.TemporaryDirectory,
        target_screen_width_px: int | None,
        temperature_labels: dict[str, str],
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.result = result
        self.report_path = report_path
        self.images = images
        self.tempdir = tempdir
        self.target_screen_width_px = target_screen_width_px
        self.temperature_labels = dict(temperature_labels)
        self.signals = _ReportWriteSignals()

    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            summary = write_report_template(
                self.result,
                self.report_path,
                images=self.images,
                target_screen_width_px=self.target_screen_width_px,
                temperature_labels=self.temperature_labels,
                progress_callback=lambda value, total, label: self.signals.progress.emit(
                    self.request_id,
                    value,
                    total,
                    label,
                ),
            )
        except PermissionError as exc:
            self.signals.failed.emit(
                self.request_id,
                "无法保存报告文件，通常是这个 .xlsx 正在被 Excel 打开或没有写入权限。\n"
                "请先关闭该报告文件，再点击“写入报告”。\n\n"
                f"文件:\n{self.report_path}\n\n"
                f"错误:\n{exc}",
            )
            return
        except Exception as exc:
            self.signals.failed.emit(self.request_id, str(exc))
            return
        finally:
            self.tempdir.cleanup()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.signals.finished.emit(self.request_id, summary, elapsed_ms)


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
        self._report_template_source_path: Path | None = report_template_source_path()
        self._report_output_path: Path | None = report_output_path()
        self._channel_store = ChannelMappingStore()
        self._mapping_custom = False
        self._slope_ranges = default_slope_ranges()
        self.cfg.short_circuit_tsc_range = self._load_short_circuit_tsc_range()
        # 记忆每个参数手动调整的光标区间（µs），再次点击时恢复而非回退默认窗口
        self._manual_intervals: dict[tuple[str, str], tuple[float, float]] = {}
        # Maximum 类参数：保存用户手动拖动的主横向光标值 (line_value, metric_value)
        self._manual_extreme_values: dict[tuple[str, str], tuple[float, float]] = {}
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
        self._offset_measurements: list[tuple[str, str, str]] = []
        self._offset_cursor_window_us: tuple[float, float] | None = None
        self._offset_cursor_waveform_source: str = ""
        self._pre_offset_cursor_type: str | None = None
        self._pre_offset_cursor_linked: bool | None = None
        self._active_slope_param: tuple[str, str] | None = None
        self._load_request_id = 0
        self._load_tasks: dict[int, _WaveformLoadTask] = {}
        self._report_request_id = 0
        self._report_tasks: dict[int, _ReportWriteTask] = {}
        self._report_capture_state: _ReportCaptureState | None = None
        self._report_progress_active = False
        self._load_pool = QThreadPool.globalInstance()
        self._license_notice_dialog: QDialog | None = None
        self._license_notice_timer = QTimer(self)
        self._license_notice_timer.setSingleShot(True)
        self._license_notice_timer.timeout.connect(self._show_first_run_license_notice)
        self._temperature_values = self._load_temperature_values()

        self._build_ui()
        self.result_table.set_range_handler(self._on_slope_range_changed)
        self.result_table.set_short_circuit_tsc_range_handler(
            self._on_short_circuit_tsc_range_changed
        )
        self.result_table.set_eoff_pre_handler(self._on_eoff_pre_changed)
        self.result_table.set_value_click_handler(self._on_value_clicked)
        self.result_table.set_offset_measurement_add_handler(
            self._on_offset_measurement_add_requested
        )
        self.result_table.set_offset_measurement_delete_handler(
            self._on_offset_measurement_delete_requested,
            self._on_offset_measurement_delete_all_requested,
        )
        self.result_table.set_offset_measurement_update_handler(
            self._on_offset_measurement_update_requested
        )
        self.result_table.set_slope_ranges(self._slope_ranges)
        # 持久 A/B 光标：global 模式拖动时显示测量读数；横向 Ha/Hb 同步
        self.wave_plot.set_global_cursor_handler(self._on_global_cursors_moved)
        self.wave_plot.set_horizontal_cursor_handler(self._on_horizontal_cursors_moved)
        self.wave_plot.set_view_range_handler(self._on_waveform_view_range_changed)
        self.wave_plot.channelMappingRequested.connect(
            self._on_waveform_channel_mapping_requested
        )
        self.wave_plot.channelLabelChanged.connect(
            self._on_waveform_channel_label_changed
        )
        self.wave_plot.channelUnitChanged.connect(
            self._on_waveform_channel_unit_changed
        )
        self.wave_plot.channelInversionChanged.connect(
            self._on_waveform_channel_inversion_changed
        )
        self._license_notice_timer.start(0)

    def _build_ui(self) -> None:
        self.wave_plot = WaveformPlot()

        self.toolbar = QFrame()
        self.toolbar.setObjectName("toolbar")
        tb_root = QVBoxLayout(self.toolbar)
        tb_root.setContentsMargins(6, 4, 6, 5)
        tb_root.setSpacing(4)

        self.lbl_current_file = QLabel("未加载文件")
        self.lbl_current_file.setObjectName("currentFileTitle")
        self.lbl_current_file.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.lbl_current_file.setSizePolicy(
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Fixed,
        )
        self.lbl_current_file.setToolTip("待处理数据原始文件名")
        self.lbl_top_status = QLabel("请打开 Tektronix TSS 会话文件")
        self.lbl_top_status.setObjectName("topStatusInfo")
        self.lbl_top_status.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.lbl_top_status.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.report_progress = ReportProgressPanel()
        self.report_progress.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        self.btn_open = QPushButton("打开文件")
        self.btn_open.setObjectName("primaryButton")
        self.btn_open.setToolTip("支持 Tektronix TSS 会话文件")
        self.btn_open.clicked.connect(self._open_waveform)

        self.combo_phase = CenteredComboBox()
        self.combo_phase.setMinimumContentsLength(4)
        for p in PHASES:
            self.combo_phase.addItem(f"{p}相", p)
        _configure_combo_popup(self.combo_phase)
        self.combo_phase.currentIndexChanged.connect(self._on_phase_bridge_changed)

        self.combo_bridge = CenteredComboBox()
        self.combo_bridge.setMinimumContentsLength(4)
        self.combo_bridge.addItem("上桥", "upper")
        self.combo_bridge.addItem("下桥", "lower")
        _configure_combo_popup(self.combo_bridge)
        self.combo_bridge.currentIndexChanged.connect(self._on_phase_bridge_changed)

        self.combo_temp = CenteredComboBox()
        self.combo_temp.setObjectName("tempSelector")
        for code in TEMP_CONDITION_DEFAULTS:
            self.combo_temp.addItem(code, code)
        _configure_combo_popup(self.combo_temp)
        self.combo_temp.setToolTip("工况温度标记，仅用于界面显示")
        self.combo_temp.currentIndexChanged.connect(self._on_temperature_changed)

        self.spin_temp_value = TemperatureSpinBox()
        self.spin_temp_value.setObjectName("tempValue")
        self.spin_temp_value.setRange(-100.0, 250.0)
        self.spin_temp_value.setDecimals(1)
        self.spin_temp_value.setSingleStep(1.0)
        self.spin_temp_value.setSuffix(" ℃")
        self.spin_temp_value.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spin_temp_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_temp_value.setToolTip("自定义当前温度数值，单位固定为 ℃")
        self.spin_temp_value.setValue(self._temperature_values["RT"])
        self.spin_temp_value.valueChanged.connect(self._on_temperature_value_changed)

        self.btn_recalc = QPushButton("重新计算")
        self.btn_recalc.setToolTip("按当前设置重新计算全部参数")
        self.btn_recalc.clicked.connect(lambda: self._recalculate(reset_manual=True))
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setToolTip("导出当前结果到 Excel")
        self.btn_export.clicked.connect(self._export_excel)
        self.btn_select_report_template = QPushButton("加载模板")
        self.btn_select_report_template.clicked.connect(self._select_report_template)
        self.btn_select_report_output = QPushButton("报告位置")
        self.btn_select_report_output.clicked.connect(self._select_report_output_path)
        self.btn_write_report = QPushButton("写入报告")
        self.btn_write_report.setObjectName("accentButton")
        self.btn_write_report.setToolTip("将当前结果写入已设置的项目报告文件")
        self.btn_write_report.clicked.connect(self._write_report_template)
        self._update_report_template_tooltip()
        self._update_report_output_tooltip()

        self.lbl_map_status = QLabel("")
        self.lbl_map_status.setStyleSheet("color:#f9e2af;font-size:11px;")
        self.lbl_map_status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )

        row_title = QHBoxLayout()
        row_title.setSpacing(6)
        row_title.addWidget(self.lbl_current_file)
        row_title.addWidget(self.lbl_top_status, stretch=3)
        row_title.addWidget(self.report_progress, stretch=2)

        row_controls = QHBoxLayout()
        row_controls.setSpacing(5)
        row_controls.addWidget(self.btn_open)
        self.lbl_phase = QLabel("相别")
        row_controls.addWidget(self.lbl_phase)
        row_controls.addWidget(self.combo_phase)
        self.lbl_bridge = QLabel("桥臂")
        row_controls.addWidget(self.lbl_bridge)
        row_controls.addWidget(self.combo_bridge)
        self.lbl_temp = QLabel("温度")
        row_controls.addWidget(self.lbl_temp)
        row_controls.addWidget(self.combo_temp)
        row_controls.addWidget(self.spin_temp_value)
        row_controls.addWidget(self.lbl_map_status, stretch=1)
        row_controls.addWidget(self.btn_recalc)
        row_controls.addWidget(self.btn_export)
        row_controls.addWidget(self.btn_select_report_template)
        row_controls.addWidget(self.btn_select_report_output)
        row_controls.addWidget(self.btn_write_report)
        self.lbl_test_mode = QLabel("测试模式")
        self.lbl_test_mode.setObjectName("testModeTitle")
        self.lbl_test_mode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.combo_test_mode = CenteredComboBox()
        self.combo_test_mode.setObjectName("testModeSelector")
        for mode in (
            TestMode.DPT,
            TestMode.SHORT_CIRCUIT,
            TestMode.OFFSET_MEASUREMENT,
        ):
            self.combo_test_mode.addItem(MODE_UI_LABELS[mode], mode.value)
        _configure_combo_popup(self.combo_test_mode)
        idx = self.combo_test_mode.findData(
            parse_test_mode(self.cfg.test_mode.mode).value
        )
        if idx >= 0:
            self.combo_test_mode.setCurrentIndex(idx)
        self.combo_test_mode.setMinimumContentsLength(8)
        self.combo_test_mode.setMaximumWidth(112)
        self.combo_test_mode.setToolTip("双脉冲、短路与偏移测量使用独立流程")
        self.combo_test_mode.currentIndexChanged.connect(self._on_test_mode_changed)

        pulse_sep = QFrame()
        pulse_sep.setFrameShape(QFrame.Shape.VLine)
        pulse_sep.setStyleSheet("color:#45475a;")

        self.lbl_pulse_count = QLabel("共 -- 波")
        self.lbl_pulse_count.setObjectName("pulseCount")
        self.lbl_pulse_count.setStyleSheet("color:#a6adc8;font-size:11px;")

        self.lbl_off_pulse = QLabel("关断")
        self.lbl_off_pulse.setObjectName("calcBadge")
        self.spin_off_pulse = PulseComboBox()
        self.spin_off_pulse.setObjectName("pulseSelector")
        self.spin_off_pulse.setRange(1, 10)
        self.spin_off_pulse.setValue(self.cfg.pulse_selection.off_pulse)
        self.spin_off_pulse.setFixedWidth(92)
        _configure_combo_popup(self.spin_off_pulse)
        self.spin_off_pulse.setToolTip("取第 N 个门极脉冲的关断沿")

        self.lbl_on_pulse = QLabel("开通")
        self.lbl_on_pulse.setObjectName("calcBadge")
        self.spin_on_pulse = PulseComboBox()
        self.spin_on_pulse.setObjectName("pulseSelector")
        self.spin_on_pulse.setRange(1, 10)
        self.spin_on_pulse.setValue(self.cfg.pulse_selection.on_pulse)
        self.spin_on_pulse.setFixedWidth(92)
        _configure_combo_popup(self.spin_on_pulse)
        self.spin_on_pulse.setToolTip(
            "取第 N 个门极脉冲的开通沿；可与关断同波（分析该脉冲的开通与关断）"
        )

        self.spin_off_pulse.valueChanged.connect(self._on_pulse_spin_changed)
        self.spin_on_pulse.valueChanged.connect(self._on_pulse_spin_changed)

        self.context_menu_selector = self._build_context_menu_selector()
        self.param_calc_group = self._build_parameter_calc_group()
        self.test_mode_group = self._build_test_mode_group()

        self._pulse_toolbar_widgets = (
            self.param_calc_group,
            self.lbl_pulse_count,
            self.lbl_off_pulse,
            self.spin_off_pulse,
            self.lbl_on_pulse,
            self.spin_on_pulse,
        )

        row_tools = QHBoxLayout()
        row_tools.setSpacing(5)
        row_tools_left = QHBoxLayout()
        row_tools_left.setContentsMargins(0, 0, 0, 0)
        row_tools_left.setSpacing(5)
        row_tools_left.addWidget(self.context_menu_selector)
        row_tools_left.addWidget(
            self.param_calc_group,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        row_tools_left.addStretch(1)

        row_tools_right = QHBoxLayout()
        row_tools_right.setContentsMargins(0, 0, 0, 0)
        row_tools_right.setSpacing(5)
        row_tools_right.addStretch(1)
        row_tools_right.addWidget(
            self.test_mode_group,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

        row_tools.addLayout(row_tools_left, stretch=0)
        row_tools.addLayout(row_tools_right, stretch=1)

        self._toolbar_rows = (row_title, row_controls, row_tools)
        self._toolbar_tool_sections = (
            row_tools_left,
            row_tools_right,
        )
        self._toolbar_density_bucket: str | None = None
        self._toolbar_text_mode: str | None = None

        tb_root.addLayout(row_title)
        tb_root.addLayout(row_controls)
        tb_root.addLayout(row_tools)

        self.result_table = ResultTable()
        self.result_table.set_temperature_labels(self._temperature_display_labels())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("mainSplitter")
        self.splitter.addWidget(self.wave_plot)
        self.splitter.addWidget(self.result_table)
        self.splitter.setStretchFactor(0, 5)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setHandleWidth(8)
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
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(self.toolbar)
        layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(root)
        self._status_bar = QStatusBar()
        self._status_bar.messageChanged.connect(self._on_status_message_changed)
        self.setStatusBar(self._status_bar)
        self._status_bar.hide()
        self.statusBar().showMessage("请打开 Tektronix TSS 会话文件")
        self._apply_toolbar_density(self.width() or 1400)
        self._apply_test_mode_ui()

    def _on_status_message_changed(self, message: str) -> None:
        if not hasattr(self, "lbl_top_status"):
            return
        text = self._top_status_display_text(message)
        self.lbl_top_status.setText(text)
        self.lbl_top_status.setToolTip(message or text)

    def _top_status_display_text(self, message: str) -> str:
        text = str(message or "").strip()
        if not text:
            return "就绪"
        file_name = Path(self._current_path).name if self._current_path else ""
        if file_name:
            for prefix in (
                f"已加载: {file_name}  |  ",
                f"已加载: {file_name} | ",
                f"正在后台加载: {file_name}",
            ):
                if text.startswith(prefix):
                    stripped = text[len(prefix) :].strip()
                    return stripped or text
        return text

    def _license_settings(self) -> QSettings:
        return QSettings("DPT", "DPTExtractor")

    def _should_show_license_notice(self) -> bool:
        raw = self._license_settings().value(
            NONCOMMERCIAL_NOTICE_SETTINGS_KEY, False, type=bool
        )
        return not bool(raw)

    def _mark_license_notice_shown(self) -> None:
        self._license_settings().setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, True)

    def _load_temperature_values(self) -> dict[str, float]:
        settings = QSettings("DPT", "DPTExtractor")
        values = dict(TEMP_CONDITION_DEFAULTS)
        for code, default in TEMP_CONDITION_DEFAULTS.items():
            raw = settings.value(f"{TEMP_CONDITION_SETTINGS_PREFIX}{code}", default)
            try:
                values[code] = float(raw)
            except (TypeError, ValueError):
                values[code] = float(default)
        return values

    def _load_short_circuit_tsc_range(self) -> str:
        raw = QSettings("DPT", "DPTExtractor").value(
            SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY,
            SHORT_CIRCUIT_TSC_RANGE_DEFAULT,
        )
        _start, _end, normalized = short_circuit_tsc_range_percentages(str(raw))
        return normalized

    def _save_short_circuit_tsc_range(self, label: str) -> str:
        _start, _end, normalized = short_circuit_tsc_range_percentages(label)
        QSettings("DPT", "DPTExtractor").setValue(
            SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY,
            normalized,
        )
        return normalized

    def _save_temperature_value(self, code: str, value: float) -> None:
        if code not in TEMP_CONDITION_DEFAULTS:
            return
        QSettings("DPT", "DPTExtractor").setValue(
            f"{TEMP_CONDITION_SETTINGS_PREFIX}{code}",
            float(value),
        )

    def _temperature_display_labels(self) -> dict[str, str]:
        return {
            code: _format_temperature_label(value)
            for code, value in self._temperature_values.items()
        }

    def _show_first_run_license_notice(self) -> None:
        app = QApplication.instance()
        if app is not None and app.platformName().lower() == "offscreen":
            return
        if not self._should_show_license_notice():
            return
        self._mark_license_notice_shown()
        self._show_license_notice(blocking=False)

    def _show_license_notice(self, *, blocking: bool = True) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(NONCOMMERCIAL_NOTICE_TITLE)
        dlg.setModal(True)
        dlg.setMinimumWidth(820)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        poster = QPixmap(str(commercial_notice_poster_path()))
        if not poster.isNull():
            poster_label = QLabel()
            poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            poster_label.setPixmap(
                poster.scaledToWidth(
                    780,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            poster_label.setStyleSheet(
                "background:#07111d;border:1px solid #28bce8;border-radius:8px;"
            )
            layout.addWidget(poster_label)
        else:
            title = QLabel(NONCOMMERCIAL_NOTICE_TITLE)
            title.setStyleSheet("font-size:18px;font-weight:700;color:#f9e2af;")
            layout.addWidget(title)

            body = QLabel(commercial_authorization_message())
            body.setWordWrap(True)
            body.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            body.setStyleSheet("line-height:1.35;color:#f5f5f5;")
            layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("OK")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
            "font-family:Arial;font-size:13px;min-width:64px;"
        )
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        if blocking:
            dlg.exec()
        else:
            dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._license_notice_dialog = dlg
            dlg.finished.connect(
                lambda _result: setattr(self, "_license_notice_dialog", None)
            )
            dlg.open()

    def _build_context_menu_selector(self) -> QWidget:
        box = QFrame()
        box.setObjectName("contextMenuSelector")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(4)

        label = QLabel("功能菜单")
        label.setObjectName("contextMenuSelectorLabel")
        self._context_menu_label = label
        label.setVisible(False)

        self._context_menu_buttons: list[QPushButton] = []
        for text, key in (
            ("光标", "cursor"),
            ("缩放", "zoom"),
        ):
            btn = QPushButton(text)
            btn.setObjectName("contextMenuSelectorButton")
            btn.setCheckable(True)
            if key == "cursor":
                btn.setChecked(self.wave_plot.cursor_switch_enabled())
                btn.clicked.connect(
                    lambda checked=False: self.wave_plot.set_cursor_switch_enabled(
                        checked
                    )
                )
                self.wave_plot.cursorVisibilityChanged.connect(
                    lambda enabled, button=btn: self._set_toolbar_button_checked(
                        button, enabled
                    )
                )
            else:
                btn.setChecked(self.wave_plot.selection_zoom_switch_enabled())
                btn.clicked.connect(
                    lambda checked=False: self.wave_plot.set_selection_zoom_switch_enabled(
                        checked
                    )
                )
                self.wave_plot.selectionZoomChanged.connect(
                    lambda enabled, button=btn: self._set_toolbar_button_checked(
                        button, enabled
                    )
                )
            lay.addWidget(btn)
            self._context_menu_buttons.append(btn)
        return box

    @staticmethod
    def _set_toolbar_button_checked(button: QPushButton, checked: bool) -> None:
        button.blockSignals(True)
        try:
            button.setChecked(bool(checked))
        finally:
            button.blockSignals(False)

    def _build_parameter_calc_group(self) -> QWidget:
        box = QFrame()
        box.setObjectName("paramCalcGroup")
        box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(box)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        title = QLabel("参数计算")
        title.setObjectName("paramCalcTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_param_calc_title = title
        for widget in (
            title,
            self.lbl_pulse_count,
            self.lbl_off_pulse,
            self.spin_off_pulse,
            self.lbl_on_pulse,
            self.spin_on_pulse,
        ):
            lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        return box

    def _build_test_mode_group(self) -> QWidget:
        box = QFrame()
        box.setObjectName("testModeGroup")
        box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(box)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        for widget in (self.lbl_test_mode, self.combo_test_mode):
            lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        return box

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_toolbar_density(event.size().width())
        self._sync_splitter_sizes()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._license_notice_timer.isActive():
            self._license_notice_timer.stop()
        if self._license_notice_dialog is not None:
            self._license_notice_dialog.close()
            self._license_notice_dialog = None
        super().closeEvent(event)

    def _apply_toolbar_density(self, window_width: int) -> None:
        """Keep the top controls legible without letting them overrun small screens."""
        if not hasattr(self, "toolbar"):
            return
        if window_width < 900:
            bucket = "tiny"
            font_px = 10
            label_px = 10
            min_h = 22
            pad_v = 1
            pad_h = 6
            spacing = 3
            test_w = 96
            context_min_w = 38
            context_pad_h = 5
            file_w = 260
            phase_w = 64
            bridge_w = 68
            temp_w = 0
            temp_value_w = 0
            pulse_w = 70
            show_temp = False
            show_context_label = False
            show_map_status = False
            text_mode = "tiny"
        elif window_width < 1180:
            bucket = "compact"
            font_px = 11
            label_px = 11
            min_h = 24
            pad_v = 1
            pad_h = 7
            spacing = 4
            test_w = 104
            context_min_w = 44
            context_pad_h = 7
            file_w = 360
            phase_w = 68
            bridge_w = 72
            temp_w = 0
            temp_value_w = 0
            pulse_w = 82
            show_temp = False
            show_context_label = False
            show_map_status = False
            text_mode = "compact"
        elif window_width < 1500:
            bucket = "medium"
            font_px = 12
            label_px = 12
            min_h = 25
            pad_v = 1
            pad_h = 9
            spacing = 4
            test_w = 108
            context_min_w = 48
            context_pad_h = 8
            file_w = 520
            phase_w = 72
            bridge_w = 78
            temp_w = 64
            temp_value_w = 70
            pulse_w = 92
            show_temp = True
            show_context_label = True
            show_map_status = True
            text_mode = "medium"
        else:
            bucket = "full"
            font_px = 13
            label_px = 12
            min_h = 26
            pad_v = 1
            pad_h = 11
            spacing = 5
            test_w = 112
            context_min_w = 52
            context_pad_h = 10
            file_w = 760
            phase_w = 78
            bridge_w = 84
            temp_w = 68
            temp_value_w = 72
            pulse_w = 96
            show_temp = True
            show_context_label = True
            show_map_status = True
            text_mode = "full"

        control_h = min_h + 8
        param_control_h = max(22, min_h + 2)
        param_group_h = param_control_h + 8
        title_h = max(24, control_h - 4)
        group_h = control_h + 4
        test_mode_title_w = (
            64 if text_mode == "tiny" else 70 if text_mode == "compact" else 76
        )
        test_mode_group_w = test_mode_title_w + test_w + 12
        param_badge_min_w = 42 if text_mode in {"tiny", "compact"} else 46
        param_pulse_w = max(62, pulse_w - 18)
        param_pulse_min_h = max(18, param_control_h - 2)

        if self._toolbar_text_mode != text_mode:
            if text_mode == "tiny":
                self.btn_open.setText("打开")
                self.btn_recalc.setText("重算")
                self.btn_export.setText("导出")
                self.btn_select_report_template.setText("模板")
                self.btn_select_report_output.setText("位置")
                self.btn_write_report.setText("写入")
            elif text_mode == "compact":
                self.btn_open.setText("打开文件")
                self.btn_recalc.setText("重算")
                self.btn_export.setText("导出")
                self.btn_select_report_template.setText("模板")
                self.btn_select_report_output.setText("位置")
                self.btn_write_report.setText("写报告")
            elif text_mode == "medium":
                self.btn_open.setText("打开文件")
                self.btn_recalc.setText("重新计算")
                self.btn_export.setText("导出 Excel")
                self.btn_select_report_template.setText("加载模板")
                self.btn_select_report_output.setText("报告位置")
                self.btn_write_report.setText("写入报告")
            else:
                self.btn_open.setText("打开文件")
                self.btn_recalc.setText("重新计算")
                self.btn_export.setText("导出 Excel")
                self.btn_select_report_template.setText("加载模板")
                self.btn_select_report_output.setText("报告位置")
                self.btn_write_report.setText("写入报告")
            short_menu = text_mode in {"tiny", "compact"}
            menu_labels = (
                ("光", "缩")
                if short_menu
                else ("光标", "缩放")
            )
            for btn, label in zip(self._context_menu_buttons, menu_labels):
                btn.setText(label)
            self._toolbar_text_mode = text_mode

        if self._toolbar_density_bucket == bucket:
            return
        self._toolbar_density_bucket = bucket

        for row in self._toolbar_rows + self._toolbar_tool_sections:
            row.setSpacing(spacing)
            row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.lbl_current_file.setMaximumWidth(file_w)
        self.lbl_current_file.setMinimumWidth(min(file_w, 220))
        self.lbl_current_file.setFixedHeight(title_h)
        self.lbl_top_status.setMinimumWidth(120)
        self.lbl_top_status.setFixedHeight(title_h)
        self.report_progress.setMinimumWidth(250 if window_width < 1180 else 360)
        self.report_progress.setMaximumWidth(520 if window_width < 1500 else 760)
        self.report_progress.setFixedHeight(title_h)
        self.combo_phase.setFixedWidth(phase_w)
        self.combo_bridge.setFixedWidth(bridge_w)
        self.spin_off_pulse.setFixedWidth(param_pulse_w)
        self.spin_on_pulse.setFixedWidth(param_pulse_w)
        for w in (
            self.btn_open,
            self.btn_recalc,
            self.btn_export,
            self.btn_select_report_template,
            self.btn_select_report_output,
            self.btn_write_report,
            self.combo_phase,
            self.combo_bridge,
            self.spin_temp_value,
        ):
            w.setFixedHeight(control_h)
        for label in (
            self.lbl_phase,
            self.lbl_bridge,
            self.lbl_temp,
            self.lbl_test_mode,
            self.lbl_pulse_count,
            self.lbl_off_pulse,
            self.lbl_on_pulse,
        ):
            label.setMinimumHeight(control_h)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.context_menu_selector.setFixedHeight(group_h)
        self.param_calc_group.setFixedHeight(param_group_h)
        for widget in (
            self.lbl_param_calc_title,
            self.lbl_pulse_count,
            self.lbl_off_pulse,
            self.lbl_on_pulse,
            self.spin_off_pulse,
            self.spin_on_pulse,
        ):
            widget.setFixedHeight(param_control_h)
            widget.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
        self.test_mode_group.setFixedSize(test_mode_group_w, param_group_h)
        self.lbl_test_mode.setFixedWidth(test_mode_title_w)
        self.combo_test_mode.setFixedWidth(test_w)
        for widget in (self.lbl_test_mode, self.combo_test_mode):
            widget.setFixedHeight(param_control_h)
            widget.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
        self.lbl_param_calc_title.setVisible(text_mode != "tiny")
        self.lbl_temp.setVisible(show_temp)
        self.combo_temp.setVisible(show_temp)
        self.spin_temp_value.setVisible(show_temp)
        if show_temp:
            self.combo_temp.setFixedWidth(temp_w)
            self.combo_temp.setFixedHeight(control_h)
            self.spin_temp_value.setFixedWidth(temp_value_w)
        self.lbl_map_status.setVisible(show_map_status)
        self._context_menu_label.setVisible(False)

        self.toolbar.setStyleSheet(
            f"""
            QFrame#toolbar {{
                background-color: #071113;
                border: 2px solid #28464c;
                border-radius: 8px;
            }}
            QFrame#toolbar QLabel {{
                background: transparent;
                font-size: {label_px}px;
            }}
            QFrame#toolbar QLabel#appTitle {{
                color: #f2f7f1;
                background: transparent;
                font-size: {font_px + 4}px;
                font-weight: 800;
                padding: 2px 8px;
            }}
            QFrame#toolbar QLabel#currentFileTitle {{
                color: #edf6ee;
                background: #0b1719;
                border: 1px solid #33545b;
                border-radius: 6px;
                font-family: "Cascadia Mono", Consolas, monospace;
                font-size: {font_px + 3}px;
                font-weight: 800;
                padding: 3px 10px;
            }}
            QFrame#toolbar QLabel#topStatusInfo {{
                color: #aebcc3;
                background: #10151d;
                border: 1px solid #2d3b4b;
                border-radius: 6px;
                font-family: "Cascadia Mono", Consolas, "Microsoft YaHei UI", monospace;
                font-size: {label_px}px;
                padding: 3px 10px;
            }}
            QFrame#toolbar QPushButton {{
                background-color: #243036;
                color: #e4ecea;
                border: 1px solid #385057;
                border-radius: 6px;
                font-size: {font_px}px;
                padding: 0 {pad_h}px;
                min-height: {min_h}px;
                text-align: center;
            }}
            QFrame#toolbar QPushButton:hover {{
                background-color: #2e4148;
                border-color: #4c727a;
            }}
            QFrame#toolbar QPushButton#primaryButton {{
                background-color: #24c3d9;
                border-color: #5ee6f4;
                color: #061014;
                font-weight: 800;
            }}
            QFrame#toolbar QPushButton#accentButton {{
                background-color: #f4b64b;
                border-color: #f6d36b;
                color: #12100a;
                font-weight: 800;
            }}
            QFrame#toolbar QComboBox,
            QFrame#toolbar QSpinBox,
            QFrame#toolbar QDoubleSpinBox {{
                background-color: #102225;
                color: #e5efec;
                border: 1px solid #3d5960;
                border-radius: 6px;
                font-size: {font_px}px;
                padding: 0 {max(5, pad_h - 2)}px;
                min-height: {min_h}px;
            }}
            QFrame#toolbar QComboBox QAbstractItemView {{
                background-color: #081719;
                color: #edf6ee;
                selection-background-color: #28bce8;
                selection-color: #061014;
                border: 1px solid #5a8b93;
                outline: 0;
            }}
            QFrame#toolbar QComboBox QAbstractItemView::item {{
                color: #edf6ee;
                min-height: 26px;
                padding: 5px 9px;
            }}
            QFrame#toolbar QComboBox#tempSelector {{
                border-color: #315b5f;
                font-weight: 700;
            }}
            QFrame#toolbar QDoubleSpinBox#tempValue {{
                background-color: #172018;
                color: #f2d45c;
                border: 1px solid #6b5b23;
                border-radius: 6px;
                font-size: {font_px}px;
                font-weight: 800;
                padding: 0 {max(5, pad_h - 4)}px;
                min-height: {min_h}px;
            }}
            QFrame#toolbar QFrame#paramCalcGroup {{
                background:#0c1515;
                border:1px solid #5d5128;
                border-radius:10px;
            }}
            QFrame#toolbar QFrame#testModeGroup {{
                background:#0c1515;
                border:1px solid #5d5128;
                border-radius:10px;
            }}
            QFrame#toolbar QLabel#paramCalcTitle {{
                background:#143338;
                color:#48d5e6;
                border:1px solid #2c6870;
                border-radius:7px;
                font-weight:800;
                font-size:{label_px}px;
                padding:0 {max(6, pad_h - 2)}px;
            }}
            QFrame#toolbar QLabel#testModeTitle {{
                background:#143338;
                color:#d8e4e1;
                border:1px solid #2c6870;
                border-radius:7px;
                font-weight:800;
                font-size:{label_px}px;
                padding:0 {max(6, pad_h - 2)}px;
            }}
            QFrame#toolbar QLabel#pulseCount {{
                color:#9ca9a6;
                font-size:{label_px}px;
                padding:0 1px;
            }}
            QFrame#toolbar QLabel#calcBadge {{
                background:#f0c54d;
                color:#16140b;
                border:1px solid #f7d56a;
                border-radius:7px;
                font-weight:800;
                font-size:{label_px}px;
                padding:0 {max(6, pad_h - 2)}px;
                min-width:{param_badge_min_w}px;
            }}
            QFrame#toolbar QFrame#paramCalcGroup QComboBox#pulseSelector {{
                background:#071113;
                color:#e9f2ef;
                border:1px solid #6a6140;
                border-radius:8px;
                font-size:{font_px}px;
                padding:0 {max(5, pad_h - 3)}px;
                min-height:{param_pulse_min_h}px;
                max-height:{param_control_h}px;
            }}
            QFrame#toolbar QFrame#testModeGroup QComboBox#testModeSelector {{
                background:#071113;
                color:#e9f2ef;
                border:1px solid #6a6140;
                border-radius:8px;
                font-size:{font_px}px;
                padding:0 {max(5, pad_h - 3)}px;
                min-height:{param_pulse_min_h}px;
                max-height:{param_control_h}px;
            }}
            QFrame#toolbar QFrame#reportProgressPanel {{
                background-color:#061314;
                border:1px solid #214a50;
                border-radius:8px;
            }}
            QFrame#toolbar QLabel#reportProgressStage {{
                color:#dff8f0;
                font-size:{label_px}px;
                font-weight:800;
            }}
            QFrame#toolbar QLabel#reportProgressDetail {{
                color:#89989d;
                font-size:{label_px}px;
                font-weight:700;
            }}
            QFrame#toolbar QLabel#reportProgressSeparator {{
                color:#284249;
                font-size:{label_px}px;
                font-weight:700;
            }}
            QFrame#toolbar QLabel#reportProgressPercent {{
                color:#bff9ef;
                font-family:"Cascadia Mono", Consolas, monospace;
                font-size:{label_px}px;
                font-weight:900;
            }}
            QFrame#toolbar QLabel#reportProgressEta {{
                color:#a8b7b8;
                font-family:"Cascadia Mono", Consolas, monospace;
                font-size:{max(10, label_px - 1)}px;
                font-weight:800;
            }}
            QFrame#toolbar QProgressBar#reportProgressTrack {{
                background-color:#020a0b;
                border:1px solid #10272b;
                border-radius:3px;
                min-height:4px;
                max-height:4px;
            }}
            QFrame#toolbar QProgressBar#reportProgressTrack::chunk {{
                background-color:#35d8d0;
                border-radius:2px;
            }}
            """
        )
        self.context_menu_selector.setStyleSheet(
            "QFrame#contextMenuSelector{background:#0b1719;"
            "border:1px solid #2b464b;border-radius:8px;}"
            f"QLabel#contextMenuSelectorLabel{{color:#aeb6d8;font-size:{label_px}px;"
            "padding-left:6px;padding-right:2px;}"
            "QPushButton#contextMenuSelectorButton{background:#142428;"
            "color:#d8e4e1;border:1px solid #344d53;border-radius:7px;"
            f"padding:0 {context_pad_h}px;"
            f"min-height:{min_h}px;min-width:{context_min_w}px;}}"
            "QPushButton#contextMenuSelectorButton:hover{background:#1f363c;}"
            "QPushButton#contextMenuSelectorButton:checked{background:#28bce8;"
            "color:#061014;border-color:#63dff2;font-weight:800;}"
        )

    def _set_temperature_code(self, code: str) -> None:
        code = code if code in TEMP_CONDITION_DEFAULTS else "RT"
        idx = self.combo_temp.findData(code)
        self.combo_temp.blockSignals(True)
        self.spin_temp_value.blockSignals(True)
        try:
            if idx >= 0:
                self.combo_temp.setCurrentIndex(idx)
            self.spin_temp_value.setValue(self._temperature_values[code])
        finally:
            self.combo_temp.blockSignals(False)
            self.spin_temp_value.blockSignals(False)
        self.result_table.set_temperature_labels(self._temperature_display_labels())

    def _on_temperature_changed(self, _index: int = 0) -> None:
        code = str(self.combo_temp.currentData() or "RT")
        code = code if code in TEMP_CONDITION_DEFAULTS else "RT"
        self.spin_temp_value.blockSignals(True)
        try:
            self.spin_temp_value.setValue(self._temperature_values[code])
        finally:
            self.spin_temp_value.blockSignals(False)
        self.result_table.set_temperature_labels(self._temperature_display_labels())
        if self.result is not None:
            self.result_table.set_result(self.result)

    def _on_temperature_value_changed(self, value: float) -> None:
        code = str(self.combo_temp.currentData() or "RT")
        if code not in TEMP_CONDITION_DEFAULTS:
            return
        self._temperature_values[code] = float(value)
        self._save_temperature_value(code, float(value))
        self.result_table.set_temperature_labels(self._temperature_display_labels())
        if self.result is not None:
            self.result_table.set_result(self.result)

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
                self.lbl_pulse_count.setText(f"共 {detected_count} 波{suffix}")
            else:
                self.lbl_pulse_count.setText("共 -- 波")
        finally:
            self.spin_off_pulse.blockSignals(False)
            self.spin_on_pulse.blockSignals(False)

    def _on_test_mode_changed(self, _index: int = 0) -> None:
        data = self.combo_test_mode.currentData()
        if data is not None:
            self.cfg.test_mode.mode = str(data)
        self._apply_test_mode_ui()
        self.profile = self._current_profile()
        if self.bundle is not None:
            self._recalculate(reset_manual=True)

    def _apply_test_mode_ui(self) -> None:
        mode = parse_test_mode(self.cfg.test_mode.mode)
        is_dpt = mode == TestMode.DPT
        is_offset = mode == TestMode.OFFSET_MEASUREMENT
        if not is_offset:
            self._restore_pre_offset_cursor_mode()
        for w in self._pulse_toolbar_widgets:
            w.setEnabled(is_dpt)
            w.setVisible(is_dpt)
        if is_offset:
            self.btn_export.setToolTip("偏移测量模式不生成参数 Excel")
            self.btn_export.setEnabled(False)
            self.btn_select_report_template.setEnabled(False)
            self.btn_select_report_output.setEnabled(False)
            self.btn_write_report.setEnabled(False)
        elif not is_dpt:
            self.btn_export.setToolTip("导出短路测试 Excel")
            self.btn_export.setEnabled(True)
            self.btn_select_report_template.setEnabled(True)
            self.btn_select_report_output.setEnabled(True)
            self.btn_write_report.setEnabled(True)
        else:
            self.btn_export.setToolTip("导出当前结果到 Excel")
            self.btn_export.setEnabled(True)
            self.btn_select_report_template.setEnabled(True)
            self.btn_select_report_output.setEnabled(True)
            self.btn_write_report.setEnabled(True)

    def _on_pulse_spin_changed(self, _value: int) -> None:
        if parse_test_mode(self.cfg.test_mode.mode) != TestMode.DPT:
            return
        self._on_pulse_selection_changed()

    def _apply_offset_cursor_mode_defaults(self) -> None:
        if self._pre_offset_cursor_type is None:
            self._pre_offset_cursor_type = self.wave_plot.cursor_type()
            self._pre_offset_cursor_linked = self.wave_plot.cursor_linked()
        self.wave_plot.set_cursor_type("waveform")

    def _restore_pre_offset_cursor_mode(self) -> None:
        if self._pre_offset_cursor_type is None:
            return
        cursor_type = self._pre_offset_cursor_type
        cursor_linked = self._pre_offset_cursor_linked
        self._pre_offset_cursor_type = None
        self._pre_offset_cursor_linked = None
        self.wave_plot.set_cursor_type(cursor_type)
        if cursor_linked is not None:
            self.wave_plot.set_cursor_linked(cursor_linked)

    def _save_offset_cursor_window(self, t_a_us: float, t_b_us: float) -> None:
        if self.bundle is None:
            return
        a_us, b_us = sorted((float(t_a_us), float(t_b_us)))
        self._offset_cursor_window_us = (a_us, b_us)
        self._offset_cursor_waveform_source = self.bundle.meta.source_path

    def _offset_cursor_window_for_current_waveform(
        self,
    ) -> tuple[float, float] | None:
        if (
            self.bundle is None
            or self._offset_cursor_window_us is None
            or self._offset_cursor_waveform_source != self.bundle.meta.source_path
        ):
            return None
        return self._offset_cursor_window_us

    def _sync_offset_cursor_window_from_plot(self) -> None:
        cursors = self.wave_plot.cursors_t_us()
        if cursors is not None:
            self._save_offset_cursor_window(cursors[0], cursors[1])

    def _restore_offset_cursor_window_to_plot(self) -> None:
        window = self._offset_cursor_window_for_current_waveform()
        if window is None:
            self._sync_offset_cursor_window_from_plot()
            return
        self.wave_plot.set_global_cursor_window(window[0], window[1])

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
        if parse_test_mode(self.cfg.test_mode.mode) == TestMode.OFFSET_MEASUREMENT:
            self._save_offset_cursor_window(t_a_us, t_b_us)
            self._refresh_offset_measurement_table(update_auxiliary=True)

    def _on_horizontal_cursors_moved(self, ha: float, hb: float) -> None:
        if self._active_slope_param is not None:
            return
        dy = hb - ha
        self.statusBar().showMessage(
            f"横光标: Ha={ha:+.3f}  Hb={hb:+.3f}  Δy={dy:+.3f}"
        )

    def _on_waveform_view_range_changed(self) -> None:
        if parse_test_mode(self.cfg.test_mode.mode) != TestMode.OFFSET_MEASUREMENT:
            return
        if any(range_key == "screen" for _source, _metric, range_key in self._offset_measurements):
            self._refresh_offset_measurement_table(update_auxiliary=True)

    def _current_profile(self) -> BridgeProfile:
        phase = self.combo_phase.currentData()
        bridge = self.combo_bridge.currentData()
        profile, custom = resolve_profile(
            phase,
            bridge,
            self._channel_store,
            source_path=self._current_mapping_source_path(),
        )
        mode = parse_test_mode(self.cfg.test_mode.mode)
        if not custom and self.bundle is not None:
            if mode == TestMode.SHORT_CIRCUIT:
                inferred = infer_short_circuit_mapping_from_bundle(self.bundle, bridge)
                if inferred is not None:
                    profile = apply_mapping(
                        as_short_circuit_profile(make_profile(phase, bridge)),
                        inferred,
                    )
                else:
                    profile = as_short_circuit_profile(profile)
            else:
                inferred, _source = infer_best_mapping_from_bundle(
                    self.bundle,
                    bridge,
                )
                if inferred is not None:
                    profile = apply_mapping(profile, inferred)
        else:
            profile = _profile_for_test_mode(profile, self.cfg)
        self._mapping_custom = custom
        self._update_map_status_label()
        return profile

    def _current_mapping_source_path(self) -> str:
        if self.bundle is not None and self.bundle.meta.source_path:
            return self.bundle.meta.source_path
        return self._current_path or ""

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

    def _on_apply_label_mapping_requested(self) -> None:
        if self.bundle is None:
            QMessageBox.information(
                self,
                "未加载 TSS",
                "请先加载 TSS 波形文件，再按标签识别通道。",
            )
            return
        phase = self.combo_phase.currentData()
        bridge = self.combo_bridge.currentData()
        mapping = infer_mapping_from_bundle(self.bundle, bridge)
        if mapping is None:
            QMessageBox.information(
                self,
                "无法识别",
                "当前 TSS 无有效通道标签，或标签无法匹配当前上/下桥配置。",
            )
            return
        errors = validate_mapping(mapping, self.bundle)
        if errors:
            QMessageBox.warning(
                self,
                "映射无效",
                "按标签识别得到的映射不可用：\n\n"
                + "\n".join(f"- {err}" for err in errors),
            )
            return
        self._channel_store.set(
            phase,
            bridge,
            mapping,
            source_path=self._current_mapping_source_path(),
        )
        self.profile = self._current_profile()
        self._mapping_custom = True
        self._update_map_status_label()
        self._recalculate(reset_manual=True)
        self.statusBar().showMessage("已按 TSS 标签识别并应用当前通道映射")

    def _on_waveform_channel_mapping_requested(self, source_key: str, logical_role: str) -> None:
        if self.bundle is None:
            return
        source_key = normalize_channel_reference(source_key)
        phase = self.combo_phase.currentData()
        bridge = self.combo_bridge.currentData()
        current = ChannelMapping.from_profile(self.profile)
        parts = {key: getattr(current, key) for key in LOGICAL_SIGNAL_KEYS}
        ic_sum = bool(current.ic_from_sum_irr_il)
        irr_diff = bool(current.irr_from_ic_minus_il)

        if logical_role:
            if logical_role not in LOGICAL_SIGNAL_KEYS:
                return
            previous_channel = str(parts.get(logical_role) or "")
            parts[logical_role] = source_key
            if logical_role == "ic":
                ic_sum = False
            elif logical_role == "irr":
                irr_diff = False
        else:
            for key in LOGICAL_SIGNAL_KEYS:
                if normalize_channel_reference(parts.get(key)) == source_key:
                    parts[key] = ""

        mapping = ChannelMapping(
            **parts,
            ic_from_sum_irr_il=ic_sum,
            irr_from_ic_minus_il=irr_diff,
        )
        if logical_role:
            mapping = resolve_mapping_conflicts(
                mapping,
                logical_role,
                previous_channel,
            )
        errors = validate_mapping(mapping, self.bundle, require_existing=False)
        if errors:
            QMessageBox.warning(
                self,
                "映射无效",
                "该设置会导致参数计算通道不完整或重复：\n\n"
                + "\n".join(f"- {err}" for err in errors),
            )
            return

        self._channel_store.set(
            phase,
            bridge,
            mapping,
            source_path=self._current_mapping_source_path(),
        )
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

    def _on_waveform_channel_unit_changed(self, source_key: str, unit: str) -> None:
        if self.bundle is None:
            return
        source_key = normalize_channel_reference(source_key)
        base = source_key[1:] if source_key.startswith("-") else source_key
        unit = str(unit or "").strip()
        if unit:
            self.bundle.meta.channel_unit_overrides[base] = unit
        else:
            self.bundle.meta.channel_unit_overrides.pop(base, None)
            self.statusBar().showMessage(f"{source_key} 标签已清空")
        if parse_test_mode(self.cfg.test_mode.mode) == TestMode.OFFSET_MEASUREMENT:
            self._refresh_offset_measurement_table()

    def _on_waveform_channel_inversion_changed(
        self, source_key: str, enabled: bool
    ) -> None:
        if self.bundle is None:
            return
        source_key = normalize_channel_reference(source_key)
        base = source_key[1:] if source_key.startswith("-") else source_key
        if not base:
            return
        if enabled:
            self.bundle.meta.channel_display_inversions.add(base)
        else:
            self.bundle.meta.channel_display_inversions.discard(base)
        if parse_test_mode(self.cfg.test_mode.mode) == TestMode.OFFSET_MEASUREMENT:
            self._refresh_offset_measurement_table(update_auxiliary=True)
        else:
            self._recalculate(reset_manual=False)
        state = "反相" if enabled else "原始方向"
        self.statusBar().showMessage(f"{base} 已切换为{state}")

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
            profile.phase,
            profile.bridge,
            self._channel_store,
            source_path=self._current_mapping_source_path(),
        )
        self.profile = _profile_for_test_mode(self.profile, self.cfg)
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
        cfg.short_circuit_tsc_range = self._load_short_circuit_tsc_range()
        return cfg

    def _set_load_busy(self, busy: bool, path: str = "") -> None:
        self.btn_open.setEnabled(not busy)
        self.btn_recalc.setEnabled(not busy)
        self.btn_export.setEnabled(not busy)
        self.btn_select_report_template.setEnabled(not busy)
        self.btn_select_report_output.setEnabled(not busy)
        self.btn_write_report.setEnabled(not busy)
        if busy:
            self.lbl_current_file.setText(f"正在加载 {Path(path).name}")
            self.lbl_current_file.setToolTip(path)
            self.statusBar().showMessage(f"正在后台加载: {Path(path).name}")
        else:
            self._apply_test_mode_ui()

    def _set_report_busy(self, busy: bool) -> None:
        self.btn_open.setEnabled(not busy)
        self.btn_recalc.setEnabled(not busy)
        self.btn_export.setEnabled(not busy)
        self.btn_select_report_template.setEnabled(not busy)
        self.btn_select_report_output.setEnabled(not busy)
        self.btn_write_report.setEnabled(not busy)
        if busy:
            self.statusBar().showMessage("正在处理报告...")

    def _begin_task_progress(self, stage: str, total: int, label: str) -> None:
        total = max(1, int(total))
        self._report_progress_active = True
        self.report_progress.begin(total, label, stage=stage)
        QApplication.processEvents()

    def _set_task_progress(
        self,
        value: int,
        total: int,
        label: str,
        *,
        stage: str | None = None,
    ) -> None:
        total = max(1, int(total))
        self.report_progress.update_progress(value, total, label, stage=stage)
        QApplication.processEvents()

    def _set_task_progress_busy(self, label: str, *, stage: str | None = None) -> None:
        self.report_progress.set_busy(label, stage=stage)
        QApplication.processEvents()

    def _finish_task_progress(
        self,
        label: str,
        *,
        ok: bool,
        stage: str | None = None,
    ) -> None:
        self.report_progress.finish(label, ok=ok, stage=stage)
        self._report_progress_active = False

    def _begin_report_progress(self, total: int, label: str) -> None:
        self._begin_task_progress("报告写入", total, label)

    def _set_report_progress(self, value: int, total: int, label: str) -> None:
        self._set_task_progress(value, total, label, stage="报告写入")

    def _set_report_progress_busy(self, label: str) -> None:
        self._set_task_progress_busy(label, stage="报告写入")

    def _finish_report_progress(self, label: str, *, ok: bool) -> None:
        self._finish_task_progress(label, ok=ok, stage="报告写入")

    def _start_background_load(self, path: str) -> None:
        self._load_request_id += 1
        request_id = self._load_request_id
        cfg = self._load_cfg_for_new_file()
        task = _WaveformLoadTask(
            request_id,
            path,
            cfg,
        )
        task.signals.progress.connect(self._on_background_load_progress)
        task.signals.finished.connect(self._on_background_load_finished)
        task.signals.failed.connect(self._on_background_load_failed)
        self._load_tasks[request_id] = task
        self._set_load_busy(True, path)
        self._begin_task_progress("数据导入", TASK_PROGRESS_TOTAL, "准备读取原始数据...")
        self._load_pool.start(task)

    def _on_background_load_progress(
        self,
        request_id: int,
        value: int,
        total: int,
        label: str,
    ) -> None:
        if request_id != self._load_request_id:
            return
        self._set_task_progress(value, total, label, stage="数据导入")

    def _on_background_load_finished(
        self,
        request_id: int,
        outcome: _WaveformLoadOutcome,
    ) -> None:
        self._load_tasks.pop(request_id, None)
        if request_id != self._load_request_id:
            return
        try:
            self._set_task_progress(
                LOAD_PROGRESS_APPLY_START,
                TASK_PROGRESS_TOTAL,
                "刷新界面...",
                stage="数据导入",
            )
            self._apply_loaded_waveform(outcome)
            self._set_task_progress(
                LOAD_PROGRESS_PLOT_DONE,
                TASK_PROGRESS_TOTAL,
                "绘制波形...",
                stage="数据导入",
            )
            self._finish_task_progress("导入完成 100%", ok=True, stage="数据导入")
        except Exception as exc:
            self._finish_task_progress("导入失败", ok=False, stage="数据导入")
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
        self._finish_task_progress("导入失败", ok=False, stage="数据导入")
        QMessageBox.critical(self, "加载失败", message)

    def _clear_manual_adjustments(self, *, reset_plot: bool = True) -> None:
        self._manual_intervals.clear()
        self._manual_extreme_values.clear()
        self._manual_turn_on_current = None
        self._manual_energy.clear()
        self._manual_delta_vce.clear()
        self._manual_dvdt.clear()
        self._manual_didt.clear()
        self._manual_trr_measure = None
        self._manual_waveform_source = ""
        self._active_slope_param = None
        if reset_plot:
            self.wave_plot.reset_interaction_state()

    def _sync_plot_math_to_bundle(self) -> None:
        if self.bundle is None:
            return
        plot_source = str(getattr(self.wave_plot, "_loaded_source_path", "") or "")
        bundle_source = str(self.bundle.meta.source_path or "")
        if plot_source and bundle_source and plot_source != bundle_source:
            return
        math_channels = self.wave_plot.export_user_math_channels()
        for key, (raw, expr, scale, offset) in math_channels.items():
            if len(raw) != self.bundle.n:
                continue
            self.bundle.channels[key] = np.asarray(raw, dtype=np.float64).copy()
            self.bundle.meta.channel_math_formulas[key] = expr
            self.bundle.meta.computed_math_channels.add(key)
            unit = self.wave_plot._unit_for_channel(key)
            if unit:
                self.bundle.meta.channel_units[key] = unit
            if scale is not None:
                self.bundle.meta.channel_vdiv[key] = float(scale)
            if offset is not None:
                self.bundle.meta.channel_y_position[key] = float(offset)

    def _loaded_status_message(
        self,
        outcome: _WaveformLoadOutcome,
        inferred: ChannelMapping | None,
    ) -> str:
        mode = parse_test_mode(self.cfg.test_mode.mode)
        if mode == TestMode.OFFSET_MEASUREMENT:
            extract_label = "偏移测量准备"
        else:
            extract_label = "提取" if outcome.result is not None else "参数尝试"
        msg = (
            f"已加载: {Path(outcome.path).name}  |  "
            f"读取 {outcome.load_ms:.0f} ms  {extract_label} {outcome.extract_ms:.0f} ms"
        )
        if outcome.mapping_custom:
            msg += "（已应用自定义通道映射）"
        elif inferred is not None:
            if outcome.inferred_source == "trend":
                msg += "（已按波形趋势识别通道）"
            else:
                msg += "（已按 TSS 标签识别通道）"
        if outcome.result is None and mode != TestMode.OFFSET_MEASUREMENT:
            reason = outcome.extraction_error or "当前波形不满足该模式的自动计算条件"
            msg += f"（参数未计算：{reason}）"
        elif mode == TestMode.OFFSET_MEASUREMENT:
            msg += "（偏移测量模式：未运行参数计算）"
        if outcome.bundle.meta.channel_vdiv:
            msg += f"（已应用 TSS 垂直刻度 {len(outcome.bundle.meta.channel_vdiv)} 通道）"
        return msg

    def _extraction_placeholder_detail(self, error: str) -> str:
        reason = error.strip() or "当前波形不满足该模式的自动计算条件。"
        return f"当前波形已加载，参数未计算。原因：{reason}"

    @staticmethod
    def _offset_source_label(key: str, label: str | None = None) -> str:
        raw = str(key or "")
        display = str(label or "").strip()
        if not display:
            m = re.fullmatch(r"CH(\d+)", raw.upper())
            if m:
                display = f"Ch {m.group(1)}"
            else:
                m = re.fullmatch(r"MATH(\d+)", raw.upper())
                display = f"Math {m.group(1)}" if m else raw
        if display.upper().replace(" ", "") == raw.upper():
            return display
        return f"{display} ({raw})"

    @staticmethod
    def _offset_source_display_name(key: str) -> str:
        raw = str(key or "").upper()
        m = re.fullmatch(r"CH(\d+)", raw)
        if m:
            return f"Ch {m.group(1)}"
        m = re.fullmatch(r"MATH(\d+)", raw)
        if m:
            return f"Math {m.group(1)}"
        return raw or "波形"

    def _offset_source_options(self) -> list[tuple[str, str]]:
        if self.bundle is None:
            return []
        out: list[tuple[str, str]] = []
        trace_items = getattr(self.wave_plot, "_trace_items", {})
        keys = list(trace_items) if trace_items else list(self.bundle.channels)
        for key in keys:
            key = normalize_channel_reference(key)
            label = getattr(self.wave_plot, "_trace_legend", {}).get(
                key,
                self.bundle.meta.channel_labels.get(key, ""),
            )
            out.append((key, self._offset_source_label(key, label)))
        return out

    def _offset_source_available(self, source_key: str) -> bool:
        source = normalize_channel_reference(source_key)
        if not source:
            return False
        trace_items = getattr(self.wave_plot, "_trace_items", {})
        if trace_items:
            return source in trace_items
        return bool(self.bundle is not None and source in self.bundle.channels)

    def _default_offset_measurements_for_bundle(self) -> list[tuple[str, str, str]]:
        if self.bundle is None:
            return []
        available = {key for key, _label in self._offset_source_options()}
        out: list[tuple[str, str, str]] = []
        for source_key, metric_key, range_key in self.bundle.meta.offset_measurements:
            source = normalize_channel_reference(source_key)
            metric = str(metric_key)
            if source not in available or metric not in OFFSET_MEASUREMENT_BY_KEY:
                continue
            item = (source, metric, normalize_offset_range_key(range_key))
            if item not in out:
                out.append(item)
        return out

    def _offset_source_unit(self, source_key: str) -> str:
        try:
            return self.wave_plot._unit_for_channel(source_key)
        except Exception:
            return ""

    @staticmethod
    def _offset_value_text(value: float) -> str:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return "—"
        if not np.isfinite(v):
            return "—"
        if abs(v) >= 100:
            return f"{v:.2f}"
        if abs(v) >= 1:
            return f"{v:.3f}"
        if abs(v) >= 0.01 or v == 0:
            return f"{v:.4f}"
        return f"{v:.4e}"

    def _offset_range_label(self, range_key: str) -> str:
        return OFFSET_RANGE_LABELS.get(str(range_key), "全波形")

    def _offset_default_unit(self, spec: tuple[str, str, str]) -> str:
        source_key, metric_key, _range_key = spec
        return offset_measurement_unit(
            metric_key,
            self._offset_source_unit(source_key),
        )

    def _offset_range_window_s(self, range_key: str) -> tuple[float, float] | None:
        if self.bundle is None or self.bundle.t.size == 0:
            return None
        key = normalize_offset_range_key(range_key)
        if key == "cursor":
            cursors = self._offset_cursor_window_for_current_waveform()
            if cursors is None:
                cursors = self.wave_plot.cursors_t_us()
                if (
                    cursors is not None
                    and parse_test_mode(self.cfg.test_mode.mode)
                    == TestMode.OFFSET_MEASUREMENT
                ):
                    self._save_offset_cursor_window(cursors[0], cursors[1])
            if cursors is not None:
                a_us, b_us = cursors
                return float(a_us) * 1e-6, float(b_us) * 1e-6
        elif key == "screen":
            screen = self.wave_plot.current_x_range_us()
            if screen is not None:
                a_us, b_us = screen
                return float(a_us) * 1e-6, float(b_us) * 1e-6
        return float(self.bundle.t[0]), float(self.bundle.t[-1])

    def _offset_series_for_range(
        self,
        source_key: str,
        range_key: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        if self.bundle is None:
            return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
        source = normalize_channel_reference(source_key)
        t_us = getattr(self.wave_plot, "_trace_t_us", None)
        y_current = self.wave_plot.current_display_raw(source)
        if t_us is not None and y_current is not None:
            t = np.asarray(t_us, dtype=np.float64) * 1e-6
            y = np.asarray(y_current, dtype=np.float64)
            if t.size != y.size:
                return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
        else:
            channel = self.bundle.maybe_get(source)
            if channel is None:
                return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
            t = np.asarray(self.bundle.t, dtype=np.float64)
            y = np.asarray(channel, dtype=np.float64)
        window = self._offset_range_window_s(range_key)
        if window is None:
            return t, y
        lo, hi = sorted((float(window[0]), float(window[1])))
        mask = (t >= lo) & (t <= hi)
        if not np.any(mask):
            return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
        return t[mask], y[mask]

    def _offset_measurement_rows(
        self,
    ) -> tuple[
        list[tuple[str, str, str, str, str, str]],
        list[tuple[str, str, str]],
    ]:
        if self.bundle is None:
            return [], []
        available = {key for key, _label in self._offset_source_options()}
        rows: list[tuple[str, str, str, str, str, str]] = []
        row_specs: list[tuple[str, str, str]] = []
        for source_key, metric_key, range_key in self._offset_measurements:
            if source_key not in available or metric_key not in OFFSET_MEASUREMENT_BY_KEY:
                continue
            range_key = normalize_offset_range_key(range_key)
            row_spec = (source_key, metric_key, range_key)
            t_range, raw = self._offset_series_for_range(source_key, range_key)
            value = calculate_offset_measurement(t_range, raw, metric_key)
            spec = OFFSET_MEASUREMENT_BY_KEY[metric_key]
            name = spec.label.replace("\n", " ")
            base_unit = self._offset_default_unit(row_spec)
            unit = auto_offset_measurement_unit(value, base_unit)
            display_value = convert_offset_measurement_value(
                value,
                base_unit,
                unit,
            )
            rows.append(
                (
                    self._offset_source_display_name(source_key),
                    name,
                    unit,
                    self._offset_range_label(range_key),
                    self._offset_value_text(display_value),
                    self.wave_plot.trace_color(source_key),
                )
            )
            row_specs.append(row_spec)
        return rows, row_specs

    def _refresh_offset_measurement_table(self, *, update_auxiliary: bool = False) -> None:
        sources = self._offset_source_options()
        rows, row_specs = self._offset_measurement_rows()
        self.result_table.set_offset_sources(sources)
        self.result_table.show_offset_measurements(
            rows,
            source_count=len(sources),
            row_specs=row_specs,
        )
        self.result_table.setMaximumWidth(self.result_table.preferred_panel_width())
        if rows and self.result_table.table.currentRow() < 0:
            self.result_table.table.setCurrentCell(0, 1)
            self.result_table.table.selectRow(0)
        if not self._splitter_user_moved:
            self._sync_splitter_sizes()
        if update_auxiliary:
            self._refresh_offset_auxiliary_from_active()

    def _refresh_offset_auxiliary_from_active(self) -> None:
        if self.bundle is None:
            self.wave_plot.clear_cursor_auxiliary_guides()
            return
        spec = self.result_table.current_offset_measurement_spec()
        if spec is None:
            self.wave_plot.clear_cursor_auxiliary_guides()
            return
        source_key, metric_key, range_key = spec
        window = self._offset_range_window_s(range_key)
        t_range, raw = self._offset_series_for_range(source_key, range_key)
        marker = offset_measurement_marker(t_range, raw, metric_key)
        if marker is None:
            self.wave_plot.clear_cursor_auxiliary_guides()
            return
        t_s, value = marker
        x_range_us = None
        if window is not None:
            lo_s, hi_s = sorted((float(window[0]), float(window[1])))
            if hi_s > lo_s:
                x_range_us = (lo_s * 1e6, hi_s * 1e6)
        self.wave_plot.set_cursor_auxiliary_point(
            source_key,
            float(t_s) * 1e6,
            value,
            show_vertical_guide=True,
            x_range_us=x_range_us,
        )

    def _enter_offset_measurement_mode(
        self,
        outcome: _WaveformLoadOutcome | None = None,
    ) -> None:
        self.result = None
        self.wave_plot.plot_waveforms(self.bundle, self.profile, None)
        self.wave_plot.enable_global_cursor_interaction()
        self._apply_offset_cursor_mode_defaults()
        self._restore_offset_cursor_window_to_plot()
        self._refresh_offset_measurement_table(update_auxiliary=True)
        if outcome is not None:
            self.statusBar().showMessage(
                self._loaded_status_message(outcome, outcome.inferred)
            )
        else:
            self.statusBar().showMessage("偏移测量：波形已加载，可自定义添加测量项")

    def _on_offset_measurement_add_requested(
        self, source_key: str, metric_key: str, range_key: str = "screen"
    ) -> None:
        if self.bundle is None:
            return
        source_key = normalize_channel_reference(source_key)
        if not self._offset_source_available(source_key):
            return
        if metric_key not in OFFSET_MEASUREMENT_BY_KEY:
            return
        range_key = normalize_offset_range_key(range_key)
        pair = (source_key, metric_key, range_key)
        if pair not in self._offset_measurements:
            self._offset_measurements.append(pair)
        self._refresh_offset_measurement_table(update_auxiliary=True)
        label = self._offset_source_display_name(source_key)
        metric = OFFSET_MEASUREMENT_BY_KEY[metric_key].label.replace("\n", " ")
        self.statusBar().showMessage(
            f"已添加偏移测量: {label} · {metric} · {self._offset_range_label(range_key)}"
        )

    def _on_offset_measurement_update_requested(
        self,
        row: int,
        field: str,
        value: str,
    ) -> None:
        if self.bundle is None:
            return
        if row < 0 or row >= len(self._offset_measurements):
            return

        old_spec = self._offset_measurements[row]
        source_key, metric_key, range_key = old_spec
        field = str(field)
        value = str(value)

        if field == "source":
            new_source = normalize_channel_reference(value)
            if not self._offset_source_available(new_source):
                return
            source_key = new_source
        elif field == "metric":
            if value not in OFFSET_MEASUREMENT_BY_KEY:
                return
            metric_key = value
        elif field == "range":
            range_key = normalize_offset_range_key(value)
        else:
            return

        new_spec = (source_key, metric_key, range_key)
        self._offset_measurements[row] = new_spec
        self._refresh_offset_measurement_table(update_auxiliary=True)
        self.statusBar().showMessage(
            f"已更新偏移测量: "
            f"{self._offset_source_display_name(source_key)} · "
            f"{OFFSET_MEASUREMENT_BY_KEY[metric_key].label.replace(chr(10), ' ')} · "
            f"{self._offset_range_label(range_key)}"
        )

    def _on_offset_measurement_delete_requested(
        self, source_key: str, metric_key: str, range_key: str
    ) -> None:
        source_key = str(source_key).upper()
        range_key = normalize_offset_range_key(range_key)
        target = (source_key, metric_key, range_key)
        for idx, item in enumerate(self._offset_measurements):
            normalized = (
                str(item[0]).upper(),
                item[1],
                normalize_offset_range_key(item[2]),
            )
            if normalized == target:
                del self._offset_measurements[idx]
                self._refresh_offset_measurement_table(update_auxiliary=True)
                metric = OFFSET_MEASUREMENT_BY_KEY.get(metric_key)
                metric_label = metric.label.replace("\n", " ") if metric else metric_key
                self.statusBar().showMessage(
                    f"已删除偏移测量: "
                    f"{self._offset_source_display_name(source_key)} · "
                    f"{metric_label} · {self._offset_range_label(range_key)}"
                )
                return

    def _on_offset_measurement_delete_all_requested(self) -> None:
        if not self._offset_measurements:
            return
        self._offset_measurements = []
        self._refresh_offset_measurement_table(update_auxiliary=True)
        self.statusBar().showMessage("已删除全部偏移测量")

    def _apply_loaded_waveform(self, outcome: _WaveformLoadOutcome) -> None:
        path = outcome.path
        inferred = outcome.inferred
        self.bundle = outcome.bundle
        self._current_path = path

        self._set_profile_combos(outcome.guessed)
        self.profile = outcome.profile
        self._mapping_custom = outcome.mapping_custom
        self._update_map_status_label()

        self.cfg.vdc_override = None
        self.lbl_current_file.setText(Path(path).name)
        self.lbl_current_file.setToolTip(path)
        self._set_temperature_code(_infer_temp_code_from_path(path))
        self._slope_ranges = default_slope_ranges()
        self.cfg.short_circuit_tsc_range = self._load_short_circuit_tsc_range()
        self.result_table.set_slope_ranges(self._slope_ranges)
        self._clear_manual_adjustments()
        self._offset_measurements = self._default_offset_measurements_for_bundle()
        set_last_open_path(path)

        if parse_test_mode(self.cfg.test_mode.mode) == TestMode.OFFSET_MEASUREMENT:
            self._enter_offset_measurement_mode(outcome)
            return

        if outcome.result is None:
            self.result = None
            mode_label = MODE_UI_LABELS[parse_test_mode(self.cfg.test_mode.mode)]
            self.result_table.set_mode_placeholder(
                mode_label,
                self._extraction_placeholder_detail(outcome.extraction_error),
            )
            self.result_table.setMaximumWidth(
                self.result_table.preferred_panel_width()
            )
            if not self._splitter_user_moved:
                self._sync_splitter_sizes()
            self.wave_plot.plot_waveforms(self.bundle, self.profile, None)
            self.statusBar().showMessage(self._loaded_status_message(outcome, inferred))
            return
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

    def _on_short_circuit_tsc_range_changed(self, label: str) -> None:
        normalized = self._save_short_circuit_tsc_range(label)
        self.cfg.short_circuit_tsc_range = normalized
        self._manual_intervals.pop(("短路过程", "短路时间Tsc"), None)
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
        is_offset = parse_test_mode(self.cfg.test_mode.mode) == TestMode.OFFSET_MEASUREMENT
        if not is_offset:
            self.result_table.set_active_metric(section, name)
        if is_offset:
            self._refresh_offset_auxiliary_from_active()
            spec = self.result_table.current_offset_measurement_spec()
            if spec is not None:
                _source, _metric, range_key = spec
                self.statusBar().showMessage(
                    f"偏移测量: {section} · {name} · {self._offset_range_label(range_key)}"
                )
            else:
                self.statusBar().showMessage(f"偏移测量: {name}")
            return
        if self._metric_unavailable(section, name):
            self.wave_plot.disable_interactive_cursors()
            self.statusBar().showMessage(
                f"{section}-{name}: 缺少关联通道，参数不可用"
            )
            return
        if self.result is not None and self.result.short_circuit_mode:
            if (
                section == "短路过程"
                and name == "Desat动作时间"
                and not self._short_desat_image_available()
            ):
                self.wave_plot.disable_interactive_cursors()
                self.statusBar().showMessage(
                    "短路过程-Desat动作时间: 缺少 Desat 波形通道或参数值，已跳过截图"
                )
                return
            if section == "短路过程" and name in {"短路电流Imax", "短路时间Tsc"}:
                self._enable_short_circuit_current_interaction(name)
                return
            self._enable_generic_parameter_interaction(section, name)
            return
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
        if name in {"Pmax", "Pdmax"}:
            self._enable_power_interaction(section)
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

    def _metric_unavailable(self, section: str, name: str) -> bool:
        return (
            self.result is not None
            and self.result.is_metric_unavailable(section, name)
        )

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

    def _vge_focus_edge_start_us(self, section: str) -> float | None:
        """默认局部视图锚点：在 IEC 10/90 计时点附近前探 Vge 边沿起始点。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        segs = self.result.segments
        t = self.bundle.t
        vge = np.asarray(self.bundle.get(self.profile.vge), dtype=np.float64)
        dt = max(float(self.bundle.dt), 1e-15)
        n = len(t)
        if n < 20 or len(vge) != n:
            return None

        def _cross_start_us(
            w0: int,
            w1: int,
            v_lo: float,
            v_hi: float,
            direction: str,
            levels: tuple[float, ...],
        ) -> float | None:
            if w1 <= w0 + 10:
                return None
            if abs(v_hi - v_lo) < 1.0:
                return None
            ts = t[w0 : w1 + 1]
            vge_s = smooth(vge[w0 : w1 + 1], dt, self.cfg.smoothing.detect_window_ns)
            starts: list[float] = []
            for pct in levels:
                tv = crossing_time(
                    ts,
                    vge_s,
                    threshold_value(v_lo, v_hi, pct),
                    direction,
                    start=0,
                )
                if tv is not None and np.isfinite(tv):
                    starts.append(float(tv))
            if not starts:
                return None
            return min(starts) * 1e6

        reference_us: float | None = None
        if section == "关断过程":
            try:
                inst = self._turn_off_timing_instants()
                if inst.t_v90_s is not None:
                    reference_us = float(inst.t_v90_s * 1e6)
            except Exception:
                reference_us = None
            pulse1_on = int(segs.pulse1_on)
            off_idx = int(segs.pulse1_off)
            pulse2_on = int(segs.pulse2_on)
            p1w = max(10, off_idx - pulse1_on)
            gap12 = max(10, pulse2_on - off_idx)
            pre_hi = max(int(50e-9 / dt), int(0.03 * p1w))
            post_lo = max(int(80e-9 / dt), int(0.06 * gap12))

            hi0 = max(0, min(pulse1_on, n - 2))
            hi1 = max(hi0 + 20, min(off_idx - pre_hi, n - 1))
            if hi1 <= hi0 + 5:
                hi1 = max(hi0 + 20, min(off_idx - int(15e-9 / dt), n - 1))
            lo0 = min(n - 1, max(off_idx + int(150e-9 / dt), hi1 + 10))
            lo1 = max(lo0 + 20, min(pulse2_on - post_lo, n - 1))
            if lo1 <= lo0 + 5:
                lo1 = max(lo0 + 20, min(off_idx + int(2e-6 / dt), n - 1))
            if hi1 <= hi0 + 5 or lo1 <= lo0 + 5:
                return None

            fall_span = max(int(1.2e-6 / dt), int(0.25 * p1w), int(0.5 * gap12))
            w0 = max(0, pulse1_on, off_idx - fall_span)
            if reference_us is not None:
                ref_idx = int(np.searchsorted(t, reference_us * 1e-6, side="left"))
                w0 = max(w0, ref_idx - int(350e-9 / dt))
            w1 = min(n - 1, off_idx)
            v_hi = float(np.percentile(vge[hi0:hi1], 95))
            v_lo = float(np.percentile(vge[lo0:lo1], 5))
            edge_us = _cross_start_us(w0, w1, v_lo, v_hi, "falling", (0.98, 0.95, 0.90))
            if edge_us is None:
                return None
            if reference_us is not None:
                edge_us = min(reference_us, max(edge_us, reference_us - 0.25))
            return edge_us

        if section in {"开通", "反向恢复"}:
            try:
                inst = self._turn_on_timing_instants()
                if inst.t_v10_s is not None:
                    reference_us = float(inst.t_v10_s * 1e6)
            except Exception:
                reference_us = None
            pulse1_off = int(segs.pulse1_off)
            on_idx = int(segs.pulse2_on)
            pulse2_off = int(segs.pulse2_off)
            same_pulse = on_idx <= pulse1_off
            gap12 = max(10, on_idx - pulse1_off) if not same_pulse else max(10, on_idx)
            p2w = max(10, pulse2_off - on_idx)
            pre_lo = max(int(50e-9 / dt), int(0.05 * gap12))
            post_hi = max(int(80e-9 / dt), int(0.06 * p2w))

            if same_pulse:
                lo0 = max(0, on_idx - int(500e-9 / dt))
                lo1 = max(lo0 + 20, min(on_idx - pre_lo, n - 1))
            else:
                lo0 = min(n - 1, max(pulse1_off + int(150e-9 / dt), 0))
                lo1 = max(lo0 + 20, min(on_idx - pre_lo, n - 1))
            if lo1 <= lo0 + 5:
                lo1 = max(lo0 + 20, min(on_idx - int(15e-9 / dt), n - 1))
            hi0 = min(n - 1, max(on_idx + int(150e-9 / dt), lo1 + 10))
            hi1 = max(hi0 + 20, min(pulse2_off - post_hi, n - 1))
            if lo1 <= lo0 + 5 or hi1 <= hi0 + 5:
                return None

            rise_span = max(int(1.2e-6 / dt), int(0.25 * gap12), int(0.5 * p2w))
            w0 = max(0, on_idx - rise_span) if same_pulse else max(0, pulse1_off, on_idx - rise_span)
            if reference_us is not None:
                ref_idx = int(np.searchsorted(t, reference_us * 1e-6, side="left"))
                w0 = max(w0, ref_idx - int(350e-9 / dt))
            w1 = min(n - 1, on_idx)
            v_lo = float(np.percentile(vge[lo0:lo1], 5))
            v_hi = float(np.percentile(vge[hi0:hi1], 95))
            edge_us = _cross_start_us(w0, w1, v_lo, v_hi, "rising", (0.02, 0.05, 0.10))
            if edge_us is None:
                return None
            if reference_us is not None:
                edge_us = min(reference_us, max(edge_us, reference_us - 0.25))
            return edge_us

        return None

    def _switching_focus_anchor_us(self, section: str) -> float | None:
        """参数局部视图锚点：关断看 Vge 下降起始，开通/反向恢复看 Vge 抬升起始。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        edge_start_us = self._vge_focus_edge_start_us(section)
        if edge_start_us is not None:
            return edge_start_us
        segs = self.result.segments
        if section == "关断过程":
            try:
                inst = self._turn_off_timing_instants()
                if inst.t_v90_s is not None:
                    return float(inst.t_v90_s * 1e6)
            except Exception:
                pass
            idx = int(segs.pulse1_off)
        elif section in {"开通", "反向恢复"}:
            try:
                inst = self._turn_on_timing_instants()
                if inst.t_v10_s is not None:
                    return float(inst.t_v10_s * 1e6)
            except Exception:
                pass
            idx = int(segs.pulse2_on)
        else:
            return None
        if idx < 0 or idx >= len(self.bundle.t):
            return None
        return float(self.bundle.t[idx] * 1e6)

    def _focus_switching_local_view(
        self,
        section: str,
        fallback_t0_us: float,
        fallback_t1_us: float,
        *,
        anchor_us: float | None = None,
    ) -> None:
        # 关断/开通以门极事件为 28% 锚点；反向恢复则必须以当前参数的
        # 实际 A/窗口起点为锚点，否则 Vge 边沿会把主要振荡挤到屏幕中部，
        # 右侧反向恢复尾部在报告截图中显示不足。
        if anchor_us is None:
            if section == "反向恢复":
                anchor_us = min(float(fallback_t0_us), float(fallback_t1_us))
            else:
                anchor_us = self._switching_focus_anchor_us(section)
        if anchor_us is None:
            self.wave_plot.focus_interval_us(fallback_t0_us, fallback_t1_us)
            return
        self.wave_plot.focus_parameter_window_us(
            anchor_us,
            fallback_t0_us,
            fallback_t1_us,
        )

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
        if restored is None or section == "反向恢复":
            if res0.t_pct_a_s is not None and res0.t_pct_b_s is not None:
                self._focus_switching_local_view(section, ta_us, tb_us)
            else:
                self._focus_switching_local_view(section, search_t0, search_t1)
        elif res0.t_pct_a_s is not None and res0.t_pct_b_s is not None:
            ta_us = res0.t_pct_a_s * 1e6
            tb_us = res0.t_pct_b_s * 1e6
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
            dt = float(getattr(getattr(self, "bundle", None), "dt", 0.0) or 0.0)
            if len(tail) >= 8 and dt > 0.0:
                hb = float(_quiet_local_platform_level(tail, dt, min_ns=200.0))
            elif len(tail) >= 8:
                p05, p95 = (float(np.nanpercentile(tail, p)) for p in (5, 95))
                hb = 0.5 * (p05 + p95)
            else:
                hb = float(np.percentile(tail, 50)) if len(tail) else 0.0
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
            self._apply_didt_result(
                section, res, top_a_live, base_a_live, t0, t1, zero_live
            )

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
        if manual is None or section == "反向恢复":
            if res0.t_pct_a_s is not None and res0.t_pct_b_s is not None:
                self._focus_switching_local_view(section, ta_us, tb_us)
            else:
                self._focus_switching_local_view(section, search_t0, search_t1)
        elif res0.t_pct_a_s is not None and res0.t_pct_b_s is not None:
            ta_us = res0.t_pct_a_s * 1e6
            tb_us = res0.t_pct_b_s * 1e6
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

        self._focus_switching_local_view("开通", top_t_us, move_t_us)

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
        self._focus_switching_local_view("关断过程", peak_t_us, top_t_us)

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

    def _enable_power_interaction(self, section: str) -> None:
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        metric_name = power_metric_name(section)
        if {
            "关断过程": "Eoff",
            "开通": "Eon",
            "反向恢复": "Err",
        }.get(section) is None:
            self._enable_generic_parameter_interaction(section, metric_name)
            return
        interval = self._parameter_interval_us(section, metric_name)
        if interval is None:
            return

        restored = self._manual_intervals.get((section, metric_name))
        t0_us, t1_us = restored if restored is not None else interval
        t0_us, t1_us = min(t0_us, t1_us), max(t0_us, t1_us)

        def _target_w() -> float | None:
            target_kw = self._stored_param_value(section, metric_name)
            try:
                if target_kw is not None:
                    return float(target_kw) * 1000.0
            except (TypeError, ValueError):
                return None
            return None

        def _power_peak(t0: float, t1: float):
            return self.wave_plot.power_peak_in_window(
                min(t0, t1),
                max(t0, t1),
                target_w=_target_w(),
                prefer_abs=section == "反向恢复",
            )

        def _store_power_peak(value_kw: float) -> None:
            if section == "关断过程":
                self.result.turn_off.pmax = value_kw
            elif section == "开通":
                self.result.turn_on.pmax = value_kw
            elif section == "反向恢复":
                self.result.reverse_recovery.pdmax = value_kw
            self.result_table.set_metric_value(section, metric_name, value_kw)

        def _apply_power_peak(t0: float, t1: float, *, remember: bool) -> bool:
            lo, hi = min(t0, t1), max(t0, t1)
            matched = _power_peak(lo, hi)
            if matched is None:
                self.statusBar().showMessage(
                    f"{section}-{metric_name}: 未显示功率波形，仅定位功率取值窗口 "
                    f"{lo:.3f}~{hi:.3f}µs"
                )
                return False
            channel, peak_w, peak_value, _peak_t_us = matched
            self.wave_plot.set_interval_peak_horizontal(
                float(peak_value),
                channel=channel,
                t0_us=lo,
                t1_us=hi,
                use_abs_peak=section == "反向恢复",
                display_abs_peak=section == "反向恢复",
            )
            peak_kw = float(peak_w) / 1000.0
            _store_power_peak(peak_kw)
            if remember:
                self._touch_manual_waveform_source()
                self._manual_intervals[(section, metric_name)] = (lo, hi)
            self.statusBar().showMessage(
                f"{section}-{metric_name}: {peak_kw:.3f} kW "
                f"({channel}, {lo:.3f}~{hi:.3f}µs，A/B 为取值窗口)"
            )
            return True

        matched = _power_peak(t0_us, t1_us)
        if restored is None or section == "反向恢复":
            self._focus_switching_local_view(section, t0_us, t1_us)
        else:
            self.wave_plot.focus_interval_us(t0_us, t1_us)
        self.wave_plot.enable_interval_interaction(
            start_t_us=t0_us,
            end_t_us=t1_us,
            on_change=lambda ta, tb: _apply_power_peak(ta, tb, remember=True),
            show_horizontal_peak=matched is not None,
            mode="power_peak",
        )
        if matched is None:
            self.statusBar().showMessage(
                f"{section}-{metric_name}: 未显示功率波形，仅定位功率取值窗口 "
                f"{t0_us:.3f}~{t1_us:.3f}µs"
            )
            return
        channel, peak_w, peak_value, _peak_t_us = matched
        self.wave_plot.set_interval_peak_horizontal(
            float(peak_value),
            channel=channel,
            t0_us=t0_us,
            t1_us=t1_us,
            use_abs_peak=section == "反向恢复",
            display_abs_peak=section == "反向恢复",
        )
        if restored is not None:
            _store_power_peak(float(peak_w) / 1000.0)
        self.statusBar().showMessage(
            f"{section}-{metric_name}: {float(peak_w) / 1000.0:.3f} kW "
            f"({channel}, {t0_us:.3f}~{t1_us:.3f}µs，拖动 A/B 后重算)"
        )

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
        from dpt_extractor.metrics.iec_windows import err_recovery_peak_index

        ipk = err_recovery_peak_index(irr[rr0 : rr1 + 1], dt)
        ipk_global = rr0 + ipk
        markers = err_energy_markers(
            t,
            irr,
            v_diode,
            rr0,
            rr1,
            dt,
            i_search_end=on1,
            vge=self.bundle.get(self.profile.vge),
            pulse1_off=segs.pulse1_off,
            pulse2_on=segs.pulse2_on,
            pulse2_off=segs.pulse2_off,
            dc_current=self.result.idc,
            lower_bridge_irr_from_ic_minus_il=self.profile.irr_from_ic_minus_il,
        )
        search_t0 = float(t[rr0] * 1e6)
        search_t1 = float(t[on1] * 1e6)
        edge_a, edge_b = "falling", "rising"
        ha_channel, hb_channel, a_channel, b_channel = "irr", "v_diode", "irr", "v_diode"
        a_anchor_us = float(t[ipk_global] * 1e6)

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
            lo, hi = min(float(ta_us), float(tb_us)), max(float(ta_us), float(tb_us))
            self._manual_intervals[("反向恢复", "Err")] = (lo, hi)
            self._manual_intervals[("反向恢复", "Pdmax")] = (lo, hi)
            win = IntegrationWindow(i0w, i1w, float(t[i0w]), float(t[i1w]))
            val = float(integrate_err_recovery(t, v_diode, irr, win))
            pdmax = float(peak_power_kw(v_diode, irr, win, absolute=True))
            self.result.reverse_recovery.err = val
            self.result.reverse_recovery.pdmax = pdmax
            self.result_table.set_metric_value("反向恢复", "Pdmax", pdmax)
            self.result_table.set_metric_value("反向恢复", "Err", val)
            self.statusBar().showMessage(
                f"反向恢复-Err: Ha(Irr)={ha_a:.2f}A Hb(Vd)={hb_v:.2f}V "
                f"A={ta_us:.3f}µs B={tb_us:.3f}µs, Pdmax={pdmax:.3f} kW, Err={val:.3f} mJ"
            )

        legacy = self._manual_intervals.get(("反向恢复", "Err"))
        restored = (
            self._manual_energy.get(("反向恢复", "Err"))
            if self._manual_cursors_apply_to_current_waveform()
            else None
        )
        if restored is not None:
            ta_us, tb_us, ha_a, hb_v = restored
        elif legacy is not None:
            ta_us, tb_us = legacy
            ha_a, hb_v = markers.ha_v, markers.hb_a
        else:
            ta_us = markers.t_start * 1e6
            tb_us = markers.t_end * 1e6
            ha_a, hb_v = markers.ha_v, markers.hb_a

        # 首次进入 Err 时将恢复区放到推荐位置；已经存在手动 energy
        # 光标时，用户可能刚刚平移/缩放到要复核的局部区域。二次点击只恢复
        # 光标和交互状态，不应覆盖当前 X 轴视图。
        if restored is None and legacy is None:
            self._focus_switching_local_view(
                "反向恢复",
                min(ta_us, tb_us) - 0.15,
                max(ta_us, tb_us) + 0.15,
                anchor_us=min(ta_us, tb_us),
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
            lower_bridge_irr_from_ic_minus_il=self.profile.irr_from_ic_minus_il,
        )
        if restored is None and legacy is None:
            self._show_stored_metric_status("反向恢复", "Err")

    def _enable_eoff_eon_energy_interaction(self, section: str, name: str) -> None:
        """Eoff/Eon：Ha=Vce 平台、Hb=Ic 平台，A/B 为与电平交点，拖动实时重算损耗。"""
        self._active_slope_param = None
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        power_name = power_metric_name(section)
        t = self.bundle.t
        dt = self.bundle.dt
        segs = self.result.segments
        from dpt_extractor.models.waveform import bundle_total_current

        ic = bundle_total_current(self.bundle, self.profile)
        vce = self.bundle.get(self.profile.vce)

        if section == "关断过程" and name in {"Eoff", power_name, "Pdmax"}:
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
                float(markers.t_start * 1e6) - 0.15,
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
            lo, hi = min(float(ta_us), float(tb_us)), max(float(ta_us), float(tb_us))
            self._manual_intervals[(section, name)] = (lo, hi)
            self._manual_intervals[(section, power_name)] = (lo, hi)
            win = IntegrationWindow(i0, i1, float(t[i0]), float(t[i1]))
            val = float(integrate_vi_window(t, vce, ic, win))
            pmax = float(peak_power_kw(vce, ic, win))
            if section == "关断过程":
                self.result.turn_off.eoff = val
                self.result.turn_off.pmax = pmax
                self.result_table.set_metric_value("关断过程", power_name, pmax)
                self.result_table.set_metric_value("关断过程", "Eoff", val)
            else:
                self.result.turn_on.eon = val
                self.result.turn_on.pmax = pmax
                self.result_table.set_metric_value("开通", power_name, pmax)
                self.result_table.set_metric_value("开通", "Eon", val)
            if section == "开通":
                ha_txt = f"Ha(Ic)={ha_v:.2f}A"
                hb_txt = f"Hb(Vce)={hb_a:.2f}V"
            else:
                ha_txt = f"Ha(Vce)={ha_v:.2f}V"
                hb_txt = f"Hb(Ic)={hb_a:.2f}A"
            self.statusBar().showMessage(
                f"{section}-{name}: {ha_txt} {hb_txt} "
                f"A={ta_us:.3f}µs B={tb_us:.3f}µs, {power_name}={pmax:.3f} kW, {name}={val:.3f} mJ"
            )

        key = (section, name)
        restored = (
            self._manual_energy.get(key)
            if self._manual_cursors_apply_to_current_waveform()
            else None
        )
        if restored is not None:
            ta_us, tb_us, ha_v, hb_v = restored
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
        self._focus_switching_local_view(section, ta_us, tb_us)
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

        def _apply_irr_interval(
            t0_us: float, t1_us: float, *, remember: bool
        ) -> None:
            i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
            i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
            i0 = max(0, min(i0, len(t) - 1))
            i1 = max(i0 + 1, min(i1, len(t) - 1))
            peak_idx = self._irr_peak_index_interactive(irr, i0, i1)
            signed_peak = (
                0.0
                if peak_idx is None
                else float(np.asarray(irr, dtype=np.float64)[peak_idx])
            )
            val = abs(float(signed_peak))
            if remember:
                self._touch_manual_waveform_source()
                self._manual_intervals[("反向恢复", "Irr")] = (
                    min(t0_us, t1_us),
                    max(t0_us, t1_us),
                )
            self.wave_plot.set_interval_peak_on_hb(
                signed_peak,
                channel="irr",
            )
            if self.result is None:
                return
            self.result.reverse_recovery.irr = val
            self.result_table.set_metric_value("反向恢复", "Irr", val)
            self.statusBar().showMessage(
                f"反向恢复 Irr: {val:.3f}A（A/B 区间内反向恢复电流尖峰值，Hb 自动跟随）  "
                f"[{min(t0_us, t1_us):.3f}~{max(t0_us, t1_us):.3f}µs]"
            )

        def _on_irr_interval(t0_us: float, t1_us: float) -> None:
            _apply_irr_interval(t0_us, t1_us, remember=True)

        self._focus_switching_local_view("反向恢复", t0_us, t1_us)
        self.wave_plot.enable_irr_peak_interaction(t0_us, t1_us, _on_irr_interval)
        _apply_irr_interval(t0_us, t1_us, remember=restored is not None)

    def _enable_trr_interaction(self) -> None:
        """Trr：Ha 参考线 + A/B 与 Ha 交点；拖 Ha 联动 A(上升沿)、B(下降沿) 首个交点。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        from dpt_extractor.metrics.irr_measure import (
            default_irr_trr_measure,
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
            m = default_irr_trr_measure(
                t,
                irr,
                i0,
                i1,
                segs.pulse2_on,
                on0,
                on1,
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
        fall_end_idx = reverse_recovery_tail_end_index(
            t,
            i1,
            on1,
            peak_idx=peak_idx,
            pulse2_off=segs.pulse2_off,
            dt=self.bundle.dt,
        )
        t1_us = max(t1_us, float(t[fall_end_idx] * 1e6))

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

        self._focus_switching_local_view(
            "反向恢复",
            ta_us,
            max(tb_us, t1_us),
            anchor_us=ta_us,
        )
        self.wave_plot.enable_trr_measure_interaction(
            t0_us,
            t1_us,
            ha_a,
            hb_a,
            ta_us,
            tb_us,
            _on_trr_measure,
            peak_idx=peak_idx,
            i_fall_end_idx=fall_end_idx,
        )
        if saved is not None:
            _on_trr_measure(ha_a, hb_a, ta_us, tb_us, trr_init)
        else:
            self._show_stored_metric_status("反向恢复", "Trr")

    def _channel_for_param(self, section: str, name: str) -> str:
        """参数 → 波形通道（用于横向光标按该通道 V/div 换算定位）。"""
        if section == "短路过程":
            if name == "短路电流Imax":
                return "ic"
            if name in {"短路能量Esc_本管", "短路能量Esc_对管"}:
                return "ic"
            if name == "应力Vpeak_本管":
                return "vce"
            if name == "应力Vpeak_对管":
                return "v_diode"
            if name == "Desat动作时间":
                return self._short_circuit_desat_channel() or "ic"
            return "ic"
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

        if restored is None:
            self._focus_switching_local_view("开通", t_a_us, t_b_us)
        else:
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
        if restored is None:
            self._focus_switching_local_view(section, t0_us, t1_us)
        else:
            self.wave_plot.focus_interval_us(t0_us, t1_us)
        self.wave_plot.enable_crosstalk_interaction(
            start_t_us=t0_us,
            end_t_us=t1_us,
            on_change=_on_interval_change,
        )
        _on_interval_change(t0_us, t1_us)

    def _enable_short_circuit_current_interaction(self, name: str) -> None:
        """短路 Imax/Tsc：默认按短路规范布置，手动拖动时横纵光标独立。"""
        self._active_slope_param = None
        if (
            self.bundle is None
            or self.result is None
            or self.result.segments is None
            or not self.result.short_circuit_mode
        ):
            return
        if name not in {"短路电流Imax", "短路时间Tsc"}:
            return
        cursors = (
            self._short_circuit_tsc_cursors()
            if name == "短路时间Tsc"
            else self._short_circuit_ic_default_cursors()
        )
        if cursors is None:
            return
        t_a_us, t_b_us, hb, ha = cursors
        restored = self._manual_intervals.get(("短路过程", name))
        if restored is not None:
            t_a_us, t_b_us = restored
        t = self.bundle.t
        gate0, gate1 = self.result.segments.turn_off
        s0 = float(t[max(0, min(int(gate0), len(t) - 1))] * 1e6)
        s1 = float(t[max(0, min(int(gate1), len(t) - 1))] * 1e6)

        def _on_change(
            cur_a_us: float,
            cur_b_us: float,
            cur_hb: float,
            cur_ha: float,
        ) -> None:
            ta, tb = min(float(cur_a_us), float(cur_b_us)), max(
                float(cur_a_us), float(cur_b_us)
            )
            self._touch_manual_waveform_source()
            self._manual_intervals[("短路过程", name)] = (ta, tb)
            sc = self.result.short_circuit
            if name == "短路电流Imax":
                sc.ic_max = float(cur_ha)
                self.result.idc = float(cur_ha)
                self.result.idc_set = float(cur_ha)
                self.result_table.set_metric_value("短路过程", name, float(cur_ha))
                self.statusBar().showMessage(
                    f"短路过程-短路电流Imax: Hb={cur_hb:.3f}A, "
                    f"A={ta:.3f}us, B={tb:.3f}us, Imax={cur_ha:.3f}A"
                )
                return
            dur_us = max(0.0, tb - ta)
            sc.tsc = float(dur_us)
            sc.tsc_start_us = ta
            sc.tsc_end_us = tb
            sc.tsc_range = self.cfg.short_circuit_tsc_range or sc.tsc_range
            self.result_table.set_metric_value("短路过程", name, dur_us)
            self.statusBar().showMessage(
                f"短路过程-短路时间Tsc: {sc.tsc_range or '0%-0%'}, "
                f"Hb={cur_hb:.3f}A, A={ta:.3f}us, B={tb:.3f}us, Tsc={dur_us:.3f}us"
            )

        self.wave_plot.enable_short_current_interaction(
            search_t0_us=s0,
            search_t1_us=s1,
            t_a_us=t_a_us,
            t_b_us=t_b_us,
            hb=hb,
            ha=ha,
            on_change=_on_change,
            channel="ic",
            emit_result_on_enter=restored is not None,
        )
        if restored is None:
            self._show_stored_metric_status("短路过程", name)

    def _enable_generic_parameter_interaction(self, section: str, name: str) -> None:
        self._active_slope_param = None
        if self.bundle is None or self.result is None:
            return
        if (
            self.result.short_circuit_mode
            and section == "短路过程"
            and name in {"短路电流Imax", "短路时间Tsc"}
        ):
            self._enable_short_circuit_current_interaction(name)
            return
        interval = self._parameter_interval_us(section, name)
        if interval is None:
            return
        t = self.bundle.t
        is_short_circuit_param = (
            self.result.short_circuit_mode and section == "短路过程"
        )
        short_energy_names = {"短路能量Esc_本管", "短路能量Esc_对管"}
        short_vpeak_roles = {
            "应力Vpeak_本管": (self.profile.vce, "vge", self.profile.vge),
            "应力Vpeak_对管": (self.profile.v_diode, "vge", self.profile.vge),
        }
        is_short_energy_param = is_short_circuit_param and name in short_energy_names
        short_vpeak_role = short_vpeak_roles.get(name) if is_short_circuit_param else None
        is_short_desat_param = is_short_circuit_param and name == "Desat动作时间"
        _MAX_INTERVAL_NAMES = {
            "Ic_off_max",
            "Vce_off_max",
            "Ic_on_max",
            "Vce_on_max",
            "Vrr",
            "应力Vpeak_本管",
            "应力Vpeak_对管",
        }

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
            self._manual_intervals[(section, name)] = (
                min(t0_us, t1_us),
                max(t0_us, t1_us),
            )
            if name in _MAX_INTERVAL_NAMES:
                self._manual_extreme_values.pop((section, name), None)
            ta, tb = min(t0_us, t1_us), max(t0_us, t1_us)
            if is_short_energy_param:
                marker = self._short_circuit_energy_peak_marker(name, i0, i1)
                if marker is not None:
                    peak_y, peak_channel = marker
                    self.wave_plot.set_interval_peak_horizontal(
                        float(peak_y),
                        channel=peak_channel,
                        t0_us=ta,
                        t1_us=tb,
                    )
                cursors = self._short_circuit_ic_default_cursors()
                if cursors is not None:
                    _ta, _tb, hb, _ha = cursors
                    self.wave_plot.set_interval_base_horizontal(hb, channel="ic")
            elif short_vpeak_role is not None:
                voltage_channel, gate_role, gate_channel = short_vpeak_role
                peak_y = self._peak_y_for_param(section, name, i0, i1)
                if peak_y is not None:
                    self.wave_plot.set_interval_peak_horizontal(
                        float(peak_y),
                        channel=self._channel_for_param(section, name),
                        t0_us=ta,
                        t1_us=tb,
                    )
                cursors = self._short_circuit_vpeak_default_cursors(
                    voltage_channel,
                    gate_channel=gate_channel,
                )
                if cursors is not None:
                    _ta, _tb, hb, _ha = cursors
                    self.wave_plot.set_interval_base_horizontal(hb, channel=gate_role)
            elif is_short_desat_param:
                cursors = self._short_circuit_desat_default_cursors()
                desat_channel = self._short_circuit_desat_channel()
                if cursors is not None and desat_channel is not None:
                    _ta, _tb, hb, ha = cursors
                    self.wave_plot.set_interval_peak_horizontal(
                        ha,
                        channel=desat_channel,
                        t0_us=ta,
                        t1_us=tb,
                    )
                    self.wave_plot.set_interval_base_horizontal(hb, channel=desat_channel)
            else:
                if name in _MAX_INTERVAL_NAMES:
                    self._set_extreme_horizontal_lines(section, name, i0, i1, ta, tb)
                else:
                    peak_y = self._peak_y_for_param(section, name, i0, i1)
                    if peak_y is not None:
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

        def _on_horizontal_extreme_change(
            which: str,
            t0_us: float,
            t1_us: float,
            ha_value: float,
            hb_value: float,
        ) -> None:
            ta, tb = min(float(t0_us), float(t1_us)), max(float(t0_us), float(t1_us))
            if which == "hb":
                self.statusBar().showMessage(
                    f"{section}-{name}: Hb={hb_value:.3f} 为当前窗口最小值参考，"
                    "不改参数值"
                )
                return
            if which != "ha":
                return
            metric_value = self._metric_value_from_extreme_line(section, name, ha_value)
            self._touch_manual_waveform_source()
            self._manual_intervals[(section, name)] = (ta, tb)
            self._manual_extreme_values[(section, name)] = (
                float(ha_value),
                float(metric_value),
            )
            self._store_extreme_metric_value(section, name, float(metric_value))
            self.statusBar().showMessage(
                f"{section}-{name}: 手动 Ha={ha_value:.3f}，"
                f"{name}={metric_value:.3f}（A/B 不跟随）"
            )

        # 若该参数此前手动调整过，恢复手动区间而非默认窗口
        restored = self._manual_intervals.get((section, name))
        manual_extreme = (
            self._manual_extreme_values.get((section, name))
            if self._manual_cursors_apply_to_current_waveform()
            else None
        )
        t0_us, t1_us = restored if restored is not None else interval
        if (
            not is_short_circuit_param
            and manual_extreme is None
            and (restored is None or section == "反向恢复")
        ):
            self._focus_switching_local_view(section, t0_us, t1_us)
        self.wave_plot.enable_interval_interaction(
            start_t_us=t0_us,
            end_t_us=t1_us,
            on_change=_on_interval_change,
            on_horizontal_change=(
                _on_horizontal_extreme_change if name in _MAX_INTERVAL_NAMES else None
            ),
            show_horizontal_peak=name
            in {
                "Ic_off_max",
                "Vce_off_max",
                "Ic_on_max",
                "Vce_on_max",
                "Vrr",
                "短路能量Esc_本管",
                "应力Vpeak_本管",
                "短路能量Esc_对管",
                "应力Vpeak_对管",
                "Desat动作时间",
            },
        )
        # IEC 时间参数：点击仅对齐 A/B 光标；拖动 A/B 时由 on_change 重算并联动
        if (section, name) in self._IEC_TIMING_PARAMS:
            self._refresh_iec_timing_status(section, name, t0_us, t1_us)
        elif restored is not None and manual_extreme is None:
            _on_interval_change(t0_us, t1_us)
        elif manual_extreme is not None:
            self._store_extreme_metric_value(section, name, manual_extreme[1])
            self.statusBar().showMessage(
                f"{section}-{name}: 恢复手动 Ha={manual_extreme[0]:.3f}，"
                f"{name}={manual_extreme[1]:.3f}"
            )
        elif name in _MAX_INTERVAL_NAMES:
            stored = self._stored_param_value(section, name)
            if stored is not None:
                self.statusBar().showMessage(
                    f"{section}-{name} 区间最大值: [{t0_us:.3f},{t1_us:.3f}]us | "
                    f"{name}={stored:.3f}（拖动 A/B 后重算）"
                )
        elif name in short_energy_names:
            stored = self._stored_param_value(section, name)
            if stored is not None:
                self.statusBar().showMessage(
                    f"{section}-{name} 积分窗口: [{t0_us:.3f},{t1_us:.3f}]us | "
                    f"{name}={stored:.3f}（拖动 A/B 后重算）"
                )
        # 进入模式布置峰值横线（首次点击用 extract 结果，不重算）
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        ta, tb = min(t0_us, t1_us), max(t0_us, t1_us)
        if is_short_energy_param:
            marker = self._short_circuit_energy_peak_marker(name, i0, i1)
            if marker is not None:
                peak_y, peak_channel = marker
                self.wave_plot.set_interval_peak_horizontal(
                    float(peak_y),
                    channel=peak_channel,
                    t0_us=ta,
                    t1_us=tb,
                )
            cursors = self._short_circuit_ic_default_cursors()
            if cursors is not None:
                _ta, _tb, hb, _ha = cursors
                self.wave_plot.set_interval_base_horizontal(hb, channel="ic")
        elif short_vpeak_role is not None:
            voltage_channel, gate_role, gate_channel = short_vpeak_role
            peak_y = self._peak_y_for_param(section, name, i0, i1)
            if peak_y is not None:
                self.wave_plot.set_interval_peak_horizontal(
                    float(peak_y),
                    channel=self._channel_for_param(section, name),
                    t0_us=ta,
                    t1_us=tb,
                )
            cursors = self._short_circuit_vpeak_default_cursors(
                voltage_channel,
                gate_channel=gate_channel,
            )
            if cursors is not None:
                _ta, _tb, hb, _ha = cursors
                self.wave_plot.set_interval_base_horizontal(hb, channel=gate_role)
        elif is_short_desat_param:
            cursors = self._short_circuit_desat_default_cursors()
            desat_channel = self._short_circuit_desat_channel()
            if cursors is not None and desat_channel is not None:
                _ta, _tb, hb, ha = cursors
                self.wave_plot.set_interval_peak_horizontal(
                    ha,
                    channel=desat_channel,
                    t0_us=ta,
                    t1_us=tb,
                )
                self.wave_plot.set_interval_base_horizontal(hb, channel=desat_channel)
        else:
            if name in _MAX_INTERVAL_NAMES:
                self._set_extreme_horizontal_lines(
                    section,
                    name,
                    i0,
                    i1,
                    ta,
                    tb,
                    primary_override=manual_extreme[0]
                    if manual_extreme is not None
                    else None,
                )
            else:
                peak_y = self._peak_y_for_param(section, name, i0, i1)
                if peak_y is not None:
                    self.wave_plot.set_interval_peak_horizontal(
                        float(peak_y),
                        channel=self._channel_for_param(section, name),
                        t0_us=ta,
                        t1_us=tb,
                        use_abs_peak=name in {"Ic_off_max", "Ic_on_max"},
                    )
        if name in _MAX_INTERVAL_NAMES:
            if manual_extreme is not None:
                self.statusBar().showMessage(
                    f"{section}-{name}: 已恢复手动 Ha={manual_extreme[0]:.3f}，"
                    f"{name}={manual_extreme[1]:.3f}；Hb 为最小值参考"
                )
            else:
                self.statusBar().showMessage(
                    f"{section}-{name} 区间最大值模式：拖动 A/B 重算窗口最大值；"
                    "拖 Ha 手动改参数值，Hb 显示窗口最小值参考"
                )
        elif name in short_energy_names:
            self.statusBar().showMessage(
                f"{section}-{name} 积分窗口模式：拖动两根纵向光标，实时积分"
            )
        elif section == "短路过程":
            self._show_stored_metric_status(section, name)

    def _recompute_param_from_interval(
        self, section: str, name: str, i0: int, i1: int
    ) -> float | str | None:
        if self.bundle is None or self.result is None:
            return None
        if self._metric_unavailable(section, name):
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
        v_diode = self.bundle.maybe_get(self.profile.v_diode)
        vge_other = self.bundle.maybe_get(self.profile.vge_other)
        dur_ns = max(0.0, (t[i1] - t[i0]) * 1e9)

        if section == "短路过程":
            sc = self.result.short_circuit
            dur_us = max(0.0, (t[i1] - t[i0]) * 1e6)
            if name == "短路电流Imax":
                val = float(np.max(ic[i0 : i1 + 1]))
                sc.ic_max = val
                self.result.idc = val
                self.result.idc_set = val
                self.result_table.set_metric_value(section, name, val)
                return val
            if name == "短路时间Tsc":
                sc.tsc = dur_us
                sc.tsc_start_us = float(t[i0] * 1e6)
                sc.tsc_end_us = float(t[i1] * 1e6)
                self.result_table.set_metric_value(section, name, dur_us)
                return dur_us
            if name == "短路能量Esc_本管":
                val, source = short_circuit_energy_value(
                    self.bundle,
                    self.profile,
                    i0,
                    i1,
                    other=False,
                    math_channel=sc.energy_dut_channel or None,
                )
                sc.esc_dut = val
                sc.energy_dut_channel = source
                self.result_table.set_metric_value(section, name, val)
                return val
            if name == "应力Vpeak_本管":
                val = float(np.max(vce[i0 : i1 + 1]))
                sc.vpeak_dut = val
                self.result_table.set_metric_value(section, name, val)
                return val
            if name == "短路能量Esc_对管":
                val, source = short_circuit_energy_value(
                    self.bundle,
                    self.profile,
                    i0,
                    i1,
                    other=True,
                    math_channel=sc.energy_other_channel or None,
                )
                sc.esc_other = val
                sc.energy_other_channel = source
                self.result_table.set_metric_value(section, name, val)
                return val
            if name == "应力Vpeak_对管":
                if v_diode is None:
                    return None
                val = float(np.max(v_diode[i0 : i1 + 1]))
                sc.vpeak_other = val
                self.result_table.set_metric_value(section, name, val)
                return val
            if name == "Desat动作时间":
                sc.desat_time = dur_us
                if self._short_circuit_desat_default_cursors() is not None:
                    sc.desat_range = "Vdesat阈值"
                self.result_table.set_metric_value(section, name, dur_us)
                return dur_us

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
                if vge_other is None:
                    return None
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
                if vge_other is None:
                    return None
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
                if v_diode is None:
                    return None
                v = float(np.max(v_diode[i0 : i1 + 1]))
                self.result.reverse_recovery.vrr = v
                return v
            if name == "dv/dt":
                if v_diode is None:
                    return None
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
        if self._metric_unavailable(section, name):
            return None
        off = self.result.turn_off
        on = self.result.turn_on
        rr = self.result.reverse_recovery
        if self.result.short_circuit_mode and section == "短路过程":
            sc = self.result.short_circuit
            return {
                "短路电流Imax": sc.ic_max,
                "短路时间Tsc": sc.tsc,
                "短路能量Esc_本管": sc.esc_dut,
                "应力Vpeak_本管": sc.vpeak_dut,
                "短路能量Esc_对管": sc.esc_other,
                "应力Vpeak_对管": sc.vpeak_other,
                "Desat动作时间": sc.desat_time,
            }.get(name)
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
                "Pmax": off.pmax,
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
                "Pmax": on.pmax,
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
                "Pdmax": rr.pdmax,
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
        if self._metric_unavailable(section, name):
            return None
        from dpt_extractor.models.waveform import (
            bundle_reverse_recovery_current,
            bundle_total_current,
        )

        vce = self.bundle.get(self.profile.vce)
        ic = bundle_total_current(self.bundle, self.profile)
        irr = bundle_reverse_recovery_current(self.bundle, self.profile)
        v_diode = self.bundle.maybe_get(self.profile.v_diode)

        if section == "短路过程":
            if name in {"短路电流Imax", "短路时间Tsc"}:
                seg = np.asarray(ic[i0 : i1 + 1], dtype=np.float64)
                if len(seg) == 0:
                    return 0.0
                return float(np.nanmax(seg))
            if name in {"短路能量Esc_本管", "短路能量Esc_对管"}:
                return None
            if name == "应力Vpeak_本管":
                return float(np.max(vce[i0 : i1 + 1]))
            if name == "应力Vpeak_对管":
                if v_diode is None:
                    return None
                return float(np.max(v_diode[i0 : i1 + 1]))
            if name == "Desat动作时间":
                threshold_v = getattr(self.cfg, "short_circuit_desat_threshold_v", None)
                if threshold_v is not None:
                    return float(threshold_v)

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
                if v_diode is None:
                    return None
                return float(np.max(v_diode[i0 : i1 + 1]))
        return None

    def _secondary_y_for_param(
        self, section: str, name: str, i0: int, i1: int
    ) -> float | None:
        """同窗口辅助横线：max 型参数用 Hb 展示当前范围内的最小值。"""
        if self.bundle is None:
            return None
        if self._metric_unavailable(section, name):
            return None
        from dpt_extractor.models.waveform import (
            bundle_reverse_recovery_current,
            bundle_total_current,
        )

        vce = self.bundle.get(self.profile.vce)
        ic = bundle_total_current(self.bundle, self.profile)
        irr = bundle_reverse_recovery_current(self.bundle, self.profile)
        v_diode = self.bundle.maybe_get(self.profile.v_diode)

        if section == "短路过程":
            if name in {"短路电流Imax", "短路时间Tsc"}:
                seg = np.asarray(ic[i0 : i1 + 1], dtype=np.float64)
                if len(seg) == 0:
                    return None
                return float(np.nanmin(seg))
            if name == "应力Vpeak_本管":
                return float(np.nanmin(vce[i0 : i1 + 1]))
            if name == "应力Vpeak_对管":
                if v_diode is None:
                    return None
                return float(np.nanmin(v_diode[i0 : i1 + 1]))

        if section == "关断过程":
            if name == "Ic_off_max":
                seg = np.asarray(ic[i0 : i1 + 1], dtype=np.float64)
                if len(seg) == 0:
                    return None
                return float(np.nanmin(seg))
            if name == "Vce_off_max":
                return float(np.nanmin(vce[i0 : i1 + 1]))
        if section == "开通":
            if name == "Ic_on_max":
                seg = np.asarray(ic[i0 : i1 + 1], dtype=np.float64)
                if len(seg) == 0:
                    return None
                return float(np.nanmin(seg))
            if name == "Vce_on_max":
                return float(np.nanmin(vce[i0 : i1 + 1]))
        if section == "反向恢复":
            if name == "Irr":
                seg = np.asarray(irr[i0 : i1 + 1], dtype=np.float64)
                if len(seg) == 0:
                    return None
                return float(np.nanmin(seg))
            if name == "Vrr":
                if v_diode is None:
                    return None
                return float(np.nanmin(v_diode[i0 : i1 + 1]))
        return None

    def _metric_value_from_extreme_line(
        self, section: str, name: str, line_value: float
    ) -> float:
        _ = section
        if name in {"Ic_off_max", "Ic_on_max", "短路电流Imax"}:
            return abs(float(line_value))
        return float(line_value)

    def _store_extreme_metric_value(
        self, section: str, name: str, metric_value: float
    ) -> None:
        if self.result is None:
            return
        value = float(metric_value)
        if section == "关断过程":
            if name == "Ic_off_max":
                self.result.turn_off.ic_off_max = value
            elif name == "Vce_off_max":
                self.result.turn_off.vce_off_max = value
            else:
                return
            self.result_table.set_metric_value(section, name, value)
            return
        if section == "开通":
            if name == "Ic_on_max":
                self.result.turn_on.ic_on_max = value
            elif name == "Vce_on_max":
                self.result.turn_on.vce_on_max = value
            else:
                return
            self.result_table.set_metric_value(section, name, value)
            return
        if section == "反向恢复" and name == "Vrr":
            self.result.reverse_recovery.vrr = value
            self.result_table.set_metric_value(section, name, value)
            return
        if section == "短路过程":
            sc = self.result.short_circuit
            if name == "短路电流Imax":
                sc.ic_max = value
                self.result.idc = value
                self.result.idc_set = value
            elif name == "应力Vpeak_本管":
                sc.vpeak_dut = value
            elif name == "应力Vpeak_对管":
                sc.vpeak_other = value
            else:
                return
            self.result_table.set_metric_value(section, name, value)

    def _set_extreme_horizontal_lines(
        self,
        section: str,
        name: str,
        i0: int,
        i1: int,
        t0_us: float,
        t1_us: float,
        *,
        primary_override: float | None = None,
    ) -> None:
        channel = self._channel_for_param(section, name)
        if not channel:
            return
        primary = (
            float(primary_override)
            if primary_override is not None
            else self._peak_y_for_param(section, name, i0, i1)
        )
        if primary is None:
            return
        use_window_marker = primary_override is None
        self.wave_plot.set_interval_peak_horizontal(
            float(primary),
            channel=channel,
            t0_us=t0_us if use_window_marker else None,
            t1_us=t1_us if use_window_marker else None,
            use_abs_peak=name in {"Ic_off_max", "Ic_on_max"},
        )
        secondary = self._secondary_y_for_param(section, name, i0, i1)
        if secondary is not None:
            self.wave_plot.set_interval_base_horizontal(
                float(secondary), channel=channel
            )

    def _irr_peak_interactive(self, irr: np.ndarray, i0: int, i1: int) -> float:
        idx = self._irr_peak_index_interactive(irr, i0, i1)
        if idx is None:
            return 0.0
        return abs(float(np.asarray(irr, dtype=np.float64)[idx]))

    def _irr_peak_index_interactive(
        self, irr: np.ndarray, i0: int, i1: int
    ) -> int | None:
        arr = np.asarray(irr, dtype=np.float64)
        if len(arr) == 0:
            return None
        i0 = max(0, min(int(i0), len(arr) - 1))
        i1 = max(i0, min(int(i1), len(arr) - 1))
        if self.result is not None and self.result.segments is not None:
            from dpt_extractor.metrics.irr_measure import irr_parameter_peak_index

            segs = self.result.segments
            idx = int(
                irr_parameter_peak_index(
                    arr,
                    segs.reverse_recovery[0],
                    segs.reverse_recovery[1],
                    segs.pulse2_on,
                    segs.turn_on[0],
                    segs.turn_on[1],
                )
            )
            if i0 <= idx <= i1:
                return idx

        seg = arr[i0 : i1 + 1]
        if len(seg) == 0:
            return None
        pos_i = int(np.nanargmax(seg))
        neg_i = int(np.nanargmin(seg))
        peak_pos = float(seg[pos_i])
        peak_neg = abs(float(seg[neg_i]))
        amp = max(peak_pos, peak_neg, 1.0)
        if peak_pos >= 0.1 * amp:
            return i0 + pos_i
        if peak_neg >= 0.1 * amp:
            return i0 + neg_i
        return i0 + pos_i

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
            pulse2_off=segs.pulse2_off,
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
        Trr 默认 A/B 使用同一套核心 marker，避免默认光标与表格值分叉。
        """
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.metrics.irr_measure import default_irr_trr_measure

        t = self.bundle.t
        segs = self.result.segments
        rr0, rr1 = segs.reverse_recovery
        on0, on1 = segs.turn_on
        irr = bundle_reverse_recovery_current(self.bundle, self.profile)
        marker = default_irr_trr_measure(t, irr, rr0, rr1, segs.pulse2_on, on0, on1)
        if marker is None:
            return None
        return float(marker.ta_s * 1e6), float(marker.tb_s * 1e6)

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

    def _short_circuit_ic_default_cursors(
        self,
    ) -> tuple[float, float, float, float] | None:
        """Default short-circuit current cursors at the Ic-Hb crossings."""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.models.waveform import bundle_total_current

        t = self.bundle.t
        if len(t) == 0:
            return None
        ic = np.asarray(bundle_total_current(self.bundle, self.profile), dtype=np.float64)
        gate0, gate1 = self.result.segments.turn_off
        cursors = short_circuit_current_cursors(
            t,
            ic,
            gate0,
            gate1,
            self.bundle.dt,
            smooth_ns=self.cfg.smoothing.detect_window_ns,
        )
        if cursors is None and len(t) > 1:
            cursors = short_circuit_current_cursors(
                t,
                ic,
                0,
                len(t) - 1,
                self.bundle.dt,
                smooth_ns=self.cfg.smoothing.detect_window_ns,
            )
        if cursors is None:
            i0 = max(0, min(int(gate0), len(t) - 1))
            i1 = max(i0, min(int(gate1), len(t) - 1))
            return t[i0] * 1e6, t[i1] * 1e6, 0.0, 0.0
        return (
            cursors.t_a_s * 1e6,
            cursors.t_b_s * 1e6,
            cursors.hb_a,
            cursors.ha_a,
        )

    def _short_circuit_tsc_cursors(
        self,
    ) -> tuple[float, float, float, float] | None:
        """Short-circuit Tsc cursors using the selected Tsc range only."""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        start_pct, end_pct, normalized = short_circuit_tsc_range_percentages(
            self.cfg.short_circuit_tsc_range
        )
        if normalized == SHORT_CIRCUIT_TSC_RANGE_DEFAULT:
            return self._short_circuit_ic_default_cursors()
        if abs(start_pct - end_pct) > 1e-12:
            return self._short_circuit_ic_default_cursors()
        from dpt_extractor.models.waveform import bundle_total_current

        t = self.bundle.t
        if len(t) == 0:
            return None
        ic = np.asarray(bundle_total_current(self.bundle, self.profile), dtype=np.float64)
        gate0, gate1 = self.result.segments.turn_off
        cursors = short_circuit_current_percent_cursors(
            t,
            ic,
            gate0,
            gate1,
            self.bundle.dt,
            smooth_ns=self.cfg.smoothing.detect_window_ns,
            percent=start_pct,
        )
        if cursors is None and len(t) > 1:
            cursors = short_circuit_current_percent_cursors(
                t,
                ic,
                0,
                len(t) - 1,
                self.bundle.dt,
                smooth_ns=self.cfg.smoothing.detect_window_ns,
                percent=start_pct,
            )
        if cursors is None:
            return self._short_circuit_ic_default_cursors()
        return (
            cursors.t_a_s * 1e6,
            cursors.t_b_s * 1e6,
            cursors.hb_a,
            cursors.ha_a,
        )

    def _short_circuit_vpeak_default_cursors(
        self,
        voltage_channel: str,
        gate_channel: str | None = None,
    ) -> tuple[float, float, float, float] | None:
        """Default Vpeak cursors: A/B and Hb from mapped Vge, Ha from voltage max."""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        t = self.bundle.t
        if len(t) == 0:
            return None
        gate_ref = gate_channel or self.profile.vge
        vge = np.asarray(self.bundle.get(gate_ref), dtype=np.float64)
        voltage = np.asarray(self.bundle.get(voltage_channel), dtype=np.float64)
        gate0, gate1 = self.result.segments.turn_off
        cursors = short_circuit_vpeak_cursors(
            t,
            vge,
            voltage,
            gate0,
            gate1,
            self.bundle.dt,
            smooth_ns=self.cfg.smoothing.detect_window_ns,
        )
        if cursors is None:
            i0 = max(0, min(int(gate0), len(t) - 1))
            i1 = max(i0, min(int(gate1), len(t) - 1))
            seg = np.asarray(voltage[i0 : i1 + 1], dtype=np.float64)
            ha = float(np.nanmax(seg)) if len(seg) else 0.0
            return t[i0] * 1e6, t[i1] * 1e6, 0.0, ha
        return (
            cursors.t_a_s * 1e6,
            cursors.t_b_s * 1e6,
            cursors.hb_a,
            cursors.ha_a,
        )

    def _short_circuit_desat_channel(self) -> str | None:
        if self.bundle is None:
            return None
        return find_desat_voltage_channel(self.bundle, getattr(self.profile, "vdesat", ""))

    def _short_circuit_desat_default_cursors(
        self,
    ) -> tuple[float, float, float, float] | None:
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        desat_channel = self._short_circuit_desat_channel()
        threshold_v = getattr(self.cfg, "short_circuit_desat_threshold_v", None)
        if desat_channel is None or threshold_v is None:
            return None
        t = self.bundle.t
        if len(t) == 0:
            return None
        gate0, gate1 = self.result.segments.turn_off
        cursors = short_circuit_desat_cursors(
            t,
            np.asarray(self.bundle.get(self.profile.vge), dtype=np.float64),
            np.asarray(self.bundle.get(desat_channel), dtype=np.float64),
            gate0,
            gate1,
            self.bundle.dt,
            threshold_v=float(threshold_v),
            smooth_ns=self.cfg.smoothing.detect_window_ns,
        )
        if cursors is None:
            return None
        return (
            cursors.t_a_s * 1e6,
            cursors.t_b_s * 1e6,
            cursors.hb_a,
            cursors.ha_a,
        )

    def _short_circuit_energy_peak_marker(
        self,
        name: str,
        i0: int,
        i1: int,
    ) -> tuple[float, str] | None:
        """Return a displayable Ha marker for short-circuit Esc, if a real trace exists."""
        if self.bundle is None or self.result is None:
            return None
        sc = self.result.short_circuit
        other = name == "短路能量Esc_对管"
        math_channel = sc.energy_other_channel if other else sc.energy_dut_channel
        peak, source = short_circuit_energy_peak_value(
            self.bundle,
            self.profile,
            i0,
            i1,
            other=other,
            math_channel=math_channel or None,
        )
        if source and self.bundle.has_channel_reference(source):
            return float(peak), source
        return None

    def _short_circuit_ic_window_indices(self) -> tuple[int, int] | None:
        cursors = self._short_circuit_ic_default_cursors()
        if cursors is None or self.bundle is None:
            return None
        t_a_us, t_b_us, _hb, _ha = cursors
        t = self.bundle.t
        if len(t) == 0:
            return None
        i0 = int(np.searchsorted(t, min(t_a_us, t_b_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t_a_us, t_b_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0, min(i1, len(t) - 1))
        return i0, i1

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
            vge = self.bundle.get(self.profile.vge)
            vce = self.bundle.get(self.profile.vce)
            vce_top = turn_on_vce_top_from_ic_rise(
                ic, vce, segs.pulse2_on, segs.pulse2_off, dt
            )
            return _clip_pair(
                *turn_on_vce_on_max_window_indices(
                    t,
                    vge,
                    vce,
                    segs.turn_on[0],
                    segs.turn_on[1],
                    segs.pulse2_on,
                    segs.pulse2_off,
                    dt,
                    vce_top,
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
        if self._metric_unavailable(section, name):
            return None
        t = self.bundle.t
        segs = self.result.segments

        if self.result.short_circuit_mode and section == "短路过程":
            if name in {
                "短路电流Imax",
                "短路能量Esc_本管",
                "短路能量Esc_对管",
            }:
                cursors = self._short_circuit_ic_default_cursors()
                if cursors is not None:
                    t_a_us, t_b_us, _hb, _ha = cursors
                    return t_a_us, t_b_us
            if name == "短路时间Tsc":
                cursors = self._short_circuit_tsc_cursors()
                if cursors is not None:
                    t_a_us, t_b_us, _hb, _ha = cursors
                    return t_a_us, t_b_us
            if name == "应力Vpeak_本管":
                cursors = self._short_circuit_vpeak_default_cursors(self.profile.vce)
                if cursors is not None:
                    t_a_us, t_b_us, _hb, _ha = cursors
                    return t_a_us, t_b_us
            if name == "应力Vpeak_对管":
                cursors = self._short_circuit_vpeak_default_cursors(
                    self.profile.v_diode,
                    gate_channel=self.profile.vge,
                )
                if cursors is not None:
                    t_a_us, t_b_us, _hb, _ha = cursors
                    return t_a_us, t_b_us
            if name == "Desat动作时间":
                cursors = self._short_circuit_desat_default_cursors()
                if cursors is not None:
                    t_a_us, t_b_us, _hb, _ha = cursors
                    return t_a_us, t_b_us
                return None
            i0, i1 = segs.turn_off
            return t[i0] * 1e6, t[i1] * 1e6

        iec_interval = self._iec_timing_interval_us(section, name)
        if iec_interval is not None:
            return iec_interval

        # 直接窗口型参数
        if section == "关断过程" and name in {"Eoff", "Pmax", "Pdmax"}:
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
        if section == "开通" and name in {"Eon", "Pmax", "Pdmax"}:
            from dpt_extractor.models.waveform import bundle_total_current

            vce = self.bundle.get(self.profile.vce)
            i = bundle_total_current(self.bundle, self.profile)
            w = eon_window_scope_example(
                t,
                i,
                vce,
                segs.turn_on[0],
                segs.turn_on[1],
                segs.pulse2_on,
                self.bundle.dt,
                pulse1_off=segs.pulse1_off,
            )
            return w.t_start * 1e6, w.t_end * 1e6
        if section == "反向恢复" and name in {"Err", "Pdmax"}:
            from dpt_extractor.models.waveform import bundle_reverse_recovery_current

            irr_sig = bundle_reverse_recovery_current(self.bundle, self.profile)
            rr0, rr1 = segs.reverse_recovery
            markers = err_energy_markers(
                t,
                irr_sig,
                self.bundle.get(self.profile.v_diode),
                rr0,
                rr1,
                self.bundle.dt,
                i_search_end=segs.turn_on[1],
                vge=self.bundle.get(self.profile.vge),
                pulse1_off=segs.pulse1_off,
                pulse2_on=segs.pulse2_on,
                pulse2_off=segs.pulse2_off,
                dc_current=self.result.idc,
                lower_bridge_irr_from_ic_minus_il=self.profile.irr_from_ic_minus_il,
            )
            w = markers.as_integration_window()
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
        self._sync_plot_math_to_bundle()
        try:
            self.cfg.slope_ranges = dict(self._slope_ranges)
            if parse_test_mode(self.cfg.test_mode.mode) == TestMode.OFFSET_MEASUREMENT:
                if reset_manual:
                    self._clear_manual_adjustments()
                self._enter_offset_measurement_mode()
                return
            active_param = self._active_slope_param
            if reset_manual:
                self._clear_manual_adjustments()
                active_param = None
            try:
                self.result = run_extraction(self.bundle, self.profile, self.cfg)
            except Exception as exc:
                self.result = None
                self._clear_manual_adjustments(reset_plot=False)
                self.wave_plot.plot_waveforms(self.bundle, self.profile, None)
                mode_label = MODE_UI_LABELS[parse_test_mode(self.cfg.test_mode.mode)]
                self.result_table.set_mode_placeholder(
                    mode_label,
                    self._extraction_placeholder_detail(str(exc)),
                )
                self.statusBar().showMessage(
                    f"{mode_label}：参数未计算，波形已保留"
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

            if self.result.short_circuit_mode:
                sc = self.result.short_circuit
                vdc_disp = self.result.vdc_set if self.result.vdc_set is not None else self.result.vdc
                self.statusBar().showMessage(
                    f"短路工况  Udc={vdc_disp:.1f} V  Imax={sc.ic_max:.0f} A  |  "
                    f"Tsc={sc.tsc:.3f} us  Esc本管={sc.esc_dut:.3f} J  Esc对管={sc.esc_other:.3f} J"
                )
                return

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

    def _update_report_template_tooltip(self) -> None:
        if self._report_template_source_path is None:
            tip = "加载完整报告模板源；未加载时使用内置数据模板生成新报告"
        else:
            tip = f"当前报告模板源:\n{self._report_template_source_path}"
        self.btn_select_report_template.setToolTip(tip)

    def _update_report_output_tooltip(self) -> None:
        if self._report_output_path is None:
            tip = "选择当前项目的报告文件路径；写入时会记住并复用"
        else:
            tip = f"当前项目报告文件:\n{self._report_output_path}"
        self.btn_select_report_output.setToolTip(tip)

    def _select_report_template(self) -> None:
        fallback = (
            self._report_template_source_path.parent
            if self._report_template_source_path is not None
            else Path(self._current_path).parent
            if self._current_path
            else Path.home()
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "加载报告模板源",
            str(fallback),
            "Excel 报告 (*.xlsx);;All (*)",
        )
        if not path:
            return
        selected = Path(path)
        self._report_template_source_path = selected
        set_report_template_source_path(selected)
        self._update_report_template_tooltip()
        self.statusBar().showMessage(
            f"已加载报告模板源: {selected.name}",
            3500,
        )

    def _select_report_output_path(self) -> bool:
        suggested = self._report_output_path or self._suggest_report_output_path()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "选择项目报告文件",
            save_dialog_initial_path(suggested),
            "Excel 报告 (*.xlsx)",
        )
        if not path:
            return False
        selected = Path(path)
        if selected.suffix.lower() != ".xlsx":
            selected = selected.with_suffix(".xlsx")
        template = self._current_report_template_source()
        if template is not None and selected.resolve() == template.resolve():
            QMessageBox.warning(
                self,
                "报告位置不可用",
                "项目报告文件不能与报告模板源文件相同，请选择另一个保存位置。",
            )
            return False
        self._report_output_path = selected
        set_report_output_path(selected)
        set_last_export_path(selected)
        self._update_report_output_tooltip()
        self.statusBar().showMessage(f"已设置项目报告文件: {selected.name}", 3500)
        return True

    def _safe_report_image_name(self, section: str, name: str, index: int) -> str:
        raw = f"{index:02d}_{section}_{name}.png"
        return re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", raw)

    def _report_plot_capture_size(self) -> QSize:
        return QSize(REPORT_PLOT_CAPTURE_SIZE)

    def _report_target_screen_width_px(self) -> int | None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return None
        return max(1, int(screen.availableGeometry().width()))

    def _save_report_plot_capture(self, path: Path, size: QSize) -> None:
        target = self.wave_plot
        if size.width() <= 0 or size.height() <= 0:
            raise ValueError("报告截图尺寸必须大于 0")

        # 直接抓取当前可见波形，再仅在内存中缩放/留边。不要通过 setFixedSize
        # 改变布局；报告逐参数截图期间只允许波形视窗变化，主窗口几何尺寸必须稳定。
        source = target.grab()
        if source.isNull() or source.width() <= 0 or source.height() <= 0:
            raise RuntimeError("报告波形截图失败：未能获取可见波形")
        if source.width() < 320 or source.height() < 200:
            raise RuntimeError(
                "报告波形截图失败：可见波形区域过小，无法确认光标和波形内容"
            )

        # 防止隐藏/未完成绘制的控件产生尺寸正常但实际只有纯色背景的 PNG。
        # 缩到小预览后抽样即可，避免报告逐参数截图时增加明显开销。
        preview = source.scaled(
            QSize(64, 48),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        ).toImage()
        sampled_colors: dict[tuple[int, int, int], int] = {}
        min_luma, max_luma = 255, 0
        opaque_samples = 0
        for py in range(preview.height()):
            for px in range(preview.width()):
                color = preview.pixelColor(px, py)
                if color.alpha() == 0:
                    continue
                rgb = (color.red(), color.green(), color.blue())
                sampled_colors[rgb] = sampled_colors.get(rgb, 0) + 1
                opaque_samples += 1
                luma = (54 * rgb[0] + 183 * rgb[1] + 19 * rgb[2]) // 256
                min_luma = min(min_luma, luma)
                max_luma = max(max_luma, luma)
        # 不能把“颜色种类少”直接等同为空白：正常未载入波形的完整控件只有
        # 少量主题色，高 DPI 测试替身也可能是单一的非背景色。仅当画面近乎
        # 纯色，并且主色确实是波形控件的已知背景色时才判为空白。
        dominant_rgb = (
            max(sampled_colors.items(), key=lambda item: item[1])[0]
            if sampled_colors
            else None
        )
        dominant_ratio = (
            sampled_colors[dominant_rgb] / opaque_samples
            if dominant_rgb is not None and opaque_samples > 0
            else 1.0
        )
        luma_span = max_luma - min_luma if opaque_samples > 0 else 0
        nearly_solid = (
            opaque_samples == 0
            or dominant_ratio >= 0.995
            or (len(sampled_colors) <= 4 and luma_span <= 8)
        )
        blank_backgrounds = (
            (0, 0, 0),
            (17, 18, 31),  # WaveformPlotRoot
            (21, 21, 21),  # overview plot
            (16, 17, 26),  # channel strip
        )

        def _near_blank_background(rgb: tuple[int, int, int] | None) -> bool:
            if rgb is None:
                return True
            return any(
                max(abs(rgb[idx] - bg[idx]) for idx in range(3)) <= 4
                for bg in blank_backgrounds
            )

        if nearly_solid and _near_blank_background(dominant_rgb):
            raise RuntimeError(
                "报告波形截图失败：截图仅包含空白或纯色背景，请等待波形绘制完成"
            )
        # grab() 在高 DPI 屏幕上携带设备像素比；报告 PNG 以固定物理像素输出，
        # 合成前归一到 DPR=1，避免 125%/150% 缩放时内容再次缩小并偏离中心。
        source.setDevicePixelRatio(1.0)

        canvas = QPixmap(size)
        canvas.fill(QColor("#11121f"))
        scaled = source.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (size.width() - scaled.width()) // 2
        y = (size.height() - scaled.height()) // 2
        painter = QPainter(canvas)
        try:
            painter.drawPixmap(x, y, scaled)
        finally:
            painter.end()

        if not canvas.save(str(path), "PNG"):
            raise RuntimeError(f"报告波形截图保存失败：{path.name}")
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"报告波形截图不完整：{path.name}")

    def _capture_report_images(self, directory: Path) -> dict[tuple[str, str], Path]:
        if self.result is None:
            return {}
        params = self._report_image_params()
        if not self._report_progress_active:
            self._begin_report_progress(REPORT_PROGRESS_TOTAL, "准备报告截图...")
        capture_start = max(0, min(self.report_progress.value(), REPORT_PROGRESS_TEMPLATE_DONE))
        capture_span = max(1, REPORT_PROGRESS_CAPTURE_DONE - capture_start)
        capture_total = max(1, len(params) + 1)
        self._set_report_progress(
            capture_start,
            REPORT_PROGRESS_TOTAL,
            "准备报告截图...",
        )
        images: dict[tuple[str, str], Path] = {}
        vb = self.wave_plot.plot.getPlotItem().getViewBox()
        old_x, old_y = vb.viewRange()
        try:
            self.wave_plot._fit_full_range()
            QApplication.processEvents()
            capture_size = self._report_plot_capture_size()
            for index, (section, name) in enumerate(params, start=1):
                if (section, name) == DPT_OVERVIEW_IMAGE_PARAM:
                    self.wave_plot._fit_full_range()
                elif self.result.short_circuit_mode:
                    self.wave_plot._fit_full_range()
                    self._on_value_clicked(section, name)
                    self.wave_plot._fit_full_range()
                else:
                    self._on_value_clicked(section, name)
                QApplication.processEvents()
                path = directory / self._safe_report_image_name(section, name, index)
                self._save_report_plot_capture(path, capture_size)
                images[(section, name)] = path
                progress_value = capture_start + int(
                    round(capture_span * index / capture_total)
                )
                self._set_report_progress(
                    min(progress_value, REPORT_PROGRESS_CAPTURE_DONE),
                    REPORT_PROGRESS_TOTAL,
                    f"截图 {index}/{len(params)} · {name}",
                )
        finally:
            vb.setRange(
                xRange=(float(old_x[0]), float(old_x[1])),
                yRange=(float(old_y[0]), float(old_y[1])),
                padding=0.0,
            )
        self._set_report_progress(
            REPORT_PROGRESS_CAPTURE_DONE,
            REPORT_PROGRESS_TOTAL,
            "截图完成，准备写入 Excel...",
        )
        return images

    def _start_report_capture_sequence(
        self,
        tempdir: tempfile.TemporaryDirectory,
        results: list[ExtractResult],
    ) -> None:
        if self.result is None:
            tempdir.cleanup()
            self._set_report_busy(False)
            return
        params = self._report_image_params()
        if not self._report_progress_active:
            self._begin_report_progress(REPORT_PROGRESS_TOTAL, "准备报告截图...")
        capture_start = max(0, min(self.report_progress.value(), REPORT_PROGRESS_TEMPLATE_DONE))
        vb = self.wave_plot.plot.getPlotItem().getViewBox()
        old_x, old_y = vb.viewRange()
        self._report_request_id += 1
        request_id = self._report_request_id
        self._report_capture_state = _ReportCaptureState(
            request_id=request_id,
            tempdir=tempdir,
            directory=Path(tempdir.name),
            params=params,
            results=results,
            old_x=[float(old_x[0]), float(old_x[1])],
            old_y=[float(old_y[0]), float(old_y[1])],
            capture_start=capture_start,
            capture_span=max(1, REPORT_PROGRESS_CAPTURE_DONE - capture_start),
            capture_size=self._report_plot_capture_size(),
            images={},
        )
        self._set_report_progress(capture_start, REPORT_PROGRESS_TOTAL, "准备报告截图...")
        self.wave_plot._fit_full_range()
        QTimer.singleShot(0, self._capture_next_report_image)

    def _restore_report_capture_view(self, state: _ReportCaptureState) -> None:
        vb = self.wave_plot.plot.getPlotItem().getViewBox()
        vb.setRange(
            xRange=(state.old_x[0], state.old_x[1]),
            yRange=(state.old_y[0], state.old_y[1]),
            padding=0.0,
        )

    def _capture_next_report_image(self) -> None:
        state = self._report_capture_state
        if state is None:
            return
        if state.request_id != self._report_request_id:
            state.tempdir.cleanup()
            self._report_capture_state = None
            return
        try:
            total = len(state.params)
            if state.index >= total:
                self._restore_report_capture_view(state)
                self._set_report_progress(
                    REPORT_PROGRESS_CAPTURE_DONE,
                    REPORT_PROGRESS_TOTAL,
                    "截图完成，准备写入 Excel...",
                )
                images = state.images or {}
                tempdir = state.tempdir
                results = state.results
                request_id = state.request_id
                self._report_capture_state = None
                self._start_report_write_task(
                    tempdir,
                    images,
                    results,
                    request_id=request_id,
                )
                return

            section, name = state.params[state.index]
            display_index = state.index + 1
            if (section, name) == DPT_OVERVIEW_IMAGE_PARAM:
                self.wave_plot._fit_full_range()
            elif self.result is not None and self.result.short_circuit_mode:
                self.wave_plot._fit_full_range()
                self._on_value_clicked(section, name)
                self.wave_plot._fit_full_range()
            else:
                self._on_value_clicked(section, name)
            QApplication.processEvents()
            path = state.directory / self._safe_report_image_name(
                section,
                name,
                display_index,
            )
            self._save_report_plot_capture(path, state.capture_size)
            if state.images is not None:
                state.images[(section, name)] = path
            progress_value = state.capture_start + int(
                round(state.capture_span * display_index / max(1, total + 1))
            )
            self._set_report_progress(
                min(progress_value, REPORT_PROGRESS_CAPTURE_DONE),
                REPORT_PROGRESS_TOTAL,
                f"截图 {display_index}/{total} · {name}",
            )
            state.index = display_index
            QTimer.singleShot(0, self._capture_next_report_image)
        except Exception as exc:
            try:
                self._restore_report_capture_view(state)
            finally:
                state.tempdir.cleanup()
                self._report_capture_state = None
                self._set_report_busy(False)
                self._finish_report_progress("写入失败", ok=False)
            QMessageBox.critical(self, "写入报告失败", str(exc))

    def _short_desat_image_available(self) -> bool:
        if self.result is None or not self.result.short_circuit_mode:
            return False
        if self.result.short_circuit.desat_time is None:
            return False
        return self._short_circuit_desat_channel() is not None

    def _report_image_params(self) -> tuple[tuple[str, str], ...]:
        if self.result is None:
            return ()
        if not self.result.short_circuit_mode:
            return dpt_report_image_params_for_result(self.result)
        return tuple(
            param
            for param in SHORT_REPORT_IMAGE_PARAMS
            if not self.result.is_metric_unavailable(*param)
            and (
                param != ("短路过程", "Desat动作时间")
                or self._short_desat_image_available()
            )
        )

    def _results_for_export_or_report(self) -> list[ExtractResult]:
        if self.result is None:
            return []
        if (
            self.bundle is None
            or self.result.short_circuit_mode
            or self.result.single_pulse_mode
            or self.result.detected_pulse_count <= 2
        ):
            return [self.result]
        return dpt_export_results(self.bundle, self.profile, self.cfg, self.result)

    def _current_report_template_source(self) -> Path | None:
        if self._report_template_source_path is not None:
            return self._report_template_source_path
        return default_report_template_path()

    def _suggest_report_output_path(self) -> Path:
        template = self._current_report_template_source()
        report_name = (
            template.name
            if template is not None and template.suffix.lower() == ".xlsx"
            else "DPT_report.xlsx"
        )
        if self._current_path:
            base_dir = Path(self._current_path).parent
        elif self.result is not None:
            base_dir = default_export_path(self.result).parent
        else:
            base_dir = Path.home()
        suggested = base_dir / report_name
        if template is not None:
            try:
                if suggested.resolve() == template.resolve():
                    suggested = suggested.with_name(f"{suggested.stem}_报告.xlsx")
            except OSError:
                pass
        return suggested

    def _ensure_report_output_file(self) -> bool:
        if self._report_output_path is None:
            if not self._select_report_output_path():
                return False
        if self._report_output_path is None:
            return False

        target = self._report_output_path
        if target.exists():
            return True

        src = self._current_report_template_source()
        if src is None or not src.is_file():
            QMessageBox.critical(
                self,
                "缺少报告模板",
                "已加载的报告模板不存在，请重新加载模板源。\n\n"
                f"模板:\n{src}",
            )
            return False

        try:
            self._begin_report_progress(REPORT_PROGRESS_TOTAL, "复制模板...")
            self._set_report_progress(
                REPORT_PROGRESS_TEMPLATE_DONE // 2,
                REPORT_PROGRESS_TOTAL,
                "复制模板...",
            )
            self._report_output_path = copy_report_template(src, target)
            self._set_report_progress(
                REPORT_PROGRESS_TEMPLATE_DONE,
                REPORT_PROGRESS_TOTAL,
                "模板复制完成",
            )
        except PermissionError as exc:
            self._finish_report_progress("写入失败", ok=False)
            QMessageBox.critical(
                self,
                "生成报告失败",
                "无法写入报告文件，请确认目标文件未被 Excel 打开且目录可写。\n\n"
                f"文件:\n{target}\n\n错误:\n{exc}",
            )
            return False
        except Exception as exc:
            self._finish_report_progress("写入失败", ok=False)
            QMessageBox.critical(self, "生成报告失败", str(exc))
            return False

        set_report_output_path(self._report_output_path)
        set_last_export_path(self._report_output_path)
        self._update_report_output_tooltip()
        self.statusBar().showMessage(
            f"已从报告模板生成项目报告: {self._report_output_path.name}",
            3500,
        )
        return True

    def _write_report_template(self) -> None:
        if self.result is None:
            QMessageBox.warning(self, "提示", "无提取结果可写入报告")
            return
        if not self._ensure_report_output_file():
            return
        tempdir = None
        self._set_report_busy(True)
        try:
            report_results = self._results_for_export_or_report()
            if not self._report_progress_active:
                self._begin_report_progress(
                    REPORT_PROGRESS_TOTAL,
                    "准备报告截图...",
                )
            tempdir = tempfile.TemporaryDirectory()
            self._start_report_capture_sequence(tempdir, report_results)
            tempdir = None
        except PermissionError as e:
            if tempdir is not None:
                tempdir.cleanup()
            self._set_report_busy(False)
            self._finish_report_progress("写入失败", ok=False)
            QMessageBox.critical(
                self,
                "写入报告失败",
                "无法保存报告文件，通常是这个 .xlsx 正在被 Excel 打开或没有写入权限。\n"
                "请先关闭该报告文件，再点击“写入报告”。\n\n"
                f"文件:\n{self._report_output_path}\n\n"
                f"错误:\n{e}",
            )
        except Exception as e:
            if tempdir is not None:
                tempdir.cleanup()
            self._set_report_busy(False)
            self._finish_report_progress("写入失败", ok=False)
            QMessageBox.critical(self, "写入报告失败", str(e))

    def _start_report_write_task(
        self,
        tempdir: tempfile.TemporaryDirectory,
        images: dict[tuple[str, str], Path],
        results: list[ExtractResult],
        *,
        request_id: int | None = None,
    ) -> None:
        if self.result is None or self._report_output_path is None:
            tempdir.cleanup()
            return
        if request_id is None:
            self._report_request_id += 1
            request_id = self._report_request_id
        task = _ReportWriteTask(
            request_id,
            results if len(results) > 1 else results[0],
            self._report_output_path,
            images,
            tempdir,
            self._report_target_screen_width_px(),
            self._temperature_display_labels(),
        )
        task.signals.progress.connect(self._on_report_write_progress)
        task.signals.finished.connect(self._on_report_write_finished)
        task.signals.failed.connect(self._on_report_write_failed)
        self._report_tasks[request_id] = task
        self._set_report_busy(True)
        self._set_report_progress(
            REPORT_PROGRESS_WRITE_START,
            REPORT_PROGRESS_TOTAL,
            "正在写入 Excel...",
        )
        self._load_pool.start(task)

    def _on_report_write_progress(
        self,
        request_id: int,
        value: int,
        total: int,
        label: str,
    ) -> None:
        if request_id != self._report_request_id:
            return
        total = max(1, int(total))
        ratio = max(0.0, min(float(value) / total, 1.0))
        span = REPORT_PROGRESS_WRITE_DONE_CAP - REPORT_PROGRESS_WRITE_START
        progress_value = REPORT_PROGRESS_WRITE_START + int(round(span * ratio))
        self._set_report_progress(
            min(progress_value, REPORT_PROGRESS_WRITE_DONE_CAP),
            REPORT_PROGRESS_TOTAL,
            label,
        )

    def _on_report_write_finished(
        self,
        request_id: int,
        summary: ReportWriteSummary,
        elapsed_ms: float,
    ) -> None:
        self._report_tasks.pop(request_id, None)
        if request_id != self._report_request_id:
            return
        self._set_report_busy(False)
        self._finish_report_progress("写入完成 100%", ok=True)
        if self._report_output_path is not None:
            set_report_output_path(self._report_output_path)
            set_last_export_path(self._report_output_path)
        self._update_report_output_tooltip()
        self.statusBar().showMessage(
            f"已写入报告: {summary.report_path.name} | "
            f"{summary.data_sheet} 第 {summary.data_row}"
            f"{'' if summary.data_rows_written == 1 else f'-{summary.data_row_end}'} 行 | "
            f"图片 {summary.images_written} 张 | 保存 {elapsed_ms:.0f} ms",
            6000,
        )
        row_text = (
            f"{summary.data_row} 行"
            if summary.data_rows_written == 1
            else f"{summary.data_row}-{summary.data_row_end} 行（{summary.data_rows_written} 行）"
        )
        QMessageBox.information(
            self,
            "写入成功",
            f"已写入:\n{summary.report_path}\n\n"
            f"数据位置: {summary.data_sheet} 第 {row_text}\n"
            f"图片: {summary.images_written} 张",
        )

    def _on_report_write_failed(self, request_id: int, message: str) -> None:
        self._report_tasks.pop(request_id, None)
        if request_id != self._report_request_id:
            return
        self._set_report_busy(False)
        self._finish_report_progress("写入失败", ok=False)
        QMessageBox.critical(self, "写入报告失败", message)

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
            rows = self._results_for_export_or_report()
            export_to_excel(rows if len(rows) > 1 else rows[0], path)
            set_last_export_path(path)
            suffix = "" if len(rows) == 1 else f"\n\n数据行数: {len(rows)}"
            QMessageBox.information(self, "导出成功", f"已保存:\n{path}{suffix}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
