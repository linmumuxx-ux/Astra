<template>
  <section class="knowledge-list">
    <header class="knowledge-list__header">
      <div>
        <h3>数字图书</h3>
        <p>{{ page.total }} 条知识<span v-if="spaceName"> · {{ spaceName }}</span></p>
      </div>
      <div class="list-filters">
        <select :value="filters.type" aria-label="知识类型" @change="change('type', $event)">
          <option value="">全部类型</option><option v-for="item in types" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <select :value="filters.status" aria-label="知识状态" @change="change('status', $event)">
          <option value="">全部状态</option><option value="published">已发布</option><option v-if="canReview" value="candidate">候选经验</option><option v-if="canManage || canReview" value="draft">草稿</option><option v-if="canManage" value="archived">已归档</option><option v-if="canReview" value="rejected">已驳回</option>
        </select>
        <select :value="filters.sort" aria-label="知识排序" @change="change('sort', $event)">
          <option value="updated_desc">最近更新</option><option value="updated_asc">最早更新</option><option value="references_desc">引用最多</option><option value="title_asc">标题排序</option>
        </select>
      </div>
    </header>
    <div v-if="filterLabel" class="active-filter"><span>{{ filterLabel }}<button type="button" aria-label="清除当前筛选" @click="$emit('clear-filter')"><X :size="12" /></button></span></div>
    <div class="knowledge-table-wrap" :class="{ loading }">
      <table>
        <thead><tr><th>标题</th><th>类型</th><th>状态</th><th>更新时间</th><th>引用次数</th><th aria-label="操作" /></tr></thead>
        <tbody>
          <tr v-for="item in page.items" :key="item.id" tabindex="0" @click="$emit('open', item.id)" @keydown.enter="$emit('open', item.id)">
            <td><div class="knowledge-title"><span :data-status="item.status"><BookMarked :size="16" /></span><div><strong>{{ item.title }}</strong><small>{{ item.summary || item.tags.join(' · ') || item.id }}</small></div></div></td>
            <td><span class="type-chip">{{ typeLabel(item.type) }}</span></td>
            <td><span class="status-chip" :data-status="item.status">{{ statusLabel(item.status) }}</span></td>
            <td>{{ formatDate(item.updated_at) }}</td>
            <td><span class="reference-count"><Quote :size="13" />{{ item.reference_count }}</span></td>
            <td><button type="button" aria-label="打开知识详情" @click.stop="$emit('open', item.id)"><ChevronRight :size="16" /></button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="loading" class="list-loading"><LoaderCircle :size="22" class="spin" />正在加载知识</div>
      <div v-else-if="!page.items.length" class="empty-list"><Library :size="30" /><strong>暂无匹配知识</strong><p>调整知识空间、状态或搜索条件后重试。</p></div>
    </div>
    <footer v-if="page.total > 0">
      <span>第 {{ page.page }} / {{ page.pages }} 页</span>
      <div><button type="button" :disabled="page.page <= 1" @click="$emit('page', page.page - 1)"><ChevronLeft :size="15" />上一页</button><button type="button" :disabled="page.page >= page.pages" @click="$emit('page', page.page + 1)">下一页<ChevronRight :size="15" /></button></div>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { BookMarked, ChevronLeft, ChevronRight, Library, LoaderCircle, Quote, X } from 'lucide-vue-next'
import type { KnowledgePage, KnowledgeStatus, KnowledgeType } from '@/api/types'

interface ListFilters { type: string; status: string; sort: string }
defineProps<{ page: KnowledgePage; filters: ListFilters; loading: boolean; canManage: boolean; canReview: boolean; spaceName: string | null; filterLabel: string }>()
const emit = defineEmits<{ open: [id: string]; page: [page: number]; filter: [key: keyof ListFilters, value: string]; 'clear-filter': [] }>()
const types = [
  { value: 'document', label: '文档' }, { value: 'rule', label: '规范' }, { value: 'guide', label: '指南' },
  { value: 'experience', label: '经验' }, { value: 'faq', label: 'FAQ' }, { value: 'tool', label: '工具' }, { value: 'example', label: '示例' },
]
function change(key: keyof ListFilters, event: Event) { emit('filter', key, (event.target as HTMLSelectElement).value) }
const typeLabel = (value: KnowledgeType) => types.find((item) => item.value === value)?.label ?? value
const statusLabel = (value: KnowledgeStatus) => ({ published: '已发布', candidate: '待审核', draft: '草稿', archived: '已归档', rejected: '已驳回' }[value])
const formatDate = (value: string) => new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
</script>

<style scoped>
.knowledge-list { min-width: 0; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 12px; background: rgba(255,255,255,.96); box-shadow: var(--astra-shadow-panel); }
.knowledge-list__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 68px; padding: 11px 15px; border-bottom: 1px solid var(--astra-border); }.knowledge-list h3,.knowledge-list p { margin: 0; }.knowledge-list h3 { color: var(--astra-text-primary); font-size: var(--astra-font-section); }.knowledge-list p { margin-top: 3px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.list-filters { display: flex; gap: 7px; }.list-filters select { min-height: 35px; padding: 0 28px 0 9px; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 8px; background: white; }
.active-filter { padding: 8px 14px 0; }.active-filter > span { display: inline-flex; align-items: center; gap: 5px; padding: 5px 8px; color: #9b6428; border: 1px solid rgba(233,149,63,.28); border-radius: 7px; background: var(--astra-warning-soft); font-size: var(--astra-font-helper); }.active-filter button { display: grid; place-items: center; padding: 0; color: inherit; border: 0; background: transparent; cursor: pointer; }
.knowledge-table-wrap { position: relative; min-height: 310px; overflow-x: auto; }.knowledge-table-wrap.loading table { opacity: .45; }.knowledge-table-wrap table { width: 100%; min-width: 760px; border-collapse: collapse; }.knowledge-table-wrap th { height: 41px; padding: 0 12px; text-align: left; font-size: var(--astra-font-control); font-weight: 600; }.knowledge-table-wrap td { height: 62px; padding: 8px 12px; border-top: 1px solid var(--astra-border); font-size: var(--astra-font-body); }.knowledge-table-wrap tbody tr { cursor: pointer; outline: none; }.knowledge-table-wrap tbody tr:focus, .knowledge-table-wrap tbody tr:hover { background: #f2faf6; }.knowledge-table-wrap td:last-child button { display: grid; place-items: center; width: 30px; height: 30px; color: var(--astra-text-muted); border: 0; border-radius: 7px; background: transparent; cursor: pointer; }
.knowledge-title { display: flex; align-items: center; gap: 10px; min-width: 260px; }.knowledge-title > span { display: grid; place-items: center; flex: none; width: 32px; height: 32px; color: var(--astra-primary-bright); border-radius: 8px; background: var(--astra-primary-soft); }.knowledge-title > span[data-status='candidate'] { color: var(--astra-warning); background: var(--astra-warning-soft); }.knowledge-title > div { display: grid; min-width: 0; }.knowledge-title strong,.knowledge-title small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.knowledge-title strong { color: var(--astra-text-primary); font-size: var(--astra-font-emphasis); }.knowledge-title small { max-width: 480px; margin-top: 3px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.type-chip,.status-chip { display: inline-flex; padding: 4px 7px; border-radius: 6px; background: #edf3f0; font-size: var(--astra-font-helper); white-space: nowrap; }.status-chip[data-status='published'] { color: var(--astra-primary-bright); background: var(--astra-primary-soft); }.status-chip[data-status='candidate'] { color: #a46726; background: var(--astra-warning-soft); }.status-chip[data-status='rejected'] { color: var(--astra-danger); background: var(--astra-danger-soft); }.reference-count { display: inline-flex; align-items: center; gap: 5px; }
.list-loading,.empty-list { position: absolute; inset: 42px 0 0; display: grid; place-content: center; justify-items: center; gap: 7px; color: var(--astra-text-muted); background: rgba(255,255,255,.78); }.empty-list strong { color: var(--astra-text-secondary); }.empty-list p { margin: 0; }
.knowledge-list > footer { display: flex; align-items: center; justify-content: space-between; min-height: 52px; padding: 8px 14px; border-top: 1px solid var(--astra-border); color: var(--astra-text-muted); font-size: var(--astra-font-helper); }.knowledge-list > footer div { display: flex; gap: 6px; }.knowledge-list > footer button { display: inline-flex; align-items: center; gap: 4px; min-height: 32px; padding: 0 9px; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 7px; background: white; cursor: pointer; }.knowledge-list > footer button:disabled { cursor: default; opacity: .45; }
@media (max-width: 900px) { .knowledge-list__header { align-items: flex-start; flex-direction: column; }.list-filters { width: 100%; flex-wrap: wrap; }.list-filters select { flex: 1; } }
</style>
