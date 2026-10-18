<template>
  <ElTable
    v-loading="loading"
    class="gateway-node-table"
    element-loading-text="正在加载节点"
    :data="nodes"
    row-key="id"
    data-testid="gateway-node-table"
  >
    <ElTableColumn label="节点" min-width="220">
      <template #default="{ row }">
        <RouterLink class="node-cell" :to="`/gateway/nodes/${row.id}`">
          <strong>{{ row.name }}</strong>
          <span class="node-cell__url">{{ poolName(row.pool_id) }} · {{ row.models.length ? row.models.join('、') : '模型未配置' }}</span>
        </RouterLink>
      </template>
    </ElTableColumn>
    <ElTableColumn label="能否接请求" min-width="180">
      <template #default="{ row }">{{ serveSentence(row as GatewayNode) }}</template>
    </ElTableColumn>
    <ElTableColumn label="健康 / 调度 / 配置" min-width="220">
      <template #default="{ row }">
        <div class="node-facts">
          <ElTag :type="tagType(healthTone(row.health_state))">健康 {{ healthStateLabel(row.health_state) }}</ElTag>
          <ElTag :type="tagType(schedulingTone(row.scheduling_state))">调度 {{ schedulingStateLabel(row.scheduling_state) }}</ElTag>
          <ElTag :type="row.config_state === 'ENABLED' ? 'success' : 'info'">配置 {{ configStateLabel(row.config_state) }}</ElTag>
        </div>
      </template>
    </ElTableColumn>
    <ElTableColumn label="操作" width="132">
      <template #default="{ row }">
        <RowMenu
          primary="详情"
          :aria-label="(row as GatewayNode).name"
          :disabled="busyId === row.id"
          :items="nodeMenu(row as GatewayNode)"
          @primary="$emit('detail', row as GatewayNode)"
          @command="(command) => onNodeCommand(row as GatewayNode, command)"
        />
      </template>
    </ElTableColumn>
    <template #empty>
      <ElEmpty v-if="!loading" :image-size="64" :description="emptyText" />
    </template>
  </ElTable>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { ElEmpty, ElTable, ElTableColumn, ElTag, vLoading } from 'element-plus'
import type { GatewayNode, GatewayPool } from '@/api/gateway'
import RowMenu, { type RowMenuItem } from '@/components/astra/RowMenu.vue'
import {
  configStateLabel,
  healthStateLabel,
  healthTone,
  schedulingStateLabel,
  schedulingTone,
  serveSentence,
  type GatewayTone,
} from '@/utils/gateway'

const props = defineProps<{
  nodes: GatewayNode[]
  pools: GatewayPool[]
  busyId?: string
  loading?: boolean
  emptyText?: string
}>()
const emit = defineEmits<{
  detail: [node: GatewayNode]
  probe: [node: GatewayNode]
  drain: [node: GatewayNode]
  restore: [node: GatewayNode]
  'toggle-config': [node: GatewayNode]
  edit: [node: GatewayNode]
  delete: [node: GatewayNode]
}>()

function poolName(poolId: string | null): string {
  if (!poolId) return '未分配'
  return props.pools.find((pool) => pool.id === poolId)?.name ?? poolId
}

function nodeMenu(row: GatewayNode): RowMenuItem[] {
  return [
    { command: 'probe', label: '探测' },
    { command: row.scheduling_state === 'ACTIVE' ? 'drain' : 'restore', label: row.scheduling_state === 'ACTIVE' ? '安全下线' : '恢复调度' },
    { command: 'toggle-config', label: row.config_state === 'ENABLED' ? '禁用' : '启用' },
    { command: 'edit', label: '编辑' },
    { command: 'delete', label: '删除' },
  ]
}

function onNodeCommand(row: GatewayNode, command: string) {
  if (command === 'probe') emit('probe', row)
  else if (command === 'drain') emit('drain', row)
  else if (command === 'restore') emit('restore', row)
  else if (command === 'toggle-config') emit('toggle-config', row)
  else if (command === 'edit') emit('edit', row)
  else if (command === 'delete') emit('delete', row)
}

function tagType(tone: GatewayTone): 'success' | 'warning' | 'danger' | 'info' {
  if (tone === 'success') return 'success'
  if (tone === 'warning') return 'warning'
  if (tone === 'danger') return 'danger'
  return 'info'
}
</script>

<style scoped>
.node-cell { display: grid; gap: 2px; min-width: 0; text-decoration: none; }
.node-cell strong { color: var(--astra-text-primary); font-size: var(--astra-font-label); }
.node-cell__url { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.node-facts { display: flex; flex-wrap: wrap; gap: 4px; }
</style>
