import numpy as np

from dpt_extractor.metrics.derived import crosstalk_extrema


def test_crosstalk_extrema_finds_raw_max_min():
    y = np.array([-5.0, -3.0, 12.0, -8.0, -2.0], dtype=float)
    vmax, vmin = crosstalk_extrema(y, 0, len(y), 1e-9)
    assert vmax == 12.0
    assert vmin == -8.0


def test_crosstalk_extrema_respects_sub_window():
    y = np.linspace(-2.0, 2.0, 20)
    y[10] = 15.0
    vmax, vmin = crosstalk_extrema(y, 8, 13, 1e-9)
    assert vmax == 15.0
    assert vmin == float(np.min(y[8:13]))
