import { expect, test } from '@playwright/test'

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
  for (const label of ['首页', '数字员工', '任务管理', '数字图书馆', '任务记录', '设置']) {
    await expect(navigation.getByRole('link', { name: new RegExp(label) })).toBeVisible()
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
  await expect(page.getByLabel('员工状态')).toHaveValue('WORKING')
})

test('核心页面可从中文主导航访问', async ({ page }) => {
  await page.goto('/')
  const navigation = page.getByRole('navigation', { name: '主导航' })
  const destinations = [
    { link: /^数字员工/, testId: 'employee-list-page', heading: '数字员工' },
    { link: /^任务管理$/, testId: 'task-list-page', heading: '任务管理' },
    { link: /^任务记录$/, testId: 'run-list-page', heading: '任务记录' },
    { link: /^数字图书馆/, testId: 'digital-library-page', heading: '数字图书馆' },
    { link: /^设置$/, testId: 'settings-page', heading: '配置中心' },
  ]
  for (const destination of destinations) {
    await navigation.getByRole('link', { name: destination.link }).click()
    const content = page.getByTestId(destination.testId)
    await expect(content).toBeVisible()
    await expect(content.getByRole('heading', { name: destination.heading, level: 2 })).toBeVisible()
  }
})

test('数字图书馆支持全局搜索、安全 Markdown 弹框和滚动恢复', async ({ page, request }) => {
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
  await library.getByLabel('知识库搜索').fill('50004')
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

test('数字图书馆兼容平铺空间响应且目录菜单只在点击后出现', async ({ page }) => {
  await page.route('**/api/library/spaces', async (route) => {
    const response = await route.fetch()
    const spaces = await response.json()
    const flatSpaces = spaces.map(({ children: _children, subtree_knowledge_count: _count, ...space }: Record<string, unknown>) => space)
    await route.fulfill({ response, json: flatSpaces })
  })
  await page.route('**/api/library/knowledge/*/usages*', (route) => route.fulfill({
    status: 404,
    json: { detail: 'Not Found' },
  }))

  await page.goto('/library')
  const library = page.getByTestId('digital-library-page')
  await expect(library.getByText('公共知识库', { exact: true })).toBeVisible()
  await expect(library.locator('.library-error')).toHaveCount(0)
  await expect(library.getByText('新建子目录', { exact: true })).toHaveCount(0)

  await library.locator('.knowledge-table-wrap tbody tr').first().click()
  const detail = page.getByTestId('knowledge-detail-dialog')
  await expect(detail).toBeVisible()
  await expect(detail.locator('.detail-error')).toHaveCount(0)
  await detail.getByRole('button', { name: '关闭知识详情' }).click()

  await library.getByRole('button', { name: '更多目录操作' }).first().click()
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
  await expect(library.getByRole('button', { name: '更多目录操作' })).toHaveCount(0)
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
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  await expect(page.getByText('等待领取', { exact: true }).first()).toBeVisible()
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
  await expect(page.getByRole('link', { name: '消息通知' }).locator('b')).toHaveText('3')
  await expect(pending.getByText('3 项待处理')).toBeVisible()
  await expect(pending.getByRole('button', { name: '全部 3' })).toBeVisible()
  await expect(pending.getByRole('button', { name: '已挂起 1' })).toBeVisible()

  await pending.getByRole('button', { name: /新增回调场景自动化覆盖/ }).click()
  await expect(pending.getByLabel('补充信息')).toBeVisible()
  await expect(pending.getByRole('button', { name: '补充并继续' })).toBeVisible()
  await expect(pending.getByRole('link', { name: '查看详情' })).toHaveAttribute('href', '/tasks/T-20260827-002')
})

test('员工管理使用列表、筛选分页并优先打开详情抽屉', async ({ page }) => {
  await page.goto('/employees')
  await expect(page.getByLabel('员工状态').getByRole('option', { name: '异常' })).toHaveCount(1)
  await expect(page.getByLabel('数字员工列表').getByRole('table')).toBeVisible()
  await expect(page.getByLabel('员工列表分页')).toBeVisible()
  await page.getByRole('button', { name: '查看 员工-01' }).click()
  const drawer = page.getByRole('dialog', { name: '员工-01 员工详情' })
  await expect(drawer).toBeVisible()
  await drawer.getByRole('link', { name: '完整记录' }).click()
  const detail = page.getByTestId('employee-detail-page')
  await expect(detail).toBeVisible()
  await expect(detail.getByRole('heading', { name: '当前工作' })).toBeVisible()
  await expect(detail).toContainText('session-task-001')
  await expect(detail).not.toContainText('8h')
  await expect(detail.getByRole('heading', { name: '历史任务' })).toBeVisible()
  await expect(detail.getByText('暂无历史任务')).toBeVisible()
})

test('任务记录列表可进入 Run 与任务详情', async ({ page }) => {
  await page.goto('/runs')
  await expect(page.getByRole('link', { name: /RUN-DEMO-003/ })).toHaveAttribute('href', '/runs/RUN-DEMO-003')
  await expect(page.getByRole('link', { name: /完善接口变更防线告警信息/ })).toHaveAttribute('href', '/tasks/T-20260827-003')

  await page.getByRole('link', { name: /RUN-DEMO-003/ }).click()
  const detail = page.getByTestId('run-detail-page')
  await expect(detail).toBeVisible()
  await expect(detail.getByText('deepseek/deepseek-v4-flash')).toBeVisible()
  await expect(detail).toContainText('160.8K')
})

test('完成任务展示会话结果、产出验收和固定视口', async ({ page }) => {
  await page.goto('/tasks/T-20260827-003')
  const detail = page.getByTestId('task-detail-page')
  await expect(detail).toBeVisible()
  await expect(detail.getByText('告警已展示接口与来源信息')).toBeVisible()
  await expect(detail.getByText('相关检查均通过')).toBeVisible()
  await expect(detail.getByRole('heading', { name: '产出与验收' })).toBeVisible()
  await expect(detail).not.toContainText('160.8K')
  await expect(detail).not.toContainText('bash')
  await detail.locator('.conversation-scroller').evaluate((element) => {
    const viewport = element as HTMLElement
    viewport.style.flex = '0 0 160px'
    viewport.style.height = '160px'
    viewport.scrollTop = 0
    element.dispatchEvent(new Event('scroll'))
  })
  await expect(detail.getByRole('button', { name: '回到最新' })).toBeVisible()
  await expect(detail.getByLabel('给数字员工的指令')).toBeVisible()
  await detail.getByRole('button', { name: '回到最新' }).click()
  await expect(detail.getByRole('button', { name: '回到最新' })).toHaveCount(0)
  await expect(detail.getByRole('link', { name: '查看运行详情' })).toHaveAttribute('href', '/runs/RUN-DEMO-003')
  await expect(detail.getByText('Agent 工作记录', { exact: true })).toHaveCount(0)

  const viewportHeight = await page.evaluate(() => window.innerHeight)
  const workspaceBox = await detail.boundingBox()
  const mainBox = await detail.locator('.task-main').boundingBox()
  const sidebarBox = await detail.getByLabel('任务信息侧栏').boundingBox()
  const composerBox = await detail.locator('.task-composer').boundingBox()
  expect(workspaceBox?.height ?? Infinity).toBeLessThanOrEqual(viewportHeight)
  expect(Math.abs((mainBox?.y ?? Infinity) - (sidebarBox?.y ?? -Infinity))).toBeLessThanOrEqual(1)
  expect((composerBox?.y ?? Infinity) + (composerBox?.height ?? Infinity)).toBeLessThanOrEqual(viewportHeight + 1)

  await page.setViewportSize({ width: 760, height: 800 })
  await expect(detail.getByRole('button', { name: '打开任务信息' })).toBeVisible()
  await detail.getByRole('button', { name: '打开任务信息' }).click()
  await expect(detail.getByLabel('任务信息侧栏')).toBeVisible()
  await expect(detail.getByRole('heading', { name: '任务概要' })).toBeVisible()
})

test('业务枚举和时间单位统一显示为中文', async ({ page }) => {
  const rawEnums = /\b(?:READY|RUNNING|WAIT_HUMAN|WAITING_INPUT|SUSPENDED|PENDING_CONFIRMATION|EXECUTION_ERROR|COMPLETED|FAILED|CANCELLED|PASSED|BLOCKED|AVAILABLE|CHECKING|UNAVAILABLE|UNKNOWN|WORKING|IDLE|OFFLINE|ERROR|VERY_HIGH|HIGH|MEDIUM|LOW|ISSUE|REQUIREMENT|SATISFIED|UNSATISFIED|UNCONFIRMED)\b/
  for (const route of ['/tasks', '/tasks/T-20260827-003', '/employees', '/employees/astra-01', '/runs', '/runs/RUN-DEMO-003', '/interventions', '/settings']) {
    await page.goto(route)
    await expect(page.locator('body')).not.toContainText(rawEnums)
  }
  await page.goto('/runs/RUN-DEMO-003')
  await expect(page.getByText('36 分钟')).toBeVisible()
  await expect(page.getByText('18.4 秒')).toBeVisible()
  await expect(page.getByText('执行会话', { exact: true })).toBeVisible()
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
  await expect(settings.getByLabel('工作空间', { exact: true })).toHaveValue('./workspaces/astra-01')
  await expect(settings.getByLabel('Agent 模型', { exact: true })).toHaveValue('deepseek/deepseek-v4-flash')
})

test('配置保存保持环境可用且任务会话覆盖真实询问、恢复、追问与普通执行', async ({ page, request }) => {
  const suffix = Date.now()
  const employeeId = `astra-inquiry-${suffix}`
  const employeeName = `询问测试员工 ${suffix}`
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
      max_auto_retries: 1,
      execution_environment: {
        mode: 'LOCAL',
        name: '隔离 Agent 工作环境',
        description: '系统级 E2E',
        port: 22,
        opencode_path: 'opencode',
        model_name: 'e2e/original-model',
        workspace_root: `./workspaces/${employeeId}`,
        labels: [],
      },
    },
  })
  expect(createEmployee.ok()).toBeTruthy()
  const checked = await request.post(`/api/employees/${employeeId}/environment/test`)
  expect(checked.ok()).toBeTruthy()
  expect((await checked.json()).status).toBe('AVAILABLE')

  await page.goto(`/settings?employee=${employeeId}`)
  const settings = page.getByTestId('settings-page')
  const employeeButton = settings.locator('.settings-employee').filter({ hasText: employeeName })
  await expect(employeeButton).toContainText('空闲')
  await settings.getByRole('button', { name: '工作环境' }).click()
  await expect(settings.getByLabel('Agent 模型', { exact: true })).toHaveValue('e2e/original-model')
  await settings.getByLabel('Agent 模型', { exact: true }).fill('deepseek/deepseek-v4-flash')
  await settings.getByRole('button', { name: '保存配置' }).click()
  await expect(settings.getByText('配置已保存，工作环境检测正常。')).toBeVisible()

  await settings.getByRole('button', { name: '基本信息' }).click()
  await settings.getByRole('textbox', { name: '说明', exact: true }).fill('配置中心保存已经通过自动化验证')
  await settings.getByRole('button', { name: '保存配置' }).click()
  await expect(settings.getByText('配置已保存，工作环境状态保持不变。')).toBeVisible()

  const afterSave = await request.get(`/api/employees/${employeeId}`)
  expect(afterSave.ok()).toBeTruthy()
  const savedEmployee = await afterSave.json()
  expect(savedEmployee.description).toBe('配置中心保存已经通过自动化验证')
  expect(savedEmployee.execution_environment.status).toBe('AVAILABLE')
  expect(savedEmployee.execution_environment.model_name).toBe('deepseek/deepseek-v4-flash')

  await page.goto('/tasks')
  await page.getByRole('button', { name: '创建任务', exact: true }).click()
  const modal = page.getByTestId('task-create-modal')
  const title = `E2E 询问场景 ${suffix}`
  await modal.getByLabel('任务标题 *').fill(title)
  await modal.getByLabel('任务类型 *').selectOption('REQUIREMENT')
  await modal.getByLabel('任务分类 *').selectOption('testing-platform')
  await modal.getByLabel('任务描述 *').fill('先向使用者询问要打印的答案，收到回答后打印该答案。')
  await modal.getByPlaceholder('验收标准 1').fill('打印使用者回答的具体答案')
  await modal.getByLabel('分配方式', { exact: true }).selectOption(employeeId)
  await modal.getByRole('button', { name: '创建任务', exact: true }).click()
  await page.waitForURL(/\/tasks\/T-[A-Z0-9-]+$/)
  const taskId = new URL(page.url()).pathname.split('/').at(-1)!

  await expect.poll(async () => {
    const response = await request.get(`/api/tasks/${taskId}`)
    return (await response.json()).status
  }, { timeout: 30_000 }).toBe('WAIT_HUMAN')

  const waitingWorkspaceResponse = await request.get(`/api/tasks/${taskId}/workspace`)
  const waitingWorkspace = await waitingWorkspaceResponse.json()
  const sessionId = waitingWorkspace.session.id
  expect(waitingWorkspace.task.status).toBe('WAIT_HUMAN')
  expect(waitingWorkspace.session.status).toBe('WAITING_INPUT')
  expect(waitingWorkspace.runs).toHaveLength(1)
  expect(waitingWorkspace.runs[0].status).toBe('WAITING_INPUT')
  expect(waitingWorkspace.inquiries).toHaveLength(1)
  expect(waitingWorkspace.inquiries[0].status).toBe('OPEN')
  expect(waitingWorkspace.inquiries[0].run_id).toBe(waitingWorkspace.runs[0].id)
  const waitingEmployee = await (await request.get(`/api/employees/${employeeId}`)).json()
  expect(waitingEmployee.status).toBe('WAIT_HUMAN')

  const detail = page.getByTestId('task-detail-page')
  await expect(detail.getByLabel('任务对话').getByText('先向使用者询问要打印的答案，收到回答后打印该答案。')).toBeVisible()
  await expect(detail.getByText('请告诉我这次需要打印的具体答案是什么？', { exact: true })).toBeVisible()
  await expect(detail.getByText('等待人工输入', { exact: true }).first()).toBeVisible()
  await expect(detail.getByText('运行元数据已更新')).toHaveCount(0)
  await expect(detail.getByText('模型用量')).toHaveCount(0)
  await detail.getByLabel('给数字员工的指令').fill('自动化验收答案')
  await detail.getByRole('button', { name: '发送指令' }).click()
  await expect(detail.getByText('回答已提交，数字员工将继续执行。')).toBeVisible()

  await expect.poll(async () => {
    const response = await request.get(`/api/tasks/${taskId}`)
    return (await response.json()).status
  }, { timeout: 30_000 }).toBe('COMPLETED')

  const completedResponse = await request.get(`/api/tasks/${taskId}`)
  const completed = await completedResponse.json()
  expect(completed.human_intervention.response).toBe('自动化验收答案')
  expect(completed.result.summary).toContain('已打印用户答案：自动化验收答案')
  expect(completed.result.acceptance_results[0].status).toBe('SATISFIED')

  const runsResponse = await request.get(`/api/tasks/${taskId}/runs`)
  const runs = await runsResponse.json()
  expect(runs).toHaveLength(1)
  expect(runs[0].status).toBe('COMPLETED')
  expect(new Set(runs.map((run: { opencode_session_id: string }) => run.opencode_session_id))).toEqual(new Set(['ses_e2e_fixture']))

  const completedWorkspace = await (await request.get(`/api/tasks/${taskId}/workspace`)).json()
  expect(completedWorkspace.session.id).toBe(sessionId)
  expect(completedWorkspace.session.status).toBe('COMPLETED')
  expect(completedWorkspace.inquiries[0].status).toBe('ANSWERED')
  const completedEmployee = await (await request.get(`/api/employees/${employeeId}`)).json()
  expect(completedEmployee.status).toBe('IDLE')

  await page.reload()
  await expect(detail.getByRole('paragraph').filter({ hasText: '已打印用户答案：自动化验收答案' })).toBeVisible()
  await expect(detail.getByText('打印使用者回答的具体答案').first()).toBeVisible()
  await expect(detail.getByText('1/1 通过').first()).toBeVisible()
  await expect(detail.getByRole('link', { name: '查看运行详情' })).toBeVisible()
  await expect(detail.getByText('运行信息', { exact: true })).toHaveCount(0)

  await detail.getByLabel('给数字员工的指令').fill('请在同一任务中再次打印自动化验收答案')
  await detail.getByRole('button', { name: '发送指令' }).click()
  await expect.poll(async () => {
    const response = await request.get(`/api/tasks/${taskId}/workspace`)
    return (await response.json()).runs.length
  }, { timeout: 30_000 }).toBe(2)
  await expect.poll(async () => {
    const response = await request.get(`/api/tasks/${taskId}/workspace`)
    const workspace = await response.json()
    return `${workspace.task.status}:${workspace.runs[0].status}`
  }, { timeout: 30_000 }).toBe('COMPLETED:COMPLETED')
  const followedUp = await (await request.get(`/api/tasks/${taskId}/workspace`)).json()
  expect(followedUp.session.id).toBe(sessionId)
  expect(followedUp.runs).toHaveLength(2)
  expect(followedUp.runs.every((run: { status: string }) => run.status === 'COMPLETED')).toBeTruthy()

  const ordinaryResponse = await request.post('/api/tasks', {
    data: {
      source: 'manual',
      task_type: 'REQUIREMENT',
      category_id: 'testing-platform',
      title: `E2E 普通任务 ${suffix}`,
      description: '直接完成一个普通任务，不需要询问使用者。',
      acceptance_criteria: [{ content: '普通任务成功完成' }],
      attachments: [],
      priority: 'MEDIUM',
      completion_policy: 'AUTO',
      employee_id: employeeId,
    },
  })
  expect(ordinaryResponse.ok()).toBeTruthy()
  const ordinaryTask = await ordinaryResponse.json()
  await expect.poll(async () => {
    const response = await request.get(`/api/tasks/${ordinaryTask.id}`)
    return (await response.json()).status
  }, { timeout: 30_000 }).toBe('COMPLETED')
  const ordinaryWorkspace = await (await request.get(`/api/tasks/${ordinaryTask.id}/workspace`)).json()
  expect(ordinaryWorkspace.inquiries).toHaveLength(0)
  expect(ordinaryWorkspace.runs).toHaveLength(1)
  expect(ordinaryWorkspace.runs[0].status).toBe('COMPLETED')
  expect(ordinaryWorkspace.messages[0].content).toBe('直接完成一个普通任务，不需要询问使用者。')
  expect(ordinaryWorkspace.messages.some((message: { role: string }) => message.role === 'agent')).toBeTruthy()

  const subagentResponse = await request.post('/api/tasks', {
    data: {
      source: 'manual',
      task_type: 'REQUIREMENT',
      category_id: 'testing-platform',
      title: `E2E Subagent 场景 ${suffix}`,
      description: 'E2E Subagent 场景：通过 Task Tool 启动 general 子 Agent。',
      acceptance_criteria: [{ content: '结构化 Subagent 事件进入任务会话' }],
      attachments: [],
      priority: 'MEDIUM',
      completion_policy: 'AUTO',
      employee_id: employeeId,
    },
  })
  expect(subagentResponse.ok()).toBeTruthy()
  const subagentTask = await subagentResponse.json()
  await expect.poll(async () => {
    const response = await request.get(`/api/tasks/${subagentTask.id}`)
    return (await response.json()).status
  }, { timeout: 30_000 }).toBe('COMPLETED')
  const subagentWorkspace = await (await request.get(`/api/tasks/${subagentTask.id}/workspace`)).json()
  const subagentEvents = subagentWorkspace.events.filter((event: { event_type: string }) => event.event_type.startsWith('subagent.'))
  expect(subagentEvents).toHaveLength(1)
  expect(subagentEvents[0]).toMatchObject({
    event_type: 'subagent.completed',
    agent_name: 'general',
    payload: {
      source_call_id: 'call-e2e-subagent',
      parent_session_id: 'ses_e2e_fixture',
      child_session_id: 'ses_e2e_child',
    },
  })
  expect(subagentWorkspace.blocks.some((block: { semantic_type: string; visibility: string }) => block.semantic_type === 'subagent.completed' && block.visibility === 'primary')).toBeTruthy()

  await page.goto(`/tasks/${subagentTask.id}`)
  const subagentDetail = page.getByTestId('task-detail-page')
  await expect(subagentDetail.getByRole('heading', { name: '协作成员' })).toBeVisible()
  const subtask = subagentDetail.getByRole('button', { name: /子任务 general.*Print hello world.*已完成/ })
  await expect(subtask).toBeVisible()
  await expect(subtask).toHaveAttribute('aria-expanded', 'false')
  await subtask.click()
  await expect(subtask).toHaveAttribute('aria-expanded', 'true')
  await expect(subagentDetail.getByText('打印 hello world', { exact: true })).toHaveCount(0)
  await expect(subagentDetail).not.toContainText('员工工作空间：')
  await expect(subagentDetail).not.toContainText('当前任务：')
  await expect(subagentDetail.getByText('当前事件中未发现 Subagent 调用')).toHaveCount(0)
})
