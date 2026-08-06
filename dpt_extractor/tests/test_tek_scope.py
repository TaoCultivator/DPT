from __future__ import annotations

import json
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.gui.waveform_plot import WaveformPlot
from dpt_extractor.io.tek_scope import (
    ScopeIdentity,
    ScopeViewState,
    _decode_ieee_block,
    _parse_scope_label,
    _waveform_dtype,
    discover_tektronix_scope,
    read_tektronix_scope,
    sync_tektronix_scope,
)


def _ieee_block(payload: bytes) -> bytes:
    size = str(len(payload)).encode("ascii")
    return b"#" + str(len(size)).encode("ascii") + size + payload + b"\n"


class TekScopeIOTests(unittest.TestCase):
    def test_bridge_requests_full_record_before_reading_preamble(self) -> None:
        bridge = (
            Path(__file__).parents[1] / "io" / "tek_scope_bridge.ps1"
        ).read_text(encoding="utf-8")
        state_query = bridge.index(
            "$acquisitionState = [int](Invoke-Query $session 'ACQUIRE:STATE?')"
        )
        freeze = bridge.index(
            "Write-Command $session 'ACQUIRE:STATE STOP'",
            state_query,
        )
        source_loop = bridge.index("for ($index = 0; $index -lt $sources.Count; $index++)")
        start = bridge.index("Write-Command $session 'DATA:START 1'", source_loop)
        stop = bridge.index('Write-Command $session "DATA:STOP $recordLength"', start)
        preamble = bridge.index(
            "$points = [long](Invoke-Query $session 'WFMOUTPRE:NR_PT?')",
            stop,
        )
        curve = bridge.index("Write-Command $session 'CURVE?'", preamble)
        self.assertLess(start, stop)
        self.assertLess(stop, preamble)
        self.assertLess(preamble, curve)
        self.assertLess(state_query, freeze)
        self.assertLess(freeze, source_loop)
        self.assertIn("Write-Command $session 'DATA:RESAMPLE 1'", bridge)
        self.assertIn("Get-DisplayedSources $session $availableSources", bridge)
        self.assertIn("Read-IeeeBinaryBlock $session", bridge)
        self.assertNotIn("$points * $item.byte_width + 64", bridge)
        self.assertIn("DATA:ENCDG SFPBINARY", bridge)
        self.assertIn("DATA:ENCDG SRIBINARY", bridge)
        self.assertIn("if ($resumeAcquisition)", bridge)
        self.assertIn("Write-Command $session 'ACQUIRE:STATE 1'", bridge)
        self.assertNotIn("throw 'SCOPE_RUNNING'", bridge)
        scope_io = (
            Path(__file__).parents[1] / "io" / "tek_scope.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("请先在示波器上按 Stop", scope_io)

    def test_scope_sync_uses_zoom_without_changing_main_timebase(self) -> None:
        bridge = (
            Path(__file__).parents[1] / "io" / "tek_scope_bridge.ps1"
        ).read_text(encoding="utf-8")
        sync_start = bridge.index("function Sync-Scope")
        sync_end = bridge.index("$manager = $null", sync_start)
        sync = bridge[sync_start:sync_end]
        win_scale = sync.index("$zoom`:HORIZONTAL:WINSCALE")
        position = sync.index("$zoom`:HORIZONTAL:POSITION", win_scale)
        state_on = sync.index("$zoom`:STATE ON", position)
        self.assertLess(win_scale, position)
        self.assertLess(position, state_on)
        self.assertIn('Write-Command $session "$zoom`:STATE OFF"', sync)
        self.assertIn("Oscilloscope did not disable the Zoom1 view", sync)
        self.assertNotIn("Write-Command $session 'HORIZONTAL:DELAY:MODE ON'", sync)
        self.assertNotIn('Write-Command $session ("HORIZONTAL:MODE:SCALE', sync)
        self.assertNotIn('Write-Command $session ("HORIZONTAL:DELAY:TIME', sync)

    def test_ieee_block_and_waveform_dtype(self) -> None:
        payload = struct.pack("<hhh", -2, 0, 3)
        self.assertEqual(_decode_ieee_block(_ieee_block(payload)), payload)
        values = np.frombuffer(payload, dtype=_waveform_dtype(2, "RI", "LSB"))
        np.testing.assert_array_equal(values, np.array([-2, 0, 3], dtype=np.int16))

    def test_scope_label_uses_only_visible_label_field(self) -> None:
        self.assertEqual(
            _parse_scope_label('H-Vge";"";14;"Frutiger LT Std 55 Roman"'),
            "H-Vge",
        )

    @patch("dpt_extractor.io.tek_scope._run_bridge")
    def test_discover_returns_tektronix_identity(self, run_bridge) -> None:
        run_bridge.return_value = {
            "resource": "USB0::0x0699::0x0527::C078514::INSTR",
            "idn": "TEKTRONIX,MSO46B,C078514,FW",
        }
        identity = discover_tektronix_scope()
        self.assertEqual(
            identity,
            ScopeIdentity(
                resource="USB0::0x0699::0x0527::C078514::INSTR",
                idn="TEKTRONIX,MSO46B,C078514,FW",
            ),
        )

    @patch("dpt_extractor.io.tek_scope._run_bridge")
    def test_read_scope_builds_standard_waveform_bundle(self, run_bridge) -> None:
        payload = struct.pack("<hhh", -2, 0, 3)

        def fake_bridge(_operation: str, **kwargs):
            output = Path(kwargs["output_path"])
            (output / "CH1.bin").write_bytes(_ieee_block(payload))
            return {
                "resource": "USB0::0x0699::0x0527::C078514::INSTR",
                "idn": "TEKTRONIX,MSO46B,C078514,FW",
                "horizontal_scale": "1e-6",
                "horizontal_position": "10.2",
                "horizontal_delay": "0",
                "record_length": 3,
                "sources": [
                    {
                        "source": "CH1",
                        "file": "CH1.bin",
                        "points": 3,
                        "x_increment": 1e-6,
                        "x_zero": -1e-6,
                        "point_offset": 0,
                        "y_multiplier": 0.5,
                        "y_zero": 1.0,
                        "y_offset": 0.0,
                        "byte_width": 2,
                        "binary_format": "RI",
                        "byte_order": "LSB",
                        "unit": "V",
                        "label": 'H-Vge";"";14;"Font"',
                        "scale": "5",
                        "position": "-0.6",
                        "formula": None,
                        "inverted": False,
                    }
                ],
            }

        run_bridge.side_effect = fake_bridge
        bundle = read_tektronix_scope()
        np.testing.assert_allclose(bundle.t, [-1e-6, 0.0, 1e-6])
        np.testing.assert_allclose(bundle.channels["CH1"], [0.0, 1.0, 2.5])
        self.assertEqual(bundle.meta.source_kind, "scope")
        self.assertEqual(bundle.meta.source_path, "scope://C078514")
        self.assertEqual(bundle.meta.channel_labels["CH1"], "H-Vge")
        self.assertEqual(bundle.meta.channel_units["CH1"], "V")
        self.assertEqual(bundle.meta.channel_vdiv["CH1"], 5.0)

    @patch("dpt_extractor.io.tek_scope._run_bridge")
    def test_read_scope_rejects_partial_record(self, run_bridge) -> None:
        payload = struct.pack("<hh", -2, 3)

        def fake_bridge(_operation: str, **kwargs):
            output = Path(kwargs["output_path"])
            (output / "CH1.bin").write_bytes(_ieee_block(payload))
            return {
                "resource": "USB0::SCOPE",
                "idn": "TEKTRONIX,MSO46B,C078514,FW",
                "record_length": 3,
                "sources": [
                    {
                        "source": "CH1",
                        "file": "CH1.bin",
                        "points": 2,
                        "x_increment": 1e-9,
                        "x_zero": 0.0,
                        "point_offset": 0.0,
                        "y_multiplier": 1.0,
                        "y_zero": 0.0,
                        "y_offset": 0.0,
                        "byte_width": 2,
                        "binary_format": "RI",
                        "byte_order": "LSB",
                        "unit": "V",
                        "label": "CH1",
                        "scale": "1",
                        "position": "0",
                        "formula": None,
                        "inverted": False,
                    }
                ],
            }

        run_bridge.side_effect = fake_bridge
        with self.assertRaisesRegex(RuntimeError, "记录长度 3.*实际读取 2 点"):
            read_tektronix_scope()

    @patch("dpt_extractor.io.tek_scope._run_bridge")
    def test_sync_serializes_one_complete_view_and_cursor_state(self, run_bridge) -> None:
        captured: dict[str, object] = {}

        def fake_bridge(operation: str, **kwargs):
            captured["operation"] = operation
            captured["resource"] = kwargs["resource"]
            captured["state"] = json.loads(
                Path(kwargs["state_path"]).read_text(encoding="utf-8")
            )
            return {"synced": True}

        run_bridge.side_effect = fake_bridge
        sync_result = sync_tektronix_scope(
            "USB::SCOPE",
            ScopeViewState(
                x_start_s=-2e-6,
                x_stop_s=8e-6,
                record_start_s=-12e-6,
                record_stop_s=28e-6,
                cursor_a_s=1e-6,
                cursor_b_s=3e-6,
                source_a="CH1",
                source_b="-MATH1",
                level_a=-4.0,
                level_b=12.5,
            ),
        )
        self.assertEqual(captured["operation"], "sync")
        self.assertEqual(sync_result, {"synced": True})
        self.assertEqual(captured["resource"], "USB::SCOPE")
        self.assertEqual(
            captured["state"],
            {
                "x_start_s": -2e-6,
                "x_stop_s": 8e-6,
                "record_start_s": -12e-6,
                "record_stop_s": 28e-6,
                "cursor_a_s": 1e-6,
                "cursor_b_s": 3e-6,
                "source_a": "CH1",
                "source_b": "MATH1",
                "level_a": -4.0,
                "level_b": 12.5,
                "zoom_enabled": True,
                "sync_cursors": True,
            },
        )

    @patch("dpt_extractor.io.tek_scope._run_bridge")
    def test_sync_serializes_zoom_disabled_view(self, run_bridge) -> None:
        captured: dict[str, object] = {}

        def fake_bridge(operation: str, **kwargs):
            captured.update(
                json.loads(Path(kwargs["state_path"]).read_text(encoding="utf-8"))
            )
            return {"synced": True}

        run_bridge.side_effect = fake_bridge
        sync_tektronix_scope(
            "USB::SCOPE",
            ScopeViewState(
                x_start_s=-12e-6,
                x_stop_s=28e-6,
                record_start_s=-12e-6,
                record_stop_s=28e-6,
                zoom_enabled=False,
                sync_cursors=False,
            ),
        )
        self.assertIs(captured["zoom_enabled"], False)
        self.assertIs(captured["sync_cursors"], False)


class _Line:
    def __init__(self, value: float, *, visible: bool = True) -> None:
        self._value = value
        self._visible = visible

    def value(self) -> float:
        return self._value

    def isVisible(self) -> bool:
        return self._visible


class ScopeInteractionTests(unittest.TestCase):
    def test_plot_view_snapshot_is_available_without_parameter_cursors(self) -> None:
        class FakePlot:
            @staticmethod
            def scope_cursor_snapshot():
                return None

            @staticmethod
            def _current_x_window_for_display():
                return -12.0, 28.0

        snapshot = WaveformPlot.scope_view_snapshot(FakePlot())
        assert snapshot is not None
        self.assertEqual(snapshot["x_start_s"], -12e-6)
        self.assertEqual(snapshot["x_stop_s"], 28e-6)
        self.assertIsNone(snapshot["cursor_a_s"])
        self.assertIsNone(snapshot["source_a"])
        self.assertIs(snapshot["sync_cursors"], False)

    @patch("dpt_extractor.gui.main_window._ScopeSyncTask")
    def test_full_view_request_builds_zoom_disabled_scope_task(self, task_type) -> None:
        class FakeWavePlot:
            @staticmethod
            def scope_view_snapshot():
                return {
                    "x_start_s": -12e-6,
                    "x_stop_s": 28e-6,
                    "cursor_a_s": None,
                    "cursor_b_s": None,
                    "source_a": None,
                    "source_b": None,
                    "level_a": None,
                    "level_b": None,
                    "sync_cursors": False,
                }

            @staticmethod
            def scope_cursor_snapshot():
                raise AssertionError("explicit view sync must not require parameter cursors")

        pool = SimpleNamespace(start=lambda _task: None)
        status_bar = SimpleNamespace(showMessage=lambda _message: None)
        window = SimpleNamespace(
            bundle=SimpleNamespace(
                t=np.array([-12e-6, 28e-6]),
                meta=SimpleNamespace(
                    source_kind="scope",
                    instrument_resource="USB::SCOPE",
                ),
            ),
            wave_plot=FakeWavePlot(),
            _scope_sync_request_id=0,
            _scope_sync_tasks={},
            _scope_io_pool=pool,
            _on_scope_sync_finished=lambda _request_id: None,
            _on_scope_sync_failed=lambda _request_id, _message: None,
            statusBar=lambda: status_bar,
        )

        MainWindow._start_scope_sync_from_plot(window, False)

        state = task_type.call_args.args[2]
        self.assertIs(state.zoom_enabled, False)
        self.assertIs(state.sync_cursors, False)

    def test_plot_snapshot_uses_current_window_and_physical_sources(self) -> None:
        class FakePlot:
            _interactive_mode = "interval"
            _cursor_a = _Line(1.25)
            _cursor_b = _Line(2.75)
            _h_cursor_a = _Line(3.0)
            _h_cursor_b = _Line(6.0)
            _disp_scale = {"CH1": 5.0, "CH2": 100.0}
            _disp_offset = {"CH1": 1.0, "CH2": -1.0}

            @staticmethod
            def _current_x_window_for_display():
                return -2.0, 8.0

            @staticmethod
            def _horizontal_cursor_binding(which: str):
                return ("vge" if which == "ha" else "vce"), True

            @staticmethod
            def _display_key_for_channel(channel: str):
                return {"vge": "CH1", "vce": "CH2"}[channel]

        snapshot = WaveformPlot.scope_cursor_snapshot(FakePlot())
        assert snapshot is not None
        self.assertEqual(snapshot["x_start_s"], -2e-6)
        self.assertEqual(snapshot["x_stop_s"], 8e-6)
        self.assertAlmostEqual(float(snapshot["cursor_a_s"]), 1.25e-6)
        self.assertAlmostEqual(float(snapshot["cursor_b_s"]), 2.75e-6)
        self.assertEqual(snapshot["source_a"], "CH1")
        self.assertEqual(snapshot["source_b"], "CH2")
        self.assertEqual(snapshot["level_a"], 10.0)
        self.assertEqual(snapshot["level_b"], 700.0)

    @patch("dpt_extractor.gui.main_window.QTimer.singleShot")
    def test_real_parameter_click_schedules_exactly_one_scope_sync(self, single_shot) -> None:
        calls: list[tuple[str, str]] = []

        class FakeWindow:
            _start_scope_sync_from_plot = object()

            @staticmethod
            def _on_value_clicked(section: str, name: str) -> None:
                calls.append((section, name))

            @staticmethod
            def _metric_unavailable(_section: str, _name: str) -> bool:
                return False

        window = FakeWindow()
        MainWindow._on_result_value_clicked(window, "开通", "Eon")
        self.assertEqual(calls, [("开通", "Eon")])
        single_shot.assert_called_once_with(0, window._start_scope_sync_from_plot)


if __name__ == "__main__":
    unittest.main()
