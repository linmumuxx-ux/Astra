<template>
  <div class="page digital-library-page" data-testid="digital-library-page">
    <section class="library-intro">
      <div><h2>数字图书馆</h2><p>集中管理与沉淀数字员工共享的知识资产，支撑任务执行与经验复用。</p></div>
      <div class="library-head-actions">
        <label class="library-search"><Search :size="17" /><input v-model="queryInput" placeholder="搜索标题、正文、标签、来源任务或关键词" aria-label="全局知识搜索" /><button v-if="queryInput" type="button" aria-label="清空搜索" @click="queryInput = ''"><X :size="14" /></button></label>
        <button v-if="permissions?.can_manage" type="button" class="button" @click="triggerImport"><Upload :size="15" />导入</button>
        <button v-if="permissions?.can_manage" type="button" class="button button--primary" @click="beginCreate"><Plus :size="15" />新建知识</button>
        <input ref="importInput" class="hidden-input" type="file" accept=".md,text/markdown,text/plain" @change="importMarkdown" />
      </div>
    </section>

    <LibraryStats :stats="stats" :active="statsActive" :can-review="Boolean(permissions?.can_review)" @select="applyStat" />

    <div v-if="pageError" class="library-error"><TriangleAlert :size="16" />{{ pageError }}<button type="button" @click="loadAll">重试</button></div>
    <section class="library-workspace">
      <KnowledgeSpacePanel :spaces="spaces" :selected-id="filters.spaceId" :total="stats?.knowledge_pages ?? 0" :can-manage="Boolean(permissions?.can_manage)" @select="selectSpace" @create="createSpace" @rename="renameSpace" @toggle="disableSpace" />
      <KnowledgeList :page="page" :filters="filters" :loading="listLoading" :can-manage="Boolean(permissions?.can_manage)" :can-review="Boolean(permissions?.can_review)" :space-name="selectedSpace?.name ?? null" :filter-label="activeFilterLabel" @open="openDetail" @page="setPage" @filter="setFilter" @clear-filter="clearFilters" />
    </section>

    <KnowledgeUsageSummary :summary="usage" />
    <div v-if="toast" class="library-toast"><CircleCheck :size="15" />{{ toast }}</div>

    <KnowledgeEditorDialog :open="editorOpen" :spaces="spaces" :saving="editorSaving" :error="editorError" :initial-content="editorInitialContent" :initial-title="editorInitialTitle" @close="editorOpen = false" @save="saveKnowledge" />
    <KnowledgeDetailDialog :open="detailOpen" :detail="detail" :spaces="spaces" :can-review="Boolean(permissions?.can_review)" :working="detailWorking" :error="detailError" :related-tasks="relatedTasks" :related-loading="relatedLoading" @close="closeDetail" @favorite="favorite" @helpful="helpful" @related="loadRelatedTasks" @publish="publish" @reject="reject" @supplement="supplement" />
  </div>
</template>

<script setup lang="ts">
import { CircleCheck, Plus, Search, TriangleAlert, Upload, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { KnowledgeDetail, KnowledgePage, KnowledgeSpace, LibraryPermissions, LibraryStats as LibraryStatsData, LibraryUsageSummary, RelatedTask } from '@/api/types'
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
const filters = reactive({ spaceId: null as string | null, type: '', status: '', sort: 'updated_desc', page: 1, keyword: '' })
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
const importInput = ref<HTMLInputElement | null>(null)
const detailOpen = ref(false)
const detail = ref<KnowledgeDetail | null>(null)
const detailWorking = ref(false)
const detailError = ref('')
const relatedTasks = ref<RelatedTask[]>([])
const relatedLoading = ref(false)
let searchTimer = 0
let toastTimer = 0

const selectedSpace = computed(() => spaces.value.find((space) => space.id === filters.spaceId))
const activeFilterLabel = computed(() => {
  if (filters.status === 'candidate') return '候选经验'
  if (filters.type === 'experience' && filters.status === 'published') return '已发布经验'
  if (filters.keyword) return `搜索：${filters.keyword}`
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
    permissions.value = permissionValue; stats.value = statsValue; spaces.value = spacesValue; usage.value = usageValue
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
    if (filters.keyword) query.set('keyword', filters.keyword)
    page.value = await api.libraryKnowledge(`?${query}`)
  } catch (error) { pageError.value = message(error, '知识列表加载失败'); page.value = emptyPage() } finally { listLoading.value = false }
}
async function refreshOverview() {
  const [statsValue, spacesValue, usageValue] = await Promise.all([api.libraryStats(), api.librarySpaces(), api.libraryUsageSummary(7)])
  stats.value = statsValue; spaces.value = spacesValue; usage.value = usageValue
}
function applyStat(value: string) {
  if (value === 'spaces') { statsActive.value = value; return }
  filters.spaceId = null; filters.type = ''; filters.status = ''; filters.sort = 'updated_desc'; filters.page = 1; filters.keyword = ''; queryInput.value = ''
  if (value === 'weekly') filters.sort = 'references_desc'
  if (value === 'published') { filters.type = 'experience'; filters.status = 'published' }
  if (value === 'candidate') { filters.type = 'experience'; filters.status = 'candidate' }
  statsActive.value = value; loadList()
}
function selectSpace(id: string | null) { filters.spaceId = id; filters.page = 1; statsActive.value = 'spaces'; loadList() }
function setPage(value: number) { filters.page = value; loadList() }
function setFilter(key: 'type' | 'status' | 'sort', value: string) { filters[key] = value; filters.page = 1; statsActive.value = value === 'candidate' ? 'candidate' : 'filter'; loadList() }
function clearFilters() { filters.spaceId = null; filters.type = ''; filters.status = ''; filters.sort = 'updated_desc'; filters.keyword = ''; filters.page = 1; queryInput.value = ''; statsActive.value = 'all'; loadList() }
function beginCreate() { editorInitialContent.value = ''; editorInitialTitle.value = ''; editorError.value = ''; editorOpen.value = true }
function triggerImport() { importInput.value?.click() }
async function importMarkdown(event: Event) { const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return; editorInitialContent.value = await file.text(); editorInitialTitle.value = file.name.replace(/\.md$/i, ''); editorError.value = ''; editorOpen.value = true; (event.target as HTMLInputElement).value = '' }
async function saveKnowledge(payload: Record<string, unknown>) {
  editorSaving.value = true; editorError.value = ''
  try { const created = await api.createLibraryKnowledge(payload); editorOpen.value = false; notify('知识草稿已保存'); await Promise.all([refreshOverview(), loadList()]); await openDetail(created.id) } catch (error) { editorError.value = message(error, '知识保存失败') } finally { editorSaving.value = false }
}
async function createSpace(name: string) { try { await api.createLibrarySpace({ name }); notify('知识空间已创建'); await refreshOverview() } catch (error) { pageError.value = message(error, '知识空间创建失败') } }
async function renameSpace(space: KnowledgeSpace, name: string) { try { await api.updateLibrarySpace(space.id, { name }); notify('知识空间已重命名'); await refreshOverview() } catch (error) { pageError.value = message(error, '知识空间重命名失败') } }
async function disableSpace(space: KnowledgeSpace) { if (!window.confirm(`确认停用“${space.name}”？已有知识仍会保留。`)) return; try { await api.updateLibrarySpace(space.id, { status: 'inactive' }); if (filters.spaceId === space.id) filters.spaceId = null; notify('知识空间已停用'); await Promise.all([refreshOverview(), loadList()]) } catch (error) { pageError.value = message(error, '知识空间停用失败') } }
async function openDetail(id: string, syncUrl = true) { detailOpen.value = true; detail.value = null; detailError.value = ''; relatedTasks.value = []; try { detail.value = await api.libraryKnowledgeDetail(id); if (syncUrl) await router.replace({ query: { ...route.query, knowledge: id } }) } catch (error) { detailError.value = message(error, '知识详情加载失败') } }
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
</script>

<style scoped>
.digital-library-page{position:relative}.library-intro{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:17px}.library-intro h2,.library-intro p{margin:0}.library-intro h2{color:var(--astra-text-primary);font-size:var(--astra-font-title)}.library-intro p{margin-top:5px;color:var(--astra-text-secondary);font-size:var(--astra-font-body)}.library-head-actions{display:flex;align-items:center;gap:8px}.library-search{display:flex;align-items:center;gap:8px;width:min(440px,38vw);height:42px;padding:0 10px;color:var(--astra-text-muted);border:1px solid var(--astra-border);border-radius:10px;background:#fff;box-shadow:0 4px 14px rgba(35,76,59,.04)}.library-search input{min-width:0;flex:1;color:var(--astra-text-primary);border:0;outline:0;background:transparent}.library-search>button{display:grid;place-items:center;padding:0;color:var(--astra-text-muted);border:0;background:transparent;cursor:pointer}.hidden-input{display:none}.library-workspace{display:grid;grid-template-columns:250px minmax(0,1fr);gap:16px;align-items:start}.library-error{display:flex;align-items:center;gap:8px;margin-bottom:12px;padding:10px 12px;color:var(--astra-danger);border:1px solid rgba(228,93,106,.18);border-radius:9px;background:var(--astra-danger-soft);font-size:var(--astra-font-body)}.library-error button{margin-left:auto;color:inherit;border:0;background:transparent;text-decoration:underline;cursor:pointer}.library-toast{position:fixed;z-index:1400;right:28px;bottom:28px;display:flex;align-items:center;gap:7px;padding:11px 14px;color:#fff;border-radius:9px;background:#178f5d;box-shadow:0 12px 36px rgba(16,37,34,.24);font-size:var(--astra-font-body)}
@media(max-width:1100px){.library-intro{align-items:flex-start;flex-direction:column}.library-head-actions{width:100%;flex-wrap:wrap}.library-search{width:auto;min-width:280px;flex:1}}@media(max-width:780px){.library-workspace{grid-template-columns:1fr}.library-head-actions .button{flex:1}.library-search{flex-basis:100%}}@media(max-width:500px){.library-head-actions{display:grid;grid-template-columns:1fr 1fr}.library-search{grid-column:1/-1;min-width:0}}
</style>
