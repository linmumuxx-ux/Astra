<template>
  <section class="gateway-audits astra-stack" data-testid="gateway-audits">
    <GatewayHeaderActions>
      <ElButton :loading="loading" :icon="RefreshCw" data-testid="gateway-audits-refresh" @click="load">刷新</ElButton>
    </GatewayHeaderActions>

    <ElAlert v-if="error" type="error" show-icon :closable="false" :title="error">
      <ElButton type="primary" @click="load">重试</ElButton>
    </ElAlert>

    <section class="astra-table-panel">
      <ElTable
        v-loading="loading"
        :data="rows"
        row-key="id"
        empty-text="暂无配置审计。"
        data-testid="gateway-audits-table"
        @row-click="openLogs"
      >
        <ElTableColumn label="时间" width="168">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </ElTableColumn>
        <ElTableColumn label="来源" width="88">
          <template #default><ElTag type="info">配置</ElTag></template>
        </ElTableColumn>
        <ElTableColumn label="操作" prop="action" min-width="140" />
        <ElTableColumn label="对象" min-width="180">
          <template #default="{ row }">{{ row.resource_type }} {{ row.resource_id ?? '' }}</template>
        </ElTableColumn>
        <ElTableColumn label="结果" width="100" prop="result" />
        <ElTableColumn label="操作者" min-width="140">
          <template #default="{ row }">{{ row.actor }}<span v-if="row.actor_role"> · {{ row.actor_role }}</span></template>
        </ElTableColumn>
      </ElTable>
    </section>
  </section>
</template>

<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElAlert, ElButton, ElTable, ElTableColumn, ElTag, vLoading } from 'element-plus'
import { gatewayApi, type GatewayAuditEvent } from '@/api/gateway'
import { errorMessage, formatDateTime } from '@/utils/gateway'
import GatewayHeaderActions from '@/views/gateway/GatewayHeaderActions.vue'

const router = useRouter()
const rows = ref<GatewayAuditEvent[]>([])
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    rows.value = await gatewayApi.audits({ limit: 200 })
  } catch (reason) {
    error.value = errorMessage(reason, '审计加载失败')
  } finally {
    loading.value = false
  }
}

function openLogs(row: GatewayAuditEvent) {
  const at = new Date(row.created_at).getTime()
  const query: Record<string, string> = {
    from: new Date(at - 5 * 60 * 1000).toISOString(),
    to: new Date(at + 5 * 60 * 1000).toISOString(),
  }
  if (row.resource_type === 'node' && row.resource_id) query.node_id = row.resource_id
  if (row.resource_type === 'pool' && row.resource_id) query.pool_id = row.resource_id
  if (row.resource_type === 'key' && row.resource_id) query.key_id = row.resource_id
  const model = row.after.model ?? row.before.model
  if (typeof model === 'string') query.model = model
  void router.push({ path: '/gateway/logs', query })
}

onMounted(() => { void load() })
</script>

<style scoped>
.gateway-audits :deep(.el-table__row) { cursor: pointer; }
</style>
