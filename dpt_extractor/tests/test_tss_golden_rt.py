from __future__ import annotations

import unittest
from pathlib import Path

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_windows import (
    eoff_energy_markers,
    eon_energy_markers,
    err_energy_markers,
    integrate_err_recovery,
    integrate_vi_window,
)
from dpt_extractor.metrics.irr_measure import default_irr_trr_measure
from dpt_extractor.metrics.plateau_level import (
    turn_on_current_hb_ha_t,
    turn_on_didt_ha_at_turn_on,
    turn_on_ic_a_cross_hb_us,
    turn_on_ic_b_cross_ha_us,
)
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.waveform import (
    bundle_reverse_recovery_current,
    bundle_total_current,
)
from dpt_extractor.pipeline.extract import (
    _turn_on_delta_vce_knee_point,
    extract_all,
)

ROOT = Path(__file__).resolve().parents[2]

GOLDEN = {
    "UH": {
        "path": ROOT
        / "示例文件/tss格式/KSU2577/SSM1R7PB12B3DTFMMSPP25M4CF0016/SSS/RT/tss/UH_750V_1050A_000.tss",
        "segments_us": {
            "turn_off": (13.831680, 15.633040),
            "turn_on": (18.197440, 19.158720),
            "rr": (18.582720, 18.676800),
        },
        "results": {
            "vdc": 756.03125,
            "idc": 1051.25,
            "off_delta_vce": 337.21875,
            "off_dvdt": 7.594292,
            "off_didt": 10.622707,
            "eoff": 88.884428,
            "on_delta_vce": 309.698529,
            "turn_on_current": 1036.125,
            "on_dvdt": 2.596768,
            "on_didt": 6.565013,
            "eon": 68.324880,
            "irr": 173.90625,
            "trr": 32.815655,
            "vrr": 985.03125,
            "rr_dvdt": 12.970562,
            "rr_didt": 13.737728,
            "err": 1.079359,
        },
        "markers": {
            "eoff": (14.518515, 14.800636, 11.59375, 40.558667),
            "eon": (18.433584, 18.768988, 32.140625, 4.09375),
            "err": (18.646479, 18.615986, 24.09375, 7.78125),
            "trr": (18.613803, 18.646618, 20.265625, 173.90625),
            "turn_on_current": (18.414384, 19.001280, 32.140625, 1036.125),
            "delta_vce_knee": (18.632640, 446.488971),
        },
    },
    "UL": {
        "path": ROOT
        / "示例文件/tss格式/KSU2577/SSM1R7PB12B3DTFMMSPP25M4CF0016/SSS/RT/tss/UL_750V_1050A_000.tss",
        "segments_us": {
            "turn_off": (14.725040, 16.384560),
            "turn_on": (19.184640, 20.158320),
            "rr": (19.550080, 19.635760),
        },
        "results": {
            "vdc": 744.0625,
            "idc": 1054.25,
            "off_delta_vce": 345.25,
            "off_dvdt": 10.957675,
            "off_didt": 12.435164,
            "eoff": 69.532798,
            "on_delta_vce": 330.249387,
            "turn_on_current": 1038.390625,
            "on_dvdt": 3.004423,
            "on_didt": 8.008443,
            "eon": 51.582301,
            "irr": 113.6875,
            "trr": 32.847202,
            "vrr": 1029.03125,
            "rr_dvdt": 14.146104,
            "rr_didt": 10.831239,
            "err": 0.596078,
        },
        "markers": {
            "eoff": (15.460102, 15.704218, 7.78125, -23.041583),
            "eon": (19.410792, 19.683402, -32.15625, 7.78125),
            "err": (19.609181, 19.571331, -38.56250, 4.09375),
            "trr": (19.576340, 19.609187, -39.109375, 113.6875),
            "turn_on_current": (19.384081, 19.968320, -32.15625, 1038.390625),
            "delta_vce_knee": (19.598880, 413.938113),
        },
    },
}


class TestGoldenRtTssSnapshots(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_config()

    def assert_close(self, actual: float, expected: float, *, tol: float, label: str) -> None:
        self.assertAlmostEqual(actual, expected, delta=tol, msg=label)

    def test_manual_validated_rt_samples_do_not_drift(self) -> None:
        for label, snap in GOLDEN.items():
            path = snap["path"]
            with self.subTest(sample=label):
                if not path.exists():
                    self.skipTest(f"missing {path}")

                profile = guess_profile_from_path(path)
                bundle = load_waveform(path)
                result = extract_all(bundle, profile, self.cfg)
                self.assertEqual(result.detected_pulse_count, 2)
                self.assertEqual(result.off_pulse_index, 1)
                self.assertEqual(result.on_pulse_index, 2)
                self.assertFalse(result.single_pulse_mode)

                segs = result.segments
                assert segs is not None
                t = bundle.t
                dt = bundle.dt
                off0, off1 = segs.turn_off
                on0, on1 = segs.turn_on
                rr0, rr1 = segs.reverse_recovery
                actual_segments = {
                    "turn_off": (float(t[off0]) * 1e6, float(t[off1]) * 1e6),
                    "turn_on": (float(t[on0]) * 1e6, float(t[on1]) * 1e6),
                    "rr": (float(t[rr0]) * 1e6, float(t[rr1]) * 1e6),
                }
                for key, expected_pair in snap["segments_us"].items():
                    actual_pair = actual_segments[key]
                    self.assert_close(
                        actual_pair[0], expected_pair[0], tol=0.001, label=f"{label} {key} start"
                    )
                    self.assert_close(
                        actual_pair[1], expected_pair[1], tol=0.001, label=f"{label} {key} end"
                    )

                res_values = {
                    "vdc": result.vdc,
                    "idc": result.idc,
                    "off_delta_vce": result.turn_off.delta_vce,
                    "off_dvdt": result.turn_off.dvdt,
                    "off_didt": result.turn_off.didt,
                    "eoff": result.turn_off.eoff,
                    "on_delta_vce": result.turn_on.delta_vce,
                    "turn_on_current": result.turn_on.turn_on_current,
                    "on_dvdt": result.turn_on.dvdt,
                    "on_didt": result.turn_on.didt,
                    "eon": result.turn_on.eon,
                    "irr": result.reverse_recovery.irr,
                    "trr": result.reverse_recovery.trr,
                    "vrr": result.reverse_recovery.vrr,
                    "rr_dvdt": result.reverse_recovery.dvdt_max,
                    "rr_didt": result.reverse_recovery.didt_irr,
                    "err": result.reverse_recovery.err,
                }
                for key, expected in snap["results"].items():
                    self.assert_close(
                        float(res_values[key]),
                        float(expected),
                        tol=max(0.001, abs(float(expected)) * 0.0005),
                        label=f"{label} {key}",
                    )

                vce = bundle.get(profile.vce)
                vd = bundle.get(profile.v_diode)
                ic = bundle_total_current(bundle, profile)
                irr = bundle_reverse_recovery_current(bundle, profile)
                eoff_m = eoff_energy_markers(
                    t,
                    ic,
                    vce,
                    off0,
                    off1,
                    segs.pulse1_off,
                    dt,
                    pre_ns=self.cfg.energy.eoff_pre_ns,
                    pulse1_on=segs.pulse1_on,
                )
                eon_m = eon_energy_markers(
                    t,
                    ic,
                    vce,
                    on0,
                    on1,
                    segs.pulse2_on,
                    dt,
                    pulse1_off=segs.pulse1_off,
                )
                err_m = err_energy_markers(t, irr, vd, rr0, rr1, dt, i_search_end=on1)
                trr_m = default_irr_trr_measure(
                    t, irr, rr0, rr1, segs.pulse2_on, on0, on1
                )
                self.assertIsNotNone(trr_m)
                assert trr_m is not None
                hb, ha = turn_on_current_hb_ha_t(t, ic, on0, on1, dt)
                a_us = turn_on_ic_a_cross_hb_us(t, ic, on0, on1, hb, dt)
                b_us = turn_on_ic_b_cross_ha_us(t, ic, on0, on1, ha, dt)
                knee = _turn_on_delta_vce_knee_point(
                    vce, on0, on1, dt, result.turn_on.vce_on_max
                )
                self.assertIsNotNone(knee)
                assert knee is not None
                actual_markers = {
                    "eoff": (
                        eoff_m.t_start * 1e6,
                        eoff_m.t_end * 1e6,
                        eoff_m.ha_v,
                        eoff_m.hb_a,
                    ),
                    "eon": (
                        eon_m.t_start * 1e6,
                        eon_m.t_end * 1e6,
                        eon_m.ha_v,
                        eon_m.hb_a,
                    ),
                    "err": (
                        err_m.t_start * 1e6,
                        err_m.t_end * 1e6,
                        err_m.ha_v,
                        err_m.hb_a,
                    ),
                    "trr": (
                        trr_m.ta_s * 1e6,
                        trr_m.tb_s * 1e6,
                        trr_m.ha,
                        trr_m.hb,
                    ),
                    "turn_on_current": (a_us, b_us, hb, ha),
                    "delta_vce_knee": (float(t[knee[0]]) * 1e6, float(knee[1])),
                }
                for key, expected_values in snap["markers"].items():
                    actual_values = actual_markers[key]
                    for idx, expected in enumerate(expected_values):
                        self.assert_close(
                            float(actual_values[idx]),
                            float(expected),
                            tol=max(0.001, abs(float(expected)) * 0.0005),
                            label=f"{label} {key}[{idx}]",
                        )
                self.assert_close(
                    turn_on_didt_ha_at_turn_on(t, ic, on0, on1, dt),
                    ha,
                    tol=0.001,
                    label=f"{label} turn-on current Ha and didt Ha",
                )
                self.assert_close(
                    integrate_vi_window(t, vce, ic, eoff_m.as_integration_window()),
                    result.turn_off.eoff,
                    tol=0.001,
                    label=f"{label} eoff integration",
                )
                self.assert_close(
                    integrate_vi_window(t, vce, ic, eon_m.as_integration_window()),
                    result.turn_on.eon,
                    tol=0.001,
                    label=f"{label} eon integration",
                )
                self.assert_close(
                    integrate_err_recovery(t, vd, irr, err_m.as_integration_window()),
                    result.reverse_recovery.err,
                    tol=0.001,
                    label=f"{label} err integration",
                )
                self.assert_close(
                    trr_m.trr_ns,
                    result.reverse_recovery.trr,
                    tol=0.001,
                    label=f"{label} trr table and default cursor",
                )
