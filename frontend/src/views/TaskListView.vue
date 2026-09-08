<template>
  <div class="page task-list-page" data-testid="task-list-page">
    <section class="task-head">
      <div><h2>任务管理</h2><p>现在有哪些任务，哪些正在正常运行，哪些需要人工处理。</p></div>
      <button class="button button--primary" @click="dialogOpen = true"><Plus :size="15" /> 创建任务</button>
    </section>

    <nav class="task-tabs" aria-label="任务状态筛选">
      <button type="button" :class="{ active: filters.status === '' }" @click="setStatus('')">全部 <b>{{ counts.all }}</b></button>
      <button type="button" :class="{ active: filters.status === 'READY' }" @click="setStatus('READY')">待领取 <b>{{ counts.ready }}</b></button>
      <button type="button" :class="{ active: filters.status === 'ASSIGNED' }" @click="setStatus('ASSIGNED')">待启动 <b>{{ counts.assigned }}</b></button>
      <button type="button" :class="{ active: filters.status === 'QUEUED' }" @click="setStatus('QUEUED')">排队中 <b>{{ counts.queued }}</b></button>
      <button type="button" :class="{ active: filters.status === 'RUNNING' }" @click="setStatus('RUNNING')">执行中 <b>{{ counts.running }}</b></button>
      <button type="button" :class="{ active: filters.status === 'WAIT_HUMAN' }" @click="setStatus('WAIT_HUMAN')">等待人工 <b>{{ counts.waitHuman }}</b></button>
      <button type="button" :class="{ active: filters.status === 'PENDING_CONFIRMATION' }" @click="setStatus('PENDING_CONFIRMATION')">待确认 <b>{{ counts.pending }}</b></button>
      <button type="button" :class="{ active: filters.status === 'ABNORMAL' }" @click="setStatus('ABNORMAL')">异常 <b>{{ counts.abnormal }}</b></button>
      <button type="button" :class="{ active: filters.status === 'COMPLETED' }" @click="setStatus('COMPLETED')">已完成 <b>{{ counts.completed }}</b></button>
    </nav>

    <div class="filter-bar task-filters">
      <div class="search-box"><Search :size="15" /><input v-model="filters.query" placeholder="搜索任务 ID 或标题" aria-label="搜索任务" /></div>
      <select v-model="filters.type" aria-label="类型"><option value="">全部类型</option><option value="ISSUE">问题</option><option value="REQUIREMENT">需求</option></select>
      <select v-model="filters.category" aria-label="分类"><option value="">全部分类</option><option v-for="item in store.categories" :key="item.id" :value="item.id">{{ item.name }}</option></select>
      <select v-model="filters.status" aria-label="状态"><option value="">全部状态</option><option value="ABNORMAL">异常（失败/异常）</option><option v-for="item in statuses" :key="item" :value="item">{{ statusLabel(item) }}</option></select>
      <select v-model="filters.employee" aria-label="执行员工"><option value="">全部员工</option><option v-for="item in store.employees" :key="item.id" :value="item.id">{{ employeeDisplayName(item.name) }}</option></select>
      <button class="button button--ghost" type="button" @click="showMore = !showMore"><SlidersHorizontal :size="14" /> 更多筛选 <ChevronDown :size="14" :class="{ rot: showMore }" /></button>
      <button class="button button--ghost" type="button" @click="resetFilters"><RotateCcw :size="14" /> 重置</button>
    </div>

    <div v-if="showMore" class="filter-bar task-filters task-filters--more">
      <select v-model="filters.priority" aria-label="优先级"><option value="">全部优先级</option><option v-for="item in priorities" :key="item" :value="item">{{ priorityLabel(item) }}</option></select>
      <select v-model="filters.timeType" aria-label="时间类型"><option value="updated">按更新时间</option><option value="created">按创建时间</option></select>
      <input v-model="filters.dateFrom" class="date-filter" type="date" aria-label="开始日期" />
      <span class="range-sep">–</span>
      <input v-model="filters.dateTo" class="date-filter" type="date" aria-label="结束日期" />
    </div>

    <AstraPanel flush class="task-table-panel">
      <template #title><div class="table-title"><h2>任务列表</h2><span>{{ total }} 项</span></div></template>
      <div class="table-wrap task-table-wrap">
        <table class="task-workbench-table">
          <thead><tr><th>任务</th><th>分类 / 类型</th><th>状态</th><th>执行员工</th><th>当前进展</th><th>更新时间</th><th>操作</th></tr></thead>
          <tbody>
            <template v-if="isInitialLoading">
              <tr v-for="index in 8" :key="index" class="task-row--loading"><td colspan="7"><span /></td></tr>
            </template>
            <template v-else>
              <tr v-for="task in paged" :key="task.id" class="task-row" @click="openTask(task.id)">
              <td class="task-cell">
                <div class="task-cell__title"><span v-if="isHigh(task.priority)" class="task-priority" :data-p="task.priority">{{ priorityLabel(task.priority) }}</span><strong :title="task.title">{{ task.title }}</strong></div>
                <div class="task-cell__meta"><span>{{ task.id }}</span><em :title="taskTypeLabel(task.task_type)">{{ taskTypeLabel(task.task_type) }}</em><em v-if="isTerminal(task.status)">已完成</em></div>
              </td>
              <td class="type-cell"><span :title="typeCopy(task)">{{ typeCopy(task) }}</span></td>
              <td class="status-cell"><AstraStatusBadge :status="task.runtime_state" :label="task.runtime_status_label" :pulse="task.status === 'RUNNING'" /></td>
              <td class="employee-cell"><span :title="employeeName(task.employee_id)">{{ employeeName(task.employee_id) }}</span></td>
              <td class="progress-cell"><span :title="progressCopy(task)">{{ progressCopy(task) }}</span></td>
              <td class="time-cell"><time :title="formatTime(task.updated_at)">{{ formatTime(task.updated_at) }}</time></td>
              <td class="actions-cell" @click.stop>
                <div class="actions-wrap">
                  <button class="task-primary-btn" :data-kind="primaryAction(task).kind" type="button" @click="onPrimary(task)">{{ primaryAction(task).label }}</button>
                  <div class="menu-wrap">
                    <button class="task-menu-btn" type="button" aria-label="更多操作" @click="toggleMenu(task.id)"><MoreHorizontal :size="17" /></button>
                    <div v-if="openMenu === task.id" class="task-menu">
                      <button v-for="item in menuItems(task)" :key="item.label" type="button" :class="{ danger: item.danger }" @click="onMenu(item, task)">{{ item.label }}</button>
                    </div>
                  </div>
                </div>
              </td>
            </tr>
              <tr v-if="!paged.length"><td colspan="7"><AstraEmptyState :icon="SearchX" title="暂无符合条件的任务" description="当前筛选条件下没有找到任务。"><button class="button button--ghost" type="button" @click="resetFilters">清除筛选</button></AstraEmptyState></td></tr>
            </template>
          </tbody>
        </table>
      </div>
      <footer class="task-table__foot">
        <span class="foot-total">共 {{ total }} 条</span>
        <div class="foot-right">
          <label class="page-size">每页<select v-model.number="pageSize"><option :value="20">20 条</option><option :value="50">50 条</option><option :value="100">100 条</option></select></label>
          <nav class="task-page-nav" aria-label="分页">
            <button type="button" :disabled="currentPage <= 1" @click="currentPage -= 1"><ChevronLeft :size="15" /></button>
            <template v-for="page in pageWindow" :key="page">
              <button type="button" :class="{ active: Number(page) === currentPage }" :disabled="page === '…'" @click="goPage(Number(page))">{{ page }}</button>
            </template>
            <button type="button" :disabled="currentPage >= pageCount" @click="currentPage += 1"><ChevronRight :size="15" /></button>
          </nav>
        </div>
      </footer>
    </AstraPanel>

    <div v-if="dialogOpen" class="modal-backdrop" data-testid="task-create-modal" @click.self="dialogOpen = false">
      <form class="modal-card task-create-card" @submit.prevent="createTask">
        <header><div><h3>创建任务</h3><p>定义目标和验收标准，执行方式由数字员工决定。</p></div><button type="button" aria-label="关闭创建任务" @click="dialogOpen = false"><X :size="17" /></button></header>
        <section class="form-section"><h4>基本信息</h4><label>任务标题 *<input v-model.trim="form.title" required placeholder="例如：修复用户登录接口偶发 500 问题" /></label><div class="form-grid"><label>任务类型 *<select v-model="form.task_type" required><option value="ISSUE">问题</option><option value="REQUIREMENT">需求</option></select></label><label>任务分类 *<select v-model="form.category_id" required><option value="" disabled>请选择</option><option v-for="item in store.categories" :key="item.id" :value="item.id">{{ item.name }}</option></select></label></div><div class="form-grid"><label>优先级 *<select v-model="form.priority"><option v-for="item in priorities" :key="item" :value="item">{{ priorityLabel(item) }}：{{ priorityHint(item) }}</option></select></label><FormField label="完成策略" help="很高/高优先级默认人工确认。" v-slot="{ id }"><select :id="id" v-model="form.completion_policy"><option value="AUTO">员工提交后自动完成</option><option value="MANUAL_CONFIRM">需人工确认</option></select></FormField></div></section>
        <section class="form-section"><h4>任务内容</h4><label>任务描述 *<textarea v-model.trim="form.description" required rows="5" placeholder="说明背景、当前情况、需要实现的能力和必要限制" /></label><label>附件<input type="file" multiple @change="selectFiles" /><small v-if="attachments.length">已选择 {{ attachments.map((item) => item.name).join('、') }}</small></label></section>
        <section class="form-section"><h4>验收标准</h4><div class="criteria-editor"><div v-for="(item, index) in criteria" :key="item.key"><span>{{ index + 1 }}</span><input v-model.trim="item.content" required :placeholder="`验收标准 ${index + 1}`" /><button type="button" title="上移" :disabled="index === 0" @click="moveCriterion(index, -1)"><ArrowUp :size="14" /></button><button type="button" title="下移" :disabled="index === criteria.length - 1" @click="moveCriterion(index, 1)"><ArrowDown :size="14" /></button><button type="button" title="删除" :disabled="criteria.length === 1" @click="criteria.splice(index, 1)"><Trash2 :size="14" /></button></div></div><button type="button" class="button button--ghost" @click="addCriterion"><Plus :size="14" /> 添加验收标准</button></section>
        <section class="form-section"><h4>执行员工</h4><FormField label="分配方式" help="自动分配会综合员工启用状态、空闲状态、任务类型和任务分类。" v-slot="{ id }"><select :id="id" v-model="form.employee_id"><option value="">自动分配</option><option v-for="item in compatibleEmployees" :key="item.id" :value="item.id">{{ employeeDisplayName(item.name) }} · {{ item.role }}</option></select></FormField></section>
        <div v-if="createError" class="form-message" data-error="true">{{ createError }}</div>
        <footer><button type="button" class="button" @click="dialogOpen = false">取消</button><button class="button button--primary" :disabled="submitting"><LoaderCircle v-if="submitting" :size="14" class="spin" /> 创建任务</button></footer>
      </form>
    </div>

    <div v-if="pending" class="modal-backdrop" data-testid="task-action-confirm" @click.self="pending = null">
      <div class="modal-card confirm-action-card">
        <header><div><h3>{{ pending.label }}</h3><p>确认对「{{ shortTitle(pending.task.title) }}」执行该操作？</p></div><button type="button" aria-label="关闭确认" @click="pending = null"><X :size="17" /></button></header>
        <footer><button type="button" class="button" @click="pending = null">取消</button><button class="button button--primary" :disabled="acting" @click="runPendingAction"><LoaderCircle v-if="acting" :size="14" class="spin" /> 确认{{ pending.label }}</button></footer>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import FormField from '@/components/forms/FormField.vue'
import { ArrowDown, ArrowUp, ChevronDown, ChevronLeft, ChevronRight, LoaderCircle, MoreHorizontal, Plus, RotateCcw, Search, SearchX, SlidersHorizontal, Trash2, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Task, TaskPriority, TaskStatus } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatTime, platformCopy, priorityLabel, safeUUID, statusLabel, taskTypeLabel } from '@/utils/format'

const store = useAstraStore()
const route = useRoute()
const router = useRouter()
const dialogOpen = ref(false)
const submitting = ref(false)
const createError = ref('')
const showMore = ref(false)
const pageSize = ref(20)
const currentPage = ref(1)
const openMenu = ref<string | null>(null)
const pending = ref<{ task: Task; name: string; label: string } | null>(null)
const acting = ref(false)

const statuses: TaskStatus[] = ['READY', 'ASSIGNED', 'QUEUED', 'RUNNING', 'WAIT_HUMAN', 'SUSPENDED', 'PENDING_CONFIRMATION', 'COMPLETED', 'FAILED', 'EXECUTION_ERROR', 'CANCELLED']
const priorities: TaskPriority[] = ['VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW']
const terminalStatuses: TaskStatus[] = ['COMPLETED', 'FAILED', 'CANCELLED']
const abnormalStatuses: TaskStatus[] = ['FAILED', 'EXECUTION_ERROR']

const filters = reactive({
  query: typeof route.query.q === 'string' ? route.query.q : '',
  type: '',
  category: '',
  priority: '',
  status: typeof route.query.status === 'string' ? route.query.status : '',
  employee: typeof route.query.employee === 'string' ? route.query.employee : '',
  timeType: 'updated' as 'updated' | 'created',
  dateFrom: '',
  dateTo: '',
})
const form = reactive({ title: '', task_type: 'ISSUE' as 'ISSUE' | 'REQUIREMENT', category_id: '', priority: 'MEDIUM' as TaskPriority, completion_policy: 'AUTO' as 'AUTO' | 'MANUAL_CONFIRM', description: '', employee_id: '' })
const criteria = ref([{ key: safeUUID(), content: '' }])
const attachments = ref<Array<{ name: string; size: number; content_type: string; content: string }>>([])
const isInitialLoading = computed(() => store.loading && !store.tasks.length)

watch(() => filters, () => { currentPage.value = 1 }, { deep: true })
watch(() => form.priority, (priority) => { form.completion_policy = ['VERY_HIGH', 'HIGH'].includes(priority) ? 'MANUAL_CONFIRM' : 'AUTO' })

onMounted(async () => {
  await store.refresh()
  form.category_id = store.categories[0]?.id ?? ''
  document.addEventListener('click', closeMenu)
})
onBeforeUnmount(() => document.removeEventListener('click', closeMenu))

function closeMenu() { openMenu.value = null }
function toggleMenu(id: string) { openMenu.value = openMenu.value === id ? null : id }

const counts = computed(() => ({
  all: store.tasks.length,
  ready: store.tasks.filter((task) => task.status === 'READY').length,
  assigned: store.tasks.filter((task) => task.status === 'ASSIGNED').length,
  queued: store.tasks.filter((task) => task.status === 'QUEUED').length,
  running: store.tasks.filter((task) => task.status === 'RUNNING').length,
  waitHuman: store.tasks.filter((task) => task.status === 'WAIT_HUMAN').length,
  pending: store.tasks.filter((task) => task.status === 'PENDING_CONFIRMATION').length,
  abnormal: store.tasks.filter((task) => abnormalStatuses.includes(task.status)).length,
  completed: store.tasks.filter((task) => task.status === 'COMPLETED').length,
}))

const filtered = computed(() => store.tasks.filter((task) => {
  const query = filters.query.toLowerCase().trim()
  const timeField = filters.timeType === 'created' ? task.created_at : task.updated_at
  return (!query || `${task.id}${task.title}`.toLowerCase().includes(query))
    && (!filters.type || task.task_type === filters.type)
    && (!filters.category || task.category_id === filters.category)
    && (!filters.priority || task.priority === filters.priority)
    && (!filters.status || (filters.status === 'ABNORMAL' ? abnormalStatuses.includes(task.status) : task.status === filters.status))
    && (!filters.employee || task.employee_id === filters.employee)
    && (!filters.dateFrom || timeField.slice(0, 10) >= filters.dateFrom)
    && (!filters.dateTo || timeField.slice(0, 10) <= filters.dateTo)
}))

const total = computed(() => filtered.value.length)
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const paged = computed(() => filtered.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))
const pageWindow = computed<string[]>(() => {
  const pages = pageCount.value
  const current = currentPage.value
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => String(i + 1))
  const seen = new Set<number | '…'>([1])
  for (let p = current - 1; p <= current + 1; p += 1) if (p > 1 && p < pages) seen.add(p)
  seen.add(pages)
  const sorted = [...seen].sort((a, b) => a === '…' ? 1 : b === '…' ? -1 : (a as number) - (b as number))
  return sorted.reduce<string[]>((result, value, index) => {
    const prev = sorted[index - 1]
    if (value === '…') return [...result, '…']
    if (typeof prev === 'number' && (value as number) - prev > 1) return [...result, '…', String(value)]
    return [...result, String(value)]
  }, [])
})

function setStatus(value: string) { filters.status = value; currentPage.value = 1 }
function goPage(page: number) { if (!Number.isNaN(page)) currentPage.value = page }
const compatibleEmployees = computed(() => store.employees.filter((item) => item.enabled && item.task_types.includes(form.task_type) && item.category_ids.includes(form.category_id)))
const categoryName = (id: string | null) => store.categories.find((item) => item.id === id)?.name ?? '—'
const employeeName = (id: string | null) => employeeDisplayName(store.employees.find((item) => item.id === id)?.name ?? '自动分配')
const typeCopy = (task: Task) => [categoryName(task.category_id), taskTypeLabel(task.task_type)].filter((item) => item !== '—').join(' · ') || '—'
const isHigh = (priority: TaskPriority) => ['VERY_HIGH', 'HIGH'].includes(priority)
const isTerminal = (status: TaskStatus) => terminalStatuses.includes(status)
const progressCopy = (task: Task) => isTerminal(task.status) ? '—' : (platformCopy(task.current_progress) || '—')
const priorityHint = (value: TaskPriority) => ({ VERY_HIGH: '重要且紧急', HIGH: '重要但可以计划处理', MEDIUM: '有一定影响或时效要求', LOW: '一般优化或可延期事项' }[value])
const shortTitle = (value: string) => value.length > 24 ? `${value.slice(0, 24)}…` : value

const resetFilters = () => Object.assign(filters, { query: '', type: '', category: '', priority: '', status: '', employee: '', timeType: 'updated', dateFrom: '', dateTo: '' })
const openTask = (id: string) => router.push(`/tasks/${id}`)

function primaryAction(task: Task) {
  if (task.status === 'ASSIGNED') return { label: '启动', kind: 'start' }
  if (task.status === 'WAIT_HUMAN') return { label: '处理', kind: 'view' }
  if (task.status === 'PENDING_CONFIRMATION') return { label: '确认', kind: 'confirm' }
  if (task.status === 'EXECUTION_ERROR') return { label: '恢复', kind: 'recover' }
  return { label: '查看', kind: 'view' }
}
function onPrimary(task: Task) {
  const { kind, label } = primaryAction(task)
  if (kind === 'view') return openTask(task.id)
  pending.value = { task, name: kind, label }
}
function menuItems(task: Task) {
  const items: Array<{ label: string; name?: string; action?: 'open'; danger?: boolean }> = []
  if (task.status === 'RUNNING') items.push({ label: '挂起任务', name: 'pause' })
  if (task.status === 'SUSPENDED') items.push({ label: '继续任务', name: 'resume' })
  if (!isTerminal(task.status)) items.push({ label: '取消任务', name: 'cancel', danger: true })
  items.push({ label: '查看运行记录', action: 'open' })
  return items
}
function onMenu(item: { label: string; name?: string; action?: 'open'; danger?: boolean }, task: Task) {
  openMenu.value = null
  if (item.action === 'open') return openTask(task.id)
  if (item.name === 'cancel') return (pending.value = { task, name: item.name, label: item.label })
  void runAction(task, item.name ?? '')
}
async function runAction(task: Task, name: string) {
  try {
    await api.taskAction(task.id, name, { reason: '从任务中心操作' })
    await store.refresh()
  } catch (error) {
    window.alert(error instanceof Error ? error.message : '操作失败')
  }
}
async function runPendingAction() {
  if (!pending.value) return
  acting.value = true
  const { task, name } = pending.value
  try {
    await api.taskAction(task.id, name, { reason: '从任务中心操作' })
    pending.value = null
    await store.refresh()
  } catch (error) {
    pending.value = null
    window.alert(error instanceof Error ? error.message : '操作失败')
  } finally {
    acting.value = false
  }
}

const addCriterion = () => criteria.value.push({ key: safeUUID(), content: '' })
function moveCriterion(index: number, direction: number) { const target = index + direction; if (target < 0 || target >= criteria.value.length) return; [criteria.value[index], criteria.value[target]] = [criteria.value[target], criteria.value[index]] }
async function selectFiles(event: Event) { const files = Array.from((event.target as HTMLInputElement).files ?? []); attachments.value = await Promise.all(files.map(async (file) => ({ name: file.name, size: file.size, content_type: file.type || 'application/octet-stream', content: await readFile(file) }))) }
const readFile = (file: File) => new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error); reader.readAsDataURL(file) })
async function createTask() { submitting.value = true; createError.value = ''; try { const task = await api.createTask({ source: 'manual', title: form.title, task_type: form.task_type, category_id: form.category_id, priority: form.priority, completion_policy: form.completion_policy, description: form.description, acceptance_criteria: criteria.value.map((item) => ({ content: item.content })), attachments: attachments.value, employee_id: form.employee_id || null }); dialogOpen.value = false; await store.refresh(); openTask(task.id) } catch (error) { createError.value = error instanceof Error ? error.message : '创建失败' } finally { submitting.value = false } }
</script>

<style scoped>
.task-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 16px; }
.task-head h2 { margin: 7px 0 5px; line-height: normal; letter-spacing: -.02em; }
.task-head p { margin: 0; color: var(--astra-text-secondary); font-size: var(--astra-font-body); }

.task-tabs { display: flex; align-items: center; gap: 5px; margin-bottom: 12px; padding: 5px; border: 1px solid var(--astra-border); border-radius: 10px; background: var(--astra-bg-panel); box-shadow: var(--astra-shadow-panel); white-space: nowrap; overflow-x: auto; }
.task-tabs button { display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 0 13px; color: var(--astra-text-secondary); border: 0; border-radius: 7px; background: transparent; font-size: var(--astra-font-control); cursor: pointer; transition: .14s ease; }
.task-tabs button:hover { background: rgba(101,121,145,.08); }
.task-tabs button.active { color: var(--astra-primary-bright); background: var(--astra-primary-soft); font-weight: var(--astra-weight-bold); }
.task-tabs b { min-width: 16px; padding: 1px 6px; border-radius: 8px; color: var(--astra-text-muted); background: rgba(101,121,145,.12); font-size: var(--astra-font-helper); font-weight: var(--astra-weight-bold); text-align: center; }
.task-tabs button.active b { color: var(--astra-primary-bright); background: rgba(24,184,117,.16); }

.task-filters--more { margin-top: -6px; padding-top: 12px; border-top: 1px dashed var(--astra-border); }
.task-filters .button--ghost { gap: 6px; }
.task-filters .button--ghost svg.rot, .task-filters .button--ghost .rot { transform: rotate(180deg); }
.range-sep { color: var(--astra-text-muted); }

.task-table-panel { width: 100%; }
.task-table-wrap { position: relative; max-height: min(620px, calc(100vh - 360px)); overflow: auto; }
.task-workbench-table { min-width: 1020px; table-layout: fixed; }
.task-workbench-table thead th { position: sticky; top: 0; z-index: 6; height: 44px; padding: 0 14px; border-bottom: 1px solid var(--astra-border); background: #f7faf8; color: var(--astra-text-muted); font-size: var(--astra-font-control); font-weight: var(--astra-weight-bold); white-space: nowrap; }
.task-workbench-table th:nth-child(1) { width: auto; }
.task-workbench-table th:nth-child(2) { width: 148px; }
.task-workbench-table th:nth-child(3) { width: 116px; }
.task-workbench-table th:nth-child(4) { width: 148px; }
.task-workbench-table th:nth-child(5) { width: auto; }
.task-workbench-table th:nth-child(6) { width: 128px; }
.task-workbench-table th:nth-child(7) { width: 150px; }
.task-workbench-table td { height: 66px; padding: 8px 14px; vertical-align: middle; border-top: 1px solid var(--astra-border); font-size: var(--astra-font-body); }
.task-workbench-table tbody tr { cursor: pointer; transition: background-color .14s ease; }
.task-workbench-table tbody tr:hover { background: rgba(24,93,62,.035); }
.task-row--loading td { height: 60px; }
.task-row--loading span { display: block; width: 100%; height: 18px; border-radius: 6px; background: linear-gradient(90deg,#edf3f0,#f8fbf9,#edf3f0); background-size: 200% 100%; animation: task-shimmer 1.35s linear infinite; }

.task-cell { min-width: 0; }
.task-cell__title { display: flex; align-items: flex-start; gap: 7px; min-width: 0; }
.task-cell__title strong { display: -webkit-box; overflow: hidden; color: var(--astra-text-primary); font-weight: var(--astra-weight-bold); line-height: 1.35; -webkit-box-orient: vertical; -webkit-line-clamp: 2; word-break: break-word; }
.task-priority { flex: none; align-self: flex-start; margin-top: 1px; display: inline-flex; align-items: center; min-height: 17px; padding: 0 6px; border-radius: 5px; font-size: var(--astra-font-micro); font-weight: var(--astra-weight-bold); }
.task-priority[data-p='VERY_HIGH'] { color: var(--astra-danger); background: var(--astra-danger-soft); }
.task-priority[data-p='HIGH'] { color: var(--astra-warning); background: var(--astra-warning-soft); }
.task-cell__meta { display: flex; align-items: center; gap: 7px; margin-top: 5px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); white-space: nowrap; }
.task-cell__meta span { font-family: var(--astra-font-family); }
.task-cell__meta em { font-style: normal; }
.task-cell__meta em:not(:empty)::before { content: '·'; margin-right: 7px; color: var(--astra-border-hover); }
.task-cell__meta em:empty { display: none; }

.type-cell, .employee-cell, .time-cell, .status-cell { white-space: nowrap; }
.type-cell span, .employee-cell span, .progress-cell span, .time-cell time { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.progress-cell span, .time-cell time { color: var(--astra-text-muted); }

.actions-wrap { display: flex; align-items: center; gap: 6px; }
.task-primary-btn { display: inline-flex; align-items: center; justify-content: center; min-height: 30px; padding: 0 12px; color: #fff; border: 0; border-radius: 7px; background: var(--astra-primary); font-size: var(--astra-font-control); font-weight: var(--astra-weight-bold); cursor: pointer; white-space: nowrap; transition: .14s ease; }
.task-primary-btn[data-kind='view'] { color: var(--astra-text-secondary); border: 1px solid var(--astra-border); background: var(--astra-bg-panel); }
.task-primary-btn[data-kind='view']:hover { border-color: var(--astra-border-hover); }
.task-primary-btn:hover { filter: brightness(.96); }
.menu-wrap { position: relative; }
.task-menu-btn { display: grid; place-items: center; width: 30px; height: 30px; color: var(--astra-text-muted); border: 1px solid var(--astra-border); border-radius: 7px; background: var(--astra-bg-panel); cursor: pointer; }
.task-menu-btn:hover { color: var(--astra-text-primary); border-color: var(--astra-border-hover); }
.task-menu { position: absolute; right: 0; top: calc(100% + 5px); z-index: 40; min-width: 148px; padding: 5px; border: 1px solid var(--astra-border); border-radius: 9px; background: var(--astra-bg-panel); box-shadow: var(--astra-shadow-panel); }
.task-menu button { display: block; width: 100%; min-height: 32px; padding: 0 9px; color: var(--astra-text-secondary); border: 0; border-radius: 6px; background: transparent; font-size: var(--astra-font-control); text-align: left; cursor: pointer; }
.task-menu button:hover { background: var(--astra-primary-soft); }
.task-menu button.danger { color: var(--astra-danger); }
.task-menu button.danger:hover { background: var(--astra-danger-soft); }

.task-table__foot { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 15px; border-top: 1px solid var(--astra-border); background: #fbfdfc; }
.foot-total { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.foot-right { display: flex; align-items: center; gap: 16px; }
.page-size { display: flex; align-items: center; gap: 7px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.page-size select { height: 30px; padding: 0 26px 0 9px; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 7px; outline: none; background: var(--astra-bg-panel); font-size: var(--astra-font-control); }
.task-page-nav { display: flex; align-items: center; gap: 5px; }
.task-page-nav button { display: grid; place-items: center; min-width: 30px; height: 30px; padding: 0 7px; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 7px; background: var(--astra-bg-panel); font-size: var(--astra-font-control); cursor: pointer; }
.task-page-nav button:hover:not(:disabled):not(.active) { color: var(--astra-primary-bright); border-color: var(--astra-primary-border); }
.task-page-nav button.active { color: #fff; border-color: var(--astra-primary); background: var(--astra-primary); }
.task-page-nav button:disabled { opacity: .4; cursor: default; }

.confirm-action-card { width: min(440px,100%); }
.confirm-action-card header p { margin: 5px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-body); line-height: 1.55; }

@keyframes task-shimmer { to { background-position: -200% 0; } }

@media (max-width: 760px) {
  .task-head { flex-wrap: wrap; align-items: flex-start; }
  .task-workbench-table { min-width: 980px; }
  .task-table-wrap { max-height: calc(100vh - 380px); }
}
</style>
