import { expect, test } from '@playwright/test'
import { createServer } from 'node:net'

async function freePort(): Promise<number> {
  return await new Promise((resolve, reject) => {
    const server = createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close(() => resolve(port))
    })
  })
}

test('首页展示数据看板、业务导航和聚合数据', async ({ page }) => {
  const requests: string[] = []
  page.on('request', (request) => requests.push(new URL(request.url()).pathname))

  await page.goto('/')
  const dashboard = page.getByTestId('dashboard-page')
  await expect(dashboard.getByRole('region', { name: '当前空间状态' })).toBeVisible()
  await expect(dashboard.getByRole('heading', { name: '数字员工', level: 1 })).toBeVisible()
  await expect(dashboard.getByRole('heading', { name: /需要处理/, level: 1 })).toBeVisible()
  await expect(dashboard.getByRole('heading', { name: '最近任务', level: 1 })).toBeVisible()
  await expect(dashboard.getByRole('heading', { name: '最近动态', level: 1 })).toBeVisible()
  await expect(dashboard.getByRole('heading', { name: '数字图书馆', level: 1 })).toBeVisible()
  await expect(dashboard.locator('.space-card')).toHaveCount(4)
  await expect(dashboard.locator('.library-scene')).toHaveCount(1)
  await expect(dashboard.getByRole('img', { name: '近 7 日完成任务数与任务总数趋势' })).toHaveCount(0)
  await expect(dashboard.getByText('数字办公室')).toHaveCount(0)
  await expect(dashboard.locator('canvas')).toHaveCount(0)

  const navigation = page.getByRole('navigation', { name: '主导航' })
  for (const label of ['首页', '数字员工', '任务管理', '数字图书馆', '设置']) {
    await expect(navigation.getByRole('menuitem', { name: new RegExp(label) })).toBeVisible()
  }
  await expect(page.getByRole('link', { name: '消息通知' })).toBeVisible()
  expect(requests).not.toContain('/api/events/stream')
  expect(requests.some((path) => path === '/api/dashboard/overview')).toBeTruthy()

  const refreshed = page.waitForResponse((response) => response.url().includes('/api/dashboard/overview'))
  await dashboard.getByRole('button', { name: '刷新首页数据' }).click()
  await refreshed
  await expect(dashboard.getByText(/最近刷新 \d{2}:\d{2}/)).toBeVisible()

  const pageSize = await page.evaluate(() => ({ clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth }))
  expect(pageSize.scrollWidth).toBeLessThanOrEqual(pageSize.clientWidth)
})

test('首页单模块失败不影响其他模块并保留筛选跳转', async ({ page }) => {
  await page.route('**/api/dashboard/overview', (route) => route.fulfill({ json: { employee_total: 24, team_count: 3, working_employees: 8, running_tasks: 12, completed_today: 36, attention_total: 3 } }))
  await page.route('**/api/dashboard/employees', (route) => route.fulfill({ json: { teams: [{ id: 'automation', name: '自动化工程', order: 10, employee_count: 1, employees: [{ id: 'dashboard-employee', name: '圆YY', role: '自动化工程师', status: 'WORKING', state: 'working', state_label: '执行中', current_task: { id: 'T-DASHBOARD', title: '自动化问题定位', status: 'RUNNING' } }] }] } }))
  await page.route('**/api/dashboard/attention', (route) => route.fulfill({ json: { items: [] } }))
  await page.route('**/api/dashboard/tasks', (route) => route.fulfill({ status: 503, json: { detail: '趋势服务不可用' } }))
  await page.route('**/api/dashboard/activity', (route) => route.fulfill({ json: { items: [] } }))
  await page.route('**/api/dashboard/knowledge', (route) => route.fulfill({ json: { today_added: 6, candidate_experiences: 4, total: 128, recent: [] } }))

  await page.goto('/')
  const dashboard = page.getByTestId('dashboard-page')
  await expect(dashboard.locator('.summary-metrics').getByRole('link', { name: '24 名数字员工' })).toBeVisible()
  await expect(dashboard.getByRole('region', { name: '自动化工程团队' })).toContainText('圆YY')
  await expect(dashboard.getByText('正在执行', { exact: true })).toBeVisible()
  await expect(dashboard.getByText('最近任务暂时无法获取')).toBeVisible()
  await expect(dashboard.getByText('当前无需处理')).toBeVisible()
  await expect(dashboard.locator('.library-scene')).toContainText('今天沉淀 6 条知识，4 条经验等待整理')

  await dashboard.locator('.summary-metrics').getByRole('link', { name: '8 工作中' }).click()
  await expect(page).toHaveURL(/\/employees\?status=WORKING$/)
  await page.locator('.employee-filter__status').click()
  await expect(page.getByRole('option', { name: '工作中' })).toHaveAttribute('aria-selected', 'true')
})

test('核心页面可从中文主导航访问', async ({ page }) => {
  await page.goto('/')
  const navigation = page.getByRole('navigation', { name: '主导航' })
  const destinations = [
    { link: /^数字员工/, testId: 'employee-list-page', heading: '数字员工' },
    { link: /^任务管理$/, testId: 'task-list-page', heading: '任务管理' },
    { link: /^数字图书馆/, testId: 'digital-library-page', heading: '数字图书馆' },
    { link: /^设置$/, testId: 'settings-page', heading: '配置中心' },
  ]
  for (const destination of destinations) {
    await navigation.getByRole('menuitem', { name: destination.link }).click()
    const content = page.getByTestId(destination.testId)
    await expect(content).toBeVisible()
    await expect(content.getByRole('heading', { name: destination.heading, level: 2 })).toBeVisible()
  }
})

test('导航深层路径保持父级菜单高亮', async ({ page }) => {
  await page.goto('/employees/astra-01')
  const navigation = page.getByRole('navigation', { name: '主导航' })
  await expect(navigation.getByRole('menuitem', { name: /^数字员工/ })).toHaveClass(/is-active/)
  await expect(navigation.getByRole('menuitem', { name: /^首页/ })).not.toHaveClass(/is-active/)
})

test('全局搜索与 URL q 参数双向同步并支持清空', async ({ page }) => {
  await page.goto('/?q=流水线')
  const search = page.getByLabel('全局搜索')
  await expect(search).toHaveValue('流水线')

  await search.fill('回调')
  await search.press('Enter')
  expect(new URL(page.url()).searchParams.get('q')).toBe('回调')

  await page.goto('/tasks')
  await expect(search).toHaveValue('回调')
  await search.press('Enter')
  await expect(page).toHaveURL(/\?q=/)
  await expect(page.getByTestId('dashboard-page')).toBeVisible()

  await search.hover()
  await page.locator('.global-search .el-input__clear').click()
  await expect(search).toHaveValue('')
  expect(new URL(page.url()).searchParams.has('q')).toBe(false)
})

test('数字图书馆支持当前空间搜索、安全 Markdown 弹框和滚动恢复', async ({ page, request }) => {
  const spacesResponse = await request.get('/api/library/spaces')
  expect(spacesResponse.ok()).toBeTruthy()
  const spaces = await spacesResponse.json()
  const title = `流水线 50004 E2E ${Date.now()}`
  const createdResponse = await request.post('/api/library/knowledge', {
    data: {
      space_id: spaces[0].id,
      title,
      type: 'experience',
      summary: '验证数字图书馆搜索和安全渲染',
      content_md: '## 问题现象\n\n返回 `50004`。\n\n<img src="x" onerror="window.__libraryXss = true">\n\n<script>window.__libraryXss = true</script>',
      tags: ['流水线', '50004'],
    },
  })
  expect(createdResponse.ok()).toBeTruthy()
  const created = await createdResponse.json()
  const publishedResponse = await request.post(`/api/library/knowledge/${created.id}/publish`, {
    data: { space_id: spaces[0].id, verification_status: 'verified' },
  })
  expect(publishedResponse.ok()).toBeTruthy()

  await page.goto('/library')
  const library = page.getByTestId('digital-library-page')
  await expect(library.getByRole('heading', { name: '数字图书馆', level: 2 })).toBeVisible()
  await expect(library.getByRole('heading', { name: '知识空间', exact: true })).toBeVisible()
  await library.getByLabel('搜索当前空间').fill('50004')
  await expect(library.getByText(title, { exact: true })).toBeVisible()
  await library.getByText(title, { exact: true }).click()

  const dialog = page.getByTestId('knowledge-detail-dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('heading', { name: title })).toBeVisible()
  await expect(dialog.getByRole('heading', { name: '问题现象' })).toBeVisible()
  await expect(dialog.locator('.markdown-body script')).toHaveCount(0)
  await expect(dialog.locator('.markdown-body [onerror]')).toHaveCount(0)
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('hidden')
  await dialog.getByRole('button', { name: '关闭知识详情' }).click()
  await expect(dialog).toHaveCount(0)
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden')
})

test('数字图书馆兼容平铺空间响应且目录菜单只在点击后出现', async ({ page, request }) => {
  const spacesResponse = await request.get('/api/library/spaces')
  expect(spacesResponse.ok()).toBeTruthy()
  const spaces = await spacesResponse.json()
  const flatSpaces = spaces.map(({ children: _children, subtree_knowledge_count: _count, ...space }: Record<string, unknown>) => space)
  await page.route('**/api/library/spaces', (route) => route.fulfill({ json: flatSpaces }))
  await page.route('**/api/library/knowledge/*/usages*', (route) => route.fulfill({
    status: 404,
    json: { detail: 'Not Found' },
  }))

  const spaceId = spaces[0].id
  const title = `平铺空间 E2E ${Date.now()}`
  const createdResponse = await request.post('/api/library/knowledge', {
    data: {
      space_id: spaceId,
      title,
      type: 'experience',
      summary: '验证平铺空间响应下的知识详情展示',
      content_md: '## 问题现象\n\n平铺空间响应不应影响知识详情。',
      tags: ['平铺空间'],
    },
  })
  expect(createdResponse.ok()).toBeTruthy()
  const created = await createdResponse.json()
  const publishedResponse = await request.post(`/api/library/knowledge/${created.id}/publish`, {
    data: { space_id: spaceId, verification_status: 'verified' },
  })
  expect(publishedResponse.ok()).toBeTruthy()

  await page.goto('/library')
  const library = page.getByTestId('digital-library-page')
  await expect(library.getByText('公共知识库', { exact: true })).toBeVisible()
  await expect(library.locator('.library-error')).toHaveCount(0)
  await expect(library.getByText('新建子目录', { exact: true })).toHaveCount(0)

  const row = library.locator('.knowledge-table-wrap tbody tr').filter({ hasText: title })
  await expect(row).toBeVisible()
  await row.click()
  const detail = page.getByTestId('knowledge-detail-dialog')
  await expect(detail).toBeVisible()
  await expect(detail.locator('.detail-error')).toHaveCount(0)
  await detail.getByRole('button', { name: '关闭知识详情' }).click()

  await library.getByRole('button', { name: /^管理目录 / }).first().click()
  await expect(library.getByText('新建子目录', { exact: true })).toBeVisible()
  await expect(library.getByText('移动到…', { exact: true })).toHaveCount(0)

  await page.route('**/api/library/permissions', (route) => route.fulfill({
    json: { user_id: 'viewer-e2e', role: 'viewer', can_manage: false, can_review: false },
  }))
  await page.reload()
  const statusFilter = library.getByLabel('知识状态')
  await expect(statusFilter).toBeVisible()
  const statusOptions = await statusFilter.locator('option').allTextContents()
  expect(statusOptions).toEqual(['全部状态', '已发布'])
  await expect(library.getByRole('button', { name: /^管理目录 / })).toHaveCount(0)
})

test('数字图书馆目录创建保持在树内原位置并自动进入新目录', async ({ page }) => {
  await page.goto('/library')
  const library = page.getByTestId('digital-library-page')
  const rootRow = library.locator('.tree-node').first()
  const rootName = (await rootRow.locator('.space-label em').first().textContent())?.trim()
  expect(rootName).toBeTruthy()

  await rootRow.getByRole('button', { name: /^管理目录 / }).click()
  await rootRow.getByRole('button', { name: '新建子目录' }).click()

  const childName = `E2E 子目录 ${Date.now()}`
  const inlineInput = rootRow.getByLabel('子目录名称')
  await expect(inlineInput).toBeVisible()
  await inlineInput.fill(childName)
  await inlineInput.press('Enter')

  await expect(library.getByText(childName, { exact: true })).toBeVisible()
  await expect(library.getByRole('heading', { name: new RegExp(childName) })).toBeVisible()
  await expect(library.getByLabel('子目录名称')).toHaveCount(0)
})

test('创建任务仅填写业务事实且高优先级默认人工确认', async ({ page, request }) => {
  await page.goto('/tasks')
  await page.getByRole('button', { name: '创建任务', exact: true }).click()
  const modal = page.getByTestId('task-create-modal')
  await expect(modal).toBeVisible()
  await expect(modal.getByText('工程路径')).toHaveCount(0)
  await expect(modal.getByText('验证脚本')).toHaveCount(0)

  const priority = modal.getByLabel('优先级 *')
  const completionPolicy = modal.getByLabel('完成策略', { exact: true })
  await priority.selectOption('HIGH')
  await expect(completionPolicy).toHaveValue('MANUAL_CONFIRM')

  const title = `V0.4 E2E 任务 ${Date.now()}`
  await modal.getByLabel('任务标题 *').fill(title)
  await modal.getByLabel('任务描述 *').fill('验证任务定义、分类、优先级和验收标准。')
  await modal.getByPlaceholder('验收标准 1').fill('任务信息正确保存')
  await modal.getByRole('button', { name: '创建任务', exact: true }).click()

  await page.waitForURL(/\/tasks\/T-[A-Z0-9-]+$/)
  await expect(page.getByTestId('task-workspace')).toBeVisible()
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  // 新任务尚未创建 Session，详情进入原生 Workspace 空状态，而非旧的对话/结果页。
  await expect(page.getByText('任务尚未创建 Session，请先启动任务。')).toBeVisible()
  await page.getByRole('button', { name: '任务信息' }).click()
  await expect(page.getByText('任务信息正确保存')).toBeVisible()

  const taskId = new URL(page.url()).pathname.split('/').at(-1)!
  const response = await request.get(`/api/tasks/${taskId}`)
  expect(response.ok()).toBeTruthy()
  const task = await response.json()
  expect(task.workspace).toBeNull()
  expect(task.current_session_id).toBeNull()
  expect(task).not.toHaveProperty('current_phase')
  expect(task).not.toHaveProperty('progress')
  expect(task.completion_policy).toBe('MANUAL_CONFIRM')
  expect(task.acceptance_criteria).toHaveLength(1)
})

test('待处理角标与聚合队列一致并提供进入 Workspace 入口', async ({ page }) => {
  await page.goto('/interventions')
  const pending = page.getByTestId('intervention-page')
  await expect(page.getByRole('link', { name: '消息通知' }).locator('.el-badge__content')).toHaveText('3')
  await expect(pending.getByRole('heading', { name: '待处理', exact: true })).toBeVisible()
  // 状态收敛后待处理只保留「等待人工或外部条件」与「执行失败」两类入口。
  await expect(pending.getByRole('button', { name: /等待人工或外部条件 · 3/ })).toBeVisible()
  await expect(pending.getByRole('button', { name: /执行失败 · 0/ })).toBeVisible()
  await expect(pending.locator('.intervention-task')).toHaveCount(3)

  // 人工介入已收敛进任务 Workspace，列表只提供进入 Workspace 的入口。
  const item = pending.locator('.intervention-task').filter({ hasText: '新增回调场景自动化覆盖' })
  await expect(item.getByRole('link', { name: '进入任务详情' })).toHaveAttribute('href', '/tasks/T-20260827-002')
})

test('员工管理使用列表、筛选分页并优先打开详情抽屉', async ({ page }) => {
  await page.goto('/employees')
  await page.locator('.employee-filter__status').click()
  await expect(page.getByRole('option', { name: '异常' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByLabel('数字员工列表').getByRole('table').first()).toBeVisible()
  await expect(page.getByLabel('员工列表分页')).toBeVisible()
  await page.getByRole('button', { name: '查看 员工-03' }).click()
  const drawer = page.getByRole('dialog', { name: '员工-03 员工详情' })
  await expect(drawer).toBeVisible()
  await drawer.getByRole('link', { name: '查看全部任务' }).first().click()
  const detail = page.getByTestId('employee-detail-page')
  await expect(detail).toBeVisible()
  await expect(detail.getByRole('heading', { name: '当前工作' })).toBeVisible()
  await expect(detail).toContainText('空闲')
  await expect(detail).not.toContainText('8h')
  await expect(detail.getByRole('heading', { name: '历史任务' })).toBeVisible()
})

test('数字员工列表就地启用停用与删除', async ({ page, request }) => {
  const suffix = Date.now()
  const employeeId = `astra-toggle-${suffix}`
  const employeeName = `启停删除员工 ${suffix}`
  const category = await (await request.get('/api/task-categories')).json()
  const reference = await (await request.get('/api/employees/astra-01')).json()
  const created = await request.post('/api/employees', {
    data: {
      id: employeeId, name: employeeName, role: '启停删除测试', task_types: ['REQUIREMENT'],
      category_ids: [category[0].id], auto_claim: false, auto_execute: false,
      execution_environment: {
        mode: 'LOCAL', name: '启停测试环境', opencode_path: 'opencode',
        opencode_server_port: reference.execution_environment.opencode_server_port,
        workspace_root: './workspaces',
      },
    },
  })
  expect(created.ok()).toBeTruthy()
  await page.goto('/employees')
  const row = page.locator('tr', { hasText: employeeName })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: `停用 ${employeeName}` }).click()
  await expect(row.getByRole('button', { name: `启用 ${employeeName}` })).toBeVisible()
  await row.getByRole('button', { name: `删除 ${employeeName}` }).click()
  const confirm = page.getByTestId('astra-confirm-dialog')
  await expect(confirm).toBeVisible()
  await confirm.getByRole('button', { name: '删除员工' }).click()
  await expect(page.locator('tr', { hasText: employeeName })).toHaveCount(0)
  expect((await request.get(`/api/employees/${employeeId}`)).status()).toBe(404)
})

test('任务详情进入原生 Workspace，无 Session 时显示空状态而非旧对话页', async ({ page }) => {
  await page.goto('/tasks/T-20260827-004')
  const detail = page.getByTestId('task-workspace')
  await expect(detail).toBeVisible()
  await expect(detail.getByRole('heading', { name: '排查任务列表时间筛选异常' })).toBeVisible()
  // 演示任务没有真实 OpenCode Session：详情显示空状态，不再渲染旧对话/产出验收 UI。
  await expect(detail.getByText('任务尚未创建 Session，请先启动任务。')).toBeVisible()
  await expect(detail.locator('.conversation-scroller')).toHaveCount(0)
  await expect(detail.getByRole('link', { name: '查看运行详情' })).toHaveCount(0)
  // 任务信息面板展示业务事实与验收标准。
  await detail.getByRole('button', { name: '任务信息' }).click()
  await expect(detail.getByText('跨天时间范围返回完整结果')).toBeVisible()
})

test('业务枚举与时间单位统一显示为中文', async ({ page }) => {
  const rawEnums = /\b(?:READY|RUNNING|WAIT_HUMAN|WAITING_INPUT|SUSPENDED|PENDING_CONFIRMATION|EXECUTION_ERROR|COMPLETED|FAILED|CANCELLED|PASSED|BLOCKED|AVAILABLE|CHECKING|UNAVAILABLE|UNKNOWN|WORKING|IDLE|OFFLINE|ERROR|VERY_HIGH|HIGH|MEDIUM|LOW|ISSUE|REQUIREMENT|SATISFIED|UNSATISFIED|UNCONFIRMED)\b/
  for (const route of ['/tasks', '/tasks/T-20260827-003', '/employees', '/employees/astra-01', '/interventions', '/settings']) {
    await page.goto(route)
    await expect(page.locator('body')).not.toContainText(rawEnums)
  }
  // 时间单位以中文呈现（员工详情的运行时长汇总）。
  await page.goto('/employees/astra-01')
  await expect(page.getByText('今日工作时长')).toBeVisible()
  await expect(page.locator('.app-main')).toContainText(/分钟|小时|秒/)
})

test('数字员工页面内编辑：只管理工作范围、工作环境和简单策略', async ({ page }) => {
  await page.goto('/employees?edit=astra-01')
  const modal = page.getByTestId('employee-config-modal')
  await expect(modal).toBeVisible()
  await modal.getByRole('button', { name: '工作范围' }).click()
  await expect(modal.getByText('支持任务类型')).toBeVisible()
  await expect(modal.getByText('支持任务分类')).toBeVisible()
  await expect(modal.getByText('能力标签')).toHaveCount(0)
  await expect(modal.getByText('技能标签')).toHaveCount(0)
  await modal.getByRole('button', { name: '工作环境' }).click()
  await expect(modal.getByLabel('工作空间', { exact: true })).toHaveValue('./workspaces/astra-01')
  await expect(modal.getByLabel('Agent 模型', { exact: true })).toHaveValue('deepseek/deepseek-v4-flash')
})

test('配置保存保持工作环境可用且基本信息保存不改变环境状态', async ({ page, request }) => {
  const suffix = Date.now()
  const employeeId = `astra-inquiry-${suffix}`
  const employeeName = `询问测试员工 ${suffix}`
  const opencodeServerPort = await freePort()
  const createEmployee = await request.post('/api/employees', {
    data: {
      id: employeeId,
      name: employeeName,
      role: '询问场景自动化员工',
      description: '创建后等待配置中心保存验证',
      task_types: ['REQUIREMENT'],
      category_ids: ['testing-platform'],
      enabled: true,
      auto_claim: true,
      auto_execute: true,
      execution_environment: {
        mode: 'LOCAL',
        name: '隔离 Agent 工作环境',
        description: '系统级 E2E',
        port: 22,
        opencode_server_port: opencodeServerPort,
        opencode_path: 'opencode',
        model_name: 'e2e/original-model',
        workspace_root: process.env.E2E_EMPLOYEE_WORKSPACE ?? './workspaces',
        labels: [],
      },
    },
  })
  expect(createEmployee.ok()).toBeTruthy()
  const checked = await request.post(`/api/employees/${employeeId}/environment/test`)
  expect(checked.ok()).toBeTruthy()
  expect((await checked.json()).status).toBe('AVAILABLE')

  await page.goto(`/employees?edit=${employeeId}`)
  const modal = page.getByTestId('employee-config-modal')
  await expect(modal).toBeVisible()
  await modal.getByRole('button', { name: '工作环境' }).click()
  await expect(modal.getByLabel('Agent 模型', { exact: true })).toHaveValue('e2e/original-model')
  await modal.getByLabel('Agent 模型', { exact: true }).fill('deepseek/deepseek-v4-flash')
  await modal.getByRole('button', { name: '保存', exact: true }).click()
  await expect(modal).toBeHidden()

  await page.goto(`/employees?edit=${employeeId}`)
  await expect(modal).toBeVisible()
  await modal.getByRole('button', { name: '基本信息' }).click()
  await modal.getByRole('textbox', { name: '说明', exact: true }).fill('配置中心保存已经通过自动化验证')
  await modal.getByRole('button', { name: '保存', exact: true }).click()
  await expect(modal).toBeHidden()

  const afterSave = await request.get(`/api/employees/${employeeId}`)
  expect(afterSave.ok()).toBeTruthy()
  const savedEmployee = await afterSave.json()
  expect(savedEmployee.description).toBe('配置中心保存已经通过自动化验证')
  expect(savedEmployee.execution_environment.status).toBe('AVAILABLE')
  expect(savedEmployee.execution_environment.model_name).toBe('deepseek/deepseek-v4-flash')
})