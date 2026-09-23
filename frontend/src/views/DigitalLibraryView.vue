<template>
  <div class="page digital-library-page" data-testid="digital-library-page">
    <section class="library-intro">
      <div>
        <h2>数字图书馆</h2>
        <p>管理团队知识、经验与项目资料。</p>
      </div>
      <div class="library-head-actions">
        <button v-if="permissions?.can_manage" type="button" class="button" @click="triggerImport"><Upload :size="15" />导入知识</button>
        <button v-if="permissions?.can_manage" type="button" class="button button--primary" @click="beginCreate"><Plus :size="15" />新建知识</button>
        <input ref="importInput" class="hidden-input" type="file" accept=".md,text/markdown,text/plain" @change="importMarkdown" />
      </div>
    </section>

    <section class="library-status-row">
      <div class="knowledge-service" :data-state="serviceError || serviceStatus?.healthy === false ? 'error' : 'ok'" aria-label="知识服务状态">
        <span class="service-dot" />
        <strong>知识服务：{{ serviceError ? '异常' : serviceStatus ? (serviceStatus.healthy ? '正常' : '异常') : '检查中' }}</strong>
        <span>最近同步：{{ serviceStatus?.last_synced_at ? new Date(serviceStatus.last_synced_at).toLocaleString() : '暂无' }}</span>
        <span v-if="(serviceStatus?.pending_count ?? 0) || (serviceStatus?.failed_count ?? 0)">待同步 {{ serviceStatus?.pending_count ?? 0 }} · 同步失败 {{ serviceStatus?.failed_count ?? 0 }}</span>
        <button v-if="permissions?.can_manage && (serviceError || serviceStatus?.healthy === false || (serviceStatus?.failed_count ?? 0) > 0)" type="button" class="text-action" :disabled="resyncing || !serviceStatus?.enabled" @click="resyncKnowledge">{{ resyncing ? '提交中…' : '重新同步' }}</button>
        <small v-if="serviceError" role="status">{{ serviceError }}</small>
      </div>
      <button v-if="permissions?.can_review" type="button" class="review-queue" :class="{ active: statsActive === 'candidate' }" @click="applyStat('candidate')">
        待审核经验 <strong>{{ stats?.candidate_experiences ?? 0 }}</strong><ChevronRight :size="14" />
      </button>
    </section>

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
        :space-path="selectedPath"
        :keyword="queryInput"
        :filter-label="activeFilterLabel"
        @search="queryInput = $event"
        @create="beginCreate"
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

    <KnowledgeEditorDialog :open="editorOpen" :directories="directoryOptions" :saving="editorSaving" :error="editorError" :initial-content="editorInitialContent" :initial-title="editorInitialTitle" :initial-space-id="editorInitialSpaceId" @close="editorOpen = false" @save="saveKnowledge" />
    <KnowledgeDetailDialog :open="detailOpen" :detail="detail" :directories="directoryOptions" :can-review="Boolean(permissions?.can_review)" :working="detailWorking" :error="detailError" :related-tasks="relatedTasks" :related-loading="relatedLoading" :usages="usages" :usages-loading="usagesLoading" @close="closeDetail" @favorite="favorite" @helpful="helpful" @related="loadRelatedTasks" @publish="publish" @reject="reject" @supplement="supplement" />

    <DirectoryPickerDialog
      :open="Boolean(moveDialog)"
      title="移动知识"
      :subtitle="moveDialog ? `为 ${moveDialog.ids.length} 条知识选择目标目录。` : ''"
      :spaces="spaces"
      :selected-id="moveSpaceId"
      confirm-label="移动"
      :busy="moving"
      @close="moveDialog = null"
      @confirm="submitMove"
    />

    <AstraDialog
      v-if="publishDialog"
      :open="true"
      title="发布知识"
      :subtitle="`为 ${publishDialog.ids.length} 条知识选择目录并发布。`"
      :dismissible="false"
      :busy="working"
      testid="knowledge-publish-dialog"
      card-class="move-knowledge-card"
      width="min(460px,100%)"
      @close="publishDialog = null"
    >
      <form id="knowledge-publish-form" @submit.prevent="submitBatchPublish">
        <label>目标目录<select v-model="publishSpaceId" required><option value="" disabled>选择目录</option><option v-for="item in directoryOptions" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
        <label>验证状态<select v-model="publishVerification"><option value="unverified">未验证</option><option value="verified">已验证</option><option value="failed">验证失败</option></select></label>
      </form>
      <template #footer>
        <button type="button" class="button" :disabled="working" @click="publishDialog = null">取消</button>
        <button type="submit" form="knowledge-publish-form" class="button button--primary" :disabled="!publishSpaceId || working"><LoaderCircle v-if="working" :size="14" class="spin" />发布</button>
      </template>
    </AstraDialog>
  </div>
</template>

<script setup lang="ts">
import { ChevronRight, LoaderCircle, Plus, TriangleAlert, Upload } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { KnowledgeDetail, KnowledgeListItem, KnowledgePage, KnowledgeSpace, KnowledgeUsageRecord, LibraryPermissions, LibraryStats as LibraryStatsData, LibraryUsageSummary, LibraryServiceStatus, RelatedTask } from '@/api/types'
import AstraDialog from '@/components/astra/AstraDialog.vue'
import { confirmDialog } from '@/composables/useConfirm'
import { notify } from '@/composables/useToast'
import DirectoryPickerDialog from '@/views/library/DirectoryPickerDialog.vue'
import KnowledgeDetailDialog from '@/views/library/KnowledgeDetailDialog.vue'
import KnowledgeEditorDialog from '@/views/library/KnowledgeEditorDialog.vue'
import KnowledgeList from '@/views/library/KnowledgeList.vue'
import KnowledgeSpacePanel from '@/views/library/KnowledgeSpacePanel.vue'
import KnowledgeUsageSummary from '@/views/library/KnowledgeUsageSummary.vue'

const route = useRoute()
const router = useRouter()
const emptyPage = (): KnowledgePage => ({ items: [], total: 0, page: 1, page_size: 20, pages: 1 })
const stats = ref<LibraryStatsData | null>(null)
const permissions = ref<LibraryPermissions | null>(null)
const spaces = ref<KnowledgeSpace[]>([])
const usage = ref<LibraryUsageSummary | null>(null)
const serviceStatus = ref<LibraryServiceStatus | null>(null)
const serviceError = ref('')
const resyncing = ref(false)
let serviceTimer = 0
let serviceLoading = false
let disposed = false
async function loadServiceStatus() {
  if (serviceLoading) return
  serviceLoading = true
  try { serviceStatus.value = await api.libraryServiceStatus(); serviceError.value = '' }
  catch (error) { serviceError.value = message(error, '知识服务状态加载失败'); serviceStatus.value = null }
  finally {
    serviceLoading = false
    if (!disposed) serviceTimer = window.setTimeout(loadServiceStatus, 10000)
  }
}
async function resyncKnowledge() {
  resyncing.value = true
  try {
    const result = await api.libraryResync()
    notify(`已提交 ${result.pending_count} 条同步任务`)
    window.clearTimeout(serviceTimer)
    await loadServiceStatus()
  } catch (error) { serviceError.value = message(error, '重新同步失败') }
  finally { resyncing.value = false }
}
const page = ref<KnowledgePage>(emptyPage())
const filters = reactive({ spaceId: null as string | null, type: '', status: '', source: '', tag: '', sort: 'updated_desc', page: 1, keyword: '' })
const queryInput = ref('')
const statsActive = ref('all')
const listLoading = ref(false)
const pageError = ref('')
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

const selectedSpace = computed(() => spaces.value.find((space) => space.id === filters.spaceId) ?? findNode(spaces.value, filters.spaceId) ?? null)
const selectedPath = computed(() => {
  if (!filters.spaceId) return '全部知识'
  return findPath(spaces.value, filters.spaceId)?.join(' / ') ?? selectedSpace.value?.name ?? '全部知识'
})
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
  void loadServiceStatus()
  if (route.query.status === 'candidate') {
    filters.type = 'experience'
    filters.status = 'candidate'
    statsActive.value = 'candidate'
  }
  await loadAll()
  const knowledgeId = typeof route.query.knowledge === 'string' ? route.query.knowledge : ''
  if (knowledgeId) await openDetail(knowledgeId, false)
})
onBeforeUnmount(() => { disposed = true; window.clearTimeout(serviceTimer); window.clearTimeout(searchTimer) })
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
async function createSpace(name: string, parentId: string | null) {
  try {
    const created = await api.createLibrarySpace({ name, parent_id: parentId })
    filters.spaceId = created.id
    filters.page = 1
    notify(parentId ? `已创建子目录「${created.name}」` : `已创建知识空间「${created.name}」`)
    await Promise.all([refreshOverview(), loadList()])
  } catch (error) { notify(message(error, '创建失败'), 'error') }
}
async function renameSpace(space: KnowledgeSpace, name: string) {
  try {
    await api.updateLibrarySpace(space.id, { name })
    notify(`已重命名为「${name}」`)
    await refreshOverview()
  } catch (error) { notify(message(error, '重命名失败'), 'error') }
}
async function deleteSpace(space: KnowledgeSpace) {
  const confirmed = await confirmDialog({ title: '删除目录', message: `确认删除「${space.name}」？仅空目录可以删除，其下内容不会被级联删除。`, confirmLabel: '删除目录', danger: true })
  if (!confirmed) return
  try { await api.deleteLibrarySpace(space.id); if (filters.spaceId === space.id) filters.spaceId = null; notify('目录已删除'); await Promise.all([refreshOverview(), loadList()]) } catch (error) { notify(message(error, '删除失败'), 'error') }
}
async function moveSpace(space: KnowledgeSpace, targetParentId: string) {
  try {
    await api.moveLibrarySpace(space.id, targetParentId)
    notify(`已移动「${space.name}」`)
    await refreshOverview()
  } catch (error) { notify(message(error, '移动失败'), 'error') }
}
function openMoveDialog(item: KnowledgeListItem) { moveSpaceId.value = item.space_id ?? ''; moveDialog.value = { ids: [item.id] } }
async function submitMove(targetSpaceId: string) {
  if (!moveDialog.value || !targetSpaceId) return
  moving.value = true
  moveSpaceId.value = targetSpaceId
  try {
    await api.batchMoveLibraryKnowledge(moveDialog.value.ids, targetSpaceId)
    moveDialog.value = null
    notify('知识已移动')
    await Promise.all([refreshOverview(), loadList()])
  } catch (error) { notify(message(error, '移动失败'), 'error') } finally { moving.value = false }
}
async function archiveFromList(item: KnowledgeListItem) { try { await api.archiveLibraryKnowledge(item.id); notify('已归档'); await Promise.all([refreshOverview(), loadList()]) } catch (error) { notify(message(error, '归档失败'), 'error') } }
async function deleteFromList(item: KnowledgeListItem) {
  const confirmed = await confirmDialog({ title: '删除知识', message: `确认删除「${item.title}」？删除后无法恢复。`, confirmLabel: '删除知识', danger: true })
  if (!confirmed) return
  try { await api.deleteLibraryKnowledge(item.id); notify('已删除'); await Promise.all([refreshOverview(), loadList()]) } catch (error) { notify(message(error, '删除失败'), 'error') }
}
function onBatch(ids: string[], action: 'move' | 'archive' | 'publish' | 'delete') {
  if (action === 'move') { moveSpaceId.value = ''; moveDialog.value = { ids }; return }
  if (action === 'publish') { publishSpaceId.value = ''; publishVerification.value = 'verified'; publishDialog.value = { ids }; return }
  if (action === 'archive') { void api.batchArchiveLibraryKnowledge(ids).then(() => { notify('已批量归档'); return Promise.all([refreshOverview(), loadList()]) }).catch((error) => { notify(message(error, '批量归档失败'), 'error') }); return }
  if (action === 'delete') {
    void confirmDialog({ title: '批量删除知识', message: `确认删除选中的 ${ids.length} 条知识？删除后无法恢复。`, confirmLabel: '批量删除', danger: true }).then((confirmed) => {
      if (!confirmed) return
      return api.batchDeleteLibraryKnowledge(ids).then(() => { notify('已批量删除'); return Promise.all([refreshOverview(), loadList()]) }).catch((error) => { notify(message(error, '批量删除失败'), 'error') })
    })
  }
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
function message(error: unknown, fallback: string) { return error instanceof Error ? error.message : fallback }
const sourceLabel = (value: string) => ({ task: '任务沉淀', manual: '人工创建', import: '文档导入', system: '系统同步' }[value] ?? value)
function findNode(nodes: KnowledgeSpace[], id: string | null): KnowledgeSpace | null {
  if (!id) return null
  for (const node of nodes) { if (node.id === id) return node; const found = findNode(node.children ?? [], id); if (found) return found }
  return null
}
function findPath(nodes: KnowledgeSpace[], id: string, parents: string[] = []): string[] | null {
  for (const node of nodes) {
    const path = [...parents, node.name]
    if (node.id === id) return path
    const found = findPath(node.children ?? [], id, path)
    if (found) return found
  }
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
.digital-library-page{position:relative;display:grid;grid-template-rows:auto auto auto minmax(0,1fr) auto;gap:12px;height:calc(100vh - 92px);min-height:620px;overflow:hidden}.library-intro{display:flex;align-items:center;justify-content:space-between;gap:18px}.library-intro h2,.library-intro p{margin:0}.library-intro h2{color:var(--astra-text-primary)}.library-intro p{margin-top:4px;color:var(--astra-text-secondary);font-size:var(--astra-font-body)}.library-head-actions{display:flex;align-items:center;gap:8px}.hidden-input{display:none}.library-status-row{display:flex;align-items:center;justify-content:space-between;gap:10px;min-width:0}.knowledge-service{display:flex;align-items:center;min-width:0;gap:8px;color:var(--astra-text-muted);font-size:var(--astra-font-helper)}.knowledge-service strong{color:var(--astra-text-secondary)}.knowledge-service[data-state='error'] strong,.knowledge-service[data-state='error'] .service-dot{color:var(--astra-danger);background:var(--astra-danger)}.service-dot{width:7px;height:7px;flex:none;border-radius:50%;background:var(--astra-primary)}.knowledge-service small{overflow:hidden;max-width:360px;color:var(--astra-danger);text-overflow:ellipsis;white-space:nowrap}.text-action{padding:0;color:var(--astra-primary-bright);border:0;background:transparent;font-size:inherit;cursor:pointer}.text-action:disabled{cursor:default;opacity:.5}.review-queue{display:inline-flex;align-items:center;gap:6px;min-height:32px;padding:0 10px;color:#9b6428;border:1px solid rgba(233,149,63,.28);border-radius:8px;background:var(--astra-warning-soft);font-size:var(--astra-font-helper);cursor:pointer}.review-queue strong{font-size:var(--astra-font-label)}.review-queue.active{box-shadow:0 0 0 2px rgba(233,149,63,.12)}.library-workspace{display:grid;grid-template-columns:300px minmax(0,1fr);min-height:0;overflow:hidden;border:1px solid var(--astra-border);border-radius:12px;background:#fff;box-shadow:var(--astra-shadow-panel)}.library-error{display:flex;align-items:center;gap:8px;padding:9px 12px;color:var(--astra-danger);border:1px solid rgba(228,93,106,.18);border-radius:9px;background:var(--astra-danger-soft);font-size:var(--astra-font-body)}.library-error button{margin-left:auto;color:inherit;border:0;background:transparent;text-decoration:underline;cursor:pointer}.move-knowledge-card{width:min(460px,100%)}.move-knowledge-card label{display:grid;gap:6px;margin-top:14px;color:var(--astra-text-secondary);font-size:var(--astra-font-body)}.move-knowledge-card select{min-height:38px;padding:0 9px;color:var(--astra-text-primary);border:1px solid var(--astra-border);border-radius:8px;background:white}.move-knowledge-card footer{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}
@media(max-width:1100px){.digital-library-page{height:auto;min-height:0;overflow:visible}.library-intro{align-items:flex-start;flex-direction:column}.library-head-actions{width:100%;flex-wrap:wrap}.library-workspace{grid-template-columns:270px minmax(0,1fr);min-height:620px}.library-status-row{align-items:flex-start;flex-direction:column}}
@media(max-width:780px){.library-workspace{grid-template-columns:1fr;overflow:visible}.library-head-actions .button{flex:1}.knowledge-service{flex-wrap:wrap}}
</style>
