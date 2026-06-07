import numpy as np


def test_decimated_display_peak_can_be_below_full_sample_peak():
    """降采样显示峰值可低于全采样峰值（Ha 应对齐显示曲线）。"""
    full = np.linspace(400.0, 800.0, 2000)
    full[1001] = 900.0
    dec = full[::20]
    assert float(np.max(dec)) < float(np.max(full))
