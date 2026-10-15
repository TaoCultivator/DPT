# k-mv9fbuea-19 交付说明：看板 diagnose 分流改为自动立项（先查 decision-ledger）

议题：`[k-mv9fbuea-19] 看板 diagnose 分流改为自动立项：先查 decision-ledger，命中即处理，未命中才请用户授权`
交付日期：2026-10-15 ｜ 交付对象：DSH 看板插件 `dsh-task-board`（本卡只动插件，未改 `E:\Works\DPT` 任何文件）

## 1. 结论

诊断类失败分流（`scheduler-core.mjs` 的 `classify()` → `unknown`）不再停在「受阻 + 等人给证据」，改为**自动开一张阻塞处置卡**：

- 复用既有修复前置机制：卡的 `blockedBy` 挂住原任务、状态 `backlog`、按用户 `promoteBacklog` 开关正常领取、独立验收通过后由看板既有逻辑自动解锁（这一步一行未改）。
- 卡内内置执行须知：先查 `decision-ledger` 台账（索引 / 检索脚本 / `PYTHONIOENCODING=utf-8` / 检索锚点），命中 `accepted`/`experience` → 直接按结论实施并回写台账；命中 `rejected` → 必须写明规避条件；只有 `proposed` 或未命中 → 返回 `failure.code = USER_APPROVAL_REQUIRED` 并附「查过的关键词 + 未命中事实」。
- 限额沿用既有预算：同一失败指纹只开一次卡，修复链深度 ≤ 3、单根 ≤ 8，超限不开卡并转 `hold`（`holdReason=diagnosis-budget-exhausted`）。

## 2. 改动文件清单（8 个模块中哈希真的变化的 4 个）

| 文件 | 变化 |
|---|---|
| `lib/scheduler-core.mjs` | 新增 `DIAGNOSIS_LEDGER`、`diagnosisDispositionDescription()`、`openDiagnosisDisposition()`；限额复用 `POLICY.maxRepairDepth / maxRepairsPerRoot`。`routeFailure` **未改**（分类与 `diagnose/hold` 语义保持原样） |
| `lib/index.js` | `applyRoutedFailure` 在 `diagnose` 分流处调用自动立项并写系统评论；待立项领取评论区分诊断处置卡；`issueView` 暴露 `diagnosisForFingerprint` |
| `lib/host-adapter.mjs` | 候选 Host 事务入口 `fail()` 与生产入口保持一致，避免适配层回落成「挂起等人」 |
| `lib/failure-resolution.mjs` | 修复前置仍必须走前置验收闭环；**仅当依赖全部是自动开的诊断处置卡**时，允许人工补充新证据后的一次恢复，并把该诊断卡作废（防止继续消耗算力） |

未改动的 4 个模块（哈希与基线一致）：`client.js`、`bounded-write.mjs`、`review-interruption.mjs`、`restart-recovery.mjs`。

**明确不动的既有行为**：「缺陷类 → 修复前置」路径、重启自动续跑、依赖自动解锁、用户开关（自动执行 / 自动验收 / `promoteBacklog`）、权限与模型口径。既有 26 套 181 组回归用例**一行未改**。

## 3. 新增用例（`test10.mjs`，9 组）

1. 诊断处置卡内置 decision-ledger 检索须知与授权兜底（索引/脚本/编码/命中分流关键词/原任务约束）
2. 同一失败指纹只开一张卡并共享受影响任务
3. 诊断开卡同样受链深 ≤3 与单根 ≤8 限额约束
4. 诊断类分流自动立项处置卡并挂住原任务（完整插件隔离 RPC，走真实 `applyRoutedFailure`）
5. 处置卡描述自带台账检索步骤与命中分流规则
6. 诊断处置卡按 `promoteBacklog` 开关正常领取（真派发子代理）
7. 台账未命中即转授权类失败挂起（卡内执行体回 `USER_APPROVAL_REQUIRED` → `hold`，不自动重跑）
8. 同一失败指纹不重复开卡，第二个任务挂到同一张卡
9. 全程无宿主错误日志

## 4. 验证命令与结果

```
node build10.mjs                              → 候选10 生成；改动集合核对 = failure-resolution.mjs / host-adapter.mjs / index.js / scheduler-core.mjs
node test10.mjs                               → 9 组通过
node verify-candidate.mjs candidate-10        → 27 套 190 组全部通过
node verify-candidate.mjs candidate-9         → 26 套 181 组全部通过（用同一份改过的回归脚本复现基线，证明脚本改动无副作用）
node install10.mjs                            → 8/8 模块哈希匹配；4 个文件哈希真的变化
在线复核（PowerShell 逐文件 SHA256）          → 8 个模块哈希全部等于安装清单
在线模块 smoke（真机 import + 构造处置卡）    → 卡内 8 个关键须知字符串全部命中，blockedBy 正确
```

`verify-candidate.mjs` 里 `test10.mjs` 只在候选号 ≥10 时纳入（旧候选没有该能力，历史基线保持可原样复现）。

- 安装备份目录：`E:\AI图书馆\DSH-学习库\01-插件与技能调研\原始素材\2026-10-15-看板待立项自动领取开关\install-backup10-20261015-1112`
  （内含 `installation.json` 日志；`inspectPlan` 保证回滚不会覆盖安装后的新修改）
- 回滚：`rollback('<备份目录>/installation.json', { safeWindow: true })`

### 环境缺陷（已顺手修在交付管线里，不属于业务改动）

本机 Node v22.21.1 对「源目录位于 `E:\AI图书馆\…`」的 `fs.cpSync(recursive)` 会**直接崩溃**（退出码 `0xC0000409`），用候选9 同样复现，与本次改动无关。`verify-candidate.mjs` 的复制步骤因此改成 `readdir + copyFileSync` 手工递归复制（行为等价），并在脚本内注明原因。

## 5. 需重启生效

4 个模块已写入在线插件目录
`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-task-board\lib\`，
但当前 DSH 进程内仍是重启前加载的旧模块（ESM 已缓存在内存）。

**需重启 DSH（profile: desktop）后新分流才会在真机生效；本卡未自行重启，也未替用户改动任何开关。**

## 6. 剩余风险

1. 自动开卡面：任何进入 `unknown` 分类的失败（含子代理派发异常、无机器码的人工验收打回）现在都会开诊断处置卡。有「同指纹一次 + 链深 ≤3 + 单根 ≤8 + `promoteBacklog` 开关」四重约束，不会无限开卡；超限时转 `hold` 等人工授权。
2. 卡片是看板里的普通议题，会消耗一次执行 + 一次验收算力；若台账必然命中，成本与收益需在真机跑几轮后评估。
3. 台账路径默认写死为本项目 `E:\Works\DPT\docs\decision-ledger\index.jsonl` 与全局技能脚本 `C:\Users\songzhenxi\.dsh\skills\decision-ledger\scripts\ledger_search.py`，可用 `DIAGNOSIS_LEDGER` / `options` 覆盖；换项目时需另行配置（本卡范围内未做配置化）。
4. 真机端到端（重启后）**待执行**：本次证据为隔离 RPC 端到端 + 在线模块 smoke，未包含重启后的真机验证。
