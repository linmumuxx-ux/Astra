<template>
  <AstraDialog
    v-if="open"
    :open="true"
    :title="title"
    :subtitle="subtitle"
    :dismissible="false"
    :busy="busy"
    testid="directory-picker-dialog"
    card-class="directory-picker-card"
    width="min(520px, 100%)"
    @close="emit('close')"
  >
    <div class="directory-picker">
      <label class="directory-search">
        <Search :size="15" />
        <input v-model.trim="query" type="search" placeholder="搜索知识空间或目录" aria-label="搜索目录" />
        <button v-if="query" type="button" aria-label="清空目录搜索" @click="query = ''"><X :size="13" /></button>
      </label>

      <div class="directory-tree" role="radiogroup" aria-label="目标目录">
        <button
          v-for="item in visibleItems"
          :key="item.id"
          type="button"
          class="directory-option"
          :class="{ selected: localSelected === item.id, disabled: excluded.has(item.id) }"
          :disabled="excluded.has(item.id)"
          :style="{ paddingLeft: `${14 + item.level * 22}px` }"
          role="radio"
          :aria-checked="localSelected === item.id"
          @click="localSelected = item.id"
        >
          <span class="radio-mark"><i /></span>
          <Folder :size="15" />
          <span class="directory-copy">
            <strong :title="item.name">{{ item.name }}</strong>
            <small v-if="query">{{ item.path }}</small>
          </span>
          <span class="directory-count">{{ item.knowledge_count }}</span>
        </button>
        <div v-if="!visibleItems.length" class="directory-empty">没有匹配的目录</div>
      </div>
    </div>

    <template #footer>
      <button type="button" class="button" :disabled="busy" @click="emit('close')">取消</button>
      <button
        type="button"
        class="button button--primary"
        :disabled="busy || !localSelected || excluded.has(localSelected)"
        @click="confirm"
      >
        <LoaderCircle v-if="busy" :size="14" class="spin" />{{ confirmLabel }}
      </button>
    </template>
  </AstraDialog>
</template>

<script setup lang="ts">
import { Folder, LoaderCircle, Search, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import type { KnowledgeSpace } from '@/api/types'
import AstraDialog from '@/components/astra/AstraDialog.vue'

interface FlatDirectory extends KnowledgeSpace {
  level: number
  path: string
}

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  subtitle?: string
  spaces: KnowledgeSpace[]
  selectedId?: string
  excludeIds?: string[]
  confirmLabel?: string
  busy?: boolean
}>(), {
  subtitle: '',
  selectedId: '',
  excludeIds: () => [],
  confirmLabel: '确定',
  busy: false,
})

const emit = defineEmits<{ close: []; confirm: [id: string] }>()
const query = ref('')
const localSelected = ref('')

const excluded = computed(() => new Set(props.excludeIds))
const flatItems = computed<FlatDirectory[]>(() => {
  const result: FlatDirectory[] = []
  const walk = (nodes: KnowledgeSpace[], level = 0, parents: string[] = []) => {
    for (const node of nodes) {
      const path = [...parents, node.name]
      result.push({ ...node, level, path: path.join(' / ') })
      walk(node.children ?? [], level + 1, path)
    }
  }
  walk(props.spaces)
  return result
})
const visibleItems = computed(() => {
  const keyword = query.value.toLocaleLowerCase()
  if (!keyword) return flatItems.value
  return flatItems.value.filter((item) => item.name.toLocaleLowerCase().includes(keyword) || item.path.toLocaleLowerCase().includes(keyword))
})

watch(() => props.open, (open) => {
  if (!open) return
  query.value = ''
  localSelected.value = props.selectedId && !excluded.value.has(props.selectedId) ? props.selectedId : ''
}, { immediate: true })

function confirm() {
  if (!localSelected.value || excluded.value.has(localSelected.value)) return
  emit('confirm', localSelected.value)
}
</script>

<style scoped>
.directory-picker{display:grid;gap:12px}.directory-search{display:flex;align-items:center;gap:8px;min-height:38px;padding:0 10px;color:var(--astra-text-muted);border:1px solid var(--astra-border);border-radius:9px;background:#fff}.directory-search:focus-within{border-color:var(--astra-primary-border);box-shadow:0 0 0 3px var(--astra-primary-soft)}.directory-search input{min-width:0;flex:1;border:0;outline:0;background:transparent;color:var(--astra-text-primary)}.directory-search button{display:grid;place-items:center;padding:0;color:var(--astra-text-muted);border:0;background:transparent;cursor:pointer}.directory-tree{max-height:min(430px,55vh);overflow:auto;padding:5px;border:1px solid var(--astra-border);border-radius:10px;background:#fbfdfc}.directory-option{display:flex;align-items:center;gap:8px;width:100%;min-height:42px;padding-right:10px;color:var(--astra-text-secondary);border:0;border-radius:8px;background:transparent;text-align:left;cursor:pointer}.directory-option:hover:not(:disabled){background:#f1f8f4}.directory-option.selected{color:var(--astra-primary-bright);background:var(--astra-primary-soft);font-weight:var(--astra-weight-bold)}.directory-option.disabled{cursor:not-allowed;opacity:.4}.radio-mark{display:grid;place-items:center;flex:none;width:16px;height:16px;border:1px solid var(--astra-border-hover);border-radius:50%;background:#fff}.directory-option.selected .radio-mark{border-color:var(--astra-primary)}.directory-option.selected .radio-mark i{width:8px;height:8px;border-radius:50%;background:var(--astra-primary)}.directory-copy{display:grid;min-width:0;flex:1}.directory-copy strong,.directory-copy small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.directory-copy strong{font-size:var(--astra-font-body);font-weight:inherit}.directory-copy small{margin-top:2px;color:var(--astra-text-muted);font-size:var(--astra-font-micro);font-weight:var(--astra-weight-normal)}.directory-count{flex:none;color:var(--astra-text-muted);font-size:var(--astra-font-helper)}.directory-empty{display:grid;place-items:center;min-height:120px;color:var(--astra-text-muted);font-size:var(--astra-font-body)}
</style>
