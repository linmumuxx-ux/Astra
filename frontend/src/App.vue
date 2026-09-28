<template>
  <RouterView />
  <AssistantLauncher />
  <AssistantDrawer />
  <AstraConfirmHost />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AstraConfirmHost from '@/components/astra/AstraConfirmHost.vue'
import AssistantDrawer from '@/features/assistant/AssistantDrawer.vue'
import AssistantLauncher from '@/features/assistant/AssistantLauncher.vue'
import { useAstraStore } from '@/stores/astra'

const route = useRoute()
const store = useAstraStore()

watch(() => route.path, (path, previous) => {
  if (path === '/') {
    store.disconnectEvents()
    return
  }
  store.connectEvents()
  if (previous === '/' && !store.loading) store.refresh()
})

onMounted(() => {
  if (route.path !== '/') {
    if (!store.loading && !store.lastUpdated) store.refresh()
    store.connectEvents()
  }
})
onBeforeUnmount(() => store.disconnectEvents())
</script>
