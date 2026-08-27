# Astra V0.4 实现与需求映射

## 产品边界

V0.4 延续 V0.3：Astra 只管理任务定义、员工分配、工作观察、人工处理和结果。数字员工的 Agent 自主选择 Agent、Skill、Tool、命令和检查方式。平台没有引入 Workflow / Phase 编排、任务级 Workspace、Verifier、多 Agent 或 Worktree。当前内置 OpenCode 本地/SSH 适配器，执行器抽象可扩展到其他 Agent。

## 连续工作

- Celery Dispatcher 保持每名员工同时一项任务。先选显式指定员工的任务，再选未指定任务；各自按优先级降序、创建时间升序。
- 任务提交结果后立即释放员工；周期分配器会继续领取后续任务。
- 任务 Session 始终绑定 Task；挂起、人工补充、退回和异常恢复优先继续原 Session。原 Session 不可用时，携带已保留上下文创建新 Session。

## 状态与人工处理

```text
READY → RUNNING → COMPLETED
                  → PENDING_CONFIRMATION → COMPLETED
                                         └→ READY（退回原员工）
                  → WAIT_HUMAN → RUNNING
                  → SUSPENDED → READY
                  → EXECUTION_ERROR → RUNNING
                  → FAILED / CANCELLED
```

`WAIT_HUMAN` 占用员工；`SUSPENDED` 保留现场但释放员工。Agent、SSH、工作环境或平台中断先进入 `EXECUTION_ERROR`，不直接当作任务未完成。

很高和高优先级默认 `MANUAL_CONFIRM`，中和低默认 `AUTO`，创建任务时可覆盖。退回会保留提交结果与意见历史。

## 恢复与活跃度

- Backend 启动和 Celery Beat 扫描 `RUNNING` / `WAIT_HUMAN` / `SUSPENDED` / `EXECUTION_ERROR`。
- 当运行中任务超过配置时间没有新 Event，只设置 `inactivity_alert`。
- 执行异常任务仅在员工环境于异常后重新检查为 `AVAILABLE` 时自动恢复，防止无限失败循环。

## 工作观察

Agent JSON 输出被流式观察，不等待整次 Run 结束：

1. 文本事件写入 `WORK_PROGRESS`，同步任务当前进展和最后活动时间；
2. 工具与模型用量事件写入 `operation` 层；
3. 完整 Agent JSON、stderr、Token / Tool 汇总保留在 Run 和证据文件。

平台不记录或展示模型内部推理，不调用另一模型生成二次总结。

## 界面

- 总览：数字办公室、工作/空闲/等待/异常/完成指标，Token 和 Tool 仅作辅助信息。
- 数字员工：办公室/列表切换，员工详情显示当前工作与任务队列。
- 待处理：聚合人工协助、挂起、待确认、执行异常和无活动提示。
- 任务详情：工作进展、详细操作、原始 Run / 日志三层结构。
- 配置中心：员工状态与环境状态分开展示；普通保存不重置环境，环境变更后自动检测；每名员工可配置 Agent 模型；增加减少动效偏好。

## 迁移与验证边界

`0004_astra_v04` 在 V0.3 数据上增量添加完成策略、挂起/异常/退回、活跃度和提交/确认时间，并将旧 `PAUSED` 转为 `SUSPENDED`。`0005_employee_model` 为员工 Agent 工作环境增加可选模型覆盖。

V0.4 已通过 Ruff、37 个后端单元/集成测试、前端类型检查、生产构建和 10 条 Chromium E2E。系统 E2E 启动隔离 Redis、Celery Worker/Beat、Backend、Frontend 和可控 Agent，正式覆盖员工模型配置、配置保存与“询问—等待答复—继续原会话—结构化验收”。另使用本地 OpenCode 1.18.23 与 `deepseek/deepseek-v4-flash` 验证真实任务领取和结构化询问。详细证据见 `docs/verification/E2E-V0.4-2026-08-28.md`；`docs/verification/E2E-2026-08-27.md` 仅保留为 V0.2 历史记录。
