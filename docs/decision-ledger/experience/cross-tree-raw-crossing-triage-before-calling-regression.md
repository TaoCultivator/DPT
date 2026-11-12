---
id: cross-tree-raw-crossing-triage-before-calling-regression
status: experience
project: DPT
scope: validation; release-gate
module: dpt_extractor.metrics.iec_timings; scripts.validate_gui_cursors
experience_type: validation
problem: 工作区改动让某条 GUI 审计判据由「干净 HEAD 判 `OK`」变成「主工作树判 `FAIL`」时，容易被直接写成「未提交工作区引入的新判据/新失败回退行为」并当成回归或缺陷去修；而真实原因可能恰恰相反——HEAD 的 `OK` 是靠 `abs()` / 截断 / 静默回退掩盖了本来就不可用的数据。
trigger_signals:
  - 同一选择、同一文件在两棵树上判定不同（HEAD `OK` / 工作树 `FAIL`），且汇总里只有一两个文件差异
  - FAIL 文案形如「参数按原始交点完整性规则不可用，核心参数缺失真实交点」
  - 该判据在 HEAD 的校验器里**已经存在**（同一常量/同一分支），只是 HEAD 从未触发
  - 报告里出现「属未提交工作区引入的新行为，不是历史失配」这种只有对照、没有中间量的结论
root_cause: 只看顶层判定（OK / FAIL）与发布出来的参数值，不看**原始交点**这类中间量，也不检查参数恒等式（`Ton = Td_on + Tr`、`Toff = Td_off + Tf`、`Err ≥ 0` 等）；而 HEAD 的参数值里可能已经含 `abs()`、`max(0.0, …)`、`min/max` 夹取，顶层数字看起来「正常」，实际是掩盖产物。
resolution: 定性前必须做「跨树同源探针」——把同一个只读探针脚本**逐字节复制**到干净 HEAD 检出与主工作树各跑一次，保证同映射推断、同分段、同窗口，然后比较：(1) 原始交点/中间量是否逐位一致；(2) 每棵树最终发布值是怎么由中间量算出来的（有无 `abs()`/夹取/回退）；(3) 参数恒等式是否成立。只有中间量也被改动时，才把差异定性为工作区回归。
avoid:
  - 不要用「干净 HEAD 判 OK」推断工作区引入的是缺陷；它只证明 HEAD 的顶层判定不同
  - 不要把只有顶层对照、没有中间量的结论写成「已定性」
  - 不要为把审计转绿而回退 fail-closed 规则、放宽搜索窗或把 `FAIL` 改判 `INFO`
  - 不要把「该判据在 HEAD 里也已存在」当成 HEAD 也能触发的证据（触发取决于数据，不取决于规则存在与否）
keywords:
  - 跨树同源探针
  - 干净 HEAD 对照
  - OK 变 FAIL 定性
  - 原始交点
  - 参数恒等式 Ton = Td_on + Tr
  - abs() 假通过
  - fail closed
  - GUI 光标审计 FAIL
related_files:
  - docs/decision-ledger/accepted/turn-on-ton-chain-failclosed-truthfulness-v76.md
  - dpt_extractor/metrics/iec_timings.py
  - scripts/validate_gui_cursors.py
  - .dsh/kanban-reports/k-mv8dll5o-8-r5-report.md
  - .dsh/kanban-reports/diagnose-90b7cc9a6e241987cff65011-disposition-r2.md
validation:
  - 本例双日志：`.tmp/dg90/probe_turnon_fail.log`（工作树）与 `.tmp/dg90/probe_turnon_fail_HEAD.log`（干净 HEAD 检出），两树原始交点逐位一致，差异只出现在 `abs()` 发布值上
  - 恒等式核算：HEAD `Ton=161.772ns` vs `Td_on+Tr=207.723ns`，差 `45.951ns` ⇒ 顶层「可用」是假通过
  - 反例边界：探针必须避开 `Path(__file__).resolve()`（该 HEAD 检出路径是软链，`resolve()` 会把根目录折叠掉，导致 `ModuleNotFoundError`）；用 `.absolute()`
reinforcement:
  subject: 判定「工作区是否引入回归」前，先在两棵树跑同源探针比较原始中间量与参数恒等式
  reward_level: R1
  penalty_level: P0
  score: 1
  feedback_conflict: false
  hard_block: false
  last_event_at: 2026-10-16
created_at: 2026-10-16
updated_at: 2026-10-16
---

# 跨树同源探针：先把「OK→FAIL」定性成回归之前

## What Happened

2026-10-16，`k-mv8dll5o-8` 第五轮报告把 `示例文件\likangkang\NED34jixian\uh\915v-uh-930a-10.8us-25c_000.tss` 的 `开通/Ton｜Td_on｜Tr` 三条 `FAIL` 写成「**属未提交工作引入的新判据/新失败回退行为，不是历史失配**」，并作为四条待用户拍板事项之一交给用户（同日的诊断卡也因此只能返回 `USER_APPROVAL_REQUIRED`）。

第二轮诊断卡用跨树同源探针复核后发现方向恰恰相反：

- 两棵树的**原始交点逐位一致**（`t_v10=12.802288us`、`t_i10=12.779312us`、`t_i90=12.964060us`）；
- 差异只出现在**发布值**：HEAD 用 `abs(t_i10 − t_v10)` 把 `−22.975ns` 发表成 `+22.975ns`，于是给出 `Td_on=22.975ns`、`Tr=184.748ns`、`Ton=161.772ns`；
- 这组数**违反 IEC 恒等式** `Ton = Td_on + Tr`（`207.723 − 161.772 = 45.951ns`）⇒ HEAD 的 `OK` 是假通过；
- 工作树的 fail-closed 只是把本来就不可用的数据暴露出来，而判 `FAIL` 的规则（`DPT_REQUIRED_INTERSECTION_PARAMS`）**在 HEAD 的校验器里也已存在**。

## Root Cause

顶层判定 + 发布值 ≠ 可定性的证据。HEAD 序列里已经含 `abs()` 这类「把反序对变成看似合理正数」的掩盖算子，只比较顶层会出现「HEAD 正常、工作区异常」的错觉。

## Correct First Move

1. 把只读探针脚本逐字节复制到干净 HEAD 检出与主工作树，各自跑一次（同映射推断、同分段、同窗口）。
2. 逐项比较**原始交点/中间量**，再看每棵树是如何把它算成发布值的（找 `abs()`/夹取/回退）。
3. 用参数恒等式与物理有序性（`Vge10` 必须早于 `Ic10`、`Ton = Td_on + Tr`）裁决谁是假通过。
4. 只有在**中间量本身**也被改动时，才把差异定性为工作区回归。

## Do-Not-Repeat Rule

- 不要用「干净 HEAD 判 OK」推断工作区引入的是缺陷。
- 不要为把审计转绿而回退 fail-closed 规则、放宽搜索窗或把 `FAIL` 改判 `INFO`。
- 探针里不要用 `Path(__file__).resolve()` 定位仓库根：本例 HEAD 检出路径是软链，`resolve()` 会把根折叠掉并报 `ModuleNotFoundError`，改用 `.absolute()`。

## Validation Evidence

- `.tmp/dg90/probe_turnon_fail.log`（主工作树：三个 metric `unavailable`，发布值全 0）
- `.tmp/dg90/probe_turnon_fail_HEAD.log`（干净 `937dc8ad` 检出：`ton=161.77218861714164`、`td_on=22.975473631473967`、`tr=184.7476622486156`，三个 metric 全部 available）

## Applicability Limits

- 该方法需要一棵可运行的干净 HEAD 检出（本例复用 `.tmp/blocker_diag/head_worktree`，经 `示例文件` 软链访问同一语料）。
- 只适用于「同一份数据在两棵树上判定不同」的差异定性；对纯新增功能导致的新 `FAIL` 不适用。
