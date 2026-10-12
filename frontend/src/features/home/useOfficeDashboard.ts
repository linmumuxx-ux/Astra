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
  let active = true
  let controller: AbortController | null = null

  async function loadSection<T>(state: SectionState<T>, request: () => Promise<T>) {
    if (!state.data) state.loading = true
    // 请求进行中保留上次错误，成功后才清除快照失效提示。
    try {
      const next = await request()
      if (!active) return false
      state.data = next
      state.error = ''
      state.updatedAt = new Date()
      return true
    } catch (error) {
      if (active) state.error = controller?.signal.aborted ? '请求超时，请重试' : error instanceof Error ? error.message : '数据加载失败'
      return false
    } finally {
      if (active) state.loading = false
    }
  }

  async function refreshDashboard() {
    if (!active) return
    if (refreshing.value) return
    refreshing.value = true
    controller = new AbortController()
    const signal = controller.signal
    const timeout = window.setTimeout(() => controller?.abort(), 15_000)
    try {
      await Promise.all([
        loadSection(overview, () => api.dashboardOverview(signal)), loadSection(employees, () => api.dashboardEmployees(signal)),
        loadSection(attention, () => api.dashboardAttention(signal)), loadSection(activity, () => api.dashboardActivity(signal)),
      ])
    } finally {
      window.clearTimeout(timeout)
      controller = null
      refreshing.value = false
    }
  }

  // 导航徽标复用这一份成功的首页快照，不额外读取全量任务。
  watch(() => overview.data, (value) => { if (value) store.homeOverview = value })
  onMounted(() => { void refreshDashboard() })
  onBeforeUnmount(() => { active = false; controller?.abort() })

  const partialError = computed(() => [overview, employees, attention, activity].some(state => !!state.error))
  const updatedText = computed(() => employees.updatedAt?.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) ?? '—')
  return { overview, employees, attention, activity, refreshing, partialError, updatedText, refreshDashboard }
}
