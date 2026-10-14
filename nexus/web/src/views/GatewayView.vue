<template>
  <section class="data-page">
    <h1 class="h-title">API 网关</h1>
    <p class="muted">远程 Worker 使用路由模型 id。deepseek-flash 在 OpenCode 侧写成 astra-gateway/deepseek-flash。</p>
    <div class="panel" style="padding: 16px; margin-bottom: 16px">
      <div class="section-label">模型路由</div>
      <el-table :data="routes" size="small" empty-text="还没有路由">
        <el-table-column prop="model" label="模型" />
        <el-table-column prop="pool_id" label="池" />
        <el-table-column label="启用" width="90">
          <template #default="{ row }">{{ row.enabled ? "是" : "否" }}</template>
        </el-table-column>
      </el-table>
    </div>
    <div class="panel" style="padding: 16px">
      <div class="section-label">访问密钥</div>
      <el-table :data="keys" size="small" empty-text="还没有密钥">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="key_prefix" label="前缀" />
        <el-table-column label="启用" width="90">
          <template #default="{ row }">{{ row.enabled ? "是" : "否" }}</template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { listGatewayKeys, listGatewayRoutes } from "../platform";

const routes = ref<Array<{ id: string; model: string; enabled: boolean; pool_id: string }>>([]);
const keys = ref<Array<{ id: string; name: string; key_prefix: string; enabled: boolean }>>([]);

onMounted(async () => {
  try {
    routes.value = await listGatewayRoutes();
    keys.value = await listGatewayKeys();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "网关不可用");
  }
});
</script>
