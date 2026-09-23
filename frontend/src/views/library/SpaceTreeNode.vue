<template>
  <div class="tree-node">
    <div
      class="space-row"
      :class="{ selected: node.id === selectedId, operating: menuOpen || editing }"
      :style="{ paddingLeft: `${level * 18 + 8}px` }"
    >
      <template v-if="editing">
        <span class="space-caret placeholder"><i /></span>
        <Folder :size="15" class="edit-folder" />
        <form class="inline-edit" @submit.prevent="submitRename">
          <input
            ref="renameInput"
            v-model.trim="renameName"
            required
            maxlength="160"
            aria-label="目录名称"
            @keydown.esc.prevent="emit('cancel-rename')"
          />
          <button type="submit" aria-label="保存重命名"><Check :size="13" /></button>
          <button type="button" aria-label="取消重命名" @click="emit('cancel-rename')"><X :size="13" /></button>
        </form>
      </template>

      <template v-else>
        <button type="button" class="space-main" @click="emit('select', node.id)">
          <span class="space-caret" :class="{ open: expanded }" @click.stop="children.length && emit('toggle', node.id)">
            <ChevronRight v-if="children.length" :size="13" />
            <i v-else />
          </span>
          <span class="space-label"><Folder :size="15" /><em :title="node.name">{{ node.name }}</em></span>
          <strong :title="`${node.subtree_knowledge_count} 条知识（含子目录）`">{{ node.knowledge_count }}</strong>
        </button>
        <div v-if="canManage" class="space-actions" @click.stop>
          <button type="button" :aria-label="`管理目录 ${node.name}`" @click="emit('menu', node.id)"><MoreHorizontal :size="14" /></button>
        </div>
        <div v-if="menuOpen" class="space-menu" @click.stop>
          <button type="button" @click="pick('create')"><Plus :size="13" />新建子目录</button>
          <button type="button" @click="pick('rename')"><Pencil :size="13" />重命名</button>
          <button v-if="node.parent_id" type="button" @click="pick('move')"><FolderInput :size="13" />移动到…</button>
          <span class="menu-separator" />
          <button type="button" class="danger" @click="pick('delete')"><Trash2 :size="13" />删除</button>
        </div>
      </template>
    </div>

    <template v-if="expanded">
      <SpaceTreeNode
        v-for="child in children"
        :key="child.id"
        :node="child"
        :level="level + 1"
        :selected-id="selectedId"
        :can-manage="canManage"
        :expanded-ids="expandedIds"
        :menu-id="menuId"
        :creating-parent-id="creatingParentId"
        :editing-id="editingId"
        :force-expanded="forceExpanded"
        @select="emit('select', $event)"
        @toggle="emit('toggle', $event)"
        @menu="emit('menu', $event)"
        @create="emit('create', $event)"
        @rename="emit('rename', $event)"
        @move="emit('move', $event)"
        @delete="emit('delete', $event)"
        @commit-create="emit('commit-create', $event[0], $event[1])"
        @cancel-create="emit('cancel-create')"
        @commit-rename="emit('commit-rename', $event[0], $event[1])"
        @cancel-rename="emit('cancel-rename')"
      />

      <form
        v-if="creatingHere"
        class="inline-create"
        :style="{ marginLeft: `${(level + 1) * 18 + 8}px` }"
        @submit.prevent="submitCreate"
      >
        <span class="space-caret placeholder"><i /></span>
        <FolderPlus :size="15" />
        <input
          ref="createInput"
          v-model.trim="createName"
          required
          maxlength="160"
          placeholder="输入子目录名称"
          aria-label="子目录名称"
          @keydown.esc.prevent="emit('cancel-create')"
        />
        <button type="submit" aria-label="创建子目录"><Check :size="13" /></button>
        <button type="button" aria-label="取消创建" @click="emit('cancel-create')"><X :size="13" /></button>
      </form>
    </template>
  </div>
</template>

<script setup lang="ts">
import { Check, ChevronRight, Folder, FolderInput, FolderPlus, MoreHorizontal, Pencil, Plus, Trash2, X } from 'lucide-vue-next'
import { computed, nextTick, ref, watch } from 'vue'
import type { KnowledgeSpace } from '@/api/types'

defineOptions({ name: 'SpaceTreeNode' })
const props = defineProps<{
  node: KnowledgeSpace
  level: number
  selectedId: string | null
  canManage: boolean
  expandedIds: Set<string>
  menuId: string | null
  creatingParentId: string | null | undefined
  editingId: string | null
  forceExpanded?: boolean
}>()
const emit = defineEmits<{
  select: [id: string]
  toggle: [id: string]
  menu: [id: string]
  create: [parentId: string]
  rename: [space: KnowledgeSpace]
  move: [space: KnowledgeSpace]
  delete: [space: KnowledgeSpace]
  'commit-create': [name: string, parentId: string]
  'cancel-create': []
  'commit-rename': [space: KnowledgeSpace, name: string]
  'cancel-rename': []
}>()

const createInput = ref<HTMLInputElement | null>(null)
const renameInput = ref<HTMLInputElement | null>(null)
const createName = ref('')
const renameName = ref('')
const children = computed(() => props.node.children ?? [])
const expanded = computed(() => Boolean(props.forceExpanded) || props.expandedIds.has(props.node.id) || props.creatingParentId === props.node.id)
const menuOpen = computed(() => props.menuId === props.node.id)
const creatingHere = computed(() => props.creatingParentId === props.node.id)
const editing = computed(() => props.editingId === props.node.id)

watch(creatingHere, async (active) => {
  if (!active) return
  createName.value = ''
  await nextTick()
  createInput.value?.focus()
})
watch(editing, async (active) => {
  if (!active) return
  renameName.value = props.node.name
  await nextTick()
  renameInput.value?.focus()
  renameInput.value?.select()
})

function pick(action: 'create' | 'rename' | 'move' | 'delete') {
  emit('menu', props.node.id)
  if (action === 'create') emit('create', props.node.id)
  else if (action === 'rename') emit('rename', props.node)
  else if (action === 'move') emit('move', props.node)
  else emit('delete', props.node)
}
function submitCreate() {
  if (!createName.value) return
  emit('commit-create', createName.value, props.node.id)
}
function submitRename() {
  if (!renameName.value || renameName.value === props.node.name) {
    emit('cancel-rename')
    return
  }
  emit('commit-rename', props.node, renameName.value)
}
</script>

<style scoped>
.tree-node{min-width:0}.space-row{position:relative;display:flex;align-items:center;min-height:38px;border-radius:8px}.space-row:hover{background:#f3f8f5}.space-row.selected{background:var(--astra-primary-soft);box-shadow:inset 3px 0 0 var(--astra-primary)}.space-row.operating{background:#eef8f3}.space-main{display:flex;align-items:center;gap:7px;min-width:0;flex:1;min-height:38px;padding:0 34px 0 0;color:var(--astra-text-secondary);border:0;border-radius:8px;background:transparent;cursor:pointer;text-align:left}.space-row.selected .space-main{color:var(--astra-primary-bright);font-weight:var(--astra-weight-bold)}.space-caret{display:grid;place-items:center;flex:none;width:16px;color:var(--astra-text-muted)}.space-caret.placeholder{width:16px}.space-caret i{display:block;width:5px;height:5px;border-radius:50%;background:var(--astra-border-hover)}.space-caret svg{transition:transform .14s ease}.space-caret.open svg{transform:rotate(90deg)}.space-label{display:flex;align-items:center;min-width:0;gap:7px;overflow:hidden}.space-label em{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-style:normal}.space-main strong{margin-left:auto;flex:none;color:var(--astra-text-muted);font-size:var(--astra-font-helper);font-weight:var(--astra-weight-bold)}.space-actions{position:absolute;right:5px;display:flex}.space-actions button{display:grid;place-items:center;width:27px;height:27px;padding:0;color:var(--astra-text-muted);border:0;border-radius:6px;background:transparent;cursor:pointer}.space-row:hover .space-actions button,.space-row.operating .space-actions button{background:#fff;box-shadow:0 0 0 1px var(--astra-border)}.space-actions button:hover{color:var(--astra-primary-bright)}.space-menu{position:absolute;right:5px;top:calc(100% + 2px);z-index:40;min-width:150px;padding:5px;border:1px solid var(--astra-border);border-radius:9px;background:var(--astra-bg-panel);box-shadow:0 12px 30px rgba(16,37,34,.14)}.space-menu button{display:flex;align-items:center;gap:7px;width:100%;min-height:32px;padding:0 9px;color:var(--astra-text-secondary);border:0;border-radius:6px;background:transparent;font-size:var(--astra-font-control);cursor:pointer}.space-menu button:hover{background:var(--astra-primary-soft)}.space-menu button.danger{color:var(--astra-danger)}.space-menu button.danger:hover{background:var(--astra-danger-soft)}.menu-separator{display:block;height:1px;margin:4px;background:var(--astra-border)}.inline-create,.inline-edit{display:flex;align-items:center;gap:6px;min-width:0}.inline-create{min-height:38px;margin-right:6px;padding-right:2px;color:var(--astra-primary-bright)}.edit-folder{flex:none;color:var(--astra-primary-bright)}.inline-edit{flex:1;margin-right:5px}.inline-create input,.inline-edit input{min-width:0;flex:1;height:30px;padding:0 8px;color:var(--astra-text-primary);border:1px solid var(--astra-primary-border);border-radius:6px;background:#fff;outline:0;box-shadow:0 0 0 3px var(--astra-primary-soft)}.inline-create button,.inline-edit button{display:grid;place-items:center;flex:none;width:27px;height:27px;padding:0;color:var(--astra-text-muted);border:1px solid var(--astra-border);border-radius:6px;background:#fff;cursor:pointer}.inline-create button[type='submit'],.inline-edit button[type='submit']{color:var(--astra-primary-bright)}
</style>
