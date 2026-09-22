# NEXUS · 数字空间——平台助手方案设计文档

> 状态：已按本方案落地第一版（后端 `backend/app/assistant/`、MCP Server `astra-assistant-mcp`、
> 项目级 Agent 与 Skill（`.opencode/`）、前端 `frontend/src/features/assistant/`）。
>
> 更新：平台助手已不再拥有独立 Workspace；它以 Astra 项目根目录作为能力加载上下文，
> 使用项目级 `opencode.json` 与 `.opencode/`，但仍保留独立 OpenCode Runtime 与 Session。

## 1. 总体方案

平台助手采用四层结构：

```text
┌───────────────────────────────────────────────┐
│                NEXUS Frontend                 │
│                                               │
│ Assistant Drawer                              │
│ Conversation UI                               │
│ Business Cards                                │
│ Confirm Dialog                                │
└──────────────────────┬────────────────────────┘
                       │
                       │ REST + SSE
                       ▼
┌───────────────────────────────────────────────┐
│              NEXUS Backend                    │
│                                               │
│ Assistant API                                 │
│ Conversation Service                          │
│ Assistant Orchestrator                        │
│ Context Service                               │
│ Permission / Confirmation                     │
│ OpenCode Adapter                              │
│ Tool Gateway                                  │
└───────────────┬───────────────────┬───────────┘
                │                   │
                │                   │
                ▼                   ▼
┌──────────────────────┐   ┌────────────────────┐
│   opencode serve     │   │ NEXUS Domain       │
│                      │   │                    │
│ platform-assistant   │   │ Task               │
│ Session              │   │ Run                │
│ LLM                  │   │ Employee           │
│ MCP tools            │   │ Knowledge          │
└──────────┬───────────┘   │ Operations         │
           │               └─────────▲──────────┘
           │                         │
           └──── Tool / MCP ─────────┘
```

核心原则：

**OpenCode 是 Agent Runtime，NEXUS Backend 是业务控制面。**

---

# 2. 服务职责

## 2.1 Frontend

只负责：

* 会话展示；
* 消息输入；
* SSE 接收；
* 业务卡片渲染；
* 用户确认；
* 页面跳转；
* 当前页面上下文传递。

Frontend 不直接：

* 调用 opencode serve；
* 调用 MCP；
* 解析 OpenCode 内部 Tool Call；
* 判断业务权限；
* 创建 Task。

---

# 3. Assistant Backend

实现目录：

```text
backend/app/assistant/
```

目录结构（按本仓库既有扁平约定落地）：

```text
assistant/
├── api.py              # REST + SSE API
├── service.py          # Conversation Service
├── orchestrator.py     # Assistant Orchestrator
├── context_service.py  # Context Service
├── operations.py       # Permission / Confirmation（prepare → confirm）
├── client.py           # OpenCode Adapter
├── tool_gateway.py     # Tool Gateway（nexus_* 业务实现）
├── mcp_server.py       # NEXUS Assistant MCP Server
├── event_hub.py        # 平台 SSE 事件总线
├── event_mapper.py     # OpenCode Event → Assistant Event
├── cards.py            # 业务卡片统一协议
├── schemas.py
└── models.py
```

---

# 4. OpenCode Server 部署

建议：

```text
opencode serve
--hostname 127.0.0.1
--port 4096
```

禁止对用户网络直接开放 4096。

架构：

```text
Browser
   ↓
NEXUS Backend
   ↓
localhost / internal network
   ↓
OpenCode Server
```

生产环境配置：

```text
OPENCODE_SERVER_USERNAME
OPENCODE_SERVER_PASSWORD
```

由 Backend 持有认证信息。

Browser 不接触 OpenCode 密码。

实现说明：平台助手默认使用独立的 `ASTRA_ASSISTANT_OPENCODE_PORT=4097`，
与数字员工执行用的 4096 完全隔离；也可通过 `ASTRA_ASSISTANT_OPENCODE_URL`
指向既有共享服务（会话仍按目录隔离）。

---

# 5. OpenCode 项目

平台助手是 Astra 项目内置 Agent，不拥有独立 Workspace。它以 Astra 项目根目录作为
OpenCode 的能力加载上下文，直接使用项目级配置：

```text
Astra/
├── opencode.json          # providers / models / MCP / permissions
└── .opencode/
    ├── agents/
    │   └── platform-assistant.md
    ├── commands/
    └── skills/
        └── nexus-task-experience-review/
```

启动助手 OpenCode Server 时以其项目根为工作目录，加载上述项目配置；不创建、不复制、
不运行时拼装任何助手专属 `opencode.json`。

以项目根为加载上下文不代表允许修改源码：助手通过 Agent 权限与 `nexus-assistant` MCP
约束能力，见第 7 节。

---

# 6. Agent 定义

建立：

```text
platform-assistant
```

职责：

1. 理解用户请求；
2. 判断查询还是操作；
3. 调用平台 Tool 获取事实；
4. 判断必要参数是否缺失；
5. 生成结构化操作请求；
6. 根据 Tool 结果回答用户；
7. 不承担 Task 长时间执行。

---

# 7. OpenCode 权限

平台助手禁止默认 Coding 工具。

`.opencode/agents/platform-assistant.md` frontmatter：

```json
{
  "permission": {
    "edit": "deny",
    "write": "deny",
    "bash": "deny",
    "webfetch": "deny"
  }
}
```

平台能力通过专用 MCP / Tool 暴露。

查询类：

```text
allow
```

变更类可以在 OpenCode 侧配置 ask，但平台不能把 OpenCode 权限当作唯一安全机制。

真正的业务授权仍由 NEXUS Backend 完成。

---

# 8. 平台 Tool 设计

统一前缀：

```text
nexus_
```

不暴露数据库表和内部 Repository 方法。

Tool 采用平台业务语义。

---

# 9. Task Tools

## nexus_task_search

用途：搜索任务。

## nexus_task_get

## nexus_task_prepare_create

注意：第一步不要直接 create，先 prepare。

后端完成：参数校验、员工资格校验、权限校验、默认值补充、Task 名称生成、风险级别计算。

返回：

```json
{
  "operation_id": "OP-xxx",
  "requires_confirmation": true,
  "preview": {}
}
```

## 确认

只有用户点击确认后，前端调用
`POST /api/assistant/operations/{operation_id}/confirm`，由后端真正执行。

## nexus_task_prepare_retry / nexus_task_prepare_cancel / nexus_task_prepare_resume / nexus_task_prepare_reassign

同样采用 prepare → confirm。

不得让 Agent 直接完成高风险状态改变。运行中的任务取消按 L3 风险处理。
重分配按 L2 风险处理，仅对待领取或已挂起任务开放，并由后端重新校验目标员工的启用状态、任务类型和分类资格。

---

# 10. Employee Tools

```text
nexus_employee_search
nexus_employee_get
nexus_employee_recommend
```

推荐 Tool 由平台规则决定，返回候选员工和推荐原因。

不要让模型自己按照员工名字猜。

---

# 11. Run Tools

```text
nexus_run_get
nexus_run_search
nexus_run_failure_summary
```

`failure_summary` 由后端汇总 executor_error、退出码、当前进展等，再交给模型解释。

---

# 12. Knowledge Tools

```text
nexus_knowledge_search
nexus_knowledge_get
```

返回 knowledge_id、title、summary、space、tags、updated_at、route。

模型只根据真实返回内容回答。

---

# 13. Operations Tools

```text
nexus_operation_overview
nexus_operation_pending_actions
nexus_operation_employee_load
```

统计必须由数据库 / Backend 计算，不要先把大量任务全部发给模型再让模型自己数。

---

# 14. Tool 接入方式

```text
OpenCode
   ↓
NEXUS MCP Server（astra-assistant-mcp）
   ↓
Tool Gateway → Domain Service
```

MCP 不直接访问数据库表，统一调用已有 Domain Service / Tool Gateway，
避免形成两套业务规则。

---

# 15-20. 数据模型

* `assistant_conversations`
* `assistant_messages`
* `assistant_message_parts`
* `assistant_context_refs`
* `assistant_operations`（operation_id 同时作为幂等键）
* `assistant_tool_calls`

详见 `backend/app/assistant/models.py` 与迁移
`backend/alembic/versions/0013_assistant.py`。

---

# 21-25. 会话、消息与 SSE

* Conversation 与 OpenCode Session 一一对应；
* 消息发送使用 `prompt_async` + SSE；
* 前端接收平台自己的 SSE（`assistant.*` 事件），不依赖 OpenCode Event Schema；
* 事件映射集中在 `event_mapper.py`，将来 OpenCode 升级只改 Adapter。

---

# 26-27. 用户确认流程

Agent 调用 prepare 工具 → Backend 推送 `assistant.operation.confirm_required`
→ 前端渲染确认卡 → 用户点击确认 →
`POST /api/assistant/operations/{operation_id}/confirm` →
权限检查 / 状态检查 / 幂等检查 → 调用 Domain Service 真正执行 → 记录结果。

**不再把“用户确认”重新发给模型，再让模型决定要不要调用工具。**

修改确认内容：点击“修改”将预览内容回填输入区，重新走一遍 prepare 流程；
旧 Operation 由用户取消（`CANCELLED`）。

---

# 28-29. 页面上下文与 Agent Context

Frontend 每次发送消息附带 `page_context`；Backend 按权限重新查询真实对象，
不把前端对象作为可信数据。发送给 OpenCode 的上下文只包含当前用户、页面、
业务对象 ID、会话关联对象和平台时间；其余信息由 Agent 调 Tool 查询。

---

# 30. Assistant API

```text
POST   /api/assistant/conversations
GET    /api/assistant/conversations
GET    /api/assistant/conversations/{id}
DELETE /api/assistant/conversations/{id}

POST /api/assistant/conversations/{id}/messages
GET  /api/assistant/conversations/{id}/messages
POST /api/assistant/conversations/{id}/abort

GET  /api/assistant/conversations/{id}/events     (text/event-stream)

GET  /api/assistant/operations/{id}
POST /api/assistant/operations/{id}/confirm
POST /api/assistant/operations/{id}/cancel

GET  /api/assistant/health
```

---

# 31-36. OpenCode Adapter、健康检查、超时、Abort、崩溃恢复、历史控制

* 业务层只依赖 `AssistantOpenCodeClient`；
* `GET /api/assistant/health` 供平台管理页展示；
* OpenCode 不健康时助手入口仍存在但显示服务异常，不影响平台核心功能；
* 停止助手生成 ≠ 取消已创建的业务 Task；
* OpenCode Session 丢失时自动重建并恢复最近对话摘要；
* 长会话采用最近消息 + 摘要 + Context Refs + 实时 Tool 查询。

---

# 37-40. 前端

实现目录：

```text
frontend/src/features/assistant/
├── AssistantLauncher.vue
├── AssistantDrawer.vue
├── MessageList.vue
├── MessageInput.vue
├── ContextBar.vue
├── cards/
│   ├── BusinessCard.vue
│   └── ConfirmCard.vue
├── api.ts
├── store.ts
└── types.ts
```

前端状态区分：

```text
IDLE / SUBMITTING / THINKING / TOOL_RUNNING / WAITING_CONFIRM / STREAMING / COMPLETED / FAILED
```

业务卡片统一协议（后端确定性生成，模型不得直接控制任意 URL）：

```json
{
  "card_type": "task",
  "id": "TASK-001",
  "title": "...",
  "status": "RUNNING",
  "fields": [],
  "actions": [
    { "type": "navigate", "label": "查看任务", "target": "/tasks/TASK-001" },
    { "type": "assistant_operation", "label": "取消任务", "operation": "task_cancel" }
  ]
}
```

---

# 41-43. 权限、身份与 Prompt Injection 防护

* 用户身份由后端注入（`ASTRA_ASSISTANT_USER_ID`），不信任模型提供的 user_id；
* MCP 不使用“超级用户”绕过业务权限；
* 知识内容、日志和用户提交内容按业务数据处理，不获得系统指令优先级；
* 写操作由后端权限和确认机制兜底。

---

# 44. 日志和审计

`assistant_tool_calls` 记录每次 Tool 调用（conversation_id、message_id、
opencode_session_id、arguments、result、status），可完整定位：
用户说了什么 → Agent 调了什么 → 平台执行了什么 → 产生了哪个 Task / Run。

---

# 45-48. 与任务执行链的关系与失败隔离

助手 `opencode serve` 与数字员工执行任务的 OpenCode Runtime 逻辑隔离；
任何 Assistant 故障不得影响 Task Scheduler、Celery、Executor、Employee 状态
和正在运行的 Run。

---

# 49. 开发顺序

第一阶段：基础设施（OpenCodeClient、Conversation、Message、SSE、Agent、MCP、Tool Gateway）
第二阶段：业务能力（Employee / Task 查询、Task 创建、Run、Retry/Cancel/Resume、Knowledge、Operations）
第三阶段：交互（Drawer、Streaming、Business Card、Confirmation、Context、History、Error Recovery）
第四阶段：治理（RBAC、Audit、Idempotency、Rate Limit、Timeout、Health Check、Session Recovery）

这是工程实施顺序，不是减少正式版本功能范围。

---

# 50. 开发验收标准

正式上线前至少满足以下验收项。

## 会话

* 新建会话正常；
* 历史会话正常；
* 页面刷新可恢复；
* SSE 断开可恢复；
* 停止生成正常。

## 创建任务

可以通过自然语言：

```text
创建任务
↓
识别参数
↓
查询员工
↓
形成 Preview
↓
用户确认
↓
真实 Task 创建
```

不得重复创建。

## 查询

以下全部使用真实平台数据：Task、Run、Employee、Knowledge、Operations。

## 操作

支持：retry、cancel、resume、reassign。权限和确认有效。重分配仅允许待领取或
已挂起任务；运行中任务必须先挂起，避免旧 Run 与新员工同时处理。

## 故障

OpenCode 停止时：助手显示不可用；平台其他功能完全正常。

## 安全

确认：

* Browser 无法直接访问 OpenCode；
* Agent 无数据库直连；
* bash/edit/write 默认不可用；
* 所有写操作均有权限验证；
* 操作具有完整审计记录。

---

# 51. 最终技术边界

```text
用户
↓
NEXUS Assistant UI
↓
Assistant Backend
↓
OpenCode Agent
↓
NEXUS Tool / MCP
↓
Domain Service
↓
Task / Run / Employee / Knowledge
```

OpenCode 负责：**理解和调用。**

NEXUS Backend 负责：**权限、规则、确认和执行。**

Task / Run / Employee 负责：**真实状态。**

Executor / Worker 负责：**真正干活。**

这是平台助手后续扩展任务创建、运营管理、异常处理、知识查询以及更多平台操作时统一遵守的架构边界。
