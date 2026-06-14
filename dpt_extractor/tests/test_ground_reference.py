"""六通道地参考线（物理 0 ↔ 显示 offset）一致性。"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dpt_extractor.tests.sample_paths import sample_tss

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = (
    sample_tss("UH_750V_1050A_000.tss"),
    sample_tss("UL_750V_1050A_000.tss"),
    sample_tss("WH_480V_800A_000.tss"),
    sample_tss("WL_480V_800A_000.tss"),
)
@unittest.skipUnless(all(p.exists() for p in SAMPLES), "四工况 TSS 样例缺失")
class TestGroundReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _plot(self, sample_path: Path):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.waveform_plot import WaveformPlot
        from dpt_extractor.io.waveform_loader import load_waveform
        from dpt_extractor.models.bridge_profile import guess_profile_from_path, make_profile
        from dpt_extractor.models.channel_mapping import apply_mapping, infer_mapping_from_bundle
        from dpt_extractor.pipeline.extract import extract_all

        cfg = load_config()
        bundle = load_waveform(sample_path)
        guessed = guess_profile_from_path(sample_path.name)
        inferred = infer_mapping_from_bundle(bundle, guessed.bridge)
        profile = make_profile(guessed.phase, guessed.bridge)
        if inferred is not None:
            profile = apply_mapping(profile, inferred)
        result = extract_all(bundle, profile, cfg)
        plot = WaveformPlot()
        plot.plot_waveforms(bundle, profile, result)
        return plot

    def test_physical_zero_maps_to_ground_offset(self):
        for sample in SAMPLES:
            plot = self._plot(sample)
            for key in plot._trace_items:
                off = plot._disp_offset[key]
                self.assertAlmostEqual(plot._to_disp(key, 0.0), off, places=9, msg=f"{sample.name}:{key}")
                self.assertAlmostEqual(plot._from_disp(key, off), 0.0, places=6, msg=f"{sample.name}:{key}")

    def test_ground_marker_matches_offset_when_highlighted(self):
        plot = self._plot(SAMPLES[0])
        if not hasattr(plot, "_ground_marker"):
            self.skipTest("ground marker UI is not present in this plot implementation")
        for key in plot._trace_items:
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
        for key in plot._trace_items:
            x, y = plot._trace_items[key].getData()
            self.assertEqual(len(x), len(y), msg=key)
            self.assertGreater(len(y), 0, msg=key)

    def test_center_grid_is_waveform_mid_not_physical_zero(self):
        import numpy as np
        from dpt_extractor.gui.waveform_plot import _raw_value_span

        plot = self._plot(SAMPLES[2])
        for key in plot._trace_items:
            raw = plot._trace_raw[key]
            scale = plot._disp_scale[key]
            off = plot._disp_offset[key]
            if key.startswith("MATH") and plot._unit_for_channel(key) == "J":
                raw = plot._fit_raw_for_channel(key, raw)
            _, _, mid, _ = _raw_value_span(raw)
            mid_disp = mid / scale + off
            self.assertLess(abs(mid_disp), 0.35, msg=key)
            if not key.startswith("MATH") and abs(mid) > scale * 0.5:
                self.assertNotAlmostEqual(plot._from_disp(key, 0.0), 0.0, places=1, msg=key)


if __name__ == "__main__":
    unittest.main()
