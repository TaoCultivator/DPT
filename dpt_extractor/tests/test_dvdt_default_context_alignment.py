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
WANGLIHUI_HT_TARGETS = (
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "20260729"
        / "UH_HT_Rgon3.33R_Rgoff8.92R"
        / "UH_486V_950A_Rgon3.33R_Rgoff8.92R_000.tss",
        0.7317665573531311,
        27.274399507423403,
        27.793075847830197,
    ),
    (
        ROOT
        / "示例文件"
        / "wanglihui"
        / "20260729"
        / "UL_HT_Rgon2.267R_Rgoff7.5R"
        / "UL_486V_950A_Rgon2.267R_Rgoff7.5R_000.tss",
        0.8956070108671828,
        26.283775999728606,
        26.712367999726833,
    ),
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
            self.assertAlmostEqual(on_context.top_v, 748.909375, places=9)
            self.assertAlmostEqual(
                on_context.crossing.dvdt,
                2.1021456116889996,
                places=12,
            )
            self.assertAlmostEqual(
                on_context.crossing.dvdt,
                win.result.turn_on.dvdt,
                places=12,
            )
            self.assertAlmostEqual(
                float(on_context.crossing.t_pct_a_s) * 1e6,
                20.576111708438016,
                places=8,
            )
            self.assertAlmostEqual(
                float(on_context.crossing.t_pct_b_s) * 1e6,
                20.86111932002712,
                places=8,
            )
            win._on_value_clicked("开通", "dv/dt")
            self._events()
            self._assert_plot_matches_context(win, "开通", on_context)

            rr_context = win._rr_dvdt_context()
            self.assertIsNotNone(rr_context)
            assert rr_context is not None
            self.assertAlmostEqual(rr_context.base_v, 0.0, places=12)
            self.assertAlmostEqual(rr_context.top_v, 1025.0, places=9)
            self.assertAlmostEqual(
                rr_context.crossing.dvdt,
                24.852287891176825,
                places=12,
            )
            self.assertAlmostEqual(
                rr_context.crossing.dvdt,
                win.result.reverse_recovery.dvdt_max,
                places=12,
            )
            self.assertAlmostEqual(
                float(rr_context.crossing.t_pct_a_s) * 1e6,
                20.762784727299738,
                places=8,
            )
            self.assertAlmostEqual(
                float(rr_context.crossing.t_pct_b_s) * 1e6,
                20.795779677446405,
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


@unittest.skipUnless(
    all(path.exists() for path, *_values in WANGLIHUI_HT_TARGETS),
    "wanglihui 20260729 HT target samples missing",
)
class TestSlowTurnOnDvdtCompletion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_ht_slow_vce_fall_uses_real_90_to_10_crossings_before_turn_off(
        self,
    ) -> None:
        from dpt_extractor.gui.main_window import MainWindow

        for path, expected_dvdt, expected_a_us, expected_b_us in (
            WANGLIHUI_HT_TARGETS
        ):
            with self.subTest(path=str(path)):
                win = MainWindow()
                try:
                    win._load_file(str(path))
                    interval = win._parameter_interval_us("开通", "dv/dt")
                    self.assertIsNotNone(interval)
                    assert interval is not None
                    context = win._turn_on_dvdt_context(*interval)
                    self.assertIsNotNone(context)
                    assert context is not None
                    self.assertFalse(context.used_fallback)
                    self.assertAlmostEqual(
                        context.crossing.dvdt, expected_dvdt, places=12
                    )
                    self.assertAlmostEqual(
                        float(context.crossing.t_pct_a_s) * 1e6,
                        expected_a_us,
                        places=8,
                    )
                    self.assertAlmostEqual(
                        float(context.crossing.t_pct_b_s) * 1e6,
                        expected_b_us,
                        places=8,
                    )
                    self.assertAlmostEqual(
                        win.result.turn_on.dvdt,
                        context.crossing.dvdt,
                        places=12,
                    )

                    win._on_value_clicked("开通", "dv/dt")
                    self.assertIsNotNone(win.wave_plot._cursor_a)
                    self.assertIsNotNone(win.wave_plot._cursor_b)
                    self.assertAlmostEqual(
                        float(win.wave_plot._cursor_a.value()),
                        expected_a_us,
                        places=8,
                    )
                    self.assertAlmostEqual(
                        float(win.wave_plot._cursor_b.value()),
                        expected_b_us,
                        places=8,
                    )
                finally:
                    win.close()


if __name__ == "__main__":
    unittest.main()
