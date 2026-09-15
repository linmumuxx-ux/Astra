---
name: nexus-task-ops
description: 处理 NEXUS 任务查询、创建、取消、重试、恢复、重新分配，以及任务执行员工选择。用于需要把自然语言任务意图整理成平台字段、解析真实对象并进入 prepare → 用户确认流程的场景；简单平台统计不要加载此 Skill。
compatibility: opencode
metadata:
  domain: task
  version: "2"
  learning: candidate-review
---

# NEXUS 任务处理

把用户意图转成最少、可验证的平台操作。状态机、默认值、资格、风险等级和最终执行始终以后端为准，本 Skill 不复制这些规则。

## 工作流

1. **确认意图**：区分查询、创建、取消、重试、恢复、重分配。用户只是询问或比较时保持只读。
2. **解析对象**：已知任务 ID 用 `nexus_task_get`；按名称/关键词找任务用 `nexus_task_search`。名称不能代替 ID，多候选时先消歧。
3. **创建任务时整理字段**：
   - `task_type`：问题处理通常为 `ISSUE`，新增/改造需求通常为 `REQUIREMENT`；确实无法判断再询问。
   - `title`：只概括明确目标。
   - `description`：保留目标、范围、约束和用户给出的上下文，不补造背景或方案。
   - `acceptance_criteria`：只写明确且可验证的结果；信息不足时省略。
   - `priority`：用户未指定时省略。
   - `category_id`：没有真实 ID 时不要猜。
   - `employee_id`：默认可省略；只有用户明确指定、要求推荐或需要重分配时才解析员工。
4. **选择员工时按需调用**：姓名/岗位查询用 `nexus_employee_search`，详情用 `nexus_employee_get`，要求“谁适合”时用 `nexus_employee_recommend`。使用平台返回顺序和推荐原因，不自行发明评分。
5. **变更前刷新事实**：已有任务操作先 `nexus_task_get` 获取最新状态，然后直接调用对应 `nexus_task_prepare_*`；不要在 Skill 中维护一份允许状态表。
6. **一次 prepare 后停止**：拿到 `operation_id` 后转述预览、风险和待确认事项，不重复 prepare，不调用 confirm。

## 经验复用

对复杂、曾被纠正或容易走错路径的任务，在执行关键步骤前可先用 `nexus_knowledge_search(keyword="nexus-task-ops")` 查找已发布经验；只读取与当前场景直接相关的少量条目。经验用于补充调用方法，不能覆盖实时 Tool 事实和 Backend 判定。

简单、标准路径不要为了“学习”额外查询知识。

## 自迭代

只有出现**明确学习信号**时，才调用数字图书馆 MCP 的 `library_submit_experience` 提交经验候选：

- 用户纠正了任务类型、字段理解、员工选择或操作路径；
- prepare 被后端拒绝，随后找到有证据的正确处理方式；
- 发现当前 Skill 未覆盖、且明显可复用于同类任务的稳定方法。

普通成功、一次性业务数据、模型猜测、临时环境故障不要沉淀。

候选经验使用：

- `title`：`[nexus-task-ops] <简短经验标题>`
- `summary`：说明“什么场景下原路径为什么不合适，以及应如何处理”
- `content_md`：至少包含 `适用场景 / 触发信号 / 推荐处理 / 不要这样做 / 证据`
- `tags`：至少包含 `assistant-skill`、`nexus-task-ops`
- `source_task_id` / `source_run_id`：有真实 ID 时填写
- `experience_data`：记录 `skill=nexus-task-ops`、场景和修正点

提交后只说明已形成“经验候选”；候选不能当场视为正式规则，需经数字图书馆审核发布后才能作为后续稳定经验复用。经验提交失败不得影响当前任务处理。

## 常见错误

- 为了填满字段而猜分类、优先级或员工。
- 把员工姓名直接拼成 ID。
- 在 Skill 里复制 Backend 状态机，导致规则漂移。
- 用户只问问题却触发 prepare。
- 等待确认时重复调用 prepare。
- 因一次异常就提交“经验”。
