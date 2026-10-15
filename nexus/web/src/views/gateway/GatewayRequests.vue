<template>
  <section class="gateway-requests astra-stack" data-testid="gateway-requests">
    <GatewayHeaderActions>
      <ElButton :loading="loading" :icon="RefreshCw" data-testid="gateway-requests-refresh" @click="load">刷新</ElButton>
    </GatewayHeaderActions>

    <ElAlert v-if="error" type="error" show-icon :closable="false" :title="error" data-testid="gateway-requests-error">
      <ElButton type="primary" data-testid="gateway-requests-retry" @click="load">重试</ElButton>
    </ElAlert>

    <AstraFilterPanel label="调用日志筛选" testid="gateway-requests-filter">
      <ElSelect v-model="filters.model" class="astra-filter__select" data-testid="log-filter-model" aria-label="模型筛选" placeholder="模型：全部" clearable>
        <ElOption v-for="model in models" :key="model" :value="model" :label="model" />
      </ElSelect>
      <ElSelect v-model="filters.node_id" class="astra-filter__select" data-testid="log-filter-node" aria-label="节点筛选" placeholder="节点：全部" clearable>
        <ElOption v-for="node in nodes" :key="node.id" :value="node.id" :label="node.name" />
      </ElSelect>
      <ElSelect v-model="filters.key_id" class="astra-filter__select" data-testid="log-filter-key" aria-label="Key 筛选" placeholder="Key：全部" clearable>
        <ElOption v-for="key in keys" :key="key.id" :value="key.id" :label="key.name" />
      </ElSelect>
      <ElInput v-model="filters.status_code" class="log-filter__status" data-testid="log-filter-status-code" aria-label="状态码筛选" placeholder="状态码" type="number" />
      <ElInput
        v-model="filters.error_code"
        class="log-filter__error"
        data-testid="log-filter-error-code"
        aria-label="错误码筛选"
        placeholder="错误码，如 UPSTREAM_CONNECT_TIMEOUT"
        clearable
      />
      <ElSelect v-model="pageSize" class="log-filter__size" data-testid="log-filter-size" aria-label="每页条数">
        <ElOption v-for="size in pageSizeOptions" :key="size" :value="size" :label="`每页 ${size}`" />
      </ElSelect>
      <template #search>
        <ElInput
          v-model="filters.request_id"
          class="astra-filter__keyword"
          data-testid="log-filter-request"
          aria-label="Request ID 筛选"
          placeholder="Request ID 精确匹配"
          clearable
        />
        <ElButton type="primary" :icon="Filter" :disabled="loading" data-testid="gateway-requests-apply" @click="apply">筛选</ElButton>
        <ElButton :disabled="loading" data-testid="gateway-requests-reset" @click="reset">重置</ElButton>
      </template>
    </AstraFilterPanel>

    <section class="astra-table-panel">
    <ElTable
      v-loading="loading"
      :data="page.items"
      row-key="id"
      height="100%"
      element-loading-text="正在加载调用日志"
      data-testid="gateway-requests-table"
    >
      <ElTableColumn label="时间" width="116">
        <template #default="{ row }"><span class="log-num">{{ formatDateTime(row.started_at) }}</span></template>
      </ElTableColumn>
      <ElTableColumn label="Request ID" width="160">
        <template #default="{ row }"><span class="log-mono" :title="row.id">{{ shortId(row.id) }}</span></template>
      </ElTableColumn>
      <ElTableColumn label="Key / 模型" min-width="170">
        <template #default="{ row }">
          <div class="log-cell">
            <strong>{{ keyName(row.key_id) }}</strong>
            <span class="log-cell__sub">{{ row.model ?? '—' }}</span>
          </div>
        </template>
      </ElTableColumn>
      <ElTableColumn label="节点" width="130" show-overflow-tooltip>
        <template #default="{ row }">{{ nodeName(row.node_id) }}</template>
      </ElTableColumn>
      <ElTableColumn label="状态" min-width="170">
        <template #default="{ row }">
          <ElTag v-if="row.error_code" type="danger" :title="row.error_code">{{ row.error_code }}</ElTag>
          <ElTag v-else :type="row.status_code && row.status_code < 400 ? 'success' : 'warning'">{{ row.status_code ?? '—' }}</ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="流式" width="110">
        <template #default="{ row }">
          <span>{{ row.streaming ? 'SSE' : '普通' }}</span>
          <ElTag v-if="row.stream_interrupted" class="log-interrupted" type="danger" effect="plain">中断</ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="重试" width="68">
        <template #default="{ row }"><span class="log-num">{{ row.retry_count }}</span></template>
      </ElTableColumn>
      <ElTableColumn label="Token（入 / 出 / 总）" width="132">
        <template #default="{ row }"><span class="log-num">{{ tokenText(row as GatewayRequestLog) }}</span></template>
      </ElTableColumn>
      <ElTableColumn label="TTFB / TTFT" width="128">
        <template #default="{ row }"><span class="log-num">{{ latencyText(row.ttfb_ms) }} / {{ latencyText(row.ttft_ms) }}</span></template>
      </ElTableColumn>
      <ElTableColumn label="总时长" width="96">
        <template #default="{ row }"><span class="log-num">{{ latencyText(row.duration_ms) }}</span></template>
      </ElTableColumn>
      <ElTableColumn label="TPS" width="84">
        <template #default="{ row }"><span class="log-num">{{ row.output_tps !== null ? row.output_tps.toFixed(1) : '—' }}</span></template>
      </ElTableColumn>
      <template #empty>
        <ElEmpty v-if="!loading" :image-size="64" :description="emptyText" />
      </template>
    </ElTable>
    </section>

    <footer class="gateway-requests__footer">
      <ElText type="info" data-testid="gateway-requests-total">共 {{ page.total }} 条 · 第 {{ page.page }} 页</ElText>
      <ElPagination
        :current-page="page.page"
        :page-size="page.page_size"
        :total="page.total"
        layout="prev, pager, next"
        :disabled="loading"
        aria-label="调用日志分页"
        data-testid="gateway-requests-pagination"
        @current-change="go"
      />
    </footer>
  </section>
</template>

<script setup lang="ts">
import { Filter, RefreshCw } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElEmpty,
  ElInput,
  ElOption,
  ElPagination,
  ElSelect,
  ElSpace,
  ElTable,
  ElTableColumn,
  ElTag,
  ElText,
  vLoading,
} from 'element-plus'
import {
  gatewayApi,
  type GatewayKey,
  type GatewayNode,
  type GatewayRequestLog,
  type GatewayRequestPage,
  type GatewayRequestQuery,
} from '@/api/gateway'
import AstraFilterPanel from '@/components/astra/AstraFilterPanel.vue'
import GatewayHeaderActions from '@/views/gateway/GatewayHeaderActions.vue'
import { errorMessage, formatDateTime } from '@/utils/gateway'

const page = ref<GatewayRequestPage>({ items: [], total: 0, page: 1, page_size: 50 })
const nodes = ref<GatewayNode[]>([])
const keys = ref<GatewayKey[]>([])
const models = ref<string[]>([])
const loading = ref(false)
const error = ref('')
const pageSizeOptions = [50, 100, 200]
const pageSize = ref(50)
const filters = reactive({ request_id: '', model: '', node_id: '', key_id: '', status_code: '', error_code: '' })

const hasFilters = computed(() =>
  Boolean(filters.request_id.trim() || filters.model || filters.node_id || filters.key_id || filters.status_code.trim() || filters.error_code.trim()),
)
const emptyText = computed(() => (hasFilters.value
  ? '没有匹配的调用记录，调整筛选条件后重试。'
  : '暂无调用记录。'))

function shortId(value: string): string {
  return value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-6)}` : value
}
function keyName(id: string | null): string {
  if (!id) return '—'
  return keys.value.find((key) => key.id === id)?.name ?? id.slice(0, 12)
}
function nodeName(id: string | null): string {
  if (!id) return '—'
  return nodes.value.find((node) => node.id === id)?.name ?? id.slice(0, 12)
}
function tokenText(row: GatewayRequestLog): string {
  if (!row.usage_known) return 'unknown'
  return `${row.input_tokens ?? 0} / ${row.output_tokens ?? 0} / ${row.total_tokens ?? 0}`
}
function latencyText(value: number | null): string {
  return value === null || value === undefined ? '—' : `${value} ms`
}

function buildQuery(target: number): GatewayRequestQuery {
  return {
    page: target,
    page_size: pageSize.value,
    request_id: filters.request_id.trim() || undefined,
    model: filters.model || undefined,
    node_id: filters.node_id || undefined,
    key_id: filters.key_id || undefined,
    status_code: Number.isFinite(Number(filters.status_code)) && filters.status_code.trim() ? Number(filters.status_code) : undefined,
    error_code: filters.error_code.trim() || undefined,
  }
}

async function loadPage(target = page.value.page) {
  loading.value = true
  error.value = ''
  try {
    page.value = await gatewayApi.requests(buildQuery(target))
  } catch (reason) {
    error.value = errorMessage(reason, '调用日志加载失败')
  } finally {
    loading.value = false
  }
}

function load() { void loadPage(page.value.page) }
function apply() { void loadPage(1) }
function go(target: number) { void loadPage(target) }
function reset() {
  Object.assign(filters, { request_id: '', model: '', node_id: '', key_id: '', status_code: '', error_code: '' })
  void loadPage(1)
}

async function loadFilterOptions() {
  try {
    const [nodeList, keyList, routeList] = await Promise.all([gatewayApi.nodes(), gatewayApi.keys(), gatewayApi.routes()])
    nodes.value = nodeList
    keys.value = keyList
    models.value = routeList.map((route) => route.model)
  } catch {
    /* 过滤选项加载失败不影响日志本身 */
  }
}

onMounted(() => {
  void loadPage(1)
  void loadFilterOptions()
})
</script>

<style scoped>
.log-filter__status { flex: none; width: 104px; }
.log-filter__error { flex: none; width: 220px; }
.log-filter__size { flex: none; width: 116px; }
.gateway-requests__footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.log-cell { display: grid; gap: 2px; min-width: 0; }
.log-cell strong { overflow: hidden; color: var(--astra-text-primary); font-size: var(--astra-font-label); text-overflow: ellipsis; white-space: nowrap; }
.log-cell__sub { overflow: hidden; color: var(--astra-text-muted); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.log-mono { overflow: hidden; font-family: var(--astra-font-family); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.log-num { white-space: nowrap; font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.log-interrupted { margin-left: 6px; }
</style>
