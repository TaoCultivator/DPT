from __future__ import annotations

import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _RecordingTempdir:
    def __init__(self, *, fail_cleanup: bool = False) -> None:
        self.fail_cleanup = fail_cleanup
        self.cleanup_calls = 0

    def cleanup(self) -> None:
        self.cleanup_calls += 1
        if self.fail_cleanup:
            raise PermissionError("temporary PNG is still locked")


class TestReportTaskProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_report_write_task_emits_finished_only_after_save_returns(self):
        from PyQt6.QtCore import Qt

        from dpt_extractor.gui.main_window import _ReportWriteTask
        from dpt_extractor.models.results import ExtractResult

        save_entered = threading.Event()
        allow_save_return = threading.Event()
        progress: list[tuple[int, int, int, str]] = []
        finished: list[tuple[object, ...]] = []
        tempdir = _RecordingTempdir()

        def fake_write(*_args, progress_callback=None, **_kwargs):
            self.assertIsNotNone(progress_callback)
            progress_callback(5, 6, "保存报告文件")
            save_entered.set()
            self.assertTrue(allow_save_return.wait(2.0))
            return object()

        task = _ReportWriteTask(
            11,
            ExtractResult(),
            Path("report.xlsx"),
            {},
            tempdir,  # type: ignore[arg-type]
            None,
            {},
        )
        task.signals.progress.connect(
            lambda *args: progress.append(args),
            Qt.ConnectionType.DirectConnection,
        )
        task.signals.finished.connect(
            lambda *args: finished.append(args),
            Qt.ConnectionType.DirectConnection,
        )

        with patch(
            "dpt_extractor.gui.main_window.write_report_template",
            side_effect=fake_write,
        ):
            worker = threading.Thread(target=task.run)
            worker.start()
            self.assertTrue(save_entered.wait(2.0))
            self.assertEqual(progress, [(11, 5, 6, "保存报告文件")])
            self.assertEqual(finished, [])
            allow_save_return.set()
            worker.join(2.0)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(finished), 1)
        self.assertEqual(tempdir.cleanup_calls, 1)

    def test_report_write_task_passes_frozen_page_conditions(self):
        from dpt_extractor.gui.main_window import _ReportWriteTask
        from dpt_extractor.models.results import ExtractResult

        received: dict[str, object] = {}
        tempdir = _RecordingTempdir()

        def fake_write(*_args, **kwargs):
            received.update(kwargs)
            return object()

        task = _ReportWriteTask(
            15,
            ExtractResult(),
            Path("report.xlsx"),
            {},
            tempdir,  # type: ignore[arg-type]
            None,
            {"RT": "25℃", "HT": "150℃", "LT": "-40℃"},
            "LT",
            "UL",
            0,
        )

        with patch(
            "dpt_extractor.gui.main_window.write_report_template",
            side_effect=fake_write,
        ):
            task.run()

        self.assertEqual(received["temperature_code"], "LT")
        self.assertEqual(received["phase_code"], "UL")
        self.assertEqual(received["image_result_index"], 0)

    def test_main_window_snapshots_selected_report_conditions_when_report_starts(self):
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import ExtractResult

        class _Pool:
            def __init__(self) -> None:
                self.tasks: list[object] = []

            def start(self, task: object) -> None:
                self.tasks.append(task)

        win = MainWindow()
        original_pool = win._load_pool
        pool = _Pool()
        try:
            win._load_pool = pool  # type: ignore[assignment]
            win.result = ExtractResult(
                source_path=str(
                    Path("colleague") / "U_L" / "UH_750V_1048A_000.tss"
                ),
                profile_code="UH",
            )
            win._set_profile_combos(make_profile("U", "lower"))
            win._set_temperature_code("LT")
            win._start_report_prepare_task()

            self.assertEqual(len(pool.tasks), 1)
            self.assertEqual(pool.tasks[0].phase_code, "UL")
            self.assertEqual(pool.tasks[0].temperature_code, "LT")
            self.assertEqual(pool.tasks[0].temperature_labels["LT"], "-40℃")
            win._set_profile_combos(make_profile("U", "upper"))
            win._set_temperature_code("RT")
            self.assertEqual(pool.tasks[0].phase_code, "UL")
            self.assertEqual(pool.tasks[0].temperature_code, "LT")
        finally:
            win._report_prepare_tasks.clear()
            win._release_report_operation()
            win._load_pool = original_pool
            win.close()

    def test_cleanup_failure_cannot_suppress_success_terminal_signal(self):
        from dpt_extractor.gui.main_window import _ReportWriteTask
        from dpt_extractor.models.results import ExtractResult

        finished: list[tuple[object, ...]] = []
        failed: list[tuple[object, ...]] = []
        tempdir = _RecordingTempdir(fail_cleanup=True)
        task = _ReportWriteTask(
            12,
            ExtractResult(),
            Path("report.xlsx"),
            {},
            tempdir,  # type: ignore[arg-type]
            None,
            {},
        )
        task.signals.finished.connect(lambda *args: finished.append(args))
        task.signals.failed.connect(lambda *args: failed.append(args))

        with patch(
            "dpt_extractor.gui.main_window.write_report_template",
            return_value=object(),
        ):
            task.run()

        self.assertEqual(tempdir.cleanup_calls, 1)
        self.assertEqual(len(finished), 1)
        self.assertEqual(failed, [])

    def test_cleanup_failure_cannot_replace_original_write_failure(self):
        from dpt_extractor.gui.main_window import _ReportWriteTask
        from dpt_extractor.models.results import ExtractResult

        finished: list[tuple[object, ...]] = []
        failed: list[tuple[object, ...]] = []
        tempdir = _RecordingTempdir(fail_cleanup=True)
        task = _ReportWriteTask(
            14,
            ExtractResult(),
            Path("report.xlsx"),
            {},
            tempdir,  # type: ignore[arg-type]
            None,
            {},
        )
        task.signals.finished.connect(lambda *args: finished.append(args))
        task.signals.failed.connect(lambda *args: failed.append(args))

        with patch(
            "dpt_extractor.gui.main_window.write_report_template",
            side_effect=ValueError("write boom"),
        ):
            task.run()

        self.assertEqual(tempdir.cleanup_calls, 1)
        self.assertEqual(finished, [])
        self.assertEqual(failed, [(14, "write boom")])

    def test_prepare_task_snapshots_result_config_and_channel_inversion(self):
        from dpt_extractor.config.loader import AppConfig
        from dpt_extractor.gui.main_window import _ReportPrepareTask
        from dpt_extractor.models.bridge_profile import make_profile
        from dpt_extractor.models.results import ExtractResult
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        cfg = AppConfig()
        result = ExtractResult(detected_pulse_count=2)
        channel = np.linspace(0.0, 1.0, 8)
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 8),
            channels={"CH3": channel},
            meta=TekMetadata(),
        )
        task = _ReportPrepareTask(
            13,
            bundle,
            make_profile("U", "upper"),
            cfg,
            result,
        )

        bundle.meta.channel_display_inversions.add("CH3")
        result.detected_pulse_count = 9
        cfg.pulse_selection.off_pulse = 7

        self.assertIsNotNone(task.bundle)
        assert task.bundle is not None
        self.assertNotIn("CH3", task.bundle.meta.channel_display_inversions)
        self.assertEqual(task.current_result.detected_pulse_count, 2)
        self.assertNotEqual(task.cfg.pulse_selection.off_pulse, 7)
        self.assertTrue(np.shares_memory(task.bundle.channels["CH3"], channel))
        self.assertFalse(task.bundle.channels["CH3"].flags.writeable)
        self.assertFalse(task.bundle.t.flags.writeable)

    def test_report_guard_blocks_double_submit_and_user_interaction(self):
        from PyQt6.QtCore import Qt

        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.models.results import ExtractResult

        class _RecordingPool:
            def __init__(self) -> None:
                self.tasks: list[object] = []

            def start(self, task) -> None:
                self.tasks.append(task)

        win = MainWindow()
        win.result = ExtractResult()
        pool = _RecordingPool()
        win._load_pool = pool  # type: ignore[assignment]
        win._ensure_report_output_file = lambda: True  # type: ignore[method-assign]
        win.spin_on_pulse.setEnabled(False)

        win._write_report_template()
        win._write_report_template()

        mouse_attribute = Qt.WidgetAttribute.WA_TransparentForMouseEvents
        self.assertEqual(len(pool.tasks), 1)
        first_request_id = win._report_request_id
        self.assertTrue(win._report_operation_active)
        self.assertFalse(win.btn_write_report.isEnabled())
        self.assertFalse(win.combo_phase.isEnabled())
        self.assertFalse(win.result_table.isEnabled())
        self.assertTrue(win.wave_plot.testAttribute(mouse_attribute))
        self.assertTrue(win.splitter.testAttribute(mouse_attribute))

        with patch("dpt_extractor.gui.main_window.QMessageBox.critical"):
            win._on_report_prepare_failed(first_request_id, "boom")
        self.assertFalse(win._report_operation_active)
        self.assertTrue(win.btn_write_report.isEnabled())
        self.assertTrue(win.combo_phase.isEnabled())
        self.assertFalse(win.spin_on_pulse.isEnabled())
        self.assertTrue(win.result_table.isEnabled())
        self.assertFalse(win.wave_plot.testAttribute(mouse_attribute))

        win._write_report_template()
        self.assertEqual(len(pool.tasks), 2)
        second_request_id = win._report_request_id
        with patch("dpt_extractor.gui.main_window.QMessageBox.critical"):
            win._on_report_prepare_failed(second_request_id, "boom again")
        self.assertFalse(win._report_operation_active)

        win._ensure_report_output_file = lambda: False  # type: ignore[method-assign]
        win._write_report_template()
        self.assertFalse(win._report_operation_active)
        self.assertTrue(win.btn_write_report.isEnabled())
        win.close()

    def test_duplicate_write_terminal_signal_is_ignored(self):
        from dpt_extractor.export.report_template import ReportWriteSummary
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        win._report_request_id = 21
        win._report_tasks[21] = object()  # type: ignore[assignment]
        win._begin_report_progress(100000, "保存中")
        summary = ReportWriteSummary(
            report_path=Path("report.xlsx"),
            data_sheet="V相_双脉冲数据",
            data_row=13,
        )
        with patch("dpt_extractor.gui.main_window.QMessageBox.information"):
            win._on_report_write_finished(21, summary, 1.0)
        with patch("dpt_extractor.gui.main_window.QMessageBox.critical") as critical:
            win._on_report_write_failed(21, "late failure")
        critical.assert_not_called()
        self.assertEqual(win.report_progress.percent_text(), "100.0%")
        self.assertEqual(win.report_progress.eta_text(), "0 ms")

        win._report_request_id = 22
        win._report_tasks[22] = object()  # type: ignore[assignment]
        win._begin_report_progress(100000, "保存中")
        with patch("dpt_extractor.gui.main_window.QMessageBox.critical"):
            win._on_report_write_failed(22, "write failed")
        with patch("dpt_extractor.gui.main_window.QMessageBox.information") as info:
            win._on_report_write_finished(22, summary, 1.0)
        info.assert_not_called()
        self.assertEqual(win.report_progress.detail_text(), "失败")
        self.assertEqual(win.report_progress.eta_text(), "—")
        win.close()


if __name__ == "__main__":
    unittest.main()
