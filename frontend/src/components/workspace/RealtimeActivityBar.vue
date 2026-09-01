<template>
  <section class="activity-bar" aria-label="实时动态">
    <header><div><Activity :size="15" /><strong>实时动态</strong><span>{{ activities.length ? `最近 ${activities.length} 条` : '暂无更新' }}</span></div><nav><button type="button" aria-label="上一组动态" :disabled="page === 0" @click="move(-1)"><ChevronLeft :size="16" /></button><button type="button" aria-label="下一组动态" :disabled="page >= lastPage" @click="move(1)"><ChevronRight :size="16" /></button></nav></header>
    <div v-if="activities.length" class="activity-bar__viewport">
      <div class="activity-bar__track" :style="{ transform: `translateX(-${page * 100}%)` }">
        <button v-for="item in activities" :key="item.id" type="button" :data-tone="item.tone" @click="openActivity(item)">
          <EmployeeAvatar v-if="item.employee" :employee="item.employee" size="small" />
          <span v-else class="activity-bar__system"><Bell :size="15" /></span>
          <span><strong>{{ item.employeeName }}</strong><em>{{ item.action }}</em><small>{{ relativeTime(item.createdAt) }}</small></span>
          <CircleAlert v-if="item.tone === 'warning'" :size="15" />
        </button>
      </div>
    </div>
    <div v-else class="activity-bar__empty">暂无实时动态</div>
  </section>
</template>

<script setup lang="ts">
import { Activity, Bell, ChevronLeft, ChevronRight, CircleAlert } from 'lucide-vue-next'
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { AstraEvent, Employee } from '@/api/types'
import EmployeeAvatar from '@/components/employee/EmployeeAvatar.vue'
import { employeeDisplayName, platformCopy } from '@/utils/format'

const props = defineProps<{ events: AstraEvent[]; employees: Employee[] }>()
const emit = defineEmits<{ select: [id: string] }>()
const router = useRouter()
const page = ref(0)
const viewportWidth = ref(window.innerWidth)
const itemsPerPage = computed(() => viewportWidth.value < 1450 ? 3 : viewportWidth.value < 1800 ? 4 : 5)
const activityTypes = new Set(['TASK_ASSIGNED', 'TASK_RUNNING', 'TASK_SUSPENDED', 'EMPLOYEE_STATUS_CHANGED'])
const activities = computed(() => props.events
  .filter((event) => activityTypes.has(event.event_type))
  .map((event) => {
    const employee = props.employees.find((item) => item.id === event.employee_id)
    const action = ({ TASK_ASSIGNED: '领取了新任务', TASK_RUNNING: '开始处理任务', TASK_SUSPENDED: '已暂停当前任务', EMPLOYEE_STATUS_CHANGED: platformCopy(event.message) || '状态已更新' }[event.event_type] ?? platformCopy(event.message))
    return { id: event.id, employee, employeeId: event.employee_id, employeeName: employeeDisplayName(employee?.name ?? (event.employee_id || '系统')), taskId: event.task_id, action, createdAt: event.created_at, tone: event.event_type === 'TASK_SUSPENDED' ? 'warning' : 'normal' }
  }))
const lastPage = computed(() => Math.max(0, Math.ceil(activities.value.length / itemsPerPage.value) - 1))
function move(direction: number) { page.value = Math.min(lastPage.value, Math.max(0, page.value + direction)) }
function openActivity(item: (typeof activities.value)[number]) { if (item.employeeId) emit('select', item.employeeId); else if (item.taskId) router.push(`/tasks/${item.taskId}`) }
function relativeTime(value: string) {
  const raw = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(raw).getTime()) / 60_000))
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`
  return `${Math.floor(minutes / 1440)} 天前`
}
function handleResize() { viewportWidth.value = window.innerWidth; page.value = Math.min(page.value, lastPage.value) }
onMounted(() => window.addEventListener('resize', handleResize))
onBeforeUnmount(() => window.removeEventListener('resize', handleResize))
</script>

<style scoped>
.activity-bar { position: absolute; z-index: 25; right: 14px; bottom: 12px; left: 14px; height: 104px; overflow: hidden; border: 1px solid rgba(205,221,214,.95); border-radius: 14px; background: rgba(255,255,255,.95); box-shadow: 0 12px 28px rgba(35,70,59,.13); backdrop-filter: blur(10px); }
.activity-bar > header { display: flex; align-items: center; justify-content: space-between; min-height: 33px; padding: 5px 8px 4px 14px; border-bottom: 1px solid var(--astra-border); }.activity-bar > header > div { display: flex; align-items: center; gap: 7px; color: var(--astra-primary); }.activity-bar > header strong { color: var(--astra-text-primary); font-size: 12px; }.activity-bar > header span { color: var(--astra-text-muted); font-size: 10px; }.activity-bar nav { display: flex; gap: 4px; }.activity-bar nav button { display: grid; place-items: center; width: 27px; height: 27px; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 7px; background: white; cursor: pointer; }.activity-bar nav button:disabled { opacity: .35; cursor: default; }
.activity-bar__viewport { height: 70px; overflow: hidden; }.activity-bar__track { display: grid; grid-auto-columns: calc((100% - 36px) / 4); grid-auto-flow: column; gap: 12px; height: 100%; padding: 6px 12px 7px; transition: transform .25s ease; }.activity-bar__track > button { display: grid; grid-template-columns: auto minmax(0,1fr) auto; align-items: center; gap: 8px; min-width: 0; padding: 4px 8px; color: inherit; text-align: left; border: 0; border-right: 1px solid var(--astra-border); background: transparent; cursor: pointer; }.activity-bar__track > button:last-child { border-right: 0; }.activity-bar__track > button > span:nth-child(2) { display: grid; min-width: 0; }.activity-bar__track strong,.activity-bar__track em,.activity-bar__track small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.activity-bar__track strong { color: var(--astra-text-primary); font-size: 11px; }.activity-bar__track em { color: var(--astra-text-secondary); font-size: 10px; font-style: normal; }.activity-bar__track small { color: var(--astra-text-muted); font-size: 9px; }.activity-bar__track > button > svg { color: var(--astra-warning); }
.activity-bar__system { display: grid; place-items: center; width: 34px; height: 34px; color: var(--astra-primary); border-radius: 11px; background: var(--astra-primary-soft); }.activity-bar__empty { display: grid; place-items: center; height: 68px; color: var(--astra-text-muted); font-size: 12px; }
@media(min-width:1800px){.activity-bar__track{grid-auto-columns:calc((100% - 48px)/5)}}
@media(max-width:1450px){.activity-bar__track{grid-auto-columns:calc((100% - 24px)/3)}}
@media(max-width:900px){.activity-bar{height:94px}.activity-bar__viewport{height:60px}.activity-bar__track{grid-auto-columns:calc((100% - 12px)/2)}}
@media(max-width:600px){.activity-bar__track{grid-auto-columns:100%}}
</style>
