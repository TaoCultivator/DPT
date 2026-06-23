# Agent Skills 与工具调用规则

本文记录 DPT 项目中对 Agent Skills、CLI 工具和外部工具调用的约定。

## 通用原则

- 遇到用户请求时，先根据任务类型选择最贴近的已安装 skill 或 CLI。
- 如果触发 skill，先完整读取对应 `SKILL.md` 再行动。
- 如果调用 CLI，优先使用全路径或确认 PATH 已刷新。
- 网络、GitHub、npm、pip、写入 `D:\AI-XG\CLI`、读取 Windows 凭据管理器等操作需按沙箱规则提权。

## Agent Skills 开放标准要点

- 创建或维护 skill 时遵循标准目录结构：`skill-name/SKILL.md` 必需，`scripts/`、`references/`、`assets/` 可选。
- `SKILL.md` 必须由 YAML frontmatter 加 Markdown 正文组成。
- frontmatter 中 `name` 和 `description` 必填。
- `name` 需 1-64 字符，只能使用小写字母/数字/连字符，不得以连字符开头或结尾，不得包含连续连字符，并且必须与父目录名一致。
- `description` 需 1-1024 字符，说明 skill 做什么以及什么时候使用，并包含有助于触发的关键词。
- `license`、`compatibility`、`metadata`、`allowed-tools` 为可选字段。
- 遵循渐进披露：启动时只依赖 `name`/`description`，触发后读取完整 `SKILL.md`，仅在需要时再读取 `scripts/`、`references/`、`assets/`。
- 主 `SKILL.md` 建议少于 500 行，较长细节拆到引用文件，文件引用使用相对路径并避免深层链式引用。
- 可用 `skills-ref validate ./my-skill` 校验格式和命名约束。
- 标准参考：https://agentskills.io/specification

## Skill 发现与安装

- 当用户问“有没有某类 skill”“找一个能做 X 的 skill”“安装某个 skill”时，优先使用 `find-skills` 搜索开放 skill 生态。
- 找到后再用 `skill-installer` 或来源仓库安装。
- 安装后提醒重启 Codex。

## 前端与视觉

- 新建或重做 UI、网页、组件、海报、主题、品牌风格时，优先考虑 `frontend-design`、`theme-factory`、`brand-guidelines`、`canvas-design`、`algorithmic-art`。
- 输出要能落地，避免模板感，并按项目现有技术栈实现。

## 文档、表格、幻灯片、PDF

- 处理 `.docx`、`.xlsx/.csv/.tsv`、`.pptx`、`.pdf` 时，分别优先使用 `docx`、`xlsx`、`pptx`、`pdf` skill。
- 需要共同写作或内部沟通稿时用 `doc-coauthoring`、`internal-comms`。
- 要求生成文件时做基本打开、渲染或命令验证。

## 开发与工具建设

- 涉及 Claude/Anthropic API 时用 `claude-api`。
- 构建 MCP Server 时用 `mcp-builder`。
- 创建或改进 skill 时用 `skill-creator`。
- 复杂 HTML/React artifact 用 `web-artifacts-builder`。
- 本地 Web 应用测试、截图、浏览器日志用 `webapp-testing`。

## 文本润色

- 用户要求“去 AI 味”“更自然”“不像 AI 写的”时使用 `humanizer`。
- 保留原意和事实，不凭空添加信息。

## OpenCLI

- 浏览器/网站/登录态网页自动化、把网站变 CLI、调用小红书/B 站/知乎/Twitter/Reddit/HackerNews 等适配器时，优先使用 `opencli`。
- 安装目录：`D:\AI-XG\CLI\opencli`
- 命令：`opencli`
- 若当前终端识别不到，使用 `D:\AI-XG\CLI\opencli\opencli.cmd` 或临时追加 `$env:Path += ';D:\AI-XG\CLI\opencli'`。
- 使用前先跑 `opencli doctor` 确认 Browser Bridge extension connected。

## CLI-Anything / CLI-Hub

- 需要发现、搜索、安装、更新、卸载社区 CLI harness 或面向桌面软件的 agent-native CLI 时，优先使用 `cli-hub`。
- 安装目录：`D:\AI-XG\CLI\CLI-Anything`
- 命令：`cli-hub`
- 若 PATH 未刷新，使用 `D:\AI-XG\CLI\CLI-Anything\.venv\Scripts\cli-hub.exe`。
- 常用命令：`cli-hub list`、`cli-hub search <query>`、`cli-hub info <name>`、`cli-hub install <name>`、`cli-hub launch <name>`。

## Playwright CLI

- 需要从终端驱动 Playwright 浏览器会话、截图、PDF、网络请求、标签页和本地浏览器自动化时，使用 `playwright-cli`。
- 安装目录：`D:\AI-XG\CLI\playwright-cli`
- 命令：`playwright-cli`
- 若 PATH 未刷新，使用 `D:\AI-XG\CLI\playwright-cli\playwright-cli.cmd`。

## 选择优先级

- 已有专用 skill 能覆盖任务时先用 skill。
- 任务依赖真实浏览器登录态或网站适配器时用 `opencli`。
- 任务是发现/安装大量外部 CLI 时用 `cli-hub`。
- 任务是 Playwright 级浏览器控制时用 `playwright-cli`。
- 如果多个工具都能做，优先选择最少副作用、最贴近用户目标的工具，并在执行前说明会用哪个。
