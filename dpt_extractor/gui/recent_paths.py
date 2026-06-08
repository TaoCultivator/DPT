"""记住上次打开 TSS、保存 Excel 的路径（QSettings 持久化）。"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings

_ORG = "DPT"
_APP = "DPTExtractor"
_KEY_LAST_OPEN = "paths/last_open"
_KEY_LAST_EXPORT = "paths/last_export"


def _settings() -> QSettings:
    return QSettings(_ORG, _APP)


def _valid_file_path(raw: object) -> Path | None:
    if not raw or not isinstance(raw, str):
        return None
    p = Path(raw)
    if p.is_file():
        return p
    return None


def _valid_dir(raw: object) -> Path | None:
    if not raw or not isinstance(raw, str):
        return None
    p = Path(raw)
    if p.is_dir():
        return p
    parent = p.parent
    if parent.is_dir():
        return parent
    return None


def last_open_path() -> Path | None:
    """上次成功打开的 TSS 完整路径。"""
    return _valid_file_path(_settings().value(_KEY_LAST_OPEN, ""))


def set_last_open_path(path: str | Path) -> None:
    p = Path(path)
    if p.is_file():
        _settings().setValue(_KEY_LAST_OPEN, str(p.resolve()))


def last_export_path() -> Path | None:
    """上次成功导出的 Excel 完整路径。"""
    return _valid_file_path(_settings().value(_KEY_LAST_EXPORT, ""))


def set_last_export_path(path: str | Path) -> None:
    p = Path(path)
    if p.suffix.lower() != ".xlsx":
        p = p.with_suffix(".xlsx")
    _settings().setValue(_KEY_LAST_EXPORT, str(p.resolve()))


def open_dialog_start_dir(fallback: str | Path) -> str:
    """打开 TSS 对话框的初始目录。"""
    last = last_open_path()
    if last is not None:
        return str(last.parent)
    fb = _valid_dir(fallback)
    if fb is not None:
        return str(fb)
    return str(Path(fallback))


def save_dialog_initial_path(suggested: str | Path) -> str:
    """
    保存 Excel 对话框的初始路径：优先「上次保存目录 + 本次建议文件名」。
    """
    suggested = Path(suggested)
    if suggested.suffix.lower() != ".xlsx":
        suggested = suggested.with_suffix(".xlsx")
    last = last_export_path()
    if last is not None and last.parent.is_dir():
        return str(last.parent / suggested.name)
    if suggested.parent.is_dir():
        return str(suggested)
    return str(suggested.name)
