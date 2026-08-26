from __future__ import annotations

import unittest
from pathlib import Path
import sys
import tempfile

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import guess_profile_from_path
from dpt_extractor.models.channel_mapping import apply_mapping, infer_best_mapping_from_bundle
from dpt_extractor.pipeline.extract import extract_all


SAMPLE = (
    Path("示例文件")
    / "liyawei"
    / "PCU2682"
    / "AP_UH_880V_35A_RT_000.tss"
)


class TestLiyaweiRemoteScopeSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(sys.argv)

    @unittest.skipUnless(SAMPLE.exists(), "liyawei remote-scope sample missing")
    def test_four_channel_direct_current_keeps_supported_metrics_available(self) -> None:
        bundle = load_waveform(SAMPLE)
        base_profile = guess_profile_from_path(str(SAMPLE))
        mapping, source = infer_best_mapping_from_bundle(bundle, base_profile.bridge)

        self.assertEqual(bundle.meta.channel_labels, {})
        self.assertEqual(bundle.meta.channel_vdiv, {"CH1": 3.2, "CH2": 140.0, "CH3": 140.0, "CH4": 10.0})
        self.assertEqual(source, "trend")
        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(
            (mapping.vge, mapping.vce, mapping.ic, mapping.v_diode),
            ("CH1", "CH2", "CH4", "CH3"),
        )
        self.assertEqual((mapping.il, mapping.irr, mapping.vge_other), ("", "", ""))
        self.assertFalse(mapping.ic_from_sum_irr_il)
        self.assertFalse(mapping.irr_from_ic_minus_il)

        result = extract_all(bundle, apply_mapping(base_profile, mapping), load_config())

        self.assertEqual(result.detected_pulse_count, 2)
        self.assertFalse(result.single_pulse_mode)
        self.assertGreater(result.vdc, 800.0)
        self.assertGreater(result.idc, 30.0)
        self.assertGreater(result.turn_off.eoff, 0.0)
        self.assertGreater(result.turn_on.eon, 0.0)
        self.assertFalse(result.is_metric_unavailable("关断过程", "Eoff"))
        self.assertFalse(result.is_metric_unavailable("开通", "Eon"))
        self.assertFalse(result.is_metric_unavailable("反向恢复", "Vrr"))
        self.assertFalse(result.is_metric_unavailable("反向恢复", "dv/dt"))
        self.assertTrue(result.is_metric_unavailable("关断过程", "串扰电压"))
        self.assertTrue(result.is_metric_unavailable("开通", "串扰电压"))
        self.assertTrue(result.is_metric_unavailable("反向恢复", "Irr"))
        self.assertTrue(result.is_metric_unavailable("反向恢复", "Trr"))
        self.assertTrue(result.is_metric_unavailable("反向恢复", "Err"))

    @unittest.skipUnless(SAMPLE.exists(), "liyawei remote-scope sample missing")
    def test_mapping_dialog_opens_with_direct_current_roles(self) -> None:
        from dpt_extractor.gui.channel_mapping_dialog import ChannelMappingDialog
        from dpt_extractor.models.channel_mapping import ChannelMappingStore

        bundle = load_waveform(SAMPLE)
        with tempfile.TemporaryDirectory() as tmp:
            dialog = ChannelMappingDialog(
                phase="U",
                bridge="upper",
                bundle=bundle,
                store=ChannelMappingStore(Path(tmp) / "maps.yaml"),
            )
            try:
                self.assertEqual(dialog._combos["vge"].currentData(), "CH1")
                self.assertEqual(dialog._combos["vce"].currentData(), "CH2")
                self.assertEqual(dialog._combos["ic"].currentData(), "CH4")
                self.assertEqual(dialog._combos["v_diode"].currentData(), "CH3")
                self.assertEqual(dialog._combos["il"].currentData(), "")
                self.assertEqual(dialog._combos["irr"].currentData(), "")
                self.assertEqual(dialog._combos["vge_other"].currentData(), "")
                self.assertFalse(dialog._ic_sum_cb.isChecked())
                self.assertFalse(dialog._irr_diff_cb.isChecked())
            finally:
                dialog.close()


if __name__ == "__main__":
    unittest.main()
