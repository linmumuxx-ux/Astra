<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { mutate, useResource } from '../api'
import type { Detail } from '../types'
import { date } from '../format'
import ResourceState from './ResourceState.vue'
const props = defineProps<{ employeeId: string; active: boolean }>()
type Memory = { content?: string; notes?: Record<string,string>; source_refs?: string[]; memory_head?: string | null; head?: string; reason?: string; created_at?: number; expires_at?: number | null; expired?: boolean; configured?: boolean }
const memory = useResource<Memory>(() => `/employees/${props.employeeId}/memory`, {})
const history = useResource<Memory[]>(() => memory.data.value.configured ? `/employees/${props.employeeId}/memory/history` : '', [])
const previous = ref('')
const difference = useResource<Detail>(() => previous.value ? `/employees/${props.employeeId}/memory/diff?previous=${encodeURIComponent(previous.value)}` : '', {})
const open = ref(false), saving = ref(false), error = ref('')
const content = ref(''), notes = ref('{}'), sources = ref(''), reason = ref(''), expires = ref<string | null>(null), expectedHead = ref<string | null>(null)
const versions = computed(() => history.data.value.filter(item => item.head !== memory.data.value.memory_head))
watch(() => props.employeeId, () => { previous.value = ''; open.value = false })
function edit(version: Memory = memory.data.value) {
  expectedHead.value = memory.data.value.memory_head || null; content.value = version.content || ''; notes.value = JSON.stringify(version.notes || {}, null, 2)
  sources.value = (version.source_refs || []).join('\n'); reason.value = version.head ? `恢复记忆版本 ${version.head}` : ''; expires.value = version.expires_at ? String(version.expires_at * 1000) : null
  error.value = ''; open.value = true
}
async function save() {
  saving.value = true; error.value = ''
  try {
    const parsed = JSON.parse(notes.value)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || Object.values(parsed).some(value => typeof value !== 'string')) throw new Error('详细笔记须为文件名与文本的 JSON 对象')
    await mutate(`/employees/${props.employeeId}/memory`, { expected_head: expectedHead.value, content: content.value, notes: parsed, source_refs: sources.value.split('\n').map(item => item.trim()).filter(Boolean), reason: reason.value, expires_at: expires.value ? Math.floor(Number(expires.value) / 1000) : null })
    open.value = false; previous.value = ''; ElMessage.success('已保存个人记忆新版本')
  } catch (caught) { error.value = (caught as Error).message } finally { saving.value = false }
}
</script>
<template>
  <h3>连续工作记忆</h3>
  <ResourceState :loading="memory.loading.value" :error="memory.error.value" @retry="memory.load">
    <el-alert v-if="memory.data.value.expired" title="这份记忆已过期，请依据最新来源确认或纠正。" type="warning" :closable="false"/>
    <pre v-if="memory.data.value.content" class="memory-content">{{ memory.data.value.content }}</pre>
    <el-empty v-else :description="memory.data.value.configured === false ? '个人记忆存储尚未配置' : '尚未形成个人记忆'" :image-size="50"/>
    <p v-if="memory.data.value.memory_head" class="caption">当前版本 {{ memory.data.value.memory_head }} · {{ date(memory.data.value.created_at) }}</p>
    <div v-for="(text,name) in memory.data.value.notes" :key="name" class="mini-card"><strong>{{ name }}</strong><pre class="memory-content">{{ text }}</pre></div>
    <p v-for="source in memory.data.value.source_refs" :key="source" class="caption">来源 {{ source }}</p>
    <el-button v-if="active && memory.data.value.configured" @click="edit()">编辑个人记忆</el-button>
  </ResourceState>
  <div v-if="memory.data.value.configured" class="divider"></div>
  <ResourceState v-if="memory.data.value.configured" :loading="history.loading.value" :error="history.error.value" @retry="history.load">
    <h3>纠错与历史</h3>
    <el-select v-model="previous" aria-label="记忆对比版本" placeholder="选择历史版本对比" clearable filterable><el-option v-for="version in versions" :key="version.head" :label="`${version.head?.slice(0,8)} · ${version.reason}`" :value="version.head!"/></el-select>
    <ResourceState v-if="previous" :loading="difference.loading.value" :error="difference.error.value" @retry="difference.load"><pre class="code-block">{{ difference.data.value.diff }}</pre><el-button :disabled="!active" @click="edit(versions.find(item => item.head === previous))">将此版本载入编辑</el-button></ResourceState>
  </ResourceState>
  <p class="caption">个人记忆保留判断和来源。岗位、授权、目标和任务状态由业务记录决定。</p>
  <el-dialog v-model="open" title="编辑个人记忆" width="min(640px, 94vw)" destroy-on-close>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item label="短核心记忆" required><el-input v-model="content" aria-label="短核心记忆" type="textarea" :rows="5" maxlength="16000"/></el-form-item>
      <el-form-item label="详细笔记 JSON"><el-input v-model="notes" aria-label="详细笔记 JSON" type="textarea" :rows="3" placeholder='{"release.md":"工作笔记"}'/><p class="caption">文件名使用小写字母、数字、下划线或连字符，以 .md 结尾。</p></el-form-item>
      <el-form-item label="来源引用（每行一项）" required><el-input v-model="sources" aria-label="记忆来源引用" type="textarea" :rows="3" placeholder="tasks/对象ID 或 messages/对象ID 或 source-events/对象ID"/></el-form-item>
      <el-form-item label="修改原因" required><el-input v-model="reason" aria-label="记忆修改原因"/></el-form-item>
      <el-form-item label="过期提醒"><el-date-picker v-model="expires" type="datetime" value-format="x" aria-label="记忆过期时间" clearable/></el-form-item>
    </el-form>
    <template #footer><el-button @click="open = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!reason.trim() || !sources.trim()" @click="save">保存记忆版本</el-button></template>
  </el-dialog>
</template>
