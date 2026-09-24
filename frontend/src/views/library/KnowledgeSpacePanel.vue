<template>
  <aside class="space-panel">
    <header class="space-panel__header">
      <div><h3>知识空间</h3><p>选择空间或目录查看知识</p></div>
      <el-button v-if="canManage" text circle title="新建知识空间" aria-label="新建知识空间" @click="beginCreate(null)"><Plus :size="15" /></el-button>
    </header>

    <el-input v-model="searchQuery" class="space-search" clearable placeholder="搜索知识空间" aria-label="搜索知识空间">
      <template #prefix><Search :size="14" /></template>
    </el-input>

    <nav aria-label="知识空间目录树">
      <button
        type="button"
        class="space-all"
        :class="{ selected: selectedId === null }"
        :title="`当前身份可见的全部知识 ${total} 条（含未归入目录的知识）`"
        @click="select(null)"
      >
        <span><Layers3 :size="16" />全部知识</span><strong>{{ total }}</strong>
      </button>

      <form v-if="creating === null" class="root-inline-create" @submit.prevent="submitRootCreate">
        <FolderPlus :size="15" />
        <el-input
          ref="rootCreateInput"
          v-model="rootName"
          required
          maxlength="160"
          placeholder="输入知识空间名称"
          aria-label="知识空间名称"
          @keydown.esc.prevent="cancelCreate"
        />
        <el-button native-type="submit" text circle aria-label="创建知识空间"><Check :size="13" /></el-button>
        <el-button text circle aria-label="取消创建" @click="cancelCreate"><X :size="13" /></el-button>
      </form>

      <SpaceTreeNode
        v-for="node in visibleSpaces"
        :key="node.id"
        :node="node"
        :level="0"
        :selected-id="selectedId"
        :can-manage="canManage"
        :expanded-ids="expandedIds"
        :menu-id="menuId"
        :creating-parent-id="creating"
        :editing-id="editingId"
        :force-expanded="Boolean(searchQuery)"
        @select="select"
        @toggle="toggleTree"
        @menu="toggleMenu"
        @create="beginCreate"
        @rename="beginRename"
        @move="openMove"
        @delete="emit('delete', $event)"
        @commit-create="submitCreate"
        @cancel-create="cancelCreate"
        @commit-rename="submitRename"
        @cancel-rename="cancelRename"
      />

      <div v-if="searchQuery && !visibleSpaces.length" class="space-empty">没有匹配的知识空间</div>
    </nav>

    <DirectoryPickerDialog
      :open="Boolean(moveNode)"
      title="移动目录"
      :subtitle="moveNode ? `将「${moveNode.name}」移动到新的父目录。` : ''"
      :spaces="moveRoot ? [moveRoot] : []"
      :selected-id="moveNode?.parent_id ?? ''"
      :exclude-ids="moveExcludedIds"
      confirm-label="移动"
      @close="moveNode = null"
      @confirm="submitMove"
    />
  </aside>
</template>

<script setup lang="ts">
import { Check, FolderPlus, Layers3, Plus, Search } from 'lucide-vue-next'
import type { InputInstance } from 'element-plus'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { KnowledgeSpace } from '@/api/types'
import DirectoryPickerDialog from './DirectoryPickerDialog.vue'
import SpaceTreeNode from './SpaceTreeNode.vue'

const props = defineProps<{ spaces: KnowledgeSpace[]; selectedId: string | null; total: number; canManage: boolean }>()
const emit = defineEmits<{
  select: [id: string | null]
  create: [name: string, parentId: string | null, done: (success: boolean) => void]
  rename: [space: KnowledgeSpace, name: string, done: (success: boolean) => void]
  move: [space: KnowledgeSpace, targetParentId: string]
  delete: [space: KnowledgeSpace]
}>()

const expandedIds = ref<Set<string>>(new Set())
const menuId = ref<string | null>(null)
const creating = ref<string | null | undefined>(undefined)
const rootName = ref('')
const rootCreateInput = ref<InputInstance | null>(null)
const editingId = ref<string | null>(null)
const moveNode = ref<KnowledgeSpace | null>(null)
const searchQuery = ref('')

const visibleSpaces = computed(() => {
  const keyword = searchQuery.value.trim().toLocaleLowerCase()
  if (!keyword) return props.spaces

  const filter = (nodes: KnowledgeSpace[]): KnowledgeSpace[] => {
    const result: KnowledgeSpace[] = []
    for (const node of nodes) {
      const children = filter(node.children ?? [])
      if (node.name.toLocaleLowerCase().includes(keyword) || children.length) result.push({ ...node, children })
    }
    return result
  }
  return filter(props.spaces)
})
const moveRoot = computed(() => moveNode.value ? findRoot(props.spaces, moveNode.value.id) : null)
const moveExcludedIds = computed(() => {
  if (!moveNode.value) return []
  return [...descendantIds(moveNode.value), moveNode.value.id]
})

function closeMenu() { menuId.value = null }
onMounted(() => document.addEventListener('click', closeMenu))
onBeforeUnmount(() => document.removeEventListener('click', closeMenu))

function select(id: string | null) {
  menuId.value = null
  emit('select', id)
}
function toggleTree(id: string) {
  const value = new Set(expandedIds.value)
  if (value.has(id)) value.delete(id)
  else value.add(id)
  expandedIds.value = value
}
function toggleMenu(id: string) { menuId.value = menuId.value === id ? null : id }
async function beginCreate(parentId: string | null) {
  creating.value = parentId
  editingId.value = null
  menuId.value = null
  if (parentId) {
    const value = new Set(expandedIds.value)
    value.add(parentId)
    expandedIds.value = value
    return
  }
  rootName.value = ''
  await nextTick()
  rootCreateInput.value?.focus()
}
function cancelCreate() { creating.value = undefined; rootName.value = '' }
function submitRootCreate() {
  const name = rootName.value.trim()
  if (!name) return
  emit('create', name, null, async (success) => {
    if (success) cancelCreate()
    else {
      await nextTick()
      rootCreateInput.value?.focus()
    }
  })
}
function submitCreate(name: string, parentId: string) {
  if (!name) return
  emit('create', name, parentId, (success) => {
    if (success) creating.value = undefined
  })
}
function beginRename(space: KnowledgeSpace) {
  creating.value = undefined
  menuId.value = null
  editingId.value = space.id
}
function cancelRename() { editingId.value = null }
function submitRename(space: KnowledgeSpace, name: string) {
  emit('rename', space, name, (success) => {
    if (success) editingId.value = null
  })
}
function openMove(space: KnowledgeSpace) {
  creating.value = undefined
  editingId.value = null
  menuId.value = null
  moveNode.value = space
}
function submitMove(targetId: string) {
  if (!moveNode.value) return
  if (targetId === moveNode.value.parent_id) {
    moveNode.value = null
    return
  }
  emit('move', moveNode.value, targetId)
  moveNode.value = null
}
function descendantIds(node: KnowledgeSpace): Set<string> {
  const result = new Set<string>()
  for (const child of node.children ?? []) {
    result.add(child.id)
    for (const id of descendantIds(child)) result.add(id)
  }
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
</script>

<style scoped>
.space-panel{display:grid;grid-template-rows:auto auto minmax(0,1fr);min-width:0;height:100%;overflow:hidden;border-right:1px solid var(--astra-border);background:#fbfdfc}.space-panel__header{display:flex;align-items:center;justify-content:space-between;min-height:64px;padding:12px 14px 10px}.space-panel h3,.space-panel p{margin:0}.space-panel h3{color:var(--astra-text-primary)}.space-panel p{margin-top:3px;color:var(--astra-text-muted);font-size:var(--astra-font-helper)}.space-panel__header>button{display:grid;place-items:center;width:30px;height:30px;padding:0;color:var(--astra-primary-bright);border:1px solid var(--astra-primary-border);border-radius:7px;background:#fff;cursor:pointer}.space-panel__header>button:hover{background:var(--astra-primary-soft)}.space-search{display:flex;align-items:center;gap:7px;height:34px;margin:0 10px 8px;padding:0 8px;color:var(--astra-text-muted);border:1px solid var(--astra-border);border-radius:8px;background:#fff}.space-search:focus-within{border-color:var(--astra-primary-border);box-shadow:0 0 0 3px var(--astra-primary-soft)}.space-search input{min-width:0;flex:1;border:0;outline:0;background:transparent;color:var(--astra-text-primary);font-size:var(--astra-font-control)}.space-search button{display:grid;place-items:center;padding:0;color:var(--astra-text-muted);border:0;background:transparent;cursor:pointer}.space-panel nav{display:block;min-height:0;overflow:auto;padding:3px 8px 10px}.space-all{display:flex;align-items:center;justify-content:space-between;width:100%;min-height:40px;padding:0 10px;color:var(--astra-text-secondary);border:0;border-radius:8px;background:transparent;cursor:pointer}.space-all:hover{background:#f3f8f5}.space-all.selected{color:var(--astra-primary-bright);background:var(--astra-primary-soft);box-shadow:inset 3px 0 0 var(--astra-primary);font-weight:var(--astra-weight-bold)}.space-all span{display:flex;align-items:center;gap:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.space-all strong{color:var(--astra-text-muted);font-size:var(--astra-font-helper);font-weight:var(--astra-weight-bold)}.root-inline-create{display:flex;align-items:center;gap:6px;min-height:38px;margin:2px 4px;padding:0 4px 0 9px;color:var(--astra-primary-bright);border-radius:8px;background:var(--astra-primary-soft)}.root-inline-create input{min-width:0;flex:1;height:30px;padding:0 8px;color:var(--astra-text-primary);border:1px solid var(--astra-primary-border);border-radius:6px;background:#fff;outline:0}.root-inline-create button{display:grid;place-items:center;flex:none;width:27px;height:27px;padding:0;color:var(--astra-text-muted);border:1px solid var(--astra-border);border-radius:6px;background:#fff;cursor:pointer}.root-inline-create button[type='submit']{color:var(--astra-primary-bright)}.space-empty{display:grid;place-items:center;min-height:100px;color:var(--astra-text-muted);font-size:var(--astra-font-body)}
</style>
