<template>
  <div class="empty-state"><span><component :is="icon" :size="20" /></span><strong>{{ title }}</strong><p>{{ description }}</p><slot /></div>
</template>
<script setup lang="ts">import type { Component } from 'vue'; defineProps<{ icon: Component; title: string; description: string }>()</script>
