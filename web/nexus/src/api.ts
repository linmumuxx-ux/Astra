import type {
  AgentScopeOutcome,
  Attachment,
  Channel,
  ChatMessage,
  Conversation,
  Employee,
  ResourceCatalog,
  RuntimeStatus,
} from "./types";

const OWNER_KEY = "nexus_owner_id";

let resolvedUid = "";
let proxyVerified = false;

export function storedOwnerId(): string {
  const value = localStorage.getItem(OWNER_KEY) ?? "";
  return value.startsWith("browser_") ? "" : value;
}

export function currentUid(): string {
  return resolvedUid || storedOwnerId();
}

function rememberCookie(uid: string) {
  document.cookie = `nexus_uid=${encodeURIComponent(uid)}; Path=/; SameSite=Lax`;
}

export function saveOwnerId(uid: string) {
  const value = uid.trim();
  if (!value) return;
  localStorage.setItem(OWNER_KEY, value);
  resolvedUid = value;
  proxyVerified = false;
  rememberCookie(value);
}

export async function resolveOwner(): Promise<string> {
  const response = await fetch("/api/v1/me", { credentials: "omit" });
  if (response.ok) {
    const payload = (await response.json()) as { uid?: string };
    if (payload.uid) {
      resolvedUid = payload.uid;
      proxyVerified = true;
      rememberCookie(payload.uid);
      return payload.uid;
    }
  }
  const stored = storedOwnerId();
  if (!stored) throw new Error("需要输入 UID");
  resolvedUid = stored;
  proxyVerified = false;
  rememberCookie(stored);
  return stored;
}

function headers(json = true): HeadersInit {
  const uid = resolvedUid || storedOwnerId();
  return {
    ...(json ? { "Content-Type": "application/json" } : {}),
    ...(!proxyVerified && uid ? { "X-Owner-Id": uid } : {}),
  };
}

async function read<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      /* 保留状态文本 */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function getRuntime(): Promise<RuntimeStatus> {
  return read(await fetch("/api/v1/runtime"));
}

export async function getSkills(): Promise<ResourceCatalog> {
  return read(await fetch("/api/v1/skills"));
}

export async function getKnowledge(): Promise<ResourceCatalog> {
  return read(await fetch("/api/v1/knowledge"));
}

export async function getTools(): Promise<ResourceCatalog> {
  return read(await fetch("/api/v1/tools"));
}

export async function listEmployees(query = ""): Promise<Employee[]> {
  const payload = await read<{ items: Employee[] }>(
    await fetch(`/api/v1/employees?q=${encodeURIComponent(query)}`),
  );
  return payload.items;
}

export async function saveEmployee(body: Omit<Employee, "id" | "agentscope_agent_id" | "mailbox_session_id">, id?: string) {
  const response = await fetch(id ? `/api/v1/employees/${id}` : "/api/v1/employees", {
    method: id ? "PATCH" : "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  return read<{ employee: Employee; agentscope: { ok: boolean; detail: string } }>(response);
}

export async function deleteEmployee(id: string): Promise<void> {
  await read(await fetch(`/api/v1/employees/${id}`, { method: "DELETE" }));
}

export async function uploadAttachment(file: File): Promise<Attachment> {
  const form = new FormData();
  form.append("file", file);
  return read(await fetch("/api/v1/attachments", {
    method: "POST",
    headers: headers(false),
    body: form,
  }));
}

export function attachmentUrl(id: string): string {
  return `/api/v1/attachments/${id}`;
}

export async function listConversations(employeeId: string): Promise<Conversation[]> {
  const payload = await read<{ items: Conversation[] }>(
    await fetch(`/api/v1/employees/${employeeId}/conversations`, { headers: headers(false) }),
  );
  return payload.items;
}

export async function createConversation(employeeId: string): Promise<Conversation> {
  return read(
    await fetch(`/api/v1/employees/${employeeId}/conversations`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ name: "新对话" }),
    }),
  );
}

export async function getConversation(
  id: string,
): Promise<Conversation & { messages: ChatMessage[]; history_error: string; event_cursor: string }> {
  return read(await fetch(`/api/v1/conversations/${id}`, { headers: headers(false) }));
}

export async function sendConversation(id: string, text: string, attachmentIds: string[]) {
  return read<{ message: ChatMessage; agentscope: AgentScopeOutcome }>(
    await fetch(`/api/v1/conversations/${id}/messages`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ text, attachment_ids: attachmentIds }),
    }),
  );
}

export async function listChannels(): Promise<Channel[]> {
  const payload = await read<{ items: Channel[] }>(await fetch("/api/v1/channels"));
  return payload.items;
}

export async function saveChannel(body: { name: string; description: string; member_ids: string[] }, id?: string) {
  return read<Channel>(
    await fetch(id ? `/api/v1/channels/${id}` : "/api/v1/channels", {
      method: id ? "PATCH" : "POST",
      headers: headers(),
      body: JSON.stringify(body),
    }),
  );
}

export async function channelMessages(id: string): Promise<Channel & { messages: ChatMessage[]; history_error?: string }> {
  return read(await fetch(`/api/v1/channels/${id}/messages`, { headers: headers(false) }));
}

export interface TimelineItem {
  id: string;
  speaker: string;
  text: string;
  kind: string;
  created_at: string;
  attachments?: Attachment[];
}

export async function channelTimeline(id: string): Promise<{ items: TimelineItem[] }> {
  return read(await fetch(`/api/v1/channels/${id}/timeline`, { headers: headers(false) }));
}

export async function sendChannel(id: string, text: string, attachmentIds: string[]) {
  return read<{ message: ChatMessage; triggered: Array<AgentScopeOutcome & { employee_id: string; name: string }> }>(
    await fetch(`/api/v1/channels/${id}/messages`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ text, attachment_ids: attachmentIds }),
    }),
  );
}

export async function readEventStream(
  path: string,
  signal: AbortSignal,
  onEvent: (event: Record<string, unknown>) => void,
): Promise<void> {
  const response = await fetch(path, { headers: headers(false), signal });
  if (!response.ok || !response.body) {
    let detail = "没有收到事件流";
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      /* 使用默认说明 */
    }
    throw new Error(detail);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (!signal.aborted) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const dataLine = frame.split("\n").find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      const raw = dataLine.slice(5).trim();
      if (!raw) continue;
      onEvent(JSON.parse(raw) as Record<string, unknown>);
    }
  }
}
