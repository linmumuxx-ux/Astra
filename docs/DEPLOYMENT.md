# Astra V0.4 部署手册

## 1. 本轮部署基线

Astra 使用主机原生进程部署，不包含容器部署配置。当前基线为：

- Python 3.11+；Python 3.8 不在支持范围；
- Node.js 20+；
- MySQL 8.0+，字符集固定为 `utf8mb4`；
- Redis 6+；
- OpenCode Server 1.18.25 或已验证的兼容版本；
- Windows 本地执行和 Linux SSH 远程执行；
- Windows PowerShell 快速安装、自检、启动和停止；
- Linux 继续支持 systemd、Nginx 和远程 Agent 主机。

管理台没有内置登录或 RBAC，必须放在可信公司网络或企业认证网关之后。

## 2. 组件与数据目录

- FastAPI：REST API、SSE、员工环境检查；
- Celery Worker + Beat：任务发现、分配、心跳、恢复扫描和 Agent 执行；
- OpenCode Server：Session、Message、Event SSE、Child Session、Question 和 Abort；
- 平台助手 OpenCode Server：独立的 4097 端口与 `nexus-assistant` 非代码工作区；
- MySQL：分类、员工、环境、任务、Run、Token、Tool、事件和结果元数据；
- Redis：Celery Broker 和 Result Backend；
- Vue 管理台：Windows 快速部署使用已构建产物的本地预览服务，Linux 正式部署由 Nginx 托管；
- 数字图书馆 MCP：独立进程但复用 Backend 的 Knowledge Service 与数据库，支持 stdio 或 Streamable HTTP；
- 员工 Workspace：员工长期使用的真实工程目录；
- `ASTRA_WORKSPACE_ROOT/records`：Astra 保存的 Agent 观察记录，不是源码工作区；
- `ASTRA_LOG_DIR`：Backend、运行时和前端日志；
- `ASTRA_RUNTIME_DIR`：PID、Celery Beat schedule 等运行状态。

机器相关路径统一放在根目录 `.env`，不要散落修改 Python 或前端源码。

## 3. Windows 快速部署

### 3.1 前置条件

- 64 位 Windows 10/11 或 Windows Server；
- Python 3.11+；可使用 `py.exe -3.11`、`python.exe`，或把完整路径写入 `ASTRA_PYTHON`；
- Node.js 20+，并能找到 `npm.cmd`；
- Git；
- 可访问的 MySQL 8.0+ 与 Redis；
- 本地员工需要的 Agent 已加入 PATH，或可配置完整 `.exe` / `.cmd` 路径；
- Linux 远程员工需要可访问的 SSH 地址、账号和密码；连接由 Python Paramiko 完成，不依赖 `ssh.exe` 或 `sshpass`。

路径可以包含盘符、空格和中文，例如 `D:\研发项目\Astra` 与 `D:\code\nr_test_system`。

### 3.2 安装

在 PowerShell 中执行：

```powershell
git clone git@github.com:linxuyiyi/Astra.git
cd Astra
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

脚本会：

1. 定位并输出实际 Python 版本；
2. 创建根目录 `.venv`；
3. 安装后端依赖和 MySQL 异步驱动；
4. 执行 `npm ci` 和前端生产构建；
5. 首次运行时从 `deploy\astra.env.windows.example` 生成根目录 `.env`。

如果公司 Python 不在 PATH：

```powershell
$env:ASTRA_PYTHON = 'C:\Company\Python311\python.exe'
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

### 3.3 配置

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
ASTRA_CONFIG_DIR=D:\Astra\configs
ASTRA_SEED_DEMO=false

ASTRA_OPENCODE_BINARY=C:\Program Files\OpenCode\opencode.exe
ASTRA_EXECUTOR_TYPE=opencode_server
ASTRA_OPENCODE_SERVER_HOSTNAME=127.0.0.1
ASTRA_OPENCODE_SERVER_PORT=4096
ASTRA_OPENCODE_SERVER_USERNAME=opencode
# 只绑定 loopback 时可留空；非 loopback 必须配置
# ASTRA_OPENCODE_SERVER_PASSWORD=replace-with-a-strong-password

ASTRA_ASSISTANT_ENABLED=true
ASTRA_ASSISTANT_OPENCODE_HOSTNAME=127.0.0.1
ASTRA_ASSISTANT_OPENCODE_PORT=4097
ASTRA_ASSISTANT_WORKSPACE_DIR=nexus-assistant
# 只绑定 loopback 时可留空；非 loopback 必须配置
# ASTRA_ASSISTANT_OPENCODE_PASSWORD=replace-with-a-strong-password
```

后端与 Celery 无论从项目根目录还是 `backend` 启动，都会读取这一个根目录 `.env`，不要再复制一份 `backend/.env`。不要提交真实数据库密码、任务源令牌或员工 SSH 密码。

### 3.4 自检、启动与停止

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1
```

访问：

- 管理台：`http://localhost:5173`
- API：`http://localhost:8100/api/health`
- API 文档：`http://localhost:8100/docs`
- 平台助手健康状态：`http://localhost:8100/api/assistant/health`
- 数字图书馆 MCP（启用 Streamable HTTP 时）：`http://127.0.0.1:8201/mcp`

查看进程状态或停止：

```powershell
.\.venv\Scripts\python.exe .\scripts\process_manager.py status
powershell -ExecutionPolicy Bypass -File .\scripts\stop-windows.ps1
```

日志位于 `ASTRA_LOG_DIR`。PID 记录位于 `ASTRA_RUNTIME_DIR\processes.json`。启动器先启动数字员工与平台助手各自的 OpenCode Server 并等待 `/global/health`，再启动 Backend、Celery 和 Frontend；助手启动失败时核心任务功能仍可启动，界面会显示助手降级状态。停止时使用 Windows 进程组与 `taskkill /T` 回收整棵进程树。

Windows Worker 固定使用 `solo` 池并监听 Celery 默认队列。不要额外添加 `-Q astra`；当前任务没有路由到该自定义队列。运行时复用同一 Proactor 事件循环，以保证 asyncmy 连接池与 OpenCode HTTP/SSE 客户端在连续任务中稳定工作。

## 4. 环境自检

Windows 使用 `scripts\check-windows.ps1`，其他环境可直接运行：

```bash
.venv/bin/python scripts/preflight.py
```

自检项目：

- 当前操作系统；
- Python 版本和必要依赖；
- MySQL 连接、服务版本、连接字符集；
- Alembic 当前版本和必要数据表；
- Redis 连接；
- 默认 Agent 是否可执行；
- OpenCode Server 配置，以及已运行实例的健康状态；
- 平台助手工作区、MCP 入口与独立 OpenCode Server 状态；
- Workspace、日志目录和运行目录是否存在且可写。

失败输出固定包含“检查项、当前值、失败原因、建议处理方式”，正常环境问题不会只显示 Python traceback。启动脚本会先迁移数据库，再执行同一自检；任一项失败时不启动平台。

## 5. MySQL 准备

使用管理员账号一次性创建数据库和最小权限账号：

```sql
CREATE DATABASE astra CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'astra'@'%' IDENTIFIED BY 'replace-with-a-strong-password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP
ON astra.* TO 'astra'@'%';
FLUSH PRIVILEGES;
```

生产建议：

- MySQL 与 Redis 只开放给受控应用网段；
- 账号密码由企业秘密系统或受保护的 `.env` 注入；
- 连接字符集必须是 `utf8mb4`；
- MySQL、应用主机和远程主机统一校时；Astra 以 UTC 写入时间字段；
- 升级前备份，升级后运行自检确认 revision 与表结构。

`ASTRA_DATABASE_URL` 仍可作为兼容覆盖项，但正式配置优先使用 Host、Port、Database、Username、Password、Charset 六项，便于换机维护。SQLite 只用于本地开发和隔离测试。

## 6. 数据库迁移

Windows 启动脚本会自动执行：

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
Pop-Location
```

Linux：

```bash
cd /opt/astra/backend
/opt/astra/.venv/bin/alembic current
/opt/astra/.venv/bin/alembic upgrade head
/opt/astra/.venv/bin/alembic current
```

当前应到达 `0013_assistant (head)`。不要对结构来源不明的数据库直接执行 `alembic stamp`。
如果旧的本地启动方式已在 0012 数据库中预建完整的助手表，0013 会校验表、列、索引和唯一约束后安全接管并保留数据；结构不完整或不一致时会拒绝升级并给出具体差异。

## 7. 员工 Agent 工作环境

### 7.1 Windows 本地

配置中心的每名员工配置 Workspace 和模型；正式 Runtime 共享由 `ASTRA_OPENCODE_BINARY` 启动的 OpenCode Server：

- 模式：本地；
- Agent 可执行文件：PATH 命令名或完整路径；
- Agent 模型：例如 `deepseek/deepseek-v4-flash`；
- 员工 Workspace：例如 `D:\code\nr_test_system`。

路径中有空格时直接填写完整路径，不要自行添加 Shell 引号。Astra 不拼接 Shell 字符串；`.exe` 使用参数数组直接启动，`.cmd` / `.bat` 通过 `COMSPEC` 显式适配。每名同时工作的员工仍必须使用独立 Workspace；Server Event 会再按主 Session 和 Child Session ID 隔离。

每名同时工作的员工必须有独立可写 Workspace。该目录应包含员工所需的代码、Agent 配置、Skills 与 Tools。

### 7.2 Linux SSH 远程

Linux 远程与本地使用同一套 Session / Event Runtime，Run 记录为 `opencode_server_ssh`。目标主机需要：

- 可访问的 Host、Port、最小权限 Username 与 SSH 密码；
- OpenCode 1.18.25 或已验证兼容版本，以及可执行路径；
- 员工专属的绝对 Workspace。

Astra 先连接 SSH，再检查远程 `127.0.0.1:<OpenCode Server Port>`。未运行时，它会在员工 Workspace 下以 `nohup opencode serve --hostname 127.0.0.1 --port <port>` 启动 Server，并将日志和 PID 放在远程 `/tmp/astra-opencode-server-<uid>-<port>/`。Backend/Celery 只连接本机临时 SSH 隧道；不要在远程防火墙开放该 Server Port，也不要把 Server 改成 `0.0.0.0`。Session、SSE、Main/Child Tool、Question/Reply、连续多轮与 Abort 都走隧道内的真实 Server API。

配置中心需要填写 SSH Port 和 OpenCode Server Port；后者默认 4096。同一 Linux 主机若由不同账号运行不同 OpenCode/provider 配置，应给每个账号分配不同 Server Port，避免连接到另一账号已经监听的进程。同一账号、同一配置可以共享一个 Server，Astra 仍按 Workspace、主 Session 和 Child Session ID 隔离并发任务。

Astra 使用 Paramiko 在线密码认证，明确禁用本机 SSH Agent 和密钥自动查找，因此 Windows 不需要安装 `ssh.exe` / `sshpass`。SSH 密码以明文保存在 Astra 数据库中，只应部署在受控公司内网并严格限制数据库访问；API 只返回 `has_ssh_password`，不会回显密码，密码也不会进入 Task/Run 环境快照、事件或证据文件。配置中心密码框留空表示保持原值。OpenCode Server Port 会进入 Task/Run 不可变环境快照，以便 Resume 和 Abort 回到原 Server。

只有全局明确设置 `ASTRA_EXECUTOR_TYPE=opencode_cli_fallback` 时，远程 Run 才退回隔离的 `opencode_cli_fallback_ssh`；正式模式不会同时维护两套事件解释逻辑。

若 Agent 依赖额外环境变量或需要跳过工作区信任交互，可复制并修改仓库模板：

- Windows 本地：`deploy/start-agent.windows.bat.example`；
- Linux 远程：`deploy/start-agent.linux.sh.example`。

模板包含 `OPENCODE_SKIP_SAFE_CHECK=1`、`USE_OSC_FILTER=false` 和 `--disable-update`，并会把 `serve` 参数继续传给真实可执行文件；`opencode_path` 指向修改后的启动器。模板中的路径都是占位符，禁止把真实凭据写入仓库。

## 8. Linux 原生部署

Windows 是公司快速部署入口；需要 Linux 服务守护时，保留现有 systemd 与 Nginx 配置：

```bash
sudo git clone git@github.com:linxuyiyi/Astra.git /opt/astra
sudo chown -R astra:astra /opt/astra
cd /opt/astra
sudo -u astra python3 -m venv .venv
sudo -u astra .venv/bin/pip install -e backend
sudo -u astra npm --prefix frontend ci
sudo -u astra npm --prefix frontend run build

sudo install -d -m 0750 -o root -g astra /etc/astra
sudo cp deploy/astra.env.example /etc/astra/astra.env
sudo editor /etc/astra/astra.env

sudo cp deploy/systemd/astra-backend.service /etc/systemd/system/
sudo cp deploy/systemd/astra-opencode.service /etc/systemd/system/
sudo cp deploy/systemd/astra-assistant-opencode.service /etc/systemd/system/
sudo cp deploy/systemd/astra-runtime.service /etc/systemd/system/
sudo cp deploy/systemd/astra-agent.service /etc/systemd/system/
sudo cp deploy/systemd/astra-beat.service /etc/systemd/system/
sudo cp deploy/systemd/astra-library-mcp.service /etc/systemd/system/
sudo cp deploy/nginx-astra.conf /etc/nginx/conf.d/astra.conf
sudo systemctl daemon-reload
sudo systemctl enable --now astra-backend astra-opencode astra-assistant-opencode astra-runtime astra-agent astra-beat astra-library-mcp
sudo nginx -t
sudo systemctl reload nginx
```

如果安装目录不是 `/opt/astra`，先修改 unit、Nginx 和环境文件中的路径。

Beat 和控制 Worker 必须与 Agent Worker 同时受守护。前两者负责 Outbox 投递、Run watchdog 与状态对账；Agent Worker 只执行 `agent` 队列中的长任务。不要把三者合并成单个 `solo` Worker，否则长时间 Agent 会阻塞投递和恢复检查。可在受保护的环境文件中调整：

```dotenv
ASTRA_OUTBOX_INTERVAL=2
ASTRA_OUTBOX_RETRY_SECONDS=5
ASTRA_RUNTIME_STARTUP_TIMEOUT=120
ASTRA_RUNTIME_HEARTBEAT_TIMEOUT=90
```

`STARTING` 超时会转为 `LOST`。`RUNNING` 心跳丢失后会先查询 OpenCode Session：Session 仍 busy 时保留现场且不重放 Prompt，idle 时尝试收集最终结果，Session 缺失或无结果时标记 `LOST`。有副作用的任务只能通过明确的“重新执行”创建新 Run，不会由 watchdog 自动重跑。

数字图书馆 MCP 默认监听 loopback `127.0.0.1:8201/mcp`。生产环境必须通过受控网关或内网代理访问，并在受保护的环境文件中配置 `ASTRA_MCP_API_KEY`；非 loopback 监听但未配置该令牌时服务会拒绝启动。每次 Tool 调用还必须携带真实 `employee_id`，并按需携带 `task_id`、`run_id`，服务端会验证三者关联并写入使用审计。无需共享 HTTP 服务的本地 MCP Host 可保持 `ASTRA_MCP_TRANSPORT=stdio`，直接运行：

```bash
cd /opt/astra/backend
/opt/astra/.venv/bin/python -m app.mcp_server
```

## 9. 首次业务配置

1. 打开“配置中心 → 任务分类”，确认正式分类；
2. 创建或更新员工基本信息与工作范围；
3. 配置每名员工的 Agent、模型和真实工程 Workspace；
4. 保存并点击“测试连接”，确认环境状态为“正常”；
5. 按需开启自动领取与自主执行；
6. 配置外部任务源后再启用正式 Task Scout；
7. 创建一项低风险测试任务，观察领取、Run、结果和验收证据。

任务中不传工程路径、模型、执行命令或验证脚本；这些属于员工工作环境。

## 10. 验证

Linux/macOS 构建机执行完整质量门禁：

```bash
./scripts/verify.sh
```

门禁包含 Ruff、后端全量测试、前端类型检查、生产构建和 13 项默认执行的隔离 Chromium E2E；另有 1 项真实平台助手 E2E 需显式启用。E2E 会真实启动 Redis、Celery Worker/Beat、Backend、Frontend 和可控 Agent，覆盖平台助手降级、数字图书馆安全 Markdown、配置保存、自动领取、员工模型以及“询问—等待回复—继续原会话—验收完成”。

在允许访问真实模型的员工主机，可执行真实 OpenCode 冒烟验证：

```bash
.venv/bin/python scripts/real_opencode_smoke.py \
  --model opencode/glm-5.1 \
  --opencode /absolute/path/to/opencode
```

该命令会在隔离目录启动真实 `opencode serve`，通过 Astra Coordinator 完成一项包含 Tool 的任务，并校验 Session ID、Event 用量和产物。它会调用真实模型并消耗 Token，不要把凭据放进命令、日志或仓库。

## 11. 备份、升级与停止

MySQL 备份示例：

```bash
mysqldump --single-transaction --routines --triggers \
  -h mysql.company.internal -u astra -p astra > astra-backup.sql
```

同时备份：

- `ASTRA_WORKSPACE_ROOT/records`；
- 员工 Workspace 或对应 Git 仓库；
- 非秘密平台配置；
- 受保护的部署配置与数据库备份（数据库包含员工 SSH 密码，必须按秘密数据管理）。

升级顺序：停止运行时与后端、备份、切换到已验收 commit、安装依赖、构建前端、执行迁移和自检、再启动。停止 Astra 不会删除 MySQL 数据、Redis、观察记录或员工 Workspace。

## 12. 排查

### 任务一直待领取

先检查运行时进程和日志，再确认员工已启用、空闲、允许自动领取，环境为“正常”，且任务类型与分类在员工工作范围中。

### 本地环境异常

以实际运行 Astra 的 Windows 账号执行配置的 Agent 加 `--version`，再检查 Workspace 是否存在且可写。完整路径不需要手工转义。

### Linux 远程异常

在配置中心重新输入密码并执行“测试连接”，检查 DNS、SSH Host/Port、账号密码、远程 Workspace、Agent 启动器权限和 OpenCode Server Port。测试会依次验证 SSH、Workspace、`opencode --version`、Server 启动以及经 SSH 隧道访问 `/global/health`。错误密码不会由 API 回显；Server 启动失败时到远程 `/tmp/astra-opencode-server-<uid>-<port>/server.log` 查看原因。

### 验收项显示“无法确认”

表示员工最终回复没有返回可识别的逐项结论，不等于执行失败或“未满足”。Astra 优先解析 `ASTRA_RESULT_JSON`，并兼容清晰的 Markdown 验收表；两者都无法确认时保留“无法确认”，供人工结合证据判断。

## 13. 仍存在的环境限制

- Python 3.8 已从本轮范围移除，当前要求 Python 3.11+；
- Celery 上游不承诺 Windows 支持。Windows 启动器固定使用 `solo` 池并完成跨平台进程管理，但公司正式镜像仍必须做持续运行验收；严格 SLA 可把调度运行时部署在 Linux；
- Windows 快速启动器使用 Vite Preview 提供已构建前端，适合可信公司内网快速部署；面向大量用户或高可用要求时，应使用企业 Web Server 或反向代理托管 `frontend\dist`；
- Redis 的 Windows 安装和守护方式由公司基础设施提供，Astra 只通过 `ASTRA_REDIS_URL` 连接；
- 当前本地与 Linux 远程 Agent 适配器实现为 OpenCode Server；接口和页面已使用中性 Agent 表述，但 Claude Code、Codex 等适配器尚未实现；
- Linux 远程目标必须支持密码 SSH、非交互 Agent 启动和可写 Workspace；当前密码明文保存在数据库，必须依靠可信内网、数据库权限和备份加密保护；
- 管理台整体仍依赖企业认证网关；数字图书馆 Web API 从可信网关头读取用户与角色，MCP Streamable HTTP 支持受保护环境变量提供的 Bearer Token，但平台尚未内置统一登录与秘密管理；
- 迁移已通过 SQLite 实际升级与 MySQL 方言离线编译，本地没有公司 MySQL 实例，因此正式 MySQL 连接、权限和版本仍需在公司环境运行自检确认。
