<template>
  <div class="agentscope-view" data-testid="agentscope-page">
    <ElCard class="agentscope-card" shadow="never">
      <template #header>
        <div class="agentscope-header">
          <div class="agentscope-title-wrap">
            <h2 class="agentscope-title">AgentScope UI</h2>
            <ElTag :type="statusTagType" effect="plain" class="agentscope-status-tag">
              {{ statusText }}
            </ElTag>
          </div>
          <ElText type="info" size="small" class="agentscope-version">
            版本: {{ runtime ? `AgentScope ${runtime.agentscope_version}` : '检查中...' }}
          </ElText>
        </div>
      </template>

      <div class="agentscope-body">
        <ElAlert
          type="info"
          :closable="false"
          show-icon
          title="功能提示"
          description="当前部署未提供可嵌入的 AgentScope 管理界面。Skill / MCP 管理暂不可用。"
        />
        <section v-for="block in catalogBlocks" :key="block.key" class="agentscope-catalog" :data-testid="`agentscope-${block.key}`">
          <h3>{{ block.label }}（只读）</h3>
          <ElText v-if="!block.catalog.available" type="warning">AgentScope 不可达，无法读取</ElText>
          <ElText v-else-if="!block.catalog.items.length" type="info">暂无</ElText>
          <div v-else class="agentscope-chips">
            <ElTag v-for="item in block.catalog.items" :key="item.id" effect="plain">{{ item.name }}</ElTag>
          </div>
        </section>
      </div>
    </ElCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElAlert, ElCard, ElTag, ElText } from 'element-plus'
import { getRuntime, getSkills, getTools } from '@/api'
import type { ResourceCatalog, RuntimeStatus } from '@/types'

const runtime = ref<RuntimeStatus | null>(null)
const loading = ref(true)
const skills = ref<ResourceCatalog>({ available: false, items: [] })
const tools = ref<ResourceCatalog>({ available: false, items: [] })
const catalogBlocks = computed(() => [
  { key: 'skills', label: '已注册 Skill', catalog: skills.value },
  { key: 'tools', label: '已注册工具', catalog: tools.value },
])

const statusText = computed(() => {
  if (!runtime.value) return loading.value ? '检查中' : '未连接'
  if (runtime.value.reachable) return '已连接'
  if (runtime.value.configured) return '不可达'
  return '未连接'
})

const statusTagType = computed<'success' | 'warning' | 'info'>(() => {
  if (!runtime.value) return 'info'
  if (runtime.value.reachable) return 'success'
  if (runtime.value.configured) return 'warning'
  return 'info'
})

onMounted(async () => {
  try {
    runtime.value = await getRuntime()
  } catch {
    runtime.value = { agentscope_version: '2.0.10', configured: false, reachable: false }
  } finally {
    loading.value = false
  }
  ;[skills.value, tools.value] = await Promise.all([
    getSkills().catch(() => ({ available: false, items: [] })),
    getTools().catch(() => ({ available: false, items: [] })),
  ])
})
</script>

<style scoped>
.agentscope-view {
  padding: 20px 24px;
  height: 100%;
  overflow-y: auto;
}
.agentscope-card {
  max-width: 800px;
}
.agentscope-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.agentscope-title-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
}
.agentscope-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
}
.agentscope-catalog h3 { margin: 0 0 8px; font-size: 14px; }
.agentscope-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.agentscope-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
