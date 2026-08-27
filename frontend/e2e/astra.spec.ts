import { expect, test } from '@playwright/test'

test('总览展示数字办公室、真实指标和员工工作现场', async ({ page }) => {
  await page.goto('/')
  const dashboard = page.getByTestId('dashboard-page')
  await expect(dashboard).toBeVisible()
  await expect(dashboard.getByRole('heading', { name: '总览', level: 2 })).toBeVisible()
  await expect(page.getByTestId('dashboard-v03-metrics')).toContainText('工作中')
  await expect(dashboard.getByRole('heading', { name: '数字办公室' })).toBeVisible()
  await expect(dashboard.getByRole('heading', { name: '测试平台开发区', level: 3 })).toBeVisible()
  await expect(dashboard.getByRole('heading', { name: '自动化区', level: 3 })).toBeVisible()
  await expect(dashboard.getByRole('heading', { name: '防线运营区', level: 3 })).toBeVisible()
  const workstation = dashboard.getByRole('button', { name: /Astra-01 测试平台开发/ })
  await expect(workstation.locator('.employee-portrait')).toBeVisible()
  await expect(workstation).toContainText('正在专注工作')
  await expect(workstation).toContainText('今日完成')
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
  await expect(detail.getByText('Agent 工作记录')).toBeVisible()
})

test('业务枚举和时间单位统一显示为中文', async ({ page }) => {
  const rawEnums = /\b(?:READY|RUNNING|WAIT_HUMAN|SUSPENDED|PENDING_CONFIRMATION|EXECUTION_ERROR|COMPLETED|FAILED|CANCELLED|PASSED|BLOCKED|AVAILABLE|CHECKING|UNAVAILABLE|UNKNOWN|WORKING|IDLE|OFFLINE|ERROR|VERY_HIGH|HIGH|MEDIUM|LOW|ISSUE|REQUIREMENT|SATISFIED|UNSATISFIED|UNCONFIRMED)\b/
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
  await expect(settings.getByLabel('工作空间')).toHaveValue('./workspaces/astra-01')
  await expect(settings.getByLabel('Agent 模型')).toHaveValue('deepseek/deepseek-v4-flash')
})

test('配置保存保持环境可用且询问任务可由真实运行时等待并继续完成', async ({ page, request }) => {
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
        auth_method: 'SSH_AGENT',
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
  await expect(settings.getByLabel('Agent 模型')).toHaveValue('e2e/original-model')
  await settings.getByLabel('Agent 模型').fill('deepseek/deepseek-v4-flash')
  await settings.getByRole('button', { name: '保存配置' }).click()
  await expect(settings.getByText('配置已保存，工作环境检测正常。')).toBeVisible()

  await settings.getByRole('button', { name: '基本信息' }).click()
  await settings.getByLabel('说明').fill('配置中心保存已经通过自动化验证')
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
  await modal.getByLabel('分配方式').selectOption(employeeId)
  await modal.getByRole('button', { name: '创建任务', exact: true }).click()
  await page.waitForURL(/\/tasks\/T-[A-Z0-9-]+$/)
  const taskId = new URL(page.url()).pathname.split('/').at(-1)!

  await expect.poll(async () => {
    const response = await request.get(`/api/tasks/${taskId}`)
    return (await response.json()).status
  }, { timeout: 30_000 }).toBe('WAIT_HUMAN')

  await page.goto('/interventions')
  const intervention = page.getByTestId('intervention-page')
  await intervention.getByRole('button', { name: new RegExp(title) }).click()
  await expect(intervention.getByText('请告诉我这次需要打印的具体答案是什么？')).toBeVisible()
  await intervention.getByLabel('补充信息').fill('自动化验收答案')
  await intervention.getByRole('button', { name: '补充并继续' }).click()

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
  expect(runs).toHaveLength(2)
  expect(runs.map((run: { status: string }) => run.status).sort()).toEqual(['BLOCKED', 'PASSED'])
  expect(new Set(runs.map((run: { opencode_session_id: string }) => run.opencode_session_id))).toEqual(new Set(['ses_e2e_fixture']))

  await page.goto(`/tasks/${taskId}`)
  const detail = page.getByTestId('task-detail-page')
  await expect(detail.getByRole('paragraph').filter({ hasText: '已打印用户答案：自动化验收答案' })).toBeVisible()
  await expect(detail.getByText('满足 · 已按使用者回答打印自动化验收答案')).toBeVisible()
})
