# Astra 1.0 当前 schema 数据字典

此快照由 `deploy/v1/export_contracts.py` 从新 ORM 生成；模型与静态 Alembic 迁移为实施事实源。
当前 30 张领域表，初始 revision `1000`；时间字段为 Unix 秒，原生 Session ID 为索引而非消息副本。
所有 Record 含稳定 UUID、revision 和 created_at；只有明确的一次性迁移可写只读历史记录。

## actors

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| kind | VARCHAR(16) | 否 | — |
| name | VARCHAR(120) | 否 | — |
| permissions | JSON | 否 | — |
| active | BOOLEAN | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## asset_locks

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| project_id | VARCHAR(200) | 否 | 唯一 |
| task_id | VARCHAR(36) | 是 | FK tasks.id |
| fence | INTEGER | 否 | — |
| expires_at | INTEGER | 否 | — |
| scope | TEXT | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：project_id。

## audit_events

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| seq | INTEGER | 否 | 主键 |
| actor_id | VARCHAR(36) | 否 | FK actors.id |
| team_id | VARCHAR(36) | 是 | FK teams.id |
| channel_id | VARCHAR(36) | 是 | FK channels.id |
| type | VARCHAR(80) | 否 | — |
| entity_ref | VARCHAR(200) | 否 | — |
| revision | INTEGER | 否 | — |
| summary | TEXT | 否 | — |
| created_at | INTEGER | 否 | — |

## budget_usage

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| actor_id | VARCHAR(36) | 否 | FK actors.id |
| purpose | VARCHAR(16) | 否 | — |
| native_session_id | VARCHAR(120) | 否 | — |
| model | VARCHAR(120) | 否 | — |
| tokens | INTEGER | 否 | — |
| cost_micros | INTEGER | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：actor_id, purpose, native_session_id。

## channel_members

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| channel_id | VARCHAR(36) | 否 | FK channels.id |
| actor_id | VARCHAR(36) | 否 | FK actors.id |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：channel_id, actor_id。

## channels

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| name | VARCHAR(240) | 否 | — |
| kind | VARCHAR(16) | 否 | — |
| read_only | BOOLEAN | 否 | — |
| dm_key | VARCHAR(80) | 是 | 唯一 |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：dm_key。

## credentials

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| actor_id | VARCHAR(36) | 否 | FK actors.id |
| digest | VARCHAR(64) | 否 | 唯一 |
| expires_at | INTEGER | 否 | — |
| revoked | BOOLEAN | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：digest。

## employee_state

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| employee_id | VARCHAR(36) | 否 | 唯一, FK employees.id |
| plan_digest | TEXT | 否 | — |
| memory_head | VARCHAR(64) | 是 | — |
| lease_until | INTEGER | 否 | — |
| fence | INTEGER | 否 | — |
| next_review | INTEGER | 是 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：employee_id。

## employee_turns

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| employee_id | VARCHAR(36) | 否 | FK employees.id |
| fence | INTEGER | 否 | — |
| status | VARCHAR(24) | 否 | — |
| native_session_id | VARCHAR(120) | 是 | — |
| input_refs | JSON | 否 | — |
| submission_started_at | INTEGER | 是 | — |
| budget_reservation | INTEGER | 否 | — |
| actions | JSON | 否 | — |
| finished_at | INTEGER | 是 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：employee_id, fence。

## employees

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| id | VARCHAR(36) | 否 | 主键, FK actors.id |
| name | VARCHAR(120) | 否 | — |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| role_id | VARCHAR(36) | 否 | FK roles.id |
| manager_id | VARCHAR(36) | 否 | FK actors.id |
| lifecycle | VARCHAR(16) | 否 | — |
| scope | JSON | 否 | — |
| permissions | JSON | 否 | — |
| daily_token_budget | INTEGER | 否 | — |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## goals

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| owner_employee_id | VARCHAR(36) | 是 | FK employees.id |
| title | VARCHAR(240) | 否 | — |
| metric | TEXT | 否 | — |
| scope | JSON | 否 | — |
| status | VARCHAR(24) | 否 | — |
| priority | INTEGER | 否 | — |
| deadline | INTEGER | 是 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## handoffs

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| task_id | VARCHAR(36) | 否 | FK tasks.id |
| source_employee_id | VARCHAR(36) | 否 | FK employees.id |
| target_employee_id | VARCHAR(36) | 否 | FK employees.id |
| status | VARCHAR(24) | 否 | — |
| task_revision | INTEGER | 否 | — |
| reason | TEXT | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## historical_artifacts

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| kind | VARCHAR(80) | 否 | — |
| content_ref | TEXT | 否 | — |
| sha256 | VARCHAR(64) | 否 | — |
| visibility | VARCHAR(16) | 否 | — |
| owner_actor_id | VARCHAR(36) | 是 | FK actors.id |
| read_only | BOOLEAN | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## inbox_admissions

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| employee_id | VARCHAR(36) | 否 | FK employees.id |
| source_event_id | VARCHAR(36) | 否 | FK source_events.id |
| reason | VARCHAR(120) | 否 | — |
| priority | INTEGER | 否 | — |
| wake_policy | VARCHAR(16) | 否 | — |
| observed_at | INTEGER | 是 | — |
| disposition | VARCHAR(24) | 是 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：employee_id, source_event_id。

## knowledge_items

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| created_by_actor | VARCHAR(36) | 否 | FK actors.id |
| title | VARCHAR(240) | 否 | — |
| kind | VARCHAR(24) | 否 | — |
| content | TEXT | 否 | — |
| source_refs | JSON | 否 | — |
| verification | VARCHAR(24) | 否 | — |
| status | VARCHAR(24) | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## messages

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| channel_id | VARCHAR(36) | 否 | FK channels.id |
| seq | INTEGER | 否 | — |
| sender_id | VARCHAR(36) | 否 | FK actors.id |
| content | TEXT | 否 | — |
| mentions | JSON | 否 | — |
| attachment_refs | JSON | 否 | — |
| reply_to | VARCHAR(36) | 是 | FK messages.id |
| causal_root | VARCHAR(200) | 否 | — |
| hops | INTEGER | 否 | — |
| provenance | JSON | 否 | — |
| fingerprint | VARCHAR(64) | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：channel_id, seq。

## mutations

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| actor_id | VARCHAR(36) | 否 | FK actors.id |
| operation_key | VARCHAR(120) | 否 | — |
| request_hash | VARCHAR(64) | 否 | — |
| response | JSON | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：actor_id, operation_key。

## operations

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| initiator_id | VARCHAR(36) | 否 | FK actors.id |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| action | VARCHAR(80) | 否 | — |
| target_id | VARCHAR(36) | 否 | — |
| target_revision | INTEGER | 否 | — |
| policy_revision | INTEGER | 否 | — |
| payload | JSON | 否 | — |
| status | VARCHAR(24) | 否 | — |
| expires_at | INTEGER | 否 | — |
| decision_note | TEXT | 否 | — |
| decided_by | VARCHAR(36) | 是 | FK actors.id |
| result | JSON | 是 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## roles

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| name | VARCHAR(120) | 否 | — |
| mandate | TEXT | 否 | — |
| permissions | JSON | 否 | — |
| skill_scope | JSON | 否 | — |
| knowledge_scope | JSON | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## routines

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| employee_id | VARCHAR(36) | 否 | FK employees.id |
| goal_id | VARCHAR(36) | 是 | FK goals.id |
| title | VARCHAR(240) | 否 | — |
| kind | VARCHAR(16) | 否 | — |
| schedule | VARCHAR(120) | 否 | — |
| timezone | VARCHAR(80) | 否 | — |
| enabled | BOOLEAN | 否 | — |
| locked | BOOLEAN | 否 | — |
| next_due_at | INTEGER | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## skill_versions

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| knowledge_id | VARCHAR(36) | 否 | FK knowledge_items.id |
| version | INTEGER | 否 | — |
| content | TEXT | 否 | — |
| validation_task_id | VARCHAR(36) | 是 | FK tasks.id |
| evidence_refs | JSON | 否 | — |
| published_by | VARCHAR(36) | 是 | FK actors.id |
| status | VARCHAR(24) | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：knowledge_id, version。

## source_events

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| source | VARCHAR(80) | 否 | — |
| source_id | VARCHAR(200) | 否 | — |
| actor_id | VARCHAR(36) | 否 | FK actors.id |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| object_ref | VARCHAR(200) | 否 | — |
| payload_ref | JSON | 否 | — |
| causal_root | VARCHAR(200) | 否 | — |
| occurred_at | INTEGER | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：source, source_id, revision。

## task_executions

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| task_id | VARCHAR(36) | 否 | FK tasks.id |
| worker_id | VARCHAR(36) | 否 | FK workers.id |
| native_session_id | VARCHAR(120) | 是 | — |
| workspace_ref | TEXT | 是 | — |
| attempt_no | INTEGER | 否 | — |
| lease_id | VARCHAR(36) | 是 | FK worker_leases.id |
| lease_fence | INTEGER | 是 | — |
| read_only | BOOLEAN | 否 | — |
| grant_snapshot | JSON | 否 | — |
| state | VARCHAR(24) | 否 | — |
| evidence_refs | JSON | 否 | — |
| output_ref | TEXT | 是 | — |
| started_at | INTEGER | 是 | — |
| finished_at | INTEGER | 是 | — |
| superseded_by | VARCHAR(36) | 是 | FK task_executions.id |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：task_id, attempt_no。

## task_reviews

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| task_id | VARCHAR(36) | 否 | FK tasks.id |
| execution_id | VARCHAR(36) | 否 | FK task_executions.id |
| reviewer_id | VARCHAR(36) | 否 | FK actors.id |
| outcome | VARCHAR(24) | 否 | — |
| criteria_results | JSON | 否 | — |
| evidence_refs | JSON | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## tasks

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| owner_employee_id | VARCHAR(36) | 是 | FK employees.id |
| created_by_actor | VARCHAR(36) | 否 | FK actors.id |
| goal_id | VARCHAR(36) | 是 | FK goals.id |
| source_event_id | VARCHAR(36) | 是 | FK source_events.id |
| title | VARCHAR(240) | 否 | — |
| objective | TEXT | 否 | — |
| acceptance_criteria | JSON | 否 | — |
| constraints | JSON | 否 | — |
| required_capabilities | JSON | 否 | — |
| asset_scope | JSON | 否 | — |
| status | VARCHAR(24) | 否 | — |
| priority | INTEGER | 否 | — |
| risk_level | VARCHAR(16) | 否 | — |
| continuity_key | VARCHAR(200) | 否 | — |
| parent_task_id | VARCHAR(36) | 是 | FK tasks.id |
| latest_result | JSON | 是 | — |
| read_only | BOOLEAN | 否 | — |
| completed_at | INTEGER | 是 | — |
| updated_at | INTEGER | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## team_members

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| actor_id | VARCHAR(36) | 否 | FK actors.id |
| role | VARCHAR(16) | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：team_id, actor_id。

## teams

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| name | VARCHAR(120) | 否 | — |
| denied_actions | JSON | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## worker_leases

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| worker_id | VARCHAR(36) | 否 | FK workers.id |
| slot | INTEGER | 否 | — |
| task_id | VARCHAR(36) | 是 | FK tasks.id |
| fence | INTEGER | 否 | — |
| expires_at | INTEGER | 否 | — |
| state | VARCHAR(24) | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：worker_id, slot。

## workers

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| name | VARCHAR(120) | 否 | — |
| base_url | VARCHAR(500) | 否 | — |
| runtime_version | VARCHAR(80) | 是 | — |
| capabilities | JSON | 否 | — |
| allowed_projects | JSON | 否 | — |
| workspace_roots | JSON | 否 | — |
| credential_ref | VARCHAR(240) | 是 | — |
| health | VARCHAR(24) | 否 | — |
| concurrent_slots | INTEGER | 否 | — |
| enabled | BOOLEAN | 否 | — |
| last_seen_at | INTEGER | 是 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

## workspace_grants

| 列 | 类型 | 可空 | 约束/关联 |
| --- | --- | --- | --- |
| actor_id | VARCHAR(36) | 否 | FK actors.id |
| team_id | VARCHAR(36) | 否 | FK teams.id |
| project_id | VARCHAR(200) | 否 | — |
| permissions | JSON | 否 | — |
| expires_at | INTEGER | 否 | — |
| id | VARCHAR(36) | 否 | 主键 |
| revision | INTEGER | 否 | — |
| created_at | INTEGER | 否 | — |

组合唯一约束：actor_id, project_id。
