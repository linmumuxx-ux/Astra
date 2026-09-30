import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const table = (page: Page) => page.getByTestId('category-table')
const rowsOf = (page: Page) => table(page).locator('.el-table__row')
const rowOf = (page: Page, name: string) => rowsOf(page).filter({ hasText: name })
const statusFilter = (page: Page) => page.getByTestId('category-filter-status')
const keywordFilter = (page: Page) => page.getByTestId('category-filter-keyword')
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

test('抽屉内有未保存修改时取消要二次确认，无改动直接关闭', async ({ page }) => {
  const confirm = page.getByTestId('astra-confirm-dialog')
  const name = `未保存-${Date.now()}`
  await page.goto('/settings')
  await page.getByTestId('category-create').click()
  await nameField(page).fill(name)
  await page.getByTestId('category-editor-cancel').click()
  await expect(confirm).toContainText('放弃未保存的分类修改')
  await confirm.getByRole('button', { name: '取消' }).click()
  await expect(drawer(page)).toBeVisible()
  // 取消确认后抽屉与已填内容都留在原处，不该被清掉。
  await expect(nameField(page)).toHaveValue(name)
  await page.getByTestId('category-editor-cancel').click()
  await confirm.getByRole('button', { name: '放弃并关闭' }).click()
  await expect(drawer(page)).toHaveCount(0)

  // 没有修改时取消不打扰用户。
  await page.getByTestId('category-create').click()
  await page.getByTestId('category-editor-cancel').click()
  await expect(drawer(page)).toHaveCount(0)
  await expect(confirm).toHaveCount(0)
})

// 路由守卫只依赖抽屉的 dirty 状态，与分类条数无关：用隔离 mock 数据断言各个状态，
// 不受本地后端累积的测试分类影响（真实数据的抽屉确认由上一个用例覆盖）。
async function mockCategoryApi(page: Page) {
  const categories = [
    { id: 'cat-nav-1', name: '导航守卫甲', description: '隔离 mock 数据', sort_order: 10, enabled: true, task_prompt: '', question_prompt: '' },
    { id: 'cat-nav-2', name: '导航守卫乙', description: '隔离 mock 数据', sort_order: 20, enabled: true, task_prompt: '原始任务提示词', question_prompt: '' },
  ]
  await page.route((url) => url.pathname.startsWith('/api/'), async route => {
    const { pathname } = new URL(route.request().url())
    const method = route.request().method()
    if (pathname === '/api/events/stream') {
      return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream' }, body: '' })
    }
    if (pathname === '/api/task-categories' && method === 'POST') {
      const created = { id: `cat-nav-new-${categories.length}`, ...route.request().postDataJSON() }
      categories.push(created)
      return route.fulfill({ json: created })
    }
    if (pathname === '/api/task-categories') return route.fulfill({ json: categories })
    const target = /^\/api\/task-categories\/(.+)$/.exec(pathname)
    if (target) {
      const found = categories.find((item) => item.id === target[1])
      if (found && method === 'PATCH') Object.assign(found, route.request().postDataJSON())
      return route.fulfill({ json: found ?? {} })
    }
    if (pathname === '/api/employees' || pathname === '/api/tasks' || pathname === '/api/events') return route.fulfill({ json: [] })
    return route.fulfill({ json: {} })
  })
}

test('切换菜单路由只在抽屉确有未保存修改时确认', async ({ page }) => {
  const navigation = page.getByRole('navigation', { name: '主导航' })
  const confirm = page.getByTestId('astra-confirm-dialog')
  await mockCategoryApi(page)

  // 每个场景都从 /tasks 出发并用菜单进入配置中心，保证前进后退都是同文档导航，会真正触发路由守卫。
  const openSettings = async () => {
    await expect(page).toHaveURL(/\/tasks$/)
    await navigation.getByRole('menuitem', { name: /^设置$/ }).click()
    await expect(page).toHaveURL(/\/settings$/)
    await expect(table(page)).toBeVisible()
  }
  const clickTasks = async () => {
    await navigation.getByRole('menuitem', { name: /^任务管理$/ }).click()
    await expect(page).toHaveURL(/\/tasks$/)
    await expect(confirm).toHaveCount(0)
  }
  await page.goto('/tasks')

  // 从未打开过抽屉：没有可丢失的内容，点菜单立即离开，不弹「放弃未保存…」。
  await openSettings()
  await expect(drawer(page)).toHaveCount(0)
  await clickTasks()

  // 抽屉打开但没改过：关闭后切菜单同样直接离开。
  await openSettings()
  await page.getByTestId('category-create').click()
  await expect(drawer(page)).toBeVisible()
  await page.getByTestId('category-editor-cancel').click()
  await expect(drawer(page)).toHaveCount(0)
  await expect(confirm).toHaveCount(0)
  await clickTasks()

  // 改过又确认放弃并关闭：内容已经丢弃，再切菜单不该二次打扰。
  await openSettings()
  await page.getByTestId('category-create').click()
  await nameField(page).fill('已放弃的分类名')
  await expect(page.getByTestId('category-editor-dirty')).toBeVisible()
  await page.getByTestId('category-editor-cancel').click()
  await confirm.getByRole('button', { name: '放弃并关闭' }).click()
  await expect(drawer(page)).toHaveCount(0)
  await clickTasks()

  // 新建保存成功后切菜单不误弹。
  await openSettings()
  await page.getByTestId('category-create').click()
  await nameField(page).fill('导航守卫新建')
  await page.getByTestId('category-editor-submit').click()
  await expect(page.locator('.el-notification').filter({ hasText: '任务分类已创建' })).toBeVisible()
  await expect(drawer(page)).toHaveCount(0)
  await clickTasks()

  // 编辑保存成功后同样不误弹。
  await openSettings()
  await rowOf(page, '导航守卫乙').getByRole('button', { name: '编辑分类 导航守卫乙' }).click()
  await taskPrompt(page).fill('改过的任务提示词')
  await page.getByTestId('category-editor-submit').click()
  await expect(page.locator('.el-notification').filter({ hasText: '任务分类已更新' })).toBeVisible()
  await clickTasks()

  // 确有未保存修改时离开仍要确认：取消则留在配置中心且表单不丢，确认后才离开。
  // 抽屉遮罩会挡住菜单点击，因此这一步用浏览器后退触发路由离开。
  await openSettings()
  await page.getByTestId('category-create').click()
  await nameField(page).fill('离开未保存')
  await taskPrompt(page).fill('离开前写的任务提示词')
  await page.goBack()
  await expect(confirm).toContainText('放弃未保存的分类修改')
  await confirm.getByRole('button', { name: '取消' }).click()
  await expect(page).toHaveURL(/\/settings$/)
  await expect(drawer(page)).toBeVisible()
  await expect(taskPrompt(page)).toHaveValue('离开前写的任务提示词')
  await page.goBack()
  await confirm.getByRole('button', { name: '放弃并离开' }).click()
  await expect(page).toHaveURL(/\/tasks$/)

  // 抽屉打开但未改动时离开同样直接放行。
  await openSettings()
  await page.getByTestId('category-create').click()
  await page.goBack()
  await expect(page).toHaveURL(/\/tasks$/)
  await expect(confirm).toHaveCount(0)

  // 改动后改回原值视为没有未保存修改，离开不打扰。
  await openSettings()
  await rowOf(page, '导航守卫乙').getByRole('button', { name: '编辑分类 导航守卫乙' }).click()
  const original = await taskPrompt(page).inputValue()
  await taskPrompt(page).fill('临时改动')
  await expect(page.getByTestId('category-editor-dirty')).toBeVisible()
  await taskPrompt(page).fill(original)
  await expect(page.getByTestId('category-editor-dirty')).toHaveCount(0)
  await page.goBack()
  await expect(page).toHaveURL(/\/tasks$/)
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
  await page.getByTestId('task-filter-category').locator('.el-select__wrapper').click()
  await expect(page.getByRole('option', { name, exact: true })).toBeVisible()
  await page.keyboard.press('Escape')

  await page.goto('/employees?create=1')
  const modal = page.getByTestId('employee-config-modal')
  await expect(modal).toBeVisible()
  await expect(modal.getByText(name, { exact: true })).toBeVisible()
})
