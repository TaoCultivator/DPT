"""Default turn-on/RR dv/dt cards must share one numeric and GUI context."""

from __future__ import annotations

import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
TARGET = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "HT"
    / "UH_750V_1048A_000.tss"
)


@unittest.skipUnless(TARGET.exists(), "songzhenxi 20260717 HT target sample missing")
class TestDvdtDefaultContextAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    @classmethod
    def _events(cls) -> None:
        for _ in range(3):
            cls.app.processEvents()

    def _assert_plot_matches_context(self, win, section: str, context) -> None:
        plot = win.wave_plot
        channel = "v_diode" if section == "反向恢复" else "vce"
        self.assertIsNotNone(plot._h_cursor_a)
        self.assertIsNotNone(plot._h_cursor_b)
        self.assertIsNotNone(plot._cursor_a)
        self.assertIsNotNone(plot._cursor_b)
        assert plot._h_cursor_a is not None and plot._h_cursor_b is not None
        assert plot._cursor_a is not None and plot._cursor_b is not None

        ha = plot._from_disp(channel, float(plot._h_cursor_a.value()))
        hb = plot._from_disp(channel, float(plot._h_cursor_b.value()))
        self.assertAlmostEqual(ha, float(context.top_v), places=9)
        self.assertAlmostEqual(hb, float(context.base_v), places=9)
        self.assertEqual(hb, 0.0)

        self.assertIsNotNone(context.crossing.t_pct_a_s)
        self.assertIsNotNone(context.crossing.t_pct_b_s)
        assert context.crossing.t_pct_a_s is not None
        assert context.crossing.t_pct_b_s is not None
        self.assertAlmostEqual(
            float(plot._cursor_a.value()),
            float(context.crossing.t_pct_a_s) * 1e6,
            places=8,
        )
        self.assertAlmostEqual(
            float(plot._cursor_b.value()),
            float(context.crossing.t_pct_b_s) * 1e6,
            places=8,
        )

        raw = np.asarray(win.bundle.get(getattr(win.profile, channel)), dtype=np.float64)
        if section == "反向恢复":
            raw = np.abs(raw)
        self.assertAlmostEqual(
            float(np.interp(context.crossing.t_pct_a_s, win.bundle.t, raw)),
            float(context.crossing.th_a),
            places=7,
        )
        self.assertAlmostEqual(
            float(np.interp(context.crossing.t_pct_b_s, win.bundle.t, raw)),
            float(context.crossing.th_b),
            places=7,
        )

    def test_target_default_dvdt_cards_match_pipeline_values_and_raw_crossings(self) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        win = MainWindow()
        try:
            win.resize(1600, 1000)
            win.show()
            self._events()
            win._load_file(str(TARGET))
            self._events()
            self.assertIsNotNone(win.result)
            assert win.result is not None
            result_before = deepcopy(win.result)

            on_interval = win._parameter_interval_us("开通", "dv/dt")
            self.assertIsNotNone(on_interval)
            assert on_interval is not None
            on_context = win._turn_on_dvdt_context(*on_interval)
            self.assertIsNotNone(on_context)
            assert on_context is not None
            self.assertAlmostEqual(on_context.base_v, 0.0, places=12)
            self.assertAlmostEqual(on_context.top_v, 751.75, places=9)
            self.assertAlmostEqual(
                on_context.crossing.dvdt,
                2.2326818108938484,
                places=12,
            )
            self.assertAlmostEqual(
                on_context.crossing.dvdt,
                win.result.turn_on.dvdt,
                places=12,
            )
            self.assertAlmostEqual(
                float(on_context.crossing.t_pct_a_s) * 1e6,
                19.010236108012553,
                places=8,
            )
            self.assertAlmostEqual(
                float(on_context.crossing.t_pct_b_s) * 1e6,
                19.279598270173594,
                places=8,
            )
            win._on_value_clicked("开通", "dv/dt")
            self._events()
            self._assert_plot_matches_context(win, "开通", on_context)

            rr_context = win._rr_dvdt_context()
            self.assertIsNotNone(rr_context)
            assert rr_context is not None
            self.assertAlmostEqual(rr_context.base_v, 0.0, places=12)
            self.assertAlmostEqual(rr_context.top_v, 1065.1875, places=9)
            self.assertAlmostEqual(
                rr_context.crossing.dvdt,
                27.364653240063777,
                places=12,
            )
            self.assertAlmostEqual(
                rr_context.crossing.dvdt,
                win.result.reverse_recovery.dvdt_max,
                places=12,
            )
            self.assertAlmostEqual(
                float(rr_context.crossing.t_pct_a_s) * 1e6,
                19.1949312896233,
                places=8,
            )
            self.assertAlmostEqual(
                float(rr_context.crossing.t_pct_b_s) * 1e6,
                19.22607182674337,
                places=8,
            )
            win._on_value_clicked("反向恢复", "dv/dt")
            self._events()
            self._assert_plot_matches_context(win, "反向恢复", rr_context)

            # Selecting a default card is display-only and cannot silently
            # rewrite the pipeline values it is supposed to explain.
            self.assertEqual(win.result, result_before)
        finally:
            win.close()
            self._events()

if __name__ == "__main__":
    unittest.main()
