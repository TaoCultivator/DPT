"""报告版面收尾：压缩组内空行、删除基础页与 0 图块、按前缀排序。

批量写入报告后调用本脚本收尾，避免报告里残留模板空行、无前缀基础页、
0 图空块与错乱的 sheet 顺序。**只改版面，不改任何数值**：载荷单元格的值与
样式按行整体搬运，图片字节不重编码，6 张基础页（封面等）原样保留。

CLI：

    python -m scripts.finalize_report_layout --xlsx <path> [--apply] [--backup-dir <dir>]

处理顺序（固定）：

1. 删除无前缀基础页：U/V/W 双脉冲数据+波形、短路测试、短路测试图片；
2. 压缩 <前缀>_<相>相_双脉冲数据：每组只保留有载荷的行，A/B/C 合并区重建；
3. 压缩 <前缀>_短路测试：删除 750V 占位行与无数据温度组，重建 A 列温度合并区；
4. 清理图片页 0 图块（双脉冲波形 53 行/块、短路测试图片 10 行/块），
   同步搬运图片锚点、合并区与行高；短路图片页重复错位的相标题只保留每相 1 行；
5. 按 基础页 -> U/V/W（10A2 数据、10A2 波形、10B2 数据、10B2 波形）-> 短路页 重排 sheet。

默认 dry-run 只输出计划 JSON，不动文件；--apply 才写盘（先自动备份到
--backup-dir），写盘后跑 16 项校验并打印 JSON 摘要。已收尾过的报告再次
运行会判定 no-op，不写盘。退出码：0=通过（含 no-op），1=校验失败或写盘失败。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

import openpyxl
from openpyxl.worksheet.cell_range import CellRange

DATA_SUFFIX = "_双脉冲数据"
WAVE_SUFFIX = "_双脉冲波形"
SHORT_SUFFIX = "_短路测试"
PIC_SUFFIX = "_短路测试图片"

HEADER_ROWS = 4
WAVE_BLOCK_ROWS = 53
PIC_BLOCK_ROWS = 10
PHASES = ("U相", "V相", "W相")
PREFIXES = ("10A2", "10B2")

#: 用户旧单模块版式的基础页，收尾时必须删除（只作克隆模板用）。
BASE_SHEETS = (
    "U相_双脉冲数据",
    "U相_双脉冲波形",
    "V相_双脉冲数据",
    "V相_双脉冲波形",
    "W相_双脉冲数据",
    "W相_双脉冲波形",
    "短路测试",
    "短路测试图片",
)

#: 收尾不动的六张基础页。
FIXED_SHEETS = (
    "封面",
    "阶段测试要求",
    "测试前数据记录",
    "PTC&NTC",
    "调试原则及注意事项",
    "参数调试记录",
)

SHORT_SHEETS = ("10A2_短路测试", "10A2_短路测试图片", "10B2_短路测试", "10B2_短路测试图片")

TEMP_LABEL = {
    "25": "25℃",
    "25℃": "25℃",
    "150": "150℃",
    "150℃": "150℃",
    "-40": "-40℃",
    "-40℃": "-40℃",
    "175": "175℃",
    "175℃": "175℃",
}


# --------------------------------------------------------------------------- 工具
def _norm(value):
    """把整数值浮点还原成 int，便于比较与输出。"""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _image_bytes(image) -> bytes:
    """取图片原始字节（不触发 PIL 重编码，也不会关闭文件指针）。"""
    ref = image.ref
    getvalue = getattr(ref, "getvalue", None)
    if callable(getvalue):
        return getvalue()
    return image._data()


def _set_cell(ws, row: int, col: int, value, style=None):
    """写入单元格；若该位置当前是只读的 MergedCell 则替换为普通 Cell。"""
    from openpyxl.cell.cell import Cell

    old = ws._cells.get((row, col))
    cell = Cell(ws, row=row, column=col, value=value)
    if style is not None:
        cell._style = copy.copy(style)
    elif old is not None:
        cell._style = copy.copy(old._style)
    ws._cells[(row, col)] = cell
    return cell


def _group_spans(ws, min_row: int = 1):
    """A 列纵向合并区（= 组标签）的行区间。"""
    spans = [
        (m.min_row, m.max_row)
        for m in ws.merged_cells.ranges
        if m.min_col == 1 and m.max_col == 1 and m.min_row >= min_row
    ]
    return sorted(spans)


def target_sheet_order(names) -> list[str]:
    """收尾后的目标 sheet 顺序；未识别的多余 sheet 追加在末尾，绝不丢页。"""
    names = list(names)
    order = [n for n in FIXED_SHEETS if n in names]
    for phase in PHASES:
        for prefix in PREFIXES:
            for suffix in (DATA_SUFFIX, WAVE_SUFFIX):
                order.append("%s_%s%s" % (prefix, phase, suffix))
    order += list(SHORT_SHEETS)
    order = [n for n in order if n in names]
    for name in names:
        if name not in order:
            order.append(name)
    return order


# --------------------------------------------------------------------------- 行压缩
class Compaction:
    """按 keep_rows 压缩行：单元格值/样式随行搬运，合并区、行高、图片锚点同步重映射。"""

    def __init__(self, ws):
        self.ws = ws
        self.merges = [(m.min_row, m.min_col, m.max_row, m.max_col) for m in ws.merged_cells.ranges]
        self.heights = {}
        for row, dim in ws.row_dimensions.items():
            self.heights[row] = {
                "ht": dim.ht,
                "hidden": dim.hidden,
                "outlineLevel": dim.outlineLevel,
                "collapsed": dim.collapsed,
                "thickTop": dim.thickTop,
                "thickBot": dim.thickBot,
                "style": copy.copy(dim._style),
            }
        self.images = [
            (
                image,
                image.anchor._from.row + 1,
                (image.anchor.to.row + 1) if getattr(image.anchor, "to", None) is not None else None,
            )
            for image in ws._images
        ]

    def apply(self, keep_rows, report):
        ws = self.ws
        keep = sorted(set(keep_rows))
        mapping = {row: index + 1 for index, row in enumerate(keep)}
        max_row = ws.max_row
        if keep == list(range(1, max_row + 1)):
            return {
                "old_rows": max_row,
                "new_rows": max_row,
                "deleted_rows": 0,
                "mapping": mapping,
                "noop": True,
            }
        dropped = []
        run = None
        for row in range(1, max_row + 1):
            if row in mapping:
                if run is not None:
                    dropped.append(tuple(run))
                    run = None
            elif run is None:
                run = [row, row]
            else:
                run[1] = row
        if run is not None:
            dropped.append(tuple(run))
        for start, end in reversed(dropped):
            ws.delete_rows(start, end - start + 1)
        new_ranges = set()
        for r1, c1, r2, c2 in self.merges:
            kept = [row for row in range(r1, r2 + 1) if row in mapping]
            if not kept:
                continue
            n1, n2 = mapping[min(kept)], mapping[max(kept)]
            if n2 - n1 + 1 != len(kept):
                report.fail("%s: 合并区 %d-%d 压缩后不连续" % (ws.title, r1, r2))
            new_ranges.add(CellRange(min_col=c1, max_col=c2, min_row=n1, max_row=n2))
        ws.merged_cells.ranges = new_ranges
        ws.row_dimensions.clear()
        for row in keep:
            dim = self.heights.get(row)
            if dim is None:
                continue
            target = ws.row_dimensions[mapping[row]]
            target.ht = dim["ht"]
            target.hidden = dim["hidden"]
            target.outlineLevel = dim["outlineLevel"]
            target.collapsed = dim["collapsed"]
            target.thickTop = dim["thickTop"]
            target.thickBot = dim["thickBot"]
            target._style = copy.copy(dim["style"])
        for image, from_row, to_row in self.images:
            if from_row not in mapping:
                report.fail("%s: 图片锚点落在被删除的第 %d 行" % (ws.title, from_row))
            image.anchor._from.row = mapping[from_row] - 1
            if to_row is not None:
                if to_row in mapping:
                    new_to = mapping[to_row]
                else:
                    lower = [row for row in keep if row <= to_row]
                    if not lower:
                        report.fail("%s: 图片下边界第 %d 行丢失" % (ws.title, to_row))
                    new_to = mapping[lower[-1]]
                image.anchor.to.row = new_to - 1
        return {
            "old_rows": max_row,
            "new_rows": len(keep),
            "deleted_rows": max_row - len(keep),
            "mapping": mapping,
            "noop": False,
        }


class PlanError(RuntimeError):
    """计划阶段发现会破坏数据的情形，直接中止。"""


class PlanReport:
    def __init__(self):
        self.steps = []

    def add(self, **kwargs):
        self.steps.append(kwargs)

    def fail(self, message):
        raise PlanError(message)

# --------------------------------------------------------------------------- 各页计划
def plan_data_sheet(ws, apply, report) -> dict:
    """双脉冲数据页：每组只保留带载荷的行，并把载荷搬到组首行。"""
    spans = _group_spans(ws, min_row=HEADER_ROWS + 1)
    keep = list(range(1, HEADER_ROWS + 1))
    writes = []
    groups = []
    for start, end in spans:
        payload = [
            row
            for row in range(start, end + 1)
            if _is_number(ws.cell(row=row, column=4).value) or _is_number(ws.cell(row=row, column=5).value)
        ]
        if not payload:
            report.fail("%s: 第 %d-%d 行组没有载荷" % (ws.title, start, end))
        for index, src in enumerate(payload):
            writes.append((src, start + index))
        for row in range(start, end + 1):
            if row in payload:
                continue
            if any(ws.cell(row=row, column=col).value is not None for col in range(4, 41)):
                report.fail("%s: 第 %d 行将被删除但仍带数据" % (ws.title, row))
        keep.extend(range(start, start + len(payload)))
        groups.append({"old": [start, end], "payload_rows": payload, "new": [start, start + len(payload) - 1]})
    changed = keep != list(range(1, ws.max_row + 1)) or any(src != dst for src, dst in writes)
    step = {
        "step": "compact_double_pulse_data",
        "sheet": ws.title,
        "kind": "data",
        "before_rows": ws.max_row,
        "after_rows": len(keep),
        "before_merges": len(list(ws.merged_cells.ranges)),
        "groups": groups,
        "changed": changed,
    }
    if apply and changed:
        for src, dst in writes:
            if src == dst:
                continue
            for col in range(4, 41):
                src_cell = ws.cell(row=src, column=col)
                dst_cell = ws.cell(row=dst, column=col)
                dst_cell.value = src_cell.value
                dst_cell._style = copy.copy(src_cell._style)
        result = Compaction(ws).apply(keep, report)
        result.pop("mapping", None)
        step.update(result)
        step["after_rows"] = ws.max_row
        step["after_merges"] = len(list(ws.merged_cells.ranges))
    elif apply:
        step["after_merges"] = len(list(ws.merged_cells.ranges))
    report.add(**step)
    return step


def plan_short_sheet(ws, apply, report) -> dict:
    """短路数据页：删除无载荷行（750V 占位行），无数据的温度组整块删除。"""
    spans = _group_spans(ws, min_row=HEADER_ROWS + 1)
    keep = list(range(1, HEADER_ROWS + 1))
    relabel = []
    groups = []
    label_dirty = False
    for start, end in spans:
        kept = [
            row
            for row in range(start, end + 1)
            if any(ws.cell(row=row, column=col).value is not None for col in range(6, 12))
        ]
        label = _norm(ws.cell(row=start, column=1).value)
        groups.append({"old": [start, end], "label": label, "kept": len(kept)})
        for row in range(start, end + 1):
            if row in kept:
                continue
            udc = _norm(ws.cell(row=row, column=4).value)
            short_type = ws.cell(row=row, column=3).value
            if udc not in (None, 750) or short_type not in (None, "SC1"):
                report.fail("%s: 第 %d 行将被删除但仍带数据（Udc=%r）" % (ws.title, row, udc))
        if not kept:
            continue
        keep.extend(kept)
        relabel.append((start, kept[0], label))
        if TEMP_LABEL.get(str(label), label) != label:
            label_dirty = True
    changed = keep != list(range(1, ws.max_row + 1)) or label_dirty
    step = {
        "step": "compact_short_circuit_data",
        "sheet": ws.title,
        "kind": "short",
        "before_rows": ws.max_row,
        "after_rows": len(keep),
        "before_merges": len(list(ws.merged_cells.ranges)),
        "groups": groups,
        "changed": changed,
    }
    if apply and changed:
        styles = {start: copy.copy(ws.cell(row=start, column=1)._style) for start, _, _ in relabel}
        result = Compaction(ws).apply(keep, report)
        mapping = result.pop("mapping")
        step.update(result)
        for start, first, label in relabel:
            _set_cell(ws, mapping[first], 1, TEMP_LABEL.get(str(label), label), styles.get(start))
        step["after_rows"] = ws.max_row
        step["after_merges"] = len(list(ws.merged_cells.ranges))
    elif apply:
        step["after_merges"] = len(list(ws.merged_cells.ranges))
    report.add(**step)
    return step


def plan_wave_sheet(ws, apply, report) -> dict:
    """双脉冲波形页：块 = 53 行，删除 0 图空块并上移后续块。"""
    chunks = sorted(
        m.min_row
        for m in ws.merged_cells.ranges
        if m.min_col == 1 and m.max_col == 8 and m.max_row - m.min_row == 16
    )
    if not chunks:
        report.fail("%s: 未找到波形块结构" % ws.title)
    base = chunks[0]
    starts = [row for row in chunks if (row - base) % WAVE_BLOCK_ROWS == 0]
    if len(starts) * 3 != len(chunks):
        report.fail("%s: 子块数 %d 与块数 %d 不匹配" % (ws.title, len(chunks), len(starts)))
    counts = Counter(image.anchor._from.row + 1 for image in ws._images)
    blocks = []
    for start in starts:
        end = start + WAVE_BLOCK_ROWS - 1
        blocks.append({"rows": [start, end], "imgs": sum(v for r, v in counts.items() if start <= r <= end)})
    dropped = []
    keep = []
    for block in blocks:
        start, end = block["rows"]
        end = min(end, ws.max_row)
        if block["imgs"] == 0:
            dropped.append([start, end])
        else:
            keep.extend(range(start, end + 1))
    for start, end in dropped:
        nxt = [b for b in blocks if b["rows"][0] > end and b["imgs"] > 0]
        if not nxt:
            continue
        reference = set()
        for row in range(nxt[0]["rows"][0], min(nxt[0]["rows"][1], ws.max_row) + 1):
            for col in range(1, ws.max_column + 1):
                value = ws.cell(row=row, column=col).value
                if value is not None:
                    reference.add(str(value))
        for row in range(start, end + 1):
            for col in range(1, ws.max_column + 1):
                value = ws.cell(row=row, column=col).value
                if value is not None and str(value) not in reference:
                    report.fail("%s: 待删空块第 %d 行含独有的值 %r" % (ws.title, row, value))
    changed = bool(dropped)
    step = {
        "step": "clean_picture_blocks",
        "sheet": ws.title,
        "kind": "wave",
        "before_rows": ws.max_row,
        "after_rows": len(keep),
        "images": len(ws._images),
        "blocks": blocks,
        "dropped_blocks": dropped,
        "changed": changed,
    }
    if apply and changed:
        result = Compaction(ws).apply(keep, report)
        result.pop("mapping", None)
        step.update(result)
        step["after_rows"] = ws.max_row
        step["after_images"] = len(ws._images)
        step["after_merges"] = len(list(ws.merged_cells.ranges))
    report.add(**step)
    return step


def _phase_of(label):
    text = str(label)
    if text[:2] in ("UH", "UL"):
        return "U相"
    if text[:2] in ("VH", "VL"):
        return "V相"
    if text[:2] in ("WH", "WL"):
        return "W相"
    return None


def plan_short_picture_sheet(ws, apply, report) -> dict:
    """短路测试图片页：块 = 10 行 4 图，删除 0 图块、块间空行与重复错位相标题。"""
    starts = sorted(m.min_row for m in ws.merged_cells.ranges if m.min_col == 1 and m.max_col == 5)
    sections = sorted(
        m.min_row
        for m in ws.merged_cells.ranges
        if m.min_col == 1 and m.max_col == ws.max_column and m.min_row == m.max_row
    )
    anchors = sorted(set(starts) | set(sections))
    counts = Counter(image.anchor._from.row + 1 for image in ws._images)
    blocks = []
    for start in starts:
        nxt = [a for a in anchors if a > start]
        hard_end = (min(nxt) - 1) if nxt else ws.max_row
        ends = [
            m.max_row
            for m in ws.merged_cells.ranges
            if start <= m.min_row <= start + 4 and m.max_row <= hard_end
        ]
        end = max(ends) if ends else hard_end
        blocks.append(
            {
                "rows": [start, end],
                "label": _norm(ws.cell(row=start, column=1).value),
                "imgs": sum(v for r, v in counts.items() if start <= r <= end),
            }
        )
    covered = set(sections)
    for block in blocks:
        covered.update(range(block["rows"][0], block["rows"][1] + 1))
    stray = []
    for row in range(1, ws.max_row + 1):
        if row in covered:
            continue
        if all(ws.cell(row=row, column=col).value is None for col in range(1, ws.max_column + 1)):
            stray.append(row)
        else:
            covered.add(row)
    seen = set()
    keep_sections = []
    duplicate_sections = []
    for row in sections:
        label = ws.cell(row=row, column=1).value
        nxt = [b for b in blocks if b["rows"][0] > row]
        phase = _phase_of(nxt[0]["label"]) if nxt else None
        if phase is not None and label == phase and phase not in seen:
            seen.add(phase)
            keep_sections.append(row)
        else:
            duplicate_sections.append([row, label, phase])
    keep = sorted(set(keep_sections) | (covered - set(sections)))
    dropped_blocks = [b for b in blocks if b["imgs"] == 0]
    for block in dropped_blocks:
        keep = [row for row in keep if not (block["rows"][0] <= row <= block["rows"][1])]
    changed = bool(dropped_blocks or duplicate_sections or stray) or keep != list(range(1, ws.max_row + 1))
    step = {
        "step": "clean_picture_blocks",
        "sheet": ws.title,
        "kind": "shortpic",
        "before_rows": ws.max_row,
        "after_rows": len(keep),
        "images": len(ws._images),
        "blocks": len(blocks),
        "blocks_with_images": sum(1 for b in blocks if b["imgs"] > 0),
        "dropped_blocks": [[b["rows"], b["label"], b["imgs"]] for b in dropped_blocks],
        "duplicate_sections": duplicate_sections,
        "stray_blank_rows": len(stray),
        "changed": changed,
    }
    if apply and changed:
        result = Compaction(ws).apply(keep, report)
        result.pop("mapping", None)
        step.update(result)
        step["after_rows"] = ws.max_row
        step["after_images"] = len(ws._images)
        step["after_merges"] = len(list(ws.merged_cells.ranges))
    report.add(**step)
    return step

# --------------------------------------------------------------------------- 快照与校验
def snapshot_workbook(wb) -> dict:
    """抓取版面/载荷/图片指纹，用于写盘前后对比。"""
    snap = {"order": list(wb.sheetnames), "sheets": {}, "image_hashes": Counter()}
    for ws in wb.worksheets:
        title = ws.title
        info = {
            "max_row": ws.max_row,
            "max_col": ws.max_column,
            "n_images": len(ws._images),
            "merges": sorted(str(m) for m in ws.merged_cells.ranges),
            "heights": {str(r): d.ht for r, d in ws.row_dimensions.items() if d.ht is not None},
            "image_hashes": [],
        }
        for image in ws._images:
            info["image_hashes"].append(hashlib.sha256(_image_bytes(image)).hexdigest())
        snap["image_hashes"] += Counter(info["image_hashes"])
        if title.endswith(DATA_SUFFIX):
            payload, labels = [], []
            for start, end in _group_spans(ws, min_row=HEADER_ROWS + 1):
                labels.append(
                    [
                        _norm(ws.cell(row=start, column=1).value),
                        _norm(ws.cell(row=start, column=2).value),
                        _norm(ws.cell(row=start, column=3).value),
                    ]
                )
                for row in range(start, end + 1):
                    if _is_number(ws.cell(row=row, column=4).value) or _is_number(ws.cell(row=row, column=5).value):
                        payload.append([_norm(ws.cell(row=row, column=c).value) for c in range(4, 41)])
            info["payload"] = payload
            info["group_labels"] = labels
        elif title.endswith(SHORT_SUFFIX):
            payload, temps = [], []
            for start, end in _group_spans(ws, min_row=HEADER_ROWS + 1):
                temps.append([start, end, _norm(ws.cell(row=start, column=1).value)])
                for row in range(start, end + 1):
                    if any(ws.cell(row=row, column=c).value is not None for c in range(6, 12)):
                        payload.append([_norm(ws.cell(row=row, column=c).value) for c in range(2, 13)])
            info["payload"] = payload
            info["temp_groups"] = temps
        snap["sheets"][title] = info
    return snap


def _zip_parts(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        return {
            "testzip": archive.testzip(),
            "entries": len(names),
            "external_links": sum(1 for n in names if n.startswith("xl/externalLinks/")),
        }


def verify_layout(before, after, after_wb, before_parts, after_parts, base_hashes) -> list:
    """16 项版面/数值校验（与现场修复使用的验收口径一致）。"""
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    order = after["order"]
    check(
        "C1a zip.testzip()==None",
        after_parts["testzip"] is None,
        "testzip=%r entries=%d" % (after_parts["testzip"], after_parts["entries"]),
    )
    check("C1b sheet order", order == target_sheet_order(order), " | ".join(order))
    expected_count = len(before["order"]) - sum(1 for n in BASE_SHEETS if n in before["order"])
    check("C1c sheet count", len(order) == expected_count, "count=%d expected=%d" % (len(order), expected_count))
    leftover = [n for n in BASE_SHEETS if n in order]
    check("C1d base sheets gone", not leftover, "leftover=%s" % leftover)
    check(
        "C1e external links preserved",
        before_parts["external_links"] == after_parts["external_links"],
        "before=%d after=%d" % (before_parts["external_links"], after_parts["external_links"]),
    )

    payload_bad = []
    for name in order:
        info = after["sheets"][name]
        if "payload" not in info:
            continue
        old = before["sheets"].get(name, {}).get("payload")
        if old is not None and old != info["payload"]:
            payload_bad.append("%s: %d vs %d 行不一致" % (name, len(old), len(info["payload"])))
    check("C2 payload identical (values & order)", not payload_bad, "; ".join(payload_bad) or "数据/短路页逐行逐值相等")

    label_bad = []
    for name in order:
        info = after["sheets"][name]
        if "group_labels" in info:
            old = before["sheets"].get(name, {}).get("group_labels")
            if old is not None and old != info["group_labels"]:
                label_bad.append(name + " 组标签")
        if "temp_groups" in info:
            old = before["sheets"].get(name, {}).get("temp_groups", [])
            expected = [TEMP_LABEL.get(str(g[2]), str(g[2])) for g in old]
            got = [TEMP_LABEL.get(str(g[2]), str(g[2])) for g in info["temp_groups"]]
            if got != [x for x in expected if x in set(got)]:
                label_bad.append("%s 温度标签 %s" % (name, got))
            for entry in info["temp_groups"]:
                if str(entry[2]) not in ("25℃", "-40℃", "150℃"):
                    label_bad.append("%s 温度标签未归一：%r" % (name, entry[2]))
    check("C3 group / temperature labels preserved & normalised", not label_bad, "; ".join(label_bad) or "ok")

    count_bad = []
    for name in order:
        old = before["sheets"].get(name)
        if old is not None and old["n_images"] != after["sheets"][name]["n_images"]:
            count_bad.append("%s %d->%d" % (name, old["n_images"], after["sheets"][name]["n_images"]))
    check("C4a per-sheet picture counts unchanged", not count_bad, "; ".join(count_bad) or "保留页图数不变")
    total_before = sum(info["n_images"] for info in before["sheets"].values())
    total_after = sum(info["n_images"] for info in after["sheets"].values())
    check(
        "C4b total pictures",
        total_after == total_before - sum(base_hashes.values()),
        "before=%d after=%d removed=%d" % (total_before, total_after, sum(base_hashes.values())),
    )
    check(
        "C4c media bytes identical (only deleted base-page pictures removed)",
        after["image_hashes"] == (before["image_hashes"] - base_hashes),
        "removed=%d 张" % sum(base_hashes.values()),
    )

    merge_bad, blank_bad, height_bad, block_bad = [], [], [], []
    for name in order:
        ws = after_wb[name]
        merges = [(m.min_row, m.min_col, m.max_row, m.max_col) for m in ws.merged_cells.ranges]
        for r1, c1, r2, c2 in merges:
            if r1 < 1 or r2 > ws.max_row or c1 < 1 or c2 > ws.max_column:
                merge_bad.append("%s 合并区越界 %s" % (name, (r1, c1, r2, c2)))
        if name.endswith(DATA_SUFFIX):
            header = {
                (1, 1, 2, 5),
                (1, 6, 2, 17),
                (1, 18, 1, 37),
                (2, 18, 2, 30),
                (2, 31, 2, 37),
                (3, 1, 4, 1),
                (3, 3, 4, 3),
            }
            got = set(merges)
            if got & header != header:
                merge_bad.append("%s 表头合并区被改写" % name)
            groups = sorted((r1, r2) for (r1, c1, r2, c2) in merges if c1 == 1 and c2 == 1 and r1 >= 5)
            if len(groups) != 6:
                merge_bad.append("%s 组数=%d" % (name, len(groups)))
            for r1, r2 in groups:
                if r2 - r1 + 1 != 2:
                    merge_bad.append("%s 组 %d-%d 不是 2 行" % (name, r1, r2))
                for col in (1, 2, 3):
                    if (r1, col, r2, col) not in got:
                        merge_bad.append("%s 缺 %s 列合并区" % (name, "ABC"[col - 1]))
                for row in range(r1, r2 + 1):
                    if any(ws.cell(row=row, column=c).value is None for c in (4, 5)):
                        blank_bad.append("%s 第 %d 行缺载荷" % (name, row))
            if groups and groups[-1][1] != ws.max_row:
                blank_bad.append("%s 末组之后仍有行" % name)
            if groups and groups[0][0] != 5:
                blank_bad.append("%s 首组不在第 5 行" % name)
            for a, b in zip(groups, groups[1:]):
                if b[0] != a[1] + 1:
                    blank_bad.append("%s 组间有空行 %d-%d" % (name, a[1], b[0]))
            for r1, r2 in groups:
                heights = tuple(ws.row_dimensions[row].ht for row in range(r1, r2 + 1))
                if len(set(heights)) != 1:
                    height_bad.append("%s 组 %d-%d 行高 %s" % (name, r1, r2, heights))
        elif name.endswith(SHORT_SUFFIX):
            got = set(merges)
            header = {(1, 1, 2, 12), (3, 1, 4, 1), (3, 2, 4, 2), (3, 3, 4, 3)}
            if got & header != header:
                merge_bad.append("%s 表头合并区被改写" % name)
            agroups = sorted((r1, r2) for (r1, c1, r2, c2) in merges if c1 == 1 and c2 == 1 and r1 >= 5)
            for r1, r2 in agroups:
                if ws.cell(row=r1, column=1).value not in ("25℃", "-40℃"):
                    merge_bad.append("%s 第 %d 行温度标签 %r" % (name, r1, ws.cell(row=r1, column=1).value))
                rows = r2 - r1 + 1
                if rows % 2 or rows < 6:
                    merge_bad.append("%s 温度合并区 %d-%d 共 %d 行" % (name, r1, r2, rows))
            for row in range(5, ws.max_row + 1):
                if not any(ws.cell(row=row, column=c).value is not None for c in range(6, 12)):
                    blank_bad.append("%s 第 %d 行无载荷" % (name, row))
            for a, b in zip(agroups, agroups[1:]):
                if b[0] != a[1] + 1:
                    blank_bad.append("%s 温度组间有空行 %d-%d" % (name, a[1], b[0]))
            if agroups and agroups[-1][1] != ws.max_row:
                blank_bad.append("%s 末温度组之后仍有行" % name)
        elif name.endswith(WAVE_SUFFIX):
            if len(merges) % 42:
                merge_bad.append("%s 合并区数 %d 非块数×42" % (name, len(merges)))
            counts = Counter(image.anchor._from.row + 1 for image in ws._images)
            starts = sorted(
                m.min_row
                for m in ws.merged_cells.ranges
                if m.min_col == 1 and m.max_col == 8 and m.max_row - m.min_row == 16
            )
            blocks = [row for row in starts if (row - 1) % WAVE_BLOCK_ROWS == 0]
            if not blocks:
                block_bad.append("%s 未识别到波形块" % name)
            for index, start in enumerate(blocks):
                end = min(start + WAVE_BLOCK_ROWS - 1, ws.max_row)
                if sum(v for r, v in counts.items() if start <= r <= end) != 19:
                    block_bad.append("%s 第 %d 块图数异常" % (name, index))
                if index and start != blocks[index - 1] + WAVE_BLOCK_ROWS:
                    block_bad.append("%s 第 %d 块步距异常" % (name, index))
            expected_start = 1
            for index, start in enumerate(blocks):
                if start != expected_start:
                    blank_bad.append("%s 第 %d 块前有空行" % (name, index))
                expected_start = start + WAVE_BLOCK_ROWS
            if blocks and ws.max_row > blocks[-1] + WAVE_BLOCK_ROWS - 1:
                blank_bad.append("%s 末块之后仍有行" % name)
            patterns = {
                tuple(
                    ws.row_dimensions[row].ht
                    for row in range(start, min(start + WAVE_BLOCK_ROWS - 2, ws.max_row + 1))
                )
                for start in blocks
            }
            if len(patterns) > 1:
                height_bad.append("%s 块行高模式 %d 种" % (name, len(patterns)))
        elif name.endswith(PIC_SUFFIX):
            starts = sorted(m.min_row for m in ws.merged_cells.ranges if m.min_col == 1 and m.max_col == 5)
            counts = Counter(image.anchor._from.row + 1 for image in ws._images)
            labels = [ws.cell(row=start, column=1).value for start in starts]
            for start in starts:
                end = start + PIC_BLOCK_ROWS - 1
                if sum(v for r, v in counts.items() if start <= r <= end) != 4:
                    block_bad.append("%s 块 %d 图数异常" % (name, start))
                if not str(ws.cell(row=start, column=1).value or "").endswith("℃"):
                    block_bad.append("%s 块 %d 标签 %r" % (name, start, ws.cell(row=start, column=1).value))
            if any("175" in str(label) for label in labels):
                block_bad.append("%s 仍有 175℃ 空块" % name)
            banners = sorted(
                m.min_row
                for m in ws.merged_cells.ranges
                if m.min_col == 1 and m.max_col == ws.max_column and m.min_row == m.max_row
            )
            if len(banners) != 3:
                block_bad.append("%s 相标题 %d 行（应为 3）" % (name, len(banners)))
            for row in banners:
                banner = str(ws.cell(row=row, column=1).value)
                first = min([start for start in starts if start > row], default=None)
                if first != row + 1:
                    block_bad.append("%s 相标题 %s 未紧贴块" % (name, banner))
                    continue
                label = str(ws.cell(row=first, column=1).value)
                if label[:1] + "相" != banner:
                    block_bad.append("%s 相标题 %s 压在 %s 上" % (name, banner, label))
            if len(starts) * PIC_BLOCK_ROWS + 3 != ws.max_row:
                block_bad.append("%s 行数 %d 与块数 %d 不符" % (name, ws.max_row, len(starts)))
            patterns = {
                tuple(ws.row_dimensions[row].ht for row in range(start, start + PIC_BLOCK_ROWS))
                for start in starts
            }
            if len(patterns) > 1:
                height_bad.append("%s 块行高模式 %d 种" % (name, len(patterns)))
            inside = set(banners)
            for start in starts:
                inside.update(range(start, start + PIC_BLOCK_ROWS))
            outside = [row for row in range(1, ws.max_row + 1) if row not in inside]
            if outside:
                blank_bad.append("%s 块外残留行 %d 行" % (name, len(outside)))

    check("C5 merge layout", not merge_bad, "; ".join(merge_bad[:10]) or "数据/短路/图片页合并区一致")
    check("C6 no blank rows / gaps", not blank_bad, "; ".join(blank_bad[:10]) or "无空行")
    check("C7 row heights copied with their rows", not height_bad, "; ".join(height_bad[:10]) or "块/组行高一致")
    check("C8 picture block structure", not block_bad, "; ".join(block_bad[:10]) or "波形 19 图/块、短路 4 图/块")
    missing_heights = []
    for name in order:
        if name in FIXED_SHEETS:
            continue  # 六张基础页不参与版面收尾，行高保持原样
        ws = after_wb[name]
        if name.endswith(WAVE_SUFFIX):
            rows = []
            for start in range(1, ws.max_row + 1, WAVE_BLOCK_ROWS):
                rows.extend(range(start, min(start + WAVE_BLOCK_ROWS - 2, ws.max_row + 1)))
        else:
            rows = range(1, ws.max_row + 1)
        for row in rows:
            dim = ws.row_dimensions.get(row)
            if dim is None or dim.ht is None:
                missing_heights.append("%s 第 %d 行" % (name, row))
                break
    check("C9 row heights present on block / group rows", not missing_heights, "; ".join(missing_heights[:6]) or "ok")
    anchor_bad = []
    for name in order:
        ws = after_wb[name]
        if name.endswith(WAVE_SUFFIX):
            bounds = [(s, s + WAVE_BLOCK_ROWS - 1) for s in range(1, ws.max_row + 1, WAVE_BLOCK_ROWS)]
        elif name.endswith(PIC_SUFFIX):
            bounds = [
                (m.min_row, m.min_row + PIC_BLOCK_ROWS - 1)
                for m in ws.merged_cells.ranges
                if m.min_col == 1 and m.max_col == 5
            ]
        else:
            continue

        def block_of(row, bounds=bounds):
            for index, (start, end) in enumerate(bounds):
                if start <= row <= end:
                    return index
            return None

        for image in ws._images:
            start_row = image.anchor._from.row + 1
            to = getattr(image.anchor, "to", None)
            to_row = (to.row + 1) if to is not None else None
            if to_row is None or to_row < start_row:
                anchor_bad.append("%s 图锚点异常 %d-%s" % (name, start_row, to_row))
                continue
            b1, b2 = block_of(start_row), block_of(to_row)
            if b1 is None or b2 is None:
                anchor_bad.append("%s 图越块 %d-%d" % (name, start_row, to_row))
            elif b1 != b2:
                anchor_bad.append("%s 图跨块 %d-%d" % (name, start_row, to_row))
    check("C10 picture anchors inside a single block", not anchor_bad, "; ".join(anchor_bad[:10]) or "ok")
    return checks


# --------------------------------------------------------------------------- 主流程
def _backup(path: Path, backup_dir) -> Path:
    if backup_dir is None:
        folder = path.parent / ".tmp" / "report_layout_backup"
    else:
        folder = Path(backup_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = folder / ("%s.pre_finalize_%s%s" % (path.stem, stamp, path.suffix))
    shutil.copy2(path, target)
    return target


def finalize_report_layout(xlsx, *, apply: bool = False, backup_dir=None, verify: bool = True) -> dict:
    """收尾入口：dry-run 返回计划，apply 返回写盘 + 校验结果。"""
    path = Path(xlsx)
    if not path.is_file():
        raise FileNotFoundError("报告不存在：%s" % path)
    started = time.time()
    wb = openpyxl.load_workbook(path, data_only=False)
    before = snapshot_workbook(wb)
    before_parts = _zip_parts(path)
    base_hashes = Counter()
    for name in BASE_SHEETS:
        if name in before["sheets"]:
            base_hashes += Counter(before["sheets"][name]["image_hashes"])

    report = PlanReport()
    steps = []

    # 1. 基础页
    removed = [name for name in BASE_SHEETS if name in wb.sheetnames]
    if apply:
        for name in removed:
            del wb[name]
    steps.append({"step": "1_delete_base_sheets", "sheets": removed, "changed": bool(removed)})

    # 2-4. 逐页压缩（固定顺序：双脉冲数据 -> 短路数据 -> 双脉冲波形 -> 短路图片）
    planners = (
        (DATA_SUFFIX, plan_data_sheet),
        (SHORT_SUFFIX, plan_short_sheet),
        (WAVE_SUFFIX, plan_wave_sheet),
        (PIC_SUFFIX, plan_short_picture_sheet),
    )
    for suffix, planner in planners:
        for ws in list(wb.worksheets):
            if not ws.title.endswith(suffix):
                continue
            if ws.title in BASE_SHEETS:
                continue
            planner(ws, apply, report)

    # 5. sheet 排序
    order_before = list(wb.sheetnames)
    order_after = target_sheet_order(order_before)
    reorder = order_before != order_after
    if apply and reorder:
        wb._sheets = [wb[name] for name in order_after]
        wb.active = 0
    steps.extend(report.steps)
    order_step = {"step": "5_reorder_sheets", "changed": reorder, "sheets": len(order_after)}
    if reorder:
        order_step["before"] = order_before
        order_step["after"] = order_after
    steps.append(order_step)
    dropped_pictures = sum(base_hashes.values())

    summary = {
        "xlsx": str(path),
        "dry_run": not apply,
        "no_op": not any(step["changed"] for step in steps),
        "elapsed_s": round(time.time() - started, 1),
        "steps": steps,
        "sheets": len(order_after) if apply else len(target_sheet_order(order_before)),
        "pictures_before": sum(info["n_images"] for info in before["sheets"].values()),
        "pictures_after": sum(info["n_images"] for info in before["sheets"].values()) - dropped_pictures,
    }
    if not apply or summary["no_op"]:
        summary["ok"] = True
        return summary

    backup = _backup(path, backup_dir)
    summary["backup"] = str(backup)
    tmp_path = path.with_name(path.name + ".finalize.tmp")
    try:
        wb.save(tmp_path)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    after_wb = openpyxl.load_workbook(path, data_only=False)
    after = snapshot_workbook(after_wb)
    after_parts = _zip_parts(path)
    checks = verify_layout(before, after, after_wb, before_parts, after_parts, base_hashes) if verify else []
    summary["checks"] = checks
    summary["ok"] = all(check["ok"] for check in checks)
    summary["pictures_after"] = sum(info["n_images"] for info in after["sheets"].values())
    summary["sheet_order"] = after["order"]
    return summary


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(
        description="报告版面收尾：压缩空行、删基础页与 0 图块、排 sheet 顺序（只改版面不改数值）"
    )
    parser.add_argument("--xlsx", required=True, help="报告 xlsx 路径")
    parser.add_argument("--apply", action="store_true", help="写盘（默认只输出计划）")
    parser.add_argument("--backup-dir", default=None, help="备份目录，默认 <xlsx 所在目录>/.tmp/report_layout_backup")
    parser.add_argument("--no-verify", action="store_true", help="写盘后跳过校验（不建议）")
    args = parser.parse_args(argv)
    try:
        result = finalize_report_layout(
            args.xlsx,
            apply=args.apply,
            backup_dir=args.backup_dir,
            verify=not args.no_verify,
        )
    except (PlanError, FileNotFoundError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    except PermissionError as exc:
        print(json.dumps({"ok": False, "error": "文件被占用（请先关闭 Excel）：%s" % exc}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if result["dry_run"]:
        return 0
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
