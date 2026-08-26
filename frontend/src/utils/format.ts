const STATUS_LABEL: Record<string, string> = {
  OFFLINE: '离线', IDLE: '空闲', WORKING: '工作中', WAIT_HUMAN: '等待人工', PAUSED: '已暂停', ERROR: '异常',
  CREATED: '已创建', READY: '待领取', CLAIMED: '已领取', RUNNING: '运行中', VERIFYING: '验证中',
  RETRY: '修复重试', COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已终止',
  PASSED: '通过', BLOCKED: '阻塞',
}

const PHASE_LABEL: Record<string, string> = {
  created: '任务创建', waiting_dispatch: '等待调度', claimed: '任务认领', workspace: '准备工作区',
  executing: 'OpenCode 执行', script_generate: '脚本生成', code_review: '代码检视', fault_analysis: '故障分析',
  repairing: '自动修复', verifying: '结果验证', completed: '已完成', environment_blocked: '环境阻塞',
  human_handoff: '人工接管', runtime_error: '运行时异常',
}

export const statusLabel = (value: string) => STATUS_LABEL[value] ?? value
export const phaseLabel = (value: string) => PHASE_LABEL[value] ?? value.replaceAll('_', ' ')

export function statusTone(status: string): 'info' | 'success' | 'warning' | 'danger' | 'neutral' {
  if (['COMPLETED', 'PASSED', 'IDLE'].includes(status)) return 'success'
  if (['WAIT_HUMAN', 'PAUSED', 'BLOCKED'].includes(status)) return 'warning'
  if (['FAILED', 'ERROR', 'CANCELLED', 'OFFLINE'].includes(status)) return 'danger'
  if (['RUNNING', 'WORKING', 'VERIFYING', 'RETRY', 'CLAIMED'].includes(status)) return 'info'
  return 'neutral'
}

export const formatTime = (value: string | null | undefined) =>
  value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) : '—'

export const formatDuration = (from: string | null, to?: string | null) => {
  if (!from) return '—'
  const milliseconds = new Date(to ?? Date.now()).getTime() - new Date(from).getTime()
  const minutes = Math.max(0, Math.floor(milliseconds / 60_000))
  if (minutes < 60) return `${minutes}m`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

export const sourceLabel = (source: string) => source === 'nr_test_system' ? 'nr_test_system' : source === 'manual' ? '手工创建' : source
