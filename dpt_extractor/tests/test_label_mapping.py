import unittest

from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.channel_mapping import infer_mapping_from_bundle
from dpt_extractor.tests.sample_paths import sample_tss

WH = sample_tss("WH_480V_800A_000.tss")
VH = sample_tss("VH_750V_1050A_000.tss")
WL = sample_tss("WL_480V_800A_000.tss")
UL = sample_tss("UL_750V_1050A_000.tss")
VH_MOS = sample_tss("VH_750V_805A_000.tss")
VL_MOS = sample_tss("VL_750V_805A_000.tss")


class TestLabelMapping(unittest.TestCase):
    @unittest.skipUnless(WH.exists(), "WH sample missing")
    def test_infer_wh_upper(self):
        bundle = load_waveform(WH)
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
        bundle = load_waveform(VH)
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
        self.assertFalse(m.irr_from_ic_minus_il)

    @unittest.skipUnless(WL.exists(), "WL sample missing")
    def test_infer_wl_lower(self):
        bundle = load_waveform(WL)
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
        bundle = load_waveform(UL)
        m = infer_mapping_from_bundle(bundle, "lower")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.ic, "CH3")
        self.assertEqual(m.il, "CH4")
        self.assertTrue(m.irr_from_ic_minus_il)
        self.assertFalse(m.ic_from_sum_irr_il)

    @unittest.skipUnless(VH_MOS.exists(), "VH MOS sample missing")
    def test_infer_vh_mos_upper(self):
        bundle = load_waveform(VH_MOS)
        m = infer_mapping_from_bundle(bundle, "upper")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.vge, "CH1")
        self.assertEqual(m.vce, "CH2")
        self.assertEqual(m.v_diode, "CH5")
        self.assertEqual(m.vge_other, "CH6")
        self.assertEqual(m.il, "CH4")
        self.assertEqual(m.irr, "CH3")
        self.assertTrue(m.ic_from_sum_irr_il)

    @unittest.skipUnless(VL_MOS.exists(), "VL MOS sample missing")
    def test_infer_vl_mos_lower(self):
        bundle = load_waveform(VL_MOS)
        m = infer_mapping_from_bundle(bundle, "lower")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.vge, "CH6")
        self.assertEqual(m.vce, "CH5")
        self.assertEqual(m.v_diode, "CH2")
        self.assertEqual(m.vge_other, "CH1")
        self.assertEqual(m.il, "CH4")
        self.assertEqual(m.ic, "CH3")
        self.assertTrue(m.irr_from_ic_minus_il)


if __name__ == "__main__":
    unittest.main()
