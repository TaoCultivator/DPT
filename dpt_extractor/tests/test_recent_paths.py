"""最近文件路径持久化。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication


class TestRecentPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        QSettings.setPath(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            self._td.name,
        )

    def tearDown(self):
        self._td.cleanup()

    def test_export_roundtrip_and_dialog_initial(self):
        from dpt_extractor.gui.recent_paths import (
            last_export_path,
            save_dialog_initial_path,
            set_last_export_path,
        )

        export_file = Path(self._td.name) / "reports" / "WH_test.xlsx"
        export_file.parent.mkdir(parents=True)
        export_file.write_bytes(b"")
        set_last_export_path(export_file)
        self.assertEqual(last_export_path(), export_file.resolve())
        initial = save_dialog_initial_path(Path(self._td.name) / "UH_new.xlsx")
        self.assertTrue(initial.replace("\\", "/").endswith("reports/UH_new.xlsx"))

    def test_open_roundtrip(self):
        from dpt_extractor.gui.recent_paths import (
            last_open_path,
            open_dialog_start_dir,
            set_last_open_path,
        )

        tss = Path(self._td.name) / "data" / "wave.tss"
        tss.parent.mkdir(parents=True)
        tss.write_text("x", encoding="utf-8")
        set_last_open_path(tss)
        self.assertEqual(last_open_path(), tss.resolve())
        self.assertEqual(open_dialog_start_dir("/fallback"), str(tss.parent.resolve()))

    def test_report_template_source_roundtrip(self):
        from dpt_extractor.gui.recent_paths import (
            report_template_source_path,
            set_report_template_source_path,
        )

        template = Path(self._td.name) / "templates" / "project_template.xlsx"
        template.parent.mkdir(parents=True)
        template.write_bytes(b"")
        set_report_template_source_path(template)
        self.assertEqual(report_template_source_path(), template.resolve())

    def test_report_output_path_can_point_to_future_file(self):
        from dpt_extractor.gui.recent_paths import (
            report_output_path,
            set_report_output_path,
        )

        report = Path(self._td.name) / "reports" / "Project_A_Report.xlsx"
        report.parent.mkdir(parents=True)
        set_report_output_path(report)
        self.assertEqual(report_output_path(), report.resolve())


if __name__ == "__main__":
    unittest.main()
