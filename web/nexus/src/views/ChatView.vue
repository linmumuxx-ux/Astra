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
          <span class="muted">同一人与该员工只有一条私聊</span>
        </div>
        <div v-else class="chat-head"><h2>尚未创建员工</h2></div>
        <div class="chat-messages" ref="messageBox">
          <div v-if="!messages.length && !notice" class="empty">{{ current ? `与 ${current.name} 开始交流` : "还没有员工可以交流" }}</div>
          <div v-for="message in messages" :key="message.id" class="msg" :class="{ user: message.sender === 'user' }">
            <div>
              <div class="muted">{{ message.sender === "user" ? (message.speaker || "你") : speakerName(message.sender) }}</div>
              <div v-if="message.text" class="bubble">{{ message.text }}</div>
              <div class="message-attachments">
                <a v-for="file in message.attachments" :key="file.id" class="sent-attachment" :class="{ image: isImage(file.type) }" :href="attachmentUrl(file.id)" :download="file.name" target="_blank">
                  <img v-if="isImage(file.type)" :src="attachmentUrl(file.id)" :alt="file.name" />
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
              <img v-if="isImage(file.type)" :src="attachmentUrl(file.id)" :alt="file.name" />
              <div><b>{{ file.name }}</b><small class="muted">{{ formatSize(file.size) }}</small></div>
              <el-button link type="danger" @click="draftFiles = draftFiles.filter((item) => item.id !== file.id)">移除</el-button>
            </div>
          </div>
          <div
            class="compose-box"
            :class="{ dropping }"
            @dragover.prevent="dropping = canSend"
            @dragleave="dropping = false"
            @drop.prevent="onDrop"
          >
            <el-button :disabled="!canSend" @click="fileInput?.click()">附件</el-button>
            <input ref="fileInput" type="file" multiple hidden @change="onPick" />
            <textarea v-model="draft" :disabled="!canSend" rows="2" :placeholder="canSend ? '发送消息，或拖入、粘贴图片…' : '该员工已禁用，历史消息仍可查看'" @paste="onPaste" @keydown.enter.exact.prevent="send" />
            <el-button type="primary" :disabled="!canSend" @click="send">发送</el-button>
          </div>
        </div>
      </article>
      <aside class="panel aside" v-if="current">
        <div class="right-tabs">
          <button class="chip" :class="{ sel: tab === 'responsibility' }" type="button" @click="tab = 'responsibility'">职责</button>
          <button class="chip" :class="{ sel: tab === 'capability' }" type="button" @click="tab = 'capability'">能力</button>
          <button class="chip" :class="{ sel: tab === 'memory' }" type="button" @click="tab = 'memory'">记忆</button>
          <button class="chip" :class="{ sel: tab === 'tasks' }" type="button" @click="tab = 'tasks'">任务</button>
        </div>
        <div v-if="tab === 'responsibility'" style="padding: 16px">
          <div class="section-label">职责范围</div>
          <div class="detail-excerpt">{{ current.description }}</div>
          <div class="section-label">工作指令</div>
          <div class="detail-excerpt">{{ current.instructions }}</div>
        </div>
        <div v-else-if="tab === 'capability'" style="padding: 16px">
          <div class="section-label">知识</div>
          <div class="resource-list">
            <span v-for="item in current.knowledge" :key="item" class="mini-chip">{{ resourceLabel(catalogs.knowledge, item) }}</span>
            <span v-if="!current.knowledge.length" class="muted">暂无</span>
          </div>
          <div class="section-label">Skill</div>
          <div class="resource-list">
            <span v-for="item in current.skills" :key="item" class="mini-chip">{{ resourceLabel(catalogs.skills, item) }}</span>
            <span v-if="!current.skills.length" class="muted">暂无</span>
          </div>
          <div class="section-label">Tools</div>
          <div class="resource-list">
            <span v-for="item in current.tools" :key="item" class="mini-chip">{{ resourceLabel(catalogs.tools, item) }}</span>
            <span v-if="!current.tools.length" class="muted">暂无</span>
          </div>
        </div>
        <div v-else-if="tab === 'memory'" style="padding: 16px">
          <div class="detail-excerpt">记忆保存在这条 AgentScope Session 里，这里只读，不能修改员工。</div>
          <div class="section-label">Session</div>
          <div class="mono">{{ activeConversation?.agentscope_session_id || "发送后才会创建" }}</div>
          <div v-if="latestReply" class="detail-excerpt" style="margin-top: 12px">{{ latestReply }}</div>
        </div>
        <div v-else style="padding: 16px">
          <TaskTable :tasks="tasks" />
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import {
  attachmentUrl,
  createConversation,
  getConversation,
  getKnowledge,
  getSkills,
  getTools,
  listEmployees,
  readEventStream,
  sendConversation,
  uploadAttachment,
} from "../api";
import TaskTable from "../components/TaskTable.vue";
import { listTasks, type PlatformTask } from "../platform";
import type { Attachment, ChatMessage, Conversation, Employee, ResourceCatalog } from "../types";

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
const dropping = ref(false);
const seenEventIds = new Map<string, Set<string>>();
let followToken = 0;
const tab = ref<"responsibility" | "capability" | "memory" | "tasks">("responsibility");
const tasks = ref<PlatformTask[]>([]);
const fileInput = ref<HTMLInputElement | null>(null);
const messageBox = ref<HTMLElement | null>(null);
const emptyCatalog = (): ResourceCatalog => ({ available: false, items: [] });
const catalogs = ref({ skills: emptyCatalog(), knowledge: emptyCatalog(), tools: emptyCatalog() });
let streamAbort: AbortController | null = null;

const current = computed(() => employees.value.find((item) => item.id === currentId.value) ?? null);
const activeConversation = computed(() => conversations.value.find((item) => item.id === conversationId.value) ?? null);
const canSend = computed(() => Boolean(current.value?.enabled && conversationId.value));
const latestReply = computed(() => [...messages.value].reverse().find((item) => item.sender !== "user")?.text ?? "");

function speakerName(sender: string) {
  return employees.value.find((item) => item.id === sender)?.name ?? sender;
}
function isImage(type: string) {
  return type.startsWith("image/");
}
function resourceLabel(catalog: ResourceCatalog, id: string) {
  return catalog.items.find((item) => item.id === id)?.name ?? id;
}
function takeLiveReply() {
  const text = liveText.value.trim();
  if (!text || !current.value) return;
  messages.value = [
    ...messages.value,
    { id: `live_${Date.now()}`, sender: current.value.id, text, attachments: [], created_at: new Date().toISOString() },
  ];
  liveText.value = "";
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
  const created = await createConversation(id);
  conversations.value = [created];
  conversationId.value = created.id;
}

async function addFileList(files: File[]) {
  if (!canSend.value) return;
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
    const named = file.name ? file : new File([file], "截图.png", { type: file.type || "image/png" });
    try {
      draftFiles.value.push(await uploadAttachment(named));
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "附件上传失败");
    }
  }
}

function onPick(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = "";
  void addFileList(files);
}

function onDrop(event: DragEvent) {
  dropping.value = false;
  void addFileList(Array.from(event.dataTransfer?.files ?? []));
}

function onPaste(event: ClipboardEvent) {
  const fromFiles = Array.from(event.clipboardData?.files ?? []);
  const fromItems = Array.from(event.clipboardData?.items ?? [])
    .filter((item) => item.type.startsWith("image/"))
    .map((item) => item.getAsFile())
    .filter((file): file is File => Boolean(file));
  const files = fromFiles.length ? fromFiles : fromItems;
  if (!files.length) return;
  event.preventDefault();
  void addFileList(files);
}

function stopStream() {
  streamAbort?.abort();
  streamAbort = null;
}

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function reloadConversation(id: string) {
  const payload = await getConversation(id);
  if (conversationId.value !== id) return;
  messages.value = payload.messages;
  if (payload.history_error) notice.value = `没有读到 Session 里的回复。${payload.history_error}`;
}

async function followStream(id: string) {
  stopStream();
  const token = ++followToken;
  streamAbort = new AbortController();
  liveText.value = "";
  const seen = seenEventIds.get(id) ?? new Set<string>();
  seenEventIds.set(id, seen);
  try {
    await readEventStream(`/api/v1/conversations/${id}/stream`, streamAbort.signal, (event) => {
      if (typeof event.id === "string") {
        if (seen.has(event.id)) return;
        seen.add(event.id);
      }
      if (event.type === "TEXT_BLOCK_DELTA" && typeof event.delta === "string") {
        liveText.value += event.delta;
      }
      if (event.type === "REPLY_END" || event.type === "NEXUS_RUN_FINISHED") {
        liveText.value = "";
        void reloadConversation(id);
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
  for (let attempt = 0; attempt < 8; attempt += 1) {
    if (token !== followToken || conversationId.value !== id) return;
    await delay(2000);
    if (token !== followToken || conversationId.value !== id) return;
    await reloadConversation(id);
  }
}

async function send() {
  if (!conversationId.value || !canSend.value) return;
  takeLiveReply();
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
  if (payload.history_error) notice.value = `没有读到 Session 里的回复。${payload.history_error}`;
});

async function refreshTasks() {
  if (!currentId.value || tab.value !== "tasks") return;
  try {
    tasks.value = await listTasks({ responsible_employee_id: currentId.value });
  } catch {
    tasks.value = [];
  }
}

watch([tab, currentId], () => {
  void refreshTasks();
});

watch([messages, liveText], async () => {
  await nextTick();
  if (messageBox.value) messageBox.value.scrollTop = messageBox.value.scrollHeight;
});

let taskTimer = 0;
onMounted(async () => {
  const [skills, knowledge, tools] = await Promise.all([getSkills(), getKnowledge(), getTools()]);
  catalogs.value = { skills, knowledge, tools };
  await loadEmployees();
  if (currentId.value) await selectEmployee(currentId.value);
  taskTimer = window.setInterval(() => void refreshTasks(), 8000);
});
onBeforeUnmount(() => {
  stopStream();
  window.clearInterval(taskTimer);
});
</script>

<style scoped>
.rail-item { width: 100%; border: 0; background: transparent; text-align: left; }
.chip.sel { background: #e5f6ed; border-color: #aad8c2; color: #187956; }
.compose-box.dropping { outline: 2px dashed #187956; }
.sent-attachment.image, .draft-file { display: flex; gap: 8px; align-items: center; }
.sent-attachment img, .draft-file img { width: 72px; height: 72px; object-fit: cover; border-radius: 8px; }
</style>
