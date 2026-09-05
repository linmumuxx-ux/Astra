<template>
  <Teleport to="body">
    <transition name="assistant-drawer">
      <aside v-if="store.open" class="assistant-drawer" role="dialog" aria-label="平台助手">
        <header class="assistant-drawer__header">
          <div class="assistant-drawer__title">
            <Sparkles :size="16" />
            <strong>平台助手</strong>
            <span
              class="assistant-drawer__conn"
              :class="{ 'assistant-drawer__conn--off': store.unavailable }"
            >{{ store.unavailable ? '服务异常' : store.eventsConnected ? '已连接' : '连接中' }}</span>
          </div>
          <div class="assistant-drawer__tools">
            <select
              v-if="store.conversations.length"
              class="assistant-drawer__select"
              :value="store.activeId ?? ''"
              aria-label="选择会话"
              @change="onSelect"
            >
              <option v-for="item in store.conversations" :key="item.id" :value="item.id">
                {{ item.title || item.id }}
              </option>
            </select>
            <button
              class="icon-button"
              type="button"
              title="新建会话"
              :disabled="store.initializing || store.conversationPending"
              @click="createConversation"
            ><Plus :size="16" /></button>
            <button
              v-if="store.activeId"
              class="icon-button"
              type="button"
              title="删除当前会话"
              @click="removeConversation"
            ><Trash2 :size="15" /></button>
            <button class="icon-button" type="button" aria-label="关闭助手" @click="store.closeDrawer()"><X :size="17" /></button>
          </div>
        </header>
        <ContextBar />
        <MessageList ref="listRef" @modify="prefillInput" @preset="sendPreset" />
        <MessageInput ref="inputRef" />
      </aside>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
import { Plus, Sparkles, Trash2, X } from 'lucide-vue-next'
import { ref } from 'vue'
import ContextBar from './ContextBar.vue'
import MessageInput from './MessageInput.vue'
import MessageList from './MessageList.vue'
import { useAssistantStore } from './store'

const store = useAssistantStore()
const inputRef = ref<InstanceType<typeof MessageInput> | null>(null)
const listRef = ref<InstanceType<typeof MessageList> | null>(null)
void listRef

function prefillInput(text: string) {
  inputRef.value?.prefill(text)
}

function sendPreset(text: string) {
  void store.sendMessage(text)
}

function onSelect(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  if (id) void store.selectConversation(id)
}

async function createConversation() {
  try {
    await store.createConversation()
  } catch (error) {
    store.error = error instanceof Error ? error.message : '创建会话失败'
  }
}

async function removeConversation() {
  if (!store.activeId) return
  try {
    await store.deleteConversation(store.activeId)
  } catch (error) {
    store.error = error instanceof Error ? error.message : '删除会话失败'
  }
}
</script>

<style scoped>
.assistant-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(440px, 100vw);
  background: var(--astra-bg-panel);
  border-left: 1px solid var(--astra-border);
  box-shadow: -18px 0 48px rgba(28, 58, 49, 0.16);
  display: flex;
  flex-direction: column;
  z-index: 700;
}
.assistant-drawer-enter-active,
.assistant-drawer-leave-active { transition: transform 0.22s ease; }
.assistant-drawer-enter-from,
.assistant-drawer-leave-to { transform: translateX(100%); }
@media (prefers-reduced-motion: reduce) {
  .assistant-drawer-enter-active,
  .assistant-drawer-leave-active { transition: none; }
}
.assistant-drawer__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--astra-border);
}
.assistant-drawer__title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--astra-text-primary);
}
.assistant-drawer__title strong { font-size: var(--astra-font-emphasis); }
.assistant-drawer__conn {
  font-size: var(--astra-font-helper);
  color: var(--astra-primary-bright);
  background: var(--astra-primary-soft);
  padding: 1px 8px;
  border-radius: 999px;
}
.assistant-drawer__conn--off {
  color: var(--astra-danger);
  background: var(--astra-danger-soft);
}
.assistant-drawer__tools { display: flex; align-items: center; gap: 6px; }
.assistant-drawer__select {
  max-width: 150px;
  font-size: var(--astra-font-control);
  padding: 5px 8px;
  border-radius: 8px;
  border: 1px solid var(--astra-border);
  background: var(--astra-bg-card);
  color: var(--astra-text-secondary);
}
</style>
