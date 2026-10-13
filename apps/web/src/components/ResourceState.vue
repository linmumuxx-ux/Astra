<script setup lang="ts">
import type { ApiError } from '../api'
defineProps<{ loading?: boolean; error?: ApiError | null; empty?: boolean; description?: string }>()
defineEmits<{ retry: [] }>()
</script>
<template>
  <div v-if="loading" class="state-block" aria-busy="true" aria-label="正在加载"><el-skeleton :rows="3" animated/></div>
  <el-result v-else-if="error" :icon="error.status === 403 ? 'warning' : 'error'" :title="error.status === 403 ? '权限不足' : error.status === 401 ? '身份已失效' : '暂时无法读取'" :sub-title="error.message"><template #extra><el-button @click="$emit('retry')">重新读取</el-button></template></el-result>
  <el-empty v-else-if="empty" :description="description || '当前没有数据'" :image-size="70"/>
  <slot v-else/>
</template>
