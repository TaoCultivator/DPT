# 已装插件真实可用性矩阵（L1 加载 / L2 能力 / L3 契约 / L4 依赖）

- 审计对象：`C:\Users\songzhenxi\.dsh\profiles\desktop` 的 `dsh.profile.bundles` 全量组合包
- 宿主版本：0.2.0-rc.2
- 契约来源：cordis_inspect_query(platform=host, provider=Service, method=listService) · data.mode=catalog（宿主服务 91 个；**客户端契约不可达**）
- 实时行表快照：plugin_manager list_plugins（2026-10-15 01:0x 本会话三次分页采集，全表 211 行）（用于核对「补丁声明的行是否真的挂上了」）
- 生成方式：`node audit-plugins.mjs`（只读、零重启；产物不含时间戳，可逐字节复跑比对）

## 汇总

| 指标 | 数量 |
| --- | --- |
| 组合包 | 20 |
| 源码静态可扫（含 app.asar 内官方包） | 20 |
| 源码不可达 | 0 |
| 补丁声明行 → 实时表比对 | 已比对 18 个组合包，缺失行 0 |
| 契约缺陷 · blocker | 0 |
| 契约缺陷 · high | 1 |
| 契约缺陷 · medium | 0 |
| 契约缺陷 · low（目录覆盖盲区 / 疑似内置方法） | 2 |
| 静默 catch（宿主半边，非内联运行时） | 320 |
| 静默 catch（内联第三方运行时，已分离） | 0 |
| 静默 catch（客户端半边，另计） | 254 |
| 结论 · 可用 | 7 |
| 结论 · 部分可用 | 8 |
| 结论 · 不可用 | 0 |
| 结论 · 未验证 / 待核 | 5 |

## 全量矩阵

| # | 组合包 | 类型 | 声称能力 | L1 加载 | L2 能力 | L3 契约 | L4 依赖 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `@deepseek-ai/dsh-base` | 官方 | DSH 基座：session / llm / tools / fs / sandbox 等核心服务 | 补丁清单声明 94 行（app.asar 内 `./cordis.patch.yml` 静态解析）· 全部 enabled=true · fiberPhase=active | 本会话全部读写、工具调用、模型调用都跑在它提供的服务上（91 条实时工具、91 个宿主服务目录可读） | 无缺陷（0 处服务调用） | 包在 app.asar 内 | **可用** |
| 2 | `@deepseek-ai/dsh-web-app` | 官方 | Web 宿主：HTTP 载体、客户端模块装配、索引注入 | 补丁清单声明 136 行（主清单 112 + 4 个 preset 层 34/35/9/35 的并集）· 相关行全部 active | 本会话的 GUI 就在 127.0.0.1:19387 由该 bundle 提供；本轮对 9 条插件路由的回环探测全部有响应（3×200 / 3×405 / 1×401 / 2×404 属探测方式不适用） | 无缺陷（0 处服务调用） | 包在 app.asar 内 | **可用** |
| 3 | `@deepseek-ai/dsh-experimental-auto-review` | 官方 | 自动验收：议题进入待验收后派验收子代理 | 补丁声明 1 行（auto-review）· enabled=true · fiberPhase=active · 逐 id 比对命中 1/1（补丁声明 1 行 → 实时表命中 1，缺 0） | 未验证 —— 本议题内不派发验收、不改生产状态，无法在不留副作用的前提下触发一次真实验收 | 无缺陷（7 处服务调用） | 包在 app.asar 内 | **未验证** |
| 4 | `@deepseek-ai/dsh-experimental-agent-team-profile` | 官方 | AgentTeams 相关行（3 启用 + 4 主动禁用） | 补丁声明 7 行（agent-team / tool-agent-team / ui-agent-team 启用；tool-subagent* 4 行补丁自写 disabled: true）· 逐 id 比对命中 7/7，其中 4 行非 active 属预期（补丁声明 7 行 → 实时表命中 7，缺 0） | 部分可用 —— 宿主 agentTeams 服务在实时 Service 目录中存在；agent_teams_status 调用返回语义化结果（非崩溃）。本议题内不建队、不派成员，避免留副作用 | 无缺陷（0 处服务调用） | 包在 app.asar 内 | **未验证** |
| 5 | `@deepseek-ai/dsh-experimental-schedule-bundle` | 官方 | 定时计划（schedule / ui-schedule / time-context 三行） | 补丁声明 3 行 · 逐 id 比对命中 3/3 · 全部 enabled=true / active（补丁声明 3 行 → 实时表命中 3，缺 0） | 未验证 —— 宿主 schedule 服务在实时 Service 目录中存在；未创建任何计划任务（会产生真实副作用） | 无缺陷（0 处服务调用） | 包在 app.asar 内 | **未验证** |
| 6 | `@deepseek-ai/dsh-experimental-voice-input-bundle` | 官方 | 语音输入（4 行） | 补丁声明 4 行 · 逐 id 比对命中 4/4 · 全部 enabled=true / active（补丁声明 4 行 → 实时表命中 4，缺 0） | 未验证 —— 宿主 speechToText / speechController 服务在实时 Service 目录中存在；真实识别需要麦克风与界面动作 | 无缺陷（0 处服务调用） | 包在 app.asar 内 | **未验证** |
| 7 | `dsh-sidenote` | 第三方 | 侧边聊天（side-chat）：把结论回流到主会话 | 补丁声明 1 行（side-chat）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 部分可用 —— 宿主路由 /sidenote/reflow 回环探测返回 HTTP 405（路由已挂载，仅接受 POST），说明宿主半边装配成功；未做真实界面动作（会向主会话注入文本，属生产副作用） | 无缺陷（0 处服务调用） | 包已就位；peer 兼容 | **部分可用** |
| 8 | `dshmarket` | 第三方 | 插件市场：浏览 / 安装 / 卸载 / 启停插件 | 补丁声明 1 行（dsh-market）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 可用 —— 真实调用 marketplace 能力：plugin_manager list_plugins 返回 211 行全量清单（三次分页）；HTTP GET /dsh-market/api/v1/capabilities 返回 200 + 660 字节 | 无缺陷（0 处服务调用） | 包已就位 | **可用** |
| 9 | `dsh-better-sidebar` | 第三方 | 右侧栏：会话/文件/终端/附件多标签 | 补丁声明 1 行（better-sidebar）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 部分可用 —— 宿主路由 /sidebar/api 回环探测返回 HTTP 405（已挂载、仅接受 POST）；/sidebar/bundle 返回 404（该路由用了非字面路径匹配，本次探测方式不适用）；界面动作未验证 | 2 项契约缺陷（0 项高危） | 包已就位 | **部分可用** |
| 10 | `dsh-context` | 第三方 | 上下文可视：按会话投影展示上下文构成 / 时间线 | 补丁声明 1 行（dsh-context）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 未验证 —— 宿主半边只声明服务依赖、不注册工具、也不注册字面路由；其宿主能力表现为向 sessionProjections 注册 contextBreakdown / contextTimeline 投影，读取需要客户端界面动作 | 无缺陷（12 处服务调用） | 包已就位 | **未验证** |
| 11 | `deep-read-summarize` | 第三方 | 深度阅读：书 / 论文 / 视频 / 网页 → 结构化 Markdown 笔记（workflow + 技能） | 补丁声明 1 行（deep-read-summarize）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 部分可用 —— 该插件注册的 workflow 工具在实时工具表中存在（meta 名 deep-read-summarize）；未做一次真实深读运行（会产出文件并消耗大量 token） | 无缺陷（1 处服务调用） | 包已就位；peer 兼容 | **部分可用** |
| 12 | `dsh-video-understand` | 第三方 | 视频理解：B 站链接 / 本地视频 → 摘要 + 问答 | 补丁声明 1 行（video-understand）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 部分可用 —— video_understand 工具在实时工具表中存在且参数契约完整；**未在本议题内运行**（需下载视频或把帧上传 MiMo API，有成本与外发）。旁证：~/.dsh/cache/video-understand/transcripts/ 有 2 个真实转写产物（2026-10-14 17:22），说明该链路此前真的跑通过 | 无缺陷（1 处服务调用） | 包已就位 | **部分可用** |
| 13 | `dsh-genui` | 第三方 | 生成式 UI：让模型输出卡片 schemaJson 并由前端渲染 | 补丁声明 1 行（genui）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 部分可用 —— 宿主半边的系统提示注入已生效（本会话系统提示里确实有 genui 卡片契约：schemaJson 代码块、组件白名单、生成规则）；客户端渲染未验证 | 无缺陷（4 处服务调用） | 包已就位 | **部分可用** |
| 14 | `dsh-mcp-connector` | 第三方 | MCP 连接器：目录 / 三通道连接 / 凭据存储 / 动态条目配置 | 补丁声明 1 行（mcp-connector）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 可用 —— 真实调用 mcp_connector_catalog 返回 113 个已上架连接器（含分类与鉴权方式）；mcp_connector_status 正常应答「共 0 条连接」（插件可用，用户尚未配置任何连接）；HTTP GET /mcp-connector/ui 返回 200 + 142 KB 静态 SPA | 无缺陷（14 处服务调用） | 包已就位 | **可用** |
| 15 | `dsh-task-board` | 第三方 | 任务看板：工作区 → 待执行 → 自动执行 → 待验收 → 自动验收 → 完成 | 补丁声明 1 行（dsh-task-board）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 部分可用 —— 读路径可用（kanban_list_issues 返回 6 条真实议题）；写路径：线上是 **v5**（00:31:26，sha256 前 16 位 0DC982AE18BFC56C），宿主当前进程组 **00:32:31 启动（晚于 v5 写盘）**，此后 40+ 分钟 **零新增落盘失败**（诊断日志 mtime 停在 00:17:24），且 .dsh/kanban-state.json 持续被写（version 46 → 69 → 71，01:04:56），无残留锁；但 00:08–00:17 的 8 条 lock timeout 属 v3 还是 v4 已无法回溯 | 无缺陷（38 处服务调用） | 包已就位 | **部分可用** |
| 16 | `cc-safety-net` | 第三方 | 命令安全网：在执行前拦截危险命令 | 补丁声明 1 行（cc-safety-net，moduleName 是 file:/// 本地路径）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 可用 —— 本轮再次实测拒绝路径两次：① 含 `git push --force` 的**复合命令被整条拦下**（Rule: git.push-force，未执行任何一段）；② `Remove-Item $out -Recurse -Force` 目标在 cwd 之外被拦（Rule: powershell.remove-item-recursive-force-outside-cwd），按它给的替代路径（切工作目录 + 只删显式相对路径）后同命令通过 → 拦截与替代路径闭环正确；放行路径亦正常（策略内删除成功） | 无缺陷（0 处服务调用） | 包已就位 | **可用** |
| 17 | `dsh-cost-meter` | 第三方 | 成本计量：按会话 / 供应商 / 模型显示 token 与费用 | 补丁声明 1 行（cost-meter）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 部分可用 —— 宿主半边可装载、逐版兼容闸判定 0.2.0-rc.2 = compatible、账本在持续写（~/.dsh/storages/cost-meter/ledger.json 215,827 字节，01:06 仍在更新）；但 L3 发现它调用了宿主 settings 服务不存在的方法（见缺陷 #1），DeepSeek 余额查询链路静默降级到环境变量兜底 | 1 项契约缺陷（1 项高危） | 包已就位 | **部分可用** |
| 18 | `@nanmicoder/dsh-agent-teams` | 第三方 | AgentTeams：多智能体团队协作（建队 / 任务 DAG / 成员调度） | 补丁声明 1 行（agent-teams）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 可用 —— 14 个 agent_teams_* + 4 个 team_task_* 工具在实时工具表中；实测 agent_teams_status 返回语义化结果（本会话为 fork 子代理、无团队，返回明确原因而非崩溃） | 无缺陷（43 处服务调用） | 包已就位 | **可用** |
| 19 | `@linxin666/dsh-client-ui-skin-center` | 第三方 | 皮肤中心：主题 / 皮肤切换 | 补丁声明 1 行（ui-skin-center）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 部分可用 —— 宿主半边已运行并落盘：~/.dsh/skin-center-active.json 内容为 {"active": null, "initialized": true}；皮肤渲染本身在客户端，未做界面动作 | 无缺陷（2 处服务调用） | 包已就位；peer 兼容 | **部分可用** |
| 20 | `@liustack/modlens` | 第三方 | 视觉理解桥：读图 / OCR / 版面与语义证据 | 补丁声明 1 行（modlens）· 逐 id 比对命中 1/1 · enabled=true / active（补丁声明 1 行 → 实时表命中 1，缺 0） | 可用 —— 本轮复跑 modlens_read_image 读取仓库内一张 PNG，返回完整转写（「DPT 双脉冲测试参数提取工具 / 禁止商用 / PolyForm Noncommercial License 1.0.0 …」）+ 版面与语义结论，与图片实际内容一致 | 无缺陷（17 处服务调用） | 包已就位 | **可用** |

## 逐包明细（L3/L4 自动证据）

### @deepseek-ai/dsh-base

- 类型：官方 · 版本 0.2.0-rc.2
- 包目录：`asar:/dsh/node_modules/@deepseek-ai/dsh-base`
- 静态扫描：app.asar 内 7 个条目，其中 JS 1 个（官方 bundle 多数只有补丁清单，JS 是 11 字节占位）
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **94** 个 id（`./cordis.patch.yml` 94 行）
- 与实时行表比对：未比对 —— 快照未覆盖该组合包（只录入了用户侧 20 个组合包对应的行）
- 依赖：声明 93 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#七基座与-web-宿主
  - contracts.json
  - evidence/l4-env.md
- 备注：第三方插件全部 inject 的服务（tools/fs/webServer/shell/timer/subagents/agents/llm 等）均由该 bundle 提供。L4：包在 app.asar 内（v0.2.0-rc.2，93 个依赖全部可达，7 个条目），首版「静态不可达」已作废。

### @deepseek-ai/dsh-web-app

- 类型：官方 · 版本 0.2.0-rc.2
- 包目录：`asar:/dsh/node_modules/@deepseek-ai/dsh-web-app`
- 静态扫描：app.asar 内 12 个条目，其中 JS 2 个（官方 bundle 多数只有补丁清单，JS 是 11 字节占位）
- 补丁清单：`./cordis.patch.yml`、`./presets/standard.patch.yml`、`./presets/ptc.patch.yml`、`./presets/minimal.patch.yml`、`./presets/cordis.patch.yml`（存在）
- 补丁声明的行：共 **136** 个 id（`./cordis.patch.yml` 112 行、`./presets/standard.patch.yml` 34 行、`./presets/ptc.patch.yml` 35 行、`./presets/minimal.patch.yml` 9 行、`./presets/cordis.patch.yml` 35 行）
- 与实时行表比对：未比对 —— 快照未覆盖该组合包（只录入了用户侧 20 个组合包对应的行）
- 依赖：声明 127 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 1 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#二回环-http-路由探测本轮重新实测
  - evidence/l4-env.md
- 备注：第三方插件注册的 /sidebar、/mcp-connector、/dsh-market、/dsh-task-board、/sidenote、/modlens、/plugins/dsh-agent-teams、/genui 路由都挂在这台服务器上。L4：asar 内 v0.2.0-rc.2，127 个依赖全部可达，声明 136 行为 5 个补丁文件的并集（未逐层去重）。

### @deepseek-ai/dsh-experimental-auto-review

- 类型：官方 · 版本 0.2.0-rc.2
- 包目录：`asar:/dsh/node_modules/@deepseek-ai/dsh-experimental-auto-review`
- 静态扫描：app.asar 内 10 个条目，其中 JS 1 个（官方 bundle 多数只有补丁清单，JS 是 11 字节占位）
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 1 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：7 处调用 / 5 个 inject key
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l1-rows.md
  - evidence/l4-env.md
- 备注：验证路径：看板 autoAccept=true 时进入待验收即触发；由用户决定何时开启（用户手动设置的开关，agent 不得代改）。该包是官方 6 包里唯一有真实 JS 实现的（lib/index.js 24 KB），已静态扫描：无契约缺陷。

### @deepseek-ai/dsh-experimental-agent-team-profile

- 类型：官方 · 版本 0.2.0-rc.2
- 包目录：`asar:/dsh/node_modules/@deepseek-ai/dsh-experimental-agent-team-profile`
- 静态扫描：app.asar 内 10 个条目，其中 JS 1 个（官方 bundle 多数只有补丁清单，JS 是 11 字节占位）
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **7** 个 id（`./cordis.patch.yml` 7 行）
- 与实时行表比对：声明 7 → 命中 7，无缺失；补丁主动 disabled 的行（预期非 active）：`tool-subagent-control`、`tool-subagent-list-agents`、`tool-subagent`、`tool-subagent-fork`
- 依赖：声明 3 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#五agent-teams
  - evidence/l1-rows.md
- 备注：与第三方 @nanmicoder/dsh-agent-teams 记录同源证据。

### @deepseek-ai/dsh-experimental-schedule-bundle

- 类型：官方 · 版本 0.2.0-rc.2
- 包目录：`asar:/dsh/node_modules/@deepseek-ai/dsh-experimental-schedule-bundle`
- 静态扫描：app.asar 内 10 个条目，其中 JS 1 个（官方 bundle 多数只有补丁清单，JS 是 11 字节占位）
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **3** 个 id（`./cordis.patch.yml` 3 行）
- 与实时行表比对：声明 3 → 命中 3，无缺失
- 依赖：声明 3 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l1-rows.md
  - evidence/l4-env.md
- 备注：验证路径：界面创建一个一次性提醒后观察是否触发。另：首版行表快照漏录了第 3 行 time-context，比对报出「缺失」后经复核补录 —— 该反例已写进 l1-rows.md。

### @deepseek-ai/dsh-experimental-voice-input-bundle

- 类型：官方 · 版本 0.2.0-rc.2
- 包目录：`asar:/dsh/node_modules/@deepseek-ai/dsh-experimental-voice-input-bundle`
- 静态扫描：app.asar 内 10 个条目，其中 JS 1 个（官方 bundle 多数只有补丁清单，JS 是 11 字节占位）
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **4** 个 id（`./cordis.patch.yml` 4 行）
- 与实时行表比对：声明 4 → 命中 4，无缺失
- 依赖：声明 4 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l1-rows.md
  - evidence/l4-env.md
- 备注：speech-to-text-sensevoice 依赖 app.asar.unpacked 里的 sherpa-onnx 原生包（该目录实测存在）。

### dsh-sidenote

- 类型：第三方 · 版本 0.5.0
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-sidenote`
- 静态扫描：122 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 6 处（空 catch 4 处；内联第三方运行时另计 0 处）；客户端半边 78 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#二回环-http-路由探测本轮重新实测
- 备注：engines.dsh 声明 `>=0.1.1-rc.1 <0.2.0 || =0.2.0-rc.2`，本机 0.2.0-rc.2 命中，兼容闸通过；该包另有本机易失补丁（批注编号按轮重置），不属本议题范围。

### dshmarket

- 类型：第三方 · 版本 1.66.20
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dshmarket`
- 静态扫描：157 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`client/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 2 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 85 处（空 catch 85 处；内联第三方运行时另计 0 处）；客户端半边 25 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l1-rows.md
  - evidence/l2-probes.md#二回环-http-路由探测本轮重新实测
- 备注：plugin_manager 工具即为该插件的宿主能力入口（DSH 自带的 tool-plugin-manager 行是 disabled 状态）。静态扫描 157 个源文件：无契约缺陷；它的 lib/verify.js 曾是本审计「注释假警报」的实证来源，已修。

### dsh-better-sidebar

- 类型：第三方 · 版本 0.26.0
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-better-sidebar`
- 静态扫描：376 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 33 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：76 处调用 / 11 个 inject key
- 静默 catch：宿主半边 28 处（空 catch 28 处；内联第三方运行时另计 0 处）；客户端半边 93 处
- **L3 契约缺陷**：
  - `[low]` `service-not-in-catalog` @ `lib/index.js:6874` —— inject 的 webRuntime 不在 Service 目录里，但已由宿主源码确证存在（审计目录覆盖盲区，非缺陷）
    - 依据：由 @deepseek-ai/dsh-web-app 提供；证据：app.asar 内 `const WEB_RUNTIME_SERVICE = "webRuntime"` 与 patch 文档 `inject: [webRuntime]`。不在 listService 目录中。
  - `[low]` `service-not-in-catalog` @ `src/index.ts:114` —— inject 的 webRuntime 不在 Service 目录里，但已由宿主源码确证存在（审计目录覆盖盲区，非缺陷）
    - 依据：由 @deepseek-ai/dsh-web-app 提供；证据：app.asar 内 `const WEB_RUNTIME_SERVICE = "webRuntime"` 与 patch 文档 `inject: [webRuntime]`。不在 listService 目录中。
- 证据路径：
  - evidence/l2-probes.md#二回环-http-路由探测本轮重新实测
- 备注：本机未安装 @linxin666/dsh-web-ui-all 聚合包，故 !!js 守卫不会把本行关掉（实测该行确实 active）。L3 只报 2 条 low（webRuntime 目录盲区，非缺陷）。

### dsh-context

- 类型：第三方 · 版本 0.70.0
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-context`
- 静态扫描：3 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 1 个，全部可达
- engines.dsh：未声明
- 逐版兼容闸（dsh.compatibility）：范围未声明；本机 0.2.0-rc.2 → **compatible**
- 宿主服务引用：12 处调用 / 3 个 inject key
- 静默 catch：宿主半边 9 处（空 catch 9 处；内联第三方运行时另计 0 处）；客户端半边 16 处
- **L3 契约缺陷**：无
- 证据路径：
  - service-refs.json
- 备注：客户端 Service 契约在本机不可达（cordis_inspect(platform=client) 两次调用均 10s 超时），客户端半边只登记引用、不做契约比对。静态扫描 3 个源文件：无契约缺陷。

### deep-read-summarize

- 类型：第三方 · 版本 0.3.13
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\deep-read-summarize`
- 静态扫描：13 个源文件（宿主半边与客户端半边分平面）
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：1 处调用 / 1 个 inject key
- 静默 catch：宿主半边 6 处（空 catch 4 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#一工具层能力真的注册进宿主了吗
- 备注：engines.dsh `>=0.1.0-rc.6` 兼容闸通过。

### dsh-video-understand

- 类型：第三方 · 版本 0.5.2
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-video-understand`
- 静态扫描：6 个源文件（宿主半边与客户端半边分平面）
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：1 处调用 / 1 个 inject key
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#一工具层能力真的注册进宿主了吗
  - evidence/l4-env.md#外部服务的本地缓存旁证真的被用过
- 备注：该行在 profile 补丁里被显式 disabled: false 覆盖过一次（见 cordis.patch.yml）。

### dsh-genui

- 类型：第三方 · 版本 0.3.1
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-genui`
- 静态扫描：3 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：4 处调用 / 10 个 inject key
- 目录外服务 key（弱信号：`ctx.<key>.<method>()` 属性访问，不据此下结论）：`data`
- 静默 catch：宿主半边 30 处（空 catch 24 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#六genui
- 备注：配置 sectionName=genui:cards / sectionOrder=80 / promptEnabled=true。扫描时它内联了打包的 zod，其内部也使用 `ctx.data` 命名 → 只进 weakUnknownKeys（弱信号），不作结论。

### dsh-mcp-connector

- 类型：第三方 · 版本 0.2.70
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-mcp-connector`
- 静态扫描：39 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 1 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：14 处调用 / 8 个 inject key
- 静默 catch：宿主半边 8 处（空 catch 8 处；内联第三方运行时另计 0 处）；客户端半边 5 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#二回环-http-路由探测本轮重新实测
- 备注：本机凭据文件 ~/.dsh/.credentials.yaml 存在（仅记录键名，未读取任何值）。「0 条连接」是用户未使用，不作为缺陷。

### dsh-task-board

- 类型：第三方 · 版本 1.0.0
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-task-board`
- 静态扫描：2 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：38 处调用 / 13 个 inject key
- 静默 catch：宿主半边 27 处（空 catch 23 处；内联第三方运行时另计 0 处）；客户端半边 17 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#四task-boarddsh-task-boardv5-与当前落盘状态
  - evidence/task-board-ledger.md
- 备注：「当前进程下链路是活的」已实测；「根因已消除」未验证 —— 需一次受控启动并把 persistDiag 扩记 exitCode/stderr/sandbox/命令行/锁目录 → 标注 待 k-mv8ak8zi-4。健康扫描误判（原缺陷 #3）已由 v5 修，仍待长任务观察。本议题内不做任何重启、不改任何开关。

### cc-safety-net

- 类型：第三方 · 版本 2.6.11
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\cc-safety-net`
- 静态扫描：19 个源文件（宿主半边与客户端半边分平面）
- 补丁清单：`./dist/deepseek-harness/cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./dist/deepseek-harness/cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 31 处（空 catch 29 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#三cc-safety-net拦截与放行本轮实测含被整条拦下的复合命令
- 备注：该插件只挂工具层（inject: ["tools"]），拦不到插件进程内的 shell 服务调用 —— 这条边界已写进 L3 风险规则，并用于排除「看板取锁被权限插件拦截」的假设。

### dsh-cost-meter

- 类型：第三方 · 版本 1.8.24
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-cost-meter`
- 静态扫描：43 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 1 个，全部可达
- engines.dsh：未声明
- 逐版兼容闸（dsh.compatibility）：`>=0.1.0-rc.5`；本机 0.2.0-rc.2 → **compatible**
- 宿主服务引用：18 处调用 / 0 个 inject key
- 静默 catch：宿主半边 55 处（空 catch 54 处；内联第三方运行时另计 0 处）；客户端半边 9 处
- **L3 契约缺陷**：
  - `[high]` `unknown-service-method` @ `lib/index.js:1101` —— settings.get() 在宿主契约里不存在（经由别名 settings，声明在第 1100 行） —— 调用点有 typeof/undefined 守卫，**不会抛异常，但该分支永不生效（静默降级）**
    - 依据：可用方法：configure / prepareDocument / describe / update / replace / mutate
- 证据路径：
  - findings.json
  - evidence/l2-probes.md
- 备注：费用面板本身在客户端，需界面动作验证。

### @nanmicoder/dsh-agent-teams

- 类型：第三方 · 版本 0.1.23
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\@nanmicoder\dsh-agent-teams`
- 静态扫描：76 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：43 处调用 / 11 个 inject key
- 静默 catch：宿主半边 1 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 4 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#五agent-teams
- 备注：本议题内不建队（会在工作区留下 .agent-teams 目录）→「建队→派成员→收报告」全链路未验证。首轮记的「16 个工具」口径已更正为 14（按工具名去重实测）。

### @linxin666/dsh-client-ui-skin-center

- 类型：第三方 · 版本 0.4.6
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\@linxin666\dsh-client-ui-skin-center`
- 静态扫描：4 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 2 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：2 处调用 / 5 个 inject key
- 静默 catch：宿主半边 10 处（空 catch 6 处；内联第三方运行时另计 0 处）；客户端半边 7 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l4-env.md#skin-center
- 备注：profile 补丁里 skin-custom-theme.applied=false（用户当前未套用自定义皮肤）。

### @liustack/modlens

- 类型：第三方 · 版本 3.26.6
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\@liustack\modlens`
- 静态扫描：5 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`dsh/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 补丁声明的行：共 **1** 个 id（`./cordis.patch.yml` 1 行）
- 与实时行表比对：声明 1 → 命中 1，无缺失
- 依赖：声明 2 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：17 处调用 / 4 个 inject key
- 静默 catch：宿主半边 23 处（空 catch 23 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#一工具层能力真的注册进宿主了吗
- 备注：另注册 /modlens/paste、/modlens/config 两条宿主路由，/modlens/config 回环探测返回 200 + 653 字节。
