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
| Python | 3.13.12 |
| 依赖 | numpy 2.2.6 / scipy 1.18.0 / pandas 3.0.3 / PyQt6 / pyqtgraph 0.14.0 / tm_data_types 0.4.1 |
| **Rust 工具链** | ❌ **本机没有**（`rustc`/`cargo`/`rustup`/`maturin` 均缺失） |
| 无头浏览器（前端原型截图用） | Chrome 或 Edge（本机两者都有） |
| Node.js（原型构建用） | 有（`node`） |

> **Rust 缺失是已知事实，本目录不含任何 Rust 基准数据。**
> 核查脚本：`scripts/check_rust_toolchain.py`，输出 `raw/rust_toolchain.json`。

依赖安装（若在干净环境复现）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# 可选：采样剖析需要 py-spy（有 win_amd64 预编译 wheel，不需要 Rust）
.\.venv\Scripts\python.exe -m pip install py-spy
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

```powershell
# ── 0. 环境核查（Rust 缺失会被如实记录）──
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\check_rust_toolchain.py

# ── 1. 全语料吞吐基线（488 文件，约 10 分钟）──
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\bench_full_corpus.py
#   快速冒烟：--limit 12

# ── 2. 汇总与标度分析（读上一步产出，秒级）──
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\show_corpus_summary.py
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\analyze_scaling.py
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\analyze_distribution.py
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\check_bundle_shape.py

# ── 3. 热点剖析（分层抽样 9 文件 × 4 轮，约 5 分钟）──
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\hotspots.py --n 9 --repeat 4
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\summarize_hotspots.py
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\profile_extract_inner.py

# ── 4. GUI 交互基线（offscreen Qt，约 1 分钟）──
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\bench_gui.py
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\bench_param_switch.py

# ── 5. PoC：热点等价向量化 + 逐值验证 ──
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\poc_crossing_vectorize.py --files 30 --fuzz 4000
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\poc_plateau_vectorize.py --files 40 --fuzz 8000
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\check_plateau_regression.py

# ── 5b. PoC-3：CPU 受限判定 + 多进程并行实测（约 3 分钟）──
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\check_cpu_bound.py
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\poc_parallel_speedup.py

# ── 5c. 差分验收器自验证（应 PASS，再故意篡改应 FAIL）──
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\diff_tester.py `
    capture --limit 12 --out analysis_outputs\arch_evolution_2026-10-15\raw\selftest.json
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\diff_tester.py `
    compare --golden ...\raw\selftest.json --candidate ...\raw\selftest.json

# ── 6. 前端原型：构建 + 截图 ──
node analysis_outputs\arch_evolution_2026-10-15\frontend_prototypes\build.mjs
node analysis_outputs\arch_evolution_2026-10-15\frontend_prototypes\shoot.mjs

# ── 7. 项目自身测试（作为「未破坏生产代码」的旁证）──
#    注意：pytest 默认 temp 根在本机可能权限不足，需用 --basetemp 指到工作区内
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest dpt_extractor/tests -q -p no:cacheprovider `
    --basetemp='E:\Works\DPT-vk-k-mv89ep9q-2\.tmp\pytest-arch'
```

`py-spy` 采样（本议题未依赖其结果，作为可选交叉验证）：

```powershell
.\.venv\Scripts\py-spy.exe record -o analysis_outputs\arch_evolution_2026-10-15\raw\flame.svg `
  --format speedscope -- `
  .\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\pyspy_workload.py --rounds 2
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

> `golden_corpus_100.json` 是**可直接使用的验收基准样例**，随本轮交付一起入库。
> 建议对**全部 488 个文件**各生成一份并随版本归档（约 1.8 MB）。

---

## 6. 数值一致性验收怎么用

```powershell
# 1) 在**现行版本**上生成基准快照（建议对全语料做，随版本归档）
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\diff_tester.py `
    capture --out analysis_outputs\arch_evolution_2026-10-15\raw\golden_corpus.json

# 2) 任何改动/重写后，生成同结构快照再比对
.\.venv\Scripts\python.exe analysis_outputs\arch_evolution_2026-10-15\scripts\diff_tester.py `
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

> **帧率口径提醒**：无头 Chrome 会限频 `requestAnimationFrame`，
> 原型里只显示**同步绘制耗时（ms/帧）**，**不显示 FPS**。
> 真实交互帧率必须在有显示的机器上实测——这是前端决策的未完成验证项。
