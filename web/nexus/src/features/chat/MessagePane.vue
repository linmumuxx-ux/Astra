<template>
  <div class="chat-messages" ref="messageBox" data-testid="msg-list">
    <div v-if="!messages.length && !hasLive && !notice" class="empty">
      {{ emptyText || "暂无消息" }}
    </div>

    <div
      v-for="message in messages"
      :key="message.id"
      class="msg"
      :class="{ user: message.sender === 'user' }"
      data-testid="msg-item"
    >
      <div>
        <div class="muted">{{ getSpeaker(message) }}</div>
        <div v-if="message.text" class="bubble markdown" v-html="renderMarkdown(message.text)"></div>

        <template v-for="tool in message.tools || []" :key="tool.id">
          <!-- contact_employee tool: compact status chip -->
          <div v-if="tool.name === 'contact_employee'" class="collab-status-block">
            <span
              class="mini-chip collab-status-chip"
              :class="{ 'collab-status-chip--error': formatContactEmployeeTool(tool.input, tool.output).isError }"
              data-testid="collab-status"
            >
              🤝 {{ formatContactEmployeeTool(tool.input, tool.output).text }}
            </span>
            <el-collapse
              v-if="!formatContactEmployeeTool(tool.input, tool.output).isJson && (tool.input || tool.output)"
              class="tool-collapse"
            >
              <el-collapse-item title="详情" name="raw">
                <pre v-if="tool.input" class="tool-pre">{{ tool.input }}</pre>
                <pre v-if="tool.output" class="tool-pre">{{ tool.output }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>

          <!-- Other tools: compact card with collapsed details -->
          <div v-else class="tool-card">
            <div class="tool-card-head">
              <b>{{ tool.name || "工具" }}</b>
              <small v-if="tool.state === 'error'" class="muted" style="color: #b42318; margin-left: 8px">工具失败</small>
            </div>
            <el-collapse v-if="tool.input || tool.output" class="tool-collapse">
              <el-collapse-item title="详情" name="details">
                <pre v-if="tool.input" class="tool-pre"><strong>输入:</strong><br />{{ tool.input }}</pre>
                <pre v-if="tool.output" class="tool-pre"><strong>输出:</strong><br />{{ tool.output }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </template>

        <div v-if="message.attachments?.length" class="message-attachments">
          <a
            v-for="file in message.attachments"
            :key="file.id"
            class="sent-attachment"
            :class="{ image: isImage(file.type) }"
            :href="attachmentUrl(file.id)"
            :download="file.name"
            target="_blank"
          >
            <img v-if="isImage(file.type)" :src="attachmentUrl(file.id)" :alt="file.name" />
            <span><b>{{ file.name }}</b><small class="muted">{{ formatSize(file.size) }}</small></span>
          </a>
        </div>
      </div>
    </div>

    <!-- Live entries (streaming text & tools) -->
    <div v-for="(entry, index) in liveEntries || []" :key="entry.employeeId || index" class="msg">
      <div>
        <div class="muted">{{ entry.name }}</div>
        <div v-if="entry.text" class="bubble markdown" v-html="renderMarkdown(entry.text)"></div>

        <template v-for="tool in entry.tools || []" :key="tool.id">
          <div v-if="tool.name === 'contact_employee'" class="collab-status-block">
            <span
              class="mini-chip collab-status-chip"
              :class="{ 'collab-status-chip--error': formatContactEmployeeTool(tool.input, tool.output).isError }"
              data-testid="collab-status"
            >
              🤝 {{ formatContactEmployeeTool(tool.input, tool.output).text }}
            </span>
            <el-collapse
              v-if="!formatContactEmployeeTool(tool.input, tool.output).isJson && (tool.input || tool.output)"
              class="tool-collapse"
            >
              <el-collapse-item title="详情" name="raw">
                <pre v-if="tool.input" class="tool-pre">{{ tool.input }}</pre>
                <pre v-if="tool.output" class="tool-pre">{{ tool.output }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
          <div v-else class="tool-card">
            <div class="tool-card-head">
              <b>{{ tool.name || "工具" }}</b>
            </div>
            <el-collapse v-if="tool.input || tool.output" class="tool-collapse">
              <el-collapse-item title="详情" name="details">
                <pre v-if="tool.input" class="tool-pre"><strong>输入:</strong><br />{{ tool.input }}</pre>
                <pre v-if="tool.output" class="tool-pre"><strong>输出:</strong><br />{{ tool.output }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>
        </template>
      </div>
    </div>

    <div v-if="notice" class="msg system">
      <div class="bubble">{{ notice }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { attachmentUrl } from "@/api";
import type { ChatMessage } from "@/types";
import { formatContactEmployeeTool, formatSize, isImage, renderMarkdown } from "./format";
import type { LiveEntry } from "./types";

const props = defineProps<{
  messages: ChatMessage[];
  liveEntries?: LiveEntry[];
  notice?: string;
  emptyText?: string;
  speakerLabel?: (message: ChatMessage) => string;
}>();

const messageBox = ref<HTMLElement | null>(null);

const hasLive = computed(() => {
  if (!props.liveEntries?.length) return false;
  return props.liveEntries.some((entry) => Boolean(entry.text?.trim() || entry.tools?.length));
});

function getSpeaker(message: ChatMessage): string {
  if (props.speakerLabel) {
    return props.speakerLabel(message);
  }
  if (message.sender === "user") {
    return message.speaker || "你";
  }
  return message.speaker || message.sender || "数字员工";
}

async function scrollToBottom() {
  await nextTick();
  if (messageBox.value) {
    messageBox.value.scrollTop = messageBox.value.scrollHeight;
  }
}

watch(
  [() => props.messages, () => props.liveEntries, () => props.notice],
  () => {
    void scrollToBottom();
  },
  { deep: true },
);

onMounted(() => {
  void scrollToBottom();
});
</script>

<style scoped>
.sent-attachment.image {
  display: flex;
  gap: 8px;
  align-items: center;
}
.sent-attachment img {
  width: 72px;
  height: 72px;
  object-fit: cover;
  border-radius: 8px;
}
.tool-card {
  margin-top: 8px;
  padding: 8px;
  border: 1px solid #d7e3dc;
  border-radius: 8px;
  background: #f7fbf8;
}
.tool-card-head {
  display: flex;
  align-items: center;
}
.tool-collapse {
  margin-top: 4px;
  border: 0 !important;
}
.tool-collapse :deep(.el-collapse-item__header) {
  height: 24px;
  line-height: 24px;
  font-size: 11px;
  color: #527d65;
  background: transparent;
  border-bottom: 0;
}
.tool-collapse :deep(.el-collapse-item__wrap) {
  background: transparent;
  border-bottom: 0;
}
.tool-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 4px;
}
.tool-pre {
  white-space: pre-wrap;
  margin: 4px 0 0;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: #f0f7f3;
  padding: 6px;
  border-radius: 6px;
}
.collab-status-block {
  margin-top: 8px;
}
.collab-status-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #eef8f2;
  border: 1px solid #cce8d9;
  color: #1b7a57;
  font-weight: 500;
  padding: 4px 8px;
  border-radius: 6px;
}
.collab-status-chip--error {
  background: #fff1f1;
  border-color: #fbd5d5;
  color: #b42318;
}
.markdown :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
</style>
