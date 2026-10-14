# 缺陷清单（含复现步骤 / 根因 / 影响面 / 处置建议）

按严重度排序。每条都标了**证据路径**与**是否已在本议题内实测**，没有实测的一律写「未验证」。

> **口径提醒**：本清单只记**插件缺陷**。用户手动设置的开关/状态（`autoAccept` / `autoExec` 等）
> **不算缺陷、不写进本清单、更不得由 agent 代改** —— 见文末「更正记录」。

---

## 完整清单：「调用了不存在 / 不兼容 API」

这是本议题的核心产出。全量扫描 14 个第三方包 + 6 个官方包（官方经 app.asar 读取）后的结论是：

| # | 严重度 | 位置 | 症状 | 是否抛异常 |
| --- | --- | --- | --- | --- |
| 1 | **high** | `dsh-cost-meter/lib/index.js:1101` `settings.get()` | 宿主 `settings` 服务没有 `get`，余额查询链静的静默降级 | 否（有 `typeof` 守卫 → **静默失效**） |
| 2 | low | `dsh-better-sidebar` `inject: webRuntime`（`lib/index.js:6874`、`src/index.ts:114`） | `webRuntime` 不在 `cordis_inspect` 的 Service 目录里 | 不适用 —— **目录覆盖盲区，非插件缺陷** |

**只有 1 条真缺陷（high），0 条 blocker、0 条 medium。**

本议题的立案缺陷 `shell.run is not a function` **已不在清单里**：它在 v3 补丁里被修掉，
现在脚本对它的检出能力由 `self-check.mjs` 的对照组 1（`shell-run-missing-method`）证明（见下文「可信度」）。

### 为什么可以相信「只有 1 条」：扫描器的探针自检

`node self-check.mjs` —— 9 个合成对照组，全部通过：

| 对照组 | 期望 | 结果 |
| --- | --- | --- |
| `shell-run-missing-method` | 报 `blocker`：`shell.run` 不存在 | ✔ |
| `shell-execute-ok` | **不报**（同服务真实方法） | ✔ |
| `fs-string-instead-of-target` | 报 `high`：第一参是字符串字面量而非 FsTarget | ✔ |
| `guarded-settings-get` | 报 `high` 且标 `guarded`（与 #1 同型） | ✔ |
| `misses-sandbox-policy` | 报 `medium`：`fs.writeText` 未传沙箱策略 | ✔ |
| `__alias-of-call-not-a-service` | **不报**且不产生伪服务 key `plugin` | ✔ |
| `get-accessor-not-a-service` | **不报**且不产生伪服务 key `get` | ✔ |
| `comment-is-not-code` | **不报**（注释里的调用点不算） | ✔ |
| `silent-catch-counted` | 静默 catch 计数 = 2 | ✔ |

即：**对已知缺陷类型会报、对已知误报类型不报** —— 「干净」是扫出来的，不是漏出来的。

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
4. 反向验证扫描器的检出能力：`node self-check.mjs` 的 `guarded-settings-get` 对照组（同型代码 → 必报 high）。

**根因**：插件按旧版/别的 settings 形态写了 `settings.get(key)`；宿主那侧没有这个方法，只有 `describe()` 等。

**为什么加载层看不出来**：调用点写着 `typeof settings?.get === 'function'` 守卫 ——
**不抛异常、不报错、控制台也没有一行输出**，只是这个分支永远进不去。

**影响面**：DeepSeek 账户余额查询链路上的「读取 `llm-deepseek` 配置段（baseURL / apiKeyEnv）」永久失效，
静默回落到环境变量 `DEEPSEEK_API_KEY` 兜底。也就是说：**用户如果在设置里改过 DeepSeek 的 baseURL 或 apiKeyEnv，
成本计量读余额时不会遵守，而且不会有任何提示。** 费用面板本身的数字统计不受影响
（它走 `tokenMeter` 与价格表；旁证：`~/.dsh/storages/cost-meter/ledger.json` 215,827 字节、01:06 仍在写）。

**处置建议**（按优先级）

1. **上报上游**：把 `settings.get('llm-deepseek')` 换成当前契约里的正确取法（`describe()` 或对应读取路径）；
2. 若短期无法上游修，本机可做最小补丁：把 `.get` 换成契约里真实存在的方法；
3. **不建议**直接停用该插件 —— 它的核心价值（token / 费用统计）不依赖这条链路。

**状态**：已实测确认（还没修，属「本机补丁 / 上报上游」二选一，由用户决定）。

---

## #2 · high · `dsh-task-board` 落盘：v5 在真实启动窗口下已通，根因仍未定死

**复现步骤**

1. 磁盘版本：`…/dsh-task-board/lib/index.js` 87,168 字节、2026-10-15 00:31:26、sha256 前 16 位 `0DC982AE18BFC56C`
   —— 与 `index.js.bak-v5-20261015-003126` 完全一致 → **线上就是 v5**。
2. 进程：宿主当前进程组启动于 **00:32:31/32**（外部重启，非本议题所为），**晚于 v5 写盘** → 当前跑的是 v5。
3. 失败日志：`E:\Works\DPT\.dsh\kanban-persist-error.log` **最后一条停在 00:17:24**（文件 mtime 也是 00:17:24）
   → 00:32:31 之后**零新增失败**（40+ 分钟）。
4. 写入仍在发生：`.dsh/kanban-state.json` version 46 → 69 → **71**（01:04:56），6 条议题状态与实时一致。
5. 无残留锁：`.dsh/kanban.lock` 不存在。
6. 五轮补丁的完整时间线与证据见 `evidence/task-board-ledger.md`。

**根因**：**仍未定死**。已排除的：① 不是 cc-safety-net 拦的（它只挂工具层，`ctx.shell` 属服务层，够不着）；
② 不是权限预设（本会话 danger-full-access）；③ 命令方言与沙箱策略已在 v1/v2 修过；④ `shell.run` 不存在已在 v3 修过。
仍不能排除的两个候选：
- **并发 persist 自锁**（多次 `persist()` 抢同一个锁，v4 前的陈旧判定阈值 5 分钟偏宽）；
- **shell 时代残留的锁目录**（shell 路线下锁可能从未被正确释放）周期性挡住写入。

**关键不确定性**：00:08:26–00:17:24 那 8 条 `state file lock timeout` 属 v3 还是 v4 已无法回溯
（profile `patchReload: "live"` + `hmr` active；`TypeError → lock timeout` 的错误类别切换恰在 v3 写盘后发生，
说明改动确实在不重启时生效过）。**本议题在零重启前提下不假装能定论。**

**影响面**：落盘是看板的全部价值所在 —— 一旦再次超时，界面上的拖拽/建议题会「看着成功、实际丢失」。

**处置建议**

1. 把 `persistDiag()` 从只记 `error.message` 扩成**同时记录**
   `result.exitCode / stderr.text / result.sandbox{denied,runnerFailed} / 实际命令行 / 锁目录路径与 mtime`；
2. 给 `withFileLock` 加**同进程重入**保护，或把陈旧阈值从 5 分钟降到秒级；
3. 落盘失败时**必须让用户可见**（现在只写进 `.dsh/kanban-persist-error.log`，界面无感知）。

**状态**：**部分确认** —— 「当前进程（v5）下链路是活的」已实测；「根因已消除」**未验证**，
需一次受控启动 + 诊断扩展 → **`待 k-mv8ak8zi-4`**（本议题零重启、不改插件代码）。

---

## #3 · medium · `dsh-task-board` 健康扫描把「仍在运行的执行体」打回待执行 —— **已由 v5 修，待观察**

**复现步骤**：读 `.dsh/kanban-state.json` 中本议题 `k-mv8b6x0z-6` 的 `activity`：

| UTC | 本机 | 事件 |
| --- | --- | --- |
| 16:20:14 | 00:20:14 | `user`：backlog → todo；`system`：todo → **in_progress** |
| 16:25:40 | 00:25:40 | `system`：in_progress → **todo**（第一次打回） |
| 16:32:28 | 00:32:28 | `system`：in_progress → **todo**（第二次打回） |

间隔 5 分 26 秒 / 6 分 48 秒，与 v4 前的 `STALE_EXEC_MS = 5 * 60 * 1000` + `HEALTH_SCAN_MS = 60s` 吻合；
而此刻执行子代理**仍在正常运行**。

**根因**：卡死判据只看「议题记录多久没更新」，没有把「子代理是否还活着」当作充分条件排除。

**影响面**：`autoExec.enabled = true` 时，被打回的议题可能被**再次派发**，同一议题两个执行体写同一个
`vk/<id>` 分支 → 冲突或重复提交（本轮实测就发生了：本议题被派发过两次）。

**处置建议**：健康扫描的「卡死」判据应至少满足一条硬条件 ——「子代理失活」或「超时上限远大于 5 分钟」。
**v5 已按此改**（运行中只在 60 分钟硬上限打回；子代理不在/空闲才立即打回）。

**状态**：**已处置（本机补丁 v5，00:31:26）**，在当前进程（00:32:31 起）里生效；长任务场景仍待一次真实观察。

---

## #4 · medium · 静默吞异常大面积存在（**修正后：宿主半边 320 处**）

**复现步骤**：`node audit-plugins.mjs` → `summary.silentCatch = 320`（宿主半边、非内联运行时；
内联第三方运行时另计；客户端半边另计 254 处）。逐包分布见 `matrix.md` 各小节「静默 catch」行。

**判定口径**：`catch (…) { }` 空体（含**只有注释**的体，剥注释后为空），或 catch 体里只有
`console.error/warn/log` 而**没有** `throw` / `return` / `reject`。

> **数字修正**：首版报的是 **183**，本轮重算为 **320**。原因不是插件变了，而是首版的正则
> 被**注释里的花括号**挡住 —— `catch (e) { /* 说明里含 { } */ … }` 的 catch 体匹配不上，被整条漏掉。
> 修正后已抽检：`dshmarket` 报 85 处，而对应文件里 `catch` 关键字总数 514；`dsh-task-board` 报 27 处 / 关键字 53 ——
> 报告值恒小于源码关键字数，口径自洽。（剥离注释的副作用也修掉了 dshmarket 的一条**假警报**：
> 它的 `lib/verify.js` 在注释里写了 `const forms = ctx.configForms; forms.get("x")` 当反例，旧版把它当真实调用点。）

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
3. 到宿主源码取证：app.asar 内可读到 `const WEB_RUNTIME_SERVICE = "webRuntime";` 与 patch 文档 `inject: [webRuntime]`
   —— **它是真实服务**（本轮 asar 读通后，这条取证从「听说」变成「可复跑」）。

**根因**：Service 目录并不枚举全部 cordis 服务（只覆盖登记过的那一批）。

**影响面**：若脚本把「不在目录」一律判成缺陷 → 假警报；若一律忽略 → 漏掉「插件 inject 了真不存在的服务」。
当前处理：**显式登记白名单 + 标注证据**，并把它作为 `low` 记录保留（不隐藏）；
每个「不在目录、也未登记」的服务 key 收进 `unknownServiceKeys`（强信号：`ctx.get('名字')`/
`inject` 显式声明）与 `weakUnknownKeys`（弱信号：`ctx.<key>.<method>()` 属性访问，**不据此下结论**）两桶供人工复核。

**状态**：已实测确认（属方法学限制，**不是插件的缺陷**）。

---

## #6 · low · 官方 6 个组合包的静态可达性 —— **首版结论「不可达」已作废**

**首版结论**：`Test-Path "…\app.asar\dsh"` 为 False、DSH 的 `read` 工具读 asar 抛
`Cannot mix BigInt and other types` → 判「官方包静态不可达」，L3/L4 只能退化为「行 active + 服务在目录里」。

**本版结论**：**用普通 Node 进程按 asar 布局直接读，完全可以读**（布局：offset 12 = 头部 JSON 字节数，
JSON 自 offset 16 起，数据区基准 `16 + headerSize`）。`audit-plugins.mjs` 已内置该读取。

**随之拿到的证据**（详见 `evidence/l4-env.md`）：官方 6 包版本均 0.2.0-rc.2、补丁清单存在、
依赖 93/127/1/3/3/4 全部可达、声明行数 94/136/1/7/3/4；
官方包的 `lib/index.js` 基本是 **11 字节占位**（真正干活的是它们 mount 的运行时节模块），
唯一有真实实现的是 `auto-review`（24 KB），已静态扫描且**无契约缺陷**。

**仍然成立的限制**：DSH 自带的 `read` 工具与 `glob` **依然读不了 asar**（那是 DSH fs 后端的缺陷，
不是本议题能修的），所以人工排查 asar 内文件仍需借助脚本。

**处置建议**：给 DSH fs 后端补 asar 读取（或提供官方解包路径）；在此之前用 `audit-plugins.mjs` 的读取实现。

**状态**：已实测确认（本议题内自解决）。

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

## 附一 · 审计方法自身的精度修正（本轮做的，直接影响「清单可信度」）

| # | 类型 | 现象 | 处置 |
| --- | --- | --- | --- |
| 1 | 假警报 | 注释里的调用点被当成真实调用（`dshmarket/lib/verify.js` 的 `ctx.configForms` 例子） | 扫描前**剥离注释**（等长空格替换，行号不变） |
| 2 | 假警报 | `const handle = ctx.plugin(HotTree, …)` 后 `handle.dispose()` → 伪服务 key `plugin` | 别名规则排除 `ctx.<svc>(` 这种**调用**形态 |
| 3 | 假警报 | `const get = ctx.get; get.call(ctx, name)` → 伪服务 key `get` | `ctx.get` 是服务反射访问器，不作为服务别名 |
| 4 | 漏报 | 注释里的花括号挡住 catch 体匹配 → 静默 catch 少报（183 vs 320） | 与 ① 同修；数字已更正 |
| 5 | 分级 | `ctx.<key>.<method>()` 属性访问（如内联 zod 的 `ctx.data.entries()`）与「按名字要服务」混在一起 | 拆成 `unknownServiceKeys`（显式）/ `weakUnknownKeys`（弱信号）两桶 |
| 6 | 快照误报 | 行表快照漏录 `time-context` → 报「缺失」 | 复核后补录；并在报告里写明「缺行必须先人工复核」 |

以上 6 条都已固化成 `self-check.mjs` 里的对照组，防止将来改坏。

## 附二 · 本次审计**没有**发现的（明确写出来，避免读者误以为漏查）

- **没有任何一个第三方包缺依赖、软链失效、补丁清单缺失、或 `engines.dsh` 不兼容**（20/20 通过 L4）。
- **没有发现第二个「调用不存在的方法」**：全量扫描 + 人工复核后只有 #1 一条
  （`shell.run` 是历史项，v3 已修；`fs.writeText` 传字符串是历史疑似项，v4/v5 已改走 `node:fs` 原子写）。
- 有 **1 条 `low`**「疑似 JS 内置方法」（`dsh-better-sidebar` 的 `profileContext.endsWith`）经人工追溯是**误报**
  （`const home = ctx.profileContext?.home` 之后的字符串方法），已修，**不计入缺陷**。
- **加载层 18/20 完成逐 id 机器比对，缺失 0、异常非 active 0**（另 2 个是 base/web-app，原因见 `l1-rows.md`）。

## 附三 · 更正记录（写进规则，不只是一次性改正）

### `autoAccept` **不是**插件漂移，是用户本人点的

曾经的判定：看到 `autoAccept=True`（备份时间线 v10–v15 为 False，v26 变 True），推断「无人操作下的静默漂移」，
并**擅自用 `kanban.setAutoAccept(false)` 把它关掉**。用户随即指出：**那个开关是他自己在界面上开的**。

**事实**：这不是插件缺陷，是 agent 把一个**用户手动设置的开关**当成了故障去「修」。
**已处置**：立即恢复用户设置（`kanban.setAutoAccept(true)`，2026-10-15 00:20）。
**本清单不收录该条**，也**不作**任何插件缺陷。

**教训（已写进用户级 `AGENTS.md` 第 7 条）**：用户手动改过的开关/状态，agent 不得在未经当次明确授权时改回；
发现异常先记录、先报告；「以前批过一次」不等于长期授权。

### 插件 shell 调用取不到锁 **不是** cc-safety-net 拦的（已排除）

① `cc-safety-net` 只 `inject: ["tools"]`，挂在**工具层**（拦 agent 的 `pwsh` 等）；
② 权限预设作用域是会话工具调用（本会话 danger-full-access）；
③ v2 已对插件显式传沙箱策略 `{mode:'danger-full-access', workspaceRoot}`；
④ `subprocess` / `shell-env` / `pwsh-sandbox` 三个服务行均 active。
→ 真正的失败点在「shell 服务 → pwsh 执行」这一段，而不是被某个插件拦下（该结论已并入 #2/#4 与 L3 扫描规则）。

### 仍然成立的观察（与 `autoAccept` 无关，保留）

`autoAccept=true` 时，议题进入待验收会自动派验收子代理，通过后由看板自动 `git merge` 回主分支；
而本机主工作树当时有 33 个未提交改动 —— 这条**风险事实**值得在派发前确认，但**是否开启由用户决定**。
