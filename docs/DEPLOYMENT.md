# Astra V0.4 部署手册

## 1. 部署拓扑

推荐使用 Docker Compose：

- `astra-frontend`：Nginx 托管 Vue 管理台并代理 `/api/`；
- `astra-backend`：FastAPI、REST API、SSE、员工环境检查和数据库迁移；
- `astra-worker`：Celery Worker + Beat，运行任务发现、任务分配、心跳与 OpenCode；
- `postgres`：分类、员工、环境、任务、Run、Token、Tool、事件和结果元数据；
- `redis`：Celery Broker 与 Result Backend。

员工工作空间是长期工程目录，必须由运维提前准备并挂载给 Worker。Astra 自己的 `/workspaces/records` 只用于保存 OpenCode 观察记录，不是任务源码工作区。

## 2. 前置条件

- Linux x86_64 或 arm64，建议从 4 核 CPU、8 GB 内存、30 GB 磁盘起步；
- Docker Engine 24+ 与 Docker Compose v2；
- PostgreSQL 16、Redis 7，或 Compose 中对应服务；
- 可访问任务源、代码仓库、模型服务和员工需要的外部系统；
- 本地模式需要 Worker 容器内可用的 Linux OpenCode CLI；
- 远程模式需要目标机 SSH、OpenCode 和员工专属可写工作空间；
- TLS 域名和企业认证网关。

管理台没有内置登录/RBAC，不得直接暴露到公网。

## 3. 获取代码与环境变量

```bash
git clone git@github.com:linxuyiyi/Astra.git
cd Astra
cp deploy/docker.env.example .env
```

生产环境必须固定 tag 或 commit，并设置：

```bash
ASTRA_SEED_DEMO=false
```

关键变量：

| 变量 | 用途 | 生产建议 |
| --- | --- | --- |
| `ASTRA_DATABASE_URL` | 异步 SQLAlchemy 数据库地址 | 使用 PostgreSQL，凭据由秘密系统注入 |
| `ASTRA_POSTGRES_PASSWORD` | Compose PostgreSQL 密码 | 使用强随机值 |
| `ASTRA_REDIS_URL` | Celery Broker / Backend | 使用受控 Redis |
| `ASTRA_SEED_DEMO` | 演示数据开关 | 必须为 `false` |
| `ASTRA_WORKSPACE_ROOT` | Astra 观察记录目录 | 使用持久卷，不作为员工源码目录 |
| `ASTRA_OPENCODE_MODEL` | 可选的全局模型覆盖 | 留空时使用员工工作空间中的 OpenCode 配置 |
| `ASTRA_OPENCODE_AGENT` | 可选的兼容性 Agent 覆盖 | 建议留空，由 OpenCode 自主选择 |
| `ASTRA_INACTIVITY_TIMEOUT` | 无可观察活动多久后提示 | 默认 `900` 秒；只提示，不改任务状态 |
| `ASTRA_RECOVERY_INTERVAL` | 恢复和活跃度扫描间隔 | 默认 `30` 秒 |
| `ASTRA_SSH_BINARY` | Linux 远程 SSH 客户端 | 默认 `ssh` |
| `ASTRA_NR_TEST_SYSTEM_ENDPOINT` | 外部任务源地址 | 使用内网 HTTPS |
| `ASTRA_NR_TEST_SYSTEM_TOKEN` | 外部任务源认证 | 只从秘密系统注入 |

## 4. 准备员工本地工作空间

若员工环境使用“本地”，这里的本地指 Astra Worker 所在主机或容器。

每名员工需要一个长期工程目录。例如：

```text
/workspaces/astra-01/nr_test_system
/workspaces/astra-02/automation_platform
```

目录必须：

- 已包含员工需要处理的工程；
- 对 Worker 运行账号可读写；
- 包含该员工自己的 OpenCode 配置、Agent、Skills 与 Tools（如业务需要）；
- 不与另一名同时工作的员工共享同一个可写目录。

在 Compose override 中把实际工程挂载到 Worker：

```yaml
services:
  astra-backend:
    volumes:
      - /srv/astra/workspaces:/workspaces
  astra-worker:
    volumes:
      - /srv/astra/workspaces:/workspaces
```

配置中心的员工“工作空间”填写容器内路径，例如 `/workspaces/astra-01/nr_test_system`。

仓库不打包 OpenCode。应在受控构建阶段安装 Linux OpenCode，或通过只读卷同时挂载到 Backend 和 Worker 能看到的路径。Backend 用它测试连接，Worker 用它处理任务。

```bash
docker compose exec astra-backend opencode --version
docker compose exec astra-worker opencode --version
docker compose exec astra-worker test -w /workspaces/astra-01/nr_test_system
```

不要把 macOS 二进制挂载到 Linux 容器，也不要把模型凭据写进镜像层或仓库。

## 5. 准备 Linux 远程工作空间

远程员工需要：

- 到目标服务器的网络和防火墙权限；
- SSH Agent，或只读挂载的私钥文件；
- 已核验的 `known_hosts`，避免首次连接交互；
- 员工专属的远程工程工作空间；
- 远程 OpenCode 路径及执行权限；
- OpenCode 所需模型、Agent、Skills 和 Tools 配置。

示例只读 SSH 挂载：

```yaml
services:
  astra-backend:
    volumes:
      - ./deploy/ssh:/root/.ssh:ro
  astra-worker:
    volumes:
      - ./deploy/ssh:/root/.ssh:ro
```

Astra 使用 `BatchMode=yes`，不支持交互式密码。配置中心只保存密钥路径，不读取或保存私钥内容。

```bash
docker compose exec astra-worker ssh -o BatchMode=yes astra01@server-a.internal true
docker compose exec astra-worker ssh astra01@server-a.internal '/usr/local/bin/opencode --version'
docker compose exec astra-worker ssh astra01@server-a.internal 'test -d /home/astra01/nr_test_system && test -w /home/astra01/nr_test_system'
```

## 6. 数据库升级

启动前先备份数据库。标准升级：

```bash
cd backend
alembic current
alembic upgrade head
alembic current
```

升级后应看到 `0004_astra_v04 (head)`。

迁移 `0003_astra_v03` 会：

- 新建可配置任务分类表并写入三个默认分类；
- 为员工增加支持任务类型和支持分类；
- 为任务增加分类、结构化验收标准、附件、自然语言进展和人工介入信息；
- 把 P0/P1/P2/P3 映射为很高/高/中/低对应枚举；
- 把旧细分状态合并为待领取或处理中；
- 将旧完成标准迁移为结构化验收标准；
- 将旧任务结果包入 V0.3 结果结构，历史验收项标记为“无法确认”；
- 删除任务级工程输入、Workspace、固定 Phase、百分比和平台验证/重试字段；
- 删除员工 Skills、Capabilities、来源范围、自动修复和可配置并发字段。

迁移 `0004_astra_v04` 会：

- 增加任务完成策略、挂起现场、执行异常、退回历史和活跃度字段；
- 将旧任务 `PAUSED` 映射为 `SUSPENDED`；
- 将很高/高优先级存量任务默认设为人工确认；
- 以原 `updated_at` 初始化最后活动时间。

迁移前必须备份。不要对来源不明或结构不一致的数据库盲目执行 `alembic stamp`。

## 7. 构建与启动

```bash
docker compose config
docker compose up -d --build
docker compose ps
```

Backend 启动命令会先执行 `alembic upgrade head`。

```bash
curl --fail http://127.0.0.1:${ASTRA_BACKEND_PORT:-8100}/api/health
curl --fail http://127.0.0.1:${ASTRA_FRONTEND_PORT:-8080}/
docker compose logs --tail=100 astra-backend astra-worker
```

Worker 应连接 Redis 并注册任务发现、分配、心跳、恢复扫描和 OpenCode 处理任务。

## 8. 首次上线配置

1. 打开“配置中心 → 任务分类”，确认生产使用的分类。
2. 创建或更新员工基本信息与工作范围。
3. 为每名员工配置真实工程工作空间。
4. 点击“测试连接”，确认 OpenCode、SSH（如有）和工作空间均正常。
5. 确认员工是否允许自动领取和自主执行。
6. 配置外部任务源后再启动正式 Task Scout。

任务中不再传入 `project_path`、验证脚本或执行命令。若外部任务源仍使用 V0.2 契约，应先在 Adapter 中完成字段映射。

## 9. 上线验收

在源码构建环境先执行完整质量门禁：

```bash
./scripts/verify.sh
```

它会运行 Ruff、32 个后端测试、前端类型检查、生产构建和 9 条隔离的 Chromium E2E。生产 Compose 启动后，再检查健康状态和版本一致性：

```bash
curl --fail http://127.0.0.1:${ASTRA_BACKEND_PORT:-8100}/api/health
curl --fail http://127.0.0.1:${ASTRA_FRONTEND_PORT:-8080}/
docker compose exec astra-backend alembic current
docker compose exec astra-worker opencode --version
```

在能访问真实模型的目标 Worker 环境，使用一个受控工程副本执行真实 OpenCode 冒烟验证。源码环境可直接使用仓库脚本：

```bash
.venv/bin/python scripts/real_opencode_smoke.py \
  --model deepseek/deepseek-v4-flash \
  --opencode "$(command -v opencode)"
```

该验证会调用真实模型并消耗 Token。它必须使用员工实际运行账号、同类 OpenCode 配置与可写工作空间；不要把凭据写入命令、日志或仓库。脚本成功时会自动清理临时现场，失败时会保留诊断目录。当前本地验收基线见 `docs/verification/E2E-V0.4-2026-08-27.md`。

自动化测试不能替代生产的 Linux、SSH、模型网络、工作空间权限、企业认证网关和外部任务源联调；这些项目应在目标环境单独签收。

## 10. 生产安全

- 入口网关提供 HTTPS、SSO/OIDC、管理员授权、速率限制与审计；
- `/api/events/stream` 关闭代理缓冲并允许长连接；
- 员工工作空间包含源代码和运行产物，应按敏感研发数据保护；
- 一名员工使用一个独立可写工作空间，V0.4 不支持并行 Worktree；
- SSH 私钥只由基础设施挂载，数据库只保存路径；
- 远程用户使用最小权限账号；
- PostgreSQL、Redis、管理台和 API 均限制在受控网络；
- OpenCode 输出记录可能包含工程信息，`ASTRA_WORKSPACE_ROOT/records` 应加密备份并限制访问。

## 11. 备份与恢复

PostgreSQL 备份：

```bash
docker compose exec -T postgres pg_dump -U astra -Fc astra > astra-backup.dump
```

同时备份：

- Astra 观察记录卷；
- 员工工作空间或其对应 Git 仓库；
- 非秘密平台配置；
- SSH `known_hosts` 和基础设施侧密钥挂载配置。

数据库与文件尽量使用同一维护窗口。回滚前在隔离环境验证迁移兼容性，不要直接覆盖唯一生产副本。

## 12. 运维排查

### 员工不领取任务

检查员工是否启用、空闲、允许自动领取，环境是否 `AVAILABLE`，以及任务类型和分类是否在员工工作范围内。

### 本地环境异常

在 Backend 和 Worker 中分别运行 OpenCode `--version`，再以 Worker 账号检查员工工作空间是否存在且可写。

### Linux 远程环境异常

使用相同容器、账号、Host、Port 与 Key 重放批处理 SSH。重点检查 DNS、网络、`known_hosts`、文件权限、远程工作空间和 OpenCode 路径。

### 任务进入等待人工

查看任务的结构化人工介入信息、Event、最近 Run 的退出码和 OpenCode stderr。补充信息后使用“继续任务”，系统会恢复该任务原 Session。

### 任务进入执行异常

先保留数据库和 `ASTRA_WORKSPACE_ROOT/records` 中的现场。在员工详情重新执行“测试连接”，只有环境在异常发生后重新检查为 `AVAILABLE` 时，手工或周期恢复才会继续原任务。如原 Session 已不可用，Worker 会携带已保留进展、挂起现场、人工补充或退回意见创建新 Session。

### 重启后未完成任务

Backend 启动和 Celery Beat 会扫描 `RUNNING` / `WAIT_HUMAN` / `SUSPENDED` / `EXECUTION_ERROR`。等待人工和已挂起任务保持原状态；运行中任务只标记无活动提示；执行异常任务仅在环境经新一次检查恢复后自动继续。

### Token 或 Tool 显示 `—`

检查 Run 对应 OpenCode JSON 事件是否包含实际用量与工具事件。Astra 不会用字符数补算。

### 任务完成但验收项显示“无法确认”

表示员工最终回复没有返回可识别的逐项结论，不等于执行失败或“未满足”。Astra 优先解析 `ASTRA_RESULT_JSON`，并兼容清晰的 Markdown 验收表；两者都无法确认时才保留“无法确认”，由人工结合工作记录判断。Astra 不运行独立 Verifier，也不伪造验收结果。

## 13. 停止服务

```bash
docker compose down
```

不要在生产使用 `docker compose down -v`，它会删除 PostgreSQL 与 Astra 观察记录卷。员工外部工作空间是否受影响取决于实际挂载方式，也必须在执行前确认。
