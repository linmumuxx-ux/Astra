<template>
  <div class="app-shell" data-testid="app-shell">
    <header class="global-header">
      <RouterLink class="brand-link" to="/" aria-label="返回 NEXUS 首页" @click="navOpen = false">
        <AstraLogo />
      </RouterLink>

      <button class="mobile-nav-trigger" type="button" :aria-expanded="navOpen" aria-label="打开主导航" @click="navOpen = !navOpen">
        <X v-if="navOpen" :size="20" />
        <Menu v-else :size="20" />
      </button>

      <nav class="top-navigation" :class="{ 'top-navigation--open': navOpen }" aria-label="主导航">
        <RouterLink
          v-for="item in navigation"
          :key="item.to"
          class="top-navigation__link"
          :class="{ active: isNavActive(item.to) }"
          :to="item.to"
          @click="navOpen = false"
        >
          <component :is="item.icon" :size="17" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="global-header__actions">
        <form class="global-search" role="search" @submit.prevent="runSearch">
          <Search :size="16" />
          <input v-model="searchInput" aria-label="全局搜索" placeholder="搜索数字员工 / 任务 / 知识…" />
          <button v-if="searchInput" type="button" aria-label="清空搜索" @click="clearSearch"><X :size="14" /></button>
        </form>
        <RouterLink class="header-icon-button header-notification" to="/interventions" aria-label="消息通知">
          <Bell :size="19" /><b v-if="pendingCount">{{ pendingCount > 9 ? '9+' : pendingCount }}</b>
        </RouterLink>
        <button class="header-user" type="button" aria-label="管理员菜单">
          <span>NR</span><strong>管理员</strong><ChevronDown :size="15" />
        </button>
      </div>
    </header>

    <main class="app-main">
      <div v-if="store.error && route.path !== '/'" class="error-banner"><TriangleAlert :size="17" />{{ store.error }}<button @click="refresh">重试</button></div>
      <RouterView />
    </main>

    <AssistantLauncher />
    <AssistantDrawer />
  </div>
</template>

<script setup lang="ts">
import { Bell, BookOpen, ChevronDown, ClipboardList, House, Menu, Search, Settings, TriangleAlert, UserRound, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import AstraLogo from '@/components/astra/AstraLogo.vue'
import AssistantDrawer from '@/features/assistant/AssistantDrawer.vue'
import AssistantLauncher from '@/features/assistant/AssistantLauncher.vue'
import { useAstraStore } from '@/stores/astra'

const route = useRoute()
const router = useRouter()
const store = useAstraStore()
const navOpen = ref(false)
const searchInput = ref('')
const pendingCount = computed(() => store.tasks.filter((task) =>
  ['WAITING', 'FAILED'].includes(task.status) || task.inactivity_alert,
).length)

const navigation = computed(() => [
  { to: '/', label: '首页', icon: House },
  { to: '/employees', label: '数字员工', icon: UserRound },
  { to: '/tasks', label: '任务管理', icon: ClipboardList },
  { to: '/library', label: '数字图书馆', icon: BookOpen },
  { to: '/settings', label: '设置', icon: Settings },
])

function isNavActive(path: string) {
  return path === '/' ? route.path === '/' : route.path === path || route.path.startsWith(`${path}/`)
}

function runSearch() {
  const query = searchInput.value.trim()
  router.push({ path: '/', query: query ? { q: query } : {} })
  navOpen.value = false
}

function clearSearch() {
  searchInput.value = ''
  if (route.path === '/' && route.query.q) router.replace({ path: '/' })
}

function refresh() { store.refresh() }

watch(() => route.query.q, (value) => {
  if (route.path === '/') searchInput.value = typeof value === 'string' ? value : ''
}, { immediate: true })

watch(() => route.path, (path, previous) => {
  if (path === '/') {
    store.disconnectEvents()
    return
  }
  store.connectEvents()
  if (previous === '/' && !store.loading) store.refresh()
})

onMounted(() => {
  if (route.path !== '/') {
    if (!store.loading && !store.lastUpdated) store.refresh()
    store.connectEvents()
  }
})
onBeforeUnmount(() => store.disconnectEvents())
</script>

<style scoped>
.app-shell{display:block;min-height:100vh;background:var(--astra-bg-base)}
.global-header{position:sticky;top:0;z-index:500;display:flex;align-items:center;height:68px;padding:0 22px;border-bottom:1px solid rgba(197,216,207,.82);background:rgba(255,255,255,.94);box-shadow:0 5px 24px rgba(48,83,70,.055);backdrop-filter:blur(18px)}
.brand-link{display:block;flex:none;margin-right:26px}.brand-link :deep(.logo){gap:9px}.brand-link :deep(.logo-mark){width:36px;height:36px}.brand-link :deep(.logo-copy small){display:none}.brand-link :deep(.logo-copy strong){font-size:var(--astra-font-section);color:#0d2823}
.top-navigation{display:flex;align-self:stretch;align-items:center;gap:3px;min-width:0}.top-navigation__link{display:flex;align-items:center;gap:7px;height:44px;padding:0 11px;color:#405d56;border-radius:9px;font-size:var(--astra-font-label);font-weight: var(--astra-weight-bold);white-space:nowrap;transition:color .16s ease,background-color .16s ease}.top-navigation__link:hover{color:#087a4c;background:rgba(22,159,101,.055)}.top-navigation__link.active{color:#08a66e;background:#e1f7ef;font-weight: var(--astra-weight-bold)}
.global-header__actions{display:flex;align-items:center;gap:8px;margin-left:auto}.global-search{display:flex;align-items:center;gap:8px;width:min(205px,16vw);height:38px;padding:0 11px;color:#6b817b;border:1px solid transparent;border-radius:20px;background:#f1f6f4;transition:border-color .16s ease,background-color .16s ease}.global-search:focus-within{border-color:var(--astra-primary-border);background:#fff}.global-search input{min-width:0;width:100%;padding:0;color:var(--astra-text-primary);border:0;outline:0;background:transparent;font-size:var(--astra-font-body)}.global-search button{display:grid;place-items:center;width:23px;height:23px;padding:0;color:var(--astra-text-muted);border:0;border-radius:50%;background:transparent;cursor:pointer}.header-icon-button{position:relative;display:grid;place-items:center;width:38px;height:38px;padding:0;color:#4f6961;border:0;border-radius:11px;background:transparent;cursor:pointer}.header-icon-button:hover{color:var(--astra-primary);background:var(--astra-primary-soft)}.header-notification b{position:absolute;top:1px;right:0;display:grid;place-items:center;min-width:18px;height:18px;padding:0 4px;color:#fff;border:2px solid #fff;border-radius:10px;background:var(--astra-danger);font-size:var(--astra-font-micro)}.header-user{display:flex;align-items:center;gap:8px;height:42px;margin-left:2px;padding:0 7px 0 3px;color:#203d35;border:0;border-radius:12px;background:transparent;cursor:pointer}.header-user:hover{background:#f4f8f6}.header-user>span{display:grid;place-items:center;width:36px;height:36px;color:#10875a;border-radius:50%;background:#dff4eb;font-size:var(--astra-font-body);font-weight: var(--astra-weight-bold)}.header-user strong{font-size:var(--astra-font-body)}.mobile-nav-trigger{display:none;place-items:center;width:38px;height:38px;margin-left:auto;color:var(--astra-text-secondary);border:0;border-radius:10px;background:#f0f6f3;cursor:pointer}.app-main{min-width:0}.error-banner{margin:12px 22px 0}
@media(max-width:1320px){.global-header{padding-inline:16px}.brand-link{margin-right:12px}.top-navigation__link{padding-inline:9px}.global-search{width:190px}.header-user strong,.header-user>svg{display:none}}
@media(max-width:1080px){.global-search{width:210px}.top-navigation{position:fixed;top:68px;right:12px;left:12px;display:none;grid-template-columns:repeat(2,minmax(0,1fr));height:auto;padding:10px;border:1px solid var(--astra-border);border-radius:14px;background:rgba(255,255,255,.98);box-shadow:0 18px 45px rgba(30,65,53,.16)}.top-navigation--open{display:grid}.top-navigation__link{min-height:43px;border-radius:9px}.top-navigation__link.active{background:var(--astra-primary-soft)}.mobile-nav-trigger{display:grid}.global-header__actions{margin-left:10px}}
@media(max-width:680px){.global-header{height:60px;padding-inline:10px}.brand-link{margin-right:0}.brand-link :deep(.logo-copy){display:none}.brand-link :deep(.logo-mark){width:32px;height:32px;transform:scale(.88)}.mobile-nav-trigger{margin-left:auto}.global-header__actions{min-width:0;margin-left:5px}.global-search{position:static;display:flex;width:min(44vw,190px);height:36px;background:#f1f6f4;box-shadow:none}.header-user{display:none}.top-navigation{top:60px}.error-banner{margin-inline:10px}}
</style>
