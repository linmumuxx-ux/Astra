<template>
  <div class="page employee-page" data-testid="employee-list-page">
    <section class="page-intro compact-intro">
      <div><h2>数字员工</h2><p>集中管理员工职责、运行状态与执行配置</p></div>
      <div class="employee-page__actions"><el-button :loading="store.loading" :disabled="store.loading" @click="store.refresh()"><RefreshCw v-if="!store.loading" :size="16" />刷新</el-button><el-button type="primary" @click="beginCreate"><Plus :size="17" />新建数字员工</el-button></div>
    </section>

    <div class="filter-bar employee-filter">
      <el-input v-model="query" class="employee-search" clearable aria-label="搜索员工" placeholder="搜索员工名称 / 编号 / 职责 / 任务"><template #prefix><Search :size="17" /></template></el-input>
      <el-select v-model="status" aria-label="员工状态"><el-option label="状态：全部" value="" /><el-option label="工作中" value="WORKING" /><el-option label="空闲" value="IDLE" /><el-option label="需要人工处理" value="WAIT_HUMAN" /><el-option label="已暂停" value="PAUSED" /><el-option label="异常" value="ERROR" /><el-option label="离线" value="OFFLINE" /></el-select>
      <el-select v-model="role" aria-label="员工职责"><el-option label="职责：全部" value="" /><el-option v-for="item in roles" :key="item" :label="item" :value="item" /></el-select>
      <el-select v-model="area" aria-label="所属区域"><el-option label="区域：全部" value="" /><el-option v-for="item in workspaceAreas" :key="item.id" :label="item.name" :value="item.id" /></el-select>
      <el-select v-model="enabled" aria-label="启用状态"><el-option label="启用：全部" value="" /><el-option label="已启用" value="enabled" /><el-option label="已停用" value="disabled" /></el-select>
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
              <td><el-tag :type="item.employee.enabled ? 'success' : 'info'" effect="light">{{ item.employee.enabled ? '已启用' : '已停用' }}</el-tag></td>
              <td class="actions-col" @click.stop><div class="row-actions"><el-button text :aria-label="`查看 ${item.name}`" @click="openDetail(item.id)">查看</el-button><el-button text :aria-label="`编辑 ${item.name}`" @click="beginEdit(item.employee)">编辑</el-button><el-button text :loading="busyId === item.id" :aria-label="`${item.employee.enabled ? '停用' : '启用'} ${item.name}`" :disabled="busyId === item.id" @click="toggleEnabled(item.employee)">{{ item.employee.enabled ? '停用' : '启用' }}</el-button><el-button type="danger" text :aria-label="`删除 ${item.name}`" :disabled="busyId === item.id" @click="removeEmployee(item.employee)">删除</el-button></div></td>
            </tr>
            <tr v-if="store.loading && !store.employees.length" v-for="index in 6" :key="`loading-${index}`" class="employee-row-loading"><td colspan="9"><span /></td></tr>
          </tbody>
        </table>

        <div v-if="store.error && !store.employees.length" class="employee-table-state"><WifiOff :size="28" /><strong>员工数据加载失败</strong><p>{{ store.error }}</p><el-button @click="store.refresh()">重新加载</el-button></div>
        <div v-else-if="!store.loading && !filtered.length" class="employee-table-state"><Search :size="28" /><strong>{{ store.employees.length ? '没有匹配员工' : '暂无数字员工' }}</strong><p>{{ store.employees.length ? '调整搜索或筛选条件后重试。' : '创建第一位数字员工后即可开始管理。' }}</p><el-button v-if="!store.employees.length" type="primary" @click="beginCreate">新建数字员工</el-button></div>
      </div>

      <footer class="employee-pagination">
        <el-pagination v-model:current-page="page" :page-size="pageSize" layout="total, prev, pager, next" :total="filtered.length" />
      </footer>
    </section>

    <EmployeeDetailDrawer :employee="detailEmployee" :tasks="store.tasks" @close="detailId = ''" @edit="beginEdit(detailEmployee)" />

    <EmployeeConfigModal :open="modalOpen" :employee="modalEmployee" :creating="modalCreating" :categories="store.categories" @close="closeModal" @saved="onModalSaved" />
  </div>
</template>

<script setup lang="ts">
import { Plus, RefreshCw, Search, WifiOff } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@/api/client'
import type { Employee } from '@/api/types'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeeAvatar from '@/components/employee/EmployeeAvatar.vue'
import EmployeeConfigModal from '@/components/employee/EmployeeConfigModal.vue'
import EmployeeDetailDrawer from '@/components/employee/EmployeeDetailDrawer.vue'
import { confirmDialog } from '@/composables/useConfirm'
import { notify } from '@/composables/useToast'
import { employeeMatches, toEmployeeViewModel, workspaceAreas } from '@/features/employees/presentation'
import { useAstraStore } from '@/stores/astra'
import { environmentLabel, formatTime, platformCopy } from '@/utils/format'

const store = useAstraStore()
const route = useRoute()
const query = ref('')
const status = ref(typeof route.query.status === 'string' ? route.query.status : '')
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
const detailEmployee = computed(() => store.employees.find((employee) => employee.id === detailId.value) ?? null)
const modalOpen = ref(false)
const modalCreating = ref(false)
const modalEmployee = ref<Employee | null>(null)
const busyId = ref('')
function openDetail(id: string) { detailId.value = id }
function beginCreate() { modalEmployee.value = null; modalCreating.value = true; modalOpen.value = true }
function beginEdit(employee: Employee | null) { if (!employee) return; detailId.value = ''; modalEmployee.value = employee; modalCreating.value = false; modalOpen.value = true }
function closeModal() { modalOpen.value = false; modalEmployee.value = null }
async function onModalSaved() { await store.refresh(); notify(modalCreating.value ? '数字员工已创建' : '数字员工已更新') }
async function toggleEnabled(employee: Employee) {
  busyId.value = employee.id
  try { await api.updateEmployee(employee.id, { enabled: !employee.enabled }); await store.refresh(); notify(employee.enabled ? '员工已停用' : '员工已启用') }
  catch (reason) { notify(reason instanceof Error ? reason.message : '操作失败', 'error') }
  finally { busyId.value = '' }
}
async function removeEmployee(employee: Employee) {
  const confirmed = await confirmDialog({ title: '删除数字员工', message: `确认删除「${employee.name}」？删除后无法恢复。`, confirmLabel: '删除员工', danger: true })
  if (!confirmed) return
  busyId.value = employee.id
  try { await api.deleteEmployee(employee.id); if (detailId.value === employee.id) detailId.value = ''; await store.refresh(); notify('数字员工已删除') }
  catch (reason) { notify(reason instanceof Error ? reason.message : '删除失败', 'error') }
  finally { busyId.value = '' }
}
watch([query, status, role, area, enabled], () => { page.value = 1 })
watch(totalPages, (value) => { page.value = Math.min(page.value, value) })
onMounted(async () => {
  const editId = typeof route.query.edit === 'string' ? route.query.edit : ''
  const create = route.query.create === '1'
  // 深链打开弹框时确保员工数据已就绪，避免与全局刷新竞争。
  if (!store.employees.length && (editId || create || !store.loading)) await store.refresh()
  if (editId) beginEdit(store.employees.find((item) => item.id === editId) ?? null)
  else if (create) beginCreate()
})
</script>

<style scoped>
.employee-page { display: grid; grid-template-rows: auto auto minmax(0,1fr); height: calc(100vh - 60px); min-height: 620px; padding-bottom: 22px; overflow: hidden; }
.employee-page__actions { display: flex; gap: 9px; }.employee-filter { flex-wrap: nowrap; min-width: 0; margin-bottom: 14px; }.employee-filter .employee-search { flex: 1; min-width: 230px; }.employee-filter :deep(.el-select) { min-width: 132px; width: 150px; }.employee-filter .filter-summary { flex: none; }
.employee-table-panel { display: grid; grid-template-rows: minmax(0,1fr) auto; min-width: 0; min-height: 0; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 13px; background: white; box-shadow: var(--astra-shadow-panel); }
.employee-table-scroll { position: relative; min-height: 0; overflow: auto; }.employee-table-panel table { min-width: 1260px; table-layout: fixed; }.employee-table-panel thead { position: sticky; top: 0; z-index: 8; }.employee-table-panel th { height: 47px; padding: 10px 14px; border-bottom: 1px solid var(--astra-border); background: #f7faf8; font-size: var(--astra-font-control); }.employee-table-panel td { height: 67px; padding: 9px 14px; font-size: var(--astra-font-body); }.employee-table-panel tbody tr { cursor: pointer; }.employee-table-panel .employee-col { width: 220px; }.employee-table-panel .task-col { width: 220px; }.employee-table-panel th:nth-child(2) { width: 130px; }.employee-table-panel th:nth-child(3) { width: 150px; }.employee-table-panel th:nth-child(4) { width: 116px; }.employee-table-panel th:nth-child(6) { width: 180px; }.employee-table-panel th:nth-child(7) { width: 130px; }.employee-table-panel th:nth-child(8) { width: 90px; }.employee-table-panel .actions-col { position: sticky; right: 0; z-index: 6; width: 214px; background: white; box-shadow: -8px 0 15px rgba(35,76,59,.04); }.employee-table-panel thead .actions-col { z-index: 10; background: #f7faf8; }
.employee-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }.employee-cell > span,.environment-cell,.task-link { display: grid; min-width: 0; }.employee-cell strong,.employee-cell small,.environment-cell strong,.environment-cell small,.task-link strong,.task-link small,.truncate { display: block; overflow: hidden; max-width: 100%; text-overflow: ellipsis; white-space: nowrap; }.employee-cell strong,.task-link strong,.environment-cell strong { margin: 0; color: var(--astra-text-primary); font-size: var(--astra-font-label); }.employee-cell small,.task-link small,.environment-cell small { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }.employee-id { color: #42655b; font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }.task-link:hover strong { color: var(--astra-primary); }.row-actions { display: flex; align-items: center; gap: 3px; }
.row-actions :deep(.el-button) { margin-left: 0; min-width: 42px; padding-inline: 6px; }

.employee-pagination { display: flex; align-items: center; justify-content: flex-end; min-height: 56px; padding: 8px 14px; border-top: 1px solid var(--astra-border); background: #fbfdfc; }
.employee-table-state { position: absolute; inset: 47px 0 0; display: grid; place-items: center; align-content: center; gap: 5px; min-height: 260px; color: var(--astra-text-muted); background: white; text-align: center; }.employee-table-state strong { color: var(--astra-text-primary); }.employee-table-state p { margin: 0 0 7px; font-size: var(--astra-font-label); }.employee-row-loading { cursor: default; }.employee-row-loading td { padding-inline: 18px; }.employee-row-loading span { display: block; width: 100%; height: 20px; border-radius: 7px; background: linear-gradient(90deg,#edf3f0,#f8fbf9,#edf3f0); background-size: 200% 100%; animation: loading-shift 1.2s linear infinite; }
@keyframes loading-shift { to { background-position: -200% 0; } }
@media(max-width:1280px){.employee-filter{flex-wrap:wrap}.employee-filter .search-box{min-width:100%}.employee-filter .filter-summary{margin-left:auto}}
@media(max-width:900px){.employee-page{height:auto;min-height:calc(100vh - 60px);overflow:visible}.employee-table-panel{min-height:620px}.employee-table-scroll{max-height:620px}}
@media(max-width:600px){.employee-page{padding:18px 12px 24px}.employee-page .page-intro{display:grid}.employee-page__actions{width:100%;}.employee-page__actions .button{flex:1}.employee-filter select{flex:1;min-width:calc(50% - 6px)}.employee-pagination{align-items:flex-start;flex-direction:column}.employee-pagination nav{width:100%;justify-content:flex-end}}
</style>
