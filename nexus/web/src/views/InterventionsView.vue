<template>
  <section class="data-page">
    <h1 class="h-title">待处理</h1>
    <p class="muted">等待人工的任务。确认完成仍走任务服务。</p>
    <div class="panel" style="padding: 16px">
      <el-table :data="tasks" size="small" empty-text="没有等待处理的任务">
        <el-table-column prop="id" label="任务" width="160" />
        <el-table-column prop="title" label="标题" />
        <el-table-column label="原因" min-width="180">
          <template #default="{ row }">{{ row.human_intervention?.reason || row.current_progress }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link @click="confirm(row.id)">确认完成</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { listTasks, taskAction, type PlatformTask } from "../platform";

const tasks = ref<PlatformTask[]>([]);

async function load() {
  try {
    tasks.value = await listTasks({ status: "WAITING" });
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "任务服务不可用");
  }
}

async function confirm(id: string) {
  try {
    await taskAction(id, "confirm");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "还不能确认完成");
  }
}

onMounted(load);
</script>
