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
管理 API MUST 展示各 Gateway 实例心跳、软件版本、运行时长、连接数、请求/错误计数与可用 CPU/内存。Astra MUST 沿用已有视觉约定提供 API 中转一级页面，包含总览、节点、额度、资源池/路由、Key 与调用日志，不提供配置版本或独立 Key 自助门户。

#### Scenario: Instance stops heartbeating
- **WHEN** an instance heartbeat expires
- **THEN** the overview marks the instance unavailable without inferring node health from that instance

#### Scenario: 在管理台查看 Key 用量
- **WHEN** 使用者在调用日志按 Key 筛选或查看对应统计
- **THEN** 数据按该 Key 展示，无需在另一个页面输入 Key 原文

#### Scenario: 删除独立自助门户
- **WHEN** 使用者打开管理台或请求旧自助用量接口
- **THEN** 管理台不提供自助用量页面、Key 会话缓存或登录入口，旧自助接口不可用；模型调用仍要求有效 Gateway Key
