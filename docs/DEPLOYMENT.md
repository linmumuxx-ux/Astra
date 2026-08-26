# Astra V0.2 部署手册

## 1. 部署拓扑

推荐使用 Docker Compose 部署：

- `astra-frontend`：Nginx 托管 Vue 管理台并代理 `/api/`；
- `astra-backend`：FastAPI、REST API、SSE、环境连接检测和数据库迁移；
- `astra-worker`：Celery Worker + Beat，运行 Scout、Dispatcher、Heartbeat、OpenCode 和 Verifier；
- `postgres`：员工、环境、任务、Run、Token、工具调用、Event 和证据元数据；
- `redis`：Celery Broker/Result Backend。

Workspace 使用持久卷。Linux 远程模式的源码、输出和验证命令位于远程服务器；Astra 仍在本地 Workspace 证据区保存 OpenCode 输出、执行日志和验证报告。

## 2. 前置条件

- Linux x86_64/arm64，建议从 4 核 CPU、8 GB 内存、30 GB 磁盘起步；
- Docker Engine 24+ 与 Docker Compose v2；
- 可访问任务源、代码工程、测试环境和模型服务；
- 本地模式需要容器内可用的 Linux OpenCode CLI；
- 远程模式需要目标机 SSH、OpenCode 和可写 Workspace；
- TLS 域名与企业认证网关。

管理台没有内置登录/RBAC，不得直接暴露到公网。

## 3. 获取代码与配置

```bash
git clone git@github.com:linxuyiyi/Astra.git
cd Astra
cp deploy/docker.env.example .env
```

正式部署应固定 tag 或 commit，并将 `ASTRA_SEED_DEMO=false`。`.env` 已被 Git 忽略，不得提交真实秘密。

关键变量：

| 变量 | 用途 | 建议 |
| --- | --- | --- |
| `ASTRA_DATABASE_URL` | 异步 SQLAlchemy 数据库地址 | PostgreSQL，凭据从秘密系统注入 |
| `ASTRA_POSTGRES_PASSWORD` | Compose PostgreSQL 密码 | 强随机值并安全分发 |
| `ASTRA_REDIS_URL` | Celery Broker/Backend | 生产 Redis 地址 |
| `ASTRA_SEED_DEMO` | 演示数据 | 生产必须为 `false` |
| `ASTRA_OPENCODE_BINARY` | 默认本地 CLI 路径 | 容器内绝对路径 |
| `ASTRA_SSH_BINARY` | Linux 远程 SSH 客户端 | 默认 `ssh` |
| `ASTRA_SSH_CONNECT_TIMEOUT_SECONDS` | SSH 连接超时 | 默认 10 秒 |
| `ASTRA_NR_TEST_SYSTEM_ENDPOINT` | 任务源基地址 | 内网 HTTPS |
| `ASTRA_NR_TEST_SYSTEM_TOKEN` | 任务源认证 | 只从秘密系统或 `.env` 注入 |

## 4. 准备本地 OpenCode 环境

仓库不会打包公司内部 OpenCode。若员工使用 `LOCAL`：

1. 在受控构建阶段将 Linux OpenCode 安装进后端镜像；或
2. 通过只读卷把二进制和必要配置同时挂载到 `astra-backend` 与 `astra-worker`。

后端需要同一二进制来执行“测试连接”，Worker 需要它执行任务。两个容器必须看到相同路径和兼容配置。

验证：

```bash
docker compose run --rm astra-backend sh -lc "$ASTRA_OPENCODE_BINARY --version"
docker compose run --rm astra-worker sh -lc "$ASTRA_OPENCODE_BINARY --version"
```

不要把 macOS 二进制挂载到 Linux 容器，也不要将模型凭据写入镜像层或仓库。

## 5. 准备 Linux 远程执行

V0.2 镜像包含 `openssh-client`，但不会托管密码或私钥。部署人员需在后端和 Worker 的运行环境中准备：

- 到目标服务器的网络与防火墙权限；
- SSH Agent，或只读挂载的私钥文件；
- 已核验的 `known_hosts`，避免首次连接交互；
- 远程绝对 Workspace 根目录及写权限；
- 远程 OpenCode 路径与执行权限；
- 远程任务 `project_path` 的读取权限。

示例 Compose override（路径仅示意）：

```yaml
services:
  astra-backend:
    volumes:
      - ./deploy/ssh:/root/.ssh:ro
  astra-worker:
    volumes:
      - ./deploy/ssh:/root/.ssh:ro
```

保护 `deploy/ssh`，不要提交该目录。配置中心的 SSH Key 路径应填写容器内路径，例如 `/root/.ssh/id_ed25519`。Astra 使用 `BatchMode=yes`，不支持交互式密码输入。

在容器中先做等价检查：

```bash
docker compose exec astra-worker ssh -o BatchMode=yes astra@server-a.internal true
docker compose exec astra-worker ssh astra@server-a.internal '/usr/local/bin/opencode --version'
docker compose exec astra-worker ssh astra@server-a.internal 'mkdir -p /srv/astra/workspaces && test -w /srv/astra/workspaces'
```

## 6. 构建与启动

```bash
docker compose config
docker compose up -d --build
docker compose ps
```

后端启动命令会先执行 `alembic upgrade head`。检查：

```bash
curl --fail http://127.0.0.1:${ASTRA_BACKEND_PORT:-8100}/api/health
curl --fail http://127.0.0.1:${ASTRA_FRONTEND_PORT:-8080}/
docker compose logs --tail=100 astra-backend astra-worker
```

健康 API 应返回 `status: ok`，Worker 应连接 Redis 并运行 Beat。

## 7. V0.1 升级到 V0.2

V0.2 迁移 `0002_astra_v02` 会：

- 为现有员工补充自主策略字段；
- 为每名 V0.1 员工创建状态为 `UNKNOWN` 的默认本地环境；
- 为 Task/Run 添加环境快照；
- 为 Run 添加模型、Token、LLM/工具计数；
- 创建工具使用量表。

升级前备份数据库和 Workspace。标准 Alembic 部署直接执行：

```bash
cd backend
alembic current
alembic upgrade head
```

若早期 SQLite 开发库由 `create_all` 创建、已有 V0.1 表但 `alembic current` 为空，应先确认它确实只有 V0.1 结构，再执行：

```bash
cp data/astra.db data/astra-v01-before-v02.db.backup
alembic stamp 0001_astra_v01
alembic upgrade head
alembic current
```

不要对来源不明或结构不一致的数据库盲目 `stamp`。升级后应看到 `0002_astra_v02 (head)`，并在配置中心逐个测试默认环境。

## 8. 生产安全

入口网关应提供 HTTPS、SSO/OIDC、管理员授权、速率限制和审计。`/api/events/stream` 需关闭代理缓冲并允许长连接。

额外边界：

- 任务 Workspace 可包含源代码、日志和测试证据，应作为敏感研发数据保护；
- SSH 私钥仅由基础设施挂载，Astra 数据库只允许保存路径；
- 远程用户使用最小权限账号，不应授予无关主机或目录访问；
- `project_path` 和验证命令属于高权限任务输入，应限制任务创建来源；
- 生产数据库、Redis、管理台和 API 均应限制在受控网络。

## 9. 上线验收

发布前：

```bash
cd frontend
npm ci
npx playwright install chromium
cd ..
python3 -m venv .venv
.venv/bin/pip install -e 'backend[dev]'
./scripts/verify.sh
```

部署后逐项验收：

1. 总览无错误横幅，SSE 显示 `LIVE`。
2. 每名启用员工都配置且测试了默认环境。
3. 本地环境分项通过 OpenCode 存在、可启动、Workspace 可写。
4. Linux 远程环境分项通过 SSH、Workspace 和 OpenCode 检查。
5. 创建一个受控 P3 任务，确认它使用正确员工与环境快照。
6. 确认 Run 记录实际 Token、模型和工具调用；缺失字段显示 `—`。
7. 确认 Verifier 通过后任务才完成，并生成执行日志和报告。
8. 验证失败/转人工后 Run 用量仍可查看。
9. 再开启正式 Task Scout。

## 10. 备份、恢复与回滚

PostgreSQL 备份：

```bash
docker compose exec -T postgres pg_dump -U astra -Fc astra > astra-backup.dump
```

Workspace 使用卷快照或文件级备份。数据库和 Workspace 尽量使用同一维护窗口。

升级前固定目标 commit、备份、在预发布运行全量门禁。回滚前确认数据库迁移兼容性；若需数据回退，应从升级前备份恢复到隔离实例验证，禁止直接覆盖唯一生产副本。

## 11. 运维排查

### 员工不领取任务

检查员工是否启用、`auto_claim`、状态、能力/来源匹配、并发上限，以及环境是否 `AVAILABLE`。

### 本地环境检测失败

在后端和 Worker 中分别运行 OpenCode `--version`，并以相同运行账号测试 Workspace 写入。

### Linux 远程检测失败

使用相同容器、账号、Host、Port 和 Key 重放批处理 SSH。重点检查 DNS、网络、`known_hosts`、文件权限、远程目录和 OpenCode 路径。

### Token 或工具数据为 `—`

检查 Run 的 `opencode_output.json` 是否包含 JSON 格式使用量/工具事件，以及 OpenCode 是否使用 `--format json`。Astra 不会用字符数补算。

### 任务反复进入人工介入

按顺序检查任务 Event、Run 退出码、OpenCode stderr、工具失败、Verifier 报告和 `human_required_reason`。

## 12. 停止服务

```bash
docker compose down
```

不要在生产使用 `docker compose down -v`，它会删除 PostgreSQL 与 Workspace 持久卷。
