---
name: nexus-task-ops
description: 查询、创建、取消、重试、恢复或重新分配 NEXUS 数字员工平台任务时使用。负责把自然语言任务意图整理为平台任务字段，并严格执行查询校验与 prepare → 用户确认流程。
compatibility: opencode
metadata:
  domain: task
  tools: nexus_task_*
---

# NEXUS 任务操作

处理任务查询和任务生命周期操作。业务状态与权限以平台 Tool 返回为准，不在模型侧自行实现状态机。

## 查询任务

- 已知 `task_id`：优先 `nexus_task_get`。
- 按关键词、员工、任务类型或状态找任务：使用 `nexus_task_search`。
- 搜索命中多个对象且用户要操作“这个/它”时，先消歧，禁止自行选择。
- 回答时优先给出任务编号、标题、当前状态、执行员工和当前进展。

## 创建任务

先从用户请求整理字段：

- `task_type`：仅 `ISSUE` 或 `REQUIREMENT`。故障、问题修复通常为 `ISSUE`；新增、改造、优化需求通常为 `REQUIREMENT`。无法可靠判断时询问用户。
- `title`：根据明确目标生成简短标题，不添加用户未提出的范围。
- `description`：保留目标、范围和约束；不编造背景、数据或技术方案。
- `acceptance_criteria`：只提取用户明确给出或可直接验证的结果；没有可靠信息时可省略，由后端补默认值。
- `priority`：用户未指定时省略，由后端使用默认值。
- `employee_id`：可选。用户允许自动分配时不要强行指定员工；用户要求推荐执行人时调用 `nexus_employee_recommend`。
- `category_id`：未知时不要猜测，交由后端按平台规则补充；用户明确指定分类时才传入真实 ID。

字段足够后只调用一次 `nexus_task_prepare_create`。返回 `operation_id` 后，用简洁中文转述 `preview`、风险等级和待确认事项，然后停止操作，等待平台确认卡。

## 修改任务生命周期

任何已有任务操作都先 `nexus_task_get` 获取最新状态，再决定是否 prepare：

| 操作 | 允许状态 | Tool |
| --- | --- | --- |
| 取消 | 非 `COMPLETED` / `FAILED` / `CANCELLED` | `nexus_task_prepare_cancel` |
| 重试 | `FAILED` / `EXECUTION_ERROR` | `nexus_task_prepare_retry` |
| 恢复 | `SUSPENDED` / `WAIT_HUMAN` | `nexus_task_prepare_resume` |
| 重分配 | `READY` / `SUSPENDED` | `nexus_task_prepare_reassign` |

重分配前通过 `nexus_employee_recommend` 或 `nexus_employee_search` 获得真实 `employee_id`，不要按姓名猜 ID。

## Prepare 规则

1. prepare 只是生成待确认操作，不代表已经执行成功。
2. 同一用户意图只调用一次 prepare，不因等待确认而重复调用。
3. 不调用 confirm、不模拟用户确认；真正执行由平台确认接口完成。
4. prepare 被后端拒绝时，原样说明核心原因，并基于最新任务状态给出可行下一步。
5. 用户只是询问、分析或比较时，不触发 prepare。
