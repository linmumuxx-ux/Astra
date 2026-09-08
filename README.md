# Astra V0.4

Astra 是面向长期数字员工的任务分配、工作观察、人工介入和结果管理平台。

平台定义任务目标、分类、优先级、执行员工和验收标准；任务真正如何完成，由数字员工自己的 Agent 决定。当前以 OpenCode Server / Session / Event 作为正式 Runtime，CLI fallback 仅用于隔离测试。

当前版本包含：

- 问题 / 需求两种任务类型和可配置任务分类；
- 自动分配或指定员工；
- 本地或 Linux SSH 远程 Agent 工作环境；
- 每项任务独立执行会话，支持挂起、恢复和异常处理；
- 持续任务工作台、数字办公室和待处理中心；
- 任务结果、逐项验收证据及 Run / Token / Tool 汇总；
- Vue 3 管理台、FastAPI、MySQL、Redis、Celery 与 OpenCode Server。

## 环境要求

- Python 3.11+
- Node.js 20+
- Redis 6+
- 正式环境：MySQL 8.0+
- OpenCode Server 1.18.25 或已验证兼容版本

Astra 不再维护多套 bat / sh / PowerShell 启停脚本。服务生命周期统一由 Python 管理。

## 首次安装

Windows 公司环境：

```powershell
git clone git@github.com:linxuyiyi/Astra.git
cd Astra
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

首次安装会从 `deploy\astra.env.windows.example` 生成根目录 `.env`。完成 MySQL、Redis、OpenCode 和目录配置后，可执行：

```powershell
.\.venv\Scripts\python.exe .\scripts\preflight.py
```

`setup-windows.ps1` 仅负责首次安装；平台启停统一使用 `scripts/astra_service.py`。

## 开发环境

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev
```

默认执行 `start`。常用命令：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev status
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev restart
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev stop
```

开发模式：

- Backend：Uvicorn `--reload`
- Frontend：Vite Dev Server
- 自动执行 Alembic migration 和 preflight
- 启动 Beat、Control Worker、Agent Worker
- 按配置启动员工 OpenCode Server、平台助手 OpenCode Server 和 Library MCP

访问：

- 管理台：`http://localhost:5173`
- API：`http://localhost:8100/api/health`
- API 文档：`http://localhost:8100/docs`

## 正式环境

根目录 `.env` 至少应满足：

```dotenv
ASTRA_ENVIRONMENT=production
ASTRA_DATABASE_BACKEND=mysql
ASTRA_SEED_DEMO=false
ASTRA_EXECUTOR_TYPE=opencode_server
```

启动：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py pro
```

管理：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py pro status
.\.venv\Scripts\python.exe .\scripts\astra_service.py pro restart
.\.venv\Scripts\python.exe .\scripts\astra_service.py pro stop
```

正式模式会在启动前：

1. 校验生产配置；
2. 执行数据库迁移；
3. 执行环境自检；
4. 构建前端生产产物；
5. 启动并检查完整服务链路。

Astra 的 Control Worker、Agent Worker 和 Beat 必须独立运行。长时间 Agent 任务不能与控制任务合并到同一个 `solo` Worker。

日志写入 `ASTRA_LOG_DIR`，服务 PID 和启动模式记录在 `ASTRA_RUNTIME_DIR/astra-service.json`。

## 质量验证

质量门禁同样统一为 Python：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify.py
```

包含：

- Ruff
- 后端全量测试
- 前端类型检查
- 前端生产构建
- 隔离 Chromium E2E

E2E 可单独执行：

```powershell
.\.venv\Scripts\python.exe .\scripts\e2e.py
```

CI 使用相同入口，不再依赖 Shell 脚本。

## Runtime 说明

运行入队会在同一数据库事务中创建 Run、占用 Task / Employee 租约并写入 Outbox。Redis 短暂不可用时任务保持 `QUEUED`，由控制 Worker 重投。

Agent Worker 使用 execution token 和 Run heartbeat 报活。watchdog 发现心跳丢失后先检查 OpenCode Session；仍在 busy 的 Session 不会重复执行，无法恢复时才标记 `LOST` 并等待明确重跑。

平台助手使用独立 OpenCode Server；助手启动失败时降级，不阻断任务核心 Runtime。

## 创建任务示例

```json
{
  "source": "manual",
  "task_type": "ISSUE",
  "category_id": "testing-platform",
  "priority": "VERY_HIGH",
  "completion_policy": "MANUAL_CONFIRM",
  "title": "修复用户登录接口偶发 500 问题",
  "description": "用户登录接口在特定情况下偶发 500，请定位并解决。",
  "acceptance_criteria": [
    { "content": "当前 500 问题解决" },
    { "content": "原有登录能力正常" },
    { "content": "相关检查通过" },
    { "content": "提供修改结果说明" }
  ],
  "employee_id": "astra-01"
}
```

任务中不填写工程路径、Workspace、Skill、Tool、模型、执行命令或验证脚本；这些属于员工 Agent 工作环境。

## 文档

- [操作使用指南](docs/USER_GUIDE.md)
- [部署手册](docs/DEPLOYMENT.md)
- [实现与需求映射](docs/implementation-brief.md)
- [数字办公室](docs/design/DIGITAL_OFFICE.md)
- [持续任务工作台](docs/design/TASK_WORKBENCH.md)
- [平台助手](docs/design/PLATFORM_ASSISTANT.md)
- [原始需求资料](docs/requirements/README.md)
