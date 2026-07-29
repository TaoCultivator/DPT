"""Uploaded wanglihui batches keep cursor/search windows on the real event."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = (
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "20260729"
        / "UH_HT_Rgon3.33R_Rgoff8.92R"
        / "UH_486V_950A_Rgon3.33R_Rgoff8.92R_000.tss",
        False,
    ),
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "20260729"
        / "UL_HT_Rgon2.267R_Rgoff7.5R"
        / "UL_486V_950A_Rgon2.267R_Rgoff7.5R_000.tss",
        True,
    ),
)


@unittest.skipUnless(
    all(path.exists() for path, _source_inverted in SAMPLES),
    "wanglihui 20260729 HT target samples missing",
)
class TestWanglihuiUploadedCursorWindowAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_channel_inversion_and_loss_search_windows_cover_real_cursors(
        self,
    ) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        for path, source_inverted in SAMPLES:
            with self.subTest(path=str(path)):
                win = MainWindow()
                try:
                    win._load_file(str(path))
                    self.assertIsNotNone(win.bundle)
                    assert win.bundle is not None
                    self.assertEqual(
                        "CH3" in win.bundle.meta.source_channel_inversions,
                        source_inverted,
                    )
                    if not source_inverted:
                        win.wave_plot.set_channel_inversion_enabled("CH3", True)
                        self.app.processEvents()
                    self.assertTrue(
                        win.wave_plot.channel_inversion_enabled("CH3")
                    )

                    for section, metric in (
                        ("开通", "Eon"),
                        ("反向恢复", "Err"),
                    ):
                        with self.subTest(section=section, metric=metric):
                            win._on_value_clicked(section, metric)
                            plot = win.wave_plot
                            self.assertEqual(plot._interactive_mode, "energy_loss")
                            self.assertIsNotNone(plot._cursor_a)
                            self.assertIsNotNone(plot._cursor_b)
                            self.assertIsNotNone(plot._interactive_search_t0_us)
                            self.assertIsNotNone(plot._interactive_search_t1_us)
                            ta = float(plot._cursor_a.value())
                            tb = float(plot._cursor_b.value())
                            self.assertLessEqual(
                                float(plot._interactive_search_t0_us),
                                min(ta, tb),
                            )
                            self.assertGreaterEqual(
                                float(plot._interactive_search_t1_us),
                                max(ta, tb),
                            )
                finally:
                    win.close()


if __name__ == "__main__":
    unittest.main()
