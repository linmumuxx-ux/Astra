<template>
  <div class="page run-list-page" data-testid="run-list-page">
    <section class="page-intro compact-intro">
      <div><h2>任务记录</h2><p>每一次执行都有一条记录，用于审计实际执行、耗时、消耗与异常。</p></div>
      <button class="button" @click="load"><RefreshCw :size="14" /> 刷新记录</button>
    </section>

    <section class="run-stats" aria-label="执行质量指标">
      <button type="button" class="run-stat" :class="{ active: levelFilter === '' }" data-tone="neutral" @click="setLevel('')">
        <div><small>执行次数</small><strong>{{ runs.length }}</strong></div>
        <span>共 {{ totalTasks }} 个任务产生</span>
      </button>
      <button type="button" class="run-stat" :class="{ active: levelFilter === 'COMPLETED' }" data-tone="success" @click="setLevel('COMPLETED')">
        <div><small>成功率</small><strong>{{ successRate }}<em>%</em></strong></div>
        <span>已完成 {{ completedCount }}</span>
      </button>
      <button type="button" class="run-stat" :class="{ active: levelFilter === 'FAILED' }" data-tone="danger" @click="setLevel('FAILED')">
        <div><small>失败次数</small><strong>{{ failedCount }}</strong></div>
        <span>含阻塞 / 超时 / 丢失</span>
      </button>
      <button type="button" class="run-stat" data-tone="info" @click="setLevel('')">
        <div><small>平均执行时长</small><strong>{{ avgDuration }}</strong></div>
        <span>每次有效执行</span>
      </button>
    </section>

    <section class="run-secondary">
      <article><small>Token</small><strong>{{ formatTokens(costStats.totalTokens) }}</strong><span>Agent 实际返回</span></article>
      <article><small>工具调用</small><strong>{{ costStats.toolCalls }}</strong><span>实际工具事件</span></article>
      <article><small>等待输入</small><strong>{{ waitingCount }}</strong><span>需要人工处理</span></article>
    </section>

    <div class="filter-bar run-filters">
      <div class="search-box"><Search :size="14" /><input v-model="filters.query" placeholder="Run / 任务 / Session ID" aria-label="搜索运行记录" /></div>
      <select v-model="filters.category" aria-label="任务分类"><option value="">全部分类</option><option v-for="item in store.categories" :key="item.id" :value="item.id">{{ item.name }}</option></select>
      <select v-model="filters.employee" aria-label="数字员工"><option value="">全部员工</option><option v-for="item in store.employees" :key="item.id" :value="item.id">{{ employeeDisplayName(item.name) }}</option></select>
      <select v-model="filters.level" aria-label="运行状态"><option value="">全部状态</option><option v-for="item in levelOptions" :key="item.id" :value="item.id">{{ item.label }}</option></select>
      <select v-model="filters.retry" aria-label="是否重试"><option value="">全部 / 含重试</option><option value="true">是否发生过重试</option><option value="false">仅首次执行</option></select>
      <input v-model="filters.dateFrom" class="date-filter" type="date" aria-label="开始日期" />
      <span class="range-sep">–</span>
      <input v-model="filters.dateTo" class="date-filter" type="date" aria-label="结束日期" />
      <button class="button button--ghost" type="button" @click="resetFilters"><RotateCcw :size="13" /> 重置</button>
    </div>

    <AstraPanel flush>
      <template #title><div class="table-title"><h2>运行列表</h2><span>{{ filtered.length }} 条</span></div></template>
      <div class="table-wrap">
        <table class="run-table">
          <thead><tr><th>Run</th><th>关联任务</th><th>数字员工</th><th>状态</th><th>开始时间</th><th>运行时长</th><th class="num">Token</th><th class="num">工具调用</th><th>执行会话</th></tr></thead>
          <tbody>
            <tr v-for="run in filtered" :key="run.id" @click="openDetail(run)">
              <td class="run-id-cell"><IdDisplay :value="run.id" :to="`/runs/${run.id}`" :max-width="140" @click.stop /></td>
              <td class="task-cell">
                <RouterLink class="task-cell__title" :to="`/tasks/${run.task_id}`" @click.stop>{{ taskTitle(run.task_id) }}</RouterLink>
                <div class="task-cell__meta"><IdDisplay :value="run.task_id" :max-width="120" :copyable="false" @click.stop /><span>第 {{ run.run_number }} 次执行</span></div>
              </td>
              <td class="employee-cell">{{ employeeName(run.employee_id) }}</td>
              <td class="status-cell"><RunStatusBadge :status="run.status" /></td>
              <td class="time-cell">{{ formatTime(run.started_at) }}</td>
              <td class="time-cell">{{ formatDuration(run.started_at, run.finished_at) }}</td>
              <td class="num-cell">{{ formatTokens(run.total_tokens) }}</td>
              <td class="num-cell">{{ run.tool_call_count ?? '—' }}</td>
              <td class="session-cell" :title="run.opencode_session_id ?? ''">
                <IdDisplay v-if="run.opencode_session_id" :value="run.opencode_session_id" :max-width="110" :copyable="false" />
                <span v-else>—</span>
              </td>
            </tr>
            <tr v-if="!filtered.length"><td colspan="9"><AstraEmptyState :icon="History" title="暂无运行记录" description="数字员工开始处理任务后会创建运行记录。"><button v-if="hasFilter" class="button button--ghost" type="button" @click="resetFilters">清除筛选</button></AstraEmptyState></td></tr>
          </tbody>
        </table>
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
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { AstraEvent, Run, RunUsage } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import IdDisplay from '@/components/astra/IdDisplay.vue'
import RunDetailDrawer from '@/components/runs/RunDetailDrawer.vue'
import RunStatusBadge from '@/components/runs/RunStatusBadge.vue'
import { runUnifiedStatus, type RunLevelStatus } from '@/features/runs/unifiedStatus'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatDuration, formatTime, formatTokens } from '@/utils/format'

const store = useAstraStore()
const runs = ref<Run[]>([])
const detail = ref<{ run: Run; usage: RunUsage | null; events: AstraEvent[] } | null>(null)

const filters = reactive({
  query: '',
  category: '',
  employee: '',
  level: '' as RunLevelStatus | '',
  retry: '',
  dateFrom: '',
  dateTo: '',
})

const levelOptions: Array<{ id: RunLevelStatus; label: string }> = [
  { id: 'WAITING', label: '等待执行' },
  { id: 'EXECUTING', label: '执行中' },
  { id: 'WAITING_INPUT', label: '等待输入' },
  { id: 'PAUSED', label: '已暂停' },
  { id: 'COMPLETED', label: '已完成' },
  { id: 'FAILED', label: '执行失败' },
  { id: 'CANCELLED', label: '已取消' },
]
const levelFilter = computed({
  get: () => filters.level,
  set: (value: RunLevelStatus | '') => { filters.level = value },
})

const load = async () => {
  runs.value = await api.runs()
  if (!store.tasks.length) await store.refresh()
}

const taskOf = (run: Run) => store.tasks.find((task) => task.id === run.task_id)
const taskTitle = (id: string) => store.tasks.find((task) => task.id === id)?.title ?? id
const totalTasks = computed(() => new Set(runs.value.map((run) => run.task_id)).size)
const completedCount = computed(() => runs.value.filter((run) => ['COMPLETED', 'PASSED'].includes(run.status)).length)
const failedCount = computed(() => runs.value.filter((run) => ['FAILED', 'BLOCKED', 'TIMEOUT', 'LOST'].includes(run.status)).length)
const waitingCount = computed(() => runs.value.filter((run) => run.status === 'WAITING_INPUT').length)
const successRate = computed(() => (runs.value.length ? Math.round((completedCount.value / runs.value.length) * 100) : 0))
const avgDuration = computed(() => {
  const timed = runs.value.filter((run) => run.started_at && run.finished_at)
  if (!timed.length) return '—'
  const total = timed.reduce((sum, run) => sum + (new Date(run.finished_at!).getTime() - new Date(run.started_at!).getTime()), 0)
  const avg = total / timed.length
  return formatDurationSeconds(Math.floor(avg / 1000))
})
const costStats = computed(() => ({
  totalTokens: runs.value.reduce((sum, run) => sum + (run.total_tokens ?? 0), 0) || null,
  toolCalls: runs.value.reduce((sum, run) => sum + (run.tool_call_count ?? 0), 0) || null,
}))

const hasFilter = computed(() => Boolean(filters.query || filters.category || filters.employee || filters.level || filters.retry || filters.dateFrom || filters.dateTo))

const filtered = computed(() => runs.value.filter((run) => {
  const query = filters.query.toLowerCase().trim()
  const task = taskOf(run)
  return (!query || `${run.id}${run.task_id}${run.opencode_session_id ?? ''}`.toLowerCase().includes(query))
    && (!filters.category || task?.category_id === filters.category)
    && (!filters.employee || run.employee_id === filters.employee)
    && (!filters.level || runUnifiedStatus(run.status).level === filters.level)
    && (!filters.retry || (filters.retry === 'true' ? Boolean(run.previous_run_id) : !run.previous_run_id))
    && (filterByDate(run))
}))

function filterByDate(run: Run): boolean {
  const time = run.created_at?.slice(0, 10)
  if (!time) return !filters.dateFrom && !filters.dateTo
  return (!filters.dateFrom || time >= filters.dateFrom) && (!filters.dateTo || time <= filters.dateTo)
}

function setLevel(value: RunLevelStatus | '') { filters.level = value }
function resetFilters() { Object.assign(filters, { query: '', category: '', employee: '', level: '', retry: '', dateFrom: '', dateTo: '' }) }
function formatDurationSeconds(seconds: number) {
  const minutes = Math.floor(seconds / 60)
  if (minutes < 1) return '不足 1 分钟'
  if (minutes < 60) return `${minutes} 分钟`
  const remaining = minutes % 60
  return `${Math.floor(minutes / 60)} 小时${remaining ? ` ${remaining} 分钟` : ''}`
}
const employeeName = (id: string) => employeeDisplayName(store.employees.find((item) => item.id === id)?.name ?? id)
async function openDetail(run: Run) {
  const [usage, events] = await Promise.all([api.runUsage(run.id).catch(() => null), api.runEvents(run.id).catch(() => [])])
  detail.value = { run, usage, events: events as AstraEvent[] }
}

onMounted(load)
</script>

<style scoped>
.run-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; margin-bottom: 9px; }
.run-stat { display: grid; gap: 8px; padding: 13px 15px; border: 1px solid var(--astra-border); border-radius: 10px; background: var(--astra-bg-panel); text-align: left; cursor: pointer; transition: .14s ease; }
.run-stat:hover { border-color: var(--astra-border-hover); transform: translateY(-1px); }
.run-stat.active { border-color: var(--astra-primary-border); background: var(--astra-primary-soft); box-shadow: inset 0 0 0 1px var(--astra-primary-border); }
.run-stat > div { display: flex; align-items: baseline; gap: 6px; }
.run-stat small { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.run-stat strong { font: 650 var(--astra-font-kpi) var(--astra-font-display); letter-spacing: -.03em; }
.run-stat > div em { font-style: normal; color: var(--astra-text-muted); font-size: var(--astra-font-label); }
.run-stat > span { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.run-stat[data-tone='success'] strong { color: var(--astra-success); }
.run-stat[data-tone='danger'] strong { color: var(--astra-danger); }
.run-secondary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; margin-bottom: 12px; }
.run-secondary article { display: grid; padding: 10px 13px; border: 1px solid var(--astra-border); border-radius: 9px; background: var(--astra-bg-panel); }
.run-secondary small, .run-secondary span { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.run-secondary strong { margin: 2px 0; font: 620 18px var(--astra-font-display); }
.run-filters { flex-wrap: wrap; }
.run-filters select { min-width: 128px; }
.run-filters .date-filter { height: 38px; }
.range-sep { color: var(--astra-text-muted); }
.run-table { min-width: 1040px; }
.run-id-cell { font-family: ui-monospace, monospace; }
.task-cell { min-width: 0; }
.task-cell__title { display: block; max-width: 280px; overflow: hidden; color: var(--astra-text-primary); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.task-cell__title:hover { color: var(--astra-primary-bright); }
.task-cell__meta { display: flex; align-items: center; gap: 8px; margin-top: 3px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.task-cell__meta span { white-space: nowrap; }
.employee-cell, .status-cell, .time-cell, .session-cell { white-space: nowrap; }
.num, .num-cell { text-align: right; }
.num-cell { font-variant-numeric: tabular-nums; }
.time-cell { color: var(--astra-text-muted); }
@media (max-width: 900px) { .run-stats { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .run-stats, .run-secondary { grid-template-columns: 1fr 1fr; } }
</style>
