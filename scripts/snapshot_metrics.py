"""TSS 全量数值快照与差分校验。

用途：把「本次改动没有改变任何参数数值」从一句声明变成一条可执行断言。

- ``--out <基线.json>``：对语料中每个 ``.tss`` 跑一次权威提取路径，把
  ``ExtractResult``（含 A/B/Ha/Hb 所在的四张上下文表）导出为可 diff 的 JSON。
- ``--compare <基线.json>``：重新算一遍并与基线逐字段比对，任何差异都以
  ``样例路径 + 字段路径 + 旧值 -> 新值`` 输出，并以退出码 1 结束。

本脚本**只读**：不修改任何计算逻辑、不写报告、不碰 GUI、不新增提示。
它调用与 ``scripts/validate_tss_samples.py`` 完全相同的提取链，因此快照的
口径就是批量验证的口径（通道映射推断亦相同）。

用法（在仓库根目录）::

    .\\.venv\\Scripts\\python.exe scripts\\snapshot_metrics.py --out .tmp\\baseline.json
    .\\.venv\\Scripts\\python.exe scripts\\snapshot_metrics.py --compare .tmp\\baseline.json

快速冒烟（只跑前 2 个样例）::

    .\\.venv\\Scripts\\python.exe scripts\\snapshot_metrics.py --limit 2 --out .tmp\\smoke.json
"""
from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dpt_extractor.config.loader import load_config
from dpt_extractor.io.waveform_loader import load_waveform
from dpt_extractor.models.bridge_profile import (
    as_short_circuit_profile,
    guess_profile_from_path,
)
from dpt_extractor.models.channel_mapping import (
    apply_mapping,
    infer_best_mapping_from_bundle,
    infer_short_circuit_mapping_from_bundle,
)
from dpt_extractor.models.slope_range import auto_max_slope_range, SLOPE_ROW_KEYS
from dpt_extractor.models.test_mode import TestMode
from dpt_extractor.pipeline.run_extract import run_extraction
from dpt_extractor.utils.sample_corpus import discover_sample_waveforms
from dpt_extractor.utils.text_encoding import configure_utf8_text_io
from scripts.validate_tss_samples import _is_short_circuit_sample

SCHEMA_VERSION = 1
_CONTEXT_KEYS = (
    ("didt", "didt_contexts"),
    ("dvdt", "dvdt_contexts"),
    ("energy", "energy_contexts"),
    ("power", "power_contexts"),
)


# --------------------------------------------------------------------------
# 序列化：把任意上下文对象压成 JSON 原生值，规则固定且确定性
# --------------------------------------------------------------------------
def _key_text(key: object) -> str:
    if isinstance(key, tuple):
        return "/".join(str(part) for part in key)
    return str(key)


def _plain(value: Any) -> Any:
    """把 dataclass / numpy / tuple / dict 递归转成 JSON 原生值。

    浮点数保持 Python 的最短往返表示（``json`` 默认即 ``repr``），因此
    两个快照文件里同一个 float 的文本相同 == 位级相同。NaN/Inf 转成字符串，
    保证产出是合法 JSON。
    """
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, np.ndarray):
        flat = np.ascontiguousarray(value)
        return {
            "__ndarray__": {
                "dtype": str(flat.dtype),
                "shape": list(flat.shape),
                "md5": _ndarray_md5(flat),
            }
        }
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        # set 的迭代顺序随 PYTHONHASHSEED 变化（多进程各不相同），必须固定，
        # 否则同一份代码两次快照会出现纯顺序差异，闸门全是假阳性。
        return sorted((_plain(item) for item in value), key=repr)
    if isinstance(value, dict):
        return {_key_text(k): _plain(v) for k, v in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    try:
        return _plain(vars(value))
    except TypeError:
        return repr(value)


def _ndarray_md5(array: np.ndarray) -> str:
    import hashlib

    return hashlib.md5(array.tobytes()).hexdigest()


# --------------------------------------------------------------------------
# 单样例快照
# --------------------------------------------------------------------------
def _snapshot_sample(path: Path, *, auto_slopes: bool) -> dict[str, Any]:
    """按批量验证器相同的路径提取一个样例。"""
    cfg = load_config()
    if auto_slopes:
        cfg.slope_ranges = {
            row_key: auto_max_slope_range(row_key) for row_key in SLOPE_ROW_KEYS.values()
        }

    base_profile = guess_profile_from_path(path)
    bundle = load_waveform(path)

    if _is_short_circuit_sample(path):
        cfg.test_mode.mode = TestMode.SHORT_CIRCUIT.value
        inferred = infer_short_circuit_mapping_from_bundle(bundle, base_profile.bridge)
        if inferred is not None:
            profile = apply_mapping(as_short_circuit_profile(base_profile), inferred)
            mapping_source = "inferred"
        else:
            profile = as_short_circuit_profile(base_profile)
            mapping_source = "default"
        mode = "short"
    else:
        inferred, source = infer_best_mapping_from_bundle(bundle, base_profile.bridge)
        if inferred is not None:
            profile = apply_mapping(base_profile, inferred)
            mapping_source = source or "inferred"
        else:
            profile = base_profile
            mapping_source = "default"
        mode = "dpt"

    result = run_extraction(bundle, profile, cfg)

    payload: dict[str, Any] = {
        "mode": mode,
        "mapping_source": mapping_source,
        "profile": _plain(profile),
        "result": _plain(result),
    }
    contexts = payload["result"]
    for label, attr in _CONTEXT_KEYS:
        contexts.pop(attr, None)
        payload[label] = _plain(getattr(result, attr))
    # 集合统一挪到顶层、以排序后的可读文本呈现（见 _plain 对 set 的说明）。
    contexts.pop("unavailable_metrics", None)
    payload["unavailable_metrics"] = sorted(
        "{}|{}".format(section, name)
        for section, name in result.unavailable_metrics
    )
    return payload


# --------------------------------------------------------------------------
# 结构比对：先摊平成 叶子路径 -> 标量，再逐键比较
# --------------------------------------------------------------------------
def _leaves(value: Any, prefix: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _leaves(child, f"{prefix}.{key}" if prefix else str(key), out)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _leaves(child, f"{prefix}[{index}]", out)
    else:
        out[prefix] = value


def _same_leaf(left: Any, right: Any) -> bool:
    if isinstance(left, float) and isinstance(right, float):
        if math.isnan(left) and math.isnan(right):
            return True
        return left == right
    return type(left) is type(right) and left == right


def _compare(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    max_report: int,
) -> tuple[list[str], int, int]:
    """返回 (差异描述列表, 比较字段数, 文本不同但值相同的字段数)。"""
    base_samples = baseline.get("samples", {})
    cur_samples = current.get("samples", {})
    diffs: list[str] = []
    compared = 0
    text_only = 0

    for path in sorted(set(base_samples) | set(cur_samples)):
        if path not in cur_samples:
            diffs.append(f"缺失   {path}\n         基线有、本次没有")
            continue
        if path not in base_samples:
            diffs.append(f"新增   {path}\n         基线没有、本次多出")
            continue
        old_leaves: dict[str, Any] = {}
        new_leaves: dict[str, Any] = {}
        _leaves(base_samples[path], "", old_leaves)
        _leaves(cur_samples[path], "", new_leaves)
        for leaf in sorted(set(old_leaves) | set(new_leaves)):
            compared += 1
            old = old_leaves.get(leaf, "<缺失>")
            new = new_leaves.get(leaf, "<缺失>")
            if leaf in old_leaves and leaf in new_leaves and _same_leaf(old, new):
                if repr(old) != repr(new):
                    text_only += 1
                continue
            diffs.append(f"差异   {path}\n         {leaf}: {old!r} -> {new!r}")
            if len(diffs) >= max_report:
                diffs.append(f"... 已截断（--max-report {max_report}）")
                return diffs, compared, text_only
    return diffs, compared, text_only


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="导出 / 比对 TSS 全量数值快照（只读校验工具）",
    )
    parser.add_argument("--out", type=Path, default=None, help="写出快照 JSON")
    parser.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="与该基线 JSON 逐字段比对；有差异时退出码为 1",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT / "示例文件",
        help="TSS 语料根目录（默认 示例文件/，与 REGRESSION_BASELINES.md 的全量验证口径一致）",
    )
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 个样例")
    parser.add_argument("--offset", type=int, default=0, help="从排序后第 N 个样例开始")
    parser.add_argument("--match", default="", help="只跑路径含该文本的样例")
    parser.add_argument(
        "--auto-slopes",
        action="store_true",
        help="六项 dv/dt、di/dt 全部切到自动最大斜率后再取快照",
    )
    parser.add_argument("--max-report", type=int, default=200, help="最多打印多少条差异")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="并行进程数；0 表示按 CPU 核数自动（单进程约 4s/样例）",
    )
    parser.add_argument("--quiet", action="store_true", help="不打印逐样例进度")
    return parser.parse_args()


def _select_samples(args: argparse.Namespace) -> list[Path]:
    samples = discover_sample_waveforms(args.root)
    if args.match:
        needle = args.match.lower()
        samples = [p for p in samples if needle in str(p).lower()]
    if args.offset:
        samples = samples[args.offset :]
    if args.limit is not None:
        samples = samples[: args.limit]
    return samples


def _label_for(path: Path, root: Path) -> str:
    """样例标签相对于**语料根**，不相对于仓库根。

    这样语料放在仓库外、或换一个 worktree 跑同一个语料时，基线键完全一致，
    比对才不会因为前缀不同而全线假阳性。
    """
    for base in (root, ROOT):
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def _snapshot_one(task: tuple[str, str, bool]) -> tuple[str, dict[str, Any]]:
    """进程池工作单元：返回 (标签, 载荷)。异常也变成载荷，便于 diff。"""
    label, path_text, auto_slopes = task
    try:
        return label, _snapshot_sample(Path(path_text), auto_slopes=auto_slopes)
    except Exception as exc:
        return label, {
            "__error__": f"{type(exc).__name__}: {exc}",
            "__traceback__": traceback.format_exc().splitlines()[-6:],
        }


def _build_snapshot(
    samples: list[Path],
    *,
    root: Path,
    auto_slopes: bool,
    quiet: bool,
    workers: int,
) -> tuple[dict[str, Any], list[str], float]:
    tasks: list[tuple[str, str, bool]] = [
        (_label_for(path, root), str(path), auto_slopes) for path in samples
    ]

    payload_samples: dict[str, Any] = {}
    errors: list[str] = []
    started = time.perf_counter()

    def _record(index: int, label: str, payload: dict[str, Any], secs: float) -> None:
        payload_samples[label] = payload
        if "__error__" in payload:
            errors.append(f"{label}: {payload['__error__']}")
        if not quiet:
            print(
                f"[{index}/{len(tasks)}] {secs:6.2f}s  {label}",
                file=sys.stderr,
                flush=True,
            )

    if workers > 1 and len(tasks) > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as pool:
            for index, (label, payload) in enumerate(
                pool.map(_snapshot_one, tasks), start=1
            ):
                _record(index, label, payload, (time.perf_counter() - started) / index)
    else:
        for index, (label, path_text, auto) in enumerate(tasks, start=1):
            sample_started = time.perf_counter()
            _, payload = _snapshot_one((label, path_text, auto))
            _record(index, label, payload, time.perf_counter() - sample_started)

    total = time.perf_counter() - started
    snapshot = {
        "schema": SCHEMA_VERSION,
        "meta": {"auto_slopes": bool(auto_slopes)},
        "samples": payload_samples,
    }
    return snapshot, errors, total


def _write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    """写基线；``.gz`` 后缀用固定 mtime 压缩，保证同一内容字节相同。"""
    import gzip

    text = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".gz":
        path.write_bytes(gzip.compress(text.encode("utf-8"), 9, mtime=0))
    else:
        path.write_text(text, encoding="utf-8", newline="\n")


def _read_snapshot(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if path.suffix.lower() == ".gz":
        import gzip

        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def main() -> int:
    configure_utf8_text_io()
    args = _parse_args()
    if args.out is None and args.compare is None:
        print("请至少给出 --out 或 --compare", file=sys.stderr)
        return 2

    samples = _select_samples(args)
    if not samples:
        print("没有匹配到任何 .tss 样例", file=sys.stderr)
        return 2
    print(f"样例数={len(samples)} auto_slopes={args.auto_slopes}", file=sys.stderr)

    workers = args.workers
    if workers <= 0:
        workers = max(1, (os.cpu_count() or 4) - 1)
    print(f"并行进程数={workers}", file=sys.stderr)

    snapshot, errors, elapsed = _build_snapshot(
        samples,
        root=args.root,
        auto_slopes=args.auto_slopes,
        quiet=args.quiet,
        workers=workers,
    )
    print(
        f"提取完成：{len(snapshot['samples'])} 个样例，耗时 {elapsed:.1f}s"
        f"（平均 {elapsed / max(1, len(samples)):.2f}s/样例）",
        file=sys.stderr,
    )
    if errors:
        print(f"提取异常 {len(errors)} 个：", file=sys.stderr)
        for line in errors[:20]:
            print(f"  {line}", file=sys.stderr)

    if args.out is not None:
        _write_snapshot(args.out, snapshot)
        print(f"已写出基线：{args.out}", file=sys.stderr)

    exit_code = 1 if errors else 0

    if args.compare is not None:
        if not args.compare.exists():
            print(f"基线文件不存在：{args.compare}", file=sys.stderr)
            return 2
        baseline = _read_snapshot(args.compare)
        if baseline.get("schema") != SCHEMA_VERSION:
            print(
                f"基线 schema={baseline.get('schema')} 与本脚本 {SCHEMA_VERSION} 不一致",
                file=sys.stderr,
            )
            return 2
        diffs, compared, text_only = _compare(
            baseline,
            snapshot,
            max_report=args.max_report,
        )
        print("", file=sys.stderr)
        if diffs:
            print("=" * 72)
            print(f"发现 {len(diffs)} 处差异（比较字段 {compared} 个）")
            print("=" * 72)
            for line in diffs:
                print(line)
            exit_code = 1
        else:
            print(
                f"数值一致：样例 {len(snapshot['samples'])} 个、"
                f"字段 {compared} 个、差异 0、位差异 0"
            )
            if text_only:
                print(f"（另有 {text_only} 个字段文本写法不同但数值相等，如 -0.0/0.0）")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
