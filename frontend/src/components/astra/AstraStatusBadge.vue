<template><span class="status-badge" :data-tone="tone" :data-status="status"><i v-if="pulse" />{{ label }}</span></template>

<script setup lang="ts">
import { computed } from 'vue'
import { statusLabel, statusTone } from '@/utils/format'
const props = defineProps<{ status: string; pulse?: boolean }>()
const label = computed(() => statusLabel(props.status))
const tone = computed(() => statusTone(props.status))
</script>
