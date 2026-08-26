# Astra V0.2 实现与需求映射

## 交付结论

V0.2 在 V0.1 任务闭环上补齐了“员工固定执行环境”和“真实工作量采集”两条链路。实现保持 Task 为核心对象、状态机为唯一状态入口、OpenCode 只负责执行、Verifier 独立判定完成。

## 默认执行环境

| 需求 | 实现 |
| --- | --- |
| 每员工一个默认环境 | `opencode_execution_environments.employee_id` 唯一约束和一对一关系 |
| 本地或 Linux 远程 | `ExecutionMode.LOCAL / LINUX_REMOTE` |
| 环境状态独立 | `UNKNOWN / CHECKING / AVAILABLE / UNAVAILABLE`，不复用员工状态 |
| 分项检测 | 本地：二进制、启动、Workspace；远程：SSH、Workspace、二进制、启动 |
| 远程认证安全 | 仅 SSH Agent 或 Key 路径，不接受密码，不保存私钥内容 |
| 任务选择环境 | Dispatcher 先匹配员工，再使用其唯一默认环境；环境非正常不领取 |
| 历史可追溯 | 领取时保存 Task 环境快照，创建 Run 时再次固化；后续配置更新不覆盖历史 |
| 远程执行 | 系统 SSH + BatchMode，远程创建任务目录、复制远程工程、运行 OpenCode 和 Verifier |
| 自主策略 | 自动领取、自动执行、自动修复、最大重试和最大并发 |

V0.2 没有引入节点池、资源调度、动态故障迁移、Kubernetes/Docker 环境编排或远程节点自动安装。

## 工作量采集

| 需求 | 实现 |
| --- | --- |
| Token 来源真实 | 解析 `opencode run --format json` 返回事件，不做字符数或模型估算 |
| Token 字段 | Input、Output、Cache Read、Cache Write、Total |
| 模型与 LLM 调用 | Run 保存 `model_name` 与实际包含 usage 的调用次数 |
| 工具调用 | 解析工具名、调用 ID、状态和时间；按 Run/工具聚合次数、成功、失败、耗时 |
| 数据归属 | 原始数据落 Run/ToolUsage，再聚合 Task、Employee、Platform |
| 异常保留 | Run 在暂停、终止、失败或等待人工判断前先持久化已产生的用量 |
| 缺失语义 | OpenCode 未提供的字段为 `NULL`，前端显示 `—`，与 `0` 区分 |
| 展示 | 总览、员工列表/详情、任务详情、Run 列表/详情、7/30 天趋势和工具 Top |

总 Token 使用 OpenCode 实际返回的 Input、Output、Cache Read 和 Cache Write 之和。V0.2 不计算费用、模型单价、员工绩效分或排名。

## 数据库升级

Alembic `0002_astra_v02` 支持 V0.1 → V0.2：

- 为员工补充技能和自主策略；
- 为存量员工回填默认本地环境；
- 为 Task/Run 补充环境快照；
- 为 Run 补充模型和用量字段；
- 新建工具使用量表。

迁移已使用临时 V0.1 SQLite 数据库验证，存量员工成功回填 `LOCAL / UNKNOWN` 环境，最终版本为 `0002_astra_v02`。

## API 与管理台

新增或扩展的主要接口：

- `POST /api/employees`
- `PATCH /api/employees/{id}`
- `PUT /api/employees/{id}/environment`
- `POST /api/employees/{id}/environment/test`
- `GET /api/employees/{id}/usage?days=7|30`
- `GET /api/tasks/{id}/usage`
- `GET /api/runs/{id}`
- `GET /api/runs/{id}/usage`

配置变更通过 Event 留痕。环境快照只保存非秘密执行参数。

## 已验证边界

- 后端测试覆盖状态机、来源幂等、环境调度、真实 Verifier、同 Session 修复、使用量解析和远程 Workspace 路由。
- 浏览器 E2E 覆盖核心导航、任务控制、人工介入、员工环境创建/检测、任务用量与 Run 详情。
- 远程 SSH 的真实目标机连通性依赖部署现场，需按《部署手册》在目标 Linux 环境验收。
- `nr_test_system` 正式接口仍需对端确认字段映射、认证与回填契约。
