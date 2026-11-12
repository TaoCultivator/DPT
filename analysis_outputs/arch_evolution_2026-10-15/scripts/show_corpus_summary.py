"""打印 bench_full_corpus.json 的汇总（只读，便于粘贴进报告）。"""
from __future__ import annotations

import json
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "raw"


def main() -> int:
    d = json.loads((RAW / "bench_full_corpus.json").read_text(encoding="utf-8"))
    s = d["summary"]

    print("== 全语料吞吐基线 ==")
    order = [
        "corpus",
        "files_total",
        "files_ok",
        "files_failed",
        "total_mb_ok",
        "cold_start_load_s",
        "sum_t_load_s",
        "sum_t_map_s",
        "sum_t_extract_s",
        "sum_t_total_s",
        "throughput_files_per_s",
        "throughput_mb_per_s",
        "extract_share_of_total",
        "load_share_of_total",
    ]
    for k in order:
        if k in s:
            print(f"  {k:24s} {s[k]}")

    print("\n== 分阶段统计 ==")
    for name, st in s["stats"].items():
        if not st:
            continue
        print(
            f"  {name:9s} sum={st['sum_s']:10.2f}s  mean={st['mean_s']:9.5f}s  "
            f"median={st['median_s']:9.5f}s  p95={st['p95_s']:9.5f}s  max={st['max_s']:9.5f}s"
        )

    print("\n== 失败分类 ==")
    for k, v in s.get("error_kinds", {}).items():
        print(f"  {k}: {v}")

    # 最慢的 10 个文件
    ok = [r for r in d["records"] if not r.get("error")]
    ok.sort(key=lambda r: r["t_extract"], reverse=True)
    print("\n== 提取耗时最长的 10 个文件 ==")
    for r in ok[:10]:
        print(f"  {r['t_extract']:8.3f}s  {r['size_mb']:6.2f}MB  n={r.get('n_samples', 0):>7d}  {r['rel'][:60]}")

    fastest = sorted(r["t_extract"] for r in ok)
    print(f"\n  最快 10 个提取均值: {sum(fastest[:10])/10:.4f}s")
    print(f"  最慢 10 个提取均值: {sum(fastest[-10:])/10:.4f}s")
    print(f"  比值: {sum(fastest[-10:])/sum(fastest[:10]):.1f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
