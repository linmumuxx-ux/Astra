import type { Channel, ChatMessage, Employee } from "@/types";

export type ConversationKind = "contact" | "group";

export interface LiveToolCall {
  id: string;
  name: string;
  input: string;
  output: string;
  state?: string;
}

export interface LiveEntry {
  employeeId?: string;
  name: string;
  text?: string;
  tools?: LiveToolCall[];
}

export interface ChatSessionAdapter {
  messages: import("vue").Ref<ChatMessage[]>;
  live: import("vue").Ref<LiveEntry[]>;
  notice: import("vue").Ref<string>;
  sending: import("vue").Ref<boolean>;
  canSend: import("vue").ComputedRef<boolean> | import("vue").Ref<boolean>;
  open: (id: string) => Promise<void> | void;
  close: () => void;
  send: (text: string, attachmentIds: string[]) => Promise<boolean>;
}

export interface UnifiedListItem {
  kind: ConversationKind;
  id: string;
  name: string;
  avatar: string;
  secondary: string;
  enabled: boolean;
  timestamp: number | null;
  orderIndex: number;
  raw: Employee | Channel;
}
