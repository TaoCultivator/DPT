"""汇总 hotspots.json：给出 Top 20 热点表与「第三方开销来自哪里」的证据。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/summarize_hotspots.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

RAW = _HERE.parent / "raw"


def main() -> int:
    data = json.loads((RAW / "hotspots.json").read_text(encoding="utf-8"))
    meta = data["meta"]
    total = meta["total_tottime_s"]

    print(f"剖析方法   : {meta['method']}")
    print(f"语料文件数 : {meta['corpus_files']}   抽样 {len(meta['sampled_files'])} 个 × {meta['repeat']} 轮")
    print(f"插桩总耗时 : {total:.2f} s\n")

    print("== Top 20 热点（本项目代码，按自身耗时 tottime）==")
    print(f"{'#':>3} {'位置':52s} {'函数':34s} {'tottime/s':>9} {'占比':>7} {'calls':>9}")
    for i, r in enumerate(data["top_project_by_tottime"][:20], 1):
        loc = f"{r['file'].split('dpt_extractor/')[-1]}:{r['line']}"
        print(
            f"{i:>3} {loc[:52]:52s} {r['func'][:34]:34s} "
            f"{r['tottime']:9.3f} {r['share_of_project_tt']*100:6.2f}% {r['ncalls']:9d}"
        )

    proj = data["top_project_by_tottime"]
    top3 = sum(r["share_of_project_tt"] for r in proj[:3])
    top5 = sum(r["share_of_project_tt"] for r in proj[:5])
    top10 = sum(r["share_of_project_tt"] for r in proj[:10])
    print(f"\n集中度：Top3 {top3*100:.1f}%  Top5 {top5*100:.1f}%  Top10 {top10*100:.1f}%（占本项目代码总耗时）")

    print("\n== 第三方开销集中在哪（全部代码，按自身耗时）==")
    print(f"{'tottime/s':>9} {'占比':>7} {'calls':>10}  {'位置'}")
    for r in data["top_all_by_tottime"][:12]:
        f = r["file"].split("site-packages/")[-1] if "site-packages" in r["file"] else r["file"]
        print(
            f"{r['tottime']:9.3f} {r['share_of_total_tt']*100:6.2f}% {r['ncalls']:10d}  {f}:{r['line']} {r['func'][:34]}"
        )

    # 关键证据：numpy 归约的调用次数
    reduce_calls = 0
    mean_calls = 0
    wrap_calls = 0
    for r in data["top_all_by_tottime"]:
        if "reduce" in r["func"] and "ufunc" in r["func"]:
            reduce_calls = max(reduce_calls, r["ncalls"])
        if r["func"] == "_mean":
            mean_calls = max(mean_calls, r["ncalls"])
        if r["func"] == "_wrapreduction":
            wrap_calls = max(wrap_calls, r["ncalls"])

    print("\n== 关键证据：小数组 numpy 分派开销 ==")
    print(f"  numpy.ufunc.reduce 调用次数 : {reduce_calls:,}")
    print(f"  numpy._methods._mean 调用   : {mean_calls:,}")
    print(f"  numpy._wrapreduction 调用   : {wrap_calls:,}")
    print("  -> 这些小数组归约主要来自 plateau_level.py 的双层窗口循环")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
