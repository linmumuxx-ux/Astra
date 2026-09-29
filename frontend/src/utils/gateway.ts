// API 中转文案与格式化：只做展示映射，指标数值全部直接取自后端契约。

const fallback = (value: string) => (value ? value : '—')

export const configStateLabel = (value: string) =>
  value === 'ENABLED' ? '启用' : value === 'DISABLED' ? '禁用' : fallback(value)

export const schedulingStateLabel = (value: string) =>
  ({ ACTIVE: '调度中', DRAINING: '安全下线', BLOCKED: '已阻止' }[value] ?? fallback(value))

export const healthStateLabel = (value: string) =>
  ({
    UNKNOWN: '未探测',
    CHECKING: '探测中',
    HEALTHY: '健康',
    DEGRADED: '降级',
    UNHEALTHY: '异常',
  }[value] ?? fallback(value))

export const quotaPolicyLabel = (value: string) =>
  ({ STOP: '停止新请求', ALERT: '仅告警', RECORD: '仅记录' }[value] ?? fallback(value))

export const probeTypeLabel = (value: string) =>
  ({ NETWORK: '网络', SERVICE: '服务', MODEL: '模型', STREAM: 'SSE 流式' }[value] ?? fallback(value))

export const authTypeLabel = (value: string) =>
  ({ BEARER: 'Bearer Token', HEADER: '自定义 Header', NONE: '无认证' }[value] ?? fallback(value))

export type GatewayAuthenticationResult = 'PASS' | 'FAIL' | null

// 认证结果从真实模型调用（MODEL 探测）推断，不新增独立探测或持久字段：
// 模型调用成功即认证 PASS；被下游以 401/403 拒绝即 FAIL；未探测或其它失败为未知。
export function authenticationResult(
  checks: Array<{ probe_type: string; success: boolean; status_code: number | null }>,
): GatewayAuthenticationResult {
  const model = checks.find((check) => check.probe_type === 'MODEL')
  if (!model) return null
  if (model.success) return 'PASS'
  if (model.status_code === 401 || model.status_code === 403) return 'FAIL'
  return null
}

export const authenticationLabel = (value: GatewayAuthenticationResult) =>
  value === 'PASS' ? '认证 PASS' : value === 'FAIL' ? '认证 FAIL' : '认证未验证'

export function authenticationTone(value: GatewayAuthenticationResult): GatewayTone {
  if (value === 'PASS') return 'success'
  if (value === 'FAIL') return 'danger'
  return 'neutral'
}

export const versionStatusLabel = (value: string) =>
  ({
    CURRENT: '当前版本',
    PENDING: '待确认',
    FAILED: '发布失败',
    SUPERSEDED: '历史版本',
  }[value] ?? fallback(value))

export type GatewayTone = 'info' | 'success' | 'warning' | 'danger' | 'neutral'

export function healthTone(value: string): GatewayTone {
  if (value === 'HEALTHY') return 'success'
  if (value === 'DEGRADED') return 'warning'
  if (value === 'UNHEALTHY') return 'danger'
  if (value === 'CHECKING') return 'info'
  return 'neutral'
}

export function schedulingTone(value: string): GatewayTone {
  if (value === 'ACTIVE') return 'success'
  if (value === 'DRAINING') return 'warning'
  if (value === 'BLOCKED') return 'danger'
  return 'neutral'
}

export function versionTone(value: string): GatewayTone {
  if (value === 'CURRENT') return 'success'
  if (value === 'PENDING') return 'warning'
  if (value === 'FAILED') return 'danger'
  return 'neutral'
}

const parseApiTime = (value: string) =>
  new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`)

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return parseApiTime(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return '—'
  const minutes = Math.max(0, Math.floor((Date.now() - parseApiTime(value).getTime()) / 60_000))
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (minutes < 1_440) return `${Math.floor(minutes / 60)} 小时前`
  return parseApiTime(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

export function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(value >= 10 ? 0 : 1)} 秒`
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(0)} MB`
  if (value >= 1024) return `${(value / 1024).toFixed(0)} KB`
  return `${value} B`
}

export function formatPercent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return '—'
  return `${(ratio * 100).toFixed(ratio >= 0.9995 ? 0 : 1)}%`
}

export function tokenLimitText(value: number | null | undefined): string {
  if (value === null || value === undefined) return '不限'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`
  return String(value)
}

export function parseNumberList(value: string): string[] {
  return value
    .split(/[\n,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}