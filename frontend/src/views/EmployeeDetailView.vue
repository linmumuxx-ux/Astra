<template>
  <div class="page" v-if="employee">
    <div class="detail-nav"><RouterLink to="/employees"><ArrowLeft :size="14" /> 数字员工</RouterLink><span>/</span><strong>{{ employee.name }}</strong></div>
    <section class="employee-hero">
      <div class="employee-avatar employee-avatar--hero"><Bot :size="42" /><i /></div>
      <div class="employee-hero__identity"><div><span>{{ employee.id }}</span><AstraStatusBadge :status="employee.status" pulse /></div><h2>{{ employee.name }}</h2><p>{{ employee.role }} · {{ employee.description }}</p></div>
      <div class="hero-actions"><button v-if="employee.status !== 'PAUSED'" class="button" @click="employeeAction('pause')"><Pause :size="14" /> 暂停员工</button><button v-else class="button button--primary" @click="employeeAction('resume')"><Play :size="14" /> 恢复员工</button></div>
    </section>
    <section class="metrics-grid employee-metrics">
      <AstraMetricCard label="在线时长" :value="formatDuration(employee.online_since)" hint="Heartbeat 10 秒" :icon="Clock3" />
      <AstraMetricCard label="自主完成率" value="92" unit="%" hint="无需人工持续对话" :icon="BadgeCheck" tone="success" />
      <AstraMetricCard label="平均重试" value="0.8" unit="次" hint="失败后恢复原 Session" :icon="RotateCcw" />
      <AstraMetricCard label="任务通过率" value="96" unit="%" hint="以 Verifier 结果为准" :icon="ShieldCheck" tone="success" />
    </section>
    <section class="detail-grid">
      <AstraPanel title="当前任务" subtitle="Workspace 与 OpenCode Session 按任务隔离">
        <template #action><RouterLink v-if="currentTask" class="text-link" :to="`/tasks/${currentTask.id}`">查看详情 <ArrowUpRight :size="13" /></RouterLink></template>
        <div v-if="currentTask" class="current-task-card"><div class="current-task-card__top"><div><small>{{ currentTask.id }}</small><h3>{{ currentTask.title }}</h3></div><AstraStatusBadge :status="currentTask.status" pulse /></div><dl><div><dt>来源</dt><dd>{{ sourceLabel(currentTask.source) }}</dd></div><div><dt>当前阶段</dt><dd>{{ phaseLabel(currentTask.current_phase) }}</dd></div><div><dt>开始时间</dt><dd>{{ formatTime(currentTask.started_at) }}</dd></div><div><dt>运行时长</dt><dd>{{ formatDuration(currentTask.started_at) }}</dd></div></dl><div class="path-row"><FolderOpen :size="13" /><span>{{ currentTask.workspace ?? 'Workspace 待创建' }}</span></div><div class="path-row"><TerminalSquare :size="13" /><span>{{ currentTask.opencode_session_id ?? 'Session 待创建' }}</span></div><div class="current-progress"><span>整体进度 <strong>{{ currentTask.progress }}%</strong></span><AstraProgress :value="currentTask.progress" /></div></div>
        <AstraEmptyState v-else :icon="Coffee" title="当前空闲" description="Astra-01 正在等待 Dispatcher 分配下一项任务。" />
      </AstraPanel>
      <AstraPanel title="能力与任务范围" subtitle="用于 Dispatcher 确定性匹配">
        <div class="capability-detail"><h4>能力标签</h4><div class="capability-list"><span v-for="capability in employee.capabilities" :key="capability">{{ capability }}</span></div><h4>任务来源范围</h4><div class="source-scope"><Database :size="15" /><div><strong>{{ employee.source_scope.join(' · ') }}</strong><small>仅允许领取范围内来源任务</small></div></div><h4>并发约束</h4><div class="concurrency-row"><span>当前负载</span><strong>{{ employee.current_task_count }} / {{ employee.max_concurrency }}</strong></div><AstraProgress :value="employee.current_task_count / employee.max_concurrency * 100" /></div>
      </AstraPanel>
      <AstraPanel class="detail-wide" title="今日处理记录" subtitle="完成状态只接受独立验证结果" flush><div class="table-wrap"><table><thead><tr><th>任务</th><th>类型</th><th>状态</th><th>重试</th><th>耗时</th><th>结果</th></tr></thead><tbody><tr v-for="task in employeeTasks" :key="task.id" @click="$router.push(`/tasks/${task.id}`)"><td><strong>{{ task.id }}</strong><small>{{ task.title }}</small></td><td>{{ task.task_type }}</td><td><AstraStatusBadge :status="task.status" /></td><td>{{ task.retry_count }} 次</td><td>{{ formatDuration(task.started_at, task.finished_at) }}</td><td>{{ task.status === 'COMPLETED' ? 'PASS' : task.failure_reason ?? '处理中' }}</td></tr></tbody></table></div></AstraPanel>
    </section>
  </div>
</template>
<script setup lang="ts">
import { Activity, ArrowLeft, ArrowUpRight, BadgeCheck, Bot, Clock3, Coffee, Database, FolderOpen, Pause, Play, RotateCcw, ShieldCheck, TerminalSquare } from 'lucide-vue-next'
import { computed, onMounted } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@/api/client'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraMetricCard from '@/components/astra/AstraMetricCard.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraProgress from '@/components/astra/AstraProgress.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
import { formatDuration, formatTime, phaseLabel, sourceLabel } from '@/utils/format'
const route = useRoute(); const store = useAstraStore(); const id = computed(() => String(route.params.id))
const employee = computed(() => store.employees.find((item) => item.id === id.value)); const employeeTasks = computed(() => store.tasks.filter((task) => task.employee_id === id.value)); const currentTask = computed(() => employeeTasks.value.find((task) => ['CLAIMED','RUNNING','VERIFYING','RETRY'].includes(task.status)))
onMounted(() => store.refresh())
async function employeeAction(action: 'pause'|'resume') { await api.employeeAction(id.value, action); await store.refresh() }
</script>
