import { defineStore } from 'pinia'
import { AssistantAPI } from '../api/assistant'
import type { ConversationResponse, MessageResponse, AssistantEvent } from '../types/assistant'
import { ref } from 'vue'

export const useAssistantStore = defineStore('assistant', () => {
  const currentConversation = ref<ConversationResponse | null>(null)
  const messages = ref<MessageResponse[]>([])
  const isStreaming = ref(false)
  const eventSource = ref<EventSource | null>(null)

  const loadConversation = async (id: string) => {
    const res = await AssistantAPI.getConversation(id)
    currentConversation.value = res
    const msgsRes = await AssistantAPI.getMessages(id)
    messages.value = msgsRes
  }

  const sendMessage = async (content: string, pageContext?: any) => {
    if (!currentConversation.value) {
       const res = await AssistantAPI.createConversation({ title: '新对话', status: 'ACTIVE' })
       currentConversation.value = res
    }

    // Add user message optimistically
    const newMsg: MessageResponse = {
        id: `temp-${Date.now()}`,
        conversation_id: currentConversation.value.id,
        role: 'USER',
        message_type: 'TEXT',
        content,
        status: 'COMPLETED',
        parts: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
    }
    messages.value.push(newMsg)

    // Send to server
    await AssistantAPI.createMessage(currentConversation.value.id, { content, page_context: pageContext })

    // Start SSE listening
    listenToEvents(currentConversation.value.id)
  }

  const listenToEvents = (conversationId: string) => {
    if (eventSource.value) {
        eventSource.value.close()
    }

    isStreaming.value = true
    // Need full URL for EventSource depending on env setup
    eventSource.value = new EventSource(`/api/assistant/conversations/${conversationId}/events`)

    eventSource.value.onmessage = (event) => {
        const data: AssistantEvent = JSON.parse(event.data)

        // Handle events to update messages ref
        // E.g., append text for message.delta, add cards, etc.
        // For brevity, not fully implemented here

        if (data.event === 'assistant.message.completed' || data.event === 'assistant.failed' || data.event === 'assistant.completed') {
             isStreaming.value = false
             if (eventSource.value) {
                 eventSource.value.close()
                 eventSource.value = null
             }
        }
    }

    eventSource.value.onerror = () => {
        isStreaming.value = false
        eventSource.value?.close()
        eventSource.value = null
    }
  }


  const confirmOperation = async (operationId: string) => {
      await AssistantAPI.confirmOperation(operationId)
  }
  const cancelOperation = async (operationId: string) => {
      await AssistantAPI.cancelOperation(operationId)
  }

  const stopGeneration = async () => {
      if (currentConversation.value) {
          await AssistantAPI.abortMessage(currentConversation.value.id)
          if (eventSource.value) {
             eventSource.value.close()
             eventSource.value = null
          }
          isStreaming.value = false
      }
  }

  return {
    currentConversation,
    messages,
    isStreaming,
    loadConversation,
    sendMessage,
    stopGeneration,
    confirmOperation,
    cancelOperation
  }
})
