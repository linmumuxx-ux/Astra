<template><section class="page" data-testid="intervention-page"><h2>待处理</h2><p>处理需要人工介入或继续执行的任务。</p><el-radio-group v-model="selected" class="filter-tabs"><el-radio-button v-for="state in states" :key="state" :value="state">{{ runtimeStatusLabel(state) }} · {{ store.tasks.filter(task => task.status === state).length }}</el-radio-button></el-radio-group><article v-for="task in tasks" :key="task.id" class="intervention-task"><div><h3>{{ task.title }}</h3><RuntimeStatusBadge :projection="task" /><p>{{ task.runtime_error || task.failure_reason || task.current_progress }}</p></div><el-button type="primary" @click="$router.push(`/tasks/${task.id}`)">进入任务详情</el-button></article><p v-if="!tasks.length">当前没有待处理任务。</p></section></template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAstraStore } from '@/stores/astra'
import RuntimeStatusBadge from '@/components/runtime/RuntimeStatusBadge.vue'
import { runtimeStatusLabel } from '@/features/runtime/status'
const store = useAstraStore()
const states = ['WAITING', 'FAILED'] as const
const selected = ref<string>('WAITING')
const tasks = computed(() => store.tasks.filter(task => task.status === selected.value))
</script>
<style scoped>.intervention-task{display:flex;align-items:center;justify-content:space-between;padding:16px;border-bottom:1px solid var(--astra-border)}</style>
