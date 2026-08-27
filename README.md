# Astra V0.4

Astra 是面向长期数字员工的任务分配、工作观察、人工介入和结果管理平台。

Astra 定义任务目标、分类、优先级、执行员工和验收标准；任务真正如何完成，由数字员工自己的 OpenCode Agent 决定。平台不编排员工内部工作步骤，不管理 Skill 或 Tool，也不运行独立 Verifier。

V0.4 保持 V0.3 的职责边界，新增长期连续工作与更直观的数字办公室。当前版本包含：

- 问题 / 需求两种任务类型，以及可配置的任务分类；
- 自动分配或指定员工，匹配依据为员工状态、任务类型与任务分类；
- 每名员工一个本地或 Linux 远程 OpenCode 环境与长期工作空间；
- 每项任务独立 OpenCode Session，挂起、恢复和重启后优先继续原 Session；
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

另开终端：

```bash
cd frontend
npm ci
npm run dev
```

访问 `http://localhost:5173`，API 文档位于 `http://localhost:8100/docs`。

## Docker Compose

```bash
docker compose up --build
```

管理台位于 `http://localhost:8080`，API 位于 `http://localhost:8100`。

正式运行前需把 Linux 版 OpenCode 安装到 Worker 镜像或挂载到容器。员工配置中的“工作空间”必须直接指向该员工长期使用的工程目录，而不是 Astra 创建的任务目录。

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

任务中不填写工程路径、Workspace、Skill、Tool、模型、执行命令或验证脚本。

## 文档

- [V0.4 操作使用指南](docs/USER_GUIDE.md)
- [V0.4 部署手册](docs/DEPLOYMENT.md)
- [V0.4 实现与需求映射](docs/implementation-brief.md)
- [原始需求资料](docs/requirements/README.md)

V0.1–V0.4 原始需求及原型资料均保存在仓库中。V0.2 E2E 报告仅作为历史记录；按用户最新指示，V0.4 未执行功能或 E2E 验收。
