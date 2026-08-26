<template>
  <div v-if="employee" class="page" data-testid="employee-detail-page">
    <div class="detail-nav"><RouterLink to="/employees"><ArrowLeft :size="14" /> 数字员工</RouterLink><span>/</span><strong>{{ employee.name }}</strong></div>
    <section class="employee-hero">
      <div class="employee-avatar employee-avatar--hero"><Bot :size="42" /><i /></div>
      <div class="employee-hero__identity"><div><span>{{ employee.id }}</span><AstraStatusBadge :status="employee.status" pulse /></div><h2>{{ employee.name }}</h2><p>{{ employee.role }} · {{ employee.description }}</p></div>
      <div class="hero-actions"><RouterLink class="button" :to="`/settings?employee=${employee.id}`"><Settings2 :size="14" /> 编辑配置</RouterLink><button v-if="employee.status !== 'PAUSED'" class="button" @click="employeeAction('pause')"><Pause :size="14" /> 暂停员工</button><button v-else class="button button--primary" @click="employeeAction('resume')"><Play :size="14" /> 恢复员工</button></div>
    </section>

    <section class="metrics-grid employee-metrics metrics-grid--six">
      <AstraMetricCard label="今日 Token" :value="formatTokens(employee.today_usage.total_tokens)" hint="仅统计实际返回" :icon="Binary" />
      <AstraMetricCard label="工具调用" :value="employee.today_usage.tool_call_count ?? '—'" unit="次" hint="成功与失败均保留" :icon="Wrench" />
      <AstraMetricCard label="今日完成" :value="employee.today_completed" unit="项" hint="Verifier 已通过" :icon="BadgeCheck" tone="success" />
      <AstraMetricCard label="今日工作时长" :value="formatDurationSeconds(employee.today_usage.duration_seconds)" hint="按 Run 聚合" :icon="Clock3" />
      <AstraMetricCard label="自主完成率" :value="formatRate(usage?.performance.autonomous_completion_rate)" unit="%" hint="无需人工介入" :icon="Sparkles" tone="success" />
      <AstraMetricCard label="任务成功率" :value="formatRate(employee.success_rate)" unit="%" hint="完成任务占比" :icon="ShieldCheck" tone="success" />
    </section>

    <section class="detail-grid">
      <AstraPanel title="默认 OpenCode 执行环境" subtitle="每位数字员工固定关联一个默认环境">
        <template #action><button class="button button--compact" :disabled="checking" data-testid="test-environment" @click="testEnvironment"><RefreshCw :size="13" :class="{ spin: checking }" /> {{ checking ? '检查中' : '检测环境' }}</button></template>
        <div v-if="employee.execution_environment" class="environment-detail">
          <div class="environment-detail__title"><span><Server :size="20" /></span><div><strong>{{ environmentLabel(employee.execution_environment) }}</strong><small>{{ employee.execution_environment.description || '默认 OpenCode 运行环境' }}</small></div><AstraStatusBadge :status="employee.execution_environment.status" /></div>
          <dl class="info-list"><div><dt>模式</dt><dd>{{ employee.execution_environment.mode }}</dd></div><div><dt>OpenCode</dt><dd>{{ employee.execution_environment.opencode_path }}</dd></div><div><dt>Workspace 根目录</dt><dd>{{ employee.execution_environment.workspace_root }}</dd></div><div v-if="employee.execution_environment.mode === 'LINUX_REMOTE'"><dt>SSH 主机</dt><dd>{{ employee.execution_environment.username }}@{{ employee.execution_environment.host }}:{{ employee.execution_environment.port }}</dd></div><div><dt>最近检测</dt><dd>{{ formatTime(employee.execution_environment.last_checked_at) }}</dd></div></dl>
          <div v-if="environmentChecks.length" class="environment-checks"><article v-for="check in environmentChecks" :key="check.name"><CheckCircle2 v-if="check.passed" :size="14" /><CircleX v-else :size="14" /><div><strong>{{ check.name }}</strong><small>{{ check.detail }}</small></div></article></div>
        </div>
        <AstraEmptyState v-else :icon="ServerOff" title="未配置执行环境" description="前往配置中心为员工绑定一个本地或 Linux 远程环境。"><RouterLink class="button" :to="`/settings?employee=${employee.id}`">立即配置</RouterLink></AstraEmptyState>
      </AstraPanel>

      <AstraPanel title="当前任务" subtitle="环境快照随任务固定，不受后续配置变更影响">
        <template #action><RouterLink v-if="currentTask" class="text-link" :to="`/tasks/${currentTask.id}`">查看详情 <ArrowUpRight :size="13" /></RouterLink></template>
        <div v-if="currentTask" class="current-task-card"><div class="current-task-card__top"><div><small>{{ currentTask.id }}</small><h3>{{ currentTask.title }}</h3></div><AstraStatusBadge :status="currentTask.status" pulse /></div><dl><div><dt>来源</dt><dd>{{ sourceLabel(currentTask.source) }}</dd></div><div><dt>阶段</dt><dd>{{ phaseLabel(currentTask.current_phase) }}</dd></div><div><dt>环境</dt><dd>{{ environmentLabel(currentTask.execution_environment_snapshot) }}</dd></div><div><dt>时长</dt><dd>{{ formatDuration(currentTask.started_at) }}</dd></div></dl><div class="path-row"><FolderOpen :size="13" /><span>{{ currentTask.workspace ?? 'Workspace 待创建' }}</span></div><div class="path-row"><TerminalSquare :size="13" /><span>{{ currentTask.opencode_session_id ?? 'Session 待创建' }}</span></div><div class="current-progress"><span>整体进度 <strong>{{ currentTask.progress }}%</strong></span><AstraProgress :value="currentTask.progress" /></div></div>
        <AstraEmptyState v-else :icon="Coffee" title="当前空闲" description="员工正在等待 Dispatcher 分配下一项匹配任务。" />
      </AstraPanel>

      <AstraPanel title="今日 Token 明细" subtitle="实际返回值；缺失项不估算"><div class="token-breakdown"><article><small>Input</small><strong>{{ formatTokens(employee.today_usage.input_tokens) }}</strong></article><article><small>Output</small><strong>{{ formatTokens(employee.today_usage.output_tokens) }}</strong></article><article><small>Cache Read</small><strong>{{ formatTokens(employee.today_usage.cache_read_tokens) }}</strong></article><article><small>Cache Write</small><strong>{{ formatTokens(employee.today_usage.cache_write_tokens) }}</strong></article><article><small>Total</small><strong>{{ formatTokens(employee.today_usage.total_tokens) }}</strong></article><article><small>LLM 调用</small><strong>{{ employee.today_usage.llm_call_count ?? '—' }}</strong></article><article><small>平均每任务 Token</small><strong>{{ averageTaskTokens }}</strong></article><article><small>平均每任务 Tool</small><strong>{{ averageTaskTools }}</strong></article></div></AstraPanel>

      <AstraPanel title="能力与自主策略" subtitle="调度匹配与工作边界"><div class="capability-detail"><h4>能力标签</h4><div class="capability-list"><span v-for="capability in employee.capabilities" :key="capability">{{ capability }}</span></div><h4>技能标签</h4><div class="capability-list"><span v-for="skill in employee.skills" :key="skill">{{ skill }}</span><span v-if="!employee.skills.length">未配置</span></div><h4>工作策略</h4><div class="policy-summary"><span>自动领取 <b>{{ yesNo(employee.auto_claim) }}</b></span><span>自动执行 <b>{{ yesNo(employee.auto_execute) }}</b></span><span>自动修复 <b>{{ yesNo(employee.auto_repair) }}</b></span><span>重试 / 并发 <b>{{ employee.max_auto_retries }} / {{ employee.max_concurrency }}</b></span></div></div></AstraPanel>

      <AstraPanel class="detail-wide" title="工作消耗趋势" subtitle="Token 数据来自 OpenCode，无法获取时显示为 —">
        <template #action><div class="range-switch"><button :class="{ active: days === 7 }" @click="changeDays(7)">近 7 天</button><button :class="{ active: days === 30 }" @click="changeDays(30)">近 30 天</button></div></template>
        <UsageTrendChart :data="usage?.trend ?? []" />
      </AstraPanel>

      <AstraPanel title="工作结果" :subtitle="`近 ${days} 天`"><dl class="performance-list"><div><dt>完成任务</dt><dd>{{ usage?.performance.completed_tasks ?? 0 }}</dd></div><div><dt>自主完成率</dt><dd>{{ rateText(usage?.performance.autonomous_completion_rate) }}</dd></div><div><dt>人工介入率</dt><dd>{{ rateText(usage?.performance.human_intervention_rate) }}</dd></div><div><dt>任务成功率</dt><dd>{{ rateText(usage?.performance.success_rate) }}</dd></div><div><dt>平均重试</dt><dd>{{ decimalText(usage?.performance.average_retries) }}</dd></div><div><dt>平均耗时</dt><dd>{{ formatDurationSeconds(usage?.performance.average_duration_seconds) }}</dd></div></dl></AstraPanel>

      <AstraPanel title="工具调用 Top" :subtitle="`近 ${days} 天实际工具事件`"><div class="tool-ranking"><article v-for="(tool, index) in usage?.tools.slice(0, 8)" :key="tool.tool_name"><b>{{ index + 1 }}</b><div><strong>{{ tool.tool_name }}</strong><small>成功 {{ tool.success_count }} · 失败 {{ tool.failure_count }}</small></div><span>{{ tool.call_count }} 次</span></article><AstraEmptyState v-if="!usage?.tools.length" :icon="Wrench" title="暂无工具数据" description="OpenCode 返回工具调用事件后会在此汇总。" /></div></AstraPanel>

      <AstraPanel class="detail-wide" title="处理记录" subtitle="失败、终止和等待人工的消耗同样保留" flush><div class="table-wrap"><table><thead><tr><th>任务</th><th>类型</th><th>环境</th><th>状态</th><th>重试</th><th>耗时</th></tr></thead><tbody><tr v-for="task in employeeTasks" :key="task.id" @click="$router.push(`/tasks/${task.id}`)"><td><strong>{{ task.id }}</strong><small>{{ task.title }}</small></td><td>{{ task.task_type }}</td><td>{{ environmentLabel(task.execution_environment_snapshot) }}</td><td><AstraStatusBadge :status="task.status" /></td><td>{{ task.retry_count }} 次</td><td>{{ formatDuration(task.started_at, task.finished_at) }}</td></tr></tbody></table></div></AstraPanel>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ArrowLeft, ArrowUpRight, BadgeCheck, Binary, Bot, CheckCircle2, CircleX, Clock3, Coffee, FolderOpen, Pause, Play, RefreshCw, Server, ServerOff, Settings2, ShieldCheck, Sparkles, TerminalSquare, Wrench } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@/api/client'
import type { EmployeeUsage } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraMetricCard from '@/components/astra/AstraMetricCard.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraProgress from '@/components/astra/AstraProgress.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import UsageTrendChart from '@/components/runtime/UsageTrendChart.vue'
import { useAstraStore } from '@/stores/astra'
import { environmentLabel, formatDuration, formatDurationSeconds, formatTime, formatTokens, phaseLabel, sourceLabel } from '@/utils/format'

const route = useRoute()
const store = useAstraStore()
const id = computed(() => String(route.params.id))
const usage = ref<EmployeeUsage | null>(null)
const days = ref(7)
const checking = ref(false)
const environmentChecks = ref<Array<{ name: string; passed: boolean; detail: string }>>([])
const employee = computed(() => store.employees.find((item) => item.id === id.value))
const employeeTasks = computed(() => store.tasks.filter((task) => task.employee_id === id.value))
const currentTask = computed(() => employeeTasks.value.find((task) => ['CLAIMED', 'RUNNING', 'VERIFYING', 'RETRY'].includes(task.status)))
const averageTaskTokens = computed(() => employee.value?.today_usage.total_tokens != null && employee.value.today_usage.task_count ? formatTokens(Math.round(employee.value.today_usage.total_tokens / employee.value.today_usage.task_count)) : '—')
const averageTaskTools = computed(() => employee.value?.today_usage.tool_call_count != null && employee.value.today_usage.task_count ? (employee.value.today_usage.tool_call_count / employee.value.today_usage.task_count).toFixed(1) : '—')

async function load() { await store.refresh(); usage.value = await api.employeeUsage(id.value, days.value) }
onMounted(load)
async function changeDays(value: number) { days.value = value; usage.value = await api.employeeUsage(id.value, value) }
async function employeeAction(action: 'pause' | 'resume') { await api.employeeAction(id.value, action); await store.refresh() }
async function testEnvironment() {
  checking.value = true
  try { const result = await api.testEnvironment(id.value); environmentChecks.value = result.checks; await store.refresh() }
  catch (error) { window.alert(error instanceof Error ? error.message : '环境检测失败') }
  finally { checking.value = false }
}
const formatRate = (value: number | null | undefined) => value == null ? '—' : Math.round(value)
const rateText = (value: number | null | undefined) => value == null ? '—' : `${value.toFixed(1)}%`
const decimalText = (value: number | null | undefined) => value == null ? '—' : value.toFixed(1)
const yesNo = (value: boolean) => value ? '开启' : '关闭'
</script>
