# Stage 3 实施批次

审查通过前不开始这些批次。每批结束时都能单独验证，不依赖后面的批次已经完成。对话链和执行链在批次 B 之后可以并行，汇合点是批次 H。

验证命令按仓库现状：

```bash
# task-platform
cd services/task-platform && pytest tests/<本批相关测试>
cd services/task-platform && ruff check app tests

# nexus-api / agent-service
cd services/nexus-api && pytest tests/<本批相关测试>

# web
cd web/nexus && npm run type-check && npm run build
```

OpenCode 相关 e2e 使用模型 `opencode/deepseek-v4.1-flash-free`，不经过网关。

## A. S3-10 缺口确认

依赖：无。`remote-worker-websocket` 的 1.1–4.6 已完成，本批不重写通道。

- [ ] A.1 核对业务路径不再调用 `ExecutionEnvironmentRuntime.run_remote` / `open_session`。允许的调用只剩 `remote_provisioning` 的安装维护，以及 `opencode_remote.py` 的 CLI fallback
  - 完成：调用点列表写进本批验证说明。若发现日常 Workspace、健康检查或 Session 仍走 SSH，只改那一处调用，不改投影
  - 验证：`pytest` 覆盖已迁移环境的连接、文件和 Git 不打开 SSH
- [ ] A.2 把 Worker 离线、OpenCode 可达、仓库已绑定、执行中、等待人工分开显示。离线不得显示成环境可用
  - 完成：展示读取 `worker_instances.status`、环境状态、Task 状态和 `runtime_connection`，不新增状态机
  - 验证：断开 WebSocket 后 Task 状态不变，Worker 仍被原 Task 占用，页面显示离线
- [ ] A.3 补上 `remote-worker-websocket` tasks 5.1–5.3 的回归：进程重启、网络超时、epoch 乱序不新建 Session、不重发 Prompt、不改 `apply_session_state()` 的含义
  - 验证：现有 Worker Gateway 与 lifecycle 测试通过

不做：短期凭据、请求头白名单、协议协商。

## B. 私聊绑定与身份

依赖：无。可与 A 并行。

- [ ] B.1 请求身份改为可信头里的 UID。`?uid=` 不参与授权。私聊、历史、SSE、附件按所有者校验
  - 完成：按 D2 的默认，AgentScope 仍使用服务用户 `nexus`。人类 UID 存在绑定上
  - 验证：两个 UID 访问同一员工得到两条 Session；伪造 query 读不到对方历史
- [ ] B.2 私聊 `(owner_uid, employee_id, kind=private)` 唯一。页面去掉新建会话。已有绑定只复用 `agentscope_session_id`
  - 完成：刷新不调用 `POST /sessions/`。找不到原 Session 时返回明确错误
  - 验证：同一 UID 换浏览器仍是原 Session。接口层仍可按管理需要删除绑定
- [ ] B.3 停止向 Nexus `messages` 写聊天正文。历史和流改读 AgentScope
  - 完成：不写回放、双写退出或归档脚本。`metadata.verified_uid` 随用户消息写入
  - 验证：刷新后的发言人不是匿名 `user`。重连不重复渲染同一事件 id

## C. 消息 UI

依赖：B。

- [ ] C.1 用 AgentScope 事件投影流式增量、Markdown、工具调用和工具结果、错误与中断
  - 完成：不新写一套 SSE 合并规则。离开页面不取消服务端运行
  - 验证：工具卡和历史一致；断流后先拉历史再续接，顺序不乱

## D. Team 与纯消息

依赖：B，以及待拍板 D1 维持推荐默认。

- [ ] D.1 在 Agent Service 增加只调用 `storage.upsert_message` 的写入。不调用 `ChatService.run`
  - 完成：消息带 `metadata.verified_uid`。写入失败对调用方可见
  - 验证：写入后 `GET /sessions/{id}/messages` 能读到，且该 Session 没有新的回复运行
- [ ] D.2 协作群复用 `channels` / `channel_members`，启用 `TeamCreate`、`AgentInvite`、`TeamSay`、`TeamDelete`。员工保存时设置 `invitable` 和 `invite_description`
  - 完成：继续卸掉 `AgentCreate`。解散团队后岗位员工仍在。`contact_employee` 不再承担群聊
  - 验证：邀请后 Agent 配置不变；定向和广播可送达；未 @ 的人类消息只落库；@ 只唤醒被点名的员工
- [ ] D.3 群页面按消息 id 和 `created_at` 合并各成员 Session。职责请求的回复回到发起协作上下文并唤醒对方
  - 完成：不把「转告 BUG」写成数字任务
  - 验证：成员看到的历史顺序一致；不同 UID 不能读非成员频道

## E. 压缩与长期记忆

依赖：B。可与 D 并行。按 D3 的默认只接 AgenticMemory。

- [ ] E.1 确认默认 `ContextConfig` 已挂到员工 Agent。补一个压缩后的检查：Session id 不变，消息表仍能读到压缩前的历史
  - 验证：不另写压缩器。摘要失败时行为跟原生 `compression_fallback_to_truncation` 一致
- [ ] E.2 用 `extra_agent_middlewares` 装配 `AgenticMemoryMiddleware`。目录按 `employee_id/uid` 隔离
  - 完成：当前启动路径能看到中间件已加载。组件不可用时聊天仍可进行，并返回可诊断错误
  - 验证：同一员工、同一 UID 的另一条已授权 Session 能读到记忆。另一个 UID 的目录不被检索

## F. IM 契约

依赖：B 和 D。公司 SDK 不在本批。

- [ ] F.1 实现入站事件、出站读取、ACK 和外部身份映射。幂等键为 `provider + event_id`
  - 完成：新增 `im_outbox` 与 `im_identity_map`。不复用 `task_wake_outbox`。每个员工有自己的外部机器人映射；未绑定则 IM 状态为不可用，Web 仍可用
  - 验证：模拟 Adapter 完成人到机器人、回复、再回到同一私聊 Session。重复事件不产生第二次推理。ACK 前不显示投递成功
- [ ] F.2 同一 UID、同一员工、同一作用域复用 B 的绑定。外部群使用独立协作绑定
  - 验证：Web 与模拟 IM 的历史一致。两个外部群不因为机器人相同而合并

## G. 员工模型路由

依赖：B。不改 Gateway 代码。

- [ ] G.1 员工增加 `model_route_id`。页面只列出网关已启用路由。创建或更新 Session 时注入指向网关 `/v1` 的 AgentScope credential
  - 完成：Key 不出现在页面和日志。没有路由时不改成直连厂商
  - 验证：错误路由能看到失败原因。空闲时更换路由不新建用户的私聊 Session

本地和 e2e 的 OpenCode 不使用这条路由，见批次 H。

## H. 仓库、PAT、Worker 复制与单仓

依赖：A。可与 B–G 并行，完成后才进入 I。

- [ ] H.1 新增 `code_repositories` 与 `git_credentials`。PAT 用现有 Fernet 加密。执行环境和 Task 增加 `repository_id`
  - 完成：URL 不内嵌 token。日志和 `opencode.jsonc` 不含 PAT。Worker 用进程内 askpass
  - 验证：错误或过期 token 克隆失败且错误文本不含 PAT。正确 token 能克隆真实 HTTPS 仓库
- [ ] H.2 复制 Worker 只复制仓库、分支、模型、技能和 MCP 引用、运行参数。新实例单独指定主机、路径和端口
  - 完成：不复制 token、PAT、SSH 密码、任务和工作区。一个 Worker 只绑定一个仓库
  - 验证：复制出来的实例没有源实例的连接凭据。同仓两个 Worker 使用各自 worktree。未指定仓库的任务不派单
- [ ] H.3 部署只写 `opencode.jsonc` 的网关 provider，并装上已绑定的 OpenCode 技能和 MCP。保留仓库自己的项目配置
  - 完成：不再写平台根 `opencode.json`，不再因 jsonc 已存在而失败。OpenCode 仍听 `127.0.0.1`，版本仍是 1.18.35
  - 验证：生产配置指向现有网关。本地 e2e 配置模型为 `opencode/deepseek-v4.1-flash-free` 且不读取网关 Key
- [ ] H.4 跨仓需求创建多条带 `repository_id` 的关联 Task，各自派给匹配仓库的空闲 Worker
  - 验证：单个 Worker 不会在执行中改绑仓库。占用中的 Worker 不会被另一条 Task 领走

## I. 等待原因与人工终态

依赖：A 与 H。投影代码只改 `apply_session_state()` 及其直接的等待字段。

- [ ] I.1 在同一次投影里写 `waiting_reason`。retry 进行中保持 `RUNNING`。retry 耗尽或执行停住写 `RETRY_EXHAUSTED` 并继续占用。问题、权限、执行结束分别写对应原因
  - 完成：通信失败不写 Task 状态。不自动 `SUCCEEDED` 或 `FAILED`
  - 验证：断线重连后原 OpenCode Session 仍在；人工确认结果后才 `SUCCEEDED` 并释放；取消和确认失败同样要等执行停止
- [ ] I.2 人工继续执行复用原 Worker、worktree 和 Session
  - 验证：继续不会新建 Session，也不会把未结束的 Task 派给另一个 Worker

## J. 去掉旧助手并保留复盘

依赖：I。必须先有可用的复盘调用，再关助手入口。

- [ ] J.1 移除 `nexus-assistant` 的产品入口、`/api/assistant` 的用户路径，以及助手专属 OpenCode Server 的启动
  - 完成：`task_summaries`、`task_reviews`、`app/assistant/review.py` 和经验技能保留。Task 进入人工确认后的终态时由后台触发复盘
  - 验证：复盘失败只更新复盘状态。已关闭的 Task 不被改回。重试复盘不覆盖已发布经验

## K. 图书馆映射

依赖：E 和 G。P1，可晚于 J。

- [ ] K.1 在 `knowledge_items` 上记录 AgentScope knowledge base / document id 和同步状态。员工绑定后，Session 的 `knowledge_config` 指向这些 id
  - 完成：启动 Agent Service 时传入 `knowledge_base_manager`。检索结果带来源。个人记忆目录不写入图书馆
  - 验证：一篇已审核文档可被绑定员工检索。未绑定员工检索不到。索引失败可见

## L. 命名与并行部署说明

依赖：J。不阻塞功能批次。按 D4 的默认。

- [ ] L.1 把本阶段改到的页面、错误文案和部署文档中的 Astra 产品名改为 Nexus
  - 完成：不改 `ASTRA_*` 变量名，不写配置迁移器，不轮换 Fernet 主密钥
  - 验证：抽查任务、Worker、聊天页面没有旧产品入口。`rg` 结果里保留的 Astra 字样有注释说明是环境变量或历史契约
- [ ] L.2 写明 Stage 3 进程、端口、数据库和 Worker 目录与 v0.9 分开
  - 完成：不写切换和回滚脚本
  - 验证：文档能让另一套进程同时留在机器上。验收步骤不要求停掉 v0.9

## 批次依赖

```text
A ─┬─> H ─> I ─> J ─> L
   │              └─> K（还要等 E、G）
B ─┬─> C
   ├─> D ─> F
   ├─> E ───────> K
   └─> G ───────> K
```

A/B 可以第一天同时开始。F 不能早于私聊绑定和纯消息写入。J 不能早于人工终态。任何批次都不重置已有 Gateway Key。
