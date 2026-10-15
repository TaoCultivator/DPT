# k-mv9g0o2i-21 交付说明：任何 ACCEPTANCE_* 失败码都归「修复」类

议题：`[k-mv9g0o2i-21] 看板分流修正：任何 ACCEPTANCE_* 失败码都归"修复"类，不要再退回"未知原因等人工诊断"`
交付日期：2026-10-15 ｜ 交付对象：DSH 看板插件 `dsh-task-board`（本卡只动插件；未改 `E:\Works\DPT` 仓库内任何项目文件，`git status` 干净）

## 1. 结论（事故复现与根因）

2026-10-15 19:1x，`k-mv8wjxd7-14` 被独立验收打回，验收给出的机器码是 `ACCEPTANCE_EVIDENCE_MISSING`。它**没有**自动立项修复，而是掉进 `UNKNOWN` → 「未知原因、等人工给诊断证据」。根因两处写死的码：

- `lib/scheduler-core.mjs` 的 `classify()` 只把写死数组里的 `ACCEPTANCE_CRITERIA_UNMET` 归 `repair`；
- `lib/host-adapter.mjs` 的 `normalizeFailure()` 只保留 `supportedCodes` 白名单内的码，其余一律降级为 `UNKNOWN`——而白名单同样只放行写死的那一个验收码。

本卡把「验收打回」这一类失败统一认成**交付缺陷**：验收侧只要给出 `ACCEPTANCE_*` 前缀的机器码，就一律归 `repair`，直接开修复前置，不再回头问用户授权。

## 2. 改动文件清单（8 个模块中哈希真的变化的 2 个）

| 文件 | 变化 |
|---|---|
| `lib/scheduler-core.mjs` | 新增 `ACCEPTANCE_FAILURE_PATTERN = /^ACCEPTANCE_[A-Z0-9_]+$/` 与 `isAcceptanceFailureCode(code)`（非字符串一律不认）；`classify()` 在**保留原写死数组**的前提下新增一条前缀判据 `if (isAcceptanceFailureCode(f.code)) return 'repair'`，位置在 `return 'unknown'` 之前 |
| `lib/host-adapter.mjs` | `normalizeFailure()` 的取码表达式改为 `supportedCodes.has(machine.code) || core.isAcceptanceFailureCode(machine.code) ? machine.code : 'UNKNOWN'`，即「白名单命中 或 `ACCEPTANCE_*` 前缀」才保留原码，其余不明码仍是 `UNKNOWN` |

未改动的 6 个模块（哈希与基线一致）：`index.js`、`client.js`、`failure-resolution.mjs`、`bounded-write.mjs`、`review-interruption.mjs`、`restart-recovery.mjs`。

**`index.js` 一行未改**（议题第 3 条：保留验收自带的 `structured.failure`，仅当它没给时才用兜底码 `ACCEPTANCE_CRITERIA_UNMET`、兜底文案不动）。构建脚本 `build11.mjs` 里对这段兜底逻辑做了唯一锚点存在性断言，防止后续误改；`test11.mjs` 用端到端用例把它钉死（验收只回 `verdict:'fail'` 时仍得兜底码 `ACCEPTANCE_CRITERIA_UNMET`，修复卡描述仍带验收原文）。

**明确不动的既有行为**：瞬时/授权/配置类分流、`diagnose` 自动立项（候选10）逻辑、修复前置限额、依赖自动解锁、用户开关（自动执行 / 自动验收 / `promoteBacklog`）、权限与模型口径。既有 27 套 190 组回归用例**一行未改**。

### 补丁原文（相对候选10 基线的全部差异）

```diff
--- lib/scheduler-core.mjs
+++ lib/scheduler-core.mjs
@@ -65,6 +65,12 @@ export function claim(state, id, attemptId, now = Date.now()) {
 }
+// 验收侧给出的失败码统一以 ACCEPTANCE_ 开头（如 ACCEPTANCE_CRITERIA_UNMET、ACCEPTANCE_EVIDENCE_MISSING）。
+// 前缀判定只放行这一族的机器码，不做任何模糊文字猜测；非字符串一律不认。
+export const ACCEPTANCE_FAILURE_PATTERN = /^ACCEPTANCE_[A-Z0-9_]+$/;
+export function isAcceptanceFailureCode(code) {
+  return typeof code === 'string' && ACCEPTANCE_FAILURE_PATTERN.test(code);
+}
 // 仅信任机器代码/明确类别，不凭含糊文字猜测瞬时失败。
 export function classify(f) {
@@ -72,6 +78,9 @@
   if (['TEST_REGRESSION', 'CODE_DEFECT', 'DELIVERABLE_MISSING', 'ENVIRONMENT_MISSING', 'PERMISSION_DENIED', 'ACCEPTANCE_CRITERIA_UNMET'].includes(f.code)) return 'repair';
+  // 任何 ACCEPTANCE_* 前缀的验收失败码一律归修复类：验收侧换个同样合理的码名（如 ACCEPTANCE_EVIDENCE_MISSING）
+  // 不得再退回“未知原因、等人工给诊断证据”。写死数组保留，前缀匹配只作补充判据。
+  if (isAcceptanceFailureCode(f.code)) return 'repair';
   return 'unknown';
 }

--- lib/host-adapter.mjs
+++ lib/host-adapter.mjs
@@ -6,7 +6,9 @@
-  const code=supportedCodes.has(machine.code)?machine.code:'UNKNOWN';
+  // 白名单命中，或验收侧给出的 ACCEPTANCE_* 前缀码（与 scheduler-core.classify 的修复类判据同源）都保留原码；
+  // 其余不明码仍是 UNKNOWN，不凭含糊文字把未知错误判成可自动处理的故障。
+  const code=(supportedCodes.has(machine.code)||core.isAcceptanceFailureCode(machine.code))?machine.code:'UNKNOWN';
```

## 3. 新增用例（`test11.mjs`，11 组，零真实模型调用）

纯规则核心（`scheduler-core` / `host-adapter` 直接导入）：

1. 任何 `ACCEPTANCE_*` 失败码都归修复类（含 `ACCEPTANCE_EVIDENCE_MISSING`；边界 `ACCEPTANCE_`、`acceptance_a`、`ACCEPTANCE-1`、中文码、非字符串一律不认）
2. `ACCEPTANCE_EVIDENCE_MISSING` 走 `repair`：自动建修复前置、原任务挂 `blockedBy`、修复卡描述含验收原文与证据指纹、不开诊断卡
3. `ACCEPTANCE_CRITERIA_UNMET` 行为不变（分类 / 归一 / 修复卡标题与描述）
4. 非 `ACCEPTANCE_` 前缀的未知码仍归一为 `UNKNOWN` 并走 `diagnose`
5. 白名单原有码行为不变（`TEST_REGRESSION` / `PERMISSION_DENIED` / `RATE_LIMITED` / `HTTP_429` / 无代码文本仍 `UNKNOWN`）
6. Host 适配层生产入口 `createAdapter().review()` 验收打回时保留 `ACCEPTANCE_EVIDENCE_MISSING` 并立修复前置

完整插件隔离 RPC 端到端（真走 `applyRoutedFailure` → `routeFailure` → 修复前置，子代理由测试桩接管）：

7. 端到端：验收打回 `ACCEPTANCE_EVIDENCE_MISSING` 自动开修复前置并挂住原任务（`failureControl.category='repair'`、`action='awaiting-repair'`、无诊断卡）
8. 端到端：修复卡标题与描述保留验收原文与证据指纹，未被降级成 `UNKNOWN`
9. 端到端：验收未给 `structured.failure` 时仍用兜底码 `ACCEPTANCE_CRITERIA_UNMET`（兜底文案不变）
10. 端到端：非 `ACCEPTANCE_` 前缀未知码仍走诊断处置卡、不误开修复卡
11. 全程无宿主错误日志

## 4. 验证命令与结果

```
node build11.mjs                              → 候选11 生成；基线核对（在线 == 候选10 安装哈希）通过；
                                                改动集合核对 = host-adapter.mjs / scheduler-core.mjs（index.js 未改）
node test11.mjs                               → 11 组通过
node verify-candidate.mjs candidate-11        → 28 套 201 组全部通过
                                                 （其中既有基线 27 套 190 组一组未变，新增 test11 贡献 11 组）
node install11.mjs                            → 8/8 模块哈希匹配；2 个文件哈希真的变化
在线逐文件 SHA256 复核（PowerShell，比对 deployment-manifest-11.json） → 8 个模块哈希全部匹配（不匹配数=0）
在线模块 smoke（真机 import 已安装文件）        → ACCEPTANCE_EVIDENCE_MISSING→repair、
                                                 ACCEPTANCE_CRITERIA_UNMET→repair、WIDGET_FLUX_9→unknown、
                                                 TEST_REGRESSION→repair；normalizeFailure 保留验收码、未知码仍 UNKNOWN
```

- 安装备份目录：`E:\AI图书馆\DSH-学习库\01-插件与技能调研\原始素材\2026-10-15-看板待立项自动领取开关\install-backup11-20261015-1121`（内含 `installation.json` 日志）
- 回滚：`rollback('<备份目录>/installation.json', { safeWindow: true })`（未执行）
- `verify-candidate.mjs` 增补一行：`test11.mjs` 仅在候选号 ≥ 11 时纳入（候选10 及更早没有该能力，历史基线 27 套 190 组可原样复现）；`test10.mjs` 的纳入条件（≥10）保持原样。
- 素材目录命名避让：本卡产物一律用 `11`（`build11.mjs` / `candidate-11` / `source-snapshot-11` / `test11.mjs` / `install11.mjs`）、交付目录用 `plugin-acceptance-repair/`，与 k-mv9fbuea-19 的 `*10` / `plugin-diag-ledger` 无重叠。

## 5. 需重启生效

2 个模块已写入在线插件目录
`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-task-board\lib\`，
但当前 DSH 进程内加载的仍是重启前的旧模块（ESM 已在内存）。

**需重启 DSH（profile: desktop）后新分流才会在真机生效；本卡未自行重启，也未替用户改动任何开关。**

## 6. 剩余风险

1. 真机端到端（重启后）**待执行**：本次证据为隔离 RPC 端到端 + 在线模块 smoke，不含重启后的真机验证（议题已明确要求本卡不得自行重启）。
2. 前缀判据只认 `^ACCEPTANCE_[A-Z0-9_]+$`：验收侧若换用不带该前缀的码名（例如 `EVIDENCE_MISSING`），仍会落到 `UNKNOWN`/诊断；建议验收 prompt 的码名口径保持 `ACCEPTANCE_*`。
3. 归入 `repair` 后仍受既有修复预算约束（链深 ≤3、单根 ≤8、同指纹不重复开卡）；预算耗尽时转 `hold` 等人工，这是既有设计，不在本卡改动范围。
4. `ACCEPTANCE_` 前缀把「验收打回」一律视为交付缺陷：若验收判定的是环境/权限类阻塞却仍带该前缀，也会走修复路径；证据（`target`/`scope`/`message`）原样带进修复卡，便于执行体识别（可用 `ENVIRONMENT_MISSING` / `PERMISSION_DENIED` 等既有码走同一条修复路径）。
