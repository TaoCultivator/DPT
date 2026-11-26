#!/usr/bin/env python3
"""DPT parameter extraction tool entry point."""

import argparse
import sys
from pathlib import Path

# Ensure package root on path when run as script
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _restart_with_local_venv() -> None:
    """Run the app with the project virtual environment when available."""
    if sys.prefix == sys.base_prefix:
        venv_python = _ROOT / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists() and Path(sys.executable).resolve() != venv_python.resolve():
            import os

            os.execv(str(venv_python), [str(venv_python), *sys.argv])


if __name__ == "__main__":
    _restart_with_local_venv()

from dpt_extractor.utils.text_encoding import configure_utf8_text_io
from dpt_extractor.utils.app_paths import configure_numba_cache_dir

configure_utf8_text_io()
configure_numba_cache_dir()

try:
    from PyQt6.QtWidgets import QApplication

    from dpt_extractor.gui.main_window import MainWindow
    from dpt_extractor.io.tek_scope import shutdown_tektronix_backend
except Exception as _gui_import_error:  # noqa: BLE001 - 启动期任何异常都要给出可读提示
    # 打包成 exe 后窗口模式只会弹一个英文 traceback（"DLL load failed while
    # importing QtWidgets"）；换成中文诊断 + 现场日志，便于远程定位缺什么。
    from dpt_extractor.utils.qt_bootstrap import report_startup_failure

    raise SystemExit(report_startup_failure(_gui_import_error)) from None


def _parse_cli(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """解析本程序自有参数，其余原样交给 Qt。"""
    parser = argparse.ArgumentParser(
        prog="DPT",
        description="DPT 双脉冲参数提取工具",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="启动时开启内嵌 API 服务（默认关闭，避免测试与多开实例抢端口）",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=8765,
        help="内嵌 API 监听端口（默认 8765，0 表示由系统分配）",
    )
    args, remaining = parser.parse_known_args(argv)
    return args, remaining


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args, qt_argv = _parse_cli(raw_argv)
    app = QApplication([sys.argv[0], *qt_argv])
    app.setApplicationName("DPT Extractor")
    app.setStyle("Fusion")
    win = MainWindow()
    win.showMaximized()
    # 显式请求才点火：GUI 启动本身不占用任何端口。
    if args.api:
        win.start_api_server(port=args.api_port)
    try:
        return app.exec()
    finally:
        # Covers programmatic quit and startup/teardown paths that do not pass
        # through MainWindow.closeEvent().  The function is idempotent.
        win.shutdown_background_work()
        shutdown_tektronix_backend()


if __name__ == "__main__":
    raise SystemExit(main())
