import type {
  AssistantConversation,
  AssistantHealth,
  AssistantMessage,
  AssistantOperation,
  AssistantPageContext,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export class AssistantApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new AssistantApiError(body.detail ?? '请求失败', response.status)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return response.json() as Promise<T>
}

export const assistantApi = {
  health: () => request<AssistantHealth>('/api/assistant/health'),
  conversations: () => request<AssistantConversation[]>('/api/assistant/conversations'),
  createConversation: (title?: string) =>
    request<AssistantConversation>('/api/assistant/conversations', {
      method: 'POST',
      body: JSON.stringify(title ? { title } : {}),
    }),
  deleteConversation: (id: string) =>
    request<void>(`/api/assistant/conversations/${id}`, { method: 'DELETE' }),
  messages: (conversationId: string) =>
    request<AssistantMessage[]>(`/api/assistant/conversations/${conversationId}/messages`),
  sendMessage: (conversationId: string, content: string, pageContext?: AssistantPageContext | null) =>
    request<AssistantMessage>(`/api/assistant/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content, page_context: pageContext ?? null }),
    }),
  abort: (conversationId: string) =>
    request<{ status: string }>(`/api/assistant/conversations/${conversationId}/abort`, {
      method: 'POST',
    }),
  operation: (operationId: string) =>
    request<AssistantOperation>(`/api/assistant/operations/${operationId}`),
  confirmOperation: (operationId: string) =>
    request<AssistantOperation>(`/api/assistant/operations/${operationId}/confirm`, {
      method: 'POST',
    }),
  cancelOperation: (operationId: string) =>
    request<AssistantOperation>(`/api/assistant/operations/${operationId}/cancel`, {
      method: 'POST',
    }),
  eventsUrl: (conversationId: string, afterSeq = 0) =>
    `${API_BASE}/api/assistant/conversations/${conversationId}/events?after_seq=${afterSeq}`,
}
