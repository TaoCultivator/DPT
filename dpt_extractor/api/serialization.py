"""JSON-safe conversion for DPT result objects.

``ExtractResult`` 里混着 dataclass、numpy 数组、``set[tuple]`` 和以 tuple 为
键的上下文字典。直接 ``dataclasses.asdict`` 会失败或产生无法序列化的对象，
本模块统一处理这些形态，并对大数组只给摘要，避免把整段示波器波形塞进 API
响应。
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np


def _scalar(value: Any) -> Any:
    """Convert numpy scalars / non-finite floats into JSON-safe values."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    return value


def _array_to_summary(array: np.ndarray, max_items: int) -> dict[str, Any]:
    flat = np.asarray(array, dtype=np.float64).reshape(-1)
    finite = flat[np.isfinite(flat)]
    summary: dict[str, Any] = {
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "size": int(array.size),
        "finite_count": int(finite.size),
    }
    if finite.size:
        summary.update(
            {
                "min": float(np.min(finite)),
                "max": float(np.max(finite)),
                "mean": float(np.mean(finite)),
                "first": float(finite[0]),
                "last": float(finite[-1]),
            }
        )
    if max_items > 0 and finite.size <= max_items:
        summary["values"] = [float(v) for v in finite]
    return summary


def _key(value: Any) -> str:
    """Stable string key for dict keys that may be tuples."""
    if isinstance(value, str):
        return value
    if isinstance(value, tuple):
        return "/".join(str(item) for item in value)
    return str(value)


def to_jsonable(
    value: Any,
    *,
    array_mode: str = "summary",
    max_array_items: int = 0,
) -> Any:
    """Recursively convert *value* into JSON-compatible primitives.

    ``array_mode``:
        ``"summary"`` (default) reports shape and basic statistics only.
        ``"list"`` returns the flat list of finite values.
        ``"none"`` drops arrays entirely.
    """

    if isinstance(value, np.ndarray):
        if array_mode == "none":
            return None
        if array_mode == "list":
            flat = np.asarray(value, dtype=np.float64).reshape(-1)
            finite = flat[np.isfinite(flat)]
            if max_array_items > 0:
                finite = finite[:max_array_items]
            return [float(v) for v in finite]
        return _array_to_summary(value, max_array_items)

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out: dict[str, Any] = {}
        for field in dataclasses.fields(value):
            # 提取阶段缓存的上下文字典体积大且不可 JSON 化，只暴露其键。
            if field.name.endswith("_contexts"):
                contexts = getattr(value, field.name)
                out[field.name] = sorted(_key(k) for k in contexts) if contexts else []
                continue
            out[field.name] = to_jsonable(
                getattr(value, field.name),
                array_mode=array_mode,
                max_array_items=max_array_items,
            )
        return out

    if isinstance(value, Mapping):
        return {
            _key(k): to_jsonable(
                v,
                array_mode=array_mode,
                max_array_items=max_array_items,
            )
            for k, v in value.items()
        }

    if isinstance(value, (set, frozenset)):
        return sorted(
            to_jsonable(
                item,
                array_mode=array_mode,
                max_array_items=max_array_items,
            )
            for item in value
        )

    if isinstance(value, (list, tuple)):
        return [
            to_jsonable(
                item,
                array_mode=array_mode,
                max_array_items=max_array_items,
            )
            for item in value
        ]

    return _scalar(value)


def result_to_dict(
    result: Any,
    *,
    array_mode: str = "summary",
    max_array_items: int = 0,
) -> dict[str, Any]:
    """Convert one ``ExtractResult`` (or a compatible object) into a dict."""
    if not (dataclasses.is_dataclass(result) and not isinstance(result, type)):
        raise TypeError(
            f"result_to_dict 需要 dataclass 实例，实际收到 {type(result).__name__}"
        )
    payload = to_jsonable(
        result,
        array_mode=array_mode,
        max_array_items=max_array_items,
    )
    if not isinstance(payload, dict):
        raise TypeError("result_to_dict 需要 dataclass 形态的结果对象")
    return payload