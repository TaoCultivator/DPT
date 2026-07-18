from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.slopes import (
    analyze_rr_recovery_current,
    didt_rr_recovery,
    prepare_rr_didt_series,
    rr_didt_between_levels,
    rr_didt_between_prepared_levels,
    rr_didt_measurement_context,
)
from dpt_extractor.tests.sample_paths import sample_tss
from scripts.validate_tss_samples import _audit_rr_didt_context

ROOT = Path(__file__).resolve().parents[2]
UH = sample_tss("UH_750V_1050A_000.tss")
SONG_SMC_HT_WL_1048 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260506"
    / "SMC"
    / "HT"
    / "WL_750V_1048A_000.tss"
)
SONG_SMC_HT_20260717_UH_1048 = (
    ROOT
    / "示例文件"
    / "songzhenxi"
    / "KSU2577"
    / "07CF2C1000 20260717"
    / "SMC"
    / "HT"
    / "UH_750V_1048A_000.tss"
)


class TestRrDidt(unittest.TestCase):
    def _synthetic_irr(self, n: int = 2000) -> tuple[np.ndarray, np.ndarray]:
        t = np.linspace(0, 2e-6, n)
        i = np.zeros(n)
        i[:400] = 100.0
        i[400:900] = np.linspace(100.0, -120.0, 500)
        i[900:] = np.linspace(-120.0, 0.0, n - 900)
        return t, i

    def test_prepeak_forward_platform_uses_quiet_band_only_for_edge_pollution(
        self,
    ) -> None:
        """A clean broad platform stays raw; an entering edge uses its quiet band."""
        from dpt_extractor.metrics.slopes import (
            _rr_prepeak_forward_platform_band_center,
            _rr_quiet_local_platform_window,
            _rr_spike_guarded_band_center,
        )

        dt = 0.08e-9
        phase = np.linspace(0.0, 40.0 * np.pi, 5000, endpoint=False)
        clean = -960.0 + 6.0 * np.sin(phase) + 1.5 * np.sin(0.37 * phase)
        clean_broad = _rr_spike_guarded_band_center(clean)
        self.assertEqual(
            _rr_prepeak_forward_platform_band_center(clean, dt),
            clean_broad,
        )

        contaminated = clean.copy()
        contaminated[-1100:] += np.linspace(0.0, 95.0, 1100)
        quiet = _rr_quiet_local_platform_window(
            contaminated,
            dt,
            min_ns=200.0,
        )
        quiet_center = _rr_spike_guarded_band_center(quiet)
        corrected = _rr_prepeak_forward_platform_band_center(
            contaminated,
            dt,
        )
        self.assertEqual(corrected, quiet_center)
        self.assertNotEqual(
            corrected,
            _rr_spike_guarded_band_center(contaminated),
        )
        self.assertEqual(
            _rr_prepeak_forward_platform_band_center(-contaminated, dt),
            -corrected,
        )

    def test_analyze_idm_irm(self):
        t, i = self._synthetic_irr()
        idm, irm, zc = analyze_rr_recovery_current(i)
        self.assertGreater(idm, 95.0)
        self.assertLess(irm, -100.0)
        self.assertGreater(zc, 300)

    def test_idm_90_10_recovery(self):
        t, i = self._synthetic_irr()
        idm_peak = 100.0
        res = didt_rr_recovery(
            t,
            i,
            0,
            len(t) - 1,
            0.9,
            0.1,
            measure="idm",
            idm_override=0.0,
            base_override=idm_peak,
        )
        self.assertGreater(res.didt, 0.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)
        self.assertAlmostEqual(res.th_a, 0.9 * idm_peak, places=0)
        self.assertAlmostEqual(res.th_b, 0.1 * idm_peak, places=0)
        self.assertLess(res.t_pct_a_s, res.t_pct_b_s)

    def test_signed_rr_context_is_mirror_invariant_and_chronological(self) -> None:
        """探头方向相反时，90% A 仍应早于 10% B 且斜率幅值不变。"""
        from dpt_extractor.config.loader import load_config

        dt = 1e-9
        t = np.arange(2401, dtype=np.float64) * dt
        irr = np.zeros_like(t)
        irr[:800] = 100.0
        irr[800:1001] = np.linspace(100.0, -40.0, 201)
        irr[1001:1501] = np.linspace(-40.0, 0.0, 500)

        contexts = [
            rr_didt_measurement_context(
                t,
                signed_irr,
                0,
                len(t) - 1,
                dt,
                load_config(),
                0.9,
                0.1,
                rr_i0=0,
                rr_i1=len(t) - 1,
            )
            for signed_irr in (irr, -irr)
        ]
        positive, negative = contexts
        self.assertEqual(positive.polarity, 1)
        self.assertEqual(negative.polarity, -1)
        self.assertFalse(positive.used_fallback)
        self.assertFalse(negative.used_fallback)
        self.assertAlmostEqual(
            positive.crossing.didt, negative.crossing.didt, places=12
        )
        self.assertAlmostEqual(positive.forward_a, -negative.forward_a, places=12)
        self.assertAlmostEqual(positive.base_a, -negative.base_a, places=12)
        for context in contexts:
            self.assertIsNotNone(context.crossing.t_pct_a_s)
            self.assertIsNotNone(context.crossing.t_pct_b_s)
            assert context.crossing.t_pct_a_s is not None
            assert context.crossing.t_pct_b_s is not None
            self.assertLess(
                context.crossing.t_pct_a_s,
                context.crossing.t_pct_b_s,
            )

    def test_prepared_cursor_series_matches_direct_levels_for_both_modes(self) -> None:
        t, positive = self._synthetic_irr()
        for sign in (1.0, -1.0):
            current = sign * positive
            prepared = prepare_rr_didt_series(t, current, 0, len(t) - 1)
            self.assertTrue(prepared.valid)
            cases = (
                ("idm", sign * 100.0, 0.0, None),
                ("if_irm", sign * 100.0, sign * -120.0, 0.0),
            )
            for measure, forward, other, zero in cases:
                with self.subTest(sign=sign, measure=measure):
                    direct = rr_didt_between_levels(
                        t,
                        current,
                        0,
                        len(t) - 1,
                        0.9 if measure == "idm" else 0.5,
                        0.1 if measure == "idm" else 0.5,
                        measure=measure,
                        forward_a=forward,
                        base_or_reverse_a=other,
                        zero_a=zero,
                    )
                    cached = rr_didt_between_prepared_levels(
                        prepared,
                        0.9 if measure == "idm" else 0.5,
                        0.1 if measure == "idm" else 0.5,
                        measure=measure,
                        forward_a=forward,
                        base_or_reverse_a=other,
                        zero_a=zero,
                    )
                    self.assertEqual(cached, direct)

    def test_invalid_prepared_idm_does_not_invent_reverse_current(self) -> None:
        t = np.arange(8, dtype=np.float64) * 1e-9
        prepared = prepare_rr_didt_series(
            t,
            np.full(8, np.nan, dtype=np.float64),
            0,
            len(t) - 1,
        )
        self.assertFalse(prepared.valid)

        result = rr_didt_between_prepared_levels(
            prepared,
            0.9,
            0.1,
            measure="idm",
            forward_a=100.0,
            base_or_reverse_a=12.5,
        )

        self.assertEqual(result.didt, 0.0)
        self.assertIsNone(result.t_pct_a_s)
        self.assertIsNone(result.t_pct_b_s)
        self.assertEqual(result.irm, 0.0)

    def test_prepared_cursor_series_is_a_read_only_snapshot(self) -> None:
        t = np.arange(12, dtype=np.float64) * 1e-9
        current = np.linspace(20.0, -5.0, len(t), dtype=np.float64)
        expected_t = t.copy()
        expected_positive = current.copy()

        prepared = prepare_rr_didt_series(t, current, 0, len(t) - 1)
        self.assertTrue(prepared.valid)
        for values in (
            prepared.t_s,
            prepared.positive_a,
            prepared.negative_a,
        ):
            self.assertFalse(values.flags.writeable)
            with self.assertRaises(ValueError):
                values[0] = values[0]

        t[:] += 1e-6
        current[:] = 999.0
        np.testing.assert_array_equal(prepared.t_s, expected_t)
        np.testing.assert_array_equal(prepared.positive_a, expected_positive)
        np.testing.assert_array_equal(prepared.negative_a, -expected_positive)

    def test_strict_validator_accepts_both_signed_rr_polarities(self) -> None:
        from dpt_extractor.config.loader import load_config

        dt = 1e-9
        t = np.arange(2401, dtype=np.float64) * dt
        irr = np.zeros_like(t)
        irr[:800] = 100.0
        irr[800:1001] = np.linspace(100.0, -40.0, 201)
        irr[1001:1501] = np.linspace(-40.0, 0.0, 500)

        for sign in (1.0, -1.0):
            with self.subTest(sign=sign):
                signed = sign * irr
                context = rr_didt_measurement_context(
                    t,
                    signed,
                    0,
                    len(t) - 1,
                    dt,
                    load_config(),
                    0.9,
                    0.1,
                    rr_i0=750,
                    rr_i1=1600,
                    fallback_i0=750,
                    fallback_i1=1600,
                )
                problems, detail = _audit_rr_didt_context(
                    t,
                    signed,
                    context,
                    context.crossing.didt,
                    pct_a=0.9,
                    pct_b=0.1,
                    measure="idm",
                )

                self.assertEqual(problems, [], detail)
                self.assertIn(f"rr_polarity={int(sign):+d}", detail)
                self.assertIn("rr_fallback=False", detail)

    def test_strict_validator_rejects_fallback_mismatch_and_raw_miss(self) -> None:
        from dataclasses import replace

        from dpt_extractor.config.loader import load_config

        dt = 1e-9
        t = np.arange(2401, dtype=np.float64) * dt
        irr = np.zeros_like(t)
        irr[:800] = 100.0
        irr[800:1001] = np.linspace(100.0, -40.0, 201)
        irr[1001:1501] = np.linspace(-40.0, 0.0, 500)
        context = rr_didt_measurement_context(
            t,
            irr,
            0,
            len(t) - 1,
            dt,
            load_config(),
            0.9,
            0.1,
            rr_i0=750,
            rr_i1=1600,
            fallback_i0=750,
            fallback_i1=1600,
        )

        problems, _detail = _audit_rr_didt_context(
            t,
            irr + 5.0,
            replace(context, used_fallback=True),
            context.crossing.didt * 1.1,
            pct_a=0.9,
            pct_b=0.1,
            measure="idm",
        )

        joined = " | ".join(problems)
        self.assertIn("fallback", joined)
        self.assertIn("pipeline/context", joined)
        self.assertIn("原始A插值", joined)
        self.assertIn("原始B插值", joined)

    def test_custom_rr_range_preserves_a_and_b_percentage_semantics(self) -> None:
        """70→30 与 30→70 只交换用户 A/B，不得偷偷改回时间先后顺序。"""
        dt = 1e-9
        t = np.arange(2401, dtype=np.float64) * dt
        irr = np.zeros_like(t)
        irr[:800] = 100.0
        irr[800:1001] = np.linspace(100.0, -40.0, 201)
        irr[1001:1501] = np.linspace(-40.0, 0.0, 500)

        forward = rr_didt_between_levels(
            t,
            irr,
            0,
            len(t) - 1,
            0.7,
            0.3,
            measure="idm",
            forward_a=100.0,
            base_or_reverse_a=0.0,
        )
        reverse = rr_didt_between_levels(
            t,
            irr,
            0,
            len(t) - 1,
            0.3,
            0.7,
            measure="idm",
            forward_a=100.0,
            base_or_reverse_a=0.0,
        )
        self.assertEqual((forward.th_a, forward.th_b), (70.0, 30.0))
        self.assertEqual((reverse.th_a, reverse.th_b), (30.0, 70.0))
        self.assertIsNotNone(forward.t_pct_a_s)
        self.assertIsNotNone(forward.t_pct_b_s)
        self.assertIsNotNone(reverse.t_pct_a_s)
        self.assertIsNotNone(reverse.t_pct_b_s)
        assert forward.t_pct_a_s is not None and forward.t_pct_b_s is not None
        assert reverse.t_pct_a_s is not None and reverse.t_pct_b_s is not None
        self.assertLess(forward.t_pct_a_s, forward.t_pct_b_s)
        self.assertGreater(reverse.t_pct_a_s, reverse.t_pct_b_s)
        self.assertAlmostEqual(forward.t_pct_a_s, reverse.t_pct_b_s, places=15)
        self.assertAlmostEqual(forward.t_pct_b_s, reverse.t_pct_a_s, places=15)
        self.assertAlmostEqual(forward.didt, reverse.didt, places=12)

    def test_rr_context_rejects_small_spike_clusters_without_moving_main_edge(
        self,
    ) -> None:
        """平台内或恢复尾的小簇毛刺不得翻极性、抢 A 或改写平台。"""
        from dpt_extractor.config.loader import load_config

        dt = 1e-9
        t = np.arange(2401, dtype=np.float64) * dt
        clean = np.zeros_like(t)
        clean[:800] = 100.0
        clean[800:1001] = np.linspace(100.0, -40.0, 201)
        clean[1001:1501] = np.linspace(-40.0, 0.0, 500)

        def _context(values: np.ndarray):
            return rr_didt_measurement_context(
                t,
                values,
                0,
                len(t) - 1,
                dt,
                load_config(),
                0.9,
                0.1,
                rr_i0=750,
                rr_i1=1600,
                fallback_i0=750,
                fallback_i1=1600,
            )

        reference = _context(clean)
        self.assertFalse(reference.used_fallback)
        for spike_start in (600, 1800):
            for cluster_size in (1, 3, 5):
                for sign in (1.0, -1.0):
                    with self.subTest(
                        spike_start=spike_start,
                        cluster_size=cluster_size,
                        sign=sign,
                    ):
                        noisy = clean.copy()
                        noisy[
                            spike_start : spike_start + cluster_size
                        ] = 130.0
                        context = _context(sign * noisy)
                        self.assertFalse(context.used_fallback)
                        self.assertEqual(context.polarity, 1 if sign > 0 else -1)
                        self.assertAlmostEqual(
                            context.forward_a,
                            sign * reference.forward_a,
                            places=12,
                        )
                        self.assertAlmostEqual(
                            context.base_a,
                            sign * reference.base_a,
                            places=12,
                        )
                        self.assertAlmostEqual(
                            context.crossing.didt,
                            reference.crossing.didt,
                            places=12,
                        )
                        self.assertEqual(
                            context.crossing.t_pct_a_s,
                            reference.crossing.t_pct_a_s,
                        )
                        self.assertEqual(
                            context.crossing.t_pct_b_s,
                            reference.crossing.t_pct_b_s,
                        )

    def test_rr_idm_rejects_early_high_only_platform_dip(self) -> None:
        """平台短毛刺仅越过 90% 时，不得与随后真实主沿的 10% 配对。"""
        dt = 1e-9
        t = np.arange(2401, dtype=np.float64) * dt
        clean = np.zeros_like(t)
        clean[:800] = 100.0
        clean[800:1001] = np.linspace(100.0, -40.0, 201)
        clean[1001:1501] = np.linspace(-40.0, 0.0, 500)

        def _measure(values: np.ndarray, sign: float):
            return rr_didt_between_levels(
                t,
                sign * values,
                0,
                len(t) - 1,
                0.9,
                0.1,
                measure="idm",
                forward_a=sign * 100.0,
                base_or_reverse_a=0.0,
            )

        for sign in (1.0, -1.0):
            reference = _measure(clean, sign)
            for cluster_size in (1, 3, 5):
                with self.subTest(sign=sign, cluster_size=cluster_size):
                    noisy = clean.copy()
                    # 85 A crosses the 90 A level but never the 10 A level.
                    noisy[400 : 400 + cluster_size] = 85.0
                    measured = _measure(noisy, sign)
                    self.assertEqual(measured.t_pct_a_s, reference.t_pct_a_s)
                    self.assertEqual(measured.t_pct_b_s, reference.t_pct_b_s)
                    self.assertAlmostEqual(
                        measured.didt,
                        reference.didt,
                        places=12,
                    )

    def test_rr_context_repairs_nonfinite_samples_and_rejects_bad_time_axis(
        self,
    ) -> None:
        """NaN/Inf 不得传播到结果；无法修复的时间轴只能走显式 fallback。"""
        from dpt_extractor.config.loader import load_config

        dt = 1e-9
        t = np.arange(2401, dtype=np.float64) * dt
        clean = np.zeros_like(t)
        clean[:800] = 100.0
        clean[800:1001] = np.linspace(100.0, -40.0, 201)
        clean[1001:1501] = np.linspace(-40.0, 0.0, 500)

        def _context(times: np.ndarray, values: np.ndarray):
            return rr_didt_measurement_context(
                times,
                values,
                0,
                len(times) - 1,
                dt,
                load_config(),
                0.9,
                0.1,
                rr_i0=750,
                rr_i1=1600,
                fallback_i0=750,
                fallback_i1=1600,
            )

        reference = _context(t, clean)
        for kind, index in (("current_nan", 900), ("current_inf", 2200)):
            with self.subTest(kind=kind):
                values = clean.copy()
                values[index] = np.nan if kind.endswith("nan") else np.inf
                context = _context(t, values)
                self.assertFalse(context.used_fallback)
                self.assertTrue(np.isfinite(context.crossing.didt))
                self.assertAlmostEqual(
                    context.crossing.didt, reference.crossing.didt, places=12
                )
                self.assertEqual(
                    context.crossing.t_pct_a_s,
                    reference.crossing.t_pct_a_s,
                )
                self.assertEqual(
                    context.crossing.t_pct_b_s,
                    reference.crossing.t_pct_b_s,
                )

        three_sample_gap = clean.copy()
        three_sample_gap[900:903] = np.nan
        repaired_three = _context(t, three_sample_gap)
        self.assertFalse(repaired_three.used_fallback)
        self.assertAlmostEqual(
            repaired_three.crossing.didt,
            reference.crossing.didt,
            places=12,
        )

        four_sample_gap = clean.copy()
        four_sample_gap[900:904] = np.nan
        rejected_four = _context(t, four_sample_gap)
        self.assertTrue(rejected_four.used_fallback)
        self.assertEqual(rejected_four.crossing.didt, 0.0)
        self.assertIsNone(rejected_four.crossing.t_pct_a_s)
        self.assertIsNone(rejected_four.crossing.t_pct_b_s)

        # A long hole across the commutation edge cannot be treated as an
        # observed linear ramp.  It must fail closed instead of returning a
        # plausible-looking synthetic slope and A/B cursor pair.
        long_edge_gap = clean.copy()
        long_edge_gap[850:1071] = np.nan
        rejected_gap = _context(t, long_edge_gap)
        self.assertTrue(rejected_gap.used_fallback)
        self.assertEqual(rejected_gap.crossing.didt, 0.0)
        self.assertIsNone(rejected_gap.crossing.t_pct_a_s)
        self.assertIsNone(rejected_gap.crossing.t_pct_b_s)

        direct_rejected = rr_didt_between_levels(
            t,
            long_edge_gap,
            0,
            len(t) - 1,
            0.9,
            0.1,
            measure="idm",
            forward_a=100.0,
            base_or_reverse_a=0.0,
        )
        self.assertEqual(direct_rejected.didt, 0.0)
        self.assertIsNone(direct_rejected.t_pct_a_s)
        self.assertIsNone(direct_rejected.t_pct_b_s)

        bad_time = t.copy()
        bad_time[900] = np.nan
        repaired = _context(bad_time, clean)
        self.assertFalse(repaired.used_fallback)
        self.assertEqual(repaired.crossing.didt, reference.crossing.didt)
        self.assertEqual(repaired.crossing.t_pct_a_s, reference.crossing.t_pct_a_s)
        self.assertEqual(repaired.crossing.t_pct_b_s, reference.crossing.t_pct_b_s)

        non_monotonic = t.copy()
        non_monotonic[900] = non_monotonic[899]
        guarded = _context(non_monotonic, clean)
        self.assertTrue(guarded.used_fallback)
        self.assertTrue(np.isfinite(guarded.crossing.didt))
        self.assertIsNone(guarded.crossing.t_pct_a_s)
        self.assertIsNone(guarded.crossing.t_pct_b_s)

        all_invalid = _context(t, np.full_like(clean, np.nan))
        self.assertTrue(all_invalid.used_fallback)
        self.assertEqual(all_invalid.crossing.didt, 0.0)
        self.assertTrue(np.isfinite(all_invalid.forward_a))
        self.assertTrue(np.isfinite(all_invalid.base_a))

        for length in (0, 1, 2, 3):
            with self.subTest(length=length):
                short = rr_didt_measurement_context(
                    np.arange(length, dtype=np.float64) * dt,
                    np.zeros(length, dtype=np.float64),
                    0,
                    max(0, length - 1),
                    dt,
                    load_config(),
                    0.9,
                    0.1,
                )
                self.assertTrue(np.isfinite(short.crossing.didt))
                self.assertIsNone(short.crossing.t_pct_a_s)
                self.assertIsNone(short.crossing.t_pct_b_s)

    @unittest.skipUnless(
        SONG_SMC_HT_20260717_UH_1048.exists(),
        "songzhenxi 20260717 UH sample missing",
    )
    def test_pipeline_passes_custom_rr_a_b_order_without_sorting(self) -> None:
        """Pipeline/report must not silently rewrite a user 30%→70% range."""
        from unittest.mock import patch

        from dpt_extractor.config.loader import load_config
        from dpt_extractor.models.bridge_profile import (
            guess_profile_from_path,
            make_profile,
        )
        from dpt_extractor.models.channel_mapping import (
            apply_mapping,
            infer_mapping_from_bundle,
        )
        from dpt_extractor.models.slope_range import SlopeRange
        from dpt_extractor.pipeline.extract import extract_all

        bundle = load_waveform(SONG_SMC_HT_20260717_UH_1048)
        guessed = guess_profile_from_path(SONG_SMC_HT_20260717_UH_1048.name)
        profile = make_profile(guessed.phase, guessed.bridge)
        mapping = infer_mapping_from_bundle(bundle, guessed.bridge)
        if mapping is not None:
            profile = apply_mapping(profile, mapping)
        cfg = load_config()
        cfg.slope_ranges["rr_didt"] = SlopeRange(
            30.0,
            70.0,
            ic_reference="idm",
            ic_direction="rise",
        )

        with patch(
            "dpt_extractor.pipeline.extract.rr_didt_measurement_context",
            wraps=rr_didt_measurement_context,
        ) as context_spy:
            result = extract_all(bundle, profile, cfg)

        self.assertEqual(context_spy.call_count, 1)
        call = context_spy.call_args
        assert call is not None
        self.assertEqual(call.args[6:8], (0.3, 0.7))
        self.assertEqual(result.reverse_recovery.didt_range, "30%→70%")
        self.assertGreater(result.reverse_recovery.didt_irr, 0.0)

    @unittest.skipUnless(
        SONG_SMC_HT_20260717_UH_1048.exists(),
        "songzhenxi 20260717 UH sample missing",
    )
    def test_real_rr_context_is_exactly_probe_polarity_invariant(self) -> None:
        """The same recorded event must not change when the probe sign flips."""
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.metrics.iec_windows import (
            err_recovery_peak_index,
            rr_slope_window_indices,
        )
        from dpt_extractor.metrics.slopes import (
            _rr_quiet_local_platform_window,
            _rr_spike_guarded_band_center,
            _rr_spike_guarded_extreme_index,
        )
        from dpt_extractor.models.bridge_profile import (
            guess_profile_from_path,
            make_profile,
        )
        from dpt_extractor.models.channel_mapping import (
            apply_mapping,
            infer_mapping_from_bundle,
        )
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = load_waveform(SONG_SMC_HT_20260717_UH_1048)
        guessed = guess_profile_from_path(SONG_SMC_HT_20260717_UH_1048.name)
        profile = make_profile(guessed.phase, guessed.bridge)
        mapping = infer_mapping_from_bundle(bundle, guessed.bridge)
        if mapping is not None:
            profile = apply_mapping(profile, mapping)
        cfg = load_config()
        result = extract_all(bundle, profile, cfg)
        irr = bundle_reverse_recovery_current(bundle, profile)
        on0, _ = result.segments.turn_on
        rr0, rr1 = result.segments.reverse_recovery
        i0, i1 = rr_slope_window_indices(on0, rr1, len(bundle.t), bundle.dt)

        contexts = tuple(
            rr_didt_measurement_context(
                bundle.t,
                signed,
                i0,
                i1,
                bundle.dt,
                cfg,
                0.9,
                0.1,
                rr_i0=rr0,
                rr_i1=rr1,
                fallback_i0=rr0,
                fallback_i1=rr1,
            )
            for signed in (irr, -irr)
        )
        original, mirrored = contexts
        self.assertEqual((original.polarity, mirrored.polarity), (-1, 1))
        self.assertEqual(original.crossing.didt, mirrored.crossing.didt)
        self.assertEqual(original.crossing.t_pct_a_s, mirrored.crossing.t_pct_a_s)
        self.assertEqual(original.crossing.t_pct_b_s, mirrored.crossing.t_pct_b_s)
        self.assertAlmostEqual(original.forward_a, -mirrored.forward_a, places=12)
        self.assertAlmostEqual(original.base_a, -mirrored.base_a, places=12)
        self.assertAlmostEqual(original.reverse_a, -mirrored.reverse_a, places=12)

        # The lower IDM horizontal cursor is the signed centre of a quiet
        # ~200 ns sub-band selected inside the broad 0.6 us to 0.2 us
        # pre-peak source region.  The source region's right edge already
        # contains the beginning of this sample's commutation edge and must not
        # participate in the final raw max/min midpoint.
        peak_idx = rr0 + int(
            err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
        )
        peak_t = float(bundle.t[peak_idx])
        platform_i0 = int(
            np.searchsorted(bundle.t, peak_t - 0.6e-6, side="left")
        )
        platform_i1 = int(
            np.searchsorted(bundle.t, peak_t - 0.2e-6, side="right")
        )
        source_region = irr[platform_i0:platform_i1]
        stable_platform = _rr_quiet_local_platform_window(
            source_region,
            bundle.dt,
            min_ns=200.0,
        )
        guarded_min = _rr_spike_guarded_extreme_index(
            stable_platform, maximum=False
        )
        guarded_max = _rr_spike_guarded_extreme_index(
            stable_platform, maximum=True
        )
        self.assertEqual(guarded_min, int(np.argmin(stable_platform)))
        self.assertEqual(guarded_max, int(np.argmax(stable_platform)))
        expected_forward = 0.5 * (
            float(stable_platform[guarded_min])
            + float(stable_platform[guarded_max])
        )
        self.assertEqual(expected_forward, -968.0624999999999)
        self.assertEqual(original.forward_a, expected_forward)
        self.assertEqual(mirrored.forward_a, -expected_forward)

        # The upper IDM horizontal cursor uses the quiet recovery-tail band.
        # Its final value must be the spike-guarded raw max/min midpoint, not
        # the P5/P95 midpoint formerly used by the generic platform helper.
        seg = irr[i0 : i1 + 1]
        reverse_idx = _rr_spike_guarded_extreme_index(seg, maximum=True)
        tail0 = reverse_idx + max(8, int(0.30 * (len(seg) - reverse_idx)))
        tail = seg[tail0:]
        if len(tail) < 8:
            tail = seg[reverse_idx:]
        quiet_tail = _rr_quiet_local_platform_window(
            tail, bundle.dt, min_ns=200.0
        )
        expected_base = _rr_spike_guarded_band_center(quiet_tail)
        self.assertAlmostEqual(expected_base, 16.265625, places=12)
        self.assertAlmostEqual(original.base_a, expected_base, places=12)
        self.assertAlmostEqual(mirrored.base_a, -expected_base, places=12)

        # Lightweight calculation callers do not construct QMainWindow.  The
        # shared RR context must not fall into uninitialised QObject lookup when
        # `_slope_ranges` is intentionally absent.
        from dpt_extractor.gui.main_window import MainWindow

        lightweight = MainWindow.__new__(MainWindow)
        lightweight.bundle = bundle
        lightweight.result = result
        lightweight.profile = profile
        lightweight.cfg = cfg
        gui_context = lightweight._rr_didt_context(
            float(bundle.t[i0]) * 1e6,
            float(bundle.t[i1]) * 1e6,
        )
        self.assertIsNotNone(gui_context)
        assert gui_context is not None
        self.assertAlmostEqual(
            gui_context.crossing.didt,
            5.485001520939264,
            places=9,
        )

    @unittest.skipUnless(
        SONG_SMC_HT_20260717_UH_1048.exists(),
        "songzhenxi 20260717 UH sample missing",
    )
    def test_real_rr_context_rejects_long_gap_in_pre_search_platform_window(
        self,
    ) -> None:
        """The stable IDM source window before search i0 must also be audited."""
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.metrics.iec_windows import (
            err_recovery_peak_index,
            rr_slope_window_indices,
        )
        from dpt_extractor.models.bridge_profile import (
            guess_profile_from_path,
            make_profile,
        )
        from dpt_extractor.models.channel_mapping import (
            apply_mapping,
            infer_mapping_from_bundle,
        )
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = load_waveform(SONG_SMC_HT_20260717_UH_1048)
        guessed = guess_profile_from_path(SONG_SMC_HT_20260717_UH_1048.name)
        profile = make_profile(guessed.phase, guessed.bridge)
        mapping = infer_mapping_from_bundle(bundle, guessed.bridge)
        if mapping is not None:
            profile = apply_mapping(profile, mapping)
        cfg = load_config()
        result = extract_all(bundle, profile, cfg)
        irr = bundle_reverse_recovery_current(bundle, profile)
        on0, _ = result.segments.turn_on
        rr0, rr1 = result.segments.reverse_recovery
        i0, i1 = rr_slope_window_indices(on0, rr1, len(bundle.t), bundle.dt)
        peak_idx = rr0 + int(
            err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
        )
        p0 = int(
            np.searchsorted(
                bundle.t,
                float(bundle.t[peak_idx]) - 0.6e-6,
                side="left",
            )
        )
        self.assertLess(p0, i0)

        missing_platform = irr.copy()
        missing_platform[p0:i0] = np.nan
        context = rr_didt_measurement_context(
            bundle.t,
            missing_platform,
            i0,
            i1,
            bundle.dt,
            cfg,
            0.9,
            0.1,
            rr_i0=rr0,
            rr_i1=rr1,
            fallback_i0=rr0,
            fallback_i1=rr1,
        )

        self.assertTrue(context.used_fallback)
        self.assertEqual(context.crossing.didt, 0.0)
        self.assertIsNone(context.crossing.t_pct_a_s)
        self.assertIsNone(context.crossing.t_pct_b_s)

    def test_if_irm_50_50(self):
        t, i = self._synthetic_irr()
        res = didt_rr_recovery(
            t,
            i,
            0,
            len(t) - 1,
            0.5,
            0.5,
            measure="if_irm",
            ha_override=100.0,
            hb_override=-120.0,
            zero_override=0.0,
        )
        self.assertGreater(res.didt, 0.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)
        self.assertAlmostEqual(res.th_a, 50.0, places=0)
        self.assertAlmostEqual(res.th_b, -60.0, places=0)
        self.assertNotAlmostEqual(res.t_pct_a_s, res.t_pct_b_s, places=9)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_if_irm_default_ha_hb_h0_levels(self) -> None:
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = load_waveform(UH)
        profile = guess_profile_from_path(UH.name)
        result = extract_all(bundle, profile, load_config())
        irr = bundle_reverse_recovery_current(bundle, profile)
        on0, _ = result.segments.turn_on
        rr0, rr1 = result.segments.reverse_recovery
        i0, i1 = rr_slope_window_indices(on0, rr1, len(bundle.t), bundle.dt)
        context = rr_didt_measurement_context(
            bundle.t,
            irr,
            i0,
            i1,
            bundle.dt,
            load_config(),
            0.5,
            0.5,
            measure="if_irm",
            rr_i0=rr0,
            rr_i1=rr1,
        )
        self.assertLess(context.forward_a, -900.0)
        self.assertGreater(context.reverse_a, 100.0)
        self.assertIsNotNone(context.zero_a)
        assert context.zero_a is not None
        self.assertGreater(context.zero_a, 10.0)
        self.assertLess(context.zero_a, 50.0)
        res = context.crossing
        self.assertGreater(res.didt, 8.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)
        assert res.t_pct_a_s is not None and res.t_pct_b_s is not None
        self.assertLess(res.t_pct_a_s, res.t_pct_b_s)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_if_irm_50_50_inverted_channel_order(self) -> None:
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = load_waveform(UH)
        profile = guess_profile_from_path(UH.name)
        result = extract_all(bundle, profile, load_config())
        irr = bundle_reverse_recovery_current(bundle, profile)
        on0, _ = result.segments.turn_on
        _, rr1 = result.segments.reverse_recovery
        i0, i1 = rr_slope_window_indices(on0, rr1, len(bundle.t), bundle.dt)
        seg = irr[i0 : i1 + 1]
        res = didt_rr_recovery(
            bundle.t,
            irr,
            i0,
            i1,
            0.5,
            0.5,
            measure="if_irm",
            ha_override=float(np.max(seg)),
            hb_override=float(np.min(seg)),
            zero_override=-0.53,
        )
        self.assertGreater(res.didt, 1.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)
        self.assertNotAlmostEqual(res.t_pct_a_s, res.t_pct_b_s, places=9)
        self.assertLess(res.t_pct_b_s, res.t_pct_a_s)
        self.assertGreater(res.t_pct_a_s * 1e6, 18.57)
        self.assertLess(res.t_pct_a_s * 1e6, 18.635)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_rr_idm_crossings_on_recovery_slope(self):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = load_waveform(UH)
        profile = guess_profile_from_path(UH.name)
        result = extract_all(bundle, profile, load_config())
        irr = bundle_reverse_recovery_current(bundle, profile)
        on0, _ = result.segments.turn_on
        _, rr1 = result.segments.reverse_recovery
        i0, i1 = rr_slope_window_indices(on0, rr1, len(bundle.t), bundle.dt)
        seg = irr[i0 : i1 + 1]
        idm, _, _ = analyze_rr_recovery_current(seg)
        res = didt_rr_recovery(
            bundle.t,
            irr,
            i0,
            i1,
            0.9,
            0.1,
            measure="idm",
            idm_override=0.0,
            base_override=idm,
        )
        self.assertGreater(res.didt, 10.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)
        i_pk = int(np.argmax(seg))
        peak_t = float(bundle.t[i0 + i_pk])
        self.assertLess(res.t_pct_a_s, res.t_pct_b_s)
        self.assertLessEqual(res.t_pct_a_s, peak_t + 5e-8)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_rising_edge_large_negative_ha_uh(self) -> None:
        """手调 Ha≈换流谷底、Hb≈0 附近：A/B 应在示波器“上升”沿（约 18.48–18.60 µs）。"""
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = load_waveform(UH)
        profile = guess_profile_from_path(UH.name)
        result = extract_all(bundle, profile, load_config())
        irr = bundle_reverse_recovery_current(bundle, profile)
        on0, _ = result.segments.turn_on
        _, rr1 = result.segments.reverse_recovery
        i0, i1 = rr_slope_window_indices(on0, rr1, len(bundle.t), bundle.dt)
        res = didt_rr_recovery(
            bundle.t,
            irr,
            i0,
            i1,
            0.9,
            0.1,
            measure="idm",
            ha_override=-948.0,
            hb_override=29.71,
        )
        self.assertGreater(res.didt, 1.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)
        self.assertLess(res.t_pct_b_s, res.t_pct_a_s)
        self.assertGreater(res.t_pct_b_s * 1e6, 18.44)
        self.assertLess(res.t_pct_a_s * 1e6, 18.65)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_manual_hb_irm_span_uh(self) -> None:
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = load_waveform(UH)
        profile = guess_profile_from_path(UH.name)
        result = extract_all(bundle, profile, load_config())
        irr = bundle_reverse_recovery_current(bundle, profile)
        on0, _ = result.segments.turn_on
        _, rr1 = result.segments.reverse_recovery
        i0, i1 = rr_slope_window_indices(on0, rr1, len(bundle.t), bundle.dt)
        _, irm, _ = analyze_rr_recovery_current(irr[i0 : i1 + 1])
        res = didt_rr_recovery(
            bundle.t,
            irr,
            i0,
            i1,
            0.9,
            0.1,
            measure="idm",
            idm_override=0.0,
            base_override=float(irm),
        )
        self.assertGreater(res.didt, 10.0)
        self.assertIsNotNone(res.t_pct_a_s)
        self.assertIsNotNone(res.t_pct_b_s)

    @unittest.skipUnless(
        SONG_SMC_HT_WL_1048.exists(), "songzhenxi SMC HT WL 1048A sample missing"
    )
    def test_wl_rr_didt_ha_uses_tail_stable_band_center(self) -> None:
        """IDM Ha 是恢复后稳定带中点，Hb 是换流前带符号平台。"""
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.metrics.slopes import (
            _rr_quiet_local_platform_band_center,
        )
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = load_waveform(SONG_SMC_HT_WL_1048)
        profile = guess_profile_from_path(str(SONG_SMC_HT_WL_1048))
        result = extract_all(bundle, profile, load_config())
        mw = MainWindow.__new__(MainWindow)
        mw.bundle = bundle
        mw.profile = profile
        irr = bundle_reverse_recovery_current(bundle, profile)
        on0, _ = result.segments.turn_on
        _, rr1 = result.segments.reverse_recovery
        i0, i1 = rr_slope_window_indices(on0, rr1, len(bundle.t), bundle.dt)
        seg = irr[i0 : i1 + 1]

        ha, hb = mw._default_rr_didt_ha_hb(seg, "idm")
        ipk_if = int(np.argmax(seg))
        tail0 = ipk_if + max(8, int(0.30 * (len(seg) - ipk_if)))
        tail = seg[tail0:]
        if len(tail) < 8:
            tail = seg[ipk_if:]
        expected = float(
            _rr_quiet_local_platform_band_center(
                tail, bundle.dt, min_ns=200.0
            )
        )

        self.assertAlmostEqual(ha, expected, delta=0.5)
        self.assertLess(abs(ha), 8.0)
        self.assertLess(hb, -900.0)


if __name__ == "__main__":
    unittest.main()
