## ADDED Requirements

### Requirement: 持久 Channel 与隔离
系统 MUST 支持人机/员工 DM 与混合 Group、附件/引用/@/成员授权及外部 Binding，Session 重建不丢长期对话。

#### Scenario: 持久 Channel 与隔离验收
- **WHEN** 非成员读取消息或已撤权 SSE 重连
- **THEN** 拒绝且不泄露，原成员仍有持久消息

### Requirement: 正式跨岗交接
系统 MUST 支持交接提出/接受/拒绝/澄清/回执与唯一主责原子变更。

#### Scenario: 正式跨岗交接验收
- **WHEN** 仅发群消息或被交接人正式接受
- **THEN** 消息不改变责任，正式接受才转移并审计

### Requirement: 冲突与防循环
系统 MUST 支持causal_root、TTL、fingerprint、回合预算限制自动消息；同级冲突请求负责人裁决。

#### Scenario: 冲突与防循环验收
- **WHEN** 无新增事实自动往返或同级指令矛盾
- **THEN** 停止回声和受影响不可逆行动，其他工作继续
