## ADDED Requirements

### Requirement: 统一工作入口
系统 MUST 支持Routine/DM/外部事件/Task 结果统一进入 SourceEvent，按责任生成 Inbox，区分投递/观察/处理。

#### Scenario: 统一工作入口验收
- **WHEN** 事件重复投递或多规则命中
- **THEN** 每员工只一个关注关系，观察不自动关闭

### Requirement: 有限决策与恢复
系统 MUST 支持每员工单活 Persona lease/fencing，短模型 Session；支持 reply/no_action/remember/dispatch/follow_up/ask_human/handoff；预算分开计费。

#### Scenario: 有限决策与恢复验收
- **WHEN** 旧回合租约过期或平台重启
- **THEN** 旧回合提交拒绝，长期上下文恢复，不强制创建 Task

### Requirement: 持续职责
系统 MUST 支持Routine 支持 Cron/周期/事件/Run Now/时区/暂停恢复/人类锁定，停用员工不唤醒。

#### Scenario: 持续职责验收
- **WHEN** 修改锁定 Routine 或恢复积压员工
- **THEN** 拒绝扩权，只处理最近应办事件，不补跑全部时间片
