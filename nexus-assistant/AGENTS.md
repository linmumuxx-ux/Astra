# NEXUS Assistant Workspace

本目录是 NEXUS 平台助手的专用 OpenCode Workspace。

- 平台助手不运行在 NEXUS 源代码目录，避免 Agent 获得不必要的代码修改能力。
- `edit` / `write` / `bash` / `webfetch` 权限默认全部拒绝。
- 平台能力通过 `nexus-assistant` MCP 暴露（`astra-assistant-mcp`）。
- 会话由 NEXUS Backend 创建和管理，本目录不保存业务数据。
- 平台事实、状态判定、权限与确认由 Backend 负责；Skill 只沉淀 Agent 的业务使用方法。

## Agent

- `platform-assistant`（`.opencode/agents/platform-assistant.md`）：理解用户请求、选择 Skill、调用平台 Tool；变更类操作只 prepare，由平台向用户展示确认卡。

## Skills

- `nexus-task-ops`：任务查询、创建及取消/重试/恢复/重分配。
- `nexus-employee-routing`：员工搜索、详情和执行人推荐。
- `nexus-run-triage`：运行查询、失败现场解释和下一步判断。
- `nexus-knowledge-qa`：数字图书馆检索与有依据的知识问答。
- `nexus-operations-overview`：平台任务统计、待处理项和员工负载。

Skill 位于 `.opencode/skills/<name>/SKILL.md`，由 Agent 根据用户意图按需加载，不在每轮对话预加载全部内容。
