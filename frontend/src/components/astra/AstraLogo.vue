<template>
  <div class="logo" aria-label="NEXUS · 数字空间">
    <span class="logo-mark"><i /><i /><i /></span>
    <span v-if="!compact" class="logo-copy"><strong>NEXUS · 数字空间</strong><small>数字员工工作与协同空间</small></span>
  </div>
</template>

<script setup lang="ts">
defineProps<{ compact?: boolean }>()
</script>

<style scoped>
.logo { display: flex; align-items: center; gap: 11px; min-width: 0; }
.logo-mark { position: relative; width: 38px; height: 38px; filter: drop-shadow(0 7px 14px rgba(24,184,117,.18)); }
.logo-mark i { position: absolute; width: 9px; height: 31px; border-radius: 6px; background: linear-gradient(180deg, #34cf8e, #10a965); transform: rotate(29deg); }
.logo-mark i:nth-child(1) { left: 8px; top: 4px; }.logo-mark i:nth-child(2) { right: 8px; top: 4px; transform: rotate(-29deg); }.logo-mark i:nth-child(3) { left: 14px; top: 18px; width: 15px; height: 7px; transform: rotate(0); background: #8ee4bb; }
.logo-copy { display: grid; line-height: 1.05; }
.logo-copy strong { font: 700 var(--astra-font-section) var(--astra-font-display); letter-spacing: .01em; color: var(--astra-text-primary); white-space: nowrap; }
.logo-copy small { margin-top: 5px; color: var(--astra-text-muted); font-size: var(--astra-font-body); letter-spacing: .02em; white-space: nowrap; }
</style>
