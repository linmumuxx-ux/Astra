<template>
  <AstraPanel title="任务分类" subtitle="分类用于表示任务所属的业务领域">
    <template #action><el-button type="primary" size="small" :disabled="loading || saving" @click="addRow"><Plus :size="14" /> 新增分类</el-button></template>
    <div class="config-table-wrap">
      <table class="config-table" :aria-busy="loading || saving">
        <thead><tr><th>分类名称</th><th>描述</th><th class="sort-col">排序</th><th>状态</th><th class="type-col">任务 / 问题 Prompt</th><th class="op-col">操作</th></tr></thead>
        <tbody>
          <template v-for="row in rows" :key="row.key">
          <tr :data-category-id="row.id">
            <td><el-input v-model="row.name" :disabled="loading || saving" size="small" placeholder="分类名称" aria-label="分类名称" /></td>
            <td><el-input v-model="row.description" :disabled="loading || saving" size="small" placeholder="分类说明" aria-label="分类说明" /></td>
            <td class="sort-col"><el-input-number v-model="row.sort_order" :disabled="loading || saving" :min="0" :step="10" controls-position="right" size="small" aria-label="排序" /></td>
            <td><el-switch :disabled="loading || saving" active-text="启用" inactive-text="停用" :model-value="row.enabled" @update:model-value="(value) => (row.enabled = value)" /></td>
            <td class="type-col">
              <span class="prompt-chip" :data-set="Boolean(row.task_prompt.trim())">任务 Prompt：{{ row.task_prompt.trim() ? '已配置' : '未配置' }}</span>
              <span class="prompt-chip" :data-set="Boolean(row.question_prompt.trim())">问题 Prompt：{{ row.question_prompt.trim() ? '已配置' : '未配置' }}</span>
            </td>
            <td class="op-col">
              <el-button size="small" :disabled="loading || saving" :aria-expanded="row.promptEditorOpen" :aria-controls="`category-prompts-${row.key}`" @click="row.promptEditorOpen = !row.promptEditorOpen">{{ row.promptEditorOpen ? '收起' : '编辑' }}</el-button>
              <el-button v-if="!row.id" :disabled="saving" type="danger" text circle size="small" title="移除新增行" @click="rows.splice(rowIndex(row), 1)"><Trash2 :size="13" /></el-button>
            </td>
          </tr>
          <tr v-if="row.promptEditorOpen">
            <td colspan="6">
              <section :id="`category-prompts-${row.key}`" class="prompt-editor" :aria-label="`${row.name || '新分类'}提示词编辑`">
                <h3>{{ row.name || '新分类' }} · 提示词</h3>
                <FormField label="任务提示词" v-slot="{ id }"><el-input :id="id" v-model="row.task_prompt" :disabled="saving" type="textarea" :rows="6" resize="vertical" /></FormField>
                <FormField label="问题提示词" v-slot="{ id }"><el-input :id="id" v-model="row.question_prompt" :disabled="saving" type="textarea" :rows="6" resize="vertical" /></FormField>
              </section>
            </td>
          </tr>
          </template>
          <tr v-if="loading"><td colspan="6"><div class="table-empty">正在加载任务分类…</div></td></tr>
          <tr v-else-if="!rows.length && loaded"><td colspan="6"><div class="table-empty">暂无任务分类，点击右上角新增。</div></td></tr>
        </tbody>
      </table>
    </div>

    <footer class="config-foot"><StickyActionBar v-if="dirty" :dirty="dirty" :saving="saving" :disabled="loading || saving" save-label="保存分类" @save="save" @cancel="reset" /></footer>
    <el-button v-if="!loaded && !loading" @click="load">重新加载</el-button>
    <div v-if="message" role="status" class="form-message" :data-error="messageIsError">{{ message }}</div>
  </AstraPanel>
</template>

<script setup lang="ts">
import { Plus, Trash2 } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import type { TaskCategory, TaskCategoryWrite } from '@/api/types'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import StickyActionBar from '@/components/astra/StickyActionBar.vue'
import FormField from '@/components/forms/FormField.vue'
import { useAstraStore } from '@/stores/astra'
import { safeUUID } from '@/utils/format'

const store = useAstraStore()
interface Row {
  key: string
  id: string | null
  name: string
  description: string
  sort_order: number
  enabled: boolean
  task_prompt: string
  question_prompt: string
  promptEditorOpen: boolean
}
const rows = ref<Row[]>([])
const original = ref<Record<string, string>>({})
const loaded = ref(false)
const loading = ref(true)
const saving = ref(false)
const message = ref('')
const messageIsError = ref(false)

function toRow(category: TaskCategory, key = category.id): Row {
  return { key, id: category.id, name: category.name, description: category.description ?? '', sort_order: Number(category.sort_order ?? 0), enabled: category.enabled, task_prompt: category.task_prompt ?? '', question_prompt: category.question_prompt ?? '', promptEditorOpen: false }
}
function payload(row: Row): TaskCategoryWrite {
  return { name: row.name.trim(), description: row.description.trim(), sort_order: Number(row.sort_order), enabled: row.enabled, task_prompt: row.task_prompt, question_prompt: row.question_prompt }
}
// Only persisted business fields count as edits; expanding the editor does not.
function snapshot(row: Row) { return JSON.stringify({ ...payload(row), sort_order: row.sort_order }) }
const dirty = computed(() => loaded.value && (rows.value.length !== Object.keys(original.value).length || rows.value.some(row => snapshot(row) !== original.value[row.key])))
function addRow() {
  rows.value.push({ key: safeUUID(), id: null, name: '', description: '', sort_order: Number(rows.value.at(-1)?.sort_order ?? 0) + 10, enabled: true, task_prompt: '', question_prompt: '', promptEditorOpen: false })
}
function rowIndex(row: Row) { return rows.value.indexOf(row) }
async function load() {
  loading.value = true; message.value = ''; messageIsError.value = false
  try {
    const nextRows = (await api.categories(true)).map(category => toRow(category))
    // Commit normalized values and their baseline together, with no async gap.
    rows.value = nextRows
    original.value = Object.fromEntries(nextRows.map(row => [row.key, snapshot(row)]))
    loaded.value = true
  } catch (error) {
    messageIsError.value = true
    message.value = error instanceof Error ? error.message : '任务分类加载失败'
  } finally { loading.value = false }
}
async function save() {
  if (saving.value || loading.value || !dirty.value) return
  saving.value = true; message.value = ''; messageIsError.value = false
  try {
    for (const row of rows.value) {
      if (!row.name.trim()) throw new Error('分类名称不能为空')
      if (!Number.isInteger(row.sort_order) || Number(row.sort_order) < 0) throw new Error('排序必须为非负整数')
    }
    for (const row of rows.value) {
      if (snapshot(row) === original.value[row.key]) continue
      const saved = row.id ? await api.updateCategory(row.id, payload(row)) : await api.createCategory(payload(row))
      // Retain successful IDs/baselines if a later row fails; retry cannot duplicate a create.
      Object.assign(row, toRow(saved, row.key), { promptEditorOpen: row.promptEditorOpen })
      original.value[row.key] = snapshot(row)
    }
    await store.refresh()
    message.value = '任务分类已保存。'
  } catch (error) { messageIsError.value = true; message.value = error instanceof Error ? error.message : '保存失败' } finally { saving.value = false }
}
function reset() { void load() }
onMounted(load)
defineExpose({ getDirty: () => dirty.value })
</script>

<style scoped>
.config-table-wrap { overflow-x: auto; }
.config-table { min-width: 860px; }
.config-table td { border-top: 1px solid var(--astra-border); }
.sort-col { width: 110px; text-align: center; }
.type-col { min-width: 320px; }
.op-col { width: 84px; }
.prompt-chip { display: inline-flex; align-items: center; margin-right: 8px; padding: 2px 8px; color: var(--astra-text-muted); border-radius: 6px; background: rgba(101, 121, 145, 0.09); font-size: var(--astra-font-helper); }
.prompt-chip[data-set='true'] { color: var(--astra-success); background: var(--astra-success-soft); }
.op-col { white-space: nowrap; }
.table-empty { padding: 28px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); text-align: center; }
.config-foot { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--astra-border); }
.config-foot > span { display: inline-flex; align-items: center; gap: 7px; color: var(--astra-warning); font-size: var(--astra-font-helper); font-weight: var(--astra-weight-bold); }
.config-foot > span i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.prompt-editor { position: relative; margin-top: 14px; padding: 14px; border: 1px solid var(--astra-primary-border); border-radius: 10px; background: var(--astra-primary-soft); }
.prompt-editor h3 { margin: 0 0 10px; font: var(--astra-weight-bold) var(--astra-font-label) var(--astra-font-display); }
.prompt-editor label { display: grid; gap: 6px; margin-bottom: 10px; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
</style>
