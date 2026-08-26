<template>
  <div class="page" v-if="task" data-testid="task-detail-page">
    <div class="detail-nav"><RouterLink to="/tasks"><ArrowLeft :size="14" /> 任务中心</RouterLink><span>/</span><strong>{{ task.id }}</strong></div>
    <section class="task-hero"><div><div class="task-hero__meta"><span>{{ task.id }}</span><AstraStatusBadge :status="task.status" pulse /><span class="priority" :data-priority="task.priority">{{ task.priority }}</span></div><h2>{{ task.title }}</h2><p>{{ task.description || '暂无补充描述' }}</p></div><div class="hero-actions"><button v-if="canPause" class="button" @click="perform('pause')"><Pause :size="14" /> 暂停</button><button v-if="task.status === 'PAUSED'" class="button button--primary" @click="perform('resume')"><Play :size="14" /> 继续</button><button v-if="canHandoff" class="button button--warning" @click="perform('handoff')"><Hand :size="14" /> 转人工</button><button v-if="canCancel" class="button button--danger" @click="perform('cancel')"><Square :size="13" /> 终止</button></div></section>
    <section class="task-facts"><div><small>当前阶段</small><strong>{{ phaseLabel(task.current_phase) }}</strong></div><div><small>分配员工</small><strong>{{ task.employee_id ?? '待分配' }}</strong></div><div><small>执行环境</small><strong>{{ environmentLabel(task.execution_environment_snapshot) }}</strong></div><div><small>自动修复</small><strong>{{ task.retry_count }} / {{ task.max_retry_count }}</strong></div><div class="fact-progress"><small>整体进度 <b>{{ task.progress }}%</b></small><AstraProgress :value="task.progress" /></div></section>
    <div v-if="task.status === 'WAIT_HUMAN'" class="human-alert"><span><TriangleAlert :size="20" /></span><div><small>HUMAN INPUT REQUIRED</small><strong>任务需要人工介入</strong><p>{{ task.human_required_reason }}</p></div><RouterLink to="/interventions" class="button button--warning">进入介入中心 <ArrowRight :size="14" /></RouterLink></div>
    <section class="task-detail-grid">
      <AstraPanel class="timeline-panel" title="执行时间线" subtitle="关键状态全部由持久化 Event 渲染">
        <div class="runtime-timeline"><article v-for="(event, index) in events" :key="event.id" :class="{ current: index === events.length - 1 }"><span><component :is="eventIcon(event.event_type)" :size="13" /></span><div><small>{{ phaseLabel(event.phase) }}</small><strong>{{ event.message }}</strong><p v-if="Object.keys(event.detail).length">{{ detailText(event.detail) }}</p></div><time>{{ formatTime(event.created_at) }}</time></article><AstraEmptyState v-if="!events.length" :icon="History" title="尚无事件" description="任务开始运行后，这里会形成完整证据时间线。" /></div>
      </AstraPanel>
      <AstraPanel title="任务信息" subtitle="不可变来源信息与完成标准">
        <dl class="info-list"><div><dt>任务来源</dt><dd>{{ sourceLabel(task.source) }}</dd></div><div><dt>来源任务 ID</dt><dd>{{ task.external_task_id ?? '—' }}</dd></div><div><dt>任务类型</dt><dd>{{ task.task_type }}</dd></div><div><dt>创建时间</dt><dd>{{ formatTime(task.created_at) }}</dd></div></dl><h4 class="section-label">完成标准</h4><ul class="dod-list"><li v-for="item in task.definition_of_done" :key="item"><Circle :size="8" />{{ item }}</li><li v-if="!task.definition_of_done.length"><Circle :size="8" />等待补充完成标准</li></ul>
      </AstraPanel>
      <AstraPanel class="usage-panel" title="本任务工作消耗" subtitle="所有 Run 的真实 Token 与工具事件汇总">
        <template #action><span class="actual-data-note"><CircleCheck :size="12" /> 实际数据</span></template>
        <div class="usage-kpis"><article><small>总 Token</small><strong>{{ formatTokens(usage?.summary.total_tokens) }}</strong></article><article><small>Input</small><strong>{{ formatTokens(usage?.summary.input_tokens) }}</strong></article><article><small>Output</small><strong>{{ formatTokens(usage?.summary.output_tokens) }}</strong></article><article><small>Cache Read</small><strong>{{ formatTokens(usage?.summary.cache_read_tokens) }}</strong></article><article><small>Cache Write</small><strong>{{ formatTokens(usage?.summary.cache_write_tokens) }}</strong></article><article><small>总耗时</small><strong>{{ formatDurationSeconds(usage?.summary.duration_seconds) }}</strong></article></div>
        <dl class="usage-context"><div><dt>员工</dt><dd>{{ task.employee_id ?? '—' }}</dd></div><div><dt>环境</dt><dd>{{ environmentLabel(task.execution_environment_snapshot) }}</dd></div><div><dt>模型</dt><dd>{{ latestRun?.model_name ?? '—' }}</dd></div><div><dt>LLM 调用</dt><dd>{{ usage?.summary.llm_call_count ?? '—' }}</dd></div><div><dt>工具调用</dt><dd>{{ usage?.summary.tool_call_count ?? '—' }}</dd></div><div><dt>Run 数量</dt><dd>{{ usage?.runs ?? 0 }}</dd></div></dl>
        <div class="tool-usage-table" v-if="usage?.tools.length"><table><thead><tr><th>工具</th><th>调用</th><th>成功</th><th>失败</th><th>耗时</th></tr></thead><tbody><tr v-for="tool in usage.tools" :key="tool.tool_name"><td><strong>{{ tool.tool_name }}</strong></td><td>{{ tool.call_count }}</td><td>{{ tool.success_count }}</td><td>{{ tool.failure_count }}</td><td>{{ tool.duration_ms }} ms</td></tr></tbody></table></div>
        <p v-else class="usage-empty">OpenCode 未返回使用信息，Token 与工具数据按要求显示为 —，不做估算。</p>
      </AstraPanel>
      <AstraPanel class="log-panel" title="实时运行日志" subtitle="日志用于观察，任务状态以数据库为准">
        <template #action><label class="toggle-label"><input v-model="autoScroll" type="checkbox" /> 自动滚动</label></template>
        <div class="run-log"><div class="log-head"><span>TIME</span><span>LEVEL</span><span>PHASE</span><span>MESSAGE</span></div><div v-for="event in events" :key="event.id" class="log-line"><time>{{ new Date(event.created_at).toLocaleTimeString('zh-CN', { hour12: false }) }}</time><b :data-level="logLevel(event.event_type)">{{ logLevel(event.event_type) }}</b><span>{{ event.phase }}</span><p>{{ event.message }}</p></div><div v-if="!events.length" class="log-empty">等待运行日志...</div></div>
      </AstraPanel>
      <AstraPanel title="关联对象" subtitle="用于恢复任务现场">
        <div class="association-list"><div><Bot :size="15" /><span>数字员工</span><RouterLink v-if="task.employee_id" :to="`/employees/${task.employee_id}`">{{ task.employee_id }} <ArrowUpRight :size="12" /></RouterLink><strong v-else>待分配</strong></div><div><Server :size="15" /><span>执行环境</span><strong>{{ environmentLabel(task.execution_environment_snapshot) }}</strong></div><div><FolderOpen :size="15" /><span>Workspace</span><strong :title="task.workspace ?? ''">{{ task.workspace ?? '待创建' }}</strong></div><div><TerminalSquare :size="15" /><span>OpenCode Session</span><strong :title="task.opencode_session_id ?? ''">{{ task.opencode_session_id ?? '待创建' }}</strong></div></div>
      </AstraPanel>
      <AstraPanel class="verification-panel" title="验证结果" subtitle="独立于 OpenCode 的确定性检查">
        <template #action><AstraStatusBadge v-if="verification" :status="verification.passed ? 'PASSED' : 'FAILED'" /></template>
        <div v-if="verification" class="verification-list"><article v-for="item in verification.items" :key="item.name"><span :data-passed="item.passed"><Check v-if="item.passed" :size="13" /><X v-else :size="13" /></span><div><strong>{{ item.name }}</strong><p>{{ item.detail }}</p></div></article></div><AstraEmptyState v-else :icon="ShieldCheck" title="等待验证" description="OpenCode 执行结束后，Verifier 会运行真实命令并保存证据。" />
      </AstraPanel>
      <AstraPanel title="证据产物" subtitle="任务完成声明的可核查依据">
        <div v-if="evidence.length" class="evidence-list"><article v-for="item in evidence" :key="item.id"><span><FileCheck2 :size="16" /></span><div><strong>{{ item.name }}</strong><p>{{ item.kind }} · {{ formatBytes(item.size) }}</p></div><time>{{ formatTime(item.created_at) }}</time></article></div><AstraEmptyState v-else :icon="Archive" title="暂无证据" description="真实执行后生成 execution.log、test_result.json 与 verify_report.json。" />
      </AstraPanel>
    </section>
  </div>
</template>
<script setup lang="ts">
import { Archive, ArrowLeft, ArrowRight, ArrowUpRight, Bot, Check, CheckCircle2, Circle, CircleAlert, CircleCheck, FileCheck2, FolderOpen, Hand, History, Pause, Play, RotateCcw, Server, ShieldCheck, Square, TerminalSquare, TriangleAlert, X } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@/api/client'
import type { AstraEvent, Evidence, Run, Task, TaskUsage } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraProgress from '@/components/astra/AstraProgress.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import { environmentLabel, formatDuration, formatDurationSeconds, formatTime, formatTokens, phaseLabel, sourceLabel } from '@/utils/format'
interface Verification { passed: boolean; items: Array<{ name: string; passed: boolean; detail: string }> }
const route = useRoute(); const task = ref<Task | null>(null); const events = ref<AstraEvent[]>([]); const evidence = ref<Evidence[]>([]); const runs = ref<Run[]>([]); const usage = ref<TaskUsage | null>(null); const autoScroll = ref(true)
const latestRun = computed(() => runs.value[0] ?? null)
const verification = computed(() => { const value = task.value?.result; return value && typeof value.passed === 'boolean' && Array.isArray(value.items) ? value as unknown as Verification : null })
const canPause = computed(() => !!task.value && ['READY','CLAIMED','RUNNING','WAIT_HUMAN'].includes(task.value.status)); const canHandoff = computed(() => !!task.value && ['CLAIMED','RUNNING','VERIFYING','RETRY'].includes(task.value.status)); const canCancel = computed(() => !!task.value && !['COMPLETED','FAILED','CANCELLED'].includes(task.value.status))
async function load() { const id = String(route.params.id); [task.value, events.value, evidence.value, runs.value, usage.value] = await Promise.all([api.task(id), api.taskEvents(id), api.evidence(id), api.taskRuns(id), api.taskUsage(id)]) }
onMounted(load)
async function perform(action: string) { if (!task.value) return; const reason = action === 'handoff' ? window.prompt('请说明人工接管原因：', '需要人工业务判断') ?? undefined : undefined; if (action === 'cancel' && !window.confirm('确定终止这项任务吗？')) return; try { await api.taskAction(task.value.id, action, { reason }); await load() } catch (error) { window.alert(error instanceof Error ? error.message : '操作失败') } }
const eventIcon = (type: string) => type.includes('FAILED') || type === 'WAIT_HUMAN' ? CircleAlert : type.includes('PASSED') || type.includes('COMPLETED') ? CheckCircle2 : type.includes('RETRY') || type.includes('REPAIR') ? RotateCcw : Play
const logLevel = (type: string) => type.includes('FAILED') ? 'ERROR' : type === 'WAIT_HUMAN' ? 'WARN' : 'INFO'
const detailText = (detail: Record<string, unknown>) => Object.entries(detail).map(([key, value]) => `${key}: ${String(value)}`).join(' · ')
const formatBytes = (size: number) => size < 1024 ? `${size} B` : `${(size/1024).toFixed(1)} KB`
</script>
