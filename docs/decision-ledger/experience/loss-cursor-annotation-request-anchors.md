---
id: loss-cursor-annotation-request-anchors
status: experience
project: DPT
scope: measurement-spec; validation; workflow-fix
module: dpt_extractor.metrics.iec_windows; scripts.validate_gui_cursors
experience_type: validation
problem: Err A 稳定区入口、关断 B 落点与 Eoff 稳定平台三类口径争议反复阻塞发布（B3/B1 与「第 7 项」跨多张卡重诊），每张卡都要重新跑一遍同样的探针；缺少一份可直接逐条回答的人工标注入口。
trigger_signals:
  - 按批准写法实现在 18 个人工工作表工况点上出现 14/18 超 5%（最差 40.61%）
  - Err A 越过开通段终点（`WL_480V_800A_000.tss` LT 拷贝 +182.5 ns）
  - 关断 Ic_off_max 全语料光标审计出现 FAIL=7（集中在低电流 50A 样例）
  - 决策台账 `loss-right-cursor-default-settled-zone-trial` 要求「下一版必须先人工标注这些样例」
  - 「强化学习/口径」评审需要样例、候选与最小动作，而不是又一个实现版本
root_cause: 三个候选入口（早期低幅穿越 / 包络结束点 / 分类型判据）在同一函数内部的所有可观测量上（锚点、边界、分段、电流档、峰值、扩展标志）无法互相分离，只能靠阈值或人工标注；不先取得人工标注就实现，必然推翻另一批样例的人工工作表。
resolution: 先产出「人工标注请求清单」再动口径——每条给出样例（文件名+工况+数值摘要）、3 个候选定义及其实测数值、当前实现与人工工作表的差值、最小标注动作、以及标注后机器可自动完成的部分；清单落在学习库 `03-运行时取证\2026-10-15-DPT人工标注请求清单.md`，本轮探针原始数据与审计日志留在 `.dsh/kanban-reports/`（git 忽略，不入库）。
avoid:
  - 不要在缺少人工标注时再实现一版「稳定区入口」，尤其是只靠候选点右侧短窗峰峰值、中心漂移和未来短窗反弹的版本（见 rejected/loss-right-cursor-default-settled-zone-trial）
  - 不要把 18 点人工工作表当作可重标的 golden，也不要为了通过断言放宽 5% 阈值
  - 不要把「越界 182.5 ns vs 最大 159.2 ns」这类纯阈值捷径当成分型判据
  - 不要用 GUI 全参数光标审计 FAIL=0 反证 Err 数值口径正确（两者互不覆盖）
  - 全语料 GUI 光标审计不能单窗口跑完，禁止把部分覆盖写成全量通过
keywords:
  - Err A 稳定区入口
  - 早期低幅穿越
  - 包络结束点
  - 分类型判据
  - 关断 B 落点
  - Ic_off_max B
  - 稳定抬升前 Base
  - Ic 下降后 Base
  - Eoff 稳定平台
  - stable_platforms
  - level_crossings
  - 人工标注请求清单
  - manual annotation
related_files:
  - docs/MEASUREMENT_SPEC.md
  - docs/DOUBLE_PULSE_SPEC.md
  - docs/WAVEFORM_UI_SPEC.md
  - docs/REGRESSION_BASELINES.md
  - dpt_extractor/metrics/iec_windows.py
  - dpt_extractor/tests/test_mcu25s2_0819_report_reference.py
  - dpt_extractor/tests/test_tss_compatibility.py
  - scripts/validate_gui_cursors.py
  - docs/decision-ledger/rejected/loss-right-cursor-default-settled-zone-trial.md
  - docs/decision-ledger/accepted/err-a-first-entry-no-tail-v11.md
  - docs/decision-ledger/accepted/err-near-zero-ha-stable-entry-v17.md
  - docs/decision-ledger/accepted/err-late-platform-drift-v73.md
  - docs/decision-ledger/accepted/turn-off-delta-vce-stable-range-cursors-v24.md
  - docs/decision-ledger/accepted/loss-horizontal-platform-center-v7.md
  - docs/decision-ledger/accepted/eoff-smooth-stable-platform-window-v71.md
validation:
  - 18 点人工工作表（18 个 RT 工况）现状 rr_e 偏差 17/18 ≤4.18%，唯一超差点 WH_600V_403A 6.34%；同一管线把入口换成「早期低幅穿越」为 14/18 超 5%（最差 WH_750V_806A 40.61%、WL_600V_403A 40.46%），换成「包络结束点」代理同样 14/18 超 5%
  - B3 权威拷贝由 sample_tss() 排序取 LT：A=23.689184us 超出开通段终点 +182.54ns、Err=3.076913mJ；同族 RT 拷贝 A=23.308442us 在界内、Err=3.444011mJ
  - 关断 Ic_off_max 定点审计（全参数卡、单文件单进程）：工作区 uh/ul/vh 50A 三个样例 FAIL=1（`B未落在Ic下降后Base稳定带`），同一文件干净 HEAD 937dc8ad 为 OK（A=5.385/B=6.173/Hb=-4.5 对 A=5.648/B=6.432/Hb=+3.0）
  - 全语料 Ic_off_max 单卡扫描跑完（`示例文件`、`DPT_VALIDATE_DPT_ONLY=1` + 单卡过滤、每批 40 文件、批后退出）：`415 files / 415 items / OK=384 / FAIL=31`；FAIL 分两类——`B未落在Ic下降后Base稳定带` 16 条、`未找到下降后首个完整 Base 稳定窗` 15 条（后者意味着「Ic 下降后 Base」这套语义在该波形上无解）；受影响样例横跨 35A/50A/100A/285A/403A 五个电流档与 HT/LT/RT 三温。日志 `.dsh/kanban-reports/k-mv9kd25y-22-icoff/`。
  - 干净 HEAD `937dc8ad` 对照（4 个点名样例，单文件审计 205–214s）：全部 `FAIL=0`，其中 `915v-uh-50a-5.5us-175c_000.tss` 为 `A=5.385/B=6.173/Hb=-4.5`（工作区为 `A=5.648/B=6.432/Hb=+3.0`）。
reinforcement:
  subject: 先产出可逐条回答的人工标注请求清单，再改任何光标口径
  reward_level: R1
  penalty_level: P0
  score: 1
  feedback_conflict: false
  hard_block: false
  last_event_at: 2026-10-15
created_at: 2026-10-15
updated_at: 2026-10-16
---

# 损耗/恢复光标口径的人工标注请求锚点

## What Happened

2026-10-15 连续三张卡都卡在同一类问题上：Err A 的稳定区入口、关断 B 的落点、Eoff 稳定平台的两套语义。**每一次都要重新跑一遍探针**才知道「换成另一个候选会打成什么样」，而没有一张卡产出过可直接逐条回答的人工标注入口。结果是实现层反复被推翻：

- 按「早期低幅穿越」实现 ⇒ 18 点人工工作表 **14/18 超 5%**（最差 40.61%），忠实报失败；
- 关断 `Ic_off_max` 的 B 在工作区落到「Ic 下降后 Base」之外 ⇒ 低电流样例光标审计 FAIL；
- Eoff 的 v7（A/B 必须与 Ha/Hb 相交）与 v71（smooth 走稳定平台代表点、不要求相交）在同一批样例上只能二选一。

## Root Cause

三个候选入口在**同一函数内部无法用可观测特征互相分离**：锚点、调用方硬边界、分段、电流档、恢复峰值、扩展标志在这些样例上交错。唯一能「分离」的是纯阈值捷径（例如越界幅度 182.5 ns vs 最大 159.2 ns），属于过拟合。因此这类争议不是实现问题，而是**人工标注缺口**。

## Correct First Move

1. 先查台账：`rejected/loss-right-cursor-default-settled-zone-trial`、`accepted/err-a-first-entry-no-tail-v11`、`accepted/err-near-zero-ha-stable-entry-v17`、`accepted/err-late-platform-drift-v73`、`accepted/turn-off-delta-vce-stable-range-cursors-v24`、`accepted/loss-horizontal-platform-center-v7`、`accepted/eoff-smooth-stable-platform-window-v71`。
2. 再产出「人工标注请求清单」：每条 = **样例（文件名+工况+数值摘要）+ 3 个候选定义及其实测数值 + 现状与人工工作表的差值 + 最小标注动作 + 标注后机器可自动完成的部分**。
3. 清单先落学习库（`E:\AI图书馆\DSH-学习库\03-运行时取证\`），探针原始数据与审计日志留 `.dsh/kanban-reports/`（git 忽略）。

## Do-Not-Repeat Rule

- 没有人工标注，不再实现第四版「稳定区入口」。
- 不重标 18 点人工工作表、不放宽 5% 阈值、不采用纯阈值分型。
- 不用 `FAIL=0` 的光标审计反证 Err 数值口径正确。

## Validation Evidence

- 探针（`%TEMP%` 只读脚本，进程内 monkeypatch，不改生产文件）：`dpt_k22_probe_err_a.py`、`dpt_k22_probe_b3.py`，原始数据 `.dsh/kanban-reports/k-mv9kd25y-22-err-a-probe.json`、`…-err-a-probe-b3.json`。
- 定点审计：`%TEMP%\dpt_k22_audit.ps1`（工作区 + 干净 HEAD），日志 `.dsh/kanban-reports/k-mv9kd25y-22-audit\`。
- 全语料单卡扫描：`%TEMP%\dpt_k22_icoff_corpus.ps1`，日志 `.dsh/kanban-reports/k-mv9kd25y-22-icoff\`。
- 交付物：`E:\AI图书馆\DSH-学习库\03-运行时取证\2026-10-15-DPT人工标注请求清单.md`（含波形截图素材目录）。

## Applicability Limits

- 本条只覆盖「怎么把口径争议变成可回答的标注请求」，**不给三项口径的最终结论**；结论要等用户答复后按 `record-maintenance` 流程升级为 accepted/rejected。
- 探针中的「包络结束点（乙）」是代理实现（锚点 = `base_end + 180ns`），不是任何已落地分支；引用其数值时必须同时引用这一限制。
- 全语料 GUI 光标审计按历史实测无法在单窗口内跑完（122 批，单批 28s~230s），引用覆盖率时不得写成全量通过。
- **后续更正（2026-10-15 22:16）**：本清单 §3.2「Eoff 稳定平台·冲突样例表」的 Ha/Hb 两列首版误用了 Err（反向恢复）上下文的值，已按事件上下文逐行更正（18 点 RT `WH_750V_1048A_000.tss`：`3.8766 / −8.2037` → `11.9227 / −64.2057`）。取值口径与复核方法见 `experience/hahb-event-context-binding.md`，被废弃的做法见 `rejected/evidence-table-hahb-cross-context-fill.md`；引用 §3.2 数值时以更正后的 Eoff 上下文为准。
- **第二轮收口（2026-10-15 22:29，`k-mv9kd25y-22` 重派后）**：本清单 §3.2 的 `—` 占位行已补齐为 29 行（18 点工作表 + 点名 6 点 + 锚点/B3 双拷贝），全部数值由独立重跑的只读探针复测（`mismatches=0`，证据 `.dsh/kanban-reports/vk-k-mv9kd25y-22-r2/round2-verify.md`）；同轮把 §2.2b 的「415 个非短路文件全覆盖」改为写明脚本口径（磁盘 488 个 `.tss` 全部被 `discover_sample_waveforms()` 枚举，内容判据下非短路 415 / 短路 73；按路径判据则为 484，不可互换），并把 §5.2 的汇总指针改指 `…k-mv9kd25y-22-icoff\summary-head.txt`。口径写法与证据指针规则见 `experience/deliverable-coverage-and-pointer-integrity.md`。
- **第三轮收口（2026-10-16，诊断卡 `diagnose-1fe83c9a131b113e2e5337a9`）**：用户已按本清单逐条拍板 ①（Err A 入口）②（关断 B 落点 = 甲·稳定抬升前 Base）③（Eoff 继续 v71）；②③ 已落地，而 ①「B3 只做越界才夹、界内一律不动」经独立复测与人工工作表 18 点**在数值上不可分离**（夹回 → 18 点中 11 点超 5%、最差 29.16%；夹到 on1 本身仍不满足 `A < t[on1]` 严格小于断言）。该结论已另立条目 `experience/err-a-on1-clamp-worksheet-inseparable.md`，本轮未再实现新版本，改向用户取三条路的当次拍板。

```text
index summary: DPT 损耗/恢复光标口径（Err A 入口、关断 B 落点、Eoff 稳定平台）反复阻塞发布时，先产出「样例+候选+最小动作」的人工标注请求清单再改口径；含 18 点工作表三候选实测、B3 越界 182.5ns、Ic_off_max 低电流审计 FAIL 与干净 HEAD 对照锚点。
```
