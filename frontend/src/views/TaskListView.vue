<template>
  <div class="task-page" data-testid="task-list-page">
    <header class="task-page__intro">
      <div>
        <h2>任务管理</h2>
        <ElText size="small" type="info">现在有哪些任务，哪些正在正常运行，哪些需要人工处理。</ElText>
      </div>
      <ElSpace :size="10">
        <ElButton :icon="RefreshCw" :loading="store.loading" @click="store.refresh()">刷新</ElButton>
        <ElButton type="primary" :icon="Plus" @click="dialogOpen = true">创建任务</ElButton>
      </ElSpace>
    </header>

    <section class="task-filter" aria-label="任务筛选">
      <ElSelect v-model="filters.type" class="task-filter__select" aria-label="任务类型" placeholder="类型：全部" clearable>
        <ElOption value="ISSUE" label="问题" />
        <ElOption value="REQUIREMENT" label="需求" />
      </ElSelect>
      <ElSelect v-model="filters.category" class="task-filter__select" aria-label="任务分类" placeholder="分类：全部" clearable>
        <ElOption v-for="item in store.categories" :key="item.id" :value="item.id" :label="item.name" />
      </ElSelect>
      <ElSelect v-model="filters.status" class="task-filter__select task-filter__status" aria-label="任务状态" placeholder="状态：全部" clearable>
        <ElOption value="ABNORMAL" label="执行失败" />
        <ElOption v-for="item in statuses" :key="item" :value="item" :label="runtimeStatusLabel(item)" />
      </ElSelect>
      <ElSelect v-model="filters.employee" class="task-filter__select" aria-label="执行员工" placeholder="员工：全部" clearable>
        <ElOption v-for="item in store.employees" :key="item.id" :value="item.id" :label="employeeDisplayName(item.name)" />
      </ElSelect>
      <ElInput v-model="filters.query" class="task-filter__search" aria-label="搜索任务" placeholder="搜索任务编号 / 标题" clearable>
        <template #prefix><Search :size="15" /></template>
      </ElInput>
      <ElButton type="primary" plain :icon="Search" @click="applySearch">搜索</ElButton>
      <ElButton :plain="!showMore" :type="showMore ? 'primary' : 'default'" :icon="SlidersHorizontal" @click="showMore = !showMore">高级筛选</ElButton>
      <ElButton :icon="RotateCcw" @click="resetFilters">重置</ElButton>
      <template v-if="showMore">
        <span class="task-filter__break" aria-hidden="true" />
        <ElSelect v-model="filters.priority" class="task-filter__select" aria-label="优先级" placeholder="优先级：全部" clearable>
          <ElOption v-for="item in priorities" :key="item" :value="item" :label="priorityLabel(item)" />
        </ElSelect>
        <ElSelect v-model="filters.timeType" class="task-filter__select" aria-label="时间类型">
          <ElOption value="updated" label="按更新时间" />
          <ElOption value="created" label="按创建时间" />
        </ElSelect>
        <ElDatePicker class="task-filter__date" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" :model-value="filters.dateFrom" @update:model-value="setDateFrom" />
        <span class="task-filter__dash">–</span>
        <ElDatePicker class="task-filter__date" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" :model-value="filters.dateTo" @update:model-value="setDateTo" />
      </template>
    </section>

    <section class="task-table-panel" aria-label="任务列表">
      <ElTable v-loading="store.loading" :data="paged" size="small" height="100%" row-key="id" @row-click="(row: Task) => openTask(row.id)">
        <ElTableColumn label="任务标题" min-width="230">
          <template #default="{ row }">
            <div class="task-title-cell">
              <ElTag v-if="isHigh(row.priority)" size="small" :type="row.priority === 'VERY_HIGH' ? 'danger' : 'warning'" effect="light">{{ priorityLabel(row.priority) }}</ElTag>
              <strong :title="row.title">{{ row.title }}</strong>
            </div>
          </template>
        </ElTableColumn>
        <ElTableColumn label="编号" prop="id" width="150" show-overflow-tooltip />
        <ElTableColumn label="类型" width="72">
          <template #default="{ row }">{{ taskTypeLabel(row.task_type) }}</template>
        </ElTableColumn>
        <ElTableColumn label="分类" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ categoryName(row.category_id) }}</template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="130">
          <template #default="{ row }"><RuntimeStatusBadge :projection="row as Task" :show-detail="false" /></template>
        </ElTableColumn>
        <ElTableColumn label="执行员工" width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ employeeName(row.employee_id) }}</template>
        </ElTableColumn>
        <ElTableColumn label="当前进展" min-width="180">
          <template #default="{ row }">
            <ElText size="small" type="info" truncated :title="progressCopy(row as Task)">{{ progressCopy(row as Task) }}</ElText>
          </template>
        </ElTableColumn>
        <ElTableColumn label="更新时间" width="140">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="158" fixed="right">
          <template #default="{ row }">
            <div class="row-actions" @click.stop>
              <ElTooltip content="查看" placement="top">
                <ElButton text type="primary" :icon="Eye" :aria-label="`查看 ${row.id}`" @click="openTask(row.id)" />
              </ElTooltip>
              <ElTooltip v-for="item in actionsFor(row as Task)" :key="item.action" :content="item.tip" placement="top">
                <ElButton text :type="item.danger ? 'danger' : 'primary'" :icon="item.icon" :aria-label="`${item.tip} ${row.id}`" @click="onAction(row as Task, item)" />
              </ElTooltip>
            </div>
          </template>
        </ElTableColumn>
        <template #empty>
          <ElEmpty v-if="store.error && !store.tasks.length" :image-size="72" description="任务数据加载失败">
            <ElText size="small" type="info">{{ store.error }}</ElText>
            <ElButton :icon="RefreshCw" @click="store.refresh()">重新加载</ElButton>
          </ElEmpty>
          <ElEmpty v-else-if="!store.loading" :image-size="72" :description="store.tasks.length ? '暂无符合条件的任务' : '暂无任务'">
            <ElText size="small" type="info">{{ store.tasks.length ? '当前筛选条件下没有找到任务。' : '创建第一个任务后即可开始管理。' }}</ElText>
            <ElButton v-if="store.tasks.length" @click="resetFilters">清除筛选</ElButton>
            <ElButton v-else type="primary" :icon="Plus" @click="dialogOpen = true">创建任务</ElButton>
          </ElEmpty>
        </template>
      </ElTable>
    </section>

    <footer class="task-page__footer">
      <ElText size="small" type="info">共 {{ total }} 条</ElText>
      <nav aria-label="任务列表分页">
        <ElPagination v-model:current-page="currentPage" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" />
      </nav>
    </footer>

    <AstraDialog
      v-if="dialogOpen"
      :open="true"
      title="创建任务"
      subtitle="定义目标和验收标准，执行方式由数字员工决定。"
      :dismissible="false"
      :busy="submitting"
      testid="task-create-modal"
      card-class="task-create-card"
      width="min(620px,100%)"
      @close="requestCloseCreate"
    >
      <form id="task-create-form" @submit.prevent="createTask">
        <section class="form-section"><h4>基本信息</h4><label>任务标题 *<input v-model.trim="form.title" required placeholder="例如：修复用户登录接口偶发 500 问题" /></label><div class="form-grid"><label>任务类型 *<select v-model="form.task_type" required><option value="ISSUE">问题</option><option value="REQUIREMENT">需求</option></select></label><label>任务分类 *<select v-model="form.category_id" required><option value="" disabled>请选择</option><option v-for="item in store.categories" :key="item.id" :value="item.id">{{ item.name }}</option></select></label></div><div class="form-grid"><label>优先级 *<select v-model="form.priority"><option v-for="item in priorities" :key="item" :value="item">{{ priorityLabel(item) }}：{{ priorityHint(item) }}</option></select></label><FormField label="完成策略" help="很高/高优先级默认人工确认。" v-slot="{ id }"><select :id="id" v-model="form.completion_policy"><option value="AUTO">员工提交后自动完成</option><option value="MANUAL_CONFIRM">需人工确认</option></select></FormField></div></section>
        <section class="form-section"><h4>任务内容</h4><label>任务描述 *<textarea v-model.trim="form.description" required rows="4" placeholder="说明背景、当前情况、需要实现的能力和必要限制" /></label><div class="attachment-field" role="group" aria-label="附件"><span class="attachment-field__label">附件</span><div class="attachment-field__row"><button type="button" class="button button--ghost attachment-add" @click="pickFiles"><Paperclip :size="14" /> 上传附件</button><small class="attachment-field__hint">可选，支持一次选择多个文件</small></div><input ref="fileInput" class="attachment-input" type="file" multiple @change="selectFiles" /><ul v-if="attachments.length" class="attachment-chips"><li v-for="(item, index) in attachments" :key="`${item.name}-${index}`"><FileText :size="13" /><span :title="item.name">{{ item.name }}</span><em>{{ fileSizeLabel(item.size) }}</em><button type="button" :aria-label="`移除附件 ${item.name}`" @click="removeAttachment(index)"><X :size="13" /></button></li></ul></div></section>
        <section class="form-section"><h4>验收标准</h4><div class="criteria-editor"><div v-for="(item, index) in criteria" :key="item.key"><span>{{ index + 1 }}</span><input v-model.trim="item.content" required :placeholder="`验收标准 ${index + 1}`" /><button type="button" title="上移" :disabled="index === 0" @click="moveCriterion(index, -1)"><ArrowUp :size="14" /></button><button type="button" title="下移" :disabled="index === criteria.length - 1" @click="moveCriterion(index, 1)"><ArrowDown :size="14" /></button><button type="button" title="删除" :disabled="criteria.length === 1" @click="criteria.splice(index, 1)"><Trash2 :size="14" /></button></div></div><button type="button" class="button button--ghost" @click="addCriterion"><Plus :size="14" /> 添加验收标准</button></section>
        <section class="form-section"><h4>执行员工</h4><FormField label="分配方式" help="自动分配会综合员工启用状态、空闲状态、任务类型和任务分类。" v-slot="{ id }"><select :id="id" v-model="form.employee_id"><option value="">自动分配</option><option v-for="item in compatibleEmployees" :key="item.id" :value="item.id">{{ employeeDisplayName(item.name) }} · {{ item.role }}</option></select></FormField></section>
        <div v-if="createError" class="form-message" data-error="true">{{ createError }}</div>
      </form>
      <template #footer>
        <button type="button" class="button" :disabled="submitting" @click="requestCloseCreate">取消</button>
        <button type="submit" form="task-create-form" class="button button--primary" :disabled="submitting"><LoaderCircle v-if="submitting" :size="14" class="spin" /> 创建任务</button>
      </template>
    </AstraDialog>

    <AstraDialog
      v-if="pending"
      :open="true"
      :title="pending.label"
      :subtitle="`确认对「${shortTitle(pending.task.title)}」执行该操作？`"
      :dismissible="false"
      :busy="acting"
      testid="task-action-confirm"
      card-class="confirm-action-card"
      width="min(440px,100%)"
      @close="pending = null"
    >
      <template #footer>
        <button type="button" class="button" :disabled="acting" @click="pending = null">取消</button>
        <button type="button" class="button button--primary" :disabled="acting" @click="runPendingAction"><LoaderCircle v-if="acting" :size="14" class="spin" /> 确认{{ pending.label }}</button>
      </template>
    </AstraDialog>
  </div>
</template>

<script setup lang="ts">
import FormField from '@/components/forms/FormField.vue'
import { ArrowDown, ArrowUp, Ban, Eye, FileText, LoaderCircle, Paperclip, Play, Plus, RefreshCw, RotateCcw, RotateCw, Search, SlidersHorizontal, Trash2, X } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElButton, ElDatePicker, ElEmpty, ElInput, ElOption, ElPagination, ElSelect, ElSpace, ElTable, ElTableColumn, ElTag, ElText, ElTooltip, vLoading } from 'element-plus'
import { api } from '@/api/client'
import type { Task, TaskPriority, TaskStatus } from '@/api/types'
import AstraDialog from '@/components/astra/AstraDialog.vue'
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
type ListAction = 'start' | 'cancel' | 'rerun' | 'delete'
interface ActionItem { action: ListAction; tip: string; label: string; icon: Component; danger?: boolean; confirm?: boolean }
const pending = ref<{ task: Task; name: ListAction; label: string } | null>(null)
const acting = ref(false)

const statuses = TASK_RUNTIME_FILTER_STATES
const priorities: TaskPriority[] = ['VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW']
const terminalStatuses: TaskStatus[] = ['SUCCEEDED', 'FAILED', 'CANCELED']

const filters = reactive({
  query: typeof route.query.q === 'string' ? route.query.q : '',
  type: '',
  category: '',
  priority: '',
  status: typeof route.query.status === 'string' ? route.query.status : '',
  employee: typeof route.query.employee === 'string' ? route.query.employee : '',
  timeType: 'updated',
  dateFrom: '',
  dateTo: '',
})
const form = reactive({ title: '', task_type: 'ISSUE' as 'ISSUE' | 'REQUIREMENT', category_id: '', priority: 'MEDIUM' as TaskPriority, completion_policy: 'AUTO' as 'AUTO' | 'MANUAL_CONFIRM', description: '', employee_id: '' })
const criteria = ref([{ key: safeUUID(), content: '' }])
const attachments = ref<Array<{ name: string; size: number; content_type: string; content: string }>>([])
const fileInput = ref<HTMLInputElement | null>(null)

watch(() => filters, () => { currentPage.value = 1 }, { deep: true })
watch(() => form.priority, (priority) => { form.completion_policy = ['VERY_HIGH', 'HIGH'].includes(priority) ? 'MANUAL_CONFIRM' : 'AUTO' })

onMounted(async () => {
  await store.refresh()
  form.category_id = store.categories[0]?.id ?? ''
})

const filtered = computed(() => store.tasks.filter((task) => {
  const query = filters.query.toLowerCase().trim()
  const timeField = filters.timeType === 'created' ? task.created_at : task.updated_at
  return (!query || `${task.id}${task.title}`.toLowerCase().includes(query))
    && (!filters.type || task.task_type === filters.type)
    && (!filters.category || task.category_id === filters.category)
    && (!filters.priority || task.priority === filters.priority)
    && runtimeStatusMatchesFilter(task.runtime_state, filters.status as RuntimeStatusFilter)
    && (!filters.employee || task.employee_id === filters.employee)
    && (!filters.dateFrom || timeField.slice(0, 10) >= filters.dateFrom)
    && (!filters.dateTo || timeField.slice(0, 10) <= filters.dateTo)
}))

const total = computed(() => filtered.value.length)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const paged = computed(() => filtered.value.slice((currentPage.value - 1) * pageSize.value, currentPage.value * pageSize.value))
watch(totalPages, (value) => { currentPage.value = Math.min(currentPage.value, value) })

const compatibleEmployees = computed(() => store.employees.filter((item) => item.enabled && item.task_types.includes(form.task_type) && item.category_ids.includes(form.category_id)))
const categoryName = (id: string | null) => store.categories.find((item) => item.id === id)?.name ?? '—'
const employeeName = (id: string | null) => employeeDisplayName(store.employees.find((item) => item.id === id)?.name ?? '自动分配')
const isHigh = (priority: TaskPriority) => ['VERY_HIGH', 'HIGH'].includes(priority)
const isTerminal = (status: TaskStatus) => terminalStatuses.includes(status)
const progressCopy = (task: Task) => platformCopy(task.runtime_detail || task.current_progress) || '—'
const priorityHint = (value: TaskPriority) => ({ VERY_HIGH: '重要且紧急', HIGH: '重要但可以计划处理', MEDIUM: '有一定影响或时效要求', LOW: '一般优化或可延期事项' }[value])
const shortTitle = (value: string) => value.length > 24 ? `${value.slice(0, 24)}…` : value

const setDateFrom = (value: unknown) => { filters.dateFrom = typeof value === 'string' ? value : '' }
const setDateTo = (value: unknown) => { filters.dateTo = typeof value === 'string' ? value : '' }
const resetFilters = () => Object.assign(filters, { query: '', type: '', category: '', priority: '', status: '', employee: '', timeType: 'updated', dateFrom: '', dateTo: '' })
const openTask = (id: string) => router.push(`/tasks/${id}`)
function applySearch() {
  currentPage.value = 1
  if (!store.loading) void store.refresh()
}

const ACTION_ENDPOINT: Record<Exclude<ListAction, 'delete'>, string> = { start: 'start', cancel: 'stop', rerun: 'restart' }

function actionsFor(task: Task): ActionItem[] {
  if (task.status === 'PENDING') {
    return [
      { action: 'start', tip: '启动', label: '启动', icon: Play },
      { action: 'cancel', tip: '取消', label: '取消任务', icon: Ban, danger: true, confirm: true },
      { action: 'delete', tip: '删除', label: '删除任务', icon: Trash2, danger: true, confirm: true },
    ]
  }
  if (task.status === 'RUNNING' || task.status === 'WAITING') {
    return [{ action: 'cancel', tip: '取消', label: '取消任务', icon: Ban, danger: true, confirm: true }]
  }
  if (isTerminal(task.status)) {
    return [
      { action: 'rerun', tip: '重新执行', label: '重新执行', icon: RotateCw },
      { action: 'delete', tip: '删除', label: '删除任务', icon: Trash2, danger: true, confirm: true },
    ]
  }
  return []
}
function onAction(task: Task, item: ActionItem) {
  if (item.confirm) {
    pending.value = { task, name: item.action, label: item.label }
    return
  }
  void runAction(task, item.action)
}
async function dispatchAction(task: Task, action: ListAction) {
  if (action === 'delete') await api.deleteTask(task.id)
  else await api.taskAction(task.id, ACTION_ENDPOINT[action], { reason: '从任务中心操作' })
}
async function runAction(task: Task, action: ListAction) {
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
.task-page { display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; gap: 14px; height: calc(100vh - 69px); min-height: 620px; padding: 20px 24px 18px; overflow: hidden; }
.task-page__intro { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.task-page__intro h2 { margin: 0 0 2px; font-size: var(--astra-font-title); letter-spacing: -.02em; }

.task-filter { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.task-filter__select { flex: none; width: 148px; }
.task-filter__status { width: 188px; }
.task-filter__search { flex: 1; min-width: 210px; max-width: 320px; }
.task-filter__break { flex-basis: 100%; height: 0; }
.task-filter__date { flex: none; width: 148px; }
.task-filter__dash { color: var(--astra-text-muted); }

.task-table-panel { min-height: 0; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 12px; background: var(--astra-bg-panel); box-shadow: var(--astra-shadow-panel); }
.task-table-panel :deep(.el-table__row) { cursor: pointer; }
.task-title-cell { display: flex; align-items: center; gap: 7px; min-width: 0; }
.task-title-cell strong { overflow: hidden; color: var(--astra-text-primary); font-size: var(--astra-font-label); text-overflow: ellipsis; white-space: nowrap; }

.row-actions { display: flex; align-items: center; gap: 2px; }
.task-page__footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }

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

@media (max-width: 900px) {
  .task-page { height: auto; min-height: calc(100vh - 69px); overflow: visible; }
  .task-table-panel { min-height: 480px; }
}
</style>
