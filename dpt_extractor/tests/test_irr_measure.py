"""Irr/Trr 卡尺算法测试。"""

from __future__ import annotations



import unittest

from pathlib import Path



import numpy as np



from dpt_extractor.config.loader import load_config

from dpt_extractor.io.tek_parser import TekParser

from dpt_extractor.metrics.irr_measure import measure_irr_trr, trr_crossings_at_ha

from dpt_extractor.models.bridge_profile import guess_profile_from_path

from dpt_extractor.models.waveform import bundle_reverse_recovery_current

from dpt_extractor.pipeline.extract import extract_all





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



    def test_uh_measured_csv(self):

        csv = Path(__file__).resolve().parents[2] / "UH_750V_1050A_000_ALL.csv"

        if not csv.is_file():

            self.skipTest("UH 实测 CSV 不在仓库根目录")

        bundle = TekParser().parse(str(csv))

        profile = guess_profile_from_path(str(csv))

        result = extract_all(bundle, profile, load_config())

        irr = bundle_reverse_recovery_current(bundle, profile)

        i0, i1 = result.segments.reverse_recovery

        m = measure_irr_trr(bundle.t, irr, i0, i1)

        self.assertIsNotNone(m, "UH 反向恢复段应能识别尖峰与 A/B")

        assert m is not None

        self.assertAlmostEqual(m.hb, 173.9, delta=2.0)

        self.assertAlmostEqual(m.irr, 173.9, delta=2.0)

        self.assertGreater(m.trr_ns, 20.0)

        self.assertLess(m.trr_ns, 80.0)





if __name__ == "__main__":

    unittest.main()

