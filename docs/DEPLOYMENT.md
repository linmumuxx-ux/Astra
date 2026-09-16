# Astra 部署手册

## 1. 部署基线

Astra 使用主机原生进程部署，不维护 Docker Compose、bat/sh 启停脚本或多套平台启动逻辑。

当前基线：

- Python 3.11+
- Node.js 20+
- MySQL 8.0+
- Redis 6+
- OpenCode Server 1.18.25 或已验证兼容版本
- Windows 为主要部署环境
- Linux 远程主机仅作为数字员工工作环境时通过 SSH 接入
- 服务生命周期统一由 `scripts/astra_service.py` 管理

管理台没有内置登录或 RBAC，应部署在可信公司网络或企业认证网关之后。

## 2. 服务组成

`astra_service.py` 统一管理：

- FastAPI Backend
- Vue Frontend
- Celery Beat
- Control Worker
- Agent Worker
- 员工 OpenCode Server
- 平台助手 OpenCode Server
- 数字图书馆 MCP（`streamable-http` 时）

基础设施：

- MySQL：业务数据、任务、Run、配置和审计数据
- Redis：Celery Broker / Result Backend
- 员工 Workspace：员工长期工程目录
- `ASTRA_LOG_DIR`：服务日志
- `ASTRA_RUNTIME_DIR`：服务 PID、Beat schedule 等运行状态

Control Worker、Agent Worker 和 Beat 必须独立运行，不能合并为单个 `solo` Worker。

## 3. 首次安装

Windows：

```powershell
git clone git@github.com:linxuyiyi/Astra.git
cd Astra
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

脚本会：

1. 定位 Python 3.11+
2. 创建根目录 `.venv`
3. 安装 Backend 依赖
4. 执行 `npm ci`
5. 执行一次前端生产构建
6. 首次运行时生成根目录 `.env`

安装脚本只负责环境准备，不负责平台启停。

如果公司 Python 不在 PATH：

```powershell
$env:ASTRA_PYTHON = 'C:\Company\Python311\python.exe'
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

## 4. 正式配置

编辑根目录 `.env`：

```dotenv
ASTRA_ENVIRONMENT=production

ASTRA_DATABASE_BACKEND=mysql
ASTRA_DATABASE_HOST=127.0.0.1
ASTRA_DATABASE_PORT=3306
ASTRA_DATABASE_NAME=astra
ASTRA_DATABASE_USERNAME=astra
ASTRA_DATABASE_PASSWORD=replace-with-a-strong-password
ASTRA_DATABASE_CHARSET=utf8mb4

ASTRA_REDIS_URL=redis://127.0.0.1:6379/0

ASTRA_DATA_DIR=D:\AstraData\data
ASTRA_WORKSPACE_ROOT=D:\AstraData\workspaces
ASTRA_LOG_DIR=D:\AstraData\logs
ASTRA_RUNTIME_DIR=D:\AstraData\run
ASTRA_CONFIG_DIR=configs
ASTRA_SEED_DEMO=false

ASTRA_EXECUTOR_TYPE=opencode_server
ASTRA_OPENCODE_BINARY=opencode
ASTRA_OPENCODE_SERVER_HOSTNAME=127.0.0.1
ASTRA_OPENCODE_SERVER_PORT=4096
ASTRA_OPENCODE_SERVER_USERNAME=opencode

ASTRA_ASSISTANT_ENABLED=true
ASTRA_ASSISTANT_OPENCODE_HOSTNAME=127.0.0.1
ASTRA_ASSISTANT_OPENCODE_PORT=4097
# 平台助手 Workspace 固定为仓库内 nexus-assistant/，无需配置路径。
```

机器相关路径和秘密配置只放 `.env`，不要散落修改源码，也不要提交真实密码、令牌或 SSH 密码。

生产模式强制：

- MySQL
- `ASTRA_SEED_DEMO=false`
- `ASTRA_EXECUTOR_TYPE=opencode_server`

## 5. 数据库准备

首次使用管理员账号创建数据库和最小权限账号：

```sql
CREATE DATABASE astra CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'astra'@'%' IDENTIFIED BY 'replace-with-a-strong-password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP
ON astra.* TO 'astra'@'%';
FLUSH PRIVILEGES;
```

生产建议：

- MySQL 与 Redis 只开放给受控应用网段
- 使用企业秘密系统或受保护 `.env`
- MySQL 字符集固定 `utf8mb4`
- 主机统一校时
- 升级前备份

## 6. 环境自检

可独立执行：

```powershell
.\.venv\Scripts\python.exe .\scripts\preflight.py
```

或：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-windows.ps1
```

自检包含：

- Python 和必要依赖
- MySQL / SQLite 配置
- Alembic 状态
- Redis
- OpenCode 配置和健康状态
- 平台助手工作区
- Workspace / 日志 / Runtime 目录
- MCP 配置

正式启动也会自动执行数据库迁移和同一套 preflight。

## 7. 开发环境

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev
```

开发模式：

- Backend 使用 Uvicorn reload
- Frontend 使用 Vite Dev Server
- Runtime、OpenCode、Assistant、MCP 与正式环境共用同一套启动逻辑

管理：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev status
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev restart
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev stop
```

## 8. 正式环境

启动：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py pro
```

启动顺序：

1. 校验正式环境配置
2. 执行 `alembic upgrade head`
3. 执行 `preflight.py`
4. 执行 `npm run build`
5. 检查 / 启动员工 OpenCode Server
6. 检查 / 启动平台助手 OpenCode Server
7. 启动 Backend
8. 启动 Beat
9. 启动 Control Worker
10. 启动 Agent Worker
11. 按配置启动 Library MCP
12. 启动 Frontend
13. 等待 Backend、Worker 和 Frontend 就绪

管理：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py pro status
.\.venv\Scripts\python.exe .\scripts\astra_service.py pro restart
.\.venv\Scripts\python.exe .\scripts\astra_service.py pro stop
```

状态文件：

```text
ASTRA_RUNTIME_DIR/astra-service.json
```

日志：

```text
ASTRA_LOG_DIR/
├── backend.log
├── runtime-beat.log
├── runtime-control.log
├── runtime-agent.log
├── opencode-server.log
├── assistant-opencode.log
├── library-mcp.log
└── frontend.log
```

## 9. 服务地址

默认：

- 管理台：`http://localhost:5173`
- Backend：`http://localhost:8100/api/health`
- API 文档：`http://localhost:8100/docs`
- 平台助手：`http://localhost:8100/api/assistant/health`
- Library MCP：`http://127.0.0.1:8201/mcp`

OpenCode Server 默认只监听 loopback。

## 10. Linux 远程数字员工

Astra 平台本身不再维护 Linux Shell 启停入口，但仍可从 Windows 主机通过 Paramiko 管理 Linux 远程员工。

远程员工需要：

- SSH Host / Port / Username / Password
- 可写绝对 Workspace
- OpenCode 可执行路径
- 独立或可复用的 OpenCode Server Port

Astra 会通过 SSH 检查远程 `127.0.0.1:<OpenCode Port>`。未运行时直接启动 OpenCode Server，并通过本机 SSH Tunnel 访问，不需要在远端防火墙开放 OpenCode Server 端口。

不再提供 Linux Agent Shell wrapper 模板。需要额外环境变量时，在目标主机自行配置 OpenCode 运行环境或使用平台认可的机器级启动方式。

## 11. 数字图书馆 MCP

`ASTRA_MCP_TRANSPORT=streamable-http` 时，`astra_service.py` 会启动 Library MCP。

默认：

```text
http://127.0.0.1:8201/mcp
```

非 loopback 监听必须配置 `ASTRA_MCP_API_KEY`。

本地不需要共享 HTTP 服务时可保持：

```dotenv
ASTRA_MCP_TRANSPORT=stdio
```

此时不启动独立 MCP 服务。

## 12. 质量验证

完整验证：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify.py
```

包含：

1. Ruff
2. Backend pytest
3. Frontend type-check
4. Frontend production build
5. Chromium E2E

单独运行 E2E：

```powershell
.\.venv\Scripts\python.exe .\scripts\e2e.py
```

CI 同样调用 `python scripts/verify.py`，不依赖 Bash。

## 13. 升级

推荐顺序：

1. `astra_service.py pro stop`
2. 备份 MySQL 和重要 Workspace
3. 切换到已验收 commit
4. 更新 Backend 依赖
5. `npm ci`
6. `astra_service.py pro`

正式启动会自动完成 migration、preflight 和 frontend build。

不要通过兼容代码长期容忍错误历史数据。需要修正历史数据库数据时，优先使用一次性迁移或数据修复脚本。

## 14. 备份

至少备份：

- MySQL
- `ASTRA_WORKSPACE_ROOT/records`
- 员工 Workspace 或对应 Git 仓库
- 受保护的 `.env`
- 必要业务配置

停止 Astra 不会删除 MySQL、Redis、工作记录或员工 Workspace。

## 15. 常见问题

### 任务一直待领取

检查：

- `astra_service.py <mode> status`
- `runtime-beat.log`
- `runtime-control.log`
- `runtime-agent.log`
- 员工启用状态
- 员工环境状态
- 任务类型和分类工作范围

### OpenCode 启动失败

检查：

- `ASTRA_OPENCODE_BINARY`
- OpenCode 版本
- `opencode-server.log`
- 4096 / 4097 端口占用
- Workspace 权限

### 正式模式拒绝启动

正式模式主动拒绝：

- SQLite
- 非 `opencode_server` Runtime
- preflight 失败
- 数据库迁移失败
- 前端构建失败

这些问题应修正配置或数据后再启动，不通过兼容分支绕过。

## 数字图书馆接入 llm_wiki

Astra 管理原始知识，原版 llm_wiki 管理派生 Wiki 和索引；Agent 统一使用 Astra Library MCP。
同机 Linux ARM64 部署时，按 llm_wiki 官方方式安装并运行完整桌面应用，保持指定项目打开；
仅启动 HTTP 监听并不能代替桌面应用中的知识加工流程。本次不修改 llm_wiki 源码。

在 Astra `.env` 配置（Token 仅从环境读取，不入库）：

```dotenv
ASTRA_LLM_WIKI_ENABLED=true
ASTRA_LLM_WIKI_API_BASE_URL=http://127.0.0.1:19828/api/v1
ASTRA_LLM_WIKI_API_TOKEN=<本地 API Token>
ASTRA_LLM_WIKI_PROJECT_ID=<固定项目 UUID>
ASTRA_LLM_WIKI_PROJECT_PATH=/srv/llm-wiki/astra-wiki
ASTRA_LLM_WIKI_TIMEOUT=10
```

使用专属项目，启用 Source Watch 和自动 Ingest，确保 Markdown 在允许的扩展名中，
并配置可用的 LLM。需要向量/Hybrid 检索时，还须在 llm_wiki 中配置并启用 Embedding；
未启用时，原版同一个搜索 API 可以返回 `mode=keyword`，这不是 Astra 的回退搜索。
Astra 会验证项目 UUID、API 返回路径及当前打开项目的一致性，拒绝向不匹配的目录写入。

部署代码后执行 `python -m alembic upgrade head`（在 `backend/` 的虚拟环境中），
重启 Astra API、Library MCP、Celery control worker 和 beat。
迁移会将现有 published 知识加入待同步；已有使用记录一次性迁移为资源级历史记录，
`astra:<knowledge_id>` 表示历史原始知识，不假装成可读取的 Wiki 路径。
保留原有可选来源字段供管理端审计使用，MCP 查询和反馈不再依赖 employee/task/run。

Celery 每 5 秒取最多 100 条待同步任务，将当前可供 Library viewer 访问的 published 知识
原子写入 `<PROJECT_PATH>/raw/sources/astra/<knowledge_id>.md`，随后调用一次 rescan。
目录、标签、正文和发布状态变化都会入队；删除记录保留清理任务。
同机 OS 文件锁防止重复 worker 并发写入，任务被中断后仍可重试；新版本请求不会被旧任务完成覆盖。
数据库提交与外部 HTTP 不构成分布式事务。失败显示在数字图书馆的“知识服务状态”，
点击“重新同步”会重新排队当前正式知识和保留的清理记录，由 worker 执行。
运行 worker 的账户需要项目源文件目录和 Astra runtime 目录的读写权限。

### 已知限制（本阶段接受）

- `synced` / 最近同步时间表示源文件操作完成且 rescan 接受，**不表示 Wiki、Vector 或 Graph 加工完成**。
- 原版删除来源时，共享 Wiki 页面可能只移除来源标记、保留正文；无可解析来源的页面可能跳过。
  因此归档、删除或收紧访问范围后，旧内容仍可能被检索。上游依据：
  [source-lifecycle.ts](https://github.com/nashsu/llm_wiki/blob/main/src/lib/source-lifecycle.ts)、
  [project-file-sync.ts](https://github.com/nashsu/llm_wiki/blob/main/src/lib/project-file-sync.ts)。
- `library_related` 明确返回 `unsupported`，不在 Astra 自建相关度算法。
- Wiki 与原始知识可能多对多；读取次数按 Wiki `resource_id` 统计，不将一次 Wiki 读取猜测分摊到原始知识。
- HTTP 服务在线不代表 LLM/Embedding 可用。加工失败需在原版 llm_wiki 检查；Astra 不复制其加工管理 UI。

### 本地端到端验收

```bash
backend/.venv/bin/python scripts/e2e_library.py
```

此命令使用临时 Astra 数据库，通过真实 HTTP 管理端接口、MCP stdio 子进程和 Celery 任务入口，
在当前配置的真实 llm_wiki 项目中创建一条带唯一标记的测试来源，验证发布、检索、读取、反馈、
更新和归档。结束时删除该测试源文件；共享派生页面清理遵循上面的已知限制。
默认等待每次加工最多 300 秒，可用 `ASTRA_LIBRARY_E2E_WAIT` 调整。
成功结果写入 `.astra/library-e2e-result.json`，记录真实搜索模式及归档后剩余命中数。
普通 backend 测试使用 MockTransport，不依赖或改动本地知识服务。
