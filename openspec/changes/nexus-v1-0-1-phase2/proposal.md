## Why

Phase 1 已经有可对话的 AgentScope 数字员工，但员工不能创建或跟踪真实工程任务。历史分支里的 Task Service、OpenCode 执行、环境运维、API 网关和数字图书馆是现成能力，本阶段要把它们接到员工身上，而不是再写一套任务系统。

## What Changes

- 记录 Phase 1 与 `codex/astra-updates-20261010`（`05dd7314`）的差异，以及按简报第二节划分的复用清单。
- 定下 Task、责任数字员工、Agent Worker、OpenCode Session 的数据关系，以及后续迁移顺序。
- 定下 Task MCP / Task Skill 如何注册进 AgentScope 2.0.10，以及任务状态事件如何用现有 inbox 与 wakeup 唤醒责任员工。
- OpenCode 执行模型默认 `deepseek-flash`（DeepSeek OpenAI 兼容接口 `https://api.deepseek.com`）。配置值使用现有适配器要求的 `deepseek/deepseek-flash`，仍可由环境变量或 Worker 覆盖。
- 本变更只提交方案。确认列出的架构取舍之前，不迁移代码、不改 Phase 1 对话行为。

## Capabilities

### New Capabilities

- `task-employee-worker`: 责任员工、执行 Worker 与 OpenCode Session 的职责和任务关联。
- `task-mcp-skill`: 员工通过 Task Skill 与 Task MCP 管理任务，MCP 只封装已有任务服务。
- `task-event-wakeup`: 任务关键状态经可靠、幂等的投递唤醒责任员工，员工再查询最新状态。

### Modified Capabilities

- 无。`openspec/specs/` 中的 Astra 历史契约不修改。Phase 1 的 `nexus-v1-0-1` change 也不改写。

## Impact

- 方案文件在 `openspec/changes/nexus-v1-0-1-phase2/`。
- 后续实现会接入 `backend/app` 的任务、运行时、网关和图书馆，并扩展 `nexus/` 的导航、员工配置和 Agent Service 启动脚本。
- Phase 1 的员工目录、私聊、团队交流和 `contact_employee` 保持为对话事实源。
- `domains/` 是历史提交之后另起的一套模型，不作为本阶段复用源。是否采纳这一点，见 design 的待确认项。
