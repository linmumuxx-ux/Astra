<template>
  <section class="office-summary" aria-label="数字办公室状态摘要">
    <div class="office-summary__title">
      <h1>NEXUS 数字办公室</h1>
      <p>让测试更智能 · 让质量更可靠</p>
    </div>

    <div class="office-summary__metrics">
      <span class="office-summary__total"><BriefcaseBusiness :size="18" />数字员工 <strong>{{ employees.length }}</strong></span>
      <span data-tone="working"><i />工作中 <strong>{{ counts.working }}</strong></span>
      <span data-tone="pending"><i />待处理 <strong>{{ counts.pending }}</strong></span>
      <span data-tone="idle"><i />空闲 <strong>{{ counts.idle }}</strong></span>
      <span data-tone="error"><i />异常 <strong>{{ counts.error }}</strong></span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { BriefcaseBusiness } from 'lucide-vue-next'
import { computed } from 'vue'
import type { OfficeTeam } from '@/features/office/officeLayout'
import type { WorkspaceEmployee } from '@/features/workspace/eventAdapter'

const props = withDefaults(defineProps<{ employees: WorkspaceEmployee[]; teams: OfficeTeam[]; activeTeamId?: string }>(), { activeTeamId: '' })
defineEmits<{ locate: [teamId: string] }>()
const counts = computed(() => {
  const working = props.employees.filter((employee) => employee.state === 'WORKING').length
  const pending = props.employees.filter((employee) => ['WAITING', 'NEED_HUMAN'].includes(employee.state)).length
  const error = props.employees.filter((employee) => employee.state === 'ERROR').length
  return { working, pending, error, idle: Math.max(0, props.employees.length - working - pending - error) }
})
</script>

<style scoped>
.office-summary{position:absolute;z-index:30;top:0;right:0;left:0;height:126px;pointer-events:none;background:linear-gradient(180deg,rgba(252,254,253,.78),rgba(250,253,252,.36) 60%,transparent)}
.office-summary__title{position:absolute;top:23px;left:clamp(24px,2.7vw,50px)}.office-summary h1{margin:0;color:#0f4035;font: var(--astra-weight-bold) clamp(var(--astra-font-size-23),2vw,var(--astra-font-size-30))/1.1 var(--astra-font-display);letter-spacing:-.035em;text-shadow:0 1px rgba(255,255,255,.82)}.office-summary__title p{margin:8px 0 0;color:#71847d;font-size: var(--astra-font-body);letter-spacing:.08em}
.office-summary__metrics{position:absolute;top:23px;left:50%;display:flex;align-items:center;height:56px;padding:0 16px;color:#64776f;border:1px solid rgba(207,220,215,.9);border-radius:12px;background:rgba(255,255,255,.91);box-shadow:0 12px 34px rgba(49,83,71,.09);font-size: var(--astra-font-control);white-space:nowrap;pointer-events:auto;transform:translateX(-50%);backdrop-filter:blur(15px)}.office-summary__metrics>span{display:flex;align-items:center;gap:7px;height:26px;padding:0 18px;border-left:1px solid #e0e9e5}.office-summary__metrics>span:first-child{border-left:0}.office-summary__metrics strong{color:#294a41;font-size:var(--astra-font-size-15);font-variant-numeric:tabular-nums}.office-summary__metrics i{width:8px;height:8px;border-radius:50%;background:#9da8a4}.office-summary__metrics [data-tone='working'] i{background:#13ae73}.office-summary__metrics [data-tone='pending'] i{background:#f2a12a}.office-summary__metrics [data-tone='error'] i{background:#ef4d55}.office-summary__total{color:#4b625a;font-weight: var(--astra-weight-bold)}.office-summary__total svg{color:#315a50}.office-summary__total strong{font-size:var(--astra-font-size-20)}
@media(max-width:1220px){.office-summary__title{top:18px}.office-summary__metrics{top:85px}.office-summary{height:157px}.office-summary__metrics>span{padding-inline:13px}}
@media(max-width:720px){.office-summary{height:132px}.office-summary__title{top:15px;left:14px}.office-summary h1{font-size: var(--astra-font-title)}.office-summary__title p{margin-top:5px;font-size: var(--astra-font-micro)}.office-summary__metrics{top:75px;left:12px;right:12px;width:auto;height:46px;padding:0 5px;overflow-x:auto;transform:none}.office-summary__metrics>span{flex:none;height:24px;padding:0 10px;font-size: var(--astra-font-micro)}.office-summary__metrics strong{font-size: var(--astra-font-body)}.office-summary__total strong{font-size: var(--astra-font-subtitle)}}
</style>
