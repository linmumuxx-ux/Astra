<template>
  <div class="app">
    <header class="top">
      <div class="brand">
        <div class="mark">✦</div>
        <div class="brandname">NEXUS <span class="version">v1.4.0</span></div>
      </div>
      <span class="env-banner">
        <i class="dot" :class="{ off: !runtime?.reachable }"></i>
        {{ banner }}
      </span>
    </header>
    <main class="page">
      <form v-if="identity === 'ask'" class="uid-gate" @submit.prevent="submitUid">
        <label>
          输入 UID
          <input v-model="uidDraft" autocomplete="username" />
        </label>
        <button type="submit">继续</button>
      </form>
      <router-view v-else-if="identity === 'ready'" />
    </main>
    <nav class="dock" aria-label="页面导航">
      <el-dropdown v-for="group in navGroups" :key="group.label" trigger="click" @command="openNav">
        <button type="button" class="dock-item" :class="{ active: group.active }">{{ group.label }}</button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="item in group.items" :key="item.to" :command="item.to">{{ item.label }}</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <router-link to="/workers" title="Worker 执行任务。数字员工负责沟通，两者不是同一个对象。">Worker</router-link>
      <router-link to="/gateway">API 网关</router-link>
      <router-link to="/library">图书馆</router-link>
    </nav>
    <AstraConfirmHost />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import AstraConfirmHost from "@/components/astra/AstraConfirmHost.vue";
import { useAstraStore } from "@/stores/astra";
import { getRuntime, resolveOwner, saveOwnerId } from "./api";
import type { RuntimeStatus } from "./types";

const store = useAstraStore();
const route = useRoute();
const router = useRouter();
const navGroups = computed(() => [
  {
    label: "数字员工",
    active: ["/employees", "/chat", "/team"].some((path) => route.path.startsWith(path)),
    items: [
      { to: "/employees", label: "名录" },
      { to: "/chat", label: "私聊" },
      { to: "/team", label: "团队" },
    ],
  },
  {
    label: "任务",
    active: ["/tasks", "/interventions", "/settings"].some((path) => route.path.startsWith(path)),
    items: [
      { to: "/tasks", label: "任务列表" },
      { to: "/interventions", label: "待处理" },
      { to: "/settings", label: "任务分类" },
    ],
  },
]);

function openNav(path: string) {
  void router.push(path);
}

const runtime = ref<RuntimeStatus | null>(null);
const identity = ref<"loading" | "ready" | "ask">("loading");
const uidDraft = ref("");
const banner = computed(() => {
  if (!runtime.value) return "正在检查 AgentScope";
  if (runtime.value.reachable) return `AgentScope ${runtime.value.agentscope_version} 已连接`;
  if (runtime.value.configured) return `AgentScope ${runtime.value.agentscope_version} 不可达`;
  return `AgentScope ${runtime.value.agentscope_version} 未连接`;
});

function submitUid() {
  const value = uidDraft.value.trim();
  if (!value) return;
  saveOwnerId(value);
  identity.value = "ready";
}

onMounted(async () => {
  try {
    await resolveOwner();
    identity.value = "ready";
  } catch {
    identity.value = "ask";
  }
  if (!store.lastUpdated) void store.refresh();
  try {
    runtime.value = await getRuntime();
  } catch {
    runtime.value = { agentscope_version: "2.0.10", configured: false, reachable: false };
  }
});
</script>

<style scoped>
.dock a.router-link-active, .dock-item.active { background: #dff3e7; color: #147d59; font-weight: 750; }
.dock-item { font: inherit; }
.uid-gate { display: flex; gap: 12px; align-items: end; max-width: 420px; }
.uid-gate label { display: flex; flex-direction: column; gap: 6px; flex: 1; }
.uid-gate input { padding: 8px 10px; border: 1px solid #c9ddd2; border-radius: 8px; }
.uid-gate button { padding: 8px 14px; border: 0; border-radius: 8px; background: #187956; color: white; }
</style>
