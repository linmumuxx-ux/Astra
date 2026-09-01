import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import type { AstraEvent, Employee, Metrics, Task, TaskCategory } from '@/api/types'

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
  let eventSource: EventSource | null = null
  let refreshTimer = 0

  const activeTasks = computed(() =>
    tasks.value.filter(
      (task) =>
        task.employee_id &&
        ['READY', 'RUNNING', 'WAIT_HUMAN', 'SUSPENDED', 'EXECUTION_ERROR'].includes(task.status),
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

  function connectEvents() {
    if (eventSource) return
    const apiBase = import.meta.env.VITE_API_BASE ?? ''
    eventSource = new EventSource(`${apiBase}/api/events/stream`)
    eventSource.addEventListener('connected', () => { realtimeConnected.value = true })
    eventSource.addEventListener('update', () => {
      window.clearTimeout(refreshTimer)
      refreshTimer = window.setTimeout(refresh, 250)
    })
    eventSource.onerror = () => { realtimeConnected.value = false }
  }

  function disconnectEvents() {
    eventSource?.close()
    eventSource = null
    realtimeConnected.value = false
    window.clearTimeout(refreshTimer)
  }

  return { metrics, employees, tasks, categories, events, activeTasks, loading, error, lastUpdated, realtimeConnected, refresh, connectEvents, disconnectEvents }
})
