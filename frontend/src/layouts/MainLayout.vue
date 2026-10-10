<template>
  <el-container class="main-layout">
    <el-header class="layout-header">
      <RouterLink class="brand-link" to="/" aria-label="返回 NEXUS 首页">
        <AstraLogo />
      </RouterLink>

      <nav class="layout-nav" aria-label="主导航">
        <el-menu
          class="layout-menu"
          mode="horizontal"
          router
          :default-active="activeNav"
        >
          <el-menu-item v-for="item in navigation" :key="item.to" :index="item.to">
            <component :is="item.icon" :size="16" />
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-menu>
      </nav>

      <div class="layout-actions">
        <el-input
          v-model="searchInput"
          class="global-search"
          aria-label="全局搜索"
          placeholder="搜索数字员工 / 任务 / 知识…"
          clearable
          @keyup.enter="runSearch"
          @clear="clearSearch"
        >
          <template #prefix><Search :size="15" /></template>
        </el-input>

        <AssistantLauncher class="header-assistant" />

        <RouterLink class="header-notification" to="/interventions" aria-label="消息通知">
          <el-badge :value="pendingCount" :max="9" :hidden="!pendingCount">
            <Bell :size="19" />
          </el-badge>
        </RouterLink>

        <el-dropdown trigger="click" placement="bottom-end" @command="handleAdminCommand">
          <el-button class="header-user" text aria-label="管理员菜单">
            <el-avatar class="header-user__avatar" :size="34">NR</el-avatar>
            <el-text class="header-user__name">管理员</el-text>
            <ChevronDown :size="15" />
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="settings">配置中心</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>

    <el-main class="app-main">
      <el-alert
        v-if="store.error && route.path !== '/'"
        class="layout-error"
        type="error"
        show-icon
        :closable="false"
        :title="store.error"
      >
        <el-button type="primary" @click="store.refresh()">重试</el-button>
      </el-alert>
      <RouterView />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { Bell, BookOpen, ChevronDown, ClipboardList, House, Search, Settings, UserRound, Waypoints } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import {
  ElAlert,
  ElAvatar,
  ElBadge,
  ElButton,
  ElContainer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElHeader,
  ElInput,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElText,
} from 'element-plus'
import AstraLogo from '@/components/astra/AstraLogo.vue'
import AssistantLauncher from '@/features/assistant/AssistantLauncher.vue'
import { useAstraStore } from '@/stores/astra'

const route = useRoute()
const router = useRouter()
const store = useAstraStore()
const searchStorageKey = 'astra.global-search'

function routeSearchQuery(): string | null {
  return typeof route.query.q === 'string' ? route.query.q : null
}

// The global search term is the same across pages, so it survives route changes
// and reloads through sessionStorage; on the dashboard the URL q is truth and
// clears the stored term when it is removed (for example by the clear button).
const searchInput = ref(routeSearchQuery() ?? sessionStorage.getItem(searchStorageKey) ?? '')

const navigation = [
  { to: '/', label: '首页', icon: House },
  { to: '/employees', label: '数字员工', icon: UserRound },
  { to: '/tasks', label: '任务管理', icon: ClipboardList },
  { to: '/library', label: '数字图书馆', icon: BookOpen },
  { to: '/gateway', label: 'API 中转', icon: Waypoints },
  { to: '/settings', label: '设置', icon: Settings },
]

const pendingCount = computed(() => route.path === '/' ? store.homeOverview?.attention_total ?? 0 : store.tasks.filter((task) =>
  ['WAITING', 'FAILED'].includes(task.status) || task.inactivity_alert,
).length)

const activeNav = computed(() => {
  if (route.path === '/') return '/'
  const match = navigation.find((item) => item.to !== '/' && (route.path === item.to || route.path.startsWith(`${item.to}/`)))
  return match ? match.to : ''
})

function runSearch() {
  const query = searchInput.value.trim()
  router.push({ path: '/', query: query ? { q: query } : {} })
}

function clearSearch() {
  searchInput.value = ''
  if (route.path === '/' && route.query.q) router.replace({ path: '/' })
}

function handleAdminCommand(command: string) {
  if (command === 'settings') router.push('/settings')
}

watch(() => route.query.q, (value) => {
  if (typeof value === 'string') searchInput.value = value
  else if (route.path === '/') searchInput.value = ''
}, { immediate: true })

watch(searchInput, (value) => {
  if (value) sessionStorage.setItem(searchStorageKey, value)
  else sessionStorage.removeItem(searchStorageKey)
})
</script>

<style scoped>
.layout-header{--el-header-padding:0 16px;--el-header-height:68px;position:sticky;top:0;z-index:500;display:flex;align-items:center;gap:16px;background:var(--astra-bg-panel);border-bottom:1px solid var(--astra-border)}
.brand-link{flex:none;display:block}.brand-link :deep(.logo-copy small){display:none}
.layout-nav{flex:1;min-width:0}
.layout-menu{--el-menu-base-level-padding:12px;--el-menu-horizontal-height:68px;width:100%;border-bottom:0;background:transparent}
.layout-menu :deep(.el-menu-item){gap:6px}
.layout-actions{flex:none;display:flex;align-items:center;gap:8px}
.global-search{width:180px}
.header-notification,.header-assistant{display:inline-flex;align-items:center;justify-content:center;color:#4f6961}
.header-assistant:hover{color:var(--astra-primary-bright)}
.header-user{gap:8px;padding:0 7px}
.header-user__avatar{--el-avatar-bg-color:var(--astra-primary-soft);--el-avatar-text-color:var(--astra-primary-bright)}
.app-main{--el-main-padding:0}
.layout-error{margin:12px 16px 0}
@media(max-width:1120px){.global-search{width:150px}.header-user__name,.header-user svg{display:none}}
@media(max-width:860px){.brand-link :deep(.logo-copy){display:none}}
</style>
