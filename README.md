# Astra V0.4

Astra 是面向长期数字员工的任务分配、工作观察、人工介入和结果管理平台。

Astra 定义任务目标、分类、优先级、执行员工和验收标准；任务真正如何完成，由数字员工自己的 Agent 决定。平台不编排员工内部工作步骤，不管理 Skill 或 Tool，也不运行独立 Verifier。当前内置 OpenCode 适配器，执行接口可继续扩展 Claude Code、Codex 等 Agent 工具。

V0.4 保持 V0.3 的职责边界，新增长期连续工作与更直观的数字办公室。当前版本包含：

- 问题 / 需求两种任务类型，以及可配置的任务分类；
- 自动分配或指定员工，匹配依据为员工状态、任务类型与任务分类；
- 每名员工一个本地或 Linux 远程 Agent 工作环境、可选模型和长期工作空间；
- 每项任务独立执行会话，挂起、恢复和重启后优先继续原会话；
- 指定员工任务优先、再按优先级和 FIFO 的连续自动领取；
- 安全挂起、待人工确认、执行异常恢复和无活动提示；
- 数字办公室、待处理中心与可选“减少动效”；
- 可读工作进展、详细操作与原始 Run / 日志三层观察；
- 员工提交的处理结果、逐项验收结果与证据；
- Run、Task、Employee 和 Platform 四级 Token / Tool 汇总；
- Vue 3 管理台、FastAPI 后端、PostgreSQL、Redis 与 Celery Worker。

## 快速启动

后端需要 Python 3.11+，前端需要 Node.js 20+。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload --port 8100
```

另开一个终端启动 Redis、任务分配器和 Agent Worker：

```bash
./scripts/runtime.sh
```

该进程必须保持运行，否则页面仍可访问，但新任务会一直停在“待领取”。脚本会复用 `ASTRA_REDIS_URL` 指定的 Redis；本地默认 Redis 未运行时，会尝试启动随进程关闭的临时实例。

再开一个终端启动管理台：

```bash
cd frontend
npm ci
npm run dev
```

访问 `http://localhost:5173`，API 文档位于 `http://localhost:8100/docs`。

## 正式部署

项目采用原生进程部署：FastAPI 和 Celery 由 systemd 守护，Redis 与 PostgreSQL
使用主机服务，前端生产产物由 Nginx 托管。员工工作空间是宿主机上的长期工程目录，
当前使用 OpenCode 适配器时，OpenCode 安装在实际执行 Worker 的主机或远程 Linux 主机。

完整安装、systemd、Nginx、升级、备份和停止步骤见[部署手册](docs/DEPLOYMENT.md)。

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

任务中不填写工程路径、Workspace、Skill、Tool、模型、执行命令或验证脚本；模型在员工的 Agent 工作环境中配置。

## 文档

- [V0.4 操作使用指南](docs/USER_GUIDE.md)
- [V0.4 部署手册](docs/DEPLOYMENT.md)
- [V0.4 实现与需求映射](docs/implementation-brief.md)
- [数字办公室设计说明与参考案例](docs/design/DIGITAL_OFFICE.md)
- [V0.4 功能、系统 E2E 与真实 Agent 验收报告](docs/verification/E2E-V0.4-2026-08-28.md)
- [原始需求资料](docs/requirements/README.md)

V0.1–V0.4 原始需求及原型资料均保存在仓库中。当前版本已通过 37 个后端测试、前端类型检查与生产构建、10 条 Chromium E2E；系统 E2E 会真实启动 Redis、Worker、Backend、Frontend 和可控 Agent，覆盖员工模型配置以及“询问—等待答复—继续执行—验收完成”。另已使用本地 OpenCode + `deepseek/deepseek-v4-flash` 验证真实任务领取和结构化询问。V0.2 E2E 报告仅作为历史记录。
