## ADDED Requirements

### Requirement: One employee has many private conversations

数字员工页面 SHALL 列出员工，并让同一浏览者与同一员工保持多条独立对话。浏览者可以新建对话、在已有对话之间切换，并看到当前对话的标题。禁用的员工 MUST NOT 接受新消息，其已有消息仍可查看。

#### Scenario: Start a second conversation

- **WHEN** 浏览者正在查看某员工的一条对话并选择新对话
- **THEN** 出现一条没有历史消息的新对话
- **THEN** 原先那条对话仍可被切换回来

#### Scenario: Disabled employee rejects input

- **WHEN** 浏览者打开一位已禁用员工的对话
- **THEN** 输入框不能发送
- **THEN** 已有消息仍然显示

### Requirement: Private replies come only from the employee agent

发送私聊消息时，系统 SHALL 保存用户消息。Agent Service 接受该次运行后，回复内容 SHALL 只来自该 Session 的事件流或该 Session 已持久化的消息。系统 MUST NOT 根据关键词编写助手回复。

#### Scenario: Accepted run streams text

- **WHEN** Agent Service 对这条私聊返回已开始，并且事件流出现文本增量
- **THEN** 对话中逐步显示这些增量
- **THEN** 显示内容不包含由 Nexus 预先写好的职责说明

#### Scenario: Service rejects the run

- **WHEN** 浏览者向已启用员工发送消息，但 Agent Service 没有接受这次运行
- **THEN** 对话中保留用户消息
- **THEN** 对话中不出现该员工的回复气泡

### Requirement: Attachments stay with the user message

私聊 SHALL 允许用户在发送前添加图片或文件，并在消息上看到附件。系统 MUST NOT 把附件描述成已经被模型理解。

#### Scenario: Send a file without an agent reply

- **WHEN** 浏览者添加一个非空且不超过大小限制的文件并发送，而 Agent Service 不可用
- **THEN** 用户消息显示该附件
- **THEN** 不出现声称已经解析该文件的员工回复
