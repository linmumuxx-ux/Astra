# Astra V0.4 部署手册

## 1. 部署方式

Astra 使用原生进程部署：

- Nginx 托管 Vue 管理台生产产物，并代理 `/api/`、API 文档和 SSE；
- Uvicorn 运行 FastAPI、REST API、SSE 和员工环境检查；
- Celery Worker + Beat 运行任务发现、分配、心跳、恢复扫描和 Agent 执行器；
- PostgreSQL 保存分类、员工、环境、任务、Run、Token、Tool、事件和结果元数据；
- Redis 作为 Celery Broker 和 Result Backend；
- systemd 守护 Backend 和调度运行时。

员工工作空间是由运维提前准备的长期工程目录。`ASTRA_WORKSPACE_ROOT/records`
只保存 Agent 观察记录，不是任务源码工作区。

## 2. 前置条件

- Linux x86_64 或 arm64，建议从 4 核 CPU、8 GB 内存、30 GB 磁盘起步；
- Python 3.11+、Node.js 20+、Nginx、Git 和 `openssh-client`；
- PostgreSQL 14+ 与 Redis 6+，安装为主机服务或使用企业已有托管实例；
- Worker 主机安装至少一种平台支持的 Agent；当前版本内置 OpenCode 适配器；
- 可访问任务源、代码仓库、模型服务和员工需要的外部系统；
- 远程员工的目标主机已配置 SSH、对应 Agent 和员工专属可写工作空间；
- TLS 域名和企业认证网关。

管理台没有内置登录/RBAC，不得直接暴露到公网。

## 3. 安装代码与依赖

以 `/opt/astra` 为示例安装目录：

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin astra
sudo git clone git@github.com:linxuyiyi/Astra.git /opt/astra
sudo chown -R astra:astra /opt/astra
cd /opt/astra
sudo -u astra python3 -m venv .venv
sudo -u astra .venv/bin/pip install -e backend
sudo -u astra npm --prefix frontend ci
sudo -u astra npm --prefix frontend run build
```

正式环境必须固定 Git tag 或 commit，不要直接跟随未验收的分支。

## 4. 准备 PostgreSQL 与 Redis

以 PostgreSQL 为例创建独立数据库和账号：

```bash
sudo -u postgres createuser --pwprompt astra
sudo -u postgres createdb --owner=astra astra
```

确认两个服务可用：

```bash
pg_isready -h 127.0.0.1 -p 5432
redis-cli -u redis://127.0.0.1:6379/0 ping
```

生产数据库和 Redis 应限制在受控网络，并按企业规范配置鉴权、备份和监控。

## 5. 配置环境变量

```bash
sudo install -d -m 0750 -o root -g astra /etc/astra
sudo cp /opt/astra/deploy/astra.env.example /etc/astra/astra.env
sudo chown root:astra /etc/astra/astra.env
sudo chmod 0640 /etc/astra/astra.env
sudo editor /etc/astra/astra.env
```

关键变量：

| 变量 | 用途 | 生产建议 |
| --- | --- | --- |
| `ASTRA_DATABASE_URL` | 异步 SQLAlchemy 数据库地址 | 使用 PostgreSQL，凭据从受控配置注入 |
| `ASTRA_REDIS_URL` | Celery Broker / Backend | 使用受控 Redis |
| `ASTRA_SEED_DEMO` | 演示数据开关 | 必须为 `false` |
| `ASTRA_WORKSPACE_ROOT` | Astra 观察记录目录 | 使用持久磁盘，不作为员工源码目录 |
| `ASTRA_CONFIG_DIR` | 员工初始配置目录 | 指向只读的受控配置 |
| `ASTRA_OPENCODE_BINARY` | 当前 OpenCode 适配器的本机 Agent 启动路径 | 使用绝对路径 |
| `ASTRA_OPENCODE_MODEL` | 可选的平台模型后备值 | 员工页面配置优先；建议按员工配置 |
| `ASTRA_INACTIVITY_TIMEOUT` | 无可观察活动多久后提示 | 默认 `900` 秒；只提示，不改状态 |
| `ASTRA_RECOVERY_INTERVAL` | 恢复和活跃度扫描间隔 | 默认 `30` 秒 |
| `ASTRA_SSH_BINARY` | Linux 远程 SSH 客户端 | 默认 `ssh` |
| `ASTRA_NR_TEST_SYSTEM_ENDPOINT` | 外部任务源地址 | 使用内网 HTTPS |
| `ASTRA_NR_TEST_SYSTEM_TOKEN` | 外部任务源认证 | 只从秘密管理系统注入 |

## 6. 准备员工工作空间

本地员工与 Astra Worker 在同一台主机上工作。每名员工需要独立的长期工程目录，例如：

```text
/srv/astra-employees/astra-01/nr_test_system
/srv/astra-employees/astra-02/automation_platform
```

目录必须：

- 已包含员工需要处理的工程；
- 对 `astra` 运行账号可读写；
- 包含该员工自己的 Agent 配置、Agent、Skills 与 Tools（如业务需要）；
- 不与另一名同时工作的员工共享同一个可写目录。

以服务账号检查：

```bash
sudo -u astra /usr/local/bin/opencode --version
sudo -u astra test -w /srv/astra-employees/astra-01/nr_test_system
```

## 7. 准备 Linux 远程工作空间

远程员工需要：

- 到目标服务器的网络和防火墙权限；
- `astra` 账号可使用的 SSH Agent，或权限为 `0600` 的私钥文件；
- 已核验的 `known_hosts`，避免首次连接交互；
- 员工专属的远程工程工作空间；
- 远程 Agent 路径及执行权限。

Astra 使用 `BatchMode=yes`，不支持交互式密码。配置中只保存私钥路径，不读取或保存私钥内容。

```bash
sudo -u astra ssh -o BatchMode=yes astra01@server-a.internal true
sudo -u astra ssh astra01@server-a.internal '/usr/local/bin/opencode --version'
sudo -u astra ssh astra01@server-a.internal \
  'test -d /home/astra01/nr_test_system && test -w /home/astra01/nr_test_system'
```

## 8. 数据库升级

升级前必须备份数据库。以 `/etc/astra/astra.env` 中的变量运行：

```bash
sudo -u astra bash -c 'set -a; source /etc/astra/astra.env; set +a; cd /opt/astra/backend; /opt/astra/.venv/bin/alembic current'
sudo -u astra bash -c 'set -a; source /etc/astra/astra.env; set +a; cd /opt/astra/backend; /opt/astra/.venv/bin/alembic upgrade head'
sudo -u astra bash -c 'set -a; source /etc/astra/astra.env; set +a; cd /opt/astra/backend; /opt/astra/.venv/bin/alembic current'
```

使用 systemd 部署时，Backend 服务的 `ExecStartPre` 会自动执行同一升级。升级后应看到
`0004_astra_v04 (head)`。不要对来源不明或结构不一致的数据库盲目执行 `alembic stamp`。

## 9. 安装 systemd 与 Nginx 配置

```bash
sudo install -d -m 0750 -o astra -g astra /var/lib/astra
sudo cp /opt/astra/deploy/systemd/astra-backend.service /etc/systemd/system/
sudo cp /opt/astra/deploy/systemd/astra-runtime.service /etc/systemd/system/
sudo cp /opt/astra/deploy/nginx-astra.conf /etc/nginx/conf.d/astra.conf
sudo systemctl daemon-reload
sudo systemctl enable --now astra-backend astra-runtime
sudo nginx -t
sudo systemctl reload nginx
```

如果实际安装目录不是 `/opt/astra`，先修改两个 unit 和 Nginx 配置中的路径。

检查启动状态：

```bash
systemctl status astra-backend astra-runtime --no-pager
curl --fail http://127.0.0.1:8100/api/health
curl --fail http://127.0.0.1/
journalctl -u astra-backend -u astra-runtime -n 100 --no-pager
```

Worker 日志应显示已连接 Redis 并注册任务发现、分配、心跳、恢复扫描和 Agent 处理任务。

## 10. 首次上线配置

1. 打开“配置中心 → 任务分类”，确认正式使用的分类。
2. 创建或更新员工基本信息与工作范围。
3. 为每名员工配置真实工程工作空间、Agent 启动命令和所需模型。
4. 保存环境配置并确认自动检测结果；也可点击“测试连接”，确认 Agent、SSH（如有）和工作空间均正常。
5. 确认员工是否允许自动领取和自主执行。
6. 配置外部任务源后再启用正式 Task Scout。

任务中不再传入 `project_path`、验证脚本或执行命令。若外部任务源仍使用 V0.2 契约，
应先在 Adapter 中完成字段映射。

## 11. 上线验收

在源码构建环境执行：

```bash
./scripts/verify.sh
```

该命令运行 Ruff、后端测试、前端类型检查、生产构建和 10 条隔离的 Chromium E2E；E2E 会启动 Redis、Celery Worker/Beat、Backend、Frontend 和可控 Agent，覆盖员工模型配置以及完整询问与继续执行链路。
服务启动后再检查：

```bash
curl --fail http://127.0.0.1:8100/api/health
curl --fail http://127.0.0.1/
sudo -u astra /usr/local/bin/opencode --version
```

在能访问真实模型的 Worker 主机，使用受控工程副本执行当前 OpenCode 适配器的冒烟验证：

```bash
.venv/bin/python scripts/real_opencode_smoke.py \
  --model deepseek/deepseek-v4-flash \
  --opencode "$(command -v opencode)"
```

该验证会调用真实模型并消耗 Token。必须使用员工实际运行账号、同类 Agent 配置
与可写工作空间；不要把凭据写入命令、日志或仓库。自动化不能替代目标 Linux、SSH、
模型网络、工作空间权限、企业认证网关和外部任务源联调。

## 12. 生产安全

- 入口网关提供 HTTPS、SSO/OIDC、管理员授权、速率限制与审计；
- `/api/events/stream` 关闭代理缓冲并允许长连接；
- 员工工作空间包含源码和运行产物，应按敏感研发数据保护；
- 一名员工使用一个独立可写工作空间，V0.4 不支持并行 Worktree；
- SSH 私钥由主机权限和秘密系统管理，数据库只保存路径；
- 远程用户使用最小权限账号；
- PostgreSQL、Redis、管理台和 API 均限制在受控网络；
- Agent 输出记录可能包含工程信息，`ASTRA_WORKSPACE_ROOT/records` 应加密备份并限制访问。

## 13. 备份与恢复

PostgreSQL 备份：

```bash
sudo -u postgres pg_dump -Fc astra > astra-backup.dump
```

同时备份：

- `ASTRA_WORKSPACE_ROOT/records`；
- 员工工作空间或其对应 Git 仓库；
- 非秘密平台配置；
- SSH `known_hosts` 和基础设施侧密钥配置。

数据库与文件尽量使用同一维护窗口。回滚前在隔离环境验证迁移兼容性，不要直接覆盖唯一生产副本。

## 14. 运维排查

### 员工不领取任务

先检查 `systemctl status astra-runtime`和 Worker 日志，再检查员工是否启用、空闲、允许自动领取，
环境是否“正常”，以及任务类型和分类是否在员工工作范围内。

### 本地环境异常

以 `astra` 账号执行配置的 Agent `--version`，并检查员工工作空间是否存在且可写。

### Linux 远程环境异常

使用相同主机账号、Host、Port 与 Key 重放批处理 SSH。重点检查 DNS、网络、`known_hosts`、
文件权限、远程工作空间和 Agent 路径。

### 任务进入等待人工或执行异常

保留数据库和 `ASTRA_WORKSPACE_ROOT/records` 中的现场，查看任务的结构化人工介入信息、Event、
最近 Run 的退出码和 Agent stderr。补充信息或修复环境后继续原任务会话。

### 任务完成但验收项显示“无法确认”

表示员工最终回复没有返回可识别的逐项结论，不等于执行失败或“未满足”。Astra 优先解析
`ASTRA_RESULT_JSON`，并兼容清晰的 Markdown 验收表；两者都无法确认时才保留“无法确认”。

## 15. 升级与停止

升级：

```bash
sudo systemctl stop astra-runtime astra-backend
cd /opt/astra
sudo -u astra git fetch --tags origin
sudo -u astra git checkout <validated-tag-or-commit>
sudo -u astra .venv/bin/pip install -e backend
sudo -u astra npm --prefix frontend ci
sudo -u astra npm --prefix frontend run build
sudo systemctl start astra-backend astra-runtime
```

停止 Astra 应用进程：

```bash
sudo systemctl stop astra-runtime astra-backend
```

停止 Astra 不会删除 PostgreSQL 数据、Redis 服务、观察记录或员工工作空间。
