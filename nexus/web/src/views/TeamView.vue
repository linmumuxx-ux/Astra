<template>
  <section>
    <div class="title-row">
      <h1 class="h-title">团队交流</h1>
      <el-button type="primary" @click="openDialog()">＋ 新建讨论</el-button>
    </div>
    <div class="workspace">
      <aside class="panel left-rail">
        <div style="display: flex; justify-content: space-between; margin-bottom: 12px">
          <b>团队频道</b><span class="tag">{{ channels.length }}</span>
        </div>
        <button
          v-for="channel in channels"
          :key="channel.id"
          class="rail-item"
          :class="{ active: channel.id === currentId }"
          type="button"
          @click="currentId = channel.id"
        >
          <span class="avatar">☷</span>
          <span><b>{{ channel.name }}</b><small class="muted">{{ channel.members.length }} 位数字员工</small></span>
        </button>
        <div v-if="!channels.length" class="muted">创建一个团队讨论</div>
      </aside>
      <article class="panel chat">
        <div class="chat-head" v-if="current">
          <div>
            <h2 style="margin: 0 0 4px"># {{ current.name }}</h2>
            <p class="muted" style="margin: 0">{{ current.description }}</p>
          </div>
          <div style="display: flex; gap: 8px; align-items: center">
            <span class="tag">{{ current.members.length }} 位员工</span>
            <el-button size="small" @click="openDialog(current)">讨论设置</el-button>
          </div>
        </div>
        <div v-else class="chat-head"><h2>暂无频道</h2></div>
        <div class="chat-messages" ref="messageBox">
          <div v-if="current && !messages.length && !liveLines.length && !notice" class="empty">开始一次团队讨论。用 @员工名 唤醒对应员工。</div>
          <div v-for="message in messages" :key="message.id" class="msg" :class="{ user: message.sender === 'user' }">
            <div>
              <div class="muted">{{ speakerName(message.sender) }}</div>
              <div v-if="message.text" class="bubble">{{ message.text }}</div>
              <div class="message-attachments">
                <a v-for="file in message.attachments" :key="file.id" class="sent-attachment" :class="{ image: isImage(file.type) }" :href="attachmentUrl(file.id)" :download="file.name" target="_blank">
                  <img v-if="isImage(file.type)" :src="attachmentUrl(file.id)" :alt="file.name" />
                  <span><b>{{ file.name }}</b><small class="muted">{{ formatSize(file.size) }}</small></span>
                </a>
              </div>
            </div>
          </div>
          <div v-for="line in liveLines" :key="line.employeeId" class="msg">
            <div><div class="muted">{{ line.name }}</div><div class="bubble">{{ line.text }}</div></div>
          </div>
          <div v-if="notice" class="msg system"><div class="bubble">{{ notice }}</div></div>
        </div>
        <div class="chat-compose" v-if="current">
          <div class="chips" style="margin-bottom: 8px">
            <button v-for="employee in enabledMembers" :key="employee.id" class="chip" type="button" @click="insertMention(employee.name)">@{{ employee.name }}</button>
          </div>
          <div v-if="draftFiles.length" class="draft-attachments">
            <div v-for="file in draftFiles" :key="file.id" class="draft-file">
              <img v-if="isImage(file.type)" :src="attachmentUrl(file.id)" :alt="file.name" />
              <div><b>{{ file.name }}</b><small class="muted">{{ formatSize(file.size) }}</small></div>
              <el-button link type="danger" @click="draftFiles = draftFiles.filter((item) => item.id !== file.id)">移除</el-button>
            </div>
          </div>
          <div class="compose-box" :class="{ dropping }" @dragover.prevent="dropping = true" @dragleave="dropping = false" @drop.prevent="onDrop">
            <el-button @click="fileInput?.click()">附件</el-button>
            <input ref="fileInput" type="file" multiple hidden @change="onPick" />
            <textarea v-model="draft" rows="2" placeholder="发送消息，@数字员工，或拖入、粘贴图片…" @input="onInput" @paste="onPaste" @keydown.enter.exact.prevent="send" />
            <el-button type="primary" @click="send">发送</el-button>
          </div>
          <div v-if="mentionOpen" class="mention-box">
            <button v-for="employee in mentionMatches" :key="employee.id" type="button" @click="insertMention(employee.name)">
              {{ employee.avatar }} {{ employee.name }} · {{ employee.domain }}
            </button>
          </div>
        </div>
      </article>
      <aside class="panel aside" v-if="current">
        <div class="right-tabs">
          <button class="chip" :class="{ sel: sideTab === 'members' }" type="button" @click="sideTab = 'members'">成员</button>
          <button class="chip" :class="{ sel: sideTab === 'tasks' }" type="button" @click="sideTab = 'tasks'">任务</button>
        </div>
        <div v-if="sideTab === 'tasks'" style="padding: 16px">
          <TaskTable :tasks="tasks" />
        </div>
        <div v-else style="padding: 0 16px 16px">
        <div style="display: flex; justify-content: space-between; align-items: center">
          <b>讨论参与者</b>
          <el-button size="small" @click="openDialog(current)">＋ 调整成员</el-button>
        </div>
        <div class="member"><span class="avatar">👤</span><div><b>你</b><small class="muted">人类成员</small></div></div>
        <div v-for="employee in memberEmployees" :key="employee.id" class="member">
          <span class="avatar" :class="{ off: !employee.enabled }">{{ employee.avatar }}</span>
          <div><b>{{ employee.name }}</b><small class="muted">{{ employee.domain }} · {{ employee.enabled ? "启用" : "禁用" }}</small></div>
        </div>
        <p class="muted">员工之间的后续联系由 contact_employee 投递。Nexus 不代写同事回复。</p>
        </div>
      </aside>
    </div>
    <el-dialog v-model="dialogOpen" :title="editingId ? '编辑讨论' : '创建团队讨论'" width="520px">
      <el-form label-position="top">
        <el-form-item label="讨论名称" required><el-input v-model="form.name" maxlength="32" /></el-form-item>
        <el-form-item label="讨论目标" required><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="参与的数字员工">
          <el-checkbox-group v-model="form.memberIds">
            <el-checkbox v-for="employee in employees" :key="employee.id" :value="employee.id">
              {{ employee.avatar }} {{ employee.name }} · {{ employee.domain }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" @click="save">{{ editingId ? "保存讨论" : "创建讨论" }}</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  attachmentUrl,
  channelMessages,
  listChannels,
  listEmployees,
  readEventStream,
  saveChannel,
  sendChannel,
  uploadAttachment,
} from "../api";
import TaskTable from "../components/TaskTable.vue";
import { listTasks, type PlatformTask } from "../platform";
import type { Attachment, Channel, ChatMessage, Employee } from "../types";

const employees = ref<Employee[]>([]);
const channels = ref<Channel[]>([]);
const currentId = ref<string | null>(null);
const messages = ref<ChatMessage[]>([]);
const draft = ref("");
const draftFiles = ref<Attachment[]>([]);
const notice = ref("");
const liveLines = ref<Array<{ employeeId: string; name: string; text: string }>>([]);
const dropping = ref(false);
const seenEventIds = new Map<string, Set<string>>();
const messageBox = ref<HTMLElement | null>(null);
const dialogOpen = ref(false);
const editingId = ref<string | null>(null);
const mentionOpen = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const form = reactive({ name: "", description: "", memberIds: [] as string[] });
const sideTab = ref<"members" | "tasks">("members");
const tasks = ref<PlatformTask[]>([]);
let streamAbort: AbortController | null = null;

const current = computed(() => channels.value.find((item) => item.id === currentId.value) ?? null);
const memberEmployees = computed(() =>
  (current.value?.members ?? [])
    .map((member) => employees.value.find((item) => item.id === member.employee_id))
    .filter((item): item is Employee => Boolean(item)),
);
const enabledMembers = computed(() => memberEmployees.value.filter((item) => item.enabled));
const mentionMatches = computed(() => {
  const match = draft.value.match(/(?:^|\s)@([^\s]*)$/);
  if (!match) return [];
  return enabledMembers.value.filter((item) => item.name.includes(match[1] ?? ""));
});

function openDialog(channel?: Channel) {
  editingId.value = channel?.id ?? null;
  form.name = channel?.name ?? "";
  form.description = channel?.description ?? "";
  form.memberIds = channel
    ? channel.members.map((item) => item.employee_id)
    : employees.value.filter((item) => item.enabled).map((item) => item.id);
  dialogOpen.value = true;
}

async function reload() {
  employees.value = await listEmployees();
  channels.value = await listChannels();
  if (!channels.value.some((item) => item.id === currentId.value)) currentId.value = channels.value[0]?.id ?? null;
}

async function save() {
  if (!form.name.trim() || !form.description.trim()) {
    ElMessage.warning("请填写讨论名称和目标");
    return;
  }
  if (!form.memberIds.length) {
    ElMessage.warning("至少选择一名员工");
    return;
  }
  try {
    const saved = await saveChannel(
      { name: form.name.trim(), description: form.description.trim(), member_ids: form.memberIds },
      editingId.value ?? undefined,
    );
    dialogOpen.value = false;
    await reload();
    currentId.value = saved.id;
    ElMessage.success("讨论已保存");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败");
  }
}

function insertMention(name: string) {
  draft.value = draft.value.replace(/(?:^|\s)@[^\s]*$/, "").trim();
  draft.value = `${draft.value}${draft.value ? " " : ""}@${name} `;
  mentionOpen.value = false;
}
function onInput() {
  mentionOpen.value = mentionMatches.value.length > 0 && /(?:^|\s)@[^\s]*$/.test(draft.value);
}

function isImage(type: string) {
  return type.startsWith("image/");
}

function formatSize(size: number) {
  if (size < 1024) return "小于 1 KB";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1048576).toFixed(1)} MB`;
}

function speakerName(sender: string) {
  if (sender === "user") return "你";
  return employees.value.find((item) => item.id === sender)?.name ?? "数字员工";
}

async function addFileList(files: File[]) {
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

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}

async function followMember(channelId: string, employeeId: string, signal: AbortSignal, settled: Set<string>) {
  const seen = seenEventIds.get(employeeId) ?? new Set<string>();
  seenEventIds.set(employeeId, seen);
  const name = speakerName(employeeId);
  try {
    await readEventStream(
      `/api/v1/channels/${channelId}/members/${employeeId}/stream`,
      signal,
      (event) => {
        if (typeof event.id === "string") {
          if (seen.has(event.id)) return;
          seen.add(event.id);
        }
        if (event.type === "TEXT_BLOCK_DELTA" && typeof event.delta === "string") {
          const line = liveLines.value.find((item) => item.employeeId === employeeId);
          if (line) line.text += event.delta;
          else liveLines.value = [...liveLines.value, { employeeId, name, text: event.delta }];
        }
        if (event.type === "REPLY_END") {
          settled.add(employeeId);
          void channelMessages(channelId).then((payload) => {
            if (currentId.value !== channelId) return;
            messages.value = payload.messages;
            liveLines.value = liveLines.value.filter((item) => item.employeeId !== employeeId);
            if (payload.history_error) notice.value = payload.history_error;
          });
        }
        if (event.type === "NEXUS_UPSTREAM_ERROR") {
          settled.add(employeeId);
          notice.value = String(event.detail ?? "事件流中断");
        }
      },
    );
  } catch (error) {
    settled.add(employeeId);
    if (!signal.aborted) notice.value = error instanceof Error ? error.message : "事件流中断";
  }
}

async function watchMembers(channelId: string, signal: AbortSignal) {
  const watching = new Set<string>();
  const settled = new Set<string>();
  const started = Date.now();
  let quiet = 0;
  while (!signal.aborted && Date.now() - started < 120_000) {
    let payload;
    try {
      payload = await channelMessages(channelId);
    } catch {
      break;
    }
    if (signal.aborted || currentId.value !== channelId) return;
    const channel = channels.value.find((item) => item.id === channelId);
    if (channel) channel.members = payload.members;
    let opened = 0;
    for (const member of payload.members) {
      if (!member.agentscope_session_id || watching.has(member.employee_id)) continue;
      watching.add(member.employee_id);
      opened += 1;
      void followMember(channelId, member.employee_id, signal, settled);
    }
    const pending = [...watching].some((id) => !settled.has(id));
    if (opened || pending) quiet = 0;
    else quiet += 1;
    if (quiet >= 3) break;
    await delay(1000, signal);
  }
}

async function send() {
  if (!current.value) return;
  const text = draft.value.trim();
  if (!text && !draftFiles.value.length) return;
  const channelId = current.value.id;
  try {
    const result = await sendChannel(channelId, text, draftFiles.value.map((item) => item.id));
    messages.value = [...messages.value, result.message];
    draft.value = "";
    draftFiles.value = [];
    mentionOpen.value = false;
    const rejected = result.triggered.filter((item) => !item.accepted);
    if (!result.triggered.length) {
      notice.value = "没有点名已启用的员工，因此没有触发任何人。";
      return;
    }
    notice.value = rejected.map((item) => `${item.name}：${item.detail}`).filter(Boolean).join(" ");
    stopStream();
    liveLines.value = [];
    const controller = new AbortController();
    streamAbort = controller;
    await watchMembers(channelId, controller.signal);
    if (streamAbort === controller) stopStream();
  } catch (error) {
    if (!(error instanceof DOMException)) {
      ElMessage.error(error instanceof Error ? error.message : "发送失败");
    }
  }
}

async function refreshTasks() {
  if (!current.value || sideTab.value !== "tasks") return;
  const collected = new Map<string, PlatformTask>();
  try {
    for (const item of await listTasks({ source_channel_id: current.value.id })) collected.set(item.id, item);
    for (const member of current.value.members) {
      for (const item of await listTasks({ responsible_employee_id: member.employee_id })) {
        collected.set(item.id, item);
      }
    }
  } catch {
    tasks.value = [];
    return;
  }
  tasks.value = [...collected.values()];
}

watch([sideTab, currentId], () => {
  void refreshTasks();
});

watch(currentId, async (id) => {
  stopStream();
  liveLines.value = [];
  notice.value = "";
  if (!id) {
    messages.value = [];
    return;
  }
  const payload = await channelMessages(id);
  messages.value = payload.messages;
  if (payload.history_error) notice.value = payload.history_error;
});

watch([messages, liveLines], async () => {
  await nextTick();
  if (messageBox.value) messageBox.value.scrollTop = messageBox.value.scrollHeight;
});

let taskTimer = 0;
onMounted(() => {
  void reload();
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
.mention-box { margin-top: 8px; background: white; border: 1px solid #dbece0; border-radius: 12px; padding: 6px; }
.mention-box button { display: block; width: 100%; text-align: left; border: 0; background: transparent; padding: 8px; cursor: pointer; }
.compose-box.dropping { outline: 2px dashed #187956; }
.sent-attachment.image, .draft-file { display: flex; gap: 8px; align-items: center; }
.sent-attachment img, .draft-file img { width: 72px; height: 72px; object-fit: cover; border-radius: 8px; }
</style>
