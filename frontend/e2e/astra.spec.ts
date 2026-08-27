import { expect, test } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

test('总览展示员工当前工作和平台真实动态', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('dashboard-page')).toBeVisible()
  await expect(page.getByRole('heading', { name: '总览', exact: true })).toBeVisible()
  await expect(page.getByTestId('dashboard-v03-metrics')).toContainText('处理中任务')
  await expect(page.getByText('员工当前工作')).toBeVisible()
  await expect(page.getByText('已定位权限缓存问题，正在检查影响范围')).toBeVisible()
  await expect(page.locator('.error-banner')).toHaveCount(0)
})

test('核心页面统一使用中文业务标题', async ({ page }) => {
  await page.goto('/')
  const destinations = [
    { link: /^数字员工/, heading: '数字员工' },
    { link: /^任务中心/, heading: '任务中心' },
    { link: /^运行记录/, heading: '运行记录' },
    { link: /^人工介入/, heading: '人工介入' },
    { link: /^配置中心/, heading: '配置中心' },
  ]
  for (const destination of destinations) {
    await page.getByRole('link', { name: destination.link }).click()
    await expect(page.locator('.page').getByRole('heading', { name: destination.heading, exact: true })).toBeVisible()
  }
})

test('创建任务只填写业务信息和验收标准', async ({ page, request }) => {
  await page.goto('/tasks')
  await page.getByRole('button', { name: '创建任务', exact: true }).click()
  const modal = page.getByTestId('task-create-modal')
  await expect(modal).toBeVisible()
  await expect(modal.getByText('工程路径')).toHaveCount(0)
  await expect(modal.getByText('验证脚本')).toHaveCount(0)

  const title = `V0.4 任务 ${Date.now()}`
  await modal.getByLabel('任务标题 *').fill(title)
  await modal.getByLabel('任务描述 *').fill('验证任务定义、分类、优先级和验收标准。')
  await modal.getByPlaceholder('验收标准 1').fill('任务信息正确保存')
  await modal.getByRole('button', { name: '创建任务', exact: true }).click()

  await page.waitForURL(/\/tasks\/T-[A-Z0-9-]+$/)
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  await expect(page.locator('[data-status="READY"]')).toBeVisible()
  await expect(page.getByText('任务信息正确保存')).toBeVisible()
  await expect(page.getByText('等待领取')).toBeVisible()

  const taskId = new URL(page.url()).pathname.split('/').at(-1)!
  const response = await request.get(`/api/tasks/${taskId}`)
  const task = await response.json()
  expect(task).not.toHaveProperty('workspace')
  expect(task).not.toHaveProperty('current_phase')
  expect(task).not.toHaveProperty('progress')
  expect(task.acceptance_criteria).toHaveLength(1)
})

test('任务详情展示员工结果、验收结果和实际消耗', async ({ page }) => {
  await page.goto('/tasks/T-20260827-003')
  await expect(page.getByTestId('task-detail-page')).toBeVisible()
  await expect(page.getByText('处理结果')).toBeVisible()
  await expect(page.getByText('告警已展示接口与来源信息')).toBeVisible()
  await expect(page.getByText('满足 · 相关检查均通过')).toBeVisible()
  await expect(page.locator('.usage-panel')).toContainText('160.8K')
  await expect(page.locator('.usage-panel')).toContainText('bash')

  await page.goto('/runs/RUN-DEMO-003')
  await expect(page.getByTestId('run-detail-page')).toBeVisible()
  await expect(page.getByRole('heading', { name: '运行详情' })).toBeVisible()
  await expect(page.getByText('deepseek/deepseek-v4-flash')).toBeVisible()
})

test('员工配置只管理工作范围、工作环境和简单策略', async ({ page }) => {
  await page.goto('/settings?employee=astra-01')
  await expect(page.getByTestId('settings-page')).toBeVisible()
  await page.getByRole('button', { name: '工作范围' }).click()
  await expect(page.getByText('支持任务类型')).toBeVisible()
  await expect(page.getByText('支持任务分类')).toBeVisible()
  await expect(page.getByText('能力标签')).toHaveCount(0)
  await expect(page.getByText('技能标签')).toHaveCount(0)
  await page.getByRole('button', { name: '工作环境' }).click()
  await expect(page.getByLabel('工作空间')).toHaveValue('./workspaces/astra-01')
})
