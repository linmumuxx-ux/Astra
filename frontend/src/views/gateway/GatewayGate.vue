<template>
  <div v-if="checking && !authorized" class="gateway-gate-loading">
    <LoaderCircle :size="18" class="spin" />正在校验控制面凭据…
  </div>
  <GatewayConnect v-else-if="!authorized" />
  <slot v-else />
</template>

<script setup lang="ts">
import { LoaderCircle } from 'lucide-vue-next'
import { onMounted } from 'vue'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import GatewayConnect from '@/views/gateway/GatewayConnect.vue'

const { authorized, checking, ensureLoaded } = useGatewayAuth()

onMounted(() => { void ensureLoaded() })
</script>

<style scoped>
.gateway-gate-loading { display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 55vh; color: var(--astra-text-muted); font-size: var(--astra-font-control); }
</style>