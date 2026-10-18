<template>
  <div class="row-menu" @click.stop>
    <ElButton v-if="primary" link type="primary" :disabled="disabled" @click="emit('primary')">{{ primary }}</ElButton>
    <ElDropdown v-if="items.length" trigger="click" :disabled="disabled" @command="onCommand">
      <ElButton link type="primary" :disabled="disabled">更多</ElButton>
      <template #dropdown>
        <ElDropdownMenu>
          <ElDropdownItem v-for="item in items" :key="item.command" :command="item.command" :disabled="item.disabled">
            {{ item.label }}
          </ElDropdownItem>
        </ElDropdownMenu>
      </template>
    </ElDropdown>
  </div>
</template>

<script setup lang="ts">
import { ElButton, ElDropdown, ElDropdownItem, ElDropdownMenu } from 'element-plus'

export interface RowMenuItem {
  command: string
  label: string
  disabled?: boolean
}

defineProps<{
  primary?: string
  items: RowMenuItem[]
  disabled?: boolean
}>()

const emit = defineEmits<{ primary: []; command: [command: string] }>()

function onCommand(command: string | number) {
  emit('command', String(command))
}
</script>

<style scoped>
.row-menu { display: inline-flex; align-items: center; gap: 2px; white-space: nowrap; }
</style>
