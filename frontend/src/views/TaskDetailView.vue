<template>
  <div v-if="task" class="page" data-testid="task-detail-page">
    <div class="detail-nav"><RouterLink to="/tasks"><ArrowLeft :size="14" /> 任务中心</RouterLink><span>/</span><strong>{{ task.id }}</strong></div>
    <section class="task-hero">
      <div class="task-hero__copy"><div><span class="priority" :data-priority="task.priority">{{ priorityLabel(task.priority) }}</span><span>{{ taskTypeLabel(task.task_type) }} · {{ categoryName }}</span><AstraStatusBadge :status="task.status" :pulse="task.status === 'RUNNING'" /></div><h2>{{ task.title }}</h2><p>{{ task.current_progress }}</p></div>
      <div class="hero-actions"><button v-if="task.status === 'RUNNING'" class="button" @click="perform('pause')"><Pause :size="14" /> 安全挂起</button><button v-if="task.status === 'RUNNING'" class="button" @click="perform('handoff')"><Hand :size="14" /> 请求人工</button><button v-if="['WAIT_HUMAN','SUSPENDED'].includes(task.status)" class="button button--primary" @click="perform('resume')"><Play :size="14" /> 继续任务</button><button v-if="task.status === 'EXECUTION_ERROR'" class="button button--primary" @click="perform('recover')"><RefreshCw :size="14" /> 恢复执行</button><button v-if="task.status === 'PENDING_CONFIRMATION'" class="button" @click="reject"><X :size="14" /> 退回继续</button><button v-if="task.status === 'PENDING_CONFIRMATION'" class="button button--primary" @click="perform('confirm')"><Check :size="14" /> 确认完成</button><button v-if="canCancel" class="button button--danger" @click="perform('cancel')"><Square :size="14" /> 取消任务</button></div>
    </section>

    <section class="task-facts task-facts--v03">
      <div><span>执行员工</span><strong>{{ employeeName }}</strong></div><div><span>完成策略</span><strong>{{ task.completion_policy === 'MANUAL_CONFIRM' ? '人工确认' : '自动完成' }}</strong></div><div><span>创建时间</span><strong>{{ formatTime(task.created_at) }}</strong></div><div><span>最后活动</span><strong>{{ formatTime(task.last_activity_at) }}</strong></div><div><span>完成时间</span><strong>{{ formatTime(task.finished_at) }}</strong></div><div><span>运行时长</span><strong>{{ formatTaskDuration(task) }}</strong></div>
    </section>

    <div v-if="task.status === 'WAIT_HUMAN' && task.human_intervention" class="human-alert human-alert--detail"><TriangleAlert :size="20" /><div><strong>等待人工处理</strong><p>{{ task.human_intervention.blocking_reason }}</p><small>已完成：{{ task.human_intervention.completed_work || '—' }}<br />需要人工：{{ task.human_intervention.requested_input }}</small></div><RouterLink class="button button--primary" to="/interventions">处理</RouterLink></div>
    <div v-if="task.inactivity_alert" class="human-alert human-alert--detail"><CircleAlert :size="20" /><div><strong>长时间无新活动</strong><p>这只是观察提示，不会改变任务状态或判定失败。</p></div><RouterLink class="button" to="/interventions">前往待处理</RouterLink></div>
    <div v-if="task.status === 'EXECUTION_ERROR'" class="human-alert human-alert--detail"><TriangleAlert :size="20" /><div><strong>执行异常，工作现场已保留</strong><p>{{ String(task.execution_error?.reason ?? '请检查 OpenCode 或远程环境') }}</p></div><button class="button button--primary" @click="perform('recover')">恢复执行</button></div>

    <section class="task-detail-grid task-detail-grid--v03">
      <AstraPanel title="任务描述" subtitle="背景、目标与必要上下文"><p class="description-copy">{{ task.description }}</p><div v-if="task.attachments.length" class="attachment-list"><strong>附件</strong><a v-for="item in task.attachments" :key="String(item.name)" :href="attachmentHref(item)" :download="String(item.name ?? '附件')"><Paperclip :size="13" /> {{ item.name }}</a></div></AstraPanel>

      <AstraPanel title="验收标准" subtitle="数字员工逐项提交验收情况">
        <div class="acceptance-list"><article v-for="criterion in task.acceptance_criteria" :key="criterion.id"><span :data-status="acceptanceResult(criterion.id)?.status ?? 'PENDING'"><Check v-if="acceptanceResult(criterion.id)?.status === 'SATISFIED'" :size="14" /><X v-else-if="acceptanceResult(criterion.id)?.status === 'UNSATISFIED'" :size="14" /><CircleHelp v-else :size="14" /></span><div><strong>{{ criterion.id }} · {{ criterion.content }}</strong><p v-if="acceptanceResult(criterion.id)">{{ acceptanceStatusLabel(acceptanceResult(criterion.id)!.status) }} · {{ acceptanceResult(criterion.id)!.description || '无补充说明' }}</p><small v-if="acceptanceResult(criterion.id)?.evidence.length">证据：{{ acceptanceResult(criterion.id)!.evidence.join('、') }}</small><p v-else-if="!task.result">等待员工提交结果</p></div></article></div>
      </AstraPanel>

      <AstraPanel class="timeline-panel" title="工作进展" subtitle="面向管理者的可读时间线">
        <div class="runtime-timeline"><article v-for="event in workEvents" :key="event.id"><time>{{ formatTime(event.created_at) }}</time><span><component :is="eventIcon(event.event_type)" :size="13" /></span><div><strong>{{ event.message }}</strong><p>{{ event.employee_id ?? '平台' }}</p></div></article><AstraEmptyState v-if="!workEvents.length" :icon="History" title="暂无工作进展" description="OpenCode 产生可观察信息后会显示在这里。" /></div>
      </AstraPanel>

      <AstraPanel title="详细操作" subtitle="OpenCode 工具、模型用量与运行事件"><div class="operation-list"><details v-for="event in operationEvents" :key="event.id"><summary><span>{{ event.message }}</span><time>{{ formatTime(event.created_at) }}</time></summary><pre>{{ JSON.stringify(event.detail, null, 2) }}</pre></details><AstraEmptyState v-if="!operationEvents.length" :icon="TerminalSquare" title="暂无详细操作" description="工具调用与用量事件会保留在这里。" /></div></AstraPanel>

      <AstraPanel title="处理结果" subtitle="由数字员工提交">
        <div v-if="task.result" class="work-result"><p>{{ task.result.summary }}</p><dl><div v-if="task.result.changes.length"><dt>主要修改</dt><dd>{{ task.result.changes.join('；') }}</dd></div><div v-if="task.result.files.length"><dt>关联文件</dt><dd>{{ task.result.files.join('、') }}</dd></div><div v-if="task.result.commits.length"><dt>关联提交</dt><dd>{{ task.result.commits.join('、') }}</dd></div><div v-if="task.result.logs.length"><dt>日志</dt><dd>{{ task.result.logs.join('、') }}</dd></div><div v-if="task.result.attachments.length"><dt>结果附件</dt><dd>{{ task.result.attachments.join('、') }}</dd></div><div v-if="Object.keys(task.result.other).length"><dt>其他产物</dt><dd>{{ JSON.stringify(task.result.other) }}</dd></div></dl></div>
        <AstraEmptyState v-else :icon="FileText" title="暂无处理结果" description="数字员工完成或终止工作后会提交结果说明。" />
      </AstraPanel>

      <AstraPanel class="usage-panel" title="工作消耗" subtitle="Token 与工具数据来自 OpenCode 实际执行">
        <div class="usage-kpis"><article><small>Input</small><strong>{{ formatTokens(usage?.summary.input_tokens) }}</strong></article><article><small>Output</small><strong>{{ formatTokens(usage?.summary.output_tokens) }}</strong></article><article><small>Cache Read</small><strong>{{ formatTokens(usage?.summary.cache_read_tokens) }}</strong></article><article><small>Cache Write</small><strong>{{ formatTokens(usage?.summary.cache_write_tokens) }}</strong></article><article><small>Total Token</small><strong>{{ formatTokens(usage?.summary.total_tokens) }}</strong></article><article><small>工具调用</small><strong>{{ usage?.summary.tool_call_count ?? '—' }}</strong></article></div>
        <div v-if="usage?.tools.length" class="tool-usage-table"><table><thead><tr><th>工具</th><th>调用</th><th>成功</th><th>失败</th><th>耗时</th></tr></thead><tbody><tr v-for="tool in usage.tools" :key="tool.tool_name"><td>{{ tool.tool_name }}</td><td>{{ tool.call_count }}</td><td>{{ tool.success_count }}</td><td>{{ tool.failure_count }}</td><td>{{ tool.duration_ms }} ms</td></tr></tbody></table></div>
        <p v-else class="usage-empty">尚无 OpenCode 消耗数据；任务未完成、已取消或等待人工时，已产生的数据仍会保留。</p>
      </AstraPanel>

      <AstraPanel title="关联信息" subtitle="任务、Session 与运行记录"><dl class="association-list"><div><TerminalSquare :size="14" /><span>OpenCode Session</span><strong>{{ task.opencode_session_id ?? '尚未创建' }}</strong></div><div><Server :size="14" /><span>工作环境</span><strong>{{ environmentLabel(task.execution_environment_snapshot) }}</strong></div><div><History :size="14" /><span>运行记录</span><RouterLink v-if="latestRun" :to="`/runs/${latestRun.id}`">{{ latestRun.id }} <ArrowUpRight :size="12" /></RouterLink><strong v-else>尚无记录</strong></div></dl><div v-if="evidence.length" class="evidence-list"><article v-for="item in evidence" :key="item.id"><span><Archive :size="15" /></span><div><strong>{{ item.name }}</strong><p>{{ item.kind }}</p></div><time>{{ formatTime(item.created_at) }}</time></article></div></AstraPanel>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Archive, ArrowLeft, ArrowUpRight, Check, CheckCircle2, CircleAlert, CircleHelp, FileText, Hand, History, Paperclip, Pause, Play, RefreshCw, Server, Square, TerminalSquare, TriangleAlert, X } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@/api/client'
import type { AcceptanceResult, AstraEvent, Evidence, Run, Task, TaskUsage } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
import { acceptanceStatusLabel, environmentLabel, formatTaskDuration, formatTime, formatTokens, priorityLabel, taskTypeLabel } from '@/utils/format'

const route = useRoute(); const store = useAstraStore(); const task = ref<Task | null>(null); const events = ref<AstraEvent[]>([]); const evidence = ref<Evidence[]>([]); const runs = ref<Run[]>([]); const usage = ref<TaskUsage | null>(null)
const latestRun = computed(() => runs.value[0] ?? null)
const canCancel = computed(() => !!task.value && ['READY', 'RUNNING', 'WAIT_HUMAN', 'SUSPENDED', 'PENDING_CONFIRMATION', 'EXECUTION_ERROR'].includes(task.value.status))
const workEvents = computed(() => events.value.filter((event) => event.phase !== 'operation'))
const operationEvents = computed(() => events.value.filter((event) => event.phase === 'operation'))
const categoryName = computed(() => store.categories.find((item) => item.id === task.value?.category_id)?.name ?? '—')
const employeeName = computed(() => store.employees.find((item) => item.id === task.value?.employee_id)?.name ?? '自动分配')
const acceptanceResult = (id: string): AcceptanceResult | undefined => task.value?.result?.acceptance_results.find((item) => item.criterion_id === id)
const attachmentHref = (item: Record<string, unknown>) => String(item.content ?? item.url ?? '#')
async function load() { const id = String(route.params.id); await store.refresh(); [task.value, events.value, evidence.value, runs.value, usage.value] = await Promise.all([api.task(id), api.taskEvents(id), api.evidence(id), api.taskRuns(id), api.taskUsage(id)]) }
onMounted(load)
async function perform(action: string) { if (!task.value) return; let note: string | undefined; let reason: string | undefined; if (action === 'handoff') { reason = window.prompt('请说明需要人工介入的原因：') ?? undefined; if (!reason) return } if (action === 'resume') note = window.prompt('请补充给数字员工的信息：') ?? undefined; if (action === 'cancel' && !window.confirm('确定取消这项任务吗？')) return; await api.taskAction(task.value.id, action, { reason, note }); await load() }
async function reject() { if (!task.value) return; const feedback = window.prompt('请输入退回原因与补充要求：'); if (!feedback) return; await api.taskAction(task.value.id, 'reject', { feedback }); await load() }
const eventIcon = (type: string) => type === 'WAIT_HUMAN' ? CircleAlert : type === 'TASK_COMPLETED' ? CheckCircle2 : Play
</script>
