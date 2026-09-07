<template>
  <button
    class="employee-seat"
    :class="{ 'employee-seat--selected': selected, 'employee-seat--muted': muted }"
    :data-state="employee.state"
    :data-row="row"
    type="button"
    :aria-label="`${employee.name}，${employee.stateLabel}，${employee.currentTaskName}`"
    @click="emit('select', employee.id)"
  >
    <span v-if="showBubble" class="employee-seat__notice" :data-tone="noticeTone">
      <CircleAlert :size="12" />{{ noticeText }}
    </span>

    <span class="employee-seat__tooltip" role="tooltip">
      <strong>{{ employee.name }}</strong>
      <span>{{ employee.stateLabel }}<template v-if="runningTime"> · {{ runningTime }}</template></span>
      <em>{{ employee.currentTaskName }}</em>
    </span>

    <span class="employee-seat__character" :style="characterStyle" aria-hidden="true">
      <span class="employee-seat__sprite" />
      <i class="employee-seat__screen-glow" />
    </span>
    <span class="employee-seat__identity"><i />{{ employee.name }}</span>
  </button>
</template>

<script setup lang="ts">
import { CircleAlert } from 'lucide-vue-next'
import { computed } from 'vue'
import type { WorkspaceEmployee } from '@/features/workspace/eventAdapter'
import { employeeCharacterStyle } from '@/features/workspace/characterAssets'

const props = withDefaults(defineProps<{
  employee: WorkspaceEmployee
  row: 'back' | 'front'
  selected?: boolean
  muted?: boolean
  showBubble?: boolean
  bubbleMode?: 'alert'
}>(), { selected: false, muted: false, showBubble: false, bubbleMode: 'alert' })
const emit = defineEmits<{ select: [id: string] }>()

const characterStyle = computed(() => employeeCharacterStyle(props.employee.id, 'seated', props.employee.characterIndex))
const runningTime = computed(() => {
  const seconds = props.employee.runningSeconds
  if (!seconds) return ''
  if (seconds < 3600) return `${Math.max(1, Math.floor(seconds / 60))} 分钟`
  return `${Math.floor(seconds / 3600)} 小时`
})
const noticeTone = computed(() => props.employee.hasError ? 'danger' : props.employee.needHuman ? 'warning' : 'normal')
const noticeText = computed(() => props.employee.hasError ? '任务执行失败' : props.employee.needHuman ? '等待人工确认' : '')
</script>

<style scoped>
.employee-seat{position:relative;z-index:4;display:block;flex:none;width:64px;height:91px;padding:0;color:inherit;border:0;border-radius:15px;background:transparent;cursor:pointer;transition:opacity .2s ease,transform .2s ease,filter .2s ease}.employee-seat:hover,.employee-seat--selected{z-index:45;transform:translateY(-4px) scale(1.06)}.employee-seat:focus-visible{outline:3px solid rgba(22,159,101,.32);outline-offset:2px}.employee-seat--selected::after{position:absolute;right:7px;bottom:0;left:7px;height:9px;border:2px solid rgba(41,188,142,.7);border-radius:50%;background:rgba(71,207,164,.12);box-shadow:0 0 16px rgba(40,187,140,.34);content:'';animation:selection-ring 1.8s ease-in-out infinite}.employee-seat--muted{filter:grayscale(.55);opacity:.2}
.employee-seat__character{position:absolute;top:4px;left:50%;display:block;width:62px;height:82px;transform:translateX(-50%)}.employee-seat__sprite{position:absolute;inset:0;display:block;background-image:var(--character-atlas);background-repeat:no-repeat;background-position:var(--sprite-x) var(--sprite-y);background-size:400% 300%;filter:drop-shadow(0 5px 4px rgba(41,86,72,.16));transform-origin:50% 100%}.employee-seat[data-state='WORKING'] .employee-seat__sprite{animation:working-breathe 2.4s ease-in-out infinite}.employee-seat[data-state='IDLE'] .employee-seat__sprite,.employee-seat[data-state='OFFLINE'] .employee-seat__sprite{filter:grayscale(.13) drop-shadow(0 4px 4px rgba(33,75,60,.09));opacity:.82}.employee-seat[data-state='ERROR'] .employee-seat__sprite{filter:drop-shadow(0 4px 6px rgba(224,65,75,.28));animation:error-shake 3s ease-in-out infinite}.employee-seat__screen-glow{position:absolute;right:3px;bottom:4px;width:16px;height:4px;border-radius:50%;background:transparent;filter:blur(4px)}.employee-seat[data-state='WORKING'] .employee-seat__screen-glow{background:rgba(37,191,142,.55)}
.employee-seat__identity{position:absolute;z-index:5;top:-7px;left:50%;display:flex;align-items:center;gap:4px;max-width:94px;height:18px;padding:0 6px;overflow:hidden;color:#244d42;border:1px solid rgba(177,207,194,.82);border-radius:7px;background:rgba(255,255,255,.94);box-shadow:0 3px 9px rgba(42,77,64,.09);font-size:var(--astra-font-size-8);font-weight: var(--astra-weight-bold);line-height:1;white-space:nowrap;text-overflow:ellipsis;opacity:0;transform:translate(-50%,4px);transition:opacity .16s ease,transform .16s ease}.employee-seat:hover .employee-seat__identity,.employee-seat--selected .employee-seat__identity,.employee-seat:focus-visible .employee-seat__identity{opacity:1;transform:translate(-50%,0)}.employee-seat__identity i{flex:none;width:5px;height:5px;border-radius:50%;background:#9ca9a5}.employee-seat[data-state='WORKING'] .employee-seat__identity i,.employee-seat[data-state='COMPLETED'] .employee-seat__identity i{background:var(--astra-primary)}.employee-seat[data-state='WAITING'] .employee-seat__identity i,.employee-seat[data-state='NEED_HUMAN'] .employee-seat__identity i{background:var(--astra-warning)}.employee-seat[data-state='ERROR'] .employee-seat__identity i{background:var(--astra-danger)}
.employee-seat__notice{position:absolute;z-index:44;bottom:calc(100% - 6px);left:50%;display:flex;align-items:center;gap:4px;width:max-content;max-width:150px;padding:6px 8px;color:#285247;border:1px solid #cfe1d9;border-radius:9px;background:rgba(255,255,255,.97);box-shadow:0 7px 18px rgba(34,72,58,.13);font-size:var(--astra-font-size-8);font-weight: var(--astra-weight-bold);white-space:nowrap;transform:translateX(-50%);transition:opacity .12s ease}.employee-seat__notice::after{position:absolute;top:100%;left:calc(50% - 4px);border:4px solid transparent;border-top-color:#fff;content:''}.employee-seat__notice[data-tone='warning']{color:#9a5e18;border-color:#efd1aa;background:#fffaf2}.employee-seat__notice[data-tone='danger']{color:#c13d45;border-color:#efc0c2;background:#fff8f8}.employee-seat:hover .employee-seat__notice{opacity:0}
.employee-seat__tooltip{position:absolute;z-index:46;bottom:calc(100% - 1px);left:50%;display:grid;width:170px;padding:10px 11px;color:#173f35;border:1px solid #ccdfd7;border-radius:11px;background:rgba(255,255,255,.98);box-shadow:0 13px 30px rgba(32,70,56,.18);text-align:left;opacity:0;pointer-events:none;transform:translate(-50%,5px);transition:opacity .15s ease,transform .15s ease}.employee-seat__tooltip strong{font-size: var(--astra-font-control)}.employee-seat__tooltip span{margin-top:1px;color:#18855b;font-size: var(--astra-font-micro)}.employee-seat__tooltip em{margin-top:4px;overflow:hidden;color:#647a73;font-size: var(--astra-font-micro);font-style:normal;text-overflow:ellipsis;white-space:nowrap}.employee-seat:hover .employee-seat__tooltip,.employee-seat:focus-visible .employee-seat__tooltip{opacity:1;transform:translate(-50%,0)}
.employee-seat[data-row='front']{z-index:12}.employee-seat[data-row='front'] .employee-seat__character{width:66px;height:87px}
@media(max-width:760px){.employee-seat{width:62px;height:88px}.employee-seat__character,.employee-seat[data-row='front'] .employee-seat__character{width:61px;height:79px}.employee-seat__notice{font-size:var(--astra-font-size-7)}}
@keyframes working-breathe{50%{transform:translateY(-2px)}}
@keyframes error-shake{2%,6%{transform:translateX(-1px)}4%,8%{transform:translateX(1px)}10%,100%{transform:none}}
@keyframes selection-ring{50%{opacity:.55;transform:scale(1.12)}}
@media(prefers-reduced-motion:reduce){.employee-seat,.employee-seat__sprite,.employee-seat__tooltip,.employee-seat--selected::after{animation:none!important;transition:none!important}}
</style>
