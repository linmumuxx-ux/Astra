<template>
  <button
    class="assistant-launcher"
    type="button"
    aria-label="打开平台助手"
    data-testid="assistant-launcher"
    :class="{ 'assistant-launcher--alert': store.waitingConfirm }"
    @click="store.openDrawer()"
  >    <MessageCircle :size="20" />
    <i v-if="store.waitingConfirm" class="assistant-launcher__dot" />
  </button>
</template>

<script setup lang="ts">
import { MessageCircle } from 'lucide-vue-next'
import { onMounted } from 'vue'
import { useAssistantStore } from './store'

const store = useAssistantStore()
onMounted(() => {
  void store.init()
})
</script>

<style scoped>
/* 入口收进顶部栏右侧：与通知铃铛同一组，不再悬浮在内容之上。
   固定悬浮会压住表格右侧固定操作列与底部分页，任何页面都不能接受。 */
.assistant-launcher {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.assistant-launcher:hover { background: var(--astra-primary-soft); color: var(--astra-primary-bright); }
.assistant-launcher--alert { color: var(--astra-warning); }
.assistant-launcher--alert:hover { color: var(--astra-warning); background: var(--astra-warning-soft); }
.assistant-launcher__dot {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid var(--astra-warning);
}
@media (prefers-reduced-motion: reduce) {
  .assistant-launcher { transition: none; }
}
</style>
