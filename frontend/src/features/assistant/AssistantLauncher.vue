<template>
  <button
    class="assistant-launcher"
    type="button"
    aria-label="打开平台助手"
    data-testid="assistant-launcher"
    :class="{ 'assistant-launcher--alert': store.waitingConfirm }"
    @click="store.openDrawer()"
  >
    <MessageCircle :size="20" />
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
.assistant-launcher {
  position: fixed;
  right: 22px;
  bottom: 22px;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  border: none;
  background: var(--astra-primary);
  color: #fff;
  display: grid;
  place-items: center;
  cursor: pointer;
  box-shadow: 0 12px 28px rgba(21, 157, 101, 0.35);
  z-index: 55;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.assistant-launcher:hover { transform: translateY(-2px); }
.assistant-launcher--alert { background: var(--astra-warning); box-shadow: 0 12px 28px rgba(233, 149, 63, 0.4); }
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
