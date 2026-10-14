# DPT 架构演进选型与可行性研究

> 议题：`k-mv89ep9q-2`　·　类型：**研究/选型（不重写生产代码）**
> 测量日期：2026-10-15　·　测量机：Windows / Python 3.13.12（系统解释器，无 venv）
> 语料：`E:\Works\DPT\示例文件` 下 **488 个真实 `.tss`**（共 652.3 MB）

---

## 一页结论

### 一句话推荐

> **不做 Rust 重写。先做「Python 热点向量化」，前端继续 PyQt6 但先还债再精致化。**

理由不是「Rust 不好」，而是**本议题的性能瓶颈实测根本不在 Rust 能解决的维度上**（见第三节证据）：
耗时集中在 **620 万次 numpy 小数组分派**上，而分派开销无论用哪种语言重写都要付；
真正的杠杆是**消除分派次数**（向量化），实测收益 **60× 量级**——比换语言或加进程高一个数量级。

### 推荐路线（按实测收益排序）

| 阶段 | 内容 | 实测预期收益 | 风险 | 是否引入新依赖 |
|---|---|---|---|---|
| **P0 还债**（1–2 周） | 拆 `gui/main_window.py`（主工作树 521 KB / 13 017 行；测量检出 11 368 行）与 `gui/waveform_plot.py`（412.7 KB / 10 389 行） | 解锁后续一切改动 | 低（纯搬迁） | 否 |
| **P1 热点向量化**（1–2 周） | 向量化 `plateau_level.py` / `iec_windows.py` / `pulse_detector.py` 与 GUI 光标投影中的 Python 元素循环 | **单函数 59–62×**（已实测，见第四节），参数提取整体预计下降一个数量级 | 低（逐值可位级验证） | 否 |
| **P2 批处理并行**（按需，2–3 周） | 批次级多进程，按文件并行 | **约 3.5×**（已实测；4 进程以上效率急剧衰减，见 PoC-3） | 中（进程模型、numba 缓存、内存带宽饱和） | 否 |
| **P3 前端精致化** | 在 PyQt6 内做视觉与交互打磨 | 取决于有显示环境实测 | 中 | 否 |
| **P4 选择性 Rust 内核** | **仅在 P1 之后仍有向量化解决不了的纯数值热点时**考虑 | 未实测（本机无工具链） | 高 | 是 |

> **P2 的预期已被实测下调**：最初按 CPU/墙钟 = 0.977 推测接近线性扩展，实测只有约 3.5×。
> 因此**不要把并行当作主要收益来源**，它是 P1 之后的补充手段。

**Rust 的适用位置**（若 P0–P2 之后仍需更快）：只对**已向量化后仍占主导**的纯数值核做 PyO3 替换，且必须通过差分验收。**不建议**独立 Rust 进程或全栈 Rust。

### 被否路线与否决理由

| 路线 | 否决理由（基于实测，不是偏好） |
|---|---|
| **B. Rust 独立进程 + IPC/Arrow** | 单文件端到端中，**提取占 92%、加载占 7.6%**；热点是**解释器分派开销**。搬进 Rust 进程能让这部分开销「消失」，但**同样的收益用 P1 向量化即可拿到（实测 60× 量级）且无进程复杂度**。实测多进程并行也只有约 3.5×（见 PoC-3），远低于理论值——说明该场景对内存带宽敏感，不是加进程/换语言能解决的。**否决，不进入 P4。** |
| **C. 全栈 Rust** | 成本集中在三块而非计算：GUI **27 836 行**、仪器桥（PowerShell 24.7 KB + C# 10.4 KB + TekVISA FFI）、Excel 报表保真（模板含 3 个 externalLink、51.8 KB styles.xml、854 KB 大表）。这三块**没有一行**能靠 Rust 提速，却要整体重建。**否决。** |
| **前端 B. Tauri + Web 前端** | 审美上限确实最高（原型 B 实测 WebGL 绘制 0.27 ms/帧），但要付出：重写 **27 836 行** GUI 交互、自研降采样/WebGL、WebView2 运行时依赖与打包改造、中文排版与高分屏重新验证。**在 P0 还债之前不具备可执行性**；建议 **P0 完成后**用真实波形做 WebGL 帧率与光标手感实测再决策。 |
| **前端 D. Qt + Rust 绑定** | 复杂度最高（两套运行时），而 Qt 侧的性能问题（见第四节：`QWidget.grab()` 整窗重绘 101.9 ms）**并不会因语言改变而消失**。**否决。** |
| **前端 C. egui / iced** | 原型 C 显示其审美上限明显低于 A/B（即时模式的无圆角单色外观），中文排版与高分屏适配需另行验证。**当前否决**，保留为「极端追求单栈/单 exe」时的备选。 |

### 明确「不改」的边界（红线）

- **参数数值计算口径一律不改**：提取、测量、积分、斜率、时间窗、平台线、损耗窗口、Trr/Err、光标落点。
- `docs/` 下全部规范（`MEASUREMENT_SPEC.md`、`WAVEFORM_UI_SPEC.md`、`DOUBLE_PULSE_SPEC.md`、`TEKTRONIX_MEASUREMENT_DEFINITIONS.md`、`REGRESSION_BASELINES.md` 等）**不动**。
- 本议题**未修改 `dpt_extractor/` 下任何文件**（可核验：分支 diff 只含 `analysis_outputs/`）。
- 任何后续优化若触及数值，必须先过第四节定义的差分验收。

---

## 二、对议题既有事实的复核（有错必纠）

议题描述里的实测数据**基本准确**（模块级行数逐字吻合，见纠正 2）。
复核后需要做 **1 处实质纠正 + 1 处口径澄清**，两者都直接影响路线判断：

### 纠正 1：`.tss` 解析**不是**自研，最内层是第三方纯 Python 库

议题称：

> `.tss` 解析：**自研**（`io/tss_parser.py` 30KB，zip + numpy），不依赖第三方解析库 → Rust 侧可自研等价实现，属可控项

实测：

```
dpt_extractor/io/tss_parser.py:57    from tm_data_types import read_file as _read_file
dpt_extractor/io/wfm_scope_display.py:109-112  from tm_data_types.files_and_formats.wfm.wfm import WFMFile ...
```

- `tm_data_types` **0.4.1** 已安装在 venv 中，是 `.tss` 内层 `.wfm` 的实际解析器。
- 该库 **38 个 `.py`、0 个 `.pyd`/`.so`**，即**纯 Python + numba**（`wfm_format.py:110 @njit(cache=True)`）。
- `dpt_extractor/io/tss_parser.py` 做的是**外层 zip 容器 + 会话 setup + MATH 公式求值**，内层波形解码依赖第三方。

**影响**：Rust 若要自研等价实现，不止要写 zip + setup 解析，还要**完整复刻 `tm_data_types` 的 WFM 编解码语义**（字节序、版本号、缩放、单位、`String8` 等）。这把「可控项」变成**中等风险项**，也意味着即使转 Rust，**仍要对该第三方解析结果做逐值对齐**。

### 纠正 2：代码体量——议题数字**基本准确**，但必须先说清「哪棵树」

第一轮报告曾把议题的体量数字判为「偏高 8–10%」。**第二轮复核推翻了那个结论**：
成因是**两棵树混算**——议题的数字对应**主工作树 `E:\Works\DPT`（带未提交改动）**，
而第一轮的统计口径落在**本分支检出的干净树（`937dc8ad`）**上。

第二轮用同一个脚本（[`scripts/count_code_stats.py`](scripts/count_code_stats.py)，
产出 [`raw/code_stats.json`](raw/code_stats.json)）把两棵树按同一口径各测一遍：

| 项 | 议题描述 | **主工作树（现行，含未提交改动）** | 本议题测量所用检出（`937dc8ad`） |
|---|---|---|---|
| 产品代码 | 约 55 000 行 | **55 056 行**（62 文件）✅ 吻合 | 50 025 行（60 文件） |
| gui 模块 | 27 836 行 / 10 文件 | **27 836 行 / 10 文件** ✅ 逐字吻合 | 25 858 行 / 10 文件 |
| metrics | 13 992 行 | **13 992 行** ✅ 逐字吻合 | 11 587 行 |
| export / io / pipeline | 5 146 / 2 869 / 2 367 | **5 146 / 2 869 / 2 367** ✅ 逐字吻合 | 5 103 / 2 512 / 2 185 |
| models / utils / detect / config / cli | 1 445 / 749 / 385 / 136 / 74 | **1 445 / 749 / 385 / 136 / 74** ✅ 逐字吻合 | 1 419 / 716 / 385 / 136 / 74 |
| `gui/main_window.py` | 533 KB | **521.0 KB / 13 017 行**（略低于议题值） | 455.7 KB / 11 368 行 |
| `gui/waveform_plot.py` | 422 KB | **412.7 KB / 10 389 行** | 403.8 KB / 10 067 行 |
| 测试文件数 / 行数 | 73 个 / 41 596 行 | **81 个 / 43 727 行**（比议题略多） | 61 个 / 34 557 行 |
| `.tss` 样例数 | 488 个 | 488 个 ✅ | 488 个 ✅ |

**结论修正**：

1. 议题给出的模块级行数与主工作树**逐字吻合**，不需要「纠偏」——**该数字是可信的**。
2. 真正需要声明的是**版本口径**：本议题的**全部测量与 PoC 都在 `937dc8ad` 上完成**，
   而主工作树当时带着 **34 个文件的未提交改动（+12 987 / −1 253 行）**。
3. 因此**搬运成本应按主工作树的体量估**（产品 55 056 行、GUI 27 836 行），
   而不是按测量时所处检出估——两者差约 10%。
4. 好消息是**这不影响热点名单**：第二轮做了逐函数比对
   （[`scripts/check_hotspot_stability.py`](scripts/check_hotspot_stability.py)，
   产出 [`raw/verify_hotspot_stability.json`](raw/verify_hotspot_stability.json)），
   **Top20 里有 19 个函数在主工作树与测量检出上逐字符相同**，
   唯一不同的是 `iec_windows.py:_legacy_err_recovery_settled_base`（占 0.60%）。
   即：热点结论对现行代码**依然成立**。

> 行号口径：3.3 节与 4.2 节引用的 `文件:行` 均以 **`937dc8ad`** 为准。
> 主工作树因为多了约 5 000 行代码，部分文件的后续行号会整体下移。

### 确认正确的事实（实测复核通过）

- ✅ 运行时：Python 3.13.12（系统解释器 `D:\System-XG\Python\python-3.13.12\python.exe`）+ PyQt6 6.11.0 + pyqtgraph 0.14.0；numpy 2.2.6 / **scipy 1.17.1** / **pandas 3.0.2**；openpyxl 3.1.5 出报表。
  （议题描述中的「scipy 1.18 / pandas 3.0」与本机实测的 **1.17.1 / 3.0.2** 有细微出入，以本机 `pip list` 实测为准。）
- ✅ 打包：`DPT.spec` 单文件 Windows GUI，随包带 `config/default.yaml`、`io/tek_scope_bridge.ps1`、`io/tekvisa_native.cs`、`默认报告模板.xlsx`、`assets/noncommercial_authorization_poster.png`。
- ✅ 仪器桥：`tek_scope_bridge.ps1` + `tekvisa_native.cs` 走 TekVISA，属高风险项。
- ✅ **本机没有 Rust 工具链**：`rustc`/`cargo`/`rustup`/`maturin` 均不在 PATH，`~/.cargo` 与 `~/.rustup` 目录不存在；MSVC `cl` 与 `gcc` 也不可用。→ 详见 `raw/rust_toolchain.json` 与第五节。

### 补充发现：`docs/` 是 gitignore 的

`.gitignore` 第 6 行忽略 `docs/`。仓库里**没有** `docs/` 的版本记录（`git ls-files docs` 为空）。
这意味着 `MEASUREMENT_SPEC.md`、`REGRESSION_BASELINES.md` 等规范**只存在于主工作树的本地磁盘上**。

**影响**：任何在 worktree/CI/新机器上做的重写与验收，都**拿不到这些规范**。
若要做跨机器或跨人的重写验收，**第一步必须先把 `docs/` 纳入版本控制**（或建立受控的规范副本），否则「口径一致」无从校验。**这是一条当前被忽略的阻塞项。**

---

## 三、性能基线（可复现）

所有原始数据与脚本在 `analysis_outputs/arch_evolution_2026-10-15/`。
复现命令见同目录 `README.md`。

### 3.1 解析与提取吞吐（488 个真实 `.tss`）

**全量实测（484 成功 + 4 失败），原始数据 `raw/bench_full_corpus.json`：**

| 指标 | 实测值 |
|---|---|
| 语料 | 488 个文件，**652.3 MB**（成功处理 649.95 MB） |
| 处理成功 | **484 / 488** |
| 端到端总耗时 | **581.68 s**（约 9.7 分钟） |
| **吞吐** | **0.832 文件/秒 · 1.117 MB/秒** |
| 单文件端到端 | 均值 1.202 s，中位 1.275 s，P95 2.127 s，最大 9.512 s |
| `load_waveform`（含第三方 `.wfm` 解析） | 合计 44.08 s → **7.6%**，中位 0.0735 s |
| 通道映射推断 | 合计 2.46 s → **0.4%**，中位 0.005 s |
| **参数提取 `extract_all`** | 合计 **535.13 s → 92.0%**，中位 1.174 s |

**提取占端到端 92%。解析不是瓶颈（7.6%），通道映射不是瓶颈（0.4%）。**

**4 个失败文件**均为 `extract:KeyError: Total current channel is not available in bundle`，
全部来自 `likangkang\NED34jixian\{short,uh}\{750v,915v}-{vh,uh}-short-25c_000.tss`。

**根因（第二轮复核后修正，见第八节）**：这 4 个文件被脚手架**正确地**路由到了
`extract_short_circuit`（记录的 `short_circuit=true` 与目录约定一致），失败发生在提取内部——
它们的 `.tss` 自身标注了 `CH3=IUH`（总电流），但波形负载只带了 CH1/CH2/CH4/CH5/CH6，
**CH3 的波形数据在文件里就不存在**，于是 `models/waveform.py:159 bundle_total_current()`
抛 `KeyError`。

即：**不是「短路样例被按双脉冲算路提取」，而是「样例文件自身缺少其标注声明的 CH3 通道数据」**。
脚手架里没有用户可以手动改映射，所以直接失败；这 4 个文件（0.8%）不影响任何吞吐结论，
但**是否属于生产缺陷需另议**（GUI 里用户可自行调整通道映射或换用其它可用通道）。

**首个文件明显更慢**（冷启动 0.368 s，含 numba 缓存校验与惰性导入），后续稳定。
这与 `utils/app_paths.py::configure_numba_cache_dir` 的存在相互印证——该函数注释本身
就在处理 numba 在 Windows 上的缓存探测停顿问题。

### 3.2 全语料结论：**瓶颈由「算路」决定，不由「数据量」决定**

这是本次测量最有价值的发现，它直接改写了优化目标。

| 分类（全语料 484 个成功文件） | 文件数 | 提取中位耗时 | 均值 | 最大 |
|---|---|---|---|---|
| **短路工况** | 69 | **0.068 s** | 0.077 s | 0.226 s |
| **双脉冲工况** | 415 | **1.269 s** | 1.277 s | 9.406 s |

**双脉冲比短路慢 18.8×**，且双脉冲贡献了 535 s 总提取耗时中的约 89%。

进一步验证：把「提取耗时」对「采样点数」做一元线性回归，得到

```
t ≈ 1052.69 ms + 86.16 ns × n        R² = 0.0116
```

**R² ≈ 0.01 意味着：耗时与采样点数几乎无关。** 佐证：

- 62 500 点 / 48 个文件 → 中位 **0.371 s**（5 943 ns/点）
- 125 000 点 / 99 个文件 → 中位 **0.086 s**（686 ns/点）
- 5 000 000 点 / 38 个文件 → 中位 **1.269 s**（254 ns/点）

**采样点数多 80 倍的文件，反而比采样点数少的文件更快。** 单位采样点成本跨度 P90/P10 = 13.7×。

> 口径校正（已实测核实，见 `raw/bundle_shape_check.json`）：某文件报 `n_samples = 5 000 000`
> 是**真实值**，语料的采样点数确实横跨 62 500 → 5 000 000；`bundle.n` 与 `len(bundle.t)`
> 在所有抽检文件上都相等。因此上表的数字不是口径错误。

**这条结论的实践含义**：

1. 优化目标应该锁定**双脉冲算路**（415 个文件、89% 耗时），短路算路几乎不值得动。
2. 「换语言」在这里没有结构性优势——耗时不在浮点运算量上，而在**算路里被反复调用的热函数**上。
3. 具体地，双脉冲路径反复调用 3.3 节那几个 O(n²)/逐元素循环函数，**它们才是真正的杠杆点**。

### 3.3 热点 Top 20（本项目代码，按自身耗时）

抽样策略：488 个语料按体积三分层各取 3 个 → 9 个文件 × 4 轮 = 36 次提取。
方法：标准库 `cProfile`（确定性插桩）。完整表见 `raw/hotspots.json`。

> **抽样敏感性（第二轮复跑补充）**：用更小的样本（3 文件 × 2 轮，
> `raw/verify_hotspots_replication.json`）复跑时，前列**集合完全一致**，
> 但内部排序有波动——`detect_all` 升到第 1（34.9%）、`_quiet_plateau_mid` 降到第 2（14.3%）。
> 结论：**Top20 名单是稳定的，但排序会随样本变化**；P1 的施工顺序应以「函数集合 + 大样本排序」
> 为准，不要拿单次小样本的百分比起步。

| # | 位置 | 函数 | 占本项目代码 |
|---|---|---|---|
| 1 | `metrics/plateau_level.py:10` | `_quiet_plateau_mid` | **35.86%** |
| 2 | `detect/pulse_detector.py:42` | `detect_all` | **19.57%** |
| 3 | `metrics/iec_windows.py:437` | `_local_extrema_indices` | **10.05%** |
| 4 | `metrics/commutation_inductance.py:27` | `_finite_series` | 6.89% |
| 5 | `metrics/iec_windows.py:814` | `_first_sustained_rise_crossing` | 3.01% |
| 6 | `io/tss_parser.py:197` | `_parse_tss_math_setup` | 2.07% |
| 7 | `metrics/iec_windows.py:355` | `_crossing_pair_indices` | 1.71% |
| 8 | `metrics/plateau_level.py:57` | `_plateau_mid_without_isolated_spikes` | 1.49% |
| 9 | `io/tss_parser.py:425` | `_eval` | 1.14% |
| 10 | `metrics/iec_windows.py:4057` | `integrate_err_recovery` | 0.89% |
| 11 | `detect/pulse_detector.py:177` | `_refine_pulse_off` | 0.82% |
| 12 | `io/tss_parser.py:119` | `_sample_interval_from_time` | 0.78% |
| 13 | `metrics/plateau_level.py:634` | `_turn_on_rise_index` | 0.76% |
| 14 | `metrics/rr_tail.py:6` | `reverse_recovery_tail_end_index` | 0.74% |
| 15 | `metrics/commutation_inductance.py:61` | `_window_series` | 0.73% |
| 16 | `metrics/iec_windows.py:1464` | `_main_edge_level_crossing` | 0.64% |
| 17 | `metrics/iec_windows.py:2506` | `_legacy_err_recovery_settled_base` | 0.60% |
| 18 | `models/waveform.py:182` | `_finite_percentiles` | 0.59% |
| 19 | `io/tss_parser.py:148` | `_strip_setup_value` | 0.48% |
| 20 | `utils/timing_adapt.py:180` | `scope_turn_on_bases` | 0.47% |

**集中度：Top3 = 65.5%，Top5 = 75.4%，Top10 = 82.7%。**
即：**十个函数决定了八成以上的提取耗时**，而它们全都是本项目 Python 代码。

### 3.4 关键证据：热点是「解释器分派开销」，不是「数值算力」

全局剖析显示第三方耗时高度集中在 numpy 的**小数组归约分派**上：

| 函数 | 自身耗时 | **调用次数** |
|---|---|---|
| `numpy.ufunc.reduce` | 8.14 s | **6 218 160** |
| `numpy._methods._mean` | 3.30 s | **1 641 208** |
| `numpy._core.fromnumeric._wrapreduction` | 2.84 s | **3 362 316** |
| `numpy._methods._count_reduce_items` | 1.99 s | **1 641 208** |
| `numpy.ndarray.partition` | 1.68 s | 418 560 |

**单次插桩运行（32 次提取）发生 621 万次 `ufunc.reduce`。** 这些调用的源头就是热点 1 的三重循环：

```python
# dpt_extractor/metrics/plateau_level.py:27-41
for wlen in range(wlen_lo, wlen_hi + 1):        # 13 个窗长
    for w0 in range(nwin):                      # 约 90 个起点
        if float(np.max(diffs[w0 : w0 + wlen - 1])) > dy_lim:   # numpy 分派
            continue
        sub = band[w0 : w0 + wlen]
        mu = float(np.mean(sub))                # numpy 分派
        s = float(np.max(sub) - np.min(sub))    # 两次 numpy 分派
```

每次 `np.max`/`np.mean` 对 10–21 个元素的数组，**固定分派开销（约 1 µs）远大于实际计算**。
源码第 6 行注释「避免对整段波形 O(n²) 滑动窗」说明作者已知此处是 O(n²)，只是用短窗压住了量级。

**这个结论直接决定路线选择**：
把这段 computation 搬进 Rust，`np.max` 的分派开销确实会消失——但**用 NumPy 向量化把它消除，效果相同、风险更低、不引入新运行时**。Rust 在这里相对「向量化」没有结构性优势。

### 3.5 提取内部成本构成（单文件，已预热排除 numba 编译）

见 `raw/profile_extract_inner.json`。按「成本种类」归类，单次 `extract_all` 的项目内热点前五与 3.2 一致，且确认 **Python 侧（项目自身字节码）占项目内耗时的主要部分**，numpy 算术 ufunc 占比极低——**再次说明瓶颈是循环与分派，不是浮点运算量**。

### 3.6 GUI 交互成本（无显示环境，offscreen Qt）

**口径限制（必须如实说明）**：本机无显示环境，只能 `QT_QPA_PLATFORM=offscreen`。
因此能测的是**真实 Qt 控件构造、真实数据装载、真实视图变换、真实重绘 CPU 成本**；
**不能**测 GPU 合成后的真实帧率。下表的「重绘」是 `QWidget.grab()` 强制同步渲染的 CPU 时间，**不等于 FPS**，报告不做换算。

样本：`示例文件/songzhenxi/.../WL_750V_805A_000.tss`（1425.4 KB）。原始数据 `raw/bench_gui.json`。

| 指标 | 中位 | 最大 |
|---|---|---|
| `MainWindow()` 构造 | 112.2 ms | — |
| **首屏**（`_load_file` + 事件循环） | **2645 ms** | — |
| 整窗一次重绘 | 101.9 ms | — |
| 平移：视图变换 | 14.3 ms | 23.2 ms |
| 平移：单次重绘 | 47.7 ms | 53.0 ms |
| 缩放：视图变换 | 12.3 ms | 22.0 ms |
| 缩放：单次重绘 | 43.7 ms | 57.9 ms |
| **参数卡切换** | **59.8 ms** | **816.3 ms** |
| 光标拖动 | 9.7 ms | 37.4 ms |
| 结果表面板重绘 | 5.1 ms | 5.3 ms |

> **复跑对照（第二轮，`raw/verify_bench_gui_replication.json`）**：各指标的**量级与方向完全一致**，
> 复跑整体快 15–30%（当时机器更空闲）：构造 112.5 ms、首屏 1823 ms、整窗重绘 79.1 ms、
> 平移重绘 38.2 ms、缩放重绘 39.0 ms、参数卡切换中位 55.8 ms / 最大 639.6 ms、光标拖动 8.7 ms。
> **口径提醒**：本表只可用于**相对比较**（哪一项贵、差几倍），绝对值有 ±30% 的运行间波动，
> 不要把它当 SLA 数字引用。

### 3.7 参数卡切换的尖峰：848 ms 定位到单个 Python 标量循环

`raw/bench_param_switch.json`：32 个参数项逐个切换，**首个 477 ms、最慢项 848 ms（`di/dt`）、其余中位 59 ms**。

对首次切换做剖析，热点确认为：

```
gui/main_window.py:379  _nearest_raw_level_crossing_time_us   190.26 ms（自身）
gui/main_window.py:415  <lambda>                               6.82 ms  调用 21 818 次
```

该函数用一个**纯 Python 逐元素 for 循环**扫描 21 818 个采样点：

```python
for k in range(lo, hi):
    y0, y1 = float(yy[k]), float(yy[k + 1])
    ...
    candidates.append(float(tt[k] + frac * (tt[k + 1] - tt[k])))
if not candidates:
    return None
return float(min(candidates, key=lambda value: abs(value - ref_t))) * 1e6
```

21 818 次 `float()` 装箱 + 21 818 次 lambda 调用 ≈ 190 ms。
**这是用户能直接感知的卡顿点（最慢项 848 ms），且与 Rust 无关，向量化即可解决。**

> **测量过程中的一次自我纠错（记录在案）**：PoC-1 最初打算从 headless 的
> `extract_all` 路径抓取该函数的调用参数，结果**抓到 0 次调用**。
> 复查后确认：该函数**不在**参数提取路径上，只在 **GUI 参数卡点击**时才被调用
> （把检测/平均电平投影回最近的真实波形过零点）。因此 PoC-1 改为驱动真实的
> offscreen Qt 窗口重放点击回调——这才是用户可感知的那条路径。
> 这个纠错本身有价值：它说明**「同一个热点」可能挂在完全不同的调用路径上，
> 优化前必须先确认调用来源**。

### 3.8 前端方案的可比较原型（3 个，含实测绘制成本）

三个原型**共用同一份数据层**（`prototypes/data.mjs`）：同一波形生成、同一 vdiv/yPosition 换算、
同一 min/max 包络降采样、同一参数表数值。因此视觉与成本差异**只来自技术栈**。

构建：`node prototypes/build.mjs`　截图：`node prototypes/shoot.mjs`（用本机 Chrome 无头模式，未新增 npm 依赖）

| 原型 | 视觉语言 | 同步绘制成本（两次独立渲染） | 审美上限判断 |
|---|---|---|---|
| **A. PyQt6 精致化** | 桌面仪器风：近直角、细描边、高信息密度、克制动效 | 0.40 / 0.45 ms/帧 · Canvas2D | 中。**零迁移风险**，但圆角/阴影/动效天花板低 |
| **B. Tauri + Web（WebGL）** | 现代设计系统：玻璃拟态、渐变层次、大留白、呼吸动效 | **0.27 / 0.23 ms/帧 · WebGL** | **最高**。代价是 WebView 依赖 + **27 836 行** GUI 重写 |
| **C. egui / iced 原生** | 即时模式：小圆角、单色面板、文字按钮、几乎无阴影 | 0.10 / 0.10 ms/帧 · 光栅化 | 低。单栈/单 exe 最干净，但外观明显朴素 |

截图见 `frontend_prototypes/shots/`。可直接在浏览器打开三个 `.html` 做交互对比。

> **原型的数值是合成演示数据**：`frontend_prototypes/data.mjs` 生成同一条演示波形与同一组
> 演示参数值（三个原型共用），**不是**对真实 `.tss` 的提取结果。原型要比较的是
> **技术栈与视觉语言的差异**，不是测量结果；三个原型显示的参数值逐项相同（ΔVce 402.6、
> Toff 1.8013、Eoff 148.72 …），因此横向对比是公平的。

> **构建可复现（第二轮实测）**：`node build.mjs` 重跑后三个 `proto_*.html` 的 sha256
> **逐字节不变**；`node shoot.mjs` 重跑 3/3 成功，其中原型 C 的截图与上一轮**逐字节相同**，
> A/B 因动效时序差异有极轻微像素变化。三个原型 HTML 均不含任何外部 URL / CDN 引用，
> 可离线打开。

> **诚实声明**：表中「绘制成本」是在无头 Chrome 中测的**同步绘制耗时**，不是用户体验帧率；
> 无头模式会限频 `requestAnimationFrame`，因此原型内**不显示 FPS 数字**（第一版曾显示，已移除以免误导）。
> 真实帧率必须在有显示的机器上用实际波形实测，这是前端决策的**未完成验证项**。

---

## 四、数值一致性方案（硬红线）与 PoC

### 4.1 差分验收：把「逐参数一致」变成可执行判据

工具：`scripts/diff_tester.py`（本议题新增，位于 `analysis_outputs/` 内，**不污染生产目录**）

```
# 1) 用现行 Python 实现生成基准快照
python scripts/diff_tester.py capture --out raw/golden_corpus.json

# 2) 与候选实现（Rust 内核 / 新版本 / 任何重写）比对
python scripts/diff_tester.py compare --golden raw/golden_corpus.json --candidate raw/candidate.json
```

**覆盖的测量面**（对每个语料文件）：

- 分段索引 `segments`（`turn_off` / `turn_on` / `reverse_recovery` / `next_pulse_on`）
- 脉冲识别：`detected_pulse_count`、`off_pulse_index`、`on_pulse_index`、`single_pulse_mode`、`short_circuit_mode`
- 四组结果数据类**全部数值字段**：`turn_off`(19) / `turn_on` / `reverse_recovery` / `short_circuit`
- `vdc`、`idc`、`vdc_set`、`idc_set`、`profile_name`、`profile_code`、`phase`
- `unavailable_metrics`（缺失通道导致的隐藏参数集合）

**分级容差**：

| 级别 | 对象 | 要求 |
|---|---|---|
| **T0** | 整数、字符串、布尔、分段索引、集合 | **位级**，必须 `==`，**不设容差**。索引错一位即窗口错位 |
| **T1（默认）** | 浮点值 | **位级一致**。浮点以 `repr()` 往返表示，逐字符相等 ≡ `float == float` |
| **T2（需显式开启）** | 浮点值 | 仅在传 `--rel-tol` 时放宽为相对误差。**默认关闭** |

**为什么默认不放宽**：同一算法、同一运算顺序在同一平台上可以做到按位一致。
放宽容差等于**接受算法漂移**，必须由人显式签字，不能是默认行为。

**容差来源说明**：`docs/REGRESSION_BASELINES.md` 记录的是样例级目标值与审计通过数，
**没有为「重写 vs 现行」定义浮点容差**。因此本工具把位级一致定为默认。

**工具自验证（含反向对照）**：

| 用例 | 结果 |
|---|---|
| 基准 vs 自身副本 | `PASS`，8/8 文件逐参数一致，0 字段差异 ✅ |
| 基准 vs 篡改候选（分段索引 +1、`eoff` +1e-9） | `FAIL`，检出 1-LSB 索引偏移与 1e-9 能量漂移 ✅ |

**已知局限（如实记录）**：该用例中 `toff + 1e-15` 的篡改**未被检出**——因为
`repr(0.001 + 1e-15) == repr(0.001)`，差异低于 float64 在该量级上的分辨率。
即：本工具的灵敏度下限是 **float64 的 ULP**，更小的差异在浮点表示层面不存在。
若未来需要亚 ULP 比对，需记录原始二进制位（如 IEEE754 十六进制），属可选增强。

### 4.2 PoC：三个热点函数的等价向量化（本机可执行，不需 Rust）

Rust 工具链缺失（见第五节），因此 PoC 选择**不依赖 Rust 也能验证核心假设**的路径：
把「Rust 会更快」的假设替换为**可实测的同口径向量化**。

两者均：
- **不修改生产代码**（脚本内断言生产文件 `sha256` 未变，并只从外部调用）；
- 保留原判据的**全部阈值与公式**，仅改变求值方式；
- 逐调用比对要求**按位相等**，并记录加速比。

#### PoC-1：`gui/main_window.py:379 _nearest_raw_level_crossing_time_us`

| 验证项 | 结果 |
|---|---|
| 边界用例（含平段/NaN/Inf/精确命中/无交叉/越界钳制） | **11/11 按位一致** ✅ |
| 随机模糊测试 | **4000 轮，0 例不一致** ✅ |
| 真实语料逐调用比对（驱动 offscreen Qt 重放参数卡点击） | **35/35 按位一致** ✅ |
| 扫描样点总数 | 383 862 点（平均 10 968 点/次） |
| 原实现 | 416.24 ms（11 892.7 µs/次） |
| 向量化实现 | 7.01 ms（200.3 µs/次） |
| **加速比** | **59.4×** |
| **独立复跑**（第二轮，12 文件 / 14 次调用 / 1 500 轮模糊） | **14/14 按位一致 · 0 例不一致 · 加速比 70.3×** |

**意义**：直接消除第 3.6 节定位的「参数卡最慢项 848 ms」卡顿点，
且不需要引入任何 Rust 组件。

#### PoC-2：`metrics/plateau_level.py:10 _quiet_plateau_mid`（热点第 1 名，36%）

| 验证项 | 结果 |
|---|---|
| 边界用例（常量/单调/尖峰/极小 span/二值台阶/NaN） | **11/11 按位一致** ✅ |
| 随机模糊测试（8000 轮） | **0 例不一致** ✅ |
| 真实语料逐调用比对 | **48/48 按位一致** ✅ |
| 平均 band 长度 / 最大 | 2 392.6 / 21 724 |
| 原实现 | 12 110.76 ms（252 307.5 µs/次） |
| 向量化实现 | 194.36 ms（4 049.2 µs/次） |
| **加速比** | **62.3×** |
| **独立复跑**（第二轮，12 文件 / 16 次调用 / 3 000 轮模糊） | **16/16 按位一致 · 0 例不一致 · 加速比 60.9×** |

**意义**：单个函数占据参数提取自身耗时的 35.9%，62.3× 意味着**提取阶段可获得
数量级级别的改善**，且同样不需要 Rust。

#### PoC-3：批处理多进程并行（P2 阶段的可行性）—— **实测低于理论，必须下调预期**

先说前提——**提取是纯 CPU 受限**，这是并行的必要条件：

| 阶段 | CPU 时间 | 墙钟时间 | CPU/墙钟 |
|---|---|---|---|
| 装载（含第三方 WFM 解析） | 2.078 s | 2.169 s | 0.958 |
| **参数提取** | 30.266 s | 30.988 s | **0.977** |
| 合计 | 32.344 s | 33.157 s | **0.976** |

**比值 0.976 ≈ 1** 意味着单线程已跑满一个核、几乎没有 I/O 等待，
16 逻辑核下并行的**理论上限约 15.6×**。

但是——**实测远低于理论**（24 个双脉冲文件，安静机器上复测）：

| 并行度 | 墙钟 | 实测加速 | 并行效率 |
|---|---|---|---|
| 串行 | 30.19 s | 1.00× | — |
| 2 进程 | 16.69 s | **1.81×** | **90.4%** |
| 4 进程 | 10.30 s | **2.93×** | 73.3% |
| 8 进程 | 9.06 s | **3.33×** | 41.7% |
| 12 进程 | 8.58 s | **3.52×** | 29.3% |

**实测最佳约 3.5×，仅达理论核数上限的 22%。** 效率从 2 进程的 90% 迅速衰减到
12 进程的 29%，说明瓶颈**不是**进程启动开销（spawn 是一次性的），
而是**内存带宽饱和**——每个工作进程都要各自装载并遍历百万级 float64 数组。

> 诚实声明：第一次运行时机器上同时跑着 544 个测试，串行基准被抬高到 33.14 s；
> 上表是**安静机器上的复测值**。两次结论一致（约 3.5×），差异不影响判断。

**这条结果是本轮研究里最重要的「反直觉」发现**：把 P2 从「接近线性扩展」修正为
**「约 3.5×，且 4 进程以上收益急剧递减」**。

#### 三个 PoC 横向对比：该把力气花在哪

| PoC | 手段 | 实测加速 | 系统代价 | 数值风险 |
|---|---|---|---|---|
| PoC-2 | 向量化 `_quiet_plateau_mid` | **62.3×** | 无 | 低（位级可验证） |
| PoC-1 | 向量化 `_nearest_raw_level_crossing_time_us` | **59.4×** | 无 | 低（位级可验证） |
| PoC-3 | 多进程并行（12 进程） | **3.5×** | 高（进程模型/内存/打包） | 中（结果需逐值比对） |

**结论非常明确：先做 P1（向量化），再考虑 P2（并行）。**
向量化的收益（60× 量级）比并行（3.5×）高一个数量级，而且**没有**进程模型、
numba 缓存竞争、内存带宽饱和这些系统代价。

**这还带出一个反直觉的观察**：向量化的收益（62×）**远大于**换语言可能带来的收益。
原因在 3.4 节已经量化——耗时在 620 万次 numpy 小数组分派上，
而分派开销无论用哪种语言重写都要付；**消除分派次数**才是真正的杠杆。
这也解释了为什么「Rust 一定更快」在本项目上不成立：
把同样的循环结构搬进 Rust，只是把「numpy 分派」换成「Rust 迭代」，
而真正该做的是**改变循环结构本身**。

#### PoC-2 过程中的一个关键失败与修复（值得写进工程规范）

第一版向量化实现用 `np.cumsum` 前缀和求窗口均值，模糊测试立刻抓到 **3 例不一致**
（全部是 `linspace(0,5,26)` + `prefer='low'`）。定位结论：

> `np.cumsum` 是**前向顺序累加**，而 `np.mean` 用 `np.add.reduce` 的**成对求和**，
> 两者在同样数据上会差 **1 ULP**（实测：`2.1000000000000005` vs `2.1`）。
> 本函数的判据是 `mu > v_lo + 0.42*span`，而此处 `v_lo + 0.42*span` 恰好等于 `2.1`，
> **1 ULP 的差异直接翻转了窗口接受/拒绝的判断**，导致选错平台窗口。

修复方式：改用 `np.add.reduce(win_idx, axis=1) / wlen`，实测与 `np.mean`
**按位相同**（`np.max`/`np.min` 的批量版本同样按位相同）。
修复后上表所有用例均按位一致，模糊测试 8000 轮零不一致。

**这条经验适用于任何重写（含 Rust）**：
「数学上等价」不等于「浮点上等价」。凡是参与**阈值比较**的中间量，
必须沿用与现行实现**相同的求和顺序与归约算法**，否则会在边界数据上产生
偶发、难复现的数值漂移。这正是「位级一致」应当作为默认验收标准的理由。

### 4.3 迁移期双跑比对协议（建议固化为流程）

1. 用 `diff_tester.py capture` 在**现行版本**上对全部 488 个 `.tss` 生成基准快照，随版本归档。
2. 任何改动（含 P1 向量化）后重跑，`compare` 必须 **PASS**。
3. 若必须放宽容差，需在 PR 中写明：放宽哪个字段、放宽到多少、**为什么无法做到位级**、由谁签字。
4. 对外发布前，额外跑 `scripts/validate_tss_samples.py` 与 `scripts/validate_gui_cursors.py` 做业务侧交叉验证。
5. 基线快照与 `docs/REGRESSION_BASELINES.md` 的重点保护样例（`UH_750V_1050A_000.tss`、`UL_750V_1050A_000.tss`）必须包含在比对集内。

---

## 五、Rust 工具链现状（如实记录，未编造任何基准）

`scripts/check_rust_toolchain.py` 的实测输出（`raw/rust_toolchain.json`）：

| 探测项 | 结果 |
|---|---|
| `rustc` | ❌ 不在 PATH |
| `cargo` | ❌ 不在 PATH |
| `rustup` | ❌ 不在 PATH |
| `maturin` | ❌ 不在 PATH |
| MSVC `cl` / `link` | ❌ 不可用 |
| `gcc` | ❌ 不可用 |
| `~/.cargo` 目录 | ❌ 不存在 |
| `~/.rustup` 目录 | ❌ 不存在 |

**结论：本机不具备编译任何 Rust 代码的能力，因此本报告不含任何 Rust 编译产物、Rust 基准数据或 Rust 加速比。**

补齐方案（供决策，**本议题未执行**）：

```powershell
# 1) 安装 rustup（Windows x86_64）
#    https://win.rustup.rs/x86_64  ->  rustup-init.exe
winget install --id Rustlang.Rustup

# 2) 默认工具链：MSVC ABI 需要 VS Build Tools 的 C++ 工作负载
rustup default stable-msvc
#    若不便安装 MSVC，可改用 GNU ABI：
#    rustup default stable-gnu

# 3) 若走 PyO3 扩展路线（方案 A）需要 maturin
python -m pip install maturin
maturin new --bindings pyo3 dpt_kernel

# 4) 纯 crate 侧先行验证（不涉及 Python 绑定）
cargo new --lib dpt_kernel
cargo bench
```

**注意**：补齐 Rust 工具链本身需要安装 MSVC C++ 工作负载（数 GB），
在决定是否走 Rust 路线**之前**，应先完成 P0/P1——因为 P1 之后热点分布会改变，
届时的 Rust 目标函数与现在完全不同，**现在就装工具链属于过早投入**。

---

## 六、迁移路线图（分阶段 + 回滚点）

### P0 · 前端还债（1–2 周）

| 项 | 内容 |
|---|---|
| 目标 | 把 `main_window.py`（主工作树 13 017 行 / 测量检出 11 368 行）与 `waveform_plot.py`（10 389 行）拆成职责清晰的模块 |
| 方式 | **纯搬迁**：类与函数原样移动，不改一行数值逻辑；用现有 73 个测试文件兜底 |
| 验收 | 全部测试通过 + `diff_tester` 对全语料 PASS |
| 回滚点 | 每个模块一次提交，可单独 `git revert` |
| 风险 | 低。主要风险是隐式循环导入与 `self.` 状态耦合 |

### P1 · 热点向量化（1–2 周）—— **最高优先级**

| 项 | 内容 |
|---|---|
| 目标 | 消除 Top5 热点里的 Python 元素循环与小数组分派：`_quiet_plateau_mid`、`detect_all`、`_local_extrema_indices`、`_nearest_raw_level_crossing_time_us` |
| 方式 | 逐函数替换，每个函数配一个**逐值等价测试**（照 PoC 的三重验证：边界用例 + 模糊 + 真实语料逐调用比对） |
| **实测依据** | `_quiet_plateau_mid` **62.3×**、`_nearest_raw_level_crossing_time_us` **59.4×**（均按位一致） |
| 验收 | `diff_tester` PASS（位级）；`bench_full_corpus.py` 吞吐提升可测；参数卡最慢项从 848 ms 降下来 |
| 回滚点 | 每函数一次提交 |
| 风险 | 中。**必须**守住两点：(1)「窗口/候选选择顺序」类 tie-break 语义（PoC 示范：取第一个最小值）；(2) **参与阈值比较的中间量必须沿用原求和顺序**（`cumsum` vs `np.mean` 差 1 ULP 就会翻转判断，见 4.2 节） |

**执行顺序建议**：先 `_quiet_plateau_mid`（占 35.9%，杠杆最大），再 GUI 光标投影函数
（消除用户可感知的 848 ms 卡顿），再 `detect_all` 与 `_local_extrema_indices`。

### P2 · 批处理并行（按需，2–3 周）—— **次要优先级，预期已下调**

| 项 | 内容 |
|---|---|
| 目标 | 488 文件批处理场景用多进程并行 |
| 方式 | `ProcessPoolExecutor` + 每进程独立 numba 缓存目录；单文件 GUI 路径不变 |
| **实测依据** | 24 个双脉冲文件：2 进程 1.81×（效率 90%）、4 进程 2.93×（73%）、8 进程 3.33×（42%）、12 进程 **3.52×（29%）** |
| 期望值修正 | **约 3.5×，不是接近线性**。效率从 2 进程起就快速衰减，瓶颈是内存带宽而非进程启动 |
| 建议参数 | 4–8 进程是性价比拐点；**不要**盲目按核数设置 |
| 验收 | 结果与串行逐值一致（用 `diff_tester` 比对串行/并行两次快照） |
| 回滚点 | 并行入口独立模块，可切回串行 |
| 风险 | 中：内存带宽饱和、numba 缓存竞争、日志与进度汇总 |

> **前置依赖**：P2 应在 **P1 之后**做。理由：P1 会显著降低单文件 CPU 时间，
> 届时的并行收益需要**重新实测**；而且先做 P1 能避免为「即将被消除的热点」付并行复杂度。

### P3 · 前端精致化（2–4 周，P0 完成后）

| 项 | 内容 |
|---|---|
| 目标 | 在 PyQt6 内做视觉与交互打磨（参考原型 A） |
| 决策门 | **先在有显示的机器上实测**：真实 GPU 下的平移/缩放帧率、光标手感、以及 WebGL 方案（原型 B）的实际帧率 |
| 方式 | 若实测达标 → PyQt6 精致化；若差距显著且团队接受 WebView 依赖 → 再评估 Tauri |
| 回滚点 | 样式与交互分层，可回退到当前外观 |
| 风险 | 中。`WAVEFORM_UI_SPEC.md` 定义了交互规则，精致化不得违反 |

### P4 · （条件触发）选择性 Rust 内核

**仅在** P0–P2 完成后仍存在**向量化无法解决**的纯数值热点时启动，且：
- 只做 PyO3 扩展（方案 A），保持 Python 侧接口不变；
- 目标函数由**届时的**剖析数据决定，不用现在的名单；
- 必须通过 `diff_tester` 位级验收。

**当前不建议启动**，理由有三：
1. P1 实测已能拿到 60× 量级收益，Rust 相对「向量化」没有结构性优势；
2. 本机**没有 Rust 工具链**，补齐需安装 MSVC C++ 工作负载（数 GB）；
3. P1 之后热点分布会变，**现在选定的 Rust 目标函数届时大概率已不是热点**——
   现在装工具链属过早投入。

---

## 七、风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| **TekVISA 仪器通信** | 迁 Rust 需 VISA FFI，PowerShell+C# 桥（35 KB）无法直接复用；这是全栈重写的最大隐性成本 | **不迁**。仪器桥保持现状，只通过进程边界与内核交互 |
| **Excel 报表保真** | `report_template.py`(145.9 KB) + 4 个 layout 模块 25 KB；模板含 3 个 `externalLink`、51.8 KB `styles.xml`、两张 854 KB 大表；openpyxl 特性面广 | **不迁**。报表留在 Python |
| **`.tss` 内层解析依赖第三方** | Rust 需复刻 `tm_data_types` 的 WFM 编解码语义（见第二节纠正 1） | 若走 Rust，**必须**对第三方解析结果做逐值对齐；优先考虑「解析留 Python，只迁计算」 |
| **`docs/` 未纳入版本控制** | 新机器/worktree/CI 拿不到规范，重写验收无从对齐口径 | **重写前置条件**：先把 `docs/` 纳入版本控制或建立受控副本 |
| **打包与 CI 复杂度** | 双运行时（Python + Rust）会让 `DPT.spec` 单文件打包与 `scripts/build_windows.ps1` 变复杂 | 若引入 Rust，先验证单文件打包可用；否则退回纯 Python |
| **数值口径漂移** | 重写最不可接受的失败模式。且已实测存在**1 ULP 级**陷阱：`cumsum` 与 `np.mean` 的求和顺序差异足以翻转窗口接受/拒绝判断（见 4.2 节 PoC-2 的失败记录） | `diff_tester` 位级默认 + 双跑比对 + 重点保护样例；**参与阈值比较的中间量必须沿用现行实现的求和顺序与归约算法** |
| **前端性能结论未在有显示环境验证** | 原型绘制成本 ≠ 真实帧率 | P3 决策门：**必须在有显示的机器上实测**后再定前端方案 |
| **过早在 Rust 上投入** | P1 之后热点分布会变，现在选定的 Rust 目标函数可能已不是热点；且本机无工具链，补齐需数 GB | 明确 P4 为**条件触发**，不在 P0–P2 前安装工具链 |
| **并行收益被高估** | 理论上限 15.6×，**实测只有约 3.5×**；效率从 2 进程 90% 衰减到 12 进程 29% | 已在本轮修正预期；P2 按 4–8 进程起步，按核数硬套并行度会浪费资源 |
| **内存带宽饱和** | 多进程各自遍历百万级 float64 数组时出现，是并行效率衰减的根因 | 降低并行度、或先做 P1 减少单文件内存流量；必要时分块处理 |

---

## 八、独立复现核查（第二轮执行者复核）

本节的目的是回答一个问题：**上面所有数字，是「测过一次」还是「可以重跑出来」？**

第二轮执行者在**不改动任何生产代码、不改动任何第一轮产物**的前提下，对下面这些关键结论
逐项做了一次独立重跑或独立核查，产物保存在 `raw/verify_*.json` / `raw/code_stats.json`，汇总见
[`raw/verify_replication_summary.json`](raw/verify_replication_summary.json)
（由 `scripts/collect_replication_summary.py` 从原始文件机械拼出，不修约任何数字）。

| 核查项 | 复跑参数 | 结果 | 与第一轮 |
|---|---|---|---|
| **全语料吞吐基线** | 分层抽样 24 文件（`replicate_baseline.py --n 24`） | 逐文件耗时比值中位 **0.866**（复跑更快），提取占比 **0.914** | 与基线 0.920 一致 ✅ |
| **PoC-2 向量化** | 12 文件 / 16 次调用 / 3 000 轮模糊 | 16/16 按位一致、0 例不一致、**60.9×** | 与 62.3× 同量级 ✅ |
| **PoC-1 向量化** | 12 文件 / 14 次调用 / 1 500 轮模糊 | 14/14 按位一致、0 例不一致、**70.3×** | 与 59.4× 同量级 ✅ |
| **热点集合** | 3 文件 × 2 轮 | 前列函数**集合一致**，Top3 内部排序波动 | 结论不变（3.3 节已注明敏感性） |
| **GUI 交互基线** | 同一 offscreen 样本 | 全部指标同量级（构造 112.5 ms、首屏 1823 ms、参数卡最大 639.6 ms） | 一致，复跑快 15–30% ✅ |
| **参数卡尖峰归属** | 同上 | 最慢项仍是 `关断过程/di/dt`，热点仍是 `main_window.py:379` | 一致 ✅ |
| **差分验收器** | 恒等快照 / 篡改快照 | PASS（退出码 0）/ FAIL（退出码 1，检出索引 +1 与 1e-9 漂移） | 一致 ✅ |
| **前端原型构建** | `node build.mjs` + `node shoot.mjs` | 三个 HTML **逐字节不变**；截图 3/3 重新生成成功 | 可复现 ✅ |
| **生产代码未被改动** | 对 PoC 冻结文件复核 sha256 | `metrics/plateau_level.py` = `d54c3c2d…`、`gui/main_window.py` = `29e79dfa…`，与两轮记录一致 | ✅ |
| **热点函数对现行代码是否仍成立** | 逐函数切块比对（`check_hotspot_stability.py`） | **Top20 中 19 个逐字符相同**，仅 `_legacy_err_recovery_settled_base`(0.60%) 有差异 | 结论成立 ✅ |
| **代码体量口径** | 同一脚本测两棵树（`count_code_stats.py --compare`） | 议题的模块级行数与**主工作树逐字吻合**；与测量检出差约 10% | **推翻第一轮「议题数字偏高」的结论** ⚠️ |
| **生产代码可用性** | 28 个测试模块 / 310 个用例（`python -m unittest`） | **全部 OK**（跳过 127 个，多为需语料或可选依赖） | ✅ |

> **测试口径说明**：本机**没有安装 pytest**（第一轮 README 写的 `python -m pytest` 在本机跑不起来），
> 第二轮改用标准库 `unittest` runner 分模块跑，共 **310 个用例通过**。
> 这也是一条旁证：**本议题没有改动生产代码，产品自身测试在测量检出上仍然全绿**。

**核查结论**：四类基线（吞吐 / 热点 / 交互 / PoC）**均可重跑复现**，量级与方向稳定；
绝对值存在 **±30% 的运行间波动**（复跑时机更空闲，普遍快 10–30%），
因此本报告的绝对数字**只用于相对比较，不应作为验收阈值或 SLA 引用**。

**三处由第二轮复核修正的内容**：

1. **3.1 节「4 个失败文件」的原因**：原描述（「短路样例被按双脉冲 profile 提取」）与代码路径不符，
   已修正为「文件自身缺少其标注声明的 CH3 通道数据」。
2. **3.6 节新增口径提醒**：GUI 绝对值仅可用于相对比较。
3. **第二节「纠正 2」整体改写**：第一轮把议题的代码体量判为「偏高 8–10%」，
   实际是**两棵树混算**（议题描述对应主工作树）。已改为双列对照表，
   并补上「热点函数对现行代码仍成立」的逐函数证据。

**复现命令**（从仓库根运行，`PYTHONIOENCODING=utf-8` 可避免中文在 GBK 控制台下显示为乱码）：

```powershell
$env:PYTHONIOENCODING='utf-8'
python analysis_outputs\arch_evolution_2026-10-15\scripts\replicate_baseline.py --n 24
python analysis_outputs\arch_evolution_2026-10-15\scripts\poc_plateau_vectorize.py --files 12 --fuzz 3000
python analysis_outputs\arch_evolution_2026-10-15\scripts\poc_crossing_vectorize.py --files 12 --fuzz 1500
python analysis_outputs\arch_evolution_2026-10-15\scripts\bench_gui.py
python analysis_outputs\arch_evolution_2026-10-15\scripts\bench_param_switch.py
python analysis_outputs\arch_evolution_2026-10-15\scripts\collect_replication_summary.py
python analysis_outputs\arch_evolution_2026-10-15\scripts\count_code_stats.py --compare E:\Works\DPT
python analysis_outputs\arch_evolution_2026-10-15\scripts\check_hotspot_stability.py --other-root E:\Works\DPT --top 20
# 生产代码自身测试（本机无 pytest，用标准库 runner；310 个用例）
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest discover -s dpt_extractor\tests -t . 2>&1 | Select-Object -Last 5
node analysis_outputs\arch_evolution_2026-10-15\frontend_prototypes\build.mjs
node analysis_outputs\arch_evolution_2026-10-15\frontend_prototypes\shoot.mjs
```

> `replicate_baseline.py`、`collect_replication_summary.py`、`count_code_stats.py`、
> `check_hotspot_stability.py` 是第二轮**新增**的脚本
> （仍全部位于 `analysis_outputs/` 内，不触及 `dpt_extractor/`）。

---

## 九、交付物清单

| 交付物 | 路径 |
|---|---|
| 本决策文档 | [`DECISION.md`](DECISION.md)（本文件） |
| 复现说明 | [`README.md`](README.md) |
| 测量与验证脚本 | [`scripts/`](scripts/)（25 个脚本，含第二轮新增的 `replicate_baseline.py` / `collect_replication_summary.py` / `count_code_stats.py` / `check_hotspot_stability.py`） |
| 原始数据与日志 | [`raw/`](raw/)（32 个文件） |
| **独立复现核查产物** | [`raw/verify_replication_summary.json`](raw/verify_replication_summary.json) 及同前缀的 10 个 `verify_*.json` |
| **代码体量口径** | [`raw/code_stats.json`](raw/code_stats.json)（同一脚本测两棵树） |
| 前端原型（3 个，可直接打开） | [`frontend_prototypes/proto_a_pyqt6_refined.html`](frontend_prototypes/proto_a_pyqt6_refined.html) 等 3 个 |
| 原型对照页 | [`frontend_prototypes/index.html`](frontend_prototypes/index.html) |
| 原型截图 | [`frontend_prototypes/shots/`](frontend_prototypes/shots/) |

**验收自检（对应议题的 7 条验收标准）**：

| 验收标准 | 状态 | 证据位置 |
|---|---|---|
| 一页结论：推荐路线 + 理由 + 被否路线否决理由 | ✅ | 第一节 |
| 可复现的性能基线报告（解析/提取/交互三类，含原始数据与脚本） | ✅ **且经独立复跑** | 第三节 + 第八节 + `raw/` + `scripts/` |
| 热点 Top 20 清单（文件:行 + 占比） | ✅ | 3.3 节 + `raw/hotspots.json`（复跑敏感性见 3.3 注释） |
| ≥1 个 PoC：实测加速比 + 数值一致性证据 | ✅ **3 个，均被独立复现** | 4.2 节（62.3×→60.9× / 59.4×→70.3× / 3.5×） |
| 迁移路线图（分阶段 + 回滚点）+ 风险清单（TekVISA/Excel/打包/双跑比对） | ✅ | 第六、七节 |
| 前端方案 2–3 个可比较原型或截图 | ✅ **3 个 + 截图** | `frontend_prototypes/`（构建逐字节可复现，见 3.8 节） |
| 明确列出「不改」的边界 | ✅ | 第一节末 + 第 4.3 节 |

**本议题未修改 `dpt_extractor/` 下任何文件**（`git status -- dpt_extractor` 为空；
PoC 冻结文件的 sha256 复核见第八节）。

**Rust 相关声明**：本机无 Rust 工具链，**本报告不含任何 Rust 编译产物、基准数据或加速比**；
所有加速比均来自「等价向量化」与「多进程并行」这两条本机可执行的路径（见第四节与第五节）。
