<template>
  <section class="task-workspace" data-testid="task-workspace">
    <header v-if="task" class="task-header">
      <RouterLink to="/tasks" class="button">返回任务列表</RouterLink>
      <div class="task-title"><h1>{{ task.title }}</h1><small>{{ employeeName }} · {{ task.id }}</small></div>
      <RuntimeStatusBadge :projection="task" :show-detail="false" />
      <span v-if="repo" class="repo" :title="repo.commit">{{ repo.name }} / {{ repo.branch || 'detached' }} · {{ repo.commit?.slice(0, 8) }} · {{ repo.dirty ? `${repo.changes} 个变更` : '干净' }}</span>
      <select v-if="binding?.sessions.length" v-model="selectedSession" aria-label="选择 Session">
        <option v-for="(item, index) in binding.sessions" :key="item.id" :value="item.id">Session #{{ binding.sessions.length - index }}{{ item.current ? ' · 当前' : ' · 历史只读' }}</option>
      </select>
      <button v-if="!task.current_session_id && !task.pending_message_id" class="button button--primary" :disabled="busy" @click="action('start')">启动任务</button>
      <button v-if="task.status === 'RUNNING' || task.status === 'WAITING' || task.pending_message_id" class="button" :disabled="busy" @click="action('stop')">停止</button>
      <button v-if="task.current_session_id && task.status !== 'RUNNING' && !task.pending_message_id" class="button" :disabled="busy" @click="action('restart')">重新开始（新 Session）</button>
      <button class="button" @click="showInfo = !showInfo">任务信息</button>
    </header>
    <div v-if="error || task?.runtime_error || task?.pending_message_id" role="alert" class="workspace-alert">
      <span>{{ error || task?.runtime_error || '正在核对 Session 输入；启动中断时可先停止后重新开始。' }}</span><span>最后已知状态：{{ task?.runtime_status_label }}</span>
      <button class="button" :disabled="busy" @click="reconnect">重连</button>
      <button v-if="task?.pending_message_id" class="button" :disabled="busy" @click="action('retry-submission')">核对并重试未确认输入</button>
    </div>
    <details v-if="showInfo && task" open class="task-info"><summary>任务信息</summary><p>{{ task.description }}</p>
      <p v-for="criterion in task.acceptance_criteria" :key="criterion.id">{{ criterion.content }}</p>
      <p>工作目录：<code>{{ binding?.runtime.workspace || '尚未准备' }}</code></p>
      <p>Session：<code>{{ selectedSession || '尚未创建' }}</code></p>
      <p>运行时长：{{ duration }}</p>
    </details>
    <iframe v-if="frameUrl" :key="frameKey" :src="frameUrl" title="OpenCode Task Workspace" class="native-workspace" allow="clipboard-read; clipboard-write" />
    <div v-else-if="binding" class="workspace-empty">
      <p>{{ task?.current_session_id ? 'Session 绑定异常，请重连检查；系统不会自动创建新 Session。' : '任务尚未创建 Session，请先启动任务。' }}</p>
      <article v-for="snapshot in binding.history" :key="snapshot.id"><h3>历史快照 · {{ snapshot.id }}</h3><pre>{{ JSON.stringify(snapshot.result, null, 2) }}</pre></article>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@/api/client'
import type { Task, TaskWorkspaceBinding } from '@/api/types'
import RuntimeStatusBadge from '@/components/runtime/RuntimeStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
const route = useRoute()
const store = useAstraStore()
const task = ref<Task | null>(null)
const binding = ref<TaskWorkspaceBinding | null>(null)
const repo = ref<{name: string; branch: string; commit: string; dirty: boolean; changes: number} | null>(null)
const selectedSession = ref('')
const error = ref('')
const busy = ref(false)
const showInfo = ref(false)
const frameKey = ref(0)
const employeeName = computed(() => store.employees.find(item => item.id === task.value?.employee_id)?.name || '未分配员工')
const frameUrl = computed(() => selectedSession.value ? `/opencode-workspace/index.html?task=${encodeURIComponent(String(route.params.id))}&session=${encodeURIComponent(selectedSession.value)}` : '')
const now = ref(Date.now())
const duration = computed(() => {
  if (!task.value?.started_at) return '尚未开始'
  const seconds = Math.max(0, Math.floor(((task.value.finished_at ? Date.parse(task.value.finished_at) : now.value) - Date.parse(task.value.started_at)) / 1000))
  return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m ${seconds % 60}s`
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
.task-workspace{display:flex;flex-direction:column;min-height:calc(100vh - 68px)}.task-header{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:14px 20px;border-bottom:1px solid var(--astra-border);background:var(--astra-bg-base)}.task-title{flex:1;min-width:180px}.task-title h1{font-size:17px;margin:0 0 4px}.task-title small,.repo{color:var(--astra-text-secondary);font-size:12px}.native-workspace{border:0;width:100%;flex:1;height:calc(100vh - 210px);min-height:560px;background:#fff}.workspace-alert{display:flex;align-items:center;gap:16px;padding:12px 20px;background:#fff0d6}.task-info,.workspace-empty{padding:16px 24px}.task-info code{overflow-wrap:anywhere}.workspace-empty pre{white-space:pre-wrap}.task-header select{max-width:220px}
</style>
