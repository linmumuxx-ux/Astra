<script setup lang="ts">
defineProps<{ title: string; subtitle: string; eyebrow: string }>()
</script>
<template><header class="page-title"><div><div class="eyebrow">{{ eyebrow }}</div><h1>{{ title }}</h1><p>{{ subtitle }}</p></div><div class="title-actions"><slot/></div></header></template>
