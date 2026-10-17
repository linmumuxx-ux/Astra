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
The system MUST store a command before publishing it. The same `request_id` with the same Worker, command name, and payload MUST return the stored command and MUST NOT publish it again. A conflicting Worker, name, or payload MUST be rejected. An offline Worker MUST persist the command as failed with `offline`. A full control queue MUST leave the command pending. Idempotent commands MUST be retried by the current owner after the dispatch lease expires. A side-effect command such as `prompt` MUST NOT be published again while its result is unknown.

#### Scenario: Duplicate request is not delivered twice
- **WHEN** a caller submits a request id that is already stored
- **THEN** the original command is returned and the route publishes once

#### Scenario: Publish sees the stored row
- **WHEN** the route publishes a new command
- **THEN** the command row is already pending

### Requirement: Routing has one owner
The process holding the socket MUST be the only owner for that epoch. Registration MUST reject an older epoch. Another memory bus MUST NOT observe that owner. Redis clients using the same prefix MUST observe it. Clearing an older epoch or a different owner MUST leave the current lease in place. Publish, consume, and send MUST fence on the target epoch. A consumer that loses ownership MUST stop. Control frames MUST be delivered before queued events, and a full event queue MUST drop events instead of blocking control.

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
