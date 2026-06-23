# AGENTS.md 拆分迁移对照表

本文用于检查本次从单一 `AGENTS.md` 拆分到 `docs/*.md` 时是否遗漏规则。

## 新增协作规则

- 用户提供的“AI 工程协作增强规则”已迁移到 `AGENT_COLLABORATION.md`。
- 根目录 `AGENTS.md` 保留摘要和入口要求。

## 工具与 Skill 规则

- GitHub CLI 提权规则迁移到 `RELEASE_PROCESS.md`，并在 `AGENT_SKILLS_AND_TOOLS.md` 的通用原则中保留外部工具提权要求。
- Agent Skills 开放标准迁移到 `AGENT_SKILLS_AND_TOOLS.md`。
- 已安装 Skills 与 CLI 工具的自适应调用规则迁移到 `AGENT_SKILLS_AND_TOOLS.md`。

## 原 AGENTS.md 1-16 条迁移

| 原条目 | 主题 | 迁移位置 |
|---|---|---|
| 1 | GitHub CLI 提权、Windows 凭据管理器 | `RELEASE_PROCESS.md` |
| 2 | 参数计算默认禁止修改 | `ENGINEERING_RULES.md`、`AGENTS.md` |
| 3 | 不擅自新增弹窗/ToolTip/一次性提示 | `ENGINEERING_RULES.md`、`AGENTS.md` |
| 4 | Release exe 资产命名 | `RELEASE_PROCESS.md`、`AGENTS.md` |
| 5 | 波形通道标识贴 0 刻度 | `WAVEFORM_UI_SPEC.md` |
| 6 | 初始加载位置/通道标识布局时序 | `WAVEFORM_UI_SPEC.md` |
| 7 | 拖动通道标识性能热路径 | `WAVEFORM_UI_SPEC.md` |
| 8 | Tektronix 偏移测量定义 | `MEASUREMENT_SPEC.md` |
| 9 | 偏移测量表展示规则 | `WAVEFORM_UI_SPEC.md` |
| 10 | TSS 双脉冲黄金样例、分段、Eoff/Eon/Err/快照 | `MEASUREMENT_SPEC.md`、`REGRESSION_BASELINES.md` |
| 11 | 单脉冲仅关断口径 | `MEASUREMENT_SPEC.md`、`REGRESSION_BASELINES.md` |
| 12 | TSS Err 兼容性校准 | `MEASUREMENT_SPEC.md`、`REGRESSION_BASELINES.md` |
| 13 | Eoff/Eon/Err 损耗卡尺统一专业口径 | `MEASUREMENT_SPEC.md` |
| 14 | 波形交点示意点规则 | `WAVEFORM_UI_SPEC.md` |
| 15 | Trr 共用核心逻辑 | `MEASUREMENT_SPEC.md` |
| 16 | 全量 TSS 验证红线 | `REGRESSION_BASELINES.md`、`AGENTS.md` |

## 拆分后的阅读路径

- 只做普通代码或展示层小修：读 `AGENTS.md` 和 `ENGINEERING_RULES.md`。
- 做波形 UI、通道标识、交点、表格：再读 `WAVEFORM_UI_SPEC.md`。
- 做测量、提取、积分、斜率、平台线、Trr/Err：再读 `MEASUREMENT_SPEC.md` 和 `REGRESSION_BASELINES.md`。
- 做发布或 GitHub Release：再读 `RELEASE_PROCESS.md`。
- 做 Skill、CLI 或自动化工具相关任务：再读 `AGENT_SKILLS_AND_TOOLS.md`。
