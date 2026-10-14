## ADDED Requirements

### Requirement: 独立身份与职责
系统 MUST 支持多用户认证、HUMAN/EMPLOYEE/SYSTEM/WORKER 分离，员工拥有稳定 ID、目标、授权、预算与记忆，不固定主机。

#### Scenario: 独立身份与职责验收
- **WHEN** 同岗位多个员工创建
- **THEN** 共享能力但独立 DM/记忆/目标

### Requirement: 员工生命周期
系统 MUST 支持暂停/恢复/调岗/归档审计，冻结唤醒并显式交接未完工作。

#### Scenario: 员工生命周期验收
- **WHEN** 有在途 Task/Goal/审批时归档
- **THEN** 拒绝直接归档，历史私人对话不转让
