<template>
  <div class="astra-filter" role="group" :aria-label="label" :data-testid="testid">
    <div class="astra-filter__fields">
      <slot />
    </div>
    <div v-if="$slots.search" class="astra-filter__search">
      <slot name="search" />
    </div>
  </div>
</template>

<script setup lang="ts">
// 所有带查询功能页面的筛选面板。左侧插槽放业务筛选下拉（.astra-filter__select），
// search 插槽放关键词输入（.astra-filter__keyword）与搜索按钮，由 .astra-filter__search
// 通过 margin-left: auto 整体靠右。样式全部来自 styles/page-layout.css。
defineProps<{ label: string; testid?: string }>()
</script>
