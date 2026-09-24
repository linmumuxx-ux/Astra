<template>
  <AstraPanel title="任务来源" subtitle="系统定时拉取外部系统任务并回填结果；当前由部署配置（configs/sources.yaml）管理">
    <el-table :data="sources" stripe empty-text="暂无已配置的任务来源。">
      <el-table-column label="来源 ID" min-width="170">
        <template #default="{ row }"><IdDisplay :value="row.id" :max-width="150" /></template>
      </el-table-column>
      <el-table-column prop="type" label="类型" min-width="130" />
      <el-table-column prop="endpoint" label="Endpoint" min-width="190" class-name="mono" />
      <el-table-column prop="discover_path" label="发现路径" min-width="180" class-name="mono" />
      <el-table-column prop="result_path" label="结果回填" min-width="230" class-name="mono" />
      <el-table-column label="轮询间隔" width="110">
        <template #default="{ row }">{{ row.poll_interval }}s</template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" disabled active-text="启用" inactive-text="停用" />
        </template>
      </el-table-column>
    </el-table>
    <div class="form-note config-note">任务来源为平台静态接入配置，由运维通过部署配置维护；此处仅以只读方式展示，避免与可编辑的配置项混同。</div>
  </AstraPanel>
</template>

<script setup lang="ts">
import AstraPanel from '@/components/astra/AstraPanel.vue'
import IdDisplay from '@/components/astra/IdDisplay.vue'

interface SourceRow { id: string; type: string; enabled: boolean; endpoint: string; discover_path: string; result_path: string; poll_interval: number }
const sources: SourceRow[] = [
  { id: 'nr_test_system', type: 'nr_test_system', enabled: true, endpoint: 'http://localhost:8000', discover_path: '/api/astra/tasks', result_path: '/api/astra/tasks/{external_task_id}/result', poll_interval: 30 },
]
</script>

<style scoped>
.config-note { margin-top: 14px; }
:deep(.mono .cell) { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
</style>
