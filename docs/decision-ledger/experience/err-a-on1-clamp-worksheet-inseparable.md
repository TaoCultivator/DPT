---
id: err-a-on1-clamp-worksheet-inseparable
status: experience
project: DPT
scope: measurement-spec; validation; workflow-fix
module: dpt_extractor.metrics.iec_windows; dpt_extractor.tests.test_tss_compatibility; dpt_extractor.tests.test_mcu25s2_0819_report_reference
experience_type: validation
problem: Err A 的「A 不得越过开通段终点（on1）」边界夹回与 2026-08-19 人工工作表 18 点在数值上不可分离；每次受阻重诊都在重试同一族夹回写法，每次都推翻另一批样例。
trigger_signals:
  - 失败码 CALIBER_CONFLICT_B3_AND_B1；target `dpt_extractor/metrics/iec_windows.py::_refine_err_a_from_recovery_envelope`（B3）
  - `test_tss_compatibility::test_err_positive_and_marker_order` SUBFAILED(sample='WL_480V_800A_000.tss')：「A 不应越过本次开通过程」
  - Err A 越过开通段终点：LT 拷贝 `A=23.689184us` vs `on1=23.506640us` = **+182.5 ns**
  - 用户口径「越界才夹、界内一律不动」；`test_mcu25s2_0819_report_reference` 18 点 5% 断言（`WH_600V_403A` 6.34%）
root_cause: |
  2026-08-19 人工工作表 18 点的人工卡尺本身把 A 放在 on1 之后 18~180 ns（是常态，不是异常），
  因此 `A < t[on1]` 这条断言与「工作表权威」互斥：任何把越界样例拉回界内的写法都会同时把工作表点
  的 A 左移、缩小 Err 积分窗。实测三种写法（夹到 on1 / 夹到 on1−1 采样 / 纯阈值 160 ns 对照）
  里前两种都让 18 点中 11 点超 5%（其中 10 点是夹回新引入，最差 `WL_750V_1048A` 29.16%）。
  同时 B3 与工作表点 `KSU2577/07CF2C1000/RT/UH_750V_806A` 在细化函数内部全部可观测量上同型：
  branch=load>=600、包络门卡在窗口末端、first_stable=None、细化前 A−on1 = −253.2 vs −0.2 ns、
  细化后 = **+182.5 vs +180.0 ns**；只有数值（legacy.amp/peak 5.43% vs 21.83%、Ha 2.19 vs 8.39）
  不同。凡能分离二者的规则都只能是纯阈值分型。
  附带事实：夹到 on1 本身也不满足该断言（需要严格小于，A 会等于 on1），只有夹到 on1−1 采样才满足。
resolution: |
  不要再试第六种「越界才夹」写法。剩下三条路都必须用户当次拍板（不允许 agent 自行选择）：
  ① 把 `A < t[on1]` 断言限定到「恢复在紧凑开通段内结束」的样例，B3 类 settled-tail 改判合格（改测试期望，不动数值口径）；
  ② 给出 `KSU2506/DCU/SMC/LT/tss/WL_480V_800A_000.tss` 的人工卡尺（A 时刻 / Err mJ），据此再定边界规则；
  ③ 显式授权按批次或电压档分档夹回，并把分档写进 `iec_windows.py` 与规范（口径实质变更）。
  B1（`WH_600V_403A` rr_e 6.34%）同理：候选是把 `load<600` 且 `ha>=legacy.level` 支路的 anchor
  从 +60 ns 调到 **+90 ns**（实测该点 6.34%→3.48%，同支路 `UH_600V_403A` 1.84%→4.37%，18 点均值
  1.696%→1.677%，全部仍在 5% 内）——但这同样是数值口径变更且影响范围未全语料评估，需授权后实施；
  否则按 ② 要该点人工卡尺值。
avoid:
  - 不要再用「越界幅度阈值」夹回（182.5 ns vs 工作表最大 180.0 ns、或 160 ns 之类）——台账已把纯阈值捷径列为禁止分型
  - 不要按文件名、批次、桥臂、温度分档夹回而不申报口径变更
  - 不要把 2026-08-19 人工工作表当可重标 golden，也不要为了通过断言放宽 5% 阈值
  - 不要在缺少人工标注时再实现第四/五/六版「Err A 稳定区入口」
  - 不要把「夹到 on1」当成能让 `A < t[on1]` 通过的写法（严格小于，A==on1 仍失败）
keywords:
  - Err A 越过开通段终点
  - 边界夹回
  - 越界才夹 界内一律不动
  - _refine_err_a_from_recovery_envelope
  - i_search_end
  - WL_480V_800A_000
  - 182.5 ns
  - 18 点人工工作表 5%
  - WH_600V_403A rr_e 6.34%
  - anchor 60ns 90ns
  - CALIBER_CONFLICT_B3_AND_B1
  - 开通段终点 on1
related_files:
  - dpt_extractor/metrics/iec_windows.py
  - dpt_extractor/tests/test_tss_compatibility.py
  - dpt_extractor/tests/test_mcu25s2_0819_report_reference.py
  - docs/decision-ledger/experience/loss-cursor-annotation-request-anchors.md
  - docs/MEASUREMENT_SPEC.md
  - .dsh/kanban-reports/diagnose-1fe83c9a131b113e2e5337a9-report.md
validation:
  - 独立探针（进程内 monkeypatch，只读）：18 点现状 1 点超 5%（`WH_600V_403A` 6.34%）；夹到 on1 与夹到 on1−1 采样都是 11 点超 5%，最差 `WL_750V_1048A` 29.16%
  - 外部积分模型与真实管线逐例一致（`model_matches_pipeline=True`，B3 3.076912→2.107732 mJ、UH_750V_806A 7.334182→5.938159 mJ、UH_750V_1048A 9.032324→6.935731 mJ）
  - 4 个兼容样例现状 `A<on1` = 真/真/真/**假**（只有 B3 拷贝越界）；夹到 on1 后 A==on1，断言仍失败
  - 结构观测量对照：B3 与工作表点 UH_750V_806A 的 branch/包络门状态/first_stable/细化后越界幅度同型（+182.5 vs +180.0 ns）
  - 定向回归：`test_tss_compatibility.py` + `test_mcu25s2_0819_report_reference.py` = 3 failed / 9 passed / 55 subtests（B3、B1 两处 + 一处 CPU 争用下的审计分批超时）
reinforcement:
  subject: 先取用户对「断言限定 / 人工卡尺 / 分档授权」的当次拍板，再动 Err A 入口；不要在无标注时再试夹回写法
  reward_level: R1
  penalty_level: P0
  score: 1
  feedback_conflict: false
  hard_block: false
  last_event_at: 2026-10-16
created_at: 2026-10-16
updated_at: 2026-10-16
---

# Err A 的 on1 边界夹回与工作表 18 点不可分离

## What Happened

2026-10-16 用户拍板 ① 要求「B3 只做『A 不得越过开通段终点』的边界夹回（不得因此改动其它数值）」。
实测这条要求在数值上不可满足：**越界才夹、界内一律不动**的两种最小写法都会同时推翻 2026-08-19
人工工作表 18 点中的 11 点（夹回新引入 10 点），并让 `test_tss_compatibility` 的
`A < t[on1]` 断言在「夹到 on1」时仍然失败。同一问题在 `k-mv9kd25y-22`、`k-mv9ealhs-18`、
`k-mvaaecqt-26` 三张卡上已重复出现。

## Root Cause

1. 工作表 18 点的人工卡尺 A 落在 on1 之后 18~180 ns（`UH_750V_1048A` +158.6、`UH_750V_806A` +180.0、
   `WH_750V_1048A` +130.2、`WL_750V_1048A` +157.4 …），而 A 是 Err 积分窗的上界，把 A 夹回 on1
   等于缩小积分窗 —— 这就是 10 个点被推翻的机制。
2. B3 与工作表点 `UH_750V_806A` 在 `_refine_err_a_from_recovery_envelope` 内部所有可观测量上同型，
   只有数值不同，因此不存在「只夹 B3、不动工作表」的结构性判据。

## Correct First Move

带硬证据向用户取一次当次拍板（三条路见 `resolution`），拍板后再动 `iec_windows.py`。
同时把「实测夹回 → 11 点超 5% / 最差 29.16%」与「B3 vs UH_750V_806A 结构同型表」一并给出，
避免下一轮再从零重诊。

## Do-Not-Repeat Rule

- 没有用户当次拍板，不再实现任何版本的「越界才夹」。
- 不用越界幅度阈值分型；不按文件名/批次/桥架分档而不申报口径变更。
- 不重标工作表、不放宽 5% 阈值。

## Validation Evidence

- 探针脚本：`.dsh/kanban-reports/diag-1fe83c9a/scripts/probe_b3_b1.py`（只读，进程内 monkeypatch）；
  原始数据：`.dsh/kanban-reports/diag-1fe83c9a/probe_b3_b1.json`；运行日志：`…/logs/probe_b3_b1.txt`。
- 结论：18 点现状 1 点超 5%（6.34%）；夹到 on1 / 夹到 on1−1 采样 = 11 点超 5%（最差 29.16%）；
  4 个兼容样例现状 `A<on1` = 真/真/真/假；夹到 on1 后 `A==on1` 断言仍失败。
- 定向回归：`pytest -q dpt_extractor/tests/test_tss_compatibility.py dpt_extractor/tests/test_mcu25s2_0819_report_reference.py`
  = `3 failed, 9 passed, 55 subtests`（B3 + B1 + 一处 CPU 争用导致的审计分批超时）。

## Applicability Limits

- 本记录只断言「夹回与工作表 18 点不可分离」，**不给 B3/B1 的最终口径**；结论要等用户拍板后按
  `record-maintenance` 流程升级。
- 探针里用于对照的「纯阈值 160 ns」写法是**被禁止**的方案，只在证据里出现，不得据此实现。
- anchor +30 ns 候选只在 18 点中的 2 点（`UH/WH_600V_403A`）实测过；其它落同一支路的样例与全语料影响未评估。
- 本记录的复测数据来自主工作树（含 49 条未提交改动）而非 HEAD；引用时须注明工作区状态。

```text
index summary: Err A 的「不越过开通段终点」夹回与 2026-08-19 人工工作表 18 点数值上不可分离（夹回 → 11 点超 5%、最差 29.16%，夹到 on1 仍不满足 A<on1 断言），B3 与工作表点 UH_750V_806A 在函数内部完全同型；只剩「断言限定 / 人工卡尺 / 分档授权」三条路要用户拍板。B1 候选为 anchor +60→+90 ns（6.34%→3.48%）。
```

## 2026-10-16 收口（用户拍板后已解除）

用户当日 10:5x 逐条拍板，本条对应的受阻已解除，按 `record-maintenance` 升级为
`docs/decision-ledger/accepted/err-a-on1-assertion-scope-and-anchor-v74.md`：

- **B3**：不再夹回，改为 `test_tss_compatibility` 的「A 不应越过本次开通过程」**按样例形态限定适用范围**
  （恢复振铃包络门未卡在「紧凑段终点 + 180ns」扩展窗末端才受约束）；`WL_480V_800A_000` 属「越界结束」类，
  改判合格并在 `docs/REGRESSION_BASELINES.md` 登记差异。数值口径未动。
- **B1**：授权 anchor `+60ns → +90ns`（仅 `load<600` 且 `ha≥legacy.level` 支路），并已补做**全语料影响评估**：
  改前/改后各跑一次原始 TSS strict 全量（两次均 `failed=0 warnings=0`），逐样例差分为 15 个唯一样例、
  最大相对变化 5.07%，18 点工作表 0 点超 5%（最差 4.37%）。⇒ 上面「其它落同一支路的样例与全语料影响未评估」
  这一条限制已解除。
- 证据：`.dsh/kanban-reports/k-mvaaecqt-26-report-v2.md`；探针与日志 `.tmp/k26c/`。
