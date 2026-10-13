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
        <div class="chat-messages">
          <div v-if="current && !messages.length && !notice" class="empty">开始一次团队讨论。用 @员工名 唤醒对应员工。</div>
          <div v-for="message in messages" :key="message.id" class="msg user">
            <div>
              <div class="muted">你</div>
              <div v-if="message.text" class="bubble">{{ message.text }}</div>
              <div class="message-attachments">
                <a v-for="file in message.attachments" :key="file.id" class="sent-attachment" :href="attachmentUrl(file.id)" target="_blank">{{ file.name }}</a>
              </div>
            </div>
          </div>
          <div v-for="(line, index) in liveLines" :key="index" class="msg">
            <div><div class="muted">{{ line.name }}</div><div class="bubble">{{ line.text }}</div></div>
          </div>
          <div v-if="notice" class="msg system"><div class="bubble">{{ notice }}</div></div>
        </div>
        <div class="chat-compose" v-if="current">
          <div class="chips" style="margin-bottom: 8px">
            <button v-for="employee in enabledMembers" :key="employee.id" class="chip" type="button" @click="insertMention(employee.name)">@{{ employee.name }}</button>
          </div>
          <div class="compose-box">
            <el-button @click="fileInput?.click()">附件</el-button>
            <input ref="fileInput" type="file" multiple hidden @change="addFiles" />
            <textarea v-model="draft" rows="2" placeholder="发送消息，@数字员工…" @input="onInput" @keydown.enter.exact.prevent="send" />
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
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
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
import type { Attachment, Channel, ChatMessage, Employee } from "../types";

const employees = ref<Employee[]>([]);
const channels = ref<Channel[]>([]);
const currentId = ref<string | null>(null);
const messages = ref<ChatMessage[]>([]);
const draft = ref("");
const draftFiles = ref<Attachment[]>([]);
const notice = ref("");
const liveLines = ref<Array<{ name: string; text: string }>>([]);
const dialogOpen = ref(false);
const editingId = ref<string | null>(null);
const mentionOpen = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const form = reactive({ name: "", description: "", memberIds: [] as string[] });
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
  form.memberIds = channel ? channel.members.map((item) => item.employee_id) : enabledMembers.value.map((item) => item.id);
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

async function addFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = "";
  for (const file of files.slice(0, 6 - draftFiles.value.length)) {
    if (!file.size || file.size > 20 * 1024 * 1024) {
      ElMessage.warning(!file.size ? "不能添加空文件" : "单个附件不能超过 20 MB");
      continue;
    }
    draftFiles.value.push(await uploadAttachment(file));
  }
}

function stopStream() {
  streamAbort?.abort();
  streamAbort = null;
}

async function send() {
  if (!current.value) return;
  const text = draft.value.trim();
  if (!text && !draftFiles.value.length) return;
  try {
    const result = await sendChannel(current.value.id, text, draftFiles.value.map((item) => item.id));
    messages.value = [...messages.value, result.message];
    draft.value = "";
    draftFiles.value = [];
    mentionOpen.value = false;
    const accepted = result.triggered.filter((item) => item.accepted);
    const rejected = result.triggered.filter((item) => !item.accepted);
    if (!result.triggered.length) {
      notice.value = "没有点名已启用的员工，因此没有触发任何人。";
      return;
    }
    notice.value = rejected.map((item) => `${item.name}：${item.detail}`).filter(Boolean).join(" ");
    stopStream();
    streamAbort = new AbortController();
    liveLines.value = accepted.map((item) => ({ name: item.name, text: "" }));
    await Promise.all(
      accepted.map(async (item, index) => {
        await readEventStream(
          `/api/v1/channels/${current.value?.id}/members/${item.employee_id}/stream`,
          streamAbort!.signal,
          (event) => {
            if (event.type === "TEXT_BLOCK_DELTA" && typeof event.delta === "string") {
              const line = liveLines.value[index];
              if (line) line.text += event.delta;
            }
          },
        );
      }),
    );
  } catch (error) {
    if (!(error instanceof DOMException)) {
      ElMessage.error(error instanceof Error ? error.message : "发送失败");
    }
  }
}

watch(currentId, async (id) => {
  stopStream();
  liveLines.value = [];
  notice.value = "";
  if (!id) {
    messages.value = [];
    return;
  }
  messages.value = (await channelMessages(id)).messages;
});

onMounted(reload);
onBeforeUnmount(stopStream);
</script>

<style scoped>
.rail-item { width: 100%; border: 0; background: transparent; text-align: left; }
.mention-box { margin-top: 8px; background: white; border: 1px solid #dbece0; border-radius: 12px; padding: 6px; }
.mention-box button { display: block; width: 100%; text-align: left; border: 0; background: transparent; padding: 8px; cursor: pointer; }
</style>
