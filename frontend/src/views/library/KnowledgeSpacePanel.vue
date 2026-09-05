<template>
  <aside class="space-panel">
    <header>
      <div><h3>知识空间</h3><p>按共享目录浏览</p></div>
      <button v-if="canManage" type="button" aria-label="创建知识空间" @click="creating = !creating"><Plus :size="15" /></button>
    </header>
    <form v-if="creating" class="space-form" @submit.prevent="submitCreate">
      <input v-model.trim="newName" required maxlength="160" placeholder="空间名称" autofocus />
      <button type="submit" aria-label="保存"><Check :size="14" /></button>
      <button type="button" aria-label="取消" @click="creating = false"><X :size="14" /></button>
    </form>
    <nav aria-label="知识空间目录">
      <button type="button" :class="{ selected: selectedId === null }" @click="$emit('select', null)">
        <span><Layers3 :size="16" />全部知识</span><strong>{{ total }}</strong>
      </button>
      <div v-for="space in spaces" :key="space.id" class="space-row" :class="{ selected: selectedId === space.id }">
        <form v-if="editingId === space.id" class="space-form space-form--edit" @submit.prevent="submitRename(space)">
          <input v-model.trim="editName" required maxlength="160" />
          <button type="submit" aria-label="保存重命名"><Check :size="14" /></button>
          <button type="button" aria-label="取消重命名" @click="editingId = null"><X :size="14" /></button>
        </form>
        <template v-else>
          <button type="button" class="space-main" @click="$emit('select', space.id)">
            <span><FolderOpen v-if="selectedId === space.id" :size="16" /><Folder v-else :size="16" />{{ space.name }}</span>
            <strong>{{ space.knowledge_count }}</strong>
          </button>
          <div v-if="canManage && selectedId === space.id" class="space-actions">
            <button type="button" aria-label="重命名知识空间" @click="beginRename(space)"><Pencil :size="13" /></button>
            <button type="button" aria-label="停用知识空间" @click="$emit('toggle', space)"><Power :size="13" /></button>
          </div>
        </template>
      </div>
    </nav>
  </aside>
</template>

<script setup lang="ts">
import { Check, Folder, FolderOpen, Layers3, Pencil, Plus, Power, X } from 'lucide-vue-next'
import { ref } from 'vue'
import type { KnowledgeSpace } from '@/api/types'

defineProps<{ spaces: KnowledgeSpace[]; selectedId: string | null; total: number; canManage: boolean }>()
const emit = defineEmits<{
  select: [id: string | null]
  create: [name: string]
  rename: [space: KnowledgeSpace, name: string]
  toggle: [space: KnowledgeSpace]
}>()
const creating = ref(false)
const newName = ref('')
const editingId = ref<string | null>(null)
const editName = ref('')

function submitCreate() {
  if (!newName.value) return
  emit('create', newName.value)
  newName.value = ''
  creating.value = false
}
function beginRename(space: KnowledgeSpace) {
  editingId.value = space.id
  editName.value = space.name
}
function submitRename(space: KnowledgeSpace) {
  if (!editName.value) return
  emit('rename', space, editName.value)
  editingId.value = null
}
</script>

<style scoped>
.space-panel { align-self: start; min-width: 0; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 12px; background: rgba(255,255,255,.96); box-shadow: var(--astra-shadow-panel); }
.space-panel > header { display: flex; align-items: center; justify-content: space-between; min-height: 68px; padding: 13px 14px; border-bottom: 1px solid var(--astra-border); }
.space-panel h3, .space-panel p { margin: 0; }.space-panel h3 { color: var(--astra-text-primary); font-size: var(--astra-font-section); }.space-panel p { margin-top: 3px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.space-panel header button, .space-actions button, .space-form button { display: grid; place-items: center; width: 30px; height: 30px; padding: 0; color: var(--astra-text-muted); border: 1px solid var(--astra-border); border-radius: 7px; background: white; cursor: pointer; }
.space-panel nav { display: grid; gap: 3px; padding: 8px; }
.space-panel nav > button, .space-main { display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 42px; padding: 0 10px; color: var(--astra-text-secondary); border: 0; border-radius: 8px; background: transparent; cursor: pointer; }
.space-panel nav > button:hover, .space-main:hover, .space-row.selected { background: #eef8f3; }
.space-panel nav > button.selected, .space-row.selected .space-main { color: var(--astra-primary-bright); font-weight: 600; }
.space-panel nav span { display: flex; align-items: center; min-width: 0; gap: 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.space-panel nav strong { color: var(--astra-text-muted); font-size: var(--astra-font-helper); font-weight: 600; }
.space-row { position: relative; display: flex; align-items: center; border-radius: 8px; }.space-row .space-main { min-width: 0; }.space-row.selected .space-main { padding-right: 68px; }
.space-actions { position: absolute; right: 7px; display: flex; gap: 3px; }.space-actions button { width: 27px; height: 27px; border-color: transparent; background: rgba(255,255,255,.7); }
.space-form { display: grid; grid-template-columns: minmax(0,1fr) 30px 30px; gap: 4px; padding: 8px; border-bottom: 1px solid var(--astra-border); }.space-form--edit { width: 100%; padding: 5px; border: 0; }
.space-form input { min-width: 0; height: 32px; padding: 0 8px; color: var(--astra-text-primary); border: 1px solid var(--astra-primary-border); border-radius: 7px; background: white; outline: none; }
</style>
