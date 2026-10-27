## Why

Stage 3 要把已经跑起来的数字员工对话、任务和 Worker 收成一条工程闭环。AgentScope 2.0.10 已经提供 Session、Team、压缩、长期记忆和知识库，Nexus 不应再做第二套聊天、团队消息或记忆引擎。本变更先固定复用边界和实施顺序，审查通过前不改业务代码。

## What Changes

- 记录 Phase 2 HEAD `5215f6e3225f9e7c4f5df1352b1e653138c978e7` 与 AgentScope tag `v2.0.10`（`e6c014f0be49b2a6f6f62a9453082a0b975484e1`）的源码复用矩阵。
- 把规格里的新职责映射到现有表、API 和事件。能复用的不新建平行实体。
- 按「内网约 10 人、产品未发布、不兼容旧数据」记下规格中要简化或不做的条款。
- 给出按依赖排序、每批可独立验证的实施计划。`remote-worker-websocket` 已覆盖 S3-10 的通道主体，剩余缺口单列。
- 把与 Phase 1 决定或规格加固条款冲突、需要拍板的项单独列出，并给出未拍板时的默认做法。

本步只提交这三份文档。`specs/` 留到审查确认冲突项之后，按批次补写，避免在拍板前把未定行为写成契约。

## Capabilities

### New Capabilities

审查通过后按批次新增，名称先记在这里：

- `private-session-binding`：可信 UID 与岗位员工的唯一长期私聊绑定，历史读 AgentScope。
- `team-collaboration`：用 AgentScope Team / AgentInvite / TeamSay 做职责协作，并补上不触发推理的纯消息写入。
- `employee-memory`：装配一种原生长期记忆，并沿用 `ContextConfig` 压缩。
- `im-contract`：渠道无关的入站事件、出站投递和 ACK。公司 IM SDK 不在本仓。
- `repository-worker`：GitHub 仓库、加密 PAT、Worker 单仓绑定与配置复制。
- `employee-capability-binding`：在现有员工 JSON 和 Worker `status_detail` 里跟踪 desired/applied revision、发现结果和任务快照。不新建能力中心。
- `task-acceptance`：在现有投影上补齐结构化等待原因和人工终态。

### Modified Capabilities

- 无。`openspec/specs/` 里的 Astra 历史契约不改。

## Impact

- 对话与员工目录：`services/nexus-api`、`services/agent-service`、`web/nexus`。
- 任务、Worker、部署、复盘、图书馆：`services/task-platform`。
- 不改 Gateway 数据面和模型映射实现。部署只写 Worker 上 `opencode.jsonc` 的网关 provider。
- 不改 OpenCode 1.18.35 的重试，不把通信失败写成 Task 终态，不新增第二套状态机。`RuntimeService.apply_session_state()` 仍是唯一投影点。
- 本地和 e2e 的 OpenCode 模型使用 `opencode/deepseek-v4.1-flash-free`，不经过网关。
