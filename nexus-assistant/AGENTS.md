# NEXUS Assistant Workspace

本目录是 NEXUS 平台助手的专用 OpenCode Workspace，固定随 Astra 仓库发布。

- `read` / `glob` / `grep` / `list` / `lsp` 允许，用于只读理解 Agent、Skill、配置和实现。
- `edit` / `write` / `bash` / `task` / `webfetch` / `websearch` / `external_directory` 默认拒绝。
- `nexus-assistant` MCP 提供任务、员工、运行、知识、运营、只读数据库兜底和经验候选提交能力。
- 会话由 Astra Backend 创建和管理，本目录不保存业务数据。
- 平台事实、状态判定、权限与确认由 Backend 负责；Skill 只沉淀方法、判断链和常见错误。

## Agent

`platform-assistant`（`.opencode/agents/platform-assistant.md`）负责：

1. 简单查询优先调用稳定 MCP Tool；
2. 复杂业务按需加载最少 Skill；
3. 现有 Tool 未覆盖所需读取能力时，先用只读文件检索或 `nexus_inspect` 补充事实；
4. 任务变更只 prepare，由平台向用户展示确认卡；
5. 出现明确学习信号时，通过 `nexus_experience_submit` 把可复用经验提交为数字图书馆 candidate，不直接修改 Skill。

## Skills

仅保留真正承载业务方法的三个 Skill：

- `nexus-task-ops`：任务创建/变更、复杂任务意图整理和任务内员工选择。
- `nexus-run-triage`：执行失败、超时、丢失、待人工等异常诊断和恢复判断。
- `nexus-knowledge-qa`：数字图书馆检索、正文读取和有依据回答。

员工简单查询、员工推荐、平台统计等一句话即可映射到 Tool 的能力不单独做 Skill。

Skill 位于 `.opencode/skills/<name>/SKILL.md`，由 Agent 根据用户意图按需加载。Skill 不重复 MCP 参数说明，也不复制 Backend 状态机。

## 读取兜底

查询优先级：

`稳定 MCP Tool → 仓库只读检索 → nexus_inspect`

`nexus_inspect` 用于尚未 MCP 化的只读数据排查，例如事件、调度状态、会话、环境详情和额外字段。它只允许受控 ORM 资源和字段，隐藏凭据类字段，最多返回 50 条，不支持任意 SQL 和任何写操作。

同一类 `nexus_inspect` 查询如果频繁出现，应升级为正式 MCP Tool，避免把兜底接口变成长期业务 API。

同一套检查逻辑也提供本地命令：

```bash
astra-assistant-inspect resources
astra-assistant-inspect describe events
astra-assistant-inspect query events --where task_id=TASK-xxx --order-by created_at --desc
```

该命令用于人工调试；Agent 本身不开放 Bash，而是通过 `nexus_inspect` 调用同一套只读逻辑。

## 经验迭代

经验闭环为：

`Skill 方法处理 → 用户纠正/有效修正/稳定新路径 → nexus_experience_submit(candidate) → 图书馆审核发布 → 后续 Skill 检索复用`

原则：

- 普通成功不沉淀；
- 模型猜测不沉淀；
- 一次性业务数据和临时环境异常不沉淀；
- 每条候选至少包含一条结构化证据；Tool 校验 `skill_name` 对应仓库内真实 Skill，并强制写入规范 Skill 标识；
- 当前请求是否实际加载该 Skill 由 Agent 路由规则约束，不把它伪装成 Backend 可验证事实；
- 复用数字图书馆经验提交流程，服务端只创建 candidate；
- 经验提交失败不阻塞当前任务；
- candidate 未审核发布前不能当作正式规则。

## 本地调试

```bash
cd nexus-assistant
opencode
```

OpenCode 会从当前 Workspace 读取 `opencode.json`、`AGENTS.md`、Agent 和 Skill，并启动工程内配置的 `astra-assistant-mcp`。
