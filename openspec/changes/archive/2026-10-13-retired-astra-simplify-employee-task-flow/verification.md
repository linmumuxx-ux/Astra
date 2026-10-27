# 验证记录（2026-09-30）

基线：`refactor/dev-constraints-20260929`，`f7aed8b5094086c8420e8ce74d1e743bab9afbd9`。
开发分支：`fix/employee-task-flow-20260930`。

| 维度 | 结果 |
| --- | --- |
| 完整性 | 实施、静态/回归验证与本地真实业务验收完成；公司环境远程流程仍未验证 |
| 正确性 | 3 项 Requirement 均有实现与回归覆盖；真实模型回复、原生问答/权限、真实断线重连、两种终态均已在真实 1.2.27 上通过 |
| 一致性 | 沿用 Task、RuntimeSession、Workspace 和 Element Plus；无新表、状态或编排层 |

本轮真实验收的完整脱敏证据见 `evidence/real-verify-20260930/`（README / acceptance-matrix /
fixes / limits-and-risks / checks）。

## 实际执行

- 在 `services/task-platform/` 执行 `../.venv/bin/python -m ruff check app tests`：通过。
- 后端全量 `PYTHONDONTWRITEBYTECODE=1 pytest -q --tb=short`：397 passed、4 skipped（70.06s）；
  4 项均为 opt-in 外部依赖（2 项需真实 Redis，2 项需 `ASTRA_REAL_OPENCODE=1`），
  已由独立执行在真实环境单独跑通并记入 `evidence/real-verify-20260930/opt-in-summary.md`。
- 一次全量运行中 `test_employee_serve.py::test_two_employees_start_and_reuse_independent_serve`
  因该用例自身 3s 启动预算在并行负载下超时而失败；隔离重跑 3 次与最终全量均通过，
  未放宽 timeout 也未改断言，改动不涉及该路径。
- 调度与 Workspace 专项：dispatcher/dispatch 5 passed；permission 与历史 Session 8 passed。
- 管理台 `npx vue-tsc -b`、`npx vite build`：均通过（退出码 0）。刻意不用 `npm run build`，
  避免重建未改动的 workspace-ui 产物。
- Diff 请求身份竞态回归（真实组件 + 真实 Chromium + 真实 fetch，仅注入网络时序）：
  `ASTRA_DIFF_RACE_TASK=<真实任务> npx playwright test e2e/task-diff-race.spec.ts --project=chromium`
  → 5 passed；移除身份守卫后首项明确失败，恢复后全通过。
- `npm run build` 会先重建未改动的 `workspace-ui` 1.18.31 产物，已仅回滚该批构建结果，
  未提交产物、未触碰 1.2.27、未修改 `web/workspace-ui/` 源码。

## 本轮修复（真实浏览器暴露）

1. **指定员工的任务不自动启动**：`Dispatcher.claim_once` 无条件要求 `auto_claim=True`，
   人工指定员工（`auto_claim=false`）的任务永远不被领取，因而不会自动启动。
   已改为按 `task.employee_id` 精确匹配，`auto_claim` 只约束无人认领的任务池。
   修复后 root 的 `T-20260930-73AB4C` 自动变 `RUNNING` 并创建真实 Session。
2. **原生 UI 无法回答权限请求**：1.2.27 原生 UI 使用
   `POST /session/{sessionID}/permissions/{permissionID}`，而 Workspace 代理只放行
   `/permission/{id}/reply`，真实日志为 `403 Forbidden`，UI 报「请求失败 / [object Object]」
   且权限卡不消失。已把 legacy 路径并入同一 Session 归属校验与转发路径，浏览器复验通过。
3. **代码变更抽屉可能永久加载**：Diff 接口本身无缺陷（命令行 0.08s/200，日志中无对应
   UI 请求），前端读取缺上界。已加 20 秒 AbortController 与可读失败提示；
   多标签/热重载是否为唯一诱因未确证，按限制记录。

## 真实业务验收（OpenCode 1.2.27 + opencode/space-bunny-free，无 mock）

- 自动启动、多轮复用同一 Session、单轮结束不完成任务、原生 question/permission 闭环、
  原生停止后继续、真实提交后累计与未提交 Diff、真实断线重连不丢 Session 不重复提交、
  人工完成与人工终止两种终态在详情/列表/办公室三处一致：均通过。
- 真实 Serve 启动失败（端口被占）时任务保持非终态、无 Session、员工占用释放，人工继续后
  真实成功：通过。
- 真实 elapsed 超时注入（隔离 fixture、真实 1.2.27、`ASTRA_OPENCODE_TIMEOUT_SECONDS=12`、
  `time.monotonic()` 实测）：Session `INTERRUPTED` + `terminal_reason=timeout` 时业务任务仍为
  `WAITING`、Session 未变、该 prompt 上游用户消息恰好 1 条，可继续；公司 Windows/Linux SSH
  未配置，明确未验证。
- 真实 in-flight ACK 丢失 / 晚到 ACK 仍只由模拟回归覆盖，隔离注入未产出结果。
- 原生长时间无首 part 的挂起（第二轮 busy、token 0、无 error，5 分 04 秒后人工 abort）
  原因未确定，不宣称该轮通过；传统办公室场景在本分支未挂载，浏览器一致性未验证。
  详见 `evidence/real-verify-20260930/limits-and-risks.md`。
- 浏览器终态与 Diff 由 root 的真实 Chrome 复核：EE0439 仅一次 `stop` 即 `CANCELED`
  （日志核对无 start/confirm/restart），最终 controller 版 Diff 累计/未提交均正常。

## 场景覆盖

| 场景 | 代码与回归证据 |
| --- | --- |
| 持续交流和人工结束 | `lifecycle.py`；`test_manual_confirm_waits_for_business_confirmation`、`test_native_permission_reply_is_denied_after_business_terminal` |
| 指定员工自动启动 | `dispatcher.py`；`test_dispatcher_claims_task_assigned_to_employee_without_auto_claim`、`test_dispatch_respects_employee_auto_execute`、`test_claimed_task_without_session_is_offered_again_for_start_retry` |
| 原生问题、权限、停止、失败 | `workspace_routes.py`、`lifecycle.py`；`test_native_permission_reply_is_allowed_only_for_task_session`、`test_bound_historical_session_rejects_native_writes`、子 Session 问题恢复与原生 abort 专项 |
| 断线、重试、晚到 ACK | `recovery.py`、`lifecycle.py`；lost-ack、delayed-ack、supersede、断线、停止后继续及旧 ACK 不中断新轮专项 |
| Worktree、配置、提交成果 | `session_connection.py`、`workspace_changes.py`；真实 Git 累计/当前 Diff、中文路径、配置及远程 shell 专项 |
| 简化创建及观察 | `schemas.py`、TaskCreateDrawer、store；现有 API 回归、busy/idle 消息读取与 supervisor 测试 |

## OpenSpec 核实（按仓库 openspec-verify-change 流程）

`node .opencode/tools/openspec.mjs status --change simplify-employee-task-flow --json`：
schema `spec-driven`、artifacts `proposal / specs / design / tasks` 齐备、`actionContext.mode = repo-local`。
`openspec validate simplify-employee-task-flow` 只做静态 schema 校验（通过），
**不等于**实现与 Scenario 核实；下列为按 spec/design/tasks 逐条读实现与测试的核实结果。

### Summary

| 维度 | 状态 |
| --- | --- |
| 完整性 | tasks 4/5 完成，2.2 因公司 SSH 未验证保持未完成；3 个 Requirement 均有实现 |
| 正确性 | 6 个 Requirement 全部有实现映射，Scenario 覆盖见下表 |
| 一致性 | 沿用 Task / RuntimeSession / Workspace / Element Plus，无新表、状态或编排层 |

### Requirement → 实现映射

| Requirement | 实现 | 核实 |
| --- | --- | --- |
| 持续工作与人工结束 | `lifecycle.py:1071` `confirm_completion`（仅人工动作关闭业务任务，重复调用幂等）、`lifecycle.py:856` `stop(cancel_task=...)`、`workspace_routes.py:390` 原生 abort 走 `cancel_task=False` | 一致 |
| 工作区及成果一致 | `session_connection.py:105/127/142`（worktree 归属、目录根、注册校验与配置继承）、`workspace_changes.py:171` `workspace_diff(cumulative=…)` | 一致；`workspace_diff` 直接读绑定工作区 Git，不依赖外网 |
| 简化入口和观察 | `schemas.py`（无完成策略/验收标准必填）、`TaskCreateDrawer.vue`、`stores/astra.ts`（事件合并刷新）、无自动复盘调度 | 一致 |

### Scenario 覆盖

| Scenario | 覆盖来源 |
| --- | --- |
| 多轮交流 | 真实：同一 Session 两轮、任务保持 `RUNNING`；回归 `test_continue_keeps_session_and_does_not_create_execution_copies` |
| 原生人工介入 | 真实：question 与 permission 均闭环；回归 `test_native_permission_reply_is_allowed_only_for_task_session`、`test_bound_historical_session_rejects_native_writes` |
| 执行失败与超时 | 真实：Serve 启动失败不终结任务并可人工继续；真实 elapsed 超时 → Session `INTERRUPTED`/`reason=timeout` 而 Task 仍 `WAITING`；回归 `test_start_definitive_failure_clears_pending_and_aborts_created_session` |
| 明确完成 | 真实：`confirm` → `SUCCEEDED` 且重复 confirm / refresh 不重开；回归 `test_delayed_ack_does_not_clear_manual_confirmation` |
| 终止和原生中断 | 真实：原生 abort 保留任务、终止为 `CANCELED`；回归 `test_stop_cancels_continued_round_after_lost_ack_on_succeeded_task` |
| 断线重试和旧轮次隔离 | 真实：Server 断线后 reconnect 同 Session、单一用户消息（发生在响应完成之后）；in-flight ACK 仍为模拟回归，真实注入未覆盖 |
| 复用与配置 | 真实：项目 `opencode.json` 继承并触发原生权限；回归覆盖错仓库/嵌套/符号链接与配置保留 |
| 提交后查看 | 真实：任务页累计 Diff 含已提交成果、未提交视图独立；原生按 Session 的 `session/{id}/diff` 分别只含各自改动 |
| 创建与观察 | 真实：手动指定员工后自动启动（本次修复）；`auto_claim`/`auto_execute` 边界由 `test_dispatcher_claims_task_assigned_to_employee_without_auto_claim`、`test_dispatcher_keeps_unclaimed_pool_on_auto_claim`、`test_dispatch_respects_employee_auto_execute` 覆盖 |

### 未通过 / 未覆盖（阻塞归档）

- CRITICAL（归档前必须完成）：`tasks.md` 2.2 公司环境真实业务验收未完成（无 SSH 配置）。
- WARNING：真实 in-flight ACK 丢失 / 晚到 ACK 未覆盖（首次注入 `forwarder_prompt_async_total=0`，
  未进入转发链路）；真实 Session execution error 未覆盖（Serve 端口失败不能替代）；
  OpenCode 原生第二轮长时间无首 part 的挂起根因未知；传统办公室场景本分支未挂载。
- 以上均如实记录，未以模拟或失败前提冒充真实通过。

## 归档状态

`tasks.md` 2.2 仍**未完成**：公司环境 SSH 与真实远程 1.2.27 流程未验证，
按实际情况不归档、不虚构已完成。

