<template>
  <section class="data-page">
    <h1 class="h-title">数字图书馆</h1>
    <div class="panel" style="padding: 16px; margin-bottom: 16px">
      <div class="section-label">空间</div>
      <el-table :data="spaces" size="small" empty-text="还没有空间">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="id" label="编号" />
      </el-table>
    </div>
    <div class="panel" style="padding: 16px">
      <div class="section-label">知识</div>
      <el-table :data="items" size="small" empty-text="还没有条目">
        <el-table-column prop="title" label="标题" />
        <el-table-column prop="type" label="类型" width="120" />
        <el-table-column prop="status" label="状态" width="120" />
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { listLibraryKnowledge, listLibrarySpaces } from "../platform";

const spaces = ref<Array<{ id: string; name: string }>>([]);
const items = ref<Array<{ id: string; title: string; type: string; status: string }>>([]);

onMounted(async () => {
  try {
    spaces.value = await listLibrarySpaces();
    items.value = (await listLibraryKnowledge()).items;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "图书馆不可用");
  }
});
</script>
