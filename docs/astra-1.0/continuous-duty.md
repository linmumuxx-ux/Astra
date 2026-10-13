# 持续职责当前行为

实现位于 `domains/personas/routines.py` 与 `apps/services/routines.py`。计划只属于 Employee / Goal，不属于模型 Session；组织锁定、岗位权限与个人主责在同一业务服务校验。创建和 PATCH 都调用该服务，不另存 `scope.routine_ids` 授权配置。

INTERVAL 以正整数秒表示；CRON 为五字段，字段解析复用 Celery，日期匹配采用日/月/星期 AND 语义。按 IANA 时区生成真实未来时刻，跳过夏令时不存在时间并正确处理回拨的两个时刻。EVENT 填明确来源名，不参加定时扫描。下次触发时间由后端计算，客户端不能直接写 next_due_at。

到期时以 Routine 当前 revision 条件更新，生成一个带 scheduled_for 的不可变 SourceEvent；长时间积压只汇总一次并推进到当前时间之后，不补跑全部历史时间片。Inbox 唯一 employee/event，多个规则命中同事件仍只有一个关注关系。Channel EVENT 计划还检查员工当前 Channel 成员资格，不能把他人私人 DM 投给本团队所有员工。

人类凭 routine.manage 在团队内配置；员工还必须为计划本人、计划未锁定，若关联 Goal 则为该 Goal 当前业务主责。系统只有经过签发认证的 routine.signal 与指定团队成员关系，不能编辑计划。员工暂停/归档后不进入到期投递；恢复 Routine 重算未来时间。手动 Run Now 可形成新关注事件，不直接创建 Task。

`apps/services/personas.py` 已接短原生模型 Session、严格 JSON 有限决策、观察/处理分离和 Git Memory。七种动作使用原有业务领域服务；dispatch 当前创建 Task 并绑定 Worker lease，不假报工程已启动。实际工程启动、独立验收和 Task 结果入站仍须完成。

回合持久保存 Inbox 输入引用、身份/岗位/策略/记忆版本、原生 Session ID、提交开始标记与预算预留。重启只查询原 Session，不重发已开始提交的 prompt。动作与 disposition、计划和 Turn 完成同一事务；失败保留已观察、未处理。失效 fence、员工暂停或服务凭据撤销阻止动作。

新增推理前计入当日真实用量及未完成对账的回合预留；原生用量按 PERSONA 单独归属，未知不按零消耗处理。当前预留不是供应商硬 Token 上限，完整网关限流与配额仍待接线。

真实 OpenCode 1.18.35 / deepseek-flash 已通过两次独立 Session 的记忆写入与回忆，以及第三次由真实 Redis/Celery/Beat 触发的 Routine 静默记档。详见 `persona-live-report.json`；它不代表多员工工程协作全量验收。
