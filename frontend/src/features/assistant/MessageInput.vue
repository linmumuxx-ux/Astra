<template>
  <div class="assistant-input">
    <textarea
      ref="inputRef"
      v-model="draft"
      rows="2"
      :placeholder="placeholder"
      :disabled="inputDisabled"
      @keydown.enter.exact.prevent="send"
    />
    <div class="assistant-input__bar">
      <span v-if="store.statusText" class="assistant-input__status">{{ store.statusText }}</span>
      <button
        v-if="store.busy"
        class="assistant-input__stop"
        type="button"
        @click="store.stopGeneration()"
      ><Square :size="13" />停止生成</button>
      <button
        v-else
        class="assistant-input__send"
        type="button"
        :disabled="!draft.trim() || inputDisabled"
        @click="send"
      ><SendHorizontal :size="14" />发送</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { SendHorizontal, Square } from 'lucide-vue-next'
import { computed, nextTick, ref, watch } from 'vue'
import { useAssistantStore } from './store'

const store = useAssistantStore()
const draft = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const inputDisabled = computed(
  () => store.unavailable || store.initializing || store.conversationPending,
)

const placeholder = computed(() =>
  store.unavailable
    ? '助手服务不可用'
    : store.initializing || store.conversationPending
      ? '正在准备会话…'
      : '输入问题或指令，Enter 发送，Shift+Enter 换行',
)

function send() {
  const text = draft.value.trim()
  if (!text || store.busy) return
  draft.value = ''
  void store.sendMessage(text)
}

defineExpose({
  prefill(text: string) {
    draft.value = text
    void nextTick(() => inputRef.value?.focus())
  },
})

watch(
  () => store.open,
  (open) => {
    if (open) void nextTick(() => inputRef.value?.focus())
  },
)
</script>

<style scoped>
.assistant-input {
  border-top: 1px solid var(--astra-border);
  padding: 10px 12px 12px;
  display: grid;
  gap: 8px;
  background: var(--astra-bg-panel);
}
.assistant-input textarea {
  resize: none;
  border: 1px solid var(--astra-border);
  border-radius: 10px;
  padding: 9px 11px;
  font: inherit;
  font-size: var(--astra-font-body);
  color: var(--astra-text-primary);
  background: var(--astra-bg-card);
  outline: none;
  min-height: 54px;
  max-height: 140px;
}
.assistant-input textarea:focus { border-color: var(--astra-border-hover); }
.assistant-input__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.assistant-input__status {
  font-size: var(--astra-font-helper);
  color: var(--astra-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.assistant-input__send,
.assistant-input__stop {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--astra-font-control);
  padding: 6px 14px;
  border-radius: 9px;
  border: none;
  cursor: pointer;
  margin-left: auto;
}
.assistant-input__send {
  background: var(--astra-primary);
  color: #fff;
}
.assistant-input__send:disabled { opacity: 0.45; cursor: default; }
.assistant-input__stop {
  background: var(--astra-danger-soft);
  color: var(--astra-danger);
}
</style>
