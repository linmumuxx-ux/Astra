<template>
  <div class="digital-office" :class="{ 'digital-office--reduced': reducedMotion }">
    <div class="office-scene">
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
          <span class="workstation__number">工位 {{ String(index + 1).padStart(2, '0') }}</span>
          <EmployeeWorkstation :employee-id="employee.id" :status="employee.status" :variant="index + 1" />
          <span class="workstation__identity">
            <span><strong>{{ employeeDisplayName(employee.name) }}</strong><small>{{ employee.role }}</small></span>
            <AstraStatusBadge :status="employee.status" :pulse="employee.status === 'WORKING'" />
          </span>
          <span class="workstation__taskline">{{ currentTask(employee.id)?.title ?? idleTitle(employee.status) }}</span>
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
const selectedTask = computed(() => selected.value ? currentTask(selected.value.id) : undefined)
const currentTask = (employeeId: string) => props.tasks.find((task) => task.employee_id === employeeId && ['READY', 'RUNNING', 'WAIT_HUMAN', 'EXECUTION_ERROR'].includes(task.status))
const statusCopy = (status: string) => ({ WORKING: '正在推进任务', IDLE: '等待新任务', WAIT_HUMAN: '等待人工补充信息', PAUSED: '暂停接收新任务', OFFLINE: '当前离线', ERROR: '工作现场已保留' }[status] ?? '等待状态更新')
const idleTitle = (status: string) => status === 'IDLE' ? '等待新任务' : status === 'WAIT_HUMAN' ? '需要人工处理' : status === 'ERROR' ? '执行异常' : '暂无任务'

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
.digital-office { position: relative; background: #eef3f1; }
.office-scene { position: relative; height: 520px; overflow: hidden; padding: 30px 24px 18px; background: url('/assets/nexus-office.png') center 44% / cover no-repeat; isolation: isolate; }
.office-scene::before { position: absolute; inset: 0; z-index: -1; background: linear-gradient(180deg,rgba(247,250,249,.16),rgba(234,242,239,.1) 46%,rgba(25,58,49,.22)); content: ''; }
.office-scene__depth { position: absolute; inset: 0; background: radial-gradient(ellipse at 50% 88%,rgba(255,255,255,.42),transparent 55%),linear-gradient(90deg,rgba(233,241,238,.2),transparent 26%,transparent 74%,rgba(233,241,238,.18)); pointer-events: none; }
.workstation-grid { position: relative; display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 2px; align-items: end; height: 100%; }
.workstation { position: relative; display: grid; grid-template-rows: minmax(0,1fr) auto auto; min-width: 0; min-height: 0; height: 100%; padding: 0 2px 10px; color: inherit; text-align: left; border: 0; background: transparent; cursor: pointer; transition: transform .2s ease; }
.workstation:hover,.workstation.active { transform: translateY(-7px); }
.workstation:focus-visible { border-radius: 14px; outline: 3px solid rgba(13,142,87,.35); outline-offset: -3px; }
.workstation__number { position: absolute; z-index: 4; top: 8px; left: 14px; color: rgba(18,48,41,.66); font: 700 12px var(--astra-font-display); letter-spacing: .08em; }
.workstation :deep(.employee-workstation) { min-height: 0; }
.workstation__identity { position: relative; z-index: 3; display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; margin: -8px 10px 0; padding: 7px 3px 5px; border-bottom: 1px solid rgba(51,78,71,.22); }
.workstation__identity > span { display: grid; min-width: 0; }
.workstation__identity strong,.workstation__identity small,.workstation__taskline { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workstation__identity strong { color: #102b25; font: 700 var(--astra-font-body) var(--astra-font-display); }
.workstation__identity small { color: #45625b; font-size: 13px; }
.workstation__identity :deep(.status-badge) { min-height: 24px; padding: 2px 7px; background: rgba(255,255,255,.76); backdrop-filter: blur(8px); }
.workstation__taskline { z-index: 3; padding: 5px 13px 0; color: #2f4b44; font-size: 13px; }
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
@media(max-width:1180px){.office-scene{height:660px;padding-top:20px}.workstation-grid{grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:repeat(2,minmax(0,1fr))}.workstation__number{top:2px}.office-inspector{grid-template-columns:1fr}.office-inspector dl{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:700px){.office-scene{height:auto;min-height:980px}.workstation-grid{grid-template-columns:1fr;grid-template-rows:repeat(4,230px)}.office-inspector dl{grid-template-columns:1fr}.office-inspector nav{flex-wrap:wrap}}
</style>
