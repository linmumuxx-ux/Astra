<template>
  <div class="digital-office" :class="{ 'digital-office--reduced': reducedMotion }">
    <div class="office-zones">
      <section
        v-for="group in roleGroups"
        :key="group.role"
        class="office-zone"
        :style="zoneStyle(group.role)"
        :data-testid="`role-zone-${group.slug}`"
      >
        <header class="office-zone__header">
          <span class="office-zone__icon"><BriefcaseBusiness :size="17" /></span>
          <div>
            <small>岗位分区</small>
            <h3>{{ roleZoneLabel(group.role) }}</h3>
          </div>
          <p><strong>{{ group.employees.length }}</strong> 位成员<span>{{ zoneActivity(group.employees) }}</span></p>
        </header>

        <div class="office-zone__members">
          <button
            v-for="employee in group.employees"
            :key="employee.id"
            class="workstation"
            :class="{ 'workstation--completed': completedIds.has(employee.id), active: selected?.id === employee.id }"
            :data-status="employee.status"
            :aria-label="`${employee.name} ${employee.role} ${statusCopy(employee.status)}`"
            @click="selectedId = selectedId === employee.id ? '' : employee.id"
          >
            <span class="workstation__profile">
              <EmployeePortrait :employee-id="employee.id" :status="employee.status" />
              <span class="workstation__identity">
                <small>{{ employee.id }}</small>
                <strong>{{ employee.name }}</strong>
                <em>{{ employee.role }}</em>
              </span>
              <AstraStatusBadge :status="employee.status" :pulse="employee.status === 'WORKING'" />
            </span>

            <span class="workstation__voice">
              <small><Sparkles :size="12" /> {{ presenceCopy(employee.status) }}</small>
              <strong>{{ currentTask(employee.id)?.title ?? '随时可以接手新任务' }}</strong>
              <span>{{ platformCopy(currentTask(employee.id)?.current_progress) || employee.description || statusCopy(employee.status) }}</span>
            </span>

            <span class="workstation__facts">
              <span><BadgeCheck :size="13" /><small>今日完成</small><strong>{{ employee.today_completed }}</strong></span>
              <span><Gauge :size="13" /><small>今日 Token</small><strong>{{ formatTokens(employee.today_usage.total_tokens) }}</strong></span>
              <span><Wrench :size="13" /><small>工具调用</small><strong>{{ employee.today_usage.tool_call_count ?? '—' }}</strong></span>
            </span>
          </button>
        </div>
      </section>
    </div>

    <aside v-if="selected" class="office-inspector">
      <div class="office-inspector__person">
        <EmployeePortrait :employee-id="selected.id" :status="selected.status" />
        <div><small>{{ selected.id }}</small><strong>{{ selected.name }}</strong><span>{{ selected.role }}</span></div>
      </div>
      <dl>
        <div><dt>当前任务</dt><dd>{{ selectedTask?.title ?? '暂无' }}</dd></div>
        <div><dt>最新进展</dt><dd>{{ platformCopy(selectedTask?.current_progress) || statusCopy(selected.status) }}</dd></div>
        <div><dt>最近活动</dt><dd>{{ formatTime(selectedTask?.last_activity_at ?? selected.last_heartbeat) }}</dd></div>
        <div><dt>工作时长</dt><dd>{{ formatDuration(selectedTask?.started_at ?? null) }}</dd></div>
        <div><dt>Token</dt><dd>{{ formatTokens(selected.today_usage.total_tokens) }}</dd></div>
        <div><dt>工具调用</dt><dd>{{ selected.today_usage.tool_call_count ?? '—' }}</dd></div>
      </dl>
      <nav><RouterLink class="button" :to="`/employees/${selected.id}`">员工详情</RouterLink><RouterLink v-if="selectedTask" class="button button--primary" :to="`/tasks/${selectedTask.id}`">任务详情</RouterLink></nav>
    </aside>

    <AstraEmptyState v-if="!employees.length" :icon="UsersRound" title="办公室暂无员工" description="在配置中心创建并启用数字员工。" />
  </div>
</template>

<script setup lang="ts">
import { BadgeCheck, BriefcaseBusiness, Gauge, Sparkles, UsersRound, Wrench } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import type { Employee, Task } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeePortrait from '@/components/office/EmployeePortrait.vue'
import { formatDuration, formatTime, formatTokens, platformCopy } from '@/utils/format'

const props = defineProps<{ employees: Employee[]; tasks: Task[] }>()
const selectedId = ref('')
const completedIds = ref(new Set<string>())
const priorStatus = new Map<string, string>()
const reducedMotion = computed(() => localStorage.getItem('astra-reduced-motion') === 'true')
const selected = computed(() => props.employees.find((employee) => employee.id === selectedId.value))
const selectedTask = computed(() => selected.value ? currentTask(selected.value.id) : undefined)

const roleGroups = computed(() => {
  const groups = new Map<string, Employee[]>()
  for (const employee of props.employees) {
    const role = employee.role.trim() || '未设置岗位'
    groups.set(role, [...(groups.get(role) ?? []), employee])
  }
  return [...groups.entries()].map(([role, employees]) => ({
    role,
    employees,
    slug: role.replace(/[^\p{L}\p{N}]+/gu, '-'),
  }))
})

const currentTask = (employeeId: string) => props.tasks.find((task) => task.employee_id === employeeId && ['READY', 'RUNNING', 'WAIT_HUMAN', 'EXECUTION_ERROR'].includes(task.status))
const statusCopy = (status: string) => ({ WORKING: '正在处理任务', IDLE: '等待新任务', WAIT_HUMAN: '等待人工回复', PAUSED: '员工已暂停', OFFLINE: '当前离线', ERROR: '等待恢复工作环境' }[status] ?? '等待任务状态更新')
const presenceCopy = (status: string) => ({ WORKING: '正在专注工作', IDLE: '今天状态不错', WAIT_HUMAN: '有一个问题想问你', PAUSED: '暂时休息', OFFLINE: '暂时不在线', ERROR: '工作遇到阻塞' }[status] ?? '正在同步近况')
const roleZoneLabel = (role: string) => `${role.replace(/(?:数字)?员工$|专员$|工程师$/u, '').trim() || role}区`
const zoneActivity = (employees: Employee[]) => {
  const working = employees.filter((employee) => employee.status === 'WORKING').length
  const waiting = employees.filter((employee) => employee.status === 'WAIT_HUMAN').length
  if (waiting) return `${waiting} 位等待回复`
  if (working) return `${working} 位工作中`
  return '当前可响应'
}
const zoneStyle = (role: string) => {
  const palettes = [
    { accent: '#5b8cff', rgb: '91, 140, 255' },
    { accent: '#36c7ae', rgb: '54, 199, 174' },
    { accent: '#9d7cff', rgb: '157, 124, 255' },
    { accent: '#ef9b58', rgb: '239, 155, 88' },
  ]
  const hash = [...role].reduce((total, character) => total + character.charCodeAt(0), 0)
  const palette = palettes[hash % palettes.length]
  return { '--zone-accent': palette.accent, '--zone-rgb': palette.rgb }
}

watch(
  () => props.employees.map((employee) => ({ id: employee.id, status: employee.status })),
  (employees) => {
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
  },
  { immediate: true },
)
</script>

<style scoped>
.digital-office { padding: 20px; background: radial-gradient(circle at 50% 0%, rgba(33, 102, 190, .16), transparent 52%), linear-gradient(180deg, rgba(8, 18, 35, .72), rgba(5, 12, 24, .94)); }
.office-zones { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; align-items: start; }
.office-zone { overflow: hidden; min-width: 0; padding: 16px; border: 1px solid rgba(var(--zone-rgb), .24); border-radius: 14px; background: linear-gradient(155deg, rgba(var(--zone-rgb), .085), rgba(7, 17, 31, .8) 38%); box-shadow: inset 0 1px rgba(255, 255, 255, .025); }
.office-zone__header { display: grid; grid-template-columns: 36px minmax(0, 1fr) auto; align-items: center; gap: 10px; margin-bottom: 11px; padding: 2px 2px 11px; border-bottom: 1px solid rgba(var(--zone-rgb), .2); }
.office-zone__icon { display: grid; width: 34px; height: 34px; place-items: center; color: var(--zone-accent); border: 1px solid rgba(var(--zone-rgb), .25); border-radius: 10px; background: rgba(var(--zone-rgb), .1); }
.office-zone__header > div { min-width: 0; }
.office-zone__header small { display: block; color: var(--zone-accent); font: 700 var(--astra-font-helper) var(--astra-font-display); letter-spacing: .12em; }
.office-zone__header h3 { overflow: hidden; margin: 2px 0 0; color: var(--astra-text-primary); font: 650 var(--astra-font-section) var(--astra-font-display); text-overflow: ellipsis; white-space: nowrap; }
.office-zone__header p { display: grid; margin: 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); text-align: right; }
.office-zone__header p strong { color: var(--astra-text-primary); font: 650 16px var(--astra-font-display); }
.office-zone__header p span { margin-top: 1px; }
.office-zone__members { display: grid; gap: 10px; }

.workstation { position: relative; display: grid; gap: 14px; width: 100%; min-height: 286px; overflow: hidden; padding: 18px; color: inherit; text-align: left; border: 1px solid var(--astra-border); border-radius: 12px; background: linear-gradient(150deg, rgba(16, 35, 61, .96), rgba(8, 19, 34, .96)); box-shadow: 0 16px 32px rgba(0, 0, 0, .16); cursor: pointer; transition: border-color .2s, transform .2s, box-shadow .2s; }
.workstation::before { position: absolute; inset: 0 auto auto 0; width: 100%; height: 2px; background: linear-gradient(90deg, var(--zone-accent), transparent 68%); content: ''; opacity: .62; }
.workstation:hover { border-color: rgba(var(--zone-rgb), .56); box-shadow: 0 18px 40px rgba(0, 0, 0, .24), 0 0 24px rgba(var(--zone-rgb), .08); transform: translateY(-2px); }
.workstation__profile { display: grid; grid-template-columns: 72px minmax(0, 1fr) auto; align-items: center; gap: 11px; }
.workstation__identity { display: grid; min-width: 0; }
.workstation__identity small { color: var(--zone-accent); font: 700 var(--astra-font-helper) var(--astra-font-display); letter-spacing: .08em; text-transform: uppercase; }
.workstation__identity strong { overflow: hidden; margin-top: 2px; color: var(--astra-text-primary); font: 660 var(--astra-font-section) var(--astra-font-display); text-overflow: ellipsis; white-space: nowrap; }
.workstation__identity em { overflow: hidden; margin-top: 2px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.workstation__profile > :last-child { align-self: start; }
.workstation__voice { position: relative; display: grid; min-height: 76px; padding: 11px 12px; border: 1px solid rgba(var(--zone-rgb), .18); border-radius: 9px 9px 9px 3px; background: rgba(var(--zone-rgb), .055); }
.workstation__voice::before { position: absolute; top: -6px; left: 24px; width: 10px; height: 10px; border-top: 1px solid rgba(var(--zone-rgb), .18); border-left: 1px solid rgba(var(--zone-rgb), .18); background: #0e2038; content: ''; transform: rotate(45deg); }
.workstation__voice small { display: flex; align-items: center; gap: 5px; color: var(--zone-accent); font-size: var(--astra-font-helper); }
.workstation__voice strong { overflow: hidden; margin-top: 5px; color: var(--astra-text-secondary); font-size: var(--astra-font-body); text-overflow: ellipsis; white-space: nowrap; }
.workstation__voice > span { display: -webkit-box; overflow: hidden; margin-top: 4px; color: #9fb2c8; font-size: var(--astra-font-control); line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.workstation__facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin-top: auto; }
.workstation__facts > span { display: grid; grid-template-columns: 14px minmax(0, 1fr); gap: 1px 5px; min-width: 0; padding: 7px; color: var(--zone-accent); border: 1px solid rgba(27, 48, 73, .7); border-radius: 7px; background: rgba(5, 13, 23, .35); }
.workstation__facts svg { grid-row: 1 / 3; align-self: center; }
.workstation__facts small { overflow: hidden; color: var(--astra-text-muted); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.workstation__facts strong { color: var(--astra-text-secondary); font: 650 var(--astra-font-body) var(--astra-font-display); }
.workstation[data-status='WORKING'] { border-color: rgba(55, 134, 255, .48); }
.workstation[data-status='WAIT_HUMAN'] { border-color: rgba(244, 185, 77, .45); }
.workstation[data-status='ERROR'] { border-color: rgba(228, 92, 104, .52); }
.workstation.active { outline: 1px solid rgba(var(--zone-rgb), .72); box-shadow: 0 0 0 3px rgba(var(--zone-rgb), .08); }
.workstation--completed { animation: completed-glow 1.8s ease-out; }

.office-inspector { display: grid; grid-template-columns: minmax(230px, .8fr) 2fr auto; gap: 18px; align-items: center; margin-top: 14px; padding: 15px; border: 1px solid rgba(67, 139, 237, .42); border-radius: 12px; background: rgba(12, 29, 53, .94); }
.office-inspector__person { display: flex; align-items: center; gap: 11px; }
.office-inspector__person > div { display: grid; gap: 2px; min-width: 0; }
.office-inspector small, .office-inspector span, .office-inspector dt { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.office-inspector__person strong { font-size: var(--astra-font-section); }
.office-inspector dl { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 14px; margin: 0; }
.office-inspector dl div { min-width: 0; }
.office-inspector dd { overflow: hidden; margin: 3px 0 0; font-size: var(--astra-font-control); text-overflow: ellipsis; white-space: nowrap; }
.office-inspector nav { display: flex; gap: 7px; }
.digital-office--reduced :deep(*) { animation: none !important; transition: none !important; }

@keyframes completed-glow { 0% { box-shadow: 0 0 0 rgba(50,214,155,0); } 28% { box-shadow: 0 0 34px rgba(50,214,155,.48); } 100% { box-shadow: 0 0 0 rgba(50,214,155,0); } }
@media (max-width: 1100px) { .office-zones { grid-template-columns: repeat(2, minmax(270px, 1fr)); }.office-inspector { grid-template-columns: 1fr; }.office-inspector dl { grid-template-columns: repeat(3, 1fr); }.office-inspector nav { justify-content: flex-end; } }
@media (max-width: 700px) { .office-zones { grid-template-columns: 1fr; }.office-inspector dl { grid-template-columns: repeat(2, 1fr); }.workstation__profile { grid-template-columns: 64px minmax(0, 1fr) auto; }.workstation__profile :deep(.employee-portrait) { width: 64px; height: 64px; } }
@media (max-width: 440px) { .workstation__facts { grid-template-columns: 1fr; }.workstation__facts > span { grid-template-columns: 18px 1fr auto; }.workstation__facts svg { grid-row: auto; }.workstation__facts strong { text-align: right; }.office-inspector dl { grid-template-columns: 1fr; }.office-inspector nav { flex-direction: column; } }
</style>
