# L4 依赖层证据 —— 包路径 / 软链 / 补丁清单 / 依赖 / 兼容闸 / 凭据 / 零重启基线

## 宿主版本（判定兼容闸的基准）

`C:\Users\songzhenxi\.dsh\dsh-runtimes\dsh-primary-runtime\runtime.json`：

```json
{ "desktopVersion": "0.2.0-rc.2", "platform": "win32", "arch": "x64",
  "python": "3.12.14", "node": "24.21.0", "pnpm": "11.7.0" }
```

审计脚本用的执行器也正是这台 Node：`…\dsh-primary-runtime\dependencies\node\bin\node.exe`（v24.21.0；本机 PATH 上的 node 是 v22.21.1，两者都能跑）。

## 包路径与软链

- **14 个第三方组合包**全部落在 `C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\<包名>`；
  `lstat` 实测**全部不是软链**（pnpm 落盘为实体目录/硬链接）→ 不存在「本地 link 源目录被删 → 整行加载失败」那条先例风险。
- **6 个官方组合包**不在 profile 的 node_modules 里，它们打包在 `…\resources\app.asar` 内。
  **本版已把 asar 读通**（见下节），所以官方包的 L4 不再是空白。

## app.asar 现在可读了（推翻首版的「静态不可达」）

首版结论是「asar 读不了 → 官方 6 包 L3/L4 不可达」。**这条已作废**，原因是找错了读法：

| 读法 | 结果 |
| --- | --- |
| `Test-Path "…\resources\app.asar\dsh"` | False（asar 不是目录）—— 首版据此判「不可达」 |
| DSH 的 `read` 工具读 asar 内文件 | `Error: Cannot mix BigInt and other types`（DSH fs 后端的缺陷） |
| **普通 Node 进程直接按 asar 布局读** | ✅ **可用** |

布局（与学习库 `03-运行时取证\脚本\asar头部探测.cjs` 已验证的一致）：
`offset 0..16` 是 pickle 头，**offset 12 处的 UInt32LE = 头部 JSON 字节数**，JSON 自 `offset 16` 起，
数据区基准 `baseOffset = 16 + headerSize`，每个文件条目给出 `size` 与相对 `offset`。

```
headerSize = 3392048   baseOffset = 3392064   app.asar = 121,348,951 字节
```

`audit-plugins.mjs` 已内置这套读取（`--asar <path>` 可换路径），于是官方 6 包拿到了真实 L4 数据：

| 官方组合包 | 版本 | 补丁清单 | 声明行数 | 依赖 | asar 内条目 | 其中 JS |
| --- | --- | --- | --- | --- | --- | --- |
| `@deepseek-ai/dsh-base` | 0.2.0-rc.2 | ✅ 存在 | 94 | 93 / 全部可达 | 7 | 1（11 字节占位） |
| `@deepseek-ai/dsh-web-app` | 0.2.0-rc.2 | ✅ 存在（含 4 个 preset 层） | 136 | 127 / 全部可达 | 12 | 2 |
| `@deepseek-ai/dsh-experimental-auto-review` | 0.2.0-rc.2 | ✅ 存在 | 1 | 1 / 全部可达 | 10 | 1（24 KB 真实实现） |
| `@deepseek-ai/dsh-experimental-agent-team-profile` | 0.2.0-rc.2 | ✅ 存在 | 7 | 3 / 全部可达 | 10 | 1（11 字节占位） |
| `@deepseek-ai/dsh-experimental-schedule-bundle` | 0.2.0-rc.2 | ✅ 存在 | 3 | 3 / 全部可达 | 10 | 1（11 字节占位） |
| `@deepseek-ai/dsh-experimental-voice-input-bundle` | 0.2.0-rc.2 | ✅ 存在 | 4 | 4 / 全部可达 | 10 | 1（11 字节占位） |

**结构性事实**（对「为什么官方包没有 L3 缺陷」很关键）：官方组合包基本**只有补丁清单**，
`lib/index.js` 只有 11 字节占位（`export {}` 之类）—— 真正干活的是它们 mount 的
`dsh/node_modules/@deepseek-ai/dsh-*` 模块（那部分是整个运行时，不属本议题的 20 包范围）。
唯一有真实 JS 的是 `auto-review`（24 KB），它已被静态扫描，**无契约缺陷**。

## 补丁清单（`dsh.bundle.patch`）

20/20 都声明了 `dsh.bundle.patch`，且声明指向的文件**全部存在**（第三方在磁盘、官方在 asar 内）。
两个特例：

- `cc-safety-net`：`./dist/deepseek-harness/cordis.patch.yml`，且行名是 `./index.js`（见 `l1-rows.md`）。
- `@deepseek-ai/dsh-web-app`：声明 5 个补丁文件（主清单 + 4 个 preset 层）。

## 依赖可达性（第三方 14 个）

| 组合包 | 声明依赖数 | 缺失 | `engines.dsh` | 兼容结论 |
| --- | --- | --- | --- | --- |
| dsh-sidenote | 0 | — | `>=0.1.1-rc.1 <0.2.0 \|\| =0.2.0-rc.2` | 兼容（命中 `=0.2.0-rc.2`） |
| deep-read-summarize | 0 | — | `>=0.1.0-rc.6` | 兼容 |
| @linxin666/dsh-client-ui-skin-center | 2 | — | `dsh.engines.dsh: >=0.1.7-rc.1` | 兼容 |
| dsh-cost-meter | 1 | — | 另有 `dsh.compatibility`：范围 `>=0.1.0-rc.5`，逐版表 `0.2.0-rc.2 = compatible` | 兼容（上游自报） |
| dshmarket | 2 | — | 未声明 | — |
| dsh-better-sidebar | 33 | — | 未声明 | — |
| dsh-context | 1 | — | 未声明 | — |
| dsh-mcp-connector | 1 | — | 未声明 | — |
| dsh-genui / dsh-task-board / dsh-video-understand / cc-safety-net / @nanmicoder/dsh-agent-teams / @liustack/modlens | 0 | — | 未声明 | — |

结论：**20/20 组合包没有任何一个缺依赖、没有软链失效、没有补丁清单缺失、没有 `engines.dsh` 被拦。**

> `dsh-task-board` 是唯一连 `engines` 都没声明的包（github 直装的自制插件，见缺陷 #7）。

## 凭据

`C:\Users\songzhenxi\.dsh\.credentials.yaml` 存在。**仅登记键名，未读取任何值**：
`version / records / kind / payload / secret / id / token / issuer / refs / DEEPSEEK_API_KEY`。

MCP 凭据存储：`mcp_connector_status` 实测**当前 0 条已配连接** —— 插件本身可用（目录 113 条），
没有连接是**用户尚未配置**，不作为缺陷。

## skin-center

`C:\Users\songzhenxi\.dsh\skin-center-active.json`：

```json
{ "active": null, "initialized": true }
```

→ 该插件的宿主半边**真的跑起来过并落了盘**（它能证明「装了且在动」的最强静态旁证）。

## 外部服务的本地缓存（旁证「真的被用过」）

- `~/.dsh/cache/video-understand/transcripts/*.json`（2 个文件，17 KB / 82 KB，2026-10-14 17:22）
  → `dsh-video-understand` 的**真实调用痕迹**：它至少在 2026-10-14 成功跑过两次转写。
- `~/.dsh/storages/cost-meter/ledger.json`（215,827 字节，2026-10-15 01:06 仍在写）
  → `dsh-cost-meter` 的账本**一直在写**（也说明它的核心记账链路与缺陷 #1 那条余额查询链路是分开的）。

## 零重启基线（可复核）

| 采集时刻 | 事实 |
| --- | --- |
| 2026-10-15 01:0x（本轮执行起点） | `DeepSeek Harness` 进程组：主进程 PID **60356** 启动于 **00:32:32**；gpu 54460 / utility 16744 / renderer 56108 启动于 **00:32:31** |
| 2026-10-15 01:0x–01:2x（本轮执行期间） | 上述启动时间**一次未变** |
| 结论 | **本议题全程零重启**（含首轮与复核轮）：执行期间宿主进程组启动时间恒定 |

> 时序（避免误读）：宿主上一代进程组启动于 **00:18:37**，在 **00:32:31/00:32:32 被外部重启**
> （**不是本议题做的** —— 本议题从 00:20 起全程零重启；重启发生在首轮提交（00:32）之后、本轮（01:01）之前）。
> 下一代进程组启动于 00:32:31，**晚于 dsh-task-board v5 补丁写盘（00:31:26）**，
> 也晚于 v4（00:09:26）→ **当前进程装的确实是 v5**，这给 v4→v5 提供了一次真实的启动窗口（见 `task-board-ledger.md`）。

复核命令（零副作用）：

```powershell
Get-CimInstance Win32_Process -Filter "Name='DeepSeek Harness.exe'" |
  Select-Object ProcessId, CreationDate, CommandLine
```
