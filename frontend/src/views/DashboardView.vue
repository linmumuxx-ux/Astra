<template>
  <div class="page dashboard-page" data-testid="dashboard-page">
    <section class="page-intro">
      <div><h2>总览</h2><p>查看数字员工当前工作、任务状态与今日消耗。</p></div>
      <div class="intro-state"><span>数据状态</span><strong :class="{ 'connection--offline': !dataHealthy }"><i /> {{ store.error ? '业务数据异常' : store.realtimeConnected ? '实时连接正常' : '正在重连' }}</strong><small>更新于 {{ lastSync }}</small></div>
    </section>

    <section class="metrics-grid metrics-grid--seven" data-testid="dashboard-v03-metrics">
      <AstraMetricCard label="工作中" :value="store.metrics?.running_tasks ?? '—'" unit="人" hint="正在自主处理" :icon="Bot" />
      <AstraMetricCard label="空闲员工" :value="store.metrics?.idle_employees ?? '—'" unit="人" hint="等待下一项任务" :icon="Activity" />
      <AstraMetricCard label="等待人工" :value="store.metrics?.wait_human_tasks ?? '—'" unit="项" hint="需要补充信息" :icon="Hand" tone="warning" />
      <AstraMetricCard label="执行异常" :value="store.metrics?.execution_error_tasks ?? '—'" unit="项" hint="工作现场已保留" :icon="CircleAlert" tone="warning" />
      <AstraMetricCard label="今日完成" :value="store.metrics?.completed_today ?? '—'" unit="项" hint="员工已提交结果" :icon="BadgeCheck" tone="success" />
      <AstraMetricCard label="今日模型用量" :value="formatTokens(store.metrics?.today_tokens)" hint="OpenCode 实际 Token" :icon="Binary" />
      <AstraMetricCard label="今日工具调用" :value="store.metrics?.today_tool_calls ?? '—'" unit="次" hint="OpenCode 实际记录" :icon="Wrench" />
    </section>

    <section class="dashboard-grid">
      <AstraPanel class="active-panel" title="数字办公室" subtitle="员工工位与当前工作状态" flush><DigitalOffice :employees="store.employees" :tasks="store.tasks" /></AstraPanel>

      <AstraPanel title="平台动态" subtitle="来自任务和员工的真实记录">
        <div class="event-feed">
          <article v-for="event in store.events.slice(0, 7)" :key="event.id">
            <span class="event-dot" :data-tone="event.event_type === 'WAIT_HUMAN' ? 'warning' : event.event_type === 'TASK_COMPLETED' ? 'success' : 'info'"><component :is="eventIcon(event.event_type)" :size="13" /></span>
            <div><strong>{{ event.message }}</strong><p>{{ event.employee_id ?? event.task_id ?? '平台事件' }}</p></div><time>{{ formatTime(event.created_at) }}</time>
          </article>
          <AstraEmptyState v-if="!store.events.length" :icon="Activity" title="暂无动态" description="员工领取、更新或完成任务后会显示在这里。" />
        </div>
      </AstraPanel>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Activity, BadgeCheck, Binary, Bot, Check, CircleAlert, Hand, Play, Wrench } from 'lucide-vue-next'
import { computed } from 'vue'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraMetricCard from '@/components/astra/AstraMetricCard.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import DigitalOffice from '@/components/office/DigitalOffice.vue'
import { useAstraStore } from '@/stores/astra'
import { formatTime, formatTokens } from '@/utils/format'

const store = useAstraStore()
const dataHealthy = computed(() => store.realtimeConnected && !store.error)
const lastSync = computed(() => store.lastUpdated?.toLocaleTimeString('zh-CN', { hour12: false }) ?? '连接中')
const eventIcon = (type: string) => type === 'WAIT_HUMAN' ? CircleAlert : type === 'TASK_COMPLETED' ? Check : Play
</script>
