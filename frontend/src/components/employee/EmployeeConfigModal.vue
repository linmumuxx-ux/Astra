<template>
  <el-dialog
    :model-value="open"
    :title="creating ? '新建数字员工' : `编辑 ${employeeDisplayName(employee?.name)}`"
    width="min(880px, calc(100vw - 32px))"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="!configRef?.saving"
    :before-close="handleBeforeClose"
    append-to-body
    lock-scroll
    destroy-on-close
    data-testid="employee-config-modal"
    class="employee-config-modal"
  >
    <EmployeeConfig
      ref="configRef"
      :employee="employee"
      :creating="creating"
      :categories="categories"
      embedded
      @saved="onSaved"
    />

    <template #footer>
      <div class="employee-config-modal__footer">
        <span v-if="configRef?.dirty" class="employee-config-modal__dirty"><i />有未保存修改</span>
        <el-button :disabled="configRef?.saving" @click="requestClose">取消</el-button>
        <el-button type="primary" :loading="configRef?.saving" :disabled="configRef?.saving || !configRef?.dirty" @click="configRef?.save()">
          {{ configRef?.saving ? '保存中' : creating ? '创建员工' : '保存' }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { Employee, TaskCategory } from '@/api/types'
import { confirmDialog } from '@/composables/useConfirm'
import { employeeDisplayName } from '@/utils/format'
import EmployeeConfig from '@/views/settings/EmployeeConfig.vue'

const props = defineProps<{ open: boolean; employee: Employee | null; creating: boolean; categories: TaskCategory[] }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved', id: string): void }>()
const configRef = ref<InstanceType<typeof EmployeeConfig> | null>(null)

async function canClose(): Promise<boolean> {
  if (configRef.value?.saving) return false
  if (!configRef.value?.getDirty()) return true
  return confirmDialog({
    title: '放弃未保存的员工配置？',
    message: '当前修改尚未保存，关闭后将无法恢复。',
    confirmLabel: '放弃并关闭',
    danger: true,
  })
}

async function requestClose() {
  if (await canClose()) emit('close')
}

async function handleBeforeClose(done: () => void) {
  if (!(await canClose())) return
  emit('close')
  done()
}

function onSaved(id: string, environmentOk?: boolean) {
  emit('saved', id)
  if (environmentOk !== false) emit('close')
}
</script>

<style scoped>
.employee-config-modal__footer { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }
.employee-config-modal__dirty { display: inline-flex; align-items: center; gap: 7px; margin-right: auto; color: var(--astra-warning); font-size: var(--astra-font-control); font-weight: var(--astra-weight-bold); }
.employee-config-modal__dirty i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
</style>
