> 历史归档。本文记录当时的设计或验收，不作为当前 Nexus 行为契约。

# Runtime 最终状态适配

基于远端 `refactor/runtime-final-state` 的 `bc20909` 继续实现。生产执行入口为 `RunCoordinator.process(run_id)`；普通执行、人工恢复、自动重试、Session 恢复和用户续聊均经持久化 Run 与 Outbox，Worker 领取后才执行。

## 状态及异常

- Run 是事实源；Task、Employee 提供业务投影。RuntimeService 统一领取、启动、人工等待、终结、停止、续跑和状态对账。`validate_invariants()` 检查活动 Run 与 Task/Employee 指针、状态和员工占用。
- 删除 Run `BLOCKED`、`PASSED` 和 Task-first 执行回退。人工询问使用 `WAITING_INPUT`，执行超时为 `TIMEOUT`，不可执行为 `FAILED` 加 FailureCode。
- `trigger_reason` 使用设计中的六种原因；`retry_index` 统计自动重试，Session 恢复保留已消耗预算，用户新续聊重置预算。人工回复复用当前 Run，并标记 `HUMAN_RESUME`。
- 异常统一保存 `failure_code/failure_scope/retryable/recovery_action/raw_error`。自动重试的原因和失败原因分开保存，不再把 `AUTO_RETRY` 当作失败码。
- OpenCode 的不存在、服务不可用、执行超时、执行错误采用类型化异常；Session 存在性通过资源接口验证，不解析错误文本。
- 后端 Task/Employee/Run 输出 `runtime_state/runtime_status_label/runtime_detail/active_run/failure`，任务、运行记录与员工界面直接展示后端标签；未知指针显示“状态待校正”。

## 异常恢复

- Redis/Celery 投递失败保持 Outbox PENDING；重投和重复 Worker 消息不能创建重复执行。
- STARTING/RUNNING 心跳超时先探测 Session。BUSY 保留现场；探测不可达持续守望，不能认定丢失；确认缺失才结束旧 Run 并按预算创建恢复 Outbox。
- DONE 收集当前执行轮次的结果，排除旧轮输出及错误消息；Question/Permission 可在 Worker 丢失后恢复人工请求。
- 对账修复 Task/Employee 状态、缺失/错误指针、无 Run 假运行及孤立占用；多活动 Run 冲突关闭失去租约的 Run，保留合法租约。
- 暂停/取消的 Server Abort 持久化为 ABORT_PENDING，失败后定期重试；清理完成前阻止重用原现场。

## 升级与验证

先备份数据库，停止旧版本 Worker/Beat，再在后端虚拟环境执行 `python -m alembic upgrade head`，统一重启后端与 Worker/Beat。不能混跑仍使用 `failure_type` 的旧 Worker。

`0017_runtime_failure_contract` 将 `failure_type` 改为 `failure_code` 并添加统一异常字段；旧值仅在迁移中一次性归一化。SQLite 空库升级、0017→0016→0017 已验证；MySQL 0016→head 离线 SQL 已验证。历史 0008 数据回填不支持全链离线 SQL，正式 MySQL 实连迁移仍需部署环境验收。

自动测试覆盖 Run-only 入口、重复消息、Outbox 失败、Worker 启动/心跳丢失、BUSY/不可达/丢失/DONE、原生人工输入、异常与超时、同 Run 恢复、自动重试预算、状态指针修复。隔离系统 E2E 使用 Redis、Beat、Control/Agent Worker 和可控 CLI Agent；真实 OpenCode 服务与远程 Windows/Linux hard-crash 演练须在对应部署环境执行，不能用模拟探测通过替代现场验收。

## 本轮验收结果（2026-09-08）

- Ruff、`git diff --check`：通过。
- 后端：128 passed；最终 RunCoordinator 收口后专项 3 passed。
- 前端类型检查和 Vite 生产构建：通过，保留既有大 chunk 提示。
- 隔离 Chromium 系统 E2E：19 passed、1 skipped（需真实模型的助手用例）。
- SQLite 空库升级及 0017→0016→0017、MySQL 0016→0017 离线 SQL：通过。
- 修复验收中暴露的 SSE 长事务：每次轮询独立借还连接；ASGI 断开时屏蔽取消直到连接关闭。本地 SQLite 启用 WAL，避免长读取阻塞 Worker 写入。
- 本轮完成开发与本地验收，未部署；提交及合并状态以 Git 历史为准。原有未跟踪 `services/task-platform/～/` 不属于本次交付。

## 合并主分支适配

主分支为 `main`。保留其任务分类提示词、员工独立 Serve、运行记录服务端分页和全量统计，状态筛选接入新的 Runtime 定义。新增 `0018_merge_runtime_category` 汇合分类与 Runtime 两条迁移历史，部署统一执行 `alembic upgrade head`。
