export interface TaskDraftSnapshot {
  title: string
  task_type: string
  category_id: string
  priority: string
  description: string
  criteria: string[]
  employee_id: string
  responsible_employee_id: string
  files: number
}

export function taskDraftSnapshot(draft: TaskDraftSnapshot): string {
  return JSON.stringify({
    title: draft.title,
    task_type: draft.task_type,
    category_id: draft.category_id,
    priority: draft.priority,
    description: draft.description,
    criteria: draft.criteria,
    employee_id: draft.employee_id || '',
    responsible_employee_id: draft.responsible_employee_id || '',
    files: draft.files,
  })
}

/**
 * 分类列表可能晚于抽屉打开。默认分类补上之前不能把空分类写进基线，
 * 否则未编辑也会被当成脏数据。用户已经改过表单时，只补分类、不刷新基线。
 */
export function applyDefaultCategory(
  draft: TaskDraftSnapshot,
  categoryIds: string[],
  baseline: string,
): { draft: TaskDraftSnapshot; baseline: string } {
  if (draft.category_id || categoryIds.length === 0) {
    return { draft, baseline: baseline || taskDraftSnapshot(draft) }
  }
  const before = taskDraftSnapshot(draft)
  const next = { ...draft, category_id: categoryIds[0] }
  const untouched = !baseline || before === baseline
  return { draft: next, baseline: untouched ? taskDraftSnapshot(next) : baseline }
}
