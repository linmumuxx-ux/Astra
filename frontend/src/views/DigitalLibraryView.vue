<template>
  <div class="page digital-library-page" data-testid="digital-library-page">
    <section class="library-intro">
      <div><h2>数字图书馆</h2><p>知识空间 · 多级目录 · 候选经验审核与引用追踪。</p></div>
      <div class="library-head-actions">
        <label class="library-search"><Search :size="17" /><input v-model="queryInput" placeholder="搜索标题、正文、标签、来源任务或关键词" aria-label="知识库搜索" /><button v-if="queryInput" type="button" aria-label="清空搜索" @click="queryInput = ''"><X :size="14" /></button></label>
        <button v-if="permissions?.can_manage" type="button" class="button" @click="triggerImport"><Upload :size="15" />导入</button>
        <button v-if="permissions?.can_manage" type="button" class="button button--primary" @click="beginCreate"><Plus :size="15" />新建知识</button>
        <input ref="importInput" class="hidden-input" type="file" accept=".md,text/markdown,text/plain" @change="importMarkdown" />
      </div>
    </section>

    <LibraryStats :stats="stats" :active="statsActive" :can-review="Boolean(permissions?.can_review)" @select="applyStat" />

    <div v-if="pageError" class="library-error"><TriangleAlert :size="16" />{{ pageError }}<button type="button" @click="loadAll">重试</button></div>

    <section class="library-workspace">
      <KnowledgeSpacePanel
        :spaces="spaces"
        :selected-id="filters.spaceId"
        :total="stats?.knowledge_pages ?? 0"
        :can-manage="Boolean(permissions?.can_manage)"
        @select="selectSpace"
        @create="createSpace"
        @rename="renameSpace"
        @move="moveSpace"
        @delete="deleteSpace"
      />
      <KnowledgeList
        :page="page"
        :filters="filters"
        :loading="listLoading"
        :can-manage="Boolean(permissions?.can_manage)"
        :can-review="Boolean(permissions?.can_review)"
        :space-name="selectedSpace?.name ?? null"
        :filter-label="activeFilterLabel"
        @open="openDetail"
        @move="openMoveDialog"
        @publish="publishFromList"
        @archive="archiveFromList"
        @delete="deleteFromList"
        @batch="onBatch"
        @page="setPage"
        @filter="setFilter"
        @clear-filter="clearFilters"
      />
    </section>

    <KnowledgeUsageSummary :summary="usage" />
    <div v-if="toast" class="library-toast"><CircleCheck :size="15" />{{ toast }}</div>

    <KnowledgeEditorDialog :open="editorOpen" :directories="directoryOptions" :saving="editorSaving" :error="editorError" :initial-content="editorInitialContent" :initial-title="editorInitialTitle" :initial-space-id="editorInitialSpaceId" @close="editorOpen = false" @save="saveKnowledge" />
    <KnowledgeDetailDialog :open="detailOpen" :detail="detail" :directories="directoryOptions" :can-review="Boolean(permissions?.can_review)" :working="detailWorking" :error="detailError" :related-tasks="relatedTasks" :related-loading="relatedLoading" :usages="usages" :usages-loading="usagesLoading" @close="closeDetail" @favorite="favorite" @helpful="helpful" @related="loadRelatedTasks" @publish="publish" @reject="reject" @supplement="supplement" />

    <div v-if="moveDialog" class="modal-backdrop" data-testid="knowledge-move-dialog" @click.self="moveDialog = null">
      <form class="modal-card move-knowledge-card" @submit.prevent="submitMove">
        <header><div><h3>移动到目录</h3><p>为 {{ moveDialog.ids.length }} 条知识选择目标目录。</p></div><button type="button" aria-label="关闭" @click="moveDialog = null"><X :size="17" /></button></header>
        <label>目标目录<select v-model="moveSpaceId" required><option value="" disabled>选择目录</option><option v-for="item in directoryOptions" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
        <footer><button type="button" class="button" @click="moveDialog = null">取消</button><button class="button button--primary" :disabled="!moveSpaceId || moving" type="submit"><LoaderCircle v-if="moving" :size="14" class="spin" />移动</button></footer>
      </form>
    </div>

    <div v-if="publishDialog" class="modal-backdrop" data-testid="knowledge-publish-dialog" @click.self="publishDialog = null">
      <form class="modal-card move-knowledge-card" @submit.prevent="submitBatchPublish">
        <header><div><h3>发布知识</h3><p>为 {{ publishDialog.ids.length }} 条知识选择目录并发布。</p></div><button type="button" aria-label="关闭" @click="publishDialog = null"><X :size="17" /></button></header>
        <label>目标目录<select v-model="publishSpaceId" required><option value="" disabled>选择目录</option><option v-for="item in directoryOptions" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
        <label>验证状态<select v-model="publishVerification"><option value="unverified">未验证</option><option value="verified">已验证</option><option value="failed">验证失败</option></select></label>
        <footer><button type="button" class="button" @click="publishDialog = null">取消</button><button class="button button--primary" :disabled="!publishSpaceId || working" type="submit"><LoaderCircle v-if="working" :size="14" class="spin" />发布</button></footer>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { CircleCheck, LoaderCircle, Plus, Search, TriangleAlert, Upload, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { KnowledgeDetail, KnowledgeListItem, KnowledgePage, KnowledgeSpace, KnowledgeUsageRecord, LibraryPermissions, LibraryStats as LibraryStatsData, LibraryUsageSummary, RelatedTask } from '@/api/types'
import KnowledgeDetailDialog from '@/views/library/KnowledgeDetailDialog.vue'
import KnowledgeEditorDialog from '@/views/library/KnowledgeEditorDialog.vue'
import KnowledgeList from '@/views/library/KnowledgeList.vue'
import KnowledgeSpacePanel from '@/views/library/KnowledgeSpacePanel.vue'
import KnowledgeUsageSummary from '@/views/library/KnowledgeUsageSummary.vue'
import LibraryStats from '@/views/library/LibraryStats.vue'

const route = useRoute()
const router = useRouter()
const emptyPage = (): KnowledgePage => ({ items: [], total: 0, page: 1, page_size: 20, pages: 1 })
const stats = ref<LibraryStatsData | null>(null)
const permissions = ref<LibraryPermissions | null>(null)
const spaces = ref<KnowledgeSpace[]>([])
const usage = ref<LibraryUsageSummary | null>(null)
const page = ref<KnowledgePage>(emptyPage())
const filters = reactive({ spaceId: null as string | null, type: '', status: '', source: '', tag: '', sort: 'updated_desc', page: 1, keyword: '' })
const queryInput = ref('')
const statsActive = ref('all')
const listLoading = ref(false)
const pageError = ref('')
const toast = ref('')
const editorOpen = ref(false)
const editorSaving = ref(false)
const editorError = ref('')
const editorInitialContent = ref('')
const editorInitialTitle = ref('')
const editorInitialSpaceId = ref('')
const editorSourceType = ref<'manual' | 'import'>('manual')
const importInput = ref<HTMLInputElement | null>(null)
const detailOpen = ref(false)
const detail = ref<KnowledgeDetail | null>(null)
const detailWorking = ref(false)
const detailError = ref('')
const relatedTasks = ref<RelatedTask[]>([])
const relatedLoading = ref(false)
const usages = ref<KnowledgeUsageRecord[]>([])
const usagesLoading = ref(false)
const moveDialog = ref<{ ids: string[] } | null>(null)
const publishDialog = ref<{ ids: string[] } | null>(null)
const moveSpaceId = ref('')
const publishSpaceId = ref('')
const publishVerification = ref('verified')
const moving = ref(false)
const working = ref(false)
let searchTimer = 0
let toastTimer = 0

const selectedSpace = computed(() => spaces.value.find((space) => space.id === filters.spaceId) ?? findNode(spaces.value, filters.spaceId) ?? null)
const directoryOptions = computed(() => {
  const result: Array<{ id: string; name: string; level: number }> = []
  const walk = (nodes: KnowledgeSpace[], level: number) => {
    for (const node of nodes) {
      result.push({ id: node.id, name: `${'　'.repeat(level)}${node.name}`, level })
      walk(node.children ?? [], level + 1)
    }
  }
  walk(spaces.value, 0)
  return result
})
const activeFilterLabel = computed(() => {
  if (filters.status === 'candidate') return '候选经验'
  if (filters.type === 'experience' && filters.status === 'published') return '已发布经验'
  if (filters.keyword) return `搜索：${filters.keyword}`
  if (filters.source) return `来源：${sourceLabel(filters.source)}`
  if (filters.tag) return `标签：${filters.tag}`
  return ''
})

onMounted(async () => {
  if (route.query.status === 'candidate') {
    filters.type = 'experience'
    filters.status = 'candidate'
    statsActive.value = 'candidate'
  }
  await loadAll()
  const knowledgeId = typeof route.query.knowledge === 'string' ? route.query.knowledge : ''
  if (knowledgeId) await openDetail(knowledgeId, false)
})
onBeforeUnmount(() => { window.clearTimeout(searchTimer); window.clearTimeout(toastTimer) })
watch(queryInput, (value) => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { filters.keyword = value.trim(); filters.page = 1; statsActive.value = filters.keyword ? 'search' : 'all'; loadList() }, 320)
})

async function loadAll() {
  pageError.value = ''
  try {
    const [permissionValue, statsValue, spacesValue, usageValue] = await Promise.all([api.libraryPermissions(), api.libraryStats(), api.librarySpaces(), api.libraryUsageSummary(7)])
    permissions.value = permissionValue; stats.value = statsValue; spaces.value = normalizeSpaces(spacesValue); usage.value = usageValue
    await loadList()
  } catch (error) { pageError.value = message(error, '数字图书馆加载失败') }
}
async function loadList() {
  listLoading.value = true
  try {
    const query = new URLSearchParams({ page: String(filters.page), page_size: '20', sort: filters.sort })
    if (filters.spaceId) query.set('space_id', filters.spaceId)
    if (filters.type) query.set('type', filters.type)
    if (filters.status) query.set('status', filters.status)
    if (filters.source) query.set('source', filters.source)
    if (filters.tag) query.set('tag', filters.tag)
    if (filters.keyword) query.set('keyword', filters.keyword)
    page.value = await api.libraryKnowledge(`?${query}`)
  } catch (error) { pageError.value = message(error, '知识列表加载失败'); page.value = emptyPage() } finally { listLoading.value = false }
}
async function refreshOverview() {
  const [statsValue, spacesValue, usageValue] = await Promise.all([api.libraryStats(), api.librarySpaces(), api.libraryUsageSummary(7)])
  stats.value = statsValue; spaces.value = normalizeSpaces(spacesValue); usage.value = usageValue
}
function applyStat(value: string) {
  if (value === 'spaces') { statsActive.value = value; return }
  filters.spaceId = null; filters.type = ''; filters.status = ''; filters.source = ''; filters.tag = ''; filters.sort = 'updated_desc'; filters.page = 1; filters.keyword = ''; queryInput.value = ''
  if (value === 'weekly') filters.sort = 'references_desc'
  if (value === 'published') { filters.type = 'experience'; filters.status = 'published' }
  if (value === 'candidate') { filters.type = 'experience'; filters.status = 'candidate' }
  statsActive.value = value; loadList()
}
function selectSpace(id: string | null) { filters.spaceId = id; filters.page = 1; statsActive.value = 'spaces'; loadList() }
function setPage(value: number) { filters.page = value; loadList() }
function setFilter(key: 'type' | 'status' | 'source' | 'tag' | 'sort', value: string) { filters[key] = value; filters.page = 1; statsActive.value = value === 'candidate' ? 'candidate' : 'filter'; loadList() }
function clearFilters() { filters.spaceId = null; filters.type = ''; filters.status = ''; filters.source = ''; filters.tag = ''; filters.sort = 'updated_desc'; filters.keyword = ''; filters.page = 1; queryInput.value = ''; statsActive.value = 'all'; loadList() }
function beginCreate() { editorInitialContent.value = ''; editorInitialTitle.value = ''; editorInitialSpaceId.value = filters.spaceId ?? directoryOptions.value[0]?.id ?? ''; editorSourceType.value = 'manual'; editorError.value = ''; editorOpen.value = true }
function publishFromList(item: KnowledgeListItem) { openDetail(item.id) }
function triggerImport() { importInput.value?.click() }
async function importMarkdown(event: Event) { const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return; editorInitialContent.value = await file.text(); editorInitialTitle.value = file.name.replace(/\.md$/i, ''); editorInitialSpaceId.value = filters.spaceId ?? directoryOptions.value[0]?.id ?? ''; editorSourceType.value = 'import'; editorError.value = ''; editorOpen.value = true; (event.target as HTMLInputElement).value = '' }
async function saveKnowledge(payload: Record<string, unknown>) {
  editorSaving.value = true; editorError.value = ''
  try {
    const created = await api.createLibraryKnowledge({ ...payload, source_type: editorSourceType.value })
    editorOpen.value = false; notify('知识草稿已保存')
    await Promise.all([refreshOverview(), loadList()])
    await openDetail(created.id)
  } catch (error) { editorError.value = message(error, '知识保存失败') } finally { editorSaving.value = false }
}
async function createSpace(name: string, parentId: string | null) { try { await api.createLibrarySpace({ name, parent_id: parentId }); notify(parentId ? '子目录已创建' : '知识空间已创建'); await refreshOverview() } catch (error) { pageError.value = message(error, '创建失败') } }
async function renameSpace(space: KnowledgeSpace, name: string) { try { await api.updateLibrarySpace(space.id, { name }); notify('已重命名'); await refreshOverview() } catch (error) { pageError.value = message(error, '重命名失败') } }
async function deleteSpace(space: KnowledgeSpace) { if (!window.confirm(`确认删除「${space.name}」？仅空目录可以删除，其下内容不会被级联删除。`)) return; try { await api.deleteLibrarySpace(space.id); if (filters.spaceId === space.id) filters.spaceId = null; notify('目录已删除'); await Promise.all([refreshOverview(), loadList()]) } catch (error) { pageError.value = message(error, '删除失败') } }
async function moveSpace(space: KnowledgeSpace, targetParentId: string) { try { await api.moveLibrarySpace(space.id, targetParentId); notify('目录已移动'); await refreshOverview() } catch (error) { pageError.value = message(error, '移动失败') } }
function openMoveDialog(item: KnowledgeListItem) { moveSpaceId.value = item.space_id ?? ''; moveDialog.value = { ids: [item.id] } }
async function submitMove() {
  if (!moveDialog.value || !moveSpaceId.value) return
  moving.value = true
  try { await api.batchMoveLibraryKnowledge(moveDialog.value.ids, moveSpaceId.value); moveDialog.value = null; notify('知识已移动'); await Promise.all([refreshOverview(), loadList()]) } catch (error) { pageError.value = message(error, '移动失败') } finally { moving.value = false }
}
async function archiveFromList(item: KnowledgeListItem) { try { await api.archiveLibraryKnowledge(item.id); notify('已归档'); await Promise.all([refreshOverview(), loadList()]) } catch (error) { pageError.value = message(error, '归档失败') } }
async function deleteFromList(item: KnowledgeListItem) { if (!window.confirm(`确认删除「${item.title}」？`)) return; try { await api.deleteLibraryKnowledge(item.id); notify('已删除'); await Promise.all([refreshOverview(), loadList()]) } catch (error) { pageError.value = message(error, '删除失败') } }
function onBatch(ids: string[], action: 'move' | 'archive' | 'publish' | 'delete') {
  if (action === 'move') { moveSpaceId.value = ''; moveDialog.value = { ids }; return }
  if (action === 'publish') { publishSpaceId.value = ''; publishVerification.value = 'verified'; publishDialog.value = { ids }; return }
  if (action === 'archive') { void api.batchArchiveLibraryKnowledge(ids).then(() => { notify('已批量归档'); return Promise.all([refreshOverview(), loadList()]) }).catch((error) => { pageError.value = message(error, '批量归档失败') }); return }
  if (action === 'delete') { if (!window.confirm(`确认删除选中的 ${ids.length} 条知识？`)) return; void api.batchDeleteLibraryKnowledge(ids).then(() => { notify('已批量删除'); return Promise.all([refreshOverview(), loadList()]) }).catch((error) => { pageError.value = message(error, '批量删除失败') }) }
}
async function submitBatchPublish() {
  if (!publishDialog.value || !publishSpaceId.value) return
  working.value = true
  try { await api.batchPublishLibraryKnowledge(publishDialog.value.ids, publishSpaceId.value, publishVerification.value); publishDialog.value = null; notify('候选经验已发布'); await Promise.all([refreshOverview(), loadList()]) } catch (error) { pageError.value = message(error, '发布失败') } finally { working.value = false }
}
async function openDetail(id: string, syncUrl = true) {
  detailOpen.value = true; detail.value = null; detailError.value = ''; relatedTasks.value = []; usages.value = []; usagesLoading.value = true
  try {
    detail.value = await api.libraryKnowledgeDetail(id)
    if (syncUrl) await router.replace({ query: { ...route.query, knowledge: id } })
    try { usages.value = await api.libraryKnowledgeUsages(id) } catch { usages.value = [] }
  } catch (error) { detailError.value = message(error, '知识详情加载失败') } finally { usagesLoading.value = false }
}
async function closeDetail() { detailOpen.value = false; detail.value = null; const query = { ...route.query }; delete query.knowledge; await router.replace({ query }) }
async function favorite() { if (!detail.value) return; try { const result = await api.favoriteLibraryKnowledge(detail.value.id); detail.value.is_favorite = result.favorite } catch (error) { detailError.value = message(error, '收藏操作失败') } }
async function helpful() { if (!detail.value) return; try { const result = await api.helpfulLibraryKnowledge(detail.value.id); detail.value.helpful_count = result.helpful_count; detail.value.user_helpful = true; notify(result.created ? '已记录“有帮助”反馈' : '你已反馈过这条知识') } catch (error) { detailError.value = message(error, '反馈提交失败') } }
async function loadRelatedTasks() { if (!detail.value || relatedLoading.value) return; relatedLoading.value = true; try { relatedTasks.value = await api.libraryRelatedTasks(detail.value.id) } catch (error) { detailError.value = message(error, '关联任务加载失败') } finally { relatedLoading.value = false } }
async function publish(payload: Record<string, unknown>) { if (!detail.value) return; await reviewAction(async () => api.publishLibraryKnowledge(detail.value!.id, payload), '候选经验已发布，数字员工现可立即检索') }
async function reject(reason: string) { if (!detail.value) return; await reviewAction(async () => api.rejectLibraryKnowledge(detail.value!.id, reason), '候选经验已驳回') }
async function supplement(reason: string) { if (!detail.value) return; await reviewAction(async () => api.supplementLibraryKnowledge(detail.value!.id, reason), '补充要求已记录') }
async function reviewAction(action: () => Promise<KnowledgeDetail>, success: string) { detailWorking.value = true; detailError.value = ''; try { detail.value = await action(); notify(success); await Promise.all([refreshOverview(), loadList()]) } catch (error) { detailError.value = message(error, '审核操作失败') } finally { detailWorking.value = false } }
function notify(value: string) { toast.value = value; window.clearTimeout(toastTimer); toastTimer = window.setTimeout(() => { toast.value = '' }, 2600) }
function message(error: unknown, fallback: string) { return error instanceof Error ? error.message : fallback }
const sourceLabel = (value: string) => ({ task: '任务沉淀', manual: '人工创建', import: '文档导入', system: '系统同步' }[value] ?? value)
function findNode(nodes: KnowledgeSpace[], id: string | null): KnowledgeSpace | null {
  if (!id) return null
  for (const node of nodes) { if (node.id === id) return node; const found = findNode(node.children ?? [], id); if (found) return found }
  return null
}
function normalizeSpaces(nodes: KnowledgeSpace[]): KnowledgeSpace[] {
  return nodes.map((node) => {
    const children = normalizeSpaces(Array.isArray(node.children) ? node.children : [])
    const directCount = Number.isFinite(node.knowledge_count) ? node.knowledge_count : 0
    const subtreeCount = Number.isFinite(node.subtree_knowledge_count)
      ? node.subtree_knowledge_count
      : directCount + children.reduce((total, child) => total + child.subtree_knowledge_count, 0)
    return { ...node, knowledge_count: directCount, subtree_knowledge_count: subtreeCount, children }
  })
}
</script>

<style scoped>
.digital-library-page{position:relative}.library-intro{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:17px}.library-intro h2,.library-intro p{margin:0}.library-intro h2{color:var(--astra-text-primary);font-size:var(--astra-font-title)}.library-intro p{margin-top:5px;color:var(--astra-text-secondary);font-size:var(--astra-font-body)}.library-head-actions{display:flex;align-items:center;gap:8px}.library-search{display:flex;align-items:center;gap:8px;width:min(440px,38vw);height:42px;padding:0 10px;color:var(--astra-text-muted);border:1px solid var(--astra-border);border-radius:10px;background:#fff;box-shadow:0 4px 14px rgba(35,76,59,.04)}.library-search input{min-width:0;flex:1;color:var(--astra-text-primary);border:0;outline:0;background:transparent}.library-search>button{display:grid;place-items:center;padding:0;color:var(--astra-text-muted);border:0;background:transparent;cursor:pointer}.hidden-input{display:none}.library-workspace{display:grid;grid-template-columns:300px minmax(0,1fr);gap:16px;align-items:start}.library-error{display:flex;align-items:center;gap:8px;margin-bottom:12px;padding:10px 12px;color:var(--astra-danger);border:1px solid rgba(228,93,106,.18);border-radius:9px;background:var(--astra-danger-soft);font-size:var(--astra-font-body)}.library-error button{margin-left:auto;color:inherit;border:0;background:transparent;text-decoration:underline;cursor:pointer}.library-toast{position:fixed;z-index:1400;right:28px;bottom:28px;display:flex;align-items:center;gap:7px;padding:11px 14px;color:#fff;border-radius:9px;background:#178f5d;box-shadow:0 12px 36px rgba(16,37,34,.24);font-size:var(--astra-font-body)}.move-knowledge-card{width:min(460px,100%)}.move-knowledge-card label{display:grid;gap:6px;margin-top:14px;color:var(--astra-text-secondary);font-size:var(--astra-font-body)}.move-knowledge-card select{min-height:38px;padding:0 9px;color:var(--astra-text-primary);border:1px solid var(--astra-border);border-radius:8px;background:white}.move-knowledge-card footer{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}
@media(max-width:1100px){.library-intro{align-items:flex-start;flex-direction:column}.library-head-actions{width:100%;flex-wrap:wrap}.library-search{width:auto;min-width:280px;flex:1}}@media(max-width:780px){.library-workspace{grid-template-columns:1fr}.library-head-actions .button{flex:1}.library-search{flex-basis:100%}}
</style>
