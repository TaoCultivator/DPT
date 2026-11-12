"""2026-08-19 manually snapped MCU25S2 cursor/energy regressions."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.channel_mapping import apply_mapping, infer_best_mapping_from_bundle
from dpt_extractor.models.waveform import (
    bundle_reverse_recovery_current,
    bundle_total_current,
)
from dpt_extractor.pipeline.extract import extract_all


ROOT = Path(__file__).resolve().parents[2]
SAMPLE_ROOT = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "RT"
)
METRICS = (
    "off_dvdt",
    "off_didt",
    "off_e",
    "on_dvdt",
    "on_didt",
    "on_e",
    "rr_dvdt",
    "rr_didt",
    "rr_e",
)
GOLDEN = {
    "UH_750V_1048A_000.tss": (7.8313, 12.0062, 81.981, 1.7904, 4.8089, 105.965, 8.7583, 4.8018, 9.388),
    "UH_750V_806A_000.tss": (7.8902, 10.5428, 59.088, 2.0409, 4.1124, 81.884, 8.5606, 4.0911, 7.040),
    "UH_600V_403A_000.tss": (6.3913, 6.8471, 16.780, 2.1878, 2.6056, 29.280, 4.4254, 2.5181, 3.356),
    "UL_750V_1048A_000.tss": (10.5593, 12.5179, 64.851, 1.9805, 4.6421, 98.591, 9.2083, 4.5538, 12.817),
    "UL_750V_806A_000.tss": (10.3400, 10.7737, 46.502, 2.2477, 4.1471, 74.988, 9.1785, 3.9486, 9.092),
    "UL_600V_403A_000.tss": (8.7089, 5.8553, 13.479, 2.2194, 2.5781, 25.929, 7.4154, 2.6965, 4.640),
    "VH_750V_1048A_000.tss": (7.8307, 12.3833, 82.057, 1.8450, 4.9376, 100.597, 8.8844, 5.0208, 7.686),
    "VH_750V_806A_000.tss": (7.7121, 10.2961, 59.061, 2.1162, 4.1940, 78.421, 8.7018, 4.2881, 7.158),
    "VH_600V_403A_000.tss": (6.4714, 7.1262, 16.273, 2.2494, 2.6906, 28.130, 6.9290, 2.7464, 3.594),
    "VL_750V_1048A_000.tss": (10.5819, 12.0938, 68.033, 1.9808, 4.7879, 96.921, 9.3864, 4.6596, 14.972),
    "VL_750V_806A_000.tss": (10.2027, 10.8399, 45.895, 2.3011, 4.1716, 72.694, 9.3611, 4.2022, 9.691),
    "VL_600V_403A_000.tss": (8.5621, 6.8850, 12.868, 2.4736, 2.7777, 25.345, 7.4614, 2.7028, 4.205),
    "WH_750V_1048A_000.tss": (7.8429, 11.6257, 82.741, 1.8450, 4.9463, 99.132, 8.8767, 4.9303, 7.914),
    "WH_750V_806A_000.tss": (7.6965, 10.2203, 59.344, 2.0572, 4.3573, 77.359, 8.7507, 4.2664, 7.635),
    "WH_600V_403A_000.tss": (6.3182, 6.6009, 15.489, 2.2190, 2.6538, 27.553, 6.9237, 2.6080, 3.308),
    "WL_750V_1048A_000.tss": (10.5773, 12.3787, 67.164, 1.9261, 4.5107, 99.565, 9.3861, 4.3990, 18.932),
    "WL_750V_806A_000.tss": (10.3644, 10.8988, 43.459, 2.1772, 4.0112, 74.470, 9.3622, 3.8977, 9.734),
    "WL_600V_403A_000.tss": (8.7895, 6.7076, 13.704, 2.3179, 2.6907, 25.750, 7.5861, 2.5237, 4.625),
}


def _actual(result) -> dict[str, float]:
    return {
        "off_dvdt": float(result.turn_off.dvdt),
        "off_didt": float(result.turn_off.didt),
        "off_e": float(result.turn_off.eoff),
        "on_dvdt": float(result.turn_on.dvdt),
        "on_didt": float(result.turn_on.didt),
        "on_e": float(result.turn_on.eon),
        "rr_dvdt": float(result.reverse_recovery.dvdt_max),
        "rr_didt": float(result.reverse_recovery.didt_irr),
        "rr_e": float(result.reverse_recovery.err),
    }


def _is_raw_crossing(
    t: np.ndarray,
    y: np.ndarray,
    cursor_t: float,
    level: float,
) -> bool:
    index = int(np.searchsorted(t, float(cursor_t), side="right")) - 1
    for k in range(max(0, index - 2), min(len(y) - 1, index + 3)):
        y0 = float(y[k])
        y1 = float(y[k + 1])
        if min(y0, y1) - 1e-9 <= float(level) <= max(y0, y1) + 1e-9:
            return True
    return False


@unittest.skipUnless(
    all((SAMPLE_ROOT / name).exists() for name in GOLDEN),
    "MCU25S2 2026-08-19 golden TSS files are missing",
)
class TestMcu25s20819ReportReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = []
        cfg = load_config()
        for name, expected_values in GOLDEN.items():
            path = SAMPLE_ROOT / name
            bundle = load_waveform(path)
            profile = guess_profile_from_path(path)
            mapping, _source = infer_best_mapping_from_bundle(bundle, profile.bridge)
            if mapping is not None:
                profile = apply_mapping(profile, mapping)
            result = extract_all(bundle, profile, cfg)
            cls.cases.append((name, expected_values, bundle, profile, result))

    def test_all_18_operating_points_track_manual_cursor_values(self) -> None:
        errors = {metric: [] for metric in METRICS}
        for name, expected_values, _bundle, _profile, result in self.cases:
            with self.subTest(sample=name):
                self.assertFalse(result.single_pulse_mode)
                self.assertEqual(result.detected_pulse_count, 2)
                actual = _actual(result)
                for metric, expected in zip(METRICS, expected_values):
                    relative = abs(actual[metric] - expected) / abs(expected)
                    errors[metric].append(relative)
                    self.assertLessEqual(relative, 0.05, f"{name} {metric}")

        for metric, values in errors.items():
            with self.subTest(metric=metric):
                self.assertLessEqual(float(np.mean(values)), 0.02)

    def test_loss_cursors_are_real_raw_waveform_intersections(self) -> None:
        for name, _expected, bundle, profile, result in self.cases:
            with self.subTest(sample=name):
                t = np.asarray(bundle.t, dtype=np.float64)
                ic = np.asarray(bundle_total_current(bundle, profile), dtype=np.float64)
                irr = np.asarray(
                    bundle_reverse_recovery_current(bundle, profile),
                    dtype=np.float64,
                )
                vce = np.asarray(bundle.get(profile.vce), dtype=np.float64)
                vd = np.asarray(bundle.get(profile.v_diode), dtype=np.float64)
                eoff = result.energy_contexts[("关断过程", "Eoff")]
                eon = result.energy_contexts[("开通", "Eon")]
                err = result.energy_contexts[("反向恢复", "Err")]
                endpoint_mode = str(
                    getattr(eoff, "endpoint_mode", "level_crossings")
                )
                if endpoint_mode == "stable_platforms":
                    context = getattr(eoff, "stable_platform_context", None)
                    self.assertIsNotNone(context, f"{name} Eoff stable context")
                    assert context is not None
                    self.assertEqual(int(eoff.i_start), int(context.a_idx))
                    self.assertEqual(int(eoff.i_end), int(context.b_idx))
                    self.assertAlmostEqual(
                        float(eoff.t_start), float(t[int(context.a_idx)]), places=15
                    )
                    self.assertAlmostEqual(
                        float(eoff.t_end), float(t[int(context.b_idx)]), places=15
                    )
                    self.assertLessEqual(
                        int(context.a_band_start_idx), int(context.a_idx)
                    )
                    self.assertLessEqual(
                        int(context.a_idx), int(context.a_band_end_idx)
                    )
                    self.assertLess(
                        int(context.a_band_end_idx), int(context.v10_idx)
                    )
                    self.assertLess(int(context.v10_idx), int(context.v90_idx))
                    self.assertLessEqual(int(context.v10_idx), int(context.i90_idx))
                    self.assertLess(int(context.i90_idx), int(context.i10_idx))
                    self.assertLessEqual(
                        int(context.i10_idx), int(context.b_band_start_idx)
                    )
                    self.assertLessEqual(
                        int(context.b_band_start_idx), int(context.b_idx)
                    )
                    self.assertLessEqual(
                        int(context.b_idx), int(context.b_band_end_idx)
                    )
                    self.assertLessEqual(
                        int(context.b_band_end_idx), int(context.search_end_idx)
                    )
                    eoff_checks = ()
                else:
                    self.assertEqual(endpoint_mode, "level_crossings")
                    eoff_checks = (
                        (vce, eoff.t_start, eoff.ha_v, "Eoff A"),
                        (ic, eoff.t_end, eoff.hb_a, "Eoff B"),
                    )
                checks = eoff_checks + (
                    (ic, eon.t_start, eon.ha_v, "Eon A"),
                    (vce, eon.t_end, eon.hb_a, "Eon B"),
                    (irr, err.t_start, err.ha_v, "Err A"),
                    (vd, err.t_end, err.hb_a, "Err B"),
                )
                for waveform, cursor_t, level, label in checks:
                    self.assertTrue(
                        _is_raw_crossing(t, waveform, cursor_t, level),
                        f"{name} {label}",
                    )


if __name__ == "__main__":
    unittest.main()
