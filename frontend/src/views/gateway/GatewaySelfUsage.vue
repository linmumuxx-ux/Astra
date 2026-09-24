<template>
  <section class="gateway-section">
    <header class="gateway-section__head">
      <div><h3>Key 自助用量</h3><p>普通 Gateway Key 只能查看自身的日志与统计，凭据仅存当前会话。</p></div>
      <el-button v-if="selfKey" @click="clear"><LogOut :size="14" />退出用量</el-button>
    </header>

    <form v-if="!selfKey" class="gateway-self-form" @submit.prevent="connect">
      <label>Gateway Key（agw_ 开头）<el-input v-model="input" type="password" show-password autocomplete="off" placeholder="粘贴你自己的 Gateway Key" /></label>
      <el-button type="primary" native-type="submit" :loading="loading" :disabled="loading">查看用量</el-button>
    </form>

    <template v-else>
      <el-radio-group v-model="statsWindow" size="small" aria-label="统计窗口">
        <el-radio-button v-for="item in windows" :key="item.id" :value="item.id">{{ item.label }}</el-radio-button>
      </el-radio-group>

      <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<el-button type="danger" link @click="load">重试</el-button></p>

      <div class="metrics-grid gateway-metrics">
        <AstraMetricCard label="请求数" :value="stats?.requests ?? '—'" hint="窗口内你的调用总量" :icon="Activity" />
        <AstraMetricCard label="成功率" :value="formatPercent(stats?.success_rate)" tone="success" hint="2xx/3xx 且未被中断" :icon="CheckCircle2" />
        <AstraMetricCard label="总 Token" :value="stats ? formatTokens(stats.total_tokens) : '—'" hint="输入 + 输出" :icon="Coins" />
        <AstraMetricCard label="未知用量" :value="stats?.unknown_usage_requests ?? '—'" tone="warning" hint="下游未返回 usage" :icon="CircleHelp" />
        <AstraMetricCard label="当前并发" :value="stats?.active ?? '—'" hint="你正在进行的请求" :icon="Waves" />
        <AstraMetricCard label="窗口" :value="windowLabel" hint="自然小时 / 自然日" :icon="Clock" />
      </div>

      <AstraPanel title="Token 趋势" :subtitle="windowLabel">
        <GatewayTrendChart v-if="stats" :buckets="stats.trend" mode="tokens" />
        <div v-else class="gateway-placeholder">{{ loading ? '加载中…' : '暂无数据' }}</div>
      </AstraPanel>

      <AstraPanel :title="`调用记录 · ${page.total} 条`" flush>
        <el-table :data="page.items" stripe :loading="loading" empty-text="暂无调用记录。">
          <el-table-column label="时间" min-width="155"><template #default="{ row }">{{ formatDateTime(row.started_at) }}</template></el-table-column>
          <el-table-column label="模型" min-width="160"><template #default="{ row }">{{ row.model ?? '—' }}</template></el-table-column>
          <el-table-column label="节点" min-width="150"><template #default="{ row }"><span class="gateway-mono">{{ row.node_id ?? '—' }}</span></template></el-table-column>
          <el-table-column label="状态" min-width="150"><template #default="{ row }"><el-tag v-if="row.error_code" type="danger" effect="light" :title="row.error_code">{{ row.error_code }}</el-tag><el-tag v-else :type="row.status_code && row.status_code < 400 ? 'success' : 'warning'" effect="light">{{ row.status_code ?? '—' }}</el-tag></template></el-table-column>
          <el-table-column label="流式" width="90"><template #default="{ row }">{{ row.streaming ? 'SSE' : '普通' }}</template></el-table-column>
          <el-table-column label="Token（入 / 出 / 总）" min-width="170" align="right"><template #default="{ row }">{{ row.usage_known ? `${row.input_tokens ?? 0} / ${row.output_tokens ?? 0} / ${row.total_tokens ?? 0}` : 'unknown' }}</template></el-table-column>
          <el-table-column label="TTFT" width="100" align="right"><template #default="{ row }">{{ row.ttft_ms ?? '—' }} ms</template></el-table-column>
          <el-table-column label="总时长" width="110" align="right"><template #default="{ row }">{{ row.duration_ms ?? '—' }} ms</template></el-table-column>
        </el-table>
      </AstraPanel>
    </template>
  </section>
</template>

<script setup lang="ts">
import { Activity, CheckCircle2, CircleHelp, Clock, Coins, LogOut, TriangleAlert, Waves } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import {
  clearSelfKey,
  gatewayApi,
  getSelfKey,
  setSelfKey,
  type GatewayRequestPage,
  type GatewayScopeStats,
  type GatewayStatsWindow,
} from '@/api/gateway'
import AstraMetricCard from '@/components/astra/AstraMetricCard.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import { formatTokens } from '@/utils/format'
import { errorMessage, formatDateTime, formatPercent } from '@/utils/gateway'
import GatewayTrendChart from '@/views/gateway/GatewayTrendChart.vue'

const windows: Array<{ id: GatewayStatsWindow; label: string }> = [
  { id: 'hour', label: '本小时' },
  { id: 'today', label: '今日' },
  { id: '7d', label: '近 7 天' },
  { id: '30d', label: '近 30 天' },
]
const selfKey = ref(getSelfKey())
const input = ref('')
const statsWindow = ref<GatewayStatsWindow>('today')
const stats = ref<GatewayScopeStats | null>(null)
const page = ref<GatewayRequestPage>({ items: [], total: 0, page: 1, page_size: 50 })
const loading = ref(false)
const error = ref('')
const windowLabel = computed(() => windows.find((item) => item.id === statsWindow.value)?.label ?? '')

async function load() {
  if (!selfKey.value) return
  loading.value = true
  error.value = ''
  try {
    const [statsValue, pageValue] = await Promise.all([
      gatewayApi.selfStats(statsWindow.value),
      gatewayApi.selfRequests({ page: 1, page_size: 50 }),
    ])
    stats.value = statsValue
    page.value = pageValue
  } catch (reason) {
    stats.value = null
    page.value = { items: [], total: 0, page: 1, page_size: 50 }
    error.value = errorMessage(reason, '用量加载失败，请确认 Key 有效')
  } finally {
    loading.value = false
  }
}

function connect() {
  const value = input.value.trim()
  if (!value) return
  setSelfKey(value)
  selfKey.value = value
  input.value = ''
  void load()
}

function clear() {
  clearSelfKey()
  selfKey.value = ''
  stats.value = null
  error.value = ''
}

watch(statsWindow, () => { void load() })
onMounted(() => { void load() })
</script>

<style scoped>
.gateway-self-form { display: flex; align-items: end; gap: 10px; padding: 14px; border: 1px solid var(--astra-border); border-radius: 10px; background: var(--astra-bg-card); }
.gateway-self-form label { display: grid; flex: 1; gap: 6px; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.gateway-self-form input { min-height: var(--astra-control-height); padding: 0 11px; color: var(--astra-text-primary); border: 1px solid var(--astra-border); border-radius: 8px; background: var(--astra-bg-base); }
.gateway-metrics { grid-template-columns: repeat(6, minmax(0, 1fr)); margin-bottom: 0; }
.gateway-metrics :deep(.metric-card) { min-height: 118px; }
.gateway-mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
.gateway-num, .gateway-time { white-space: nowrap; font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.gateway-log-table { min-width: 900px; }
.gateway-placeholder { display: grid; place-items: center; height: 200px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-alert { display: flex; align-items: center; gap: 7px; margin: 0; padding: 10px 12px; color: var(--astra-danger); border: 1px solid rgba(228, 93, 106, .2); border-radius: 9px; background: var(--astra-danger-soft); font-size: var(--astra-font-helper); }
@media (max-width: 1280px) { .gateway-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 760px) { .gateway-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .gateway-self-form { flex-direction: column; align-items: stretch; } }
</style>