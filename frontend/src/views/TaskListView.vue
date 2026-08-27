<template>
  <div class="page" data-testid="task-list-page">
    <section class="page-intro compact-intro"><div><h2>任务中心</h2><p>统一查看任务优先级、执行员工、当前进展和处理结果。</p></div><button class="button button--primary" @click="dialogOpen = true"><Plus :size="15" /> 创建任务</button></section>

    <section class="task-stats">
      <article><span class="mini-icon"><Inbox :size="16" /></span><div><small>待领取</small><strong>{{ count('READY') }}</strong></div></article>
      <article><span class="mini-icon"><Activity :size="16" /></span><div><small>处理中</small><strong>{{ count('RUNNING') }}</strong></div></article>
      <article data-tone="warning"><span class="mini-icon"><Hand :size="16" /></span><div><small>等待人工</small><strong>{{ count('WAIT_HUMAN') }}</strong></div></article>
      <article data-tone="warning"><span class="mini-icon"><Hand :size="16" /></span><div><small>待确认</small><strong>{{ count('PENDING_CONFIRMATION') }}</strong></div></article>
      <article data-tone="success"><span class="mini-icon"><CheckCircle2 :size="16" /></span><div><small>已完成</small><strong>{{ count('COMPLETED') }}</strong></div></article>
    </section>

    <div class="filter-bar task-filters">
      <div class="search-box"><Search :size="15" /><input v-model="filters.query" placeholder="搜索任务 ID 或标题" /></div>
      <select v-model="filters.type"><option value="">全部类型</option><option value="ISSUE">问题</option><option value="REQUIREMENT">需求</option></select>
      <select v-model="filters.category"><option value="">全部分类</option><option v-for="item in store.categories" :key="item.id" :value="item.id">{{ item.name }}</option></select>
      <select v-model="filters.priority"><option value="">全部优先级</option><option v-for="item in priorities" :key="item" :value="item">{{ priorityLabel(item) }}</option></select>
      <select v-model="filters.status"><option value="">全部状态</option><option v-for="item in statuses" :key="item" :value="item">{{ statusLabel(item) }}</option></select>
      <select v-model="filters.employee"><option value="">全部员工</option><option v-for="item in store.employees" :key="item.id" :value="item.id">{{ item.name }}</option></select>
      <input v-model="filters.date" class="date-filter" type="date" aria-label="创建日期" />
      <button class="button button--ghost" @click="resetFilters"><RotateCcw :size="14" /> 重置</button>
    </div>

    <AstraPanel flush>
      <template #title><div class="table-title"><h2>任务列表</h2><span>{{ filtered.length }} 项</span></div></template>
      <div class="table-wrap task-table"><table><thead><tr><th>任务</th><th>类型</th><th>分类</th><th>优先级</th><th>状态</th><th>执行员工</th><th>当前进展</th><th>创建时间</th><th>更新时间</th><th>操作</th></tr></thead><tbody>
        <tr v-for="task in filtered" :key="task.id"><td @click="openTask(task.id)"><strong>{{ task.title }}</strong><small>{{ task.id }}</small></td><td>{{ taskTypeLabel(task.task_type) }}</td><td>{{ categoryName(task.category_id) }}</td><td><span class="priority" :data-priority="task.priority">{{ priorityLabel(task.priority) }}</span></td><td><AstraStatusBadge :status="task.status" :pulse="task.status === 'RUNNING'" /></td><td>{{ employeeName(task.employee_id) }}</td><td class="progress-copy">{{ platformCopy(task.current_progress) || '—' }}</td><td>{{ formatTime(task.created_at) }}</td><td>{{ formatTime(task.updated_at) }}</td><td><div class="row-actions"><button title="查看详情" @click="openTask(task.id)"><Eye :size="14" /></button><button v-if="task.status === 'RUNNING'" title="安全挂起" @click="action(task, 'pause')"><Pause :size="14" /></button><button v-if="['WAIT_HUMAN','SUSPENDED'].includes(task.status)" title="继续" @click="action(task, 'resume')"><Play :size="14" /></button></div></td></tr>
        <tr v-if="!filtered.length"><td colspan="10"><AstraEmptyState :icon="SearchX" title="没有匹配任务" description="调整筛选条件后重试。" /></td></tr>
      </tbody></table></div>
    </AstraPanel>

    <div v-if="dialogOpen" class="modal-backdrop" data-testid="task-create-modal" @click.self="dialogOpen = false">
      <form class="modal-card task-create-card" @submit.prevent="createTask">
        <header><div><h3>创建任务</h3><p>定义目标和验收标准，执行方式由数字员工决定。</p></div><button type="button" aria-label="关闭创建任务" @click="dialogOpen = false"><X :size="17" /></button></header>
        <section class="form-section"><h4>基本信息</h4><label>任务标题 *<input v-model.trim="form.title" required placeholder="例如：修复用户登录接口偶发 500 问题" /></label><div class="form-grid"><label>任务类型 *<select v-model="form.task_type" required><option value="ISSUE">问题</option><option value="REQUIREMENT">需求</option></select></label><label>任务分类 *<select v-model="form.category_id" required><option value="" disabled>请选择</option><option v-for="item in store.categories" :key="item.id" :value="item.id">{{ item.name }}</option></select></label></div><div class="form-grid"><label>优先级 *<select v-model="form.priority"><option v-for="item in priorities" :key="item" :value="item">{{ priorityLabel(item) }}：{{ priorityHint(item) }}</option></select></label><label>完成策略<select v-model="form.completion_policy"><option value="AUTO">员工提交后自动完成</option><option value="MANUAL_CONFIRM">需人工确认</option></select><small>很高/高优先级默认人工确认。</small></label></div></section>
        <section class="form-section"><h4>任务内容</h4><label>任务描述 *<textarea v-model.trim="form.description" required rows="5" placeholder="说明背景、当前情况、需要实现的能力和必要限制" /></label><label>附件<input type="file" multiple @change="selectFiles" /><small v-if="attachments.length">已选择 {{ attachments.map((item) => item.name).join('、') }}</small></label></section>
        <section class="form-section"><h4>验收标准</h4><div class="criteria-editor"><div v-for="(item, index) in criteria" :key="item.key"><span>{{ index + 1 }}</span><input v-model.trim="item.content" required :placeholder="`验收标准 ${index + 1}`" /><button type="button" title="上移" :disabled="index === 0" @click="moveCriterion(index, -1)"><ArrowUp :size="14" /></button><button type="button" title="下移" :disabled="index === criteria.length - 1" @click="moveCriterion(index, 1)"><ArrowDown :size="14" /></button><button type="button" title="删除" :disabled="criteria.length === 1" @click="criteria.splice(index, 1)"><Trash2 :size="14" /></button></div></div><button type="button" class="button button--ghost" @click="addCriterion"><Plus :size="14" /> 添加验收标准</button></section>
        <section class="form-section"><h4>执行员工</h4><label>分配方式<select v-model="form.employee_id"><option value="">自动分配</option><option v-for="item in compatibleEmployees" :key="item.id" :value="item.id">{{ item.name }} · {{ item.role }}</option></select><small>自动分配会综合员工启用状态、空闲状态、任务类型和任务分类。</small></label></section>
        <div v-if="createError" class="form-message" data-error="true">{{ createError }}</div>
        <footer><button type="button" class="button" @click="dialogOpen = false">取消</button><button class="button button--primary" :disabled="submitting"><LoaderCircle v-if="submitting" :size="14" class="spin" /> 创建任务</button></footer>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Activity, ArrowDown, ArrowUp, CheckCircle2, Eye, Hand, Inbox, LoaderCircle, Pause, Play, Plus, RotateCcw, Search, SearchX, Trash2, X } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Task, TaskPriority, TaskStatus } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
import { formatTime, platformCopy, priorityLabel, statusLabel, taskTypeLabel } from '@/utils/format'

const store = useAstraStore(); const router = useRouter(); const dialogOpen = ref(false); const submitting = ref(false); const createError = ref('')
const statuses: TaskStatus[] = ['READY', 'RUNNING', 'WAIT_HUMAN', 'SUSPENDED', 'PENDING_CONFIRMATION', 'COMPLETED', 'FAILED', 'EXECUTION_ERROR', 'CANCELLED']
const priorities: TaskPriority[] = ['VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW']
const filters = reactive({ query: '', type: '', category: '', priority: '', status: '', employee: '', date: '' })
const form = reactive({ title: '', task_type: 'ISSUE' as 'ISSUE' | 'REQUIREMENT', category_id: '', priority: 'MEDIUM' as TaskPriority, completion_policy: 'AUTO' as 'AUTO' | 'MANUAL_CONFIRM', description: '', employee_id: '' })
const criteria = ref([{ key: crypto.randomUUID(), content: '' }])
const attachments = ref<Array<{ name: string; size: number; content_type: string; content: string }>>([])
watch(() => form.priority, (priority) => { form.completion_policy = ['VERY_HIGH', 'HIGH'].includes(priority) ? 'MANUAL_CONFIRM' : 'AUTO' })

onMounted(async () => { await store.refresh(); form.category_id = store.categories[0]?.id ?? '' })
const filtered = computed(() => store.tasks.filter((task) => {
  const day = filters.date && task.created_at.slice(0, 10) === filters.date
  return (!filters.query || `${task.id}${task.title}`.toLowerCase().includes(filters.query.toLowerCase())) && (!filters.type || task.task_type === filters.type) && (!filters.category || task.category_id === filters.category) && (!filters.priority || task.priority === filters.priority) && (!filters.status || task.status === filters.status) && (!filters.employee || task.employee_id === filters.employee) && (!filters.date || day)
}))
const compatibleEmployees = computed(() => store.employees.filter((item) => item.enabled && item.task_types.includes(form.task_type) && item.category_ids.includes(form.category_id)))
const count = (value: TaskStatus) => store.tasks.filter((task) => task.status === value).length
const categoryName = (id: string | null) => store.categories.find((item) => item.id === id)?.name ?? '—'
const employeeName = (id: string | null) => store.employees.find((item) => item.id === id)?.name ?? '自动分配'
const priorityHint = (value: TaskPriority) => ({ VERY_HIGH: '重要且紧急', HIGH: '重要但可以计划处理', MEDIUM: '有一定影响或时效要求', LOW: '一般优化或可延期事项' }[value])
const resetFilters = () => Object.assign(filters, { query: '', type: '', category: '', priority: '', status: '', employee: '', date: '' })
const openTask = (id: string) => router.push(`/tasks/${id}`)
const addCriterion = () => criteria.value.push({ key: crypto.randomUUID(), content: '' })
function moveCriterion(index: number, direction: number) { const target = index + direction; if (target < 0 || target >= criteria.value.length) return; [criteria.value[index], criteria.value[target]] = [criteria.value[target], criteria.value[index]] }
async function selectFiles(event: Event) { const files = Array.from((event.target as HTMLInputElement).files ?? []); attachments.value = await Promise.all(files.map(async (file) => ({ name: file.name, size: file.size, content_type: file.type || 'application/octet-stream', content: await readFile(file) }))) }
const readFile = (file: File) => new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error); reader.readAsDataURL(file) })
async function action(task: Task, name: string) { try { await api.taskAction(task.id, name, { reason: '从任务中心操作' }); await store.refresh() } catch (error) { window.alert(error instanceof Error ? error.message : '操作失败') } }
async function createTask() { submitting.value = true; createError.value = ''; try { const task = await api.createTask({ source: 'manual', title: form.title, task_type: form.task_type, category_id: form.category_id, priority: form.priority, completion_policy: form.completion_policy, description: form.description, acceptance_criteria: criteria.value.map((item) => ({ content: item.content })), attachments: attachments.value, employee_id: form.employee_id || null }); dialogOpen.value = false; await store.refresh(); openTask(task.id) } catch (error) { createError.value = error instanceof Error ? error.message : '创建失败' } finally { submitting.value = false } }
</script>
