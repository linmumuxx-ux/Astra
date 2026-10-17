## ADDED Requirements

### Requirement: Task MCP wraps the task service

Task MCP SHALL expose create, query, update, and assign; start, pause, resume, terminate, and retry; run status, progress, logs, and result; human intervention, confirmation, and exception handling; and read access to delivery, task summary, and candidate experience. The MCP layer MUST call the existing task service and MUST NOT keep a second task state machine or execution implementation.

#### Scenario: MCP create uses the task service

- **WHEN** an employee invokes task creation through Task MCP
- **THEN** the task is stored by the task service, and the service's state machine decides the resulting status

#### Scenario: Illegal control is rejected by the service

- **WHEN** an employee asks Task MCP to start, pause, resume, terminate, or retry a task whose current status does not allow that operation
- **THEN** the task status stays unchanged and the tool result says the operation was not applied

### Requirement: Task Skill tells the employee how to use the MCP

A Task Skill SHALL state when creating a task is appropriate, how to choose task type, category, and acceptance criteria, how to call Task MCP, how to handle exceptions and human intervention, and how to follow the task until delivery.

#### Scenario: Conversational answer does not create a task

- **WHEN** the person asks a question that the employee can answer in the conversation without a workspace or a code change
- **THEN** the skill directs the employee to answer in the conversation and not to create a task

#### Scenario: Engineering request can create a task

- **WHEN** the person asks the employee for an engineering change that needs OpenCode execution
- **THEN** the skill directs the employee to choose type, category, and acceptance criteria and to create the task through Task MCP

### Requirement: Skill and MCP are configured on the employee

Task MCP SHALL be registered in the AgentScope tool system, and Task Skill SHALL be available to the employees that have it configured. Employee management SHALL show and save that Skill and MCP selection. An employee uses them according to its own duty. The product MUST NOT require the person to create the task from the chat page.

#### Scenario: Configured employee can call the task tools

- **WHEN** an enabled employee with Task Skill and Task MCP configured receives an engineering request in its session
- **THEN** that session can load the skill and call the Task MCP tools

#### Scenario: Employee without the configuration has no task tools

- **WHEN** an employee is saved without Task Skill and Task MCP
- **THEN** that employee's sessions do not gain the task tools from this configuration

### Requirement: AgentScope planning tools stay unloaded

The AgentScope built-in planning tools and Agent Team tools SHALL remain unloaded for Nexus employees. Task MCP tools SHALL use names that those unloaded tools do not use.

#### Scenario: Built-in planning tool is absent

- **WHEN** a Nexus employee session lists its tools
- **THEN** the AgentScope planning tools and Agent Team tools are absent, and the configured Task MCP tools remain present
