import tempfile
import unittest
from pathlib import Path

from dpt_extractor.models.bridge_profile import make_profile
from dpt_extractor.models.channel_mapping import (
    ChannelMapping,
    ChannelMappingStore,
    apply_mapping,
    channels_for_mapping,
    default_mapping_for,
    resolve_mapping_conflicts,
    sort_channel_names,
    validate_mapping,
)
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.tests.sample_paths import sample_tss

WH = sample_tss("WH_480V_800A_000.tss")
OTHER_360A = Path("示例文件") / "tss格式" / "其他数据" / "360A.tss"


class TestChannelMapping(unittest.TestCase):
    def test_apply_override(self):
        base = make_profile("U", "upper")
        m = ChannelMapping(vge="CH3", vce="CH2")
        p = apply_mapping(base, m)
        self.assertEqual(p.vge, "CH3")
        self.assertEqual(p.phase, "U")

    def test_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "maps.yaml"
            store = ChannelMappingStore(path)
            m = default_mapping_for("V", "lower")
            m2 = ChannelMapping.from_dict({**m.to_dict(), "vge": "CH5"})
            store.set("V", "lower", m2)
            loaded = store.get("V", "lower")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.vge, "CH5")

    def test_store_ignores_default_template_as_custom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "maps.yaml"
            store = ChannelMappingStore(path)
            store.set("U", "lower", default_mapping_for("U", "lower"))
            self.assertIsNone(store.get("U", "lower"))
            self.assertFalse(store.has_custom("U", "lower"))

    def test_validate_duplicate(self):
        m = ChannelMapping(vge="CH1", vce="CH1")
        errs = validate_mapping(m, None)
        self.assertTrue(any("重复" in e for e in errs))

    def test_bundle_get_supports_signed_channel_references(self):
        import numpy as np

        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        raw = np.array([1.0, -2.0, 3.5])
        bundle = WaveformBundle(
            t=np.arange(raw.size, dtype=np.float64),
            channels={"CH3": raw},
            meta=TekMetadata(),
        )

        np.testing.assert_allclose(bundle.get("-CH3"), -raw)
        np.testing.assert_allclose(bundle.get("+CH3"), raw)
        bundle.meta.channel_display_inversions.add("CH3")
        np.testing.assert_allclose(bundle.get("CH3"), -raw)
        np.testing.assert_allclose(bundle.get("-CH3"), -raw)
        self.assertTrue(bundle.has_channel_reference("-CH3"))
        with self.assertRaises(KeyError):
            bundle.get("-CH9")

    def test_display_inversions_feed_default_derived_currents(self):
        import numpy as np

        from dpt_extractor.models.waveform import (
            TekMetadata,
            WaveformBundle,
            bundle_reverse_recovery_current,
            try_bundle_total_current,
        )

        ch2 = np.array([100.0, 200.0, 300.0])
        ch3 = np.array([1.0, 2.0, 3.0])
        ch4 = np.array([10.0, 20.0, 30.0])
        bundle = WaveformBundle(
            t=np.arange(ch3.size, dtype=np.float64),
            channels={"CH2": ch2, "CH3": ch3, "CH4": ch4},
            meta=TekMetadata(),
        )

        upper = make_profile("U", "upper")
        lower = make_profile("U", "lower")

        np.testing.assert_allclose(bundle.get("CH2"), ch2)
        np.testing.assert_allclose(try_bundle_total_current(bundle, upper), ch3 + ch4)
        np.testing.assert_allclose(
            bundle_reverse_recovery_current(bundle, lower),
            ch3 - ch4,
        )

        bundle.meta.channel_display_inversions.add("CH2")
        bundle.meta.channel_display_inversions.add("CH4")
        np.testing.assert_allclose(bundle.get("CH2"), -ch2)
        np.testing.assert_allclose(try_bundle_total_current(bundle, upper), ch3 - ch4)
        np.testing.assert_allclose(
            bundle_reverse_recovery_current(bundle, lower),
            ch3 + ch4,
        )

    def test_channels_for_mapping_can_include_inverted_refs(self):
        import numpy as np

        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 4),
            channels={"CH1": np.zeros(4), "MATH1": np.ones(4)},
            meta=TekMetadata(),
        )

        names = channels_for_mapping(bundle, include_inverted=True)
        self.assertEqual(names, ["CH1", "-CH1", "MATH1", "-MATH1"])

    def test_validate_accepts_signed_existing_channels(self):
        import numpy as np

        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 8),
            channels={
                "CH1": np.zeros(8),
                "CH2": np.zeros(8),
                "CH3": np.zeros(8),
                "MATH1": np.zeros(8),
            },
            meta=TekMetadata(),
        )
        m = ChannelMapping(
            vge="-CH1",
            vce="CH2",
            ic="-MATH1",
            il="",
            irr="-CH3",
            v_diode="",
            vge_other="",
        )

        self.assertFalse(validate_mapping(m, bundle))

    def test_current_helpers_apply_signed_refs(self):
        import numpy as np
        from dataclasses import replace

        from dpt_extractor.models.waveform import (
            TekMetadata,
            WaveformBundle,
            bundle_reverse_recovery_current,
            try_bundle_total_current,
        )

        ch3 = np.array([1.0, 2.0, 3.0])
        ch4 = np.array([10.0, 20.0, 30.0])
        bundle = WaveformBundle(
            t=np.arange(ch3.size, dtype=np.float64),
            channels={"CH3": ch3, "CH4": ch4},
            meta=TekMetadata(),
        )
        profile = replace(
            make_profile("U", "upper"),
            ic="",
            irr="-CH3",
            il="CH4",
            ic_from_sum_irr_il=True,
            irr_from_ic_minus_il=False,
        )

        np.testing.assert_allclose(try_bundle_total_current(bundle, profile), ch4 - ch3)
        np.testing.assert_allclose(
            bundle_reverse_recovery_current(bundle, profile),
            -ch3,
        )

    def test_upper_inverted_lower_ic_is_oriented_as_irr(self):
        import numpy as np
        from dataclasses import replace

        from dpt_extractor.models.waveform import (
            TekMetadata,
            WaveformBundle,
            bundle_reverse_recovery_current,
            try_bundle_total_current,
        )

        il = np.full(128, 1050.0)
        raw_lower_ic = np.full(128, 980.0)
        raw_lower_ic[64:72] = 1220.0
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, raw_lower_ic.size),
            channels={"CH3": raw_lower_ic, "CH4": il},
            meta=TekMetadata(),
        )
        profile = replace(
            make_profile("U", "upper"),
            ic="",
            irr="CH3",
            il="CH4",
            ic_from_sum_irr_il=True,
            irr_from_ic_minus_il=False,
        )

        np.testing.assert_allclose(
            bundle_reverse_recovery_current(bundle, profile),
            -raw_lower_ic,
        )
        np.testing.assert_allclose(
            try_bundle_total_current(bundle, profile),
            il - raw_lower_ic,
        )

    def test_direct_total_current_negative_platform_is_oriented_positive(self):
        import numpy as np
        from dataclasses import replace

        from dpt_extractor.models.waveform import (
            TekMetadata,
            WaveformBundle,
            try_bundle_total_current,
        )

        raw_total = np.full(96, -800.0)
        raw_total[30:40] = -930.0
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, raw_total.size),
            channels={"CH3": raw_total},
            meta=TekMetadata(),
        )
        profile = replace(
            make_profile("U", "lower"),
            ic="CH3",
            il="",
            irr="",
            ic_from_sum_irr_il=False,
            irr_from_ic_minus_il=False,
        )

        np.testing.assert_allclose(try_bundle_total_current(bundle, profile), -raw_total)

    def test_direct_ic_overrides_sum_formula_fallback(self):
        import numpy as np
        from dataclasses import replace

        from dpt_extractor.models.waveform import (
            TekMetadata,
            WaveformBundle,
            bundle_reverse_recovery_current,
            try_bundle_total_current,
        )

        ch3 = np.array([1.0, 2.0, 3.0])
        ch4 = np.array([10.0, 20.0, 30.0])
        total = np.array([100.0, 200.0, 300.0])
        bundle = WaveformBundle(
            t=np.arange(ch3.size, dtype=np.float64),
            channels={"CH3": ch3, "CH4": ch4, "MATH1": total},
            meta=TekMetadata(),
        )
        profile = replace(
            make_profile("U", "upper"),
            ic="MATH1",
            irr="-CH3",
            il="CH4",
            ic_from_sum_irr_il=True,
        )

        np.testing.assert_allclose(try_bundle_total_current(bundle, profile), total)
        np.testing.assert_allclose(
            bundle_reverse_recovery_current(bundle, profile),
            -ch3,
        )

    def test_direct_irr_overrides_ic_minus_il_fallback(self):
        import numpy as np
        from dataclasses import replace

        from dpt_extractor.models.waveform import (
            TekMetadata,
            WaveformBundle,
            bundle_reverse_recovery_current,
            try_bundle_total_current,
        )

        ic = np.array([10.0, 20.0, 30.0])
        il = np.array([1.0, 2.0, 3.0])
        irr = np.array([4.0, 5.0, 6.0])
        bundle = WaveformBundle(
            t=np.arange(ic.size, dtype=np.float64),
            channels={"CH3": ic, "CH4": il, "MATH1": irr},
            meta=TekMetadata(),
        )
        profile = replace(
            make_profile("U", "lower"),
            ic="CH3",
            il="CH4",
            irr="-MATH1",
            irr_from_ic_minus_il=True,
        )

        np.testing.assert_allclose(try_bundle_total_current(bundle, profile), ic)
        np.testing.assert_allclose(
            bundle_reverse_recovery_current(bundle, profile),
            -irr,
        )

    def test_validate_direct_current_satisfies_formula_fallback_mapping(self):
        m = ChannelMapping(
            vge="CH1",
            vce="CH2",
            ic="CH3",
            il="",
            irr="-CH3",
            v_diode="",
            vge_other="",
            ic_from_sum_irr_il=True,
            irr_from_ic_minus_il=True,
        )

        self.assertFalse(validate_mapping(m, None))

    def test_formula_current_inputs_reject_same_underlying_channel(self):
        m = ChannelMapping(
            ic_from_sum_irr_il=True,
            irr="-CH3",
            il="CH3",
            ic="",
        )
        errs = validate_mapping(m, None)
        self.assertTrue(any("Irr" in e and "IL" in e for e in errs))

    def test_validate_can_allow_missing_current_file_channels(self):
        import numpy as np

        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 8),
            channels={f"CH{i}": np.zeros(8) for i in range(1, 6)},
            meta=TekMetadata(),
        )
        m = ChannelMapping(
            vge="CH1",
            vce="CH2",
            ic="CH3",
            il="CH4",
            irr="CH3",
            v_diode="CH5",
            vge_other="CH6",
            irr_from_ic_minus_il=True,
        )

        strict = validate_mapping(m, bundle)
        relaxed = validate_mapping(m, bundle, require_existing=False)

        self.assertTrue(any("CH6" in e and "不存在" in e for e in strict))
        self.assertFalse(relaxed)

    def test_validate_allows_optional_channels_to_be_unused(self):
        m = ChannelMapping(
            vge="CH1",
            vce="CH2",
            ic="CH3",
            il="",
            irr="",
            v_diode="",
            vge_other="",
            ic_from_sum_irr_il=False,
            irr_from_ic_minus_il=False,
        )

        self.assertFalse(validate_mapping(m, None))

    def test_validate_requires_total_current_source(self):
        m = ChannelMapping(
            vge="CH1",
            vce="CH2",
            ic="",
            il="",
            irr="",
            v_diode="",
            vge_other="",
            ic_from_sum_irr_il=False,
            irr_from_ic_minus_il=False,
        )

        self.assertTrue(any("Ic" in err for err in validate_mapping(m, None)))

    def test_validate_formula_current_still_requires_its_inputs(self):
        m = ChannelMapping(
            vge="CH1",
            vce="CH2",
            ic="",
            il="",
            irr="CH3",
            v_diode="",
            vge_other="",
            ic_from_sum_irr_il=True,
            irr_from_ic_minus_il=False,
        )

        self.assertTrue(any("IL" in err for err in validate_mapping(m, None)))

    def test_current_helpers_support_direct_total_without_rr_channels(self):
        import numpy as np
        from dataclasses import replace

        from dpt_extractor.models.waveform import (
            TekMetadata,
            WaveformBundle,
            try_bundle_reverse_recovery_current,
            try_bundle_total_current,
        )

        total = np.linspace(0.0, 10.0, 8)
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 8),
            channels={"CH1": np.zeros(8), "CH2": np.ones(8), "CH3": total},
            meta=TekMetadata(),
        )
        profile = replace(
            make_profile("U", "upper"),
            ic="CH3",
            il="",
            irr="",
            v_diode="",
            vge_other="",
            ic_from_sum_irr_il=False,
            irr_from_ic_minus_il=False,
        )

        self.assertTrue(np.array_equal(try_bundle_total_current(bundle, profile), total))
        self.assertIsNone(try_bundle_reverse_recovery_current(bundle, profile, total))

    def test_direct_math_current_roles_use_selected_supported_channels(self):
        import numpy as np

        from dpt_extractor.models.waveform import (
            TekMetadata,
            WaveformBundle,
            bundle_reverse_recovery_current,
            try_bundle_total_current,
        )

        n = 8
        ch4 = np.linspace(1.0, 8.0, n)
        irr = -ch4
        il = np.linspace(10.0, 80.0, n)
        total = irr + il
        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, n),
            channels={
                **{f"CH{i}": np.full(n, float(i)) for i in range(1, 9)},
                "CH4": ch4,
                "CH5": il,
                "MATH1": irr,
                "MATH2": total,
            },
            meta=TekMetadata(),
        )
        mapping = ChannelMapping(
            vge="CH8",
            vce="CH7",
            v_diode="CH6",
            irr="MATH1",
            il="CH5",
            ic="MATH2",
            vge_other="CH1",
            ic_from_sum_irr_il=True,
            irr_from_ic_minus_il=True,
        )
        profile = apply_mapping(make_profile("U", "upper"), mapping)

        self.assertFalse(validate_mapping(mapping, bundle))
        np.testing.assert_allclose(try_bundle_total_current(bundle, profile), total)
        np.testing.assert_allclose(
            bundle_reverse_recovery_current(bundle, profile),
            irr,
        )

    def test_waveform_mapping_unit_filters_use_overrides_first(self):
        import numpy as np

        from dpt_extractor.io.waveform_mapping import _unit_allows
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        bundle = WaveformBundle(
            t=np.linspace(0.0, 1e-6, 4),
            channels={"CH1": np.zeros(4), "CH2": np.zeros(4), "CH3": np.zeros(4)},
            meta=TekMetadata(
                channel_units={"CH1": "V", "CH2": "A", "CH3": "V"},
                channel_unit_overrides={"CH3": "A"},
            ),
        )

        self.assertTrue(_unit_allows(bundle, "CH1", "voltage"))
        self.assertFalse(_unit_allows(bundle, "CH1", "current"))
        self.assertTrue(_unit_allows(bundle, "CH2", "current"))
        self.assertFalse(_unit_allows(bundle, "CH2", "voltage"))
        self.assertTrue(_unit_allows(bundle, "CH3", "current"))
        self.assertFalse(_unit_allows(bundle, "CH3", "voltage"))

    @unittest.skipUnless(OTHER_360A.exists(), "360A sample missing")
    def test_waveform_mapping_uses_math_current_formula_when_labels_missing(self):
        from dpt_extractor.models.channel_mapping import infer_best_mapping_from_bundle

        bundle = load_waveform(OTHER_360A)
        mapping, method = infer_best_mapping_from_bundle(bundle, "upper")

        self.assertEqual(method, "trend")
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.vge, "CH1")
        self.assertEqual(mapping.vce, "CH2")
        self.assertEqual(mapping.v_diode, "CH3")
        self.assertEqual(mapping.irr, "MATH1")
        self.assertEqual(mapping.il, "CH5")
        self.assertTrue(mapping.ic_from_sum_irr_il)
        self.assertFalse(validate_mapping(mapping, bundle))

    def test_waveform_mapping_trend_values_use_display_inversion(self):
        import numpy as np

        from dpt_extractor.io.waveform_mapping import _channel_values
        from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

        raw = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        bundle = WaveformBundle(
            t=np.arange(raw.size, dtype=np.float64),
            channels={"CH4": raw},
            meta=TekMetadata(channel_display_inversions={"CH4"}),
        )

        np.testing.assert_allclose(_channel_values(bundle, "CH4"), -raw)

    def test_validate_irr_ic_minus_il_requires_distinct(self):
        m = ChannelMapping(
            irr_from_ic_minus_il=True,
            ic="CH3",
            il="CH3",
            irr="",
        )
        errs = validate_mapping(m, None)
        self.assertTrue(any("Ic" in e and "IL" in e for e in errs))

    def test_validate_ic_sum_irr_il_requires_distinct(self):
        m = ChannelMapping(
            ic_from_sum_irr_il=True,
            irr="CH3",
            il="CH3",
            ic="",
        )
        errs = validate_mapping(m, None)
        self.assertTrue(any("Irr" in e and "IL" in e for e in errs))

    def test_resolve_mapping_conflict_swaps_displaced_role(self):
        m = ChannelMapping(
            vge="CH1",
            vce="CH2",
            ic="",
            il="CH3",
            irr="CH3",
            v_diode="CH5",
            vge_other="CH6",
            ic_from_sum_irr_il=True,
        )
        resolved = resolve_mapping_conflicts(m, "il", "CH4")
        self.assertEqual(resolved.il, "CH3")
        self.assertEqual(resolved.irr, "CH4")
        self.assertFalse(validate_mapping(resolved, None))

    @unittest.skipUnless(WH.exists(), "WH sample missing")
    def test_channels_from_tss_bundle(self):
        bundle = load_waveform(WH)
        names = channels_for_mapping(bundle)
        self.assertEqual(names[0], "CH1")
        self.assertIn("MATH3", names)
        self.assertNotIn("MATH4", names)

    def test_sort_channel_names(self):
        self.assertEqual(
            sort_channel_names(["MATH2", "CH3", "MATH1", "CH1"]),
            ["CH1", "CH3", "MATH1", "MATH2"],
        )


if __name__ == "__main__":
    unittest.main()
