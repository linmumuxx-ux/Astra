<template>
  <section class="astra-panel" :class="{ 'astra-panel--flush': flush }">
    <header v-if="$slots.title || title" class="astra-panel__header">
      <div><slot name="title"><h2>{{ title }}</h2></slot><p v-if="subtitle">{{ subtitle }}</p></div>
      <slot name="action" />
    </header>
    <div class="astra-panel__body"><slot /></div>
  </section>
</template>

<script setup lang="ts">
defineProps<{ title?: string; subtitle?: string; flush?: boolean }>()
</script>
