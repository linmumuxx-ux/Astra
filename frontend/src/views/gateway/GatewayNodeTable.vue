<template>
  <el-table :data="nodes" stripe empty-text="暂无节点，点击「新增节点」开始配置。" class="gateway-node-table">
    <el-table-column label="节点" min-width="220">
      <template #default="{ row }">
        <RouterLink class="gateway-node-name" :to="`/gateway/nodes/${row.id}`">
          <strong>{{ row.name }}</strong>
          <small>{{ row.base_url }}</small>
        </RouterLink>
      </template>
    </el-table-column>
    <el-table-column label="资源池" min-width="130"><template #default="{ row }">{{ poolName(row.pool_id) }}</template></el-table-column>
    <el-table-column label="健康" width="100">
      <template #default="{ row }"><el-tag :type="tagType(healthTone(row.health_state))" effect="light">{{ healthStateLabel(row.health_state) }}</el-tag></template>
    </el-table-column>
    <el-table-column label="调度" width="110">
      <template #default="{ row }"><el-tag :type="tagType(schedulingTone(row.scheduling_state))" effect="light">{{ schedulingStateLabel(row.scheduling_state) }}</el-tag></template>
    </el-table-column>
    <el-table-column label="配置" width="100">
      <template #default="{ row }"><el-tag :type="row.config_state === 'ENABLED' ? 'success' : 'info'" effect="light">{{ configStateLabel(row.config_state) }}</el-tag></template>
    </el-table-column>
    <el-table-column label="支持模型" min-width="180">
      <template #default="{ row }"><span v-if="row.models.length" class="gateway-models" :title="row.models.join('、')">{{ modelSummary(row.models) }}</span><span v-else class="gateway-muted">未配置</span></template>
    </el-table-column>
    <el-table-column label="并发 / 权重" width="110" align="right"><template #default="{ row }">{{ row.max_concurrency || '不限' }} / {{ row.weight }}</template></el-table-column>
    <el-table-column label="额度（时 / 日）" min-width="140" align="right"><template #default="{ row }">{{ limitText(row.hourly_token_limit) }} / {{ limitText(row.daily_token_limit) }}</template></el-table-column>
    <el-table-column label="最近探测" min-width="120"><template #default="{ row }">{{ formatRelativeTime(row.last_checked_at) }}</template></el-table-column>
    <el-table-column v-if="!readonly" label="操作" width="220" fixed="right">
      <template #default="{ row }">
        <div class="gateway-row-actions">
          <RouterLink :to="`/gateway/nodes/${row.id}`" title="查看详情"><el-button text circle><ChevronRight :size="15" /></el-button></RouterLink>
          <el-button text circle title="连接/模型/SSE 探测" :loading="busyId === row.id" :disabled="busyId === row.id" @click="$emit('probe', row)"><Activity v-if="busyId !== row.id" :size="15" /></el-button>
          <el-button v-if="row.scheduling_state === 'ACTIVE'" text circle title="安全下线（DRAINING）" :disabled="busyId === row.id" @click="$emit('drain', row)"><Pause :size="15" /></el-button>
          <el-button v-else text circle title="恢复调度" :disabled="busyId === row.id" @click="$emit('restore', row)"><Play :size="15" /></el-button>
          <el-button text circle :title="row.config_state === 'ENABLED' ? '禁用节点' : '启用节点'" :disabled="busyId === row.id" @click="$emit('toggle-config', row)"><PowerOff v-if="row.config_state === 'ENABLED'" :size="15" /><Power v-else :size="15" /></el-button>
          <el-button type="danger" text circle title="删除节点（需已下线且并发为 0）" :disabled="busyId === row.id" @click="$emit('delete', row)"><Trash2 :size="15" /></el-button>
        </div>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">

import { Activity, ChevronRight, Pause, Play, Power, PowerOff, Trash2 } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import type { GatewayNode, GatewayPool } from '@/api/gateway'
import {
  configStateLabel,
  formatRelativeTime,
  healthStateLabel,
  healthTone,
  schedulingStateLabel,
  schedulingTone,
} from '@/utils/gateway'

const props = defineProps<{ nodes: GatewayNode[]; pools: GatewayPool[]; busyId?: string; readonly?: boolean }>()
defineEmits<{
  probe: [node: GatewayNode]
  drain: [node: GatewayNode]
  restore: [node: GatewayNode]
  'toggle-config': [node: GatewayNode]
  delete: [node: GatewayNode]
}>()

function poolName(poolId: string | null): string {
  if (!poolId) return '未分配'
  return props.pools.find((pool) => pool.id === poolId)?.name ?? poolId
}

function modelSummary(models: string[]): string {
  if (models.length <= 2) return models.join('、')
  return `${models.slice(0, 2).join('、')} +${models.length - 2}`
}

function limitText(value: number | null): string {
  if (value === null || value === undefined) return '不限'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`
  return String(value)
}

function tagType(tone: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (tone === 'success' || tone === 'warning' || tone === 'danger' || tone === 'info') return tone
  return 'info'
}
</script>

<style scoped>

.gateway-node-table { min-width: 1080px; }
.gateway-node-name { display: grid; gap: 3px; }
.gateway-node-name strong { color: var(--astra-text-primary); font-size: var(--astra-font-body); }
.gateway-node-name small { max-width: 260px; overflow: hidden; color: var(--astra-text-muted); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.gateway-models { display: inline-block; max-width: 200px; overflow: hidden; font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.gateway-muted { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-num, .gateway-time { white-space: nowrap; font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.gateway-col-actions { width: 190px; }
.gateway-row-actions { display: flex; gap: 3px; }
.gateway-icon-btn { display: grid; place-items: center; width: 27px; height: 27px; color: var(--astra-text-muted); border: 1px solid transparent; border-radius: 7px; background: transparent; cursor: pointer; }
.gateway-icon-btn:hover:not(:disabled) { color: var(--astra-primary-bright); border-color: var(--astra-border); background: var(--astra-primary-soft); }
.gateway-icon-btn--danger:hover:not(:disabled) { color: var(--astra-danger); border-color: rgba(228, 93, 106, .3); background: var(--astra-danger-soft); }
.gateway-icon-btn:disabled { opacity: .45; cursor: not-allowed; }

.gateway-row-actions { display:flex;align-items:center;gap:2px; }
.gateway-row-actions :deep(.el-button) { margin-left:0; }
</style>
