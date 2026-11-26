"""数值快照工具自身的逻辑校验（不依赖语料全量耗时）。

覆盖：序列化规则、叶子摊平、差异判定（含 NaN / 类型差异）、缺失与新增样例、
单样例异常落成载荷、以及 ``main`` 的参数校验退出码。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from scripts.snapshot_metrics import (
    _compare,
    _label_for,
    _leaves,
    _plain,
    _read_snapshot,
    _same_leaf,
    _snapshot_one,
    _write_snapshot,
    main,
)


@dataclass(frozen=True)
class _Inner:
    base_v: float
    top_v: float


@dataclass(frozen=True)
class _Outer:
    name: str
    inner: _Inner
    windows: tuple[int, int] | None = None


def test_plain_serializes_nested_dataclass_and_tuples():
    payload = _plain(_Outer("关断过程/Eoff", _Inner(1.5, 9.25), (3, 7)))
    assert payload == {
        "name": "关断过程/Eoff",
        "inner": {"base_v": 1.5, "top_v": 9.25},
        "windows": [3, 7],
    }


def test_plain_keeps_none_and_none_window():
    assert _plain(_Outer("x", _Inner(0.0, 1.0), None))["windows"] is None


def test_plain_normalizes_non_finite_to_strings():
    assert _plain(float("nan")) == "NaN"
    assert _plain(float("inf")) == "Infinity"
    assert _plain(float("-inf")) == "-Infinity"


def test_plain_unwraps_numpy_scalars():
    assert _plain(np.float64(2.5)) == 2.5
    assert _plain(np.int64(7)) == 7
    assert isinstance(_plain(np.float32(1.5)), float)


def test_plain_hashes_ndarray_instead_of_expanding_it():
    first = _plain(np.array([1.0, 2.0, 3.0]))
    second = _plain(np.array([1.0, 2.0, 3.0]))
    third = _plain(np.array([1.0, 2.0, 4.0]))
    assert first["__ndarray__"]["shape"] == [3]
    assert first["__ndarray__"]["dtype"] == "float64"
    assert first["__ndarray__"]["md5"] == second["__ndarray__"]["md5"]
    assert first["__ndarray__"]["md5"] != third["__ndarray__"]["md5"]


def test_plain_flattens_tuple_keys_into_readable_text():
    payload = _plain({("关断过程", "Eoff"): 1.0})
    assert payload == {"关断过程/Eoff": 1.0}


def test_plain_sorts_sets_so_hash_seed_cannot_change_the_snapshot():
    # 集合的迭代顺序随 PYTHONHASHSEED 变化；快照必须按固定顺序输出，
    # 否则同一份代码两次快照会出现纯顺序差异（假阳性）。
    payload = _plain({("开通", "Tr"), ("关断过程", "Eoff"), ("开通", "Ton")})
    assert payload == [["关断过程", "Eoff"], ["开通", "Ton"], ["开通", "Tr"]]


def test_leaves_flattens_nested_dicts_and_lists():
    out: dict[str, object] = {}
    _leaves({"a": {"b": [1, 2]}, "c": None}, "", out)
    assert out == {"a.b[0]": 1, "a.b[1]": 2, "c": None}


def test_same_leaf_treats_nan_as_equal_but_distinguishes_types():
    assert _same_leaf(float("nan"), float("nan"))
    assert _same_leaf(1.0, 1.0)
    assert not _same_leaf(1, 1.0)
    assert not _same_leaf(True, 1)


def _snapshot(*samples: tuple[str, dict]) -> dict:
    return {"schema": 1, "samples": dict(samples)}


def test_compare_reports_no_diff_for_identical_snapshots():
    baseline = _snapshot(("a.tss", {"eoff": 1.25, "segments": {"turn_off": [1, 2]}}))
    diffs, compared, text_only = _compare(baseline, baseline, max_report=10)
    assert diffs == []
    assert compared == 3
    assert text_only == 0


def test_compare_reports_changed_leaf_with_field_path():
    baseline = _snapshot(("a.tss", {"eoff": 1.25}))
    current = _snapshot(("a.tss", {"eoff": 1.2500001}))
    diffs, compared, _ = _compare(baseline, current, max_report=10)
    assert compared == 1
    assert len(diffs) == 1
    assert "a.tss" in diffs[0]
    assert "eoff" in diffs[0]


def test_compare_distinguishes_missing_and_new_samples():
    baseline = _snapshot(("old.tss", {"eoff": 1.0}))
    current = _snapshot(("new.tss", {"eoff": 1.0}))
    diffs, _, _ = _compare(baseline, current, max_report=10)
    joined = "\n".join(diffs)
    assert "old.tss" in joined and "缺失" in joined
    assert "new.tss" in joined and "新增" in joined


def test_compare_reports_sign_zero_as_text_only_not_failure():
    baseline = _snapshot(("a.tss", {"v": 0.0}))
    current = _snapshot(("a.tss", {"v": -0.0}))
    diffs, _, text_only = _compare(baseline, current, max_report=10)
    assert diffs == []
    assert text_only == 1


def test_compare_honours_max_report():
    baseline = _snapshot(("a.tss", {"v": 0.0, "w": 0.0, "x": 0.0}))
    current = _snapshot(("a.tss", {"v": 1.0, "w": 1.0, "x": 1.0}))
    diffs, _, _ = _compare(baseline, current, max_report=2)
    assert diffs[-1].startswith("... 已截断")


def test_snapshot_one_turns_failure_into_payload_instead_of_raising():
    label, payload = _snapshot_one(("bad.tss", "no/such/file.tss", False))
    assert label == "bad.tss"
    assert "__error__" in payload
    assert "__traceback__" in payload


def test_main_requires_out_or_compare(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["snapshot_metrics.py"])
    assert main() == 2
    assert "请至少给出" in capsys.readouterr().err


def test_parse_args_accepts_documented_flags(monkeypatch):
    from scripts.snapshot_metrics import _parse_args

    monkeypatch.setattr(
        "sys.argv",
        ["snapshot_metrics.py", "--limit", "1", "--out", "x.json"],
    )
    args = _parse_args()
    assert args.limit == 1
    assert args.out is not None
    assert args.root.name == "示例文件"


def test_snapshot_files_roundtrip_through_plain_and_gzip(tmp_path):
    snapshot = {"schema": 1, "meta": {"auto_slopes": False}, "samples": {"a.tss": {"v": 1.5}}}
    plain = tmp_path / "b.json"
    packed = tmp_path / "b.json.gz"
    _write_snapshot(plain, snapshot)
    _write_snapshot(packed, snapshot)
    assert _read_snapshot(plain) == snapshot
    assert _read_snapshot(packed) == snapshot


def test_gzip_baseline_bytes_are_reproducible(tmp_path):
    # gzip 头里默认写当前时间；不固定 mtime 的话同一份内容每次字节都不同，
    # 「基线没变」就无法用哈希核对。
    snapshot = {"schema": 1, "samples": {"a.tss": {"v": 1.5}}}
    packed = tmp_path / "b.json.gz"
    _write_snapshot(packed, snapshot)
    first = packed.read_bytes()
    _write_snapshot(packed, snapshot)
    assert packed.read_bytes() == first


def test_label_is_relative_to_corpus_root_not_repo_root(tmp_path):
    corpus = tmp_path / "示例文件"
    sample = corpus / "likangkang" / "uh" / "750v-uh-000.tss"
    assert _label_for(sample, corpus) == str(Path("likangkang") / "uh" / "750v-uh-000.tss")
    # 语料根之外的路径退化为相对仓库根（仍可读、不抛异常）；仓库外才是绝对路径
    outside = tmp_path / "elsewhere" / "x.tss"
    label = _label_for(outside, corpus)
    assert not Path(label).is_absolute()
    assert label.endswith(str(Path("elsewhere") / "x.tss"))
