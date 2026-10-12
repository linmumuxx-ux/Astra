<template>
  <!-- 全局唯一尺寸入口：所有 Element Plus 控件默认 small，
       紧凑高度由 styles/tokens.css 的 --el-component-size* 统一决定。 -->
  <ElConfigProvider size="small">
    <RouterView />
    <AssistantDrawer />
    <AstraConfirmHost />
  </ElConfigProvider>
</template>

<script setup lang="ts">
import { ElConfigProvider } from 'element-plus'
import { onMounted, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AstraConfirmHost from '@/components/astra/AstraConfirmHost.vue'
import AssistantDrawer from '@/features/assistant/AssistantDrawer.vue'
import { useAstraStore } from '@/stores/astra'

const route = useRoute()
const store = useAstraStore()

watch(() => route.path, (path, previous) => {
  if (path !== '/' && previous === '/' && !store.loading) store.refresh()
})

onMounted(() => {
  if (route.path !== '/' && !store.loading && !store.lastUpdated) store.refresh()
})
</script>
