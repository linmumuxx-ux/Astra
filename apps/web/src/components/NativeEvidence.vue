<script setup lang="ts">
import { useResource } from '../api'
import ResourceState from './ResourceState.vue'
interface Evidence { native_session_id: string; message_id: string; part_id: string; tool: string; state: string; output: string; truncated: boolean; matches_submission: boolean }
const props = defineProps<{ executionId: string }>()
const resource = useResource<{ items: Evidence[] }>(() => props.executionId ? `/executions/${props.executionId}/native-evidence` : '', { items: [] })
</script>
<template><ResourceState :loading="resource.loading.value" :error="resource.error.value" :empty="!resource.data.value.items.length" description="尚无可见的原生工具结果" @retry="resource.load"><article v-for="item in resource.data.value.items" :key="`${item.native_session_id}/${item.part_id}`" class="mini-card"><strong>{{ item.tool }} · {{ item.state }}</strong><p v-if="item.state === 'completed' && !item.matches_submission" class="caption">此内容未匹配原提交证据哈希，不可作为通过依据。</p><pre class="code-block">{{ item.output || '此工具未提交输出，不能据此认定成功。' }}</pre><p v-if="item.truncated" class="caption">长输出显示前 20000 字符。</p><el-collapse><el-collapse-item title="来源索引" :name="item.part_id"><p class="caption">{{ item.native_session_id }} / {{ item.message_id }} / {{ item.part_id }}</p></el-collapse-item></el-collapse></article></ResourceState></template>
