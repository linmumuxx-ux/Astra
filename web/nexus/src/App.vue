<template>
  <div class="app">
    <header class="top">
      <div class="brand">
        <div class="mark">✦</div>
        <div class="brandname">NEXUS <span class="version">v1.0.1</span></div>
      </div>
      <span class="env-banner">
        <i class="dot" :class="{ off: !runtime?.reachable }"></i>
        {{ banner }}
      </span>
    </header>
    <main class="page">
      <router-view />
    </main>
    <nav class="dock" aria-label="页面导航">
      <router-link to="/employees">员工管理</router-link>
      <router-link to="/chat">数字员工</router-link>
      <router-link to="/team">团队交流</router-link>
      <router-link to="/tasks">任务管理</router-link>
      <router-link to="/workers">Agent Worker</router-link>
      <router-link to="/gateway">API 中转</router-link>
      <router-link to="/library">数字图书馆</router-link>
      <router-link to="/interventions">待处理</router-link>
      <router-link to="/settings">分类设置</router-link>
    </nav>
    <AstraConfirmHost />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import AstraConfirmHost from "@/components/astra/AstraConfirmHost.vue";
import { useAstraStore } from "@/stores/astra";
import { getRuntime } from "./api";
import type { RuntimeStatus } from "./types";

const store = useAstraStore();

const runtime = ref<RuntimeStatus | null>(null);
const banner = computed(() => {
  if (!runtime.value) return "正在检查 AgentScope";
  if (runtime.value.reachable) return `AgentScope ${runtime.value.agentscope_version} 已连接`;
  if (runtime.value.configured) return `AgentScope ${runtime.value.agentscope_version} 不可达`;
  return `AgentScope ${runtime.value.agentscope_version} 未连接`;
});

onMounted(async () => {
  if (!store.lastUpdated) void store.refresh();
  try {
    runtime.value = await getRuntime();
  } catch {
    runtime.value = { agentscope_version: "2.0.10", configured: false, reachable: false };
  }
});
</script>

<style scoped>
.dock a.router-link-active { background: #dff3e7; color: #147d59; font-weight: 750; }
</style>
