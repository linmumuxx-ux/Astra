<template>
  <div class="page" data-testid="run-list-page">
    <section class="page-intro compact-intro"><div><h2>运行记录</h2><p>每次 OpenCode 针对某个任务的执行都会保留独立记录。</p></div><button class="button" @click="load"><RefreshCw :size="14" /> 刷新记录</button></section>
    <section class="run-summary"><article><small>运行总数</small><strong>{{ runs.length }}</strong><span>可追溯记录</span></article><article><small>已完成</small><strong>{{ runCount('PASSED') }}</strong><span>员工已提交结果</span></article><article><small>未完成 / 阻塞</small><strong>{{ runCount('FAILED') + runCount('BLOCKED') }}</strong><span>已产生消耗仍保留</span></article><article><small>实际 Token</small><strong>{{ formatTokens(totalTokens) }}</strong><span>不包含估算值</span></article></section>
    <AstraPanel flush><template #title><div class="table-title"><h2>运行列表</h2><span>{{ runs.length }} 条</span></div></template><template #action><div class="search-box search-box--small"><Search :size="14" /><input v-model="query" placeholder="运行 ID / 任务 ID" /></div></template><div class="table-wrap"><table><thead><tr><th>运行 ID</th><th>任务</th><th>员工</th><th>工作环境</th><th>状态</th><th>Token</th><th>工具调用</th><th>开始时间</th><th>运行时长</th><th>Session</th></tr></thead><tbody><tr v-for="run in filtered" :key="run.id" @click="$router.push(`/runs/${run.id}`)"><td><strong>{{ run.id }}</strong><small>第 {{ run.run_number }} 次</small></td><td><strong>{{ taskTitle(run.task_id) }}</strong><small>{{ run.task_id }}</small></td><td>{{ employeeName(run.employee_id) }}</td><td><span class="executor-chip"><Server :size="12" />{{ environmentLabel(run.execution_environment_snapshot) }}</span></td><td><AstraStatusBadge :status="run.status" /></td><td>{{ formatTokens(run.total_tokens) }}</td><td>{{ run.tool_call_count ?? '—' }}</td><td>{{ formatTime(run.started_at) }}</td><td>{{ formatDuration(run.started_at, run.finished_at) }}</td><td class="session-cell" :title="run.opencode_session_id ?? ''">{{ run.opencode_session_id ?? '—' }}</td></tr><tr v-if="!filtered.length"><td colspan="10"><AstraEmptyState :icon="History" title="暂无运行记录" description="数字员工开始处理任务后会创建运行记录。" /></td></tr></tbody></table></div></AstraPanel>
  </div>
</template>
<script setup lang="ts">
import { History, RefreshCw, Search, Server } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type { Run } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
import { environmentLabel, formatDuration, formatTime, formatTokens } from '@/utils/format'
const runs = ref<Run[]>([]); const query = ref(''); const store = useAstraStore()
const load = async () => { runs.value = await api.runs(); if (!store.tasks.length) await store.refresh() }; onMounted(load)
const filtered = computed(() => runs.value.filter((run) => !query.value || `${run.id}${run.task_id}`.toLowerCase().includes(query.value.toLowerCase())))
const totalTokens = computed(() => runs.value.reduce((total, run) => total + (run.total_tokens ?? 0), 0) || null)
const runCount = (status: string) => runs.value.filter((run) => run.status === status).length
const taskTitle = (id: string) => store.tasks.find((task) => task.id === id)?.title ?? '任务详情'
const employeeName = (id: string) => store.employees.find((item) => item.id === id)?.name ?? id
</script>
