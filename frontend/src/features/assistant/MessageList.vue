<template>
  <div class="assistant-messages" ref="listRef">
    <p v-if="store.unavailable" class="assistant-messages__unavailable">
      助手服务当前不可用：{{ store.health?.detail || '请稍后再试' }}。平台任务与员工功能不受影响。
    </p>
    <p v-else-if="!store.messages.length" class="assistant-messages__empty">
      你可以问我任务、员工、运行和知识，例如：<br />
      “最近有哪些失败的任务？”“创建一个问题任务让图丫丫处理”。
    </p>
    <div
      v-for="message in store.messages"
      :key="message.id"
      class="assistant-message"
      :class="`assistant-message--${message.role.toLowerCase()}`"
    >
      <div v-if="message.content" class="assistant-message__bubble">{{ message.content }}</div>
      <template v-for="part in message.parts" :key="`${message.id}-${part.seq}-${part.id}`">
        <ConfirmCard
          v-if="part.part_type === 'CONFIRM_CARD'"
          :payload="part.payload"
          @modify="(text) => emit('modify', text)"
        />
        <BusinessCard
          v-else-if="CARD_TYPES.has(part.part_type)"
          :card="part.payload"
          @operation="onCardOperation"
        />
        <p v-else-if="part.part_type === 'ERROR'" class="assistant-message__error">{{ part.payload.text }}</p>
      </template>
      <div
        v-if="message.role === 'ASSISTANT' && message.status === 'STREAMING' && streamingId === message.id"
        class="assistant-message__typing"
      ><i /><i /><i /></div>
    </div>
    <p v-if="store.error" class="assistant-messages__error">{{ store.error }}</p>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import BusinessCard from './cards/BusinessCard.vue'
import ConfirmCard from './cards/ConfirmCard.vue'
import { useAssistantStore } from './store'
import type { AssistantCardAction, AssistantCardPayload } from './types'

const emit = defineEmits<{ modify: [text: string]; preset: [text: string] }>()
const store = useAssistantStore()
const listRef = ref<HTMLElement | null>(null)

const CARD_TYPES = new Set(['TASK_CARD', 'EMPLOYEE_CARD', 'RUN_CARD', 'KNOWLEDGE_CARD'])

const streamingId = ref<string | null>(null)
watch(
  () => store.messages.map((message) => `${message.id}:${message.status}:${message.content.length}:${message.parts.length}`).join('|'),
  () => {
    const streaming = [...store.messages].reverse().find((message) => message.status === 'STREAMING')
    streamingId.value = streaming?.id ?? null
    void nextTick(() => {
      listRef.value?.scrollTo({ top: listRef.value.scrollHeight })
    })
  },
  { immediate: true, flush: 'post' },
)

const OPERATION_PHRASES: Record<string, string> = {
  task_cancel: '请取消任务',
  task_retry: '请重试任务',
  task_resume: '请恢复任务',
  task_reassign: '请重新分配任务',
}

function onCardOperation(action: AssistantCardAction, card: AssistantCardPayload) {
  const phrase = OPERATION_PHRASES[action.operation ?? ''] ?? action.label
  emit('preset', card.id ? `${phrase} ${card.id}` : phrase)
}
</script>

<style scoped>
.assistant-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: grid;
  gap: 14px;
  align-content: start;
}
.assistant-messages__empty,
.assistant-messages__unavailable {
  color: var(--astra-text-muted);
  font-size: var(--astra-font-body);
  line-height: 1.7;
  padding: 12px;
  border: 1px dashed var(--astra-border);
  border-radius: 12px;
}
.assistant-messages__error {
  color: var(--astra-danger);
  font-size: var(--astra-font-helper);
  margin: 0;
}
.assistant-message { display: grid; gap: 8px; justify-items: start; }
.assistant-message--user { justify-items: end; }
.assistant-message__bubble {
  max-width: 86%;
  padding: 9px 13px;
  border-radius: 13px;
  font-size: var(--astra-font-body);
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.assistant-message--user .assistant-message__bubble {
  background: var(--astra-primary);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.assistant-message--assistant .assistant-message__bubble,
.assistant-message--system .assistant-message__bubble {
  background: var(--astra-bg-elevated);
  color: var(--astra-text-primary);
  border-bottom-left-radius: 4px;
}
.assistant-message__error {
  color: var(--astra-danger);
  font-size: var(--astra-font-helper);
  margin: 0;
}
.assistant-message__typing { display: flex; gap: 4px; padding: 4px 2px; }
.assistant-message__typing i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--astra-primary);
  opacity: 0.35;
  animation: assistant-typing 1s infinite;
}
.assistant-message__typing i:nth-child(2) { animation-delay: 0.2s; }
.assistant-message__typing i:nth-child(3) { animation-delay: 0.4s; }
@keyframes assistant-typing {
  0%, 100% { opacity: 0.25; transform: translateY(0); }
  50% { opacity: 1; transform: translateY(-2px); }
}
@media (prefers-reduced-motion: reduce) {
  .assistant-message__typing i { animation: none; opacity: 0.6; }
}
</style>
