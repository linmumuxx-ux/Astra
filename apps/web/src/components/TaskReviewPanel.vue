<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { mutate, useResource } from '../api'
import { json } from '../format'
import type { Detail, Task } from '../types'
import ResourceState from './ResourceState.vue'
interface NativeEvidence { native_session_id: string; message_id: string; part_id: string; tool: string; state: string; input: unknown; exit_code: number | null; output: string; truncated: boolean; matches_submission: boolean }
interface CriterionDraft { passed: boolean; reason: string; evidence: string; excerpt: string }
const props = defineProps<{ task: Task; executions: Detail[] }>()
const execution = computed(() => props.executions.find(item => item.state === 'SUBMITTED' && !item.superseded_by))
const evidence = useResource<{ items: NativeEvidence[] }>(() => execution.value ? `/executions/${execution.value.id}/native-evidence` : '', { items: [] })
const drafts = ref<CriterionDraft[]>([]), outcome = ref('COMPLETED'), busy = ref(false), error = ref('')
const evidenceKey = (item: NativeEvidence) => `${item.native_session_id}/${item.message_id}/${item.part_id}`
watch(() => `${props.task.id}:${props.task.revision}`, () => { drafts.value = props.task.acceptance_criteria.map(() => ({ passed: false, reason: '', evidence: '', excerpt: '' })); error.value = '' }, { immediate: true })
async function submit() {
  if (!execution.value) return
  error.value = ''
  if (drafts.value.some(item => !item.reason.trim())) { error.value = '请逐条说明验收依据或未通过原因。'; return }
  if (outcome.value === 'COMPLETED' && drafts.value.some(item => !item.passed || !item.evidence || !item.excerpt.trim())) { error.value = '完成工作需要每条标准通过，并引用真实工具输出。'; return }
  busy.value = true
  try {
    await mutate(`/tasks/${props.task.id}/review`, {
      execution_id: execution.value.id, expected_task_revision: props.task.revision, outcome: outcome.value,
      criteria_results: drafts.value.map((item, criterion_index) => {
        const source = evidence.data.value.items.find(value => evidenceKey(value) === item.evidence)
        return { criterion_index, passed: item.passed, reason: item.reason, evidence: source ? [{ native_session_id: source.native_session_id, message_id: source.message_id, part_id: source.part_id, excerpt: item.excerpt }] : [] }
      }),
    })
    ElMessage.success('独立验收结论已保存')
  } catch (caught) { error.value = (caught as Error).message } finally { busy.value = false }
}
</script>
<template>
  <section class="review-panel" role="region" aria-label="逐条独立验收">
    <h3>逐条独立验收</h3><p class="caption">按原始标准审查原生工具结果，再记录完成、返工或等待人类的结论。</p>
    <ResourceState :loading="evidence.loading.value" :error="evidence.error.value" :empty="!evidence.data.value.items.length" description="当前执行没有可核验工具证据，不能完成工作" @retry="evidence.load">
      <el-collapse><el-collapse-item title="查看原生工具证据" name="evidence"><article v-for="item in evidence.data.value.items" :key="evidenceKey(item)" class="mini-card"><strong>{{ item.tool }} · {{ item.state }}</strong><p v-if="item.tool === 'bash'" class="caption">退出码：{{ item.exit_code ?? '未提供，不得推断成功' }}</p><pre v-if="item.input" class="code-block">{{ json(item.input) }}</pre><p v-if="item.state === 'completed' && !item.matches_submission" class="caption">此内容未匹配原提交证据哈希，不可作为通过依据。</p><p class="caption">{{ evidenceKey(item) }}</p><pre class="code-block">{{ item.output }}</pre><p v-if="item.truncated" class="caption">长输出仅显示前 20000 字符，请按具体片段引用。</p></article></el-collapse-item></el-collapse>
    </ResourceState>
    <el-form label-position="top" @submit.prevent="submit">
      <article v-for="(criterion, index) in task.acceptance_criteria" :key="index" class="mini-card">
        <strong>标准 {{ index + 1 }} · {{ criterion }}</strong>
        <el-checkbox v-model="drafts[index]!.passed" :aria-label="`标准 ${index + 1} 已通过`">此标准已独立审查通过</el-checkbox>
        <el-form-item :label="`标准 ${index + 1} 的验收依据`" required><el-input v-model="drafts[index]!.reason" type="textarea" :rows="2" :aria-label="`标准 ${index + 1} 的验收依据`"/></el-form-item>
        <el-form-item :label="`标准 ${index + 1} 的证据`"><el-select v-model="drafts[index]!.evidence" filterable clearable :aria-label="`标准 ${index + 1} 的证据`"><el-option v-for="item in evidence.data.value.items.filter(value => value.state === 'completed' && value.matches_submission)" :key="evidenceKey(item)" :value="evidenceKey(item)" :label="`${item.tool} · ${item.part_id}`"/></el-select></el-form-item>
        <el-form-item v-if="drafts[index]!.evidence" :label="`标准 ${index + 1} 的原文摘录`"><el-input v-model="drafts[index]!.excerpt" type="textarea" :rows="2" :aria-label="`标准 ${index + 1} 的原文摘录`" placeholder="引用工具输出中的实际文字，后端将重新核验"/></el-form-item>
      </article>
      <el-form-item label="验收结论"><el-select v-model="outcome" aria-label="验收结论"><el-option label="完成工作" value="COMPLETED"/><el-option label="要求返工" value="REWORK"/><el-option label="等待人类处理" value="WAIT_HUMAN"/></el-select></el-form-item>
      <el-alert v-if="error" :title="error" type="error" :closable="false"/><el-button type="primary" :loading="busy" @click="submit">提交验收结论</el-button>
    </el-form>
  </section>
</template>
