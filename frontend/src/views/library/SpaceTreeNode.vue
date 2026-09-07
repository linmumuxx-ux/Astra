<template>
  <div>
    <div class="space-row" :class="{ selected: node.id === selectedId }" :style="{ paddingLeft: `${level * 14 + 8}px` }">
      <button type="button" class="space-main" @click="emit('select', node.id)">
        <span class="space-caret" :class="{ open: expanded }" @click.stop="emit('toggle', node.id)">
          <ChevronRight v-if="children.length" :size="13" />
          <i v-else />
        </span>
        <span class="space-label"><Folder :size="15" /><em :title="node.name">{{ node.name }}</em></span>
        <strong :title="`${node.subtree_knowledge_count} 条`">{{ node.knowledge_count }}</strong>
      </button>
      <div v-if="canManage" class="space-actions" @click.stop>
        <button type="button" aria-label="更多目录操作" @click="emit('menu', node.id)"><MoreHorizontal :size="14" /></button>
      </div>
      <div v-if="menuOpen" class="space-menu" @click.stop>
        <button type="button" @click="pick('create')"><Plus :size="13" />新建子目录</button>
        <button type="button" @click="pick('rename')"><Pencil :size="13" />重命名</button>
        <button v-if="node.parent_id" type="button" @click="pick('move')"><FolderInput :size="13" />移动到…</button>
        <button type="button" class="danger" @click="pick('delete')"><Trash2 :size="13" />删除</button>
      </div>
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
        @select="emit('select', $event)"
        @toggle="emit('toggle', $event)"
        @menu="emit('menu', $event)"
        @create="emit('create', $event)"
        @rename="emit('rename', $event)"
        @move="emit('move', $event)"
        @delete="emit('delete', $event)"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ChevronRight, Folder, FolderInput, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-vue-next'
import { computed } from 'vue'
import type { KnowledgeSpace } from '@/api/types'

defineOptions({ name: 'SpaceTreeNode' })
const props = defineProps<{
  node: KnowledgeSpace
  level: number
  selectedId: string | null
  canManage: boolean
  expandedIds: Set<string>
  menuId: string | null
}>()
const emit = defineEmits<{
  select: [id: string]
  toggle: [id: string]
  menu: [id: string]
  create: [parentId: string]
  rename: [space: KnowledgeSpace]
  move: [space: KnowledgeSpace]
  delete: [space: KnowledgeSpace]
}>()

const children = computed(() => props.node.children ?? [])
const expanded = computed(() => props.expandedIds.has(props.node.id))
const menuOpen = computed(() => props.menuId === props.node.id)
function pick(action: 'create' | 'rename' | 'move' | 'delete') {
  emit('menu', props.node.id)
  if (action === 'create') emit('create', props.node.id)
  else if (action === 'rename') emit('rename', props.node)
  else if (action === 'move') emit('move', props.node)
  else emit('delete', props.node)
}
</script>

<style scoped>
.space-row { position: relative; display: flex; align-items: center; border-radius: 8px; }
.space-main { display: flex; align-items: center; gap: 7px; min-width: 0; flex: 1; min-height: 38px; padding: 0 8px; color: var(--astra-text-secondary); border: 0; border-radius: 8px; background: transparent; cursor: pointer; }
.space-main:hover, .space-row.selected { background: #eef8f3; }
.space-row.selected .space-main { color: var(--astra-primary-bright); font-weight: var(--astra-weight-bold); }
.space-caret { display: grid; place-items: center; flex: none; width: 16px; color: var(--astra-text-muted); }
.space-caret i { display: block; width: 5px; height: 5px; border-radius: 50%; background: var(--astra-border-hover); }
.space-caret svg { transition: transform .16s ease; }
.space-caret.open svg { transform: rotate(90deg); }
.space-label { display: flex; align-items: center; min-width: 0; gap: 7px; overflow: hidden; }
.space-label em { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.space-main strong { color: var(--astra-text-muted); font-size: var(--astra-font-helper); font-weight: var(--astra-weight-bold); }
.space-actions { position: absolute; right: 6px; display: flex; }
.space-actions button { display: grid; place-items: center; width: 26px; height: 26px; padding: 0; color: var(--astra-text-muted); border: 1px solid var(--astra-border); border-radius: 6px; background: var(--astra-bg-panel); cursor: pointer; }
.space-actions button:hover { color: var(--astra-primary-bright); }
.space-menu { position: absolute; right: 6px; top: calc(100% - 2px); z-index: 30; min-width: 140px; padding: 5px; border: 1px solid var(--astra-border); border-radius: 9px; background: var(--astra-bg-panel); box-shadow: var(--astra-shadow-panel); }
.space-menu button { display: flex; align-items: center; gap: 7px; width: 100%; min-height: 32px; padding: 0 9px; color: var(--astra-text-secondary); border: 0; border-radius: 6px; background: transparent; font-size: var(--astra-font-control); cursor: pointer; }
.space-menu button:hover { background: var(--astra-primary-soft); }
.space-menu button.danger { color: var(--astra-danger); }
.space-menu button.danger:hover { background: var(--astra-danger-soft); }
</style>
