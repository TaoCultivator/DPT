from __future__ import annotations

import atexit
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time
from typing import Callable, TextIO

import numpy as np

from dpt_extractor.models.waveform import TekMetadata, WaveformBundle


_ANALOG_OR_MATH_SOURCE = re.compile(r"^(?:CH\d+|MATH\d+)$", re.IGNORECASE)
_PROGRESS_PREFIX = "PROGRESS\t"
_RESULT_PREFIX = "RESULT\t"
_BRIDGE_IDLE_TIMEOUT_SECONDS = {
    "discover": 30.0,
    "acquire": 75.0,
    "sync": 30.0,
}
_BRIDGE_TOTAL_TIMEOUT_SECONDS = {
    "discover": 45.0,
    "acquire": 600.0,
    "sync": 60.0,
}
_BRIDGE_OPERATION_LABELS = {
    "discover": "发现",
    "acquire": "波形读取",
    "sync": "光标同步",
}
_BRIDGE_TERMINATE_GRACE_SECONDS = 2.0
#: `viFindRsrc` can transiently report no resource right after the scope powers
#: on or after another process releases the device.  Retry the preferred
#: provider once with a short backoff before switching back end; the second
#: provider is the fallback already, so it is never retried.
_BRIDGE_IDENTITY_ATTEMPTS = 2
_BRIDGE_SCOPE_NOT_FOUND_RETRY_SECONDS = 1.5
_ACTIVE_BRIDGE_PROCESSES: set[subprocess.Popen[str]] = set()
_ACTIVE_BRIDGE_LOCK = threading.Lock()
_BRIDGE_PROVIDER_LOCK = threading.Lock()
_LAST_WORKING_BRIDGE_PROVIDER: str | None = None
_TEKVISA_USED_BY_PROCESS = False
#: Set when the previous transfer stopped before completing, so the next open
#: clears the bus exactly once.  Direct reads and syncs never clear.
_TRANSFER_NEEDS_CLEAR = False
_TEKVISA_RESOURCE_MANAGER_PATH = (
    r"C:\Program Files\IVI Foundation\VISA\Win64\TekVISA\Bin\TekVisaRM.exe"
)


class TekScopeError(RuntimeError):
    """Base error shown by the USB scope workflow."""


class ScopeNotFoundError(TekScopeError):
    pass


class _BridgeIdentityError(TekScopeError):
    """A provider failed before waveform transfer or synchronization began."""

    def __init__(self, message: str, *, scope_not_found: bool = False) -> None:
        super().__init__(message)
        self.scope_not_found = scope_not_found


@dataclass(frozen=True)
class ScopeIdentity:
    resource: str
    idn: str

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(part.strip() for part in self.idn.split(","))

    @property
    def model(self) -> str:
        fields = self.fields
        return fields[1] if len(fields) > 1 else "Tektronix"

    @property
    def serial(self) -> str:
        fields = self.fields
        return fields[2] if len(fields) > 2 else ""

    @property
    def display_name(self) -> str:
        return " ".join(part for part in (self.model, self.serial) if part).strip()


@dataclass(frozen=True)
class ScopeViewState:
    x_start_s: float
    x_stop_s: float
    record_start_s: float
    record_stop_s: float
    cursor_a_s: float | None = None
    cursor_b_s: float | None = None
    source_a: str | None = None
    source_b: str | None = None
    level_a: float | None = None
    level_b: float | None = None
    zoom_enabled: bool = True
    sync_cursors: bool = True


def _clean_text(value: object) -> str:
    return str(value or "").strip().strip('"').strip()


def _scope_source(value: object) -> str:
    source = _clean_text(value).upper().lstrip("+-")
    return source if _ANALOG_OR_MATH_SOURCE.fullmatch(source) else ""


def _decode_ieee_block(raw: bytes) -> bytes:
    start = raw.find(b"#")
    if start < 0 or start + 2 > len(raw):
        raise TekScopeError("示波器返回的波形不是 IEEE 二进制块")
    digit = raw[start + 1 : start + 2]
    if not digit.isdigit():
        raise TekScopeError("示波器返回了无效的波形块头")
    digits = int(digit)
    if digits <= 0 or start + 2 + digits > len(raw):
        raise TekScopeError("示波器返回了不支持的波形块长度")
    size = int(raw[start + 2 : start + 2 + digits])
    payload_start = start + 2 + digits
    payload = raw[payload_start : payload_start + size]
    if len(payload) != size:
        raise TekScopeError(
            f"示波器波形数据不完整：应为 {size} 字节，实际 {len(payload)} 字节"
        )
    return payload


def _bridge_script_path() -> Path:
    path = Path(__file__).with_name("tek_scope_bridge.ps1")
    if not path.is_file():
        raise TekScopeError(f"缺少示波器 VISA 桥接脚本：{path}")
    return path


def _powershell_executable() -> str:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    executable = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not executable.is_file():
        raise TekScopeError("未找到 Windows PowerShell，无法调用 VISA .NET 驱动")
    return str(executable)


def _bridge_timeouts(operation: str) -> tuple[float, float]:
    return (
        _BRIDGE_IDLE_TIMEOUT_SECONDS.get(operation, 30.0),
        _BRIDGE_TOTAL_TIMEOUT_SECONDS.get(operation, 60.0),
    )


def _bridge_provider_order() -> tuple[str, str]:
    with _BRIDGE_PROVIDER_LOCK:
        preferred = _LAST_WORKING_BRIDGE_PROVIDER
    if preferred == "NI-VISA":
        return "NI-VISA", "TekVISA"
    return "TekVISA", "NI-VISA"


def _remember_bridge_provider(provider: str) -> None:
    if provider not in {"TekVISA", "NI-VISA"}:
        return
    global _LAST_WORKING_BRIDGE_PROVIDER
    with _BRIDGE_PROVIDER_LOCK:
        _LAST_WORKING_BRIDGE_PROVIDER = provider


def _bridge_progress_label(label: str) -> str:
    if label.startswith("Initializing "):
        return f"正在初始化 {label.removeprefix('Initializing ')}"
    if label == "Loading TekVISA adapter...":
        return "正在加载 TekVISA 适配器..."
    if label == "Opening TekVISA resource manager...":
        return "正在创建 TekVISA 资源管理器..."
    if label == "TekVISA resource manager ready":
        return "TekVISA 资源管理器已就绪"
    if label.startswith("Searching scope via "):
        provider = label.removeprefix("Searching scope via ").removesuffix("...")
        return f"正在通过 {provider} 搜索示波器..."
    if label.startswith("Opening scope "):
        return "正在打开 USB 示波器..."
    if label.startswith("Connected scope via "):
        provider = label.removeprefix("Connected scope via ").removesuffix("...")
        return f"已通过 {provider} 连接示波器"
    if label == "Preparing scope waveform transfer...":
        return "正在准备示波器波形读取..."
    if label.startswith("Reading scope "):
        return f"读取示波器 {label.removeprefix('Reading scope ')}"
    if label.startswith("Read scope "):
        return f"已读取示波器 {label.removeprefix('Read scope ')}"
    if label == "Scope waveform transfer complete":
        return "示波器波形读取完成"
    return label


def _register_bridge_process(process: subprocess.Popen[str]) -> None:
    with _ACTIVE_BRIDGE_LOCK:
        _ACTIVE_BRIDGE_PROCESSES.add(process)


def _unregister_bridge_process(process: subprocess.Popen[str]) -> None:
    with _ACTIVE_BRIDGE_LOCK:
        _ACTIVE_BRIDGE_PROCESSES.discard(process)


def _terminate_bridge_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=_BRIDGE_TERMINATE_GRACE_SECONDS)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
        process.wait(timeout=_BRIDGE_TERMINATE_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _terminate_active_bridge_processes() -> None:
    with _ACTIVE_BRIDGE_LOCK:
        processes = tuple(_ACTIVE_BRIDGE_PROCESSES)
        _ACTIVE_BRIDGE_PROCESSES.clear()
    for process in processes:
        _terminate_bridge_process(process)


def _terminate_hung_tekvisa_resource_managers() -> None:
    """Best-effort cleanup of the out-of-process TekVISA server after init fails.

    TekVISA starts ``TekVisaRM.exe`` outside the bridge process.  Terminating a
    timed-out bridge therefore does not terminate that server, and the orphan
    can keep the USBTMC device locked so the NI-VISA identity fallback also
    fails.  Limit cleanup to the exact official executable path and only call
    it after TekVISA has failed before data transfer begins.
    """

    script = (
        f"$expected = '{_TEKVISA_RESOURCE_MANAGER_PATH}'; "
        "Get-Process -Name 'TekVisaRM' -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -eq $expected } | "
        "Stop-Process -Force -ErrorAction SilentlyContinue"
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            [
                _powershell_executable(),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _read_bridge_stream(
    stream_name: str,
    stream: TextIO,
    output_queue: queue.Queue[tuple[str, str | None]],
) -> None:
    try:
        while True:
            line = stream.readline()
            if line == "":
                break
            output_queue.put((stream_name, line))
    finally:
        output_queue.put((stream_name, None))


def shutdown_tektronix_backend() -> None:
    """Stop every external VISA helper process started by this application."""

    global _TEKVISA_USED_BY_PROCESS
    _terminate_active_bridge_processes()
    if _TEKVISA_USED_BY_PROCESS:
        # TekVISA hosts its resource manager outside the PowerShell bridge, so
        # terminating only the bridge can leave TekVisaRM.exe alive after the
        # GUI exits.  The helper already limits termination to Tektronix's exact
        # official executable path.
        _terminate_hung_tekvisa_resource_managers()
        _TEKVISA_USED_BY_PROCESS = False


atexit.register(shutdown_tektronix_backend)


def _run_bridge_once(
    operation: str,
    *,
    provider: str,
    resource: str = "",
    output_path: str = "",
    state_path: str = "",
    progress_callback: Callable[[int, int, str], None] | None = None,
    clear_on_open: bool = False,
) -> dict[str, object]:
    global _TEKVISA_USED_BY_PROCESS
    if provider == "TekVISA":
        _TEKVISA_USED_BY_PROCESS = True
    command = [
        _powershell_executable(),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(_bridge_script_path()),
        "-Operation",
        operation,
        "-Provider",
        provider,
    ]
    if resource:
        command.extend(("-Resource", resource))
    if output_path:
        command.extend(("-OutputPath", output_path))
    if state_path:
        command.extend(("-StatePath", state_path))
    if clear_on_open:
        command.append("-ClearOnOpen")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
    )
    _register_bridge_process(process)
    result: dict[str, object] | None = None
    stderr_lines: list[str] = []
    assert process.stdout is not None
    assert process.stderr is not None
    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    readers = (
        threading.Thread(
            target=_read_bridge_stream,
            args=("stdout", process.stdout, output_queue),
            name=f"tek-scope-{operation}-stdout",
            daemon=True,
        ),
        threading.Thread(
            target=_read_bridge_stream,
            args=("stderr", process.stderr, output_queue),
            name=f"tek-scope-{operation}-stderr",
            daemon=True,
        ),
    )
    for reader in readers:
        reader.start()

    idle_timeout, total_timeout = _bridge_timeouts(operation)
    started_at = time.monotonic()
    last_output_at = started_at
    open_streams = {"stdout", "stderr"}
    timeout_message = ""
    max_progress = 0
    try:
        while open_streams or process.poll() is None:
            now = time.monotonic()
            idle_elapsed = now - last_output_at
            total_elapsed = now - started_at
            if total_elapsed >= total_timeout:
                operation_label = _BRIDGE_OPERATION_LABELS.get(operation, operation)
                timeout_message = (
                    f"示波器{operation_label}操作超过 {total_timeout:g} 秒，"
                    "已终止无响应的 VISA 桥接进程"
                )
                break
            if max_progress <= 2:
                current_idle_timeout = min(idle_timeout, 15.0)
            elif max_progress < 6:
                current_idle_timeout = min(idle_timeout, 30.0)
            else:
                current_idle_timeout = idle_timeout
            if idle_elapsed >= current_idle_timeout:
                operation_label = _BRIDGE_OPERATION_LABELS.get(operation, operation)
                timeout_message = (
                    f"{provider} 示波器{operation_label}操作连续 "
                    f"{current_idle_timeout:g} 秒无响应，"
                    "已终止 VISA 桥接进程，请检查 USB 连接和 VISA 驱动后重试"
                )
                break
            wait_seconds = max(
                0.01,
                min(
                    0.1,
                    current_idle_timeout - idle_elapsed,
                    total_timeout - total_elapsed,
                ),
            )
            try:
                stream_name, raw_line = output_queue.get(timeout=wait_seconds)
            except queue.Empty:
                continue
            if raw_line is None:
                open_streams.discard(stream_name)
                continue
            last_output_at = time.monotonic()
            line = raw_line.rstrip("\r\n")
            if stream_name == "stderr":
                stderr_lines.append(line)
                continue
            if line.startswith(_PROGRESS_PREFIX):
                fields = line.split("\t", 3)
                if len(fields) == 4:
                    done = int(fields[1])
                    total = int(fields[2])
                    if total > 0:
                        max_progress = max(
                            max_progress,
                            int(round(100 * max(0, min(done, total)) / total)),
                        )
                    label = _bridge_progress_label(fields[3])
                    if progress_callback is not None:
                        progress_callback(done, total, label)
            elif line.startswith(_RESULT_PREFIX):
                result = json.loads(line[len(_RESULT_PREFIX) :])

        if timeout_message:
            _terminate_bridge_process(process)
            if max_progress < 6:
                if provider == "TekVISA":
                    _terminate_hung_tekvisa_resource_managers()
                raise _BridgeIdentityError(timeout_message)
            raise TekScopeError(timeout_message)
        return_code = process.wait(timeout=_BRIDGE_TERMINATE_GRACE_SECONDS)
    except Exception:
        _terminate_bridge_process(process)
        raise
    finally:
        _unregister_bridge_process(process)
        for reader in readers:
            reader.join(timeout=0.5)
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass

    stderr = "\n".join(stderr_lines).strip()
    if return_code != 0:
        message = stderr.splitlines()[-1].strip() if stderr else "VISA 桥接进程失败"
        if max_progress < 6:
            scope_not_found = "SCOPE_NOT_FOUND" in message
            if scope_not_found:
                # A transient enumeration miss is not a hung resource manager:
                # keep TekVisaRM alive and let the caller retry or fall back.
                message = "未找到通过 USB 连接的 Tektronix 示波器"
            elif provider == "TekVISA":
                _terminate_hung_tekvisa_resource_managers()
            raise _BridgeIdentityError(message, scope_not_found=scope_not_found)
        raise TekScopeError(message)
    if result is None:
        message = "VISA 桥接进程未返回结果"
        if max_progress < 6:
            if provider == "TekVISA":
                _terminate_hung_tekvisa_resource_managers()
            raise _BridgeIdentityError(message)
        raise TekScopeError(message)
    return result


def _run_bridge(
    operation: str,
    *,
    resource: str = "",
    output_path: str = "",
    state_path: str = "",
    progress_callback: Callable[[int, int, str], None] | None = None,
    clear_on_open: bool = False,
) -> dict[str, object]:
    identity_errors: list[str] = []
    scope_not_found_count = 0
    providers = _bridge_provider_order()
    max_progress_fraction = 0.0

    def emit_progress(done: int, total: int, label: str) -> None:
        """Forward bridge progress without allowing provider fallback to rewind it."""

        nonlocal max_progress_fraction
        safe_total = max(1, int(total))
        requested = max(0, min(int(done), safe_total)) / safe_total
        max_progress_fraction = max(max_progress_fraction, requested)
        if progress_callback is not None:
            progress_callback(
                int(math.ceil(max_progress_fraction * safe_total - 1e-12)),
                safe_total,
                label,
            )

    for index, provider in enumerate(providers):
        if index > 0:
            emit_progress(
                1,
                100,
                f"{providers[0]} 身份连接失败，正在尝试 {provider}...",
            )
        attempts = _BRIDGE_IDENTITY_ATTEMPTS if index == 0 else 1
        for attempt in range(attempts):
            try:
                result = _run_bridge_once(
                    operation,
                    provider=provider,
                    resource=resource,
                    output_path=output_path,
                    state_path=state_path,
                    progress_callback=emit_progress,
                    clear_on_open=clear_on_open,
                )
                _remember_bridge_provider(
                    _clean_text(result.get("visa_backend")) or provider
                )
                return result
            except _BridgeIdentityError as exc:
                if exc.scope_not_found and attempt + 1 < attempts:
                    # Enumeration can come back empty for a moment; retry the
                    # same provider before declaring the scope missing.
                    emit_progress(
                        1,
                        100,
                        f"{provider} 暂时未枚举到示波器，"
                        f"{_BRIDGE_SCOPE_NOT_FOUND_RETRY_SECONDS:g} 秒后重试...",
                    )
                    time.sleep(_BRIDGE_SCOPE_NOT_FOUND_RETRY_SECONDS)
                    continue
                identity_errors.append(f"{provider}: {exc}")
                if exc.scope_not_found:
                    scope_not_found_count += 1
                break
    if scope_not_found_count == len(providers):
        raise ScopeNotFoundError("未找到通过 USB 连接的 Tektronix 示波器")
    detail = "; ".join(identity_errors)
    raise TekScopeError(f"无法连接 Tektronix 示波器：{detail}")


def discover_tektronix_scope() -> ScopeIdentity:
    result = _run_bridge("discover")
    resource = _clean_text(result.get("resource"))
    idn = _clean_text(result.get("idn"))
    if not resource or not idn.upper().startswith("TEKTRONIX,"):
        raise ScopeNotFoundError("未找到通过 USB 连接的 Tektronix 示波器")
    return ScopeIdentity(resource=resource, idn=idn)


def read_tektronix_scope(
    *,
    resource: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> WaveformBundle:
    global _TRANSFER_NEEDS_CLEAR
    with tempfile.TemporaryDirectory(prefix="dpt_scope_") as temp_dir:
        try:
            result = _run_bridge(
                "acquire",
                resource=_clean_text(resource),
                output_path=temp_dir,
                progress_callback=progress_callback,
                clear_on_open=_TRANSFER_NEEDS_CLEAR,
            )
        except ScopeNotFoundError:
            raise
        except Exception:
            # An interrupted transfer can leave a half response queued on the
            # instrument; clear the bus once on the next open, not on every open.
            _TRANSFER_NEEDS_CLEAR = True
            raise
        _TRANSFER_NEEDS_CLEAR = False
        resource_name = _clean_text(result.get("resource"))
        idn = _clean_text(result.get("idn"))
        sources = result.get("sources")
        if not isinstance(sources, list) or not sources:
            raise TekScopeError("示波器未返回有效波形通道")
        reported_record_length = int(result.get("record_length") or 0)

        channels: dict[str, np.ndarray] = {}
        channel_labels: dict[str, str] = {}
        channel_vdiv: dict[str, float] = {}
        channel_units: dict[str, str] = {}
        channel_y_position: dict[str, float] = {}
        channel_math_formulas: dict[str, str] = {}
        source_inversions: set[str] = set()
        x_increment: float | None = None
        x_zero: float | None = None
        point_offset: float | None = None
        expected_points: int | None = None

        for item in sources:
            if not isinstance(item, dict):
                raise TekScopeError("示波器通道元数据格式无效")
            source = _scope_source(item.get("source"))
            filename = Path(temp_dir) / _clean_text(item.get("file"))
            points = int(item["points"])
            if reported_record_length > 0 and points != reported_record_length:
                raise TekScopeError(
                    f"{source} 波形数据不完整：记录长度 {reported_record_length}，"
                    f"实际读取 {points} 点"
                )
            xincr = float(item["x_increment"])
            xzero = float(item["x_zero"])
            ptoff = float(item["point_offset"])
            ymult = float(item["y_multiplier"])
            yzero = float(item["y_zero"])
            yoff = float(item["y_offset"])
            payload = _decode_ieee_block(filename.read_bytes())
            byte_width = int(item["byte_width"])
            binary_format = _clean_text(item["binary_format"]).upper()
            byte_order = _clean_text(item["byte_order"]).upper()
            dtype = _waveform_dtype(byte_width, binary_format, byte_order)
            if len(payload) % byte_width:
                raise TekScopeError(f"{source} 返回的波形字节长度无效")
            raw = np.frombuffer(payload, dtype=dtype)
            if raw.size != points:
                raise TekScopeError(
                    f"{source} 点数不一致：前导信息 {points}，实际 {raw.size}"
                )
            if expected_points is None:
                expected_points = points
                x_increment = xincr
                x_zero = xzero
                point_offset = ptoff
            elif (
                points != expected_points
                or not math.isclose(xincr, float(x_increment), rel_tol=1e-9, abs_tol=1e-18)
                or not math.isclose(xzero, float(x_zero), rel_tol=1e-9, abs_tol=1e-15)
                or not math.isclose(ptoff, float(point_offset), rel_tol=1e-9, abs_tol=1e-9)
            ):
                raise TekScopeError(f"{source} 与其他通道的时间轴不一致")
            channels[source] = (raw.astype(np.float64) - yoff) * ymult + yzero
            channel_labels[source] = _parse_scope_label(item.get("label"))
            channel_units[source] = _clean_text(item.get("unit")) or "V"
            if item.get("scale") is not None:
                channel_vdiv[source] = float(item["scale"])
            if item.get("position") is not None:
                channel_y_position[source] = float(item["position"])
            formula = _clean_text(item.get("formula"))
            if formula:
                channel_math_formulas[source] = formula
            if bool(item.get("inverted")):
                source_inversions.add(source)

        if expected_points is None or x_increment is None or x_zero is None or point_offset is None:
            raise TekScopeError("示波器未返回有效波形")
        t = x_zero + (np.arange(expected_points, dtype=np.float64) - point_offset) * x_increment
        fields = tuple(part.strip() for part in idn.split(","))
        model = fields[1] if len(fields) > 1 else "Tektronix"
        serial = fields[2] if len(fields) > 2 else ""
        source_path = f"scope://{serial or resource_name}"
        meta = TekMetadata(
            model=model,
            sample_interval=x_increment,
            record_length=expected_points,
            zero_index=float(point_offset - x_zero / x_increment),
            source_path=source_path,
            source_kind="scope",
            instrument_resource=resource_name,
            instrument_idn=idn,
            channel_labels=channel_labels,
            channel_vdiv=channel_vdiv,
            channel_units=channel_units,
            channel_y_position=channel_y_position,
            channel_math_formulas=channel_math_formulas,
            horizontal_scale_per_div=_optional_float(result.get("horizontal_scale")),
            horizontal_position_percent=_optional_float(result.get("horizontal_position")),
            horizontal_delay=_optional_float(result.get("horizontal_delay")),
            source_channel_inversions=set(source_inversions),
            channel_display_inversions=set(source_inversions),
        )
        return WaveformBundle(t=t, channels=channels, meta=meta)


def _optional_float(value: object) -> float | None:
    if value is None or _clean_text(value) == "":
        return None
    return float(value)


def _parse_scope_label(value: object) -> str:
    label = _clean_text(value)
    if '";' in label:
        label = label.split('";', 1)[0]
    return label.strip('"').strip()


def _waveform_dtype(byte_width: int, binary_format: str, byte_order: str) -> np.dtype:
    endian = "<" if byte_order in {"LSB", "LSBFIRST"} else ">"
    if binary_format in {"FP", "FLOAT", "REAL"} and byte_width in {4, 8}:
        return np.dtype(f"{endian}f{byte_width}")
    if binary_format in {"RI", "SRI", "SIGNED"} and byte_width in {1, 2, 4, 8}:
        return np.dtype(f"{endian}i{byte_width}")
    if binary_format in {"RP", "SRP", "UNSIGNED"} and byte_width in {1, 2, 4, 8}:
        return np.dtype(f"{endian}u{byte_width}")
    raise TekScopeError(
        f"不支持的示波器二进制格式：{binary_format}/{byte_width} byte/{byte_order}"
    )


def sync_tektronix_scope(resource: str, state: ScopeViewState) -> dict[str, object]:
    global _TRANSFER_NEEDS_CLEAR
    if not (
        math.isfinite(float(state.x_start_s))
        and math.isfinite(float(state.x_stop_s))
        and float(state.x_stop_s) > float(state.x_start_s)
    ):
        raise TekScopeError("软件当前波形窗口无效，无法同步示波器")
    if not (
        math.isfinite(float(state.record_start_s))
        and math.isfinite(float(state.record_stop_s))
        and float(state.record_stop_s) > float(state.record_start_s)
    ):
        raise TekScopeError("软件完整波形范围无效，无法同步示波器缩放窗口")
    payload = {
        "x_start_s": float(state.x_start_s),
        "x_stop_s": float(state.x_stop_s),
        "record_start_s": float(state.record_start_s),
        "record_stop_s": float(state.record_stop_s),
        "cursor_a_s": state.cursor_a_s,
        "cursor_b_s": state.cursor_b_s,
        "source_a": _scope_source(state.source_a),
        "source_b": _scope_source(state.source_b),
        "level_a": state.level_a,
        "level_b": state.level_b,
        "zoom_enabled": bool(state.zoom_enabled),
        "sync_cursors": bool(state.sync_cursors),
    }
    with tempfile.TemporaryDirectory(prefix="dpt_scope_sync_") as temp_dir:
        state_path = Path(temp_dir) / "state.json"
        state_path.write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        try:
            result = _run_bridge(
                "sync",
                resource=resource,
                state_path=str(state_path),
                clear_on_open=_TRANSFER_NEEDS_CLEAR,
            )
        except ScopeNotFoundError:
            raise
        except Exception:
            # Same as the read path: only an interrupted exchange needs a clear.
            _TRANSFER_NEEDS_CLEAR = True
            raise
        _TRANSFER_NEEDS_CLEAR = False
        return result
