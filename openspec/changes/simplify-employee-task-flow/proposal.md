## Why
单轮回复被当成任务完成，人工确认阻塞继续交流；远程工作区和公司版 Diff 影响实际使用。

## What Changes
- Task 仅由人工完成或终止；回复结束保持可交流，原生中断只结束当前轮。
- 收敛 Worktree 复用校验、项目配置读取、累计和未提交 Diff。
- 移除自动复盘触发、无效完成策略入口和重复刷新。

## Capabilities
### New Capabilities
- `employee-task-lifecycle`：已有员工任务流程的业务契约，现有 Spec 尚无此 capability。
### Modified Capabilities
无。

## Impact
既有 Runtime、Workspace 代理、任务表单和详情。保留 Task/RuntimeSession 表及原生界面，无数据库结构变更，无新增编排。
