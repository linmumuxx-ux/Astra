<template>
  <section class="activity-bar" aria-label="实时动态">
    <header><Activity :size="15" /><strong>实时动态</strong></header>
    <div v-if="activities.length" class="activity-bar__items">
      <button v-for="item in activities.slice(0, 5)" :key="item.id" type="button" :data-tone="item.tone" @click="openActivity(item)">
        <i /><time>{{ formatClock(item.createdAt) }}</time><strong>{{ item.employeeName }}</strong><span>{{ item.action }}</span>
      </button>
    </div>
    <div v-else class="activity-bar__empty">暂无实时动态</div>
    <RouterLink class="activity-bar__more" to="/runs">查看更多<ChevronRight :size="14" /></RouterLink>
  </section>
</template>

<script setup lang="ts">
import { Activity, ChevronRight } from 'lucide-vue-next'
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import type { AstraEvent, Employee } from '@/api/types'
import { employeeDisplayName, platformCopy } from '@/utils/format'

const props = defineProps<{ events: AstraEvent[]; employees: Employee[] }>()
const emit = defineEmits<{ select: [id: string] }>()
const router = useRouter()
const activityTypes = new Set([
  'TASK_ASSIGNED', 'TASK_RUNNING', 'TASK_SUSPENDED', 'WAIT_HUMAN',
  'TASK_COMPLETED', 'RESULT_SUBMITTED', 'TASK_FAILED', 'EXECUTION_ERROR', 'EMPLOYEE_STATUS_CHANGED',
])
const activities = computed(() => props.events
  .filter((event) => activityTypes.has(event.event_type))
  .map((event) => {
    const employee = props.employees.find((item) => item.id === event.employee_id)
    const action = ({
      TASK_ASSIGNED: '领取了新任务', TASK_RUNNING: '开始处理任务', TASK_SUSPENDED: '暂停了当前任务',
      WAIT_HUMAN: '等待人工确认', TASK_COMPLETED: '完成了任务', RESULT_SUBMITTED: '生成了任务结果',
      TASK_FAILED: '任务执行失败', EXECUTION_ERROR: '执行发生异常',
      EMPLOYEE_STATUS_CHANGED: platformCopy(event.message) || '状态已更新',
    }[event.event_type] ?? platformCopy(event.message))
    const tone = ['WAIT_HUMAN', 'TASK_SUSPENDED'].includes(event.event_type)
      ? 'warning'
      : ['TASK_FAILED', 'EXECUTION_ERROR'].includes(event.event_type) ? 'danger' : 'normal'
    return { id: event.id, employeeId: event.employee_id, employeeName: employeeDisplayName(employee?.name ?? (event.employee_id || '系统')), taskId: event.task_id, action, createdAt: event.created_at, tone }
  }))

function openActivity(item: (typeof activities.value)[number]) {
  if (item.employeeId) emit('select', item.employeeId)
  else if (item.taskId) router.push(`/tasks/${item.taskId}`)
}
function formatClock(value: string) {
  const normalized = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`
  return new Date(normalized).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}
</script>

<style scoped>
.activity-bar{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;width:min(1430px,calc(100% - 170px));height:55px;min-width:0;padding:0 18px;border:1px solid rgba(215,228,222,.88);border-bottom:0;border-left:0;border-radius:0 15px 0 0;background:rgba(255,255,255,.91);box-shadow:0 -9px 30px rgba(39,72,60,.09);backdrop-filter:blur(15px)}.activity-bar>header{display:flex;align-items:center;gap:9px;padding-right:19px;color:#fff;border-right:1px solid #dce7e2}.activity-bar>header>svg{box-sizing:content-box;padding:8px;border-radius:8px;background:#18ae73}.activity-bar>header strong{color:#23463d;font-size:12px;white-space:nowrap}.activity-bar__items{display:flex;align-items:center;min-width:0;overflow:hidden}.activity-bar__items button{display:flex;align-items:center;gap:7px;min-width:0;flex:1 1 0;height:35px;padding:0 16px;color:#566c65;border:0;border-right:1px solid #e1eae6;background:transparent;font-size:10px;cursor:pointer;transition:background-color .16s ease}.activity-bar__items button:hover{background:rgba(235,248,242,.78)}.activity-bar__items i{flex:none;width:7px;height:7px;border-radius:50%;background:var(--astra-primary)}.activity-bar__items button[data-tone='warning'] i{background:var(--astra-warning)}.activity-bar__items button[data-tone='danger'] i{background:var(--astra-danger)}.activity-bar__items time{flex:none;color:#879790;font-variant-numeric:tabular-nums}.activity-bar__items strong{flex:none;max-width:66px;overflow:hidden;color:#34554c;text-overflow:ellipsis;white-space:nowrap}.activity-bar__items span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.activity-bar__empty{padding-left:18px;color:#86968f;font-size:10px}.activity-bar__more{display:flex;align-items:center;gap:2px;padding-left:14px;color:#2b8a68;font-size:10px;white-space:nowrap}
@media(max-width:900px){.activity-bar__items button:nth-child(n+4){display:none}.activity-bar{padding-inline:12px}.activity-bar>header{padding-right:10px}.activity-bar__items button{padding-inline:9px}}
@media(max-width:600px){.activity-bar{width:100%;height:48px;padding-inline:9px;border-radius:0}.activity-bar>header{padding-right:8px}.activity-bar>header>svg{padding:6px}.activity-bar__items button:nth-child(n+2){display:none}.activity-bar__items button{padding-inline:8px}.activity-bar__items strong{max-width:90px}.activity-bar__more{display:none}}
</style>
