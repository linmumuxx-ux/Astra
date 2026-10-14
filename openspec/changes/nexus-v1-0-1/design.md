## Context

Nexus v1.0.1 是这个分支上的新产品。仓库里的 Astra 实现只保留为规范来源。数字员工的推理、会话、技能、知识和记忆由 AgentScope Agent Service 承担。Nexus 提供员工目录和两个聊天界面，并通过 HTTP 调用已经发布的 Agent Service。

版本钉在 **AgentScope 2.0.10**。依据是 2026-10-13 的 PyPI `agentscope` 最新正式版，以及 GitHub tag [`v2.0.10`](https://github.com/agentscope-ai/agentscope/releases/tag/v2.0.10)（2026-10-12）。Python 要求 `>=3.11`。文档站的 `2.0.10` 版本页当时返回 404；`2.0.7` / `2.0.8` 架构页仍把消息分页写成 `offset` + `limit`。tag `v2.0.10` 的源码里 `offset` 已废弃并被忽略，分页参数是 `before` 与 `limit`。接口以该 tag 源码为准，细节见 `nexus/docs/agentscope-2.0.10.md`。

## Goals / Non-Goals

**Goals:**

- 一位数字员工对应一个独立 Agent，一条对话对应一条 Session。
- 员工之间对等交流走自定义工具 `contact_employee`，使用 MessageBus 的 inbox 与 wakeup，由对方 Agent 自己推理。
- 前端只有员工管理、数字员工、团队交流三页，不出现模型或凭证配置。
- Agent Service 不可达时，界面保留用户刚发送的内容，并说明没有生成回复。

**Non-Goals:**

- 不迁移 Astra 的任务、运行时、3D 首页或 WeTalks。
- 不 fork AgentScope，也不在 Nexus 进程内嵌 Agent。
- 本阶段不在没有真实 Agent Service 的环境里宣称对话已经跑通。
- 不使用 Agent Team 来模拟同事互相说话。

## Decisions

### 1. AgentScope 是 Agent / Session / Skill / Knowledge / 记忆的唯一事实源

Nexus 的 SQLite 只保存员工目录、对话与 Session 的绑定，以及 Agent Service 尚未接受的用户消息。技能目录读取 `GET /skill`。知识库读取 `GET /knowledge_bases/`；当前部署没有传入 `knowledge_base_manager` 时，这个接口返回 503，Nexus 不接受新的手写知识库标识。工具没有用户级 HTTP 目录，员工档案只能关联 Linux 工作区自带的 Bash、Edit、Glob、Grep、Read、Write 和部署注册的 `contact_employee`。这份关联不改写 `get_toolkit`：AgentScope 仍会自行挂上任务工具和团队工具。对话事件只消费 `GET /sessions/{session_id}/stream` 的 `AgentEvent`。Nexus 不维护第二份记忆，也不根据本地消息条数推断 Agent 状态。

被放弃的做法：在 Nexus 里用提示词模板直接生成同事回复。那会变成脚本，而不是 Agent 推理。

### 2. 对等协作不使用 Agent Team

Agent Team（`TeamCreate`、`AgentCreate`、`TeamSay`、`TeamDelete`、`AgentInvite`）的结构是 Leader 创建 Worker 并派工。Nexus 的员工是预先存在、彼此平等的同事，所以部署时不注册这些团队工具，也不创建 `TeamRecord`。

同事联系使用 Agent Service 进程内的自定义工具 `contact_employee`，通过 `create_app(..., extra_agent_tools=...)` 放进每次组装的 basic 工具组。工具在 `v2.0.10` 中的调用链是：

1. 用当前 Session 向 Nexus 查询同一讨论里目标员工的 `agent_id` 与 `session_id`。私聊场景则查询该员工单独的邮箱 Session。
2. 构造 `HintBlock`（`type="hint"`，`hint` 为文本，`source` 为发送方员工名）。
3. 调用 `agentscope.app._bus_ops.deliver_to_inbox`。该函数在 inbox 锁内 `queue_push` 到 `MessageBusKeys.inbox(session_id)`；若没有正在消费 inbox 的 run，再 `enqueue_run_trigger(..., kind="wake")`。
4. `WakeupDispatcher` 取走 wakeup 并执行 `ChatService.run`。`InboxMiddleware` 在下一步推理前把 `HintBlock` 变成 `HintBlockEvent`。

工具返回值只说明投递结果。对方说什么由对方的模型推理决定，Nexus 不补下一句。

`FunctionTool` 对未显式授权的自定义工具默认 `PermissionBehavior.ASK`。部署时为 `contact_employee` 传入 `PermissionDecision(behavior=PermissionBehavior.ALLOW)`，避免每次联系同事都停成人机确认。

### 3. 多条对话依赖 PER_SESSION

`POST /sessions` 对同一个 `(user_id, agent_id, workspace_id)` 做 upsert。`LocalWorkspaceManager` 的默认隔离是 `IsolationPolicy.PER_AGENT`，同一员工的多次创建会回到同一条 Session。Nexus 的部署把隔离设为 `IsolationPolicy.PER_SESSION`，让每条私聊、每位员工在每个团队讨论中的上下文都得到独立 Session。Nexus 只保存返回的 `session_id`。这个隔离只是工作目录，不是沙箱。Agent Service 进程持有模型 API 密钥。邮箱和团队 Session 设为 `dont_ask`，私聊保持默认权限。

### 4. 聊天触发与事件分开

用户消息调用 `POST /chat`，请求体为 `agent_id`、`session_id` 和 `input`（一条 `role="user"` 的 `Msg`）。成功响应是 `{"status":"started","session_id":...}`，不含回复正文。同一进程里该 Session 已有运行中的 turn 时，源码返回 409。

正文来自 `GET /sessions/{session_id}/stream?agent_id=...`，媒体类型 `text/event-stream`。帧格式是 `data: {AgentEvent JSON}\n\n`，空闲时每 30 秒一个 `:\\n\\n` 心跳。可展示的增量是 `TEXT_BLOCK_DELTA` 的 `delta`。一轮结束的信号是 `REPLY_END`。Nexus 在本连接里见过对应的 `REPLY_START` 后，转发 `REPLY_END`，再写一条 `NEXUS_RUN_FINISHED` 并结束这次 SSE。上一轮留在重放日志里的单独 `REPLY_END` 不会提前关掉连接。身份头使用 Agent Service 当前的 `X-User-ID`。Nexus 在自己的 API 上代理这条流。`after` 只有在符合 Agent Service checkpoint 游标（`数字-数字`）时才转发；事件自己的 `id` 传进去会让 Redis 拒绝并中断连接。页面记下已经见过的事件 `id`，重放时不再把上一轮文本画出来。浏览器不直接持有 Agent Service 地址。

Session 要能产生文本增量，创建时必须带 `chat_model_config`。这项来自部署环境变量 `NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG`，内容是 Agent Service 里已登记的 credential id、provider type 和模型名。`nexus/deploy/bootstrap_chat_model.py` 调用官方 `POST /credential/` 生成它。Nexus 页面仍然没有模型或密钥字段。变量为空时，Session 不带模型，聊天不会被改成模拟回复。

### 5. 团队讨论只唤醒被 @ 的员工

频道消息先记在 Nexus。正文里的 `@员工名` 会对该成员在此频道的 Session 发一次 `POST /chat`。没有被点名的员工不会被 Nexus 调用。若发送者需要其他人，由该员工的模型自行调用 `contact_employee`。解析时如果同事还没有这条讨论的 Session，就只创建 Session，不代替对方发起运行。Agent Service 不可达时，只保留用户消息和失败说明。

同一句话对同一同事只投递一次。每位发送方在同一讨论里最多联系 2 次，整场讨论最多 6 次。达到上限时解析返回 409，工具把这段说明交回模型，不再写入 inbox。这个上限仍允许第一位员工联系第二位、第二位再联系第三位。讨论记录把每位成员 Session 里的助手文本标成该员工，不写入本地助手行。附件与私聊使用同一套内容块。

### 6. 产品代码与旧树隔离

新的页面、API 和部署说明都在 `nexus/`。根 `README.md` 指向这里。旧的 `backend/` 与 `frontend/` 不改业务行为。

## Risks / Trade-offs

- [小模型不稳定] → 2026-10-13 的 6.1 用本机 Redis、官方 `agentscope==2.0.10` 和 Ollama `qwen2.5:3b` 跑通了创建、两条 Session、SSE 增量和 `contact_employee` 唤醒。3B 模型没有稳定按提示只回复指定数字，对方增量是它自己的文本。换更大的模型不改变这条投递路径。
- [自定义工具运行在 Agent Service 进程内，目录查询却在 Nexus] → 工具通过 Nexus 的解析接口拿到绑定，不复制一份员工表进 AgentScope。
- [`X-User-ID` 不是认证] → 骨架沿用 Agent Service 的占位头，并在部署说明中标明上线前要换成调用方自己的认证。Nexus 页面用浏览器本地生成的 owner id 区分私聊，这不是账号体系。
- [文档站与 2.0.10 源码的分页参数不一致] → 客户端使用源码中的 `before` / `limit`，不发送已被忽略的 `offset`。
- [官方 `get_toolkit` 会挂上 Team、Task、ToolStop 和 Schedule 工具] → Nexus 启动脚本在官方组装之后用 `Toolkit.remove_tool` 卸掉这些名字，并丢掉已经空掉的非 basic 工具组。不修改已安装的 AgentScope 包。`contact_employee` 和工作区文件工具保留。

## Migration Plan

没有旧业务数据要搬。回滚就是停掉 `nexus/web` 与 `nexus/api`，不改动 AgentScope 以外的旧服务。Agent Service 本身的安装与卸载见 `nexus/deploy/agentscope.md`。

## Open Questions

- 生产环境的登录主体何时替换 `X-User-ID` 与浏览器 owner id。
- 知识库文档上传和 Skill 安装放到员工保存流程的哪一步。员工保存只记录目录中选中的标识。当前启动脚本没有传入 `knowledge_base_manager`，也没有注册 SkillHub，所以知识库目录不可用，技能也不能从库安装进 workspace。
