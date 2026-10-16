# 看板修正：授权类挂起在「用户已授权」后的解锁通道（k-mvae3o8m-29）

## 背景（事故）

`k-mv8yxm2n-15` 被**授权类挂起**（`failureControl.action='hold'`、`category='authorization'`）后，用户已按要求完成人工动作，
但看板没有任何入口能把它放回队列：

| 尝试入口 | 结果 |
|---|---|
| `kanban.moveIssue` → `todo` | 被 `retryGuard` 拦下（"失败原因尚未解除，禁止原地重试"） |
| `kanban.resolveFailure` | 被 `failure-resolution.mjs` 显式拒绝（"授权问题需专门的授权验证流程"） |
| 界面「解除阻塞」 | 复用同一个 `moveIssue`，同样被拒 |

**拒绝本身是对的**（诊断证据不等于授权），缺的是"用户已授权"这条路径。

## 改动（候选14，8 个模块里只改 3 个）

1. `lib/failure-resolution.mjs`：新增纯规则 `grantAuthorization(state, id, input, now)`
   - 只处理 `action==='hold' && category==='authorization'`（诊断类/修复类/配置类一律不走）；
   - 必须带与挂起对象一致的 `failureToken`（`fingerprint ?? holdReason`）；
   - 必须 `confirmed===true` 且写明人工动作（`note` ≥ 4 字）；
   - **同一 `failureToken` 只放行一次**（`authorizationGrants` 记账）；放行后 `action='recovered'`、`run=null`、`status='todo'`；
   - 原有 `resolveFailure` 判定一字未动（仍拒绝 authorization / repair / configuration）。
2. `lib/index.js`：
   - 新增 RPC `kanban.grantAuthorization`，来源校验用插件内部冻结对象 `CLIENT_ORIGIN`，
     只有 HTTP RPC 路由在"请求带 `x-kanban-client: board` 交互标记"时注入；agent 的动态工具是单参数调用、拿不到凭证；
   - **不注册**任何 agent 侧工具；`issueView` 暴露 `authorizationGrants` 供界面判断；
   - 授权成功写审计：user 评论（含授权指纹）+ `blocked→todo` 活动流（带 `authorizationToken`）。
3. `lib/client.js`：`call()` 每次 RPC 带交互标记；新增 `AuthorizationGrantView`
   （勾选"我已完成所需的人工动作/批准" + 授权说明 + 确认按钮）；
   - 详情页挂上该面板；授权类说明改为指向该面板；
   - 「受阻」列表的「解除阻塞」对 authorization 类**改为就地调出确认**，不再复用 `moveIssue`。

## 验证（全部在候选/在线副本上跑过）

| 环节 | 命令 | 结果 |
|---|---|---|
| 构建 | `node build14.mjs` | 候选14 生成；改动集合 = `client.js,failure-resolution.mjs,index.js`；构建前核对在线 8 模块 == 候选13 安装哈希 |
| 新增用例 | `node test14.mjs` | **14 组全绿**（纯规则 3 + 端到端 8 + 界面 3） |
| 全量回归 | `node verify-candidate.mjs candidate-14` | **31 套 238 组全绿，0 失败**（候选13 基线 30 套 224 组 + test14 的 14 组） |
| 变异检查 | `node mutation-check14.mjs` | **8/8 变异体全部被抓住**（去来源校验、给 agent 补工具、不校验令牌、不要求人工确认、去一次性限制、不解除 hold、界面复用 moveIssue、界面不带交互标记） |
| 安装 | `node install14.mjs` | 备份 `install-backup14-20261016-0354`；安装后 8 模块哈希匹配（3 个变化） |
| 独立核对 | `node verify-installed14.mjs` | 在线 8 模块哈希 == 清单 == 候选逐字节；**对在线已安装文件重跑 test14 通过 14 组** |

回归过程中发现并修掉一处**兼容性问题**：既有用例 `priority-components.test.mjs` 按
`function DiagnosticRecoveryView(` → `function DetailView(` 切片 client.js 再在 vm 里执行，
新组件若放在切片外，`DetailView` 引用它就报 `ReferenceError`。已把新组件放到该切片内（DiagnosticRecoveryView 与 DetailView 之间），
该套件恢复通过 —— 这是真实约束，不是测试噪声。

## 边界与未做

- 未重启 DSH（**需重启生效**），未改任何用户开关，未改 `E:\Works\DPT` 源码。
- 威胁模型说明：来源校验挡住的是"agent 的合规调用路径"（没有工具入口 + 无凭证即拒）。
  本地 Web 服务的原始 HTTP 直连理论上可以自带请求头伪装；这是本机同侪信任模型下的已知边界，未做加密级防伪。
- 同一失败指纹第二次受阻仍拒绝重复放行（按需求 ③④）；此时出口是换新证据（新指纹）或取消另立承接卡。

## 回滚

`deployment-core.mjs` 的 `rollback(journal,{safeWindow:true})`，journal =
`install-backup14-20261016-0354/installation.json`，未自动执行。
