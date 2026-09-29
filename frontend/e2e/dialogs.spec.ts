import { expect, test, type Page } from '@playwright/test'

function makeTask(id: string, title: string, status: string, label: string) {
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
    runtime_status_label: label,
    runtime_detail: '',
    failure: null,
  }
}

const TASKS = [makeTask('T-DIALOG-SUCCEEDED', '已完成任务', 'SUCCEEDED', '已完成')]

interface MockOptions {
  failCreate?: boolean
  deletes?: string[]
}

async function mockApi(page: Page, options: MockOptions = {}) {
  await page.route('**/api/**', (route) => {
    const url = new URL(route.request().url())
    const { pathname } = url
    const method = route.request().method()
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
    if (pathname === '/api/task-categories') {
      return route.fulfill({ json: [{ id: 'CAT-1', name: '通用', description: '', color: null, sort_order: 0 }] })
    }
    if (pathname === '/api/tasks' && !url.search) {
      if (method === 'POST') {
        if (options.failCreate) return route.fulfill({ status: 500, json: { detail: '创建任务失败' } })
        return route.fulfill({ json: TASKS[0] })
      }
      return route.fulfill({ json: TASKS })
    }
    if (pathname === '/api/events' && url.searchParams.get('limit') === '40') return route.fulfill({ json: [] })
    if (/^\/api\/tasks\/[^/]+\/(start|stop|restart)$/.test(pathname) && method === 'POST') {
      return route.fulfill({ json: TASKS[0] })
    }
    const detail = pathname.match(/^\/api\/tasks\/([^/]+)$/)
    if (detail && method === 'DELETE') {
      options.deletes?.push(pathname)
      return route.fulfill({ json: { deleted: detail[1] } })
    }
    if (detail) return route.fulfill({ json: TASKS.find((item) => item.id === detail[1]) ?? TASKS[0] })
    if (pathname.match(/^\/api\/tasks\/[^/]+\/workspace$/)) {
      return route.fulfill({
        json: {
          task_id: pathname.split('/')[3],
          task_status: 'SUCCEEDED',
          runtime: { server: '', session_id: null, workspace: null, connection: 'UNKNOWN', error: null },
          sessions: [],
          history: [],
        },
      })
    }
    return route.continue()
  })
}

async function gotoTaskList(page: Page) {
  await page.goto('/tasks')
  await expect(page.getByTestId('task-list-page')).toBeVisible()
  await expect(page.locator('.el-table__row')).toHaveCount(TASKS.length)
}

function taskRow(page: Page, title: string) {
  return page.locator('.el-table__row').filter({ hasText: title })
}

test('创建任务表单点击遮罩与 ESC 都不会关闭', async ({ page }) => {
  await mockApi(page)
  await gotoTaskList(page)
  await page.getByRole('button', { name: '创建任务', exact: true }).click()

  const modal = page.getByTestId('task-create-modal')
  await expect(modal).toBeVisible()
  await modal.getByLabel('任务标题 *').fill('保护中的草稿')

  await page.locator('.el-overlay-dialog').click({ position: { x: 6, y: 6 } })
  await expect(modal).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(modal).toBeVisible()
  await expect(modal.getByLabel('任务标题 *')).toHaveValue('保护中的草稿')
})

test('有未保存修改时关闭需二次确认，取消确认后草稿保留', async ({ page }) => {
  await mockApi(page)
  await gotoTaskList(page)
  await page.getByRole('button', { name: '创建任务', exact: true }).click()

  const modal = page.getByTestId('task-create-modal')
  await modal.getByLabel('任务标题 *').fill('需要确认的草稿')
  await modal.getByRole('button', { name: '取消', exact: true }).click()

  const confirm = page.getByTestId('astra-confirm-dialog')
  await expect(confirm).toBeVisible()
  await expect(confirm).toContainText('放弃未保存的任务草稿')
  await confirm.getByRole('button', { name: '取消', exact: true }).click()
  await expect(confirm).toHaveCount(0)
  await expect(modal).toBeVisible()

  await modal.getByRole('button', { name: '取消', exact: true }).click()
  await confirm.getByRole('button', { name: '放弃并关闭' }).click()
  await expect(modal).toHaveCount(0)
})

test('危险操作确认框不会因点击空白或 ESC 误关闭', async ({ page }) => {
  const deletes: string[] = []
  await mockApi(page, { deletes })
  await gotoTaskList(page)

  await taskRow(page, '已完成任务').getByRole('button', { name: '删除 T-DIALOG-SUCCEEDED' }).click()

  const confirm = page.getByTestId('task-action-confirm')
  await expect(confirm).toBeVisible()
  await page.locator('.el-overlay-dialog').click({ position: { x: 6, y: 6 } })
  await expect(confirm).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(confirm).toBeVisible()

  await confirm.getByRole('button', { name: '取消', exact: true }).click()
  await expect(confirm).toHaveCount(0)
  expect(deletes).toEqual([])
})

test('表单提交失败后弹窗与用户输入仍然保留，错误在弹窗内展示', async ({ page }) => {
  await mockApi(page, { failCreate: true })
  await gotoTaskList(page)
  await page.getByRole('button', { name: '创建任务', exact: true }).click()

  const modal = page.getByTestId('task-create-modal')
  await modal.getByLabel('任务标题 *').fill('失败的创建草稿')
  await modal.getByLabel('任务描述 *').fill('描述内容')
  await modal.getByPlaceholder('验收标准 1').fill('验收内容')
  await modal.getByRole('button', { name: '创建任务', exact: true }).click()

  await expect(modal).toBeVisible()
  await expect(modal.locator('.form-message[data-error="true"]')).toContainText('创建任务失败')
  await expect(modal.getByLabel('任务标题 *')).toHaveValue('失败的创建草稿')
})

test('任务操作失败使用统一提示而非浏览器原生弹框', async ({ page }) => {
  const nativeDialogs: string[] = []
  page.on('dialog', (dialog) => {
    nativeDialogs.push(dialog.type())
    void dialog.dismiss()
  })
  await mockApi(page)
  await page.route('**/api/tasks/*/restart', (route) => route.fulfill({ status: 500, json: { detail: '重新执行失败' } }))
  await gotoTaskList(page)

  await taskRow(page, '已完成任务').getByRole('button', { name: '重新执行 T-DIALOG-SUCCEEDED' }).click()

  await expect(page.locator('.el-notification:has(.el-notification--error)')).toContainText('重新执行失败')
  expect(nativeDialogs).toEqual([])
})