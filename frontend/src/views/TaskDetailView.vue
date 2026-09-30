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
        <ElButton v-if="!task.current_session_id && !task.pending_message_id" type="primary" :disabled="busy" @click="action('start')">启动任务</ElButton>
        <ElButton v-if="awaitingConfirmation" type="primary" :disabled="busy" @click="action('confirm')">确认完成</ElButton>
        <ElButton v-if="task.status === 'RUNNING' || task.status === 'WAITING' || task.pending_message_id" :type="awaitingConfirmation ? 'danger' : ''" :disabled="busy" @click="action('stop')">{{ awaitingConfirmation ? '取消任务' : '停止' }}</ElButton>
        <ElButton v-if="task.current_session_id && task.status !== 'RUNNING' && !task.pending_message_id" :disabled="busy" @click="action('restart')">重新开始（新 Session）</ElButton>
        <ElButton :icon="Info" @click="showInfo = true">任务信息</ElButton>
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
          <ElButton :disabled="busy" @click="reconnect">重连</ElButton>
          <ElButton v-if="task?.pending_message_id" :disabled="busy" @click="action('retry-submission')">核对并重试未确认输入</ElButton>
        </div>
      </ElAlert>
      <iframe v-if="frameUrl" :key="frameKey" :src="frameUrl" title="OpenCode Task Workspace" class="task-detail__frame" allow="clipboard-read; clipboard-write" />
      <ElEmpty v-else-if="binding" :image-size="80" :description="task?.current_session_id ? 'Session 绑定异常，请重连检查；系统不会自动创建新 Session。' : '任务尚未创建 Session，请先启动任务。'" />
    </ElMain>

    <ElDrawer v-if="task" v-model="showInfo" class="task-info" title="任务信息" size="min(480px, 100%)">
      <ElDescriptions :column="1" border size="small">
        <ElDescriptionsItem label="任务编号">{{ task.id }}</ElDescriptionsItem>
        <ElDescriptionsItem label="任务类型">{{ taskTypeLabel(task.task_type) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="任务分类">{{ categoryName }}</ElDescriptionsItem>
        <ElDescriptionsItem label="优先级">{{ priorityLabel(task.priority) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="完成策略">{{ completionPolicyLabel }}</ElDescriptionsItem>
        <ElDescriptionsItem label="执行员工">{{ employeeName }}</ElDescriptionsItem>
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
  </ElContainer>
</template>

<script setup lang="ts">
import { ArrowLeft, Info } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ElAlert, ElButton, ElContainer, ElDescriptions, ElDescriptionsItem, ElDrawer, ElEmpty, ElHeader, ElMain, ElOption, ElSelect, ElTag, ElText } from 'element-plus'
import { api } from '@/api/client'
import type { Task, TaskWorkspaceBinding } from '@/api/types'
import RuntimeStatusBadge from '@/components/runtime/RuntimeStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatTaskDuration, formatTime, priorityLabel, taskTypeLabel } from '@/utils/format'

const route = useRoute()
const store = useAstraStore()
const task = ref<Task | null>(null)
const binding = ref<TaskWorkspaceBinding | null>(null)
const repo = ref<{ name: string; branch: string; commit: string; dirty: boolean; changes: number } | null>(null)
const selectedSession = ref('')
const error = ref('')
const busy = ref(false)
const showInfo = ref(false)
const frameKey = ref(0)

const employeeName = computed(() => {
  const employee = store.employees.find(item => item.id === task.value?.employee_id)
  return employee ? employeeDisplayName(employee.name) : '未分配员工'
})
const categoryName = computed(() => store.categories.find(item => item.id === task.value?.category_id)?.name ?? '未分类')
const completionPolicyLabel = computed(() => task.value?.completion_policy === 'MANUAL_CONFIRM' ? '需人工确认' : '员工提交后自动完成')
const repoSummary = computed(() => repo.value
  ? `${repo.value.name} / ${repo.value.branch || 'detached'} · ${repo.value.commit?.slice(0, 8)} · ${repo.value.dirty ? `${repo.value.changes} 个变更` : '干净'}`
  : '')
const awaitingConfirmation = computed(() =>
  task.value?.completion_policy === 'MANUAL_CONFIRM' &&
  task.value?.status === 'WAITING' &&
  Boolean(task.value?.submitted_at) &&
  !task.value?.confirmed_at,
)
const selectedSessionBinding = computed(() => binding.value?.sessions.find(item => item.id === selectedSession.value))
const frameUrl = computed(() => {
  if (!selectedSession.value) return ''
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
let events: EventSource | undefined
async function load() {
  const id = String(route.params.id)
  try {
    const [nextTask, nextBinding] = await Promise.all([api.task(id), api.taskWorkspace(id)])
    if (id !== String(route.params.id)) return
    task.value = nextTask; binding.value = nextBinding
    if (!nextBinding.sessions.some(item => item.id === selectedSession.value)) selectedSession.value = nextTask.current_session_id || ''
    error.value = ''
    if (nextTask.workspace) api.taskRepo(id).then(value => { repo.value = value }).catch(() => { repo.value = null })
    else repo.value = null
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '任务加载失败' }
}
async function action(name: string) {
  busy.value = true
  try { task.value = await api.taskAction(String(route.params.id), name); selectedSession.value = task.value.current_session_id || ''; await load() }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '操作失败' }
  finally { busy.value = false }
}
async function reconnect() { await action('reconnect'); frameKey.value++ }
watch(() => route.params.id, () => { selectedSession.value = ''; void load() }, { immediate: true })
onMounted(() => {
  timer = setInterval(() => { now.value = Date.now() }, 1000)
  events = new EventSource(`${import.meta.env.VITE_API_BASE ?? ''}/api/events/stream`)
  events.addEventListener('update', event => { const value = JSON.parse((event as MessageEvent).data); if (value.task_id === route.params.id) void load() })
})
onBeforeUnmount(() => { clearInterval(timer); events?.close() })
</script>

<style scoped>
.task-detail{--el-border-color-lighter:var(--astra-border);height:calc(100vh - 68px);min-height:600px;overflow:hidden}
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
</style>
