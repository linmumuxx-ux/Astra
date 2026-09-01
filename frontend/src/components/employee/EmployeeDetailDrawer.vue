<template>
  <Teleport to="body">
    <div v-if="employee && model" class="employee-drawer-layer" role="presentation" @click.self="emit('close')">
      <aside class="employee-drawer" role="dialog" aria-modal="true" :aria-label="`${model.name} 员工详情`">
        <header class="employee-drawer__header">
          <div class="employee-drawer__identity">
            <EmployeeAvatar :employee="employee" size="large" />
            <div><small>{{ employee.id }}</small><h2>{{ model.name }}</h2><p>{{ employee.role }}</p></div>
          </div>
          <button class="icon-button" type="button" aria-label="关闭员工详情" @click="emit('close')"><X :size="18" /></button>
        </header>

        <div class="employee-drawer__body">
          <section class="employee-drawer__status" :data-help="model.needHelp">
            <div><span>当前状态</span><AstraStatusBadge :status="employee.status" :pulse="employee.status === 'WORKING'" /></div>
            <strong>{{ model.statusTextLong }}</strong>
            <p v-if="model.needHelp">{{ model.currentTask?.human_required_reason || model.currentTask?.human_intervention?.requested_input || '该员工正在等待人工补充信息。' }}</p>
          </section>

          <section class="drawer-section">
            <header><h3>当前任务</h3><RouterLink v-if="model.currentTask" :to="`/tasks/${model.currentTask.id}`">查看任务 <ArrowUpRight :size="14" /></RouterLink></header>
            <div v-if="model.currentTask" class="drawer-current-task">
              <strong>{{ model.currentTask.title }}</strong>
              <p>{{ platformCopy(model.currentTask.current_progress) || '等待进度更新' }}</p>
              <dl><div><dt>任务编号</dt><dd>{{ model.currentTask.id }}</dd></div><div><dt>最近活动</dt><dd>{{ formatTime(model.lastActiveAt) }}</dd></div></dl>
            </div>
            <AstraEmptyState v-else :icon="Coffee" title="当前空闲" description="正在等待下一项匹配任务。" />
          </section>

          <section class="drawer-section">
            <header><h3>基本信息</h3></header>
            <dl class="drawer-facts">
              <div><dt>所在区域</dt><dd>{{ model.areaName }}</dd></div>
              <div><dt>职责</dt><dd>{{ employee.description || employee.role }}</dd></div>
              <div><dt>启用状态</dt><dd>{{ employee.enabled ? '已启用' : '已停用' }}</dd></div>
              <div><dt>最近活动</dt><dd>{{ formatTime(model.lastActiveAt) }}</dd></div>
            </dl>
          </section>

          <section class="drawer-section">
            <header><h3>最近任务</h3></header>
            <div class="drawer-task-list">
              <RouterLink v-for="task in recentTasks" :key="task.id" :to="`/tasks/${task.id}`">
                <span><strong>{{ task.title }}</strong><small>{{ task.id }} · {{ formatTime(task.updated_at) }}</small></span><AstraStatusBadge :status="task.status" />
              </RouterLink>
              <AstraEmptyState v-if="!recentTasks.length" :icon="ClipboardList" title="暂无任务记录" description="员工处理任务后会显示在这里。" />
            </div>
          </section>

          <section class="drawer-section">
            <header><h3>配置摘要</h3></header>
            <dl class="drawer-facts">
              <div><dt>执行方式</dt><dd>{{ environmentLabel(employee.execution_environment) }}</dd></div>
              <div><dt>Agent 模型</dt><dd>{{ employee.execution_environment?.model_name || '使用默认配置' }}</dd></div>
              <div><dt>自动领取</dt><dd>{{ employee.auto_claim ? '已开启' : '已关闭' }}</dd></div>
              <div><dt>自动执行</dt><dd>{{ employee.auto_execute ? '已开启' : '已关闭' }}</dd></div>
            </dl>
          </section>
        </div>

        <footer class="employee-drawer__footer">
          <RouterLink class="button" :to="`/employees/${employee.id}`">完整记录</RouterLink>
          <RouterLink class="button button--primary" :to="`/settings?employee=${employee.id}`"><Settings2 :size="15" /> 编辑配置</RouterLink>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ArrowUpRight, ClipboardList, Coffee, Settings2, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { RouterLink } from 'vue-router'
import type { Employee, Task } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeeAvatar from '@/components/employee/EmployeeAvatar.vue'
import { toEmployeeViewModel } from '@/features/employees/presentation'
import { environmentLabel, formatTime, platformCopy } from '@/utils/format'

const props = defineProps<{ employee: Employee | null; tasks: Task[] }>()
const emit = defineEmits<{ close: [] }>()
const model = computed(() => props.employee ? toEmployeeViewModel(props.employee, props.tasks) : null)
const recentTasks = computed(() => props.employee
  ? props.tasks.filter((task) => task.employee_id === props.employee?.id).sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 5)
  : [])
function handleEscape(event: KeyboardEvent) { if (props.employee && event.key === 'Escape') emit('close') }
watch(() => props.employee, (employee) => document.body.classList.toggle('overlay-open', Boolean(employee)), { immediate: true })
onMounted(() => window.addEventListener('keydown', handleEscape))
onBeforeUnmount(() => { document.body.classList.remove('overlay-open'); window.removeEventListener('keydown', handleEscape) })
</script>

<style scoped>
.employee-drawer-layer { position: fixed; inset: 0; z-index: 80; display: flex; justify-content: flex-end; background: rgba(24,45,39,.22); backdrop-filter: blur(2px); }
.employee-drawer { display: grid; grid-template-rows: auto minmax(0,1fr) auto; width: min(620px,100%); height: 100%; border-left: 1px solid var(--astra-border); background: #fff; box-shadow: -18px 0 50px rgba(33,60,52,.16); animation: drawer-in .2s ease-out; }
.employee-drawer__header { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 108px; padding: 18px 22px; border-bottom: 1px solid var(--astra-border); }
.employee-drawer__identity { display: flex; align-items: center; gap: 15px; min-width: 0; }
.employee-drawer__identity > div { min-width: 0; }.employee-drawer__identity small { color: var(--astra-primary); font-size: 12px; letter-spacing: .08em; }.employee-drawer__identity h2 { overflow: hidden; margin: 1px 0; font: 700 23px var(--astra-font-display); text-overflow: ellipsis; white-space: nowrap; }.employee-drawer__identity p { margin: 0; color: var(--astra-text-secondary); }
.employee-drawer__body { min-height: 0; overflow-y: auto; padding: 20px 22px 28px; }
.employee-drawer__status { padding: 16px; border: 1px solid var(--astra-primary-border); border-radius: 12px; background: #f1faf6; }.employee-drawer__status[data-help='true'] { border-color: color-mix(in srgb,var(--astra-warning) 42%,transparent); background: #fff8ef; }.employee-drawer__status > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.employee-drawer__status span { color: var(--astra-text-muted); font-size: 13px; }.employee-drawer__status strong { display: block; margin-top: 9px; }.employee-drawer__status p { margin: 5px 0 0; color: #8b561f; font-size: 14px; }
.drawer-section { margin-top: 22px; }.drawer-section > header { display: flex; align-items: center; justify-content: space-between; min-height: 34px; margin-bottom: 10px; }.drawer-section h3 { margin: 0; font: 700 16px var(--astra-font-display); }.drawer-section header a { display: inline-flex; align-items: center; gap: 4px; color: var(--astra-primary); font-size: 13px; }
.drawer-current-task { padding: 15px; border: 1px solid var(--astra-border); border-radius: 11px; background: #fafcfb; }.drawer-current-task > strong { display: block; }.drawer-current-task > p { margin: 5px 0 14px; color: var(--astra-text-secondary); }.drawer-current-task dl,.drawer-facts { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; margin: 0; }.drawer-current-task dl > div,.drawer-facts > div { min-width: 0; padding: 10px 12px; border-radius: 9px; background: #f4f8f6; }.drawer-current-task dt,.drawer-facts dt { color: var(--astra-text-muted); font-size: 12px; }.drawer-current-task dd,.drawer-facts dd { overflow: hidden; margin: 3px 0 0; color: var(--astra-text-primary); font-size: 14px; text-overflow: ellipsis; }
.drawer-task-list { display: grid; }.drawer-task-list > a { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; padding: 12px 0; border-bottom: 1px solid var(--astra-border); }.drawer-task-list > a > span { display: grid; min-width: 0; }.drawer-task-list strong,.drawer-task-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.drawer-task-list strong { font-size: 14px; }.drawer-task-list small { color: var(--astra-text-muted); font-size: 12px; }
.employee-drawer__footer { display: flex; justify-content: flex-end; gap: 9px; padding: 15px 22px; border-top: 1px solid var(--astra-border); background: #fff; }
@keyframes drawer-in { from { transform: translateX(30px); opacity: .5; } }
@media(max-width:600px){.employee-drawer__header{padding-inline:16px}.employee-drawer__body{padding-inline:16px}.drawer-current-task dl,.drawer-facts{grid-template-columns:1fr}.employee-drawer__footer{padding-inline:16px}}
</style>
