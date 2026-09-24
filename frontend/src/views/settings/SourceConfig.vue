<template>
  <AstraPanel title="任务来源" subtitle="系统定时拉取外部系统任务并回填结果；当前由部署配置（configs/sources.yaml）管理">
    <div class="config-table-wrap">
      <table class="config-table">
        <thead><tr><th>来源 ID</th><th>类型</th><th>Endpoint</th><th>发现路径</th><th>结果回填</th><th class="narrow-col">轮询间隔</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="source in sources" :key="source.id">
            <td><IdDisplay :value="source.id" :max-width="150" /></td>
            <td>{{ source.type }}</td>
            <td class="mono">{{ source.endpoint }}</td>
            <td class="mono">{{ source.discover_path }}</td>
            <td class="mono">{{ source.result_path }}</td>
            <td class="narrow-col">{{ source.poll_interval }}s</td>
            <td><el-switch :model-value="source.enabled" disabled active-text="启用" inactive-text="停用"  /></td>
          </tr>
          <tr v-if="!sources.length"><td colspan="7"><div class="table-empty">暂无已配置的任务来源。</div></td></tr>
        </tbody>
      </table>
    </div>
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
.config-table-wrap { overflow-x: auto; }
.config-table { min-width: 900px; }
.config-table td { border-top: 1px solid var(--astra-border); }
.mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
.narrow-col { width: 100px; }
.table-empty { padding: 28px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); text-align: center; }
.config-note { margin-top: 14px; }
</style>
