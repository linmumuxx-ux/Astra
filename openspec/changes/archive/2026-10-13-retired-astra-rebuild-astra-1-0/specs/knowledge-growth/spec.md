## ADDED Requirements

### Requirement: 知识与个人记忆分离
系统 MUST 支持统一原始资料/Wiki/经验/Skill，来源/权限/验证状态；个人 Git Memory 限长/索引/纠错/过期。

#### Scenario: 知识与个人记忆分离验收
- **WHEN** 检索其他员工私有记忆或未经验证经验
- **THEN** 按权限拒绝或显式标为候选，不自动发布

### Requirement: 受控成长链路
系统 MUST 支持验收→经验候选→知识发布→Skill 提案→Worker 验证→审批→版本发布→效果观测与回滚。

#### Scenario: 受控成长链路验收
- **WHEN** 无验证证据发布 Skill 或撤销发布权限
- **THEN** 拒绝发布，已有版本可审计恢复
