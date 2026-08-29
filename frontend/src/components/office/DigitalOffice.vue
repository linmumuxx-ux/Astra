<template>
  <div class="digital-office" :class="{ 'digital-office--reduced': reducedMotion }">
    <div class="office-scene">
      <div class="office-scene__backdrop" />
      <div class="office-scene__depth" />
      <div class="workstation-grid">
        <button
          v-for="(employee, index) in visibleEmployees"
          :key="employee.id"
          class="workstation"
          :class="{ active: selected?.id === employee.id, 'workstation--completed': completedIds.has(employee.id) }"
          :data-status="employee.status"
          :aria-label="`${employeeDisplayName(employee.name)} ${employee.role} ${statusLabel(employee.status)}`"
          @click="selectedId = selectedId === employee.id ? '' : employee.id"
        >
          <span class="workstation__header">
            <span class="workstation__number"><small>工位 </small>{{ String(index + 1).padStart(2, '0') }}</span>
            <AstraStatusBadge :status="employee.status" :pulse="employee.status === 'WORKING'" />
          </span>
          <EmployeeWorkstation :employee-id="employee.id" :status="employee.status" :variant="index + 1" />
          <span class="workstation__info">
            <span class="workstation__identity"><strong>{{ employeeDisplayName(employee.name) }}</strong><small>{{ employee.role }}</small></span>
            <span class="workstation__activity"><small>{{ activityLabel(employee.status) }}</small><strong>{{ currentTask(employee)?.title ?? idleTitle(employee.status) }}</strong></span>
          </span>
        </button>
      </div>
    </div>

    <aside v-if="selected" class="office-inspector">
      <div class="office-inspector__identity">
        <small>当前选中</small>
        <strong>{{ employeeDisplayName(selected.name) }}</strong>
        <span>{{ selected.role }}</span>
      </div>
      <dl>
        <div><dt>当前任务</dt><dd>{{ selectedTask?.title ?? '暂无任务' }}</dd></div>
        <div><dt>当前进展</dt><dd>{{ platformCopy(selectedTask?.current_progress) || statusCopy(selected.status) }}</dd></div>
        <div><dt>最近活动</dt><dd>{{ formatTime(selectedTask?.last_activity_at ?? selected.last_heartbeat) }}</dd></div>
      </dl>
      <nav>
        <RouterLink class="button" :to="`/employees/${selected.id}`">员工详情</RouterLink>
        <RouterLink v-if="selectedTask" class="button button--primary" :to="`/tasks/${selectedTask.id}`">任务详情</RouterLink>
      </nav>
    </aside>

    <AstraEmptyState v-if="!employees.length" :icon="UsersRound" title="办公区暂无员工" description="请调整筛选条件或在配置中心创建数字员工。" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { UsersRound } from 'lucide-vue-next'
import type { Employee, Task } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeeWorkstation from '@/components/office/EmployeeWorkstation.vue'
import { employeeDisplayName, formatTime, platformCopy, statusLabel } from '@/utils/format'

const props = defineProps<{ employees: Employee[]; tasks: Task[] }>()
const selectedId = ref('')
const completedIds = ref(new Set<string>())
const priorStatus = new Map<string, string>()
const reducedMotion = computed(() => localStorage.getItem('astra-reduced-motion') === 'true')
const visibleEmployees = computed(() => props.employees.slice(0, 4))
const selected = computed(() => props.employees.find((employee) => employee.id === selectedId.value))
const selectedTask = computed(() => selected.value ? currentTask(selected.value) : undefined)
const taskStatuses = (status: string) => ({ WORKING: ['RUNNING'], WAIT_HUMAN: ['WAIT_HUMAN'], ERROR: ['EXECUTION_ERROR'], PAUSED: ['SUSPENDED'] }[status] ?? [])
const currentTask = (employee: Employee) => props.tasks.find((task) => task.employee_id === employee.id && taskStatuses(employee.status).includes(task.status))
const statusCopy = (status: string) => ({ WORKING: '正在推进任务', IDLE: '等待新任务', WAIT_HUMAN: '等待人工补充信息', PAUSED: '暂停接收新任务', OFFLINE: '当前离线', ERROR: '工作现场已保留' }[status] ?? '等待状态更新')
const idleTitle = (status: string) => status === 'IDLE' ? '等待新任务' : status === 'WAIT_HUMAN' ? '需要人工处理' : status === 'ERROR' ? '执行异常' : '暂无任务'
const activityLabel = (status: string) => ({ WORKING: '正在处理', IDLE: '当前状态', WAIT_HUMAN: '正在等待', ERROR: '异常任务', PAUSED: '当前状态', OFFLINE: '工位状态' }[status] ?? '当前工作')

watch(() => props.employees.map(({ id, status }) => ({ id, status })), (employees) => {
  for (const employee of employees) {
    if (priorStatus.get(employee.id) === 'WORKING' && employee.status === 'IDLE') {
      completedIds.value = new Set([...completedIds.value, employee.id])
      window.setTimeout(() => {
        const next = new Set(completedIds.value)
        next.delete(employee.id)
        completedIds.value = next
      }, 1800)
    }
    priorStatus.set(employee.id, employee.status)
  }
}, { immediate: true })
</script>

<style scoped>
.digital-office { position: relative; background: #e7eeeb; }
.office-scene { position: relative; height: 420px; overflow: hidden; padding: 14px 18px 12px; isolation: isolate; }
.office-scene__backdrop { position: absolute; inset: -2%; z-index: -3; background: url('/assets/nexus-office.png') center 47% / cover no-repeat; filter: brightness(.86) saturate(.87) contrast(1.04); transform: scale(1.02); }
.office-scene::before { position: absolute; inset: 0; z-index: -2; background: linear-gradient(180deg,rgba(226,237,233,.06),rgba(216,231,225,.03) 44%,rgba(12,42,34,.28)); content: ''; }
.office-scene__depth { position: absolute; inset: 0; z-index: -1; background: radial-gradient(ellipse at 50% 92%,rgba(31,196,127,.15),transparent 54%),linear-gradient(90deg,rgba(20,54,45,.1),transparent 23%,transparent 77%,rgba(20,54,45,.1)); pointer-events: none; }
.workstation-grid { position: relative; display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); height: 100%; }
.workstation { position: relative; display: grid; grid-template-rows: 34px minmax(0,1fr) 66px; min-width: 0; min-height: 0; height: 100%; padding: 0 8px 7px; color: inherit; text-align: left; border: 0; background: transparent; cursor: pointer; transition: transform .2s ease; }
.workstation::after { position: absolute; top: 20px; right: 0; bottom: 16px; width: 1px; background: linear-gradient(transparent,rgba(228,239,235,.7) 22%,rgba(21,57,48,.28) 76%,transparent); content: ''; }
.workstation:last-child::after { display: none; }
.workstation:hover,.workstation.active { transform: translateY(-4px); }
.workstation:focus-visible { border-radius: 14px; outline: 3px solid rgba(13,142,87,.35); outline-offset: -3px; }
.workstation__header { position: relative; z-index: 4; display: flex; align-items: center; justify-content: space-between; padding: 0 7px; }
.workstation__number { display: inline-flex; align-items: baseline; gap: 4px; color: rgba(12,42,34,.82); font: 800 14px var(--astra-font-display); letter-spacing: .06em; text-shadow: 0 1px 1px rgba(255,255,255,.64); }
.workstation__number small { font: 700 11px var(--astra-font-body); letter-spacing: .08em; }
.workstation__header :deep(.status-badge) { min-height: 23px; padding: 2px 7px; border: 1px solid rgba(255,255,255,.48); background: rgba(247,250,249,.78); backdrop-filter: blur(8px); }
.workstation :deep(.employee-workstation) { min-height: 0; }
.workstation__info { position: relative; z-index: 3; display: grid; grid-template-columns: minmax(88px,.8fr) minmax(0,1.2fr); gap: 12px; min-width: 0; margin: -10px 7px 0; padding: 9px 10px 8px; border-top: 1px solid rgba(229,240,236,.82); background: linear-gradient(90deg,rgba(245,249,247,.88),rgba(238,245,242,.69)); box-shadow: 0 -8px 24px rgba(18,50,42,.08); backdrop-filter: blur(9px); }
.workstation__identity,.workstation__activity { display: grid; align-content: center; min-width: 0; }
.workstation__identity strong,.workstation__identity small,.workstation__activity strong,.workstation__activity small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workstation__identity strong { color: #102b25; font: 750 var(--astra-font-body) var(--astra-font-display); }
.workstation__identity small { color: #45625b; font-size: 13px; }
.workstation__activity { padding-left: 12px; border-left: 1px solid rgba(51,78,71,.22); }
.workstation__activity small { color: #587069; font-size: 12px; }
.workstation__activity strong { color: #1c3b33; font-size: 13px; font-weight: 650; }
.workstation[data-status='WAIT_HUMAN'] .workstation__number { color: #a55d12; }
.workstation[data-status='ERROR'] .workstation__number { color: #bd4350; }
.workstation--completed { animation: completed-lift 1.8s ease-out; }
.office-inspector { display: grid; grid-template-columns: minmax(170px,.55fr) minmax(0,2fr) auto; gap: 22px; align-items: center; padding: 16px 20px; border-top: 1px solid #c7d4d0; background: #fff; }
.office-inspector__identity { display: grid; min-width: 0; }
.office-inspector__identity small,.office-inspector dt { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.office-inspector__identity strong { color: var(--astra-text-primary); font-size: var(--astra-font-section); }
.office-inspector__identity span { color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.office-inspector dl { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 18px; margin: 0; }
.office-inspector dd { overflow: hidden; margin: 3px 0 0; color: var(--astra-text-primary); text-overflow: ellipsis; white-space: nowrap; }
.office-inspector nav { display: flex; gap: 8px; }
@keyframes completed-lift { 35% { filter: drop-shadow(0 0 24px rgba(24,184,117,.42)); } }
.digital-office--reduced :deep(*) { animation: none !important; transition: none !important; }
@media(max-width:1180px){.office-scene{height:660px;padding-top:16px}.workstation-grid{grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:repeat(2,minmax(0,1fr))}.workstation{grid-template-rows:30px minmax(0,1fr) 60px}.workstation:nth-child(2n)::after{display:none}.office-inspector{grid-template-columns:1fr}.office-inspector dl{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:700px){.office-scene{height:auto;min-height:980px}.workstation-grid{grid-template-columns:1fr;grid-template-rows:repeat(4,230px)}.office-inspector dl{grid-template-columns:1fr}.office-inspector nav{flex-wrap:wrap}}
</style>
