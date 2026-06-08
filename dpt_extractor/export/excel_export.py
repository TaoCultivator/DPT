from __future__ import annotations

from pathlib import Path

from dpt_extractor.export.mcu2506_layout import export_mcu2506
from dpt_extractor.models.results import ExtractResult


def export_to_excel(result: ExtractResult, path: str | Path) -> None:
    """按 MCU2506 列序生成 Excel，写入本次测试数据。"""
    export_mcu2506(result, path)


def default_export_path(result: ExtractResult) -> Path:
    """默认导出路径：与导入 TSS 同名，扩展名 .xlsx。"""
    if result.source_path:
        return Path(result.source_path).with_suffix(".xlsx")
    code = result.profile_code or "DPT"
    return Path.cwd() / f"{code}.xlsx"
