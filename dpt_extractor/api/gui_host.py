"""GUI 主进程内嵌 API 服务的薄封装。

``main_window`` 只调用 :func:`ensure_running` / :func:`shutdown`，不关心
线程、端口与异常细节；并且所有失败都被吞成 ``None``，API 不可用绝不能
拖垮 GUI 主流程。
"""

from __future__ import annotations

import secrets
import threading
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt, pyqtSignal

from dpt_extractor.api.server import ApiServerHandle, start_in_thread

#: 访问令牌默认持久化到用户数据目录，GUI 与外部调用方共享同一份。
_TOKEN_FILE_NAME = "api_token.txt"

_lock = threading.Lock()
_handle: ApiServerHandle | None = None
_last_error: str | None = None
_active_token: str | None = None


class GuiDispatcher(QObject):
    """把 Python 可调用对象从任意线程投递到 Qt 主线程执行。

    ``_requested`` 信号跨线程 emit 时，Qt 自动按 QueuedConnection 排队到
    构造本对象所在线程（即 Qt 主线程）的事件循环，因此是唯一安全的
    「API 后台线程 -> 主窗口控件」入口。
    """

    _requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._requested.connect(self._execute, Qt.ConnectionType.QueuedConnection)

    def _execute(self, job: Callable[[], None]) -> None:
        job()


class GuiCall:
    """一次跨线程调用的结果信箱。"""

    __slots__ = ("done", "result", "error", "abandoned")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None
        self.abandoned = False


class GuiReportWaiter:
    """GUI 报告流水线的跨线程完成信号。

    API 线程提交写入任务后阻塞在 :attr:`done`；GUI 在写入成功、失败或
    截图异常时调用 :meth:`finish` 唤醒。``abandoned`` 用来丢弃超时后迟到
    的终态，避免污染下一次请求。
    """

    __slots__ = ("done", "ok", "result", "error", "detail", "abandoned")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.ok = False
        self.result: dict[str, Any] = {}
        self.error = ""
        self.detail = ""
        self.abandoned = False

    def finish(
        self,
        *,
        ok: bool,
        result: dict[str, Any] | None = None,
        error: str = "",
        detail: str = "",
    ) -> None:
        if self.abandoned:
            self.done.set()
            return
        self.ok = bool(ok)
        self.result = dict(result or {})
        self.error = str(error)
        self.detail = str(detail)
        self.done.set()


_gui_bridge: Any = None
_dispatcher: GuiDispatcher | None = None


def register_gui_bridge(bridge: Any, *, dispatcher: GuiDispatcher | None = None) -> None:
    """登记 GUI 主窗口与跨线程派发器；两者都必须在 Qt 主线程构造。"""
    global _gui_bridge, _dispatcher
    with _lock:
        _gui_bridge = bridge
        if dispatcher is not None:
            _dispatcher = dispatcher


def get_gui_bridge() -> Any | None:
    with _lock:
        return _gui_bridge


def create_dispatcher() -> GuiDispatcher:
    """在 Qt 主线程创建派发器并立即登记，返回同一实例。"""
    dispatcher = GuiDispatcher()
    register_gui_bridge(get_gui_bridge(), dispatcher=dispatcher)
    return dispatcher


def has_bridge() -> bool:
    with _lock:
        return _gui_bridge is not None and _dispatcher is not None


def call_sync(fn: Callable[[], Any] | None, *, timeout: float = 120.0) -> Any:
    """在 GUI 主线程同步执行 ``fn`` 并把结果（或异常）带回调用线程。

    没有运行中的主线程事件循环时抛 ``RuntimeError``；超时抛
    ``TimeoutError`` 并把该次作业标记为放弃，防止迟到执行污染后续状态。
    """
    with _lock:
        dispatcher = _dispatcher
    if dispatcher is None:
        raise RuntimeError("GUI 派发器未注册：API 服务需要由 GUI 主窗口启动")
    if fn is None:
        raise RuntimeError("GUI 派发器收到空任务")

    call = GuiCall()

    def job() -> None:
        if call.abandoned:
            call.done.set()
            return
        try:
            call.result = fn()
        except BaseException as exc:  # noqa: BLE001 - 原样回传调用线程
            call.error = exc
        finally:
            call.done.set()

    dispatcher._requested.emit(job)
    if not call.done.wait(timeout):
        call.abandoned = True
        raise TimeoutError(f"GUI 主线程派发超时（{timeout:.0f}s）")
    if call.error is not None:
        raise call.error
    return call.result


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