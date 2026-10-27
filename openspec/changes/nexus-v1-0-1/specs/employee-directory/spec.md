## ADDED Requirements

### Requirement: Operator can manage digital employees

系统 SHALL 提供员工列表、搜索、档案、创建、编辑、启用或禁用，以及删除。员工名称、责任领域、职责说明和工作指令为必填。名称与责任领域在忽略大小写后 MUST 各自唯一。

#### Scenario: Create an employee

- **WHEN** 操作者提交名称、责任领域、职责说明和工作指令都完整且不与现有员工冲突的表单
- **THEN** 列表和档案中出现该员工
- **THEN** 该员工可以被启用或禁用

#### Scenario: Reject a duplicate name

- **WHEN** 操作者保存的名称与另一位员工在忽略大小写后相同
- **THEN** 系统拒绝保存并说明名称不可重复

#### Scenario: Delete removes the employee from discussions

- **WHEN** 操作者确认删除一位已经加入团队讨论的员工
- **THEN** 员工列表不再显示该员工
- **THEN** 既有讨论的参与者中不再包含该员工

### Requirement: Skills are selected from AgentScope

技能选择器 SHALL 显示 Agent Service 技能库返回的技能。服务不可用时 MUST 显示空列表并说明技能库不可用，MUST NOT 显示写死的示例技能。操作者不能在 Nexus 里自由编写技能正文。

#### Scenario: Skill catalog is unavailable

- **WHEN** 操作者打开技能选择器且 Agent Service 技能库不可达
- **THEN** 选择器没有可选项，并说明当前无法读取技能

#### Scenario: Operator selects a returned skill

- **WHEN** 技能库返回一项技能且操作者选中它并保存员工
- **THEN** 该员工档案显示这项技能的名称

### Requirement: Knowledge and tools come from AgentScope catalogs

知识选择器 SHALL 使用 Agent Service `GET /knowledge_bases/` 返回的知识库。该接口不可用时，选择器 MUST 为空并说明无法读取，系统 MUST NOT 接受新的手写知识库标识。工具选择器 SHALL 只提供当前启动方式实际具备的工作区工具：Linux 上 `LocalWorkspace.list_tools` 的 Bash、Edit、Glob、Grep、Read、Write，以及部署注册的 `contact_employee`。服务不可达时 MUST NOT 接受新的工具名称。两种选择器都 MUST NOT 预置产品示例里的虚构名称。

#### Scenario: Knowledge catalog is disabled

- **WHEN** Agent Service 没有启用知识库，操作者提交一个目录中不存在的知识库标识
- **THEN** 系统拒绝保存并说明当前不能新增知识库

#### Scenario: Unknown tool name is rejected

- **WHEN** Agent Service 可达，操作者提交目录以外的工具名称
- **THEN** 系统拒绝保存
- **THEN** 可选工具里仍然有 `contact_employee` 与工作区自带工具

### Requirement: A disabled employee does not start a new run

禁用只改变 Nexus 是否允许开始新的 Agent 运行。已禁用的员工 MUST NOT 接受新的私聊运行、频道点名运行，也 MUST NOT 被 `contact_employee` 唤醒。重新启用后可以再次开始运行。删除员工时，若已经有 AgentScope Agent，MUST 先删除该 Agent，再从员工列表和既有讨论中移除。

#### Scenario: Disable blocks a new private run

- **WHEN** 操作者禁用一位员工后，浏览者向该员工发送私聊
- **THEN** 系统拒绝这次发送，并且 Agent Service 没有为该员工开始新的运行

#### Scenario: Disable blocks peer wakeup

- **WHEN** 另一位员工联系这位已禁用的员工
- **THEN** 解析结果不返回对方的 Session
- **THEN** 不会为被禁用的员工开始新的运行
