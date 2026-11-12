from __future__ import annotations

from pathlib import Path
import unittest

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_timings import turn_on_vce_top_from_ic_rise
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.channel_mapping import (
    apply_mapping,
    infer_best_mapping_from_bundle,
)
from dpt_extractor.models.waveform import bundle_total_current
from dpt_extractor.pipeline.extract import (
    _turn_on_delta_vce_knee_point,
    extract_all,
)


ROOT = Path(__file__).resolve().parents[2]
NDE36_ROOT = ROOT / "示例文件" / "songzhenxi" / "NDE36_MCU24A1" / "SMC"

# Values are the manually checked opening Delta Vce cursors embedded in
# MCU24A1_20260818_功率模块动态测试规范及数据记录.xlsx.  The NDE36 edge has a
# long gentle first fall followed by the main Vce fall; the old fixed slope
# gate selected about 229-233 V on seven of these eight waveforms.
CASES = {
    "UH1_25": (NDE36_ROOT / "RT" / "UH1_915V_400A_000.tss", 142.7457),
    "UL1_25": (NDE36_ROOT / "RT" / "UL1_915V_400A_000.tss", 99.0255),
    "UH2_25": (NDE36_ROOT / "RT" / "UH2_915V_400A_000.tss", 122.3871),
    "UL2_25": (NDE36_ROOT / "RT" / "UL2_915V_400A_000.tss", 105.8640),
    "UH1_150": (NDE36_ROOT / "HT" / "UH1_915V_400A_000.tss", 143.1450),
    "UL1_150": (NDE36_ROOT / "HT" / "UL1_915V_400A_000.tss", 100.2361),
    "UH2_150": (NDE36_ROOT / "HT" / "UH2_915V_400A_000.tss", 139.7169),
    "UL2_150": (NDE36_ROOT / "HT" / "UL2_915V_400A_000.tss", 115.6900),
}


@unittest.skipUnless(
    all(path.exists() for path, _target in CASES.values()),
    "NDE36 MCU24A1 report reference TSS files are missing",
)
class TestNde36ReportReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_config()

    def test_opening_delta_vce_tracks_manual_two_slope_knees(self) -> None:
        for label, (path, expected_delta) in CASES.items():
            with self.subTest(sample=label):
                bundle = load_waveform(path)
                profile = guess_profile_from_path(path)
                mapping, _source = infer_best_mapping_from_bundle(
                    bundle,
                    profile.bridge,
                )
                if mapping is not None:
                    profile = apply_mapping(profile, mapping)
                result = extract_all(bundle, profile, self.cfg)
                self.assertFalse(result.single_pulse_mode)
                self.assertAlmostEqual(
                    float(result.turn_on.delta_vce),
                    float(expected_delta),
                    delta=15.0,
                    msg=label,
                )

                segments = result.segments
                assert segments is not None
                vce = bundle.get(profile.vce)
                ic = bundle_total_current(bundle, profile)
                top = turn_on_vce_top_from_ic_rise(
                    ic,
                    vce,
                    segments.pulse2_on,
                    segments.pulse2_off,
                    bundle.dt,
                )
                knee = _turn_on_delta_vce_knee_point(
                    vce,
                    segments.turn_on[0],
                    segments.turn_on[1],
                    bundle.dt,
                    top,
                )
                self.assertIsNotNone(knee, label)
                assert knee is not None
                self.assertGreaterEqual(knee[0], segments.turn_on[0])
                self.assertLessEqual(knee[0], segments.turn_on[1])
                self.assertAlmostEqual(
                    float(top - knee[1]),
                    float(result.turn_on.delta_vce),
                    places=9,
                    msg=label,
                )


if __name__ == "__main__":
    unittest.main()
