# Astra V0.1 实施简报

## 目标

交付一个可独立运行的最小闭环：任务创建/发现 → Astra-01 原子领取 → 独立 Workspace → OpenCode CLI 执行与同 Session 重试 → 独立验证 → 证据保存 → 结果回填 → 员工恢复 IDLE。

## 已核实现场

- 本机存在 OpenCode CLI，支持 `opencode run --format json`、`--session`、`--dir` 和 `--agent`。
- `nr_test_system` 当前工程包含 Vue/Django/Celery 和 OpenCode 维护能力，但尚未出现需求附件约定的 READY 测试任务发现/结果回填接口。
- 因此 Astra 实现可配置 `NrTestSystemSource` 契约；对端接口未就绪时不伪造“已打通”的结论。

## V0.1 范围

- Task 是核心对象；状态只能由 `TaskStateMachine` 和 `TaskService` 改变。
- 每次状态变化写入 Event；页面从数据库恢复真实状态，SSE 只负责增量刷新。
- `source + external_task_id` 唯一，PostgreSQL 领取使用事务和行锁。
- 一个任务一个 Workspace，一个 Task 保留一个 OpenCode Session；重试使用 `--session` 恢复。
- OpenCode 只负责执行；任务发现、调度、状态判断、Heartbeat 和验证均为确定性程序。
- Verifier 至少检查必需文件、真实命令退出码、有效测试结果和证据文件。
- V0.1 不加入多 Agent、复杂权限、Temporal/LangGraph、模型 API 或工作流设计器。
- CLI 执行中的暂停/终止采用协作式阶段边界：API 立即持久化控制状态，Worker 在当前 OpenCode 调用返回后停止后续验证或重试；恢复时继续原 Workspace 与 Session。跨进程即时杀进程需后续引入可持久化执行句柄。

## 外部契约缺口

默认 Adapter 约定：

- `GET /api/astra/tasks?status=READY` 返回数组或 `{ "items": [...] }`；
- `POST /api/astra/tasks/{external_task_id}/result` 接收 Astra 结果、证据摘要和最终状态；
- Bearer Token 仅从 `ASTRA_NR_TEST_SYSTEM_TOKEN` 环境变量读取。

路径均可由环境变量覆盖。正式联调前需由 `nr_test_system` 确认字段映射、认证和幂等语义。

## 验收证据

- 状态机、任务创建/操作、Scout 去重、Dispatcher 匹配、Workspace 隔离和 Verifier 具备单元/集成测试。
- 后端测试、前端类型检查与生产构建必须通过。
- 浏览器检查四个核心页面，并验证搜索、筛选、导航和任务操作的关键交互。
