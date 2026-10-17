## Context

`derive_session_state` 已把 busy/retry 视为 RUNNING，并把正常结束、助手错误、无回复和未完整结束分成不同 Session 结果。`_project_session_state` 却把 Session SUCCEEDED 和 RUNNING 都写成 Task RUNNING。当前轮锚点不在消息列表里时，idle 会一直返回 RUNNING。

OpenCode 1.18.35 的事件（vendored SDK）是 `session.status`（`idle` / `busy` / `retry`）、已废弃的 `session.idle`，以及 `session.error`（`sessionID` 与 `error`，没有 message id）。一次 `session.error` 不能当成本轮最终失败。

## Goals / Non-Goals

**Goals:**

- 修正已有投影：本轮正常结束进入待验收，最终失败或未完整结束进入待恢复，断连保持原业务状态并标明异常。
- Worker 在 Task 未正式关闭前保持独占。取消必须先确认执行停止。
- 重复 SSE 和 refresh 不产生重复状态事件和唤醒。

**Non-Goals:**

- 不新增 RETRYING，不记录或改写 OpenCode retry 次数。
- 不把 Session FAILED 自动写成 Task FAILED。
- 不启用 AUTO 完成策略，不新增 Run 状态机。

## Decisions

1. 待验收、待回答、待恢复都使用现有 Task WAITING。原因分别写在 `human_required_reason`；执行异常同时写 `execution_error` 与 Session `terminal_reason`。
2. 当前轮锚点缺失且 idle 超过宽限期时，Session 记为 INTERRUPTED / `unconfirmed`，Task 进入待恢复。这不是成功，也不是模型失败。
3. 助手错误只看当前轮最后一条 assistant。其后若已有更新的 user 消息，不把旧错误当成这一轮的结果。
4. SSE 只触发对账。`session.error` 不再直接写入 `failure_reason`。对账读取真实消息，并用 `last_message_id` 与 `turn_started_at` 丢弃过期观察。
5. 确认完成只接受本轮 Session SUCCEEDED。消息重读失败时，仅当绑定 Session 已经是 SUCCEEDED 才允许确认，并且不把 UNKNOWN 改写成成功。
6. 取消先 abort，再等待 Session 树离开 busy/retry。等不到则保持占用并报错。
7. 取消与发送预留互斥。`stop` 在接触 OpenCode 之前，于短事务里记下本轮锚点（Session、`last_message_id`、`pending_message_id`、`turn_started_at`），并把 `suspension.cancel_token` 提交为带截止时间的预留。截止时间覆盖 abort 等待，进程崩溃后预留会过期，不新增列。`send` 与 `retry_submission` 在持有行锁、写入新预留之前看到有效预留就拒绝。最终事务再次核对锚点与预留标识都未变，才清空预留、写入取消并释放 Worker。锚点已变时只去掉自己的预留，保留新的 `pending_message_id`，不释放 Worker。SQLite 与 MySQL 都只在短事务里 `with_for_update`，不把行锁留在 OpenCode I/O 上。
8. idle 快捷路径在 Session 已是 SUCCEEDED、Task 仍是 RUNNING 或待验收文案未对齐时，先幂等投影到待验收并最多唤醒一次。已经对齐的重复 refresh 不再读历史、也不再发事件。
9. 同一轮里 Task 一直是 WAITING 时，有效等待原因第一次变化仍写 `TASK_WAITING` 事件、复用 outbox，并更新 `current_progress`。原因不变的 refresh 不新增事件。
10. `unconfirmed` 不是可以跳过历史读取的确定终态。消息重新出现后按当前轮重新推导，可以回到 SUCCEEDED 并进入待验收。

## Risks / Trade-offs

- [历史数据里 Session 已成功但 Task 仍是 RUNNING] → 下一次对账会把 Task 收到 WAITING，并唤醒一次责任员工。快捷路径会先做这次投影，而不是直接返回。
- [确认完成比以前更严] → 读不到本轮且 Session 还不是 SUCCEEDED 时不能确认。避免把未知执行收成业务成功。
- [取消预留写在现有 suspension JSON] → 只读写 `cancel_token` 这一键，挂起现场等其他键保持不动。预留过期前崩溃会暂时拒绝新输入，过期后发送恢复。

## Migration Plan

无表结构变更。部署后由现有 Session 监听和周期对账收敛。

## Open Questions

无。真实 OpenCode 进程上的限流回放不作为合并门禁；单元与集成测试覆盖同一判定。
