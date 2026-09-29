<template>
  <ElContainer class="gateway-page" data-testid="gateway-page">
    <ElHeader class="gateway-header">
      <div class="gateway-title">
        <h2>API 中转</h2>
        <ElText type="info">模型统一入口的控制面：节点调度、额度、Pool/Route/Key、调用证据与配置版本。</ElText>
      </div>
      <div v-if="authorized" class="gateway-session">
        <i />
        <span><strong>{{ actor }}</strong><small>{{ rolesText }}</small></span>
        <ElButton @click="disconnect">退出</ElButton>
      </div>
    </ElHeader>

    <GatewayGate>
      <ElContainer class="gateway-workspace">
        <ElAside class="gateway-aside">
          <ElMenu class="gateway-menu" mode="vertical" :default-active="activeMenu" router>
            <ElMenuItem
              v-for="item in menuItems"
              :key="item.path"
              :index="item.path"
              :data-testid="`gateway-menu-${item.id}`"
            >
              <component :is="item.icon" :size="16" />
              <span>{{ item.label }}</span>
            </ElMenuItem>
          </ElMenu>
        </ElAside>
        <ElMain class="gateway-content">
          <RouterView />
        </ElMain>
      </ElContainer>
    </GatewayGate>
  </ElContainer>
</template>

<script setup lang="ts">
import { Activity, Boxes, GitBranch, KeyRound, Route, ScrollText, Server } from 'lucide-vue-next'
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import { ElAside, ElButton, ElContainer, ElHeader, ElMain, ElMenu, ElMenuItem, ElText } from 'element-plus'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import GatewayGate from '@/views/gateway/GatewayGate.vue'

const route = useRoute()
const { authorized, actor, roles, disconnect } = useGatewayAuth()

const menuItems = [
  { id: 'overview', label: '运行总览', path: '/gateway/overview', icon: Activity },
  { id: 'nodes', label: '下游节点', path: '/gateway/nodes', icon: Server },
  { id: 'routes', label: '资源池与路由', path: '/gateway/routes', icon: Boxes },
  { id: 'keys', label: 'API Key 管理', path: '/gateway/keys', icon: KeyRound },
  { id: 'logs', label: '调用日志', path: '/gateway/logs', icon: ScrollText },
  { id: 'versions', label: '配置版本', path: '/gateway/versions', icon: GitBranch },
  { id: 'self', label: '自助用量', path: '/gateway/self', icon: Route },
]

const activeMenu = computed(() => {
  const match = menuItems.find((item) => route.path === item.path || route.path.startsWith(`${item.path}/`))
  return match ? match.path : '/gateway/overview'
})
const rolesText = computed(() => (roles.value.length ? roles.value.join(' · ') : '无管理角色'))
</script>

<style scoped>
.gateway-page { min-height: calc(100vh - 68px); background: var(--astra-bg-base); }
.gateway-header { --el-header-height: auto; --el-header-padding: 0; display: flex; align-items: center; gap: 16px; padding: 14px 24px; border-bottom: 1px solid var(--astra-border); background: var(--astra-bg-panel); }
.gateway-title { display: grid; min-width: 0; gap: 3px; margin-right: auto; }
.gateway-title h2 { margin: 0; color: var(--astra-text-primary); font-size: var(--astra-font-section); line-height: normal; }
.gateway-session { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border: 1px solid var(--astra-border); border-radius: 10px; background: var(--astra-bg-card); }
.gateway-session > i { width: 8px; height: 8px; border-radius: 50%; background: var(--astra-success); box-shadow: 0 0 0 4px var(--astra-success-soft); }
.gateway-session span { display: grid; }
.gateway-session strong { color: var(--astra-text-primary); font-size: var(--astra-font-control); }
.gateway-session small { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-workspace { align-items: stretch; }
.gateway-aside { --el-aside-width: 210px; border-right: 1px solid var(--astra-border); background: var(--astra-bg-panel); }
.gateway-menu { --el-menu-base-level-padding: 14px; --el-menu-item-height: 44px; border-right: 0; background: transparent; }
.gateway-menu :deep(.el-menu-item) { gap: 8px; }
.gateway-content { --el-main-padding: 20px 24px 64px; min-width: 0; }
@media (max-width: 860px) { .gateway-header { align-items: flex-start; flex-wrap: wrap; } .gateway-aside { --el-aside-width: 170px; } }
</style>
