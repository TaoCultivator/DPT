# 已装插件真实可用性矩阵（L1 加载 / L2 能力 / L3 契约 / L4 依赖）

- 审计对象：`C:\Users\songzhenxi\.dsh\profiles\desktop` 的 `dsh.profile.bundles` 全量组合包
- 宿主版本：0.2.0-rc.2
- 契约来源：cordis_inspect_query(platform=host, provider=Service, method=listService) · data.mode=catalog（宿主服务 91 个；**客户端契约不可达**）
- 生成方式：`node audit-plugins.mjs`（只读、零重启；产物不含时间戳，可逐字节复跑比对）

## 汇总

| 指标 | 数量 |
| --- | --- |
| 组合包 | 20 |
| 源码静态可扫（宿主半边） | 14 |
| 源码不可达（app.asar 内） | 6 |
| 契约缺陷 · blocker | 0 |
| 契约缺陷 · high | 1 |
| 契约缺陷 · medium | 0 |
| 契约缺陷 · low（疑似内置方法，待人工确认） | 2 |
| 静默 catch（宿主半边，非内联运行时） | 183 |
| 静默 catch（内联第三方运行时，已分离） | 0 |
| 静默 catch（客户端半边，另计） | 219 |
| 结论 · 可用 | 7 |
| 结论 · 部分可用 | 8 |
| 结论 · 不可用 | 0 |
| 结论 · 未验证 / 待核 | 5 |

## 全量矩阵

| # | 组合包 | 类型 | 声称能力 | L1 加载 | L2 能力 | L3 契约 | L4 依赖 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `@deepseek-ai/dsh-base` | 官方 | DSH 基座：session / llm / tools / fs / sandbox 等核心服务 | 由 @deepseek-ai/dsh-base 提供的全部核心行 · enabled=true · fiberPhase=active | 本会话全部读写、工具调用、模型调用都跑在它提供的服务上（91 个实时工具、91 个宿主服务目录可读） | 静态不可达 | 包未解析 | **可用** |
| 2 | `@deepseek-ai/dsh-web-app` | 官方 | Web 宿主：HTTP 载体、客户端模块装配、索引注入 | web-startup / webserver / web-runtime / client-modules 等行 active | 本会话的 GUI 就在 127.0.0.1:19387 由该 bundle 提供；对 8 条插件路由的回环探测全部有响应 | 静态不可达 | 包未解析 | **可用** |
| 3 | `@deepseek-ai/dsh-experimental-auto-review` | 官方 | 自动验收：议题进入待验收后派验收子代理 | auto-review 行 enabled=true · fiberPhase=active | 未验证 —— 本议题内不派发验收、不改生产状态，无法在不留副作用的前提下触发一次真实验收 | 静态不可达 | 包未解析 | **未验证** |
| 4 | `@deepseek-ai/dsh-experimental-agent-team-profile` | 官方 | AgentTeams 相关行（3 行） | agent-team / tool-agent-team / ui-agent-team 三行 enabled=true · fiberPhase=active | 部分可用 —— 宿主 agentTeams 服务在实时 Service 目录中存在；agent_teams_status 调用返回语义化结果（非崩溃）。本议题内不建队、不派成员，避免留副作用 | 静态不可达 | 包未解析 | **未验证** |
| 5 | `@deepseek-ai/dsh-experimental-schedule-bundle` | 官方 | 定时计划（2 行） | schedule / ui-schedule 两行 enabled=true · fiberPhase=active | 未验证 —— 宿主 schedule 服务在实时 Service 目录中存在；未创建任何计划任务（会产生真实副作用） | 静态不可达 | 包未解析 | **未验证** |
| 6 | `@deepseek-ai/dsh-experimental-voice-input-bundle` | 官方 | 语音输入（4 行） | speech-to-text / speech-to-text-sensevoice / api-speech-to-text / ui-voice-input 四行 active | 未验证 —— 宿主 speechToText / speechController 服务在实时 Service 目录中存在；真实识别需要麦克风与界面动作 | 静态不可达 | 包未解析 | **未验证** |
| 7 | `dsh-sidenote` | 第三方 | 侧边聊天（side-chat）：把结论回流到主会话 | 以「side-chat」行挂载 · enabled=true · fiberPhase=active | 部分可用 —— 宿主路由 /sidenote/reflow 回环探测返回 HTTP 405（路由已挂载，仅接受 POST），说明宿主半边装配成功；未做真实界面动作（会向主会话注入文本，属生产副作用） | 无缺陷（0 处服务调用） | 包已就位；peer 兼容 | **部分可用** |
| 8 | `dshmarket` | 第三方 | 插件市场：浏览 / 安装 / 卸载 / 启停插件 | 以「dsh-market」行挂载 · enabled=true · fiberPhase=active | 可用 —— 真实调用 marketplace 能力：plugin_manager list_plugins 返回 211 行全量清单（三次分页）；HTTP GET /dsh-market/api/v1/capabilities 返回 200 + 660 字节 | 无缺陷（0 处服务调用） | 包已就位 | **可用** |
| 9 | `dsh-better-sidebar` | 第三方 | 右侧栏：会话/文件/终端/附件多标签 | 以「better-sidebar」行挂载 · enabled=true · fiberPhase=active（补丁内有防重复挂载的 !!js 守卫） | 部分可用 —— 宿主路由 /sidebar/api 回环探测返回 HTTP 405（已挂载、仅接受 POST）；/sidebar/bundle 返回 404（该路由用了非字面路径匹配，本次探测方式不适用）；界面动作未验证 | 2 项契约缺陷（0 项高危） | 包已就位 | **部分可用** |
| 10 | `dsh-context` | 第三方 | 上下文可视：按会话投影展示上下文构成 / 时间线 | 以「dsh-context」行挂载 · enabled=true · fiberPhase=active | 未验证 —— 宿主半边只声明服务依赖、不注册工具、也不注册字面路由；其宿主能力表现为向 sessionProjections 注册 contextBreakdown / contextTimeline 投影，读取需要客户端界面动作 | 无缺陷（12 处服务调用） | 包已就位 | **未验证** |
| 11 | `deep-read-summarize` | 第三方 | 深度阅读：书 / 论文 / 视频 / 网页 → 结构化 Markdown 笔记（workflow + 技能） | 以「deep-read-summarize」行挂载 · enabled=true · fiberPhase=active | 部分可用 —— 该插件注册的 workflow 工具在实时工具表中存在（meta 名 deep-read-summarize，见 91 个工具清单）；未做一次真实深读运行（会产出文件并消耗大量 token） | 无缺陷（1 处服务调用） | 包已就位；peer 兼容 | **部分可用** |
| 12 | `dsh-video-understand` | 第三方 | 视频理解：B 站链接 / 本地视频 → 摘要 + 问答 | 以「video-understand」行挂载 · enabled=true · fiberPhase=active | 部分可用 —— video_understand 工具在实时工具表中存在且参数契约完整；未做真实视频调用（需下载或上传帧到 MiMo API，有成本与外发） | 无缺陷（1 处服务调用） | 包已就位 | **部分可用** |
| 13 | `dsh-genui` | 第三方 | 生成式 UI：让模型输出卡片 schemaJson 并由前端渲染 | 以「genui」行挂载 · enabled=true · fiberPhase=active | 部分可用 —— 宿主半边的系统提示注入已生效（本会话系统提示里确实有 genui 卡片契约：schemaJson 代码块、组件白名单、生成规则）；客户端渲染未验证 | 无缺陷（4 处服务调用） | 包已就位 | **部分可用** |
| 14 | `dsh-mcp-connector` | 第三方 | MCP 连接器：目录 / 三通道连接 / 凭据存储 / 动态条目配置 | 以「mcp-connector」行挂载 · enabled=true · fiberPhase=active | 可用 —— 真实调用 mcp_connector_catalog 返回 113 个已上架连接器（含分类与鉴权方式）；HTTP GET /mcp-connector/ui 返回 200 + 142 KB 静态 SPA | 无缺陷（14 处服务调用） | 包已就位 | **可用** |
| 15 | `dsh-task-board` | 第三方 | 任务看板：工作区 → 待执行 → 自动执行 → 待验收 → 自动验收 → 完成 | 以「dsh-task-board」行挂载 · enabled=true · fiberPhase=active | 部分可用 —— 读路径可用（kanban_list_issues 返回 6 条真实议题）；写路径：宿主 00:18:37 启动（晚于 v4 写盘 00:09:26，即当前进程装载的就是 v4），此后 12 分钟零新增失败，且 .dsh/kanban-state.json 在 00:25:40 被成功写入（version=46）、无残留锁；但 00:09:26–00:18:37 之间仍有 5 条 state file lock timeout（调用栈指向 v4 的 withFileLock），无法确认属 v3 还是 v4 | 无缺陷（39 处服务调用） | 包已就位 | **部分可用** |
| 16 | `cc-safety-net` | 第三方 | 命令安全网：在执行前拦截危险命令 | 以「cc-safety-net」行挂载（moduleName 是 file:/// 本地路径）· enabled=true · fiberPhase=active | 可用 —— 拒绝路径实测生效两次：`git push --force` 被拦（Rule: git.push-force）、审计收尾时跨目录的 `Remove-Item -Recurse -Force` 被拦（Rule: powershell.remove-item-recursive-force-outside-cwd，按它给的替代路径改 `workdir` 后同命令通过，闭环正确）；放行路径实测生效：对自建临时目录的删除被放行（属策略允许，不是失效） | 无缺陷（0 处服务调用） | 包已就位 | **可用** |
| 17 | `dsh-cost-meter` | 第三方 | 成本计量：按会话 / 供应商 / 模型显示 token 与费用 | 以「cost-meter」行挂载 · enabled=true · fiberPhase=active | 部分可用 —— 宿主半边可装载、逐版兼容闸判定 0.2.0-rc.2 = compatible；但 L3 发现它调用了宿主 settings 服务不存在的方法（见缺陷 #1），DeepSeek 余额查询会静默降级到环境变量兜底 | 1 项契约缺陷（1 项高危） | 包已就位 | **部分可用** |
| 18 | `@nanmicoder/dsh-agent-teams` | 第三方 | AgentTeams：多智能体团队协作（建队 / 任务 DAG / 成员调度） | 以「agent-teams」行挂载 · enabled=true · fiberPhase=active | 可用 —— 16 个 agent_teams_* 工具全部在实时工具表中；实测 agent_teams_status 返回语义化结果（本会话为 fork 子代理、无团队，返回明确原因而非崩溃） | 无缺陷（43 处服务调用） | 包已就位 | **可用** |
| 19 | `@linxin666/dsh-client-ui-skin-center` | 第三方 | 皮肤中心：主题 / 皮肤切换 | 以「ui-skin-center」行挂载 · enabled=true · fiberPhase=active | 部分可用 —— 宿主半边已运行并落盘：~/.dsh/skin-center-active.json 内容为 {"active": null, "initialized": true}；皮肤渲染本身在客户端，未做界面动作 | 无缺陷（2 处服务调用） | 包已就位；peer 兼容 | **部分可用** |
| 20 | `@liustack/modlens` | 第三方 | 视觉理解桥：读图 / OCR / 版面与语义证据 | 以「modlens」行挂载 · enabled=true · fiberPhase=active | 可用 —— 真实调用 modlens_read_image 读取仓库内一张 1.18 MB PNG，返回完整 OCR 全文 + 版面 + 语义结论（内容与图片实际文字一致） | 无缺陷（17 处服务调用） | 包已就位 | **可用** |

## 逐包明细（L3/L4 自动证据）

### @deepseek-ai/dsh-base

- 类型：官方
- 包目录：**未解析**
- 静态扫描：不可达 —— profile/node_modules 下无该包（官方 bundle 打包在 app.asar 内，普通 fs 读不到）
- 补丁清单：未声明
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- 证据路径：
  - evidence/l2-probes.md#基座与-web-宿主
  - contracts.json
- 备注：第三方插件全部 inject 的服务（tools/fs/webServer/shell/timer/subagents/agents/llm 等）均由该 bundle 提供。

### @deepseek-ai/dsh-web-app

- 类型：官方
- 包目录：**未解析**
- 静态扫描：不可达 —— profile/node_modules 下无该包（官方 bundle 打包在 app.asar 内，普通 fs 读不到）
- 补丁清单：未声明
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- 证据路径：
  - evidence/l2-probes.md#回环-http-路由探测
- 备注：第三方插件注册的 /sidebar、/mcp-connector、/dsh-market、/dsh-task-board、/sidenote、/modlens、/plugins/dsh-agent-teams、/genui 路由都挂在这台服务器上。

### @deepseek-ai/dsh-experimental-auto-review

- 类型：官方
- 包目录：**未解析**
- 静态扫描：不可达 —— profile/node_modules 下无该包（官方 bundle 打包在 app.asar 内，普通 fs 读不到）
- 补丁清单：未声明
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- 证据路径：
  - evidence/l1-rows.md
- 备注：验证路径：看板 autoAccept=true 时进入待验收即触发；由用户决定何时开启（用户手动设置的开关，agent 不得代改）。

### @deepseek-ai/dsh-experimental-agent-team-profile

- 类型：官方
- 包目录：**未解析**
- 静态扫描：不可达 —— profile/node_modules 下无该包（官方 bundle 打包在 app.asar 内，普通 fs 读不到）
- 补丁清单：未声明
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- 证据路径：
  - evidence/l2-probes.md#agent-teams
- 备注：与第三方 @nanmicoder/dsh-agent-teams 记录同源证据。

### @deepseek-ai/dsh-experimental-schedule-bundle

- 类型：官方
- 包目录：**未解析**
- 静态扫描：不可达 —— profile/node_modules 下无该包（官方 bundle 打包在 app.asar 内，普通 fs 读不到）
- 补丁清单：未声明
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- 证据路径：
  - contracts.json
- 备注：验证路径：界面创建一个一次性提醒后观察是否触发。

### @deepseek-ai/dsh-experimental-voice-input-bundle

- 类型：官方
- 包目录：**未解析**
- 静态扫描：不可达 —— profile/node_modules 下无该包（官方 bundle 打包在 app.asar 内，普通 fs 读不到）
- 补丁清单：未声明
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- 证据路径：
  - contracts.json
- 备注：speech-to-text-sensevoice 依赖 app.asar.unpacked 里的 sherpa-onnx 原生包（该目录实测存在）。

### dsh-sidenote

- 类型：第三方 · 版本 0.5.0
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-sidenote`
- 静态扫描：122 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 目录外服务 key（覆盖盲区候选，需人工复核）：`get`（未确证）
- 静默 catch：宿主半边 6 处（空 catch 4 处；内联第三方运行时另计 0 处）；客户端半边 54 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#回环-http-路由探测
- 备注：engines.dsh 声明 `>=0.1.1-rc.1 <0.2.0 || =0.2.0-rc.2`，本机 0.2.0-rc.2 命中，兼容闸通过。

### dshmarket

- 类型：第三方 · 版本 1.66.20
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dshmarket`
- 静态扫描：157 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`client/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 依赖：声明 2 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 目录外服务 key（覆盖盲区候选，需人工复核）：`plugin`（未确证）、`configForms`（未确证）
- 静默 catch：宿主半边 5 处（空 catch 5 处；内联第三方运行时另计 0 处）；客户端半边 24 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l1-rows.md
  - evidence/l2-probes.md#回环-http-路由探测
- 备注：plugin_manager 工具即为该插件的宿主能力入口（DSH 自带的 tool-plugin-manager 行是 disabled 状态）。

### dsh-better-sidebar

- 类型：第三方 · 版本 0.26.0
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-better-sidebar`
- 静态扫描：376 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 依赖：声明 33 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：79 处调用 / 11 个 inject key
- 静默 catch：宿主半边 14 处（空 catch 14 处；内联第三方运行时另计 0 处）；客户端半边 82 处
- **L3 契约缺陷**：
  - `[low]` `service-not-in-catalog` @ `lib/index.js:6874` —— inject 的 webRuntime 不在 Service 目录里，但已由宿主源码确证存在（审计目录覆盖盲区，非缺陷）
    - 依据：由 @deepseek-ai/dsh-web-app 提供；证据：app.asar 内 `const WEB_RUNTIME_SERVICE = "webRuntime"` 与 patch 文档 `inject: [webRuntime]`。不在 listService 目录中。
  - `[low]` `service-not-in-catalog` @ `src/index.ts:114` —— inject 的 webRuntime 不在 Service 目录里，但已由宿主源码确证存在（审计目录覆盖盲区，非缺陷）
    - 依据：由 @deepseek-ai/dsh-web-app 提供；证据：app.asar 内 `const WEB_RUNTIME_SERVICE = "webRuntime"` 与 patch 文档 `inject: [webRuntime]`。不在 listService 目录中。
- 证据路径：
  - evidence/l2-probes.md#回环-http-路由探测
- 备注：本机未安装 @linxin666/dsh-web-ui-all 聚合包，故 !!js 守卫不会把本行关掉（实测该行确实 active）。

### dsh-context

- 类型：第三方 · 版本 0.70.0
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-context`
- 静态扫描：3 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 依赖：声明 1 个，全部可达
- engines.dsh：未声明
- 逐版兼容闸（dsh.compatibility）：范围未声明；本机 0.2.0-rc.2 → **compatible**
- 宿主服务引用：12 处调用 / 3 个 inject key
- 静默 catch：宿主半边 9 处（空 catch 9 处；内联第三方运行时另计 0 处）；客户端半边 17 处
- **L3 契约缺陷**：无
- 证据路径：
  - service-refs.json
- 备注：客户端 inspect 在本会话不可达（Client 查询 10s 超时），客户端契约无法比对。

### deep-read-summarize

- 类型：第三方 · 版本 0.3.13
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\deep-read-summarize`
- 静态扫描：13 个源文件（宿主半边与客户端半边分平面）
- 补丁清单：`./cordis.patch.yml`（存在）
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：1 处调用 / 1 个 inject key
- 静默 catch：宿主半边 2 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#工具层
- 备注：engines.dsh `>=0.1.0-rc.6` 兼容闸通过。

### dsh-video-understand

- 类型：第三方 · 版本 0.5.2
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-video-understand`
- 静态扫描：6 个源文件（宿主半边与客户端半边分平面）
- 补丁清单：`./cordis.patch.yml`（存在）
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：1 处调用 / 1 个 inject key
- 静默 catch：宿主半边 0 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#工具层
- 备注：该行在 profile 补丁里被显式 disabled: false 覆盖过一次（见 cordis.patch.yml）。

### dsh-genui

- 类型：第三方 · 版本 0.3.1
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-genui`
- 静态扫描：3 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：4 处调用 / 10 个 inject key
- 目录外服务 key（覆盖盲区候选，需人工复核）：`data`（未确证）、`parsedType`（未确证）
- 静默 catch：宿主半边 30 处（空 catch 24 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#genui
- 备注：配置 sectionName=genui:cards / sectionOrder=80 / promptEnabled=true。

### dsh-mcp-connector

- 类型：第三方 · 版本 0.2.70
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-mcp-connector`
- 静态扫描：39 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 依赖：声明 1 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：14 处调用 / 8 个 inject key
- 静默 catch：宿主半边 6 处（空 catch 6 处；内联第三方运行时另计 0 处）；客户端半边 5 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#回环-http-路由探测
- 备注：本机凭据文件 ~/.dsh/.credentials.yaml 存在（仅记录键名，未读取任何值）。

### dsh-task-board

- 类型：第三方 · 版本 1.0.0
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-task-board`
- 静态扫描：2 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：39 处调用 / 13 个 inject key
- 静默 catch：宿主半边 22 处（空 catch 18 处；内联第三方运行时另计 0 处）；客户端半边 17 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#task-board
  - evidence/task-board-ledger.md
- 备注：v4 = 部分已验证，定论需一次受控启动（把 persistDiag 扩记 exitCode/stderr/sandbox/命令行）→ 标注 待 k-mv8ak8zi-4。另观察到健康扫描在 5 分 26 秒无议题更新后把仍在运行的执行体打回 todo（autoExec=true 时存在重复派发风险），详见台账。本议题内不做任何重启、不改任何开关。

### cc-safety-net

- 类型：第三方 · 版本 2.6.11
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\cc-safety-net`
- 静态扫描：19 个源文件（宿主半边与客户端半边分平面）
- 补丁清单：`./dist/deepseek-harness/cordis.patch.yml`（存在）
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：无（或静态不可达）
- 静默 catch：宿主半边 31 处（空 catch 29 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#cc-safety-net
- 备注：该插件只挂工具层（inject: ["tools"]），拦不到插件进程内的 shell 服务调用 —— 这条边界已写进 L3 风险规则。

### dsh-cost-meter

- 类型：第三方 · 版本 1.8.24
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\dsh-cost-meter`
- 静态扫描：43 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
- 依赖：声明 1 个，全部可达
- engines.dsh：未声明
- 逐版兼容闸（dsh.compatibility）：`>=0.1.0-rc.5`；本机 0.2.0-rc.2 → **compatible**
- 宿主服务引用：25 处调用 / 0 个 inject key
- 目录外服务 key（覆盖盲区候选，需人工复核）：`get`（未确证）
- 静默 catch：宿主半边 27 处（空 catch 26 处；内联第三方运行时另计 0 处）；客户端半边 9 处
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
- 依赖：声明 0 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：43 处调用 / 11 个 inject key
- 目录外服务 key（覆盖盲区候选，需人工复核）：`get`（未确证）
- 静默 catch：宿主半边 1 处（空 catch 0 处；内联第三方运行时另计 0 处）；客户端半边 4 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#agent-teams
  - evidence/l2-probes.md#工具层
- 备注：本议题内不建队（会在工作区留下 .agent-teams 目录）。

### @linxin666/dsh-client-ui-skin-center

- 类型：第三方 · 版本 0.4.6
- 包目录：`C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\@linxin666\dsh-client-ui-skin-center`
- 静态扫描：4 个源文件（宿主半边与客户端半边分平面）
- 客户端入口：`lib/client.js`
- 补丁清单：`./cordis.patch.yml`（存在）
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
- 依赖：声明 2 个，全部可达
- engines.dsh：未声明
- 宿主服务引用：17 处调用 / 4 个 inject key
- 静默 catch：宿主半边 20 处（空 catch 20 处；内联第三方运行时另计 0 处）；客户端半边 0 处
- **L3 契约缺陷**：无
- 证据路径：
  - evidence/l2-probes.md#modlens
- 备注：另注册 /modlens/paste、/modlens/config 两条宿主路由，/modlens/config 回环探测返回 200。
