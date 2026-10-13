## Why

`nexus/v1.0.1` 需要一套新的数字员工产品，而不是继续运行 Astra 的 Task / Worker / OpenCode 业务。第一阶段先定下 AgentScope 2.0 的事实源、对等协作方式和可运行的三页骨架，避免后面再长出第二套 Agent、Session 或模型配置。

## What Changes

- 将开发约定和 OpenSpec 背景改为 Nexus v1.0.1：Vue 3 + Element Plus、Python API、AgentScope 2.0.10 Agent Service。
- 清掉仍标为活跃的 Astra change。保留 OpenSpec 工作流、schema 和已归档历史；不把 Astra 历史 spec 改写成 Nexus 需求。
- 按仓库实况记录 Superpowers，不补写不存在的 skill。
- 钉住 AgentScope `2.0.10`，并按该 tag 的源码记录 Agent、Session、Skill、Knowledge 与 chat SSE。
- 新增独立的 `nexus/web` 与 `nexus/api` 骨架，覆盖员工管理、数字员工私聊和团队交流。对话失败时明确报告 AgentScope 不可用，不生成模拟回复。
- 写明 Agent Service 与 Redis 的部署方式，以及 `contact_employee` 如何借用 inbox、wakeup 和 MessageBus。

## Capabilities

### New Capabilities

- `agentscope-deployment`: 部署并钉住 AgentScope 2.0.10 Agent Service，Nexus 只通过 HTTP 使用它。
- `employee-directory`: 创建、查看、修改、启用和删除数字员工，技能列表来自 AgentScope。
- `private-employee-chat`: 一位员工对应多条私聊，每条私聊绑定一条 Session，回复只来自 Agent 推理。
- `team-peer-chat`: 团队讨论里的员工对等联系，不使用 Agent Team，也不由 Nexus 代写同事回复。

### Modified Capabilities

- 无。`openspec/specs/` 中的既有 capability 保持为 Astra 历史契约。

## Impact

- 新增 `nexus/`、根 `README.md`、`AGENTS.md`、`openspec/config.yaml`。
- AgentScope 与 Redis 作为外部服务。Nexus API 不依赖 AgentScope 的 Python 包。
- 原 `backend/`、`frontend/`、`workspace-ui/` 仍留在树里，但不再作为本分支的产品入口。
