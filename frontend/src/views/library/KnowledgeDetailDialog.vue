<template>
  <Teleport to="body">
    <div v-if="open" class="detail-backdrop" data-testid="knowledge-detail-dialog" @click.self="$emit('close')">
      <article v-if="detail" class="knowledge-detail" role="dialog" aria-modal="true" :aria-labelledby="`knowledge-${detail.id}`">
        <header>
          <div class="detail-heading">
            <div><span class="detail-type">{{ typeLabel(detail.type) }}</span><span v-for="tag in detail.tags" :key="tag" class="detail-tag">{{ tag }}</span></div>
            <h2 :id="`knowledge-${detail.id}`">{{ detail.title }}</h2>
            <div class="detail-meta">
              <span :data-status="detail.status"><CircleCheck v-if="detail.status === 'published'" :size="14" /><Clock3 v-else :size="14" />{{ statusLabel(detail.status) }}</span>
              <span :data-verified="detail.verification_status"><BadgeCheck :size="14" />{{ verificationLabel(detail.verification_status) }}</span>
              <RouterLink v-if="detail.source_task_id" :to="`/tasks/${detail.source_task_id}`" @click="$emit('close')">来源任务：{{ detail.source_task_id }}</RouterLink>
              <span>更新：{{ formatDate(detail.updated_at) }}</span><span>引用：{{ detail.reference_count }}</span>
            </div>
          </div>
          <button type="button" aria-label="关闭知识详情" @click="$emit('close')"><X :size="19" /></button>
        </header>

        <div class="detail-scroll">
          <section v-if="detail.status === 'candidate'" class="candidate-origin">
            <div class="section-title"><span><Sparkles :size="16" /></span><div><h3>候选经验</h3><p>来自数字员工任务执行现场，发布前需核对结论与证据。</p></div></div>
            <dl class="origin-facts">
              <div><dt>来源员工</dt><dd>{{ detail.source_employee_name || detail.source_employee_id || '—' }}</dd></div>
              <div><dt>来源任务</dt><dd>{{ detail.source_task_id || '—' }}</dd></div>
              <div><dt>Run</dt><dd>{{ detail.source_run_id || '—' }}</dd></div>
              <div><dt>执行时间</dt><dd>{{ experienceValue(['task_executed_at', 'executed_at']) }}</dd></div>
              <div><dt>处理前</dt><dd>{{ experienceValue(['before_status', 'status_before', 'problem_symptom']) }}</dd></div>
              <div><dt>处理后</dt><dd>{{ experienceValue(['after_status', 'status_after', 'retry_result', 'run_status']) }}</dd></div>
              <div><dt>验证次数</dt><dd>{{ experienceValue(['verification_count', 'retry_count']) }}</dd></div>
              <div><dt>验证结果</dt><dd>{{ experienceValue(['verification_passed', 'verification_result']) }}</dd></div>
            </dl>
            <div v-if="detail.review_note" class="review-note"><MessageSquareWarning :size="15" /><div><strong>审核意见</strong><p>{{ detail.review_note }}</p></div></div>
            <div class="experience-details">
              <article v-for="field in experienceFields" :key="field.label"><h4>{{ field.label }}</h4><p>{{ field.value }}</p></article>
            </div>
            <div class="evidence-list"><h4>相关日志 / Run / Task 证据</h4><article v-for="evidence in detail.evidence" :key="evidence.id"><span :data-result="evidence.result"><FileCheck2 :size="15" /></span><div><strong>{{ evidence.evidence_type }}</strong><p>{{ evidence.content || evidence.uri || '已关联结构化证据' }}</p><small>{{ evidence.task_id || '—' }} · {{ evidence.run_id || '—' }} · {{ evidence.result || '未标记结果' }}</small></div><a v-if="safeExternalUrl(evidence.uri)" :href="safeExternalUrl(evidence.uri)" target="_blank" rel="noopener noreferrer">打开</a></article><p v-if="!detail.evidence.length" class="evidence-empty">暂无额外证据，审核时请重点核对来源 Task 与 Run。</p></div>
          </section>

          <section v-if="reviewEditing" class="review-editor">
            <div class="section-title"><span><ClipboardEdit :size="16" /></span><div><h3>发布前编辑</h3><p>确认目标空间、标题、标签和 Markdown，保存后立即进入员工检索范围。</p></div></div>
            <div class="review-grid"><label>目标知识空间 *<select v-model="review.space_id"><option value="" disabled>请选择</option><option v-for="space in spaces" :key="space.id" :value="space.id">{{ space.name }}</option></select></label><label>验证状态<select v-model="review.verification_status"><option value="unverified">未验证</option><option value="verified">已验证</option><option value="failed">验证失败</option></select></label></div>
            <label>标题<input v-model.trim="review.title" maxlength="240" /></label><label>标签<input v-model="review.tags" placeholder="用逗号分隔" /></label><label>摘要<textarea v-model="review.summary" rows="2" /></label><label>Markdown 正文<textarea v-model="review.content_md" rows="18" /></label>
            <label v-if="detail.status === 'candidate'">驳回 / 补充原因<textarea v-model.trim="review.reason" rows="3" placeholder="驳回时必填，也可填写需要数字员工补充的内容" /></label>
          </section>
          <section v-else class="markdown-section">
            <div class="markdown-body" v-html="safeMarkdown" />
          </section>

          <section v-if="detail.sources.length" class="knowledge-sources"><h3>资料来源</h3><article v-for="source in detail.sources" :key="source.id"><strong>{{ source.source_name || source.source_id || source.source_type }}</strong><span>{{ source.source_type }}<template v-if="source.version"> · {{ source.version }}</template></span><a v-if="safeExternalUrl(source.source_uri)" :href="safeExternalUrl(source.source_uri)" target="_blank" rel="noopener noreferrer">查看来源</a></article></section>
          <section v-if="relatedOpen" class="related-tasks"><div class="section-title"><span><ListTree :size="16" /></span><div><h3>关联任务</h3><p>来源任务及实际引用过该知识的任务。</p></div><button type="button" aria-label="关闭关联任务" @click="relatedOpen = false"><X :size="15" /></button></div><div v-if="relatedLoading" class="related-loading"><LoaderCircle :size="17" class="spin" />正在加载</div><RouterLink v-for="task in relatedTasks" :key="task.id" :to="`/tasks/${task.id}`" @click="$emit('close')"><div><strong>{{ task.title }}</strong><small>{{ task.id }} · {{ task.relation }}</small></div><span>{{ task.status }}</span><ChevronRight :size="15" /></RouterLink><p v-if="!relatedLoading && !relatedTasks.length">暂无关联任务记录。</p></section>
          <p v-if="error" class="detail-error">{{ error }}</p>
        </div>

        <footer>
          <div class="knowledge-actions">
            <button type="button" :class="{ active: detail.is_favorite }" @click="$emit('favorite')"><Star :size="15" :fill="detail.is_favorite ? 'currentColor' : 'none'" />{{ detail.is_favorite ? '已收藏' : '收藏' }}</button>
            <button type="button" :class="{ active: detail.user_helpful }" @click="$emit('helpful')"><ThumbsUp :size="15" />有帮助 ({{ detail.helpful_count }})</button>
            <button type="button" @click="share"><Share2 :size="15" />分享</button><button type="button" @click="copyLink"><Link2 :size="15" />{{ copied ? '已复制' : '复制链接' }}</button>
            <button type="button" @click="openRelated"><ListTree :size="15" />查看关联任务</button>
          </div>
          <div v-if="canReview && ['candidate','draft'].includes(detail.status)" class="review-actions">
            <button type="button" class="button" @click="reviewEditing = !reviewEditing"><Pencil :size="14" />{{ reviewEditing ? '预览正文' : '审核编辑' }}</button>
            <template v-if="detail.status === 'candidate'"><button type="button" class="button" :disabled="working || review.reason.length < 2" @click="$emit('supplement', review.reason)">要求补充</button><button type="button" class="button button--danger" :disabled="working || review.reason.length < 2" @click="$emit('reject', review.reason)">驳回</button></template>
            <button type="button" class="button button--primary" :disabled="working || !review.space_id || !review.title || !review.content_md" @click="publish"><LoaderCircle v-if="working" :size="14" class="spin" />发布</button>
          </div>
        </footer>
      </article>
      <div v-else-if="error" class="detail-loading detail-loading--error"><TriangleAlert :size="22" /><span>{{ error }}</span><button type="button" @click="$emit('close')">关闭</button></div>
      <div v-else class="detail-loading"><LoaderCircle :size="24" class="spin" />正在加载知识详情</div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { BadgeCheck, ChevronRight, CircleCheck, ClipboardEdit, Clock3, FileCheck2, Link2, ListTree, LoaderCircle, MessageSquareWarning, Pencil, Share2, Sparkles, Star, ThumbsUp, TriangleAlert, X } from 'lucide-vue-next'
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import type { KnowledgeDetail, KnowledgeSpace, RelatedTask } from '@/api/types'

const props = defineProps<{ open: boolean; detail: KnowledgeDetail | null; spaces: KnowledgeSpace[]; canReview: boolean; working: boolean; error: string; relatedTasks: RelatedTask[]; relatedLoading: boolean }>()
const emit = defineEmits<{ close: []; favorite: []; helpful: []; related: []; publish: [payload: Record<string, unknown>]; reject: [reason: string]; supplement: [reason: string] }>()
const reviewEditing = ref(false)
const relatedOpen = ref(false)
const copied = ref(false)
const review = reactive({ space_id: '', title: '', summary: '', tags: '', content_md: '', verification_status: 'unverified', reason: '' })
let previousOverflow = ''
marked.setOptions({ gfm: true, breaks: false })
watch(() => props.open, (open) => { if (open) { previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden' } else document.body.style.overflow = previousOverflow })
watch(() => props.detail?.id, () => {
  const detail = props.detail
  if (!detail) return
  Object.assign(review, { space_id: detail.space_id || props.spaces[0]?.id || '', title: detail.title, summary: detail.summary, tags: detail.tags.join(', '), content_md: detail.content_md, verification_status: detail.verification_status, reason: detail.review_note || '' })
  reviewEditing.value = false; relatedOpen.value = false; copied.value = false
})
onBeforeUnmount(() => { document.body.style.overflow = previousOverflow })
const safeMarkdown = computed(() => DOMPurify.sanitize(marked.parse(props.detail?.content_md || '', { async: false }) as string, { USE_PROFILES: { html: true } }))
const typeLabel = (value: string) => ({ document: '文档', rule: '规范', guide: '指南', experience: '经验', faq: 'FAQ', tool: '工具', example: '示例' }[value] ?? value)
const statusLabel = (value: string) => ({ published: '已发布', candidate: '待审核', draft: '草稿', archived: '已归档', rejected: '已驳回' }[value] ?? value)
const verificationLabel = (value: string) => ({ verified: '已验证', unverified: '未验证', failed: '验证失败' }[value] ?? value)
const formatDate = (value: string) => new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
function experienceValue(keys: string[]) { for (const key of keys) { const value = props.detail?.experience_data[key]; if (value !== undefined && value !== null && value !== '') return typeof value === 'boolean' ? value ? '通过' : '未通过' : String(value) } return '—' }
function safeExternalUrl(value: string | null | undefined) {
  if (!value) return ''
  try {
    const url = new URL(value, window.location.origin)
    return ['http:', 'https:'].includes(url.protocol) ? value : ''
  } catch {
    return ''
  }
}
const experienceFields = computed(() => [
  { label: '问题现象', value: experienceValue(['problem_symptom', 'problem', 'symptom']) },
  { label: '原始异常 / 错误信息', value: experienceValue(['original_error', 'error', 'exception']) },
  { label: 'Agent 采取的处理方式', value: experienceValue(['handling', 'resolution', 'solution']) },
  { label: '修改内容摘要', value: experienceValue(['change_summary', 'changes', 'modification_summary']) },
  { label: '重试与验证结果', value: experienceValue(['retry_result', 'verification_result', 'result']) },
].filter((field) => field.value !== '—'))
function publish() { emit('publish', { space_id: review.space_id, title: review.title, summary: review.summary, tags: review.tags.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean), content_md: review.content_md, verification_status: review.verification_status }) }
function knowledgeUrl() { const url = new URL(window.location.href); if (props.detail) url.searchParams.set('knowledge', props.detail.id); return url.toString() }
async function copyLink() { await navigator.clipboard.writeText(knowledgeUrl()); copied.value = true; window.setTimeout(() => { copied.value = false }, 1600) }
async function share() { if (navigator.share) await navigator.share({ title: props.detail?.title, url: knowledgeUrl() }); else await copyLink() }
function openRelated() { relatedOpen.value = true; emit('related') }
</script>

<style scoped>
.detail-backdrop{position:fixed;z-index:1250;inset:0;display:grid;place-items:center;padding:20px;background:rgba(16,37,34,.42);backdrop-filter:blur(2px)}.knowledge-detail{display:grid;grid-template-rows:auto minmax(0,1fr) auto;width:min(1020px,100%);max-height:80vh;overflow:hidden;border:1px solid var(--astra-border);border-radius:16px;background:#fff;box-shadow:0 28px 80px rgba(16,37,34,.24)}.knowledge-detail>header{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:18px 22px 16px;border-bottom:1px solid var(--astra-border);background:#fff}.knowledge-detail>header>button{display:grid;place-items:center;flex:none;width:35px;height:35px;color:var(--astra-text-muted);border:0;border-radius:9px;background:#f2f6f4;cursor:pointer}.detail-heading{min-width:0}.detail-heading>div:first-child{display:flex;flex-wrap:wrap;gap:6px}.detail-type,.detail-tag{display:inline-flex;padding:4px 8px;border-radius:6px;font-size:12px}.detail-type{color:var(--astra-primary-bright);background:var(--astra-primary-soft)}.detail-tag{color:var(--astra-text-secondary);background:#edf2f0}.detail-heading h2{margin:9px 0 8px;color:var(--astra-text-primary);font-size:23px;line-height:1.3}.detail-meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;color:var(--astra-text-muted);font-size:12px}.detail-meta span,.detail-meta a{display:inline-flex;align-items:center;gap:4px}.detail-meta span[data-status='published'],.detail-meta span[data-verified='verified']{color:var(--astra-primary-bright)}.detail-meta a{color:var(--astra-primary-bright)}.detail-loading--error{display:grid;justify-items:center;max-width:420px;text-align:center}.detail-loading--error button{padding:7px 14px;color:var(--astra-danger);border:1px solid rgba(228,93,106,.24);border-radius:7px;background:#fff;cursor:pointer}
.detail-scroll{overflow-y:auto;overscroll-behavior:contain;padding:0 24px 24px;scrollbar-gutter:stable}.markdown-section{padding:25px 4px 10px}.markdown-body{color:var(--astra-text-secondary);font-size:15px;line-height:1.78}.markdown-body:deep(h1),.markdown-body:deep(h2),.markdown-body:deep(h3){color:var(--astra-text-primary);line-height:1.35}.markdown-body:deep(h1){margin:0 0 18px;font-size:25px}.markdown-body:deep(h2){margin:25px 0 12px;padding-bottom:7px;border-bottom:1px solid var(--astra-border);font-size:20px}.markdown-body:deep(h3){margin:19px 0 9px;font-size:17px}.markdown-body:deep(p){margin:9px 0}.markdown-body:deep(ul),.markdown-body:deep(ol){padding-left:24px}.markdown-body:deep(blockquote){margin:14px 0;padding:10px 14px;color:var(--astra-text-secondary);border-left:3px solid var(--astra-primary);background:var(--astra-primary-soft)}.markdown-body:deep(code){padding:2px 5px;color:#b45140;border-radius:5px;background:#f4efec;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em}.markdown-body:deep(pre){overflow:auto;padding:14px;border:1px solid var(--astra-border);border-radius:9px;background:#15231f}.markdown-body:deep(pre code){padding:0;color:#dcebe5;background:transparent}.markdown-body:deep(table){display:block;max-width:100%;overflow:auto;border-collapse:collapse}.markdown-body:deep(th),.markdown-body:deep(td){padding:8px 10px;border:1px solid var(--astra-border)}.markdown-body:deep(th){background:#f3f8f5}.markdown-body:deep(img){max-width:100%;height:auto;border-radius:8px}.markdown-body:deep(a){color:var(--astra-primary-bright);text-decoration:underline}.markdown-body:deep(hr){margin:24px 0;border:0;border-top:1px solid var(--astra-border)}
.candidate-origin{margin:18px 0 4px;padding:16px;border:1px solid rgba(233,149,63,.25);border-radius:12px;background:linear-gradient(135deg,rgba(255,250,244,.96),rgba(255,255,255,.96))}.section-title{display:flex;align-items:center;gap:10px}.section-title>span{display:grid;place-items:center;flex:none;width:34px;height:34px;color:var(--astra-warning);border-radius:9px;background:var(--astra-warning-soft)}.section-title h3,.section-title p{margin:0}.section-title h3{color:var(--astra-text-primary);font-size:16px}.section-title p{margin-top:2px;color:var(--astra-text-muted);font-size:12px}.origin-facts{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;margin:14px 0 0;overflow:hidden;border:1px solid rgba(233,149,63,.2);border-radius:9px;background:rgba(233,149,63,.16)}.origin-facts div{min-width:0;padding:9px 10px;background:#fff}.origin-facts dt{color:var(--astra-text-muted);font-size:11px}.origin-facts dd{overflow:hidden;margin:3px 0 0;color:var(--astra-text-primary);font-size:13px;font-weight:600;text-overflow:ellipsis;white-space:nowrap}.experience-details{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}.experience-details article{padding:10px;border:1px solid var(--astra-border);border-radius:8px;background:#fff}.experience-details h4,.experience-details p,.evidence-list h4{margin:0}.experience-details h4,.evidence-list h4{color:var(--astra-text-secondary);font-size:12px}.experience-details p{margin-top:4px;color:var(--astra-text-muted);font-size:12px;white-space:pre-wrap}.review-note{display:flex;gap:8px;margin-top:12px;padding:9px 10px;color:#9a6328;border-radius:8px;background:var(--astra-warning-soft)}.review-note svg{flex:none}.review-note strong{font-size:12px}.review-note p{margin:3px 0 0;font-size:12px}.evidence-list{margin-top:14px}.evidence-list>article{display:flex;align-items:flex-start;gap:9px;padding:9px 0;border-bottom:1px solid var(--astra-border)}.evidence-list>article>span{display:grid;place-items:center;flex:none;width:30px;height:30px;color:var(--astra-primary-bright);border-radius:8px;background:var(--astra-primary-soft)}.evidence-list article>div{display:grid;min-width:0;flex:1}.evidence-list strong{color:var(--astra-text-primary);font-size:12px}.evidence-list p,.evidence-list small{overflow:hidden;margin:2px 0 0;color:var(--astra-text-muted);font-size:11px;text-overflow:ellipsis;white-space:nowrap}.evidence-list a{color:var(--astra-primary-bright);font-size:12px}.evidence-empty{color:var(--astra-text-muted);font-size:12px}
.review-editor{display:grid;gap:12px;margin:18px 0;padding:16px;border:1px solid var(--astra-primary-border);border-radius:12px;background:#f8fcfa}.review-editor>.section-title{margin-bottom:2px}.review-editor>.section-title>span{color:var(--astra-primary-bright);background:var(--astra-primary-soft)}.review-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.review-editor label{display:grid;gap:5px;color:var(--astra-text-secondary);font-size:12px}.review-editor input,.review-editor select,.review-editor textarea{width:100%;padding:8px 9px;color:var(--astra-text-primary);border:1px solid var(--astra-border);border-radius:8px;background:#fff;font:inherit}.review-editor textarea{resize:vertical}.review-editor label:nth-of-type(4) textarea{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.55}
.knowledge-sources,.related-tasks{margin:18px 0 0;padding-top:15px;border-top:1px solid var(--astra-border)}.knowledge-sources h3{margin:0 0 8px;color:var(--astra-text-primary);font-size:15px}.knowledge-sources article{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:10px;padding:7px 0;color:var(--astra-text-muted);font-size:12px}.knowledge-sources strong{color:var(--astra-text-secondary)}.knowledge-sources a{color:var(--astra-primary-bright)}.related-tasks>.section-title>button{margin-left:auto;display:grid;place-items:center;width:28px;height:28px;border:0;border-radius:7px;background:#f2f6f4}.related-tasks>a{display:grid;grid-template-columns:minmax(0,1fr) auto 20px;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--astra-border)}.related-tasks>a div{display:grid}.related-tasks>a strong{color:var(--astra-text-primary);font-size:13px}.related-tasks>a small,.related-tasks>a span,.related-tasks>p{color:var(--astra-text-muted);font-size:11px}.related-loading{display:flex;align-items:center;gap:7px;padding:15px;color:var(--astra-text-muted);font-size:12px}.detail-error{padding:9px 11px;color:var(--astra-danger);border-radius:8px;background:var(--astra-danger-soft);font-size:12px}
.knowledge-detail>footer{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:62px;padding:10px 18px;border-top:1px solid var(--astra-border);background:#fbfdfc}.knowledge-actions,.review-actions{display:flex;align-items:center;flex-wrap:wrap;gap:5px}.knowledge-actions button{display:inline-flex;align-items:center;gap:5px;min-height:34px;padding:0 8px;color:var(--astra-text-muted);border:0;border-radius:7px;background:transparent;cursor:pointer;font-size:12px}.knowledge-actions button:hover,.knowledge-actions button.active{color:var(--astra-primary-bright);background:var(--astra-primary-soft)}.button--danger{color:var(--astra-danger)!important;border-color:rgba(228,93,106,.28)!important;background:var(--astra-danger-soft)!important}.detail-loading{display:flex;align-items:center;gap:9px;padding:20px;color:#fff}.button:disabled{cursor:default;opacity:.55}
@media(max-width:900px){.knowledge-detail>footer{align-items:flex-start;flex-direction:column}.knowledge-actions,.review-actions{width:100%}.origin-facts{grid-template-columns:repeat(2,1fr)}}@media(max-width:650px){.detail-backdrop{padding:7px}.knowledge-detail{max-height:94vh}.knowledge-detail>header{padding:14px}.detail-scroll{padding:0 14px 18px}.detail-heading h2{font-size:19px}.origin-facts,.experience-details,.review-grid{grid-template-columns:1fr}.knowledge-actions button{font-size:0}.knowledge-actions button svg{width:17px;height:17px}.knowledge-detail>footer{padding:9px 12px}}
</style>
