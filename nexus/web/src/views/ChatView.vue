<template>
  <section>
    <div class="title-row"><h1 class="h-title">数字员工</h1></div>
    <div class="workspace">
      <aside class="panel left-rail">
        <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
          <b>我的数字员工</b><span class="tag">{{ employees.length }} 位</span>
        </div>
        <div v-if="!employees.length" class="muted">还没有数字员工</div>
        <button
          v-for="employee in employees"
          :key="employee.id"
          class="rail-item"
          :class="{ active: employee.id === currentId }"
          type="button"
          @click="selectEmployee(employee.id)"
        >
          <span class="avatar" :class="{ off: !employee.enabled }">{{ employee.avatar }}</span>
          <span><b>{{ employee.name }}</b><small class="muted">{{ employee.domain }}</small></span>
        </button>
      </aside>
      <article class="panel chat">
        <div class="chat-head" v-if="current">
          <div>
            <h2 style="margin: 0 0 4px">{{ current.name }} · {{ current.domain }}</h2>
            <p class="muted" style="margin: 0">{{ current.description }}</p>
          </div>
          <div style="display: flex; gap: 8px; align-items: center">
            <el-select :model-value="conversationId" style="width: 180px" @change="selectConversation">
              <el-option v-for="item in conversations" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
            <el-button size="small" @click="startConversation">＋ 新对话</el-button>
          </div>
        </div>
        <div v-else class="chat-head"><h2>尚未创建员工</h2></div>
        <div class="chat-messages" ref="messageBox">
          <div v-if="!messages.length && !notice" class="empty">{{ current ? `与 ${current.name} 开始交流` : "还没有员工可以交流" }}</div>
          <div v-for="message in messages" :key="message.id" class="msg" :class="{ user: message.sender === 'user' }">
            <div>
              <div class="muted">{{ message.sender === "user" ? "你" : speakerName(message.sender) }}</div>
              <div v-if="message.text" class="bubble">{{ message.text }}</div>
              <div class="message-attachments">
                <a v-for="file in message.attachments" :key="file.id" class="sent-attachment" :href="attachmentUrl(file.id)" target="_blank">
                  <span><b>{{ file.name }}</b><small class="muted">{{ formatSize(file.size) }}</small></span>
                </a>
              </div>
            </div>
          </div>
          <div v-if="liveText" class="msg"><div><div class="muted">{{ current?.name }}</div><div class="bubble">{{ liveText }}</div></div></div>
          <div v-if="notice" class="msg system"><div class="bubble">{{ notice }}</div></div>
        </div>
        <div class="chat-compose">
          <div class="chips" style="margin-bottom: 8px">
            <button class="chip" type="button" :disabled="!canSend" @click="draft = '你负责哪些工作？'">你的职责</button>
            <button class="chip" type="button" :disabled="!canSend" @click="draft = '你能访问哪些知识和工具？'">你的能力</button>
          </div>
          <div v-if="draftFiles.length" class="draft-attachments">
            <div v-for="file in draftFiles" :key="file.id" class="draft-file">
              <div><b>{{ file.name }}</b><small class="muted">{{ formatSize(file.size) }}</small></div>
              <el-button link type="danger" @click="draftFiles = draftFiles.filter((item) => item.id !== file.id)">移除</el-button>
            </div>
          </div>
          <div class="compose-box">
            <el-button :disabled="!canSend" @click="fileInput?.click()">附件</el-button>
            <input ref="fileInput" type="file" multiple hidden @change="addFiles" />
            <textarea v-model="draft" :disabled="!canSend" rows="2" :placeholder="canSend ? '发送消息…' : '该员工已禁用，历史消息仍可查看'" @keydown.enter.exact.prevent="send" />
            <el-button type="primary" :disabled="!canSend" @click="send">发送</el-button>
          </div>
        </div>
      </article>
      <aside class="panel aside" v-if="current">
        <div class="right-tabs">
          <button class="chip" :class="{ sel: tab === 'responsibility' }" type="button" @click="tab = 'responsibility'">职责</button>
          <button class="chip" :class="{ sel: tab === 'capability' }" type="button" @click="tab = 'capability'">能力</button>
          <button class="chip" :class="{ sel: tab === 'memory' }" type="button" @click="tab = 'memory'">记忆</button>
        </div>
        <div v-if="tab === 'responsibility'" style="padding: 16px">
          <div class="section-label">职责范围</div>
          <div class="detail-excerpt">{{ current.description }}</div>
          <div class="section-label">工作指令</div>
          <div class="detail-excerpt">{{ current.instructions }}</div>
        </div>
        <div v-else-if="tab === 'capability'" style="padding: 16px">
          <div class="section-label">知识</div>
          <div class="resource-list"><span v-for="item in current.knowledge" :key="item" class="mini-chip">{{ item }}</span></div>
          <div class="section-label">Skill</div>
          <div class="resource-list"><span v-for="item in current.skills" :key="item" class="mini-chip">{{ item }}</span></div>
          <div class="section-label">Tools</div>
          <div class="resource-list"><span v-for="item in current.tools" :key="item" class="mini-chip">{{ item }}</span></div>
        </div>
        <div v-else style="padding: 16px">
          <div class="detail-excerpt">长期记忆在 AgentScope Session 中。Nexus 不另存一份记忆。</div>
          <div class="muted" style="margin-top: 8px">当前对话用户消息 {{ messages.length }} 条</div>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import {
  attachmentUrl,
  createConversation,
  getConversation,
  listConversations,
  listEmployees,
  readEventStream,
  sendConversation,
  uploadAttachment,
} from "../api";
import type { Attachment, ChatMessage, Conversation, Employee } from "../types";

const route = useRoute();
const employees = ref<Employee[]>([]);
const currentId = ref<string | null>(null);
const conversations = ref<Conversation[]>([]);
const conversationId = ref<string | null>(null);
const messages = ref<ChatMessage[]>([]);
const draft = ref("");
const draftFiles = ref<Attachment[]>([]);
const notice = ref("");
const liveText = ref("");
const tab = ref<"responsibility" | "capability" | "memory">("responsibility");
const fileInput = ref<HTMLInputElement | null>(null);
let streamAbort: AbortController | null = null;

const current = computed(() => employees.value.find((item) => item.id === currentId.value) ?? null);
const canSend = computed(() => Boolean(current.value?.enabled && conversationId.value));

function speakerName(sender: string) {
  return employees.value.find((item) => item.id === sender)?.name ?? sender;
}
function formatSize(size: number) {
  if (size < 1024) return "小于 1 KB";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1048576).toFixed(1)} MB`;
}

async function loadEmployees() {
  employees.value = await listEmployees();
  const queryId = typeof route.query.employee === "string" ? route.query.employee : null;
  currentId.value = queryId && employees.value.some((item) => item.id === queryId) ? queryId : employees.value[0]?.id ?? null;
}

async function selectEmployee(id: string) {
  currentId.value = id;
  notice.value = "";
  liveText.value = "";
  const items = await listConversations(id);
  conversations.value = items;
  if (!items.length && employees.value.find((item) => item.id === id)) {
    const created = await createConversation(id);
    conversations.value = [created];
  }
  conversationId.value = conversations.value.at(-1)?.id ?? null;
}

async function selectConversation(id: string) {
  conversationId.value = id;
  notice.value = "";
  liveText.value = "";
}

async function startConversation() {
  if (!currentId.value) return;
  const created = await createConversation(currentId.value);
  conversations.value = [...conversations.value, created];
  conversationId.value = created.id;
  messages.value = [];
  notice.value = "";
  liveText.value = "";
}

async function addFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = "";
  if (draftFiles.value.length + files.length > 6) {
    ElMessage.warning("每条消息最多添加 6 个附件");
  }
  for (const file of files.slice(0, 6 - draftFiles.value.length)) {
    if (!file.size) {
      ElMessage.warning("不能添加空文件");
      continue;
    }
    if (file.size > 20 * 1024 * 1024) {
      ElMessage.warning("单个附件不能超过 20 MB");
      continue;
    }
    try {
      draftFiles.value.push(await uploadAttachment(file));
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "附件上传失败");
    }
  }
}

function stopStream() {
  streamAbort?.abort();
  streamAbort = null;
}

async function followStream(id: string) {
  stopStream();
  streamAbort = new AbortController();
  liveText.value = "";
  try {
    await readEventStream(`/api/v1/conversations/${id}/stream`, streamAbort.signal, (event) => {
      if (event.type === "TEXT_BLOCK_DELTA" && typeof event.delta === "string") {
        liveText.value += event.delta;
      }
      if (event.type === "NEXUS_UPSTREAM_ERROR") {
        notice.value = String(event.detail ?? "事件流中断");
      }
    });
  } catch (error) {
    if (!streamAbort?.signal.aborted) {
      notice.value = error instanceof Error ? error.message : "事件流中断";
    }
  }
}

async function send() {
  if (!conversationId.value || !canSend.value) return;
  const text = draft.value.trim();
  if (!text && !draftFiles.value.length) return;
  try {
    const result = await sendConversation(conversationId.value, text, draftFiles.value.map((item) => item.id));
    messages.value = [...messages.value, result.message];
    draft.value = "";
    draftFiles.value = [];
    const conversation = conversations.value.find((item) => item.id === conversationId.value);
    if (conversation && conversation.name === "新对话") {
      conversation.name = result.message.text.slice(0, 20) || result.message.attachments[0]?.name || "新对话";
    }
    if (!result.agentscope.accepted) {
      notice.value = result.agentscope.detail || "没有生成回复";
      liveText.value = "";
      return;
    }
    notice.value = "";
    await followStream(conversationId.value);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "发送失败");
  }
}

watch(conversationId, async (id) => {
  stopStream();
  if (!id) {
    messages.value = [];
    return;
  }
  const payload = await getConversation(id);
  messages.value = payload.messages;
});

onMounted(async () => {
  await loadEmployees();
  if (currentId.value) await selectEmployee(currentId.value);
});
onBeforeUnmount(stopStream);
</script>

<style scoped>
.rail-item { width: 100%; border: 0; background: transparent; text-align: left; }
.chip.sel { background: #e5f6ed; border-color: #aad8c2; color: #187956; }
</style>
