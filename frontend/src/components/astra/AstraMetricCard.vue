<template>
  <article class="metric-card" :data-tone="tone">
    <div class="metric-card__top"><span class="metric-card__icon"><component :is="icon" :size="17" /></span><small>{{ label }}</small></div>
    <div class="metric-card__value"><strong>{{ value }}</strong><span v-if="unit">{{ unit }}</span></div>
    <p>{{ hint }}</p>
  </article>
</template>

<script setup lang="ts">
import type { Component } from 'vue'
withDefaults(defineProps<{ label: string; value: number | string; unit?: string; hint: string; icon: Component; tone?: string }>(), { tone: 'info' })
</script>
