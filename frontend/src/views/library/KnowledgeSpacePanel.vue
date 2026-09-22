<template>
  <aside class="space-panel">
    <header>
      <div><h3>知识空间</h3><p>空间 · 目录树</p></div>
      <button v-if="canManage" type="button" aria-label="新建一级目录" @click="beginCreate(null)"><Plus :size="15" /></button>
    </header>

    <nav aria-label="知识空间目录树">
      <button type="button" class="space-all" :class="{ selected: selectedId === null }" @click="emit('select', null)">
        <span><Layers3 :size="16" />全部知识</span><strong>{{ total }}</strong>
      </button>
      <SpaceTreeNode
        v-for="node in spaces"
        :key="node.id"
        :node="node"
        :level="0"
        :selected-id="selectedId"
        :can-manage="canManage"
        :expanded-ids="expandedIds"
        :menu-id="menuId"
        @select="emit('select', $event)"
        @toggle="toggleTree"
        @menu="toggleMenu"
        @create="beginCreate"
        @rename="beginRename"
        @move="openMove"
        @delete="emit('delete', $event)"
      />
    </nav>

    <form v-if="creating !== undefined" class="space-form" @submit.prevent="submitCreate">
      <input v-model.trim="newName" required maxlength="160" :placeholder="creating === null ? '一级目录名称' : '子目录名称'" autofocus />
      <button type="submit" aria-label="保存"><Check :size="14" /></button>
      <button type="button" aria-label="取消" @click="creating = undefined"><X :size="14" /></button>
    </form>

    <form v-if="editingTarget" class="space-form" @submit.prevent="submitRename">
      <input v-model.trim="editName" required maxlength="160" autofocus />
      <button type="submit" aria-label="保存重命名"><Check :size="14" /></button>
      <button type="button" aria-label="取消重命名" @click="editingId = null"><X :size="14" /></button>
    </form>

    <div v-if="moveNode" class="move-backdrop">
      <form class="move-card" @submit.prevent="submitMove">
        <header><div><h3>移动「{{ moveNode.name }}」</h3><p>选择目标目录（保存在同一知识空间内）。</p></div><button type="button" aria-label="关闭" @click="moveNode = null"><X :size="16" /></button></header>
        <label>移动到<select v-model="moveTargetId" required><option value="" disabled>选择目标目录</option><option v-for="item in moveTargets" :key="item.id" :value="item.id">{{ '　'.repeat(item.level) }}{{ item.name }}</option></select></label>
        <footer><button type="button" class="button" @click="moveNode = null">取消</button><button class="button button--primary" type="submit">移动</button></footer>
      </form>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { Check, Layers3, Plus, X } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import type { KnowledgeSpace } from '@/api/types'
import SpaceTreeNode from './SpaceTreeNode.vue'

const props = defineProps<{ spaces: KnowledgeSpace[]; selectedId: string | null; total: number; canManage: boolean }>()
const emit = defineEmits<{
  select: [id: string | null]
  create: [name: string, parentId: string | null]
  rename: [space: KnowledgeSpace, name: string]
  move: [space: KnowledgeSpace, targetParentId: string]
  delete: [space: KnowledgeSpace]
}>()

const expandedIds = ref<Set<string>>(new Set())
const menuId = ref<string | null>(null)
const creating = ref<string | null | undefined>(undefined)
const newName = ref('')
const editingId = ref<string | null>(null)
const editName = ref('')
const moveNode = ref<KnowledgeSpace | null>(null)
const moveTargetId = ref('')

const editingTarget = computed(() => findNode(props.spaces, editingId.value))

function toggleTree(id: string) {
  const value = new Set(expandedIds.value)
  if (value.has(id)) value.delete(id)
  else value.add(id)
  expandedIds.value = value
}
function toggleMenu(id: string) { menuId.value = menuId.value === id ? null : id }
function beginCreate(parentId: string | null) {
  creating.value = parentId
  newName.value = ''
  if (parentId) {
    const value = new Set(expandedIds.value)
    value.add(parentId)
    expandedIds.value = value
  }
}
function submitCreate() {
  if (!newName.value) return
  emit('create', newName.value, creating.value ?? null)
  newName.value = ''
  creating.value = undefined
}
function beginRename(space: KnowledgeSpace) { editingId.value = space.id; editName.value = space.name }
function submitRename() {
  if (!editName.value || !editingTarget.value) return
  emit('rename', editingTarget.value, editName.value)
  editingId.value = null
}
function openMove(space: KnowledgeSpace) { moveNode.value = space; moveTargetId.value = space.parent_id ?? '' }
function submitMove() {
  if (!moveNode.value || !moveTargetId.value) return
  emit('move', moveNode.value, moveTargetId.value)
  moveNode.value = null
}
const moveTargets = computed(() => {
  if (!moveNode.value) return []
  const root = findRoot(props.spaces, moveNode.value.id)
  if (!root || root.id === moveNode.value.id) return []
  const excluded = descendantIds(moveNode.value)
  excluded.add(moveNode.value.id)
  return flatten([root]).filter((item) => !excluded.has(item.id))
})
function descendantIds(node: KnowledgeSpace): Set<string> {
  const result = new Set<string>()
  for (const child of node.children ?? []) { result.add(child.id); for (const id of descendantIds(child)) result.add(id) }
  return result
}
function findNode(nodes: KnowledgeSpace[], id: string | null): KnowledgeSpace | null {
  if (!id) return null
  for (const node of nodes) {
    if (node.id === id) return node
    const found = findNode(node.children ?? [], id)
    if (found) return found
  }
  return null
}
function findRoot(nodes: KnowledgeSpace[], id: string): KnowledgeSpace | null {
  for (const node of nodes) {
    if (node.id === id || findNode(node.children ?? [], id)) return node
  }
  return null
}
function flatten(nodes: KnowledgeSpace[], level = 0): Array<KnowledgeSpace & { level: number }> {
  return nodes.reduce<Array<KnowledgeSpace & { level: number }>>((result, node) => {
    result.push({ ...node, level })
    return result.concat(flatten(node.children ?? [], level + 1))
  }, [])
}
</script>

<style scoped>
.space-panel { align-self: start; min-width: 0; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 12px; background: rgba(255,255,255,.96); box-shadow: var(--astra-shadow-panel); }
.space-panel > header { display: flex; align-items: center; justify-content: space-between; min-height: 68px; padding: 13px 14px; border-bottom: 1px solid var(--astra-border); }
.space-panel h3, .space-panel p { margin: 0; }.space-panel h3 { color: var(--astra-text-primary);  }.space-panel p { margin-top: 3px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.space-panel > header button, .space-form button { display: grid; place-items: center; width: 30px; height: 30px; padding: 0; color: var(--astra-text-muted); border: 1px solid var(--astra-border); border-radius: 7px; background: white; cursor: pointer; }
.space-panel nav { display: grid; gap: 2px; max-height: min(560px, calc(100vh - 380px)); overflow-y: auto; padding: 8px; }
.space-all { display: flex; align-items: center; justify-content: space-between; min-height: 40px; padding: 0 10px; color: var(--astra-text-secondary); border: 0; border-radius: 8px; background: transparent; cursor: pointer; }
.space-all:hover, .space-all.selected { background: #eef8f3; }
.space-all.selected { color: var(--astra-primary-bright); font-weight: var(--astra-weight-bold); }
.space-all span { display: flex; align-items: center; gap: 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.space-all strong { color: var(--astra-text-muted); font-size: var(--astra-font-helper); font-weight: var(--astra-weight-bold); }
.space-form { display: grid; grid-template-columns: minmax(0,1fr) 30px 30px; gap: 4px; padding: 8px; border-top: 1px solid var(--astra-border); }
.space-form input { min-width: 0; height: 32px; padding: 0 8px; color: var(--astra-text-primary); border: 1px solid var(--astra-primary-border); border-radius: 7px; background: white; outline: none; }
.move-backdrop { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; padding: 20px; background: rgba(16,37,34,.38); backdrop-filter: blur(2px); }
.move-card { width: min(420px,100%); padding: 18px; border: 1px solid var(--astra-border); border-radius: 13px; background: white; box-shadow: 0 24px 70px rgba(16,37,34,.22); }
.move-card h3 { margin: 0; color: var(--astra-text-primary);  }
.move-card header p { margin: 4px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.move-card label { display: grid; gap: 6px; margin-top: 14px; color: var(--astra-text-secondary); font-size: var(--astra-font-body); }
.move-card select { min-height: 38px; padding: 0 9px; color: var(--astra-text-primary); border: 1px solid var(--astra-border); border-radius: 8px; background: white; }
.move-card footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
</style>
