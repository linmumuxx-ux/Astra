import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const table = (page: Page) => page.getByTestId('category-table')
const rowsOf = (page: Page) => table(page).locator('.el-table__row')
const rowOf = (page: Page, name: string) => rowsOf(page).filter({ hasText: name })
const statusFilter = (page: Page) => page.locator('.category-filter__status')
const keywordFilter = (page: Page) => page.getByLabel('搜索任务分类')
const drawer = (page: Page) => page.getByTestId('category-editor-drawer')
const nameField = (page: Page) => drawer(page).getByTestId('category-form-name')
const taskPrompt = (page: Page) => drawer(page).getByLabel('任务 Prompt')
const questionPrompt = (page: Page) => drawer(page).getByLabel('问题 Prompt')

async function createCategory(request: APIRequestContext, data: Record<string, unknown>) {
  const response = await request.post('/api/task-categories', { data })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

// 抽屉带滑入动画，等它真正贴到视口右侧再截图，避免拍到半路状态。
async function settleDrawer(page: Page) {
  await expect(async () => {
    const [box, width] = await Promise.all([drawer(page).boundingBox(), page.evaluate(() => window.innerWidth)])
    expect(box && Math.abs(box.x + box.width - width) < 2).toBeTruthy()
  }).toPass({ timeout: 3000 })
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

test('新增分类走右侧抽屉表单，校验通过后落库并进入列表', async ({ page, request }) => {
  const name = `新增回归-${Date.now()}`
  await page.goto('/settings')
  await page.getByTestId('category-create').click()
  await expect(drawer(page)).toBeVisible()
  await expect(drawer(page).getByRole('heading', { name: '新增任务分类' })).toBeVisible()
  // 空表单点保存必须停在抽屉内并提示必填，不产生任何请求。
  await page.getByTestId('category-editor-submit').click()
  await expect(drawer(page).getByText('请输入分类名称')).toBeVisible()
  await expect(drawer(page)).toBeVisible()
  await expect(page.getByTestId('category-editor-dirty')).toHaveCount(0)

  await nameField(page).fill(name)
  await expect(page.getByTestId('category-editor-dirty')).toBeVisible()
  await drawer(page).locator('textarea').nth(0).fill('新增分类的描述')
  await drawer(page).locator('.el-input-number input').fill('35')
  const taskText = '  新增任务提示词 {{input}}  '
  const questionText = '新增问题提示词\nQuestion?'
  await taskPrompt(page).fill(taskText)
  await questionPrompt(page).fill(questionText)
  await settleDrawer(page)
  await page.screenshot({ path: '../artifacts/category-config/create-drawer.png', fullPage: true })
  await page.getByTestId('category-editor-submit').click()
  await expect(page.locator('.el-notification').filter({ hasText: '任务分类已创建' })).toBeVisible()
  await expect(drawer(page)).toHaveCount(0)

  const saved = (await (await request.get('/api/task-categories?include_disabled=true')).json()).find((item: { name: string }) => item.name === name)
  expect(saved.sort_order).toBe(35)
  expect(saved.enabled).toBe(true)
  expect(saved.task_prompt).toBe(taskText)
  expect(saved.question_prompt).toBe(questionText)

  await keywordFilter(page).fill(name)
  await page.getByTestId('category-search').click()
  const row = rowOf(page, name)
  await expect(row.locator('td').nth(1)).toContainText('新增分类的描述')
  await expect(row.locator('td').nth(2)).toContainText('35')
  await expect(row.getByText('任务 已配置', { exact: true })).toBeVisible()
  await expect(row.getByText('问题 已配置', { exact: true })).toBeVisible()
})

test('编辑分类预填既有字段，排序与双提示词保存后刷新保持一致', async ({ page, request }) => {
  const name = `编辑回归-${Date.now()}`
  await createCategory(request, { name, description: '编辑前描述', sort_order: 60, task_prompt: '旧任务提示词', question_prompt: '旧问题提示词' })
  await page.goto('/settings')
  await keywordFilter(page).fill(name)
  await page.getByTestId('category-search').click()
  await rowOf(page, name).getByRole('button', { name: `编辑分类 ${name}` }).click()
  await expect(drawer(page)).toBeVisible()
  await expect(drawer(page).getByRole('heading', { name: '编辑任务分类' })).toBeVisible()
  await expect(nameField(page)).toHaveValue(name)
  await expect(taskPrompt(page)).toHaveValue('旧任务提示词')
  await expect(questionPrompt(page)).toHaveValue('旧问题提示词')
  await expect(page.getByTestId('category-editor-dirty')).toHaveCount(0)

  const taskText = '  Task 123\n任务提示词 {{input}}  '
  const questionText = '问题提示词\nQuestion?'
  await taskPrompt(page).fill(taskText)
  await questionPrompt(page).fill(questionText)
  await drawer(page).locator('.el-input-number input').fill('15')
  await page.getByTestId('category-editor-submit').click()
  await expect(page.locator('.el-notification').filter({ hasText: '任务分类已更新' })).toBeVisible()
  await expect(drawer(page)).toHaveCount(0)

  await page.reload()
  await keywordFilter(page).fill(name)
  await page.getByTestId('category-search').click()
  await expect(rowOf(page, name).locator('td').nth(2)).toContainText('15')
  await rowOf(page, name).getByRole('button', { name: `编辑分类 ${name}` }).click()
  await expect(taskPrompt(page)).toHaveValue(taskText)
  await expect(questionPrompt(page)).toHaveValue(questionText)
  await settleDrawer(page)
  await page.screenshot({ path: '../artifacts/category-config/saved-prompts.png', fullPage: true })

  // 清空提示词后保存，列表回到「未配置」，刷新后仍然为空。
  await taskPrompt(page).fill('')
  await questionPrompt(page).fill('')
  await page.getByTestId('category-editor-submit').click()
  await expect(page.locator('.el-notification').filter({ hasText: '任务分类已更新' })).toBeVisible()
  await expect(rowOf(page, name).getByText('任务 未配置', { exact: true })).toBeVisible()
  await rowOf(page, name).getByRole('button', { name: `编辑分类 ${name}` }).click()
  await expect(taskPrompt(page)).toHaveValue('')
  await expect(questionPrompt(page)).toHaveValue('')
})

test('未保存修改在取消与离开页面时都要二次确认', async ({ page }) => {
  const navigation = page.getByRole('navigation', { name: '主导航' })
  const confirm = page.getByTestId('astra-confirm-dialog')
  // 抽屉是带遮罩的模态层，会挡住页面上的导航点击；路由离开只能用浏览器前进/后退触发。
  const openSettings = async () => {
    await page.goto('/tasks')
    await navigation.getByRole('menuitem', { name: /设置/ }).click()
    await expect(page).toHaveURL(/\/settings$/)
  }
  await openSettings()
  await page.getByTestId('category-create').click()
  await nameField(page).fill(`未保存-${Date.now()}`)
  await page.getByTestId('category-editor-cancel').click()
  await expect(confirm).toContainText('放弃未保存的分类修改')
  await confirm.getByRole('button', { name: '取消' }).click()
  await expect(drawer(page)).toBeVisible()
  await page.getByTestId('category-editor-cancel').click()
  await confirm.getByRole('button', { name: '放弃并关闭' }).click()
  await expect(drawer(page)).toHaveCount(0)

  // 没有修改时取消不打扰用户。
  await page.getByTestId('category-create').click()
  await page.getByTestId('category-editor-cancel').click()
  await expect(drawer(page)).toHaveCount(0)
  await expect(confirm).toHaveCount(0)

  // 抽屉打开但未改动时离开页面同样直接放行，不弹「放弃修改」。
  await page.getByTestId('category-create').click()
  await page.goBack()
  await expect(page).toHaveURL(/\/tasks?$/)
  await expect(confirm).toHaveCount(0)

  // 改动过提示词再离开，先确认；取消则留在原页面且抽屉内容不丢。
  await openSettings()
  await page.getByTestId('category-create').click()
  await nameField(page).fill(`离开未保存-${Date.now()}`)
  await taskPrompt(page).fill('离开前写的任务提示词')
  await page.goBack()
  await expect(confirm).toContainText('放弃未保存的分类修改')
  await confirm.getByRole('button', { name: '取消' }).click()
  await expect(page).toHaveURL(/\/settings$/)
  await expect(drawer(page)).toBeVisible()
  await expect(taskPrompt(page)).toHaveValue('离开前写的任务提示词')
  await page.goBack()
  await confirm.getByRole('button', { name: '放弃并离开' }).click()
  await expect(page).toHaveURL(/\/tasks?$/)

  // 改动后改回原值视为没有未保存修改，离开不打扰。
  await openSettings()
  await keywordFilter(page).fill('防线运营')
  await page.getByTestId('category-search').click()
  await rowOf(page, '防线运营').getByRole('button', { name: '编辑分类 防线运营' }).click()
  const original = await taskPrompt(page).inputValue()
  await taskPrompt(page).fill('临时改动')
  await expect(page.getByTestId('category-editor-dirty')).toBeVisible()
  await taskPrompt(page).fill(original)
  await expect(page.getByTestId('category-editor-dirty')).toHaveCount(0)
  await page.goBack()
  await expect(page).toHaveURL(/\/tasks?$/)
  await expect(confirm).toHaveCount(0)
})

test('保存失败保留抽屉内容并可重试成功', async ({ page, request }) => {
  const name = `失败重试-${Date.now()}`
  await page.goto('/settings')
  await page.getByTestId('category-create').click()
  await nameField(page).fill(name)
  let failed = false
  await page.route('**/api/task-categories', async route => {
    if (route.request().method() === 'POST' && !failed) {
      failed = true
      await route.fulfill({ status: 500, json: { detail: '分类保存失败测试' } })
    } else await route.continue()
  })
  await page.getByTestId('category-editor-submit').click()
  await expect(page.getByTestId('category-editor-error')).toContainText('分类保存失败测试')
  await expect(drawer(page)).toBeVisible()
  await expect(nameField(page)).toHaveValue(name)
  await page.getByTestId('category-editor-submit').click()
  await expect(drawer(page)).toHaveCount(0)
  const rows = await (await request.get('/api/task-categories?include_disabled=true')).json()
  expect(rows.filter((row: { name: string }) => row.name === name)).toHaveLength(1)
})

test('新建的分类立即出现在任务与员工的分类选择中', async ({ page }) => {
  const name = `跨页回归-${Date.now()}`
  await page.goto('/settings')
  await page.getByTestId('category-create').click()
  await nameField(page).fill(name)
  await page.getByTestId('category-editor-submit').click()
  await expect(page.locator('.el-notification').filter({ hasText: '任务分类已创建' })).toBeVisible()

  await page.goto('/tasks')
  await page.locator('.task-filter__select').nth(1).click()
  await expect(page.getByRole('option', { name, exact: true })).toBeVisible()
  await page.keyboard.press('Escape')

  await page.goto('/employees?create=1')
  const modal = page.getByTestId('employee-config-modal')
  await expect(modal).toBeVisible()
  await expect(modal.getByText(name, { exact: true })).toBeVisible()
})
