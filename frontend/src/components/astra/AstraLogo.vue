<template>
  <div class="logo" aria-label="Astra">
    <span class="logo-mark">A</span>
    <span v-if="!compact" class="logo-copy"><strong>Astra</strong><small>运行控制台</small></span>
  </div>
</template>

<script setup lang="ts">
defineProps<{ compact?: boolean }>()
</script>

<style scoped>
.logo { display: flex; align-items: center; gap: 11px; min-width: 0; }
.logo-mark { position: relative; display: grid; place-items: center; width: 36px; height: 36px; color: var(--astra-primary-bright); font: 700 19px/1 var(--astra-font-display); border: 1px solid var(--astra-primary-border); border-radius: 11px 4px 11px 4px; background: var(--astra-primary-soft); box-shadow: 0 0 28px var(--astra-primary-glow); }
.logo-mark::after { content: ''; position: absolute; inset: 6px; border: 1px solid currentColor; border-width: 1px 0; transform: skew(-18deg); opacity: .4; }
.logo-copy { display: grid; line-height: 1.05; }
.logo-copy strong { font: 650 var(--astra-font-section) var(--astra-font-display); letter-spacing: .03em; color: var(--astra-text-primary); }
.logo-copy small { margin-top: 4px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); letter-spacing: .18em; text-transform: uppercase; }
</style>
