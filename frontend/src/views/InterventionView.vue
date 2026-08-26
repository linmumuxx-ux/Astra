<template>
  <div class="page" data-testid="intervention-page">
    <section class="page-intro compact-intro"><div><span class="kicker warning-kicker"><Hand :size="13" /> HUMAN IN THE LOOP</span><h2>人工介入中心</h2><p>仅处理数字员工无法自主完成的环境、权限、信息与业务判断问题。</p></div><span class="intervention-count"><i /> {{ waiting.length }} 项等待处理</span></section>
    <div v-if="waiting.length" class="intervention-layout">
      <AstraPanel title="等待队列" subtitle="按优先级与等待时长排序" flush><div class="intervention-queue"><button v-for="task in waiting" :key="task.id" :class="{ active: selected?.id === task.id }" @click="selectedId = task.id"><span class="priority" :data-priority="task.priority">{{ task.priority }}</span><div><strong>{{ task.title }}</strong><p>{{ task.id }} · {{ sourceLabel(task.source) }}</p></div><time>{{ formatDuration(task.updated_at) }}</time><ChevronRight :size="16" /></button></div></AstraPanel>
      <div v-if="selected" class="intervention-workbench">
        <AstraPanel title="需要人工输入" subtitle="补充信息后优先恢复原 Workspace 与 Session"><div class="intervention-warning"><TriangleAlert :size="18" /><div><strong>{{ selected.human_required_reason }}</strong><p>当前阶段：{{ phaseLabel(selected.current_phase) }} · 自动修复 {{ selected.retry_count }}/{{ selected.max_retry_count }}</p></div></div><dl class="info-list compact-info"><div><dt>数字员工</dt><dd>{{ selected.employee_id ?? '未分配' }}</dd></div><div><dt>Workspace</dt><dd :title="selected.workspace ?? ''">{{ selected.workspace ?? '待创建' }}</dd></div><div><dt>Session</dt><dd :title="selected.opencode_session_id ?? ''">{{ selected.opencode_session_id ?? '待创建' }}</dd></div></dl></AstraPanel>
        <AstraPanel title="人工操作" subtitle="输入将追加到任务上下文并形成 Event"><form class="intervention-form" @submit.prevent="resume"><label>处理说明<textarea v-model="note" rows="5" placeholder="说明环境已恢复、补充缺失参数或给出业务判断..." required /></label><label>补充信息（可选）<textarea v-model="inputText" rows="3" placeholder="将以 human_input 字段追加到任务 input" /></label><div class="form-note"><ShieldCheck :size="15" /><span>继续后恢复原 Session，不会丢弃已有分析、代码修改和验证证据。</span></div><footer><button type="button" class="button button--danger" @click="cancel"><Square :size="13" /> 终止任务</button><button class="button button--primary"><Play :size="14" /> 补充并继续</button></footer></form></AstraPanel>
      </div>
    </div>
    <AstraPanel v-else><AstraEmptyState :icon="BadgeCheck" title="没有等待人工的任务" description="所有数字员工当前都能自主推进，或任务已进入终态。"><RouterLink class="button" to="/tasks">查看任务中心</RouterLink></AstraEmptyState></AstraPanel>
  </div>
</template>
<script setup lang="ts">
import { BadgeCheck, ChevronRight, Hand, Play, ShieldCheck, Square, TriangleAlert } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import AstraEmptyState from '@/components/astra/AstraEmptyState.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import { useAstraStore } from '@/stores/astra'
import { formatDuration, phaseLabel, sourceLabel } from '@/utils/format'
const store = useAstraStore(); const selectedId = ref(''); const note = ref(''); const inputText = ref('')
const waiting = computed(() => store.tasks.filter((task) => task.status === 'WAIT_HUMAN').sort((a,b) => b.priority.localeCompare(a.priority)))
const selected = computed(() => waiting.value.find((task) => task.id === selectedId.value) ?? waiting.value[0])
onMounted(() => store.refresh()); watch(selected, () => { note.value = ''; inputText.value = '' })
async function resume() { if (!selected.value) return; await api.taskAction(selected.value.id, 'resume', { note: note.value, input_patch: inputText.value ? { human_input: inputText.value } : undefined }); await store.refresh() }
async function cancel() { if (!selected.value || !window.confirm('确定终止这项任务吗？')) return; await api.taskAction(selected.value.id, 'cancel', { reason: note.value || '人工终止' }); await store.refresh() }
</script>
