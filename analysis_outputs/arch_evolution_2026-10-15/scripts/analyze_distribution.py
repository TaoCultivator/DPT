"""按采样点数分组看提取耗时的**分布形状**（不只看均值）。

动机：``analyze_scaling.py`` 显示同样 62 500 点的文件，均值 0.372 s 但
125 000 点只有 0.086 s —— 采样点更多反而更快，说明组内是**双峰**的。
只看均值会把「慢算路」和「快算路」平均掉，得出错误结论。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/analyze_distribution.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "raw"


def main() -> int:
    d = json.loads((RAW / "bench_full_corpus.json").read_text(encoding="utf-8"))
    ok = [r for r in d["records"] if not r.get("error") and r.get("n_samples")]

    by_n: dict[int, list[dict]] = defaultdict(list)
    for r in ok:
        by_n[int(r["n_samples"])].append(r)

    print("== 每个采样点数分组的耗时分布 ==")
    for n in sorted(by_n):
        rows = by_n[n]
        vals = sorted(r["t_extract"] for r in rows)
        k = len(vals)
        p10 = vals[max(0, int(k * 0.10))]
        p50 = vals[k // 2]
        p90 = vals[min(k - 1, int(k * 0.90))]
        fast = sum(1 for v in vals if v < 0.15)
        slow = sum(1 for v in vals if v >= 0.15)
        print(
            f"  n={n:>8d}  文件数={k:>3d}  P10={p10:7.4f}  P50={p50:7.4f}  P90={p90:7.4f}  "
            f"快(<0.15s)={fast:>3d}  慢(>=0.15s)={slow:>3d}"
        )

    print("\n== 分组：走「慢算路」的文件有什么共同点 ==")
    n625 = by_n.get(62500, [])
    slow = [r for r in n625 if r["t_extract"] >= 0.15]
    fast = [r for r in n625 if r["t_extract"] < 0.15]
    print(f"  n=62500 慢算路 {len(slow)} 个，文件样例：")
    for r in sorted(slow, key=lambda x: -x["t_extract"])[:6]:
        print(f"    {r['t_extract']:7.4f}s  sc={r['short_circuit']!s:5s}  {r['rel'][-58:]}")
    print(f"  n=62500 快算路 {len(fast)} 个，文件样例：")
    for r in sorted(fast, key=lambda x: x["t_extract"])[:6]:
        print(f"    {r['t_extract']:7.4f}s  sc={r['short_circuit']!s:5s}  {r['rel'][-58:]}")

    print("\n== 短路 vs 双脉冲（全语料）==")
    for flag in (True, False):
        rows = [r for r in ok if bool(r["short_circuit"]) == flag]
        if not rows:
            continue
        vals = sorted(r["t_extract"] for r in rows)
        label = "短路" if flag else "双脉冲"
        print(
            f"  {label}: 文件数={len(rows):>3d}  中位={vals[len(vals)//2]:7.4f}s  "
            f"均值={sum(vals)/len(vals):7.4f}s  最大={vals[-1]:7.4f}s"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
