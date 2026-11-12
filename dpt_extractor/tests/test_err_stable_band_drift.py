from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_windows import (
    _err_recovery_settled_base,
    _err_vd_rise_cross_hb_t,
    err_recovery_peak_index,
)
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.channel_mapping import (
    apply_mapping,
    infer_best_mapping_from_bundle,
)
from dpt_extractor.models.waveform import bundle_reverse_recovery_current
from dpt_extractor.pipeline.extract import extract_all

ZHONGBAN2 = Path(
    r"F:\JinMai\双脉冲数据处理\songzhenxi\MCU25T8\SMC\zhongban2"
)


def _extract(path: Path):
    bundle = load_waveform(path)
    base_profile = guess_profile_from_path(path)
    mapping, _source = infer_best_mapping_from_bundle(bundle, base_profile.bridge)
    profile = (
        apply_mapping(base_profile, mapping)
        if mapping is not None
        else base_profile
    )
    return bundle, profile, extract_all(bundle, profile, load_config())


def test_err_stable_band_rejects_transient_shelf(monkeypatch):
    monkeypatch.delenv("DPT_LOSS_CURSOR_MODE", raising=False)
    dt = 1e-9
    n = 1200
    irr = np.zeros(n, dtype=np.float64)
    irr[60:101] = np.linspace(0.0, 500.0, 41)
    irr[101:161] = np.linspace(500.0, 100.0, 60)
    irr[160:281] = 100.0
    irr[280:421] = np.linspace(100.0, 65.0, 141)
    irr[420:] = 65.0

    base = _err_recovery_settled_base(irr, 100, dt, 1100)

    assert base.start_idx > 300
    assert base.level < 85.0


def test_err_vd_b_crossing_respects_main_rise_floor():
    dt = 1e-9
    t = np.arange(0, 800, dtype=np.float64) * dt
    vd = np.zeros_like(t)
    vd[:51] = -1.0
    vd[50:151] = np.linspace(-1.0, 1.0, 101)
    vd[150:251] = 1.0
    vd[250:351] = np.linspace(1.0, 400.0, 101)
    vd[350:] = 400.0

    early = _err_vd_rise_cross_hb_t(t, vd, 0.0, 400, 0, dt)
    late = _err_vd_rise_cross_hb_t(
        t,
        vd,
        0.0,
        400,
        0,
        dt,
        main_rise_floor_idx=200,
    )

    assert early * 1e9 < 150.0
    assert late * 1e9 > 240.0


@pytest.mark.skipif(
    not (
        ZHONGBAN2
        / "LT"
        / "VL_486V_1050A_Rgon0.8_Rgoff5.1_000.tss"
    ).exists(),
    reason="zhongban2 1050A source sample missing",
)
def test_zhongban2_1050a_err_waits_for_late_platform():
    p1050 = (
        ZHONGBAN2
        / "LT"
        / "VL_486V_1050A_Rgon0.8_Rgoff5.1_000.tss"
    )
    p1000 = (
        ZHONGBAN2
        / "LT"
        / "VL_486V_1000A_Rgon0.8_Rgoff5.1_000.tss"
    )
    p1070 = (
        ZHONGBAN2
        / "LT"
        / "VL_486V_1070A_Rgon0.8_Rgoff5.1_000.tss"
    )
    if not (p1000.exists() and p1070.exists()):
        pytest.skip("zhongban2 neighboring current samples missing")

    bundles = []
    for path in (p1000, p1050, p1070):
        bundle, profile, result = _extract(path)
        bundles.append((bundle, profile, result))

    errs = [item[2].reverse_recovery.err for item in bundles]
    neighbor_median = float(np.median([errs[0], errs[2]]))
    assert errs[1] == pytest.approx(neighbor_median, abs=0.6)

    bundle, profile, result = bundles[1]
    marker = result.energy_contexts[("反向恢复", "Err")]
    assert result.segments is not None
    rr0, rr1 = result.segments.reverse_recovery
    irr = bundle_reverse_recovery_current(bundle, profile)
    peak_idx = int(
        rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
    )
    assert (marker.t_start - bundle.t[peak_idx]) * 1e9 > 180.0


@pytest.mark.skipif(
    not (
        ZHONGBAN2
        / "LT"
        / "VH_400V_600A_Rgon1.8_Rgoff6.8_000.tss"
    ).exists(),
    reason="zhongban2 600A source sample missing",
)
def test_zhongban2_vh_400v_600a_err_b_after_pulse2_on():
    path = (
        ZHONGBAN2
        / "LT"
        / "VH_400V_600A_Rgon1.8_Rgoff6.8_000.tss"
    )
    bundle, profile, result = _extract(path)
    assert result.segments is not None
    marker = result.energy_contexts[("反向恢复", "Err")]
    pulse2_on_t = float(bundle.t[result.segments.pulse2_on])

    assert marker.t_end >= pulse2_on_t - 1e-12
    vd = bundle.get(profile.v_diode)
    assert marker.hb_a == pytest.approx(
        float(np.interp(marker.t_end, bundle.t, vd)),
        abs=0.02,
    )
    b_idx = int(np.searchsorted(bundle.t, marker.t_end, side="left"))
    probe_idx = int(
        np.searchsorted(bundle.t, marker.t_end + 220e-9, side="right")
    )
    assert float(np.nanmax(vd[b_idx:probe_idx])) - marker.hb_a >= 25.0
