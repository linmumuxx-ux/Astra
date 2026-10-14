## Why

组内 AI 工具直接连接个人维护的 Proxy，节点故障、额度耗尽和性能下降难以统一发现和治理。Astra 需要一个独立于任务 Runtime 的模型 API 入口，集中管理节点、调度、额度和调用证据。

## What Changes

- 新增独立运行的 `astra-gateway`，提供 OpenAI 兼容的 `/v1/models` 与 `/v1/chat/completions`，透传非流式与流式响应。
- 新增 Astra 控制面：节点、资源池、模型路由、Gateway Key、健康探测、审计与统计。配置保存后自动生效，删除草稿、版本、手动发布、回滚与对账。
- Redis 维护跨实例并发、周期 Token、健康/熔断、Key 吊销与心跳；MySQL 配置表是唯一配置事实源，Gateway 启动及后台周期读取一致视图。
- 「API 中转」一级导航只保留总览、节点、资源池/路由、Key 与调用日志。
- 控制面直接随 Astra 管理台使用，删除独立管理登录、管理 Token、角色权限与 Key 自助门户；模型调用继续使用 Gateway Key 鉴权。
- 新增独立服务启动和部署配置。第一阶段不承担下游 Token 刷新、模型协议转换、模型计费或 Prompt 审计。

## Capabilities

### New Capabilities

- `api-gateway`: 模型统一入口、鉴权、调度、限额、透传、重试与故障治理。
- `gateway-control`: 控制面配置、保存后自动生效、探测与审计。
- `gateway-observability`: 请求记录、Token 和性能统计、实例运行状态与管理页面。

### Modified Capabilities

无。现有 Task/Employee/Session Runtime 行为保持不变。

## Impact

涉及 `backend/app/gateway/`、`backend/app/api/`、`backend/alembic/versions/`、`frontend/src/`、`scripts/astra_service.py` 和 `deploy/`。需要 MySQL 与 Redis；Gateway 独立进程运行，控制面仍由 Astra Backend 提供。
