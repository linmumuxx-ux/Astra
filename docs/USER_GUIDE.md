# Astra V0.2 操作使用指南

## 1. 平台用途

Astra 是面向测试业务的常驻型数字员工平台。它把任务发现、员工调度、OpenCode 执行、独立验证、自动修复和人工介入串成可恢复、可追踪的工作闭环。任务只有通过独立 Verifier，才能进入“已完成”。

V0.2 新增两项核心能力：

- 每名数字员工固定关联一个默认 OpenCode 执行环境，可选择本地或 Linux 远程环境；
- 从 OpenCode 实际返回中采集 Token、LLM 调用和工具调用，并按 Run、任务、员工和平台聚合。

默认地址：

- 本地管理台：`http://localhost:5173`
- Docker Compose 管理台：`http://localhost:8080`
- API 文档：`http://localhost:8100/docs`

## 2. 首次启动

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

打开 `http://localhost:5173`。默认 `ASTRA_SEED_DEMO=true`，首次启动会生成演示员工、任务、环境、Run 和使用量数据。正式环境必须将该变量设为 `false`。

## 3. 推荐的首次配置顺序

1. 进入“配置中心 → 数字员工配置”。
2. 新建员工，填写基本信息、能力/技能和自主策略。
3. 在“执行环境”中选择“本地执行”或“Linux 远程”。
4. 保存配置，然后点击“测试连接”。
5. 确认环境状态为“正常”。只有环境正常、员工启用且允许自动领取时，Dispatcher 才会分配新任务。
6. 创建一条包含真实验证命令的受控测试任务，观察 Run、Token、工具调用和 Verifier 证据。

员工运行状态与环境状态互相独立。例如，员工可以处于“空闲”，但环境为“不可用”；此时不会自动领取任务。

## 4. 配置数字员工

### 基本信息

- 员工 ID：创建后不可修改，建议使用稳定标识，如 `astra-04`。
- 显示名称、岗位、描述：用于说明职责和业务边界。
- 任务来源范围：以英文逗号分隔，例如 `manual, nr_test_system`。
- 启用员工：关闭后不参与调度，但历史任务和使用量仍保留。

### 能力与技能

能力标签参与 Dispatcher 的确定性匹配，常用值包括：

- `script_generate`
- `script_review`
- `script_execute`
- `script_repair`
- `result_verify`

技能标签用于描述员工擅长的技术栈，不替代任务类型匹配。

### 自主策略

- 自动领取：允许 Dispatcher 分配匹配任务。
- 自动执行：领取后立即进入 Worker；关闭时任务停留在“已领取”，可从 API 手工启动。
- 自动修复：执行或验证失败后继续原 OpenCode Session 修复。
- 最大自动重试：限制自动修复次数。
- 最大并发任务：限制该员工的同时工作数量。

## 5. 配置 OpenCode 执行环境

### 本地执行

本地指 Astra 后端/Worker 所在主机或容器。需填写：

- 环境名称；
- OpenCode 命令或绝对路径，例如 `opencode` 或 `/usr/local/bin/opencode`；
- Workspace 根目录，例如 `./workspaces`。

“测试连接”会分项检查 OpenCode 是否存在、能否启动，以及 Workspace 是否可创建和写入。

### Linux 远程

Linux 远程环境通过系统 `ssh` 命令执行。需填写：

- Host、Port、Username；
- SSH Agent 或 SSH Key 路径；
- 远程 OpenCode 路径；
- 远程绝对 Workspace 根目录，例如 `/srv/astra/workspaces`。

“测试连接”会分项检查 SSH、远程 Workspace、OpenCode 文件和启动命令。Astra 不接受 SSH 密码，也不保存私钥内容；SSH Key 字段只保存 Worker 可访问的文件路径。

修改正在工作的员工环境时，当前任务继续使用领取时保存的环境快照，新配置只影响后续新任务。

## 6. 页面说明

### 总览

展示在线员工、运行中任务、等待人工、今日完成、今日 Token 和今日工具调用。Token 无法从 OpenCode 获取时显示 `—`，不会估算。

### 数字员工

员工卡片展示员工状态、默认环境、环境状态、当前任务、今日 Token、工具调用和完成数。列表可按员工状态与环境模式筛选。

员工详情包含：

- 默认 OpenCode 执行环境与检测结果；
- 当前任务和环境快照；
- 今日工作消耗；
- 近 7 天/30 天 Token 趋势；
- 自主完成率、人工介入率、成功率、平均重试和平均耗时；
- 工具调用 Top 与处理记录。

### 任务中心与任务详情

任务中心支持关键词、来源、状态和优先级筛选。常见状态：

- 待领取：等待 Dispatcher；
- 已领取：已分配员工，等待自动或手工启动；
- 运行中：OpenCode 正在工作；
- 验证中：Verifier 正在执行确定性检查；
- 修复重试：恢复原 Session 进行最小修复；
- 等待人工：缺少环境、权限、信息或业务判断；
- 已完成：Verifier 已通过；
- 失败/已终止：终态，但消耗和证据仍保留。

任务详情中的“本任务工作消耗”汇总所有 Run，展示 Input、Output、Cache Read、Cache Write、总 Token、模型、LLM 调用、工具调用和总耗时。环境字段来自任务领取时的快照。

### 运行记录

每次 OpenCode 调用形成一个 Run。列表展示员工、环境、状态、Token、工具调用、时间和 Session。点击 Run 进入独立详情，可查看模型、环境快照、各 Token 字段和工具汇总。

### 人工介入

这里只显示 `WAIT_HUMAN` 任务。处理人应阅读阻塞原因，补充处理说明和继续执行所需上下文，再选择继续或终止。操作会持久化为 Event，失败前产生的 Token 和工具记录不会丢失。

## 7. 创建手工任务

在“任务中心”点击“创建任务”，填写标题、任务类型、优先级、描述、工程路径、验证命令、必需产物和完成标准。

本地环境的 `project_path` 必须是 Worker 可访问的本地目录。Linux 远程环境的 `project_path` 指远程服务器上的目录；Astra 会在远程 Workspace 中复制该目录作为任务独立源码区。

示例验证配置：

```json
{
  "project_path": "/srv/projects/nr_test_system",
  "verification": {
    "test_command": ["pytest", "tests/test_login.py", "-q"],
    "required_files": ["tests/test_login.py"],
    "expected_exit_code": 0,
    "timeout_seconds": 900
  }
}
```

不要仅凭 OpenCode 输出中的“完成”判断成功；应以任务为“已完成”且验证结果为“通过”为准。

## 8. 使用量口径

- Token 仅取 OpenCode JSON 事件中的实际字段，不根据字符数或模型规则估算。
- 总 Token 按 Input、Output、Cache Read 和 Cache Write 的实际返回值求和。
- 工具调用按 OpenCode 工具事件聚合名称、次数、成功、失败和耗时。
- 使用量先归属 Run，再聚合到任务、员工和平台。
- 执行失败、等待人工、暂停和终止前已产生的用量都会保留。
- OpenCode 未返回某项数据时显示 `—`；这与数值 `0` 含义不同。

V0.2 不计算费用、模型单价、绩效分或跨员工排名。

## 9. 接入 nr_test_system

```bash
ASTRA_NR_TEST_SYSTEM_ENDPOINT=https://nr-test.example.internal
ASTRA_NR_TEST_SYSTEM_DISCOVER_PATH=/api/astra/tasks
ASTRA_NR_TEST_SYSTEM_RESULT_PATH=/api/astra/tasks/{external_task_id}/result
ASTRA_NR_TEST_SYSTEM_TOKEN=replace-with-secret
```

Task Scout 以 `source + external_task_id` 幂等去重。正式联调前需由目标系统确认字段、认证和结果回填语义。

## 10. 验收与常见问题

```bash
./scripts/verify.sh
```

只运行隔离浏览器验收：

```bash
./scripts/e2e.sh
```

结果位于 `artifacts/playwright-report/index.html` 和 `artifacts/test-results/results.json`。

- 页面显示 `RECONNECT`：检查 `/api/health`、前端代理与 SSE 网关配置。
- 员工不领取任务：检查员工是否启用、自动领取、能力/来源匹配、并发上限和环境是否“正常”。
- 本地环境不可用：使用 Worker 运行账号执行 `<opencode_path> --version`，并检查 Workspace 权限。
- 远程环境不可用：从 Astra 运行主机使用相同账号、密钥和 Host 执行批处理 SSH，检查 `known_hosts`、网络、防火墙和远程目录权限。
- Token 显示 `—`：当前 OpenCode 事件没有提供该字段；Astra 按设计不做估算。
- 任务无法完成：检查 `input.verification.test_command`、必需文件和测试退出码。

## 11. 版本边界

- 不提供节点资源池、动态故障迁移、Kubernetes/Docker 环境编排或远程节点自动安装。
- 不提供密码认证、私钥托管、成本核算或员工绩效排名。
- 管理台没有内置登录/RBAC，必须放在可信内网或企业认证网关之后。
- CLI 暂停/终止采用阶段边界上的协作式控制，不保证中断第三方 CLI 的单条原子操作。
