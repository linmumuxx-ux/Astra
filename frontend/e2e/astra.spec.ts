import { expect, test } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

test('总览加载真实 API 数据且无错误横幅', async ({ page }) => {
  const metrics = page.waitForResponse(
    (response) => response.url().includes('/api/system/metrics') && response.ok(),
  )
  await page.goto('/')
  await metrics

  await expect(page.getByTestId('app-shell')).toBeVisible()
  await expect(page.getByTestId('dashboard-page')).toBeVisible()
  await expect(page.getByRole('heading', { name: '数字员工运行态势' })).toBeVisible()
  await expect(page.getByText('全部服务正常')).toBeVisible()
  await expect(page.locator('.metrics-grid')).toContainText('在线员工')
  await expect(page.getByTestId('dashboard-v02-metrics')).toContainText('今日 Token')
  await expect(page.getByTestId('dashboard-v02-metrics')).toContainText('工具调用')
  await expect(page.locator('.error-banner')).toHaveCount(0)
})

test('核心业务页面可从主导航访问', async ({ page }) => {
  await page.goto('/')
  const destinations = [
    { link: /^数字员工/, heading: '数字员工工作台' },
    { link: /^任务中心/, heading: '任务中心' },
    { link: /^运行记录/, heading: '运行记录' },
    { link: /^人工介入/, heading: '人工介入中心' },
    { link: /^配置中心/, heading: '配置中心' },
  ]

  for (const destination of destinations) {
    await page.getByRole('link', { name: destination.link }).click()
    await expect(
      page.locator('.page').getByRole('heading', { name: destination.heading, exact: true }),
    ).toBeVisible()
    await expect(page.locator('.error-banner')).toHaveCount(0)
  }
})

test('手工任务可创建、暂停、继续并留下事件证据', async ({ page, request }) => {
  await page.goto('/tasks')
  await expect(page.getByTestId('task-list-page')).toBeVisible()
  await page.getByRole('button', { name: '创建任务', exact: true }).click()
  await expect(page.getByTestId('task-create-modal')).toBeVisible()

  const title = `E2E 验收任务 ${Date.now()}`
  await page.getByLabel('任务标题').fill(title)
  await page.getByLabel('任务描述').fill('验证 Astra 管理台与 API 的任务控制闭环。')
  await page.getByLabel('工程路径').fill('/tmp/astra-e2e-project')
  await page.getByLabel('真实验证命令').fill('python -c "print(\'astra-e2e-ok\')"')
  await page.getByLabel('必需产物（可选，每行一个）').fill('README.md')
  await page.getByLabel('完成标准').fill('任务成功创建\n暂停与继续可追溯')
  await page.getByRole('button', { name: '创建并进入队列' }).click()

  await page.waitForURL(/\/tasks\/T-[A-Z0-9-]+$/)
  await expect(page.getByTestId('task-detail-page')).toBeVisible()
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  await expect(page.locator('[data-status="READY"]')).toBeVisible()
  const timeline = page.locator('.runtime-timeline')
  await expect(timeline.getByText('任务已创建', { exact: true })).toBeVisible()

  const taskId = new URL(page.url()).pathname.split('/').at(-1)!
  await page.getByRole('button', { name: '暂停' }).click()
  await expect(page.locator('[data-status="PAUSED"]')).toBeVisible()
  await expect(timeline.getByText('任务已由人工暂停', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: '继续' }).click()
  await expect(page.locator('[data-status="READY"]')).toBeVisible()
  await expect(timeline.getByText('任务已继续', { exact: true })).toBeVisible()

  const response = await request.get(`/api/tasks/${taskId}/events`)
  expect(response.ok()).toBeTruthy()
  const events = (await response.json()) as Array<{ event_type: string }>
  expect(events.map((event) => event.event_type)).toEqual([
    'TASK_CREATED',
    'TASK_READY',
    'TASK_PAUSED',
    'TASK_READY',
  ])
})

test('V0.2 可追溯员工环境、任务消耗与 Run 使用明细', async ({ page }) => {
  await page.goto('/employees')
  await expect(page.getByText('Linux · Linux Server A', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: /Astra-01/ }).click()
  await expect(page.getByTestId('employee-detail-page')).toBeVisible()
  await expect(page.getByText('默认 OpenCode 执行环境')).toBeVisible()
  await expect(page.getByText('160.8K').first()).toBeVisible()
  await expect(page.getByText('工具调用 Top')).toBeVisible()

  await page.goto('/tasks/T-20260827-001')
  await expect(page.getByText('本任务工作消耗')).toBeVisible()
  await expect(page.locator('.usage-panel')).toContainText('160.8K')
  await expect(page.locator('.usage-panel')).toContainText('internal/test-model')
  await expect(page.locator('.usage-panel')).toContainText('Bash')

  await page.goto('/runs')
  await page.getByText('RUN-DEMO-001', { exact: true }).click()
  await expect(page.getByTestId('run-detail-page')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'OpenCode 执行详情' })).toBeVisible()
  await expect(page.getByText('internal/test-model')).toBeVisible()
  await expect(page.locator('.run-summary').getByText('32', { exact: true })).toBeVisible()
})

test('V0.2 可创建员工并检测本地 OpenCode 环境', async ({ page, request }) => {
  await page.goto('/settings?create=1')
  await expect(page.getByTestId('settings-page')).toBeVisible()
  await page.getByLabel('员工 ID').fill('astra-e2e')
  await page.getByLabel('显示名称').fill('Astra-E2E')
  await page.getByLabel('岗位').fill('端到端测试员工')
  await page.getByRole('button', { name: '执行环境' }).click()
  await expect(page.getByTestId('environment-form')).toBeVisible()
  await page.getByLabel('环境名称').fill('E2E 本地 OpenCode')
  await page.getByLabel('Workspace 根目录').fill('./workspaces/astra-e2e')
  await page.getByRole('button', { name: '创建员工' }).click()
  await expect(page.getByText('员工已创建')).toBeVisible()

  await page.getByRole('button', { name: '测试连接' }).click()
  await expect(page.getByText('环境检测通过，可以领取新任务。')).toBeVisible()
  await expect(page.locator('.environment-checks')).toContainText('OpenCode')

  const response = await request.get('/api/employees/astra-e2e')
  expect(response.ok()).toBeTruthy()
  const employee = (await response.json()) as {
    execution_environment: { mode: string; status: string }
  }
  expect(employee.execution_environment).toMatchObject({ mode: 'LOCAL', status: 'AVAILABLE' })
})

test('人工介入可补充上下文并恢复待调度状态', async ({ page, request }) => {
  await page.goto('/interventions')
  await expect(page.getByTestId('intervention-page')).toBeVisible()
  await expect(page.getByText('订单支付流程回归验证', { exact: true })).toBeVisible()
  await page.getByLabel('处理说明').fill('E2E 验证：测试环境已经恢复。')
  await page.getByLabel('补充信息（可选）').fill('payment_callback_ready=true')
  await page.getByRole('button', { name: '补充并继续' }).click()

  await expect(page.getByText('没有等待人工的任务', { exact: true })).toBeVisible()
  const response = await request.get('/api/tasks/T-20260827-002')
  expect(response.ok()).toBeTruthy()
  const task = (await response.json()) as { status: string; input: Record<string, unknown> }
  expect(task.status).toBe('READY')
  expect(task.input.human_input).toBe('payment_callback_ready=true')
})
