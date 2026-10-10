import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import type { AstraEvent, DashboardOverview, Employee, Metrics, Task, TaskCategory } from '@/api/types'

export const useAstraStore = defineStore('astra', () => {
  const metrics = ref<Metrics | null>(null)
  const employees = ref<Employee[]>([])
  const tasks = ref<Task[]>([])
  const categories = ref<TaskCategory[]>([])
  const events = ref<AstraEvent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const lastUpdated = ref<Date | null>(null)
  const realtimeConnected = ref(false)
  const lastEvent = ref<AstraEvent | null>(null)
  const homeOverview = ref<DashboardOverview | null>(null)
  const pendingTaskIds = new Set<string>()
  let pendingFullRefresh = false
  let refreshingEvents = false
  let eventSource: EventSource | null = null
  let refreshTimer = 0
  let refreshStoreOnEvents = true

  const activeTasks = computed(() =>
    tasks.value.filter(
      (task) =>
        task.employee_id &&
        ['PENDING', 'RUNNING', 'WAITING', 'FAILED'].includes(task.status),
    ),
  )

  async function refresh() {
    loading.value = true
    try {
      const [metricsValue, employeeValue, taskValue, categoryValue, eventValue] = await Promise.all([
        api.metrics(), api.employees(), api.tasks(), api.categories(), api.events(40),
      ])
      metrics.value = metricsValue
      employees.value = employeeValue
      tasks.value = taskValue
      categories.value = categoryValue
      events.value = eventValue
      error.value = null
      lastUpdated.value = new Date()
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '控制台数据加载失败'
    } finally {
      loading.value = false
    }
  }

  function connectEvents(refreshData = true) {
    // 首页只消费事件和连接状态，由自己的聚合接口刷新；全站始终复用一条 SSE。
    refreshStoreOnEvents = refreshData
    if (!refreshData) {
      pendingTaskIds.clear()
      pendingFullRefresh = false
      window.clearTimeout(refreshTimer)
      refreshTimer = 0
    }
    if (eventSource) return
    const apiBase = import.meta.env.VITE_API_BASE ?? ''
    eventSource = new EventSource(`${apiBase}/api/events/stream`)
    let connectedBefore = false
    eventSource.addEventListener('connected', () => {
      realtimeConnected.value = true
      if (connectedBefore && refreshStoreOnEvents) {
        pendingFullRefresh = true
        if (!refreshTimer) refreshTimer = window.setTimeout(refreshTaskEvents, 250)
      }
      connectedBefore = true
    })
    eventSource.addEventListener('update', event => {
      const raw = JSON.parse((event as MessageEvent).data)
      const value = { ...raw, event_type: raw.type } as AstraEvent
      events.value = [value, ...events.value.filter(item => item.id !== value.id)].slice(0, 40)
      lastEvent.value = value
      if (!refreshStoreOnEvents) return
      if (value.task_id) {
        pendingTaskIds.add(value.task_id)
      } else {
        pendingFullRefresh = true
      }
      if (!refreshTimer) refreshTimer = window.setTimeout(refreshTaskEvents, 250)
    })
    eventSource.onerror = () => { realtimeConnected.value = false }
  }

  async function refreshTaskEvents() {
    refreshTimer = 0
    if (refreshingEvents || (!pendingTaskIds.size && !pendingFullRefresh)) return
    refreshingEvents = true
    const ids = [...pendingTaskIds]; pendingTaskIds.clear()
    const fullRefresh = pendingFullRefresh; pendingFullRefresh = false
    try {
      if (fullRefresh) { await refresh(); return }
      const [nextMetrics, nextEmployees, updated] = await Promise.all([
        api.metrics(), api.employees(), Promise.all(ids.map(id => api.task(id).catch(() => null))),
      ])
      metrics.value = nextMetrics; employees.value = nextEmployees
      for (let index = 0; index < ids.length; index++) {
        const next = updated[index]
        const position = tasks.value.findIndex(item => item.id === ids[index])
        if (next && position >= 0) tasks.value[position] = next
        else if (next) tasks.value.unshift(next)
      }
      lastUpdated.value = new Date()
    } catch (reason) { error.value = reason instanceof Error ? reason.message : '任务状态刷新失败' }
    finally {
      refreshingEvents = false
      if ((pendingTaskIds.size || pendingFullRefresh) && !refreshTimer) refreshTimer = window.setTimeout(refreshTaskEvents, 250)
    }
  }

  function disconnectEvents() {
    eventSource?.close()
    eventSource = null
    realtimeConnected.value = false
    window.clearTimeout(refreshTimer)
    refreshTimer = 0
  }

  return { metrics, employees, tasks, categories, events, activeTasks, loading, error, lastUpdated, realtimeConnected, lastEvent, homeOverview, refresh, connectEvents, disconnectEvents }
})
