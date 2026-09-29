<template>
  <section class="gateway-nodes" data-testid="gateway-nodes">
    <header class="gateway-nodes__bar">
      <div class="gateway-nodes__intro">
        <h3>下游节点</h3>
        <ElText size="small" type="info">配置态、健康态与调度态相互独立；节点默认先安全下线再删除。</ElText>
      </div>
      <ElButton :loading="loading" :icon="RefreshCw" data-testid="gateway-nodes-refresh" @click="load">刷新</ElButton>
      <ElButton v-if="canManage" type="success" :icon="Plus" data-testid="gateway-node-create" @click="openCreate">新增节点</ElButton>
    </header>

    <ElAlert v-if="error" type="error" show-icon :closable="false" :title="error" data-testid="gateway-nodes-error">
      <ElButton size="small" type="primary" data-testid="gateway-nodes-retry" @click="load">重试</ElButton>
    </ElAlert>

    <div class="gateway-nodes__filters" aria-label="节点筛选">
      <ElInput
        v-model="filters.keyword"
        class="node-filter__keyword"
        aria-label="搜索节点"
        placeholder="搜索名称 / 地址 / 模型"
        clearable
      >
        <template #prefix><Search :size="15" /></template>
      </ElInput>
      <ElSelect v-model="filters.health" class="node-filter__health" aria-label="健康状态筛选" placeholder="健康：全部" clearable>
        <ElOption v-for="item in healthOptions" :key="item.value" :value="item.value" :label="item.label" />
      </ElSelect>
      <ElSelect v-model="filters.scheduling" class="node-filter__scheduling" aria-label="调度状态筛选" placeholder="调度：全部" clearable>
        <ElOption v-for="item in schedulingOptions" :key="item.value" :value="item.value" :label="item.label" />
      </ElSelect>
      <ElSelect v-model="filters.config" class="node-filter__config" aria-label="配置状态筛选" placeholder="配置：全部" clearable>
        <ElOption value="ENABLED" label="启用" />
        <ElOption value="DISABLED" label="禁用" />
      </ElSelect>
      <ElSelect v-model="filters.pool" class="node-filter__pool" aria-label="资源池筛选" placeholder="资源池：全部" clearable>
        <ElOption value="__none__" label="未分配" />
        <ElOption v-for="pool in pools" :key="pool.id" :value="pool.id" :label="pool.name" />
      </ElSelect>
      <ElButton v-if="hasFilters" text type="primary" @click="clearFilters">清除筛选</ElButton>
    </div>

    <GatewayNodeTable
      :nodes="pagedNodes"
      :pools="pools"
      :busy-id="busyId"
      :loading="loading"
      :readonly="!canManage"
      :empty-text="hasFilters ? '没有匹配的节点，调整筛选条件后重试。' : '暂无节点，点击「新增节点」开始配置。'"
      @detail="openDetail"
      @probe="onProbe"
      @drain="onDrain"
      @restore="onRestore"
      @toggle-config="onToggleConfig"
      @edit="openEdit"
      @delete="onDelete"
    />

    <footer v-if="filteredNodes.length" class="gateway-nodes__footer">
      <ElText size="small" type="info">共 {{ filteredNodes.length }} 条</ElText>
      <ElPagination
        :current-page="page"
        :page-size="pageSize"
        :total="filteredNodes.length"
        layout="prev, pager, next"
        aria-label="节点列表分页"
        data-testid="gateway-nodes-pagination"
        @current-change="page = $event"
      />
    </footer>

    <GatewayNodeDrawer :open="drawerOpen" :node="drawerNode" :pools="pools" @close="drawerOpen = false" @saved="load" />
  </section>
</template>

<script setup lang="ts">
import { Plus, RefreshCw, Search } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElAlert, ElButton, ElInput, ElOption, ElPagination, ElSelect, ElText } from 'element-plus'
import {
  gatewayApi,
  GatewayApiError,
  type GatewayNode,
  type GatewayPool,
  type GatewayProbeType,
} from '@/api/gateway'
import { confirmDialog } from '@/composables/useConfirm'
import { notify } from '@/composables/useToast'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import { errorMessage, healthStateLabel, schedulingStateLabel } from '@/utils/gateway'
import GatewayNodeDrawer from '@/views/gateway/GatewayNodeDrawer.vue'
import GatewayNodeTable from '@/views/gateway/GatewayNodeTable.vue'

const router = useRouter()
const { hasRole, disconnect } = useGatewayAuth()
const canManage = computed(() => hasRole('node'))
const nodes = ref<GatewayNode[]>([])
const pools = ref<GatewayPool[]>([])
const loading = ref(false)
const error = ref('')
const busyId = ref('')
const drawerOpen = ref(false)
const drawerNode = ref<GatewayNode | null>(null)
const allProbes: GatewayProbeType[] = ['NETWORK', 'SERVICE', 'MODEL', 'STREAM']

const healthOptions = (['HEALTHY', 'DEGRADED', 'UNHEALTHY', 'CHECKING', 'UNKNOWN'] as const)
  .map((value) => ({ value, label: healthStateLabel(value) }))
const schedulingOptions = (['ACTIVE', 'DRAINING', 'BLOCKED'] as const)
  .map((value) => ({ value, label: schedulingStateLabel(value) }))

const filters = reactive({ keyword: '', health: '', scheduling: '', config: '', pool: '' })
const page = ref(1)
const pageSize = 10

const filteredNodes = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return nodes.value.filter((node) => {
    if (keyword && !`${node.name} ${node.base_url} ${node.models.join(' ')}`.toLowerCase().includes(keyword)) return false
    if (filters.health && node.health_state !== filters.health) return false
    if (filters.scheduling && node.scheduling_state !== filters.scheduling) return false
    if (filters.config && node.config_state !== filters.config) return false
    if (filters.pool && (node.pool_id ?? '__none__') !== filters.pool) return false
    return true
  })
})
const pagedNodes = computed(() => {
  const start = (page.value - 1) * pageSize
  return filteredNodes.value.slice(start, start + pageSize)
})
const hasFilters = computed(() => Boolean(
  filters.keyword.trim() || filters.health || filters.scheduling || filters.config || filters.pool,
))

watch(filteredNodes, (list) => {
  const maxPage = Math.max(1, Math.ceil(list.length / pageSize))
  if (page.value > maxPage) page.value = maxPage
})
watch(filters, () => { page.value = 1 })

function clearFilters() {
  filters.keyword = ''
  filters.health = ''
  filters.scheduling = ''
  filters.config = ''
  filters.pool = ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [nodeList, poolList] = await Promise.all([gatewayApi.nodes(), gatewayApi.pools()])
    nodes.value = nodeList
    pools.value = poolList
  } catch (reason) {
    if (reason instanceof GatewayApiError && reason.status === 401) { disconnect(); return }
    error.value = errorMessage(reason, '节点列表加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  drawerNode.value = null
  drawerOpen.value = true
}

function openEdit(node: GatewayNode) {
  drawerNode.value = node
  drawerOpen.value = true
}

function openDetail(node: GatewayNode) {
  router.push(`/gateway/nodes/${node.id}`)
}

async function onProbe(node: GatewayNode) {
  busyId.value = node.id
  try {
    const result = await gatewayApi.probeNode(node.id, allProbes)
    const passed = result.checks.filter((check) => check.success).length
    notify(`${node.name} 探测完成：${passed}/${result.checks.length} 项通过`, passed === result.checks.length ? 'success' : 'info')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '探测失败'), 'error')
  } finally {
    busyId.value = ''
  }
}

async function onDrain(node: GatewayNode) {
  const confirmed = await confirmDialog({ title: '安全下线节点', message: `确认让「${node.name}」进入 DRAINING？活跃请求会继续完成，新请求改走其它节点。`, confirmLabel: '安全下线', danger: true })
  if (!confirmed) return
  busyId.value = node.id
  try {
    await gatewayApi.drainNode(node.id)
    notify('节点已进入安全下线')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '下线失败'), 'error')
  } finally {
    busyId.value = ''
  }
}

async function onRestore(node: GatewayNode) {
  busyId.value = node.id
  try {
    await gatewayApi.activateNode(node.id)
    notify('节点已恢复调度')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '恢复失败'), 'error')
  } finally {
    busyId.value = ''
  }
}

async function onToggleConfig(node: GatewayNode) {
  const enable = node.config_state !== 'ENABLED'
  busyId.value = node.id
  try {
    await gatewayApi.updateNode(node.id, { config_state: enable ? 'ENABLED' : 'DISABLED' })
    notify(enable ? '节点已启用' : '节点已禁用')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '状态更新失败'), 'error')
  } finally {
    busyId.value = ''
  }
}

async function onDelete(node: GatewayNode) {
  const confirmed = await confirmDialog({ title: '删除节点', message: `确认删除「${node.name}」？仅当节点已 DRAINING 且活跃并发为 0 时才允许删除。`, confirmLabel: '删除节点', danger: true })
  if (!confirmed) return
  busyId.value = node.id
  try {
    await gatewayApi.deleteNode(node.id)
    notify('节点已删除')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '删除失败'), 'error')
  } finally {
    busyId.value = ''
  }
}

onMounted(load)
</script>

<style scoped>
.gateway-nodes { display: grid; gap: 12px; }
.gateway-nodes__bar { display: flex; align-items: center; gap: 12px; }
.gateway-nodes__intro { margin-right: auto; }
.gateway-nodes__intro h3 { margin: 0; color: var(--astra-text-primary); }
.gateway-nodes__filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.node-filter__keyword { max-width: 280px; }
.node-filter__health { width: 132px; }
.node-filter__scheduling { width: 136px; }
.node-filter__config { width: 120px; }
.node-filter__pool { width: 152px; }
.gateway-nodes__footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 2px; }
</style>
