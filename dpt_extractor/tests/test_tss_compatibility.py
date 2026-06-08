"""基准 TSS 示例波形与 UH 逻辑的一致性（重型 TSS 语料由脚本验证）。"""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.metrics.iec_windows import (
    err_energy_markers,
    err_recovery_peak_index,
    integrate_err_recovery,
)
from dpt_extractor.metrics.plateau_level import (
    turn_on_current_hb_ha_t,
    turn_on_didt_ha_at_turn_on,
    turn_on_ic_a_cross_hb_us,
    turn_on_ic_b_cross_ha_us,
)
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.waveform import (
    bundle_reverse_recovery_current,
    bundle_total_current,
)
from dpt_extractor.pipeline.extract import extract_all
from dpt_extractor.tests.sample_paths import sample_tss

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = (
    sample_tss("UH_750V_1050A_000.tss"),
    sample_tss("UL_750V_1050A_000.tss"),
    sample_tss("WH_480V_800A_000.tss"),
    sample_tss("WL_480V_800A_000.tss"),
)


class TestFourTssCompatibility(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
      cls.cfg = load_config()

  def _load(self, path: Path):
      profile = guess_profile_from_path(path.name)
      bundle = load_waveform(path)
      result = extract_all(bundle, profile, self.cfg)
      return profile, bundle, result

  def test_err_positive_and_marker_order(self) -> None:
      for path in SAMPLES:
          with self.subTest(sample=path.name):
              if not path.exists():
                  self.skipTest(f"missing {path.name}")
              profile, bundle, result = self._load(path)
              segs = result.segments
              assert segs is not None
              t = bundle.t
              irr = bundle_reverse_recovery_current(bundle, profile)
              vd = bundle.get(profile.v_diode)
              rr0, rr1 = segs.reverse_recovery
              on1 = segs.turn_on[1]
              mk = err_energy_markers(
                  t, irr, vd, rr0, rr1, bundle.dt, i_search_end=on1
              )
              # Hb=恢复前正向导通 Vd 平台(带符号，≈0)，Ha=恢复后稳定 Irr 平台(带符号)
              self.assertLess(abs(mk.hb_a), 50.0, "Hb 应在二极管正向导通电平附近")
              self.assertGreater(mk.t_start, mk.t_end, "A(Irr) 应晚于 B(Vd)")
              win = mk.as_integration_window()
              span_us = abs(float(t[win.i_end]) - float(t[win.i_start])) * 1e6
              self.assertGreater(span_us, 0.01, "Err 积分窗应足够宽")
              e = integrate_err_recovery(t, vd, irr, mk.as_integration_window())
              self.assertGreater(e, 0.2)
              self.assertAlmostEqual(
                  result.reverse_recovery.err, e, places=3
              )
              # A 应落在恢复主峰之后的下降段内（不早于主峰、不超出恢复段太远）
              ipk = rr0 + err_recovery_peak_index(irr[rr0 : rr1 + 1], bundle.dt)
              t_pk_us = float(t[ipk]) * 1e6
              self.assertGreater(mk.t_start * 1e6, t_pk_us - 0.01, "A 应在恢复主峰之后")
              self.assertLess(
                  mk.t_start * 1e6, t_pk_us + 0.30, "A 不应远离恢复段"
              )

  def test_wh_err_ab_on_waveform_crossings(self) -> None:
      """WH 软恢复：B 在段界前 Vd×Hb 抬升脚，A 在主峰后 |Irr| 下降×|Ha|。"""
      path = next(
          (p for p in SAMPLES if guess_profile_from_path(p.name).code == "WH"),
          None,
      )
      if path is None or not path.exists():
          self.skipTest("missing WH-like waveform")
      profile, bundle, result = self._load(path)
      segs = result.segments
      assert segs is not None
      t = bundle.t
      irr = bundle_reverse_recovery_current(bundle, profile)
      vd = bundle.get(profile.v_diode)
      rr0, rr1 = segs.reverse_recovery
      on1 = segs.turn_on[1]
      mk = err_energy_markers(
          t, irr, vd, rr0, rr1, bundle.dt, i_search_end=on1
      )
      ipk = rr0 + err_recovery_peak_index(
          irr[rr0 : rr1 + 1], bundle.dt
      )
      t_pk_us = float(t[ipk]) * 1e6
      tb_us = mk.t_end * 1e6
      ta_us = mk.t_start * 1e6
      self.assertLess(tb_us, t_pk_us - 0.04, "B 应在 IRM 主峰前（勿卡在 rr 段起点）")
      self.assertGreater(tb_us, t_pk_us - 0.15)
      self.assertGreater(ta_us, t_pk_us)
      self.assertLess(ta_us, t_pk_us + 0.22)
      self.assertGreater(ta_us, tb_us)

  def test_eoff_a_at_vce_rise_foot(self) -> None:
      """Eoff A 必须落在 Vce 主抬升脚（抬升后短窗内电压显著上升），
      不得卡在导通态噪声里（下桥曾因 350ns 搜索窗截断而提前 ~130ns）。"""
      from dpt_extractor.metrics.iec_windows import eoff_energy_markers

      for path in SAMPLES:
          with self.subTest(sample=path.name):
              if not path.exists():
                  self.skipTest(f"missing {path.name}")
              profile, bundle, result = self._load(path)
              segs = result.segments
              assert segs is not None
              t = bundle.t
              vce = bundle.get(profile.vce)
              ic = bundle_total_current(bundle, profile)
              mk = eoff_energy_markers(
                  t, ic, vce, segs.turn_off[0], segs.turn_off[1],
                  segs.pulse1_off, bundle.dt,
                  pre_ns=self.cfg.energy.eoff_pre_ns,
                  pulse1_on=segs.pulse1_on,
              )
              ia = int(np.searchsorted(t, mk.t_start))
              i_aft = int(np.searchsorted(t, mk.t_start + 200e-9))
              i_aft = min(i_aft, segs.turn_off[1])
              vce_a = float(vce[ia])
              vce_aft = float(np.max(vce[ia : i_aft + 1]))
              vpk = float(result.turn_off.vce_off_max)
              swing = max(vpk - mk.ha_v, 1.0)
              # A 处≈导通态(≈Ha)，且 200ns 内电压已抬升过半（排除卡在导通态平台）
              self.assertLess(vce_a, mk.ha_v + 0.12 * swing)
              self.assertGreater(
                  vce_aft, mk.ha_v + 0.5 * swing,
                  "A 未落在 Vce 主抬升脚（疑似卡在导通态平台）",
              )

  def test_turn_on_current_and_didt_ha_aligned(self) -> None:
      for path in SAMPLES:
          with self.subTest(sample=path.name):
              if not path.exists():
                  self.skipTest(f"missing {path.name}")
              profile, bundle, result = self._load(path)
              segs = result.segments
              assert segs is not None
              on0, on1 = segs.turn_on
              ic = bundle_total_current(bundle, profile)
              t = bundle.t
              dt = bundle.dt
              hb, ha = turn_on_current_hb_ha_t(t, ic, on0, on1, dt)
              ha_didt = turn_on_didt_ha_at_turn_on(t, ic, on0, on1, dt)
              self.assertAlmostEqual(ha, ha_didt, places=0)
              # Hb 为带符号导通前基线（下桥可能为负），Ha 为导通平台
              self.assertGreater(ha, 0.0)
              self.assertLess(abs(hb), abs(ha) * 0.2)
              a_us = turn_on_ic_a_cross_hb_us(t, ic, on0, on1, hb, dt)
              b_us = turn_on_ic_b_cross_ha_us(t, ic, on0, on1, ha, dt)
              self.assertGreater(b_us, a_us)
              self.assertGreater(a_us, float(t[on0]) * 1e6)
              self.assertLess(a_us, float(t[on1]) * 1e6)


class TestGuiCursorBinding(unittest.TestCase):
  """无界面驱动 GUI，逐参数校验数据光标绑定到正确波形/特征（上下桥兼容）。

  Qt 在 unittest 同进程内不易干净退出，故用独立子进程 + 超时运行审计脚本，
  既隔离 Qt 事件循环，又能在脚本非零退出时给出失败矩阵。
  """

  def test_all_parameter_cursors_bind_correct_waveform(self) -> None:
      if not any(p.exists() for p in SAMPLES):
          self.skipTest("示例波形缺失")
      try:
          import PyQt6  # noqa: F401
      except Exception:  # noqa: BLE001
          self.skipTest("PyQt6 不可用")

      import os
      import subprocess
      import sys

      script = ROOT / "scripts" / "validate_gui_cursors.py"
      env = dict(os.environ)
      env.setdefault("QT_QPA_PLATFORM", "offscreen")
      try:
          proc = subprocess.run(
              [sys.executable, str(script)],
              cwd=str(ROOT),
              env=env,
              capture_output=True,
              text=True,
              timeout=180,
          )
      except subprocess.TimeoutExpired:
          self.fail("validate_gui_cursors.py 运行超时 (>180s)")
      out = (proc.stdout or "") + (proc.stderr or "")
      self.assertEqual(
          proc.returncode, 0, f"光标审计存在 FAIL:\n{out}"
      )
