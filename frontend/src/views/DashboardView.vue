<template>
  <div class="dashboard-page" data-testid="dashboard-page">
    <section class="space-summary" aria-label="当前空间状态">
      <div class="space-summary__health">
        <i :data-attention="attentionCount > 0" />
        <span><small>当前空间状态</small><strong>{{ healthCopy }}</strong></span>
      </div>

      <div v-if="overview.loading && !overview.data" class="summary-skeleton" aria-label="正在加载运行摘要">
        <i v-for="index in 4" :key="index" />
      </div>
      <nav v-else class="summary-metrics" aria-label="运行摘要">
        <RouterLink to="/employees"><strong>{{ overview.data?.employee_total ?? '—' }}</strong><span>名数字员工</span></RouterLink>
        <RouterLink to="/employees?status=WORKING"><strong>{{ overview.data?.working_employees ?? '—' }}</strong><span>工作中</span></RouterLink>
        <RouterLink to="/interventions"><strong>{{ tasks.data?.waiting ?? '—' }}</strong><span>个任务待处理</span></RouterLink>
        <RouterLink class="summary-metrics__attention" to="/interventions"><strong>{{ attentionCount }}</strong><span>项需要关注</span></RouterLink>
      </nav>

      <div class="space-summary__refresh">
        <span v-if="overview.error || tasks.error" title="部分摘要暂时无法获取"><TriangleAlert :size="15" />部分数据异常</span>
        <small>最近刷新 {{ lastUpdatedText }}</small>
        <button type="button" :disabled="refreshing" aria-label="刷新首页数据" @click="refreshDashboard">
          <RefreshCw :size="16" :class="{ spin: refreshing }" />刷新
        </button>
      </div>
    </section>

    <section class="dashboard-core">
      <article class="space-card employee-space" aria-labelledby="employee-space-title">
        <header class="space-card__header">
          <div>
            <h1 id="employee-space-title">数字员工</h1>
            <p>看见每一位数字员工正在做什么</p>
          </div>
          <RouterLink to="/employees">全部员工 <ChevronRight :size="15" /></RouterLink>
        </header>

        <div v-if="employees.loading && !employees.data" class="employee-space__skeleton">
          <section v-for="index in 2" :key="index"><i /><div><span v-for="item in 4" :key="item" /></div></section>
        </div>
        <div v-else-if="employees.error" class="module-state module-state--error">
          <TriangleAlert :size="24" /><strong>数字员工暂时无法获取</strong><span>{{ employees.error }}</span><button type="button" @click="loadEmployees">重试</button>
        </div>
        <div v-else-if="!employeeTeams.length" class="module-state">
          <UsersRound :size="28" /><strong>{{ searchQuery ? `没有找到“${searchQuery}”` : '暂无数字员工' }}</strong><span>{{ searchQuery ? '可搜索员工名称、职责或当前任务。' : '创建数字员工后，他们会出现在这里。' }}</span>
        </div>
        <div v-else class="employee-teams">
          <section v-for="team in employeeTeams" :key="team.id" class="employee-team" :aria-label="`${team.name}团队`">
            <header><h2>{{ team.name }}</h2><span>{{ teamSummary(team) }}</span></header>
            <div class="employee-team__members">
              <RouterLink
                v-for="employee in team.employees"
                :key="employee.id"
                :to="`/employees/${employee.id}`"
                class="employee-person"
                :data-state="employee.state"
              >
                <EmployeeAvatar :employee="employee" />
                <span>
                  <strong :title="employeeDisplayName(employee.name)">{{ employeeDisplayName(employee.name) }}</strong>
                  <small><i />{{ employeeStateCopy(employee.state) }}</small>
                  <em :title="employee.current_task?.title ?? ''">{{ employee.current_task?.title ?? '暂无当前任务' }}</em>
                </span>
              </RouterLink>
            </div>
          </section>
        </div>
      </article>

      <article class="space-card handling-space" aria-labelledby="handling-title">
        <header class="space-card__header">
          <div>
            <h1 id="handling-title">需要处理 <b>{{ attentionCount }}</b></h1>
            <p>优先处理会阻塞数字员工继续工作的事项</p>
          </div>
          <RouterLink to="/interventions">全部待处理 <ChevronRight :size="15" /></RouterLink>
        </header>

        <div v-if="attention.loading && !attention.data" class="handling-list handling-list--skeleton">
          <i v-for="index in 5" :key="index" />
        </div>
        <div v-else-if="attention.error" class="module-state module-state--error">
          <TriangleAlert :size="24" /><strong>待处理事项暂时无法获取</strong><span>{{ attention.error }}</span><button type="button" @click="loadAttention">重试</button>
        </div>
        <div v-else-if="!attention.data?.items.length" class="module-state module-state--healthy">
          <CircleCheck :size="30" /><strong>当前无需处理</strong><span>数字员工可以继续自主运行。</span>
        </div>
        <div v-else class="handling-list">
          <article v-for="item in attention.data.items" :key="item.task_id" class="handling-item" :data-status="item.status">
            <RouterLink :to="`/tasks/${item.task_id}`" class="handling-item__content">
              <strong>{{ item.task_title }}</strong>
              <span>{{ employeeDisplayName(item.employee_name) }} · {{ item.status_label }}</span>
              <time>{{ formatRelativeTime(item.occurred_at) }}</time>
            </RouterLink>
            <RouterLink :to="`/tasks/${item.task_id}`" class="handling-item__action">处理</RouterLink>
          </article>
        </div>
      </article>
    </section>

    <section class="dashboard-running" aria-label="最近运行信息">
      <article class="space-card recent-tasks" aria-labelledby="recent-tasks-title">
        <header class="space-card__header space-card__header--compact">
          <div><h1 id="recent-tasks-title">最近任务</h1><p>最近发生变化的任务</p></div>
          <RouterLink to="/tasks">查看全部任务 <ChevronRight :size="15" /></RouterLink>
        </header>

        <div v-if="tasks.loading && !tasks.data" class="recent-list-skeleton"><i v-for="index in 5" :key="index" /></div>
        <div v-else-if="tasks.error" class="module-state module-state--error module-state--compact">
          <TriangleAlert :size="22" /><strong>最近任务暂时无法获取</strong><span>{{ tasks.error }}</span><button type="button" @click="loadTasks">重试</button>
        </div>
        <div v-else-if="!tasks.data?.recent?.length" class="module-state module-state--compact">
          <strong>暂无最近任务</strong><span>新创建或状态发生变化的任务会显示在这里。</span>
        </div>
        <div v-else class="recent-task-list" role="table" aria-label="最近任务列表">
          <div class="recent-task-list__head" role="row"><span>任务</span><span>状态</span><span>数字员工</span><span>时间</span></div>
          <RouterLink v-for="task in tasks.data?.recent ?? []" :key="task.id" :to="`/tasks/${task.id}`" role="row">
            <strong :title="task.title">{{ task.title }}</strong>
            <span class="task-state" :data-tone="taskTone(task.status)">{{ statusLabel(task.status) }}</span>
            <span :title="employeeDisplayName(task.employee_name)">{{ employeeDisplayName(task.employee_name) }}</span>
            <time>{{ formatRelativeTime(task.updated_at) }}</time>
          </RouterLink>
        </div>
      </article>

      <article class="space-card recent-activity" aria-labelledby="recent-activity-title">
        <header class="space-card__header space-card__header--compact">
          <div><h1 id="recent-activity-title">最近动态</h1><p>数字空间里的关键业务事件</p></div>
          <RouterLink to="/tasks">更多动态 <ChevronRight :size="15" /></RouterLink>
        </header>

        <div v-if="activity.loading && !activity.data" class="recent-list-skeleton"><i v-for="index in 5" :key="index" /></div>
        <div v-else-if="activity.error" class="module-state module-state--error module-state--compact">
          <TriangleAlert :size="22" /><strong>最近动态暂时无法获取</strong><span>{{ activity.error }}</span><button type="button" @click="loadActivity">重试</button>
        </div>
        <div v-else-if="!activity.data?.items.length" class="module-state module-state--compact">
          <Clock3 :size="25" /><strong>暂无最近动态</strong><span>重要任务和员工事件会显示在这里。</span>
        </div>
        <div v-else class="activity-feed">
          <component
            :is="activityTarget(item) ? RouterLink : 'div'"
            v-for="item in activity.data.items.slice(0, 5)"
            :key="item.id"
            :to="activityTarget(item) || undefined"
            class="activity-feed__item"
          >
            <time>{{ formatClock(item.created_at) }}</time>
            <i :data-kind="item.kind" />
            <span><strong>{{ employeeDisplayName(item.employee_name) }}</strong><em>{{ item.description }}</em></span>
          </component>
        </div>
      </article>
    </section>

    <article class="library-scene" aria-labelledby="library-title">
      <span class="library-scene__icon"><BookOpen :size="29" /></span>
      <div class="library-scene__intro">
        <small>KNOWLEDGE SPACE</small>
        <h1 id="library-title">数字图书馆</h1>
        <p v-if="knowledge.data">今天沉淀 {{ knowledge.data.today_added }} 条知识，{{ knowledge.data.candidate_experiences }} 条经验等待整理</p>
        <p v-else>把每次任务中的有效经验沉淀下来</p>
      </div>

      <div v-if="knowledge.loading && !knowledge.data" class="library-scene__skeleton"><i /><i /><i /></div>
      <div v-else-if="knowledge.error" class="library-scene__error"><span>最近知识暂时无法获取</span><button type="button" @click="loadKnowledge">重试</button></div>
      <div v-else class="library-scene__recent">
        <small>最近知识</small>
        <template v-if="knowledge.data?.recent?.length">
          <RouterLink v-for="item in knowledge.data?.recent ?? []" :key="item.id" :to="`/library?knowledge=${item.id}`">{{ item.title }}</RouterLink>
        </template>
        <span v-else>还没有沉淀知识，完成任务后从经验开始积累。</span>
      </div>

      <RouterLink class="library-scene__action" to="/library">进入数字图书馆 <ChevronRight :size="16" /></RouterLink>
    </article>
  </div>
</template>

<script setup lang="ts">
import { BookOpen, ChevronRight, CircleCheck, Clock3, RefreshCw, TriangleAlert, UsersRound } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@/api/client'
import type {
  DashboardActivity,
  DashboardActivityItem,
  DashboardAttention,
  DashboardEmployee,
  DashboardEmployees,
  DashboardKnowledge,
  DashboardOverview,
  DashboardTasks,
  DashboardTeam,
} from '@/api/types'
import EmployeeAvatar from '@/components/employee/EmployeeAvatar.vue'
import { employeeDisplayName, statusLabel } from '@/utils/format'

interface SectionState<T> { data: T | null; loading: boolean; error: string }

const section = <T>(): SectionState<T> => reactive({ data: null, loading: true, error: '' }) as SectionState<T>
const overview = section<DashboardOverview>()
const employees = section<DashboardEmployees>()
const attention = section<DashboardAttention>()
const tasks = section<DashboardTasks>()
const activity = section<DashboardActivity>()
const knowledge = section<DashboardKnowledge>()
const route = useRoute()
const refreshing = ref(false)
const lastUpdated = ref<Date | null>(null)
let refreshTimer = 0

const searchQuery = computed(() => typeof route.query.q === 'string' ? route.query.q.trim() : '')
const employeeTeams = computed<DashboardTeam[]>(() => {
  const teams = employees.data?.teams ?? []
  const query = searchQuery.value.toLocaleLowerCase('zh-CN')
  if (!query) return teams
  return teams.map((team) => {
    const members = team.employees.filter((employee) => `${employee.name} ${employee.role} ${employee.current_task?.title ?? ''}`.toLocaleLowerCase('zh-CN').includes(query))
    return { ...team, employee_count: members.length, employees: members }
  }).filter((team) => team.employees.length)
})
const attentionCount = computed(() => overview.data?.attention_total ?? attention.data?.items.length ?? 0)
const healthCopy = computed(() => attentionCount.value > 0 ? `${attentionCount.value} 项需要你关注` : '运行平稳，无需介入')
const lastUpdatedText = computed(() => lastUpdated.value?.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }) ?? '—')

async function loadSection<T>(state: SectionState<T>, request: () => Promise<T>, fallback: string): Promise<boolean> {
  if (!state.data) state.loading = true
  state.error = ''
  try {
    state.data = await request()
    return true
  } catch (error) {
    state.error = error instanceof Error ? error.message : fallback
    return false
  } finally {
    state.loading = false
  }
}

const loadOverview = () => loadSection(overview, api.dashboardOverview, '运行摘要加载失败')
const loadEmployees = () => loadSection(employees, api.dashboardEmployees, '数字员工加载失败')
const loadAttention = () => loadSection(attention, api.dashboardAttention, '待处理事项加载失败')
const loadTasks = () => loadSection(tasks, api.dashboardTasks, '最近任务加载失败')
const loadActivity = () => loadSection(activity, api.dashboardActivity, '最近动态加载失败')
const loadKnowledge = () => loadSection(knowledge, api.dashboardKnowledge, '最近知识加载失败')

async function refreshDashboard() {
  if (refreshing.value) return
  refreshing.value = true
  const results = await Promise.all([loadOverview(), loadEmployees(), loadAttention(), loadTasks(), loadActivity(), loadKnowledge()])
  if (results.some(Boolean)) lastUpdated.value = new Date()
  refreshing.value = false
}

function employeeStateCopy(state: DashboardEmployee['state']) {
  if (state === 'working') return '正在执行'
  if (state === 'waiting') return '等待处理'
  if (state === 'error') return '异常'
  return '空闲'
}

function teamSummary(team: DashboardTeam) {
  const counts = team.employees.reduce<Record<DashboardEmployee['state'], number>>((result, employee) => {
    result[employee.state] += 1
    return result
  }, { working: 0, idle: 0, waiting: 0, error: 0 })
  if (counts.idle === team.employee_count) return `${team.employee_count} 人 · 全部空闲`
  const active = []
  if (counts.working) active.push(`${counts.working} 人执行中`)
  if (counts.waiting) active.push(`${counts.waiting} 人等待处理`)
  if (counts.error) active.push(`${counts.error} 人异常`)
  if (counts.idle) active.push(`${counts.idle} 人空闲`)
  return `${team.employee_count} 人 · ${active.join(' · ')}`
}

function taskTone(status: string) {
  if (['WAIT_HUMAN', 'SUSPENDED', 'PENDING_CONFIRMATION'].includes(status)) return 'waiting'
  if (['FAILED', 'EXECUTION_ERROR'].includes(status)) return 'error'
  if (status === 'COMPLETED') return 'success'
  if (status === 'RUNNING') return 'working'
  return 'neutral'
}

function activityTarget(item: DashboardActivityItem) {
  if (!item.target_id) return ''
  return item.target_type === 'task' ? `/tasks/${item.target_id}` : `/employees/${item.target_id}`
}

function parseTime(value: string) {
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`)
}

function formatRelativeTime(value: string) {
  const minutes = Math.max(0, Math.floor((Date.now() - parseTime(value).getTime()) / 60_000))
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (minutes < 1_440) return `${Math.floor(minutes / 60)} 小时前`
  return parseTime(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function formatClock(value: string) {
  return parseTime(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function handleVisibility() {
  if (!document.hidden && (!lastUpdated.value || Date.now() - lastUpdated.value.getTime() >= 30_000)) refreshDashboard()
}

onMounted(() => {
  refreshDashboard()
  refreshTimer = window.setInterval(() => { if (!document.hidden) refreshDashboard() }, 30_000)
  document.addEventListener('visibilitychange', handleVisibility)
})

onBeforeUnmount(() => {
  window.clearInterval(refreshTimer)
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<style scoped>
.dashboard-page{min-height:calc(100vh - 68px);padding:22px 32px 40px;color:#16332b;background:#f5f9f7}
.space-summary{display:flex;align-items:center;gap:28px;min-height:75px;margin-bottom:18px;padding:0 4px 18px;border-bottom:1px solid #dce8e3}
.space-summary__health{display:flex;align-items:center;gap:11px;width:225px;flex:none}.space-summary__health>i{width:10px;height:10px;border-radius:50%;background:#13b77a;box-shadow:0 0 0 6px rgba(19,183,122,.1)}.space-summary__health>i[data-attention='true']{background:#df9139;box-shadow:0 0 0 6px rgba(223,145,57,.12)}.space-summary__health>span{display:grid}.space-summary__health small{color:#72847e;font-size:var(--astra-font-helper)}.space-summary__health strong{margin-top:2px;color:#16332b;font-size:var(--astra-font-emphasis)}
.summary-metrics{display:flex;align-items:center;min-width:0}.summary-metrics>a{display:flex;align-items:baseline;gap:7px;min-width:122px;padding:0 23px;border-left:1px solid #dbe6e1;color:#5f746d}.summary-metrics>a:first-child{border-left:0}.summary-metrics strong{color:#16332b;font:780 var(--astra-font-kpi)/1 var(--astra-font-display);font-variant-numeric:tabular-nums}.summary-metrics span{font-size:var(--astra-font-control);white-space:nowrap}.summary-metrics__attention strong,.summary-metrics__attention span{color:#d87943}.space-summary__refresh{display:flex;align-items:center;gap:12px;margin-left:auto;color:#7b8c87;white-space:nowrap}.space-summary__refresh>span{display:flex;align-items:center;gap:5px;color:#c66f45;font-size:var(--astra-font-helper)}.space-summary__refresh>small{font-size:var(--astra-font-helper)}.space-summary__refresh button{display:flex;align-items:center;gap:6px;height:36px;padding:0 13px;color:#fff;border:0;border-radius:9px;background:#163f34;font-size:var(--astra-font-control);font-weight:700;cursor:pointer}.space-summary__refresh button:hover{background:#0f332a}.space-summary__refresh button:disabled{opacity:.65;cursor:wait}
.summary-skeleton{display:grid;grid-template-columns:repeat(4,110px);gap:14px}.summary-skeleton i,.employee-space__skeleton i,.employee-space__skeleton span,.handling-list--skeleton i,.recent-list-skeleton i,.library-scene__skeleton i{display:block;border-radius:8px;background:linear-gradient(90deg,#e5eeea,#f6faf8,#e5eeea);background-size:200% 100%;animation:dashboard-shimmer 1.35s linear infinite}.summary-skeleton i{height:34px}
.dashboard-core,.dashboard-running{display:grid;grid-template-columns:minmax(0,7fr) minmax(390px,5fr);gap:18px}.dashboard-core{margin-bottom:18px}.dashboard-running{grid-template-columns:minmax(0,7fr) minmax(380px,5fr);margin-bottom:18px}
.space-card{min-width:0;overflow:hidden;border:1px solid #dfeae5;border-radius:17px;background:#fff;box-shadow:0 11px 32px rgba(27,67,53,.065)}.space-card__header{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:20px 24px 15px}.space-card__header h1,.space-card__header p{margin:0}.space-card__header h1{color:#16332b;font:760 var(--astra-font-section)/1.15 var(--astra-font-display);letter-spacing:-.015em}.space-card__header h1 b{margin-left:5px;color:#d87842;font-size:inherit}.space-card__header p{margin-top:5px;color:#7a8b85;font-size:var(--astra-font-helper)}.space-card__header>a{display:flex;align-items:center;gap:2px;margin-top:2px;color:#15865e;font-size:var(--astra-font-helper);white-space:nowrap}.space-card__header>a:hover{color:#0c6746}.space-card__header--compact{padding-bottom:13px;border-bottom:1px solid #edf2ef}
.employee-space,.handling-space{min-height:388px}.employee-teams{padding:0 24px 20px}.employee-team{padding:6px 0 15px;border-top:1px solid #edf2ef}.employee-team:first-child{border-top:0}.employee-team+ .employee-team{padding-top:15px}.employee-team>header{display:flex;align-items:baseline;justify-content:space-between;gap:14px;margin-bottom:7px}.employee-team h2{margin:0;color:#244139;font-size:var(--astra-font-label)}.employee-team>header span{overflow:hidden;color:#82918c;font-size:var(--astra-font-micro);text-overflow:ellipsis;white-space:nowrap}.employee-team__members{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.employee-person{display:grid;grid-template-columns:58px minmax(0,1fr);align-items:center;gap:10px;min-width:0;min-height:72px;padding:8px 9px;border-radius:14px;transition:background-color .16s ease,transform .16s ease}.employee-person:hover{background:#f1f8f5;transform:translateY(-1px)}.employee-person[data-state='waiting']{background:#fffaf1}.employee-person[data-state='error']{background:#fff5f3}.employee-person[data-state='working']{background:#f1faf6}.employee-person :deep(.employee-avatar-image){width:54px;height:54px;border:3px solid #fff;border-radius:50%;box-shadow:0 5px 15px rgba(32,74,59,.13)}.employee-person>span{display:grid;min-width:0;align-content:center}.employee-person strong{display:-webkit-box;overflow:hidden;color:#1d372f;font-size:var(--astra-font-control);line-height:1.25;-webkit-box-orient:vertical;-webkit-line-clamp:2}.employee-person small{display:flex;align-items:center;gap:5px;margin-top:4px;color:#5f776f;font-size:var(--astra-font-helper);font-weight:650}.employee-person small i{width:6px;height:6px;border-radius:50%;background:#6d8a80}.employee-person[data-state='working'] small{color:#079c66}.employee-person[data-state='working'] small i{background:#13b77a;box-shadow:0 0 0 3px rgba(19,183,122,.1)}.employee-person[data-state='waiting'] small{color:#c98025}.employee-person[data-state='waiting'] small i{background:#dda03b}.employee-person[data-state='error'] small{color:#d05259}.employee-person[data-state='error'] small i{background:#df6367}.employee-person em{overflow:hidden;margin-top:2px;color:#83928d;font-size:var(--astra-font-micro);font-style:normal;text-overflow:ellipsis;white-space:nowrap}
.employee-space__skeleton{padding:0 24px 20px}.employee-space__skeleton>section{padding:12px 0;border-top:1px solid #edf2ef}.employee-space__skeleton>section>i{width:130px;height:14px;margin-bottom:10px}.employee-space__skeleton>section>div{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.employee-space__skeleton span{height:72px}
.handling-list{display:grid;padding:0 24px 18px}.handling-item{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:14px;min-height:61px;padding:10px 0 10px 15px;border-top:1px solid #edf2ef}.handling-item::before{position:absolute;top:13px;bottom:13px;left:0;width:3px;border-radius:3px;background:#dfa13f;content:''}.handling-item[data-status='execution_failed']::before,.handling-item[data-status='exception']::before{background:#dc6267}.handling-item__content{display:grid;min-width:0}.handling-item__content strong{display:-webkit-box;overflow:hidden;color:#243c35;font-size:var(--astra-font-body);line-height:1.35;-webkit-box-orient:vertical;-webkit-line-clamp:2}.handling-item__content span{margin-top:4px;color:#71847d;font-size:var(--astra-font-helper)}.handling-item__content time{margin-top:2px;color:#9aa5a1;font-size:var(--astra-font-micro)}.handling-item__action{display:grid;place-items:center;width:52px;height:30px;color:#fff;border-radius:8px;background:#174538;font-size:var(--astra-font-helper);font-weight:700}.handling-item__action:hover{background:#0f352b}.handling-item[data-status='execution_failed'] .handling-item__action,.handling-item[data-status='exception'] .handling-item__action{background:#c95c60}.handling-list--skeleton{gap:8px}.handling-list--skeleton i{height:52px}
.recent-tasks,.recent-activity{min-height:294px}.recent-task-list{padding:0 24px 16px}.recent-task-list__head,.recent-task-list>a{display:grid;grid-template-columns:minmax(180px,1.7fr) 82px minmax(90px,.72fr) 64px;align-items:center;gap:13px}.recent-task-list__head{height:27px;color:#98a39f;font-size:var(--astra-font-micro)}.recent-task-list>a{min-height:40px;border-top:1px solid #edf2ef;color:#6f827b;font-size:var(--astra-font-helper)}.recent-task-list>a:hover{background:#f8fbf9}.recent-task-list>a>strong,.recent-task-list>a>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.recent-task-list>a>strong{color:#29433b;font-size:var(--astra-font-control)}.recent-task-list time{color:#899791;font-size:var(--astra-font-micro);text-align:right}.task-state{justify-self:start;padding:4px 7px;color:#64776f;border-radius:6px;background:#f0f4f2;font-size:var(--astra-font-micro)}.task-state[data-tone='working']{color:#078a59;background:#eaf8f2}.task-state[data-tone='waiting']{color:#b87520;background:#fff6e6}.task-state[data-tone='error']{color:#c84f56;background:#fff0f1}.task-state[data-tone='success']{color:#48776a;background:#eef7f3}
.activity-feed{display:grid;padding:5px 24px 17px}.activity-feed__item{display:grid;grid-template-columns:40px 8px minmax(0,1fr);align-items:center;gap:10px;min-height:43px;border-top:1px solid #edf2ef}.activity-feed__item:first-child{border-top:0}.activity-feed__item:hover{background:#f8fbf9}.activity-feed__item>time{color:#8b9994;font-size:var(--astra-font-micro);font-variant-numeric:tabular-nums}.activity-feed__item>i{width:6px;height:6px;border-radius:50%;background:#13a870}.activity-feed__item>i[data-kind='waiting_human']{background:#dca03e}.activity-feed__item>i[data-kind='task_failed']{background:#d85d63}.activity-feed__item>span{display:flex;align-items:baseline;gap:5px;min-width:0}.activity-feed__item strong{flex:none;color:#345047;font-size:var(--astra-font-helper)}.activity-feed__item em{overflow:hidden;color:#71847d;font-size:var(--astra-font-helper);font-style:normal;text-overflow:ellipsis;white-space:nowrap}
.recent-list-skeleton{display:grid;gap:8px;padding:12px 24px}.recent-list-skeleton i{height:35px}
.library-scene{display:grid;grid-template-columns:72px 280px minmax(320px,1fr) 154px;align-items:center;gap:20px;min-height:138px;padding:20px 24px;border:1px solid #cfe5dc;border-radius:17px;background:#eaf6f1;box-shadow:0 10px 28px rgba(30,81,61,.06)}.library-scene__icon{display:grid;place-items:center;width:66px;height:66px;color:#fff;border-radius:22px;background:#174538;box-shadow:0 10px 24px rgba(23,69,56,.18)}.library-scene__intro small{color:#168b61;font-size:var(--astra-font-micro);font-weight:750;letter-spacing:.14em}.library-scene__intro h1{margin:4px 0 5px;color:#16332b;font:770 var(--astra-font-section)/1.15 var(--astra-font-display)}.library-scene__intro p{margin:0;color:#637a72;font-size:var(--astra-font-control)}.library-scene__recent{display:grid;min-width:0;padding-left:20px;border-left:1px solid #cce0d8}.library-scene__recent>small{margin-bottom:5px;color:#789087;font-size:var(--astra-font-micro)}.library-scene__recent>a,.library-scene__recent>span{overflow:hidden;color:#345047;font-size:var(--astra-font-helper);line-height:1.7;text-overflow:ellipsis;white-space:nowrap}.library-scene__recent>a::before{margin-right:7px;color:#16a36e;content:'·'}.library-scene__recent>a:hover{color:#08744c}.library-scene__action{display:flex;align-items:center;justify-content:center;gap:3px;height:38px;color:#fff;border-radius:10px;background:#13a66f;font-size:var(--astra-font-helper);font-weight:700}.library-scene__action:hover{background:#0b8c5b}.library-scene__skeleton{display:grid;gap:6px}.library-scene__skeleton i{height:13px}.library-scene__error{display:flex;align-items:center;gap:10px;color:#bd6850;font-size:var(--astra-font-helper)}.library-scene__error button{color:inherit;border:0;background:transparent;text-decoration:underline;cursor:pointer}
.module-state{display:grid;place-items:center;align-content:center;min-height:240px;padding:24px;color:#7c8e87;text-align:center}.module-state>svg{color:#718a81}.module-state strong{margin-top:7px;color:#3b554d;font-size:var(--astra-font-body)}.module-state span{margin-top:3px;font-size:var(--astra-font-helper)}.module-state button{margin-top:10px;padding:5px 10px;color:#146f4f;border:1px solid #bcdccc;border-radius:7px;background:#f3faf7;cursor:pointer}.module-state--error>svg{color:#d67855}.module-state--healthy>svg{color:#13a66f}.module-state--compact{min-height:200px}.module-state--compact>svg{margin-bottom:2px}
@keyframes dashboard-shimmer{to{background-position:-200% 0}}
@media(max-width:1280px){.dashboard-page{padding-inline:22px}.space-summary{gap:16px}.space-summary__health{width:190px}.summary-metrics>a{min-width:104px;padding-inline:14px}.dashboard-core{grid-template-columns:minmax(0,3fr) minmax(360px,2fr)}.employee-team__members{grid-template-columns:repeat(2,minmax(0,1fr))}.library-scene{grid-template-columns:64px 230px minmax(280px,1fr) 140px}}
</style>
