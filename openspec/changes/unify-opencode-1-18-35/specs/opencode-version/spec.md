## ADDED Requirements

### Requirement: Single supported OpenCode version

系统 SHALL 只接受 OpenCode 1.18.35 作为可启动的 Server 版本。版本检查开启时，缺失版本、1.2.27、1.18.25 和 1.18.33 SHALL 被拒绝。显式关闭检查后，其他版本可以通过。`0.0.0` SHALL NOT 作为关闭检查的写法。

#### Scenario: Supported release passes

- **WHEN** 版本检查开启且 Server 报告 `1.18.35` 或 `v1.18.35`
- **THEN** 版本检查通过

#### Scenario: Retired and other releases fail

- **WHEN** 版本检查开启且 Server 报告 `1.2.27`、`1.18.25`、`1.18.33` 或没有版本
- **THEN** 版本检查失败并说明唯一支持版本

#### Scenario: Check can be disabled explicitly

- **WHEN** 版本检查被显式关闭
- **THEN** 其他版本不再因版本号被拒绝

### Requirement: Recorded versions stay unchanged

系统 SHALL 保留 Session 环境快照中已经写入的 OpenCode 版本。健康检查没有版本时，新快照 SHALL 记录为未知，SHALL NOT 写入 1.18.35 或任何已退役版本。

#### Scenario: Missing health version is unknown

- **WHEN** 新 Session 的健康检查没有版本
- **THEN** 快照中的版本为未知

#### Scenario: Historical version is not rewritten

- **WHEN** 已有 Session 的快照版本是 1.18.31 或没有版本字段
- **THEN** 读取工作区不会把该字段改成 1.18.35 或 1.2.27

### Requirement: Retired workspace UI is visible

系统 SHALL 只为已安装界面包的记录版本返回界面地址。未知版本或界面包已删除的版本 SHALL 返回空界面地址，并显示「版本未知/界面已退役」。响应仍 SHALL 带回原记录版本；没有记录时显示未知。

#### Scenario: Current bundle is served

- **WHEN** Session 记录的版本是 1.18.35 且该界面包存在
- **THEN** 工作区响应包含该版本的界面地址且没有界面错误

#### Scenario: Retired bundle is not substituted

- **WHEN** Session 记录的版本是 1.18.31 或 9.9.9，且没有对应界面包
- **THEN** 界面地址为空，错误包含「版本未知/界面已退役」，记录版本保持不变

#### Scenario: Unknown snapshot does not fall back

- **WHEN** Session 快照没有 OpenCode 版本
- **THEN** 响应版本为未知，界面地址为空，错误为「版本未知/界面已退役」
