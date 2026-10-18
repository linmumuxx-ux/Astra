<template>
  <div class="chat-compose">
    <!-- Optional @ mention candidate chips for group -->
    <div v-if="mentionCandidates?.length" class="chips" style="margin-bottom: 8px">
      <button
        v-for="employee in mentionCandidates"
        :key="employee.id"
        class="chip"
        type="button"
        :disabled="disabled"
        @click="insertMention(employee.name)"
      >
        @{{ employee.name }}
      </button>
    </div>

    <!-- Draft attachments preview -->
    <div v-if="draftFiles.length" class="draft-attachments">
      <div v-for="file in draftFiles" :key="file.id" class="draft-file">
        <img v-if="isImage(file.type)" :src="attachmentUrl(file.id)" :alt="file.name" />
        <div>
          <b>{{ file.name }}</b>
          <small class="muted">{{ formatSize(file.size) }}</small>
        </div>
        <el-button link type="danger" @click="draftFiles = draftFiles.filter((item) => item.id !== file.id)">
          移除
        </el-button>
      </div>
    </div>

    <!-- Input box with attach button, textarea, send button -->
    <div
      class="compose-box"
      :class="{ dropping }"
      @dragover.prevent="onDragOver"
      @dragleave="dropping = false"
      @drop.prevent="onDrop"
    >
      <el-button
        :disabled="disabled"
        data-testid="compose-attach"
        @click="fileInput?.click()"
      >
        附件
      </el-button>
      <input ref="fileInput" type="file" multiple hidden @change="onPick" />

      <textarea
        ref="textareaRef"
        v-model="draft"
        :disabled="disabled"
        rows="2"
        :placeholder="placeholder || '发送消息，或拖入、粘贴图片…'"
        data-testid="compose-input"
        @input="onInput"
        @paste="onPaste"
        @keydown.enter.exact.prevent="handleSubmit"
      />

      <el-button
        type="primary"
        :disabled="disabled || (!draft.trim() && !draftFiles.length)"
        data-testid="compose-send"
        @click="handleSubmit"
      >
        发送
      </el-button>
    </div>

    <!-- Autocomplete popup for @ mentions -->
    <div v-if="mentionOpen && mentionMatches.length" class="mention-box">
      <button
        v-for="employee in mentionMatches"
        :key="employee.id"
        type="button"
        @click="insertMention(employee.name)"
      >
        {{ employee.avatar }} {{ employee.name }} · {{ employee.domain }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { attachmentUrl, uploadAttachment } from "@/api";
import type { Attachment, Employee } from "@/types";
import { formatSize, isImage } from "./format";

const props = defineProps<{
  disabled?: boolean;
  placeholder?: string;
  mentionCandidates?: Employee[];
  submit: (payload: { text: string; attachmentIds: string[] }) => Promise<boolean>;
}>();

const busy = ref(false);

const draft = ref("");
const draftFiles = ref<Attachment[]>([]);
const dropping = ref(false);
const mentionOpen = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const textareaRef = ref<HTMLTextAreaElement | null>(null);

const mentionMatches = computed(() => {
  if (!props.mentionCandidates || !props.mentionCandidates.length) return [];
  const match = draft.value.match(/(?:^|\s)@([^\s]*)$/);
  if (!match) return [];
  const query = (match[1] ?? "").toLowerCase();
  return props.mentionCandidates.filter((item) => item.name.toLowerCase().includes(query));
});

function onInput() {
  mentionOpen.value = Boolean(
    props.mentionCandidates?.length &&
      mentionMatches.value.length > 0 &&
      /(?:^|\s)@[^\s]*$/.test(draft.value),
  );
}

function insertMention(name: string) {
  draft.value = draft.value.replace(/(?:^|\s)@[^\s]*$/, "").trim();
  draft.value = `${draft.value}${draft.value ? " " : ""}@${name} `;
  mentionOpen.value = false;
  textareaRef.value?.focus();
}

async function addFileList(files: File[]) {
  if (props.disabled) return;
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
      const uploaded = await uploadAttachment(named);
      draftFiles.value.push(uploaded);
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

function onDragOver() {
  if (!props.disabled) {
    dropping.value = true;
  }
}

function onDrop(event: DragEvent) {
  dropping.value = false;
  if (props.disabled) return;
  void addFileList(Array.from(event.dataTransfer?.files ?? []));
}

function onPaste(event: ClipboardEvent) {
  if (props.disabled) return;
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

async function handleSubmit() {
  if (props.disabled || busy.value) return;
  const text = draft.value.trim();
  const attachmentIds = draftFiles.value.map((item) => item.id);
  if (!text && !attachmentIds.length) return;
  busy.value = true;
  try {
    // Keep the draft when the send is refused so nothing typed is lost.
    if (!(await props.submit({ text, attachmentIds }))) return;
    draft.value = "";
    draftFiles.value = [];
    mentionOpen.value = false;
  } finally {
    busy.value = false;
  }
}
</script>

<style scoped>
.compose-box.dropping {
  outline: 2px dashed #187956;
}
.draft-file {
  display: flex;
  gap: 8px;
  align-items: center;
}
.draft-file img {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 8px;
}
.mention-box {
  margin-top: 8px;
  background: white;
  border: 1px solid #dbece0;
  border-radius: 12px;
  padding: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}
.mention-box button {
  display: block;
  width: 100%;
  text-align: left;
  border: 0;
  background: transparent;
  padding: 8px;
  cursor: pointer;
  border-radius: 8px;
}
.mention-box button:hover {
  background: #f3faf6;
}
</style>
