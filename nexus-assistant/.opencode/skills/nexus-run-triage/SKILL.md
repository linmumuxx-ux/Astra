---
name: nexus-run-triage
description: 查询 NEXUS 任务执行记录、分析失败/超时/丢失运行、解释执行异常并判断下一步处理方式时使用。区分 Task、Run 和 Employee 状态，只根据平台汇总的真实失败现场做诊断。
compatibility: opencode
metadata:
  domain: run
  tools: nexus_run_*
---

# NEXUS 执行诊断

用于回答“任务为什么失败”“刚才执行到哪了”“这次运行是什么状态”“接下来应该重试还是人工处理”等问题。

## 查询路径

- 已知 `run_id`：调用 `nexus_run_get`。
- 查看某任务的历史执行：调用 `nexus_run_search(task_id=...)`。
- 分析失败现场：调用 `nexus_run_failure_summary(task_id=...)`；没有指定任务时才查询最近失败现场。
- 需要判断任务当前是否允许重试/恢复时，再调用 `nexus_task_get` 获取最新 Task 状态。

## 诊断方法

按以下顺序组织结论：

1. **发生了什么**：Run 状态、退出码、failure code、执行器状态、开始/结束时间。
2. **任务现在怎样**：Task 当前状态、当前进展、`execution_error` / `failure_reason`。
3. **能确定的原因**：只解释 Tool 返回的错误事实。证据不足时写“当前信息不足以确定根因”，不要补造日志或调用链。
4. **下一步**：根据 Task 最新状态给出处理建议，不把建议说成已执行。

## 状态边界

Task、Run、Employee 是不同状态域，不互相代替。例如 Run `TIMEOUT` 不等于 Task 必然 `FAILED`，员工 `WORKING` 也不代表某个 Run 正常。

失败汇总只覆盖平台提供的失败现场（当前为 `FAILED` / `TIMEOUT` / `LOST` Run）。没有命中时，不得声称系统“没有异常”，只能说明该查询未返回匹配失败记录。

## 后续操作

- Task 为 `FAILED` / `EXECUTION_ERROR` 且用户明确要求重试：加载 `nexus-task-ops`，按任务操作流程 prepare retry。
- Task 为 `SUSPENDED` / `WAIT_HUMAN` 且用户明确要求继续：先说明待人工原因；确认条件已满足后加载 `nexus-task-ops` prepare resume。
- 用户只要求分析原因或给建议：不要触发任何 prepare。
