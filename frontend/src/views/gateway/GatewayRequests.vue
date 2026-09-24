<template>
  <section class="gateway-section">
    <header class="gateway-section__head">
      <div><h3>调用日志</h3><p>只记录元数据与测量值，不保存 Prompt、Authorization 或响应体。</p></div>
      <el-button :loading="loading" :disabled="loading" @click="load"><RefreshCw v-if="!loading" :size="14" />刷新</el-button>
    </header>

    <form class="gateway-filters" @submit.prevent="apply">
      <label>Request ID<el-input v-model="filters.request_id" placeholder="精确匹配" /></label>
      <label>模型<el-select v-model="filters.model"><el-option label="全部" value="" /><el-option v-for="model in models" :key="model" :label="model" :value="model" /></el-select></label>
      <label>节点<el-select v-model="filters.node_id"><el-option label="全部" value="" /><el-option v-for="node in nodes" :key="node.id" :label="node.name" :value="node.id" /></el-select></label>
      <label>Key<el-select v-model="filters.key_id"><el-option label="全部" value="" /><el-option v-for="key in keys" :key="key.id" :label="key.name" :value="key.id" /></el-select></label>
      <label>状态码<el-input v-model="filters.status_code" type="number" placeholder="200" /></label>
      <label>错误码<el-input v-model="filters.error_code" placeholder="例如 UPSTREAM_CONNECT_TIMEOUT" /></label>
      <label>每页<el-select v-model="pageSize"><el-option :value="50" label="50" /><el-option :value="100" label="100" /><el-option :value="200" label="200" /></el-select></label>
      <el-button type="primary" native-type="submit" :loading="loading" :disabled="loading"><Filter v-if="!loading" :size="14" />筛选</el-button>
      <el-button :disabled="loading" @click="reset">重置</el-button>
    </form>

    <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<el-button type="danger" link @click="load">重试</el-button></p>

    <div class="gateway-card">
      <el-table :data="page.items" stripe :loading="loading" empty-text="暂无调用记录。">
        <el-table-column label="时间" min-width="155"><template #default="{ row }">{{ formatDateTime(row.started_at) }}</template></el-table-column>
        <el-table-column label="Request ID" min-width="150"><template #default="{ row }"><span class="gateway-mono" :title="row.id">{{ shortId(row.id) }}</span></template></el-table-column>
        <el-table-column label="Key / 模型" min-width="170"><template #default="{ row }"><strong>{{ keyName(row.key_id) }}</strong><small>{{ row.model ?? '—' }}</small></template></el-table-column>
        <el-table-column label="节点" min-width="140"><template #default="{ row }">{{ nodeName(row.node_id) }}</template></el-table-column>
        <el-table-column label="状态" min-width="150"><template #default="{ row }"><el-tag v-if="row.error_code" type="danger" effect="light" :title="row.error_code">{{ row.error_code }}</el-tag><el-tag v-else :type="row.status_code && row.status_code < 400 ? 'success' : 'warning'" effect="light">{{ row.status_code ?? '—' }}</el-tag></template></el-table-column>
        <el-table-column label="流式" width="100"><template #default="{ row }">{{ row.streaming ? 'SSE' : '普通' }}<span v-if="row.stream_interrupted" class="gateway-bad">中断</span></template></el-table-column>
        <el-table-column prop="retry_count" label="重试" width="75" />
        <el-table-column label="Token（入 / 出 / 总）" min-width="160" align="right"><template #default="{ row }">{{ tokenText(row) }}</template></el-table-column>
        <el-table-column label="TTFB / TTFT" min-width="140" align="right"><template #default="{ row }">{{ latencyText(row.ttfb_ms) }} / {{ latencyText(row.ttft_ms) }}</template></el-table-column>
        <el-table-column label="总时长" min-width="110" align="right"><template #default="{ row }">{{ latencyText(row.duration_ms) }}</template></el-table-column>
        <el-table-column label="TPS" width="90" align="right"><template #default="{ row }">{{ row.output_tps !== null ? row.output_tps.toFixed(1) : '—' }}</template></el-table-column>
      </el-table>
    </div>

    <footer class="gateway-pager">
      <span>共 {{ page.total }} 条 · 第 {{ page.page }} 页</span>
      <el-button :disabled="page.page <= 1 || loading" @click="go(page.page - 1)">上一页</el-button>
      <el-button :disabled="page.page * page.page_size >= page.total || loading" @click="go(page.page + 1)">下一页</el-button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { Filter, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import { onMounted, reactive, ref } from 'vue'
import {
  gatewayApi,
  GatewayApiError,
  type GatewayKey,
  type GatewayNode,
  type GatewayRequestPage,
  type GatewayRequestQuery,
} from '@/api/gateway'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import { errorMessage, formatDateTime } from '@/utils/gateway'

const { disconnect } = useGatewayAuth()
const page = ref<GatewayRequestPage>({ items: [], total: 0, page: 1, page_size: 50 })
const nodes = ref<GatewayNode[]>([])
const keys = ref<GatewayKey[]>([])
const models = ref<string[]>([])
const loading = ref(false)
const error = ref('')
const pageSize = ref(50)
const filters = reactive({ request_id: '', model: '', node_id: '', key_id: '', status_code: '', error_code: '' })

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
function tokenText(row: GatewayRequestPage['items'][number]): string {
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
    if (reason instanceof GatewayApiError && reason.status === 401) { disconnect(); return }
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

onMounted(async () => {
  await loadPage(1)
  try {
    const [nodeList, keyList, routeList] = await Promise.all([gatewayApi.nodes(), gatewayApi.keys(), gatewayApi.routes()])
    nodes.value = nodeList
    keys.value = keyList
    models.value = routeList.map((route) => route.model)
  } catch {
    /* 过滤选项加载失败不影响日志本身 */
  }
})
</script>

<style scoped>
.gateway-filters { display: flex; flex-wrap: wrap; align-items: end; gap: 10px; padding: 12px; border: 1px solid var(--astra-border); border-radius: 10px; background: var(--astra-bg-card); }
.gateway-filters label { display: grid; gap: 5px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-filters :deep(.el-input), .gateway-filters :deep(.el-select) { min-width:130px;width:150px }
.gateway-card { border: 1px solid var(--astra-border); border-radius: 12px; background: var(--astra-bg-card); box-shadow: var(--astra-shadow-panel); }
:deep(.el-table strong){display:block;color:var(--astra-text-primary);font-size:var(--astra-font-helper)}
:deep(.el-table small){display:block;color:var(--astra-text-muted);font-size:var(--astra-font-micro)}
.gateway-mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
.gateway-num, .gateway-time { white-space: nowrap; font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.gateway-bad { margin-left: 5px; color: var(--astra-danger); font-size: var(--astra-font-micro); }
.gateway-pager { display: flex; align-items: center; justify-content: flex-end; gap: 9px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-pager > span { margin-right: auto; }
</style>