<template>
  <article
    class="office-workstation"
    :class="{
      'office-workstation--working': isWorking,
      'office-workstation--thinking': isThinking,
      'office-workstation--attention-live': isAttentionLive,
    }"
    :data-employee-id="employee.id"
    :data-state="employee.status"
    data-testid="office-workstation"
  >
    <ElTooltip
      placement="bottom" effect="light" popper-class="office-workstation-tooltip"
      :reference-el="identityElement" :popper-options="tooltipOptions"
      :trigger="['hover', 'focus']" :trigger-keys="[]"
      :show-after="350" :persistent="false"
    >
      <template #content>
        <div class="office-workstation-tooltip__heading"><strong>{{ employee.name }}</strong><span>{{ employee.availabilityLabel }} · {{ employee.statusLabel }}</span></div>
        <p class="office-workstation-tooltip__role">{{ employeeDescription }}</p>
        <dl v-if="actionDescription || employee.taskTitle" class="office-workstation-tooltip__details">
          <template v-if="actionDescription"><dt>当前动作</dt><dd>{{ actionDescription }}</dd></template>
          <template v-if="employee.taskTitle"><dt>当前任务</dt><dd>{{ employee.taskTitle }}</dd></template>
        </dl>
      </template>
      <RouterLink class="office-workstation__main" :to="employee.target" :aria-label="tooltipContent">
        <header ref="identityElement" class="office-workstation__identity">
          <div class="office-workstation__name">
            <strong>{{ employee.name }}</strong>
            <CircleAlert v-if="employee.status === 'attention'" class="office-workstation__notice" :size="16" aria-label="需要人工处理" />
            <TriangleAlert v-else-if="employee.status === 'error'" :size="15" aria-label="执行异常" />
            <Check v-else-if="isCompleted" class="office-workstation__completed" :size="17" aria-label="刚刚完成" />
            <i v-else :title="employee.statusLabel" />
          </div>
          <div class="office-workstation__status">
            <span class="office-workstation__availability" :data-availability="employee.availability" title="平台员工状态快照，不代表 Server 实时连接">{{ employee.availabilityLabel }}</span>
            <span v-if="employee.statusLabel !== employee.availabilityLabel">{{ employee.status === 'attention' ? employee.currentAction : employee.statusLabel }}</span>
          </div>
          <span class="office-workstation__action" :title="employee.taskTitle || employee.currentAction">{{ employee.taskTitle || (employee.status === 'idle' ? '暂无当前任务' : employee.currentAction) }}</span>
        </header>
        <div class="office-workstation__scene" aria-hidden="true">
          <span class="office-workstation__floor" />
          <img class="office-workstation__desk" src="/assets/office/desk.png" alt="" draggable="false" />
          <span class="office-workstation__monitor"><i /><i /><i /></span>
          <span class="office-workstation__keyboard" />
          <img class="office-workstation__character" :src="characterSource" alt="" draggable="false" />
          <img class="office-workstation__chair" src="/assets/office/chair.png" alt="" draggable="false" />
          <span class="office-workstation__seat-light" />
        </div>
      </RouterLink>
    </ElTooltip>
    <nav class="office-workstation__links" :aria-label="`${employee.name}的工作入口`">
      <RouterLink :to="employee.employeeTarget" :aria-label="`查看${employee.name}的员工详情`">员工详情</RouterLink>
      <RouterLink v-if="employee.taskId" :to="employee.target" class="office-workstation__task-link" :aria-label="`${employee.taskLinkLabel}：${employee.taskTitle}`">{{ employee.taskLinkLabel }}<ArrowUpRight :size="13" /></RouterLink>
    </nav>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ElTooltip } from 'element-plus'
import { ArrowUpRight, Check, CircleAlert, TriangleAlert } from 'lucide-vue-next'
import type { OfficeEmployee } from '@/features/home/officePresentation'
import { employeeCharacterSource } from '@/features/workspace/characterAssets'

const props = withDefaults(defineProps<{ employee: OfficeEmployee; live?: boolean; completed?: boolean }>(), { live: false, completed: false })
const identityElement = ref<HTMLElement>()
// 用可见的姓名/动作定位；参考元素滚出工位视口时，Popper 的 hide 修饰器隐藏提示。
const tooltipOptions = { modifiers: [
  { name: 'preventOverflow', options: { altBoundary: true, altAxis: true, padding: 10 } },
  { name: 'flip', options: { altBoundary: true, padding: 10 } },
] }
const isWorking = computed(() => props.live && props.employee.status === 'working')
const isThinking = computed(() => props.live && props.employee.status === 'thinking')
const isAttentionLive = computed(() => props.live && props.employee.status === 'attention')
const isCompleted = computed(() => props.completed)
const characterSource = computed(() => employeeCharacterSource(props.employee.characterIndex, props.employee.status === 'attention' || props.employee.status === 'error' ? 'front' : 'back'))
const employeeDescription = computed(() => [...new Set([props.employee.teamName, props.employee.role].filter(Boolean))].join(' · '))
const actionDescription = computed(() => props.employee.currentAction === props.employee.statusLabel || props.employee.status === 'working' ? '' : props.employee.currentAction)
const tooltipContent = computed(() => [props.employee.name, employeeDescription.value, props.employee.availabilityLabel, props.employee.statusLabel, actionDescription.value, props.employee.taskTitle].filter(Boolean).join(' · '))
</script>

<style scoped>
/* 移植 workbzw/ai-office-react DeskEntity 的桌/人物/椅子前后层级和锚点。
   Spine 原人物离线渲染为透明 PNG；页面仅用 DOM/CSS 展示，无 Pixi/Spine 运行依赖。 */
.office-workstation{position:relative;min-width:0;isolation:isolate}
.office-workstation__main{display:block;position:relative;color:var(--astra-text-primary);text-decoration:none;border-radius:10px;outline-offset:3px}
.office-workstation__main:focus-visible{outline:2px solid var(--astra-primary)}
.office-workstation__identity{position:relative;z-index:5;display:grid;justify-items:center;align-content:start;gap:4px;height:81px;margin-inline:2px}
.office-workstation__status{display:flex;justify-content:center;align-items:center;gap:6px;max-width:100%;font-size:var(--astra-font-helper);line-height:18px;color:var(--astra-text-secondary);background:rgb(255 255 255 / 92%);padding:0 6px;border-radius:4px}
.office-workstation__availability{color:var(--astra-primary-bright)}
.office-workstation__availability[data-availability='offline'],.office-workstation__availability[data-availability='disabled'],.office-workstation__availability[data-availability='unknown']{color:var(--astra-text-muted)}
.office-workstation__availability[data-availability='error']{color:var(--astra-danger)}
.office-workstation__links{position:relative;z-index:6;display:flex;justify-content:center;align-items:center;gap:12px;margin-top:-4px;font-size:var(--astra-font-helper);line-height:24px}
.office-workstation__links a{display:inline-flex;align-items:center;gap:2px;padding:0 5px;border-radius:4px;background:rgb(255 255 255 / 92%);color:var(--astra-text-secondary)}
.office-workstation__links a:hover,.office-workstation__links a:focus-visible{color:var(--astra-primary-bright);outline:1px solid var(--astra-primary-border)}
.office-workstation__links .office-workstation__task-link{color:var(--astra-primary-bright);font-weight:var(--astra-weight-bold)}
.office-workstation__action{position:relative;display:block;max-width:100%;padding:4px 9px;border:1px solid rgb(255 255 255 / 85%);border-radius:5px;background:rgb(255 255 255 / 94%);box-shadow:0 2px 7px rgb(35 41 38 / 7%);color:var(--astra-text-secondary);font-size:var(--astra-font-helper);line-height:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.office-workstation__name{display:flex;align-items:center;justify-content:center;gap:5px;min-width:0;max-width:100%;padding:0 5px;border-radius:4px;background:rgb(255 255 255 / 70%)}
.office-workstation__name strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--astra-font-body);line-height:22px}
.office-workstation__name i{width:7px;height:7px;flex:none;border-radius:50%;background:var(--astra-text-muted)}
.office-workstation__name svg{flex:none}
.office-workstation__name{padding:0 7px;background:rgb(255 255 255 / 95%)}
.office-workstation__name strong{font-size:var(--astra-font-emphasis)}
.office-workstation__scene{position:relative;height:145px;max-width:200px;margin:-2px auto 0;pointer-events:none}
.office-workstation__floor{position:absolute;bottom:1px;left:calc(50% - 74px);width:148px;height:25px;border-radius:50%;background:rgb(61 79 110 / 10%);transition:background .2s}
.office-workstation__desk{position:absolute;z-index:1;top:29px;left:calc(50% - 76px);width:152px;height:auto;user-select:none}
.office-workstation__character{position:absolute;z-index:3;top:0;left:calc(50% - 44px);width:88px;height:110px;object-fit:contain;object-position:center bottom;transform-origin:center bottom;user-select:none}
.office-workstation__chair{position:absolute;z-index:4;top:73px;left:calc(50% - 36px);width:72px;height:auto;user-select:none}
.office-workstation__seat-light{position:absolute;z-index:5;top:105px;left:calc(50% - 5px);width:10px;height:10px;border:2px solid white;border-radius:50%;background:var(--astra-text-muted);box-shadow:0 0 0 1px rgb(255 255 255 / 40%)}
.office-workstation__monitor{position:absolute;z-index:2;top:32px;left:calc(50% - 18px);width:36px;height:21px;display:grid;align-content:center;gap:3px;padding:4px;opacity:0;background:var(--astra-primary-soft)}
.office-workstation__monitor i{height:1px;width:100%;background:var(--astra-primary)}.office-workstation__monitor i:nth-child(2){width:65%}.office-workstation__monitor i:nth-child(3){width:80%}
.office-workstation__keyboard{position:absolute;z-index:2;top:67px;left:calc(50% - 18px);width:36px;height:3px;opacity:0;background:var(--astra-primary-soft)}
.office-workstation__main:hover .office-workstation__action{border-color:var(--astra-primary-border);box-shadow:0 2px 10px var(--astra-primary-glow)}
.office-workstation__main:hover .office-workstation__floor{background:var(--astra-primary-soft)}
[data-state='working'] .office-workstation__name i,[data-state='thinking'] .office-workstation__name i,[data-state='working'] .office-workstation__seat-light,[data-state='thinking'] .office-workstation__seat-light{background:var(--astra-primary)}
[data-state='attention'] .office-workstation__action{border-color:var(--astra-warning);background:color-mix(in srgb,var(--astra-warning-soft) 65%,white);color:var(--astra-text-primary)}
[data-state='attention'] .office-workstation__name svg{color:var(--astra-warning)}
[data-state='attention'] .office-workstation__seat-light,[data-state='waiting'] .office-workstation__seat-light{background:var(--astra-warning)}
[data-state='error'] .office-workstation__action{border-color:var(--astra-danger);color:var(--astra-danger)}
[data-state='error'] .office-workstation__name svg{color:var(--astra-danger)}
[data-state='error'] .office-workstation__seat-light{background:var(--astra-danger)}
[data-state='waiting'] .office-workstation__status,[data-state='attention'] .office-workstation__status{color:var(--astra-warning)}
[data-state='error'] .office-workstation__status{color:var(--astra-danger)}
[data-state='offline'] .office-workstation__scene,[data-state='disabled'] .office-workstation__scene{filter:grayscale(.8);opacity:.65}
.office-workstation__completed{color:var(--astra-primary);animation:office-workstation-complete .5s ease-out both}
.office-workstation--working .office-workstation__character{animation:office-workstation-body-bob 1.2s ease-in-out infinite}
.office-workstation--working .office-workstation__keyboard{opacity:1;animation:office-workstation-typing .3s steps(2) infinite}
.office-workstation--working .office-workstation__monitor{opacity:1}
.office-workstation--working .office-workstation__monitor i{animation:office-workstation-monitor-flicker 2s ease-in-out infinite}
.office-workstation--thinking .office-workstation__character{animation:office-workstation-body-bob 3s ease-in-out infinite}
.office-workstation--attention-live .office-workstation__notice{animation:office-workstation-attention 2s ease-in-out infinite}
/* 工作动画结构来自 k1dav-c/agent-virtual-office App.css。 */
@keyframes office-workstation-typing{0%,100%{transform:translateY(0)}25%,75%{transform:translateY(-1px)}50%{transform:translateY(0)}}
@keyframes office-workstation-body-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-2px)}}
@keyframes office-workstation-monitor-flicker{0%,100%{opacity:.7}30%{opacity:.9}50%{opacity:.5}70%{opacity:1}85%{opacity:.6}}
@keyframes office-workstation-attention{0%,100%{opacity:1;transform:translateY(0)}50%{opacity:.6;transform:translateY(-2px)}}
@keyframes office-workstation-complete{from{opacity:0;transform:translateY(5px) scale(.9)}to{opacity:1;transform:translateY(0) scale(1)}}
@media(prefers-reduced-motion:reduce){.office-workstation__character,.office-workstation__monitor i,.office-workstation__keyboard,.office-workstation__notice,.office-workstation__completed{animation:none!important}.office-workstation__floor{transition:none}}
</style>

<style>
/* 提示 teleport 到 body；限定内容宽度并随工位裁切范围隐藏，避免盖住筛选栏。 */
.el-popper.office-workstation-tooltip{max-width:320px;padding:12px 14px;color:var(--astra-text-primary);font-size:var(--astra-font-helper);line-height:1.6;overflow-wrap:anywhere}
.office-workstation-tooltip[data-popper-reference-hidden='true']{visibility:hidden;pointer-events:none}
.office-workstation-tooltip__heading{display:flex;align-items:flex-start;gap:10px;justify-content:space-between}
.office-workstation-tooltip__heading strong{min-width:0;font-size:var(--astra-font-body)}
.office-workstation-tooltip__heading>span{flex:none;color:var(--astra-text-muted)}
.office-workstation-tooltip__role{margin:5px 0 0;color:var(--astra-text-muted)}
.office-workstation-tooltip__details{display:grid;grid-template-columns:52px minmax(0,1fr);gap:6px 10px;max-height:240px;overflow:auto;margin:10px 0 0;padding-top:10px;border-top:1px solid var(--astra-border)}
.office-workstation-tooltip__details dt{color:var(--astra-text-muted)}
.office-workstation-tooltip__details dd{margin:0;min-width:0}
</style>
