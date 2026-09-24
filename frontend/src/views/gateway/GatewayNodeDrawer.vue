<template>
  <el-drawer
    :model-value="open"
    size="min(600px, 100vw)"
    :with-header="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    append-to-body
    lock-scroll
    destroy-on-close
    class="gateway-node-drawer"
  >
        <header class="gateway-drawer__head">
          <div>
            <small>{{ node ? '编辑节点' : '新增节点' }}</small>
            <h3>{{ form.name || 'Gateway 节点配置' }}</h3>
            <p>按顺序完成基本信息、连接与探测、限额、资源池与启用。</p>
          </div>
          <el-button text circle aria-label="关闭" :disabled="busy" @click="requestClose"><X :size="18" /></el-button>
        </header>

        <ol class="gateway-steps">
          <li v-for="(item, index) in steps" :key="item.id" :class="{ active: step === item.id, done: step > item.id }">
            <b>{{ index + 1 }}</b><span>{{ item.label }}</span>
          </li>
        </ol>

        <div class="gateway-drawer__body">
          <!-- 1. 基本信息 -->
          <section v-if="step === 1" class="gateway-form">
            <label>节点名称<el-input v-model="form.name" placeholder="例如 主 Proxy 节点" /></label>
            <label>下游 Base URL（节点根地址）<el-input v-model="form.baseUrl" placeholder="https://proxy.example.com" /></label>
            <p class="gateway-form__note"><Info :size="13" />填节点根地址，不要带 /v1；Gateway 会自动追加 /v1/chat/completions。</p>
            <div class="gateway-form__grid">
              <label>认证方式
                <el-select v-model="form.authType">
                  <el-option label="Bearer Token" value="BEARER" />
                  <el-option label="自定义 Header" value="HEADER" />
                  <el-option label="无认证" value="NONE" />
                </el-select>
              </label>
              <label>认证 Header<el-input v-model="form.authHeader" :disabled="form.authType === 'NONE'" placeholder="Authorization" /></label>
            </div>
            <label v-if="form.authType !== 'NONE'">下游凭据
              <el-input v-model="form.apiKey" type="password" show-password autocomplete="new-password" :placeholder="node?.has_api_key ? '已配置，留空保持不变' : '下游 Proxy 的 Token / 凭据值'" />
            </label>
            <p class="gateway-form__note"><ShieldCheck :size="13" />凭据加密入库，任何响应与日志都不会回显明文。</p>
            <div class="gateway-form__grid">
              <label>健康路径<el-input v-model="form.healthPath" placeholder="/health" /></label>
              <label>探测间隔（秒）<el-input v-model="form.probeInterval" type="number" min="10" placeholder="继承默认" /></label>
            </div>
            <div class="gateway-form__grid">
              <label>连接超时（秒）<el-input v-model="form.connectTimeout" type="number" min="0.1" step="0.1" placeholder="继承默认" /></label>
              <label>请求超时（秒）<el-input v-model="form.requestTimeout" type="number" min="0.1" step="0.1" placeholder="继承默认" /></label>
            </div>
          </section>

          <!-- 2. 连接 / 模型 / SSE 探测 -->
          <section v-else-if="step === 2" class="gateway-form">
            <label>支持模型（逗号或换行分隔）<el-input v-model="form.modelsText" type="textarea" :rows="3" resize="vertical" placeholder="gpt-4o-mini&#10;claude-3-5-sonnet" /></label>
            <div class="gateway-probe-block">
              <div class="gateway-probe-block__head">
                <strong>探测项目</strong>
                <el-checkbox v-for="type in probeTypes" :key="type" v-model="form.probeTypes" :value="type">
                  {{ probeTypeLabel(type) }}
                </el-checkbox>
                <el-button type="primary" :loading="probeRunning" :disabled="busy || !form.probeTypes.length" @click="runProbe">
                  <RefreshCw v-if="!probeRunning" :size="13" />{{ probeRunning ? '探测中…' : '保存并执行探测' }}
                </el-button>
              </div>
              <p class="gateway-form__note"><Info :size="13" />必须同时勾选网络 / 服务 / 模型 / SSE 完成完整探测；局部探测不会让节点脱离 UNKNOWN。连续成功 2 次方为 HEALTHY。首次保存会先以禁用态落库。</p>
              <p v-if="probeChecks.length" class="gateway-form__note">
                <span class="status-badge" :data-tone="authenticationTone(probeAuthentication)">{{ authenticationLabel(probeAuthentication) }}</span>
                <span>由真实模型调用状态推断（无独立认证探测）。</span>
              </p>
              <ul v-if="probeChecks.length" class="gateway-probe-result">
                <li v-for="check in probeChecks" :key="check.id">
                  <CheckCircle2 v-if="check.success" :size="14" class="ok" /><XCircle v-else :size="14" class="bad" />
                  <span>{{ probeTypeLabel(check.probe_type) }}</span>
                  <small>{{ check.latency_ms }} ms</small>
                  <small v-if="check.status_code">HTTP {{ check.status_code }}</small>
                  <em v-if="check.error" :title="check.error">{{ check.error }}</em>
                </li>
              </ul>
            </div>
          </section>

          <!-- 3. 限额 -->
          <section v-else-if="step === 3" class="gateway-form">
            <div class="gateway-form__grid">
              <label>权重<el-input v-model="form.weight" type="number" min="0" /></label>
              <label>最大并发（0 为不限）<el-input v-model="form.maxConcurrency" type="number" min="0" /></label>
            </div>
            <div class="gateway-form__grid">
              <label>每小时 Token 限额<el-input v-model="form.hourly" type="number" min="0" placeholder="不限" /></label>
              <label>每日 Token 限额<el-input v-model="form.daily" type="number" min="0" placeholder="不限" /></label>
            </div>
            <label>额度策略
              <el-select v-model="form.quotaPolicy">
                <el-option label="达到限额停止新请求" value="STOP" />
                <el-option label="达到限额仅告警" value="ALERT" />
                <el-option label="达到限额仅记录" value="RECORD" />
              </el-select>
            </label>
            <p class="gateway-form__note"><Timer :size="13" />额度按自然小时 / 自然日统计已完成请求的实际 usage，未知用量记为 unknown，不估算为零。</p>
          </section>

          <!-- 4. 资源池与启用 -->
          <section v-else class="gateway-form">
            <label>资源池
              <el-select v-model="form.poolId">
                <el-option label="不分配" value="" />
                <el-option v-for="pool in pools" :key="pool.id" :label="`${pool.name}${pool.enabled ? '' : '（已禁用）'}`" :value="pool.id" />
              </el-select>
            </label>
            <label>排序<el-input v-model="form.sortOrder" type="number" /></label>
            <div class="gateway-form__grid">
              <label>调度状态
                <el-select v-model="form.scheduling">
                  <el-option label="调度中" value="ACTIVE" :disabled="activeOptionDisabled" />
                  <el-option label="安全下线" value="DRAINING" />
                  <el-option label="已阻止" value="BLOCKED" />
                </el-select>
              </label>
              <label class="gateway-toggle">
                <span>启用节点</span>
                <el-switch v-model="form.enabled" />
              </label>
            </div>
            <p v-if="!activationReady" class="gateway-form__note gateway-form__note--warn">
              <TriangleAlert :size="13" />只有完成 NETWORK/SERVICE/MODEL/STREAM 完整探测并达到 HEALTHY/DEGRADED，且未修改连接配置（Base URL、认证、模型、健康路径）时，才可启用并进入「调度中」。
            </p>
            <p class="gateway-form__note"><PlugZap :size="13" />完成后节点才允许被数据面调度；未启用时保持禁用，不影响现有请求。</p>
          </section>

          <p v-if="error" class="gateway-form__error"><TriangleAlert :size="14" />{{ error }}</p>
        </div>

        <footer class="gateway-drawer__foot">
          <el-button v-if="step > 1" :disabled="busy" @click="prevStep">上一步</el-button>
          <span class="gateway-drawer__spacer" />
          <el-button :disabled="busy" @click="requestClose">取消</el-button>
          <el-button v-if="step < 4" type="primary" :loading="saving" :disabled="busy" @click="goNext">下一步</el-button>
          <el-button v-else type="primary" :loading="saving" :disabled="busy" @click="finish">{{ node ? '保存节点' : '完成' }}</el-button>
        </footer>
  </el-drawer>
</template>

<script setup lang="ts">
import {
  CheckCircle2,
  Info,
  PlugZap,
  RefreshCw,
  ShieldCheck,
  Timer,
  TriangleAlert,
  X,
  XCircle,
} from 'lucide-vue-next'
import { computed, reactive, ref, watch } from 'vue'
import {
  gatewayApi,
  type GatewayHealthCheck,
  type GatewayHealthState,
  type GatewayNode,
  type GatewayNodeWrite,
  type GatewayPool,
  type GatewayProbeType,
  type GatewayQuotaPolicy,
  type GatewaySchedulingState,
  type GatewayAuthType,
} from '@/api/gateway'
import {
  authenticationLabel,
  authenticationResult,
  authenticationTone,
  errorMessage,
  parseNumberList,
  probeTypeLabel,
} from '@/utils/gateway'

type StepId = 1 | 2 | 3 | 4

const props = defineProps<{ open: boolean; node: GatewayNode | null; pools: GatewayPool[] }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const probeTypes: GatewayProbeType[] = ['NETWORK', 'SERVICE', 'MODEL', 'STREAM']
const steps = [
  { id: 1 as StepId, label: '基本信息' },
  { id: 2 as StepId, label: '连接 / 模型 / 探测' },
  { id: 3 as StepId, label: '限额' },
  { id: 4 as StepId, label: '资源池与启用' },
]

const step = ref<StepId>(1)
const saving = ref(false)
const probeRunning = ref(false)
const error = ref('')
const probeChecks = ref<GatewayHealthCheck[]>([])
const currentHealth = ref<GatewayHealthState>('UNKNOWN')
const createdId = ref<string | null>(null)
const createdInFlow = ref(false)

const form = reactive({
  name: '',
  baseUrl: '',
  authType: 'BEARER' as GatewayAuthType,
  authHeader: 'Authorization',
  apiKey: '',
  healthPath: '',
  connectTimeout: '',
  requestTimeout: '',
  probeInterval: '',
  modelsText: '',
  probeTypes: [...probeTypes] as GatewayProbeType[],
  weight: '1',
  maxConcurrency: '0',
  hourly: '',
  daily: '',
  quotaPolicy: 'STOP' as GatewayQuotaPolicy,
  poolId: '',
  sortOrder: '0',
  enabled: true,
  scheduling: 'ACTIVE' as GatewaySchedulingState,
})

const busy = computed(() => saving.value || probeRunning.value)
const probeAuthentication = computed(() => authenticationResult(probeChecks.value))

// 连接相关字段一旦改动（相对最近一次已保存配置），服务端会重置旧健康态，
// 因此这次编辑同样视为未就绪，必须重新保存并完整探测。
interface ConnectionBaseline {
  baseUrl: string
  authType: GatewayAuthType
  authHeader: string
  healthPath: string
  models: string
}
const baseline = ref<ConnectionBaseline | null>(null)

function connectionSnapshot(): ConnectionBaseline {
  return {
    baseUrl: form.baseUrl.trim(),
    authType: form.authType,
    authHeader: form.authHeader.trim() || 'Authorization',
    healthPath: form.healthPath.trim(),
    models: parseNumberList(form.modelsText).join('\u0000'),
  }
}

function baselineOf(node: GatewayNode | null): ConnectionBaseline | null {
  if (!node) return null
  return {
    baseUrl: node.base_url,
    authType: node.auth_type,
    authHeader: node.auth_header,
    healthPath: node.health_path,
    models: (node.models ?? []).join('\u0000'),
  }
}

const connectionChanged = computed(() => {
  if (form.apiKey !== '') return true
  const base = baseline.value
  if (!base) return false
  const now = connectionSnapshot()
  return (
    now.baseUrl !== base.baseUrl ||
    now.authType !== base.authType ||
    now.authHeader !== base.authHeader ||
    now.healthPath !== base.healthPath ||
    now.models !== base.models
  )
})
const activationReady = computed(
  () =>
    !connectionChanged.value &&
    (currentHealth.value === 'HEALTHY' || currentHealth.value === 'DEGRADED'),
)
// 新进入 ACTIVE（当前不是 ACTIVE）才需要健康就绪；保持原有 ACTIVE 不是状态迁移。
const activating = computed(
  () => form.scheduling === 'ACTIVE' && (props.node?.scheduling_state ?? 'DRAINING') !== 'ACTIVE',
)
const activeOptionDisabled = computed(() => activating.value && !activationReady.value)

watch(
  () => [props.open, props.node] as const,
  ([open]) => {
    if (!open) return
    step.value = 1
    error.value = ''
    probeChecks.value = []
    currentHealth.value = props.node?.health_state ?? 'UNKNOWN'
    createdId.value = props.node?.id ?? null
    createdInFlow.value = false
    baseline.value = baselineOf(props.node)
    const node = props.node
    form.name = node?.name ?? ''
    form.baseUrl = node?.base_url ?? ''
    form.authType = node?.auth_type ?? 'BEARER'
    form.authHeader = node?.auth_header ?? 'Authorization'
    form.apiKey = ''
    form.healthPath = node?.health_path ?? ''
    form.connectTimeout = node?.connect_timeout_seconds?.toString() ?? ''
    form.requestTimeout = node?.request_timeout_seconds?.toString() ?? ''
    form.probeInterval = node?.probe_interval_seconds?.toString() ?? ''
    form.modelsText = (node?.models ?? []).join('\n')
    form.probeTypes = [...probeTypes]
    form.weight = String(node?.weight ?? 1)
    form.maxConcurrency = String(node?.max_concurrency ?? 0)
    form.hourly = node?.hourly_token_limit?.toString() ?? ''
    form.daily = node?.daily_token_limit?.toString() ?? ''
    form.quotaPolicy = node?.quota_policy ?? 'STOP'
    form.poolId = node?.pool_id ?? ''
    form.sortOrder = String(node?.sort_order ?? 0)
    form.enabled = (node?.config_state ?? 'ENABLED') === 'ENABLED'
    form.scheduling = node?.scheduling_state ?? 'ACTIVE'
  },
  { immediate: true },
)

function intOrNull(value: string): number | null {
  const text = value.trim()
  if (!text) return null
  const parsed = Number(text)
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null
}

function floatOrNull(value: string): number | null {
  const text = value.trim()
  if (!text) return null
  const parsed = Number(text)
  return Number.isFinite(parsed) ? parsed : null
}

function basePayload(): GatewayNodeWrite {
  return {
    name: form.name.trim(),
    base_url: form.baseUrl.trim(),
    auth_type: form.authType,
    auth_header: form.authHeader.trim() || 'Authorization',
    health_path: form.healthPath.trim(),
    connect_timeout_seconds: floatOrNull(form.connectTimeout),
    request_timeout_seconds: floatOrNull(form.requestTimeout),
    probe_interval_seconds: intOrNull(form.probeInterval),
    models: parseNumberList(form.modelsText),
    weight: Number(form.weight) || 0,
    max_concurrency: Number(form.maxConcurrency) || 0,
    hourly_token_limit: intOrNull(form.hourly),
    daily_token_limit: intOrNull(form.daily),
    quota_policy: form.quotaPolicy,
  }
}

function validateBasic(): boolean {
  if (!form.name.trim()) { error.value = '请填写节点名称'; return false }
  if (!/^https?:\/\//i.test(form.baseUrl.trim())) { error.value = 'Base URL 需以 http:// 或 https:// 开头'; return false }
  if (/\/v1\/?$/i.test(form.baseUrl.trim())) { error.value = 'Base URL 请填写节点根地址，不要包含 /v1'; return false }
  return true
}

async function persistBasic(): Promise<boolean> {
  const payload = basePayload()
  if (form.apiKey) payload.api_key = form.apiKey
  try {
    let saved: GatewayNode
    if (!createdId.value) {
      saved = await gatewayApi.createNode({ ...payload, config_state: 'DISABLED', scheduling_state: 'DRAINING' })
      createdId.value = saved.id
      createdInFlow.value = true
    } else {
      saved = await gatewayApi.updateNode(createdId.value, payload)
    }
    form.apiKey = ''
    // 连接配置变化后服务端会重置健康，以返回的节点为准同步界面状态。
    currentHealth.value = saved.health_state
    baseline.value = connectionSnapshot()
    error.value = ''
    return true
  } catch (reason) {
    error.value = errorMessage(reason, '保存节点失败')
    return false
  }
}

async function runProbe() {
  if (!validateBasic()) return
  probeRunning.value = true
  error.value = ''
  try {
    if (!(await persistBasic())) return
    if (!createdId.value) return
    const result = await gatewayApi.probeNode(createdId.value, form.probeTypes)
    probeChecks.value = result.checks
    currentHealth.value = result.node.health_state
  } catch (reason) {
    error.value = errorMessage(reason, '探测失败')
  } finally {
    probeRunning.value = false
  }
}

async function saveLimits(): Promise<boolean> {
  if (!createdId.value) return true
  try {
    await gatewayApi.updateNode(createdId.value, {
      weight: Number(form.weight) || 0,
      max_concurrency: Number(form.maxConcurrency) || 0,
      hourly_token_limit: intOrNull(form.hourly),
      daily_token_limit: intOrNull(form.daily),
      quota_policy: form.quotaPolicy,
    })
    return true
  } catch (reason) {
    error.value = errorMessage(reason, '保存限额失败')
    return false
  }
}

async function goNext() {
  if (step.value === 1) {
    if (!validateBasic()) return
    error.value = ''
    step.value = 2
    return
  }
  if (step.value === 2) {
    if (form.modelsText.trim() === '' && (props.node?.models.length ?? 0) === 0) {
      error.value = '请至少配置一个支持模型，否则节点不会被任何路由选中'
      return
    }
    saving.value = true
    const created = await persistBasic()
    saving.value = false
    if (!created) return
    step.value = 3
    return
  }
  if (step.value === 3) {
    saving.value = true
    const saved = await saveLimits()
    saving.value = false
    if (!saved) return
    step.value = 4
  }
}

async function finish() {
  if (!validateBasic()) return
  if (activating.value && !activationReady.value) {
    error.value = '节点需完成 NETWORK/SERVICE/MODEL/STREAM 完整探测并达到 HEALTHY/DEGRADED，才能进入「调度中」；请先在连接步骤完成探测，或改为安全下线 / 已阻止。'
    return
  }
  saving.value = true
  error.value = ''
  try {
    if (!(await persistBasic())) return
    if (!createdId.value) return
    await gatewayApi.updateNode(createdId.value, {
      pool_id: form.poolId || null,
      sort_order: Number(form.sortOrder) || 0,
      config_state: form.enabled ? 'ENABLED' : 'DISABLED',
      scheduling_state: form.scheduling,
    })
    emit('saved')
    emit('close')
  } catch (reason) {
    error.value = errorMessage(reason, '保存节点失败')
  } finally {
    saving.value = false
  }
}

function prevStep() {
  if (step.value > 1) step.value = (step.value - 1) as StepId
}

function requestClose() {
  if (busy.value) return
  if (createdInFlow.value) emit('saved')
  emit('close')
}
</script>

<style scoped>

.gateway-drawer__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 20px 22px 15px; border-bottom: 1px solid var(--astra-border); }
.gateway-drawer__head small { color: var(--astra-primary); font-size: var(--astra-font-helper); letter-spacing: .14em; }
.gateway-drawer__head h3 { margin: 4px 0 0; color: var(--astra-text-primary); }
.gateway-drawer__head p { margin: 4px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-steps { display: flex; gap: 6px; margin: 0; padding: 12px 22px; border-bottom: 1px solid var(--astra-border); list-style: none; }
.gateway-steps li { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0; padding: 6px 8px; color: var(--astra-text-muted); border-radius: 8px; font-size: var(--astra-font-helper); }
.gateway-steps li b { display: grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; background: var(--astra-bg-elevated); font-size: var(--astra-font-micro); }
.gateway-steps li span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gateway-steps li.active { color: var(--astra-primary-bright); background: var(--astra-primary-soft); }
.gateway-steps li.active b { color: #fff; background: var(--astra-primary); }
.gateway-steps li.done b { color: #fff; background: var(--astra-success); }
.gateway-drawer__body { flex: 1; min-height: 0; padding: 18px 22px; overflow-y: auto; }
.gateway-form { display: grid; gap: 13px; }
.gateway-form label { display: grid; gap: 6px; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.gateway-form :deep(.el-input), .gateway-form :deep(.el-select), .gateway-form :deep(.el-textarea) { width:100%;min-width:0 }
.gateway-form__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.gateway-toggle { align-content: center; }
.gateway-form__note { display: flex; align-items: center; gap: 6px; margin: 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-form__note--warn { color: var(--astra-warning); }
.gateway-form__error { display: flex; align-items: center; gap: 6px; margin: 0; padding: 9px 11px; color: var(--astra-danger); border: 1px solid rgba(228, 93, 106, .2); border-radius: 8px; background: var(--astra-danger-soft); font-size: var(--astra-font-helper); }
.gateway-probe-block { padding: 12px; border: 1px solid var(--astra-border); border-radius: 10px; background: var(--astra-bg-base); }
.gateway-probe-block__head { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 8px; }
.gateway-probe-block__head strong { margin-right: auto; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.gateway-probe-result { display: grid; gap: 5px; margin: 10px 0 0; padding: 0; list-style: none; }
.gateway-probe-result li { display: grid; grid-template-columns: 16px 70px auto auto minmax(0, 1fr); align-items: center; gap: 8px; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.gateway-probe-result .ok { color: var(--astra-success); }
.gateway-probe-result .bad { color: var(--astra-danger); }
.gateway-probe-result em { overflow: hidden; color: var(--astra-danger); font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.gateway-drawer__foot { display: flex; align-items: center; gap: 9px; padding: 14px 22px; border-top: 1px solid var(--astra-border); background: var(--astra-bg-card); }
.gateway-drawer__spacer { flex: 1; }
@media (max-width: 560px) { .gateway-form__grid { grid-template-columns: 1fr; } }

:global(.gateway-node-drawer .el-drawer__body) { display:flex;flex-direction:column;padding:0;overflow:hidden; }
:global(.gateway-node-drawer .el-drawer__header) { display:none; }
</style>