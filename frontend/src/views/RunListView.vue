<template>
  <div class="page run-list-page" data-testid="run-list-page">
    <section class="page-intro compact-intro">
      <div><h2>任务记录</h2><p>每一次执行都有一条记录，用于审计实际执行、耗时、消耗与异常。</p></div>
      <button class="button" @click="load"><RefreshCw :size="14" /> 刷新记录</button>
    </section>

    <section class="run-stats" aria-label="执行质量指标" :aria-busy="loading">
      <article class="run-stat">
        <small>执行次数</small>
        <button type="button" class="stat-action stat-value" @click="setLevel('')">{{ stats?.run_count ?? '—' }}</button>
        <span>关联 {{ stats?.task_count ?? '—' }} 个任务</span>
      </article>
      <article class="run-stat" data-tone="success">
        <small>成功率</small><strong>{{ stats?.success_rate == null ? '—' : `${stats.success_rate}%` }}</strong>
        <span><button type="button" class="stat-action" @click="setLevel('COMPLETED')">{{ stats?.completed_count ?? '—' }} 成功</button> / <button type="button" class="stat-action danger" @click="setLevel('FAILED')">{{ stats?.failed_count ?? '—' }} 异常结束</button></span>
      </article>
      <article class="run-stat">
        <small>平均执行时长</small><strong>{{ avgDuration }}</strong><span>按已结束执行统计</span>
      </article>
      <article class="run-stat">
        <small>Token 消耗</small><strong>{{ tokenTotal }}</strong><span>模型实际用量</span>
      </article>
    </section>
    <section class="run-secondary" aria-label="辅助统计">
      <button type="button" class="stat-action" @click="setLevel('FAILED')">异常结束 <b class="danger">{{ stats?.failed_count ?? '—' }}</b></button><span>·</span>
      <button type="button" class="stat-action" @click="filters.retry = 'true'">重试 <b>{{ stats?.retry_count ?? '—' }}</b></button><span>·</span>
      <button type="button" class="stat-action" @click="setLevel('WAITING_INPUT')">{{ runtimeStatusLabel('WAITING_INPUT') }} <b>{{ stats?.waiting_input_count ?? '—' }}</b></button><span>·</span>
      <span>关联任务 <b>{{ stats?.task_count ?? '—' }}</b></span>
    </section>

    <div class="filter-bar run-filters">
      <div class="search-box"><Search :size="14" /><input v-model="filters.query" placeholder="Run / 任务 / Session ID" aria-label="搜索运行记录" /></div>
      <select v-model="filters.category" aria-label="任务分类"><option value="">全部分类</option><option v-for="item in store.categories" :key="item.id" :value="item.id">{{ item.name }}</option></select>
      <select v-model="filters.employee" aria-label="数字员工"><option value="">全部员工</option><option v-for="item in store.employees" :key="item.id" :value="item.id">{{ employeeDisplayName(item.name) }}</option></select>
      <select v-model="filters.level" aria-label="运行状态"><option value="">全部状态</option><option v-for="item in levelOptions" :key="item" :value="item">{{ runtimeStatusLabel(item) }}</option></select>
      <select v-model="filters.retry" aria-label="是否重试"><option value="">全部 / 含重试</option><option value="true">仅重试执行</option><option value="false">仅首次执行</option></select>
      <input v-model="filters.dateFrom" class="date-filter" type="date" aria-label="开始日期" />
      <span class="range-sep">–</span>
      <input v-model="filters.dateTo" class="date-filter" type="date" aria-label="结束日期" />
      <button class="button button--ghost" type="button" @click="resetFilters"><RotateCcw :size="13" /> 重置</button>
    </div>

    <p v-if="error" role="alert">{{ error }} <button class="button" @click="load">重试加载</button></p>
    <p v-if="loading" role="status">正在加载运行记录…</p>
    <AstraPanel flush>
      <template #title><div class="table-title"><h2>运行列表</h2><span>{{ total }} 条</span></div></template>
      <div class="table-wrap">
        <table class="run-table">
          <thead><tr><th>Run</th><th>关联任务</th><th>数字员工</th><th>状态</th><th>开始时间</th><th>运行时长</th><th class="num">Token</th><th class="num">工具调用</th><th>执行会话</th></tr></thead>
          <tbody>
            <tr v-for="run in runs" :key="run.id" @click="openDetail(run)">
              <td class="run-id-cell"><IdDisplay :value="run.id" :to="`/runs/${run.id}`" :max-width="140" @click.stop /></td>
              <td class="task-cell">
                <RouterLink class="task-cell__title" :to="`/tasks/${run.task_id}`" @click.stop>{{ run.task_title }}</RouterLink>
                <div class="task-cell__meta"><IdDisplay :value="run.task_id" :max-width="120" :copyable="false" @click.stop /><span>第 {{ run.run_number }} 次执行</span></div>
              </td>
              <td class="employee-cell">{{ employeeName(run.employee_id) }}</td>
              <td class="status-cell"><RuntimeStatusBadge :projection="run" /></td>
              <td class="time-cell">{{ formatTime(run.started_at) }}</td>
              <td class="time-cell">{{ formatDuration(run.started_at, run.finished_at) }}</td>
              <td class="num-cell">{{ formatTokens(run.total_tokens) }}</td>
              <td class="num-cell">{{ run.tool_call_count ?? '—' }}</td>
              <td class="session-cell" :title="run.opencode_session_id ?? ''">
                <IdDisplay v-if="run.opencode_session_id" :value="run.opencode_session_id" :max-width="110" :copyable="false" />
                <span v-else>—</span>
              </td>
            </tr>
            <tr v-if="!runs.length && !loading && !error"><td colspan="9"><AstraEmptyState :icon="History" title="暂无运行记录" description="数字员工开始处理任务后会创建运行记录。"><button v-if="hasFilter" class="button button--ghost" type="button" @click="resetFilters">清除筛选</button></AstraEmptyState></td></tr>
          </tbody>
        </table>
      </div>
      <div class="run-pagination">
        <span>共 {{ total }} 条 · 第 {{ page }} / {{ pageCount }} 页</span>
        <select v-model.number="pageSize" aria-label="每页条数"><option :value="20">20 条 / 页</option><option :value="50">50 条 / 页</option><option :value="100">100 条 / 页</option></select>
        <button class="button" :disabled="loading || page <= 1" @click="page--">上一页</button>
        <button class="button" :disabled="loading || page >= pageCount" @click="page++">下一页</button>
      </div>
    </AstraPanel>

    <RunDetailDrawer
      v-if="detail"
      :run="detail.run"
      :usage="detail.usage"
      :events="detail.events"
      @close="detail = null"
    />
  </div>
</template>

<script setup lang="ts">
import { History, RefreshCw, RotateCcw, Search } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { AstraEvent, Run, RunUsage, RunPage, RunStats } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import IdDisplay from '@/components/astra/IdDisplay.vue'
import RunDetailDrawer from '@/components/runs/RunDetailDrawer.vue'
import RuntimeStatusBadge from '@/components/runtime/RuntimeStatusBadge.vue'
import { RUN_RUNTIME_FILTER_STATES, runtimeStatusLabel, type RuntimeState } from '@/features/runtime/status'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatDuration, formatTime, formatTokens } from '@/utils/format'

const store = useAstraStore()
const runs = ref<RunPage['items']>([])
const detail = ref<{ run: Run; usage: RunUsage | null; events: AstraEvent[] } | null>(null)

type RunFilterState = Extract<RuntimeState, 'QUEUED' | 'STARTING' | 'RUNNING' | 'WAITING_INPUT' | 'SUSPENDED' | 'COMPLETED' | 'FAILED' | 'TIMEOUT' | 'LOST' | 'CANCELLED'>

const filters = reactive({
  query: '',
  category: '',
  employee: '',
  level: '' as RunFilterState | '',
  retry: '',
  dateFrom: '',
  dateTo: '',
})

const levelOptions = RUN_RUNTIME_FILTER_STATES as RunFilterState[]
const stats = ref<RunStats | null>(null)
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref('')
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
let requestVersion = 0
const load = async () => {
  const version = ++requestVersion
  loading.value = true
  error.value = ''
  const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize.value) })
  const values = { q: filters.query.trim(), category: filters.category, employee: filters.employee, level: filters.level, retry: filters.retry, date_from: filters.dateFrom, date_to: filters.dateTo }
  Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value) })
  try {
    const result = await api.runPage(params)
    if (version !== requestVersion) return
    runs.value = result.items
    stats.value = result.stats
    total.value = result.total
    if (page.value > pageCount.value) page.value = pageCount.value
  } catch (cause) {
    if (version !== requestVersion) return
    runs.value = []
    stats.value = null
    total.value = 0
    error.value = cause instanceof Error ? cause.message : '运行记录加载失败'
  } finally {
    if (version === requestVersion) loading.value = false
  }
}
const tokenTotal = computed(() => stats.value?.total_tokens == null ? '—' : new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(stats.value.total_tokens))
const avgDuration = computed(() => {
  if (stats.value?.avg_duration_seconds == null) return '—'
  const seconds = Math.round(stats.value.avg_duration_seconds)
  const remainder = `${Math.floor(seconds / 60) % 60}分${String(seconds % 60).padStart(2, '0')}秒`
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)}小时${remainder}`
  return seconds < 60 ? `${seconds}秒` : remainder
})
watch([() => ({ ...filters }), pageSize], () => {
  if (page.value !== 1) page.value = 1
  else void load()
})
watch(page, load)

const hasFilter = computed(() => Boolean(filters.query || filters.category || filters.employee || filters.level || filters.retry || filters.dateFrom || filters.dateTo))

function setLevel(value: RunFilterState | '') { filters.level = value }
function resetFilters() { Object.assign(filters, { query: '', category: '', employee: '', level: '', retry: '', dateFrom: '', dateTo: '' }) }
const employeeName = (id: string) => employeeDisplayName(store.employees.find((item) => item.id === id)?.name ?? id)
async function openDetail(run: Run) {
  const [usage, events] = await Promise.all([api.runUsage(run.id).catch(() => null), api.runEvents(run.id).catch(() => [])])
  detail.value = { run, usage, events: events as AstraEvent[] }
}

onMounted(() => {
  void load()
  void Promise.all([api.employees(), api.categories()]).then(([employees, categories]) => {
    store.employees = employees
    store.categories = categories
  }).catch(() => { error.value = '员工与分类选项加载失败，请刷新页面' })
})
</script>

<style scoped>
.run-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); padding: 20px 0; border: 1px solid var(--astra-border); border-radius: 12px; background: var(--astra-bg-panel); }
.run-stat { display: grid; gap: 10px; padding: 0 24px; align-content: start; }
.run-stat + .run-stat { border-left: 1px solid var(--astra-border); }
.run-stat small, .run-stat > span { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.run-stat strong, .stat-value { font: var(--astra-weight-bold) var(--astra-font-kpi) var(--astra-font-display); letter-spacing: -.03em; color: var(--astra-text-primary); }
.run-stat[data-tone='success'] strong { color: var(--astra-success); }
.stat-action { width: fit-content; padding: 0; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.stat-action.stat-value { font: var(--astra-weight-bold) var(--astra-font-kpi) var(--astra-font-display); }
.stat-action:hover { color: var(--astra-primary); text-decoration: underline; text-underline-offset: 4px; }
.stat-action:focus-visible { outline: 2px solid var(--astra-success); outline-offset: 4px; border-radius: 2px; }
.danger { color: var(--astra-danger); }
.run-secondary { display: flex; align-items: center; gap: 14px; padding: 14px 4px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.run-secondary b { font-weight: 600; }
.run-pagination { display: flex; justify-content: flex-end; align-items: center; gap: 12px; padding: 14px 18px; border-top: 1px solid var(--astra-border); color: var(--astra-text-muted); }
.run-filters { flex-wrap: wrap; }
.run-filters select { min-width: 128px; }
.run-filters .date-filter { height: 38px; }
.range-sep { color: var(--astra-text-muted); }
.run-table { min-width: 1040px; }
.run-id-cell { font-family: var(--astra-font-family); }
.task-cell { min-width: 0; }
.task-cell__title { display: block; max-width: 280px; overflow: hidden; color: var(--astra-text-primary); font-weight: var(--astra-weight-bold); text-overflow: ellipsis; white-space: nowrap; }
.task-cell__title:hover { color: var(--astra-primary-bright); }
.task-cell__meta { display: flex; align-items: center; gap: 8px; margin-top: 3px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.task-cell__meta span { white-space: nowrap; }
.employee-cell, .status-cell, .time-cell, .session-cell { white-space: nowrap; }
.num, .num-cell { text-align: right; }
.num-cell { font-variant-numeric: tabular-nums; }
.time-cell { color: var(--astra-text-muted); }
@media (max-width: 900px) { .run-stats { grid-template-columns: repeat(2, 1fr); row-gap: 24px; } .run-stat:nth-child(3) { border-left: 0; } }
@media (max-width: 600px) { .run-secondary { flex-wrap: wrap; } }
</style>
