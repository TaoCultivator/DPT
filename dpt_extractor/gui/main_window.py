from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path
import re
import tempfile
import time
from typing import Callable
import numpy as np

from PyQt6 import sip
from PyQt6.QtCore import QLocale, QObject, QRunnable, QSize, QThreadPool, Qt, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCloseEvent, QDoubleValidator, QPainter, QPalette, QPixmap, QResizeEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
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
    DptReportConditions,
    ReportConditions,
    SHORT_REPORT_IMAGE_PARAMS,
    ReportWriteSummary,
    ShortReportConditions,
    dpt_report_image_params_for_result,
    infer_dpt_report_conditions,
    infer_short_report_conditions,
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
from dpt_extractor.gui.task_progress import (
    ReportStageBudgetEstimator,
    ReportTimingContext,
    ReportTimingHistory,
    UnitRateEstimator,
    format_duration_ms,
)
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
from dpt_extractor.io.label_mapping import infer_profile_hint_from_labels
from dpt_extractor.io.tek_scope import (
    ScopeViewState,
    read_tektronix_scope,
    sync_tektronix_scope,
)
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
    slope_range_result_label,
)
from dpt_extractor.models.waveform import WaveformBundle, normalize_channel_reference
from dpt_extractor.metrics.iec_windows import (
    IntegrationWindow,
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
    DidtMeasurementContext,
    DidtCrossingResult,
    DvdtMeasurementContext,
    DvdtCrossingResult,
    RrDidtMeasurementContext,
    RrDidtPreparedSeries,
    analyze_rr_recovery_current,
    auto_didt_between_base_top,
    auto_dvdt_between_base_top,
    auto_rr_didt_between_levels,
    auto_rr_didt_between_prepared_levels,
    didt_between_base_top,
    didt_max,
    dvdt_between_base_top,
    dvdt_max,
    prepare_rr_didt_series,
    rr_dvdt_measurement_context,
    rr_dvdt_prefers_settled_platform,
    rr_didt_between_levels,
    rr_didt_between_prepared_levels,
    rr_didt_measurement_context,
    turn_on_dvdt_measurement_context,
    turn_on_didt_measurement_context,
    turn_off_didt_measurement_context,
    turn_off_dvdt_measurement_context,
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
from dpt_extractor.pipeline.pulse_sequence import (
    dpt_export_pulse_pairs,
    dpt_export_results,
)
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
REPORT_PROGRESS_PREPARE_DONE = 15000
REPORT_PROGRESS_CAPTURE_DONE = 55000
REPORT_PROGRESS_WRITE_START = REPORT_PROGRESS_CAPTURE_DONE
REPORT_PROGRESS_WRITE_TEMPLATE_DONE = 57500
REPORT_PROGRESS_WRITE_DATA_DONE = 60000
REPORT_PROGRESS_WRITE_IMAGES_DONE = 80000
REPORT_PROGRESS_WRITE_DONE_CAP = 85000
REPORT_TIMING_SETTINGS_KEY = "task_progress/report_timing_history_v1"
REPORT_TIMING_STAGE_ORDER = (
    "copy-template",
    "prepare",
    "capture",
    "open-workbook",
    "write-data",
    "write-images",
    "finalize-workbook",
    "save-workbook",
)


def report_timing_stage_windows(
    budgets_ms: dict[str, float],
) -> dict[str, tuple[float, float]]:
    """Allocate 1%-99.9% in proportion to predicted stage wall time."""

    durations = {
        stage: max(1.0, float(budgets_ms.get(stage, 1.0)))
        for stage in REPORT_TIMING_STAGE_ORDER
    }
    total = max(1.0, sum(durations.values()))
    cursor = 0.01
    windows: dict[str, tuple[float, float]] = {}
    for stage in REPORT_TIMING_STAGE_ORDER:
        end = cursor + 0.989 * durations[stage] / total
        windows[stage] = (cursor, min(0.999, end))
        cursor = end
    return windows
LOAD_PROGRESS_PARSE_DONE = 35000
LOAD_PROGRESS_MAPPING_DONE = 45000
LOAD_PROGRESS_EXTRACT_DONE = 85000
TEMP_CONDITION_DEFAULTS = {
    "RT": 25.0,
    "HT": 150.0,
    "LT": -40.0,
}
TEMP_CONDITION_SETTINGS_PREFIX = "conditions/temperature/"
SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY = "short_circuit/tsc_range"
REPORT_CONDITION_SETTINGS_PREFIX = "conditions/report/"
DPT_REPORT_CONDITION_FIELDS = (
    ("voltage_v", "Vdc", "V"),
    ("current_a", "Idc", "A"),
    ("rg_on_ohm", "Rg_on", "Ω"),
    ("rg_off_ohm", "Rg_off", "Ω"),
    ("cg_nf", "Cg", "nF"),
)
SHORT_REPORT_CONDITION_FIELDS = (
    ("vce_v", "Vce", "V"),
    ("imax_a", "Imax", "A"),
    ("cdesat_pf", "Cdesat", "pF"),
    ("rdesat_kohm", "Rdesat", "kΩ"),
    ("vdesat_v", "Vdesat", "V"),
)


def _app_settings() -> QSettings:
    """Create the production settings store; tests may inject an isolated store."""

    return QSettings("DPT", "DPTExtractor")

_REPORT_MANUAL_STATE_ATTRS = (
    "_manual_intervals",
    "_manual_extreme_values",
    "_manual_short_current",
    "_manual_turn_on_current",
    "_manual_energy",
    "_manual_delta_vce",
    "_manual_waveform_source",
    "_manual_pulse_pair",
    "_manual_dvdt",
    "_manual_didt",
    "_manual_trr_measure",
)


def _readonly_waveform_view(values: np.ndarray) -> np.ndarray:
    """Return a read-only ndarray view without copying waveform samples."""

    view = np.asarray(values).view()
    view.setflags(write=False)
    return view


def _snapshot_waveform_bundle(bundle: WaveformBundle | None) -> WaveformBundle | None:
    """Freeze report-visible bundle state while sharing immutable sample buffers."""

    if bundle is None:
        return None
    return WaveformBundle(
        t=_readonly_waveform_view(bundle.t),
        channels={
            key: _readonly_waveform_view(values)
            for key, values in bundle.channels.items()
        },
        meta=deepcopy(bundle.meta),
    )


def _safe_cleanup_tempdir(tempdir: tempfile.TemporaryDirectory | None) -> None:
    """Best-effort cleanup that must never suppress a report terminal signal."""

    if tempdir is None:
        return
    try:
        tempdir.cleanup()
    except Exception:
        # A report has already succeeded or failed at this point.  Windows can
        # transiently retain a PNG handle; cleanup must not overwrite that
        # authoritative task outcome or leave the GUI permanently busy.
        return


def _same_report_path(first: Path | None, second: Path | None) -> bool:
    """Compare report paths after resolving links and Windows case differences."""

    if first is None or second is None:
        return False
    try:
        first_text = str(first.expanduser().resolve(strict=False))
        second_text = str(second.expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        first_text = str(first.expanduser().absolute())
        second_text = str(second.expanduser().absolute())
    return first_text.casefold() == second_text.casefold()


def _format_temperature_number(value: float) -> str:
    fv = float(value)
    if abs(fv - round(fv)) < 0.05:
        return str(int(round(fv)))
    return f"{fv:.1f}".rstrip("0").rstrip(".")


def _format_temperature_label(value: float) -> str:
    return f"{_format_temperature_number(value)}℃"


def _nearest_raw_level_crossing_time_us(
    t: np.ndarray,
    values: np.ndarray,
    level: float,
    reference_index: int,
    search_start: int,
    search_end: int,
) -> float | None:
    """Project a detected/averaged level onto the nearest raw-waveform crossing."""

    tt = np.asarray(t, dtype=np.float64)
    yy = np.asarray(values, dtype=np.float64)
    if len(tt) < 2 or len(yy) != len(tt) or not np.isfinite(float(level)):
        return None
    lo = max(0, min(int(search_start), len(tt) - 2))
    hi = max(lo + 1, min(int(search_end), len(tt) - 1))
    ref = max(lo, min(int(reference_index), hi))
    ref_t = float(tt[ref])
    candidates: list[float] = []
    target = float(level)
    for k in range(lo, hi):
        y0, y1 = float(yy[k]), float(yy[k + 1])
        if not (np.isfinite(y0) and np.isfinite(y1)):
            continue
        if y0 == target:
            candidates.append(float(tt[k]))
            continue
        if y1 == target:
            candidates.append(float(tt[k + 1]))
            continue
        if (y0 - target) * (y1 - target) >= 0.0:
            continue
        frac = (target - y0) / (y1 - y0)
        candidates.append(float(tt[k] + frac * (tt[k + 1] - tt[k])))
    if not candidates:
        return None
    return float(min(candidates, key=lambda value: abs(value - ref_t))) * 1e6


class TemperatureSpinBox(QDoubleSpinBox):
    def textFromValue(self, value: float) -> str:  # noqa: N802
        return _format_temperature_number(value)


class ReportConditionEdit(QLineEdit):
    """Compact optional numeric editor used by the report-condition toolbar."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        validator = QDoubleValidator(0.0, 1_000_000_000.0, 6, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        validator.setLocale(QLocale.c())
        self.setValidator(validator)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def numeric_value(self) -> float | None:
        text = self.text().strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        return value if math.isfinite(value) and value >= 0.0 else None

    def set_numeric_value(self, value: float | None) -> None:
        if value is None or not math.isfinite(float(value)):
            self.clear()
            return
        self.setText(f"{float(value):g}")


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
        self._progress_fraction = 0.0
        self._format = "待命"
        self._busy = False
        self._running = False
        self._eta_active = False
        self._finished_ok = False
        self._task_started = False
        self._eta_estimator = UnitRateEstimator()
        self._report_eta_estimator: ReportStageBudgetEstimator | None = None
        self._density_mode = ""

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh_readout)

        lay = QHBoxLayout(self)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(8)

        self._stage_label = QLabel("任务进度")
        self._stage_label.setObjectName("reportProgressStage")
        self._detail_label = QLabel("待命")
        self._detail_label.setObjectName("reportProgressDetail")
        self._detail_label.setMinimumWidth(62)
        self._detail_label.setMaximumWidth(180)

        self._sep_a = QLabel("|")
        self._sep_a.setObjectName("reportProgressSeparator")
        self._sep_b = QLabel("|")
        self._sep_b.setObjectName("reportProgressSeparator")
        self._sep_c = QLabel("|")
        self._sep_c.setObjectName("reportProgressSeparator")

        self._bar = QProgressBar()
        self._bar.setObjectName("reportProgressTrack")
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 100000)
        self._bar.setValue(0)
        self._bar.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._bar.setMinimumWidth(36)

        self._percent_label = QLabel("0.0%")
        self._percent_label.setObjectName("reportProgressPercent")
        self._percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._percent_label.setMinimumWidth(74)
        self._eta_label = QLabel("—")
        self._eta_label.setObjectName("reportProgressEta")
        self._eta_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._eta_label.setMinimumWidth(50)
        self._eta_caption = QLabel("当前阶段预计剩余")
        self._eta_caption.setObjectName("reportProgressEtaCaption")

        lay.addWidget(self._stage_label)
        lay.addWidget(self._sep_a)
        lay.addWidget(self._detail_label)
        lay.addWidget(self._sep_b)
        lay.addWidget(self._bar, stretch=1)
        lay.addWidget(self._percent_label)
        lay.addWidget(self._sep_c)
        lay.addWidget(self._eta_caption)
        lay.addWidget(self._eta_label)
        self.setAccessibleName("任务进度")
        self.reset_idle()
        # Start from the smallest valid layout so the parent can allocate a
        # restored-window width before the first real resize event arrives.
        self._apply_density_for_width(0)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._apply_density_for_width(event.size().width())

    def _apply_density_for_width(self, width: int) -> None:
        """Keep the progress readout non-overlapping at restored window widths."""

        width = max(0, int(width))
        if width < 340:
            mode = "tiny"
        elif width < 470:
            mode = "compact"
        elif width < 620:
            mode = "medium"
        else:
            mode = "full"
        if mode == self._density_mode:
            return
        self._density_mode = mode

        full = mode == "full"
        medium = mode == "medium"
        tiny = mode == "tiny"
        show_detail = full or medium
        show_separators = full

        self._detail_label.setVisible(show_detail)
        for separator in (self._sep_a, self._sep_b, self._sep_c):
            separator.setVisible(show_separators)
        self._eta_caption.setVisible(not tiny)
        self._eta_caption.setText(
            "预计剩余"
            if self._report_eta_estimator is not None
            else "当前阶段预计剩余"
            if full
            else "剩余"
        )

        layout = self.layout()
        if layout is not None:
            margin = 6 if tiny else 8 if not full else 10
            layout.setContentsMargins(margin, 0, margin, 0)
            layout.setSpacing(4 if tiny else 6 if not full else 8)

        self._detail_label.setMinimumWidth(50 if medium else 62)
        self._detail_label.setMaximumWidth(108 if medium else 180)
        self._percent_label.setMinimumWidth(56 if tiny else 62 if not full else 74)
        self._eta_label.setMinimumWidth(46 if tiny else 48 if not full else 50)
        self._bar.setMinimumWidth(32 if tiny else 44 if not full else 52)

    def set_stage(self, stage: str) -> None:
        self._stage_label.setText(str(stage or "任务进度"))
        self._refresh_tooltip()

    def begin(self, total: int, label: str, *, stage: str = "任务进度") -> None:
        self._busy = False
        self._running = True
        self._eta_active = False
        self._finished_ok = False
        self._task_started = True
        self._eta_estimator = UnitRateEstimator()
        self._report_eta_estimator = None
        self._eta_caption.setText(
            "当前阶段预计剩余" if self._density_mode == "full" else "剩余"
        )
        self.set_stage(stage)
        # Reset atomically so a previous successful 100% cannot flash while
        # the new task's range is being installed.
        self._minimum = 0
        self._maximum = max(1, int(total))
        self._value = 0
        self._progress_fraction = 0.0
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
        eta_phase: str | None = None,
        eta_completed: int = 0,
        eta_total: int = 0,
    ) -> None:
        # A terminal state is immutable.  This also blocks a queued progress
        # signal from the same request from rewriting 100% after ``finished``.
        if not self._running:
            return
        self._busy = False
        self._finished_ok = False
        self._task_started = True
        if stage is not None:
            self.set_stage(stage)
        self._set_running_progress_value(value, total)
        self.setFormat(label)
        self._eta_active = eta_phase is not None
        if eta_phase is not None:
            self._eta_estimator.observe(
                eta_phase,
                int(eta_completed),
                max(0, int(eta_total)),
            )
        self._timer.start()
        self.show()
        self._refresh_readout()

    def begin_report_timing(
        self,
        budgets_ms: dict[str, float],
        stage_windows: dict[str, tuple[float, float]],
        initial_stage: str,
    ) -> None:
        """Attach a whole-task report model to the active progress task."""

        if not self._running:
            return
        self._report_eta_estimator = ReportStageBudgetEstimator(
            budgets_ms,
            stage_windows,
        )
        self._report_eta_estimator.observe(initial_stage)
        self._eta_caption.setText("预计剩余")
        self._refresh_readout()

    def observe_report_timing(
        self,
        stage: str,
        completed: int = 0,
        total: int = 0,
    ) -> None:
        if self._running and self._report_eta_estimator is not None:
            self._report_eta_estimator.observe(stage, completed, total)

    def finish_report_timing(self) -> dict[str, float]:
        if self._report_eta_estimator is None:
            return {}
        durations = self._report_eta_estimator.finish()
        self._report_eta_estimator = None
        return durations

    def update_busy_progress(
        self,
        value: int,
        total: int,
        label: str,
        *,
        stage: str | None = None,
    ) -> None:
        """Atomically publish a completed checkpoint followed by an atomic phase."""

        if not self._running:
            return
        self._busy = True
        self._eta_active = False
        self._finished_ok = False
        self._task_started = True
        if stage is not None:
            self.set_stage(stage)
        self._set_running_progress_value(value, total)
        self._format = str(label or "")
        self._detail_label.setText(self._detail_text(self._format))
        self._detail_label.setToolTip(self._format)
        self._timer.start()
        self.show()
        self._refresh_readout()

    def set_busy(self, label: str, *, stage: str | None = None) -> None:
        if not self._running:
            return
        self._busy = True
        self._eta_active = False
        self._finished_ok = False
        self._task_started = True
        if stage is not None:
            self.set_stage(stage)
        self.setFormat(label)
        self._timer.start()
        self.show()
        self._refresh_readout()

    def _set_running_progress_value(self, value: int, total: int) -> None:
        """Publish a monotonic, non-terminal checkpoint for the active task."""

        new_minimum = 0
        new_maximum = max(1, int(total))
        requested = max(new_minimum, min(int(value), new_maximum))
        requested_fraction = requested / new_maximum
        if self._report_eta_estimator is not None:
            projected = self._report_eta_estimator.projected_fraction()
            if projected is not None:
                requested_fraction = projected
        fraction = max(self._progress_fraction, requested_fraction)

        # One-decimal rendering means 99.95% would round to 100.0%.  Keep all
        # running states at or below 99.9%; only finish(ok=True) may publish
        # the authoritative 100%/0 ms terminal state.
        ceiling = max(
            new_minimum,
            int(math.floor(new_maximum * 0.999 + 1e-12)),
        )
        fraction = min(fraction, 0.999)
        self._progress_fraction = fraction
        next_value = int(round(fraction * new_maximum))
        self._minimum = new_minimum
        self._maximum = new_maximum
        self._value = max(new_minimum, min(next_value, ceiling))

    def finish(self, label: str, *, ok: bool, stage: str | None = None) -> None:
        # The first terminal signal wins.  Duplicate or contradictory queued
        # callbacks must not rewrite a completed task's result.
        if not self._running:
            return
        self._busy = False
        self._running = False
        self._eta_active = False
        self._finished_ok = bool(ok)
        self._task_started = True
        if stage is not None:
            self.set_stage(stage)
        if ok:
            self._progress_fraction = 1.0
            self.setRange(0, 100)
            self.setValue(100)
        self.setFormat(label)
        self._refresh_readout()
        self._timer.stop()
        self.show()

    def reset_idle(self) -> None:
        self._busy = False
        self._running = False
        self._eta_active = False
        self._finished_ok = False
        self._task_started = False
        self._report_eta_estimator = None
        self._progress_fraction = 0.0
        self.set_stage("任务进度")
        self.setRange(0, 100)
        self.setValue(0)
        self.setFormat("待命")
        self._timer.stop()
        self._eta_label.setText("—")
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

    def eta_caption_text(self) -> str:
        return self._eta_caption.text()

    def detail_text(self) -> str:
        return self._detail_label.text()

    def stage_text(self) -> str:
        return self._stage_label.text()

    def is_busy(self) -> bool:
        return self._busy

    def _percent(self) -> float:
        if self._task_started:
            percent = 100.0 * self._progress_fraction
        else:
            span = self._maximum - self._minimum
            if span <= 0:
                return 0.0
            percent = 100.0 * (self._value - self._minimum) / span
        if self._task_started and percent < 100.0:
            return max(1.0, percent)
        return percent

    def _refresh_readout(self) -> None:
        if self._running and self._report_eta_estimator is not None:
            projected = self._report_eta_estimator.projected_fraction()
            if projected is not None:
                projected = max(self._progress_fraction, min(0.999, projected))
                self._progress_fraction = projected
                ceiling = int(math.floor(self._maximum * 0.999 + 1e-12))
                self._value = min(ceiling, int(round(projected * self._maximum)))
        percent = max(0.0, min(100.0, self._percent()))
        self._bar.setRange(0, 100000)
        self._bar.setValue(int(round(percent * 1000.0)))
        self._percent_label.setText(f"{percent:0.1f}%")
        if percent >= 100.0 and not self._running and self._finished_ok:
            eta_text = "0 ms"
        elif not self._running:
            eta_text = "—"
        elif self._report_eta_estimator is not None:
            eta_ms = self._report_eta_estimator.eta_ms()
            if eta_ms is None or eta_ms <= 0.0:
                eta_text = "估算中"
            elif eta_ms < 1000.0:
                eta_text = "<1 s"
            else:
                eta_text = format_duration_ms(eta_ms)
        elif self._busy or not self._eta_active:
            eta_text = "估算中"
        else:
            eta_ms = self._eta_estimator.eta_ms()
            if eta_ms is None or eta_ms <= 0.0:
                eta_text = "估算中"
            elif eta_ms < 1000.0:
                # GUI repaint and queued worker callbacks make millisecond digits
                # look much more precise than they are.  Preserve the useful
                # "finishing within a second" signal without presenting false
                # precision; exact ``0 ms`` remains reserved for success.
                eta_text = "<1 s"
            else:
                eta_text = format_duration_ms(eta_ms)
        self._eta_label.setText(eta_text)
        self._refresh_tooltip()

    def _refresh_tooltip(self) -> None:
        detail = self._format.strip() or self._detail_label.text().strip() or "待命"
        eta_scope = (
            "整个任务预计剩余"
            if self._report_eta_estimator is not None
            else "当前阶段预计剩余"
        )
        eta_note = (
            "预计剩余时间由本机同类报告分阶段历史耗时并结合当前进度校正"
            if self._report_eta_estimator is not None
            else "预计剩余时间仅按当前同质阶段估算"
        )
        description = (
            f"{self.stage_text()}：{detail}\n"
            f"进度 {self.percent_text()}；{eta_scope} {self.eta_text()}\n"
            f"百分比表示整个后台任务进度；{eta_note}"
        )
        self.setToolTip(description)
        self.setAccessibleDescription(description)

    @staticmethod
    def _format_duration_ms(ms: float) -> str:
        return format_duration_ms(ms)

    @staticmethod
    def _detail_text(label: str) -> str:
        text = str(label or "").strip()
        text = re.sub(r"[.。…]+$", "", text)
        replacements = (
            ("准备读取原始数据", "准备读取"),
            ("读取原始数据", "读取"),
            ("解析波形数据", "解析波形"),
            ("读取完成，正在识别通道", "识别通道"),
            ("识别通道", "识别通道"),
            ("通道识别完成，正在计算参数", "参数计算"),
            ("执行参数计算", "参数计算"),
            ("参数计算完成，准备刷新界面", "刷新界面"),
            ("正在刷新界面并绘制波形", "绘制波形"),
            ("刷新界面", "刷新界面"),
            ("绘制波形", "绘制波形"),
            ("导入完成", "导入完成"),
            ("导入失败", "导入失败"),
            ("准备报告截图", "准备截图"),
            ("准备报告文件", "准备报告"),
            ("报告文件已就绪，准备分析数据", "分析数据"),
            ("报告数据准备完成，准备截图", "准备截图"),
            ("截图完成，准备写入 Excel", "准备写入 Excel"),
            ("正在打开并写入 Excel", "写入 Excel"),
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
    *,
    prefer_labels: bool = False,
) -> _AutoProfileCandidate | None:
    base_profile = make_profile(phase, bridge)
    inferred, inferred_source = infer_best_mapping_from_bundle(
        bundle,
        bridge,
        prefer_labels=prefer_labels,
    )
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
    *,
    ignore_path_bridge_hint: bool = False,
    prefer_labels: bool = False,
) -> _AutoProfileCandidate | None:
    if not ignore_path_bridge_hint and has_bridge_hint_from_path(path):
        return None
    candidates: list[_AutoProfileCandidate] = []
    bridges = [guessed.bridge, "lower" if guessed.bridge == "upper" else "upper"]
    for bridge in dict.fromkeys(bridges):
        candidate = _auto_dpt_profile_candidate(
            bundle,
            cfg,
            guessed.phase,
            bridge,
            prefer_labels=prefer_labels,
        )
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.score)


def _compute_waveform_load_outcome(
    path: str,
    cfg: AppConfig,
    progress_callback: Callable[[int, int, str, str, int, int], None] | None = None,
    *,
    waveform_reader: Callable[[Callable[[int, int, str], None]], WaveformBundle]
    | None = None,
) -> _WaveformLoadOutcome:
    profile_hint_path = path

    def emit_progress(
        value: int,
        label: str,
        *,
        eta_phase: str = "",
        eta_completed: int = 0,
        eta_total: int = 0,
    ) -> None:
        if progress_callback is not None:
            progress_callback(
                value,
                TASK_PROGRESS_TOTAL,
                label,
                eta_phase,
                eta_completed,
                eta_total,
            )

    def emit_waveform_progress(done: int, total: int, label: str) -> None:
        total_i = max(1, int(total))
        done_i = max(0, min(int(done), total_i))
        value = int(round(LOAD_PROGRESS_PARSE_DONE * done_i / total_i))
        emit_progress(
            value,
            label,
            eta_phase="load-waveform-channels",
            eta_completed=done_i,
            eta_total=total_i,
        )

    emit_progress(0, "读取原始数据...")
    load_t0 = time.perf_counter()
    if waveform_reader is None:
        bundle = load_waveform(path, progress_callback=emit_waveform_progress)
    else:
        bundle = waveform_reader(emit_waveform_progress)
        idn_fields = tuple(
            part.strip() for part in bundle.meta.instrument_idn.split(",")
        )
        model = idn_fields[1] if len(idn_fields) > 1 else bundle.meta.model
        serial = idn_fields[2] if len(idn_fields) > 2 else ""
        path = "_".join(part for part in (model, serial) if part) + ".scope"
    load_t1 = time.perf_counter()
    emit_progress(LOAD_PROGRESS_PARSE_DONE, "读取完成，正在识别通道...")

    guessed = guess_profile_from_path(profile_hint_path)
    scope_phase_hint: str | None = None
    scope_bridge_hint: str | None = None
    mapping_store = ChannelMappingStore()
    source_path = bundle.meta.source_path or path
    current_scope_mapping = (
        mapping_store.get(
            guessed.phase,
            guessed.bridge,
            source_path=source_path,
        )
        if bundle.meta.source_kind == "scope"
        else None
    )
    if bundle.meta.source_kind == "scope" and current_scope_mapping is None:
        scope_phase_hint, scope_bridge_hint = infer_profile_hint_from_labels(
            bundle.meta.channel_labels
        )
        guessed = make_profile(
            scope_phase_hint or guessed.phase,
            scope_bridge_hint or guessed.bridge,
        )
    base_profile = make_profile(guessed.phase, guessed.bridge)
    custom_mapping = mapping_store.get(
        guessed.phase,
        guessed.bridge,
        source_path=source_path,
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
                prefer_labels=bundle.meta.source_kind == "scope",
            )
            if inferred is not None:
                profile = apply_mapping(base_profile, inferred)
    else:
        profile = _profile_for_test_mode(profile, cfg)
    emit_progress(LOAD_PROGRESS_MAPPING_DONE, "通道识别完成，正在计算参数...")

    extract_t0 = time.perf_counter()
    extraction_error = ""
    try:
        if mode == TestMode.OFFSET_MEASUREMENT:
            result = None
            short_circuit_not_ready = False
        elif mode == TestMode.DPT and custom_mapping is None:
            selected = _select_ambiguous_bridge_dpt_profile(
                profile_hint_path,
                bundle,
                cfg,
                guessed,
                ignore_path_bridge_hint=(
                    bundle.meta.source_kind == "scope"
                    and scope_bridge_hint is None
                ),
                prefer_labels=bundle.meta.source_kind == "scope",
            )
            if selected is not None:
                profile = selected.profile
                inferred = selected.inferred
                inferred_source = selected.inferred_source
                result = selected.result
                if bundle.meta.source_kind == "scope":
                    guessed = make_profile(guessed.phase, profile.bridge)
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
    emit_progress(LOAD_PROGRESS_EXTRACT_DONE, "参数计算完成，准备刷新界面...")

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
    progress = pyqtSignal(int, int, int, str, str, int, int)
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
                progress_callback=lambda value, total, label, eta_phase, eta_completed, eta_total: self.signals.progress.emit(
                    self.request_id,
                    value,
                    total,
                    label,
                    eta_phase,
                    eta_completed,
                    eta_total,
                ),
            )
        except Exception as exc:
            self.signals.failed.emit(self.request_id, self.path, str(exc))
            return
        self.signals.finished.emit(self.request_id, outcome)


class _ScopeLoadTask(QRunnable):
    def __init__(self, request_id: int, cfg: AppConfig, profile_code: str) -> None:
        super().__init__()
        self.request_id = request_id
        self.cfg = cfg
        self.profile_code = profile_code
        self.signals = _WaveformLoadSignals()

    def run(self) -> None:
        try:
            outcome = _compute_waveform_load_outcome(
                f"{self.profile_code}_USB_示波器",
                self.cfg,
                progress_callback=lambda value, total, label, eta_phase, eta_completed, eta_total: self.signals.progress.emit(
                    self.request_id,
                    value,
                    total,
                    label,
                    eta_phase,
                    eta_completed,
                    eta_total,
                ),
                waveform_reader=lambda progress: read_tektronix_scope(
                    progress_callback=progress
                ),
            )
        except Exception as exc:
            self.signals.failed.emit(self.request_id, "scope://usb", str(exc))
            return
        self.signals.finished.emit(self.request_id, outcome)


class _ScopeSyncSignals(QObject):
    finished = pyqtSignal(int)
    failed = pyqtSignal(int, str)


class _ScopeSyncTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        resource: str,
        state: ScopeViewState,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.resource = resource
        self.state = state
        self.signals = _ScopeSyncSignals()

    def run(self) -> None:
        try:
            sync_tektronix_scope(self.resource, self.state)
        except Exception as exc:
            self.signals.failed.emit(self.request_id, str(exc))
            return
        self.signals.finished.emit(self.request_id)


class _ReportWriteSignals(QObject):
    progress = pyqtSignal(int, int, int, str)
    finished = pyqtSignal(int, object, float)
    failed = pyqtSignal(int, str)


class _ReportPrepareSignals(QObject):
    progress = pyqtSignal(int, int, int, str)
    finished = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)


def _report_image_result_index(
    results: list[ExtractResult],
    current_result: ExtractResult,
) -> int:
    current_pair = (
        int(current_result.off_pulse_index),
        int(current_result.on_pulse_index),
    )
    for index, result in enumerate(results):
        if (
            int(result.off_pulse_index),
            int(result.on_pulse_index),
        ) == current_pair:
            return index
    return 0


class _ReportPrepareTask(QRunnable):
    """在后台准备报告数据行，避免多脉冲重复提取阻塞界面。"""

    def __init__(
        self,
        request_id: int,
        bundle: WaveformBundle | None,
        profile: BridgeProfile,
        cfg: AppConfig,
        current_result: ExtractResult,
        temperature_code: str | None = None,
        temperature_labels: dict[str, str] | None = None,
        phase_code: str | None = None,
        slope_ranges: dict[str, SlopeRange] | None = None,
        manual_state: dict[str, object] | None = None,
        active_metric: tuple[str, str] | None = None,
        active_slope_param: tuple[str, str] | None = None,
        display_state: dict[str, object] | None = None,
        report_conditions: ReportConditions | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.bundle = _snapshot_waveform_bundle(bundle)
        self.profile = profile
        self.cfg = deepcopy(cfg)
        self.current_result = deepcopy(current_result)
        self.temperature_code = temperature_code
        self.temperature_labels = dict(temperature_labels or {})
        self.phase_code = phase_code
        self.slope_ranges = deepcopy(slope_ranges or cfg.slope_ranges)
        self.manual_state = deepcopy(manual_state or {})
        self.active_metric = deepcopy(active_metric)
        self.active_slope_param = deepcopy(active_slope_param)
        self.display_state = deepcopy(display_state or {})
        self.report_conditions = deepcopy(
            report_conditions
            if report_conditions is not None
            else ShortReportConditions()
            if current_result.short_circuit_mode
            else DptReportConditions()
        )
        self.signals = _ReportPrepareSignals()

    def run(self) -> None:
        try:
            result = self.current_result
            if (
                self.bundle is None
                or result.short_circuit_mode
                or result.single_pulse_mode
                or result.detected_pulse_count <= 2
            ):
                rows = [result]
                self.signals.progress.emit(
                    self.request_id,
                    1,
                    1,
                    "报告数据准备完成",
                )
            else:
                rows = dpt_export_results(
                    self.bundle,
                    self.profile,
                    self.cfg,
                    result,
                    progress_callback=lambda done, total: self.signals.progress.emit(
                        self.request_id,
                        done,
                        total,
                        f"分析脉冲组合 {done}/{total}",
                    ),
                )
        except Exception as exc:
            self.signals.failed.emit(self.request_id, str(exc))
            return
        self.signals.finished.emit(self.request_id, rows)


@dataclass
class _ReportPageState:
    bundle: WaveformBundle | None
    profile: BridgeProfile
    cfg: AppConfig
    result: ExtractResult | None
    slope_ranges: dict[str, SlopeRange]
    manual_state: dict[str, object]
    active_metric: tuple[str, str] | None
    active_slope_param: tuple[str, str] | None
    display_state: dict[str, object]


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
    temperature_code: str
    temperature_labels: dict[str, str]
    phase_code: str
    report_conditions: ReportConditions
    image_result_index: int
    capture_page: _ReportPageState
    restore_page: _ReportPageState
    snapshot_active: bool = False
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
        temperature_code: str | None = None,
        phase_code: str | None = None,
        image_result_index: int = 0,
        report_conditions: ReportConditions | None = None,
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.result = result
        self.report_path = report_path
        self.images = images
        self.tempdir = tempdir
        self.target_screen_width_px = target_screen_width_px
        self.temperature_labels = dict(temperature_labels)
        self.temperature_code = temperature_code
        self.phase_code = phase_code
        self.image_result_index = int(image_result_index)
        result0 = result[0] if isinstance(result, list) else result
        self.report_conditions = deepcopy(
            report_conditions
            if report_conditions is not None
            else ShortReportConditions()
            if result0.short_circuit_mode
            else DptReportConditions()
        )
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
                temperature_code=self.temperature_code,
                phase_code=self.phase_code,
                image_result_index=self.image_result_index,
                report_conditions=self.report_conditions,
                progress_callback=lambda value, total, label: self.signals.progress.emit(
                    self.request_id,
                    value,
                    total,
                    label,
                ),
            )
        except PermissionError as exc:
            _safe_cleanup_tempdir(self.tempdir)
            self.signals.failed.emit(
                self.request_id,
                "无法保存报告文件，通常是这个 .xlsx 正在被 Excel 打开或没有写入权限。\n"
                "请先关闭该报告文件，再点击“写入报告”。\n\n"
                f"文件:\n{self.report_path}\n\n"
                f"错误:\n{exc}",
            )
            return
        except Exception as exc:
            _safe_cleanup_tempdir(self.tempdir)
            self.signals.failed.emit(self.request_id, str(exc))
            return
        _safe_cleanup_tempdir(self.tempdir)
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
        # 短路 Imax/Tsc：保存 A/B 时刻 + Hb/Ha 电平 (µs, µs, A, A)
        self._manual_short_current: dict[
            tuple[str, str], tuple[float, float, float, float]
        ] = {}
        # 开通电流：保存 A/B 时刻 + Hb/Ha 电平 (µs, µs, A, A)
        self._manual_turn_on_current: tuple[float, float, float, float] | None = None
        # Eoff/Eon 四光标 (A_t, B_t, Ha_v, Hb_a)
        self._manual_energy: dict[tuple[str, str], tuple[float, float, float, float]] = {}
        # ΔVce 四光标状态 (A_t, B_t, Ha_v, Hb_v)，再次点击时恢复
        self._manual_delta_vce: dict[tuple[str, str], tuple[float, float, float, float]] = {}
        # 手动光标绑定的波形源路径；换文件后不再恢复旧光标位置
        self._manual_waveform_source: str = ""
        # 同一原始记录的不同脉冲组合互不复用手调状态。
        self._manual_pulse_pair: tuple[int, int] | None = None
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
        self._load_tasks: dict[int, QRunnable] = {}
        self._scope_sync_request_id = 0
        self._scope_sync_tasks: dict[int, _ScopeSyncTask] = {}
        self._pending_parameter_local_view_restore: tuple[
            tuple[str, str], tuple[float, float]
        ] | None = None
        self._report_request_id = 0
        self._report_prepare_tasks: dict[int, _ReportPrepareTask] = {}
        self._report_tasks: dict[int, _ReportWriteTask] = {}
        self._report_capture_state: _ReportCaptureState | None = None
        self._report_progress_active = False
        self._report_timing_history = ReportTimingHistory.from_json(
            _app_settings().value(
                REPORT_TIMING_SETTINGS_KEY,
                "",
            )
        )
        self._active_report_timing_context: ReportTimingContext | None = None
        self._report_writes_this_session = 0
        self._report_operation_active = False
        self._report_interaction_locked = False
        self._report_toolbar_enabled_states: list[tuple[QWidget, bool]] = []
        self._report_focus_policies: list[tuple[QWidget, Qt.FocusPolicy]] = []
        self._report_result_table_enabled = True
        self._report_waveform_mouse_transparent = False
        self._report_splitter_mouse_transparent = False
        self._load_pool = QThreadPool.globalInstance()
        self._scope_io_pool = QThreadPool(self)
        self._scope_io_pool.setMaxThreadCount(1)
        self._license_notice_dialog: QDialog | None = None
        self._license_notice_timer = QTimer(self)
        self._license_notice_timer.setSingleShot(True)
        self._license_notice_timer.timeout.connect(self._show_first_run_license_notice)
        self._temperature_values = self._load_temperature_values()
        self._report_condition_context: tuple[str, str] | None = None

        self._build_ui()
        self.result_table.set_range_handler(self._on_slope_range_changed)
        self.result_table.set_short_circuit_tsc_range_handler(
            self._on_short_circuit_tsc_range_changed
        )
        self.result_table.set_eoff_pre_handler(self._on_eoff_pre_changed)
        self.result_table.set_value_click_handler(self._on_result_value_clicked)
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
        self.wave_plot.scopeZoomSyncRequested.connect(
            self._on_plot_zoom_sync_requested
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
        self.lbl_top_status = QLabel("请读取示波器或打开 Tektronix TSS 会话文件")
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

        self.btn_scope = QPushButton("读取示波器")
        self.btn_scope.setObjectName("primaryButton")
        self.btn_scope.clicked.connect(self._read_scope_waveform)

        self.btn_open = QPushButton("打开 TSS")
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
        self.combo_temp.setToolTip(
            "当前报告温度工况；加载时按路径识别，手动选择后以当前选择为准"
        )
        self.combo_temp.currentIndexChanged.connect(self._on_temperature_changed)

        self.spin_temp_value = TemperatureSpinBox()
        self.spin_temp_value.setObjectName("tempValue")
        self.spin_temp_value.setRange(-100.0, 250.0)
        self.spin_temp_value.setDecimals(1)
        self.spin_temp_value.setSingleStep(1.0)
        self.spin_temp_value.setSuffix(" ℃")
        self.spin_temp_value.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spin_temp_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_temp_value.setToolTip(
            "自定义当前工况温度；写入报告时采用，单位固定为 ℃"
        )
        self.spin_temp_value.setValue(self._temperature_values["RT"])
        self.spin_temp_value.valueChanged.connect(self._on_temperature_value_changed)

        self.report_condition_group = QFrame()
        self.report_condition_group.setObjectName("reportConditions")
        report_condition_layout = QHBoxLayout(self.report_condition_group)
        report_condition_layout.setContentsMargins(6, 2, 6, 2)
        report_condition_layout.setSpacing(3)
        self.lbl_report_conditions = QLabel("工况")
        self.lbl_report_conditions.setObjectName("reportConditionsTitle")
        report_condition_layout.addWidget(self.lbl_report_conditions)
        self._report_condition_edits: list[ReportConditionEdit] = []
        self._report_condition_field_labels: list[QLabel] = []
        self._report_condition_unit_labels: list[QLabel] = []
        for _key, label_text, unit_text in DPT_REPORT_CONDITION_FIELDS:
            label = QLabel(label_text)
            label.setObjectName("reportConditionLabel")
            edit = ReportConditionEdit()
            edit.setObjectName("reportConditionValue")
            unit = QLabel(unit_text)
            unit.setObjectName("reportConditionUnit")
            report_condition_layout.addWidget(label)
            report_condition_layout.addWidget(edit)
            report_condition_layout.addWidget(unit)
            edit.editingFinished.connect(self._save_current_report_conditions)
            self._report_condition_edits.append(edit)
            self._report_condition_field_labels.append(label)
            self._report_condition_unit_labels.append(unit)

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
        row_controls.addWidget(self.btn_scope)
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
        row_controls.addWidget(self.lbl_map_status)
        row_controls.addWidget(self.report_condition_group, stretch=1)
        row_controls.addWidget(self.btn_recalc)
        row_controls.addWidget(self.btn_export)
        row_controls.addWidget(self.btn_select_report_template)
        row_controls.addWidget(self.btn_select_report_output)
        row_controls.addWidget(self.btn_write_report)
        row_report_conditions = QHBoxLayout()
        row_report_conditions.setSpacing(5)
        self._toolbar_primary_row = row_controls
        self._toolbar_report_condition_row = row_report_conditions
        self._report_condition_in_primary_row = True
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

        self._toolbar_rows = (
            row_title,
            row_controls,
            row_report_conditions,
            row_tools,
        )
        self._toolbar_tool_sections = (
            row_tools_left,
            row_tools_right,
        )
        self._toolbar_density_bucket: str | None = None
        self._toolbar_text_mode: str | None = None

        tb_root.addLayout(row_title)
        tb_root.addLayout(row_controls)
        tb_root.addLayout(row_report_conditions)
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
        return _app_settings()

    def _should_show_license_notice(self) -> bool:
        raw = self._license_settings().value(
            NONCOMMERCIAL_NOTICE_SETTINGS_KEY, False, type=bool
        )
        return not bool(raw)

    def _mark_license_notice_shown(self) -> None:
        settings = self._license_settings()
        settings.setValue(NONCOMMERCIAL_NOTICE_SETTINGS_KEY, True)
        settings.sync()

    def _load_temperature_values(self) -> dict[str, float]:
        settings = _app_settings()
        values = dict(TEMP_CONDITION_DEFAULTS)
        for code, default in TEMP_CONDITION_DEFAULTS.items():
            raw = settings.value(f"{TEMP_CONDITION_SETTINGS_PREFIX}{code}", default)
            try:
                values[code] = float(raw)
            except (TypeError, ValueError):
                values[code] = float(default)
        return values

    def _load_short_circuit_tsc_range(self) -> str:
        raw = _app_settings().value(
            SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY,
            SHORT_CIRCUIT_TSC_RANGE_DEFAULT,
        )
        _start, _end, normalized = short_circuit_tsc_range_percentages(str(raw))
        return normalized

    def _save_short_circuit_tsc_range(self, label: str) -> str:
        _start, _end, normalized = short_circuit_tsc_range_percentages(label)
        _app_settings().setValue(
            SHORT_CIRCUIT_TSC_RANGE_SETTINGS_KEY,
            normalized,
        )
        return normalized

    def _save_temperature_value(self, code: str, value: float) -> None:
        if code not in TEMP_CONDITION_DEFAULTS:
            return
        settings = _app_settings()
        settings.setValue(
            f"{TEMP_CONDITION_SETTINGS_PREFIX}{code}",
            float(value),
        )
        settings.sync()

    def _temperature_display_labels(self) -> dict[str, str]:
        return {
            code: _format_temperature_label(value)
            for code, value in self._temperature_values.items()
        }

    def _current_temperature_code(self) -> str:
        code = str(self.combo_temp.currentData() or "RT").strip().upper()
        return code if code in TEMP_CONDITION_DEFAULTS else "RT"

    @staticmethod
    def _report_condition_specs(
        mode_key: str,
    ) -> tuple[tuple[str, str, str], ...]:
        return (
            SHORT_REPORT_CONDITION_FIELDS
            if mode_key == "short"
            else DPT_REPORT_CONDITION_FIELDS
        )

    def _report_condition_mode_key(self) -> str:
        return (
            "short"
            if parse_test_mode(self.cfg.test_mode.mode) == TestMode.SHORT_CIRCUIT
            else "dpt"
        )

    def _save_current_report_conditions(self) -> None:
        if self._report_condition_context is None:
            return
        mode_key, phase_code = self._report_condition_context
        settings = _app_settings()
        for (field, _label, _unit), edit in zip(
            self._report_condition_specs(mode_key),
            self._report_condition_edits,
        ):
            key = (
                f"{REPORT_CONDITION_SETTINGS_PREFIX}"
                f"{mode_key}/{phase_code}/{field}"
            )
            value = edit.numeric_value()
            if value is None:
                settings.remove(key)
            else:
                settings.setValue(key, float(value))
        settings.sync()

    def _switch_report_condition_context(self) -> None:
        mode_key = self._report_condition_mode_key()
        phase_code = self._current_report_phase_code()
        context = (mode_key, phase_code)
        if context == self._report_condition_context:
            return
        self._save_current_report_conditions()
        settings = _app_settings()
        specs = self._report_condition_specs(mode_key)
        for index, ((field, label_text, unit_text), edit) in enumerate(
            zip(specs, self._report_condition_edits)
        ):
            self._report_condition_field_labels[index].setText(label_text)
            self._report_condition_unit_labels[index].setText(unit_text)
            key = (
                f"{REPORT_CONDITION_SETTINGS_PREFIX}"
                f"{mode_key}/{phase_code}/{field}"
            )
            raw = settings.value(key, None)
            try:
                value = None if raw is None or str(raw).strip() == "" else float(raw)
            except (TypeError, ValueError):
                value = None
            edit.set_numeric_value(value)
        self._report_condition_context = context

    def _current_report_conditions(self) -> ReportConditions:
        self._switch_report_condition_context()
        mode_key = self._report_condition_mode_key()
        values = {
            field: edit.numeric_value()
            for (field, _label, _unit), edit in zip(
                self._report_condition_specs(mode_key),
                self._report_condition_edits,
            )
        }
        self._save_current_report_conditions()
        if mode_key == "short":
            return ShortReportConditions(**values)
        return DptReportConditions(**values)

    def _merge_recognized_report_conditions(
        self,
        conditions: ReportConditions,
    ) -> None:
        self._switch_report_condition_context()
        mode_key = self._report_condition_mode_key()
        if mode_key == "short" and not isinstance(conditions, ShortReportConditions):
            return
        if mode_key == "dpt" and not isinstance(conditions, DptReportConditions):
            return
        for (field, _label, _unit), edit in zip(
            self._report_condition_specs(mode_key),
            self._report_condition_edits,
        ):
            value = getattr(conditions, field)
            if value is not None:
                edit.set_numeric_value(value)
        self._save_current_report_conditions()

    def _apply_detected_short_imax(self, result: ExtractResult | None) -> None:
        if (
            result is None
            or not result.short_circuit_mode
            or self._report_condition_mode_key() != "short"
            or result.is_metric_unavailable("短路过程", "短路电流Imax")
        ):
            return
        value = float(result.short_circuit.ic_max)
        if not math.isfinite(value):
            return
        self._merge_recognized_report_conditions(
            ShortReportConditions(imax_a=value)
        )

    def _place_report_condition_group(self, *, primary_row: bool) -> None:
        if primary_row == self._report_condition_in_primary_row:
            return
        if primary_row:
            self._toolbar_report_condition_row.removeWidget(
                self.report_condition_group
            )
            insert_at = self._toolbar_primary_row.indexOf(self.lbl_map_status) + 1
            self._toolbar_primary_row.insertWidget(
                insert_at,
                self.report_condition_group,
                1,
            )
        else:
            self._toolbar_primary_row.removeWidget(self.report_condition_group)
            self._toolbar_report_condition_row.addWidget(
                self.report_condition_group,
                1,
            )
        self._report_condition_in_primary_row = primary_row

    def _current_report_phase_code(self) -> str:
        phase = str(self.combo_phase.currentData() or "U").strip().upper()
        bridge = str(self.combo_bridge.currentData() or "upper").strip().lower()
        suffix = "L" if bridge == "lower" else "H"
        code = f"{phase}{suffix}"
        valid = {f"{item}{side}" for item in PHASES for side in ("H", "L")}
        if code in valid:
            return code
        fallback = str(self.profile.code or "UH").strip().upper()
        return fallback if fallback in valid else "UH"

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

        report_conditions_in_primary_row = bucket == "full"
        self._place_report_condition_group(
            primary_row=report_conditions_in_primary_row
        )

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
                self.btn_scope.setText("示波器")
                self.btn_open.setText("TSS")
                self.btn_recalc.setText("重算")
                self.btn_export.setText("导出")
                self.btn_select_report_template.setText("模板")
                self.btn_select_report_output.setText("位置")
                self.btn_write_report.setText("写入")
            elif text_mode == "compact":
                self.btn_scope.setText("示波器")
                self.btn_open.setText("打开 TSS")
                self.btn_recalc.setText("重算")
                self.btn_export.setText("导出")
                self.btn_select_report_template.setText("模板")
                self.btn_select_report_output.setText("位置")
                self.btn_write_report.setText("写报告")
            elif text_mode == "medium":
                self.btn_scope.setText("读取示波器")
                self.btn_open.setText("打开 TSS")
                self.btn_recalc.setText("重新计算")
                self.btn_export.setText("导出 Excel")
                self.btn_select_report_template.setText("加载模板")
                self.btn_select_report_output.setText("报告位置")
                self.btn_write_report.setText("写入报告")
            else:
                self.btn_scope.setText("读取示波器")
                self.btn_open.setText("打开 TSS")
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
        self.report_condition_group.setFixedHeight(control_h)
        condition_edit_w = (
            50
            if report_conditions_in_primary_row
            else 64
            if window_width >= 1180
            else 54
        )
        condition_layout = self.report_condition_group.layout()
        if condition_layout is not None:
            condition_layout.setSpacing(2 if window_width < 1180 else 3)
        for index, edit in enumerate(self._report_condition_edits):
            edit.setFixedWidth(condition_edit_w + (4 if index == 4 else 0))
            edit.setFixedHeight(max(20, control_h - 6))
        for label in (
            self.lbl_report_conditions,
            *self._report_condition_field_labels,
            *self._report_condition_unit_labels,
        ):
            label.setFixedHeight(max(20, control_h - 4))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_off_pulse.setFixedWidth(param_pulse_w)
        self.spin_on_pulse.setFixedWidth(param_pulse_w)
        for w in (
            self.btn_scope,
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
            QFrame#toolbar QFrame#reportConditions {{
                background:#0c1719;
                border:1px solid #31545a;
                border-radius:7px;
            }}
            QFrame#toolbar QLabel#reportConditionsTitle {{
                color:#70dfeb;
                font-weight:800;
                padding-right:2px;
            }}
            QFrame#toolbar QLabel#reportConditionLabel {{
                color:#d9e5e2;
                font-size:{label_px}px;
            }}
            QFrame#toolbar QLabel#reportConditionUnit {{
                color:#8fa7aa;
                font-size:{label_px}px;
            }}
            QFrame#toolbar QLineEdit#reportConditionValue {{
                background:#101e20;
                color:#f2d45c;
                border:1px solid #3c6268;
                border-radius:5px;
                font-family:"Cascadia Mono", Consolas, monospace;
                font-size:{font_px}px;
                font-weight:700;
                padding:0 3px;
            }}
            QFrame#toolbar QLineEdit#reportConditionValue:focus {{
                border-color:#44d8e8;
                background:#13282b;
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
        if is_offset:
            self._save_current_report_conditions()
        else:
            self._switch_report_condition_context()
        self.report_condition_group.setVisible(not is_offset)
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
                    prefer_labels=self.bundle.meta.source_kind == "scope",
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
        self._switch_report_condition_context()
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
        self._invalidate_manual_adjustments_for_channel_transform(base)
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
        if parse_test_mode(self.cfg.test_mode.mode) != TestMode.OFFSET_MEASUREMENT:
            self._switch_report_condition_context()
        self._update_map_status_label()

    def _open_waveform(self) -> None:
        fallback = (
            Path(self._current_path).parent
            if self._current_path
            and (self.bundle is None or self.bundle.meta.source_kind == "file")
            else Path.home()
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开波形文件",
            open_dialog_start_dir(fallback),
            "TSS 会话 (*.tss);;All (*)",
        )
        if path:
            self._load_file(path, background=True)

    def _read_scope_waveform(self) -> None:
        self._load_request_id += 1
        request_id = self._load_request_id
        profile_code = make_profile(
            str(self.combo_phase.currentData() or self.profile.phase),
            str(self.combo_bridge.currentData() or self.profile.bridge),
        ).code
        task = _ScopeLoadTask(
            request_id,
            self._load_cfg_for_new_file(),
            profile_code,
        )
        task.signals.progress.connect(self._on_background_load_progress)
        task.signals.finished.connect(self._on_background_load_finished)
        task.signals.failed.connect(self._on_background_load_failed)
        self._load_tasks[request_id] = task
        self._set_load_busy(True, "USB 示波器")
        self._begin_task_progress("数据导入", TASK_PROGRESS_TOTAL, "正在连接 USB 示波器...")
        self._scope_io_pool.start(task)

    def _load_cfg_for_new_file(self) -> AppConfig:
        cfg = deepcopy(self.cfg)
        cfg.vdc_override = None
        cfg.slope_ranges = default_slope_ranges()
        cfg.short_circuit_tsc_range = self._load_short_circuit_tsc_range()
        return cfg

    def _set_load_busy(self, busy: bool, path: str = "") -> None:
        self.btn_scope.setEnabled(not busy)
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
        busy = bool(busy)
        if busy != self._report_interaction_locked:
            if busy:
                controls: list[QWidget] = []
                seen: set[int] = set()
                for widget_type in (QPushButton, QComboBox, QDoubleSpinBox):
                    for widget in self.toolbar.findChildren(widget_type):
                        if id(widget) in seen:
                            continue
                        seen.add(id(widget))
                        controls.append(widget)
                self._report_toolbar_enabled_states = [
                    (widget, widget.isEnabled()) for widget in controls
                ]
                for widget, _enabled in self._report_toolbar_enabled_states:
                    widget.setEnabled(False)

                self._report_result_table_enabled = self.result_table.isEnabled()
                self.result_table.setEnabled(False)
                mouse_attribute = Qt.WidgetAttribute.WA_TransparentForMouseEvents
                self._report_waveform_mouse_transparent = self.wave_plot.testAttribute(
                    mouse_attribute
                )
                self._report_splitter_mouse_transparent = self.splitter.testAttribute(
                    mouse_attribute
                )
                self.wave_plot.setAttribute(mouse_attribute, True)
                self.splitter.setAttribute(mouse_attribute, True)

                focus_widgets = [
                    self.wave_plot,
                    *self.wave_plot.findChildren(QWidget),
                ]
                self._report_focus_policies = [
                    (widget, widget.focusPolicy())
                    for widget in focus_widgets
                    if widget.focusPolicy() != Qt.FocusPolicy.NoFocus
                ]
                for widget, _policy in self._report_focus_policies:
                    widget.clearFocus()
                    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                focus_widget = QApplication.focusWidget()
                if focus_widget is not None:
                    focus_widget.clearFocus()
            else:
                for widget, enabled in self._report_toolbar_enabled_states:
                    widget.setEnabled(enabled)
                self._report_toolbar_enabled_states = []
                self.result_table.setEnabled(self._report_result_table_enabled)
                mouse_attribute = Qt.WidgetAttribute.WA_TransparentForMouseEvents
                self.wave_plot.setAttribute(
                    mouse_attribute,
                    self._report_waveform_mouse_transparent,
                )
                self.splitter.setAttribute(
                    mouse_attribute,
                    self._report_splitter_mouse_transparent,
                )
                for widget, policy in self._report_focus_policies:
                    # Report capture temporarily swaps/restores the waveform
                    # page.  PyQtGraph may destroy child controls during that
                    # rebuild while their Python wrappers remain in this
                    # snapshot; calling a QWidget method on such a wrapper
                    # raises ``wrapped C/C++ object ... has been deleted`` and
                    # used to abort the whole report-completion handler.
                    if not sip.isdeleted(widget):
                        widget.setFocusPolicy(policy)
                self._report_focus_policies = []
            self._report_interaction_locked = busy
        if busy:
            self.statusBar().showMessage("正在处理报告...")

    def _try_begin_report_operation(self) -> bool:
        if self._report_operation_active:
            return False
        self._report_operation_active = True
        self._set_report_busy(True)
        return True

    def _release_report_operation(self) -> None:
        self._report_operation_active = False
        self._set_report_busy(False)

    def _begin_task_progress(self, stage: str, total: int, label: str) -> None:
        total = max(1, int(total))
        self._report_progress_active = True
        self.report_progress.begin(total, label, stage=stage)

    def _set_task_progress(
        self,
        value: int,
        total: int,
        label: str,
        *,
        stage: str | None = None,
        eta_phase: str | None = None,
        eta_completed: int = 0,
        eta_total: int = 0,
    ) -> None:
        total = max(1, int(total))
        self.report_progress.update_progress(
            value,
            total,
            label,
            stage=stage,
            eta_phase=eta_phase,
            eta_completed=eta_completed,
            eta_total=eta_total,
        )

    def _set_task_progress_busy(
        self,
        label: str,
        *,
        stage: str | None = None,
        value: int | None = None,
        total: int | None = None,
    ) -> None:
        if value is None:
            self.report_progress.set_busy(label, stage=stage)
            return
        self.report_progress.update_busy_progress(
            value,
            max(1, int(total if total is not None else self.report_progress.maximum())),
            label,
            stage=stage,
        )

    def _finish_task_progress(
        self,
        label: str,
        *,
        ok: bool,
        stage: str | None = None,
    ) -> None:
        self.report_progress.finish(label, ok=ok, stage=stage)
        self._report_progress_active = False

    def _begin_report_progress(
        self,
        total: int,
        label: str,
        *,
        timing_stage: str | None = None,
    ) -> None:
        self._begin_task_progress("报告写入", total, label)
        if self._active_report_timing_context is not None and timing_stage is not None:
            budgets = self._report_timing_history.estimate(
                self._active_report_timing_context
            )
            self.report_progress.begin_report_timing(
                budgets,
                report_timing_stage_windows(budgets),
                timing_stage,
            )

    def _estimate_report_result_count(self) -> int:
        result = self.result
        if (
            result is None
            or result.short_circuit_mode
            or result.single_pulse_mode
            or int(result.detected_pulse_count or 0) <= 2
        ):
            return 1
        return max(
            1,
            len(
                dpt_export_pulse_pairs(
                    int(result.detected_pulse_count),
                    include_pair=(
                        int(result.off_pulse_index),
                        int(result.on_pulse_index),
                    ),
                )
            ),
        )

    def _initialize_report_timing(
        self,
        *,
        existing_report: bool,
        report_path: Path,
    ) -> None:
        if self._active_report_timing_context is not None:
            return
        size_path = report_path
        if not existing_report:
            template = self._current_report_template_source()
            if template is not None:
                size_path = template
        try:
            size_bytes = max(0, int(size_path.stat().st_size))
        except OSError:
            size_bytes = 0
        self._active_report_timing_context = ReportTimingContext(
            existing_report=bool(existing_report),
            report_size_bytes=size_bytes,
            image_count=len(self._report_image_params()),
            result_count=self._estimate_report_result_count(),
            first_in_session=self._report_writes_this_session == 0,
        )

    def _set_report_progress(
        self,
        value: int,
        total: int,
        label: str,
        *,
        eta_phase: str | None = None,
        eta_completed: int = 0,
        eta_total: int = 0,
        timing_stage: str | None = None,
        timing_completed: int = 0,
        timing_total: int = 0,
    ) -> None:
        if timing_stage is not None:
            self.report_progress.observe_report_timing(
                timing_stage,
                timing_completed,
                timing_total,
            )
        self._set_task_progress(
            value,
            total,
            label,
            stage="报告写入",
            eta_phase=eta_phase,
            eta_completed=eta_completed,
            eta_total=eta_total,
        )

    def _set_report_progress_busy(
        self,
        label: str,
        *,
        value: int | None = None,
        total: int | None = None,
        timing_stage: str | None = None,
    ) -> None:
        if timing_stage is not None:
            self.report_progress.observe_report_timing(timing_stage)
        self._set_task_progress_busy(
            label,
            stage="报告写入",
            value=value,
            total=total,
        )

    def _finish_report_progress(self, label: str, *, ok: bool) -> None:
        durations = self.report_progress.finish_report_timing()
        context = self._active_report_timing_context
        self._active_report_timing_context = None
        if ok and context is not None and durations:
            self._report_timing_history.record(context, durations)
            _app_settings().setValue(
                REPORT_TIMING_SETTINGS_KEY,
                self._report_timing_history.to_json(),
            )
            self._report_writes_this_session += 1
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
        eta_phase: str = "",
        eta_completed: int = 0,
        eta_total: int = 0,
    ) -> None:
        if request_id != self._load_request_id:
            return
        self._set_task_progress(
            value,
            total,
            label,
            stage="数据导入",
            eta_phase=eta_phase or None,
            eta_completed=eta_completed,
            eta_total=eta_total,
        )

    def _on_background_load_finished(
        self,
        request_id: int,
        outcome: _WaveformLoadOutcome,
    ) -> None:
        self._load_tasks.pop(request_id, None)
        if request_id != self._load_request_id:
            return
        try:
            self._set_task_progress_busy(
                "正在刷新界面并绘制波形...",
                stage="数据导入",
            )
            self._apply_loaded_waveform(outcome)
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
        if _path.startswith("scope://"):
            self.lbl_top_status.setText(message)
            self.statusBar().showMessage(message)
            return
        QMessageBox.critical(self, "加载失败", message)

    def _clear_manual_adjustments(self, *, reset_plot: bool = True) -> None:
        self._manual_intervals.clear()
        self._manual_extreme_values.clear()
        self._manual_short_current.clear()
        self._manual_turn_on_current = None
        self._manual_energy.clear()
        self._manual_delta_vce.clear()
        self._manual_dvdt.clear()
        self._manual_didt.clear()
        self._manual_trr_measure = None
        self._manual_waveform_source = ""
        self._manual_pulse_pair = None
        self._active_slope_param = None
        self._pending_parameter_local_view_restore = None
        if reset_plot:
            self.wave_plot.reset_interaction_state()

    def _logical_roles_affected_by_channel_transform(
        self, source_key: str
    ) -> set[str]:
        """Return logical waveform roles changed by one display inversion.

        Math dependencies are followed so an inverted CH source also invalidates
        a role mapped to a derived MATH trace.  The result is based only on the
        current channel mapping; no sample path or operating-point special case
        participates.
        """

        base = normalize_channel_reference(source_key).lstrip("-")
        if not base:
            return set()
        affected_sources = {base}
        bundle = self.bundle
        formulas = (
            getattr(getattr(bundle, "meta", None), "channel_math_formulas", {})
            if bundle is not None
            else {}
        )
        pending = {
            normalize_channel_reference(key).lstrip("-"): str(expr or "")
            for key, expr in formulas.items()
        }
        changed = True
        while changed:
            changed = False
            for output, expr in pending.items():
                refs = {
                    normalize_channel_reference(ref).lstrip("-")
                    for ref in re.findall(r"\b(?:CH[1-8]|MATH\d+)\b", expr.upper())
                }
                if output and output not in affected_sources and refs & affected_sources:
                    affected_sources.add(output)
                    changed = True

        profile = self.profile
        role_channels = {
            "vge": profile.vge,
            "vce": profile.vce,
            "ic": profile.ic,
            "il": profile.il,
            "irr": profile.irr,
            "v_diode": profile.v_diode,
            "vge_other": profile.vge_other,
            "vdesat": profile.vdesat,
        }
        roles = {
            role
            for role, channel in role_channels.items()
            if normalize_channel_reference(channel).lstrip("-") in affected_sources
        }
        if profile.ic_from_sum_irr_il and roles & {"irr", "il"}:
            roles.add("ic")
        if profile.irr_from_ic_minus_il and roles & {"ic", "il"}:
            roles.add("irr")
        return roles

    def _manual_parameter_waveform_roles(
        self, section: str, name: str
    ) -> set[str]:
        """Logical waveforms whose transform makes a saved card state stale."""

        if name == "ΔVce":
            return {"vce"}
        if name == "dv/dt":
            return {"v_diode" if section == "反向恢复" else "vce"}
        if name == "di/dt":
            return {"irr" if section == "反向恢复" else "ic"}
        if name in {"Eoff", "Eon"}:
            return {"vce", "ic"}
        if name == "Err":
            return {"irr", "v_diode"}
        if name in {"Pmax", "Pdmax"}:
            return (
                {"irr", "v_diode"}
                if section == "反向恢复"
                else {"vce", "ic"}
            )
        if name in {"Irr", "Trr"}:
            return {"irr"}
        if name == "Vrr":
            return {"v_diode"}
        if name == "开通电流":
            return {"ic"}
        if name == "串扰电压":
            return {"vge_other"}
        if section == "短路过程":
            short_roles = {
                "短路电流Imax": {"ic"},
                "短路时间Tsc": {"ic", "vge"},
                "短路能量Esc_本管": {"ic", "vce"},
                "短路能量Esc_对管": {"ic", "v_diode"},
                "应力Vpeak_本管": {"vce", "vge"},
                "应力Vpeak_对管": {"v_diode", "vge"},
                "Desat动作时间": {"vge", "vdesat"},
            }
            if name in short_roles:
                return short_roles[name]

        roles = {
            role
            for role in self._cursor_endpoint_channels_for_param(section, name)
            if role
        }
        primary = self._channel_for_param(section, name)
        if primary:
            roles.add(primary)
        return roles

    def _invalidate_manual_adjustments_for_channel_transform(
        self, source_key: str
    ) -> set[str]:
        """Drop only saved card state whose source waveform changed sign."""

        affected_roles = self._logical_roles_affected_by_channel_transform(source_key)
        if not affected_roles:
            return set()

        for cache_name in (
            "_manual_intervals",
            "_manual_extreme_values",
            "_manual_short_current",
            "_manual_energy",
            "_manual_delta_vce",
            "_manual_dvdt",
            "_manual_didt",
        ):
            cache = getattr(self, cache_name)
            for key in list(cache):
                if self._manual_parameter_waveform_roles(*key) & affected_roles:
                    cache.pop(key, None)
        if "ic" in affected_roles:
            self._manual_turn_on_current = None
        if "irr" in affected_roles:
            self._manual_trr_measure = None
        return affected_roles

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
        source_label = "已读取示波器" if outcome.bundle.meta.source_kind == "scope" else "已加载"
        msg = (
            f"{source_label}: {Path(outcome.path).name}  |  "
            f"读取 {outcome.load_ms:.0f} ms  {extract_label} {outcome.extract_ms:.0f} ms"
        )
        if outcome.bundle.meta.source_kind == "scope":
            msg += (
                f"（完整记录 {len(outcome.bundle.channels)} 通道 × "
                f"{outcome.bundle.n} 点/通道）"
            )
        if outcome.mapping_custom:
            msg += "（已应用自定义通道映射）"
        elif inferred is not None:
            if outcome.inferred_source == "trend":
                msg += "（已按波形趋势识别通道）"
            else:
                msg += "（已按通道标签识别通道）"
        if outcome.result is None and mode != TestMode.OFFSET_MEASUREMENT:
            if outcome.bundle.meta.source_kind == "scope":
                # USB acquisition and parameter extraction are independent:
                # once samples are available, the import is successful even
                # when the current record cannot produce DPT parameters.
                msg += "（当前波形已完整加载；参数计算未生成结果）"
            else:
                reason = outcome.extraction_error or "当前波形不满足该模式的自动计算条件"
                msg += f"（参数未计算：{reason}）"
        elif mode == TestMode.OFFSET_MEASUREMENT:
            msg += "（偏移测量模式：未运行参数计算）"
        if outcome.bundle.meta.channel_vdiv:
            msg += f"（已应用源垂直刻度 {len(outcome.bundle.meta.channel_vdiv)} 通道）"
        return msg

    def _extraction_placeholder_detail(
        self,
        error: str,
        *,
        source_kind: str = "file",
    ) -> str:
        reason = error.strip() or "当前波形不满足该模式的自动计算条件。"
        if source_kind == "scope":
            return (
                "示波器当前波形已完整加载并显示。"
                f"参数计算未生成结果；这不影响波形查看。计算信息：{reason}"
            )
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
        if self.bundle.meta.source_kind == "file":
            mode = parse_test_mode(self.cfg.test_mode.mode)
            if mode == TestMode.DPT:
                self._merge_recognized_report_conditions(
                    infer_dpt_report_conditions(path)
                )
            elif mode == TestMode.SHORT_CIRCUIT:
                self._merge_recognized_report_conditions(
                    infer_short_report_conditions(path)
                )
        self._slope_ranges = default_slope_ranges()
        self.cfg.short_circuit_tsc_range = self._load_short_circuit_tsc_range()
        self.result_table.set_slope_ranges(self._slope_ranges)
        self._clear_manual_adjustments()
        self._offset_measurements = self._default_offset_measurements_for_bundle()
        if self.bundle.meta.source_kind == "file":
            set_last_open_path(path)

        if parse_test_mode(self.cfg.test_mode.mode) == TestMode.OFFSET_MEASUREMENT:
            self._enter_offset_measurement_mode(outcome)
            return

        if outcome.result is None:
            self.result = None
            mode_label = MODE_UI_LABELS[parse_test_mode(self.cfg.test_mode.mode)]
            self.result_table.set_mode_placeholder(
                mode_label,
                self._extraction_placeholder_detail(
                    outcome.extraction_error,
                    source_kind=self.bundle.meta.source_kind,
                ),
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
        self._apply_detected_short_imax(self.result)
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
        new = normalize_slope_range(key, sr)
        self._slope_ranges[key] = new
        if old != new:
            for param_key, row_key in SLOPE_ROW_KEYS.items():
                if row_key != key:
                    continue
                section, metric = param_key
                cache = self._manual_dvdt if metric == "dv/dt" else self._manual_didt
                cache.pop(param_key, None)
                self._manual_intervals.pop(param_key, None)
                if metric == "di/dt":
                    ls_name = {
                        "关断过程": "Ls_off",
                        "开通": "Ls_on",
                    }.get(section)
                    if ls_name is not None:
                        self._manual_intervals.pop((section, ls_name), None)
                break
        self.cfg.slope_ranges = dict(self._slope_ranges)
        self._recalculate()

    def _on_eoff_pre_changed(self, pre_ns: float) -> None:
        self.cfg.energy.eoff_pre_ns = float(pre_ns)
        self._recalculate()

    def _on_short_circuit_tsc_range_changed(self, label: str) -> None:
        normalized = self._save_short_circuit_tsc_range(label)
        self.cfg.short_circuit_tsc_range = normalized
        key = ("短路过程", "短路时间Tsc")
        self._manual_intervals.pop(key, None)
        self._manual_short_current.pop(key, None)
        self._recalculate()

    def _touch_manual_waveform_source(self) -> None:
        if self.bundle is not None:
            self._manual_waveform_source = self.bundle.meta.source_path
        if self.result is not None:
            self._manual_pulse_pair = (
                int(self.result.off_pulse_index),
                int(self.result.on_pulse_index),
            )

    def _manual_cursors_apply_to_current_waveform(self) -> bool:
        if self.bundle is None or self.result is None:
            return False
        if self.bundle.meta.source_path != self._manual_waveform_source:
            return False
        current_pair = (
            int(self.result.off_pulse_index),
            int(self.result.on_pulse_index),
        )
        return self._manual_pulse_pair in (None, current_pair)

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
        # A click starts a new parameter context.  Only the two slope handlers
        # below may opt back into automatic slope reactivation after a
        # recalculation.  Clearing here also covers unavailable/single-pulse
        # early returns, which otherwise resurrected a previously selected
        # di/dt card after a channel or range change.
        self._active_slope_param = None
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
            self.wave_plot.clear_parameter_cursor_context()
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

    def _on_result_value_clicked(self, section: str, name: str) -> None:
        """Handle a real table click, then perform one live-scope refresh."""

        key = (section, name)
        pending = getattr(self, "_pending_parameter_local_view_restore", None)
        restore_window = (
            pending[1]
            if pending is not None and pending[0] == key
            else None
        )
        self._pending_parameter_local_view_restore = None
        self._on_value_clicked(section, name)
        if self._metric_unavailable(section, name):
            return
        if restore_window is not None:
            self.wave_plot.restore_local_x_window_us(restore_window)
        QTimer.singleShot(0, self._start_scope_sync_from_plot)

    def _on_plot_zoom_sync_requested(self, zoom_enabled: bool) -> None:
        if zoom_enabled:
            self._pending_parameter_local_view_restore = None
        else:
            active_metric = self.result_table._active_metric
            recent_window = self.wave_plot.recent_local_x_window_us()
            self._pending_parameter_local_view_restore = (
                (active_metric, recent_window)
                if active_metric is not None and recent_window is not None
                else None
            )
        self._start_scope_sync_from_plot(zoom_enabled)

    def _start_scope_sync_from_plot(self, zoom_enabled: bool | None = None) -> None:
        bundle = self.bundle
        if (
            bundle is None
            or bundle.meta.source_kind != "scope"
            or not bundle.meta.instrument_resource
        ):
            return
        snapshot = (
            self.wave_plot.scope_view_snapshot()
            if zoom_enabled is not None
            else self.wave_plot.scope_cursor_snapshot()
        )
        if snapshot is None:
            return
        state = ScopeViewState(
            record_start_s=float(bundle.t[0]),
            record_stop_s=float(bundle.t[-1]),
            zoom_enabled=True if zoom_enabled is None else bool(zoom_enabled),
            **snapshot,
        )
        self._scope_sync_request_id += 1
        request_id = self._scope_sync_request_id
        task = _ScopeSyncTask(
            request_id,
            bundle.meta.instrument_resource,
            state,
        )
        task.signals.finished.connect(self._on_scope_sync_finished)
        task.signals.failed.connect(self._on_scope_sync_failed)
        self._scope_sync_tasks[request_id] = task
        self.statusBar().showMessage("正在同步软件窗口与光标到示波器...")
        self._scope_io_pool.start(task)

    def _on_scope_sync_finished(self, request_id: int) -> None:
        self._scope_sync_tasks.pop(request_id, None)
        if request_id != self._scope_sync_request_id:
            return
        self.statusBar().showMessage("示波器已同步当前软件窗口与光标")

    def _on_scope_sync_failed(self, request_id: int, message: str) -> None:
        self._scope_sync_tasks.pop(request_id, None)
        if request_id != self._scope_sync_request_id:
            return
        self.statusBar().showMessage(f"示波器同步失败：{message}")

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
        # 三类过程都以对应门极切换起点作为首选锚点。反向恢复发生在第二
        # 脉冲开通过程内，因此沿用开通构图：保留左侧开通过程，同时让恢复
        # 主瓣、振铃和右侧稳定段落在窗口主体内。
        if anchor_us is None:
            anchor_us = self._switching_focus_anchor_us(section)
        if anchor_us is None:
            self.wave_plot.focus_interval_us(fallback_t0_us, fallback_t1_us)
            return
        self.wave_plot.focus_parameter_window_us(
            anchor_us,
            fallback_t0_us,
            fallback_t1_us,
        )

    def _recovery_peak_us(self) -> float | None:
        """反向恢复主峰 (IRM) 时刻（µs，定向后取 argmax）。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.metrics.iec_windows import err_recovery_peak_index
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        irr = bundle_reverse_recovery_current(self.bundle, self.profile)
        rr0, rr1 = self.result.segments.reverse_recovery
        completed = self._rr_measurement_window_indices()
        rr_context_i1 = completed[2] if completed is not None else rr1
        ipk = rr0 + err_recovery_peak_index(
            irr[rr0 : rr_context_i1 + 1],
            self.bundle.dt,
        )
        return float(self.bundle.t[ipk]) * 1e6

    def _rr_measurement_window_indices(
        self,
    ) -> tuple[int, int, int, bool] | None:
        """Shared completed RR slope/context window for GUI parameter cards."""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.metrics.iec_windows import (
            rr_completed_measurement_window_indices,
            rr_slope_window_indices,
        )

        t = self.bundle.t
        segs = self.result.segments
        on0, on1 = segs.turn_on
        _rr0, rr1 = segs.reverse_recovery
        vd = self.bundle.maybe_get(self.profile.v_diode)
        if vd is None:
            i0, i1 = rr_slope_window_indices(on0, rr1, len(t), self.bundle.dt)
            return i0, i1, rr1, False
        i0, i1, completed = rr_completed_measurement_window_indices(
            on0,
            rr1,
            on1,
            vd,
            len(t),
            self.bundle.dt,
        )
        return i0, i1, i1 if completed else rr1, completed

    def _default_dvdt_on_vce_base_top(
        self, t0_us: float, t1_us: float
    ) -> tuple[float, float] | None:
        """开通 Vce dv/dt：Hb=0 幅值基准，Ha=权威 Vce Top。"""
        context = self._turn_on_dvdt_context(t0_us, t1_us)
        if context is None:
            return None
        return float(context.base_v), float(context.top_v)

    def _default_rr_dvdt_base_top_v(self) -> tuple[float, float] | None:
        """反向恢复 dv/dt：返回数值计算使用的同一组 Vd Base/Top。"""
        context = self._rr_dvdt_context()
        if context is None:
            return None
        return float(context.base_v), float(context.top_v)

    def _turn_on_dvdt_context(
        self, _t0_us: float, _t1_us: float
    ) -> DvdtMeasurementContext | None:
        """与 pipeline 共用的开通 dv/dt 默认测量上下文。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.models.waveform import bundle_total_current

        segs = self.result.segments
        t = self.bundle.t
        vce = self.bundle.get(self.profile.vce)
        ic = bundle_total_current(self.bundle, self.profile)
        top_v = turn_on_vce_top_from_ic_rise(
            ic,
            vce,
            segs.pulse2_on,
            segs.pulse2_off,
            self.bundle.dt,
        )
        row_key = SLOPE_ROW_KEYS.get(("开通", "dv/dt"))
        sr = self._slope_ranges.get(row_key) if row_key else None
        pct_hi, pct_lo = sr.as_fractions() if sr else (0.9, 0.1)
        on0, on1 = segs.turn_on
        return turn_on_dvdt_measurement_context(
            t,
            vce,
            top_v,
            on0,
            on1,
            self.bundle.dt,
            self.cfg,
            pct_hi,
            pct_lo,
            event_end_idx=segs.pulse2_off,
            auto_max=bool(sr and sr.is_auto_max),
        )

    def _rr_dvdt_context(self) -> DvdtMeasurementContext | None:
        """与 pipeline 共用的反向恢复 dv/dt 默认测量上下文。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None

        t = self.bundle.t
        vd = self.bundle.get(self.profile.v_diode)
        rr0, rr1 = self.result.segments.reverse_recovery
        completed = self._rr_measurement_window_indices()
        if completed is None:
            return None
        i0, i1, rr_context_i1, _extended = completed
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        irr = bundle_reverse_recovery_current(self.bundle, self.profile)
        use_settled_platform = rr_dvdt_prefers_settled_platform(
            irr,
            self.result.reverse_recovery.irr,
            self.result.segments.turn_on[1],
            self.result.segments.pulse2_off,
            self.bundle.dt,
        )
        row_key = SLOPE_ROW_KEYS.get(("反向恢复", "dv/dt"))
        sr = self._slope_ranges.get(row_key) if row_key else None
        pct_a, pct_b = sr.as_fractions() if sr else (0.1, 0.9)
        return rr_dvdt_measurement_context(
            t,
            vd,
            i0,
            i1,
            self.bundle.dt,
            self.cfg,
            min(pct_a, pct_b),
            max(pct_a, pct_b),
            fallback_i0=rr0,
            fallback_i1=rr_context_i1,
            use_settled_platform=use_settled_platform,
            event_end_idx=self.result.segments.turn_on[1],
            auto_max=bool(sr and sr.is_auto_max),
        )

    def _turn_off_dvdt_context(
        self, t0_us: float, t1_us: float
    ) -> DvdtMeasurementContext | None:
        """与 pipeline 共用的关断 dv/dt 默认测量上下文。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 2))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        sr = self._slope_ranges.get(SLOPE_ROW_KEYS.get(("关断过程", "dv/dt"), ""))
        pct_a, pct_b = sr.as_fractions() if sr else (0.1, 0.9)
        segs = self.result.segments
        fall_win = turn_off_ic_fall_window(
            t,
            self.bundle.get(self.profile.vge),
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_on,
            segs.pulse1_off,
            segs.pulse2_on,
            self.bundle.dt,
            self.cfg,
        )
        rise_start, rise_end = fall_win if fall_win is not None else segs.turn_off
        return turn_off_dvdt_measurement_context(
            t,
            self.bundle.get(self.profile.vce),
            i0,
            i1,
            self.bundle.dt,
            self.cfg,
            pct_a,
            pct_b,
            rise_start=rise_start,
            rise_end=rise_end,
            auto_max=bool(sr and sr.is_auto_max),
        )

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
        context = self._turn_off_dvdt_context(t0_us, t1_us)
        if context is None:
            return None
        return context.base_v, context.top_v

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
        if edge == "fall":
            pct_a, pct_b = max(pct_a, pct_b), min(pct_a, pct_b)
        else:
            pct_a, pct_b = min(pct_a, pct_b), max(pct_a, pct_b)
        use_abs = section == "反向恢复"
        if section == "反向恢复":
            y = self.bundle.get(self.profile.v_diode)
        else:
            y = self.bundle.get(self.profile.vce)
        if sr and sr.is_auto_max:
            return auto_dvdt_between_base_top(
                t,
                y,
                i0,
                i1,
                float(base_v),
                float(top_v),
                edge,
                use_abs=use_abs,
            )
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
        range_disp = slope_range_result_label(sr, res) if sr else ""
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
        self.result_table.set_range_text(section, "dv/dt", range_disp)
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
            f"{range_disp}, {ab_msg}, 值={val:.3f} V/ns"
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
        default_context: DvdtMeasurementContext | None = None
        if restored is not None:
            search_t0, search_t1, top_v, base_v = restored
        elif section == "关断过程":
            default_context = self._turn_off_dvdt_context(search_t0, search_t1)
            if default_context is not None:
                base_v = default_context.base_v
                top_v = default_context.top_v
            else:
                top_v = self._default_dvdt_top_v(section, search_t0, search_t1)
                base_v = self._default_dvdt_base_v(section, search_t0, search_t1)
        elif section == "反向恢复":
            default_context = self._rr_dvdt_context()
            if default_context is not None:
                base_v = default_context.base_v
                top_v = default_context.top_v
            else:
                top_v = self._default_dvdt_top_v(section, search_t0, search_t1)
                base_v = self._default_dvdt_base_v(section, search_t0, search_t1)
        elif section == "开通":
            default_context = self._turn_on_dvdt_context(search_t0, search_t1)
            if default_context is not None:
                base_v = default_context.base_v
                top_v = default_context.top_v
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
                self.wave_plot.apply_dvdt_ab_times(
                    ta_us,
                    tb_us,
                    refresh_readout=False,
                )
            else:
                self.wave_plot.invalidate_dvdt_ab_times(
                    refresh_readout=False
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
        res0 = (
            default_context.crossing
            if default_context is not None
            else self._compute_dvdt_base_top(
                section, search_t0, search_t1, top_v, base_v
            )
        )
        if res0.t_pct_a_s is not None and res0.t_pct_b_s is not None:
            ta_us = res0.t_pct_a_s * 1e6
            tb_us = res0.t_pct_b_s * 1e6
            self.wave_plot.apply_dvdt_ab_times(ta_us, tb_us)
        if restored is None:
            if res0.t_pct_a_s is not None and res0.t_pct_b_s is not None:
                self._focus_switching_local_view(section, ta_us, tb_us)
            else:
                self._focus_switching_local_view(section, search_t0, search_t1)
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
        key = (section, "di/dt")
        channel = self._didt_channel(section)
        # Turn-off and turn-on both use logical Ic.  Channel equality alone
        # cannot prove that the visible Ha/Hb belong to this parameter.
        if self.__dict__.get("_active_slope_param") == key:
            live = self.wave_plot.read_didt_slope_state(channel)
            if live is not None:
                return live
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
        idm：Ha=恢复尾 Base，Hb=换流前带符号 IDM 平台（与探头极性无关）。
        if_irm：Ha=换流前 IF 平台，Hb=反向恢复 IRM 峰。

        正常加载路径会复用 ``RrDidtMeasurementContext``；这里仍须保持
        同一语义，避免轻量调用或上下文不可用时把 negative-first 的
        Ha/Hb 对调。
        """
        seg = np.asarray(seg, dtype=np.float64)
        if len(seg) < 8:
            return 0.0, 0.0
        from dpt_extractor.metrics.slopes import _rr_default_signed_levels

        dt = float(getattr(getattr(self, "bundle", None), "dt", 0.0) or 0.0)
        forward, base, reverse, _zero, _polarity = _rr_default_signed_levels(
            seg,
            dt if dt > 0.0 else 1e-9,
        )
        if mode_tag == "if_irm":
            return float(forward), float(reverse)
        return float(base), float(forward)

    def _default_didt_zero_a(self, section: str, t0_us: float, t1_us: float) -> float:
        if self.bundle is None or section != "反向恢复":
            return 0.0
        context = self._rr_didt_context(t0_us, t1_us)
        if context is not None and context.zero_a is not None:
            return float(context.zero_a)
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

    def _turn_off_didt_context(
        self, t0_us: float, t1_us: float
    ) -> DidtMeasurementContext | None:
        """与 pipeline 共用的关断 di/dt 默认测量上下文。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.models.waveform import bundle_total_current

        t = self.bundle.t
        segs = self.result.segments
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 2))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        fall_win = turn_off_ic_fall_window(
            t,
            self.bundle.get(self.profile.vge),
            segs.turn_off[0],
            segs.turn_off[1],
            segs.pulse1_on,
            segs.pulse1_off,
            segs.pulse2_on,
            self.bundle.dt,
            self.cfg,
        )
        fall_start, fall_end = fall_win if fall_win is not None else segs.turn_off
        row_key = SLOPE_ROW_KEYS.get(("关断过程", "di/dt"))
        sr = self._slope_ranges.get(row_key) if row_key else None
        pct_a, pct_b = sr.as_fractions() if sr else (0.9, 0.1)
        edge = sr.ic_direction if sr else "fall"
        return turn_off_didt_measurement_context(
            t,
            bundle_total_current(self.bundle, self.profile),
            i0,
            i1,
            segs.pulse1_on,
            segs.pulse1_off,
            fall_start,
            fall_end,
            self.bundle.dt,
            self.cfg,
            pct_a,
            pct_b,
            edge=edge,
            next_pulse_on=segs.next_pulse_on,
            auto_max=bool(sr and sr.is_auto_max),
        )

    def _turn_on_didt_context(
        self,
        t0_us: float,
        t1_us: float,
        *,
        top_override: float | None = None,
        base_override: float | None = None,
    ) -> DidtMeasurementContext | None:
        """与 pipeline 共用的开通 di/dt 默认/手调测量上下文。"""
        if self.bundle is None or self.result is None or self.result.segments is None:
            return None
        from dpt_extractor.models.waveform import bundle_total_current

        t = self.bundle.t
        segs = self.result.segments
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 2))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        row_key = SLOPE_ROW_KEYS.get(("开通", "di/dt"))
        sr = self._slope_ranges.get(row_key) if row_key else None
        pct_a, pct_b = sr.as_fractions() if sr else (0.1, 0.9)
        edge = sr.ic_direction if sr else "rise"
        return turn_on_didt_measurement_context(
            t,
            bundle_total_current(self.bundle, self.profile),
            i0,
            i1,
            self.bundle.dt,
            pct_a,
            pct_b,
            edge=edge,
            base_override=base_override,
            top_override=top_override,
            event_end_idx=segs.pulse2_off,
            auto_max=bool(sr and sr.is_auto_max),
        )

    def _rr_didt_context(
        self, t0_us: float, t1_us: float
    ) -> RrDidtMeasurementContext | None:
        """与 pipeline 共用的反向恢复 di/dt 默认测量上下文。"""
        # Some calculation-only callers construct a lightweight instance via
        # ``__new__`` without running QMainWindow.__init__.  Read the Python
        # state directly so those legacy helpers can cleanly fall back instead
        # of entering PyQt's uninitialised QObject attribute lookup.
        state = self.__dict__
        bundle = state.get("bundle")
        result = state.get("result")
        profile = state.get("profile")
        cfg = state.get("cfg")
        if (
            bundle is None
            or result is None
            or result.segments is None
            or profile is None
            or cfg is None
        ):
            return None
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        t = bundle.t
        rr0, rr1 = result.segments.reverse_recovery
        completed = self._rr_measurement_window_indices()
        if completed is None:
            return None
        i0, i1, rr_context_i1, _extended = completed
        row_key = SLOPE_ROW_KEYS.get(("反向恢复", "di/dt"))
        slope_ranges = state.get("_slope_ranges")
        if not isinstance(slope_ranges, dict):
            slope_ranges = getattr(cfg, "slope_ranges", {})
        sr = slope_ranges.get(row_key) if row_key else None
        pct_a, pct_b = sr.as_fractions() if sr else (0.9, 0.1)
        measure = (
            sr.ic_reference
            if sr and sr.ic_reference in {"idm", "if_irm"}
            else "idm"
        )
        irr = bundle_reverse_recovery_current(bundle, profile)
        return rr_didt_measurement_context(
            t,
            irr,
            i0,
            i1,
            bundle.dt,
            cfg,
            pct_a,
            pct_b,
            measure=measure,
            rr_i0=rr0,
            rr_i1=rr_context_i1,
            fallback_i0=rr0,
            fallback_i1=rr_context_i1,
            auto_max=bool(sr and sr.is_auto_max),
        )

    def _default_didt_top_a(self, section: str, t0_us: float, t1_us: float) -> float:
        if self.bundle is None or self.result is None:
            return 0.0
        t = self.bundle.t
        i0 = int(np.searchsorted(t, min(t0_us, t1_us) * 1e-6, side="left"))
        i1 = int(np.searchsorted(t, max(t0_us, t1_us) * 1e-6, side="left"))
        i0 = max(0, min(i0, len(t) - 1))
        i1 = max(i0 + 1, min(i1, len(t) - 1))
        if section == "关断过程":
            context = self._turn_off_didt_context(t0_us, t1_us)
            return float(context.top_a) if context is not None else 0.0
        if section == "开通":
            context = self._turn_on_didt_context(t0_us, t1_us)
            return float(context.top_a) if context is not None else 0.0
        if section == "反向恢复":
            context = self._rr_didt_context(t0_us, t1_us)
            if context is not None:
                if self._rr_didt_mode_tag(section) == "if_irm":
                    return float(context.forward_a)
                # IDM display semantics: Ha is the recovery-tail zero/base.
                return float(context.base_a)
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
            context = self._rr_didt_context(t0_us, t1_us)
            if context is not None:
                if self._rr_didt_mode_tag(section) == "if_irm":
                    return float(context.reverse_a)
                # IDM display semantics: Hb is the signed forward IDM level.
                return float(context.forward_a)
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
        if section == "开通":
            context = self._turn_on_didt_context(t0_us, t1_us)
            return float(context.base_a) if context is not None else 0.0
        from dpt_extractor.models.waveform import bundle_total_current
        ic = bundle_total_current(self.bundle, self.profile)
        if section == "关断过程":
            context = self._turn_off_didt_context(t0_us, t1_us)
            return float(context.base_a) if context is not None else 0.0
        seg = ic[i0 : i1 + 1].astype(np.float64)
        return float(np.min(np.abs(seg))) if len(seg) else 0.0

    def _compute_didt_base_top(
        self,
        section: str,
        search_t0_us: float,
        search_t1_us: float,
        top_a: float,
        base_a: float,
        zero_a: float | None = None,
        *,
        rr_prepared: RrDidtPreparedSeries | None = None,
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
        if section == "关断过程":
            pct_a, pct_b = max(pct_a, pct_b), min(pct_a, pct_b)
            edge = "fall"
        if section == "反向恢复":
            if sr and sr.is_auto_max:
                # IDM horizontal semantics are Ha=tail base, Hb=signed IDM.
                forward_a = float(base_a)
                idm_base_a = float(top_a)
                if rr_prepared is not None:
                    return auto_rr_didt_between_prepared_levels(
                        rr_prepared,
                        forward_a=forward_a,
                        base_a=idm_base_a,
                    )
                from dpt_extractor.models.waveform import (
                    bundle_reverse_recovery_current,
                )

                wave_plot = self.__dict__.get("wave_plot")
                y = (
                    wave_plot.logical_reverse_recovery_current(
                        self.bundle, self.profile
                    )
                    if wave_plot is not None
                    else None
                )
                if y is None:
                    y = bundle_reverse_recovery_current(
                        self.bundle, self.profile
                    )
                return auto_rr_didt_between_levels(
                    t,
                    y,
                    i0,
                    i1,
                    forward_a=forward_a,
                    base_a=idm_base_a,
                )
            measure = "idm"
            if sr and sr.ic_reference == "if_irm":
                measure = "if_irm"
            elif sr and sr.ic_reference == "idm":
                measure = "idm"
            if measure == "if_irm":
                forward_a = float(top_a)
                base_or_reverse_a = float(base_a)
            else:
                # IDM horizontal semantics are Ha=tail base, Hb=signed IDM.
                forward_a = float(base_a)
                base_or_reverse_a = float(top_a)
            if rr_prepared is not None:
                return rr_didt_between_prepared_levels(
                    rr_prepared,
                    pct_a,
                    pct_b,
                    measure=measure,
                    forward_a=forward_a,
                    base_or_reverse_a=base_or_reverse_a,
                    zero_a=None if zero_a is None else float(zero_a),
                )
            from dpt_extractor.models.waveform import bundle_reverse_recovery_current

            wave_plot = self.__dict__.get("wave_plot")
            y = (
                wave_plot.logical_reverse_recovery_current(self.bundle, self.profile)
                if wave_plot is not None
                else None
            )
            if y is None:
                y = bundle_reverse_recovery_current(self.bundle, self.profile)
            return rr_didt_between_levels(
                t,
                y,
                i0,
                i1,
                pct_a,
                pct_b,
                measure=measure,
                forward_a=forward_a,
                base_or_reverse_a=base_or_reverse_a,
                zero_a=None if zero_a is None else float(zero_a),
            )
        if section == "开通":
            context = self._turn_on_didt_context(
                search_t0_us,
                search_t1_us,
                top_override=float(top_a),
                base_override=float(base_a),
            )
            if context is not None:
                return context.crossing
            return DidtCrossingResult(0.0, None, None, 0.0, 0.0)
        from dpt_extractor.models.waveform import bundle_total_current

        y = bundle_total_current(self.bundle, self.profile)
        if sr and sr.is_auto_max:
            return auto_didt_between_base_top(
                t,
                y,
                i0,
                i1,
                float(base_a),
                float(top_a),
                "fall",
                use_abs=False,
            )
        return didt_between_base_top(
            t,
            y,
            i0,
            i1,
            float(base_a),
            float(top_a),
            pct_a,
            pct_b,
            edge,
            use_abs=section != "关断过程",
        )

    def _prepare_rr_didt_cursor_series(
        self,
        search_t0_us: float,
        search_t1_us: float,
    ) -> RrDidtPreparedSeries | None:
        """Freeze RR preprocessing once for one horizontal-cursor session."""

        if self.bundle is None:
            return None
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current

        t = self.bundle.t
        if len(t) < 2:
            return None
        i0 = int(
            np.searchsorted(
                t, min(search_t0_us, search_t1_us) * 1e-6, side="left"
            )
        )
        i1 = int(
            np.searchsorted(
                t, max(search_t0_us, search_t1_us) * 1e-6, side="left"
            )
        )
        i0 = max(0, min(i0, len(t) - 2))
        i1 = max(i0 + 2, min(i1, len(t) - 1))
        wave_plot = self.__dict__.get("wave_plot")
        y = (
            wave_plot.logical_reverse_recovery_current(self.bundle, self.profile)
            if wave_plot is not None
            else None
        )
        if y is None:
            y = bundle_reverse_recovery_current(self.bundle, self.profile)
        # Keep even an invalid prepared result.  Its fail-closed zero crossing
        # is deterministic, and caching it prevents a malformed long record
        # from repeating the same rejected full-record repair on every event.
        return prepare_rr_didt_series(t, y, i0, i1)

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
        val = float(res.didt) if np.isfinite(float(res.didt)) else 0.0
        available = (
            res.t_pct_a_s is not None
            and res.t_pct_b_s is not None
            and np.isfinite(float(res.t_pct_a_s))
            and np.isfinite(float(res.t_pct_b_s))
            and val > 1e-9
        )
        metric_key = (section, "di/dt")
        if available:
            self.result.unavailable_metrics.discard(metric_key)
        else:
            self.result.unavailable_metrics.add(metric_key)
            val = 0.0
        self.result_table.set_metric_unavailable(section, "di/dt", not available)
        row_key = SLOPE_ROW_KEYS.get((section, "di/dt"))
        sr = self._slope_ranges.get(row_key) if row_key else None
        is_if_irm = bool(sr and sr.ic_reference == "if_irm")
        range_disp = slope_range_result_label(sr, res) if sr else ""
        if section == "关断过程":
            self.result.turn_off.didt = val
            self.result.turn_off.didt_range = range_disp
            self.result_table.set_metric_value(
                "关断过程", "di/dt", val if available else None
            )
            self._sync_ls_off()
        elif section == "开通":
            self.result.turn_on.didt = val
            self.result.turn_on.didt_range = range_disp
            self.result_table.set_metric_value(
                "开通", "di/dt", val if available else None
            )
            self._sync_ls_on()
        else:
            self.result.reverse_recovery.didt_irr = val
            self.result.reverse_recovery.didt_range = range_disp
            self.result_table.set_metric_value(
                "反向恢复", "di/dt", val if available else None
            )
        self.result_table.set_range_text(section, "di/dt", range_disp)
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
                if ta_us <= tb_us:
                    display_th_a, display_th_b = res.th_a, res.th_b
                else:
                    # The oscilloscope cards always name the physical left
                    # cursor A and right cursor B.  Preserve the configured
                    # start/end semantics in the measurement result, but keep
                    # the status thresholds paired with the visible cursors
                    # when a custom percentage range is entered in reverse.
                    display_th_a, display_th_b = res.th_b, res.th_a
                ab_msg = (
                    f"A={t_left:.3f}µs B={t_right:.3f}µs "
                    f"thA={display_th_a:.2f}A thB={display_th_b:.2f}A"
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
            mode = range_disp
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
                f"{range_disp}, {ab_msg}, 值={val:.3f} A/ns"
            )

    def _enable_didt_interaction(self, section: str) -> None:
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        interval = self._parameter_interval_us(section, "di/dt")
        if interval is None:
            return
        key = (section, "di/dt")
        search_t0, search_t1 = interval
        mode_tag = self._rr_didt_mode_tag(section)
        use_zero = mode_tag == "if_irm"
        default_context: DidtMeasurementContext | RrDidtMeasurementContext | None
        if section == "关断过程":
            default_context = self._turn_off_didt_context(search_t0, search_t1)
        elif section == "开通":
            default_context = self._turn_on_didt_context(search_t0, search_t1)
        elif section == "反向恢复":
            default_context = self._rr_didt_context(search_t0, search_t1)
        else:
            default_context = None
        if isinstance(default_context, RrDidtMeasurementContext):
            if use_zero:
                auto_top = default_context.forward_a
                auto_base = default_context.reverse_a
                auto_zero = default_context.zero_a
            else:
                auto_top = default_context.base_a
                auto_base = default_context.forward_a
                auto_zero = None
        else:
            auto_top = (
                default_context.top_a
                if default_context is not None
                else self._default_didt_top_a(section, search_t0, search_t1)
            )
            auto_base = (
                default_context.base_a
                if default_context is not None
                else self._default_didt_base_a(section, search_t0, search_t1)
            )
            auto_zero = (
                self._default_didt_zero_a(section, search_t0, search_t1)
                if use_zero
                else None
            )
        manual = self._restore_manual_didt(key, mode_tag)
        saved_levels = self._saved_didt_slope_state(section)
        self._active_slope_param = key
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
        # Ha/Hb movement changes only the selected levels.  Repairing the time
        # axis, finite samples and spike-guarded extrema is independent of
        # those levels, so freeze it once per interaction session.  Each event
        # still performs its exact raw-sample crossing calculation immediately.
        rr_prepared = (
            self._prepare_rr_didt_cursor_series(search_t0, search_t1)
            if section == "反向恢复"
            else None
        )

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
                section,
                t0,
                t1,
                top_a_live,
                base_a_live,
                zero_live,
                rr_prepared=rr_prepared,
            )
            if res.t_pct_a_s is not None and res.t_pct_b_s is not None:
                ta_us = res.t_pct_a_s * 1e6
                tb_us = res.t_pct_b_s * 1e6
                self.wave_plot.apply_dvdt_ab_times(
                    ta_us,
                    tb_us,
                    refresh_readout=False,
                )
            else:
                self.wave_plot.invalidate_dvdt_ab_times(
                    refresh_readout=False
                )
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
        res0 = (
            default_context.crossing
            if default_context is not None
            and manual is None
            and saved_levels is None
            else self._compute_didt_base_top(
                section,
                search_t0,
                search_t1,
                top_a,
                base_a,
                zero_a if use_zero else None,
                rr_prepared=rr_prepared,
            )
        )
        if res0.t_pct_a_s is not None and res0.t_pct_b_s is not None:
            ta_us = res0.t_pct_a_s * 1e6
            tb_us = res0.t_pct_b_s * 1e6
            self.wave_plot.apply_dvdt_ab_times(ta_us, tb_us)
        if manual is None:
            if res0.t_pct_a_s is not None and res0.t_pct_b_s is not None:
                self._focus_switching_local_view(section, ta_us, tb_us)
            else:
                self._focus_switching_local_view(section, search_t0, search_t1)
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
        # Reuse the extraction-layer Top definition so the default Ha/Hb
        # difference is exactly the ΔVce value shown on the parameter card.
        # The local window above is retained only to place A on the nearest
        # raw Vce sample; it must not independently redefine the level.
        v_top = turn_on_vce_top_from_ic_rise(
            ic,
            vce,
            segs.pulse2_on,
            segs.pulse2_off,
            dt,
        )
        top_seg = vce[w0:w1] if w1 > w0 else vce[i0:i1]
        if len(top_seg) == 0:
            return
        top_local = int(np.argmin(np.abs(top_seg - v_top)))
        top_idx = (w0 + top_local) if w1 > w0 else (i0 + top_local)
        top_t_us = _nearest_raw_level_crossing_time_us(
            t, vce, v_top, top_idx, w0, max(w0 + 1, w1 - 1)
        )
        if top_t_us is None:
            top_t_us = _nearest_raw_level_crossing_time_us(
                t, vce, v_top, top_idx, pre0, i1
            )
        if top_t_us is None:
            top_t_us = float(t[top_idx] * 1e6)
        # The authoritative Top point is intentionally sampled from the
        # pre-rise plateau and can precede the compact turn_on segment by a
        # few samples.  The interaction search range must contain its own
        # default A cursor; otherwise entering the card is valid but the first
        # horizontal drag immediately clips A to a different crossing.
        delta_search_i0 = max(0, min(i0, w0, top_idx))
        delta_search_t0_us = float(t[delta_search_i0] * 1e6)
        delta_search_t1_us = float(t[i1] * 1e6)

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
        move_t_us = _nearest_raw_level_crossing_time_us(
            t, vce, move_v, move_idx, i0, i1
        )
        if move_t_us is None:
            move_t_us = float(t[move_idx] * 1e6)

        key = ("开通", "ΔVce")
        restored = (
            self._manual_delta_vce.get(key)
            if self._manual_cursors_apply_to_current_waveform()
            else None
        )
        if restored is None:
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

        if restored is not None:
            a_t, b_t, ha_v, hb_v = restored
            self.wave_plot.enable_delta_vce_interaction(
                fixed_t_us=a_t,
                fixed_v=ha_v,
                move_t_us=b_t,
                move_v=hb_v,
                on_change=_on_cursor_change,
                search_t0_us=delta_search_t0_us,
                search_t1_us=delta_search_t1_us,
            )
            return

        self.wave_plot.enable_delta_vce_interaction(
            fixed_t_us=top_t_us,
            fixed_v=v_top,
            move_t_us=move_t_us,
            move_v=move_v,
            on_change=_on_cursor_change,
            search_t0_us=delta_search_t0_us,
            search_t1_us=delta_search_t1_us,
        )
        self._show_stored_metric_status("开通", focus_name if focus_name == "Ls_on" else "ΔVce")

    def _enable_turn_off_delta_vce_interaction(self, *, focus_name: str = "ΔVce") -> None:
        self._active_slope_param = None
        if self.bundle is None or self.result is None or self.result.segments is None:
            return
        t = self.bundle.t
        dt = self.bundle.dt
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
        # Segmenter 的 off1 只是有限 post-off 窗；双脉冲的 canonical Vdc
        # 却来自第一、第二脉冲之间的阻断平台。把真实交点搜索有限延伸到
        # pulse2_on 前 200 ns，和平台取值上下文保持一致，不向后追逐第二脉冲。
        blocking_end = off1
        if (
            not self.result.single_pulse_mode
            and segs.pulse2_on > peak_idx
        ):
            blocking_end = max(
                off1,
                min(
                    len(t) - 1,
                    int(segs.pulse2_on) - max(1, int(200e-9 / dt)),
                ),
            )
        if self.result.single_pulse_mode:
            stable_n = max(16, int(round(200e-9 / max(float(dt), 1e-15))))
            crossing_lo = max(peak_idx, off1 - stable_n + 1)
        else:
            crossing_lo = peak_idx
        tail = np.arange(crossing_lo, blocking_end + 1)
        if len(tail) >= 2:
            top_idx = int(tail[np.argmin(np.abs(vce[tail] - v_top))])
        else:
            top_idx = int(search[np.argmin(np.abs(vce[search] - v_top))])
        top_t_us = _nearest_raw_level_crossing_time_us(
            t, vce, v_top, top_idx, crossing_lo, blocking_end
        )
        if top_t_us is None:
            top_t_us = float(t[top_idx] * 1e6)
        key = ("关断过程", "ΔVce")
        restored = (
            self._manual_delta_vce.get(key)
            if self._manual_cursors_apply_to_current_waveform()
            else None
        )
        if restored is None:
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

        if restored is not None:
            a_t, b_t, ha_v, hb_v = restored
            self.wave_plot.enable_delta_vce_interaction(
                fixed_t_us=a_t,
                fixed_v=ha_v,
                move_t_us=b_t,
                move_v=hb_v,
                on_change=_on_cursor_change,
                search_t0_us=float(t[off0] * 1e6),
                search_t1_us=float(t[blocking_end] * 1e6),
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
            search_t1_us=float(t[blocking_end] * 1e6),
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

        def _boundary_channels() -> tuple[str, str]:
            # Without a visible W/kW trace, A/B still describe the exact loss
            # window.  Bind them to the two physical/logical boundary waves
            # instead of pretending that a power card is an Ic-only card.
            return {
                "关断过程": ("vce", "ic"),
                "开通": ("ic", "vce"),
                # Err's chronological left/right boundaries are Vd then Irr.
                "反向恢复": ("v_diode", "irr"),
            }[section]

        if section in {"关断过程", "开通"}:
            from dpt_extractor.models.waveform import bundle_total_current

            raw_voltage = np.asarray(
                self.bundle.get(self.profile.vce), dtype=np.float64
            )
            raw_current = np.asarray(
                bundle_total_current(self.bundle, self.profile), dtype=np.float64
            )
            raw_power_w = raw_voltage * raw_current
            required_power_roles = ("vce", "ic")
            raw_power_absolute = False
        else:
            from dpt_extractor.models.waveform import (
                bundle_reverse_recovery_current,
            )

            raw_voltage = np.asarray(
                self.bundle.get(self.profile.v_diode), dtype=np.float64
            )
            raw_current = np.asarray(
                bundle_reverse_recovery_current(self.bundle, self.profile),
                dtype=np.float64,
            )
            raw_power_w = np.abs(raw_voltage) * np.abs(raw_current)
            required_power_roles = ("v_diode", "irr")
            raw_power_absolute = True

        def _raw_power_peak_kw(t0: float, t1: float) -> float | None:
            t = self.bundle.t
            lo_s, hi_s = sorted((float(t0) * 1e-6, float(t1) * 1e-6))
            i0 = int(np.searchsorted(t, lo_s, side="left"))
            i1 = int(np.searchsorted(t, hi_s, side="left"))
            i0 = max(0, min(i0, len(t) - 2))
            i1 = max(i0 + 1, min(i1, len(t) - 1))
            win = IntegrationWindow(i0, i1, float(t[i0]), float(t[i1]))
            return float(
                peak_power_kw(
                    raw_voltage,
                    raw_current,
                    win,
                    absolute=raw_power_absolute,
                )
            )

        def _power_peak(t0: float, t1: float):
            raw_peak_kw = _raw_power_peak_kw(t0, t1)
            return self.wave_plot.power_peak_in_window(
                min(t0, t1),
                max(t0, t1),
                target_w=(
                    float(raw_peak_kw) * 1000.0
                    if raw_peak_kw is not None
                    else None
                ),
                prefer_abs=raw_power_absolute,
                required_roles=required_power_roles,
                expected_power_w=raw_power_w,
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
            peak_kw = _raw_power_peak_kw(lo, hi)
            if peak_kw is None:
                return False
            _store_power_peak(float(peak_kw))
            if remember:
                self._touch_manual_waveform_source()
                self._manual_intervals[(section, metric_name)] = (lo, hi)
            matched = _power_peak(lo, hi)
            if matched is None:
                self.wave_plot.apply_power_peak_binding(
                    boundary_a_channel=boundary_a,
                    boundary_b_channel=boundary_b,
                )
                self.statusBar().showMessage(
                    f"{section}-{metric_name}: 未显示功率波形，"
                    f"按原始 V×I 重算 {float(peak_kw):.3f} kW，"
                    f"A/B={lo:.3f}~{hi:.3f}µs"
                )
                return True
            channel, _trace_peak_w, peak_value, peak_t_us = matched
            self.wave_plot.apply_power_peak_binding(
                boundary_a_channel=boundary_a,
                boundary_b_channel=boundary_b,
                peak_channel=channel,
                peak_value=float(peak_value),
                peak_t_us=float(peak_t_us),
            )
            self.statusBar().showMessage(
                f"{section}-{metric_name}: 原始 V×I={peak_kw:.3f} kW "
                f"({channel} 用于 A/B/Ha 显示；卡值按原始 V×I，"
                f"{lo:.3f}~{hi:.3f}µs)"
            )
            return True

        matched = _power_peak(t0_us, t1_us)
        boundary_a, boundary_b = _boundary_channels()
        interval_channel = matched[0] if matched is not None else boundary_a
        endpoint_a = matched[0] if matched is not None else boundary_a
        endpoint_b = matched[0] if matched is not None else boundary_b
        if restored is None:
            self._focus_switching_local_view(section, t0_us, t1_us)
        self.wave_plot.enable_interval_interaction(
            start_t_us=t0_us,
            end_t_us=t1_us,
            on_change=lambda ta, tb: _apply_power_peak(ta, tb, remember=True),
            show_horizontal_peak=matched is not None,
            mode="power_peak",
            channel=interval_channel,
            a_channel=endpoint_a,
            b_channel=endpoint_b,
        )
        if matched is None:
            self.wave_plot.apply_power_peak_binding(
                boundary_a_channel=boundary_a,
                boundary_b_channel=boundary_b,
            )
            if restored is not None:
                _apply_power_peak(t0_us, t1_us, remember=False)
                return
            self.statusBar().showMessage(
                f"{section}-{metric_name}: 未显示功率波形，A/B 使用"
                f"{boundary_a}/{boundary_b} 损耗边界，拖动后按原始 V×I 重算"
            )
            return
        channel, peak_w, peak_value, peak_t_us = matched
        self.wave_plot.apply_power_peak_binding(
            boundary_a_channel=boundary_a,
            boundary_b_channel=boundary_b,
            peak_channel=channel,
            peak_value=float(peak_value),
            peak_t_us=float(peak_t_us),
        )
        if restored is not None:
            # The Math trace is only the display source for A/B/Ha.  A saved
            # interval must restore the same authoritative raw V×I card value
            # used while dragging; otherwise a scaled-but-shape-compatible
            # Math expression (for example 0.8*Vce*Ic) silently rewrites the
            # report value every time the user re-enters Pmax/Pdmax.
            _apply_power_peak(t0_us, t1_us, remember=False)
            return
        self.statusBar().showMessage(
            f"{section}-{metric_name}: {float(peak_w) / 1000.0:.3f} kW "
            f"({channel} 用于 A/B/Ha 显示；卡值按原始 V×I，"
            f"{t0_us:.3f}~{t1_us:.3f}µs，拖动 A/B 后重算)"
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

        completed = self._rr_measurement_window_indices()
        rr_context_i1 = completed[2] if completed is not None else rr1
        ipk = err_recovery_peak_index(irr[rr0 : rr_context_i1 + 1], dt)
        ipk_global = rr0 + ipk
        markers = err_energy_markers(
            t,
            irr,
            v_diode,
            rr0,
            rr_context_i1,
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
        search_t0 = min(search_t0, float(ta_us), float(tb_us))
        search_t1 = max(search_t1, float(ta_us), float(tb_us))

        # 首次进入 Err 时将恢复区放到推荐位置；已经存在手动 energy
        # 光标时，用户可能刚刚平移/缩放到要复核的局部区域。二次点击只恢复
        # 光标和交互状态，不应覆盖当前 X 轴视图。
        if restored is None and legacy is None:
            self._focus_switching_local_view(
                "反向恢复",
                min(ta_us, tb_us) - 0.15,
                max(ta_us, tb_us) + 0.15,
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
            search_t0 = min(search_t0, float(ta_us), float(tb_us))
            search_t1 = max(search_t1, float(ta_us), float(tb_us))
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
        search_t0 = min(search_t0, float(ta_us), float(tb_us))
        search_t1 = max(search_t1, float(ta_us), float(tb_us))
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
        if (
            not self._manual_cursors_apply_to_current_waveform()
            or self._manual_trr_measure is None
        ):
            return None
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

        if restored is None:
            self._focus_switching_local_view("反向恢复", t0_us, t1_us)
        self.wave_plot.enable_irr_peak_interaction(t0_us, t1_us, _on_irr_interval)
        _apply_irr_interval(t0_us, t1_us, remember=restored is not None)

    def _enable_trr_interaction(self) -> None:
        """Trr：Hb=I_RM 尖峰，Ha=峰后恢复稳定平台的可见中线。"""
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
                pulse2_off=segs.pulse2_off,
            )
            if m is None:
                self.wave_plot.clear_parameter_cursor_context()
                self.statusBar().showMessage(
                    "反向恢复-Trr: 无法在逻辑 Irr 主瓣上取得完整稳定平台中线交点，光标不可用"
                )
                return
            ha_a, hb_a = m.ha, m.hb
            ta_us, tb_us = m.ta_s * 1e6, m.tb_s * 1e6
            peak_idx = m.peak_idx
            trr_init = m.trr_ns
        else:
            ha_a, hb_a, ta_us, tb_us, peak_idx = saved
            trr_init = abs(tb_us - ta_us) * 1e3
        pulse2_off_idx = max(0, min(int(segs.pulse2_off), len(t) - 1))
        if peak_idx is None or pulse2_off_idx <= int(peak_idx):
            self.wave_plot.clear_parameter_cursor_context()
            self.statusBar().showMessage(
                "反向恢复-Trr: 第二脉冲关断界早于恢复峰，光标不可用"
            )
            return
        fall_end_idx = reverse_recovery_tail_end_index(
            t,
            i1,
            on1,
            peak_idx=peak_idx,
            pulse2_off=segs.pulse2_off,
            dt=self.bundle.dt,
        )
        fall_end_idx = min(fall_end_idx, pulse2_off_idx - 1)
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
                f"反向恢复 Trr={trr_ns:.3f}ns（手动卡尺；"
                f"A={ta_us:.3f}µs B={tb_us:.3f}µs，"
                f"Ha={ha:.2f}A，Hb={hb:.2f}A）"
            )

        if saved is None:
            self._focus_switching_local_view(
                "反向恢复",
                ta_us,
                max(tb_us, t1_us),
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
            stable_a = m.stable_level
            stable_text = (
                f"，恢复平台={float(stable_a):.2f}A"
                if stable_a is not None
                else ""
            )
            self.statusBar().showMessage(
                f"反向恢复 Trr={trr_init:.3f}ns（Hb=I_RM尖峰 {hb_a:.2f}A，"
                f"Ha=恢复稳定平台中线 {ha_a:.2f}A{stable_text}；"
                f"A/B=Ha与主瓣上升/下降沿首交点）"
            )

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

    def _cursor_endpoint_channels_for_param(
        self, section: str, name: str
    ) -> tuple[str | None, str | None]:
        """Semantic A/B waveform sources for mixed-boundary interval rows."""

        timing = {
            ("开通", "Ton"): ("vge", "ic"),
            ("开通", "Td_on"): ("vge", "ic"),
            ("开通", "Tr"): ("ic", "ic"),
            ("关断过程", "Toff"): ("vge", "ic"),
            ("关断过程", "Td_off"): ("vge", "ic"),
            ("关断过程", "Tf"): ("ic", "ic"),
        }
        bound = timing.get((section, name))
        if bound is not None:
            return bound
        extrema = {
            # turn_off_ic_fall_window() delegates both limits to the Vge
            # falling-edge window; Ic supplies the extrema inside that window.
            ("关断过程", "Ic_off_max"): ("vge", "vge"),
            # _turn_off_vce_max_window_indices() finds both sides of the Vce
            # overshoot itself.
            ("关断过程", "Vce_off_max"): ("vce", "vce"),
            # _turn_on_ic_max_window_indices(): A=Ic rise, B=Vce base.
            ("开通", "Ic_on_max"): ("ic", "vce"),
            # turn_on_vce_on_max_window_indices(): A=Vge rise, B=Vce base.
            ("开通", "Vce_on_max"): ("vge", "vce"),
            ("反向恢复", "Vrr"): ("v_diode", "v_diode"),
        }
        bound = extrema.get((section, name))
        if bound is not None:
            return bound
        if section == "短路过程" and name in {
            "应力Vpeak_本管",
            "应力Vpeak_对管",
        }:
            # short_circuit_vpeak_cursors(): both boundaries are Vge base crossings.
            return "vge", "vge"
        if section == "短路过程" and name == "Desat动作时间":
            desat_channel = self._short_circuit_desat_channel()
            return "vge", desat_channel
        return None, None

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
        restored = (
            self._manual_turn_on_current
            if self._manual_cursors_apply_to_current_waveform()
            else None
        )

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
        from dpt_extractor.metrics.plateau_level import (
            turn_on_ic_b_cross_ha_us,
            turn_on_ic_link_default_times,
        )
        from dpt_extractor.models.waveform import bundle_total_current

        # 带符号：下桥导通前基线为负，光标须贴真实波形（上桥电流为正，等价不变）
        ic = bundle_total_current(self.bundle, self.profile)
        event_end_idx = self.result.segments.pulse2_off
        if restored is not None:
            t_a_us, t_b_us, hb0, ha0 = restored
        else:
            vge10_s: float | None = None
            try:
                timing = self._turn_on_timing_instants()
                vge10_s = timing.t_v10_s
            except Exception:
                vge10_s = None
            t_a_us, t_b_us, hb0, ha0 = turn_on_ic_link_default_times(
                t,
                ic,
                i0,
                i1,
                dt,
                event_end_idx=event_end_idx,
                vge10_s=vge10_s,
                detect_window_ns=self.cfg.smoothing.detect_window_ns,
            )
            if not all(
                np.isfinite(value) for value in (t_a_us, t_b_us, hb0, ha0)
            ) or not t_a_us < t_b_us:
                self.wave_plot.clear_parameter_cursor_context()
                self.statusBar().showMessage(
                    "开通-开通电流: 本次开通主沿与稳定平台没有真实交点，默认光标不可用"
                )
                return
            if self.result is not None:
                ha0 = float(self.result.turn_on.turn_on_current)
                # The card value is authoritative.  Recompute B against that
                # final displayed Ha so a future pipeline fallback cannot leave
                # the vertical cursor attached to an older platform level.
                t_b_us = turn_on_ic_b_cross_ha_us(
                    t,
                    ic,
                    i0,
                    i1,
                    ha0,
                    dt,
                    event_end_idx=event_end_idx,
                )

        if restored is None:
            self._focus_switching_local_view("开通", t_a_us, t_b_us)
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
        if (
            self.bundle is None
            or self.result is None
            or self.result.segments is None
        ):
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

        def _on_interval_change(
            t0_us: float,
            t1_us: float,
            *,
            remember: bool = True,
        ) -> None:
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
            if remember:
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
        self.wave_plot.enable_crosstalk_interaction(
            start_t_us=t0_us,
            end_t_us=t1_us,
            on_change=_on_interval_change,
        )
        _on_interval_change(t0_us, t1_us, remember=False)

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
        key = ("短路过程", name)
        restored_state = (
            self._manual_short_current.get(key)
            if self._manual_cursors_apply_to_current_waveform()
            else None
        )
        restored = self._manual_intervals.get(key)
        if restored_state is not None:
            t_a_us, t_b_us, hb, ha = restored_state
        elif restored is not None:
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
            self._manual_intervals[key] = (ta, tb)
            self._manual_short_current[key] = (
                float(cur_a_us),
                float(cur_b_us),
                float(cur_hb),
                float(cur_ha),
            )
            sc = self.result.short_circuit
            if name == "短路电流Imax":
                sc.ic_max = float(cur_ha)
                self.result.idc = float(cur_ha)
                self.result.idc_set = float(cur_ha)
                # The detected Imax report condition must follow the final
                # hand-adjusted measurement as well as the result/table.  The
                # picture sheet prefers this explicit snapshot over sc.ic_max.
                self._apply_detected_short_imax(self.result)
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
            emit_result_on_enter=restored_state is not None or restored is not None,
        )
        if restored_state is None and restored is None:
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
            self.wave_plot.clear_parameter_cursor_context()
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
            # 记住用户手动调整的区间，下次点击该参数时恢复。跨通道
            # IEC 时间参数的 A/B 是语义端点（例如 A=Vge10、B=Ic10），
            # 即使物理时间倒序也不能交换字母含义。
            self._touch_manual_waveform_source()
            if (section, name) in self._IEC_TIMING_PARAMS:
                self._manual_intervals[(section, name)] = (
                    float(t0_us),
                    float(t1_us),
                )
            else:
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
            and restored is None
        ):
            self._focus_switching_local_view(section, t0_us, t1_us)
        cursor_a_channel, cursor_b_channel = (
            self._cursor_endpoint_channels_for_param(section, name)
        )
        self.wave_plot.enable_interval_interaction(
            start_t_us=t0_us,
            end_t_us=t1_us,
            on_change=_on_interval_change,
            mode=(
                "semantic_interval"
                if (section, name) in self._IEC_TIMING_PARAMS
                else "interval"
            ),
            channel=self._channel_for_param(section, name),
            a_channel=cursor_a_channel,
            b_channel=cursor_b_channel,
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
            peak_y = (
                float(manual_extreme[0])
                if manual_extreme is not None
                else self._peak_y_for_param(section, name, i0, i1)
            )
            if peak_y is not None:
                self.wave_plot.set_interval_peak_horizontal(
                    float(peak_y),
                    channel=self._channel_for_param(section, name),
                    t0_us=ta if manual_extreme is None else None,
                    t1_us=tb if manual_extreme is None else None,
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
                if not np.isfinite(val):
                    return None
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
                if not np.isfinite(val):
                    return None
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
        action_hint = (
            "拖动 Ha/Hb 后 A/B 自动跟随重算"
            if name in {"dv/dt", "di/dt"}
            else "拖动光标后重算"
        )
        self.statusBar().showMessage(
            f"{section}-{name}: 当前值={disp}（{action_hint}）"
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
        unavailable = self.result.is_metric_unavailable("关断过程", "di/dt")
        off.ls_off = (
            float(off.delta_vce / off.didt)
            if not unavailable and off.didt > 1e-9
            else 0.0
        )
        key = ("关断过程", "Ls_off")
        if unavailable:
            self.result.unavailable_metrics.add(key)
        else:
            self.result.unavailable_metrics.discard(key)
        self.result_table.set_metric_unavailable(*key, unavailable)
        self.result_table.set_metric_value(*key, None if unavailable else off.ls_off)

    def _sync_ls_on(self) -> None:
        """Ls_on = 开通 ΔVce / (开通 di/dt)，单位 nH，与 Ls_off 对称（ΔVce 可光标卡值）。"""
        if self.result is None:
            return
        on = self.result.turn_on
        unavailable = self.result.is_metric_unavailable("开通", "di/dt")
        on.ls_on = (
            float(on.delta_vce / on.didt)
            if not unavailable and on.didt > 1e-9
            else 0.0
        )
        key = ("开通", "Ls_on")
        if unavailable:
            self.result.unavailable_metrics.add(key)
        else:
            self.result.unavailable_metrics.discard(key)
        self.result_table.set_metric_unavailable(*key, unavailable)
        self.result_table.set_metric_value(*key, None if unavailable else on.ls_on)

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
        marker = default_irr_trr_measure(
            t,
            irr,
            rr0,
            rr1,
            segs.pulse2_on,
            on0,
            on1,
            pulse2_off=segs.pulse2_off,
        )
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
            completed = self._rr_measurement_window_indices()
            rr_context_i1 = completed[2] if completed is not None else rr1
            markers = err_energy_markers(
                t,
                irr_sig,
                self.bundle.get(self.profile.v_diode),
                rr0,
                rr_context_i1,
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
                completed = self._rr_measurement_window_indices()
                if completed is None:
                    return None
                i0, i1, _rr_context_i1, _extended = completed
                return t[i0] * 1e6, t[i1] * 1e6

        return None

    def _restore_manual_result_values_after_recalculation(
        self,
        previous: ExtractResult,
    ) -> None:
        """Keep valid hand-adjusted metrics materialized after re-extraction.

        Cursor caches and ``ExtractResult`` are two views of one user action.
        A non-reset recalculation may refresh automatic metrics, but it must not
        leave preserved manual cursors paired with default report values.
        Only fields owned by an existing manual cache are copied; every other
        freshly extracted metric remains untouched.
        """

        current = self.result
        if current is None or not self._manual_cursors_apply_to_current_waveform():
            return
        if bool(previous.short_circuit_mode) != bool(current.short_circuit_mode):
            return
        previous_pair = (
            int(previous.off_pulse_index),
            int(previous.on_pulse_index),
        )
        current_pair = (
            int(current.off_pulse_index),
            int(current.on_pulse_index),
        )
        if previous_pair != current_pair:
            return

        def _restore_metric_availability(section: str, name: str) -> None:
            key = (section, name)
            if previous.is_metric_unavailable(section, name):
                current.unavailable_metrics.add(key)
            else:
                current.unavailable_metrics.discard(key)

        intervals = set(self._manual_intervals)
        extremes = set(self._manual_extreme_values)
        energies = set(self._manual_energy)
        deltas = set(self._manual_delta_vce)
        dvdts = set(self._manual_dvdt)
        didts = set(self._manual_didt)
        short_current = set(self._manual_short_current)

        if current.short_circuit_mode:
            old_sc = previous.short_circuit
            new_sc = current.short_circuit
            manual_keys = intervals | extremes | short_current
            if ("短路过程", "短路电流Imax") in manual_keys:
                new_sc.ic_max = float(old_sc.ic_max)
                current.idc = float(previous.idc)
                current.idc_set = previous.idc_set
            if ("短路过程", "短路时间Tsc") in manual_keys:
                new_sc.tsc = float(old_sc.tsc)
                new_sc.tsc_start_us = old_sc.tsc_start_us
                new_sc.tsc_end_us = old_sc.tsc_end_us
                new_sc.tsc_range = str(old_sc.tsc_range)
            if ("短路过程", "短路能量Esc_本管") in manual_keys:
                new_sc.esc_dut = float(old_sc.esc_dut)
                new_sc.energy_dut_channel = str(old_sc.energy_dut_channel)
            if ("短路过程", "应力Vpeak_本管") in manual_keys:
                new_sc.vpeak_dut = float(old_sc.vpeak_dut)
            if ("短路过程", "短路能量Esc_对管") in manual_keys:
                new_sc.esc_other = float(old_sc.esc_other)
                new_sc.energy_other_channel = str(old_sc.energy_other_channel)
            if ("短路过程", "应力Vpeak_对管") in manual_keys:
                new_sc.vpeak_other = float(old_sc.vpeak_other)
            if ("短路过程", "Desat动作时间") in manual_keys:
                new_sc.desat_time = old_sc.desat_time
                new_sc.desat_range = str(old_sc.desat_range)
            return

        old_off, new_off = previous.turn_off, current.turn_off
        old_on, new_on = previous.turn_on, current.turn_on
        old_rr, new_rr = previous.reverse_recovery, current.reverse_recovery

        off_delta_manual = ("关断过程", "ΔVce") in deltas
        off_didt_manual = ("关断过程", "di/dt") in didts
        off_ls_manual = ("关断过程", "Ls_off") in intervals
        if off_delta_manual:
            new_off.delta_vce = float(old_off.delta_vce)
        if ("关断过程", "Ic_off_max") in intervals | extremes:
            new_off.ic_off_max = float(old_off.ic_off_max)
        if ("关断过程", "Vce_off_max") in intervals | extremes:
            new_off.vce_off_max = float(old_off.vce_off_max)
        if ("关断过程", "dv/dt") in dvdts:
            new_off.dvdt = float(old_off.dvdt)
            new_off.dvdt_range = str(old_off.dvdt_range)
        if off_didt_manual:
            new_off.didt = float(old_off.didt)
            new_off.didt_range = str(old_off.didt_range)
            _restore_metric_availability("关断过程", "di/dt")
        if off_ls_manual:
            new_off.didt = float(old_off.didt)
            new_off.didt_range = str(old_off.didt_range)
            _restore_metric_availability("关断过程", "di/dt")

        off_timing_keys = {
            ("关断过程", "Toff"),
            ("关断过程", "Td_off"),
            ("关断过程", "Tf"),
        }
        if intervals & off_timing_keys:
            new_off.toff = float(old_off.toff)
            new_off.td_off = float(old_off.td_off)
            new_off.tf = float(old_off.tf)
        if ("关断过程", "串扰电压") in intervals:
            new_off.crosstalk_v = float(old_off.crosstalk_v)
            new_off.crosstalk_vmax = float(old_off.crosstalk_vmax)
            new_off.crosstalk_vmin = float(old_off.crosstalk_vmin)
        if (
            ("关断过程", "Pmax") in intervals
            or ("关断过程", "Eoff") in energies
        ):
            new_off.pmax = float(old_off.pmax)
        if ("关断过程", "Eoff") in energies:
            new_off.eoff = float(old_off.eoff)

        on_delta_manual = ("开通", "ΔVce") in deltas
        on_didt_manual = ("开通", "di/dt") in didts
        on_ls_manual = ("开通", "Ls_on") in intervals
        if on_delta_manual:
            new_on.delta_vce = float(old_on.delta_vce)
        if ("开通", "Ic_on_max") in intervals | extremes:
            new_on.ic_on_max = float(old_on.ic_on_max)
        if ("开通", "Vce_on_max") in intervals | extremes:
            new_on.vce_on_max = float(old_on.vce_on_max)
        if self._manual_turn_on_current is not None:
            new_on.turn_on_current = float(old_on.turn_on_current)
        if ("开通", "dv/dt") in dvdts:
            new_on.dvdt = float(old_on.dvdt)
            new_on.dvdt_range = str(old_on.dvdt_range)
        if on_didt_manual:
            new_on.didt = float(old_on.didt)
            new_on.didt_range = str(old_on.didt_range)
            _restore_metric_availability("开通", "di/dt")
        if on_ls_manual:
            new_on.didt = float(old_on.didt)
            new_on.didt_range = str(old_on.didt_range)
            _restore_metric_availability("开通", "di/dt")

        on_timing_keys = {
            ("开通", "Ton"),
            ("开通", "Td_on"),
            ("开通", "Tr"),
        }
        if intervals & on_timing_keys:
            new_on.ton = float(old_on.ton)
            new_on.td_on = float(old_on.td_on)
            new_on.tr = float(old_on.tr)
        if ("开通", "串扰电压") in intervals:
            new_on.crosstalk_v = float(old_on.crosstalk_v)
            new_on.crosstalk_vmax = float(old_on.crosstalk_vmax)
            new_on.crosstalk_vmin = float(old_on.crosstalk_vmin)
        if ("开通", "Pmax") in intervals or ("开通", "Eon") in energies:
            new_on.pmax = float(old_on.pmax)
        if ("开通", "Eon") in energies:
            new_on.eon = float(old_on.eon)

        if ("反向恢复", "Irr") in intervals:
            new_rr.irr = float(old_rr.irr)
        if self._manual_trr_measure is not None:
            new_rr.trr = float(old_rr.trr)
        if ("反向恢复", "Vrr") in intervals | extremes:
            new_rr.vrr = float(old_rr.vrr)
        if ("反向恢复", "dv/dt") in dvdts:
            new_rr.dvdt_max = float(old_rr.dvdt_max)
            new_rr.dvdt_range = str(old_rr.dvdt_range)
        if ("反向恢复", "di/dt") in didts:
            new_rr.didt_irr = float(old_rr.didt_irr)
            new_rr.didt_range = str(old_rr.didt_range)
            _restore_metric_availability("反向恢复", "di/dt")
        if (
            ("反向恢复", "Pdmax") in intervals
            or ("反向恢复", "Err") in energies
        ):
            new_rr.pdmax = float(old_rr.pdmax)
        if ("反向恢复", "Err") in energies:
            new_rr.err = float(old_rr.err)

        if off_delta_manual or off_didt_manual or off_ls_manual:
            unavailable = current.is_metric_unavailable("关断过程", "di/dt")
            new_off.ls_off = (
                float(new_off.delta_vce / new_off.didt)
                if not unavailable and new_off.didt > 1e-9
                else 0.0
            )
            if unavailable:
                current.unavailable_metrics.add(("关断过程", "Ls_off"))
            else:
                current.unavailable_metrics.discard(("关断过程", "Ls_off"))
        if on_delta_manual or on_didt_manual or on_ls_manual:
            unavailable = current.is_metric_unavailable("开通", "di/dt")
            new_on.ls_on = (
                float(new_on.delta_vce / new_on.didt)
                if not unavailable and new_on.didt > 1e-9
                else 0.0
            )
            if unavailable:
                current.unavailable_metrics.add(("开通", "Ls_on"))
            else:
                current.unavailable_metrics.discard(("开通", "Ls_on"))

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
            active_metric = self.result_table._active_metric
            if reset_manual:
                self._clear_manual_adjustments()
                active_param = None
            previous_result = deepcopy(self.result) if self.result is not None else None
            try:
                self.result = run_extraction(self.bundle, self.profile, self.cfg)
            except Exception as exc:
                self.result = None
                self._clear_manual_adjustments(reset_plot=False)
                self.wave_plot.plot_waveforms(self.bundle, self.profile, None)
                mode_label = MODE_UI_LABELS[parse_test_mode(self.cfg.test_mode.mode)]
                self.result_table.set_mode_placeholder(
                    mode_label,
                    self._extraction_placeholder_detail(
                        str(exc),
                        source_kind=self.bundle.meta.source_kind,
                    ),
                )
                self.statusBar().showMessage(
                    f"{mode_label}：参数未计算，波形已保留"
                )
                return

            pulse_pair_changed = bool(
                previous_result is not None
                and not previous_result.short_circuit_mode
                and not self.result.short_circuit_mode
                and (
                    int(previous_result.off_pulse_index),
                    int(previous_result.on_pulse_index),
                )
                != (
                    int(self.result.off_pulse_index),
                    int(self.result.on_pulse_index),
                )
            )
            if pulse_pair_changed:
                # Manual card state belongs to one concrete measurement pair.
                # A different pair starts from its own automatic result instead
                # of inheriting cursor caches or report values from the old pair.
                self._clear_manual_adjustments(reset_plot=False)

            if previous_result is not None and not pulse_pair_changed:
                self._restore_manual_result_values_after_recalculation(
                    previous_result
                )
            # Sync the report condition only after manual values have been
            # rematerialized; otherwise a non-reset extraction leaves the
            # picture condition at the automatic Imax while the data row uses
            # the restored hand-adjusted value.
            self._apply_detected_short_imax(self.result)
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
            elif active_metric is not None:
                # Replotting installs the default global cursor context while
                # the result table keeps its selected row.  Restore that row's
                # complete parameter context so A/B/Ha/Hb and the readout still
                # belong to the active card.  Unavailable rows intentionally
                # restore the empty parameter context in _on_value_clicked().
                self._on_value_clicked(*active_metric)

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
        if _same_report_path(selected, self._report_output_path):
            QMessageBox.warning(
                self,
                "模板位置不可用",
                "报告模板源不能与当前项目报告文件相同，请先选择另一个模板或报告位置。",
            )
            return
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
        if _same_report_path(selected, template):
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
        capture_total = max(1, len(params))
        self._set_report_progress(
            capture_start,
            REPORT_PROGRESS_TOTAL,
            "准备报告截图...",
            eta_phase="report-capture",
            eta_completed=0,
            eta_total=len(params),
            timing_stage="capture",
            timing_completed=0,
            timing_total=len(params),
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
                    eta_phase="report-capture",
                    eta_completed=index,
                    eta_total=len(params),
                    timing_stage="capture",
                    timing_completed=index,
                    timing_total=len(params),
                )
        finally:
            vb.setRange(
                xRange=(float(old_x[0]), float(old_x[1])),
                yRange=(float(old_y[0]), float(old_y[1])),
                padding=0.0,
            )
            self.wave_plot._settle_report_view_layout()
        self._set_report_progress(
            REPORT_PROGRESS_CAPTURE_DONE,
            REPORT_PROGRESS_TOTAL,
            "截图完成，准备写入 Excel...",
        )
        return images

    def _snapshot_report_manual_state(self) -> dict[str, object]:
        return {
            name: deepcopy(getattr(self, name))
            for name in _REPORT_MANUAL_STATE_ATTRS
        }

    def _current_report_page_state(self) -> _ReportPageState:
        return _ReportPageState(
            bundle=self.bundle,
            profile=self.profile,
            cfg=self.cfg,
            result=self.result,
            slope_ranges=dict(self._slope_ranges),
            manual_state=self._snapshot_report_manual_state(),
            active_metric=deepcopy(self.result_table._active_metric),
            active_slope_param=deepcopy(self._active_slope_param),
            display_state=deepcopy(self.wave_plot.snapshot_report_display_state()),
        )

    def _apply_report_page_state(self, page: _ReportPageState) -> None:
        self.bundle = page.bundle
        self.profile = page.profile
        self.cfg = page.cfg
        self.result = page.result
        self._slope_ranges = deepcopy(page.slope_ranges)
        for name in _REPORT_MANUAL_STATE_ATTRS:
            if name in page.manual_state:
                setattr(self, name, deepcopy(page.manual_state[name]))
        self.result_table.set_slope_ranges(self._slope_ranges)
        if self.result is not None:
            self.result_table.set_result(self.result)
        else:
            mode_label = MODE_UI_LABELS[parse_test_mode(self.cfg.test_mode.mode)]
            self.result_table.set_mode_placeholder(mode_label, "当前页面无提取结果")
        if self.bundle is not None:
            self.wave_plot.plot_waveforms(self.bundle, self.profile, self.result)
        if page.active_metric is not None and self.result is not None:
            self._on_value_clicked(*page.active_metric)
        else:
            self.result_table._active_metric = None
            self.result_table.table.clearSelection()
            self.wave_plot.disable_interactive_cursors()
        self._active_slope_param = deepcopy(page.active_slope_param)
        self.wave_plot.restore_report_display_state(page.display_state)

    def _start_report_capture_sequence(
        self,
        tempdir: tempfile.TemporaryDirectory,
        results: list[ExtractResult],
        *,
        request_id: int | None = None,
        temperature_code: str | None = None,
        temperature_labels: dict[str, str] | None = None,
        phase_code: str | None = None,
        report_conditions: ReportConditions | None = None,
        image_result_index: int | None = None,
        capture_bundle: WaveformBundle | None = None,
        capture_profile: BridgeProfile | None = None,
        capture_cfg: AppConfig | None = None,
        capture_result: ExtractResult | None = None,
        capture_slope_ranges: dict[str, SlopeRange] | None = None,
        capture_manual_state: dict[str, object] | None = None,
        capture_active_metric: tuple[str, str] | None = None,
        capture_active_slope_param: tuple[str, str] | None = None,
        capture_display_state: dict[str, object] | None = None,
        capture_active_state_frozen: bool = False,
    ) -> None:
        preferred_result = capture_result if capture_result is not None else self.result
        if preferred_result is None or not results:
            _safe_cleanup_tempdir(tempdir)
            self._finish_report_progress("写入失败", ok=False)
            self._release_report_operation()
            return
        if not self._report_progress_active:
            self._begin_report_progress(REPORT_PROGRESS_TOTAL, "准备报告截图...")
        capture_start = max(
            REPORT_PROGRESS_PREPARE_DONE,
            min(self.report_progress.value(), REPORT_PROGRESS_CAPTURE_DONE),
        )
        vb = self.wave_plot.plot.getPlotItem().getViewBox()
        old_x, old_y = vb.viewRange()
        if request_id is None:
            self._report_request_id += 1
            request_id = self._report_request_id
        resolved_image_index = (
            int(image_result_index)
            if image_result_index is not None
            else _report_image_result_index(results, preferred_result)
        )
        resolved_image_index = max(0, min(resolved_image_index, len(results) - 1))
        capture_page = _ReportPageState(
            bundle=(
                capture_bundle
                if capture_bundle is not None
                else _snapshot_waveform_bundle(self.bundle)
            ),
            profile=capture_profile if capture_profile is not None else self.profile,
            cfg=deepcopy(capture_cfg if capture_cfg is not None else self.cfg),
            result=deepcopy(results[resolved_image_index]),
            slope_ranges=deepcopy(
                capture_slope_ranges
                if capture_slope_ranges is not None
                else self._slope_ranges
            ),
            manual_state=deepcopy(
                capture_manual_state
                if capture_manual_state is not None
                else self._snapshot_report_manual_state()
            ),
            active_metric=deepcopy(
                capture_active_metric
                if capture_active_state_frozen
                else self.result_table._active_metric
            ),
            active_slope_param=deepcopy(
                capture_active_slope_param
                if capture_active_state_frozen
                else self._active_slope_param
            ),
            display_state=deepcopy(
                capture_display_state
                if capture_display_state is not None
                else self.wave_plot.snapshot_report_display_state()
            ),
        )
        self._report_capture_state = _ReportCaptureState(
            request_id=request_id,
            tempdir=tempdir,
            directory=Path(tempdir.name),
            params=(),
            results=results,
            old_x=[float(old_x[0]), float(old_x[1])],
            old_y=[float(old_y[0]), float(old_y[1])],
            capture_start=capture_start,
            capture_span=max(1, REPORT_PROGRESS_CAPTURE_DONE - capture_start),
            capture_size=self._report_plot_capture_size(),
            temperature_code=(
                temperature_code
                if temperature_code in TEMP_CONDITION_DEFAULTS
                else self._current_temperature_code()
            ),
            temperature_labels=dict(
                temperature_labels
                if temperature_labels is not None
                else self._temperature_display_labels()
            ),
            phase_code=(
                str(phase_code).strip().upper()
                if phase_code is not None
                else self._current_report_phase_code()
            ),
            report_conditions=deepcopy(
                report_conditions
                if report_conditions is not None
                else ShortReportConditions()
                if preferred_result.short_circuit_mode
                else DptReportConditions()
            ),
            image_result_index=resolved_image_index,
            capture_page=capture_page,
            restore_page=self._current_report_page_state(),
            images={},
        )
        state = self._report_capture_state
        # Applying the capture page can partially mutate widgets before it
        # raises.  Mark restoration as required before the first mutation so
        # both the page snapshot and the caller's exact ViewBox are recoverable.
        state.snapshot_active = True
        try:
            self._apply_report_page_state(state.capture_page)
            state.params = self._report_image_params()
        except Exception:
            self._report_capture_state = None
            try:
                self._restore_report_capture_view(state)
            except Exception:
                # Cleanup must not replace the original capture-initialization
                # exception with a secondary restoration failure.
                pass
            finally:
                _safe_cleanup_tempdir(state.tempdir)
            raise
        self._set_report_progress(
            capture_start,
            REPORT_PROGRESS_TOTAL,
            "准备报告截图...",
            eta_phase="report-capture",
            eta_completed=0,
            eta_total=len(state.params),
            timing_stage="capture",
            timing_completed=0,
            timing_total=len(state.params),
        )
        self.wave_plot._fit_full_range()
        QTimer.singleShot(0, self._capture_next_report_image)

    def _restore_report_capture_view(self, state: _ReportCaptureState) -> None:
        if state.snapshot_active:
            self._apply_report_page_state(state.restore_page)
            state.snapshot_active = False
        vb = self.wave_plot.plot.getPlotItem().getViewBox()
        vb.setRange(
            xRange=(state.old_x[0], state.old_x[1]),
            yRange=(state.old_y[0], state.old_y[1]),
            padding=0.0,
        )
        self.wave_plot._settle_report_view_layout()

    def _start_report_write_after_capture(
        self,
        state: _ReportCaptureState,
    ) -> None:
        """Start Excel work after restored widget geometry reaches the event loop."""

        if state.request_id != self._report_request_id:
            _safe_cleanup_tempdir(state.tempdir)
            return
        try:
            self._start_report_write_task(
                state.tempdir,
                state.images or {},
                state.results,
                request_id=state.request_id,
                temperature_code=state.temperature_code,
                temperature_labels=state.temperature_labels,
                phase_code=state.phase_code,
                report_conditions=state.report_conditions,
                image_result_index=state.image_result_index,
            )
        except Exception as exc:
            self._fail_report_capture(state, exc)

    def _fail_report_capture(
        self,
        state: _ReportCaptureState,
        exc: Exception,
    ) -> None:
        self._report_capture_state = None
        try:
            self._restore_report_capture_view(state)
        except Exception:
            pass
        _safe_cleanup_tempdir(state.tempdir)
        self._finish_report_progress("写入失败", ok=False)
        self._release_report_operation()
        QMessageBox.critical(self, "写入报告失败", str(exc))

    def _capture_next_report_image(self) -> None:
        state = self._report_capture_state
        if state is None:
            return
        if state.request_id != self._report_request_id:
            self._report_capture_state = None
            try:
                self._restore_report_capture_view(state)
            except Exception:
                pass
            _safe_cleanup_tempdir(state.tempdir)
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
                self._report_capture_state = None
                # Leave one event-loop boundary between hiding the temporary
                # overview widgets and starting the Excel worker.  This lets
                # Windows/Qt commit the restored high-DPI layout instead of
                # exposing the now-unpainted 86px + 20px reserved area.
                QTimer.singleShot(
                    0,
                    lambda state=state: self._start_report_write_after_capture(state),
                )
                return

            section, name = state.params[state.index]
            if (section, name) == DPT_OVERVIEW_IMAGE_PARAM:
                self.wave_plot._fit_full_range()
            elif self.result is not None and self.result.short_circuit_mode:
                self.wave_plot._fit_full_range()
                self._on_value_clicked(section, name)
                self.wave_plot._fit_full_range()
            else:
                self._on_value_clicked(section, name)
            # 让本次参数点击/缩放先完整经过一次事件循环，再抓取像素；避免
            # 选中图片后需要轻微移动才能恢复的陈旧帧，也避免嵌套 processEvents 重入。
            QTimer.singleShot(0, self._save_current_report_image)
        except Exception as exc:
            self._fail_report_capture(state, exc)

    def _save_current_report_image(self) -> None:
        state = self._report_capture_state
        if state is None:
            return
        if state.request_id != self._report_request_id:
            self._report_capture_state = None
            try:
                self._restore_report_capture_view(state)
            except Exception:
                pass
            _safe_cleanup_tempdir(state.tempdir)
            return
        try:
            total = len(state.params)
            if state.index >= total:
                QTimer.singleShot(0, self._capture_next_report_image)
                return
            section, name = state.params[state.index]
            display_index = state.index + 1
            path = state.directory / self._safe_report_image_name(
                section,
                name,
                display_index,
            )
            self._save_report_plot_capture(path, state.capture_size)
            if state.images is not None:
                state.images[(section, name)] = path
            progress_value = state.capture_start + int(
                round(state.capture_span * display_index / max(1, total))
            )
            self._set_report_progress(
                min(progress_value, REPORT_PROGRESS_CAPTURE_DONE),
                REPORT_PROGRESS_TOTAL,
                f"截图 {display_index}/{total} · {name}",
                eta_phase="report-capture",
                eta_completed=display_index,
                eta_total=total,
                timing_stage="capture",
                timing_completed=display_index,
                timing_total=total,
            )
            state.index = display_index
            QTimer.singleShot(0, self._capture_next_report_image)
        except Exception as exc:
            self._fail_report_capture(state, exc)

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
        src = self._current_report_template_source()
        if _same_report_path(target, src):
            QMessageBox.warning(
                self,
                "报告位置不可用",
                "项目报告文件不能与报告模板源文件相同，请重新选择报告位置。",
            )
            return False
        if target.exists():
            return True

        if src is None or not src.is_file():
            QMessageBox.critical(
                self,
                "缺少报告模板",
                "已加载的报告模板不存在，请重新加载模板源。\n\n"
                f"模板:\n{src}",
            )
            return False

        try:
            self._initialize_report_timing(
                existing_report=False,
                report_path=target,
            )
            self._begin_report_progress(
                REPORT_PROGRESS_TOTAL,
                "复制模板...",
                timing_stage="copy-template",
            )
            self._set_report_progress_busy(
                "复制模板...",
                timing_stage="copy-template",
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

    def _start_report_prepare_task(self) -> None:
        if self.result is None:
            raise RuntimeError("报告任务启动前提取结果已失效")
        self._report_request_id += 1
        request_id = self._report_request_id
        task = _ReportPrepareTask(
            request_id,
            self.bundle,
            self.profile,
            self.cfg,
            self.result,
            temperature_code=self._current_temperature_code(),
            temperature_labels=self._temperature_display_labels(),
            phase_code=self._current_report_phase_code(),
            slope_ranges=self._slope_ranges,
            manual_state=self._snapshot_report_manual_state(),
            active_metric=self.result_table._active_metric,
            active_slope_param=self._active_slope_param,
            display_state=self.wave_plot.snapshot_report_display_state(),
            report_conditions=self._current_report_conditions(),
        )
        result_snapshot = task.current_result
        if self._report_output_path is not None:
            self._initialize_report_timing(
                existing_report=True,
                report_path=self._report_output_path,
            )
        if not self._report_progress_active:
            self._begin_report_progress(
                REPORT_PROGRESS_TOTAL,
                "准备报告文件...",
                timing_stage="prepare",
            )
        prepare_total = 1
        if (
            not result_snapshot.short_circuit_mode
            and not result_snapshot.single_pulse_mode
            and int(result_snapshot.detected_pulse_count or 0) > 2
        ):
            prepare_total = len(
                dpt_export_pulse_pairs(
                    int(result_snapshot.detected_pulse_count),
                    include_pair=(
                        int(result_snapshot.off_pulse_index),
                        int(result_snapshot.on_pulse_index),
                    ),
                )
            )
        self._set_report_progress(
            REPORT_PROGRESS_TEMPLATE_DONE,
            REPORT_PROGRESS_TOTAL,
            "报告文件已就绪，准备分析数据...",
            eta_phase="report-prepare",
            eta_completed=0,
            eta_total=prepare_total,
            timing_stage="prepare",
            timing_completed=0,
            timing_total=prepare_total,
        )
        task.signals.progress.connect(self._on_report_prepare_progress)
        task.signals.finished.connect(self._on_report_prepare_finished)
        task.signals.failed.connect(self._on_report_prepare_failed)
        self._report_prepare_tasks[request_id] = task
        try:
            self._load_pool.start(task)
        except Exception:
            self._report_prepare_tasks.pop(request_id, None)
            raise

    def _on_report_prepare_progress(
        self,
        request_id: int,
        done: int,
        total: int,
        label: str,
    ) -> None:
        if request_id != self._report_request_id:
            return
        total = max(1, int(total))
        ratio = max(0.0, min(float(done) / total, 1.0))
        span = REPORT_PROGRESS_PREPARE_DONE - REPORT_PROGRESS_TEMPLATE_DONE
        value = REPORT_PROGRESS_TEMPLATE_DONE + int(round(span * ratio))
        self._set_report_progress(
            min(value, REPORT_PROGRESS_PREPARE_DONE),
            REPORT_PROGRESS_TOTAL,
            label,
            eta_phase="report-prepare",
            eta_completed=max(0, int(done)),
            eta_total=total,
            timing_stage="prepare",
            timing_completed=max(0, int(done)),
            timing_total=total,
        )

    def _on_report_prepare_finished(
        self,
        request_id: int,
        results: list[ExtractResult],
    ) -> None:
        task = self._report_prepare_tasks.pop(request_id, None)
        if request_id != self._report_request_id:
            return
        if task is None:
            # A normal GUI report request is only valid together with the
            # frozen page snapshot created at submission time.  Falling back
            # to the current live controls here could silently write a later
            # temperature/phase selection into an earlier report request.
            self._on_report_prepare_failed(
                request_id,
                "报告页面快照已失效，请重新点击“写入报告”后重试。",
            )
            return
        self._set_report_progress(
            REPORT_PROGRESS_PREPARE_DONE,
            REPORT_PROGRESS_TOTAL,
            "报告数据准备完成，准备截图...",
            timing_stage="capture",
        )
        tempdir: tempfile.TemporaryDirectory | None = None
        try:
            tempdir = tempfile.TemporaryDirectory()
            self._start_report_capture_sequence(
                tempdir,
                results,
                request_id=request_id,
                temperature_code=(
                    task.temperature_code if task is not None else None
                ),
                temperature_labels=(
                    task.temperature_labels if task is not None else None
                ),
                phase_code=(task.phase_code if task is not None else None),
                report_conditions=(
                    task.report_conditions if task is not None else None
                ),
                image_result_index=(
                    _report_image_result_index(results, task.current_result)
                    if task is not None
                    else None
                ),
                capture_bundle=(task.bundle if task is not None else None),
                capture_profile=(task.profile if task is not None else None),
                capture_cfg=(task.cfg if task is not None else None),
                capture_result=(task.current_result if task is not None else None),
                capture_slope_ranges=(
                    task.slope_ranges if task is not None else None
                ),
                capture_manual_state=(
                    task.manual_state if task is not None else None
                ),
                capture_active_metric=(
                    task.active_metric if task is not None else None
                ),
                capture_active_slope_param=(
                    task.active_slope_param if task is not None else None
                ),
                capture_display_state=(
                    task.display_state if task is not None else None
                ),
                capture_active_state_frozen=task is not None,
            )
            tempdir = None
        except Exception as exc:
            _safe_cleanup_tempdir(tempdir)
            self._finish_report_progress("写入失败", ok=False)
            self._release_report_operation()
            QMessageBox.critical(self, "写入报告失败", str(exc))

    def _on_report_prepare_failed(self, request_id: int, message: str) -> None:
        self._report_prepare_tasks.pop(request_id, None)
        if request_id != self._report_request_id:
            return
        self._finish_report_progress("写入失败", ok=False)
        self._release_report_operation()
        QMessageBox.critical(self, "写入报告失败", message)

    def _write_report_template(self) -> None:
        if not self._try_begin_report_operation():
            return
        if self.result is None:
            self._release_report_operation()
            QMessageBox.warning(self, "提示", "无提取结果可写入报告")
            return
        try:
            if not self._ensure_report_output_file():
                self._release_report_operation()
                return
            self._start_report_prepare_task()
        except PermissionError as e:
            self._finish_report_progress("写入失败", ok=False)
            self._release_report_operation()
            QMessageBox.critical(
                self,
                "写入报告失败",
                "无法保存报告文件，通常是这个 .xlsx 正在被 Excel 打开或没有写入权限。\n"
                "请先关闭该报告文件，再点击“写入报告”。\n\n"
                f"文件:\n{self._report_output_path}\n\n"
                f"错误:\n{e}",
            )
        except Exception as e:
            self._finish_report_progress("写入失败", ok=False)
            self._release_report_operation()
            QMessageBox.critical(self, "写入报告失败", str(e))

    def _start_report_write_task(
        self,
        tempdir: tempfile.TemporaryDirectory,
        images: dict[tuple[str, str], Path],
        results: list[ExtractResult],
        *,
        request_id: int | None = None,
        temperature_code: str | None = None,
        temperature_labels: dict[str, str] | None = None,
        phase_code: str | None = None,
        report_conditions: ReportConditions | None = None,
        image_result_index: int | None = None,
    ) -> None:
        if not results or self._report_output_path is None:
            _safe_cleanup_tempdir(tempdir)
            self._finish_report_progress("写入失败", ok=False)
            self._release_report_operation()
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
            (
                temperature_labels
                if temperature_labels is not None
                else self._temperature_display_labels()
            ),
            (
                temperature_code
                if temperature_code in TEMP_CONDITION_DEFAULTS
                else self._current_temperature_code()
            ),
            (
                str(phase_code).strip().upper()
                if phase_code is not None
                else self._current_report_phase_code()
            ),
            (
                int(image_result_index)
                if image_result_index is not None
                else _report_image_result_index(results, self.result or results[0])
            ),
            (
                report_conditions
                if report_conditions is not None
                else ShortReportConditions()
                if results[0].short_circuit_mode
                else DptReportConditions()
            ),
        )
        task.signals.progress.connect(self._on_report_write_progress)
        task.signals.finished.connect(self._on_report_write_finished)
        task.signals.failed.connect(self._on_report_write_failed)
        self._report_tasks[request_id] = task
        self._set_report_busy(True)
        self._set_report_progress_busy(
            "正在打开并写入 Excel...",
            timing_stage="open-workbook",
        )
        try:
            self._load_pool.start(task)
        except Exception:
            self._report_tasks.pop(request_id, None)
            _safe_cleanup_tempdir(tempdir)
            raise

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
        if label == "保存报告文件":
            self._set_report_progress_busy(
                label,
                value=REPORT_PROGRESS_WRITE_DONE_CAP,
                total=REPORT_PROGRESS_TOTAL,
                timing_stage="save-workbook",
            )
            return
        if label == "整理报告版式":
            self._set_report_progress(
                REPORT_PROGRESS_WRITE_IMAGES_DONE,
                REPORT_PROGRESS_TOTAL,
                label,
                timing_stage="finalize-workbook",
            )
            return
        if label == "插入报告图片":
            ratio = max(0.0, min(float(value) / total, 1.0))
            span = REPORT_PROGRESS_WRITE_IMAGES_DONE - REPORT_PROGRESS_WRITE_DATA_DONE
            progress_value = REPORT_PROGRESS_WRITE_DATA_DONE + int(round(span * ratio))
            self._set_report_progress(
                min(progress_value, REPORT_PROGRESS_WRITE_IMAGES_DONE),
                REPORT_PROGRESS_TOTAL,
                label,
                eta_phase="report-write-images",
                eta_completed=max(0, int(value)),
                eta_total=total,
                timing_stage="write-images",
                timing_completed=max(0, int(value)),
                timing_total=total,
            )
            return
        checkpoint_values = {
            "打开报告文件": REPORT_PROGRESS_WRITE_START,
            "读取报告模板": REPORT_PROGRESS_WRITE_TEMPLATE_DONE,
            "写入报告数据": REPORT_PROGRESS_WRITE_DATA_DONE,
        }
        progress_value = checkpoint_values.get(label, self.report_progress.value())
        self._set_report_progress(
            min(progress_value, REPORT_PROGRESS_WRITE_DATA_DONE),
            REPORT_PROGRESS_TOTAL,
            label,
            timing_stage=(
                "open-workbook"
                if label == "打开报告文件"
                else "write-data"
                if label == "读取报告模板"
                else "write-images"
                if label == "写入报告数据"
                else None
            ),
        )

    def _on_report_write_finished(
        self,
        request_id: int,
        summary: ReportWriteSummary,
        elapsed_ms: float,
    ) -> None:
        task = self._report_tasks.pop(request_id, None)
        if request_id != self._report_request_id or task is None:
            return
        self._finish_report_progress("写入完成 100%", ok=True)
        self._release_report_operation()
        # Publish the durable, concise terminal state before settings I/O and
        # before the modal success dialog disables the parent window.  Updating
        # the QLabel synchronously avoids leaving the last painted
        # ``正在处理报告...`` frame visible behind that dialog.
        terminal_status = f"报告写入完成: {summary.report_path.name}"
        self.statusBar().showMessage(terminal_status)
        self.lbl_top_status.repaint()
        if self._report_output_path is not None:
            set_report_output_path(self._report_output_path)
            set_last_export_path(self._report_output_path)
        self._update_report_output_tooltip()
        terminal_detail = (
            f"已写入报告: {summary.report_path.name} | "
            f"{summary.data_sheet} 第 {summary.data_row}"
            f"{'' if summary.data_rows_written == 1 else f'-{summary.data_row_end}'} 行 | "
            f"图片 {summary.images_written} 张 | 保存 {elapsed_ms:.0f} ms"
        )
        self.lbl_top_status.setToolTip(terminal_detail)
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
        task = self._report_tasks.pop(request_id, None)
        if request_id != self._report_request_id or task is None:
            return
        self._finish_report_progress("写入失败", ok=False)
        self._release_report_operation()
        report_name = (
            self._report_output_path.name
            if self._report_output_path is not None
            else "当前报告"
        )
        terminal_status = f"报告写入失败: {report_name}"
        self.statusBar().showMessage(terminal_status)
        self.lbl_top_status.setToolTip(f"{terminal_status}\n{message}")
        self.lbl_top_status.repaint()
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
