<template>
  <div class="page" data-testid="intervention-page">
    <section class="page-intro compact-intro"><div><h2>待处理</h2><p>统一处理人工协助、结果确认、执行异常和长时间无活动提示。</p></div><span class="intervention-count"><i /> {{ tasks.length }} 项待处理</span></section>
    <div class="filter-tabs pending-tabs"><button v-for="item in filters" :key="item.value" :class="{ active: filter === item.value }" @click="filter = item.value">{{ item.label }} <span>{{ item.count }}</span></button></div>
    <section class="intervention-layout">
      <AstraPanel title="处理队列" subtitle="异常和需要人工决策的任务" flush><div class="intervention-queue"><button v-for="task in filtered" :key="task.id" :class="{ active: selected?.id === task.id }" @click="selectedId = task.id"><component :is="queueIcon(task)" :size="17" /><div><strong>{{ task.title }}</strong><p>{{ task.runtime_status_label }} · {{ employeeName(task.employee_id) }}</p></div><time>{{ formatTime(task.updated_at) }}</time><ChevronRight :size="14" /></button><AstraEmptyState v-if="!filtered.length" :icon="CheckCircle2" title="当前分类无待处理项" description="新的协助、确认或异常会显示在这里。" /></div></AstraPanel>
      <div class="intervention-workbench"><AstraPanel v-if="selected" :title="selected.title" :subtitle="selected.id">
        <div class="intervention-warning"><component :is="queueIcon(selected)" :size="18" /><div><strong>{{ statusLabel(selected.status) }}</strong><p>{{ pendingReason(selected) }}</p></div></div>
        <dl class="info-list compact-info"><div><dt>当前进展</dt><dd>{{ platformCopy(selected.current_progress) }}</dd></div><div><dt>执行员工</dt><dd>{{ employeeName(selected.employee_id) }}</dd></div><div><dt>最后活动</dt><dd>{{ formatTime(selected.last_activity_at) }}</dd></div><div><dt>执行会话</dt><dd>{{ selected.opencode_session_id ?? '尚未创建' }}</dd></div></dl>
        <div v-if="selected.status === 'PENDING_CONFIRMATION' && selected.result" class="work-result"><strong>员工提交结果</strong><p>{{ selected.result.summary }}</p></div>
        <form v-if="selected.status === 'WAIT_HUMAN'" class="intervention-form config-form" @submit.prevent="resume"><label>补充信息<textarea v-model.trim="note" required placeholder="输入权限、业务判断或环境说明" /></label><footer><button type="button" class="button button--danger" @click="cancel">终止任务</button><RouterLink class="button" :to="`/tasks/${selected.id}`">查看详情</RouterLink><button class="button button--primary">补充并继续</button></footer></form>
        <footer v-else class="pending-actions"><RouterLink class="button" :to="`/tasks/${selected.id}`">查看详情</RouterLink><template v-if="selected.status === 'PENDING_CONFIRMATION'"><button class="button button--danger" @click="reject">退回继续</button><button class="button button--primary" @click="confirm">确认完成</button></template><button v-else-if="selected.status === 'EXECUTION_ERROR'" class="button button--primary" @click="recover">恢复执行</button><button v-else-if="selected.status === 'SUSPENDED'" class="button button--primary" @click="resume">恢复到队列</button><button v-else-if="selected.inactivity_alert" class="button" @click="openTask">检查任务</button></footer>
      </AstraPanel><AstraPanel v-else title="待处理"><AstraEmptyState :icon="Hand" title="选择一项任务" description="在左侧选择需要处理的任务。" /></AstraPanel></div>
    </section>
  </div>
</template>
<script setup lang="ts">
import { CheckCircle2, ChevronRight, CircleAlert, Hand, PauseCircle, ShieldCheck, TriangleAlert } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { Task } from '@/api/types'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import { useAstraStore } from '@/stores/astra'
import { employeeDisplayName, formatTime, platformCopy, statusLabel } from '@/utils/format'
const store = useAstraStore(); const router = useRouter(); const selectedId = ref(''); const note = ref(''); const filter = ref('ALL')
const tasks = computed(() => store.tasks.filter((task) => ['WAIT_HUMAN', 'SUSPENDED', 'PENDING_CONFIRMATION', 'EXECUTION_ERROR'].includes(task.status) || task.inactivity_alert))
const filtered = computed(() => filter.value === 'ALL' ? tasks.value : filter.value === 'INACTIVE' ? tasks.value.filter((task) => task.inactivity_alert) : tasks.value.filter((task) => task.status === filter.value))
const filters = computed(() => [{ value: 'ALL', label: '全部', count: tasks.value.length }, { value: 'WAIT_HUMAN', label: '人工协助', count: tasks.value.filter((t) => t.status === 'WAIT_HUMAN').length }, { value: 'PENDING_CONFIRMATION', label: '待确认', count: tasks.value.filter((t) => t.status === 'PENDING_CONFIRMATION').length }, { value: 'EXECUTION_ERROR', label: '执行异常', count: tasks.value.filter((t) => t.status === 'EXECUTION_ERROR').length }, { value: 'SUSPENDED', label: '已挂起', count: tasks.value.filter((t) => t.status === 'SUSPENDED').length }, { value: 'INACTIVE', label: '无活动', count: tasks.value.filter((t) => t.inactivity_alert).length }])
const selected = computed(() => filtered.value.find((task) => task.id === selectedId.value) ?? filtered.value[0])
watch(selected, () => { note.value = '' })
const employeeName = (id: string | null) => employeeDisplayName(store.employees.find((item) => item.id === id)?.name ?? '未分配')
const queueIcon = (task: Task) => task.status === 'PENDING_CONFIRMATION' ? ShieldCheck : task.status === 'EXECUTION_ERROR' ? TriangleAlert : task.status === 'SUSPENDED' ? PauseCircle : task.inactivity_alert ? CircleAlert : Hand
const pendingReason = (task: Task) => task.status === 'WAIT_HUMAN' ? (task.human_intervention?.blocking_reason ?? task.human_required_reason ?? '需要人工补充信息') : task.status === 'PENDING_CONFIRMATION' ? '请检查工作结果后确认或退回' : task.status === 'EXECUTION_ERROR' ? String(task.execution_error?.reason ?? '执行环境异常，工作现场已保留') : task.status === 'SUSPENDED' ? String(task.suspension?.reason ?? '任务已安全挂起') : '长时间没有新的可观察活动'
async function act(action: string, body: Record<string, unknown> = {}) { if (!selected.value) return; await api.taskAction(selected.value.id, action, body); await store.refresh() }
async function resume() { await act('resume', note.value ? { note: note.value } : {}) }
async function cancel() { if (selected.value && window.confirm('确定终止这项任务吗？')) await act('cancel', { reason: '人工决定终止' }) }
async function confirm() { await act('confirm') }
async function reject() { const feedback = window.prompt('请输入退回原因与补充要求：'); if (feedback) await act('reject', { feedback }) }
async function recover() { await act('recover') }
function openTask() { if (selected.value) router.push(`/tasks/${selected.value.id}`) }
</script>
