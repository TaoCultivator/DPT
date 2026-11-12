"""GUI 主进程内嵌 API 服务的薄封装。

``main_window`` 只调用 :func:`ensure_running` / :func:`shutdown`，不关心
线程、端口与异常细节；并且所有失败都被吞成 ``None``，API 不可用绝不能
拖垮 GUI 主流程。
"""

from __future__ import annotations

import secrets
import threading
from pathlib import Path
from typing import Any

from dpt_extractor.api.server import ApiServerHandle, start_in_thread

#: 访问令牌默认持久化到用户数据目录，GUI 与外部调用方共享同一份。
_TOKEN_FILE_NAME = "api_token.txt"

_lock = threading.Lock()
_handle: ApiServerHandle | None = None
_last_error: str | None = None
_active_token: str | None = None


def _token_path() -> Path:
    from dpt_extractor.utils.app_paths import user_data_dir

    return user_data_dir() / _TOKEN_FILE_NAME


def ensure_token(token: str | None = None) -> str:
    """返回生效的访问令牌。

    显式给出时直接采用；否则读取本机持久令牌，缺失或为空时生成新令牌并落盘。
    任何磁盘异常都不阻断启动——退化为进程内临时令牌，但依旧强制鉴权。
    """
    if token:
        return token
    path = _token_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    generated = secrets.token_urlsafe(24)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generated, encoding="utf-8")
    except OSError:
        pass
    return generated


def current_token() -> str | None:
    """返回当前生效的令牌；服务未运行时返回 ``None``。"""
    with _lock:
        if _handle is not None and _handle.is_running():
            return _active_token
        return None


def ensure_running(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    service: Any = None,
) -> ApiServerHandle | None:
    """幂等启动内嵌服务；已在跑则直接返回既有句柄。

    ``token`` 省略时自动读取/生成本机持久令牌，鉴权层默认生效，
    不再出现「令牌为空 = 整个 /rpc 敞开」的默认配置。
    """
    global _handle, _last_error, _active_token
    with _lock:
        if _handle is not None and _handle.is_running():
            return _handle
        try:
            effective = ensure_token(token)
            _handle = start_in_thread(
                host=host, port=port, token=effective, service=service
            )
            _active_token = effective
            _last_error = None
            return _handle
        except Exception as exc:  # 端口占用等：不阻断 GUI
            _handle = None
            _active_token = None
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
    global _handle, _active_token
    with _lock:
        handle, _handle = _handle, None
        _active_token = None
    if handle is not None:
        try:
            handle.stop(timeout=timeout)
        except Exception:
            pass