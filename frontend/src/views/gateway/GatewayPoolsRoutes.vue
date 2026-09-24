<template>
  <section class="gateway-section">
    <header class="gateway-section__head">
      <div><h3>资源池与模型路由</h3><p>路由模型名唯一，第一阶段一个路由指向一个资源池。</p></div>
      <el-button :loading="loading" :disabled="loading" @click="load"><RefreshCw v-if="!loading" :size="14" />刷新</el-button>
    </header>

    <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<el-button type="danger" link @click="load">重试</el-button></p>

    <div class="gateway-two-col">
      <AstraPanel title="资源池" :subtitle="`共 ${pools.length} 个`" flush>
        <template #action><el-button v-if="canRoute" type="primary" size="small" @click="openPoolCreate"><Plus :size="13" />新增资源池</el-button></template>
        <el-table :data="pools" stripe empty-text="暂无资源池。">
          <el-table-column label="名称" min-width="180"><template #default="{ row }"><strong>{{ row.name }}</strong><small>{{ row.description || '—' }}</small></template></el-table-column>
          <el-table-column prop="weight" label="权重" width="90" />
          <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'" effect="light">{{ row.enabled ? '启用' : '禁用' }}</el-tag></template></el-table-column>
          <el-table-column prop="sort_order" label="排序" width="90" />
          <el-table-column v-if="canRoute" label="操作" width="100" fixed="right">
            <template #default="{ row }"><el-button text circle title="编辑" @click="openPoolEdit(row)"><Pencil :size="14" /></el-button><el-button type="danger" text circle title="删除" @click="removePool(row)"><Trash2 :size="14" /></el-button></template>
          </el-table-column>
        </el-table>
      </AstraPanel>

      <AstraPanel title="模型路由" :subtitle="`共 ${routes.length} 条`" flush>
        <template #action><el-button v-if="canRoute" type="primary" size="small" @click="openRouteCreate"><Plus :size="13" />新增路由</el-button></template>
        <el-table :data="routes" stripe empty-text="暂无模型路由。">
          <el-table-column label="模型" min-width="190"><template #default="{ row }"><strong>{{ row.model }}</strong><small>{{ row.description || '—' }}</small></template></el-table-column>
          <el-table-column label="资源池" min-width="140"><template #default="{ row }">{{ poolName(row.pool_id) }}</template></el-table-column>
          <el-table-column prop="weight" label="权重" width="90" />
          <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'" effect="light">{{ row.enabled ? '启用' : '禁用' }}</el-tag></template></el-table-column>
          <el-table-column v-if="canRoute" label="操作" width="100" fixed="right">
            <template #default="{ row }"><el-button text circle title="编辑" @click="openRouteEdit(row)"><Pencil :size="14" /></el-button><el-button type="danger" text circle title="删除" @click="removeRoute(row)"><Trash2 :size="14" /></el-button></template>
          </el-table-column>
        </el-table>
      </AstraPanel>
    </div>

    <el-dialog :model-value="poolDialog" :title="poolForm.id ? '编辑资源池' : '新增资源池'" data-testid="gateway-pool-dialog" @close="poolDialog = false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="!(saving)"
      append-to-body
      lock-scroll
      destroy-on-close
    >
      <form id="gateway-pool-form" class="gateway-dialog-form" @submit.prevent="submitPool">
        <label>名称<el-input v-model="poolForm.name" required /></label>
        <label>描述<el-input v-model="poolForm.description" type="textarea" :rows="2" resize="vertical" /></label>
        <div class="gateway-form__grid">
          <label>权重<el-input v-model="poolForm.weight" type="number" min="0" /></label>
          <label>排序<el-input v-model="poolForm.sort_order" type="number" /></label>
        </div>
        <label class="gateway-toggle"><span>启用</span><el-switch v-model="poolForm.enabled" /></label>
      </form>
      <template #footer>
        <el-button :disabled="saving" @click="poolDialog = false">取消</el-button>
        <el-button type="primary" native-type="submit" form="gateway-pool-form" :loading="saving" :disabled="saving">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog :model-value="routeDialog" :title="routeForm.id ? '编辑路由' : '新增路由'" data-testid="gateway-route-dialog" @close="routeDialog = false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="!(saving)"
      append-to-body
      lock-scroll
      destroy-on-close
    >
      <form id="gateway-route-form" class="gateway-dialog-form" @submit.prevent="submitRoute">
        <label>模型名<el-input v-model="routeForm.model" required placeholder="例如 gpt-4o-mini" /></label>
        <label>资源池<el-select v-model="routeForm.pool_id" placeholder="选择资源池"><el-option v-for="pool in pools" :key="pool.id" :label="pool.name" :value="pool.id" /></el-select></label>
        <label>描述<el-input v-model="routeForm.description" type="textarea" :rows="2" resize="vertical" /></label>
        <div class="gateway-form__grid">
          <label>权重<el-input v-model="routeForm.weight" type="number" min="0" /></label>
          <label class="gateway-toggle"><span>启用</span><el-switch v-model="routeForm.enabled" /></label>
        </div>
      </form>
      <template #footer>
        <el-button :disabled="saving" @click="routeDialog = false">取消</el-button>
        <el-button type="primary" native-type="submit" form="gateway-route-form" :loading="saving" :disabled="saving">保存</el-button>
      </template>
    </el-dialog>
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
import AstraPanel from '@/components/astra/AstraPanel.vue'
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
:deep(.el-table strong) { display:block;color:var(--astra-text-primary);font-size:var(--astra-font-body) }
:deep(.el-table small) { display:block;max-width:220px;overflow:hidden;color:var(--astra-text-muted);font-size:var(--astra-font-helper);text-overflow:ellipsis;white-space:nowrap }
.gateway-dialog-form :deep(.el-select){width:100%}
.gateway-dialog-form { display: grid; gap: 12px; }
.gateway-dialog-form label { display: grid; gap: 6px; margin: 0; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
@media (max-width: 900px) { .gateway-two-col { grid-template-columns: 1fr; } }
</style>