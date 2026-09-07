<template>
  <aside class="task-sidebar" aria-label="任务信息侧栏">
    <header class="task-sidebar__mobile-head">
      <strong>任务信息</strong>
      <button type="button" aria-label="关闭任务信息" @click="$emit('close')"><X :size="18" /></button>
    </header>

    <section class="task-sidebar__section task-summary">
      <h3>任务概要</h3>
      <dl>
        <div>
          <dt>任务 ID</dt>
          <dd class="task-id"><span>{{ task.id }}</span><button type="button" :aria-label="copied ? '已复制任务 ID' : '复制任务 ID'" @click="copyTaskId"><Check v-if="copied" :size="14" /><Copy v-else :size="14" /></button></dd>
        </div>
        <div><dt>任务来源</dt><dd>{{ task.source }}</dd></div>
        <div><dt>任务目标</dt><dd>{{ task.title }}</dd></div>
        <div><dt>任务描述</dt><dd :class="{ 'is-clamped': !summaryExpanded }">{{ task.description }}</dd></div>
      </dl>
      <button v-if="task.description.length > 80" class="summary-toggle" type="button" :aria-expanded="summaryExpanded" @click="summaryExpanded = !summaryExpanded">
        {{ summaryExpanded ? '收起内容' : '查看更多' }} <ChevronDown :class="{ 'is-open': summaryExpanded }" :size="15" />
      </button>
    </section>

    <section class="task-sidebar__section collaborators">
      <h3>协作成员</h3>
      <p class="section-label">数字员工</p>
      <article class="collaborator collaborator--employee">
        <span class="collaborator__icon"><Bot :size="17" /></span>
        <span><strong>{{ employeeName }}</strong><small>{{ employeeRole }}</small></span>
        <b :data-status="task.status"><i />{{ taskStatusLabel }}</b>
      </article>
      <p class="section-label">子代理 <span v-if="subtasks.length">({{ subtasks.length }})</span></p>
      <div v-if="subtasks.length" class="subagent-list">
        <article v-for="subtask in subtasks" :key="subtask.id" class="collaborator collaborator--subagent">
          <span class="collaborator__icon"><Boxes :size="16" /></span>
          <span><strong>{{ subtask.name }}</strong><small>{{ subtask.title }}</small></span>
          <b :data-status="subtask.status"><i />{{ subtask.statusLabel }}</b>
        </article>
      </div>
      <p v-else class="sidebar-empty">当前由数字员工独立处理</p>
    </section>

    <section class="task-sidebar__section outputs">
      <h3>产出与验收</h3>
      <p class="section-label">产出文件</p>
      <div v-if="artifacts.length" class="artifact-list">
        <article v-for="artifact in artifacts" :key="artifact.key">
          <span class="artifact-icon"><FileText :size="16" /></span>
          <span><strong>{{ artifact.name }}</strong><small :title="artifact.path">{{ artifact.path }}</small></span>
          <b>{{ formatFileSize(artifact.size) }}</b>
        </article>
      </div>
      <p v-else class="sidebar-empty">暂无产出</p>

      <div v-if="task.acceptance_criteria.length" class="acceptance-summary">
        <div class="acceptance-summary__title"><span>验收标准</span><strong>{{ passedAcceptance }}/{{ task.acceptance_criteria.length }} {{ acceptanceSummaryLabel }}</strong></div>
        <article v-for="criterion in task.acceptance_criteria" :key="criterion.id">
          <CheckCircle2 v-if="acceptanceResult(criterion.id)?.status === 'SATISFIED'" :size="16" />
          <CircleX v-else-if="acceptanceResult(criterion.id)?.status === 'UNSATISFIED'" :size="16" />
          <Circle v-else :size="16" />
          <span><strong>{{ criterion.content }}</strong><small v-if="acceptanceResult(criterion.id)?.description">{{ acceptanceResult(criterion.id)?.description }}</small></span>
        </article>
      </div>

      <RouterLink v-if="latestRunId" class="run-detail-link" :to="`/runs/${latestRunId}`">查看运行详情 <ChevronRight :size="16" /></RouterLink>
      <span v-else class="run-detail-link is-disabled">暂无运行详情</span>
    </section>
  </aside>
</template>

<script setup lang="ts">
import { Bot, Boxes, Check, CheckCircle2, ChevronDown, ChevronRight, Circle, CircleX, Copy, FileText, X } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import type { AcceptanceResult, Task } from '@/api/types'
import type { ConversationSubtask } from './conversation'

export interface SidebarArtifact {
  key: string
  name: string
  path: string
  size: number | null
}

const props = defineProps<{
  task: Task
  employeeName: string
  employeeRole: string
  taskStatusLabel: string
  subtasks: ConversationSubtask[]
  artifacts: SidebarArtifact[]
  latestRunId: string | null
}>()

defineEmits<{ close: [] }>()

const summaryExpanded = ref(false)
const copied = ref(false)
let copiedTimer = 0
const passedAcceptance = computed(() => props.task.result?.acceptance_results.filter((item) => item.status === 'SATISFIED').length ?? 0)
const acceptanceSummaryLabel = computed(() => {
  if (!props.task.result) return '待验证'
  if (passedAcceptance.value === props.task.acceptance_criteria.length) return '通过'
  return '完成'
})

const acceptanceResult = (criterionId: string): AcceptanceResult | undefined => props.task.result?.acceptance_results.find((item) => item.criterion_id === criterionId)

async function copyTaskId() {
  try {
    await navigator.clipboard.writeText(props.task.id)
    copied.value = true
    window.clearTimeout(copiedTimer)
    copiedTimer = window.setTimeout(() => { copied.value = false }, 1400)
  } catch {
    copied.value = false
  }
}

function formatFileSize(size: number | null): string {
  if (size === null || size < 0) return '—'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
</script>

<style scoped>
.task-sidebar{height:100%;overflow-y:auto;overscroll-behavior:contain;border-left:1px solid var(--astra-border);background:#fbfdfc;scrollbar-gutter:stable}
.task-sidebar__mobile-head{display:none}.task-sidebar__section{padding:24px 22px;border-bottom:1px solid var(--astra-border)}.task-sidebar__section:last-child{border-bottom:0}.task-sidebar h3{margin:0 0 20px;line-height: normal;}
.task-summary dl{display:grid;gap:17px;margin:0}.task-summary dl>div{display:grid;grid-template-columns:78px minmax(0,1fr);gap:12px}.task-summary dt{color:var(--astra-text-muted);font-size: var(--astra-font-body)}.task-summary dd{min-width:0;margin:0;color:var(--astra-text-secondary);font-size: var(--astra-font-body);line-height:1.55;word-break:break-word}.task-summary dd.is-clamped{display:-webkit-box;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:3}.task-id{display:flex;align-items:center;justify-content:space-between;gap:6px}.task-id span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.task-id button{display:grid;flex:none;place-items:center;width:26px;height:26px;color:var(--astra-text-muted);border:0;border-radius:6px;background:transparent;cursor:pointer}.task-id button:hover{color:var(--astra-primary);background:var(--astra-primary-soft)}
.summary-toggle{display:flex;align-items:center;gap:5px;margin:15px auto 0;color:var(--astra-primary-bright);border:0;background:transparent;font-size: var(--astra-font-body);cursor:pointer}.summary-toggle svg{transition:transform .18s}.summary-toggle svg.is-open{transform:rotate(180deg)}
.section-label{margin:0 0 8px;color:var(--astra-text-muted);font-size: var(--astra-font-body)}.section-label:not(:first-of-type){margin-top:18px}.collaborator{display:grid;grid-template-columns:34px minmax(0,1fr) auto;align-items:center;gap:10px;min-height:42px}.collaborator__icon{display:grid;place-items:center;width:32px;height:32px;color:var(--astra-primary-bright);border-radius:50%;background:var(--astra-primary-soft)}.collaborator>span:nth-child(2){display:grid;min-width:0}.collaborator strong{overflow:hidden;font-size: var(--astra-font-label);text-overflow:ellipsis;white-space:nowrap}.collaborator small{overflow:hidden;margin-top:1px;color:var(--astra-text-muted);font-size: var(--astra-font-control);text-overflow:ellipsis;white-space:nowrap}.collaborator>b{display:flex;align-items:center;gap:6px;color:var(--astra-info);font-size: var(--astra-font-control);font-weight: var(--astra-weight-regular);white-space:nowrap}.collaborator>b i{width:7px;height:7px;border-radius:50%;background:currentColor}.collaborator>b[data-status=COMPLETED],.collaborator>b[data-status=completed]{color:var(--astra-success)}.collaborator>b[data-status=WAIT_HUMAN],.collaborator>b[data-status=PENDING_CONFIRMATION],.collaborator>b[data-status=SUSPENDED]{color:var(--astra-warning)}.collaborator>b[data-status=FAILED],.collaborator>b[data-status=EXECUTION_ERROR],.collaborator>b[data-status=CANCELLED],.collaborator>b[data-status=failed]{color:var(--astra-danger)}.subagent-list{display:grid;gap:9px;padding-left:12px;border-left:1px solid #dce8e2}.sidebar-empty{margin:0;padding:9px 10px;color:var(--astra-text-muted);border-radius:7px;background:#f4f8f6;font-size: var(--astra-font-body)}
.artifact-list{display:grid;gap:9px}.artifact-list article{display:grid;grid-template-columns:32px minmax(0,1fr) auto;align-items:center;gap:9px}.artifact-icon{display:grid;place-items:center;width:30px;height:30px;color:var(--astra-info);border-radius:8px;background:color-mix(in srgb,var(--astra-info) 9%,transparent)}.artifact-list article>span:nth-child(2){display:grid;min-width:0}.artifact-list strong{overflow:hidden;font-size: var(--astra-font-body);text-overflow:ellipsis;white-space:nowrap}.artifact-list small{overflow:hidden;color:var(--astra-text-muted);font-size: var(--astra-font-helper);text-overflow:ellipsis;white-space:nowrap}.artifact-list b{color:var(--astra-text-muted);font-size: var(--astra-font-helper);font-weight: var(--astra-weight-regular);white-space:nowrap}
.acceptance-summary{margin-top:21px}.acceptance-summary__title{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;color:var(--astra-text-muted);font-size: var(--astra-font-body)}.acceptance-summary__title strong{color:var(--astra-success);font-weight: var(--astra-weight-bold)}.acceptance-summary article{display:grid;grid-template-columns:18px minmax(0,1fr);gap:8px;padding:7px 0}.acceptance-summary article>svg{margin-top:2px;color:var(--astra-text-muted)}.acceptance-summary article>svg.lucide-check-circle{color:var(--astra-success)}.acceptance-summary article>svg.lucide-circle-x{color:var(--astra-danger)}.acceptance-summary article>span{display:grid}.acceptance-summary article strong{font-size: var(--astra-font-body);font-weight: var(--astra-weight-regular);line-height:1.45}.acceptance-summary article small{margin-top:2px;color:var(--astra-text-muted);font-size: var(--astra-font-helper);line-height:1.4}
.run-detail-link{display:flex;align-items:center;justify-content:center;gap:7px;min-height:40px;margin-top:18px;color:var(--astra-text-primary);border:1px solid var(--astra-border-hover);border-radius:8px;background:#fff;font-size: var(--astra-font-body);font-weight: var(--astra-weight-bold);transition:.16s ease}.run-detail-link:hover{color:var(--astra-primary-bright);border-color:var(--astra-primary-border);background:var(--astra-primary-soft)}.run-detail-link.is-disabled{color:var(--astra-text-muted);font-weight: var(--astra-weight-regular)}
@media(max-width:900px){.task-sidebar__mobile-head{position:sticky;top:0;z-index:2;display:flex;align-items:center;justify-content:space-between;min-height:52px;padding:0 18px;border-bottom:1px solid var(--astra-border);background:rgba(255,255,255,.96);backdrop-filter:blur(12px)}.task-sidebar__mobile-head button{display:grid;place-items:center;width:32px;height:32px;color:var(--astra-text-muted);border:0;border-radius:8px;background:transparent;cursor:pointer}}
</style>
