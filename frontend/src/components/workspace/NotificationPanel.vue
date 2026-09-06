<template>
  <aside
    ref="panel"
    class="notification-panel"
    :data-open="panelOpen"
    aria-label="消息通知"
    @mouseenter="hovering = true"
    @mouseleave="hovering = false"
    @focusin="focused = true"
    @focusout="handleFocusOut"
    @keydown.esc.stop="closePanel"
  >
    <button
      class="notification-panel__trigger"
      type="button"
      aria-controls="workspace-notification-content"
      :aria-expanded="panelOpen"
      :aria-label="triggerLabel"
      @click="togglePinned"
    >
      <X v-if="pinned" :size="16" />
      <BellRing v-else :size="18" />
      <b v-if="unreadCount && !pinned">{{ unreadCount > 9 ? '9+' : unreadCount }}</b>
    </button>

    <div id="workspace-notification-content" class="notification-panel__content" :aria-hidden="!panelOpen">
      <header>
        <div><h2>消息通知</h2><p>{{ unreadCount ? `${unreadCount} 条需要关注` : '暂无未读消息' }}</p></div>
        <RouterLink to="/interventions">查看全部 <ChevronRight :size="14" /></RouterLink>
      </header>
      <div v-if="notifications.length" class="notification-panel__list">
        <RouterLink v-for="item in notifications" :key="item.id" :to="item.href" :data-tone="item.tone" @click="readIds.add(item.id)">
          <span class="notification-panel__icon"><component :is="item.icon" :size="15" /></span>
          <span><strong>{{ item.title }}</strong><em>{{ item.description }}</em><small>{{ formatTime(item.createdAt) }}</small></span>
          <i v-if="!readIds.has(item.id)" aria-label="未读" />
        </RouterLink>
      </div>
      <div v-else class="notification-panel__empty"><BellRing :size="24" /><strong>暂无新消息</strong><span>任务结果和待处理事件会显示在这里。</span></div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { BellRing, CheckCircle2, ChevronRight, CircleAlert, FileCheck2, TriangleAlert, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import type { AstraEvent, Task } from '@/api/types'
import { formatTime, platformCopy } from '@/utils/format'

const props = defineProps<{ events: AstraEvent[]; tasks: Task[] }>()
const panel = ref<HTMLElement | null>(null)
const readIds = reactive(new Set<string>())
const hovering = ref(false)
const focused = ref(false)
const pinned = ref(false)
const compactViewport = ref(false)
const panelOpen = computed(() => compactViewport.value || hovering.value || focused.value || pinned.value)
const triggerLabel = computed(() => pinned.value
  ? '收起通知面板'
  : panelOpen.value ? '固定通知面板' : `展开通知面板，${unreadCount.value} 条需要关注`)
let compactMedia: MediaQueryList | undefined
const notificationTypes = new Set(['WAIT_HUMAN', 'RESULT_SUBMITTED', 'TASK_COMPLETED', 'EXECUTION_ERROR', 'TASK_FAILED'])
const notifications = computed(() => props.events
  .filter((event) => notificationTypes.has(event.event_type))
  .slice(0, 12)
  .map((event) => {
    const task = props.tasks.find((item) => item.id === event.task_id)
    const config = ({
      WAIT_HUMAN: { title: '等待人工处理', icon: CircleAlert, tone: 'warning' },
      RESULT_SUBMITTED: { title: '任务结果已生成', icon: FileCheck2, tone: 'success' },
      TASK_COMPLETED: { title: '任务已完成', icon: CheckCircle2, tone: 'success' },
      EXECUTION_ERROR: { title: '运行出现异常', icon: TriangleAlert, tone: 'danger' },
      TASK_FAILED: { title: '任务未完成', icon: TriangleAlert, tone: 'danger' },
    } as const)[event.event_type as 'WAIT_HUMAN' | 'RESULT_SUBMITTED' | 'TASK_COMPLETED' | 'EXECUTION_ERROR' | 'TASK_FAILED']
    return { id: String(event.id), title: config?.title ?? '业务消息', icon: config?.icon ?? BellRing, tone: config?.tone ?? 'normal', description: task?.title ?? (platformCopy(event.message) || '任务状态已更新'), createdAt: event.created_at, href: event.task_id ? `/tasks/${event.task_id}` : '/interventions' }
  }))
const unreadCount = computed(() => notifications.value.filter((item) => !readIds.has(item.id)).length)

function handleFocusOut(event: FocusEvent) {
  if (!panel.value?.contains(event.relatedTarget as Node | null)) focused.value = false
}
function closePanel() {
  hovering.value = false
  focused.value = false
  pinned.value = false
  ;(document.activeElement as HTMLElement | null)?.blur()
}
function togglePinned() {
  if (pinned.value) closePanel()
  else pinned.value = true
}
function syncCompactViewport() { compactViewport.value = Boolean(compactMedia?.matches) }
onMounted(() => {
  compactMedia = window.matchMedia('(max-width: 1100px)')
  syncCompactViewport()
  compactMedia.addEventListener('change', syncCompactViewport)
})
onBeforeUnmount(() => compactMedia?.removeEventListener('change', syncCompactViewport))
</script>

<style scoped>
.notification-panel{position:relative;display:block;width:56px;height:56px;min-width:0;min-height:0;overflow:hidden;border:1px solid rgba(196,216,207,.7);border-radius:17px;background:rgba(255,255,255,.48);box-shadow:0 8px 22px rgba(35,76,59,.08);backdrop-filter:blur(14px) saturate(1.08);transition:width .22s ease,height .22s ease,background-color .22s ease,box-shadow .22s ease}
.notification-panel[data-open='true']{width:276px;height:var(--notification-panel-height,min(470px,calc(100% - 132px)));background:rgba(255,255,255,.88);box-shadow:0 16px 40px rgba(35,76,59,.15)}
.notification-panel__trigger{position:absolute;z-index:3;top:5px;right:5px;display:grid;place-items:center;width:44px;height:44px;padding:0;color:#356355;border:1px solid rgba(174,207,193,.72);border-radius:13px;background:rgba(255,255,255,.58);box-shadow:0 5px 14px rgba(35,76,59,.08);cursor:pointer;transition:width .2s ease,height .2s ease,background-color .2s ease}.notification-panel__trigger:hover,.notification-panel__trigger:focus-visible{color:var(--astra-primary);background:rgba(239,249,244,.94);outline:0}.notification-panel[data-open='true'] .notification-panel__trigger{top:12px;right:12px;width:30px;height:30px;border-radius:9px;background:rgba(245,250,247,.88)}.notification-panel__trigger b{position:absolute;top:-4px;right:-4px;display:grid;place-items:center;min-width:18px;height:18px;padding:0 4px;color:#fff;border:2px solid rgba(255,255,255,.94);border-radius:10px;background:var(--astra-warning);font-size:var(--astra-font-micro);line-height:1}
.notification-panel__content{display:grid;grid-template-rows:auto minmax(0,1fr);width:274px;height:100%;min-height:0;opacity:0;visibility:hidden;pointer-events:none;transform:translateX(9px);transition:opacity .14s ease,transform .18s ease,visibility 0s linear .18s}.notification-panel[data-open='true'] .notification-panel__content{opacity:1;visibility:visible;pointer-events:auto;transform:none;transition-delay:.05s,0s,0s}
.notification-panel__content>header{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:72px;padding:13px 50px 13px 15px;border-bottom:1px solid rgba(208,224,217,.86)}.notification-panel h2{margin:0;font:700 var(--astra-font-emphasis) var(--astra-font-display)}.notification-panel header p{margin:2px 0 0;color:var(--astra-text-muted);font-size:var(--astra-font-control)}.notification-panel header a{display:inline-flex;align-items:center;gap:3px;color:var(--astra-primary);font-size:var(--astra-font-control);white-space:nowrap}
.notification-panel__list{min-height:0;overflow-y:auto;padding:3px 12px 14px}.notification-panel__list>a{position:relative;display:grid;grid-template-columns:auto minmax(0,1fr);align-items:start;gap:9px;min-height:76px;padding:12px 4px;border-bottom:1px solid rgba(208,224,217,.86)}.notification-panel__list>a:hover{background:rgba(245,250,247,.86)}.notification-panel__icon{--tone:var(--astra-primary);display:grid;place-items:center;width:32px;height:32px;color:var(--tone);border-radius:10px;background:color-mix(in srgb,var(--tone) 10%,rgba(255,255,255,.76))}.notification-panel__list>a[data-tone='warning'] .notification-panel__icon{--tone:var(--astra-warning)}.notification-panel__list>a[data-tone='danger'] .notification-panel__icon{--tone:#dc654c}.notification-panel__list>a[data-tone='success'] .notification-panel__icon{--tone:var(--astra-success)}.notification-panel__list>a>span:nth-child(2){display:grid;min-width:0}.notification-panel__list strong,.notification-panel__list em,.notification-panel__list small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.notification-panel__list strong{color:var(--astra-text-primary);font-size:var(--astra-font-body)}.notification-panel__list em{color:var(--astra-text-secondary);font-size:var(--astra-font-control);font-style:normal}.notification-panel__list small{margin-top:2px;color:var(--astra-text-muted);font-size:var(--astra-font-helper)}.notification-panel__list>a>i{position:absolute;top:13px;right:2px;width:6px;height:6px;border-radius:50%;background:var(--astra-primary)}
.notification-panel__empty{display:grid;place-items:center;align-content:center;gap:5px;padding:24px;color:var(--astra-text-muted);text-align:center}.notification-panel__empty svg{color:#91a69f}.notification-panel__empty strong{color:var(--astra-text-primary);font-size:var(--astra-font-label)}.notification-panel__empty span{font-size:var(--astra-font-control)}
@media(max-width:1100px){.notification-panel,.notification-panel[data-open='true']{width:100%;height:340px;border-radius:16px;background:rgba(255,255,255,.9)}.notification-panel__trigger{display:none}.notification-panel__content{width:100%;opacity:1;visibility:visible;pointer-events:auto;transform:none}.notification-panel__content>header{padding-right:15px}}
@media(prefers-reduced-motion:reduce){.notification-panel,.notification-panel__trigger,.notification-panel__content{transition:none}}
</style>
