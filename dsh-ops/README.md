# DSH 运维：重启与「重启后续跑验证」

> 本文件**只做指路与速查**，完整流程、源码证据与风险清单在 DSH 学习库中维护（避免两处各写一遍）。
>
> 规范文档（唯一来源）：
> - 流程（六步可照抄）：`E:\AI图书馆\DSH-学习库\03-运行时取证\2026-10-15-DSH重启续跑流程.md`
> - 起停途径与源码证据：`E:\AI图书馆\DSH-学习库\03-运行时取证\2026-10-15-DSH起停途径静态调研.md`
> - 脚本与标记模板：`E:\AI图书馆\DSH-学习库\03-运行时取证\脚本\dsh-restart-once.ps1`、`restart-request.example.json`

## 什么时候需要

改动**只在 DSH 启动时加载**的东西之后（插件代码、profile 的 `dsh.profile.bundles` 插件行、部分运行时常量），必须先重启 DSH 才能验证。

## 六步速查

1. **写标记**：`restart-request.json` 必须有 `expiresAt`（默认 10 分钟）与 `postRestartCheck`（写清"重启后要验什么"），缺一个脚本直接拒绝。
2. **先排续跑任务**（顺序不能反）：`schedule_create`，`after_seconds ≈ 150`，prompt 里逐字抄 `postRestartCheck`。
3. **触发**：
   ```powershell
   pwsh -NoProfile -File 'E:\AI图书馆\DSH-学习库\03-运行时取证\脚本\dsh-restart-once.ps1' `
        -Request .\restart-request.json -DelaySeconds 45
   ```
   自检用 `-DryRun`（不杀进程、不重启、不写锁、不标记 `usedAt`）。
4. **runner**：延时 → 结束 DSH → 重新拉起 → 自清理标记/锁/自身，过程写 `restart-runner.log`。
5. **重启后自动续跑**：宿主启动时即重新计算日程，到点把消息投进原会话（**不需要用户打开会话**；重启窗口内到期的会补投，可能重复一次，所以 prompt 要幂等）。
6. **回填结论**：写进被验证的议题；流程自身的问题回填 `k-mv8ak8zi-4`。

## 两个续跑通道

| 通道 | 机制 | 什么时候用 |
|---|---|---|
| 日程提醒（`@deepseek-ai/dsh-schedule`） | 宿主重启后 `requestDrive()` 重新计算，投递时 `resolveAgent` 恢复冷会话 | **默认必排** |
| 看板自动执行（`dsh-task-board`，本工作区 `autoExec` 已开启、间隔 60s） | 重启后插件重新加载，自动派发 `todo` 议题给新的 executor | 需要**独立执行者**做代码级核验时叠加 |

## 本机已知缺陷（**未修**，别当成"能用"）

| 编号 | 缺陷 | 后果 |
|---|---|---|
| D1 | 触发段的 WMI 路线被本机拒绝（`Invoke-CimMethod Win32_Process Create` **返回码 8**） | 触发即失败：写了 `usedAt`/锁/日志后退出，runner 从未生成，DSH 不会被关闭。替代候选 `schtasks` / `explorer` / 人工，均待实测 |
| D2 | "请求主窗口关闭"在 Windows 上只是**隐藏到托盘**，不是退出 | 真正停掉 DSH 的是随后的 `Stop-Process -Force`：**硬杀**，不是优雅退出 |
| D3 | 硬杀跳过应用收尾（`before-quit` / `finishQuit`） | 正在生成的回合、会话尾部、插件外部状态可能丢 |

## 红线

- 重启会**连带杀死并行议题的执行者**：动手前先确认没有别的任务在跑。
- 脚本只认白名单里的 DSH 可执行文件，不接受额外命令/参数；不做任意命令的重启后门。
- 不做常驻服务 / 常设计划任务（要的就是"临时、用完即弃"）；真机实测需**用户批准后由人执行**。
