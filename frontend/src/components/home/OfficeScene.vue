<template>
  <section class="office-scene" data-testid="digital-office-scene" aria-label="数字办公室工位">
    <header class="office-scene__toolbar">
      <div class="office-scene__identity"><Monitor :size="18" /><h2>办公区</h2><span>{{ employees.length }} 位员工</span></div>
      <ElRadioGroup class="office-scene__state" v-model="stateFilter" aria-label="状态筛选">
        <ElRadioButton value="all">全部员工</ElRadioButton>
        <ElRadioButton value="working">工作中 <span>{{ workingCount }}</span></ElRadioButton>
        <ElRadioButton value="attention">待处理 <span>{{ attentionCount }}</span></ElRadioButton>
      </ElRadioGroup>
      <ElSelect v-model="teamFilter" aria-label="团队筛选" class="office-scene__team">
        <ElOption label="全部团队" value="all" />
        <ElOption v-for="team in teams" :key="team.id" :label="`${team.name} · ${team.count}`" :value="team.id" />
      </ElSelect>
    </header>


    <div class="office-scene__room">
      <div class="office-scene__backdrop" aria-hidden="true"><OfficeRoom /></div>
      <div class="office-scene__viewport" data-testid="office-room-viewport" tabindex="0" role="region" aria-label="办公室工位，可滚动查看全部员工">
        <div v-if="!employees.length" class="office-scene__empty">
          <UsersRound :size="32" /><h3>办公室还没有数字员工</h3><p>创建员工后，他们会拥有自己的工位。</p>
          <ElButton :tag="RouterLink" to="/employees?create=1" type="primary">创建数字员工</ElButton>
        </div>
        <div v-else-if="!visibleEmployees.length" class="office-scene__empty">
          <Search :size="28" /><h3>{{ query ? `没有找到“${query}”` : '这个范围暂时没有员工' }}</h3>
          <p>可搜索姓名、职责或任务，或切换团队与状态。</p>
          <ElButton v-if="teamFilter !== 'all' || stateFilter !== 'all'" @click="resetFilters">显示全部员工</ElButton>
        </div>
        <div v-else class="office-scene__desks">
          <OfficeWorkstation v-for="employee in visibleEmployees" :key="employee.id" :employee="employee" :live="live" :completed="completedIds.has(employee.id)" />
        </div>
      </div>
    </div>
    <footer class="office-scene__legend" aria-label="工位状态图例">
      <span><i data-state="working" />工作中</span><span><i data-state="idle" />空闲</span><span><i data-state="attention" />需要人工</span><span><i data-state="error" />异常</span>
      <small>{{ visibleEmployees.length }} / {{ employees.length }} 位员工</small>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { Monitor, Search, UsersRound } from 'lucide-vue-next'
import { ElButton, ElOption, ElRadioButton, ElRadioGroup, ElSelect } from 'element-plus'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import OfficeRoom from './OfficeRoom.vue'
import OfficeWorkstation from './OfficeWorkstation.vue'
import type { OfficeEmployee, OfficeEvent } from '@/features/home/officePresentation'

const props = withDefaults(defineProps<{ employees: OfficeEmployee[]; officeEvents: OfficeEvent[] | null; live?: boolean; query?: string }>(), { live: false, query: '' })
const teamFilter = ref('all')
const stateFilter = ref('all')
const completedIds = ref(new Set<string>())
const completionTimers = new Map<string, number>()
const teams = computed(() => {
  const groups = new Map<string, { id: string; name: string; count: number }>()
  for (const employee of props.employees) {
    const group = groups.get(employee.teamId) ?? { id: employee.teamId, name: employee.teamName, count: 0 }
    group.count += 1
    groups.set(group.id, group)
  }
  return [...groups.values()]
})
const workingCount = computed(() => props.employees.filter(employee => ['working', 'thinking'].includes(employee.status)).length)
const attentionCount = computed(() => props.employees.filter(employee => ['attention', 'error'].includes(employee.status)).length)
const visibleEmployees = computed(() => {
  const query = props.query.trim().toLocaleLowerCase('zh-CN')
  return props.employees.filter(employee => (teamFilter.value === 'all' || employee.teamId === teamFilter.value)
    && (stateFilter.value === 'all' || (stateFilter.value === 'working' ? ['working', 'thinking'] : ['attention', 'error']).includes(employee.status))
    && (!query || `${employee.name} ${employee.role} ${employee.taskTitle ?? ''}`.toLocaleLowerCase('zh-CN').includes(query)))
})
function resetFilters() { teamFilter.value = 'all'; stateFilter.value = 'all' }

watch(teams, (value) => { if (!value.some(team => team.id === teamFilter.value)) teamFilter.value = 'all' })
// 首次历史快照不播放“刚完成”。动态与工位接口可先后返回，
// 尚未对应到空闲工位的新完成事件，等员工快照更新后再反馈。
let seenEventIds: Set<number> | null = null
watch(() => [props.officeEvents, props.employees, props.live] as const, ([events]) => {
  if (!events) return
  const currentEventIds = new Set(events.map(event => event.id))
  if (!seenEventIds) { seenEventIds = currentEventIds; return }
  seenEventIds = new Set([...seenEventIds].filter(id => currentEventIds.has(id)))
  // 重连快照尚未就绪时不播放，也不消费随后到达的新事件。
  if (!props.live) return
  for (const event of events) {
    if (seenEventIds.has(event.id)) continue
    if (event.kind !== 'task_completed' || !event.employeeId) { seenEventIds.add(event.id); continue }
    const employee = props.employees.find(employee => employee.id === event.employeeId)
    if (!employee || (employee.taskId && employee.target !== event.target)) { seenEventIds.add(event.id); continue }
    if (employee.status !== 'idle') continue
    seenEventIds.add(event.id)
    completedIds.value.add(employee.id)
    window.clearTimeout(completionTimers.get(employee.id))
    completionTimers.set(employee.id, window.setTimeout(() => { completedIds.value.delete(employee.id); completionTimers.delete(employee.id) }, 3500))
  }
}, { immediate: true })
onBeforeUnmount(() => { completionTimers.forEach(timer => window.clearTimeout(timer)) })
</script>

<style scoped>
.office-scene{min-width:0;overflow:hidden;border:1px solid var(--astra-border);border-radius:16px;background:var(--astra-bg-panel)}
.office-scene__toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 20px}.office-scene__toolbar :deep(.el-radio-button__inner){display:inline-flex;align-items:center;gap:5px}.office-scene__identity{display:flex;align-items:center;gap:9px;min-width:0}.office-scene__identity>svg{color:var(--astra-primary)}.office-scene__identity h2{margin:0;font-size:var(--astra-font-section)}.office-scene__identity>span{color:var(--astra-text-muted);font-size:var(--astra-font-helper);white-space:nowrap}.office-scene__team{width:190px;flex:none}

.office-scene__room{position:relative;height:clamp(460px,calc(100vh - 365px),760px);overflow:hidden;border-top:1px solid var(--astra-border);background:var(--astra-bg-base);isolation:isolate}
.office-scene__backdrop{position:absolute;inset:0;z-index:0;overflow:hidden;pointer-events:none}
.office-scene__viewport{position:absolute;inset:32% 0 0;z-index:1;overflow-x:hidden;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable}
.office-scene__viewport:focus-visible{outline:2px solid var(--astra-primary);outline-offset:-3px}
.office-scene__desks{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-items:start;gap:24px 8px;padding:12px 14% 42px}
.office-scene__legend{display:flex;align-items:center;gap:16px;min-height:48px;padding:10px 22px;flex-wrap:wrap;color:var(--astra-text-muted);font-size:var(--astra-font-helper)}.office-scene__legend>span{display:flex;align-items:center;gap:5px}.office-scene__legend i{width:7px;height:7px;border-radius:50%;background:var(--astra-text-muted)}.office-scene__legend i[data-state='working']{background:var(--astra-primary)}.office-scene__legend i[data-state='attention']{background:var(--astra-warning)}.office-scene__legend i[data-state='error']{background:var(--astra-danger)}.office-scene__legend small{margin-left:auto;font-size:inherit;font-variant-numeric:tabular-nums}
.office-scene__empty{display:grid;justify-items:center;align-content:center;min-height:100%;padding:32px 24px 64px;text-align:center;color:var(--astra-text-muted)}.office-scene__empty h3{margin:14px 0 0;color:var(--astra-text-secondary);font-size:var(--astra-font-subtitle)}.office-scene__empty p{margin:8px 0 18px;font-size:var(--astra-font-body);overflow-wrap:anywhere}
</style>
