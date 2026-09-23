<template>
  <section class="gateway-section">
    <header class="gateway-section__head">
      <div><h3>节点</h3><p>配置态、健康态与调度态相互独立；节点默认先安全下线再删除。</p></div>
      <div class="gateway-section__actions">
        <button type="button" class="button" :disabled="loading" @click="load"><RefreshCw :size="14" :class="{ spin: loading }" />刷新</button>
        <button v-if="canManage" type="button" class="button button--primary" @click="openCreate"><Plus :size="15" />新增节点</button>
      </div>
    </header>

    <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<button type="button" @click="load">重试</button></p>

    <GatewayNodeTable
      :nodes="nodes"
      :pools="pools"
      :busy-id="busyId"
      @probe="onProbe"
      @drain="onDrain"
      @restore="onRestore"
      @toggle-config="onToggleConfig"
      @delete="onDelete"
    />

    <GatewayNodeDrawer :open="drawerOpen" :node="drawerNode" :pools="pools" @close="drawerOpen = false" @saved="load" />
  </section>
</template>

<script setup lang="ts">
import { Plus, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
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
import { errorMessage } from '@/utils/gateway'
import GatewayNodeDrawer from '@/views/gateway/GatewayNodeDrawer.vue'
import GatewayNodeTable from '@/views/gateway/GatewayNodeTable.vue'

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
.gateway-section { display: grid; gap: 14px; }
.gateway-section__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.gateway-section__head h3 { margin: 0; color: var(--astra-text-primary); }
.gateway-section__head p { margin: 4px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-section__actions { display: flex; gap: 8px; }
.gateway-alert { display: flex; align-items: center; gap: 7px; margin: 0; padding: 10px 12px; color: var(--astra-danger); border: 1px solid rgba(228, 93, 106, .2); border-radius: 9px; background: var(--astra-danger-soft); font-size: var(--astra-font-helper); }
.gateway-alert button { margin-left: auto; color: inherit; border: 0; background: transparent; text-decoration: underline; cursor: pointer; }
</style>