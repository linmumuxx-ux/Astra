<template>
  <div class="task-hall" data-testid="task-hall">
    <ElRadioGroup :model-value="view" size="small" class="task-hall__tabs" data-testid="task-hall-tabs" @update:model-value="select">
      <ElRadioButton value="list" data-testid="task-hall-tab-list">任务列表</ElRadioButton>
      <ElRadioButton value="pending" data-testid="task-hall-tab-pending">待处理</ElRadioButton>
    </ElRadioGroup>
    <InterventionView v-if="view === 'pending'" />
    <TaskListView v-else />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElRadioButton, ElRadioGroup } from 'element-plus'
import InterventionView from './InterventionView.vue'
import TaskListView from './TaskListView.vue'

const route = useRoute()
const router = useRouter()
const view = computed(() => (route.query.view === 'pending' ? 'pending' : 'list'))

function select(value: string | number | boolean | undefined) {
  const { view: _view, ...rest } = route.query
  void router.push({ path: '/tasks', query: value === 'pending' ? { ...rest, view: 'pending' } : rest })
}
</script>

<style scoped>
.task-hall { display: flex; flex-direction: column; gap: 10px; height: 100%; min-height: 0; }
.task-hall > :last-child { flex: 1 1 auto; min-height: 0; }
.task-hall__tabs { align-self: flex-start; }
</style>
