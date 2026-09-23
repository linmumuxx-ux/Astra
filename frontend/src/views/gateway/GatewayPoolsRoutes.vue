<template>
  <section class="gateway-section">
    <header class="gateway-section__head">
      <div><h3>资源池与模型路由</h3><p>路由模型名唯一，第一阶段一个路由指向一个资源池。</p></div>
      <button type="button" class="button" :disabled="loading" @click="load"><RefreshCw :size="14" :class="{ spin: loading }" />刷新</button>
    </header>

    <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<button type="button" @click="load">重试</button></p>

    <div class="gateway-two-col">
      <AstraPanel title="资源池" :subtitle="`共 ${pools.length} 个`" flush>
        <template #action><button v-if="canRoute" type="button" class="button button--compact" @click="openPoolCreate"><Plus :size="13" />新增资源池</button></template>
        <div class="table-wrap">
          <table class="gateway-mini-table">
            <thead><tr><th>名称</th><th>权重</th><th>状态</th><th>排序</th><th class="gateway-col-actions">操作</th></tr></thead>
            <tbody>
              <tr v-for="pool in pools" :key="pool.id">
                <td><strong>{{ pool.name }}</strong><small>{{ pool.description || '—' }}</small></td>
                <td>{{ pool.weight }}</td>
                <td><span class="status-badge" :data-tone="pool.enabled ? 'success' : 'neutral'">{{ pool.enabled ? '启用' : '禁用' }}</span></td>
                <td>{{ pool.sort_order }}</td>
                <td class="gateway-col-actions">
                  <div v-if="canRoute" class="gateway-row-actions">
                    <button class="gateway-icon-btn" type="button" title="编辑" @click="openPoolEdit(pool)"><Pencil :size="14" /></button>
                    <button class="gateway-icon-btn gateway-icon-btn--danger" type="button" title="删除" @click="removePool(pool)"><Trash2 :size="14" /></button>
                  </div>
                </td>
              </tr>
              <tr v-if="!pools.length"><td colspan="5" class="empty-cell">暂无资源池。</td></tr>
            </tbody>
          </table>
        </div>
      </AstraPanel>

      <AstraPanel title="模型路由" :subtitle="`共 ${routes.length} 条`" flush>
        <template #action><button v-if="canRoute" type="button" class="button button--compact" @click="openRouteCreate"><Plus :size="13" />新增路由</button></template>
        <div class="table-wrap">
          <table class="gateway-mini-table">
            <thead><tr><th>模型</th><th>资源池</th><th>权重</th><th>状态</th><th class="gateway-col-actions">操作</th></tr></thead>
            <tbody>
              <tr v-for="route in routes" :key="route.id">
                <td><strong>{{ route.model }}</strong><small>{{ route.description || '—' }}</small></td>
                <td>{{ poolName(route.pool_id) }}</td>
                <td>{{ route.weight }}</td>
                <td><span class="status-badge" :data-tone="route.enabled ? 'success' : 'neutral'">{{ route.enabled ? '启用' : '禁用' }}</span></td>
                <td class="gateway-col-actions">
                  <div v-if="canRoute" class="gateway-row-actions">
                    <button class="gateway-icon-btn" type="button" title="编辑" @click="openRouteEdit(route)"><Pencil :size="14" /></button>
                    <button class="gateway-icon-btn gateway-icon-btn--danger" type="button" title="删除" @click="removeRoute(route)"><Trash2 :size="14" /></button>
                  </div>
                </td>
              </tr>
              <tr v-if="!routes.length"><td colspan="5" class="empty-cell">暂无模型路由。</td></tr>
            </tbody>
          </table>
        </div>
      </AstraPanel>
    </div>

    <AstraDialog :open="poolDialog" :title="poolForm.id ? '编辑资源池' : '新增资源池'" :busy="saving" testid="gateway-pool-dialog" @close="poolDialog = false">
      <form id="gateway-pool-form" class="gateway-dialog-form" @submit.prevent="submitPool">
        <label>名称<input v-model="poolForm.name" required /></label>
        <label>描述<textarea v-model="poolForm.description" rows="2" /></label>
        <div class="gateway-form__grid">
          <label>权重<input v-model="poolForm.weight" type="number" min="0" /></label>
          <label>排序<input v-model="poolForm.sort_order" type="number" /></label>
        </div>
        <label class="gateway-toggle"><span>启用</span><AstraSwitch v-model="poolForm.enabled" /></label>
      </form>
      <template #footer>
        <button type="button" class="button" :disabled="saving" @click="poolDialog = false">取消</button>
        <button type="submit" form="gateway-pool-form" class="button button--primary" :disabled="saving">保存</button>
      </template>
    </AstraDialog>

    <AstraDialog :open="routeDialog" :title="routeForm.id ? '编辑路由' : '新增路由'" :busy="saving" testid="gateway-route-dialog" @close="routeDialog = false">
      <form id="gateway-route-form" class="gateway-dialog-form" @submit.prevent="submitRoute">
        <label>模型名<input v-model="routeForm.model" required placeholder="例如 gpt-4o-mini" /></label>
        <label>资源池<select v-model="routeForm.pool_id" required><option value="" disabled>选择资源池</option><option v-for="pool in pools" :key="pool.id" :value="pool.id">{{ pool.name }}</option></select></label>
        <label>描述<textarea v-model="routeForm.description" rows="2" /></label>
        <div class="gateway-form__grid">
          <label>权重<input v-model="routeForm.weight" type="number" min="0" /></label>
          <label class="gateway-toggle"><span>启用</span><AstraSwitch v-model="routeForm.enabled" /></label>
        </div>
      </form>
      <template #footer>
        <button type="button" class="button" :disabled="saving" @click="routeDialog = false">取消</button>
        <button type="submit" form="gateway-route-form" class="button button--primary" :disabled="saving">保存</button>
      </template>
    </AstraDialog>
  </section>
</template>

<script setup lang="ts">
import { Pencil, Plus, RefreshCw, Trash2, TriangleAlert } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref } from 'vue'
import {
  gatewayApi,
  GatewayApiError,
  type GatewayPool,
  type GatewayRoute,
} from '@/api/gateway'
import AstraDialog from '@/components/astra/AstraDialog.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraSwitch from '@/components/astra/AstraSwitch.vue'
import { confirmDialog } from '@/composables/useConfirm'
import { notify } from '@/composables/useToast'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import { errorMessage } from '@/utils/gateway'

const { hasRole, disconnect } = useGatewayAuth()
const canRoute = computed(() => hasRole('route'))
const pools = ref<GatewayPool[]>([])
const routes = ref<GatewayRoute[]>([])
const loading = ref(false)
const error = ref('')
const saving = ref(false)
const poolDialog = ref(false)
const routeDialog = ref(false)

const poolForm = reactive({ id: '', name: '', description: '', weight: '1', sort_order: '0', enabled: true })
const routeForm = reactive({ id: '', model: '', pool_id: '', description: '', weight: '1', enabled: true })

function poolName(poolId: string): string {
  return pools.value.find((pool) => pool.id === poolId)?.name ?? poolId
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [poolList, routeList] = await Promise.all([gatewayApi.pools(), gatewayApi.routes()])
    pools.value = poolList
    routes.value = routeList
  } catch (reason) {
    if (reason instanceof GatewayApiError && reason.status === 401) { disconnect(); return }
    error.value = errorMessage(reason, '资源池 / 路由加载失败')
  } finally {
    loading.value = false
  }
}

function openPoolCreate() {
  Object.assign(poolForm, { id: '', name: '', description: '', weight: '1', sort_order: '0', enabled: true })
  poolDialog.value = true
}

function openPoolEdit(pool: GatewayPool) {
  Object.assign(poolForm, {
    id: pool.id,
    name: pool.name,
    description: pool.description,
    weight: String(pool.weight),
    sort_order: String(pool.sort_order),
    enabled: pool.enabled,
  })
  poolDialog.value = true
}

async function submitPool() {
  saving.value = true
  try {
    const body = {
      name: poolForm.name.trim(),
      description: poolForm.description,
      weight: Number(poolForm.weight) || 0,
      sort_order: Number(poolForm.sort_order) || 0,
      enabled: poolForm.enabled,
    }
    if (poolForm.id) await gatewayApi.updatePool(poolForm.id, body)
    else await gatewayApi.createPool(body)
    poolDialog.value = false
    notify('资源池已保存')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '保存资源池失败'), 'error')
  } finally {
    saving.value = false
  }
}

async function removePool(pool: GatewayPool) {
  const confirmed = await confirmDialog({ title: '删除资源池', message: `确认删除「${pool.name}」？仍被路由引用的资源池无法删除。`, confirmLabel: '删除', danger: true })
  if (!confirmed) return
  try {
    await gatewayApi.deletePool(pool.id)
    notify('资源池已删除')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '删除失败'), 'error')
  }
}

function openRouteCreate() {
  Object.assign(routeForm, { id: '', model: '', pool_id: '', description: '', weight: '1', enabled: true })
  routeDialog.value = true
}

function openRouteEdit(route: GatewayRoute) {
  Object.assign(routeForm, {
    id: route.id,
    model: route.model,
    pool_id: route.pool_id,
    description: route.description,
    weight: String(route.weight),
    enabled: route.enabled,
  })
  routeDialog.value = true
}

async function submitRoute() {
  saving.value = true
  try {
    const body = {
      model: routeForm.model.trim(),
      pool_id: routeForm.pool_id,
      description: routeForm.description,
      weight: Number(routeForm.weight) || 0,
      enabled: routeForm.enabled,
    }
    if (routeForm.id) await gatewayApi.updateRoute(routeForm.id, body)
    else await gatewayApi.createRoute(body)
    routeDialog.value = false
    notify('路由已保存')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '保存路由失败'), 'error')
  } finally {
    saving.value = false
  }
}

async function removeRoute(route: GatewayRoute) {
  const confirmed = await confirmDialog({ title: '删除路由', message: `确认删除模型「${route.model}」的路由？`, confirmLabel: '删除', danger: true })
  if (!confirmed) return
  try {
    await gatewayApi.deleteRoute(route.id)
    notify('路由已删除')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '删除失败'), 'error')
  }
}

onMounted(load)
</script>

<style scoped>
.gateway-two-col { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; align-items: start; }
.gateway-mini-table { min-width: 420px; }
.gateway-mini-table td strong { display: block; color: var(--astra-text-primary); font-size: var(--astra-font-body); }
.gateway-mini-table td small { display: block; max-width: 220px; overflow: hidden; color: var(--astra-text-muted); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.gateway-dialog-form { display: grid; gap: 12px; }
.gateway-dialog-form label { display: grid; gap: 6px; margin: 0; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
@media (max-width: 900px) { .gateway-two-col { grid-template-columns: 1fr; } }
</style>