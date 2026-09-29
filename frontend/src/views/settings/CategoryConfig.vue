<template>
  <div class="category-page" data-testid="category-page">
    <header class="category-page__intro">
      <div>
        <h2>任务分类</h2>
        <ElText size="small" type="info">分类用于表示任务所属的业务领域；排序小的排在前面，提示词随分类下发给对应数字员工。</ElText>
      </div>
      <ElSpace :size="10">
        <ElButton :icon="RefreshCw" :loading="loading" data-testid="category-refresh" @click="load">刷新</ElButton>
      </ElSpace>
    </header>

    <ElAlert v-if="error" type="error" show-icon :closable="false" :title="error" data-testid="category-error">
      <ElButton size="small" type="primary" data-testid="category-retry" @click="load">重试</ElButton>
    </ElAlert>

    <div class="category-filter" aria-label="任务分类筛选">
      <ElSelect v-model="status" class="category-filter__status" aria-label="启用状态" placeholder="状态：全部" clearable>
        <ElOption value="enabled" label="已启用" />
        <ElOption value="disabled" label="已停用" />
      </ElSelect>
      <ElInput
        v-model="keywordDraft"
        class="category-filter__search"
        aria-label="搜索任务分类"
        placeholder="搜索分类名称 / 描述"
        clearable
        @keydown.enter.prevent="applyKeyword"
        @clear="applyKeyword"
      >
        <template #prefix><Search :size="15" /></template>
      </ElInput>
      <ElButton type="primary" plain :icon="Search" data-testid="category-search" @click="applyKeyword">搜索</ElButton>
    </div>

    <section class="category-table-panel" aria-label="任务分类列表">
      <ElTable
        v-loading="loading"
        :data="paged"
        size="small"
        height="100%"
        row-key="id"
        element-loading-text="正在加载任务分类"
        data-testid="category-table"
      >
        <ElTableColumn label="分类名称" prop="name" min-width="150" show-overflow-tooltip />
        <ElTableColumn label="描述" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '—' }}</template>
        </ElTableColumn>
        <ElTableColumn label="排序" width="84">
          <template #default="{ row }"><span class="category-num">{{ row.sort_order }}</span></template>
        </ElTableColumn>
        <ElTableColumn label="启用" width="96">
          <template #default="{ row }">
            <ElTag size="small" :type="row.enabled ? 'success' : 'info'" :effect="row.enabled ? 'light' : 'plain'">{{ row.enabled ? '已启用' : '已停用' }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="任务 / 问题 Prompt" min-width="230">
          <template #default="{ row }">
            <ElSpace :size="6">
              <ElTag size="small" effect="plain" :type="row.task_prompt?.trim() ? 'success' : 'info'">任务 {{ row.task_prompt?.trim() ? '已配置' : '未配置' }}</ElTag>
              <ElTag size="small" effect="plain" :type="row.question_prompt?.trim() ? 'success' : 'info'">问题 {{ row.question_prompt?.trim() ? '已配置' : '未配置' }}</ElTag>
            </ElSpace>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="88" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <ElTooltip :content="row.enabled ? '停用该分类' : '启用该分类'" placement="top">
                <ElButton
                  text
                  type="primary"
                  :icon="row.enabled ? Pause : Play"
                  :aria-label="`${row.enabled ? '停用' : '启用'}分类 ${row.name}`"
                  :disabled="busyId === row.id"
                  data-testid="category-toggle"
                  @click="toggleEnabled(row as TaskCategory)"
                />
              </ElTooltip>
            </div>
          </template>
        </ElTableColumn>
        <template #empty>
          <ElEmpty v-if="error && !categories.length" :image-size="72" description="任务分类加载失败">
            <ElText size="small" type="info">{{ error }}</ElText>
            <ElButton :icon="RefreshCw" data-testid="category-empty-retry" @click="load">重新加载</ElButton>
          </ElEmpty>
          <ElEmpty v-else-if="!loading" :image-size="72" :description="categories.length ? '没有匹配的任务分类' : '暂无任务分类'">
            <ElText size="small" type="info">{{ categories.length ? '调整状态或搜索条件后重试。' : '任务分类用于给任务归类，创建后即可分配给数字员工。' }}</ElText>
          </ElEmpty>
        </template>
      </ElTable>
    </section>

    <footer class="category-page__footer">
      <ElText size="small" type="info" data-testid="category-total">共 {{ filtered.length }} 条</ElText>
      <ElPagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="filtered.length"
        layout="prev, pager, next"
        aria-label="任务分类分页"
        data-testid="category-pagination"
      />
    </footer>
  </div>
</template>

<script setup lang="ts">
import { Pause, Play, RefreshCw, Search } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElEmpty,
  ElInput,
  ElOption,
  ElPagination,
  ElSelect,
  ElSpace,
  ElTable,
  ElTableColumn,
  ElTag,
  ElText,
  ElTooltip,
  vLoading,
} from 'element-plus'
import { api } from '@/api/client'
import type { TaskCategory } from '@/api/types'
import { notify } from '@/composables/useToast'
import { useAstraStore } from '@/stores/astra'

const store = useAstraStore()
const pageSize = 10

const categories = ref<TaskCategory[]>([])
const loading = ref(false)
const error = ref('')
const busyId = ref('')
const status = ref('')
const keywordDraft = ref('')
const keyword = ref('')
const page = ref(1)

const filtered = computed(() => categories.value.filter((item) => {
  if (status.value && item.enabled !== (status.value === 'enabled')) return false
  const text = keyword.value.trim().toLowerCase()
  if (!text) return true
  return item.name.toLowerCase().includes(text) || (item.description ?? '').toLowerCase().includes(text)
}))
const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const paged = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))

async function load() {
  loading.value = true
  error.value = ''
  try {
    categories.value = await api.categories(true)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '任务分类加载失败'
  } finally {
    loading.value = false
  }
}

function applyKeyword() {
  keyword.value = keywordDraft.value
  page.value = 1
}

// 启停是列表级即时操作：只改 enabled 并立即落库，其余字段按服务端返回值原样带回。
async function toggleEnabled(row: TaskCategory) {
  if (busyId.value) return
  busyId.value = row.id
  try {
    await api.updateCategory(row.id, {
      name: row.name,
      description: row.description ?? '',
      enabled: !row.enabled,
      sort_order: row.sort_order,
      task_prompt: row.task_prompt,
      question_prompt: row.question_prompt,
    })
    await load()
    // 分类在任务、员工与自动分配里被引用，启停后同步刷新平台缓存。
    await store.refresh()
    notify(row.enabled ? '分类已停用' : '分类已启用')
  } catch (reason) {
    notify(reason instanceof Error ? reason.message : '操作失败', 'error')
  } finally {
    busyId.value = ''
  }
}

watch([status, keyword], () => { page.value = 1 })
watch(totalPages, (value) => { page.value = Math.min(page.value, value) })

onMounted(load)
</script>

<style scoped>
.category-page { display: flex; flex-direction: column; gap: 14px; height: calc(100vh - 69px); min-height: 620px; padding: 20px 24px 18px; overflow: hidden; }
.category-page__intro { display: flex; flex: none; align-items: flex-start; justify-content: space-between; gap: 16px; }
.category-page__intro h2 { margin: 0 0 2px; font-size: var(--astra-font-title); letter-spacing: -.02em; }
.category-filter { display: flex; flex: none; align-items: center; gap: 10px; }
.category-filter__status { flex: none; width: 148px; }
.category-filter__search { flex: 1; min-width: 210px; max-width: 320px; }
.category-table-panel { flex: 1 1 auto; min-height: 0; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 12px; background: var(--astra-bg-panel); box-shadow: var(--astra-shadow-panel); }
.category-num { font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.row-actions { display: flex; align-items: center; gap: 2px; }
.category-page__footer { display: flex; flex: none; align-items: center; justify-content: space-between; gap: 16px; }
@media (max-width: 900px) { .category-page { height: auto; min-height: calc(100vh - 69px); overflow: visible; } .category-table-panel { min-height: 480px; } }
</style>
