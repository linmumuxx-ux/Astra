<template>
  <div class="astra-page" data-testid="task-list-page">
    <AstraPageHeader title="任务管理" description="现在有哪些任务，哪些正在正常运行，哪些需要人工处理。" testid="task-header">
      <template #actions>
        <ElButton :icon="RefreshCw" :loading="store.loading" data-testid="task-refresh" @click="store.refresh()">刷新</ElButton>
        <ElButton type="primary" :icon="Plus" data-testid="task-create" @click="createOpen = true">创建任务</ElButton>
      </template>
    </AstraPageHeader>

    <AstraFilterPanel label="任务筛选" testid="task-filter">
      <ElSelect v-model="filters.type" class="astra-filter__select" data-testid="task-filter-type" aria-label="任务类型" placeholder="类型：全部" clearable>
        <ElOption value="ISSUE" label="问题" />
        <ElOption value="REQUIREMENT" label="需求" />
      </ElSelect>
      <ElSelect v-model="filters.category" class="astra-filter__select" data-testid="task-filter-category" aria-label="任务分类" placeholder="分类：全部" clearable>
        <ElOption v-for="item in store.categories" :key="item.id" :value="item.id" :label="item.name" />
      </ElSelect>
      <ElSelect v-model="filters.status" class="astra-filter__select" data-testid="task-filter-status" aria-label="任务状态" placeholder="状态：全部" clearable>
        <ElOption value="ABNORMAL" label="执行失败" />
        <ElOption v-for="item in statuses" :key="item" :value="item" :label="runtimeStatusLabel(item)" />
      </ElSelect>
      <ElSelect v-model="filters.employee" class="astra-filter__select" data-testid="task-filter-employee" aria-label="执行员工" placeholder="员工：全部" clearable>
        <ElOption v-for="item in store.employees" :key="item.id" :value="item.id" :label="employeeDisplayName(item.name)" />
      </ElSelect>
      <template #search>
        <ElInput v-model="filters.query" class="astra-filter__keyword" data-testid="task-filter-keyword" aria-label="搜索任务" placeholder="搜索任务编号 / 标题" clearable>
          <template #prefix><Search :size="15" /></template>
        </ElInput>
        <ElButton type="primary" :icon="Search" data-testid="task-search" @click="applySearch">搜索</ElButton>
        <ElButton :icon="RotateCcw" data-testid="task-filter-reset" @click="resetFilters">重置</ElButton>
      </template>
    </AstraFilterPanel>

    <section class="astra-table-panel astra-table-panel--clickable" aria-label="任务列表">
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
            <ElSpace class="astra-row-actions" :size="4" @click.stop>
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

    <footer class="astra-page__footer">
      <ElText type="info" data-testid="task-total">共 {{ total }} 条</ElText>
      <nav aria-label="任务列表分页">
        <ElPagination v-model:current-page="currentPage" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" data-testid="task-pagination" />
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
import { Ban, Eye, Play, Plus, RefreshCw, RotateCcw, RotateCw, Search, Trash2 } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElButton, ElDialog, ElEmpty, ElInput, ElOption, ElPagination, ElSelect, ElSpace, ElTable, ElTableColumn, ElTag, ElText, ElTooltip, vLoading } from 'element-plus'
import { api } from '@/api/client'
import type { Task, TaskPriority, TaskStatus } from '@/api/types'
import AstraFilterPanel from '@/components/astra/AstraFilterPanel.vue'
import AstraPageHeader from '@/components/astra/AstraPageHeader.vue'
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
const createOpen = ref(route.query.create === '1')
const pageSize = ref(20)
const currentPage = ref(1)
type ListAction = 'start' | 'cancel' | 'rerun' | 'delete'
interface ActionItem { action: ListAction; tip: string; label: string; icon: Component; danger?: boolean; confirm?: boolean }
const pending = ref<{ task: Task; name: ListAction; label: string } | null>(null)
const acting = ref(false)

const statuses = TASK_RUNTIME_FILTER_STATES
const terminalStatuses: TaskStatus[] = ['SUCCEEDED', 'FAILED', 'CANCELED']

// 只保留最常用的查询条件：类型、分类、状态、执行员工与关键词。
// 优先级、时间类型与日期区间随「高级筛选」一并取消，不再进入 filtered。
const filters = reactive({
  query: typeof route.query.q === 'string' ? route.query.q : '',
  type: '',
  category: '',
  status: typeof route.query.status === 'string' ? route.query.status : '',
  employee: typeof route.query.employee === 'string' ? route.query.employee : '',
})
watch(() => filters, () => { currentPage.value = 1 }, { deep: true })

onMounted(async () => { await store.refresh() })

const filtered = computed(() => store.tasks.filter((task) => {
  const query = filters.query.toLowerCase().trim()
  return (!query || `${task.id}${task.title}`.toLowerCase().includes(query))
    && (!filters.type || task.task_type === filters.type)
    && (!filters.category || task.category_id === filters.category)
    && runtimeStatusMatchesFilter(task.runtime_state, filters.status as RuntimeStatusFilter)
    && (!filters.employee || task.employee_id === filters.employee)
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

const resetFilters = () => Object.assign(filters, { query: '', type: '', category: '', status: '', employee: '' })
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
/* 页面骨架、标题区、筛选面板、表格面板与页脚统一走 styles/page-layout.css，
   这里只保留表格单元格内部的排版。 */
.task-title-cell { display: flex; align-items: center; gap: 7px; min-width: 0; }
.task-title-cell strong { overflow: hidden; color: var(--astra-text-primary); font-size: var(--astra-font-label); text-overflow: ellipsis; white-space: nowrap; }
</style>
