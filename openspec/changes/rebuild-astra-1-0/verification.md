# rebuild-astra-1-0 验证报告

日期：2026-10-13。已读取 proposal/design/全部 delta specs/tasks，并运行 status/instructions apply；以既有 change 为范围。status 的规划产物完成不代表产品完成。

| 维度 | 结论 |
| --- | --- |
| 完整性 | 1/19 实施任务完成；18 项 CRITICAL |
| 正确性 | 23 条新增 Requirement 有部分实现及证据；完整 Scenario 门禁未满足 |
| 一致性 | 新域/新 API/独立迁移/原生事实边界已遵守；正式切换及旧实现移除未执行 |

## CRITICAL：未完成实施任务

- **1.2** 完成全部领域规范、架构/数据字典/API/Tool 契约和复用审计，OpenSpec validate 通过。 位置：`docs/astra-1.0/contracts.md`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **2.1** 新 schema、认证 Principal、权限交集、组织/岗位/员工/Goal/生命周期；越权/归档/撤权测试。 位置：`domains/organization/service.py`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **2.2** SourceEvent/Inbox/Persona fencing/Routine/记忆/预算与外部 connectors，重复事件/恢复/锁定测试。 位置：`apps/services/personas.py`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **2.3** 长期 DM/Group/附件/引用/@、正式交接、冲突/防循环、持久 SSE；隔离/并发/重连测试。 位置：`domains/messaging/service.py`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **2.4** 具体操作准备/审批/执行、权限版本/失效/重复审批、审计、pause/stop/takeover 测试。 位置：`domains/governance/service.py`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **3.1** 复制成熟 OpenCode/Workspace/SSH，Worker 池/lease/资产隔离/旧尝试 fencing；版本契约测试。 位置：`domains/runtime/workspace.py`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **3.2** 任务委派、原生执行、证据独立验收、返工/跟踪；断线/超时/取消/重启/未知副作用对账测试。 位置：`domains/runtime/service.py`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **3.3** 原始知识/Wiki/经验/Skill 验证审批发布回滚、个人 Git Memory、API 网关/资源指标；证据及权限测试。 位置：`domains/knowledge/memory.py`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **4.1** 动态 3D 数字空间、真实状态、DOM 交互、2D 降级/减少动态效果/离线资源构建验证。 位置：`apps/web/src`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **4.2** 员工长期 DM、团队 Channel、工作列表详情/Workspace、Human Inbox 全交互真实 API 验证。 位置：`apps/web/src`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **4.3** 组织/岗位/目标/预算、图书馆/Skill/Memory、Worker/API、治理/审计全交互与页面状态验证。 位置：`apps/web/src`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **5.1** 独立 from_0xx 冻结/导出/显式映射/幂等导入/dry-run/恢复/对账工具与失败注入测试。 位置：`migrations/from_0xx/formal.py`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **5.2** 真实旧库和所有 Session/Workspace/知识/Skill/会话逐类对账签收，提交审计报告。 位置：`docs/astra-1.0/migration-reconciliation-report.json`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **5.3** 单运行树部署/健康检查/备份恢复，公司 Windows/Linux 内网真实部署；切换后删除旧运行实现。 位置：`docs/astra-1.0/deployment.md`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **6.1** 领域/集成/迁移/MySQL 并发、完整前端构建与浏览器 E2E 全通过。 位置：`tests/v1`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **6.2** 真实 OpenCode：同岗多员工/同员工并行/共享 Worker/跨岗交接复验/主动职责/成长完整流程。 位置：`tests/v1/test_runtime_live.py`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **6.3** 真实权限撤销/重复审批/冲突指令/人工接管/历史证据/断线重启/SSE 恢复与全部页面截图。 位置：`tests/v1/test_persona_live.py`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。
- **6.4** 执行 opsx-verify，全部门禁完成后同步归档；提交架构/契约/部署/测试/问题清单，才可标记 1.0 完成。 位置：`docs/astra-1.0/verification.md`。建议：完成该任务全部内容及 Scenario 验证后再勾选；具体缺口见 `docs/astra-1.0/issues.md`。

## Requirement 与 Scenario 对照

| Requirement | 实现和测试证据 | Scenario 结论 |
| --- | --- | --- |
| 九类真实工作页面 | apps/web/src；apps/web/e2e；test_sse.py | 九页面基础交互、2D/移动端/断线恢复通过；所有必需业务操作/内网冷构建未覆盖 |
| 轻量动态空间 | apps/web/src；apps/web/e2e；test_sse.py | 九页面基础交互、2D/移动端/断线恢复通过；所有必需业务操作/内网冷构建未覆盖 |
| 状态与 SSE 恢复 | apps/web/src；apps/web/e2e；test_sse.py | 九页面基础交互、2D/移动端/断线恢复通过；所有必需业务操作/内网冷构建未覆盖 |
| 统一工作入口 | apps/services/personas.py、domains/personas/routines.py；test_personas.py/test_routines.py/test_persona_live.py | 三真实短回合和 Routine 通过；Task 结果/连接器/完整冲突与预算未覆盖 |
| 有限决策与恢复 | apps/services/personas.py、domains/personas/routines.py；test_personas.py/test_routines.py/test_persona_live.py | 三真实短回合和 Routine 通过；Task 结果/连接器/完整冲突与预算未覆盖 |
| 持续职责 | apps/services/personas.py、domains/personas/routines.py；test_personas.py/test_routines.py/test_persona_live.py | 三真实短回合和 Routine 通过；Task 结果/连接器/完整冲突与预算未覆盖 |
| 独立身份与职责 | domains/identity/service.py、domains/organization/service.py；test_identity_management.py | 身份/权限/暂停/归档有测试；调岗及责任清点未覆盖 |
| 员工生命周期 | domains/identity/service.py、domains/organization/service.py；test_identity_management.py | 身份/权限/暂停/归档有测试；调岗及责任清点未覆盖 |
| 知识与个人记忆分离 | domains/knowledge/memory.py；test_memory.py/test_persona_live.py | Git Memory 及来源隔离通过；Skill 完整成长链未覆盖 |
| 受控成长链路 | domains/knowledge/memory.py；test_memory.py/test_persona_live.py | Git Memory 及来源隔离通过；Skill 完整成长链未覆盖 |
| 独立冻结与显式映射 | migrations/from_0xx；test_migration_etl.py/test_migration_formal.py | 隔离 fixture 导入恢复对账通过；真实旧库外部资产/正式切换未覆盖 |
| 可恢复导入与对账 | migrations/from_0xx；test_migration_etl.py/test_migration_formal.py | 隔离 fixture 导入恢复对账通过；真实旧库外部资产/正式切换未覆盖 |
| 单次正式切换 | migrations/from_0xx；test_migration_etl.py/test_migration_formal.py | 隔离 fixture 导入恢复对账通过；真实旧库外部资产/正式切换未覆盖 |
| 持久 Channel 与隔离 | domains/messaging/service.py、domains/work/service.py；test_handoff_responses.py/test_sse.py | DM 隔离/交接/因果防循环通过；附件/同级冲突/跨岗修复复验未覆盖 |
| 正式跨岗交接 | domains/messaging/service.py、domains/work/service.py；test_handoff_responses.py/test_sse.py | DM 隔离/交接/因果防循环通过；附件/同级冲突/跨岗修复复验未覆盖 |
| 冲突与防循环 | domains/messaging/service.py、domains/work/service.py；test_handoff_responses.py/test_sse.py | DM 隔离/交接/因果防循环通过；附件/同级冲突/跨岗修复复验未覆盖 |
| 可信 Principal 与权限交集 | domains/governance/service.py、domains/identity/service.py；test_review_regressions.py/test_mysql_locking.py | Principal/幂等/有限审批通过；外部执行账本/硬配额/接管未覆盖 |
| 具体审批和幂等操作 | domains/governance/service.py、domains/identity/service.py；test_review_regressions.py/test_mysql_locking.py | Principal/幂等/有限审批通过；外部执行账本/硬配额/接管未覆盖 |
| 人工介入与资源治理 | domains/governance/service.py、domains/identity/service.py；test_review_regressions.py/test_mysql_locking.py | Principal/幂等/有限审批通过；外部执行账本/硬配额/接管未覆盖 |
| 执行资源隔离 | domains/runtime/service.py/client.py/workspace.py、apps/services/executions.py；test_dispatch.py/test_execution_live.py | 资源租约、原生工程启动、真实业务与浏览器独立验收通过；完整自主返工/接管/公司版本未覆盖 |
| 原生执行与独立验收 | domains/runtime/service.py/client.py/workspace.py、apps/services/executions.py；test_dispatch.py/test_execution_live.py | 资源租约、原生工程启动、真实业务与浏览器独立验收通过；完整自主返工/接管/公司版本未覆盖 |
| 恢复与旧轮次隔离 | domains/runtime/service.py/client.py/workspace.py、apps/services/executions.py；test_dispatch.py/test_execution_live.py | 资源租约、原生工程启动、真实业务与浏览器独立验收通过；完整自主返工/接管/公司版本未覆盖 |
| 真实 Runtime 兼容 | domains/runtime/service.py/client.py/workspace.py、apps/services/executions.py；test_dispatch.py/test_execution_live.py | 资源租约、原生工程启动、真实业务与浏览器独立验收通过；完整自主返工/接管/公司版本未覆盖 |

## WARNING 与一致性检查

- 工程真实业务及浏览器验收已通过；Persona 自主验收、自动返工/Goal 跟踪、多员工并行和未知副作用恢复尚未通过，不能替代完整 Scenario 门禁。
- Skill、API 网关及 Workspace UI 仍未接通；页面禁止虚构成功或展示假业务状态。
- 所有 REMOVED 规范对应旧实现仍作为复制来源保留，单次切换时须从正式运行仓库移除；当前不得同步/归档。
- 内网冷构建、公司 Linux/Windows/SSH、生产全量迁移/灾备未验证；没有以本机隔离结果推断通过。
- AST 边界检查覆盖新 API/services/agents，禁止旧 app/backend.app/from_0xx 导入；事务外 Runtime/Git I/O，TaskExecution 仅索引、不复制 Transcript。

## 结论

18 项 CRITICAL 尚未关闭，禁止归档或标记 Astra 1.0 完成。没有跳过规划产物；公司及生产验证因尚无安全环境配置/资产清单未执行。实际检查命令、结果和证据见 `docs/astra-1.0/verification.md`。
