<template>
  <div class="employee-gallery">
    <RouterLink v-for="(employee, index) in employees" :key="employee.id" class="employee-gallery__item" :data-status="employee.status" :to="`/employees/${employee.id}`">
      <span class="employee-gallery__visual">
        <EmployeeWorkstation :employee-id="employee.id" :status="employee.status" :variant="index + 1" />
      </span>
      <span class="employee-gallery__content">
        <span class="employee-gallery__heading">
          <span><strong>{{ employeeDisplayName(employee.name) }}</strong><small>{{ employee.role }}</small></span>
          <AstraStatusBadge :status="employee.status" :pulse="employee.status === 'WORKING'" />
        </span>
        <span class="employee-gallery__task">
          <small>当前任务</small>
          <strong>{{ currentTask(employee.id)?.title ?? idleTitle(employee.status) }}</strong>
          <span>{{ platformCopy(currentTask(employee.id)?.current_progress) || statusCopy(employee.status) }}</span>
        </span>
        <span class="employee-gallery__metrics">
          <span><small>今日完成</small><strong>{{ employee.today_completed }} 项</strong></span>
          <span><small>模型用量</small><strong>{{ formatTokens(employee.today_usage.total_tokens) }}</strong></span>
        </span>
      </span>
    </RouterLink>
    <AstraEmptyState v-if="!employees.length" :icon="UsersRound" title="没有匹配员工" description="调整筛选条件后重试。" />
  </div>
</template>

<script setup lang="ts">
import { UsersRound } from 'lucide-vue-next'
import { RouterLink } from 'vue-router'
import type { Employee, Task } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeeWorkstation from '@/components/office/EmployeeWorkstation.vue'
import { employeeDisplayName, formatTokens, platformCopy } from '@/utils/format'

const props = defineProps<{ employees: Employee[]; tasks: Task[] }>()
const currentTask = (employeeId: string) => props.tasks.find((task) => task.employee_id === employeeId && ['READY', 'RUNNING', 'WAIT_HUMAN', 'EXECUTION_ERROR'].includes(task.status))
const statusCopy = (status: string) => ({ WORKING: '正在推进任务', IDLE: '等待任务', WAIT_HUMAN: '等待人工补充信息', PAUSED: '暂停接收新任务', OFFLINE: '当前离线', ERROR: '工作现场已保留' }[status] ?? '等待状态更新')
const idleTitle = (status: string) => status === 'IDLE' ? '等待新任务' : status === 'WAIT_HUMAN' ? '需要人工处理' : status === 'ERROR' ? '执行异常' : '暂无任务'
</script>

<style scoped>
.employee-gallery { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); column-gap: 26px; row-gap: 30px; padding: 24px; }
.employee-gallery__item { position: relative; display: grid; grid-template-rows: 245px auto; min-width: 0; color: inherit; }
.employee-gallery__item::after { position: absolute; right: -13px; top: 16px; bottom: 16px; width: 1px; background: var(--astra-border); content: ''; }
.employee-gallery__item:nth-child(3n)::after { display: none; }
.employee-gallery__item:hover .employee-workstation { transform: translateY(-6px); }
.employee-gallery__visual { position: relative; display: block; min-width: 0; overflow: hidden; }
.employee-gallery__visual::before { position: absolute; right: 10%; bottom: 4%; left: 10%; height: 42%; border-radius: 50%; background: radial-gradient(ellipse,rgba(199,219,211,.52),rgba(229,237,234,.08) 64%,transparent 70%); content: ''; }
.employee-gallery__visual :deep(.employee-workstation) { transition: transform .2s ease; }
.employee-gallery__content { display: grid; grid-template-rows: auto 1fr auto; min-width: 0; padding: 10px 6px 0; border-top: 1px solid #cbd8d3; }
.employee-gallery__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.employee-gallery__heading > span { display: grid; min-width: 0; }
.employee-gallery__heading strong { overflow: hidden; color: var(--astra-text-primary); font: 700 20px var(--astra-font-display); text-overflow: ellipsis; white-space: nowrap; }
.employee-gallery__heading small { color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.employee-gallery__task { display: grid; align-content: center; min-width: 0; padding: 14px 0; }
.employee-gallery__task small,.employee-gallery__metrics small { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.employee-gallery__task strong { overflow: hidden; margin: 3px 0 2px; color: var(--astra-text-primary); font-size: var(--astra-font-body); text-overflow: ellipsis; white-space: nowrap; }
.employee-gallery__task > span { overflow: hidden; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.employee-gallery__metrics { display: grid; grid-template-columns: 1fr 1fr; padding-top: 10px; border-top: 1px solid var(--astra-border); }
.employee-gallery__metrics > span { display: grid; }
.employee-gallery__metrics > span + span { padding-left: 16px; border-left: 1px solid var(--astra-border); }
.employee-gallery__metrics strong { color: var(--astra-text-primary); font-size: var(--astra-font-body); }
@media(max-width:1180px){.employee-gallery{grid-template-columns:repeat(2,minmax(0,1fr))}.employee-gallery__item:nth-child(3n)::after{display:block}.employee-gallery__item:nth-child(2n)::after{display:none}}
@media(max-width:760px){.employee-gallery{grid-template-columns:1fr;padding:18px}.employee-gallery__item{grid-template-rows:230px auto}.employee-gallery__item::after{display:none!important}}
</style>
