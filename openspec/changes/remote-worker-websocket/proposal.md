## Why

远程执行现在把 Paramiko SSH、本地端口转发和反向隧道同时当成部署通道和业务通道。云执行机因此要对外暴露 OpenCode，隧道散落在 API 与 Celery 两个进程里，断线会连带影响 Gateway、MCP、Workspace 和 Session 事件，网络故障也容易被看成 OpenCode 进程故障。

## What Changes

- 新增 Worker Gateway 与 Worker Agent。Worker 主动连接主控；WebSocket 负责控制与事件，HTTP 负责服务调用和大文件，SSH 只保留初次安装和故障维护。
- 一台 Worker 同时只有一个连接纪元。指令先写入数据库，再经共享路由交给持有套接字的进程。旧连接的迟到响应不能覆盖新状态。
- 阶段 1 只建立这条通道。任务执行、Workspace、Gateway/MCP 仍走现有 SSH，调用方在后续阶段切换后再移除业务转发。
- 不改 `fix-session-task-state`（`dfc5eab`）的 Task/Session 投影语义，不新增第二套状态机，不改 AgentScope 和 LLM Wiki。

## Capabilities

### New Capabilities

- `worker-channel`：Worker 实例、连接认证、epoch、指令持久化和跨进程路由。

### Modified Capabilities

- 无。不修改 `openspec/specs/` 中的历史契约。

## Impact

- 新增 `app/worker_gateway`、`app/worker_agent`、表 `worker_instances` / `worker_connections` / `worker_commands` 和迁移 `0039_worker_gateway`。
- 阶段 2 起才会改 `session_connection.py`、`opencode_remote_server.py`、`recovery.py` 的传输方式。`lifecycle.py` 只适配连接，不改投影。
- 阶段 3 改 `workspace_files.py`、`workspace_changes.py`、`workspace_routes.py` 的远程文件与 Git。
- 阶段 4 改 `remote_provisioning.py`：安装 Worker Agent 与 OpenCode 配置，删除执行期反向隧道和 `ssh` 执行路径。SSH 只留安装和故障维护。
- 数字员工别名 `/api/workers` 保持不变。新通道使用 `/api/worker-gateway`。
