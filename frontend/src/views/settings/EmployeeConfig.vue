<template>
  <AstraPanel
    :title="creating ? '创建数字员工' : `${employeeDisplayName(employee?.name)} 配置`"
    subtitle="配置描述员工职责与工作环境；运行状态由系统状态机维护。"
  >
    <nav class="sub-tabs">
      <button v-for="item in tabs" :key="item.id" :class="{ active: employeeTab === item.id }" @click="switchTab(item.id)">{{ item.label }}</button>
    </nav>

    <form class="config-form config-form--editable" @submit.prevent="save">
      <div v-if="employeeTab === 'basic'">
        <div class="form-grid">
          <label class="field-id">
            <span>员工 ID</span>
            <IdDisplay v-if="!creating" :value="employee?.id ?? ''" :max-width="200" />
            <input v-else v-model.trim="form.id" required placeholder="employee-04" />
          </label>
          <label>员工名称<input v-model.trim="form.name" required placeholder="员工-04" /></label>
        </div>
        <div class="form-grid">
          <label>岗位<input v-model.trim="form.role" required placeholder="测试平台开发" /></label>
          <label>默认办公区域<select v-model="form.default_work_area" required><option v-for="area in workspaceAreas" :key="area.id" :value="area.id">{{ area.name }}</option></select><small>无特定任务场景时，员工会出现在这个区域。</small></label>
        </div>
        <label>说明<textarea v-model="form.description" rows="4" placeholder="说明该员工的工作职责与边界" /></label>

        <fieldset class="config-fieldset">
          <legend>配置状态</legend>
          <label class="check-row"><AstraSwitch v-model="form.enabled" /><span><strong>启用员工</strong><small>停用后不再自动分配新任务</small></span></label>
        </fieldset>

        <div v-if="!creating" class="runtime-card">
          <div class="runtime-card__head"><strong>运行状态</strong><span>{{ runtimeMeta.label }}</span></div>
          <small>由系统状态机维护（空闲 / 执行中 / 等待输入 / 异常），此表单不可直接修改。</small>
          <div class="runtime-card__action">
            <span>{{ paused ? '员工已暂停接单，不会领取新任务。' : '员工可正常领取匹配任务。' }}</span>
            <button type="button" class="button button--compact" :class="{ 'button--warning': !paused }" :disabled="statusChanging || (!paused && currentTaskCount > 0)" @click="toggleRuntime">
              {{ statusChanging ? '处理中…' : paused ? '继续接单' : '暂停接单' }}
            </button>
          </div>
        </div>
      </div>

      <div v-else-if="employeeTab === 'scope'" class="scope-config">
        <fieldset class="config-fieldset">
          <legend>支持任务类型</legend>
          <label class="check-row"><AstraSwitch :model-value="hasType('ISSUE')" @update:model-value="toggleType('ISSUE')" /><span><strong>问题</strong><small>缺陷、故障、异常或已有能力失效</small></span></label>
          <label class="check-row"><AstraSwitch :model-value="hasType('REQUIREMENT')" @update:model-value="toggleType('REQUIREMENT')" /><span><strong>需求</strong><small>新功能、能力增强、改造、优化或重构</small></span></label>
        </fieldset>
        <fieldset class="config-fieldset">
          <legend>支持任务分类</legend>
          <label v-for="category in categories" :key="category.id" class="check-row"><AstraSwitch :model-value="hasCategory(category.id)" @update:model-value="toggleCategory(category.id)" /><span><strong>{{ category.name }}</strong><small>{{ category.description }}</small></span></label>
        </fieldset>
      </div>

      <div v-else-if="employeeTab === 'environment'" data-testid="environment-form">
        <div class="environment-mode">
          <button type="button" :class="{ active: form.environment.mode === 'LOCAL' }" @click="setMode('LOCAL')"><Laptop :size="20" /><strong>本地</strong><small>NEXUS 所在主机</small></button>
          <button type="button" :class="{ active: form.environment.mode === 'LINUX_REMOTE' }" @click="setMode('LINUX_REMOTE')"><Server :size="20" /><strong>Linux 远程</strong><small>SSH 隧道连接 Server</small></button>
        </div>
        <div class="form-grid"><label>环境名称<input v-model.trim="form.environment.name" required /></label><label>Agent 可执行文件<input v-model.trim="form.environment.opencode_path" required :placeholder="form.environment.mode === 'LOCAL' ? 'opencode 或 C:\\Program Files\\OpenCode\\opencode.exe' : '/usr/local/bin/opencode'" /><small>正式 Runtime 由该 OpenCode 启动 Server；显式 fallback 时才使用 CLI。</small></label></div>
        <div class="form-grid"><label>Agent 模型<input v-model.trim="form.environment.model_name" placeholder="opencode/glm-5.1" /><small>留空时使用 Agent 自身或平台默认模型。</small></label><label>环境说明<input v-model="form.environment.description" placeholder="例如：测试平台开发环境" /></label></div>
        <label>工作空间<input v-model.trim="form.environment.workspace_root" required :placeholder="form.environment.mode === 'LOCAL' ? 'D:\\code\\nr_test_system' : '/home/nexus/project'" /><small>支持 Windows 盘符、空格和中文目录；该路径属于员工，会在不同任务间长期复用。</small></label>
        <template v-if="form.environment.mode === 'LINUX_REMOTE'">
          <div class="form-grid"><label>SSH Host<input v-model.trim="form.environment.host" required placeholder="10.0.0.12" /></label><label>SSH Port<input v-model.number="form.environment.port" required type="number" min="1" max="65535" /></label></div>
          <div class="form-grid"><label>Username<input v-model.trim="form.environment.username" required placeholder="nexus" /></label><label>SSH 密码<input v-model="form.environment.ssh_password" :required="creating || !employee?.execution_environment?.has_ssh_password" type="password" autocomplete="new-password" :placeholder="employee?.execution_environment?.has_ssh_password ? '已配置，留空保持不变' : '请输入 SSH 密码'" /></label></div>
          <label>OpenCode Server Port<input v-model.number="form.environment.opencode_server_port" required type="number" min="1" max="65535" /><small>默认 4096，仅监听远程 127.0.0.1，并通过 SSH 隧道访问；无需开放防火墙端口。</small></label>
        </template>
        <div class="environment-security"><ShieldCheck :size="15" /><span>SSH 密码保存在部署数据库中且接口不回显；远程 OpenCode Server 只绑定 Linux loopback，不对公网暴露。</span></div>

        <div class="env-connection" v-if="!creating">
          <div class="env-connection__row"><strong>工作环境连接</strong><AstraStatusBadge :status="selectedEnvironmentStatus" /></div>
          <div class="env-connection__grid" v-if="selectedEnvironment">
            <div><dt>Server 地址</dt><dd>{{ serverAddress }}</dd></div>
            <div><dt>工作目录</dt><dd>{{ selectedEnvironment.workspace_root || '—' }}</dd></div>
            <div><dt>模型</dt><dd>{{ selectedEnvironment.model_name || '—' }}</dd></div>
            <div><dt>最近检测</dt><dd>{{ formatTime(selectedEnvironment.last_checked_at) }}</dd></div>
          </div>
          <button type="button" class="button button--compact" :disabled="testing" @click="testConnection"><RefreshCw :size="13" :class="{ spin: testing }" /> {{ testing ? '检测中' : '测试连接' }}</button>
        </div>
        <div v-if="checks.length" class="environment-checks"><article v-for="check in checks" :key="check.name"><CheckCircle2 v-if="check.passed" :size="14" /><CircleX v-else :size="14" /><div><strong>{{ check.name }}</strong><small>{{ check.detail }}</small></div></article></div>
      </div>

      <div v-else class="config-fieldset policy-block">
        <div class="policy-grid">
          <label class="check-row"><AstraSwitch v-model="form.auto_claim" /><span><strong>自动领取任务</strong><small>空闲时可以领取匹配的新任务</small></span></label>
          <label class="check-row"><AstraSwitch v-model="form.auto_execute" /><span><strong>允许自主执行</strong><small>领取后自动启动任务独立执行会话</small></span></label>
        </div>
        <label class="num-field">最大自动重试次数<input v-model.number="form.max_auto_retries" type="number" min="0" max="20" /><small>用于 Agent 执行异常时的恢复上限；员工工作方法不由 Astra 规定。</small></label>
        <div class="form-note">每位员工同时只处理一项任务。</div>
      </div>

      <div v-if="message" class="form-message" :data-error="messageIsError">{{ message }}</div>
    </form>

    <StickyActionBar v-if="isDirty" :dirty="isDirty" :saving="saving" :save-label="creating ? '创建员工' : '保存配置'" @save="save" @cancel="reset" />
  </AstraPanel>
</template>

<script setup lang="ts">
import { CheckCircle2, CircleX, Laptop, RefreshCw, Server, ShieldCheck } from 'lucide-vue-next'
import { computed, reactive, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { Employee, TaskCategory, TaskType } from '@/api/types'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import AstraSwitch from '@/components/astra/AstraSwitch.vue'
import IdDisplay from '@/components/astra/IdDisplay.vue'
import StickyActionBar from '@/components/astra/StickyActionBar.vue'
import { workspaceAreas, type WorkspaceAreaId } from '@/features/workspace/sceneLayout'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatTime } from '@/utils/format'

const props = defineProps<{ employee: Employee | null; creating: boolean; categories: TaskCategory[] }>()
const emit = defineEmits<{ (e: 'saved', id: string): void }>()
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
const form = reactive({ id: '', name: '', role: '', description: '', default_work_area: 'development' as WorkspaceAreaId, task_types: ['ISSUE', 'REQUIREMENT'] as TaskType[], category_ids: [] as string[], enabled: true, auto_claim: true, auto_execute: true, max_auto_retries: 3, environment: emptyEnvironment() })

const selectedEnvironment = computed(() => props.employee?.execution_environment ?? null)
const selectedEnvironmentStatus = computed(() => selectedEnvironment.value?.status ?? 'UNKNOWN')
const currentTaskCount = computed(() => props.employee?.current_task_count ?? 0)
const paused = computed(() => props.employee?.status === 'PAUSED')
const serverAddress = computed(() => {
  const env = selectedEnvironment.value
  if (!env) return '—'
  return env.mode === 'LINUX_REMOTE' ? `${env.host ?? ''}:${env.port}` : '本地'
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
    max_auto_retries: employee?.max_auto_retries ?? 3,
    environment: environment ? { mode: environment.mode, name: environment.name, description: environment.description, host: environment.host ?? '', port: environment.port, username: environment.username ?? '', ssh_password: '', opencode_server_port: environment.opencode_server_port ?? 4096, opencode_path: environment.opencode_path, model_name: environment.model_name ?? '', workspace_root: environment.workspace_root, labels: [...environment.labels] } : emptyEnvironment(),
  })
  checks.value = []; message.value = ''; employeeTab.value = 'basic'
  originalSnapshot.value = snapshot()
}

function snapshot(): string {
  return JSON.stringify({
    id: form.id, name: form.name, role: form.role, description: form.description, default_work_area: form.default_work_area,
    task_types: form.task_types, category_ids: form.category_ids, enabled: form.enabled, auto_claim: form.auto_claim, auto_execute: form.auto_execute,
    max_auto_retries: form.max_auto_retries,
    environment: { mode: form.environment.mode, name: form.environment.name, description: form.environment.description, host: form.environment.host ?? null, port: Number(form.environment.port), username: form.environment.username ?? null, opencode_server_port: Number(form.environment.opencode_server_port ?? 4096), opencode_path: form.environment.opencode_path, model_name: form.environment.model_name ?? null, workspace_root: form.environment.workspace_root, ssh_password: form.environment.ssh_password || null },
  })
}
const isDirty = computed(() => snapshot() !== originalSnapshot.value)

watch([() => props.employee?.id, () => props.creating], () => { fill(props.employee ?? undefined) }, { immediate: true })

function switchTab(id: string) { employeeTab.value = id }
function setMode(mode: 'LOCAL' | 'LINUX_REMOTE') { form.environment.mode = mode }
function hasType(value: TaskType) { return form.task_types.includes(value) }
function toggleType(value: TaskType) { form.task_types = form.task_types.includes(value) ? form.task_types.filter((item) => item !== value) : [...form.task_types, value] }
function hasCategory(id: string) { return form.category_ids.includes(id) }
function toggleCategory(id: string) { form.category_ids = form.category_ids.includes(id) ? form.category_ids.filter((item) => item !== id) : [...form.category_ids, id] }

function environmentPayload() {
  return { ...form.environment, host: form.environment.mode === 'LOCAL' ? null : form.environment.host || null, username: form.environment.mode === 'LOCAL' ? null : form.environment.username || null, ssh_password: form.environment.mode === 'LINUX_REMOTE' ? form.environment.ssh_password || null : null, model_name: form.environment.model_name || null }
}
function employeePayload() {
  return { name: form.name, role: form.role, description: form.description, default_work_area: form.default_work_area, task_types: form.task_types, category_ids: form.category_ids, enabled: form.enabled, auto_claim: form.auto_claim, auto_execute: form.auto_execute, max_auto_retries: form.max_auto_retries }
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
    await store.refresh()
    originalSnapshot.value = snapshot()
    emit('saved', employeeId)
    if (checkResult) {
      checks.value = checkResult.checks; messageIsError.value = checkResult.status !== 'AVAILABLE'
      message.value = checkResult.status === 'AVAILABLE' ? '配置已保存，工作环境检测正常。' : '配置已保存，但工作环境检测异常，请查看检查项。'
    } else {
      message.value = '配置已保存，工作环境状态保持不变。'
    }
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

defineExpose({ getDirty: () => isDirty.value, reset })
</script>

<style scoped>
.config-fieldset { border: 0; margin: 0 0 16px; padding: 0; }
.config-fieldset legend { margin-bottom: 9px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }
.field-id > span { color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.field-id { gap: 7px; }
.policy-block .policy-grid { margin-bottom: 12px; }
.num-field input { width: 100%; min-height: var(--astra-control-height); padding: 10px 12px; color: var(--astra-text-primary); border: 1px solid var(--astra-border); border-radius: 7px; outline: none; background: var(--astra-bg-base); }
.runtime-card { display: grid; gap: 8px; padding: 13px 14px; border: 1px solid var(--astra-border); border-radius: 10px; background: rgba(76, 141, 255, 0.04); }
.runtime-card__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.runtime-card__head strong { font-size: var(--astra-font-control); }
.runtime-card__head span { color: var(--astra-primary-bright); font-size: var(--astra-font-control); font-weight: 700; }
.runtime-card > small { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.runtime-card__action { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.runtime-card__action span { color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.env-connection { display: grid; gap: 10px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--astra-border); }
.env-connection__row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.env-connection__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.env-connection__grid > div { display: grid; padding: 8px 10px; border-radius: 8px; background: var(--astra-bg-base); }
.env-connection dt { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.env-connection dd { overflow: hidden; margin: 2px 0 0; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.env-connection .button { align-self: start; }
@media (max-width: 560px) { .env-connection__grid { grid-template-columns: 1fr; } }
</style>
