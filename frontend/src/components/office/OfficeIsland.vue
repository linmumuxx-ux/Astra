<template>
  <div
    class="office-island"
    :class="`office-island--${island.capacity}`"
    :data-testid="`office-island-${island.capacity}`"
    :data-occupied="occupiedCount"
    :aria-label="`${occupiedCount} 人 ${island.capacity} 座办公岛`"
  >
    <div class="office-island__row office-island__row--back">
      <template v-for="(employee, index) in backSeats" :key="employee?.id ?? `back-empty-${index}`">
        <EmployeeSeat
          v-if="employee"
          :employee="employee"
          row="back"
          :selected="employee.id === selectedId"
          :muted="Boolean(query) && !matchedIds.has(employee.id)"
          :show-bubble="bubbleModes.has(employee.id)"
          :bubble-mode="bubbleModes.get(employee.id)"
          @select="emit('select', $event)"
        />
      </template>
    </div>

    <div class="office-island__row office-island__row--front">
      <template v-for="(employee, index) in frontSeats" :key="employee?.id ?? `front-empty-${index}`">
        <EmployeeSeat
          v-if="employee"
          :employee="employee"
          row="front"
          :selected="employee.id === selectedId"
          :muted="Boolean(query) && !matchedIds.has(employee.id)"
          :show-bubble="bubbleModes.has(employee.id)"
          :bubble-mode="bubbleModes.get(employee.id)"
          @select="emit('select', $event)"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import EmployeeSeat from '@/components/office/EmployeeSeat.vue'
import type { OfficeIslandLayout } from '@/features/office/officeLayout'

type BubbleMode = 'alert'
const props = withDefaults(defineProps<{
  island: OfficeIslandLayout
  selectedId?: string
  query?: string
  matchedIds: Set<string>
  bubbleModes: Map<string, BubbleMode>
}>(), { selectedId: '', query: '' })
const emit = defineEmits<{ select: [id: string] }>()
const seatsPerSide = computed(() => props.island.capacity / 2)
const backSeats = computed(() => props.island.employees.slice(0, seatsPerSide.value))
const frontSeats = computed(() => props.island.employees.slice(seatsPerSide.value))
const occupiedCount = computed(() => props.island.employees.filter(Boolean).length)
</script>

<style scoped>
.office-island{position:relative;display:grid;grid-template-rows:1fr 1fr;width:100%;height:100%;min-height:145px}.office-island__row{display:flex;align-items:flex-end;justify-content:center;gap:clamp(2px,.5vw,9px);min-width:0}.office-island__row--front{margin-top:-28px;padding-left:10%}.office-island__row :deep(.employee-seat:nth-child(n+4)){display:none}.office-island__row--back :deep(.employee-seat){transform:scale(.84);transform-origin:center bottom}.office-island__row--back :deep(.employee-seat:hover),.office-island__row--back :deep(.employee-seat--selected){transform:translateY(-5px) scale(.84)}
@media(max-width:720px){.office-island__row{gap:0}.office-island__row--front{padding-left:14%}.office-island__row :deep(.employee-seat:nth-child(n+3)){display:none}}
</style>
