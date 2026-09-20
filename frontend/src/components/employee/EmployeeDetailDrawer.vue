<template>
  <Teleport to="body">
    <div v-if="employee && model" class="employee-drawer-layer" role="presentation" @click.self="emit('close')">
      <aside class="employee-drawer" role="dialog" aria-modal="true" :aria-label="`${model.name} 员工详情`">
        <header class="employee-drawer__header">
          <div class="employee-drawer__identity">
            <EmployeeAvatar :employee="employee" size="large" />
            <div>
              <small>{{ employee.id }}</small>
              <h2>{{ model.name }}</h2>
              <p>{{ employee.role }}</p>
              <div class="employee-drawer__meta"><AstraStatusBadge :status="employee.runtime_state" :label="employee.runtime_status_label" :pulse="employee.status === 'WORKING'" /><span>最近活动 {{ formatTime(model.lastActiveAt) }}</span></div>
            </div>
          </div>
          <button class="icon-button" type="button" aria-label="关闭员工详情" @click="emit('close')"><X :size="18" /></button>
        </header>

        <div class="employee-drawer__body">
          <section class="drawer-section">
            <header><h3>运行状态</h3><RouterLink v-if="model.currentTask" :to="`/tasks/${model.currentTask.id}`">进入任务详情 <ArrowUpRight :size="14" /></RouterLink></header>
            <div v-if="model.currentTask" class="drawer-current-task">
              <strong>{{ model.currentTask.title }}</strong>
              <p v-if="platformCopy(model.currentTask.current_progress)">{{ platformCopy(model.currentTask.current_progress) }}</p>
              <dl>
                <div><dt>执行状态</dt><dd><AstraStatusBadge :status="model.currentTask.runtime_state" :label="model.currentTask.runtime_status_label" /></dd></div>
                <div><dt>开始时间</dt><dd>{{ formatTime(model.currentTask.started_at) }}</dd></div>
              </dl>
            </div>
            <p v-else class="drawer-idle">当前无执行任务</p>
          </section>

          <section class="drawer-section">
            <header><h3>基本信息</h3></header>
            <dl class="drawer-facts">
              <div><dt>员工编号</dt><dd>{{ employee.id }}</dd></div>
              <div><dt>岗位</dt><dd>{{ employee.role }}</dd></div>
              <div><dt>所在区域</dt><dd>{{ model.areaName }}</dd></div>
              <div><dt>职责</dt><dd>{{ employee.description || employee.role }}</dd></div>
              <div><dt>启用状态</dt><dd>{{ employee.enabled ? '已启用' : '已停用' }}</dd></div>
            </dl>
          </section>

          <section class="drawer-section">
            <header><h3>工作配置</h3></header>
            <dl class="drawer-facts">
              <div><dt>执行方式</dt><dd>{{ environmentLabel(employee.execution_environment) }}</dd></div>
              <div><dt>Agent / 模型</dt><dd>{{ employee.execution_environment?.model_name || '使用默认配置' }}</dd></div>
              <div><dt>工作环境</dt><dd>{{ employee.execution_environment?.name || '未配置' }}</dd></div>
              <div><dt>自动领取</dt><dd>{{ employee.auto_claim ? '已开启' : '已关闭' }}</dd></div>
              <div><dt>自动执行</dt><dd>{{ employee.auto_execute ? '已开启' : '已关闭' }}</dd></div>
            </dl>
          </section>

          <section class="drawer-section">
            <header><h3>最近任务</h3><RouterLink :to="`/employees/${employee.id}`">查看全部任务 <ArrowUpRight :size="14" /></RouterLink></header>
            <div class="drawer-task-list">
              <RouterLink v-for="task in recentTasks" :key="task.id" :to="`/tasks/${task.id}`">
                <span><strong>{{ task.title }}</strong><small>{{ formatTime(task.updated_at) }}</small></span><AstraStatusBadge :status="task.runtime_state" :label="task.runtime_status_label" />
              </RouterLink>
              <p v-if="!recentTasks.length" class="drawer-idle">暂无任务记录</p>
            </div>
          </section>
        </div>

        <footer class="employee-drawer__footer">
          <RouterLink class="button" :to="`/employees/${employee.id}`">查看全部任务</RouterLink>
          <button type="button" class="button button--primary" @click="emit('edit', employee)"><Settings2 :size="15" /> 编辑</button>
        </footer>
      </aside>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ArrowUpRight, Settings2, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { RouterLink } from 'vue-router'
import type { Employee, Task } from '@/api/types'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeeAvatar from '@/components/employee/EmployeeAvatar.vue'
import { toEmployeeViewModel } from '@/features/employees/presentation'
import { environmentLabel, formatTime, platformCopy } from '@/utils/format'

const props = defineProps<{ employee: Employee | null; tasks: Task[] }>()
const emit = defineEmits<{ close: []; edit: [employee: Employee] }>()
const model = computed(() => props.employee ? toEmployeeViewModel(props.employee, props.tasks) : null)
const recentTasks = computed(() => props.employee
  ? props.tasks.filter((task) => task.employee_id === props.employee?.id).sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 3)
  : [])
function handleEscape(event: KeyboardEvent) { if (props.employee && event.key === 'Escape') emit('close') }
watch(() => props.employee, (employee) => document.body.classList.toggle('overlay-open', Boolean(employee)), { immediate: true })
onMounted(() => window.addEventListener('keydown', handleEscape))
onBeforeUnmount(() => { document.body.classList.remove('overlay-open'); window.removeEventListener('keydown', handleEscape) })
</script>

<style scoped>
.employee-drawer-layer { position: fixed; inset: 0; z-index: 80; display: flex; justify-content: flex-end; background: rgba(24,45,39,.22); backdrop-filter: blur(2px); }
.employee-drawer { display: grid; grid-template-rows: auto minmax(0,1fr) auto; width: min(620px,100%); height: 100%; border-left: 1px solid var(--astra-border); background: #fff; box-shadow: -18px 0 50px rgba(33,60,52,.16); animation: drawer-in .2s ease-out; }
.employee-drawer__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding: 20px 22px; border-bottom: 1px solid var(--astra-border); }
.employee-drawer__identity { display: flex; align-items: center; gap: 15px; min-width: 0; }
.employee-drawer__identity > div { min-width: 0; }.employee-drawer__identity small { color: var(--astra-primary); font-size: var(--astra-font-body); letter-spacing: .08em; }.employee-drawer__identity h2 { overflow: hidden; margin: 1px 0; line-height: normal; text-overflow: ellipsis; white-space: nowrap; }.employee-drawer__identity p { margin: 0; color: var(--astra-text-secondary); }
.employee-drawer__meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; margin-top: 8px; }.employee-drawer__meta span { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.employee-drawer__body { min-height: 0; overflow-y: auto; padding: 20px 22px 28px; }
.drawer-section { margin-top: 22px; }.drawer-section:first-child { margin-top: 0; }.drawer-section > header { display: flex; align-items: center; justify-content: space-between; min-height: 34px; margin-bottom: 10px; }.drawer-section h3 { margin: 0; line-height: normal; }.drawer-section header a { display: inline-flex; align-items: center; gap: 4px; color: var(--astra-primary); font-size: var(--astra-font-label); }
.drawer-current-task { padding: 15px; border: 1px solid var(--astra-border); border-radius: 11px; background: #fafcfb; }.drawer-current-task > strong { display: block; }.drawer-current-task > p { margin: 5px 0 14px; color: var(--astra-text-secondary); }.drawer-current-task dl,.drawer-facts { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; margin: 0; }.drawer-current-task dl > div,.drawer-facts > div { min-width: 0; padding: 10px 12px; border-radius: 9px; background: #f4f8f6; }.drawer-current-task dt,.drawer-facts dt { color: var(--astra-text-muted); font-size: var(--astra-font-body); }.drawer-current-task dd,.drawer-facts dd { overflow: hidden; margin: 3px 0 0; color: var(--astra-text-primary); font-size: var(--astra-font-emphasis); text-overflow: ellipsis; }
.drawer-idle { margin: 0; padding: 2px 0; color: var(--astra-text-muted); font-size: var(--astra-font-body); }
.drawer-task-list { display: grid; }.drawer-task-list > a { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; padding: 12px 0; border-bottom: 1px solid var(--astra-border); }.drawer-task-list > a:last-child { border-bottom: 0; }.drawer-task-list > a > span { display: grid; min-width: 0; }.drawer-task-list strong,.drawer-task-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.drawer-task-list strong { font-size: var(--astra-font-emphasis); }.drawer-task-list small { color: var(--astra-text-muted); font-size: var(--astra-font-body); }
.employee-drawer__footer { display: flex; justify-content: flex-end; gap: 9px; padding: 15px 22px; border-top: 1px solid var(--astra-border); background: #fff; }
@keyframes drawer-in { from { transform: translateX(30px); opacity: .5; } }
@media(max-width:600px){.employee-drawer__header{padding-inline:16px}.employee-drawer__body{padding-inline:16px}.drawer-current-task dl,.drawer-facts{grid-template-columns:1fr}.employee-drawer__footer{padding-inline:16px}}
</style>