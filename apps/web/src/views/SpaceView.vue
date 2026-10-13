<script setup lang="ts">
import { computed } from 'vue'
import { ArrowUpRight, ChevronRight, CircleDot, MessagesSquare } from 'lucide-vue-next'
import { useResource } from '../api'
import type { AuditEvent, Employee, Goal, Operation, Role, Task } from '../types'
import { date } from '../format'
import TeamScene from '../components/TeamScene.vue'
import ResourceState from '../components/ResourceState.vue'
const employees = useResource<Employee[]>('/employees', [])
const roles = useResource<Role[]>('/roles', [])
const tasks = useResource<Task[]>('/tasks', [])
const goals = useResource<Goal[]>('/goals', [])
const inbox = useResource<Operation[]>('/human-inbox', [])
const activity = useResource<AuditEvent[]>('/audit-events', [])
const ongoing = computed(() => tasks.data.value.filter(task => !['COMPLETED','CANCELLED'].includes(task.status)).length)
</script>
<template>
  <div class="space-layout">
    <aside class="space-intro"><div class="eyebrow">A NEW WAY OF WORKING</div><h1>你的数字团队，<br/><em>和你一起向前。</em></h1><p class="lead">有自己的职责，有独立判断，有持续的记忆。你关注目标和结果，员工持续推进工作。</p><div class="quick-actions"><RouterLink to="/employees"><el-button type="primary">与员工交流 <ArrowUpRight :size="15"/></el-button></RouterLink><RouterLink to="/channels"><el-button>团队讨论</el-button></RouterLink></div>
      <section class="panel overview-panel"><div class="panel-heading"><h2>团队此刻</h2><span class="caption">权威业务快照</span></div><ResourceState :loading="employees.loading.value || tasks.loading.value" :error="employees.error.value || tasks.error.value" @retry="employees.load(); tasks.load()"><div class="metric-row"><div><strong>{{ employees.data.value.length }}</strong><span>数字员工</span></div><div><strong>{{ ongoing }}</strong><span>推进中工作</span></div><div><strong>{{ inbox.error.value ? '—' : inbox.data.value.length }}</strong><span>需要你决策</span></div></div></ResourceState><div class="divider"></div><h3>当前工作重点</h3><ResourceState :loading="goals.loading.value" :error="goals.error.value" :empty="!goals.data.value.length" description="尚未设定团队目标" @retry="goals.load"><p v-for="goal in goals.data.value.slice(0,3)" :key="goal.id" class="goal-line">{{ goal.title }}<small>{{ goal.metric }}</small></p></ResourceState><RouterLink to="/organization" class="text-link">查看团队目标 <ChevronRight :size="13"/></RouterLink></section>
    </aside>
    <div class="space-center"><ResourceState :loading="employees.loading.value && !employees.data.value.length" :error="employees.error.value" @retry="employees.load"><TeamScene :employees="employees.data.value" :roles="roles.data.value" :tasks="tasks.data.value"/></ResourceState></div>
    <aside class="space-aside"><section class="panel"><div class="panel-heading"><h2>需要你关注</h2><CircleDot :size="17" class="amber"/></div><ResourceState :loading="inbox.loading.value" :error="inbox.error.value" :empty="!inbox.data.value.length" description="当前没有待决策事项" @retry="inbox.load"><RouterLink v-for="item in inbox.data.value.slice(0,4)" :key="item.id" to="/attention" class="activity-row"><span class="activity-dot amber-dot"></span><div><strong>{{ item.action }}</strong><small>操作范围 {{ item.target_id.slice(0,8) }}</small></div><ChevronRight :size="13"/></RouterLink></ResourceState><RouterLink to="/attention" class="text-link">进入决策中心 <ChevronRight :size="13"/></RouterLink></section>
      <section class="panel"><div class="panel-heading"><h2>团队最近动态</h2><MessagesSquare :size="17"/></div><ResourceState :loading="activity.loading.value" :error="activity.error.value" :empty="!activity.data.value.length" description="暂无可见工作动态" @retry="activity.load"><div v-for="event in activity.data.value.slice(-5).reverse()" :key="event.seq" class="activity-row"><span class="activity-dot"></span><div><p>{{ event.summary }}</p><small>{{ date(event.created_at) }}</small></div></div></ResourceState></section>
      <div class="soft-note"><strong>工作连续性，属于员工。</strong><p>职责、对话和未完成承诺保存在业务系统中，不依赖一个永久运行的模型会话。</p></div>
    </aside>
  </div>
</template>
