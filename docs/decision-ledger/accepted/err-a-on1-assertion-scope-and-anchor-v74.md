---
id: err-a-on1-assertion-scope-and-anchor-v74
status: accepted
project: DPT
scope: measurement-spec; validation; test-scope
module: dpt_extractor.metrics.iec_windows; dpt_extractor.tests.test_tss_compatibility
problem: Err A 的「不得越过开通段终点（on1）」在数值上与 2026-08-19 人工工作表 18 点不可分离（边界夹回族六种写法全部失败）；B1 的 WH_600V_403A rr_e 6.34% 未收敛。两张看板卡（k-mv9ealhs-18 / diagnose-1fe83c9a）连续受阻，缺用户口径拍板。
solution: 用户 2026-10-16 10:5x 逐条拍板——① 不夹回、不改数值，把 test_tss_compatibility 的「A 不应越过本次开通过程」断言适用范围收敛到「恢复在紧凑段内结束」的样例（判据=主 IRM 峰后振铃包络门未卡在紧凑段终点+180ns 扩展窗末端），B3 之类「越界结束」样例改判合格并在提交说明登记差异；② 授权把 load<600 且 ha≥legacy.level 支路的 Err A 锚点由 +60ns 改到 +90ns，并补做全语料影响评估（改前/改后各跑一次原始 TSS strict 全量 + 相关测试 + 点名样例），发现新增不合规点即停。
keywords:
  - Err A 越过开通段终点
  - 断言适用范围
  - 在紧凑段内结束
  - 越界结束
  - 振铃包络门
  - WL_480V_800A_000
  - anchor 90ns
  - WH_600V_403A rr_e 3.48%
  - 18 点人工工作表
  - 全语料影响评估
  - Irr 无真实稳定平台来源 INFO
supersedes: []
related_files:
  - dpt_extractor/metrics/iec_windows.py
  - dpt_extractor/tests/test_tss_compatibility.py
  - dpt_extractor/tests/test_mcu25s2_0819_report_reference.py
  - scripts/validate_gui_cursors.py
  - docs/REGRESSION_BASELINES.md
  - docs/decision-ledger/experience/err-a-on1-clamp-worksheet-inseparable.md
  - .dsh/kanban-reports/k-mvaaecqt-26-report-v2.md
validation:
  - 定向 4 项 7 passed 31 subtests passed（上一轮同调用 2 failed 8 passed）
  - 相关三批 49+80+191 passed，0 failed
  - 原始 TSS strict 全量（改前/改后）total=1464 failed=0 warnings=0，8 分片退出码全 0
  - 逐样例差分 err 变化 15 个唯一样例、其余字段逐位不变、最大 5.07%
  - 18 点工作表 over5pct=0 最差 4.37%
  - 单卡审计 反向恢复/Irr files=36 OK=34 INFO=2 FAIL=0；关断过程/Ic_off_max files=36 OK=36 FAIL=0
reinforcement:
  subject: Err A 的「不越过 on1」按样例形态（紧凑段内结束 vs 越界结束）限定断言适用范围；改锚点必须附全语料影响评估
  reward_level: R2
  penalty_level: P0
  score: 2
  feedback_conflict: false
  hard_block: false
  last_event_at: 2026-10-16
created_at: 2026-10-16
updated_at: 2026-10-16
---

# Err A 断言适用范围 + B1 锚点 +90ns（v74）

## Decision

1. **不再尝试边界夹回**：`_refine_err_a_from_recovery_envelope` 的返回值不做「越界才夹、界内一律不动」处理（该族六种写法已实测推翻 2026-08-19 人工工作表 10~14/18 点与 LT 落点 6/6）。
2. **断言按样例形态限定**：`test_err_positive_and_marker_order` 的「A 不应越过本次开通过程」只适用于**恢复在紧凑段内结束**的样例，判据是主 IRM 峰后振铃包络门未卡在「紧凑段终点 + 180ns」扩展窗末端；门卡窗末（如 `WL_480V_800A_000`、工作表点 `UH_750V_806A_000`）属「越界结束」类，不受该断言约束（已登记差异）。
3. **B1 锚点 +90ns**：`load < 600` 且 `ha ≥ legacy.level` 的正向软恢复支路锚点由 `legacy.start + 60ns` 改为 `+90ns`（获用户当次授权）。其它支路、阈值、golden 均不改。
4. **Irr INFO 通道**：审计器在样例**无真实 Irr 稳定平台来源**时，Ha 绑定/有效性/可见性期望按 `INFO` 记录，不再计 `FAIL`。

## Validation Evidence

- 定向 4 项（含 18 点人工工作表）：`7 passed, 31 subtests passed in 69.0s`（上一轮同调用 `2 failed, 8 passed`）。
- 相关批次 A/B/C：`49 passed, 35 skipped, 92 subtests` / `80 passed, 7 skipped, 42 subtests` / `191 passed, 13 skipped, 143 subtests`，全部 0 failed。
- 原始 TSS strict 全量（默认 `--root`，1464 项含 `.tmp` 副本）：改前 `failed=0 warnings=0`，改后 `failed=0 warnings=0`，分类计数两次完全一致。
- 逐样例差分：Err 变化 45 条 = 15 个唯一样例（各 3 份拷贝），`b`/`rr_AB`/`ha`/`settle`/`Ton/Td_on/Tr`/`rr_*`/状态逐位不变；最大相对 5.07%（`HT/VL_600V_403A` 3.332→3.501mJ）、最大绝对 0.169mJ；全部落在被修改支路。
- 工作表：`over5pct=0`，最差 `UH_600V_403A` 4.37%；`WH_600V_403A` 6.34%→3.48%。
- 单卡审计（`likangkang\NED34jixian`，仅该目录）：`反向恢复/Irr` `files=36 items=36 OK=34 INFO=2 FAIL=0`（改前该目录 4 文件批次 `FAIL=1`、exit=1）；`关断过程/Ic_off_max` `files=36 items=36 OK=36 INFO=0 FAIL=0`。
- 已知非本轮缺陷：`TestGuiCursorBinding::test_all_parameter_cursors_bind_correct_waveform` 在 180s 子进程超时上失败（审计本体 172.4s / `OK=128 FAIL=0` / exit=0；该批 4 样例 Err 改前改后完全相同）。阈值属测试口径，未改。

## Guardrails

- 不改 Err 以外的数值口径；不改 golden；不放宽 5% 阈值；不按文件名/批次/桥臂/温度分档。
- 断言收窄只针对单条断言，其余 Err 断言（A 晚于 B、Hb 电平、积分窗宽、独立积分一致、A 在恢复主峰之后）继续对全部样例生效。
- 本判据是**恢复形态分类**，不是「A 是否真的越界」的同义反复：工作表点 `UH_750V_1048A`（A=+158.6ns）判据适用，说明判据没有被写成「谁失败就排除谁」。
- 审计覆盖范围必须逐条如实标注（本目录 / 单卡 / 未跑部分），不得写成「全量通过」。
