# 已装插件真实可用性审计（DPT · 看板议题 `k-mv8b6x0z-6`）

**这份目录回答一个问题：装上的插件，真的能用吗？**

立案理由：`dsh-task-board` 在插件列表里 `enabled=true / fiberPhase=active`，界面能开、能建议题、能拖状态，
但它的落盘写入路径**从安装第一天起就是死的**（调了 `shell.run`，而 DSH 的 shell 服务只有 `resolve` + `execute`），
一路查到第四次补丁才被临时诊断日志抓到 `TypeError: shell.run is not a function`。
**「加载成功」与「真的能用」之间没有任何保证** —— 这套审计就是来补这个保证的。

- 审计对象：`C:\Users\songzhenxi\.dsh\profiles\desktop` 的 `dsh.profile.bundles` 全部 **20 个**组合包
  （6 官方 + 14 第三方）
- 宿主版本：**0.2.0-rc.2**（desktop，win32 x64，Node 24.21.0）
- **全程零重启、零生产数据改动**（零重启基线：宿主进程组启动时间恒为 `2026-10-15 00:18:37`，见 `evidence/l4-env.md`）

---

## 一、四层方法

| 层 | 查什么 | 手段 | 是否需要重启 | 本次由谁完成 |
| --- | --- | --- | --- | --- |
| **L1 加载层** | 行是否挂载、是否 active | `plugin_manager list_plugins` 三次分页取全表（211 行），再按各包补丁里的 `insert.id` 反查 | 否 | 会话内采集 |
| **L2 能力层** | 插件声称的能力**在会话里真跑一次** | 真实工具调用 + 回环 HTTP 探测宿主路由（200/405/401 都算挂载成功） | 否 | 会话内采集 |
| **L3 契约层** | 代码里的服务调用是否**真的存在** | 扫插件源码 → 抽别名/直调 → 与 `cordis_inspect` 实时 Service 契约逐条比对 | 否 | **`audit-plugins.mjs` 自动** |
| **L4 依赖层** | 包路径 / 软链 / 补丁清单 / 依赖 / 兼容闸 | 文件系统 + `package.json` + `runtime.json` 比对（自带最小 semver） | 否 | **`audit-plugins.mjs` 自动** |

L3 正是抓出 `dsh-task-board` 的方法：**纯静态、零重启**。

## 二、结论速览

| 结论 | 数量 | 组合包 |
| --- | --- | --- |
| **可用** | 7 | `@deepseek-ai/dsh-base`、`@deepseek-ai/dsh-web-app`、`dshmarket`、`dsh-mcp-connector`、`cc-safety-net`、`@nanmicoder/dsh-agent-teams`、`@liustack/modlens` |
| **部分可用** | 8 | `dsh-sidenote`、`dsh-better-sidebar`、`deep-read-summarize`、`dsh-video-understand`、`dsh-genui`、`dsh-task-board`、`dsh-cost-meter`、`@linxin666/dsh-client-ui-skin-center` |
| **不可用** | 0 | —— |
| **未验证** | 5 | `auto-review`、`agent-team-profile`、`schedule-bundle`、`voice-input-bundle`、`dsh-context` |

「部分可用」的通常含义：**宿主半边已实测可用，客户端界面动作未验证**，或**能力被结构性削弱**（见缺陷 #1）。
「未验证」的每一包都在 `evidence.json` 里写明了**原因**与**验证路径**，没有一项是含糊带过。

> ⚠️ 诚实边界：本报告**没有**说「全部可用」。20 个里有 5 个是「未验证」，
> 原因是它们要验证就必须真实触发一次有副作用的动作（派验收、建队、建计划任务、开麦克风、写生产状态），
> 而本议题明确不做这类动作。**「未验证」是结论，不是遗漏。**

## 三、文件清单

| 文件 | 内容 |
| --- | --- |
| `audit-plugins.mjs` | 可复跑审计脚本（L3 契约比对 + L4 依赖检查 + 矩阵生成），只读 |
| `contracts.json` | 宿主 Service 契约快照（91 个服务），由 `cordis_inspect(host/Service.listService)` 导出 |
| `evidence.json` | 人工采集的 L1/L2 证据与结论（脚本不伪造，缺项一律标「未验证」） |
| `matrix.md` | **全量矩阵**：每包一行 = 声称能力 / L1–L4 / 结论，后附逐包自动证据明细 |
| `audit-result.json` | 机器可读的全量审计结果 |
| `findings.json` | 「调用了不存在 / 不兼容 API」的完整清单 |
| `service-refs.json` | 每个包引用了哪些服务与方法（含静默 catch 位置） |
| `defects.md` | **缺陷清单**：复现步骤 / 根因 / 影响面 / 处置建议（7 条） |
| `evidence/l1-rows.md` | L1 加载层原始证据（20 个包 → 实际挂载行） |
| `evidence/l2-probes.md` | L2 能力层原始证据（工具表、回环探测、真实调用记录） |
| `evidence/l4-env.md` | L4 依赖层原始证据（版本基准、软链、兼容闸、凭据、零重启基线） |
| `evidence/task-board-ledger.md` | **dsh-task-board 四轮补丁处置台账** |

## 四、怎么复跑

先决条件：只有 Node（本机用 DSH 自带那台即可），无第三方依赖。

```powershell
$node = "C:\Users\songzhenxi\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
cd E:\Works\DPT-vk-k-mv8b6x0z-6\plugin-audit
& $node audit-plugins.mjs                 # 重新生成 matrix.md / findings.json / audit-result.json
& $node audit-plugins.mjs --print         # 只打印 JSON，不写文件
```

可选参数：`--profile <dir>` 换 profile、`--out <dir>` 换产物目录、`--quiet` 静默。

### 复跑一致性自检（验收用）

产物**不含时间戳**，同一份输入两次运行应当逐字节一致：

```powershell
& $node audit-plugins.mjs --out .\repro-a --quiet
& $node audit-plugins.mjs --out .\repro-b --quiet
foreach ($f in 'matrix.md','findings.json','audit-result.json','service-refs.json') {
  $a = (Get-FileHash ".\repro-a\$f" -Algorithm SHA256).Hash
  $b = (Get-FileHash ".\repro-b\$f" -Algorithm SHA256).Hash
  "{0,-20} {1}" -f $f, ($(if ($a -eq $b) { '一致' } else { '不一致' }))
}
```

### 契约快照怎么更新

`contracts.json` 是**拍下来的宿主契约**，不是脚本自己连宿主拿的（脚本是普通 Node 进程，没这个权限）。
宿主升级后要重新拍：

1. 调用 `cordis_inspect_query(platform=host, provider=Service, method=listService)`；
2. 把结果整理成 `{ "services": { "<服务key>": { "methods": ["<方法签名>", …] } } }` 写入 `contracts.json`；
3. `node audit-plugins.mjs` 重跑，对比 `findings.json` 的差异。

（`evidence/` 下留了本次导出的原始形态说明；脚本顶部注释里有同样的提示。）

## 五、精度：三类误报是怎么处理的

静态扫描「服务调用点」最容易产出一堆假警报。脚本对三类情形做了显式处理，**每一条都在源码里复核过**：

1. **别名必须精确绑定**。`const x = ctx.svc` 才算别名；
   `const x = ctx.svc.method(...)`、`const x = ctx.svc?.field` **不算**。
   （否则 `const captain = ctx.agents.get(id)` 会把 `captain.steer()` 误报成 `agents.steer()` —— 实测确实发生过。）
2. **宿主 / 客户端分平面**。客户端半边（`exports["./client"]`、`src/client/**`、出现 `@deepseek-ai/dsh-client-*` 的文件）
   **不与宿主契约比对**，只登记引用。否则 `ctx.sessions.binding()` 这类客户端服务会被误报成宿主 services 服务缺方法。
3. **契约方法名剥泛型 / 装饰器**。`@Remote('modelCatalog') modelCatalog()` → `modelCatalog`；
   `open<S extends DomainSpec>(s)` → `open`。否则会把这两个真实存在的方法判成「不存在」。

另外还有两条降噪：

- **内联第三方运行时**（如 `dsh-genui` 里打包进去的 zod，它也用 `ctx` 命名）通过 esbuild 标记识别并分离，
  不计入宿主半边统计；
- **JS 内置同名方法**（`slice/filter/map/call/bind/…`）在服务确有同名=否时降级为 `low`，标注「需人工确认」。

**已知覆盖盲区（不隐藏）**：`cordis_inspect` 的 Service 目录**不枚举全部服务** ——
`webRuntime` 是真实服务（app.asar 内有 `const WEB_RUNTIME_SERVICE = "webRuntime"`），却不在目录里。
脚本用一份**带证据的显式白名单**处理，并把每个「不在目录、也未登记」的服务 key 收进
`unknownServiceKeys` 供人工复核。详见 `defects.md` #5。

## 六、本议题明确不做的

- **不做任何重启**。凡需重启才能验证的项，一律标注 `待 k-mv8ak8zi-4`（不假装验证过）。
- **不改生产数据**、**不动 DPT 仓库代码**（本目录是独立新增，未触碰 `dpt_extractor/` 等任何产品代码）。
- **不擅自卸载 / 停用任何插件**，也不改任何开关 —— `autoAccept` / `autoExec` 是用户手动设置的状态，只报告不处置。
