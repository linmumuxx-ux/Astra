<template>
  <section class="gateway-section">
    <header class="gateway-section__head">
      <div><h3>调用日志</h3><p>只记录元数据与测量值，不保存 Prompt、Authorization 或响应体。</p></div>
      <button type="button" class="button" :disabled="loading" @click="load"><RefreshCw :size="14" :class="{ spin: loading }" />刷新</button>
    </header>

    <form class="gateway-filters" @submit.prevent="apply">
      <label>Request ID<input v-model="filters.request_id" placeholder="精确匹配" /></label>
      <label>模型
        <select v-model="filters.model"><option value="">全部</option><option v-for="model in models" :key="model" :value="model">{{ model }}</option></select>
      </label>
      <label>节点
        <select v-model="filters.node_id"><option value="">全部</option><option v-for="node in nodes" :key="node.id" :value="node.id">{{ node.name }}</option></select>
      </label>
      <label>Key
        <select v-model="filters.key_id"><option value="">全部</option><option v-for="key in keys" :key="key.id" :value="key.id">{{ key.name }}</option></select>
      </label>
      <label>状态码<input v-model="filters.status_code" type="number" placeholder="200" /></label>
      <label>错误码<input v-model="filters.error_code" placeholder="例如 UPSTREAM_CONNECT_TIMEOUT" /></label>
      <label>每页
        <select v-model.number="pageSize"><option :value="50">50</option><option :value="100">100</option><option :value="200">200</option></select>
      </label>
      <button type="submit" class="button button--primary" :disabled="loading"><Filter :size="14" />筛选</button>
      <button type="button" class="button" :disabled="loading" @click="reset">重置</button>
    </form>

    <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<button type="button" @click="load">重试</button></p>

    <div class="table-wrap gateway-card">
      <table class="gateway-log-table">
        <thead>
          <tr><th>时间</th><th>Request ID</th><th>Key / 模型</th><th>节点</th><th>状态</th><th>流式</th><th>重试</th><th>Token（入 / 出 / 总）</th><th>TTFB / TTFT</th><th>总时长</th><th>TPS</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in page.items" :key="row.id">
            <td class="gateway-time">{{ formatDateTime(row.started_at) }}</td>
            <td class="gateway-mono" :title="row.id">{{ shortId(row.id) }}</td>
            <td><strong>{{ keyName(row.key_id) }}</strong><small>{{ row.model ?? '—' }}</small></td>
            <td>{{ nodeName(row.node_id) }}</td>
            <td>
              <span v-if="row.error_code" class="status-badge" data-tone="danger" :title="row.error_code">{{ row.error_code }}</span>
              <span v-else class="status-badge" :data-tone="row.status_code && row.status_code < 400 ? 'success' : 'warning'">{{ row.status_code ?? '—' }}</span>
            </td>
            <td>{{ row.streaming ? 'SSE' : '普通' }}<span v-if="row.stream_interrupted" class="gateway-bad">中断</span></td>
            <td>{{ row.retry_count }}</td>
            <td class="gateway-num">{{ tokenText(row) }}</td>
            <td class="gateway-num">{{ latencyText(row.ttfb_ms) }} / {{ latencyText(row.ttft_ms) }}</td>
            <td class="gateway-num">{{ latencyText(row.duration_ms) }}</td>
            <td class="gateway-num">{{ row.output_tps !== null ? row.output_tps.toFixed(1) : '—' }}</td>
          </tr>
          <tr v-if="!page.items.length"><td colspan="11" class="empty-cell">{{ loading ? '加载中…' : '暂无调用记录。' }}</td></tr>
        </tbody>
      </table>
    </div>

    <footer class="gateway-pager">
      <span>共 {{ page.total }} 条 · 第 {{ page.page }} 页</span>
      <button type="button" class="button button--compact" :disabled="page.page <= 1 || loading" @click="go(page.page - 1)">上一页</button>
      <button type="button" class="button button--compact" :disabled="page.page * page.page_size >= page.total || loading" @click="go(page.page + 1)">下一页</button>
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
.gateway-filters input, .gateway-filters select { min-width: 130px; height: var(--astra-control-height-compact); padding: 0 9px; color: var(--astra-text-primary); border: 1px solid var(--astra-border); border-radius: 8px; background: var(--astra-bg-base); }
.gateway-card { border: 1px solid var(--astra-border); border-radius: 12px; background: var(--astra-bg-card); box-shadow: var(--astra-shadow-panel); }
.gateway-log-table { min-width: 1200px; }
.gateway-log-table td > strong { display: block; color: var(--astra-text-primary); font-size: var(--astra-font-helper); }
.gateway-log-table td > small { display: block; color: var(--astra-text-muted); font-size: var(--astra-font-micro); }
.gateway-mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
.gateway-num, .gateway-time { white-space: nowrap; font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.gateway-bad { margin-left: 5px; color: var(--astra-danger); font-size: var(--astra-font-micro); }
.gateway-pager { display: flex; align-items: center; justify-content: flex-end; gap: 9px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-pager > span { margin-right: auto; }
</style>