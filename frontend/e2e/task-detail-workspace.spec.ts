import { expect, test, type Page } from '@playwright/test'

// TaskDetailView 浏览器回归：全部走 page.route mock，覆盖 Session 切换、人工确认、
// 连接异常恢复与 Git/信息抽屉。真实模型场景由 session-workspace-real.spec.ts 承担。
type TaskState = {
  id: string
  source: string
  external_task_id: string | null
  task_type: string
  category_id: string | null
  title: string
  description: string
  acceptance_criteria: Array<{ id: string; content: string }>
  attachments: unknown[]
  priority: string
  completion_policy: string
  status: string
  employee_id: string | null
  current_session_id: string | null
  workspace: string | null
  runtime_connection: string
  pending_message_id: string | null
  runtime_error: string | null
  current_progress: string
  result: unknown
  failure_reason: string | null
  human_required_reason: string | null
  human_intervention: unknown
  suspension: unknown
  execution_error: unknown
  review_history: unknown[]
  inactivity_alert: boolean
  inactivity_alert_since: string | null
  last_activity_at: string | null
  submitted_at: string | null
  confirmed_at: string | null
  execution_environment_snapshot: unknown
  claimed_at: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
  runtime_state: string
  runtime_status_label: string
  runtime_detail: string
  failure: unknown
}

type SessionItem = {
  id: string
  workspace: string
  created_at: string
  status: string
  superseded_by: string | null
  finished_at: string | null
  opencode_version: string
  workspace_ui: string
}

type RepoState = { name: string; branch: string; commit: string; dirty: boolean; changes: number; task_changes?: { changed_files: number; commits: string[] } }

const STATUS_LABEL: Record<string, string> = {
  PENDING: '待执行',
  RUNNING: '执行中',
  WAITING: '等待人工或外部条件',
  SUCCEEDED: '已完成',
  FAILED: '执行失败',
  CANCELED: '已取消',
}

function makeTask(id: string, title: string, overrides: Partial<TaskState> = {}): TaskState {
  const base: TaskState = {
    id,
    source: 'manual',
    external_task_id: null,
    task_type: 'ISSUE',
    category_id: null,
    title,
    description: '回归测试任务描述',
    acceptance_criteria: [],
    attachments: [],
    priority: 'MEDIUM',
    completion_policy: 'AUTO',
    status: 'PENDING',
    employee_id: 'E1',
    current_session_id: null,
    workspace: null,
    runtime_connection: 'CONNECTED',
    pending_message_id: null,
    runtime_error: null,
    current_progress: '',
    result: null,
    failure_reason: null,
    human_required_reason: null,
    human_intervention: null,
    suspension: null,
    execution_error: null,
    review_history: [],
    inactivity_alert: false,
    inactivity_alert_since: null,
    last_activity_at: null,
    submitted_at: null,
    confirmed_at: null,
    execution_environment_snapshot: null,
    claimed_at: null,
    started_at: null,
    finished_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    runtime_state: 'PENDING',
    runtime_status_label: STATUS_LABEL.PENDING,
    runtime_detail: '',
    failure: null,
  }
  const merged = { ...base, ...overrides }
  if (!('runtime_state' in overrides)) merged.runtime_state = merged.status
  if (!('runtime_status_label' in overrides)) merged.runtime_status_label = STATUS_LABEL[merged.status] ?? merged.runtime_status_label
  return merged
}

function project(task: TaskState, status: string, detail = '') {
  task.status = status
  task.runtime_state = status
  task.runtime_status_label = STATUS_LABEL[status]
  task.runtime_detail = detail
}

function makeSession(id: string, version: string, workspace: string, overrides: Partial<SessionItem> = {}): SessionItem {
  return {
    id,
    workspace,
    created_at: '2026-01-01T00:00:00Z',
    status: 'RUNNING',
    superseded_by: null,
    finished_at: null,
    opencode_version: version,
    workspace_ui: `/mock-workspace/${version}/index.html`,
    ...overrides,
  }
}

interface FixtureHandle {
  posts: Array<{ method: string; pathname: string; body: unknown }>
  errors: string[]
  frame: ReturnType<Page['frameLocator']>
}

async function installFixture(
  page: Page,
  config: {
    tasks: TaskState[]
    sessions?: Record<string, SessionItem[]>
    repos?: Record<string, RepoState>
  },
): Promise<FixtureHandle> {
  const posts: FixtureHandle['posts'] = []
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))

  const applyAction = (task: TaskState, action: string) => {
    switch (action) {
      case 'confirm':
        task.confirmed_at = '2026-01-03T00:00:00Z'
        task.finished_at = task.confirmed_at
        task.human_required_reason = null
        task.human_intervention = null
        project(task, 'SUCCEEDED', '任务结果已人工确认')
        break
      case 'stop':
        task.pending_message_id = null
        task.finished_at = '2026-01-03T00:00:00Z'
        project(task, 'CANCELED')
        break
      case 'reconnect':
        task.runtime_connection = 'CONNECTED'
        task.runtime_error = null
        break
      case 'retry-submission':
        task.pending_message_id = null
        task.runtime_error = null
        project(task, 'RUNNING')
        break
    }
  }

  const bindingFor = (task: TaskState) => {
    const sessions = (config.sessions?.[task.id] ?? []).map(item => ({ ...item, current: item.id === task.current_session_id }))
    const selected = sessions.find(item => item.current) ?? sessions[0]
    return {
      task_id: task.id,
      task_status: task.status,
      runtime: {
        server: `/api/tasks/${task.id}/opencode`,
        session_id: selected?.id ?? null,
        workspace: selected?.workspace ?? task.workspace,
        connection: task.runtime_connection,
        error: task.runtime_error,
        opencode_version: selected?.opencode_version ?? '1.18.31',
        workspace_ui: selected?.workspace_ui ?? '/mock-workspace/1.18.31/index.html',
      },
      sessions,
    }
  }

  await page.route('**/api/**', route => {
    const url = new URL(route.request().url())
    const { pathname } = url
    const method = route.request().method()
    if (!pathname.startsWith('/api/')) return route.continue()
    const taskMatch = pathname.match(/^\/api\/tasks\/([^/]+)$/)
    const actionMatch = pathname.match(/^\/api\/tasks\/([^/]+)\/([a-z][a-z-]*)$/)
    const findTask = (id: string) => config.tasks.find(item => item.id === id)

    if (pathname === '/api/system/metrics') {
      return route.fulfill({ json: { online_employees: 0, running_tasks: 0, idle_employees: 0, error_employees: 0, pending_tasks: 0, waiting_tasks: 0, failed_tasks: 0, completed_today: 0, failed_today: 0, today_tokens: null, today_tool_calls: null, task_status_distribution: {}, employee_status_distribution: {} } })
    }
    if (pathname === '/api/employees') return route.fulfill({ json: [{ id: 'E1', name: 'Astra-01', role: '自动化工程师', status: 'WORKING' }] })
    if (pathname === '/api/task-categories') return route.fulfill({ json: [] })
    if (pathname === '/api/events/stream') return route.fulfill({ contentType: 'text/event-stream', body: 'event: connected\ndata: {}\n\n' })
    if (pathname === '/api/events') return route.fulfill({ json: [] })
    if (pathname === '/api/tasks' && method === 'GET') return route.fulfill({ json: config.tasks })
    if (taskMatch && method === 'GET') {
      const task = findTask(taskMatch[1]!)
      return task ? route.fulfill({ json: task }) : route.fulfill({ status: 404, json: { detail: '任务不存在' } })
    }
    if (taskMatch && method === 'DELETE') return route.fulfill({ json: { deleted: taskMatch[1] } })
    if (actionMatch && actionMatch[2] !== 'workspace' && actionMatch[2] !== 'repo' && method === 'POST') {
      const task = findTask(actionMatch[1]!)
      if (!task) return route.fulfill({ status: 404, json: { detail: '任务不存在' } })
      posts.push({ method, pathname, body: route.request().postDataJSON() })
      applyAction(task, actionMatch[2]!)
      return route.fulfill({ json: task })
    }
    const workspaceMatch = pathname.match(/^\/api\/tasks\/([^/]+)\/workspace$/)
    if (workspaceMatch) {
      const task = findTask(workspaceMatch[1]!)
      return task ? route.fulfill({ json: bindingFor(task) }) : route.fulfill({ status: 404, json: { detail: '任务不存在' } })
    }
    const repoMatch = pathname.match(/^\/api\/tasks\/([^/]+)\/repo$/)
    if (repoMatch) {
      const repo = config.repos?.[repoMatch[1]!]
      return repo ? route.fulfill({ json: repo }) : route.fulfill({ status: 409, json: { detail: 'Workspace 尚未准备' } })
    }
    return route.fulfill({ json: [] })
  })

  // 受控 Workspace 替身：把 iframe 收到的 task/session 查询参数回显到页面文本，
  // 断言实际载入内容而不是仅 URL 字符串。
  await page.route('**/mock-workspace/**', route => {
    const url = new URL(route.request().url())
    const version = url.pathname.split('/')[2] ?? ''
    const marker = `task=${url.searchParams.get('task') ?? 'none'} session=${url.searchParams.get('session') ?? 'none'} version=${version}`
    return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><body><pre id="workspace-marker">${marker}</pre></body></html>` })
  })

  return { posts, errors, frame: page.frameLocator('iframe[title="OpenCode Task Workspace"]') }
}

const sessionsConfig = (workspace: string): SessionItem[] => [
  makeSession('ses_new', '1.18.31', workspace),
  makeSession('ses_old', '1.2.27', workspace, { status: 'CANCELED', superseded_by: 'ses_new', finished_at: '2026-01-02T00:00:00Z' }),
]

test('Session 切换：ElSelect 切换当前/历史 Session 后 iframe URL 与载入内容同步，且不触发控制操作', async ({ page }) => {
  const workspace = '/ws/tasks/T-SESSIONS'
  const { posts, errors, frame } = await installFixture(page, {
    tasks: [makeTask('T-SESSIONS', '会话切换任务', { status: 'RUNNING', current_session_id: 'ses_new', workspace, started_at: '2026-01-01T00:00:00Z', acceptance_criteria: [{ id: 'ac-1', content: '切换 Session 后 Workspace 不串任务' }] })],
    sessions: { 'T-SESSIONS': sessionsConfig(workspace) },
  })
  await page.goto('/tasks/T-SESSIONS')

  const select = page.getByTestId('session-select')
  const iframe = page.locator('iframe[title="OpenCode Task Workspace"]')
  await expect(select).toHaveAttribute('data-session-id', 'ses_new')
  await expect(iframe).toHaveAttribute('src', /\/mock-workspace\/1\.18\.31\/index\.html\?task=T-SESSIONS&session=ses_new$/)
  await expect(frame.locator('#workspace-marker')).toHaveText('task=T-SESSIONS session=ses_new version=1.18.31')

  await select.locator('.el-select__wrapper').click()
  await expect(page.getByRole('option')).toHaveText(['Session #2 · 当前', 'Session #1 · 历史只读'])
  await page.getByRole('option', { name: 'Session #1 · 历史只读' }).click()
  await expect(select).toHaveAttribute('data-session-id', 'ses_old')
  await expect(iframe).toHaveAttribute('src', /\/mock-workspace\/1\.2\.27\/index\.html\?task=T-SESSIONS&session=ses_old$/)
  await expect(frame.locator('#workspace-marker')).toHaveText('task=T-SESSIONS session=ses_old version=1.2.27')

  await select.locator('.el-select__wrapper').click()
  await page.getByRole('option', { name: 'Session #2 · 当前' }).click()
  await expect(select).toHaveAttribute('data-session-id', 'ses_new')
  await expect(frame.locator('#workspace-marker')).toHaveText('task=T-SESSIONS session=ses_new version=1.18.31')

  expect(posts).toEqual([])
  expect(errors).toEqual([])
})

test('Git 状态与任务信息抽屉：仓库标签、业务字段与 Session 上下文保持呈现', async ({ page }) => {
  const workspace = '/ws/tasks/T-SESSIONS'
  const { errors, posts } = await installFixture(page, {
    tasks: [makeTask('T-SESSIONS', '会话切换任务', { status: 'RUNNING', current_session_id: 'ses_new', workspace, started_at: '2026-01-01T00:00:00Z', acceptance_criteria: [{ id: 'ac-1', content: '切换 Session 后 Workspace 不串任务' }] })],
    sessions: { 'T-SESSIONS': sessionsConfig(workspace) },
    repos: { 'T-SESSIONS': { name: 'demo-repo', branch: 'main', commit: '0123456789abcdef01234567', dirty: true, changes: 3, task_changes: { changed_files: 5, commits: ['commit-one', 'commit-two'] } } },
  })
  await page.goto('/tasks/T-SESSIONS')
  const detail = page.getByTestId('task-workspace')

  await expect(detail.locator('.repo')).toHaveText('demo-repo / main · 01234567 · 累计 5 个文件 / 2 次提交 · 未提交 3')
  await expect(detail.locator('.repo')).toHaveAttribute('title', '0123456789abcdef01234567')

  await detail.getByRole('button', { name: '任务信息' }).click()
  const drawer = page.getByRole('dialog', { name: '任务信息' })
  await expect(drawer).toBeVisible()
  for (const [label, value] of [
    ['任务编号', 'T-SESSIONS'],
    ['任务类型', '问题'],
    ['优先级', '中'],
    ['执行员工', '员工-01'],
    ['当前状态', '执行中'],
    ['工作目录', workspace],
    ['执行会话', 'ses_new'],
    ['验收标准', '切换 Session 后 Workspace 不串任务'],
  ] as const) {
    await expect(drawer.getByText(label, { exact: true })).toBeVisible()
    await expect(drawer.getByText(value, { exact: true }).first()).toBeVisible()
  }
  await expect(drawer.getByText('未分类')).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  expect(posts).toEqual([])
  expect(errors).toEqual([])
})

test('WAITING 人工确认：确认完成调用 POST confirm 且页面收敛为已完成状态', async ({ page }) => {
  const workspace = '/ws/tasks/T-CONFIRM'
  const { posts, errors, frame } = await installFixture(page, {
    tasks: [makeTask('T-CONFIRM', '人工确认任务', { status: 'WAITING', completion_policy: 'MANUAL_CONFIRM', current_session_id: 'ses_c1', workspace, started_at: '2026-01-01T00:00:00Z', submitted_at: '2026-01-02T00:00:00Z', last_activity_at: '2026-01-02T00:00:00Z' })],
    sessions: { 'T-CONFIRM': [makeSession('ses_c1', '1.18.31', workspace, { status: 'SUCCEEDED' })] },
  })
  await page.goto('/tasks/T-CONFIRM')
  const detail = page.getByTestId('task-workspace')

  await expect(detail.getByRole('button', { name: '确认完成' })).toBeVisible()
  await expect(detail.getByRole('button', { name: '终止任务' })).toBeVisible()
  const confirmResponse = page.waitForResponse(response => response.url().endsWith('/api/tasks/T-CONFIRM/confirm'))
  await detail.getByRole('button', { name: '确认完成' }).click()
  const request = (await confirmResponse).request()
  expect(request.method()).toBe('POST')
  expect(await request.postDataJSON()).toEqual({})

  await expect(detail.getByRole('button', { name: '确认完成' })).toHaveCount(0)
  await expect(detail.getByRole('button', { name: '终止任务' })).toHaveCount(0)
  await expect(detail.getByRole('button', { name: '重新开始（新 Session）' })).toBeVisible()
  await expect(detail.locator('.runtime-status-badge')).toContainText('已完成')
  await expect(page.locator('.workspace-alert')).toHaveCount(0)
  await expect(frame.locator('#workspace-marker')).toHaveText('task=T-CONFIRM session=ses_c1 version=1.18.31')

  expect(posts.map(item => item.pathname)).toEqual(['/api/tasks/T-CONFIRM/confirm'])
  expect(errors).toEqual([])
})

test('连接异常：ElAlert 提示错误与最后已知状态，重连后告警清除并重建 Workspace iframe', async ({ page }) => {
  const workspace = '/ws/tasks/T-BROKEN'
  const { posts, errors, frame } = await installFixture(page, {
    tasks: [makeTask('T-BROKEN', '连接异常任务', { status: 'RUNNING', current_session_id: 'ses_b1', workspace, started_at: '2026-01-01T00:00:00Z', runtime_connection: 'UNAVAILABLE', runtime_error: 'OpenCode Server 连接失败：ECONNREFUSED' })],
    sessions: { 'T-BROKEN': [makeSession('ses_b1', '1.18.31', workspace)] },
  })
  await page.goto('/tasks/T-BROKEN')

  const alert = page.locator('.workspace-alert')
  await expect(alert).toBeVisible()
  await expect(alert).toHaveClass(/el-alert--error/)
  await expect(alert).toContainText('OpenCode Server 连接失败：ECONNREFUSED')
  await expect(alert).toContainText('最后已知状态：执行中')
  await expect(alert.getByRole('button', { name: '核对并重试未确认输入' })).toHaveCount(0)

  const reconnectResponse = page.waitForResponse(response => response.url().endsWith('/api/tasks/T-BROKEN/reconnect'))
  await alert.getByRole('button', { name: '重连' }).click()
  const request = (await reconnectResponse).request()
  expect(request.method()).toBe('POST')

  await expect(alert).toHaveCount(0)
  await expect(frame.locator('#workspace-marker')).toHaveText('task=T-BROKEN session=ses_b1 version=1.18.31')
  expect(posts.map(item => item.pathname)).toEqual(['/api/tasks/T-BROKEN/reconnect'])
  expect(errors).toEqual([])
})

test('待确认输入：warning 告警提供核对并重试入口，retry-submission 成功后告警清除', async ({ page }) => {
  const workspace = '/ws/tasks/T-PENDING'
  const { posts, errors, frame } = await installFixture(page, {
    tasks: [makeTask('T-PENDING', '输入待确认任务', { status: 'RUNNING', current_session_id: 'ses_p1', workspace, started_at: '2026-01-01T00:00:00Z', pending_message_id: 'msg_pending_1' })],
    sessions: { 'T-PENDING': [makeSession('ses_p1', '1.18.31', workspace)] },
  })
  await page.goto('/tasks/T-PENDING')

  const alert = page.locator('.workspace-alert')
  await expect(alert).toBeVisible()
  await expect(alert).toHaveClass(/el-alert--warning/)
  await expect(alert).toContainText('正在核对 Session 输入；启动中断时可先停止后重新开始。')
  const detail = page.getByTestId('task-workspace')
  await expect(detail.getByRole('button', { name: '启动任务' })).toHaveCount(0)
  await expect(detail.getByRole('button', { name: '重新开始（新 Session）' })).toHaveCount(0)

  const retryResponse = page.waitForResponse(response => response.url().endsWith('/api/tasks/T-PENDING/retry-submission'))
  await alert.getByRole('button', { name: '核对并重试未确认输入' }).click()
  const request = (await retryResponse).request()
  expect(request.method()).toBe('POST')
  expect(await request.postDataJSON()).toEqual({})

  await expect(alert).toHaveCount(0)
  await expect(detail.getByRole('button', { name: '终止任务' })).toBeVisible()
  await expect(frame.locator('#workspace-marker')).toHaveText('task=T-PENDING session=ses_p1 version=1.18.31')
  expect(posts.map(item => item.pathname)).toEqual(['/api/tasks/T-PENDING/retry-submission'])
  expect(errors).toEqual([])
})

test('跨任务隔离：切换历史 Session 后经列表进入另一任务，Session 与 iframe 不串', async ({ page }) => {
  const sessionsWorkspace = '/ws/tasks/T-SESSIONS'
  const isolateWorkspace = '/ws/tasks/T-ISOLATE'
  const { posts, errors, frame } = await installFixture(page, {
    tasks: [
      makeTask('T-SESSIONS', '会话切换任务', { status: 'RUNNING', current_session_id: 'ses_new', workspace: sessionsWorkspace, started_at: '2026-01-01T00:00:00Z' }),
      makeTask('T-ISOLATE', '隔离验证任务', { status: 'RUNNING', current_session_id: 'ses_iso', workspace: isolateWorkspace, started_at: '2026-01-01T00:00:00Z' }),
    ],
    sessions: {
      'T-SESSIONS': sessionsConfig(sessionsWorkspace),
      'T-ISOLATE': [makeSession('ses_iso', '1.18.31', isolateWorkspace)],
    },
  })
  await page.goto('/tasks/T-SESSIONS')
  await expect(page.getByTestId('session-select')).toHaveAttribute('data-session-id', 'ses_new')

  await page.getByTestId('session-select').locator('.el-select__wrapper').click()
  await page.getByRole('option', { name: 'Session #1 · 历史只读' }).click()
  await expect(frame.locator('#workspace-marker')).toHaveText('task=T-SESSIONS session=ses_old version=1.2.27')

  await page.getByRole('link', { name: '返回任务列表' }).click()
  await expect(page.getByTestId('task-list-page')).toBeVisible()
  await page.locator('.el-table__row').filter({ hasText: '隔离验证任务' }).getByRole('button', { name: '查看 T-ISOLATE' }).click()
  await expect(page).toHaveURL(/\/tasks\/T-ISOLATE$/)

  const select = page.getByTestId('session-select')
  await expect(select).toHaveAttribute('data-session-id', 'ses_iso')
  await expect(select).toContainText('Session #1 · 当前')
  await expect(page.locator('iframe[title="OpenCode Task Workspace"]')).toHaveAttribute('src', /task=T-ISOLATE&session=ses_iso$/)
  await expect(frame.locator('#workspace-marker')).toHaveText('task=T-ISOLATE session=ses_iso version=1.18.31')

  expect(posts).toEqual([])
  expect(errors).toEqual([])
})
