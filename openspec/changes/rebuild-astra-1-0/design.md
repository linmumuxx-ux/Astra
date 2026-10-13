## Context

起点 `05dd73142b294a9cb6b2b14a0750b707422aeec3`，fetch 后原分支与远端一致；新分支 `rewrite/astra-1.0`。用户原未跟踪设计包保持原样。唯一产品基线为同包设计全部 17 节。

## Goals / Non-Goals

完整集成所有能力并全量验收。无需新推理引擎、第二套 Workflow/Transcript、重复 Wiki/Skill；不保持 0.xx 业务兼容。

## Decisions

- 新 `apps/api`、`apps/web`、`domains/*` 与独立 schema；SQLAlchemy Base 仅注册 1.0 模型，禁止导入 backend.app。旧树仅在完成迁移验收前保留作复制来源，不作为新应用入口。
- 员工/岗位/目标和 Worker 分离；Task 是业务闭环，TaskExecution 只索引原生 Session、Workspace、尝试/终态/证据；未知结果保持待对账。
- 所有服务以认证 Principal 与 operation key 入口；opaque bearer token 仅存哈希；组织/岗位/员工/Task Grant 取交集。API 不接受自报 actor，成员可见性每次查询/推送重查。
- SourceEvent 唯一 source/source_id/revision；Inbox 唯一 employee/event；Persona lease 使用数据库 CAS/fencing。Worker slot 租约控制容量，结果以 attempt/superseded_by 隔离。短事务内不做外部 I/O。
- 审批绑定具体 action/target/payload/target_revision/policy_revision/expiry；批准不等于执行。外部副作用有独立账本，未知结果先对账。
- Channel 是长期沟通事实；事件只引用消息。Git Memory 保存索引并限长，不授权、不自动复制私人 DM。
- 按固定起点审计并复制成熟通信/证据/知识/网关实现，记录来源与依赖；实际 Runtime/SSH 版本仍需真实验证。
- 新前端只接新 API，Three.js 本地打包、DOM 处理业务；权限过滤持久 SSE 可从 after 恢复和刷新快照。
- 离线 ETL 的旧 ID/manifest 不进入业务字段；无明确主责历史 Task 为只读、不调度。

## Risks / Trade-offs

- 公司环境/生产库/模型凭据未确认 → 只读探测并如实标为未验证。
- SQLite 不证明 MySQL 并发 → 补真实 MySQL lease/锁竞争测试。
- 删除旧树和正式切换不可提前 → 全量门禁失败拒绝切换，保留冻结备份恢复。

## Migration Plan

新空库→冻结并停止旧调度→导出/Session/资产验证→显式映射→幂等导入→逐类对账→全量真实验收→封存旧树→只启用新树。切换前可重排练，切换后以新库备份恢复，不双写。

## Open Questions

需要确认公司 Windows/Linux/SSH、可读旧库备份和模型授权；真实公司部署不能由模拟环境代替。
