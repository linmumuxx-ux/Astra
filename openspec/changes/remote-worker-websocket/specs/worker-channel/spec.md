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

### Requirement: Migrated environments are explicitly marked
The system MUST store `worker_channel` as `ssh` or `worker` on the execution environment. A Worker instance row alone MUST NOT select the Worker transport. The system MUST set `worker` only after the Worker is online, has probed the intranet Gateway and MCP endpoints, and the OpenCode configuration contains those intranet URLs. OpenCode MUST keep listening on `127.0.0.1`.

#### Scenario: Enrollment alone does not migrate
- **WHEN** an environment has a Worker instance and `worker_channel` is still `ssh`
- **THEN** OpenCode HTTP continues to use the existing SSH path

#### Scenario: Migration requires a successful intranet probe
- **WHEN** the Worker cannot reach the intranet Gateway or MCP endpoint
- **THEN** `worker_channel` stays `ssh`

### Requirement: OpenCode HTTP uses a worker-initiated data channel
For an environment marked `worker`, Nexus MUST publish only a short ready notice on the WebSocket. The notice contains the request id, epoch, and deadline, and MUST NOT contain the request or response body. The Worker MUST fetch the body with `GET /api/worker-gateway/data/{request_id}/request` and upload the response with `PUT /api/worker-gateway/data/{request_id}/response`. The upload MUST authenticate with the enrollment token and the command epoch, and MUST carry the response headers needed by callers, including `x-next-cursor`. An older epoch MUST be rejected without storing the body. A request or non-stream response larger than 8 MiB MUST fail. The Workspace proxy MUST use this transport instead of dialing `client.base_url` directly. HTTP work MUST run outside the Agent read loop so heartbeat and cancel stay responsive.

#### Scenario: Large response stays off the socket
- **WHEN** a migrated Worker completes an OpenCode HTTP call
- **THEN** the WebSocket carries only the ready notice, and the response body and headers are stored from the HTTP upload

#### Scenario: Stale data upload is rejected
- **WHEN** a data upload carries an epoch older than the Worker instance
- **THEN** the upload is rejected and no response body is stored

### Requirement: OpenCode events are sequenced WebSocket frames
The Agent MUST assign a per-epoch, per-directory sequence and send each fitting OpenCode SSE event as a WebSocket event frame. One local SSE read MUST exist per Worker, epoch, and directory. The shared log MUST retain the last N events. When the slowest active consumer is N events behind, the Agent MUST pause that directory's SSE read. An event larger than the frame limit MUST be reported as `astra.event_gap` without uploading its payload, and recovery MUST reread the native Session, the full message pages, questions, and permissions. An event from an older epoch MUST NOT advance the cursor. Reconnect MUST NOT create a Session to fill a gap.

#### Scenario: Oversized event becomes a gap
- **WHEN** an OpenCode event exceeds the WebSocket frame limit
- **THEN** consumers receive `astra.event_gap` and recovery rereads the native Session without creating a new one

### Requirement: Only an explicit human retry may resend a prompt
`pending_message_id`, `pending_prompt.in_flight`, and `pending_attempt` MUST be committed before the OpenCode POST leaves Nexus. Reconnect, recovery, dispatch, heartbeat, and timeout paths MUST NOT call the human retry. The human retry MUST reject a submission whose `in_flight` has not expired, then claim it with a compare-and-set on `pending_message_id` and `pending_attempt`. It MUST read every message page. A failed read MUST leave `in_flight` set. A resend MUST also require the original Worker command to be `expired`, `failed`, or bound to an epoch that is no longer current. OpenCode 1.18.35 MUST be treated as not deduplicating `messageID`: a second POST enters the prompt loop again. A visible message id MUST NOT be posted again. Reconnect MUST NOT create a Session.

#### Scenario: Accepted prompt survives an agent exit
- **WHEN** the full message pages contain the pending message id and the Agent exits before uploading the result
- **THEN** reconnect observes that message, does not send the prompt again, and does not create a Session

#### Scenario: Concurrent manual retries post once
- **WHEN** two human retries claim the same pending message at the same time
- **THEN** only one compare-and-set succeeds and only that attempt may post

### Requirement: Transport faults stay out of task status
A communication failure MUST set `runtime_connection` to `UNAVAILABLE` and MUST leave `Task.status` unchanged. An execution timeout and an OpenCode session error MUST be projected only through `RuntimeService.apply_session_state()`. Worker Gateway code MUST NOT assign `Task.status`. An environment marked `worker` that loses its socket MUST NOT open an SSH tunnel and MUST NOT run the start script that kills an existing OpenCode process. A WebSocket disconnect MUST NOT restart a healthy OpenCode.

#### Scenario: Disconnect keeps the business status
- **WHEN** the Worker socket closes during a running task on a migrated environment
- **THEN** the task business status is unchanged, the runtime connection is `UNAVAILABLE`, and no SSH tunnel is opened

### Requirement: Worker occupancy has one predicate
Projection, heartbeat, dispatch, start, send, maintenance, and cancel completion MUST use one occupancy predicate. A task occupies its employee unless the task is `SUCCEEDED`, the task is `CANCELED` and execution stop is confirmed, or a human release has recorded `execution_stop_confirmed_at`. `FAILED`, a broken binding, and a canceled task whose stop is unconfirmed MUST occupy the employee. Socket presence, session idle, and command completion MUST NOT release occupancy. `current_task_count` MUST be written only from this predicate. Heartbeat MUST NOT clear it independently, and dispatch MUST NOT use `current_task_count < 1` as a separate rule. Maintenance MUST additionally refuse while the employee has a Session in `RUNNING`, `WAITING`, or `UNKNOWN` without a human stop confirmation. The human release MUST be explicit, MUST require an unknown or missing Session, and MUST NOT mark the task succeeded.

#### Scenario: Session success does not free the worker
- **WHEN** the native Session has succeeded and the task is still `WAITING` for human confirmation
- **THEN** the employee remains occupied

#### Scenario: Unconfirmed cancel keeps the worker
- **WHEN** a task is `CANCELED` and its Session is still `UNKNOWN`
- **THEN** the employee remains occupied and heartbeat does not clear the occupancy count

#### Scenario: Human confirmation releases a stuck unknown session
- **WHEN** a person confirms that execution has stopped for a Session that remains `UNKNOWN`
- **THEN** the employee is no longer occupied by that task and the task is not marked succeeded

### Requirement: Command identity includes the session
The same `request_id` MUST return the stored command only when the Worker, command name, payload, and `session_id` all match. A different `session_id`, including null versus non-null, MUST be rejected with a conflict. A cancel MUST use its own request id and carry `target_request_id` in the payload. Canceling the HTTP wait MUST NOT abort the native OpenCode session; task cancellation MUST still call the native abort.

#### Scenario: Same request id on another session conflicts
- **WHEN** a stored request id is submitted again with a different session id
- **THEN** the command is rejected and the original row is not returned as a replay

#### Scenario: Cancel does not reuse the target request id
- **WHEN** a caller cancels an in-flight HTTP command
- **THEN** the cancel is stored under a new request id whose payload names the target, and the native session is not aborted by that cancel

### Requirement: Epoch changes fence a claim and an in-flight upload
Authorization to fetch or execute a command MUST come from the database epoch and command row. The Redis owner MUST only choose the publishing process. A command claimed before an epoch change MUST NOT be executed on the new epoch. An upload whose final compare-and-set no longer matches the current epoch MUST discard the stored body and MUST NOT wake the waiter or change `Task.status`.

#### Scenario: Epoch moves while a body is uploading
- **WHEN** the Worker epoch changes after a response upload has started and before its final update
- **THEN** the final update does not succeed, the waiter does not receive that body, and the task status stays unchanged
