<template>
  <article class="subtask-card" :data-status="subtask.status" :data-testid="`subtask-${subtask.id}`">
    <button class="subtask-card__summary" type="button" :aria-expanded="expanded" @click="toggle">
      <span class="subtask-card__icon"><Box :size="18" /></span>
      <span class="subtask-card__identity">
        <span><b>子任务</b><strong>{{ subtask.name }}</strong></span>
        <small>{{ subtask.title }}</small>
      </span>
      <span class="subtask-card__status">
        <LoaderCircle v-if="subtask.status === 'running'" class="spin" :size="15" />
        <CheckCircle2 v-else-if="subtask.status === 'completed'" :size="15" />
        <CircleX v-else :size="15" />
        {{ subtask.statusLabel }}
      </span>
      <ChevronDown class="subtask-card__chevron" :class="{ 'is-open': expanded }" :size="17" />
    </button>

    <div v-if="expanded" class="subtask-card__details">
      <ol class="subtask-steps">
        <li v-for="(step, index) in subtask.steps" :key="step.id" :data-status="step.status">
          <span class="subtask-step__index">
            <Check v-if="step.status === 'completed'" :size="13" />
            <CircleX v-else-if="step.status === 'failed'" :size="13" />
            <LoaderCircle v-else-if="step.status === 'running'" class="spin" :size="13" />
            <b v-else>{{ index + 1 }}</b>
          </span>
          <span class="subtask-step__copy">
            <strong>{{ step.title }}</strong>
            <small v-if="step.detail">{{ step.detail }}</small>
          </span>
          <span class="subtask-step__state">{{ stepStatusLabel(step.status) }}</span>
          <time>{{ formatClock(step.timestamp) }}</time>
        </li>
      </ol>
      <div v-if="subtask.output || subtask.error" class="subtask-output" :data-error="!!subtask.error">
        <strong>{{ subtask.error ? '失败原因' : '最终输出' }}</strong>
        <p>{{ subtask.error || subtask.output }}</p>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { Box, Check, CheckCircle2, ChevronDown, CircleX, LoaderCircle } from 'lucide-vue-next'
import { ref, watch } from 'vue'
import type { ConversationSubtask, SubtaskStepStatus } from './conversation'

const props = defineProps<{ subtask: ConversationSubtask }>()
const expanded = ref(props.subtask.status === 'running')
const manuallyToggled = ref(false)

function toggle() {
  manuallyToggled.value = true
  expanded.value = !expanded.value
}

watch(() => props.subtask.status, (status) => {
  if (!manuallyToggled.value) expanded.value = status === 'running'
})

const stepStatusLabel = (status: SubtaskStepStatus) => ({
  pending: '等待中',
  running: '进行中',
  completed: '已完成',
  failed: '失败',
}[status])

const formatClock = (value: string) => new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
}).format(new Date(value))
</script>

<style scoped>
.subtask-card{width:min(100%,720px);overflow:hidden;border:1px solid var(--astra-border);border-radius:13px;background:#fff;box-shadow:0 8px 24px rgba(32,79,59,.045)}
.subtask-card__summary{display:grid;width:100%;grid-template-columns:38px minmax(0,1fr) auto 20px;align-items:center;gap:11px;padding:13px 14px;color:var(--astra-text-primary);border:0;background:transparent;text-align:left;cursor:pointer}
.subtask-card__summary:hover{background:#fbfdfc}.subtask-card__icon{display:grid;place-items:center;width:36px;height:36px;color:var(--astra-primary-bright);border-radius:50%;background:var(--astra-primary-soft)}
.subtask-card__identity{display:grid;min-width:0}.subtask-card__identity>span{display:flex;align-items:center;gap:9px}.subtask-card__identity b{font-size:14px}.subtask-card__identity strong{font-size:14px;font-weight:650}.subtask-card__identity small{overflow:hidden;margin-top:2px;color:var(--astra-text-muted);font-size:12px;text-overflow:ellipsis;white-space:nowrap}
.subtask-card__status{display:inline-flex;align-items:center;gap:5px;padding:4px 9px;color:var(--astra-info);border-radius:999px;background:color-mix(in srgb,var(--astra-info) 10%,transparent);font-size:12px;white-space:nowrap}.subtask-card[data-status=completed] .subtask-card__status{color:var(--astra-success);background:var(--astra-success-soft)}.subtask-card[data-status=failed] .subtask-card__status{color:var(--astra-danger);background:var(--astra-danger-soft)}
.subtask-card__chevron{color:var(--astra-text-muted);transition:transform .18s ease}.subtask-card__chevron.is-open{transform:rotate(180deg)}
.subtask-card__details{padding:0 12px 12px}.subtask-steps{margin:0;padding:0 10px;border:1px solid var(--astra-border);border-radius:10px;list-style:none;background:#fcfefd}
.subtask-steps li{position:relative;display:grid;grid-template-columns:30px minmax(0,1fr) auto auto;align-items:start;gap:9px;min-height:62px;padding:12px 0;border-bottom:1px solid #edf2ef}.subtask-steps li:last-child{border-bottom:0}.subtask-steps li:not(:last-child):before{content:"";position:absolute;top:38px;bottom:-16px;left:14px;width:1px;background:#dce8e2}
.subtask-step__index{position:relative;z-index:1;display:grid;place-items:center;width:28px;height:28px;color:#fff;border:1px solid var(--astra-border-hover);border-radius:50%;background:#fff}.subtask-step__index b{color:var(--astra-text-muted);font-size:12px}.subtask-steps li[data-status=completed] .subtask-step__index{border-color:var(--astra-success);background:var(--astra-success)}.subtask-steps li[data-status=running] .subtask-step__index{color:var(--astra-primary);border-color:var(--astra-primary);background:#fff}.subtask-steps li[data-status=failed] .subtask-step__index{border-color:var(--astra-danger);background:var(--astra-danger)}
.subtask-step__copy{display:grid;min-width:0;padding-top:2px}.subtask-step__copy strong{font-size:13px}.subtask-step__copy small{overflow:hidden;margin-top:2px;color:var(--astra-text-muted);font-size:12px;line-height:1.45;text-overflow:ellipsis;white-space:nowrap}.subtask-step__state{padding-top:4px;color:var(--astra-text-muted);font-size:12px;white-space:nowrap}.subtask-steps li[data-status=completed] .subtask-step__state{color:var(--astra-success)}.subtask-steps li[data-status=running] .subtask-step__state{color:var(--astra-info)}.subtask-steps li[data-status=failed] .subtask-step__state{color:var(--astra-danger)}.subtask-steps time{padding-top:4px;color:var(--astra-text-muted);font-size:11px;white-space:nowrap}
.subtask-output{display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px;margin-top:9px;padding:10px 12px;border-radius:8px;background:linear-gradient(90deg,var(--astra-success-soft),#f8fcfa)}.subtask-output strong{font-size:12px}.subtask-output p{min-width:0;margin:0;color:var(--astra-text-secondary);font-size:12px;line-height:1.55;white-space:pre-wrap;word-break:break-word}.subtask-output[data-error=true]{background:var(--astra-danger-soft)}
@media(max-width:640px){.subtask-card__summary{grid-template-columns:34px minmax(0,1fr) 20px}.subtask-card__status{grid-column:2;justify-self:start}.subtask-card__chevron{grid-column:3;grid-row:1}.subtask-steps li{grid-template-columns:28px minmax(0,1fr) auto}.subtask-steps time{display:none}.subtask-step__state{grid-column:3}.subtask-step__copy small{white-space:normal}.subtask-output{grid-template-columns:1fr}}
</style>
