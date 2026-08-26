from __future__ import annotations

import sys
import unittest

import numpy as np

from dpt_extractor.gui.waveform_plot import (
    WaveformPlot,
    _saved_horizontal_window_us,
)
from dpt_extractor.models.bridge_profile import make_profile
from dpt_extractor.models.waveform import TekMetadata, WaveformBundle


class TestSavedHorizontalView(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_remote_tekscope_window_uses_scale_position_and_delay(self) -> None:
        window = _saved_horizontal_window_us(
            (-992.756, 1007.244),
            2e-6,
            50.0,
            7.244e-6,
        )

        self.assertAlmostEqual(window[0], -2.756, places=9)
        self.assertAlmostEqual(window[1], 17.244, places=9)

    def test_plot_treats_saved_tekscope_window_as_global_preview(self) -> None:
        n = 400
        t = np.linspace(-992.756e-6, 1007.244e-6, n)
        profile = make_profile("U", "upper")
        channels = {
            "CH1": np.sin(np.linspace(0.0, 8.0, n)),
            "CH2": np.linspace(0.0, 900.0, n),
            "CH3": np.linspace(-10.0, 70.0, n),
            "CH4": np.linspace(0.0, 60.0, n),
        }
        bundle = WaveformBundle(
            t=t,
            channels=channels,
            meta=TekMetadata(
                source_path="remote-scope-session.tss",
                horizontal_scale_per_div=2e-6,
                horizontal_position_percent=50.0,
                horizontal_delay=7.244e-6,
            ),
        )
        plot = WaveformPlot()
        try:
            plot.plot_waveforms(bundle, profile, None)
            self.app.processEvents()

            self.assertAlmostEqual(plot._full_x_range[0], -2.756, places=6)
            self.assertAlmostEqual(plot._full_x_range[1], 17.244, places=6)
            current = plot.current_x_range_us()
            self.assertIsNotNone(current)
            assert current is not None
            self.assertAlmostEqual(current[0], -2.756, places=6)
            self.assertAlmostEqual(current[1], 17.244, places=6)
            self.assertIsNone(plot.current_local_x_window_us())
            self.assertTrue(plot._overview_plot.isHidden())
        finally:
            plot.close()

    def test_invalid_or_out_of_record_metadata_falls_back_to_full_record(self) -> None:
        full = (-10.0, 10.0)

        self.assertEqual(_saved_horizontal_window_us(full, None, 50.0, 0.0), full)
        self.assertEqual(
            _saved_horizontal_window_us(full, 1e-6, 50.0, 100e-6),
            full,
        )


if __name__ == "__main__":
    unittest.main()
