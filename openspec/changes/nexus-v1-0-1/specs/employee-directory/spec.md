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
