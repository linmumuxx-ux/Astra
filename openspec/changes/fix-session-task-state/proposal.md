## Why

OpenCode 本轮已经结束或异常停止后，Task 仍显示 RUNNING。用户无法区分执行中、本轮已完成、执行异常和等待确认；断连时页面还会像正常执行一样。

## What Changes

- 保留现有 Session 与 Task 状态枚举。Session 成功或最终失败只改变本轮事实，不自动关闭或判失败业务 Task。
- Session RUNNING（含 OpenCode busy/retry）投影为 Task RUNNING。Session SUCCEEDED 投影为 Task WAITING（待验收）。Session FAILED 与 INTERRUPTED 投影为 Task WAITING（待恢复）。Session UNKNOWN 保留原 Task 状态，并显示连接异常。
- 当前轮无法定位且服务已停止时，宽限期后收敛为待确认，不再永久 RUNNING。只用当前轮消息，不沿用上一轮回复或错误。
- RUNNING 与 WAITING 都继续占用 Agent Worker。Task 正式完成，或取消且确认执行已停止后，才释放。
- 进入待验收或待恢复时复用 Task Wake Outbox 通知责任员工。重复对账不重复切换、不重复唤醒。

## Capabilities

### New Capabilities

- `session-task-sync`：Session 本轮结果与 Task 业务状态的投影、Worker 占用和可见原因。

### Modified Capabilities

- 无。不修改 `openspec/specs/` 中的历史契约。

## Impact

- `services/task-platform/app/runtime/session_state.py`、`lifecycle.py`、`recovery.py`、`wake_outbox.py`。
- 任务列表、任务详情和办公室状态文案。
- 不新增 Run 状态机，不启用 AUTO 完成，不改 OpenCode 重试策略。
