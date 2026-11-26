"""Qt 界面库加载失败时的启动诊断。

打包后的 exe 在目标机器上缺系统 DLL（例如 Qt6Gui 直接依赖的 ``d3d12.dll``）、
运行库不匹配或被安全软件拦截时，PyInstaller 只会弹出英文 traceback，现场无法
判断到底缺什么。本模块只做三件事：

1. 收集现场：程序版本、打包形态、Windows 版本/架构、关键 DLL 在哪些目录里
   找到或缺失、Qt 的 DLL 搜索目录是否齐全；
2. 把同一份现场写入日志文件（优先 exe 同目录，不可写时退回 ``%TEMP%``）；
3. 用 ``ctypes`` 弹一个中文提示框，请用户把日志发回来。

它**不导入 Qt**，因此 Qt 挂掉时仍能运行；也**不改变正常运行路径**——只有
``main.py`` 的 Qt 导入抛出异常时才会被调用。
"""
from __future__ import annotations

import os
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from dpt_extractor import __version__

LOG_FILE_NAME = "DPT_startup_failure.txt"
MESSAGE_BOX_TITLE = "DPT 启动失败"

#: (用途说明, 文件名)。顺序即日志里的输出顺序。
_REQUIRED_DLLS: tuple[tuple[str, str], ...] = (
    ("Qt 核心", "Qt6Core.dll"),
    ("Qt 图形", "Qt6Gui.dll"),
    ("Qt 控件", "Qt6Widgets.dll"),
    ("Qt 平台插件", "qwindows.dll"),
    ("C++ 运行库", "MSVCP140.dll"),
    ("C++ 运行库", "MSVCP140_1.dll"),
    ("C++ 运行库", "MSVCP140_2.dll"),
    ("C 运行库", "VCRUNTIME140.dll"),
    ("C 运行库", "VCRUNTIME140_1.dll"),
    ("通用 C 运行库", "ucrtbase.dll"),
    # Qt6Gui 直接依赖这三个系统 DLL：Win7/8.1 没有 d3d12，精简系统可能缺 dwrite。
    ("系统 DLL（Qt6Gui 依赖）", "d3d12.dll"),
    ("系统 DLL（Qt6Gui 依赖）", "d3d11.dll"),
    ("系统 DLL（Qt6Gui 依赖）", "dwrite.dll"),
)


def _candidate_dirs() -> list[Path]:
    """Qt 实际搜索 DLL 的目录，按优先级排列。"""
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        dirs.append(exe_dir)
        mei = getattr(sys, "_MEIPASS", None)
        if mei:
            root = Path(mei)
            dirs.extend(
                [
                    root,
                    root / "PyQt6" / "Qt6" / "bin",
                    root / "PyQt6" / "Qt6" / "plugins" / "platforms",
                ]
            )
    else:
        here = Path(__file__).resolve()
        repo_root = here.parents[2]
        dirs.append(repo_root)
        try:
            import PyQt6  # noqa: F401 - 只为定位开发环境的 Qt6 目录

            qt6 = Path(PyQt6.__file__).resolve().parent / "Qt6"
            dirs.extend([qt6 / "bin", qt6 / "plugins" / "platforms"])
        except Exception:  # noqa: BLE001 - 定位失败不影响诊断输出
            pass

    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    dirs.append(Path(system_root) / "System32")
    return dirs


def probe_required_dlls(dirs: Sequence[Path] | None = None) -> list[str]:
    """逐个检查关键 DLL，返回「找到」或「缺失」的可读行。"""
    search = list(dirs) if dirs is not None else _candidate_dirs()
    lines: list[str] = []
    for usage, name in _REQUIRED_DLLS:
        found_at = None
        for directory in search:
            try:
                if (directory / name).is_file():
                    found_at = directory
                    break
            except OSError:
                continue
        if found_at is None:
            lines.append(f"  缺失  {name}（{usage}）—— 已搜索 {len(search)} 个目录")
        else:
            lines.append(f"  找到  {name}（{usage}）→ {found_at}")
    return lines


def _windows_description() -> str:
    if sys.platform != "win32":
        return f"{sys.platform}（非 Windows，Qt 依赖无法按 Windows 规则核对）"
    try:
        info = sys.getwindowsversion()
    except Exception:  # noqa: BLE001 - 诊断信息缺失不应再抛异常
        return "Windows（版本号读取失败）"
    return f"Windows {info.major}.{info.minor}.{info.build}"


def _arch_description() -> str:
    machine = platform.machine() or "未知架构"
    bits = "64 位" if sys.maxsize > 2**32 else "32 位"
    return f"{machine} / {bits}"


def _runtime_description() -> str:
    if getattr(sys, "frozen", False):
        return "打包运行（PyInstaller 单文件）"
    return f"源码运行（{Path(sys.executable).resolve()}）"


def collect_diagnostics(
    exc: BaseException | None = None,
    search_dirs: Sequence[Path] | None = None,
) -> str:
    """生成诊断正文（不含日志路径与提示语）。"""
    search = list(search_dirs) if search_dirs is not None else _candidate_dirs()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = [
        f"时间        : {now}",
        f"程序版本    : DPT {__version__}",
        f"运行形态    : {_runtime_description()}",
        f"操作系统    : {_windows_description()}",
        f"CPU 架构    : {_arch_description()}",
        f"Python      : {sys.version.split()[0]}",
        f"可执行文件  : {sys.executable}",
        "",
        "关键文件检查（Qt 界面库依赖）：",
        *probe_required_dlls(search),
        "",
        "已搜索的目录：",
        *(f"  {d}" for d in search),
    ]
    if exc is not None:
        lines.extend(
            [
                "",
                "异常：",
                "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ).rstrip(),
            ]
        )
    return "\n".join(lines)


def _log_candidates(log_dir: Path | None) -> Iterable[Path]:
    if log_dir is not None:
        yield Path(log_dir) / LOG_FILE_NAME
        return
    if getattr(sys, "frozen", False):
        yield Path(sys.executable).resolve().parent / LOG_FILE_NAME
    else:
        yield Path(__file__).resolve().parents[2] / LOG_FILE_NAME
    temp = os.environ.get("TEMP") or os.environ.get("TMP")
    if temp:
        yield Path(temp) / LOG_FILE_NAME


def write_failure_log(text: str, log_dir: Path | None = None) -> Path | None:
    """写入日志，返回实际路径；全部候选目录都不可写时返回 ``None``。"""
    for target in _log_candidates(log_dir):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            return target
        except OSError:
            continue
    return None


def format_failure_message(log_path: Path | None, exc: BaseException | None = None) -> str:
    """弹出框正文：用户视角的结论 + 日志位置，不放整段 traceback。"""
    if log_path is not None:
        tail = f"详细现场已写入：\n{log_path}\n\n请把这个文件发给开发同事。"
    else:
        tail = "详细现场无法写入磁盘（目录不可写），请截图本窗口发给开发同事。"
    reason = ""
    if exc is not None:
        text = f"{type(exc).__name__}: {exc}".strip()
        if len(text) > 300:
            text = text[:300] + "…"
        reason = f"\n\n错误信息：\n{text}"
    return (
        "DPT 的界面库（Qt）没能加载，程序无法启动。\n\n"
        "常见原因是这台电脑缺少 Qt 依赖的系统组件或运行库，"
        "或安全软件拦截了程序目录里的 DLL。\n"
        f"{reason}\n\n{tail}"
    )


def show_message_box(text: str) -> bool:
    """在没有 Qt 的情况下弹一个 Windows 错误提示框。"""
    if sys.platform != "win32":
        try:
            print(text, file=sys.stderr)
        except OSError:
            pass
        return False
    try:
        import ctypes

        # MB_OK | MB_ICONERROR | MB_SETFOREGROUND
        ctypes.windll.user32.MessageBoxW(None, text, MESSAGE_BOX_TITLE, 0x00000000 | 0x00000010 | 0x00010000)
        return True
    except Exception:  # noqa: BLE001 - 弹窗失败只能退回控制台输出
        try:
            print(text, file=sys.stderr)
        except OSError:
            pass
        return False


def report_startup_failure(
    exc: BaseException,
    *,
    show_dialog: bool = True,
    log_dir: Path | None = None,
    search_dirs: Sequence[Path] | None = None,
) -> int:
    """收集现场、写日志、弹提示，返回建议的进程退出码。"""
    try:
        diagnostics = collect_diagnostics(exc, search_dirs=search_dirs)
    except Exception:  # noqa: BLE001 - 诊断本身出错也要给出可读结果
        diagnostics = f"诊断信息收集失败：{exc!r}"
    log_path = write_failure_log(diagnostics, log_dir=log_dir)
    message = format_failure_message(log_path, exc)
    if show_dialog:
        show_message_box(message)
    else:
        try:
            print(message, file=sys.stderr)
        except OSError:
            pass
    return 1
