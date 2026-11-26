from __future__ import annotations

import io
import json
from pathlib import Path
import struct
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from dpt_extractor.gui.main_window import MainWindow
from dpt_extractor.gui.waveform_plot import WaveformPlot
from dpt_extractor.io.tek_scope import (
    ScopeIdentity,
    ScopeViewState,
    TekScopeError,
    _BridgeIdentityError,
    _BRIDGE_SCOPE_NOT_FOUND_RETRY_SECONDS,
    _decode_ieee_block,
    _bridge_provider_order,
    _parse_scope_label,
    _run_bridge,
    _run_bridge_once,
    _waveform_dtype,
    discover_tektronix_scope,
    read_tektronix_scope,
    shutdown_tektronix_backend,
    sync_tektronix_scope,
)


def _ieee_block(payload: bytes) -> bytes:
    size = str(len(payload)).encode("ascii")
    return b"#" + str(len(size)).encode("ascii") + size + payload + b"\n"


class _FakeBridgeProcess:
    def __init__(
        self,
        stdout: io.StringIO,
        stderr: io.StringIO,
        *,
        return_code: int | None = 0,
        release: threading.Event | None = None,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = return_code
        self.release = release
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise TimeoutError
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15
        if self.release is not None:
            self.release.set()

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        if self.release is not None:
            self.release.set()


class _BlockingTextStream(io.StringIO):
    def __init__(self, release: threading.Event) -> None:
        super().__init__("")
        self.release = release

    def readline(self, *args, **kwargs) -> str:
        self.release.wait()
        return ""


class TekScopeIOTests(unittest.TestCase):
    @patch("dpt_extractor.gui.main_window.shutdown_tektronix_backend")
    def test_window_shutdown_clears_and_waits_for_owned_pools(self, shutdown_backend) -> None:
        calls: list[str] = []

        class Pool:
            def __init__(self, name: str) -> None:
                self.name = name

            def clear(self) -> None:
                calls.append(f"clear:{self.name}")

            def waitForDone(self, timeout: int) -> bool:  # noqa: N802
                calls.append(f"wait:{self.name}:{timeout}")
                return True

        status = SimpleNamespace(
            showMessage=lambda _message: None,
            repaint=lambda: None,
        )
        timer = SimpleNamespace(stop=lambda: calls.append("stop:progress"))
        window = SimpleNamespace(
            _background_shutdown_complete=False,
            _load_request_id=1,
            _scope_sync_request_id=2,
            _report_request_id=3,
            _load_pool=Pool("load"),
            _scope_io_pool=Pool("scope"),
            _load_tasks={1: object()},
            _scope_sync_tasks={2: object()},
            _report_prepare_tasks={3: object()},
            _report_tasks={3: object()},
            report_progress=SimpleNamespace(_timer=timer),
            statusBar=lambda: status,
        )

        MainWindow.shutdown_background_work(window)

        self.assertEqual(window._load_request_id, 2)
        self.assertEqual(window._scope_sync_request_id, 3)
        self.assertEqual(window._report_request_id, 4)
        self.assertEqual(
            calls,
            [
                "stop:progress",
                "clear:load",
                "clear:scope",
                "wait:scope:-1",
                "wait:load:-1",
            ],
        )
        shutdown_backend.assert_called_once_with()
        self.assertTrue(window._background_shutdown_complete)
        self.assertFalse(window._load_tasks)
        self.assertFalse(window._scope_sync_tasks)
        self.assertFalse(window._report_prepare_tasks)
        self.assertFalse(window._report_tasks)

    @patch("dpt_extractor.io.tek_scope._terminate_hung_tekvisa_resource_managers")
    def test_shutdown_stops_active_bridge_and_tekvisa_server(self, terminate_tekvisa) -> None:
        from dpt_extractor.io import tek_scope

        release = threading.Event()
        process = _FakeBridgeProcess(
            _BlockingTextStream(release),
            _BlockingTextStream(release),
            return_code=None,
            release=release,
        )
        tek_scope._ACTIVE_BRIDGE_PROCESSES.add(process)
        tek_scope._TEKVISA_USED_BY_PROCESS = True

        shutdown_tektronix_backend()

        self.assertTrue(process.terminated)
        self.assertNotIn(process, tek_scope._ACTIVE_BRIDGE_PROCESSES)
        self.assertFalse(tek_scope._TEKVISA_USED_BY_PROCESS)
        terminate_tekvisa.assert_called_once_with()

    @patch("dpt_extractor.io.tek_scope._bridge_script_path")
    @patch("dpt_extractor.io.tek_scope._powershell_executable")
    @patch("dpt_extractor.io.tek_scope.subprocess.Popen")
    def test_bridge_streams_progress_and_result(
        self,
        popen,
        powershell_executable,
        bridge_script_path,
    ) -> None:
        powershell_executable.return_value = "powershell.exe"
        bridge_script_path.return_value = Path("tek_scope_bridge.ps1")
        popen.return_value = _FakeBridgeProcess(
            io.StringIO(
                'PROGRESS\t1\t2\tReading scope CH1...\n'
                'RESULT\t{"resource":"USB::SCOPE"}\n'
            ),
            io.StringIO(""),
        )
        progress: list[tuple[int, int, str]] = []

        result = _run_bridge("discover", progress_callback=lambda *args: progress.append(args))

        self.assertEqual(result, {"resource": "USB::SCOPE"})
        self.assertEqual(progress, [(1, 2, "读取示波器 CH1...")])

    @patch("dpt_extractor.io.tek_scope._bridge_script_path")
    @patch("dpt_extractor.io.tek_scope._powershell_executable")
    @patch("dpt_extractor.io.tek_scope._bridge_timeouts", return_value=(0.03, 0.1))
    @patch("dpt_extractor.io.tek_scope._terminate_hung_tekvisa_resource_managers")
    @patch("dpt_extractor.io.tek_scope.subprocess.Popen")
    def test_bridge_timeout_terminates_silent_process(
        self,
        popen,
        terminate_tekvisa,
        _bridge_timeouts,
        powershell_executable,
        bridge_script_path,
    ) -> None:
        powershell_executable.return_value = "powershell.exe"
        bridge_script_path.return_value = Path("tek_scope_bridge.ps1")
        release = threading.Event()
        process = _FakeBridgeProcess(
            _BlockingTextStream(release),
            _BlockingTextStream(release),
            return_code=None,
            release=release,
        )
        popen.return_value = process

        with self.assertRaisesRegex(TekScopeError, "连续 0.03 秒无响应"):
            _run_bridge_once("acquire", provider="TekVISA")

        self.assertTrue(process.terminated)
        self.assertIsNotNone(process.poll())
        terminate_tekvisa.assert_called_once_with()

    def test_identity_stage_failure_falls_back_to_ni_visa(self) -> None:
        with (
            patch(
                "dpt_extractor.io.tek_scope._bridge_provider_order",
                return_value=("TekVISA", "NI-VISA"),
            ),
            patch("dpt_extractor.io.tek_scope._remember_bridge_provider"),
            patch("dpt_extractor.io.tek_scope._run_bridge_once") as run_once,
        ):
            run_once.side_effect = (
                _BridgeIdentityError("TekVISA initialization timed out"),
                {"resource": "USB::SCOPE", "visa_backend": "NI-VISA"},
            )
            progress: list[tuple[int, int, str]] = []

            result = _run_bridge(
                "acquire",
                progress_callback=lambda *args: progress.append(args),
            )

        self.assertEqual(result["visa_backend"], "NI-VISA")
        self.assertEqual(
            [call.kwargs["provider"] for call in run_once.call_args_list],
            ["TekVISA", "NI-VISA"],
        )
        self.assertIn("正在尝试 NI-VISA", progress[-1][2])

    def test_provider_fallback_progress_never_rewinds(self) -> None:
        def run_once(_operation: str, **kwargs):
            callback = kwargs["progress_callback"]
            provider = kwargs["provider"]
            if provider == "TekVISA":
                callback(1, 100, "Initializing TekVISA")
                callback(2, 100, "Opening TekVISA resource manager")
                raise _BridgeIdentityError("TekVISA initialization failed")
            callback(1, 100, "Initializing NI-VISA")
            callback(5, 100, "NI-VISA scope ready")
            return {"resource": "USB::SCOPE", "visa_backend": "NI-VISA"}

        with (
            patch(
                "dpt_extractor.io.tek_scope._bridge_provider_order",
                return_value=("TekVISA", "NI-VISA"),
            ),
            patch("dpt_extractor.io.tek_scope._remember_bridge_provider"),
            patch(
                "dpt_extractor.io.tek_scope._run_bridge_once",
                side_effect=run_once,
            ),
        ):
            progress: list[tuple[int, int, str]] = []
            _run_bridge(
                "discover",
                progress_callback=lambda *args: progress.append(args),
            )

        fractions = [done / total for done, total, _label in progress]
        self.assertEqual(fractions, sorted(fractions))
        self.assertEqual(fractions, [0.01, 0.02, 0.02, 0.02, 0.05])

    def test_last_working_provider_is_reused_first(self) -> None:
        with patch(
            "dpt_extractor.io.tek_scope._LAST_WORKING_BRIDGE_PROVIDER",
            "NI-VISA",
        ):
            self.assertEqual(_bridge_provider_order(), ("NI-VISA", "TekVISA"))

    @patch("dpt_extractor.io.tek_scope._run_bridge_once")
    def test_transfer_stage_failure_does_not_switch_provider(self, run_once) -> None:
        run_once.side_effect = TekScopeError("waveform transfer failed")

        with self.assertRaisesRegex(TekScopeError, "waveform transfer failed"):
            _run_bridge("acquire")

        self.assertEqual(run_once.call_count, 1)

    def test_bridge_prefers_tekvisa_and_limits_ni_fallback_to_provider_selection(self) -> None:
        root = Path(__file__).parents[2]
        bridge = (root / "dpt_extractor" / "io" / "tek_scope_bridge.ps1").read_text(
            encoding="utf-8"
        )
        selection_start = bridge.index("function Open-PreferredVisaContext")
        selection_end = bridge.index("function Optional-Query", selection_start)
        selection = bridge[selection_start:selection_end]
        self.assertIn("@('TekVISA', 'NI-VISA')", selection)
        self.assertIn("foreach ($provider in $providers)", selection)
        self.assertIn("@($RequestedProvider)", selection)
        self.assertLess(
            selection.index("Open-TekVisaManager"),
            selection.index("Open-NiVisaManager"),
        )
        self.assertIn("$resolved = Resolve-ScopeIdentity", selection)
        self.assertIn("if ($scopeNotFound) { throw 'SCOPE_NOT_FOUND' }", selection)

        acquire_start = bridge.index("function Read-ScopeWaveforms")
        acquire_end = bridge.index("function Test-JsonValue", acquire_start)
        acquire = bridge[acquire_start:acquire_end]
        self.assertNotIn("Open-TekVisaManager", acquire)
        self.assertNotIn("Open-NiVisaManager", acquire)
        self.assertIn("visa_backend = $Identity.visa_backend", acquire)

        native = (root / "dpt_extractor" / "io" / "tekvisa_native.cs").read_text(
            encoding="utf-8"
        )
        self.assertIn("tkVisa64.dll", native)
        for entrypoint in (
            "viOpenDefaultRM",
            "viFindRsrc",
            "viOpen",
            "viRead",
            "viWrite",
            "viClear",
        ):
            self.assertIn(entrypoint, native)

        spec = (root / "DPT.spec").read_text(encoding="utf-8")
        self.assertIn('"tekvisa_native.cs"', spec)

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
        sync_end = bridge.index("$context = $null", sync_start)
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


    def test_bridge_clears_bus_only_after_interrupted_transfer(self) -> None:
        bridge = (
            Path(__file__).parents[1] / "io" / "tek_scope_bridge.ps1"
        ).read_text(encoding="utf-8")

        open_scope = bridge[
            bridge.index("function Open-Scope") : bridge.index("function Write-Command")
        ]
        self.assertIn("[switch]$ShouldClear", open_scope)
        self.assertIn("if ($ShouldClear) {", open_scope)
        self.assertEqual(open_scope.count("Clear()"), 1)

        optional = bridge[
            bridge.index("function Optional-Query") : bridge.index(
                "function Get-SourceDisplayCommand"
            )
        ]
        self.assertNotIn("Clear()", optional)
        self.assertIn("[int]$TimeoutMilliseconds = 2000", optional)

        self.assertIn("[switch]$ClearOnOpen", bridge)
        self.assertIn("-ShouldClear:$ClearOnOpen", bridge)

    @patch("dpt_extractor.io.tek_scope._bridge_script_path")
    @patch("dpt_extractor.io.tek_scope._powershell_executable")
    @patch("dpt_extractor.io.tek_scope.subprocess.Popen")
    def test_clear_on_open_flag_is_forwarded_to_bridge(
        self,
        popen,
        powershell_executable,
        bridge_script_path,
    ) -> None:
        powershell_executable.return_value = "powershell.exe"
        bridge_script_path.return_value = Path("tek_scope_bridge.ps1")
        popen.side_effect = [
            _FakeBridgeProcess(
                io.StringIO('RESULT\t{"resource":"USB::SCOPE"}\n'),
                io.StringIO(""),
            ),
            _FakeBridgeProcess(
                io.StringIO('RESULT\t{"resource":"USB::SCOPE"}\n'),
                io.StringIO(""),
            ),
        ]

        _run_bridge_once("acquire", provider="TekVISA")
        self.assertNotIn("-ClearOnOpen", popen.call_args_list[0].args[0])

        _run_bridge_once("acquire", provider="TekVISA", clear_on_open=True)
        self.assertIn("-ClearOnOpen", popen.call_args_list[1].args[0])

    def test_scope_not_found_is_retried_on_the_same_provider(self) -> None:
        with (
            patch(
                "dpt_extractor.io.tek_scope._bridge_provider_order",
                return_value=("TekVISA", "NI-VISA"),
            ),
            patch("dpt_extractor.io.tek_scope._remember_bridge_provider"),
            patch("dpt_extractor.io.tek_scope.time.sleep") as sleep,
            patch("dpt_extractor.io.tek_scope._run_bridge_once") as run_once,
        ):
            run_once.side_effect = (
                _BridgeIdentityError(
                    "未找到通过 USB 连接的 Tektronix 示波器",
                    scope_not_found=True,
                ),
                {"resource": "USB::SCOPE", "visa_backend": "TekVISA"},
            )

            result = _run_bridge("acquire")

        self.assertEqual(result["visa_backend"], "TekVISA")
        self.assertEqual(
            [call.kwargs["provider"] for call in run_once.call_args_list],
            ["TekVISA", "TekVISA"],
        )
        sleep.assert_called_once_with(_BRIDGE_SCOPE_NOT_FOUND_RETRY_SECONDS)

    @patch("dpt_extractor.io.tek_scope._bridge_script_path")
    @patch("dpt_extractor.io.tek_scope._powershell_executable")
    @patch("dpt_extractor.io.tek_scope._terminate_hung_tekvisa_resource_managers")
    @patch("dpt_extractor.io.tek_scope.subprocess.Popen")
    def test_scope_not_found_keeps_tekvisa_resource_manager(
        self,
        popen,
        terminate_tekvisa,
        powershell_executable,
        bridge_script_path,
    ) -> None:
        powershell_executable.return_value = "powershell.exe"
        bridge_script_path.return_value = Path("tek_scope_bridge.ps1")
        popen.return_value = _FakeBridgeProcess(
            io.StringIO(""),
            io.StringIO("SCOPE_NOT_FOUND\n"),
            return_code=1,
        )

        with self.assertRaises(_BridgeIdentityError) as captured:
            _run_bridge_once("acquire", provider="TekVISA")

        self.assertTrue(captured.exception.scope_not_found)
        terminate_tekvisa.assert_not_called()

    @patch("dpt_extractor.io.tek_scope._run_bridge")
    def test_failed_read_requests_one_clear_on_the_next_open(self, run_bridge) -> None:
        from dpt_extractor.io import tek_scope as module

        module._TRANSFER_NEEDS_CLEAR = False
        try:
            run_bridge.side_effect = TekScopeError("波形传输中断")
            with self.assertRaises(TekScopeError):
                read_tektronix_scope()
            self.assertTrue(module._TRANSFER_NEEDS_CLEAR)
            self.assertFalse(run_bridge.call_args.kwargs["clear_on_open"])

            with self.assertRaises(TekScopeError):
                read_tektronix_scope()
            self.assertTrue(run_bridge.call_args.kwargs["clear_on_open"])
        finally:
            module._TRANSFER_NEEDS_CLEAR = False


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
            _parameter_local_views: dict[tuple[str, str], tuple[float, float]] = {}

            class wave_plot:
                @staticmethod
                def current_local_x_window_us():
                    return None

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
