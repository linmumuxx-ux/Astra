<template>
  <div class="page employee-page" data-testid="employee-list-page">
    <section class="page-intro compact-intro"><div><h2>数字员工</h2><p>查看员工状态、工作分布与当前任务</p></div><RouterLink class="button button--primary" to="/settings?create=1"><Plus :size="17" /> 新增员工</RouterLink></section>
    <div class="filter-bar employee-filter">
      <div class="search-box"><Search :size="17" /><input v-model="query" placeholder="搜索员工名称 / 岗位 / 任务" /></div>
      <select v-model="status" aria-label="员工状态"><option value="">状态：全部</option><option value="WORKING">工作中</option><option value="IDLE">空闲</option><option value="WAIT_HUMAN">等待人工</option><option value="PAUSED">已暂停</option><option value="ERROR">执行异常</option><option value="OFFLINE">离线</option></select>
      <select v-model="zone" aria-label="员工分区"><option value="">分区：全部</option><option v-for="role in roles" :key="role" :value="role">{{ roleZoneLabel(role) }}</option></select>
      <div class="view-switch"><button :class="{ active: view === 'office' }" @click="view = 'office'"><LayoutGrid :size="16" /> 办公室视图</button><button :class="{ active: view === 'list' }" @click="view = 'list'"><List :size="16" /> 列表视图</button></div>
    </div>
    <section class="employee-layout">
      <AstraPanel v-if="view === 'office'" class="employee-office" title="数字办公区" :subtitle="`${filtered.length} 名数字员工`" flush><EmployeeGallery :employees="filtered" :tasks="store.tasks" /></AstraPanel>
      <AstraPanel v-else class="employee-office" flush><div class="table-wrap"><table><thead><tr><th>员工</th><th>岗位</th><th>状态</th><th>工作范围</th><th>工作环境</th><th>当前任务</th><th>今日完成</th><th>模型用量</th><th>工具调用</th><th></th></tr></thead><tbody>
        <tr v-for="employee in filtered" :key="employee.id" @click="$router.push(`/employees/${employee.id}`)"><td><RouterLink class="table-primary-link" :to="`/employees/${employee.id}`" @click.stop><strong>{{ employeeDisplayName(employee.name) }}</strong><small>{{ employee.id }}</small></RouterLink></td><td>{{ employee.role }}</td><td><AstraStatusBadge :status="employee.status" :pulse="employee.status === 'WORKING'" /></td><td><div class="scope-summary"><span>{{ employee.task_types.map(taskTypeLabel).join(' / ') }}</span><small>{{ employee.category_ids.map(categoryName).join('、') }}</small></div></td><td><strong>{{ environmentLabel(employee.execution_environment) }}</strong><small>{{ statusLabel(employee.execution_environment?.status ?? 'UNKNOWN') }}</small></td><td><strong>{{ currentTask(employee.id)?.title ?? '—' }}</strong><small>{{ platformCopy(currentTask(employee.id)?.current_progress) || '等待新任务' }}</small></td><td>{{ employee.today_completed }}</td><td>{{ formatTokens(employee.today_usage.total_tokens) }}</td><td>{{ employee.today_usage.tool_call_count ?? '—' }}</td><td><RouterLink class="row-detail-link" :to="`/employees/${employee.id}`" :aria-label="`查看 ${employeeDisplayName(employee.name)} 详情`" @click.stop><ChevronRight :size="16" /></RouterLink></td></tr>
        <tr v-if="!filtered.length"><td colspan="10"><AstraEmptyState :icon="Search" title="没有匹配员工" description="调整筛选条件后重试。" /></td></tr>
      </tbody></table></div></AstraPanel>
      <aside class="employee-aside">
        <AstraPanel title="员工状态概览"><div class="status-overview">
          <article><span class="status-overview__icon status-overview__icon--online"><UsersRound :size="19" /></span><small>在线员工</small><strong>{{ onlineCount }}</strong></article><article><span class="status-overview__icon status-overview__icon--working"><Activity :size="19" /></span><small>工作中</small><strong>{{ count('WORKING') }}</strong></article><article><span class="status-overview__icon status-overview__icon--idle"><Coffee :size="19" /></span><small>空闲</small><strong>{{ count('IDLE') }}</strong></article><article><span class="status-overview__icon status-overview__icon--waiting"><Hand :size="19" /></span><small>等待人工</small><strong>{{ count('WAIT_HUMAN') }}</strong></article><article><span class="status-overview__icon status-overview__icon--error"><CircleAlert :size="19" /></span><small>执行异常</small><strong>{{ count('ERROR') }}</strong></article>
        </div></AstraPanel>
        <AstraPanel title="近期动态"><div class="event-feed employee-events"><article v-for="event in meaningfulEvents.slice(0, 5)" :key="event.id"><span class="event-dot"><BriefcaseBusiness :size="13" /></span><div><strong>{{ platformCopy(event.message) }}</strong><p>{{ employeeName(event.employee_id) }}</p></div><time>{{ formatTime(event.created_at) }}</time></article><AstraEmptyState v-if="!meaningfulEvents.length" :icon="Activity" title="暂无动态" description="员工工作后会显示在这里。" /></div></AstraPanel>
      </aside>
    </section>
  </div>
</template>
<script setup lang="ts">
import { Activity, BriefcaseBusiness, ChevronRight, CircleAlert, Coffee, Hand, LayoutGrid, List, Plus, Search, UsersRound } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeeGallery from '@/components/office/EmployeeGallery.vue'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, environmentLabel, formatTime, formatTokens, platformCopy, statusLabel, taskTypeLabel } from '@/utils/format'
const store = useAstraStore(); const query = ref(''); const status = ref(''); const zone = ref(''); const view = ref<'office' | 'list'>('office')
onMounted(() => store.refresh())
const roles = computed(() => [...new Set(store.employees.map((employee) => employee.role))])
const currentTask = (id: string) => store.activeTasks.find((task) => task.employee_id === id)
const filtered = computed(() => store.employees.filter((employee) => { const task = currentTask(employee.id); const search = `${employee.name}${employee.role}${task?.title ?? ''}`.toLowerCase(); return (!status.value || employee.status === status.value) && (!zone.value || employee.role === zone.value) && (!query.value || search.includes(query.value.toLowerCase())) }))
const count = (employeeStatus: string) => store.employees.filter((employee) => employee.status === employeeStatus).length
const onlineCount = computed(() => store.employees.filter((employee) => !['OFFLINE', 'PAUSED'].includes(employee.status)).length)
const meaningfulEvents = computed(() => store.events.filter((event) => !/(模型用量|token|工具调用|工作环境检查|工作环境已更新|缓存|Agent 调用|Agent 会话|会话已启动|Bash|Shell)/i.test(platformCopy(event.message))))
const categoryName = (id: string) => store.categories.find((item) => item.id === id)?.name ?? id
const employeeName = (id: string | null) => employeeDisplayName(store.employees.find((employee) => employee.id === id)?.name ?? (id ? '数字员工' : '系统更新'))
const roleZoneLabel = (role: string) => `${role.replace(/(?:数字)?员工$|专员$|工程师$/u, '').trim() || role}区`
</script>
