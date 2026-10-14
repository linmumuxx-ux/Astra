<template>
  <section class="data-page">
    <div class="title-row">
      <h1 class="h-title">数字任务</h1>
      <el-button type="primary" @click="open = true">人工创建</el-button>
    </div>
    <div class="panel" style="padding: 16px">
      <TaskTable :tasks="tasks" actions @action="run" />
    </div>
    <el-dialog v-model="open" title="创建任务" width="520px">
      <el-form label-position="top">
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.task_type" style="width: 100%">
            <el-option label="缺陷 ISSUE" value="ISSUE" />
            <el-option label="需求 REQUIREMENT" value="REQUIREMENT" />
          </el-select>
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category_id" style="width: 100%">
            <el-option v-for="item in categories" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="open = false">取消</el-button>
        <el-button type="primary" @click="create">创建</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import TaskTable from "../components/TaskTable.vue";
import { createTask, listCategories, listTasks, taskAction, type PlatformTask } from "../platform";

const tasks = ref<PlatformTask[]>([]);
const categories = ref<Array<{ id: string; name: string; enabled: boolean }>>([]);
const open = ref(false);
const form = reactive({ title: "", description: "", task_type: "ISSUE", category_id: "" });

async function load() {
  try {
    tasks.value = await listTasks();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "任务服务不可用");
  }
}

async function run(id: string, action: "start" | "pause" | "resume" | "stop") {
  try {
    await taskAction(id, action);
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "操作没有生效");
  }
}

async function create() {
  try {
    await createTask({
      task_type: form.task_type,
      category_id: form.category_id,
      title: form.title,
      description: form.description,
      acceptance_criteria: [{ content: "结果可核对" }],
    });
    open.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "没有创建");
  }
}

onMounted(async () => {
  try {
    categories.value = (await listCategories()).filter((item) => item.enabled);
    form.category_id = categories.value[0]?.id ?? "";
  } catch {
    categories.value = [];
  }
  await load();
});
</script>
