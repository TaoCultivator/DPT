"""Irr/Trr 卡尺算法测试。"""

from __future__ import annotations



import unittest

import numpy as np



from dpt_extractor.config.loader import load_config

from dpt_extractor.io.waveform_loader import load_waveform

from dpt_extractor.metrics.irr_measure import (
    irr_parameter_peak_index,
    irr_parameter_peak_value,
    measure_irr_trr,
    trr_crossings_at_ha,
)

from dpt_extractor.models.bridge_profile import guess_profile_from_path

from dpt_extractor.models.waveform import bundle_reverse_recovery_current

from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.tests.sample_paths import sample_tss





class TestIrrMeasure(unittest.TestCase):

    def test_positive_lobe_crossings(self):

        n = 400

        t = np.linspace(0, 1e-6, n)

        irr = np.zeros(n)

        irr[:80] = 25.0

        irr[80:140] = np.linspace(25.0, 165.0, 60)

        irr[140:220] = np.linspace(165.0, 25.0, 80)

        irr[220:] = 25.0

        m = measure_irr_trr(t, irr, 0, n - 1)

        self.assertIsNotNone(m)

        assert m is not None

        self.assertAlmostEqual(m.ha, 25.0, delta=3.0)

        self.assertAlmostEqual(m.hb, 165.0, delta=3.0)

        self.assertAlmostEqual(m.irr, 165.0, delta=3.0)

        self.assertGreater(m.trr_ns, 50.0)

        self.assertLess(m.ta_s, m.tb_s)


    def test_negative_lobe_uses_absolute_main_peak(self):

        n = 500

        t = np.linspace(0, 1.2e-6, n)

        irr = np.full(n, 20.0)

        irr[90:150] = np.linspace(20.0, -900.0, 60)

        irr[150:230] = np.linspace(-900.0, 20.0, 80)

        irr[280:320] = np.linspace(20.0, 120.0, 40)

        irr[320:360] = np.linspace(120.0, 20.0, 40)

        m = measure_irr_trr(t, irr, 0, n - 1, ha=20.0)

        self.assertIsNotNone(m)

        assert m is not None

        self.assertAlmostEqual(m.hb, -900.0, delta=5.0)

        self.assertAlmostEqual(m.irr, 900.0, delta=5.0)

        self.assertLess(m.ta_s, m.tb_s)

        self.assertLess(m.peak_idx, 230)


    def test_parameter_peak_matches_extraction_main_lobe_rule(self):

        n = 400

        irr = np.zeros(n)

        irr[100:130] = np.linspace(0.0, -260.0, 30)

        irr[130:170] = np.linspace(-260.0, 0.0, 40)

        irr[210:240] = np.linspace(0.0, 145.0, 30)

        irr[240:280] = np.linspace(145.0, 0.0, 40)

        idx = irr_parameter_peak_index(irr, 90, 180, 90, 80, n - 1)

        self.assertGreater(idx, 200)

        self.assertAlmostEqual(float(irr[idx]), 145.0, delta=5.0)

        self.assertAlmostEqual(
            irr_parameter_peak_value(irr, 90, 180, 90, 80, n - 1),
            145.0,
            delta=5.0,
        )



    def test_ha_drag_recomputes_crossings(self):

        n = 400

        t = np.linspace(0, 1e-6, n)

        irr = np.zeros(n)

        irr[:80] = 20.0

        irr[80:140] = np.linspace(20.0, 150.0, 60)

        irr[140:220] = np.linspace(150.0, 20.0, 80)

        irr[220:] = 20.0

        m0 = measure_irr_trr(t, irr, 0, n - 1)

        m1 = measure_irr_trr(t, irr, 0, n - 1, ha=25.0)

        self.assertIsNotNone(m0)

        self.assertIsNotNone(m1)

        assert m1 is not None

        self.assertAlmostEqual(m1.ha, 25.0, delta=1.0)

        self.assertGreater(m1.tb_s, m1.ta_s)



        cross = trr_crossings_at_ha(t, irr, 0, n - 1, 30.0, peak_idx=m1.peak_idx)

        self.assertIsNotNone(cross)

        assert cross is not None

        ta, tb, _ = cross

        self.assertLess(ta, tb)



    def test_uh_measured_tss(self):

        sample = sample_tss("UH_750V_1050A_000.tss")

        if not sample.is_file():

            self.skipTest("UH TSS 样本缺失")

        bundle = load_waveform(sample)

        profile = guess_profile_from_path(str(sample))

        result = extract_all(bundle, profile, load_config())

        irr = bundle_reverse_recovery_current(bundle, profile)

        i0, i1 = result.segments.reverse_recovery

        m = measure_irr_trr(bundle.t, irr, i0, i1)

        self.assertIsNotNone(m, "UH 反向恢复段应能识别尖峰与 A/B")

        assert m is not None

        self.assertGreater(abs(m.hb), 300.0)

        self.assertLess(abs(m.hb), 400.0)

        self.assertGreater(m.irr, 300.0)

        self.assertLess(m.irr, 400.0)

        self.assertGreater(m.trr_ns, 20.0)

        self.assertLess(m.trr_ns, 80.0)





if __name__ == "__main__":

    unittest.main()

