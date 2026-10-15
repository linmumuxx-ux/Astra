<template>
  <header class="astra-page-header" :data-testid="testid">
    <div class="astra-page-header__lead">
      <h2 class="astra-page-header__title">{{ title }}</h2>
      <p v-if="description" class="astra-page-header__desc">{{ description }}</p>
      <div v-if="$slots.default" class="astra-page-header__meta">
        <slot />
      </div>
    </div>
    <div class="astra-page-header__actions" :data-testid="testid ? `${testid}-actions` : undefined">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup lang="ts">
// 所有管理页的标题区。样式全部来自 styles/page-layout.css 的 .astra-page-header，
// 组件自身不写 style —— 标题字号、按钮高度与上下留白只在这一层定义一次。
defineProps<{ title: string; description?: string; testid?: string }>()
</script>
