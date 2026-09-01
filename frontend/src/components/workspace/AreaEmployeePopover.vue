<template>
  <div class="area-popover-layer" role="presentation" @click.self="emit('close')">
    <section class="area-popover" role="dialog" aria-modal="true" :aria-label="`${areaName}员工列表`">
      <header><div><small>区域员工</small><h2>{{ areaName }}</h2><p>共 {{ employees.length }} 名数字员工</p></div><button class="icon-button" type="button" aria-label="关闭区域员工列表" @click="emit('close')"><X :size="17" /></button></header>
      <div class="area-popover__list">
        <button v-for="employee in employees" :key="employee.id" type="button" @click="emit('select', employee.id)">
          <EmployeeAvatar :employee="employee.employee" />
          <span><strong>{{ employee.name }}</strong><small>{{ employee.id }} · {{ employee.role }}</small><em>{{ employee.currentTaskName }}</em></span>
          <AstraStatusBadge :status="employee.status" />
          <CircleAlert v-if="employee.needHelp" class="area-popover__alert" :size="17" />
          <ChevronRight :size="16" />
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ChevronRight, CircleAlert, X } from 'lucide-vue-next'
import AstraStatusBadge from '@/components/astra/AstraStatusBadge.vue'
import EmployeeAvatar from '@/components/employee/EmployeeAvatar.vue'
import type { EmployeeViewModel } from '@/features/employees/presentation'

defineProps<{ areaName: string; employees: EmployeeViewModel[] }>()
const emit = defineEmits<{ close: []; select: [id: string] }>()
</script>

<style scoped>
.area-popover-layer { position: absolute; inset: 0; z-index: 35; display: grid; place-items: center; padding: 18px; background: rgba(35,61,53,.18); }
.area-popover { display: grid; grid-template-rows: auto minmax(0,1fr); width: min(520px,100%); max-height: min(560px,calc(100% - 24px)); overflow: hidden; border: 1px solid var(--astra-border); border-radius: 15px; background: white; box-shadow: 0 22px 50px rgba(28,58,49,.20); }
.area-popover > header { display: flex; justify-content: space-between; gap: 16px; padding: 16px 18px; border-bottom: 1px solid var(--astra-border); }.area-popover header small { color: var(--astra-primary); font-size: 11px; }.area-popover header h2 { margin: 0; font: 700 20px var(--astra-font-display); }.area-popover header p { margin: 1px 0 0; color: var(--astra-text-muted); font-size: 12px; }
.area-popover__list { min-height: 0; overflow-y: auto; padding: 6px 14px 14px; }.area-popover__list > button { display: grid; grid-template-columns: auto minmax(0,1fr) auto auto auto; align-items: center; gap: 10px; width: 100%; padding: 10px 4px; color: inherit; text-align: left; border: 0; border-bottom: 1px solid var(--astra-border); background: transparent; cursor: pointer; }.area-popover__list > button:hover { background: #f4faf7; }.area-popover__list > button > span { display: grid; min-width: 0; }.area-popover__list strong,.area-popover__list small,.area-popover__list em { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.area-popover__list strong { font-size: 14px; }.area-popover__list small { color: var(--astra-text-muted); font-size: 11px; }.area-popover__list em { color: var(--astra-text-secondary); font-size: 12px; font-style: normal; }.area-popover__alert { color: var(--astra-warning); }
</style>
