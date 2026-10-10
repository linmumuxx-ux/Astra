import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '@/api/client'
import type { DashboardActivity, DashboardAttention, DashboardEmployees, DashboardOverview } from '@/api/types'
import { useAstraStore } from '@/stores/astra'

interface SectionState<T> { data: T | null; loading: boolean; error: string; updatedAt: Date | null }
const section = <T>(): SectionState<T> => reactive({ data: null, loading: true, error: '', updatedAt: null }) as SectionState<T>

/** 只读取现有首页聚合接口，不探测员工 Server，也不管理任何执行状态。 */
export function useOfficeDashboard() {
  const store = useAstraStore()
  const overview = section<DashboardOverview>()
  const employees = section<DashboardEmployees>()
  const attention = section<DashboardAttention>()
  const activity = section<DashboardActivity>()
  const refreshing = ref(false)
  const visible = ref(!document.hidden)
  const snapshotReady = ref(false)
  let snapshotGeneration = 0
  let active = true
  let queued = false
  let eventTimer = 0
  let pollTimer = 0

  async function loadSection<T>(state: SectionState<T>, request: () => Promise<T>) {
    if (!state.data) state.loading = true
    // 请求进行中保留上次错误，成功后才恢复动画与可信状态。
    try {
      const next = await request()
      if (!active) return false
      state.data = next
      state.error = ''
      state.updatedAt = new Date()
      return true
    } catch (error) {
      if (active) state.error = error instanceof Error ? error.message : '数据加载失败'
      return false
    } finally {
      if (active) state.loading = false
    }
  }

  async function refreshDashboard() {
    if (!active) return
    if (refreshing.value) { queued = true; return }
    window.clearTimeout(eventTimer)
    eventTimer = 0
    refreshing.value = true
    queued = false
    const generation = snapshotGeneration
    const results = await Promise.all([
      loadSection(overview, api.dashboardOverview), loadSection(employees, api.dashboardEmployees),
      loadSection(attention, api.dashboardAttention), loadSection(activity, api.dashboardActivity),
    ])
    if (generation === snapshotGeneration && results[1] && store.realtimeConnected && visible.value) snapshotReady.value = true
    refreshing.value = false
    if (queued && active && visible.value) void refreshDashboard()
  }

  function scheduleRefresh() {
    if (!visible.value) { queued = true; return }
    if (refreshing.value) { queued = true; return }
    if (!eventTimer) eventTimer = window.setTimeout(() => { eventTimer = 0; void refreshDashboard() }, 350)
  }

  function handleVisibility() {
    visible.value = !document.hidden
    if (!visible.value) { snapshotGeneration += 1; snapshotReady.value = false }
    if (visible.value) scheduleRefresh()
  }

  watch(() => store.lastEvent, scheduleRefresh)
  // 导航徽标复用这一份成功的首页快照，不额外读取全量任务。
  watch(() => overview.data, (value) => { if (value) store.homeOverview = value })
  watch(() => store.realtimeConnected, (connected) => {
    if (connected) scheduleRefresh()
    else { snapshotGeneration += 1; snapshotReady.value = false }
  })

  onMounted(() => {
    void refreshDashboard()
    // 原生轮结束可能没有 Task 业务事件；只补刷聚合快照，不推断终态。
    pollTimer = window.setInterval(() => { if (visible.value) scheduleRefresh() }, 15_000)
    document.addEventListener('visibilitychange', handleVisibility)
  })
  onBeforeUnmount(() => {
    active = false
    window.clearTimeout(eventTimer)
    window.clearInterval(pollTimer)
    document.removeEventListener('visibilitychange', handleVisibility)
  })

  const live = computed(() => snapshotReady.value && store.realtimeConnected && visible.value && !!employees.data && !employees.error)
  const partialError = computed(() => [overview, employees, attention, activity].some(state => !!state.error))
  const updatedText = computed(() => employees.updatedAt?.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }) ?? '—')
  return { overview, employees, attention, activity, refreshing, live, partialError, updatedText, refreshDashboard, connected: computed(() => store.realtimeConnected) }
}
