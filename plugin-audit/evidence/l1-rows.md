# L1 加载层证据 —— 行是否挂载、是否 active

L1 用**两路证据**交叉验证，缺一路都证明不了「这个组合包该挂的行都挂上了」：

1. **实时行表**：会话内 `plugin_manager list_plugins` 三次分页采集（全表 211 行），落到 `live-entries.json`；
2. **补丁声明的行**：`audit-plugins.mjs` 静态解析每个组合包的 `cordis.patch.yml`，抽出全部 `id:`；
   再与实时行表**逐 id 比对**（结果在 `audit-result.json` 的 `liveStatus`）。

为什么必须有第 2 路：只看「表里有这行」证明不了「这个包该挂的行没漏」——
漏挂/静默失败在加载层是看不见的，而本议题的立案理由正是这一类失效。

## 比对结果（18/20 逐 id 机器比对，缺失 0、异常非 active 0）

| # | 组合包 | 补丁清单 | 声明行数 | 实时命中 | 缺失 | 预期 disabled | 实际异常非 active |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `@deepseek-ai/dsh-base` | ./cordis.patch.yml | 94 | 未比对 | — | 0 | 0 |
| 2 | `@deepseek-ai/dsh-web-app` | ./cordis.patch.yml<br>./presets/standard.patch.yml<br>./presets/ptc.patch.yml<br>./presets/minimal.patch.yml<br>./presets/cordis.patch.yml | 136 | 未比对 | — | 0 | 0 |
| 3 | `@deepseek-ai/dsh-experimental-auto-review` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 4 | `@deepseek-ai/dsh-experimental-agent-team-profile` | ./cordis.patch.yml | 7 | 7 | 0 | 4 | 0 |
| 5 | `@deepseek-ai/dsh-experimental-schedule-bundle` | ./cordis.patch.yml | 3 | 3 | 0 | 0 | 0 |
| 6 | `@deepseek-ai/dsh-experimental-voice-input-bundle` | ./cordis.patch.yml | 4 | 4 | 0 | 0 | 0 |
| 7 | `dsh-sidenote` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 8 | `dshmarket` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 9 | `dsh-better-sidebar` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 10 | `dsh-context` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 11 | `deep-read-summarize` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 12 | `dsh-video-understand` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 13 | `dsh-genui` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 14 | `dsh-mcp-connector` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 15 | `dsh-task-board` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 16 | `cc-safety-net` | ./dist/deepseek-harness/cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 17 | `dsh-cost-meter` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 18 | `@nanmicoder/dsh-agent-teams` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 19 | `@linxin666/dsh-client-ui-skin-center` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |
| 20 | `@liustack/modlens` | ./cordis.patch.yml | 1 | 1 | 0 | 0 | 0 |

口径：
- **实时命中** = 声明的 id 能在实时行表里按 id 找到；**缺失** = 找不到（`liveMissing`）。
- **预期 disabled** = 补丁自己写了 `disabled: true`（快照里标了 `disabledByPatch`），非 active 属预期；
- **实际异常非 active** = 补丁声明启用、实时却不是 `enabled+active` —— **这一列才是真问题，实测为 0**。
- **未比对的 2 个**（base / web-app）：它们声明的行各近百行，而实时行表快照只录入了用户侧 20 个组合包对应的行。
  显式标「未比对」，不假装比过；补录全表后该列会自动填充（`--live` 参数可换快照）。

### 小包的声明 id 明细（≤10 行的包逐条列出）

- `@deepseek-ai/dsh-experimental-auto-review`（1）：`auto-review`
- `@deepseek-ai/dsh-experimental-agent-team-profile`（7）：`tool-subagent-control`、`tool-subagent-list-agents`、`tool-subagent`、`tool-subagent-fork`（**这 4 行补丁自己写了 `disabled: true`**）、`agent-team`、`tool-agent-team`、`ui-agent-team`
- `@deepseek-ai/dsh-experimental-schedule-bundle`（3）：`time-context`、`schedule`、`ui-schedule`
- `@deepseek-ai/dsh-experimental-voice-input-bundle`（4）：`speech-to-text`、`speech-to-text-sensevoice`、`api-speech-to-text`、`ui-voice-input`
- 14 个第三方包各 1 行：`side-chat`、`dsh-market`、`better-sidebar`、`dsh-context`、`deep-read-summarize`、`video-understand`、`genui`、`mcp-connector`、`dsh-task-board`、`cc-safety-net`、`cost-meter`、`agent-teams`、`ui-skin-center`、`modlens`

### 两个大包的静态声明（只给数量与来源）

- `@deepseek-ai/dsh-base`：94 行，来源 `./cordis.patch.yml`（20,780 字节 → 94 行）
- `@deepseek-ai/dsh-web-app`：136 行 = 5 个补丁文件的**并集**（`./cordis.patch.yml` 112 行 + `presets/standard` 34 + `presets/ptc` 35 + `presets/minimal` 9 + `presets/cordis` 35；后 4 个是可选层，**未逐层去重**）

### 一个反例（本机实测，说明这套比对不是摆设）

`@deepseek-ai/dsh-experimental-schedule-bundle` 的补丁声明 **3** 行（`time-context` / `schedule` / `ui-schedule`），
而首版快照只录了 2 行 → 比对直接报出「缺失 `time-context`」。
复核实时行表后确认是**快照漏录**（`include:time-context` 确实 active），已补录，现为 3/3。
这条既证明比对会报警，也说明「缺行」必须先人工复核才能定性（**别把快照的锅算到插件头上**）。

## 重要细节：`cc-safety-net` 的行名是本地文件路径

```
include:cc-safety-net  moduleName = file:///C:/Users/songzhenxi/.dsh/profiles/desktop/node_modules/cc-safety-net/dist/deepseek-harness/index.js
```

它不走包名解析，而是按相对 `./index.js` 展开成**绝对文件 URL**。这正是议题里提到的那类 L4 风险：
本地文件被移动或删除，整行立刻加载失败（学习库有先例：`E:\Works\模型测试` 被删后对应行失效）。
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
node audit-plugins.mjs --live live-entries.json               # 重跑逐 id 比对
```

## 与「加载层全绿」的关系

20 个组合包对应的行**全部 `enabled=true` / `fiberPhase=active`**（唯一 4 行非 active 的，是
agent-team-profile 补丁主动 `disabled: true` 的 `tool-subagent*`）。
**但加载层全绿只证明「挂上了」，不证明「能用」** —— 能力层见 `l2-probes.md`，契约层见 `findings.json`。
