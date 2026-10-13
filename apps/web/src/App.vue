<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { ArrowLeft, Atom, BookOpen, Boxes, Building2, ChevronRight, CircleCheck, CircleDot, LogOut, MessageCircle, RefreshCw, ShieldCheck, Sparkles, Users, WifiOff } from 'lucide-vue-next'
import { connection, online, principal, refresh, request, setToken, startEvents, token } from './api'
import type { Principal } from './types'
const route = useRoute()
const credential = ref('')
const loggingIn = ref(false)
const loginError = ref('')
const navigation = [
  { path: '/space', title: '数字空间', icon: Sparkles }, { path: '/employees', title: '数字员工', icon: Users },
  { path: '/channels', title: '团队交流', icon: MessageCircle }, { path: '/tasks', title: '工作中心', icon: Boxes },
  { path: '/attention', title: '待我处理', icon: CircleDot }, { path: '/library', title: '数字图书馆', icon: BookOpen },
  { path: '/resources', title: '资源 / API', icon: Atom }, { path: '/organization', title: '组织员工', icon: Building2 },
  { path: '/governance', title: '治理', icon: ShieldCheck },
]
const connectionText = computed(() => ({ connected: '实时同步', connecting: '正在连接', disconnected: '连接中断 · 正在重连', forbidden: '事件访问受限', offline: '网络已离线' }[connection.value]))
async function login() {
  if (!credential.value.trim()) return
  loggingIn.value = true; loginError.value = ''
  const current = credential.value.trim()
  setToken(current)
  try { const result = await request<Principal>('/me'); if (token.value === current) { principal.value = result; credential.value = '' } }
  catch (error) { if (token.value === current) { loginError.value = (error as Error).message; setToken('') } }
  finally { loggingIn.value = false }
}
watch(token, async value => { if (value && !principal.value) { try { const result = await request<Principal>('/me'); if (token.value === value) principal.value = result } catch (error) { if (token.value === value) { loginError.value = (error as Error).message; setToken('') } } } }, { immediate: true })
onUnmounted(startEvents())
</script>

<template>
  <el-config-provider size="small" :locale="zhCn">
    <div v-if="!token" class="login-page">
      <div class="login-visual" aria-hidden="true"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><div class="login-core"><Atom :size="90" :stroke-width="1"/></div><span class="login-coordinate">ASTRA / HUMAN × DIGITAL TEAM</span></div>
      <section class="login-card">
        <div class="brand"><span class="brand-symbol">✦</span><div><strong>ASTRA <sup>1.0</sup></strong><small>与你的数字团队，一起向前</small></div></div>
        <p class="eyebrow">WELCOME TO YOUR WORKSPACE</p><h1>连接你的团队。</h1><p class="muted">使用管理员签发的身份凭据进入 Astra。职责、工作与对话由当前身份的权限决定。</p>
        <el-form @submit.prevent="login"><el-form-item label="访问凭据"><el-input v-model="credential" type="password" show-password autocomplete="off" placeholder="输入 Bearer 访问凭据" aria-label="访问凭据"/></el-form-item><el-alert v-if="loginError" :title="loginError" type="error" :closable="false"/><el-button native-type="submit" type="primary" size="large" :loading="loggingIn" :disabled="!credential.trim()" class="login-submit">进入数字空间 <ChevronRight :size="16"/></el-button></el-form>
        <p class="caption">凭据仅保存于当前浏览器会话，不作为 URL 参数传递。</p>
      </section>
    </div>
    <div v-else-if="!principal" class="session-verification" role="status"><el-skeleton :rows="3" animated/><p>正在验证身份与权限…</p></div>
    <div v-else class="app-shell" :class="{ 'is-space': route.path === '/space' }">
      <header class="topbar">
        <RouterLink to="/space" class="brand" aria-label="Astra 数字空间"><span class="brand-symbol">✦</span><div><strong>ASTRA <sup>1.0</sup></strong><small>NEXUS · 数字空间</small></div></RouterLink>
        <div class="topbar-right"><span class="connection" :class="connection" role="status" aria-live="polite"><CircleCheck v-if="connection === 'connected'" :size="13"/><WifiOff v-else :size="13"/><span>{{ connectionText }}</span></span><el-button circle :icon="RefreshCw" aria-label="刷新权威状态" @click="refresh"/><RouterLink to="/attention"><el-button>待我处理 <CircleDot :size="14"/></el-button></RouterLink><el-dropdown><el-button circle :icon="Users" :aria-label="principal?.name || '当前身份'"/><template #dropdown><el-dropdown-menu><el-dropdown-item disabled>{{ principal?.name || principal?.id }}</el-dropdown-item><el-dropdown-item :icon="LogOut" @click="setToken('')">退出连接</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
      </header>
      <div v-if="!online" class="offline-banner" role="status"><WifiOff :size="15"/>网络离线，当前数据可能已过期。恢复网络后将重新同步。</div>
      <div v-if="route.path !== '/space'" class="context-nav"><RouterLink to="/space"><ArrowLeft :size="14"/>数字空间</RouterLink><ChevronRight :size="13"/><span>{{ route.meta.title }}</span></div>
      <main id="main-content"><RouterView/></main>
      <nav class="dock" aria-label="空间导航"><RouterLink v-for="item in navigation" :key="item.path" :to="item.path" :class="{ active: route.path.startsWith(item.path) }" :aria-current="route.path.startsWith(item.path) ? 'page' : undefined"><component :is="item.icon" :size="20" :stroke-width="1.6"/><span>{{ item.title }}</span></RouterLink></nav>
    </div>
  </el-config-provider>
</template>
