import { expect, test } from '@playwright/test'

test('总览展示数字办公室、真实指标和员工工作现场', async ({ page }) => {
  await page.goto('/')
  const dashboard = page.getByTestId('dashboard-page')
  await expect(dashboard).toBeVisible()
  await expect(dashboard.getByRole('heading', { name: '总览', level: 2 })).toBeVisible()
  await expect(page.getByTestId('dashboard-v03-metrics')).toContainText('工作中')
  await expect(dashboard.getByRole('heading', { name: '数字办公室' })).toBeVisible()
  const workstation = dashboard.getByRole('button', { name: /Astra-01 测试平台开发/ })
  await expect(workstation).toContainText('已定位权限缓存问题，正在检查影响范围')
  await workstation.click()
  await expect(dashboard.getByRole('link', { name: '员工详情' })).toBeVisible()
  await expect(dashboard.getByRole('link', { name: '任务详情' })).toBeVisible()
  await expect(page.locator('.error-banner')).toHaveCount(0)
})

test('核心页面可从中文主导航访问', async ({ page }) => {
  await page.goto('/')
  const destinations = [
    { link: /^数字员工/, testId: 'employee-list-page', heading: '数字员工' },
    { link: /^任务中心/, testId: 'task-list-page', heading: '任务中心' },
    { link: /^运行记录/, testId: 'run-list-page', heading: '运行记录' },
    { link: /^待处理/, testId: 'intervention-page', heading: '待处理' },
    { link: /^配置中心/, testId: 'settings-page', heading: '配置中心' },
  ]
  for (const destination of destinations) {
    await page.getByRole('link', { name: destination.link }).click()
    const content = page.getByTestId(destination.testId)
    await expect(content).toBeVisible()
    await expect(content.getByRole('heading', { name: destination.heading, level: 2 })).toBeVisible()
  }
})

test('创建任务仅填写业务事实且高优先级默认人工确认', async ({ page, request }) => {
  await page.goto('/tasks')
  await page.getByRole('button', { name: '创建任务', exact: true }).click()
  const modal = page.getByTestId('task-create-modal')
  await expect(modal).toBeVisible()
  await expect(modal.getByText('工程路径')).toHaveCount(0)
  await expect(modal.getByText('验证脚本')).toHaveCount(0)

  const priority = modal.getByLabel('优先级 *')
  const completionPolicy = modal.locator('label').filter({ hasText: '完成策略' }).locator('select')
  await priority.selectOption('HIGH')
  await expect(completionPolicy).toHaveValue('MANUAL_CONFIRM')

  const title = `V0.4 E2E 任务 ${Date.now()}`
  await modal.getByLabel('任务标题 *').fill(title)
  await modal.getByLabel('任务描述 *').fill('验证任务定义、分类、优先级和验收标准。')
  await modal.getByPlaceholder('验收标准 1').fill('任务信息正确保存')
  await modal.getByRole('button', { name: '创建任务', exact: true }).click()

  await page.waitForURL(/\/tasks\/T-[A-Z0-9-]+$/)
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  await expect(page.getByText('人工确认', { exact: true })).toBeVisible()
  await expect(page.getByText('任务信息正确保存')).toBeVisible()

  const taskId = new URL(page.url()).pathname.split('/').at(-1)!
  const response = await request.get(`/api/tasks/${taskId}`)
  expect(response.ok()).toBeTruthy()
  const task = await response.json()
  expect(task).not.toHaveProperty('workspace')
  expect(task).not.toHaveProperty('current_phase')
  expect(task).not.toHaveProperty('progress')
  expect(task.completion_policy).toBe('MANUAL_CONFIRM')
  expect(task.acceptance_criteria).toHaveLength(1)
})

test('待处理角标与聚合队列一致并提供人工处理入口', async ({ page }) => {
  await page.goto('/interventions')
  const pending = page.getByTestId('intervention-page')
  await expect(page.getByRole('link', { name: /^待处理 3$/ })).toBeVisible()
  await expect(pending.getByText('3 项待处理')).toBeVisible()
  await expect(pending.getByRole('button', { name: '全部 3' })).toBeVisible()
  await expect(pending.getByRole('button', { name: '已挂起 1' })).toBeVisible()

  await pending.getByRole('button', { name: /新增回调场景自动化覆盖/ }).click()
  await expect(pending.getByLabel('补充信息')).toBeVisible()
  await expect(pending.getByRole('button', { name: '补充并继续' })).toBeVisible()
  await expect(pending.getByRole('link', { name: '查看详情' })).toHaveAttribute('href', '/tasks/T-20260827-002')
})

test('员工列表可筛选异常并通过显式链接进入详情', async ({ page }) => {
  await page.goto('/employees')
  await page.getByRole('button', { name: '列表' }).click()
  await expect(page.getByLabel('员工状态').getByRole('option', { name: '异常' })).toHaveCount(1)

  await page.getByRole('link', { name: /Astra-01 astra-01/ }).click()
  const detail = page.getByTestId('employee-detail-page')
  await expect(detail).toBeVisible()
  await expect(detail.getByRole('heading', { name: '当前工作' })).toBeVisible()
  await expect(detail).toContainText('session-task-001')
  await expect(detail).not.toContainText('8h')
  await expect(detail.getByRole('heading', { name: '历史任务' })).toBeVisible()
  await expect(detail.getByText('暂无历史任务')).toBeVisible()
})

test('运行记录列表可进入 Run 与任务详情', async ({ page }) => {
  await page.goto('/runs')
  await expect(page.getByRole('link', { name: /RUN-DEMO-003/ })).toHaveAttribute('href', '/runs/RUN-DEMO-003')
  await expect(page.getByRole('link', { name: /完善接口变更防线告警信息/ })).toHaveAttribute('href', '/tasks/T-20260827-003')

  await page.getByRole('link', { name: /RUN-DEMO-003/ }).click()
  const detail = page.getByTestId('run-detail-page')
  await expect(detail).toBeVisible()
  await expect(detail.getByText('deepseek/deepseek-v4-flash')).toBeVisible()
  await expect(detail).toContainText('160.8K')
})

test('完成任务展示结果、逐项验收和实际工作消耗', async ({ page }) => {
  await page.goto('/tasks/T-20260827-003')
  const detail = page.getByTestId('task-detail-page')
  await expect(detail).toBeVisible()
  await expect(detail.getByText('告警已展示接口与来源信息')).toBeVisible()
  await expect(detail.getByText('满足 · 相关检查均通过')).toBeVisible()
  await expect(detail.locator('.usage-panel')).toContainText('160.8K')
  await expect(detail.locator('.usage-panel')).toContainText('bash')
  await expect(detail.getByRole('link', { name: 'RUN-DEMO-003' })).toHaveAttribute('href', '/runs/RUN-DEMO-003')
})

test('员工配置只管理工作范围、工作环境和简单策略', async ({ page }) => {
  await page.goto('/settings?employee=astra-01')
  const settings = page.getByTestId('settings-page')
  await expect(settings).toBeVisible()
  await settings.getByRole('button', { name: '工作范围' }).click()
  await expect(settings.getByText('支持任务类型')).toBeVisible()
  await expect(settings.getByText('支持任务分类')).toBeVisible()
  await expect(settings.getByText('能力标签')).toHaveCount(0)
  await expect(settings.getByText('技能标签')).toHaveCount(0)
  await settings.getByRole('button', { name: '工作环境' }).click()
  await expect(settings.getByLabel('工作空间')).toHaveValue('./workspaces/astra-01')
})
