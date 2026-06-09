"""记住上次打开 TSS、保存 Excel 的路径（QSettings 持久化）。"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings

_ORG = "DPT"
_APP = "DPTExtractor"
_KEY_LAST_OPEN = "paths/last_open"
_KEY_LAST_EXPORT = "paths/last_export"
_KEY_REPORT_TEMPLATE_LEGACY = "paths/report_template"
_KEY_REPORT_TEMPLATE_SOURCE = "paths/report_template_source"
_KEY_REPORT_OUTPUT = "paths/report_output"


def _settings() -> QSettings:
    return QSettings(_ORG, _APP)


def _valid_file_path(raw: object) -> Path | None:
    if not raw or not isinstance(raw, str):
        return None
    p = Path(raw)
    if p.is_file():
        return p
    return None


def _valid_xlsx_file_path(raw: object) -> Path | None:
    p = _valid_file_path(raw)
    if p is not None and p.suffix.lower() == ".xlsx":
        return p
    return None


def _valid_xlsx_output_path(raw: object) -> Path | None:
    if not raw or not isinstance(raw, str):
        return None
    p = Path(raw)
    if p.suffix.lower() != ".xlsx":
        p = p.with_suffix(".xlsx")
    if p.is_file() or p.parent.is_dir():
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


def report_template_path() -> Path | None:
    """上次加载的报告模板源文件。"""
    return report_template_source_path()


def set_report_template_path(path: str | Path) -> None:
    set_report_template_source_path(path)


def report_template_source_path() -> Path | None:
    """上次加载的报告模板源文件。"""
    current = _valid_xlsx_file_path(_settings().value(_KEY_REPORT_TEMPLATE_SOURCE, ""))
    if current is not None:
        return current
    return _valid_xlsx_file_path(_settings().value(_KEY_REPORT_TEMPLATE_LEGACY, ""))


def set_report_template_source_path(path: str | Path) -> None:
    p = Path(path)
    if p.suffix.lower() == ".xlsx" and p.is_file():
        _settings().setValue(_KEY_REPORT_TEMPLATE_SOURCE, str(p.resolve()))


def report_output_path() -> Path | None:
    """当前项目报告文件路径；可尚未创建，但父目录必须存在。"""
    return _valid_xlsx_output_path(_settings().value(_KEY_REPORT_OUTPUT, ""))


def set_report_output_path(path: str | Path) -> None:
    p = Path(path)
    if p.suffix.lower() != ".xlsx":
        p = p.with_suffix(".xlsx")
    if p.parent.is_dir():
        _settings().setValue(_KEY_REPORT_OUTPUT, str(p.resolve()))


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
