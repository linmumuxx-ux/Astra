<template>
  <section class="usage-summary">
    <header role="button" tabindex="0" @click="collapsed = !collapsed" @keydown.enter="collapsed = !collapsed">
      <div><h3>知识使用情况</h3><p>最近 {{ summary?.days ?? 7 }} 天，引用指 Agent 读取完整知识正文</p></div>
      <span class="collapse-toggle"><ChevronDown :size="16" :class="{ open: !collapsed }" /></span>
    </header>
    <div v-if="!collapsed" class="usage-summary__body">
      <div class="usage-kpis">
        <article><span><Quote :size="16" /></span><small>总引用次数</small><strong>{{ summary?.total_references ?? 0 }}</strong></article>
        <article><span><BookOpen :size="16" /></span><small>使用知识数</small><strong>{{ summary?.used_resources ?? 0 }}</strong></article>
        <article><span><LibraryBig :size="16" /></span><small>反馈次数</small><strong class="text-value">{{ summary?.feedback_count ?? 0 }}</strong></article>
      </div>
      <div class="top-knowledge">
        <h4>最常引用知识 TOP3</h4>
        <ol v-if="summary?.top_knowledge.length"><li v-for="item in summary.top_knowledge" :key="item.resource_id"><span>{{ item.title }}</span><strong>{{ item.reference_count }} 次</strong></li></ol>
        <p v-else>暂无知识引用记录</p>
      </div>
      <div class="usage-trend" aria-label="近七日知识引用趋势">
        <h4>引用趋势</h4>
        <div><span v-for="point in summary?.trend ?? []" :key="point.date" :title="`${point.date}：${point.reference_count} 次`"><i :style="{ height: `${barHeight(point.reference_count)}%` }" /><small>{{ point.date.slice(5) }}</small></span></div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { BookOpen, ChevronDown, LibraryBig, Quote } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import type { LibraryUsageSummary } from '@/api/types'

const props = defineProps<{ summary: LibraryUsageSummary | null }>()
const collapsed = ref(false)
const maximum = computed(() => Math.max(1, ...(props.summary?.trend.map((point) => point.reference_count) ?? [0])))
const barHeight = (value: number) => value ? Math.max(12, Math.round(value / maximum.value * 100)) : 4
</script>

<style scoped>
.usage-summary { margin-top: 16px; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 12px; background: rgba(255,255,255,.92); box-shadow: var(--astra-shadow-panel); }.usage-summary > header { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 66px; padding: 13px 16px; border-bottom: 1px solid var(--astra-border); cursor: pointer; }.usage-summary h3,.usage-summary p,.usage-summary h4 { margin: 0; }.usage-summary h3 { color: var(--astra-text-primary);  }.usage-summary header p { margin-top: 4px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }.collapse-toggle { display: grid; place-items: center; color: var(--astra-text-muted); }.collapse-toggle svg { transition: transform .18s ease; }.collapse-toggle svg.open { transform: rotate(180deg); }
.usage-summary__body { display: grid; grid-template-columns: 1.1fr 1fr 1.25fr; gap: 0; min-height: 150px; }.usage-summary__body > div { padding: 15px 18px; }.usage-summary__body > div + div { border-left: 1px solid var(--astra-border); }
.usage-kpis { display: grid; grid-template-columns: repeat(3,1fr); gap: 8px; }.usage-kpis article { display: grid; align-content: center; min-width: 0; padding: 9px; border-radius: 9px; background: #f5f9f7; }.usage-kpis span { display: grid; place-items: center; width: 29px; height: 29px; color: var(--astra-primary-bright); border-radius: 8px; background: var(--astra-primary-soft); }.usage-kpis small { margin-top: 6px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }.usage-kpis strong { margin-top: 2px; color: var(--astra-text-primary); font: var(--astra-weight-bold) var(--astra-font-kpi) var(--astra-font-display); }.usage-kpis .text-value { overflow: hidden; font-size: var(--astra-font-emphasis); line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.top-knowledge h4,.usage-trend h4 { color: var(--astra-text-secondary); font-size: var(--astra-font-label); }.top-knowledge ol { display: grid; gap: 5px; margin: 10px 0 0; padding: 0; list-style: none; counter-reset: item; }.top-knowledge li { display: grid; grid-template-columns: 24px minmax(0,1fr) auto; align-items: center; gap: 7px; min-height: 29px; color: var(--astra-text-secondary); font-size: var(--astra-font-body); counter-increment: item; }.top-knowledge li::before { display: grid; place-items: center; width: 22px; height: 22px; color: var(--astra-primary-bright); border-radius: 6px; background: var(--astra-primary-soft); content: counter(item); }.top-knowledge li span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.top-knowledge li strong { color: var(--astra-text-muted); font-weight: var(--astra-weight-bold); }.top-knowledge p { margin-top: 18px; color: var(--astra-text-muted); font-size: var(--astra-font-body); }
.usage-trend > div { display: flex; align-items: end; gap: 7px; height: 99px; margin-top: 8px; }.usage-trend span { display: grid; grid-template-rows: 68px 18px; align-items: end; flex: 1; height: 91px; text-align: center; }.usage-trend i { display: block; min-height: 3px; border-radius: 4px 4px 2px 2px; background: linear-gradient(180deg,#24c47d,#0d9e61); }.usage-trend small { color: var(--astra-text-muted); font-size: var(--astra-font-micro); }
@media(max-width:1100px){.usage-summary__body{grid-template-columns:1fr 1fr}.usage-trend{grid-column:1/-1;border-left:0!important;border-top:1px solid var(--astra-border)}}
@media(max-width:700px){.usage-summary__body{grid-template-columns:1fr}.usage-summary__body>div+div{border-left:0;border-top:1px solid var(--astra-border)}.usage-trend{grid-column:auto}}
</style>
