export interface PlatformTask {
  id: string;
  title: string;
  status: string;
  task_type: string;
  category_id: string | null;
  employee_id: string | null;
  worker_id: string | null;
  responsible_employee_id: string | null;
  source_session_id: string | null;
  source_channel_id: string | null;
  current_progress: string;
  runtime_status_label?: string;
  human_intervention: { reason?: string } | null;
}

export interface PlatformWorker {
  id: string;
  name: string;
  role: string;
  status: string;
  enabled: boolean;
  current_task_count: number;
  execution_environment: {
    mode: string;
    status: string;
    model_name: string | null;
    host: string | null;
  } | null;
}

async function read<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      /* 保留状态文本 */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function listTasks(params: Record<string, string> = {}): Promise<PlatformTask[]> {
  const query = new URLSearchParams(params);
  return read(await fetch(`/api/tasks?${query}`));
}

export async function getTask(id: string): Promise<PlatformTask> {
  return read(await fetch(`/api/tasks/${id}`));
}

export async function createTask(body: Record<string, unknown>): Promise<PlatformTask> {
  return read(await fetch("/api/tasks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
}

export async function taskAction(id: string, action: "start" | "pause" | "resume" | "stop" | "confirm"): Promise<PlatformTask> {
  return read(await fetch(`/api/tasks/${id}/${action}`, { method: "POST" }));
}

export async function listCategories(): Promise<Array<{ id: string; name: string; enabled: boolean }>> {
  return read(await fetch("/api/task-categories"));
}

export async function listWorkers(): Promise<PlatformWorker[]> {
  return read(await fetch("/api/workers"));
}

export async function maintainWorker(id: string, action: "deploy" | "restart"): Promise<string> {
  const response = await fetch(`/api/employees/${id}/environment/${action}`, { method: "POST" });
  if (!response.ok || !response.body) throw new Error(response.statusText || "环境操作失败");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let last = "";
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    last += decoder.decode(chunk.value, { stream: true });
  }
  return last.trim().split("\n").filter(Boolean).at(-1) ?? "已发送";
}

export async function listGatewayRoutes(): Promise<Array<{ id: string; model: string; enabled: boolean; pool_id: string }>> {
  return read(await fetch("/api/gateway/routes"));
}

export async function listGatewayKeys(): Promise<Array<{ id: string; name: string; key_prefix: string; enabled: boolean }>> {
  return read(await fetch("/api/gateway/keys"));
}

export async function listLibrarySpaces(): Promise<Array<{ id: string; name: string }>> {
  return read(await fetch("/api/library/spaces"));
}

export async function listLibraryKnowledge(): Promise<{ items: Array<{ id: string; title: string; type: string; status: string }> }> {
  return read(await fetch("/api/library/knowledge"));
}
