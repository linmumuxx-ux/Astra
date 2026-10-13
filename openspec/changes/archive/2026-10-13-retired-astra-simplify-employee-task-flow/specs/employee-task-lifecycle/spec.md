## ADDED Requirements

### Requirement: 持续工作与人工结束
任务 SHALL 默认复用当前会话，仅人工确认完成或终止进入业务终态；单轮回复、失败或超时 MUST NOT 自动结束任务。

#### Scenario: 多轮交流
- **WHEN** 模型完成一轮回复
- **THEN** 任务仍可继续交流，不弹出完成确认，不更换会话

#### Scenario: 原生人工介入
- **WHEN** 员工提出原生问题或权限请求
- **THEN** 用户 SHALL 能在 Workspace 回答并继续执行

#### Scenario: 执行失败与超时
- **WHEN** 当前轮失败或超时
- **THEN** 任务 SHALL 保留会话、工作区和错误信息，允许人工继续或终止

#### Scenario: 明确完成
- **WHEN** 用户确认完成且当前会话空闲、无待回答请求与未确认输入
- **THEN** 任务 SHALL 记录最终完成状态，后续刷新和延迟返回 MUST NOT 重开任务

#### Scenario: 终止和原生中断
- **WHEN** 用户终止任务，或只在原生界面停止当前回复
- **THEN** 前者 SHALL 取消任务，后者 SHALL 保留可继续的任务

#### Scenario: 断线重试和旧轮次隔离
- **WHEN** 输入确认丢失、断线重连或旧会话结果晚到
- **THEN** 系统 SHALL 核对原会话后重试，MUST NOT 重复发送已接受输入或覆盖新会话

### Requirement: 工作区及成果一致
本地和远程 SHALL 采用一致的 Worktree 归属、目录根和注册校验，保留员工自带配置，提供累计与当前未提交成果。

#### Scenario: 复用与配置
- **WHEN** 复用任务工作区
- **THEN** 系统 SHALL 拒绝错仓库、嵌套目录与符号链接，不覆盖任务自带 OpenCode 配置；缺少配置时继承项目配置

#### Scenario: 提交后查看
- **WHEN** 员工提交代码，用户查看任务代码变更
- **THEN** 累计变更 SHALL 仍包含已提交成果，当前未提交视图 SHALL 独立反映工作区状态，Diff MUST NOT 依赖外网

### Requirement: 简化入口和观察
创建任务 SHALL 无需完成策略或验收标准；平台 MUST NOT 自动发起经验复盘；运行中观察 SHALL 避免重复全量消息读取。

#### Scenario: 创建与观察
- **WHEN** 创建任务或员工正在回复
- **THEN** 用户 SHALL 能省略验收标准，后台 SHALL 保留必要断线核验但减少完整消息读取
