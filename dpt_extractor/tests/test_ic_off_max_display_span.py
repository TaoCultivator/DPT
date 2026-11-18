"""Ic_off_max 默认 A/B 显示区间：峰值左右各 300ns，数值口径不变。

覆盖 2026-11-18 用户拍板口径：

- 默认 A/B 是以提取峰值（`argmax(|Ic|)`，与 `ic_off_max` 同一窗）为中心、
  左右各 `300ns` 的显示取值区间，按 `dt` 取整并夹到关断窗内；
- 峰值贴边时按较小一侧等比收窄，仍然 `A < B`；
- Ic 全零或窗口退化时退回历史 Base→Base 落点，不抛异常；
- `Ic_off_max` 数值恒等于「区间内 |Ic| 最大值」，即提取峰值本身不变。
"""

from __future__ import annotations

import unittest

import numpy as np

from dpt_extractor.metrics.plateau_level import (
    IC_OFF_MAX_DISPLAY_HALF_SPAN_S,
    turn_off_ic_off_max_cursor_context,
    turn_off_ic_off_max_display_span_indices,
)


def _turn_off_waveform(dt: float = 1e-9, n: int = 2200):
    """Synthetic hard turn-off: Ic plateau -> fall, Vce Base -> Top."""

    t = np.arange(n, dtype=np.float64) * dt
    idx = np.arange(n)
    vce = np.full(n, 5.0, dtype=np.float64)
    vce[900:1001] = np.linspace(5.0, 472.0, 102)[1:]
    vce[1001:] = 472.0
    ic = np.full(n, 1000.0, dtype=np.float64)
    ic[820:901] = np.linspace(1000.0, 0.0, 82)[1:]
    ic[901:] = 0.0
    # tiny deterministic base ripple so the stable-band locators see samples
    ic[901:] = np.where(idx[901:] % 2 == 0, 0.4, -0.4)
    vce[:900] = np.where(idx[:900] % 2 == 0, 4.9, 5.1)
    return t, vce, ic


class TestIcOffMaxDisplaySpanIndices(unittest.TestCase):
    def test_helper_uses_300ns_quantized_by_dt(self) -> None:
        offset = int(round(IC_OFF_MAX_DISPLAY_HALF_SPAN_S / 8e-11))
        self.assertEqual(offset, 3750)
        self.assertEqual(
            turn_off_ic_off_max_display_span_indices(10_000, 0, 20_000, 8e-11),
            (10_000 - offset, 10_000 + offset),
        )

    def test_helper_narrows_proportionally_near_window_edge(self) -> None:
        # 峰值离右边界只有 120 个采样:两侧等比收窄到同一半径。
        a_idx, b_idx = turn_off_ic_off_max_display_span_indices(880, 0, 1000, 1e-9)
        self.assertEqual((a_idx, b_idx), (760, 1000))
        self.assertEqual(880 - a_idx, b_idx - 880)

    def test_helper_clamps_pinned_peak_and_keeps_interval_ordered(self) -> None:
        # 峰值正好落在窗口右端:按单侧夹取，仍 A < B。
        a_idx, b_idx = turn_off_ic_off_max_display_span_indices(800, 0, 800, 1e-9)
        self.assertEqual(a_idx, 500)
        self.assertEqual(b_idx, 800)
        self.assertLess(a_idx, b_idx)
        # 峰值正好落在窗口左端。
        a_idx, b_idx = turn_off_ic_off_max_display_span_indices(800, 800, 2199, 1e-9)
        self.assertEqual(a_idx, 800)
        self.assertEqual(b_idx, 1100)

    def test_helper_rejects_degenerate_windows(self) -> None:
        self.assertIsNone(turn_off_ic_off_max_display_span_indices(5, 5, 5, 1e-9))


class TestIcOffMaxCursorContext(unittest.TestCase):
    def _context(self, **kwargs):
        t, vce, ic = _turn_off_waveform()
        args = dict(
            local_start=0,
            local_end=len(t) - 1,
            pulse1_on=10,
            off_idx=900,
            fall_start=800,
            fall_end=920,
            dt=1e-9,
        )
        args.update(kwargs)
        return t, ic, turn_off_ic_off_max_cursor_context(t, vce, ic, **args)

    def test_default_interval_is_peak_centred_300ns(self) -> None:
        t, ic, context = self._context()
        a_idx, b_idx, base = context
        peak_idx = 800 + int(np.argmax(np.abs(ic[800:921])))
        self.assertEqual(a_idx, peak_idx - 300)
        self.assertEqual(b_idx, peak_idx + 300)
        self.assertAlmostEqual(float(t[a_idx] - t[peak_idx]), -300e-9, places=18)
        self.assertAlmostEqual(float(t[b_idx] - t[peak_idx]), 300e-9, places=18)
        self.assertLess(a_idx, peak_idx)
        self.assertLess(peak_idx, b_idx)
        # Hb 仍是电流 Base 稳定值（合成波形 Base=0），不随 A/B 口径改变。
        self.assertAlmostEqual(float(base), 0.0, delta=1.0)

    def test_value_is_unchanged_max_abs_ic_over_the_interval(self) -> None:
        _t, ic, context = self._context()
        a_idx, b_idx, _base = context
        extracted = float(np.max(np.abs(ic[800:921])))
        displayed = float(np.max(np.abs(ic[a_idx : b_idx + 1])))
        self.assertEqual(displayed, extracted)

    def test_peak_near_window_edge_is_clipped_and_value_preserved(self) -> None:
        t, ic, context = self._context(local_end=900)
        a_idx, b_idx, _base = context
        self.assertEqual(b_idx, 900)
        self.assertLess(a_idx, b_idx)
        self.assertLessEqual(a_idx, 800)
        self.assertLessEqual(800, b_idx)
        peak_idx = 800 + int(np.argmax(np.abs(ic[800:901])))
        self.assertLessEqual(a_idx, peak_idx)
        self.assertLessEqual(peak_idx, b_idx)
        self.assertEqual(
            float(np.max(np.abs(ic[a_idx : b_idx + 1]))),
            float(np.max(np.abs(ic[800:901]))),
        )
        self.assertGreater(float(t[b_idx]), float(t[a_idx]))

    def test_all_zero_current_falls_back_without_raising(self) -> None:
        t, vce, _ic = _turn_off_waveform()
        ic = np.zeros_like(t)
        context = turn_off_ic_off_max_cursor_context(
            t,
            vce,
            ic,
            0,
            len(t) - 1,
            10,
            900,
            800,
            920,
            1e-9,
        )
        a_idx, b_idx, base = context
        self.assertLess(a_idx, b_idx)
        self.assertTrue(np.isfinite(float(base)))


if __name__ == "__main__":
    unittest.main()