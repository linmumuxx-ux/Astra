# OpenCode Server POC（2026-08-31）

## 结论

**最终结论：PASS（已完成 Runtime 切换）**

OpenCode Server 1.18.25 在当前 macOS 主机和真实 `opencode/glm-5.1` 模型下，Session、SSE、主 Agent Tool、Subagent、Child Session 内部 Tool、原生 Question/Reply、同 Session 多轮、Abort 和两 Session 并发隔离均通过。

首次 POC 在 macOS 上对 Windows 正确标记为 `UNVERIFIED`，因此当时没有切换主链。随后使用者明确确认“Windows 下功能是一致的”并指示实施，该确认作为 Windows 门禁的外部验收依据；报告仍保留 macOS 未能本机仿造 Windows 实测的事实。Astra 现已将 OpenCode Server 作为本地与 Linux SSH 远程正式 Runtime；远程连接通过 loopback SSH Tunnel，不公开 Server 端口。

## 能力矩阵

| 能力 | `opencode run` | `opencode serve` | POC 结果 |
|---|---|---|---|
| Agent Message | 支持，stdout JSON | 支持，Message API + SSE | PASS |
| Tool Event | 支持，父会话 stdout JSON | 支持，Message API + SSE | PASS |
| Subagent 识别 | 可从 `task` Tool 的结构化 metadata 识别 | `GET /session/{id}/children` + `parentID` | PASS |
| Subagent 结果 | `task` Tool output 内可取 | Child Message API 可取 | PASS |
| Subagent 内部 Tool | 父进程 stdout 不输出 child Tool | Child Session Event/Message 可取 | PASS（Server）；CLI 能力限制 |
| 用户 Question | 非交互执行会自动拒绝，当前 Astra 依赖文本标记 | 原生 `/question` + `question.asked` | PASS（Server） |
| Question 后 Resume | CLI 非交互路径不可原生回答 | `/question/{id}/reply` 后原 Session 继续 | PASS（Server） |
| Session 多轮对话 | `--session` 可继续 | 同一 Session 重复 Message API | PASS |
| Abort | 终止 CLI 进程 | `POST /session/{id}/abort` | PASS |
| 并发隔离 | 进程级隔离 | Session ID + Event 分区 | PASS |
| Windows 兼容 | Astra 现有 argv/进程组逻辑有静态覆盖 | Windows 启停器统一管理 Server 进程树 | **ACCEPTED（使用者确认）** |

## 真实环境与证据

- OpenCode：`1.18.25`
- Server 健康检查：`GET /global/health` 返回 `healthy=true`、`version=1.18.25`
- Provider/Model：`opencode/glm-5.1`
- Host：macOS arm64，当前日期 2026-08-31（Asia/Shanghai）
- Server API：由运行实例的 `GET /doc` OpenAPI 3.1 文档确认，没有依据猜测端点。
- POC 工作目录：系统临时目录，不修改 Astra 工作空间业务文件。
- Mock：未使用。
- 自动化 POC 已分别使用“连接已启动 Server”和“脚本自行启停 Server”两种模式复跑；13 项本机能力均为 `PASS`。POC 脚本在非 Windows 主机仍会诚实输出 Windows `UNVERIFIED`。
- 切换后 Astra 定向门禁通过：Ruff、63 项后端测试、真实 Coordinator 烟测；全量前端与系统 E2E 结果见本报告后文的最终门禁。

### Case 1：普通 Agent + Tool

- Session：`ses_fac789e16ffeT8XisuqvsAXnAs`
- 主 Agent 真实调用 Bash `pwd`，Message 中 Tool state 为 `completed`。
- SSE 收到 `message.part.updated` 的 Bash `pending → running → completed`。
- 最终回答：`SERVER_POC_OK`。

### Case 2 / 4：一个 Subagent + Subagent 内 Tool

- Parent：`ses_fac782a9bffepWi6WOz31OSBQY`
- Child：`ses_fac782084ffeJJu2EYjL8Rv4v0`，`parentID` 正确，Agent 为 `general`。
- Parent 的 Task Tool 状态为 `completed`。
- Child Message 与 SSE 均包含真实 Bash Tool，状态为 `completed`。
- Child 最终回答：`CHILD_TOOL_OK`；Parent 最终回答：`MAIN_CHILD_OK`。

### Case 3：多个 Subagent

- Parent：`ses_fac77c7e8ffeVvR0kcZ6IkU31B`
- Child 1：`ses_fac77bbdcffeLC94qed7TtLBOs`（general），输出 `CHILD_ALPHA`。
- Child 2：`ses_fac77b9baffeQ9ElTF69bukuiZ`（explore），输出 `CHILD_BETA`。
- Parent 最终回答同时包含 `MULTI_CHILD_OK`、`CHILD_ALPHA`、`CHILD_BETA`。

### Case 5：同 Session 连续两轮

- 复用 Case 1 Session，没有创建新任务。
- Message 数量从 3 增至 5。
- 第二轮正确记住第一轮标记，回答 `TURN2_MEMORY:SERVER_POC_OK`。

### Case 6：原生 Question / Reply / Resume

- Session：`ses_fac77453effeqx5CC7Y6Cpv4pt`
- 原生请求：`que_05388c5e1001CUhNG52dV20sRI`。
- SSE 顺序包含 `question.asked`、`question.replied`、`session.idle`。
- `POST /question/{requestID}/reply` 返回 `true`。
- 回答 `BLUE` 后，同一 Session 最终输出 `QUESTION_RESUMED:BLUE`。

### Case 7：Abort

- Session：`ses_fac76b0e3ffe5uI6FUaImh67bw`。
- Bash 已进入 `running` 后调用 Abort，API 在约 0.012 秒返回 `true`。
- Session 回到 `idle`，Assistant Message 记录 `MessageAbortedError`。
- Bash part 会以 `completed` 收敛，但 output 明确带 `User aborted the command`，因此适配时必须同时读取 Message error/Tool output，不能仅凭 Tool status 判定业务成功。

### Case 8：两个任务并发执行

- ALPHA：`ses_fac762c06ffeJE1dfil7j4890R`，最终只含 `ALPHA_FINAL`。
- BETA：`ses_fac762bfeffeSM1nlqv4RtLR5I`，最终只含 `BETA_FINAL`。
- 两个 Prompt 同时发送；Message 内容无对方标记，SSE 可按 Session ID 完整分区。

### Case 9：Astra Coordinator 真实端到端

- 当时脚本 `tools/e2e/real_opencode_smoke.py --model opencode/glm-5.1` 已删除，下面只保留当次结果。
- Task：`T-20260830-320FC7`，Run：`RUN-3C58DD4833`。
- OpenCode Session：`ses_fab042febffe27v2QcDF09LqjW`。
- `executor_type=opencode_server`，Task/Run 均完成，exit code 0。
- 真实 Agent 使用 Tool 创建 `astra-opencode-smoke.txt`，内容精确为 `ASTRA_V04_OPENCODE_OK`。
- Event 用量和 Tool 已写入 Run；总 Token 口径为 136499，Tool call 为 2。

## `opencode run` 基线复核

另用真实 `opencode run --format json --model opencode/glm-5.1 --auto` 运行了 Parent → general Subagent → Bash：

- Parent stdout 能取得 Task Tool、Child Session ID 和 Child 最终结果；
- stdout 只包含 Parent Session 事件；
- Child 内部 Bash Tool 没有出现在 Parent stdout；
- 同一个 Child 通过 Server 的 Child Message/Event API 可以取得内部 Bash Tool。

这证明 Server 模式能消除当前“只解析 Parent CLI stdout”的可观测性缺口。

## OpenCode Server 实际能力边界

1. `GET /event?directory=...` 会输出目录作用域内所有 Session 事件，Astra 必须按绑定的 Session ID 和已发现的 Child Session ID 分流，不能把整条 SSE 连接直接绑定一个 Run。
2. Parent Task Tool、`GET /session/{parent}/children`、Child 的 `parentID` 和 Tool metadata 可以交叉核对父子关系。
3. 原生 Question 是稳定的结构化请求；Reply 后 OpenCode 自行继续原 Session，不需要 Astra 伪造 Resume。
4. Abort 的 Session/Message 语义正确，但被中止的 Bash part 仍可能显示 `completed`；`MessageAbortedError` 和 output 的 abort metadata 是必须保留的事实。
5. `opencode serve` 未设置 `OPENCODE_SERVER_PASSWORD` 时会明确警告无认证。正式部署只能绑定 loopback，或配置认证并限制访问。
6. `/doc` 同时包含当前稳定端点和 `/api/*` 新端点。Astra 重构时应锁定 1.18.25 已验证的稳定 `/session`、`/event`、`/question` 接口，并增加版本门禁，不能混用两套 API。
7. 当前 macOS 仓库现场无法生成 Windows 实机日志；Windows 一致性由使用者明确确认，启停器、进程组和预检代码保留跨平台实现与复验脚本。

## 修改前后架构

修改前：

```text
Vue Task Workbench
        → Astra Backend
        → Celery / Coordinator
        → OpenCodeCLIExecutor
        → opencode run --format json
```

修改后（已实施）：

```text
Vue Task Workbench
        → Astra Backend
        → Celery / Coordinator
        → OpenCode Server Manager
        → Session / Message / Event / Child / Question / Abort API
```

## API / Session / Event 映射

| Astra Runtime 事实 | OpenCode Server 来源 |
|---|---|
| Run 绑定 Session | `POST /session` 返回的 `id` |
| 用户消息 / Agent 最终消息 | `POST` / `GET /session/{id}/message` |
| 实时文本 / Tool | `GET /event` 的 `message.part.updated` / `message.part.delta` |
| 运行状态 | `session.status`、`session.idle`、`GET /session/status` |
| Subagent 发现 | `GET /session/{id}/children`、Child `parentID`、Task Tool metadata |
| Subagent 输出 / Tool | Child 的 Message API 与 Child Session Event |
| 用户询问 | `GET /question`、`question.asked` |
| 用户回答并继续 | `POST /question/{requestID}/reply` |
| 取消 | `POST /session/{id}/abort` + `MessageAbortedError` |

## 修改文件

- `tools/e2e/opencode_server_poc.py`：可在 macOS/Linux/Windows 上复跑的真实 Server POC；默认启动独立 `opencode serve`，也可用 `--base-url` 连接已启动实例。
- `services/task-platform/app/executors/opencode_server.py`：真实 HTTP/SSE Executor，处理 Session、Event、Child、Question/Permission Reply、Abort 和用量。
- `services/task-platform/app/runtime/opencode_server.py`：共享 Server 命令、认证和健康检查。
- `services/task-platform/app/executors/opencode_prompt.py`：Server 与 CLI fallback 共用任务提示，仅 Server 启用原生 Question。
- `services/task-platform/app/runtime/coordinator.py`、`services/task-platform/app/runtime/semantic_events.py`、`services/task-platform/app/api/routes.py`：Session 绑定、结构化事件、继续输入与 Abort。
- `scripts/process_manager.py`、`scripts/runtime.sh`、`deploy/systemd/astra-opencode.service`：Windows/macOS/Linux 生命周期。
- 配置、部署示例、前端执行器标签、测试与文档同步更新。

## Windows 复验

在正式 Windows 部署主机的 Astra 仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe .\scripts\opencode_server_poc.py --model opencode/glm-5.1
```

当前实施依据包含使用者对 Windows 一致性的明确确认。上述命令仍是正式部署主机的建议回归步骤；脚本不会在 macOS/Linux 上伪造 Windows `PASS`。

## 最终质量门禁

- Ruff：PASS。
- Backend：67 passed。
- Vue TypeScript：PASS。
- Vite production build：PASS。
- Chromium 系统 E2E：10 passed。
- 真实 OpenCode Server 能力 POC：Windows 以外的 13 项全部 PASS；Windows 由使用者确认一致性。
- 真实 Astra Coordinator + OpenCode Server + GLM5.1：PASS。

## Linux 远程适配后回归

加入 SSH Tunnel 远程 Server 客户端后，再次运行完整真实 POC：13 项本机 Server 能力全部 PASS；脚本的 `overall=FAIL` 仍只来自 macOS 无法生成 Windows 实机证据，`windows_compatibility=UNVERIFIED`。随后真实 Coordinator 烟测再次 PASS：Task `T-20260831-4539C3`、Run `RUN-6FF0D75D13`、Session `ses_faacc6996ffeT1th28ZP4vFJch`，`executor_type=opencode_server`，真实 Tool 产物内容为 `ASTRA_V04_OPENCODE_OK`。Linux SSH 传输层的结论与现场限制见 `REMOTE-OPENCODE-SERVER-2026-08-31.md`。
