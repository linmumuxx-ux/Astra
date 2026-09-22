<template>
  <Teleport to="body">
    <div v-if="open" class="editor-backdrop">
      <form class="knowledge-editor" role="dialog" aria-modal="true" aria-labelledby="knowledge-editor-title" @submit.prevent="save">
        <header><div><h3 id="knowledge-editor-title">新建知识</h3><p>知识先保存为草稿，经审核发布后才对数字员工可见。</p></div><button type="button" aria-label="关闭" @click="requestClose"><X :size="18" /></button></header>
        <div class="editor-body">
          <div class="editor-grid"><label>知识标题 *<input v-model.trim="form.title" required maxlength="240" placeholder="请输入清晰、可检索的知识标题" /></label><label>所属目录 *<select v-model="form.space_id" required><option value="" disabled>请选择</option><option v-for="dir in directories" :key="dir.id" :value="dir.id">{{ dir.name }}</option></select></label></div>
          <div class="editor-grid editor-grid--three"><label>知识类型<select v-model="form.type"><option v-for="item in types" :key="item.value" :value="item.value">{{ item.label }}</option></select></label><label>验证状态<select v-model="form.verification_status"><option value="unverified">未验证</option><option value="verified">已验证</option><option value="failed">验证失败</option></select></label><label>标签<input v-model="form.tags" placeholder="用逗号分隔" /></label></div>
          <label>摘要<textarea v-model.trim="form.summary" rows="2" maxlength="4000" placeholder="用于列表与搜索结果的简短说明" /></label>
          <label class="markdown-field"><span>Markdown 正文 *<label class="file-button"><Upload :size="13" />导入 .md<input type="file" accept=".md,text/markdown,text/plain" @change="readMarkdown" /></label></span><textarea v-model="form.content_md" required rows="16" placeholder="## 问题现象\n\n说明知识内容……" /></label>
          <p v-if="error" class="editor-error">{{ error }}</p>
        </div>
        <footer><button type="button" class="button" :disabled="saving" @click="requestClose">取消</button><button class="button button--primary" :disabled="saving"><LoaderCircle v-if="saving" :size="14" class="spin" />保存草稿</button></footer>
      </form>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { LoaderCircle, Upload, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { confirmDialog } from '@/composables/useConfirm'


const props = defineProps<{ open: boolean; directories: Array<{ id: string; name: string; level: number }>; saving: boolean; error: string; initialContent?: string; initialTitle?: string; initialSpaceId?: string }>()
const emit = defineEmits<{ close: []; save: [payload: Record<string, unknown>] }>()
const types = [{ value: 'document', label: '文档' }, { value: 'rule', label: '规范' }, { value: 'guide', label: '指南' }, { value: 'experience', label: '经验' }, { value: 'faq', label: 'FAQ' }, { value: 'tool', label: '工具' }, { value: 'example', label: '示例' }]
const form = reactive({ space_id: '', title: '', type: 'document', verification_status: 'unverified', tags: '', summary: '', content_md: '' })
const snapshot = ref('')
const dirty = computed(() => JSON.stringify(form) !== snapshot.value)
let previousOverflow = ''
watch(() => props.open, (open) => {
  if (open) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    Object.assign(form, { space_id: props.initialSpaceId || props.directories[0]?.id || '', title: props.initialTitle ?? '', type: 'document', verification_status: 'unverified', tags: '', summary: '', content_md: props.initialContent ?? '' })
    snapshot.value = JSON.stringify(form)
  } else {
    document.body.style.overflow = previousOverflow
  }
})
onBeforeUnmount(() => { document.body.style.overflow = previousOverflow })
async function requestClose() {
  if (props.saving) return
  if (dirty.value) {
    const confirmed = await confirmDialog({ title: '放弃未保存的知识草稿？', message: '编辑内容尚未保存，关闭后将无法恢复。', confirmLabel: '放弃并关闭', danger: true })
    if (!confirmed) return
  }
  emit('close')
}
function save() { emit('save', { ...form, tags: form.tags.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean) }) }
async function readMarkdown(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  form.content_md = await file.text()
  if (!form.title) form.title = file.name.replace(/\.md$/i, '')
}
</script>

<style scoped>
.editor-backdrop { position: fixed; z-index: 1200; inset: 0; display: grid; place-items: center; padding: 20px; background: rgba(16,37,34,.38); backdrop-filter: blur(2px); }.knowledge-editor { display: grid; grid-template-rows: auto minmax(0,1fr) auto; width: min(860px,100%); max-height: 86vh; overflow: hidden; border: 1px solid var(--astra-border); border-radius: 15px; background: white; box-shadow: 0 24px 70px rgba(16,37,34,.22); }.knowledge-editor>header { display:flex;align-items:center;justify-content:space-between;gap:16px;padding:17px 20px;border-bottom:1px solid var(--astra-border) }.knowledge-editor h3,.knowledge-editor p{margin:0}.knowledge-editor h3{color:var(--astra-text-primary);}.knowledge-editor header p{margin-top:4px;color:var(--astra-text-muted);font-size:var(--astra-font-helper)}.knowledge-editor header>button{display:grid;place-items:center;width:34px;height:34px;color:var(--astra-text-muted);border:0;border-radius:8px;background:#f3f7f5;cursor:pointer}
.editor-body { display:grid;gap:14px;overflow-y:auto;padding:18px 20px }.editor-grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(180px,.7fr);gap:12px}.editor-grid--three{grid-template-columns:repeat(3,1fr)}.editor-body label{display:grid;gap:6px;color:var(--astra-text-secondary);font-size:var(--astra-font-body)}.editor-body input,.editor-body select,.editor-body textarea{width:100%;padding:9px 10px;color:var(--astra-text-primary);border:1px solid var(--astra-border);border-radius:8px;background:white;font:inherit;outline:none}.editor-body input,.editor-body select{height:40px}.editor-body input:focus,.editor-body select:focus,.editor-body textarea:focus{border-color:var(--astra-primary-border);box-shadow:0 0 0 3px var(--astra-primary-soft)}.markdown-field>span{display:flex;align-items:center;justify-content:space-between}.file-button{display:inline-flex!important;align-items:center;gap:5px;padding:5px 8px;color:var(--astra-primary-bright)!important;border:1px solid var(--astra-primary-border);border-radius:7px;background:var(--astra-primary-soft);cursor:pointer}.file-button input{display:none}.markdown-field textarea{min-height:300px;resize:vertical;font-family:var(--astra-font-family);font-size:var(--astra-font-body);line-height:1.55}.editor-error{padding:9px 11px;color:var(--astra-danger);border-radius:8px;background:var(--astra-danger-soft);font-size:var(--astra-font-body)}.knowledge-editor>footer{display:flex;justify-content:flex-end;gap:8px;padding:13px 20px;border-top:1px solid var(--astra-border);background:#fbfdfc}
@media(max-width:700px){.editor-grid,.editor-grid--three{grid-template-columns:1fr}.knowledge-editor{max-height:94vh}.editor-backdrop{padding:8px}}
</style>
