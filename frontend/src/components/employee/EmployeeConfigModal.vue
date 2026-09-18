<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" data-testid="employee-config-modal" @click.self="requestClose">
      <section class="modal-card employee-config-modal" role="dialog" aria-modal="true" :aria-label="creating ? '新建数字员工' : `编辑 ${employeeDisplayName(employee?.name)}`">
        <header>
          <div>
            <small>{{ creating ? 'NEW EMPLOYEE' : 'EDIT EMPLOYEE' }}</small>
            <h3>{{ creating ? '新建数字员工' : `编辑 ${employeeDisplayName(employee?.name)}` }}</h3>
          </div>
          <button type="button" aria-label="关闭" @click="requestClose"><X :size="18" /></button>
        </header>

        <div class="modal-body">
          <EmployeeConfig ref="configRef" :employee="employee" :creating="creating" :categories="categories" embedded @saved="onSaved" />
        </div>

        <footer class="employee-config-modal__footer">
          <span v-if="configRef?.dirty" class="employee-config-modal__dirty"><i />有未保存修改</span>
          <button type="button" class="button" :disabled="configRef?.saving" @click="requestClose">取消</button>
          <button type="button" class="button button--primary" :disabled="configRef?.saving || !configRef?.dirty" @click="configRef?.save()">
            <LoaderCircle v-if="configRef?.saving" :size="14" class="spin" />
            {{ configRef?.saving ? '保存中' : creating ? '创建员工' : '保存' }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { LoaderCircle, X } from 'lucide-vue-next'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Employee, TaskCategory } from '@/api/types'
import { employeeDisplayName } from '@/utils/format'
import EmployeeConfig from '@/views/settings/EmployeeConfig.vue'

const props = defineProps<{ open: boolean; employee: Employee | null; creating: boolean; categories: TaskCategory[] }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'saved', id: string): void }>()
const configRef = ref<InstanceType<typeof EmployeeConfig> | null>(null)

function requestClose() {
  if (configRef.value?.getDirty() && !window.confirm('有未保存的员工配置修改，确定放弃并关闭吗？')) return
  emit('close')
}
function onSaved(id: string, environmentOk?: boolean) {
  emit('saved', id)
  // 保存已成功；仅当工作环境检测也通过时才自动关闭，异常时保留弹框以便处理检查项。
  if (environmentOk !== false) emit('close')
}
function handleEscape(event: KeyboardEvent) { if (props.open && event.key === 'Escape') requestClose() }
watch(() => props.open, (value) => document.body.classList.toggle('overlay-open', value), { immediate: true })
onMounted(() => window.addEventListener('keydown', handleEscape))
onBeforeUnmount(() => { document.body.classList.remove('overlay-open'); window.removeEventListener('keydown', handleEscape) })
</script>

<style scoped>
.employee-config-modal { width: min(880px, 100%); }
.employee-config-modal__footer { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }
.employee-config-modal__dirty { display: inline-flex; align-items: center; gap: 7px; margin-right: auto; color: var(--astra-warning); font-size: var(--astra-font-control); font-weight: var(--astra-weight-bold); }
.employee-config-modal__dirty i { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
</style>