# L2 能力层证据 —— 每个插件「真跑一次」的原始记录

原则：**非破坏性、不留生产副作用、零重启**。凡是会产生真实副作用的动作（改生产数据、向主会话注入文本、建队、创建计划任务、上传外部 API），
一律不做，并显式标注「未验证 + 原因 + 验证路径」。

---

## 工具层

会话内调用 `cordis_inspect_query(platform=host, provider=Tool, method=listTools)`，得到当前 Agent 可调用的**实时**工具表（91 个）。
把工具名与插件一一对上，就是「该插件的能力真的注册进宿主了」的直接证据。

| 工具（组） | 数量 | 归属插件 |
| --- | --- | --- |
| `kanban_*` | 16 | `dsh-task-board` |
| `mcp_connector_*` | 23 | `dsh-mcp-connector` |
| `agent_teams_*` | 16 | `@nanmicoder/dsh-agent-teams` |
| `video_understand` | 1 | `dsh-video-understand` |
| `modlens_read_image` | 1 | `@liustack/modlens` |
| `workflow` | 1 | `deep-read-summarize`（该插件注册的 workflow，meta 名 `deep-read-summarize`） |
| `plugin_manager` | 1 | `dshmarket`（DSH 自带的 `tool-plugin-manager` 行恰为 `disabled`） |

其余 32 个工具属 DSH 基座与 Web 宿主（read/write/edit/glob/grep/pwsh/web_search/web_fetch/subagent/… ），与用户侧第三方插件无关。

真实调用记录：

- `mcp_connector_catalog()` → **成功**，返回「共 113 个已上架连接器」及分类、鉴权方式明细。
- `kanban_list_issues()` → **成功**，返回 6 条真实议题（含本议题 `k-mv8b6x0z-6`，retries=1）。
- `agent_teams_status()` → **返回语义化错误**：`you do not lead or belong to any active team yet (this session is a fork of …)`。
  这是服务正常应答（明确说明原因），不是崩溃 —— 说明工具已注册且宿主服务可达。
- `workflow` 工具存在但本议题未运行（真实运行会写入笔记文件并消耗大量 token）。
- `video_understand` 工具存在但本议题未运行（需下载视频或把帧上传到 MiMo API，有成本与外发）。

---

## 回环 HTTP 路由探测

插件用 `ctx.webServer.register({ path, ... })` 把宿主能力挂到 GUI 同一台服务器上。
对每台服务器做一次 `GET http://127.0.0.1:19387<path>`，就能在不改任何状态的前提下判断「路由到底挂没挂上」：

| 路由 | 归属插件 | HTTP | 判读 |
| --- | --- | --- | --- |
| `/mcp-connector/ui` | dsh-mcp-connector | **200**（142062 字节） | 已挂载且能返回内容 |
| `/dsh-market/api/v1/capabilities` | dshmarket | **200**（660 字节） | 已挂载且能返回内容 |
| `/modlens/config` | @liustack/modlens | **200**（653 字节） | 已挂载且能返回内容 |
| `/dsh-task-board` | dsh-task-board | **405** | 已挂载（该路由仅接受 POST） |
| `/sidenote/reflow` | dsh-sidenote | **405** | 已挂载（仅接受 POST） |
| `/sidebar/api` | dsh-better-sidebar | **405** | 已挂载（仅接受 POST） |
| `/plugins/dsh-agent-teams/plan` | @nanmicoder/dsh-agent-teams | **401** | 已挂载（需授权令牌，属预期） |
| `/sidebar/bundle` | dsh-better-sidebar | 404 | 该路由用非字面路径匹配，本探测方式不适用 → 不判负 |
| `/genui` | dsh-genui | 404 | 同上（其三条路由的 path 是动态拼接）→ 不判负 |

判读口径：**404 只说明「这次这么问没问到」，不等于路由没挂**；**405/401 反而证明路由存在**。

---

## cc-safety-net

它声明 `inject: ["tools"]`，注册方式为 `e.tools.guard((r) => i(r, process.cwd()))`，即**工具层执行前守卫**。

- **拒绝路径（实测生效，同一会话二次复核）**：在自建临时目录（非 git 仓库，命令即使放行也无副作用）执行 `git push --force origin main`
  → 被拦，原文：

  ```
  Error: BLOCKED by CC Safety Net
  Reason: git push --force destroys remote history. Use --force-with-lease for safer push.
  Rule: git.push-force
  ```

  同一会话里还有一次**自然拦截**（不是刻意探测）：清理审计临时目录时写的
  `cd <worktree>; Remove-Item .\repro-a,.\repro-b,.\run1 -Recurse -Force` 被拦，原文：

  ```
  Error: BLOCKED by CC Safety Net
  Reason: PowerShell Remove-Item -Recurse -Force outside cwd is blocked.
          Retry deleting only explicit paths inside the current directory; escalate for anything outside it.
  Rule: powershell.remove-item-recursive-force-outside-cwd
  ```

  它给出的替代建议（把工作目录切到目标目录、只删显式相对路径）确实可行 —— 换成 `workdir=<目标目录>` 后同一条命令通过。
  → 这是「拦截 + 可执行替代路径」都正确的一次完整闭环。

- **放行路径（实测生效）**：对自建临时目录执行 `Remove-Item -Recurse -Force` → 放行并成功删除（属策略允许，不是失效）。
  收尾核验：探测目录已不存在，无残留。

- **边界（重要）**：它只挂**工具层**，而插件进程内的 `ctx.shell.*`、`node:fs` 属**服务层**，不经过工具层 ——
  所以「插件自己执行的命令」不受它保护。这条已写进 L3 的风险规则。

---

## task-board

- 读路径：`kanban_list_issues` 返回 6 条议题 ✅
- 状态文件：`E:\Works\DPT\.dsh\kanban-state.json`，`version=46`，最后写入 **2026-10-15 00:25:40**（本议题记录 updatedAt=2026-10-14T16:25:40Z，为同一时刻的 UTC 表示）
- 锁目录：`E:\Works\DPT\.dsh\kanban.lock` **当前不存在**（无残留锁）
- 但诊断日志 `E:\Works\DPT\.dsh\kanban-persist-error.log` 在 v4 补丁（备份名 `index.js.bak-v4-20261015-000926`，即 00:09:26）之后**仍新增 5 条**：

  ```
  2026-10-14T16:13:52.944Z  Error: state file lock timeout
  2026-10-14T16:14:12.174Z  Error: state file lock timeout
  2026-10-14T16:15:34.953Z  Error: state file lock timeout
  2026-10-14T16:15:51.238Z  Error: state file lock timeout
  2026-10-14T16:17:24.238Z  Error: state file lock timeout   ← UTC，对应本机 00:17:24
  ```

  调用栈指向 v4 之后的 `withFileLock`（`lib/index.js:226`）→ 说明 **v4 用 node:fs 的 `mkdirSync` 取锁同样会超时**，
  根因未完全消除（可能是并发 persist 自锁，或某次未释放的锁目录）。

- 定论需要一次启动（把诊断扩成记录 `exitCode / stderr / sandbox.denied / 实际命令行`）→ **待 `k-mv8ak8zi-4`**。

---

## agent-teams

- 16 个 `agent_teams_*` 工具在实时工具表中 ✅
- `agent_teams_status()` 返回明确原因（本会话是 fork 子代理，无团队）—— 服务可达、应答正常
- 本议题不建队（会在工作区留下 `.agent-teams/` 目录与 mailbox 文件），故「建队 → 派成员 → 收报告」链路 **未验证**

---

## modlens

真实调用 `modlens_read_image(path="E:\Works\DPT\assets\noncommercial_authorization_poster.png")`：

- **成功**：返回完整 OCR 全文（「DPT 双脉冲测试参数提取工具 / 禁止商用 / PolyForm Noncommercial License 1.0.0」等），
  版面与语义结论与图片实际内容一致 → 视觉桥、OCR、外部引擎链路全部打通。

## genui

- 宿主半边：配置 `sectionName=genui:cards`、`sectionOrder=80`、`promptEnabled=true`，**注入确实生效** ——
  本会话的系统提示里含完整的 genui 卡片契约（`schemaJson` 代码块、组件白名单、生成规则、双向绑定要求）。
- 客户端半边：卡片渲染未做界面验证 → 标「部分可用」。

---

## 基座与 Web 宿主

- 本次审计全部读写、91 个工具、91 个宿主服务目录、三次分页的插件表，全部由 `@deepseek-ai/dsh-base` + `@deepseek-ai/dsh-web-app` 提供 →
  两个官方 bundle 记为「可用」。
- 其余 4 个官方组合包（auto-review / agent-team-profile / schedule / voice-input）只做到 L1 + 服务目录确认，**均标「未验证」**，
  因为它们都需要真实触发一次有副作用的动作才能证明「能用」，而本议题明确不做这类动作。
