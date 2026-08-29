<template>
  <div class="page dashboard-page" data-testid="dashboard-page">
    <section class="page-intro">
      <div><h2>总览</h2><p>实时掌握数字员工运行状态与工作进展</p></div>
      <div class="intro-live"><strong :class="{ 'connection--offline': !dataHealthy }"><i /> {{ store.error ? '数据异常' : store.realtimeConnected ? '实时连接' : '正在重连' }}</strong><span>最后更新 {{ lastSync }}</span></div>
    </section>

    <section class="metrics-grid metrics-grid--status" data-testid="dashboard-v03-metrics">
      <AstraMetricCard label="工作中" :value="employeeCount('WORKING')" unit="人" hint="正在处理工作" :icon="BriefcaseBusiness" tone="success" />
      <AstraMetricCard label="空闲" :value="employeeCount('IDLE')" unit="人" hint="等待新任务" :icon="Activity" />
      <AstraMetricCard label="等待人工" :value="employeeCount('WAIT_HUMAN')" unit="人" hint="需要补充信息" :icon="Hand" tone="warning" />
      <AstraMetricCard label="执行异常" :value="employeeCount('ERROR')" unit="人" hint="工作现场已保留" :icon="CircleAlert" tone="danger" />
      <AstraMetricCard label="今日完成" :value="store.metrics?.completed_today ?? '—'" unit="项" hint="员工已提交结果" :icon="BadgeCheck" tone="success" />
      <article class="usage-brief"><div><span><Binary :size="17" /></span><small>今日模型用量</small><strong>{{ formatTokens(store.metrics?.today_tokens) }}</strong></div><div><span><Wrench :size="17" /></span><small>工具调用</small><strong>{{ store.metrics?.today_tool_calls ?? '—' }}</strong></div></article>
    </section>

    <section class="dashboard-grid">
      <div class="dashboard-main">
        <AstraPanel class="active-panel" title="数字办公区" subtitle="查看团队工作状态与任务进展" flush><DigitalOffice :employees="store.employees" :tasks="store.tasks" /></AstraPanel>
        <section class="overview-bottom">
          <AstraPanel title="分区概览"><div class="zone-summary"><article v-for="group in roleGroups" :key="group.role"><small>{{ group.label }}</small><strong>{{ group.count }}</strong><span>{{ group.working }} 人工作中</span></article></div></AstraPanel>
          <AstraPanel title="系统运行指标"><div class="system-summary"><article><small>数字员工</small><strong>{{ store.employees.length }}</strong><span>已配置</span></article><article><small>当前任务</small><strong>{{ store.activeTasks.length }}</strong><span>未完成</span></article><article><small>待办事项</small><strong>{{ pendingTasks.length }}</strong><span>需要关注</span></article><article><small>数据连接</small><strong>{{ dataHealthy ? '正常' : '重连中' }}</strong><span>实时状态</span></article></div></AstraPanel>
        </section>
      </div>

      <aside class="dashboard-side">
        <AstraPanel title="最近更新" subtitle="真实的任务与员工记录"><div class="event-feed"><article v-for="event in meaningfulEvents.slice(0, 5)" :key="event.id"><span class="event-dot" :data-tone="eventTone(event.event_type)"><component :is="eventIcon(event.event_type)" :size="13" /></span><div><strong>{{ eventSummary(event) }}</strong><p>{{ eventTaskTitle(event.task_id) }}</p></div><time>{{ formatTime(event.created_at) }}</time></article><AstraEmptyState v-if="!meaningfulEvents.length" :icon="Activity" title="暂无动态" description="员工工作后会显示在这里。" /></div></AstraPanel>
        <AstraPanel title="待办事项"><div class="todo-list"><RouterLink v-for="task in pendingTasks.slice(0,4)" :key="task.id" :to="`/tasks/${task.id}`"><span><CircleAlert :size="15" /></span><div><strong>{{ task.title }}</strong><small>{{ platformCopy(task.current_progress) || '等待处理' }}</small></div></RouterLink><AstraEmptyState v-if="!pendingTasks.length" :icon="Check" title="暂无待办" description="需要处理的任务会显示在这里。" /></div></AstraPanel>
      </aside>
    </section>

  </div>
</template>

<script setup lang="ts">
import { Activity, BadgeCheck, Binary, BriefcaseBusiness, Check, CircleAlert, Hand, Play, Wrench } from 'lucide-vue-next'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { AstraEvent } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraMetricCard from '@/components/astra/AstraMetricCard.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import DigitalOffice from '@/components/office/DigitalOffice.vue'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatTime, formatTokens, platformCopy } from '@/utils/format'

const store = useAstraStore()
const dataHealthy = computed(() => store.realtimeConnected && !store.error)
const lastSync = computed(() => store.lastUpdated?.toLocaleTimeString('zh-CN', { hour12: false }) ?? '连接中')
const employeeCount = (status: string) => store.employees.filter((employee) => employee.status === status).length
const pendingTasks = computed(() => store.tasks.filter((task) => ['WAIT_HUMAN', 'SUSPENDED', 'PENDING_CONFIRMATION', 'EXECUTION_ERROR'].includes(task.status) || task.inactivity_alert))
const visibleEventTypes = new Set(['TASK_ASSIGNED', 'TASK_RUNNING', 'WAIT_HUMAN', 'TASK_SUSPENDED', 'RESULT_SUBMITTED', 'TASK_COMPLETED', 'EXECUTION_ERROR', 'TASK_FAILED', 'TASK_CANCELLED'])
const meaningfulEvents = computed(() => store.events.filter((event) => visibleEventTypes.has(event.event_type)))
const employeeName = (id: string | null) => employeeDisplayName(store.employees.find((employee) => employee.id === id)?.name ?? (id ?? '系统更新'))
const eventTaskTitle = (id: string | null) => store.tasks.find((task) => task.id === id)?.title ?? '任务状态已更新'
const eventSummary = (event: AstraEvent) => {
  const name = employeeName(event.employee_id)
  return ({
    TASK_ASSIGNED: `${name} 已领取任务`,
    TASK_RUNNING: `${name} 开始或恢复任务`,
    WAIT_HUMAN: `${name} 请求人工协助`,
    TASK_SUSPENDED: `${name} 暂停任务`,
    RESULT_SUBMITTED: `${name} 提交任务结果`,
    TASK_COMPLETED: `${name} 完成任务`,
    EXECUTION_ERROR: `${name} 出现执行异常`,
    TASK_FAILED: `${name} 任务执行失败`,
    TASK_CANCELLED: '任务已取消',
  }[event.event_type] ?? '任务状态已更新')
}
const roleGroups = computed(() => {
  const groups = new Map<string, { count: number; working: number }>()
  for (const employee of store.employees) { const group = groups.get(employee.role) ?? { count: 0, working: 0 }; group.count += 1; if (employee.status === 'WORKING') group.working += 1; groups.set(employee.role, group) }
  return [...groups.entries()].map(([role, value]) => ({ role, label: `${role.replace(/(?:数字)?员工$|专员$|工程师$/u, '').trim() || role}区`, ...value }))
})
const eventIcon = (type: string) => type === 'WAIT_HUMAN' ? CircleAlert : type === 'TASK_COMPLETED' ? Check : Play
const eventTone = (type: string) => type === 'WAIT_HUMAN' ? 'warning' : type === 'TASK_COMPLETED' ? 'success' : ['EXECUTION_ERROR', 'TASK_FAILED'].includes(type) ? 'danger' : 'info'
</script>
