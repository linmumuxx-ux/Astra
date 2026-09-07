<template>
  <section class="library-stats" aria-label="数字图书馆统计">
    <button type="button" :class="{ active: active === 'all' }" @click="$emit('select', 'all')">
      <span><Files :size="18" /></span><div class="stat-copy"><small>知识页面</small><strong>{{ stats?.knowledge_pages ?? 0 }}</strong><em>正式知识总数</em></div>
    </button>
    <button type="button" :class="{ active: active === 'spaces' }" @click="$emit('select', 'spaces')">
      <span><LibraryBig :size="18" /></span><div class="stat-copy"><small>知识空间</small><strong>{{ stats?.knowledge_spaces ?? 0 }}</strong><em>共享知识目录</em></div>
    </button>
    <button type="button" :class="{ active: active === 'weekly' }" @click="$emit('select', 'weekly')">
      <span><Quote :size="18" /></span><div class="stat-copy"><small>本周引用次数</small><strong>{{ stats?.weekly_references ?? 0 }}</strong><em>实际进入员工上下文</em></div>
    </button>
    <button type="button" :class="{ active: active === 'published' }" @click="$emit('select', 'published')">
      <span><BadgeCheck :size="18" /></span><div class="stat-copy"><small>已发布经验</small><strong>{{ stats?.published_experiences ?? 0 }}</strong><em>已审核可复用经验</em></div>
    </button>
    <button type="button" data-tone="warning" :disabled="!canReview" :class="{ active: active === 'candidate' }" @click="$emit('select', 'candidate')">
      <span><ClipboardCheck :size="18" /></span><div class="stat-copy"><small>候选经验</small><strong>{{ stats?.candidate_experiences ?? 0 }}</strong><em>{{ canReview ? '等待审核处理' : '仅审核者可查看' }}</em></div>
    </button>
  </section>
</template>

<script setup lang="ts">
import { BadgeCheck, ClipboardCheck, Files, LibraryBig, Quote } from 'lucide-vue-next'
import type { LibraryStats } from '@/api/types'

defineProps<{ stats: LibraryStats | null; active: string; canReview: boolean }>()
defineEmits<{ select: [value: string] }>()
</script>

<style scoped>
.library-stats { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 10px; margin-bottom: 14px; }
.library-stats button { position: relative; display: flex; align-items: center; gap: 11px; min-height: 62px; padding: 10px 13px; text-align: left; border: 1px solid var(--astra-border); border-radius: 11px; background: rgba(255,255,255,.94); box-shadow: var(--astra-shadow-panel); cursor: pointer; transition: .16s ease; }
.library-stats button:hover:not(:disabled), .library-stats button.active { border-color: var(--astra-primary-border); }
.library-stats button.active::after { position: absolute; right: 10px; top: 10px; width: 6px; height: 6px; border-radius: 50%; background: var(--astra-primary); content: ''; }
.library-stats button:disabled { cursor: default; opacity: .72; }
.library-stats span { display: grid; flex: none; place-items: center; width: 34px; height: 34px; color: var(--astra-primary-bright); border-radius: 9px; background: var(--astra-primary-soft); }
.library-stats button[data-tone='warning'] span { color: var(--astra-warning); background: var(--astra-warning-soft); }
.library-stats .stat-copy { display: grid; min-width: 0; }
.library-stats small { color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.library-stats strong { color: var(--astra-text-primary); font: var(--astra-weight-bold) var(--astra-font-emphasis) var(--astra-font-display); line-height: 1.1; }
.library-stats em { overflow: hidden; margin-top: 1px; color: var(--astra-text-muted); font-size: var(--astra-font-micro); font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 1300px) { .library-stats { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 760px) { .library-stats { grid-template-columns: 1fr 1fr; } }
@media (max-width: 480px) { .library-stats { grid-template-columns: 1fr; } }
</style>
