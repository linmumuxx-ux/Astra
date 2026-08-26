# Astra V0.1 部署手册

## 1. 部署拓扑

推荐使用 Docker Compose 部署五个服务：

- `astra-frontend`：Nginx 托管 Vue 静态文件，并将 `/api/` 代理到后端。
- `astra-backend`：FastAPI、数据库迁移、REST API 和 SSE。
- `astra-worker`：Celery Worker + Beat，运行 Scout、Dispatcher、Heartbeat 和任务闭环。
- `postgres`：权威业务状态、事件、Run 和证据元数据。
- `redis`：Celery Broker/Result Backend。

任务 Workspace 放在 `astra-workspaces` 持久卷，前后端不以本地内存作为权威状态。

## 2. 前置条件

- Linux x86_64/arm64 主机，建议 4 核 CPU、8 GB 内存、30 GB 可用磁盘起步。
- Docker Engine 24+ 与 Docker Compose v2。
- 可访问 `nr_test_system`、代码工程、测试环境和所需模型服务的网络。
- Worker 可用的 Linux 版 OpenCode CLI。
- 生产域名、TLS 证书和企业认证网关。

V0.1 管理台没有内置登录与 RBAC，不得直接暴露到公网。

## 3. 获取代码

```bash
git clone git@github.com:linxuyiyi/Astra.git
cd Astra
```

建议部署固定 tag 或 commit，不要让生产环境长期跟随未固定的开发分支。

## 4. 生产环境变量

复制示例并修改：

```bash
cp deploy/docker.env.example .env
```

必须修改 `ASTRA_POSTGRES_PASSWORD` 和所有真实系统地址/Token。`.env` 已被 Git 忽略，不要提交。

关键变量：

| 变量 | 用途 | 生产建议 |
| --- | --- | --- |
| `ASTRA_POSTGRES_PASSWORD` | PostgreSQL 密码 | 使用密码管理器生成并安全分发 |
| `ASTRA_SEED_DEMO` | 是否写入演示数据 | 必须设为 `false` |
| `ASTRA_FRONTEND_PORT` | 管理台宿主机端口 | 仅绑定内网或由反向代理访问 |
| `ASTRA_BACKEND_PORT` | API 宿主机端口 | 不需要外部访问时用防火墙限制 |
| `ASTRA_NR_TEST_SYSTEM_ENDPOINT` | 任务源基地址 | 使用内网 HTTPS 地址 |
| `ASTRA_NR_TEST_SYSTEM_TOKEN` | 任务源认证 | 只放秘密管理系统或 `.env` |
| `ASTRA_OPENCODE_BINARY` | Worker 内 CLI 路径 | 指向容器内 Linux 可执行文件 |

若密码包含 URL 保留字符，应进行 URL 编码并显式设置完整 `ASTRA_DATABASE_URL`，同时确保它与 PostgreSQL 实际密码一致。

## 5. 准备 OpenCode Worker

仓库的基础 Worker 镜像不会打包公司内部 OpenCode。上线前选择一种方式：

1. 在 `backend/Dockerfile` 的受控构建阶段安装公司分发的 Linux 包；或
2. 通过只读卷把 Linux 可执行文件和必要配置挂载进 `astra-worker`，并设置 `ASTRA_OPENCODE_BINARY`。

验证 Worker 镜像：

```bash
docker compose run --rm astra-worker sh -lc "$ASTRA_OPENCODE_BINARY --version"
```

不要把 macOS 可执行文件挂载到 Linux 容器，也不要把模型密钥写进镜像层、仓库或 Compose 文件。

## 6. 构建与启动

先检查最终配置：

```bash
docker compose config
```

构建并启动：

```bash
docker compose up -d --build
docker compose ps
```

后端容器启动时自动执行 `alembic upgrade head`。首次部署后检查：

```bash
curl --fail http://127.0.0.1:${ASTRA_BACKEND_PORT:-8100}/api/health
curl --fail http://127.0.0.1:${ASTRA_FRONTEND_PORT:-8080}/
docker compose logs --tail=100 astra-backend astra-worker
```

健康 API 应返回 `{"status":"ok", ...}`。Worker 日志应显示 Celery 已连接 Redis，Beat 正常调度。

## 7. 反向代理与安全

生产入口应由企业网关或反向代理提供：

- HTTPS/TLS；
- SSO、OIDC 或等效认证；
- 仅允许管理员网段/身份访问；
- `/api/events/stream` 关闭代理缓冲并允许长连接；
- 请求体、超时和访问日志策略；
- 速率限制和异常告警。

只允许 Astra Worker 访问被授权的代码工程与测试环境。Workspace 持久卷可能包含代码、日志和测试证据，应按敏感研发数据保护和备份。

## 8. 上线验收

在发布机先执行仓库质量门禁：

```bash
cd frontend
npm ci
npx playwright install chromium
cd ..
python3 -m venv backend/.venv
backend/.venv/bin/pip install -e 'backend[dev]'
./scripts/verify.sh
```

部署后执行最小冒烟：

1. 访问管理台并确认总览无错误横幅。
2. 确认顶部显示 `LIVE`。
3. 检查数字员工心跳与 Worker 日志。
4. 创建一个指向受控测试工程的 P3 手工任务。
5. 确认任务形成 Run、Event、Verifier 结果和证据。
6. 验证完成后再开启正式 Task Scout 来源。

## 9. 数据备份与恢复

备份 PostgreSQL：

```bash
docker compose exec -T postgres pg_dump -U astra -Fc astra > astra-backup.dump
```

Workspace 卷应使用基础设施提供的卷快照或文件级备份。数据库和 Workspace 快照应使用同一维护窗口，以减少元数据与证据文件不一致。

恢复前先停止写入流量和 Worker，再在隔离环境验证备份。恢复属于高风险操作，应按组织变更流程执行，不要直接覆盖唯一生产副本。

## 10. 升级与回滚

升级前：

1. 备份 PostgreSQL 和 Workspace。
2. 阅读数据库迁移与配置差异。
3. 在预发布环境执行 `./scripts/verify.sh`。
4. 固定目标 tag/commit 并重新构建镜像。

升级命令：

```bash
git fetch --tags
git checkout <approved-tag-or-commit>
docker compose up -d --build
docker compose ps
```

如需回滚，先确认新迁移是否向后兼容；再切换到已批准的旧版本并重新部署。若数据库迁移不可逆，应从升级前备份恢复到隔离实例，验证后再切换流量。

## 11. 运维排查

### 后端不健康

```bash
docker compose logs --tail=200 astra-backend postgres
docker compose exec postgres pg_isready -U astra
```

重点检查数据库密码、迁移错误和数据卷权限。

### Worker 不领取任务

```bash
docker compose logs --tail=200 astra-worker redis
docker compose exec redis redis-cli ping
```

重点检查员工是否暂停、并发上限、Redis 连接、Task Scout 来源和 OpenCode 可执行文件。

### 实时状态断开

检查 `/api/events/stream` 是否被网关缓冲或超时关闭。Nginx/网关需要允许长连接，前端代理路径必须保持 `/api/`。

### 任务反复进入人工介入

从任务详情按顺序检查 Event、Run 退出码、执行日志、Verifier 报告和 `human_required_reason`。修复外部环境后，在介入中心补充说明并恢复原 Session。

## 12. 停止服务

普通停机保留数据卷：

```bash
docker compose down
```

不要在生产环境使用 `docker compose down -v`，它会删除 PostgreSQL 和 Workspace 持久卷。
