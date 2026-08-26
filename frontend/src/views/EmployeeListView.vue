<template>
  <div class="page">
    <section class="page-intro compact-intro"><div><span class="kicker"><Bot :size="13" /> EMPLOYEE FLEET</span><h2>数字员工工作台</h2><p>管理长期在线的岗位实例、能力边界与当前负载。</p></div><button class="button button--primary" disabled><Plus :size="15" /> 新增员工 <small>V0.2</small></button></section>
    <div class="filter-bar"><div class="search-box"><Search :size="15" /><input v-model="query" placeholder="搜索员工名称或岗位" /></div><select v-model="status"><option value="">全部状态</option><option value="WORKING">工作中</option><option value="IDLE">空闲</option><option value="WAIT_HUMAN">等待人工</option><option value="PAUSED">已暂停</option></select><span class="filter-summary">{{ filtered.length }} 个岗位实例</span></div>
    <section class="employee-grid">
      <RouterLink v-for="employee in filtered" :key="employee.id" :to="`/employees/${employee.id}`" class="employee-card">
        <header><div class="employee-avatar employee-avatar--large"><Bot :size="31" /><i /></div><AstraStatusBadge :status="employee.status" pulse /></header>
        <div class="employee-card__identity"><small>{{ employee.id }}</small><h3>{{ employee.name }}</h3><p>{{ employee.role }}</p></div>
        <div class="capability-list"><span v-for="capability in employee.capabilities.slice(0, 4)" :key="capability">{{ capabilityLabel(capability) }}</span><span v-if="employee.capabilities.length > 4">+{{ employee.capabilities.length - 4 }}</span></div>
        <div v-if="currentTask(employee.id)" class="employee-current"><div><small>当前任务</small><strong>{{ currentTask(employee.id)?.title }}</strong></div><AstraProgress :value="currentTask(employee.id)?.progress ?? 0" /></div>
        <div v-else class="employee-current employee-current--idle"><div><small>当前任务</small><strong>等待调度</strong></div><span>队列就绪</span></div>
        <footer><span><Activity :size="13" /> 在线 {{ formatDuration(employee.online_since) }}</span><span><Gauge :size="13" /> {{ completedCount(employee.id) }} 项完成</span><ChevronRight :size="17" /></footer>
      </RouterLink>
    </section>
  </div>
</template>
<script setup lang="ts">
import { Activity, Bot, ChevronRight, Gauge, Plus, Search } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import AstraProgress from '@/components/astra/AstraProgress.vue'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import { useAstraStore } from '@/stores/astra'
import { formatDuration } from '@/utils/format'
const store = useAstraStore(); const query = ref(''); const status = ref('')
onMounted(() => store.refresh())
const filtered = computed(() => store.employees.filter((employee) => (!status.value || employee.status === status.value) && (!query.value || `${employee.name}${employee.role}`.toLowerCase().includes(query.value.toLowerCase()))))
const currentTask = (id: string) => store.activeTasks.find((task) => task.employee_id === id)
const completedCount = (id: string) => store.tasks.filter((task) => task.employee_id === id && task.status === 'COMPLETED').length
const capabilityLabel = (value: string) => ({ script_generate: '脚本生成', script_review: '代码检视', script_execute: '真实执行', script_repair: '故障修复', result_verify: '结果验证' }[value] ?? value)
</script>
