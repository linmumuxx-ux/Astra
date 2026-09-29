<template>
  <section class="knowledge-list">
    <header class="knowledge-list__header">
      <div class="list-context">
        <h3 :title="spacePath">{{ spacePath }}</h3>
        <p>{{ page.total }} 条知识</p>
      </div>
    </header>

    <div class="knowledge-list__filters" aria-label="知识筛选">
      <ElSelect
        class="knowledge-filter__type"
        :model-value="filters.type"
        aria-label="知识类型"
        placeholder="类型：全部"
        clearable
        @update:model-value="applyFilter('type', $event)"
      >
        <ElOption v-for="item in types" :key="item.value" :value="item.value" :label="item.label" />
      </ElSelect>
      <ElSelect
        class="knowledge-filter__status"
        :model-value="filters.status"
        aria-label="知识状态"
        placeholder="状态：全部"
        clearable
        @update:model-value="applyFilter('status', $event)"
      >
        <ElOption v-for="item in statusOptions" :key="item.value" :value="item.value" :label="item.label" />
      </ElSelect>
      <ElSelect
        class="knowledge-filter__sort"
        :model-value="filters.sort"
        aria-label="知识排序"
        @update:model-value="applyFilter('sort', $event)"
      >
        <ElOption value="updated_desc" label="最近更新" />
        <ElOption value="updated_asc" label="最早更新" />
        <ElOption value="references_desc" label="引用最多" />
        <ElOption value="title_asc" label="标题排序" />
      </ElSelect>
      <ElInput
        v-model="keywordDraft"
        class="knowledge-filter__search"
        aria-label="搜索当前空间"
        placeholder="搜索当前空间"
        clearable
        @keydown.enter.prevent="runSearch"
        @clear="runSearch"
      >
        <template #prefix><Search :size="15" /></template>
      </ElInput>
      <ElSpace :size="8">
        <ElButton type="primary" plain :icon="Search" @click="runSearch">搜索</ElButton>
        <ElButton class="knowledge-filter__more" :class="{ 'is-active': moreOpen || Boolean(filters.source || filters.tag) }" :icon="SlidersHorizontal" @click="moreOpen = !moreOpen">更多筛选</ElButton>
      </ElSpace>
    </div>

    <div v-if="moreOpen" class="knowledge-list__more">
      <ElSelect
        class="knowledge-filter__source"
        :model-value="filters.source"
        aria-label="知识来源"
        placeholder="来源：全部"
        clearable
        @update:model-value="applyFilter('source', $event)"
      >
        <ElOption v-for="item in sources" :key="item.value" :value="item.value" :label="item.label" />
      </ElSelect>
      <div class="knowledge-filter__tag">
        <ElInput v-model="tagInput" list="knowledge-tag-options" aria-label="知识标签" placeholder="标签：全部" clearable @keydown.enter.prevent="applyTag" />
        <datalist id="knowledge-tag-options"><option v-for="tag in tagOptions" :key="tag" :value="tag" /></datalist>
        <ElButton aria-label="应用标签筛选" @click="applyTag">应用</ElButton>
      </div>
      <ElButton v-if="hasFilters" text type="primary" @click="emit('clear-filter')">清除筛选</ElButton>
    </div>

    <div v-if="filterLabel" class="knowledge-list__active">
      <ElTag closable type="warning" @close="emit('clear-filter')">{{ filterLabel }}</ElTag>
    </div>

    <div v-if="selectedRows.length" class="knowledge-list__batch" aria-label="批量操作">
      <ElText>已选 {{ selectedRows.length }} 条</ElText>
      <ElSpace :size="8">
        <ElButton v-if="canManage" @click="emitBatch('move')">移动</ElButton>
        <ElButton v-if="canManage" @click="emitBatch('archive')">归档</ElButton>
        <ElButton v-if="canReview" @click="emitBatch('publish')">发布</ElButton>
        <ElButton v-if="canManage" type="danger" @click="emitBatch('delete')">删除</ElButton>
        <ElButton text @click="clearSelection">取消选择</ElButton>
      </ElSpace>
    </div>

    <div class="knowledge-table-wrap">
      <ElTable
        ref="tableRef"
        v-loading="loading"
        class="knowledge-table"
        element-loading-text="正在加载知识"
        :data="page.items"
        height="100%"
        row-key="id"
        @row-click="onRowClick"
        @selection-change="onSelectionChange"
      >
        <ElTableColumn v-if="canManage || canReview" type="selection" width="46" :reserve-selection="true" />
        <ElTableColumn label="标题" min-width="280">
          <template #default="{ row }">
            <div class="knowledge-cell">
              <strong :title="row.title">{{ row.title }}</strong>
              <ElText type="info" truncated>{{ metaText(row) }}</ElText>
              <ElText v-if="tagText(row)" type="info" truncated>{{ tagText(row) }}</ElText>
            </div>
          </template>
        </ElTableColumn>
        <ElTableColumn label="类型" width="80">
          <template #default="{ row }">{{ typeLabel(row.type) }}</template>
        </ElTableColumn>
        <ElTableColumn label="所属目录" width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.space_name ?? '未归类' }}</template>
        </ElTableColumn>
        <ElTableColumn label="审核状态" width="112">
          <template #default="{ row }"><ElTag :type="statusTag(row.status)">{{ statusLabel(row.status) }}</ElTag></template>
        </ElTableColumn>
        <ElTableColumn label="验证状态" width="104">
          <template #default="{ row }"><ElTag :type="verificationTag(row.verification_status)" effect="plain">{{ verificationLabel(row.verification_status) }}</ElTag></template>
        </ElTableColumn>
        <ElTableColumn label="更新时间" width="132">
          <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="232" fixed="right">
          <template #default="{ row }">
            <ElSpace class="row-actions" :size="4" @click.stop>
              <ElTooltip content="查看" placement="top">
                <ElButton circle type="primary" :icon="Eye" :aria-label="`查看 ${row.title}`" @click="openRow(row)" />
              </ElTooltip>
              <ElTooltip v-if="canManage" content="编辑" placement="top">
                <ElButton circle type="primary" :icon="Pencil" :aria-label="`编辑 ${row.title}`" @click="editRow(row)" />
              </ElTooltip>
              <ElTooltip v-if="canManage" content="移动到其他目录" placement="top">
                <ElButton circle type="primary" :icon="FolderInput" :aria-label="`移动 ${row.title}`" @click="moveRow(row)" />
              </ElTooltip>
              <ElTooltip v-if="canReview && (row.status === 'candidate' || row.status === 'draft')" content="在详情中审核发布" placement="top">
                <ElButton circle type="warning" :icon="Stamp" :aria-label="`审核发布 ${row.title}`" @click="publishRow(row)" />
              </ElTooltip>
              <ElTooltip v-if="canManage && row.status !== 'archived'" content="归档" placement="top">
                <ElButton circle type="primary" :icon="Archive" :aria-label="`归档 ${row.title}`" @click="archiveRow(row)" />
              </ElTooltip>
              <ElTooltip v-if="canManage" content="删除" placement="top">
                <ElButton circle type="danger" :icon="Trash2" :aria-label="`删除 ${row.title}`" @click="deleteRow(row)" />
              </ElTooltip>
            </ElSpace>
          </template>
        </ElTableColumn>
        <template #empty>
          <ElEmpty v-if="!loading" :image-size="72" :description="hasFilters ? '没有匹配的知识' : '这里还没有知识'">
            <ElText type="info">{{ hasFilters ? '调整搜索或筛选条件后重试。' : `当前位置：${spacePath}。你可以新建知识，或将已有知识移动到这里。` }}</ElText>
            <div class="empty-actions">
              <ElButton v-if="!hasFilters && canManage" type="primary" :icon="Plus" @click="emit('create')">新建知识</ElButton>
              <ElButton v-else-if="hasFilters" @click="emit('clear-filter')">清除筛选</ElButton>
            </div>
          </ElEmpty>
        </template>
      </ElTable>
    </div>

    <footer v-if="page.total > 0" class="knowledge-list__footer">
      <ElText type="info">共 {{ page.total }} 条</ElText>
      <ElPagination
        :current-page="page.page"
        :page-size="page.page_size"
        :total="page.total"
        layout="prev, pager, next"
        aria-label="知识列表分页"
        @current-change="emit('page', $event)"
      />
    </footer>
  </section>
</template>

<script setup lang="ts">
import { Archive, Eye, FolderInput, Pencil, Plus, Search, SlidersHorizontal, Stamp, Trash2 } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { ElButton, ElEmpty, ElInput, ElOption, ElPagination, ElSelect, ElSpace, ElTable, ElTableColumn, ElTag, ElText, ElTooltip, vLoading } from 'element-plus'
import type { TableInstance } from 'element-plus'
import type { KnowledgeListItem, KnowledgePage, KnowledgeStatus, VerificationStatus } from '@/api/types'

interface ListFilters { type: string; status: string; source: string; tag: string; sort: string }
const props = defineProps<{
  page: KnowledgePage
  filters: ListFilters
  loading: boolean
  canManage: boolean
  canReview: boolean
  spacePath: string
  keyword: string
  filterLabel: string
}>()
const emit = defineEmits<{
  search: [value: string]
  create: []
  open: [id: string]
  edit: [item: KnowledgeListItem]
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
const statusMeta: Record<KnowledgeStatus, { label: string; tag: 'success' | 'warning' | 'info' | 'danger' }> = {
  published: { label: '已发布', tag: 'success' },
  candidate: { label: '待人工审核', tag: 'warning' },
  draft: { label: '草稿', tag: 'info' },
  archived: { label: '已归档', tag: 'info' },
  rejected: { label: '已驳回', tag: 'danger' },
}
const verificationMeta: Record<VerificationStatus, { label: string; tag: 'success' | 'info' | 'danger' }> = {
  verified: { label: '已验证', tag: 'success' },
  unverified: { label: '未验证', tag: 'info' },
  failed: { label: '验证失败', tag: 'danger' },
}

const keywordDraft = ref(props.keyword)
const tagInput = ref(props.filters.tag)
const moreOpen = ref(false)
const selectedRows = ref<KnowledgeListItem[]>([])
const tableRef = ref<TableInstance>()

type Row = Record<string, any>

const statusOptions = computed(() => [
  { value: 'published', label: '已发布' },
  ...(props.canReview ? [{ value: 'candidate', label: '待审核经验' }] : []),
  ...(props.canManage || props.canReview ? [{ value: 'draft', label: '草稿' }] : []),
  ...(props.canManage ? [{ value: 'archived', label: '已归档' }] : []),
  ...(props.canReview ? [{ value: 'rejected', label: '已驳回' }] : []),
])
const allTags = computed(() => { const set = new Set<string>(); props.page.items.forEach((item) => item.tags.forEach((tag) => set.add(tag))); return [...set] })
const tagOptions = computed(() => allTags.value.slice(0, 24))
const hasFilters = computed(() => Boolean(props.keyword || props.filters.type || props.filters.status || props.filters.source || props.filters.tag))

watch(() => props.keyword, (value) => { keywordDraft.value = value })
watch(() => props.filters.tag, (value) => { tagInput.value = value })

function runSearch() { emit('search', keywordDraft.value.trim()) }
function applyFilter(key: keyof ListFilters, value: unknown) { emit('filter', key, String(value ?? '')) }
function applyTag() { const value = tagInput.value.trim(); if (value === props.filters.tag) return; emit('filter', 'tag', value) }
function onRowClick(row: Row, column: unknown) {
  if (column && typeof column === 'object' && (column as { type?: string }).type === 'selection') return
  emit('open', row.id)
}
function onSelectionChange(rows: Row[]) { selectedRows.value = rows as KnowledgeListItem[] }
function clearSelection() { tableRef.value?.clearSelection() }
function emitBatch(action: 'move' | 'archive' | 'publish' | 'delete') { const ids = selectedRows.value.map((item) => item.id); clearSelection(); emit('batch', ids, action) }
function openRow(row: Row) { emit('open', row.id) }
function editRow(row: Row) { emit('edit', row as KnowledgeListItem) }
function moveRow(row: Row) { emit('move', row as KnowledgeListItem) }
function publishRow(row: Row) { emit('publish', row as KnowledgeListItem) }
function archiveRow(row: Row) { emit('archive', row as KnowledgeListItem) }
function deleteRow(row: Row) { emit('delete', row as KnowledgeListItem) }
const typeLabel = (value: string) => types.find((item) => item.value === value)?.label ?? value
const statusTag = (value: KnowledgeStatus) => (statusMeta[value] ?? statusMeta.draft).tag
const statusLabel = (value: KnowledgeStatus) => (statusMeta[value] ?? { label: value, tag: 'info' as const }).label
const verificationTag = (value: VerificationStatus) => (verificationMeta[value] ?? verificationMeta.unverified).tag
const verificationLabel = (value: VerificationStatus) => (verificationMeta[value] ?? { label: value, tag: 'info' as const }).label
const metaText = (row: Row) => row.summary || (row.tags as string[]).map((tag) => `#${tag}`).join(' ') || row.id
const tagText = (row: Row) => (row.summary && (row.tags as string[]).length ? (row.tags as string[]).slice(0, 3).map((tag) => `#${tag}`).join(' ') : '')
const formatDate = (value: string) => new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
</script>

<style scoped>
.knowledge-list{display:flex;flex-direction:column;min-width:0;height:100%;overflow:hidden;background:#fff}
.knowledge-list>*{flex:none}
.knowledge-list>.knowledge-table-wrap{flex:1 1 auto;min-height:0}
.knowledge-list__header{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:58px;padding:10px 15px;border-bottom:1px solid var(--astra-border)}
.list-context{min-width:0}
.knowledge-list h3,.knowledge-list p{margin:0}
.knowledge-list h3{overflow:hidden;color:var(--astra-text-primary);font-size:var(--astra-font-section);text-overflow:ellipsis;white-space:nowrap}
.knowledge-list p{margin-top:3px;color:var(--astra-text-muted);font-size:var(--astra-font-helper)}
.knowledge-list__filters{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:9px 14px;border-bottom:1px solid var(--astra-border);background:#fbfdfc}
.knowledge-filter__type{width:132px}
.knowledge-filter__status{width:150px}
.knowledge-filter__sort{width:136px}
.knowledge-filter__search{flex:1 1 240px;min-width:190px;max-width:420px}
.knowledge-filter__more.is-active{color:var(--astra-primary-bright);border-color:var(--astra-primary-border);background:var(--astra-primary-soft)}
.knowledge-list__more{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:9px 14px;border-bottom:1px solid var(--astra-border)}
.knowledge-filter__source{width:140px}
.knowledge-filter__tag{display:flex;align-items:center;gap:8px;flex:1 1 260px;min-width:0;max-width:420px}
.knowledge-filter__tag .el-input{flex:1 1 auto;min-width:0}
.knowledge-list__active{display:flex;align-items:center;padding:8px 14px;border-bottom:1px solid var(--astra-border)}
.knowledge-list__batch{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:7px 14px;border-bottom:1px solid var(--astra-border);background:var(--astra-primary-soft)}
.knowledge-table-wrap{min-height:0}
.knowledge-table{--el-table-border-color:var(--astra-border)}
.knowledge-table :deep(.el-table__row){cursor:pointer}
.knowledge-table :deep(.el-empty){padding:28px 0}
.knowledge-cell{display:grid;min-width:0;gap:2px}
.knowledge-cell strong{overflow:hidden;color:var(--astra-text-primary);font-size:var(--astra-font-label);text-overflow:ellipsis;white-space:nowrap}
.row-actions{justify-content:flex-end}
.empty-actions{display:flex;justify-content:center;gap:8px}
.knowledge-list__footer{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:8px 14px;border-top:1px solid var(--astra-border)}
@media(max-width:1100px){.knowledge-filter__search{max-width:none}}
</style>
