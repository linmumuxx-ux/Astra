# Astra 1.0 架构落地现状

产品范围以 `SLIM_BASELINE.md` 为准：1.0 完成是一条垂直切片，不是原设计包全部章节同时验收。本文件只记录实现现状。起点提交与已取代设计包的 SHA256 见 `baseline.json`。实施清单只有 `openspec/changes/rebuild-astra-1-0/tasks.md`。

## 新运行边界

| 位置 | 当前职责 | 相对垂直切片尚未闭环 |
| --- | --- | --- |
| `apps/api` | 新 `/api/v1`、认证、REST/SSE、强类型写入、独立运维入口 | 切片仍须确认新入口不暴露旧运行树。原生 Workspace 受权代理、跨主机执行接线为 post-1.0 |
| `apps/web` | Vue3 / Element Plus 九类页面、本地 Three.js、DOM 业务操作 | 切片要能走 DM、建 Task、执行与验收、一张批准卡。正式 WebGL 三维首页为 post-1.0；状态驱动空间即可 |
| `apps/services` | 独立 Celery/Beat、Routine、短 Persona、工程运行器与独立员工验收，不使用旧队列 | 切片要把 Routine/Inbox 唤醒接到建 Task 与执行。Goal 跟踪、接管、完整多员工协作为 post-1.0 |
| `domains/identity` | Actor / Credential / WorkspaceGrant，短事务重新认证 | 切片使用现有认证与工程授权。人员完整权限模板与组织运维为 post-1.0 |
| `domains/organization` | Team / Role / Employee / Goal，员工生命周期、岗位权限上限 | 切片要求 Employee 担任 Task 业务主责。调岗、责任清点、目标运营指标为 post-1.0 |
| `domains/personas` | SourceEvent / Inbox / Routine / Turn lease/fencing，持久输入引用、观察/处理区分 | 切片要求来源、关注、观察、处理继续分离。外部连接器与完整预算/冲突处置为 post-1.0 |
| `domains/messaging` | 持久 DM/Group、引用/@、成员 ACL、因果链/TTL/去重 | 切片只要求 Human↔Employee DM。附件、企业 IM Binding、同级指令冲突裁决为 post-1.0 |
| `domains/work` | Task、交接提出/澄清/拒绝/撤回/签收、执行、逐条独立验收/原 Task 产物续做 | 切片要求创建 Task、执行索引和独立验收。跨主机产物转移、Goal 跟踪、完整交接产品为 post-1.0 |
| `domains/runtime` | 固定 OpenCode 1.19.0、原生 Session/SSE、本地 worktree、Worker lease、SSH 传输 | 切片要求 Worker 以 OpenCode 执行且旧轮次不回写。远程工作区、完整接管、公司全服务恢复为 post-1.0 |
| `domains/governance` | 幂等、审批、版本复验、审计、历史内容哈希读取 | 切片要求一张风险写入批准卡（Role 上限 ∩ 工程授权 ∩ 人类批准）。成本配额、副作用总账、完整运维治理为 post-1.0 |
| `domains/knowledge` | 资料/Skill 模型、个人 Git Memory、来源校验、CAS 版本/diff/恢复/过期 | 已有 Memory 可保留，但不是切片门禁。Skill 验证审批发布回滚全链路为 post-1.0 |
| `agents` | 独立 Persona 指令与十三个认证 MCP Tool | 切片沿用已接通的建 Task、消息、验收与准备操作。完整 Skill/知识 Tool 为 post-1.0 |
| `migrations/schema` | 静态初始 1000 + Persona 1001 + 执行意图/基线 1002 + 不可变产物/续做来源 1003，拒绝旧库覆盖 | 切片不增加 0.xx 兼容字段。与切片无关的新领域迁移为 post-1.0 |
| `migrations/from_0xx` | 离线导出、显式映射、正式导入、账本恢复与对账 | 工具保持一次性、不进入业务 API。真实旧库签收与公司切换为 post-1.0 |

新 API / Tool / 领域服务不导入旧 `backend.app`、旧 `app` 或一次性迁移工具。此边界由 AST 检查验证。旧代码尚保留作选择性复制与迁移来源，当前没有执行正式切换或删除旧树。

## 单一业务事实

- Employee 使用独立 Actor ID，岗位、职责、预算和生命周期属于业务域；没有 `worker_id` 固定主机绑定。Worker 是资源池节点，不承担岗位人格。
- Task 保存业务主责、目标、原始验收标准和闭环状态。TaskExecution 仅保存 Worker/原生 Session/Workspace/尝试/终态/证据索引；原生消息和 Tool 结果不复制为 Astra Transcript。
- Channel/Message 是长期交流事实。SourceEvent 只引用来源，InboxAdmission 保存关注关系；投递不等于阅读或处理。交接处理原文作为不可变 SourceEvent 保存，签收前不转移主责。
- 已实现的授权会把组织强制规则、Role 权限、Employee 权限/工程范围、当前 WorkspaceGrant 逐次取交集。人类管理员也不能绕过组织禁止动作或特定工程 Grant；管理员不能读取非参与者的私人 DM / PRIVATE 历史档案。1.0 完成只把门禁收成 Role 上限 ∩ 员工工程授权 ∩ 人类批准；五层策略全量交集不是切片完成条件。已实现的更严检查保留，不回退。
- 所有写入在请求认证后再次锁定主体与凭据，带稳定幂等键；缓存重放也复验当前权限。具体审批固定目标版本、策略版本和有效期，批准时复验发起人当前工程授权。
- Persona 与 Worker 各自使用数据库 lease/fence；旧 Turn/attempt 不得回写新轮次。过期 Worker 槽保留为待对账，不释放给新任务，不盲重跑未知副作用。
- 网络、Git/文件和模型 I/O 不在数据库行锁内执行。历史文件先授权、事务外读取并核验哈希，再复验当前认证和内容索引。

## 当前行为与状态

Routine 到期、DM/@、外部 SourceEvent 和正式交接变化可以进入 Inbox。Celery/Beat 通过指定团队 SYSTEM 身份扫描职责与有效 Inbox；Persona 使用单独目录、禁用工具的短 OpenCode Session，返回有限 JSON 决策，后端严格校验再执行业务服务。观察与用量单独提交；业务动作、处理结论和 Turn 完成原子提交。超时保留原生绑定，恢复只查询、不重发 prompt。

每回合只合并同一私人 Channel；读取同 Channel 最近消息。其他私人 Channel 产生的计划和记忆不注入当前回复上下文。个人记忆的来源并集不会在模型改写时丢失；数据库 head 决定可见 Git 版本，构造提交不等于发布。其他团队成员无法读取员工私人状态、Inbox 或 Memory。

INTERVAL/CRON 的下次时间由后端计算，EVENT 不参与时间扫描；积压汇总一条并推进到未来，暂停员工不投递到期唤醒。预算在新增回合前检查真实已记录用量及未对账回合预留，不把未知用量当成零；这是停止新增推理的门禁，不代替模型网关的硬配额。

Task 派工提交 Worker 租约与 `BOUND` 执行绑定，Task 进入 `DISPATCHED`；独立工程运行器随后创建固定 worktree 和原生 Session，核验稳定输入后才标 RUNNING。真实原生结果进入 REVIEW，独立人类/员工验收接口逐条重新核验证据后才能完成。运行中暂停/取消保留 `RECONCILE_REQUIRED`，不会把未确认 abort 当成已取消。`SUBMITTED` 对账结果只进入 `REVIEW`，不能凭 Worker 自报完成。

真实短回合、跨 Session Memory、Redis/Celery/Beat、原生执行和独立验收已在隔离环境分项通过，详见验证报告。这些分项还没有作为 `SLIM_BASELINE.md` 的同一条垂直切片关闭。Skill 全链路、模型网关硬配额、企业 IM、正式三维首页、公司全量切换属于 post-1.0，不阻塞该切片。页面存在不代表切片已签收。旧 `backend/`、`frontend/` 仍留在仓库作复制来源；删除计划见实施清单，本文件不宣布已经删除。
