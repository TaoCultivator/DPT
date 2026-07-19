"""Irr/Trr 卡尺算法测试。"""

from __future__ import annotations



import unittest

import numpy as np



from dpt_extractor.config.loader import load_config

from dpt_extractor.io.waveform_loader import load_waveform

from dpt_extractor.metrics.irr_measure import (
    default_irr_trr_measure,
    irr_parameter_peak_index,
    irr_parameter_peak_value,
    measure_irr_trr,
    trr_crossings_at_ha,
)
from dpt_extractor.metrics.iec_timings import reverse_recovery_trr

from dpt_extractor.models.bridge_profile import guess_profile_from_path

from dpt_extractor.models.waveform import bundle_reverse_recovery_current

from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.tests.sample_paths import SAMPLE_ROOT, sample_tss





class TestIrrMeasure(unittest.TestCase):

    def test_positive_lobe_crossings(self):

        n = 400

        t = np.linspace(0, 1e-6, n)

        irr = np.zeros(n)

        irr[:80] = 25.0

        irr[80:140] = np.linspace(25.0, 165.0, 60)

        irr[140:220] = np.linspace(165.0, 25.0, 80)

        irr[220:] = 25.0

        m = measure_irr_trr(t, irr, 0, n - 1)

        self.assertIsNotNone(m)

        assert m is not None

        self.assertAlmostEqual(m.stable_level, 25.0, delta=1.0)
        self.assertAlmostEqual(m.ha, 25.0, delta=1.0)

        self.assertAlmostEqual(m.hb, 165.0, delta=3.0)

        self.assertAlmostEqual(m.irr, 165.0, delta=3.0)

        self.assertGreater(m.trr_ns, 50.0)

        self.assertLess(m.ta_s, m.tb_s)


    def test_negative_lobe_uses_absolute_main_peak(self):

        n = 500

        t = np.linspace(0, 1.2e-6, n)

        irr = np.full(n, 20.0)

        irr[90:150] = np.linspace(20.0, -900.0, 60)

        irr[150:230] = np.linspace(-900.0, 20.0, 80)

        irr[280:320] = np.linspace(20.0, 120.0, 40)

        irr[320:360] = np.linspace(120.0, 20.0, 40)

        m = measure_irr_trr(t, irr, 0, n - 1, ha=20.0)

        self.assertIsNotNone(m)

        assert m is not None

        self.assertAlmostEqual(m.hb, -900.0, delta=5.0)

        self.assertAlmostEqual(m.irr, 900.0, delta=5.0)

        self.assertLess(m.ta_s, m.tb_s)

        self.assertLess(m.peak_idx, 230)


    def test_parameter_peak_matches_extraction_main_lobe_rule(self):

        n = 400

        irr = np.zeros(n)

        irr[100:130] = np.linspace(0.0, -260.0, 30)

        irr[130:170] = np.linspace(-260.0, 0.0, 40)

        irr[210:240] = np.linspace(0.0, 145.0, 30)

        irr[240:280] = np.linspace(145.0, 0.0, 40)

        idx = irr_parameter_peak_index(irr, 90, 180, 90, 80, n - 1)

        self.assertGreater(idx, 200)

        self.assertAlmostEqual(float(irr[idx]), 145.0, delta=5.0)

        self.assertAlmostEqual(
            irr_parameter_peak_value(irr, 90, 180, 90, 80, n - 1),
            145.0,
            delta=5.0,
        )

    def test_parameter_peak_keeps_small_recovery_lobe_after_large_negative_platform(self):
        irr = np.full(500, -1080.0)
        irr[170:211] = np.linspace(-1080.0, 70.0, 41)
        irr[211:251] = np.linspace(70.0, -60.0, 40)
        irr[251:] = -60.0

        idx = irr_parameter_peak_index(irr, 80, 260, 100, 60, 420)

        self.assertEqual(idx, 210)
        self.assertAlmostEqual(float(irr[idx]), 70.0, places=12)
        self.assertAlmostEqual(
            irr_parameter_peak_value(irr, 80, 260, 100, 60, 420),
            70.0,
            places=12,
        )

    def test_parameter_peak_keeps_existing_bipolar_rule_without_negative_platform(self):
        irr = np.zeros(500)
        irr[100:151] = np.linspace(0.0, -260.0, 51)
        irr[151:201] = np.linspace(-260.0, 0.0, 50)
        irr[240:271] = np.linspace(0.0, 14.0, 31)
        irr[271:301] = np.linspace(14.0, 0.0, 30)

        idx = irr_parameter_peak_index(irr, 90, 210, 90, 80, 420)

        self.assertLess(idx, 210)
        self.assertAlmostEqual(float(irr[idx]), -260.0, places=12)

    def test_default_trr_stops_before_short_second_pulse_turn_off(self):
        t = np.arange(2001, dtype=np.float64) * 1e-9
        irr = np.full(2001, -50.0)
        irr[200:301] = np.linspace(-50.0, 200.0, 101)
        irr[301:451] = np.linspace(200.0, 20.0, 150)
        irr[451:650] = 20.0
        # A later, larger turn-off level must not steal I_RM or stable_level.
        irr[650:] = 300.0

        marker = default_irr_trr_measure(
            t,
            irr,
            0,
            500,
            0,
            0,
            800,
            pulse2_off=650,
        )

        self.assertIsNotNone(marker)
        assert marker is not None
        self.assertAlmostEqual(marker.hb, 200.0, places=12)
        self.assertAlmostEqual(marker.stable_level, 20.0, places=12)
        self.assertAlmostEqual(marker.ha, 20.0, places=12)
        self.assertAlmostEqual(marker.ta_s * 1e9, 228.0, places=9)
        self.assertAlmostEqual(marker.tb_s * 1e9, 450.0, places=9)
        self.assertAlmostEqual(marker.trr_ns, 222.0, places=9)
        self.assertAlmostEqual(
            reverse_recovery_trr(
                t,
                irr,
                np.zeros_like(irr),
                0,
                800,
                1e-9,
                load_config(),
                rr0=0,
                rr1=500,
                on_edge=0,
                pulse2_off=650,
            ),
            222.0,
            places=9,
        )

    def test_default_trr_fails_closed_without_post_peak_platform_before_turn_off(self):
        t = np.arange(1001, dtype=np.float64) * 1e-9
        irr = np.full(1001, -50.0)
        irr[200:301] = np.linspace(-50.0, 200.0, 101)
        irr[301:451] = np.linspace(200.0, 20.0, 150)
        irr[451:] = 20.0

        before_peak = default_irr_trr_measure(
            t, irr, 0, 500, 0, 0, 800, pulse2_off=280
        )
        two_tail_samples = default_irr_trr_measure(
            t, irr, 0, 500, 0, 0, 800, pulse2_off=303
        )

        self.assertIsNone(before_peak)
        self.assertIsNone(two_tail_samples)



    def test_ha_drag_recomputes_crossings(self):

        n = 400

        t = np.linspace(0, 1e-6, n)

        irr = np.zeros(n)

        irr[:80] = 20.0

        irr[80:140] = np.linspace(20.0, 150.0, 60)

        irr[140:220] = np.linspace(150.0, 20.0, 80)

        irr[220:] = 20.0

        m0 = measure_irr_trr(t, irr, 0, n - 1)

        m1 = measure_irr_trr(t, irr, 0, n - 1, ha=25.0)

        self.assertIsNotNone(m0)

        self.assertIsNotNone(m1)

        assert m1 is not None

        self.assertAlmostEqual(m1.ha, 25.0, delta=1.0)

        self.assertGreater(m1.tb_s, m1.ta_s)



        cross = trr_crossings_at_ha(t, irr, 0, n - 1, 30.0, peak_idx=m1.peak_idx)

        self.assertIsNotNone(cross)

        assert cross is not None

        ta, tb, _ = cross

        self.assertLess(ta, tb)

    def test_positive_lobe_negative_ha_uses_signed_raw_crossings(self):
        n = 240
        t = np.linspace(0.0, 1.2e-6, n)
        irr = np.full(n, -2.0)
        irr[60:120] = np.linspace(-2.0, 120.0, 60)
        irr[120:190] = np.linspace(120.0, -2.0, 70)

        cross = trr_crossings_at_ha(
            t,
            irr,
            0,
            n - 1,
            -1.5,
            peak_idx=119,
        )

        self.assertIsNotNone(cross)
        assert cross is not None
        ta, tb, _ = cross
        self.assertAlmostEqual(float(np.interp(ta, t, irr)), -1.5, places=10)
        self.assertAlmostEqual(float(np.interp(tb, t, irr)), -1.5, places=10)

    def test_trr_does_not_invent_abs_fallback_without_signed_b(self):
        n = 240
        t = np.linspace(0.0, 1.2e-6, n)
        irr = np.full(n, 1.0)
        irr[60:120] = np.linspace(1.0, 120.0, 60)
        irr[120:190] = np.linspace(120.0, 1.0, 70)

        cross = trr_crossings_at_ha(
            t,
            irr,
            0,
            n - 1,
            -1.0,
            peak_idx=119,
        )

        self.assertIsNone(cross)

    def test_default_trr_uses_recovered_platform_midline(self):
        t = np.linspace(0.0, 1.0e-6, 1001)
        irr = np.full_like(t, 20.0)
        irr[100:201] = np.linspace(20.0, 220.0, 101)
        irr[201:301] = np.linspace(218.0, 20.0, 100)

        m = measure_irr_trr(
            t,
            irr,
            0,
            800,
            peak_idx=200,
            i_fall_end=800,
        )

        self.assertIsNotNone(m)
        assert m is not None
        self.assertAlmostEqual(m.stable_level, 20.0, delta=0.01)
        self.assertAlmostEqual(m.ha, 20.0, delta=0.01)
        self.assertAlmostEqual(m.hb, 220.0, delta=0.01)
        self.assertAlmostEqual(m.ta_s * 1e6, 0.100, delta=0.002)
        self.assertAlmostEqual(m.tb_s * 1e6, 0.300, delta=0.002)
        self.assertAlmostEqual(float(np.interp(m.ta_s, t, irr)), m.ha, places=9)
        self.assertAlmostEqual(float(np.interp(m.tb_s, t, irr)), m.ha, places=9)

    def test_stable_midline_trr_is_invariant_for_a_fixed_physical_peak(self):
        t = np.linspace(0.0, 1.0e-6, 1001)
        irr = np.full_like(t, 20.0)
        irr[120:281] = np.linspace(20.0, 240.0, 161)
        irr[281:441] = np.linspace(238.625, 20.0, 160)

        positive = measure_irr_trr(
            t, irr, 0, 800, peak_idx=280, i_fall_end=800
        )
        mirrored = measure_irr_trr(
            t, -irr, 0, 800, peak_idx=280, i_fall_end=800
        )

        self.assertIsNotNone(positive)
        self.assertIsNotNone(mirrored)
        assert positive is not None and mirrored is not None
        self.assertAlmostEqual(positive.trr_ns, mirrored.trr_ns, places=9)
        self.assertAlmostEqual(positive.ta_s, mirrored.ta_s, places=15)
        self.assertAlmostEqual(positive.tb_s, mirrored.tb_s, places=15)
        self.assertAlmostEqual(positive.ha, -mirrored.ha, places=9)
        self.assertAlmostEqual(positive.hb, -mirrored.hb, places=9)

    def test_stable_midline_trr_ignores_ringing_after_reference_window(self):
        t = np.linspace(0.0, 1.5e-6, 1501)
        irr = np.full_like(t, 20.0)
        irr[150:301] = np.linspace(20.0, 200.0, 151)
        irr[301:501] = np.linspace(199.1, 20.0, 200)
        baseline = measure_irr_trr(
            t, irr, 0, 1200, peak_idx=300, i_fall_end=1200
        )

        ringing = irr.copy()
        ring_t = t[950:1150] - t[950]
        ringing[950:1150] += 70.0 * np.exp(-ring_t / 0.4e-6) * np.sin(
            2.0 * np.pi * ring_t / 60e-9
        )
        measured = measure_irr_trr(
            t, ringing, 0, 1200, peak_idx=300, i_fall_end=1200
        )

        self.assertIsNotNone(baseline)
        self.assertIsNotNone(measured)
        assert baseline is not None and measured is not None
        self.assertAlmostEqual(measured.trr_ns, baseline.trr_ns, places=9)

    def test_recovered_platform_ignores_an_isolated_spike(self):
        t = np.linspace(0.0, 1.0e-6, 1001)
        irr = np.full_like(t, 20.0)
        irr[100:201] = np.linspace(20.0, 220.0, 101)
        irr[201:301] = np.linspace(218.0, 20.0, 100)
        clean = measure_irr_trr(
            t, irr, 0, 800, peak_idx=200, i_fall_end=800
        )
        spiked = irr.copy()
        spiked[650] = 220.0
        measured = measure_irr_trr(
            t, spiked, 0, 800, peak_idx=200, i_fall_end=800
        )
        self.assertIsNotNone(clean)
        self.assertIsNotNone(measured)
        assert clean is not None and measured is not None
        self.assertAlmostEqual(measured.stable_level, 20.0, delta=0.01)
        self.assertAlmostEqual(measured.ha, clean.ha, delta=0.01)
        self.assertAlmostEqual(measured.trr_ns, clean.trr_ns, places=9)

    def test_short_recovery_tail_uses_only_samples_before_tail_end(self):
        t = np.linspace(0.0, 1.0e-6, 1001)
        irr = np.linspace(0.0, 1000.0, len(t))
        irr[100:151] = np.linspace(100.0, 300.0, 51)
        irr[151:221] = np.linspace(297.0, 180.0, 70)
        m = measure_irr_trr(
            t,
            irr,
            100,
            220,
            peak_idx=150,
            i_fall_end=220,
        )
        self.assertIsNotNone(m)
        assert m is not None
        self.assertIsNotNone(m.stable_level)
        assert m.stable_level is not None
        self.assertLessEqual(m.stable_level, float(np.max(irr[150:221])))
        self.assertGreaterEqual(m.stable_level, float(np.min(irr[150:221])))



    def test_uh_measured_tss(self):

        sample = sample_tss("UH_750V_1050A_000.tss")

        if not sample.is_file():

            self.skipTest("UH TSS 样本缺失")

        bundle = load_waveform(sample)

        profile = guess_profile_from_path(str(sample))

        result = extract_all(bundle, profile, load_config())

        irr = bundle_reverse_recovery_current(bundle, profile)

        i0, i1 = result.segments.reverse_recovery

        m = measure_irr_trr(bundle.t, irr, i0, i1)

        self.assertIsNotNone(m, "UH 反向恢复段应能识别尖峰与 A/B")

        assert m is not None

        self.assertGreater(abs(m.hb), 300.0)

        self.assertLess(abs(m.hb), 400.0)

        self.assertGreater(m.irr, 300.0)

        self.assertLess(m.irr, 400.0)

        self.assertGreater(m.trr_ns, 20.0)

        self.assertLess(m.trr_ns, 80.0)

    def test_songzhenxi_uh_1048_stable_midline_trr_regression(self):
        sample = (
            SAMPLE_ROOT
            / "songzhenxi/KSU2577/07CF2C1000 20260717/SMC/HT/"
            "UH_750V_1048A_000.tss"
        )
        if not sample.is_file():
            self.skipTest("songzhenxi UH 1048A TSS 样本缺失")

        bundle = load_waveform(sample)
        profile = guess_profile_from_path(str(sample))
        result = extract_all(bundle, profile, load_config())
        self.assertIsNotNone(result.segments)
        assert result.segments is not None
        segs = result.segments
        irr = bundle_reverse_recovery_current(bundle, profile)
        marker = default_irr_trr_measure(
            bundle.t,
            irr,
            segs.reverse_recovery[0],
            segs.reverse_recovery[1],
            segs.pulse2_on,
            segs.turn_on[0],
            segs.turn_on[1],
            pulse2_off=segs.pulse2_off,
        )

        self.assertIsNotNone(marker)
        assert marker is not None
        self.assertAlmostEqual(marker.ta_s * 1e6, 19.165671, delta=0.002)
        self.assertAlmostEqual(marker.tb_s * 1e6, 19.229842, delta=0.002)
        self.assertAlmostEqual(marker.trr_ns, 64.170834, delta=0.02)
        self.assertAlmostEqual(marker.stable_level, 16.0, delta=0.02)
        self.assertAlmostEqual(marker.ha, 16.0, delta=0.02)
        self.assertAlmostEqual(marker.hb, 286.0625, delta=0.02)
        self.assertAlmostEqual(marker.irr, 286.0625, delta=0.02)
        self.assertAlmostEqual(result.reverse_recovery.trr, marker.trr_ns, places=9)
        self.assertAlmostEqual(result.reverse_recovery.irr, 286.0625, delta=0.02)
        self.assertAlmostEqual(result.reverse_recovery.err, 14.085713, delta=0.02)

    def test_songzhenxi_sss_lt_lower_high_load_uses_recovery_lobe(self):
        sample_dir = (
            SAMPLE_ROOT
            / "songzhenxi/KSU2577/SSM1R7PB12B3DTFMMSPP25M4CF0016/SSS/LT/tss"
        )
        cases = {
            "UL-750V-1050A_000.tss": (
                70.71875,
                -60.3125,
                17.511416393,
                17.54057,
                29.153606557,
            ),
            "VL-750V-805A_000.tss": (
                81.8125,
                -35.078125,
                13.981224444,
                14.011738806,
                30.514361526,
            ),
        }
        for filename, expected in cases.items():
            sample = sample_dir / filename
            with self.subTest(sample=filename):
                if not sample.is_file():
                    self.skipTest(f"样本缺失: {sample}")
                bundle = load_waveform(sample)
                profile = guess_profile_from_path(str(sample))
                result = extract_all(bundle, profile, load_config())
                self.assertIsNotNone(result.segments)
                assert result.segments is not None
                segs = result.segments
                irr = bundle_reverse_recovery_current(bundle, profile)
                marker = default_irr_trr_measure(
                    bundle.t,
                    irr,
                    segs.reverse_recovery[0],
                    segs.reverse_recovery[1],
                    segs.pulse2_on,
                    segs.turn_on[0],
                    segs.turn_on[1],
                    pulse2_off=segs.pulse2_off,
                )

                self.assertIsNotNone(marker)
                assert marker is not None
                peak, stable, ta_us, tb_us, trr_ns = expected
                self.assertAlmostEqual(marker.hb, peak, delta=0.02)
                self.assertAlmostEqual(marker.stable_level, stable, delta=0.02)
                self.assertAlmostEqual(marker.ha, stable, delta=0.02)
                self.assertAlmostEqual(marker.ta_s * 1e6, ta_us, delta=0.002)
                self.assertAlmostEqual(marker.tb_s * 1e6, tb_us, delta=0.002)
                self.assertAlmostEqual(marker.trr_ns, trr_ns, delta=0.02)
                self.assertAlmostEqual(result.reverse_recovery.irr, peak, delta=0.02)
                self.assertAlmostEqual(
                    result.reverse_recovery.trr,
                    marker.trr_ns,
                    places=9,
                )





if __name__ == "__main__":

    unittest.main()

