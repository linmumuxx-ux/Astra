# Astra V0.1

Astra 是面向测试业务的常驻型数字员工平台。它用确定性程序发现和调度任务，以每任务独立的 Workspace 与 OpenCode Session 执行工作，并在独立 Verifier 通过后才完成任务。

当前版本包含：

- FastAPI + SQLAlchemy 后端、集中状态机、事件与 SSE；
- Task Scout、Dispatcher、Celery Worker、Heartbeat；
- OpenCode CLI Executor 与 `nr_test_system` Task Source Adapter；
- 文件、执行结果和证据链的确定性 Verifier；
- Vue 3 + TypeScript 管理台：总览、数字员工、任务中心、任务详情、运行记录、人工介入和配置中心；
- PostgreSQL、Redis 与 Docker Compose 部署；
- SQLite 本地开发模式和演示数据。

## 快速启动（本地开发）

后端需要 Python 3.11+，前端需要 Node.js 20+。

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8100
```

另开终端：

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`，API 文档在 `http://localhost:8100/docs`。

## Docker Compose

```bash
docker compose up --build
```

管理台在 `http://localhost:8080`，API 在 `http://localhost:8100`。

`astra-worker` 镜像不会打包公司内部 OpenCode。正式容器运行前，需要按公司分发方式把 Linux 版改装 OpenCode 加入该镜像或挂载到 `ASTRA_OPENCODE_BINARY` 指定位置；macOS 的本机二进制不能直接挂入 Linux 容器。开发阶段可在已配置 OpenCode 的宿主机直接启动 Celery Worker。

## 运行真实任务前

1. 按 `.env.example` 配置 `nr_test_system` 的正式发现/回填地址；目前目标仓库尚未提供附件约定的 Astra 任务接口，因此 Adapter 契约已实现，但需要对端补齐接口或调整路径映射。
2. 确认本机 `opencode run --format json` 可用，并把任务输入中的 `project_path` 指向允许执行的工程。
3. 任务必须提供 `input.verification.test_command`；没有可程序化验证命令时，Verifier 会拒绝把任务标为完成并转入人工介入。

任务输入示例：

```json
{
  "task_type": "script_generate",
  "title": "生成并验证登录测试脚本",
  "description": "为登录流程补充自动化测试并在真实环境执行。",
  "input": {
    "project_path": "/path/to/nr_test_system",
    "verification": {
      "test_command": ["pytest", "tests/test_login.py", "-q"],
      "required_files": ["tests/test_login.py"]
    }
  },
  "definition_of_done": ["脚本生成完成", "测试真实执行并通过", "验证证据已保存"],
  "priority": 2
}
```

## 测试

```bash
./scripts/verify.sh
```

该命令依次执行后端静态检查、后端测试、前端类型检查、生产构建和 Chromium E2E。首次运行 E2E 前执行：

```bash
cd frontend
npm ci
npx playwright install chromium
```

只运行隔离的浏览器验收：`./scripts/e2e.sh`。HTML 报告生成在 `artifacts/playwright-report/index.html`。

## 文档

- [操作使用指南](docs/USER_GUIDE.md)
- [部署手册](docs/DEPLOYMENT.md)
- [E2E 验收报告](docs/verification/E2E-2026-08-27.md)
- [实现与需求映射](docs/implementation-brief.md)

原始需求和原型已保存在 [docs/requirements](docs/requirements) 与 [docs/references](docs/references)。实现边界和验收映射见 [docs/implementation-brief.md](docs/implementation-brief.md)。
