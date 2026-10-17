## ADDED Requirements

### Requirement: Worker identity is independent of the employee
The system MUST bind one Worker instance to one execution environment and MUST identify it with `worker_instance_id`. The system MUST NOT use the digital employee id as that identity. Enrollment MUST return the token once and store only its digest.

#### Scenario: Enrollment hides the token
- **WHEN** an operator enrolls an execution environment and later reads the Worker
- **THEN** the enrollment response contains the token and the stored row and later reads do not

#### Scenario: Re-enrollment keeps the instance
- **WHEN** the same environment is enrolled again
- **THEN** the instance id is unchanged, the previous token no longer authenticates, and the epoch increases

### Requirement: One connection epoch is current
The system MUST increment the epoch when a connection authenticates. After a newer epoch is stored, a disconnect or response from an older epoch MUST NOT change the Worker status or command result.

#### Scenario: Stale response is ignored
- **WHEN** a command was stored for an older epoch and that epoch later sends its result
- **THEN** the command status stays unchanged

#### Scenario: Old disconnect keeps the new connection
- **WHEN** the old connection closes after a newer epoch is online
- **THEN** the Worker remains online at the newer epoch

### Requirement: Commands are durable and idempotent
The system MUST store a command before publishing it. The same `request_id` with the same Worker, command name, and payload MUST return the stored command and MUST NOT publish it again. A conflicting Worker, name, or payload MUST be rejected. An offline Worker MUST persist the command as failed with `offline`. A full control queue MUST leave the command pending and `unpublished`. A publish whose result is unknown MUST leave the command `uncertain` and MUST NOT roll the attempt back. Idempotent commands that are still `pending` MAY be retried by the same-epoch owner after the dispatch lease expires. Accepted commands MUST NOT be republished. A newer epoch MUST NOT adopt the previous epoch's commands. A side-effect command such as `prompt` MUST NOT be published again after it leaves `unpublished`.

#### Scenario: Duplicate request is not delivered twice
- **WHEN** a caller submits a request id that is already stored
- **THEN** the original command is returned and the route publishes once

#### Scenario: Publish sees the stored row
- **WHEN** the route publishes a new command
- **THEN** the command row is already pending

### Requirement: Routing has one owner
The process holding the socket MUST be the only owner for that epoch. Registration MUST reject an older epoch, including after the current lease is cleared or expires. Another memory bus MUST NOT observe that owner. Redis clients using the same prefix MUST observe it. Clearing an older epoch or a different owner MUST leave the current lease in place. Publish, consume, and send MUST fence on the target epoch. A consumer that loses ownership MUST stop. Control frames MUST be delivered before queued events, and a full event queue MUST drop events instead of blocking control. Local heartbeat frames MUST NOT release Redis queue capacity.

#### Scenario: Separate memory buses do not share ownership
- **WHEN** one memory bus records an owner
- **THEN** a second memory bus does not return that owner

#### Scenario: Stale lease clear is ignored
- **WHEN** the current lease is epoch 2 and a caller clears epoch 1
- **THEN** the epoch 2 lease remains

### Requirement: Configured Redis is the default bus
When the bus setting is `auto` and the Redis URL is non-empty, the gateway MUST use the Redis bus. When that URL is empty, the gateway MUST use the memory bus and its health payload MUST include the warning `仅单进程可用`. An explicit `memory` or `redis` setting MUST override the automatic choice. Redis queue admission MUST reject a frame once the list length plus frames already pulled but not delivered reaches the limit, and the check plus enqueue MUST be one atomic operation.

#### Scenario: Automatic Redis
- **WHEN** the bus setting is `auto` and a Redis URL is configured
- **THEN** the health payload reports `redis` and has no single-process warning

#### Scenario: Bounded Redis admission
- **WHEN** one command is already queued and the control limit is 1
- **THEN** the next command is rejected even if a consumer has moved the queued command out of the Redis list and not yet delivered it

### Requirement: Disconnect does not restart OpenCode
The Worker Agent MUST reconnect with backoff after a socket failure and MUST NOT count that failure as an OpenCode process restart.

#### Scenario: Reconnect keeps the restart count
- **WHEN** the socket closes and the agent connects again
- **THEN** the new session receives a new epoch and the process restart count stays unchanged

### Requirement: OpenCode HTTP uses a worker-initiated data channel
For an environment that already has a Worker instance, Nexus MUST send OpenCode calls as `http` commands and MUST receive response bodies on `PUT /api/worker-gateway/data/{request_id}`. The Worker MUST open that HTTP call. Nexus MUST NOT dial the Worker, and the response body MUST NOT be placed in a WebSocket frame. The PUT MUST authenticate with the enrollment token and the command epoch. An older epoch MUST be rejected without storing the body. A request body larger than 32 KiB MUST be rejected before publish. A non-stream response larger than 8 MiB MUST fail as `response_too_large`.

#### Scenario: Large response stays off the socket
- **WHEN** a migrated Worker completes an OpenCode HTTP call
- **THEN** the WebSocket completion frame contains only the request id, HTTP status, and size, and the body is stored under the data-channel result key

#### Scenario: Stale data upload is rejected
- **WHEN** a data upload carries an epoch older than the Worker instance
- **THEN** the upload is rejected and no response body is stored

### Requirement: OpenCode events are sequenced and reconciled
The Agent MUST assign a per-epoch, per-subscription sequence to each OpenCode SSE event and upload it on the data channel. Consumers MUST read the shared event log, not the in-process socket buffer. A gap or an event dropped for size MUST surface as `astra.event_gap` and MUST be repaired by rereading the native Session, messages, questions, and permissions. An event from an older epoch MUST NOT advance the cursor. Reconnect MUST NOT create a Session to fill a gap.

#### Scenario: Gap triggers reconcile
- **WHEN** the next event sequence skips one or more numbers
- **THEN** the browser stream receives `astra.event_gap` and recovery rereads the native Session without creating a new one

### Requirement: Reconnect does not resend the last prompt
`pending_message_id` and `pending_prompt.in_flight` MUST be committed before the OpenCode POST leaves Nexus. After reconnect, Nexus MUST compare that id with the native message list. A visible message MUST clear `in_flight` and MUST NOT be sent again. A failed or timed-out read MUST NOT be treated as proof that OpenCode rejected the prompt. Reconnect MUST NOT create a Session and MUST NOT send the last prompt. An explicit retry MAY resend the same message id only after a successful read shows it is absent and `in_flight` has expired. The Agent MUST NOT persist a side-effect deduplication ledger; its in-memory `request_id` record only collapses duplicate frames inside one process.

#### Scenario: Accepted prompt survives an agent exit
- **WHEN** OpenCode has stored the pending message id and the Agent exits before uploading the result
- **THEN** reconnect observes that message, does not send the prompt again, and does not create a Session

### Requirement: Transport faults stay out of task status
A communication failure MUST set `runtime_connection` to `UNAVAILABLE` and MUST leave `Task.status` unchanged. An execution timeout and an OpenCode session error MUST be projected only through `RuntimeService.apply_session_state()`. Worker Gateway code MUST NOT assign `Task.status`. A migrated environment that loses its socket MUST NOT open an SSH tunnel and MUST NOT run the start script that kills an existing OpenCode process. A WebSocket disconnect MUST NOT restart a healthy OpenCode.

#### Scenario: Disconnect keeps the business status
- **WHEN** the Worker socket closes during a running task
- **THEN** the task business status is unchanged, the runtime connection is `UNAVAILABLE`, and no SSH tunnel is opened

### Requirement: Worker occupancy has one predicate
Start, send, and environment maintenance MUST use one occupancy predicate. An employee is occupied while a task is `RUNNING` or `WAITING`, has `pending_message_id`, is claimed `PENDING`, or is `CANCELED` before execution stop is confirmed. Occupancy MUST end only when the task is `SUCCEEDED`, or when the task is `CANCELED` and both pending fields are clear and the bound session is not `RUNNING`, `WAITING`, or `UNKNOWN`. Socket presence, session idle, and command completion MUST NOT release occupancy. `current_task_count` MUST be written from this predicate and MUST NOT be read as an input to it.

#### Scenario: Session success does not free the worker
- **WHEN** the native Session has succeeded and the task is still `WAITING` for human confirmation
- **THEN** the employee remains occupied

#### Scenario: Confirmed cancel releases the worker
- **WHEN** a canceled task has no pending message or prompt and its session is no longer running, waiting, or unknown
- **THEN** the employee is not occupied

### Requirement: Command identity includes the session
The same `request_id` MUST return the stored command only when the Worker, command name, payload, and `session_id` all match. A different `session_id`, including null versus non-null, MUST be rejected with a conflict.

#### Scenario: Same request id on another session conflicts
- **WHEN** a stored request id is submitted again with a different session id
- **THEN** the command is rejected and the original row is not returned as a replay
