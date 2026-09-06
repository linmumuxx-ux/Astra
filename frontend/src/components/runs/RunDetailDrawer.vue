<template>
  <div v-if="run" class="run-drawer-layer" role="presentation" @click.self="$emit('close')">
    <aside class="run-drawer" role="dialog" aria-modal="true" aria-label="运行详情">
      <header class="run-drawer__header">
        <div class="run-drawer__identity">
          <div class="run-drawer__id">
            <IdDisplay :value="run.id" :max-width="180" />
            <span class="run-drawer__number">第 {{ run.run_number }} 次执行</span>
          </div>
          <h2>运行详情</h2>
          <p>{{ employeeName }} · {{ environmentLabel(run.execution_environment_snapshot) }} · {{ executorLabel(run.executor_type) }}</p>
        </div>
        <div class="run-drawer__actions">
          <RouterLink class="button button--compact" :to="`/tasks/${run.task_id}`"><ArrowUpRight :size="13" /> 查看任务</RouterLink>
          <button class="run-drawer__close" type="button" aria-label="关闭运行详情" @click="$emit('close')"><X :size="17" /></button>
        </div>
      </header>

      <div class="run-drawer__body">
        <section class="run-drawer__statusbar" :data-state="meta.level">
          <RunStatusBadge :status="run.status" :show-detail="true" />
          <span v-if="isFailed">
            <CircleX :size="13" /> {{ meta.detail || '执行异常' }}
            <code v-if="failureCode">HTTP {{ failureCode }}</code>
          </span>
          <span v-else class="run-drawer__muted">{{ meta.label }}</span>
        </section>

        <section class="drawer-section">
          <h3>执行概览</h3>
          <dl class="drawer-facts">
            <div><dt>Run ID</dt><dd><IdDisplay :value="run.id" :max-width="160" /></dd></div>
            <div><dt>Task ID</dt><dd><RouterLink class="fact-link" :to="`/tasks/${run.task_id}`">{{ run.task_id }} <ArrowUpRight :size="11" /></RouterLink></dd></div>
            <div><dt>第几次执行</dt><dd>{{ run.run_number }} 次</dd></div>
            <div><dt>数字员工</dt><dd>{{ employeeName }}</dd></div>
            <div><dt>当前状态</dt><dd><RunStatusBadge :status="run.status" :show-detail="false" /></dd></div>
            <div><dt>模型</dt><dd>{{ run.model_name || '—' }}</dd></div>
            <div><dt>工作空间</dt><dd class="wrap">{{ workspace }}</dd></div>
            <div><dt>执行会话</dt><dd><IdDisplay :value="run.opencode_session_id || '—'" :copyable="Boolean(run.opencode_session_id)" :max-width="130" /></dd></div>
          </dl>
        </section>

        <section class="drawer-section">
          <h3>时间信息</h3>
          <dl class="drawer-facts">
            <div><dt>创建时间</dt><dd>{{ ts(run.created_at) }}</dd></div>
            <div><dt>入队时间</dt><dd>{{ ts(run.queued_at) }}</dd></div>
            <div><dt>领取时间</dt><dd>{{ ts(run.dispatched_at) }}</dd></div>
            <div><dt>开始时间</dt><dd>{{ ts(run.started_at) }}</dd></div>
            <div><dt>结束时间</dt><dd>{{ ts(run.finished_at) }}</dd></div>
            <div><dt>总耗时</dt><dd>{{ timer }}</dd></div>
          </dl>
        </section>

        <section class="drawer-section">
          <h3>执行消耗</h3>
          <div class="run-costs">
            <article><small>Token</small><strong>{{ formatTokens(run.total_tokens) }}</strong><span>输入 {{ formatTokens(run.input_tokens) }} / 输出 {{ formatTokens(run.output_tokens) }}</span></article>
            <article><small>工具调用</small><strong>{{ run.tool_call_count ?? '—' }}</strong><span>{{ run.llm_call_count ?? '—' }} 次模型调用</span></article>
            <article class="span"><small>执行会话</small><strong class="session"><IdDisplay :value="run.opencode_session_id || '—'" :copyable="Boolean(run.opencode_session_id)" :max-width="160" /></strong><span>{{ worker }} {{ worker ? '执行' : '无活动 Worker' }}</span></article>
          </div>
        </section>

        <section v-if="isFailed" class="drawer-section">
          <h3>异常信息</h3>
          <ErrorDetail
            :title="errorSummary"
            :label="errorStage"
            :description="errorDescription"
            :code="failureCode"
            :raw-error="rawError"
          />
        </section>

        <section v-if="toolRows.length" class="drawer-section">
          <h3>工具调用明细</h3>
          <div class="tool-list">
            <div v-for="tool in toolRows" :key="tool.tool_name" class="tool-row">
              <span class="tool-name">{{ tool.tool_name }}</span>
              <span class="tool-calls">{{ tool.call_count }} 次</span>
              <span class="tool-ok">成功 {{ tool.success_count }}</span>
              <span class="tool-fail">失败 {{ tool.failure_count }}</span>
              <span class="tool-duration">{{ formatMilliseconds(tool.duration_ms) }}</span>
            </div>
          </div>
        </section>

        <section class="drawer-section">
          <h3>状态轨迹</h3>
          <ol class="run-timeline">
            <li v-for="point in timeline" :key="point.key" :data-tone="point.tone">
              <span class="run-timeline__dot" />
              <div><time>{{ point.time }}</time><strong>{{ point.title }}</strong></div>
              <small v-if="point.sub">{{ point.sub }}</small>
            </li>
            <li v-if="!timeline.length"><span class="timeline-empty">暂无状态事件记录</span></li>
          </ol>
        </section>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowUpRight, CircleX, X } from 'lucide-vue-next'
import type { AstraEvent, Run, RunUsage } from '@/api/types'
import ErrorDetail from '@/components/astra/ErrorDetail.vue'
import IdDisplay from '@/components/astra/IdDisplay.vue'
import RunStatusBadge from '@/components/runs/RunStatusBadge.vue'
import { runUnifiedStatus, type RunTone } from '@/features/runs/unifiedStatus'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, environmentLabel, executorLabel, formatDuration, formatMilliseconds, formatTokens, formatTime } from '@/utils/format'

const props = defineProps<{ run: Run; usage?: RunUsage | null; events?: AstraEvent[] }>()
defineEmits<{ (e: 'close'): void }>()

const store = useAstraStore()
const meta = computed(() => runUnifiedStatus(props.run.status))
const isFailed = computed(() => ['FAILED', 'BLOCKED', 'TIMEOUT', 'LOST'].includes(props.run.status))
const employeeName = computed(() => employeeDisplayName(store.employees.find((item) => item.id === props.run.employee_id)?.name ?? props.run.employee_id))
const workspace = computed(() => props.run.execution_environment_snapshot.workspace_root ?? '—')
const worker = computed(() => props.run.worker_id ?? '')
const timer = computed(() => formatDuration(props.run.started_at, props.run.finished_at))
const ts = (value: string | null | undefined) => formatTime(value)
const failureContext = computed(() => {
  const failureEvents = (props.events ?? []).filter((event) => /err|fail|失|异常|超时|丢失/.test(`${event.event_type}${event.message}`))
  const detail = props.run.execution_environment_snapshot?.status_detail as Record<string, unknown> | undefined
  const last = failureEvents.at(-1)
  return {
    stage: props.run.executor_status ?? (last ? last.phase : null) ?? '执行阶段',
    summary: isFailed.value ? (last?.message || props.run.failure_type || '执行失败') : null,
    raw: [last?.message && cleanMessage(last), detail?.message && String(detail.message)].filter(Boolean).join('\n') || null,
  }
})
function cleanMessage(event: AstraEvent) {
  const detail = event.detail as Record<string, unknown> | undefined
  const raw = detail?.error || detail?.detail || detail?.message
  return typeof raw === 'string' ? raw : `${event.message}${detail ? `\n${JSON.stringify(detail, null, 2)}` : ''}`
}
const errorStage = computed(() => failureContext.value.stage)
const errorSummary = computed(() => failureContext.value.summary ?? '执行失败')
const errorDescription = computed(() => (props.run.failure_type ? `失败类型：${props.run.failure_type}` : null) || null)
const failureCode = computed(() => props.run.exit_code)
const rawError = computed(() => failureContext.value.raw)
const toolRows = computed(() => props.usage?.tools ?? [])

function eventTone(event: AstraEvent): RunTone {
  const detail = event.detail as Record<string, unknown> | undefined
  const status = typeof detail?.status === 'string' ? detail.status : null
  if (event.event_type === 'RUN_STATUS' && status) {
    if (['FAILED', 'BLOCKED', 'TIMEOUT', 'LOST'].includes(status)) return 'danger'
    if (['COMPLETED', 'PASSED'].includes(status)) return 'success'
    if (['WAITING_INPUT', 'SUSPENDED'].includes(status)) return 'warning'
    if (['RUNNING', 'STARTING'].includes(status)) return 'info'
    return 'neutral'
  }
  if (/err|fail|失|异常|超时/.test(`${event.event_type}${event.message}`)) return 'danger'
  if (/wait|input|人工/.test(event.message)) return 'warning'
  return 'neutral'
}
function eventSub(event: AstraEvent): string {
  const detail = event.detail as Record<string, unknown> | undefined
  if (event.event_type === 'RUN_STATUS' && typeof detail?.status === 'string') return detail.status
  return event.event_type
}

interface TimelinePoint { key: string; time: string; title: string; sub?: string; tone: RunTone }
const timeline = computed<TimelinePoint[]>(() => {
  const points: TimelinePoint[] = []
  const push = (key: string, value: string | null | undefined, title: string, tone: RunTone = 'neutral', sub?: string) => {
    if (!value) return
    points.push({ key, time: formatTime(value), title, tone, sub })
  }
  push('created', props.run.created_at, 'Run 创建', 'neutral')
  push('queued', props.run.queued_at, '加入执行队列', 'neutral', '等待执行')
  push('dispatched', props.run.dispatched_at, '已领取 / 派发', 'info', '开始启动')
  push('started', props.run.started_at, '开始执行', 'info', props.run.worker_id ? `Worker ${props.run.worker_id}` : undefined)
  for (const event of props.events ?? []) {
    const tone = eventTone(event)
    points.push({ key: `ev-${event.id}`, time: formatTime(event.created_at), title: event.message, tone, sub: eventSub(event) })
  }
  push('finished', props.run.finished_at, '执行结束', meta.value.tone, meta.value.label)
  return points
})
</script>

<style scoped>
.run-drawer-layer { position: fixed; inset: 0; z-index: 800; display: flex; justify-content: flex-end; background: rgba(24, 45, 39, 0.22); backdrop-filter: blur(2px); }
.run-drawer { display: grid; grid-template-rows: auto minmax(0, 1fr); width: min(640px, 100%); height: 100%; border-left: 1px solid var(--astra-border); background: #fff; box-shadow: -18px 0 50px rgba(33, 60, 52, 0.18); animation: run-drawer-in 0.2s ease-out; }
.run-drawer__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; min-height: 104px; padding: 18px 22px; border-bottom: 1px solid var(--astra-border); }
.run-drawer__identity { min-width: 0; }
.run-drawer__id { display: flex; align-items: center; gap: 9px; }
.run-drawer__number { color: var(--astra-primary); font-size: var(--astra-font-helper); font-weight: 700; letter-spacing: 0.06em; }
.run-drawer__identity h2 { margin: 5px 0 2px; font: 700 var(--astra-font-title) var(--astra-font-display); }
.run-drawer__identity p { margin: 0; color: var(--astra-text-secondary); }
.run-drawer__actions { display: flex; align-items: center; gap: 9px; flex: none; }
.run-drawer__close { display: grid; place-items: center; width: 34px; height: 34px; color: var(--astra-text-muted); border: 1px solid var(--astra-border); border-radius: 9px; background: var(--astra-bg-panel); cursor: pointer; }
.run-drawer__close:hover { color: var(--astra-primary); border-color: var(--astra-border-hover); }
.run-drawer__body { min-height: 0; overflow-y: auto; padding: 18px 22px 30px; }
.run-drawer__statusbar { display: flex; align-items: center; gap: 9px; padding: 11px 13px; border: 1px solid var(--astra-primary-border); border-radius: 10px; background: var(--astra-primary-soft); }
.run-drawer__statusbar[data-state='FAILED'] { border-color: rgba(255, 111, 125, 0.3); background: var(--astra-danger-soft); }
.run-drawer__statusbar > span { display: inline-flex; align-items: center; gap: 6px; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.run-drawer__statusbar code { padding: 1px 6px; color: var(--astra-danger); border-radius: 5px; background: rgba(255, 111, 125, 0.13); font: 700 var(--astra-font-helper) ui-monospace, monospace; }
.run-drawer__muted { color: var(--astra-text-muted) !important; }
.drawer-section { margin-top: 22px; }
.drawer-section h3 { margin: 0 0 10px; font: 700 var(--astra-font-label) var(--astra-font-display); color: var(--astra-text-primary); }
.drawer-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; margin: 0; }
.drawer-facts > div { min-width: 0; padding: 10px 12px; border-radius: 9px; background: #f4f8f6; }
.drawer-facts dt { color: var(--astra-text-muted); font-size: var(--astra-font-body); }
.drawer-facts dd { overflow: hidden; margin: 4px 0 0; color: var(--astra-text-primary); font-size: var(--astra-font-control); text-overflow: ellipsis; white-space: nowrap; }
.drawer-facts dd.wrap { white-space: normal; word-break: break-word; }
.fact-link { display: inline-flex; align-items: center; gap: 4px; color: var(--astra-primary-bright); font-family: ui-monospace, monospace; }
.run-costs { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.run-costs article { display: grid; padding: 11px 12px; border: 1px solid var(--astra-border); border-radius: 9px; background: #fafcfb; }
.run-costs article.span { grid-column: 1 / -1; }
.run-costs small { color: var(--astra-text-muted); font-size: var(--astra-font-body); }
.run-costs strong { margin: 3px 0 1px; font: 640 19px var(--astra-font-display); }
.run-costs strong.session { font: var(--astra-font-control) ui-monospace, monospace; font-weight: 600; }
.run-costs span { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.tool-list { display: grid; gap: 5px; }
.tool-row { display: grid; grid-template-columns: minmax(0, 1fr) 64px 52px 52px 72px; gap: 8px; align-items: center; padding: 7px 10px; border: 1px solid var(--astra-border); border-radius: 8px; background: #fafcfb; font-size: var(--astra-font-helper); }
.tool-name { overflow: hidden; color: var(--astra-text-primary); font-family: ui-monospace, monospace; text-overflow: ellipsis; white-space: nowrap; }
.tool-calls, .tool-ok, .tool-fail, .tool-duration { text-align: right; color: var(--astra-text-muted); white-space: nowrap; }
.tool-ok { color: var(--astra-success); }
.tool-fail { color: var(--astra-danger); }
.run-timeline { position: relative; display: grid; gap: 0; margin: 0; padding-left: 18px; list-style: none; }.run-timeline::before { content: ''; position: absolute; top: 8px; bottom: 8px; left: 5px; width: 1px; background: var(--astra-border); }
.run-timeline li { position: relative; display: grid; grid-template-columns: minmax(64px, auto) minmax(0, 1fr); gap: 10px; padding: 9px 0; }
.run-timeline__dot { position: absolute; left: -18px; top: 13px; width: 11px; height: 11px; border-radius: 50%; border: 2px solid #fff; box-shadow: 0 0 0 2px var(--tone); background: var(--tone); }
.run-timeline__dot { --tone: var(--astra-border-hover); }
.run-timeline li[data-tone='danger'] .run-timeline__dot { --tone: var(--astra-danger); }
.run-timeline li[data-tone='warning'] .run-timeline__dot { --tone: var(--astra-warning); }
.run-timeline li[data-tone='info'] .run-timeline__dot { --tone: var(--astra-info); }
.run-timeline li[data-tone='success'] .run-timeline__dot { --tone: var(--astra-success); }
.run-timeline li > div { display: grid; gap: 1px; }
.run-timeline time { color: var(--astra-text-muted); font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.run-timeline strong { color: var(--astra-text-primary); font-size: var(--astra-font-control); font-weight: 500; }
.run-timeline small { color: var(--astra-text-muted); font-size: var(--astra-font-helper); font-family: ui-monospace, monospace; }
.timeline-empty { color: var(--astra-text-muted); font-size: var(--astra-font-helper); padding: 12px 0; }
@keyframes run-drawer-in { from { transform: translateX(30px); opacity: 0.5; } }
@media (max-width: 600px) {
  .run-drawer__header { padding-inline: 16px; }
  .run-drawer__body { padding-inline: 16px; }
  .drawer-facts, .run-costs { grid-template-columns: 1fr; }
  .run-costs article.span { grid-column: auto; }
}
</style>
