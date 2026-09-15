# NEXUS Assistant Workspace

本目录是 NEXUS 平台助手的专用 OpenCode Workspace，固定随 Astra 仓库发布。

- 平台助手不运行在 Astra 源代码目录，避免获得不必要的代码修改能力。
- `edit` / `write` / `bash` / `webfetch` 默认拒绝。
- `nexus-assistant` MCP 提供任务、员工、运行、知识、运营和经验候选提交能力。
- 会话由 Astra Backend 创建和管理，本目录不保存业务数据。
- 平台事实、状态判定、权限与确认由 Backend 负责；Skill 只沉淀方法、判断链和常见错误。

## Agent

`platform-assistant`（`.opencode/agents/platform-assistant.md`）负责：

1. 简单查询直接调用 MCP Tool；
2. 复杂业务按需加载最少 Skill；
3. 任务变更只 prepare，由平台向用户展示确认卡；
4. 出现明确学习信号时，通过 `nexus_experience_submit` 把可复用经验提交为数字图书馆 candidate，不直接修改 Skill。

## Skills

仅保留真正承载业务方法的三个 Skill：

- `nexus-task-ops`：任务创建/变更、复杂任务意图整理和任务内员工选择。
- `nexus-run-triage`：执行失败、超时、丢失、待人工等异常诊断和恢复判断。
- `nexus-knowledge-qa`：数字图书馆检索、正文读取和有依据回答。

员工简单查询、员工推荐、平台统计等一句话即可映射到 Tool 的能力不单独做 Skill。

Skill 位于 `.opencode/skills/<name>/SKILL.md`，由 Agent 根据用户意图按需加载。Skill 不重复 MCP 参数说明，也不复制 Backend 状态机。

## 经验迭代

经验闭环为：

`Skill 使用 → 用户纠正/有效修正/稳定新路径 → nexus_experience_submit(candidate) → 图书馆审核发布 → 后续 Skill 检索复用`

原则：

- 普通成功不沉淀；
- 模型猜测不沉淀；
- 一次性业务数据和临时环境异常不沉淀；
- Tool 自动加入来源 Skill 标签，服务端只创建 candidate；
- 经验提交失败不阻塞当前任务；
- candidate 未审核发布前不能当作正式规则。

## 本地调试

```bash
cd nexus-assistant
opencode
```

OpenCode 会从当前 Workspace 读取 `opencode.json`、`AGENTS.md`、Agent 和 Skill，并启动工程内配置的 `astra-assistant-mcp`。
