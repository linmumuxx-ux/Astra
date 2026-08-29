<template>
  <figure class="employee-workstation" :data-status="status" :data-pose="pose" :data-variant="visualVariant" aria-hidden="true">
    <img v-if="asset" :src="asset" alt="" />
    <span v-else class="employee-workstation__empty">
      <i class="employee-workstation__monitor" />
      <i class="employee-workstation__desk" />
      <i class="employee-workstation__chair" />
    </span>
    <span v-if="status === 'ERROR'" class="employee-workstation__alert">!</span>
    <span class="employee-workstation__signal" />
  </figure>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ employeeId: string; status: string; variant?: number }>()

const visualVariant = computed(() => {
  const numericId = Number(props.employeeId.match(/(\d+)(?!.*\d)/)?.[1] ?? 1)
  return ((Math.max(1, props.variant ?? numericId) - 1) % 4) + 1
})
const pose = computed(() => ({
  WORKING: 'working',
  IDLE: 'idle',
  WAIT_HUMAN: 'waiting',
  ERROR: 'error',
  PAUSED: 'idle',
  OFFLINE: 'offline',
}[props.status] ?? 'offline'))
const asset = computed(() => ({
  working: '/assets/employees/nexus-workstation-01.png',
  idle: '/assets/employees/nexus-workstation-02.png',
  waiting: '/assets/employees/nexus-workstation-04.png',
  error: '/assets/employees/nexus-workstation-03.png',
}[pose.value] ?? ''))
</script>

<style scoped>
.employee-workstation { position: relative; width: 100%; height: 100%; margin: 0; overflow: hidden; }
.employee-workstation::before { position: absolute; right: 8%; bottom: 5%; left: 8%; height: 15%; border-radius: 50%; background: rgba(11,42,34,.28); filter: blur(13px); content: ''; }
.employee-workstation::after { position: absolute; z-index: 2; right: 11%; bottom: 6%; left: 11%; height: 26%; border-radius: 50%; background: radial-gradient(ellipse,rgba(32,207,133,.13),transparent 66%); pointer-events: none; content: ''; }
.employee-workstation img { position: relative; z-index: 1; display: block; width: 100%; height: 100%; object-fit: contain; object-position: center bottom; filter: contrast(1.06) drop-shadow(0 18px 14px rgba(16,43,36,.25)); transition: filter .22s ease, transform .22s ease, opacity .22s ease; }
.employee-workstation[data-pose='working'] img { transform: scale(1.05); }
.employee-workstation[data-pose='idle'] img { transform: scale(1.02); }
.employee-workstation[data-pose='waiting'] img { transform: scale(.94); transform-origin: center bottom; }
.employee-workstation[data-pose='error'] img { transform: scale(1.07); }
.employee-workstation[data-variant='2'] img { object-position: 48% bottom; }
.employee-workstation[data-variant='3'] img { object-position: 52% bottom; }
.employee-workstation__signal { position: absolute; z-index: 4; right: 10%; bottom: 10%; width: 10px; height: 10px; border: 2px solid rgba(255,255,255,.94); border-radius: 50%; background: var(--employee-signal,var(--astra-success)); box-shadow: 0 0 0 0 color-mix(in srgb,var(--employee-signal,var(--astra-success)) 34%,transparent); }
.employee-workstation__alert { position: absolute; z-index: 4; top: 19%; right: 12%; display: grid; place-items: center; width: 28px; height: 28px; color: #fff; font: 800 18px var(--astra-font-display); border: 1px solid rgba(255,255,255,.8); border-radius: 8px; background: rgba(208,55,70,.92); box-shadow: 0 0 24px rgba(208,55,70,.42); }
.employee-workstation__empty { position: absolute; inset: 12% 8% 3%; z-index: 1; display: block; opacity: .8; }
.employee-workstation__monitor { position: absolute; top: 15%; left: 50%; width: 44%; height: 32%; border: 7px solid #d9e0df; border-radius: 7px; background: #50605e; box-shadow: inset 0 0 0 2px rgba(255,255,255,.16),0 15px 24px rgba(17,43,37,.16); transform: translateX(-50%); }
.employee-workstation__monitor::after { position: absolute; top: 100%; left: 50%; width: 9px; height: 28px; background: #c9d2d0; content: ''; transform: translateX(-50%); }
.employee-workstation__desk { position: absolute; right: 5%; bottom: 24%; left: 5%; height: 10px; border-radius: 4px; background: #eef2f1; box-shadow: 0 5px 0 #c6d0ce,0 16px 22px rgba(19,49,41,.18); }
.employee-workstation__desk::before,.employee-workstation__desk::after { position: absolute; top: 9px; width: 9px; height: 68px; border-radius: 0 0 5px 5px; background: #cbd4d2; content: ''; }
.employee-workstation__desk::before { left: 12%; }.employee-workstation__desk::after { right: 12%; }
.employee-workstation__chair { position: absolute; bottom: 2%; left: 50%; width: 29%; height: 30%; border: 7px solid #9aa8a5; border-radius: 22px 22px 10px 10px; background: rgba(68,84,80,.44); transform: translateX(-50%); }
.employee-workstation[data-status='WORKING'] { --employee-signal: var(--astra-success); }
.employee-workstation[data-status='WAIT_HUMAN'] { --employee-signal: var(--astra-warning); }
.employee-workstation[data-status='ERROR'] { --employee-signal: var(--astra-danger); }
.employee-workstation[data-status='IDLE'] { --employee-signal: var(--astra-info); }
.employee-workstation[data-status='OFFLINE'],.employee-workstation[data-status='PAUSED'] { --employee-signal: #7d8c89; }
.employee-workstation[data-status='IDLE'] img,.employee-workstation[data-status='PAUSED'] img { filter: brightness(.94) saturate(.76) contrast(1.05) drop-shadow(0 17px 14px rgba(16,43,36,.2)); opacity: .94; }
.employee-workstation[data-status='PAUSED'] img { filter: grayscale(.35) saturate(.5) contrast(1.04) drop-shadow(0 17px 14px rgba(16,43,36,.18)); opacity: .82; }
.employee-workstation[data-status='ERROR'] img { filter: saturate(.78) contrast(1.12) drop-shadow(0 18px 17px rgba(178,43,57,.26)); }
.employee-workstation[data-status='OFFLINE']::after { display: none; }
.employee-workstation[data-status='WORKING'] .employee-workstation__signal,.employee-workstation[data-status='WAIT_HUMAN'] .employee-workstation__signal,.employee-workstation[data-status='ERROR'] .employee-workstation__signal { animation: workstation-signal 1.8s ease-out infinite; }
@keyframes workstation-signal { 65% { box-shadow: 0 0 0 9px transparent; } 100% { box-shadow: 0 0 0 12px transparent; } }
@media (prefers-reduced-motion: reduce) { .employee-workstation__signal { animation: none !important; } }
</style>
