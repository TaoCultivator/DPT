"""Local HTTP/JSON protocol shell for :class:`ApiService`.

只使用 Python 标准库 ``http.server``：不引入 aiohttp/flask/fastapi，避免打包
体积与 PyInstaller 隐藏依赖问题。

两种启动方式：

1. 独立进程::

       python -m dpt_extractor.api.server --port 8765

2. GUI 主进程内后台线程::

       from dpt_extractor.api import start_in_thread

       handle = start_in_thread(port=8765)
       ...
       handle.stop()

协议约定（保持极简，便于自动化代理直连）：

- 只有一个写入口 ``POST /rpc``，body 为 ``{"command": str, "params": {...}}``。
- 成功返回 ``200`` 且 ``{"ok": true, "command": ..., "data": ...}``。
- 业务失败返回 ``200`` 且 ``{"ok": false, "error": {...}}``；协议/参数错误返回 4xx。
- ``GET /health`` 与 ``GET /status`` 为免鉴权快速探针。
- 配置了 token 时，``/rpc`` 必须带 ``X-DPT-Token`` 头或 ``?token=``。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dpt_extractor.api.service import ApiError, ApiService

#: 打包/冻结环境下，服务端不应把 traceback 原文抛给调用方以外的地方，
#: 但本地单机代理场景保留 detail 更利于排障，故默认开启。
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 8 * 1024 * 1024


class _Handler(BaseHTTPRequestHandler):
    server_version = "DPTApi/1.0"
    #: 由 :func:`create_server` 注入。
    service: ApiService
    token: str | None = None

    # ------------------------------------------------------------ 基础设施

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # 默认实现写 stderr，GUI 进程里会污染控制台；改为静默，仅保留致命错误。
        if getattr(self, "_verbose", False):
            super().log_message(fmt, *args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0") or "0"
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ApiError("bad_content_length", "Content-Length 不是整数") from exc
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ApiError("body_too_large", f"请求体超过 {MAX_BODY_BYTES} 字节上限")
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("bad_json", "请求体不是合法 JSON") from exc
        if not isinstance(parsed, dict):
            raise ApiError("bad_payload", "请求体必须是 JSON 对象")
        return parsed

    def _check_token(self) -> None:
        if not self.token:
            return
        header = self.headers.get("X-DPT-Token")
        if header == self.token:
            return
        query = parse_qs(urlparse(self.path).query)
        if (query.get("token") or [""])[0] == self.token:
            return
        raise ApiError("unauthorized", "缺少或错误的访问令牌")

    # ------------------------------------------------------------ 路由

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path in ("/health", "/healthz"):
                self._send_json(HTTPStatus.OK, {"ok": True, "data": self.service.health()})
                return
            if path == "/status":
                self._send_json(HTTPStatus.OK, {"ok": True, "data": self.service.status()})
                return
            if path in ("/", "/index"):
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "service": "dpt-extractor-api",
                        "protocol": "POST /rpc {command, params}",
                        "endpoints": ["/health", "/status", "/rpc"],
                    },
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "not_found", "message": path}})
        except Exception as exc:  # pragma: no cover - 兜底
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "internal_error", "message": str(exc)}},
            )

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/rpc":
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "not_found", "message": path}})
            return
        try:
            self._check_token()
            body = self._read_body()
            command = body.get("command")
            if not isinstance(command, str) or not command:
                raise ApiError("missing_command", "缺少 command 字段")
            params = body.get("params") or {}
            if not isinstance(params, dict):
                raise ApiError("bad_params", "params 必须是 JSON 对象")
            data = self.service.dispatch(command, params)
            self._send_json(
                HTTPStatus.OK, {"ok": True, "command": command, "data": data}
            )
        except ApiError as exc:
            self._send_json(
                HTTPStatus.OK, {"ok": False, "error": exc.to_dict()}
            )
        except KeyError as exc:
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": False,
                    "error": {
                        "code": "missing_param",
                        "message": f"缺少必需参数：{exc}",
                    },
                },
            )
        except (TypeError, ValueError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "bad_request", "message": str(exc)}},
            )
        except Exception as exc:  # pragma: no cover - 兜底
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": {"code": "internal_error", "message": str(exc)}},
            )


class ApiServerHandle:
    """对运行中的服务句柄，支持在 GUI 里优雅停掉后台线程。"""

    def __init__(
        self,
        server: ThreadingHTTPServer,
        thread: threading.Thread | None = None,
    ) -> None:
        self._server = server
        self._thread = thread

    @property
    def host(self) -> str:
        return str(self._server.server_address[0])

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def __enter__(self) -> "ApiServerHandle":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.stop()


def create_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    service: ApiService | None = None,
    token: str | None = None,
) -> tuple[ThreadingHTTPServer, ApiService]:
    """构造（但不启动）HTTP 服务，返回 ``(server, service)``。

    ``port=0`` 会由系统分配空闲端口，适合测试与 GUI 内嵌。
    """
    svc = service or ApiService()

    handler_cls = type(
        "DPTApiHandler",
        (_Handler,),
        {"service": svc, "token": token},
    )
    server = ThreadingHTTPServer((host, port), handler_cls)
    server.daemon_threads = True
    return server, svc


def serve_forever(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    service: ApiService | None = None,
    token: str | None = None,
) -> None:
    """在当前线程阻塞式运行服务（用于独立进程入口）。"""
    server, _svc = create_server(host=host, port=port, service=service, token=token)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def start_in_thread(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    service: ApiService | None = None,
    token: str | None = None,
    daemon: bool = True,
) -> ApiServerHandle:
    """在后台线程启动服务，返回可 :meth:`ApiServerHandle.stop` 的句柄。

    GUI 主进程调用示例::

        handle = start_in_thread(port=0)   # 随机空闲端口
        print(handle.base_url)             # http://127.0.0.1:53421
    """
    server, _svc = create_server(host=host, port=port, service=service, token=token)
    thread = threading.Thread(
        target=server.serve_forever,
        name="dpt-api-server",
        daemon=daemon,
    )
    thread.start()
    return ApiServerHandle(server, thread)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m dpt_extractor.api.server",
        description="DPT local HTTP/JSON API server",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口（默认 8765）")
    parser.add_argument("--token", default=None, help="可选访问令牌，启用后 /rpc 必须携带")
    return parser


def main(argv: list[str] | None = None) -> int:
    import os

    # 与 CLI 一致：在导入重依赖前钉住 numba 缓存目录。
    from dpt_extractor.utils.app_paths import configure_numba_cache_dir

    configure_numba_cache_dir()

    args = _build_parser().parse_args(argv)
    token = args.token or os.environ.get("DPT_API_TOKEN") or None
    print(
        f"[dpt-api] serving on http://{args.host}:{args.port} "
        f"(token={'on' if token else 'off'})",
        file=sys.stderr,
        flush=True,
    )
    serve_forever(host=args.host, port=args.port, token=token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())