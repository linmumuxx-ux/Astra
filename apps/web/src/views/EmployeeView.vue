<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowUpRight, Pause, Play, Plus } from 'lucide-vue-next'
import { ApiError, mutate, token, useResource } from '../api'
import type { Channel, Detail, Employee, Goal, Role, Routine, Task } from '../types'
import { date, json } from '../format'
import PageTitle from '../components/PageTitle.vue'
import ResourceState from '../components/ResourceState.vue'
import StatusTag from '../components/StatusTag.vue'
import EntityForm from '../components/EntityForm.vue'
import ChatThread from '../components/ChatThread.vue'
import MemoryPanel from '../components/MemoryPanel.vue'
import PersonaInbox from '../components/PersonaInbox.vue'
const route = useRoute(), router = useRouter()
const employees = useResource<Employee[]>('/employees', [])
const roles = useResource<Role[]>('/roles', [])
const employee = computed(() => employees.data.value.find(item => item.id === route.params.id))
const id = computed(() => employee.value?.id || '')
const work = useResource<Task[]>(() => id.value ? `/employees/${id.value}/work` : '', [])
const goals = useResource<Goal[]>(() => id.value ? `/employees/${id.value}/goals` : '', [])
const routines = useResource<Routine[]>(() => id.value ? `/employees/${id.value}/routines` : '', [])
const dashboard = useResource<Detail>(() => id.value ? `/employees/${id.value}/dashboard` : '', {})
const plan = computed(() => (dashboard.data.value.state as Detail | undefined)?.plan_digest)
const tab = ref('work'), form = ref(''), channel = ref(''), dmLoading = ref(false), dmError = ref<ApiError | null>(null), actionLoading = ref(false)
watch(() => employees.data.value, list => { if (!route.params.id && list[0]) router.replace(`/employees/${list[0].id}`) })
let dmSerial = 0
async function connectDm() {
  const current = ++dmSerial; channel.value = ''; dmError.value = null
  if (!id.value || !token.value) return
  dmLoading.value = true
  try { const result = await mutate<Channel>(`/employees/${id.value}/dm`); if (current === dmSerial) channel.value = result.id }
  catch (caught) { if (current === dmSerial) dmError.value = caught as ApiError }
  finally { if (current === dmSerial) dmLoading.value = false }
}
watch([id, token], connectDm, { immediate: true })
async function action(name: string) {
  if (!employee.value) return
  if (name === 'archive') { try { await ElMessageBox.confirm('归档前必须完成在途工作和目标交接。后端会检查责任连续性，归档后停止自主唤醒。', `归档 ${employee.value.name}`, { confirmButtonText: '提交归档', cancelButtonText: '取消', type: 'warning' }) } catch { return } }
  actionLoading.value = true
  try { await mutate(`/employees/${id.value}/${name}`, { revision: employee.value.revision }); ElMessage.success('操作已记录') } catch (caught) { ElMessage.error((caught as Error).message) } finally { actionLoading.value = false }
}
async function routineAction(routine: Routine, name: string) {
  actionLoading.value = true
  try { await mutate(`/routines/${routine.id}/${name}`); ElMessage.success(name === 'run-now' ? '已进入员工工作收件箱' : '例程状态已更新') } catch (caught) { ElMessage.error((caught as Error).message) } finally { actionLoading.value = false }
}
</script>
<template>
  <PageTitle title="员工工作空间" subtitle="与你的员工保持长期对话，让责任、计划和工作持续相连。" eyebrow="PERSONA / ONGOING WORK"><el-button v-if="employee" :icon="Plus" @click="form = 'goal'">设定工作目标</el-button></PageTitle>
  <div class="workspace-layout"><aside class="panel roster"><div class="panel-heading"><h2>我的数字员工</h2><el-tag round>{{ employees.data.value.length }}</el-tag></div><ResourceState :loading="employees.loading.value" :error="employees.error.value" :empty="!employees.data.value.length" description="尚未配置数字员工" @retry="employees.load"><RouterLink v-for="item in employees.data.value" :key="item.id" :to="`/employees/${item.id}`" class="roster-item" :class="{ selected: item.id === id }"><span class="avatar">{{ item.name.slice(0,1) }}</span><div><strong>{{ item.name }}</strong><small>{{ roles.data.value.find(role => role.id === item.role_id)?.name || '岗位待配置' }}</small></div><span class="presence" :class="item.lifecycle.toLowerCase()"></span></RouterLink></ResourceState><div class="roster-footer"><RouterLink to="/organization" class="text-link">组织与员工管理 <ArrowUpRight :size="13"/></RouterLink></div></aside>
    <article v-if="employee" class="panel conversation"><div class="chat-heading"><span class="avatar">{{ employee.name.slice(0,1) }}</span><div><h2>{{ employee.name }}</h2><p>{{ roles.data.value.find(role => role.id === employee?.role_id)?.mandate || '长期职责由岗位和工作目标定义' }}</p></div><StatusTag :value="employee.lifecycle"/></div><ResourceState :loading="dmLoading" :error="dmError" @retry="connectDm"><ChatThread v-if="channel" :channel-id="channel" :employees="employees.data.value"/></ResourceState></article>
    <article v-else class="panel empty-conversation"><el-empty :description="employees.loading.value ? '正在读取员工' : route.params.id ? '员工不存在或不可见' : '选择员工开始长期对话'"/></article>
    <aside v-if="employee" class="panel employee-aside"><el-tabs v-model="tab" stretch><el-tab-pane label="工作" name="work"/><el-tab-pane label="职责" name="goals"/><el-tab-pane label="记忆" name="memory"/><el-tab-pane label="收件箱" name="inbox"/><el-tab-pane label="例程" name="routines"/></el-tabs>
      <div class="aside-body"><template v-if="tab === 'work'"><h3>当前工作</h3><ResourceState :loading="work.loading.value" :error="work.error.value" :empty="!work.data.value.length" description="暂无关联工作" @retry="work.load"><RouterLink v-for="task in work.data.value" :key="task.id" :to="{ path: `/tasks/${task.id}`, query: { from: id } }" class="mini-card"><strong>{{ task.title }}</strong><StatusTag :value="task.status"/></RouterLink></ResourceState><el-button :icon="Plus" @click="form = 'task'">交办业务工作</el-button><div class="divider"></div><h3>工作计划</h3><ResourceState :loading="dashboard.loading.value" :error="dashboard.error.value" @retry="dashboard.load"><p class="muted">{{ plan || '尚无已记录的工作计划' }}</p></ResourceState></template>
        <template v-if="tab === 'goals'"><h3>长期职责与目标</h3><ResourceState :loading="goals.loading.value" :error="goals.error.value" :empty="!goals.data.value.length" description="尚未分配具体工作目标" @retry="goals.load"><div v-for="goal in goals.data.value" :key="goal.id" class="mini-card"><strong>{{ goal.title }}</strong><p>{{ goal.metric }}</p><StatusTag :value="goal.status"/></div></ResourceState><div class="divider"></div><h3>授权边界</h3><pre class="code-block">{{ json(employee.scope) }}</pre><div class="tag-wrap"><el-tag v-for="permission in employee.permissions" :key="permission" type="info">{{ permission }}</el-tag></div><p class="caption">权限由岗位、组织规则、具体授权与当前操作共同约束。</p><p class="caption">每日 Token 预算 {{ employee.daily_token_budget.toLocaleString() }}</p></template>
        <MemoryPanel v-if="tab === 'memory'" :employee-id="id" :active="employee.lifecycle === 'ACTIVE'"/>
        <PersonaInbox v-if="tab === 'inbox'" :employee-id="id"/>
        <template v-if="tab === 'routines'"><div class="spread"><h3>持续职责</h3><el-button text :icon="Plus" @click="form = 'routine'">添加</el-button></div><ResourceState :loading="routines.loading.value" :error="routines.error.value" :empty="!routines.data.value.length" description="尚未安排周期职责" @retry="routines.load"><div v-for="routine in routines.data.value" :key="routine.id" class="mini-card"><strong>{{ routine.title }}</strong><p>{{ routine.kind }} · {{ routine.schedule }}</p><small>{{ routine.timezone }} · {{ routine.enabled ? '启用' : '暂停' }}{{ routine.locked ? ' · 人类锁定' : '' }}</small><small>下次检查 {{ date(routine.next_due_at) }}</small><div class="action-row"><el-button :loading="actionLoading" :disabled="!routine.enabled || employee.lifecycle !== 'ACTIVE'" @click="routineAction(routine, 'run-now')">立即检查</el-button><el-button :loading="actionLoading" @click="routineAction(routine, routine.enabled ? 'pause' : 'resume')">{{ routine.enabled ? '暂停' : '恢复' }}</el-button></div></div></ResourceState></template>
        <div class="divider"></div><div class="employee-controls"><el-button v-if="employee.lifecycle === 'ACTIVE'" :icon="Pause" :loading="actionLoading" @click="action('pause')">暂停主动工作</el-button><el-button v-else-if="employee.lifecycle === 'PAUSED'" :icon="Play" :loading="actionLoading" @click="action('resume')">恢复主动工作</el-button><el-button v-if="employee.lifecycle !== 'ARCHIVED'" text type="danger" :loading="actionLoading" @click="action('archive')">归档员工</el-button></div>
      </div></aside>
  </div><EntityForm :model-value="!!form" :kind="form" :employee-id="id" :team-id="employee?.team_id" @update:model-value="form = ''"/>
</template>
