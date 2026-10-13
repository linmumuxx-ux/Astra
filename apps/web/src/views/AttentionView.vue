<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, CircleHelp, Clock3, ShieldCheck, X } from 'lucide-vue-next'
import { mutate, useResource } from '../api'
import type { AuditEvent, Operation } from '../types'
import { date, json } from '../format'
import PageTitle from '../components/PageTitle.vue'
import ResourceState from '../components/ResourceState.vue'
import StatusTag from '../components/StatusTag.vue'
const inbox = useResource<Operation[]>('/human-inbox', [])
const operations = useResource<Operation[]>('/operations', [])
const events = useResource<AuditEvent[]>('/audit-events', [])
const tab = ref('decisions'), busy = ref('')
const decisions = computed(() => inbox.data.value.filter(item => !['QUESTION','RISK','REPORT'].includes(String(item.payload?.category || ''))))
const questions = computed(() => inbox.data.value.filter(item => item.payload?.category === 'QUESTION'))
const risks = computed(() => inbox.data.value.filter(item => item.payload?.category === 'RISK'))
const reports = computed(() => inbox.data.value.filter(item => item.payload?.category === 'REPORT'))
const visible = computed(() => tab.value === 'decisions' ? decisions.value : tab.value === 'questions' ? questions.value : tab.value === 'risks' ? risks.value : tab.value === 'reports' ? reports.value : operations.data.value.filter(item => item.status !== 'WAIT_HUMAN'))
async function decide(operation: Operation, action: string) {
  let reason = ''
  try {
    if (action === 'approve') await ElMessageBox.confirm(`批准 ${operation.action}，仅对资源 ${operation.target_id} 和当前策略版本 ${operation.policy_revision} 生效。`, '批准具体操作', { confirmButtonText: '确认批准', cancelButtonText: '返回审阅', type: 'warning' })
    else { const result = await ElMessageBox.prompt(action === 'reject' ? '说明拒绝原因，帮助提出者理解你的决定。' : '说明需修改的边界或需要补充的分析。当前操作不会直接执行。', action === 'reject' ? '拒绝操作' : '要求修改与补充', { inputType: 'textarea', inputValidator: value => !!value?.trim() || '请填写原因', confirmButtonText: '提交', cancelButtonText: '取消' }); reason = result.value }
  } catch { return }
  busy.value = operation.id
  try { await mutate(`/operations/${operation.id}/${action}`, { reason }); ElMessage.success('决策已记录，正在刷新操作结果') } catch (caught) { ElMessage.error((caught as Error).message) } finally { busy.value = '' }
}
</script>
<template>
  <PageTitle title="需要我处理" subtitle="把具体业务判断放在一起；查看消息不会被视为批准或处理。" eyebrow="HUMAN / ACTION REQUIRED"><el-tag type="warning" round>{{ inbox.data.value.length }} 项待处理</el-tag></PageTitle>
  <div class="attention-layout"><section><el-tabs v-model="tab"><el-tab-pane :label="`需要我决策 ${decisions.length}`" name="decisions"/><el-tab-pane :label="`需要我回答 ${questions.length}`" name="questions"/><el-tab-pane label="风险关注" name="risks"/><el-tab-pane label="工作汇报" name="reports"/><el-tab-pane label="处理记录" name="history"/></el-tabs>
      <ResourceState :loading="tab === 'history' ? operations.loading.value : inbox.loading.value" :error="tab === 'history' ? operations.error.value : inbox.error.value" :empty="!visible.length" description="此分类暂无待处理事项" @retry="inbox.load(); operations.load()"><article v-for="operation in visible" :key="operation.id" class="panel decision-card"><div class="spread"><span class="eyebrow">SCOPED OPERATION</span><StatusTag :value="operation.status"/></div><h2>{{ operation.action }}</h2><p class="muted">提出者 {{ operation.initiator_id }} · 目标版本 {{ operation.target_revision }}</p><dl class="detail-list"><dt>具体资源</dt><dd>{{ operation.target_id }}</dd><dt>作用范围</dt><dd>{{ operation.team_id }}</dd><dt>审批有效期</dt><dd>{{ date(operation.expires_at) }}</dd><dt>策略版本</dt><dd>{{ operation.policy_revision }}</dd></dl><el-collapse><el-collapse-item title="操作参数、影响与证据" name="payload"><pre class="code-block">{{ json(operation.payload) }}</pre></el-collapse-item></el-collapse><pre v-if="operation.result" class="code-block">{{ json(operation.result) }}</pre><div v-if="operation.status === 'WAIT_HUMAN'" class="action-row"><el-button type="primary" :icon="Check" :loading="busy === operation.id" @click="decide(operation, 'approve')">批准本次操作</el-button><el-button :icon="X" :loading="busy === operation.id" @click="decide(operation, 'reject')">拒绝</el-button><el-button text :icon="CircleHelp" :loading="busy === operation.id" @click="decide(operation, 'request-changes')">修改 / 补充分析</el-button></div></article></ResourceState>
    </section><aside><section class="panel decision-guide"><ShieldCheck :size="26" :stroke-width="1.5"/><h2>你的决策职责</h2><h3>员工自主推进</h3><p>已授权范围内的查询、分析和常规工作，由员工自主判断并保留行动记录。</p><div class="divider"></div><h3>人来决定</h3><p>跨权修改、生产发布、重大风险、权限扩张与冲突取舍，需要明确的具体授权。</p><div class="soft-note"><Clock3 :size="16"/><p>状态、权限或策略变更会使旧批准失效；后台执行前重新校验，并记录唯一副作用结果。</p></div></section><section class="panel recent-decisions"><h3>最近可信动态</h3><ResourceState :loading="events.loading.value" :error="events.error.value" :empty="!events.data.value.length" description="暂无可见动态" @retry="events.load"><div v-for="event in events.data.value.slice(-4).reverse()" :key="event.seq" class="activity-row"><span class="activity-dot"></span><div><p>{{ event.summary }}</p><small>{{ date(event.created_at) }}</small></div></div></ResourceState></section></aside>
  </div>
</template>
