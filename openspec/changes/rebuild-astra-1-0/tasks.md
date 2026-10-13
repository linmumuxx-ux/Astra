产品范围以 `docs/astra-1.0/SLIM_BASELINE.md` 为准。未验证的项保持未勾选。Post-1.0 不作为 1.0 完成条件。

## 1. 基线与契约

- [x] 1.1 核对远端、固定起点并建立独立分支，原未提交设计包保持不变。
- [ ] 1.2 架构、问题清单和本清单与瘦身基线一致；垂直切片的契约可对照 `docs/astra-1.0/contracts.md`。OpenSpec validate 通过。不把 Post-1.0 写成 1.0 门禁。

## 2. 垂直切片前半：对话、唤醒、建 Task

- [ ] 2.1 Human↔Employee 长期 DM：持久消息、成员 ACL、引用因果；其他私人 Channel 不注入当前回复。附件与企业 IM Binding 不在本项。
- [ ] 2.2 Inbox/Routine 唤醒：SourceEvent 与 InboxAdmission 分离；观察与处理结论分开提交；到期 Routine 经短 Persona 决策。外部连接器不在本项。
- [ ] 2.3 创建 Task：业务主责是 Employee；Task 保存目标与原始验收标准。Worker 不承担岗位人格。

## 3. 垂直切片后半：执行、验收、一张批准卡

- [ ] 3.1 Worker 用固定 OpenCode 执行：TaskExecution 只索引 Session、Workspace、尝试、终态和证据；lease/fence 保证旧 attempt 不回写新轮次。
- [ ] 3.2 独立验收：Worker 自报完成不能把 Task 标完成；人类或另一员工按原生证据逐条复验后才闭环。
- [ ] 3.3 一张风险写入的人类批准卡：Role 上限 ∩ 该员工工程授权 ∩ 人类批准。批准绑定目标版本、策略版本和有效期，批准不等于执行。五层策略全量交集、成本看板和 API 网关硬配额不在本项。

## 4. 新应用路径与切片完成

- [ ] 4.1 新 `apps/api`、`apps/web`、`domains/*` 不把 `backend/` 或 `frontend/` 当作运行入口，也不提供 0.xx 业务 API。`deploy/systemd/` 里指向旧 `backend` 的单元不得再作为新应用的启动说明。
- [ ] 4.2 写明旧 `backend/`、`frontend/` 的删除计划。切换完成前不删除这两棵树。
- [ ] 4.3 用状态驱动空间（2.5D 或 DOM 即可）走通 DM、建 Task、执行状态、独立验收和一张批准卡。正式 Three.js WebGL 三维首页不是本项。
- [ ] 4.4 同一条真实链跑通第 2、3 节和第 4.1 节：DM → Inbox/Routine 唤醒 → 创建 Task → OpenCode 执行 → 独立验收 → 一张风险写入批准卡，且旧轮次不覆盖新轮次。
- [ ] 4.5 按该切片核实后才可标记 1.0 完成。不以「全部页面 + 原设计全部门禁同时变绿」为完成条件。

## Post-1.0

以下保持未勾选。它们来自瘦身前的全量清单，不再阻塞 1.0。

- [ ] P.1 正式 Three.js WebGL 三维数字空间首页，以及专为该首页设置的 2D 降级、减少动态和离线资源门禁。
- [ ] P.2 企业 IM 渠道 Binding、受控附件存储、订阅与通知偏好。
- [ ] P.3 Skill 提案 → Worker 验证 → 审批 → 发布 → 观察 → 回滚，以及成熟 Wiki/Experience 提取。
- [ ] P.4 治理成本看板、模型 API 网关硬配额、外部副作用执行总账。
- [ ] P.5 五层策略全量交集；pause/stop/takeover、同级指令冲突裁决、完整多员工并行与跨岗复验。
- [ ] P.6 全部页面与原设计全部门禁同时验收；团队 Channel 全交互、组织调岗与 Goal 运营、图书馆全流程。
- [ ] P.7 DeepSeekBot、Grok 或 OpenClaw 隐喻下、超出 OpenCode Session/Event 的额外运行语义。
- [ ] P.8 公司环境全量 ETL：真实旧库与 Session/Workspace/知识/Skill/会话逐类签收，公司 Linux 全服务部署；切换完成后删除旧 `backend/` 与 `frontend/` 运行树。一次性迁移工具保持独立，不在 1.0 引入业务 API 兼容层。
