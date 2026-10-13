import { computed, onScopeDispose, ref, shallowRef, watch, type Ref } from 'vue'
import type { Principal } from './types'

const base = (import.meta.env.VITE_API_BASE || '/api/v1').replace(/\/$/, '')
export const token = ref(sessionStorage.getItem('astra.access') || '')
export const principal = shallowRef<Principal | null>(null)
export const revision = ref(0)
export const connection = ref<'connecting' | 'connected' | 'disconnected' | 'forbidden' | 'offline'>('disconnected')
export const online = ref(navigator.onLine)
const pendingKeys = new Map<string, string>()
let refreshTimer: ReturnType<typeof setTimeout> | undefined

export class ApiError extends Error { constructor(public status: number, message: string) { super(message) } }
export function refresh() { clearTimeout(refreshTimer); refreshTimer = setTimeout(() => revision.value++, 160) }
export function setToken(value: string) { token.value = value.trim(); principal.value = null; pendingKeys.clear(); if (token.value) sessionStorage.setItem('astra.access', token.value); else sessionStorage.removeItem('astra.access') }
window.addEventListener('online', () => { online.value = true; refresh() })
window.addEventListener('offline', () => { online.value = false; connection.value = 'offline' })

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${token.value}`)
  headers.set('Accept', 'application/json')
  if (init.body) headers.set('Content-Type', 'application/json')
  let response: Response
  try { response = await fetch(`${base}${path}`, { ...init, headers, cache: 'no-store' }) }
  catch (error) { if (error instanceof DOMException && error.name === 'AbortError') throw error; throw new ApiError(0, '无法连接 Astra 服务，请检查网络后重试。') }
  if (!response.ok) {
    let detail = ''
    try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body) } catch { /* 非 JSON 错误由状态码呈现 */ }
    throw new ApiError(response.status, detail || ({ 401: '身份凭据无效或已过期，请重新连接。', 403: '当前身份没有访问此内容的权限。', 404: '内容不存在或当前服务未提供此能力。', 409: '内容已发生变化，请刷新后重试。' }[response.status] ?? `服务请求失败（${response.status}）`))
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

/** 传输失败保留同一请求的 operation key；只有明确成功才开始下一次业务操作。 */
export async function mutate<T = unknown>(path: string, data: unknown = {}, method = 'POST'): Promise<T> {
  const body = JSON.stringify(data)
  const fingerprint = `${method}:${path}:${body}`
  const key = pendingKeys.get(fingerprint) || crypto.randomUUID()
  pendingKeys.set(fingerprint, key)
  try { const result = await request<T>(path, { method, body, headers: { 'Idempotency-Key': key } }); pendingKeys.delete(fingerprint); refresh(); return result }
  catch (error) { if (error instanceof ApiError && error.status >= 400 && error.status < 500) pendingKeys.delete(fingerprint); throw error }
}

export function useResource<T>(path: string | Ref<string> | (() => string), initial: T) {
  const data = shallowRef<T>(initial)
  const loading = ref(false)
  const refreshing = ref(false)
  const error = shallowRef<ApiError | null>(null)
  let controller: AbortController | undefined
  let serial = 0
  let hasSnapshot = false, loadedPath = '', loadedToken = ''
  const resourcePath = computed(() => typeof path === 'function' ? path() : typeof path === 'string' ? path : path.value)
  async function load() {
    const current = ++serial
    controller?.abort()
    if (!token.value || !resourcePath.value) { data.value = initial; error.value = null; loading.value = false; refreshing.value = false; hasSnapshot = false; return }
    if (loadedPath !== resourcePath.value || loadedToken !== token.value) { hasSnapshot = false; data.value = initial; loadedPath = resourcePath.value; loadedToken = token.value }
    controller = new AbortController()
    loading.value = !hasSnapshot
    refreshing.value = hasSnapshot
    error.value = null
    try { const result = await request<T>(resourcePath.value, { signal: controller.signal }); if (current === serial) { data.value = result; hasSnapshot = true } }
    catch (caught) { if (current === serial && !(caught instanceof DOMException && caught.name === 'AbortError')) { error.value = caught as ApiError; data.value = initial; hasSnapshot = false } }
    finally { if (current === serial) { loading.value = false; refreshing.value = false } }
  }
  watch([resourcePath, token, revision], load, { immediate: true })
  onScopeDispose(() => { serial++; controller?.abort() })
  return { data, loading, refreshing, error, load }
}

/** 带认证 fetch SSE；游标仅定位事件，业务终态始终来自详情查询。 */
export function startEvents() {
  let disposed = false
  let controller: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let after = 0
  let delay = 1000
  let generation = 0
  async function connect(current: number) {
    if (disposed || current !== generation || !token.value) return
    if (!online.value) { connection.value = 'offline'; return }
    controller = new AbortController()
    connection.value = 'connecting'
    try {
      const response = await fetch(`${base}/events?after=${after}`, { headers: { Authorization: `Bearer ${token.value}`, Accept: 'text/event-stream' }, signal: controller.signal, cache: 'no-store' })
      if (!response.ok) throw new ApiError(response.status, '事件连接失败')
      if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) throw new ApiError(0, '事件服务未返回事件流')
      connection.value = 'connected'
      delay = 1000
      refresh()
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (!disposed && current === generation) {
        const chunk = await reader.read()
        if (chunk.done) break
        buffer += decoder.decode(chunk.value, { stream: true }).replace(/\r\n/g, '\n')
        let boundary: number
        while ((boundary = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2)
          const payload = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
          const id = frame.split('\n').find(line => line.startsWith('id:'))?.slice(3).trim()
          const eventType = frame.split('\n').find(line => line.startsWith('event:'))?.slice(6).trim()
          if (eventType === 'auth_revoked') { connection.value = 'forbidden'; setToken(''); await reader.cancel(); return }
          if (!payload) continue
          try { const event = JSON.parse(payload); const seq = Number(event.seq ?? id); if (Number.isFinite(seq) && seq > after) after = seq; if (event.type !== 'heartbeat') refresh() } catch { refresh() }
        }
      }
    } catch (error) {
      if (disposed || current !== generation || (error instanceof DOMException && error.name === 'AbortError')) return
      if (error instanceof ApiError && [401, 403].includes(error.status)) { connection.value = 'forbidden'; refresh(); return }
    }
    if (disposed || current !== generation) return
    connection.value = online.value ? 'disconnected' : 'offline'
    timer = setTimeout(() => connect(current), delay)
    delay = Math.min(delay * 2, 30000)
  }
  const stop = watch([token, online], (values, previous) => { generation++; controller?.abort(); clearTimeout(timer); if (!previous || values[0] !== previous[0]) after = 0; delay = 1000; if (token.value) void connect(generation) }, { immediate: true })
  return () => { disposed = true; stop(); controller?.abort(); clearTimeout(timer) }
}
