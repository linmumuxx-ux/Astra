<template>
  <div class="astra-page" data-testid="intervention-page">
    <AstraPageHeader title="待处理" description="处理需要人工介入或继续执行的任务。" testid="intervention-header">
      <template #actions>
        <ElButton :icon="RefreshCw" :loading="store.loading" data-testid="intervention-refresh" @click="store.refresh()">刷新</ElButton>
      </template>
    </AstraPageHeader>

    <AstraFilterPanel label="待处理筛选" testid="intervention-filter">
      <ElButton
        v-for="state in states"
        :key="state"
        :type="selected === state ? 'primary' : undefined"
        :data-testid="`intervention-state-${state}`"
        @click="selected = state"
      >{{ runtimeStatusLabel(state) }} · {{ countOf(state) }}</ElButton>
    </AstraFilterPanel>

    <section class="astra-table-panel">
      <ElTable v-loading="store.loading" :data="tasks" height="100%" row-key="id">
        <ElTableColumn label="任务" min-width="260">
          <template #default="{ row }">
            <div class="intervention-task">
              <strong>{{ row.title }}</strong>
              <ElText type="info" truncated>{{ row.runtime_error || row.failure_reason || row.current_progress || '—' }}</ElText>
            </div>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="140">
          <template #default="{ row }"><RuntimeStatusBadge :projection="row as Task" :show-detail="false" /></template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <ElSpace class="astra-row-actions" :size="4">
              <ElTooltip content="进入任务详情" placement="top">
                <ElButton circle type="primary" :icon="ExternalLink" :aria-label="`进入 ${row.id} 任务详情`" @click="openTask(row as Task)" />
              </ElTooltip>
            </ElSpace>
          </template>
        </ElTableColumn>
        <template #empty>
          <ElEmpty v-if="!store.loading" :image-size="72" description="当前没有待处理任务" />
        </template>
      </ElTable>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ExternalLink, RefreshCw } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElButton, ElEmpty, ElSpace, ElTable, ElTableColumn, ElText, ElTooltip, vLoading } from 'element-plus'
import type { Task } from '@/api/types'
import AstraFilterPanel from '@/components/astra/AstraFilterPanel.vue'
import AstraPageHeader from '@/components/astra/AstraPageHeader.vue'
import RuntimeStatusBadge from '@/components/runtime/RuntimeStatusBadge.vue'
import { runtimeStatusLabel } from '@/features/runtime/status'
import { useAstraStore } from '@/stores/astra'

const store = useAstraStore()
const router = useRouter()
const states = ['WAITING', 'FAILED'] as const
const selected = ref<string>('WAITING')
const tasks = computed(() => store.tasks.filter((task) => task.status === selected.value))
const countOf = (state: string) => store.tasks.filter((task) => task.status === state).length
const openTask = (task: Task) => router.push(`/tasks/${task.id}`)
onMounted(() => { void store.refresh() })
</script>

<style scoped>
/* 页面骨架、标题区、筛选面板与表格面板统一走 styles/page-layout.css。 */
.intervention-task { display: grid; gap: 2px; min-width: 0; }
.intervention-task strong { overflow: hidden; color: var(--astra-text-primary); font-size: var(--astra-font-label); text-overflow: ellipsis; white-space: nowrap; }
</style>
