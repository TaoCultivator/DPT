from __future__ import annotations

import ast
import io
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import numpy as np

from dpt_extractor.models.waveform import TekMetadata, WaveformBundle

_CHANNEL_RE = re.compile(r"^(CH[1-6]|MATH\d+|M\d+)$", re.I)
_WFM_NAME_RE = re.compile(r"(CH[1-6]|MATH\d+|M\d+)", re.I)
_MATH_KEY_RE = re.compile(r"MATH(\d+)", re.I)


def _normalize_channel(name: str) -> str:
    upper = name.upper()
    if re.fullmatch(r"M\d+", upper):
        return f"MATH{upper[1:]}"
    if upper.startswith("MATH"):
        suffix = upper[4:]
        return f"MATH{suffix}" if suffix else upper
    return upper


def _channel_from_member(member: str) -> str | None:
    stem = PurePosixPath(member).stem
    match = _WFM_NAME_RE.fullmatch(stem) or _WFM_NAME_RE.search(stem)
    if not match:
        return None
    return _normalize_channel(match.group(1))


def read_file(path: str | Path):
    from dpt_extractor.utils.app_paths import configure_numba_cache_dir

    configure_numba_cache_dir()
    from tm_data_types import read_file as _read_file

    return _read_file(path)


def read_wfm_vertical_scale_per_div(path: str | Path) -> float | None:
    from dpt_extractor.io.wfm_scope_display import (
        read_wfm_vertical_scale_per_div as _read_wfm_vertical_scale_per_div,
    )

    return _read_wfm_vertical_scale_per_div(path)


def _channel_from_waveform(wfm) -> str | None:
    if wfm.source_name:
        token = wfm.source_name.split(",", 1)[0].strip()
        if _CHANNEL_RE.match(token):
            return _normalize_channel(token)
    return None


def _looks_like_analog_waveform(wfm) -> bool:
    return hasattr(wfm, "normalized_vertical_values") or hasattr(wfm, "y_axis_values")


def _waveform_arrays(wfm) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(wfm.normalized_vertical_values, dtype=np.float64)
    if wfm.x_axis_values is not None:
        t = np.asarray(wfm.x_axis_values, dtype=np.float64)
    else:
        t = np.asarray(wfm.normalized_horizontal_values, dtype=np.float64)
    if len(t) != len(y):
        spacing = float(wfm.x_axis_spacing or 0.0)
        trigger = float(wfm.trigger_index or 0.0)
        idx = np.arange(len(y), dtype=np.float64)
        t = (idx - trigger) * spacing
    return t, y


def _sample_interval_from_time(t: np.ndarray, fallback: float) -> float:
    """Return the waveform sampling interval from the WFM time axis when possible."""
    if len(t) > 1:
        dt = np.diff(np.asarray(t, dtype=np.float64))
        dt = dt[np.isfinite(dt) & (dt > 0)]
        if len(dt):
            return float(np.median(dt))
    return float(fallback)


@dataclass
class _MathSetup:
    formulas: dict[str, str] = field(default_factory=dict)
    vdiv: dict[str, float] = field(default_factory=dict)
    y_position: dict[str, float] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)


def _strip_setup_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return unquote(value)


def _normalise_formula(expr: str) -> str:
    expr = expr.strip()
    expr = re.sub(r"\bMath\s*(\d+)\b", r"MATH\1", expr, flags=re.I)
    expr = re.sub(r"\bCh\s*(\d+)\b", r"CH\1", expr, flags=re.I)
    expr = re.sub(r"\bAND\b(?!\s*\()", "and", expr, flags=re.I)
    expr = re.sub(r"\bOR\b(?!\s*\()", "or", expr, flags=re.I)
    expr = re.sub(r"\bXOR\b(?!\s*\()", "^", expr, flags=re.I)
    return expr


def _math_sort_key(name: str) -> tuple[int, str]:
    match = _MATH_KEY_RE.fullmatch(name.upper())
    return (int(match.group(1)) if match else 0, name)


def _split_lrn_setup(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;\r\n]+", text) if part.strip()]


def _read_setup_text(zf: zipfile.ZipFile) -> str:
    for name in zf.namelist():
        if not name.lower().endswith(".set"):
            continue
        try:
            data = zf.read(name)
        except KeyError:
            continue
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data), "r") as setup_zip:
                for inner_name in setup_zip.namelist():
                    if inner_name.lower().endswith(".set"):
                        data = setup_zip.read(inner_name)
                        break
        return data.decode("utf-8", errors="ignore")
    return ""


def _parse_tss_math_setup(zf: zipfile.ZipFile) -> _MathSetup:
    text = _read_setup_text(zf)
    if not text:
        return _MathSetup()

    setup = _MathSetup()
    fields: dict[str, dict[str, str]] = {}
    display_state: dict[str, bool] = {}
    for part in _split_lrn_setup(text):
        if " " in part:
            key, raw_value = part.split(" ", 1)
        else:
            key, raw_value = part, ""
        key_u = key.upper()
        value = _strip_setup_value(raw_value)

        if key_u == ":MAINWINDOW:SOURCEORDER":
            setup.order = [
                _normalize_channel(token)
                for token in value.split(";")
                if re.fullmatch(r"(?:math|m)\d+", token, flags=re.I)
            ]
            continue

        label_match = re.fullmatch(r":(?:(MATH):(MATH\d+)|(CH[1-6])):LABEL:NAME", key_u)
        if label_match:
            label_key = _normalize_channel(label_match.group(2) or label_match.group(3) or "")
            if label_key and value:
                setup.labels[label_key] = value
            continue

        scale_match = re.fullmatch(r":DISPLAY:WAVEVIEW\d+:MATH:(MATH\d+):VERTICAL:SCALE", key_u)
        if scale_match:
            try:
                setup.vdiv[_normalize_channel(scale_match.group(1))] = float(value)
            except ValueError:
                pass
            continue

        pos_match = re.fullmatch(r":DISPLAY:WAVEVIEW\d+:MATH:(MATH\d+):VERTICAL:POSITION", key_u)
        if pos_match:
            try:
                setup.y_position[_normalize_channel(pos_match.group(1))] = float(value)
            except ValueError:
                pass
            continue

        state_match = re.fullmatch(r":DISPLAY:(?:GLOBAL|WAVEVIEW\d+:MATH):(MATH\d+):STATE", key_u)
        if state_match:
            display_state[_normalize_channel(state_match.group(1))] = value != "0"
            continue

        math_match = re.fullmatch(r":MATH:(MATH\d+):(.+)", key_u)
        if not math_match:
            continue
        math_key = _normalize_channel(math_match.group(1))
        fields.setdefault(math_key, {})[math_match.group(2)] = value

    for math_key in sorted(fields, key=_math_sort_key):
        data = fields[math_key]
        expr = data.get("DEFINE", "").strip()
        if not expr:
            func = data.get("FUNCTION", "").upper()
            src1 = _normalize_channel(data.get("SOURCE1", "").strip())
            src2 = _normalize_channel(data.get("SOURCE2", "").strip())
            ops = {
                "ADD": "+",
                "SUBTRACT": "-",
                "MULTIPLY": "*",
                "DIVIDE": "/",
            }
            if func in ops and _CHANNEL_RE.match(src1) and _CHANNEL_RE.match(src2):
                expr = f"{src1}{ops[func]}{src2}"
        if not expr:
            continue
        if display_state and display_state.get(math_key) is False and math_key not in setup.order:
            continue
        setup.formulas[math_key] = _normalise_formula(expr)

    return setup


class _FormulaEvaluator:
    def __init__(self, t: np.ndarray, sources: dict[str, np.ndarray]) -> None:
        self.t = np.asarray(t, dtype=np.float64)
        self.sources = {k.upper(): np.asarray(v, dtype=np.float64) for k, v in sources.items()}

    @staticmethod
    def _logic_array(value) -> np.ndarray:
        return np.asarray(value) != 0

    @staticmethod
    def _logic_float(value) -> np.ndarray:
        return np.asarray(value, dtype=bool).astype(np.float64)

    def _eval(self, node: ast.AST):
        if isinstance(node, ast.Expression):
            return self._eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Only numeric constants are allowed.")
        if isinstance(node, ast.Name):
            name = node.id.upper()
            if name == "PI":
                return float(np.pi)
            if name == "E":
                return float(np.e)
            if name not in self.sources:
                raise ValueError(f"Unknown source: {node.id}")
            return self.sources[name]
        if isinstance(node, ast.UnaryOp):
            val = self._eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -val
            if isinstance(node.op, ast.UAdd):
                return val
            raise ValueError("Unsupported unary operator.")
        if isinstance(node, ast.BinOp):
            left = self._eval(node.left)
            right = self._eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return np.power(left, right)
            if isinstance(node.op, ast.BitAnd):
                return self._logic_float(np.logical_and(self._logic_array(left), self._logic_array(right)))
            if isinstance(node.op, ast.BitOr):
                return self._logic_float(np.logical_or(self._logic_array(left), self._logic_array(right)))
            if isinstance(node.op, ast.BitXor):
                return self._logic_float(np.logical_xor(self._logic_array(left), self._logic_array(right)))
            raise ValueError("Unsupported operator.")
        if isinstance(node, ast.BoolOp):
            vals = [self._eval(v) for v in node.values]
            out = vals[0] != 0
            for val in vals[1:]:
                if isinstance(node.op, ast.And):
                    out = np.logical_and(out, val != 0)
                elif isinstance(node.op, ast.Or):
                    out = np.logical_or(out, val != 0)
                else:
                    raise ValueError("Unsupported boolean operator.")
            return self._logic_float(out)
        if isinstance(node, ast.Compare):
            left = self._eval(node.left)
            out = None
            for op, comp in zip(node.ops, node.comparators):
                right = self._eval(comp)
                if isinstance(op, ast.Eq):
                    cur = left == right
                elif isinstance(op, ast.NotEq):
                    cur = left != right
                elif isinstance(op, ast.Lt):
                    cur = left < right
                elif isinstance(op, ast.LtE):
                    cur = left <= right
                elif isinstance(op, ast.Gt):
                    cur = left > right
                elif isinstance(op, ast.GtE):
                    cur = left >= right
                else:
                    raise ValueError("Unsupported comparison.")
                out = cur if out is None else np.logical_and(out, cur)
                left = right
            return self._logic_float(out)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Unsupported function.")
            name = node.func.id.upper()
            args = [self._eval(arg) for arg in node.args]
            if name in {"INTG", "INTEG"}:
                if len(args) != 1:
                    raise ValueError("INTG() takes one argument.")
                y = np.asarray(args[0], dtype=np.float64)
                out = np.zeros_like(y, dtype=np.float64)
                if len(self.t) != len(y) or len(y) <= 1:
                    return out
                dt = np.diff(self.t)
                out[1:] = np.cumsum(0.5 * (y[1:] + y[:-1]) * dt)
                return out
            if name in {"DERIV", "DDX"}:
                if len(args) != 1:
                    raise ValueError("DERIV() takes one argument.")
                y = np.asarray(args[0], dtype=np.float64)
                if len(self.t) != len(y) or len(y) <= 1:
                    return np.zeros_like(y, dtype=np.float64)
                return np.gradient(y, self.t)
            funcs = {
                "ABS": np.abs,
                "SQRT": np.sqrt,
                "LOG": np.log10,
                "LN": np.log,
                "EXP": np.exp,
                "SIN": np.sin,
                "COS": np.cos,
                "TAN": np.tan,
                "CEIL": np.ceil,
                "FLOOR": np.floor,
                "INV": lambda x: 1.0 / x,
                "MIN": np.minimum if len(args) == 2 else np.nanmin,
                "MAX": np.maximum if len(args) == 2 else np.nanmax,
                "AND": lambda a, b: self._logic_float(np.logical_and(self._logic_array(a), self._logic_array(b))),
                "OR": lambda a, b: self._logic_float(np.logical_or(self._logic_array(a), self._logic_array(b))),
                "XOR": lambda a, b: self._logic_float(np.logical_xor(self._logic_array(a), self._logic_array(b))),
                "NAND": lambda a, b: self._logic_float(~np.logical_and(self._logic_array(a), self._logic_array(b))),
                "NOR": lambda a, b: self._logic_float(~np.logical_or(self._logic_array(a), self._logic_array(b))),
                "EQV": lambda a, b: self._logic_float(~np.logical_xor(self._logic_array(a), self._logic_array(b))),
            }
            if name not in funcs:
                raise ValueError(f"Unsupported function: {name}")
            return funcs[name](*args)
        raise ValueError("Unsupported formula syntax.")

    def evaluate(self, expr: str) -> np.ndarray:
        parsed = ast.parse(_normalise_formula(expr), mode="eval")
        arr = np.asarray(self._eval(parsed), dtype=np.float64)
        if arr.ndim == 0:
            arr = np.full(len(self.t), float(arr), dtype=np.float64)
        if len(arr) != len(self.t):
            raise ValueError("Formula result length does not match the waveform.")
        return arr


class TssParser:
    """Parse Tektronix session (.tss) files — ZIP archives of .wfm waveforms."""

    def parse(self, path: str | Path) -> WaveformBundle:
        path = Path(path)
        if not zipfile.is_zipfile(path):
            raise ValueError("TSS 会话: 文件不是有效的 ZIP/TSS 格式")

        channels: dict[str, np.ndarray] = {}
        labels: dict[str, str] = {}
        vdiv: dict[str, float] = {}
        y_position: dict[str, float] = {}
        meta = TekMetadata()
        t_ref: np.ndarray | None = None

        with zipfile.ZipFile(path, "r") as zf:
            math_setup = _parse_tss_math_setup(zf)
            wfm_members = sorted(
                name
                for name in zf.namelist()
                if name.lower().endswith(".wfm")
                and not name.startswith("__MACOSX/")
                and not PurePosixPath(name).name.startswith(".")
            )
            if not wfm_members:
                raise ValueError("TSS 会话: 未找到 .wfm 波形文件")

            with tempfile.TemporaryDirectory(prefix="dpt_tss_") as tmp:
                tmp_path = Path(tmp)
                for member in wfm_members:
                    channel = _channel_from_member(member)
                    local = tmp_path / PurePosixPath(member).name
                    with zf.open(member) as src, open(local, "wb") as dst:
                        dst.write(src.read())

                    wfm = read_file(str(local))
                    if not _looks_like_analog_waveform(wfm):
                        continue

                    channel = channel or _channel_from_waveform(wfm)
                    if not channel or channel in channels:
                        continue

                    t, y = _waveform_arrays(wfm)
                    if y.size == 0:
                        continue

                    channels[channel] = y
                    if t_ref is None:
                        t_ref = t
                        meta.sample_interval = _sample_interval_from_time(
                            t, float(wfm.x_axis_spacing or meta.sample_interval)
                        )
                        meta.zero_index = float(wfm.trigger_index or 0.0)
                        meta.record_length = int(y.size)
                        if wfm.meta_info is not None:
                            equipment = getattr(wfm.meta_info, "test_equipment", None)
                            if equipment:
                                meta.model = str(equipment)

                    label = ""
                    if wfm.meta_info and wfm.meta_info.waveform_label:
                        label = wfm.meta_info.waveform_label.strip()
                    if label:
                        labels[channel] = label

                    scale = read_wfm_vertical_scale_per_div(local)
                    if scale is not None:
                        vdiv[channel] = scale
                    if wfm.meta_info is not None and wfm.meta_info.y_position is not None:
                        y_position[channel] = float(wfm.meta_info.y_position)

        if not channels or t_ref is None:
            raise ValueError("TSS 会话: 未能解析有效波形通道")

        n = len(t_ref)
        for ch, y in list(channels.items()):
            if len(y) != n:
                channels[ch] = y[:n] if len(y) > n else np.pad(y, (0, n - len(y)))

        if math_setup.formulas:
            math_order = math_setup.order or sorted(math_setup.formulas, key=_math_sort_key)
            for math_key in math_order:
                if math_key in channels or math_key not in math_setup.formulas:
                    continue
                try:
                    channels[math_key] = _FormulaEvaluator(t_ref, channels).evaluate(
                        math_setup.formulas[math_key]
                    )
                except (SyntaxError, ValueError, ZeroDivisionError, FloatingPointError):
                    continue
            for math_key in sorted(math_setup.formulas, key=_math_sort_key):
                if math_key in channels:
                    continue
                try:
                    channels[math_key] = _FormulaEvaluator(t_ref, channels).evaluate(
                        math_setup.formulas[math_key]
                    )
                except (SyntaxError, ValueError, ZeroDivisionError, FloatingPointError):
                    continue

        meta.source_path = str(path.resolve())
        meta.channel_labels = labels
        meta.channel_labels.update(math_setup.labels)
        meta.channel_vdiv = vdiv
        meta.channel_vdiv.update(math_setup.vdiv)
        meta.channel_y_position = y_position
        meta.channel_y_position.update(math_setup.y_position)
        meta.channel_math_formulas = {
            key: expr for key, expr in math_setup.formulas.items() if key in channels
        }
        meta.record_length = n
        return WaveformBundle(t=t_ref, channels=channels, meta=meta)
