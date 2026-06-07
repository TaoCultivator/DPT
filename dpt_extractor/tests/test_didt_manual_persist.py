"""关断 di/dt 手调 Ha/Hb 应在再次点击时保留。"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dpt_extractor.gui.main_window import MainWindow


class TestDidtManualPersist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_restore_off_didt_with_low_hb(self):
        win = MainWindow()
        key = ("关断过程", "di/dt")
        win._manual_didt[key] = (14.375, 15.633, 1051.25, 42.46, "generic")
        restored = win._restore_manual_didt(key, "generic")
        self.assertIsNotNone(restored)
        assert restored is not None
        _t0, _t1, top, base, zero = restored
        self.assertAlmostEqual(top, 1051.25, places=2)
        self.assertAlmostEqual(base, 42.46, places=2)
        self.assertIsNone(zero)


if __name__ == "__main__":
    unittest.main()
