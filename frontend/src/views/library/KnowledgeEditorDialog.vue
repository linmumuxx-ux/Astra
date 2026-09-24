<template>
  <el-dialog
    :model-value="open"
    title="新建知识"
    width="min(860px, calc(100vw - 32px))"
    top="7vh"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="!saving"
    :before-close="handleBeforeClose"
    append-to-body
    lock-scroll
    destroy-on-close
    class="knowledge-editor-dialog"
  >
    <p class="astra-dialog-subtitle">知识先保存为草稿，经审核发布后才对数字员工可见。</p>

    <form id="knowledge-editor-form" class="editor-body" @submit.prevent="save">
      <div class="editor-grid">
        <label>知识标题 *<el-input v-model="form.title" required maxlength="240" show-word-limit placeholder="请输入清晰、可检索的知识标题" /></label>
        <label>所属目录 *
          <el-select v-model="form.space_id" placeholder="请选择">
            <el-option v-for="dir in directories" :key="dir.id" :label="dir.name" :value="dir.id" />
          </el-select>
        </label>
      </div>

      <div class="editor-grid editor-grid--three">
        <label>知识类型
          <el-select v-model="form.type">
            <el-option v-for="item in types" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </label>
        <label>验证状态
          <el-select v-model="form.verification_status">
            <el-option label="未验证" value="unverified" />
            <el-option label="已验证" value="verified" />
            <el-option label="验证失败" value="failed" />
          </el-select>
        </label>
        <label>标签<el-input v-model="form.tags" placeholder="用逗号分隔" /></label>
      </div>

      <label>摘要
        <el-input v-model="form.summary" type="textarea" :rows="2" maxlength="4000" show-word-limit resize="vertical" placeholder="用于列表与搜索结果的简短说明" />
      </label>

      <label class="markdown-field">
        <span>
          Markdown 正文 *
          <label class="file-button"><Upload :size="13" />导入 .md<input type="file" accept=".md,text/markdown,text/plain" @change="readMarkdown" /></label>
        </span>
        <el-input v-model="form.content_md" type="textarea" :rows="16" resize="vertical" required placeholder="## 问题现象\n\n说明知识内容……" />
      </label>

      <p v-if="error" class="editor-error">{{ error }}</p>
    </form>

    <template #footer>
      <el-button :disabled="saving" @click="requestClose">取消</el-button>
      <el-button type="primary" native-type="submit" form="knowledge-editor-form" :loading="saving" :disabled="saving">保存草稿</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { Upload } from 'lucide-vue-next'
import { computed, reactive, ref, watch } from 'vue'
import { confirmDialog } from '@/composables/useConfirm'

const props = defineProps<{
  open: boolean
  directories: Array<{ id: string; name: string; level: number }>
  saving: boolean
  error: string
  initialContent?: string
  initialTitle?: string
  initialSpaceId?: string
}>()
const emit = defineEmits<{ close: []; save: [payload: Record<string, unknown>] }>()

const types = [
  { value: 'document', label: '文档' },
  { value: 'rule', label: '规范' },
  { value: 'guide', label: '指南' },
  { value: 'experience', label: '经验' },
  { value: 'faq', label: 'FAQ' },
  { value: 'tool', label: '工具' },
  { value: 'example', label: '示例' },
]

const form = reactive({
  space_id: '',
  title: '',
  type: 'document',
  verification_status: 'unverified',
  tags: '',
  summary: '',
  content_md: '',
})
const snapshot = ref('')
const dirty = computed(() => JSON.stringify(form) !== snapshot.value)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    Object.assign(form, {
      space_id: props.initialSpaceId || props.directories[0]?.id || '',
      title: props.initialTitle ?? '',
      type: 'document',
      verification_status: 'unverified',
      tags: '',
      summary: '',
      content_md: props.initialContent ?? '',
    })
    snapshot.value = JSON.stringify(form)
  },
)

async function canClose(): Promise<boolean> {
  if (props.saving) return false
  if (!dirty.value) return true
  return confirmDialog({
    title: '放弃未保存的知识草稿？',
    message: '编辑内容尚未保存，关闭后将无法恢复。',
    confirmLabel: '放弃并关闭',
    danger: true,
  })
}

async function requestClose() {
  if (await canClose()) emit('close')
}

async function handleBeforeClose(done: () => void) {
  if (!(await canClose())) return
  emit('close')
  done()
}

function save() {
  emit('save', {
    ...form,
    title: form.title.trim(),
    summary: form.summary.trim(),
    tags: form.tags.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean),
  })
}

async function readMarkdown(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  form.content_md = await file.text()
  if (!form.title) form.title = file.name.replace(/\.md$/i, '')
}
</script>

<style scoped>
.editor-body { display: grid; gap: 14px; max-height: 64vh; overflow-y: auto; padding-right: 2px; }
.editor-grid { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(180px, .7fr); gap: 12px; }
.editor-grid--three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.editor-body label { display: grid; gap: 6px; color: var(--astra-text-secondary); font-size: var(--astra-font-body); }
.editor-body :deep(.el-select) { width: 100%; }
.markdown-field > span { display: flex; align-items: center; justify-content: space-between; }
.file-button { display: inline-flex !important; align-items: center; gap: 5px; padding: 5px 8px; color: var(--astra-primary-bright) !important; border: 1px solid var(--astra-primary-border); border-radius: 7px; background: var(--astra-primary-soft); cursor: pointer; }
.file-button input { display: none; }
.markdown-field :deep(textarea) { min-height: 300px; font-family: var(--astra-font-family); font-size: var(--astra-font-body); line-height: 1.55; }
.editor-error { margin: 0; padding: 9px 11px; color: var(--astra-danger); border-radius: 8px; background: var(--astra-danger-soft); font-size: var(--astra-font-body); }
@media (max-width: 700px) {
  .editor-grid, .editor-grid--three { grid-template-columns: 1fr; }
  .editor-body { max-height: 72vh; }
}
</style>
