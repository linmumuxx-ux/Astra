<template>
  <ElContainer direction="vertical" class="task-detail" data-testid="task-workspace">
    <ElHeader v-if="task" class="task-header">
      <ElButton :tag="RouterLink" to="/tasks" :icon="ArrowLeft">返回任务列表</ElButton>
      <div class="task-title">
        <h1>{{ task.title }}</h1>
        <ElText type="info">{{ employeeName }} · {{ task.id }}</ElText>
      </div>
      <RuntimeStatusBadge :projection="task" :show-detail="false" />
      <ElTag v-if="repo" class="repo" type="info" effect="plain" :title="repo.commit">{{ repoSummary }}</ElTag>
      <ElSelect v-if="binding?.sessions.length" v-model="selectedSession" class="task-header__session" data-testid="session-select" :data-session-id="selectedSession" aria-label="选择 Session">
        <ElOption v-for="(item, index) in binding.sessions" :key="item.id" :value="item.id" :label="`Session #${binding.sessions.length - index} · ${item.current ? '当前' : '历史只读'}`" />
      </ElSelect>
      <div class="task-header__actions">
        <ElButton :icon="RefreshCw" :loading="loading" :disabled="busy || loading" data-testid="task-detail-refresh" @click="load">刷新</ElButton>
        <ElButton v-if="!task.current_session_id && !task.pending_message_id" type="primary" :disabled="busy || loading" @click="action('start')">启动任务</ElButton>
        <ElButton v-if="canFinish" type="primary" :disabled="busy || loading" @click="action('confirm')">确认完成</ElButton>
        <ElButton v-if="task.status === 'RUNNING' || task.status === 'WAITING' || task.pending_message_id" type="danger" :disabled="busy || loading" @click="action('stop')">终止任务</ElButton>
        <ElButton v-if="task.current_session_id && task.status !== 'RUNNING' && !task.pending_message_id" :disabled="busy || loading" @click="action('restart')">重新开始（新 Session）</ElButton>
        <ElButton v-if="task.workspace" @click="openChanges">代码变更</ElButton>
        <ElButton v-if="task.current_session_id" data-testid="task-review-open" @click="showReview = true">总结与经验</ElButton>
        <ElButton :icon="Info" @click="showInfo = true">任务信息</ElButton>
        <ElButton data-testid="task-events-open" @click="openEvents">实时事件</ElButton>
        <ElButton data-testid="task-usage-open" @click="openUsage">用量</ElButton>
      </div>
    </ElHeader>

    <ElMain class="task-detail__main">
      <ElAlert
        v-if="error || task?.runtime_error || task?.pending_message_id"
        class="workspace-alert"
        :type="error || task?.runtime_error ? 'error' : 'warning'"
        show-icon
        :closable="false"
        :title="error || task?.runtime_error || '正在核对 Session 输入；启动中断时可先停止后重新开始。'"
      >
        <div class="workspace-alert__body">
          <span>最后已知状态：{{ task?.runtime_status_label }}</span>
          <ElButton :loading="loading" :disabled="busy || loading" @click="load">刷新状态</ElButton>
          <ElButton :disabled="busy || loading" @click="reconnect">重连</ElButton>
          <ElButton v-if="task?.pending_message_id" :disabled="busy || loading" @click="action('retry-submission')">核对并重试未确认输入</ElButton>
        </div>
      </ElAlert>
      <ElAlert v-if="workspaceUiError" class="workspace-alert" type="warning" show-icon :closable="false" :title="workspaceUiError" />
      <iframe v-else-if="frameUrl" :key="frameKey" :src="frameUrl" title="OpenCode Task Workspace" class="task-detail__frame" allow="clipboard-read; clipboard-write" />
      <ElEmpty v-else-if="binding" :image-size="80" :description="task?.current_session_id ? 'Session 绑定异常，请重连检查；系统不会自动创建新 Session。' : '任务尚未创建 Session，请先启动任务。'" />
    </ElMain>

    <ElDrawer v-model="showChanges" title="代码变更" size="min(800px, 100%)">
      <ElTabs v-model="changeMode" @tab-change="loadChanges">
        <ElTabPane label="任务累计变更" name="task" />
        <ElTabPane label="当前未提交" name="git" />
      </ElTabs>
      <ElAlert v-if="changesError" type="error" :title="changesError" :closable="false" />
      <ElText v-if="changesLoading">正在读取 Git 变更…</ElText>
      <ElEmpty v-else-if="!changesError && !changes.length" description="暂无代码变更" />
      <ElCollapse v-else>
        <ElCollapseItem v-for="item in changes" :key="item.file" :title="`${item.file}  +${item.additions} / -${item.deletions}`">
          <pre class="task-diff">{{ item.patch || '二进制文件或无文本差异' }}</pre>
        </ElCollapseItem>
      </ElCollapse>
    </ElDrawer>
    <ElDrawer v-model="showReview" title="任务总结与经验" size="min(720px, 100%)" data-testid="task-review-drawer">
      <ElAlert v-if="reviewError" :title="reviewError" type="error" :closable="false" />
      <template v-if="review">
        <div class="task-review__status">
          <ElTag data-testid="task-review-status" :type="review.status === 'failed' ? 'danger' : 'info'">{{ reviewStatusLabel }}</ElTag>
          <ElText type="info">已尝试 {{ review.attempts }} 次</ElText>
          <ElButton :loading="reviewLoading" @click="loadReview(String(route.params.id))">刷新复盘</ElButton>
          <ElButton v-if="review.can_retry && review.enabled" type="primary" :loading="reviewRetrying" data-testid="task-review-retry" @click="retryReview">重试复盘</ElButton>
        </div>
        <ElAlert v-if="!review.enabled" title="后台复盘未启用，请启用平台助手后刷新。" type="info" :closable="false" />
        <ElAlert v-if="review.error" :title="review.error" type="error" :closable="false" />
        <ElAlert v-if="review.summary && !review.summary_current" title="以下是历史轮次总结，当前轮次尚未完成复盘。" type="warning" :closable="false" />
        <div v-if="review.summary" class="task-review__summary" data-testid="task-review-summary" v-html="safeSummary" />
        <ElEmpty v-else :description="review.status === 'not_ready' ? '人工确认任务完成后，后台自动生成总结。' : '尚未生成任务总结，可刷新查看复盘进度。'" />
        <h3>关联经验</h3>
        <ElText type="info">候选经验须经人工审核发布；任务成功不代表经验已验证。</ElText>
        <ul v-if="review.experiences.length" class="task-review__experiences" data-testid="task-review-experiences">
          <li v-for="item in review.experiences" :key="item.id">
            <RouterLink :to="{ path: '/library', query: { knowledge: item.id } }">{{ item.title }}</RouterLink>
            <ElTag size="small">{{ knowledgeStatusLabel[item.status] }}</ElTag>
            <ElTag size="small" :type="item.verification_status === 'verified' ? 'success' : 'info'">{{ verificationLabel[item.verification_status] }}</ElTag>
          </li>
        </ul>
        <ElEmpty v-else description="暂无关联经验；没有可复用价值时允许只保存总结。" :image-size="50" />
      </template>
    </ElDrawer>
    <ElDrawer v-if="task" v-model="showInfo" class="task-info" title="任务信息" size="min(480px, 100%)">
      <ElDescriptions :column="1" border size="small">
        <ElDescriptionsItem label="任务编号">{{ task.id }}</ElDescriptionsItem>
        <ElDescriptionsItem label="任务类型">{{ taskTypeLabel(task.task_type) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="任务分类">{{ categoryName }}</ElDescriptionsItem>
        <ElDescriptionsItem label="优先级">{{ priorityLabel(task.priority) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="Worker">{{ employeeName }}</ElDescriptionsItem>
        <ElDescriptionsItem label="责任员工">{{ responsibleName }}</ElDescriptionsItem>
        <ElDescriptionsItem label="来源会话">{{ task.source_session_id || '无' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="来源对话">{{ task.source_conversation_id || '无' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="当前状态">{{ task.runtime_status_label }}</ElDescriptionsItem>
        <ElDescriptionsItem label="创建时间">{{ formatTime(task.created_at) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="开始时间">{{ formatTime(task.started_at) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="运行时长">{{ duration }}</ElDescriptionsItem>
        <ElDescriptionsItem label="任务描述"><p class="task-info__paragraph">{{ task.description }}</p></ElDescriptionsItem>
        <ElDescriptionsItem label="验收标准">
          <ol v-if="task.acceptance_criteria.length" class="task-info__criteria"><li v-for="criterion in task.acceptance_criteria" :key="criterion.id">{{ criterion.content }}</li></ol>
          <span v-else>未设置验收标准</span>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="工作目录"><code class="task-info__path">{{ binding?.runtime.workspace || '尚未准备' }}</code></ElDescriptionsItem>
        <ElDescriptionsItem label="执行会话">{{ selectedSession || '尚未创建' }}</ElDescriptionsItem>
      </ElDescriptions>
    </ElDrawer>
    <ElDrawer v-model="showEvents" title="实时事件" size="min(640px, 100%)" data-testid="task-events-drawer">
      <ElEmpty v-if="!events.length" description="还没有任务事件" />
      <ElTimeline v-else>
        <ElTimelineItem v-for="item in events" :key="item.id" :timestamp="formatTime(item.created_at)">
          <strong>{{ item.event_type }}</strong>
          <div>{{ item.message }}</div>
        </ElTimelineItem>
      </ElTimeline>
    </ElDrawer>
    <ElDrawer v-model="showUsage" title="用量" size="min(520px, 100%)" data-testid="task-usage-drawer">
      <ElAlert v-if="usageError" :title="usageError" type="error" :closable="false" />
      <template v-else-if="usage">
        <ElDescriptions :column="1" border size="small">
          <ElDescriptionsItem label="总 Token">{{ formatTokens(usage.summary.total_tokens) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="输入 / 输出">{{ formatTokens(usage.summary.input_tokens) }} / {{ formatTokens(usage.summary.output_tokens) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="模型调用">{{ usage.summary.llm_call_count ?? 0 }}</ElDescriptionsItem>
          <ElDescriptionsItem label="工具调用">{{ usage.summary.tool_call_count ?? 0 }}</ElDescriptionsItem>
          <ElDescriptionsItem label="会话数">{{ usage.sessions }}</ElDescriptionsItem>
        </ElDescriptions>
        <ElTable v-if="usage.tools.length" :data="usage.tools" size="small" style="margin-top: 16px">
          <ElTableColumn prop="tool_name" label="工具" />
          <ElTableColumn prop="call_count" label="次数" width="80" />
          <ElTableColumn prop="success_count" label="成功" width="80" />
          <ElTableColumn prop="failure_count" label="失败" width="80" />
        </ElTable>
      </template>
      <ElEmpty v-else description="正在读取用量" />
    </ElDrawer>
  </ElContainer>
</template>

<script setup lang="ts">
import { ArrowLeft, Info, RefreshCw } from 'lucide-vue-next'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ElAlert, ElButton, ElCollapse, ElCollapseItem, ElContainer, ElDescriptions, ElDescriptionsItem, ElDrawer, ElEmpty, ElHeader, ElMain, ElOption, ElSelect, ElTable, ElTableColumn, ElTabPane, ElTabs, ElTag, ElText, ElTimeline, ElTimelineItem } from 'element-plus'
import { api } from '@/api/client'
import type { AstraEvent, Task, TaskReview, TaskUsage, TaskWorkspaceBinding } from '@/api/types'
import RuntimeStatusBadge from '@/components/runtime/RuntimeStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatTaskDuration, formatTime, formatTokens, priorityLabel, taskTypeLabel } from '@/utils/format'
import { listEmployees } from '../api'
import type { Employee as NexusEmployee } from '../types'

const route = useRoute()
const store = useAstraStore()
const task = ref<Task | null>(null)
const binding = ref<TaskWorkspaceBinding | null>(null)
const repo = ref<{ name: string; branch: string; commit: string; dirty: boolean; changes: number; task_changes?: { changed_files?: number; commits?: string[] } } | null>(null)
const selectedSession = ref('')
const error = ref('')
const busy = ref(false)
const loading = ref(false)
const showInfo = ref(false)
const frameKey = ref(0)
const review = ref<TaskReview | null>(null)
const showReview = ref(false)
const reviewError = ref('')
const reviewLoading = ref(false)
const reviewRetrying = ref(false)
const reviewLabels = { not_ready: '待人工确认完成', pending: '等待后台复盘', running: '正在复盘', completed: '复盘完成', failed: '复盘失败' }
const knowledgeStatusLabel = { draft: '草稿', candidate: '待审核', published: '已发布', archived: '已归档', rejected: '已拒绝' }
const verificationLabel = { unverified: '未验证', verified: '已验证', failed: '验证失败' }
const reviewStatusLabel = computed(() => review.value ? reviewLabels[review.value.status] : '')
const safeSummary = computed(() => DOMPurify.sanitize(marked.parse(review.value?.summary || '', { async: false }) as string, { USE_PROFILES: { html: true } }))
async function loadReview(id: string) {
  reviewLoading.value = true
  try {
    const value = await api.taskReview(id)
    if (id === String(route.params.id)) { review.value = value; reviewError.value = '' }
  } catch (reason) {
    if (id === String(route.params.id)) reviewError.value = reason instanceof Error ? reason.message : '复盘读取失败'
  } finally { if (id === String(route.params.id)) reviewLoading.value = false }
}
async function retryReview() {
  const id = String(route.params.id)
  reviewRetrying.value = true
  try {
    const value = await api.retryTaskReview(id)
    if (id === String(route.params.id)) { review.value = value; reviewError.value = '' }
  } catch (reason) {
    if (id === String(route.params.id)) reviewError.value = reason instanceof Error ? reason.message : '复盘重试失败'
  } finally { reviewRetrying.value = false }
}

const owners = ref<NexusEmployee[]>([])
const employeeName = computed(() => {
  const workerId = task.value?.worker_id || task.value?.employee_id
  const employee = store.employees.find(item => item.id === workerId)
  return employee ? employeeDisplayName(employee.name) : '未分配 Worker'
})
const responsibleName = computed(() => {
  const id = task.value?.responsible_employee_id
  if (!id) return '未指定'
  return owners.value.find(item => item.id === id)?.name ?? id
})
const showEvents = ref(false)
const showUsage = ref(false)
const events = ref<AstraEvent[]>([])
const usage = ref<TaskUsage | null>(null)
const usageError = ref('')
let eventSource: EventSource | null = null
function closeEvents() { eventSource?.close(); eventSource = null }
async function openEvents() {
  const id = String(route.params.id)
  showEvents.value = true
  events.value = await api.taskEvents(id).catch(() => [])
  closeEvents()
  eventSource = new EventSource('/api/events/stream')
  eventSource.addEventListener('update', (message) => {
    const data = JSON.parse((message as MessageEvent).data) as { id: number; type?: string; task_id: string | null; employee_id: string | null; phase: string; message: string; created_at: string }
    if (data.task_id !== id || events.value.some(item => item.id === data.id)) return
    events.value = [...events.value, { id: data.id, task_id: data.task_id, employee_id: data.employee_id, event_type: data.type || '', phase: data.phase, message: data.message, detail: {}, created_at: data.created_at }]
  })
}
async function openUsage() {
  showUsage.value = true
  usageError.value = ''
  usage.value = null
  try { usage.value = await api.taskUsage(String(route.params.id)) }
  catch (reason) { usageError.value = reason instanceof Error ? reason.message : '用量读取失败' }
}
const categoryName = computed(() => store.categories.find(item => item.id === task.value?.category_id)?.name ?? '未分类')
const repoSummary = computed(() => repo.value
  ? `${repo.value.name} / ${repo.value.branch || 'detached'} · ${repo.value.commit?.slice(0, 8)} · 累计 ${repo.value.task_changes?.changed_files ?? 0} 个文件 / ${repo.value.task_changes?.commits?.length ?? 0} 次提交 · 未提交 ${repo.value.changes}`
  : '')
const canFinish = computed(() => task.value?.current_session_id &&
  ['RUNNING', 'WAITING', 'FAILED'].includes(task.value.status) && !task.value.pending_message_id)
const showChanges = ref(false)
const changesLoading = ref(false)
const changesError = ref('')
const changeMode = ref('task')
const changes = ref<Array<{ file: string; patch: string; additions: number; deletions: number }>>([])
let diffRequest: AbortController | null = null
async function loadRepo(id: string) {
  try {
    const value = await api.taskRepo(id)
    if (id === String(route.params.id)) repo.value = value
  } catch { if (id === String(route.params.id)) repo.value = null }
}
async function loadChanges() {
  if (!task.value?.current_session_id) return
  const id = String(route.params.id)
  const sessionId = task.value.current_session_id
  const mode = changeMode.value
  // 快速切换模式时取消上一个请求：只有当前请求能写数据、错误与加载态。
  diffRequest?.abort()
  const controller = new AbortController()
  diffRequest = controller
  changesLoading.value = true; changesError.value = ''
  // 读取有界等待与失败提示：长时间无响应时给出可读错误，而不是永久停留在加载态。
  const deadline = window.setTimeout(() => controller.abort(), 20000)
  try {
    const response = await fetch(`${import.meta.env.VITE_API_BASE ?? ''}/api/tasks/${encodeURIComponent(id)}/opencode/${encodeURIComponent(sessionId)}/vcs/diff?mode=${mode}`, { signal: controller.signal })
    const data = await response.json()
    if (diffRequest !== controller) return
    if (!response.ok) throw new Error(data.detail || '代码变更读取失败')
    if (id === String(route.params.id) && mode === changeMode.value) changes.value = data
    if (id === String(route.params.id)) void loadRepo(id)
  } catch (reason) {
    if (diffRequest !== controller) return
    if (id === String(route.params.id) && mode === changeMode.value) {
      changesError.value = controller.signal.aborted
        ? '读取 Git 变更超时，请重试'
        : reason instanceof Error ? reason.message : '代码变更读取失败'
    }
  } finally {
    window.clearTimeout(deadline)
    if (diffRequest === controller && id === String(route.params.id) && mode === changeMode.value) changesLoading.value = false
  }
}
async function openChanges() { showChanges.value = true; await loadChanges() }
const selectedSessionBinding = computed(() => binding.value?.sessions.find(item => item.id === selectedSession.value))
const workspaceUiError = computed(() => {
  if (!selectedSession.value) return ''
  return selectedSessionBinding.value?.workspace_ui_error || binding.value?.runtime.workspace_ui_error || ''
})
const frameUrl = computed(() => {
  if (!selectedSession.value || workspaceUiError.value) return ''
  const workspaceUi = selectedSessionBinding.value?.workspace_ui || binding.value?.runtime.workspace_ui
  if (!workspaceUi) return ''
  return `${workspaceUi}?task=${encodeURIComponent(String(route.params.id))}&session=${encodeURIComponent(selectedSession.value)}`
})
const now = ref(Date.now())
const duration = computed(() => {
  void now.value
  return task.value?.started_at ? formatTaskDuration(task.value) : '尚未开始'
})

let timer: ReturnType<typeof setInterval> | undefined
let loadRequest: { id: string; promise: Promise<void> } | null = null
function load() {
  const id = String(route.params.id)
  if (loadRequest?.id === id) return loadRequest.promise
  loading.value = true
  const promise = loadTask(id).finally(() => {
    if (loadRequest?.promise === promise) { loadRequest = null; loading.value = false }
  })
  loadRequest = { id, promise }
  return promise
}
async function loadTask(id: string) {
  try {
    const [nextTask, nextBinding] = await Promise.all([api.task(id), api.taskWorkspace(id)])
    if (id !== String(route.params.id)) return
    task.value = nextTask; binding.value = nextBinding
    void loadReview(id)
    if (!nextBinding.sessions.some(item => item.id === selectedSession.value)) selectedSession.value = nextTask.current_session_id || ''
    error.value = ''
    if (nextTask.workspace) await loadRepo(id)
    else repo.value = null
  } catch (reason) { if (id === String(route.params.id)) error.value = reason instanceof Error ? reason.message : '任务加载失败' }
}
async function action(name: string) {
  busy.value = true
  try { task.value = await api.taskAction(String(route.params.id), name); selectedSession.value = task.value.current_session_id || ''; await load() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '操作失败' }
  finally { busy.value = false }
}
async function reconnect() { await action('reconnect'); frameKey.value++ }
watch(() => route.params.id, () => { selectedSession.value = ''; review.value = null; showReview.value = false; reviewError.value = ''; closeEvents(); showEvents.value = false; void load() }, { immediate: true })
onMounted(() => {
  timer = setInterval(() => { now.value = Date.now() }, 1000)
  void listEmployees().then(items => { owners.value = items }).catch(() => { owners.value = [] })
})
onBeforeUnmount(() => { clearInterval(timer); diffRequest?.abort(); closeEvents() })
</script>

<style scoped>
.task-detail{--el-border-color-lighter:var(--astra-border);height:calc(100vh - 260px);min-height:480px;overflow:hidden}
.task-header{--el-header-height:auto;display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:12px 20px;border-bottom:1px solid var(--astra-border);background:var(--astra-bg-panel)}
.task-title{flex:1;min-width:200px;display:grid;gap:3px}
.task-title h1{margin:0;font-size:var(--astra-font-section);line-height:normal}
.task-header__session{width:220px;flex:none}
.task-header__actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-left:auto}
.repo{max-width:400px}
.repo :deep(.el-tag__content){overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.task-detail__main{--el-main-padding:0;display:flex;flex-direction:column;min-height:0;overflow:hidden;background:var(--astra-bg-base)}
.workspace-alert{flex:none;border-radius:0}
.workspace-alert__body{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-top:6px}
.task-detail__frame{flex:1;width:100%;min-height:0;border:0;background:#fff}
.task-detail__main :deep(.el-empty){margin:auto}
.task-info__paragraph{margin:0;white-space:pre-line;line-height:1.6}
.task-info__criteria{margin:0;padding-left:18px;display:grid;gap:4px;line-height:1.6}
.task-info__path{overflow-wrap:anywhere}
.task-diff{white-space:pre;overflow:auto;font-family:monospace;font-size:12px}
.task-review__status{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:16px}
.task-review__summary{line-height:1.7;overflow-wrap:anywhere;margin:18px 0;color:var(--astra-text-primary)}
.task-review__summary :deep(pre){overflow:auto;padding:12px;background:var(--astra-bg-base)}
.task-review__summary :deep(img){max-width:100%}
.task-review__experiences{list-style:none;padding:0;display:grid;gap:12px}
.task-review__experiences li{display:flex;align-items:center;flex-wrap:wrap;gap:8px}
.task-review__experiences a{color:var(--astra-primary);margin-right:auto}
</style>
