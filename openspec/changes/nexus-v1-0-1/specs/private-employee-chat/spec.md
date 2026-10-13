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

### Requirement: Anonymous conversations stay bound to one Session

系统 SHALL 用浏览器本地的匿名标识区分对话所有者，不要求登录。同一员工的每条对话 MUST 绑定 Agent Service 返回的 Session，刷新或重启 API 后仍能按该标识取回。其他匿名标识 MUST NOT 读到这些对话。回复正文 MUST 来自该 Session 已保存的消息或它的事件流。

#### Scenario: Another browser cannot read the conversation

- **WHEN** 一个匿名标识创建了对话，另一个匿名标识查询同一员工
- **THEN** 第二个标识看不到这条对话

#### Scenario: Restart restores the same Session

- **WHEN** 一条对话已经绑定 Session，API 进程用同一份目录数据重新启动
- **THEN** 原匿名标识仍能打开这条对话和已发送的用户消息
- **THEN** Session 标识与重启前相同

### Requirement: Readable attachments are placed in the model input

图片 SHALL 作为 AgentScope 的 `data` 块发送。文本、代码和日志 SHALL 把文件正文放进文本块。当前模型接口不接收的二进制 SHALL 只保留文件名和类型，并明确告诉模型不要描述文件内容。系统 MUST NOT 生成“已经解析附件”这类回复。

#### Scenario: A log file is included in the chat input

- **WHEN** 浏览者发送一个文本日志，并且 Agent Service 接受这次运行
- **THEN** 发给 Agent Service 的用户消息包含该日志正文

#### Scenario: An opaque file is not described

- **WHEN** 浏览者发送一个不能按文本读取、也不是图片或 PDF 的文件
- **THEN** 模型输入说明该文件没有放进输入，并要求不要描述内容
