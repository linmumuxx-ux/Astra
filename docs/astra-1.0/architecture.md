# Astra 1.0 架构落地现状

唯一产品基线为用户提供的 `docs/Astra_1.0/Astra_1.0_全新架构与产品交互设计.md`，本文件记录实现现状，不缩减其中要求。起点与原设计包 SHA256 见 `baseline.json`。实施清单只有 `openspec/changes/rebuild-astra-1-0/tasks.md`。

## 新运行边界

| 位置 | 当前职责 | 尚未闭环部分 |
| --- | --- | --- |
| `apps/api` | 新 `/api/v1`、认证、REST/SSE、强类型写入、独立运维入口 | 原生 Workspace 受权代理、完整执行服务接线 |
| `apps/web` | Vue3 / Element Plus 九类页面、本地 Three.js、DOM 业务操作 | 依赖后端未实现能力的正式交互 |
| `apps/services` | 独立 Celery/Beat、Routine 投递、短 Persona 原生决策及恢复，不使用旧队列 | 完整自主验收、返工跟踪、接管及多员工协作闭环 |
| `domains/identity` | Actor / Credential / WorkspaceGrant，短事务重新认证 | 人员完整权限模板与组织运维流程 |
| `domains/organization` | Team / Role / Employee / Goal，员工生命周期、岗位权限上限 | 调岗与责任清点完整流程、目标运营指标 |
| `domains/personas` | SourceEvent / Inbox / Routine / Turn lease/fencing，持久输入引用、观察/处理区分 | 连接器、完整预算/冲突与异常处置 |
| `domains/messaging` | 持久 DM/Group、引用/@、成员 ACL、因果链/TTL/去重 | 附件存储、外部 Binding、同级指令冲突裁决 |
| `domains/work` | Task、交接提出/澄清/拒绝/撤回/签收、执行与验收模型 | Persona 自主验收与返工/跟踪自动闭环 |
| `domains/runtime` | OpenCode 控制/SSE/Session 树、本地安全 worktree、Worker lease/资产锁 | SSH/Windows 提取、完整接管、副作用对账及公司恢复验证 |
| `domains/governance` | 幂等、审批、版本复验、审计、历史内容哈希读取 | 外部副作用执行账本、成本配额与完整运维治理 |
| `domains/knowledge` | 资料/Skill 模型、个人 Git Memory、来源校验、CAS 版本/diff/恢复/过期 | 成熟知识实现复制整合、验证审批发布回滚全链路 |
| `agents` | 独立 Persona 指令与十三个认证 MCP Tool | Routine、知识/Skill 等完整业务 Tool |
| `migrations/schema` | 静态初始 1000 + Persona 1001 + 执行意图/基线 1002，拒绝旧库覆盖 | 其他新增领域迁移 |
| `migrations/from_0xx` | 离线导出、显式映射、正式导入、账本恢复与对账 | 外部资产及 Skill 正式迁移、真实旧库签收 |

新 API / Tool / 领域服务不导入旧 `backend.app`、旧 `app` 或一次性迁移工具。此边界由 AST 检查验证。旧代码尚保留作选择性复制与迁移来源，当前没有执行正式切换或删除旧树。

## 单一业务事实

- Employee 使用独立 Actor ID，岗位、职责、预算和生命周期属于业务域；没有 `worker_id` 固定主机绑定。Worker 是资源池节点，不承担岗位人格。
- Task 保存业务主责、目标、原始验收标准和闭环状态。TaskExecution 仅保存 Worker/原生 Session/Workspace/尝试/终态/证据索引；原生消息和 Tool 结果不复制为 Astra Transcript。
- Channel/Message 是长期交流事实。SourceEvent 只引用来源，InboxAdmission 保存关注关系；投递不等于阅读或处理。交接处理原文作为不可变 SourceEvent 保存，签收前不转移主责。
- 组织强制规则、Role 权限、Employee 权限/工程范围、当前 WorkspaceGrant 逐次取交集。人类管理员也不能绕过组织禁止动作或特定工程 Grant；管理员不能读取非参与者的私人 DM / PRIVATE 历史档案。
- 所有写入在请求认证后再次锁定主体与凭据，带稳定幂等键；缓存重放也复验当前权限。具体审批固定目标版本、策略版本和有效期，批准时复验发起人当前工程授权。
- Persona 与 Worker 各自使用数据库 lease/fence；旧 Turn/attempt 不得回写新轮次。过期 Worker 槽保留为待对账，不释放给新任务，不盲重跑未知副作用。
- 网络、Git/文件和模型 I/O 不在数据库行锁内执行。历史文件先授权、事务外读取并核验哈希，再复验当前认证和内容索引。

## 当前行为与状态

Routine 到期、DM/@、外部 SourceEvent 和正式交接变化可以进入 Inbox。Celery/Beat 通过指定团队 SYSTEM 身份扫描职责与有效 Inbox；Persona 使用单独目录、禁用工具的短 OpenCode Session，返回有限 JSON 决策，后端严格校验再执行业务服务。观察与用量单独提交；业务动作、处理结论和 Turn 完成原子提交。超时保留原生绑定，恢复只查询、不重发 prompt。

每回合只合并同一私人 Channel；读取同 Channel 最近消息。其他私人 Channel 产生的计划和记忆不注入当前回复上下文。个人记忆的来源并集不会在模型改写时丢失；数据库 head 决定可见 Git 版本，构造提交不等于发布。其他团队成员无法读取员工私人状态、Inbox 或 Memory。

INTERVAL/CRON 的下次时间由后端计算，EVENT 不参与时间扫描；积压汇总一条并推进到未来，暂停员工不投递到期唤醒。预算在新增回合前检查真实已记录用量及未对账回合预留，不把未知用量当成零；这是停止新增推理的门禁，不代替模型网关的硬配额。

Task 派工提交 Worker 租约与 `BOUND` 执行绑定，Task 进入 `DISPATCHED`；独立工程运行器随后创建固定 worktree 和原生 Session，核验稳定输入后才标 RUNNING。真实原生结果进入 REVIEW，独立人类/员工验收接口逐条重新核验证据后才能完成。运行中暂停/取消保留 `RECONCILE_REQUIRED`，不会把未确认 abort 当成已取消。`SUBMITTED` 对账结果只进入 `REVIEW`，不能凭 Worker 自报完成。

真实短回合/跨 Session Memory/Redis/Celery/Beat 已在隔离本机通过；完整自主返工跟踪与知识成长、模型网关、资源治理和公司环境仍有缺口，详见验证报告。页面存在不代表全部产品能力已签收。
