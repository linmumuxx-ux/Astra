# Astra V0.1 操作使用指南

## 1. 平台用途

Astra 是测试业务的常驻型数字员工平台。平台把任务发现、调度、OpenCode 执行、独立验证、失败修复和人工介入放在同一条可追踪链路中。任务只有在 Verifier 真实执行验证命令并通过后，才能进入“已完成”。

管理台默认地址：

- 本地开发：`http://localhost:5173`
- Docker Compose：`http://localhost:8080`
- API 文档：`http://localhost:8100/docs`

## 2. 首次启动

### 本地开发

后端需要 Python 3.11+，前端需要 Node.js 20+。

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload --port 8100
```

另开终端：

```bash
cd frontend
npm ci
npm run dev
```

打开 `http://localhost:5173`。默认 `ASTRA_SEED_DEMO=true`，首次启动会生成演示员工、任务、运行记录和事件。

## 3. 页面说明

### 总览

“总览”展示在线员工、运行中任务、等待人工、今日完成、任务趋势、活跃任务和最新事件。顶部 `LIVE` 表示 SSE 事件流已连接；`RECONNECT` 表示实时流暂时断开，此时仍可手工刷新。

### 数字员工

“数字员工”展示岗位、状态、能力边界、并发上限和当前任务。进入员工详情后可以查看任务负载，并暂停或恢复员工。暂停员工不会删除已生成的 Workspace、Session 或证据。

### 任务中心

任务可按关键词、来源、状态和优先级筛选。点击任务行或详情图标进入任务详情。常用状态：

- `待领取`：任务已持久化，等待 Dispatcher 分配。
- `运行中`：Worker 正在使用任务独立 Workspace 和 OpenCode Session 执行。
- `验证中`：Verifier 正在检查产物并执行真实验证命令。
- `修复重试`：失败可修复，继续使用原 Session 进行最小修复。
- `等待人工`：缺少环境、权限、信息或业务判断。
- `已完成`：独立验证已经通过。
- `失败/已终止`：终态，保留运行记录与证据。

### 运行记录

每次 OpenCode 调用形成一条 Run。这里可查看运行序号、执行器、退出码、耗时和 Session ID。点击 Run 可回到关联任务，检查完整事件和证据。

### 人工介入

这里只显示 `WAIT_HUMAN` 任务。处理人应：

1. 阅读阻塞原因、当前阶段、Workspace 和 Session。
2. 在“处理说明”中写明已完成的外部处理或判断。
3. 可在“补充信息”中加入继续执行所需上下文。
4. 点击“补充并继续”，任务恢复原现场；或确认无法继续后终止任务。

所有操作都会持久化为 Event，补充信息会写入任务 `input.human_input`。

### 配置中心

配置中心只展示非秘密运行参数。Token、密码等秘密必须通过环境变量注入，不得写入 YAML、数据库、任务描述或日志。

## 4. 创建手工任务

在“任务中心”点击“创建任务”，填写：

- 任务标题：简短、可检索的业务目标。
- 任务类型：脚本生成、代码检视、脚本执行或故障修复。
- 优先级：P0 最高，P3 最低。
- 任务描述：范围、背景、边界条件和禁止事项。
- 工程路径：Worker 能访问的绝对工程路径。
- 真实验证命令：Verifier 在工程目录中独立执行的命令，例如 `pytest tests/test_login.py -q`。
- 必需产物：每行一个相对工程路径，例如 `tests/test_login.py`。
- 完成标准：每行一条可检查的 Definition of Done。

创建后任务进入“待领取”。生产环境需要后端、Redis、Worker 和 OpenCode 均正常，任务才会被自动领取执行。

## 5. 任务控制与证据判读

任务详情提供以下操作：

- 暂停：停止继续推进，保留现场。
- 继续：从暂停或人工介入状态恢复；已分配任务会重新进入运行队列。
- 转人工：为需要人工判断的运行中任务记录原因并转入介入中心。
- 终止：进入不可恢复的终态，操作前页面会再次确认。

详情页证据分为三层：

1. 执行时间线：由数据库 Event 渲染，是状态变化的权威记录。
2. 实时运行日志：用于观察执行过程，不替代状态机结果。
3. 验证结果与证据产物：包含必需文件检查、测试命令退出码、执行日志和验证报告。

不要仅凭 OpenCode 输出中的“完成”判断任务成功；应以任务状态为“已完成”且验证结果为“通过”为准。

## 6. 接入 nr_test_system

设置以下环境变量并重启后端、Worker：

```bash
ASTRA_NR_TEST_SYSTEM_ENDPOINT=https://nr-test.example.internal
ASTRA_NR_TEST_SYSTEM_DISCOVER_PATH=/api/astra/tasks
ASTRA_NR_TEST_SYSTEM_RESULT_PATH=/api/astra/tasks/{external_task_id}/result
ASTRA_NR_TEST_SYSTEM_TOKEN=replace-with-secret
```

Task Scout 会按来源 Adapter 契约发现任务，`source + external_task_id` 用于幂等去重。目标系统当前仍需提供或映射对应的发现与结果回填接口。

## 7. E2E 验收

首次安装浏览器依赖：

```bash
cd frontend
npm ci
npx playwright install chromium
```

运行全量质量门禁：

```bash
./scripts/verify.sh
```

只运行浏览器端到端验收：

```bash
./scripts/e2e.sh
```

E2E 会启动独立后端和前端，使用临时 SQLite 数据库，完成健康检查、页面导航、任务创建、暂停/继续、事件核对和人工介入恢复。结束后自动停止临时服务，不修改日常开发数据库。

结果位置：

- HTML：`artifacts/playwright-report/index.html`
- JSON：`artifacts/test-results/results.json`
- 失败截图、视频和 Trace：`artifacts/test-results/`

## 8. 常见问题

- 页面出现 `RECONNECT`：先请求 `http://localhost:8100/api/health`，再检查前端代理和后端日志。
- 任务恢复后立即等待人工：通常是 Redis/Celery 队列不可用，事件中会保存具体错误。
- 任务无法完成：检查是否提供了 `input.verification.test_command`，以及 Worker 是否能访问工程路径和必需产物。
- OpenCode 启动失败：检查 `ASTRA_OPENCODE_BINARY`、执行权限、模型/Agent 配置和 Worker 运行用户的环境。
- E2E 提示缺少 Chromium：执行 `cd frontend && npx playwright install chromium`。

## 9. V0.1 边界

- `nr_test_system` 的正式接口需要对端联调。
- Docker Worker 镜像不内置公司分发的 OpenCode，部署时必须按实际渠道安装或挂载 Linux 可执行文件。
- 暂停与终止采用阶段边界上的协作式控制，不保证能中断任意第三方 CLI 的单条原子操作。
- V0.1 管理台没有内置登录和 RBAC，必须部署在可信内网或由外部网关提供认证。
