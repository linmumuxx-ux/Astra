<template>
  <div class="page task-list-page" data-testid="task-list-page">
    <section class="task-head">
      <div><h2>任务管理</h2><p>现在有哪些任务，哪些正在正常运行，哪些需要人工处理。</p></div>
      <el-button type="primary" @click="dialogOpen = true"><Plus :size="15" /> 创建任务</el-button>
    </section>

    <nav class="task-tabs" aria-label="任务状态筛选">
      <button type="button" :class="{ active: filters.status === '' }" @click="setStatus('')">全部 <b>{{ store.tasks.length }}</b></button>
      <button v-for="state in statuses" :key="state" type="button" :class="{ active: filters.status === state }" @click="setStatus(state)">{{ runtimeStatusLabel(state) }} <b>{{ runtimeCount(state) }}</b></button>
    </nav>

    <div class="filter-bar task-filters">
      <el-input v-model="filters.query" class="task-search" clearable placeholder="搜索任务 ID 或标题" aria-label="搜索任务"><template #prefix><Search :size="15" /></template></el-input>
      <el-select v-model="filters.type" aria-label="类型"><el-option label="全部类型" value="" /><el-option label="问题" value="ISSUE" /><el-option label="需求" value="REQUIREMENT" /></el-select>
      <el-select v-model="filters.category" aria-label="分类"><el-option label="全部分类" value="" /><el-option v-for="item in store.categories" :key="item.id" :label="item.name" :value="item.id" /></el-select>
      <el-select v-model="filters.status" aria-label="状态"><el-option label="全部状态" value="" /><el-option label="执行失败" value="ABNORMAL" /><el-option v-for="item in statuses" :key="item" :label="runtimeStatusLabel(item)" :value="item" /></el-select>
      <el-select v-model="filters.employee" aria-label="执行员工"><el-option label="全部员工" value="" /><el-option v-for="item in store.employees" :key="item.id" :label="employeeDisplayName(item.name)" :value="item.id" /></el-select>
      <el-button text @click="showMore = !showMore"><SlidersHorizontal :size="14" /> 更多筛选 <ChevronDown :size="14" :class="{ rot: showMore }" /></el-button>
      <el-button text @click="resetFilters"><RotateCcw :size="14" /> 重置</el-button>
    </div>

    <div v-if="showMore" class="filter-bar task-filters task-filters--more">
      <el-select v-model="filters.priority" aria-label="优先级"><el-option label="全部优先级" value="" /><el-option v-for="item in priorities" :key="item" :label="priorityLabel(item)" :value="item" /></el-select>
      <el-select v-model="filters.timeType" aria-label="时间类型"><el-option label="按更新时间" value="updated" /><el-option label="按创建时间" value="created" /></el-select>
      <el-date-picker v-model="filters.dateFrom" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" aria-label="开始日期" />
      <span class="range-sep">–</span>
      <el-date-picker v-model="filters.dateTo" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" aria-label="结束日期" />
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
                  <div class="task-cell__meta"><span>{{ task.id }}</span><em :title="taskTypeLabel(task.task_type)">{{ taskTypeLabel(task.task_type) }}</em></div>
                </td>
                <td class="type-cell"><span :title="typeCopy(task)">{{ typeCopy(task) }}</span></td>
                <td class="status-cell"><RuntimeStatusBadge :projection="task" :show-detail="false" /></td>
                <td class="employee-cell"><span :title="employeeName(task.employee_id)">{{ employeeName(task.employee_id) }}</span></td>
                <td class="progress-cell"><span :title="progressCopy(task)">{{ progressCopy(task) }}</span></td>
                <td class="time-cell"><time :title="formatTime(task.updated_at)">{{ formatTime(task.updated_at) }}</time></td>
                <td class="actions-cell" @click.stop>
                  <div class="actions-wrap">
                    <el-button size="small" @click="openTask(task.id)">查看详情</el-button>
                    <div class="menu-wrap">
                      <button class="task-menu-btn" type="button" aria-label="更多操作" @click="toggleMenu(task.id)"><MoreHorizontal :size="17" /></button>
                      <div v-if="openMenu === task.id" class="task-menu">
                        <button v-for="item in menuItems(task)" :key="item.label" type="button" :class="{ danger: item.danger }" @click="onMenu(item, task)">{{ item.label }}</button>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
              <tr v-if="!paged.length"><td colspan="7"><AstraEmptyState :icon="SearchX" title="暂无符合条件的任务" description="当前筛选条件下没有找到任务。"><el-button text @click="resetFilters">清除筛选</el-button></AstraEmptyState></td></tr>
            </template>
          </tbody>
        </table>
      </div>
      <footer class="task-table__foot">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          :total="total"
        />
      </footer>
    </AstraPanel>

    <el-dialog
      v-if="dialogOpen"
      :model-value="true"
      title="创建任务"
     
     
     
      data-testid="task-create-modal"
      class="task-create-card"
      width="min(620px,100%)"
      @close="requestCloseCreate"
    
      :close-on-click-modal="((false)) && !(submitting)"
      :close-on-press-escape="((false)) && !(submitting)"
      :show-close="!(submitting)"
      append-to-body
      lock-scroll
      destroy-on-close
    >
      <p class="astra-dialog-subtitle">定义目标和验收标准，执行方式由数字员工决定。</p>
      <form id="task-create-form" @submit.prevent="createTask">
        <section class="form-section"><h4>基本信息</h4><label>任务标题 *<el-input v-model="form.title" required placeholder="例如：修复用户登录接口偶发 500 问题" /></label><div class="form-grid"><label>任务类型 *<el-select v-model="form.task_type"><el-option label="问题" value="ISSUE" /><el-option label="需求" value="REQUIREMENT" /></el-select></label><label>任务分类 *<el-select v-model="form.category_id" placeholder="请选择"><el-option v-for="item in store.categories" :key="item.id" :label="item.name" :value="item.id" /></el-select></label></div><div class="form-grid"><label>优先级 *<el-select v-model="form.priority"><el-option v-for="item in priorities" :key="item" :label="`${priorityLabel(item)}：${priorityHint(item)}`" :value="item" /></el-select></label><FormField label="完成策略" help="很高/高优先级默认人工确认。" v-slot="{ id }"><el-select :id="id" v-model="form.completion_policy"><el-option label="员工提交后自动完成" value="AUTO" /><el-option label="需人工确认" value="MANUAL_CONFIRM" /></el-select></FormField></div></section>
        <section class="form-section"><h4>任务内容</h4><label>任务描述 *<el-input v-model="form.description" type="textarea" :rows="4" resize="vertical" required placeholder="说明背景、当前情况、需要实现的能力和必要限制" /></label><div class="attachment-field" role="group" aria-label="附件"><span class="attachment-field__label">附件</span><div class="attachment-field__row"><el-button class="attachment-add" @click="pickFiles"><Paperclip :size="14" /> 上传附件</el-button><small class="attachment-field__hint">可选，支持一次选择多个文件</small></div><input ref="fileInput" class="attachment-input" type="file" multiple @change="selectFiles" /><ul v-if="attachments.length" class="attachment-chips"><li v-for="(item, index) in attachments" :key="`${item.name}-${index}`"><FileText :size="13" /><span :title="item.name">{{ item.name }}</span><em>{{ fileSizeLabel(item.size) }}</em><button type="button" :aria-label="`移除附件 ${item.name}`" @click="removeAttachment(index)"><X :size="13" /></button></li></ul></div></section>
        <section class="form-section"><h4>验收标准</h4><div class="criteria-editor"><div v-for="(item, index) in criteria" :key="item.key"><span>{{ index + 1 }}</span><el-input v-model="item.content" required :placeholder="`验收标准 ${index + 1}`" /><el-button text circle title="上移" :disabled="index === 0" @click="moveCriterion(index, -1)"><ArrowUp :size="14" /></el-button><el-button text circle title="下移" :disabled="index === criteria.length - 1" @click="moveCriterion(index, 1)"><ArrowDown :size="14" /></el-button><el-button type="danger" text circle title="删除" :disabled="criteria.length === 1" @click="criteria.splice(index, 1)"><Trash2 :size="14" /></el-button></div></div><el-button text @click="addCriterion"><Plus :size="14" /> 添加验收标准</el-button></section>
        <section class="form-section"><h4>执行员工</h4><FormField label="分配方式" help="自动分配会综合员工启用状态、空闲状态、任务类型和任务分类。" v-slot="{ id }"><el-select :id="id" v-model="form.employee_id"><el-option label="自动分配" value="" /><el-option v-for="item in compatibleEmployees" :key="item.id" :label="`${employeeDisplayName(item.name)} · ${item.role}`" :value="item.id" /></el-select></FormField></section>
        <div v-if="createError" class="form-message" data-error="true">{{ createError }}</div>
      </form>
      <template #footer>
        <el-button :disabled="submitting" @click="requestCloseCreate">取消</el-button>
        <el-button type="primary" native-type="submit" form="task-create-form" :loading="submitting" :disabled="submitting">创建任务</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-if="pending"
      :model-value="true"
      :title="pending.label"
     
     
     
      data-testid="task-action-confirm"
      class="confirm-action-card"
      width="min(440px,100%)"
      @close="pending = null"
    
      :close-on-click-modal="((false)) && !(acting)"
      :close-on-press-escape="((false)) && !(acting)"
      :show-close="!(acting)"
      append-to-body
      lock-scroll
      destroy-on-close
    >
      <p class="astra-dialog-subtitle">{{ `确认对「${shortTitle(pending.task.title)}」执行该操作？` }}</p>
      <template #footer>
        <el-button :disabled="acting" @click="pending = null">取消</el-button>
        <el-button type="primary" :loading="acting" :disabled="acting" @click="runPendingAction">确认{{ pending.label }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import FormField from '@/components/forms/FormField.vue'
import { ArrowDown, ArrowUp, ChevronDown, FileText, MoreHorizontal, Paperclip, Plus, RotateCcw, Search, SearchX, SlidersHorizontal, Trash2, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Task, TaskPriority, TaskStatus } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import RuntimeStatusBadge from '@/components/runtime/RuntimeStatusBadge.vue'
import { confirmDialog } from '@/composables/useConfirm'
import { notify } from '@/composables/useToast'
import {
  TASK_RUNTIME_FILTER_STATES,
  runtimeStatusLabel,
  runtimeStatusMatchesFilter,
  type RuntimeStatusFilter,
} from '@/features/runtime/status'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatTime, platformCopy, priorityLabel, safeUUID, taskTypeLabel } from '@/utils/format'

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
type MenuAction = 'start' | 'cancel' | 'rerun' | 'delete'
interface MenuItem { label: string; action: MenuAction; danger?: boolean }
const pending = ref<{ task: Task; name: MenuAction; label: string } | null>(null)
const acting = ref(false)

const statuses = TASK_RUNTIME_FILTER_STATES
const priorities: TaskPriority[] = ['VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW']
const terminalStatuses: TaskStatus[] = ['SUCCEEDED', 'FAILED', 'CANCELED']

const filters = reactive({
  query: typeof route.query.q === 'string' ? route.query.q : '',
  type: '',
  category: '',
  priority: '',
  status: (typeof route.query.status === 'string' ? route.query.status : '') as RuntimeStatusFilter,
  employee: typeof route.query.employee === 'string' ? route.query.employee : '',
  timeType: 'updated' as 'updated' | 'created',
  dateFrom: '',
  dateTo: '',
})
const form = reactive({ title: '', task_type: 'ISSUE' as 'ISSUE' | 'REQUIREMENT', category_id: '', priority: 'MEDIUM' as TaskPriority, completion_policy: 'AUTO' as 'AUTO' | 'MANUAL_CONFIRM', description: '', employee_id: '' })
const criteria = ref([{ key: safeUUID(), content: '' }])
const attachments = ref<Array<{ name: string; size: number; content_type: string; content: string }>>([])
const fileInput = ref<HTMLInputElement | null>(null)
const isInitialLoading = computed(() => store.loading && !store.tasks.length)

watch(() => filters, () => { currentPage.value = 1 }, { deep: true })
watch(() => form.priority, (priority) => { form.completion_policy = ['VERY_HIGH', 'HIGH'].includes(priority) ? 'MANUAL_CONFIRM' : 'AUTO' })

onMounted(async () => {
  await store.refresh()
  form.category_id = store.categories[0]?.id ?? ''
  document.addEventListener('click', closeMenu)
})
onBeforeUnmount(() => { document.removeEventListener('click', closeMenu) })

function closeMenu() { openMenu.value = null }
function toggleMenu(id: string) { openMenu.value = openMenu.value === id ? null : id }
const runtimeCount = (state: string) => store.tasks.filter((task) => task.runtime_state === state).length


const filtered = computed(() => store.tasks.filter((task) => {
  const query = filters.query.toLowerCase().trim()
  const timeField = filters.timeType === 'created' ? task.created_at : task.updated_at
  return (!query || `${task.id}${task.title}`.toLowerCase().includes(query))
    && (!filters.type || task.task_type === filters.type)
    && (!filters.category || task.category_id === filters.category)
    && (!filters.priority || task.priority === filters.priority)
    && runtimeStatusMatchesFilter(task.runtime_state, filters.status)
    && (!filters.employee || task.employee_id === filters.employee)
    && (!filters.dateFrom || timeField.slice(0, 10) >= filters.dateFrom)
    && (!filters.dateTo || timeField.slice(0, 10) <= filters.dateTo)
}))

const total = computed(() => filtered.value.length)
const paged = computed(() => filtered.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))
function setStatus(value: RuntimeStatusFilter) { filters.status = value; currentPage.value = 1 }
const compatibleEmployees = computed(() => store.employees.filter((item) => item.enabled && item.task_types.includes(form.task_type) && item.category_ids.includes(form.category_id)))
const categoryName = (id: string | null) => store.categories.find((item) => item.id === id)?.name ?? '—'
const employeeName = (id: string | null) => employeeDisplayName(store.employees.find((item) => item.id === id)?.name ?? '自动分配')
const typeCopy = (task: Task) => [categoryName(task.category_id), taskTypeLabel(task.task_type)].filter((item) => item !== '—').join(' · ') || '—'
const isHigh = (priority: TaskPriority) => ['VERY_HIGH', 'HIGH'].includes(priority)
const isTerminal = (status: TaskStatus) => terminalStatuses.includes(status)
const progressCopy = (task: Task) => platformCopy(task.runtime_detail || task.current_progress) || '—'
const priorityHint = (value: TaskPriority) => ({ VERY_HIGH: '重要且紧急', HIGH: '重要但可以计划处理', MEDIUM: '有一定影响或时效要求', LOW: '一般优化或可延期事项' }[value])
const shortTitle = (value: string) => value.length > 24 ? `${value.slice(0, 24)}…` : value

const resetFilters = () => Object.assign(filters, { query: '', type: '', category: '', priority: '', status: '', employee: '', timeType: 'updated', dateFrom: '', dateTo: '' })
const openTask = (id: string) => router.push(`/tasks/${id}`)

const ACTION_ENDPOINT: Record<Exclude<MenuAction, 'delete'>, string> = { start: 'start', cancel: 'stop', rerun: 'restart' }

function menuItems(task: Task): MenuItem[] {
  if (task.status === 'PENDING') {
    return [
      { label: '开始执行', action: 'start' },
      { label: '取消任务', action: 'cancel', danger: true },
      { label: '删除任务', action: 'delete', danger: true },
    ]
  }
  if (task.status === 'RUNNING' || task.status === 'WAITING') {
    return [{ label: '取消任务', action: 'cancel', danger: true }]
  }
  if (isTerminal(task.status)) {
    return [
      { label: '重新执行', action: 'rerun' },
      { label: '删除任务', action: 'delete', danger: true },
    ]
  }
  return []
}
function onMenu(item: MenuItem, task: Task) {
  openMenu.value = null
  if (item.action === 'cancel' || item.action === 'delete') {
    pending.value = { task, name: item.action, label: item.label }
    return
  }
  void runAction(task, item.action)
}
async function dispatchAction(task: Task, action: MenuAction) {
  if (action === 'delete') await api.deleteTask(task.id)
  else await api.taskAction(task.id, ACTION_ENDPOINT[action], { reason: '从任务中心操作' })
}
async function runAction(task: Task, action: MenuAction) {
  try {
    await dispatchAction(task, action)
    await store.refresh()
  } catch (error) {
    notify(error instanceof Error ? error.message : '操作失败', 'error')
  }
}
async function runPendingAction() {
  if (!pending.value) return
  acting.value = true
  const { task, name } = pending.value
  try {
    await dispatchAction(task, name)
    pending.value = null
    await store.refresh()
  } catch (error) {
    // Keep the dialog open on failure so the user can retry or cancel.
    notify(error instanceof Error ? error.message : '操作失败', 'error')
  } finally {
    acting.value = false
  }
}

const createDirty = computed(() => Boolean(
  form.title.trim()
  || form.description.trim()
  || form.employee_id
  || attachments.value.length
  || criteria.value.some((item) => item.content.trim()),
))
async function requestCloseCreate() {
  if (submitting.value) return
  if (createDirty.value) {
    const confirmed = await confirmDialog({
      title: '放弃未保存的任务草稿？',
      message: '创建任务的内容尚未提交，关闭后将无法恢复。',
      confirmLabel: '放弃并关闭',
      danger: true,
    })
    if (!confirmed) return
  }
  dialogOpen.value = false
}

const addCriterion = () => criteria.value.push({ key: safeUUID(), content: '' })
function moveCriterion(index: number, direction: number) { const target = index + direction; if (target < 0 || target >= criteria.value.length) return; [criteria.value[index], criteria.value[target]] = [criteria.value[target], criteria.value[index]] }
function pickFiles() { fileInput.value?.click() }
function removeAttachment(index: number) { attachments.value.splice(index, 1) }
const fileSizeLabel = (size: number) => size < 1024 ? `${size} B` : size < 1048576 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1048576).toFixed(1)} MB`
async function selectFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length) return
  const picked = await Promise.all(files.map(async (file) => ({ name: file.name, size: file.size, content_type: file.type || 'application/octet-stream', content: await readFile(file) })))
  attachments.value = [...attachments.value, ...picked.filter((item) => !attachments.value.some((existing) => existing.name === item.name && existing.size === item.size))]
}
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
.task-search { width: min(280px, 32vw); }
.task-filters :deep(.el-select) { width: 150px; }
.task-filters :deep(.el-date-editor) { width: 150px; }
.task-filters :deep(.rot) { transform: rotate(180deg); }
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
.menu-wrap { position: relative; }
.task-menu-btn { display: grid; place-items: center; width: 30px; height: 30px; color: var(--astra-text-muted); border: 1px solid var(--astra-border); border-radius: 7px; background: var(--astra-bg-panel); cursor: pointer; }
.task-menu-btn:hover { color: var(--astra-text-primary); border-color: var(--astra-border-hover); }
.task-menu { position: absolute; right: 0; top: calc(100% + 5px); z-index: 40; min-width: 148px; padding: 5px; border: 1px solid var(--astra-border); border-radius: 9px; background: var(--astra-bg-panel); box-shadow: var(--astra-shadow-panel); }
.task-menu button { display: block; width: 100%; min-height: 32px; padding: 0 9px; color: var(--astra-text-secondary); border: 0; border-radius: 6px; background: transparent; font-size: var(--astra-font-control); text-align: left; cursor: pointer; }
.task-menu button:hover { background: var(--astra-primary-soft); }
.task-menu button.danger { color: var(--astra-danger); }
.task-menu button.danger:hover { background: var(--astra-danger-soft); }

.task-table__foot { display: flex; align-items: center; justify-content: flex-end; padding: 10px 15px; border-top: 1px solid var(--astra-border); background: #fbfdfc; }

.confirm-action-card { width: min(440px,100%); }
.confirm-action-card header p { margin: 5px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-body); line-height: 1.55; }

.attachment-field { display: grid; gap: 7px; min-width: 0; }
.attachment-field__label { color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.attachment-field__row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.attachment-field__hint { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.attachment-add { gap: 6px; min-height: var(--astra-control-height-compact); padding: 0 12px; color: var(--astra-primary-bright); border-style: dashed; border-color: var(--astra-primary-border); background: var(--astra-primary-soft); }
.attachment-add:hover:not(:disabled) { color: var(--astra-primary-bright); border-color: var(--astra-primary-border); background: rgba(24,184,117,.16); }
.attachment-input { display: none; }
.attachment-chips { display: flex; flex-wrap: wrap; gap: 7px; margin: 0; padding: 0; list-style: none; }
.attachment-chips li { display: flex; align-items: center; gap: 6px; max-width: 280px; height: 30px; padding: 0 5px 0 9px; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 8px; background: #f8fbf9; font-size: var(--astra-font-helper); }
.attachment-chips li > svg { flex: none; color: var(--astra-primary-bright); }
.attachment-chips span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attachment-chips em { flex: none; color: var(--astra-text-muted); font-style: normal; }
.attachment-chips button { display: grid; place-items: center; flex: none; width: 20px; height: 20px; padding: 0; color: var(--astra-text-muted); border: 0; border-radius: 6px; background: transparent; cursor: pointer; }
.attachment-chips button:hover { color: var(--astra-danger); background: var(--astra-danger-soft); }

@keyframes task-shimmer { to { background-position: -200% 0; } }

@media (max-width: 760px) {
  .task-head { flex-wrap: wrap; align-items: flex-start; }
  .task-workbench-table { min-width: 980px; }
  .task-table-wrap { max-height: calc(100vh - 380px); }
}
</style>
