<template>
  <div class="page dashboard-page" data-testid="dashboard-page">
    <section class="page-intro">
      <div><span class="kicker"><Activity :size="13" /> RUNTIME OVERVIEW</span><h2>数字员工运行态势</h2><p>任务发现、执行、验证与人工介入的统一控制面。</p></div>
      <div class="intro-state"><span>系统状态</span><strong><i /> 全部服务正常</strong><small>上次同步 {{ lastSync }}</small></div>
    </section>

    <section class="metrics-grid">
      <AstraMetricCard label="在线员工" :value="store.metrics?.online_employees ?? '—'" unit="人" hint="Astra-01 心跳正常" :icon="Bot" />
      <AstraMetricCard label="运行中任务" :value="store.metrics?.running_tasks ?? '—'" unit="项" hint="任务闭环持续推进" :icon="Workflow" />
      <AstraMetricCard label="等待人工" :value="store.metrics?.wait_human_tasks ?? '—'" unit="项" hint="需要业务或环境输入" :icon="Hand" tone="warning" />
      <AstraMetricCard label="今日完成" :value="store.metrics?.completed_today ?? '—'" unit="项" hint="均经过独立验证" :icon="BadgeCheck" tone="success" />
    </section>

    <section class="dashboard-grid">
      <AstraPanel class="trend-panel" title="今日任务趋势" subtitle="创建 / 完成 / 失败">
        <template #action><div class="chart-legend"><span data-tone="info">创建</span><span data-tone="success">完成</span><span data-tone="danger">失败</span></div></template>
        <TrendChart />
      </AstraPanel>

      <AstraPanel title="数字员工状态" subtitle="长期在线岗位实例">
        <template #action><RouterLink class="text-link" to="/employees">查看全部 <ArrowUpRight :size="13" /></RouterLink></template>
        <article v-for="employee in store.employees" :key="employee.id" class="employee-summary">
          <div class="employee-avatar"><Bot :size="25" /><i /></div>
          <div class="employee-copy"><div><strong>{{ employee.name }}</strong><AstraStatusBadge :status="employee.status" pulse /></div><p>{{ employee.role }}</p><small>在线 {{ formatDuration(employee.online_since) }} · {{ employee.capabilities.length }} 项能力</small></div>
          <RouterLink :to="`/employees/${employee.id}`" aria-label="查看员工"><ChevronRight :size="18" /></RouterLink>
        </article>
      </AstraPanel>

      <AstraPanel class="active-panel" title="当前活跃任务" subtitle="按优先级与创建时间调度" flush>
        <template #action><RouterLink class="text-link" to="/tasks">进入任务中心 <ArrowUpRight :size="13" /></RouterLink></template>
        <div class="table-wrap">
          <table>
            <thead><tr><th>任务</th><th>来源</th><th>状态</th><th>员工</th><th>当前阶段</th><th>进度</th></tr></thead>
            <tbody>
              <tr v-for="task in store.activeTasks" :key="task.id" @click="$router.push(`/tasks/${task.id}`)">
                <td><strong>{{ task.id }}</strong><small>{{ task.title }}</small></td><td>{{ sourceLabel(task.source) }}</td><td><AstraStatusBadge :status="task.status" pulse /></td><td>{{ task.employee_id ?? '待分配' }}</td><td>{{ phaseLabel(task.current_phase) }}</td><td><span class="progress-value">{{ task.progress }}%</span><AstraProgress :value="task.progress" /></td>
              </tr>
              <tr v-if="!store.activeTasks.length"><td colspan="6" class="empty-cell">当前没有活跃任务</td></tr>
            </tbody>
          </table>
        </div>
      </AstraPanel>

      <AstraPanel title="系统动态" subtitle="来自持久化 Event 的最新变化">
        <div class="event-feed">
          <article v-for="event in store.events.slice(0, 6)" :key="event.id"><span class="event-dot" :data-tone="event.event_type.includes('FAILED') || event.event_type === 'WAIT_HUMAN' ? 'warning' : event.event_type.includes('COMPLETED') ? 'success' : 'info'"><component :is="eventIcon(event.event_type)" :size="13" /></span><div><strong>{{ event.message }}</strong><p>{{ event.task_id ?? '系统事件' }} · {{ phaseLabel(event.phase) }}</p></div><time>{{ formatTime(event.created_at) }}</time></article>
        </div>
      </AstraPanel>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Activity, ArrowUpRight, BadgeCheck, Bot, Check, ChevronRight, CircleAlert, Hand, Play, RotateCcw, Workflow } from 'lucide-vue-next'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AstraMetricCard from '@/components/astra/AstraMetricCard.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraProgress from '@/components/astra/AstraProgress.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import TrendChart from '@/components/runtime/TrendChart.vue'
import { useAstraStore } from '@/stores/astra'
import { formatDuration, formatTime, phaseLabel, sourceLabel } from '@/utils/format'

const store = useAstraStore()
const lastSync = computed(() => store.lastUpdated ? store.lastUpdated.toLocaleTimeString('zh-CN', { hour12: false }) : '连接中')
const eventIcon = (type: string) => type.includes('FAILED') || type === 'WAIT_HUMAN' ? CircleAlert : type.includes('COMPLETED') || type.includes('PASSED') ? Check : type.includes('RETRY') || type.includes('REPAIR') ? RotateCcw : Play
</script>
