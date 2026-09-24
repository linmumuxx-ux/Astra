<template>
  <el-drawer
    :model-value="true"
    size="min(390px, 100vw)"
    :with-header="false"
    append-to-body
    lock-scroll
    destroy-on-close
    data-testid="office-employee-drawer"
    class="office-employee-drawer"
    @close="emit('close')"
  >
        <header>
          <div class="employee-drawer__identity">
            <EmployeeAvatar :employee="employee.employee" :character-index="employee.characterIndex" size="large" />
            <span><small>{{ employee.id }}</small><strong :id="drawerTitleId">{{ employee.name }}</strong><em>{{ employee.role }}</em></span>
          </div>
          <el-button text circle aria-label="关闭员工详情" @click="emit('close')"><X :size="18" /></el-button>
        </header>

        <div class="employee-drawer__body">
          <section class="employee-drawer__state" :data-state="employee.state">
            <span><i />{{ employee.stateLabel }}</span>
            <strong>{{ employee.stateDetail }}</strong>
            <p v-if="employee.needHuman"><CircleAlert :size="15" />{{ waitingReason }}</p>
          </section>

          <section class="employee-drawer__task">
            <h3>当前任务</h3>
            <template v-if="employee.currentTask">
              <strong>{{ employee.currentTask.title }}</strong>
              <small>{{ employee.currentTask.id }}</small>
            </template>
            <p v-else>暂无当前任务，正在等待分配。</p>
          </section>

          <dl>
            <div><dt>所属团队</dt><dd>{{ teamName || '综合协作' }}</dd></div>
            <div><dt>当前阶段</dt><dd>{{ phaseText }}</dd></div>
            <div><dt>运行时间</dt><dd>{{ runningTime }}</dd></div>
            <div><dt>最近动作</dt><dd>{{ employee.lastAction }}</dd></div>
          </dl>
        </div>

        <footer>
          <el-button @click="$router.push(`/employees/${employee.id}`)">查看员工</el-button>
          <el-button v-if="employee.currentTask" @click="$router.push(`/tasks/${employee.currentTask.id}?compose=1`)"><MessageSquareText :size="15" />发送消息</el-button>
          <el-button v-if="employee.currentTask" type="primary" @click="$router.push(`/tasks/${employee.currentTask.id}`)">进入任务<ArrowUpRight :size="15" /></el-button>
        </footer>
  </el-drawer>
</template>

<script setup lang="ts">
import { ArrowUpRight, CircleAlert, MessageSquareText, X } from 'lucide-vue-next'
import { computed } from 'vue'
import EmployeeAvatar from '@/components/employee/EmployeeAvatar.vue'
import type { WorkspaceEmployee } from '@/features/workspace/eventAdapter'

const props = withDefaults(defineProps<{ employee: WorkspaceEmployee; teamName?: string }>(), { teamName: '' })
const emit = defineEmits<{ close: [] }>()
const drawerTitleId = `employee-drawer-${props.employee.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`
const waitingReason = computed(() => props.employee.currentTask?.human_required_reason
  || props.employee.currentTask?.human_intervention?.requested_input
  || '该员工正在等待人工补充信息。')
const phaseText = computed(() => ({ work: '任务执行', inquiry: '等待回复', result: '结果整理', message: '消息处理' })[props.employee.currentPhase] || props.employee.currentPhase)
const runningTime = computed(() => {
  const seconds = props.employee.runningSeconds
  if (!seconds) return props.employee.currentTask ? '不足 1 分钟' : '—'
  if (seconds < 3600) return `${Math.max(1, Math.floor(seconds / 60))} 分钟`
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor((seconds % 3600) / 60)} 分钟`
})
</script>

<style scoped>

.employee-drawer>header{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:102px;padding:16px 18px;border-bottom:1px solid var(--astra-border)}.employee-drawer__identity{display:flex;align-items:center;gap:12px;min-width:0}.employee-drawer__identity>span{display:grid;min-width:0}.employee-drawer__identity small{color:var(--astra-primary);font-size:var(--astra-font-helper);letter-spacing:.06em}.employee-drawer__identity strong,.employee-drawer__identity em{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.employee-drawer__identity strong{font-size:var(--astra-font-section)}.employee-drawer__identity em{margin-top:2px;color:var(--astra-text-muted);font-size:var(--astra-font-control);font-style:normal}
.employee-drawer__body{min-height:0;overflow-y:auto;padding:18px}.employee-drawer__state{padding:14px;border:1px solid var(--astra-primary-border);border-radius:13px;background:#f2faf6}.employee-drawer__state>span{display:flex;align-items:center;gap:6px;color:var(--astra-primary);font-size:var(--astra-font-control);font-weight: var(--astra-weight-bold)}.employee-drawer__state>span i{width:8px;height:8px;border-radius:50%;background:currentColor}.employee-drawer__state>strong{display:block;margin-top:7px;font-size:var(--astra-font-emphasis);line-height:1.45}.employee-drawer__state>p{display:flex;gap:6px;margin:9px 0 0;padding-top:9px;color:#925b1c;border-top:1px solid #efdbc0;font-size:var(--astra-font-control);line-height:1.45}.employee-drawer__state[data-state='NEED_HUMAN'],.employee-drawer__state[data-state='WAITING']{border-color:#efd2aa;background:#fff8ee}.employee-drawer__state[data-state='NEED_HUMAN']>span,.employee-drawer__state[data-state='WAITING']>span{color:#be741f}.employee-drawer__state[data-state='ERROR']{border-color:#edc2ba;background:#fff5f3}.employee-drawer__state[data-state='ERROR']>span{color:var(--astra-danger)}
.employee-drawer__task{margin-top:20px;padding-bottom:17px;border-bottom:1px solid var(--astra-border)}.employee-drawer__task h3{margin:0 0 9px;color:var(--astra-text-muted);font-size:var(--astra-font-control);font-weight: var(--astra-weight-bold)}.employee-drawer__task>strong,.employee-drawer__task>small{display:block}.employee-drawer__task>strong{font-size:var(--astra-font-emphasis);line-height:1.5}.employee-drawer__task>small{margin-top:4px;color:var(--astra-text-muted);font-size:var(--astra-font-helper)}.employee-drawer__task>p{margin:0;color:var(--astra-text-secondary);font-size:var(--astra-font-body)}.employee-drawer dl{display:grid;margin:9px 0 0}.employee-drawer dl>div{display:grid;grid-template-columns:72px minmax(0,1fr);gap:10px;padding:11px 0;border-bottom:1px solid #edf2ef}.employee-drawer dt{color:var(--astra-text-muted);font-size:var(--astra-font-control)}.employee-drawer dd{overflow:hidden;margin:0;color:var(--astra-text-primary);font-size:var(--astra-font-control);line-height:1.45;text-overflow:ellipsis}.employee-drawer>footer{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px;padding:13px 16px;border-top:1px solid var(--astra-border);background:#fbfdfc}
}



:global(.office-employee-drawer .el-drawer__body){display:grid;grid-template-rows:auto minmax(0,1fr) auto;padding:0;overflow:hidden}
</style>
