from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Callable

import numpy as np

from dpt_extractor.models.waveform import TekMetadata, WaveformBundle


_ANALOG_OR_MATH_SOURCE = re.compile(r"^(?:CH\d+|MATH\d+)$", re.IGNORECASE)
_PROGRESS_PREFIX = "PROGRESS\t"
_RESULT_PREFIX = "RESULT\t"


class TekScopeError(RuntimeError):
    """Base error shown by the USB scope workflow."""


class ScopeNotFoundError(TekScopeError):
    pass


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


def _run_bridge(
    operation: str,
    *,
    resource: str = "",
    output_path: str = "",
    state_path: str = "",
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
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
    ]
    if resource:
        command.extend(("-Resource", resource))
    if output_path:
        command.extend(("-OutputPath", output_path))
    if state_path:
        command.extend(("-StatePath", state_path))
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
    result: dict[str, object] | None = None
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip("\r\n")
        if line.startswith(_PROGRESS_PREFIX):
            fields = line.split("\t", 3)
            if progress_callback is not None and len(fields) == 4:
                label = fields[3]
                if label.startswith("Reading scope "):
                    label = f"读取示波器 {label.removeprefix('Reading scope ')}"
                elif label == "Scope waveform transfer complete":
                    label = "示波器波形读取完成"
                progress_callback(int(fields[1]), int(fields[2]), label)
        elif line.startswith(_RESULT_PREFIX):
            result = json.loads(line[len(_RESULT_PREFIX) :])
    stderr = process.stderr.read().strip() if process.stderr is not None else ""
    return_code = process.wait()
    if return_code != 0:
        message = stderr.splitlines()[-1].strip() if stderr else "VISA 桥接进程失败"
        if "SCOPE_NOT_FOUND" in message:
            raise ScopeNotFoundError("未找到通过 USB 连接的 Tektronix 示波器")
        raise TekScopeError(message)
    if result is None:
        raise TekScopeError("VISA 桥接进程未返回结果")
    return result


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
    with tempfile.TemporaryDirectory(prefix="dpt_scope_") as temp_dir:
        result = _run_bridge(
            "acquire",
            resource=_clean_text(resource),
            output_path=temp_dir,
            progress_callback=progress_callback,
        )
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
        return _run_bridge("sync", resource=resource, state_path=str(state_path))
