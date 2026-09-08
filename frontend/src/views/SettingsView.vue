<template>
  <div class="page settings-page" data-testid="settings-page">
    <section class="page-intro compact-intro">
      <div><h2>配置中心</h2><p>管理员工工作范围、Agent 工作环境、任务分类和平台设置。</p></div>
      <span class="config-mode"><LockKeyhole :size="13" /> 远程密码不会回显</span>
    </section>

    <nav class="settings-tabs">
      <button v-for="item in tabs" :key="item.id" :class="{ active: tab === item.id }" @click="switchTab(item.id)"><component :is="item.icon" :size="14" />{{ item.label }}</button>
    </nav>

    <section v-if="tab === 'employees'" class="settings-layout settings-layout--v03">
      <AstraPanel title="员工配置" subtitle="左侧选择员工，右侧维护配置；运行状态由系统维护">
        <template #action><button class="button button--compact button--primary" @click="beginCreate"><Plus :size="13" /> 新建员工</button></template>
        <div class="settings-employee-toolbar">
          <div class="search-box search-box--small"><Search :size="13" /><input v-model="employeeQuery" placeholder="搜索员工" aria-label="搜索员工" /></div>
          <select v-model="employeeEnabledFilter" aria-label="配置状态筛选"><option value="">全部状态</option><option value="true">已启用</option><option value="false">已停用</option></select>
        </div>
        <div class="settings-employee-list">
          <button v-for="employee in filteredEmployees" :key="employee.id" class="settings-employee" :class="{ active: !creating && selectedId === employee.id }" @click="selectEmployee(employee.id)">
            <EmployeeAvatar :employee="employee" size="small" /><div><strong>{{ employeeDisplayName(employee.name) }}</strong><small>{{ employee.role }}</small></div><AstraStatusBadge :status="employee.runtime_state" :label="employee.runtime_status_label" />
          </button>
          <button class="settings-new" @click="beginCreate"><Plus :size="14" /> 新建员工</button>
          <AstraEmptyState v-if="!filteredEmployees.length" class="settings-empty" :icon="SearchX" title="无匹配员工" description="调整搜索或状态筛选后重试。" />
        </div>
      </AstraPanel>

      <EmployeeConfig ref="employeeConfigRef" :employee="selectedEmployee" :creating="creating" :categories="store.categories" @saved="onEmployeeSaved" />
    </section>

    <section v-else-if="tab === 'categories'"><div class="config-tab"><CategoryConfig ref="categoryRef" /></div></section>
    <section v-else-if="tab === 'sources'"><div class="config-tab"><SourceConfig /></div></section>
    <section v-else><SystemSettings ref="systemRef" /></section>
  </div>
</template>

<script setup lang="ts">
import { Bot, Database, FolderTree, LockKeyhole, Plus, Search, SearchX, SlidersHorizontal } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeeAvatar from '@/components/employee/EmployeeAvatar.vue'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName } from '@/utils/format'
import CategoryConfig from '@/views/settings/CategoryConfig.vue'
import EmployeeConfig from '@/views/settings/EmployeeConfig.vue'
import SourceConfig from '@/views/settings/SourceConfig.vue'
import SystemSettings from '@/views/settings/SystemSettings.vue'

const route = useRoute(); const router = useRouter(); const store = useAstraStore()
const tab = ref('employees')
const selectedId = ref('')
const creating = ref(false)
const employeeQuery = ref('')
const employeeEnabledFilter = ref('')
const employeeConfigRef = ref<InstanceType<typeof EmployeeConfig> | null>(null)
const categoryRef = ref<InstanceType<typeof CategoryConfig> | null>(null)
const systemRef = ref<InstanceType<typeof SystemSettings> | null>(null)

const tabs = [
  { id: 'employees', label: '员工配置', icon: Bot },
  { id: 'categories', label: '任务分类', icon: FolderTree },
  { id: 'sources', label: '任务来源', icon: Database },
  { id: 'system', label: '系统设置', icon: SlidersHorizontal },
]

const selectedEmployee = computed(() => store.employees.find((employee) => employee.id === selectedId.value) ?? null)
const filteredEmployees = computed(() => {
  const query = employeeQuery.value.trim().toLowerCase()
  return store.employees.filter((employee) =>
    (!query || `${employee.id}${employee.name}${employee.role}`.toLowerCase().includes(query))
    && (!employeeEnabledFilter.value || String(employee.enabled) === employeeEnabledFilter.value)
  )
})

function isEmployeeDirty(): boolean { return employeeConfigRef.value?.getDirty?.() ?? false }
function guardEmployeeChange() {
  if (isEmployeeDirty() && !window.confirm('有未保存的员工配置修改，确定放弃并切换吗？')) return false
  return true
}

function selectEmployee(id: string) {
  if (!guardEmployeeChange()) return
  creating.value = false; selectedId.value = id
  router.replace({ query: { employee: id } })
}
function beginCreate() {
  if (!guardEmployeeChange()) return
  creating.value = true; selectedId.value = ''
  router.replace({ query: { create: '1' } })
}
function switchTab(next: string) {
  if (next === tab.value) return
  if (isEmployeeDirty() && tab.value === 'employees' && !guardEmployeeChange()) return
  if (tab.value === 'categories' && categoryRef.value?.getDirty() && !window.confirm('有未保存的任务分类修改，确定放弃并切换吗？')) return
  tab.value = next
  router.replace({ query: { ...route.query, tab: next } })
}
function onEmployeeSaved(id: string) {
  creating.value = false; selectedId.value = id
  router.replace({ query: { employee: id } })
}

onMounted(async () => {
  if (!store.employees.length) await store.refresh()
  const tabFromQuery = typeof route.query.tab === 'string' ? route.query.tab : 'employees'
  if (tabs.some((item) => item.id === tabFromQuery)) tab.value = tabFromQuery
  selectedId.value = String(route.query.employee ?? store.employees[0]?.id ?? '')
  if (tab.value === 'employees') {
    if (route.query.create === '1') beginCreate()
    else selectEmployee(String(route.query.employee ?? store.employees[0]?.id ?? ''))
  }
})

onBeforeRouteLeave(() => {
  if (isEmployeeDirty() && tab.value === 'employees') return window.confirm('有未保存的员工配置修改，确定离开吗？')
  if (tab.value === 'categories' && categoryRef.value?.getDirty()) return window.confirm('有未保存的任务分类修改，确定离开吗？')
  return true
})
</script>

<style scoped>
.settings-page { padding-bottom: 96px; }
.settings-employee-toolbar { display: grid; gap: 8px; margin-bottom: 12px; }
.settings-employee-toolbar select { width: 100%; height: 38px; padding: 0 10px; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 8px; outline: none; background: var(--astra-bg-base); }
.settings-employee { width: 100%; }
.settings-empty { margin-top: 6px; }
.config-tab { max-width: 1080px; }
@media (max-width: 900px) { .settings-layout--v03 { grid-template-columns: 1fr; } }
</style>
