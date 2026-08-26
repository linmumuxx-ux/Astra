<template>
  <div class="page" data-testid="task-list-page">
    <section class="page-intro compact-intro"><div><span class="kicker"><ClipboardList :size="13" /> TASK OPERATIONS</span><h2>任务中心</h2><p>统一管理任务发现、调度、运行、验证与人工控制。</p></div><button class="button button--primary" @click="dialogOpen = true"><Plus :size="15" /> 创建任务</button></section>
    <section class="task-stats">
      <article><span class="mini-icon"><Inbox :size="16" /></span><div><small>待领取</small><strong>{{ count('READY') }}</strong></div></article>
      <article><span class="mini-icon"><Activity :size="16" /></span><div><small>运行中</small><strong>{{ runningCount }}</strong></div></article>
      <article data-tone="warning"><span class="mini-icon"><Hand :size="16" /></span><div><small>等待人工</small><strong>{{ count('WAIT_HUMAN') }}</strong></div></article>
      <article data-tone="success"><span class="mini-icon"><CheckCircle2 :size="16" /></span><div><small>已完成</small><strong>{{ count('COMPLETED') }}</strong></div></article>
    </section>
    <div class="filter-bar task-filters"><div class="search-box"><Search :size="15" /><input v-model="query" placeholder="搜索任务 ID / 标题" /></div><select v-model="source"><option value="">全部来源</option><option value="nr_test_system">nr_test_system</option><option value="manual">手工创建</option></select><select v-model="status"><option value="">全部状态</option><option v-for="item in statuses" :key="item" :value="item">{{ statusLabel(item) }}</option></select><select v-model="priority"><option value="">全部优先级</option><option v-for="item in ['P0','P1','P2','P3']" :key="item">{{ item }}</option></select><button class="button button--ghost" @click="resetFilters"><RotateCcw :size="14" /> 重置</button></div>
    <AstraPanel flush>
      <template #title><div class="table-title"><h2>任务队列</h2><span>{{ filtered.length }} 项</span></div></template>
      <template #action><span class="live-hint"><i /> 数据库状态</span></template>
      <div class="table-wrap task-table"><table><thead><tr><th>任务</th><th>来源 / 类型</th><th>优先级</th><th>状态</th><th>分配员工</th><th>当前阶段</th><th>进度</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="task in filtered" :key="task.id"><td @click="openTask(task.id)"><strong>{{ task.id }}</strong><small>{{ task.title }}</small></td><td @click="openTask(task.id)"><strong class="secondary-strong">{{ sourceLabel(task.source) }}</strong><small>{{ task.task_type }}</small></td><td><span class="priority" :data-priority="task.priority">{{ task.priority }}</span></td><td><AstraStatusBadge :status="task.status" :pulse="['RUNNING','VERIFYING','RETRY'].includes(task.status)" /></td><td>{{ task.employee_id ?? '待分配' }}</td><td>{{ phaseLabel(task.current_phase) }}</td><td><span class="progress-value">{{ task.progress }}%</span><AstraProgress :value="task.progress" /></td><td>{{ formatTime(task.created_at) }}</td><td><div class="row-actions"><button title="详情" @click="openTask(task.id)"><Eye :size="14" /></button><button v-if="['READY','RUNNING','WAIT_HUMAN'].includes(task.status)" title="暂停" @click="action(task, 'pause')"><Pause :size="14" /></button><button v-if="['FAILED','WAIT_HUMAN'].includes(task.status)" title="重试" @click="action(task, 'retry')"><RotateCcw :size="14" /></button></div></td></tr><tr v-if="!filtered.length"><td colspan="9"><AstraEmptyState :icon="SearchX" title="没有匹配任务" description="调整搜索词或筛选条件后重试。" /></td></tr></tbody></table></div>
    </AstraPanel>
    <section class="alert-strip"><span><TriangleAlert :size="16" /></span><div><strong>异常关注</strong><p>{{ count('WAIT_HUMAN') }} 项等待人工 · {{ count('FAILED') }} 项失败 · 完成状态均已通过 Verifier</p></div><RouterLink to="/interventions">处理人工介入 <ArrowRight :size="14" /></RouterLink></section>

    <div v-if="dialogOpen" class="modal-backdrop" data-testid="task-create-modal" @click.self="dialogOpen = false"><form class="modal-card" @submit.prevent="createTask"><header><div><small>MANUAL TASK</small><h3>创建 Astra 任务</h3></div><button type="button" aria-label="关闭创建任务" @click="dialogOpen = false"><X :size="17" /></button></header><label>任务标题<input v-model="form.title" required placeholder="例如：生成登录流程自动化脚本" /></label><div class="form-grid"><label>任务类型<select v-model="form.task_type"><option value="script_generate">脚本生成</option><option value="script_review">代码检视</option><option value="script_execute">脚本执行</option><option value="script_repair">故障修复</option></select></label><label>优先级<select v-model="form.priority"><option>P0</option><option>P1</option><option>P2</option><option>P3</option></select></label></div><label>任务描述<textarea v-model="form.description" rows="3" placeholder="描述目标、范围与必要上下文" /></label><label>工程路径<input v-model="form.project_path" required placeholder="/absolute/path/to/nr_test_system" /></label><label>真实验证命令<input v-model="form.test_command" required placeholder="pytest tests/test_login.py -q" /></label><label>必需产物（可选，每行一个）<textarea v-model="requiredFiles" rows="2" placeholder="tests/test_login.py" /></label><label>完成标准<textarea v-model="dod" rows="2" placeholder="每行一条，例如：pytest 真实执行通过" /></label><div class="form-note"><ShieldCheck :size="15" /><span>任务不会因 OpenCode 自报完成而完成；Verifier 会在独立进程中执行上述命令。</span></div><footer><button type="button" class="button" @click="dialogOpen = false">取消</button><button class="button button--primary" :disabled="submitting"><LoaderCircle v-if="submitting" :size="14" class="spin" /> 创建并进入队列</button></footer></form></div>
  </div>
</template>
<script setup lang="ts">
import { Activity, ArrowRight, CheckCircle2, ClipboardList, Eye, Hand, Inbox, LoaderCircle, Pause, Plus, RotateCcw, Search, SearchX, ShieldCheck, TriangleAlert, X } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import type { Task } from '@/api/types'
import { api } from '@/api/client'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraProgress from '@/components/astra/AstraProgress.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
import { formatTime, phaseLabel, sourceLabel, statusLabel } from '@/utils/format'
const store = useAstraStore(); const router = useRouter(); const query = ref(''); const source = ref(''); const status = ref(''); const priority = ref(''); const dialogOpen = ref(false); const submitting = ref(false); const dod = ref(''); const requiredFiles = ref('')
const statuses = ['READY','CLAIMED','RUNNING','VERIFYING','RETRY','WAIT_HUMAN','PAUSED','COMPLETED','FAILED','CANCELLED']
const form = reactive({ title: '', task_type: 'script_generate', priority: 'P2', description: '', project_path: '', test_command: '' })
onMounted(() => store.refresh())
const filtered = computed(() => store.tasks.filter((task) => (!query.value || `${task.id}${task.title}`.toLowerCase().includes(query.value.toLowerCase())) && (!source.value || task.source === source.value) && (!status.value || task.status === status.value) && (!priority.value || task.priority === priority.value)))
const count = (value: string) => store.tasks.filter((task) => task.status === value).length
const runningCount = computed(() => store.tasks.filter((task) => ['CLAIMED','RUNNING','VERIFYING','RETRY'].includes(task.status)).length)
const resetFilters = () => { query.value = ''; source.value = ''; status.value = ''; priority.value = '' }
const openTask = (id: string) => router.push(`/tasks/${id}`)
async function action(task: Task, name: string) { try { await api.taskAction(task.id, name, { reason: '从任务中心操作' }); await store.refresh() } catch (error) { window.alert(error instanceof Error ? error.message : '操作失败') } }
async function createTask() { submitting.value = true; try { const task = await api.createTask({ title: form.title, task_type: form.task_type, priority: form.priority, description: form.description, source: 'manual', definition_of_done: dod.value.split('\n').map((item) => item.trim()).filter(Boolean), input: { project_path: form.project_path, verification: { test_command: form.test_command, required_files: requiredFiles.value.split('\n').map((item) => item.trim()).filter(Boolean) } } }); dialogOpen.value = false; await store.refresh(); openTask(task.id) } finally { submitting.value = false } }
</script>
