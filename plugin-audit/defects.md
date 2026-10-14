# 缺陷清单（含复现步骤 / 根因 / 影响面 / 处置建议）

按严重度排序。每条都标了**证据路径**与**是否已在本议题内实测**，没有实测的一律写「未验证」。

---

## #1 · high · `dsh-cost-meter` 调用了宿主 `settings` 服务不存在的方法 `get()`

**分类**：调用了不存在 / 不兼容的 API（本议题要找的那一类，且**不是** `dsh-task-board`）

**复现步骤**

1. 读源码：`~/.dsh/profiles/desktop/node_modules/dsh-cost-meter/lib/index.js:1100-1101`

   ```js
   const settings = ctx.get('settings')
   const section = typeof settings?.get === 'function' ? settings.get('llm-deepseek') : undefined
   ```

2. 读实时契约：`cordis_inspect_query(platform=host, provider=Service, method=listService)` → `settings` 服务的方法只有
   `configure / prepareDocument / describe / update / replace / mutate` —— **没有 `get`**。
3. 复跑审计：`node audit-plugins.mjs` → `findings.json` 里 `dsh-cost-meter · lib/index.js:1101 · settings.get`。

**根因**：插件按旧版/别的 settings 形态写了 `settings.get(key)`；宿主那侧没有这个方法，只有 `describe()` 等。

**为什么加载层看不出来**：调用点写着 `typeof settings?.get === 'function'` 守卫 ——
**不抛异常、不报错、控制台也没有一行输出**，只是这个分支永远进不去。

**影响面**：DeepSeek 账户余额查询链路上的「读取 `llm-deepseek` 配置段（baseURL / apiKeyEnv）」永久失效，
静默回落到环境变量 `DEEPSEEK_API_KEY` 兜底。也就是说：**用户如果在设置里改过 DeepSeek 的 baseURL 或 apiKeyEnv，
成本计量读余额时不会遵守，而且不会有任何提示。** 费用面板本身的数字统计不受影响（它走 `tokenMeter` 与价格表）。

**处置建议**（按优先级）

1. **上报上游**：把 `settings.get('llm-deepseek')` 换成当前契约里的正确取法（`describe()` 或对应读取路径），
   或改成 `ctx.get('settings')?.describe?.()` + 显式存在性检查；
2. 若短期无法上游修，本机可做最小补丁：把 `.get` 换成契约里真实存在的方法；
3. **不建议**直接停用该插件 —— 它的核心价值（token / 费用统计）不依赖这条链路。

**状态**：已实测确认（还没修，属于「本机补丁 / 上报上游」二选一，由用户决定）。

---

## #2 · high · `dsh-task-board` 落盘锁在 v4 之后仍有超时，根因未定

**复现步骤**

1. 看磁盘版本：`…/dsh-task-board/lib/index.js`（86493 字节，sha256 前 16 位 `3cbcbc5f8182952d`）
   与 `index.js.bak-v4-20261015-000926` **完全一致** → 线上就是 v4。
2. 看诊断日志：`E:\Works\DPT\.dsh\kanban-persist-error.log`

   ```
   2026-10-14T16:13:52.944Z  Error: state file lock timeout | at withFileLock (…/lib/index.js:226:46) …
   2026-10-14T16:14:12.174Z  Error: state file lock timeout
   2026-10-14T16:15:34.953Z  Error: state file lock timeout
   2026-10-14T16:15:51.238Z  Error: state file lock timeout
   2026-10-14T16:17:24.238Z  Error: state file lock timeout   ← 本机 00:17:24
   ```

3. 看宿主启动时间：`Get-Process -Name 'DeepSeek Harness' | Select-Object Id,StartTime` → **00:18:37**
   （晚于 v4 写盘 00:09:26 → 当前进程装载的就是 v4）。
4. 重启后 12 分钟内：日志**零新增**；`kanban-state.json` 在 **00:25:40** 成功写入（`version=46`）；`.dsh/kanban.lock` 不存在。

**根因**：**未定**。已经排除的：① 不是 cc-safety-net 拦的（它只挂工具层，`ctx.shell` 属服务层，够不着）；
② 不是权限预设（本会话 danger-full-access）；③ 语法/沙箱策略已在 v1/v2 修过。
仍不能排除的：**并发 persist 自锁**（多次 `persist()` 抢同一个 `mkdirSync` 锁，陈旧判定阈值 5 分钟太宽）。

**关键不确定性**：00:09:26–00:18:37 之间的 5 条超时，**到底算 v3 还是 v4**，无法在零重启前提下取证
（profile 声明 `patchReload: "live"`、`hmr` 行 active，存在热重载已生效的可能）。

**影响面**：落盘是看板的全部价值所在 —— 一旦再次超时，界面上的拖拽/建议题会「看着成功、实际丢失」。

**处置建议**

1. 把 `persistDiag()` 从只记 `error.message` 扩成**同时记录**
   `result.exitCode / stderr.text / result.sandbox{denied,runnerFailed} / 实际命令行`（一次启动即可定论）；
2. 给 `withFileLock` 加**同进程重入**保护（`store.queue` 已经串行化了写，锁不必对同进程再加一层）或把陈旧阈值从 5 分钟降到秒级；
3. 落盘失败时**必须让用户可见**（现在只写进 `.dsh/kanban-persist-error.log`，界面无感知）。

**状态**：**`待 k-mv8ak8zi-4`**（需一次受控启动才能验证，本议题内不做重启）。

---

## #3 · medium · `dsh-task-board` 健康扫描把「仍在运行的执行体」打回待执行

**复现步骤**：读 `.dsh/kanban-state.json` 中本议题 `k-mv8b6x0z-6` 的 `activity`：

| UTC | 本机 | 事件 |
| --- | --- | --- |
| 16:20:14.186Z | 00:20:14 | `user`：backlog → todo |
| 16:20:14.355Z | 00:20:14 | `system`：todo → **in_progress** |
| 16:25:40.754Z | 00:25:40 | `system`：in_progress → **todo** |

间隔 **5 分 26 秒**，与源码 `STALE_EXEC_MS = 5 * 60 * 1000` + `HEALTH_SCAN_MS = 60s` 吻合；
而此刻执行子代理**仍在正常运行**。

**根因**：卡死判据只看「议题记录多久没更新」，没有把「子代理是否还活着」当作充分条件排除。

**影响面**：`autoExec.enabled = true`（intervalSec 60 / concurrency 3）时，被打回的议题可能被**再次派发**，
同一议题两个执行体写同一个 `vk/<id>` 分支 → 冲突或重复提交。当前批次 `batch-mv8bg043-1496` 仍是
`status: "running"` / `finishedAt: null`，而其唯一 `issueIds` 已被打回 `todo`，状态是自相矛盾的。

**处置建议**：健康扫描的卡死判据应至少满足一条硬条件 ——「子代理失活」或「超时上限远大于 5 分钟」；
把 `run.subagentId` 存活作为**豁免条件**。具体阈值与改法由用户决定。

**状态**：已实测确认（观察记录），**未改动任何状态**（`autoAccept` / `autoExec` 都是用户手动设置的开关）。

---

## #4 · medium · 静默吞异常大面积存在（宿主半边 183 处）

**复现步骤**：`node audit-plugins.mjs` → `summary.silentCatch = 183`（宿主半边、非内联运行时；内联第三方运行时另计 49 处，
客户端半边另计一批）。逐包分布见 `matrix.md` 各小节「静默 catch」行。

**判定口径**：`catch (…) { }` 空体，或 catch 体里只有 `console.error/warn/log` 而**没有** `throw` / `return` / `reject`。

**根因**：这是 DSH 插件生态的通行写法 —— 主进程的 `console.*` **没有接收方**，写进去就没了。

**影响面**：这正是 `dsh-task-board` 能坏 4 轮才被发现的土壤：**功能 100% 失效，加载层与界面全绿**。
它不是一个插件的毛病，而是一整类风险。

**处置建议**

1. 插件侧：catch 里至少给「可观测信号」（写工作区日志文件 / 上报 telemetry / 在界面留痕）；
2. 宿主侧：给插件 `console.*` 一个汇聚出口（按 plugin id 落盘），失败可见；
3. 长期：把「静默 catch」列进插件上架检查项。

**状态**：已实测统计（不逐条判定「这条是不是 bug」，只作为风险面）。

---

## #5 · low · 审计方法自身的覆盖盲区：`webRuntime` 是真实服务，却不在 Service 目录里

**复现步骤**

1. `cordis_inspect_query(host/Service.listService)` → 91 个服务，**无 `webRuntime`**；
2. `dsh-better-sidebar` 的 `inject` 里写了 `webRuntime`（`lib/index.js:6874`、`src/index.ts:114`）；
3. 到宿主源码取证：`app.asar` 内可 grep 到
   `const WEB_RUNTIME_SERVICE = "webRuntime";` 与 patch 文档 `inject: [webRuntime]` —— **它是真实服务**。

**根因**：Service 目录并不枚举全部 cordis 服务（只覆盖登记过的那一批）。

**影响面**：如果审计脚本把「不在目录」一律判成缺陷，就会产出假警报；
反过来，若一律忽略，又会漏掉「插件 inject 了一个真正不存在的服务」。
当前脚本的处理：**显式登记白名单 + 标注证据**，并把它作为 `low` 记录保留在矩阵里（不隐藏）。同时把每个
「不在目录、也未登记」的服务 key 收进 `unknownServiceKeys` 供人工复核。

**处置建议**：上游若能补齐服务登记面最好；否则本白名单需要随宿主升级人工维护（脚本里已集中在一处常数）。

**状态**：已实测确认（属方法学限制，**不是插件的缺陷**）。

---

## #6 · low · 官方 6 个组合包在 `app.asar` 内，静态源码扫描不可达

**复现步骤**

- `Test-Path "D:\Ai-XG\Deepseek Harness\resources\app.asar\dsh"` → **False**（asar 不是目录）；
- `read` 工具读 asar 内文件 → `Error: Cannot mix BigInt and other types, use explicit conversions`（DSH fs 后端缺陷）；
- `glob` 也无法遍历其内部 → `audit-plugins.mjs` 对 6 个官方包输出「静态不可达」。

**根因**：官方 bundle 打包进 asar，而 DSH 的 fs 后端目前读不了 asar 内条目偏移。

**影响面**：官方 6 包的 L3 只能退化为「行 active + 其服务出现在实时目录中」，无法做逐条 API 比对。
**本报告已显式标注，没有假装扫过。**

**处置建议**：给 fs 后端补 asar 读取（或提供解包路径）；在此之前，官方包以运行时实例化为准。

**状态**：已实测确认（工具链限制）。

---

## #7 · low · `dsh-task-board` 未声明任何版本兼容闸

**复现步骤**：读 `…/dsh-task-board/package.json` → `engines` 字段缺失、`peerDependencies` 为空。
对比：`dsh-sidenote` 声明 `engines.dsh = ">=0.1.1-rc.1 <0.2.0 || =0.2.0-rc.2"`，
`deep-read-summarize` 声明 `>=0.1.0-rc.6`，`@linxin666/…` 声明 `dsh.engines.dsh`，
`dsh-cost-meter` 更是逐版登记（`0.2.0-rc.2 = compatible`）。

**根因**：该包是 `github:` 直装的自制插件，没有走发布侧的门禁。

**影响面**：宿主升级时不会有任何提示，正是 `shell.run` 这类 API 漂移能长期潜伏的原因之一。

**处置建议**：补 `engines.dsh`（或 `dsh.engines.dsh`）声明；它同时也是给审计脚本用的自动兼容闸。

**状态**：已实测确认（建议项）。

---

## 附：本次审计**没有**发现的（明确写出来，避免读者误以为漏查）

- **没有任何一个第三方包缺依赖、软链失效、补丁清单缺失、或 `engines.dsh` 不兼容**（14/14 全部通过 L4）。
- **没有发现第二个「调用不存在的方法」**：全量扫描 + 人工复核后只有 #1 一条（`shell.run` 是历史项，已由 v4 前的 v3 修掉）。
- 有 **1 条 `low`**「疑似 JS 内置方法」（`dsh-better-sidebar` 的 `profileContext.endsWith`）经人工追溯是**误报**
  （`const home = ctx.profileContext?.home` 之后的字符串方法），已在脚本里用 `?.` 前瞻修掉，**不计入缺陷**。
- `autoAccept` / `autoExec` 的当前值（true / true）是**用户手动设置**，**不作为缺陷**，也未做任何改动。
