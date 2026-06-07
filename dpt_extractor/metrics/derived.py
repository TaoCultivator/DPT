from __future__ import annotations

import numpy as np

from dpt_extractor.config.loader import AppConfig
from dpt_extractor.utils.signal import smooth

# 母线电压识别采用「相对平台」判据而非绝对电压带，兼容 480V/750V/任意等级。
_BUS_MIN_LEVEL = 50.0  # 低于此值视为导通/接地通道，不作母线
_BUS_FLAT_RATIO = 0.18  # IQR / |median| 小于该比例视为平台（非切换暂态）


def _channel_plateau(seg: np.ndarray) -> tuple[float, float] | None:
    """返回 (中位电平, 平整度比 IQR/|median|)；样本不足返回 None。"""
    if len(seg) < 10:
        return None
    med = float(np.median(seg))
    q1, q3 = np.percentile(seg, [25, 75])
    iqr = float(q3 - q1)
    flat_ratio = iqr / max(abs(med), 1e-6)
    return med, flat_ratio


def _select_bus_plateau(segments: list[np.ndarray | None]) -> float | None:
    """
    在若干候选通道段中选出母线平台电平。

    规则：取「高且平」的通道（中位电平 > 阈值、IQR 相对小）；
    若多个满足取电平较高者；都不够平时回退到电平较高且为正的通道。
    与电压等级无关，避免硬编码 350~600V 带。
    """
    flat_candidates: list[float] = []
    any_candidates: list[float] = []
    for seg in segments:
        if seg is None:
            continue
        res = _channel_plateau(seg)
        if res is None:
            continue
        med, flat_ratio = res
        if med <= _BUS_MIN_LEVEL:
            continue
        any_candidates.append(med)
        if flat_ratio <= _BUS_FLAT_RATIO:
            flat_candidates.append(med)
    if flat_candidates:
        return max(flat_candidates)
    if any_candidates:
        return max(any_candidates)
    return None


def bus_voltage_before_off(
    vce: np.ndarray,
    vce_other: np.ndarray | None,
    pulse_off_idx: int,
    dt: float,
    pre_ns: float = 400e-9,
    gap_ns: float = 20e-9,
) -> float | None:
    """关断前母线平台：DUT Vce 或对管 Vce 中「高且平」的那一路（上下桥接线对称）。"""
    pre0 = max(0, pulse_off_idx - int(pre_ns / dt))
    pre1 = max(pre0 + 10, pulse_off_idx - int(gap_ns / dt))
    if pre1 <= pre0:
        return None
    segs = [vce[pre0:pre1]]
    if vce_other is not None:
        segs.append(vce_other[pre0:pre1])
    return _select_bus_plateau(segs)


def bus_voltage_plateau(
    vce: np.ndarray,
    vce_other: np.ndarray | None,
    i0: int,
    i1: int,
    percentile: float = 95.0,
) -> float | None:
    """脉冲间关断平台上，取 DUT/对管通道中母线平台电平（高且平的那一路）。"""
    if i1 <= i0 + 5:
        return None
    # 先用相对平台判据锁定母线通道，再在该通道上取分位值（贴近示波器 Top 读数）
    candidates: list[float] = []
    for arr in (vce, vce_other):
        if arr is None:
            continue
        seg = arr[i0:i1]
        res = _channel_plateau(seg)
        if res is None:
            continue
        med, flat_ratio = res
        if med <= _BUS_MIN_LEVEL:
            continue
        if flat_ratio <= _BUS_FLAT_RATIO:
            candidates.append(float(np.percentile(seg, percentile)))
    if candidates:
        return max(candidates)
    # 回退：若没有足够平整的平台，用相对判据选电平
    return _select_bus_plateau(
        [vce[i0:i1], vce_other[i0:i1] if vce_other is not None else None]
    )


def measure_vdc(
    t: np.ndarray,
    vce: np.ndarray,
    vge: np.ndarray,
    ic: np.ndarray,
    i0: int,
    i1: int,
    cfg: AppConfig,
    pulse_off_idx: int | None = None,
    dt: float = 8e-11,
    vce_other: np.ndarray | None = None,
) -> float:
    """Median Vce on plateau immediately before turn-off edge."""
    if cfg.vdc_override is not None:
        return cfg.vdc_override

    if pulse_off_idx is not None:
        bus = bus_voltage_before_off(vce, vce_other, pulse_off_idx, dt)
        if bus is not None:
            return bus
        pre0 = max(0, pulse_off_idx - int(400e-9 / dt))
        pre1 = max(pre0 + 10, pulse_off_idx - int(20e-9 / dt))
        if pre1 > pre0:
            return float(np.median(vce[pre0:pre1]))

    vce_w = vce[i0:i1]
    vge_w = vge[i0:i1]
    ic_w = ic[i0:i1]
    if len(vce_w) < 20:
        return float(np.median(vce_w))

    n_pre = max(20, len(vce_w) // 5)
    return float(np.median(vce_w[:n_pre]))


def measure_idc(
    ic: np.ndarray,
    i0: int,
    i1: int,
    pulse_off_idx: int | None = None,
    dt: float = 8e-11,
) -> float:
    if pulse_off_idx is not None:
        pre0 = max(i0, pulse_off_idx - int(400e-9 / dt))
        pre1 = max(pre0 + 10, pulse_off_idx - int(20e-9 / dt))
        if pre1 > pre0:
            seg = np.abs(ic[pre0:pre1])
            hi = seg[seg > np.percentile(seg, 50)]
            if len(hi) >= 5:
                return float(np.median(hi))
            return float(np.median(seg))
    ic_w = ic[i0:i1]
    n_pre = max(10, len(ic_w) // 5)
    return float(np.median(np.abs(ic_w[:n_pre])))


def compute_crosstalk(
    vge_other: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
) -> float:
    seg = vge_other[i0:i1]
    if len(seg) < 5:
        return 0.0
    vs = smooth(seg, dt, 40.0)
    baseline = float(np.percentile(vs, 10))
    spike = float(np.max(vs) - baseline)
    return max(0.0, spike)


def crosstalk_extrema(
    vge_other: np.ndarray,
    i0: int,
    i1: int,
    dt: float,
) -> tuple[float, float]:
    """Return (vmax, vmin) of opposite gate voltage in window [i0, i1)."""
    seg = vge_other[i0:i1]
    if len(seg) == 0:
        return 0.0, 0.0
    return float(np.max(seg)), float(np.min(seg))
