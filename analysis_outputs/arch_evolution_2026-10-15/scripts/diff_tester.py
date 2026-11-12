"""数值一致性差分验收器（differential tester）。

用途
----
任何「用 Rust / 新算法重写参数提取」的方案，都必须先通过本工具的逐参数比对，
才允许进入下一步。它把「逐参数一致」从口号变成可执行的判据：

1. **生成基准（golden）**：在当前 Python 生产实现上跑语料，把**测量面上的每一个值**
   落成 JSON 快照。包含：
   - 分段索引（``segments``）与脉冲计数（``detected_pulse_count`` 等）
   - 四组结果数据类的全部数值字段（turn_off / turn_on / reverse_recovery / short_circuit）
   - ``unavailable_metrics``（缺失通道导致的隐藏参数集合）
2. **比对候选**：候选实现（Rust 内核、独立进程、任何新版本）产出同结构 JSON，
   本工具按**分级容差**判定并输出结构化差异报告。

分级容差（红线）
----------------
- **T0 位级一致**：整数与字符串（分段索引、脉冲序号、范围标签、profile 名）。
  必须 ``==``，不设容差。索引错一位就意味着窗口错了。
- **T1 位级一致**：浮点值默认按 ``repr()`` 生成的十进制往返表示逐字符比较，
  等价于 ``float == float`` 的按位相等。这是**默认要求**。
- **T2 显式容差**：仅当调用方显式指定 ``--rel-tol`` 时才放宽为相对误差判定。
  **默认不放宽**——因为按位一致是完全可以做到的（同一算法同一顺序），
  一旦放宽就等于接受了算法漂移，必须由人显式签字。

容差来源说明
------------
``docs/REGRESSION_BASELINES.md``（仓库内为 gitignore 的本地文档）记录的是
**样例级目标值与审计通过数**，没有为「重写 vs 现行」定义浮点容差。
因此本工具把「位级一致」定为默认，并把放宽动作留给显式开关。

用法::

    # 1) 生成基准快照（用现行 Python 实现）
    python scripts/diff_tester.py capture --out raw/golden_corpus.json

    # 2) 与候选实现比对
    python scripts/diff_tester.py compare \\
        --golden raw/golden_corpus.json --candidate raw/candidate_corpus.json
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from _harness import (  # noqa: E402
    DEFAULT_CORPUS,
    corpus_files,
    ensure_repo_on_path,
    is_short_circuit_sample,
    write_json,
)

ensure_repo_on_path()

from dpt_extractor.utils.app_paths import configure_numba_cache_dir  # noqa: E402

configure_numba_cache_dir()

#: 参与比对的「测量面」字段。顺序固定，便于人读差异。
_RESULT_GROUPS = ("turn_off", "turn_on", "reverse_recovery", "short_circuit")
_SCALAR_FIELDS = (
    "vdc",
    "idc",
    "vdc_set",
    "idc_set",
    "profile_name",
    "profile_code",
    "phase",
    "detected_pulse_count",
    "off_pulse_index",
    "on_pulse_index",
    "single_pulse_mode",
    "short_circuit_mode",
)


def _freeze(value: Any) -> Any:
    """把任意结果对象转成可 JSON 化、可逐值比较的结构。

    - dataclass → dict（递归）
    - set/tuple → 排序后的 list（保证顺序稳定）
    - float → 保留原值（JSON 往返由 repr 保证精度）
    """
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _freeze(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _freeze(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_freeze(v) for v in value), key=lambda x: repr(x))
    if isinstance(value, (list, tuple)):
        return [_freeze(v) for v in value]
    if isinstance(value, float):
        if value != value:  # NaN
            return "NaN"
        return repr(value)
    return value


def _snapshot_result(result: Any) -> dict:
    out: dict[str, Any] = {}
    for field in _SCALAR_FIELDS:
        if hasattr(result, field):
            out[field] = _freeze(getattr(result, field))
    seg = getattr(result, "segments", None)
    out["segments"] = _freeze(seg) if seg is not None else None
    for group in _RESULT_GROUPS:
        obj = getattr(result, group, None)
        out[group] = _freeze(obj) if obj is not None else None
    unavail = getattr(result, "unavailable_metrics", None)
    out["unavailable_metrics"] = (
        sorted([list(item) for item in unavail]) if unavail else []
    )
    return out


def capture(out_path: str, limit: int | None, corpus: Path) -> int:
    from dpt_extractor.config.loader import load_config
    from dpt_extractor.io.waveform_loader import load_waveform
    from dpt_extractor.models.bridge_profile import guess_profile_from_path
    from dpt_extractor.models.channel_mapping import (
        apply_mapping,
        infer_best_mapping_from_bundle,
    )
    from dpt_extractor.pipeline.extract import extract_all
    from dpt_extractor.pipeline.short_circuit_extract import extract_short_circuit

    cfg = load_config()
    files = corpus_files(corpus)
    if limit is not None:
        files = files[:limit]

    records: list[dict] = []
    for i, path in enumerate(files):
        rec: dict[str, Any] = {"file": path.name, "rel": str(path), "error": ""}
        try:
            bundle = load_waveform(path)
            base = guess_profile_from_path(path)
            mapping, src = infer_best_mapping_from_bundle(bundle, base.bridge)
            prof = apply_mapping(base, mapping) if mapping is not None else base
            rec["mapping_source"] = src
            rec["bridge"] = prof.bridge
            rec["phase"] = prof.phase
            if is_short_circuit_sample(path):
                from dpt_extractor.models.bridge_profile import as_short_circuit_profile

                prof = as_short_circuit_profile(prof)
                result = extract_short_circuit(bundle, prof, cfg)
            else:
                result = extract_all(bundle, prof, cfg)
            rec["result"] = _snapshot_result(result)
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}:{exc}"
        records.append(rec)
        if i % 50 == 0:
            print(f"  captured {i+1}/{len(files)}")
            sys.stdout.flush()

    payload = {
        "meta": {
            "producer": "dpt_extractor (Python 现行实现)",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "corpus": str(corpus),
            "files": len(records),
            "ok": sum(1 for r in records if not r["error"]),
            "failed": sum(1 for r in records if r["error"]),
            "field_groups": list(_RESULT_GROUPS),
            "numeric_policy": "浮点以 repr() 往返表示，比对默认按字符串逐字相等（等价按位）",
        },
        "records": records,
    }
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n基准快照 -> {dest}  ({payload['meta']['ok']} ok / {payload['meta']['failed']} failed)")
    return 0


# ---------------------------------------------------------------- 比对


def _walk(
    a: Any,
    b: Any,
    path: str,
    diffs: list[dict],
    max_diffs: int,
    rel_tol: float | None,
) -> None:
    if len(diffs) >= max_diffs:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                diffs.append({"path": f"{path}.{key}", "kind": "仅在候选存在", "golden": None, "candidate": b[key]})
            elif key not in b:
                diffs.append({"path": f"{path}.{key}", "kind": "仅基准存在", "golden": a[key], "candidate": None})
            else:
                _walk(a[key], b[key], f"{path}.{key}", diffs, max_diffs, rel_tol)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append({"path": f"{path}.length", "kind": "长度不同", "golden": len(a), "candidate": len(b)})
        for i in range(min(len(a), len(b))):
            _walk(a[i], b[i], f"{path}[{i}]", diffs, max_diffs, rel_tol)
        return

    if a == b:
        return

    # 允许显式放宽的浮点比较
    if rel_tol is not None and not isinstance(a, bool) and not isinstance(b, bool):
        try:
            fa, fb = float(a), float(b)
            denom = max(abs(fa), abs(fb), 1e-300)
            if abs(fa - fb) / denom <= rel_tol:
                return
            diffs.append(
                {
                    "path": path,
                    "kind": "浮点超出相对容差",
                    "golden": a,
                    "candidate": b,
                    "rel_error": abs(fa - fb) / denom,
                }
            )
            return
        except (TypeError, ValueError):
            pass
    diffs.append({"path": path, "kind": "值不同", "golden": a, "candidate": b})


def compare(golden_path: str, candidate_path: str, rel_tol: float | None, max_diffs: int) -> int:
    golden = json.loads(Path(golden_path).read_text(encoding="utf-8"))
    cand = json.loads(Path(candidate_path).read_text(encoding="utf-8"))

    gm = {r["rel"]: r for r in golden["records"]}
    cm = {r["rel"]: r for r in cand["records"]}

    only_golden = sorted(set(gm) - set(cm))
    only_cand = sorted(set(cm) - set(gm))

    per_file: list[dict] = []
    total_diffs: list[dict] = []
    compared = 0

    for rel in sorted(set(gm) & set(cm)):
        g, c = gm[rel], cm[rel]
        name = g.get("file", rel)
        if g["error"] or c["error"]:
            if g["error"] != c["error"]:
                per_file.append({"file": name, "status": "错误状态不一致", "golden_error": g["error"], "candidate_error": c["error"]})
            continue
        diffs: list[dict] = []
        _walk(g.get("result"), c.get("result"), name, diffs, max_diffs, rel_tol)
        compared += 1
        if diffs:
            per_file.append({"file": name, "status": "有差异", "diff_count": len(diffs), "diffs": diffs[:20]})
            total_diffs.extend(diffs)
        else:
            per_file.append({"file": name, "status": "一致"})

    bad = [r for r in per_file if r["status"] != "一致"]
    report = {
        "golden": golden_path,
        "candidate": candidate_path,
        "policy": {
            "default": "位级一致（字符串逐字相等）",
            "rel_tol": rel_tol,
        },
        "summary": {
            "files_golden": len(gm),
            "files_candidate": len(cm),
            "files_compared": compared,
            "files_identical": compared - len([r for r in per_file if r["status"] == "有差异"]),
            "files_with_diff": len([r for r in per_file if r["status"] == "有差异"]),
            "files_status_mismatch": len([r for r in per_file if r["status"] == "错误状态不一致"]),
            "only_in_golden": only_golden,
            "only_in_candidate": only_cand,
            "total_field_diffs": len(total_diffs),
            "verdict": "PASS" if not bad and not only_golden and not only_cand else "FAIL",
        },
        "per_file": per_file,
    }

    out = write_json("diff_report.json", report)
    s = report["summary"]
    print("\n================ 差分比对结果 ================")
    print(f"基准文件数        : {s['files_golden']}")
    print(f"候选文件数        : {s['files_candidate']}")
    print(f"实际比对文件数    : {s['files_compared']}")
    print(f"逐参数完全一致    : {s['files_identical']}")
    print(f"存在差异          : {s['files_with_diff']}")
    print(f"错误状态不一致    : {s['files_status_mismatch']}")
    print(f"字段级差异总数    : {s['total_field_diffs']}")
    print(f"仅基准有          : {len(s['only_in_golden'])}")
    print(f"仅候选有          : {len(s['only_in_candidate'])}")
    print(f"容差口径          : {report['policy']['default']}" + (f"（rel_tol={rel_tol}）" if rel_tol else ""))
    print(f"\n>>> 判定: {s['verdict']}")
    if bad:
        print("\n差异样例（前 5 个文件）:")
        for r in bad[:5]:
            print(f"  {r['file']}: {r.get('diff_count', '-')} 处")
            for d in r.get("diffs", [])[:3]:
                print(f"    {d['path']}  {d['kind']}  基准={d['golden']}  候选={d['candidate']}")
    print(f"\n完整报告 -> {out}")

    # 生成种子用的写法：把不同字段出现的频次汇总，便于判断是系统性还是随机漂移
    freq: dict[str, int] = {}
    for d in total_diffs:
        key = d["path"].split(".", 2)[-1]
        freq[key] = freq.get(key, 0) + 1
    top = sorted(freq.items(), key=lambda kv: -kv[1])[:15]
    if top:
        print("\n差异最集中的字段（前 15）:")
        for k, v in top:
            print(f"  {v:5d}  {k}")

    return 0 if s["verdict"] == "PASS" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="数值一致性差分验收器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="用现行实现生成基准快照")
    cap.add_argument("--out", default="raw/golden_corpus.json")
    cap.add_argument("--limit", type=int, default=None)
    cap.add_argument("--corpus", default=str(DEFAULT_CORPUS))

    cmp_ = sub.add_parser("compare", help="比对基准与候选")
    cmp_.add_argument("--golden", required=True)
    cmp_.add_argument("--candidate", required=True)
    cmp_.add_argument("--rel-tol", type=float, default=None,
                      help="显式放宽的相对容差；默认 None 表示要求位级一致")
    cmp_.add_argument("--max-diffs", type=int, default=200)

    args = ap.parse_args()
    if args.cmd == "capture":
        return capture(args.out, args.limit, Path(args.corpus))
    return compare(args.golden, args.candidate, args.rel_tol, args.max_diffs)


if __name__ == "__main__":
    raise SystemExit(main())
