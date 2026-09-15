# NEXUS Assistant Workspace

本目录是 NEXUS 平台助手的专用 OpenCode Workspace，也是 Astra 内置的固定助手工程。

- Workspace 固定为仓库根目录下的 `nexus-assistant/`，不通过环境变量切换到外部目录。
- Agent、Skill、MCP 配置随 Astra 代码一起版本管理、评审和发布。
- 平台助手不运行在 Astra 源代码根目录，避免 Agent 获得不必要的代码修改能力。
- `edit` / `write` / `bash` / `webfetch` 权限默认全部拒绝。
- 平台能力通过 `nexus-assistant` MCP 暴露（`astra-assistant-mcp`）。
- 会话由 NEXUS Backend 创建和管理，本目录不保存业务数据。
- 平台事实、状态判定、权限与确认由 Backend 负责；Skill 只沉淀 Agent 的业务使用方法。

## Workspace 组成

- `opencode.json`：Workspace 级 OpenCode 配置、权限和本地 MCP 定义。
- `.opencode/agents/platform-assistant.md`：平台助手主 Agent。
- `.opencode/skills/`：按业务能力拆分的 Skill。
- `assistant-context/`：仅用于需要落盘的助手上下文，不保存平台业务主数据。

Astra 启动平台助手 OpenCode Server 时，以本目录作为 `cwd`。因此 OpenCode 会直接读取这里的 `opencode.json`、Agent 和 Skill，不依赖用户全局 OpenCode 配置。

## Agent

- `platform-assistant`（`.opencode/agents/platform-assistant.md`）：理解用户请求、选择 Skill、调用平台 Tool；变更类操作只 prepare，由平台向用户展示确认卡。

## Skills

- `nexus-task-ops`：任务查询、创建及取消/重试/恢复/重分配。
- `nexus-employee-routing`：员工搜索、详情和执行人推荐。
- `nexus-run-triage`：运行查询、失败现场解释和下一步判断。
- `nexus-knowledge-qa`：数字图书馆检索与有依据的知识问答。
- `nexus-operations-overview`：平台任务统计、待处理项和员工负载。

Skill 位于 `.opencode/skills/<name>/SKILL.md`，由 Agent 根据用户意图按需加载，不在每轮对话预加载全部内容。

## 本地调试

Backend 已安装到当前 Python 虚拟环境后，可直接进入本目录运行 OpenCode：

```bash
cd nexus-assistant
opencode
```

`opencode.json` 会在当前 Workspace 内启动 `astra-assistant-mcp`。正式运行时由 Astra 服务管理器使用相同 Workspace 启动 `opencode serve`。
