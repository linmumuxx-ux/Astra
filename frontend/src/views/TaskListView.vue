<template>
  <div class="task-page" data-testid="task-list-page">
    <header class="task-page__intro">
      <div>
        <h2>任务管理</h2>
        <ElText type="info">现在有哪些任务，哪些正在正常运行，哪些需要人工处理。</ElText>
      </div>
      <ElSpace :size="8">
        <ElButton :icon="RefreshCw" :loading="store.loading" @click="store.refresh()">刷新</ElButton>
        <ElButton type="primary" :icon="Plus" @click="createOpen = true">创建任务</ElButton>
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
      <ElTable v-loading="store.loading" :data="paged" height="100%" row-key="id" @row-click="(row: Task) => openTask(row.id)">
        <ElTableColumn label="任务标题" min-width="230">
          <template #default="{ row }">
            <div class="task-title-cell">
              <ElTag v-if="isHigh(row.priority)" :type="row.priority === 'VERY_HIGH' ? 'danger' : 'warning'" effect="light">{{ priorityLabel(row.priority) }}</ElTag>
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
            <ElText type="info" truncated :title="progressCopy(row as Task)">{{ progressCopy(row as Task) }}</ElText>
          </template>
        </ElTableColumn>
        <ElTableColumn label="更新时间" width="140">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <ElSpace class="row-actions" :size="4" @click.stop>
              <ElTooltip content="查看" placement="top">
                <ElButton circle type="primary" :icon="Eye" :aria-label="`查看 ${row.id}`" @click="openTask(row.id)" />
              </ElTooltip>
              <ElTooltip v-for="item in actionsFor(row as Task)" :key="item.action" :content="item.tip" placement="top">
                <ElButton circle :type="item.danger ? 'danger' : 'primary'" :icon="item.icon" :aria-label="`${item.tip} ${row.id}`" @click="onAction(row as Task, item)" />
              </ElTooltip>
            </ElSpace>
          </template>
        </ElTableColumn>
        <template #empty>
          <ElEmpty v-if="store.error && !store.tasks.length" :image-size="72" description="任务数据加载失败">
            <ElText type="info">{{ store.error }}</ElText>
            <ElButton :icon="RefreshCw" @click="store.refresh()">重新加载</ElButton>
          </ElEmpty>
          <ElEmpty v-else-if="!store.loading" :image-size="72" :description="store.tasks.length ? '暂无符合条件的任务' : '暂无任务'">
            <ElText type="info">{{ store.tasks.length ? '当前筛选条件下没有找到任务。' : '创建第一个任务后即可开始管理。' }}</ElText>
            <ElButton v-if="store.tasks.length" @click="resetFilters">清除筛选</ElButton>
            <ElButton v-else type="primary" :icon="Plus" @click="createOpen = true">创建任务</ElButton>
          </ElEmpty>
        </template>
      </ElTable>
    </section>

    <footer class="task-page__footer">
      <ElText type="info">共 {{ total }} 条</ElText>
      <nav aria-label="任务列表分页">
        <ElPagination v-model:current-page="currentPage" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" />
      </nav>
    </footer>

    <TaskCreateDrawer :open="createOpen" @close="createOpen = false" @created="onTaskCreated" />

    <ElDialog
      v-if="pending"
      data-testid="task-action-confirm"
      :model-value="true"
      :title="pending.label"
      width="min(440px,100%)"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :before-close="closePendingAction"
    >
      <ElText type="info">{{ `确认对「${shortTitle(pending.task.title)}」执行该操作？` }}</ElText>
      <template #footer>
        <ElSpace :size="8">
          <ElButton :disabled="acting" @click="pending = null">取消</ElButton>
          <ElButton type="primary" :disabled="acting" :loading="acting" @click="runPendingAction">确认{{ pending.label }}</ElButton>
        </ElSpace>
      </template>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { Ban, Eye, Play, Plus, RefreshCw, RotateCcw, RotateCw, Search, SlidersHorizontal, Trash2 } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElButton, ElDatePicker, ElDialog, ElEmpty, ElInput, ElOption, ElPagination, ElSelect, ElSpace, ElTable, ElTableColumn, ElTag, ElText, ElTooltip, vLoading } from 'element-plus'
import { api } from '@/api/client'
import type { Task, TaskPriority, TaskStatus } from '@/api/types'
import RuntimeStatusBadge from '@/components/runtime/RuntimeStatusBadge.vue'
import TaskCreateDrawer from '@/components/task/TaskCreateDrawer.vue'
import { notify } from '@/composables/useToast'
import {
  TASK_RUNTIME_FILTER_STATES,
  runtimeStatusLabel,
  runtimeStatusMatchesFilter,
  type RuntimeStatusFilter,
} from '@/features/runtime/status'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatTime, platformCopy, priorityLabel, taskTypeLabel } from '@/utils/format'

const store = useAstraStore()
const route = useRoute()
const router = useRouter()
const createOpen = ref(false)
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
watch(() => filters, () => { currentPage.value = 1 }, { deep: true })

onMounted(async () => { await store.refresh() })

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

const categoryName = (id: string | null) => store.categories.find((item) => item.id === id)?.name ?? '—'
const employeeName = (id: string | null) => employeeDisplayName(store.employees.find((item) => item.id === id)?.name ?? '自动分配')
const isHigh = (priority: TaskPriority) => ['VERY_HIGH', 'HIGH'].includes(priority)
const isTerminal = (status: TaskStatus) => terminalStatuses.includes(status)
const progressCopy = (task: Task) => platformCopy(task.runtime_detail || task.current_progress) || '—'
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
function closePendingAction() {
  if (!acting.value) pending.value = null
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

async function onTaskCreated(id: string) {
  createOpen.value = false
  await store.refresh()
  openTask(id)
}
</script>

<style scoped>
.task-page { display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; gap: 14px; height: calc(100vh - 69px); min-height: 620px; padding: 20px 24px 18px; overflow: hidden; }
.task-page__intro { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.task-page__intro h2 { margin: 0 0 2px; font-size: var(--astra-font-title); letter-spacing: -.02em; }

.task-filter { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.task-filter__select { flex: none; width: 148px; }
.task-filter__status { width: 180px; }
.task-filter__search { flex: 1 1 240px; min-width: 190px; max-width: 420px; }
.task-filter__break { flex-basis: 100%; height: 0; }
/* ElDatePicker 根节点是 .el-date-editor.el-input，自身宽度写死 var(--el-date-editor-width)=220px；
   它也没有 scoped 的 data-v 标记，所以这里用 :deep 改它自己的宽度变量，
   让日期框与筛选下拉统一到同一个宽度。 */
.task-filter :deep(.task-filter__date) { --el-date-editor-width: 148px; flex: none; }
.task-filter__dash { color: var(--astra-text-muted); }

.task-table-panel { min-height: 0; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 12px; background: var(--astra-bg-panel); box-shadow: var(--astra-shadow-panel); }
.task-table-panel :deep(.el-table__row) { cursor: pointer; }
.task-title-cell { display: flex; align-items: center; gap: 7px; min-width: 0; }
.task-title-cell strong { overflow: hidden; color: var(--astra-text-primary); font-size: var(--astra-font-label); text-overflow: ellipsis; white-space: nowrap; }

.row-actions { justify-content: flex-end; }
.task-page__footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }

@media (max-width: 900px) {
  .task-page { height: auto; min-height: calc(100vh - 69px); overflow: visible; }
  .task-table-panel { min-height: 480px; }
  .task-filter__select { flex: 1 1 148px; width: auto; }
  .task-filter :deep(.task-filter__date) { --el-date-editor-width: 100%; flex: 1 1 148px; }
  .task-filter__search { flex: 1 1 100%; max-width: none; }
}
</style>
