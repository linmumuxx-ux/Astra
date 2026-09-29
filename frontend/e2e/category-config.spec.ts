import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const table = (page: Page) => page.getByTestId('category-table')
const rowsOf = (page: Page) => table(page).locator('.el-table__row')
const rowOf = (page: Page, name: string) => rowsOf(page).filter({ hasText: name })
const statusFilter = (page: Page) => page.locator('.category-filter__status')
const keywordFilter = (page: Page) => page.getByLabel('搜索任务分类')

async function createCategory(request: APIRequestContext, data: Record<string, unknown>) {
  const response = await request.post('/api/task-categories', { data })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

test('任务分类列表展示名称、描述、排序、启用与提示词状态', async ({ page, request }) => {
  const name = `列表回归-${Date.now()}`
  await createCategory(request, { name, description: '列表展示与筛选回归', sort_order: 5, task_prompt: '任务提示词', question_prompt: '问题提示词' })
  await page.goto('/settings')
  await expect(table(page)).toBeVisible()
  const row = rowOf(page, name)
  await expect(row).toBeVisible()
  await expect(row.locator('td').nth(0)).toContainText(name)
  await expect(row.locator('td').nth(1)).toContainText('列表展示与筛选回归')
  await expect(row.locator('td').nth(2)).toContainText('5')
  await expect(row.getByText('已启用', { exact: true })).toBeVisible()
  await expect(row.getByText('任务 已配置', { exact: true })).toBeVisible()
  await expect(row.getByText('问题 已配置', { exact: true })).toBeVisible()
  // 未配置提示词的分类以「未配置」呈现，不伪造内容。
  const plain = rowOf(page, '防线运营')
  await expect(plain.getByText('任务 未配置', { exact: true })).toBeVisible()
  await expect(plain.getByText('问题 未配置', { exact: true })).toBeVisible()
  await page.screenshot({ path: '../artifacts/category-config/list.png', fullPage: true })
})

test('状态与关键词筛选即时生效并重置到第一页', async ({ page, request }) => {
  const name = `筛选回归-${Date.now()}`
  await createCategory(request, { name, description: '只用于筛选回归' })
  await page.goto('/settings')
  await expect(rowOf(page, name)).toBeVisible()
  await statusFilter(page).click()
  await page.getByRole('option', { name: '已停用' }).click()
  await expect(page.getByTestId('category-total')).toHaveText('共 0 条')
  await expect(page.getByText('没有匹配的任务分类')).toBeVisible()
  await statusFilter(page).click()
  await page.getByRole('option', { name: '已启用' }).click()
  await expect(rowOf(page, name)).toBeVisible()

  await keywordFilter(page).fill(name)
  await page.getByTestId('category-search').click()
  await expect(rowsOf(page)).toHaveCount(1)
  await expect(page.getByTestId('category-total')).toHaveText('共 1 条')
  await keywordFilter(page).fill('不存在的分类关键字')
  await page.getByTestId('category-search').click()
  await expect(page.getByTestId('category-total')).toHaveText('共 0 条')
  await keywordFilter(page).fill('')
  await page.getByTestId('category-search').click()
  await expect(rowsOf(page).first()).toBeVisible()
})

test('列表内启停立即落库并刷新平台分类缓存', async ({ page, request }) => {
  const name = `启停回归-${Date.now()}`
  const category = await createCategory(request, { name, description: '启停回归', sort_order: 40, task_prompt: '任务提示词', question_prompt: null })
  await page.goto('/settings')
  const row = rowOf(page, name)
  await expect(row).toBeVisible()

  await row.getByRole('button', { name: `停用分类 ${name}` }).click()
  await expect(page.locator('.el-notification').filter({ hasText: '分类已停用' })).toBeVisible()
  await expect(row.getByText('已停用', { exact: true })).toBeVisible()
  const afterDisable = await (await request.get('/api/task-categories?include_disabled=true')).json()
  expect(afterDisable.find((item: { id: string }) => item.id === category.id).enabled).toBe(false)

  // 停用只影响新任务选择：平台其他页面仍按启用分类渲染，停用后仍可再次启用。
  await row.getByRole('button', { name: `启用分类 ${name}` }).click()
  await expect(page.locator('.el-notification').filter({ hasText: '分类已启用' })).toBeVisible()
  await expect(row.getByText('已启用', { exact: true })).toBeVisible()
  const afterEnable = await (await request.get('/api/task-categories?include_disabled=true')).json()
  expect(afterEnable.find((item: { id: string }) => item.id === category.id).enabled).toBe(true)
})

test('列表底部左侧总数与右侧分页同步', async ({ page, request }) => {
  const prefix = `分页回归-${Date.now()}`
  for (let index = 0; index < 12; index += 1) {
    await createCategory(request, { name: `${prefix}-${index}`, sort_order: 100 + index })
  }
  await page.goto('/settings')
  await keywordFilter(page).fill(prefix)
  await page.getByTestId('category-search').click()
  await expect(page.getByTestId('category-total')).toHaveText('共 12 条')
  await expect(rowsOf(page)).toHaveCount(10)
  await page.getByTestId('category-pagination').getByRole('button', { name: '下一页' }).click()
  await expect(rowsOf(page)).toHaveCount(2)
  await page.getByTestId('category-pagination').getByRole('button', { name: '上一页' }).click()
  await expect(rowsOf(page)).toHaveCount(10)
})

test('初次加载失败给出错误与重试入口', async ({ page }) => {
  let failed = false
  await page.route('**/api/task-categories?include_disabled=true', async route => {
    if (!failed) { failed = true; await route.fulfill({ status: 500, json: { detail: '分类加载失败测试' } }) }
    else await route.continue()
  })
  await page.goto('/settings')
  await expect(page.getByTestId('category-error')).toContainText('分类加载失败测试')
  await page.getByTestId('category-retry').click()
  await expect(rowsOf(page).first()).toBeVisible()
  await expect(page.getByTestId('category-error')).toHaveCount(0)
})
