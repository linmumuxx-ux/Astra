<template>
  <div class="app-shell" data-testid="app-shell">
    <aside class="sidebar" :class="{ 'sidebar--open': navOpen }">
      <AstraLogo />
      <nav aria-label="主导航">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to" @click="navOpen = false">
          <component :is="item.icon" :size="17" /><span>{{ item.label }}</span>
          <span v-if="item.count" class="nav-count">{{ item.count }}</span>
        </RouterLink>
      </nav>
      <div class="sidebar__foot">
        <div class="system-live" :class="{ 'connection--offline': store.error }"><i />{{ store.error ? '数据连接异常' : '系统运行中' }}</div>
        <div class="admin"><span>NR</span><div><strong>Admin</strong><small>平台管理员</small></div></div>
      </div>
    </aside>
    <div v-if="navOpen" class="sidebar-backdrop" @click="navOpen = false" />
    <main>
      <header class="topbar">
        <button class="icon-button mobile-menu" aria-label="打开导航" @click="navOpen = true"><Menu :size="19" /></button>
        <div class="topbar__title"><h1>{{ route.meta.title }}</h1></div>
        <div class="topbar__actions">
          <span class="connection" :class="{ 'connection--offline': !connectionHealthy }"><i /> {{ connectionLabel }}</span>
          <button class="icon-button" aria-label="刷新" @click="refresh"><RefreshCw :size="18" :class="{ spin: store.loading }" /></button>
          <span class="clock">{{ clock }}</span>
        </div>
      </header>
      <div v-if="store.error" class="error-banner"><TriangleAlert :size="17" />{{ store.error }}<button @click="refresh">重试</button></div>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { Bot, CircleGauge, ClipboardList, Hand, History, Menu, RefreshCw, Settings, TriangleAlert } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import AstraLogo from '@/components/astra/AstraLogo.vue'
import { useAstraStore } from '@/stores/astra'

const route = useRoute()
const store = useAstraStore()
const navOpen = ref(false)
const now = ref(new Date())
let timer = 0
const clock = computed(() => new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(now.value))
const connectionHealthy = computed(() => store.realtimeConnected && !store.error)
const connectionLabel = computed(() => store.error ? '数据异常' : store.realtimeConnected ? '实时连接' : '重新连接')
const navigation = computed(() => [
  { to: '/', label: '总览', icon: CircleGauge },
  { to: '/employees', label: '数字员工', icon: Bot },
  { to: '/tasks', label: '任务中心', icon: ClipboardList, count: store.metrics?.running_tasks },
  { to: '/runs', label: '运行记录', icon: History },
  { to: '/interventions', label: '待处理', icon: Hand, count: store.tasks.filter((task) => ['WAIT_HUMAN', 'SUSPENDED', 'PENDING_CONFIRMATION', 'EXECUTION_ERROR'].includes(task.status) || task.inactivity_alert).length },
  { to: '/settings', label: '配置中心', icon: Settings },
])
const refresh = () => store.refresh()
onMounted(() => { store.refresh(); store.connectEvents(); timer = window.setInterval(() => { now.value = new Date() }, 1000) })
onBeforeUnmount(() => { window.clearInterval(timer); store.disconnectEvents() })
</script>
