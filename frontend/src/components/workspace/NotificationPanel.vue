<template>
  <aside class="notification-panel" aria-label="消息通知">
    <header><div><h2>消息通知</h2><p>{{ unreadCount ? `${unreadCount} 条需要关注` : '暂无未读消息' }}</p></div><RouterLink to="/interventions">查看全部 <ChevronRight :size="14" /></RouterLink></header>
    <div v-if="notifications.length" class="notification-panel__list">
      <RouterLink v-for="item in notifications" :key="item.id" :to="item.href" :data-tone="item.tone" @click="readIds.add(item.id)">
        <span class="notification-panel__icon"><component :is="item.icon" :size="15" /></span>
        <span><strong>{{ item.title }}</strong><em>{{ item.description }}</em><small>{{ formatTime(item.createdAt) }}</small></span>
        <i v-if="!readIds.has(item.id)" aria-label="未读" />
      </RouterLink>
    </div>
    <div v-else class="notification-panel__empty"><BellRing :size="24" /><strong>暂无新消息</strong><span>任务结果和待处理事件会显示在这里。</span></div>
  </aside>
</template>

<script setup lang="ts">
import { BellRing, CheckCircle2, ChevronRight, CircleAlert, FileCheck2, TriangleAlert } from 'lucide-vue-next'
import { computed, reactive } from 'vue'
import { RouterLink } from 'vue-router'
import type { AstraEvent, Task } from '@/api/types'
import { formatTime, platformCopy } from '@/utils/format'

const props = defineProps<{ events: AstraEvent[]; tasks: Task[] }>()
const readIds = reactive(new Set<string>())
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
</script>

<style scoped>
.notification-panel { display: grid; grid-template-rows: auto minmax(0,1fr); min-width: 0; min-height: 0; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 16px; background: white; box-shadow: 0 13px 34px rgba(35,76,59,.08); }
.notification-panel > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 72px; padding: 13px 15px; border-bottom: 1px solid var(--astra-border); }.notification-panel h2 { margin: 0; font: 700 16px var(--astra-font-display); }.notification-panel header p { margin: 2px 0 0; color: var(--astra-text-muted); font-size: 11px; }.notification-panel header a { display: inline-flex; align-items: center; gap: 3px; color: var(--astra-primary); font-size: 11px; white-space: nowrap; }
.notification-panel__list { min-height: 0; overflow-y: auto; padding: 3px 12px 14px; }.notification-panel__list > a { position: relative; display: grid; grid-template-columns: auto minmax(0,1fr); align-items: start; gap: 9px; min-height: 76px; padding: 12px 4px; border-bottom: 1px solid var(--astra-border); }.notification-panel__list > a:hover { background: #f5faf7; }.notification-panel__icon { --tone: var(--astra-primary); display: grid; place-items: center; width: 32px; height: 32px; color: var(--tone); border-radius: 10px; background: color-mix(in srgb,var(--tone) 10%,white); }.notification-panel__list > a[data-tone='warning'] .notification-panel__icon { --tone: var(--astra-warning); }.notification-panel__list > a[data-tone='danger'] .notification-panel__icon { --tone: #dc654c; }.notification-panel__list > a[data-tone='success'] .notification-panel__icon { --tone: var(--astra-success); }.notification-panel__list > a > span:nth-child(2) { display: grid; min-width: 0; }.notification-panel__list strong,.notification-panel__list em,.notification-panel__list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.notification-panel__list strong { color: var(--astra-text-primary); font-size: 12px; }.notification-panel__list em { color: var(--astra-text-secondary); font-size: 11px; font-style: normal; }.notification-panel__list small { margin-top: 2px; color: var(--astra-text-muted); font-size: 10px; }.notification-panel__list > a > i { position: absolute; top: 13px; right: 2px; width: 6px; height: 6px; border-radius: 50%; background: var(--astra-primary); }
.notification-panel__empty { display: grid; place-items: center; align-content: center; gap: 5px; padding: 24px; color: var(--astra-text-muted); text-align: center; }.notification-panel__empty svg { color: #91a69f; }.notification-panel__empty strong { color: var(--astra-text-primary); font-size: 13px; }.notification-panel__empty span { font-size: 11px; }
</style>
