from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.utils.signal import smooth

MAX_PULSES = 10


@dataclass
class PulseEdges:
    """Active switching edges (semantic names kept for pipeline compatibility)."""

    pulse1_on: int
    pulse1_off: int
    pulse2_on: int
    pulse2_off: int
    off_pulse_number: int = 1
    on_pulse_number: int = 2
    detected_pulse_count: int = 2
    #: First physical gate rise after the selected turn-off pulse.  This may
    #: differ from ``pulse2_on`` when the user analyzes non-adjacent pulses.
    next_pulse_on: int | None = None
    #: True when only one gate pulse is present (turn-on / RR extraction skipped).
    single_pulse: bool = False


class PulseDetector:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg

    def detect(self, t: np.ndarray, vge: np.ndarray, dt: float) -> PulseEdges:
        pulses = self.detect_all(t, vge, dt)
        sel = self.cfg.pulse_selection
        off = min(max(1, sel.off_pulse), len(pulses))
        on = 1 if len(pulses) == 1 else min(max(1, sel.on_pulse), len(pulses))
        return self.build_edges(pulses, off, on, vge, dt)

    def detect_all(self, t: np.ndarray, vge: np.ndarray, dt: float) -> list[tuple[int, int]]:
        """Return up to ``MAX_PULSES`` gate-on intervals ``(on_idx, off_idx)``."""
        pd = self.cfg.pulse_detection
        vs = smooth(vge, dt, pd.smooth_ns)
        lo, hi = np.percentile(vs, [2, 98])
        span = hi - lo
        # A valid short gate state can occupy less than 2% of a long capture.
        # In that case the historical percentile pair collapses onto the
        # majority state and the short pulse/gap disappears before interval
        # detection.  Estimate an alternate pair from a persistence-smoothed
        # trace whose window is the configured minimum valid pulse width.  It
        # rejects isolated spikes while preserving every >=0.5us T1/T2/... state
        # with the default 0.3us validity threshold.  Keep the historical
        # percentile levels whenever they still represent the full gate swing.
        persistence_ns = max(pd.smooth_ns, pd.min_pulse_width_us * 1_000.0)
        persistent = smooth(vs, dt, persistence_ns)
        persistent_lo = float(np.min(persistent))
        persistent_hi = float(np.max(persistent))
        persistent_span = persistent_hi - persistent_lo
        if persistent_span > 1e-6 and span < 0.5 * persistent_span:
            lo, hi = persistent_lo, persistent_hi
            span = persistent_span
        if span < 1e-6:
            raise ValueError("Vge has insufficient swing for pulse detection")
        th_on = lo + pd.hysteresis_ratio * span
        th_off = lo + (pd.hysteresis_ratio * 0.5) * span

        on = np.zeros(len(vs), dtype=bool)
        state = vs[0] > th_on
        on[0] = state
        for i in range(1, len(vs)):
            if state:
                if vs[i] < th_off:
                    state = False
            else:
                if vs[i] > th_on:
                    state = True
            on[i] = state

        min_width = int(pd.min_pulse_width_us * 1e-6 / dt)
        changes = np.where(np.diff(on.astype(np.int8)) != 0)[0]
        pulses: list[tuple[int, int]] = []
        i = 0
        while i < len(changes):
            if on[changes[i] + 1]:
                start = int(changes[i] + 1)
                j = i + 1
                while j < len(changes) and on[changes[j] + 1]:
                    j += 1
                if j < len(changes):
                    end = int(changes[j] + 1)
                    if end - start >= min_width:
                        pulses.append((start, end))
                    i = j + 1
                else:
                    break
            else:
                i += 1

        if len(pulses) < 2:
            pulses = self._fallback_wide_pulses(on, min_width)

        if len(pulses) < 1:
            raise ValueError(
                "未识别到门极脉冲。请检查 Vge 通道或调整 pulse_detection 配置。"
            )

        return sorted(pulses, key=lambda p: p[0])[:MAX_PULSES]

    def build_edges(
        self,
        pulses: list[tuple[int, int]],
        off_pulse: int,
        on_pulse: int,
        vge: np.ndarray,
        dt: float,
    ) -> PulseEdges:
        """
        Map 1-based pulse indices to legacy ``pulse1_*`` / ``pulse2_*`` edge fields.

        ``off_pulse``: which pulse's turn-off to analyze.
        ``on_pulse``: which pulse's turn-on to analyze (may equal ``off_pulse``).
        """
        n = len(pulses)
        if n == 1:
            if off_pulse != 1 or on_pulse != 1:
                raise ValueError("单脉冲工况仅支持分析第 1 个门极脉冲的关断沿")
            p1_on, rough_off = pulses[0]
            p1_off = self._refine_pulse_off(vge, p1_on, rough_off, rough_off, dt)
            post = max(int(0.1e-6 / dt), 5)
            p2_off = min(len(vge) - 1, p1_off + post)
            return PulseEdges(
                pulse1_on=p1_on,
                pulse1_off=p1_off,
                pulse2_on=p1_on,
                pulse2_off=p2_off,
                off_pulse_number=1,
                on_pulse_number=1,
                detected_pulse_count=1,
                single_pulse=True,
            )

        if off_pulse < 1 or on_pulse < 1:
            raise ValueError("脉冲序号须 ≥ 1")
        if off_pulse > n:
            raise ValueError(
                f"关断取第 {off_pulse} 波，但仅识别到 {n} 个门极脉冲"
            )
        if on_pulse > n:
            raise ValueError(
                f"开通取第 {on_pulse} 波，但仅识别到 {n} 个门极脉冲"
            )
        if on_pulse < off_pulse:
            raise ValueError(
                f"开通脉冲序号 ({on_pulse}) 不能早于关断脉冲序号 ({off_pulse})"
            )

        p1_on, rough_off = pulses[off_pulse - 1]
        p2_on, p2_off = pulses[on_pulse - 1]
        next_pulse_on = pulses[off_pulse][0] if off_pulse < n else None
        if off_pulse == on_pulse:
            p1_off = self._refine_pulse_off(vge, p1_on, rough_off, rough_off, dt)
        else:
            p1_off = self._refine_pulse_off(vge, p1_on, rough_off, p2_on, dt)
        return PulseEdges(
            pulse1_on=p1_on,
            pulse1_off=p1_off,
            pulse2_on=p2_on,
            pulse2_off=p2_off,
            off_pulse_number=off_pulse,
            on_pulse_number=on_pulse,
            detected_pulse_count=n,
            next_pulse_on=next_pulse_on,
        )

    def _refine_pulse_off(
        self,
        vge: np.ndarray,
        p_on: int,
        rough_off: int,
        p2_on: int,
        dt: float,
    ) -> int:
        """Last Vge 90%->10% falling crossing between pulse on and off (or next on)."""
        search_start = max(p_on, rough_off - int(3e-6 / dt))
        search_end = min(len(vge) - 2, max(p2_on, rough_off))
        if search_end <= search_start:
            return rough_off

        seg = vge[search_start:search_end]
        hi = float(np.percentile(seg, 98))
        lo = float(np.percentile(seg, 2))
        span = hi - lo
        if span < 1e-3:
            return rough_off
        th90 = lo + 0.9 * span
        th10 = lo + 0.1 * span

        refined = rough_off
        for i in range(search_end - 1, search_start + 1, -1):
            if vge[i] < th10 and vge[i - 1] > th90:
                refined = i
                break
        return refined

    @staticmethod
    def _fallback_wide_pulses(on: np.ndarray, min_width: int) -> list[tuple[int, int]]:
        changes = np.where(np.diff(on.astype(np.int8)) != 0)[0]
        pulses = []
        for i, idx in enumerate(changes):
            if on[idx + 1]:
                start = idx + 1
                for j in range(i + 1, len(changes)):
                    if not on[changes[j] + 1]:
                        end = changes[j] + 1
                        if end - start >= min_width:
                            pulses.append((int(start), int(end)))
                        break
        return sorted(pulses, key=lambda p: p[0])
