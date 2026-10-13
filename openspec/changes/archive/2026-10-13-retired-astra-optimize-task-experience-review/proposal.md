## Why

现有后台复盘没有接入周期调度，人工确认也可能留下非终态 Session；员工侧仍可主动提交经验，去重仅覆盖同一来源的完全相同内容。任务成功还被误用作经验验证依据。

## What Changes

- 人工确认完成后由后台统一复盘，支持幂等提交、失败重试及旧轮次隔离；任务结束不依赖复盘成功。
- **BREAKING** 移除员工侧经验提交 MCP，员工仅执行任务、查询知识和反馈。
- 复盘先保存客观任务总结，提炼通常不超过两条、允许零条的经验；检索相似候选及正式知识，合并证据，内容补充必须重新审核。
- 校验真实 Session 引用，区分执行成功、经验验证和人工发布；详情展示总结、复盘状态、关联经验及重试入口。
- 不新增表、执行状态机、向量服务；保留既有数据与正式知识。

## Capabilities

### New Capabilities

- `task-experience-review`: 任务完成后的总结、经验去重、证据校验、人工发布及可观察重试。

### Modified Capabilities

无。现有 capability 只约束 Skill 注册与平台助手权限，没有定义任务复盘业务。

## Impact

影响确认完成链路、Celery 周期任务、助手 MCP/Skill、知识服务和任务详情。复用 TaskReview、TaskSummary、KnowledgeItem 与 ExperienceEvidence；不删除历史知识。
