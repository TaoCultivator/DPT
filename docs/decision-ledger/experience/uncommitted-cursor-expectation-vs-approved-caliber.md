---
id: uncommitted-cursor-expectation-vs-approved-caliber
status: experience
project: DPT
scope: measurement-spec; validation; release-gate
module: dpt_extractor.tests.test_gui_smoke; dpt_extractor.gui.main_window
experience_type: validation
problem: 用户已拍板的光标口径（甲 · 关断 `Ic_off_max` 的 B 落点 = 稳定抬升前 Base）与只存在于未提交工作树的 GUI 回归期望值（被否决的乙口径锚点 `11.641us`）冲突；执行侧既不能改期望（等于重标未提交验收口径），也不能回退拍板（参数数值口径变更），该红项无法自行消解。
trigger_signals:
  - "test_gui_smoke.py:7118: AssertionError: 13.083520000018307 != 11.641 within 0.03 delta"
  - 全量 pytest 唯一红项 test_ic_off_max_matches_manual_stable_cursor_and_focus_ratio
  - 诊断/处置卡要求「台账命中即处理」，但冲突两侧都属红线（验收口径 / 数值口径）
  - 被用户拍板否决口径的实测锚点（B=11.644us）仍被写成回归断言
root_cause: 口径拍板（2026-10-16，甲）先落在生产代码 `gui/main_window.py::_turn_off_ic_off_max_cursor_context`，而未提交批次的 GUI 回归测试是拍板之前按旧口径（乙 · Ic 下降后 Base）手写期望；该用例与 `_turn_off_ic_off_max_cursor_context` 在 HEAD 中都不存在，只存在于主工作树未提交批次，因此「已拍板口径 — 过期期望值 — 提交范围」三者耦合，任何一侧的单点修复都会牵动另外两侧。
resolution: 分两段。**第一段（无授权时）**执行侧只做取证与归因——不改该期望、不回退甲口径；把「已拍板事实」（用户拍板 ②=甲；`docs/REGRESSION_BASELINES.md:790` 明示乙口径与 `B=11.644us` 锚点只作历史追溯、不得再作为当前默认卡值或审计期望；代码注释 `main_window.py:10483-10489` 记录同一拍板）与「冲突证据」（本次独立复跑实测）一并交用户当次拍板，并提示该用例的修复牵动未提交批次（提交范围见 `.dsh/kanban-reports/k-mv8dll5o-8-commit-allowlist-r5.md`）。**第二段（2026-10-16 用户就本次失败给出当次授权后，已落地）**：按已拍板甲口径对齐该用例——`b_us` 由 `11.641` 改为甲口径实测 `13.083520`（±0.03），并补上甲口径语义断言（B 必须落在 `didt_contexts[("关断过程","di/dt")].base_window` 时间区间内）、把随乙口径失效的「A≈20%/B≈50%」构图断言更新为甲口径实测比例（`0.008`/`0.894`）；**生产代码、参数数值、golden 与光标落点零改动**，该用例由 `1 failed` 转 `1 passed`。仍未提交（提交范围未定案，禁止单独提交该文件）。
avoid:
  - 未经用户当次授权时，不得把 `test_gui_smoke.py` 该期望值改成甲的新实测值（属重标未提交验收口径）；已获当次授权并按甲对齐后，仍然**不得回退或二次实现**关断 B 落点（甲已用户拍板，属参数数值口径红线）
  - 不要用「干净 HEAD 没有这个测试」推断该期望无依据（它编码的是真实 GUI 观察锚点，只是属于已被否决的旧口径）
  - 不要在提交范围未定案时单独提交 `test_gui_smoke.py`（该文件属 50 条未落地改动之一）
  - 不要顺带重标同一文件里其它与本次拍板无关的期望值（只改与乙口径直接耦合的断言）
  - 不要把「单测绿」当作发布门槛达成（发布门槛 = 原始 TSS strict + 全量 pytest + 全语料光标审计，三者同时满足）
keywords:
  - test_gui_smoke.py:7118
  - 13.083520
  - 11.641
  - Ic_off_max B 落点
  - 甲 稳定抬升前 Base
  - 乙 下降后 Base
  - 未提交回归期望
  - 重标 golden
  - 关断 B 落点冲突
related_files:
  - docs/REGRESSION_BASELINES.md
  - docs/decision-ledger/experience/loss-cursor-annotation-request-anchors.md
  - docs/decision-ledger/accepted/turn-off-delta-vce-stable-range-cursors-v24.md
  - docs/decision-ledger/accepted/stable-top-base-measurement-v67.md
  - dpt_extractor/tests/test_gui_smoke.py
  - dpt_extractor/gui/main_window.py
  - .dsh/kanban-reports/k-mv8dll5o-8-r5-report.md
  - .dsh/kanban-reports/k-mv8dll5o-8-commit-allowlist-r5.md
validation:
  - 本机独立复跑（2026-10-16，主工作树 `E:\Works\DPT`，`.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider`）：该用例 `1 failed in 3.08s`，`b_us=13.083520000018307` vs 期望 `11.641±0.03`（差 +1.4425us）；日志 `.tmp/k8x/pytest_red_single.log`、`.tmp/k8_r4/pytest_full_v.log`（全量 `1 failed, 909 passed`）
  - `git show HEAD:dpt_extractor/tests/test_gui_smoke.py` 中既无该用例、也无 `_turn_off_ic_off_max_cursor_context` ⇒ 该期望只存在于未提交批次
  - `docs/REGRESSION_BASELINES.md:790`（2026-10-16 现行边界）与 `main_window.py:10483-10489` 代码注释互为佐证：乙口径已被用户拍板否决；该处同时把 `B=11.644us` 锚点降级为历史追溯
  - **对齐后复跑（2026-10-16 第二轮）**：同一命令 `1 passed in 4.05s`（日志 `.tmp/dg90/pytest_after.log`），对齐前基线 `.tmp/dg90/pytest_before.log` 为 `1 failed in 4.38s`
  - **甲口径落点只读探针**（`.tmp/dg90/probe_ic_off_max.py` / `.log`）：`a_us=10.868160`、`b_us=13.083520`、`peak_us=11.210400`、`signed_base=3.15234375`、`|signed_peak|=50.90625`、`base_window=[12.990240,13.190160]us`（B 在窗内且 `ic[b]=3.15625A` ≈ Base 电平）、`x_range=[10.848160,13.348160]us`（`A 8.0%`、`B 89.4%`）；发布值 `turn_off.ic_off_max=50.90625` 未变
  - 全量 pytest 复跑（对齐后，主工作树）：见 `.tmp/dg90/pytest_full.log`
reinforcement:
  subject: 已拍板口径与只存在于未提交工作树的回归期望冲突时，先取证并向用户取当次拍板；拿到当次授权后按已拍板口径对齐过期期望，不为转绿改动生产数值
  reward_level: R2
  penalty_level: P0
  score: 2
  feedback_conflict: false
  hard_block: false
  last_event_at: 2026-10-16
created_at: 2026-10-16
updated_at: 2026-10-16
---

# 未提交回归期望与已拍板光标口径的冲突处置

## What Happened

2026-10-16 的诊断卡 `diagnose-90b7cc9a6e241987cff65011` 处置 `k-mv8dll5o-8` 的发布阻塞项时，全量 pytest 的唯一红项落在 `dpt_extractor/tests/test_gui_smoke.py:7118`：

```text
AssertionError: 13.083520000018307 != 11.641 within 0.03 delta (1.4425200000183072 difference)
```

同一次探针里其它量全部一致（`a_us=10.868160` 对期望 `10.884±0.03`；`signed_base=3.15234375`、`signed_peak=50.90625` 精确一致），只有 B 的时间落点差 `+1.4425us`（= +18 采样 @80ns）。

关键事实：

- 该用例在 HEAD 中**不存在**（属未提交工作新增），其期望值 `11.641` 与被 `docs/REGRESSION_BASELINES.md:792/:800` 记录的历史锚点 `B=11.64384us` / `B=11.644us` 同源。
- 用户 2026-10-16 已拍板 ②「关断 B 落点 = 甲 · 稳定抬升前 Base」，并已落在生产代码（`main_window.py::_turn_off_ic_off_max_cursor_context` 移除「优先取 Ic 主下降后首个稳定带中心」分支）；`docs/REGRESSION_BASELINES.md:790` 明确该乙口径与 `B=11.644us` 锚点「只保留为历史追溯，不得再作为当前默认卡值或审计期望」。
- 于是同一个未提交批次内部自相矛盾：代码走甲，回归期望仍是乙。

## Root Cause

口径拍板先落代码、后对齐测试，而这条测试**写在拍板之前**；又因为它尚属未提交批次，执行侧看不到任何一处「已批准的新期望值」可依据——两侧都是红线（改期望 = 重标未提交验收口径；回退甲 = 参数数值口径变更），冲突无法由执行侧自行消解。

## Correct First Move

1. 复跑该单条用例取证（秒级，不要跑全量）：确认断言两侧的实测值。
2. 在同一批证据里列出「已拍板事实」三处佐证：`REGRESSION_BASELINES.md:790`、`main_window.py` 内同拍板注释、台账 `experience/loss-cursor-annotation-request-anchors` 的第三轮收口记述。
3. 向用户取当次拍板（改期望 / 回退甲 / 复核人工卡尺），并同时提示该用例的修复与「提交范围」耦合。

## Do-Not-Repeat Rule

- 不要自行改这条期望值转绿，也不要回退甲口径。
- 不要把「干净 HEAD 没有该测试」当作期望无依据的证据。
- 不要在提交范围未定案时单独提交 `test_gui_smoke.py`。
- 不要用「单测绿」代替发布门槛（strict + pytest + 全语料光标审计三者同时满足）。

## Validation Evidence

- 单条复跑：`.tmp/k8x/pytest_red_single.log`（`1 failed in 3.08s`，`13.083520000018307 != 11.641`）。
- 全量基线（同日由 `k-mv8dll5o-8` 第五轮独立复跑）：`.tmp/k8_r4/pytest_full_v.log`（`1 failed, 909 passed, 89 skipped, 536 subtests passed in 1806.98s`）。
- HEAD 对照：`git show HEAD:dpt_extractor/tests/test_gui_smoke.py` 无该用例。
- 文档与代码注释：`docs/REGRESSION_BASELINES.md:790`、`dpt_extractor/gui/main_window.py:10483-10489`。
- 侧向佐证（同族语义）：`accepted/turn-off-delta-vce-stable-range-cursors-v24`（关断竖向 A 落在主抬升前安静 Base 带）与 `REGRESSION_BASELINES.md:790` 所称「与 v24 一致」。

## Applicability Limits

- 本条**不裁决**甲与乙谁对，也不给新的落点数值；它只规定这类冲突的处置顺序（取证 → 交用户当次拍板）。
- 结论落地前不得打包、不得把该红项写成已修复。
- 「未提交批次」这一前提若改变（例如该批次已提交并成为既有验收口径），须重新评估本条。
- 本例只覆盖光标落点类的期望值冲突；Err 数值口径、桥臂判定等其它冲突类型仍需各自取证。

## 2026-10-16 第二轮：当次授权后的落地（已完成）

诊断卡 `diagnose-90b7cc9a6e241987cff65011` 第一轮按本条返回 `USER_APPROVAL_REQUIRED`（四项待决、逐条最小问题）。用户随后就本次失败给出**当次授权**（授权指纹 `8e3ef383785a48f64928e726`，同一失败仅放行一次），第二轮据此落地：

- 口径侧不动的判据：甲（稳定抬升前 Base）是**已拍板**口径且已落在生产代码，`REGRESSION_BASELINES.md:790` 明示乙锚点「不得再作为当前默认卡值或审计期望」⇒ 对齐方向唯一。
- 实际改动（**仅测试期望，零生产数值改动**）：`dpt_extractor/tests/test_gui_smoke.py::TestWaveformPlotSmoke::test_ic_off_max_matches_manual_stable_cursor_and_focus_ratio`
  1. `assertAlmostEqual(b_us, 11.641, delta=0.03)` → `assertAlmostEqual(b_us, 13.083520, delta=0.03)`，并加同拍板注释（引用用户拍板 ②、`main_window.py::_turn_off_ic_off_max_cursor_context` 注释与 `REGRESSION_BASELINES.md` 现行边界）；
  2. 新增甲口径**语义**断言：`b_us` 必须落在 `result.didt_contexts[("关断过程","di/dt")].base_window` 的时间区间内（落点语义，不只锚数字）；
  3. 随乙口径失效的构图断言 `(a−x0)/span≈0.20`、`(b−x0)/span≈0.50` 更新为甲口径实测 `0.008`/`0.894`（±0.01），并加 `a_us ≥ x0`、`b_us ≤ x1` 的包含性断言；
  4. `a_us≈10.884`、`a<peak<b`、`|signed_peak|`、`signed_base`、纵向 Ha/Hb 绑定与「结果对象未被改写」等断言**原样保留**。
- 验证：对齐前 `1 failed in 4.38s` → 对齐后 `1 passed in 4.05s`（`.tmp/dg90/pytest_before.log` / `pytest_after.log`）；甲口径全量重建见 `.tmp/dg90/probe_ic_off_max.log`。
- 仍未做（交发布迭代）：该文件的**提交**（提交范围 ③ 未定案，本条禁止单独提交该文件）；全量 pytest 与全语料光标审计的发布门槛见 `docs/REGRESSION_BASELINES.md`「2026-10-16 诊断处置」节。

```text
index summary: 已拍板的光标口径（甲 · 关断 Ic_off_max B 落点）与只存在于未提交工作树的 GUI 回归期望（被否决的乙锚点 11.641us）冲突时，先取证并把逐条最小问题交用户当次拍板；拿到当次授权后按甲口径对齐该期望（11.641→13.083520，补 base_window 语义断言与甲口径构图比例 0.008/0.894），生产数值零改动，用例 1 failed→1 passed；该文件仍属未提交批次，禁止单独提交。
```
