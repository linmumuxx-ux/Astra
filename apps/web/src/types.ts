export interface Entity { id: string; revision: number; created_at: number; updated_at?: number }
export interface Team extends Entity { name: string; denied_actions: string[] }
export interface Role extends Entity { name: string; team_id: string; mandate: string; permissions: string[] }
export interface Employee extends Entity { name: string; team_id: string; role_id: string; manager_id: string; lifecycle: string; scope: Record<string, unknown>; permissions: string[]; daily_token_budget: number }
export interface Goal extends Entity { title: string; team_id: string; owner_employee_id: string | null; metric: string; scope: Record<string, unknown>; status: string }
export interface Task extends Entity { title: string; team_id: string; objective: string; owner_employee_id: string | null; acceptance_criteria: string[]; status: string; priority: number; risk_level: string; latest_result: unknown; read_only: boolean; goal_id?: string }
export interface Channel extends Entity { name: string; team_id: string; kind: string; member_ids?: string[] }
export interface Message extends Entity { content: string; sender_id: string; seq: number; mentions: string[]; attachment_refs: string[]; reply_to: string | null }
export interface Operation extends Entity { action: string; target_id: string; team_id: string; initiator_id: string; status: string; payload: Record<string, unknown>; expires_at: number; target_revision: number; policy_revision: number; result: unknown }
export interface Routine extends Entity { title: string; employee_id: string; kind: string; schedule: string; timezone: string; enabled: boolean; locked: boolean; next_due_at: number }
export interface Worker extends Entity { name: string; base_url: string; runtime_version?: string; health: string; capabilities: string[]; allowed_projects: string[]; workspace_roots: string[]; concurrent_slots: number; enabled: boolean; last_seen_at: number | null }
export interface Knowledge extends Entity { title: string; team_id: string; kind: string; content: string; verification: string; status: string; source_refs: string[] }
export interface Handoff extends Entity { task_id: string; source_employee_id: string; target_employee_id: string; status: string; reason: string }
export interface AuditEvent { seq: number; type: string; entity_ref: string; revision: number; actor_id: string; summary: string; created_at: number }
export interface Principal { id: string; name?: string; kind?: string; permissions?: string[]; [key: string]: unknown }
export type Detail = Record<string, unknown>
