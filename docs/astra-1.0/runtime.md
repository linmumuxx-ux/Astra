# Astra 1.0 Runtime 契约与验证

## 责任边界

`domains/runtime/` 只负责 Worker 资源租约、OpenCode 连接、原生事实读取和独立工作区。Employee 是业务主责，Worker 是共享执行资源；Task 是业务闭环，OpenCode Session 是执行事实源。Adapter 不持久化原生消息/工具 transcript，不把 `session.idle`、事件数量、网络中断或文件时间当作 Task 成功证据。

`TaskExecution` 保存 `worker_id / native_session_id / workspace_ref / attempt_no / lease_id / lease_fence / grant_snapshot / evidence_refs / superseded_by`。`NativeSessionBinding.permission_digest` 是批准的原生权限规则摘要，启动接入时应保存到 `grant_snapshot` 并在恢复时取回；未绑定摘要不能发起 Prompt，原生权限漂移会阻断执行。短决策 `EmployeeTurn` 使用独立 `PERSONA` Runtime Session，工程执行使用 `TASK` Session，长期对话只保存在 Channel。

## OpenCode 接口

`OpenCodeConfig` 是独立 dataclass，不读取 0.xx `Settings`。调用者显式提供 `base_url / runtime_id / purpose / workspace_roots`，凭据从部署安全渠道注入，密码不会出现在配置 repr 或错误正文里。客户端不继承系统 HTTP proxy 环境，也不自动跟随重定向。公司代理应通过明确的受控地址部署，而不是隐式改变凭据去向。

`verify_contract()` 读取实际 `/global/health` 和 `/doc`，检查精确兼容版本、Session/Message/Event/Abort/人工干预接口，以及 Session 的 metadata/permission 能力。默认验证版本为当前真实探测过的 `1.18.35`。公司固定版本须明确配置并通过同一套契约和真实工程验证；更高版本或旧业务“兼容”都不会自动放行。

| 方法 | 契约 |
|---|---|
| `create_session(directory, owner_ref, title, permission_rules)` | 创建带用途、Runtime 标识、业务执行/决策索引的 Session；返回不可变 `NativeSessionBinding` |
| `prompt_async(binding, text, message_id)` | 使用后端保存的稳定原生消息 ID 发起一次执行；请求断开时结果未知，不自动重发 |
| `session(binding)` | 核验原生 ID、目录、用途与主责索引；Persona 额外核验权限边界未漂移 |
| `native_session(directory, native_session_id)` | 供具有历史证据授权的服务只读核验；不向历史 Session 伪造新员工身份 |
| `messages(binding, limit, before)` | 直接分页读取原生消息和 `x-next-cursor`；不写入 Astra transcript |
| `status(binding)` | 先核验 Session 存在，再读原生活动状态；`idle` 不产生业务完成结论 |
| `events(binding, include_children)` | 原生 SSE、多行 data、根/子 Session 过滤、有限内存去重；断线明确要求重新对账 |
| `pending_interventions / reply_question / reply_permission` | 请求须属于根/原生子 Session；权限只允许本次批准或拒绝，不提供永久授权 |
| `abort(binding)` | 返回原生 abort 回执；业务仍须核验已经发生的副作用 |

`OpenCodeUnavailable.outcome_uncertain` 对断线、超时或服务端错误的写请求为 `True`。调用服务必须查询同一 Session/稳定消息 ID、文件与外部副作用，不得因为请求失败创建第二次执行。

Persona 绑定独立决策目录，deny-all 后只开放明确命名的 `astra_*` 业务工具，不允许调用者覆盖权限模板，也不能通过原生 permission reply 扩权。Task Session 必须传入有效 Workspace/Task Grant 转换的非空权限快照。Adapter 的 metadata 是后端与原生会话的绑定核验，不能代替身份认证、业务 ACL、具体审批或组织规则。

## Worker 租约

`dispatch_task()` 在短数据库事务中验证请求人与业务主责员工的当前授权、团队/岗位最大边界、project Workspace Grant、Worker 最近真实健康检查、已验证版本、能力与工程范围。Worker slot 用 `FREE → ACTIVE` 的条件更新和 fence 递增取得。结果是 `Task.DISPATCHED + TaskExecution.BOUND`，没有原生启动事实时不写 `RUNNING`。

同一员工可同时持有多个 Task 租约，多员工可共享 Worker 并发槽位。私有 worktree 相互独立；`asset_scope.shared_assets` 明确声明的外部写资产按稳定键独占。资产锁到期也不会被直接抢走。

启动、续租与提交调用 `assert_current_execution()`/`validate_execution_authority()`，核对当前 fence、轮次、主责、Role/Team/WorkspaceGrant 版本、Worker 地址/版本/目录/能力。权限撤销后禁止新动作。`superseded_by` 阻断旧轮次写入新轮次。

`expire_worker_leases(session, principal)` 要求可信系统/人类身份与 `runtime.recover` 工程授权；过期租约、执行与 Task 进入 `RECONCILE_REQUIRED`，保留槽位和工作区，记录审计，不重复派工。

`release_reconciled_execution()` 仅供获得 `task.reconcile` 授权的人/系统在核验原生事实、文件和副作用后调用。`SUBMITTED` 必须含原生 Session 与证据索引，业务仅进入 `REVIEW`；不能凭 Worker 声称成功完成 Task。该函数保存核验引用，不自行证明外部引用内容；证据校验调用链必须在接入时真实执行。

## Git 工作区

`prepare_task_workspace()` 从明确工程 commit 为每个 `task_id/execution_id` 创建独立 detached worktree。恢复须显式 `reuse=True, base_ref=已保存commit`，禁止跟随已经变化的主工程 HEAD；验证物理目录、所有父路径无符号链接、仓库 common-dir、worktree 注册和目录根。已丢失工作区不自动重建，普通残留目录、其他仓库 worktree、路径穿越均明确拒绝。恢复保留未提交修改与任务自己的 OpenCode 配置。

运行前服务必须验证 Workspace Grant、租约、授权根目录与共享资产锁；API 主机不得用本地 `resolve()` 改写 Windows/Linux 远端 Runtime 路径。当前工作区执行器是本地 Git；远程 SSH/Tunnel 的新凭据边界与公司 Windows/Linux 实测尚需集成验证。

## 已执行验证

2026-10-13 在本机对 4096 与 4097 进行只读探测：均为 OpenCode `1.18.35`，`healthy=true`，新 Adapter 的实时 `/doc` 契约校验通过。

`tests/v1/test_runtime_client.py` 使用明确的 `httpx.MockTransport`，验证版本拒绝、Persona/Task 隔离、权限漂移、未知写结果、历史只读、SSE 过滤/去重/断线及人工干预范围。`test_runtime_workspace.py` 在真实临时 Git 仓库中验证并行 worktree、恢复、配置保留、错误仓库和符号链接拒绝。`test_dispatch.py` 使用真实 SQLite 事务验证租约、幂等、并发、撤权、过期对账、共享资产锁和旧轮次 fencing。

`test_runtime_live.py` 为默认跳过的真实模型工程验证。已使用 `deepseek/deepseek-flash` 创建受限 Task Session，模型实际 read/write/bash，在独立仓库实现 `arithmetic.py`，运行冻结的 5 个验收测试；平台随后独立复验测试、产物哈希、Session/工作区恢复和原生 abort 回执。可核验原生 Session/Tool ID、事件类型与测试输出见 [真实 Runtime 报告](runtime-live-report.json)。报告中 `whole_system_acceptance=false`，这不是多人协作、审批、平台恢复、SSE 业务重连或公司环境的全部验收。

当前保留证据目录位于 `/Users/niuniu/.astra-1.0/runtime-evidence/58ba559acff14863b4a6814627df5842/`，不由 pytest 临时目录清理。原生 Session 为 `ses_ecec77f49ffe3R17poB48S041D`，未删除。自动清理不得将此验收证据当作普通临时产物移除。

重复执行真实模型测试会消耗额度。显式指定安全 Runtime、模型、凭据环境变量，使用 `ASTRA_LIVE_WORK_ROOT` 保留独立工作区：

```bash
ASTRA_LIVE_OPENCODE=1 \
ASTRA_LIVE_MODEL=deepseek/deepseek-flash \
ASTRA_LIVE_URL=http://127.0.0.1:4096 \
ASTRA_LIVE_WORK_ROOT=/absolute/private/astra-runtime-evidence \
ASTRA_LIVE_REPORT=docs/astra-1.0/runtime-live-report.json \
python -m pytest -q -s tests/v1/test_runtime_live.py
```

## 待完成的集成与风险

- 将数据库派工绑定与提交后 OpenCode 启动、稳定消息 operation、持续观察、证据验证、业务验收完整接入任务服务；不能停在 `BOUND`。
- 将 Persona 原生短会话、可信 MCP Principal、实际决策动作与长期 Inbox/Memory 恢复连接；不得用脚本回复冒充员工判断。
- 权限撤销、暂停/停止/接管须实际中止受影响副作用并对账，既有操作不会因 DB 状态变化自动消失。
- 完成真实的运行中取消、断线/平台重启、跨 Worker 恢复、权限撤销、多员工/多任务及公司固定版本验证。当前通过的工程测试不覆盖这些系统场景。
- 部署中须指定可达路径、隔离账号、Credential 引用与内网镜像；本机 API 描述可读不能证明公司 Runtime 或第三方模型网关可用。
