<template>
  <div class="table-wrap">
    <table class="gateway-node-table">
      <thead>
        <tr>
          <th>节点</th>
          <th>资源池</th>
          <th>健康</th>
          <th>调度</th>
          <th>配置</th>
          <th>支持模型</th>
          <th>并发 / 权重</th>
          <th>额度（时 / 日）</th>
          <th>最近探测</th>
          <th v-if="!readonly" class="gateway-col-actions">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="node in nodes" :key="node.id">
          <td>
            <RouterLink class="gateway-node-name" :to="`/gateway/nodes/${node.id}`">
              <strong>{{ node.name }}</strong>
              <small>{{ node.base_url }}</small>
            </RouterLink>
          </td>
          <td>{{ poolName(node.pool_id) }}</td>
          <td><span class="status-badge" :data-tone="healthTone(node.health_state)">{{ healthStateLabel(node.health_state) }}</span></td>
          <td><span class="status-badge" :data-tone="schedulingTone(node.scheduling_state)">{{ schedulingStateLabel(node.scheduling_state) }}</span></td>
          <td><span class="status-badge" :data-tone="node.config_state === 'ENABLED' ? 'success' : 'neutral'">{{ configStateLabel(node.config_state) }}</span></td>
          <td>
            <span v-if="node.models.length" class="gateway-models" :title="node.models.join('、')">{{ modelSummary(node.models) }}</span>
            <span v-else class="gateway-muted">未配置</span>
          </td>
          <td class="gateway-num">{{ node.max_concurrency ? node.max_concurrency : '不限' }} / {{ node.weight }}</td>
          <td class="gateway-num">{{ limitText(node.hourly_token_limit) }} / {{ limitText(node.daily_token_limit) }}</td>
          <td class="gateway-time">{{ formatRelativeTime(node.last_checked_at) }}</td>
          <td v-if="!readonly" class="gateway-col-actions">
            <div class="gateway-row-actions">
              <RouterLink class="gateway-icon-btn" :to="`/gateway/nodes/${node.id}`" title="查看详情"><ChevronRight :size="15" /></RouterLink>
              <button class="gateway-icon-btn" type="button" title="连接/模型/SSE 探测" :disabled="busyId === node.id" @click="$emit('probe', node)"><Activity :size="15" /></button>
              <button v-if="node.scheduling_state === 'ACTIVE'" class="gateway-icon-btn" type="button" title="安全下线（DRAINING）" :disabled="busyId === node.id" @click="$emit('drain', node)"><Pause :size="15" /></button>
              <button v-else class="gateway-icon-btn" type="button" title="恢复调度" :disabled="busyId === node.id" @click="$emit('restore', node)"><Play :size="15" /></button>
              <button class="gateway-icon-btn" type="button" :title="node.config_state === 'ENABLED' ? '禁用节点' : '启用节点'" :disabled="busyId === node.id" @click="$emit('toggle-config', node)">
                <PowerOff v-if="node.config_state === 'ENABLED'" :size="15" /><Power v-else :size="15" />
              </button>
              <button class="gateway-icon-btn gateway-icon-btn--danger" type="button" title="删除节点（需已下线且并发为 0）" :disabled="busyId === node.id" @click="$emit('delete', node)"><Trash2 :size="15" /></button>
            </div>
          </td>
        </tr>
        <tr v-if="!nodes.length">
          <td :colspan="readonly ? 9 : 10" class="empty-cell">暂无节点，点击「新增节点」开始配置。</td>
        </tr>
      </tbody>
    </table>
  </div>
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
</style>