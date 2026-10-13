<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { CornerUpLeft, Paperclip, Send, X } from 'lucide-vue-next'
import { mutate, principal, useResource } from '../api'
import { date } from '../format'
import type { Employee, Message } from '../types'
import ResourceState from './ResourceState.vue'
const props = defineProps<{ channelId: string; employees: Employee[]; participants?: { id: string; name: string }[]; group?: boolean }>()
const thread = useResource<Message[]>(() => props.channelId ? `/channels/${props.channelId}/messages` : '', [])
const content = ref('')
const mentions = ref<string[]>([])
const reply = ref<Message | null>(null)
const sending = ref(false)
const error = ref('')
const scroller = ref<HTMLElement>()
const sender = (id: string) => id === principal.value?.id ? principal.value?.name || '我' : props.participants?.find(member => member.id === id)?.name || props.employees.find(employee => employee.id === id)?.name || `成员 ${id.slice(0,8)}`
const ordered = computed(() => [...thread.data.value].sort((left, right) => left.seq - right.seq))
watch(() => props.channelId, () => { content.value = ''; mentions.value = []; reply.value = null; error.value = '' })
watch(() => thread.data.value.length, async () => { await nextTick(); scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' }) })
async function send() {
  if (!content.value.trim() || sending.value || !props.channelId) return
  sending.value = true; error.value = ''
  const current = props.channelId
  try { await mutate(`/channels/${current}/messages`, { content: content.value.trim(), mentions: mentions.value, reply_to: reply.value?.id || null }); if (current === props.channelId) { content.value = ''; mentions.value = []; reply.value = null; await thread.load() } }
  catch (caught) { if (current === props.channelId) error.value = (caught as Error).message }
  finally { sending.value = false }
}
function keyboard(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void send() } }
</script>
<template>
  <div class="chat-thread">
    <div ref="scroller" class="chat-messages" role="log" aria-live="polite" aria-label="长期对话消息">
      <ResourceState :loading="thread.loading.value && !thread.data.value.length" :error="thread.error.value" :empty="!thread.data.value.length" description="从这里开始对话。消息将保存在此交流空间。" @retry="thread.load">
        <article v-for="message in ordered" :key="message.id" class="message" :class="{ mine: message.sender_id === principal?.id }">
          <span class="avatar avatar-small">{{ sender(message.sender_id).slice(0,1) }}</span><div class="message-content"><div class="message-meta"><strong>{{ sender(message.sender_id) }}</strong><time>{{ date(message.created_at) }}</time></div><div class="bubble"><blockquote v-if="message.reply_to">{{ thread.data.value.find(item => item.id === message.reply_to)?.content || `引用消息 ${message.reply_to.slice(0,8)}` }}</blockquote><p>{{ message.content }}</p><div v-if="message.attachment_refs.length" class="message-attachments"><span v-for="attachment in message.attachment_refs" :key="attachment"><Paperclip :size="12"/>{{ attachment }}</span></div></div><button class="reply-button" @click="reply = message"><CornerUpLeft :size="12"/>回复</button></div>
        </article>
      </ResourceState>
    </div>
    <form class="chat-compose" @submit.prevent="send">
      <div v-if="reply" class="reply-preview"><CornerUpLeft :size="13"/><span>回复 {{ sender(reply.sender_id) }}：{{ reply.content }}</span><el-button text circle :icon="X" aria-label="取消引用回复" @click="reply = null"/></div>
      <div v-if="group" class="mention-row"><span class="caption">优先通知</span><el-select v-model="mentions" multiple filterable collapse-tags placeholder="@ 选择员工" aria-label="提及数字员工"><el-option v-for="employee in employees" :key="employee.id" :label="employee.name" :value="employee.id"/></el-select></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false"/>
      <div class="compose-box"><el-input v-model="content" type="textarea" :rows="3" resize="none" placeholder="交办工作、询问进展，或与团队交流…" aria-label="消息内容" @keydown="keyboard"/><el-button type="primary" :icon="Send" :loading="sending" :disabled="!content.trim() || !channelId" aria-label="发送消息" native-type="submit"/></div>
      <div class="compose-footer"><el-button text :icon="Paperclip" disabled title="附件存储尚未接入">附件待接入</el-button><span class="caption">Enter 发送 · Shift + Enter 换行</span></div>
    </form>
  </div>
</template>
