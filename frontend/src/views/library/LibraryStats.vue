<template>
  <section class="library-stats" aria-label="数字图书馆统计">
    <button type="button" :class="{ active: active === 'all' }" @click="$emit('select', 'all')">
      <span><Files :size="18" /></span><small>知识页面</small><strong>{{ stats?.knowledge_pages ?? 0 }}</strong><em>正式知识总数</em>
    </button>
    <button type="button" :class="{ active: active === 'spaces' }" @click="$emit('select', 'spaces')">
      <span><LibraryBig :size="18" /></span><small>知识空间</small><strong>{{ stats?.knowledge_spaces ?? 0 }}</strong><em>共享知识目录</em>
    </button>
    <button type="button" :class="{ active: active === 'weekly' }" @click="$emit('select', 'weekly')">
      <span><Quote :size="18" /></span><small>本周引用次数</small><strong>{{ stats?.weekly_references ?? 0 }}</strong><em>实际进入员工上下文</em>
    </button>
    <button type="button" :class="{ active: active === 'published' }" @click="$emit('select', 'published')">
      <span><BadgeCheck :size="18" /></span><small>已发布经验</small><strong>{{ stats?.published_experiences ?? 0 }}</strong><em>已审核可复用经验</em>
    </button>
    <button type="button" data-tone="warning" :disabled="!canReview" :class="{ active: active === 'candidate' }" @click="$emit('select', 'candidate')">
      <span><ClipboardCheck :size="18" /></span><small>候选经验</small><strong>{{ stats?.candidate_experiences ?? 0 }}</strong><em>{{ canReview ? '等待审核处理' : '仅审核者可查看' }}</em>
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
.library-stats { display: grid; grid-template-columns: repeat(5, minmax(150px, 1fr)); gap: 12px; margin-bottom: 16px; }
.library-stats button { position: relative; display: grid; grid-template-columns: 42px 1fr; grid-template-rows: auto auto auto; gap: 1px 11px; min-height: 118px; padding: 15px 16px; text-align: left; border: 1px solid var(--astra-border); border-radius: 12px; background: rgba(255,255,255,.94); box-shadow: var(--astra-shadow-panel); cursor: pointer; transition: .16s ease; }
.library-stats button:hover:not(:disabled), .library-stats button.active { border-color: var(--astra-primary-border); transform: translateY(-1px); }
.library-stats button.active::after { position: absolute; right: 12px; top: 12px; width: 7px; height: 7px; border-radius: 50%; background: var(--astra-primary); content: ''; }
.library-stats button:disabled { cursor: default; opacity: .72; }
.library-stats span { grid-row: 1 / 4; display: grid; place-items: center; width: 40px; height: 40px; color: var(--astra-primary-bright); border-radius: 10px; background: var(--astra-primary-soft); }
.library-stats button[data-tone='warning'] span { color: var(--astra-warning); background: var(--astra-warning-soft); }
.library-stats small { align-self: end; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.library-stats strong { color: var(--astra-text-primary); font: 700 28px var(--astra-font-display); line-height: 1.08; }
.library-stats em { overflow: hidden; color: var(--astra-text-muted); font-size: 12px; font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 1300px) { .library-stats { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 760px) { .library-stats { grid-template-columns: 1fr 1fr; } }
@media (max-width: 480px) { .library-stats { grid-template-columns: 1fr; } }
</style>
