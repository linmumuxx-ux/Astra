<template>
  <RuntimeStatusBadge :projection="run" :show-detail="showDetail" />
</template>

<script setup lang="ts">
import RuntimeStatusBadge from '@/components/runtime/RuntimeStatusBadge.vue'
import type { RuntimeStatusProjection } from '@/features/runtime/status'

withDefaults(defineProps<{ run: RuntimeStatusProjection; showDetail?: boolean }>(), { showDetail: true })
</script>
