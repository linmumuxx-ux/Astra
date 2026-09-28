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

        <RouterLink class="header-notification" to="/interventions" aria-label="消息通知">
          <el-badge :value="pendingCount" :max="9" :hidden="!pendingCount">
            <Bell :size="19" />
          </el-badge>
        </RouterLink>

        <el-dropdown trigger="click" placement="bottom-end" @command="handleAdminCommand">
          <button class="header-user" type="button" aria-label="管理员菜单">
            <span>NR</span><strong>管理员</strong><ChevronDown :size="15" />
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="settings">配置中心</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>

    <el-main class="app-main">
      <div v-if="store.error && route.path !== '/'" class="error-banner">
        <TriangleAlert :size="17" />{{ store.error }}<button type="button" @click="store.refresh()">重试</button>
      </div>
      <RouterView />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { BookOpen, ChevronDown, ClipboardList, House, Search, Settings, TriangleAlert, UserRound, Waypoints, Bell } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import {
  ElBadge,
  ElContainer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElHeader,
  ElInput,
  ElMain,
  ElMenu,
  ElMenuItem,
} from 'element-plus'
import AstraLogo from '@/components/astra/AstraLogo.vue'
import { useAstraStore } from '@/stores/astra'

const route = useRoute()
const router = useRouter()
const store = useAstraStore()
const searchInput = ref('')

const navigation = [
  { to: '/', label: '首页', icon: House },
  { to: '/employees', label: '数字员工', icon: UserRound },
  { to: '/tasks', label: '任务管理', icon: ClipboardList },
  { to: '/library', label: '数字图书馆', icon: BookOpen },
  { to: '/gateway', label: 'API 中转', icon: Waypoints },
  { to: '/settings', label: '设置', icon: Settings },
]

const pendingCount = computed(() => store.tasks.filter((task) =>
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
  if (route.path === '/') searchInput.value = typeof value === 'string' ? value : ''
}, { immediate: true })
</script>

<style scoped>
.layout-header{--el-header-padding:0 16px;--el-header-height:68px;position:sticky;top:0;z-index:500;display:flex;align-items:center;gap:16px;background:rgba(255,255,255,.94);border-bottom:1px solid var(--astra-border);backdrop-filter:blur(14px)}
.brand-link{flex:none;display:block}.brand-link :deep(.logo-copy small){display:none}
.layout-nav{flex:1;min-width:0}
.layout-menu{--el-menu-base-level-padding:12px;--el-menu-horizontal-height:68px;width:100%;border-bottom:0;background:transparent}
.layout-menu :deep(.el-menu-item){gap:6px}
.layout-actions{flex:none;display:flex;align-items:center;gap:8px}
.global-search{width:180px}
.header-notification{display:inline-flex;align-items:center;justify-content:center;color:#4f6961}
.header-user{display:flex;align-items:center;gap:8px;height:42px;padding:0 7px;color:#203d35;border:0;border-radius:12px;background:transparent;cursor:pointer}
.header-user:hover{background:#f4f8f6}
.header-user>span{display:grid;place-items:center;width:34px;height:34px;color:#10875a;border-radius:50%;background:#dff4eb;font-weight:var(--astra-weight-bold)}
.header-user strong{font-size:var(--astra-font-body)}
.app-main{--el-main-padding:0}
@media(max-width:1120px){.global-search{width:150px}.header-user strong,.header-user>svg{display:none}}
@media(max-width:860px){.brand-link :deep(.logo-copy){display:none}}
</style>
