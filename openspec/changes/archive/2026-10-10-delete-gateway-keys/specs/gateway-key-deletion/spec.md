## ADDED Requirements

### Requirement: 独立删除 Key

API Key 管理 MUST 提供独立于编辑和吊销的删除入口，允许删除启用、停用和已吊销 Key。删除 MUST 在明确确认后执行，成功后从管理列表移除且刷新后仍不出现；已删除 Key MUST 不再允许编辑或吊销。

#### Scenario: 确认删除并刷新
- **WHEN** 使用者确认删除一个启用、停用或已吊销 Key
- **THEN** 删除成功，该 Key 从列表和计数中移除，刷新页面后仍不出现

#### Scenario: 取消删除
- **WHEN** 使用者打开删除确认后选择取消
- **THEN** 不发送删除请求，Key 状态和列表保持不变

#### Scenario: 删除失败后重试
- **WHEN** 删除请求失败，之后使用者重新确认删除且请求成功
- **THEN** 失败时显示原因并保留 Key，重试成功后从列表移除

#### Scenario: 删除分页末行
- **WHEN** 使用者删除最后一页的最后一个 Key
- **THEN** 列表自动回到仍有效的页码，不显示可避免的空页

#### Scenario: 已删除 Key 不可修改
- **WHEN** 调用方尝试编辑或吊销已删除 Key
- **THEN** 接口返回不存在，Key 不能恢复为可用状态

### Requirement: 删除保持永久阻断和历史

删除 MUST 立即阻断 Key 的新请求，并保留旧吊销时间、历史调用和审计。共享阻断写入失败 MUST 返回结构化 503，且不保存删除或吊销状态。共享阻断状态丢失后，系统 MUST 继续从持久数据恢复已删除 Key 的阻断。

#### Scenario: 删除启用 Key
- **WHEN** 删除的数据面内存配置仍包含该启用 Key
- **THEN** 新请求立即被阻断，历史调用保留，并可查询删除审计

#### Scenario: 删除已吊销 Key
- **WHEN** 使用者删除一个已吊销 Key
- **THEN** 原吊销时间及历史审计保留，并新增删除审计

#### Scenario: 共享状态不可用
- **WHEN** 删除时无法写入共享阻断状态
- **THEN** 返回结构化 503，Key 仍在列表且未保存新的吊销或删除状态

#### Scenario: 删除后共享状态重建
- **WHEN** 已删除 Key 的共享阻断状态丢失并从持久数据重建
- **THEN** 该 Key 仍被阻断，不会因旧缓存配置而重新获得访问权限

### Requirement: 删除与吊销接口语义

控制面 MUST 用 `DELETE /api/gateway/keys/{id}` 执行删除并在成功时返回 204；独立吊销 MUST 用 `POST /api/gateway/keys/{id}/revoke` 返回已吊销 Key，吊销后记录仍可在列表查询。

#### Scenario: 仅吊销
- **WHEN** 使用者确认吊销一个 Key
- **THEN** Key 立即失效，记录仍在列表且显示已吊销
