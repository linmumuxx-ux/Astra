<template>
  <div class="page employee-page" data-testid="employee-list-page">
    <section class="page-intro compact-intro">
      <div><h2>数字员工</h2><p>集中管理员工职责、运行状态与执行配置</p></div>
      <div class="employee-page__actions"><button class="button" type="button" :disabled="store.loading" @click="store.refresh()"><RefreshCw :size="16" :class="{ spin: store.loading }" /> 刷新</button><RouterLink class="button button--primary" to="/settings?create=1"><Plus :size="17" /> 新建数字员工</RouterLink></div>
    </section>

    <div class="filter-bar employee-filter">
      <label class="search-box"><Search :size="17" /><input v-model="query" aria-label="搜索员工" placeholder="搜索员工名称 / 编号 / 职责 / 任务" /></label>
      <select v-model="status" aria-label="员工状态"><option value="">状态：全部</option><option value="WORKING">工作中</option><option value="IDLE">空闲</option><option value="WAIT_HUMAN">需要人工处理</option><option value="PAUSED">已暂停</option><option value="ERROR">异常</option><option value="OFFLINE">离线</option></select>
      <select v-model="role" aria-label="员工职责"><option value="">职责：全部</option><option v-for="item in roles" :key="item" :value="item">{{ item }}</option></select>
      <select v-model="area" aria-label="所属区域"><option value="">区域：全部</option><option v-for="item in workspaceAreas" :key="item.id" :value="item.id">{{ item.name }}</option></select>
      <select v-model="enabled" aria-label="启用状态"><option value="">启用：全部</option><option value="enabled">已启用</option><option value="disabled">已停用</option></select>
      <span class="filter-summary">{{ filtered.length }} 名员工</span>
    </div>

    <section class="employee-table-panel" aria-label="数字员工列表">
      <div class="employee-table-scroll">
        <table>
          <thead><tr><th class="employee-col">员工</th><th>编号</th><th>职责</th><th>状态</th><th class="task-col">当前任务</th><th>执行器 / 模型</th><th>最近活动</th><th>启用</th><th class="actions-col">操作</th></tr></thead>
          <tbody>
            <tr v-for="item in paged" :key="item.id" @click="openDetail(item.id)">
              <td><div class="employee-cell"><EmployeeAvatar :employee="item.employee" /><span><strong>{{ item.name }}</strong><small :title="item.employee.description">{{ item.employee.description || '暂无职责说明' }}</small></span></div></td>
              <td><span class="employee-id">{{ item.id }}</span></td>
              <td><span class="truncate" :title="item.role">{{ item.role }}</span></td>
              <td><AstraStatusBadge :status="item.status" :pulse="item.status === 'WORKING'" /></td>
              <td><RouterLink v-if="item.currentTask" class="task-link" :to="`/tasks/${item.currentTask.id}`" :title="item.currentTaskName" @click.stop><strong>{{ item.currentTaskName }}</strong><small>{{ platformCopy(item.currentTask.current_progress) || '等待进度更新' }}</small></RouterLink><span v-else>—</span></td>
              <td><span class="environment-cell"><strong>{{ environmentLabel(item.employee.execution_environment) }}</strong><small :title="item.employee.execution_environment?.model_name ?? ''">{{ item.employee.execution_environment?.model_name || '默认模型' }}</small></span></td>
              <td>{{ formatTime(item.lastActiveAt) }}</td>
              <td><span class="enabled-tag" :data-enabled="item.employee.enabled">{{ item.employee.enabled ? '已启用' : '已停用' }}</span></td>
              <td class="actions-col" @click.stop><div class="row-actions"><button type="button" :aria-label="`查看 ${item.name}`" @click="openDetail(item.id)">查看</button><RouterLink :to="`/settings?employee=${item.id}`" :aria-label="`编辑 ${item.name}`">编辑</RouterLink></div></td>
            </tr>
            <tr v-if="store.loading && !store.employees.length" v-for="index in 6" :key="`loading-${index}`" class="employee-row-loading"><td colspan="9"><span /></td></tr>
          </tbody>
        </table>

        <div v-if="store.error && !store.employees.length" class="employee-table-state"><WifiOff :size="28" /><strong>员工数据加载失败</strong><p>{{ store.error }}</p><button class="button" type="button" @click="store.refresh()">重新加载</button></div>
        <div v-else-if="!store.loading && !filtered.length" class="employee-table-state"><Search :size="28" /><strong>{{ store.employees.length ? '没有匹配员工' : '暂无数字员工' }}</strong><p>{{ store.employees.length ? '调整搜索或筛选条件后重试。' : '创建第一位数字员工后即可开始管理。' }}</p><RouterLink v-if="!store.employees.length" class="button button--primary" to="/settings?create=1">新建数字员工</RouterLink></div>
      </div>

      <footer class="employee-pagination">
        <span>共 {{ filtered.length }} 条，第 {{ page }} / {{ totalPages }} 页</span>
        <nav aria-label="员工列表分页"><button type="button" :disabled="page === 1" aria-label="上一页" @click="page -= 1"><ChevronLeft :size="16" /></button><button v-for="number in visiblePages" :key="number" type="button" :class="{ active: page === number }" :aria-current="page === number ? 'page' : undefined" @click="page = number">{{ number }}</button><button type="button" :disabled="page === totalPages" aria-label="下一页" @click="page += 1"><ChevronRight :size="16" /></button></nav>
      </footer>
    </section>

    <EmployeeDetailDrawer :employee="detailEmployee" :tasks="store.tasks" @close="detailId = ''" />
  </div>
</template>

<script setup lang="ts">
import { ChevronLeft, ChevronRight, Plus, RefreshCw, Search, WifiOff } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeeAvatar from '@/components/employee/EmployeeAvatar.vue'
import EmployeeDetailDrawer from '@/components/employee/EmployeeDetailDrawer.vue'
import { employeeMatches, toEmployeeViewModel, workspaceAreas } from '@/features/employees/presentation'
import { useAstraStore } from '@/stores/astra'
import { environmentLabel, formatTime, platformCopy } from '@/utils/format'

const store = useAstraStore()
const query = ref('')
const status = ref('')
const role = ref('')
const area = ref('')
const enabled = ref('')
const page = ref(1)
const pageSize = 10
const detailId = ref('')
const models = computed(() => store.employees.map((employee) => toEmployeeViewModel(employee, store.tasks)))
const roles = computed(() => [...new Set(store.employees.map((employee) => employee.role))].sort((left, right) => left.localeCompare(right, 'zh-CN')))
const filtered = computed(() => models.value.filter((item) =>
  employeeMatches(item, query.value)
  && (!status.value || item.status === status.value)
  && (!role.value || item.role === role.value)
  && (!area.value || item.areaId === area.value)
  && (!enabled.value || item.employee.enabled === (enabled.value === 'enabled')),
))
const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
const visiblePages = computed(() => {
  const start = Math.max(1, Math.min(page.value - 1, totalPages.value - 4))
  return Array.from({ length: Math.min(5, totalPages.value) }, (_, index) => start + index)
})
const detailEmployee = computed(() => store.employees.find((employee) => employee.id === detailId.value) ?? null)
function openDetail(id: string) { detailId.value = id }
watch([query, status, role, area, enabled], () => { page.value = 1 })
watch(totalPages, (value) => { page.value = Math.min(page.value, value) })
onMounted(() => { if (!store.employees.length && !store.loading) store.refresh() })
</script>

<style scoped>
.employee-page { display: grid; grid-template-rows: auto auto minmax(0,1fr); height: calc(100vh - 60px); min-height: 620px; padding-bottom: 22px; overflow: hidden; }
.employee-page__actions { display: flex; gap: 9px; }.employee-filter { flex-wrap: nowrap; min-width: 0; margin-bottom: 14px; }.employee-filter .search-box { flex: 1; min-width: 230px; }.employee-filter select { min-width: 132px; }.employee-filter .filter-summary { flex: none; }
.employee-table-panel { display: grid; grid-template-rows: minmax(0,1fr) auto; min-width: 0; min-height: 0; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 13px; background: white; box-shadow: var(--astra-shadow-panel); }
.employee-table-scroll { position: relative; min-height: 0; overflow: auto; }.employee-table-panel table { min-width: 1180px; table-layout: fixed; }.employee-table-panel thead { position: sticky; top: 0; z-index: 8; }.employee-table-panel th { height: 47px; padding: 10px 14px; border-bottom: 1px solid var(--astra-border); background: #f7faf8; font-size: 12px; }.employee-table-panel td { height: 67px; padding: 9px 14px; font-size: 13px; }.employee-table-panel tbody tr { cursor: pointer; }.employee-table-panel .employee-col { width: 220px; }.employee-table-panel .task-col { width: 220px; }.employee-table-panel th:nth-child(2) { width: 130px; }.employee-table-panel th:nth-child(3) { width: 150px; }.employee-table-panel th:nth-child(4) { width: 116px; }.employee-table-panel th:nth-child(6) { width: 180px; }.employee-table-panel th:nth-child(7) { width: 130px; }.employee-table-panel th:nth-child(8) { width: 90px; }.employee-table-panel .actions-col { position: sticky; right: 0; z-index: 6; width: 130px; background: white; box-shadow: -8px 0 15px rgba(35,76,59,.04); }.employee-table-panel thead .actions-col { z-index: 10; background: #f7faf8; }
.employee-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }.employee-cell > span,.environment-cell,.task-link { display: grid; min-width: 0; }.employee-cell strong,.employee-cell small,.environment-cell strong,.environment-cell small,.task-link strong,.task-link small,.truncate { display: block; overflow: hidden; max-width: 100%; text-overflow: ellipsis; white-space: nowrap; }.employee-cell strong,.task-link strong,.environment-cell strong { margin: 0; color: var(--astra-text-primary); font-size: 13px; }.employee-cell small,.task-link small,.environment-cell small { color: var(--astra-text-muted); font-size: 11px; }.employee-id { color: #42655b; font-family: ui-monospace,SFMono-Regular,Menlo,monospace; font-size: 11px; }.task-link:hover strong { color: var(--astra-primary); }.enabled-tag { display: inline-flex; align-items: center; gap: 5px; color: #247655; font-size: 12px; }.enabled-tag::before { width: 6px; height: 6px; border-radius: 50%; background: var(--astra-success); content: ''; }.enabled-tag[data-enabled='false'] { color: #7f8e89; }.enabled-tag[data-enabled='false']::before { background: #a4afab; }
.row-actions { display: flex; align-items: center; gap: 3px; }.row-actions button,.row-actions a { display: inline-grid; place-items: center; width: auto; min-width: 46px; height: 30px; padding: 0 8px; color: var(--astra-primary); border: 0; border-radius: 7px; background: transparent; font-size: 12px; cursor: pointer; }.row-actions button:hover,.row-actions a:hover { background: var(--astra-primary-soft); }
.employee-pagination { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 56px; padding: 8px 14px; border-top: 1px solid var(--astra-border); background: #fbfdfc; }.employee-pagination > span { color: var(--astra-text-muted); font-size: 12px; }.employee-pagination nav { display: flex; gap: 5px; }.employee-pagination button { display: grid; place-items: center; min-width: 32px; height: 32px; padding: 0 7px; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 7px; background: white; cursor: pointer; }.employee-pagination button.active { color: white; border-color: var(--astra-primary); background: var(--astra-primary); }.employee-pagination button:disabled { opacity: .35; cursor: default; }
.employee-table-state { position: absolute; inset: 47px 0 0; display: grid; place-items: center; align-content: center; gap: 5px; min-height: 260px; color: var(--astra-text-muted); background: white; text-align: center; }.employee-table-state strong { color: var(--astra-text-primary); }.employee-table-state p { margin: 0 0 7px; font-size: 13px; }.employee-row-loading { cursor: default; }.employee-row-loading td { padding-inline: 18px; }.employee-row-loading span { display: block; width: 100%; height: 20px; border-radius: 7px; background: linear-gradient(90deg,#edf3f0,#f8fbf9,#edf3f0); background-size: 200% 100%; animation: loading-shift 1.2s linear infinite; }
@keyframes loading-shift { to { background-position: -200% 0; } }
@media(max-width:1280px){.employee-filter{flex-wrap:wrap}.employee-filter .search-box{min-width:100%}.employee-filter .filter-summary{margin-left:auto}}
@media(max-width:900px){.employee-page{height:auto;min-height:calc(100vh - 60px);overflow:visible}.employee-table-panel{min-height:620px}.employee-table-scroll{max-height:620px}}
@media(max-width:600px){.employee-page{padding:18px 12px 24px}.employee-page .page-intro{display:grid}.employee-page__actions{width:100%;}.employee-page__actions .button{flex:1}.employee-filter select{flex:1;min-width:calc(50% - 6px)}.employee-pagination{align-items:flex-start;flex-direction:column}.employee-pagination nav{width:100%;justify-content:flex-end}}
</style>
