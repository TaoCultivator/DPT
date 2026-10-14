"""补充测量：参数卡切换的首次 vs 稳态成本（定位 816ms 尖峰）。

用法::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/bench_param_switch.py
"""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import statistics
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

from dpt_extractor.utils.app_paths import configure_numba_cache_dir  # noqa: E402

configure_numba_cache_dir()

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dpt_extractor.gui.main_window import MainWindow  # noqa: E402


def main() -> int:
    files = [p for p in corpus_files(DEFAULT_CORPUS) if not is_short_circuit_sample(p)]
    files.sort(key=lambda p: p.stat().st_size)
    sample = files[len(files) // 2]
    print(f"sample: {sample.name}")

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.resize(1600, 900)
    app.processEvents()
    win._load_file(str(sample))
    app.processEvents()

    metas = list(getattr(win.result_table, "_row_meta", []) or [])
    uniq: list[tuple[str, str]] = []
    seen = set()
    for meta in metas:
        key = (str(meta[0]), str(meta[1]))
        if key not in seen:
            seen.add(key)
            uniq.append(key)
    print(f"parameter items: {len(uniq)}")

    viewport = win.wave_plot.plot.viewport()

    # 逐项测，全部记录（不做 [:10] 截断）
    per_item: list[dict] = []
    prof = cProfile.Profile()
    for i, (section, name) in enumerate(uniq):
        t = time.perf_counter()
        if i == 0:
            prof.enable()
        win._on_result_value_clicked(section, name)
        app.processEvents()
        viewport.grab()
        if i == 0:
            prof.disable()
        end = time.perf_counter()
        per_item.append(
            {"i": i, "section": section, "name": name, "ms": round((end - t) * 1000, 2)}
        )

    ms = [r["ms"] for r in per_item]
    ordered = sorted(ms)

    # 冷启动 vs 稳态：第一项 vs 其余
    first = ms[0] if ms else 0.0
    rest = ms[1:]
    summary = {
        "sample": str(sample),
        "parameter_items": len(uniq),
        "first_switch_ms": first,
        "rest_median_ms": round(statistics.median(rest), 2) if rest else None,
        "rest_mean_ms": round(statistics.fmean(rest), 2) if rest else None,
        "all_median_ms": round(statistics.median(ms), 2) if ms else None,
        "all_p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2) if ms else None,
        "all_max_ms": round(ordered[-1], 2) if ms else None,
        "all_max_item": max(per_item, key=lambda r: r["ms"]) if per_item else None,
        "fast_items_over_50ms": [
            r for r in per_item if r["ms"] > 50 and r["i"] != 0
        ],
    }

    buf = io.StringIO()
    stats = pstats.Stats(prof, stream=buf)
    stats.sort_stats("cumtime")
    rows = []
    for (fn, ln, func), (cc, nc, tt, ct, _c) in stats.stats.items():
        try:
            rel = str(Path(fn).resolve().relative_to(Path(__file__).resolve().parents[3]))
        except (ValueError, OSError):
            rel = fn
        rows.append(
            {
                "file": rel.replace("\\", "/"),
                "line": ln,
                "func": func,
                "tottime_ms": round(tt * 1000, 2),
                "cumtime_ms": round(ct * 1000, 2),
                "ncalls": nc,
            }
        )
    rows.sort(key=lambda r: r["tottime_ms"], reverse=True)
    project = [r for r in rows if "dpt_extractor" in r["file"]][:20]

    payload = {
        "summary": summary,
        "per_item": per_item,
        "first_switch_profile_top20_tottime": project,
    }
    out = write_json("bench_param_switch.json", payload)

    print(f"\n首项切换  : {first:.2f} ms")
    print(f"其余中位  : {summary['rest_median_ms']} ms   其余均值: {summary['rest_mean_ms']} ms")
    print(f"全部中位  : {summary['all_median_ms']} ms   p95: {summary['all_p95_ms']} ms   max: {summary['all_max_ms']} ms")
    print(f"最慢项    : {summary['all_max_item']}")
    print("\n首次切换热点 Top10（tottime）:")
    for r in project[:10]:
        print(f"  {r['file'].split('dpt_extractor/')[-1]}:{r['line']} {r['func']} {r['tottime_ms']} ms n={r['ncalls']}")
    print(f"\nraw -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
