from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.metrics.slopes import analyze_rr_recovery_current, didt_rr_recovery

ROOT = Path(__file__).resolve().parents[2]
UH = ROOT / "UH_750V_1050A_000_ALL.csv"


class TestRrDidt(unittest.TestCase):
    def _synthetic_irr(self, n: int = 2000) -> tuple[np.ndarray, np.ndarray]:
        t = np.linspace(0, 2e-6, n)
        i = np.zeros(n)
        i[:400] = 100.0
        i[400:900] = np.linspace(100.0, -120.0, 500)
        i[900:] = np.linspace(-120.0, 0.0, n - 900)
        return t, i

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
        from dpt_extractor.gui.main_window import MainWindow
        from dpt_extractor.io.tek_parser import TekParser
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = TekParser().parse(UH)
        profile = guess_profile_from_path(UH.name)
        result = extract_all(bundle, profile, load_config())
        mw = MainWindow.__new__(MainWindow)
        mw.bundle = bundle
        mw.profile = profile
        irr = bundle_reverse_recovery_current(bundle, profile)
        on0, _ = result.segments.turn_on
        _, rr1 = result.segments.reverse_recovery
        i0, i1 = rr_slope_window_indices(on0, rr1, len(bundle.t), bundle.dt)
        seg = irr[i0 : i1 + 1]
        ha, hb = mw._default_rr_didt_ha_hb(seg, "if_irm")
        t0 = float(bundle.t[i0] * 1e6)
        t1 = float(bundle.t[i1] * 1e6)
        h0 = mw._default_didt_zero_a("反向恢复", t0, t1)
        self.assertGreater(ha, 100.0)
        self.assertLess(hb, -900.0)
        self.assertGreater(h0, 10.0)
        self.assertLess(h0, 50.0)
        res = didt_rr_recovery(
            bundle.t,
            irr,
            i0,
            i1,
            0.5,
            0.5,
            measure="if_irm",
            ha_override=ha,
            hb_override=hb,
            zero_override=h0,
        )
        self.assertGreater(res.didt, 8.0)
        self.assertLess(res.t_pct_b_s, res.t_pct_a_s)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_if_irm_50_50_inverted_channel_order(self) -> None:
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.io.tek_parser import TekParser
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = TekParser().parse(UH)
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
        self.assertGreater(res.t_pct_a_s * 1e6, 18.60)
        self.assertLess(res.t_pct_a_s * 1e6, 18.635)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_uh_rr_idm_crossings_on_recovery_slope(self):
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.io.tek_parser import TekParser
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = TekParser().parse(UH)
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
        from dpt_extractor.io.tek_parser import TekParser
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = TekParser().parse(UH)
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
        self.assertGreater(res.t_pct_b_s * 1e6, 18.47)
        self.assertLess(res.t_pct_a_s * 1e6, 18.65)

    @unittest.skipUnless(UH.exists(), "UH sample missing")
    def test_manual_hb_irm_span_uh(self) -> None:
        from dpt_extractor.config.loader import load_config
        from dpt_extractor.io.tek_parser import TekParser
        from dpt_extractor.metrics.iec_windows import rr_slope_window_indices
        from dpt_extractor.models.bridge_profile import guess_profile_from_path
        from dpt_extractor.models.waveform import bundle_reverse_recovery_current
        from dpt_extractor.pipeline.extract import extract_all

        bundle = TekParser().parse(UH)
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


if __name__ == "__main__":
    unittest.main()
