## ADDED Requirements

### Requirement: 节点、资源池、路由和密钥管理
The control plane MUST manage nodes, pools, model routes and Gateway Keys with explicit access roles. It MUST encrypt downstream credentials at rest, store only Gateway Key hashes, and return plaintext Gateway Keys only at creation.

#### Scenario: Create node and Key
- **WHEN** an authorized administrator creates a node or Key
- **THEN** credentials are persisted securely, the response omits downstream secrets, and the Key plaintext is returned once

#### Scenario: Unauthorized mutation
- **WHEN** a caller lacks the required management role
- **THEN** the write is rejected and no configuration changes

#### Scenario: Delete active node
- **WHEN** a node still accepts or serves requests
- **THEN** deletion is rejected until it has drained and active concurrency is zero

### Requirement: 三维节点状态与探测
The control plane MUST represent configuration, health and scheduling states independently. It MUST support network, service and model/streaming probes and record timing, outcomes and success/failure streaks.

#### Scenario: New node
- **WHEN** a node has not passed the required probe sequence
- **THEN** it remains unschedulable with UNKNOWN health

#### Scenario: New node defaults to a safe state
- **WHEN** an administrator creates a node without explicitly choosing scheduling and configuration states
- **THEN** it is created DRAINING and DISABLED with UNKNOWN health, and cannot become ACTIVE without a completed probe (no implicit ACTIVE default)

#### Scenario: Draft edit is isolated from the published runtime
- **WHEN** an administrator edits an unpublished node's connection fields (base URL, credential, models, health path) or probes the draft
- **THEN** the published version's health and circuit runtime state is neither cleared nor rewritten, the previously published configuration keeps serving, and the changed connection must be probed before the new configuration can be scheduled

#### Scenario: Probe failures and recovery
- **WHEN** a node fails three successive checks or later passes two successive checks
- **THEN** health changes to UNHEALTHY or HEALTHY respectively without changing its administrator configuration state

### Requirement: Versioned publication
The control plane MUST keep edits as draft, validate all references before publication, publish immutable versioned snapshots, and support rollback by issuing a new version from a historical snapshot. Data plane instances MUST atomically adopt one published version.

#### Scenario: Publish invalid draft
- **WHEN** a draft has a route to a missing or disabled pool
- **THEN** publication fails and the currently published version stays active

#### Scenario: Connection change requires a fresh probe
- **WHEN** a new version changes a node's connection (base URL, credential, models or health path) and becomes current
- **THEN** the data plane treats that node as UNKNOWN until the changed connection passes its own probe, and earlier health or circuit results from the previous connection cannot authorise it

#### Scenario: Rollback
- **WHEN** an authorized administrator rolls back to an earlier version
- **THEN** a new version with that content becomes current and existing in-flight requests complete with their original snapshot

### Requirement: 吊销立即阻断
The control plane MUST make a revoked Gateway Key immediately unusable across all data plane instances, without waiting for a new publication. It MUST write an append-only shared revocation state before committing the database revocation, and MUST reject the revoke request with a structured 503 when that shared write fails without claiming success. A revoked Gateway Key MUST remain a permanent database tombstone: rolling back an earlier version MUST NOT delete its row, clear its revocation time or re-enable it, and a rollback whose snapshot contains that Key MUST produce a new snapshot that marks it disabled and revoked while preserving the current revocation time. Concurrent revocations and rollbacks MUST be serialized so a rollback cannot overwrite a revocation.

#### Scenario: Revoke a Key that is still enabled in the published snapshot
- **WHEN** an administrator revokes a Key that the currently published snapshot still lists as enabled
- **THEN** new requests with that Key are rejected immediately on every data plane instance, without publishing a new version

#### Scenario: Shared revocation write fails
- **WHEN** the shared revocation state cannot be written (for example Redis is unavailable)
- **THEN** the revoke request fails with a structured 503, the database revocation is not committed, and the response never claims success

#### Scenario: Rollback cannot revive a revoked Key
- **WHEN** an administrator rolls back to a version published before the Key was revoked and that version contains the Key
- **THEN** requests with that Key remain rejected, the database row keeps its revocation time, and the new snapshot marks the Key disabled and revoked

#### Scenario: Rollback to a version without the revoked Key
- **WHEN** an administrator rolls back to a version that does not contain a revoked Key
- **THEN** the revoked Key's database row is preserved as a tombstone instead of being deleted

#### Scenario: Concurrent revoke and rollback
- **WHEN** a revoke and a rollback run concurrently on the same Key
- **THEN** they are serialized on the Key row, so neither can overwrite the other and the Key stays revoked

### Requirement: 吊销状态的持久就绪
The shared revocation state MUST be append-only: synchronization MUST NOT clear existing entries or overwrite a concurrent revocation. Readiness MUST be a sentinel member inside the same revocation set, never a separate key, so that a Redis maxmemory eviction of the set removes the readiness sentinel together with the digests instead of leaving a false positive. Because Redis can be flushed or restarted, the data plane MUST append-sync all revoked Key digests from the database at startup and periodically, and mark the set ready in the same single `SADD` only after that sync. While the sentinel is missing or the shared state is unavailable, the data plane MUST fail closed. The data plane MUST read the sentinel and the digests as members of that one set in a single atomic operation; a missing sentinel MUST make that read itself fail closed, so a flush or whole-key eviction can never let a request through.

#### Scenario: Redis flushed or restarted
- **WHEN** the shared revocation set is lost, dropping the readiness sentinel together with every digest
- **THEN** new requests are rejected until a database sync rebuilds the set and its sentinel

#### Scenario: Revocation set key evicted
- **WHEN** Redis evicts the single revocation set key under maxmemory pressure
- **THEN** the sentinel disappears with the digests, so the atomic read fails closed and new requests are rejected until a database sync rebuilds the set; no request is authorized against an empty set

#### Scenario: Sentinel lost between independent reads
- **WHEN** the revocation set is flushed while a request is being authorized
- **THEN** the single atomic read fails closed and the request is rejected, never observing a present sentinel together with an empty set

#### Scenario: Concurrent synchronization and revocation
- **WHEN** synchronization runs while a revocation is being written concurrently
- **THEN** both previously revoked and concurrently revoked digests remain blocked

### Requirement: 操作审计
Every management mutation MUST record actor, timestamp, action, result and redacted before/after values without storing plaintext secrets.

#### Scenario: Update a node credential
- **WHEN** an administrator replaces a node credential
- **THEN** audit history identifies the change and never reveals either credential
