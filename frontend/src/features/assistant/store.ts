import { defineStore } from 'pinia'
import { assistantApi, AssistantApiError } from './api'
import type {
  AssistantConversation,
  AssistantEventEnvelope,
  AssistantHealth,
  AssistantMessage,
  AssistantMessagePart,
  AssistantPageContext,
  AssistantUiState,
} from './types'

function pageContextFromLocation(): AssistantPageContext | null {
  const path = window.location.pathname
  const match = (prefix: string) => {
    if (!path.startsWith(prefix)) return null
    const id = path.slice(prefix.length).split('/')[0]
    return id || null
  }
  if (path === '/' ) return { route: path, type: 'dashboard' }
  const taskId = match('/tasks/')
  if (taskId) return { route: path, type: 'task', id: taskId }
  const employeeId = match('/employees/')
  if (employeeId) return { route: path, type: 'employee', id: employeeId }
  if (path.startsWith('/library')) return { route: path, type: 'library' }
  return null
}

export const useAssistantStore = defineStore('assistant', {
  state: () => ({
    open: false,
    health: null as AssistantHealth | null,
    conversations: [] as AssistantConversation[],
    activeId: null as string | null,
    messages: [] as AssistantMessage[],
    uiState: 'IDLE' as AssistantUiState,
    statusText: '',
    error: '',
    eventsConnected: false,
    lastSeq: 0,
    eventSource: null as EventSource | null,
    reconnectTimer: null as ReturnType<typeof setTimeout> | null,
    initialized: false,
    initializing: false,
    conversationPending: false,
  }),

  getters: {
    unavailable(): boolean {
      return this.health !== null && !this.health.available
    },
    activeConversation(): AssistantConversation | null {
      return this.conversations.find((item) => item.id === this.activeId) ?? null
    },
    waitingConfirm(): boolean {
      return this.messages.some((message) =>
        message.parts.some(
          (part) => part.part_type === 'CONFIRM_CARD' && part.payload?.status === 'WAITING_CONFIRM',
        ),
      )
    },
    busy(): boolean {
      return ['SUBMITTING', 'THINKING', 'TOOL_RUNNING', 'STREAMING'].includes(this.uiState)
    },
  },

  actions: {
    async init() {
      if (this.initializing) return
      this.initializing = true
      try {
        await this.loadHealth()
        if (!this.health?.available) return
        if (!this.initialized) {
          await this.loadConversations()
          this.initialized = true
        }
      } finally {
        this.initializing = false
      }
    },

    async loadHealth() {
      try {
        this.health = await assistantApi.health()
      } catch {
        this.health = {
          available: false,
          assistant: 'unreachable',
          opencode_healthy: false,
          opencode_version: null,
          opencode_url: '',
          detail: '助手服务不可达',
        }
      }
    },

    async loadConversations() {
      try {
        this.conversations = await assistantApi.conversations()
        if (!this.activeId && this.conversations.length) {
          await this.selectConversation(this.conversations[0].id)
        }
      } catch (error) {
        this.error = error instanceof Error ? error.message : '加载会话失败'
      }
    },

    openDrawer() {
      this.open = true
      void this.init()
    },

    closeDrawer() {
      this.open = false
    },

    async createConversation(title?: string) {
      if (this.conversationPending) return null
      this.conversationPending = true
      try {
        const conversation = await assistantApi.createConversation(title)
        this.conversations.unshift(conversation)
        await this.selectConversation(conversation.id)
        return conversation
      } finally {
        this.conversationPending = false
      }
    },

    async deleteConversation(id: string) {
      await assistantApi.deleteConversation(id)
      this.conversations = this.conversations.filter((item) => item.id !== id)
      if (this.activeId === id) {
        this.disconnectEvents()
        this.activeId = null
        this.messages = []
        this.uiState = 'IDLE'
        if (this.conversations.length) {
          await this.selectConversation(this.conversations[0].id)
        }
      }
    },

    async selectConversation(id: string) {
      if (this.activeId !== id) {
        this.disconnectEvents(true)
        this.activeId = id
        this.messages = []
        this.uiState = 'IDLE'
        this.statusText = ''
        this.error = ''
      }
      try {
        this.messages = await assistantApi.messages(id)
      } catch (error) {
        this.error = error instanceof Error ? error.message : '加载消息失败'
      }
      if (this.waitingConfirm) this.uiState = 'WAITING_CONFIRM'
      this.connectEvents()
    },

    connectEvents() {
      this.disconnectEvents(false)
      if (!this.activeId) return
      const conversationId = this.activeId
      const source = new EventSource(assistantApi.eventsUrl(conversationId, this.lastSeq))
      source.addEventListener('connected', () => {
        this.eventsConnected = true
      })
      source.addEventListener('assistant', (raw) => {
        try {
          const envelope = JSON.parse((raw as MessageEvent).data) as AssistantEventEnvelope
          this.applyEvent(envelope)
        } catch {
          // 单条事件解析失败不影响连接
        }
      })
      source.onerror = () => {
        if (this.eventSource !== source) return
        source.close()
        this.eventSource = null
        this.eventsConnected = false
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
        this.reconnectTimer = setTimeout(() => {
          this.reconnectTimer = null
          if (this.activeId !== conversationId) return
          void this.restoreAfterDisconnect(conversationId)
        }, 1200)
      }
      this.eventSource = source
    },

    async restoreAfterDisconnect(conversationId: string) {
      try {
        const messages = await assistantApi.messages(conversationId)
        if (this.activeId !== conversationId) return
        this.messages = messages
        if (this.waitingConfirm) {
          this.uiState = 'WAITING_CONFIRM'
        } else if (messages.some((message) => message.status === 'STREAMING')) {
          this.uiState = 'THINKING'
        } else if (this.uiState !== 'FAILED') {
          this.uiState = 'IDLE'
        }
      } catch {
        // Backend 仍在恢复时保留当前消息，继续重连 SSE。
      }
      if (this.activeId === conversationId) this.connectEvents()
    },

    disconnectEvents(resetCursor = true) {
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer)
        this.reconnectTimer = null
      }
      if (this.eventSource) {
        this.eventSource.close()
        this.eventSource = null
      }
      this.eventsConnected = false
      if (resetCursor) this.lastSeq = 0
    },

    async sendMessage(content: string) {
      const text = content.trim()
      if (!text || this.busy || this.initializing || this.conversationPending) return
      this.error = ''
      try {
        if (!this.activeId) {
          await this.createConversation(text.slice(0, 32))
        }
        const conversationId = this.activeId
        if (!conversationId) return
        this.uiState = 'SUBMITTING'
        const message = await assistantApi.sendMessage(
          conversationId,
          text,
          pageContextFromLocation(),
        )
        this.messages.push({ ...message, parts: [] })
        this.uiState = 'THINKING'
      } catch (error) {
        this.uiState = 'FAILED'
        this.error =
          error instanceof AssistantApiError || error instanceof Error
            ? error.message
            : '发送失败'
      }
    },

    async stopGeneration() {
      if (!this.activeId) return
      try {
        await assistantApi.abort(this.activeId)
      } catch {
        // 停止失败时保持当前状态，等待事件流恢复
      }
    },

    async confirmOperation(operationId: string) {
      try {
        const operation = await assistantApi.confirmOperation(operationId)
        this.markConfirmCard(operationId, operation.status === 'SUCCESS' ? 'SUCCESS' : operation.status, operation.result)
        if (this.uiState === 'WAITING_CONFIRM') this.uiState = 'IDLE'
      } catch (error) {
        this.error = error instanceof Error ? error.message : '确认失败'
      }
    },

    async cancelOperation(operationId: string) {
      try {
        await assistantApi.cancelOperation(operationId)
        this.markConfirmCard(operationId, 'CANCELLED', {})
        if (this.uiState === 'WAITING_CONFIRM') this.uiState = 'IDLE'
      } catch (error) {
        this.error = error instanceof Error ? error.message : '取消失败'
      }
    },

    markConfirmCard(operationId: string, status: string, result: Record<string, any>) {
      for (const message of this.messages) {
        for (const part of message.parts) {
          if (part.part_type === 'CONFIRM_CARD' && part.payload?.operation_id === operationId) {
            part.payload = { ...part.payload, status, result }
          }
        }
      }
    },

    findMessage(messageId: string | null | undefined): AssistantMessage | null {
      if (!messageId) return null
      return this.messages.find((item) => item.id === messageId) ?? null
    },

    appendPart(messageId: string | null | undefined, part: Partial<AssistantMessagePart>) {
      const message = this.findMessage(messageId)
      if (!message || !part?.payload) return
      const exists = message.parts.some(
        (item) =>
          item.part_type === part.part_type &&
          ((part.seq !== undefined && item.seq === part.seq) ||
            (part.part_type === 'CONFIRM_CARD' &&
              item.payload?.operation_id === part.payload?.operation_id)),
      )
      if (exists) return
      message.parts.push({
        id: part.id ?? Date.now(),
        part_type: part.part_type ?? 'STATUS',
        seq: part.seq ?? message.parts.length + 1,
        payload: part.payload,
        created_at: part.created_at ?? new Date().toISOString(),
      })
    },

    applyEvent(envelope: AssistantEventEnvelope) {
      if (envelope.conversation_id !== this.activeId) return
      if (typeof envelope.seq === 'number') this.lastSeq = envelope.seq
      const data = envelope.data ?? {}
      switch (envelope.event) {
        case 'assistant.started':
          this.uiState = 'THINKING'
          this.statusText = ''
          break
        case 'assistant.status':
          if (data.state) this.uiState = data.state as AssistantUiState
          break
        case 'assistant.message.created': {
          if (!this.findMessage(envelope.message_id)) {
            this.messages.push({
              id: envelope.message_id ?? `tmp-${Date.now()}`,
              conversation_id: envelope.conversation_id,
              role: 'ASSISTANT',
              message_type: 'TEXT',
              content: String(data.content ?? ''),
              status: 'STREAMING',
              created_at: envelope.timestamp,
              updated_at: envelope.timestamp,
              parts: [],
            })
          }
          this.uiState = 'STREAMING'
          break
        }
        case 'assistant.message.delta': {
          const message = this.findMessage(envelope.message_id)
          if (message) {
            message.content = String(data.content ?? '')
            message.status = 'STREAMING'
            this.uiState = 'STREAMING'
          }
          break
        }
        case 'assistant.message.completed': {
          const message = this.findMessage(envelope.message_id)
          if (message) message.status = 'COMPLETED'
          break
        }
        case 'assistant.tool.started':
          this.uiState = 'TOOL_RUNNING'
          this.statusText = data.tool ? `正在调用 ${data.tool}…` : '正在执行平台操作…'
          break
        case 'assistant.tool.completed':
        case 'assistant.tool.failed':
          this.statusText = ''
          if (this.uiState === 'TOOL_RUNNING') this.uiState = 'THINKING'
          break
        case 'assistant.card.created':
          if (data.part) this.appendPart(envelope.message_id, data.part)
          break
        case 'assistant.operation.confirm_required':
          if (data.part) this.appendPart(envelope.message_id, data.part)
          this.uiState = 'WAITING_CONFIRM'
          break
        case 'assistant.operation.completed':
          this.markConfirmCard(String(data.operation_id ?? ''), String(data.status ?? 'SUCCESS'), data.result ?? {})
          if (this.uiState === 'WAITING_CONFIRM') this.uiState = 'IDLE'
          break
        case 'assistant.operation.cancelled':
          this.markConfirmCard(String(data.operation_id ?? ''), 'CANCELLED', {})
          if (this.uiState === 'WAITING_CONFIRM') this.uiState = 'IDLE'
          break
        case 'assistant.failed':
          this.uiState = 'FAILED'
          this.error = String(data.error || '助手执行异常')
          {
            const message = this.findMessage(envelope.message_id)
            if (message) message.status = 'FAILED'
          }
          break
        case 'assistant.completed':
          if (this.uiState !== 'WAITING_CONFIRM') this.uiState = 'IDLE'
          this.statusText = ''
          break
        default:
          break
      }
    },
  },
})
