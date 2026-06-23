# AGENTS.md

本文件是 Codex/AI 进入 DPT 项目后的入口规范。只放最高优先级规则和详细规范索引；具体口径、样例快照、发布流程和工具规则放在 `docs/*.md` 中维护。

## 使用原则

- 开始任务前，先判断任务类型，并阅读下方对应规范文件。
- 涉及参数计算、提取、测量、积分、斜率、时间窗、平台线、损耗窗口、Trr/Err 或光标落点的改动，必须先阅读 `docs/MEASUREMENT_SPEC.md` 和 `docs/REGRESSION_BASELINES.md`。
- 涉及波形显示、通道标识、交点示意点、表格展示或交互性能的改动，必须先阅读 `docs/WAVEFORM_UI_SPEC.md`。
- 涉及发布、打包、GitHub Release、推送或远端认证的操作，必须先阅读 `docs/RELEASE_PROCESS.md`。
- 涉及 Skill、CLI、OpenCLI、Playwright CLI 或外部工具选择的任务，必须先阅读 `docs/AGENT_SKILLS_AND_TOOLS.md`。

## 最高优先级红线

- 参数数值的计算千万别改；涉及提取、测量、积分、斜率、时间窗等计算逻辑时，除非用户明确要求，否则只允许改展示层、交互层或样式。
- 不要擅自新增弹窗提示、悬浮提示（ToolTip）或一次性提示；如确实需要，必须先说明用途并获得用户明确同意。
- GitHub CLI 发布、上传 Release、推送等涉及远端认证的操作，需要使用 `sandbox_permissions="require_escalated"` 提权执行。
- GitHub Release 资产命名必须沿用历史规则：上传的 Windows exe 统一命名为 `DPT_Windows_vX.Y.Z.exe`。
- 凡是修改 TSS 提取、脉冲分段、平台线、损耗窗口、光标落点、积分、斜率、Trr/Err 或任意会影响参数数值的逻辑，完成后必须清理/绕开旧验证缓存，使用 `示例文件` 下全部原始 `.tss` 文件重新跑全量验证训练，并同时覆盖双脉冲与单脉冲样例。
- 全量验证失败、异常数增加、单脉冲被误判为双脉冲、或任一重点样例数值无依据漂移时，不能交付。

## AI 协作方式

- 如果用户需求直接跳到实现，先反问或澄清产品目标、用户场景和成功标准，避免为了做功能而做功能。
- 当发现用户可能把“实现方案”误当成“真实需求”时，主动区分：用户目标、当前方案、可选方案、推荐方案。
- 涉及架构、状态管理、数据模型、权限、依赖、路由、主要 UI 结构的变更时，必须先说明技术判断依据。
- 每次重要实现前，简短列出：本次改动影响范围、可能破坏的模块、验证方式。
- 如果存在多个实现路径，给出至少两个方案，并比较复杂度、扩展性、风险和开发成本，再推荐一个。
- 不允许为了短期跑通而引入长期难维护的临时方案；如必须临时处理，必须标记 TODO、说明原因。

## 文档同步

- 大的功能、信息架构、数据结构、权限模型或主要布局调整，都要询问用户是否同步更新项目规范，并提出更新大纲。
- 发现代码实现与规范文件偏离时，必须说明偏离点、偏离原因和潜在影响，并请用户选择：更新代码、更新文档，或记录偏差原因。

## 详细规范索引

- AI 工程协作规则：`docs/AGENT_COLLABORATION.md`
- Agent Skills 与工具调用规则：`docs/AGENT_SKILLS_AND_TOOLS.md`
- 工程开发红线：`docs/ENGINEERING_RULES.md`
- 发布、打包与 GitHub Release：`docs/RELEASE_PROCESS.md`
- 参数测量与损耗口径：`docs/MEASUREMENT_SPEC.md`
- 波形界面与交互规则：`docs/WAVEFORM_UI_SPEC.md`
- TSS 回归样例、数值快照与全量验证：`docs/REGRESSION_BASELINES.md`
- 本次拆分迁移对照表：`docs/AGENTS_MIGRATION_MAP.md`
