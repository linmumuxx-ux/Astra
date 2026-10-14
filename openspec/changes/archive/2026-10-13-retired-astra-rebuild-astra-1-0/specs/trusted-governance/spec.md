## ADDED Requirements

### Requirement: 可信 Principal 与权限交集
系统 MUST 支持后端认证注入 actor，组织/岗位/员工/具体 Workspace Grant/当前操作取交集，密钥不入模型和日志。

#### Scenario: 可信 Principal 与权限交集验收
- **WHEN** 自报管理员、Prompt 注入或员工自行扩权
- **THEN** 拒绝并审计真实主体

### Requirement: 具体审批和幂等操作
系统 MUST 支持PREPARED/WAIT_HUMAN/APPROVED/REJECTED/EXPIRED/EXECUTED/FAILED，绑定 action/target/scope/revision/expiry；批准前后复验。

#### Scenario: 具体审批和幂等操作验收
- **WHEN** 重复批准、过期、目标变更或权限撤销
- **THEN** 仅一个副作用或拒绝失效授权，未知结果先对账

### Requirement: 人工介入与资源治理
系统 MUST 支持pause/stop/takeover、Worker/网关密钥/额度/成本/故障治理、目标/介入/交接/质量/复发等真实指标。

#### Scenario: 人工介入与资源治理验收
- **WHEN** 人停止正在执行的任务
- **THEN** 停止新动作，未知结果独立对账，权威结果审计
