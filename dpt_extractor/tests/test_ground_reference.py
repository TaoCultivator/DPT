"""六通道地参考线（物理 0 ↔ 显示 offset）一致性。"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = tuple(ROOT / n for n in (
    "UH_750V_1050A_000_ALL.csv",
    "UL_750V_1050A_000_ALL.csv",
    "WH_480V_800A_000_ALL.csv",
    "WL_480V_800A_000_ALL.csv",
))
CHANNELS = ("vge", "vce", "ic", "irr", "v_diode", "vge_other")


@unittest.skipUnless(all(p.exists() for p in SAMPLES), "四工况样例 CSV 缺失")
class TestGroundReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _plot(self, csv_path: Path):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.io.tek_parser import TekParser
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.pipeline.extract import extract_all

        cfg = load_config()
        bundle = TekParser().parse(csv_path)
        profile = guess_profile_from_path(csv_path.name)
        result = extract_all(bundle, profile, cfg)
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, result)
        return plot

    def test_physical_zero_maps_to_ground_offset(self):
        for csv in SAMPLES:
            plot = self._plot(csv)
            for key in CHANNELS:
                off = plot._disp_offset[key]
                self.assertAlmostEqual(plot._to_disp(key, 0.0), off, places=9, msg=f"{csv.name}:{key}")
                self.assertAlmostEqual(plot._from_disp(key, off), 0.0, places=6, msg=f"{csv.name}:{key}")

    def test_ground_marker_matches_offset_when_highlighted(self):
        plot = self._plot(SAMPLES[0])
        for key in CHANNELS:
            plot._on_legend_clicked(key)
            self.assertTrue(plot._ground_marker.isVisible())
            self.assertEqual(plot._ground_marker_key, key)
            self.assertAlmostEqual(
                float(plot._ground_marker.value()),
                plot._disp_offset[key],
                places=9,
                msg=key,
            )
            plot._on_legend_clicked(key)

    def test_plot_y_equals_raw_over_scale_plus_offset(self):
        import numpy as np

        plot = self._plot(SAMPLES[1])
        for key in CHANNELS:
            raw = plot._trace_raw[key]
            scale = plot._disp_scale[key]
            off = plot._disp_offset[key]
            y = plot._trace_items[key].getData()[1]
            self.assertTrue(np.allclose(y, raw / scale + off), msg=key)

    def test_center_grid_is_waveform_mid_not_physical_zero(self):
        import numpy as np
        from dpt_extractor.gui.waveform_plot import _raw_value_span

        plot = self._plot(SAMPLES[2])
        for key in CHANNELS:
            raw = plot._trace_raw[key]
            scale = plot._disp_scale[key]
            off = plot._disp_offset[key]
            _, _, mid, _ = _raw_value_span(raw)
            mid_disp = mid / scale + off
            self.assertAlmostEqual(mid_disp, 0.0, places=2, msg=key)
            if abs(mid) > scale * 0.5:
                self.assertNotAlmostEqual(plot._from_disp(key, 0.0), 0.0, places=1, msg=key)


if __name__ == "__main__":
    unittest.main()
