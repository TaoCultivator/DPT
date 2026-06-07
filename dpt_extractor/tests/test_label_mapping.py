import unittest
from pathlib import Path

from dpt_extractor.io.tek_parser import TekParser
from dpt_extractor.models.channel_mapping import infer_mapping_from_bundle

ROOT = Path(__file__).resolve().parents[2]
WH = ROOT / "WH_480V_800A_000_ALL.csv"
VH = ROOT / "VH_482V_820A_000_ALL.csv"
WL = ROOT / "WL_480V_800A_000_ALL.csv"
UL = ROOT / "UL_750V_1050A_000_ALL.csv"
VH_MOS = ROOT / "VH_915V_930A_000_ALL.csv"
VL_MOS = ROOT / "VL_915V_930A_000_ALL.csv"


class TestLabelMapping(unittest.TestCase):
    @unittest.skipUnless(WH.exists(), "WH sample missing")
    def test_infer_wh_upper(self):
        bundle = TekParser().parse(WH)
        m = infer_mapping_from_bundle(bundle, "upper")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.vge, "CH1")
        self.assertEqual(m.vce, "CH2")
        self.assertEqual(m.irr, "CH3")
        self.assertEqual(m.il, "CH4")
        self.assertEqual(m.v_diode, "CH5")
        self.assertEqual(m.vge_other, "CH6")
        self.assertTrue(m.ic_from_sum_irr_il)

    @unittest.skipUnless(VH.exists(), "VH sample missing")
    def test_infer_vh_upper(self):
        bundle = TekParser().parse(VH)
        m = infer_mapping_from_bundle(bundle, "upper")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.vge, "CH4")
        self.assertEqual(m.vce, "CH5")
        self.assertEqual(m.irr, "CH3")
        self.assertEqual(m.il, "CH6")
        self.assertEqual(m.v_diode, "CH2")
        self.assertEqual(m.vge_other, "CH1")
        self.assertTrue(m.ic_from_sum_irr_il)
        self.assertFalse(m.irr_from_ic_minus_il)

    @unittest.skipUnless(WL.exists(), "WL sample missing")
    def test_infer_wl_lower(self):
        bundle = TekParser().parse(WL)
        m = infer_mapping_from_bundle(bundle, "lower")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.vge, "CH6")
        self.assertEqual(m.vce, "CH5")
        self.assertEqual(m.ic, "CH3")
        self.assertEqual(m.il, "CH4")
        self.assertEqual(m.v_diode, "CH2")
        self.assertEqual(m.vge_other, "CH1")
        self.assertTrue(m.irr_from_ic_minus_il)
        self.assertFalse(m.ic_from_sum_irr_il)

    @unittest.skipUnless(UL.exists(), "UL sample missing")
    def test_infer_ul_lower(self):
        bundle = TekParser().parse(UL)
        m = infer_mapping_from_bundle(bundle, "lower")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.ic, "CH3")
        self.assertEqual(m.il, "CH4")
        self.assertTrue(m.irr_from_ic_minus_il)
        self.assertFalse(m.ic_from_sum_irr_il)

    @unittest.skipUnless(VH_MOS.exists(), "VH MOS sample missing")
    def test_infer_vh_mos_upper(self):
        bundle = TekParser().parse(VH_MOS)
        m = infer_mapping_from_bundle(bundle, "upper")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.vge, "CH1")
        self.assertEqual(m.vce, "CH5")
        self.assertEqual(m.v_diode, "CH2")
        self.assertEqual(m.vge_other, "CH4")
        self.assertEqual(m.il, "CH3")
        self.assertEqual(m.irr, "CH6")
        self.assertTrue(m.ic_from_sum_irr_il)

    @unittest.skipUnless(VL_MOS.exists(), "VL MOS sample missing")
    def test_infer_vl_mos_lower(self):
        bundle = TekParser().parse(VL_MOS)
        m = infer_mapping_from_bundle(bundle, "lower")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.vge, "CH4")
        self.assertEqual(m.vce, "CH2")
        self.assertEqual(m.v_diode, "CH5")
        self.assertEqual(m.vge_other, "CH1")
        self.assertEqual(m.il, "CH3")
        self.assertEqual(m.ic, "CH6")
        self.assertTrue(m.irr_from_ic_minus_il)


if __name__ == "__main__":
    unittest.main()
