import type { RuntimeEvent, SessionMessage, TaskWorkbench } from '@/api/types'

export type SubtaskStatus = 'running' | 'completed' | 'failed'
export type SubtaskStepStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface SubtaskStep {
  id: string
  title: string
  detail: string
  status: SubtaskStepStatus
  timestamp: string
}

export interface ConversationSubtask {
  kind: 'subtask'
  id: string
  timestamp: string
  name: string
  title: string
  status: SubtaskStatus
  statusLabel: string
  childSessionId: string | null
  output: string
  error: string
  steps: SubtaskStep[]
}

export interface ConversationMessage {
  kind: 'message'
  id: string
  timestamp: string
  role: 'user' | 'agent'
  content: string
  status: SessionMessage['status']
  initial: boolean
}

export interface ConversationInquiry {
  kind: 'inquiry'
  id: string
  timestamp: string
  inquiry: TaskWorkbench['inquiries'][number]
}

export type ConversationItem = ConversationMessage | ConversationInquiry | ConversationSubtask

export interface TaskConversation {
  items: ConversationItem[]
  subtasks: ConversationSubtask[]
}

const text = (value: unknown) => typeof value === 'string' ? value.trim() : ''

const timestampValue = (value: string) => {
  const parsed = new Date(value).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
}

function lifecycleStatus(event: RuntimeEvent): SubtaskStatus {
  if (event.event_type.endsWith('failed')) return 'failed'
  if (event.event_type.endsWith('completed')) return 'completed'
  return 'running'
}

function stepStatus(event: RuntimeEvent): SubtaskStepStatus {
  if (event.event_type.endsWith('failed')) return 'failed'
  if (event.event_type.endsWith('completed')) return 'completed'
  if (event.event_type.endsWith('started') || event.event_type.endsWith('progress')) return 'running'
  return 'pending'
}

function eventIdentity(event: RuntimeEvent): string {
  return text(event.payload.source_call_id)
    || text(event.payload.child_session_id)
    || [event.run_id ?? 'run', event.agent_name ?? 'subagent', text(event.payload.description) || event.summary].join(':')
}

function toolIdentity(event: RuntimeEvent): string {
  return text(event.payload.source_call_id)
    || text(event.payload.call_id)
    || text(event.payload.source_part_id)
    || event.id
}

function toolLabel(event: RuntimeEvent): string {
  const tool = text(event.payload.tool).toLowerCase()
  const labels: Record<string, string> = {
    bash: '执行命令',
    read: '读取文件',
    grep: '搜索内容',
    edit: '修改文件',
    write: '写入文件',
    task: '派发子任务',
    question: '询问用户',
  }
  return text(event.payload.title) || labels[tool] || event.summary || '执行操作'
}

function toolDetail(event: RuntimeEvent): string {
  const input = event.payload.input
  if (!input || typeof input !== 'object') return ''
  const value = input as Record<string, unknown>
  const candidate = text(value.description) || text(value.filePath) || text(value.path)
  return candidate.length > 120 ? `${candidate.slice(0, 117)}…` : candidate
}

function compactOutput(value: unknown): string {
  const output = text(value)
  if (!output) return ''
  return output.length > 600 ? `${output.slice(0, 597)}…` : output
}

function isPlatformPrompt(message: SessionMessage, taskId: string): boolean {
  if (message.role !== 'agent') return false
  const content = message.content
  return content.includes(`当前任务：\n${taskId}`)
    || (content.includes(`当前任务： ${taskId}`) && content.includes('员工工作空间：') && content.includes('验收标准：'))
}

function cleanAgentContent(value: string): string {
  const marker = value.indexOf('ASTRA_RESULT_JSON:')
  return (marker >= 0 ? value.slice(0, marker) : value).trim()
}

function buildSubtasks(events: RuntimeEvent[]): ConversationSubtask[] {
  const lifecycleEvents = events.filter((event) => event.event_type.startsWith('subagent.'))
  const groups = new Map<string, RuntimeEvent[]>()
  for (const event of lifecycleEvents) {
    const id = eventIdentity(event)
    groups.set(id, [...(groups.get(id) ?? []), event])
  }

  return [...groups.entries()].map(([id, group]) => {
    const ordered = [...group].sort((a, b) => timestampValue(a.timestamp) - timestampValue(b.timestamp))
    const latest = ordered.at(-1)!
    const first = ordered[0]
    const childSessionId = text(latest.payload.child_session_id) || text(first.payload.child_session_id) || null
    const name = latest.agent_name || first.agent_name || text(latest.payload.role) || '子代理'
    const title = text(latest.payload.description)
      || text(first.payload.description)
      || latest.summary.split('：').at(-1)?.trim()
      || '执行专项任务'
    const status = lifecycleStatus(latest)
    const matchingTools = events.filter((event) => {
      if (!event.event_type.startsWith('tool.')) return false
      const sourceSession = text(event.payload.source_session_id) || text(event.payload.session_id)
      return !!childSessionId && sourceSession === childSessionId
    })
    const toolGroups = new Map<string, RuntimeEvent[]>()
    for (const event of matchingTools) {
      const toolId = toolIdentity(event)
      toolGroups.set(toolId, [...(toolGroups.get(toolId) ?? []), event])
    }
    const toolSteps = [...toolGroups.entries()].map(([toolId, toolEvents]) => {
      const sequence = [...toolEvents].sort((a, b) => timestampValue(a.timestamp) - timestampValue(b.timestamp))
      const current = sequence.at(-1)!
      return {
        id: `${id}:${toolId}`,
        title: toolLabel(current),
        detail: toolDetail(current),
        status: stepStatus(current),
        timestamp: current.timestamp,
      } satisfies SubtaskStep
    })
    const steps = toolSteps.length ? toolSteps : [
      {
        id: `${id}:received`,
        title: '接收子任务',
        detail: title,
        status: 'completed' as const,
        timestamp: first.timestamp,
      },
      {
        id: `${id}:execute`,
        title: '执行子任务',
        detail: status === 'running' ? '正在自主处理任务' : status === 'failed' ? '执行过程中遇到问题' : '子任务处理完成',
        status: status === 'running' ? 'running' as const : status,
        timestamp: latest.timestamp,
      },
      {
        id: `${id}:return`,
        title: '返回执行结果',
        detail: status === 'completed' ? '结果已返回主任务' : status === 'failed' ? '失败信息已返回主任务' : '等待子任务返回',
        status: status === 'running' ? 'pending' as const : status,
        timestamp: latest.timestamp,
      },
    ]
    return {
      kind: 'subtask' as const,
      id,
      timestamp: first.timestamp,
      name,
      title,
      status,
      statusLabel: status === 'completed' ? '已完成' : status === 'failed' ? '执行失败' : '执行中',
      childSessionId,
      output: compactOutput(latest.payload.output),
      error: compactOutput(latest.payload.error),
      steps,
    }
  }).sort((a, b) => timestampValue(a.timestamp) - timestampValue(b.timestamp))
}

export function buildTaskConversation(workbench: TaskWorkbench): TaskConversation {
  const events = workbench.events
  const subtasks = buildSubtasks(events)
  const hiddenAgentMessages = new Set<string>()
  for (const event of events.filter((item) => item.event_type.startsWith('subagent.'))) {
    const prompt = text(event.payload.prompt)
    const output = text(event.payload.output)
    if (prompt) hiddenAgentMessages.add(prompt)
    if (output) hiddenAgentMessages.add(output)
  }
  for (const inquiry of workbench.inquiries) {
    hiddenAgentMessages.add(inquiry.question.trim())
    if (inquiry.answer) hiddenAgentMessages.add(inquiry.answer.trim())
  }

  const firstUserId = workbench.messages.find((message) => message.role === 'user')?.id
  const items: ConversationItem[] = []
  for (const message of workbench.messages) {
    if (message.role === 'system' || isPlatformPrompt(message, workbench.task.id)) continue
    const content = message.role === 'agent' ? cleanAgentContent(message.content) : message.content.trim()
    if (!content || (message.role === 'agent' && hiddenAgentMessages.has(content))) continue
    if (message.role === 'agent' && workbench.task.result?.summary.trim() === content) continue
    items.push({
      kind: 'message',
      id: message.id,
      timestamp: message.created_at,
      role: message.role,
      content,
      status: message.status,
      initial: message.id === firstUserId,
    })
  }
  if (!firstUserId && workbench.task.description.trim()) {
    items.push({
      kind: 'message',
      id: `task-objective-${workbench.task.id}`,
      timestamp: workbench.task.created_at,
      role: 'user',
      content: workbench.task.description.trim(),
      status: 'APPLIED',
      initial: true,
    })
  }
  for (const inquiry of workbench.inquiries) {
    items.push({ kind: 'inquiry', id: inquiry.id, timestamp: inquiry.created_at, inquiry })
  }
  items.push(...subtasks)
  const order: Record<ConversationItem['kind'], number> = { message: 0, subtask: 1, inquiry: 2 }
  items.sort((a, b) => timestampValue(a.timestamp) - timestampValue(b.timestamp) || order[a.kind] - order[b.kind])
  return { items, subtasks }
}
