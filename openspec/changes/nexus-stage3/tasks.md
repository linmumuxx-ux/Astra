# Stage 3 实施批次

审查结论已写入 `design.md`。每批结束时单独验证。对话链和执行链在批次 0 之后可以并行。`waiting_reason` 不依赖仓库表，批次 I 跟在 A 后面即可。能力绑定 S 要早于 H 的安装和调度。K 依赖 E 和 G，不依赖 J。

验证：

```bash
cd services/task-platform && ASTRA_REDIS_URL=redis://127.0.0.1:6379/15 ASTRA_TEST_REDIS_URL=redis://127.0.0.1:6379/15 pytest tests && ruff check app tests
cd services/nexus-api && pytest tests && ruff check nexus_api tests
cd web/nexus && npm run type-check && npm run build
```

OpenCode 相关 e2e 使用 `opencode/deepseek-v4.1-flash-free`，不经过网关。Agent Service 集成测试使用仓库里已钉住的 AgentScope 2.0.10。

## 0. 与 v0.9 并行的进程隔离

依赖：无。早于任何同机验证。不改 `ASTRA_*` 变量名，只改会撞车的默认值。

- [x] 0.1 Celery 应用和任务名改为 `nexus.*`（dispatch、task-review、task-wake、scout、heartbeat）。v0.9 仍消费 `astra.*` 时两边互不领取
- [x] 0.2 Redis 键前缀改为 `nexus:`。默认库号离开 0。测试使用 db 15
- [x] 0.3 本地 OpenCode 锁目录改为 `/tmp/nexus-employee-serve`。systemd 单元默认名改为 `nexus-opencode-{id}.service`
- [x] 0.4 本分支默认端口和数据库名与 v0.9 错开：Task API、Nexus API、Agent Service、MCP、Task MCP、Web、网关、助手 OpenCode，以及数据库名 `nexus`
- [x] 0.5 冒烟：默认值里不再出现会和 v0.9 共用的 Celery 任务名、Redis 前缀、临时目录和数据库名
  - 验证：`pytest` 覆盖上述默认值。不要求在这台机器上同时拉起 v0.9

## A. S3-10 缺口

依赖：0。不重写已落地的 Worker 通道。

- [x] A.1 业务路径不再调用 `run_remote` / `open_session`。允许的只剩安装维护和 `opencode_remote.py` 的 CLI fallback
  - 验证：测试列出调用点，Workspace、健康检查和 Session 不在其中
- [x] A.2 Worker 离线、OpenCode 可达、仓库已绑定、执行中、等待人工分开显示。离线不得显示成环境可用
  - 完成：读 `worker_instances.status`、环境状态、Task 状态和 `runtime_connection`。不新增状态机
  - 验证：Worker 标成 offline 后 Task 状态不变，占用仍在，接口里的可用性不是 `AVAILABLE`
- [x] A.3 进程重启、网络超时、epoch 乱序不新建 Session、不重发 Prompt、不改 `apply_session_state()` 的含义
  - 验证：现有 Worker Gateway 与 lifecycle 测试，加上一条断线不改 Task 的回归

不做：短期凭据、请求头白名单、协议协商。

## P. 工作区性能

依赖：A。S3-09 / PERF-01。

- [ ] P.1 记录热态首开、再次打开、冷启动，以及 HTTP、SSE、iframe 的耗时。热态目标是首开 P95 ≤ 3 秒、再次打开 P95 ≤ 1.5 秒。冷启动单独统计
  - 验证：同一次打开不新建 Session、不换 Worker、不重启 OpenCode。结果写成可复现的数字，不在未测量时宣称达标

## B. 私聊绑定与身份

依赖：0。可与 A 并行。

- [x] B.1 身份来自可信头 `X-Verified-UID`（内网开发可沿用已有的 `X-Owner-Id`，两者是同一个值）。`?uid=` 不参与授权。私聊、历史、SSE、附件按所有者校验
  - 完成：AgentScope 仍使用服务用户 `nexus`。绑定是授权事实
  - 验证：两个 UID 访问同一员工得到两条 Session。伪造 query 读不到对方历史和附件
- [x] B.2 私聊 `(owner_uid, employee_id, kind=private)` 唯一。页面去掉新建会话和会话切换。已有绑定只复用 `agentscope_session_id`
  - 完成：刷新不再次 `POST /sessions/`。找不到原 Session 时返回明确错误
  - 验证：同一 UID 再次进入仍是原绑定
- [x] B.3 私聊停止写入 Nexus `messages`。历史改读 AgentScope。`POST /chat/` 的 `Msg.name` 是人类显示名或 UID，`metadata.verified_uid` 同时写入
  - 完成：附件增加 `owner_uid`。不写回放脚本
  - 验证：发言人不是匿名 `user`。另一个 UID 不能下载这条附件

## C. 消息 UI

依赖：B。

- [x] C.1 投影 AgentScope 事件：流式增量、Markdown、工具调用和工具结果、错误与中断
  - 完成：离开页面只断开浏览器连接，不取消服务端运行。重连先读历史和游标，再用事件 id 去重
  - 验证：工具卡和历史一致。断流后续接不重复、不乱序

## D. 人类群与员工协作

依赖：B。按 design 的两种模式。

- [x] D.1 群记录 Session 上的纯写入：checkpoint 锁，运行中拒绝，不调用 `ChatService.run`。写完向其他人类成员推 SSE
  - 验证：写入后消息列表可见，且没有新的回复运行
- [x] D.2 人类群沿用 `channels`。成员保存 `last_delivered_message_id`。被 @ 时把积压和这条 @ 以原 id 经 `POST /chat/` 送进该员工 Session，然后推进游标
  - 验证：先说一件事且不 @，再 @ 并追问，重启后该员工上下文里仍有那件事。第一次写入没有推理
- [x] D.3 员工协作启用 `TeamCreate`、`TeamSay`、`TeamDelete`，以及只改 workspace 来源的 `AgentInvite` 子类。workspace 来自该员工的 mailbox Session，或新建。继续卸掉 `AgentCreate`。`contact_employee` 只做单向通知
  - 验证：两个 UID 的私聊 workspace 与两个团队的 workspace 互不相同。邀请后员工定义还在。解散团队不删员工
- [x] D.4 群时间线按块合并：人类消息按 id 只显示一次；TeamSay 用 HintBlock id 显示为 A→B 或 A→全体，隐藏接收方副本；按 `(created_at, session, id)` 做带游标的 k 路合并
  - 验证：广播、定向和分页不重复、不丢
- [x] D.5 E2E-07：A 的当前 Session 当 leader，邀请 B，B 用 `TeamSay` 回到 A 并唤醒 A。不创建数字任务
  - 验证：一条 A→B→A 的跟踪。`contact_employee` 的回信不会出现在 A 的上下文里

## E. 压缩与长期记忆

依赖：B。团队 workspace 隔离依赖 D.3，E 的团队用例排在 D.3 之后。私聊用例只依赖 B。

- [x] E.1 确认默认 `ContextConfig` 已挂上。压缩后 Session id 不变，消息表仍能读到压缩前的历史
- [x] E.2 用官方 workspace 接法装配 `AgenticMemoryMiddleware`
  - 验证：两个 UID 的私聊记忆互不可见。用同一个 `workspace_id` 重建 Session 后记忆还在。组件不可用时主聊天仍可进行，并返回可诊断错误

## F. IM 契约

依赖：B 和 D。公司 SDK 不在本批。

- [x] F.1 入站事件、出站、ACK、身份映射。幂等键 `provider + event_id`。AgentScope 接受输入之后才向 Adapter 返回成功。每个员工自己的机器人映射；未绑定则 IM 不可用，Web 仍可用
- [x] F.2 同一 UID、同一员工复用 B 的绑定。外部群使用独立协作绑定，不因机器人相同而合并
- [x] F.3 `contact_human`：员工发起 → outbox → ACK → 人类回复进入同一 Session。同一会话串行投递。ACK 丢失时按 `delivery_id` 重投，不第二次推理
  - 验证：模拟 Adapter 走完主动联系和丢 ACK。重复入站事件不产生第二次回复

## G. 员工模型路由

依赖：B。不改 Gateway 代码。

- [ ] G.1 员工增加 `model_route_id`。页面只列已启用路由。Session 注入指向网关 `/v1` 的 credential。Key 不出现在页面和日志。没有路由时不改成直连厂商
  - 验证：空闲时更换路由不新建私聊 Session。错误路由的原因可见

本地和 e2e 的 OpenCode 不使用这条路由，见 H.3。

## S. 能力绑定跟踪

依赖：B 和 G。早于 H.3、H.4。不新建页面和表。

- [x] S.1 员工 JSON 和环境 `status_detail` 保存 `desired_revision`、`applied_revision`、`runtime_status`、`error`、`checked_at`。desired 是绑定集合的哈希
- [x] S.2 员工侧调用原生 `/skill`、`/workspace/skill`、`/mcp`，再检查该 Session 的 toolkit 是否列出它们。Worker 侧安装后按 OpenCode 1.18.35 的发现规则检查
- [x] S.3 `applied_revision == desired_revision` 才允许分配。Session 创建和 Task 分配时记下 revision 快照
  - 验证：未生效的绑定不会派到任务上。发现失败时 `runtime_status` 和 `error` 可见，已在跑的任务不被改掉

## H. 仓库、PAT、复制与单仓

依赖：A 和 S。

- [ ] H.1 `code_repositories` 与 `git_credentials`。PAT 用现有 Fernet。环境和 Task 增加 `repository_id`。git 用进程内 askpass。URL、日志和配置不含 PAT
  - 验证：错误 token 克隆失败且错误文本不含 PAT
- [ ] H.2 复制 Worker 只复制仓库、分支、模型、技能和 MCP 引用、运行参数。不复制 token、PAT、密码、端口、任务和工作区
  - 验证：同仓两个 Worker 各自 worktree。一个 Worker 不改绑仓库
- [ ] H.3 部署写入 Worker 全局 `config_home/opencode/opencode.jsonc` 的网关 provider 和该 Worker 的 MCP。技能装到 Worker 专用目录。不改仓库 `.opencode/` 和项目配置。不再写平台根 `opencode.json`
  - 验证：生产配置指向现有网关。本地 e2e 模型为 `opencode/deepseek-v4.1-flash-free`，不读网关 Key
- [ ] H.4 分配时记录 base commit 和 S 的配置快照。跨仓拆成多条带 `repository_id` 的关联 Task，并按依赖汇总。未指定仓库不派单。占用中的 Worker 不被另一条 Task 领走

## I. 等待原因与人工终态

依赖：A。不依赖 H。

- [ ] I.1 按 design 的映射表写 `waiting_reason`。`UNCONFIRMED` 只记 `TRANSPORT_RECOVERY`，不改变 Task 状态。`TIMEOUT` 不触发平台 abort 或重试。retry 进行中保持 `RUNNING`。OpenCode 自己停住才写 `RETRY_EXHAUSTED`
  - 验证：断线不改 Task。问题、权限、正常结束、retry 耗尽分别落到对应原因。没有待处理 HITL 且执行已停止，人工确认后才 `SUCCEEDED` 并释放。取消和确认失败同样要等执行停止
- [ ] I.2 人工继续复用原 Worker、worktree 和 Session
  - 验证：不新建 Session，也不把未结束的 Task 派给另一个 Worker

## J. 复盘执行器，然后去掉产品入口

依赖：I。先迁执行器，再删入口。

- [ ] J.1 把现有助手 OpenCode 收成内部复盘执行器：只听 `127.0.0.1`，启动配置只带复盘 MCP（含 `nexus_task_review_submit` 和只读工具）。不再依赖 `assistant_enabled` 和根目录 `opencode.json`
  - 验证：产品助手入口关闭时，仍能生成一条任务总结和一个候选经验。失败只更新复盘行
- [ ] J.2 删除 `/api/assistant` 的用户路径、任务创建/取消类助手工具和根目录 `opencode.json`
  - 验证：页面没有旧助手入口。重试复盘不覆盖已发布经验

## K. 图书馆映射

依赖：E 和 G。

- [ ] K.1 `knowledge_items` 记录 AgentScope knowledge base / document id 和同步状态。启动时传入 `knowledge_base_manager`
  - 验证：已审核文档可被绑定员工检索，未绑定员工检索不到。个人记忆不写入图书馆

## L. 可见旧名

依赖：J。不阻塞功能。变量名按 D4 例外清单留下。

- [ ] L.1 本阶段改到的页面和错误文案里，用户能看到的 Astra 产品入口改为 Nexus
  - 验证：E2E-19 只检查没有旧产品入口和依赖该入口的运行功能。`ASTRA_*` 仍在

## 依赖

```text
0 ─┬─> A ─┬─> P
   │      └─> I ─> J ─> L
   └─> B ─┬─> C
          ├─> D ─> F
          │    └─> E（团队用例）
          ├─> E（私聊用例）
          └─> G ─> S ─> H
                    E ─> K
                    G ─> K
```
