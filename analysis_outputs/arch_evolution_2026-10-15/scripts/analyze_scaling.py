"""从全语料基线里提取「提取耗时 vs 采样点数」的标度关系。

用途：判断热点是**与采样点数成比例**（逐元素循环/分派）还是**由算路分支决定**。
这是区分「向量化/Rust 有效」与「I/O 或固定开销」的关键判据。

重要口径校正（已实测核实，见 ``check_bundle_shape.py``）：
语料里 ``bundle.n`` 与 ``len(bundle.t)`` **始终相等**，但不同文件的采样点数
跨度极大（62 500 → 5 000 000），因此不能假设「文件大小 ≈ 采样点数」。
``bench_full_corpus.py`` 记录的 ``n_samples`` 直接取自 ``bundle.n``，口径正确。

若线性拟合的 R² 很低，说明耗时**不是**由采样点数单调决定，而是由
算路分支（单脉冲/双脉冲、短路、平台搜索深度）决定 —— 这一点本身很重要：
它意味着「换语言」不会自动解决问题，必须逐个算路看。

只用 numpy 做一元线性回归，不引入新依赖。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/analyze_scaling.py
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

RAW = Path(__file__).resolve().parents[1] / "raw"


def main() -> int:
    d = json.loads((RAW / "bench_full_corpus.json").read_text(encoding="utf-8"))
    ok = [r for r in d["records"] if not r.get("error") and r.get("n_samples")]
    if not ok:
        print("没有可用记录")
        return 1

    by_n: dict[int, list[float]] = defaultdict(list)
    for r in ok:
        by_n[int(r["n_samples"])].append(float(r["t_extract"]))

    rows = sorted(by_n.items())
    base = None
    for n, vals in rows:
        if n == 62500:
            base = sorted(vals)[len(vals) // 2]

    print("== 采样点数 → 参数提取耗时 ==")
    print(f"{'采样点数':>10} {'文件数':>6} {'均值(s)':>9} {'中位(s)':>9} {'ns/采样点':>11} {'相对 62500点':>13}")
    for n, vals in rows:
        vals_sorted = sorted(vals)
        mean = sum(vals) / len(vals)
        med = vals_sorted[len(vals_sorted) // 2]
        ratio = f"{med / base:.1f}x" if base else "-"
        print(f"{n:>10d} {len(vals):>6d} {mean:>9.4f} {med:>9.4f} {med / n * 1e9:>11.1f} {ratio:>13}")

    # 一元线性回归 t = a + b*n（最小二乘，只用 numpy）
    ns = np.array([r["n_samples"] for r in ok], dtype=float)
    ts = np.array([r["t_extract"] for r in ok], dtype=float)
    b, a = np.polyfit(ns, ts, 1)
    pred = a + b * ns
    ss_res = float(np.sum((ts - pred) ** 2))
    ss_tot = float(np.sum((ts - ts.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")

    print("\n== 线性模型 t ≈ a + b·n（最小二乘）==")
    print(f"  斜率 b = {b * 1e9:.3f} ns/采样点")
    print(f"  截距 a = {a * 1e3:.2f} ms")
    print(f"  R²    = {r2:.4f}   （越接近 1 说明耗时越由采样点数单调决定）")
    print(f"  样本数 = {len(ok)}")

    # 单位采样点成本的离散度：R² 低时看这个，说明算路分支主导
    per_sample = np.array(
        [r["t_extract"] / max(1, int(r["n_samples"])) for r in ok], dtype=float
    )
    print("\n== 单位采样点成本离散度（ns/采样点）==")
    print(f"  中位 {np.median(per_sample) * 1e9:.1f}   "
          f"P10 {np.percentile(per_sample, 10) * 1e9:.1f}   "
          f"P90 {np.percentile(per_sample, 90) * 1e9:.1f}   "
          f"最大 {per_sample.max() * 1e9:.1f}")
    ratio = np.percentile(per_sample, 90) / max(np.percentile(per_sample, 10), 1e-12)
    print(f"  P90/P10 = {ratio:.1f}x")

    if r2 < 0.5:
        print("\n  判读：R² 偏低 → 提取耗时**不是**由采样点数单调决定，")
        print("        而是由算路分支（脉冲识别路径、平台搜索深度、短路/偏移模式）主导。")
        print("        因此「换语言」不会自动解决问题，必须逐算路实测。")

    # 按桥臂/模式看是否存在特例
    print("\n== 按识别出的 profile 分组（前 8）==")
    by_prof: dict[str, list[float]] = defaultdict(list)
    for r in ok:
        key = f"{r.get('phase', '?')}/{r.get('bridge', '?')}"
        by_prof[key].append(float(r["t_extract"]))
    items = sorted(by_prof.items(), key=lambda kv: -(sum(kv[1]) / len(kv[1])))[:8]
    for key, vals in items:
        print(f"  {key:12s} n={len(vals):>3d}  均值 {sum(vals)/len(vals):8.4f}s  中位 {sorted(vals)[len(vals)//2]:8.4f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
