<template>
  <section class="data-page">
    <h1 class="h-title">Agent Worker</h1>
    <p class="muted">每个 Worker 同时只执行一个任务。部署和重启沿用原环境接口。</p>
    <div class="panel" style="padding: 16px">
      <el-table :data="workers" size="small" empty-text="还没有 Worker">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column label="环境" width="140">
          <template #default="{ row }">{{ row.execution_environment?.status || "未配置" }}</template>
        </el-table-column>
        <el-table-column label="模型" min-width="180">
          <template #default="{ row }">{{ row.execution_environment?.model_name || "默认 deepseek/deepseek-flash" }}</template>
        </el-table-column>
        <el-table-column label="当前任务" min-width="200">
          <template #default="{ row }">
            <router-link v-if="row.task" class="task-link" :to="{ path: '/tasks', query: { id: row.task.id } }">
              {{ row.task.id }} · {{ row.task.runtime_status_label || row.task.status }}
            </router-link>
            <span v-else class="muted">暂无任务</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link @click="run(row.id, 'deploy')">部署</el-button>
            <el-button link @click="run(row.id, 'restart')">重启</el-button>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="note" class="muted">{{ note }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { listTasks, listWorkers, maintainWorker, type PlatformTask, type PlatformWorker } from "../platform";

type WorkerRow = PlatformWorker & { task: PlatformTask | null };

const workers = ref<WorkerRow[]>([]);
const note = ref("");

function currentTask(tasks: PlatformTask[]): PlatformTask | null {
  return tasks.find((item) => item.status === "RUNNING" || item.status === "WAITING") ?? tasks[0] ?? null;
}

async function load() {
  try {
    const rows = await listWorkers();
    workers.value = await Promise.all(
      rows.map(async (worker) => {
        try {
          return { ...worker, task: currentTask(await listTasks({ employee_id: worker.id })) };
        } catch {
          return { ...worker, task: null };
        }
      }),
    );
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "Worker 服务不可用");
  }
}

async function run(id: string, action: "deploy" | "restart") {
  note.value = "正在执行环境操作";
  try {
    note.value = await maintainWorker(id, action);
    await load();
  } catch (error) {
    note.value = error instanceof Error ? error.message : "环境操作失败";
  }
}

onMounted(load);
</script>

<style scoped>
.task-link { color: var(--green); text-decoration: none; }
.task-link:hover { text-decoration: underline; }
</style>
