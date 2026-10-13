# Astra 1.0 当前接口与 Tool 契约

API 入口为 `apps/api/main.py`；请求模型为 `apps/api/schemas.py`。`openapi.json` 和 `tools.json` 从真实路由/注册表导出，运行 `python deploy/v1/export_contracts.py` 可刷新。此文列出当前已接通契约；原设计要求但尚未实现的接口仍属于必需范围。

## 认证与并发

所有业务接口通过 `Authorization: Bearer` 认证；不接受请求自报 actor。写入必须提供 1–120 字符 `Idempotency-Key`，同主体/同键/不同请求返回 409。版本编辑必须带 `revision`。401 表示身份失效，403 为当前授权不足，409 为状态/版本/重复副作用冲突，422 为输入不符合契约。凭据只存 SHA256，明文由部署渠道或管理员当前页面安全交付；不会放入 URL。

具体 POST/PATCH 路径具有严格 Pydantic 请求 schema，禁止额外字段。只读资源列表/详情共用新资源注册表，不承接旧 API、字段 alias 或旧对象。列表当前最多返回 1000 项、消息最多 500 项、审计页最多 500 项，完整游标分页仍待补齐。

## 已实现路由

| 路由族 | 行为 |
| --- | --- |
| `GET /api/v1/health`、`me`、`teams/overview` | schema 健康、真实 Principal、团队权威快照 |
| `GET /api/v1/{resource}`、`{resource}/{id}` | teams/roles/employees/goals/channels/tasks/routines/workers/knowledge/operations/handoffs/worker-leases/source-events/historical-artifacts/workspace-grants 的授权列表与详情 |
| `POST /api/v1/teams|roles|employees|goals|channels|tasks|routines|workers|knowledge|operations|source-events` | 新领域创建；SourceEvent 外部入站禁止冒用内部保留来源 |
| `PATCH /api/v1/goals|roles|employees|routines|knowledge/{id}` | 版本化编辑；已发布知识不可原地覆盖，修改候选内容/来源清除旧验证状态 |
| `GET /api/v1/employees/{id}/dashboard|goals|work|inbox|turns|memory|routines` | 员工视图；私人状态/Inbox/Turn/Memory 仅本人及负责人可见 |
| `POST /api/v1/employees/{id}/memory`、`GET .../memory/history|diff` | 核心记忆/笔记、来源、原因、过期提醒；expected_head CAS；恢复须产生新版本 |
| `POST /api/v1/employees/{id}/dm|pause|resume|archive` | 独立长期 DM、生命周期；未完 Goal/Task/审批/交接阻止归档 |
| `GET /api/v1/channels/{id}/members|messages`、`POST .../messages` | 成员 ACL、持久消息、引用/@ 与因果限制；附件当前明确拒绝，不伪造上传成功 |
| `GET /api/v1/tasks/{id}/executions|evidence|workspace|handoff-events|reviews` | 真实执行索引和交接回执；Workspace 当前 connected=false |
| `POST /api/v1/tasks/{id}/pause|resume|cancel|rework|dispatch|handoff|review` | 业务动作、租约绑定、正式交接；dispatch 只绑定，后台工程运行器启动；review 逐条复验原生证据 |
| `POST /api/v1/handoffs/{id}/accept|reject|request-clarification|clarify|withdraw` | 当事人/负责人授权；只有签收原子转移主责；工程范围和 Grant 当前有效 |
| `POST /api/v1/operations/{id}/approve|reject|request-changes` | 具体审批，当前仅受控数据库动作；对外发布/生产副作用尚未接入 |
| `POST /api/v1/routines/{id}/run-now|pause|resume`、`teams/{id}/routines/sweep` | 人工/到期投递 Inbox，不直接造 Task；系统只获 routine.signal |
| `GET/POST /api/v1/actors`、`PATCH .../actors/{id}`、`POST .../actors/{id}/revoke|credentials` | 人员管理、版本化授权、停用、短期凭据签发；不能复用员工生命周期接口 |
| `POST /api/v1/credentials/{id}/revoke`、`system-identities/schedulers|personas|executors` | 凭据撤销、仅人类管理员签发指定团队 routine.signal 、persona.run 或 runtime.execute/task.reconcile 身份 |
| `GET/POST /api/v1/teams/{id}/members` | 团队成员查询、人类加入团队 |
| `POST/PATCH /api/v1/workspace-grants[/{id}]`、`POST .../{id}/revoke` | 有期限的特定工程授权、版本更新/续期与撤销 |
| `POST /api/v1/workers/{id}/probe|credential` | 事务外真实 OpenCode 健康/版本/接口契约验证；受控 file: 凭据引用；注册不等于健康 |
| `GET /api/v1/human-inbox|audit-events|events` | 待人决定、按权限审计、持久 seq SSE；SSE 每次扫描重新认证/过滤，after 重连 |
| `GET /api/v1/governance/metrics|policies|budgets|resource-metrics` | 已保存业务指标；不伪造未采集的成本或 Runtime 用量 |
| `GET /api/v1/knowledge/{id}/versions|skill-proposals` | 现有版本/候选索引；完整验证发布链未接通 |
| `GET /api/v1/historical-artifacts/{id}/content` | 授权后在受控根读 artifact://SHA256.json；读前后复验且文件哈希必须一致 |

| `GET /api/v1/executions/{id}/native-evidence` | 当前工程审核权限下读取原生 Session 树工具结果；完成后仍可查询，读前后复验授权 |

具体工程配置、准备/提交意图、恢复规则及独立验收输入见 `execution.md`。

Persona 有限动作现为 reply/no_action/remember/dispatch/follow_up/ask_human/handoff/review，严格机器契约见 `persona-decision.schema.json`。review 使用同一 TaskReviewInput，必须绑定本回合具体 submitted 事件；受权原生输入/退出码/输出仅即时注入，提交前重读哈希，所有业务动作与 Inbox/Turn 原子完成。无效已知决策记录拒绝并冷却，未知提交结果不重提。模型不得传入 reviewer/actor 身份。

## MCP

`agents/tools.py` 使用 Streamable HTTP 与同一数据库凭据验证，转发当前请求的认证到新 API；Tool 不维护第二套业务授权或默认用户。写入 `operation_key` 映射到 API 幂等键。HTTP 写结果未知时不会换 key 自动重发。

当前十三个 Tool：`astra_context_get`、`astra_goal_list`、`astra_task_get`、`astra_task_create`、`astra_task_handoff`、`astra_channel_send`、`astra_operation_prepare`、`astra_memory_read`、`astra_memory_write`、`astra_event_read`、`astra_inbox_list`、`astra_task_review`、`astra_task_evidence`。参数和输出 schema 见 `tools.json`，Tool 参数不提供 actor/user_id。真实 HTTP 集成已验证身份转发、幂等、伪造字段拒绝和无凭据 401。

`astra_inbox_decide`、Routine/Knowledge/Skill Tool 仍待接入。当前有限决策运行器不直接开放任何主机或 MCP 写工具：模型提交符合 PersonaDecision 的提案，由可信后台调用领域服务，并与 Inbox/Turn 原子提交；不能把注册 Tool 数量当成产品完成度。
