<template>
  <div class="dashboard-page" data-testid="dashboard-page">
    <header class="office-header" aria-label="当前空间状态">
      <div><div class="office-header__eyebrow"><i />你的数字团队</div><h1>数字办公室</h1><p>{{ overviewCopy }}</p></div>
      <div class="office-header__sync">
        <span class="sync-state"><i />自动刷新已关闭</span>
        <small>工位更新 {{ updatedText }}</small>
        <ElButton :loading="refreshing" :icon="RefreshCw" aria-label="刷新首页数据" @click="refreshDashboard">刷新</ElButton>
        <ElButton :tag="RouterLink" to="/tasks?create=1" type="primary" :icon="Plus">创建任务</ElButton>
      </div>
    </header>

    <nav class="office-summary" aria-label="关键运行统计" :aria-busy="refreshing" :title="overview.updatedAt ? `统计快照：${snapshotTime(overview.updatedAt)}${overview.error ? '，本次更新失败' : ''}` : '统计尚未加载'">
      <RouterLink to="/employees"><UsersRound :size="19" /><span>在线员工<strong>{{ overview.data ? `${overview.data.online_employees}/${overview.data.employee_total}` : '—' }}</strong></span></RouterLink>
      <RouterLink to="/employees"><Monitor :size="19" /><span>正在工作<strong>{{ overview.data?.working_employees ?? '—' }}</strong></span></RouterLink>
      <RouterLink to="/tasks?status=SUCCEEDED"><CircleCheck :size="19" /><span>今日完成<strong>{{ overview.data?.completed_today ?? '—' }}</strong></span></RouterLink>
      <RouterLink to="/interventions" :data-attention="(overview.data?.attention_total ?? 0) > 0"><Hand :size="19" /><span>待处理<strong>{{ overview.data?.attention_total ?? '—' }}</strong></span><small v-if="overview.data?.attention_total">等待 {{ overview.data.waiting_tasks }} · 异常 {{ overview.data.failed_tasks }}</small></RouterLink>
    </nav>

    <ElAlert v-if="partialError" class="office-error" type="warning" show-icon :closable="false" title="部分数据暂时无法更新；已加载的内容为上次快照，请手动重试。" />

    <div class="office-layout">
      <div class="office-layout__main">
        <p v-if="employees.error && employees.data" class="office-snapshot-error" role="status"><TriangleAlert :size="15" />工位暂未更新：{{ employees.error }} · 上次成功更新 {{ updatedText }}</p>
        <div v-if="employees.loading && !employees.data" class="office-loading" aria-label="正在加载数字办公室"><ElSkeleton :rows="8" /></div>
        <div v-else-if="employees.error && !employees.data" class="office-module-state office-module-state--error">
          <TriangleAlert :size="28" /><h2>数字员工暂时无法获取</h2><p>{{ employees.error }}</p><ElButton @click="refreshDashboard">重试</ElButton>
        </div>
        <OfficeScene v-else :employees="officeEmployees" :office-events="activity.data ? officeEvents : null" :query="searchQuery" />
      </div>

      <aside class="office-sidebar" aria-label="人工处理与最近动态">
        <section class="attention-panel" :class="{ 'attention-panel--empty': attention.data && !attention.data.items.length && !attention.error }" :data-attention="(overview.data?.attention_total ?? attention.data?.items.length ?? 0) > 0" aria-labelledby="attention-title">
          <header class="office-panel-header"><h2 id="attention-title"><Hand :size="18" />需要你处理 <span>{{ overview.data?.attention_total ?? '—' }}</span></h2><RouterLink to="/interventions" aria-label="全部待处理"><ArrowUpRight :size="16" /></RouterLink></header>
          <ElSkeleton v-if="attention.loading && !attention.data" :rows="3" />
          <div v-else-if="attention.error" class="office-panel-message office-panel-message--error"><TriangleAlert :size="19" /><span>待处理事项暂时无法更新</span><ElButton link @click="refreshDashboard">重试</ElButton></div>
          <div v-if="attention.data?.items.length" class="attention-list">
            <RouterLink v-for="item in attention.data.items" :key="item.task_id" :to="`/tasks/${encodeURIComponent(item.task_id)}`" class="attention-item" :data-status="item.status" :title="item.human_required_reason || item.runtime_detail || item.task_title">
              <span class="attention-item__icon"><TriangleAlert v-if="item.status === 'FAILED'" :size="16" /><MessageCircleQuestion v-else :size="16" /></span>
              <div><strong>{{ employeeDisplayName(item.employee_name) }}</strong><span>{{ item.status_label }}</span><p>{{ item.task_title }}</p><small v-if="item.human_required_reason || item.runtime_detail">{{ shortReason(item.human_required_reason || item.runtime_detail) }}</small><time :datetime="item.occurred_at" :title="fullTime(item.occurred_at)">{{ eventTime(item.occurred_at) }}</time></div>
              <ArrowUpRight :size="16" />
            </RouterLink>
            <RouterLink v-if="(overview.data?.attention_total ?? 0) > attention.data.items.length" class="office-text-link" to="/interventions">查看全部 {{ overview.data?.attention_total }} 项 <ChevronRight :size="14" /></RouterLink>
          </div>
          <div v-else-if="!attention.loading && !attention.error" class="office-panel-message"><CircleCheck :size="20" /><span>当前无需处理</span></div>
          <small v-if="attention.error && attention.updatedAt" class="section-snapshot">上次成功更新 {{ snapshotTime(attention.updatedAt) }}</small>
        </section>

        <section class="activity-panel" aria-labelledby="activity-title">
          <header class="office-panel-header"><h2 id="activity-title"><Activity :size="18" />最近动态</h2><span>最近 {{ officeEvents.length }} 条</span></header>
          <p class="activity-panel__intro">关键事件 · {{ activity.updatedAt ? `更新于 ${snapshotTime(activity.updatedAt)}` : '尚未获取快照' }}</p>
          <ElSkeleton v-if="activity.loading && !activity.data" :rows="6" />
          <div v-else-if="activity.error" class="office-panel-message office-panel-message--error"><TriangleAlert :size="19" /><span>最近动态暂时无法更新</span><ElButton link @click="refreshDashboard">重试</ElButton></div>
          <div v-if="officeEvents.length" class="activity-feed" data-testid="office-activity-feed">
            <component :is="event.target ? RouterLink : 'div'" v-for="event in officeEvents" :key="event.id" :to="event.target || undefined" class="activity-feed__item" :data-kind="event.kind">
              <span class="activity-feed__dot"><Check v-if="event.kind === 'task_completed'" :size="11" /><span v-else /></span>
              <div><header><strong>{{ event.employeeName }}</strong><time :datetime="event.occurredAt" :title="fullTime(event.occurredAt)">{{ eventTime(event.occurredAt) }}</time></header><p>{{ event.description }}</p><small v-if="event.repeatCount > 1" class="activity-feed__repeat">同类事件 {{ event.repeatCount }} 次 · 显示最近一次</small></div>
            </component>
          </div>
          <div v-else-if="!activity.loading && !activity.error" class="office-panel-message"><Clock3 :size="21" /><span>暂无最近动态</span></div>
          <RouterLink class="office-text-link activity-panel__link" to="/tasks">进入任务中心 <ChevronRight :size="14" /></RouterLink>
        </section>
      </aside>
    </div>

    <footer class="office-footer">
      <span>点击工位进入当前任务，员工详情可查看职责与工作记录</span>
      <RouterLink class="office-text-link" to="/library"><BookOpen :size="14" />数字图书馆 <ChevronRight :size="14" /></RouterLink>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { Activity, ArrowUpRight, BookOpen, Check, ChevronRight, CircleCheck, Clock3, Hand, MessageCircleQuestion, Monitor, Plus, RefreshCw, TriangleAlert, UsersRound } from 'lucide-vue-next'
import { ElAlert, ElButton, ElSkeleton } from 'element-plus'
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import OfficeScene from '@/components/home/OfficeScene.vue'
import { useOfficeDashboard } from '@/features/home/useOfficeDashboard'
import { officeClock, parseOfficeTime, presentOfficeEmployees, presentOfficeEvents } from '@/features/home/officePresentation'
import { employeeDisplayName } from '@/utils/format'

const route = useRoute()
const { overview, employees, attention, activity, refreshing, partialError, updatedText, refreshDashboard } = useOfficeDashboard()
const searchQuery = computed(() => typeof route.query.q === 'string' ? route.query.q.trim() : '')
const officeEmployees = computed(() => presentOfficeEmployees(employees.data))
const officeEvents = computed(() => presentOfficeEvents((activity.data?.items ?? []).slice(0, 12)))
const overviewCopy = computed(() => {
  if (!overview.data) return overview.error ? '运行概况暂时无法获取' : '正在连接你的数字团队…'
  return '查看员工工作快照，处理需要你关注的任务'
})
function snapshotTime(value: Date) { return value.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) }
function shortReason(value: string) { return value.replace(/\s+/g, ' ').slice(0, 80) }
function fullTime(value: string) { return parseOfficeTime(value).toLocaleString('zh-CN', { hour12: false }) }
function eventTime(value: string) {
  const date = parseOfficeTime(value)
  return date.toLocaleDateString() === new Date().toLocaleDateString() ? officeClock(value)
    : `${date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })} ${officeClock(value)}`
}
</script>

<style scoped>
.dashboard-page{min-height:calc(100vh - 68px);min-width:0;max-width:1920px;margin:0 auto;padding:18px 28px 16px;color:var(--astra-text-primary)}
.office-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:16px;border:1px solid var(--astra-border);border-radius:12px;background:var(--astra-bg-panel);overflow:hidden}
.office-summary>a{display:flex;align-items:center;gap:12px;min-width:0;padding:14px 20px;color:var(--astra-text-muted)}
.office-summary>a+a{border-left:1px solid var(--astra-border)}
.office-summary>a:hover{background:var(--astra-primary-soft)}
.office-summary>a>svg{flex:none;color:var(--astra-primary-bright)}
.office-summary>a>span{display:flex;align-items:center;gap:14px;font-size:var(--astra-font-body)}
.office-summary strong{color:var(--astra-text-primary);font-size:var(--astra-font-section);font-variant-numeric:tabular-nums}
.office-summary small{margin-left:auto;font-size:var(--astra-font-helper);white-space:nowrap}
.office-summary>a[data-attention='true']{background:var(--astra-warning-soft)}
.office-summary>a[data-attention='true']>svg,.office-summary>a[data-attention='true'] strong{color:var(--astra-warning)}
.office-header{display:flex;justify-content:space-between;align-items:center;gap:24px;margin-bottom:16px}.office-header__eyebrow{display:flex;align-items:center;gap:7px;color:var(--astra-primary-bright);font-size:var(--astra-font-helper)}.office-header__eyebrow i{width:6px;height:6px;border-radius:50%;background:var(--astra-primary)}.office-header h1{margin:6px 0 7px;font-size:var(--astra-font-title);line-height:1.3}.office-header p{margin:0;color:var(--astra-text-muted);font-size:var(--astra-font-body)}.office-header__sync{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:flex-end}.office-header__sync small{color:var(--astra-text-muted);font-size:var(--astra-font-helper)}.sync-state{display:flex;align-items:center;gap:6px;font-size:var(--astra-font-helper);color:var(--astra-warning)}.sync-state i{width:6px;height:6px;border-radius:50%;background:currentColor}.office-error{margin-bottom:16px}
.office-layout{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:20px;align-items:start}.office-layout__main{min-width:0}.office-sidebar{display:grid;gap:16px;min-width:0}.office-loading,.office-module-state{padding:32px;border:1px solid var(--astra-border);border-radius:16px;background:var(--astra-bg-panel)}.office-loading{min-height:520px}.office-module-state{display:grid;justify-items:center;align-content:center;min-height:450px;text-align:center}.office-module-state h2{font-size:var(--astra-font-section);margin:12px 0 0}.office-module-state p{color:var(--astra-text-muted);font-size:var(--astra-font-body);overflow-wrap:anywhere}.office-module-state--error>svg{color:var(--astra-warning)}
.attention-panel,.activity-panel{padding:20px;border:1px solid var(--astra-border);border-radius:16px;background:var(--astra-bg-panel)}.attention-panel[data-attention='true']{border-color:color-mix(in srgb,var(--astra-warning) 40%,var(--astra-border));background:color-mix(in srgb,var(--astra-warning-soft) 26%,white)}.office-panel-header{display:flex;justify-content:space-between;align-items:center;gap:10px}.office-panel-header h2{display:flex;align-items:center;gap:7px;margin:0;font-size:var(--astra-font-subtitle)}.office-panel-header h2>svg{color:var(--astra-primary)}.attention-panel[data-attention='true'] h2>svg,.attention-panel h2>span{color:var(--astra-warning)}.office-panel-header>span{color:var(--astra-text-muted);font-size:var(--astra-font-helper);white-space:nowrap}.office-panel-header>a{display:flex;color:var(--astra-text-muted)}.office-panel-header>a:hover{color:var(--astra-primary)}.office-panel-message{display:flex;gap:8px;align-items:center;flex-wrap:wrap;min-height:66px;color:var(--astra-text-muted);font-size:var(--astra-font-helper)}.office-panel-message>svg{color:var(--astra-primary);flex:none}.office-panel-message--error>svg{color:var(--astra-warning)}
.attention-list{display:grid;margin-top:12px;gap:9px}.attention-item{display:flex;align-items:flex-start;gap:9px;min-width:0;padding:12px;border:1px solid color-mix(in srgb,var(--astra-warning) 28%,var(--astra-border));border-radius:10px;background:var(--astra-bg-panel)}.attention-item:hover{border-color:var(--astra-warning);box-shadow:var(--astra-shadow-panel)}.attention-item__icon{display:flex;flex:none;color:var(--astra-warning);margin-top:2px}.attention-item>div{flex:1;min-width:0}.attention-item strong{font-size:var(--astra-font-body);overflow-wrap:anywhere}.attention-item span:not(.attention-item__icon){display:block;margin-top:3px;color:var(--astra-warning);font-size:var(--astra-font-helper)}.attention-item p{margin:5px 0 0;color:var(--astra-text-secondary);font-size:var(--astra-font-helper);display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;overflow-wrap:anywhere}.attention-item small{display:block;overflow:hidden;margin-top:5px;color:var(--astra-text-muted);font-size:var(--astra-font-helper);white-space:nowrap;text-overflow:ellipsis}.attention-item>svg{flex:none;color:var(--astra-text-muted);margin-top:3px}.attention-item[data-status='FAILED'] .attention-item__icon,.attention-item[data-status='FAILED'] span:not(.attention-item__icon){color:var(--astra-danger)}
.activity-panel__intro{margin:6px 0 18px;color:var(--astra-text-muted);font-size:var(--astra-font-helper)}.activity-feed{display:grid;max-height:350px;overflow-y:auto;overscroll-behavior:contain;padding-right:4px}.activity-feed__item{position:relative;display:grid;grid-template-columns:18px minmax(0,1fr);gap:10px;padding:0 0 19px;color:inherit}.activity-feed__item::before{position:absolute;left:8px;top:21px;bottom:0;width:1px;background:var(--astra-border);content:''}.activity-feed__item:last-child::before{display:none}.activity-feed__dot{position:relative;display:grid;place-items:center;width:18px;height:18px;border-radius:50%;color:var(--astra-primary);background:var(--astra-primary-soft)}.activity-feed__dot>span{width:5px;height:5px;border-radius:50%;background:currentColor}.activity-feed__item[data-kind='waiting_human'] .activity-feed__dot{color:var(--astra-warning);background:var(--astra-warning-soft)}.activity-feed__item[data-kind='task_failed'] .activity-feed__dot{color:var(--astra-danger);background:var(--astra-danger-soft)}.activity-feed__item header{display:flex;align-items:baseline;justify-content:space-between;gap:10px}.activity-feed__item strong{overflow:hidden;color:var(--astra-text-secondary);font-size:var(--astra-font-body);text-overflow:ellipsis;white-space:nowrap}.activity-feed__item time{flex:none;color:var(--astra-text-muted);font-size:var(--astra-font-helper);font-variant-numeric:tabular-nums}.activity-feed__item p{margin:5px 0 0;font-size:var(--astra-font-helper);line-height:1.6;color:var(--astra-text-muted);overflow-wrap:anywhere;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}.activity-feed__item[href]:hover p{color:var(--astra-primary-bright)}.office-text-link{display:inline-flex;align-items:center;gap:4px;color:var(--astra-primary-bright);font-size:var(--astra-font-helper)}.office-text-link:hover{color:var(--astra-primary)}.activity-panel__link{margin-top:6px}
.office-footer{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px;margin-top:16px;padding:10px 2px 0;border-top:1px solid var(--astra-border)}
@media(min-width:1680px){.office-layout{grid-template-columns:minmax(0,1fr) 350px}.dashboard-page{padding-inline:36px}}
.attention-panel--empty{padding-block:14px}.attention-panel--empty .office-panel-message{min-height:0;margin-top:8px}.attention-panel--empty .office-panel-message>svg{width:16px;height:16px}
.attention-item time,.section-snapshot{display:block;margin-top:7px;font-size:var(--astra-font-helper);color:var(--astra-text-muted)}
.activity-feed__repeat{display:block;margin-top:4px;font-size:var(--astra-font-helper);color:var(--astra-text-secondary)}
.activity-feed__item[href]:focus-visible,.attention-item:focus-visible,.office-summary>a:focus-visible{outline:2px solid var(--astra-primary);outline-offset:-2px}
.activity-feed{max-height:clamp(280px,calc(100vh - 475px),540px)}
.office-footer>span{color:var(--astra-text-muted);font-size:var(--astra-font-helper)}
.office-snapshot-error{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin:0 0 10px;color:var(--astra-text-secondary);font-size:var(--astra-font-helper)}.office-snapshot-error>svg{color:var(--astra-warning);flex:none}
@media(max-width:1300px){.dashboard-page{padding-inline:20px}.office-layout{grid-template-columns:minmax(0,1fr) 300px;gap:16px}.office-summary>a{padding:12px 16px}.office-summary small{display:none}}
@media(max-width:1000px){.office-layout{grid-template-columns:minmax(0,1fr)}.office-sidebar{grid-template-columns:1fr 1fr;align-items:start}.office-header{align-items:flex-start}.office-header__sync{max-width:380px}.office-summary>a>span{gap:8px}}
@media(max-width:700px){.dashboard-page{padding:16px 12px}.office-header{flex-direction:column;gap:12px}.office-header__sync{justify-content:flex-start;max-width:none}.office-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.office-summary>a:nth-child(3){border-left:0;border-top:1px solid var(--astra-border)}.office-summary>a:nth-child(4){border-top:1px solid var(--astra-border)}.office-sidebar{grid-template-columns:1fr}.office-footer{align-items:flex-start}.office-header__eyebrow{display:none}}
</style>
