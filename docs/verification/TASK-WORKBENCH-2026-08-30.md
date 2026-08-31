# 持续任务工作台语义与 HITL 验收报告

验收日期：2026-08-30

## 结论

任务详情已从“运行事件时间线”调整为 OpenCode CLI 风格的持久任务会话。P0 询问任务能够在任务详情内完成 User Message → Agent Message → Inquiry → User Answer → 原 Run 恢复 → Agent Final Output 的完整闭环；usage、token、heartbeat、session metadata 不进入主会话流。

## 自动化证据

| 门禁 | 结果 |
| --- | --- |
| Ruff | 通过 |
| 后端单元 / 集成测试 | 58 passed |
| Vue TypeScript 检查 | 通过 |
| Vite 生产构建 | 通过 |
| Chromium 系统 E2E | 10 passed |

系统 E2E 使用隔离数据库、Redis、Celery Worker/Beat、FastAPI、Vue 与可控 Agent 子进程，不复用日常开发数据。

## 四类验收

1. HITL：P0 任务进入 `WAIT_HUMAN / WAITING_INPUT / OPEN`；从任务详情输入答案后，原 Run 恢复并成为 `COMPLETED`，全过程只有一个 Run。
2. 普通任务：直接执行完成，无 Inquiry，保留首条 User Message 与最终 Agent Message。
3. 已完成任务追问：保持相同 Task 与 TaskSession，创建第二个 Run，完成后两个 Run 均为 `COMPLETED`。
4. 状态一致性：等待阶段 Task、Session、Run、Inquiry、Employee 分别为 `WAIT_HUMAN`、`WAITING_INPUT`、`WAITING_INPUT`、`OPEN`、`WAIT_HUMAN`；完成阶段分别为 `COMPLETED`、`COMPLETED`、`COMPLETED`、`ANSWERED`、`IDLE`。

## 历史数据迁移验证

`0008_semantic_workbench` 已在真实本地库完成升级。历史任务 `T-20260829-E81934` 已补齐 TaskSession、首条 User Message、结构化 Inquiry、用户回答和有意义的 Agent Message；旧“模型用量已更新”事件未进入会话消息。升级前数据库备份保存在 `backend/data/backups/astra-before-semantic-workbench-20260830-100050.db`。

`0009_runtime_event_adapter` 已在真实本地库完成升级。现场任务 `T-20260830-C5D9E8` 的 OpenCode 1.18.25 工作记录证明 Subagent 由 `tool_use`、`part.tool=task`、`input.subagent_type=general` 与父子 Session 元数据产生；迁移后新增 `SUBAGENT_COMPLETED`，页面主会话显示“general 已完成子任务”，右侧显示 `Subagent (1)`，不再出现错误空状态。升级前数据库备份保存在 `backend/data/backups/astra-before-runtime-event-adapter-20260830-2019.db`。

自动化包含反例断言：Agent 最终文本即使出现“新的 subagent 返回了 hello world”，也只能产生 `message.agent`，不能生成 Subagent 事件。隔离系统 E2E 使用真实 OpenCode JSON 形状验证 Task Tool 同时投影为 Tool 与 Subagent，并保留 call ID、父 Session、子 Session 和模型元数据。

浏览器复查确认：

- 工作台为深色连续 Session，原始任务、Inquiry、回答、真实 Subagent 与简洁 Agent Output 可见；底部输入区持续可用。
- `T-20260830-C5D9E8` 同时显示 `Subagent (1)`、`general 已完成子任务：Print hello world` 和任务结果，错误空状态不再出现。
- `T-20260829-E81934` 的 Inquiry 正文计算颜色为 `rgb(231, 234, 240)`，问题、回答和最终输出可读。
- 运行信息默认折叠；Tool、Run 生命周期、usage 和 Session 元数据不进入主会话。
