# 已知缺陷处置台账 —— dsh-task-board（看板落盘）

对象：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-task-board\lib\index.js`
（`package.json` 声明来源：`github:xuanlanwuta/dsh-task-board`，版本 1.0.0）

## 一、五轮补丁史（v1→v5）

| 轮次 | 时间（+08:00） | 磁盘证据 | 改动 | 当时以为的根因 | 结果 |
| --- | --- | --- | --- | --- | --- |
| **v1** | 2026-10-14 白天 | 未留 bak | 改**命令方言**：取锁 `mkdir X 2>/dev/null && echo $$ > X/pid` → Windows `New-Item`/`Set-Content`；判陈旧 `stat -f %m` → `[DateTimeOffset]::new((Get-Item X).CreationTimeUtc).ToUnixTimeSeconds()`；释放 `rm -rf X` → `Remove-Item -Recurse -Force` | 「PowerShell 把 `2>/dev/null` 解析成写 `E:\dev\null`，命令必然失败」 | ❌ 未解决 —— 命令仍从未被执行 |
| **v2** | 2026-10-14 23:40 | 未留 bak | 给每个 shell 调用**显式传沙箱策略** `{ mode: 'danger-full-access', workspaceRoot }` | 「插件属『直接调用』，不传策略就落到部署默认 `read-only`，取锁被拒」 | ❌ 未解决（症状不变） |
| **v3** | 2026-10-15 00:04:02 | `index.js.bak-v3-20261015-000402`（86,014 字节，sha256 前 16 位 `8f5660eee66038ad`） | shell **兼容层**：有原生 `run` 用原生，否则 `resolve → execute → result` | 「DSH 的 shell 服务只有 `resolve` + `execute`，**没有 `run`** → `TypeError: shell.run is not a function`」（靠临时诊断日志才抓到） | ⚠️ 症状改变：00:06:26 之后日志里 `TypeError` 消失，改报 `state file lock timeout` |
| **v4** | 2026-10-15 00:09:26 | `index.js.bak-v4-20261015-000926`（86,493 字节，sha256 前 16 位 `3cbcbc5f8182952d`） | **文件锁改用 `node:fs`**（`mkdirSync` 取锁 / `statSync` 判陈旧 / `rmSync` 释放），落盘改走 `node:fs` 原子写（tmp + rename） | 「插件上下文的 shell 调用在本机取不到锁」—— Node 内置 fs 没有沙箱策略/命令方言/API 版本这三层中间态 | ⏳ 之后 00:13–00:17 仍报 5 次 lock timeout，**归因不明**（见 §三） |
| **v5** | 2026-10-15 00:31:26 | `index.js.bak-v5-20261015-003126`（87,168 字节，sha256 前 16 位 `0DC982AE18BFC56C`，与线上一致） | **健康扫描判据**：`stale = 5 分钟无更新` → `hardStale = 运行中且超过 60 分钟硬上限`；子代理不在/已空闲才立即打回 | 见缺陷 #3：5 分 26 秒的「卡死」误判把仍在写工作树的执行体打回待执行，批次队列停摆 | ✅ 判据已改（本轮实测线上就是 v5，见 §二） |

当前磁盘状态（本轮实测，只读）：

```
index.js                          87168  2026-10-15 00:31:26  sha256:0DC982AE18BFC56C
index.js.bak-v5-20261015-003126   87168  2026-10-15 00:31:26  sha256:0DC982AE18BFC56C  ← 与线上完全一致，即「线上就是 v5」
index.js.bak-v4-20261015-000926   86493  2026-10-15 00:09:26  sha256:3cbcbc5f8182952d
index.js.bak-v3-20261015-000402   86014  2026-10-15 00:04:02  sha256:8f5660eee66038ad
```

v5 相对 v4 的差异只有 12 行（健康扫描那一段）：

```
+ const HARD_STALE_MS = 60 * 60 * 1000
+ const hardStale = running && (now - lastT > HARD_STALE_MS)
+ if (!running || hardStale) {
~ const why = alive === null ? '执行子代理已失活'
                : (alive.status !== 'running' ? '执行子代理已空闲（未正常落盘）' : '执行超过 60 分钟无进展')
```

v5 里 shell 相关残留：`shell.run(` **0 次**、`runShell(` **7 次**、`ctx.shell` **1 处**（L11 `const shell = ctx.shell`）、
`node:fs` **5 处**、`mkdirSync/statSync/rmSync/renameSync/writeFileSync` **13 处**
→ 锁与落盘已离开 shell；仍走 shell 的是另外 7 个调用点（`currentBranch` / `doMerge` / `saveReport` 等），
只在派发、自动合并、写报告时才会被触发（**这条也属 L3 扫描范围，已并入矩阵**）。

## 二、v4/v5 的验证窗口（**这一次有真实启动，但不是本议题做的**）

时间线（全部为磁盘/进程实测，非推断）：

| 本地时刻 | 事件 | 证据 |
| --- | --- | --- |
| 00:03:11–00:06:26 | 4 条 `TypeError: shell.run is not a function` | `kanban-persist-error.log` |
| 00:04:02 | v3 写盘 | `index.js.bak-v3-…` |
| 00:08:26–00:17:24 | 8 条 `state file lock timeout`（调用栈指向 `withFileLock`） | 同上 |
| 00:09:26 | v4 写盘 | `index.js.bak-v4-…` |
| 00:18:37 | 宿主**上一代**进程组启动 | 首轮采集（`l4-env.md` 历史记录） |
| 00:25:40 | 看板健康扫描把本议题打回 todo（缺陷 #3） | `kanban-state.json` 的 activity |
| 00:31:26 | v5 写盘 | `index.js.bak-v5-…` |
| **00:32:31/32** | 宿主**当前**进程组启动（外部重启，**非本议题所为**：本议题从 00:20 起零重启） | `Get-CimInstance Win32_Process` 主进程 PID 60356 |
| 00:32:31 → 01:17+ | **零新增落盘失败**；`kanban-persist-error.log` 的 mtime 一直停在 **00:17:24** | 日志文件 mtime + 内容 |
| 期间 | `kanban-state.json` 持续被写：version 46 → 69 → **71**（01:04:56） | 文件 mtime + version |
| 本轮 | `.dsh/kanban.lock` **不存在** | `Test-Path` |

**结论：v5 = 在真实启动窗口下已验证「落盘链路活着」**（40+ 分钟、多个 version 连续推进、零失败、无残留锁）。
这与首轮的「部分已验证」相比是实质前进 —— 因为**进程组是在 v5 写盘之后启动的**，当前跑的就是 v5（哈希一致）。

**仍然不能定论的**：

1. 00:08–00:17 那 8 条 lock timeout **到底属于 v3 还是 v4**：profile 声明 `patchReload: "live"` 且 `hmr` 行 active，
   存在「写盘后被热重载接管」的可能；而 `TypeError → lock timeout` 的**错误类别切换**（00:06:26 → 00:08:26）
   恰好发生在 v3 写盘之后，说明**代码变更确实在不重启的情况下生效过**。
   至于 v4 是 00:09:26 之后立即生效、还是等到 00:18:37 重启才生效，**已无法回溯取证**。
2. **根因仍未定死**。两个候选：① 并发 `persist()` 自锁；② **shell 时代残留的锁目录**（shell 路线下锁可能从未被正确释放，
   而陈旧判定阈值又偏宽）在 5 分钟量级上周期性挡住写入。要定论必须把 `persistDiag()` 从只记 `error.message`
   扩成**同时记录** `result.exitCode / stderr.text / result.sandbox{denied,runnerFailed} / 实际命令行 / 锁目录路径与 mtime`
   —— 那需要一次受控启动 → **标注 `待 k-mv8ak8zi-4`**（本议题内不做重启、不改插件代码）。
3. 重启后的成功写入样本虽多，但**没有并发压测**，「并发 persist 自锁」这条路径依旧未被主动打穿。

## 三、这条缺陷为什么值得单列

它是本议题的立案理由，也是最典型的一种失败形态：

> **`enabled=true` / `fiberPhase=active` / 界面能开、能建议题、能拖状态 —— 但核心落盘从安装第一天起就是死的。**

失败链条上每一环都「看起来正常」：

1. **接口名错**（`shell.run` 不存在）→ 旧 API 沿用，无编译期/加载期检查；
2. **异常被吞**（`catch (e) { console.error(...) }`）→ 主进程的 `console.error` 无人接收，坏了没人知道；
3. **缺少沙箱策略**（不传 `sandboxPolicy`）→ 落到部署默认 `read-only`，写入被拒；
4. **命令方言**（POSIX 专用 shell 语法）→ 在 Windows PowerShell 下必然失败；
5. **静默降级**（`typeof X.get === 'function'` 之类守卫）→ 不抛异常，但分支永不生效。

第 5 条不是 task-board 的问题，而是 **dsh-cost-meter** 的问题（缺陷清单 #1）——
它证明这不是孤例，而是一类系统性风险。

## 四、顺带记录：健康扫描误判（缺陷 #3，**已由 v5 修，仍待观察**）

`kanban-state.json` 里本议题 `k-mv8b6x0z-6` 的 activity 原文（UTC，+8 = 本机）：

| UTC 时刻 | 本机 | 事件 |
| --- | --- | --- |
| 16:20:14.186Z | 00:20:14 | `user`：backlog → todo |
| 16:20:14.355Z | 00:20:14 | `system`：todo → **in_progress**（派发成功并落盘） |
| 16:25:40.754Z | 00:25:40 | `system`：in_progress → **todo**（本议题被打回） |
| 16:32:28Z | 00:32:28 | `system`：in_progress → **todo**（第二次打回，同一原因） |

间隔 5 分 26 秒 / 6 分 48 秒，与 v4 之前的 `STALE_EXEC_MS = 5 * 60 * 1000` + `HEALTH_SCAN_MS = 60s` 吻合；
而当时**执行子代理仍在正常运行**。v5 已把判据改为「子代理失活/空闲才立即打回，运行中只在 60 分钟硬上限打回」。

**风险事实（不改，只报告）**：被打回的议题若再次被 `autoExec` 派发，同一议题可能有两个执行体写同一个
`vk/<id>` 分支 → 分支冲突/重复提交。
**本议题不做**：不关开关、不改状态、不重启 —— `autoAccept` / `autoExec` 都是用户手动设置的状态。
