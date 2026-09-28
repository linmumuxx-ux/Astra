<template>
  <ElDrawer
    v-model="visible"
    title="平台助手"
    direction="rtl"
    size="min(440px, 100vw)"
    :modal="false"
    modal-penetrable
    :lock-scroll="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    header-class="assistant-drawer__header"
    body-class="assistant-drawer__body"
  >
    <template #header="{ titleId, titleClass }">
      <ElSpace alignment="center" :size="8">
        <Sparkles :size="16" />
        <span :id="titleId" :class="titleClass" role="heading" aria-level="2">平台助手</span>
        <ElTag size="small" :type="store.unavailable ? 'danger' : store.eventsConnected ? 'success' : 'info'">
          {{ store.unavailable ? '服务异常' : store.eventsConnected ? '已连接' : '连接中' }}
        </ElTag>
      </ElSpace>
      <ElSpace alignment="center" :size="6">
        <ElSelect
          v-if="store.conversations.length"
          :model-value="store.activeId ?? ''"
          size="small"
          class="assistant-drawer__select"
          aria-label="选择会话"
          @change="onSelect"
        >
          <ElOption
            v-for="item in store.conversations"
            :key="item.id"
            :label="item.title || item.id"
            :value="item.id"
          />
        </ElSelect>
        <ElButton
          size="small"
          title="新建会话"
          :disabled="store.initializing || store.conversationPending"
          @click="createConversation"
        ><Plus :size="16" /></ElButton>
        <ElButton
          v-if="store.activeId"
          size="small"
          title="删除当前会话"
          @click="removeConversation"
        ><Trash2 :size="15" /></ElButton>
        <ElButton size="small" aria-label="关闭助手" title="关闭助手" @click="store.closeDrawer()">
          <X :size="17" />
        </ElButton>
      </ElSpace>
    </template>

    <ContextBar />
    <MessageList ref="listRef" @modify="prefillInput" @preset="sendPreset" />
    <MessageInput ref="inputRef" />
  </ElDrawer>
</template>

<script setup lang="ts">
import { Plus, Sparkles, Trash2, X } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { ElButton, ElDrawer, ElOption, ElSelect, ElSpace, ElTag } from 'element-plus'
import ContextBar from './ContextBar.vue'
import MessageInput from './MessageInput.vue'
import MessageList from './MessageList.vue'
import { useAssistantStore } from './store'

// The drawer is a native ElDrawer: non-modal and pointer-penetrable so the page
// stays usable while the assistant is open, and it never locks scrolling or
// closes on ESC / outside clicks. Only spacing and the chat column layout are
// customized here; the conversation tools use native ElSelect/ElButton/ElTag.
const store = useAssistantStore()
const inputRef = ref<InstanceType<typeof MessageInput> | null>(null)
const listRef = ref<InstanceType<typeof MessageList> | null>(null)
void listRef

const visible = computed({
  get: () => store.open,
  set: (value: boolean) => {
    if (!value) store.closeDrawer()
  },
})

function prefillInput(text: string) {
  inputRef.value?.prefill(text)
}

function sendPreset(text: string) {
  void store.sendMessage(text)
}

function onSelect(id: string) {
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

<style>
/* Layout-only spacing so the chat column fits the drawer body. */
.assistant-drawer__header { margin-bottom: 0; padding: 10px 14px; }
.assistant-drawer__body { display: flex; flex-direction: column; overflow: hidden; padding: 0; }
</style>

<style scoped>
.assistant-drawer__select { width: 110px; }
</style>
