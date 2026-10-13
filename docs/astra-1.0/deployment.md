# Astra 1.0 部署与验证入口

当前为重建开发分支，尚不满足生产切换条件。下列命令运行独立 1.0 schema 和新运行树；不得指向现有 0.xx 数据库，也不得以这些命令替代生产迁移签收。本机隔离 MySQL 8.4.10、Redis/Celery/Beat 已真实验证；公司 Linux/Windows、SSH、反向代理与灾备仍需实际环境验收。

## 独立排练

从仓库根目录运行，Python >=3.11，使用独立虚拟环境安装根 `pyproject.toml`。当前本机实际验证环境为 Python 3.14.3；MCP SDK 2.1.1、FastAPI 0.141.1、SQLAlchemy 2.0.52、Celery 5.6.3。宽版本范围不等于已验证所有组合，发布前必须锁定完整依赖与公司镜像。

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
export ASTRA_V1_DATABASE_URL=sqlite+aiosqlite:////absolute/isolated/astra-v1.db
.venv/bin/python -m apps.api.manage migrate
.venv/bin/python -m apps.api.manage bootstrap --name 管理员 --token-file /secure/astra-v1-admin.token
.venv/bin/python -m apps.api.manage serve --host 127.0.0.1 --port 8200
```

上面是新环境安装步骤，不要在已有含用户改动的虚拟环境上重新初始化。bootstrap 仅允许首次创建人类身份，输出文件以 0600 创建、拒绝覆盖、不打印凭据；初始凭据 24 小时有效。后续人类身份、团队成员和工程 Grant 通过组织页管理；凭据轮换经人类管理员调用 `/actors/{id}/credentials`，旧凭据经 `/credentials/{id}/revoke` 撤销。员工权限仍受岗位与工程范围限制。

```bash
cd apps/web
npm ci
ASTRA_API_URL=http://127.0.0.1:8200 npm run dev
```

开发 Web 默认 5273，只代理新 API。旧 8100/5173 服务、旧 `.env` 和数据库不会被新入口修改。正式 Web 运行 `npm run build` 后由公司静态服务器分发 `apps/web/dist`；配置 SPA 路由回退和同源 `/api/v1` 反向代理。SSE 关闭代理缓冲并设置足够长的读取超时；凭据不放 URL，使用 HTTPS。

## Runtime 与 MCP

Persona 与 Task 使用不同 OpenCode Server、目录、Session 用途及权限。当前实际兼容验证为 OpenCode **1.18.35**，版本之外必须重新跑真实接口/权限测试，不能仅按版本更大放行。不要把员工固定绑定 Worker，也不要给 Persona 工程目录或无限制 shell。

Worker 在资源页注册明确 OpenCode URL、允许工程、能力和绝对工作区根，再点击“检查真实 Runtime”。当前本地 worktree 适配已验收；远程 SSH/Windows 尚未接线。受保护 Worker 的 credential_ref 解析未实现时检查会明确拒绝，不能忽略秘密配置。任务 dispatch 当前只绑定租约，不能据此认为工程任务已启动。

MCP 必须显式配置 `ASTRA_V1_DATABASE_URL`、`ASTRA_V1_API_URL`、`ASTRA_V1_MCP_RESOURCE_URL`、`ASTRA_V1_MCP_PORT`，运行 `python -m agents.tools`。默认只监听 127.0.0.1，反向代理继续转发 Authorization。使用经过签发的主体凭据，不能配置默认用户或让模型传入操作身份。

## 可信 Routine 调度

人类管理员通过 `POST /api/v1/system-identities/schedulers` 提供名称、指定团队和客户端生成的短期凭据 SHA256。后端固定签发 SYSTEM + routine.signal，不接收调用者自选权限；明文只写部署秘密文件。

```bash
export ASTRA_V1_BROKER_URL=redis://127.0.0.1:6379/2
export ASTRA_V1_SCHEDULER_CREDENTIAL_FILE=/run/secrets/astra-v1-scheduler.token
.venv/bin/celery -A apps.services.celery_app:app worker --queues astra-v1 --loglevel INFO
.venv/bin/celery -A apps.services.celery_app:app beat --schedule /var/lib/astra-v1/beat-state --loglevel INFO
```

Beat 每 30 秒扫描指定身份有成员关系的团队。重复扫描由 Routine CAS 与来源唯一键防重，过期积压汇总一条；系统每团队重新认证，撤销/到期立即阻止后续投递。调度身份不能编辑 Routine。

## Persona 与个人 Git Memory

人类管理员另经 `POST /api/v1/system-identities/personas` 签发指定团队 SYSTEM + persona.run。凭据 24 小时到期，需要部署侧轮换；不复用人类管理员、Worker 或 Routine 投递凭据。

```bash
export ASTRA_V1_PERSONA_CREDENTIAL_FILE=/run/secrets/astra-v1-persona.token
export ASTRA_V1_PERSONA_URL=http://127.0.0.1:4097
export ASTRA_V1_PERSONA_DIRECTORY=/var/lib/astra-v1/persona
export ASTRA_V1_PERSONA_MODEL=provider/model
export ASTRA_V1_MEMORY_ROOT=/var/lib/astra-v1/memory
```

决策目录与 Git Memory 根使用真实绝对路径，不经过符号链接。部署侧先建立只有服务账号可读写的目录，启动独立 OpenCode Server；模型密钥和 `ASTRA_V1_PERSONA_PASSWORD` 通过秘密渠道注入，不能写进项目或模型上下文。Persona Session 权限为 deny-all；有限提案由后台领域服务执行。

配置 Persona 凭据后，Beat 每 10 秒扫描有效 Inbox。一个员工最多一个有效 Turn；持久记录输入引用与提交意图。进程重启只对账原生 Session，不能重新提交同一 prompt。观察与用量先保存；动作与处理结论原子提交。暂停、撤权、旧 fence 和政策/记忆版本变化均阻止动作。当前 dispatch 只创建 Task 并绑定 lease，工程启动仍待接线。

Memory 在 `employees/<UUID>/.git` 的对象库内保存 IDENTITY.md、MEMORY.md、notes 与来源 manifest；数据库 head 决定可见版本，工作权限不会从 Git 文件恢复。API 支持版本编辑、diff、载入历史内容再提交新版本和过期提醒。备份必须同时包含数据库 head 和对应 Git 对象库；不能只备份某个工作目录文件。

OpenCode 1.18.35 的原生 json_schema 输出在实际验证中触发持久消息解码错误；本版本明确采用原生文本 JSON 协议并由后端严格校验，不走出错后自动重提的路径。真实短回合、跨 Session 记忆和 Redis/Celery/Beat 结果见 `persona-live-report.json`。公司多节点队列、硬配额与全部工程协作仍未验收。

## 历史内容与迁移

按照 `migration.md` 执行冻结签认、只读导出、显式映射和正式 schema 导入。离线 importer 不打包到业务 wheel，新业务运行时不 import 它。迁入文件放入管理员维护的归档目录，配置 `ASTRA_V1_HISTORY_ARTIFACT_ROOT`；在线读取仅接受索引内 `artifact://SHA256.json`，验证真实文件字节，不读取任意本机路径。

正式导入需要新空库，不能先 bootstrap 写入再首次全量导入。迁入 Actor 默认 inactive，Employee 默认 PAUSED，Worker disabled；业务及权限签收后才按受控流程配置。当前迁移报告一律不允许生产切换；真实外部 Session/Workspace/Skill 与只读档案不能被当成可继续执行的新任务。

## 内网构建与运维边界

前端依赖锁定在 `apps/web/package-lock.json`；Three.js、Vue、Element Plus、图标和 CSS 都本地打包，没有远程字体/CDN 脚本。联网构建环境应预先填充公司 npm 镜像/缓存与 Python wheelhouse，并保存 Node/Python/OpenCode 安装包、平台专用浏览器和版本清单；内网构建用 `npm ci --offline --cache <company-cache>` 和 pip `--no-index --find-links <wheelhouse>`。本机已构建产物不证明另一台全新内网机器的缓存齐全，离线冷构建尚待实测。

分别备份新数据库、知识/历史归档、员工 Memory Git 对象库、Task worktree 与 OpenCode 原生会话目录，并做恢复演练。不要把模型/SSH/API 密钥放入镜像、文档或模型上下文。发布时只启用新 API/Web/Celery/MCP 与新 schema，旧写入者停止并封存；完整门禁未通过前不得删除原数据或正式切换。

## 本地检查

```bash
ASTRA_E2E_BROWSER=/absolute/path/to/chrome .venv/bin/python scripts/verify.py
```

默认执行新树静态、领域/迁移/HTTP 集成、前端构建和独立临时库上的真实 API 浏览器测试。浏览器默认使用 Playwright 安装；已有 Chrome 可显式指定，不由脚本联网下载。临时进程使用自己的随机端口与数据库，退出后只清理自己的资源。Windows 使用 `.venv/Scripts/python.exe` 与本机浏览器路径，当前未在 Windows 运行。

隔离 MySQL 运行 `python tests/v1/run_mysql.py`，只启动自己的临时目录与端口。真实 Persona/Beat 运行 `ASTRA_LIVE_MODEL=provider/model python scripts/verify.py --live-persona`；模型测试默认跳过，避免重复消耗。

真实 OpenCode 工程测试须显式配置 `ASTRA_LIVE_MODEL=provider/model` 并追加 `--live-runtime`，默认测试不会重复消耗模型额度。已有成功报告保存在 `runtime-live-report.json`，其中 whole_system_acceptance=false。本地入口通过仍不能替代全部多员工、成长、生产历史及公司环境验收。
