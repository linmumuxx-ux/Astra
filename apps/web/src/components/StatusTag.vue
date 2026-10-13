<script setup lang="ts">
import { label, tone } from '../format'
defineProps<{ value?: string }>()
</script>
<template><el-tag :type="tone(value)" effect="light" round>{{ label(value) }}</el-tag></template>
