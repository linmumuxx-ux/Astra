<template>
  <component
    :is="embedded ? 'div' : AstraPanel"
    v-bind="embedded ? {} : { title: creating ? '创建数字员工' : `${employeeDisplayName(employee?.name)} 配置`, subtitle: '配置描述员工职责与工作环境；运行状态由系统状态机维护。' }"
  >
    <el-tabs v-model="employeeTab" class="employee-config-tabs">
      <el-tab-pane v-for="item in tabs" :key="item.id" :label="item.label" :name="item.id" />
    </el-tabs>

    <form class="config-form config-form--editable" @submit.prevent="save">
      <div v-if="employeeTab === 'basic'">
        <div class="form-grid">
          <label class="field-id">
            <span>员工 ID</span>
            <IdDisplay v-if="!creating" :value="employee?.id ?? ''" :max-width="200" />
            <el-input v-else v-model="form.id" required placeholder="employee-04" />
          </label>
          <label>员工名称<el-input v-model="form.name" required placeholder="员工-04" /></label>
        </div>
        <div class="form-grid">
          <label>岗位<el-input v-model="form.role" required placeholder="测试平台开发" /></label>
          <FormField label="默认办公区域" help="无特定任务场景时，员工会出现在这个区域。" v-slot="{ id }"><el-select :id="id" v-model="form.default_work_area"><el-option v-for="area in workspaceAreas" :key="area.id" :label="area.name" :value="area.id" /></el-select></FormField>
        </div>
        <label>说明<el-input v-model="form.description" type="textarea" :rows="4" resize="vertical" placeholder="说明该员工的工作职责与边界" /></label>

        <fieldset class="config-fieldset">
          <legend>配置状态</legend>
          <FormField class="check-row" label="启用员工" help="停用后不再自动分配新任务" inline v-slot="{ id }"><el-switch :id="id" v-model="form.enabled" /></FormField>
        </fieldset>

        <div v-if="!creating" class="runtime-card">
          <div class="runtime-card__head"><FormLabel label="运行状态" help="由系统状态机维护（空闲 / 执行中 / 等待输入 / 异常），此表单不可直接修改。" /><span>{{ runtimeMeta.label }}</span></div>
          <div class="runtime-card__action">
            <span>{{ paused ? '员工已暂停接单，不会领取新任务。' : '员工可正常领取匹配任务。' }}</span>
            <el-button :type="paused ? 'primary' : 'warning'" :loading="statusChanging" :disabled="statusChanging || (!paused && currentTaskCount > 0)" @click="toggleRuntime">
              {{ statusChanging ? '处理中…' : paused ? '继续接单' : '暂停接单' }}
            </el-button>
          </div>
        </div>
      </div>

      <div v-else-if="employeeTab === 'scope'" class="scope-config">
        <fieldset class="config-fieldset">
          <legend>支持任务类型</legend>
          <FormField class="check-row" label="问题" help="缺陷、故障、异常或已有能力失效" inline v-slot="{ id }"><el-switch :id="id" :model-value="hasType('ISSUE')" @update:model-value="toggleType('ISSUE')" /></FormField>
          <FormField class="check-row" label="需求" help="新功能、能力增强、改造、优化或重构" inline v-slot="{ id }"><el-switch :id="id" :model-value="hasType('REQUIREMENT')" @update:model-value="toggleType('REQUIREMENT')" /></FormField>
        </fieldset>
        <fieldset class="config-fieldset">
          <legend>支持任务分类</legend>
          <FormField v-for="category in categories" :key="category.id" class="check-row" :label="category.name" :help="category.description" inline v-slot="{ id }"><el-switch :id="id" :model-value="hasCategory(category.id)" @update:model-value="toggleCategory(category.id)" /></FormField>
        </fieldset>
      </div>

      <div v-else-if="employeeTab === 'environment'" data-testid="environment-form">
        <FormLabel label="工作环境类型" help="本地：NEXUS 所在主机。Linux 远程：SSH 隧道连接 Server。" />
        <div class="environment-mode">
          <button type="button" :class="{ active: form.environment.mode === 'LOCAL' }" @click="setMode('LOCAL')"><Laptop :size="20" /><strong>本地</strong></button>
          <button type="button" :class="{ active: form.environment.mode === 'LINUX_REMOTE' }" @click="setMode('LINUX_REMOTE')"><Server :size="20" /><strong>Linux 远程</strong></button>
        </div>
        <div class="form-grid"><label>环境名称<el-input v-model="form.environment.name" required /></label><FormField label="Agent 可执行文件" help="正式 Runtime 由该 OpenCode 启动 Server；显式 fallback 时才使用 CLI。" v-slot="{ id }"><el-input :id="id" v-model="form.environment.opencode_path" required :placeholder="form.environment.mode === 'LOCAL' ? 'opencode 或 C:\\Program Files\\OpenCode\\opencode.exe' : '/usr/local/bin/opencode'" /></FormField></div>
        <div class="form-grid"><FormField label="Agent 模型" help="留空时使用 Agent 自身或平台默认模型。" v-slot="{ id }"><el-input :id="id" v-model="form.environment.model_name" placeholder="opencode/glm-5.1" /></FormField><label>环境说明<el-input v-model="form.environment.description" placeholder="例如：测试平台开发环境" /></label></div>
        <FormField label="工作空间" help="支持 Windows 盘符、空格和中文目录；该路径属于员工，会在不同任务间长期复用。" v-slot="{ id }"><el-input :id="id" v-model="form.environment.workspace_root" required :placeholder="form.environment.mode === 'LOCAL' ? 'D:\\code\\nr_test_system' : '/home/nexus/project'" /></FormField>
          <FormField label="OpenCode Server Port" help="人工配置固定端口，同一主机的员工须使用不同端口，避开平台与助手端口。仅监听 127.0.0.1；远程通过 SSH 隧道访问。" v-slot="{ id }"><el-input-number :id="id" v-model="form.environment.opencode_server_port" :min="1" :max="65535" controls-position="right" /></FormField>
        <template v-if="form.environment.mode === 'LINUX_REMOTE'">
          <div class="form-grid"><label>SSH Host<el-input v-model="form.environment.host" required placeholder="10.0.0.12" /></label><label>SSH Port<el-input-number v-model="form.environment.port" :min="1" :max="65535" controls-position="right" /></label></div>
          <div class="form-grid"><label>Username<el-input v-model="form.environment.username" required placeholder="nexus" /></label><FormField label="SSH 密码" help="SSH 密码保存在部署数据库中且接口不回显；已配置时留空保持不变。" v-slot="{ id }"><el-input :id="id" v-model="form.environment.ssh_password" :required="creating || !employee?.execution_environment?.has_ssh_password" type="password" show-password autocomplete="new-password" :placeholder="employee?.execution_environment?.has_ssh_password ? '已配置，留空保持不变' : '请输入 SSH 密码'" /></FormField></div>
        </template>

        <div class="env-connection" v-if="!creating">
          <div class="env-connection__row"><strong>工作环境连接</strong><AstraStatusBadge :status="selectedEnvironmentStatus" /></div>
          <div class="env-connection__grid" v-if="selectedEnvironment">
            <div><dt>Server 地址</dt><dd>{{ serverAddress }}</dd></div>
            <div><dt>工作目录</dt><dd>{{ selectedEnvironment.workspace_root || '—' }}</dd></div>
            <div><dt>模型</dt><dd>{{ selectedEnvironment.model_name || '—' }}</dd></div>
            <div><dt>最近检测</dt><dd>{{ formatTime(selectedEnvironment.last_checked_at) }}</dd></div>
          </div>
          <el-button :loading="testing" :disabled="testing" @click="testConnection"><RefreshCw v-if="!testing" :size="13" />{{ testing ? '检测中' : '测试连接' }}</el-button>
        </div>
        <div v-if="checks.length" class="environment-checks"><article v-for="check in checks" :key="check.name"><CheckCircle2 v-if="check.passed" :size="14" /><CircleX v-else :size="14" /><div><strong>{{ check.name }}</strong><small>{{ check.detail }}</small></div></article></div>
      </div>

      <div v-else class="config-fieldset policy-block">
        <div class="policy-grid">
          <FormField class="check-row" label="自动领取任务" help="空闲时可以领取匹配的新任务。每位员工同时只处理一项任务。" inline v-slot="{ id }"><el-switch :id="id" v-model="form.auto_claim" /></FormField>
          <FormField class="check-row" label="允许自主执行" help="领取后自动启动任务独立执行会话" inline v-slot="{ id }"><el-switch :id="id" v-model="form.auto_execute" /></FormField>
        </div>
      </div>

      <div v-if="message" class="form-message" :data-error="messageIsError">{{ message }}</div>
    </form>

    <StickyActionBar v-if="isDirty && !embedded" :dirty="isDirty" :saving="saving" :save-label="creating ? '创建员工' : '保存配置'" @save="save" @cancel="reset" />
  </component>
</template>

<script setup lang="ts">
import FormField from '@/components/forms/FormField.vue'
import FormLabel from '@/components/forms/FormLabel.vue'
import { CheckCircle2, CircleX, Laptop, RefreshCw, Server } from 'lucide-vue-next'
import { computed, reactive, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { Employee, TaskCategory, TaskType } from '@/api/types'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import IdDisplay from '@/components/astra/IdDisplay.vue'
import StickyActionBar from '@/components/astra/StickyActionBar.vue'
import { workspaceAreas, type WorkspaceAreaId } from '@/features/workspace/sceneLayout'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatTime } from '@/utils/format'

const props = defineProps<{ employee: Employee | null; creating: boolean; categories: TaskCategory[]; embedded?: boolean }>()
const emit = defineEmits<{ (e: 'saved', id: string, environmentOk?: boolean): void }>()
const store = useAstraStore()

const tabs = [{ id: 'basic', label: '基本信息' }, { id: 'scope', label: '工作范围' }, { id: 'environment', label: '工作环境' }, { id: 'policy', label: '工作策略' }]
const employeeTab = ref('basic')
const saving = ref(false)
const testing = ref(false)
const statusChanging = ref(false)
const message = ref('')
const messageIsError = ref(false)
const checks = ref<Array<{ name: string; passed: boolean; detail: string }>>([])
const originalSnapshot = ref('')

const emptyEnvironment = () => ({ mode: 'LOCAL' as 'LOCAL' | 'LINUX_REMOTE', name: '本地 Agent 工作环境', description: '', host: '', port: 22, username: '', ssh_password: '', opencode_server_port: 4096, opencode_path: 'opencode', model_name: '', workspace_root: '', labels: [] as string[] })
const form = reactive({ id: '', name: '', role: '', description: '', default_work_area: 'development' as WorkspaceAreaId, task_types: ['ISSUE', 'REQUIREMENT'] as TaskType[], category_ids: [] as string[], enabled: true, auto_claim: true, auto_execute: true, environment: emptyEnvironment() })

const selectedEnvironment = computed(() => props.employee?.execution_environment ?? null)
const selectedEnvironmentStatus = computed(() => selectedEnvironment.value?.status ?? 'UNKNOWN')
const currentTaskCount = computed(() => props.employee?.current_task_count ?? 0)
const paused = computed(() => props.employee?.status === 'PAUSED')
const serverAddress = computed(() => {
  const env = selectedEnvironment.value
  if (!env) return '—'
  return env.mode === 'LINUX_REMOTE' ? `${env.host ?? ''} → 127.0.0.1:${env.opencode_server_port}（SSH）` : `127.0.0.1:${env.opencode_server_port}`
})

const EMPLOYEE_RUNTIME: Record<string, { label: string; tone: string }> = {
  IDLE: { label: '空闲', tone: 'neutral' },
  WORKING: { label: '执行中', tone: 'info' },
  WAIT_HUMAN: { label: '等待输入', tone: 'warning' },
  ERROR: { label: '异常', tone: 'danger' },
  PAUSED: { label: '已暂停接单', tone: 'warning' },
  OFFLINE: { label: '离线', tone: 'neutral' },
}
const runtimeMeta = computed(() => EMPLOYEE_RUNTIME[props.employee?.status ?? ''] ?? { label: '未知', tone: 'neutral' })

function fill(employee?: Employee) {
  const environment = employee?.execution_environment
  Object.assign(form, {
    id: employee?.id ?? '', name: employee?.name ?? '', role: employee?.role ?? '', description: employee?.description ?? '',
    default_work_area: employee?.default_work_area ?? 'development',
    task_types: [...(employee?.task_types ?? ['ISSUE', 'REQUIREMENT'])],
    category_ids: [...(employee?.category_ids ?? props.categories.filter((item) => item.enabled).map((item) => item.id))],
    enabled: employee?.enabled ?? true, auto_claim: employee?.auto_claim ?? true, auto_execute: employee?.auto_execute ?? true,
    environment: environment ? { mode: environment.mode, name: environment.name, description: environment.description, host: environment.host ?? '', port: environment.port, username: environment.username ?? '', ssh_password: '', opencode_server_port: environment.opencode_server_port ?? 4096, opencode_path: environment.opencode_path, model_name: environment.model_name ?? '', workspace_root: environment.workspace_root, labels: [...environment.labels] } : emptyEnvironment(),
  })
  checks.value = []; message.value = ''; employeeTab.value = 'basic'
  originalSnapshot.value = snapshot()
}

function snapshot(): string {
  return JSON.stringify({
    id: form.id, name: form.name, role: form.role, description: form.description, default_work_area: form.default_work_area,
    task_types: form.task_types, category_ids: form.category_ids, enabled: form.enabled, auto_claim: form.auto_claim, auto_execute: form.auto_execute,
    environment: { mode: form.environment.mode, name: form.environment.name, description: form.environment.description, host: form.environment.host ?? null, port: Number(form.environment.port), username: form.environment.username ?? null, opencode_server_port: Number(form.environment.opencode_server_port ?? 4096), opencode_path: form.environment.opencode_path, model_name: form.environment.model_name ?? null, workspace_root: form.environment.workspace_root, ssh_password: form.environment.ssh_password || null },
  })
}
const isDirty = computed(() => snapshot() !== originalSnapshot.value)

watch([() => props.employee?.id, () => props.creating], () => { fill(props.employee ?? undefined) }, { immediate: true })

function setMode(mode: 'LOCAL' | 'LINUX_REMOTE') { form.environment.mode = mode }
function hasType(value: TaskType) { return form.task_types.includes(value) }
function toggleType(value: TaskType) { form.task_types = form.task_types.includes(value) ? form.task_types.filter((item) => item !== value) : [...form.task_types, value] }
function hasCategory(id: string) { return form.category_ids.includes(id) }
function toggleCategory(id: string) { form.category_ids = form.category_ids.includes(id) ? form.category_ids.filter((item) => item !== id) : [...form.category_ids, id] }

function environmentPayload() {
  return { ...form.environment, host: form.environment.mode === 'LOCAL' ? null : form.environment.host || null, username: form.environment.mode === 'LOCAL' ? null : form.environment.username || null, ssh_password: form.environment.mode === 'LINUX_REMOTE' ? form.environment.ssh_password || null : null, model_name: form.environment.model_name || null }
}
function employeePayload() {
  return {
    name: form.name.trim(),
    role: form.role.trim(),
    description: form.description.trim(),
    default_work_area: form.default_work_area,
    task_types: form.task_types,
    category_ids: form.category_ids,
    enabled: form.enabled,
    auto_claim: form.auto_claim,
    auto_execute: form.auto_execute,
  }
}
function normalizedEnvironment(value: ReturnType<typeof environmentPayload> | Employee['execution_environment']) {
  return value ? { mode: value.mode, name: value.name, description: value.description ?? '', host: value.host ?? null, port: Number(value.port), username: value.username ?? null, opencode_server_port: Number(value.opencode_server_port ?? 4096), opencode_path: value.opencode_path, model_name: value.model_name ?? null, workspace_root: value.workspace_root, labels: [...(value.labels ?? [])] } : null
}
function environmentChanged() {
  return Boolean(form.environment.ssh_password) || JSON.stringify(normalizedEnvironment(environmentPayload())) !== JSON.stringify(normalizedEnvironment(props.employee?.execution_environment ?? null))
}

async function save() {
  if (!form.task_types.length || !form.category_ids.length) { message.value = '工作范围至少需要一种任务类型和一个任务分类'; messageIsError.value = true; return }
  saving.value = true; message.value = ''; messageIsError.value = false
  try {
    let employeeId = props.employee?.id ?? ''
    let shouldCheckEnvironment = false
    if (props.creating) {
      const created = await api.createEmployee({ id: form.id, ...employeePayload(), execution_environment: environmentPayload() })
      employeeId = created.id; shouldCheckEnvironment = true
    } else {
      await api.updateEmployee(employeeId, employeePayload())
      if (environmentChanged()) { await api.updateEnvironment(employeeId, environmentPayload()); shouldCheckEnvironment = true }
    }
    const checkResult = shouldCheckEnvironment ? await api.testEnvironment(employeeId) : null
    const environmentOk = checkResult ? checkResult.status === 'AVAILABLE' : true
    await store.refresh()
    originalSnapshot.value = snapshot()
    if (checkResult) {
      checks.value = checkResult.checks; messageIsError.value = !environmentOk
      message.value = environmentOk ? '配置已保存，工作环境检测正常。' : '配置已保存，但工作环境检测异常，请查看检查项。'
    } else {
      message.value = '配置已保存，工作环境状态保持不变。'
    }
    emit('saved', employeeId, environmentOk)
  } catch (error) {
    messageIsError.value = true; message.value = error instanceof Error ? error.message : '保存失败'
  } finally { saving.value = false }
}

async function testConnection() {
  if (!props.employee) return
  testing.value = true
  try {
    const result = await api.testEnvironment(props.employee.id)
    checks.value = result.checks; message.value = result.status === 'AVAILABLE' ? '环境正常，可以处理新任务。' : '环境异常，请根据检查项处理。'; messageIsError.value = result.status !== 'AVAILABLE'
    await store.refresh()
  } catch (error) { messageIsError.value = true; message.value = error instanceof Error ? error.message : '检测失败' } finally { testing.value = false }
}

async function toggleRuntime() {
  if (!props.employee) return
  statusChanging.value = true; message.value = ''
  try {
    const action = paused.value ? 'resume' : 'pause'
    await api.employeeAction(props.employee.id, action)
    await store.refresh()
    message.value = action === 'resume' ? '员工已恢复接单。' : '员工已暂停接单，不会领取新任务。'
  } catch (error) { messageIsError.value = true; message.value = error instanceof Error ? error.message : '状态更新失败' } finally { statusChanging.value = false }
}

function reset() {
  fill(props.employee ?? undefined)
}

defineExpose({ getDirty: () => isDirty.value, dirty: isDirty, saving, reset, save })
</script>

<style scoped>
.config-fieldset { border: 0; margin: 0 0 16px; padding: 0; }
.config-fieldset legend { margin-bottom: 9px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); font-weight: var(--astra-weight-bold); text-transform: uppercase; letter-spacing: 0.08em; }
.field-id > span { color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.field-id { gap: 7px; }
.policy-block .policy-grid { margin-bottom: 12px; }
.num-field input { width: 100%; min-height: var(--astra-control-height); padding: 10px 12px; color: var(--astra-text-primary); border: 1px solid var(--astra-border); border-radius: 7px; outline: none; background: var(--astra-bg-base); }
.runtime-card { display: grid; gap: 8px; padding: 13px 14px; border: 1px solid var(--astra-border); border-radius: 10px; background: rgba(76, 141, 255, 0.04); }
.runtime-card__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.runtime-card__head strong { font-size: var(--astra-font-control); }
.runtime-card__head > span:not(.astra-form-label) { color: var(--astra-primary-bright); font-size: var(--astra-font-control); font-weight: var(--astra-weight-bold); }
.runtime-card__action { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.runtime-card__action span { color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.env-connection { display: grid; gap: 10px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--astra-border); }
.env-connection__row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.env-connection__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.env-connection__grid > div { display: grid; padding: 8px 10px; border-radius: 8px; background: var(--astra-bg-base); }
.env-connection dt { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.env-connection dd { overflow: hidden; margin: 2px 0 0; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.env-connection :deep(.el-button) { justify-self: start; }
.employee-config-tabs :deep(.el-tabs__content) { display: none; }
.employee-config-tabs { margin-bottom: 12px; }
@media (max-width: 560px) { .env-connection__grid { grid-template-columns: 1fr; } }
</style>
