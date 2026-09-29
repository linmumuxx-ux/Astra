<template>
  <section class="gateway-pools-routes" data-testid="gateway-pools-routes">
    <header class="gateway-pools-routes__bar">
      <div class="gateway-pools-routes__intro">
        <h3>资源池与模型路由</h3>
        <ElText type="info">路由模型名唯一，第一阶段一个路由指向一个资源池。</ElText>
      </div>
      <ElButton :loading="loading" :icon="RefreshCw" data-testid="gateway-pools-routes-refresh" @click="load">刷新</ElButton>
    </header>

    <ElAlert v-if="error" type="error" show-icon :closable="false" :title="error" data-testid="gateway-pools-routes-error">
      <ElButton type="primary" data-testid="gateway-pools-routes-retry" @click="load">重试</ElButton>
    </ElAlert>

    <ElCard shadow="never" data-testid="gateway-pool-card">
      <template #header>
        <div class="gateway-pools-routes__card-head">
          <div class="gateway-pools-routes__card-title">
            <h4>资源池</h4>
            <ElText type="info">仍被节点或路由引用的资源池无法删除。</ElText>
          </div>
          <ElButton v-if="canRoute" type="success" :icon="Plus" data-testid="gateway-pool-create" @click="openPoolCreate">新增资源池</ElButton>
        </div>
      </template>

      <div class="gateway-pools-routes__filters" aria-label="资源池筛选">
        <ElInput
          v-model="poolFilters.keyword"
          class="pool-filter__keyword"
          aria-label="搜索资源池"
          placeholder="搜索名称 / 描述"
          clearable
        >
          <template #prefix><Search :size="15" /></template>
        </ElInput>
        <ElSelect v-model="poolFilters.enabled" class="pool-filter__enabled" aria-label="资源池启用筛选" placeholder="状态：全部" clearable>
          <ElOption value="enabled" label="启用" />
          <ElOption value="disabled" label="禁用" />
        </ElSelect>
        <ElButton v-if="poolHasFilters" text type="primary" @click="clearPoolFilters">清除筛选</ElButton>
      </div>

      <ElTable
        v-loading="loading"
        :data="pagedPools"
        row-key="id"
        element-loading-text="正在加载资源池"
        data-testid="gateway-pool-table"
      >
        <ElTableColumn label="名称" min-width="220">
          <template #default="{ row }">
            <div class="pool-cell">
              <strong>{{ row.name }}</strong>
              <span class="pool-cell__desc" :title="row.description">{{ row.description || '—' }}</span>
            </div>
          </template>
        </ElTableColumn>
        <ElTableColumn label="权重" prop="weight" width="90" />
        <ElTableColumn label="状态" width="90">
          <template #default="{ row }">
            <ElTag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '禁用' }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="排序" prop="sort_order" width="80" />
        <ElTableColumn v-if="canRoute" label="操作" width="88" fixed="right">
          <template #default="{ row }">
            <ElSpace :size="4">
              <ElTooltip content="编辑资源池" placement="top">
                <ElButton circle type="primary" :icon="Pencil" :aria-label="`编辑 ${row.name}`" :disabled="busy" @click="openPoolEdit(row as GatewayPool)" />
              </ElTooltip>
              <ElTooltip content="删除资源池（被引用时无法删除）" placement="top">
                <ElButton circle type="danger" :icon="Trash2" :aria-label="`删除 ${row.name}`" :disabled="busy" @click="removePool(row as GatewayPool)" />
              </ElTooltip>
            </ElSpace>
          </template>
        </ElTableColumn>
        <template #empty>
          <ElEmpty v-if="!loading" :image-size="64" :description="poolEmptyText" />
        </template>
      </ElTable>

      <footer v-if="filteredPools.length" class="gateway-pools-routes__footer">
        <ElText type="info">共 {{ filteredPools.length }} 个</ElText>
        <ElPagination
          :current-page="poolPage"
          :page-size="pageSize"
          :total="filteredPools.length"
          layout="prev, pager, next"
          aria-label="资源池列表分页"
          data-testid="gateway-pool-pagination"
          @current-change="poolPage = $event"
        />
      </footer>
    </ElCard>

    <ElCard shadow="never" data-testid="gateway-route-card">
      <template #header>
        <div class="gateway-pools-routes__card-head">
          <div class="gateway-pools-routes__card-title">
            <h4>模型路由</h4>
            <ElText type="info">每条路由把一个模型名指向一个资源池。</ElText>
          </div>
          <ElButton v-if="canRoute" type="success" :icon="Plus" data-testid="gateway-route-create" @click="openRouteCreate">新增路由</ElButton>
        </div>
      </template>

      <div class="gateway-pools-routes__filters" aria-label="路由筛选">
        <ElInput
          v-model="routeFilters.keyword"
          class="route-filter__keyword"
          aria-label="搜索路由"
          placeholder="搜索模型名 / 描述"
          clearable
        >
          <template #prefix><Search :size="15" /></template>
        </ElInput>
        <ElSelect v-model="routeFilters.pool" class="route-filter__pool" aria-label="路由资源池筛选" placeholder="资源池：全部" clearable>
          <ElOption v-for="pool in pools" :key="pool.id" :value="pool.id" :label="pool.name" />
        </ElSelect>
        <ElSelect v-model="routeFilters.enabled" class="route-filter__enabled" aria-label="路由启用筛选" placeholder="状态：全部" clearable>
          <ElOption value="enabled" label="启用" />
          <ElOption value="disabled" label="禁用" />
        </ElSelect>
        <ElButton v-if="routeHasFilters" text type="primary" @click="clearRouteFilters">清除筛选</ElButton>
      </div>

      <ElTable
        v-loading="loading"
        :data="pagedRoutes"
        row-key="id"
        element-loading-text="正在加载路由"
        data-testid="gateway-route-table"
      >
        <ElTableColumn label="模型名" min-width="220">
          <template #default="{ row }">
            <div class="pool-cell">
              <strong>{{ row.model }}</strong>
              <span class="pool-cell__desc" :title="row.description">{{ row.description || '—' }}</span>
            </div>
          </template>
        </ElTableColumn>
        <ElTableColumn label="资源池" width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ poolName(row.pool_id) }}</template>
        </ElTableColumn>
        <ElTableColumn label="权重" prop="weight" width="90" />
        <ElTableColumn label="状态" width="90">
          <template #default="{ row }">
            <ElTag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '禁用' }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn v-if="canRoute" label="操作" width="88" fixed="right">
          <template #default="{ row }">
            <ElSpace :size="4">
              <ElTooltip content="编辑路由" placement="top">
                <ElButton circle type="primary" :icon="Pencil" :aria-label="`编辑 ${row.model}`" :disabled="busy" @click="openRouteEdit(row as GatewayRoute)" />
              </ElTooltip>
              <ElTooltip content="删除路由" placement="top">
                <ElButton circle type="danger" :icon="Trash2" :aria-label="`删除 ${row.model}`" :disabled="busy" @click="removeRoute(row as GatewayRoute)" />
              </ElTooltip>
            </ElSpace>
          </template>
        </ElTableColumn>
        <template #empty>
          <ElEmpty v-if="!loading" :image-size="64" :description="routeEmptyText" />
        </template>
      </ElTable>

      <footer v-if="filteredRoutes.length" class="gateway-pools-routes__footer">
        <ElText type="info">共 {{ filteredRoutes.length }} 条</ElText>
        <ElPagination
          :current-page="routePage"
          :page-size="pageSize"
          :total="filteredRoutes.length"
          layout="prev, pager, next"
          aria-label="路由列表分页"
          data-testid="gateway-route-pagination"
          @current-change="routePage = $event"
        />
      </footer>
    </ElCard>

    <ElDrawer
      v-if="poolDrawerOpen"
      class="gateway-drawer"
      data-testid="gateway-pool-drawer"
      :model-value="true"
      :title="poolForm.id ? '编辑资源池' : '新增资源池'"
      size="min(460px, 100%)"
      :close-on-click-modal="false"
      :before-close="() => requestPoolClose()"
    >
      <ElForm ref="poolFormRef" :model="poolForm" :rules="poolRules" label-position="top" scroll-to-error :disabled="saving">
        <ElFormItem label="名称" prop="name">
          <ElInput v-model="poolForm.name" placeholder="例如 默认资源池" />
        </ElFormItem>
        <ElFormItem label="描述" prop="description">
          <ElInput v-model="poolForm.description" type="textarea" :rows="2" />
        </ElFormItem>
        <ElFormItem label="权重" prop="weight">
          <ElInput v-model="poolForm.weight" type="number" min="0" />
        </ElFormItem>
        <ElFormItem label="排序" prop="sort_order">
          <ElInput v-model="poolForm.sort_order" type="number" />
        </ElFormItem>
        <ElFormItem label="启用" prop="enabled">
          <ElSwitch v-model="poolForm.enabled" data-testid="gateway-pool-enabled" />
        </ElFormItem>
        <ElAlert v-if="poolError" type="error" show-icon :closable="false" :title="poolError" data-testid="gateway-pool-error" />
      </ElForm>
      <template #footer>
        <div class="gateway-drawer__footer">
          <ElTag v-if="poolDirty" type="warning" effect="light" data-testid="gateway-pool-dirty">有未保存修改</ElTag>
          <span class="gateway-drawer__spacer" />
          <ElButton :disabled="saving" @click="requestPoolClose">取消</ElButton>
          <ElButton type="primary" :loading="saving" data-testid="gateway-pool-save" @click="submitPool">保存</ElButton>
        </div>
      </template>
    </ElDrawer>

    <ElDrawer
      v-if="routeDrawerOpen"
      class="gateway-drawer"
      data-testid="gateway-route-drawer"
      :model-value="true"
      :title="routeForm.id ? '编辑路由' : '新增路由'"
      size="min(460px, 100%)"
      :close-on-click-modal="false"
      :before-close="() => requestRouteClose()"
    >
      <ElForm ref="routeFormRef" :model="routeForm" :rules="routeRules" label-position="top" scroll-to-error :disabled="saving">
        <ElFormItem label="模型名" prop="model">
          <ElInput v-model="routeForm.model" placeholder="例如 gpt-4o-mini" />
        </ElFormItem>
        <ElFormItem label="资源池" prop="pool_id">
          <ElSelect v-model="routeForm.pool_id" placeholder="选择资源池" data-testid="gateway-route-pool">
            <ElOption
              v-for="pool in pools"
              :key="pool.id"
              :value="pool.id"
              :label="`${pool.name}${pool.enabled ? '' : '（已禁用）'}`"
            />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="描述" prop="description">
          <ElInput v-model="routeForm.description" type="textarea" :rows="2" />
        </ElFormItem>
        <ElFormItem label="权重" prop="weight">
          <ElInput v-model="routeForm.weight" type="number" min="0" />
        </ElFormItem>
        <ElFormItem label="启用" prop="enabled">
          <ElSwitch v-model="routeForm.enabled" data-testid="gateway-route-enabled" />
        </ElFormItem>
        <ElAlert v-if="routeError" type="error" show-icon :closable="false" :title="routeError" data-testid="gateway-route-error" />
      </ElForm>
      <template #footer>
        <div class="gateway-drawer__footer">
          <ElTag v-if="routeDirty" type="warning" effect="light" data-testid="gateway-route-dirty">有未保存修改</ElTag>
          <span class="gateway-drawer__spacer" />
          <ElButton :disabled="saving" @click="requestRouteClose">取消</ElButton>
          <ElButton type="primary" :loading="saving" data-testid="gateway-route-save" @click="submitRoute">保存</ElButton>
        </div>
      </template>
    </ElDrawer>
  </section>
</template>

<script setup lang="ts">
import { Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDrawer,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElOption,
  ElPagination,
  ElSelect,
  ElSpace,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTag,
  ElText,
  ElTooltip,
  vLoading,
} from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import {
  gatewayApi,
  GatewayApiError,
  type GatewayPool,
  type GatewayRoute,
} from '@/api/gateway'
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
const busy = computed(() => loading.value || saving.value)

const poolDrawerOpen = ref(false)
const routeDrawerOpen = ref(false)
const poolFormRef = ref<FormInstance>()
const routeFormRef = ref<FormInstance>()
const poolError = ref('')
const routeError = ref('')

const poolForm = reactive({ id: '', name: '', description: '', weight: '1', sort_order: '0', enabled: true })
const routeForm = reactive({ id: '', model: '', pool_id: '', description: '', weight: '1', enabled: true })

const pageSize = 10

const poolFilters = reactive({ keyword: '', enabled: '' })
const routeFilters = reactive({ keyword: '', pool: '', enabled: '' })
const poolPage = ref(1)
const routePage = ref(1)

function matchesEnabled(enabled: boolean, filter: string): boolean {
  if (!filter) return true
  return filter === 'enabled' ? enabled : !enabled
}

const filteredPools = computed(() => {
  const keyword = poolFilters.keyword.trim().toLowerCase()
  return pools.value.filter((pool) => {
    if (keyword && !`${pool.name} ${pool.description}`.toLowerCase().includes(keyword)) return false
    return matchesEnabled(pool.enabled, poolFilters.enabled)
  })
})
const filteredRoutes = computed(() => {
  const keyword = routeFilters.keyword.trim().toLowerCase()
  return routes.value.filter((route) => {
    if (keyword && !`${route.model} ${route.description}`.toLowerCase().includes(keyword)) return false
    if (routeFilters.pool && route.pool_id !== routeFilters.pool) return false
    return matchesEnabled(route.enabled, routeFilters.enabled)
  })
})
const pagedPools = computed(() => {
  const start = (poolPage.value - 1) * pageSize
  return filteredPools.value.slice(start, start + pageSize)
})
const pagedRoutes = computed(() => {
  const start = (routePage.value - 1) * pageSize
  return filteredRoutes.value.slice(start, start + pageSize)
})
const poolHasFilters = computed(() => Boolean(poolFilters.keyword.trim() || poolFilters.enabled))
const routeHasFilters = computed(() => Boolean(routeFilters.keyword.trim() || routeFilters.pool || routeFilters.enabled))
const poolEmptyText = computed(() => (poolHasFilters.value ? '没有匹配的资源池，调整筛选条件后重试。' : '暂无资源池，点击「新增资源池」开始配置。'))
const routeEmptyText = computed(() => (routeHasFilters.value ? '没有匹配的路由，调整筛选条件后重试。' : '暂无模型路由，点击「新增路由」开始配置。'))

watch(poolFilters, () => { poolPage.value = 1 })
watch(routeFilters, () => { routePage.value = 1 })
watch(filteredPools, (list) => {
  const maxPage = Math.max(1, Math.ceil(list.length / pageSize))
  if (poolPage.value > maxPage) poolPage.value = maxPage
})
watch(filteredRoutes, (list) => {
  const maxPage = Math.max(1, Math.ceil(list.length / pageSize))
  if (routePage.value > maxPage) routePage.value = maxPage
})

function clearPoolFilters() {
  poolFilters.keyword = ''
  poolFilters.enabled = ''
}

function clearRouteFilters() {
  routeFilters.keyword = ''
  routeFilters.pool = ''
  routeFilters.enabled = ''
}

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

// ── 资源池：抽屉表单 + 未保存提醒 ──────────────────────────────────────

function poolSnapshot(): string {
  return JSON.stringify(poolForm)
}
const poolInitial = ref('')
const poolDirty = computed(() => poolDrawerOpen.value && poolSnapshot() !== poolInitial.value)

const poolRules: FormRules = {
  name: [{ required: true, message: '请填写资源池名称', trigger: 'blur' }],
}

function openPoolCreate() {
  Object.assign(poolForm, { id: '', name: '', description: '', weight: '1', sort_order: '0', enabled: true })
  poolError.value = ''
  poolInitial.value = poolSnapshot()
  poolDrawerOpen.value = true
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
  poolError.value = ''
  poolInitial.value = poolSnapshot()
  poolDrawerOpen.value = true
}

async function submitPool() {
  if (!(await poolFormRef.value?.validate().catch(() => false))) return
  saving.value = true
  poolError.value = ''
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
    poolDrawerOpen.value = false
    notify('资源池已保存')
    await load()
  } catch (reason) {
    poolError.value = errorMessage(reason, '保存资源池失败')
  } finally {
    saving.value = false
  }
}

async function requestPoolClose() {
  if (saving.value) return
  if (poolDirty.value) {
    const confirmed = await confirmDialog({
      title: '放弃未保存修改',
      message: '当前资源池配置尚未保存，确认放弃并关闭？',
      confirmLabel: '放弃并关闭',
      cancelLabel: '继续编辑',
      danger: true,
    })
    if (!confirmed) return
  }
  poolDrawerOpen.value = false
}

async function removePool(pool: GatewayPool) {
  const confirmed = await confirmDialog({
    title: '删除资源池',
    message: `确认删除「${pool.name}」？仍被节点或路由引用的资源池无法删除。`,
    confirmLabel: '删除',
    danger: true,
  })
  if (!confirmed) return
  try {
    await gatewayApi.deletePool(pool.id)
    notify('资源池已删除')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '删除失败'), 'error')
  }
}

// ── 模型路由：抽屉表单 + 模型名唯一 + 未保存提醒 ───────────────────────

function routeSnapshot(): string {
  return JSON.stringify(routeForm)
}
const routeInitial = ref('')
const routeDirty = computed(() => routeDrawerOpen.value && routeSnapshot() !== routeInitial.value)

const routeRules: FormRules = {
  model: [
    { required: true, message: '请填写模型名', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        const text = String(value ?? '').trim()
        if (text && routes.value.some((route) => route.model === text && route.id !== routeForm.id)) {
          return callback(new Error(`模型「${text}」已有路由，模型名必须唯一`))
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
  pool_id: [{ required: true, message: '请选择资源池', trigger: 'change' }],
}

function openRouteCreate() {
  Object.assign(routeForm, { id: '', model: '', pool_id: '', description: '', weight: '1', enabled: true })
  routeError.value = ''
  routeInitial.value = routeSnapshot()
  routeDrawerOpen.value = true
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
  routeError.value = ''
  routeInitial.value = routeSnapshot()
  routeDrawerOpen.value = true
}

async function submitRoute() {
  if (!(await routeFormRef.value?.validate().catch(() => false))) return
  saving.value = true
  routeError.value = ''
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
    routeDrawerOpen.value = false
    notify('路由已保存')
    await load()
  } catch (reason) {
    routeError.value = errorMessage(reason, '保存路由失败')
  } finally {
    saving.value = false
  }
}

async function requestRouteClose() {
  if (saving.value) return
  if (routeDirty.value) {
    const confirmed = await confirmDialog({
      title: '放弃未保存修改',
      message: '当前路由配置尚未保存，确认放弃并关闭？',
      confirmLabel: '放弃并关闭',
      cancelLabel: '继续编辑',
      danger: true,
    })
    if (!confirmed) return
  }
  routeDrawerOpen.value = false
}

async function removeRoute(route: GatewayRoute) {
  const confirmed = await confirmDialog({
    title: '删除路由',
    message: `确认删除模型「${route.model}」的路由？`,
    confirmLabel: '删除',
    danger: true,
  })
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
.gateway-pools-routes { display: grid; gap: 12px; }
.gateway-pools-routes__bar { display: flex; align-items: center; gap: 12px; }
.gateway-pools-routes__intro { margin-right: auto; }
.gateway-pools-routes__intro h3 { margin: 0; color: var(--astra-text-primary); }
.gateway-pools-routes__card-head { display: flex; align-items: center; gap: 12px; }
.gateway-pools-routes__card-title { display: grid; gap: 2px; margin-right: auto; }
.gateway-pools-routes__card-title h4 { margin: 0; color: var(--astra-text-primary); }
.gateway-pools-routes__filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 10px; }
.pool-filter__keyword { flex: 1 1 240px; min-width: 190px; max-width: 420px; }
.pool-filter__enabled { width: 120px; }
.route-filter__keyword { flex: 1 1 240px; min-width: 190px; max-width: 420px; }
.route-filter__pool { width: 152px; }
.route-filter__enabled { width: 120px; }
.gateway-pools-routes__footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 10px; }
.pool-cell { display: grid; gap: 2px; min-width: 0; }
.pool-cell strong { overflow: hidden; color: var(--astra-text-primary); font-size: var(--astra-font-label); text-overflow: ellipsis; white-space: nowrap; }
.pool-cell__desc { overflow: hidden; color: var(--astra-text-muted); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.gateway-drawer__footer { display: flex; align-items: center; gap: 10px; }
.gateway-drawer__spacer { flex: 1; }
</style>
