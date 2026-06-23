from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from dpt_extractor.export.mcu2506_layout import export_mcu2506
from dpt_extractor.export.short_circuit_layout import export_short_circuit
from dpt_extractor.models.results import ExtractResult


def _as_results(result: ExtractResult | Sequence[ExtractResult]) -> list[ExtractResult]:
    if isinstance(result, ExtractResult):
        return [result]
    rows = list(result)
    if not rows:
        raise ValueError("没有可导出的结果")
    return rows


def export_to_excel(result: ExtractResult | Sequence[ExtractResult], path: str | Path) -> None:
    """按当前测试类型生成 Excel，写入本次测试数据。"""
    rows = _as_results(result)
    if rows[0].short_circuit_mode:
        if len(rows) != 1:
            raise ValueError("短路测试导出不支持多行结果")
        export_short_circuit(rows[0], path)
        return
    export_mcu2506(rows, path)


def default_export_path(result: ExtractResult) -> Path:
    """默认导出路径：与导入 TSS 同名，扩展名 .xlsx。"""
    if result.source_path:
        return Path(result.source_path).with_suffix(".xlsx")
    code = result.profile_code or "DPT"
    return Path.cwd() / f"{code}.xlsx"
