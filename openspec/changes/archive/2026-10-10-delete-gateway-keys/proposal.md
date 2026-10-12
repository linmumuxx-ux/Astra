## Why

API Key 管理只有编辑和吊销，吊销后的 Key 仍占据列表，使用者无法删除不用的记录。需要提供可确认的删除操作，并保持既有吊销阻断和历史审计能力。

## What Changes

- 增加独立删除按钮，确认后让 Key 立即失效并从管理列表移除；刷新后不会重新出现。
- 删除保留数据库中的密钥摘要、吊销信息、历史调用和审计，防止共享阻断状态重建后旧 Key 复活。
- **BREAKING**：`DELETE /api/gateway/keys/{id}` 改为删除并返回 204；原吊销操作改用 `POST /api/gateway/keys/{id}/revoke`，仍返回吊销后的 Key。
- 删除失败保留列表记录并提示原因，取消确认不发送写请求。

## Capabilities

### New Capabilities

- `gateway-key-deletion`：Key 删除、与吊销的区分、持久阻断与历史保留。`openspec/specs/` 尚无 Gateway 正式 capability；既有约束参照进行中的 `api-gateway/specs/gateway-control`，本次不改写该 change。

### Modified Capabilities

无。

## Impact

影响 Gateway Key 控制面路由、服务、模型及数据库迁移，前端 API 层、Key 列表和对应测试。数据面沿用现有吊销同步；不提供恢复删除、批量删除或历史清理功能。
