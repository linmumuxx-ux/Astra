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
      </div>
    </ElCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElAlert, ElCard, ElTag, ElText } from 'element-plus'
import { getRuntime } from '@/api'
import type { RuntimeStatus } from '@/types'

const runtime = ref<RuntimeStatus | null>(null)
const loading = ref(true)

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
.agentscope-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
