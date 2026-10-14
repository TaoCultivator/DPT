# L2 能力层证据 —— 每个插件「真跑一次」的原始记录

原则：**非破坏性、不留生产副作用、零重启**。凡是要真实副作用才能验证的动作（改生产数据、向主会话注入文本、
建队、创建计划任务、上传外部 API、开麦克风），一律不做，并显式标注「未验证 + 原因 + 验证路径」。

本文件为**复核轮（2026-10-15 01:0x–01:2x）重新采集**；首轮（00:2x）的同类证据已被本轮覆盖。

---

## 一、工具层：能力真的注册进宿主了吗

`cordis_inspect_query(platform=host, provider=Tool, method=listTools)` → **实时工具表 91 条**（本轮实测）。
把工具名与插件对上，就是「该插件的宿主能力确实注册了」的直接证据：

| 工具组 | 条目数 | 归属插件 |
| --- | --- | --- |
| `kanban_*` | **14** | `dsh-task-board` |
| `mcp_connector_*` | **24** | `dsh-mcp-connector` |
| `agent_teams_*` | **14** | `@nanmicoder/dsh-agent-teams` |
| `team_task_*` | **4** | AgentTeams 的任务板（同一家族） |
| `plugin_manager` | 1 | `dshmarket`（DSH 自带的 `tool-plugin-manager` 行恰为 `disabled`） |
| `video_understand` | 1 | `dsh-video-understand` |
| `modlens_read_image` | 1 | `@liustack/modlens` |
| `workflow` | 1 | `deep-read-summarize`（注册的 workflow，meta 名即插件名） |

> **口径更正**：首轮记录写的是「kanban 16 / mcp_connector 23 / agent_teams 16」，
> 本轮按工具名去重重新点数，实际是 **14 / 24 / 14**。首轮数字没有可复现的计数口径，已作废。

真实调用记录（本轮）：

- `kanban_list_issues()` → **成功**，返回 6 条真实议题（含本议题 `k-mv8b6x0z-6`，`in_progress`）。
- `mcp_connector_catalog()` → **成功**，返回「共 113 个已上架连接器」及分类/鉴权方式明细。
- `mcp_connector_status()` → **成功**，返回「共 0 条连接」—— 插件正常应答，本机**尚未配置任何 MCP 连接**（用户未用，不是故障）。
- `agent_teams_status()` → **返回语义化错误**：`you do not lead or belong to any active team yet (this session is a fork of …)`。
  服务正常应答（明确说明原因），不是崩溃 → 工具已注册且宿主服务可达。
- `modlens_read_image(path=<仓库内 PNG>)` → **成功**（本轮复跑），返回完整文字转写：
  「DPT 双脉冲测试参数提取工具 / 禁止商用 / PolyForm Noncommercial License 1.0.0 …」+ 版面与语义结论，
  与图片实际内容一致 → 视觉桥、OCR、外部引擎链路全部打通。
- `workflow`（deep-read-summarize）与 `video_understand`：**未运行**。
  前者会产出笔记文件并消耗大量 token，后者需下载视频或把帧上传 MiMo API（有成本与外发）。
  两者在实时工具表中存在且参数契约完整 → 记「部分可用」。

## 二、回环 HTTP 路由探测（本轮重新实测）

插件用 `ctx.webServer.register({ path, ... })` 把宿主能力挂到 GUI 同一台服务器。
对 `http://127.0.0.1:19387` 做一次 GET，就能在不改任何状态的前提下判断「路由挂没挂上」：

| 路由 | 归属插件 | HTTP | 判读 |
| --- | --- | --- | --- |
| `/mcp-connector/ui` | dsh-mcp-connector | **200**（142,062 字节） | 已挂载且能返回内容 |
| `/dsh-market/api/v1/capabilities` | dshmarket | **200**（660 字节） | 已挂载且能返回内容 |
| `/modlens/config` | @liustack/modlens | **200**（653 字节） | 已挂载且能返回内容 |
| `/dsh-task-board` | dsh-task-board | **405**（43 字节） | 已挂载（仅接受 POST） |
| `/sidenote/reflow` | dsh-sidenote | **405**（41 字节） | 已挂载（仅接受 POST） |
| `/sidebar/api` | dsh-better-sidebar | **405**（75 字节） | 已挂载（仅接受 POST） |
| `/plugins/dsh-agent-teams/plan` | @nanmicoder/dsh-agent-teams | **401**（24 字节） | 已挂载（需授权令牌，属预期） |
| `/sidebar/bundle` | dsh-better-sidebar | 404（9 字节） | 非字面路径匹配 → 本探测方式不适用，**不判负** |
| `/genui` | dsh-genui | 404（0 字节） | 同上（路由 path 动态拼接）→ **不判负** |

判读口径：**405/401 反而证明路由存在**；404 只说明「这次这么问没问到」。

## 三、cc-safety-net：拦截与放行（本轮实测，含被整条拦下的复合命令）

它 `inject: ["tools"]`、注册为工具层执行前守卫（`e.tools.guard(...)`）。

- **拦截路径 ①（本轮，最干净的一次证据）**：一条**复合命令**里含 `git push --force origin main`，
  被**整条命令**拦下（未执行任何一段），原文：

  ```
  Error: BLOCKED by CC Safety Net
  Reason: git push --force destroys remote history. Use --force-with-lease for safer force push.
  Rule: git.push-force
  Segment: git push --force origin main 2
  ```

  机制要点：守卫是**按整条命令文本**判定的，命中即整体拒绝（不是放行其它段）。
- **拦截路径 ②（本轮）**：`Remove-Item $out -Recurse -Force`（目标是 `%TEMP%` 下、**不在 cwd 内**）被拦：

  ```
  Reason: PowerShell Remove-Item -Recurse -Force outside cwd is blocked.
  Rule: powershell.remove-item-recursive-force-outside-cwd
  ```

  按它给的替代路径（把工作目录切到目标目录、只删显式相对路径）后同命令通过 → **拦截 + 可执行替代路径**闭环正确。
- **放行路径**：在目标目录内、删显式相对路径 → 放行并成功（属策略允许，不是失效）。

- **边界（重要，已写进 L3 风险规则）**：它只挂**工具层**；插件进程内的 `ctx.shell.*`、`node:fs`
  属**服务层**，不经过工具层 —— **插件自己执行的命令不受它保护**。

## 四、task-board（dsh-task-board）：v5 与当前落盘状态

- 读路径：`kanban_list_issues()` 返回 6 条议题 ✅（本轮复跑）。
- 落盘路径（本轮实测）：`.dsh/kanban-state.json` **在 01:01:34 仍是新的**（`version=69`，
  6 条议题状态与我们看到的实时状态一致）→ **写入链路在当前进程里是活的**。
- 诊断日志 `.dsh/kanban-persist-error.log`：**最后一条仍是 00:17:24**（文件 mtime 也是 00:17:24），
  即 **00:32:31 那次外部重启之后零新增失败**（至今 40 分钟以上，期间看板持续在写）。
- `.dsh/kanban.lock` **不存在**（无残留锁）。
- 线上代码 = **v5**（`lib/index.js` 87,168 字节，2026-10-15 00:31:26，sha256 前 16 位 `0DC982AE18BFC56C`）。
- 结论与遗留见 `task-board-ledger.md`（v1→v5 五轮台账 + v4/v5 的验证窗口）。

## 五、agent-teams

- 14 个 `agent_teams_*` + 4 个 `team_task_*` 工具在实时工具表中 ✅
- `agent_teams_status()` 返回明确原因（本会话是 fork 子代理，无团队）—— 服务可达、应答正常
- 本议题不建队（会在工作区留下 `.agent-teams/` 目录与 mailbox 文件）→「建队 → 派成员 → 收报告」链路 **未验证**。

## 六、genui

- 宿主半边：配置 `sectionName=genui:cards`、`sectionOrder=80`、`promptEnabled=true`，**注入确实生效** ——
  本会话的系统提示里含完整的 genui 卡片契约（`schemaJson` 代码块、组件白名单、生成规则、双向绑定要求）。
- 客户端半边：卡片渲染未做界面验证 → 标「部分可用」。

## 七、基座与 Web 宿主

- 本次审计全部读写、91 条工具、91 个宿主服务目录、三次分页的插件表，全部由
  `@deepseek-ai/dsh-base` + `@deepseek-ai/dsh-web-app` 提供 → 两个官方 bundle 记为「可用」。
- 其余 4 个官方组合包（auto-review / agent-team-profile / schedule / voice-input）只做到
  L1（逐 id 比对，见 `l1-rows.md`）+ 服务目录确认 + L4（asar 内包与补丁清单，见 `l4-env.md`），
  **均标「未验证」**：它们都需要真实触发一次有副作用的动作才能证明「能用」，而本议题明确不做。
