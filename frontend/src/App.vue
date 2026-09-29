<template>
  <!-- 全局唯一尺寸入口：所有 Element Plus 控件默认 small，
       紧凑高度由 styles/tokens.css 的 --el-component-size* 统一决定。 -->
  <ElConfigProvider size="small">
    <RouterView />
    <AssistantLauncher />
    <AssistantDrawer />
    <AstraConfirmHost />
  </ElConfigProvider>
</template>

<script setup lang="ts">
import { ElConfigProvider } from 'element-plus'
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
