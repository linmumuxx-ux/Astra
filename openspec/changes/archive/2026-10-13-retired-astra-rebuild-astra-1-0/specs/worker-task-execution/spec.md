## ADDED Requirements

### Requirement: 执行资源隔离
系统 MUST 支持Worker 能力/授权/健康/容量租约和 fencing，工程 worktree/资产锁；同员工多任务并行。

#### Scenario: 执行资源隔离验收
- **WHEN** 多员工共享 Worker 并发抢租约
- **THEN** 不超容量、不跨授权、不共享任务写工作区

### Requirement: 原生执行与独立验收
系统 MUST 支持Task 唯一主责；TaskExecution 仅索引原生 Session/Workspace/证据/用量，不复制 Transcript；员工按标准验收、返工或跟踪。

#### Scenario: 原生执行与独立验收验收
- **WHEN** Worker 声称成功却无可核验证据
- **THEN** 不得完成 Task，支持人工介入和后续 Goal 检查

#### Scenario: 返工保留产物和责任
- **WHEN** 员工引用真实失败工具结果逐条判定返工，并对原 Task 再派工
- **THEN** 原始目标和标准不变，下一独立 Session/工作区以已核验不可变产物为基线；保留来源验收及 superseded_by，旧尝试不得覆盖新结果；缺失产物时拒绝退回默认基线盲重跑

### Requirement: 恢复与旧轮次隔离
系统 MUST 支持取消/重试/超时/断线/接管/重启先对账，旧尝试不覆盖新结果。

#### Scenario: 恢复与旧轮次隔离验收
- **WHEN** Worker 失联或停止副作用未知或旧 attempt 返回
- **THEN** 记录未知并拒绝盲重跑及过期写入

### Requirement: 真实 Runtime 兼容
系统 MUST 支持公司 Linux 主机及 SSH 与固定的单一 OpenCode 版本真实契约验证。当前部署目标版本为 `1.19.0`；版本升级必须先完成真实 Session/Tool/恢复契约验证，运行时不得自动回退其他版本。

#### Scenario: 真实 Runtime 兼容验收
- **WHEN** Runtime 版本不兼容
- **THEN** 明确拒绝并显示诊断，不伪造执行
