---
name: nexus-operations-overview
description: 用户询问 NEXUS 平台整体任务情况、成功率、待人工/执行异常/待确认数量、数字员工负载或“现在有哪些事情需要关注”时使用。统计直接采用后端聚合结果，不让模型自行遍历任务计算。
compatibility: opencode
metadata:
  domain: operations
  tools: nexus_operation_*
---

# NEXUS 运营概览

用于平台运营态势、待处理事项和员工负载查询。所有数字以平台聚合 Tool 为准。

## Tool 选择

- 整体任务量、状态分布、完成数、失败数、成功率：`nexus_operation_overview`。
- 待人工、执行异常、待确认数量：`nexus_operation_pending_actions`。
- 各数字员工当前任务负载：`nexus_operation_employee_load`。

用户问“平台现在怎么样”“有什么要处理的”时，可组合 overview + pending actions；只有涉及人员负载时再查询 employee load。

## 解释规则

- 直接使用 Tool 返回的 `total_tasks`、`status_distribution`、`success_rate` 等，不自行重新计数或另算口径。
- `pending_actions` 返回的是数量，不代表已经获得具体任务列表。用户继续问“具体是哪几个”时，再使用 `nexus_task_search` 按相应状态查询。
- 员工负载只表示 `current_task_count` 和员工状态，不等同于产能、效率或任务难度，不自行生成绩效排名。
- 成功率为平台当前定义的统计口径；不要擅自引入“排除取消”“只算今日”等新口径。

## 从概览到处理

发现待人工或执行异常后，可以建议用户进一步查看具体任务；只有用户明确要求执行取消、重试、恢复、重分配等操作时，才加载 `nexus-task-ops` 并进入 prepare 流程。

## 输出方式

优先给出一段短结论，再列出最值得关注的 2–4 个数字或异常项。没有异常项时直接说明当前聚合结果，不为了“有洞察”而制造问题。
