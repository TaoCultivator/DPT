---
id: turn-on-ton-chain-failclosed-truthfulness-v76
status: accepted
project: DPT
scope: measurement-spec; validation; release-gate
module: dpt_extractor.metrics.iec_timings; scripts.validate_gui_cursors
problem: 工作区把「Vge10 必须早于 Ic10，否则 Ton/Td_on/Tr fail-closed」写成规则后，`示例文件\likangkang\NED34jixian\uh\915v-uh-930a-10.8us-25c_000.tss` 由干净 HEAD 的 `OK` 变为 `FAIL=3`；只看「OK→FAIL」很容易被定性成工作区引入的回归或缺陷，从而去回退一条本来正确的规则。
solution: 定性为**正确 fail-closed**，不改规则、不改判据分类。判据链：跨树同源探针证明两树的原始交点**完全一致**（`t_v10=12.802288us`、`t_i10=12.779312us`、`t_i90=12.964060us`，同映射推断 `mapping_source=trend`、同分段 `turn_on=(71088,73899)`、同窗口 `[12.728320,13.307520]us`），带符号 `Td_on=t_i10−t_v10=−22.975ns` ⇒ **Vge10 晚于 Ic10，物理上不可能**；干净 HEAD 用 `abs()` 把它发表成 `Td_on=+22.975ns`、`Tr=184.748ns`、`Ton=161.772ns`，而 `Td_on+Tr=207.723ns` ⇒ **违反 IEC 恒等式 `Ton = Td_on + Tr` 达 45.951ns**。故 HEAD 的 `OK` 是假通过，工作树只是把真实不可用暴露出来（`unavailable_metrics` → 校验器既有规则 `DPT_REQUIRED_INTERSECTION_PARAMS` 判 `FAIL`，该规则在 HEAD 中同样存在）。
keywords:
  - 915v-uh-930a-10.8us-25c
  - 开通 Ton Td_on Tr
  - 原始交点完整性
  - fail closed 反序
  - Ton = Td_on + Tr 恒等式
  - DPT_REQUIRED_INTERSECTION_PARAMS
  - abs() 假通过
  - 跨树同源探针
  - GUI 光标审计 FAIL=0
supersedes: []
related_files:
  - dpt_extractor/metrics/iec_timings.py
  - scripts/validate_gui_cursors.py
  - docs/REGRESSION_BASELINES.md
  - docs/decision-ledger/accepted/slow-turn-on-timing-fallback-v15.md
  - docs/decision-ledger/accepted/turn-on-current-hb-a-raw-intersection-v33.md
  - .dsh/kanban-reports/k-mv8dll5o-8-r5-report.md
  - .dsh/kanban-reports/diagnose-90b7cc9a6e241987cff65011-disposition-r2.md
validation:
  - 工作树探针：`.tmp/dg90/probe_turnon_fail.log`（`t_i10=12.779312us`、`t_i90=12.964060us`、`unavailable(开通/Ton,Td_on,Tr)=[True,True,True]`、发布值 `ton=0.0/td_on=0.0/tr=0.0`）
  - 干净 HEAD 检出同源探针（同一脚本副本，`HEAD=937dc8ad`）：`.tmp/dg90/probe_turnon_fail_HEAD.log`（`ton=161.77218861714164/td_on=22.975473631473967/tr=184.7476622486156`、三个 metric 全部 `available`）
  - 两树原始交点逐位一致；`abs()` 发布值与恒等式之差 `207.723−161.772=45.951ns` 由两日志直接可得
  - 校验器规则来源：`scripts/validate_gui_cursors.py` 的 `DPT_REQUIRED_INTERSECTION_PARAMS`（工作树 `:313`）与 FAIL 分支（工作树 `:3229`）在 `git show HEAD:scripts/validate_gui_cursors.py`（`:294`/`:2165`）中同样存在 ⇒ 该 FAIL 不是新判据
reinforcement:
  subject: 工作区 fail-closed 把样例由 OK 变 FAIL 时，先比较两树的原始交点与参数恒等式，再定性回归/正确，不得为转绿回退规则或改判 INFO
  reward_level: R0
  penalty_level: P0
  score: 0
  feedback_conflict: false
  hard_block: false
  last_event_at: 2026-10-16
created_at: 2026-10-16
updated_at: 2026-10-16
---

# 开通 Ton 链 fail-closed 的定性（v76）

## Decision

1. `示例文件\likangkang\NED34jixian\uh\915v-uh-930a-10.8us-25c_000.tss` 的 `开通/Ton｜Td_on｜Tr` 判 `FAIL` **成立**，属**正确 fail-closed**：该样例没有合法的 IEC 10% 有序交点对（`t_v10 > t_i10`）。
2. **不授权任何削弱**：不得回退 `iec_timings.py` 的反序 fail-closed、不得放宽开通搜索窗、不得把该 `FAIL` 改判 `INFO`（改判等于用分类掩盖真实不可用，卡内明令禁止）。
3. 该样例登记为**正确的已知差异**。发布门槛的「全语料 `FAIL=0`」只能通过以下任一途径达成：经用户授权的数据/沿条件修复，或用户**明确批准**的登记例外（含理由与样例清单）。

## Guardrails

- 本条的定性依据是**原始交点**与**参数恒等式**，不是用例名字或审计汇总数字；任何后续变更必须重跑跨树同源探针再定性。
- 反序判据（`t_v10 >= t_i10`）与既有原子对判据（`t_i10`/`t_i90` 缺失或 `t_i90 <= t_i10`）同属 fail-closed 家族，**同一族的其它参数（如关断 `Td_off/Tf/Toff`）适用同样定性方法**，但其本机覆盖未在本条验证。
- 本条只覆盖这一个样例；同目录其余 35 个文件两树同为 `OK`，**不得写成全语料结论**。

## 与既有 accepted 条目的关系

- `accepted/slow-turn-on-timing-fallback-v15` 规范的是**搜索路径**（仅在缺交点时扩展到 `pulse2_off`）；本条不修改该路径。
- `accepted/turn-on-current-hb-a-raw-intersection-v33` 管的是**开通电流光标** `Hb/A` 的 fail-closed `NaN`；与本条的 `Ton/Td_on/Tr` 时序不是同一参数族，不得互相引用为授权。

## Provenance（如实）

- 反序 fail-closed 规则本身来自主工作树**未提交批次**（`dpt_extractor/metrics/iec_timings.py`，`git diff HEAD` 共 9 行：新增反序守卫 + `abs()` 改带符号差）；其原始提出卡未在本条核实，故不署名。
- 本条的跨树对照与恒等式核算由诊断卡 `diagnose-90b7cc9a6e241987cff65011` 第二轮实测。

```text
index summary: 开通 Ton/Td_on/Tr 在某样例由干净 HEAD 的 OK 变 FAIL 时，定性为「正确 fail-closed」：两树原始交点逐位一致（t_v10=12.802288 > t_i10=12.779312us），HEAD 用 abs() 发表出违反 Ton=Td_on+Tr 达 45.951ns 的三元组（假通过）；不得回退规则、放宽窗口或改判 INFO，样例登记为正确的已知差异，FAIL=0 只能靠授权修复或用户明确批准的例外。
```
