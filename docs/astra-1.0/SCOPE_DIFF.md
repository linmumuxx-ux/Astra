# 瘦身基线相对原完整设计的差异

原基线是未纳入仓库的设计包（`Astra_1.0_全新架构与产品交互设计.md` 及同包任务书、原型；SHA256 见 `baseline.json`），并被写成「全部章节、全部页面、全部门禁同时完成」。现行产品基线是 `SLIM_BASELINE.md`。

## 保留

- Employee 与 Worker 分离。
- SourceEvent / InboxAdmission 与观察、处理分离。
- Task 业务主责是 Employee；执行是 Worker / TaskExecution。
- 独立、基于证据的验收；Worker 自报完成无效。
- 不设 0.xx 业务 API 兼容层；只保留一次性迁移工具。
- 运行树目标为 `apps/*` + `domains/*`；旧 `backend/`、`frontend/` 计划删除，本阶段不删。
- OpenCode 作为唯一执行事实源；旧轮次不得覆盖新轮次。
- 风险写入的人类批准，且批准前复验授权与版本。

## 从 1.0 门禁移出（Post-1.0 / 可选）

- 正式 Three.js WebGL 三维首页。状态驱动 2.5D / DOM 空间即足够。
- 企业 IM Binding，以及附件存储、订阅通知作为完成条件。
- Skill 提案、验证、审批、发布、观察、回滚的完整产品。
- 治理成本看板、API 网关硬配额作为 1.0 阻断项。
- 五层策略全量交集。保留 Role 上限 ∩ 员工工程授权 ∩ 人类批准。
- 全部页面与原设计全部门禁同时变绿。改为一条垂直切片。
- DeepSeekBot / Grok / OpenClaw 隐喻带来的额外运行语义。
- 公司全量 ETL、真实旧资产逐类签收、全服务部署，以及切换后删除旧运行树。

## 1.0 改为这条垂直切片

Human↔Employee DM → Inbox/Routine 唤醒 → 创建 Task → Worker/OpenCode 执行 → 独立验收 → 一张风险写入批准卡 → 新应用路径停止暴露旧运行入口。
