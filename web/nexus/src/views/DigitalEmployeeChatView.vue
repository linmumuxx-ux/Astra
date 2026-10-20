<template>
  <section>
    <div class="title-row">
      <h1 class="h-title">数字员工</h1>
    </div>
    <div class="workspace" :class="{ 'workspace--focus': currentKind === 'contact' && !materialsOpen }">
      <!-- Left Rail: Conversation List -->
      <ConversationList
        :employees="employees"
        :channels="channels"
        :current-kind="currentKind"
        :current-id="currentId"
        :default-filter="defaultFilter"
        @select="onSelectConversation"
        @create-group="openCreateGroupDialog"
      />

      <!-- Middle: Chat Pane -->
      <article class="panel chat">
        <div class="chat-head" v-if="currentKind === 'contact' && currentContact">
          <div>
            <h2 style="margin: 0 0 4px">{{ currentContact.name }} · {{ currentContact.domain }}</h2>
          </div>
          <el-button @click="materialsOpen = !materialsOpen">
            {{ materialsOpen ? "收起资料" : "查看资料" }}
          </el-button>
        </div>
        <div class="chat-head" v-else-if="currentKind === 'group' && currentGroup">
          <div style="display: flex; gap: 8px; align-items: center">
            <h2 style="margin: 0"># {{ currentGroup.name }}</h2>
            <span class="tag">{{ currentGroup.members.length }} 位成员</span>
          </div>
          <el-button size="small" @click="openEditGroupDialog(currentGroup)">
            群组设置
          </el-button>
        </div>
        <div class="chat-head" v-else>
          <h2>{{ currentKind === "group" ? "暂无群组" : "暂无联系人" }}</h2>
        </div>

        <!-- Messages list -->
        <MessagePane
          :messages="currentMessages"
          :live-entries="currentLive"
          :notice="currentNotice"
          :empty-text="emptyText"
          :speaker-label="getSpeakerLabel"
        />

        <!-- Compose Box -->
        <ComposeBox
          v-if="currentId"
          :disabled="composeDisabled"
          :placeholder="composePlaceholder"
          :key="`${currentKind}:${currentId}`"
          :mention-candidates="composeMentionCandidates"
          :submit="handleSend"
        />
      </article>

      <!-- Right Aside: Type-Aware Tabs -->
      <aside
        class="panel aside"
        v-if="(currentKind === 'contact' && currentContact && materialsOpen) || (currentKind === 'group' && currentGroup)"
      >
        <!-- Contact Aside: 任务 | 资料 | 记忆 -->
        <template v-if="currentKind === 'contact' && currentContact">
          <div class="right-tabs">
            <button
              class="chip"
              :class="{ sel: contactTab === 'tasks' }"
              type="button"
              @click="contactTab = 'tasks'"
            >
              任务
            </button>
            <button
              class="chip"
              :class="{ sel: contactTab === 'materials' }"
              type="button"
              @click="contactTab = 'materials'"
            >
              资料
            </button>
            <button
              class="chip"
              :class="{ sel: contactTab === 'memory' }"
              type="button"
              @click="contactTab = 'memory'"
            >
              记忆
            </button>
          </div>

          <div v-if="contactTab === 'tasks'" style="padding: 16px">
            <div v-if="!tasks.length" class="muted">暂无关联任务</div>
            <TaskRail v-else :tasks="tasks" :names="nameById" hide-responsible />
          </div>

          <div v-else-if="contactTab === 'materials'" style="padding: 16px">
            <div class="section-label">职责范围</div>
            <div class="detail-excerpt">{{ currentContact.description }}</div>
            <div class="section-label">工作指令</div>
            <div class="detail-excerpt">{{ currentContact.instructions }}</div>
            <div class="section-label">知识</div>
            <div class="resource-list">
              <span v-for="item in currentContact.knowledge" :key="item" class="mini-chip">
                {{ resourceLabel(catalogs.knowledge, item) }}
              </span>
              <span v-if="!currentContact.knowledge.length" class="muted">暂无</span>
            </div>
            <div class="section-label">技能</div>
            <div class="resource-list">
              <span v-for="item in currentContact.skills" :key="item" class="mini-chip">
                {{ resourceLabel(catalogs.skills, item) }}
              </span>
              <span v-if="!currentContact.skills.length" class="muted">暂无</span>
            </div>
            <div class="section-label">工具</div>
            <div class="resource-list">
              <span v-for="item in currentContact.tools" :key="item" class="mini-chip">
                {{ toolLabel(item) }}
              </span>
              <span v-if="!currentContact.tools.length" class="muted">暂无</span>
            </div>
          </div>

          <div v-else style="padding: 16px">
            <div class="section-label">会话</div>
            <div class="mono">{{ contactSession.conversation.value?.agentscope_session_id || "发送后才会创建" }}</div>
            <div v-if="latestReply" class="detail-excerpt" style="margin-top: 12px">{{ latestReply }}</div>
          </div>
        </template>

        <!-- Group Aside: 任务 | 成员 | 资料 -->
        <template v-else-if="currentKind === 'group' && currentGroup">
          <div class="right-tabs">
            <button
              class="chip"
              :class="{ sel: groupTab === 'tasks' }"
              type="button"
              @click="groupTab = 'tasks'"
            >
              任务
            </button>
            <button
              class="chip"
              :class="{ sel: groupTab === 'members' }"
              type="button"
              @click="groupTab = 'members'"
            >
              成员
            </button>
            <button
              class="chip"
              :class="{ sel: groupTab === 'materials' }"
              type="button"
              @click="groupTab = 'materials'"
            >
              资料
            </button>
          </div>

          <div v-if="groupTab === 'tasks'" style="padding: 16px">
            <div v-if="!tasks.length" class="muted">暂无关联任务</div>
            <TaskRail v-else :tasks="tasks" :names="nameById" />
          </div>

          <div v-else-if="groupTab === 'members'" style="padding: 0 16px 16px">
            <div style="display: flex; justify-content: space-between; align-items: center; margin: 14px 0 10px">
              <b>群组成员</b>
              <el-button size="small" @click="openEditGroupDialog(currentGroup)">调整成员</el-button>
            </div>
            <div class="member">
              <span class="avatar">👤</span>
              <div><b>你</b><small class="muted">人类成员</small></div>
            </div>
            <div v-for="emp in currentGroupEmployees" :key="emp.id" class="member">
              <span class="avatar" :class="{ off: !emp.enabled }">{{ emp.avatar }}</span>
              <div>
                <b>{{ emp.name }}</b>
                <small class="muted">{{ emp.domain }} · {{ emp.enabled ? "启用" : "禁用" }}</small>
              </div>
            </div>
          </div>

          <div v-else style="padding: 16px">
            <div class="section-label">群组名称</div>
            <div class="detail-excerpt">{{ currentGroup.name }}</div>
            <div class="section-label">群组目标</div>
            <div class="detail-excerpt">{{ currentGroup.description }}</div>
          </div>
        </template>
      </aside>
    </div>

    <!-- Create / Edit Group Dialog -->
    <el-dialog v-model="dialogOpen" :title="editingId ? '编辑群组' : '创建群组'" width="520px">
      <el-form label-position="top">
        <el-form-item label="群组名称" required>
          <el-input v-model="form.name" maxlength="32" />
        </el-form-item>
        <el-form-item label="群组目标" required>
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="参与的数字员工">
          <el-checkbox-group v-model="form.memberIds">
            <el-checkbox v-for="emp in employees" :key="emp.id" :value="emp.id">
              {{ emp.avatar }} {{ emp.name }} · {{ emp.domain }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" @click="saveGroupForm">
          {{ editingId ? "保存群组" : "创建群组" }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  currentUid,
  getKnowledge,
  getSkills,
  getTools,
  listChannels,
  listEmployees,
  saveChannel,
} from "@/api";
import TaskRail from "@/components/TaskRail.vue";
import { listTasks, listWorkers, type PlatformTask, type PlatformWorker } from "@/platform";
import type { Channel, ChannelMember, ChatMessage, Employee, ResourceCatalog } from "@/types";
import ComposeBox from "@/features/chat/ComposeBox.vue";
import ConversationList from "@/features/chat/ConversationList.vue";
import MessagePane from "@/features/chat/MessagePane.vue";
import type { ConversationKind } from "@/features/chat/types";
import { useContactSession } from "@/features/chat/useContactSession";
import { useGroupSession } from "@/features/chat/useGroupSession";

const route = useRoute();
const router = useRouter();

const employees = ref<Employee[]>([]);
const channels = ref<Channel[]>([]);
const workers = ref<PlatformWorker[]>([]);

const currentKind = ref<ConversationKind | null>(null);
const currentId = ref<string | null>(null);
const defaultFilter = ref<"all" | "contact" | "group">("all");

const materialsOpen = ref(true);
const contactTab = ref<"tasks" | "materials" | "memory">("tasks");
const groupTab = ref<"tasks" | "members" | "materials">("tasks");
const tasks = ref<PlatformTask[]>([]);

const emptyCatalog = (): ResourceCatalog => ({ available: false, items: [] });
const catalogs = ref({ skills: emptyCatalog(), knowledge: emptyCatalog(), tools: emptyCatalog() });

const currentContact = computed(() => {
  if (currentKind.value !== "contact") return null;
  return employees.value.find((e) => e.id === currentId.value) ?? null;
});

const currentGroup = computed(() => {
  if (currentKind.value !== "group") return null;
  return channels.value.find((c) => c.id === currentId.value) ?? null;
});

const currentGroupEmployees = computed(() => {
  if (!currentGroup.value) return [];
  return (currentGroup.value.members ?? [])
    .map((member) => employees.value.find((item) => item.id === member.employee_id))
    .filter((item): item is Employee => Boolean(item));
});

const enabledGroupMembers = computed(() => currentGroupEmployees.value.filter((item) => item.enabled));

const nameById = computed(() => {
  const names: Record<string, string> = {};
  for (const employee of employees.value) names[employee.id] = employee.name;
  for (const worker of workers.value) names[worker.id] = worker.name;
  return names;
});

function speakerName(sender: string) {
  return employees.value.find((item) => item.id === sender)?.name ?? sender;
}

function getSpeakerLabel(message: ChatMessage): string {
  const speaker = message.speaker || "";
  const me = currentUid();
  if (message.sender === "user" && (!speaker || speaker === "user" || (me && speaker === me))) {
    return "你";
  }
  if (speaker && speaker !== "user") {
    return employees.value.find((item) => item.id === speaker)?.name ?? speaker;
  }
  return speakerName(message.sender);
}

function resourceLabel(catalog: ResourceCatalog, id: string) {
  return catalog.items.find((item) => item.id === id)?.name ?? id;
}

function toolLabel(id: string) {
  if (id === "contact_employee") return "联系其他数字员工";
  const name = resourceLabel(catalogs.value.tools, id);
  return name === id ? "工作区工具" : name;
}

// Adapters
const contactSession = useContactSession(() => currentContact.value);
const groupSession = useGroupSession({
  getSpeakerName: (id: string) => speakerName(id),
  onMembersUpdated: (channelId: string, members: ChannelMember[]) => {
    const channel = channels.value.find((c) => c.id === channelId);
    if (channel) channel.members = members;
  },
});

const currentMessages = computed(() => {
  return currentKind.value === "contact" ? contactSession.messages.value : groupSession.messages.value;
});

const currentLive = computed(() => {
  return currentKind.value === "contact" ? contactSession.live.value : groupSession.live.value;
});

const currentNotice = computed(() => {
  if (loadError.value) return loadError.value;
  return currentKind.value === "contact" ? contactSession.notice.value : groupSession.notice.value;
});

const emptyText = computed(() => {
  if (currentKind.value === "contact") {
    return currentContact.value ? `与 ${currentContact.value.name} 开始交流` : "还没有员工可以交流";
  }
  return "用 @员工名 唤醒对应员工";
});

const composeDisabled = computed(() => {
  if (currentKind.value === "contact") {
    return !currentContact.value?.enabled || contactSession.sending.value;
  }
  if (currentKind.value === "group") {
    return groupSession.sending.value;
  }
  return true;
});

const composePlaceholder = computed(() => {
  if (currentKind.value === "contact") {
    return currentContact.value?.enabled
      ? "发送消息，或拖入、粘贴图片…"
      : "该员工已禁用，历史消息仍可查看";
  }
  return "发送消息，@数字员工，或拖入、粘贴图片…";
});

const composeMentionCandidates = computed(() => {
  if (currentKind.value === "group") {
    return enabledGroupMembers.value;
  }
  return undefined;
});

const latestReply = computed(() => {
  return [...contactSession.messages.value].reverse().find((item) => item.sender !== "user")?.text ?? "";
});

async function handleSend(payload: { text: string; attachmentIds: string[] }): Promise<boolean> {
  if (currentKind.value === "contact") return contactSession.send(payload.text, payload.attachmentIds);
  if (currentKind.value === "group") return groupSession.send(payload.text, payload.attachmentIds);
  return false;
}

// Task management
let taskToken = 0;
async function refreshTasks() {
  const token = ++taskToken;
  if (currentKind.value === "contact") {
    const sessionId = contactSession.conversation.value?.agentscope_session_id;
    if (!sessionId) {
      tasks.value = [];
      return;
    }
    try {
      const items = await listTasks({ source_session_id: sessionId });
      if (token !== taskToken) return;
      tasks.value = items;
    } catch {
      if (token !== taskToken) return;
      tasks.value = [];
    }
  } else if (currentKind.value === "group") {
    const channelId = currentId.value;
    if (!channelId) {
      tasks.value = [];
      return;
    }
    try {
      const items = await listTasks({ source_channel_id: channelId });
      if (token !== taskToken) return;
      tasks.value = items;
    } catch {
      if (token !== taskToken) return;
      tasks.value = [];
    }
  } else {
    tasks.value = [];
  }
}

watch(
  () => contactSession.conversation.value?.agentscope_session_id,
  (newId, oldId) => {
    if (newId && newId !== oldId) {
      void refreshTasks();
    }
  },
);

watch([contactTab, groupTab], () => {
  void refreshTasks();
});

// Selection handling
async function selectContact(id: string, replaceQuery = true) {
  if (currentKind.value === "contact" && currentId.value === id) return;
  groupSession.close();
  currentKind.value = "contact";
  currentId.value = id;
  localStorage.setItem("nexus.chat.last", `contact:${id}`);
  if (replaceQuery) {
    await router.replace({ path: "/chat", query: { employee: id } });
  }
  tasks.value = [];
  await contactSession.open(id);
  void refreshTasks();
}

async function selectGroup(id: string, replaceQuery = true) {
  if (currentKind.value === "group" && currentId.value === id) return;
  contactSession.close();
  currentKind.value = "group";
  currentId.value = id;
  localStorage.setItem("nexus.chat.last", `group:${id}`);
  if (replaceQuery) {
    await router.replace({ path: "/chat", query: { channel: id } });
  }
  tasks.value = [];
  await groupSession.open(id);
  void refreshTasks();
}

function onSelectConversation(payload: { kind: ConversationKind; id: string }) {
  if (payload.kind === "contact") {
    void selectContact(payload.id, true);
  } else {
    void selectGroup(payload.id, true);
  }
}

// Dialog management
const dialogOpen = ref(false);
const editingId = ref<string | null>(null);
const form = reactive({ name: "", description: "", memberIds: [] as string[] });

function openCreateGroupDialog() {
  editingId.value = null;
  form.name = "";
  form.description = "";
  form.memberIds = employees.value.filter((item) => item.enabled).map((item) => item.id);
  dialogOpen.value = true;
}

function openEditGroupDialog(channel: Channel) {
  editingId.value = channel.id;
  form.name = channel.name;
  form.description = channel.description;
  form.memberIds = channel.members.map((item) => item.employee_id);
  dialogOpen.value = true;
}

async function saveGroupForm() {
  if (!form.name.trim() || !form.description.trim()) {
    ElMessage.warning("请填写群组名称和目标");
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
    channels.value = await listChannels();
    await selectGroup(saved.id, true);
    ElMessage.success("群组已保存");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败");
  }
}

// Route synchronization
async function initSelection() {
  const queryEmp = typeof route.query.employee === "string" ? route.query.employee : null;
  const queryChan = typeof route.query.channel === "string" ? route.query.channel : null;
  const queryKind = typeof route.query.kind === "string" ? route.query.kind : null;

  if (queryEmp && employees.value.some((e) => e.id === queryEmp)) {
    await selectContact(queryEmp, false);
    return;
  }

  if (queryChan && channels.value.some((c) => c.id === queryChan)) {
    await selectGroup(queryChan, false);
    return;
  }

  if (queryKind === "group") {
    defaultFilter.value = "group";
    if (channels.value.length > 0) {
      await selectGroup(channels.value[0].id, true);
      return;
    }
  }

  const last = localStorage.getItem("nexus.chat.last");
  if (last) {
    if (last.startsWith("contact:")) {
      const id = last.slice(8);
      if (employees.value.some((e) => e.id === id)) {
        await selectContact(id, true);
        return;
      }
    } else if (last.startsWith("group:")) {
      const id = last.slice(6);
      if (channels.value.some((c) => c.id === id)) {
        await selectGroup(id, true);
        return;
      }
    }
  }

  if (employees.value.length > 0) {
    await selectContact(employees.value[0].id, true);
  } else if (channels.value.length > 0) {
    await selectGroup(channels.value[0].id, true);
  }
}

watch(
  () => [route.query.employee, route.query.channel, route.query.kind],
  async ([emp, chan, kind]) => {
    if (typeof emp === "string" && emp) {
      if (currentKind.value !== "contact" || currentId.value !== emp) {
        if (employees.value.some((e) => e.id === emp)) {
          await selectContact(emp, false);
        }
      }
      return;
    }
    if (typeof chan === "string" && chan) {
      if (currentKind.value !== "group" || currentId.value !== chan) {
        if (channels.value.some((c) => c.id === chan)) {
          await selectGroup(chan, false);
        }
      }
      return;
    }
    if (kind === "group") {
      defaultFilter.value = "group";
      if (channels.value.length > 0 && currentKind.value !== "group") {
        await selectGroup(channels.value[0].id, true);
      }
    }
  },
);

let taskTimer = 0;

const loadError = ref("");
onMounted(async () => {
  // Catalogs and Workers only decorate the side panel; their failure must not block chatting.
  const [skills, knowledge, tools] = await Promise.all([
    getSkills().catch(emptyCatalog),
    getKnowledge().catch(emptyCatalog),
    getTools().catch(emptyCatalog),
  ]);
  catalogs.value = { skills, knowledge, tools };
  workers.value = await listWorkers().catch(() => []);
  try {
    [employees.value, channels.value] = await Promise.all([listEmployees(), listChannels()]);
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : "无法读取数字员工";
  }

  await initSelection();
  taskTimer = window.setInterval(() => void refreshTasks(), 8000);
});

onBeforeUnmount(() => {
  contactSession.close();
  groupSession.close();
  window.clearInterval(taskTimer);
});
</script>

<style scoped>
.chip.sel {
  background: #e5f6ed;
  border-color: #aad8c2;
  color: #187956;
}
</style>
