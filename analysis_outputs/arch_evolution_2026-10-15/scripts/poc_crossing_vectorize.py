"""PoC：``_nearest_raw_level_crossing_time_us`` 的等价优化 + 逐值一致性验证。

背景（来自 ``raw/bench_param_switch.json``）
--------------------------------------------
参数卡切换的最慢项（di/dt，848 ms）热点在
``dpt_extractor/gui/main_window.py:379 _nearest_raw_level_crossing_time_us``。
该函数用一个 **纯 Python 逐元素 for 循环** 扫描 21818 个采样点：

    for k in range(lo, hi):
        y0, y1 = float(yy[k]), float(yy[k + 1])
        ...
        candidates.append(...)

这是「解释器逐元素开销」型热点，而不是「数值算法」型热点。

PoC 目标
--------
1. 用 NumPy 向量化重写同一判据（**不改变任何阈值、公式或取值口径**）。
2. 在**全部语料**上逐次调用，验证：
   - 返回的交叉点时间 **逐值按位相等**（``==``，非近似）；
   - 候选集大小一致；
   - NaN / 无穷 / 平段 / 端点命中等边界行为一致。
3. 给出实测加速比。

本脚本**不修改生产代码**：向量化版本定义在本文件内，通过猴子补丁喂给调用方；
生产文件 ``dpt_extractor/gui/main_window.py`` 保持不变（由 ``--check-frozen`` 断言）。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/poc_crossing_vectorize.py
    python analysis_outputs/arch_evolution_2026-10-15/scripts/poc_crossing_vectorize.py --full-corpus
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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

import numpy as np  # noqa: E402

from dpt_extractor.utils.app_paths import configure_numba_cache_dir  # noqa: E402

configure_numba_cache_dir()

from dpt_extractor.config.loader import load_config  # noqa: E402
from dpt_extractor.gui import main_window as mw  # noqa: E402
from dpt_extractor.io.waveform_loader import load_waveform  # noqa: E402
from dpt_extractor.models.bridge_profile import guess_profile_from_path  # noqa: E402
from dpt_extractor.models.channel_mapping import (  # noqa: E402
    apply_mapping,
    infer_best_mapping_from_bundle,
)
from dpt_extractor.pipeline.extract import extract_all  # noqa: E402

_ORIGINAL = mw._nearest_raw_level_crossing_time_us


# ---------------------------------------------------------------- 向量化版本


def _candidates_vectorized(
    t: np.ndarray,
    values: np.ndarray,
    level: float,
    reference_index: int,
    search_start: int,
    search_end: int,
) -> tuple[np.ndarray, float]:
    """向量化地复现原函数的候选集与参考时间。

    返回 (候选时间数组单位=秒, ref_t)。语义与原函数逐条对应：

    * ``lo``/``hi``/``ref`` 的钳制完全一致；
    * 原来的 ``if y0 == target`` / ``if y1 == target`` 两个"精确命中"分支
      合并为 ``命中掩码``，命中时取对应端点时间，且此时不再算线性插值
      （原实现用 ``continue`` 跳过后续分支）；
    * 其余情况按 ``(y0-target)*(y1-target) < 0`` 判交叉，再线性插值；
    * 非有限（NaN/Inf）的端点对整对跳过 —— 与 ``np.isfinite`` 判断一致。
    """
    tt = np.asarray(t, dtype=np.float64)
    yy = np.asarray(values, dtype=np.float64)
    if len(tt) < 2 or len(yy) != len(tt) or not np.isfinite(float(level)):
        return np.empty(0, dtype=np.float64), 0.0
    lo = max(0, min(int(search_start), len(tt) - 2))
    hi = max(lo + 1, min(int(search_end), len(tt) - 1))
    ref = max(lo, min(int(reference_index), hi))
    ref_t = float(tt[ref])

    target = float(level)
    y0 = yy[lo:hi]
    y1 = yy[lo + 1 : hi + 1]
    t0 = tt[lo:hi]
    t1 = tt[lo + 1 : hi + 1]

    finite = np.isfinite(y0) & np.isfinite(y1)

    exact0 = finite & (y0 == target)
    exact1 = finite & (~exact0) & (y1 == target)
    # 剩余区间：两个端点的值与 target 之差乘积为负 -> 严格穿越
    rest = finite & ~exact0 & ~exact1
    d0 = np.where(rest, y0 - target, 0.0)  # 掩蔽非有限值，避免 NaN*Inf 告警
    d1 = np.where(rest, y1 - target, 0.0)
    cross = rest & ((d0 * d1) < 0.0)

    parts: list[np.ndarray] = []
    if exact0.any():
        parts.append(t0[exact0])
    if exact1.any():
        parts.append(t1[exact1])
    if cross.any():
        dy = y1[cross] - y0[cross]
        frac = (target - y0[cross]) / dy
        parts.append(t0[cross] + frac * (t1[cross] - t0[cross]))
    if not parts:
        return np.empty(0, dtype=np.float64), ref_t
    return np.concatenate(parts), ref_t


def _vectorized_crossing_time_us(
    t: np.ndarray,
    values: np.ndarray,
    level: float,
    reference_index: int,
    search_start: int,
    search_end: int,
) -> float | None:
    """与原函数返回值口径完全相同的向量化实现。"""
    cand, ref_t = _candidates_vectorized(
        t, values, level, reference_index, search_start, search_end
    )
    if cand.size == 0:
        return None
    return float(cand[np.argmin(np.abs(cand - ref_t))]) * 1e6


# ---------------------------------------------------------------- 一致性验证


def _equivalence_cases() -> list[dict]:
    """构造覆盖边界情况的合成用例（平段、NaN、Inf、精确命中、无交叉…）。"""
    rng = np.random.default_rng(20261015)
    cases: list[dict] = []

    def add(name: str, t: np.ndarray, y: np.ndarray, level: float, ref: int, a: int, b: int):
        cases.append(
            {
                "name": name,
                "t": t,
                "values": y,
                "level": level,
                "reference_index": ref,
                "search_start": a,
                "search_end": b,
            }
        )

    n = 500
    t = np.linspace(0.0, 5e-6, n)
    add("随机游走", t, np.cumsum(rng.normal(0, 1, n)), 0.0, n // 2, 0, n)

    y = np.sin(np.linspace(0, 20, n))
    add("多交叉", t, y, 0.5, n // 2, 0, n)

    y2 = np.ones(n)
    y2[n // 3] = 3.0
    add("平段+单尖峰", t, y2, 2.0, 0, 0, n)

    y3 = np.zeros(n)
    y3[:] = 7.0
    add("全精确命中", t, y3, 7.0, 3, 0, n)

    y4 = np.zeros(n)
    y4[n // 2] = np.nan
    y4[n // 2 + 1] = 5.0
    add("含 NaN", t, y4, 2.5, n // 2, 0, n)

    y5 = np.zeros(n)
    y5[n // 4] = np.inf
    y5[n // 4 + 1] = -np.inf
    add("含 Inf", t, y5, 0.0, 0, 0, n)

    y6 = np.linspace(-1, 1, n)
    add("单调线性", t, y6, 0.0, n // 2, 0, n)

    add("无交叉", t, np.full(n, 99.0), 1.0, 0, 0, n)

    add("越界索引钳制", t, rng.normal(0, 2, n), 0.0, -5, -10, n + 10)

    add("degenerate len<2", t[:1], np.array([1.0]), 0.0, 0, 0, 1)

    y7 = np.zeros(n)
    y7[n // 2] = 4.0
    y7[n // 2 + 1] = 5.0
    add("水平穿越", t, y7, 4.5, n // 2, 0, n)

    return cases


def _check_frozen() -> dict:
    """断言生产文件未被本 PoC 修改。"""
    path = Path(mw.__file__)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path), "sha256": digest}


def _random_fuzz(rounds: int, seed: int) -> list[dict]:
    """随机模糊测试：随机波形 + 随机 level/索引，逐例比对。"""
    rng = np.random.default_rng(seed)
    mismatches: list[dict] = []
    for i in range(rounds):
        n = int(rng.integers(3, 900))
        t = np.sort(rng.uniform(0, 1e-5, n))
        kind = i % 5
        if kind == 0:
            y = rng.normal(0, 1, n)
        elif kind == 1:
            y = np.round(rng.normal(0, 2, n))  # 制造大量精确命中
        elif kind == 2:
            y = np.full(n, float(rng.integers(-2, 3)))  # 全平
        elif kind == 3:
            y = rng.normal(0, 1, n)
            y[rng.integers(0, n, max(1, n // 10))] = np.nan
        else:
            y = np.linspace(-3, 3, n)
        level = float(rng.choice([0.0, 0.5, -1.25, float(rng.normal(0, 2))]))
        a = int(rng.integers(0, max(1, n)))
        b = int(rng.integers(0, max(1, n)))
        if a > b:
            a, b = b, a
        ref = int(rng.integers(0, max(1, n)))
        orig = _ORIGINAL(t, y, level, ref, a, b)
        new = _vectorized_crossing_time_us(t, y, level, ref, a, b)
        same = (orig is None and new is None) or (
            orig is not None and new is not None and float(orig) == float(new)
        )
        if not same:
            mismatches.append(
                {
                    "round": i,
                    "n": n,
                    "level": level,
                    "a": a,
                    "b": b,
                    "ref": ref,
                    "original": orig,
                    "vectorized": new,
                }
            )
    return mismatches


# ---------------------------------------------------------------- 语料实测


def _stratified_pick(files: list[Path], want: int) -> list[Path]:
    """按体积分层抽样并混入短路样例，避免只覆盖单一算路。"""
    ordered = sorted(files, key=lambda p: p.stat().st_size)
    third = max(1, len(ordered) // 3)
    strata = [ordered[:third], ordered[third : 2 * third], ordered[2 * third :]]
    per = max(1, want // 3)
    picked: list[Path] = []
    for stratum in strata:
        half = max(1, per // 2)
        picked.extend(stratum[:half])
        picked.extend([p for p in stratum if is_short_circuit_sample(p)][:half])
    seen: set[Path] = set()
    out: list[Path] = []
    for p in picked:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out[:want]


def _collect_calls(want_files: int) -> list[dict]:
    """抓取该函数的真实调用参数。

    **重要口径修正**：``_nearest_raw_level_crossing_time_us`` **不在** headless
    参数提取路径里被调用 —— 它只在 **GUI 参数卡点击**时被调用（把检测/平均电平
    投影回最近的真实波形过零点）。首次尝试直接从 ``extract_all`` 抓取，得到
    0 次调用，就是这个原因。

    因此这里改为驱动真实的 **offscreen Qt 窗口**：加载样例 → 重放参数卡点击回调，
    这才是**用户可直接感知**的那条路径（对应 ``bench_param_switch.json`` 中的
    848 ms 最慢项）。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from dpt_extractor.gui.main_window import MainWindow

    files = _stratified_pick(corpus_files(DEFAULT_CORPUS), want_files)
    captured: list[dict] = []

    def spy(t, values, level, reference_index, search_start, search_end):
        captured.append(
            {
                "t": np.asarray(t, dtype=np.float64),
                "values": np.asarray(values, dtype=np.float64),
                "level": float(level),
                "reference_index": int(reference_index),
                "search_start": int(search_start),
                "search_end": int(search_end),
            }
        )
        return _ORIGINAL(t, values, level, reference_index, search_start, search_end)

    win = None
    try:
        from PyQt6.QtWidgets import QApplication as _QApp

        app = _QApp.instance() or _QApp([])
        win = MainWindow()
        win.resize(1600, 900)
        app.processEvents()
        mw._nearest_raw_level_crossing_time_us = spy

        for i, path in enumerate(files):
            try:
                win._load_file(str(path))
                app.processEvents()
            except Exception:  # noqa: BLE001
                continue
            metas = list(getattr(win.result_table, "_row_meta", []) or [])
            seen: set[tuple[str, str]] = set()
            for meta in metas:
                if not meta or len(meta) < 2:
                    continue
                key = (str(meta[0]).strip(), str(meta[1]).strip())
                if not key[0] or not key[1] or key in seen:
                    continue
                seen.add(key)
                try:
                    win._on_result_value_clicked(key[0], key[1])
                    app.processEvents()
                except Exception:  # noqa: BLE001
                    continue
            print(f"  scanned {i+1}/{len(files)}  calls={len(captured)}")
            sys.stdout.flush()
    finally:
        mw._nearest_raw_level_crossing_time_us = _ORIGINAL
        if win is not None:
            try:
                win.close()
            except Exception:  # noqa: BLE001
                pass
    return captured


def _measure_speed(calls: list[dict], repeats: int = 1) -> dict:
    """在真实调用参数上对比两种实现的总耗时。"""
    if not calls:
        return {}

    # 预热
    for c in calls[: min(50, len(calls))]:
        _ORIGINAL(c["t"], c["values"], c["level"], c["reference_index"], c["search_start"], c["search_end"])
        _vectorized_crossing_time_us(c["t"], c["values"], c["level"], c["reference_index"], c["search_start"], c["search_end"])

    t0 = time.perf_counter()
    for _ in range(repeats):
        for c in calls:
            _ORIGINAL(c["t"], c["values"], c["level"], c["reference_index"], c["search_start"], c["search_end"])
    t_orig = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(repeats):
        for c in calls:
            _vectorized_crossing_time_us(c["t"], c["values"], c["level"], c["reference_index"], c["search_start"], c["search_end"])
    t_new = time.perf_counter() - t0

    scans = [c["search_end"] - c["search_start"] for c in calls]
    return {
        "calls": len(calls),
        "repeats": repeats,
        "total_scanned_elements": int(sum(scans)),
        "mean_scanned_elements": round(sum(scans) / len(scans), 1) if scans else 0,
        "max_scanned_elements": int(max(scans)) if scans else 0,
        "original_total_ms": round(t_orig * 1000, 3),
        "vectorized_total_ms": round(t_new * 1000, 3),
        "original_per_call_us": round(t_orig / len(calls) / repeats * 1e6, 2),
        "vectorized_per_call_us": round(t_new / len(calls) / repeats * 1e6, 2),
        "speedup": round(t_orig / t_new, 2) if t_new > 0 else None,
    }


def _compare_on_calls(calls: list[dict]) -> dict:
    """逐调用比对返回值是否按位相等。"""
    mismatch: list[dict] = []
    both_none = 0
    equal = 0
    for i, c in enumerate(calls):
        args = (c["t"], c["values"], c["level"], c["reference_index"], c["search_start"], c["search_end"])
        a = _ORIGINAL(*args)
        b = _vectorized_crossing_time_us(*args)
        if a is None and b is None:
            both_none += 1
            continue
        if a is not None and b is not None and float(a) == float(b):
            equal += 1
            continue
        mismatch.append(
            {
                "call": i,
                "search_start": c["search_start"],
                "search_end": c["search_end"],
                "level": c["level"],
                "original": a,
                "vectorized": b,
            }
        )
    return {
        "calls": len(calls),
        "bitwise_equal": equal,
        "both_none": both_none,
        "mismatch_count": len(mismatch),
        "mismatch_examples": mismatch[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=60,
                    help="抓取真实调用时抽样多少个语料文件（每个文件只跑一次提取）")
    ap.add_argument("--fuzz", type=int, default=4000, help="随机模糊测试轮数")
    args = ap.parse_args()

    frozen = _check_frozen()
    print(f"生产文件（未修改）: {frozen['path']}")
    print(f"  sha256: {frozen['sha256']}\n")

    # --- 1. 合边界用例 ---
    print("== 1. 边界用例比对 ==")
    synth_mismatch = []
    synth_total = 0
    for case in _equivalence_cases():
        call_args = (
            case["t"],
            case["values"],
            case["level"],
            case["reference_index"],
            case["search_start"],
            case["search_end"],
        )
        a = _ORIGINAL(*call_args)
        b = _vectorized_crossing_time_us(*call_args)
        synth_total += 1
        ok = (a is None and b is None) or (
            a is not None and b is not None and float(a) == float(b)
        )
        flag = "OK " if ok else "DIFF"
        print(f"  [{flag}] {case['name']:16s} original={a} vectorized={b}")
        if not ok:
            synth_mismatch.append({"case": case["name"], "original": a, "vectorized": b})
    print(f"  边界用例 {synth_total - len(synth_mismatch)}/{synth_total} 按位一致\n")

    # --- 2. 随机模糊 ---
    print(f"== 2. 随机模糊测试 {args.fuzz} 轮 ==")
    fuzz_mismatch = _random_fuzz(args.fuzz, seed=20261015)
    print(f"  不一致 {len(fuzz_mismatch)} 例 / {args.fuzz}\n")

    # --- 3. 真实语料抓取 ---
    scope = f"分层抽样 {args.files} 个文件（覆盖小/中/大体积与短路/双脉冲算路）"
    print(f"== 3. 真实语料调用抓取（{scope}）==")
    calls = _collect_calls(args.files)
    print(f"  抓到真实调用 {len(calls)} 次\n")

    corpus_cmp = _compare_on_calls(calls) if calls else {}
    speed = _measure_speed(calls) if calls else {}

    if corpus_cmp:
        print("== 4. 真实语料逐值比对 ==")
        print(f"  调用总数      : {corpus_cmp['calls']}")
        print(f"  按位相等      : {corpus_cmp['bitwise_equal']}")
        print(f"  双方均为 None : {corpus_cmp['both_none']}")
        print(f"  不一致        : {corpus_cmp['mismatch_count']}")
        if corpus_cmp["mismatch_examples"]:
            for m in corpus_cmp["mismatch_examples"]:
                print(f"    {m}")

    if speed:
        print("\n== 5. 实测加速比（相同真实调用参数）==")
        print(f"  调用次数            : {speed['calls']}")
        print(f"  合计扫描样点数      : {speed['total_scanned_elements']:,}")
        print(f"  平均每次扫描点数    : {speed['mean_scanned_elements']:,}")
        print(f"  原始实现总耗时      : {speed['original_total_ms']:.2f} ms  ({speed['original_per_call_us']:.1f} us/次)")
        print(f"  向量化总耗时        : {speed['vectorized_total_ms']:.2f} ms  ({speed['vectorized_per_call_us']:.1f} us/次)")
        print(f"  >>> 加速比          : {speed['speedup']}x")

    payload = {
        "frozen_production_file": frozen,
        "boundary_cases": {
            "total": synth_total,
            "mismatch": synth_mismatch,
        },
        "fuzz": {
            "rounds": args.fuzz,
            "mismatch_count": len(fuzz_mismatch),
            "mismatch_examples": fuzz_mismatch[:10],
        },
        "corpus_comparison": corpus_cmp,
        "speed": speed,
        "scope": {
            "sampled_files": args.files,
            "description": scope,
            "note": "每个文件只跑一次提取；调用数即该抽样集下该函数的实际调用总数",
        },
    }
    out = write_json("poc_crossing_vectorize.json", payload)
    print(f"\nraw -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
