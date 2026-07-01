import unittest

from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.channel_mapping import (
    infer_best_mapping_from_bundle,
    infer_mapping_from_bundle,
    infer_mapping_from_waveform_trends,
)
from dpt_extractor.tests.sample_paths import sample_tss

WH = sample_tss("WH_480V_800A_000.tss")
VH = sample_tss("VH_750V_1050A_000.tss")
WL = sample_tss("WL_480V_800A_000.tss")
UL = sample_tss("UL_750V_1050A_000.tss")
UL_2577 = sample_tss("UL_750V_1048A_000.tss")
VH_MOS = sample_tss("VH_750V_805A_000.tss")
VL_MOS = sample_tss("VL_750V_805A_000.tss")


class TestLabelMapping(unittest.TestCase):
    def _synthetic_upper_bundle(self):
        import numpy as np

        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 1200
        t = np.linspace(0.0, 1e-6, n)
        gate = (((t > 0.18e-6) & (t < 0.48e-6)) | (t > 0.72e-6)).astype(float)
        vge = -5.0 + 20.0 * gate
        vce = 620.0 * (1.0 - gate)
        v_diode = 610.0 * gate
        il = 80.0 + 520.0 * t / t[-1]
        branch = 35.0 + 470.0 * gate
        branch += 120.0 * np.exp(-((t - 0.50e-6) / 0.018e-6) ** 2)
        return WaveformBundle(
            t=t,
            channels={
                "CH1": vge,
                "CH2": vce,
                "CH3": branch,
                "CH4": il,
                "CH5": v_diode,
                "CH6": -7.0 + 0.2 * np.sin(np.linspace(0.0, 8.0, n)),
            },
            meta=TekMetadata(
                channel_labels={
                    "CH1": "L-Vge",
                    "CH2": "L-Vce",
                    "CH3": "IL",
                    "CH4": "Ic",
                    "CH5": "H-Vce",
                    "CH6": "H-Vge",
                }
            ),
        )

    def _synthetic_lower_bundle(self):
        import numpy as np

        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        n = 1200
        t = np.linspace(0.0, 1e-6, n)
        gate = (((t > 0.20e-6) & (t < 0.50e-6)) | (t > 0.74e-6)).astype(float)
        vge = -4.0 + 22.0 * gate
        vce = 720.0 * (1.0 - gate)
        v_diode = 700.0 * gate
        il = 100.0 + 620.0 * t / t[-1]
        ic = 40.0 + 540.0 * gate
        ic += 150.0 * np.exp(-((t - 0.76e-6) / 0.018e-6) ** 2)
        return WaveformBundle(
            t=t,
            channels={
                "CH1": -6.0 + 0.2 * np.sin(np.linspace(0.0, 8.0, n)),
                "CH2": v_diode,
                "CH3": ic,
                "CH4": il,
                "CH5": vce,
                "CH6": vge,
            },
            meta=TekMetadata(
                channel_labels={
                    "CH1": "L-Vge",
                    "CH2": "L-Vce",
                    "CH3": "IL",
                    "CH4": "Ic",
                    "CH5": "H-Vce",
                    "CH6": "H-Vge",
                }
            ),
        )

    def test_waveform_trend_mapping_ignores_bad_labels(self):
        bundle = self._synthetic_upper_bundle()
        label_mapping = infer_mapping_from_bundle(bundle, "upper")
        self.assertIsNotNone(label_mapping)
        assert label_mapping is not None
        self.assertEqual(label_mapping.vge, "CH6")
        self.assertEqual(label_mapping.il, "CH3")

        mapping, source = infer_best_mapping_from_bundle(bundle, "upper")
        self.assertEqual(source, "trend")
        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.vge, "CH1")
        self.assertEqual(mapping.vce, "CH2")
        self.assertEqual(mapping.irr, "CH3")
        self.assertEqual(mapping.il, "CH4")
        self.assertEqual(mapping.v_diode, "CH5")
        self.assertEqual(mapping.vge_other, "CH6")
        self.assertTrue(mapping.ic_from_sum_irr_il)

    def test_lower_waveform_trend_mapping_ignores_bad_labels(self):
        bundle = self._synthetic_lower_bundle()
        label_mapping = infer_mapping_from_bundle(bundle, "lower")
        self.assertIsNotNone(label_mapping)
        assert label_mapping is not None
        self.assertEqual(label_mapping.vge, "CH1")
        self.assertEqual(label_mapping.il, "CH3")

        mapping, source = infer_best_mapping_from_bundle(bundle, "lower")
        self.assertEqual(source, "trend")
        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.vge, "CH6")
        self.assertEqual(mapping.vce, "CH5")
        self.assertEqual(mapping.ic, "CH3")
        self.assertEqual(mapping.il, "CH4")
        self.assertEqual(mapping.v_diode, "CH2")
        self.assertEqual(mapping.vge_other, "CH1")
        self.assertTrue(mapping.irr_from_ic_minus_il)

    def test_best_mapping_falls_back_to_labels_when_trend_is_unclear(self):
        import numpy as np

        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 16),
            channels={f"CH{i}": np.zeros(16) for i in range(1, 7)},
            meta=TekMetadata(
                channel_labels={
                    "CH1": "H-Vge",
                    "CH2": "H-Vce",
                    "CH3": "Ic",
                    "CH4": "IL",
                    "CH5": "L-Vce",
                    "CH6": "L-Vge",
                }
            ),
        )
        self.assertIsNone(infer_mapping_from_waveform_trends(bundle, "upper"))
        mapping, source = infer_best_mapping_from_bundle(bundle, "upper")
        self.assertEqual(source, "label")
        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.vge, "CH1")
        self.assertEqual(mapping.vce, "CH2")

    def test_upper_label_ic_ul_is_upper_irr(self):
        import numpy as np

        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 16),
            channels={f"CH{i}": np.zeros(16) for i in range(1, 7)},
            meta=TekMetadata(
                channel_labels={
                    "CH1": "VGE_UH",
                    "CH2": "VCE_UH",
                    "CH3": "IC_UL",
                    "CH4": "IL",
                    "CH5": "VCE_UL",
                    "CH6": "VGE_UL",
                }
            ),
        )

        mapping = infer_mapping_from_bundle(bundle, "upper")
        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.irr, "CH3")
        self.assertEqual(mapping.ic, "")
        self.assertEqual(mapping.il, "CH4")
        self.assertTrue(mapping.ic_from_sum_irr_il)
        self.assertFalse(mapping.irr_from_ic_minus_il)

    def test_lower_label_ic_ul_is_lower_total_current(self):
        import numpy as np

        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 16),
            channels={f"CH{i}": np.zeros(16) for i in range(1, 7)},
            meta=TekMetadata(
                channel_labels={
                    "CH1": "VGE_UH",
                    "CH2": "VCE_UH",
                    "CH3": "IC_UL",
                    "CH4": "IL",
                    "CH5": "VCE_UL",
                    "CH6": "VGE_UL",
                }
            ),
        )

        mapping = infer_mapping_from_bundle(bundle, "lower")
        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.ic, "CH3")
        self.assertEqual(mapping.irr, "")
        self.assertEqual(mapping.il, "CH4")
        self.assertFalse(mapping.ic_from_sum_irr_il)
        self.assertTrue(mapping.irr_from_ic_minus_il)

    def test_infer_uses_channel_order_for_equal_label_matches(self):
        import numpy as np

        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        channels = {f"CH{i}": np.zeros(8) for i in range(1, 7)}
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 8),
            channels=channels,
            meta=TekMetadata(
                channel_labels={
                    "CH6": "H-Vge",
                    "CH5": "L-Vce",
                    "CH4": "IL",
                    "CH3": "Ic",
                    "CH2": "H-Vce",
                    "CH1": "H-Vge",
                }
            ),
        )

        m = infer_mapping_from_bundle(bundle, "upper")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.vge, "CH1")
        self.assertEqual(m.vce, "CH2")
        self.assertEqual(m.irr, "CH3")
        self.assertEqual(m.il, "CH4")

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

    @unittest.skipUnless(UL_2577.exists(), "UL 2577 sample missing")
    def test_infer_ul_lower_keeps_raw_ic_when_math_label_says_ic(self):
        bundle = load_waveform(UL_2577)
        self.assertEqual(bundle.meta.channel_labels.get("CH3"), "Irr")
        self.assertEqual(bundle.meta.channel_labels.get("MATH1"), "Ic")
        self.assertEqual(bundle.meta.channel_math_formulas.get("MATH1"), "CH3-CH4")

        m = infer_mapping_from_bundle(bundle, "lower")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.vge, "CH6")
        self.assertEqual(m.vce, "CH5")
        self.assertEqual(m.ic, "CH3")
        self.assertEqual(m.il, "CH4")
        self.assertEqual(m.v_diode, "CH2")
        self.assertEqual(m.vge_other, "CH1")
        self.assertEqual(m.irr, "")
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
