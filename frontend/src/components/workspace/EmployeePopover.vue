<template>
  <aside class="employee-popover" :data-side="popoverSide" :style="popoverStyle" role="dialog" :aria-label="`${employee.name} 基础信息`">
    <header>
      <EmployeeAvatar :employee="employee.employee" />
      <div><strong>{{ employee.name }}</strong><small>{{ employee.id }} · {{ employee.role }}</small></div>
      <AstraStatusBadge :status="employee.status" :pulse="employee.status === 'WORKING'" />
      <button type="button" aria-label="关闭员工信息" @click="emit('close')"><X :size="15" /></button>
    </header>
    <div v-if="employee.needHelp" class="employee-popover__help"><CircleAlert :size="15" /><span><strong>需要人工处理</strong>{{ helpReason }}</span></div>
    <dl>
      <div><dt>当前任务</dt><dd>{{ employee.currentTaskName }}</dd></div>
      <div><dt>所在区域</dt><dd>{{ employee.areaName }}</dd></div>
      <div><dt>最近活动</dt><dd>{{ formatTime(employee.lastActiveAt) }}</dd></div>
    </dl>
    <footer>
      <button class="button" type="button" @click="emit('detail', employee.id)">查看详情</button>
      <RouterLink v-if="employee.currentTask" class="button button--primary" :to="`/tasks/${employee.currentTask.id}`">查看当前任务</RouterLink>
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { CircleAlert, X } from 'lucide-vue-next'
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeeAvatar from '@/components/employee/EmployeeAvatar.vue'
import type { EmployeeViewModel } from '@/features/employees/presentation'
import { formatTime } from '@/utils/format'

const props = withDefaults(defineProps<{ employee: EmployeeViewModel; anchorX?: number; anchorY?: number }>(), { anchorX: 82, anchorY: 20 })
const emit = defineEmits<{ close: []; detail: [id: string] }>()
const helpReason = computed(() => props.employee.currentTask?.human_required_reason || props.employee.currentTask?.human_intervention?.requested_input || props.employee.statusTextLong)
const popoverSide = computed(() => props.anchorX > 64 ? 'left' : 'right')
const popoverStyle = computed(() => ({
  '--popover-x': `${props.anchorX}%`,
  '--popover-y': `${Math.min(54, Math.max(19, props.anchorY - 7))}%`,
}))
</script>

<style scoped>
.employee-popover { position: absolute; z-index: 170; top: var(--popover-y); left: var(--popover-x); width: min(350px,calc(100% - 36px)); overflow: hidden; border: 1px solid rgba(201,218,211,.94); border-radius: 14px; background: rgba(255,255,255,.98); box-shadow: 0 18px 45px rgba(26,62,51,.18); transform: translate(18px,-42%); }
.employee-popover[data-side='left'] { transform: translate(calc(-100% - 18px),-42%); }
.employee-popover > header { position: relative; display: grid; grid-template-columns: auto minmax(0,1fr) auto; align-items: center; gap: 10px; padding: 14px 42px 12px 14px; border-bottom: 1px solid var(--astra-border); }.employee-popover header > div { display: grid; min-width: 0; }.employee-popover header strong,.employee-popover header small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.employee-popover header strong { font-size: 15px; }.employee-popover header small { color: var(--astra-text-muted); font-size: 11px; }.employee-popover header > button { position: absolute; top: 10px; right: 10px; display: grid; place-items: center; width: 28px; height: 28px; color: var(--astra-text-muted); border: 0; border-radius: 7px; background: transparent; cursor: pointer; }.employee-popover header > button:hover { background: #f1f6f3; }
.employee-popover__help { display: flex; gap: 8px; margin: 12px 14px 0; padding: 10px; color: #9a5e18; border-radius: 9px; background: #fff6e9; }.employee-popover__help > svg { flex: none; margin-top: 2px; }.employee-popover__help span { display: grid; font-size: 12px; }.employee-popover__help strong { font-size: 12px; }
.employee-popover dl { display: grid; gap: 0; margin: 0; padding: 7px 14px; }.employee-popover dl > div { display: grid; grid-template-columns: 72px minmax(0,1fr); gap: 10px; padding: 7px 0; }.employee-popover dt { color: var(--astra-text-muted); font-size: 12px; }.employee-popover dd { overflow: hidden; margin: 0; color: var(--astra-text-primary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.employee-popover footer { display: flex; justify-content: flex-end; gap: 7px; padding: 11px 14px; border-top: 1px solid var(--astra-border); }.employee-popover footer .button { min-height: 34px; padding-inline: 12px; font-size: 12px; }
@media(max-width:700px){.employee-popover,.employee-popover[data-side='left']{position:fixed;top:auto;right:12px;bottom:12px;left:12px;width:auto;transform:none}}
</style>
