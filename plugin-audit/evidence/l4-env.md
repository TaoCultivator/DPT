# L4 依赖层证据 —— 包路径 / 软链 / 补丁清单 / 依赖 / 兼容闸 / 凭据 / 零重启基线

## 宿主版本（判定兼容闸的基准）

`C:\Users\songzhenxi\.dsh\dsh-runtimes\dsh-primary-runtime\runtime.json`：

```json
{ "desktopVersion": "0.2.0-rc.2", "platform": "win32", "arch": "x64",
  "python": "3.12.14", "node": "24.21.0", "pnpm": "11.7.0" }
```

审计脚本用的执行器也正是这台 Node：`…\dsh-primary-runtime\dependencies\node\bin\node.exe`。

## 包路径与软链

- 14 个第三方组合包全部落在 `C:\Users\songzhenxi\.dsh\profiles\desktop\node_modules\<包名>`；
  **`lstat` 实测全部不是软链**（pnpm 落盘为实体目录/硬链接），因此不存在「本地 link 源目录被删 → 整行加载失败」那条先例风险。
- 6 个官方组合包**不在 profile 的 node_modules 里**：它们打包在 `…\resources\app.asar` 内。
  实测结论：`app.asar` **不是普通目录**，`Test-Path` 为 False；`read` 工具读 asar 内文件会抛
  `Cannot mix BigInt and other types`（DSH fs 后端读 asar 的已知缺陷）；`glob` 也无法遍历其内部。
  → 官方 6 包的 **L3 静态源码扫描不可达**，本报告一律显式标注「静态不可达」，不假装扫过。
  → 可用的替代证据：它们的行全部 active + 其拥有的服务全部出现在实时 Service 目录中。

## 补丁清单（`dsh.bundle.patch`）

14/14 第三方包都在 package.json 里声明了 `dsh.bundle.patch`，且**声明指向的文件全部存在**。
两个特例：

- `cc-safety-net`：`./dist/deepseek-harness/cordis.patch.yml`，且行名是 `./index.js`（见 `l1-rows.md`）。
- 其余均为 `./cordis.patch.yml`。

## 依赖可达性

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

结论：**没有任何一个第三方包缺依赖，也没有任何一个因 `engines.dsh` 被拦**。

## 凭据

`C:\Users\songzhenxi\.dsh\.credentials.yaml` 存在。**仅登记键名，未读取任何值**：
`version / records / kind / payload / secret / id / token / issuer / refs / DEEPSEEK_API_KEY`。

## skin-center

`C:\Users\songzhenxi\.dsh\skin-center-active.json`：

```json
{ "active": null, "initialized": true }
```

→ 该插件的宿主半边**真的跑起来过并落了盘**（这是它能证明「装了且在动」的最强静态旁证）。

## 零重启基线（可复核）

| 采集时刻 | 事实 |
| --- | --- |
| 2026-10-15 00:29:55 | `DeepSeek Harness` 进程组 StartTime = **2026-10-15 00:18:37**（PIDs 46752 / 56284 / 60092 / 58856 / 18380） |
| 本议题执行起点 | 2026-10-15 00:20:14（议题被移入 in_progress 的时刻） |
| 结论 | 本议题全程 **未重启宿主**：执行期间宿主启动时间恒为 00:18:37 |

复核命令（零副作用）：

```powershell
Get-Process -Name 'DeepSeek Harness' | Select-Object Id, StartTime
```

> 注意时序（避免误读）：宿主上一次启动是 **00:18:37**，早于本议题执行起点（00:20:14），
> 但晚于 dsh-task-board v4 补丁写盘时刻（00:09:26）。也就是说 **v4 补丁在当前进程里是已经装载的**——
> 这一点对判断「v4 到底修没修好」很关键，详见 `task-board-ledger.md`。
