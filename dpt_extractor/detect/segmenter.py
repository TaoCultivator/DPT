from __future__ import annotations

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.detect.pulse_detector import PulseEdges
from dpt_extractor.models.results import SegmentIndices


class Segmenter:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg

    def build(
        self,
        edges: PulseEdges,
        n: int,
        dt: float,
        irr: np.ndarray | None = None,
        ic: np.ndarray | None = None,
        vce: np.ndarray | None = None,
    ) -> SegmentIndices:
        seg = self.cfg.segments
        p1w = max(10, edges.pulse1_off - edges.pulse1_on)
        if edges.single_pulse:
            gap12 = 10
        else:
            gap12 = max(10, edges.pulse2_on - edges.pulse1_off)
        p2w = max(10, edges.pulse2_off - edges.pulse2_on)

        pre_off = max(
            int(seg.turn_off_pre_ns * 1e-9 / dt),
            int(0.05 * p1w),
        )
        pre_off = min(pre_off, int(3.0e-6 / dt))
        post_off = max(
            int(seg.turn_off_post_ns * 1e-9 / dt),
            int(0.01 * p1w),
        )
        post_off = min(post_off, int(1.5e-6 / dt))

        pre_on = max(
            int(seg.turn_on_pre_ns * 1e-9 / dt),
            int(0.05 * gap12),
        )
        pre_on = min(pre_on, int(1.5e-6 / dt))
        post_on = max(
            int(seg.turn_on_post_ns * 1e-9 / dt),
            int(0.12 * max(p2w, gap12)),
        )
        post_on = min(post_on, int(2.5e-6 / dt))

        off0 = max(0, edges.pulse1_off - pre_off)
        off1 = min(n, edges.pulse1_off + post_off)

        # 慢栅/短脉冲工况：pulse1_off（栅极电气关断）可能远晚于实际 Vce 抬升，
        # 固定比例回看不足以覆盖开关沿。用 Vce 锚定真实抬升脚，必要时把窗口前沿前移，
        # 并保证抬升前留有足够导通态铺垫（首 1/5 窗启发式依赖此点）。
        rise_start = self._turn_off_rise_start(vce, edges.pulse1_on, edges.pulse1_off)
        if rise_start is not None:
            lead_in = max(pre_off, int(0.3e-6 / dt))
            off0 = max(0, min(off0, rise_start - lead_in))
            off0 = max(off0, edges.pulse1_on)

        if edges.single_pulse:
            on0 = min(n - 2, max(0, off1))
            on1 = min(n, on0 + max(10, int(50e-9 / dt)))
        else:
            on0 = max(0, edges.pulse2_on - pre_on)
            on1 = min(n, edges.pulse2_on + post_on)

        rr0, rr1 = on0, on1
        if irr is not None and ic is not None:
            rr0, rr1 = self._reverse_recovery_window(irr, ic, on0, on1, dt)

        return SegmentIndices(
            turn_off=(off0, off1),
            turn_on=(on0, on1),
            reverse_recovery=(rr0, rr1),
            pulse1_on=edges.pulse1_on,
            pulse1_off=edges.pulse1_off,
            pulse2_on=edges.pulse2_on,
            pulse2_off=edges.pulse2_off,
            next_pulse_on=edges.next_pulse_on,
        )

    @staticmethod
    def _turn_off_rise_start(
        vce: np.ndarray | None, p_on: int, p_off: int
    ) -> int | None:
        """关断主抬升脚索引：自 pulse1_off 反向找最后一个仍处导通态的 Vce 样本。

        必须反向搜索——[p_on, p_off] 起点是 *开通* 暂态（Vce 仍高），正向首个越阈点
        会误取开通沿；关断抬升脚在该窗末段。导通基准取中段（避开两端开关沿）。
        """
        if vce is None or p_off - p_on < 8:
            return None
        seg = np.asarray(vce[p_on:p_off], dtype=np.float64)
        L = len(seg)
        if L < 8:
            return None
        mid = seg[L // 4 : (3 * L) // 4]
        if len(mid) < 2:
            return None
        base = float(np.percentile(mid, 50))
        top = float(np.max(seg))
        span = top - base
        if span < 1e-3:
            return None
        thr = base + max(20.0, 0.1 * span)
        on_state = np.where(seg <= thr)[0]
        if len(on_state) == 0:
            return None
        return int(p_on + int(on_state[-1]))

    def _reverse_recovery_window(
        self,
        irr: np.ndarray,
        ic: np.ndarray,
        on0: int,
        on1: int,
        dt: float,
    ) -> tuple[int, int]:
        seg = irr[on0:on1]
        if len(seg) < 10:
            return on0, on1

        seg_f = seg.astype(np.float64)
        amp = max(float(np.max(seg_f)), abs(float(np.min(seg_f))), 1.0)
        # 上桥 CH3 多为正向 Irr 峰；下桥 Ic−IL 可能在开通窗后半段出现正向峰，前半段为负平台
        if float(np.max(seg_f)) >= 0.1 * amp:
            peak_local = int(np.argmax(seg_f))
            peak_val = float(seg_f[peak_local])
        else:
            peak_local = int(np.argmin(seg_f))
            peak_val = abs(float(seg_f[peak_local]))
        if peak_val < 5.0:
            return on0, on1

        irr_abs = np.abs(seg_f)
        thresh = 0.1 * peak_val
        start_local = peak_local
        for k in range(peak_local, -1, -1):
            if irr_abs[k] < 0.05 * peak_val:
                start_local = k
                break

        end_local = peak_local
        for k in range(peak_local, min(len(irr_abs), peak_local + int(400e-9 / dt))):
            if irr_abs[k] < thresh:
                end_local = k
                break
        else:
            end_local = min(len(irr_abs) - 1, peak_local + int(200e-9 / dt))

        margin = int(30e-9 / dt)
        rr0 = on0 + max(0, start_local - margin)
        rr1 = on0 + min(len(seg), end_local + margin)
        if rr1 <= rr0 + 10:
            rr1 = min(on1, rr0 + int(150e-9 / dt))
        return rr0, rr1
