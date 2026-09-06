<template>
  <AstraPanel title="任务分类" subtitle="分类用于表示任务所属的业务领域">
    <template #action><button class="button button--compact" @click="addRow"><Plus :size="14" /> 新增分类</button></template>
    <div class="config-table-wrap">
      <table class="config-table">
        <thead><tr><th>分类名称</th><th>描述</th><th class="sort-col">排序</th><th>状态</th><th class="type-col">任务 / 问题 Prompt</th><th class="op-col">操作</th></tr></thead>
        <tbody>
          <tr v-for="row in rows" :key="row.key">
            <td><input v-model.trim="row.name" class="config-input" placeholder="分类名称" aria-label="分类名称" /></td>
            <td><input v-model.trim="row.description" class="config-input" placeholder="分类说明" aria-label="分类说明" /></td>
            <td class="sort-col"><input v-model.number="row.sort_order" class="config-number" type="number" min="0" aria-label="排序" /></td>
            <td><AstraSwitch :model-value="row.enabled" @update:model-value="(value) => (row.enabled = value)" /></td>
            <td class="type-col">
              <span class="prompt-chip" :data-set="row.taskPrompt">任务 Prompt：{{ row.taskPrompt ? '已配置' : '未配置' }}</span>
              <span class="prompt-chip" :data-set="row.questionPrompt">问题 Prompt：{{ row.questionPrompt ? '已配置' : '未配置' }}</span>
            </td>
            <td class="op-col">
              <button v-if="row.persisted === undefined" type="button" class="icon-button icon-button--mini" title="移除新增行" @click="rows.splice(rowIndex(row), 1)"><Trash2 :size="13" /></button>
            </td>
          </tr>
          <tr v-if="!rows.length"><td colspan="6"><div class="table-empty">暂无任务分类，点击右上角新增。</div></td></tr>
        </tbody>
      </table>
    </div>

    <footer class="config-foot"><StickyActionBar v-if="dirty" :dirty="dirty" :saving="saving" save-label="保存分类" @save="save" @cancel="reset" /></footer>
    <div v-if="message" class="form-message" :data-error="messageIsError">{{ message }}</div>
  </AstraPanel>
</template>

<script setup lang="ts">
import { Plus, Trash2 } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import type { TaskCategory } from '@/api/types'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraSwitch from '@/components/astra/AstraSwitch.vue'
import StickyActionBar from '@/components/astra/StickyActionBar.vue'
import { useAstraStore } from '@/stores/astra'
import { safeUUID } from '@/utils/format'

const store = useAstraStore()
interface Row { key: string; id: string | null; name: string; description: string; sort_order: number; enabled: boolean; taskPrompt: string | null; questionPrompt: string | null; persisted?: boolean; promptEditorOpen: boolean }
const rows = ref<Row[]>([])
const original = ref('')
const saving = ref(false)
const message = ref('')
const messageIsError = ref(false)

function toRows(categories: TaskCategory[]) {
  return categories.map((category) => ({ key: category.id, id: category.id, name: category.name, description: category.description, sort_order: category.sort_order, enabled: category.enabled, taskPrompt: null, questionPrompt: null, persisted: true, promptEditorOpen: false }))
}
function addRow() {
  const key = safeUUID()
  rows.value.push({ key, id: null, name: '', description: '', sort_order: (rows.value.at(-1)?.sort_order ?? 0) + 10, enabled: true, taskPrompt: null, questionPrompt: null, persisted: undefined, promptEditorOpen: false })
}
function rowIndex(row: Row) { return rows.value.indexOf(row) }
function syncSnapshot() { original.value = JSON.stringify(rows.value.map((row) => ({ name: row.name, description: row.description, sort_order: row.sort_order, enabled: row.enabled }))) }
const dirty = computed(() => JSON.stringify(rows.value.map((row) => ({ name: row.name, description: row.description, sort_order: row.sort_order, enabled: row.enabled }))) !== original.value)

async function load() {
  const categories = await api.categories(true)
  rows.value = toRows(categories)
  await store.refresh()
  syncSnapshot()
}
async function save() {
  saving.value = true; message.value = ''; messageIsError.value = false
  try {
    for (const row of rows.value) {
      if (!row.name.trim()) throw new Error('分类名称不能为空')
      const body = { name: row.name.trim(), description: row.description.trim(), enabled: row.enabled, sort_order: row.sort_order }
      if (row.persisted) await api.updateCategory(row.id as string, body)
      else await api.createCategory(body)
      row.persisted = true
    }
    await load()
    message.value = '任务分类已保存。'
  } catch (error) { messageIsError.value = true; message.value = error instanceof Error ? error.message : '保存失败' } finally { saving.value = false }
}
function reset() { load() }

defineExpose({ load })
</script>

<style scoped>
.config-table-wrap { overflow-x: auto; }
.config-table { min-width: 860px; }
.config-table td { border-top: 1px solid var(--astra-border); }
.sort-col { width: 110px; text-align: center; }
.type-col { min-width: 320px; }
.op-col { width: 84px; }
.config-input, .config-number { width: 100%; min-height: 36px; padding: 7px 10px; color: var(--astra-text-primary); border: 1px solid var(--astra-border); border-radius: 7px; outline: none; background: var(--astra-bg-base); }
.config-input:focus, .config-number:focus { border-color: var(--astra-primary-border); }
.config-number { width: 70px; text-align: center; }
.prompt-chip { display: inline-flex; align-items: center; margin-right: 8px; padding: 2px 8px; color: var(--astra-text-muted); border-radius: 6px; background: rgba(101, 121, 145, 0.09); font-size: var(--astra-font-helper); }
.prompt-chip[data-set='true'] { color: var(--astra-success); background: var(--astra-success-soft); }
.icon-button--mini { width: 28px; height: 28px; margin-left: 5px; border-radius: 7px; }
.op-col { white-space: nowrap; }
.table-empty { padding: 28px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); text-align: center; }
.config-foot { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--astra-border); }
.config-foot > span { display: inline-flex; align-items: center; gap: 7px; color: var(--astra-warning); font-size: var(--astra-font-helper); font-weight: 600; }
.config-foot > span i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.prompt-editor { position: relative; margin-top: 14px; padding: 14px; border: 1px solid var(--astra-primary-border); border-radius: 10px; background: var(--astra-primary-soft); }
.prompt-editor h3 { margin: 0 0 10px; font: 700 var(--astra-font-label) var(--astra-font-display); }
.prompt-editor label { display: grid; gap: 6px; margin-bottom: 10px; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.prompt-editor textarea { width: 100%; padding: 9px 11px; border: 1px solid var(--astra-border); border-radius: 8px; outline: none; background: var(--astra-bg-panel); resize: vertical; }
.prompt-editor__close { position: absolute; top: 12px; right: 12px; display: grid; place-items: center; width: 28px; height: 28px; color: var(--astra-text-muted); border: 0; border-radius: 7px; background: transparent; cursor: pointer; }
</style>
