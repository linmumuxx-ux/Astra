<template>
  <span class="run-status-badge" :data-tone="meta.tone" :data-level="meta.level">
    <i v-if="meta.level === 'EXECUTING' || meta.level === 'WAITING'" />
    {{ meta.label }}
    <em v-if="meta.detail && showDetail">{{ meta.detail }}</em>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { runUnifiedStatus } from '@/features/runs/unifiedStatus'

const props = withDefaults(defineProps<{ status: string; showDetail?: boolean }>(), { showDetail: true })
const meta = computed(() => runUnifiedStatus(props.status))
</script>

<style scoped>
.run-status-badge {
  --tone: var(--astra-text-muted);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 26px;
  padding: 2px 9px;
  color: var(--tone);
  border: 1px solid color-mix(in srgb, var(--tone) 28%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--tone) 9%, transparent);
  font-size: var(--astra-font-helper);
  white-space: nowrap;
}
.run-status-badge[data-tone='info'] { --tone: var(--astra-info); }
.run-status-badge[data-tone='success'] { --tone: var(--astra-success); }
.run-status-badge[data-tone='warning'] { --tone: var(--astra-warning); }
.run-status-badge[data-tone='danger'] { --tone: var(--astra-danger); }
.run-status-badge i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; animation: pulse 1.8s ease-in-out infinite; }
.run-status-badge em {
  font-style: normal;
  opacity: .82;
  padding-left: 6px;
  color: var(--tone);
}
</style>
