<template>
  <div class="message-list">
    <div v-for="msg in store.messages" :key="msg.id" class="message" :class="msg.role.toLowerCase()">
      <div class="content">{{ msg.content }}</div>
      <!-- Cards rendering would go here based on msg.parts -->
    </div>
  </div>
</template>

<script setup lang="ts">
import { useAssistantStore } from '../store/assistantStore'
const store = useAssistantStore()
</script>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.message {
  max-width: 85%;
  padding: 12px;
  border-radius: 8px;
}
.user {
  align-self: flex-end;
  background-color: var(--color-primary-light);
}
.assistant {
  align-self: flex-start;
  background-color: #f5f5f5;
}
</style>
