<template>
  <div v-if="task && workbench" class="page task-detail-page" data-testid="task-detail-page">
    <section class="task-workspace">
      <div class="task-shell">
        <main class="task-main">
          <header class="task-header">
            <nav class="task-breadcrumb" aria-label="任务路径">
              <RouterLink to="/">工作台</RouterLink><ChevronRight :size="14" />
              <RouterLink to="/tasks">任务管理</RouterLink><ChevronRight :size="14" />
              <span>{{ task.id }}</span>
            </nav>
            <div class="task-title-row">
              <h2>{{ task.title }}</h2>
              <span class="task-status" :data-tone="taskStatusTone"><Play v-if="task.status === 'RUNNING'" :size="14" /><CheckCircle2 v-else-if="task.status === 'COMPLETED'" :size="14" /><CircleAlert v-else :size="14" />{{ taskStatusLabel }}</span>
              <button class="sidebar-toggle" type="button" aria-label="打开任务信息" @click="sidebarOpen = true"><PanelRightOpen :size="18" />任务信息</button>
            </div>
            <div class="task-meta">
              <span><UserRound :size="15" />分配给：<i />{{ employeeName }}</span><b />
              <span><Clock3 :size="15" />耗时：{{ formatTaskDuration(task) }}</span><b />
              <span><CalendarDays :size="15" />创建时间：{{ formatTime(task.created_at) }}</span>
            </div>
          </header>

          <div ref="conversationViewport" class="conversation-scroller" @scroll="trackScroll">
            <button v-if="workbench.has_more_events" class="load-history" type="button" @click="loadOlder"><History :size="15" />加载更早会话</button>
            <section class="conversation-list" aria-label="任务对话">
              <template v-for="item in conversation.items" :key="`${item.kind}-${item.id}`">
                <article v-if="item.kind === 'message'" class="conversation-turn" :class="`conversation-turn--${item.role}`">
                  <span v-if="item.role === 'agent'" class="actor-avatar actor-avatar--agent"><Bot :size="19" /></span>
                  <div class="turn-content">
                    <header><strong>{{ item.role === 'user' ? '你' : employeeName }}</strong><span v-if="item.role === 'user' && item.status !== 'APPLIED'">{{ messageStatusLabel(item.status) }}</span><time>{{ formatClock(item.timestamp) }}</time></header>
                    <p class="message-bubble">{{ item.content }}</p>
                    <div v-if="item.initial && task.attachments.length" class="message-attachments">
                      <a v-for="attachment in task.attachments" :key="String(attachment.name)" :href="attachmentHref(attachment)" :download="String(attachment.name ?? '附件')"><Paperclip :size="14" />{{ attachment.name }}</a>
                    </div>
                  </div>
                  <span v-if="item.role === 'user'" class="actor-avatar actor-avatar--user">NR</span>
                </article>

                <article v-else-if="item.kind === 'subtask'" class="conversation-turn conversation-turn--agent">
                  <span class="actor-avatar actor-avatar--agent"><Bot :size="19" /></span>
                  <div class="turn-content turn-content--wide">
                    <header><strong>{{ employeeName }}</strong><time>{{ formatClock(item.timestamp) }}</time></header>
                    <SubtaskCard :subtask="item" />
                  </div>
                </article>

                <article v-else class="conversation-turn conversation-turn--agent">
                  <span class="actor-avatar actor-avatar--agent"><Bot :size="19" /></span>
                  <div class="turn-content turn-content--wide">
                    <header><strong>{{ employeeName }}</strong><time>{{ formatClock(item.timestamp) }}</time></header>
                    <section class="inquiry-card" :data-open="isInquiryOpen(item.inquiry)">
                      <div class="inquiry-card__title"><CircleHelp :size="18" /><strong>需要你的确认</strong><span>{{ isInquiryOpen(item.inquiry) ? '等待回答' : item.inquiry.status === 'ANSWERED' ? '已回答' : '已关闭' }}</span></div>
                      <p>{{ item.inquiry.question }}</p><small v-if="item.inquiry.description">{{ item.inquiry.description }}</small>
                      <div v-if="isInquiryOpen(item.inquiry) && item.inquiry.options.length" class="inquiry-options">
                        <button v-for="option in item.inquiry.options" :key="option.value ?? option.label" type="button" @click="answerOption(item.inquiry.id, String(option.value ?? option.label))"><strong>{{ option.label ?? option.value }}</strong><small v-if="option.description">{{ option.description }}</small></button>
                      </div>
                      <div v-if="item.inquiry.answer" class="inquiry-answer"><CheckCircle2 :size="15" />你的回答：{{ item.inquiry.answer }}</div>
                    </section>
                  </div>
                </article>
              </template>

              <article v-if="failureVisible" class="conversation-turn conversation-turn--agent">
                <span class="actor-avatar actor-avatar--danger"><TriangleAlert :size="18" /></span>
                <div class="turn-content turn-content--wide">
                  <header><strong>{{ employeeName }}</strong><time>{{ formatClock(task.finished_at || task.updated_at) }}</time></header>
                  <section class="failure-card"><div><TriangleAlert :size="18" /><strong>任务执行遇到问题</strong></div><p>{{ failureReason }}</p><small>你可以补充要求，让数字员工重新处理；技术细节可在运行详情中查看。</small></section>
                </div>
              </article>

              <article v-if="task.result" class="conversation-turn conversation-turn--agent">
                <span class="actor-avatar actor-avatar--agent"><Bot :size="19" /></span>
                <div class="turn-content turn-content--wide">
                  <header><strong>{{ employeeName }}</strong><time>{{ formatClock(task.submitted_at) }}</time></header>
                  <section class="result-card">
                    <div class="result-card__title"><CheckCircle2 :size="19" /><strong>任务结果</strong><span>{{ task.status === 'PENDING_CONFIRMATION' ? '待你确认' : '已完成' }}</span></div>
                    <p>{{ task.result.summary }}</p>
                    <div v-if="task.acceptance_criteria.length" class="result-acceptance">
                      <div><strong>验收标准</strong><span>{{ passedAcceptance }}/{{ task.acceptance_criteria.length }} 通过</span></div>
                      <article v-for="criterion in task.acceptance_criteria" :key="criterion.id">
                        <CheckCircle2 v-if="acceptanceResult(criterion.id)?.status === 'SATISFIED'" :size="15" /><CircleX v-else-if="acceptanceResult(criterion.id)?.status === 'UNSATISFIED'" :size="15" /><Circle v-else :size="15" /><span>{{ criterion.content }}</span>
                      </article>
                    </div>
                    <small v-if="task.status === 'PENDING_CONFIRMATION'">请确认结果，或直接告诉数字员工需要修改的内容。</small>
                  </section>
                </div>
              </article>

              <article v-if="showWorkingIndicator" class="conversation-turn conversation-turn--agent conversation-turn--working">
                <span class="actor-avatar actor-avatar--agent"><Bot :size="19" /></span>
                <div class="turn-content"><header><strong>{{ employeeName }}</strong><span class="typing"><i /><i /><i /></span></header><p class="working-copy">{{ safeCurrentWork }}</p></div>
              </article>
              <div ref="conversationEnd" class="conversation-end" />
            </section>
          </div>

          <button v-if="showJumpToLatest" class="jump-latest" type="button" @click="scrollToLatest('smooth')"><ArrowDown :size="15" />回到最新</button>

          <footer class="task-composer">
            <div v-if="composerNotice" class="composer-notice" :data-error="composerError"><CircleAlert :size="15" />{{ composerNotice }}</div>
            <div class="composer-row">
              <button class="composer-attach" type="button" aria-label="引用文件"><Paperclip :size="19" /></button>
              <textarea ref="composer" v-model="messageText" :disabled="composerDisabled" :placeholder="composerPlaceholder" rows="2" aria-label="给数字员工的指令" @keydown.enter.exact.prevent="sendMessage" />
              <button class="composer-send" type="button" :disabled="sending || composerDisabled || !messageText.trim()" aria-label="发送指令" @click="sendMessage"><LoaderCircle v-if="sending" class="spin" :size="19" /><Send v-else :size="19" /></button>
            </div>
            <div class="composer-actions">
              <span><i :data-status="task.status" />{{ employeeName }} · {{ taskStatusLabel }}</span>
              <div>
                <button v-if="canStop" class="action-button action-button--danger" type="button" @click="stopDialogOpen = true"><Square :size="15" />停止任务</button>
                <button v-if="task.status === 'RUNNING'" class="action-button" type="button" @click="focusComposer"><PenLine :size="15" />补充要求</button>
                <button v-if="task.status === 'PENDING_CONFIRMATION'" class="action-button action-button--primary" type="button" :disabled="performingAction" @click="perform('confirm')"><CheckCircle2 :size="15" />确认完成</button>
                <button v-if="['PENDING_CONFIRMATION','COMPLETED'].includes(task.status)" class="action-button" type="button" @click="requestRevision"><PenLine :size="15" />要求修改</button>
                <button v-if="canRerun" class="action-button action-button--primary" type="button" :disabled="performingAction" @click="requestRerun"><LoaderCircle v-if="performingAction" class="spin" :size="15" /><RotateCcw v-else :size="15" />重新执行</button>
                <button v-if="task.result" class="action-button" type="button" @click="exportResult"><Download :size="15" />导出结果</button>
              </div>
            </div>
          </footer>
        </main>

        <div v-if="sidebarOpen" class="task-sidebar-backdrop" @click="sidebarOpen = false" />
        <TaskSidebar :class="{ 'is-open': sidebarOpen }" :task="task" :employee-name="employeeName" :employee-role="employeeRole" :task-status-label="taskStatusLabel" :subtasks="conversation.subtasks" :artifacts="artifactItems" :latest-run-id="latestRun?.id ?? null" @close="sidebarOpen = false" />
      </div>
    </section>

    <div v-if="stopDialogOpen" class="dialog-backdrop" role="presentation" @click.self="stopDialogOpen = false">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="stop-dialog-title">
        <span><Square :size="20" /></span><div><h3 id="stop-dialog-title">确定停止任务？</h3><p>数字员工会停止当前执行，已经产生的消息、文件和运行记录仍会保留。</p></div>
        <footer><button type="button" @click="stopDialogOpen = false">继续执行</button><button class="confirm-stop" type="button" :disabled="performingAction" @click="confirmStop"><LoaderCircle v-if="performingAction" class="spin" :size="16" />确认停止</button></footer>
      </section>
    </div>
  </div>
  <div v-else class="page task-detail-loading"><LoaderCircle class="spin" :size="24" /><span>正在加载任务工作区…</span></div>
</template>

<script setup lang="ts">
import { ArrowDown, Bot, CalendarDays, CheckCircle2, ChevronRight, Circle, CircleAlert, CircleHelp, CircleX, Clock3, Download, History, LoaderCircle, PanelRightOpen, Paperclip, PenLine, Play, RotateCcw, Send, Square, TriangleAlert, UserRound } from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@/api/client'
import type { AcceptanceResult, RunInquiry, SessionMessage, TaskWorkbench } from '@/api/types'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatTaskDuration, formatTime, platformCopy, statusTone } from '@/utils/format'
import { buildTaskConversation } from './task-detail/conversation'
import SubtaskCard from './task-detail/SubtaskCard.vue'
import TaskSidebar, { type SidebarArtifact } from './task-detail/TaskSidebar.vue'

const route = useRoute()
const store = useAstraStore()
const workbench = ref<TaskWorkbench | null>(null)
const messageText = ref('')
const sending = ref(false)
const performingAction = ref(false)
const composerNotice = ref('')
const composerError = ref(false)
const sidebarOpen = ref(false)
const stopDialogOpen = ref(false)
const showJumpToLatest = ref(false)
const streamConnected = ref(false)
const conversationViewport = ref<HTMLElement | null>(null)
const conversationEnd = ref<HTMLElement | null>(null)
const composer = ref<HTMLTextAreaElement | null>(null)
let eventSource: EventSource | null = null
let refreshTimer = 0
let stayAtLatest = true

const task = computed(() => workbench.value?.task ?? null)
const employee = computed(() => store.employees.find((item) => item.id === task.value?.employee_id))
const employeeName = computed(() => employeeDisplayName(employee.value?.name ?? task.value?.employee_id ?? '等待分配'))
const employeeRole = computed(() => employee.value?.role ?? '自主任务执行')
const conversation = computed(() => workbench.value ? buildTaskConversation(workbench.value) : { items: [], subtasks: [] })
const latestRun = computed(() => workbench.value?.runs[0] ?? null)
const activeInquiry = computed(() => [...(workbench.value?.inquiries ?? [])].reverse().find(isInquiryOpen) ?? null)
const failureVisible = computed(() => !!task.value && ['FAILED', 'EXECUTION_ERROR'].includes(task.value.status))
const canRerun = computed(() => !!task.value && ['COMPLETED', 'FAILED', 'EXECUTION_ERROR'].includes(task.value.status))
const failureReason = computed(() => String(task.value?.execution_error?.reason ?? task.value?.failure_reason ?? '执行没有达到预期，请补充要求后重新处理。'))
const passedAcceptance = computed(() => task.value?.result?.acceptance_results.filter((item) => item.status === 'SATISFIED').length ?? 0)
const canStop = computed(() => !!task.value && ['READY', 'ASSIGNED', 'QUEUED', 'RUNNING', 'WAIT_HUMAN', 'SUSPENDED', 'EXECUTION_ERROR'].includes(task.value.status))
const composerDisabled = computed(() => task.value?.status === 'CANCELLED')
const showWorkingIndicator = computed(() => task.value?.status === 'RUNNING' && !activeInquiry.value)
const taskStatusLabel = computed(() => ({ READY: '等待领取', ASSIGNED: '等待启动', QUEUED: '等待执行', RUNNING: '执行中', WAIT_HUMAN: '等待输入', SUSPENDED: '已暂停', PENDING_CONFIRMATION: '待你确认', COMPLETED: '已完成', FAILED: '执行失败', EXECUTION_ERROR: '执行异常', CANCELLED: '已停止' }[task.value?.status ?? 'READY']))
const taskStatusTone = computed(() => statusTone(task.value?.status ?? 'READY'))
const safeCurrentWork = computed(() => {
  if (activeInquiry.value) return `等待你的回答：${activeInquiry.value.question}`
  const progress = platformCopy(task.value?.current_progress)
  if (!progress || progress.length > 150 || progress.includes('当前任务：') || progress.includes('员工工作空间：')) return '正在分析任务并推进执行…'
  return progress
})
const composerPlaceholder = computed(() => {
  if (composerDisabled.value) return '任务已停止，无法继续输入'
  if (task.value?.status === 'WAIT_HUMAN') return `请回答：${activeInquiry.value?.question ?? '补充继续执行所需的信息'}`
  if (task.value?.status === 'PENDING_CONFIRMATION') return '继续告诉数字员工如何处理…'
  if (task.value?.status === 'RUNNING') return '补充说明或调整要求…'
  if (task.value?.status === 'COMPLETED') return '继续提出新的要求…'
  if (failureVisible.value) return '说明需要重新处理的内容…'
  return '告诉数字员工下一步怎么处理…'
})
const artifactItems = computed<SidebarArtifact[]>(() => {
  if (!workbench.value || !task.value) return []
  const items: SidebarArtifact[] = []
  const known = new Set<string>()
  for (const artifact of workbench.value.artifacts) {
    if (['work_record', 'log'].includes(artifact.kind)) continue
    known.add(artifact.path)
    items.push({ key: `evidence-${artifact.id}`, name: artifact.name, path: artifact.path, size: artifact.size })
  }
  for (const file of task.value.result?.files ?? []) {
    if (known.has(file)) continue
    items.push({ key: `file-${file}`, name: file.split(/[\\/]/).at(-1) || file, path: file, size: null })
  }
  return items
})

const acceptanceResult = (criterionId: string): AcceptanceResult | undefined => task.value?.result?.acceptance_results.find((item) => item.criterion_id === criterionId)
const isInquiryOpen = (inquiry: RunInquiry) => ['OPEN', 'PENDING'].includes(inquiry.status)
const messageStatusLabel = (status: SessionMessage['status']) => ({ PENDING: '等待生效', QUEUED: '已排队', ANSWERED: '已回答', APPLIED: '已生效' }[status])
const attachmentHref = (item: Record<string, unknown>) => String(item.content ?? item.url ?? '#')
const formatClock = (value: string | null | undefined) => value ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(value)) : '—'

async function load(initial = false) {
  const shouldFollow = initial || stayAtLatest
  workbench.value = await api.taskWorkbench(String(route.params.id))
  if (initial && !store.employees.length) await store.refresh()
  await nextTick()
  if (shouldFollow) scrollToLatest()
}

async function loadOlder() {
  if (!workbench.value?.events.length || !conversationViewport.value) return
  const viewport = conversationViewport.value
  const previousHeight = viewport.scrollHeight
  const older = await api.taskWorkbench(String(route.params.id), workbench.value.events[0].sequence)
  const known = new Set(workbench.value.events.map((event) => event.id))
  workbench.value = { ...workbench.value, events: [...older.events.filter((event) => !known.has(event.id)), ...workbench.value.events], has_more_events: older.has_more_events }
  await nextTick()
  viewport.scrollTop += viewport.scrollHeight - previousHeight
}

function connectStream() {
  eventSource?.close()
  const base = import.meta.env.VITE_API_BASE ?? ''
  const sequence = workbench.value?.events.at(-1)?.sequence ?? 0
  eventSource = new EventSource(`${base}/api/tasks/${route.params.id}/workspace/stream?after_sequence=${sequence}`)
  eventSource.addEventListener('connected', () => { streamConnected.value = true })
  eventSource.addEventListener('update', () => { window.clearTimeout(refreshTimer); refreshTimer = window.setTimeout(() => load(), 180) })
  eventSource.onerror = () => { streamConnected.value = false }
}

function scrollToLatest(behavior: ScrollBehavior = 'auto') {
  const viewport = conversationViewport.value
  if (!viewport) return
  stayAtLatest = true
  showJumpToLatest.value = false
  viewport.scrollTo({ top: viewport.scrollHeight, behavior })
}

function trackScroll() {
  const viewport = conversationViewport.value
  if (!viewport) return
  const distance = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight
  stayAtLatest = distance < 72
  showJumpToLatest.value = !stayAtLatest
}

async function sendMessage() {
  const content = messageText.value.trim()
  if (!content || sending.value || !task.value || composerDisabled.value) return
  sending.value = true
  composerNotice.value = ''
  composerError.value = false
  try {
    const wasRunning = task.value.status === 'RUNNING'
    const wasWaiting = task.value.status === 'WAIT_HUMAN'
    workbench.value = await api.postTaskMessage(task.value.id, content)
    messageText.value = ''
    composerNotice.value = wasRunning ? '补充要求已收到，将在当前操作结束后生效。' : wasWaiting ? '回答已提交，数字员工将继续执行。' : '要求已发送给数字员工。'
    await nextTick()
    scrollToLatest('smooth')
  } catch (reason) {
    composerError.value = true
    composerNotice.value = reason instanceof Error ? reason.message : '发送失败'
  } finally {
    sending.value = false
  }
}

async function answerOption(inquiryId: string, answer: string) {
  sending.value = true
  try {
    workbench.value = await api.answerInquiry(inquiryId, answer)
    composerNotice.value = '选择已提交，数字员工将继续执行。'
    await nextTick()
    scrollToLatest('smooth')
  } catch (reason) {
    composerError.value = true
    composerNotice.value = reason instanceof Error ? reason.message : '提交失败'
  } finally {
    sending.value = false
  }
}

function focusComposer() { nextTick(() => composer.value?.focus()) }
function requestRevision() { messageText.value = '请根据以下要求修改结果：'; focusComposer() }
function requestRerun() { void perform('rerun') }

async function perform(action: string) {
  if (!task.value || performingAction.value) return
  performingAction.value = true
  composerError.value = false
  try {
    await api.taskAction(task.value.id, action, action === 'cancel' ? { reason: '用户在任务工作区停止任务' } : {})
    composerNotice.value = action === 'confirm' ? '任务结果已确认。' : action === 'cancel' ? '任务已停止。' : action === 'rerun' ? '已创建新的运行并进入执行队列。' : '操作已完成。'
    await load()
  } catch (reason) {
    composerError.value = true
    composerNotice.value = reason instanceof Error ? reason.message : '操作失败'
  } finally {
    performingAction.value = false
  }
}

async function confirmStop() { await perform('cancel'); stopDialogOpen.value = false }

function exportResult() {
  if (!workbench.value) return
  const body = JSON.stringify({ task: workbench.value.task, result: workbench.value.task.result, artifacts: artifactItems.value }, null, 2)
  const link = document.createElement('a')
  const url = URL.createObjectURL(new Blob([body], { type: 'application/json' }))
  link.href = url
  link.download = `${workbench.value.task.id}-result.json`
  link.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  await load(true)
  connectStream()
  if (route.query.compose === '1') focusComposer()
})
onBeforeUnmount(() => { eventSource?.close(); window.clearTimeout(refreshTimer) })
</script>

<style scoped>
.task-detail-page{height:calc(100dvh - 80px);min-height:620px;padding:0;overflow:hidden;background:#fff}.task-workspace{display:flex;height:100%;min-width:0;flex-direction:column;overflow:hidden;background:#fff}
.task-header{flex:none;padding:15px clamp(20px,3vw,38px) 16px;border-bottom:1px solid var(--astra-border);background:linear-gradient(135deg,#fff 72%,#f5fbf8)}.task-breadcrumb{display:flex;align-items:center;gap:7px;margin-bottom:13px;color:var(--astra-text-muted);font-size: var(--astra-font-body)}.task-breadcrumb a:hover{color:var(--astra-primary-bright)}.task-title-row{display:flex;align-items:center;gap:15px}.task-title-row h2{min-width:0;margin:0;line-height: 1.3;letter-spacing:-.025em}.task-status{display:inline-flex;flex:none;align-items:center;gap:6px;padding:6px 11px;color:var(--astra-info);border-radius:9px;background:color-mix(in srgb,var(--astra-info) 11%,transparent);font-size: var(--astra-font-label);font-weight: var(--astra-weight-bold);white-space:nowrap}.task-status[data-tone=success]{color:var(--astra-success);background:var(--astra-success-soft)}.task-status[data-tone=warning]{color:var(--astra-warning);background:var(--astra-warning-soft)}.task-status[data-tone=danger]{color:var(--astra-danger);background:var(--astra-danger-soft)}.task-meta{display:flex;align-items:center;gap:12px;margin-top:13px;color:var(--astra-text-muted);font-size: var(--astra-font-body)}.task-meta span{display:inline-flex;align-items:center;gap:6px}.task-meta span i{width:7px;height:7px;border-radius:50%;background:var(--astra-success)}.task-meta>b{width:1px;height:16px;background:var(--astra-border)}.sidebar-toggle{display:none;align-items:center;gap:6px;margin-left:auto;padding:7px 10px;color:var(--astra-text-secondary);border:1px solid var(--astra-border);border-radius:8px;background:#fff;cursor:pointer}
.task-shell{position:relative;display:grid;min-height:0;flex:1;grid-template-columns:minmax(0,1fr) 340px;overflow:hidden}.task-main{position:relative;display:flex;min-width:0;min-height:0;flex-direction:column;background:#fff}.conversation-scroller{min-height:0;flex:1;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable}.load-history{display:flex;align-items:center;gap:6px;margin:13px auto 0;padding:7px 11px;color:var(--astra-text-muted);border:1px solid var(--astra-border);border-radius:18px;background:#fff;font-size: var(--astra-font-body);cursor:pointer}.load-history:hover{color:var(--astra-primary-bright);border-color:var(--astra-primary-border)}.conversation-list{width:min(100%,920px);min-height:100%;margin:0 auto;padding:24px clamp(20px,4vw,52px) 36px}
.conversation-turn{display:flex;align-items:flex-start;gap:12px;margin-bottom:22px}.conversation-turn--user{justify-content:flex-end}.actor-avatar{display:grid;flex:none;place-items:center;width:42px;height:42px;border-radius:50%;font-size: var(--astra-font-label);font-weight: var(--astra-weight-bold)}.actor-avatar--agent{color:var(--astra-primary-bright);background:var(--astra-primary-soft)}.actor-avatar--user{color:#0d7b50;background:#e4f5ec}.actor-avatar--danger{color:var(--astra-danger);background:var(--astra-danger-soft)}.turn-content{display:grid;max-width:min(72%,720px);min-width:0}.turn-content--wide{width:min(100%,720px);max-width:none}.turn-content>header{display:flex;align-items:center;gap:8px;min-height:20px;margin-bottom:5px;color:var(--astra-text-muted);font-size: var(--astra-font-control)}.turn-content>header strong{color:var(--astra-text-secondary);font-size: var(--astra-font-body)}.turn-content>header span{color:var(--astra-primary-bright)}.turn-content>header time{margin-left:auto}.conversation-turn--user .turn-content>header{justify-content:flex-end}.message-bubble{margin:0;padding:12px 15px;color:var(--astra-text-secondary);border:1px solid var(--astra-border);border-radius:4px 13px 13px 13px;background:#fff;font-size: var(--astra-font-emphasis);line-height:1.7;white-space:pre-wrap;word-break:break-word}.conversation-turn--user .message-bubble{border-color:#d8e9e1;border-radius:13px 4px 13px 13px;background:linear-gradient(135deg,#f0f9f5,#eaf6f0)}.message-attachments{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px;margin-top:7px}.message-attachments a{display:inline-flex;align-items:center;gap:5px;padding:5px 8px;color:var(--astra-primary-bright);border-radius:6px;background:var(--astra-primary-soft);font-size: var(--astra-font-control)}
.inquiry-card{width:min(100%,720px);padding:15px 16px;border:1px solid color-mix(in srgb,var(--astra-warning) 30%,var(--astra-border));border-radius:12px;background:#fffdf8}.inquiry-card__title{display:flex;align-items:center;gap:7px;color:var(--astra-warning)}.inquiry-card__title strong{color:var(--astra-text-primary);font-size: var(--astra-font-emphasis)}.inquiry-card__title span{margin-left:auto;padding:3px 7px;border-radius:999px;background:var(--astra-warning-soft);font-size: var(--astra-font-control)}.inquiry-card>p{margin:10px 0 0;font-size: var(--astra-font-emphasis);line-height:1.65}.inquiry-card>small{display:block;margin-top:4px;color:var(--astra-text-muted);font-size: var(--astra-font-body)}.inquiry-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}.inquiry-options button{display:grid;gap:2px;padding:10px;color:var(--astra-text-secondary);border:1px solid var(--astra-border);border-radius:8px;background:#fff;text-align:left;cursor:pointer}.inquiry-options button:hover{color:var(--astra-primary-bright);border-color:var(--astra-primary-border);background:var(--astra-primary-soft)}.inquiry-options small{color:var(--astra-text-muted)}.inquiry-answer{display:flex;align-items:center;gap:6px;margin-top:12px;padding:8px 10px;color:var(--astra-success);border-radius:7px;background:var(--astra-success-soft);font-size: var(--astra-font-body)}
.failure-card,.result-card{width:min(100%,720px);padding:15px 16px;border:1px solid var(--astra-border);border-radius:12px;background:#fff}.failure-card{border-color:color-mix(in srgb,var(--astra-danger) 28%,var(--astra-border));background:linear-gradient(135deg,#fff,var(--astra-danger-soft))}.failure-card>div,.result-card__title{display:flex;align-items:center;gap:7px;color:var(--astra-danger)}.failure-card strong,.result-card__title strong{color:var(--astra-text-primary);font-size: var(--astra-font-emphasis)}.failure-card p,.result-card>p{margin:9px 0 0;color:var(--astra-text-secondary);font-size: var(--astra-font-label);line-height:1.65;white-space:pre-wrap;word-break:break-word}.failure-card small,.result-card>small{display:block;margin-top:10px;color:var(--astra-text-muted);font-size: var(--astra-font-control)}.result-card{background:linear-gradient(135deg,#fff,#f8fcfa)}.result-card__title{color:var(--astra-success)}.result-card__title span{margin-left:auto;color:var(--astra-success);font-size: var(--astra-font-control)}.result-acceptance{margin-top:13px;padding:10px 11px;border:1px solid #dfeae5;border-radius:8px;background:#fff}.result-acceptance>div{display:flex;align-items:center;justify-content:space-between;margin-bottom:5px}.result-acceptance>div strong{font-size: var(--astra-font-body)}.result-acceptance>div span{color:var(--astra-success);font-size: var(--astra-font-control)}.result-acceptance article{display:flex;align-items:flex-start;gap:7px;padding:5px 0;color:var(--astra-text-secondary);font-size: var(--astra-font-control)}.result-acceptance article svg{flex:none;margin-top:1px;color:var(--astra-text-muted)}.result-acceptance article svg.lucide-check-circle{color:var(--astra-success)}.result-acceptance article svg.lucide-circle-x{color:var(--astra-danger)}
.conversation-turn--working{opacity:.88}.working-copy{margin:0;color:var(--astra-text-muted);font-size: var(--astra-font-body)}.typing{display:inline-flex!important;gap:3px!important}.typing i{width:4px;height:4px;border-radius:50%;background:var(--astra-primary);animation:typing 1.2s infinite}.typing i:nth-child(2){animation-delay:.15s}.typing i:nth-child(3){animation-delay:.3s}.conversation-end{height:1px}.jump-latest{position:absolute;right:24px;bottom:132px;z-index:4;display:flex;align-items:center;gap:5px;padding:7px 11px;color:var(--astra-primary-bright);border:1px solid var(--astra-primary-border);border-radius:18px;background:#fff;box-shadow:var(--astra-shadow-panel);font-size: var(--astra-font-body);cursor:pointer}
.task-composer{flex:none;padding:11px clamp(18px,3vw,28px) 12px;border-top:1px solid var(--astra-border);background:#fbfdfc;box-shadow:0 -9px 28px rgba(28,58,49,.045)}.composer-notice{display:flex;align-items:center;gap:6px;margin-bottom:8px;padding:7px 9px;color:var(--astra-success);border-radius:7px;background:var(--astra-success-soft);font-size: var(--astra-font-body)}.composer-notice[data-error=true]{color:var(--astra-danger);background:var(--astra-danger-soft)}.composer-row{display:grid;grid-template-columns:38px minmax(0,1fr) 38px;align-items:center;gap:6px;min-height:58px;padding:5px 8px;border:1px solid var(--astra-border-hover);border-radius:11px;background:#fff}.composer-row:focus-within{border-color:var(--astra-primary-border);box-shadow:0 0 0 3px var(--astra-primary-soft)}.composer-row textarea{width:100%;min-height:43px;max-height:110px;padding:8px 5px;color:var(--astra-text-primary);border:0;outline:0;background:transparent;line-height:1.55;resize:none}.composer-row textarea:disabled{cursor:not-allowed}.composer-attach,.composer-send{display:grid;place-items:center;width:36px;height:36px;color:var(--astra-text-muted);border:0;border-radius:8px;background:transparent;cursor:pointer}.composer-attach:hover{color:var(--astra-primary-bright);background:var(--astra-primary-soft)}.composer-send{color:var(--astra-primary-bright)}.composer-send:disabled{cursor:not-allowed;opacity:.35}.composer-actions{display:flex;align-items:center;gap:12px;margin-top:9px}.composer-actions>span{display:flex;align-items:center;gap:6px;color:var(--astra-text-muted);font-size: var(--astra-font-control)}.composer-actions>span i{width:7px;height:7px;border-radius:50%;background:var(--astra-success)}.composer-actions>span i[data-status=RUNNING]{background:var(--astra-info)}.composer-actions>span i[data-status=WAIT_HUMAN],.composer-actions>span i[data-status=PENDING_CONFIRMATION],.composer-actions>span i[data-status=SUSPENDED]{background:var(--astra-warning)}.composer-actions>span i[data-status=FAILED],.composer-actions>span i[data-status=EXECUTION_ERROR],.composer-actions>span i[data-status=CANCELLED]{background:var(--astra-danger)}.composer-actions>div{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px;margin-left:auto}.action-button{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:34px;padding:0 11px;color:var(--astra-text-secondary);border:1px solid var(--astra-border);border-radius:8px;background:#fff;font-size: var(--astra-font-body);cursor:pointer}.action-button:hover{color:var(--astra-primary-bright);border-color:var(--astra-primary-border)}.action-button--primary{color:#fff;border-color:var(--astra-success);background:var(--astra-success)}.action-button--primary:hover{color:#fff}.action-button--danger{color:var(--astra-danger);border-color:color-mix(in srgb,var(--astra-danger) 38%,transparent);background:var(--astra-danger-soft)}
.task-sidebar-backdrop{display:none}.dialog-backdrop{position:fixed;inset:0;z-index:80;display:grid;place-items:center;padding:20px;background:rgba(18,32,27,.32);backdrop-filter:blur(4px)}.confirm-dialog{display:grid;width:min(100%,440px);grid-template-columns:42px minmax(0,1fr);gap:13px;padding:20px;border:1px solid var(--astra-border);border-radius:14px;background:#fff;box-shadow:0 24px 70px rgba(28,58,49,.22)}.confirm-dialog>span{display:grid;place-items:center;width:40px;height:40px;color:var(--astra-danger);border-radius:50%;background:var(--astra-danger-soft)}.confirm-dialog h3{margin:0;}.confirm-dialog p{margin:5px 0 0;color:var(--astra-text-muted);font-size: var(--astra-font-body);line-height:1.55}.confirm-dialog footer{display:flex;grid-column:1/-1;justify-content:flex-end;gap:8px;margin-top:5px}.confirm-dialog footer button{min-height:36px;padding:0 13px;color:var(--astra-text-secondary);border:1px solid var(--astra-border);border-radius:8px;background:#fff;cursor:pointer}.confirm-dialog footer .confirm-stop{display:flex;align-items:center;gap:6px;color:#fff;border-color:var(--astra-danger);background:var(--astra-danger)}.task-detail-loading{display:flex;height:calc(100dvh - 80px);align-items:center;justify-content:center;gap:9px;color:var(--astra-text-muted);background:#fff}
@keyframes typing{0%,60%,100%{transform:translateY(0);opacity:.35}30%{transform:translateY(-3px);opacity:1}}
@media(max-width:1180px){.task-shell{grid-template-columns:minmax(0,1fr) 300px}}
@media(max-width:900px){.task-shell{grid-template-columns:1fr}.sidebar-toggle{display:inline-flex}.task-sidebar{position:absolute;top:0;right:0;bottom:0;z-index:20;width:min(380px,92%);transform:translateX(102%);border-left:1px solid var(--astra-border);box-shadow:-18px 0 50px rgba(28,58,49,.16);transition:transform .2s ease}.task-sidebar.is-open{transform:translateX(0)}.task-sidebar-backdrop{position:absolute;inset:0;z-index:19;display:block;background:rgba(23,43,35,.18)}}
@media(max-width:700px){.task-detail-page{height:calc(100dvh - 80px);min-height:520px}.task-header{padding:12px 15px}.task-breadcrumb{margin-bottom:9px}.task-title-row{align-items:flex-start;flex-wrap:wrap;gap:8px}.task-title-row h2{width:calc(100% - 108px);}.task-status{padding:5px 8px;font-size: var(--astra-font-control)}.sidebar-toggle{order:3;margin-left:0}.task-meta{flex-wrap:wrap;gap:7px 10px;margin-top:9px}.task-meta>b{display:none}.conversation-list{padding:18px 13px 24px}.conversation-turn{gap:8px;margin-bottom:18px}.actor-avatar{width:34px;height:34px}.turn-content{max-width:calc(100% - 42px)}.turn-content--wide{width:calc(100% - 42px)}.message-bubble{padding:10px 12px;font-size: var(--astra-font-label)}.inquiry-options{grid-template-columns:1fr}.task-composer{padding:9px 10px}.composer-actions{align-items:flex-start;flex-direction:column}.composer-actions>div{justify-content:flex-start;margin-left:0}.action-button{min-height:32px;padding:0 9px}.jump-latest{right:14px;bottom:164px}.task-sidebar{width:100%}}
</style>
