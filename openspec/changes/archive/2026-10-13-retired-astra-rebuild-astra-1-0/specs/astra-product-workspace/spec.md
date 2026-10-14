## ADDED Requirements

### Requirement: 九类真实工作页面
系统 MUST 支持/space、/employees/:id、/channels、/tasks/:id、/attention、/organization、/library、/resources、/governance 全覆盖真实 API。

#### Scenario: 九类真实工作页面验收
- **WHEN** 空间→员工 DM→Task→批准→回到 DM
- **THEN** 真实状态一致，来源上下文保留，无假数据/空操作

### Requirement: 轻量动态空间
系统 MUST 支持离线 Three.js 低多边形场景、按需渲染/动态人数/减少动态效果/2D 降级，可访问 Element Plus DOM 业务叠层。

#### Scenario: 轻量动态空间验收
- **WHEN** 人数增加或 WebGL 不可用
- **THEN** 动态布局或 2D 降级，键盘可操作，不伪造思考动画

### Requirement: 状态与 SSE 恢复
系统 MUST 支持持久业务事件 seq/权限重查/after 重连/快照，加载/空/异常/离线/无权限完整反馈。

#### Scenario: 状态与 SSE 恢复验收
- **WHEN** 断线重连或游标过期
- **THEN** 刷新权威快照，不丢事实、不泄露已撤权信息
