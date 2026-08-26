<template><div class="progress" :aria-label="`${value}%`"><span :style="{ width: `${value}%` }" /></div></template>
<script setup lang="ts">defineProps<{ value: number }>()</script>
