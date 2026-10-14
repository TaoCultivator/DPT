# 已知缺陷处置台账 —— dsh-task-board（看板落盘）

对象：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-task-board\lib\index.js`
（`package.json` 声明来源：`github:xuanlanwuta/dsh-task-board`，版本 1.0.0）

## 一、四轮补丁史

| 轮次 | 时间（+08:00） | 备份文件 | 改动 | 当时以为的根因 | 结果 |
| --- | --- | --- | --- | --- | --- |
| **v1** | 2026-10-14 白天 | —（未留 bak） | 改**命令方言**：取锁 `mkdir X 2>/dev/null && echo $$ > X/pid` → Windows 的 `New-Item`/`Set-Content`；判陈旧 `stat -f %m` → `[DateTimeOffset]::new((Get-Item X).CreationTimeUtc).ToUnixTimeSeconds()`；释放 `rm -rf X` → `Remove-Item -Recurse -Force` | 「PowerShell 把 `2>/dev/null` 解析成写 `E:\dev\null`，命令必然失败」 | ❌ 未解决 —— 命令仍从未被执行 |
| **v2** | 2026-10-14 23:40 | — | 给每个 shell 调用**显式传沙箱策略** `{ mode: 'danger-full-access', workspaceRoot }` | 「插件属『直接调用』，不传策略就落到部署默认 `read-only`，取锁被拒」 | ❌ 未解决 |
| **v3** | 2026-10-15 00:04:02 | `index.js.bak-v3-20261015-000402`（86014 字节，sha256 前 16 位 `8f5660eee66038ad`） | 加 shell **兼容层**：有原生 `run` 用原生，否则 `resolve → execute → result` 组合 | 「DSH 的 shell 服务只有 `resolve` + `execute`，**没有 `run`**；插件调 `shell.run(...)` → `TypeError: shell.run is not a function`」（靠临时诊断日志 `kanban-persist-error.log` 才抓到） | ⚠️ 症状改变：从 `TypeError` 变成 `state file lock timeout` |
| **v4** | 2026-10-15 00:09:26 | `index.js.bak-v4-20261015-000926`（86493 字节，sha256 前 16 位 `3cbcbc5f8182952d`） | **文件锁改用 `node:fs`**（`mkdirSync` 取锁 / `statSync` 判陈旧 / `rmSync` 释放），落盘先试 `ctx.fs.writeText` + 显式策略，失败回落到 `node:fs` 原子写（tmp + rename） | 「插件上下文的 shell 调用在本机取不到锁」——Node 内置 fs 没有沙箱策略/命令方言/API 版本这三层中间态 | ⏳ 待定（见下） |

当前磁盘状态（实测，只读）：

```
index.js                          86493  2026-10-15 00:09:26  sha256:3cbcbc5f8182952d
index.js.bak-v4-20261015-000926   86493  2026-10-15 00:09:26  sha256:3cbcbc5f8182952d  ← 与线上完全一致，即「线上就是 v4」
index.js.bak-v3-20261015-000402   86014  2026-10-15 00:04:02  sha256:8f5660eee66038ad
```

## 二、v4 的当前验证状态（**部分已验证，不能算定论**）

**已经拿到的正面事实：**

1. 宿主进程组当前启动时间 **2026-10-15 00:18:37**，晚于 v4 写盘（00:09:26）
   → 当前进程里装载的就是 v4 代码（磁盘一致，见上表哈希）。
2. 诊断日志 `E:\Works\DPT\.dsh\kanban-persist-error.log` 的**最后一条仍是 00:17:24**
   → 00:18:37 重启之后 **12 分钟内零新增失败**。
3. `E:\Works\DPT\.dsh\kanban-state.json` 在 **00:25:40 被成功写入**（`version=46`）
   → 落盘链路在 v4 下**确实跑通过至少一次**。
4. `.dsh\kanban.lock` **当前不存在**（没有残留锁把后续写入钉死）。
5. 读路径实测可用：`kanban_list_issues` 返回 6 条真实议题。

**还不能定论的地方（必须诚实标注）：**

- 00:09:26（v4 写盘）到 00:18:37（重启）之间，还有 **5 条 `state file lock timeout`**
  （00:13:52 / 00:14:12 / 00:15:34 / 00:15:51 / 00:17:24，调用栈全部指向 v4 的 `withFileLock` 第 226 行）。
  由于 profile 里 `patchReload: "live"` 且 `hmr` 行 active，这段时间**可能**已经通过热重载跑上了 v4 代码——
  但热重载是否真的替换了运行实例，本议题内**无法零副作用取证**。因此：
  **这 5 条超时到底属于 v3 还是 v4，属「未定」。**
- 重启后的成功写入样本只有 **1 次**，且没有并发压测，不足以证明「并发 persist 自锁」这条路径已经健康。

**结论：v4 = 部分已验证。** 要给出定论，需要**一次受控启动**，并把 `persistDiag()` 从只记 `error.message`
扩成同时记录：`result.exitCode / stderr.text / result.sandbox{denied,runnerFailed} / 实际命令行`。
→ 该动作按本议题规则**挂起，标注 `待 k-mv8ak8zi-4`**；本议题内零重启。

## 三、这条缺陷为什么值得单列

它是本议题的立案理由，也是最典型的一种失败形态：

> **`enabled=true` / `fiberPhase=active` / 界面能开、能建议题、能拖状态 —— 但核心落盘从安装第一天起就是死的。**

失败链条上每一环都「看起来正常」：

1. **接口名错**（`shell.run` 不存在）→ 旧 API 沿用，无编译期/加载期检查；
2. **异常被吞**（`catch (e) { console.error(...) }`）→ 主进程的 `console.error` 无人接收，坏了没人知道；
3. **缺少沙箱策略**（不传 `sandboxPolicy`）→ 落到部署默认 `read-only`，写入被拒；
4. **命令方言**（POSIX 专用 shell 语法）→ 在 Windows PowerShell 下必然失败；
5. **静默降级**（`typeof X.get === 'function'` 之类的守卫）→ 不抛异常，但分支永不生效。

第 5 条不是 task-board 的问题，而是 **dsh-cost-meter** 的问题（见缺陷清单 #1）——
它证明这不是孤例，而是一类系统性风险。

## 四、顺带记录：健康扫描把「仍在运行的执行子代理」打回待执行（**观察，非缺陷结论**）

`kanban-state.json` 里本议题 `k-mv8b6x0z-6` 的 activity 原文（UTC，+8 = 本机）：

| UTC 时刻 | 本机 | 事件 |
| --- | --- | --- |
| 16:20:14.186Z | 00:20:14 | `user`：backlog → todo |
| 16:20:14.355Z | 00:20:14 | `system`：todo → **in_progress**（派发成功并落盘） |
| 16:25:40.754Z | 00:25:40 | `system`：in_progress → **todo**（本议题被打回） |

- 间隔 5 分 26 秒，与源码里的 `STALE_EXEC_MS = 5 * 60 * 1000`（「5 分钟无进展即视为卡死」）+ `HEALTH_SCAN_MS = 60s` 完全吻合。
- 而此刻**子代理仍在正常运行**（本报告正在被它写出来）。
- 同时存在：`autoExec.enabled = true`（intervalSec 60 / concurrency 3），且批次
  `batch-mv8bg043-1496` 的 `status` 仍是 `"running"`、`finishedAt: null`，而它的 `issueIds` 里唯一那条
  已经被打回 `todo`。

**风险事实（不改，只报告）**：一个仍在跑的执行被判定为「卡死」，在自动执行开启时存在**重复派发**的可能。
**影响面**：同一议题两个执行体写同一个 `vk/<id>` 分支 → 分支冲突/重复提交。
**处置建议**：健康扫描的「卡死」判据应至少满足一条硬性条件（子代理失活 / 超时上限远大于 5 分钟），
或把「子代理存活」作为**充分条件**直接豁免；具体改法由用户决定。
**本议题不做**：不关开关、不改状态、不重启 —— `autoAccept` / `autoExec` 都是用户手动设置的状态。
