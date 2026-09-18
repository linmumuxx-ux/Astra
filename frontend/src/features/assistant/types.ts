export type AssistantRole = 'USER' | 'ASSISTANT' | 'SYSTEM'

export type AssistantPartType =
  | 'TEXT'
  | 'TASK_CARD'
  | 'EMPLOYEE_CARD'
  | 'SESSION_CARD'
  | 'KNOWLEDGE_CARD'
  | 'CONFIRM_CARD'
  | 'STATUS'
  | 'ERROR'

export interface AssistantMessagePart {
  id: number
  part_type: AssistantPartType | string
  seq: number
  payload: Record<string, any>
  created_at: string
}

export interface AssistantMessage {
  id: string
  conversation_id: string
  role: AssistantRole | string
  message_type: string
  content: string
  status: 'PENDING' | 'STREAMING' | 'COMPLETED' | 'FAILED' | string
  created_at: string
  updated_at: string
  parts: AssistantMessagePart[]
}

export interface AssistantConversation {
  id: string
  user_id: string
  title: string
  status: string
  last_message_at: string | null
  created_at: string
  updated_at: string
}

export interface AssistantOperation {
  operation_id: string
  conversation_id: string | null
  operation_type: string
  risk_level: 'L1' | 'L2' | 'L3' | string
  status: string
  preview: Record<string, any>
  result: Record<string, any>
  expires_at: string | null
  confirmed_at: string | null
  executed_at: string | null
  created_at: string
}

export interface AssistantPageContext {
  route?: string
  type?: 'task' | 'employee' | 'session' | 'knowledge' | 'library' | 'dashboard'
  id?: string
}

export interface AssistantCardAction {
  type: 'navigate' | 'assistant_operation' | string
  label: string
  target?: string
  operation?: string
}

export interface AssistantCardPayload {
  card_type?: 'task' | 'employee' | 'session' | 'knowledge' | 'confirm' | string
  result?: Record<string, any>
  id?: string
  title?: string
  status?: string
  status_label?: string
  fields?: Array<{ label: string; value: string }>
  actions?: AssistantCardAction[]
  operation_id?: string
  operation_type?: string
  operation_label?: string
  risk_level?: string
  preview?: Record<string, any>
}

export interface AssistantEventEnvelope {
  event: string
  seq: number
  conversation_id: string
  message_id?: string | null
  timestamp: string
  data: Record<string, any>
}

export interface AssistantHealth {
  available: boolean
  assistant: string
  opencode_healthy: boolean
  opencode_version: string | null
  opencode_url: string
  detail: string
}

/**
 * 前端状态机：避免只用 loading = true / false，
 * 否则 Tool、确认、Streaming 场景很快会混乱。
 */
export type AssistantUiState =
  | 'IDLE'
  | 'SUBMITTING'
  | 'THINKING'
  | 'TOOL_RUNNING'
  | 'WAITING_CONFIRM'
  | 'STREAMING'
  | 'COMPLETED'
  | 'FAILED'
