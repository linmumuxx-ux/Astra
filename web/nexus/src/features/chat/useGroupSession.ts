import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  channelMessages,
  channelTimeline,
  readEventStream,
  sendChannel,
  type TimelineItem,
} from "@/api";
import type { ChannelMember, ChatMessage } from "@/types";
import type { LiveEntry } from "./types";

interface UseGroupSessionOptions {
  getSpeakerName?: (employeeId: string) => string;
  onMembersUpdated?: (channelId: string, members: ChannelMember[]) => void;
}

export function useGroupSession(options?: UseGroupSessionOptions) {
  const currentChannelId = ref<string | null>(null);
  const messages = ref<ChatMessage[]>([]);
  const liveLines = ref<Array<{ employeeId: string; name: string; text: string }>>([]);
  const notice = ref("");
  const sending = ref(false);

  const seenEventIds = new Map<string, Set<string>>();
  let sessionToken = 0;
  let channelAbort: AbortController | null = null;
  let memberAbort: AbortController | null = null;

  const canSend = computed(() => Boolean(currentChannelId.value && !sending.value));

  const live = computed<LiveEntry[]>(() =>
    liveLines.value.map((line) => ({
      employeeId: line.employeeId,
      name: line.name,
      text: line.text,
    })),
  );

  function stopMemberStream() {
    memberAbort?.abort();
    memberAbort = null;
  }

  function stopChannelStream() {
    channelAbort?.abort();
    channelAbort = null;
  }

  function stopAllStreams() {
    stopMemberStream();
    stopChannelStream();
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

  function fromTimeline(item: TimelineItem): ChatMessage {
    return {
      id: item.id,
      sender: item.kind === "human" ? "user" : item.speaker,
      speaker: item.speaker,
      text: item.text,
      attachments: item.attachments ?? [],
      created_at: item.created_at,
    };
  }

  function mergeById(item: ChatMessage) {
    const index = messages.value.findIndex((message) => message.id === item.id);
    if (index >= 0) {
      const next = messages.value.slice();
      const previous = next[index];
      next[index] = {
        ...previous,
        ...item,
        attachments: item.attachments.length ? item.attachments : previous.attachments,
      };
      messages.value = next;
      return;
    }
    messages.value = [...messages.value, item];
  }

  async function followChannel(channelId: string, signal: AbortSignal, token: number) {
    try {
      await readEventStream(`/api/v1/channels/${channelId}/events`, signal, (event) => {
        if (token !== sessionToken || currentChannelId.value !== channelId || typeof event.id !== "string") return;
        mergeById({
          id: event.id,
          sender: "user",
          speaker: String(event.speaker ?? ""),
          text: String(event.text ?? ""),
          attachments: [],
          created_at: "",
        });
      });
    } catch (error) {
      if (!signal.aborted && token === sessionToken) {
        notice.value = error instanceof Error ? error.message : "事件流中断";
      }
    }
  }

  async function followMember(
    channelId: string,
    employeeId: string,
    signal: AbortSignal,
    settled: Set<string>,
    token: number,
  ) {
    const seen = seenEventIds.get(employeeId) ?? new Set<string>();
    seenEventIds.set(employeeId, seen);
    const name = options?.getSpeakerName ? options.getSpeakerName(employeeId) : "数字员工";

    try {
      await readEventStream(
        `/api/v1/channels/${channelId}/members/${employeeId}/stream`,
        signal,
        (event) => {
          if (token !== sessionToken || currentChannelId.value !== channelId) return;
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
            void channelTimeline(channelId).then((payload) => {
              if (token !== sessionToken || currentChannelId.value !== channelId) return;
              messages.value = payload.items.map(fromTimeline);
              liveLines.value = liveLines.value.filter((item) => item.employeeId !== employeeId);
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
      if (!signal.aborted && token === sessionToken) {
        notice.value = error instanceof Error ? error.message : "事件流中断";
      }
    }
  }

  async function watchMembers(channelId: string, signal: AbortSignal, token: number) {
    const watching = new Set<string>();
    const settled = new Set<string>();
    const started = Date.now();
    let quiet = 0;

    while (!signal.aborted && token === sessionToken && Date.now() - started < 120_000) {
      let payload;
      try {
        payload = await channelMessages(channelId);
      } catch {
        break;
      }
      if (signal.aborted || token !== sessionToken || currentChannelId.value !== channelId) return;
      options?.onMembersUpdated?.(channelId, payload.members);
      let opened = 0;
      for (const member of payload.members) {
        if (!member.agentscope_session_id || watching.has(member.employee_id)) continue;
        watching.add(member.employee_id);
        opened += 1;
        void followMember(channelId, member.employee_id, signal, settled, token);
      }
      const pending = [...watching].some((id) => !settled.has(id));
      if (opened || pending) quiet = 0;
      else quiet += 1;
      if (quiet >= 3) break;
      await delay(1000, signal);
    }
  }

  function close() {
    sessionToken += 1;
    stopAllStreams();
    currentChannelId.value = null;
    messages.value = [];
    liveLines.value = [];
    notice.value = "";
    sending.value = false;
  }

  async function open(channelId: string) {
    close();
    const token = ++sessionToken;
    currentChannelId.value = channelId;
    try {
      const payload = await channelTimeline(channelId);
      if (token !== sessionToken || currentChannelId.value !== channelId) return;
      messages.value = payload.items.map(fromTimeline);
      const controller = new AbortController();
      channelAbort = controller;
      void followChannel(channelId, controller.signal, token);
      stopMemberStream();
      const memberController = new AbortController();
      memberAbort = memberController;
      void watchMembers(channelId, memberController.signal, token).then(() => {
        if (memberAbort === memberController) memberAbort = null;
      });
    } catch (error) {
      if (token !== sessionToken || currentChannelId.value !== channelId) return;
      notice.value = error instanceof Error ? error.message : "无法加载群组消息";
    }
  }

  async function send(text: string, attachmentIds: string[]): Promise<boolean> {
    if (!currentChannelId.value || sending.value) return false;
    const targetId = currentChannelId.value;
    const token = sessionToken;
    sending.value = true;
    try {
      const result = await sendChannel(targetId, text, attachmentIds);
      if (token !== sessionToken || currentChannelId.value !== targetId) return true;
      sending.value = false;
      messages.value = [...messages.value, result.message];
      const rejected = result.triggered.filter((item) => !item.accepted);
      if (!result.triggered.length) {
        notice.value = "没有点名已启用的员工，因此没有触发任何人。";
        return true;
      }
      notice.value = rejected.map((item) => `${item.name}：${item.detail}`).filter(Boolean).join(" ");
      stopMemberStream();
      liveLines.value = [];
      const controller = new AbortController();
      memberAbort = controller;
      void watchMembers(targetId, controller.signal, token).then(() => {
        if (memberAbort === controller) memberAbort = null;
      });
      return true;
    } catch (error) {
      if (token === sessionToken && currentChannelId.value === targetId && !(error instanceof DOMException)) {
        ElMessage.error(error instanceof Error ? error.message : "发送失败");
      }
      return false;
    } finally {
      if (token === sessionToken && currentChannelId.value === targetId) {
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
    currentChannelId,
    open,
    close,
    send,
  };
}
