<template>
  <el-table :data="tasks" size="small" empty-text="还没有任务">
    <el-table-column prop="id" label="任务" width="150" />
    <el-table-column prop="title" label="标题" min-width="140" />
    <el-table-column label="状态" width="110">
      <template #default="{ row }">{{ row.runtime_status_label || row.status }}</template>
    </el-table-column>
    <el-table-column prop="responsible_employee_id" label="责任员工" width="120" />
    <el-table-column prop="worker_id" label="Worker" width="120" />
    <el-table-column v-if="actions" label="操作" width="220">
      <template #default="{ row }">
        <el-button link @click="emit('action', row.id, 'start')">开始</el-button>
        <el-button link @click="emit('action', row.id, 'pause')">暂停</el-button>
        <el-button link @click="emit('action', row.id, 'resume')">恢复</el-button>
        <el-button link @click="emit('action', row.id, 'stop')">终止</el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">
import type { PlatformTask } from "../platform";

defineProps<{ tasks: PlatformTask[]; actions?: boolean }>();
const emit = defineEmits<{ action: [id: string, name: "start" | "pause" | "resume" | "stop"] }>();
</script>
