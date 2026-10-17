## ADDED Requirements

### Requirement: Session result projects independently of Task closure
The system MUST keep Session status and Task status independent. Session RUNNING, including OpenCode busy and retry, MUST project Task RUNNING. Session SUCCEEDED MUST project Task WAITING for acceptance and MUST NOT mark the Task SUCCEEDED. Session FAILED or INTERRUPTED MUST project Task WAITING for recovery and MUST NOT mark the Task FAILED. Session UNKNOWN MUST keep the current Task status.

#### Scenario: Normal round ends
- **WHEN** the current round's assistant reply finishes with a terminal finish reason and visible text
- **THEN** the Session is SUCCEEDED and the Task is WAITING with an acceptance reason, while the Worker, Session, and Workspace remain occupied

#### Scenario: Retries stay running
- **WHEN** OpenCode reports retry one or more times
- **THEN** the Session and Task stay RUNNING and a single session error event does not become a final failure

#### Scenario: Final failure waits for recovery
- **WHEN** the server is idle after retries and the current round's assistant ends with an error or no visible reply past the grace period
- **THEN** the Session is FAILED or INTERRUPTED and the Task is WAITING for recovery with that reason

### Requirement: Missing current-round evidence does not stay running
The system MUST judge only messages at and after the current-round anchor. When that anchor cannot be found, the server is idle, and the grace period has elapsed, the system MUST mark the Session INTERRUPTED with reason unconfirmed and the Task WAITING. It MUST NOT report success or model failure from an older round.

#### Scenario: Idle without a locatable round
- **WHEN** the submitted anchor is absent from the message list, the server is idle, and the grace period has elapsed
- **THEN** the Session is INTERRUPTED with reason unconfirmed and the Task is no longer RUNNING

### Requirement: Disconnect keeps occupancy and says the state is unconfirmed
The system MUST mark the Session UNKNOWN when the connection drops or the Session cannot be found. The page MUST show a connection anomaly. The Worker MUST remain occupied until the Task is explicitly closed.

#### Scenario: Connection lost while running
- **WHEN** the OpenCode connection drops during execution
- **THEN** the Task status stays unchanged, the Session is UNKNOWN, and the Worker is not released

### Requirement: Explicit close is the only release
The system MUST release the Worker only when the Task becomes SUCCEEDED after an explicit confirmation of a SUCCEEDED Session, or CANCELED after execution is confirmed stopped. WAITING MUST NOT accept a new task on that Worker. Repeating refresh or SSE MUST NOT emit another status transition or wake for the same projection.

#### Scenario: Human confirms acceptance
- **WHEN** a person confirms a Task whose current Session is SUCCEEDED and no question, permission, or unacked input is pending
- **THEN** the Task becomes SUCCEEDED and the Worker is released

#### Scenario: Cancel waits until execution stops
- **WHEN** a person cancels and the Session remains busy after abort
- **THEN** the Task stays occupied and the Worker is not released
