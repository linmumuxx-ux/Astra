<template>
  <button
    class="employee-character"
    :class="{
      'employee-character--selected': selected,
      'employee-character--muted': employee.status === 'OFFLINE',
      'employee-character--help': employee.needHelp,
    }"
    :data-status="employee.status"
    :data-pose="slot.pose"
    :style="characterStyle"
    :aria-label="`${employee.name} ${employee.role} ${employee.statusText}`"
    type="button"
    @click="emit('select', employee.id)"
    @dblclick="emit('detail', employee.id)"
  >
    <span v-if="showBubble" class="employee-character__bubble" :data-help="employee.needHelp">
      <CircleAlert v-if="employee.needHelp" :size="13" />{{ bubbleText }}
    </span>
    <span class="employee-character__visual" aria-hidden="true">
      <span class="employee-character__sprite" />
      <span v-if="employee.needHelp" class="employee-character__help">!</span>
      <span class="employee-character__halo" />
    </span>
    <span class="employee-character__name">{{ employee.name }}</span>
  </button>
</template>

<script setup lang="ts">
import { CircleAlert } from 'lucide-vue-next'
import { computed } from 'vue'
import type { EmployeeViewModel } from '@/features/employees/presentation'
import { employeeCharacterStyle } from '@/features/workspace/characterAssets'
import type { SceneSlot } from '@/features/workspace/sceneLayout'

const props = defineProps<{
  employee: EmployeeViewModel
  slot: SceneSlot
  selected?: boolean
  showBubble?: boolean
}>()
const emit = defineEmits<{ select: [id: string]; detail: [id: string] }>()
const bubbleText = computed(() => {
  const copy = props.employee.statusTextLong.replace(/[。！!]+$/u, '')
  return copy.length > 14 ? `${copy.slice(0, 14)}…` : copy
})
const characterStyle = computed(() => ({
  ...employeeCharacterStyle(props.employee.id, props.slot.pose),
  '--character-x': `${props.slot.x}%`,
  '--character-y': `${props.slot.y}%`,
  '--character-size': `${props.slot.scale}%`,
  '--character-depth': String(20 + props.slot.depth),
}))
</script>

<style scoped>
.employee-character {
  position: absolute;
  z-index: var(--character-depth);
  top: var(--character-y);
  left: var(--character-x);
  display: block;
  width: var(--character-size);
  min-width: 72px;
  max-width: 136px;
  padding: 0;
  color: inherit;
  border: 0;
  background: transparent;
  cursor: pointer;
  transform: translate(-50%,-100%);
}
.employee-character:focus-visible { border-radius: 50%; outline: 3px solid rgba(18,156,98,.34); outline-offset: 4px; }
.employee-character__visual { position: relative; display: block; width: 100%; transition: transform .2s ease,filter .2s ease,opacity .2s ease; }
.employee-character__sprite {
  position: relative;
  z-index: 2;
  display: block;
  width: 100%;
  aspect-ratio: .8;
  background-image: var(--character-atlas);
  background-repeat: no-repeat;
  background-position: var(--sprite-x) var(--sprite-y);
  background-size: 400% 300%;
  filter: drop-shadow(0 7px 6px rgba(45,67,56,.19));
}
.employee-character[data-pose='seated'] .employee-character__sprite { aspect-ratio: .767; }
.employee-character:hover .employee-character__visual,.employee-character--selected .employee-character__visual { transform: translateY(-4px) scale(1.04); filter: saturate(1.06); }
.employee-character__halo { position: absolute; z-index: 1; right: 12%; bottom: 1%; left: 12%; height: 10%; border-radius: 50%; background: rgba(28,190,121,.22); filter: blur(5px); opacity: 0; transition: opacity .18s ease; }
.employee-character--selected .employee-character__halo { opacity: 1; box-shadow: 0 0 0 8px rgba(24,184,117,.10); }
.employee-character__help { position: absolute; z-index: 5; top: 5%; right: 2%; display: grid; place-items: center; width: 25px; height: 25px; color: #fff; border: 2px solid #fff; border-radius: 50%; background: var(--astra-warning); box-shadow: 0 5px 13px rgba(218,128,42,.33); font-size: 14px; font-weight: 850; }
.employee-character__name { position: absolute; z-index: 7; bottom: -18px; left: 50%; max-width: 130px; padding: 3px 8px; overflow: hidden; color: #174638; border: 1px solid rgba(170,204,190,.78); border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: 0 4px 10px rgba(36,73,59,.10); font-size: 10px; font-weight: 750; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; opacity: 0; pointer-events: none; transform: translate(-50%,4px); transition: opacity .16s ease,transform .16s ease; }
.employee-character:hover .employee-character__name,.employee-character--selected .employee-character__name,.employee-character--help .employee-character__name { opacity: 1; transform: translate(-50%,0); }
.employee-character__bubble { position: absolute; z-index: 9; bottom: calc(100% - 5px); left: 50%; display: flex; align-items: center; gap: 5px; width: max-content; max-width: 190px; padding: 7px 10px; color: #35554c; border: 1px solid #d7e4df; border-radius: 10px; background: rgba(255,255,255,.97); box-shadow: 0 8px 20px rgba(34,67,57,.13); font-size: 11px; white-space: nowrap; transform: translateX(-50%); }
.employee-character__bubble::after { position: absolute; top: 100%; left: calc(50% - 5px); border: 5px solid transparent; border-top-color: #fff; content: ''; }
.employee-character__bubble[data-help='true'] { color: #945716; border-color: #f0d3ae; }
.employee-character--muted .employee-character__visual { filter: grayscale(.7); opacity: .54; }
@media(max-height:800px){.employee-character{min-width:64px;max-width:108px}.employee-character__bubble{padding:5px 8px;font-size:10px}.employee-character__help{width:22px;height:22px;font-size:12px}}
</style>
