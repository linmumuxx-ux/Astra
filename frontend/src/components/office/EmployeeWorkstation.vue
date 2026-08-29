<template>
  <figure class="employee-workstation" :data-status="status" aria-hidden="true">
    <img :src="asset" alt="" />
    <span class="employee-workstation__signal" />
  </figure>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ employeeId: string; status: string; variant?: number }>()

const asset = computed(() => {
  const numericId = Number(props.employeeId.match(/(\d+)(?!.*\d)/)?.[1] ?? 1)
  const index = ((Math.max(1, props.variant ?? numericId) - 1) % 4) + 1
  return `/assets/employees/nexus-workstation-0${index}.png`
})
</script>

<style scoped>
.employee-workstation { position: relative; width: 100%; height: 100%; margin: 0; }
.employee-workstation::before { position: absolute; right: 12%; bottom: 6%; left: 12%; height: 12%; border-radius: 50%; background: rgba(20,52,44,.2); filter: blur(14px); content: ''; }
.employee-workstation img { position: relative; z-index: 1; display: block; width: 100%; height: 100%; object-fit: contain; object-position: center bottom; filter: drop-shadow(0 18px 16px rgba(24,55,46,.17)); transition: filter .22s ease, transform .22s ease, opacity .22s ease; }
.employee-workstation__signal { position: absolute; z-index: 2; right: 14%; bottom: 13%; width: 9px; height: 9px; border: 2px solid rgba(255,255,255,.9); border-radius: 50%; background: var(--employee-signal,var(--astra-success)); box-shadow: 0 0 0 0 color-mix(in srgb,var(--employee-signal,var(--astra-success)) 34%,transparent); }
.employee-workstation[data-status='WORKING'] { --employee-signal: var(--astra-success); }
.employee-workstation[data-status='WAIT_HUMAN'] { --employee-signal: var(--astra-warning); }
.employee-workstation[data-status='ERROR'] { --employee-signal: var(--astra-danger); }
.employee-workstation[data-status='IDLE'] { --employee-signal: var(--astra-info); }
.employee-workstation[data-status='OFFLINE'],.employee-workstation[data-status='PAUSED'] { --employee-signal: #7d8c89; }
.employee-workstation[data-status='IDLE'] img { filter: saturate(.74) drop-shadow(0 16px 15px rgba(24,55,46,.14)); opacity: .9; }
.employee-workstation[data-status='OFFLINE'] img,.employee-workstation[data-status='PAUSED'] img { filter: grayscale(.55) saturate(.45) drop-shadow(0 14px 12px rgba(24,55,46,.11)); opacity: .7; }
.employee-workstation[data-status='ERROR'] img { filter: saturate(.86) drop-shadow(0 18px 17px rgba(215,72,86,.18)); }
.employee-workstation[data-status='WORKING'] .employee-workstation__signal,.employee-workstation[data-status='WAIT_HUMAN'] .employee-workstation__signal,.employee-workstation[data-status='ERROR'] .employee-workstation__signal { animation: workstation-signal 1.8s ease-out infinite; }
@keyframes workstation-signal { 65% { box-shadow: 0 0 0 9px transparent; } 100% { box-shadow: 0 0 0 12px transparent; } }
@media (prefers-reduced-motion: reduce) { .employee-workstation__signal { animation: none !important; } }
</style>
