## ADDED Requirements

### Requirement: Operator can manage team discussions

团队交流页面 SHALL 允许创建和编辑讨论。讨论必须有名称、目标和至少一位数字员工。操作者可以调整参与者。页面 SHALL 显示当前讨论的成员及其启用状态。

#### Scenario: Create a discussion

- **WHEN** 操作者提交名称、目标和至少一位员工
- **THEN** 讨论出现在频道列表中并成为当前讨论

#### Scenario: Reject a discussion without members

- **WHEN** 操作者提交讨论时没有选择任何员工
- **THEN** 系统不创建该讨论并说明至少需要一位员工

### Requirement: Mentions wake only the named employees

发送团队消息时，系统 SHALL 保存用户消息。正文中的 `@员工名` SHALL 只触发被点名且已启用、并且属于该讨论的员工。系统 MUST NOT 代替任何员工生成回复，也 MUST NOT 按职责链条自动追加其他员工的发言。

#### Scenario: Mentioned employee is woken through the agent service

- **WHEN** 用户在讨论中发送点名一位已启用成员的消息，且 Agent Service 接受该成员的运行
- **THEN** 只有该成员的讨论 Session 被触发
- **THEN** 其他成员没有被这次发送触发

#### Scenario: No fabricated colleague reply

- **WHEN** 用户发送团队消息但 Agent Service 没有接受运行
- **THEN** 讨论中保留用户消息
- **THEN** 讨论中不出现任何数字员工的回复

### Requirement: Peer contact is a real tool call between equal agents

员工需要联系另一位员工时，MUST 由发送方 Agent 调用 `contact_employee` 完成。该工具 SHALL 把一条提示写入对方 Session 的 inbox，并在对方当前没有运行消费该 inbox 时唤醒对方。对方的发言 MUST 来自对方自己的推理。产品 MUST NOT 使用 Leader 与 Worker 的 Agent Team 来完成这种对等联系。

#### Scenario: Tool delivers a hint instead of a scripted answer

- **WHEN** 一位员工的 Agent 对同一讨论中的另一位员工调用联系工具
- **THEN** 对方 Session 收到这条提示并可以被唤醒
- **THEN** 工具结果不包含代替对方写好的答复
