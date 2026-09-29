import { expect, test, type Page } from '@playwright/test'

type TaskStatus = 'PENDING' | 'RUNNING' | 'WAITING' | 'SUCCEEDED' | 'FAILED' | 'CANCELED'

const STATUS_LABEL: Record<TaskStatus, string> = {
  PENDING: '待执行',
  RUNNING: '执行中',
  WAITING: '等待人工或外部条件',
  SUCCEEDED: '已完成',
  FAILED: '执行失败',
  CANCELED: '已取消',
}

function makeTask(id: string, title: string, status: TaskStatus) {
  return {
    id,
    source: 'manual',
    external_task_id: null,
    task_type: 'ISSUE',
    category_id: null,
    title,
    description: '测试任务描述',
    acceptance_criteria: [],
    attachments: [],
    priority: 'MEDIUM',
    completion_policy: 'AUTO',
    status,
    employee_id: null,
    current_session_id: null,
    workspace: null,
    runtime_connection: 'UNKNOWN',
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
    runtime_state: status,
    runtime_status_label: STATUS_LABEL[status],
    runtime_detail: '',
    failure: null,
  }
}

const TASKS = [
  makeTask('T-MOCK-PENDING', '待执行任务', 'PENDING'),
  makeTask('T-MOCK-RUNNING', '执行中任务', 'RUNNING'),
  makeTask('T-MOCK-WAITING', '等待人工任务', 'WAITING'),
  makeTask('T-MOCK-SUCCEEDED', '已完成任务', 'SUCCEEDED'),
  makeTask('T-MOCK-FAILED', '执行失败任务', 'FAILED'),
  makeTask('T-MOCK-CANCELED', '已取消任务', 'CANCELED'),
]

interface ApiCall {
  method: string
  pathname: string
}

async function mockTaskApi(page: Page, calls: ApiCall[] = []) {
  await page.route('**/api/**', (route) => {
    const url = new URL(route.request().url())
    const { pathname, searchParams } = url
    const method = route.request().method()
    if (pathname.startsWith('/api/tasks/')) calls.push({ method, pathname })
    if (pathname === '/api/system/metrics') {
      return route.fulfill({
        json: {
          online_employees: 0,
          running_tasks: 0,
          idle_employees: 0,
          error_employees: 0,
          pending_tasks: 0,
          waiting_tasks: 0,
          failed_tasks: 0,
          completed_today: 0,
          failed_today: 0,
          today_tokens: null,
          today_tool_calls: null,
          task_status_distribution: {},
          employee_status_distribution: {},
        },
      })
    }
    if (pathname === '/api/employees') return route.fulfill({ json: [] })
    if (pathname === '/api/tasks' && !searchParams.toString()) return route.fulfill({ json: TASKS })
    if (pathname === '/api/task-categories') return route.fulfill({ json: [] })
    if (pathname === '/api/events' && searchParams.get('limit') === '40') return route.fulfill({ json: [] })
    const detail = pathname.match(/^\/api\/tasks\/([^/]+)$/)
    if (detail) {
      const task = TASKS.find((item) => item.id === detail[1])
      if (method === 'DELETE') {
        if (!task) return route.fulfill({ status: 404, json: { detail: '任务不存在' } })
        return route.fulfill({ json: { deleted: task.id } })
      }
      if (!task) return route.fulfill({ status: 404, json: { detail: '任务不存在' } })
      return route.fulfill({ json: task })
    }
    if (/^\/api\/tasks\/[^/]+\/(start|stop|restart)$/.test(pathname) && method === 'POST') {
      const task = TASKS.find((item) => pathname.includes(item.id))
      return route.fulfill({ json: task ?? TASKS[0] })
    }
    if (pathname.match(/^\/api\/tasks\/[^/]+\/workspace$/)) {
      return route.fulfill({
        json: {
          task_id: pathname.split('/')[3],
          task_status: 'PENDING',
          runtime: { server: '', session_id: null, workspace: null, connection: 'UNKNOWN', error: null },
          sessions: [],
          history: [],
        },
      })
    }
    return route.continue()
  })
}

function trackConsoleErrors(page: Page) {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function gotoTaskList(page: Page) {
  await page.goto('/tasks')
  await expect(page.getByTestId('task-list-page')).toBeVisible()
  await expect(page.locator('.el-table__row')).toHaveCount(TASKS.length)
}

function taskRow(page: Page, title: string) {
  return page.locator('.el-table__row').filter({ hasText: title })
}

async function openTaskList(page: Page, calls: ApiCall[] = []) {
  await mockTaskApi(page, calls)
  await gotoTaskList(page)
}

async function expectRowActions(page: Page, title: string, labels: string[]) {
  const row = taskRow(page, title)
  await expect(row).toHaveCount(1)
  await expect(row.getByRole('button')).toHaveCount(labels.length)
  const task = TASKS.find((item) => item.title === title)!
  const all = ['查看', '启动', '取消', '重新执行', '删除']
  for (const label of all) {
    const expectation = row.getByRole('button', { name: `${label} ${task.id}` })
    if (labels.includes(label)) await expect(expectation).toBeVisible()
    else await expect(expectation).toHaveCount(0)
  }
}

test('任务列表所有状态统一提供查看操作', async ({ page }) => {
  await openTaskList(page)
  for (const task of TASKS) {
    await expect(taskRow(page, task.title).getByRole('button', { name: `查看 ${task.id}` })).toBeVisible()
  }
})

test('待执行任务操作列提供启动、取消、删除', async ({ page }) => {
  await openTaskList(page)
  await expectRowActions(page, '待执行任务', ['查看', '启动', '取消', '删除'])
})

test('执行中任务操作列只有查看与取消', async ({ page }) => {
  await openTaskList(page)
  await expectRowActions(page, '执行中任务', ['查看', '取消'])
})

test('等待人工任务操作列只有查看与取消', async ({ page }) => {
  await openTaskList(page)
  await expectRowActions(page, '等待人工任务', ['查看', '取消'])
})

for (const title of ['已完成任务', '执行失败任务', '已取消任务']) {
  test(`${title}操作列提供重新执行和删除`, async ({ page }) => {
    await openTaskList(page)
    await expectRowActions(page, title, ['查看', '重新执行', '删除'])
  })
}

test('点击查看按钮进入对应任务，不会跳错', async ({ page }) => {
  await openTaskList(page)
  await taskRow(page, '待执行任务').getByRole('button', { name: '查看 T-MOCK-PENDING' }).click()
  await page.waitForURL('**/tasks/T-MOCK-PENDING')
  await expect(page.getByTestId('task-workspace').getByRole('heading', { name: '待执行任务' })).toBeVisible()

  await page.goBack()
  await expect(page.locator('.el-table__row')).toHaveCount(TASKS.length)

  await taskRow(page, '执行失败任务').getByRole('button', { name: '查看 T-MOCK-FAILED' }).click()
  await page.waitForURL('**/tasks/T-MOCK-FAILED')
  await expect(page.getByTestId('task-workspace').getByRole('heading', { name: '执行失败任务' })).toBeVisible()
})

test('删除任务需要二次确认，且只作用于当前行任务', async ({ page }) => {
  const calls: ApiCall[] = []
  await openTaskList(page, calls)

  await taskRow(page, '已完成任务').getByRole('button', { name: '删除 T-MOCK-SUCCEEDED' }).click()

  const confirm = page.getByTestId('task-action-confirm')
  await expect(confirm).toBeVisible()
  await expect(confirm.getByRole('heading', { name: '删除任务' })).toBeVisible()
  await expect(confirm).toContainText('已完成任务')

  await confirm.getByRole('button', { name: '确认删除任务' }).click()
  await expect(confirm).toHaveCount(0)
  await expect(calls).toContainEqual({ method: 'DELETE', pathname: '/api/tasks/T-MOCK-SUCCEEDED' })
  expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)
})

test('取消任务需要二次确认，且只作用于当前行任务', async ({ page }) => {
  const calls: ApiCall[] = []
  await openTaskList(page, calls)

  await taskRow(page, '执行中任务').getByRole('button', { name: '取消 T-MOCK-RUNNING' }).click()

  const confirm = page.getByTestId('task-action-confirm')
  await expect(confirm).toBeVisible()
  await expect(confirm).toContainText('执行中任务')

  await confirm.getByRole('button', { name: '确认取消任务' }).click()
  await expect(confirm).toHaveCount(0)
  await expect(calls).toContainEqual({ method: 'POST', pathname: '/api/tasks/T-MOCK-RUNNING/stop' })
})

test('任务列表不再出现 Workspace 等旧文案', async ({ page }) => {
  await openTaskList(page)
  const list = page.getByTestId('task-list-page')
  for (const forbidden of ['Workspace', '进入 Workspace', 'Enter Workspace', 'Session Workspace', 'OpenCode Workspace', '查看进展', '查看结果', '查看问题', '更多操作', '查看详情']) {
    await expect(list.getByText(forbidden, { exact: false })).toHaveCount(0)
  }
})

test('任务列表操作没有新增 console error', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  await openTaskList(page)

  await taskRow(page, '已完成任务').getByRole('button', { name: '删除 T-MOCK-SUCCEEDED' }).click()
  const confirm = page.getByTestId('task-action-confirm')
  await expect(confirm).toBeVisible()
  await confirm.getByRole('button', { name: '取消', exact: true }).click()
  await expect(confirm).toHaveCount(0)

  await taskRow(page, '待执行任务').getByRole('button', { name: '查看 T-MOCK-PENDING' }).click()
  await page.waitForURL('**/tasks/T-MOCK-PENDING')

  expect(errors).toEqual([])
})
