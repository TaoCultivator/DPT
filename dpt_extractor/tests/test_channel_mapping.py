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
