<template>
  <div class="page" data-testid="settings-page">
    <section class="page-intro compact-intro"><div><span class="kicker"><Settings :size="13" /> SYSTEM CONFIG</span><h2>配置中心</h2><p>配置数字员工、默认 OpenCode 执行环境与自主工作策略。</p></div><span class="config-mode"><LockKeyhole :size="13" /> 不保存密码与私钥内容</span></section>
    <nav class="settings-tabs"><button v-for="item in tabs" :key="item.id" :class="{ active: tab === item.id }" @click="tab = item.id"><component :is="item.icon" :size="14" />{{ item.label }}</button></nav>

    <section v-if="tab === 'employees'" class="settings-layout settings-layout--v02">
      <AstraPanel title="数字员工" subtitle="一名员工绑定一个默认执行环境">
        <template #action><button class="icon-button" aria-label="新增员工" data-testid="create-employee" @click="beginCreate"><Plus :size="15" /></button></template>
        <div class="settings-employee-list"><button v-for="employee in store.employees" :key="employee.id" class="settings-employee" :class="{ active: !creating && selectedId === employee.id }" @click="selectEmployee(employee.id)"><span class="employee-avatar employee-avatar--mini"><Bot :size="18" /><i /></span><div><strong>{{ employee.name }}</strong><small>{{ environmentLabel(employee.execution_environment) }}</small></div><AstraStatusBadge :status="employee.execution_environment?.status ?? 'UNKNOWN'" /></button><button class="settings-new" @click="beginCreate"><Plus :size="14" /> 新建员工</button></div>
      </AstraPanel>

      <AstraPanel :title="creating ? '创建数字员工' : `${selectedEmployee?.name ?? '员工'} 配置`" :subtitle="creating ? '保存后可立即检测执行环境' : '环境变更仅应用于后续新任务'">
        <template #action><AstraStatusBadge v-if="!creating && selectedEmployee?.execution_environment" :status="selectedEmployee.execution_environment.status" /></template>
        <div v-if="selectedEmployee?.current_task_count" class="configuration-warning"><TriangleAlert :size="15" /><span>员工正在执行任务。本次环境修改只影响后续领取的新任务，当前任务继续使用原环境快照。</span></div>
        <nav class="sub-tabs"><button v-for="item in employeeTabs" :key="item.id" :class="{ active: employeeTab === item.id }" @click="employeeTab = item.id">{{ item.label }}</button></nav>
        <form class="config-form config-form--editable" @submit.prevent="save">
          <div v-if="employeeTab === 'basic'">
            <div class="form-grid"><label>员工 ID<input v-model.trim="form.id" :readonly="!creating" required placeholder="Astra-04" /></label><label>显示名称<input v-model.trim="form.name" required placeholder="Astra-04" /></label></div>
            <label>岗位<input v-model.trim="form.role" required placeholder="测试执行员工" /></label>
            <label>描述<textarea v-model="form.description" rows="4" placeholder="该数字员工的工作职责与边界" /></label>
            <label>任务来源范围<input v-model="form.sourceScope" placeholder="manual, nr_test_system" /><small>多个来源用英文逗号分隔</small></label>
            <label class="check-row"><input v-model="form.enabled" type="checkbox" /><span><strong>启用员工</strong><small>关闭后不参与 Dispatcher 调度</small></span></label>
          </div>

          <div v-else-if="employeeTab === 'capabilities'">
            <label>能力标签<textarea v-model="form.capabilities" rows="5" placeholder="script_generate, script_execute, result_verify" /><small>用于 Dispatcher 的确定性任务匹配</small></label>
            <label>技能标签<textarea v-model="form.skills" rows="5" placeholder="pytest, playwright, api-test" /><small>用于描述员工擅长的测试技术栈</small></label>
          </div>

          <div v-else-if="employeeTab === 'environment'" data-testid="environment-form">
            <div class="environment-mode"><button type="button" :class="{ active: form.environment.mode === 'LOCAL' }" @click="setMode('LOCAL')"><Laptop :size="20" /><strong>本地执行</strong><small>Astra 所在主机</small></button><button type="button" :class="{ active: form.environment.mode === 'LINUX_REMOTE' }" @click="setMode('LINUX_REMOTE')"><Server :size="20" /><strong>Linux 远程</strong><small>通过 SSH 执行</small></button></div>
            <div class="form-grid"><label>环境名称<input v-model.trim="form.environment.name" required /></label><label>OpenCode 命令<input v-model.trim="form.environment.opencode_path" required placeholder="opencode" /></label></div>
            <label>环境描述<input v-model="form.environment.description" placeholder="例如：本机开发环境 / Linux 测试机" /></label>
            <label>Workspace 根目录<input v-model.trim="form.environment.workspace_root" required :placeholder="form.environment.mode === 'LOCAL' ? './workspaces' : '/opt/astra/workspaces'" /></label>
            <template v-if="form.environment.mode === 'LINUX_REMOTE'">
              <div class="form-grid"><label>Host<input v-model.trim="form.environment.host" required placeholder="10.0.0.12" /></label><label>Port<input v-model.number="form.environment.port" required type="number" min="1" max="65535" /></label></div>
              <div class="form-grid"><label>Username<input v-model.trim="form.environment.username" required placeholder="astra" /></label><label>认证方式<select v-model="form.environment.auth_method"><option value="SSH_AGENT">SSH Agent</option><option value="SSH_KEY">SSH Key 路径</option></select></label></div>
              <label v-if="form.environment.auth_method === 'SSH_KEY'">SSH Key 路径<input v-model.trim="form.environment.ssh_key_path" required placeholder="/Users/me/.ssh/id_ed25519" /><small>只保存路径，不读取或展示私钥内容</small></label>
            </template>
            <div class="environment-security"><ShieldCheck :size="15" /><span>远程认证仅支持 SSH Agent 或密钥路径。Astra 不在页面、数据库或日志中保存密码和私钥内容。</span></div>
            <div v-if="checks.length" class="environment-checks"><article v-for="check in checks" :key="check.name"><CheckCircle2 v-if="check.passed" :size="14" /><CircleX v-else :size="14" /><div><strong>{{ check.name }}</strong><small>{{ check.detail }}</small></div></article></div>
          </div>

          <div v-else>
            <div class="policy-grid"><label class="check-row"><input v-model="form.auto_claim" type="checkbox" /><span><strong>自动领取</strong><small>允许 Dispatcher 分配匹配任务</small></span></label><label class="check-row"><input v-model="form.auto_execute" type="checkbox" /><span><strong>自动执行</strong><small>领取后自动进入 OpenCode</small></span></label><label class="check-row"><input v-model="form.auto_repair" type="checkbox" /><span><strong>自动修复</strong><small>验证失败后继续原 Session</small></span></label></div>
            <div class="form-grid"><label>最大自动重试<input v-model.number="form.max_auto_retries" type="number" min="0" max="20" /></label><label>最大并发任务<input v-model.number="form.max_concurrency" type="number" min="1" max="16" /></label></div>
          </div>

          <div v-if="message" class="form-message" :data-error="messageIsError">{{ message }}</div>
          <footer class="config-actions"><button v-if="!creating" type="button" class="button" :disabled="testing || saving" @click="testEnvironment"><RefreshCw :size="14" :class="{ spin: testing }" /> {{ testing ? '检测中' : '测试连接' }}</button><button type="button" class="button" @click="resetForm">取消</button><button class="button button--primary" :disabled="saving"><Save :size="14" /> {{ saving ? '保存中' : creating ? '创建员工' : '保存配置' }}</button></footer>
        </form>
      </AstraPanel>
    </section>

    <section v-else class="config-grid"><AstraPanel v-for="group in activeConfig" :key="group.title" :title="group.title" :subtitle="group.subtitle"><dl class="config-list"><div v-for="item in group.items" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div></dl></AstraPanel></section>
    <div class="config-security"><ShieldCheck :size="18" /><div><strong>配置安全边界</strong><p>业务 Token 仅从环境变量读取；SSH 配置只记录非秘密连接参数和密钥文件路径。</p></div></div>
  </div>
</template>

<script setup lang="ts">
import { Bot, CheckCircle2, CircleX, Database, Laptop, LockKeyhole, Plus, RefreshCw, Save, Server, Settings, ShieldCheck, SlidersHorizontal, TriangleAlert } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Employee } from '@/api/types'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
import { environmentLabel } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const store = useAstraStore()
const tab = ref('employees')
const employeeTab = ref('basic')
const selectedId = ref('')
const creating = ref(false)
const saving = ref(false)
const testing = ref(false)
const message = ref('')
const messageIsError = ref(false)
const checks = ref<Array<{ name: string; passed: boolean; detail: string }>>([])
const tabs = [{ id: 'employees', label: '数字员工配置', icon: Bot }, { id: 'sources', label: '任务源配置', icon: Database }, { id: 'system', label: '系统配置', icon: SlidersHorizontal }]
const employeeTabs = [{ id: 'basic', label: '基本信息' }, { id: 'capabilities', label: '能力与技能' }, { id: 'environment', label: '执行环境' }, { id: 'policy', label: '自主策略' }]

const emptyEnvironment = () => ({ mode: 'LOCAL' as 'LOCAL' | 'LINUX_REMOTE', name: '本地 OpenCode', description: '', host: '', port: 22, username: '', auth_method: 'SSH_AGENT' as 'SSH_AGENT' | 'SSH_KEY', ssh_key_path: '', opencode_path: 'opencode', workspace_root: './workspaces', labels: [] as string[] })
const form = reactive({ id: '', name: '', role: '', description: '', capabilities: '', skills: '', sourceScope: 'manual', enabled: true, auto_claim: true, auto_execute: true, auto_repair: true, max_auto_retries: 3, max_concurrency: 1, environment: emptyEnvironment() })
const selectedEmployee = computed(() => store.employees.find((employee) => employee.id === selectedId.value))
const split = (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean)

function fill(employee?: Employee) {
  const environment = employee?.execution_environment
  Object.assign(form, { id: employee?.id ?? '', name: employee?.name ?? '', role: employee?.role ?? '', description: employee?.description ?? '', capabilities: employee?.capabilities.join(', ') ?? '', skills: employee?.skills.join(', ') ?? '', sourceScope: employee?.source_scope.join(', ') ?? 'manual', enabled: employee?.enabled ?? true, auto_claim: employee?.auto_claim ?? true, auto_execute: employee?.auto_execute ?? true, auto_repair: employee?.auto_repair ?? true, max_auto_retries: employee?.max_auto_retries ?? 3, max_concurrency: employee?.max_concurrency ?? 1, environment: environment ? { mode: environment.mode, name: environment.name, description: environment.description, host: environment.host ?? '', port: environment.port, username: environment.username ?? '', auth_method: environment.auth_method, ssh_key_path: environment.ssh_key_path ?? '', opencode_path: environment.opencode_path, workspace_root: environment.workspace_root, labels: [...environment.labels] } : emptyEnvironment() })
  checks.value = []
  message.value = ''
}
function selectEmployee(id: string) { creating.value = false; selectedId.value = id; fill(store.employees.find((item) => item.id === id)); router.replace({ query: { employee: id } }) }
function beginCreate() { creating.value = true; selectedId.value = ''; employeeTab.value = 'basic'; fill(); router.replace({ query: { create: '1' } }) }
function resetForm() { if (creating.value) beginCreate(); else fill(selectedEmployee.value) }
function setMode(mode: 'LOCAL' | 'LINUX_REMOTE') { form.environment.mode = mode; if (mode === 'LINUX_REMOTE' && !form.environment.workspace_root.startsWith('/')) form.environment.workspace_root = '/opt/astra/workspaces'; if (mode === 'LOCAL' && form.environment.workspace_root.startsWith('/opt/astra')) form.environment.workspace_root = './workspaces' }
function environmentPayload() { return { ...form.environment, host: form.environment.mode === 'LOCAL' ? null : form.environment.host || null, username: form.environment.mode === 'LOCAL' ? null : form.environment.username || null, ssh_key_path: form.environment.auth_method === 'SSH_KEY' ? form.environment.ssh_key_path || null : null } }
function employeePayload() { return { name: form.name, role: form.role, description: form.description, capabilities: split(form.capabilities), skills: split(form.skills), source_scope: split(form.sourceScope), enabled: form.enabled, auto_claim: form.auto_claim, auto_execute: form.auto_execute, auto_repair: form.auto_repair, max_auto_retries: form.max_auto_retries, max_concurrency: form.max_concurrency } }

async function save() {
  saving.value = true; message.value = ''; messageIsError.value = false
  try {
    if (creating.value) {
      const created = await api.createEmployee({ id: form.id, ...employeePayload(), execution_environment: environmentPayload() })
      await store.refresh(); selectEmployee(created.id); message.value = '员工已创建。请测试连接，使环境进入“正常”状态。'; employeeTab.value = 'environment'
    } else {
      await api.updateEmployee(selectedId.value, employeePayload()); await api.updateEnvironment(selectedId.value, environmentPayload()); await store.refresh(); fill(store.employees.find((item) => item.id === selectedId.value)); message.value = '配置已保存。环境状态已重置为“未检查”，请重新测试连接。'
    }
  } catch (error) { messageIsError.value = true; message.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}
async function testEnvironment() {
  testing.value = true; message.value = ''; messageIsError.value = false
  try { const result = await api.testEnvironment(selectedId.value); checks.value = result.checks; message.value = result.status === 'AVAILABLE' ? '环境检测通过，可以领取新任务。' : '环境检测未通过，请根据检查项修复。'; messageIsError.value = result.status !== 'AVAILABLE'; await store.refresh() }
  catch (error) { messageIsError.value = true; message.value = error instanceof Error ? error.message : '检测失败' }
  finally { testing.value = false }
}

onMounted(async () => {
  await store.refresh()
  if (route.query.create === '1') beginCreate()
  else selectEmployee(String(route.query.employee ?? store.employees[0]?.id ?? ''))
})

const configs = {
  sources: [{ title: 'nr_test_system', subtitle: 'Task Source Adapter', items: [{ label: '状态', value: '可配置 / 待对端联调' }, { label: '发现路径', value: '/api/astra/tasks' }, { label: '发现状态', value: 'READY' }, { label: '唯一键', value: 'source + external_task_id' }] }, { title: '来源隔离', subtitle: 'Core 不依赖外部结构', items: [{ label: '字段映射', value: 'Adapter 内完成' }, { label: '认证', value: 'Bearer Token（环境变量）' }, { label: '回填时点', value: 'Verifier PASS 后' }] }],
  system: [{ title: 'Runtime 调度', subtitle: 'configs/astra.yaml', items: [{ label: 'Task Scout 间隔', value: '30 秒' }, { label: 'Dispatcher 间隔', value: '5 秒' }, { label: 'Heartbeat 间隔', value: '10 秒' }, { label: '离线阈值', value: '60 秒' }] }, { title: 'OpenCode 与验证', subtitle: '真实执行门禁', items: [{ label: '环境模式', value: 'LOCAL / LINUX_REMOTE' }, { label: 'Session 策略', value: '每任务独立，重试恢复' }, { label: '完成门禁', value: 'Verifier PASS' }, { label: '使用量口径', value: 'OpenCode 实际返回，不估算' }] }],
}
const activeConfig = computed(() => configs[tab.value as keyof typeof configs] ?? [])
</script>
