import unittest

from dpt_extractor.models.bridge_profile import (
    guess_profile_from_path,
    make_profile,
    all_profiles,
)


class TestBridgeProfile(unittest.TestCase):
    def test_six_profiles(self):
        profiles = all_profiles()
        codes = {p.code for p in profiles}
        self.assertEqual(codes, {"UH", "UL", "VH", "VL", "WH", "WL"})

    def test_guess_from_filename(self):
        self.assertEqual(guess_profile_from_path("UH_480V_800A.csv").code, "UH")
        self.assertEqual(guess_profile_from_path("VL_test.csv").code, "VL")
        self.assertEqual(guess_profile_from_path("WH_480V_800A_000_ALL.csv").code, "WH")
        self.assertEqual(guess_profile_from_path("WL_480V_800A_000_ALL.csv").code, "WL")
        self.assertEqual(
            guess_profile_from_path("projectA_phaseA_upper_run001.csv").code,
            "UH",
        )
        self.assertEqual(
            guess_profile_from_path("projectB_phaseC_lowside_final.csv").code,
            "WL",
        )

    def test_same_channels_across_phases(self):
        wh = make_profile("W", "upper")
        uh = make_profile("U", "upper")
        self.assertEqual(wh.vge, uh.vge)
        self.assertEqual(wh.ic, uh.ic)


if __name__ == "__main__":
    unittest.main()
