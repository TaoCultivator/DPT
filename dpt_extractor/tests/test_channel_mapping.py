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
