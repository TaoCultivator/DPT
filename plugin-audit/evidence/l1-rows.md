# L1 加载层证据 —— 20 个用户侧组合包的实际挂载行

采集方式（零重启、只读）：会话内调用 `plugin_manager(action=list_plugins)` 分三页取全表（`limit=100`，offset 0 / 100 / 200），
再按各组合包自带的 `cordis.patch.yml` 反查它插入的 `id`，将「组合包 → 实际挂载行」对上号。

- 全表行数：**211**
- 用户侧组合包：**20**（6 官方 + 14 第三方）
- 结论：**20/20 全部 `enabled=true` / `fiberPhase=active`** —— 加载层全绿（但加载层全绿不等于能用，这正是本议题的出发点）

| # | 组合包 | 类型 | 补丁声明的行 id | entryId | enabled | fiberPhase |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `@deepseek-ai/dsh-base` | 官方 | （多行） | 多个 `include:*` | true | active |
| 2 | `@deepseek-ai/dsh-web-app` | 官方 | `web-startup` / `webserver` / `web-runtime` / `client-modules` … | `include:web-startup` 等 | true | active |
| 3 | `@deepseek-ai/dsh-experimental-auto-review` | 官方 | `auto-review` | `include:auto-review` | true | active |
| 4 | `@deepseek-ai/dsh-experimental-agent-team-profile` | 官方 | `agent-team` / `tool-agent-team` / `ui-agent-team` | `include:agent-team` 等 | true | active |
| 5 | `@deepseek-ai/dsh-experimental-schedule-bundle` | 官方 | `schedule` / `ui-schedule` | `include:schedule` 等 | true | active |
| 6 | `@deepseek-ai/dsh-experimental-voice-input-bundle` | 官方 | `speech-to-text` / `speech-to-text-sensevoice` / `api-speech-to-text` / `ui-voice-input` | `include:speech-to-text` 等 | true | active |
| 7 | `dsh-sidenote` | 第三方 | `side-chat` | `include:side-chat` | true | active |
| 8 | `dshmarket` | 第三方 | `dsh-market` | `include:dsh-market` | true | active |
| 9 | `dsh-better-sidebar` | 第三方 | `better-sidebar` | `include:better-sidebar` | true | active |
| 10 | `dsh-context` | 第三方 | `dsh-context` | `include:dsh-context` | true | active |
| 11 | `deep-read-summarize` | 第三方 | `deep-read-summarize` | `include:deep-read-summarize` | true | active |
| 12 | `dsh-video-understand` | 第三方 | `video-understand` | `include:video-understand` | true | active |
| 13 | `dsh-genui` | 第三方 | `genui` | `include:genui` | true | active |
| 14 | `dsh-mcp-connector` | 第三方 | `mcp-connector` | `include:mcp-connector` | true | active |
| 15 | `dsh-task-board` | 第三方 | `dsh-task-board` | `include:dsh-task-board` | true | active |
| 16 | `cc-safety-net` | 第三方 | `cc-safety-net`（name 为 `./index.js`） | `include:cc-safety-net` | true | active |
| 17 | `dsh-cost-meter` | 第三方 | `cost-meter` | `include:cost-meter` | true | active |
| 18 | `@nanmicoder/dsh-agent-teams` | 第三方 | `agent-teams` | `include:agent-teams` | true | active |
| 19 | `@linxin666/dsh-client-ui-skin-center` | 第三方 | `ui-skin-center` | `include:ui-skin-center` | true | active |
| 20 | `@liustack/modlens` | 第三方 | `modlens` | `include:modlens` | true | active |

## 重要细节：`cc-safety-net` 的行名是本地文件路径

```
include:cc-safety-net  moduleName = file:///C:/Users/songzhenxi/.dsh/profiles/desktop/node_modules/cc-safety-net/dist/deepseek-harness/index.js
```

它不走包名解析，而是**按相对 `./index.js` 展开成绝对文件 URL**。这正是议题里提到的那类 L4 风险：
本地 link / 文件路径一旦被移动或删除，整行立刻加载失败（学习库有先例：`E:\Works\模型测试` 被删后对应行失效）。
当前实测该文件存在（229 字节）：

```js
import"../chunks/index-babcfevy.js";import{gt}from"../chunks/index-n6djve2j.js";…
var t={name:"cc-safety-net",inject:["tools"],apply:gt};export{t as default};
```

## 复核命令（零重启）

```
plugin_manager(action="list_plugins", limit=100, offset=0)
plugin_manager(action="list_plugins", limit=100, offset=100)
plugin_manager(action="list_plugins", limit=100, offset=200)   # total=211, nextOffset=null
```
