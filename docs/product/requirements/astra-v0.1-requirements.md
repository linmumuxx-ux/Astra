# Astra V0.1 数字员工平台需求与技术设计

## 1. 项目目标

Astra 是一个面向测试业务的常驻型数字员工平台。

与一次对话式 Coding Agent 不同，Astra 数字员工长期在线，自主查询待处理任务，领取任务后调用现有 OpenCode 完成任务处理、执行、验证、失败修复和结果回填。

Astra 管理平台负责：

* 创建任务；
* 查看数字员工状态；
* 查看任务执行进度；
* 查看执行日志和结果；
* 暂停、继续、终止任务；
* 在无法自主完成时进行人工介入。

V0.1 仅接入 `nr_test_system`。

后续通过任务源适配器扩展：

* `nr_test`
* 其他测试管理平台
* 数据库任务
* 外部接口任务

---

# 2. 核心原则

## 2.1 数字员工长期存在，任务会话按任务隔离

数字员工长期运行：

```text
数字员工上线
    ↓
持续查询任务
    ↓
领取任务
    ↓
执行
    ↓
验证
    ↓
完成 / 等待人工
    ↓
继续领取下一任务
```

每个任务独立创建：

* 工作目录；
* OpenCode Session；
* 执行记录；
* 日志；
* 验证结果；
* 任务上下文。

禁止一个长期 OpenCode Session 连续处理所有任务。

---

## 2.2 OpenCode 是模型执行器

内部没有模型 API Key。

Astra 不直接调用大模型。

统一通过公司改装后的 OpenCode 使用模型能力：

```text
Astra Worker
    ↓
OpenCode Executor
    ↓
OpenCode
    ↓
内部模型
```

OpenCode 负责：

* 理解任务；
* 分析任务；
* 使用 Skill；
* 使用 Command；
* 调用工具；
* 修改代码；
* 执行测试；
* 分析失败；
* 修复问题。

Astra 不重复建设 Agent Framework。

---

## 2.3 主动找任务由程序完成

禁止通过 LLM 持续轮询任务。

任务发现由 Astra Task Scout 完成。

```text
Task Scout
    ↓
查询 nr_test_system
    ↓
发现 READY 任务
    ↓
导入 Astra Task Pool
    ↓
Dispatcher 分配
```

没有任务时不调用模型。

---

## 2.4 结果必须真实验证

不能因为 OpenCode 返回“任务完成”就直接将任务标记为完成。

流程必须经过 Verifier：

```text
OpenCode执行完成
    ↓
Verifier
    ↓
检查真实结果
    ↓
PASS
    ↓
COMPLETED
```

原则：

> 能通过程序验证的结果，不交给模型自行判断。

---

# 3. V0.1 使用场景

第一阶段只实现一个数字员工：

```text
Astra-01
角色：测试执行员工
```

负责从 `nr_test_system` 获取待处理任务。

首个闭环目标：

```text
nr_test_system产生任务
        ↓
Astra自动发现
        ↓
Astra-01领取
        ↓
创建任务工作区
        ↓
调用OpenCode
        ↓
完成脚本生成
        ↓
代码检视
        ↓
真实环境执行
        ↓
失败
        ↓
故障分析
        ↓
自动修复
        ↓
重新执行
        ↓
PASS
        ↓
结果验证
        ↓
回填nr_test_system
        ↓
继续领取下一任务
```

---

# 4. 系统架构

```text
┌────────────────────────────────────────┐
│             Astra Console              │
│                                        │
│ 总览 / 数字员工 / 任务 / 运行 / 人工介入 │
└───────────────────┬────────────────────┘
                    │
                 REST/SSE
                    │
┌───────────────────▼────────────────────┐
│             Astra Backend              │
│                                        │
│ Task Manager                           │
│ Employee Manager                       │
│ Run Manager                            │
│ Event Manager                          │
│ Verifier                               │
└───────┬───────────────────────┬────────┘
        │                       │
        │                       │
        ▼                       ▼
 Task Source                 Runtime
 Adapter
        │                       │
        ▼                       ▼
 nr_test_system           Task Scout
                          Dispatcher
                          Worker
                              │
                              ▼
                     OpenCode Executor
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
             CLI Executor       Server Executor
                                      后续
                    │
                    ▼
             改装后的 OpenCode
                    │
       Skill / Command / Tool / MCP
                    │
                    ▼
        测试代码 / Git / 测试环境
```

---

# 5. 技术栈

## 5.1 后端

```text
Python 3.11+
FastAPI
SQLAlchemy 2.x
Pydantic
Alembic
PostgreSQL
Redis
Celery
```

职责：

* REST API；
* 任务状态管理；
* 数字员工管理；
* 任务发现；
* 调度；
* Worker；
* OpenCode 调用；
* 执行记录；
* 验证；
* SSE 状态推送。

---

## 5.2 前端

```text
Vue 3
TypeScript
Vite

shadcn-vue
Reka UI
Tailwind CSS 4

TanStack Table
Apache ECharts
Lucide Vue

Pinia
Vue Router
VueUse
```

不使用 Element Plus 作为主 UI 框架。

Astra 使用自己的 Design System。

---

## 5.3 部署

V0.1：

```text
Docker Compose
```

包含：

```text
astra-backend
astra-worker
astra-frontend
postgres
redis
```

OpenCode 根据公司现有环境部署，不要求容器化。

---

# 6. 后端目录建议

```text
astra/
├── services/task-platform/
│   ├── app/
│   │   ├── api/
│   │   │   ├── employees.py
│   │   │   ├── tasks.py
│   │   │   ├── runs.py
│   │   │   ├── events.py
│   │   │   └── system.py
│   │   │
│   │   ├── core/
│   │   │   ├── employee/
│   │   │   ├── task/
│   │   │   ├── run/
│   │   │   └── event/
│   │   │
│   │   ├── sources/
│   │   │   ├── base.py
│   │   │   └── nr_test_system.py
│   │   │
│   │   ├── executors/
│   │   │   └── opencode/
│   │   │       ├── base.py
│   │   │       ├── cli.py
│   │   │       └── server.py
│   │   │
│   │   ├── runtime/
│   │   │   ├── scout.py
│   │   │   ├── dispatcher.py
│   │   │   ├── worker.py
│   │   │   ├── verifier.py
│   │   │   └── heartbeat.py
│   │   │
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── config/
│   │   └── main.py
│   │
│   └── tests/
│
├── frontend/
├── configs/
├── deploy/
└── README.md
```

---

# 7. 核心领域对象

## 7.1 DigitalEmployee

数字员工是长期存在的岗位实例。

主要字段：

```text
id
name
role
description

status
capabilities
source_scope

max_concurrency
current_task_count

last_heartbeat
online_since

created_at
updated_at
```

状态：

```text
OFFLINE
IDLE
WORKING
WAIT_HUMAN
PAUSED
ERROR
```

示例：

```json
{
  "id": "astra-01",
  "name": "Astra-01",
  "role": "测试执行员工",
  "status": "WORKING",
  "capabilities": [
    "script_generate",
    "script_review",
    "script_execute",
    "script_repair",
    "result_verify"
  ],
  "source_scope": [
    "nr_test_system"
  ],
  "max_concurrency": 1
}
```

V0.1 默认：

```text
max_concurrency = 1
```

---

# 8. Task

Task 是 Astra 最核心的业务对象。

字段建议：

```text
id

source
external_task_id

task_type
title
description

input
definition_of_done

priority
status

employee_id

workspace
opencode_session_id

current_phase
progress

retry_count
max_retry_count

result
failure_reason
human_required_reason

created_at
claimed_at
started_at
finished_at
updated_at
```

---

# 9. Task 状态机

V0.1 使用以下状态：

```text
CREATED
READY
CLAIMED
RUNNING
VERIFYING
RETRY
WAIT_HUMAN
PAUSED
COMPLETED
FAILED
CANCELLED
```

主要流程：

```text
CREATED
   ↓
READY
   ↓
CLAIMED
   ↓
RUNNING
   ↓
VERIFYING
   ↓
COMPLETED
```

失败处理：

```text
RUNNING
   ↓
执行失败
   ↓
RETRY
   ↓
RUNNING
```

无法自主解决：

```text
RUNNING
   ↓
WAIT_HUMAN
   ↓
人工处理
   ↓
RUNNING
```

人工控制：

```text
RUNNING → PAUSED
PAUSED  → RUNNING

READY / RUNNING / WAIT_HUMAN
        ↓
    CANCELLED
```

超过最大自动修复次数：

```text
RETRY
   ↓
达到 max_retry_count
   ↓
WAIT_HUMAN
```

---

# 10. Task Source

所有外部任务系统通过统一 Adapter 接入。

接口：

```python
class TaskSource:

    def discover_tasks(self):
        ...

    def get_task(self, external_task_id):
        ...

    def update_task(self, external_task_id, result):
        ...

    def heartbeat(self):
        ...
```

V0.1：

```text
NrTestSystemSource
```

未来：

```text
NrTestSource
WeTaskSource
DatabaseSource
```

Astra Core 不允许直接依赖 `nr_test_system` 的具体数据结构。

---

# 11. Task Scout

Task Scout 负责主动查询任务。

默认：

```text
poll_interval = 30s
```

流程：

```text
启动
 ↓
遍历启用的 TaskSource
 ↓
discover_tasks()
 ↓
转换成 Astra Task
 ↓
判断是否已存在
 ↓
不存在 → 创建
 ↓
进入 READY
```

唯一性：

```text
source + external_task_id
```

必须保证同一个外部任务不会重复导入。

Task Scout 不允许调用模型。

---

# 12. Dispatcher

Dispatcher 负责数字员工和任务匹配。

V0.1 匹配条件：

```text
员工 ONLINE / IDLE
+
当前任务数 < max_concurrency
+
员工 capability 满足 task_type
+
员工 source_scope 包含任务 source
```

任务排序：

```text
priority DESC
created_at ASC
```

领取成功：

```text
READY
 ↓
CLAIMED
```

必须通过数据库事务保证同一任务不能被多个 Worker 重复领取。

---

# 13. Worker

Worker 是数字员工实际运行载体。

Worker 长期运行。

工作循环：

```text
检查员工状态
    ↓
获取分配任务
    ↓
无任务
    ↓
等待
    ↓
继续检查
```

有任务：

```text
CLAIM
  ↓
创建 Workspace
  ↓
创建 Run
  ↓
调用 OpenCode Executor
  ↓
收集结果
  ↓
Verifier
  ↓
更新 Task
  ↓
回填 Source
  ↓
继续下一任务
```

---

# 14. Workspace

每个任务拥有独立工作目录。

建议：

```text
/workspaces/
└── TASK-20260827-001/
    ├── source/
    ├── output/
    ├── evidence/
    ├── logs/
    └── meta/
```

禁止不同任务共用一个临时目录。

Workspace 信息保存到 Task。

---

# 15. OpenCode Executor

定义统一接口：

```python
class OpenCodeExecutor:

    def start(self, task, workspace):
        ...

    def resume(self, run):
        ...

    def get_status(self, run):
        ...

    def abort(self, run):
        ...

    def collect_result(self, run):
        ...
```

实现：

```text
OpenCodeCLIExecutor
OpenCodeServerExecutor
```

V0.1 优先实现：

```text
OpenCodeCLIExecutor
```

调用方式以内部改装版本实际支持的 OpenCode CLI 为准。

禁止直接调用模型 API。

---

# 16. OpenCode Session

一个 Task 对应一个 OpenCode Session。

关系：

```text
Task
  └── Run
       └── OpenCode Session
```

保存：

```text
opencode_session_id
```

任务暂停或等待人工后继续执行时，应优先恢复原 Session。

不能创建新的 Session 后重新从头分析任务，除非原 Session 已不可恢复。

---

# 17. OpenCode 任务输入

Astra 给 OpenCode 的输入使用统一结构。

示例：

```text
当前任务：
TASK-20260827-001

任务来源：
nr_test_system

任务目标：
完成指定测试用例的自动化脚本开发与真实环境验证。

任务输入：
<原始任务信息>

工作目录：
<workspace>

完成标准：
1. 脚本生成完成；
2. 代码检视通过；
3. 在指定测试环境真实执行；
4. 测试最终结果 PASS；
5. 执行失败时允许自主分析和修复；
6. 无法自主处理时明确返回 BLOCKED；
7. 保存真实执行结果和验证证据。

请优先使用项目已有 Skill、Command 和工具完成任务。

不要仅输出分析或建议，应完成实际操作。
```

---

# 18. Run

一个 Task 可以产生多个 Run。

字段：

```text
id
task_id
employee_id

run_number
status

executor_type
opencode_session_id

started_at
finished_at

exit_code
result

created_at
```

例如：

```text
Task
├── Run 1 FAILED
├── Run 2 FAILED
└── Run 3 PASS
```

用于后续统计：

* 自动修复次数；
* 平均重试次数；
* 自主完成率。

---

# 19. Event

所有关键状态变化必须形成事件。

字段：

```text
id
task_id
employee_id
run_id

event_type
phase
message
detail

created_at
```

示例：

```text
TASK_CREATED
TASK_CLAIMED
WORKSPACE_CREATED
OPENCODE_STARTED
SCRIPT_GENERATED
CODE_REVIEWED
EXECUTION_STARTED
EXECUTION_FAILED
FAULT_ANALYZED
REPAIR_COMPLETED
RETRY_STARTED
EXECUTION_PASSED
VERIFY_STARTED
VERIFY_PASSED
WAIT_HUMAN
TASK_COMPLETED
```

前端执行时间线基于 Event 渲染。

---

# 20. Verifier

Verifier 必须独立于 OpenCode。

统一接口：

```python
class TaskVerifier:

    def verify(self, task, workspace):
        ...
```

返回：

```json
{
  "passed": true,
  "items": [],
  "evidence": []
}
```

首个测试脚本任务至少验证：

```text
目标文件存在
目标测试类存在
代码检视完成
测试真实执行
执行返回结果有效
最终结果 PASS
验证证据存在
```

Verifier 失败：

```text
可修复
 ↓
RETRY

不可修复
 ↓
WAIT_HUMAN / FAILED
```

---

# 21. Evidence

任务完成必须保存证据。

建议：

```text
evidence/
├── execution.log
├── opencode_output.json
├── verify_report.json
├── test_result.json
└── artifacts/
```

Task Detail 页面展示证据清单。

---

# 22. 人工介入

当出现以下情况时进入：

```text
WAIT_HUMAN
```

例如：

* 测试环境不可用；
* 权限不足；
* 业务信息缺失；
* 超过最大自动修复次数；
* 需要人工业务判断；
* OpenCode 无法继续。

保存：

```text
human_required_reason
current_phase
workspace
opencode_session_id
last_error
```

人工操作：

```text
继续
终止
修改任务输入
补充信息
```

继续后：

```text
WAIT_HUMAN
   ↓
RUNNING
```

优先恢复原 Session。

---

# 23. Heartbeat

数字员工必须定期发送 Heartbeat。

默认：

```text
10s
```

后台根据：

```text
last_heartbeat
```

判断状态。

超过：

```text
60s
```

未收到 Heartbeat：

```text
Employee → OFFLINE
```

其正在执行任务暂不自动转移。

V0.1 只标记异常并等待人工处理。

后续版本再支持 Lease 和任务接管。

---

# 24. API

## Employee

```text
GET    /api/employees
GET    /api/employees/{id}
POST   /api/employees
PATCH  /api/employees/{id}
POST   /api/employees/{id}/pause
POST   /api/employees/{id}/resume
```

---

## Task

```text
GET    /api/tasks
POST   /api/tasks
GET    /api/tasks/{id}

POST   /api/tasks/{id}/pause
POST   /api/tasks/{id}/resume
POST   /api/tasks/{id}/cancel
POST   /api/tasks/{id}/handoff
POST   /api/tasks/{id}/retry
```

---

## Run

```text
GET /api/tasks/{id}/runs
GET /api/runs/{id}
```

---

## Event

```text
GET /api/tasks/{id}/events
```

---

## Evidence

```text
GET /api/tasks/{id}/evidence
```

---

## Realtime

```text
GET /api/events/stream
```

使用：

```text
Server-Sent Events
```

前端不要求 WebSocket。

---

# 25. 前端页面

V0.1 实现以下页面：

```text
总览
数字员工
任务中心
任务详情
运行记录
人工介入
配置中心
```

其中首期重点完成：

```text
总览
数字员工详情
任务中心
任务详情
```

---

# 26. 页面一：总览

展示：

## 顶部指标

```text
在线员工
运行中任务
等待人工
今日完成
```

## 数字员工状态

员工卡展示：

```text
员工头像
员工名称
角色
状态
当前任务
工作时长
成功率
```

## 当前活跃任务

字段：

```text
任务ID
任务类型
来源
状态
分配员工
进度
```

## 系统动态

展示最近 Event。

例如：

```text
任务领取
执行开始
修复重试
验证通过
需要人工介入
```

## 今日任务趋势

展示：

```text
创建任务
完成任务
失败任务
```

---

# 27. 页面二：数字员工详情

展示：

## 员工信息

```text
头像
名称
岗位
当前状态
在线时长
能力
任务来源范围
```

## 当前任务

```text
任务ID
任务标题
来源
当前阶段
开始时间
Workspace
OpenCode Session ID
整体进度
```

操作：

```text
查看任务详情
暂停
转人工
```

## 运行状态

时间线：

```text
任务认领
获取上下文
脚本生成
首次执行
故障分析
脚本修复
再次执行
结果验证
```

## 今日处理记录

字段：

```text
任务ID
任务类型
状态
耗时
结果
```

## 能力与绩效

V0.1 指标：

```text
自主完成率
人工介入率
平均重试次数
任务通过率
```

---

# 28. 页面三：任务中心

顶部：

```text
搜索
来源
任务类型
状态
优先级
分配员工
时间范围
```

按钮：

```text
创建任务
```

指标：

```text
待领取
运行中
等待人工
今日完成
```

任务表字段：

```text
任务ID
任务标题
来源
类型
优先级
状态
分配员工
当前阶段
进度
创建时间
操作
```

操作：

```text
详情
暂停
终止
转人工
重试
```

右侧展示：

```text
状态分布
来源分布
员工工作量
```

底部异常提示：

```text
超时任务
验证失败
等待人工过久
```

---

# 29. 页面四：任务详情

顶部：

```text
当前状态
当前阶段
分配员工
已运行时长
```

## 任务信息

```text
任务ID
标题
来源
优先级
完成标准
关联对象
```

操作：

```text
暂停
继续
终止
转人工
```

## 执行时间线

基于 Event 展示：

```text
任务创建
任务领取
获取上下文
生成脚本
代码检视
首次执行失败
故障分析
自动修复
二次执行通过
结果验证
```

## 实时运行日志

展示：

```text
时间
日志级别
员工
阶段
日志内容
```

支持自动滚动和暂停滚动。

## 验证结果

展示：

```text
验证项
状态
详情
验证时间
```

## 关联对象

展示：

```text
数字员工
Workspace
OpenCode Session ID
来源任务ID
证据产物
```

---

# 30. Astra Design System

视觉目标：

> 深色运行控制台 + 数字员工工作台。

不要做成普通后台系统换暗色主题。

---

## 30.1 整体风格

采用：

```text
Dark UI
少量玻璃质感
低强度 Glow
蓝色主色
紫色辅助
绿色成功
橙色人工介入
红色失败
```

实际开发的科技感控制在原型图约 60%。

避免：

* 大面积霓虹；
* 强烈发光；
* 每个 Panel 都渐变；
* 游戏 HUD 风格。

---

## 30.2 Design Token

统一维护：

```text
--astra-bg-base
--astra-bg-sidebar
--astra-bg-panel
--astra-bg-card

--astra-border
--astra-border-hover

--astra-primary
--astra-secondary

--astra-success
--astra-warning
--astra-danger
--astra-info

--astra-text-primary
--astra-text-secondary
--astra-text-muted
```

业务组件禁止随意硬编码颜色。

---

# 31. 自定义组件

优先建设：

```text
AstraPanel
AstraMetricCard
AstraStatusBadge
AstraProgress
AstraEmptyState

EmployeeAvatar
EmployeeCard
EmployeeStatus

TaskStatus
TaskTable
TaskProgress

RunTimeline
RunLog

VerifyResult
EvidenceCard

StatusPulse
```

shadcn-vue / Reka UI 主要作为基础交互组件。

不要让页面直接大量依赖具体组件库风格。

---

# 32. 前端目录建议

```text
frontend/
├── src/
│   ├── api/
│   │   ├── employee.ts
│   │   ├── task.ts
│   │   ├── run.ts
│   │   └── system.ts
│   │
│   ├── components/
│   │   ├── astra/
│   │   ├── employee/
│   │   ├── task/
│   │   └── runtime/
│   │
│   ├── views/
│   │   ├── DashboardView.vue
│   │   ├── EmployeeListView.vue
│   │   ├── EmployeeDetailView.vue
│   │   ├── TaskListView.vue
│   │   ├── TaskDetailView.vue
│   │   ├── RunListView.vue
│   │   └── InterventionView.vue
│   │
│   ├── stores/
│   ├── composables/
│   ├── styles/
│   │   ├── tokens.css
│   │   ├── theme.css
│   │   └── animations.css
│   │
│   ├── router/
│   └── main.ts
```

---

# 33. 配置

建议：

```text
configs/
├── astra.yaml
├── employees.yaml
└── sources.yaml
```

`astra.yaml`

```yaml
runtime:
  scout_interval: 30
  heartbeat_interval: 10
  heartbeat_timeout: 60

task:
  default_max_retry_count: 3

executor:
  type: opencode_cli
```

---

`employees.yaml`

```yaml
employees:
  - id: astra-01
    name: Astra-01
    role: 测试执行员工

    enabled: true
    max_concurrency: 1

    capabilities:
      - script_generate
      - script_review
      - script_execute
      - script_repair
      - result_verify

    sources:
      - nr_test_system
```

---

`sources.yaml`

```yaml
sources:
  - id: nr_test_system
    type: nr_test_system
    enabled: true

    endpoint: http://localhost:8000

    poll_interval: 30
```

---

# 34. 日志

使用结构化日志。

每条日志至少包含：

```text
timestamp
level
employee_id
task_id
run_id
phase
message
```

禁止依赖纯文本日志作为任务状态来源。

任务状态以数据库为准。

日志只用于运行观察和问题定位。

---

# 35. 数据统计

V0.1 提供：

## 员工指标

```text
在线时长
处理任务数
完成任务数
自主完成率
人工介入率
任务通过率
平均任务耗时
平均重试次数
```

## 平台指标

```text
在线员工
运行中任务
待领取任务
等待人工任务
今日完成
今日失败
```

---

# 36. V0.1 不做的内容

以下能力暂不实现：

```text
Temporal
LangGraph
Agent Registry
多 Agent 协作
Agent-to-Agent
自动员工扩缩容
跨 Worker 任务接管
复杂权限系统
Keycloak
OPA
MCP Gateway
长期记忆平台
知识图谱
自动能力学习
多模型调度
复杂工作流设计器
```

有实际需求后再增加。

---

# 37. 开发优先级

## Phase 1：最小运行闭环

必须先打通：

```text
手工创建 Astra Task
      ↓
Astra-01 自动领取
      ↓
OpenCode CLI执行
      ↓
获得结果
      ↓
Verifier验证
      ↓
COMPLETED
```

完成标准：

> 在无人继续对话的情况下，一条任务可以自动完成。

---

## Phase 2：接入 nr_test_system

实现：

```text
NrTestSystemSource
Task Scout
任务导入
结果回填
```

达到：

```text
nr_test_system
      ↓
Astra自动发现
      ↓
自动执行
      ↓
自动回填
```

---

## Phase 3：失败修复闭环

增加：

```text
执行失败
 ↓
OpenCode分析
 ↓
自动修复
 ↓
重新执行
 ↓
验证
```

增加：

```text
retry_count
max_retry_count
```

---

## Phase 4：暂停与人工介入

实现：

```text
WAIT_HUMAN
PAUSED
RESUME
CANCELLED
```

能够恢复原：

```text
Workspace
OpenCode Session
任务上下文
```

---

## Phase 5：管理页面

依次实现：

```text
任务详情
任务中心
数字员工详情
总览
```

先保证运行能力，再完成完整运营页面。

---

# 38. 首个验收场景

最终必须完成以下真实 Demo：

```text
1. nr_test_system 中出现一条待开发测试任务。

2. 无人工操作 Astra。

3. Task Scout 自动发现该任务。

4. Astra-01 自动领取。

5. Astra 创建独立 Workspace。

6. Astra 调用改装后的 OpenCode。

7. OpenCode 使用现有 Skill / Command 完成脚本生成。

8. 自动执行脚本。

9. 首次执行失败。

10. OpenCode 自动分析失败。

11. 修改脚本。

12. 再次执行。

13. 测试 PASS。

14. Astra Verifier 独立验证执行结果。

15. 保存执行证据。

16. Task 状态更新为 COMPLETED。

17. 结果回填 nr_test_system。

18. Astra-01 自动恢复 IDLE。

19. Astra-01 继续寻找下一条任务。
```

整个过程中：

> 不需要用户打开 OpenCode 与 Agent 持续对话。

这是 Astra V0.1 是否成立的核心验收标准。

---

# 39. Codex 开发约束

开发过程中遵守以下原则：

1. 不为了“Agent 化”重新实现 OpenCode 已有能力。
2. 不直接接入任何模型 API。
3. OpenCode 必须通过 Executor Adapter 调用。
4. `nr_test_system` 必须通过 Task Source Adapter 接入。
5. Task 是系统核心对象，不以聊天 Session 为核心建模。
6. 每个任务必须拥有独立 Workspace。
7. 每个任务独立维护 OpenCode Session。
8. 所有关键状态必须持久化。
9. 前端刷新后必须能够恢复真实任务状态。
10. 任务完成必须经过 Verifier。
11. 不允许 OpenCode 自己轮询任务源。
12. 不允许使用 LLM 完成可以程序化判断的状态检查。
13. V0.1 保持简单，不提前引入 Temporal、LangGraph 等复杂基础设施。
14. 新增外部依赖前先确认是否确有必要。
15. 后端核心逻辑必须具备单元测试。
16. 状态流转必须集中管理，不允许页面或 Worker 任意修改状态。
17. 所有任务状态变化必须记录 Event。
18. 保持模块边界清晰，避免 `nr_test_system`、OpenCode 和 Astra Core 相互耦合。

---

# 40. 最终目标

Astra V0.1 不追求建立完整的数字员工平台。

第一阶段只验证一件事：

> **一个长期在线的数字员工，可以在没有人工持续对话的情况下，主动发现测试任务，自主完成处理、执行、修复和验证，并持续处理下一项工作。**

当这一闭环稳定后，再扩展：

```text
更多任务源
更多数字员工
更多岗位
更复杂任务
任务接管
员工权限
运行治理
绩效管理
数字员工规模化运行
```
