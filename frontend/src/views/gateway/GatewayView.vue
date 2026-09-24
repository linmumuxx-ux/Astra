<template>
  <div class="page gateway-page" data-testid="gateway-page">
    <section class="page-intro compact-intro">
      <div>
        <h2>API 中转</h2>
        <p>模型统一入口的控制面：节点调度、额度、Pool/Route/Key、调用证据与配置版本。</p>
      </div>
      <div v-if="authorized" class="gateway-session">
        <i />
        <span><strong>{{ actor }}</strong><small>{{ rolesText }}</small></span>
        <el-button size="small" @click="disconnect">退出</el-button>
      </div>
    </section>

    <GatewayGate>
      <el-tabs v-model="tab" class="gateway-main-tabs" aria-label="API 中转导航" @tab-change="switchTab(String($event))">
        <el-tab-pane v-for="item in tabs" :key="item.id" :name="item.id">
          <template #label><span class="gateway-tab-label"><component :is="item.icon" :size="14" />{{ item.label }}</span></template>
        </el-tab-pane>
      </el-tabs>

      <GatewayOverview v-if="tab === 'overview'" />
      <GatewayNodes v-else-if="tab === 'nodes'" />
      <GatewayPoolsRoutes v-else-if="tab === 'routes'" />
      <GatewayKeys v-else-if="tab === 'keys'" />
      <GatewayRequests v-else-if="tab === 'logs'" />
      <GatewayVersions v-else-if="tab === 'versions'" />
      <GatewaySelfUsage v-else />
    </GatewayGate>
  </div>
</template>

<script setup lang="ts">
import { Activity, Boxes, GitBranch, KeyRound, Route, ScrollText, Server } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import GatewayGate from '@/views/gateway/GatewayGate.vue'
import GatewayKeys from '@/views/gateway/GatewayKeys.vue'
import GatewayNodes from '@/views/gateway/GatewayNodes.vue'
import GatewayOverview from '@/views/gateway/GatewayOverview.vue'
import GatewayPoolsRoutes from '@/views/gateway/GatewayPoolsRoutes.vue'
import GatewayRequests from '@/views/gateway/GatewayRequests.vue'
import GatewaySelfUsage from '@/views/gateway/GatewaySelfUsage.vue'
import GatewayVersions from '@/views/gateway/GatewayVersions.vue'

const route = useRoute()
const router = useRouter()
const { authorized, actor, roles, disconnect } = useGatewayAuth()

const tabs = [
  { id: 'overview', label: '总览', icon: Activity },
  { id: 'nodes', label: '节点', icon: Server },
  { id: 'routes', label: '资源池 / 路由', icon: Boxes },
  { id: 'keys', label: '密钥', icon: KeyRound },
  { id: 'logs', label: '调用日志', icon: ScrollText },
  { id: 'versions', label: '配置版本', icon: GitBranch },
  { id: 'self', label: '自助用量', icon: Route },
]
const tab = ref('overview')
const rolesText = computed(() => (roles.value.length ? roles.value.join(' · ') : '无管理角色'))

function switchTab(next: string) {
  tab.value = next
  router.replace({ query: { ...route.query, tab: next } })
}

onMounted(() => {
  const fromQuery = typeof route.query.tab === 'string' ? route.query.tab : 'overview'
  if (tabs.some((item) => item.id === fromQuery)) tab.value = fromQuery
})
</script>

<style scoped>
.gateway-page { padding-bottom: 64px; }
.gateway-session { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border: 1px solid var(--astra-border); border-radius: 10px; background: var(--astra-bg-card); }
.gateway-session > i { width: 8px; height: 8px; border-radius: 50%; background: var(--astra-success); box-shadow: 0 0 0 4px var(--astra-success-soft); }
.gateway-session span { display: grid; }
.gateway-session strong { color: var(--astra-text-primary); font-size: var(--astra-font-control); }
.gateway-session small { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-tabs { flex-wrap: wrap; }
.gateway-main-tabs :deep(.el-tabs__content){display:none}
.gateway-tab-label{display:inline-flex;align-items:center;gap:6px}
</style>