<template>
  <div class="page" data-testid="employee-list-page">
    <section class="page-intro compact-intro"><div><h2>数字员工</h2><p>通过数字办公室或列表查看员工的当前工作。</p></div><div class="hero-actions"><div class="range-switch"><button :class="{ active: view === 'office' }" @click="view = 'office'">办公室</button><button :class="{ active: view === 'list' }" @click="view = 'list'">列表</button></div><RouterLink class="button button--primary" to="/settings?create=1"><Plus :size="15" /> 新增员工</RouterLink></div></section>
    <div class="filter-bar"><div class="search-box"><Search :size="15" /><input v-model="query" placeholder="搜索员工名称或岗位" /></div><select v-model="status" aria-label="员工状态"><option value="">全部状态</option><option value="WORKING">工作中</option><option value="IDLE">空闲</option><option value="WAIT_HUMAN">等待人工</option><option value="PAUSED">已暂停</option><option value="ERROR">异常</option><option value="OFFLINE">离线</option></select><select v-model="environment" aria-label="工作环境"><option value="">全部环境</option><option value="LOCAL">本地</option><option value="LINUX_REMOTE">Linux 远程</option><option value="UNAVAILABLE">环境异常</option></select><span class="filter-summary">{{ filtered.length }} 名员工</span></div>
    <AstraPanel v-if="view === 'office'" title="数字办公室" :subtitle="`${filtered.length} 名员工 · 按岗位分区`" flush><DigitalOffice :employees="filtered" :tasks="store.tasks" /></AstraPanel>
    <AstraPanel v-else flush>
      <div class="table-wrap"><table><thead><tr><th>员工</th><th>岗位</th><th>状态</th><th>工作范围</th><th>工作环境</th><th>当前任务</th><th>今日完成</th><th>今日 Token</th><th>工具调用</th><th></th></tr></thead><tbody>
        <tr v-for="employee in filtered" :key="employee.id" @click="$router.push(`/employees/${employee.id}`)"><td><RouterLink class="table-primary-link" :to="`/employees/${employee.id}`" @click.stop><strong>{{ employee.name }}</strong><small>{{ employee.id }}</small></RouterLink></td><td>{{ employee.role }}</td><td><AstraStatusBadge :status="employee.status" :pulse="employee.status === 'WORKING'" /></td><td><div class="scope-summary"><span>{{ employee.task_types.map(taskTypeLabel).join(' / ') }}</span><small>{{ employee.category_ids.map(categoryName).join('、') }}</small></div></td><td><strong>{{ environmentLabel(employee.execution_environment) }}</strong><small>{{ statusLabel(employee.execution_environment?.status ?? 'UNKNOWN') }}</small></td><td><strong>{{ currentTask(employee.id)?.title ?? '—' }}</strong><small>{{ platformCopy(currentTask(employee.id)?.current_progress) || '等待新任务' }}</small></td><td>{{ employee.today_completed }}</td><td>{{ formatTokens(employee.today_usage.total_tokens) }}</td><td>{{ employee.today_usage.tool_call_count ?? '—' }}</td><td><RouterLink class="row-detail-link" :to="`/employees/${employee.id}`" :aria-label="`查看 ${employee.name} 详情`" @click.stop><ChevronRight :size="16" /></RouterLink></td></tr>
        <tr v-if="!filtered.length"><td colspan="10"><AstraEmptyState :icon="Search" title="没有匹配员工" description="调整筛选条件后重试。" /></td></tr>
      </tbody></table></div>
    </AstraPanel>
  </div>
</template>
<script setup lang="ts">
import { ChevronRight, Plus, Search } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import DigitalOffice from '@/components/office/DigitalOffice.vue'
import { useAstraStore } from '@/stores/astra'
import { environmentLabel, formatTokens, platformCopy, statusLabel, taskTypeLabel } from '@/utils/format'
const store = useAstraStore(); const query = ref(''); const status = ref(''); const environment = ref(''); const view = ref<'office' | 'list'>('office')
onMounted(() => store.refresh())
const filtered = computed(() => store.employees.filter((employee) => { const environmentMatch = !environment.value || (environment.value === 'UNAVAILABLE' ? employee.execution_environment?.status === 'UNAVAILABLE' : employee.execution_environment?.mode === environment.value); return (!status.value || employee.status === status.value) && environmentMatch && (!query.value || `${employee.name}${employee.role}`.toLowerCase().includes(query.value.toLowerCase())) }))
const currentTask = (id: string) => store.activeTasks.find((task) => task.employee_id === id)
const categoryName = (id: string) => store.categories.find((item) => item.id === id)?.name ?? id
</script>
