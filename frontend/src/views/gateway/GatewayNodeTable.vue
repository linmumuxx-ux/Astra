<template>
  <ElTable
    v-loading="loading"
    class="gateway-node-table"
    element-loading-text="正在加载节点"
    :data="nodes"
    size="small"
    row-key="id"
    data-testid="gateway-node-table"
  >
    <ElTableColumn label="节点" min-width="230">
      <template #default="{ row }">
        <RouterLink class="node-cell" :to="`/gateway/nodes/${row.id}`">
          <strong>{{ row.name }}</strong>
          <span class="node-cell__url" :title="row.base_url">{{ row.base_url }}</span>
        </RouterLink>
      </template>
    </ElTableColumn>
    <ElTableColumn label="资源池" width="120" show-overflow-tooltip>
      <template #default="{ row }">{{ poolName(row.pool_id) }}</template>
    </ElTableColumn>
    <ElTableColumn label="健康" width="88">
      <template #default="{ row }">
        <ElTag size="small" :type="tagType(healthTone(row.health_state))">{{ healthStateLabel(row.health_state) }}</ElTag>
      </template>
    </ElTableColumn>
    <ElTableColumn label="调度" width="100">
      <template #default="{ row }">
        <ElTag size="small" :type="tagType(schedulingTone(row.scheduling_state))">{{ schedulingStateLabel(row.scheduling_state) }}</ElTag>
      </template>
    </ElTableColumn>
    <ElTableColumn label="配置" width="80">
      <template #default="{ row }">
        <ElTag size="small" :type="row.config_state === 'ENABLED' ? 'success' : 'info'">{{ configStateLabel(row.config_state) }}</ElTag>
      </template>
    </ElTableColumn>
    <ElTableColumn label="支持模型" min-width="150" show-overflow-tooltip>
      <template #default="{ row }">
        <span v-if="row.models.length">{{ row.models.join('、') }}</span>
        <span v-else class="node-muted">未配置</span>
      </template>
    </ElTableColumn>
    <ElTableColumn label="并发 / 权重" width="104">
      <template #default="{ row }">{{ row.max_concurrency ? row.max_concurrency : '不限' }} / {{ row.weight }}</template>
    </ElTableColumn>
    <ElTableColumn label="额度（时 / 日）" width="116">
      <template #default="{ row }">{{ tokenLimitText(row.hourly_token_limit) }} / {{ tokenLimitText(row.daily_token_limit) }}</template>
    </ElTableColumn>
    <ElTableColumn label="最近探测" width="108">
      <template #default="{ row }">{{ formatRelativeTime(row.last_checked_at) }}</template>
    </ElTableColumn>
    <ElTableColumn v-if="!readonly" label="操作" width="210" fixed="right">
      <template #default="{ row }">
        <div class="row-actions">
          <ElTooltip content="查看详情" placement="top">
            <ElButton text type="primary" :icon="ChevronRight" :aria-label="`查看 ${row.name} 详情`" @click="$emit('detail', row as GatewayNode)" />
          </ElTooltip>
          <ElTooltip content="连接/模型/SSE 探测" placement="top">
            <ElButton text type="primary" :icon="Activity" :aria-label="`探测 ${row.name}`" :disabled="busyId === row.id" @click="$emit('probe', row as GatewayNode)" />
          </ElTooltip>
          <ElTooltip v-if="row.scheduling_state === 'ACTIVE'" content="安全下线（DRAINING）" placement="top">
            <ElButton text type="warning" :icon="Pause" :aria-label="`安全下线 ${row.name}`" :disabled="busyId === row.id" @click="$emit('drain', row as GatewayNode)" />
          </ElTooltip>
          <ElTooltip v-else content="恢复调度" placement="top">
            <ElButton text type="success" :icon="Play" :aria-label="`恢复调度 ${row.name}`" :disabled="busyId === row.id" @click="$emit('restore', row as GatewayNode)" />
          </ElTooltip>
          <ElTooltip :content="row.config_state === 'ENABLED' ? '禁用节点' : '启用节点'" placement="top">
            <ElButton text type="primary" :icon="row.config_state === 'ENABLED' ? PowerOff : Power" :aria-label="`${row.config_state === 'ENABLED' ? '禁用' : '启用'} ${row.name}`" :disabled="busyId === row.id" @click="$emit('toggle-config', row as GatewayNode)" />
          </ElTooltip>
          <ElTooltip content="编辑节点配置" placement="top">
            <ElButton text type="primary" :icon="Pencil" :aria-label="`编辑 ${row.name}`" :disabled="busyId === row.id" @click="$emit('edit', row as GatewayNode)" />
          </ElTooltip>
          <ElTooltip content="删除节点（需已下线且并发为 0）" placement="top">
            <ElButton text type="danger" :icon="Trash2" :aria-label="`删除 ${row.name}`" :disabled="busyId === row.id" @click="$emit('delete', row as GatewayNode)" />
          </ElTooltip>
        </div>
      </template>
    </ElTableColumn>
    <template #empty>
      <ElEmpty v-if="!loading" :image-size="64" :description="emptyText" />
    </template>
  </ElTable>
</template>

<script setup lang="ts">
import { Activity, ChevronRight, Pause, Pencil, Play, Power, PowerOff, Trash2 } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import { ElButton, ElEmpty, ElTable, ElTableColumn, ElTag, ElTooltip, vLoading } from 'element-plus'
import type { GatewayNode, GatewayPool } from '@/api/gateway'
import {
  configStateLabel,
  formatRelativeTime,
  healthStateLabel,
  healthTone,
  schedulingStateLabel,
  schedulingTone,
  tokenLimitText,
  type GatewayTone,
} from '@/utils/gateway'

const props = defineProps<{
  nodes: GatewayNode[]
  pools: GatewayPool[]
  busyId?: string
  loading?: boolean
  readonly?: boolean
  emptyText?: string
}>()
defineEmits<{
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

function tagType(tone: GatewayTone): 'success' | 'warning' | 'danger' | 'info' {
  if (tone === 'success') return 'success'
  if (tone === 'warning') return 'warning'
  if (tone === 'danger') return 'danger'
  return 'info'
}
</script>

<style scoped>
.node-cell { display: grid; gap: 2px; min-width: 0; text-decoration: none; }
.node-cell strong { overflow: hidden; color: var(--astra-text-primary); font-size: var(--astra-font-label); text-overflow: ellipsis; white-space: nowrap; }
.node-cell__url { overflow: hidden; color: var(--astra-text-muted); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.node-muted { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.row-actions { display: flex; align-items: center; gap: 2px; }
</style>
