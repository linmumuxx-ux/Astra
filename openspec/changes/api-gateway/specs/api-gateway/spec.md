## ADDED Requirements

### Requirement: 统一模型入口和密钥鉴权
Gateway MUST provide OpenAI-compatible model listing and chat completion endpoints and authenticate each request with an active Gateway Key. It MUST enforce allowed models, expiry and key concurrency without exposing downstream credentials.

#### Scenario: Authorized request
- **WHEN** a valid Key calls an allowed model
- **THEN** Gateway routes the request to an eligible downstream node and returns its compatible response

#### Scenario: Invalid or forbidden Key
- **WHEN** a Key is absent, expired, disabled or does not allow the requested model
- **THEN** Gateway rejects the request with a structured error before contacting a downstream node

### Requirement: 跨实例共享吊销阻断
Gateway MUST consult a shared, append-only revocation state before reading the request body and before dispatching downstream, and MUST reject a revoked Key immediately even when the published snapshot still lists it as enabled. It MUST fail closed with a structured error when the revocation state is unavailable or not yet synchronized, and MUST NOT disconnect already running streams. Readiness MUST be a sentinel member of the same revocation set, and Gateway MUST read that sentinel and the digest in a single atomic operation on the one set, so a missing sentinel fails closed on its own; it MUST NOT check readiness and the set in separate calls that a flush or a whole-key eviction could split.

#### Scenario: Revoked Key on a still-published snapshot
- **WHEN** a Key is revoked while the current published snapshot still enables it
- **THEN** both `/v1/models` and `/v1/chat/completions` reject it with a structured error before reading the body or contacting a downstream node

#### Scenario: Shared result across instances
- **WHEN** one instance observes a revocation through the shared state
- **THEN** every other instance rejects the same Key too

#### Scenario: Revocation state unavailable or not synchronized
- **WHEN** the shared revocation state is unreachable or its readiness sentinel is missing
- **THEN** Gateway rejects new requests with a structured 503 while already running streams complete normally

#### Scenario: Revocation set key evicted
- **WHEN** the single revocation set key is flushed or evicted while a request is being authorized
- **THEN** the sentinel is gone with the digests, the atomic read fails closed, and Gateway rejects the request instead of observing readiness with an empty set

### Requirement: 跨实例调度与限额
Gateway MUST apply node/key concurrency and node hourly/daily Token policies across instances. It MUST exclude disabled, draining, unhealthy, blocked, circuit-open and full nodes. It MUST select among remaining nodes primarily by least active load, adjusted by weight and remaining quota.

#### Scenario: Node is draining
- **WHEN** a node enters DRAINING while requests are active
- **THEN** existing requests continue and new requests use other eligible nodes

#### Scenario: Quota reaches stop threshold
- **WHEN** a node's completed usage reaches its configured stop limit
- **THEN** new requests are not scheduled to that node while in-flight requests continue

#### Scenario: Concurrent instances
- **WHEN** two Gateway instances select a node at its final free slot
- **THEN** at most one acquires the slot

### Requirement: 故障治理与安全重试
Gateway MUST use active and passive health signals, remove unhealthy nodes after repeated failures, restore them after repeated success, and operate CLOSED/OPEN/HALF_OPEN circuit states. It MAY retry on another node only when a transport error proves the request was not sent downstream.

#### Scenario: Health is scoped to the published connection
- **WHEN** a node's published connection differs from the connection that produced the current health or circuit result (for example after a publish, a draft edit, or an old instance still serving an older version)
- **THEN** Gateway does not authorise the new configuration with that mismatched result, across all instances, restarts, rollbacks, and unknown publish outcomes

#### Scenario: Missing runtime health is unknown
- **WHEN** a node has no runtime health record (reset, expired or lost runtime state), even if the published snapshot recorded HEALTHY
- **THEN** Gateway treats it as UNKNOWN and does not schedule it until runtime health is re-established, never falling back to the snapshot

#### Scenario: Connection fails before send
- **WHEN** a connection is refused before any HTTP request bytes are sent
- **THEN** Gateway may retry once on another eligible node and records the retry

#### Scenario: Downstream response has started
- **WHEN** response headers or any stream chunk has been received
- **THEN** Gateway never sends the same request to another node

#### Scenario: Recovery
- **WHEN** a removed node passes the required successive checks
- **THEN** it becomes eligible again if configuration and quotas allow it

### Requirement: Streaming transparency
Gateway MUST forward SSE/chunked response chunks as they arrive and close downstream connections when the client disconnects. It MUST record interrupted streams and release all concurrency slots.

#### Scenario: Stream succeeds
- **WHEN** downstream emits multiple SSE chunks
- **THEN** each chunk is forwarded without waiting for the full response and terminal usage is recorded when available

#### Scenario: Client disconnects
- **WHEN** the client disconnects mid-stream
- **THEN** Gateway closes downstream, records CLIENT_DISCONNECTED and releases concurrency leases
