> 历史归档。本文记录当时的设计或验收，不作为当前 Nexus 行为契约。

# Astra V0.4 实现与需求映射

## 产品边界

V0.4 延续 V0.3：Astra 只管理任务定义、员工分配、工作观察、人工处理和结果。数字员工的 Agent 自主选择 Agent、Skill、Tool、命令和检查方式。平台没有引入 Workflow / Phase 编排、任务级 Workspace、Verifier 或 Worktree。本地与 Linux SSH 远程的正式 Runtime 都是 OpenCode Server；可重复测试和运维应急才显式使用隔离的 CLI fallback。

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

## Server Runtime 与工作观察

Coordinator 为每个 Task/Run 绑定真实 OpenCode Session ID，以 Server Event SSE 作为执行事实：

1. `message.part.updated` 中的文本和 Tool 经 Semantic Event Adapter 写入任务现场；
2. Task Tool metadata、Child `parentID` 和 Child Session Event 识别真实 Subagent 及其内部 Tool；
3. `question.asked` 保存原生 request ID，用户回答后调用 Reply 并继续原 Session；
4. 暂停、挂起、取消调用 Session Abort；
5. 完整结构化 Event、Message error、Token / Tool 汇总保留在 Run 和证据文件。

Linux 远程由 Paramiko 建立 SSH 本地端口转发，Server 只监听目标机 loopback。每个 Run 使用远程 POSIX Workspace 和真实 Session ID；Question/Resume/Abort 不回退到 CLI stdout 解析。

平台不记录或展示模型内部推理，不调用另一模型生成二次总结。

## 界面

- 总览：数字办公室按岗位自动分区，以差异化数字肖像、人物近况和状态灯呈现员工；工作/空闲/等待/异常/完成指标仍保留，Token 和 Tool 仅作辅助信息。
- 数字员工：办公室/列表切换，岗位区域内展示拟人化员工卡片，点击后展开当前工作现场；员工详情继续显示当前工作与任务队列。
- 待处理：聚合人工协助、挂起、待确认、执行异常和无活动提示。
- 任务详情：工作进展、详细操作、原始 Run / 日志三层结构。
- 配置中心：员工状态与环境状态分开展示；普通保存不重置环境，环境变更后自动检测；每名员工可配置 Agent 模型；增加减少动效偏好。

## 迁移与验证边界

`0004_astra_v04` 在 V0.3 数据上增量添加完成策略、挂起/异常/退回、活跃度和提交/确认时间，并将旧 `PAUSED` 转为 `SUSPENDED`。`0005_employee_model` 为员工 Agent 工作环境增加可选模型覆盖。`0006_ssh_password` 将 Linux 远程认证从 SSH Agent/密钥路径迁移为数据库密码字段；API 只暴露是否已配置，任务与 Run 快照不保存密码，远程命令由 Paramiko 执行。`0010_remote_opencode_server` 增加远程私有 Server Port，并把 Linux 主链切换为 SSH Tunnel + Session/Event API。

V0.4 当前通过 Ruff、67 个后端单元/集成测试、前端类型检查和生产构建；10 条 Chromium E2E 显式使用 CLI fallback fixture 做可重复业务验收。OpenCode 1.18.25 + `opencode/glm-5.1` 的真实 Server 验收覆盖 Session、SSE、Tool、Subagent/Child Tool、Question/Reply、同 Session 多轮、Abort 和并发隔离；Astra Coordinator 端到端烟测也已使用真实 Server/GLM5.1 完成任务、Tool、Session ID 和用量持久化。远程适配另有 SSH 隧道、远程 POSIX Workspace、私有 Server 自启动和主/fallback 选择测试；仓库现场没有可认证的 Linux SSH 主机，因此不把远程主机 E2E 伪报为 PASS。
