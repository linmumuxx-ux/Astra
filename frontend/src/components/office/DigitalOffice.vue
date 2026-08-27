<template>
  <div class="digital-office" :class="{ 'digital-office--reduced': reducedMotion }">
    <button
      v-for="employee in employees"
      :key="employee.id"
      class="workstation"
      :class="{ 'workstation--completed': completedIds.has(employee.id), active: selected?.id === employee.id }"
      :data-status="employee.status"
      @click="selectedId = selectedId === employee.id ? '' : employee.id"
    >
      <span class="workstation__scene">
        <i class="desk" />
        <i class="screen"><span /></i>
        <span class="employee-figure"><Bot :size="22" /></span>
        <span v-if="employee.status === 'WORKING'" class="activity-wave"><i /><i /><i /></span>
        <span v-else-if="employee.status === 'WAIT_HUMAN'" class="attention-mark">!</span>
        <span v-else-if="employee.status === 'ERROR'" class="error-mark">×</span>
      </span>
      <span class="workstation__copy">
        <strong>{{ employee.name }}</strong>
        <small>{{ employee.role }}</small>
        <span><AstraStatusBadge :status="employee.status" :pulse="employee.status === 'WORKING'" /></span>
        <em>{{ platformCopy(currentTask(employee.id)?.current_progress) || statusCopy(employee.status) }}</em>
      </span>
    </button>
    <aside v-if="selected" class="office-inspector">
      <div><small>{{ selected.id }}</small><strong>{{ selected.name }}</strong><span>{{ selected.role }}</span></div>
      <dl><div><dt>当前任务</dt><dd>{{ selectedTask?.title ?? '暂无' }}</dd></div><div><dt>最新进展</dt><dd>{{ platformCopy(selectedTask?.current_progress) || statusCopy(selected.status) }}</dd></div><div><dt>最近活动</dt><dd>{{ formatTime(selectedTask?.last_activity_at ?? selected.last_heartbeat) }}</dd></div><div><dt>工作时长</dt><dd>{{ formatDuration(selectedTask?.started_at ?? null) }}</dd></div><div><dt>Token</dt><dd>{{ formatTokens(selected.today_usage.total_tokens) }}</dd></div><div><dt>工具调用</dt><dd>{{ selected.today_usage.tool_call_count ?? '—' }}</dd></div></dl>
      <nav><RouterLink class="button" :to="`/employees/${selected.id}`">员工详情</RouterLink><RouterLink v-if="selectedTask" class="button button--primary" :to="`/tasks/${selectedTask.id}`">任务详情</RouterLink></nav>
    </aside>
    <AstraEmptyState v-if="!employees.length" :icon="Bot" title="办公室暂无员工" description="在配置中心创建并启用数字员工。" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Bot } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import type { Employee, Task } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import { formatDuration, formatTime, formatTokens, platformCopy } from '@/utils/format'

const props = defineProps<{ employees: Employee[]; tasks: Task[] }>()
const selectedId = ref('')
const completedIds = ref(new Set<string>())
const priorStatus = new Map<string, string>()
const reducedMotion = computed(() => localStorage.getItem('astra-reduced-motion') === 'true')
const selected = computed(() => props.employees.find((employee) => employee.id === selectedId.value))
const selectedTask = computed(() => selected.value ? currentTask(selected.value.id) : undefined)
const currentTask = (employeeId: string) => props.tasks.find((task) => task.employee_id === employeeId && ['READY', 'RUNNING', 'WAIT_HUMAN', 'EXECUTION_ERROR'].includes(task.status))
const statusCopy = (status: string) => ({ IDLE: '等待新任务', PAUSED: '员工已暂停', OFFLINE: '当前离线', ERROR: '等待恢复执行环境' }[status] ?? '等待任务状态更新')
watch(() => props.employees.map((employee) => ({ id: employee.id, status: employee.status })), (employees) => { for (const employee of employees) { if (priorStatus.get(employee.id) === 'WORKING' && employee.status === 'IDLE') { completedIds.value = new Set([...completedIds.value, employee.id]); window.setTimeout(() => { const next = new Set(completedIds.value); next.delete(employee.id); completedIds.value = next }, 1800) } priorStatus.set(employee.id, employee.status) } }, { immediate: true })
</script>

<style scoped>
.digital-office { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; padding: 16px; background: radial-gradient(circle at 50% 0%, rgba(33, 102, 190, .16), transparent 52%), linear-gradient(180deg, rgba(8, 18, 35, .72), rgba(5, 12, 24, .94)); }
.workstation { min-height: 190px; overflow: hidden; padding: 0; color: inherit; text-align: left; border: 1px solid var(--astra-border); border-radius: 12px; background: rgba(10, 25, 46, .86); cursor: pointer; transition: border-color .2s, transform .2s; }
.workstation:hover { border-color: var(--blue); transform: translateY(-2px); }
.workstation__scene { position: relative; display: block; height: 102px; background: linear-gradient(180deg, rgba(31, 67, 116, .32), rgba(8, 18, 33, .12)); }
.desk { position: absolute; left: 15%; right: 15%; bottom: 17px; height: 8px; border-radius: 3px; background: #24405e; box-shadow: 0 18px 0 -3px #182b41; }
.screen { position: absolute; left: 25%; bottom: 28px; width: 58px; height: 39px; border: 4px solid #263e5b; border-radius: 4px; background: #071523; box-shadow: 0 0 17px rgba(47, 130, 255, .2); }
.screen span { display: block; width: 72%; height: 2px; margin: 11px 5px; background: #2d7cff; box-shadow: 0 7px 0 #25b6a3; }
.employee-figure { position: absolute; right: 23%; bottom: 27px; display: grid; width: 42px; height: 42px; place-items: center; border-radius: 50%; color: #d9eaff; background: linear-gradient(145deg, #315b8b, #152a44); }
.activity-wave { position: absolute; top: 13px; left: 17px; display: flex; align-items: end; gap: 3px; height: 18px; }
.activity-wave i { width: 3px; height: 7px; border-radius: 2px; background: #3b8cff; animation: work-pulse 1.1s ease-in-out infinite; }
.activity-wave i:nth-child(2) { height: 15px; animation-delay: .18s; }.activity-wave i:nth-child(3) { height: 10px; animation-delay: .36s; }
.attention-mark,.error-mark { position: absolute; top: 12px; right: 14px; display: grid; width: 25px; height: 25px; place-items: center; border-radius: 50%; font-weight: 800; color: #09111e; background: #f4b94d; }
.error-mark { color: white; background: #e45c68; }
.workstation__copy { display: grid; grid-template-columns: 1fr auto; gap: 3px 8px; padding: 12px 14px; }.workstation__copy strong { font-size: 14px; }.workstation__copy small { grid-column: 1; color: var(--astra-text-muted); }.workstation__copy > span { grid-column: 2; grid-row: 1 / span 2; }.workstation__copy em { grid-column: 1 / -1; overflow: hidden; margin-top: 5px; color: #a9bbcf; font-size: 12px; font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.workstation[data-status='WORKING'] { border-color: rgba(55, 134, 255, .52); }.workstation[data-status='WAIT_HUMAN'] { border-color: rgba(244, 185, 77, .48); }.workstation[data-status='ERROR'] { border-color: rgba(228, 92, 104, .55); }
.workstation.active { outline: 1px solid rgba(82, 153, 255, .62); }.workstation--completed { animation: completed-glow 1.8s ease-out; }
.office-inspector { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(150px, .6fr) 2fr auto; gap: 18px; align-items: center; padding: 15px; border: 1px solid rgba(67, 139, 237, .42); border-radius: 10px; background: rgba(12, 29, 53, .92); }.office-inspector > div { display: grid; gap: 3px; }.office-inspector small,.office-inspector span,.office-inspector dt { color: var(--astra-text-muted); font-size: 11px; }.office-inspector strong { font-size: 16px; }.office-inspector dl { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 14px; margin: 0; }.office-inspector dl div { min-width: 0; }.office-inspector dd { overflow: hidden; margin: 3px 0 0; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.office-inspector nav { display: flex; gap: 7px; }
.digital-office--reduced * { animation: none !important; transition: none !important; }
@keyframes work-pulse { 50% { height: 18px; opacity: .65; } }
@keyframes completed-glow { 25% { border-color: #4fd6a6; box-shadow: 0 0 28px rgba(79, 214, 166, .35); } }
@media (max-width: 900px) { .office-inspector { grid-template-columns: 1fr; }.office-inspector dl { grid-template-columns: repeat(2, 1fr); } }
</style>
