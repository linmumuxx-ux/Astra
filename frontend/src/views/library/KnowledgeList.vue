<template>
  <section class="knowledge-list">
    <header class="knowledge-list__header">
      <div>
        <h3>知识列表</h3>
        <p>{{ page.total }} 条知识<span v-if="spaceName"> · {{ spaceName }}</span></p>
      </div>
      <div class="list-filters">
        <select :value="filters.type" aria-label="知识类型" @change="change('type', $event)">
          <option value="">全部类型</option><option v-for="item in types" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <select :value="filters.status" aria-label="知识状态" @change="change('status', $event)">
          <option value="">全部状态</option><option value="published">已发布</option><option v-if="canReview" value="candidate">候选经验</option><option v-if="canManage || canReview" value="draft">草稿</option><option v-if="canManage" value="archived">已归档</option><option v-if="canReview" value="rejected">已驳回</option>
        </select>
        <select :value="filters.source" aria-label="知识来源" @change="change('source', $event)">
          <option value="">全部来源</option><option v-for="item in sources" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <select :value="filters.tag" aria-label="知识标签" @change="change('tag', $event)">
          <option value="">全部标签</option><option v-for="tag in tagOptions" :key="tag" :value="tag">{{ tag }}</option>
        </select>
        <select :value="filters.sort" aria-label="知识排序" @change="change('sort', $event)">
          <option value="updated_desc">最近更新</option><option value="updated_asc">最早更新</option><option value="references_desc">引用最多</option><option value="title_asc">标题排序</option>
        </select>
      </div>
    </header>

    <div v-if="filterLabel" class="active-filter"><span>{{ filterLabel }}<button type="button" aria-label="清除当前筛选" @click="emit('clear-filter')"><X :size="12" /></button></span></div>

    <div v-if="selected.size" class="batch-bar">
      <span>已选 {{ selected.size }} 条</span>
      <button v-if="canManage" type="button" class="button" @click="emitBatch('move')">移动</button>
      <button v-if="canManage" type="button" class="button" @click="emitBatch('archive')">归档</button>
      <button v-if="canReview" type="button" class="button" @click="emitBatch('publish')">发布</button>
      <button v-if="canManage" type="button" class="button button--danger" @click="emitBatch('delete')">删除</button>
      <button type="button" class="button button--ghost" @click="selected = new Set()">取消选择</button>
    </div>

    <div class="knowledge-table-wrap" :class="{ loading }">
      <table>
        <thead>
          <tr>
            <th v-if="canManage || canReview" class="check-col"><input type="checkbox" :checked="allSelected" aria-label="全选" @change="toggleAll" /></th>
            <th>标题 / 标签</th><th>来源</th><th>状态</th><th>更新时间</th><th class="num-col">引用</th><th aria-label="操作" />
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in page.items" :key="item.id" tabindex="0" @click="emit('open', item.id)" @keydown.enter="emit('open', item.id)">
            <td v-if="canManage || canReview" class="check-col" @click.stop><input type="checkbox" :checked="selected.has(item.id)" :aria-label="`选择 ${item.title}`" @change="toggle(item.id)" /></td>
            <td>
              <div class="knowledge-title">
                <span :data-status="item.status"><BookMarked :size="16" /></span>
                <div><strong :title="item.title">{{ item.title }}</strong><small class="tag-row" :title="item.tags.join('、') || (item.summary || item.id)">{{ item.tags.length ? item.tags.slice(0, 3).map((t) => '#' + t).join(' ') : (item.summary || item.id) }}</small></div>
              </div>
            </td>
            <td><span class="source-chip">{{ sourceLabel(item.source_type, item.source_task_id) }}</span></td>
            <td><span class="status-chip" :data-status="item.status">{{ statusLabel(item.status) }}</span></td>
            <td>{{ formatDate(item.updated_at) }}</td>
            <td class="num-col"><span class="reference-count"><Quote :size="13" />{{ item.reference_count }}</span></td>
            <td @click.stop>
              <div class="menu-wrap">
                <button type="button" aria-label="知识操作" @click="toggleMenu(item.id)"><MoreHorizontal :size="16" /></button>
                <div v-if="menuId === item.id" class="row-menu">
                  <button type="button" @click="emit('open', item.id)">查看</button>
                  <button v-if="canManage" type="button" @click.stop="pick(item, 'move')">移动</button>
                  <button v-if="canReview && ['candidate', 'draft'].includes(item.status)" type="button" @click.stop="pick(item, 'publish')">发布</button>
                  <button v-if="canManage && item.status !== 'archived'" type="button" @click.stop="pick(item, 'archive')">归档</button>
                  <button v-if="canManage" type="button" class="danger" @click.stop="pick(item, 'delete')">删除</button>
                </div>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="loading" class="list-loading"><LoaderCircle :size="22" class="spin" />正在加载知识</div>
      <div v-else-if="!page.items.length" class="empty-list"><Library :size="30" /><strong>暂无匹配知识</strong><p>调整知识空间、状态、来源或搜索条件后重试。</p></div>
    </div>

    <footer v-if="page.total > 0">
      <span>第 {{ page.page }} / {{ page.pages }} 页</span>
      <div><button type="button" :disabled="page.page <= 1" @click="emit('page', page.page - 1)"><ChevronLeft :size="15" />上一页</button><button type="button" :disabled="page.page >= page.pages" @click="emit('page', page.page + 1)">下一页<ChevronRight :size="15" /></button></div>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { BookMarked, ChevronLeft, ChevronRight, Library, LoaderCircle, MoreHorizontal, Quote, X } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import type { KnowledgeListItem, KnowledgePage, KnowledgeStatus, KnowledgeType } from '@/api/types'

interface ListFilters { type: string; status: string; source: string; tag: string; sort: string }
const props = defineProps<{ page: KnowledgePage; filters: ListFilters; loading: boolean; canManage: boolean; canReview: boolean; spaceName: string | null; filterLabel: string }>()
const emit = defineEmits<{
  open: [id: string]
  move: [item: KnowledgeListItem]
  publish: [item: KnowledgeListItem]
  archive: [item: KnowledgeListItem]
  delete: [item: KnowledgeListItem]
  batch: [ids: string[], action: 'move' | 'archive' | 'publish' | 'delete']
  page: [page: number]
  filter: [key: keyof ListFilters, value: string]
  'clear-filter': []
}>()

const types = [
  { value: 'document', label: '文档' }, { value: 'rule', label: '规范' }, { value: 'guide', label: '指南' },
  { value: 'experience', label: '经验' }, { value: 'faq', label: 'FAQ' }, { value: 'tool', label: '工具' }, { value: 'example', label: '示例' },
]
const sources = [
  { value: 'manual', label: '人工创建' }, { value: 'task', label: '任务沉淀' }, { value: 'import', label: '文档导入' }, { value: 'system', label: '系统同步' },
]
const selected = ref<Set<string>>(new Set())
const menuId = ref<string | null>(null)
const allTags = computed(() => { const set = new Set<string>(); props.page.items.forEach((item) => item.tags.forEach((tag) => set.add(tag))); return [...set] })
const tagOptions = computed(() => allTags.value.slice(0, 24))
const allSelected = computed(() => props.page.items.length > 0 && props.page.items.every((item) => selected.value.has(item.id)))

function change(key: keyof ListFilters, event: Event) { emit('filter', key, (event.target as HTMLSelectElement).value) }
function toggle(id: string) { const value = new Set(selected.value); if (value.has(id)) value.delete(id); else value.add(id); selected.value = value }
function toggleAll() { if (allSelected.value) selected.value = new Set(); else selected.value = new Set(props.page.items.map((item) => item.id)) }
function toggleMenu(id: string) { menuId.value = menuId.value === id ? null : id }
function emitBatch(action: 'move' | 'archive' | 'publish' | 'delete') { const ids = [...selected.value]; selected.value = new Set(); emit('batch', ids, action) }
function pick(item: KnowledgeListItem, action: 'move' | 'publish' | 'archive' | 'delete') { menuId.value = null; if (action === 'move') emit('move', item); else if (action === 'publish') emit('publish', item); else if (action === 'archive') emit('archive', item); else emit('delete', item) }
const typeLabel = (value: KnowledgeType) => types.find((item) => item.value === value)?.label ?? value
const statusLabel = (value: KnowledgeStatus) => ({ published: '已发布', candidate: '待审核', draft: '草稿', archived: '已归档', rejected: '已驳回' }[value])
const sourceLabel = (value: string | null, taskId: string | null) => {
  if (value === 'task' || taskId) return '任务沉淀'
  if (value === 'manual') return '人工创建'
  if (value === 'import') return '文档导入'
  if (value === 'system') return '系统同步'
  return '人工创建'
}
const formatDate = (value: string) => new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
</script>

<style scoped>
.knowledge-list { min-width: 0; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 12px; background: rgba(255,255,255,.96); box-shadow: var(--astra-shadow-panel); }
.knowledge-list__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 68px; padding: 11px 15px; border-bottom: 1px solid var(--astra-border); }.knowledge-list h3,.knowledge-list p { margin: 0; }.knowledge-list h3 { color: var(--astra-text-primary);  }.knowledge-list p { margin-top: 3px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.list-filters { display: flex; gap: 7px; flex-wrap: wrap; }.list-filters select { min-height: 35px; padding: 0 28px 0 9px; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 8px; background: white; }
.active-filter { padding: 8px 14px 0; }.active-filter > span { display: inline-flex; align-items: center; gap: 5px; padding: 5px 8px; color: #9b6428; border: 1px solid rgba(233,149,63,.28); border-radius: 7px; background: var(--astra-warning-soft); font-size: var(--astra-font-helper); }.active-filter button { display: grid; place-items: center; padding: 0; color: inherit; border: 0; background: transparent; cursor: pointer; }
.batch-bar { display: flex; align-items: center; gap: 8px; padding: 8px 14px; border-bottom: 1px solid var(--astra-border); background: #f6faf8; }.batch-bar > span { margin-right: auto; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }.batch-bar .button { min-height: 30px; padding: 0 11px; font-size: var(--astra-font-helper); }
.knowledge-table-wrap { position: relative; min-height: 310px; overflow-x: auto; }.knowledge-table-wrap.loading table { opacity: .45; }.knowledge-table-wrap table { width: 100%; min-width: 900px; border-collapse: collapse; }.knowledge-table-wrap th { height: 41px; padding: 0 12px; text-align: left; font-size: var(--astra-font-control); font-weight: var(--astra-weight-bold); }.knowledge-table-wrap td { height: 62px; padding: 8px 12px; border-top: 1px solid var(--astra-border); font-size: var(--astra-font-body); }.knowledge-table-wrap tbody tr { cursor: pointer; outline: none; }.knowledge-table-wrap tbody tr:focus, .knowledge-table-wrap tbody tr:hover { background: #f2faf6; }
.check-col { width: 36px; }.check-col input { width: 15px; height: 15px; accent-color: var(--astra-primary); }.num-col { text-align: right; }
.knowledge-title { display: flex; align-items: center; gap: 10px; min-width: 240px; }.knowledge-title > span { display: grid; place-items: center; flex: none; width: 32px; height: 32px; color: var(--astra-primary-bright); border-radius: 8px; background: var(--astra-primary-soft); }.knowledge-title > span[data-status='candidate'] { color: var(--astra-warning); background: var(--astra-warning-soft); }.knowledge-title > div { display: grid; min-width: 0; }.knowledge-title strong,.knowledge-title small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.knowledge-title strong { color: var(--astra-text-primary); font-size: var(--astra-font-emphasis); }.knowledge-title small { max-width: 320px; margin-top: 3px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.source-chip,.type-chip,.status-chip { display: inline-flex; padding: 4px 7px; border-radius: 6px; background: #edf3f0; font-size: var(--astra-font-helper); white-space: nowrap; }.status-chip[data-status='published'] { color: var(--astra-primary-bright); background: var(--astra-primary-soft); }.status-chip[data-status='candidate'] { color: #a46726; background: var(--astra-warning-soft); }.status-chip[data-status='rejected'] { color: var(--astra-danger); background: var(--astra-danger-soft); }.reference-count { display: inline-flex; align-items: center; gap: 5px; }
.menu-wrap { position: relative; display: inline-block; }.menu-wrap > button { display: grid; place-items: center; width: 30px; height: 30px; color: var(--astra-text-muted); border: 0; border-radius: 7px; background: transparent; cursor: pointer; }.menu-wrap > button:hover { background: var(--astra-primary-soft); }
.row-menu { position: absolute; right: 0; top: calc(100% + 4px); z-index: 30; min-width: 128px; padding: 5px; border: 1px solid var(--astra-border); border-radius: 9px; background: var(--astra-bg-panel); box-shadow: var(--astra-shadow-panel); }.row-menu button { display: block; width: 100%; min-height: 31px; padding: 0 9px; color: var(--astra-text-secondary); border: 0; border-radius: 6px; background: transparent; font-size: var(--astra-font-control); text-align: left; cursor: pointer; }.row-menu button:hover { background: var(--astra-primary-soft); }.row-menu button.danger { color: var(--astra-danger); }
.list-loading,.empty-list { position: absolute; inset: 42px 0 0; display: grid; place-content: center; justify-items: center; gap: 7px; color: var(--astra-text-muted); background: rgba(255,255,255,.78); }.empty-list strong { color: var(--astra-text-secondary); }.empty-list p { margin: 0; }
.knowledge-list > footer { display: flex; align-items: center; justify-content: space-between; min-height: 52px; padding: 8px 14px; border-top: 1px solid var(--astra-border); color: var(--astra-text-muted); font-size: var(--astra-font-helper); }.knowledge-list > footer div { display: flex; gap: 6px; }.knowledge-list > footer button { display: inline-flex; align-items: center; gap: 4px; min-height: 32px; padding: 0 9px; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 7px; background: white; cursor: pointer; }.knowledge-list > footer button:disabled { cursor: default; opacity: .45; }
@media (max-width: 1000px) { .knowledge-list__header { align-items: flex-start; flex-direction: column; }.list-filters { width: 100%; flex-wrap: wrap; }.list-filters select { flex: 1; min-width: 120px; } }
</style>
