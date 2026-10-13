<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRightLeft, ExternalLink, Pause, Play, Plus, Search } from 'lucide-vue-next'
import { mutate, principal, useResource } from '../api'
import type { Detail, Employee, Handoff, Task } from '../types'
import { date, json, safeLink } from '../format'
import PageTitle from '../components/PageTitle.vue'
import ResourceState from '../components/ResourceState.vue'
import StatusTag from '../components/StatusTag.vue'
import EntityForm from '../components/EntityForm.vue'
import TaskReviewPanel from '../components/TaskReviewPanel.vue'
import NativeEvidence from '../components/NativeEvidence.vue'
const route = useRoute(), router = useRouter()
const tasks = useResource<Task[]>('/tasks', [])
const employees = useResource<Employee[]>('/employees', [])
const handoffs = useResource<Handoff[]>('/handoffs', [])
const query = ref(''), filter = ref('all'), creating = ref(false), actionBusy = ref(''), handoffDialog = ref(false), handoffTarget = ref(''), handoffReason = ref(''), handoffError = ref(''), iframeVisible = ref(false)
const id = computed(() => typeof route.params.id === 'string' ? route.params.id : '')
const detail = useResource<Task | null>(() => id.value ? `/tasks/${id.value}` : '', null)
const task = computed(() => detail.data.value || tasks.data.value.find(item => item.id === id.value))
const executions = useResource<Detail[]>(() => id.value ? `/tasks/${id.value}/executions` : '', [])
const evidence = useResource<Detail[]>(() => id.value ? `/tasks/${id.value}/evidence` : '', [])
const workspace = useResource<Detail>(() => id.value ? `/tasks/${id.value}/workspace` : '', {})
const selectedEvidence = ref('')
const reviews = useResource<Detail[]>(() => id.value ? `/tasks/${id.value}/reviews` : '', [])
const workspaceUrl = computed(() => safeLink(workspace.data.value.url))
const list = computed(() => tasks.data.value.filter(item => (!query.value || `${item.title} ${item.objective}`.toLowerCase().includes(query.value.toLowerCase())) && (filter.value === 'all' || filter.value === 'done' ? filter.value === 'all' || item.status === 'COMPLETED' : filter.value === 'attention' ? ['REVIEW','RECONCILE_REQUIRED'].includes(item.status) : !['COMPLETED','CANCELLED'].includes(item.status))))
const taskHandoffs = computed(() => handoffs.data.value.filter(item => item.task_id === id.value))
const handoffEvents = useResource<Detail[]>(() => id.value ? `/tasks/${id.value}/handoff-events` : '', [])
function owner(value: string | null) { return employees.data.value.find(item => item.id === value)?.name || (value ? value.slice(0,8) : '历史无业务主责') }
async function action(name: string) {
  if (!task.value) return
  if (name === 'cancel') { try { await ElMessageBox.confirm('停止该业务工作后，运行中的副作用仍须以真实执行结果对账。', '取消工作', { confirmButtonText: '确认取消', cancelButtonText: '继续工作', type: 'warning' }) } catch { return } }
  actionBusy.value = name
  try { await mutate(`/tasks/${id.value}/${name}`); ElMessage.success('操作已记录') } catch (caught) { ElMessage.error((caught as Error).message) } finally { actionBusy.value = '' }
}
async function handoff() {
  if (!handoffTarget.value || !handoffReason.value.trim()) { handoffError.value = '请选择接收员工并说明交接原因与证据。'; return }
  actionBusy.value = 'handoff'; handoffError.value = ''
  try { await mutate(`/tasks/${id.value}/handoff`, { target_employee_id: handoffTarget.value, reason: handoffReason.value }); handoffDialog.value = false; ElMessage.success('已发起正式交接，签收前主责保持原归属') } catch (caught) { handoffError.value = (caught as Error).message } finally { actionBusy.value = '' }
}
async function accept(handoff: Handoff) { actionBusy.value = handoff.id; try { await mutate(`/handoffs/${handoff.id}/accept`); ElMessage.success('交接已签收') } catch (caught) { ElMessage.error((caught as Error).message) } finally { actionBusy.value = '' } }
function represents(employeeId: string) { return principal.value?.id === employeeId || employees.data.value.find(employee => employee.id === employeeId)?.manager_id === principal.value?.id }
async function respond(handoff: Handoff, name: string) {
  try {
    const result = await ElMessageBox.prompt('记录处理原因与需补充的信息；主责在签收前保持原归属。', '处理正式交接', { inputType: 'textarea', inputValidator: value => !!value.trim() || '请填写处理原因', confirmButtonText: '确认处理', cancelButtonText: '取消' })
    actionBusy.value = handoff.id
    await mutate(`/handoffs/${handoff.id}/${name}`, { reason: result.value }); ElMessage.success('交接处理已保存')
  } catch (caught) { if (caught instanceof Error) ElMessage.error(caught.message) } finally { actionBusy.value = '' }
}
</script>
<template>
  <PageTitle title="工作中心" subtitle="员工对业务结果负责，Worker 提供可调度执行能力，验收以真实证据为准。" eyebrow="WORK / DELIVERABLES & EVIDENCE"><RouterLink v-if="route.query.from" :to="`/employees/${route.query.from}`"><el-button :icon="ArrowLeft">回到员工对话</el-button></RouterLink><el-button type="primary" :icon="Plus" @click="creating = true">创建工作</el-button></PageTitle>
  <div class="work-toolbar"><el-radio-group v-model="filter"><el-radio-button value="all">全部工作</el-radio-button><el-radio-button value="progress">推进中</el-radio-button><el-radio-button value="attention">待处理</el-radio-button><el-radio-button value="done">已完成</el-radio-button></el-radio-group><el-input v-model="query" :prefix-icon="Search" placeholder="搜索工作与目标" aria-label="搜索工作" clearable/></div>
  <div class="work-layout" :class="{ 'has-detail': id }"><section class="panel task-list"><ResourceState :loading="tasks.loading.value" :error="tasks.error.value" :empty="!list.length" description="暂无符合条件的工作" @retry="tasks.load"><el-table :data="list" highlight-current-row :current-row-key="id" row-key="id" @row-click="(row: Task) => router.push({ path: `/tasks/${row.id}`, query: route.query })"><el-table-column label="工作 / 交付目标" min-width="230"><template #default="{ row }"><div class="table-title"><strong>{{ row.title }}</strong><small>{{ row.objective }}</small></div></template></el-table-column><el-table-column label="主责员工" min-width="110"><template #default="{ row }">{{ owner(row.owner_employee_id) }}</template></el-table-column><el-table-column label="业务状态" width="130"><template #default="{ row }"><StatusTag :value="row.status"/></template></el-table-column><el-table-column v-if="!id" label="最近变化" min-width="170"><template #default="{ row }">{{ date(row.updated_at || row.created_at) }}</template></el-table-column></el-table></ResourceState></section>
    <section v-if="id" class="panel task-detail"><ResourceState :loading="detail.loading.value && !task" :error="detail.error.value" :empty="!task" description="工作不存在或不可见" @retry="detail.load"><template v-if="task"><div class="spread"><span class="eyebrow">BUSINESS TASK</span><StatusTag :value="task.status"/></div><h2>{{ task.title }}</h2><p class="task-objective">{{ task.objective }}</p><div class="task-meta"><span>主责 <RouterLink v-if="task.owner_employee_id" :to="`/employees/${task.owner_employee_id}`">{{ owner(task.owner_employee_id) }}</RouterLink><b v-else>历史无业务主责</b></span><span>风险 <StatusTag :value="task.risk_level"/></span><span>版本 {{ task.revision }}</span></div><el-alert v-if="task.read_only" title="历史只读工作：执行来源与证据仍可查询。" type="info" :closable="false"/>
      <h3>验收标准</h3><ol class="criteria"><li v-for="criterion in task.acceptance_criteria" :key="criterion">{{ criterion }}</li></ol>
      <div v-if="!task.read_only && !['COMPLETED','CANCELLED'].includes(task.status)" class="action-row"><el-button v-if="task.status !== 'PAUSED'" :icon="Pause" :loading="actionBusy === 'pause'" @click="action('pause')">暂停</el-button><el-button v-else :icon="Play" :loading="actionBusy === 'resume'" @click="action('resume')">恢复</el-button><el-button :icon="ArrowRightLeft" @click="handoffDialog = true">正式交接</el-button><el-button text type="danger" :loading="actionBusy === 'cancel'" @click="action('cancel')">取消工作</el-button></div>
      <div class="divider"></div><h3>结果与真实证据</h3><div v-for="review in reviews.data.value" :key="String(review.id)" class="mini-card"><div class="spread"><strong>独立验收结论</strong><StatusTag :value="String(review.outcome)"/></div><p v-for="result in (review.criteria_results as Detail[])" :key="Number(result.criterion_index)"><strong>标准 {{ Number(result.criterion_index) + 1 }} · {{ result.passed ? '已通过' : '未通过' }}</strong><br/>{{ result.reason }}</p></div><ResourceState :loading="evidence.loading.value" :error="evidence.error.value" :empty="!evidence.data.value.length" description="尚未提交可见证据" @retry="evidence.load"><div v-for="(item, index) in evidence.data.value" :key="index" class="evidence-card"><div class="spread"><strong>执行 {{ index + 1 }} · {{ Array.isArray(item.refs) ? item.refs.length : 0 }} 项证据</strong><el-button v-if="executions.data.value.find(value => value.id === item.execution_id)?.permission_digest" @click="selectedEvidence = String(item.execution_id)">查看原生证据</el-button></div><el-collapse><el-collapse-item title="证据来源索引" :name="String(index)"><pre class="code-block">{{ json(item) }}</pre></el-collapse-item></el-collapse></div></ResourceState>
      <TaskReviewPanel v-if="task.status === 'REVIEW'" :task="task" :executions="executions.data.value"/><h3>正式交接记录</h3><ResourceState :loading="handoffs.loading.value" :error="handoffs.error.value" :empty="!taskHandoffs.length" description="没有正式交接记录" @retry="handoffs.load"><div v-for="item in taskHandoffs" :key="item.id" class="mini-card"><div class="spread"><strong>{{ owner(item.source_employee_id) }} → {{ owner(item.target_employee_id) }}</strong><StatusTag :value="item.status"/></div><p>{{ item.reason }}</p><div v-for="event in handoffEvents.data.value.filter(event => event.source_id === item.id)" :key="String(event.id)" class="caption"><strong>{{ (event.payload_ref as Detail).action }}</strong> · {{ (event.payload_ref as Detail).reason }}</div><el-button v-if="item.status === 'PROPOSED' && represents(item.target_employee_id)" :loading="actionBusy === item.id" @click="accept(item)">签收主责</el-button><template v-if="['PROPOSED','NEEDS_CLARIFICATION'].includes(item.status)"><el-button v-if="represents(item.target_employee_id)" :loading="actionBusy === item.id" @click="respond(item, 'reject')">拒绝交接</el-button><el-button v-if="item.status === 'PROPOSED' && represents(item.target_employee_id)" @click="respond(item, 'request-clarification')">请求澄清</el-button><el-button v-if="item.status === 'NEEDS_CLARIFICATION' && represents(item.source_employee_id)" @click="respond(item, 'clarify')">补充说明</el-button><el-button v-if="represents(item.source_employee_id)" @click="respond(item, 'withdraw')">撤回交接</el-button></template></div></ResourceState>
      <el-collapse><el-collapse-item title="执行与 OpenCode 诊断" name="executions"><ResourceState :loading="executions.loading.value" :error="executions.error.value" :empty="!executions.data.value.length" description="尚未绑定执行会话" @retry="executions.load"><div v-for="execution in executions.data.value" :key="String(execution.id)" class="mini-card"><div class="spread"><strong>执行 {{ execution.attempt_no }}</strong><StatusTag :value="String(execution.state || '')"/></div><dl class="detail-list"><dt>Worker</dt><dd>{{ execution.worker_id }}</dd><dt>原生 Session</dt><dd>{{ execution.native_session_id || '尚未绑定' }}</dd><dt>工作区</dt><dd>{{ execution.workspace_ref || '尚未分配' }}</dd><dt>产物版本</dt><dd>{{ execution.artifact_commit || '尚未保存' }}</dd><dt>续做来源</dt><dd>{{ execution.continued_from_execution_id || '首次执行' }}</dd><dt>后继轮次</dt><dd>{{ execution.superseded_by || '无' }}</dd></dl></div></ResourceState><ResourceState :loading="workspace.loading.value" :error="workspace.error.value" @retry="workspace.load"><template v-if="workspaceUrl"><div class="action-row"><el-button :icon="ExternalLink" @click="iframeVisible = !iframeVisible">{{ iframeVisible ? '收起' : '展开' }}原生工作区</el-button><a :href="workspaceUrl" target="_blank" rel="noopener" class="text-link">独立窗口打开</a></div><iframe v-if="iframeVisible" :src="workspaceUrl" class="native-workspace" title="OpenCode 原生工程工作区" referrerpolicy="no-referrer"/></template><p v-else class="muted">当前没有可访问的原生工作区入口。</p></ResourceState></el-collapse-item></el-collapse>
    </template></ResourceState></section>
  </div>
  <el-dialog :model-value="!!selectedEvidence" title="原生执行证据" width="min(900px, 95vw)" @close="selectedEvidence = ''"><NativeEvidence v-if="selectedEvidence" :execution-id="selectedEvidence"/></el-dialog>
  <EntityForm v-model="creating" kind="task" @created="(result: unknown) => router.push(`/tasks/${(result as Task).id}`)"/>
  <el-dialog v-model="handoffDialog" title="正式交接业务主责" width="500px"><el-form label-position="top" @submit.prevent="handoff"><el-form-item label="接收员工" required><el-select v-model="handoffTarget" filterable placeholder="选择接收员工" aria-label="接收员工"><el-option v-for="employee in employees.data.value.filter(item => item.id !== task?.owner_employee_id && item.lifecycle === 'ACTIVE' && item.team_id === task?.team_id)" :key="employee.id" :label="employee.name" :value="employee.id"/></el-select></el-form-item><el-form-item label="交接原因与证据" required><el-input v-model="handoffReason" type="textarea" :rows="4" aria-label="交接原因与证据"/></el-form-item><el-alert v-if="handoffError" :title="handoffError" type="error" :closable="false"/><p class="caption">签收前原主责不变，接收员工须在自己的授权范围内接受。</p></el-form><template #footer><el-button @click="handoffDialog = false">取消</el-button><el-button type="primary" :loading="actionBusy === 'handoff'" @click="handoff">发起交接</el-button></template></el-dialog>
</template>
