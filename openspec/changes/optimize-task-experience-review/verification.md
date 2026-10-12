# OpenSpec 核实：optimize-task-experience-review

| 维度 | 结果 |
| --- | --- |
| 完整性 | 6/6 tasks，5 项 Requirement 均已实现 |
| 正确性 | 下列场景有代码、针对性测试或真实链路证据 |
| 一致性 | 复用现有表、轮次与租约；原生执行事实、人工完成、经验验证和发布保持独立 |

| Scenario | 实现与验证 |
| --- | --- |
| 确认完成时观察器尚未同步 | lifecycle.confirm_completion 同步主 Session；test_confirmation_syncs_native_root_before_review_dispatch；真实端到端绕过观察器后确认；test_review_capture_failure_does_not_block_human_completion 验证消息读取失败不阻断业务完成 |
| 普通回复、人工等待、失败或取消 | review_ready 与扫描只接受 SUCCEEDED；test_unconfirmed_rounds_do_not_dispatch_or_submit；真实执行结束前扫描无复盘 |
| 重复调度与提交 | Task 行锁、TaskReview 轮次 ID/CAS 租约、完成结果复用；test_structured_review_preserves_correction_and_candidate；真实重复扫描无派发 |
| 失败与超时重试 | 原记录 retry_at/status 重置；test_dispatch_failure_retry_and_durable_lease、test_failed_review_retry_reuses_record_and_completed_retry_is_noop、test_expired_review_can_retry_but_live_lease_cannot |
| 任务重新执行 | 提交前后双重核对 Task/Session/轮次与 superseded_by；test_old_session_and_old_round_cannot_overwrite、test_evidence_read_race_cannot_write_old_round |
| 无可复用价值 | test_no_experience_is_valid；真实助手夹具中的“回复收到”无候选；超过两条的独立价值校验另有测试 |
| 员工能力边界 | 员工 MCP 删除提交工具与 submit scope，员工 Prompt 明确只执行；test_employee_mcp_exposes_read_and_feedback_without_experience_submission |
| 不同措辞的相似经验 | nexus_experience_search 与 merge_into_id/reason；test_semantic_merge_retains_evidence_and_links_both_tasks；真实两个任务复用同一经验 |
| 已有正式知识 | test_published_experience_reuse_only_appends_evidence；内容编辑后撤销验证与刷新指纹另有测试 |
| 无依据或未验证 | 原生分页、消息/片段/摘录核对；test_evidence_is_checked_before_atomic_save、test_task_success_is_not_experience_verification、test_failed_command_cannot_be_marked_verified；真实工具输出验证 |
| 候选隔离与人工发布 | 保留 library reviewer 权限与发布同步逻辑；既有 library 测试及真实 HTTP 查看者 403/审核者成功 |
| 查看失败并重试 | review API、任务详情抽屉；test_review_api_exposes_failure_and_retries_same_record；Chromium 新增复盘抽屉用例通过 |

精确重复并发额外验证：test_concurrent_exact_submissions_share_one_record 使用真实文件 SQLite 和两个独立数据库会话并行提交，返回同一知识 ID，只有一条记录。

没有本次变更的未实现契约。全量质量门禁有一项既有网关测试失败；真实环境未覆盖 MySQL、SSH 和正式 Wiki 写入，不宣称这些验证通过。详见 [验证记录](../../../evidence/task-experience-review-20261011/README.md)。本 change 保留为已完成、可评审状态。
