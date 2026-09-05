<template>
  <span
    class="employee-avatar-image"
    :class="`employee-avatar-image--${size}`"
    :data-status="employee.status"
    :style="avatarStyle"
    aria-hidden="true"
  ><span class="employee-avatar-image__sprite" /></span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Employee } from '@/api/types'
import { employeeCharacterStyle } from '@/features/workspace/characterAssets'

const props = withDefaults(defineProps<{
  employee: Pick<Employee, 'id' | 'status'>
  characterIndex?: number
  size?: 'small' | 'medium' | 'large'
}>(), { characterIndex: undefined, size: 'medium' })
const avatarStyle = computed(() => employeeCharacterStyle(props.employee.id, 'standing', props.characterIndex))
</script>

<style scoped>
.employee-avatar-image { position: relative; display: inline-block; flex: none; width: 42px; height: 42px; overflow: hidden; border: 1px solid rgba(183,213,200,.8); border-radius: 14px; background: linear-gradient(145deg,#e8f5ef,#cfe9de); box-shadow: 0 6px 16px rgba(35,76,59,.10); }
.employee-avatar-image--small { width: 34px; height: 34px; border-radius: 11px; }
.employee-avatar-image--large { width: 72px; height: 72px; border-radius: 22px; }
.employee-avatar-image__sprite { position: absolute; bottom: -54%; left: 50%; display: block; width: 145%; aspect-ratio: .8; background-image: var(--character-atlas); background-repeat: no-repeat; background-position: var(--sprite-x) var(--sprite-y); background-size: 400% 300%; filter: drop-shadow(0 3px 3px rgba(32,71,56,.18)); transform: translateX(-50%); }
.employee-avatar-image[data-status='OFFLINE'] .employee-avatar-image__sprite { filter: grayscale(.75); opacity: .62; }
</style>
