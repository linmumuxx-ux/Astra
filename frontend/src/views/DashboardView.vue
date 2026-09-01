<template>
  <div class="dashboard-page" data-testid="dashboard-page">
    <h2 class="sr-only">数字员工工作空间</h2>
    <section class="workspace-layout">
      <div class="workspace-main">
        <div class="workspace-controls" aria-label="工作空间筛选">
          <label class="workspace-search">
            <Search :size="15" />
            <input v-model="query" aria-label="搜索员工名称或编号" placeholder="搜索员工" />
            <button v-if="query" type="button" aria-label="清空员工搜索" @click="query = ''"><X :size="13" /></button>
          </label>
          <select v-model="statusFilter" aria-label="筛选员工状态">
            <option value="">全部状态</option>
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <select v-model="areaFilter" aria-label="筛选工作区域">
            <option value="">全部区域</option>
            <option v-for="area in workspaceAreas" :key="area.id" :value="area.id">{{ area.name }}</option>
          </select>
          <button
            class="workspace-help-filter"
            :class="{ active: statusFilter === 'WAIT_HUMAN' }"
            type="button"
            :aria-label="`筛选需要人工处理的员工，当前 ${helpCount} 人`"
            @click="toggleHelpFilter"
          ><CircleAlert :size="15" /><span>待处理</span><strong>{{ helpCount }}</strong></button>
        </div>

        <WorkspaceScene
          :employees="filteredEmployees"
          :tasks="store.tasks"
          :selected-id="selectedId"
          :empty-title="store.employees.length ? '没有匹配的数字员工' : '工作空间暂无数字员工'"
          :empty-description="store.employees.length ? '调整搜索或筛选条件后重试。' : '创建员工后，他们会进入对应的办公区域。'"
          :show-create="!store.employees.length"
          @select="selectedId = $event"
          @detail="openDetail"
        />
        <RealtimeActivityBar :events="store.events" :employees="store.employees" @select="selectFromActivity" />
      </div>
      <NotificationPanel :events="store.events" :tasks="store.tasks" />
    </section>

    <EmployeeDetailDrawer :employee="detailEmployee" :tasks="store.tasks" @close="detailId = ''" />
  </div>
</template>

<script setup lang="ts">
import { CircleAlert, Search, X } from 'lucide-vue-next'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import EmployeeDetailDrawer from '@/components/employee/EmployeeDetailDrawer.vue'
import NotificationPanel from '@/components/workspace/NotificationPanel.vue'
import RealtimeActivityBar from '@/components/workspace/RealtimeActivityBar.vue'
import WorkspaceScene from '@/components/workspace/WorkspaceScene.vue'
import { employeeMatches, toEmployeeViewModel, workspaceAreas } from '@/features/employees/presentation'
import { useAstraStore } from '@/stores/astra'

const store = useAstraStore()
const query = ref('')
const statusFilter = ref('')
const areaFilter = ref('')
const selectedId = ref('')
const detailId = ref('')
const statusOptions = [
  { value: 'WORKING', label: '工作中' },
  { value: 'IDLE', label: '空闲' },
  { value: 'WAIT_HUMAN', label: '需要人工处理' },
  { value: 'PAUSED', label: '已暂停' },
  { value: 'ERROR', label: '异常' },
  { value: 'OFFLINE', label: '离线' },
]
const allModels = computed(() => store.employees.map((employee) => toEmployeeViewModel(employee, store.tasks)))
const filteredModels = computed(() => allModels.value.filter((employee) =>
  employeeMatches(employee, query.value)
  && (!statusFilter.value || employee.status === statusFilter.value)
  && (!areaFilter.value || employee.areaId === areaFilter.value),
))
const filteredEmployees = computed(() => filteredModels.value.map((employee) => employee.employee))
const detailEmployee = computed(() => store.employees.find((employee) => employee.id === detailId.value) ?? null)
const helpCount = computed(() => allModels.value.filter((employee) => employee.needHelp).length)
function toggleHelpFilter() { statusFilter.value = statusFilter.value === 'WAIT_HUMAN' ? '' : 'WAIT_HUMAN' }
function openDetail(id: string) { detailId.value = id }
async function selectFromActivity(id: string) {
  query.value = ''
  statusFilter.value = ''
  areaFilter.value = ''
  await nextTick()
  selectedId.value = id
}
watch(query, (value) => {
  if (!value.trim()) return
  selectedId.value = filteredModels.value[0]?.id ?? ''
})
watch(filteredModels, (employees) => {
  if (selectedId.value && !employees.some((employee) => employee.id === selectedId.value)) selectedId.value = ''
})
onMounted(() => { if (!store.employees.length && !store.loading) store.refresh() })
</script>

<style scoped>
.dashboard-page { height: calc(100vh - 60px); min-height: 620px; padding: 14px 18px 16px; overflow: hidden; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
.workspace-layout { position: relative; width: 100%; height: 100%; min-width: 0; min-height: 0; }
.workspace-main { position: absolute; inset: 0; min-width: 0; min-height: 0; }
.workspace-layout :deep(.notification-panel) { position: absolute; z-index: 205; top: 12px; right: 12px; width: 258px; height: min(470px,calc(100% - 132px)); background: rgba(255,255,255,.95); backdrop-filter: blur(10px); }
.workspace-main :deep(.activity-bar) { right: 282px; }
.workspace-controls { position: absolute; z-index: 210; top: 12px; right: 282px; display: flex; align-items: center; gap: 6px; max-width: calc(100% - 306px); padding: 5px; border: 1px solid rgba(201,219,211,.88); border-radius: 12px; background: rgba(255,255,255,.91); box-shadow: 0 8px 20px rgba(32,72,57,.10); backdrop-filter: blur(10px); }
.workspace-search { display: flex; align-items: center; gap: 6px; width: 146px; height: 32px; padding: 0 8px; color: var(--astra-text-muted); border-radius: 8px; background: #f5f9f7; }
.workspace-search input { min-width: 0; width: 100%; padding: 0; color: var(--astra-text-primary); border: 0; outline: 0; background: transparent; font-size: 11px; }
.workspace-search button { display: grid; place-items: center; width: 22px; height: 22px; padding: 0; color: var(--astra-text-muted); border: 0; border-radius: 6px; background: transparent; cursor: pointer; }
.workspace-controls select { width: 105px; height: 32px; padding: 0 25px 0 8px; color: var(--astra-text-secondary); border: 0; border-radius: 8px; outline: 0; background: #f5f9f7; font-size: 11px; }
.workspace-help-filter { display: inline-flex; align-items: center; gap: 4px; height: 32px; padding: 0 8px; color: #9a5e18; border: 0; border-radius: 8px; background: #fff7eb; font-size: 10px; cursor: pointer; white-space: nowrap; }.workspace-help-filter.active { box-shadow: inset 0 0 0 1px #dfb577; background: #ffefd9; }.workspace-help-filter strong { font-size: 11px; }
@media(max-width:1360px){.workspace-layout :deep(.notification-panel){width:226px}.workspace-main :deep(.activity-bar){right:250px}.workspace-controls{right:250px;max-width:calc(100% - 274px)}.workspace-controls select{width:92px}.workspace-search{width:124px}.workspace-help-filter span{display:none}}
@media(max-height:800px){.dashboard-page{padding:9px 12px 11px}.workspace-layout :deep(.notification-panel){top:8px;right:8px;height:min(430px,calc(100% - 124px))}.workspace-main :deep(.activity-bar){right:278px}.workspace-controls{top:8px;right:278px;max-width:calc(100% - 294px)}.workspace-search{width:116px}}
@media(max-width:1360px) and (max-height:800px){.workspace-main :deep(.activity-bar){right:246px}.workspace-controls{right:246px;max-width:calc(100% - 262px)}}
@media(max-width:900px){.dashboard-page{height:auto;min-height:calc(100vh - 60px);overflow:visible}.workspace-layout{display:grid;grid-template-rows:minmax(660px,1fr) 340px;gap:10px}.workspace-main{position:relative;min-height:660px}.workspace-layout :deep(.notification-panel){position:relative;inset:auto;width:auto;height:auto}.workspace-main :deep(.activity-bar){right:14px}.workspace-controls{right:12px;max-width:calc(100% - 24px)}}
@media(max-width:600px){.dashboard-page{padding:9px}.workspace-controls{right:6px;left:6px;max-width:none;overflow-x:auto}.workspace-controls select{flex:none}.workspace-help-filter{flex:none}}
</style>
