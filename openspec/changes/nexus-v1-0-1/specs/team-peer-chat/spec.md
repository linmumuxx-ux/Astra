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

员工需要联系另一位员工时，MUST 由发送方 Agent 调用 `contact_employee` 完成。该工具 SHALL 把一条提示写入对方 Session 的 inbox，并在对方当前没有运行消费该 inbox 时唤醒对方。对方的发言 MUST 来自对方自己的推理。产品 MUST NOT 使用 Leader 与 Worker 的 Agent Team 来完成这种对等联系。Nexus 启动的 Agent Service SHALL 在官方工具组装之后卸下任务规划工具和 Agent Team 工具，并保留 `contact_employee`。

#### Scenario: Team and task tools are not offered

- **WHEN** 一位 Nexus 员工开始一次讨论中的运行
- **THEN** 该运行可以调用 `contact_employee`
- **THEN** 该运行的工具事件里不出现 `TeamCreate` 或 `TaskGet`

#### Scenario: Tool delivers a hint instead of a scripted answer

- **WHEN** 一位员工的 Agent 对同一讨论中的另一位员工调用联系工具
- **THEN** 对方 Session 收到这条提示并可以被唤醒
- **THEN** 工具结果不包含代替对方写好的答复

#### Scenario: Peer without a prior mention still receives a channel session

- **WHEN** 被联系的同事属于同一讨论，但这次人类消息没有点名该同事
- **THEN** 系统为该同事创建或复用这条讨论上的 Session，并把提示交给该 Session
- **THEN** 这次解析不代替该同事调用聊天，也不生成该同事的回复

### Requirement: A channel keeps each employee's identity

讨论中的发言 SHALL 按说话人区分。人类消息来自 Nexus 保存的用户消息。数字员工的发言 SHALL 读取该员工自己在这条讨论中的 Session，并用该员工的标识展示。刷新讨论后仍然能看到这些发言。系统 MUST NOT 把一位员工的 Session 文本标成另一位员工。

#### Scenario: Restore a multi-employee transcript

- **WHEN** 讨论中已有用户消息，且某位成员的 Session 里有助手文本
- **THEN** 读取讨论消息时，用户消息的发送者是用户，助手文本的发送者是该成员
- **THEN** Nexus 的消息表里仍然只有用户发言

### Requirement: Channel files are sent like private chat

团队消息的附件 SHALL 使用与私聊相同的模型输入。文本和日志进入文本块。图片进入数据块。读不到的二进制只说明没有放进模型输入。

#### Scenario: A log attachment is included in the named employee's input

- **WHEN** 用户在讨论中点名一位员工并附上文本日志
- **THEN** 只有该员工的运行收到包含日志正文的内容块

### Requirement: Peer contact does not loop

同一次讨论里，系统 SHALL 拒绝同一发送方把同一句话再次交给同一位同事。每位发送方在同一讨论中的联系次数 SHALL 有上限。讨论内的联系总次数 SHALL 有上限。达到上限时，联系工具 SHALL 得到停止继续联系的说明，并且不再投递。该上限 MUST 仍允许一位员工联系下一位同事。

#### Scenario: Repeated and extra contacts stop

- **WHEN** 同一发送方再次提交已经交给对方的同一句话，或已达到该发送方的联系次数
- **THEN** 解析不返回可投递的 Session
- **THEN** 联系工具不把这条消息再写入对方 inbox

#### Scenario: A second employee can still contact a third

- **WHEN** 第一位员工已经联系过同事，第二位员工再联系另一位尚未被禁用的成员
- **THEN** 解析返回第三位成员在该讨论中的 Session
- **THEN** 被禁用的成员不会被这次联系唤醒
