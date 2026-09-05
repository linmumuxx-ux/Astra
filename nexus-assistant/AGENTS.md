# NEXUS Assistant Workspace

本目录是 NEXUS 平台助手的专用 OpenCode Workspace。

- 平台助手不运行在 NEXUS 源代码目录，避免 Agent 获得不必要的代码修改能力。
- `edit` / `write` / `bash` / `webfetch` 权限默认全部拒绝。
- 平台能力通过 `nexus-assistant` MCP 暴露（`astra-assistant-mcp`）。
- 会话由 NEXUS Backend 创建和管理，本目录不保存业务数据。

## Agent

- `platform-assistant`（`.opencode/agents/platform-assistant.md`）：
  理解用户请求，区分查询与操作，调用平台 Tool 获取事实，
  变更类操作必须先 prepare，由平台向用户展示确认卡。
