<template>
  <ElContainer class="gateway-page" data-testid="gateway-page">
    <AstraPageHeader title="API 中转" :description="sectionLine" testid="gateway-header">
      <span class="astra-session" data-testid="gateway-session">
        <strong>{{ actor }}</strong>
        <span>{{ rolesText }}</span>
      </span>
      <ElButton text type="primary" data-testid="gateway-disconnect" @click="disconnect">退出</ElButton>
      <template #actions>
        <!-- 子页把自己的刷新与主操作 Teleport 到这里，全站按钮位置保持一致。 -->
        <div id="gateway-header-actions" class="gateway-header-actions" />
      </template>
    </AstraPageHeader>

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
import { ElAside, ElButton, ElContainer, ElMain, ElMenu, ElMenuItem } from 'element-plus'
import AstraPageHeader from '@/components/astra/AstraPageHeader.vue'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import GatewayGate from '@/views/gateway/GatewayGate.vue'

const route = useRoute()
const { authorized, actor, roles, disconnect } = useGatewayAuth()

// 父级是 API 中转唯一的标题区：这里同时承载分区名与分区说明，
// 子页不再各自带一套大标题，避免父子两套大标题重复。
const menuItems = [
  { id: 'overview', label: '运行总览', path: '/gateway/overview', icon: Activity, description: 'Token、QPS、延迟、节点健康与实例状态均直接来自后端观测契约。' },
  { id: 'nodes', label: '下游节点', path: '/gateway/nodes', icon: Server, description: '配置态、健康态与调度态相互独立；节点默认先安全下线再删除。' },
  { id: 'routes', label: '资源池与路由', path: '/gateway/routes', icon: Boxes, description: '路由模型名唯一，第一阶段一个路由指向一个资源池。' },
  { id: 'keys', label: 'API Key 管理', path: '/gateway/keys', icon: KeyRound, description: 'Key 以 agw_ 前缀生成，库中只存不可逆摘要；原文仅在创建成功后显示一次。' },
  { id: 'logs', label: '调用日志', path: '/gateway/logs', icon: ScrollText, description: '只记录元数据与测量值，不保存 Prompt、Authorization 或响应体。' },
  { id: 'versions', label: '配置版本', path: '/gateway/versions', icon: GitBranch, description: '发布前校验全部引用，生成不可变快照；回滚会以历史快照生成新版本。' },
  { id: 'self', label: '自助用量', path: '/gateway/self', icon: Route, description: '普通 Gateway Key 只能查看自身的日志与统计，凭据仅存当前会话。' },
]

const activeMenu = computed(() => {
  const match = menuItems.find((item) => route.path === item.path || route.path.startsWith(`${item.path}/`))
  return match ? match.path : '/gateway/overview'
})
const sectionLine = computed(() => {
  const current = menuItems.find((item) => item.path === activeMenu.value) ?? menuItems[0]
  return `${current.label} · ${current.description}`
})
const rolesText = computed(() => (roles.value.length ? roles.value.join(' · ') : '无管理角色'))
</script>

<style scoped>
.gateway-page { display: flex; flex-direction: column; gap: 14px; min-height: calc(100vh - 68px); padding: 16px 24px 18px; background: var(--astra-bg-base); }
.gateway-page > .gateway-workspace { flex: 1 1 auto; }
.gateway-header-actions { display: flex; align-items: center; gap: 8px; }
.gateway-workspace { align-items: stretch; }
.gateway-aside { --el-aside-width: 210px; border: 1px solid var(--astra-border); border-radius: 12px; background: var(--astra-bg-panel); }
.gateway-menu { --el-menu-base-level-padding: 14px; --el-menu-item-height: 44px; border-right: 0; background: transparent; }
.gateway-menu :deep(.el-menu-item) { gap: 8px; }
.gateway-content { --el-main-padding: 0; display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.gateway-content > * { flex: 1 1 auto; min-height: 0; }
@media (max-width: 860px) { .gateway-aside { --el-aside-width: 170px; } }
</style>
