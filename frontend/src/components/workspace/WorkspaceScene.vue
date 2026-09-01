<template>
  <section ref="sceneElement" class="workspace-scene" aria-label="数字员工工作空间">
    <div class="workspace-stage">
      <img
        class="workspace-stage__art"
        src="/assets/workspace/nexus-office-game-v2.png"
        alt=""
        aria-hidden="true"
        @error="sceneFailed = true"
      />
      <div class="workspace-stage__light" aria-hidden="true" />

      <button
        v-for="group in areaGroups"
        :key="group.area.id"
        class="workspace-area-sign"
        :style="areaSignStyle(group.area)"
        type="button"
        :aria-label="`${group.area.name}，${group.employees.length} 名数字员工`"
        @click="openArea(group.area.id)"
      >
        <span>{{ group.area.shortName }}</span>
        <small v-if="group.hiddenCount">+{{ group.hiddenCount }}</small>
        <i v-if="group.hiddenNeedHelp" aria-label="有员工需要人工处理">!</i>
      </button>

      <EmployeeCharacter
        v-for="assignment in assignments"
        :key="assignment.employee.id"
        :employee="assignment.employee"
        :slot="assignment.slot"
        :selected="assignment.employee.id === selectedId"
        :show-bubble="bubbleEmployeeIds.has(assignment.employee.id)"
        @select="emit('select', $event)"
        @detail="emit('detail', $event)"
      />

      <EmployeePopover
        v-if="selectedAssignment"
        :employee="selectedAssignment.employee"
        :anchor-x="selectedAssignment.slot.x"
        :anchor-y="selectedAssignment.slot.y"
        @close="emit('select', '')"
        @detail="emit('detail', $event)"
      />

      <div v-if="sceneFailed" class="workspace-scene__error">
        <strong>办公空间资源加载失败</strong>
        <span>请检查场景图片是否完整。</span>
      </div>

      <div v-if="!employees.length" class="workspace-scene__empty">
        <strong>{{ emptyTitle }}</strong>
        <span>{{ emptyDescription }}</span>
        <RouterLink v-if="showCreate" class="button button--primary" to="/settings?create=1">创建数字员工</RouterLink>
      </div>
    </div>

    <AreaEmployeePopover
      v-if="openedAreaGroup"
      :area-name="openedAreaGroup.area.name"
      :employees="openedAreaGroup.employees"
      @close="openedAreaId = ''"
      @select="selectFromArea"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import type { Employee, Task } from '@/api/types'
import AreaEmployeePopover from '@/components/workspace/AreaEmployeePopover.vue'
import EmployeeCharacter from '@/components/workspace/EmployeeCharacter.vue'
import EmployeePopover from '@/components/workspace/EmployeePopover.vue'
import { toEmployeeViewModel, type EmployeeViewModel } from '@/features/employees/presentation'
import {
  availableAreaSlots,
  workspaceAreas,
  type SceneSlot,
  type WorkspaceArea,
  type WorkspaceAreaId,
} from '@/features/workspace/sceneLayout'

const props = withDefaults(defineProps<{
  employees: Employee[]
  tasks: Task[]
  selectedId?: string
  emptyTitle?: string
  emptyDescription?: string
  showCreate?: boolean
}>(), {
  selectedId: '',
  emptyTitle: '工作空间暂无数字员工',
  emptyDescription: '创建员工后，他们会进入对应的办公区域。',
  showCreate: false,
})
const emit = defineEmits<{ select: [id: string]; detail: [id: string] }>()

interface CharacterAssignment {
  employee: EmployeeViewModel
  slot: SceneSlot
}

const sceneElement = ref<HTMLElement | null>(null)
const sceneWidth = ref(1280)
const openedAreaId = ref<WorkspaceAreaId | ''>('')
const sceneFailed = ref(false)
let resizeObserver: ResizeObserver | undefined

const models = computed(() => props.employees.map((employee) => toEmployeeViewModel(employee, props.tasks)))

function employeePriority(employee: EmployeeViewModel): number {
  if (employee.id === props.selectedId) return 0
  if (employee.needHelp) return 1
  if (employee.status === 'WORKING') return 2
  if (employee.status === 'IDLE') return 3
  return 4
}

const areaGroups = computed(() => workspaceAreas.map((area) => {
  const employees = models.value
    .filter((employee) => employee.areaId === area.id)
    .sort((left, right) => employeePriority(left) - employeePriority(right)
      || (right.lastActiveAt ?? '').localeCompare(left.lastActiveAt ?? '')
      || left.id.localeCompare(right.id))
  const slots = availableAreaSlots(area, sceneWidth.value)
  const visibleEmployees = employees.slice(0, slots.length)
  const hiddenEmployees = employees.slice(slots.length)
  return {
    area,
    employees,
    assignments: visibleEmployees.map((employee, index) => ({ employee, slot: slots[index] })),
    hiddenCount: hiddenEmployees.length,
    hiddenNeedHelp: hiddenEmployees.some((employee) => employee.needHelp),
  }
}))

const assignments = computed<CharacterAssignment[]>(() => areaGroups.value.flatMap((group) => group.assignments))
const selectedAssignment = computed(() => assignments.value.find((assignment) => assignment.employee.id === props.selectedId))
const openedAreaGroup = computed(() => areaGroups.value.find((group) => group.area.id === openedAreaId.value && group.employees.length))
const bubbleEmployeeIds = computed(() => {
  const result = new Set<string>()
  assignments.value.forEach(({ employee }) => {
    if (employee.needHelp || employee.id === props.selectedId) result.add(employee.id)
  })
  assignments.value
    .filter(({ employee }) => employee.status === 'WORKING' && !result.has(employee.id))
    .sort((left, right) => (right.employee.lastActiveAt ?? '').localeCompare(left.employee.lastActiveAt ?? ''))
    .slice(0, 2)
    .forEach(({ employee }) => result.add(employee.id))
  return result
})

function areaSignStyle(area: WorkspaceArea) {
  return { left: `${area.labelX}%`, top: `${area.labelY}%` }
}

function openArea(areaId: WorkspaceAreaId) {
  const group = areaGroups.value.find((item) => item.area.id === areaId)
  if (group?.employees.length) openedAreaId.value = areaId
}

function selectFromArea(id: string) {
  openedAreaId.value = ''
  emit('select', id)
}

onMounted(() => {
  if (!sceneElement.value) return
  resizeObserver = new ResizeObserver(([entry]) => { sceneWidth.value = entry.contentRect.width })
  resizeObserver.observe(sceneElement.value)
  sceneWidth.value = sceneElement.value.clientWidth
})
onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<style scoped>
.workspace-scene {
  position: absolute;
  inset: 0;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid rgba(196,216,207,.9);
  border-radius: 20px;
  background: #edf6f1;
  box-shadow: 0 16px 38px rgba(32,74,58,.10);
  container-type: size;
}
.workspace-stage {
  position: absolute;
  top: 50%;
  left: 50%;
  width: max(100cqw,156.33cqh);
  height: max(100cqh,63.97cqw);
  overflow: hidden;
  transform: translate(-50%,-50%);
}
.workspace-stage__art { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: fill; user-select: none; }
.workspace-stage__light { position: absolute; inset: 0; pointer-events: none; background: linear-gradient(180deg,rgba(255,255,255,.04),transparent 24%,rgba(16,91,61,.025)); }
.workspace-area-sign {
  position: absolute;
  z-index: 132;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 31px;
  padding: 5px 10px;
  color: #fff;
  border: 2px solid rgba(255,255,255,.85);
  border-radius: 7px;
  background: linear-gradient(145deg,#14895c,#087449);
  box-shadow: 0 5px 11px rgba(25,84,62,.22);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .04em;
  white-space: nowrap;
  cursor: pointer;
  transform: translate(-50%,-50%) rotate(-2deg);
  transition: transform .16s ease,filter .16s ease;
}
.workspace-area-sign:hover { filter: brightness(1.07); transform: translate(-50%,-53%) rotate(-1deg); }
.workspace-area-sign small { display: grid; place-items: center; min-width: 18px; height: 18px; padding: 0 4px; color: #0c714b; border-radius: 9px; background: #fff; font-size: 9px; }
.workspace-area-sign i { display: grid; place-items: center; width: 18px; height: 18px; margin-right: -5px; color: #fff; border: 2px solid #fff; border-radius: 50%; background: var(--astra-warning); font-size: 10px; font-style: normal; }
.workspace-scene__empty,.workspace-scene__error { position: absolute; z-index: 180; top: 46%; left: 50%; display: grid; place-items: center; gap: 6px; min-width: 280px; padding: 18px; color: var(--astra-text-secondary); border: 1px solid rgba(202,219,212,.9); border-radius: 14px; background: rgba(255,255,255,.96); box-shadow: 0 14px 32px rgba(37,72,59,.14); text-align: center; transform: translate(-50%,-50%); }
.workspace-scene__empty strong,.workspace-scene__error strong { color: var(--astra-text-primary); font-size: 14px; }.workspace-scene__empty span,.workspace-scene__error span { font-size: 11px; }.workspace-scene__empty .button { margin-top: 4px; }
@media(max-height:800px){.workspace-area-sign{min-height:27px;padding:4px 8px;font-size:10px}}
@media(max-width:900px){.workspace-scene{position:relative;min-height:660px}}
</style>
