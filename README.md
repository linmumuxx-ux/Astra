# Astra 1.0 重建分支

当前分支 `rewrite/astra-1.0` 使用独立新代码、schema 与 `/api/v1`。1.0 产品范围见 [瘦身基线](docs/astra-1.0/SLIM_BASELINE.md)。开发入口、实现现状和验证证据见 [部署说明](docs/astra-1.0/deployment.md)、[架构现状](docs/astra-1.0/architecture.md) 与 [验证报告](docs/astra-1.0/verification.md)。垂直切片尚未作为一条真实链关闭，不能标记 1.0 完成。公司全量切换属于该基线中的 post-1.0。

下文保留为原始实现的复制与迁移参考，不作为 1.0 的运行入口。

## 原始 Astra V0.6 参考

Astra 是面向长期数字员工的任务分配、工作观察、人工介入和结果管理平台。

平台定义任务目标、分类、优先级、执行员工和验收标准；任务真正如何完成，由数字员工自己的 Agent 决定。当前以 OpenCode Server / Session / Event 作为正式 Runtime，CLI fallback 仅用于隔离测试。

当前版本包含：

- 问题 / 需求两种任务类型和可配置任务分类；
- 自动分配或指定员工；
- 本地或 Linux SSH 远程 Agent 工作环境；
- 每项任务独立执行会话，支持挂起、恢复和异常处理；
- 持续任务工作台、数字办公室和待处理中心；
- 任务结果、Task Summary 及 Session / Token / Tool 汇总；
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

`workspace-ui` 的公司 Windows 环境优先使用 pnpm 安装和构建；未安装 pnpm 时可通过 Corepack，其他环境仍可回退 bun。统一入口为 `node scripts/workspace_ui.mjs <install|build|type-check>`。

仓库已提交 `workspace-ui` 的生产构建产物（`frontend/public/opencode-workspace`）。未安装 workspace-ui 依赖时，`npm run build` 会直接复用该产物，因此公司环境无需联网安装 workspace-ui 依赖即可构建和运行工作台。只有修改 `workspace-ui` 源码时才需要先 `node scripts/workspace_ui.mjs install` 再重新构建。

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

- Backend：Linux/Mac 开发模式使用 Uvicorn `--reload`；Windows 为保证 asyncio 子进程稳定，使用普通 Uvicorn，代码变更后执行 `dev restart`
- Frontend：Vite Dev Server
- 自动执行 Alembic migration 和 preflight
- 启动 Beat、Control Worker、Agent Worker
- 按配置启动员工 OpenCode Server、平台助手 OpenCode Server 和 Library MCP

访问：

- 管理台：`http://localhost:5173`
- API：`http://localhost:8100/api/health`
- API 文档：`http://localhost:8100/docs`

## 旧版本数据库升级

从旧 Run 架构升级且需要保留历史数据时，先做一次原始归档，再执行迁移：

```powershell
.\.venv\Scripts\python.exe .\scripts\archive_legacy_history.py
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
```

迁移会把可可靠映射的历史 Run 状态、时间、模型、Token/Tool 用量、Task 结果、Evidence 元数据和知识来源关系回填到 `RuntimeSession` / `TaskSummary`；原始归档用于审计，不作为运行时兼容层。新安装无需执行归档。

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

Task 是业务闭环边界，OpenCode Session 是执行事实源，`RuntimeSession` 只保存 Session 绑定、终态和用量索引，不复制消息或执行日志。人工确认完成后，后台自动复盘并更新该任务唯一的 `TaskSummary`，任务结束不等待复盘；重新执行会创建新的 OpenCode Session。

数字员工只负责执行、查询和反馈知识；后台复盘统一提炼经验，允许零条，通常不超过两条。相似经验优先合并候选或补充正式知识的证据，执行成功不等于经验已验证。候选须经人工审核后发布。任务详情的“总结与经验”可查看总结、复盘状态、关联经验，并重试失败或超时的复盘。自动复盘依赖已启用的平台助手、Celery Beat 和 Control Worker。

本地数字员工的 OpenCode Server 采用按需启动：空闲时 Server 未运行属于正常状态；任务启动、重连、停止和历史 Session 读取时会按需检查并启动对应员工 Serve。网络或 Runtime 不可达不会被直接等同于任务失败。

数据库事务只用于短状态更新。OpenCode、SSH、文件和网络 I/O 不应在持有 Task/Employee 行锁期间执行。生产环境建议 Astra 使用独立 MySQL Database，避免其他业务长事务阻塞 Astra 写操作。

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

Linux 远程员工的安装、模型中转和数字图书馆接入见 [远程员工部署](docs/REMOTE_EMPLOYEES.md)。
