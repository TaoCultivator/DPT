# 已装插件真实可用性审计（DPT · 看板议题 `k-mv8b6x0z-6`）

**这份目录回答一个问题：装上的插件，真的能用吗？**

立案理由：`dsh-task-board` 在插件列表里 `enabled=true / fiberPhase=active`，界面能开、能建议题、能拖状态，
但它的落盘写入路径**从安装第一天起就是死的**（调了 `shell.run`，而 DSH 的 shell 服务只有 `resolve` + `execute`），
一路查到第四次补丁才靠临时诊断日志抓到 `TypeError: shell.run is not a function`。
**「加载成功」与「真的能用」之间没有任何保证** —— 这套审计就是来补这个保证的。

- 审计对象：`C:\Users\songzhenxi\.dsh\profiles\desktop` 的 `dsh.profile.bundles` 全部 **20 个**组合包
  （6 官方 + 14 第三方）
- 宿主版本：**0.2.0-rc.2**（desktop，win32 x64，Node 24.21.0）
- **全程零重启、零生产数据改动**。零重启基线：宿主进程组（主进程 PID 60356）启动于 `2026-10-15 00:32:32`，
  本议题执行期间（01:01–01:2x）**一次未变**；期间**未改任何插件代码、未动任何开关**
- 本目录为**复核轮**产物：首轮（00:2x）已在同一分支提交，本轮重跑了全部自动层、刷新了 L1/L2 证据，
  并修掉了审计方法自身的 6 处误报/漏报（见 `defects.md` 附一）

---

## 一、四层方法

| 层 | 查什么 | 手段 | 是否需要重启 | 本次由谁完成 |
| --- | --- | --- | --- | --- |
| **L1 加载层** | 行是否挂载、是否 active，**声明的行是否都挂上了** | 实时行表三次分页（211 行）→ `live-entries.json`；再与各包 `cordis.patch.yml` 声明的 id **逐条比对** | 否 | 快照手采 + **`audit-plugins.mjs` 自动比对** |
| **L2 能力层** | 插件声称的能力**在会话里真跑一次** | 真实工具调用 + 回环 HTTP 探测宿主路由（200/405/401 都算挂载成功） | 否 | 会话内采集 |
| **L3 契约层** | 代码里的服务调用是否**真的存在** | 扫插件源码 → 抽别名/直调 → 与 `cordis_inspect` 实时 Service 契约逐条比对；**探测器自身由 `self-check.mjs` 用合成对照组验灵敏度** | 否 | **`audit-plugins.mjs` 自动** |
| **L4 依赖层** | 包路径 / 软链 / 补丁清单 / 依赖 / 兼容闸 / **官方包（app.asar 内）** | 文件系统 + `package.json` + **asar 头部直读** + 自带最小 semver | 否 | **`audit-plugins.mjs` 自动** |

L3 正是抓出 `dsh-task-board` 的方法：**纯静态、零重启**。

## 二、结论速览

| 结论 | 数量 | 组合包 |
| --- | --- | --- |
| **可用** | 7 | `@deepseek-ai/dsh-base`、`@deepseek-ai/dsh-web-app`、`dshmarket`、`dsh-mcp-connector`、`cc-safety-net`、`@nanmicoder/dsh-agent-teams`、`@liustack/modlens` |
| **部分可用** | 8 | `dsh-sidenote`、`dsh-better-sidebar`、`deep-read-summarize`、`dsh-video-understand`、`dsh-genui`、`dsh-task-board`、`dsh-cost-meter`、`@linxin666/dsh-client-ui-skin-center` |
| **不可用** | 0 | —— |
| **未验证** | 5 | `auto-review`、`agent-team-profile`、`schedule-bundle`、`voice-input-bundle`、`dsh-context` |

自动层的硬指标：

| 指标 | 值 |
| --- | --- |
| 静态可扫组合包 | **20 / 20**（官方 6 包经 app.asar 直读，首版的「不可达」已作废） |
| L1 逐 id 比对 | **18 / 20** 完成，缺失行 **0**、异常非 active **0**（base/web-app 未比对，原因见 `evidence/l1-rows.md`） |
| L3 契约缺陷 | blocker **0** · high **1** · medium **0** · low **2** |
| 静默 catch | 宿主半边 **320**（客户端半边另计 254） |
| 探测器自检 | **9 / 9 对照组通过**（含 `shell.run` 正例与 4 个误报反例） |

「部分可用」的通常含义：**宿主半边已实测可用，客户端界面动作未验证**，或**能力被结构性削弱**（见缺陷 #1）。
「未验证」的每一包都在 `evidence.json` 里写明了**原因**与**验证路径**，没有一项是含糊带过。

> ⚠️ 诚实边界：本报告**没有**说「全部可用」。20 个里有 5 个是「未验证」，
> 原因是它们要验证就必须真实触发一次有副作用的动作（派验收、建队、建计划任务、开麦克风、写生产状态），
> 而本议题明确不做这类动作。**「未验证」是结论，不是遗漏。**

## 三、文件清单

| 文件 | 内容 |
| --- | --- |
| `audit-plugins.mjs` | 可复跑审计脚本（L1 行表比对 + L3 契约比对 + L4 依赖/asar 检查 + 矩阵生成），只读 |
| `self-check.mjs` | **探测器自检**：9 个合成对照组，验证扫描器「该报的报、不该报的不报」 |
| `contracts.json` | 宿主 Service 契约快照（91 个服务），由 `cordis_inspect(host/Service.listService)` 导出 |
| `live-entries.json` | 实时行表快照（用户侧 20 包对应的行），手采自 `plugin_manager list_plugins` |
| `evidence.json` | 人工采集的 L1/L2 证据与结论（脚本不伪造，缺项一律标「未验证」） |
| `matrix.md` | **全量矩阵**：每包一行 = 声称能力 / L1–L4 / 结论，后附逐包自动证据明细 |
| `audit-result.json` | 机器可读的全量审计结果（含 `liveStatus` / `declaredIds` / `weakUnknownKeys`） |
| `findings.json` | 「调用了不存在 / 不兼容 API」的完整清单 |
| `service-refs.json` | 每个包引用了哪些服务与方法（含静默 catch 位置、未知服务 key 分桶） |
| `defects.md` | **缺陷清单**：复现步骤 / 根因 / 影响面 / 处置建议（7 条 + 方法精度修正 + 更正记录） |
| `evidence/l1-rows.md` | L1 加载层证据（逐 id 比对表 + 一个反例） |
| `evidence/l2-probes.md` | L2 能力层证据（工具表 91 条、回环探测、真实调用记录） |
| `evidence/l4-env.md` | L4 依赖层证据（asar 读法、软链、兼容闸、凭据、零重启基线） |
| `evidence/task-board-ledger.md` | **dsh-task-board v1→v5 五轮补丁处置台账**与验证窗口 |

## 四、怎么复跑

先决条件：只有 Node（本机用 DSH 自带那台即可），无第三方依赖。

```powershell
$node = "C:\Users\songzhenxi\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
cd E:\Works\DPT-vk-k-mv8b6x0z-6\plugin-audit
& $node audit-plugins.mjs                 # 重新生成 matrix.md / findings.json / audit-result.json
& $node audit-plugins.mjs --print         # 只打印 JSON，不写文件
& $node self-check.mjs                    # 探测器自检（退出码 0 = 9 个对照组全部符合预期）
```

可选参数：`--profile <dir>` 换 profile、`--out <dir>` 换产物目录、`--asar <app.asar>` 换官方包来源、
`--live <live-entries.json>` 换行表快照、`--quiet` 静默。

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

本机实测：4 个产物两次运行**逐字节一致**，且与提交版本一致。

### 契约快照怎么更新

`contracts.json` 是**拍下来的宿主契约**，不是脚本自己连宿主拿的（脚本是普通 Node 进程，没这个权限）。
宿主升级后要重新拍：

1. 调用 `cordis_inspect_query(platform=host, provider=Service, method=listService)`；
2. 把结果整理成 `{ "services": { "<服务key>": { "methods": ["<方法签名>", …] } } }` 写入 `contracts.json`；
3. `node audit-plugins.mjs` 重跑，对比 `findings.json` 的差异。

同理，`live-entries.json`（实时行表）也要重采：它是 L1 「声明的行是否真挂上」的唯一来源。

## 五、精度：误报与漏报是怎么处理的

静态扫描最容易产出一堆假警报。下面每一条都在源码里复核过，并已固化成 `self-check.mjs` 的对照组：

1. **注释必须先剥掉**。`dshmarket/lib/verify.js` 在注释里写了 `const forms = ctx.configForms; forms.get("x")`
   当反例 —— 不剥注释就会产出「`configForms.get` 不存在」的假警报（本机实测）。现在扫描前把注释替换成等长空格（行号不变）。
2. **别名必须精确绑定**。`const x = ctx.svc` 才算别名；
   `const x = ctx.svc.method(...)`、`const x = ctx.svc?.field`、**`const x = ctx.svc(...)`（调用）都不算**。
   （否则 `const captain = ctx.agents.get(id)` 会把 `captain.steer()` 误报成 `agents.steer()`；
   `const handle = ctx.plugin(…)` 会把 `handle.dispose()` 误报成服务 `plugin`。）
3. **`ctx.get` 是反射访问器，不是服务**。`const get = ctx.get; get.call(ctx, name)`
   不得被当成「服务 `get` 的方法 `call`」。
4. **宿主 / 客户端分平面**。客户端半边（`exports["./client"]`、`src/client/**`、出现 `@deepseek-ai/dsh-client-*` 的文件）
   **不与宿主契约比对**，只登记引用。
5. **契约方法名剥泛型 / 装饰器**。`@Remote('modelCatalog') modelCatalog()` → `modelCatalog`；
   `open<S extends DomainSpec>(s)` → `open`。
6. **未知服务 key 分两桶**：`ctx.get('名字')` / `inject` 是**显式按名字要服务**（强信号，进 `unknownServiceKeys`）；
   `ctx.<key>.<method>()` 属性访问是弱信号（打包进来的第三方运行时也这么写，如 genui 内联 zod 的 `ctx.data.entries()`），
   进 `weakUnknownKeys`，**不据此下结论**。
7. **内联第三方运行时**（`__commonJS(` / `__toCommonJS(` / `__require(` 标记）单独计，不计入插件自身统计。

**已知覆盖盲区（不隐藏）**：`cordis_inspect` 的 Service 目录**不枚举全部服务** ——
`webRuntime` 是真实服务（app.asar 内可读到 `const WEB_RUNTIME_SERVICE = "webRuntime"`），却不在目录里。
脚本用一份**带证据的显式白名单**处理，并把每个「不在目录、也未登记」的服务 key 收进上面那两个桶供人工复核。
另：**客户端 Service 契约本机不可达**（`cordis_inspect(platform=client)` 两次调用均 10s 超时），
因此客户端半边只登记引用、不做契约比对（矩阵里逐包标注）。

## 六、本议题明确不做的

- **不做任何重启**。凡需重启才能验证的项，一律标注 `待 k-mv8ak8zi-4`（不假装验证过）。
  （宿主在 00:32:31 被**外部**重启过一次 —— 不是本议题做的；它顺带给 v5 提供了一次真实启动窗口，
  证据与边界见 `evidence/task-board-ledger.md`。）
- **不改生产数据**、**不动 DPT 仓库代码**（本目录是独立新增，未触碰 `dpt_extractor/` 等任何产品代码）。
- **不擅自卸载 / 停用任何插件**，也**不改任何开关** —— `autoAccept` / `autoExec` 是用户手动设置的状态，只报告不处置。
  （首轮曾把一个用户手动开的开关当故障关掉，随后已恢复；更正与教训见 `defects.md` 附三。）
