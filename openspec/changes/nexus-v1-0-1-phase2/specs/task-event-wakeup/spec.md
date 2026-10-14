## ADDED Requirements

### Requirement: Task transitions wake the responsible employee

A task transition to completed, failed, waiting for a person, canceled, or recovered after a failure SHALL be delivered to the responsible employee's AgentScope session through the existing inbox and wakeup path. The delivered hint SHALL identify the task and the event. It MUST tell the employee to read the current task through Task MCP before deciding what to do next.

#### Scenario: Failure wakes the employee

- **WHEN** a running task becomes failed
- **THEN** the responsible employee's target session receives one hint for that event, and a wakeup is requested when that session has no inbox consumer

#### Scenario: Employee reads current state after the hint

- **WHEN** the employee session consumes a task hint
- **THEN** the skill directs the employee to query the task through Task MCP and to decide the next action from that result

### Requirement: Delivery is durable, idempotent, and recoverable

The wake MUST be recorded in the same transaction as the task event. A recorded wake SHALL be retried until the inbox accepts it or a newer wake for the same task and target session supersedes it. Delivering the same event again MUST NOT apply a second task-state change. Restarting the delivery process MUST NOT drop a recorded wake that has not been acknowledged.

#### Scenario: Process stops after the event is stored

- **WHEN** the task transition is committed and the delivery process stops before the inbox accepts the hint
- **THEN** a later delivery pass sends that wake, and the task status remains the status already committed

#### Scenario: Repeated delivery does not change status twice

- **WHEN** the same committed event is delivered to the inbox more than once
- **THEN** a repeated control call for that event leaves the task status unchanged

### Requirement: Wake has no separate page

Task wake is an internal delivery to the employee session. The product MUST NOT add a page whose purpose is to browse wake events. Task center, worker management, and the employee conversation SHALL show the task's current relationship and status.

#### Scenario: Status is read from the task

- **WHEN** a person opens the employee conversation, the task center, or worker management after a task transition
- **THEN** those views show the task status stored by the task service
