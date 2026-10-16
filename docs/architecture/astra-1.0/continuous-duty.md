# 持续职责当前行为

实现位于 `domains/personas/routines.py` 与 `apps/services/routines.py`。计划只属于 Employee / Goal，不属于模型 Session；组织锁定、岗位权限与个人主责在同一业务服务校验。创建和 PATCH 都调用该服务，不另存 `scope.routine_ids` 授权配置。

INTERVAL 以正整数秒表示；CRON 为五字段，字段解析复用 Celery，日期匹配采用日/月/星期 AND 语义。按 IANA 时区生成真实未来时刻，跳过夏令时不存在时间并正确处理回拨的两个时刻。EVENT 填明确来源名，不参加定时扫描。下次触发时间由后端计算，客户端不能直接写 next_due_at。

到期时以 Routine 当前 revision 条件更新，生成一个带 scheduled_for 的不可变 SourceEvent；长时间积压只汇总一次并推进到当前时间之后，不补跑全部历史时间片。Inbox 唯一 employee/event，多个规则命中同事件仍只有一个关注关系。Channel EVENT 计划还检查员工当前 Channel 成员资格，不能把他人私人 DM 投给本团队所有员工。

人类凭 routine.manage 在团队内配置；员工还必须为计划本人、计划未锁定，若关联 Goal 则为该 Goal 当前业务主责。系统只有经过签发认证的 routine.signal 与指定团队成员关系，不能编辑计划。员工暂停/归档后不进入到期投递；恢复 Routine 重算未来时间。手动 Run Now 可形成新关注事件，不直接创建 Task。

`apps/services/personas.py` 已接短原生模型 Session、严格 JSON 有限决策、观察/处理分离和 Git Memory。九种动作均调用新领域服务；dispatch 创建 Task 并绑定 Worker lease，工程运行器取得原生事实后启动。Task 提交产生结果 Inbox；review 只能验收该 Inbox 引用的具体提交，逐条核对原始标准、工具输入/退出码/输出及提交哈希，不凭 Worker 自述关闭工作。

回合持久保存 Inbox 输入引用、身份/岗位/策略/记忆版本、原生 Session ID、提交开始标记与预算预留。重启只查询原 Session，不重发已开始提交的 prompt。动作与 disposition、计划和 Turn 完成同一事务；无效决策事务回滚并记录 FAILED 与拒绝原因，保留已观察事实，关注事项延后至少 60 秒重新判断。新回合可见同一 Channel 范围的拒绝原因，仍受预算控制；网络结果未知时保持原生绑定，不以新回合盲重发。失效 fence、员工暂停或服务凭据撤销阻止动作。

新增推理前计入当日真实用量及未完成对账的回合预留；原生用量按 PERSONA 单独归属，未知不按零消耗处理。当前预留不是供应商硬 Token 上限，完整网关限流与配额仍待接线。

真实 OpenCode 1.18.35 / deepseek-flash 已通过两次独立 Session 的记忆写入与回忆，以及第三次由真实 Redis/Celery/Beat 触发的 Routine 静默记档。详见 `persona-live-report.json`；它不代表多员工工程协作全量验收。

当前运行版本统一 1.19.0，拒绝其他版本和自动回退。`employee-review-live-report.json` 记录 1.19.0 上工程与独立员工 Persona 两个不同原生 Session 的真实验收通过；旧 1.18.35 报告保留其原始验证版本，不改写成新版本证据。原 Task 返工续做已通过真实双工程/三短回合验收，完整多员工与成长链仍未验收。
