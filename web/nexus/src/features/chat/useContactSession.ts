import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { createConversation, getConversation, readEventStream, sendConversation } from "@/api";
import type { ChatMessage, Conversation, Employee } from "@/types";
import type { LiveEntry, LiveToolCall } from "./types";

export function useContactSession(getEmployee?: () => Employee | null | undefined) {
  const currentEmployeeId = ref<string | null>(null);
  const conversation = ref<Conversation | null>(null);
  const messages = ref<ChatMessage[]>([]);
  const liveText = ref("");
  const liveTools = ref<LiveToolCall[]>([]);
  const notice = ref("");
  const sending = ref(false);

  const seenEventIds = new Map<string, Set<string>>();
  let sessionToken = 0;
  let streamAbort: AbortController | null = null;

  const canSend = computed(() => {
    if (sending.value || !conversation.value?.id) return false;
    const emp = getEmployee ? getEmployee() : null;
    return emp ? emp.enabled : true;
  });

  const live = computed<LiveEntry[]>(() => {
    if (!liveText.value && !liveTools.value.length) return [];
    const emp = getEmployee ? getEmployee() : null;
    return [
      {
        employeeId: currentEmployeeId.value ?? undefined,
        name: emp?.name ?? "数字员工",
        text: liveText.value,
        tools: [...liveTools.value],
      },
    ];
  });

  function stopStream() {
    streamAbort?.abort();
    streamAbort = null;
  }

  function delay(ms: number, signal?: AbortSignal) {
    return new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, ms);
      signal?.addEventListener(
        "abort",
        () => {
          clearTimeout(timer);
          resolve();
        },
        { once: true },
      );
    });
  }

  function ensureTool(id: string, name = ""): LiveToolCall {
    let card = liveTools.value.find((item) => item.id === id);
    if (!card) {
      card = { id, name, input: "", output: "" };
      liveTools.value = [...liveTools.value, card];
    } else if (name && !card.name) {
      card.name = name;
    }
    return card;
  }

  function takeLiveReply() {
    const text = liveText.value.trim();
    if (!text || !currentEmployeeId.value) return;
    const emp = getEmployee ? getEmployee() : null;
    messages.value = [
      ...messages.value,
      {
        id: `live_${Date.now()}`,
        sender: emp?.id ?? currentEmployeeId.value,
        text,
        attachments: [],
        created_at: new Date().toISOString(),
      },
    ];
    liveText.value = "";
  }

  async function reloadConversation(id: string, token: number) {
    const payload = await getConversation(id);
    if (token !== sessionToken || conversation.value?.id !== id) return null;
    messages.value = payload.messages;
    if (payload.history_error) {
      notice.value = `没有读到 Session 里的回复。${payload.history_error}`;
    }
    return payload;
  }

  function applyStreamEvent(
    id: string,
    event: Record<string, unknown>,
    seen: Set<string>,
    cursor: { value: string },
    token: number,
  ): boolean {
    if (token !== sessionToken || conversation.value?.id !== id) return false;
    if (typeof event.id === "string" && /^\d+-\d+$/.test(event.id)) {
      cursor.value = event.id;
    }
    if (typeof event.id === "string") {
      if (seen.has(event.id)) return false;
      seen.add(event.id);
    }
    if (event.type === "TEXT_BLOCK_DELTA" && typeof event.delta === "string") {
      liveText.value += event.delta;
    }
    if (event.type === "TOOL_CALL_START" && typeof event.tool_call_id === "string") {
      ensureTool(event.tool_call_id, typeof event.tool_call_name === "string" ? event.tool_call_name : "");
    }
    if (event.type === "TOOL_CALL_DELTA" && typeof event.tool_call_id === "string" && typeof event.delta === "string") {
      ensureTool(event.tool_call_id).input += event.delta;
    }
    if (
      event.type === "TOOL_RESULT_TEXT_DELTA" &&
      typeof event.tool_call_id === "string" &&
      typeof event.delta === "string"
    ) {
      ensureTool(event.tool_call_id).output += event.delta;
    }
    if (event.type === "REPLY_END" || event.type === "NEXUS_RUN_FINISHED") {
      const reason = String(event.finished_reason ?? "");
      if (reason === "error" || reason === "interrupted") {
        notice.value = reason === "interrupted" ? "回复已中断" : "回复失败";
      }
      liveText.value = "";
      liveTools.value = [];
      void reloadConversation(id, token);
      return true;
    }
    if (event.type === "NEXUS_UPSTREAM_ERROR") {
      notice.value = String(event.detail ?? "事件流中断");
    }
    return false;
  }

  async function followStream(id: string, token: number, untilFinished = false) {
    stopStream();
    liveText.value = "";
    liveTools.value = [];
    const seen = new Set<string>();
    seenEventIds.set(id, seen);

    const payload = await reloadConversation(id, token);
    if (!payload || token !== sessionToken || conversation.value?.id !== id) return;
    if (!payload.agentscope_session_id) return;

    const cursor = { value: payload.event_cursor || "" };
    for (let attempt = 0; attempt < 8; attempt += 1) {
      if (token !== sessionToken || conversation.value?.id !== id) return;
      streamAbort = new AbortController();
      const signal = streamAbort.signal;
      const query = cursor.value ? `?after=${encodeURIComponent(cursor.value)}` : "";
      let sawEvent = false;
      let finished = false;
      try {
        await readEventStream(`/api/v1/conversations/${id}/stream${query}`, signal, (event) => {
          if (token !== sessionToken || conversation.value?.id !== id) return;
          sawEvent = true;
          if (applyStreamEvent(id, event, seen, cursor, token)) finished = true;
        });
        if (finished || signal.aborted || token !== sessionToken || conversation.value?.id !== id) return;
        if (!untilFinished && !sawEvent) return;
        await delay(400, signal);
      } catch (error) {
        if (signal.aborted || token !== sessionToken || conversation.value?.id !== id) return;
        notice.value = error instanceof Error ? error.message : "事件流中断";
        await delay(1000, signal);
      }
    }
  }

  function close() {
    sessionToken += 1;
    stopStream();
    currentEmployeeId.value = null;
    conversation.value = null;
    messages.value = [];
    liveText.value = "";
    liveTools.value = [];
    notice.value = "";
    sending.value = false;
  }

  async function open(employeeId: string) {
    close();
    const token = ++sessionToken;
    currentEmployeeId.value = employeeId;
    try {
      const created = await createConversation(employeeId);
      if (token !== sessionToken || currentEmployeeId.value !== employeeId) return;
      conversation.value = created;
      await followStream(created.id, token, false);
    } catch (error) {
      if (token !== sessionToken || currentEmployeeId.value !== employeeId) return;
      notice.value = error instanceof Error ? error.message : "无法加载会话";
    }
  }

  async function send(text: string, attachmentIds: string[]): Promise<boolean> {
    if (!conversation.value?.id || sending.value || !canSend.value) return false;
    const targetId = conversation.value.id;
    const token = sessionToken;
    sending.value = true;
    takeLiveReply();
    try {
      const result = await sendConversation(targetId, text, attachmentIds);
      if (token !== sessionToken || conversation.value?.id !== targetId) return true;
      // The POST is the only send lock; following the reply must not block the composer.
      sending.value = false;
      if (!result.agentscope.accepted) {
        notice.value = result.agentscope.detail || "没有生成回复";
        return false;
      }
      messages.value = [...messages.value, result.message];
      if (conversation.value && conversation.value.name === "新对话") {
        conversation.value.name =
          result.message.text.slice(0, 20) || result.message.attachments[0]?.name || "新对话";
      }
      notice.value = "";
      void followStream(targetId, token, true);
      return true;
    } catch (error) {
      if (token === sessionToken && conversation.value?.id === targetId) {
        ElMessage.error(error instanceof Error ? error.message : "发送失败");
      }
      return false;
    } finally {
      if (token === sessionToken && conversation.value?.id === targetId) {
        sending.value = false;
      }
    }
  }

  return {
    messages,
    live,
    notice,
    sending,
    canSend,
    conversation,
    currentEmployeeId,
    open,
    close,
    send,
  };
}
