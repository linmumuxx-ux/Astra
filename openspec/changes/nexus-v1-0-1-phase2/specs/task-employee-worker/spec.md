## ADDED Requirements

### Requirement: Responsible employee and executing worker are different records

A task SHALL record one responsible digital employee and at most one executing Agent Worker. The employee is the AgentScope agent that accepts the engineering request and follows the task. The worker is the OpenCode execution resource. The system MUST NOT treat the worker as a digital employee or as an AgentScope sub-agent.

#### Scenario: Task is created for an employee

- **WHEN** a configured employee creates a task for an engineering request
- **THEN** the task stores that employee as the responsible employee and leaves execution to a worker

#### Scenario: Worker is not listed as a chat employee

- **WHEN** a worker is added for OpenCode execution
- **THEN** the worker appears in worker management and does not become a private-chat or team-discussion participant

### Requirement: Task keeps the execution relationship

A task SHALL keep its type, category, business status, responsible employee, source conversation when one exists, assigned worker, and the OpenCode session and workspace used for execution.

#### Scenario: Execution is visible from the task

- **WHEN** a worker has started OpenCode for a task
- **THEN** the task detail shows the responsible employee, the worker, and the OpenCode session and workspace for that execution

### Requirement: Phase 1 conversations stay available

Private chat, team discussion, employee directory, and peer contact SHALL keep the Phase 1 behaviour. The chat page MUST NOT offer a button that creates a task by hand.

#### Scenario: Chat has no manual task button

- **WHEN** a person opens a private chat or a team discussion
- **THEN** the page still sends messages and attachments, and it does not show a control whose action is to create a task

### Requirement: Worker keeps the execution environment

Worker management SHALL preserve local and Linux remote environments, SSH host, port, username and authentication, workspace root, OpenCode executable path and version, OpenCode server port, execution model, environment status, connection test, health check, one-step deploy, and one-step OpenCode restart, including deploy steps, logs, and the failure reason.

#### Scenario: Remote environment can be deployed from the worker

- **WHEN** an operator runs deploy or restart on a Linux remote worker
- **THEN** the same worker record shows the operation steps, the log, and either success or the failure reason

### Requirement: OpenCode defaults to deepseek-flash

OpenCode execution SHALL default to model id `deepseek-flash` on the DeepSeek OpenAI-compatible API at `https://api.deepseek.com`. The setting and a worker-level model SHALL be able to replace that default. A worker model SHALL take precedence over the global default.

#### Scenario: Worker has no model of its own

- **WHEN** a worker has no execution model set
- **THEN** OpenCode uses model id `deepseek-flash` and the DeepSeek API base `https://api.deepseek.com`

#### Scenario: Worker model overrides the default

- **WHEN** a worker has its own execution model
- **THEN** that worker's model is used for its tasks
