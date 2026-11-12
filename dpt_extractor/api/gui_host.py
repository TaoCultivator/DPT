"""GUI 主进程内嵌 API 服务的薄封装。

``main_window`` 只调用 :func:`ensure_running` / :func:`shutdown`，不关心
线程、端口与异常细节；并且所有失败都被吞成 ``None``，API 不可用绝不能
拖垮 GUI 主流程。
"""

from __future__ import annotations

import threading
from typing import Any

from dpt_extractor.api.server import ApiServerHandle, start_in_thread

_lock = threading.Lock()
_handle: ApiServerHandle | None = None
_last_error: str | None = None


def ensure_running(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    service: Any = None,
) -> ApiServerHandle | None:
    """幂等启动内嵌服务；已在跑则直接返回既有句柄。"""
    global _handle, _last_error
    with _lock:
        if _handle is not None and _handle.is_running():
            return _handle
        try:
            _handle = start_in_thread(
                host=host, port=port, token=token, service=service
            )
            _last_error = None
            return _handle
        except Exception as exc:  # 端口占用等：不阻断 GUI
            _handle = None
            _last_error = f"{type(exc).__name__}: {exc}"
            return None


def current_url() -> str | None:
    with _lock:
        if _handle is not None and _handle.is_running():
            return _handle.base_url
        return None


def last_error() -> str | None:
    with _lock:
        return _last_error


def shutdown(*, timeout: float = 5.0) -> None:
    """停止内嵌服务；重复调用安全。"""
    global _handle
    with _lock:
        handle, _handle = _handle, None
    if handle is not None:
        try:
            handle.stop(timeout=timeout)
        except Exception:
            pass