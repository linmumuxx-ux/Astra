// API 中转（Gateway）控制面唯一前端数据层：类型、凭据会话与全部 HTTP 调用。
// 所有指标字段直接对应后端 gateway-observability 契约，前端不再重算指标口径。

import { ref } from 'vue'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const CONTROL_TOKEN_KEY = 'astra.gateway.control.token'
const SELF_KEY_KEY = 'astra.gateway.self.key'

export type GatewayConfigState = 'ENABLED' | 'DISABLED'
export type GatewaySchedulingState = 'ACTIVE' | 'DRAINING' | 'BLOCKED'
export type GatewayHealthState = 'UNKNOWN' | 'CHECKING' | 'HEALTHY' | 'DEGRADED' | 'UNHEALTHY'
export type GatewayAuthType = 'BEARER' | 'HEADER' | 'NONE'
export type GatewayQuotaPolicy = 'STOP' | 'ALERT' | 'RECORD'
export type GatewayProbeType = 'NETWORK' | 'SERVICE' | 'MODEL' | 'STREAM'
export type GatewayStatsScope = 'overview' | 'node' | 'pool' | 'model' | 'key'
export type GatewayStatsWindow = 'hour' | 'today' | '7d' | '30d'

export interface GatewayPermissions {
  actor: string
  roles: string[]
}

export interface GatewayPool {
  id: string
  name: string
  description: string
  weight: number
  enabled: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

export interface GatewayPoolWrite {
  name: string
  description?: string
  weight?: number
  enabled?: boolean
  sort_order?: number
}

export interface GatewayNode {
  id: string
  name: string
  pool_id: string | null
  base_url: string
  auth_type: GatewayAuthType
  auth_header: string
  connect_timeout_seconds: number | null
  request_timeout_seconds: number | null
  health_path: string
  probe_interval_seconds: number | null
  models: string[]
  weight: number
  max_concurrency: number
  hourly_token_limit: number | null
  daily_token_limit: number | null
  quota_policy: GatewayQuotaPolicy
  config_state: GatewayConfigState
  scheduling_state: GatewaySchedulingState
  health_state: GatewayHealthState
  success_streak: number
  failure_streak: number
  health_detail: Record<string, unknown>
  has_api_key: boolean
  sort_order: number
  last_checked_at: string | null
  created_at: string
  updated_at: string
}

export interface GatewayNodeWrite {
  name?: string
  base_url?: string
  pool_id?: string | null
  api_key?: string | null
  auth_type?: GatewayAuthType
  auth_header?: string
  connect_timeout_seconds?: number | null
  request_timeout_seconds?: number | null
  health_path?: string
  probe_interval_seconds?: number | null
  models?: string[]
  weight?: number
  max_concurrency?: number
  hourly_token_limit?: number | null
  daily_token_limit?: number | null
  quota_policy?: GatewayQuotaPolicy
  config_state?: GatewayConfigState
  scheduling_state?: GatewaySchedulingState
  sort_order?: number
}

export interface GatewayRoute {
  id: string
  model: string
  pool_id: string
  description: string
  enabled: boolean
  weight: number
  created_at: string
  updated_at: string
}

export interface GatewayRouteWrite {
  model?: string
  pool_id?: string
  description?: string
  enabled?: boolean
  weight?: number
}

export interface GatewayKey {
  id: string
  name: string
  key_prefix: string
  owner_id: string | null
  allowed_models: string[]
  max_concurrency: number
  hourly_token_limit: number | null
  daily_token_limit: number | null
  enabled: boolean
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
  updated_at: string
}

export interface GatewayKeyCreated extends GatewayKey {
  key: string
}

export interface GatewayKeyWrite {
  name?: string
  owner_id?: string | null
  allowed_models?: string[]
  max_concurrency?: number
  hourly_token_limit?: number | null
  daily_token_limit?: number | null
  enabled?: boolean
  expires_at?: string | null
}

export interface GatewayHealthCheck {
  id: number
  node_id: string
  probe_type: GatewayProbeType
  success: boolean
  latency_ms: number
  status_code: number | null
  error: string | null
  detail: Record<string, unknown>
  created_at: string
}

export interface GatewayNodeProbeResult {
  node: GatewayNode
  checks: GatewayHealthCheck[]
}

export interface GatewayValidationError {
  code: string
  message: string
  resource_type: string | null
  resource_id: string | null
}

export interface GatewayDraftValidation {
  valid: boolean
  errors: GatewayValidationError[]
  warnings: string[]
  counts: Record<string, number>
}

export interface GatewayConfigVersion {
  id: number
  version: number
  status: 'CURRENT' | 'SUPERSEDED' | 'PENDING' | 'FAILED'
  source_version: number | null
  note: string
  published_by: string
  published_at: string
  created_at: string
}

export interface GatewayConfigVersionDetail extends GatewayConfigVersion {
  snapshot: Record<string, unknown>
}

export interface GatewayAuditEvent {
  id: number
  actor: string
  actor_role: string
  action: string
  resource_type: string
  resource_id: string | null
  result: string
  before: Record<string, unknown>
  after: Record<string, unknown>
  created_at: string
}

export interface GatewayRequestLog {
  id: string
  key_id: string | null
  owner_id: string | null
  model: string | null
  pool_id: string | null
  node_id: string | null
  streaming: boolean
  retry_count: number
  status_code: number | null
  error_code: string | null
  stream_interrupted: boolean
  connect_ms: number | null
  ttfb_ms: number | null
  ttft_ms: number | null
  duration_ms: number | null
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  output_tps: number | null
  usage_known: boolean
  started_at: string
  finished_at: string | null
}

export interface GatewayRequestPage {
  items: GatewayRequestLog[]
  total: number
  page: number
  page_size: number
}

export interface GatewayLatencyStats {
  avg: number | null
  p50: number | null
  p95: number | null
}

export interface GatewayStatBucket {
  bucket_start: string
  requests: number
  success: number
  errors: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  unknown_usage_requests: number
}

export interface GatewayScopeStats {
  scope: GatewayStatsScope
  scope_id: string | null
  window: GatewayStatsWindow
  window_start: string
  window_end: string
  requests: number
  success: number
  errors: number
  success_rate: number | null
  input_tokens: number
  output_tokens: number
  total_tokens: number
  unknown_usage_requests: number
  qps: number
  active: number
  peak_concurrency: number
  connect_ms: GatewayLatencyStats
  ttfb_ms: GatewayLatencyStats
  ttft_ms: GatewayLatencyStats
  duration_ms: GatewayLatencyStats
  output_tps: GatewayLatencyStats
  trend: GatewayStatBucket[]
}

export interface GatewayInstance {
  instance_id: string
  status: string
  app_version: string | null
  config_version: number | null
  pid: number | null
  started_at: string | null
  updated_at: string | null
  uptime_seconds: number | null
  age_seconds: number | null
  requests: number | null
  errors: number | null
  active: number | null
  cpu_percent: number | null
  memory_bytes: number | null
}

export interface GatewayRequestQuery {
  request_id?: string
  node_id?: string
  model?: string
  key_id?: string
  status_code?: number
  error_code?: string
  page?: number
  page_size?: number
}

export class GatewayApiError extends Error {
  errors: GatewayValidationError[]
  status: number
  constructor(message: string, status: number, errors: GatewayValidationError[] = []) {
    super(message)
    this.name = 'GatewayApiError'
    this.status = status
    this.errors = errors
  }
}

// ── 凭据会话：控制面 Bearer 与 Gateway Key 仅存 sessionStorage 或内存 ──

function readSession(key: string): string {
  if (typeof window === 'undefined') return ''
  try {
    return window.sessionStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

function writeSession(key: string, value: string): void {
  if (typeof window === 'undefined') return
  try {
    if (value) window.sessionStorage.setItem(key, value)
    else window.sessionStorage.removeItem(key)
  } catch {
    /* 隐私模式下降级为内存态 */
  }
}

const memoryControlToken = ref('')
const memorySelfKey = ref('')

export function getGatewayToken(): string {
  return memoryControlToken.value || readSession(CONTROL_TOKEN_KEY)
}

export function setGatewayToken(token: string): void {
  memoryControlToken.value = token.trim()
  writeSession(CONTROL_TOKEN_KEY, memoryControlToken.value)
}

export function clearGatewayToken(): void {
  memoryControlToken.value = ''
  writeSession(CONTROL_TOKEN_KEY, '')
}

export function getSelfKey(): string {
  return memorySelfKey.value || readSession(SELF_KEY_KEY)
}

export function setSelfKey(key: string): void {
  memorySelfKey.value = key.trim()
  writeSession(SELF_KEY_KEY, memorySelfKey.value)
}

export function clearSelfKey(): void {
  memorySelfKey.value = ''
  writeSession(SELF_KEY_KEY, '')
}

function queryString(params: object): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

interface RequestOptions {
  method?: string
  body?: unknown
  identity?: 'control' | 'self' | 'none'
}

async function gatewayRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const identity = options.identity ?? 'control'
  const headers: Record<string, string> = {}
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (identity !== 'none') {
    const token = identity === 'self' ? getSelfKey() : getGatewayToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  })
  if (response.status === 204) return undefined as T
  const payload = await response.json().catch(() => ({ detail: response.statusText }))
  if (!response.ok) {
    throw new GatewayApiError(
      payload?.detail ?? '请求失败',
      response.status,
      Array.isArray(payload?.errors) ? payload.errors : [],
    )
  }
  return payload as T
}

export const gatewayApi = {
  permissions: () => gatewayRequest<GatewayPermissions>('/api/gateway/permissions'),

  // Pool
  pools: () => gatewayRequest<GatewayPool[]>('/api/gateway/pools'),
  createPool: (body: GatewayPoolWrite) =>
    gatewayRequest<GatewayPool>('/api/gateway/pools', { method: 'POST', body }),
  updatePool: (id: string, body: Partial<GatewayPoolWrite>) =>
    gatewayRequest<GatewayPool>(`/api/gateway/pools/${id}`, { method: 'PATCH', body }),
  deletePool: (id: string) => gatewayRequest<void>(`/api/gateway/pools/${id}`, { method: 'DELETE' }),

  // Node
  nodes: () => gatewayRequest<GatewayNode[]>('/api/gateway/nodes'),
  node: (id: string) => gatewayRequest<GatewayNode>(`/api/gateway/nodes/${id}`),
  createNode: (body: GatewayNodeWrite) =>
    gatewayRequest<GatewayNode>('/api/gateway/nodes', { method: 'POST', body }),
  updateNode: (id: string, body: GatewayNodeWrite) =>
    gatewayRequest<GatewayNode>(`/api/gateway/nodes/${id}`, { method: 'PATCH', body }),
  deleteNode: (id: string) =>
    gatewayRequest<void>(`/api/gateway/nodes/${id}`, { method: 'DELETE' }),
  drainNode: (id: string) =>
    gatewayRequest<GatewayNode>(`/api/gateway/nodes/${id}/drain`, { method: 'POST' }),
  activateNode: (id: string) =>
    gatewayRequest<GatewayNode>(`/api/gateway/nodes/${id}/activate`, { method: 'POST' }),
  probeNode: (id: string, probeTypes: GatewayProbeType[]) =>
    gatewayRequest<GatewayNodeProbeResult>(`/api/gateway/nodes/${id}/probe`, {
      method: 'POST',
      body: { probe_types: probeTypes },
    }),

  // Route
  routes: () => gatewayRequest<GatewayRoute[]>('/api/gateway/routes'),
  createRoute: (body: GatewayRouteWrite) =>
    gatewayRequest<GatewayRoute>('/api/gateway/routes', { method: 'POST', body }),
  updateRoute: (id: string, body: Partial<GatewayRouteWrite>) =>
    gatewayRequest<GatewayRoute>(`/api/gateway/routes/${id}`, { method: 'PATCH', body }),
  deleteRoute: (id: string) =>
    gatewayRequest<void>(`/api/gateway/routes/${id}`, { method: 'DELETE' }),

  // Key
  keys: () => gatewayRequest<GatewayKey[]>('/api/gateway/keys'),
  createKey: (body: GatewayKeyWrite) =>
    gatewayRequest<GatewayKeyCreated>('/api/gateway/keys', { method: 'POST', body }),
  updateKey: (id: string, body: Partial<GatewayKeyWrite>) =>
    gatewayRequest<GatewayKey>(`/api/gateway/keys/${id}`, { method: 'PATCH', body }),
  revokeKey: (id: string) =>
    gatewayRequest<GatewayKey>(`/api/gateway/keys/${id}`, { method: 'DELETE' }),

  // 草稿 / 版本 / 审计
  draftValidation: () => gatewayRequest<GatewayDraftValidation>('/api/gateway/config/draft'),
  versions: () => gatewayRequest<GatewayConfigVersion[]>('/api/gateway/config/versions'),
  version: (version: number) =>
    gatewayRequest<GatewayConfigVersionDetail>(`/api/gateway/config/versions/${version}`),
  publish: (note: string) =>
    gatewayRequest<GatewayConfigVersion>('/api/gateway/config/publish', {
      method: 'POST',
      body: { note },
    }),
  rollback: (version: number) =>
    gatewayRequest<GatewayConfigVersion>('/api/gateway/config/rollback', {
      method: 'POST',
      body: { version },
    }),
  reconcile: () =>
    gatewayRequest<{ changed: number }>('/api/gateway/config/reconcile', { method: 'POST' }),
  audits: (params: { resource_type?: string; resource_id?: string; limit?: number } = {}) =>
    gatewayRequest<GatewayAuditEvent[]>(`/api/gateway/audits${queryString(params)}`),

  // 观测
  requests: (query: GatewayRequestQuery = {}) =>
    gatewayRequest<GatewayRequestPage>(`/api/gateway/requests${queryString(query)}`),
  stats: (scope: GatewayStatsScope, window: GatewayStatsWindow, scopeId?: string) =>
    gatewayRequest<GatewayScopeStats>(
      `/api/gateway/stats${queryString({ scope, scope_id: scopeId, window })}`,
    ),
  instances: () => gatewayRequest<GatewayInstance[]>('/api/gateway/instances'),
  healthChecks: (nodeId: string, limit = 100) =>
    gatewayRequest<GatewayHealthCheck[]>(
      `/api/gateway/nodes/${nodeId}/health-checks${queryString({ limit })}`,
    ),

  // Key 自助：使用 Gateway Key 自身鉴权，只看自己的用量
  selfRequests: (query: GatewayRequestQuery = {}) =>
    gatewayRequest<GatewayRequestPage>(`/api/gateway/self/requests${queryString(query)}`, {
      identity: 'self',
    }),
  selfStats: (window: GatewayStatsWindow) =>
    gatewayRequest<GatewayScopeStats>(`/api/gateway/self/stats${queryString({ window })}`, {
      identity: 'self',
    }),
}