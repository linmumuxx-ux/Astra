## Context

审计基线是 Astra 分支 `cursor/nexus-v1-0-1-phase2-f6f2` 的 HEAD `5215f6e3225f9e7c4f5df1352b1e653138c978e7`（`fix: install and restart the worker agent on deploy`）。实施前已 `git fetch`，本地与 `origin/cursor/nexus-v1-0-1-phase2-f6f2` 一致，无需再 rebase。Stage 3 分支 `cursor/nexus-v1-0-1-stage3` 从该提交拉出。

AgentScope 证据来自 tag `v2.0.10`，提交 `e6c014f0be49b2a6f6f62a9453082a0b975484e1`。下面的路径都相对于该 tag 的 `src/agentscope/` 或 `examples/web_ui/`。行号对应该提交。

当前产品已经分成两条链：

- 对话：`services/nexus-api` 的 SQLite 保存员工目录和会话绑定；`services/agent-service` 启动 AgentScope 2.0.10，并用 `contact_employee` 走 MessageBus。
- 执行：`services/task-platform` 保存 Task、执行环境、Worker Gateway、网关控制面、数字图书馆和任务复盘。Worker 主动连接 Gateway。WebSocket 走控制和事件，HTTP 走服务调用和大文件。

用户已经拍板、本设计直接遵守的约束：

- 内网大约 10 人。ACL 只做归属校验。PAT 加密保存，并且不出现在 URL、日志和配置明文里。不做短时凭据通道。
- 产品未发布。只为旧数据兼容而存在的迁移、回放、双写退出可以不做，但要在下面的矩阵里说明。
- Worker 主动连接；OpenCode 只听 `127.0.0.1`，版本固定 1.18.35；SSH 只用于安装和维护。
- Worker 重连不新建 OpenCode Session，不重发 Prompt。通信失败不改 Task 状态。投影只走 `RuntimeService.apply_session_state()`。
- Task 完成必须人工确认。`FAILED` 不自动设置。Worker 严格独占。不干预 OpenCode 原生重试。
- 不改 AgentScope 与 LLM Wiki 的业务设计，不改 Gateway 和模型映射代码。部署只写 `opencode.jsonc` 的网关 provider。
- 本地和 e2e 的 OpenCode 使用 `opencode/deepseek-v4.1-flash-free`。

## Goals / Non-Goals

**Goals:**

- 给出可核对的源码复用矩阵，以及现有表、API、事件到新职责的映射。
- 标出在内网小规模、不兼容旧版的前提下要简化的规格条款。
- 把 S3-01～S3-16 排成可独立验证的批次，并写明 S3-10 还剩什么。
- 把尚未拍板的冲突和推荐默认做法分开，供审查。

**Non-Goals:**

- 本步不改业务代码、不写 Alembic、不补 capability spec。
- 不实现公司 IM SDK，不替换数字图书馆，不重写 OpenCode Web UI。
- 不新建第二套聊天历史、Team 消息总线、长期记忆引擎或任务状态机。

## Decisions

本节先记录已经由源码和用户偏好确定的做法。需要另请拍板的冲突在文末「待拍板」列出。

### 1. 私聊绑定由 Nexus 记住 `session_id`，不能靠再次调用创建接口

`POST /sessions/` 的文档字符串写着按 `(user_id, agent_id, workspace_id)` upsert（`app/_router/_session.py` 303–305 行）。存储实现并不是这样：

- Redis：`session_id is None` 时总是新建（`app/storage/_redis_storage.py` 898–901 行）。
- SQL：同样在未传入 `session_id` 时插入新行（`app/storage/_sql/_storage.py` 1239–1254 行）。
- `sessions` 表只有 `(user_id, agent_id)` 索引，没有这个三元组的唯一约束（`app/storage/_sql/_tables.py` 143–174 行）。
- `IsolationPolicy.PER_AGENT` 复用的是 workspace 目录，不是 Session 记录（`app/workspace_manager/_base.py` 95–97 行）。`PER_SESSION` 每次分配新的 workspace id。
- HTTP 创建接口本身不传 `session_id`（`_session.py` 357–374 行），所以每次 `POST /sessions/` 都是一条新 Session。

Nexus 现在的部署已经使用 `PER_SESSION`。Stage 3 继续这样做，并且私聊只在绑定不存在时创建一次，之后只使用已保存的 `agentscope_session_id`。页面去掉「新建会话」。`conversations` 对私聊增加 `(owner_uid, employee_id, kind)` 唯一约束。产品未发布，不为已经存在的多条开发数据写回放或合并脚本；开发库若撞上唯一约束，清掉本地库即可。

### 2. 人类身份放在 Nexus 绑定和消息 metadata，AgentScope 继续使用一个服务用户

`X-User-ID` 是 AgentScope 的占位身份。头为空时源码返回 401（`app/deps.py` 52–56 行）；头缺失时走 FastAPI 的参数校验，通常是 422。默认资源策略 `DenyAllResourceAccessPolicy` 只拒绝另一个 AgentScope 用户的资源（`app/_app.py` 290–295 行），不区分共用 `nexus` 的人类 UID。`Msg` 含 `name`、`content`、`role`、`id`、`metadata`、`created_at`（`message/_base.py` 70–94 行），没有 `sender_uid`。

审查已接受 D2，附加条件如下。所有 Agent 和 Session 仍由服务用户 `nexus` 拥有。会话绑定是授权事实，消息 metadata 不是。私聊和群消息的 `Msg.name` 写成人类显示名（没有显示名时用 UID），`metadata.verified_uid` 同时写入，供审计。`role` 仍是 `user`。Nexus 在读历史、订阅 SSE、发消息和下载附件之前检查所有者或成员。浏览器不直连 Agent Service。`?uid=` 不参与授权。附件表增加 `owner_uid`，下载按该列校验。

### 3. 原生 HTTP 不能写入一条不触发推理的消息

公开写路径只有 `POST /chat/`。它把用户消息直接交给 `ChatRunRegistry.spawn`（`app/_router/_chat.py` 142–160 行）。`ChatService.run` 先 `upsert_message`，然后必定进入 `agent.reply_stream`（`app/_service/_chat.py` 1248–1269 行）。`upsert_message` 没有对应的 HTTP 路由，调用点只在聊天运行和 WebRTC 持久化里。`Agent.observe` 能把消息放进 `state.context` 且不调用模型（`agent/_agent.py` 381–384 行），但它不是 HTTP，也不写入消息表。

`TeamSay` 把 `HintBlock` 交给 `deliver_to_inbox`（`app/_tool/_team_say.py` 269 行起，`app/_bus_ops.py` 163–199 行）。inbox 没有消费者时会 `enqueue_run_trigger`，从而启动推理。它适合员工之间的职责消息，不适合「群里一句普通人类消息，谁也不 @」。

只写入消息表不会进入模型上下文。`ChatService` 用 `session_record.state` 组装 Agent，不从消息表重建上下文（`app/_service/_chat.py` 1176–1187 行）。因此：

- 人类群里没被 @ 的消息，只写入该群的记录 Session 一次，使用 `storage.upsert_message`，不调用 `ChatService.run`。写入前拿与聊天相同的 session checkpoint 锁；Session 正在运行则拒绝这次纯写入。写完后 Nexus 向其他人类成员推一条轻量 SSE「有新消息」，因为这条路径没有 AgentScope 事件。
- 每个成员在 `channel_members.last_delivered_message_id` 记下已经送进该员工上下文的位置。
- 被 @ 时，`POST /chat/` 的 `input` 是列表：该成员游标之后的积压消息，加上这一条 @。沿用原来的消息 id。`ChatService.run` 会按 id 原地 upsert，并把这些 `Msg` 送进 `reply_stream`。然后推进游标。
- 私聊不走这条积压。`POST /chat/` 直接带 `Msg.name` 和 `metadata.verified_uid`。

官方 `TeamPanel` 只切换成员 Session（`examples/web_ui/frontend/src/components/panel/TeamPanel.tsx` 23–31 行）。`TeamSay` 会在发送方留下工具调用，并在每个接收方的回复消息里各放一份 `HintBlock`（`app/middleware/_inbox_middleware.py` 99–133 行），两边的消息 id 不同。群时间线按块投影，不按整条消息 id 去重：

- 人类 `UserMsg` 相同 id 只显示一次。
- `TeamSay` 工具调用显示为「A→B」或「A→全体」，键用 HintBlock id。接收方回复里的 HintBlock 隐藏。
- 排序键是 `(created_at, session_id, id)`。
- 分页用每个 Session 自己的游标做 k 路合并。
- 人类群的记录 Session 和员工协作 Team 的 leader/member Session 都纳入这个投影。这是读时投影，不是第二份历史。

### 4. 协作使用原生 Team，临时员工工具继续卸掉

`get_toolkit` 按 Session 的团队角色挂工具：非成员或 Leader 得到 `TeamCreate`、`AgentCreate`、`TeamSay`、`TeamDelete`，有可邀请 Agent 时再加 `AgentInvite`；成员只有 `TeamSay`（`app/_service/_toolkit.py` 177–229 行，`app/_tool/__init__.py` 14–21 行）。

`AgentInvite` 在已有 `AgentRecord` 上新建 team-scoped Session，不复制岗位定义（`app/_tool/_agent_invite.py` 1–15 行）。`delete_team` 对 `invited` 成员只删借来的 Session，`AgentRecord` 保留；`created` 成员会整份删除（`app/_service/_session.py` 432–470 行）。所以岗位员工必须走 `AgentInvite`，不能走 `AgentCreate`。

当前 `services/agent-service/agent_service.py` 113–128 行把这些工具全部卸掉。审查后的分工是两种模式，而不是把人类群直接当成一个 Team：

- **人类群**沿用 Nexus `channels`。普通消息走上面的纯写入和投递游标，`@` 才 `POST /chat/`。这里只路由人类输入，不另做成员之间的消息引擎。`channels` 增加 `owner_uid`。`channel_members` 增加人类成员和 `last_delivered_message_id`。
- **员工协作**使用原生 `TeamCreate`、`AgentInvite`、`TeamSay`。发起员工的当前 Session 就是 leader。没有 HTTP 建团队接口，团队只能在那次运行里由工具创建。成员 `TeamSay` 回 leader 会原生唤醒 leader，这就是 E2E-07。从私聊 Session 当 leader 可以，该团队只对该 UID 可见。继续卸掉 `AgentCreate`。
- `contact_employee` 只做单向邮箱通知。它投到对方的 mailbox Session，回信到不了发起人的上下文，所以不能当作 E2E-07。

`AgentInvite` 在单一用户 `nexus` 下会取 `list_sessions(user_id, agent_id)` 的第一条，SQL/Redis 都是新到旧（`app/_tool/_agent_invite.py` 351–360、404–414 行）。那通常是某个人的私聊 workspace，文件、技能、MCP 和 workspace 记忆会跨 UID 泄露。`agent_service.py` 在组装 toolkit 时把 `AgentInvite` 换成一个薄子类，只改 workspace 和模型来源：用该员工自己的 `mailbox_session_id` 上的 workspace，没有 mailbox 时新建一个 workspace。绝不选用私聊或其他团队的 Session。AgentScope 包本身不改。

### 5. 压缩用原生 `ContextConfig`，长期记忆只装配一种

`ContextConfig` 默认 `trigger_ratio=0.8`、`reserve_ratio=0.1`、`compression_fallback_to_truncation=True`（`agent/_config.py` 57–62、156–157 行）。组装 Agent 时传入 `chat_config.context_config`（`app/_service/_chat.py` 1185 行）。`compress_context` 替换的是 `state.summary` 和 `state.context`（`agent/_agent.py` 749–751 行）。消息表由 `list_messages` 另读，压缩不删已持久化的历史，也不改 Session id。

默认中间件只有 `InboxMiddleware`、`StateChangeMiddleware`、`ToolOffloadMiddleware`，外加可选的团队循环和调用方工厂（`_chat.py` 984–1015 行）。`ReMeMiddleware`、`AgenticMemoryMiddleware`、`Mem0Middleware` 都要经 `extra_agent_middlewares` 才会挂上。当前 `agent_service.py` 没有传入这个工厂，所以长期记忆代码在包里，运行时没有装配。

ReMe 的搜索覆盖整个 workspace（`middleware/_longterm_memory/_reme/_middleware.py` 28–31 行）。不接 ReMe，也不接 Mem0。

`extra_agent_middlewares` 每次运行调用，参数是 `(user_id, agent_id, session_id, workspace)`，看不到消息 metadata。AgenticMemory 的官方接法是 `workdir=workspace.workdir`、`backend=workspace.get_backend()`（`examples/agent_service/main.py` 57–72 行）。私聊绑定在 `PER_SESSION` 下已经是「一个 UID 加一个员工一个 workspace」，这个 workspace 就是记忆范围。邀请子类修好之后，团队 Session 各自有 workspace，不会读到私聊记忆。重新绑定私聊时必须把原来的 `workspace_id` 传进 `POST /sessions/`，记忆才还在。不另做 `employee_id/uid` 目录。

知识库同理：`RAGMiddleware` 只在 Session 的 `knowledge_config.knowledge_base_ids` 非空且进程持有 `knowledge_base_manager` 时注入（`_chat.py` 1044–1085 行）。当前启动没有传入 manager，`/knowledge_bases` 不可用。S3-07 是 P1，映射放在现有 `knowledge_items` 上，不新做图书馆。

### 6. Task 投影保持原入口，只补结构化等待原因

`RuntimeService.apply_session_state()`（`services/task-platform/app/runtime/lifecycle.py` 356–361 行）是 Session 事实进入 Task 的唯一入口。现有行为已经符合硬性决定：

- Session `RUNNING` 投影为 Task `RUNNING`。
- Session 正常结束投影为 `WAITING`，原因是「执行结束，待确认」（91 行），不自动 `SUCCEEDED`。
- 问题或权限投影为 `WAITING`。
- Session `FAILED` / `INTERRUPTED` 也投影为 `WAITING`，文案来自 `_RECOVERY_REASON`（207–215 行），不自动把 Task 设为 `FAILED`。
- `UNKNOWN` 保持原业务状态。

`waiting_reason` 只在 `_project_session_state` 同一次写入里设置，对照现有 `SessionTerminalReason`：

| Session 事实 | Task | `waiting_reason` |
|---|---|---|
| `WAITING` 且是问题 | `WAITING` | `HITL_QUESTION` |
| `WAITING` 且是权限 | `WAITING` | `HITL_PERMISSION` |
| `SUCCEEDED` | `WAITING` | `EXECUTION_RESULT_REVIEW` |
| `ASSISTANT_ERROR` / `NO_REPLY` / `INCOMPLETE`，且是 OpenCode 自己停住 | `WAITING` | `RETRY_EXHAUSTED` |
| `ABORTED` | `WAITING` | `MANUAL_INTERVENTION` |
| `TIMEOUT` | 保持现有投影为 `WAITING` | 不从耗时推断 retry 耗尽。投影不调用 OpenCode abort，也不代它重试 |
| `UNCONFIRMED`（`session_state.py` 148–157 行，服务空闲且锚点不在记录里） | **不改变 Task 状态** | `TRANSPORT_RECOVERY` |

通信失败、心跳丢失和 `UNKNOWN` 不进入这张表，也不写 `TRANSPORT_RECOVERY`。人工确认、取消和关闭失败仍走现有 Task 接口，执行停止且没有待处理 HITL 之后才释放 Worker。分配时记下 base commit，以及当时的能力与模型 revision 快照。

### 7. Worker 通道沿用已落地的实现

`openspec/changes/remote-worker-websocket` 的 1.1–4.6 已完成。`worker_instances` 与执行环境一对一，状态是 `online` / `offline`，凭据是登记 token 的摘要。重连不新建 OpenCode Session，不重发 Prompt。SSH 的业务隧道已从日常路径撤下；`remote_provisioning.py` 仍在安装时调用 `open_session`，这符合「SSH 只用于安装和维护」。`opencode_remote.py` 的 CLI fallback 按既有决定保留。

S3-10 剩下的缺口见 tasks.md 批次 A。规格里的短期 Worker 凭据和请求头白名单按用户偏好不做。

### 8. 仓库、PAT 和部署配置

现在没有 `code_repositories`。执行环境与 `digital_employees` 一对一，Task 只有 `workspace` 路径。部署把整份配置写到全局 `opencode.json`，若已有 `opencode.jsonc` 则直接失败（`remote_provisioning.py` 341–344 行）。

Stage 3 增加仓库表和 `repository_id`，挂到现有执行环境和 Task 上，不另建 Worker 平台。PAT 复用 `app/gateway/security.py` 的 Fernet，密文入库。git 在 Worker 进程内用内存 askpass 取一次明文，不写入 remote URL、命令日志、`git config` 或 `opencode.jsonc`。不做短时凭据服务，也不做独立的 Git 写进程。

部署写的是 Worker 用户全局配置目录里的 `opencode.jsonc`（`config_home/opencode/opencode.jsonc`），不是仓库里的项目配置。这一份里包含网关 provider，以及该 Worker 绑定的 MCP。MCP 也可以经 `OPENCODE_CONFIG_CONTENT` 注入，二选一，不写两份。技能装到 Worker 专用目录，不改仓库自带的 `.opencode/`。不再生成平台根目录 `opencode.json`，也不再因为 jsonc 已存在而失败。Gateway 路由和模型映射代码不动。本地与 e2e 把 OpenCode 模型设为 `opencode/deepseek-v4.1-flash-free`，不读网关。生产 Worker 仍指向已验证的网关。

## 源码复用矩阵

| 子域 | 已有实现与证据 | 复用调用点 | 最小适配 | 不新增 |
|---|---|---|---|---|
| Session / 消息 / UI | 创建、列表、SSE、中断在 `app/_router/_session.py`、`_chat.py`。消息只读 `GET /sessions/{id}/messages`（586 行起）。Vue 页面在 `web/nexus/src/views/ChatView.vue`。事件类型在 AgentScope `event/_event.py` | Nexus 继续代理 `POST /chat/` 和 `GET .../stream`、`GET .../messages`。页面用原生事件增量，重连先拿历史和游标再续流 | 私聊唯一绑定；`metadata.verified_uid`；去掉新建会话按钮；群消息来源 | Nexus `messages` 不再作为历史正文。不建第二套聊天库 |
| 纯消息 | 无公开「只落库」接口。`upsert_message` 位于 `app/storage/_base.py` 738 行，实际写入发生在推理运行内 | 适配层直接调用该存储方法 | `services/agent-service` 一个内部写入接口，不 `spawn` 推理 | 不把未 @ 的话写进 Nexus `messages` |
| Team / 职责请求 | `TeamCreate`、`AgentInvite`、`TeamSay`、`TeamDelete` 在 `app/_tool/`。投递走 `deliver_to_inbox`。官方 UI 只切换成员 Session。没有 HTTP 建团队路由 | 员工协作：当前 Session 当 leader，岗位员工用改过 workspace 来源的 `AgentInvite`，定向和广播用 `TeamSay` | 人类群仍是 `channels` 加投递游标。`contact_employee` 只做单向通知 | 不把人类群建成 Team。`AgentCreate` 继续卸掉。不把 `source=team` 的临时 Agent 登记成员工 |
| Memory / 压缩 | `ContextConfig` 与 `compress_context` 已在默认 Agent 上。三种长期记忆都在 `middleware/_longterm_memory/`，当前进程未装配 | 压缩零开发。长期记忆用官方 workspace 接法挂 `AgenticMemoryMiddleware` | 私聊重新绑定时传入原 `workspace_id`。不可用时主聊天继续，错误可见 | 不写自定义记忆目录。不接 ReMe 和 Mem0 |
| Knowledge | 路由 `app/_router/_knowledge_base.py`。运行时 `RAGMiddleware`（`middleware/_rag.py`）。图书馆已有 `knowledge_items` 及审核发布 | 图书馆仍是已审核原文。Agent 检索走原生 KB | `knowledge_items` 增加 AgentScope KB / document 映射列。命中结果带来源 | 不替换 LLM Wiki，不把个人记忆写成图书馆资产 |
| Skill / MCP | AgentScope：`/skill`、`/workspace/skill`、`/mcp`。OpenCode 1.18.35 有自己的发现规则。员工行已有 `skills_json` / `tools_json` | 员工走 AgentScope API。Worker 把技能装进专用目录，MCP 写入该 Worker 的全局 `opencode.jsonc` 或 `OPENCODE_CONFIG_CONTENT` | 现有 JSON 和 `status_detail` 保存 `desired_revision`、`applied_revision`、`runtime_status`、`error`、`checked_at`。发现通过后才算 applied。Task 分配时记快照 | 不新建能力中心页面或表。不改仓库里的 `.opencode/` |
| 模型 | Gateway 表 `gateway_pools` / `gateway_nodes` / `gateway_routes` / `gateway_keys` 已加密。AgentScope 凭据接口 `POST /credential/`。现有 `bootstrap_chat_model.py` | 生产员工和 Worker 都指向现有网关 `/v1`。页面只列已启用路由 | 员工增加 `model_route_id`。部署只改 Worker 的 `opencode.jsonc` provider | 不改 Gateway 与模型映射代码。不在页面收集厂商 Key。本地 e2e 不走网关 |
| OpenCode 工作区 | 官方 UI 已在 `web/workspace-ui`。Task 详情 iframe。传输已走 Worker HTTP/SSE | 浏览器仍用现有 Workspace URL | 首屏按需加载、静态资源缓存。授权仍按 Task 归属 | 不重写编辑器、Diff、终端 |
| Task / Worker | Task 状态机 `app/state_machine.py`。投影 `lifecycle.py`。占用在执行员工槽。通道表 `worker_instances` / `worker_connections` / `worker_commands` | 终态、重连、独占、人工确认都沿用 | `waiting_reason`、`repository_id`、关联任务。健康展示分开「Worker 离线」和「环境可用」 | 不新增状态机，不在断线时释放 Worker，不自动 `SUCCEEDED` / `FAILED` |
| 复盘 | `review.py` 现在依赖 `assistant_enabled`、`AssistantOpenCodeClient`（334、366、419–431 行）和根目录 `opencode.json` 里的 `nexus-assistant` MCP | 保留这个 OpenCode 进程，改成只听 `127.0.0.1` 的内部复盘执行器。启动配置只带复盘 MCP 和只读工具，不再看 `assistant_enabled` | 先迁好执行器并跑通总结和候选，再删产品入口、`/api/assistant` 的用户路径和根目录 `opencode.json` | 不把复盘失败写回已关闭的 Task。不先删执行器 |
| IM | AgentScope 自带钉钉 / 飞书 / Discord channel（`app/channel/`）。Nexus 已有 `peer_deliveries` 和 `task_wake_outbox`，职责都不是外部 IM | 不启用 AgentScope 的厂商 channel，避免把公司 IM 写进 Agent 进程 | Nexus 提供事件、出站、ACK、身份映射。测试用模拟 Adapter | 不把 WeTalks / 钉钉 / 飞书 SDK 放进 Core。Outbox 不当永久聊天记录 |

## 现有表、API、事件到新职责

两个库保持 Phase 2 的拆分：对话绑定在 `services/nexus-api` 的 SQLite，任务和 Worker 在 `services/task-platform`。不合并数据库。

| 现有对象 | 新职责 | 改动 |
|---|---|---|
| `employees` | 长期岗位。一岗一员工 | 增加 `model_route_id`。`agentscope_agent_id` 继续指向同一个 `AgentRecord`。不按 UID 复制行 |
| `conversations` | 私聊绑定：`owner_uid + employee_id + kind=private → agentscope_session_id` | `owner_id` 改为可信 UID。私聊加唯一约束。不存消息正文 |
| `messages` | 不再承担历史 | 停止写入。读历史改走 AgentScope。表可以留着，不做回放、双写退出或归档作业 |
| `channels`、`channel_members` | 人类群的业务索引。员工协作 Team 另由 AgentScope 保存，群视图只引用其 Session | `channels.owner_uid`。成员可以是员工或人类 UID。员工成员有 `last_delivered_message_id`。不把 `agentscope_team_id` 当成人类群的必填字段 |
| `attachments` | 附件元数据 | 增加 `owner_uid`。下载前按所有者或会话成员校验 |
| `peer_deliveries` | 仅作 `contact_employee` 的次数账 | 协作群改走 TeamSay 后，它不再当群消息引擎 |
| `digital_employees` + `opencode_execution_environments` | Worker 槽，不是岗位员工 | 增加 `repository_id`。一个 Worker 一个仓库。复制时新行，不复制 token、PAT、端口、任务和工作区 |
| `worker_instances` 及连接、指令、HTTP 槽 | S3-10 的连接身份和投递 | 不换一套表。离线只改 `status=offline`，不改 Task |
| `tasks` | 业务闭环 | 增加 `repository_id`、`waiting_reason`、关联任务 id。`current_session_id` 仍是 OpenCode Session。`source_session_id` 仍是 AgentScope Session。`responsible_employee_id` 仍是岗位员工 |
| `runtime_sessions` | OpenCode Session 的绑定和用量索引 | 消息正文仍在 OpenCode。重连复用同一行 |
| `events`、`task_wake_outbox` | 任务审计和员工唤醒 | 不拿来当 IM Outbox，也不拿来当聊天历史 |
| `task_summaries`、`task_reviews`、`knowledge_*` | 复盘和图书馆 | 保留。知识项加映射列即可 |
| `gateway_*` | 模型入口 | 只读已启用路由。不改表和代理 |
| 新表 `code_repositories`、`git_credentials` | 仓库 URL、分支、加密 PAT | 现有表没有对应列，这是唯一成对新增的业务表 |
| 新表 `im_outbox`、`im_identity_map` | 短期投递和外部用户映射 | `task_wake_outbox` 的语义不同，不硬塞。Outbox 有保留期，不当历史 |

API 对应关系：

| 现有 API | Stage 3 用法 |
|---|---|
| `POST/GET /api/v1/employees/{id}/conversations`、`POST /api/v1/conversations/{id}/messages`、`GET .../stream` | 私聊入口。创建改为「没有绑定才创建」。消息和流仍代理 AgentScope |
| `POST /api/v1/channels` 与频道消息 | 协作群入口。普通消息走纯写入；`@` 才 `POST /chat/` |
| `/api/v1/internal/wake-target`、`/api/v1/peers/resolve` | 邮箱唤醒仍可留给非团队的职责通知 |
| `/api/tasks`、`/api/tasks/{id}` Workspace | 任务与 OpenCode UI。不新增工作区协议 |
| `/api/worker-gateway` | 保持。不把数字员工别名 `/api/workers` 改成通道 |
| `/api/employees/{id}/environment` | 挂到 Worker 槽，补仓库和复制 |
| `/api/gateway` | 只提供可选模型列表 |
| `/api/library` | 保持审核发布。增加同步到 AgentScope KB 的动作 |
| `/api/assistant` | 去掉产品入口。复盘改由任务闭环后的后台调用触发 |
| 新增 `/api/integrations/v1/im/*` | 按规格的事件、出站、ACK、身份映射。字段可按现有路由风格收敛 |

事件对应关系：

| 事件 | 事实来源 | Nexus 做什么 |
|---|---|---|
| AgentScope `AgentEvent`（含 `TEXT_BLOCK_DELTA`、`REPLY_END`） | `GET /sessions/{id}/stream` | 原样投影到页面。用事件 id 去重。不自行推断 Agent 状态 |
| `TeamSay` 的 inbox `HintBlock` | MessageBus | 只作为员工间投递。成功与否看工具结果，不看模型口头说「已通知」 |
| OpenCode `session.status`、问题、权限、SSE | Worker 事件帧，缺口时 `refresh` | 只进入 `apply_session_state()` |
| Worker 心跳丢失 | `worker_instances.status=offline` | 标注连接异常。Task 状态不动，Worker 不释放 |
| 任务 `TASK_WAITING` 与 `task_wake_outbox` | Task 投影之后 | 唤醒责任员工。不把等待文案当成终态 |

三类 ID 继续分开：`employee_id`、`agentscope_session_id`、`opencode_session_id`。`conversation_id` 和频道 id 只是业务索引。

## 规格简化矩阵

下列条款在「内网约 10 人、不兼容旧数据」下简化或不做。功能本身保留。

| 规格位置 | 本阶段做法 | 原因 |
|---|---|---|
| S3-01 第 7 条：消息迁移、只读回放、退出双写 | 停止把新消息写入 Nexus `messages`。不写迁移和回放 | 没有发布数据。历史改读 AgentScope |
| S3-04：签名断言、逐接口授权、租户模型 | 可信请求头加所有者/成员校验。单租户 | 用户要求最简 ACL。公司登录不在本仓 |
| S3-05：租约、死信平台 | 幂等键、按会话串行投递、ACK 丢失后按 `delivery_id` 重投。入站要等 AgentScope 接受输入再返回成功。含员工主动 `contact_human` | 10 人不做完整投递平台。主动联系和丢 ACK 仍是功能，不能省 |
| S3-06：独立能力中心页面和新表 | 不建页面、导航和表。revision、发现检查和快照仍要做，字段放进现有 JSON 和 `status_detail` | 规格允许复用存储。不能因此丢掉 desired/applied 和发现检查 |
| S3-08：配额、限流、上下文长度平台 | 使用网关已有能力。失败直接可见，不直连厂商。不改网关代码 | 网关已验证。本地 e2e 按拍板绕过网关 |
| S3-10：短期凭据、协议版本协商、请求头白名单、任意流控框架 | 沿用登记 token 摘要、epoch、8 路 HTTP 和帧大小限制 | 用户明确不要另做短时凭据通道 |
| S3-11：短时凭据通道、独立 Git 写进程、Push 的另一套鉴权 | Fernet 密文加进程内 askpass。Push 跟随任务人工确认 | 用户明确不要短时凭据通道 |
| S3-11 / S3-16：凭据轮换审计、回滚编排 | 支持更换 PAT 密文。不写轮换仪式和自动回滚器 | 未发布，换密文即可 |
| S3-14：历史归档 | 不归档旧助手数据。内部复盘执行器先迁好，再删产品入口和根目录 `opencode.json` | 没有发布数据。执行器本身不能先删 |
| S3-15：一次性迁移工具、Fernet 主密钥迁移、`ASTRA_*` 双读 | 不做迁移器，不轮换主密钥，不改环境变量名。例外清单见下文。E2E-19 只验收「没有旧产品入口和运行功能」 | D4 已接受。隔离靠端口、库、Redis 和路径，不靠改名 |
| S3-16：SQLite 消息表的核验、映射、回放、关写、归档 | 只关写 | 同 S3-01 |
| S3-16：切换和回滚脚本 | 不做切换脚本。同机并行要改的是 Celery 任务名、Redis 前缀和库号、临时目录、systemd 单元名、端口、数据库名。这是第一批代码，不是最后的说明 | 验收前不切换现网。名字相同会在共享 Redis 上互相消费任务 |
| 故障注入里的跨租户、密钥迁移、发布冲突 | 保留跨 UID、断线、脏仓库、复盘重试。跨租户和密钥迁移不单测 | 单租户，且没有旧密钥要迁 |

性能目标 P95 仍要测量，不在文档里宣称已经达到。测量失败不改 Task 状态机。

## S3-10 已覆盖与缺口

已覆盖，Stage 3 不重写：

- Worker 主动 WebSocket：控制、心跳、事件帧、`seq`、缺口时 `astra.event_gap` 加 `refresh`。
- HTTP 拉取请求体、上传响应，大文件走同一数据通道。
- 单 epoch、token 摘要、旧连接不能覆盖新状态。
- 重连对账原生 Session、分页消息、问题和权限。不新建 Session，不重发 Prompt。
- 断线不改变 Task 业务状态，投影仍只经过 `apply_session_state()`。
- 文件、Git diff、上传在 Worker 本地执行。OpenCode 听 `127.0.0.1`。
- 反向隧道和业务 `ssh` 执行已从日常路径删除。安装仍可用 SSH。

缺口：

1. `remote-worker-websocket/tasks.md` 的 5.1–5.3 仍未勾完：确认没有残留业务 SSH 调用、进程重启和超时下的 Task/Session 一致性、CLI fallback 与状态机未被改写。`environment.py` 仍保留 `open_session` / `run_remote`，需要在批次 A 确认业务路径没有调用方。
2. 健康展示还没有把 Worker 离线、OpenCode 可用、仓库就绪、能力已装上、执行中、等待人工分开。`WorkerInstance.status` 只有 online/offline，环境状态仍是 `AVAILABLE` 一类。离线不能显示成可用。
3. 规格中的短期凭据、`headers_allowlist` 和独立协议协商不做，见简化矩阵。
4. S3-09 的首屏计时还没有基线。通道本身不缺。

## Risks / Trade-offs

- 官方创建接口的文档写 upsert，实现是每次新建。绑定若丢失，再调用创建会得到另一条 Session。恢复必须凭已保存的 `session_id`，找不到就返回错误，不能按 UID 去猜别人的 Session。
- 官方创建接口的文档写 upsert，实现是每次新建。绑定若丢失，再调用创建会得到另一条 Session。恢复必须凭已保存的 `session_id`，找不到就返回错误。
- 纯写入被拒绝或某个成员的 `POST /chat/` 失败时，页面显示错误，游标不前移。
- `AgentInvite` 要求 `invitable=true` 且 `invite_description` 非空。员工保存时写入这两项。薄子类只替换 workspace 来源。
- 单服务用户意味着 AgentScope 本身不区分人类。授权边界在 Nexus 绑定。Agent Service 不能被浏览器直连。
- AgenticMemory 跟 workspace 走。私聊重建时若没传原 `workspace_id`，记忆不在。批次 E 用两个 UID，以及一次带原 workspace 的重建来验证。
- Worker 全局 `opencode.jsonc` 可以写 provider 和 MCP。仓库自带的项目配置和 `.opencode/` 不动。
- 本设计修订后的实现从 phase2 `5a7ce999` 开始。

## 已接受的决定

审查已接受 D1–D5，并加上下面的约束。实现按此执行。

### D1. 两种会话，一种 Team

人类群是 Nexus channel，加上纯写入和 `@` 时的积压投递。员工之间的协作才用 `TeamCreate` / `AgentInvite` / `TeamSay`，leader 是发起员工的当前 Session。`AgentCreate` 继续卸掉。`contact_employee` 只做单向通知。E2E-07 走 Team，不走 `contact_employee`。

### D2. 服务用户 `nexus`

AgentScope 固定 `X-User-ID: nexus`。人类隔离靠会话绑定、`Msg.name` 和附件 `owner_uid`。`metadata.verified_uid` 只作审计。不实现 `ResourceAccessPolicy`。邀请子类不得复用私聊 workspace。

### D3. 只用官方 workspace 上的 AgenticMemory

不接 ReMe，不接 Mem0，不做自定义记忆目录。压缩仍用默认 `ContextConfig`。

### D4. 不改 `ASTRA_*` 变量名

不双读，不迁移 Fernet 主密钥，不把 `ASTRA_GATEWAY_MASTER_KEY` 改名。E2E-19 收窄为：没有旧产品入口，也没有依赖旧助手页面的运行功能。全库可见文案不单开一轮。

例外清单（这些名字刻意留下，隔离不靠改它们）：

| 留下的名字 | 原因 |
|---|---|
| 环境变量前缀 `ASTRA_` | 改名会碰到 Gateway 主密钥和大量设置。D4 明确不改 |
| `ASTRA_GATEWAY_MASTER_KEY` | 硬性要求不改 Gateway |
| Celery 代码里的历史注释、已归档 OpenSpec | 不是运行入口 |
| 测试夹具里为了断言旧字符串而保留的样本 | 只存在于测试 |

同机隔离改的是值，不是这些变量名：Celery 任务名、Redis 前缀和库号、`/tmp` 目录、systemd 单元名、监听端口、数据库名。

### D5. 不建能力中心，但保留绑定跟踪

不新增页面、导航和表。员工 JSON 与环境 `status_detail` 保存 `desired_revision`、`applied_revision`、`runtime_status`、`error`、`checked_at`。发现检查通过才把 applied 写成 desired。调度要求两者相等。Session 创建和 Task 分配时记下当时的 revision。
