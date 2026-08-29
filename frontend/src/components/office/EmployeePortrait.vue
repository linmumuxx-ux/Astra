<template>
  <span
    class="employee-portrait"
    :data-status="status"
    :data-variant="variant"
    :style="portraitStyle"
    aria-hidden="true"
  >
    <svg viewBox="0 0 96 96" role="presentation">
      <defs>
        <linearGradient :id="`portrait-bg-${safeId}`" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" :stop-color="palette.background" />
          <stop offset="1" stop-color="#e8f6ef" />
        </linearGradient>
        <linearGradient :id="`portrait-jacket-${safeId}`" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" :stop-color="palette.accent" />
          <stop offset="1" stop-color="#f6fbf8" />
        </linearGradient>
      </defs>

      <rect width="96" height="96" rx="25" :fill="`url(#portrait-bg-${safeId})`" />
      <circle cx="77" cy="19" r="15" :fill="palette.accent" opacity=".12" />
      <path d="M17 96c2-20 13-31 31-31s29 11 31 31" :fill="`url(#portrait-jacket-${safeId})`" />
      <path d="M38 63h20v17H38z" :fill="palette.skinShadow" />
      <path d="M29 34c0-16 8-25 20-25 13 0 21 10 21 26v11c0 15-9 25-21 25S29 61 29 46z" :fill="palette.skin" />
      <path v-if="variant === 0" d="M28 39C25 19 35 7 50 7c13 0 21 9 21 25-8-1-15-5-20-11-5 8-12 14-23 18z" :fill="palette.hair" />
      <path v-else-if="variant === 1" d="M28 35C29 16 37 7 51 7c12 0 20 9 20 24-8-8-17-11-29-9-3 7-8 11-14 13z" :fill="palette.hair" />
      <path v-else d="M27 36C27 17 36 7 50 7c15 0 23 11 21 29l-6-8-8 3-8-10-8 9-8-3z" :fill="palette.hair" />
      <path d="M34 44h10M54 44h10" :stroke="palette.hair" stroke-width="2" stroke-linecap="round" opacity=".7" />
      <circle cx="39" cy="49" r="2.2" fill="#102036" />
      <circle cx="59" cy="49" r="2.2" fill="#102036" />
      <path d="M48 50l-2 8h5" fill="none" :stroke="palette.skinShadow" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      <path d="M42 62c4 3 9 3 14 0" fill="none" stroke="#934d5a" stroke-width="2" stroke-linecap="round" />
      <path d="M27 47c0-8 3-15 8-20M71 47c0-8-3-15-8-20" fill="none" :stroke="palette.accentSoft" stroke-width="2.5" stroke-linecap="round" />
      <rect x="24" y="45" width="5" height="12" rx="2.5" :fill="palette.accent" />
      <rect x="69" y="45" width="5" height="12" rx="2.5" :fill="palette.accent" />
      <path d="M72 55c0 7-4 10-10 10" fill="none" :stroke="palette.accent" stroke-width="2" stroke-linecap="round" />
      <circle cx="61" cy="65" r="2.4" :fill="palette.accentSoft" />
      <path d="M62 56h5M64.5 53.5v5" :stroke="palette.accent" stroke-width="1.3" stroke-linecap="round" opacity=".8" />
      <path d="M41 78l7 7 8-7 4 18H36z" fill="#d9e8fb" opacity=".9" />
      <path d="M48 85v11" :stroke="palette.accent" stroke-width="2" />
    </svg>
    <i class="employee-portrait__presence" />
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ employeeId: string; status: string }>()

const palettes = [
  { accent: '#18b875', accentSoft: '#70dbaa', background: '#dff6ea', skin: '#dca77f', skinShadow: '#b97862', hair: '#233432' },
  { accent: '#22aa82', accentSoft: '#8ae8d4', background: '#ddf5ef', skin: '#bf8768', skinShadow: '#975f50', hair: '#1b3130' },
  { accent: '#3d8ff0', accentSoft: '#a8cdf9', background: '#e5f1fb', skin: '#efc3a0', skinShadow: '#c98d79', hair: '#2c3040' },
  { accent: '#18b875', accentSoft: '#96e5bf', background: '#e8f7ef', skin: '#9f654d', skinShadow: '#754337', hair: '#252b2a' },
]

const hash = computed(() => [...props.employeeId].reduce((total, character) => total + character.charCodeAt(0), 0))
const variant = computed(() => hash.value % 3)
const palette = computed(() => palettes[hash.value % palettes.length])
const safeId = computed(() => props.employeeId.replace(/[^a-zA-Z0-9_-]/g, '-'))
const portraitStyle = computed(() => ({ '--portrait-accent': palette.value.accent }))
</script>

<style scoped>
.employee-portrait { position: relative; display: block; flex: none; width: 72px; height: 72px; border: 1px solid color-mix(in srgb, var(--portrait-accent) 32%, transparent); border-radius: 20px 12px 20px 12px; background: #edf8f3; box-shadow: 0 10px 24px rgba(35,76,59,.12); }
.employee-portrait svg { display: block; width: 100%; height: 100%; border-radius: inherit; }
.employee-portrait__presence { position: absolute; right: -3px; bottom: -3px; width: 14px; height: 14px; border: 3px solid #fff; border-radius: 50%; background: #7b8da3; box-shadow: 0 0 10px rgba(123,141,163,.25); }
.employee-portrait[data-status='IDLE'] .employee-portrait__presence { background: var(--astra-success); box-shadow: 0 0 11px rgba(50, 214, 155, .55); }
.employee-portrait[data-status='WORKING'] .employee-portrait__presence { background: var(--astra-primary-bright); box-shadow: 0 0 12px rgba(91, 140, 255, .65); animation: portrait-presence 1.6s ease-in-out infinite; }
.employee-portrait[data-status='WAIT_HUMAN'] .employee-portrait__presence { background: var(--astra-warning); box-shadow: 0 0 12px rgba(255, 173, 91, .6); }
.employee-portrait[data-status='ERROR'] .employee-portrait__presence { background: var(--astra-danger); box-shadow: 0 0 12px rgba(255, 111, 125, .6); }
.employee-portrait[data-status='PAUSED'] .employee-portrait__presence { background: #9a80d9; }
@keyframes portrait-presence { 50% { transform: scale(.78); opacity: .66; } }
</style>
