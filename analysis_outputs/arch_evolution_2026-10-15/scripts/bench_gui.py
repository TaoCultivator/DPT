"""性能基线 3/3：GUI 交互耗时（offscreen Qt）。

用法（从仓库根运行）::

    python analysis_outputs/arch_evolution_2026-10-15/scripts/bench_gui.py

口径说明（重要）
----------------
本机是**无显示环境**，只能用 ``QT_QPA_PLATFORM=offscreen``。因此：

* 能测的：真实 Qt 控件构造、真实数据装载进绘图项、真实视图变换、**真实重绘耗时**
  —— 通过 ``QWidget.grab()`` 强制同步渲染，读出「一次重绘的 CPU 成本」。
* 不能测的：GPU/合成器实际帧率（FPS）。offscreen 后端走光栅化，
  与用户机器的真实显示路径不同。报告里只给「单次重绘毫秒」，
  **不换算成 FPS**，避免把不同口径混为一谈。

输出：``raw/bench_gui.json``。
"""
from __future__ import annotations

import os
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

from dpt_extractor.config.loader import load_config  # noqa: E402
from dpt_extractor.gui.main_window import MainWindow  # noqa: E402
from dpt_extractor.io.waveform_loader import load_waveform  # noqa: E402
from dpt_extractor.models.bridge_profile import (  # noqa: E402
    as_short_circuit_profile,
    guess_profile_from_path,
)
from dpt_extractor.models.channel_mapping import (  # noqa: E402
    apply_mapping,
    infer_best_mapping_from_bundle,
)
from dpt_extractor.pipeline.extract import extract_all  # noqa: E402
from dpt_extractor.pipeline.short_circuit_extract import extract_short_circuit  # noqa: E402


def _pick_sample() -> Path:
    """优先选一个体积中等的双脉冲样例，覆盖面广且不至于太慢。"""
    files = [p for p in corpus_files(DEFAULT_CORPUS) if not is_short_circuit_sample(p)]
    files.sort(key=lambda p: p.stat().st_size)
    return files[len(files) // 2]


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {}
    ordered = sorted(vals)
    return {
        "n": len(vals),
        "mean_ms": round(statistics.fmean(vals) * 1000, 3),
        "median_ms": round(statistics.median(vals) * 1000, 3),
        "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)] * 1000, 3),
        "min_ms": round(ordered[0] * 1000, 3),
        "max_ms": round(ordered[-1] * 1000, 3),
    }


def main() -> int:
    sample = _pick_sample()
    print(f"sample: {sample}")
    print(f"size: {sample.stat().st_size/1024:.1f} KB")
    sys.stdout.flush()

    app = QApplication.instance() or QApplication([])
    cfg = load_config()

    results: dict = {
        "platform": os.environ.get("QT_QPA_PLATFORM"),
        "sample": str(sample),
        "sample_kb": round(sample.stat().st_size / 1024, 1),
        "note": "offscreen 光栅化；单次重绘 CPU 成本，不等于 GPU 帧率",
    }

    # ---- 1. 冷启动：MainWindow 构造 ----
    t0 = time.perf_counter()
    win = MainWindow()
    t1 = time.perf_counter()
    results["window_construct_ms"] = round((t1 - t0) * 1000, 2)
    print(f"MainWindow()                  : {(t1-t0)*1000:8.2f} ms")
    sys.stdout.flush()

    win.resize(1600, 900)
    app.processEvents()

    try:
        # ---- 2. 首屏：加载文件（含解析 + 提取 + 首次绘制）----
        t0 = time.perf_counter()
        win._load_file(str(sample))
        app.processEvents()
        t1 = time.perf_counter()
        first_screen = t1 - t0
        results["first_screen_ms"] = round(first_screen * 1000, 2)
        print(f"首屏 _load_file + events      : {first_screen*1000:8.2f} ms")
        sys.stdout.flush()

        # 首屏后强制一次完整重绘，作为「稳态单帧成本」的基准
        t0 = time.perf_counter()
        win.grab()
        t1 = time.perf_counter()
        results["repaint_full_window_ms"] = round((t1 - t0) * 1000, 2)
        print(f"整窗一次重绘 grab()           : {(t1-t0)*1000:8.2f} ms")

        plot = win.wave_plot
        viewport = plot.plot.viewport()

        # ---- 3. 平移：连续改变 X 视窗并强制重绘 ----
        span = None
        try:
            span = plot.current_x_range_us()
        except Exception:  # noqa: BLE001
            span = None
        if not span:
            span = (0.0, 40.0)
        x0, x1 = float(span[0]), float(span[1])
        width = x1 - x0
        if width <= 0:
            width = 40.0
        vb = plot.plot.getPlotItem().getViewBox()

        pan_paint: list[float] = []
        pan_set: list[float] = []
        steps = 12
        for i in range(steps):
            shift = width * 0.03 * i
            a, b = x0 + shift, x0 + shift + width * 0.6
            t = time.perf_counter()
            vb.setXRange(a, b, padding=0.0)
            app.processEvents()
            mid = time.perf_counter()
            viewport.grab()
            end = time.perf_counter()
            pan_set.append(mid - t)
            pan_paint.append(end - mid)
        results["pan_view_set_ms"] = _stats(pan_set)
        results["pan_repaint_ms"] = _stats(pan_paint)
        print(f"平移 视图变换 (n={len(pan_set)})       : 中位 {results['pan_view_set_ms']['median_ms']:.2f} ms")
        print(f"平移 单次重绘 (n={len(pan_paint)})     : 中位 {results['pan_repaint_ms']['median_ms']:.2f} ms")

        # ---- 4. 缩放：连续收窄 X 视窗 ----
        zoom_paint: list[float] = []
        zoom_set: list[float] = []
        for i in range(steps):
            factor = 0.82 ** i
            centre = (x0 + x1) / 2
            half = width * factor / 2
            t = time.perf_counter()
            vb.setXRange(centre - half, centre + half, padding=0.0)
            app.processEvents()
            mid = time.perf_counter()
            viewport.grab()
            end = time.perf_counter()
            zoom_set.append(mid - t)
            zoom_paint.append(end - mid)
        results["zoom_view_set_ms"] = _stats(zoom_set)
        results["zoom_repaint_ms"] = _stats(zoom_paint)
        print(f"缩放 视图变换 (n={len(zoom_set)})       : 中位 {results['zoom_view_set_ms']['median_ms']:.2f} ms")
        print(f"缩放 单次重绘 (n={len(zoom_paint)})     : 中位 {results['zoom_repaint_ms']['median_ms']:.2f} ms")

        # ---- 5. 参数卡切换：重放真实点击回调 ----
        table = getattr(win, "result_table", None)
        param_switch: list[float] = []
        switched: list[str] = []
        uniq: list[tuple[str, str]] = []
        if table is not None:
            keys: list[tuple[str, str]] = []
            # ResultTable 是 QTableWidget，``_row_meta`` 保存 (section, name)
            try:
                for meta in getattr(table, "_row_meta", []) or []:
                    if not meta or len(meta) < 2:
                        continue
                    section, name = str(meta[0]).strip(), str(meta[1]).strip()
                    if section and name:
                        keys.append((section, name))
            except Exception as exc:  # noqa: BLE001
                results["param_switch_error"] = f"enumerate:{type(exc).__name__}:{exc}"

            seen = set()
            for k in keys:
                if k in seen:
                    continue
                seen.add(k)
                uniq.append(k)
            for section, name in uniq[:10]:
                t = time.perf_counter()
                win._on_result_value_clicked(section, name)
                app.processEvents()
                viewport.grab()
                end = time.perf_counter()
                param_switch.append(end - t)
                switched.append(f"{section}/{name}")
            results["param_switch_ms"] = _stats(param_switch)
            results["param_switch_items"] = switched
            if param_switch:
                print(
                    f"参数卡切换 (n={len(param_switch)})         : "
                    f"中位 {results['param_switch_ms']['median_ms']:.2f} ms  "
                    f"max {results['param_switch_ms']['max_ms']:.2f} ms"
                )
            else:
                print("参数卡切换: 未能枚举到参数项")

        # ---- 6. 光标拖动：按参数项取光标窗口并连续移动 ----
        cursor_moves: list[float] = []
        for section, name in uniq[:3]:
            win._on_result_value_clicked(section, name)
            app.processEvents()
            cur = plot.cursors_t_us()
            if not cur:
                continue
            a, b = float(cur[0]), float(cur[1])
            for k in range(8):
                delta = (b - a) * 0.02 * (k + 1)
                t = time.perf_counter()
                plot.set_global_cursor_window(a + delta, b + delta)
                app.processEvents()
                viewport.grab()
                end = time.perf_counter()
                cursor_moves.append(end - t)
        results["cursor_drag_ms"] = _stats(cursor_moves)
        if cursor_moves:
            print(f"光标拖动 (n={len(cursor_moves)})           : 中位 {results['cursor_drag_ms']['median_ms']:.2f} ms  max {results['cursor_drag_ms']['max_ms']:.2f} ms")

        # ---- 7. 面板重绘：结果表面板单独重绘 ----
        if table is not None:
            tbl = [time.perf_counter()]
            for _ in range(5):
                table.grab()
                tbl.append(time.perf_counter())
            diffs = [tbl[i + 1] - tbl[i] for i in range(len(tbl) - 1)]
            results["result_table_repaint_ms"] = _stats(diffs)
            print(f"结果表面板重绘                 : 中位 {results['result_table_repaint_ms']['median_ms']:.2f} ms")

    finally:
        try:
            win.close()
        except Exception:  # noqa: BLE001
            pass

    out = write_json("bench_gui.json", results)
    print(f"\nraw -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
