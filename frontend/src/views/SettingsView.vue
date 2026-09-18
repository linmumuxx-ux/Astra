<template>
  <div class="page settings-page" data-testid="settings-page">
    <section class="page-intro compact-intro">
      <div><h2>配置中心</h2><p>管理任务分类、任务来源和平台设置；数字员工请在「数字员工」页面维护。</p></div>
      <span class="config-mode"><LockKeyhole :size="13" /> 远程密码不会回显</span>
    </section>

    <nav class="settings-tabs">
      <button v-for="item in tabs" :key="item.id" :class="{ active: tab === item.id }" @click="switchTab(item.id)"><component :is="item.icon" :size="14" />{{ item.label }}</button>
    </nav>

    <section v-if="tab === 'categories'"><div class="config-tab"><CategoryConfig ref="categoryRef" /></div></section>
    <section v-else-if="tab === 'sources'"><div class="config-tab"><SourceConfig /></div></section>
    <section v-else><SystemSettings ref="systemRef" /></section>
  </div>
</template>

<script setup lang="ts">
import { Database, FolderTree, LockKeyhole, SlidersHorizontal } from 'lucide-vue-next'
import { onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import CategoryConfig from '@/views/settings/CategoryConfig.vue'
import SourceConfig from '@/views/settings/SourceConfig.vue'
import SystemSettings from '@/views/settings/SystemSettings.vue'

const route = useRoute(); const router = useRouter()
const tab = ref('categories')
const categoryRef = ref<InstanceType<typeof CategoryConfig> | null>(null)
const systemRef = ref<InstanceType<typeof SystemSettings> | null>(null)

const tabs = [
  { id: 'categories', label: '任务分类', icon: FolderTree },
  { id: 'sources', label: '任务来源', icon: Database },
  { id: 'system', label: '系统设置', icon: SlidersHorizontal },
]

function switchTab(next: string) {
  if (next === tab.value) return
  if (tab.value === 'categories' && categoryRef.value?.getDirty() && !window.confirm('有未保存的任务分类修改，确定放弃并切换吗？')) return
  tab.value = next
  router.replace({ query: { ...route.query, tab: next } })
}

onMounted(() => {
  const tabFromQuery = typeof route.query.tab === 'string' ? route.query.tab : 'categories'
  if (tabs.some((item) => item.id === tabFromQuery)) tab.value = tabFromQuery
})

onBeforeRouteLeave(() => {
  if (tab.value === 'categories' && categoryRef.value?.getDirty()) return window.confirm('有未保存的任务分类修改，确定离开吗？')
  return true
})
</script>

<style scoped>
.settings-page { padding-bottom: 96px; }
.config-tab { max-width: 1080px; }
</style>