# DPT 架构演进选型研究 · 测量脚手架

> 议题 `k-mv89ep9q-2`　·　日期 2026-10-15
> **本目录不修改 `dpt_extractor/` 下任何文件**，全部为只读调用 + 新增测量脚本。

结论文档：**[`DECISION.md`](DECISION.md)**（先读这个）

> 注：本目录刻意**不叫 `docs/`**——仓库根 `.gitignore` 第 6 行有一条**未加锚点**的
> `docs/` 规则，会匹配到任意层级的 `docs/` 目录。若把交付文档放在 `docs/` 下，
> 它会被静默排除在提交之外（本议题第一版就踩了这个坑，已改正）。

---

## 1. 环境要求

| 项 | 本机实测值 |
|---|---|
| 运行解释器 | **系统解释器** `D:\System-XG\Python\python-3.13.12\python.exe`（仓库内**没有** `.venv`） |
| Python | 3.13.12 |
| 依赖 | numpy 2.2.6 / scipy **1.17.1** / pandas **3.0.2** / PyQt6 6.11.0 / pyqtgraph 0.14.0 / openpyxl 3.1.5 / tm_data_types 0.4.1 / numba 0.61.2（`python -m pip list` 实测） |
| **Rust 工具链** | ❌ **本机没有**（`rustc`/`cargo`/`rustup`/`maturin` 均缺失） |
| C 编译器 | ❌ MSVC `cl` 与 `gcc` 均不可用（故本议题也未做 C 扩展 PoC） |
| 无头浏览器（前端原型截图用） | Chrome 或 Edge（本机两者都有） |
| Node.js（原型构建用） | 有（`node` v22.21.1） |
| py-spy（可选采样剖析） | ❌ 未安装（`raw/hotspots.json` 中 `pyspy_available=false`，本轮改用 cProfile） |
| pytest（跑项目自带测试） | ❌ 未安装；仓库测试是 unittest 风格，用 `python -m unittest` 即可（见第 3 节第 7 步） |

> **版本口径纠正**：议题描述里写的是「scipy 1.18 / pandas 3.0」，本机实测为
> **scipy 1.17.1 / pandas 3.0.2**。本目录所有数字都来自上表这台机器。
>
> **运行解释器说明**：下文命令统一用 `python` 代表运行解释器；若你自己建了 venv，
> 换成 `.\.venv\Scripts\python.exe` 即可。**本轮测量没有使用 venv**。
>
> **Rust 缺失是已知事实，本目录不含任何 Rust 基准数据。**
> 核查脚本：`scripts/check_rust_toolchain.py`，输出 `raw/rust_toolchain.json`。

依赖安装（若在干净环境复现；本机已有全部依赖，未执行）：

```powershell
python -m venv .venv
python -m pip install -r requirements.txt
# 可选：采样剖析需要 py-spy（有 win_amd64 预编译 wheel，不需要 Rust）
# 注意：本机未安装 py-spy，本轮全部热点数据来自标准库 cProfile
python -m pip install py-spy
```

---

## 2. 语料位置

脚本默认读取 `E:\Works\DPT\示例文件`（可通过环境变量 `DPT_CORPUS` 覆盖）。

**注意**：`示例文件/` 在 `.gitignore` 里，**不属于仓库**，只在主工作树的本机磁盘上。
在别的机器上复现需自备同名语料目录。

脚本会用 `dpt_extractor.utils.sample_corpus.discover_sample_waveforms`
做真实性嗅探（zip 且含 `.wfm` 成员），避免把非 TSS 文件算进去。

---

## 3. 复现全部测量（推荐顺序）

所有命令都**从仓库根目录**执行。

> **编码提示**：脚本输出含中文，Windows 控制台默认 GBK 会把它们显示成乱码
> （**不影响 `raw/` 下写入的文件**，那些都是 UTF-8）。建议先执行
> `$env:PYTHONIOENCODING='utf-8'` 再跑脚本。

```powershell
# 环境变量（可选但建议）
$env:PYTHONIOENCODING='utf-8'
```

```powershell
# ── 0. 环境核查（Rust 缺失会被如实记录）──
python analysis_outputs\arch_evolution_2026-10-15\scripts\check_rust_toolchain.py

# ── 1. 全语料吞吐基线（488 文件，约 10 分钟）──
python analysis_outputs\arch_evolution_2026-10-15\scripts\bench_full_corpus.py
#   快速冒烟：--limit 12

# ── 2. 汇总与标度分析（读上一步产出，秒级）──
python analysis_outputs\arch_evolution_2026-10-15\scripts\show_corpus_summary.py
python analysis_outputs\arch_evolution_2026-10-15\scripts\analyze_scaling.py
python analysis_outputs\arch_evolution_2026-10-15\scripts\analyze_distribution.py
python analysis_outputs\arch_evolution_2026-10-15\scripts\check_bundle_shape.py

# ── 3. 热点剖析（分层抽样 9 文件 × 4 轮，约 5 分钟）──
python analysis_outputs\arch_evolution_2026-10-15\scripts\hotspots.py --n 9 --repeat 4
python analysis_outputs\arch_evolution_2026-10-15\scripts\summarize_hotspots.py
python analysis_outputs\arch_evolution_2026-10-15\scripts\profile_extract_inner.py

# ── 4. GUI 交互基线（offscreen Qt，约 1 分钟）──
python analysis_outputs\arch_evolution_2026-10-15\scripts\bench_gui.py
python analysis_outputs\arch_evolution_2026-10-15\scripts\bench_param_switch.py

# ── 5. PoC：热点等价向量化 + 逐值验证 ──
python analysis_outputs\arch_evolution_2026-10-15\scripts\poc_crossing_vectorize.py --files 30 --fuzz 4000
python analysis_outputs\arch_evolution_2026-10-15\scripts\poc_plateau_vectorize.py --files 40 --fuzz 8000
python analysis_outputs\arch_evolution_2026-10-15\scripts\check_plateau_regression.py

# ── 5b. PoC-3：CPU 受限判定 + 多进程并行实测（约 3 分钟）──
python analysis_outputs\arch_evolution_2026-10-15\scripts\check_cpu_bound.py
python analysis_outputs\arch_evolution_2026-10-15\scripts\poc_parallel_speedup.py

# ── 5c. 差分验收器自验证（应 PASS，再故意篡改应 FAIL）──
python analysis_outputs\arch_evolution_2026-10-15\scripts\diff_tester.py `
    capture --limit 12 --out analysis_outputs\arch_evolution_2026-10-15\raw\selftest.json
python analysis_outputs\arch_evolution_2026-10-15\scripts\diff_tester.py `
    compare --golden ...\raw\selftest.json --candidate ...\raw\selftest.json

# ── 6. 前端原型：构建 + 截图 ──
node analysis_outputs\arch_evolution_2026-10-15\frontend_prototypes\build.mjs
node analysis_outputs\arch_evolution_2026-10-15\frontend_prototypes\shoot.mjs

# ── 6b. 独立复现核查（第二轮新增；约 2 分钟）──
#     抽样重跑基线 → 汇总对照表；详细结论见 DECISION.md 第八节
python analysis_outputs\arch_evolution_2026-10-15\scripts\replicate_baseline.py --n 24
python analysis_outputs\arch_evolution_2026-10-15\scripts\collect_replication_summary.py
#     代码体量口径（两棵树同口径对照）+ 热点函数是否对现行代码仍成立
python analysis_outputs\arch_evolution_2026-10-15\scripts\count_code_stats.py --compare E:\Works\DPT
python analysis_outputs\arch_evolution_2026-10-15\scripts\check_hotspot_stability.py --other-root E:\Works\DPT --top 20

# ── 7. 项目自身测试（作为「未破坏生产代码」的旁证）──
#    本机**没有安装 pytest**（`python -m pytest` 直接报 "No module named pytest"）。
#    仓库测试是 unittest 风格，可直接用标准库 runner：
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest discover -s dpt_extractor\tests -t . -v
#    第二轮实测（按模块分批跑，避免一次性拉起全部 GUI 用例）：
#      test_app_paths / test_tss_parser / test_channel_mapping / test_bridge_profile /
#      test_single_pulse / test_commutation_inductance / test_extract / test_eoff_window /
#      test_irr_measure / test_short_circuit / test_offset_measurement /
#      test_turn_on_timing_atomic / test_slope_range / test_test_mode /
#      test_wfm_scope_display / test_tss_golden_rt / test_pulse_selection /
#      test_auto_max_slope / test_ground_reference / test_on_didt_8020 /
#      test_peak_plot_align / test_crosstalk_extrema / test_filename / test_label_mapping /
#      test_logical_display_sign / test_recent_paths / test_task_progress_estimator /
#      test_tss_compatibility
#      → 合计 310 个用例，全部 OK（跳过 127 个，多为需要语料或可选依赖）
#    若自行装了 pytest，也可用：
#      python -m pytest dpt_extractor/tests -q --basetemp='.\.tmp\pytest-arch'
```

`py-spy` 采样（**本议题未执行**：本机未安装 py-spy，全部热点数据来自 cProfile。
下面的命令仅作为可选交叉验证的**待执行方案**，需要先 `python -m pip install py-spy`）：

```powershell
py-spy record -o analysis_outputs\arch_evolution_2026-10-15\raw\flame.svg `
  --format speedscope -- `
  python analysis_outputs\arch_evolution_2026-10-15\scripts\pyspy_workload.py --rounds 2
```

---

## 4. 脚本清单

| 脚本 | 作用 |
|---|---|
| `_harness.py` | 共用：语料发现、算路判定、路径解析 |
| `check_rust_toolchain.py` | 只读核查 Rust 工具链（如实记录缺失） |
| `bench_full_corpus.py` | 全语料解析/提取吞吐基线 |
| `show_corpus_summary.py` | 打印上一步汇总（含最慢文件） |
| `analyze_scaling.py` | 耗时 vs 采样点数：线性回归 + 判读 |
| `analyze_distribution.py` | 分组分布形状、短路 vs 双脉冲对比 |
| `check_bundle_shape.py` | 校正 `bundle.n` / `len(t)` 口径 |
| `hotspots.py` | cProfile 热点剖析（分层抽样） |
| `summarize_hotspots.py` | 打印 Top20 与第三方开销来源 |
| `profile_extract_inner.py` | 单次提取内部的成本种类归类 |
| `pyspy_workload.py` | py-spy 采样的目标负载 |
| `bench_gui.py` | GUI 构造/首屏/平移/缩放/参数切换/光标拖动 |
| `bench_param_switch.py` | 参数卡切换的冷/热成本与剖析 |
| `poc_crossing_vectorize.py` | PoC-1：`_nearest_raw_level_crossing_time_us` |
| `poc_plateau_vectorize.py` | PoC-2：`_quiet_plateau_mid`（热点第一名，36%） |
| `check_plateau_regression.py` | PoC-2 曾经失败的退化用例回归检查 |
| `check_cpu_bound.py` | 判定提取是 CPU 受限还是 I/O 受限 |
| `poc_parallel_speedup.py` | PoC-3：多进程并行实测加速比 |
| `diagnose_plateau_mismatch.py` | 诊断 PoC-2 的模糊测试不一致（1 ULP 问题） |
| `diagnose_plateau_step.py` | 上面诊断的逐步对比版本 |
| `diff_tester.py` | **数值一致性差分验收器**（capture / compare） |
| `replicate_baseline.py` | **独立复现核查**：分层抽样重跑，与已入库全语料基线逐文件比对（第二轮新增） |
| `collect_replication_summary.py` | 把「已入库基线」与「独立复跑」产物拼成对照表（第二轮新增） |
| `count_code_stats.py` | **代码体量统计**（可 `--compare` 同时统计两棵树，避免版本混算；第二轮新增） |
| `check_hotspot_stability.py` | **热点函数一致性核查**：Top20 热点在另一棵树里是否逐字符相同（第二轮新增） |

---

## 5. 输出数据清单（`raw/`）

| 文件 | 内容 |
|---|---|
| `rust_toolchain.json` | Rust/链接器探测器结果 |
| `bench_full_corpus.json` | 488 文件逐文件原始耗时（+ `.log`） |
| `hotspots.json` | cProfile 热点全表（+ `.log`） |
| `profile_extract_inner.json` | 提取内部成本构成（+ `.log`） |
| `bench_gui.json` | GUI 交互基线（+ `.log`） |
| `bench_param_switch.json` | 参数卡切换冷/热成本（+ `.log`） |
| `bundle_shape_check.json` | 采样点数口径核查 |
| `cpu_bound_check.json` | CPU/墙钟比值（判定是否 CPU 受限） |
| `poc_crossing_vectorize.json` | PoC-1 一致性 + 加速比（+ `.log`） |
| `poc_plateau_vectorize.json` | PoC-2 一致性 + 加速比（+ `.log`） |
| `poc_parallel_speedup.json` | PoC-3 并行实测加速比（+ `.log`） |
| `golden_corpus_100.json` | **数值基准快照样例**（前 100 个文件，96 ok / 4 failed，361.8 KB） |
| `diff_report.json` | 差分验收报告（最近一次运行） |
| `verify_replication_summary.json` | **独立复现核查对照表**（第二轮） |
| `verify_baseline_replication.json` | 抽样 24 文件重跑 vs 全语料基线的逐文件比值 |
| `verify_poc_plateau_replication.json` | PoC-2 复跑（16 次调用按位一致，60.9×） |
| `verify_poc_crossing_replication.json` | PoC-1 复跑（14 次调用按位一致，70.3×） |
| `verify_hotspots_replication.json` | 热点复跑（3 文件 × 2 轮，集合一致） |
| `verify_bench_gui_replication.json` | GUI 交互复跑 |
| `verify_bench_param_switch_replication.json` | 参数卡切换复跑 |
| `verify_diff_report_pass.json` / `verify_diff_report_tamper_fail.json` | 差分验收器自验证的两个方向（PASS / FAIL） |
| `code_stats.json` | **代码体量**：本分支检出 vs 主工作树（同一脚本、同一口径） |
| `verify_hotspot_stability.json` | **热点函数一致性**：Top20 在主工作树上是否逐字符相同（19/20 相同） |

> `golden_corpus_100.json` 是**可直接使用的验收基准样例**，随本轮交付一起入库。
> 建议对**全部 488 个文件**各生成一份并随版本归档（约 1.8 MB）。

---

## 6. 数值一致性验收怎么用

```powershell
# 1) 在**现行版本**上生成基准快照（建议对全语料做，随版本归档）
python analysis_outputs\arch_evolution_2026-10-15\scripts\diff_tester.py `
    capture --out analysis_outputs\arch_evolution_2026-10-15\raw\golden_corpus.json

# 2) 任何改动/重写后，生成同结构快照再比对
python analysis_outputs\arch_evolution_2026-10-15\scripts\diff_tester.py `
    compare --golden ...\raw\golden_corpus.json --candidate ...\raw\candidate_corpus.json
```

- **默认要求位级一致**（浮点按 `repr()` 往返表示逐字符比较）。
- 只有显式传 `--rel-tol` 才会放宽为相对误差；**放宽必须由人签字并写进 PR**。
- 退出码：`PASS` → 0，`FAIL` → 1，便于接进 CI。

工具自验证记录（含反向对照）见 [`DECISION.md`](DECISION.md) 第 4.1 节。

---

## 7. 前端原型

| 文件 | 说明 |
|---|---|
| `frontend_prototypes/data.mjs` | **共用数据层**（波形生成、vdiv 换算、包络降采样、参数表） |
| `frontend_prototypes/*.tpl.html` | 三个原型模板（含 `<!--INLINE_DATA-->` 占位符） |
| `frontend_prototypes/build.mjs` | 把数据层内联进模板 → 自包含单文件 HTML |
| `frontend_prototypes/shoot.mjs` | 用本机 Chrome 无头模式截图 |
| `frontend_prototypes/proto_*.html` | **构建产物**（生成物，勿手改） |
| `frontend_prototypes/shots/*.png` | 截图证据 |
| `frontend_prototypes/index.html` | 三个原型并排对照页 |

三个原型画的是**同一条波形、同一份参数值**，差异只来自技术栈与视觉语言，
因此可以横向比较审美上限与实现成本。

> **数据性质声明**：原型里的波形与参数值都是 `data.mjs` **生成的演示数据**，
> **不是**对真实 `.tss` 的提取结果。原型比较的是技术栈与视觉语言，不是测量口径。
>
> **构建可复现**：`node build.mjs` 重跑后三个 `proto_*.html` 的 sha256 逐字节不变；
> 三个 HTML 均不含任何外部 URL / CDN 引用，可离线打开。

> **帧率口径提醒**：无头 Chrome 会限频 `requestAnimationFrame`，
> 原型里只显示**同步绘制耗时（ms/帧）**，**不显示 FPS**。
> 真实交互帧率必须在有显示的机器上实测——这是前端决策的未完成验证项。
