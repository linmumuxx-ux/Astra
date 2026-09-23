## ADDED Requirements

### Requirement: 调用日志与错误分类
Gateway MUST record request ID, time, Key identity, model, pool, node, token usage, status, typed error, streaming flag, retry count and latency data. It MUST NOT store Prompt content or authorization headers.

#### Scenario: Failed upstream call
- **WHEN** an upstream connection times out
- **THEN** the log contains UPSTREAM_CONNECT_TIMEOUT and the associated routing context rather than an unclassified 500

#### Scenario: Unknown usage
- **WHEN** downstream omits usage
- **THEN** token counts are marked unknown instead of fabricated from bytes or set to zero

### Requirement: 容量与性能统计
The management API MUST expose recent and daily input/output/total Tokens, request counts, success rate, current/peak concurrency, QPS, connect time, TTFB, TTFT, duration and output TPS with trend and percentile views at node, pool, model and Key level.

#### Scenario: Examine a slow node
- **WHEN** an administrator opens node performance details
- **THEN** mean and p50/p95 TTFT and duration plus throughput trends can be inspected for the selected period

### Requirement: Gateway 实例与页面
The management API MUST report each Gateway instance heartbeat, software/config version, uptime, connections, request/error counters and available CPU/memory. Astra MUST provide an API 中转 first-level page with overview, node state, quotas, pools/routes, Keys, logs and version history using existing visual conventions.

#### Scenario: Instance stops heartbeating
- **WHEN** an instance heartbeat expires
- **THEN** the overview marks the instance unavailable without inferring node health from that instance

#### Scenario: Key owner views usage
- **WHEN** a non-admin Key owner opens usage
- **THEN** only that Key's metrics and records are visible
